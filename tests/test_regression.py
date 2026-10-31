"""Back-compat of the public surface, plus the probes converted to the Phase 0 behaviour."""
from __future__ import annotations

import dataclasses
import inspect
import logging

import pytest
from textual.app import App
from textual.widgets import Input

from cli_interface.app import CLIApp, attach_logging, run
from cli_interface.display import DisplayPanel
from cli_interface.log_handler import TUILogHandler
from cli_interface.menu import MenuItem
from cli_interface.widgets import PromptScreen
from helpers import (
    SIZE, Calls, StubApp, leaf, menu, panel_text, quiet_app, read_panel, run_threads, tui_handlers, wait_for,
)


# --------------------------------------------------------------------------- signatures and shapes

def params(fn) -> dict[str, inspect.Parameter]:
    return dict(inspect.signature(fn).parameters)


def test_menu_item_field_order_keeps_positional_construction_working():
    names = [f.name for f in dataclasses.fields(MenuItem)]
    assert names == ["label", "shortcut", "description", "children", "action", "prompt", "current_value", "secret"]
    action = lambda: None  # noqa: E731
    item = MenuItem("a", "b", "c", [], action, "p", 1)
    assert (item.shortcut, item.description, item.children, item.action, item.prompt, item.current_value, item.secret) == (
        "b", "c", [], action, "p", 1, False,
    )
    assert MenuItem("x").secret is False and MenuItem("x", secret=True).secret is True


def test_cliapp_constructor_gained_only_keyword_only_options():
    p = params(CLIApp.__init__)
    assert list(p)[:2] == ["self", "menu"]
    assert p["strict_shortcuts"].kind is inspect.Parameter.KEYWORD_ONLY and p["strict_shortcuts"].default is False
    assert p["max_lines"].kind is inspect.Parameter.KEYWORD_ONLY and p["max_lines"].default == 5000
    assert p["kwargs"].kind is inspect.Parameter.VAR_KEYWORD


def test_attach_logging_signature():
    p = params(attach_logging)
    assert list(p) == ["app", "logger", "exclusive", "level"]
    assert p["logger"].default is None
    assert p["exclusive"].kind is p["level"].kind is inspect.Parameter.KEYWORD_ONLY
    assert p["exclusive"].default is False and p["level"].default is None


@pytest.mark.parametrize(
    "name, expected",
    [
        ("log", ["message", "level", "markup"]),
        ("text", ["content", "style", "markup"]),
        ("rule", ["title"]),
        ("json", ["data", "title"]),
        ("table", ["rows", "headers", "title"]),
        ("csv", ["csv_string", "title"]),
        ("array", ["items", "title"]),
        ("pretty", ["obj", "title"]),
        ("renderable", ["obj"]),
    ],
)
def test_display_panel_method_signatures(name, expected):
    p = params(getattr(DisplayPanel, name))
    assert list(p)[1:] == expected
    if "markup" in p:
        assert p["markup"].kind is inspect.Parameter.KEYWORD_ONLY and p["markup"].default is False
    for other in set(expected) - {"markup"}:
        assert p[other].kind is not inspect.Parameter.KEYWORD_ONLY


def test_prompt_screen_keeps_its_positional_form_and_gains_a_keyword_only_secret():
    p = params(PromptScreen.__init__)
    assert list(p) == ["self", "item_label", "prompt", "secret"]
    assert p["secret"].kind is inspect.Parameter.KEYWORD_ONLY and p["secret"].default is False


def test_push_log_and_panel_surface_is_unchanged():
    assert list(params(CLIApp.push_log))[1:] == ["message", "level"]
    assert params(CLIApp.push_log)["level"].default == "INFO"
    assert isinstance(CLIApp.panel, property)
    assert list(params(run)) == ["menu"] and params(run)["menu"].default is None


def test_removed_names_stay_removed():
    import cli_interface.theme as theme

    with pytest.raises(ImportError):
        from cli_interface.theme import _MAX_LOG_LINES  # noqa: F401  (a removed name)
    assert not hasattr(theme, "_MAX_LOG_LINES")


def test_tui_log_handler_is_still_constructible_from_just_an_app():
    handler = TUILogHandler(StubApp())  # type: ignore[arg-type]
    assert isinstance(handler, logging.Handler) and handler.detached is False
    record = logging.LogRecord("n", logging.INFO, "f", 1, "msg", (), None)
    assert handler.format(record).endswith("[INFO] n: msg")


# --------------------------------------------------------------------------- display panel behaviour kept

