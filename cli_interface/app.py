from __future__ import annotations

import logging
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.widgets import Input, RichLog, Static

from .display import DisplayPanel
from .log_handler import TUILogHandler
from .menu import MenuItem, MenuState
from .phrases import get_phrase
from .theme import (
    _BACK, _BG, _DIM_FG, _EXIT, _FG, _HINT_TEXT,
    _ORANGE, _PANEL, _SURFACE,
)
from .widgets import Dashboard, NavBar, PromptScreen


class CLIApp(App):
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

    def __init__(self, menu: MenuItem, **kwargs: Any) -> None:
        super().__init__(**kwargs)
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
        """General-purpose display panel for output, logs, tables, JSON, etc."""
        if self._panel is None:
            self._panel = DisplayPanel(self.query_one("#display-panel", RichLog))
        return self._panel

    def start_spinner(self, label: str = "", phrase_context: str = "loading") -> None:
        """
        Show the animated spinner in the dashboard header.

        ``label``          — static text shown next to the spinner.  If empty,
                             the spinner label rotates through the phrase pool
                             selected by ``phrase_context`` every ~10 seconds.
        ``phrase_context`` — phrase pool used when ``label`` is empty.
                             One of: ``"loading"``, ``"thinking"``, ``"applying"``.

        Call from a Textual action (main thread). From a background thread::

            app.call_from_thread(app.start_spinner, phrase_context="thinking")
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
        Hide the spinner and return to idle phrase display.

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
            markup=True,
            wrap=True,
            auto_scroll=True,
        )
        with Container(id="nav-area"):
            yield NavBar(id="nav-bar")
            yield Static(_HINT_TEXT, id="hint")
            yield Input(placeholder="  › command or shortcut…", id="command-input")

    # ------------------------------------------------------------------
    # Lifecycle

    def on_mount(self) -> None:
        self._refresh_view("idle")
        self.set_interval(45, self._cycle_phrase)
        self.query_one("#command-input", Input).focus()

    # ------------------------------------------------------------------
    # Log shortcut (used by TUILogHandler)

    def push_log(self, message: str, level: str = "INFO") -> None:
        self.panel.log(message, level)

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
                {"Key / Command": "<letter>",        "Action": "Activate item by shortcut key (shown in yellow)"},
                {"Key / Command": "1 … 9",           "Action": "Activate item by position"},
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
        sentinel = MenuItem("Exit", shortcut="q", description=_EXIT) if at_root \
              else MenuItem("Back", shortcut="esc", description=_BACK)
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
            self.push_screen(PromptScreen(item.label, item.prompt), _on_value)
        else:
            self._run_action(item)

    def _run_action(self, item: MenuItem, value: str | None = None) -> None:
        if item.action is None:
            return
        self._refresh_view("applying")
        self.panel.prepare_for_action()
        try:
            result = item.action(value) if value is not None else item.action()
            label  = f"{item.label}({value!r})" if value is not None else item.label
            self.panel.log(
                f"Executed: {label}" + (f" → {result}" if result is not None else ""),
                "INFO",
            )
        except Exception as exc:
            self.panel.log(f"Error in {item.label}: {exc}", "ERROR")
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
        cmd = event.value.strip()
        event.input.clear()

        if not cmd:
            self.action_select()
            return
        if cmd in ("q", "quit", "exit"):
            self.exit()
            return
        if cmd in ("b", "back"):
            self.action_go_back()
            return

        if cmd == "clear":
            self.panel.clear()
            return
        if cmd in ("help", "?"):
            self._show_help()
            return

        item = self._state.select_by_shortcut(cmd)
        if item:
            self._activate(item)
            return

        if cmd.isdigit():
            idx  = int(cmd) - 1
            real = self._state.current_menu.children
            if 0 <= idx < len(real):
                self._display_selected = idx
                self._activate(real[idx])
                return

        self.panel.log(f"Unknown command: {cmd!r}", "WARNING")

    def on_key(self, event) -> None:
        key = event.character
        if key and len(key) == 1 and key.isalpha() and key not in ("b", "q"):
            inp = self.query_one("#command-input", Input)
            if self.focused is inp and inp.value == "":
                item = self._state.select_by_shortcut(key)
                if item:
                    event.stop()
                    self._activate(item)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def attach_logging(
    app: CLIApp,
    logger: logging.Logger | None = None,
    *,
    exclusive: bool = False,
) -> None:
    """
    Wire a Python logger into the display panel.

    Pass ``logger=None`` to capture the root logger (catches everything).
    Pass a specific logger to capture only that namespace::

        attach_logging(app, logging.getLogger("my_project"))

    Set ``exclusive=True`` to strip all pre-existing handlers first so that
    logs go *only* to the TUI (suppresses the default stderr StreamHandler).
    """
    target = logger or logging.getLogger()
    if exclusive:
        target.handlers.clear()
    target.addHandler(TUILogHandler(app))


def run(menu: MenuItem | None = None) -> None:
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
