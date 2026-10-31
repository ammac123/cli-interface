"""Widgets used by ``CLIApp``: the prompt dialog (``PromptScreen``), the header (``Dashboard``) and the menu strip (``NavBar``)."""
from __future__ import annotations

from rich.text import Text
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

    Enter confirms (an empty input confirms as ``""``); Esc cancels. The title and
    prompt text are shown literally. With ``secret=True`` the input is masked
    (a password field). ``CLIApp`` opens one for a ``MenuItem`` that has ``prompt``
    set, and the calling action receives the value::

        MenuItem("Set port", prompt="Port number:", action=lambda v: set_port(int(v)))
        MenuItem("Set token", prompt="API token:", secret=True, action=set_token)
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

    def __init__(self, item_label: str, prompt: str, *, secret: bool = False) -> None:
        """``item_label`` is the dialog title, ``prompt`` the text above the input; ``secret`` masks the input."""
        super().__init__()
        self._item_label = item_label
        self._prompt     = prompt
        self._secret     = secret

    def compose(self) -> ComposeResult:
        with Container(id="prompt-dialog"):
            yield Label(self._item_label, id="prompt-title", markup=False)
            yield Label(self._prompt, id="prompt-label", markup=False)
            yield Input(id="prompt-input", password=self._secret)
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
    """
    Top bar showing navigation breadcrumb, idle phrase, and optional spinner.

    ``location`` is the breadcrumb as labels joined with ``"|"``, so a menu label
    that itself contains ``"|"`` is displayed as separate crumbs.
    """

    location      = reactive("Home")
    status        = reactive(get_phrase("idle"))
    spinning      = reactive(False)
    spinner_frame = reactive(0)
    spinner_label = reactive("")

    def render(self) -> Text:
        crumbs = self.location.split("|")
        sep    = Text(" › ", style=_DIM_FG)
        path   = sep.join(Text(c, style=f"bold {_ORANGE}") for c in crumbs)
        if self.spinning:
            frame  = _SPINNER_FRAMES[self.spinner_frame % len(_SPINNER_FRAMES)]
            label  = self.spinner_label or "working…"
            status = f"{frame} {label}"
        else:
            status = f"{self.status}"
        result = Text(" ")
        result.append_text(path)
        result.append("\n ")
        result.append(status, style=f"{_CYAN} italic")
        return result


# ---------------------------------------------------------------------------
# NavBar
# ---------------------------------------------------------------------------

def _value_text(item: MenuItem) -> str:
    if item.secret and item.current_value is not None:
        return "••••"
    return f"{item.current_value}"


class NavBar(Static):
    """
    Horizontal strip of menu items, with wrapping and pagination.

    Each cell reads ``shortcut label (value) ›``: the shortcut in yellow (exactly
    what to type, then Enter), the optional ``current_value`` (``••••`` for a secret
    item) and a ``›`` marker on submenus. The Exit (``q``) and Back (``b``) cells
    are appended by the app. Everything is drawn literally. Two rows fit per page;
    the rest are reached with the arrow keys.
    """

    items:    reactive[list[MenuItem]] = reactive(list, layout=True)
    selected: reactive[int]            = reactive(0)

    def watch_items(self, _: list[MenuItem]) -> None:
        self.refresh(layout=True)

    def watch_selected(self, _: int) -> None:
        self.refresh(layout=True)

    # ------------------------------------------------------------------
    # Layout helpers

    def _compute_item_width(self, item: MenuItem) -> int:
        """
        Estimate visible character width of a rendered item cell.

        The shortcut is counted as 2 columns, which is exact only for a one-character
        shortcut: longer shortcuts are under-estimated, so a row can overflow.
        """
        sc        = 2 if item.shortcut else 0
        val       = len(f" ({_value_text(item)})") if item.current_value is not None else 0
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

    def _render_item(self, i: int, item: MenuItem) -> Text:
        is_sent = item.description in (_BACK, _EXIT)

        sc = Text()
        if item.shortcut:
            sc.append(item.shortcut, style=_YELLOW)
            sc.append(" ")
        label = Text(item.label)
        if item.current_value is not None:
            label.append(" ")
            label.append(f"({_value_text(item)})", style=_DIM_FG)
        arrow = Text()
        if not item.is_leaf and not is_sent:
            arrow.append(" ")
            arrow.append("›", style=_DIM_FG)

        if i == self.selected:
            cell = Text(style=f"bold {_BG} on {_DIM_FG if is_sent else _ORANGE}")
            cell.append(" ")
            cell.append_text(sc)
            cell.append_text(label)
            cell.append_text(arrow)
            cell.append(" ")
        elif is_sent:
            body = Text()
            body.append_text(sc)
            body.append_text(label)
            body.stylize_before(_DIM_FG)
            cell = Text("  ")
            cell.append_text(body)
            cell.append("  ")
        else:
            label.stylize_before(_FG)
            cell = Text("  ")
            cell.append_text(sc)
            cell.append_text(label)
            cell.append_text(arrow)
            cell.append("  ")
        return cell

    # ------------------------------------------------------------------
    # Render

    def render(self) -> Text:
        if not self.items:
            return Text("  (no options)", style=_DIM_FG)

        width = self.size.width if self.size.width > 0 else 80
        rows  = self._layout_rows(width)
        if not rows:
            return Text("  (no options)", style=_DIM_FG)

        # Determine which page (pair of rows) contains the selected item
        total_pages   = (len(rows) + 1) // 2
        selected_page = 0
        for p in range(total_pages):
            if any(self.selected in row for row in rows[p * 2 : p * 2 + 2]):
                selected_page = p
                break

        page_rows = rows[selected_page * 2 : selected_page * 2 + 2]
        result = Text()
        for n, row in enumerate(page_rows):
            if n:
                result.append("\n")
            for i in row:
                result.append_text(self._render_item(i, self.items[i]))

        if total_pages > 1:
            result.append("\n  ")
            result.append(
                f"page {selected_page + 1} of {total_pages}"
                f" — keep navigating ↑↓ to reach items on other pages",
                style=_DIM_FG,
            )

        return result
