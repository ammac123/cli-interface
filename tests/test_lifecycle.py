"""CF-1 timer lifecycle, CF-8 / CF-10 run() and max_lines, CF-17 fatal tracebacks."""
from __future__ import annotations

import asyncio
import io
import uuid
from typing import Any

import pytest
from rich.console import Console
from textual.app import App
from textual.timer import Timer
from textual.widgets import RichLog

from cli_interface import CLIApp, ShortcutConflictWarning, run
from cli_interface.widgets import Dashboard
from helpers import SIZE, leaf, menu

# --------------------------------------------------------------------------- CF-1: timers


class SpyTimerStop:
    """Records every Timer.stop() call. Textual's own shutdown stops timers without calling it."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.stopped: list[Timer] = []
        original = Timer.stop

        def spy(timer: Timer) -> None:
            self.stopped.append(timer)
            original(timer)

        monkeypatch.setattr(Timer, "stop", spy)


async def test_on_unmount_stops_all_three_timers_and_forgets_them(monkeypatch):
    spy = SpyTimerStop(monkeypatch)
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.start_spinner()  # no label: this starts the frame timer and the phrase-rotation timer
        handles = (app._spinner_handle, app._spinner_phrase_handle, app._phrase_handle)
        assert all(isinstance(h, Timer) for h in handles) and len({id(h) for h in handles}) == 3
        spy.stopped.clear()
    assert all(any(h is s for s in spy.stopped) for h in handles), "each timer was stopped by the app"
    assert app._spinner_handle is None and app._spinner_phrase_handle is None and app._phrase_handle is None


async def test_stop_spinner_stops_both_spinner_timers_and_leaves_the_phrase_timer(monkeypatch):
    spy = SpyTimerStop(monkeypatch)
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.start_spinner()
        frame, phrase, idle = app._spinner_handle, app._spinner_phrase_handle, app._phrase_handle
        spy.stopped.clear()
        app.stop_spinner()
        assert any(t is frame for t in spy.stopped) and any(t is phrase for t in spy.stopped)
        assert not any(t is idle for t in spy.stopped)
        assert app._spinner_handle is None and app._spinner_phrase_handle is None
        assert app._phrase_handle is idle and idle is not None


async def test_starting_the_spinner_twice_keeps_one_timer_of_each_kind():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.start_spinner()
        first = (app._spinner_handle, app._spinner_phrase_handle)
        app.start_spinner()
        assert (app._spinner_handle, app._spinner_phrase_handle) == first


async def test_a_second_on_mount_does_not_start_a_second_phrase_timer(monkeypatch):
    intervals: list[float] = []
    original = CLIApp.set_interval

    def spy(self, interval, *args, **kwargs):
        intervals.append(interval)
        return original(self, interval, *args, **kwargs)

    monkeypatch.setattr(CLIApp, "set_interval", spy)

    class Twice(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()  # Textual also calls CLIApp.on_mount: the base handler runs twice

    app = Twice(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        handle = app._phrase_handle
        assert handle is not None and intervals.count(45) == 1


async def test_late_ticks_after_the_app_has_exited_are_harmless():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.start_spinner()
    for tick in (app._tick_spinner, app._cycle_phrase, app._cycle_spinner_phrase):
        tick()
    app.start_spinner()
    app.stop_spinner()


async def test_the_spinner_methods_do_nothing_before_the_app_starts():
    app = CLIApp(menu(leaf("A", "a")))
    app.start_spinner()
    app.stop_spinner()
    assert app._spinner_handle is None and app._spinner_phrase_handle is None
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.query_one("#dashboard", Dashboard).spinning is False


async def test_a_tick_advances_the_spinner_frame_while_the_app_is_running():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        app.start_spinner()
        frame = dash.spinner_frame
        app._tick_spinner()
        assert dash.spinner_frame == frame + 1
        app.stop_spinner()
        await pilot.pause()


# --------------------------------------------------------------------------- CF-8: run() forwards its options

@pytest.fixture
def headless_run(monkeypatch):
    """Replace CLIApp.run by a headless run_test that records what the app was built with."""
    seen: dict[str, Any] = {"runs": 0, "return_code": 0}

    def fake_run(self: CLIApp, *args: Any, **kwargs: Any) -> None:
        async def probe() -> None:
            async with self.run_test(size=SIZE) as pilot:
                await pilot.pause()
                seen["max_lines"] = self.query_one("#display-panel", RichLog).max_lines
                seen["crumbs"] = self.query_one("#dashboard", Dashboard).crumbs
                self.exit(return_code=seen["return_code"])

        seen["runs"] += 1
        seen["app"] = self
        asyncio.run(probe())

    monkeypatch.setattr(CLIApp, "run", fake_run)
    return seen


def test_run_builds_the_app_runs_it_and_returns_zero_by_default(headless_run):
    assert run(menu(leaf("A", "a"))) == 0
    assert headless_run["runs"] == 1 and isinstance(headless_run["app"], CLIApp)
    assert headless_run["max_lines"] == 5000


def test_run_returns_the_apps_return_code(headless_run):
    headless_run["return_code"] = 7
    assert run(menu(leaf("A", "a"))) == 7


def test_run_forwards_max_lines(headless_run):
    run(menu(leaf("A", "a")), max_lines=123)
    assert headless_run["max_lines"] == 123


def test_run_forwards_an_unbounded_max_lines(headless_run):
    run(menu(leaf("A", "a")), max_lines=None)
    assert headless_run["max_lines"] is None


def test_run_forwards_strict_shortcuts_so_a_conflict_stops_it_before_the_app_runs(headless_run):
    conflicted = menu(leaf("Quit it", "q"))
    with pytest.raises(ValueError, match="reserved command"):
        run(conflicted, strict_shortcuts=True)
    assert headless_run["runs"] == 0


def test_run_without_strict_shortcuts_warns_instead(headless_run):
    with pytest.warns(ShortcutConflictWarning, match="reserved command"):
        run(menu(leaf("Quit it", "q")))
    assert headless_run["runs"] == 1


def test_run_passes_its_menu_through_to_the_app(headless_run):
    root = menu(leaf("A", "a"), label="Custom root")
    run(root)
    assert headless_run["crumbs"] == ("Custom root",)


# --------------------------------------------------------------------------- CF-10: max_lines

@pytest.mark.parametrize("bad", [0, -1, -5000, True, False, "5", "5000", 1.5, 5.0, [], b"1"])
def test_max_lines_must_be_none_or_a_positive_int(bad):
    with pytest.raises(ValueError, match="max_lines"):
        CLIApp(menu(leaf("A", "a")), max_lines=bad)


@pytest.mark.parametrize("good", [1, 2, 5000, 10**9, None])
def test_valid_max_lines_values_are_accepted(good):
    CLIApp(menu(leaf("A", "a")), max_lines=good)


def test_run_rejects_a_bad_max_lines_before_running(headless_run):
    with pytest.raises(ValueError, match="max_lines"):
        run(menu(leaf("A", "a")), max_lines=0)
    assert headless_run["runs"] == 0


async def test_a_bounded_panel_keeps_only_the_newest_lines():
    app = CLIApp(menu(leaf("A", "a")), max_lines=10)
    async with app.run_test(size=SIZE) as pilot:
        for n in range(30):
            app.panel.log(f"row {n}")
        await pilot.pause()
        lines = [s.text.rstrip() for s in app.query_one("#display-panel", RichLog).lines]
        assert len(lines) == 10 and "row 29" in lines[-1] and "row 20" in lines[0]


async def test_the_default_panel_is_bounded_at_5000_lines():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        for n in range(5100):
            app.panel.log(f"row {n}")
        await pilot.pause()
        assert len(app.query_one("#display-panel", RichLog).lines) == 5000


async def test_max_lines_none_keeps_every_line():
    app = CLIApp(menu(leaf("A", "a")), max_lines=None)
    async with app.run_test(size=SIZE) as pilot:
        for n in range(5100):
            app.panel.log(f"row {n}")
        await pilot.pause()
        log = app.query_one("#display-panel", RichLog)
        assert len(log.lines) == 5100 and "row 0" in log.lines[0].text


# --------------------------------------------------------------------------- CF-17: no locals in the fatal traceback

def make_secret() -> str:
    return "sk-" + uuid.uuid4().hex  # computed at run time: a literal would also show in the traceback's source lines


def fail_holding(secret: str) -> None:
    api_key = secret  # a local that Textual's own handler would print  # noqa: F841
    raise RuntimeError("boom")


def rendered_exit_text(app: App) -> str:
    console = Console(file=io.StringIO(), width=240, force_terminal=False, color_system=None)
    for renderable in app._exit_renderables:
        console.print(renderable)
    return console.file.getvalue()  # type: ignore[attr-defined]


def fatal_error_text(app: App, handler) -> tuple[str, str]:
    secret = make_secret()
    try:
        fail_holding(secret)
    except RuntimeError:
        handler(app)
    return secret, rendered_exit_text(app)


def test_the_fatal_traceback_does_not_print_local_variables():
    app = CLIApp(menu(leaf("A", "a")))
    secret, text = fatal_error_text(app, lambda a: a._fatal_error())
    assert "RuntimeError" in text and "boom" in text, "the traceback itself is still shown"
    assert "fail_holding" in text
    assert secret not in text


def test_control_textuals_own_handler_prints_locals():
    app = CLIApp(menu(leaf("A", "a")))
    secret, text = fatal_error_text(app, lambda a: App._fatal_error(a))
    if secret not in text:
        pytest.skip("this Textual version no longer prints locals, so there is nothing to suppress")


def test_a_crash_in_a_real_run_ends_the_app_and_prints_no_locals(capsys):
    secrets: list[str] = []

    class Crash(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()
            secrets.append(make_secret())
            self.set_timer(0.05, lambda: fail_holding(secrets[0]))

    app = Crash(menu(leaf("A", "a")))
    app.run(headless=True, size=(120, 30))
    assert app.return_code == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "boom" in err and "fail_holding" in err
    assert secrets[0] not in err
