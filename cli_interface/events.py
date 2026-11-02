"""Event schema v1: dict shapes, constructors, validation, drop policy, redaction and JSON lines. Stdlib only."""
from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final, Literal, Protocol, runtime_checkable

SCHEMA_VERSION: Final = 1
KINDS: Final[tuple[str, ...]] = ("hello", "log", "progress", "text", "json", "table", "result", "error")
LOCAL_KINDS: Final[frozenset[str]] = frozenset({"clear", "action"})
DROPPABLE_KINDS: Final[frozenset[str]] = frozenset({"log", "text"})
PROTECTED_KINDS: Final[frozenset[str]] = (frozenset(KINDS) | LOCAL_KINDS) - DROPPABLE_KINDS

Event = dict[str, Any]

_PROTO_VERSION: Final = 1
_MASK: Final = "***"
_LEVELS: Final[dict[str, int]] = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_FORMATTER: Final = logging.Formatter()


@runtime_checkable
class EventSink(Protocol):
    """Anything that accepts events; thread-safety is a property of the implementation."""

    def emit(self, event: Event) -> None: ...


def is_droppable(event: Mapping[str, Any]) -> bool:
    """True for kinds the inbox may drop under overflow; unknown kinds are protected."""
    kind = event.get("kind")
    return isinstance(kind, str) and kind in DROPPABLE_KINDS


def level_number(level: str) -> int:
    """Standard logging number for a level name (case-insensitive); 0 for anything unknown."""
    if not isinstance(level, str):
        return 0
    return _LEVELS.get(level.upper(), 0)


def _str(value: Any) -> str:
    return value if isinstance(value, str) else str(value)


def _base(kind: str, t: float | None = None) -> Event:
    return {"v": SCHEMA_VERSION, "t": time.time() if t is None else float(t), "kind": kind}


def make_hello(
    app: str,
    *,
    version: str | None = None,
    source: Literal["inprocess", "subprocess"] = "inprocess",
    pid: int | None = None,
) -> Event:
    """Build a ``hello`` event."""
    event = _base("hello")
    event.update(
        app=_str(app),
        proto=_PROTO_VERSION,
        source=source,
        pid=os.getpid() if pid is None else pid,
        version=version,
    )
    return event


def make_log(
    msg: str,
    level: str = "INFO",
    *,
    logger: str | None = None,
    levelno: int | None = None,
    exc: str | None = None,
    markup: bool = False,
    t: float | None = None,
) -> Event:
    """Build a ``log`` event; ``level`` is upper-cased and ``levelno`` defaults from it."""
    name = _str(level).upper()
    event = _base("log", t)
    event.update(
        level=name,
        levelno=level_number(name) if levelno is None else levelno,
        msg=_str(msg),
        logger=logger,
        exc=exc,
        markup=markup,
    )
    return event


def make_log_from_record(record: logging.LogRecord) -> Event:
    """Build a ``log`` event from a record: ``msg`` is ``getMessage()``, ``exc`` the preformatted traceback text."""
    exc: str | None = record.exc_text or None
    if exc is None and record.exc_info and record.exc_info[0] is not None:
        exc = _FORMATTER.formatException(record.exc_info)
    if record.stack_info:
        stack = _FORMATTER.formatStack(record.stack_info)
        exc = f"{exc}\n{stack}" if exc else stack
    return make_log(
        record.getMessage(),
        record.levelname,
        logger=record.name,
        levelno=record.levelno,
        exc=exc,
        t=record.created,
    )


def make_progress(
    *,
    id: str = "default",
    label: str = "",
    current: float | None = None,
    total: float | None = None,
    done: bool = False,
) -> Event:
    """Build a ``progress`` event."""
    event = _base("progress")
    event.update(id=_str(id), label=_str(label), current=current, total=total, done=done)
    return event


def make_text(
    text: str,
    *,
    style: str | None = None,
    markup: bool = False,
    stream: Literal["stdout", "stderr"] | None = None,
    rule: bool = False,
    obj: Any = None,
) -> Event:
    """Build a ``text`` event; ``obj`` (a local Rich renderable) is added only when given."""
    event = _base("text")
    event.update(text=_str(text), style=style, markup=markup, stream=stream, rule=rule)
    if obj is not None:
        event["obj"] = obj
    return event


