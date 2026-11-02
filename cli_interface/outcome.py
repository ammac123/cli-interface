"""
What a finished job shows: ``value_events`` maps a return value to content events plus the
``result`` summary, and ``exception_event`` builds the ``error`` event (traceback, no locals).
"""
from __future__ import annotations

import json
import os
import traceback
from collections.abc import Mapping, Sequence
from typing import Any

from .events import Event, make_error, make_json, make_table, make_text, redact_text

_TEXT_LIMIT = 50_000

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNNER_FILES = frozenset(os.path.join(_PKG_DIR, name) for name in ("jobs.py", "outcome.py"))


def _text_of(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return f"<{type(value).__name__}>"


def _dumpable(data: Any) -> bool:
    try:
        json.dumps(data)
    except (TypeError, ValueError, RecursionError):
        return False
    return True


def _copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    if isinstance(value, set):
        return set(value)
    return value


def _block_or_line(text: str) -> tuple[list[Event], str | None]:
    if "\n" in text:
        return [make_text(text)], None
    return [], text or None


def _map(value: Any) -> tuple[list[Event], str | None]:
    if isinstance(value, str):
        return _block_or_line(str.__str__(value))
    if isinstance(value, Mapping | list | tuple | set | frozenset):
        if not value:
            return [], repr(value)
        if isinstance(value, list | tuple) and all(isinstance(row, Mapping) for row in value):
            rows = [{str(key): item for key, item in row.items()} for row in value]
            headers = list(rows[0])
            if headers:
                return [make_table(rows, headers, scroll="end")], None
        data = _copy(value)
        return [make_json(data, pretty=not _dumpable(data), scroll="end")], None
    from rich.protocol import is_renderable
    from rich.text import Text

    if is_renderable(value):
        plain = value.plain if isinstance(value, Text) else f"<{type(value).__name__}>"
        return [make_text(plain, obj=value)], None
    if isinstance(value, bytes | bytearray):
        return [], repr(value)
    return _block_or_line(_text_of(value))


def value_events(value: Any, *, secret: bool) -> tuple[list[Event], str | None]:
    """
    The content events for a job's return value (to be emitted before ``result``) and the
    one-line ``result.summary``. A secret job, or ``None``, gives ``([], None)``. Never raises.
    """
    if value is None or secret:
        return [], None
    try:
        return _map(value)
    except Exception:
        return [], _text_of(value) or None


def _cap(text: str, limit: int = _TEXT_LIMIT) -> str:
    if len(text) <= limit:
        return text
    marker = f"\n... [{len(text)} characters, middle omitted] ...\n"
    keep = max(0, limit - len(marker))
    head = keep // 2
    return text[:head] + marker + text[len(text) - (keep - head):]


def _is_runner_frame(frame: traceback.FrameSummary) -> bool:
    return os.path.abspath(frame.filename) in _RUNNER_FILES


def _trim(te: traceback.TracebackException, seen: set[int]) -> None:
    if id(te) in seen:
        return
    seen.add(id(te))
    frames = [frame for frame in te.stack if not _is_runner_frame(frame)]
    if frames:
        te.stack = traceback.StackSummary.from_list(frames)
    for child in (te.__cause__, te.__context__, *(getattr(te, "exceptions", None) or ())):
        if child is not None:
            _trim(child, seen)


def _format_traceback(exc: BaseException) -> str:
    try:
        te = traceback.TracebackException(type(exc), exc, exc.__traceback__, capture_locals=False)
        _trim(te, set())
        return "".join(te.format())
    except Exception:
        return "".join(traceback.format_exception_only(type(exc), exc))


def exception_event(exc: BaseException, label: str, secrets: Sequence[str]) -> Event:
    """
    The ``error`` event for ``exc``: ``message`` is ``str(exc)``, ``traceback`` the formatted
    chain without the runner's own frames and without locals. Both are redacted and capped.
    """
    message = _cap(redact_text(_text_of(exc), secrets))
    trace = _cap(redact_text(_format_traceback(exc), secrets))
    return make_error(
        redact_text(label, secrets),
        message,
        exc_type=type(exc).__name__,
        traceback=trace or None,
    )
