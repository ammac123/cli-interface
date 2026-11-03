"""Phase 3 end to end: forms, confirm, settings and secrets driven the way a consumer and a user would."""
import argparse
import dataclasses
import enum
import logging
import subprocess
import sys
import threading
from pathlib import Path
from typing import Annotated, Any

import pytest

from cli_interface import App, Context, Param, Secret
from cli_interface.jobs import JobSpec
from cli_interface.params import ParamSpec
from cli_interface.widgets import ConfirmScreen, FormScreen
from helpers import HOSTILE, SIZE, make_gate, panel_text, type_command, wait_for, widget_text

PASSWORD = "hunter2-Zq81"
TOKEN = "tok-4d1c9e77"


# --------------------------------------------------------------------------- reading and driving the UI

def screen_text(app: App) -> str:
    return "\n".join(strip.text.rstrip() for strip in app.screen._compositor.render_strips())


def nav(app: App) -> str:
    return widget_text(app.query_one("#nav-bar"))


def visible(app: App) -> str:
    return "\n".join([panel_text(app), screen_text(app), nav(app)])


def on_form(app: App) -> bool:
    return isinstance(app.screen, FormScreen)


def on_confirm(app: App) -> bool:
    return isinstance(app.screen, ConfirmScreen)


def on_base(app: App) -> bool:
    return not isinstance(app.screen, FormScreen | ConfirmScreen)


async def type_in(pilot: Any, text: str) -> None:
    """Replace the content of the focused input, key by key."""
    await pilot.press("end", "ctrl+u", *text)


async def submit_with_enter(pilot: Any, jobs: int = 1) -> None:
    app = pilot.app
    mark = app.jobs.mark()
    await pilot.press("enter")
    await app.jobs.wait_idle(since=mark, jobs=jobs)
    await pilot.pause()


async def answer(pilot: Any, key: str) -> None:
    await pilot.press(key)
    await pilot.pause()


async def run_confirmed(pilot: Any, key: str = "y") -> None:
    app = pilot.app
    assert on_confirm(app)
    mark = app.jobs.mark()
    await pilot.press(key)
    await app.jobs.wait_idle(since=mark)
    await pilot.pause()


# --------------------------------------------------------------------------- a: the consumer-sketch flow

def scrape_app(logger: logging.Logger | None = None) -> tuple[App, dict[str, Any]]:
    app = App("Scraper", capture_loggers=[logger.name] if logger else ())
    app.state.sites = ["alpha", "beta", "gamma"]
    seen: dict[str, Any] = {}

    @app.command("Scrape", key="s")
    def scrape(
        ctx: Context,
        site: Annotated[str, Param(choices=lambda c: c.state.sites, label="Site")],
        limit: int | None = None,
        headless: bool = True,
        password: Annotated[str, Secret()] = "",
    ) -> str:
        seen.update(site=site, limit=limit, headless=headless, password=password)
        return f"scraped {site}"

    @app.command("Probe", key="p")
    def probe(ctx: Context) -> None:
        ctx.log(f"using {seen['password']}")
        print(f"print {seen['password']}")
        if logger is not None:
            logger.info("record %s", seen["password"])

    return app, seen


async def test_the_consumer_sketch_flow_is_driven_by_key_presses_and_the_secret_stays_hidden(unique_logger):
    logger = unique_logger("sketch", logging.INFO)
    app, seen = scrape_app(logger)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert on_form(app) and app.screen.focused is app.screen.query_one("#form-field-site")
        await pilot.press("enter", "down", "enter")  # open the select, move to the second option, pick it
        await pilot.press("tab")
        await type_in(pilot, "25")
        await pilot.press("tab", "space")  # headless: True -> False
        await pilot.press("tab")
        await pilot.press(*PASSWORD)
        assert PASSWORD not in screen_text(app) and "•" in screen_text(app)
        await submit_with_enter(pilot)
        assert on_base(app)
        assert seen == {"site": "beta", "limit": 25, "headless": False, "password": PASSWORD}
        assert "Executed: Scrape → scraped beta" in panel_text(app)
        assert PASSWORD not in visible(app)

        await type_command(pilot, "p")
        await app.jobs.wait_idle()
        await pilot.pause()
        logger.warning("late %s", PASSWORD)
        await pilot.pause()
        text = visible(app)
        assert "using ***" in text and "print ***" in text and "record ***" in text and "late ***" in text
        assert PASSWORD not in text


