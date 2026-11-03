"""Phase 3 integration: command forms, confirm=, App.settings, the shared secret set and capture_loggers, all through Pilot."""
import argparse
import dataclasses
import enum
import functools
import io
import logging
import threading
from pathlib import Path
from typing import Annotated, Any, Literal

import pytest
from rich.console import Console
from textual.widgets import Button, Select

import cli_interface
from cli_interface import App, Context, Param, Secret
from cli_interface.commands import _first_doc_line
from cli_interface.menu import _CommandItem
from cli_interface.params import FormContext, ParamSpec
from cli_interface.widgets import ConfirmScreen, FormScreen
from helpers import HOSTILE, crumbs, SIZE, make_gate, panel_text, press_and_wait, type_command, wait_for, widget_text

PASSWORD = "pw-s3cret-7421"


class Color(enum.Enum):
    RED = 1
    BLUE = 2


def field(app: App, name: str) -> Any:
    return app.screen.query_one(f"#form-field-{name}")


def error_of(app: App, name: str) -> str:
    box = app.screen.query_one(f"#form-error-{name}")
    return widget_text(box).strip() if box.display else ""


def screen_text(app: App) -> str:
    return "\n".join(strip.text.rstrip() for strip in app.screen._compositor.render_strips())


def nav(app: App) -> str:
    return widget_text(app.query_one("#nav-bar"))


def on_form(app: App) -> bool:
    return isinstance(app.screen, FormScreen)


def on_confirm(app: App) -> bool:
    return isinstance(app.screen, ConfirmScreen)


def on_base(app: App) -> bool:
    return not isinstance(app.screen, FormScreen | ConfirmScreen)


async def fill_and_submit(pilot: Any, jobs: int = 1, **values: Any) -> None:
    app = pilot.app
    for name, value in values.items():
        field(app, name).value = value
    mark = app.jobs.mark()
    await pilot.click("#form-submit")
    await app.jobs.wait_idle(since=mark, jobs=jobs)
    await pilot.pause()


async def answer_confirm(pilot: Any, key: str) -> None:
    await pilot.press(key)
    await pilot.pause()


def banner_commands() -> tuple[App, dict[str, Any]]:
    app = App("T")
    seen: dict[str, Any] = {}

    @app.command("Scrape", key="s")
    def scrape(
        ctx: Context,
        filter: Literal["all", "new"],
        limit: int = 4,
        headless: bool = True,
        password: Annotated[str, Secret()] = "",
    ) -> str:
        seen.update(filter=filter, limit=limit, headless=headless, password=password)
        return "scraped"

    return app, seen


# --------------------------------------------------------------------------- P3.1: forms from a signature

async def test_a_command_with_typed_params_opens_a_form_and_runs_with_typed_kwargs():
    app, seen = banner_commands()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert on_form(app)
        assert field(app, "limit").value == "4" and field(app, "headless").value is True
        assert field(app, "password").password is True
        assert seen == {}, "nothing runs before the form is submitted"
        await fill_and_submit(pilot, filter="new", limit="9", headless=False, password=PASSWORD)
        assert on_base(app)
        assert seen == {"filter": "new", "limit": 9, "headless": False, "password": PASSWORD}
        assert type(seen["limit"]) is int and type(seen["headless"]) is bool
        assert "Executed: Scrape" in panel_text(app)


async def test_untouched_defaults_are_delivered():
    app, seen = banner_commands()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await fill_and_submit(pilot, filter="all")
        assert seen == {"filter": "all", "limit": 4, "headless": True, "password": ""}


async def test_invalid_values_leave_the_form_open_with_inline_errors_until_fixed():
    app, seen = banner_commands()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        field(app, "limit").value = "many"
        await pilot.click("#form-submit")
        await pilot.pause(0.3)
        assert on_form(app) and seen == {}
        assert error_of(app, "limit") == "Enter a whole number"
        assert error_of(app, "filter") == ""
        assert "Executed" not in panel_text(app)
        await fill_and_submit(pilot, filter="new", limit="12")
        assert on_base(app) and seen["limit"] == 12


async def test_escape_in_the_form_runs_nothing_and_logs_nothing():
    app, seen = banner_commands()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        before = panel_text(app)
        await pilot.press("escape")
        await pilot.pause()
        assert on_base(app) and seen == {} and not app.jobs.busy
        assert panel_text(app) == before


