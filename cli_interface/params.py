"""Parameter schema, derivation from signatures/dataclasses/argparse, and string-to-value conversion. Stdlib only."""
from __future__ import annotations

import argparse
import dataclasses
import enum
import inspect
import math
import sys
import types
import typing
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated, Any, Final, Literal, Union, get_args, get_origin, get_type_hints

__all__ = [
    "MISSING",
    "FormContext",
    "Kind",
    "Param",
    "ParamError",
    "ParamSpec",
    "Secret",
    "build_spec",
    "call_with_ctx",
    "convert",
    "initial_text",
    "pack",
    "resolve_choices",
    "specs_from_argparse",
    "specs_from_dataclass",
    "specs_from_signature",
    "validate_all",
]


class _Missing:
    """Sentinel for "no default"."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False

    def __copy__(self) -> _Missing:
        return self

    def __deepcopy__(self, memo: Any) -> _Missing:
        return self

    def __reduce__(self) -> str:
        return "MISSING"


MISSING: Final = _Missing()

Kind = Literal["text", "int", "float", "bool", "choice", "multi", "path", "list"]
ChoicesArg = Iterable[Any] | Callable[..., Iterable[Any]] | None


@dataclass(frozen=True)
class Param:
    """
    Metadata for a command parameter or settings field, as ``Annotated[T, Param(...)]`` or
    ``field(metadata={"param": Param(...)})``. ``choices`` is an iterable (of values or
    ``(value, label)`` pairs) or a callable taking a ``FormContext``; ``validate`` raises
    ``ValueError`` to reject a value; ``min`` and ``max`` bound a number.
    """

    label: str | None = None
    help: str = ""
    choices: ChoicesArg = None
    secret: bool = False
    validate: Callable[[Any], Any] | None = None
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Secret(Param):
    """A ``Param`` with ``secret=True``: ``Annotated[str, Secret()]``. Masked, and its value is redacted."""

    secret: bool = True


@dataclass(frozen=True)
class ParamSpec:
    name: str
    kind: Kind
    label: str
    help: str = ""
    default: Any = MISSING
    optional: bool = False
    choices: ChoicesArg = None
    item_kind: Kind | None = None
    secret: bool = False
    min: float | None = None
    max: float | None = None
    validate: Callable[[Any], Any] | None = None
    enum_type: type | None = None
    convert_fn: Callable[[str], Any] | None = None

    @property
    def required(self) -> bool:
        return self.default is MISSING and not self.optional


class ParamError(ValueError):
    """A user-facing message for one field."""


@dataclass
class FormContext:
    state: SimpleNamespace = field(default_factory=SimpleNamespace)


class _Blank(Exception):
    """Internal: the raw input counts as empty."""


class _Unsupported(ValueError):
    """The annotation cannot be shown as a form field."""


# --------------------------------------------------------------------------- choices

def _label_of(value: Any) -> str:
    return value.name if isinstance(value, enum.Enum) else str(value)


def _normalize_choices(items: Iterable[Any]) -> list[tuple[Any, str]]:
    out: list[tuple[Any, str]] = []
    for item in items:
        if isinstance(item, tuple) and len(item) == 2:
            out.append((item[0], str(item[1])))
        else:
            out.append((item, _label_of(item)))
    return out


def call_with_ctx(fn: Callable[..., Any], ctx: Any) -> Any:
    """Call ``fn()`` or ``fn(ctx)`` depending on whether it accepts a positional argument."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (ValueError, TypeError):
        return fn()
    takes_one = any(
        p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL) for p in params
    )
    return fn(ctx) if takes_one else fn()


def resolve_choices(spec: ParamSpec, fctx: FormContext) -> list[tuple[Any, str]]:
    source = spec.choices
    if source is None:
        return []
    if callable(source):
        source = call_with_ctx(source, fctx)
    return _normalize_choices(source)


def _options(spec: ParamSpec, choices: Sequence[tuple[Any, str]] | None) -> list[tuple[Any, str]]:
    if choices is not None:
        return list(choices)
    if spec.choices is None or callable(spec.choices):
        return []
    return _normalize_choices(spec.choices)


# --------------------------------------------------------------------------- derivation

