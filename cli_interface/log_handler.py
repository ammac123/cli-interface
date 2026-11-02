"""
Log plumbing for the display panel: ``PanelInbox`` (the thread-safe event queue behind
``CLIApp.emit``), ``TUILogHandler`` (a ``logging.Handler`` feeding it) and
``LogAttachment`` (the handle ``attach_logging`` returns).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .events import Event, EventSink, is_droppable, make_log, make_log_from_record

if TYPE_CHECKING:
    from .app import CLIApp

_INBOX_MAXLEN = 10_000
_DRAIN_BUDGET = 0.015
_COMPACT_MIN = 1024


class _Entry:
    __slots__ = ("event", "droppable", "key")

    def __init__(self, event: Event | None, droppable: bool, key: tuple[Any, Any] | None) -> None:
        self.event = event  # None marks a tombstone: dropped or coalesced, still sitting in the deque
        self.droppable = droppable
        self.key = key


class PanelInbox:
    """
    Thread-safe queue that feeds events to a UI-thread sink in first-in first-out order.

    Owned by ``CLIApp`` (``emit``/``push_log`` call ``put``); not meant to be
    constructed by consumers. Its lifecycle is ``new`` -> ``open`` -> ``closed``:

    * before ``open``: events are buffered;
    * ``open``, called on the UI thread: an event from the UI thread is delivered
      straight away after any queued backlog, within one ``_DRAIN_BUDGET`` slice (what
      is left follows from a scheduled wake); an event from any other thread is queued
      and the UI loop is woken, so the caller never waits on the UI;
    * after ``close``: ``put`` is a silent no-op.

    ``log`` and ``text`` events are droppable: at most ``maxlen`` (default 10,000) are
    queued, and past that the oldest is dropped. Every other kind is kept, and
    ``progress`` events are coalesced per ``(job, id)``. A "N log record(s) dropped" WARNING is
    written before the surviving events at the start of an overflow episode, and one
    "M more ..." line at its end (when the queue drains to empty). ``put`` never raises: a
    sink exception is swallowed and counted in ``write_errors``. An event put by the sink
    itself (a re-entrant call) is discarded.
    """

    def __init__(self, sink: EventSink, maxlen: int | None = None) -> None:
        """``sink.emit(event)`` is called on the UI thread only. ``maxlen=None`` uses the module default."""
        self._sink = sink
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self._dq: deque[_Entry] = deque()
        self._droppables: deque[_Entry] = deque()
        self._progress: dict[tuple[Any, Any], _Entry] = {}
        self._live = 0
        self._tombs = 0
        self._state = "new"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ui_ident: int | None = None
        self._wake_pending = False
        self._ep_dropped = 0
        self._ep_notified = 0
        self._local = threading.local()
        self.dropped = 0  # cumulative number of droppable events dropped because the queue was full
        self.write_errors = 0  # cumulative number of exceptions swallowed (sink errors included)

    @property
    def pending(self) -> int:
        """Number of events queued and not yet delivered."""
        return self._live

    def open(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Start delivering to the sink. Call on the UI thread, with its running loop.

        Events buffered so far are drained on the next loop iteration. Calling
        it again, or after ``close``, does nothing.
        """
        with self._lock:
            if self._state != "new":
                return
            self._state = "open"
            self._loop = loop
            self._ui_ident = threading.get_ident()
            wake = self._live > 0 or self._ep_dropped > 0
            if wake:
                self._wake_pending = True
        if wake:
            self._schedule(loop, False)

    def close(self) -> None:
        """Stop for good: discard anything queued and make later ``put`` calls no-ops. Any thread; idempotent."""
        with self._lock:
            self._state = "closed"
            self._dq.clear()
            self._droppables.clear()
            self._progress.clear()
            self._live = self._tombs = 0
            self._ep_dropped = self._ep_notified = 0
            self._loop = None
            self._wake_pending = False

    def put(self, event: Event | str, level: str = "INFO") -> None:
        """
        Queue one event for the sink. Any thread; never raises.

        A ``str`` is a log convenience: it becomes a ``log`` event at ``level``
        (shown literally). From a non-UI thread this never blocks on the UI. From the
        UI thread it delivers at most one ``_DRAIN_BUDGET`` slice of the backlog, then
        queues behind what is left and schedules a wake.
        """
        # Events put while the sink is running on this thread (busy) are dropped to avoid recursion.
        if getattr(self._local, "busy", False):
            return
        try:
            if isinstance(event, str):
                event = make_log(event, level)
            elif not isinstance(event, dict):
                event = dict(event) if isinstance(event, Mapping) else make_log(str(event), level)
            ui = False
            loop = None
            # The lock only guards state; it is never held across sink calls.
            with self._lock:
                state = self._state
                if state == "closed":
                    return
                self._enqueue(event)
                if state == "open":
                    if threading.get_ident() == self._ui_ident:
                        ui = True
                    elif not self._wake_pending:
                        self._wake_pending = True
                        loop = self._loop
            if ui:
                if self._drain(_DRAIN_BUDGET, None):
                    self._ensure_wake()
            elif loop is not None:
                self._schedule(loop, True)
        except Exception:
            self.write_errors += 1

    emit = put

    def flush(self) -> None:
        """Deliver everything queued now, ignoring the budget. UI thread only; a no-op elsewhere and before ``open``."""
        if getattr(self._local, "busy", False):
            return
        try:
            with self._lock:
                if self._state != "open" or threading.get_ident() != self._ui_ident:
                    return
                limit = self._live + 2  # what is queued now, plus the two notice lines
            self._drain(None, limit)
        except Exception:
            self.write_errors += 1

    def _enqueue(self, event: Event) -> None:
        # Caller holds the lock.
        droppable = is_droppable(event)
        key: tuple[Any, Any] | None = None
        if droppable:
            maxlen = max(1, self._maxlen if self._maxlen is not None else _INBOX_MAXLEN)
            while len(self._droppables) >= maxlen:
                victim = self._droppables.popleft()
                victim.event = None
                self._live -= 1
                self._tombs += 1
                self.dropped += 1
                self._ep_dropped += 1
                self._trim()
        elif event.get("kind") == "progress":
            key = self._coalesce(event)
        entry = _Entry(event, droppable, key)
        self._dq.append(entry)
        self._live += 1
        if droppable:
            self._droppables.append(entry)
        elif key is not None:
            self._progress[key] = entry

    def _coalesce(self, event: Event) -> tuple[Any, Any] | None:
        # Caller holds the lock. The older queued progress of the same (job, id) is replaced, unless it is final.
        key = (event.get("job"), event.get("id"))
        try:
            prev = self._progress.get(key)
        except TypeError:
            return None
        if prev is not None and prev.event is not None and not prev.event.get("done"):
            prev.event = None
            self._live -= 1
            self._tombs += 1
            self._trim()
        return key

    def _trim(self) -> None:
        # Caller holds the lock. Keeps tombstones from piling up: O(1) amortised.
        dq = self._dq
        while dq and dq[0].event is None:
            dq.popleft()
            self._tombs -= 1
        if self._tombs > _COMPACT_MIN and self._tombs > self._live:
            self._dq = deque(entry for entry in dq if entry.event is not None)
            self._tombs = 0

    def _next(self) -> Event | None:
        # Caller holds the lock. The next event to deliver, the overflow notice lines included; None when idle.
        if self._ep_dropped and not self._ep_notified:
            self._ep_notified = self._ep_dropped
            return make_log(f"{self._ep_notified} log record(s) dropped (UI busy)", "WARNING")
        dq = self._dq
        while dq:
            entry = dq.popleft()
            event = entry.event
            if event is None:
                self._tombs -= 1
                continue
            self._live -= 1
            if entry.droppable:
                if self._droppables and self._droppables[0] is entry:
                    self._droppables.popleft()
            elif entry.key is not None and self._progress.get(entry.key) is entry:
                del self._progress[entry.key]
            return event
        more = self._ep_dropped - self._ep_notified
        self._ep_dropped = self._ep_notified = 0
        return make_log(f"{more} more log record(s) dropped (UI busy)", "WARNING") if more > 0 else None

    def _drain(self, budget: float | None, limit: int | None) -> bool:
        """UI thread. Deliver until idle, out of ``budget`` seconds or ``limit`` events; True if work may remain."""
        deadline = None if budget is None else time.monotonic() + budget
        while True:
            with self._lock:
                event = self._next() if self._state == "open" else None
                if event is None:
                    # Emptiness check and clearing the flag share one lock acquisition: no lost wakeup.
                    self._wake_pending = False
                    return False
            self._deliver(event)
            if limit is not None:
                limit -= 1
                if limit <= 0:
                    return True
            if deadline is not None and time.monotonic() >= deadline:
                return True

    def _deliver(self, event: Event) -> None:
        local = self._local
        local.busy = True
        try:
            self._sink.emit(event)
        except Exception:
            self.write_errors += 1
        finally:
            local.busy = False

    def _on_wake(self) -> None:
        try:
            more = self._drain(_DRAIN_BUDGET, None)
            if more:
                with self._lock:
                    loop = self._loop if self._state == "open" else None
                if loop is not None:
                    self._schedule(loop, False)
        except Exception:
            self.write_errors += 1

    def _ensure_wake(self) -> None:
        with self._lock:
            if self._state != "open" or self._wake_pending or self._loop is None:
                return
            self._wake_pending = True
            loop = self._loop
        self._schedule(loop, False)

    def _schedule(self, loop: asyncio.AbstractEventLoop, threadsafe: bool) -> None:
        try:
            if threadsafe:
                loop.call_soon_threadsafe(self._on_wake)
            else:
                loop.call_soon(self._on_wake)
        except RuntimeError:
            self.close()


