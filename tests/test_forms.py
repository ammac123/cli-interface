"""P3.1 (form UI) and P3.3 (confirm dialog): FormScreen and ConfirmScreen mounted in a minimal host app."""
from __future__ import annotations

from typing import Any

import pytest
from textual.app import App
from textual.widgets import Button, Input, Select, SelectionList, Static, Switch

from cli_interface.params import ParamSpec
from cli_interface.widgets import ConfirmScreen, FormScreen
from helpers import HOSTILE, SIZE, wait_for, widget_text


class Host(App[None]):
    """Pushes one screen and records what it dismisses with and any Input.Submitted that leaks to the app."""

    def __init__(self, screen: Any) -> None:
        super().__init__()
        self._screen = screen
        self.results: list[Any] = []
        self.leaked: list[str] = []

    def on_mount(self) -> None:
        self.push_screen(self._screen, self._record)

    def _record(self, result: Any) -> None:
        self.results.append(result)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.leaked.append(event.value)


def spec(name: str, kind: str = "text", **kw: Any) -> ParamSpec:
    kw.setdefault("label", name.title())
    return ParamSpec(name=name, kind=kind, **kw)  # type: ignore[arg-type]


def form(*specs: ParamSpec, **kw: Any) -> tuple[Host, FormScreen]:
    screen = FormScreen("Settings", specs, **kw)
    return Host(screen), screen


def field(app: App[Any], name: str) -> Any:
    return app.screen.query_one(f"#form-field-{name}")


def error_of(app: App[Any], name: str) -> Static:
    return app.screen.query_one(f"#form-error-{name}", Static)


def error_text(app: App[Any], name: str) -> str:
    box = error_of(app, name)
    return widget_text(box).strip() if box.display else ""


def screen_text(app: App[Any]) -> str:
    """Everything drawn on the current screen, as plain text."""
    return "\n".join(strip.text.rstrip() for strip in app.screen._compositor.render_strips())


async def result_of(host: Host) -> Any:
    await wait_for(lambda: host.results, what="the screen to dismiss")
    return host.results[0]


CHOICES = {"mode": [("fast", "Fast"), ("slow", "Slow")], "tags": [("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")]}


# --------------------------------------------------------------------------- one widget per kind

async def test_each_kind_renders_the_right_widget_type():
    host, _ = form(
        spec("name", "text"), spec("count", "int"), spec("ratio", "float"), spec("where", "path"), spec("items", "list"),
        spec("flag", "bool"), spec("mode", "choice"), spec("tags", "multi"),
        choices=CHOICES,
    )
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        for name in ("name", "count", "ratio", "where", "items"):
            assert type(field(host, name)) is Input, name
        assert isinstance(field(host, "flag"), Switch)
        assert isinstance(field(host, "mode"), Select)
        assert isinstance(field(host, "tags"), SelectionList)
        assert host.screen.query_one("#form-submit", Button)
        assert host.screen.query_one("#form-cancel", Button)
        for name in ("name", "flag", "mode", "tags"):
            assert error_of(host, name) is not None


