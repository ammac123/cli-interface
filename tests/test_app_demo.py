"""WP-8 / D19: examples/app_demo.py, the App + Context showcase, walked through end to end on a headless app."""
from __future__ import annotations

import importlib
import sys

import pytest
from textual.widgets import Input

from helpers import SIZE, crumbs, panel_lines, panel_text, press_and_wait, spin_until, type_command


@pytest.fixture
def demo():
    """A fresh import of the demo: its module-level App can only be run once (Textual)."""
    sys.modules.pop("examples.app_demo", None)
    module = importlib.import_module("examples.app_demo")
    yield module
    sys.modules.pop("examples.app_demo", None)


def spinner_label(app) -> str:
    return app.screen_stack[0].query_one("#dashboard").spinner_label


def test_the_demo_imports_cleanly_with_its_groups_hooks_and_commands(demo):
    import warnings

    app = demo.app
    assert type(app).__name__ == "App" and app.title == "Demo"
    root = app._state.root
    assert [c.label for c in root.children] == ["Run", "Tools"] and [c.shortcut for c in root.children] == ["r", "t"]
    assert [c.label for c in root.children[0].children] == ["Count", "Crunch"]
    assert [c.label for c in root.children[1].children] == ["Greet", "Table"]
    count = root.children[0].children[0]
    assert count.cancellable is True and root.children[0].children[1].cancellable is False
    assert len(app.jobs._hooks["startup"]) == len(app.jobs._hooks["shutdown"]) == 1
    assert len(app.jobs._hooks["before"]) == len(app.jobs._hooks["after"]) == 1
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        importlib.reload(demo)


async def test_start_observe_progress_stop_rerun_and_quit(demo):
    app = demo.app
    async with app.run_test(size=SIZE) as pilot:
        await settle_startup(pilot)
        assert "Demo ready. Try Run, then type stop while it counts." in panel_text(app)
        await type_command(pilot, "r")
        assert crumbs(app) == ("Demo", "Run")
        for n in (1, 2):
            mark = app.jobs.mark()
            await pilot.press("c", "enter")
            await spin_until(lambda: spinner_label(app).startswith("Counting"), what="the progress label")
            assert "Counting" in spinner_label(app) and "/20" in spinner_label(app)
            await type_command(pilot, "stop")
            await app.jobs.wait_idle(since=mark, jobs=1)
            await pilot.pause()
            lines = panel_lines(app)
            assert lines.count("Cancelled: Count") == n
            assert lines.count(f"Count: cancelled (command {n})") == 1, "after_command saw the outcome"
        assert app.state.runs == 2
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        assert app.return_code == 0


async def test_the_thread_command_prints_reports_status_and_returns_a_dict(demo):
    app = demo.app
    async with app.run_test(size=SIZE) as pilot:
        await settle_startup(pilot)
        await type_command(pilot, "r")
        mark = app.jobs.mark()
        await pilot.press("n", "enter")
        await spin_until(lambda: "step 1 of 10" in panel_text(app), what="the first printed step")
        assert spinner_label(app).startswith("Crunching")
        app.query_one("#command-input", Input).value = "q"
        await pilot.press("enter")  # the quit starts here: nothing may press or pause after it
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=15)
        assert app.return_code == 0 and app.jobs.completed > mark


async def test_the_tools_commands_return_a_string_and_a_table(demo):
    app = demo.app
    async with app.run_test(size=SIZE) as pilot:
        await settle_startup(pilot)
        await type_command(pilot, "t")
        await press_and_wait(pilot, "g", "enter")
        await press_and_wait(pilot, "s", "enter")
        text = panel_text(app)
        assert "Executed: Greet → Hello from the demo" in text
        assert "alpha" in text and "gamma" in text and "size" in text and "Executed: Table" in text
        assert any(ch in text for ch in "┏┌╭"), "the list of dicts is drawn as a table"


async def settle_startup(pilot) -> None:
    await pilot.app.jobs.wait_idle()
    await pilot.pause()
