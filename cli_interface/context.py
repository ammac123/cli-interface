"""
What a running job sees: ``Context``, the event emitter that tags and redacts its output,
and the ``JobCancelled`` exception.
"""
from __future__ import annotations

import json
import logging
import math
import pprint
import threading
from collections.abc import Callable, Mapping, Sequence
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from .events import Event, make_log, make_progress, redact_event, redact_text

if TYPE_CHECKING:
    from .display import DisplayPanel
    from .jobs import Job
    from .menu import MenuItem


class JobCancelled(Exception):
    """
    Raised by ``Context.check_cancelled`` once the job has been asked to stop. The job runner
    catches it: the job ends as cancelled (``Cancelled: <label>``). Internal; not exported.
    """


_UNPRINTABLE = "<unprintable>"


def _forms(secrets: tuple[str, ...]) -> tuple[str, ...]:
    # each secret plus its json/repr/ascii escaped spellings (two levels deep), as they appear inside serialised text
    forms = set(secrets)
    for _ in range(2):
        for form in tuple(forms):
            forms.update(
                (
                    json.dumps(form)[1:-1],
                    json.dumps(form, ensure_ascii=False)[1:-1],
                    repr(form)[1:-1],
                    ascii(form)[1:-1],
                )
            )
    return tuple(f for f in forms if f)


