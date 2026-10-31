"""
Log plumbing for the display panel: ``PanelInbox`` (the thread-safe queue behind
``CLIApp.push_log``), ``TUILogHandler`` (a ``logging.Handler`` feeding it) and
``LogAttachment`` (the handle ``attach_logging`` returns).
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import CLIApp

_INBOX_MAXLEN = 10_000
_DRAIN_BUDGET = 0.015


class PanelInbox:
    """
    Thread-safe, bounded queue that feeds log records to the display panel.

    Owned by ``CLIApp`` (``CLIApp.push_log`` calls ``put``); not meant to be
    constructed by consumers. Its lifecycle is ``new`` -> ``open`` -> ``closed``:

    * before ``open``: records are buffered;
    * ``open``, called on the UI thread: a record from the UI thread is written
      to the panel immediately, after any queued backlog so order is kept; a
      record from any other thread is queued and the UI loop is woken to drain
      it, so the caller never waits on the UI;
    * after ``close``: ``put`` is a silent no-op.

    The queue holds at most ``maxlen`` records (default 10,000). When full, the
    oldest record is dropped and the panel later shows a "N log record(s)
    dropped" WARNING saying how many. Order is first-in first-out among queued records only:
    direct ``DisplayPanel`` calls bypass the inbox. A record logged while the
    panel is already writing one (a re-entrant log call) is discarded.
    """

    def __init__(self, app: "CLIApp", maxlen: int | None = None) -> None:
        """``app`` must expose ``panel.log(message, level)``. ``maxlen=None`` uses the module default."""
        self._app = app
        self._maxlen = maxlen
        self._lock = threading.Lock()
        self._dq: deque[tuple[str, str]] = deque()
        self._state = "new"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ui_ident: int | None = None
        self._wake_pending = False
        self._dropped_pending = 0
        self._local = threading.local()
        self.dropped = 0  # cumulative number of records dropped because the queue was full

    def open(self, loop: asyncio.AbstractEventLoop) -> None:
        """
        Start delivering to the panel. Call on the UI thread, with its running loop.

        Records buffered so far are drained on the next loop iteration. Calling
        it again, or after ``close``, does nothing.
        """
        with self._lock:
            if self._state != "new":
                return
            self._state = "open"
            self._loop = loop
            self._ui_ident = threading.get_ident()
            wake = bool(self._dq) or self._dropped_pending > 0
            if wake:
                self._wake_pending = True
        if wake:
            loop.call_soon(self._on_wake)

    def close(self) -> None:
        """Stop for good: discard anything queued and make later ``put`` calls no-ops. Any thread; idempotent."""
        with self._lock:
            self._state = "closed"
            self._dq.clear()
            self._loop = None
            self._wake_pending = False
            self._dropped_pending = 0

    def put(self, message: str, level: str = "INFO") -> None:
        """
        Queue one record for the panel. Any thread.

        ``level`` is a level name (``"INFO"``, ``"ERROR"``...) used only for
        styling. ``message`` is shown literally. From a non-UI thread this never
        blocks on the UI. From the UI thread it writes straight away, after any
        backlog (so a large backlog can briefly stall the UI); an error raised by
        that write propagates to the caller, and ``TUILogHandler.emit`` passes it
        to ``handleError``.
        """
        # Records logged while the panel is writing (busy) are dropped to avoid recursion.
        if getattr(self._local, "busy", False):
            return
        direct = False
        notice = 0
        backlog: list[tuple[str, str]] = []
        loop = None
        # The lock only guards state; it is never held across UI calls.
        with self._lock:
            if self._state == "closed":
                return
            if self._state == "open" and threading.get_ident() == self._ui_ident:
                # UI thread: take the backlog now and write it before this record, to keep FIFO order.
                direct = True
                notice, self._dropped_pending = self._dropped_pending, 0
                backlog = list(self._dq)
                self._dq.clear()
            else:
                maxlen = max(1, self._maxlen if self._maxlen is not None else _INBOX_MAXLEN)
                if len(self._dq) >= maxlen:
                    self._dq.popleft()
                    self.dropped += 1
                    self._dropped_pending += 1
                self._dq.append((message, level))
                if self._state == "open" and not self._wake_pending:
                    self._wake_pending = True
                    loop = self._loop
        if direct:
            self._write_all(notice, backlog)
            self._write(message, level)
            return
        if loop is not None:
            try:
                loop.call_soon_threadsafe(self._on_wake)
            except RuntimeError:
                self.close()

    def _on_wake(self) -> None:
        deadline = time.monotonic() + _DRAIN_BUDGET
        while True:
            with self._lock:
                if self._state != "open":
                    self._wake_pending = False
                    return
                notice, self._dropped_pending = self._dropped_pending, 0
                entry = self._dq.popleft() if self._dq else None
                if entry is None and not notice:
                    # Emptiness check and clearing the flag share one lock acquisition: no lost wakeup.
                    self._wake_pending = False
                    return
                loop = self._loop
            self._write_all(notice, [entry] if entry is not None else [])
            if time.monotonic() >= deadline:
                if loop is not None:
                    loop.call_soon(self._on_wake)
                return

    def _write_all(self, notice: int, entries: list[tuple[str, str]]) -> None:
        if notice:
            entries = [(f"{notice} log record(s) dropped (UI busy)", "WARNING"), *entries]
        for message, level in entries:
            try:
                self._write(message, level)
            except Exception:
                pass

    def _write(self, message: str, level: str) -> None:
        local = self._local
        local.busy = True
        try:
            self._app.panel.log(message, level)
        finally:
            local.busy = False


class TUILogHandler(logging.Handler):
    """
    Routes Python log records into the TUI log panel via ``app.push_log``.

    Each record is formatted as ``HH:MM:SS [LEVEL] logger.name: message`` and shown
    with the level's colour. Normally created for you by ``attach_logging``.
    Safe to emit from any thread. After ``detach()``, or once the app has exited,
    ``emit`` does nothing.
    """

    def __init__(self, app: "CLIApp") -> None:
        super().__init__()
        self._app = app
        self._detached = False
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))

    @property
    def detached(self) -> bool:
        """True once ``detach()`` has been called."""
        return self._detached

    def detach(self) -> None:
        """Make the handler inert (later ``emit`` calls are ignored). It does not remove itself from the logger."""
        self._detached = True

    def emit(self, record: logging.LogRecord) -> None:
        if self._detached:
            return
        try:
            self._app.push_log(self.format(record), record.levelname)
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

    Constructing a ``LogAttachment`` directly attaches immediately but bypasses
    the app's bookkeeping: no de-duplication, no automatic detach when the app
    exits, and no restoring of handlers removed by ``exclusive=True`` unless you
    call ``detach()`` yourself. Prefer ``attach_logging``.
    """

    def __init__(
        self,
        app: "CLIApp",
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

    def share(self) -> "LogAttachment":
        """
        Return a lease on this attachment: a handle that shares the same handler.

        Calling ``detach()`` on a lease only releases the lease (it never touches
        the logger); the attachment ends when the original is detached or the app
        exits. ``attach_logging`` returns a lease when a logger is already attached.
        """
        return _Lease(self)

    def __enter__(self) -> "LogAttachment":
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
