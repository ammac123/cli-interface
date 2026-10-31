"""Tests that need a real App.run(headless=True): they are synchronous because run() owns its own event loop."""
from __future__ import annotations

import logging
import threading
import time

import pytest

from cli_interface.app import CLIApp, attach_logging
from helpers import (
    Calls, build_demo_app, join_all, leaf, menu, panel_text, tui_handlers, wait_until,
)

RUN = dict(headless=True, size=(120, 30))


def test_a_worker_that_keeps_logging_after_a_real_run_exits_is_silent(unique_logger, handle_errors, thread_errors):
    lg = unique_logger("exp2", logging.INFO)
    stop = threading.Event()
    emitted: list[int] = []

    def worker():
        while not stop.is_set():
            lg.info("tick")
            emitted.append(1)
            time.sleep(0.001)

    class App(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()
            attach_logging(self, lg)
            threading.Thread(target=worker, daemon=True, name="exp2-worker").start()
            self.set_timer(0.4, self.exit)

    app = App(menu(leaf("A", "a")))
    app.run(**RUN)
    assert app._loop is None, "control: the app's loop reference is gone after run() returns"
    n0 = len(emitted)
    wait_until(lambda: len(emitted) > n0 + 50, timeout=10, what="records emitted after exit")
    stop.set()
    join_all([t for t in threading.enumerate() if t.name == "exp2-worker"])
    assert lg.handlers == []
    assert handle_errors == [] and thread_errors == []


@pytest.mark.parametrize("cycle", range(3))
def test_a_logger_hammered_from_a_thread_through_a_real_run_tears_down_cleanly(
    cycle, unique_logger, handle_errors, thread_errors
):
    lg = unique_logger(f"hammer{cycle}")
    calls = Calls()
    app = CLIApp(menu(leaf("A", "a", calls.action("A"))))
    stop = threading.Event()

    def hammer_loop():
        n = 0
        while not stop.is_set():
            lg.info("msg %d", n)
            n += 1
            time.sleep(0.001)

    hammer = threading.Thread(target=hammer_loop, daemon=True)
    attach_logging(app, lg)

    async def auto(pilot):
        await pilot.pause()
        await pilot.press("a", "enter")  # before the hammer starts: pilot.press waits for an idle UI
        hammer.start()
        await pilot.pause(0.2)
        for k in range(50):
            lg.warning("ui %d", k)  # UI-thread records while the hammer runs
        await pilot.pause(0.1)
        app.exit()

    app.run(auto_pilot=auto, **RUN)
    time.sleep(0.1)  # the hammer is still logging into a dead app
    stop.set()
    join_all([hammer])
    assert calls.names == ["A"]
    assert lg.handlers == []
    assert handle_errors == [] and thread_errors == []


def test_a_crashing_real_run_restores_the_hosts_handlers_and_level(host_root):
    class Crash(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()
            self.set_timer(0.2, lambda: 1 / 0)

    before = (list(host_root.handlers), host_root.level)
    app = Crash(menu(leaf("A", "a")))

    async def auto(pilot):
        await pilot.pause()
        attach_logging(app, None, exclusive=True, level=logging.DEBUG)
        assert host_root.sentinel not in host_root.handlers

    app.run(auto_pilot=auto, **RUN)
    assert app.return_code == 1
    assert (list(host_root.handlers), host_root.level) == before
    assert not tui_handlers(host_root)


def test_closing_the_app_mid_worker_in_a_real_run_leaves_no_traceback_and_restores_root(
    gated_worker, host_root, handle_errors, thread_errors
):
    before = (list(host_root.handlers), host_root.level)
    app = build_demo_app()
    seen: dict[str, object] = {}

    async def auto(pilot):
        await pilot.pause()
        await pilot.press("w", "enter")
        deadline = time.monotonic() + 5
        while not gated_worker.started.is_set() and time.monotonic() < deadline:
            await pilot.pause(0.02)
        await pilot.pause()
        seen["attached"] = len(tui_handlers(host_root))
        app.exit()

    app.run(auto_pilot=auto, **RUN)
    assert app.return_code == 0
    assert seen["attached"] == 1
    assert (list(host_root.handlers), host_root.level) == before
    assert app._loop is None
    worker = gated_worker.threads.alive()
    assert len(worker) == 1, "control: the worker outlives the app"
    gated_worker.release.set()
    join_all(worker)  # no loop to answer call_from_thread, so the guard must absorb the RuntimeError
    assert thread_errors == [] and handle_errors == []
    assert (list(host_root.handlers), host_root.level) == before


def test_real_run_of_the_worker_demo_shows_its_records_then_restores_root(fast_worker, host_root):
    before = (list(host_root.handlers), host_root.level)
    app = build_demo_app()
    seen: dict[str, str] = {}

    async def auto(pilot):
        await pilot.pause()
        await pilot.press("w", "enter")
        deadline = time.monotonic() + 15
        while "Worker finished" not in panel_text(app) and time.monotonic() < deadline:
            await pilot.pause(0.05)
        while fast_worker.alive() and time.monotonic() < deadline:
            await pilot.pause(0.05)
        seen["text"] = panel_text(app)
        seen["handlers_after_worker"] = str(len(tui_handlers(host_root)))
        app.exit()

    app.run(auto_pilot=auto, **RUN)
    assert "Worker starting" in seen["text"] and "Worker finished" in seen["text"]
    assert seen["handlers_after_worker"] == "0"
    assert (list(host_root.handlers), host_root.level) == before


def test_logging_attached_and_used_before_a_real_run_is_shown_after_mount(unique_logger, handle_errors):
    lg = unique_logger()
    app = CLIApp(menu(leaf("A", "a")))
    attach_logging(app, lg)
    lg.info("logged before app.run")
    seen: dict[str, str] = {}

    async def auto(pilot):
        await pilot.pause()
        lg.info("logged from UI thread")
        await pilot.pause()
        seen["text"] = panel_text(app)
        app.exit()

    app.run(auto_pilot=auto, **RUN)
    assert "logged before app.run" in seen["text"] and "logged from UI thread" in seen["text"]
    assert lg.handlers == [] and handle_errors == []


@pytest.mark.parametrize("settle", [0.0, 0.05, 0.2])
def test_quitting_through_exit_with_a_spinner_running_in_a_real_run_returns_zero(settle):
    app = CLIApp(menu(leaf("A", "a")))

    async def auto(pilot):
        await pilot.pause()
        app.start_spinner()  # no label: also starts the phrase-rotation timer
        await pilot.pause(settle)  # vary where in the 1/12 s tick the quit lands
        app.exit()

    app.run(auto_pilot=auto, **RUN)
    assert app.return_code == 0