async def test_a_choices_callable_is_resolved_with_the_state_each_time_the_form_opens():
    app = App("T")
    seen: list[str] = []
    asked: list[Any] = []

    def pick(c: FormContext) -> list[str]:
        asked.append(c)
        return list(c.state.options)

    @app.command("Pick", key="p")
    def run(who: Annotated[str, Param(choices=pick)]) -> None:
        seen.append(who)

    app.state.options = ["ann", "bob"]
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "p")
        assert isinstance(field(app, "who"), Select) and asked and asked[0].state is app.state
        await fill_and_submit(pilot, who="bob")
        app.state.options = ["cy"]
        await type_command(pilot, "p")
        await fill_and_submit(pilot, who="cy")
    assert seen == ["bob", "cy"]


async def test_a_failing_choices_callable_logs_and_opens_nothing():
    app = App("T")

    def broken() -> list[str]:
        raise RuntimeError("no backend")

    @app.command("Pick", key="p")
    def run(who: Annotated[str, Param(choices=broken)]) -> None: ...

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "p")
        assert on_base(app) and not app.jobs.busy
        assert "Cannot open form: no backend" in panel_text(app)


async def test_opening_is_rejected_with_a_busy_warning_while_a_job_runs():
    app, seen = banner_commands()
    gate = make_gate()
    started = threading.Event()

    @app.command("Slow", key="w")
    def slow(ctx: Context) -> None:
        started.set()
        gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        await wait_for(started.is_set, what="the slow job")
        await type_command(pilot, "s")
        assert on_base(app) and seen == {}
        assert "Busy: Slow is running" in panel_text(app)
        gate.set()
        await app.jobs.wait_idle()


async def test_every_field_kind_is_delivered_with_its_python_type():
    app = App("T")
    seen: dict[str, Any] = {}

    @app.command("All", key="a")
    def run(
        name: str, count: int, ratio: float, where: Path, color: Color,
        tags: list[str], opt: int | None = 5, flag: bool = False,
    ) -> None:
        seen.update(name=name, count=count, ratio=ratio, where=where, color=color, tags=tags, opt=opt, flag=flag)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "a")
        await fill_and_submit(
            pilot, name="n", count="2", ratio="1.5", where="/tmp/x", color=Color.BLUE, tags="a, b", opt="", flag=True,
        )
    assert seen == {
        "name": "n", "count": 2, "ratio": 1.5, "where": Path("/tmp/x"), "color": Color.BLUE,
        "tags": ["a", "b"], "opt": None, "flag": True,
    }


# --------------------------------------------------------------------------- P3.1: params= and legacy behaviour

@dataclasses.dataclass
class Job:
    target: str
    retries: int = 2


async def test_a_dataclass_params_delivers_one_instance():
    app = App("T")
    seen: list[Any] = []

    @app.command("Do", key="d", params=Job)
    def run(ctx: Context, job: Job) -> None:
        seen.append(job)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "d")
        await fill_and_submit(pilot, target="prod", retries="5")
    assert seen == [Job("prod", 5)] and type(seen[0]) is Job


async def test_an_argparse_params_delivers_a_namespace():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    app = App("T")
    seen: list[Any] = []
    app.add_command("Do", lambda ns: seen.append(ns), key="d", params=parser)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "d")
        await fill_and_submit(pilot, name="x", count="7", verbose=True)
    assert seen == [argparse.Namespace(name="x", count=7, verbose=True)]


@pytest.mark.parametrize("exc_type", [ValueError, RuntimeError])
async def test_a_params_dataclass_that_raises_logs_an_error_redacted_and_keeps_the_app_running(exc_type):
    app = App("T")
    seen: list[Any] = []

    @dataclasses.dataclass
    class Login:
        user: str
        token: Annotated[str, Secret()] = ""

        def __post_init__(self) -> None:
            raise exc_type(f"token {self.token} is rejected for {self.user}")

    @app.command("Login", key="l", params=Login)
    def run(ctx: Context, login: Login) -> None:
        seen.append(login)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "l")
        field(app, "user").value = "ann"
        field(app, "token").value = PASSWORD
        await pilot.click("#form-submit")
        await pilot.pause(0.3)
        assert app.is_running and on_base(app)
        assert "Cannot run Login: token *** is rejected for ann" in panel_text(app)
        assert PASSWORD not in panel_text(app)
        assert seen == [] and not app.jobs.busy
        assert "Executed" not in panel_text(app)


