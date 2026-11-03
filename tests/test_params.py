"""P3.1/P3.2/C2-1/C2-2 (pure side): param schema, derivation, conversion, and settings-model introspection."""
# ruff: noqa: UP037, UP045
from __future__ import annotations

import argparse
import dataclasses
import enum
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Optional

import pytest

from cli_interface import params, settings
from cli_interface.context import Context
from cli_interface.params import (
    MISSING,
    FormContext,
    Param,
    ParamError,
    ParamSpec,
    Secret,
    call_with_ctx,
    convert,
    initial_text,
    pack,
    resolve_choices,
    specs_from_argparse,
    specs_from_dataclass,
    specs_from_signature,
    validate_all,
)


class Color(enum.Enum):
    RED = 1
    GREEN = 2


def validator(v):
    pass


def by_name(specs: list[ParamSpec]) -> dict[str, ParamSpec]:
    return {s.name: s for s in specs}


def spec(kind: str = "text", **kw: Any) -> ParamSpec:
    kw.setdefault("name", "x")
    kw.setdefault("label", "X")
    return ParamSpec(kind=kind, **kw)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- imports stay pure

def test_modules_import_with_pydantic_and_textual_blocked():
    code = textwrap.dedent(
        """
        import sys, types
        class Block:
            def find_spec(self, name, path=None, target=None):
                if name.split(".")[0] in ("pydantic", "textual"):
                    raise ImportError("blocked " + name)
        sys.meta_path.insert(0, Block())
        pkg = types.ModuleType("cli_interface")
        pkg.__path__ = [sys.argv[1]]
        sys.modules["cli_interface"] = pkg
        import cli_interface.params, cli_interface.settings
        assert "pydantic" not in sys.modules and "textual" not in sys.modules
        print("ok")
        """
    )
    src = str(Path(params.__file__).parent)
    result = subprocess.run([sys.executable, "-I", "-c", code, src], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


def test_package_imports_without_pydantic():
    code = "import sys; sys.modules['pydantic'] = None; import cli_interface; import cli_interface.settings, cli_interface.params"
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=Path(params.__file__).parent.parent)
    assert result.returncode == 0, result.stderr


# --------------------------------------------------------------------------- the schema

def test_missing_is_falsy_singleton_and_survives_copy():
    import copy
    import pickle

    assert not MISSING
    assert copy.deepcopy(MISSING) is MISSING
    assert copy.copy(MISSING) is MISSING
    assert pickle.loads(pickle.dumps(MISSING)) is MISSING
    assert repr(MISSING) == "MISSING"


def test_required_means_no_default_and_not_optional():
    assert spec().required
    assert not spec(default="a").required
    assert not spec(optional=True).required
    assert not spec(default=None).required


def test_secret_is_a_param_with_secret_set():
    assert isinstance(Secret(), Param) and Secret().secret and not Param().secret


def test_param_and_spec_are_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        Param().label = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec().label = "x"  # type: ignore[misc]


def test_form_context_state_is_per_instance_namespace():
    a, b = FormContext(), FormContext()
    a.state.x = 1
    assert not hasattr(b.state, "x")


# --------------------------------------------------------------------------- signature derivation

def test_signature_type_matrix():
    def fn(
        s: str,
        i: int,
        f: float,
        b: bool,
        p: Path,
        c: Color,
        lit: Literal["a", "b"],
        opt: int | None,
        old_opt: Optional[str],
        tags: list[str],
        picks: list[Literal["x", "y"]],
        nums: list[int],
    ):
        pass

    specs = by_name(specs_from_signature(fn, strict=False))
    assert {k: v.kind for k, v in specs.items()} == {
        "s": "text", "i": "int", "f": "float", "b": "bool", "p": "path", "c": "choice", "lit": "choice",
        "opt": "int", "old_opt": "text", "tags": "list", "picks": "multi", "nums": "list",
    }
    assert specs["opt"].optional and specs["old_opt"].optional and not specs["s"].optional
    assert all(s.required for k, s in specs.items() if k not in ("opt", "old_opt"))
    assert specs["tags"].item_kind == "text" and specs["nums"].item_kind == "int"
    assert specs["c"].enum_type is Color
    assert specs["c"].choices == [(Color.RED, "RED"), (Color.GREEN, "GREEN")]
    assert specs["lit"].choices == [("a", "a"), ("b", "b")]
    assert specs["picks"].choices == [("x", "x"), ("y", "y")]


def test_literal_int_values_keep_their_type():
    def fn(level: Literal[1, 2, 3] = 2):
        pass

    (s,) = specs_from_signature(fn, strict=True)
    assert s.kind == "choice" and s.default == 2
    assert convert(s, 3) == 3 and type(convert(s, 3)) is int
    with pytest.raises(ParamError, match="Choose one of: 1, 2, 3"):
        convert(s, 4)


