"""The demo menu (examples/), its scoped worker capture, and examples.main."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import warnings
from pathlib import Path

import pytest
from textual.widgets import Input

from cli_interface import CLIApp, LoggingAttachWarning, MenuItem, attach_logging, find_shortcut_conflicts
from cli_interface.widgets import Dashboard, PromptScreen
from examples.example_menu import build_menu
from cli_interface.menu import item_label
from cli_interface.widgets import NavBar
from helpers import (
    SIZE, build_demo_app, panel_lines, panel_text, read_panel, tui_handlers, type_command, wait_for, widget_text,
)

REPO = Path(__file__).resolve().parent.parent


def flat(text: str) -> str:
    return " ".join(text.split())


def walk(item: MenuItem):
    yield item
    for child in item.children:
        yield from walk(child)


# --------------------------------------------------------------------------- the menu itself

def test_demo_menu_has_no_shortcut_conflicts():
    assert find_shortcut_conflicts(build_menu(CLIApp(MenuItem("Home")))) == []


def test_demo_menu_offers_a_secret_token_prompt_under_settings():
    demo = build_menu(CLIApp(MenuItem("Home")))
    token = next(i for i in walk(demo) if i.label == "Set Token")
    assert (token.shortcut, token.secret, token.prompt) == ("k", True, "Enter API token:")
    settings = next(i for i in demo.children if i.label == "Settings")
    assert token in settings.children
    port = next(i for i in settings.children if i.label == "Set Port")
    assert port.secret is False


def test_building_the_demo_app_emits_no_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_demo_app()


# --------------------------------------------------------------------------- examples.main

IMPORT_PROBE = """
import json, logging, sys
root = logging.getLogger()
before = ([type(h).__name__ for h in root.handlers], root.level)
sys.path.insert(0, {repo!r})
import examples.main as m
after = ([type(h).__name__ for h in root.handlers], root.level)
print(json.dumps({{"before": before, "after": after, "main": m.main.__module__ + "." + m.main.__name__}}))
"""


def test_importing_examples_main_in_a_fresh_interpreter_configures_no_logging():
    out = subprocess.run(
        [sys.executable, "-c", IMPORT_PROBE.format(repo=str(REPO))],
        capture_output=True, text=True, timeout=60, check=True,
    ).stdout
    result = json.loads(out.strip().splitlines()[-1])
    assert result["after"] == result["before"] == [[], logging.WARNING]
    assert result["main"] == "examples.main.main"


def test_executing_examples_main_as_a_module_does_not_start_the_app_or_touch_root(root_logger_guard, monkeypatch):
    import runpy

    monkeypatch.delitem(sys.modules, "examples.main", raising=False)  # an earlier import would make runpy warn
    before = (list(root_logger_guard.handlers), root_logger_guard.level)
    namespace = runpy.run_module("examples.main", run_name="not_main")
    assert callable(namespace["main"])
    assert (list(root_logger_guard.handlers), root_logger_guard.level) == before


# --------------------------------------------------------------------------- demo views and prompts

VIEWS = [
    ("j", "Application Config"), ("t", "Alice Chen"), ("c", "api-01"), ("l", "Recent Events"),
    ("a", "Allowed IP Addresses"), ("p", "Pipeline Definition"), ("m", "System Overview"),
]


@pytest.mark.parametrize("key, expected", VIEWS)
async def test_every_view_output_demo_renders_and_leaves_the_app_alive(key, expected):
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("v", "enter")
        await pilot.press(key, "enter")
        text = await read_panel(pilot)
        assert expected in text, text[-500:]
        assert "Error in" not in text and app.is_running and app.return_code is None


async def test_log_lines_demo_shows_the_literal_bracket_sample():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("v", "enter")
        await pilot.press("l", "enter")
        assert "Loaded config[server][port] = 8080" in await read_panel(pilot)
        assert app.return_code is None


async def test_spinner_demo_starts_the_spinner():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("v", "enter")
        await pilot.press("s", "enter")
        await pilot.pause()
        assert app.query_one("#dashboard", Dashboard).spinning is True
        assert "Background job started" in panel_text(app)
        app.exit()


async def test_set_token_shows_a_masked_input_and_never_echoes_the_value():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await pilot.press("k", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is True
        for ch in "hunter2":
            await pilot.press(ch)
        await pilot.press("enter")
        text = await read_panel(pilot)
        assert "Executed: Set Token" in text and "Executed: Set Token →" not in text
        assert "Token accepted (7 chars)" in text
        assert "hunter2" not in text
        assert app.return_code is None


async def test_set_port_is_unmasked_and_shows_its_result_without_echoing_the_value():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await pilot.press("p", "enter")
        await pilot.pause()
        assert app.screen.query_one("#prompt-input", Input).password is False
        for ch in "8080":
            await pilot.press(ch)
        await pilot.press("enter")
        text = await read_panel(pilot)
        assert "Executed: Set Port → port → 8080" in text and "'8080'" not in text


# --------------------------------------------------------------------------- the worker demo's scoped capture

async def test_worker_demo_captures_exclusively_only_while_it_runs(gated_worker, host_root):
    before = (list(host_root.handlers), host_root.level)
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("w", "enter")
        await wait_for(gated_worker.started.is_set, what="worker to start")
        await pilot.pause()
        assert len(tui_handlers(host_root)) == 1
        assert host_root.sentinel not in host_root.handlers, "exclusive capture removes the host's handlers"
        assert host_root.level == logging.DEBUG
        assert app.query_one("#dashboard", Dashboard).spinning is True
        await wait_for(lambda: "heartbeat OK" in panel_text(app), what="DEBUG record in panel")
        assert "Launching background worker" in flat(panel_text(app))

        gated_worker.release.set()
        await wait_for(lambda: not tui_handlers(host_root), what="capture to be released")
        await wait_for(lambda: not app.query_one("#dashboard", Dashboard).spinning, what="spinner to stop")
        assert (list(host_root.handlers), host_root.level) == before
        text = panel_text(app)
        assert "Worker starting" in text and "Worker finished" in text
        await gated_worker.threads.settle()


async def test_pressing_worker_demo_twice_warns_and_never_stacks_a_second_handler(gated_worker, host_root):
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("w", "enter")
        await wait_for(gated_worker.started.is_set)
        await pilot.press("w", "enter")
        await pilot.pause()
        assert "Worker already running" in panel_text(app)
        assert len(tui_handlers(host_root)) == 1
        assert gated_worker.runs == 1
        gated_worker.release.set()
        await wait_for(lambda: not tui_handlers(host_root))
        await gated_worker.threads.settle()


async def test_worker_demo_can_be_restarted_after_it_finishes(gated_worker, host_root):
    app = build_demo_app()
    gated_worker.release.set()  # runs complete immediately
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("w", "enter")
        await wait_for(lambda: gated_worker.runs == 1 and not tui_handlers(host_root), what="first run to finish")
        await wait_for(lambda: not app.query_one("#dashboard", Dashboard).spinning)
        await pilot.press("w", "enter")
        await wait_for(lambda: gated_worker.runs == 2 and not tui_handlers(host_root), what="second run to finish")
        assert "Worker already running" not in panel_text(app)
        assert panel_text(app).count("Worker finished") >= 1
        await gated_worker.threads.settle()


async def test_closing_the_app_mid_run_is_clean_and_root_is_restored(gated_worker, host_root, handle_errors, thread_errors):
    before = (list(host_root.handlers), host_root.level)
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("w", "enter")
        await wait_for(gated_worker.started.is_set)
        await pilot.pause()
        assert len(tui_handlers(host_root)) == 1
        (worker,) = gated_worker.threads.alive()
        app.exit()
    assert (list(host_root.handlers), host_root.level) == before, "app exit restores the host's logging"
    assert worker.is_alive(), "control: the worker outlives the app"
    gated_worker.release.set()
    # yield to the loop (never time.sleep): the worker's call_from_thread needs it to answer
    await wait_for(lambda: not worker.is_alive(), timeout=10, what="worker thread to finish")
    assert thread_errors == [] and handle_errors == []
    assert (list(host_root.handlers), host_root.level) == before


async def test_worker_demo_against_a_host_attached_root_keeps_the_hosts_capture(gated_worker, host_root):
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        host = attach_logging(app)
        level_before = host_root.level
        with pytest.warns(LoggingAttachWarning, match="ignored"):
            await pilot.press("w", "enter")
            await wait_for(gated_worker.started.is_set)
            await pilot.pause()
        assert "Error in Worker Demo" not in panel_text(app)
        assert len(tui_handlers(host_root)) == 1 and host.active
        assert host_root.sentinel in host_root.handlers and host_root.level == level_before
        gated_worker.release.set()
        await gated_worker.threads.settle()
        assert host.active and host.handler in host_root.handlers
        assert host_root.sentinel in host_root.handlers and host_root.level == level_before
        logging.getLogger("tests.hosted").warning("HOST-STILL-CAPTURES")
        await pilot.pause()
        assert "HOST-STILL-CAPTURES" in panel_text(app)


# --------------------------------------------------------------------------- converted smoke test

async def test_demo_walkthrough_with_the_smoke_test_expectations_updated(fast_worker, host_root):
    app = build_demo_app()
    consumer = logging.getLogger("tests.consumer.walkthrough")
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        entry = app.query_one("#command-input", Input)
        assert dash.crumbs == ("Home",)

        # 1. a lone shortcut key no longer navigates; with Enter it does
        await pilot.press("v")
        await pilot.pause()
        assert dash.crumbs == ("Home",) and entry.value == "v"
        entry.value = ""
        await pilot.press("v", "enter")
        await pilot.pause()
        assert dash.crumbs == ("Home", "View Output")

        # 2. a view renders, escape goes back, arrows + Enter enter Settings
        await pilot.press("j", "enter")
        assert "server" in await read_panel(pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert dash.crumbs == ("Home",)
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert dash.crumbs == ("Home", "Settings")

        # 3. prompt modal and its result
        await pilot.press("p", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        await pilot.press("8", "0", "8", "0", "enter")
        assert "port → 8080" in await read_panel(pilot)

        # 4. typed help
        entry.value = "help"
        await pilot.press("enter")
        assert "Navigate menu items" in await read_panel(pilot)

        # 5. untrusted bracketed output
        for msg in ["array[0] = 1", "path C:\\tmp\\[x]", "closing tag [/oops] here"]:
            app.panel.log(msg, "INFO")
            await pilot.pause()
            assert msg in panel_lines(app)[-1]

        # 6. worker demo: capture is scoped to the run
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("w", "enter")
        await wait_for(lambda: tui_handlers(host_root) or "Worker finished" in panel_text(app), what="worker capture")
        await wait_for(lambda: "Worker finished" in panel_text(app), timeout=15, what="worker to finish")
        await wait_for(lambda: not tui_handlers(host_root), what="capture to be released")
        await fast_worker.settle()

        # 7. so a consumer logger is NOT shown unless it is attached explicitly
        consumer.warning("consumer before attach")
        await pilot.pause()
        assert "consumer before attach" not in panel_text(app)
        attach_logging(app)
        consumer.warning("consumer after attach")
        await pilot.pause()
        assert "consumer after attach" in panel_text(app)

        entry.value = "q"
        await pilot.press("enter")
        await wait_for(lambda: app.return_code is not None)
    assert not tui_handlers(host_root)
    assert app.return_code in (0, None)


# --------------------------------------------------------------------------- CF-11: Settings actions reach the panel

DEMO_LOGGER = "examples.example_menu"


def demo_logger_is_clean() -> bool:
    """Level restored, no TUI handler left, still not propagating (pytest adds its own handlers to such loggers)."""
    lg = logging.getLogger(DEMO_LOGGER)
    return lg.level == logging.NOTSET and not tui_handlers(lg) and lg.propagate is False


async def open_audio(pilot) -> None:
    await type_command(pilot, "s")
    await type_command(pilot, "a")


def count(text: str, needle: str) -> int:
    return flat(text).count(needle)


async def test_a_settings_action_logs_once_before_its_executed_line_and_leaves_no_handler_behind():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await open_audio(pilot)
        await type_command(pilot, "1")
        text = flat(panel_text(app))
        assert text.count("Volume set to 25%") == 1
        assert text.index("Volume set to 25%") < text.index("Executed: Volume Low")
        assert demo_logger_is_clean()
        await type_command(pilot, "3")
        text = flat(panel_text(app))
        assert text.count("Volume set to 100%") == 1 and text.count("Volume set to 25%") == 1
    assert demo_logger_is_clean()


async def test_toggle_debug_logs_each_change_once_and_its_value_follows_in_the_nav_bar():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        nav = app.query_one("#nav-bar", NavBar)
        assert "d Toggle Debug (off)" in widget_text(nav)
        await type_command(pilot, "d")
        assert "d Toggle Debug (on)" in widget_text(nav)
        assert count(panel_text(app), "Debug mode toggled on") == 1
        await type_command(pilot, "d")
        assert "d Toggle Debug (off)" in widget_text(nav)
        assert count(panel_text(app), "Debug mode toggled off") == 1 and count(panel_text(app), "toggled on") == 1


async def test_set_port_updates_the_nav_bar_value_and_an_invalid_port_changes_nothing():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        nav = app.query_one("#nav-bar", NavBar)
        assert "p Set Port (8080)" in widget_text(nav)
        await type_command(pilot, "p")
        await pilot.press("x", "enter")
        await pilot.pause()
        text = flat(panel_text(app))
        assert text.count("Invalid port 'x'") == 1 and "p Set Port (8080)" in widget_text(nav)
        await type_command(pilot, "p")
        await pilot.press("9", "0", "9", "0", "enter")
        await pilot.pause()
        text = flat(panel_text(app))
        assert text.count("Port set to 9090") == 1 and "Executed: Set Port → port → 9090" in text
        assert "p Set Port (9090)" in widget_text(nav)
        assert demo_logger_is_clean()


async def test_reset_all_restores_the_defaults_and_goes_back_to_the_home_menu():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "s")
        await type_command(pilot, "d")
        await type_command(pilot, "p")
        await pilot.press("7", "0", "7", "0", "enter")
        await pilot.pause()
        assert dash.crumbs == ("Home", "Settings")
        await type_command(pilot, "x")
        assert dash.crumbs == ("Home",)
        assert count(panel_text(app), "All settings reset to defaults") == 1
        await type_command(pilot, "s")
        shown = widget_text(app.query_one("#nav-bar", NavBar))
        assert "Toggle Debug (off)" in shown and "Set Port (8080)" in shown


async def test_settings_records_appear_once_even_while_the_worker_demos_exclusive_root_capture_is_active(
    gated_worker, host_root
):
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "w")
        await wait_for(gated_worker.started.is_set, what="worker to start")
        await pilot.pause()
        assert len(tui_handlers(host_root)) == 1
        await open_audio(pilot)
        await type_command(pilot, "2")
        await type_command(pilot, "b")
        await type_command(pilot, "d")
        text = panel_text(app)
        assert count(text, "Volume set to 50%") == 1 and count(text, "Debug mode toggled on") == 1
        assert count(text, "Worker starting") == 1
        assert demo_logger_is_clean()
        gated_worker.release.set()
        await wait_for(lambda: not tui_handlers(host_root), what="capture to be released")
        await gated_worker.threads.settle()
        assert count(panel_text(app), "Worker finished") == 1


# --------------------------------------------------------------------------- the demo dogfoods callable labels and values

def test_the_demo_menu_uses_a_callable_label_and_callable_values():
    demo = build_menu(CLIApp(MenuItem("Home")))
    worker = next(i for i in demo.children if i.shortcut == "w")
    settings = next(i for i in demo.children if i.label == "Settings")
    values = {item_label(i): i.current_value for i in settings.children if i.current_value is not None}
    assert callable(worker.label) and item_label(worker) == "Worker Demo"
    assert callable(values["Toggle Debug"]) and callable(values["Set Port"])


async def test_the_worker_demo_label_shows_running_while_it_runs_but_the_executed_line_does_not(gated_worker, host_root):
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        nav = app.query_one("#nav-bar", NavBar)
        assert "w Worker Demo " in widget_text(nav) and "(running)" not in widget_text(nav)
        await type_command(pilot, "w")
        await wait_for(gated_worker.started.is_set, what="worker to start")
        await pilot.pause()
        assert "w Worker Demo (running)" in widget_text(nav)
        text = flat(panel_text(app))
        assert "Executed: Worker Demo" in text and "Executed: Worker Demo (running)" not in text
        gated_worker.release.set()
        await wait_for(lambda: "(running)" not in widget_text(nav), what="the label to go idle again")
        await gated_worker.threads.settle()