async def test_explicit_specs_replace_the_signature():
    app = App("T")
    seen: list[Any] = []
    spec = ParamSpec(name="n", kind="int", label="N", default=1, min=1)
    app.add_command("Do", lambda n: seen.append(n), key="d", params=[spec])
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "d")
        field(app, "n").value = "0"
        await pilot.click("#form-submit")
        await pilot.pause(0.3)
        assert error_of(app, "n") == "Must be at least 1"
        await fill_and_submit(pilot, n="3")
    assert seen == [3]


async def test_a_command_without_extra_parameters_is_unchanged():
    app = App("T")
    seen: list[str] = []

    @app.command("Plain", key="p")
    def plain(ctx: Context, *args: Any, **kwargs: Any) -> None:
        seen.append("ran")

    app.add_command("Bare", lambda: seen.append("bare"), key="r")
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, *"p", "enter")
        await press_and_wait(pilot, *"r", "enter")
    assert seen == ["ran", "bare"]


async def test_extra_supported_parameters_show_a_form_and_params_false_restores_the_old_run():
    app = App("T")
    seen: list[int] = []

    def work(n: int = 3) -> None:
        seen.append(n)

    app.add_command("Form", work, key="f")
    app.add_command("Legacy", work, key="l", params=False)
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, *"l", "enter")
        assert seen == [3] and on_base(app)
        await type_command(pilot, "f")
        assert on_form(app) and seen == [3]
        await fill_and_submit(pilot, n="8")
    assert seen == [3, 8]


async def test_an_unsupported_parameter_with_a_default_is_skipped_so_the_function_still_runs():
    app = App("T")
    seen: list[Any] = []

    def work(cache: dict = {}) -> None:  # noqa: B006
        seen.append(cache)

    app.add_command("Work", work, key="w")
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, *"w", "enter")
    assert seen == [{}]


def test_registration_fails_early_with_the_command_and_parameter_named():
    app = App("T")

    def needs(thing: dict) -> None: ...

    with pytest.raises(ValueError, match=r"'Group/Needs'.*'thing'"):
        app.add_command("Group/Needs", needs)
    assert app._state.root.children == []

    def strict(cache: dict = {}) -> None: ...  # noqa: B006

    with pytest.raises(ValueError, match="cache"):
        app.add_command("Strict", strict, params=True)
    with pytest.raises(ValueError, match="positional-only"):
        app.add_command("Pos", lambda a, /: None)
    with pytest.raises(ValueError, match="exactly one"):
        app.add_command("Two", lambda a, b: None, params=Job)
    with pytest.raises(ValueError, match="not a parameter"):
        app.add_command("Unknown", lambda a=1: None, params=[ParamSpec(name="zzz", kind="text", label="Z")])
    with pytest.raises(ValueError, match="no field"):
        app.add_command("Missing", lambda a, b: None, params=[ParamSpec(name="a", kind="text", label="A")])
    with pytest.raises(TypeError, match="params"):
        app.add_command("Bad", lambda: None, params=3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="confirm"):
        app.add_command("Bad", lambda: None, confirm=3)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="confirm"):
        app.command("Bad", confirm=3)  # type: ignore[arg-type]
    assert app._state.root.children == []


def test_a_dataclass_or_parser_params_needs_one_receiving_parameter():
    app = App("T")
    app.add_command("Ok", lambda ctx, job: None, params=Job)
    with pytest.raises(ValueError, match="exactly one"):
        app.add_command("None", lambda ctx: None, params=Job)


def test_the_decorator_derives_params_like_add_command():
    app = App("T")

    @app.command("X", key="x", confirm=True)
    def x(n: int = 1) -> None: ...

    leaf = app._state.root.children[0]
    assert isinstance(leaf, _CommandItem)
    assert [s.name for s in leaf.params] == ["n"] and leaf.confirm == "Run X?"


# --------------------------------------------------------------------------- P3.3: confirm