def test_labels_defaults_and_optional_bool():
    def fn(max_retries: int = 3, flag: bool | None = None, name: str = "x"):
        pass

    specs = by_name(specs_from_signature(fn, strict=False))
    assert specs["max_retries"].label == "Max retries" and specs["max_retries"].default == 3
    assert specs["flag"].kind == "choice" and specs["flag"].optional
    assert [label for _, label in specs["flag"].choices] == ["Yes", "No"]
    assert [v for v, _ in specs["flag"].choices] == [True, False]
    assert specs["name"].default == "x" and not specs["name"].required


def test_annotated_param_and_secret_supply_metadata():
    def fn(
        a: Annotated[int, Param(label="Count", help="how many", min=1, max=9, validate=validator)] = 1,
        pw: Annotated[str, Secret()] = "",
        maybe: Annotated[str, Secret()] | None = None,
        which: Annotated[str, Param(choices=["u", "v"])] = "u",
        many: Annotated[list[str], Param(choices=[("a", "Alpha"), ("b", "Beta")])] = (),  # type: ignore[assignment]
    ):
        pass

    specs = by_name(specs_from_signature(fn, strict=True))
    assert (specs["a"].label, specs["a"].help, specs["a"].min, specs["a"].max, specs["a"].validate) == (
        "Count", "how many", 1, 9, validator,
    )
    assert specs["pw"].secret and specs["pw"].kind == "text"
    assert specs["maybe"].secret and specs["maybe"].optional
    assert specs["which"].kind == "choice" and specs["which"].choices == ["u", "v"]
    assert specs["many"].kind == "multi"
    assert resolve_choices(specs["many"], FormContext()) == [("a", "Alpha"), ("b", "Beta")]


def test_default_inference_without_annotations():
    def fn(a=3, b=1.5, c=True, d="s", e=None, f=Path("."), g=Color.GREEN, h=Literal):  # noqa: B006
        pass

    specs = by_name(specs_from_signature(fn, strict=False))
    assert specs["a"].kind == "int" and specs["b"].kind == "float" and specs["c"].kind == "bool"
    assert specs["d"].kind == "text" and specs["f"].kind == "path"
    assert specs["e"].kind == "text" and specs["e"].optional
    assert specs["g"].kind == "choice" and specs["g"].enum_type is Color
    assert "h" not in specs  # unsupported default type is skipped when lenient


def test_unannotated_without_default_is_text():
    def fn(name):
        pass

    (s,) = specs_from_signature(fn, strict=True)
    assert s.kind == "text" and s.required


def test_context_and_var_parameters_are_skipped():
    def fn(ctx, n: int = 1, *args, **kwargs):
        pass

    def fn2(n: int, c: Context):
        pass

    def fn3(*, context, n: int = 2):
        pass

    assert [s.name for s in specs_from_signature(fn, strict=True)] == ["n"]
    assert [s.name for s in specs_from_signature(fn2, strict=True)] == ["n"]
    assert [s.name for s in specs_from_signature(fn3, strict=True)] == ["n"]


def test_string_annotations_resolve():
    def fn(n: "int" = 1, mode: "Literal['a', 'b']" = "a", c: "Context | None" = None):
        pass

    specs = by_name(specs_from_signature(fn, strict=True))
    assert list(specs) == ["n", "mode"] and specs["mode"].kind == "choice"


def test_unresolvable_context_annotation_does_not_hide_other_parameters():
    def fn(ctx: "ui.Context", n: "int" = 1):  # noqa: F821
        pass

    assert [s.name for s in specs_from_signature(fn, strict=True)] == ["n"]


def test_unsupported_with_default_is_skipped_only_when_not_strict():
    def fn(n: int = 1, blob: dict = None, other: set[str] = frozenset()):  # type: ignore[assignment]
        pass

    assert [s.name for s in specs_from_signature(fn, strict=False)] == ["n"]
    with pytest.raises(ValueError, match="blob"):
        specs_from_signature(fn, strict=True)


def test_unsupported_without_default_raises_naming_function_and_parameter():
    def run_report(data: dict):
        pass

    with pytest.raises(ValueError) as exc:
        specs_from_signature(run_report, strict=False)
    assert "run_report" in str(exc.value) and "data" in str(exc.value)


@pytest.mark.parametrize("annotation", [int | str, list[list[int]], list[bool], list[int | None], tuple[int, ...]])
def test_unsupported_annotations(annotation):
    def fn(x):
        pass

    fn.__annotations__ = {"x": annotation}
    with pytest.raises(ValueError):
        specs_from_signature(fn, strict=False)


