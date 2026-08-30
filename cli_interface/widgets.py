from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from .menu import MenuItem
from .phrases import get_phrase
from .theme import (
    _BACK, _BG, _CYAN, _DIM_FG, _EXIT,
    _FG, _ORANGE, _PANEL, _SPINNER_FRAMES, _SURFACE, _YELLOW,
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
        event.stop()
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class Dashboard(Static):
    """Top bar showing navigation breadcrumb, idle phrase, and optional spinner."""

    location      = reactive("Home")
    status        = reactive(get_phrase("idle"))
    spinning      = reactive(False)
    spinner_frame = reactive(0)
    spinner_label = reactive("")

    def render(self) -> str:
        crumbs = self.location.split("|")
        sep    = f"[{_DIM_FG}] › [/]"
        path   = sep.join(f"[bold {_ORANGE}]{c}[/]" for c in crumbs)
        if self.spinning:
            frame       = _SPINNER_FRAMES[self.spinner_frame % len(_SPINNER_FRAMES)]
            label       = self.spinner_label or "working…"
            status_line = f" [{_CYAN} italic]{frame} {label}[/]"
        else:
            status_line = f" [{_CYAN} italic]{self.status}[/]"
        return f" {path}\n{status_line}"


# ---------------------------------------------------------------------------
# NavBar
# ---------------------------------------------------------------------------

class NavBar(Static):
    """Horizontal strip of menu items, with wrapping and pagination."""

    items:    reactive[list[MenuItem]] = reactive(list, layout=True)
    selected: reactive[int]            = reactive(0)

    def watch_items(self, _: list[MenuItem]) -> None:
        self.refresh(layout=True)

    def watch_selected(self, _: int) -> None:
        self.refresh(layout=True)

    # ------------------------------------------------------------------
    # Layout helpers

    def _compute_item_width(self, item: MenuItem) -> int:
        """Estimate visible character width of a rendered item cell."""
        sc        = 2 if item.shortcut else 0
        val       = len(f" ({item.current_value})") if item.current_value is not None else 0
        is_sent   = item.description in (_BACK, _EXIT)
        arrow     = 2 if (not item.is_leaf and not is_sent) else 0
        return 4 + sc + len(item.label) + val + arrow   # 4 = leading + trailing padding

    def _layout_rows(self, width: int) -> list[list[int]]:
        """Pack item indices into rows, starting a new row when the current one is full."""
        if not self.items:
            return []
        rows: list[list[int]] = []
        cur_row: list[int]    = []
        cur_w = 0
        for i, item in enumerate(self.items):
            w = self._compute_item_width(item)
            if cur_row and cur_w + w > width:
                rows.append(cur_row)
                cur_row = [i]
                cur_w   = w
            else:
                cur_row.append(i)
                cur_w += w
        if cur_row:
            rows.append(cur_row)
        return rows

    # ------------------------------------------------------------------
    # Item rendering

    def _render_item(self, i: int, item: MenuItem) -> str:
        is_sent = item.description in (_BACK, _EXIT)
        sc      = f"[{_YELLOW}]{item.shortcut}[/] " if item.shortcut else ""
        label   = item.label
        if item.current_value is not None:
            label += f" [{_DIM_FG}]({item.current_value})[/]"
        arrow = f" [{_DIM_FG}]›[/]" if (not item.is_leaf and not is_sent) else ""

        if i == self.selected:
            if is_sent:
                return f"[bold {_BG} on {_DIM_FG}] {sc}{label} [/]"
            else:
                return f"[bold {_BG} on {_ORANGE}] {sc}{label}{arrow} [/]"
        else:
            if is_sent:
                return f"  [{_DIM_FG}]{sc}{label}[/]  "
            else:
                return f"  {sc}[{_FG}]{label}[/]{arrow}  "

    # ------------------------------------------------------------------
    # Render

    def render(self) -> str:
        if not self.items:
            return f"[{_DIM_FG}]  (no options)[/]"

        width = self.size.width if self.size.width > 0 else 80
        rows  = self._layout_rows(width)
        if not rows:
            return f"[{_DIM_FG}]  (no options)[/]"

        # Determine which page (pair of rows) contains the selected item
        total_pages   = (len(rows) + 1) // 2
        selected_page = 0
        for p in range(total_pages):
            if any(self.selected in row for row in rows[p * 2 : p * 2 + 2]):
                selected_page = p
                break

        page_rows = rows[selected_page * 2 : selected_page * 2 + 2]
        lines = [
            "".join(self._render_item(i, self.items[i]) for i in row)
            for row in page_rows
        ]
        result = "\n".join(lines)

        if total_pages > 1:
            result += (
                f"\n  [{_DIM_FG}]page {selected_page + 1} of {total_pages}"
                f" — keep navigating ↑↓ to reach items on other pages[/]"
            )

        return result