def confirm_app(confirm: bool | str) -> tuple[App, list[str]]:
    app = App("T")
    seen: list[str] = []
    app.add_command("Wipe", lambda: seen.append("wiped"), key="w", confirm=confirm)
    return app, seen


@pytest.mark.parametrize("confirm, shown", [(True, "Run Wipe?"), ("Really wipe everything?", "Really wipe everything?")])
async def test_confirm_defaults_to_cancel_and_yes_runs_the_job(confirm, shown):
    app, seen = confirm_app(confirm)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        assert on_confirm(app) and shown in screen_text(app)
        assert app.screen.focused is app.screen.query_one("#confirm-no", Button)
        assert "Cancel" in widget_text(app.screen.query_one("#confirm-no", Button))
        await pilot.press("enter")
        await pilot.pause()
        assert on_base(app) and seen == [] and not app.jobs.busy
        await type_command(pilot, "w")
        mark = app.jobs.mark()
        await pilot.press("y")
        await app.jobs.wait_idle(since=mark)
        await pilot.pause()
    assert seen == ["wiped"]


@pytest.mark.parametrize("key", ["escape", "n"])
async def test_declining_the_confirm_runs_nothing_and_logs_nothing(key):
    app = App("T")
    seen: list[str] = []
    app.add_command("Wipe", lambda: seen.append("x"), key="w", confirm=True)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        assert on_confirm(app)
        before = panel_text(app)
        await answer_confirm(pilot, key)
        assert on_base(app) and seen == [] and not app.jobs.busy and panel_text(app) == before


async def test_the_confirm_message_is_shown_literally():
    app = App("T")
    for i, text in enumerate(HOSTILE):
        app.add_command(f"C{i}", lambda: None, key=f"k{i}", confirm=text)
    async with app.run_test(size=SIZE) as pilot:
        for i, text in enumerate(HOSTILE):
            await type_command(pilot, f"k{i}")
            assert text in screen_text(app)
            await answer_confirm(pilot, "escape")


async def test_the_form_comes_first_and_declining_the_confirm_discards_its_values():
    app = App("T")
    seen: list[int] = []
    app.add_command("Del", lambda n: seen.append(n), key="d", params=[ParamSpec(name="n", kind="int", label="N")], confirm="Sure?")
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "d")
        assert on_form(app)
        field(app, "n").value = "4"
        await pilot.click("#form-submit")
        await pilot.pause()
        assert on_confirm(app) and "Sure?" in screen_text(app) and seen == []
        await answer_confirm(pilot, "n")
        assert seen == [] and on_base(app)
        await type_command(pilot, "d")
        field(app, "n").value = "6"
        await pilot.click("#form-submit")
        await pilot.pause()
        mark = app.jobs.mark()
        await pilot.press("y")
        await app.jobs.wait_idle(since=mark)
    assert seen == [6]


async def test_a_busy_app_refuses_the_confirm_dialog_too():
    app, seen = confirm_app(True)
    gate = make_gate()
    started = threading.Event()

    @app.command("Slow", key="s")
    def slow(ctx: Context) -> None:
        started.set()
        gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await wait_for(started.is_set)
        await type_command(pilot, "w")
        assert on_base(app) and "Busy" in panel_text(app)
        gate.set()
        await app.jobs.wait_idle()


# --------------------------------------------------------------------------- C2-2: secrets

def test_the_secret_set_is_the_union_of_values_and_sources_and_skips_failures():
    app = App("T")
    app.add_secret("one")
    app.add_secret("")
    app.add_secret_source(lambda: ["two", "one", ""])

    def broken() -> list[str]:
        raise RuntimeError("x")

    app.add_secret_source(broken)
    assert app.secret_values() == ("one", "two")
    with pytest.raises(TypeError):
        app.add_secret(3)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        app.add_secret_source("x")  # type: ignore[arg-type]


async def test_a_masked_form_value_never_reaches_the_panel_a_logger_or_an_error(unique_logger):
    logger = unique_logger("secret")
    app = App("T", capture_loggers=[logger.name])
    logger.setLevel(logging.INFO)

    @app.command("Login", key="l")
    def login(ctx: Context, password: Annotated[str, Secret()]) -> str:
        ctx.log(f"ctx {password}")
        print(f"print {password}")
        logger.info("record %s", password)
        raise RuntimeError(f"rejected {password}")

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "l")
        await fill_and_submit(pilot, password=PASSWORD)
        logger.warning("later %s", PASSWORD)  # after the job: the set is sticky for the session
        await pilot.pause()
        await pilot.pause()
        text = panel_text(app)
        assert "Error in Login" in text and "ctx ***" in text and "print ***" in text
        assert "record ***" in text and "rejected ***" in text and "later ***" in text
        assert PASSWORD not in text
        assert PASSWORD in app.secret_values()