def test_positional_only():
    def needs(a, /, b: int = 1):
        pass

    def has_default(a: int = 1, /, b: int = 2):
        pass

    with pytest.raises(ValueError, match="positional-only"):
        specs_from_signature(needs, strict=False)
    assert [s.name for s in specs_from_signature(has_default, strict=False)] == ["b"]


def test_methods_and_callable_objects():
    class Job:
        def go(self, n: int = 1):
            pass

        def __call__(self, m: float = 2.0):
            pass

    assert [s.name for s in specs_from_signature(Job().go, strict=True)] == ["n"]
    assert [s.name for s in specs_from_signature(Job(), strict=True)] == ["m"]


# --------------------------------------------------------------------------- dataclass derivation

def test_dataclass_fields_defaults_factories_and_metadata():
    @dataclass
    class Opts:
        name: str
        count: int = 3
        tags: list[str] = field(default_factory=lambda: ["a"])
        mode: Literal["x", "y"] = "x"
        token: Annotated[str, Secret()] = ""
        ratio: float = field(default=0.5, metadata={"param": Param(label="Ratio", min=0, max=1)})
        internal: int = field(default=0, init=False)

    specs = by_name(specs_from_dataclass(Opts))
    assert "internal" not in specs
    assert specs["name"].required
    assert specs["count"].default == 3
    assert specs["tags"].kind == "list" and specs["tags"].default == ["a"]
    assert specs["mode"].kind == "choice"
    assert specs["token"].secret
    assert (specs["ratio"].label, specs["ratio"].min, specs["ratio"].max) == ("Ratio", 0, 1)


def test_dataclass_nested_field_raises():
    @dataclass
    class Inner:
        a: int = 1

    @dataclass
    class Outer:
        inner: Inner = field(default_factory=Inner)

    with pytest.raises(ValueError, match="inner"):
        specs_from_dataclass(Outer)


def test_dataclass_unsupported_field_raises_even_with_default():
    @dataclass
    class Bad:
        extra: dict = field(default_factory=dict)

    with pytest.raises(ValueError, match="extra"):
        specs_from_dataclass(Bad)


def test_specs_from_dataclass_rejects_non_dataclasses():
    with pytest.raises(TypeError):
        specs_from_dataclass(int)


def test_pack_builds_dataclass_instance():
    @dataclass
    class Opts:
        n: int = 1
        s: str = ""

    specs = specs_from_dataclass(Opts)
    values, errors = validate_all(specs, {"n": "5", "s": "hi"})
    assert errors == {}
    assert pack(specs, values, Opts) == Opts(n=5, s="hi")


# --------------------------------------------------------------------------- argparse derivation

def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="t")
    p.add_argument("target", help="what")
    p.add_argument("--count", type=int, default=2, help="default %(default)s")
    p.add_argument("--ratio", type=float)
    p.add_argument("--out", type=Path)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--quiet", action="store_false")
    p.add_argument("--mode", choices=["fast", "slow"], default="fast")
    p.add_argument("--names", nargs="+")
    p.add_argument("--opt-names", nargs="*")
    p.add_argument("--picks", nargs="+", choices=["a", "b"])
    p.add_argument("--hex", type=lambda s: int(s, 16), required=True)
    return p


def test_argparse_actions_map_to_specs():
    specs = by_name(specs_from_argparse(make_parser()))
    assert "help" not in specs
    assert specs["target"].kind == "text" and specs["target"].required and specs["target"].help == "what"
    assert specs["count"].kind == "int" and specs["count"].default == 2 and specs["count"].help == "default 2"
    assert specs["ratio"].kind == "float" and specs["ratio"].optional and specs["ratio"].default is None
    assert specs["out"].kind == "path"
    assert specs["verbose"].kind == "bool" and specs["verbose"].default is False
    assert specs["quiet"].kind == "bool" and specs["quiet"].default is True
    assert specs["mode"].kind == "choice" and specs["mode"].default == "fast"
    assert specs["names"].kind == "list" and specs["names"].item_kind == "text"
    assert specs["opt_names"].kind == "list" and specs["opt_names"].default == []
    assert specs["picks"].kind == "multi"
    assert specs["hex"].kind == "text" and specs["hex"].convert_fn is not None and specs["hex"].required
    assert specs["hex"].label == "Hex"


def test_argparse_custom_type_is_applied_by_convert():
    s = by_name(specs_from_argparse(make_parser()))["hex"]
    assert convert(s, "ff") == 255
    with pytest.raises(ParamError):
        convert(s, "zz")


def test_argparse_list_item_types():
    p = argparse.ArgumentParser()
    p.add_argument("nums", nargs="+", type=int)
    (s,) = specs_from_argparse(p)
    assert s.kind == "list" and s.item_kind == "int" and s.required
    assert convert(s, "1, 2,3") == [1, 2, 3]


