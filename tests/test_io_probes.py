"""The Phase 0/1 I/O probes (exp1-exp7), turned into regression tests for the Phase 2 job runner and capture."""
from __future__ import annotations

import asyncio
import collections
import logging
import sys
import threading
import time
from typing import Optional

from cli_interface import App, CLIApp, Context
from cli_interface.app import attach_logging
from cli_interface.capture import CAPTURE
from cli_interface.log_handler import PanelInbox
from cli_interface.menu import MenuItem
from helpers import (
    SIZE, StubSink, leaf, make_gate, menu, panel_lines, panel_text, press_and_wait, run_threads, wait_event,
)

RUN = dict(headless=True, size=(120, 30))


# --------------------------------------------------------------------------- exp1: logging from every thread, in order, no deadlock

async def test_records_from_the_ui_thread_an_action_and_a_background_thread_arrive_in_order(make_app, unique_logger, handle_errors):
    lg = unique_logger("exp1", logging.DEBUG)
    app = make_app(MenuItem("Act", shortcut="a", action=lambda: lg.warning("FROM-ACTION")))
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        lg.info("FROM-MAIN-THREAD")
        await pilot.press("a", "enter")
        t = threading.Thread(target=lambda: lg.info("FROM-BG-THREAD"))
        t.start()
        t.join(5)
        assert not t.is_alive(), "a background log call must not wait on the UI"
        await app.jobs.wait_idle()
        text = panel_text(app)
        order = [text.index(x) for x in ("FROM-MAIN-THREAD", "FROM-ACTION", "Executed: Act", "FROM-BG-THREAD")]
        assert order == sorted(order)
    assert handle_errors == []
    t = threading.Thread(target=lambda: lg.info("AFTER-EXIT"))
    t.start()
    t.join(5)
    assert not t.is_alive() and lg.handlers == []


async def test_a_job_thread_logging_through_a_named_logger_does_not_deadlock_the_ui(unique_logger):
    lg = unique_logger("exp1job", logging.DEBUG)
    app = App("Exp1")

    @app.command("Log", key="l")
    def log_a_lot(ctx: Context):
        attach_logging(app, lg)
        for i in range(500):
            lg.info("job record %d", i)

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "l", "enter")
        text = panel_text(app)
        assert "job record 0" in text and "job record 499" in text and "dropped" not in text
    assert lg.handlers == []


# --------------------------------------------------------------------------- exp2: after exit, with a job thread still running

def test_a_job_thread_that_keeps_logging_and_printing_after_a_real_run_exits_is_silent(
    unique_logger, handle_errors, thread_errors, capfd
):
    lg = unique_logger("exp2", logging.INFO)
    app = App("Exp2", quit_grace=0.1)
    stop, started, installed_ticks, drained_ticks = threading.Event(), threading.Event(), threading.Event(), threading.Event()
    progress = {"ticks": 0, "target": None}

    @app.command("Run", key="r")
    def noisy(ctx: Context):
        started.set()
        while not stop.is_set():
            lg.info("tick")
            print("job tick")
            if app.return_code is not None and CAPTURE.installed:  # run() has returned and the capture is back
                progress["ticks"] += 1
                if progress["ticks"] > 50:
                    installed_ticks.set()
                target = progress["target"]
                if target is not None and progress["ticks"] > target:
                    drained_ticks.set()
            stop.wait(0.001)

    async def auto(pilot):
        attach_logging(app, lg)
        await pilot.press("r", "enter")
        await asyncio.get_running_loop().run_in_executor(None, started.wait, 10)
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=15)

    app.run(auto_pilot=auto, **RUN)
    assert app.return_code == 0 and app._loop is None, "the run returned although the job thread is still running"
    assert installed_ticks.wait(15), "the abandoned job kept logging and printing into a dead app"
    capfd.readouterr()  # whatever an abandoned job printed while Textual was leaving its own redirect
    progress["target"] = progress["ticks"] + 50
    assert drained_ticks.wait(15)
    stop.set()
    for t in threading.enumerate():
        if t.name.startswith("cli-interface-job-"):
            t.join(10)
    assert lg.handlers == []
    assert handle_errors == [] and thread_errors == []
    assert CAPTURE.refs == 0
    leaked = capfd.readouterr()
    assert "job tick" not in leaked.out + leaked.err, "once run() has returned the capture swallows the abandoned job"