class TUILogHandler(logging.Handler):
    """
    Routes Python log records into the TUI log panel.

    Each record becomes a ``log`` event sent to ``app.emit`` and is shown as
    ``HH:MM:SS [LEVEL] logger.name: message`` with the level's colour. If the handler's
    formatter was replaced, its output is sent instead. A host without ``emit`` gets
    ``app.push_log`` with the formatted line. Normally created for you by
    ``attach_logging``. Safe to emit from any thread. After ``detach()``, or once the
    app has exited, ``emit`` does nothing.
    """

    def __init__(self, app: CLIApp) -> None:
        super().__init__()
        self._app = app
        self._detached = False
        self._default_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S")
        self.setFormatter(self._default_formatter)

    @property
    def detached(self) -> bool:
        """True once ``detach()`` has been called."""
        return self._detached

    def detach(self) -> None:
        """Make the handler inert (later ``emit`` calls are ignored). It does not remove itself from the logger."""
        self._detached = True

    def emit(self, record: logging.LogRecord) -> None:
        """Queue ``record`` for the panel as a ``log`` event. Does nothing once detached."""
        if self._detached:
            return
        try:
            host_emit = getattr(self._app, "emit", None)
            if not callable(host_emit):
                self._app.push_log(self.format(record), record.levelname)
            elif self.formatter is self._default_formatter:
                host_emit(make_log_from_record(record))
            else:
                host_emit(
                    make_log(
                        self.format(record), record.levelname,
                        logger=None, levelno=record.levelno, exc=None, t=record.created,
                    )
                )
        except Exception:
            self.handleError(record)