async def test_the_sketch_form_defaults_empty_optional_and_choices_are_resolved_when_opened():
    app, seen = scrape_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await pilot.press("tab")
        assert app.screen.focused.value == "" and app.screen.query_one("#form-field-headless").value is True
        await submit_with_enter(pilot)
        assert seen["site"] == "alpha" and seen["limit"] is None and seen["headless"] is True
        app.state.sites = ["delta"]
        await type_command(pilot, "s")
        await pilot.press("tab")
        await submit_with_enter(pilot)
        assert seen["site"] == "delta"


async def test_an_invalid_value_is_reported_inline_focus_moves_there_and_the_fixed_form_runs():
    app, seen = scrape_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await pilot.press("tab")
        await type_in(pilot, "lots")
        await pilot.press("enter")
        await pilot.pause()
        assert on_form(app) and seen == {}
        assert screen_text(app).count("Enter a whole number") == 1
        assert app.screen.focused is app.screen.query_one("#form-field-limit")
        await type_in(pilot, "3")
        await submit_with_enter(pilot)
        assert seen["limit"] == 3 and on_base(app)


# --------------------------------------------------------------------------- b: a settings flow

class Level(enum.Enum):
    LOW = 1
    HIGH = 2


@dataclasses.dataclass
class Database:
    host: str = "localhost"
    port: int = 5432


@dataclasses.dataclass
class Config:
    name: str = "app"
    level: Level = Level.LOW
    token: str = ""
    db: Database = dataclasses.field(default_factory=Database)


class Disk:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.writes: list[tuple[str, int]] = []
        self.fail = False

    def __call__(self, ctx: Context) -> None:
        if self.fail:
            raise OSError(f"cannot write {self.cfg.token or 'config'}")
        self.writes.append((self.cfg.name, self.cfg.db.port))


def settings_app(cfg: Config, disk: Disk, **kw: Any) -> App:
    app = App("T")
    app.settings("Settings", cfg, key="s", save=disk, secret=["token"], **kw)
    return app


async def test_a_settings_session_edits_nested_values_live_saves_each_change_and_resets_on_confirmation():
    cfg = Config()
    disk = Disk(cfg)
    app = settings_app(cfg, disk)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("enter")  # the first root item: the Settings group
        await pilot.pause()
        for label in ("Name (app)", "Level (LOW)", "Token (••••)", "Db", "Reset to defaults"):
            assert label in nav(app), label

        await type_command(pilot, "1")
        assert on_form(app) and app.screen.focused.value == "app"
        await type_in(pilot, "prod")
        await submit_with_enter(pilot)
        assert cfg.name == "prod" and "Name (prod)" in nav(app) and disk.writes == [("prod", 5432)]

        await type_command(pilot, "4")  # Db
        assert "Host (localhost)" in nav(app) and "Port (5432)" in nav(app)
        await type_command(pilot, "2")
        await type_in(pilot, "6543")
        await submit_with_enter(pilot)
        assert cfg.db.port == 6543 and "Port (6543)" in nav(app) and len(disk.writes) == 2
        await type_command(pilot, "2")
        await type_in(pilot, "6543")  # unchanged: nothing is saved
        await submit_with_enter(pilot)
        assert len(disk.writes) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert "Name (prod)" in nav(app)

        await type_command(pilot, "5")  # Reset to defaults
        assert on_confirm(app) and "Reset all Settings settings to their defaults?" in screen_text(app)
        await answer(pilot, "n")
        assert cfg.name == "prod" and len(disk.writes) == 2
        await type_command(pilot, "5")
        await run_confirmed(pilot)
        assert (cfg.name, cfg.db.port) == ("app", 5432) and len(disk.writes) == 3
        assert "Name (app)" in nav(app)


async def test_a_failing_save_rolls_the_value_back_and_a_later_save_still_works():
    cfg = Config()
    disk = Disk(cfg)
    app = settings_app(cfg, disk)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        disk.fail = True
        await type_command(pilot, "1")
        await type_in(pilot, "doomed")
        await submit_with_enter(pilot)
        assert cfg.name == "app" and "Name (app)" in nav(app)
        assert "Error in Set Name" in panel_text(app) and "cannot write config" in panel_text(app)
        disk.fail = False
        await type_command(pilot, "1")
        await type_in(pilot, "kept")
        await submit_with_enter(pilot)
        assert cfg.name == "kept" and disk.writes == [("kept", 5432)]