def _humanize(name: str) -> str:
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _type_name(annotation: Any) -> str:
    return getattr(annotation, "__name__", None) or repr(annotation)


_SCALARS: dict[Any, Kind] = {str: "text", int: "int", float: "float", Path: "path", bool: "bool"}


def _unwrap(annotation: Any) -> tuple[Any, bool, Param | None]:
    """Strip Annotated, Optional, NewType and type aliases: (base, optional, first Param)."""
    optional = False
    meta: Param | None = None
    ann = annotation
    for _ in range(32):
        origin = get_origin(ann)
        if origin is Annotated:
            args = get_args(ann)
            ann = args[0]
            if meta is None:
                meta = next((e for e in args[1:] if isinstance(e, Param)), None)
        elif origin is Union or origin is types.UnionType:
            args = get_args(ann)
            members = [a for a in args if a is not type(None)]
            optional = optional or len(members) != len(args)
            if len(members) != 1:
                raise _Unsupported(f"unsupported type {annotation!r}")
            ann = members[0]
        elif isinstance(ann, typing.TypeAliasType):
            ann = ann.__value__
        elif hasattr(ann, "__supertype__"):
            ann = ann.__supertype__
        else:
            break
    return ann, optional, meta


def _enum_choices(cls: type[enum.Enum]) -> list[tuple[Any, str]]:
    return [(member, member.name) for member in cls]


def _literal_choices(ann: Any) -> tuple[list[tuple[Any, str]], bool]:
    values = list(get_args(ann))
    optional = any(v is None for v in values)
    values = [v for v in values if v is not None]
    if not values:
        raise _Unsupported(f"unsupported type {ann!r}")
    return [(v, _label_of(v)) for v in values], optional


@dataclass
class _Shape:
    kind: Kind
    optional: bool = False
    choices: list[tuple[Any, str]] | None = None
    item_kind: Kind | None = None
    enum_type: type | None = None


def _shape_of(ann: Any) -> _Shape:
    origin = get_origin(ann)
    if origin is Literal:
        choices, optional = _literal_choices(ann)
        return _Shape("choice", optional, choices)
    if isinstance(ann, type):
        if issubclass(ann, enum.Enum):
            return _Shape("choice", False, _enum_choices(ann), enum_type=ann)
        if dataclasses.is_dataclass(ann):
            raise _Unsupported(f"nested dataclass {ann.__name__} is not supported; use app.settings for nested models")
        if ann in _SCALARS:
            return _Shape(_SCALARS[ann])
        if issubclass(ann, Path):
            return _Shape("path")
    if ann is list or origin is list:
        args = get_args(ann)
        if not args:
            return _Shape("list", item_kind="text")
        item, item_optional, _ = _unwrap(args[0])
        if item_optional:
            raise _Unsupported(f"unsupported type {ann!r}")
        if get_origin(item) is Literal:
            choices, _opt = _literal_choices(item)
            return _Shape("multi", choices=choices)
        if isinstance(item, type) and issubclass(item, enum.Enum):
            return _Shape("multi", choices=_enum_choices(item), enum_type=item)
        if item in (str, int, float, Path):
            return _Shape("list", item_kind=_SCALARS[item])
    raise _Unsupported(f"unsupported type {_type_name(ann)}")


def _shape_from_default(default: Any) -> _Shape:
    if default is MISSING or default is None:
        return _Shape("text", optional=default is None)
    if isinstance(default, enum.Enum):
        cls = type(default)
        return _Shape("choice", False, _enum_choices(cls), enum_type=cls)
    for typ, kind in _SCALARS.items():
        if type(default) is typ:
            return _Shape(kind)
    if isinstance(default, Path):
        return _Shape("path")
    raise _Unsupported(f"unsupported default {default!r}")


