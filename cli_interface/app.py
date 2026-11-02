"""
The application: ``CLIApp`` (renders a ``MenuItem`` tree), ``attach_logging``
(route Python logging into the output panel) and ``run`` (build a ``CLIApp`` and run it).
All three are re-exported by ``cli_interface``.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import contextvars
import logging
import math
import threading
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any, TypeVar

import rich
from rich.console import RenderableType
from rich.segment import Segments
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.css.query import NoMatches
from textual.timer import Timer
from textual.widgets import Input, RichLog, Static

from ._version import __version__
from .capture import CAPTURE
from .display import DisplayPanel, PanelRenderer
from .events import Event, EventSink, make_action, make_hello, make_log
from .jobs import Job, JobManager, SpinnerRefs, spec_from_item
from .log_handler import LogAttachment, PanelInbox
from .menu import (
    MenuItem, MenuState, _NavCell, find_shortcut_conflicts, item_label,
    make_nav_cell, reserved_action,
)
from .phrases import get_phrase
from .theme import (
    _BG, _DIM_FG, _FG, _HINT_TEXT,
    _ORANGE, _PANEL, _SURFACE,
)
from .warning_types import LoggingAttachWarning, ShortcutConflictWarning, warn_external
from .widgets import Dashboard, NavBar, PromptScreen

_DEFAULT_MAX_LINES = 5000
_DEFAULT_QUIT_GRACE = 2.0

_log = logging.getLogger(__name__)

_F = TypeVar("_F", bound=Callable[..., Any])


def _check_max_lines(max_lines: int | None) -> None:
    if max_lines is not None and (
        isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines <= 0
    ):
        raise ValueError(f"max_lines must be None or a positive int, not {max_lines!r}")


def _check_quit_grace(quit_grace: float) -> None:
    if (
        isinstance(quit_grace, bool)
        or not isinstance(quit_grace, int | float)
        or not math.isfinite(quit_grace)
        or quit_grace < 0
    ):
        raise ValueError(f"quit_grace must be a number of seconds >= 0, not {quit_grace!r}")


def _number_text(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _progress_text(event: Event) -> str:
    # "label current/total (pct%)", "label current" or "label".
    label = str(event.get("label") or "")
    current, total = event.get("current"), event.get("total")
    if current is None:
        return label
    if total:
        tail = f"{_number_text(current)}/{_number_text(total)} ({current / total * 100:.0f}%)"
    else:
        tail = _number_text(current)
    return f"{label} {tail}" if label else tail


class _AppSink:
    """The inbox's sink: an object with ``emit``, because the inbox looks that up on it."""

    __slots__ = ("_app",)

    def __init__(self, app: CLIApp) -> None:
        self._app = app

    def emit(self, event: Event) -> None:
        self._app._sink_event(event)


