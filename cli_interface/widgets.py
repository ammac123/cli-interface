"""Widgets used by ``CLIApp``: the prompt dialog (``PromptScreen``), the header (``Dashboard``) and the menu strip (``NavBar``)."""
from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Select, SelectionList, Static, Switch

from .menu import MenuItem, _NavCell, item_label, item_value
from .params import MISSING, ParamSpec, initial_text, validate_all
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
# Form and confirm dialogs
# ---------------------------------------------------------------------------

_DIALOG_CSS = f"""
    align: center middle;

    .dialog {{
        width: 72;
        height: auto;
        max-height: 90%;
        background: {_SURFACE};
        border: heavy {_ORANGE};
        padding: 1 2;
    }}

    .dialog-title {{
        height: auto;
        padding: 0 0 1 0;
        color: {_ORANGE};
        text-style: bold;
    }}

    .dialog-buttons {{
        height: auto;
        padding: 1 0 0 0;
        align-horizontal: right;
    }}

    .dialog-buttons Button {{
        margin: 0 0 0 2;
    }}
"""


def _safe_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def _field_keys(names: Sequence[str]) -> dict[str, str]:
    """Unique widget-id suffix per field: a valid name keeps itself, any other gets ``<safe>_<index>``."""
    used = {name for name in names if _safe_id(name) == name}
    keys: dict[str, str] = {}
    for index, name in enumerate(names):
        if _safe_id(name) == name:
            keys[name] = name
            continue
        candidate = f"{_safe_id(name)}_{index}"
        while candidate in used:
            candidate += "_"
        used.add(candidate)
        keys[name] = candidate
    return keys


class FormScreen(ModalScreen[dict[str, Any] | None]):
    """
    Modal form for a list of ``ParamSpec``. Dismisses with the validated ``{name: value}`` dict, or None on cancel.

    One widget per field (``Input``, ``Switch``, ``Select`` or ``SelectionList``) with its label, help
    and inline error (``form-field-<name>``, ``form-error-<name>``; a name with characters outside
    ``[A-Za-z0-9_-]`` gets an index suffix, see ``_field_keys``). Enter in an input or the submit
    button (``form-submit``) validates everything: errors are shown inline, focus goes to the first
    bad field and the form stays open. Esc or ``form-cancel`` dismisses with None. All text is literal.
    ``choices`` maps a field name to its ``(value, label)`` options, ``initial`` overrides defaults.
    """

    CSS = f"""
    FormScreen {{ {_DIALOG_CSS} }}

    #form-fields {{
        height: auto;
        max-height: 24;
    }}

    .form-field {{
        height: auto;
        padding: 0 0 1 0;
    }}

    .form-label {{
        height: auto;
        color: {_FG};
    }}

    .form-error {{
        height: auto;
        color: {_ORANGE};
    }}

    FormScreen SelectionList {{
        height: auto;
        max-height: 8;
    }}
    """

    BINDINGS = [Binding("escape", "cancel", show=False)]

    def __init__(
        self,
        title: str,
        specs: Sequence[ParamSpec],
        *,
        choices: Mapping[str, Sequence[tuple[Any, str]]] | None = None,
        initial: Mapping[str, Any] | None = None,
        submit_label: str = "Run",
    ) -> None:
        super().__init__()
        self._title = title
        self._specs = list(specs)
        self._choices = {name: list(opts) for name, opts in (choices or {}).items()}
        self._initial = dict(initial or {})
        self._submit_label = submit_label
        self._keys = _field_keys([spec.name for spec in self._specs])
        self._inputs: dict[str, Widget] = {}
        self._errors: dict[str, Static] = {}
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._title, classes="dialog-title", markup=False)
            with VerticalScroll(id="form-fields"):
                for spec in self._specs:
                    yield from self._compose_field(spec)
            with Horizontal(classes="dialog-buttons"):
                yield Button(Text(self._submit_label), id="form-submit", variant="primary")
                yield Button("Cancel", id="form-cancel")

    def _compose_field(self, spec: ParamSpec) -> ComposeResult:
        key = self._keys[spec.name]
        label = Text(spec.label, style="bold")
        if spec.help:
            label.append("\n" + spec.help, style=_DIM_FG)
        widget = self._make_input(spec, f"form-field-{key}")
        self._inputs[spec.name] = widget
        error = Static("", id=f"form-error-{key}", classes="form-error", markup=False)
        error.display = False
        self._errors[spec.name] = error
        with Vertical(classes="form-field"):
            yield Static(label, classes="form-label", markup=False)
            yield widget
            yield error

    def _make_input(self, spec: ParamSpec, widget_id: str) -> Widget:
        value = self._initial.get(spec.name, spec.default)
        if spec.kind == "bool":
            return Switch(value=bool(value) if value is not MISSING else False, id=widget_id)
        if spec.kind in ("choice", "multi"):
            options = self._choices.get(spec.name, [])
            if spec.kind == "multi":
                chosen = list(value) if isinstance(value, (list, tuple, set)) else []
                return SelectionList(*[(Text(lbl), val, val in chosen) for val, lbl in options], id=widget_id)
            items = [(Text(lbl), val) for val, lbl in options]
            allow_blank = spec.optional or not items
            kw: dict[str, Any] = {}
            if value is not MISSING:
                match = next((val for val, _ in options if val == value), MISSING)
                if match is not MISSING:
                    kw["value"] = match
            return Select(
                items, allow_blank=allow_blank, prompt="(none)" if allow_blank else "Select", id=widget_id, **kw
            )
        text = initial_text(replace(spec, default=value)) if spec.name in self._initial else initial_text(spec)
        return Input(value=text, password=spec.secret, id=widget_id)

    def on_mount(self) -> None:
        if self._specs:
            self._inputs[self._specs[0].name].focus()
        else:
            self.query_one("#form-submit", Button).focus()

    def _collect(self) -> dict[str, Any]:
        raw: dict[str, Any] = {}
        for spec in self._specs:
            widget = self._inputs[spec.name]
            if isinstance(widget, Switch):
                raw[spec.name] = widget.value
            elif isinstance(widget, Select):
                raw[spec.name] = None if widget.is_blank() else widget.value
            elif isinstance(widget, SelectionList):
                picked = widget.selected
                raw[spec.name] = [val for val, _ in self._choices.get(spec.name, []) if val in picked]
            elif isinstance(widget, Input):
                raw[spec.name] = widget.value
        return raw

    def _submit(self) -> None:
        if self._answered:
            return
        values, errors = validate_all(self._specs, self._collect(), self._choices)
        first_bad: Widget | None = None
        for spec in self._specs:
            message = errors.get(spec.name, "")
            box = self._errors[spec.name]
            box.update(Text(message))
            box.display = bool(message)
            if message and first_bad is None:
                first_bad = self._inputs[spec.name]
        if first_bad is not None:
            first_bad.focus()
            return
        self._answered = True
        self.dismiss(values)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "form-submit":
            self._submit()
        else:
            self.action_cancel()

    def action_cancel(self) -> None:
        if not self._answered:
            self._answered = True
            self.dismiss(None)