async def test_a_secret_field_in_a_dataclass_is_redacted_too():
    @dataclasses.dataclass
    class Login:
        user: str
        token: Annotated[str, Secret()]

    app = App("T")

    @app.command("Login", key="l", params=Login)
    def login(ctx: Context, data: Login) -> str:
        ctx.log(f"{data.user}/{data.token}")
        return f"token={data.token}"

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "l")
        await fill_and_submit(pilot, user="ann", token=PASSWORD)
        text = panel_text(app)
        assert "ann/***" in text and "token=***" in text and PASSWORD not in text


def test_the_fatal_traceback_does_not_print_form_values():
    app, _ = banner_commands()

    def submit_form() -> None:
        values = {"password": PASSWORD}  # noqa: F841
        raise RuntimeError("boom")

    try:
        submit_form()
    except RuntimeError:
        app._fatal_error()
    console = Console(file=io.StringIO(), width=240, force_terminal=False, color_system=None)
    for renderable in app._exit_renderables:
        console.print(renderable)
    text = console.file.getvalue()  # type: ignore[attr-defined]
    assert "boom" in text and "submit_form" in text and PASSWORD not in text


# --------------------------------------------------------------------------- C2-3 and X-1

async def test_capture_loggers_route_records_to_the_panel_and_detach_on_exit(unique_logger):
    logger = unique_logger("cap", level=logging.NOTSET)
    app = App("T", capture_loggers=[logger.name], capture_level="INFO")
    async with app.run_test(size=SIZE) as pilot:
        logger.info("hello from the logger")
        logger.debug("too quiet")
        await pilot.pause()
        text = panel_text(app)
        assert "hello from the logger" in text and "too quiet" not in text
        assert any(type(h).__name__ == "TUILogHandler" for h in logger.handlers)
        app.on_mount()  # a second mount must not attach again
        assert sum(type(h).__name__ == "TUILogHandler" for h in logger.handlers) == 1
    assert not any(type(h).__name__ == "TUILogHandler" for h in logger.handlers)
    assert logger.level == logging.NOTSET


async def test_capture_loggers_accepts_logger_objects(unique_logger):
    logger = unique_logger("obj")
    app = App("T", capture_loggers=[logger])
    async with app.run_test(size=SIZE) as pilot:
        logger.info("by object")
        await pilot.pause()
        assert "by object" in panel_text(app)


def test_capture_arguments_are_validated():
    with pytest.raises(TypeError):
        App("T", capture_loggers="mylogger")
    with pytest.raises(TypeError):
        App("T", capture_loggers=[3])  # type: ignore[list-item]
    with pytest.raises(ValueError, match="capture_level"):
        App("T", capture_level="LOUD")
    with pytest.raises(ValueError, match="capture_level"):
        App("T", capture_level=True)


def test_a_partial_does_not_pick_up_the_docstring_of_its_class():
    def documented() -> None:
        """First line."""

    assert _first_doc_line(documented) == "First line."
    assert _first_doc_line(functools.partial(documented)) == ""
    assert _first_doc_line(functools.partialmethod(documented)) == ""  # type: ignore[arg-type]


def test_the_public_api_gains_param_and_secret():
    assert cli_interface.Param is Param and cli_interface.Secret is Secret
    assert len(cli_interface.__all__) == 15 and {"Param", "Secret"} <= set(cli_interface.__all__)


# --------------------------------------------------------------------------- P3.2: settings

@dataclasses.dataclass
class Database:
    host: str = "localhost"
    port: int = 5432


@dataclasses.dataclass
class Config:
    name: str = "app"
    debug: bool = False
    color: Color = Color.RED
    token: str = ""
    db: Database = dataclasses.field(default_factory=Database)
    note: str | None = None


