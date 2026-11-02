"""
``DisplayPanel``: the object behind ``CLIApp.panel``, for writing log lines,
text, JSON, tables and other Rich renderables into the output area.
"""
from __future__ import annotations

import copy as _copy
import csv as _csv
import io
import json as _json
import time
from collections.abc import Mapping
from typing import Any

from rich.errors import MarkupError
from rich.markup import escape
from rich.pretty import Pretty
from rich.protocol import is_renderable
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog

from .events import Event, EventSink, make_action, make_clear, make_json, make_log, make_table, make_text
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


def _snapshot(value: Any) -> Any:
    # One-level copy of a plain mutable container, so later changes by the caller are not rendered.
    if type(value) in (dict, list, set):
        return _copy.copy(value)
    return value


def _snapshot_rows(rows: Any) -> list:
    return [_snapshot(row) for row in rows or []]


def _clock(t: Any) -> str:
    try:
        return time.strftime("%H:%M:%S", time.localtime(t))
    except (TypeError, ValueError, OverflowError, OSError):
        return time.strftime("%H:%M:%S")


class PanelRenderer:
    """
    Draws events into a ``RichLog``. Call ``emit`` from the UI thread only.

    ``hello``, ``progress`` and unknown kinds write nothing.
    """

    def __init__(self, widget: RichLog) -> None:
        self._w = widget
        self._scrolled_to_top = False

    def emit(self, event: Event) -> None:
        """Draw one event."""
        kind = event.get("kind") if isinstance(event, Mapping) else None
        if kind == "log":
            self._on_log(event)
        elif kind == "text":
            self._on_text(event)
        elif kind == "json":
            self._on_json(event)
        elif kind == "table":
            self._on_table(event)
        elif kind == "result":
            self._on_result(event)
        elif kind == "error":
            self._on_error(event)
        elif kind == "clear":
            self._clear()
        elif kind == "action":
            if event.get("phase") == "begin":
                self.prepare_for_action()
            elif event.get("phase") == "end":
                self.ensure_latest_visible()

    def _clear(self) -> None:
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

    def _block(self, event: Event, *parts: Any) -> None:
        # ``scroll="top"`` is content mode: stop following the end, write, then snap to the top.
        top = event.get("scroll") == "top"
        if top:
            self._enter_content_mode()
        for part in parts:
            self._w.write(part)
        if top:
            self._snap_to_top()

    # ------------------------------------------------------------------
    # Lines

    def _styled(self, content: str, style: str, markup: bool, highlight: bool = True, prefix: str = "") -> Text:
        # ``prefix`` is always literal; only ``content`` is parsed when ``markup`` is on.
        content = str(content)
        try:
            t = Text.from_markup(escape(prefix) + content, style=style) if markup else _as_text(prefix + content, style)
        except MarkupError:
            t = _as_text(prefix + content, style)
        highlighter = getattr(self._w, "highlighter", None)
        if highlight and highlighter is not None and getattr(self._w, "highlight", False):
            t = highlighter(t)
        return t

    def _line(self, content: str, level: str) -> None:
        self._w.write(self._styled(content, LEVEL_STYLES.get(level, ""), False))

    def _on_log(self, event: Event) -> None:
        level = str(event.get("level", "INFO")).upper()
        logger = event.get("logger")
        prefix = "" if logger is None else f"{_clock(event.get('t'))} [{level}] {logger}: "
        self._w.write(
            self._styled(event.get("msg", ""), LEVEL_STYLES.get(level, ""), bool(event.get("markup")), prefix=prefix)
        )
        exc = event.get("exc")
        if exc:
            for line in str(exc).splitlines():
                self._w.write(Text(line))

    def _on_text(self, event: Event) -> None:
        obj = event.get("obj")
        if event.get("rule"):
            title = obj if isinstance(obj, Text) else event.get("text", "")
            self._w.write(Rule(_title(title), style=_ORANGE))
            return
        style = event.get("style") or (LEVEL_STYLES["WARNING"] if event.get("stream") == "stderr" else "")
        if isinstance(obj, Text):
            self._w.write(_as_text(obj, style))
        elif obj is not None and not isinstance(obj, str) and is_renderable(obj):
            self._w.write(obj)
        else:
            self._w.write(self._styled(event.get("text", ""), style, bool(event.get("markup")), highlight=not style))

    def _on_result(self, event: Event) -> None:
        label = event.get("label", "")
        if event.get("status") == "cancelled":
            self._line(f"Cancelled: {label}", "WARNING")
            return
        summary = event.get("summary")
        suffix = f" → {summary}" if summary else ""
        self._line(f"Executed: {label}{suffix}", "INFO")

    def _on_error(self, event: Event) -> None:
        self._line(f"Error in {event.get('label', '')}: {event.get('message', '')}", "ERROR")
        traceback = event.get("traceback")
        if traceback:
            for line in str(traceback).splitlines():
                self._w.write(Text(line, style="dim"))

    # ------------------------------------------------------------------
    # Content

    def _on_json(self, event: Event) -> None:
        data = event.get("data")
        title = event.get("title")
        body: Any
        if event.get("pretty"):
            body = Pretty(data)
        else:
            try:
                raw = data if isinstance(data, str) else _json.dumps(data, indent=2, default=str)
            except (ValueError, TypeError, RecursionError):
                body = Pretty(data)
            else:
                body = Syntax(raw, "json", theme="monokai", word_wrap=True)
        heading = [Rule(_title(title), style=_ORANGE)] if title else []
        self._block(event, *heading, body)

    def _on_table(self, event: Event) -> None:
        rows = event.get("rows")
        headers = event.get("headers")
        title = event.get("title")
        tbl = Table(
            title=_as_text(title, "table.title") if title else None,
            border_style=_DIM_FG,
            header_style=f"bold {_ORANGE}",
            show_lines=False,
        )
        if rows:
            if isinstance(rows[0], Mapping):
                cols = headers or list(rows[0].keys())
                for col in cols:
                    tbl.add_column(_as_text(col))
                for row in rows:
                    tbl.add_row(*[_cell(row.get(c, "")) for c in cols])
            else:
                n    = len(rows[0])
                cols = headers or [str(i + 1) for i in range(n)]
                for col in cols:
                    tbl.add_column(_as_text(col))
                for row in rows:
                    tbl.add_row(*[_cell(v) for v in row])
        self._block(event, tbl)