class ConfirmScreen(ModalScreen[bool]):
    """
    Modal yes/no dialog. Dismisses with True (``y`` or ``confirm-yes``) or False (``n``, Esc or ``confirm-no``).

    The no button has the initial focus, so a stray Enter declines. Title and message are shown literally.
    """

    CSS = f"""
    ConfirmScreen {{ {_DIALOG_CSS} }}

    #confirm-message {{
        height: auto;
        color: {_FG};
    }}
    """

    BINDINGS = [
        Binding("escape", "answer(False)", show=False),
        Binding("n", "answer(False)", show=False),
        Binding("y", "answer(True)", show=False),
    ]

    def __init__(self, title: str, message: str, *, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self._title = title
        self._message = message
        self._yes = yes
        self._no = no
        self._answered = False

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self._title, classes="dialog-title", markup=False)
            yield Label(self._message, id="confirm-message", markup=False)
            with Horizontal(classes="dialog-buttons"):
                yield Button(Text(self._yes), id="confirm-yes", variant="primary")
                yield Button(Text(self._no), id="confirm-no")

    def on_mount(self) -> None:
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.action_answer(event.button.id == "confirm-yes")

    def action_answer(self, answer: bool) -> None:
        if not self._answered:
            self._answered = True
            self.dismiss(answer)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class Dashboard(Static):
    """
    Top bar showing navigation breadcrumb, idle phrase, and optional spinner.

    ``crumbs`` is the breadcrumb as a tuple of labels.
    """

    crumbs: reactive[tuple[str, ...]] = reactive(("Home",))
    status        = reactive(get_phrase("idle"))
    spinning      = reactive(False)
    spinner_frame = reactive(0)
    spinner_label = reactive("")

    def render(self) -> Text:
        sep    = Text(" › ", style=_DIM_FG)
        path   = sep.join(Text(c, style=f"bold {_ORANGE}") for c in self.crumbs)
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
        """Visible width in terminal cells of an unselected item cell (a selected cell is two columns narrower)."""
        label, value = self._resolve(item)
        shortcut  = item.shortcut.strip()
        sc        = cell_len(shortcut) + 1 if shortcut else 0
        val       = cell_len(f" ({value})") if value is not None else 0
        arrow     = 2 if (not item.is_leaf and not isinstance(item, _NavCell)) else 0
        return 4 + sc + cell_len(label) + val + arrow   # 4 = leading + trailing padding

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