class CLIApp(App):
    """
    Textual app that shows a ``MenuItem`` tree as a keyboard-driven menu with a
    scrolling output panel::

        app = CLIApp(root_menu)
        app.run()

    Screen, top to bottom: the dashboard (breadcrumb, status phrase, spinner),
    the output panel (``app.panel``), the nav bar for the current menu level, a
    key hint and the command input.

    Keys: Up/Down move the selection; Enter on an empty input activates it; Esc
    goes back one level; PgUp/PgDn/Home/End scroll the output; Ctrl+C quits.

    Typed commands: type, then press Enter. A single key is never a shortcut:
    the yellow shortcut shown in the nav bar is typed in full and confirmed with
    Enter. The input is matched in this order, case-insensitively:

    1. Reserved commands: ``q`` / ``quit`` / ``exit``, ``b`` / ``back``,
       ``clear``, ``help`` / ``?``, ``stop`` (``menu.RESERVED_COMMANDS``). They
       always win over a consumer shortcut. ``b`` at the root does nothing.
       ``stop`` cancels the running command.
    2. An item shortcut on the current level (the first match wins).
    3. A position number: ``2`` activates the second item of the current level.
       The Exit / Back cell has no number.

    Anything else logs ``Unknown command: ...``.

    Jobs: every action runs as a job (see ``jobs.JobManager``), one at a time; a second
    start while one runs is rejected with a ``Busy:`` warning. An ``async`` action runs
    on the UI event loop, an action that takes a ``Context`` (and every ``App.command``
    function) in a daemon thread, and a plain context-free ``MenuItem`` action inline on
    the UI thread, where a long one freezes the UI. ``print()`` and stderr written inside
    a job appear in the panel. ``stop`` asks a job to stop, a second ``stop`` abandons it,
    and quitting gives a running job ``quit_grace`` seconds before it is abandoned.

    Public API: ``panel``, ``push_log``, ``start_spinner`` / ``stop_spinner``,
    ``set_menu`` / ``refresh_menu`` / ``go_home``, ``state`` (a ``SimpleNamespace`` shared
    by all jobs and hooks, also ``Context.state``), ``jobs`` (the ``JobManager``; its
    ``mark`` / ``wait_idle`` / ``wait_until`` are the test hooks), the hook decorators
    ``on_startup`` / ``on_shutdown`` / ``before_command`` / ``after_command``, ``exit``,
    and the module-level ``attach_logging`` and ``run``. Names starting with an
    underscore are internal.

    Protocol surface, not consumer API: ``emit``, ``loop``, ``call_ui``, ``post_ui``,
    ``on_ui_thread``, ``panel_for``, ``spinner_acquire``, ``spinner_release``,
    ``job_changed``, ``flush_inbox`` and ``request_exit``. They are what the job runner
    and ``Context`` (see ``context.JobHost`` and ``jobs.ManagerHost``) need from the app,
    are public only because those protocols are structural, and may change without
    notice. Write to the panel through ``app.panel`` / ``ctx.panel`` / ``push_log``, move
    work onto the UI thread with ``Context.set_menu`` and friends or
    ``app.call_from_thread``.

    Changing the menu while the app runs: ``refresh_menu`` after editing the tree in
    place, ``set_menu`` to swap it, ``go_home`` to return to the root. On ``CLIApp``
    these three are UI-thread only (from another thread use ``app.call_from_thread``, or
    ``Context.set_menu`` / ``refresh_menu`` / ``go_home`` inside a job, which hop to the
    UI thread for you). They may be called before the app starts, after it has exited
    and with a prompt open, and never touch the output panel except to log
    shortcut-conflict warnings.

    Subclassing: Textual calls this class's ``on_mount`` and ``on_unmount`` for a
    subclass as well, so an override need not call ``super()``; doing so is harmless,
    because both handlers can safely run twice. A subclass's ``on_mount`` runs before
    the base one (which opens the output queue, installs the print capture and starts
    the ``on_startup`` hooks), and ``start_spinner`` works from it. ``exit``, ``run``
    and ``run_async`` are overridden to run the quit sequence and keep the capture over
    teardown: an override must call ``super()``. ``run_test`` is not wrapped, so the
    print capture guard of ``run`` / ``run_async`` does not cover it.
    """

    CSS = f"""
    Screen {{
        background: {_BG};
        color: {_FG};
        layout: vertical;
    }}

    #dashboard {{
        height: 5;
        background: {_SURFACE};
        border-bottom: heavy {_ORANGE};
        padding: 1 2;
    }}

    #display-panel {{
        height: 1fr;
        background: {_BG};
        color: {_FG};
        border-bottom: heavy {_ORANGE};
        padding: 0 1;
        scrollbar-background: {_SURFACE};
        scrollbar-color: {_DIM_FG};
        scrollbar-color-hover: {_ORANGE};
        scrollbar-corner-color: {_SURFACE};
        scrollbar-size-vertical: 1;
    }}

    #nav-area {{
        height: auto;
        background: {_SURFACE};
        padding: 0 1 1 1;
    }}

    #nav-bar {{
        height: auto;
        padding: 1 0 0 0;
        margin-bottom: 1;
    }}

    #hint {{
        height: 2;
        padding: 0 1;
        color: {_DIM_FG};
        margin-bottom: 1;
    }}

    #command-input {{
        height: 3;
        background: {_PANEL};
        color: {_FG};
        border: none;
        padding: 0 1;
    }}

    #command-input:focus {{
        border: none;
        background: {_PANEL};
    }}
    """

    BINDINGS = [
        Binding("up",       "move_up",          "Up",   show=False),
        Binding("down",     "move_down",         "Down", show=False),
        Binding("escape",   "go_back",           "Back", show=False),
        Binding("pageup",   "panel_scroll_up",   "PgUp", show=False),
        Binding("pagedown", "panel_scroll_down", "PgDn", show=False),
        Binding("home",     "panel_scroll_home", "Home", show=False),
        Binding("end",      "panel_scroll_end",  "End",  show=False),
        Binding("ctrl+c",   "quit",              "Quit"),
    ]

    def __init__(
        self,
        menu: MenuItem,
        *,
        strict_shortcuts: bool = False,
        max_lines: int | None = _DEFAULT_MAX_LINES,
        quit_grace: float = _DEFAULT_QUIT_GRACE,
        **kwargs: Any,
    ) -> None:
        """
        ``menu`` is the root ``MenuItem``; its children are the first menu level.
        ``TypeError`` if it is not a ``MenuItem``.

        ``strict_shortcuts`` — what to do when a shortcut is reserved or duplicated
        on one level (see ``menu.find_shortcut_conflicts``). ``False`` (default):
        emit a ``ShortcutConflictWarning`` per problem now and log it as a WARNING
        line in the panel once the app starts. ``True``: raise ``ValueError``
        listing all the problems, before anything is created.

        ``max_lines`` — scrollback of the output panel, in lines (default 5000). The
        oldest lines are discarded beyond it, content such as a large table or JSON
        dump included. ``None`` keeps every line (unbounded). Anything else must be
        a positive ``int`` (``bool`` excluded), otherwise ``ValueError``.

        ``quit_grace`` — seconds a running command gets to stop when the app quits
        (and each ``on_shutdown`` hook gets to finish) before it is abandoned. A
        number >= 0, otherwise ``ValueError``.

        Other keyword arguments go to ``textual.app.App``.
        """
        if not isinstance(menu, MenuItem):
            raise TypeError(f"menu must be a MenuItem, not {type(menu).__name__}")
        _check_max_lines(max_lines)
        _check_quit_grace(quit_grace)
        # _validate_menu runs before App.__init__ (so a strict-mode ValueError is raised before
        # anything is created), which means everything it reads must be set first.
        self._strict_shortcuts = strict_shortcuts
        self._menu_warnings:    list[str] = []
        self._reported:         set[str] = set()
        self._dashboard:        Dashboard | None = None
        self._navbar:           NavBar | None = None
        self._rich_log:         RichLog | None = None
        self._unmounted         = False
        self._validate_menu(menu)
        super().__init__(**kwargs)
        self._max_lines         = max_lines
        self._sink              = _AppSink(self)
        self._inbox             = PanelInbox(self._sink)
        self._attach_lock       = threading.Lock()
        self._attachments:      list[LogAttachment] = []
        self._state             = MenuState(menu)
        self._display_items:    list[MenuItem] = []
        self._display_selected: int  = 0
        self._panel             = DisplayPanel(emitter=self._inbox)
        self._renderer:         PanelRenderer | None = None
        self._renderer_widget:  RichLog | None = None
        self._spinner_handle:        Timer | None = None
        self._spinner_phrase_handle: Timer | None = None
        self._phrase_handle:         Timer | None = None
        self._spinner_static_label  = ""
        self._spinner_phrase_ctx    = "loading"
        self._spin_refs             = SpinnerRefs()
        self._spin_manual           = False
        self._spin_manual_label     = ""
        self._spin_manual_ctx       = "loading"
        self._spin_status:          str | None = None
        self._spin_job:             int | None = None
        self._ui_loop:              asyncio.AbstractEventLoop | None = None
        self._ui_ident:             int | None = None
        self._ui_context:           contextvars.Context | None = None
        self._hop_lock              = threading.Lock()
        self._hops_closed           = False
        self._hops_pending:         set[concurrent.futures.Future[Any]] = set()
        self._capture_token:        object | None = None
        self._hello_sent            = False
        self.state                  = SimpleNamespace()
        self.jobs                   = JobManager(self, quit_grace=quit_grace)

    # ------------------------------------------------------------------
    # Public API

    @property
    def panel(self) -> DisplayPanel:
        """
        General-purpose display panel for output, logs, tables, JSON, etc.

        See ``DisplayPanel``. Works before the app has mounted too: what is written
        then is held and shown on start.
        """
        return self._panel

    def emit(self, event: Event) -> None:
        """
        Queue an event (see ``events``) for the output panel. Any thread; never raises.

        Protocol surface used by the job runner and the log handler, not consumer API:
        write through ``app.panel``, ``ctx.panel`` or ``push_log``.
        """
        self._inbox.put(event)

    def on_startup(self, fn: _F) -> _F:
        """
        Register ``fn(ctx)`` or ``fn()`` (sync or async) to run once, as a job named ``startup``, after
        the app has started; commands are rejected as busy until it ends. A failure is shown as an
        error and the app keeps running. ``RuntimeError`` if the app has already started. Usable as
        a decorator.
        """
        self.jobs.add_hook("startup", fn)
        return fn

    def on_shutdown(self, fn: _F) -> _F:
        """
        Register ``fn(ctx)`` or ``fn()`` to run when the app quits through ``exit()`` (typed ``q``,
        the Exit cell, Ctrl+C or a call), after the running job has stopped or been abandoned. Each
        hook is bounded by ``quit_grace``; a failure is dropped. Not run when the app crashes.
        Usable as a decorator.
        """
        self.jobs.add_hook("shutdown", fn)
        return fn

    def before_command(self, fn: _F) -> _F:
        """
        Register ``fn(ctx)`` or ``fn()`` to run before each command, in the command's lane; raising
        vetoes the command (its body and the later ``before_command`` hooks do not run, and it ends
        as an error). Usable as a decorator.
        """
        self.jobs.add_hook("before", fn)
        return fn

    def after_command(self, fn: _F) -> _F:
        """
        Register ``fn(ctx)`` or ``fn()`` to run after each command, once its ``Executed:`` /
        ``Cancelled:`` / ``Error in`` line has been shown, whatever its outcome (``ctx.job.outcome``
        and ``ctx.job.error`` are readable) except for an abandoned job, which gets no
        ``after_command``. A failure is shown as an error and does not change the outcome. Usable as
        a decorator.
        """
        self.jobs.add_hook("after", fn)
        return fn

    def start_spinner(self, label: str = "", phrase_context: str = "loading") -> None:
        """
        Show the animated spinner in the dashboard header.

        Not reference-counted: one ``stop_spinner`` ends it however many times it
        was started (a running job keeps it on until the job ends). UI thread only, and
        only while the app is running (before the app has mounted or after it has
        exited this does nothing).

        ``label``          — static text shown next to the spinner.  If empty,
                             the spinner label rotates through the phrase pool
                             selected by ``phrase_context`` every ~10 seconds.
        ``phrase_context`` — phrase pool used when ``label`` is empty.
                             One of: ``"loading"``, ``"thinking"``, ``"applying"``.

        Call from a Textual action (main thread). From a background thread::

            app.call_from_thread(app.start_spinner, phrase_context="thinking")
        """
        if self._dashboard is None and self.is_running and not self._unmounted:
            self._bind_view()  # a subclass's on_mount runs before ours
        if self._dashboard is None:  # before mount or after exit
            return
        self._spin_manual       = True
        self._spin_manual_label = label
        self._spin_manual_ctx   = phrase_context
        self._reconcile_spinner(restart=True)

    def stop_spinner(self) -> None:
        """
        Hide the spinner and return to idle phrase display. Safe to call when no
        spinner is running (it then only resets the status to an idle phrase). A
        running job keeps the spinner on until it ends.

        Call from a Textual action (main thread). From a background thread::

            app.call_from_thread(app.stop_spinner)
        """
        self._spin_manual = False
        if self._spin_refs.count > 0:
            self._reconcile_spinner()
        else:
            self._halt_spinner()

    def _reconcile_spinner(self, restart: bool = False) -> None:
        # The spinner shows while start_spinner is on or a job holds a reference. A job's
        # label (or its latest status / progress text) wins over the manual one.
        dash = self._dashboard
        if dash is None:
            return
        held = self._spin_refs.count > 0
        if not (self._spin_manual or held):
            self._halt_spinner()
            return
        if held:
            label, context = self._spin_status or self._spin_refs.label or "", "applying"
        else:
            label, context = self._spin_manual_label, self._spin_manual_ctx
        self._spinner_static_label = label
        self._spinner_phrase_ctx   = context

        dash.spinner_label = label or get_phrase(context)
        if restart or not dash.spinning:
            dash.spinner_frame = 0
        dash.spinning = True

        if self._spinner_handle is None:
            self._spinner_handle = self.set_interval(1 / 12, self._tick_spinner)

        if not label and self._spinner_phrase_handle is None:
            self._spinner_phrase_handle = self.set_interval(10, self._cycle_spinner_phrase)

    def _halt_spinner(self) -> None:
        dash = self._dashboard
        if dash is not None:
            dash.spinning = False
            dash.status   = get_phrase("idle")
        if self._spinner_handle is not None:
            self._spinner_handle.stop()
            self._spinner_handle = None
        if self._spinner_phrase_handle is not None:
            self._spinner_phrase_handle.stop()
            self._spinner_phrase_handle = None

    def set_menu(self, menu: MenuItem) -> None:
        """
        Replace the whole menu: back to the root, first item selected. UI thread only
        (from another thread: ``app.call_from_thread(app.set_menu, menu)``).

        Legal before the app starts, after it has exited and with a prompt open (the
        menu behind the prompt is updated). ``TypeError`` if ``menu`` is not a
        ``MenuItem``. The new tree is checked like the constructor's, and its problems
        are reported afresh: in strict mode a conflict raises ``ValueError``, otherwise
        each one emits a ``ShortcutConflictWarning`` (and, once the app is running, a
        WARNING line in the panel). If the check raises, a warning turned into an error
        by a filter included, the old menu and its warning state are left as they were.
        The output panel is not cleared or written to, apart from those WARNING lines.
        """
        if not isinstance(menu, MenuItem):
            raise TypeError(f"menu must be a MenuItem, not {type(menu).__name__}")
        # A new tree warns afresh, so start from an empty reported set and warning queue (any
        # warning still queued for the old tree is dropped). The tree is swapped only after the
        # check passes; if it raises, put the old state back.
        saved = (self._reported, self._menu_warnings)
        self._reported, self._menu_warnings = set(), []  # a new tree: warn afresh
        try:
            self._validate_menu(menu)
        except Exception:
            self._reported, self._menu_warnings = saved
            raise
        self._state.set_root(menu)
        self._display_selected = 0
        if self._view_ready:
            self._refresh_view("navigating")

    def refresh_menu(self) -> None:
        """
        Re-read the menu after changing it in place: callable labels and values are
        called again and added or removed children appear. UI thread only. Stays on the
        current level unless it no longer exists (then it falls back to the nearest one
        that does; the selection then goes back to the first item), and keeps the
        selection otherwise, clamped to the level's size. Legal before the app starts,
        after it has exited and with a prompt open. The output panel is not touched,
        apart from WARNING lines for new shortcut conflicts.

        The tree is checked again: strict mode raises ``ValueError`` (and the view is
        left as it was); otherwise only problems not reported before warn. A problem
        that has been fixed and comes back warns again.

        The nav bar already repaints after every action and every navigation, so this is
        needed for changes made elsewhere (a timer, a message handler, a thread via
        ``app.call_from_thread``) and for changes to the tree's structure.
        """
        self._validate_menu(self._state.root)
        if self._state.prune():
            self._display_selected = 0
        if self._view_ready:
            self._refresh_view(None)

    def go_home(self) -> None:
        """
        Return to the root level, first item selected. Does nothing at the root. UI thread
        only; legal before the app starts, after it has exited and with a prompt open. It
        does not check the tree and does not touch the output panel.
        """
        if self._state.home():
            self._display_selected = 0
            if self._view_ready:
                self._refresh_view("navigating")

    def _configure(self, *, strict_shortcuts: bool | None = None, max_lines: int | None = None) -> None:
        # For the CLI, before run(). ``strict_shortcuts=True`` turns strict mode on (and raises
        # ValueError at once if the current menu has a conflict); False and None leave it as it
        # is. ``max_lines`` None leaves the scrollback as it is.
        if max_lines is not None:
            _check_max_lines(max_lines)
        if strict_shortcuts and not self._strict_shortcuts:
            self._strict_shortcuts = True
            try:
                self._validate_menu(self._state.root)
            except Exception:
                self._strict_shortcuts = False
                raise
        if max_lines is not None:
            self._max_lines = max_lines

    def _validate_menu(self, menu: MenuItem) -> None:
        problems = find_shortcut_conflicts(menu)
        if problems and self._strict_shortcuts:
            raise ValueError("\n".join(problems))
        for problem in problems:
            if problem in self._reported:
                continue
            warn_external(problem, ShortcutConflictWarning)
            if self._view_ready:
                self.push_log(problem, "WARNING")
            else:
                self._menu_warnings.append(problem)
        self._reported = set(problems)

    @property
    def _view_ready(self) -> bool:
        return self._dashboard is not None and self._navbar is not None

    def _bind_view(self) -> None:
        # Cache the base screen's widgets: query_one resolves on the active screen, so
        # it fails with a prompt open. Cleared in on_unmount.
        stack = self.screen_stack
        if not stack:
            return
        try:
            dash = stack[0].query_one("#dashboard", Dashboard)
            nav  = stack[0].query_one("#nav-bar", NavBar)
            log  = stack[0].query_one("#display-panel", RichLog)
        except NoMatches:
            return
        self._dashboard, self._navbar, self._rich_log = dash, nav, log
        if self._renderer is None or self._renderer_widget is not log:  # one per widget: it holds scroll state
            self._renderer, self._renderer_widget = PanelRenderer(log), log

    # ------------------------------------------------------------------
    # Compose

    def compose(self) -> ComposeResult:
        yield Dashboard(id="dashboard")
        yield RichLog(
            id="display-panel",
            highlight=True,
            markup=False,
            wrap=True,
            auto_scroll=True,
            max_lines=self._max_lines,
        )
        with Container(id="nav-area"):
            yield NavBar(id="nav-bar")
            yield Static(_HINT_TEXT, id="hint")
            yield Input(placeholder="  › command or shortcut…", id="command-input")

    # ------------------------------------------------------------------
    # Lifecycle

    def on_mount(self) -> None:
        # Must stay idempotent: it can run twice (see "Subclassing" in the class docstring).
        self._unmounted = False
        loop = asyncio.get_running_loop()
        with self._hop_lock:
            self._hops_closed = False
            self._ui_loop = loop
        self._ui_ident = threading.get_ident()
        self._ui_context = contextvars.copy_context()
        self._bind_view()
        self._refresh_view("idle")
        if self._phrase_handle is None:
            self._phrase_handle = self.set_interval(45, self._cycle_phrase)
        self.query_one("#command-input", Input).focus()
        if self._capture_token is None:  # once per mount
            CAPTURE.acquire()
            self._capture_token = CAPTURE.open_app(self.emit, self._ui_ident)
        self._inbox.open(loop)
        if not self._hello_sent:
            self._hello_sent = True
            self.emit(make_hello(str(self.title), version=__version__))
        while self._menu_warnings:  # pop each once, so a second on_mount does not repeat them
            self.push_log(self._menu_warnings.pop(0), "WARNING")
        self.jobs.start()

    def on_unmount(self) -> None:
        # Stop the jobs first and let go of the output capture (before Textual leaves its own
        # redirect and prints any error), then the timers (a tick can still land during
        # teardown), then close the inbox so late records are dropped silently, then restore the
        # host's logging (detach in reverse order, so nested exclusive captures unwind).
        with self._attach_lock:
            self._unmounted = True
            attachments = list(self._attachments)
            self._attachments.clear()
        self._close_runtime()
        self._dashboard = self._navbar = self._rich_log = None
        for handle in (self._spinner_handle, self._spinner_phrase_handle, self._phrase_handle):
            if handle is not None:
                handle.stop()
        self._spinner_handle = self._spinner_phrase_handle = self._phrase_handle = None
        self._inbox.close()
        for attachment in reversed(attachments):
            attachment.detach()
        self._renderer = self._renderer_widget = None
        self._ui_loop = None

    def _close_runtime(self) -> None:
        # Idempotent; also called by run() in case on_unmount never ran (a crash).
        self.jobs.close()
        with self._hop_lock:
            self._hops_closed = True
            pending = list(self._hops_pending)
            self._hops_pending.clear()
        for fut in pending:
            fut.cancel()
        token, self._capture_token = self._capture_token, None
        if token is not None:
            CAPTURE.close_app(token)
            CAPTURE.release()

    async def run_async(self, *args: Any, **kwargs: Any) -> Any:
        """
        Run the app (see ``textual.app.App.run_async``) with the output capture held over the real
        streams, so an abandoned job's output cannot reach the terminal while Textual tears down.
        ``run`` goes through this; ``run_test`` does not.
        """
        CAPTURE.hold()
        try:
            return await super().run_async(*args, **kwargs)
        finally:
            CAPTURE.unhold()

    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Run the app (see ``textual.app.App.run``) and, afterwards, keep the output capture over any abandoned job."""
        try:
            return super().run(*args, **kwargs)
        finally:
            self._close_runtime()
            CAPTURE.reinstall()

    def exit(
        self,
        result: Any = None,
        return_code: int = 0,
        message: RenderableType | None = None,
    ) -> None:
        """
        Quit the app (``textual.app.App.exit``). A running job is asked to stop and given
        ``quit_grace`` seconds, then the ``on_shutdown`` hooks run; a second call (or typing ``q``
        again) skips the wait. With nothing running it exits at once. Any thread.
        """
        if self._ui_loop is None:  # not mounted yet, or already unmounted
            self.request_exit(result, return_code, message)
            return
        job = self.jobs.current
        if not self.on_ui_thread() or (job is not None and job.lane == "inline"):
            # From another thread, or from an inline action: defer, so the quit sees a settled manager.
            self.post_ui(self._begin_exit, result, return_code, message)
            return
        self._begin_exit(result, return_code, message)

    def _begin_exit(self, result: Any, return_code: int, message: RenderableType | None) -> None:
        self.jobs.begin_quit(lambda: self.request_exit(result, return_code, message))

    # ------------------------------------------------------------------
    # Log shortcut (used by TUILogHandler)

    def push_log(self, message: str, level: str = "INFO") -> None:
        """
        Show ``message`` in the output panel as a log line. Safe to call from any thread.

        ``level`` is a level name (``"DEBUG"``, ``"INFO"``, ``"WARNING"``,
        ``"ERROR"``, ``"CRITICAL"``) and only selects the colour; the text is
        shown literally. Called from a worker thread it returns at once and the
        line appears shortly after (records from threads stay in order). Called on
        the UI thread it is written immediately. Before the app has started the
        record is held and shown on start; after the app has exited it is
        ignored. At most 10,000 records wait for the UI: beyond that the oldest are
        dropped and a "N log record(s) dropped" WARNING says how many.

        Every panel write goes through the same ordered queue, so this holds for
        ``app.panel`` calls and ``emit`` as well.
        """
        try:
            event = make_log(message, level)
        except Exception:
            return
        self.emit(event)

    # ------------------------------------------------------------------
    # What the job manager needs from the app (see jobs.ManagerHost)

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The UI event loop while the app is mounted, else None. Protocol surface, not consumer API."""
        return self._ui_loop

    def on_ui_thread(self) -> bool:
        """True on the UI thread (or before the app has mounted). Protocol surface, not consumer API."""
        ident = self._ui_ident
        return ident is None or threading.get_ident() == ident

    def call_ui(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Run ``fn`` on the UI thread and return its result. Protocol surface, not consumer API."""
        # Inline on the UI thread. From another thread: run there and wait for the result. An exception
        # from ``fn`` is raised in the caller; None if the app is not running or has gone.
        if self.on_ui_thread():
            return fn(*args, **kwargs)
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def run() -> None:
            if not fut.set_running_or_notify_cancel():
                return
            try:
                fut.set_result(fn(*args, **kwargs))
            except BaseException as exc:
                fut.set_exception(exc)

        with self._hop_lock:
            loop, context = self._ui_loop, self._ui_context
            if self._hops_closed or loop is None or context is None:
                return None
            self._hops_pending.add(fut)
        try:
            loop.call_soon_threadsafe(run, context=context.copy())
        except RuntimeError:  # the loop is closed
            with self._hop_lock:
                self._hops_pending.discard(fut)
            return None
        try:
            return fut.result()
        except concurrent.futures.CancelledError:
            return None
        finally:
            with self._hop_lock:
                self._hops_pending.discard(fut)

    def post_ui(self, fn: Callable[..., Any], *args: Any) -> None:
        """Schedule ``fn`` on the UI thread without waiting. Protocol surface, not consumer API."""
        # Always deferred to the loop, even from the UI thread; never raises.
        with self._hop_lock:
            loop, context = self._ui_loop, self._ui_context
            if self._hops_closed or loop is None or context is None:
                return

        def run() -> None:
            try:
                fn(*args)
            except Exception as exc:
                _log.debug("posted UI call failed", exc_info=True)
                self.emit(make_log(f"{getattr(fn, '__name__', 'UI call')} failed: {exc!r}", "ERROR"))

        try:
            loop.call_soon_threadsafe(run, context=context.copy())
        except RuntimeError:
            pass

    def panel_for(self, emitter: EventSink) -> DisplayPanel:
        """A panel that writes through ``emitter`` (a job's). Protocol surface, not consumer API."""
        return DisplayPanel(emitter=emitter)

    def spinner_acquire(self, label: str) -> int:
        """Hold the spinner for a job and return the token to release. Protocol surface, not consumer API."""
        token = self._spin_refs.acquire(label)
        if self._spin_refs.count == 1:
            self._spin_status = None
        self._reconcile_spinner()
        return token

    def spinner_release(self, token: int) -> None:
        """Give back a spinner token. Protocol surface, not consumer API."""
        self._spin_refs.release(token)
        if self._spin_refs.count == 0:
            self._spin_status = None
        self._reconcile_spinner()

    def job_changed(self, job: Job | None) -> None:
        """A job began (``job``) or the last one ended (None). Protocol surface, not consumer API."""
        # The panel's action markers go through the event queue, in order with the job's output.
        if job is not None:
            self._spin_job = job.id
            self._refresh_view("applying")
            self.emit(make_action("begin"))
        else:
            self._spin_job = None
            self.emit(make_action("end"))
            self._refresh_view("idle")

    def flush_inbox(self) -> None:
        """Deliver everything queued for the panel now (UI thread). Protocol surface, not consumer API."""
        self._inbox.flush()

    def request_exit(self, result: Any, return_code: int, message: RenderableType | None) -> None:
        """Exit now, without the quit sequence (Textual's own ``exit``). Protocol surface, not consumer API."""
        super().exit(result, return_code, message)

    def _sink_event(self, event: Event) -> None:
        # The inbox's sink (UI thread). It must not emit or push_log itself: the inbox drops those.
        kind = event.get("kind")
        if kind == "hello":
            return
        if kind == "progress":
            self._apply_progress(event)
            return
        renderer = self._renderer
        if renderer is not None:
            renderer.emit(event)

    def _apply_progress(self, event: Event) -> None:
        if self._spin_refs.count == 0:
            return
        job = event.get("job")
        if job is not None and job != self._spin_job:
            return
        self._spin_status = None if event.get("done") else (_progress_text(event) or None)
        self._reconcile_spinner()

    # ------------------------------------------------------------------
    # Internal helpers

    def _show_help(self) -> None:
        self.panel.table(
            [
                {"Key / Command": "↑ / ↓",          "Action": "Navigate menu items"},
                {"Key / Command": "Enter",           "Action": "Select item or enter submenu"},
                {"Key / Command": "Esc",             "Action": "Go back one level"},
                {"Key / Command": "b / back + Enter", "Action": "Go back (typed command)"},
                {"Key / Command": "q / quit / exit + Enter", "Action": "Quit the application"},
                {"Key / Command": "PgUp / PgDn",     "Action": "Scroll output up / down"},
                {"Key / Command": "Home / End",      "Action": "Jump to top / bottom of output"},
                {"Key / Command": "clear + Enter",   "Action": "Clear the display panel"},
                {"Key / Command": "stop + Enter",    "Action": "Cancel the running command"},
                {"Key / Command": "help  /  ? + Enter", "Action": "Show this help"},
                {"Key / Command": "<shortcut> + Enter", "Action": "Activate item by its shortcut (shown in yellow)"},
                {"Key / Command": "<number> + Enter",   "Action": "Activate item by position"},
            ],
            title="Help",
        )

    def _tick_spinner(self) -> None:
        dash = self._dashboard
        if not self.is_running or dash is None:
            return
        dash.spinner_frame += 1

    def _cycle_spinner_phrase(self) -> None:
        dash = self._dashboard
        if not self.is_running or dash is None:
            return
        if dash.spinning and not self._spinner_static_label:
            dash.spinner_label = get_phrase(self._spinner_phrase_ctx)

    def _build_display_items(self) -> list[MenuItem]:
        children = list(self._state.current_menu.children)
        at_root  = len(self._state._stack) <= 1
        children.append(make_nav_cell("exit" if at_root else "back"))
        return children

    def _refresh_view(self, phrase_context: str | None = "idle") -> None:
        # phrase_context=None leaves the status phrase alone.
        dash, nav = self._dashboard, self._navbar
        if dash is None or nav is None:
            return
        labels        = self._state.breadcrumb
        dash.crumbs   = tuple(labels)
        if phrase_context is not None and not dash.spinning:
            dash.status = get_phrase(phrase_context)
        dash.refresh()

        self._display_items    = self._build_display_items()
        self._display_selected = min(
            self._display_selected, len(self._display_items) - 1
        )
        nav.items    = self._display_items
        nav.selected = self._display_selected
        nav.refresh(layout=True)  # an equal list or index does not fire the watchers

    def _cycle_phrase(self) -> None:
        dash = self._dashboard
        if not self.is_running or dash is None:
            return
        if not dash.spinning:
            dash.status = get_phrase("idle")

    def _execute_item(self, item: MenuItem) -> None:
        if not item.action:
            self.panel.log(f"{item_label(item)}: no action bound", "WARNING")
            return
        if not self.jobs.ensure_idle():  # before a prompt opens, not after it is answered
            return
        if item.prompt:
            def _on_value(value: str | None) -> None:
                if value is not None:
                    self._run_action(item, value)
            self.push_screen(PromptScreen(item_label(item), item.prompt, secret=item.secret), _on_value)
        else:
            self._run_action(item)

    def _run_action(self, item: MenuItem, value: str | None = None) -> None:
        if item.action is None:
            return
        # The typed value is never echoed. A secret item also shows no result and has the value
        # masked out of the error text (best effort: an action that logs it itself is not
        # covered). The label is read before the action, which may change it. The job manager
        # runs the action and writes the Executed / Error / Cancelled lines.
        self.jobs.submit(spec_from_item(item, value, ()))

    def _activate(self, item: MenuItem) -> None:
        if isinstance(item, _NavCell):
            if item.kind == "exit":
                self.exit()
            else:
                self.action_go_back()
            return
        if item.is_leaf:
            self._execute_item(item)
        else:
            index = next((i for i, c in enumerate(self._state.current_menu.children) if c is item), None)
            if index is None:  # the menu changed since the view was drawn
                self._refresh_view(None)
                return
            self._state.selected_index = index
            self._state.enter()
            self._display_selected = 0
            self._refresh_view("navigating")

    # ------------------------------------------------------------------
    # Actions

    def action_move_up(self) -> None:
        self._display_selected = max(0, self._display_selected - 1)
        if self._navbar is not None:
            self._navbar.selected = self._display_selected

    def action_move_down(self) -> None:
        self._display_selected = min(
            len(self._display_items) - 1, self._display_selected + 1
        )
        if self._navbar is not None:
            self._navbar.selected = self._display_selected

    def action_select(self) -> None:
        if not self._display_items:
            return
        self._activate(self._display_items[self._display_selected])

    def action_panel_scroll_up(self) -> None:
        if self._rich_log is not None:
            self._rich_log.scroll_page_up()

    def action_panel_scroll_down(self) -> None:
        if self._rich_log is not None:
            self._rich_log.scroll_page_down()

    def action_panel_scroll_home(self) -> None:
        if self._rich_log is not None:
            self._rich_log.scroll_home()

    def action_panel_scroll_end(self) -> None:
        if self._rich_log is not None:
            self._rich_log.scroll_end()

    def action_go_back(self) -> None:
        if self._state.back():
            self._display_selected = 0
            self._refresh_view("navigating")

    # ------------------------------------------------------------------
    # Input handling

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """
        Handle the command input. Empty input activates the selected item; otherwise
        the text is tried as a reserved command, an item shortcut, then a position
        number (see the class docstring); anything else logs "Unknown command".
        """
        cmd = event.value.strip()
        event.input.clear()

        if not cmd:
            self.action_select()
            return
        reserved = reserved_action(cmd)
        if reserved == "quit":
            self.exit()
            return
        if reserved == "back":
            self.action_go_back()
            return
        if reserved == "clear":
            self.panel.clear()
            return
        if reserved == "help":
            self._show_help()
            return
        if reserved == "stop":
            self.jobs.request_cancel()
            return

        item = self._state.select_by_shortcut(cmd)
        if item:
            self._activate(item)
            return

        if cmd.isdecimal():
            idx  = int(cmd) - 1
            real = self._state.current_menu.children
            if 0 <= idx < len(real):
                self._display_selected = idx
                self._activate(real[idx])
                return

        self.panel.log(f"Unknown command: {cmd!r}", "WARNING")

    def _fatal_error(self) -> None:
        # Textual's own handler prints the traceback with show_locals=True, which would print
        # a local such as the prompted secret `value` (a parameter of _run_action, also held by
        # the job's JobSpec and the frames of its thread). This is its body with show_locals=False. It overrides a private Textual hook (the same in Textual 0.80 and
        # 8.x): if Textual renames it this silently stops applying, so keep its regression test.
        from rich.traceback import Traceback

        self.bell()
        traceback = Traceback(show_locals=False, width=None, suppress=[rich])
        self._exit_renderables.append(
            Segments(self.console.render(traceback, self.console.options))
        )
        self._close_messages_no_wait()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def attach_logging(
    app: CLIApp,
    logger: logging.Logger | None = None,
    *,
    exclusive: bool = False,
    level: int | str | None = None,
) -> LogAttachment:
    """
    Wire a Python logger into the display panel.

    Pass ``logger=None`` to capture the root logger (catches everything).
    Pass a specific logger to capture only that namespace::

        attach_logging(app, logging.getLogger("my_project"))

    ``level`` sets the logger's level (a number or name such as ``"DEBUG"``) for
    as long as the attachment lasts. Without it the logger's level is left as it
    is, and the root logger's default (WARNING) drops INFO and DEBUG records.

    Set ``exclusive=True`` to remove all handlers already on *that* logger so that
    its logs go *only* to the TUI (suppresses the default stderr StreamHandler).
    ``detach()`` puts them back. For a named logger this does not stop records
    propagating to the root logger's handlers; the package does not touch
    ``propagate``.

    Returns a ``LogAttachment``. ``detach()`` (or leaving a ``with`` block) undoes
    exactly what the call changed: it removes the handler, restores any handlers
    ``exclusive`` removed (a handler the host added meanwhile is kept) and restores
    the level if nobody else changed it. Records already queued still appear.

    Rules:

    * Call it on the UI thread while the app is running (for example inside an
      action). The returned handle's ``detach()`` may be called from any thread.
    * Attachments are detached automatically when the app exits. Called after the
      app has exited, it attaches nothing: it warns (``LoggingAttachWarning``) and
      returns an already-detached handle.
    * If this app already has an active attachment for the logger, no second
      handler is added. You get a lease on the existing one (``share()``);
      detaching the lease leaves the attachment in place. If ``exclusive`` or
      ``level`` was passed it is ignored, with a ``LoggingAttachWarning``.
    """
    target = logging.getLogger() if logger is None else logger
    ignored: LogAttachment | None = None
    attachment: LogAttachment | None = None
    # The lock is shared with on_unmount, so nothing is added after its sweep.
    with app._attach_lock:
        if not app._unmounted:
            app._attachments[:] = [a for a in app._attachments if a.active]
            ignored = next((a for a in app._attachments if a.logger is target), None)
            if ignored is None:
                attachment = LogAttachment(app, target, exclusive=exclusive, level=level)
                app._attachments.append(attachment)
    if attachment is not None:
        return attachment
    if ignored is None:
        warn_external("attach_logging: the app has exited; nothing attached", LoggingAttachWarning)
        return LogAttachment.inert(app, target)
    if exclusive or level is not None:
        warn_external(
            "attach_logging: 'exclusive' and 'level' were ignored because "
            "an attachment already exists for this logger",
            LoggingAttachWarning,
        )
    return ignored.share()


def run(
    menu: MenuItem,
    *,
    strict_shortcuts: bool = False,
    max_lines: int | None = _DEFAULT_MAX_LINES,
) -> int:
    """
    Run ``CLIApp(menu, strict_shortcuts=..., max_lines=...)`` until the user quits
    and return its exit code (``app.return_code``, or 0 when the app set none). The
    arguments, and the ``TypeError`` / ``ValueError`` they can raise, are those of
    ``CLIApp``. ``menu`` is required.

    This does not hand back the app, so actions that need ``app.panel`` or the spinner
    must build a ``CLIApp`` themselves (``run`` suits actions that only return a value).
    It needs a real terminal: there is no non-TTY run path yet.
    """
    app = CLIApp(menu, strict_shortcuts=strict_shortcuts, max_lines=max_lines)
    app.run()
    return app.return_code or 0
