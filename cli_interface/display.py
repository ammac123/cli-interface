from __future__ import annotations

import csv as _csv
import io
import json as _json
from typing import Any

from rich.pretty import Pretty
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from textual.widgets import RichLog

from .theme import LEVEL_STYLES, _DIM_FG, _MAX_LOG_LINES, _ORANGE


class DisplayPanel:
    """
    General-purpose display panel.

    Push any content here — log lines, JSON, tables, CSVs, raw text, or
    arbitrary Rich renderables. Attach a Python logger via
    ``attach_logging(app)`` to have log records flow in automatically.

    When only ``log()`` calls are made since the last ``clear()``, the panel
    operates in log mode: a rolling buffer is maintained and the oldest two
    entries are rendered with a fade effect. Calling any other method
    (json, table, rule, etc.) switches to append mode for the remainder of
    that view.

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
        self._log_buffer: list[tuple[str, str]] = []
        self._log_only        = True
        self._scrolled_to_top = False

    def clear(self) -> None:
        self._w.clear()
        self._log_buffer      = []
        self._log_only        = True
        self._scrolled_to_top = False
        self._w.auto_scroll   = True

    # ------------------------------------------------------------------
    # Content-mode helpers

    def _enter_content_mode(self) -> None:
        """Switch to content mode: disable auto-scroll before writing."""
        self._log_only      = False
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
    # Log mode — rolling buffer with fade effect on oldest entries

    def _render_log_buffer(self) -> None:
        """Clear and re-render the full log buffer, fading the two oldest entries."""
        self._w.clear()
        n = len(self._log_buffer)
        for i, (msg, level) in enumerate(self._log_buffer):
            style = LEVEL_STYLES.get(level, "")
            if i == 0 and n >= 2:
                # Oldest entry fades to dim gray
                self._w.write(f"[{_DIM_FG}]{msg}[/]")
            elif i == 1 and n >= 3:
                # Second oldest gets a dim tint of its level color
                dim_style = f"dim {style}" if style else f"dim {_DIM_FG}"
                self._w.write(f"[{dim_style}]{msg}[/]")
            else:
                self._w.write(f"[{style}]{msg}[/]" if style else msg)

    def log(self, message: str, level: str = "INFO") -> None:
        """Coloured log line. level: DEBUG | INFO | WARNING | ERROR | CRITICAL"""
        if not self._log_only:
            style = LEVEL_STYLES.get(level.upper(), "")
            self._w.write(f"[{style}]{message}[/]" if style else message)
            return

        self._log_buffer.append((message, level.upper()))
        overflow = len(self._log_buffer) > _MAX_LOG_LINES
        if overflow:
            self._log_buffer.pop(0)

        n = len(self._log_buffer)
        if n >= 4 and not overflow:
            # Fast path: the two faded entries haven't changed — just append
            style = LEVEL_STYLES.get(level.upper(), "")
            self._w.write(f"[{style}]{message}[/]" if style else message)
        else:
            # Fading boundaries shifted or buffer wrapped — full re-render
            self._render_log_buffer()

    # ------------------------------------------------------------------
    # Append mode — non-log content disables fade buffering for this view

    def rule(self, title: str = "") -> None:
        """Horizontal divider, optionally titled."""
        self._log_only = False
        self._w.write(Rule(title, style=_ORANGE))

    def text(self, content: str, style: str = "") -> None:
        """Plain text, optionally with a Rich style string."""
        self._log_only = False
        if style:
            self._w.write(Text.from_markup(f"[{style}]{content}[/]"))
        else:
            self._w.write(content)

    def json(self, data: Any, title: str = "") -> None:
        """Pretty-print a dict, list, or JSON string with syntax highlighting."""
        self._enter_content_mode()
        raw = data if isinstance(data, str) else _json.dumps(data, indent=2, default=str)
        if title:
            self._w.write(Rule(title, style=_ORANGE))
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
        lists/tuples (pass ``headers`` to name the columns).
        """
        self._enter_content_mode()
        tbl = Table(
            title=title or None,
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
        self._snap_to_top()

    def csv(self, csv_string: str, title: str = "") -> None:
        """Parse and render a CSV string as a table."""
        self._log_only = False
        reader  = _csv.reader(io.StringIO(csv_string.strip()))
        rows    = list(reader)
        if not rows:
            return
        headers, *data = rows
        self.table([dict(zip(headers, row)) for row in data], headers=headers, title=title)

    def array(self, items: list, title: str = "") -> None:
        """Pretty-print a list."""
        self._enter_content_mode()
        if title:
            self._w.write(Rule(title, style=_ORANGE))
        self._w.write(Pretty(items))
        self._snap_to_top()

    def pretty(self, obj: Any, title: str = "") -> None:
        """Pretty-print any Python object."""
        self._enter_content_mode()
        if title:
            self._w.write(Rule(title, style=_ORANGE))
        self._w.write(Pretty(obj))
        self._snap_to_top()

    def renderable(self, obj: Any) -> None:
        """Write any Rich renderable directly (Table, Syntax, Panel, etc.)."""
        self._log_only = False
        self._w.write(obj)