# --------------------------------------------------------------------------- exp3 / exp3b: print is captured, odd text is safe

async def test_print_and_stderr_from_an_action_reach_the_panel_and_not_the_terminal(make_app, capfd):
    def prints():
        print("PRINTED-BY-FOREIGN-CODE")
        sys.stderr.write("STDERR-BY-FOREIGN-CODE\n")

    app = make_app(MenuItem("Print", shortcut="p", action=prints))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        text = panel_text(app)
        assert "PRINTED-BY-FOREIGN-CODE" in text and "STDERR-BY-FOREIGN-CODE" in text
    captured = capfd.readouterr()
    assert "FOREIGN-CODE" not in captured.out + captured.err


async def test_a_return_value_and_an_exception_containing_closing_tags_leave_the_app_alive(make_app):
    def ret():
        return "copied 3 files to out/[/tmp]"

    def boom():
        raise ValueError("bad key [/x] in config")

    app = make_app(MenuItem("Ret", shortcut="r", action=ret), MenuItem("Boom", shortcut="b2", action=boom))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r", "enter")
        await pilot.press(*"b2", "enter")
        text = panel_text(app)
        assert "Executed: Ret → copied 3 files to out/[/tmp]" in text and "Error in Boom: bad key [/x] in config" in text
        assert app.is_running and app.return_code is None


async def test_a_background_record_with_a_closing_tag_is_shown_and_the_app_survives(make_app, unique_logger):
    lg = unique_logger("exp3b", logging.INFO)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        attach_logging(app, lg)
        run_threads(lambda: lg.info("path is out/[/tmp] ok"))
        await app.jobs.wait_idle()
        assert "path is out/[/tmp] ok" in panel_text(app) and app.is_running


# --------------------------------------------------------------------------- exp4: reruns after every kind of ending

async def test_a_command_can_be_rerun_after_an_error_a_cancel_and_an_abandon(capfd):
    app = App("Reruns")
    behaviour = {"mode": "ok"}
    started, release = threading.Event(), make_gate()

    @app.command("Cmd", key="c", cancellable=True)
    def cmd(ctx: Context):
        print(f"PRINTED {behaviour['mode']}")
        mode = behaviour["mode"]
        if mode == "error":
            raise KeyError("missing")
        if mode == "cancel":
            started.set()
            ctx.cancelled.wait(15)
            ctx.check_cancelled()
        if mode == "abandon":
            started.set()
            release.wait(15)
        return mode

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "c", "enter")
        behaviour["mode"] = "error"
        await press_and_wait(pilot, "c", "enter")
        behaviour["mode"] = "cancel"
        mark = app.jobs.mark()
        await pilot.press("c", "enter")
        await wait_event(started)
        await pilot.press(*"stop", "enter")
        await app.jobs.wait_idle(since=mark, jobs=1)
        behaviour["mode"] = "abandon"
        started.clear()
        await pilot.press("c", "enter")
        await wait_event(started)
        await pilot.press(*"stop", "enter")
        await pilot.press(*"stop", "enter")
        assert app.jobs.state == "idle"
        behaviour["mode"] = "ok"
        await press_and_wait(pilot, "c", "enter")
        release.set()
        lines = panel_lines(app)
        for expected in ("Executed: Cmd → ok", "Error in Cmd: 'missing'", "Cancelled: Cmd",
                         "Abandoned: Cmd (it did not stop; its output is now ignored)"):
            assert expected in lines, (expected, lines)
        assert lines.count("Executed: Cmd → ok") == 2
        assert all(f"PRINTED {m}" in lines for m in ("ok", "error", "cancel", "abandon"))
    captured = capfd.readouterr()
    assert "PRINTED" not in captured.out + captured.err


# --------------------------------------------------------------------------- M6, at the app level

async def test_an_optional_context_parameter_makes_a_plain_action_run_in_a_thread_with_the_context():
    seen = {}

    def f(ctx: Context | None = None):
        seen["thread"] = threading.current_thread().name
        seen["ctx"] = type(ctx).__name__
        return "done"

    app = CLIApp(menu(MenuItem("Opt", shortcut="o", action=f)))
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "o", "enter")
        assert seen["thread"].startswith("cli-interface-job-") and seen["ctx"] == "Context"
        assert panel_lines(app) == ["Executed: Opt → done"]