def test_argparse_meta_supplies_secret_label_help():
    p = argparse.ArgumentParser()
    p.add_argument("--password", required=True)
    (s,) = specs_from_argparse(p, {"password": Secret(label="Pass", help="shh")})
    assert s.secret and s.label == "Pass" and s.help == "shh"


def test_argparse_namespace_pack():
    p = make_parser()
    specs = specs_from_argparse(p)
    values, errors = validate_all(specs, {"target": "t", "hex": "10", "mode": "slow", "verbose": True})
    assert errors == {}
    ns = pack(specs, values, p)
    assert isinstance(ns, argparse.Namespace)
    assert (ns.target, ns.hex, ns.mode, ns.verbose, ns.count, ns.ratio) == ("t", 16, "slow", True, 2, None)


@pytest.mark.parametrize(
    "build",
    [
        lambda p: p.add_subparsers(),
        lambda p: p.add_argument("-v", action="count"),
        lambda p: p.add_argument("--x", action="append"),
        lambda p: p.add_argument("--c", action="store_const", const=1),
        lambda p: p.add_argument("--b", action=argparse.BooleanOptionalAction),
        lambda p: p.add_argument("--pair", nargs=2),
        lambda p: p.add_argument("--custom", action=type("Mine", (argparse.Action,), {"__call__": lambda *a: None})),
    ],
)
def test_argparse_unsupported_actions_raise(build):
    p = argparse.ArgumentParser()
    build(p)
    with pytest.raises(ValueError):
        specs_from_argparse(p)


# --------------------------------------------------------------------------- convert: empty input

@pytest.mark.parametrize("kind", ["int", "float", "path", "list"])
def test_empty_without_default_is_required(kind):
    for raw in ("", "   ", None):
        with pytest.raises(ParamError, match="^Required$"):
            convert(spec(kind, item_kind="int" if kind == "list" else None), raw)


def test_empty_text_rules():
    assert convert(spec("text", default="d"), "") == ""
    assert convert(spec("text", default=""), "") == ""
    with pytest.raises(ParamError, match="^Required$"):
        convert(spec("text"), "")
    assert convert(spec("text", default="d"), None) == "d"
    assert convert(spec("text", default="d"), "  ") == "  "


@pytest.mark.parametrize("kind", ["text", "int", "float", "path", "list", "choice", "multi"])
def test_empty_optional_is_none_even_with_default(kind):
    s = spec(kind, optional=True, default=None, choices=[("a", "a")])
    assert convert(s, "" if kind not in ("choice", "multi") else None) is None
    s2 = spec(kind, optional=True, default="zz", choices=[("a", "a")])
    assert convert(s2, "" if kind not in ("choice", "multi") else None) is None


def test_empty_non_text_falls_back_to_default():
    assert convert(spec("int", default=7), "") == 7
    assert convert(spec("float", default=1.5), " ") == 1.5
    assert convert(spec("path", default=Path("p")), "") == Path("p")
    assert convert(spec("list", item_kind="text", default=["a"]), "") == ["a"]
    assert convert(spec("list", item_kind="text", default=[]), " , ,") == []
    assert convert(spec("choice", default="a", choices=[("a", "a")]), None) == "a"
    assert convert(spec("multi", default=[], choices=[("a", "a")]), []) == []


def test_bool_conversion():
    assert convert(spec("bool"), True) is True
    assert convert(spec("bool"), False) is False
    assert convert(spec("bool", default=True), None) is True
    with pytest.raises(ParamError, match="Required"):
        convert(spec("bool"), None)


def test_int_none_optional_empty_unsets_even_when_default_is_set():
    def fn(limit: int | None = 5):
        pass

    (s,) = specs_from_signature(fn, strict=True)
    assert convert(s, "") is None
    assert convert(s, "9") == 9


# --------------------------------------------------------------------------- convert: numbers, paths, lists

def test_int_rules():
    s = spec("int")
    assert convert(s, " 42 ") == 42 and convert(s, "-3") == -3
    for bad in ("4.5", "abc", "1e3", "0x10"):
        with pytest.raises(ParamError, match="^Enter a whole number$"):
            convert(s, bad)


def test_float_rules_reject_nan_and_inf():
    s = spec("float")
    assert convert(s, "1.5") == 1.5 and convert(s, "3") == 3.0 and convert(s, "1e3") == 1000.0
    for bad in ("nan", "NaN", "inf", "-inf", "Infinity", "abc"):
        with pytest.raises(ParamError, match="^Enter a number$"):
            convert(s, bad)