def build_spec(
    name: str,
    annotation: Any = inspect.Parameter.empty,
    default: Any = MISSING,
    meta: Param | None = None,
) -> ParamSpec:
    """One ParamSpec from an annotation and default; raises ValueError (subclass) if the type is unsupported."""
    if annotation is inspect.Parameter.empty:
        shape = _shape_from_default(default)
        found = None
    else:
        base, optional, found = _unwrap(annotation)
        shape = _shape_of(base)
        shape.optional = shape.optional or optional
    meta = meta if meta is not None else found
    if default is None:
        shape.optional = True
    choices: Any = shape.choices
    kind: Kind = shape.kind
    item_kind = shape.item_kind
    if kind == "bool" and shape.optional:
        kind, choices = "choice", [(True, "Yes"), (False, "No")]
    if meta is not None and meta.choices is not None:
        choices = meta.choices if callable(meta.choices) else list(meta.choices)
        if kind == "list":
            kind, item_kind = "multi", None
        elif kind in ("text", "int", "float", "path", "bool"):
            kind = "choice"
    if kind == "multi":
        item_kind = None
    if kind not in ("choice", "multi"):
        choices = None
    return ParamSpec(
        name=name,
        kind=kind,
        label=(meta.label if meta and meta.label else None) or _humanize(name),
        help=meta.help if meta else "",
        default=default,
        optional=shape.optional,
        choices=choices,
        item_kind=item_kind,
        secret=bool(meta and meta.secret),
        min=meta.min if meta else None,
        max=meta.max if meta else None,
        validate=meta.validate if meta else None,
        enum_type=shape.enum_type,
    )


def _annotation_resolver(fn: Callable[..., Any]) -> Callable[[Any], Any]:
    target: Any = fn
    try:
        target = inspect.unwrap(fn)
    except ValueError:
        pass
    namespace = getattr(target, "__globals__", None) or getattr(type(target).__call__, "__globals__", {})

    def resolve(annotation: Any) -> Any:
        for _ in range(3):
            if not isinstance(annotation, str):
                break
            try:
                annotation = eval(annotation, dict(namespace))
            except Exception:
                break
        return annotation

    return resolve


def specs_from_signature(fn: Callable[..., Any], *, strict: bool) -> list[ParamSpec]:
    from .jobs import _asks_context

    fname = getattr(fn, "__qualname__", None) or getattr(fn, "__name__", None) or repr(fn)
    try:
        sig = inspect.signature(fn, eval_str=True)
    except Exception:
        try:
            sig = inspect.signature(fn)
        except (ValueError, TypeError):
            return []
    resolve = _annotation_resolver(fn)
    specs: list[ParamSpec] = []
    for p in sig.parameters.values():
        p = p.replace(annotation=resolve(p.annotation))
        if p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD) or _asks_context(p):
            continue
        default = MISSING if p.default is p.empty else p.default
        if p.kind is p.POSITIONAL_ONLY:
            if default is MISSING:
                raise ValueError(f"{fname}: positional-only parameter '{p.name}' cannot be filled from a form")
            continue
        try:
            specs.append(build_spec(p.name, p.annotation, default))
        except _Unsupported as exc:
            if strict or default is MISSING:
                raise ValueError(f"Cannot build a form for {fname}(): parameter '{p.name}': {exc}") from exc
    return specs


def specs_from_dataclass(cls: type) -> list[ParamSpec]:
    if not (isinstance(cls, type) and dataclasses.is_dataclass(cls)):
        raise TypeError(f"{cls!r} is not a dataclass class")
    hints = _type_hints(cls)
    return [_dataclass_spec(cls, f, hints) for f in dataclasses.fields(cls) if f.init]


def _resolve_text(annotation: Any, namespace: Mapping[str, Any]) -> Any:
    for _ in range(3):
        if not isinstance(annotation, str):
            break
        try:
            annotation = eval(annotation, dict(namespace))
        except Exception:
            break
    return annotation


def _type_hints(cls: type) -> dict[str, Any]:
    """Resolved annotations of a dataclass; a field whose annotation cannot be resolved keeps its raw string."""
    try:
        return get_type_hints(cls, include_extras=True)
    except Exception:
        pass
    module = sys.modules.get(cls.__module__)
    namespace = {**vars(module), **vars(cls)} if module else dict(vars(cls))
    return {f.name: _resolve_text(f.type, namespace) for f in dataclasses.fields(cls)}


def dataclass_default(f: dataclasses.Field[Any]) -> Any:
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    return MISSING


def _dataclass_spec(cls: type, f: dataclasses.Field[Any], hints: Mapping[str, Any]) -> ParamSpec:
    meta = f.metadata.get("param")
    try:
        return build_spec(f.name, hints.get(f.name, f.type), dataclass_default(f), meta if isinstance(meta, Param) else None)
    except _Unsupported as exc:
        raise ValueError(f"{cls.__name__}.{f.name}: {exc}") from exc