async def test_a_secret_setting_is_masked_and_redacted_from_a_later_save_error_and_a_command_log(unique_logger):
    logger = unique_logger("cfg", logging.INFO)
    cfg = Config()
    disk = Disk(cfg)
    app = App("T", capture_loggers=[logger.name])
    app.settings("Settings", cfg, key="s", save=disk, secret=["token"])

    @app.command("Use", key="u")
    def use(ctx: Context) -> None:
        logger.info("using %s", cfg.token)
        ctx.log(f"also {cfg.token}")

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await type_command(pilot, "3")
        assert app.screen.focused.password is True and app.screen.focused.value == ""
        await pilot.press(*TOKEN)
        assert TOKEN not in screen_text(app)
        await submit_with_enter(pilot)
        assert cfg.token == TOKEN and "Token (••••)" in nav(app) and TOKEN not in visible(app)

        disk.fail = True
        await type_command(pilot, "1")
        await type_in(pilot, "other")
        await submit_with_enter(pilot)
        assert "cannot write ***" in panel_text(app) and TOKEN not in visible(app)
        await pilot.press("escape")
        await pilot.pause()
        await type_command(pilot, "u")
        await app.jobs.wait_idle()
        await pilot.pause()
        assert "using ***" in panel_text(app) and "also ***" in panel_text(app) and TOKEN not in visible(app)


async def test_an_empty_secret_submit_keeps_the_value():
    cfg = Config(token=TOKEN)
    disk = Disk(cfg)
    app = settings_app(cfg, disk)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await type_command(pilot, "3")
        await submit_with_enter(pilot)
        assert cfg.token == TOKEN and disk.writes == []


# --------------------------------------------------------------------------- c: confirm

def wipe_app(confirm: bool | str = "Delete everything?") -> tuple[App, list[Any]]:
    app = App("T")
    ran: list[Any] = []
    app.add_command("Wipe", lambda: ran.append("wiped"), key="w", confirm=confirm)

    @app.command("Purge", key="g", confirm="Purge for good?")
    def purge(days: int, reason: Annotated[str, Param(label="Reason")] = "") -> None:
        ran.append((days, reason))

    return app, ran


@pytest.mark.parametrize("keys", [("enter",), ("escape",), ("n",)])
async def test_every_way_of_declining_a_destructive_action_runs_nothing(keys):
    app, ran = wipe_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        assert on_confirm(app) and "Delete everything?" in screen_text(app)
        before = panel_text(app)
        await pilot.press(*keys)
        await pilot.pause()
        assert on_base(app) and ran == [] and not app.jobs.busy and panel_text(app) == before
        await type_command(pilot, "w")
        await run_confirmed(pilot)
    assert ran == ["wiped"]


async def test_yes_button_by_keyboard_runs_the_action_once():
    app, ran = wipe_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        await pilot.press("shift+tab")  # from Cancel back to Yes
        assert app.screen.focused is app.screen.query_one("#confirm-yes")
        mark = app.jobs.mark()
        await pilot.press("enter")
        await app.jobs.wait_idle(since=mark)
    assert ran == ["wiped"]


async def test_form_then_confirm_ordering_and_cancelling_at_each_stage_runs_nothing():
    app, ran = wipe_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "g")
        assert on_form(app) and not on_confirm(app)
        await pilot.press("escape")  # stage 1: cancel the form
        await pilot.pause()
        assert on_base(app) and ran == [] and not app.jobs.busy

        await type_command(pilot, "g")
        await type_in(pilot, "30")
        await pilot.press("enter")
        await pilot.pause()
        assert on_confirm(app) and ran == [], "the confirm comes after a valid form and nothing runs yet"
        await answer(pilot, "n")  # stage 2: cancel the confirm
        assert on_base(app) and ran == [] and "Executed" not in panel_text(app)

        await type_command(pilot, "g")  # the form starts fresh
        assert app.screen.focused.value == ""
        await pilot.press("enter")
        await pilot.pause()
        assert on_form(app) and "Required" in screen_text(app), "an invalid form never reaches the confirm"
        await type_in(pilot, "7")
        await pilot.press("enter")
        await pilot.pause()
        await run_confirmed(pilot)
    assert ran == [(7, "")]


