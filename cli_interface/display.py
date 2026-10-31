"""
``DisplayPanel``: the object behind ``CLIApp.panel``, for writing log lines,
text, JSON, tables and other Rich renderables into the output area.
"""
from __future__ import annotations

import csv as _csv
import io
import json as _json
from typing import Any

from rich.errors import MarkupError
from rich.pretty import Pretty
from rich.protocol import is_renderable
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog

from .theme import LEVEL_STYLES, _DIM_FG, _ORANGE


def _as_text(value: Any, style: str = "") -> Text:
    # Literal text. A Text passes through as a copy, with ``style`` applied underneath its own spans.
    if isinstance(value, Text):
        t = value.copy()
        if style:
            t.stylize_before(style)
        return t
    return Text(str(value), style=style)


def _title(title: str | Text) -> Text | str:
    return _as_text(title) if title else ""


def _cell(value: Any) -> Any:
    # Strings and non-renderables become literal Text; Rich renderables are kept as they are.
    if isinstance(value, str) or not is_renderable(value):
        return Text(str(value))
    return value


class DisplayPanel:
    """
    General-purpose display panel, reached as ``CLIApp.panel``.

    Push any content here: log lines, JSON, tables, CSVs, raw text, or
    arbitrary Rich renderables. Every string is shown literally, including
    titles, table headers and cells: ``[/x]``, ``matrix[i][j]`` and Windows paths
    are safe. For styling pass ``markup=True`` (``log`` and ``text`` only) or a
    ``rich.text.Text`` / other Rich renderable.

    All methods must be called from the UI thread (for example inside an action),
    and only after the app has mounted. From any other thread use
    ``CLIApp.push_log``, or ``attach_logging`` for the ``logging`` module.

    The scrollback is bounded by ``CLIApp(max_lines=...)`` (default 5000 lines):
    when it is exceeded the oldest lines are discarded, for content such as large
    tables or JSON as well as for log lines.

    Scrolling: the panel follows the end of the output. The content methods
    (``json``, ``table``, ``csv``, ``array``, ``pretty``) switch that off and
    scroll to the top of the panel, so call ``clear()`` first if the new content
    should be the only thing shown. ``clear()`` turns following back on, and so
    does the end of an action that did not use a content method.

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
        self._scrolled_to_top = False

    def clear(self) -> None:
        """Remove everything from the panel and resume following the end of the output."""
        self._w.clear()
        self._scrolled_to_top = False
        self._w.auto_scroll   = True

    # ------------------------------------------------------------------
    # Content-mode helpers

    def _enter_content_mode(self) -> None:
        """Switch to content mode: disable auto-scroll before writing."""
        self._w.auto_scroll = False

    def _snap_to_top(self) -> None:
        """Scroll to the top of the panel after writing content."""
        self._scrolled_to_top = True
        self._w.scroll_home(animate=False)

    def prepare_for_action(self) -> None:
        """Reset per-action scroll tracking before running a new action."""
        self._scrolled_to_top = False

    def ensure_latest_visible(self) -> None:
        """After an action completes, scroll to the bottom unless the action
        already positioned the view at the top of new content."""
        if not self._scrolled_to_top:
            self._w.auto_scroll = True
            self._w.scroll_end(animate=False)
        self._scrolled_to_top = False

    # ------------------------------------------------------------------
    # Log lines

    def _styled(self, content: str | Text, style: str, markup: bool, highlight: bool = True) -> Text:
        if isinstance(content, Text):
            return _as_text(content, style)
        content = str(content)
        try:
            t = Text.from_markup(content, style=style) if markup else _as_text(content, style)
        except MarkupError:
            t = _as_text(content, style)
        highlighter = getattr(self._w, "highlighter", None)
        if highlight and highlighter is not None and getattr(self._w, "highlight", False):
            t = highlighter(t)
        return t

    def log(self, message: str | Text, level: str = "INFO", *, markup: bool = False) -> None:
        """
        Write one coloured log line.

        ``level`` is DEBUG | INFO | WARNING | ERROR | CRITICAL (case-insensitive;
        an unknown name writes the line unstyled). A string is shown literally and
        gets Rich's number/string highlighting. With ``markup=True`` it is parsed
        as Rich markup first (``"[bold]hi[/]"``); markup that does not parse falls
        back to the literal text instead of raising. A ``rich.text.Text`` is used
        as given (its own styles win over the level colour) and is not highlighted.
        """
        self._w.write(self._styled(message, LEVEL_STYLES.get(level.upper(), ""), markup))

    # ------------------------------------------------------------------
    # Content

    def rule(self, title: str = "") -> None:
        """Horizontal divider, optionally titled. ``title`` is shown literally."""
        self._w.write(Rule(_title(title), style=_ORANGE))

    def text(self, content: str | Text, style: str = "", *, markup: bool = False) -> None:
        """
        Write plain text, optionally with a Rich style string such as ``"bold red"``.

        Literal unless ``markup=True`` (an unparseable string falls back to
        literal text); a ``rich.text.Text`` is used as given. Text written with a
        ``style`` is not highlighted.
        """
        self._w.write(self._styled(content, style, markup, highlight=not style))

    def json(self, data: Any, title: str = "") -> None:
        """
        Pretty-print a dict, list, or JSON string with syntax highlighting.

        A string is shown as given (it is not validated or re-indented); anything
        else is serialised with ``json.dumps(indent=2, default=str)``. ``title`` is
        shown literally. Content method: see the class notes on scrolling.
        """
        self._enter_content_mode()
        raw = data if isinstance(data, str) else _json.dumps(data, indent=2, default=str)
        if title:
            self._w.write(Rule(_title(title), style=_ORANGE))
        self._w.write(Syntax(raw, "json", theme="monokai", word_wrap=True))
        self._snap_to_top()

    def table(
        self,
        rows: list,
        headers: list[str] | None = None,
        title: str = "",
    ) -> None:
        """
        Render a table.

        ``rows`` can be a list of dicts (keys become columns) or a list of
        lists/tuples (pass ``headers`` to name the columns). For dicts, ``headers``
        selects which keys to show and in what order; a missing key gives an empty
        cell. The first row decides which form is used; an empty ``rows`` draws an
        empty table. Cells, headers and ``title`` are literal; a cell that is
        already a Rich renderable (``Text``, ``Syntax``...) is kept as it is.
        Content method: see the class notes on scrolling.
        """
        self._enter_content_mode()
        tbl = Table(
            title=_as_text(title, "table.title") if title else None,
            border_style=_DIM_FG,
            header_style=f"bold {_ORANGE}",
            show_lines=False,
        )
        if not rows:
            self._w.write(tbl)
            self._snap_to_top()
            return
        if isinstance(rows[0], dict):
            cols = headers or list(rows[0].keys())
            for col in cols:
                tbl.add_column(_as_text(col))
            for row in rows:
                tbl.add_row(*[_cell(row.get(c, "")) for c in cols])
        else:
            n    = len(rows[0]) if rows else 0
            cols = headers or [str(i + 1) for i in range(n)]
            for col in cols:
                tbl.add_column(_as_text(col))
            for row in rows:
                tbl.add_row(*[_cell(v) for v in row])
        self._w.write(tbl)
        self._snap_to_top()

    def csv(self, csv_string: str, title: str = "") -> None:
        """Parse a CSV string (first row = headers) and render it with ``table``. Empty input writes nothing."""
        reader  = _csv.reader(io.StringIO(csv_string.strip()))
        rows    = list(reader)
        if not rows:
            return
        headers, *data = rows
        self.table([dict(zip(headers, row)) for row in data], headers=headers, title=title)

    def array(self, items: list, title: str = "") -> None:
        """Pretty-print a list with Rich's ``Pretty``. ``title`` is literal. Content method."""
        self._enter_content_mode()
        if title:
            self._w.write(Rule(_title(title), style=_ORANGE))
        self._w.write(Pretty(items))
        self._snap_to_top()

    def pretty(self, obj: Any, title: str = "") -> None:
        """Pretty-print any Python object with Rich's ``Pretty``. ``title`` is literal. Content method."""
        self._enter_content_mode()
        if title:
            self._w.write(Rule(_title(title), style=_ORANGE))
        self._w.write(Pretty(obj))
        self._snap_to_top()

    def renderable(self, obj: Any) -> None:
        """
        Write any Rich renderable directly (Table, Syntax, Panel, etc.).

        A ``str`` is written as literal text. Unlike the content methods this does
        not change scrolling.
        """
        self._w.write(self._styled(obj, "", False) if isinstance(obj, str) else obj)
