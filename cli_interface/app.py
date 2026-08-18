from __future__ import annotations

import json as _json
import csv as _csv
import io
import logging
from typing import Any

from rich.pretty import Pretty
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, RichLog, Static

from .log_handler import TUILogHandler
from .menu import MenuItem, MenuState
from .phrases import get_phrase

# One Half Dark — orange primary accent
_BG      = "#282c34"
_SURFACE = "#2c2f3a"
_PANEL   = "#353a45"
_FG      = "#dcdfe4"
_ORANGE  = "#d19a66"
_CYAN    = "#56b6c2"
_GREEN   = "#98c379"
_YELLOW  = "#e5c07b"
_RED     = "#e06c75"
_DIM_FG  = "#7a8194"

_BACK = "__back__"
_EXIT = "__exit__"

LEVEL_STYLES = {
    "DEBUG":    f"dim {_CYAN}",
    "INFO":     _GREEN,
    "WARNING":  _YELLOW,
    "ERROR":    f"bold {_RED}",
    "CRITICAL": f"bold {_FG} on {_RED}",
}

_HINT_TEXT = (
    f"  [{_ORANGE}]↑ ↓[/]  [{_FG}]navigate[/]"
    f"   [{_ORANGE}]Enter[/]  [{_FG}]select[/]"
    f"   [{_ORANGE}]Esc[/]  [{_FG}]back[/]"
    f"   [{_ORANGE}]q[/]  [{_FG}]quit[/]"
    f"   [{_DIM_FG}]·[/]  type a shortcut or command\n"
    f"  [{_ORANGE}]PgUp / PgDn[/]  [{_FG}]scroll output[/]"
    f"   [{_ORANGE}]Home / End[/]  [{_FG}]jump to top / bottom[/]"
)


# ---------------------------------------------------------------------------
# Prompt modal
# ---------------------------------------------------------------------------