class LogAttachment:
    """
    Handle for a ``TUILogHandler`` attached to a logger.

    Returned by ``attach_logging``; ``detach()`` undoes exactly what the attach
    changed. Use it as a context manager to scope a capture::

        with attach_logging(app, logging.getLogger("job")):
            ...

    ``logger`` and ``handler`` expose what was attached. ``detach()`` is
    idempotent, thread-safe and removes only this attachment's handler.

    Create one only through ``attach_logging``. Constructing a ``LogAttachment``
    directly is discouraged, not blocked: it attaches immediately but bypasses the app's
    bookkeeping (no de-duplication, no automatic detach when the app exits), so
    calling ``detach()`` is then your job (it still restores what ``exclusive=True``
    removed). The class is exported from ``cli_interface`` only so it can be used in
    type annotations.
    """

    def __init__(
        self,
        app: CLIApp,
        logger: logging.Logger | None = None,
        *,
        exclusive: bool = False,
        level: int | str | None = None,
    ) -> None:
        """
        Attach a new handler to ``logger`` (``None`` means the root logger).

        ``exclusive=True`` first removes every handler already on ``logger``;
        ``level`` sets the logger's level. Both are undone by ``detach()``.
        """
        self.logger = logging.getLogger() if logger is None else logger
        self.handler = TUILogHandler(app)
        self._lock = threading.Lock()
        self._active = True
        self._removed: list[logging.Handler] = []
        self._level_changed = False
        self._prev_level = 0
        self._set_level = 0
        try:
            if exclusive:
                for h in list(self.logger.handlers):
                    self.logger.removeHandler(h)
                    self._removed.append(h)
            if level is not None:
                prev = self.logger.level
                self.logger.setLevel(level)
                self._prev_level = prev
                self._set_level = self.logger.level
                self._level_changed = True
            self.logger.addHandler(self.handler)
        except BaseException:
            self.detach()
            raise

    @classmethod
    def inert(cls, app: CLIApp, logger: logging.Logger | None = None) -> LogAttachment:
        """An already-detached attachment: nothing is attached or changed, ``detach()`` does nothing."""
        att = cls.__new__(cls)
        att.logger = logging.getLogger() if logger is None else logger
        att.handler = TUILogHandler(app)
        att.handler.detach()
        att.handler.close()
        att._lock = threading.Lock()
        att._active = False
        att._removed = []
        att._level_changed = False
        att._prev_level = 0
        att._set_level = 0
        return att

    @property
    def active(self) -> bool:
        """True until ``detach()`` is called."""
        return self._active

    def detach(self) -> None:
        """
        Remove the handler and restore what this attachment changed. Any thread; idempotent.

        Handlers removed by ``exclusive=True`` are put back (skipping any that
        were themselves detached TUI handlers), and a handler the host added
        during the attachment is left alone. The logger's level is restored only
        if it still has the value this attachment set. Records already queued
        for the panel are still shown.
        """
        with self._lock:
            if not self._active:
                return
            self._active = False
            logger = self.logger
            self.handler.detach()
            logger.removeHandler(self.handler)
            self.handler.close()
            for h in self._removed:
                if isinstance(h, TUILogHandler) and h.detached:
                    continue
                if h not in logger.handlers:
                    logger.addHandler(h)
            self._removed = []
            if self._level_changed and logger.level == self._set_level:
                logger.setLevel(self._prev_level)

    def share(self) -> LogAttachment:
        """
        Return a lease on this attachment: a handle that shares the same handler.

        Calling ``detach()`` on a lease only releases the lease (it never touches
        the logger); the attachment ends when the original is detached or the app
        exits. ``attach_logging`` returns a lease when a logger is already attached.
        """
        return _Lease(self)

    def __enter__(self) -> LogAttachment:
        return self

    def __exit__(self, *exc: object) -> None:
        self.detach()


class _Lease(LogAttachment):
    """A shared handle on another attachment (see ``LogAttachment.share``); ``detach`` only releases it."""

    def __init__(self, base: LogAttachment) -> None:
        self._base = base
        self._released = False
        self.handler = base.handler
        self.logger = base.logger

    @property
    def active(self) -> bool:
        return not self._released and self._base.active

    def detach(self) -> None:
        self._released = True

    def share(self) -> LogAttachment:
        return self._base.share()