def test_min_max():
    s = spec("int", min=1, max=10)
    assert convert(s, "1") == 1 and convert(s, "10") == 10
    with pytest.raises(ParamError, match="^Must be at least 1$"):
        convert(s, "0")
    with pytest.raises(ParamError, match="^Must be at most 10$"):
        convert(s, "11")
    f = spec("float", min=0.5)
    with pytest.raises(ParamError, match="Must be at least 0.5"):
        convert(f, "0.1")
    items = spec("list", item_kind="int", min=0)
    with pytest.raises(ParamError, match="at least 0"):
        convert(items, "1,-2")


def test_path_has_no_tilde_expansion():
    assert convert(spec("path"), "~/x") == Path("~/x")
    assert convert(spec("path"), "a/b") == Path("a/b")


def test_list_splits_strips_and_converts_items():
    assert convert(spec("list", item_kind="text"), " a, b ,,c ") == ["a", "b", "c"]
    assert convert(spec("list", item_kind="int"), "1,2") == [1, 2]
    assert convert(spec("list", item_kind="float"), "1,2.5") == [1.0, 2.5]
    assert convert(spec("list", item_kind="path"), "a,b") == [Path("a"), Path("b")]
    with pytest.raises(ParamError, match="whole number"):
        convert(spec("list", item_kind="int"), "1,x")


# --------------------------------------------------------------------------- convert: choices

def test_choice_membership_and_error_text():
    s = spec("choice", choices=[("a", "Alpha"), ("b", "Beta")])
    assert convert(s, "a") == "a"
    with pytest.raises(ParamError, match="^Choose one of: Alpha, Beta$"):
        convert(s, "c")


def test_choice_enum_returns_member():
    def fn(c: Color):
        pass

    (s,) = specs_from_signature(fn, strict=True)
    assert convert(s, Color.GREEN) is Color.GREEN
    assert convert(s, "RED") is Color.RED


def test_choice_with_explicit_choices_argument():
    s = spec("choice")
    assert convert(s, 2, [(1, "one"), (2, "two")]) == 2
    with pytest.raises(ParamError, match="No choices available"):
        convert(s, 2, [])


def test_empty_choices_on_required_field():
    s = spec("choice", choices=[])
    with pytest.raises(ParamError, match="^No choices available$"):
        convert(s, None)
    with pytest.raises(ParamError, match="^No choices available$"):
        convert(spec("multi"), [])
    assert convert(spec("choice", optional=True, choices=[]), None) is None
    assert convert(spec("choice", default="d", choices=[]), None) == "d"


def test_choice_blank_vs_literal_empty_string():
    s = spec("choice", choices=[("", "(none)"), ("a", "a")])
    assert convert(s, "") == ""
    with pytest.raises(ParamError, match="Required"):
        convert(s, None)


def test_multi_selection():
    s = spec("multi", choices=[("a", "A"), ("b", "B"), ("c", "C")])
    assert convert(s, ["c", "a"]) == ["c", "a"]
    with pytest.raises(ParamError, match="Choose one of: A, B, C"):
        convert(s, ["a", "z"])
    with pytest.raises(ParamError, match="Required"):
        convert(s, [])


def test_choice_callable_with_zero_and_one_argument():
    seen = []

    def zero():
        seen.append("zero")
        return ["a", "b"]

    def one(c):
        seen.append(c)
        return [("x", "Ex")]

    fctx = FormContext()
    fctx.state.names = ["q"]
    assert resolve_choices(spec("choice", choices=zero), fctx) == [("a", "a"), ("b", "b")]
    assert resolve_choices(spec("choice", choices=one), fctx) == [("x", "Ex")]
    assert seen == ["zero", fctx]
    assert resolve_choices(spec("choice", choices=lambda c: c.state.names), fctx) == [("q", "q")]
    assert resolve_choices(spec("choice", choices=lambda c=None: [1]), fctx) == [(1, "1")]


def test_call_with_ctx_by_arity():
    assert call_with_ctx(lambda: "none", 5) == "none"
    assert call_with_ctx(lambda c: c, 5) == 5
    assert call_with_ctx(lambda *a: a, 5) == (5,)
    assert call_with_ctx(lambda *, kw=1: kw, 5) == 1


def test_resolve_choices_static_forms_and_exceptions():
    fctx = FormContext()
    assert resolve_choices(spec("choice", choices=None), fctx) == []
    assert resolve_choices(spec("choice", choices=iter(["a"])), fctx) == [("a", "a")]
    assert resolve_choices(spec("choice", choices=[Color.RED]), fctx) == [(Color.RED, "RED")]

    def boom():
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError, match="db down"):
        resolve_choices(spec("choice", choices=boom), fctx)


# --------------------------------------------------------------------------- convert: validate hook

