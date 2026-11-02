"""
Process-wide capture of ``print()`` and stderr output (``CAPTURE``): a refcounted proxy over
``sys.stdout``/``sys.stderr`` that turns writes made inside a job into ``text`` events.
"""
from __future__ import annotations

import io
import re
import sys
import threading
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, Literal, TextIO, cast

from .events import Event, make_text

_Stream = Literal["stdout", "stderr"]

_CAPTURE = "capture"
_SWALLOW = "swallow"
_IGNORE = "ignore"

_MAX_PARTIAL = 65_536

_ANSI = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\|$)"
    r"|\x1b[PX^_][^\x1b]*(?:\x1b\\|$)"
    r"|\x1b[ -/]*[0-~]"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

_JOB: ContextVar[JobCapture | None] = ContextVar("cli_interface_job", default=None)
_LOCAL = threading.local()


def _collapse_cr(text: str) -> str:
    if "\r" not in text:
        return text
    core = text.rstrip("\r")
    return core.rpartition("\r")[2] + text[len(core):]


def _clean(raw: str) -> str:
    return _CONTROL.sub("", _ANSI.sub("", _collapse_cr(raw).rstrip("\r")))


def _safe_emit(emit: Callable[[Event], None], event: Event) -> None:
    previous = getattr(_LOCAL, "busy", False)
    _LOCAL.busy = True
    try:
        emit(event)
    except Exception:
        pass
    finally:
        _LOCAL.busy = previous


class _Lines:
    """Line buffering shared by job capture and app-level routing."""

    def __init__(self, emit: Callable[[Event], None], job_id: int | None) -> None:
        self._emit = emit
        self._job_id = job_id
        self._lock = threading.Lock()
        self._bufs: dict[tuple[int, _Stream], str] = {}

    def _line(self, stream: _Stream, raw: str) -> None:
        event = make_text(_clean(raw), stream=stream)
        if self._job_id is not None:
            event["job"] = self._job_id
        _safe_emit(self._emit, event)

    def _feed(self, stream: _Stream, data: str, ident: int = 0) -> None:
        key = (ident, stream)
        with self._lock:
            parts = (self._bufs.pop(key, "") + data).split("\n")
            rest = parts.pop()
            if len(rest) > _MAX_PARTIAL:
                cut = len(rest) - (len(rest) % _MAX_PARTIAL or _MAX_PARTIAL)
                parts.extend(rest[i : i + _MAX_PARTIAL] for i in range(0, cut, _MAX_PARTIAL))
                rest = rest[cut:]
            if rest:
                self._bufs[key] = _collapse_cr(rest)
        for raw in parts:
            self._line(stream, raw)

    def _flush_partials(self) -> None:
        with self._lock:
            pending = list(self._bufs.items())
            self._bufs.clear()
        for (_, stream), raw in pending:
            if _clean(raw):
                self._line(stream, raw)


class _AppRoute(_Lines):
    def __init__(self, emit: Callable[[Event], None], ui_thread_id: int) -> None:
        super().__init__(emit, None)
        self.ui_thread_id = ui_thread_id
        self.closed = False

    def write(self, stream: _Stream, data: str) -> None:
        self._feed(stream, data, threading.get_ident())

    def close(self) -> None:
        self._flush_partials()
        self.closed = True


class JobCapture(_Lines):
    """Output sink for one job; ``activate`` binds it to the current context."""

    def __init__(
        self,
        emit: Callable[[Event], None],
        job_id: int,
        route: _AppRoute | None = None,
        ui_thread_id: int | None = None,
    ) -> None:
        super().__init__(emit, job_id)
        self._route = route
        self._ui_ident = threading.get_ident() if ui_thread_id is None else ui_thread_id
        self._abandoned = False
        self._closed = False

    def activate(self) -> None:
        _JOB.set(self)

    def flush(self) -> None:
        if self._verdict() == _CAPTURE:
            self._flush_partials()

    def abandon(self) -> None:
        with self._lock:
            if self._closed or self._abandoned:
                return
            self._abandoned = True
            self._bufs.clear()

    def close(self) -> None:
        if self._closed:
            return
        self.flush()
        self._closed = True
        if _JOB.get() is self and threading.get_ident() == self._ui_ident:
            _JOB.set(None)

    def _verdict(self) -> str:
        if self._abandoned:
            return _SWALLOW
        route = self._route
        if self._closed or (route is not None and route.closed):
            return _IGNORE if threading.get_ident() == self._ui_ident else _SWALLOW
        return _CAPTURE

    def _write(self, stream: _Stream, data: str) -> None:
        self._feed(stream, data)


def _attributed() -> bool:
    job = _JOB.get()
    return job is not None and job._verdict() != _IGNORE