async def test_a_job_that_starts_while_a_form_is_open_makes_the_submit_busy_not_a_crash():
    app, ran = wipe_app()
    gate = make_gate()
    started = threading.Event()

    def slow(ctx: Context) -> None:
        started.set()
        gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "g")
        await type_in(pilot, "3")
        app.jobs.submit(JobSpec(label="Slow", fn=slow, threaded=True))
        await wait_for(started.is_set, what="the slow job")
        await pilot.press("enter")
        await pilot.pause()
        if on_confirm(app):
            await answer(pilot, "y")
        assert app.is_running and ran == [] and "Busy" in panel_text(app)
        gate.set()
        await app.jobs.wait_idle()
        await type_command(pilot, "g")
        await type_in(pilot, "4")
        await pilot.press("enter")
        await pilot.pause()
        await run_confirmed(pilot)
    assert ran == [(4, "")]


# --------------------------------------------------------------------------- d: the hostile-string matrix

@pytest.mark.parametrize("h", HOSTILE)
async def test_hostile_strings_are_literal_in_form_labels_help_defaults_choices_messages_and_results(h):
    app = App("T")
    seen: dict[str, Any] = {}

    def refuse(value: str) -> str:
        if value == h:
            raise ValueError(f"bad {h}")
        return value

    @app.command("Run", key="r", confirm=f"sure {h}?")
    def run(
        name: Annotated[str, Param(label=f"L {h}", help=f"H {h}", validate=refuse)] = h,
        pick: Annotated[str, Param(label="Pick", choices=[(h, f"C {h}"), ("ok", "ok")])] = h,
        many: Annotated[list[str], Param(label="Many", choices=[(h, f"M {h}"), ("ok", "ok")])] = [],  # noqa: B006
    ) -> str:
        seen.update(name=name, pick=pick, many=many)
        return f"got {name} {pick} {many}"

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        text = screen_text(app)
        for expected in (f"L {h}", f"H {h}", f"M {h}"):
            assert expected in text, expected
        assert app.screen.query_one("#form-field-name").value == h
        await pilot.press("enter")  # the hostile default is rejected with a hostile message
        await pilot.pause()
        assert on_form(app) and f"bad {h}" in screen_text(app)
        await type_in(pilot, "fine")
        await pilot.press("tab", "enter")  # open the select: its options are listed
        assert f"C {h}" in screen_text(app)
        await pilot.press("enter", "tab", "space", "tab")  # pick the first option, tick the first choice, reach Run
        await pilot.press("enter")
        await pilot.pause()
        assert on_confirm(app) and f"sure {h}?" in screen_text(app)
        await run_confirmed(pilot)
        assert seen == {"name": "fine", "pick": h, "many": [h]}
        assert f"got fine {h} {[h]}" in panel_text(app)
        assert app.is_running


@pytest.mark.parametrize("h", HOSTILE)
async def test_hostile_strings_are_literal_in_settings_labels_values_help_and_messages(h):
    @dataclasses.dataclass
    class Hostile:
        thing: Annotated[str, Param(label=f"T {h}", help=f"H {h}", validate=lambda v: v)] = h
        tags: Annotated[list[str], Param(label="Tags")] = dataclasses.field(default_factory=lambda: [h, "x"])
        checked: Annotated[int, Param(label="Checked", validate=lambda v: _refuse(v, h))] = 1

    def _refuse(v: int, text: str) -> int:
        raise ValueError(f"never {text}")

    cfg = Hostile()
    app = App("T")
    app.settings("Settings", cfg, key="s", save=None)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        text = nav(app)
        assert f"T {h} ({h})" in text and f"Tags ({h}, x)" in text
        await type_command(pilot, "1")
        assert f"H {h}" in screen_text(app) and app.screen.query_one("#form-field-value").value == h
        await type_in(pilot, f"a{h}b")
        await submit_with_enter(pilot)
        assert cfg.thing == f"a{h}b" and f"T {h} (a{h}b)" in nav(app)
        await type_command(pilot, "3")
        await pilot.press("enter")
        await pilot.pause()
        assert on_form(app) and f"never {h}" in screen_text(app)
        assert app.is_running


# --------------------------------------------------------------------------- e: ids, names and failing constructors

