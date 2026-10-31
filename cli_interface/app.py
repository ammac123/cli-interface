"""
The application: ``CLIApp`` (renders a ``MenuItem`` tree), ``attach_logging``
(route Python logging into the output panel) and ``run`` (console-script entry point).
"""
from __future__ import annotations

import asyncio
import logging
import warnings
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, RichLog, Static

from .display import DisplayPanel
from .log_handler import LogAttachment, PanelInbox
from .menu import MenuItem, MenuState, find_shortcut_conflicts
from .phrases import get_phrase
from .theme import (
    _BACK, _BG, _DIM_FG, _EXIT, _FG, _HINT_TEXT,
    _ORANGE, _PANEL, _SURFACE,
)
from .widgets import Dashboard, NavBar, PromptScreen

_DEFAULT_MAX_LINES = 5000


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
       ``clear``, ``help`` / ``?`` (``menu.RESERVED_COMMANDS``). They always win
       over a consumer shortcut. ``b`` at the root does nothing.
    2. An item shortcut on the current level (the first match wins).
    3. A position number: ``2`` activates the second item of the current level.
       The Exit / Back cell has no number.

    Anything else logs ``Unknown command: ...``. An action runs synchronously on
    the UI thread, so a long action freezes the UI; for slow work start a thread
    and report with ``push_log`` or ``attach_logging``. ``async`` actions are not
    awaited.

    Public API: ``panel``, ``push_log``, ``start_spinner`` / ``stop_spinner``, and
    the module-level ``attach_logging`` and ``run``. Names starting with an
    underscore are internal.

    Subclassing: Textual already calls this class's ``on_mount`` and
    ``on_unmount`` for a subclass, so an override must not call
    ``super().on_mount()``: that runs the base handler twice (and starts its
    timers twice).
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
        max_lines: int = _DEFAULT_MAX_LINES,
        **kwargs: Any,
    ) -> None:
        """
        ``menu`` is the root ``MenuItem``; its children are the first menu level.

        ``strict_shortcuts`` — what to do when a shortcut is reserved or duplicated
        on one level (see ``menu.find_shortcut_conflicts``). ``False`` (default):
        emit a ``UserWarning`` per problem now and log it as a WARNING line in the
        panel once the app starts. ``True``: raise ``ValueError`` listing all the
        problems, before anything is created.

        ``max_lines`` — scrollback of the output panel, in lines (default 5000). The
        oldest lines are discarded beyond it, content such as a large table or JSON
        dump included. Pass a positive integer; ``None`` and ``<= 0`` are neither
        validated nor supported.

        Other keyword arguments go to ``textual.app.App``.
        """
        problems = find_shortcut_conflicts(menu)
        if problems and strict_shortcuts:
            raise ValueError("\n".join(problems))
        for problem in problems:
            warnings.warn(problem, UserWarning, stacklevel=2)
        super().__init__(**kwargs)
        self._menu_warnings:    list[str] = problems
        self._max_lines         = max_lines
        self._inbox             = PanelInbox(self)
        self._attachments:      list[LogAttachment] = []
        self._state             = MenuState(menu)
        self._display_items:    list[MenuItem] = []
        self._display_selected: int  = 0
        self._panel:            DisplayPanel | None = None
        self._spinner_handle        = None
        self._spinner_phrase_handle = None
        self._spinner_static_label  = ""
        self._spinner_phrase_ctx    = "loading"

    # ------------------------------------------------------------------
    # Public API

    @property
    def panel(self) -> DisplayPanel:
        """
        General-purpose display panel for output, logs, tables, JSON, etc.

        See ``DisplayPanel``. Available once the app has mounted (inside actions and
        handlers); before that, Textual raises ``ScreenStackError``. UI thread only.
        """
        if self._panel is None:
            self._panel = DisplayPanel(self.query_one("#display-panel", RichLog))
        return self._panel

    def start_spinner(self, label: str = "", phrase_context: str = "loading") -> None:
        """
        Show the animated spinner in the dashboard header.

        Not reference-counted: one ``stop_spinner`` ends it however many times it
        was started. UI thread only, and only while the app is running.

        ``label``          — static text shown next to the spinner.  If empty,
                             the spinner label rotates through the phrase pool
                             selected by ``phrase_context`` every ~10 seconds.
        ``phrase_context`` — phrase pool used when ``label`` is empty.
                             One of: ``"loading"``, ``"thinking"``, ``"applying"``.

        Call from a Textual action (main thread). From a background thread::

            app.call_from_thread(app.start_spinner, phrase_context="thinking")

        Testing with ``App.run_test``: if a spinner is still running, call
        ``app.exit()`` before leaving the ``async with`` block. Otherwise a spinner
        timer can tick after the screens are torn down and fail.
        """
        self._spinner_static_label = label
        self._spinner_phrase_ctx   = phrase_context

        dash = self.query_one("#dashboard", Dashboard)
        dash.spinner_label = label or get_phrase(phrase_context)
        dash.spinner_frame = 0
        dash.spinning      = True

        if self._spinner_handle is None:
            self._spinner_handle = self.set_interval(1 / 12, self._tick_spinner)

        if not label and self._spinner_phrase_handle is None:
            self._spinner_phrase_handle = self.set_interval(10, self._cycle_spinner_phrase)

    def stop_spinner(self) -> None:
        """
        Hide the spinner and return to idle phrase display. Safe to call when no
        spinner is running (it then only resets the status to an idle phrase).

        Call from a Textual action (main thread). From a background thread::

            app.call_from_thread(app.stop_spinner)
        """
        dash = self.query_one("#dashboard", Dashboard)
        dash.spinning = False
        dash.status   = get_phrase("idle")
        if self._spinner_handle is not None:
            self._spinner_handle.stop()
            self._spinner_handle = None
        if self._spinner_phrase_handle is not None:
            self._spinner_phrase_handle.stop()
            self._spinner_phrase_handle = None

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
        self._refresh_view("idle")
        self.set_interval(45, self._cycle_phrase)
        self.query_one("#command-input", Input).focus()
        _ = self.panel  # prime the cached panel; query_one fails once a modal is active
        self._inbox.open(asyncio.get_running_loop())
        while self._menu_warnings:  # pop each once, so a second on_mount does not repeat them
            self.push_log(self._menu_warnings.pop(0), "WARNING")

    def on_unmount(self) -> None:
        # Close the inbox first so late records are dropped silently, then restore the
        # host's logging (detach in reverse order, so nested exclusive captures unwind).
        self._inbox.close()
        for attachment in reversed(self._attachments):
            attachment.detach()
        self._attachments.clear()

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

        Ordering holds only among ``push_log`` records (and logging routed through
        ``attach_logging``): direct ``app.panel`` calls are written at once and may
        appear ahead of records still queued from other threads.
        """
        self._inbox.put(message, level)

    # ------------------------------------------------------------------
    # Internal helpers

    def _show_help(self) -> None:
        self.panel.table(
            [
                {"Key / Command": "↑ / ↓",          "Action": "Navigate menu items"},
                {"Key / Command": "Enter",           "Action": "Select item or enter submenu"},
                {"Key / Command": "Esc",             "Action": "Go back one level"},
                {"Key / Command": "b / back",        "Action": "Go back (typed command)"},
                {"Key / Command": "q / quit / exit", "Action": "Quit the application"},
                {"Key / Command": "PgUp / PgDn",     "Action": "Scroll output up / down"},
                {"Key / Command": "Home / End",      "Action": "Jump to top / bottom of output"},
                {"Key / Command": "clear",           "Action": "Clear the display panel"},
                {"Key / Command": "help  /  ?",      "Action": "Show this help"},
                {"Key / Command": "<shortcut> + Enter", "Action": "Activate item by its shortcut (shown in yellow)"},
                {"Key / Command": "<number> + Enter",   "Action": "Activate item by position"},
            ],
            title="Help",
        )

    def _tick_spinner(self) -> None:
        self.query_one("#dashboard", Dashboard).spinner_frame += 1

    def _cycle_spinner_phrase(self) -> None:
        dash = self.query_one("#dashboard", Dashboard)
        if dash.spinning and not self._spinner_static_label:
            dash.spinner_label = get_phrase(self._spinner_phrase_ctx)

    def _build_display_items(self) -> list[MenuItem]:
        children = list(self._state.current_menu.children)
        at_root  = len(self._state._stack) <= 1
        # Sentinel shortcuts must be typeable, so each must be in RESERVED_COMMANDS.
        sentinel = MenuItem("Exit", shortcut="q", description=_EXIT) if at_root \
              else MenuItem("Back", shortcut="b", description=_BACK)
        children.append(sentinel)
        return children

    def _refresh_view(self, phrase_context: str = "idle") -> None:
        dash          = self.query_one("#dashboard", Dashboard)
        dash.location = "|".join(self._state.breadcrumb)
        if not dash.spinning:
            dash.status = get_phrase(phrase_context)

        self._display_items    = self._build_display_items()
        self._display_selected = min(
            self._display_selected, len(self._display_items) - 1
        )
        nav          = self.query_one("#nav-bar", NavBar)
        nav.items    = self._display_items
        nav.selected = self._display_selected

    def _cycle_phrase(self) -> None:
        dash = self.query_one("#dashboard", Dashboard)
        if not dash.spinning:
            dash.status = get_phrase("idle")

    def _execute_item(self, item: MenuItem) -> None:
        if not item.action:
            self.panel.log(f"{item.label}: no action bound", "WARNING")
            return
        if item.prompt:
            def _on_value(value: str | None) -> None:
                if value is not None:
                    self._run_action(item, value)
            self.push_screen(PromptScreen(item.label, item.prompt, secret=item.secret), _on_value)
        else:
            self._run_action(item)

    def _run_action(self, item: MenuItem, value: str | None = None) -> None:
        if item.action is None:
            return
        self._refresh_view("applying")
        self.panel.prepare_for_action()
        # The typed value is never echoed. A secret item also shows no result and has
        # the value masked out of the error text (best effort: an action that logs it
        # itself is not covered).
        try:
            result = item.action(value) if value is not None else item.action()
            suffix = f" → {result}" if result is not None and not item.secret else ""
            self.panel.log(f"Executed: {item.label}{suffix}", "INFO")
        except Exception as exc:
            text = str(exc)
            if item.secret and value:
                text = text.replace(value, "***")
            self.panel.log(f"Error in {item.label}: {text}", "ERROR")
        self.panel.ensure_latest_visible()
        self._refresh_view("idle")

    def _activate(self, item: MenuItem) -> None:
        if item.description == _EXIT:
            self.exit()
            return
        if item.description == _BACK:
            self.action_go_back()
            return
        if item.is_leaf:
            self._execute_item(item)
        else:
            real_children = self._state.current_menu.children
            if item in real_children:
                self._state.selected_index = real_children.index(item)
            self._state.enter()
            self._display_selected = 0
            self._refresh_view("navigating")

    # ------------------------------------------------------------------
    # Actions

    def action_move_up(self) -> None:
        self._display_selected = max(0, self._display_selected - 1)
        self.query_one("#nav-bar", NavBar).selected = self._display_selected

    def action_move_down(self) -> None:
        self._display_selected = min(
            len(self._display_items) - 1, self._display_selected + 1
        )
        self.query_one("#nav-bar", NavBar).selected = self._display_selected

    def action_select(self) -> None:
        if not self._display_items:
            return
        self._activate(self._display_items[self._display_selected])

    def action_panel_scroll_up(self) -> None:
        self.query_one("#display-panel", RichLog).scroll_page_up()

    def action_panel_scroll_down(self) -> None:
        self.query_one("#display-panel", RichLog).scroll_page_down()

    def action_panel_scroll_home(self) -> None:
        self.query_one("#display-panel", RichLog).scroll_home()

    def action_panel_scroll_end(self) -> None:
        self.query_one("#display-panel", RichLog).scroll_end()

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
        low = cmd.lower()
        if low in ("q", "quit", "exit"):
            self.exit()
            return
        if low in ("b", "back"):
            self.action_go_back()
            return

        if low == "clear":
            self.panel.clear()
            return
        if low in ("help", "?"):
            self._show_help()
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
    * Attachments are detached automatically when the app exits. One made after
      the app has exited is not: detach it yourself.
    * If this app already has an active attachment for the logger, no second
      handler is added. You get a lease on the existing one (``share()``);
      detaching the lease leaves the attachment in place. If ``exclusive`` or
      ``level`` was passed it is ignored, with a ``UserWarning``.
    """
    target = logging.getLogger() if logger is None else logger
    app._attachments[:] = [a for a in app._attachments if a.active]
    for existing in app._attachments:
        if existing.logger is target:
            if exclusive or level is not None:
                warnings.warn(
                    "attach_logging: 'exclusive' and 'level' were ignored because "
                    "an attachment already exists for this logger",
                    UserWarning,
                    stacklevel=2,
                )
            return existing.share()
    attachment = LogAttachment(app, target, exclusive=exclusive, level=level)
    app._attachments.append(attachment)
    return attachment


def run(menu: MenuItem | None = None) -> None:
    """
    Run the app until the user quits. This is the ``cli-interface`` console script.

    With no argument it starts the bundled demo menu (``example_menu``). With a
    ``MenuItem`` it runs ``CLIApp(menu)``. It does not accept ``strict_shortcuts``
    or ``max_lines``: construct ``CLIApp`` yourself for those.
    """
    if menu is not None:
        CLIApp(menu).run()
        return
    from .example_menu import build_example_menu
    ref: list[CLIApp] = []
    demo_menu = build_example_menu(
        get_panel=lambda: ref[0].panel,
        get_app=lambda: ref[0],
    )
    app = CLIApp(demo_menu)
    ref.append(app)
    app.run()