def test_validate_raising_value_error_becomes_field_error():
    def positive(v):
        if v <= 0:
            raise ValueError("must be positive")

    s = spec("int", validate=positive)
    assert convert(s, "3") == 3
    with pytest.raises(ParamError, match="^must be positive$"):
        convert(s, "-1")


def test_validate_return_value_is_ignored():
    s = spec("int", validate=lambda v: False)
    assert convert(s, "3") == 3


def test_validate_raising_any_other_exception_becomes_a_generic_field_error():
    def boom(v):
        raise KeyError("x")

    with pytest.raises(ParamError, match="^Invalid value$"):
        convert(spec("text", default="", validate=boom), "a")


@pytest.mark.parametrize("exc", [ValueError, KeyError])
def test_validate_errors_on_secret_fields_never_echo_the_value(exc):
    def reject(v):
        raise exc(f"bad {v}")

    with pytest.raises(ParamError) as info:
        convert(spec("text", default="", secret=True, validate=reject), "hunter2")
    assert str(info.value) == "Invalid value"


def test_validate_skipped_for_blank_and_defaults():
    calls = []
    s = spec("int", default=5, validate=calls.append)
    assert convert(s, "") == 5
    assert calls == []


def test_secret_never_echoed_in_conversion_errors():
    s = spec("int", secret=True)
    with pytest.raises(ParamError) as exc:
        convert(s, "hunter2")
    assert "hunter2" not in str(exc.value)
    fn = spec("text", secret=True, convert_fn=lambda v: (_ for _ in ()).throw(ValueError(f"bad {v}")))
    with pytest.raises(ParamError) as exc:
        convert(fn, "hunter2")
    assert "hunter2" not in str(exc.value)


# --------------------------------------------------------------------------- validate_all, initial_text

def test_validate_all_collects_every_error_and_valid_values():
    specs = [
        spec("int", name="a"),
        spec("int", name="b", min=5),
        spec("text", name="c", default=""),
        spec("choice", name="d", choices=[("x", "x")]),
        spec("float", name="e", default=1.0),
    ]
    values, errors = validate_all(specs, {"a": "x", "b": "1", "c": "hi", "d": "y"})
    assert errors == {"a": "Enter a whole number", "b": "Must be at least 5", "d": "Choose one of: x"}
    assert values == {"c": "hi", "e": 1.0}


def test_validate_all_uses_per_field_choices_and_missing_keys():
    specs = [spec("choice", name="d"), spec("text", name="t", default="dflt")]
    values, errors = validate_all(specs, {"d": 2}, {"d": [(1, "one"), (2, "two")]})
    assert errors == {} and values == {"d": 2, "t": "dflt"}
    _, errors = validate_all(specs, {}, {"d": []})
    assert errors == {"d": "No choices available"}


def test_initial_text():
    assert initial_text(spec("text")) == ""
    assert initial_text(spec("text", default=None)) == ""
    assert initial_text(spec("text", default="hi")) == "hi"
    assert initial_text(spec("text", default="hunter2", secret=True)) == ""
    assert initial_text(spec("int", default=4)) == "4"
    assert initial_text(spec("float", default=1.5)) == "1.5"
    assert initial_text(spec("path", default=Path("a/b"))) == "a/b"
    assert initial_text(spec("list", default=["a", "b"])) == "a, b"
    assert initial_text(spec("choice", default=Color.RED)) == "RED"


def test_pack_rejects_unknown_targets():
    with pytest.raises(TypeError):
        pack([], {}, dict)


# --------------------------------------------------------------------------- settings: dataclasses

class Level(enum.Enum):
    LOW = "low"
    HIGH = "high"


@dataclass
class _Db:
    host: str = "localhost"
    port: int = 5432
    password: str = ""


@dataclass
class _Plain:
    name: str = "app"
    debug: bool = False
    level: Level = Level.LOW
    tags: list[str] = field(default_factory=lambda: ["a"])
    token: Annotated[str, Secret()] = ""
    db: _Db = field(default_factory=_Db)
    required_one: int = field(default=0)


def names(items) -> list[str]:
    return [i.name for i in items]


def test_describe_dataclass_flat_depth_first_with_groups_first():
    items = settings.describe(_Plain())
    assert names(items) == [
        "name", "debug", "level", "tags", "token", "db", "db.host", "db.port", "db.password", "required_one",
    ]
    group = items[5]
    assert isinstance(group, settings.Group) and group.label == "Db"
    leaf = items[6]
    assert isinstance(leaf, settings.Field) and leaf.spec.name == "host" and leaf.default == "localhost"
    assert [i.spec.kind for i in items if isinstance(i, settings.Field)][:4] == ["text", "bool", "choice", "list"]