async def test_panel_log_accepts_lowercase_and_unknown_levels_and_defaults_to_info(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log("default level")
        app.panel.log("lower", "warning")
        app.panel.log("odd", "TRACE")
        text = await read_panel(pilot)
        assert "default level" in text and "lower" in text and "odd" in text


# --------------------------------------------------------------------------- hosts that wire things by hand

async def test_a_host_built_tui_handler_still_works_on_both_threads_and_goes_quiet_at_exit(
    make_app, unique_logger, handle_errors, thread_errors
):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    handler = TUILogHandler(app)
    lg.addHandler(handler)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        lg.warning("ui-side")
        run_threads(lambda: lg.warning("thread-side"))
        await wait_for(lambda: "thread-side" in panel_text(app))
        assert "ui-side" in panel_text(app)
    lg.warning("after-exit")
    run_threads(lambda: lg.warning("after-exit-thread"))
    assert handle_errors == [] and thread_errors == []
    lg.removeHandler(handler)  # the host owns this handler, so the host removes it


async def test_subclass_on_unmount_without_super_still_lets_the_base_detach(host_root):
    class Sub(CLIApp):
        def on_unmount(self) -> None:  # does not call super()
            pass

    before = (list(host_root.handlers), host_root.level)
    app = Sub(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE):
        attach_logging(app, exclusive=True, level=logging.DEBUG)
    assert (list(host_root.handlers), host_root.level) == before


async def test_subclass_on_unmount_with_super_also_restores(host_root):
    class Sub(CLIApp):
        def on_unmount(self) -> None:
            super().on_unmount()

    before = (list(host_root.handlers), host_root.level)
    app = Sub(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE):
        attach_logging(app, exclusive=True, level=logging.DEBUG)
    assert (list(host_root.handlers), host_root.level) == before
    assert not tui_handlers(host_root)


async def test_subclass_on_mount_without_super_still_gets_a_working_panel_and_inbox():
    class Sub(CLIApp):
        def on_mount(self) -> None:
            self.push_log("sub-before-base-mount")

    app = Sub(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE):
        run_threads(lambda: app.push_log("bg-after"))
        await wait_for(lambda: "bg-after" in panel_text(app))
        assert "sub-before-base-mount" in panel_text(app)


# --------------------------------------------------------------------------- degraded-but-reachable items

async def test_an_item_with_a_reserved_shortcut_stays_reachable_by_enter_and_by_position():
    calls = Calls()
    app = quiet_app(MenuItem("Quit it", shortcut="q", action=calls.action("quit-item")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        app.query_one("#command-input", Input).value = "1"
        await pilot.press("enter")
        await pilot.pause()
        assert calls.names == ["quit-item", "quit-item"] and app.is_running


# --------------------------------------------------------------------------- api/probe4.py, converted

async def test_probe4_single_key_does_nothing_and_key_plus_enter_fires(make_app, unique_logger, handle_errors):
    lg = unique_logger("probe4", logging.INFO)
    app = make_app(leaf("Value", "a", lambda: 42), leaf("Logs", "l", lambda: lg.info("hello from UI thread")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        await pilot.press("a")
        await pilot.pause()
        assert app.query_one("#command-input", Input).value == "a"
        assert "Executed" not in panel_text(app)
        await pilot.press("enter")
        await pilot.pause()
        assert "Executed: Value → 42" in panel_text(app)
        await pilot.press("l", "enter")
        await pilot.pause()
        assert "hello from UI thread" in panel_text(app)
    assert handle_errors == []


# --------------------------------------------------------------------------- PromptScreen used on its own

class _PromptHost(App):
    result = "unset"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__()
        self._args, self._kwargs = args, kwargs

    def on_mount(self) -> None:
        self.push_screen(PromptScreen(*self._args, **self._kwargs), lambda v: setattr(self, "result", v))


async def test_prompt_screen_positional_form_mounts_unmasked_and_dismisses_with_the_typed_value():
    app = _PromptHost("Title", "Prompt")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is False
        await pilot.press("h", "i", "enter")
        await pilot.pause()
    assert app.result == "hi"


async def test_prompt_screen_escape_dismisses_with_none_for_plain_and_secret():
    for kwargs in ({}, {"secret": True}):
        app = _PromptHost("T", "P", **kwargs)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
        assert app.result is None


async def test_prompt_screen_secret_keyword_form_masks_and_still_returns_the_real_value():
    app = _PromptHost(item_label="T [/x]", prompt="P [/y]", secret=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#prompt-input", Input).password is True
        await pilot.press("s", "e", "c", "enter")
        await pilot.pause()
    assert app.result == "sec"


# --------------------------------------------------------------------------- spinner timers and quitting

@pytest.mark.parametrize("label", ["", "busy"])
async def test_quitting_through_exit_with_a_spinner_running_leaves_run_test_cleanly(make_app, label):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.start_spinner(label=label)  # without a label this also starts the phrase-rotation timer
        await pilot.pause(0.2)  # let the 1/12 s tick fire a few times
        app.exit()
    assert app.return_code == 0


@pytest.mark.xfail(
    strict=True,
    reason=(
        "harness-only teardown race, pre-existing (code unchanged since fdb8069): run_test shuts down without "
        "exit(), so Timer._tick does not skip the callback and it finds the screens pruned; a real quit goes "
        "through exit(). The guard is deferred to the Phase 1 timer lifecycle, ruling E."
    ),
)
async def test_late_timer_ticks_after_teardown_are_harmless(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    failures = []
    for tick in (app._tick_spinner, app._cycle_phrase, app._cycle_spinner_phrase):
        try:
            tick()  # what a timer callback that lands after the screens are gone does
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{tick.__name__}: {type(exc).__name__}")
    assert not failures, failures