async def test_non_ascii_parameter_names_compose_submit_and_run():
    app = App("T")
    seen: list[Any] = []

    @app.command("Run", key="r")
    def run(größe: int = 1, 名前: str = "x", ß: bool = False) -> None:
        seen.append((größe, 名前, ß))

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        await type_in(pilot, "7")
        await pilot.press("tab")
        await type_in(pilot, "z")
        await pilot.press("tab", "space", "tab")  # the switch, then the Run button
        await submit_with_enter(pilot)
    assert seen == [(7, "z", True)]


async def test_colliding_names_each_keep_their_own_value_and_error():
    parser = argparse.ArgumentParser()
    parser.add_argument("--one", dest="a.b", type=int, default=1)
    parser.add_argument("--two", dest="a_b", default="2")
    parser.add_argument("--three", dest="a b", default="3")
    app = App("T")
    seen: list[argparse.Namespace] = []
    app.add_command("Run", lambda ns: seen.append(ns), key="r", params=parser)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        await type_in(pilot, "many")
        await pilot.press("enter")
        await pilot.pause()
        assert on_form(app) and screen_text(app).count("Enter a whole number") == 1
        assert app.screen.focused is app.screen._inputs["a.b"]
        await type_in(pilot, "5")
        await pilot.press("tab")
        await type_in(pilot, "two")
        await pilot.press("tab")
        await type_in(pilot, "three")
        await submit_with_enter(pilot)
    assert vars(seen[0]) == {"a.b": 5, "a_b": "two", "a b": "three"}


async def test_non_ascii_settings_fields_edit_and_show_live():
    @dataclasses.dataclass
    class Inner:
        名前: str = "x"

    @dataclasses.dataclass
    class Config:
        größe: int = 3
        inner: Inner = dataclasses.field(default_factory=Inner)

    cfg = Config()
    app = App("T")
    app.settings("Settings", cfg, key="s", save=None)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        assert "(3)" in nav(app)
        await type_command(pilot, "1")
        await type_in(pilot, "8")
        await submit_with_enter(pilot)
        assert cfg.größe == 8 and "(8)" in nav(app)
        await type_command(pilot, "2")
        await type_command(pilot, "1")
        await type_in(pilot, "y")
        await submit_with_enter(pilot)
        assert cfg.inner.名前 == "y"


@dataclasses.dataclass
class Window:
    lo: int
    hi: int
    pin: Annotated[str, Secret()] = ""

    def __post_init__(self) -> None:
        if self.lo > self.hi:
            raise ValueError(f"lo {self.lo} is above hi {self.hi} for pin {self.pin}")


@pytest.mark.parametrize("confirm", [False, "Go?"])
async def test_a_params_dataclass_whose_post_init_raises_is_an_error_line_and_the_next_try_runs(confirm):
    app = App("T")
    seen: list[Window] = []

    @app.command("Win", key="w", params=Window, confirm=confirm)
    def win(w: Window) -> None:
        seen.append(w)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        await type_in(pilot, "9")
        await pilot.press("tab")
        await type_in(pilot, "2")
        await pilot.press("tab")
        await pilot.press(*"4455")
        await pilot.press("enter")
        await pilot.pause()
        if confirm:
            assert on_confirm(app)
            await answer(pilot, "y")
        await pilot.pause()
        assert app.is_running and on_base(app) and not app.jobs.busy and seen == []
        assert "Cannot run Win: lo 9 is above hi 2 for pin ***" in panel_text(app)
        assert "4455" not in visible(app)

        await type_command(pilot, "w")
        await type_in(pilot, "1")
        await pilot.press("tab")
        await type_in(pilot, "2")
        await pilot.press("enter")
        await pilot.pause()
        if confirm:
            await run_confirmed(pilot)
        else:
            await app.jobs.wait_idle()
    assert seen == [Window(1, 2)]