def test_describe_secret_by_bare_dotted_and_param():
    by = {i.name: i for i in settings.describe(_Plain(), secret=["password"]) if isinstance(i, settings.Field)}
    assert by["db.password"].secret and by["db.password"].spec.secret
    assert by["token"].secret  # via Secret() annotation
    assert not by["name"].secret and not by["db.host"].secret

    by = {i.name: i for i in settings.describe(_Plain(), secret=["db.host", "name"]) if isinstance(i, settings.Field)}
    assert by["db.host"].secret and by["name"].secret and not by["db.port"].secret

    by = {i.name: i for i in settings.describe(_Plain(), secret=["host"]) if isinstance(i, settings.Field)}
    assert by["db.host"].secret  # a bare name matches at any depth
    by = {i.name: i for i in settings.describe(_Plain(), secret=["other.password"]) if isinstance(i, settings.Field)}
    assert not by["db.password"].secret


def test_fields_without_default_have_missing_default():
    @dataclass
    class M:
        a: int
        b: int = 2

    d = {i.name: i for i in settings.describe(M(a=1))}
    assert d["a"].default is MISSING and d["b"].default == 2


def test_get_and_set_value_with_dotted_paths():
    s = _Plain()
    assert settings.get_value(s, "db.port") == 5432
    settings.set_value(s, "db.port", 1)
    settings.set_value(s, "name", "z")
    assert (s.db.port, s.name) == (1, "z")
    with pytest.raises(AttributeError):
        settings.get_value(s, "db.nope")


def test_reset_defaults_recurses_in_place_and_reports_changes():
    s = _Plain(name="x", db=_Db(host="h", port=5432))
    inner = s.db
    s.tags.append("b")
    s.token = "tok"
    changed = settings.reset_defaults(s)
    assert changed == ["name", "tags", "token", "db.host"]
    assert s.db is inner and inner.host == "localhost"
    assert s.tags == ["a"] and s.name == "app" and s.token == ""
    assert settings.reset_defaults(s) == []


def test_reset_skips_fields_without_defaults():
    @dataclass
    class M:
        a: int
        b: int = 2

    m = M(a=9, b=5)
    assert settings.reset_defaults(m) == ["b"]
    assert m.a == 9 and m.b == 2


def test_reset_resets_nested_without_replacing_objects():
    @dataclass
    class C:
        v: int = 1

    @dataclass
    class B:
        c: C = field(default_factory=C)
        w: int = 1

    @dataclass
    class A:
        b: B = field(default_factory=B)

    a = A(B(C(5), 6))
    b, c = a.b, a.b.c
    assert settings.reset_defaults(a) == ["b.c.v", "b.w"]
    assert a.b is b and b.c is c and (c.v, b.w) == (1, 1)


def test_frozen_dataclass_and_class_raise_type_error():
    @dataclass(frozen=True)
    class F:
        a: int = 1

    @dataclass
    class HasFrozen:
        inner: F = field(default_factory=F)

    for bad in (F(), HasFrozen()):
        with pytest.raises(TypeError, match="frozen"):
            settings.describe(bad)
    with pytest.raises(TypeError, match="instance"):
        settings.describe(_Plain)
    with pytest.raises(TypeError):
        settings.describe(object())
    with pytest.raises(TypeError):
        settings.describe({"a": 1})


def test_unsupported_and_private_fields_are_omitted():
    @dataclass
    class M:
        ok: int = 1
        extra: dict = field(default_factory=dict)
        _hidden: int = 3

    assert names(settings.describe(M())) == ["ok"]


def test_self_referencing_models_do_not_loop():
    @dataclass
    class Node:
        v: int = 1
        child: Any = None

    n = Node()
    n.child = n
    assert settings.describe(n)  # terminates


def test_describe_uses_param_label_help_and_title_metadata():
    @dataclass
    class M:
        a: Annotated[int, Param(label="Alpha", help="the a", min=1)] = 2
        sub: _Db = field(default_factory=_Db, metadata={"param": Param(label="Database")})

    items = settings.describe(M())
    assert (items[0].spec.label, items[0].spec.help, items[0].spec.min) == ("Alpha", "the a", 1)
    assert items[1].label == "Database"


def test_secret_values_recursive_and_non_empty_only():
    s = _Plain(token="t0k", db=_Db(password="pw"))
    assert settings.secret_values(s, ["password"]) == ["t0k", "pw"]
    assert settings.secret_values(_Plain(), ["password"]) == []
    s.db.host = "secret-host"
    assert settings.secret_values(s, ["db.host"]) == ["t0k", "secret-host"]
    assert settings.secret_values(s, ["host"]) == ["t0k", "secret-host"]