class PromptScreen(ModalScreen[str | None]):
    """
    Modal input dialog. Dismisses with the typed string, or None on cancel.

    The calling action receives the value::

        MenuItem("Set port", prompt="Port number:", action=lambda v: set_port(int(v)))
    """

    CSS = f"""
    PromptScreen {{
        align: center middle;
    }}

    #prompt-dialog {{
        width: 64;
        height: auto;
        background: {_SURFACE};
        border: heavy {_ORANGE};
        padding: 1 2 2 2;
    }}

    #prompt-title {{
        height: 2;
        padding: 0 0 1 0;
        color: {_ORANGE};
        text-style: bold;
    }}

    #prompt-label {{
        height: 2;
        color: {_FG};
        padding: 0 0 1 0;
    }}

    #prompt-input {{
        background: {_PANEL};
        color: {_FG};
        border: tall {_ORANGE};
    }}

    #prompt-hint {{
        height: 1;
        color: {_DIM_FG};
        padding: 1 0 0 0;
    }}
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(self, item_label: str, prompt: str) -> None:
        super().__init__()
        self._item_label = item_label
        self._prompt     = prompt

    def compose(self) -> ComposeResult:
        with Container(id="prompt-dialog"):
            yield Label(self._item_label, id="prompt-title")
            yield Label(self._prompt, id="prompt-label")
            yield Input(id="prompt-input")
            yield Label(
                f"[{_ORANGE}]Enter[/]  confirm   [{_ORANGE}]Esc[/]  cancel",
                id="prompt-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#prompt-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Display panel API
# ---------------------------------------------------------------------------

class DisplayPanel:
    """
    General-purpose display panel.

    Push any content here — log lines, JSON, tables, CSVs, raw text, or
    arbitrary Rich renderables. Attach a Python logger via
    ``attach_logging(app)`` to have log records flow in automatically.

    Usage from within an action::

        app.panel.json(my_config, title="Current config")
        app.panel.table(rows, headers=["Name", "Value"])
        app.panel.log("Something happened", level="WARNING")
        app.panel.text("plain output", style="bold")
        app.panel.rule("section divider")
        app.panel.clear()
    """

    def __init__(self, widget: RichLog) -> None:
        self._w = widget

    def clear(self) -> None:
        self._w.clear()

    def rule(self, title: str = "") -> None:
        """Horizontal divider, optionally titled."""
        self._w.write(Rule(title, style=_ORANGE))

    def text(self, content: str, style: str = "") -> None:
        """Plain text, optionally with a Rich style string."""
        if style:
            self._w.write(Text.from_markup(f"[{style}]{content}[/]"))
        else:
            self._w.write(content)

    def log(self, message: str, level: str = "INFO") -> None:
        """Coloured log line. level: DEBUG | INFO | WARNING | ERROR | CRITICAL"""
        style = LEVEL_STYLES.get(level.upper(), "")
        self._w.write(f"[{style}]{message}[/]" if style else message)

    def json(self, data: Any, title: str = "") -> None:
        """Pretty-print a dict, list, or JSON string with syntax highlighting."""
        raw = data if isinstance(data, str) else _json.dumps(data, indent=2, default=str)
        if title:
            self.rule(title)
        self._w.write(Syntax(raw, "json", theme="monokai", word_wrap=True))

    def table(
        self,
        rows: list,
        headers: list[str] | None = None,
        title: str = "",
    ) -> None:
        """
        Render a table.

        ``rows`` can be a list of dicts (keys become columns) or a list of
        lists/tuples (pass ``headers`` to name the columns).
        """
        tbl = Table(
            title=title or None,
            border_style=_DIM_FG,
            header_style=f"bold {_ORANGE}",
            show_lines=False,
        )
        if not rows:
            self._w.write(tbl)
            return
        if isinstance(rows[0], dict):
            cols = headers or list(rows[0].keys())
            for col in cols:
                tbl.add_column(str(col))
            for row in rows:
                tbl.add_row(*[str(row.get(c, "")) for c in cols])
        else:
            n    = len(rows[0]) if rows else 0
            cols = headers or [str(i + 1) for i in range(n)]
            for col in cols:
                tbl.add_column(str(col))
            for row in rows:
                tbl.add_row(*[str(v) for v in row])
        self._w.write(tbl)

    def csv(self, csv_string: str, title: str = "") -> None:
        """Parse and render a CSV string as a table."""
        reader  = _csv.reader(io.StringIO(csv_string.strip()))
        rows    = list(reader)
        if not rows:
            return
        headers, *data = rows
        self.table([dict(zip(headers, row)) for row in data], headers=headers, title=title)

    def array(self, items: list, title: str = "") -> None:
        """Pretty-print a list."""
        if title:
            self.rule(title)
        self._w.write(Pretty(items))

    def pretty(self, obj: Any, title: str = "") -> None:
        """Pretty-print any Python object."""
        if title:
            self.rule(title)
        self._w.write(Pretty(obj))

    def renderable(self, obj: Any) -> None:
        """Write any Rich renderable directly (Table, Syntax, Panel, etc.)."""
        self._w.write(obj)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class Dashboard(Static):
    location = reactive("Home")
    status   = reactive(get_phrase("idle"))

    def render(self) -> str:
        crumbs = self.location.split("|")
        sep    = f"[{_DIM_FG}] › [/]"
        path   = sep.join(f"[bold {_ORANGE}]{c}[/]" for c in crumbs)
        return f" {path}\n [{_CYAN} italic]{self.status}[/]"


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
            sc    = f"[{_YELLOW}]{item.shortcut}[/] " if item.shortcut else ""
            label = item.label
            if item.current_value is not None:
                label += f" [{_DIM_FG}]({item.current_value})[/]"
            arrow = f" [{_DIM_FG}]›[/]" if (not item.is_leaf and not is_sentinel) else ""

            if i == self.selected:
                if is_sentinel:
                    parts.append(f"[bold {_BG} on {_DIM_FG}] {sc}{label} [/]")
                else:
                    parts.append(f"[bold {_BG} on {_ORANGE}] {sc}{label}{arrow} [/]")
            else:
                if is_sentinel:
                    parts.append(f"  [{_DIM_FG}]{sc}{label}[/]  ")
                else:
                    parts.append(f"  {sc}[{_FG}]{label}[/]{arrow}  ")
        return "  " + "  ".join(parts)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

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
        height: 2;
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
        Binding("up",       "move_up",          "Up",     show=False),
        Binding("down",     "move_down",         "Down",   show=False),
        Binding("escape",   "go_back",           "Back",   show=False),
        Binding("pageup",   "panel_scroll_up",   "PgUp",   show=False),
        Binding("pagedown", "panel_scroll_down", "PgDn",   show=False),
        Binding("home",     "panel_scroll_home", "Home",   show=False),
        Binding("end",      "panel_scroll_end",  "End",    show=False),
        Binding("ctrl+c",   "quit",              "Quit"),
    ]

    def __init__(self, menu: MenuItem, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._state             = MenuState(menu)
        self._display_items:    list[MenuItem] = []
        self._display_selected: int  = 0
        self._panel:            DisplayPanel | None = None

    @property
    def panel(self) -> DisplayPanel:
        """General-purpose display panel for output, logs, tables, JSON, etc."""
        if self._panel is None:
            self._panel = DisplayPanel(self.query_one("#display-panel", RichLog))
        return self._panel

    # ------------------------------------------------------------------
    # Compose

    def compose(self) -> ComposeResult:
        yield Dashboard(id="dashboard")
        yield RichLog(id="display-panel", highlight=True, markup=True, wrap=True)
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
    # Backward-compat log shortcut

    def push_log(self, message: str, level: str = "INFO") -> None:
        self.panel.log(message, level)

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
        try:
            result = item.action(value) if value is not None else item.action()
            label  = f"{item.label}({value!r})" if value is not None else item.label
            self.panel.log(
                f"Executed: {label}" + (f" → {result}" if result is not None else ""),
                "INFO",
            )
        except Exception as exc:
            self.panel.log(f"Error in {item.label}: {exc}", "ERROR")
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


def attach_logging(app: CLIApp, logger: logging.Logger | None = None) -> None:
    """
    Wire a Python logger into the display panel.

    Pass ``logger=None`` to capture the root logger (catches everything).
    Pass a specific logger to capture only that namespace::

        attach_logging(app, logging.getLogger("my_project"))
    """
    target  = logger or logging.getLogger()
    handler = TUILogHandler(app)
    target.addHandler(handler)


def run(menu: MenuItem | None = None) -> None:
    if menu is not None:
        CLIApp(menu).run()
        return
    # Demo mode: build example menu with lazy access to app.panel
    from .example_menu import build_example_menu
    ref: list[CLIApp] = []
    demo_menu = build_example_menu(lambda: ref[0].panel)
    app = CLIApp(demo_menu)
    ref.append(app)
    app.run()
