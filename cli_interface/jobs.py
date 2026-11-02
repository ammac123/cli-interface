"""
Job model and runner. ``JobManager`` runs every menu action as a job on one of three lanes
(inline on the UI thread, a daemon thread, or a Task on the UI loop), with hooks, ``stop``,
quit and abandonment, and the ``mark`` / ``wait_idle`` / ``wait_until`` test hooks.

The manager belongs to the UI thread; only job bodies and ``Context`` run elsewhere.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
import itertools
import logging
import re
import sys
import threading
import time
import types
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ForwardRef, Literal, Protocol, Union, get_args, get_origin

from .capture import CAPTURE, JobCapture
from .context import Context, JobCancelled, JobEmitter, JobHost
from .events import Event, EventSink, make_log, make_progress, make_result
from .menu import MenuItem, _CommandItem, item_label
from .outcome import exception_event, value_events

if TYPE_CHECKING:
    from .display import DisplayPanel

_log = logging.getLogger(__name__)

Lane = Literal["inline", "thread", "loop"]
HookKind = Literal["startup", "shutdown", "before", "after"]
Outcome = Literal["ok", "error", "cancelled", "abandoned"]
ManagerState = Literal["idle", "running", "cancelling"]

_Result = tuple[bool, Any]


class ManagerHost(JobHost, Protocol):
    """What ``JobManager`` needs from the app, on top of ``JobHost``."""

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None: ...

    def panel_for(self, emitter: EventSink) -> DisplayPanel: ...

    def spinner_acquire(self, label: str) -> int: ...

    def spinner_release(self, token: int) -> None: ...

    def job_changed(self, job: Job | None) -> None: ...

    def flush_inbox(self) -> None: ...

    def request_exit(self, result: Any, return_code: int, message: str | None) -> None: ...


@dataclass
class JobSpec:
    label: str
    fn: Callable[..., Any]
    path: tuple[str, ...] = ()
    value: str | None = field(default=None, repr=False)
    secret: bool = False
    cancellable: bool = False
    kind: Literal["command", "startup", "shutdown"] = "command"
    threaded: bool = False


def spec_from_item(item: MenuItem, value: str | None, path: tuple[str, ...]) -> JobSpec:
    """
    The spec for running ``item``. The label is read now, before the action can change it.
    ``path`` is stored as given; when empty, a command item's ``command_path`` is used.
    A command item runs on a thread even if its function does not ask for a ``Context``.
    """
    if item.action is None:
        raise ValueError("menu item has no action")
    command = item if isinstance(item, _CommandItem) else None
    return JobSpec(
        label=item_label(item),
        fn=item.action,
        path=tuple(path) or (command.command_path if command else ()),
        value=value,
        secret=item.secret,
        cancellable=command.cancellable if command else False,
        threaded=command is not None,
    )


# ----------------------------------------------------------------------
# Call binding and lanes

_P = inspect.Parameter


def _signature(fn: Callable[..., Any]) -> inspect.Signature | None:
    try:
        return inspect.signature(fn, eval_str=True)
    except Exception:
        pass
    try:
        return inspect.signature(fn)
    except Exception:
        return None


_MAX_NESTING = 32
_WRAPPER = re.compile(r"(?:\w+\.)*(?:Optional|Union)\[(.*)\]", re.S)


def _split_top(text: str, sep: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for char in text:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        if depth == 0 and char == sep:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def _text_is_context(text: str, depth: int = 0) -> bool:
    if depth > _MAX_NESTING:
        return False
    text = text.strip().strip("'\"").strip()
    parts = _split_top(text, "|")
    if len(parts) > 1:
        return any(_text_is_context(part, depth + 1) for part in parts)
    match = _WRAPPER.fullmatch(text)
    if match:
        return any(_text_is_context(part, depth + 1) for part in _split_top(match.group(1), ","))
    return text == "Context" or text.endswith(".Context")


def _is_context_annotation(annotation: Any) -> bool:
    if isinstance(annotation, str):
        return _text_is_context(annotation)
    if isinstance(annotation, ForwardRef):
        return _text_is_context(annotation.__forward_arg__)
    if get_origin(annotation) in (Union, types.UnionType):
        return any(_is_context_annotation(arg) for arg in get_args(annotation))
    try:
        return isinstance(annotation, type) and issubclass(annotation, Context)
    except TypeError:
        return False


def _asks_context(param: inspect.Parameter) -> bool:
    if param.kind not in (_P.POSITIONAL_ONLY, _P.POSITIONAL_OR_KEYWORD, _P.KEYWORD_ONLY):
        return False
    if param.annotation is _P.empty:
        return param.name in ("ctx", "context")
    try:
        return _is_context_annotation(param.annotation)
    except RecursionError:
        return False


def wants_context(fn: Callable[..., Any]) -> bool:
    """True if ``fn`` has a parameter that asks for the ``Context`` (see ``bind_call``)."""
    sig = _signature(fn)
    return sig is not None and any(_asks_context(p) for p in sig.parameters.values())


def bind_call(fn: Callable[..., Any], ctx: Any, value: str | None) -> tuple[tuple[Any, ...], dict[str, Any]]:
    """
    Arguments for ``fn``, in parameter order: ``ctx`` goes in its own slot (by keyword if
    keyword-only) and the prompt ``value``, if not None, to the first other positional slot.
    A callable with no usable signature gets just the value, positionally.
    """
    pending = value is not None
    sig = _signature(fn)
    if sig is None:
        return ((value,) if pending else ()), {}
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    gap = False
    for param in sig.parameters.values():
        if param.kind is _P.KEYWORD_ONLY:
            if _asks_context(param):
                kwargs[param.name] = ctx
        elif param.kind is _P.VAR_POSITIONAL:
            if pending and not gap:
                args.append(value)
                pending = False
        elif param.kind in (_P.POSITIONAL_ONLY, _P.POSITIONAL_OR_KEYWORD):
            if _asks_context(param):
                if gap:
                    kwargs[param.name] = ctx
                else:
                    args.append(ctx)
            elif pending and not gap:
                args.append(value)
                pending = False
            else:
                gap = True
    if pending and not gap:
        args.append(value)
    return tuple(args), kwargs


def _hook_binding(fn: Callable[..., Any], ctx: Any) -> tuple[tuple[Any, ...], dict[str, Any]]:
    sig = _signature(fn)
    if sig is not None and not wants_context(fn):
        required = [
            p for p in sig.parameters.values()
            if p.kind in (_P.POSITIONAL_ONLY, _P.POSITIONAL_OR_KEYWORD) and p.default is _P.empty
        ]
        if required:
            return (ctx,), {}
    return bind_call(fn, ctx, None)


def _is_async(fn: Callable[..., Any]) -> bool:
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(type(fn).__call__)


def choose_lane(spec: JobSpec, fn: Callable[..., Any]) -> Lane:
    """``loop`` for an async function, ``thread`` for a command or a ``Context``-taker, else ``inline``."""
    if _is_async(fn):
        return "loop"
    if spec.threaded or spec.kind != "command" or wants_context(fn):
        return "thread"
    return "inline"


# ----------------------------------------------------------------------
# Spinner

class SpinnerRefs:
    """Counted spinner holders (UI thread only); ``label`` is that of the newest holder."""

    def __init__(self) -> None:
        self._held: dict[int, str] = {}
        self._next = 1

    def acquire(self, label: str = "") -> int:
        token = self._next
        self._next += 1
        self._held[token] = label
        return token

    def release(self, token: int) -> bool:
        return self._held.pop(token, None) is not None

    @property
    def count(self) -> int:
        return len(self._held)

    @property
    def label(self) -> str | None:
        return self._held[max(self._held)] if self._held else None


# ----------------------------------------------------------------------
# Job

@dataclass
class _Step:
    phase: str
    call: Callable[[], Any]
    lane: Lane
    suffix: str = ""


class Job:
    """
    One run of an action, reached as ``Context.job`` and ``CLIApp.jobs.current``. Consumers read
    it; only ``JobManager`` changes it. Internal type (not exported), but these attributes are
    stable: ``id``, ``label`` (read before the action ran), ``path`` (the command path, or ``()``),
    ``kind`` (``"command"``, ``"startup"`` or ``"shutdown"``), ``lane`` (``"inline"``, ``"thread"``
    or ``"loop"``), ``cancellable``, ``cancelled`` (a ``threading.Event``), ``state``
    (``"running"``, ``"cancelling"`` or ``"done"``), ``outcome`` (``None`` while running, then
    ``"ok"``, ``"error"``, ``"cancelled"`` or ``"abandoned"``), ``error`` (the message of the
    exception, if it failed), ``started``, ``ended`` (epoch seconds) and ``abandoned``.
    """

    def __init__(self, job_id: int, spec: JobSpec, lane: Lane) -> None:
        self.id = job_id
        self.label = spec.label
        self.path = spec.path
        self.kind = spec.kind
        self.lane = lane
        self.cancellable = spec.cancellable
        self.cancelled = threading.Event()
        self.state: Literal["running", "cancelling", "done"] = "running"
        self.outcome: Outcome | None = None
        self.error: str | None = None
        self.started: float | None = None
        self.ended: float | None = None
        self.abandoned = False
        self._spec = spec
        self._secrets: tuple[str, ...] = ()
        self._hooks: tuple[Callable[..., Any], ...] = ()
        self._emitter: JobEmitter
        self._capture: JobCapture
        self._ctx: Context
        self._gen: Generator[_Step, _Result] | None = None
        self._task: asyncio.Task[None] | None = None
        self._stage_task: asyncio.Task[_Result] | None = None
        self._stage_fut: asyncio.Future[_Result] | None = None
        self._thread: threading.Thread | None = None
        self._thread_exited = True
        self._holds_capture = False
        self._lock = threading.Lock()
        self._spinner: int | None = None
        self._stop_asked = False
        self._cancel_stages = False
        self._stage_phase = ""
        self._finished = False

    def __repr__(self) -> str:
        return f"<Job #{self.id} {self.label!r} {self.state} outcome={self.outcome}>"


def _deliver(fut: asyncio.Future[_Result], result: _Result) -> None:
    if not fut.done():
        fut.set_result(result)


def _noop() -> None:
    return None


# ----------------------------------------------------------------------
# Manager

class JobManager:
    """
    Owns the one running job, the hooks, the quit sequence and the wait API; reached as
    ``CLIApp.jobs``. The consumer-facing surface is ``state`` / ``busy`` / ``current`` /
    ``completed`` (reads), ``request_cancel`` (what typed ``stop`` calls) and the test hooks
    ``mark``, ``wait_idle`` and ``wait_until``; ``submit``, ``begin_quit``, ``close`` and the
    rest belong to the app.
    """

    def __init__(self, host: ManagerHost, *, quit_grace: float = 2.0) -> None:
        self._host = host
        self._grace = quit_grace
        self._ids = itertools.count(1)
        self._hooks: dict[str, list[Callable[..., Any]]] = {
            "startup": [], "shutdown": [], "before": [], "after": [],
        }
        self._current: Job | None = None
        self._state: ManagerState = "idle"
        self._completed = 0
        self._waiters: list[asyncio.Future[None]] = []
        self._started = False
        self._closed = False
        self._quitting = False
        self._exited = False
        self._then: Callable[[], None] | None = None
        self._shutdown_queue: list[Callable[..., Any]] | None = None
        self._timer: asyncio.TimerHandle | None = None

    # -- reads

    @property
    def state(self) -> ManagerState:
        return self._state

    @property
    def busy(self) -> bool:
        return self._state != "idle"

    @property
    def current(self) -> Job | None:
        return self._current

    @property
    def completed(self) -> int:
        return self._completed

    def mark(self) -> int:
        """The ``completed`` counter now; pass it to ``wait_idle(since=...)``."""
        return self._completed

    # -- registration and start

    def add_hook(self, kind: HookKind, fn: Callable[..., Any]) -> None:
        """Register a hook; a non-callable is ignored. ``startup`` after ``start()`` raises ``RuntimeError``."""
        if kind not in self._hooks:
            raise ValueError(f"unknown hook kind: {kind!r}")
        if not callable(fn):
            return
        if kind == "startup" and self._started:
            raise RuntimeError("on_startup hooks must be registered before the app starts")
        self._hooks[kind].append(fn)

    def start(self) -> None:
        """Run the startup hooks as one job named ``startup``. The ``hello`` event is the host's."""
        if self._started or self._closed:
            return
        self._started = True
        hooks = tuple(self._hooks["startup"])
        if not hooks or self._host.loop is None or self._current is not None:
            return
        job = self._launch(JobSpec("startup", _noop, kind="startup"), "thread", hooks)
        self._begin(job)

    # -- submit and stop

    def ensure_idle(self) -> bool:
        """True if a job may start now. Otherwise the ``Busy:`` WARNING has been emitted and this is False."""
        if self._closed:
            return False
        if self._current is None and not (self._quitting or self._exited):
            return True
        job = self._current
        if job is None:
            text = "Busy: the app is exiting"
        elif job.state == "cancelling":
            text = f"Busy: {job.label} is stopping"
        else:
            text = f"Busy: {job.label} is running (type stop to stop it)"
        self._say(text, "WARNING")
        return False

    def submit(self, spec: JobSpec) -> Job | None:
        """Start a job. None if the manager is busy (the WARNING is emitted) or closed."""
        if not self.ensure_idle():
            return None
        lane = choose_lane(spec, spec.fn)
        if lane != "inline" and self._host.loop is None:
            return None
        job = self._launch(spec, lane)
        self._begin(job)
        return job

    def request_cancel(self, *, source: Literal["user", "quit"] = "user") -> None:
        """
        ``stop``: ask a cancellable job to stop; a second ``stop`` abandons it. A job that is not
        cancellable is only warned about first. ``source="quit"`` cancels any job without warnings.
        """
        job = self._current
        if job is None:
            if source == "user":
                self._say("Nothing is running", "INFO")
            return
        if source == "quit":
            self._cancel(job)
        elif job.state == "cancelling" or job._stop_asked:
            self._abandon(job)
        elif job.cancellable:
            self._cancel(job)
        else:
            job._stop_asked = True
            self._say(f"{job.label} cannot be stopped cleanly; type stop again to abandon it", "WARNING")

    def begin_quit(self, then: Callable[[], None]) -> None:
        """
        Stop the running job (waiting up to ``quit_grace``), run the shutdown hooks (each bounded by
        ``quit_grace``), then call ``then``. With nothing to wait for, ``then`` is called at once.
        A repeated call skips the wait that is in progress.
        """
        if self._closed:
            return
        if self._exited:
            then()
            return
        if self._quitting:
            self._escalate_quit()
            return
        job = self._current
        if job is None and not self._hooks["shutdown"]:
            then()
            return
        self._quitting = True
        self._then = then
        self._notify()
        if job is None:
            self._shutdown_queue = list(self._hooks["shutdown"])
            self._next_shutdown()
            return
        self._say(f"Stopping {job.label} (q + Enter again quits now)", "WARNING")
        self._cancel(job)
        self._arm_timer(job)

    def close(self) -> None:
        """Backstop for unmount: abandon the survivor quietly and wake the waiters. Never joins a thread."""
        if self._closed:
            return
        self._closed = True
        self._cancel_timer()
        self._then = None
        job = self._current
        if job is not None:
            self._abandon(job, quiet=True)
        self._notify()

    # -- waiting

    async def wait_until(
        self, predicate: Callable[[JobManager], bool], timeout: float | None = 10.0
    ) -> None:
        """Return once ``predicate(self)`` holds, re-checked at each state change; ``TimeoutError`` has a state dump."""
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout
        while True:
            if predicate(self):
                return
            if self._closed:
                raise RuntimeError("the job manager is closed")
            fut: asyncio.Future[None] = loop.create_future()
            self._waiters.append(fut)
            try:
                if deadline is None:
                    await fut
                else:
                    await asyncio.wait_for(fut, max(0.0, deadline - loop.time()))
            except TimeoutError:
                raise TimeoutError(f"timed out after {timeout}s: {self._dump()}") from None
            finally:
                if fut in self._waiters:
                    self._waiters.remove(fut)

    async def wait_idle(
        self, *, since: int | None = None, jobs: int = 0, timeout: float | None = 10.0
    ) -> None:
        """
        Return when ``jobs`` jobs have completed since ``since`` (a ``mark()``), nothing is running, no
        quit is in progress, and the host's inbox has been flushed.
        """
        base = since or 0

        def settled(manager: JobManager) -> bool:
            return manager._completed - base >= jobs and manager._state == "idle" and not manager._quitting

        while True:
            await self.wait_until(settled, timeout)
            self._call_host(self._host.flush_inbox)
            if settled(self):
                return

    # -- building and starting jobs

    def _launch(self, spec: JobSpec, lane: Lane, hooks: tuple[Callable[..., Any], ...] = ()) -> Job:
        host = self._host
        job = Job(next(self._ids), spec, lane)
        job._hooks = hooks
        job._secrets = (spec.value,) if spec.secret and spec.value else ()
        job._emitter = JobEmitter(host.emit, job.id, job._secrets, lambda: job.abandoned)
        job._capture = CAPTURE.open_job(job._emitter.emit, job.id)
        job._ctx = Context(job, host, host.panel_for(job._emitter), job._emitter)
        return job

    def _begin(self, job: Job) -> None:
        self._current = job
        self._state = "running"
        job.started = time.time()
        if job.lane != "inline":
            job._spinner = self._call_host(self._host.spinner_acquire, job.label)
        self._call_host(self._host.job_changed, job)
        self._notify()
        job._gen = self._plan(job)
        self._advance(job, job._gen)

    def _hook_step(self, job: Job, kind: str, index: int, fn: Callable[..., Any]) -> _Step:
        args, kwargs = _hook_binding(fn, job._ctx)
        lane: Lane = "loop" if _is_async(fn) else ("thread" if job.lane == "thread" else "inline")
        return _Step(kind, lambda: fn(*args, **kwargs), lane, f"{kind}{index}" if index else kind)

    def _plan(self, job: Job) -> Generator[_Step, _Result]:
        spec = job._spec
        ok: bool
        value: Any
        if spec.kind == "startup":
            for index, fn in enumerate(job._hooks, 1):
                ok, value = yield self._hook_step(job, "startup", index, fn)
                if not ok:
                    self._hook_failed(job, value, job.label)
            return
        if spec.kind == "shutdown":
            yield self._hook_step(job, "shutdown", 0, spec.fn)
            return
        before, after = tuple(self._hooks["before"]), tuple(self._hooks["after"])
        ok, value = True, None
        for index, fn in enumerate(before, 1):
            ok, value = yield self._hook_step(job, "before", index, fn)
            if not ok:
                break
        if ok and job.cancelled.is_set():
            ok, value = False, JobCancelled()
        if ok:
            args, kwargs = bind_call(spec.fn, job._ctx, spec.value)
            ok, value = yield _Step("body", lambda: spec.fn(*args, **kwargs), job.lane)
        if ok and inspect.isawaitable(value):
            pending = value
            ok, value = yield _Step("await", lambda: pending, "loop")
        self._conclude(job, ok, value)
        for index, fn in enumerate(after, 1):
            ok, value = yield self._hook_step(job, "after", index, fn)
            if not ok:
                self._hook_failed(job, value, f"{job.label} (after_command)")

    def _advance(self, job: Job, gen: Generator[_Step, _Result]) -> None:
        try:
            step = next(gen)
            while step.lane == "inline":
                step = gen.send(self._inline(job, step.call))
        except StopIteration:
            self._finish(job)
            return
        except Exception:
            self._internal_error(job)
            return
        loop = self._host.loop
        if loop is not None:
            coro = self._orchestrate(job, gen, step)
            try:
                job._task = loop.create_task(coro, name=f"cli-interface-job-{job.id}")
                return
            except RuntimeError:
                coro.close()
        self._abandon(job, quiet=True)

    async def _orchestrate(self, job: Job, gen: Generator[_Step, _Result], step: _Step) -> None:
        try:
            while True:
                result = await self._exec(job, step)
                step = gen.send(result)
        except StopIteration:
            self._finish(job)
        except asyncio.CancelledError:
            if not job._finished:
                self._abandon(job, quiet=True)
            raise
        except Exception:
            self._internal_error(job)

    def _internal_error(self, job: Job) -> None:
        _log.debug("job pipeline failed", exc_info=True)
        if job.outcome is None:
            job.outcome = "error"
        self._finish(job)

    # -- stage executors

    async def _exec(self, job: Job, step: _Step) -> _Result:
        if step.lane == "thread":
            return await self._stage_thread(job, step)
        if step.lane == "loop":
            return await self._stage_loop(job, step)
        return self._inline(job, step.call)

    @staticmethod
    def _guarded(job: Job, call: Callable[[], Any]) -> _Result:
        job._capture.activate()
        try:
            return True, call()
        except BaseException as exc:
            return False, exc
        finally:
            job._capture.flush()

    def _inline(self, job: Job, call: Callable[[], Any]) -> _Result:
        return contextvars.copy_context().run(self._guarded, job, call)

    async def _stage_thread(self, job: Job, step: _Step) -> _Result:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[_Result] = loop.create_future()
        job._stage_fut = fut
        name = f"cli-interface-job-{job.id}" + (f"-{step.suffix}" if step.suffix else "")
        thread = threading.Thread(
            target=self._thread_main,
            args=(job, loop, fut, contextvars.copy_context(), step.call),
            name=name,
            daemon=True,
        )
        with job._lock:
            job._thread = thread
            job._thread_exited = False
        try:
            thread.start()
        except RuntimeError as exc:
            self._thread_exit(job)
            _deliver(fut, (False, exc))
        try:
            return await fut
        finally:
            job._stage_fut = None

    def _thread_main(
        self,
        job: Job,
        loop: asyncio.AbstractEventLoop,
        fut: asyncio.Future[_Result],
        context: contextvars.Context,
        call: Callable[[], Any],
    ) -> None:
        try:
            try:
                result = context.run(self._guarded, job, call)
            except BaseException as exc:
                result = (False, exc)
            try:
                loop.call_soon_threadsafe(_deliver, fut, result)
            except RuntimeError:
                pass
        finally:
            self._thread_exit(job)

    @staticmethod
    def _thread_exit(job: Job) -> None:
        with job._lock:
            job._thread_exited = True
            release, job._holds_capture = job._holds_capture, False
        if release:
            CAPTURE.release()

    async def _stage_loop(self, job: Job, step: _Step) -> _Result:
        loop = asyncio.get_running_loop()

        async def run() -> _Result:
            job._capture.activate()
            try:
                value = step.call()
                if inspect.isawaitable(value):
                    value = await value
                return True, value
            except asyncio.CancelledError:
                raise
            except BaseException as exc:
                return False, exc
            finally:
                job._capture.flush()

        name = f"cli-interface-job-{job.id}" + (f"-{step.suffix}" if step.suffix else "")
        task = loop.create_task(run(), name=name)
        job._stage_task = task
        job._stage_phase = step.phase
        if job._cancel_stages and step.phase != "after":
            task.cancel()
        try:
            await asyncio.wait([task])
        except asyncio.CancelledError:
            task.cancel()
            raise
        finally:
            job._stage_task = None
        if task.cancelled():
            return False, asyncio.CancelledError()
        return task.result()

    # -- outcome

    def _emit_job(self, job: Job, event: Event) -> None:
        try:
            job._emitter.emit(event)
        except Exception:
            _log.debug("emitting a job event failed", exc_info=True)

    def _conclude(self, job: Job, ok: bool, value: Any) -> None:
        if ok:
            events, summary = value_events(value, secret=job._spec.secret)
            job.outcome = "ok"
            for event in events:
                self._emit_job(job, event)
            self._emit_job(job, make_result(job.label, summary=summary))
        elif isinstance(value, JobCancelled | asyncio.CancelledError):
            job.outcome = "cancelled"
            self._emit_job(job, make_result(job.label, status="cancelled"))
        else:
            exc = value if isinstance(value, BaseException) else RuntimeError(str(value))
            event = exception_event(exc, job.label, job._secrets)
            job.outcome = "error"
            job.error = event["message"]
            self._emit_job(job, event)

    def _hook_failed(self, job: Job, exc: Any, label: str) -> None:
        if isinstance(exc, JobCancelled | asyncio.CancelledError) or not isinstance(exc, BaseException):
            return
        self._emit_job(job, exception_event(exc, label, job._secrets))

    def _finish(self, job: Job, *, quiet: bool = False) -> None:
        if job._finished:
            return
        job._finished = True
        job._gen = None
        job.ended = time.time()
        job.state = "done"
        if job.outcome is None:
            job.outcome = "error"
        job._capture.close()
        self._cancel_timer()
        token, job._spinner = job._spinner, None
        if self._current is job:
            self._current = None
            self._state = "idle"
        self._completed += 1
        if not quiet:
            if token is not None:
                self._call_host(self._host.spinner_release, token)
            self._call_host(self._host.job_changed, None)
        self._notify()
        if self._quitting and not self._closed:
            self._quit_continue(job)

    # -- cancel, abandon, quit

    def _cancel(self, job: Job) -> None:
        if job.state != "running":
            return
        job.state = "cancelling"
        self._state = "cancelling"
        job.cancelled.set()
        job._cancel_stages = True
        if job._stage_task is not None and not job._stage_task.done() and job._stage_phase != "after":
            job._stage_task.cancel()
        self._emit_job(job, make_progress(id="status", label=f"Stopping {job.label} ..."))
        self._notify()

    def _abandon(self, job: Job, *, quiet: bool = False) -> None:
        if job._finished:
            return
        job.abandoned = True
        job.outcome = "abandoned"
        job.cancelled.set()
        job._capture.abandon()
        with job._lock:
            if job._thread is not None and not job._thread_exited:
                CAPTURE.acquire()
                job._holds_capture = True
        for handle in (job._stage_fut, job._stage_task, job._task):
            if handle is not None and not handle.done():
                handle.cancel()
        if job._gen is not None:
            try:
                job._gen.close()
            except ValueError:
                pass
        if not quiet:
            self._say(f"Abandoned: {job.label} (it did not stop; its output is now ignored)", "WARNING")
        self._finish(job, quiet=quiet)

    def _escalate_quit(self) -> None:
        self._shutdown_queue = []
        job = self._current
        if job is not None:
            self._abandon(job)
        else:
            self._next_shutdown()

    def _quit_continue(self, job: Job) -> None:
        if job.kind != "shutdown" and self._shutdown_queue is None:
            self._shutdown_queue = list(self._hooks["shutdown"])
        self._next_shutdown()

    def _next_shutdown(self) -> None:
        queue = self._shutdown_queue
        if queue:
            fn = queue.pop(0)
            job = self._launch(JobSpec("shutdown", fn, kind="shutdown"), "loop" if _is_async(fn) else "thread")
            self._begin(job)
            if not job._finished:
                self._arm_timer(job)
            return
        then, self._then = self._then, None
        self._quitting = False
        self._exited = True
        self._notify()
        if then is not None:
            then()

    def _arm_timer(self, job: Job) -> None:
        self._cancel_timer()
        loop = self._host.loop
        if loop is not None:
            self._timer = loop.call_later(self._grace, self._expire, job)

    def _expire(self, job: Job) -> None:
        self._timer = None
        if not job._finished:
            self._abandon(job)

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()

    # -- host and waiters

    def _call_host(self, fn: Callable[..., Any], *args: Any) -> Any:
        try:
            return fn(*args)
        except Exception:
            _log.debug("host call %s failed", getattr(fn, "__name__", fn), exc_info=True)
            return None

    def _say(self, text: str, level: str) -> None:
        self._call_host(self._host.emit, make_log(text, level))

    def _notify(self) -> None:
        waiters, self._waiters = self._waiters, []
        for fut in waiters:
            try:
                if not fut.done():
                    fut.set_result(None)
            except RuntimeError:
                pass

    def _dump(self) -> str:
        parts = [f"state={self._state}", f"completed={self._completed}", f"quitting={self._quitting}"]
        job = self._current
        if job is not None:
            parts.append(f"job={job.label!r} #{job.id} lane={job.lane} job_state={job.state}")
            thread = job._thread
            frame = sys._current_frames().get(thread.ident) if thread is not None and thread.ident else None
            if frame is not None:
                stack = []
                while frame is not None:
                    stack.append(f"{frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}")
                    frame = frame.f_back
                parts.append("thread stack (innermost first): " + " <- ".join(stack))
        return " ".join(parts)
