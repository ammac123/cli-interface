"""P2.2: which callables ask for a Context (wants_context), which lane they run on, and how a call is bound."""
from __future__ import annotations

import functools
import textwrap
from typing import Any

import pytest

from cli_interface import Context
from cli_interface.jobs import JobSpec, bind_call, choose_lane, wants_context
from cli_interface.menu import make_command_item

CTX = object()


def build(source: str, *, future: bool = False) -> dict[str, Any]:
    """Execute ``source`` as a module body, with or without ``from __future__ import annotations``."""
    header = "from __future__ import annotations\n" if future else ""
    namespace: dict[str, Any] = {
        "__name__": "shapes_under_test", "Context": Context,
    }
    code = header + "import typing\nfrom typing import Any, Optional, Union, Literal, Annotated\nimport cli_interface\n"
    exec(compile(code + textwrap.dedent(source), "<shapes>", "exec", dont_inherit=True), namespace)  # noqa: S102
    return namespace


# --------------------------------------------------------------------------- the 29 annotation shapes of the review

ASKING = [
    "def f(ctx: Context | None = None): ...",
    "def f(ctx: Optional[Context] = None): ...",
    "def f(ctx: Union[Context, int]): ...",
    "def f(ctx: 'Optional[Context]'): ...",
    "def f(ctx: Optional['Context']): ...",
    "def f(ctx: cli_interface.Context | None = None): ...",
    "def f(ctx: 'typing.Optional[cli_interface.context.Context]'): ...",
    "def f(ctx: 'Context | None' = None): ...",
    "def f(*, ctx: Context): ...",
    "async def f(ctx: Context): ...",
    "class K:\n    def __call__(self, ctx: Context): ...\nf = K()",
    "def base(a, ctx: Context): ...\nimport functools\nf = functools.partial(base, 1)",
    "class Sub(Context): ...\ndef f(c: Sub): ...",
    "Ctx = Context\ndef f(c: Ctx): ...",
    "def f(ctx): ...",
    "def f(context): ...",
    "def f(value, ctx): ...",
    "def f(ctx: Context): ...",
    "def f(ctx: 'Context'): ...",
    "def f(c: cli_interface.Context): ...",
    "def f(x: Optional[Missing], ctx: Optional[Context]): ...",
]

NOT_ASKING = [
    "def f(v: Optional[str] = None): ...",
    "f = lambda v: None",
    "def f(ctx: Any): ...",
    "def f(ctx: int): ...",
    "class MyContext: ...\ndef f(ctx: MyContext): ...",
    "class Contexts: ...\ndef f(ctx: Contexts): ...",
    "def f(ctx: list[Context]): ...",
    "def f(ctx: dict[str, Context | None]): ...",
    "def f(ctx: Optional[int]): ...",
    "def f(ctx: Union[str, bytes]): ...",
    "def f(ctx: Literal['Context']): ...",
    "def f(c: Missing | None): ...",
    "def f(c: Missing): ...",
    "def f(): ...",
    "def f(value): ...",
    "def f(*args, **kwargs): ...",
    "def f(a, b=1): ...",
    "async def f(): ...",
]


def with_and_without_postponed_evaluation(sources: list[str]) -> list[tuple[str, bool]]:
    # an undefined name is only a legal annotation under postponed evaluation
    return [(src, future) for src in sources for future in ((True,) if "Missing" in src else (False, True))]


@pytest.mark.parametrize("source, future", with_and_without_postponed_evaluation(ASKING))
def test_shapes_that_ask_for_a_context(source, future):
    ns = build(source, future=future)
    assert wants_context(ns["f"]) is True


@pytest.mark.parametrize("source, future", with_and_without_postponed_evaluation(NOT_ASKING))
def test_shapes_that_do_not_ask_for_a_context(source, future):
    ns = build(source, future=future)
    assert wants_context(ns["f"]) is False


def test_an_unresolved_name_never_triggers_a_false_positive():
    ns = build("def f(a: Missing | None, b: Optional[Missing]): ...", future=True)
    assert wants_context(ns["f"]) is False


def test_annotated_context_is_not_detected_and_that_is_not_pinned_either_way():
    ns = build("def f(ctx: Annotated[Context, 'x']): ...")
    assert wants_context(ns["f"]) in (True, False)


def test_a_string_annotation_resolves_under_postponed_evaluation_in_this_very_module():
    def f(ctx: Context) -> None: ...

    def g(value: str) -> None: ...

    assert wants_context(f) is True and wants_context(g) is False


def test_absurdly_nested_annotations_do_not_raise():
    deep = "Optional[" * 600 + "Context" + "]" * 600
    ns = build(f"def f(ctx: '{deep}'): ...")
    assert wants_context(ns["f"]) in (True, False)


# --------------------------------------------------------------------------- the shapes in the plan

def zero(): ...


def one(value): ...


def with_ctx(ctx): ...


def ctx_first(ctx, value): ...


def ctx_last(value, ctx): ...


def kw_only(value, *, ctx): ...


def annotated(c: Context): ...


def string_annotated(c: "Context"): ...  # noqa: UP037


def varargs(*args): ...


def ctx_then_varargs(ctx, *args): ...


def optional_value(value=None): ...


class CallObj:
    def __call__(self, ctx): ...


class LegacyCallObj:
    def __call__(self, value): ...


def _base(a, ctx): ...


PARTIAL = functools.partial(_base, 1)