async def test_an_optional_str_prompt_value_keeps_the_action_inline_and_gets_the_value():
    seen = {}

    def f(value: Optional[str]):  # noqa: UP045
        seen["thread"] = threading.get_ident()
        seen["value"] = value

    app = CLIApp(menu(MenuItem("Ask", shortcut="a", prompt="v:", action=f)))
    async with app.run_test(size=SIZE) as pilot:
        from helpers import type_command

        await type_command(pilot, "a")
        await pilot.press("x", "enter")
        await pilot.pause()
        assert seen == {"thread": threading.get_ident(), "value": "x"}


# --------------------------------------------------------------------------- exp7: the event path costs no more than twice the Phase 1 path

class Phase1Inbox:
    """The Phase 1 PanelInbox.put hot path (strings, a deque, one wake), kept here as a same-run baseline."""

    def __init__(self, loop) -> None:
        self._loop = loop
        self._lock = threading.Lock()
        self._dq: collections.deque = collections.deque()
        self._ui_ident = threading.get_ident()
        self._wake_pending = False
        self.out: list = []

    def put(self, message: str, level: str = "INFO") -> None:
        loop = None
        with self._lock:
            if threading.get_ident() != self._ui_ident:
                if len(self._dq) >= 10_000:
                    self._dq.popleft()
                self._dq.append((message, level))
                if not self._wake_pending:
                    self._wake_pending = True
                    loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._on_wake)

    def _on_wake(self) -> None:
        with self._lock:
            self._wake_pending = False
        while self._dq:
            self.out.append(self._dq.popleft())


def _logging_rate(lg: logging.Logger, handler: logging.Handler, n: int) -> float:
    lg.addHandler(handler)
    try:
        start = time.perf_counter()
        t = threading.Thread(target=lambda: [lg.info("record %d", i) for i in range(n)], daemon=True)
        t.start()
        t.join(60)
        assert not t.is_alive()
        return n / (time.perf_counter() - start)
    finally:
        lg.removeHandler(handler)


async def test_logging_through_the_event_path_costs_no_more_than_twice_the_phase_1_path(unique_logger):
    from cli_interface.log_handler import TUILogHandler

    lg = unique_logger("exp7", logging.INFO)
    loop = asyncio.get_running_loop()
    n = 10_000

    class Phase1Host:
        def __init__(self) -> None:
            self.inbox = Phase1Inbox(loop)

        def push_log(self, message: str, level: str = "INFO") -> None:
            self.inbox.put(message, level)

    class Phase2Host:
        def __init__(self) -> None:
            self.sink = StubSink()
            self.inbox = PanelInbox(self.sink, 100_000)
            self.inbox.open(loop)
            self.emit = self.inbox.put

        def push_log(self, message: str, level: str = "INFO") -> None:
            self.inbox.put(message, level)

    old = max(_logging_rate(lg, TUILogHandler(Phase1Host()), n) for _ in range(3))  # type: ignore[arg-type]
    new = max(_logging_rate(lg, TUILogHandler(Phase2Host()), n) for _ in range(3))  # type: ignore[arg-type]
    assert new > 20_000, f"{new:,.0f} records/s"
    assert new > old / 2, f"events {new:,.0f}/s against the Phase 1 path's {old:,.0f}/s on this machine"


async def test_a_hundred_thousand_puts_complete_quickly_and_flush_in_order():
    from cli_interface.events import make_log

    sink = StubSink()
    inbox = PanelInbox(sink, 200_000)
    inbox.open(asyncio.get_running_loop())
    events = [make_log(f"r{i}") for i in range(100_000)]
    start = time.perf_counter()
    t = threading.Thread(target=lambda: [inbox.put(e) for e in events], daemon=True)
    t.start()
    t.join(30)
    elapsed = time.perf_counter() - start
    assert not t.is_alive() and elapsed < 5, f"100,000 puts took {elapsed:.2f}s"
    inbox.flush()
    assert [e["msg"] for e in sink.events] == [f"r{i}" for i in range(100_000)]
