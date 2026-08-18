from __future__ import annotations

import logging
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.widgets import Input, RichLog, Static

from .log_handler import TUILogHandler
from .menu import MenuItem, MenuState
from .phrases import get_phrase

# One Half Dark — orange/purple accent variant
_BG       = "#282c34"
_SURFACE  = "#2c2f3a"
_PANEL    = "#353a45"
_FG       = "#dcdfe4"
_ORANGE   = "#d19a66"
_MAGENTA  = "#c678dd"
_CYAN     = "#56b6c2"
_GREEN    = "#98c379"
_YELLOW   = "#e5c07b"
_RED      = "#e06c75"
_DIM_FG   = "#7a8194"

# Sentinel descriptions for Back / Exit nav items
_BACK = "__back__"
_EXIT = "__exit__"

LEVEL_STYLES = {
    "DEBUG":    f"dim {_CYAN}",
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    f"bold {_RED}",
    "CRITICAL": f"bold {_FG} on {_RED}",
}


class Dashboard(Static):
    location = reactive("Home")
    status   = reactive(get_phrase("idle"))

    def render(self) -> str:
        crumbs = self.location.split("|")
        sep = f"[{_DIM_FG}] › [/]"
        path = sep.join(f"[bold {_ORANGE}]{c}[/]" for c in crumbs)
        return f" {path}\n [{_MAGENTA} italic]{self.status}[/]"


class NavBar(Static):
    items:    reactive[list[MenuItem]] = reactive(list, layout=True)
    selected: reactive[int]            = reactive(0)

    def watch_items(self, _: list[MenuItem]) -> None:
        self.refresh()

    def watch_selected(self, _: int) -> None:
        self.refresh()

    def render(self) -> str:
        if not self.items:
            return f"[{_DIM_FG}]  (no options)[/]"
        parts = []
        for i, item in enumerate(self.items):
            is_sentinel = item.description in (_BACK, _EXIT)
            sc = f"[{_YELLOW}]{item.shortcut}[/] " if item.shortcut else ""
            label = item.label
            if item.current_value is not None:
                label += f" [{_DIM_FG}]({item.current_value})[/]"
            arrow = f" [{_DIM_FG}]›[/]" if (not item.is_leaf and not is_sentinel) else ""

            if i == self.selected:
                if is_sentinel:
                    parts.append(f"[bold {_BG} on {_DIM_FG}] {sc}{label} [/]")
                else:
                    parts.append(f"[bold {_BG} on {_MAGENTA}] {sc}{label}{arrow} [/]")
            else:
                if is_sentinel:
                    parts.append(f"  [{_DIM_FG}]{sc}{label}[/]  ")
                else:
                    parts.append(f"  {sc}[{_FG}]{label}[/]{arrow}  ")
        return "  " + "  ".join(parts)


class CLIApp(App):
    CSS = f"""
    Screen {{
        background: {_BG};
        color: {_FG};
        layout: vertical;
    }}

    #dashboard {{
        height: 4;
        background: {_SURFACE};
        border-bottom: heavy {_MAGENTA};
        padding: 0 1;
    }}

    #log-panel {{
        height: 1fr;
        background: {_BG};
        color: {_FG};
        border-bottom: heavy {_MAGENTA};
        padding: 0 1;
    }}

    #nav-area {{
        height: auto;
        background: {_SURFACE};
        padding: 0 1 0 1;
    }}

    #nav-bar {{
        height: 2;
        padding: 1 0 0 0;
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
        Binding("up",     "move_up",   "Up",   show=False),
        Binding("down",   "move_down", "Down", show=False),
        Binding("escape", "go_back",   "Back", show=False),
        Binding("ctrl+c", "quit",      "Quit"),
    ]

    def __init__(self, menu: MenuItem, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state = MenuState(menu)
        self._display_items: list[MenuItem] = []
        self._display_selected: int = 0

    # ------------------------------------------------------------------
    # Compose

    def compose(self) -> ComposeResult:
        yield Dashboard(id="dashboard")
        yield RichLog(id="log-panel", highlight=True, markup=True, wrap=True)
        with Container(id="nav-area"):
            yield NavBar(id="nav-bar")
            yield Input(placeholder="  › command or shortcut…", id="command-input")

    # ------------------------------------------------------------------
    # Lifecycle

    def on_mount(self) -> None:
        self._refresh_view("idle")
        self.set_interval(15, self._cycle_phrase)
        self.query_one("#command-input", Input).focus()

    # ------------------------------------------------------------------
    # Log API

    def push_log(self, message: str, level: str = "INFO") -> None:
        style = LEVEL_STYLES.get(level, "")
        log   = self.query_one("#log-panel", RichLog)
        log.write(f"[{style}]{message}[/]" if style else message)

    # ------------------------------------------------------------------
    # Internal helpers

    def _build_display_items(self) -> list[MenuItem]:
        children = list(self._state.current_menu.children)
        at_root  = len(self._state._stack) <= 1
        if at_root:
            children.append(MenuItem("Exit", shortcut="q",   description=_EXIT))
        else:
            children.append(MenuItem("Back", shortcut="esc", description=_BACK))
        return children

    def _refresh_view(self, phrase_context: str = "idle") -> None:
        dashboard          = self.query_one("#dashboard", Dashboard)
        dashboard.location = "|".join(self._state.breadcrumb)
        dashboard.status   = get_phrase(phrase_context)

        self._display_items    = self._build_display_items()
        self._display_selected = min(
            self._display_selected, len(self._display_items) - 1
        )

        nav          = self.query_one("#nav-bar", NavBar)
        nav.items    = self._display_items
        nav.selected = self._display_selected

    def _cycle_phrase(self) -> None:
        self.query_one("#dashboard", Dashboard).status = get_phrase("idle")

    def _execute_item(self, item: MenuItem) -> None:
        if item.action:
            self._refresh_view("applying")
            try:
                result = item.action()
                self.push_log(
                    f"Executed: {item.label}" + (f" → {result}" if result is not None else ""),
                    "INFO",
                )
            except Exception as exc:
                self.push_log(f"Error in {item.label}: {exc}", "ERROR")
            self._refresh_view("idle")
        else:
            self.push_log(f"{item.label}: no action bound", "WARNING")

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
            # Sync MenuState selection before entering
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

        item = self._state.select_by_shortcut(cmd)
        if item:
            self._activate(item)
            return

        if cmd.isdigit():
            idx = int(cmd) - 1
            real = self._state.current_menu.children
            if 0 <= idx < len(real):
                self._display_selected = idx
                self._activate(real[idx])
                return

        self.push_log(f"Unknown command: {cmd!r}", "WARNING")

    def on_key(self, event) -> None:
        key = event.character
        if key and len(key) == 1 and key.isalpha() and key not in ("b", "q"):
            inp = self.query_one("#command-input", Input)
            if self.focused is inp and inp.value == "":
                item = self._state.select_by_shortcut(key)
                if item:
                    event.stop()
                    self._activate(item)


def attach_logging(app: CLIApp, logger: logging.Logger | None = None) -> None:
    """Wire a Python logger (or the root logger) into the TUI log panel."""
    target  = logger or logging.getLogger()
    handler = TUILogHandler(app)
    target.addHandler(handler)


def run(menu: MenuItem | None = None) -> None:
    if menu is None:
        from .example_menu import build_example_menu
        menu = build_example_menu()
    CLIApp(menu).run()