def _scrub(value: Any, forms: tuple[str, ...], seen: tuple[int, ...] = ()) -> Any:
    if isinstance(value, str):
        return redact_text(value, forms)
    if not isinstance(value, Mapping | list | tuple | set | frozenset):
        return value
    if id(value) in seen:
        return "<circular>"
    seen += (id(value),)
    if isinstance(value, Mapping):
        return {_scrub(k, forms, seen): _scrub(v, forms, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub(v, forms, seen) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub(v, forms, seen) for v in value)
    if isinstance(value, frozenset):
        return frozenset(_scrub(v, forms, seen) for v in value)
    return {_scrub(v, forms, seen) for v in value}


def _text(value: Any) -> str:
    try:
        return value if isinstance(value, str) else str(value)
    except Exception:
        return _UNPRINTABLE


def _redact_json(event: Event, forms: tuple[str, ...]) -> None:
    pretty = bool(event.get("pretty"))
    try:
        clean = _scrub(event.get("data"), forms)
    except Exception:
        text = _UNPRINTABLE
    else:
        try:
            if pretty:
                text = pprint.pformat(clean, sort_dicts=False)
            elif isinstance(clean, str):
                text = clean
            else:
                text = json.dumps(clean, indent=2, default=_text, ensure_ascii=False)
        except Exception:
            text = _text(clean)
    event["data"] = redact_text(text, forms)
    event["pretty"] = False
    event["title"] = redact_text(_text(event.get("title", "")), forms)


def _redact_table(event: Event, forms: tuple[str, ...]) -> None:
    def cell(value: Any) -> str:
        return redact_text(_text(value), forms)

    rows: list[Any] = []
    for row in event.get("rows") or ():
        if isinstance(row, Mapping):
            rows.append({cell(k): cell(v) for k, v in row.items()})
        elif isinstance(row, list | tuple):
            rows.append([cell(v) for v in row])
        else:
            rows.append([cell(row)])
    headers = event.get("headers")
    event["rows"] = rows
    event["headers"] = None if headers is None else [cell(h) for h in headers]
    event["title"] = cell(event.get("title", ""))


def _redact_payload(event: Event, forms: tuple[str, ...]) -> None:
    kind = event.get("kind")
    try:
        if kind == "json":
            _redact_json(event, forms)
        elif kind == "table":
            _redact_table(event, forms)
    except Exception:
        # a malformed hand-built payload is replaced by an empty one, never emitted as it was
        event["title"] = redact_text(_text(event.get("title", "")), forms)
        if kind == "json":
            event.update(data=_UNPRINTABLE, pretty=False)
        else:
            event.update(rows=[], headers=None)


class JobEmitter:
    """Event sink for one job: tags ``job``, redacts secrets, and goes silent once the job is dead."""

    def __init__(
        self,
        emit: Callable[[Event], None],
        job_id: int,
        secrets: Sequence[str],
        dead: Callable[[], bool],
    ) -> None:
        self._emit = emit
        self._job_id = job_id
        if isinstance(secrets, str):
            secrets = (secrets,)
        self._secrets = tuple(s for s in secrets if isinstance(s, str) and s)
        self._forms = _forms(self._secrets)
        self._dead = dead

    @property
    def dead(self) -> bool:
        return self._dead()

    def emit(self, event: Event) -> None:
        if self._dead():
            return
        if self._secrets:
            event = redact_event(event, self._secrets)
            event.pop("obj", None)
            _redact_payload(event, self._forms)
        else:
            event = dict(event)
        event["job"] = self._job_id
        self._emit(event)


def _level(level: str | int) -> tuple[str, int | None]:
    if isinstance(level, int):
        return logging.getLevelName(level), level
    return str(level), None


class JobLog:
    """``ctx.log(msg, level="INFO", *, markup=False)`` plus one method per standard level."""

    def __init__(self, emit: Callable[[Event], None]) -> None:
        self._emit = emit

    def __call__(self, msg: object, level: str | int = "INFO", *, markup: bool = False) -> None:
        name, levelno = _level(level)
        self._emit(make_log(str(msg), name, levelno=levelno, markup=markup))

    def debug(self, msg: object, *, markup: bool = False) -> None:
        self(msg, "DEBUG", markup=markup)

    def info(self, msg: object, *, markup: bool = False) -> None:
        self(msg, "INFO", markup=markup)

    def warning(self, msg: object, *, markup: bool = False) -> None:
        self(msg, "WARNING", markup=markup)

    def error(self, msg: object, *, markup: bool = False) -> None:
        self(msg, "ERROR", markup=markup)

    def critical(self, msg: object, *, markup: bool = False) -> None:
        self(msg, "CRITICAL", markup=markup)


@runtime_checkable
class JobHost(Protocol):
    """What ``Context`` needs from the app; ``CLIApp`` satisfies it structurally."""

    state: SimpleNamespace

    def emit(self, event: Event) -> None: ...

    def on_ui_thread(self) -> bool: ...

    def call_ui(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any: ...

    def post_ui(self, fn: Callable[..., Any], *args: Any) -> None: ...

    def set_menu(self, menu: MenuItem) -> None: ...

    def refresh_menu(self) -> None: ...

    def go_home(self) -> None: ...


def _number(value: float | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, int):
        return int(value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


class Context:
    """
    The one argument a job function may ask for: a parameter annotated ``Context`` (also
    ``Context | None`` or ``Optional[Context]``) or, unannotated, named ``ctx`` or ``context``.
    Hooks may take it too. Every member is safe to use from any thread, including threads the
    job starts itself; once the job has been abandoned they do nothing.

    * ``panel``: a ``DisplayPanel`` whose output is tagged with the job and, for a job with a
      secret prompt value, redacted.
    * ``log(msg, level="INFO", *, markup=False)``, also ``log.debug`` / ``info`` / ``warning`` /
      ``error`` / ``critical``: a log line in the panel.
    * ``progress(current, total, label, *, id="default", done=False)`` and ``status(text)``:
      drive the spinner label while the job runs (``label current/total (pct%)``); ``done=True``
      clears it.
    * ``cancelled``: a ``threading.Event`` set when the job is stopped or the app quits. It is
      new for each job. ``check_cancelled()`` raises an exception the runner turns into a
      ``Cancelled:`` ending.
    * ``state``: the app's shared ``SimpleNamespace`` (``CLIApp.state``).
    * ``job``: the running ``Job`` (read-only: ``label``, ``path``, ``outcome``, ``error``, ...).
    * ``set_menu(menu)``, ``refresh_menu()``, ``go_home()``: thread-safe versions of the
      ``CLIApp`` methods. From a worker thread they wait for the UI thread to do the work.
    """

    def __init__(self, job: Job, host: JobHost, panel: DisplayPanel, emitter: JobEmitter) -> None:
        self.job = job
        self.panel = panel
        self.log = JobLog(emitter.emit)
        self.cancelled: threading.Event = job.cancelled
        self._host = host
        self._emitter = emitter

    @property
    def state(self) -> SimpleNamespace:
        return self._host.state

    def progress(
        self,
        current: float | None = None,
        total: float | None = None,
        label: str = "",
        *,
        id: str = "default",
        done: bool = False,
    ) -> None:
        """
        Report progress. The newest value of each ``id`` wins; while the job runs the spinner label
        reads ``label current/total (pct%)``, ``label current`` or ``label``. ``done=True`` clears
        it. Non-finite numbers are treated as unknown.
        """
        self._emitter.emit(
            make_progress(id=id, label=label, current=_number(current), total=_number(total), done=done)
        )

    def status(self, text: str) -> None:
        """Show ``text`` as the spinner label until the next ``status`` or ``progress``."""
        self._emitter.emit(make_progress(id="status", label=text))

    def check_cancelled(self) -> None:
        """Raise ``JobCancelled`` if the job has been asked to stop; the job then ends as cancelled."""
        if self.cancelled.is_set():
            raise JobCancelled()

    def set_menu(self, menu: MenuItem) -> None:
        """``CLIApp.set_menu`` on the UI thread, from any thread (waits for it)."""
        if not self._emitter.dead:
            self._host.call_ui(self._host.set_menu, menu)

    def refresh_menu(self) -> None:
        """``CLIApp.refresh_menu`` on the UI thread, from any thread (waits for it)."""
        if not self._emitter.dead:
            self._host.call_ui(self._host.refresh_menu)

    def go_home(self) -> None:
        """``CLIApp.go_home`` on the UI thread, from any thread (waits for it)."""
        if not self._emitter.dead:
            self._host.call_ui(self._host.go_home)