def test_secret_values_include_secret_list_items_and_skip_non_strings():
    @dataclass
    class M:
        keys: Annotated[list[str], Secret()] = field(default_factory=lambda: ["k1", "", "k2"])
        n: Annotated[int, Secret()] = 5

    assert settings.secret_values(M()) == ["k1", "k2"]


# --------------------------------------------------------------------------- format_value

def test_format_value():
    f = settings.format_value
    assert f(None) == "-"
    assert f(Level.HIGH) == "HIGH"
    assert f(["a", "b"]) == "a, b"
    assert f(("a", 2)) == "a, 2"
    assert f([]) == ""
    assert f(5) == "5" and f(True) == "True" and f("hi") == "hi" and f(Path("a/b")) == "a/b"
    assert f([None, Level.LOW]) == "-, LOW"
    assert f("x" * 40) == "x" * 40
    long = f("x" * 100)
    assert len(long) == 40 and long.endswith("…")
    assert len(f(["abcdefgh"] * 10)) == 40
    assert "\n" not in f("a\nb\r\nc")


def test_format_value_keeps_markup_text_literal():
    assert settings.format_value("[/x] matrix[i][j]") == "[/x] matrix[i][j]"


# --------------------------------------------------------------------------- settings: pydantic v2

def test_pydantic_models_describe_nest_reset_and_secret():
    pydantic = pytest.importorskip("pydantic")
    if int(pydantic.VERSION.split(".")[0]) < 2:
        pytest.skip("pydantic v2 required")
    from pydantic import BaseModel, Field as PField, SecretStr

    class Db(BaseModel):
        host: str = "localhost"
        port: int = 5432

    class Cfg(BaseModel):
        name: str = PField("app", description="The app name")
        level: Level = Level.LOW
        retries: int | None = None
        api_key: SecretStr = SecretStr("k-1")
        tags: list[str] = PField(default_factory=lambda: ["a"])
        db: Db = PField(default_factory=Db)
        needed: int
        flagged: Annotated[str, Secret()] = "f"
        pw: str = PField("x", json_schema_extra={"param": Param(label="Password", secret=True)})

    cfg = Cfg(needed=1)
    items = {i.name: i for i in settings.describe(cfg)}
    assert names(settings.describe(cfg)) == [
        "name", "level", "retries", "api_key", "tags", "db", "db.host", "db.port", "needed", "flagged", "pw",
    ]
    assert items["name"].spec.help == "The app name" and items["name"].default == "app"
    assert items["needed"].default is MISSING
    assert items["retries"].spec.kind == "int" and items["retries"].spec.optional
    assert items["level"].spec.kind == "choice"
    assert items["api_key"].secret and items["api_key"].spec.kind == "text" and items["api_key"].default == "k-1"
    assert items["flagged"].secret and items["pw"].secret and items["pw"].spec.label == "Password"
    assert isinstance(items["db"], settings.Group)

    assert settings.get_value(cfg, "api_key") == "k-1"
    settings.set_value(cfg, "api_key", "k-2")
    assert isinstance(cfg.api_key, SecretStr) and cfg.api_key.get_secret_value() == "k-2"
    assert settings.secret_values(cfg) == ["k-2", "f", "x"]

    db = cfg.db
    cfg.name = "other"
    cfg.db.port = 1
    cfg.tags.append("b")
    changed = settings.reset_defaults(cfg)
    assert changed == ["name", "api_key", "tags", "db.port"]
    assert cfg.db is db and db.port == 5432 and cfg.api_key.get_secret_value() == "k-1"
    assert cfg.needed == 1


def test_pydantic_optional_secret_and_frozen():
    pytest.importorskip("pydantic")
    from pydantic import BaseModel, ConfigDict, SecretStr

    class Cfg(BaseModel):
        token: SecretStr | None = None

    cfg = Cfg()
    (item,) = settings.describe(cfg)
    assert item.secret and item.spec.optional
    settings.set_value(cfg, "token", "abc")
    assert isinstance(cfg.token, SecretStr) and settings.secret_values(cfg) == ["abc"]
    settings.set_value(cfg, "token", None)
    assert cfg.token is None

    class Frozen(BaseModel):
        model_config = ConfigDict(frozen=True)
        a: int = 1

    with pytest.raises(TypeError, match="frozen"):
        settings.describe(Frozen())
    with pytest.raises(TypeError, match="instance"):
        settings.describe(Cfg)


def test_pydantic_assignment_validation_error_propagates():
    pytest.importorskip("pydantic")
    from pydantic import BaseModel, ConfigDict, ValidationError

    class Cfg(BaseModel):
        model_config = ConfigDict(validate_assignment=True)
        n: int = 1

    cfg = Cfg()
    with pytest.raises(ValidationError):
        settings.set_value(cfg, "n", "not a number")
    assert cfg.n == 1