class DisplayPanel:
    """
    General-purpose display panel, reached as ``CLIApp.panel``.

    Push any content here: log lines, JSON, tables, CSVs, raw text, or
    arbitrary Rich renderables. Every string is shown literally, including
    titles, table headers and cells: ``[/x]``, ``matrix[i][j]`` and Windows paths
    are safe. For styling pass ``markup=True`` (``log`` and ``text`` only) or a
    ``rich.text.Text`` / other Rich renderable.

    Threads: ``CLIApp.panel`` and ``Context.panel`` are *emitter-mode* panels: each method
    only builds an event and hands it to the app's ordered queue, so they may be called
    from any thread, before the app has mounted (the output is held and shown on start)
    and after it has exited (ignored), and the lines appear in the order they were
    written. Through ``Context.panel`` the events are also tagged with the job and
    redacted for a secret job. A panel built directly on a ``RichLog`` widget
    (``DisplayPanel(widget)``, the legacy *widget mode*) draws at once and is UI-thread
    only. A ``Text`` given as a ``title`` to ``json``, ``table``, ``csv``, ``array`` or
    ``pretty`` is shown as plain text, without its style (``rule`` keeps the style of a
    ``Text`` title). For the ``logging`` module use ``attach_logging``.

    The scrollback is bounded by ``CLIApp(max_lines=...)`` (default 5000 lines,
    ``None`` for no limit): when it is exceeded the oldest lines are discarded, for
    content such as large tables or JSON as well as for log lines.

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

    def __init__(self, widget: RichLog | None = None, *, emitter: EventSink | None = None) -> None:
        self._renderer: PanelRenderer | None = None
        if widget is not None and emitter is None:
            self._renderer = PanelRenderer(widget)
            self._emitter: EventSink = self._renderer
        elif emitter is not None and widget is None:
            self._emitter = emitter
        else:
            raise TypeError("DisplayPanel takes exactly one of a widget or an emitter")

    def emit(self, event: Event) -> None:
        """Pass a ready-made event to the panel's emitter."""
        self._emitter.emit(event)

    def clear(self) -> None:
        """Remove everything from the panel and resume following the end of the output."""
        self._emitter.emit(make_clear())

    # ------------------------------------------------------------------
    # Content-mode helpers

    def prepare_for_action(self) -> None:
        """Reset per-action scroll tracking before running a new action."""
        self._emitter.emit(make_action("begin"))

    def ensure_latest_visible(self) -> None:
        """After an action completes, scroll to the bottom unless the action
        already positioned the view at the top of new content."""
        self._emitter.emit(make_action("end"))

    # ------------------------------------------------------------------
    # Log lines

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
        if isinstance(message, Text):
            style = LEVEL_STYLES.get(level.upper(), "") or None
            self._emitter.emit(make_text(message.plain, style=style, obj=message.copy()))
        else:
            self._emitter.emit(make_log(str(message), level, markup=markup))

    # ------------------------------------------------------------------
    # Content

    def rule(self, title: str = "") -> None:
        """Horizontal divider, optionally titled. ``title`` is shown literally."""
        if isinstance(title, Text):
            self._emitter.emit(make_text(title.plain, rule=True, obj=title.copy()))
        else:
            self._emitter.emit(make_text(title or "", rule=True))

    def text(self, content: str | Text, style: str = "", *, markup: bool = False) -> None:
        """
        Write plain text, optionally with a Rich style string such as ``"bold red"``.

        Literal unless ``markup=True`` (an unparseable string falls back to
        literal text); a ``rich.text.Text`` is used as given. Text written with a
        ``style`` is not highlighted.
        """
        applied = str(style) if style else None
        if isinstance(content, Text):
            self._emitter.emit(make_text(content.plain, style=applied, obj=content.copy()))
        else:
            self._emitter.emit(make_text(str(content), style=applied, markup=markup))

    def json(self, data: Any, title: str = "") -> None:
        """
        Pretty-print a dict, list, or JSON string with syntax highlighting.

        A string is shown as given (it is not validated or re-indented); anything
        else is serialised with ``json.dumps(indent=2, default=str)``. ``title`` is
        shown literally. Content method: see the class notes on scrolling.
        """
        self._emitter.emit(make_json(_snapshot(data), title or "", scroll="top"))

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
        self._emitter.emit(make_table(_snapshot_rows(rows), headers, title or "", scroll="top"))

    def csv(self, csv_string: str, title: str = "") -> None:
        """Parse a CSV string (first row = headers) and render it with ``table``. Empty input writes nothing."""
        reader  = _csv.reader(io.StringIO(csv_string.strip()))
        rows    = list(reader)
        if not rows:
            return
        headers, *data = rows
        self.table([dict(zip(headers, row, strict=False)) for row in data], headers=headers, title=title)

    def array(self, items: list, title: str = "") -> None:
        """Pretty-print a list with Rich's ``Pretty``. ``title`` is literal. Content method."""
        self._emitter.emit(make_json(_snapshot(items), title or "", pretty=True, scroll="top"))

    def pretty(self, obj: Any, title: str = "") -> None:
        """Pretty-print any Python object with Rich's ``Pretty``. ``title`` is literal. Content method."""
        self._emitter.emit(make_json(_snapshot(obj), title or "", pretty=True, scroll="top"))

    def renderable(self, obj: Any) -> None:
        """
        Write any Rich renderable directly (Table, Syntax, Panel, etc.).

        A ``str`` is written as literal text. Unlike the content methods this does
        not change scrolling.
        """
        if isinstance(obj, str):
            self._emitter.emit(make_text(obj))
        elif isinstance(obj, Text):
            self._emitter.emit(make_text(obj.plain, obj=obj.copy()))
        else:
            self._emitter.emit(make_text(f"<{type(obj).__name__}>", obj=obj if is_renderable(obj) else Pretty(obj)))