_ARGPARSE_ACTIONS = (argparse._StoreAction, argparse._StoreTrueAction, argparse._StoreFalseAction)


def _argparse_help(parser: argparse.ArgumentParser, action: argparse.Action) -> str:
    text = action.help
    if not text or text == argparse.SUPPRESS:
        return ""
    params = {"default": action.default, "prog": parser.prog, "dest": action.dest, "choices": action.choices}
    try:
        return text % params
    except (KeyError, ValueError, TypeError):
        return text


def _argparse_kind(action: argparse.Action) -> tuple[Kind, Callable[[str], Any] | None]:
    typ = action.type
    if typ is None or typ is str:
        return "text", None
    if typ is int:
        return "int", None
    if typ is float:
        return "float", None
    if typ is Path:
        return "path", None
    return "text", typ  # type: ignore[return-value]


def specs_from_argparse(parser: argparse.ArgumentParser, meta: Mapping[str, Param] | None = None) -> list[ParamSpec]:
    meta = meta or {}
    specs: list[ParamSpec] = []
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if type(action) not in _ARGPARSE_ACTIONS:
            raise ValueError(f"argparse action {type(action).__name__} for '{action.dest}' is not supported")
        name = action.dest
        param = meta.get(name)
        default: Any = action.default
        optional = False
        if isinstance(action, argparse._StoreTrueAction | argparse._StoreFalseAction):
            kind: Kind = "bool"
            convert_fn = None
            item_kind: Kind | None = None
            choices: Any = None
        else:
            kind, convert_fn = _argparse_kind(action)
            item_kind = None
            choices = None
            nargs = action.nargs
            if nargs in ("+", "*"):
                item_kind, kind = kind, "list"
                if nargs == "*" and default is None:
                    default = []
            elif nargs == "?":
                optional = True
            elif nargs is not None:
                raise ValueError(f"argparse nargs={nargs!r} for '{name}' is not supported")
            if action.choices is not None:
                choices = _normalize_choices(action.choices)
                kind, item_kind = ("multi" if kind == "list" else "choice"), None
                convert_fn = None
        if isinstance(default, str) and default == argparse.SUPPRESS:
            default, optional = MISSING, True
        elif default is None:
            if action.required:
                default = MISSING
            else:
                optional = True
        if param is not None and param.choices is not None:
            choices = param.choices if callable(param.choices) else list(param.choices)
            if kind == "list":
                kind, item_kind = "multi", None
            elif kind != "multi":
                kind = "choice"
        specs.append(
            ParamSpec(
                name=name,
                kind=kind,
                label=(param.label if param and param.label else None) or _humanize(name),
                help=(param.help if param and param.help else _argparse_help(parser, action)),
                default=default,
                optional=optional,
                choices=choices,
                item_kind=item_kind,
                secret=bool(param and param.secret),
                min=param.min if param else None,
                max=param.max if param else None,
                validate=param.validate if param else None,
                convert_fn=convert_fn,
            )
        )
    return specs


# --------------------------------------------------------------------------- conversion

def _num(n: float) -> str:
    return str(int(n)) if float(n).is_integer() else str(n)


def _convert_scalar(spec: ParamSpec, kind: Kind, text: str) -> Any:
    value: Any
    if kind == "int":
        try:
            value = int(text.strip())
        except ValueError:
            raise ParamError("Enter a whole number") from None
    elif kind == "float":
        try:
            value = float(text.strip())
        except ValueError:
            raise ParamError("Enter a number") from None
        if not math.isfinite(value):
            raise ParamError("Enter a number")
    elif kind == "path":
        return Path(text)
    elif spec.convert_fn is not None:
        try:
            return spec.convert_fn(text)
        except (ValueError, TypeError, argparse.ArgumentTypeError) as exc:
            raise ParamError("Invalid value" if spec.secret else (str(exc) or "Invalid value")) from None
    else:
        return text
    if spec.min is not None and value < spec.min:
        raise ParamError(f"Must be at least {_num(spec.min)}")
    if spec.max is not None and value > spec.max:
        raise ParamError(f"Must be at most {_num(spec.max)}")
    return value