@pytest.mark.parametrize(
    "fn, expected",
    [
        (zero, False), (one, False), (lambda v: v, False), (lambda: None, False), (varargs, False),
        (optional_value, False), (print, False), (len, False), (LegacyCallObj(), False),
        (with_ctx, True), (ctx_first, True), (ctx_last, True), (kw_only, True), (annotated, True),
        (string_annotated, True), (ctx_then_varargs, True), (CallObj(), True), (PARTIAL, True),
    ],
)
def test_wants_context_table(fn, expected):
    assert wants_context(fn) is expected


def test_a_callable_whose_signature_cannot_be_read_is_legacy():
    class Odd:
        __signature__ = "not a signature"

        def __call__(self, ctx): ...

    assert wants_context(Odd()) is False
    assert bind_call(Odd(), CTX, "v") == (("v",), {})
    assert bind_call(Odd(), CTX, None) == ((), {})


@pytest.mark.parametrize(
    "fn, value, args, kwargs",
    [
        (zero, None, (), {}),
        (one, "v", ("v",), {}),
        (lambda v: v, "typed", ("typed",), {}),
        (with_ctx, None, (CTX,), {}),
        (ctx_first, "v", (CTX, "v"), {}),
        (ctx_last, "v", ("v", CTX), {}),
        (kw_only, "v", ("v",), {"ctx": CTX}),
        (kw_only, None, (), {"ctx": CTX}),
        (annotated, None, (CTX,), {}),
        (string_annotated, None, (CTX,), {}),
        (varargs, "v", ("v",), {}),
        (varargs, None, (), {}),
        (ctx_then_varargs, "v", (CTX, "v"), {}),
        (ctx_then_varargs, None, (CTX,), {}),
        (optional_value, None, (), {}),
        (optional_value, "v", ("v",), {}),
        (CallObj(), None, (CTX,), {}),
        (PARTIAL, None, (CTX,), {}),
        (print, "v", ("v",), {}),
    ],
)
def test_bind_call_table(fn, value, args, kwargs):
    assert bind_call(fn, CTX, value) == (args, kwargs)


def test_the_value_goes_to_the_first_slot_that_is_not_the_context_even_after_a_gap():
    def f(a, ctx, b): ...

    assert bind_call(f, CTX, "v") == (("v", CTX), {})


def test_an_empty_string_value_is_a_value_not_none():
    assert bind_call(one, CTX, "") == (("",), {})


# --------------------------------------------------------------------------- lanes

async def an_async_fn(): ...


class AsyncCallObj:
    async def __call__(self): ...


def lane(fn, **spec_kw) -> str:
    return choose_lane(JobSpec("L", fn, **spec_kw), fn)


@pytest.mark.parametrize(
    "fn, kwargs, expected",
    [
        (zero, {}, "inline"),
        (one, {}, "inline"),
        (lambda v: v, {}, "inline"),
        (varargs, {}, "inline"),
        (print, {}, "inline"),
        (with_ctx, {}, "thread"),
        (ctx_first, {}, "thread"),
        (kw_only, {}, "thread"),
        (CallObj(), {}, "thread"),
        (PARTIAL, {}, "thread"),
        (zero, {"threaded": True}, "thread"),
        (zero, {"kind": "startup"}, "thread"),
        (zero, {"kind": "shutdown"}, "thread"),
        (an_async_fn, {}, "loop"),
        (an_async_fn, {"threaded": True}, "loop"),
        (an_async_fn, {"kind": "startup"}, "loop"),
        (AsyncCallObj(), {}, "loop"),
    ],
)
def test_choose_lane_table(fn, kwargs, expected):
    assert lane(fn, **kwargs) == expected


def test_a_command_item_runs_in_a_thread_even_without_a_ctx_parameter():
    from cli_interface.jobs import spec_from_item

    item = make_command_item("Group/Name", zero, key="n", cancellable=True)
    spec = spec_from_item(item, None, ())
    assert spec.threaded and spec.cancellable and spec.path == ("Group", "Name")
    assert choose_lane(spec, spec.fn) == "thread"


def test_a_plain_menu_item_is_inline_and_not_cancellable():
    from cli_interface.jobs import spec_from_item
    from cli_interface.menu import MenuItem

    spec = spec_from_item(MenuItem("Plain", action=zero), None, ())
    assert not spec.threaded and not spec.cancellable and spec.path == ()
    assert choose_lane(spec, spec.fn) == "inline"


def test_spec_from_item_reads_a_callable_label_before_the_action_can_change_it():
    from cli_interface.jobs import spec_from_item
    from cli_interface.menu import MenuItem

    state = {"name": "before"}
    item = MenuItem(lambda: state["name"], action=zero)
    spec = spec_from_item(item, "typed", ("A", "B"))
    state["name"] = "after"
    assert spec.label == "before" and spec.value == "typed" and spec.path == ("A", "B")


def test_spec_from_item_rejects_an_item_without_an_action():
    from cli_interface.jobs import spec_from_item
    from cli_interface.menu import MenuItem

    with pytest.raises(ValueError):
        spec_from_item(MenuItem("Folder"), None, ())


def test_a_secret_item_makes_a_secret_spec_whose_repr_hides_the_value():
    from cli_interface.jobs import spec_from_item
    from cli_interface.menu import MenuItem

    spec = spec_from_item(MenuItem("Login", prompt="pw:", secret=True, action=one), "hunter2", ())
    assert spec.secret is True
    assert "hunter2" not in repr(spec) and "hunter2" not in str(spec)
    assert spec == JobSpec("Login", one, (), "hunter2", True)
    assert spec != JobSpec("Login", one, (), "other", True), "equality still compares the value"