async def test_a_secret_field_is_masked_and_others_are_not():
    host, _ = form(spec("token", secret=True), spec("user"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert field(host, "token").password is True
        assert field(host, "user").password is False


async def test_the_first_field_has_focus_and_label_and_help_are_shown():
    host, _ = form(spec("user", label="User name", help="Who you are"), spec("other"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert host.screen.focused is field(host, "user")
        text = screen_text(host)
        assert "User name" in text and "Who you are" in text and "Settings" in text


async def test_the_submit_label_is_used():
    host, _ = form(spec("a"), submit_label="Go now")
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "Go now" in widget_text(host.screen.query_one("#form-submit", Button))


async def test_defaults_and_initial_values_prefill_the_fields():
    host, _ = form(
        spec("name", default="bob"), spec("count", "int", default=3), spec("flag", "bool", default=True),
        spec("secret", secret=True, default="hunter2"), spec("limit", "int", default=1),
        spec("mode", "choice", default="slow"), spec("tags", "multi", default=["b"]),
        choices=CHOICES, initial={"limit": 9, "name": "alice"},
    )
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert field(host, "name").value == "alice"
        assert field(host, "count").value == "3"
        assert field(host, "limit").value == "9"
        assert field(host, "flag").value is True
        assert field(host, "secret").value == ""
        assert field(host, "mode").value == "slow"
        assert field(host, "tags").selected == ["b"]


# --------------------------------------------------------------------------- submitting

async def test_a_valid_submit_dismisses_with_the_typed_dict():
    host, _ = form(
        spec("name", default=""), spec("count", "int"), spec("limit", "int", optional=True, default=5),
        spec("flag", "bool"), spec("mode", "choice"), spec("tags", "multi"),
        choices=CHOICES,
    )
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "name").value = "bob"
        field(host, "count").value = "42"
        field(host, "limit").value = ""
        field(host, "flag").value = True
        field(host, "mode").value = "slow"
        field(host, "tags").select("c")
        field(host, "tags").select("a")
        await pilot.click("#form-submit")
        result = await result_of(host)
    assert result == {"name": "bob", "count": 42, "limit": None, "flag": True, "mode": "slow", "tags": ["a", "c"]}
    assert type(result["count"]) is int


async def test_typing_then_enter_submits_through_the_real_keyboard():
    host, _ = form(spec("count", "int"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("1", "2", "enter")
        result = await result_of(host)
    assert result == {"count": 12}


async def test_enter_in_an_input_does_not_reach_the_host_app():
    host, _ = form(spec("name", default="x"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await result_of(host)
        await pilot.pause()
    assert host.leaked == []


async def test_enter_in_an_input_with_errors_does_not_leak_and_keeps_the_form_open():
    host, screen = form(spec("count", "int"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "count").value = "abc"
        await pilot.press("enter")
        await pilot.pause()
        assert host.screen is screen and host.results == []
    assert host.leaked == []


async def test_errors_keep_the_screen_open_show_inline_and_focus_the_first_bad_field():
    host, screen = form(spec("name", default=""), spec("count", "int"), spec("other", "int"), spec("fine", default=""))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "count").value = "x"
        field(host, "other").value = "y"
        await pilot.click("#form-submit")
        await pilot.pause()
        assert host.screen is screen and host.results == []
        assert error_text(host, "count") and error_text(host, "other")
        assert error_text(host, "name") == "" and not error_of(host, "name").display
        assert host.screen.focused is field(host, "count")


async def test_fixing_the_errors_and_resubmitting_clears_them_and_closes():
    host, _ = form(spec("count", "int"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "count").value = "x"
        await pilot.click("#form-submit")
        await pilot.pause()
        assert error_text(host, "count")
        await pilot.pause(0.3)  # a button ignores clicks while its press effect is still active
        field(host, "count").value = "7"
        await pilot.click("#form-submit")
        result = await result_of(host)
    assert result == {"count": 7}


async def test_a_required_field_left_empty_reports_an_error():
    host, screen = form(spec("count", "int"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#form-submit")
        await pilot.pause()
        assert host.screen is screen and host.results == []
        assert error_text(host, "count")


async def test_a_required_choice_with_no_choices_cannot_be_submitted():
    host, screen = form(spec("mode", "choice"), choices={"mode": []})
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(field(host, "mode"), Select)
        await pilot.click("#form-submit")
        await pilot.pause()
        assert host.screen is screen and host.results == []
        assert error_text(host, "mode")


async def test_an_optional_choice_starts_blank_and_submits_none():
    host, _ = form(spec("mode", "choice", optional=True), choices=CHOICES)
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert field(host, "mode").is_blank()
        await pilot.click("#form-submit")
        result = await result_of(host)
    assert result == {"mode": None}


async def test_a_required_choice_has_no_blank_option():
    host, _ = form(spec("mode", "choice", default="fast"), choices=CHOICES)
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        select = field(host, "mode")
        assert not select.is_blank()
        await pilot.click("#form-submit")
        assert await result_of(host) == {"mode": "fast"}


async def test_a_validate_callback_error_is_shown_inline():
    def no_admin(value: str) -> str:
        raise ValueError("not admin")

    host, screen = form(spec("user", validate=no_admin))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "user").value = "admin"
        await pilot.press("enter")
        await pilot.pause()
        assert host.screen is screen
        assert "not admin" in error_text(host, "user")


async def test_an_empty_form_submits_an_empty_dict():
    host, _ = form()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#form-submit")
        assert await result_of(host) == {}


# --------------------------------------------------------------------------- cancelling

async def test_escape_dismisses_with_none():
    host, _ = form(spec("name", default="x"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        assert await result_of(host) is None
        assert host.leaked == []


async def test_the_cancel_button_dismisses_with_none_even_with_invalid_input():
    host, _ = form(spec("count", "int"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "count").value = "bad"
        await pilot.click("#form-cancel")
        assert await result_of(host) is None


async def test_dismissing_twice_in_a_row_gives_one_result():
    host, _ = form(spec("name", default="x"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("enter", "enter")
        await pilot.pause()
    assert host.results == [{"name": "x"}]


# --------------------------------------------------------------------------- confirm dialog

def confirm(**kw: Any) -> tuple[Host, ConfirmScreen]:
    screen = ConfirmScreen("Confirm", "Run Build?", **kw)
    return Host(screen), screen


async def test_confirm_focus_starts_on_no():
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert host.screen.focused is host.screen.query_one("#confirm-no", Button)
        text = screen_text(host)
        assert "Confirm" in text and "Run Build?" in text and "Yes" in text and "No" in text


async def test_confirm_enter_returns_false():
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        assert await result_of(host) is False


@pytest.mark.parametrize(("key", "expected"), [("y", True), ("n", False), ("escape", False)])
async def test_confirm_keys(key: str, expected: bool):
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press(key)
        assert await result_of(host) is expected


async def test_confirm_buttons_and_tab_then_enter_choose_yes():
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.click("#confirm-yes")
        assert await result_of(host) is True
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("shift+tab", "enter")
        assert await result_of(host) is True


async def test_confirm_custom_button_labels():
    host, _ = confirm(yes="Do it", no="Cancel")
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "Do it" in widget_text(host.screen.query_one("#confirm-yes", Button))
        assert "Cancel" in widget_text(host.screen.query_one("#confirm-no", Button))


async def test_confirm_answers_only_once():
    host, _ = confirm()
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("y", "n")
        await pilot.pause()
    assert host.results == [True]


# --------------------------------------------------------------------------- literal text

@pytest.mark.parametrize("hostile", HOSTILE)
async def test_hostile_strings_render_literally_in_the_form(hostile: str):
    def reject(value: str) -> str:
        raise ValueError(hostile)

    specs = [
        spec("name", label=hostile, help=hostile, validate=reject, default=""),
        spec("mode", "choice", label=hostile, default="x"),
        spec("tags", "multi", label=hostile),
    ]
    choices = {"mode": [("x", hostile)], "tags": [("t", hostile)]}
    host = Host(FormScreen("T " + hostile, specs, choices=choices, submit_label=hostile))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        field(host, "name").value = "v"
        await pilot.click("#form-submit")
        await pilot.pause()
        text = screen_text(host)
        assert text.count(hostile) >= 5
        assert error_text(host, "name") == hostile


@pytest.mark.parametrize("hostile", HOSTILE)
async def test_hostile_strings_render_literally_in_the_confirm_dialog(hostile: str):
    host = Host(ConfirmScreen(hostile, hostile, yes=hostile, no=hostile + "!"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(host)
        assert text.count(hostile) >= 4
        await pilot.press("y")
        assert await result_of(host) is True


async def test_a_dotted_field_name_does_not_break_the_widget_ids():
    host, _ = form(spec("db.host", default="h"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("enter")
        assert await result_of(host) == {"db.host": "h"}


async def test_a_non_ascii_field_name_composes_and_submits():
    host, screen = form(spec("größe", default="5"), spec("名前", default="x"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        ids = [screen._inputs[name].id for name in ("größe", "名前")]
        assert all(widget_id and widget_id.isascii() for widget_id in ids)
        assert len(set(ids)) == 2
        await pilot.press("enter")
        assert await result_of(host) == {"größe": "5", "名前": "x"}


async def test_colliding_field_names_each_keep_their_own_widget():
    host, screen = form(spec("a.b", default="1"), spec("a_b", default="2"))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert screen._inputs["a.b"].id != screen._inputs["a_b"].id
        screen._inputs["a.b"].value = "dotted"
        screen._inputs["a_b"].value = "underscored"
        await pilot.press("enter")
        assert await result_of(host) == {"a.b": "dotted", "a_b": "underscored"}


async def test_an_error_on_one_colliding_field_shows_under_that_field():
    def reject(value: str) -> str:
        if value == "bad":
            raise ValueError("no bad values")
        return value

    host, screen = form(spec("a.b", validate=reject, default=""), spec("a_b", default=""))
    async with host.run_test(size=SIZE) as pilot:
        await pilot.pause()
        screen._inputs["a.b"].value = "bad"
        screen._inputs["a_b"].value = "fine"
        await pilot.click("#form-submit")
        await pilot.pause()
        assert widget_text(screen._errors["a.b"]).strip() == "no bad values"
        assert screen._errors["a.b"].display
        assert not screen._errors["a_b"].display
        assert host.results == []


# --------------------------------------------------------------------------- short terminals

MANY = [spec(f"f{i}", "text") for i in range(10)] + [spec("flag", "bool")]


@pytest.mark.parametrize("rows", [20, 24, 30, 40])
async def test_form_buttons_stay_on_screen_in_short_terminals(rows):
    host, _ = form(*MANY)
    async with host.run_test(size=(120, rows)) as pilot:
        await pilot.pause()
        screen = host.screen
        dialog = screen.query_one(".dialog")
        assert screen.region.contains_region(dialog.region)
        for button in ("#form-submit", "#form-cancel"):
            assert dialog.region.contains_region(screen.query_one(button).region)
            assert screen.query_one(button).region.bottom <= rows
        fields = screen.query_one("#form-fields")
        last = field(host, "flag")
        last.focus()
        await wait_for(lambda: fields.region.contains_region(last.region), what="the last field to scroll into view")


async def test_small_form_keeps_its_natural_height():
    host, _ = form(spec("a"), spec("b"))
    async with host.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        fields = host.screen.query_one("#form-fields")
        assert fields.region.height == fields.virtual_size.height


@pytest.mark.parametrize("rows", [12, 20, 24])
async def test_confirm_dialog_fits_in_short_terminals(rows):
    host = Host(ConfirmScreen("Sure?", "word " * 80))
    async with host.run_test(size=(120, rows)) as pilot:
        await pilot.pause()
        screen = host.screen
        assert screen.region.contains_region(screen.query_one(".dialog").region)
        assert screen.query_one("#confirm-yes").region.bottom <= rows