class _Proxy:
    """Stands in for ``sys.stdout``/``sys.stderr``; unknown attributes go to the wrapped stream uncaptured."""

    def __init__(self, owner: OutputCapture, name: _Stream, wrapped: Any) -> None:
        self._owner = owner
        self._name = name
        self._wrapped = wrapped

    def _raw_write(self, data: str) -> int:
        wrapped = self._wrapped
        if isinstance(wrapped, _Proxy):
            return wrapped._raw_write(data)
        if wrapped is None:
            return len(data)
        return cast("int", wrapped.write(data))

    def write(self, data: str) -> int:
        if not isinstance(data, str):
            raise TypeError(f"write() argument must be str, not {type(data).__name__}")
        if not data:
            return 0
        if not getattr(_LOCAL, "busy", False):
            job = _JOB.get()
            if job is not None:
                verdict = job._verdict()
                if verdict == _CAPTURE:
                    job._write(self._name, data)
                    return len(data)
                if verdict == _SWALLOW:
                    return len(data)
            route = self._owner._active_route()
            if route is not None and threading.get_ident() != route.ui_thread_id:
                route.write(self._name, data)
        return self._raw_write(data)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        if _attributed() or self._wrapped is None:
            return
        self._wrapped.flush()

    def isatty(self) -> bool:
        if _attributed() or self._wrapped is None:
            return False
        return bool(self._wrapped.isatty())

    def fileno(self) -> int:
        if _attributed() or self._wrapped is None:
            raise io.UnsupportedOperation("fileno")
        return cast("int", self._wrapped.fileno())

    def __getattr__(self, name: str) -> Any:
        if name in ("_owner", "_name", "_wrapped"):
            raise AttributeError(name)
        return getattr(self._wrapped, name)

    def __repr__(self) -> str:
        return f"<capture proxy over {self._wrapped!r}>"


class OutputCapture:
    """Refcounted, identity-guarded install of the stdout/stderr proxies, plus the routing table."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._refs = 0
        self._proxies: dict[str, _Proxy] = {}
        self._holds = 0
        self._outer: dict[str, _Proxy] = {}
        self._routes: list[_AppRoute] = []

    @property
    def installed(self) -> bool:
        proxies = self._proxies or self._outer
        return bool(proxies) and all(
            getattr(sys, name) in (proxy, self._outer.get(name)) for name, proxy in proxies.items()
        )

    @property
    def refs(self) -> int:
        return self._refs

    def acquire(self) -> None:
        with self._lock:
            self._refs += 1
            if self._refs == 1:
                self._wrap("stdout")
                self._wrap("stderr")

    def release(self) -> None:
        with self._lock:
            if self._refs <= 0:
                return
            self._refs -= 1
            if self._refs == 0:
                self._unwrap("stdout")
                self._unwrap("stderr")
                self._drop_outer()

    def reinstall(self) -> None:
        with self._lock:
            if self._refs > 0:
                self._wrap("stdout")
                self._wrap("stderr")

    def hold(self) -> None:
        """
        Put an outer proxy over the real streams for one ``App.run``: Textual puts back what ``sys.stdout`` was
        when its loop started, so teardown has no unwrapped window. It outlives ``unhold`` while any ref is held.
        """
        with self._lock:
            self._holds += 1
            if self._holds == 1:
                self._wrap_outer("stdout")
                self._wrap_outer("stderr")

    def unhold(self) -> None:
        with self._lock:
            if self._holds > 0:
                self._holds -= 1
            self._drop_outer()

    def open_app(self, emit: Callable[[Event], None], ui_thread_id: int) -> object:
        route = _AppRoute(emit, ui_thread_id)
        with self._lock:
            self._routes.append(route)
        return route

    def close_app(self, token: object) -> None:
        if not isinstance(token, _AppRoute):
            return
        with self._lock:
            if token in self._routes:
                self._routes.remove(token)
        token.close()

    def open_job(self, emit: Callable[[Event], None], job_id: int) -> JobCapture:
        route = self._active_route()
        return JobCapture(emit, job_id, route, None if route is None else route.ui_thread_id)

    def _active_route(self) -> _AppRoute | None:
        try:
            return self._routes[-1]
        except IndexError:
            return None

    def _wrap(self, name: _Stream) -> None:
        current = getattr(sys, name)
        existing = self._proxies.get(name)
        if current is self._outer.get(name) or (existing is not None and current is existing):
            return
        proxy = _Proxy(self, name, current)
        self._proxies[name] = proxy
        setattr(sys, name, cast("TextIO", proxy))

    def _unwrap(self, name: _Stream) -> None:
        proxy = self._proxies.pop(name, None)
        if proxy is not None and getattr(sys, name) is proxy:
            setattr(sys, name, proxy._wrapped)

    def _wrap_outer(self, name: _Stream) -> None:
        current = getattr(sys, name)
        existing = self._outer.get(name)
        if existing is not None and current is existing:
            return
        proxy = _Proxy(self, name, current)
        self._outer[name] = proxy
        setattr(sys, name, cast("TextIO", proxy))

    def _drop_outer(self) -> None:
        if self._holds or self._refs:
            return
        for name in ("stdout", "stderr"):
            proxy = self._outer.pop(name, None)
            if proxy is not None and getattr(sys, name) is proxy:
                setattr(sys, name, proxy._wrapped)


CAPTURE = OutputCapture()