def settings_app(model: Any, **kw: Any) -> tuple[App, list[Any]]:
    app = App("T")
    saves: list[Any] = []

    def save(ctx: Any) -> None:
        saves.append(dataclasses.replace(model, db=dataclasses.replace(model.db)) if dataclasses.is_dataclass(model) else None)

    kw.setdefault("save", save)
    app.settings("Settings", model, key="s", **kw)
    return app, saves


async def open_item(pilot: Any, position: int) -> None:
    await type_command(pilot, str(position))


async def edit(pilot: Any, position: int, **values: Any) -> None:
    await open_item(pilot, position)
    assert on_form(pilot.app)
    await fill_and_submit(pilot, **values)


async def test_settings_show_fields_nested_submenus_and_live_values():
    cfg = Config()
    app, _ = settings_app(cfg, secret=["token"])
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        text = nav(app)
        for label in ("Name (app)", "Debug (False)", "Color (RED)", "Note (-)", "Db", "Reset to defaults"):
            assert label in text, label
        assert "Token (••••)" in text
        await open_item(pilot, 5)  # Db
        assert "Host (localhost)" in nav(app) and "Port (5432)" in nav(app)
        assert "Reset" not in nav(app) and "Name" not in nav(app)
        await pilot.press("escape")
        await pilot.pause()
        assert "Name (app)" in nav(app)


async def test_an_edit_updates_the_model_and_the_label_and_calls_save_once():
    cfg = Config()
    app, saves = settings_app(cfg)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await edit(pilot, 1, value="renamed")
        assert cfg.name == "renamed" and len(saves) == 1 and saves[0].name == "renamed"
        assert "Name (renamed)" in nav(app) and "Executed: Set Name" in panel_text(app)
        await edit(pilot, 2, value=True)
        assert cfg.debug is True and "Debug (True)" in nav(app) and len(saves) == 2
        await edit(pilot, 3, value=Color.BLUE)
        assert cfg.color is Color.BLUE and "Color (BLUE)" in nav(app)
        await edit(pilot, 1, value="renamed")  # unchanged: no save
        assert len(saves) == 3
        await open_item(pilot, 5)
        await edit(pilot, 2, value="9000")
        assert cfg.db.port == 9000 and "Port (9000)" in nav(app)
    assert len(saves) == 4


async def test_the_edit_form_is_prefilled_with_the_current_value_and_an_optional_field_can_be_cleared():
    cfg = Config(name="seed", note="x")
    app, _ = settings_app(cfg)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await open_item(pilot, 1)
        assert field(app, "value").value == "seed"
        await pilot.press("escape")
        await pilot.pause()
        assert cfg.name == "seed" and not app.jobs.busy
        await edit(pilot, 6, value="")
        assert cfg.note is None and "Note (-)" in nav(app)


async def test_a_save_that_raises_rolls_the_value_back_and_shows_an_error():
    cfg = Config()
    calls: list[int] = []

    def save(ctx: Context) -> None:
        calls.append(1)
        raise OSError("disk full")

    app, _ = settings_app(cfg, save=save)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await edit(pilot, 1, value="changed")
        assert cfg.name == "app" and calls == [1]
        assert "Error in Set Name" in panel_text(app) and "disk full" in panel_text(app)
        assert "Name (app)" in nav(app)


async def test_save_none_keeps_the_change_in_memory_only():
    cfg = Config()
    app, _ = settings_app(cfg, save=None)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await edit(pilot, 1, value="mem")
    assert cfg.name == "mem"


async def test_reset_asks_for_confirmation_and_writes_defaults_in_place():
    cfg = Config(name="x", debug=True, color=Color.BLUE, note="n")
    cfg.db.host, cfg.db.port = "remote", 1
    nested = cfg.db
    app, saves = settings_app(cfg)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await open_item(pilot, 7)
        assert on_confirm(app) and "Reset all Settings settings to their defaults?" in screen_text(app)
        await answer_confirm(pilot, "n")
        assert cfg.name == "x" and saves == []
        await open_item(pilot, 7)
        mark = app.jobs.mark()
        await pilot.press("y")
        await app.jobs.wait_idle(since=mark)
        await pilot.pause()
    assert (cfg.name, cfg.debug, cfg.color, cfg.note) == ("app", False, Color.RED, None)
    assert cfg.db is nested and (nested.host, nested.port) == ("localhost", 5432)
    assert len(saves) == 1