async def test_a_validate_callable_raising_a_non_value_error_does_not_take_the_app_down():
    app = App("T")
    seen: list[int] = []

    @app.command("Run", key="r")
    def run(n: Annotated[int, Param(validate=lambda v: 1 // 0)] = 1) -> None:
        seen.append(n)

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        await pilot.press("enter")
        await pilot.pause()
        assert app.is_running and seen == []


async def test_explicit_specs_with_awkward_names_work_through_the_form():
    app = App("T")
    seen: list[dict[str, Any]] = []
    specs = [
        ParamSpec(name="a.b", kind="int", label="Dotted", default=1),
        ParamSpec(name="a_b", kind="text", label="Under", default="u"),
    ]
    app.add_command("Run", lambda **kw: seen.append(kw), key="r", params=specs)
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        await pilot.press("enter")
        await pilot.pause()
        await app.jobs.wait_idle()
    assert seen == [{"a.b": 1, "a_b": "u"}]


async def test_a_choice_field_shows_its_default_option_when_the_form_opens():
    app = App("T")

    @app.command("Run", key="r")
    def run(mode: Annotated[str, Param(choices=[("fast", "Fast one"), ("slow", "Slow one")])] = "slow") -> None: ...

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "r")
        await pilot.pause(0.2)
        assert app.screen.query_one("#form-field-mode").value == "slow"
        assert "Slow one" in screen_text(app)


async def test_the_settings_edit_form_of_a_choice_field_shows_the_current_value():
    cfg = Config(level=Level.HIGH)
    app = settings_app(cfg, Disk(cfg))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        await type_command(pilot, "2")
        await pilot.pause(0.2)
        assert app.screen.query_one("#form-field-value").value is Level.HIGH
        assert "HIGH" in screen_text(app)


# --------------------------------------------------------------------------- real runs in a subprocess

_SCRIPT = '''
import sys
from pathlib import Path
from typing import Annotated

sys.path.insert(0, sys.argv[1])
from cli_interface import App, Context, Secret
from helpers import panel_text

password, mode, out = sys.argv[2], sys.argv[3], Path(sys.argv[4])
app = App("Real", capture_loggers=["real-run"])


@app.command("Login", key="l", confirm="Really log in?" if mode == "quit-confirm" else False)
def login(ctx: Context, user: str = "ann", token: Annotated[str, Secret()] = "") -> str:
    import logging

    ctx.log(f"user {user} token {token}")
    print(f"printed {token}")
    logging.getLogger("real-run").warning("record %s", token)
    return f"returned {token}"


def screen() -> str:
    return "\\n".join(strip.text.rstrip() for strip in app.screen._compositor.render_strips())


async def auto(pilot):
    await pilot.pause()
    app.query_one("#command-input").value = "l"
    await pilot.press("enter")
    await pilot.pause()
    await pilot.press("tab", *password)
    out.write_text("FORM\\n" + screen())
    if mode == "quit-form":
        await app.run_action("quit")
        return
    await pilot.press("enter")
    await pilot.pause()
    if mode == "quit-confirm":
        await app.run_action("quit")
        return
    mark = app.jobs.mark()
    await app.jobs.wait_idle(since=mark, timeout=10)
    await pilot.pause()
    out.write_text("PANEL\\n" + panel_text(app))
    app.exit()


app.run(headless=True, auto_pilot=auto, size=(120, 30))
print("done", file=sys.stderr)
'''


def real_run(tmp_path: Any, mode: str) -> tuple[Any, str]:
    script = tmp_path / "real_app.py"
    script.write_text(_SCRIPT)
    out = tmp_path / "out.txt"
    tests_dir = str(Path(__file__).parent)
    proc = subprocess.run(
        [sys.executable, str(script), tests_dir, PASSWORD, mode, str(out)],
        capture_output=True, text=True, timeout=30, cwd=str(tmp_path),
    )
    return proc, out.read_text() if out.exists() else ""


@pytest.mark.parametrize("mode", ["quit-form", "quit-confirm"])
def test_quitting_while_a_form_or_confirm_is_open_exits_cleanly_without_the_secret(tmp_path, mode):
    proc, out = real_run(tmp_path, mode)
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr and "done" in proc.stderr
    assert PASSWORD not in proc.stdout + proc.stderr + out
    assert out.startswith("FORM") and "Login" in out and "•" in out


def test_a_typed_secret_never_reaches_the_process_output_or_the_panel(tmp_path):
    proc, out = real_run(tmp_path, "submit")
    assert proc.returncode == 0, proc.stderr
    assert "Traceback" not in proc.stdout + proc.stderr
    assert PASSWORD not in proc.stdout + proc.stderr
    assert out.startswith("PANEL") and PASSWORD not in out
    for expected in ("user ann token ***", "printed ***", "record ***", "returned ***"):
        assert expected in out, expected