def make_json(data: Any, title: str = "", *, pretty: bool = False, scroll: Literal["top", "end"] = "end") -> Event:
    """Build a ``json`` event."""
    event = _base("json")
    event.update(data=data, title=_str(title), pretty=pretty, scroll=scroll)
    return event


def make_table(
    rows: Iterable[Any],
    headers: Iterable[str] | None = None,
    title: str = "",
    *,
    scroll: Literal["top", "end"] = "end",
) -> Event:
    """Build a ``table`` event; ``rows`` and ``headers`` are copied into lists."""
    event = _base("table")
    event.update(
        rows=list(rows),
        headers=None if headers is None else list(headers),
        title=_str(title),
        scroll=scroll,
    )
    return event


def make_result(
    label: str,
    *,
    status: Literal["ok", "cancelled"] = "ok",
    summary: str | None = None,
    exit_code: int | None = None,
) -> Event:
    """Build a ``result`` event."""
    event = _base("result")
    event.update(label=_str(label), status=status, summary=summary, exit_code=exit_code)
    return event


def make_error(
    label: str,
    message: str,
    *,
    exc_type: str | None = None,
    traceback: str | None = None,
    exit_code: int | None = None,
) -> Event:
    """Build an ``error`` event."""
    event = _base("error")
    event.update(
        label=_str(label), message=_str(message), exc_type=exc_type, traceback=traceback, exit_code=exit_code
    )
    return event


def make_clear() -> Event:
    """Build the local-only ``clear`` event."""
    return _base("clear")


def make_action(phase: Literal["begin", "end"]) -> Event:
    """Build the local-only ``action`` event."""
    event = _base("action")
    event["phase"] = phase
    return event


# ----------------------------------------------------------------------
# Validation

_Check = tuple[Callable[[Any], bool], str]


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return _is_int(value)


def _one_of(*allowed: str | None) -> _Check:
    return (lambda value: isinstance(value, str | None) and value in allowed), "one of " + ", ".join(map(repr, allowed))


def _list_of_rows(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(row, Mapping | list | tuple) for row in value)