async def test_reset_rolls_back_when_save_raises():
    cfg = Config(name="x")

    def save(ctx: Context) -> None:
        raise OSError("nope")

    app, _ = settings_app(cfg, save=save)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await open_item(pilot, 7)
        mark = app.jobs.mark()
        await pilot.press("y")
        await app.jobs.wait_idle(since=mark)
    assert cfg.name == "x"


async def test_reset_false_omits_the_reset_item():
    app, _ = settings_app(Config(), reset=False)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "Reset" not in nav(app)


async def test_a_callable_model_is_resolved_each_time_the_group_is_entered():
    made: list[Config] = []

    def factory(c: FormContext) -> Config:
        made.append(Config(name=f"gen{len(made)}"))
        return made[-1]

    app = App("T")
    app.settings("Settings", factory, key="s")
    async with app.run_test(size=SIZE) as pilot:
        assert made == [], "nothing is called while registering"
        await type_command(pilot, "s")
        assert len(made) == 1 and "Name (gen0)" in nav(app)
        await edit(pilot, 1, value="edited")
        assert made[0].name == "edited"
        await pilot.press("escape")
        await pilot.pause()
        await type_command(pilot, "s")
        assert len(made) == 2 and "Name (gen1)" in nav(app)


async def test_a_factory_that_raises_logs_a_warning_and_does_not_navigate():
    def factory() -> Config:
        raise RuntimeError("no config file")

    app = App("T")
    app.settings("Settings", factory, key="s")
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "Settings unavailable: no config file" in panel_text(app)
        assert "Settings" in nav(app) and "Name" not in nav(app)


async def test_a_factory_returning_a_non_model_logs_a_warning():
    app = App("T")
    app.settings("Settings", lambda: {"a": 1}, key="s")
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "Settings unavailable:" in panel_text(app)


def test_settings_registration_errors():
    app = App("T")
    with pytest.raises(TypeError, match="instance"):
        app.settings("A", Config)
    with pytest.raises(TypeError, match="frozen"):
        app.settings("A", dataclasses.make_dataclass("F", [("x", int, 1)], frozen=True)())
    with pytest.raises(TypeError):
        app.settings("A", {"x": 1})
    with pytest.raises(TypeError, match="secret"):
        app.settings("A", Config(), secret="token")
    with pytest.raises(TypeError, match="save"):
        app.settings("A", Config(), save="no")  # type: ignore[arg-type]

    async def async_save() -> None: ...

    with pytest.raises(TypeError, match="save"):
        app.settings("A", Config(), save=async_save)
    with pytest.raises(ValueError, match="invalid path"):
        app.settings("A//B", Config())
    assert app._state.root.children == []
    app.settings("Tools/Settings", Config())
    with pytest.raises(ValueError, match="already registered"):
        app.settings("Tools/Settings", Config())
    app.add_command("Tools/Run", lambda: None)
    assert [c.label for c in app._state.root.children[0].children] == ["Settings", "Run"]


async def test_an_empty_settings_group_does_not_navigate():
    @dataclasses.dataclass
    class Empty:
        _hidden: int = 0

    app = App("T")
    app.settings("Settings", Empty(), key="s", reset=False)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "Settings" in nav(app) and crumbs(app) == ("T",)


async def test_the_settings_group_shortcut_conflict_is_reported_like_a_command():
    app = App("T", strict_shortcuts=True)
    app.add_command("A", lambda: None, key="s")
    with pytest.raises(ValueError, match="shortcut"):
        app.settings("Settings", Config(), key="s")
    assert [c.label for c in app._state.root.children] == ["A"]


async def test_a_settings_edit_is_refused_while_another_job_runs():
    cfg = Config()
    app, saves = settings_app(cfg)
    gate = make_gate()
    started = threading.Event()

    @app.command("Slow", key="w")
    def slow(ctx: Context) -> None:
        started.set()
        gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        await wait_for(started.is_set)
        await type_command(pilot, "s")
        await open_item(pilot, 1)
        assert on_base(app) and "Busy: Slow is running" in panel_text(app) and saves == []
        gate.set()
        await app.jobs.wait_idle()


