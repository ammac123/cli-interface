"""Introspection of dataclass and pydantic v2 model instances for ``App.settings``. Stdlib only; pydantic is duck-typed."""
from __future__ import annotations

import dataclasses
import enum
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from .params import MISSING, Param, ParamSpec, _humanize, _type_hints, _unwrap, build_spec, dataclass_default

__all__ = [
    "Field",
    "Group",
    "describe",
    "format_value",
    "get_value",
    "reset_defaults",
    "secret_values",
    "set_value",
]

_MAX_DEPTH = 16


@dataclass(frozen=True)
class Field:
    """A leaf setting. ``name`` is the dotted path from the root; ``spec.name`` is the bare field name."""

    name: str
    spec: ParamSpec
    secret: bool
    default: Any


@dataclass(frozen=True)
class Group:
    name: str
    label: str


def _is_pydantic(obj: Any) -> bool:
    cls = obj if isinstance(obj, type) else type(obj)
    return hasattr(cls, "model_fields") and hasattr(cls, "model_validate")


def _is_model(obj: Any) -> bool:
    return not isinstance(obj, type) and (dataclasses.is_dataclass(obj) or _is_pydantic(obj))


def _check(obj: Any) -> None:
    if isinstance(obj, type):
        raise TypeError(f"settings model must be an instance, not the class {obj.__name__}")
    if dataclasses.is_dataclass(obj):
        if getattr(getattr(obj, "__dataclass_params__", None), "frozen", False):
            raise TypeError(f"settings model {type(obj).__name__} is a frozen dataclass and cannot be edited")
    elif _is_pydantic(obj):
        config = getattr(type(obj), "model_config", None) or {}
        if config.get("frozen"):
            raise TypeError(f"settings model {type(obj).__name__} is frozen and cannot be edited")
    else:
        raise TypeError(f"settings model must be a dataclass or pydantic v2 instance, not {type(obj).__name__}")


def _is_secret_type(value: Any) -> bool:
    return not isinstance(value, type) and callable(getattr(value, "get_secret_value", None))


def _plain(value: Any) -> Any:
    return value.get_secret_value() if _is_secret_type(value) else value


def _secret_class(annotation: Any) -> type | None:
    try:
        base, _optional, _meta = _unwrap(annotation)
    except ValueError:
        return None
    if isinstance(base, type) and callable(getattr(base, "get_secret_value", None)):
        return base
    return None


def _entries(obj: Any) -> list[tuple[str, Any, Any, Param | None, str, str | None]]:
    """(name, annotation, default, Param, description, title) for each settable field of one model level."""
    out: list[tuple[str, Any, Any, Param | None, str, str | None]] = []
    if dataclasses.is_dataclass(obj):
        hints = _type_hints(type(obj))
        for f in dataclasses.fields(obj):
            meta = f.metadata.get("param")
            out.append((f.name, hints.get(f.name, f.type), dataclass_default(f), meta if isinstance(meta, Param) else None, "", None))
        return out
    for name, info in type(obj).model_fields.items():
        if getattr(info, "frozen", False):
            continue
        meta = next((m for m in info.metadata if isinstance(m, Param)), None)
        extra = info.json_schema_extra
        if meta is None and isinstance(extra, dict) and isinstance(extra.get("param"), Param):
            meta = extra["param"]
        default: Any = MISSING
        if not info.is_required():
            try:
                default = _plain(info.get_default(call_default_factory=True))
            except Exception:
                default = MISSING
        out.append((name, info.annotation, default, meta, info.description or "", info.title))
    return out


def describe(obj: Any, secret: Collection[str] = ()) -> list[Field | Group]:
    """Depth-first flat list: each Group precedes its children; names are dotted paths from ``obj``."""
    _check(obj)
    out: list[Field | Group] = []
    _walk(obj, "", frozenset(secret), out, 0)
    return out


def _walk(obj: Any, prefix: str, secret: frozenset[str], out: list[Field | Group], depth: int) -> None:
    if depth > _MAX_DEPTH:
        return
    for name, annotation, default, meta, description, title in _entries(obj):
        if name.startswith("_"):
            continue
        path = prefix + name
        value = getattr(obj, name, None)
        if _is_model(value):
            _check(value)
            label = (meta.label if meta and meta.label else None) or title or _humanize(name)
            out.append(Group(path, label))
            _walk(value, path + ".", secret, out, depth + 1)
            continue
        secret_cls = _secret_class(annotation)
        if secret_cls is not None:
            annotation = (str | None) if _unwrap(annotation)[1] else str
        try:
            spec = build_spec(name, annotation, default, meta)
        except ValueError:
            continue
        if spec.help == "" and description:
            spec = dataclasses.replace(spec, help=description)
        if title and not (meta and meta.label):
            spec = dataclasses.replace(spec, label=title)
        is_secret = spec.secret or secret_cls is not None or name in secret or path in secret
        if is_secret and not spec.secret:
            spec = dataclasses.replace(spec, secret=True)
        out.append(Field(path, spec, is_secret, default))


def get_value(obj: Any, name: str) -> Any:
    """The current value at a dotted path; secret wrappers (``SecretStr``) are unwrapped."""
    for part in name.split("."):
        obj = getattr(obj, part)
    return _plain(obj)


def set_value(obj: Any, name: str, value: Any) -> None:
    *parents, leaf = name.split(".")
    for part in parents:
        obj = getattr(obj, part)
    current = getattr(obj, leaf, None)
    if value is not None:
        wrapper = type(current) if _is_secret_type(current) else _declared_secret_class(obj, leaf)
        if wrapper is not None:
            value = wrapper(value)
    setattr(obj, leaf, value)


def _declared_secret_class(obj: Any, leaf: str) -> type | None:
    if dataclasses.is_dataclass(obj) or not _is_pydantic(obj):
        return None
    info = type(obj).model_fields.get(leaf)
    return _secret_class(info.annotation) if info is not None else None


def reset_defaults(obj: Any, secret: Collection[str] = ()) -> list[str]:
    """Reset every field that has a default, in place; returns the dotted names that changed."""
    changed: list[str] = []
    for item in describe(obj, secret):
        if isinstance(item, Field) and item.default is not MISSING:
            if get_value(obj, item.name) != item.default:
                set_value(obj, item.name, item.default)
                changed.append(item.name)
    return changed


def secret_values(obj: Any, secret: Collection[str] = ()) -> list[str]:
    """Non-empty string values of secret fields, recursively."""
    found: list[str] = []
    for item in describe(obj, secret):
        if not (isinstance(item, Field) and item.secret):
            continue
        value = get_value(obj, item.name)
        candidates = value if isinstance(value, list | tuple | set | frozenset) else [value]
        for candidate in candidates:
            candidate = _plain(candidate)
            if isinstance(candidate, str) and candidate and candidate not in found:
                found.append(candidate)
    return found


_LIMIT = 40


def format_value(value: Any) -> str:
    """Short single-line text for a nav-bar value: None is "-", an Enum its name, a list "a, b"; cut at 40 chars."""
    if value is None:
        text = "-"
    elif isinstance(value, enum.Enum):
        text = value.name
    elif isinstance(value, list | tuple | set | frozenset):
        text = ", ".join(format_value(item) for item in value)
    else:
        text = str(value)
    text = re.sub(r"\s*[\r\n]+\s*", " ", text)
    return text if len(text) <= _LIMIT else text[: _LIMIT - 1] + "…"
