"""Widgets used by ``CLIApp``: the prompt dialog (``PromptScreen``), the header (``Dashboard``) and the menu strip (``NavBar``)."""
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from .menu import MenuItem, _NavCell, item_label, item_value
from .phrases import get_phrase
from .theme import (
    _BG, _CYAN, _DIM_FG,
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
        height: 2;
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

    ``crumbs`` is the breadcrumb as a tuple of labels. While it is ``None``,
    ``location`` (labels joined with ``"|"``) is split instead, so a label that
    itself contains ``"|"`` is displayed as separate crumbs.
    """

    location      = reactive("Home")
    crumbs: reactive[tuple[str, ...] | None] = reactive(None)
    status        = reactive(get_phrase("idle"))
    spinning      = reactive(False)
    spinner_frame = reactive(0)
    spinner_label = reactive("")

    def render(self) -> Text:
        crumbs = self.crumbs if self.crumbs is not None else self.location.split("|")
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

def _value_text(item: MenuItem) -> str | None:
    """The text shown for ``current_value``, or None for no value. A secret item is masked without calling anything."""
    if item.secret:
        return "••••" if item.current_value is not None else None
    value = item_value(item)
    if value is None:
        return None
    try:
        return str(value)
    except Exception:
        return "<error>"


class NavBar(Static):
    """
    Horizontal strip of menu items, with wrapping and pagination.

    Each cell reads ``shortcut label (value) ›``: the shortcut in yellow (exactly
    what to type, then Enter), the optional ``current_value`` (``••••`` for a secret
    item) and a ``›`` marker on submenus. The Exit (``q``) and Back (``b``) cells
    are appended by the app. Everything is drawn literally. Two rows fit per page;
    the rest are reached with the arrow keys.

    A callable label or value is evaluated once per item per render pass (see ``_snap``);
    a secret item's value is masked without calling it.
    """

    items:    reactive[list[MenuItem]] = reactive(list, layout=True)
    selected: reactive[int]            = reactive(0)

    # Label/value text per item (keyed by id) for the render pass in progress, None outside one.
    # Each label and value callable then runs once per pass, so the width used to lay the rows out
    # and the text drawn cannot disagree. render() saves and restores it, so a nested render is safe.
    _snap: dict[int, tuple[str, str | None]] | None = None

    def watch_items(self, _: list[MenuItem]) -> None:
        self.refresh(layout=True)

    def watch_selected(self, _: int) -> None:
        self.refresh(layout=True)

    # ------------------------------------------------------------------
    # Layout helpers

    def _resolve(self, item: MenuItem) -> tuple[str, str | None]:
        """The item's label text and value text (None = no value); once per render pass while rendering."""
        snap = self._snap
        if snap is None:
            return item_label(item), _value_text(item)
        key = id(item)
        if key not in snap:
            snap[key] = (item_label(item), _value_text(item))
        return snap[key]

    def _compute_item_width(self, item: MenuItem) -> int:
        """Visible character width of an unselected item cell (a selected cell is two columns narrower)."""
        label, value = self._resolve(item)
        shortcut  = item.shortcut.strip()
        sc        = len(shortcut) + 1 if shortcut else 0
        val       = len(f" ({value})") if value is not None else 0
        arrow     = 2 if (not item.is_leaf and not isinstance(item, _NavCell)) else 0
        return 4 + sc + len(label) + val + arrow   # 4 = leading + trailing padding

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
        is_sent = isinstance(item, _NavCell)
        label_text, value = self._resolve(item)
        shortcut = item.shortcut.strip()

        sc = Text()
        if shortcut:
            sc.append(shortcut, style=_YELLOW)
            sc.append(" ")
        label = Text(label_text)
        if value is not None:
            label.append(" ")
            label.append(f"({value})", style=_DIM_FG)
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

        prev = self._snap
        self._snap = {}
        try:
            return self._render_page()
        finally:
            self._snap = prev

    def _render_page(self) -> Text:
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