async def test_a_secret_setting_is_masked_keeps_its_value_on_an_empty_submit_and_is_redacted(unique_logger):
    logger = unique_logger("setting")
    cfg = Config(token="tok-9f8e7d6c")
    app = App("T", capture_loggers=[logger.name])
    app.settings("Settings", cfg, key="s", secret=["token"])
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "Token (••••)" in nav(app) and "tok-9f8e7d6c" not in nav(app)
        logger.info("connecting with %s", cfg.token)
        await pilot.pause()
        assert "connecting with ***" in panel_text(app) and "tok-9f8e7d6c" not in panel_text(app)
        await open_item(pilot, 4)
        assert field(app, "value").password is True and field(app, "value").value == ""
        await fill_and_submit(pilot, value="")
        assert cfg.token == "tok-9f8e7d6c"
        await open_item(pilot, 4)
        await fill_and_submit(pilot, value="new-secret-1234")
        assert cfg.token == "new-secret-1234" and "new-secret-1234" not in nav(app)
        logger.info("now %s", cfg.token)
        await pilot.pause()
        text = panel_text(app)
        assert "now ***" in text and "new-secret-1234" not in text and "tok-9f8e7d6c" not in text
        assert {"new-secret-1234"} <= set(app.secret_values())


async def test_a_dotted_secret_name_masks_a_nested_field():
    cfg = Config()
    cfg.db.host = "db.internal.example"
    app = App("T")
    app.settings("Settings", cfg, key="s", secret=["db.host"])
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await open_item(pilot, 5)
        assert "Host (••••)" in nav(app) and "internal" not in nav(app) and "Port (5432)" in nav(app)
        assert "db.internal.example" in app.secret_values()


async def test_hostile_text_in_labels_and_values_is_shown_literally():
    @dataclasses.dataclass
    class Hostile:
        label: Annotated[str, Param(label="[/x] label", help="matrix[i][j]")] = "[bold]x[/bold]"

    cfg = Hostile()
    app = App("T")
    app.settings("Settings", cfg, key="s")
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "[/x] label ([bold]x[/bold])" in nav(app)
        await open_item(pilot, 1)
        assert "matrix[i][j]" in screen_text(app)
        await fill_and_submit(pilot, value="a|b")
        assert cfg.label == "a|b"


# --------------------------------------------------------------------------- P3.2: pydantic

async def test_pydantic_models_work_with_nesting_validation_and_secret_str():
    pydantic = pytest.importorskip("pydantic")

    class Inner(pydantic.BaseModel):
        retries: int = 3

    class Model(pydantic.BaseModel):
        model_config = pydantic.ConfigDict(validate_assignment=True)
        name: str = pydantic.Field("srv", description="Server name")
        port: Annotated[int, Param(min=1, max=65535)] = 80
        key: pydantic.SecretStr = pydantic.SecretStr("")
        inner: Inner = pydantic.Field(default_factory=Inner)

    model = Model()
    saves: list[str] = []
    app = App("T")
    app.settings("Cfg", model, key="c", save=lambda: saves.append(model.name))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "c")
        text = nav(app)
        assert "Name (srv)" in text and "Port (80)" in text and "Key (••••)" in text and "Inner" in text
        await open_item(pilot, 1)
        assert "Server name" in screen_text(app)
        await fill_and_submit(pilot, value="alpha")
        assert model.name == "alpha" and saves == ["alpha"]
        await open_item(pilot, 2)
        field(app, "value").value = "70000"
        await pilot.click("#form-submit")
        await pilot.pause(0.3)
        assert on_form(app) and error_of(app, "value") == "Must be at most 65535"
        await fill_and_submit(pilot, value="8080")
        assert model.port == 8080
        await open_item(pilot, 3)
        await fill_and_submit(pilot, value="sekret-pydantic-1")
        assert model.key.get_secret_value() == "sekret-pydantic-1"
        assert "sekret-pydantic-1" in app.secret_values()
        await open_item(pilot, 4)
        await edit(pilot, 1, value="7")
        assert model.inner.retries == 7
        await pilot.press("escape")
        await pilot.pause()
        await open_item(pilot, 5)
        mark = app.jobs.mark()
        await pilot.press("y")
        await app.jobs.wait_idle(since=mark)
    assert (model.name, model.port, model.inner.retries) == ("srv", 80, 3) and model.key.get_secret_value() == ""