def _to_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0"):
            return False
    raise ParamError("Enter yes or no")


def _match_option(raw: Any, options: Sequence[tuple[Any, str]]) -> Any:
    for value, _label in options:
        if value == raw and type(value) is type(raw):
            return value
    for value, _label in options:
        if value == raw:
            return value
    if isinstance(raw, str):
        for value, label in options:
            if label == raw or str(value) == raw:
                return value
    raise ParamError("Choose one of: " + ", ".join(label for _v, label in options))


def _is_blank(spec: ParamSpec, raw: Any) -> bool:
    if raw is None:
        return True
    if spec.kind in ("choice", "bool") or (spec.kind == "text" and spec.convert_fn is None):
        return False
    if spec.kind == "multi":
        return isinstance(raw, list | tuple | set) and len(raw) == 0
    if isinstance(raw, str):
        return raw.strip() == ""
    return False


def _convert_value(spec: ParamSpec, raw: Any, options: Sequence[tuple[Any, str]]) -> Any:
    kind = spec.kind
    if kind == "bool":
        return _to_bool(raw)
    if kind == "choice":
        if not options:
            raise ParamError("No choices available")
        return _match_option(raw, options)
    if kind == "multi":
        if not options:
            raise ParamError("No choices available")
        items = [raw] if isinstance(raw, str) or not isinstance(raw, Iterable) else list(raw)
        return [_match_option(item, options) for item in items]
    if kind == "list":
        parts = list(raw) if isinstance(raw, list | tuple) else str(raw).split(",")
        texts = [str(p).strip() for p in parts]
        texts = [t for t in texts if t]
        if not texts:
            raise _Blank
        item_kind = spec.item_kind or "text"
        return [_convert_scalar(spec, item_kind, t) for t in texts]
    return _convert_scalar(spec, kind, raw if isinstance(raw, str) else str(raw))


def convert(spec: ParamSpec, raw: Any, choices: Sequence[tuple[Any, str]] | None = None) -> Any:
    options = _options(spec, choices)
    if spec.kind == "text" and spec.convert_fn is None and isinstance(raw, str) and raw == "":
        if spec.optional:
            return None
        if spec.default is MISSING:
            raise ParamError("Required")
        return ""
    try:
        if _is_blank(spec, raw):
            raise _Blank
        value = _convert_value(spec, raw, options)
    except _Blank:
        if spec.optional:
            return None
        if spec.default is not MISSING:
            return spec.default
        if spec.kind in ("choice", "multi") and not options:
            raise ParamError("No choices available") from None
        raise ParamError("Required") from None
    if spec.validate is not None:
        try:
            spec.validate(value)
        except ValueError as exc:
            msg = str(exc) or "Invalid value"
        except Exception:
            msg = "Invalid value"
        else:
            return value
        raise ParamError("Invalid value" if spec.secret else msg) from None
    return value


def validate_all(
    specs: Sequence[ParamSpec],
    raw: Mapping[str, Any],
    choices: Mapping[str, Sequence[tuple[Any, str]]] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for spec in specs:
        try:
            values[spec.name] = convert(spec, raw.get(spec.name), choices.get(spec.name) if choices else None)
        except ParamError as exc:
            errors[spec.name] = str(exc)
    return values, errors


def initial_text(spec: ParamSpec) -> str:
    default = spec.default
    if spec.secret or default is MISSING or default is None:
        return ""
    if isinstance(default, enum.Enum):
        return default.name
    if isinstance(default, list | tuple | set | frozenset):
        return ", ".join(_label_of(item) for item in default)
    return str(default)


def pack(specs: Sequence[ParamSpec], values: Mapping[str, Any], target: Any) -> Any:
    """A dataclass instance (target is the class) or an argparse.Namespace (target is a parser or Namespace)."""
    names = [s.name for s in specs if s.name in values]
    data = {n: values[n] for n in names}
    if isinstance(target, type) and dataclasses.is_dataclass(target):
        return target(**data)
    if isinstance(target, argparse.ArgumentParser) or target is argparse.Namespace:
        return argparse.Namespace(**data)
    raise TypeError(f"cannot pack values into {target!r}")