def _list_of_str(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


_ANY: Final[_Check] = (lambda value: True, "any value")
_STR: Final[_Check] = (lambda value: isinstance(value, str), "str")
_OPT_STR: Final[_Check] = (lambda value: value is None or isinstance(value, str), "str or None")
_BOOL: Final[_Check] = (lambda value: isinstance(value, bool), "bool")
_INT: Final[_Check] = (_is_int, "int")
_OPT_INT: Final[_Check] = (lambda value: value is None or _is_int(value), "int or None")
_OPT_NUMBER: Final[_Check] = (lambda value: value is None or _is_number(value), "finite number or None")
_UPPER: Final[_Check] = (lambda value: isinstance(value, str) and value == value.upper(), "upper-case str")
_SCROLL: Final[_Check] = _one_of("top", "end")
_COMMON: Final[dict[str, _Check]] = {
    "v": (lambda value: value == SCHEMA_VERSION and _is_int(value), f"int {SCHEMA_VERSION}"),
    "t": (_is_number, "finite number"),
    "kind": (lambda value: isinstance(value, str), "str"),
}
_REQUIRED: Final[dict[str, dict[str, _Check]]] = {
    "hello": {
        "app": _STR,
        "proto": _INT,
        "source": _one_of("inprocess", "subprocess"),
        "pid": _INT,
        "version": _OPT_STR,
    },
    "log": {
        "level": _UPPER,
        "levelno": _INT,
        "msg": _STR,
        "logger": _OPT_STR,
        "exc": _OPT_STR,
        "markup": _BOOL,
    },
    "progress": {
        "id": _STR,
        "label": _STR,
        "current": _OPT_NUMBER,
        "total": _OPT_NUMBER,
        "done": _BOOL,
    },
    "text": {
        "text": _STR,
        "style": _OPT_STR,
        "markup": _BOOL,
        "stream": _one_of("stdout", "stderr", None),
        "rule": _BOOL,
    },
    "json": {"data": _ANY, "title": _STR, "pretty": _BOOL, "scroll": _SCROLL},
    "table": {
        "rows": (_list_of_rows, "list of dicts or lists"),
        "headers": (lambda value: value is None or _list_of_str(value), "list of str or None"),
        "title": _STR,
        "scroll": _SCROLL,
    },
    "result": {
        "label": _STR,
        "status": _one_of("ok", "cancelled"),
        "summary": _OPT_STR,
        "exit_code": _OPT_INT,
    },
    "error": {
        "label": _STR,
        "message": _STR,
        "exc_type": _OPT_STR,
        "traceback": _OPT_STR,
        "exit_code": _OPT_INT,
    },
    "clear": {},
    "action": {"phase": _one_of("begin", "end")},
}
_OPTIONAL: Final[dict[str, dict[str, _Check]]] = {
    kind: {"job": _INT} | ({"obj": _ANY} if kind == "text" else {}) for kind in _REQUIRED
}


def validate_event(event: Mapping[str, Any]) -> list[str]:
    """Return a list of problems with ``event`` against schema v1; an empty list means valid. Never raises."""
    if not isinstance(event, Mapping):
        return [f"event must be a mapping, got {type(event).__name__}"]
    problems: list[str] = []
    raw = event.get("kind")
    kind = raw if isinstance(raw, str) and raw in _REQUIRED else None
    if isinstance(raw, str) and kind is None:
        problems.append(f"unknown kind {raw!r}")
    required = {**_COMMON, **_REQUIRED[kind]} if kind is not None else _COMMON
    optional = _OPTIONAL[kind] if kind is not None else {"job": _INT}
    for name, (check, expected) in required.items():
        if name not in event:
            problems.append(f"missing field {name!r}")
        elif not check(event[name]):
            problems.append(f"field {name!r} must be {expected}, got {type(event[name]).__name__}")
    for name, (check, expected) in optional.items():
        if name in event and not check(event[name]):
            problems.append(f"field {name!r} must be {expected}, got {type(event[name]).__name__}")
    if kind is not None:
        for name in event:
            if name not in required and name not in optional:
                problems.append(f"unexpected field {name!r} for kind {kind!r}")
    return problems


# ----------------------------------------------------------------------
# Encoding

def _jsonable(value: Any, seen: tuple[int, ...] = ()) -> Any:
    if isinstance(value, Mapping | list | tuple):
        if id(value) in seen or len(seen) > 100:
            return "<circular>"
        seen += (id(value),)
        if isinstance(value, Mapping):
            return {str(key): _jsonable(item, seen) for key, item in value.items()}
        return [_jsonable(item, seen) for item in value]
    return value


def dumps(event: Mapping[str, Any]) -> str:
    """Encode an event as one JSON line: the local-only ``obj`` key is dropped, unknown values go through ``str``."""
    payload = {key: value for key, value in event.items() if key != "obj"}
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError, RecursionError):
        return json.dumps(_jsonable(payload), default=str)


# ----------------------------------------------------------------------
# Redaction

_REDACT_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "log": ("msg", "exc"),
    "text": ("text",),
    "progress": ("label",),
    "result": ("label", "summary"),
    "error": ("label", "message", "traceback"),
}


def _mask_pattern(secrets: Iterable[str]) -> re.Pattern[str] | None:
    if isinstance(secrets, str):
        secrets = (secrets,)
    found = sorted({s for s in secrets if isinstance(s, str) and s}, key=len, reverse=True)
    return re.compile("|".join(map(re.escape, found))) if found else None


def redact_text(text: str, secrets: Iterable[str]) -> str:
    """Replace every secret in ``text`` with ``***``, longest first; empty and non-str secrets are ignored."""
    pattern = _mask_pattern(secrets)
    return text if pattern is None else pattern.sub(_MASK, text)


def redact_event(event: Event, secrets: Sequence[str]) -> Event:
    """Return a copy of ``event`` with the secrets masked in its text fields; ``json``/``table`` data are left alone."""
    copy = dict(event)
    kind = copy.get("kind")
    pattern = _mask_pattern(secrets)
    if pattern is not None and isinstance(kind, str):
        for name in _REDACT_FIELDS.get(kind, ()):
            value = copy.get(name)
            if isinstance(value, str):
                copy[name] = pattern.sub(_MASK, value)
    return copy
