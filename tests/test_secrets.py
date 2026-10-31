"""F4: prompted values are never echoed; secret items are masked, redacted and kept out of repr."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Callable

import pytest
from textual.widgets import Input

from cli_interface.menu import MenuItem
from cli_interface.widgets import NavBar, PromptScreen
from helpers import SIZE, Calls, leaf, panel_lines, panel_text, read_panel, widget_text

SECRET = "hunter2"


async def type_into_prompt(pilot, text: str) -> None:
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")
    await pilot.pause()


# --------------------------------------------------------------------------- the prompt screen

async def test_prompt_input_is_masked_only_for_secret_items(make_app):
    app = make_app(
        MenuItem("Port", shortcut="p", prompt="Port:", action=lambda v: None),
        MenuItem("Token", shortcut="k", prompt="Token:", action=lambda v: None, secret=True),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is False
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("k", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is True


async def test_typed_secret_characters_are_not_visible_on_screen(make_app):
    app = make_app(MenuItem("Token", shortcut="k", prompt="Token:", action=lambda v: None, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "enter")
        await pilot.pause()
        for ch in SECRET:
            await pilot.press(ch)
        await pilot.pause()
        field_text = widget_text(app.screen.query_one("#prompt-input", Input))
        assert SECRET not in field_text and "hunter" not in field_text
        assert app.screen.query_one("#prompt-input", Input).value == SECRET


def test_prompt_screen_secret_is_keyword_only_and_defaults_to_off():
    assert PromptScreen("label", "prompt")._secret is False
    assert PromptScreen("label", "prompt", secret=True)._secret is True
    with pytest.raises(TypeError):
        PromptScreen("label", "prompt", True)  # type: ignore[misc]


# --------------------------------------------------------------------------- no echo of the typed value

async def test_plain_prompted_item_does_not_echo_the_typed_value(make_app):
    calls = Calls()
    app = make_app(MenuItem("Set Port", shortcut="p", prompt="Port:", action=calls.action("port")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "8080")
        lines = panel_lines(app)
        assert calls.log == [("port", ("8080",))]
        assert [l for l in lines if "Executed" in l] == ["Executed: Set Port"]
        assert not any("8080" in l for l in lines)


async def test_plain_prompted_result_is_shown_but_not_the_value(make_app):
    app = make_app(MenuItem("Set Port", shortcut="p", prompt="Port:", action=lambda v: f"port → {v}"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "8080")
        text = panel_text(app)
        assert "Executed: Set Port → port → 8080" in text
        assert "'8080'" not in text


async def test_non_prompted_result_suffix_is_unchanged(make_app):
    app = make_app(leaf("Answer", "a", lambda: 42), leaf("Nothing", "n", lambda: None))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a", "enter")
        await pilot.press("n", "enter")
        lines = await read_panel(pilot)
        assert "Executed: Answer → 42" in lines
        assert "Executed: Nothing" in lines and "Executed: Nothing →" not in lines


# --------------------------------------------------------------------------- secret items

async def test_secret_value_never_appears_in_any_panel_line_and_has_no_result_suffix(make_app):
    app = make_app(MenuItem("Set Tok", shortcut="k", prompt="Token:", action=lambda v: f"tok {v}", secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, SECRET)
        lines = panel_lines(app)
        assert not any(SECRET in l for l in lines)
        executed = [l for l in lines if "Executed" in l]
        assert len(executed) == 1 and executed[0].endswith("Executed: Set Tok")
        assert "→" not in executed[0]


async def test_secret_item_without_a_prompt_also_suppresses_its_result(make_app):
    app = make_app(MenuItem("S", shortcut="s", action=lambda: "SECRETRESULT", secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        text = await read_panel(pilot)
        assert "Executed: S" in text and "SECRETRESULT" not in text


async def test_secret_value_is_redacted_from_exception_text(make_app):
    def reject(value):
        raise RuntimeError(f"bad token {value} rejected [/x]; {value}!")

    app = make_app(MenuItem("Bad Tok", shortcut="j", prompt="Token:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "s3cr3t")
        text = panel_text(app)
        assert "Error in Bad Tok: bad token *** rejected [/x]; ***!" in text
        assert "s3cr3t" not in text
        assert app.is_running


async def test_value_with_markup_like_characters_is_redacted_literally(make_app):
    value = "p[/w]d"

    def reject(v):
        raise ValueError(f"wrong {v}")

    app = make_app(MenuItem("T", shortcut="t", prompt="v:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t", "enter")
        await pilot.pause()
        app.screen.query_one("#prompt-input", Input).value = value
        await pilot.press("enter")
        text = await read_panel(pilot)
        assert "Error in T: wrong ***" in text and value not in text


async def test_empty_secret_value_leaves_the_error_text_untouched(make_app):
    def reject(value):
        raise ValueError("token required")

    app = make_app(MenuItem("Tok", shortcut="t", prompt="Token:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t", "enter")
        await pilot.pause()
        await pilot.press("enter")  # submit nothing
        await pilot.pause()
        lines = panel_lines(app)
        assert [l for l in lines if "Error in" in l] == ["Error in Tok: token required"]
        assert app.is_running


async def test_non_secret_error_text_is_not_redacted(make_app):
    def reject(value):
        raise ValueError(f"bad port {value}")

    app = make_app(MenuItem("Port", shortcut="p", prompt="Port:", action=reject))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "99999")
        assert "Error in Port: bad port 99999" in panel_text(app)


# --------------------------------------------------------------------------- nav bar masking

async def test_navbar_masks_a_secret_current_value(make_app):
    app = make_app(
        MenuItem("Token", shortcut="k", current_value=SECRET, secret=True, action=lambda: None),
        MenuItem("Pw", shortcut="w", secret=True, action=lambda: None),
        MenuItem("Port", shortcut="p", current_value=8080, action=lambda: None),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.query_one("#nav-bar", NavBar)
        plain = nav.render().plain
        assert "Token (••••)" in plain and SECRET not in plain
        assert "Pw " in plain and "Pw (" not in plain
        assert "Port (8080)" in plain
        assert "Token (••••)" in widget_text(nav) and SECRET not in widget_text(nav)


async def test_navbar_layout_uses_the_masked_width_not_the_raw_width(make_app):
    long_secret = "x" * 300
    secret_app = make_app(
        MenuItem("Token", shortcut="k", current_value=long_secret, secret=True, action=lambda: None),
        MenuItem("Port", shortcut="p", action=lambda: None),
    )
    plain_app = make_app(
        MenuItem("Token", shortcut="k", current_value=long_secret, action=lambda: None),
        MenuItem("Port", shortcut="p", action=lambda: None),
    )
    async with secret_app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        masked_rows = secret_app.query_one("#nav-bar", NavBar).render().plain.split("\n")
    async with plain_app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        raw_rows = plain_app.query_one("#nav-bar", NavBar).render().plain.split("\n")
    assert len(masked_rows) == 1, "the masked secret and the next item fit on one row"
    assert len(raw_rows) > 1, "control: the same long value unmasked forces a wrap"


# --------------------------------------------------------------------------- repr / str

@dataclass
class _Stock:  # reference: the stock dataclass repr with the same field layout as MenuItem
    label: str
    shortcut: str = ""
    description: str = ""
    children: list = field(default_factory=list)
    action: Callable[..., Any] | None = None
    prompt: str | None = None
    current_value: Any = None
    secret: bool = False


_Stock.__qualname__ = "MenuItem"  # the stock repr prints the class name


def build(cls: type, spec: dict) -> Any:
    spec = dict(spec)
    kids = spec.pop("children", [])
    return cls(**spec, children=[build(cls, k) for k in kids])


NON_SECRET_SPECS = [
    dict(label="x"),
    dict(label="a", shortcut="s", description="d", prompt="p", current_value=8080),
    dict(label="a", current_value="hunter2"),
    dict(label="a", current_value=None, action=print),
    dict(label="a", current_value=False),
    dict(label="a", current_value="it's [/x]\n"),
    dict(label="root", current_value=1, children=[
        dict(label="k1", current_value="v"), dict(label="k2", children=[dict(label="k3", shortcut="z")]),
    ]),
]


@pytest.mark.parametrize("spec", NON_SECRET_SPECS, ids=lambda s: s["label"] + str(s.get("current_value")))
def test_non_secret_menu_item_repr_is_identical_to_the_stock_dataclass_repr(spec):
    assert repr(build(MenuItem, spec)) == repr(build(_Stock, spec))


def test_secret_item_without_a_value_has_the_stock_repr():
    assert repr(MenuItem("x", secret=True)) == repr(_Stock("x", secret=True))


def test_secret_value_is_masked_in_repr_str_and_format():
    item = MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    for rendered in (repr(item), str(item), f"{item!r}", f"{item}", "%r" % (item,)):
        assert "SECRET123" not in rendered
    assert "current_value='***'" in repr(item) and "secret=True" in repr(item)
    assert item.current_value == "SECRET123", "masking must not change the stored value"


def test_secret_children_are_masked_inside_a_parents_repr_and_siblings_are_not():
    secret = MenuItem("Tok", current_value="SECRET123", secret=True)
    parent = MenuItem("P", children=[secret, MenuItem("Plain", current_value="visible")])
    rendered = repr(parent)
    assert "SECRET123" not in rendered and "current_value='visible'" in rendered
    deep = MenuItem("Top", children=[MenuItem("Mid", children=[secret])])
    assert "SECRET123" not in repr(deep)


def test_cyclic_menu_repr_terminates_and_still_masks():
    plain = MenuItem("C", current_value="abc")
    plain.children.append(plain)
    secret = MenuItem("S", current_value="topsecret", secret=True)
    secret.children.append(secret)
    assert "..." in repr(plain)
    assert "..." in repr(secret) and "topsecret" not in repr(secret)


def test_equality_and_replace_still_work_on_secret_items():
    item = MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    assert dataclasses.replace(item, label="n").current_value == "SECRET123"
    assert item == MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    assert item != MenuItem("Token", prompt="p", current_value="other", secret=True)
