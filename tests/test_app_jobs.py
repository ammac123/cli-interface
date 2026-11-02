"""P2.2 / P2.3 / P2.4 on a real (headless) app: busy, stop, spinner, the menu proxies, hello, state and quit."""
from __future__ import annotations

import asyncio
import os
import threading
import time

import pytest
from textual.widgets import Input

import cli_interface
from cli_interface import App, CLIApp, Context
from cli_interface.capture import CAPTURE
from cli_interface.jobs import JobSpec
from cli_interface.menu import RESERVED_COMMANDS, MenuItem
from cli_interface.widgets import Dashboard, PromptScreen
from helpers import (
    SIZE, crumbs, leaf, make_gate, menu, panel_lines, panel_text, press_and_wait, settle, type_command, wait_event, widget_text,
)


class Body:
    """A gated command body: records that it started and waits for the test to release it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = make_gate()
        self.runs = 0

    def __call__(self, ctx: Context) -> str:
        self.runs += 1
        self.started.set()
        self.release.wait(15)
        return "slow done"


def spinner(app) -> tuple[bool, str]:
    dash = app.query_one("#dashboard", Dashboard)
    return dash.spinning, dash.spinner_label


# --------------------------------------------------------------------------- a thread job end to end

async def test_a_thread_command_renders_its_output_in_order_and_ends_with_executed():
    app = App("T")
    proceed = make_gate()

    @app.command("Work", key="w")
    def work(ctx: Context):
        ctx.log("log from thread")
        print("print from thread")
        ctx.panel.text("panel from thread")
        ctx.progress(1, 2, "half")
        ctx.state.touched = True
        assert threading.current_thread().daemon
        assert threading.current_thread().name.startswith("cli-interface-job-")
        proceed.wait(15)
        return {"done": True}

    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press(*"w", "enter")
        await pilot.pause()
        assert app.jobs.busy and app.jobs.current.label == "Work"
        proceed.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await pilot.pause()
        lines = panel_lines(app)
        assert lines[:3] == ["log from thread", "print from thread", "panel from thread"]
        assert lines[-1] == "Executed: Work" and '"done": true' in panel_text(app)
        assert app.state.touched is True
        assert spinner(app)[0] is False


async def test_a_plain_menu_action_that_asks_for_a_context_runs_in_a_thread_too():
    names = []

    def with_ctx(ctx: Context):
        names.append(threading.current_thread().name)
        ctx.log("hello")
        return 5

    app = CLIApp(menu(MenuItem("Ctx", shortcut="c", action=with_ctx)))
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "c", "enter")
        assert names[0].startswith("cli-interface-job-")
        assert panel_lines(app) == ["hello", "Executed: Ctx → 5"]


async def test_ctx_state_is_the_apps_shared_namespace_across_commands():
    app = App("S")

    @app.command("Set", key="a")
    def set_it(ctx: Context):
        ctx.state.value = 41

    @app.command("Read", key="r")
    def read_it(ctx: Context):
        return ctx.state.value + 1

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "a", "enter")
        await press_and_wait(pilot, "r", "enter")
        assert app.state.value == 41 and panel_lines(app)[-1] == "Executed: Read → 42"


# --------------------------------------------------------------------------- busy

async def test_a_second_enter_while_a_command_runs_is_rejected_with_the_busy_warning():
    app = App("B")
    body = Body()
    app.add_command("Slow", body, key="s")
    app.add_command("Other", lambda: "never", key="o")
    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await pilot.press("s", "enter")
        await pilot.press("o", "enter")
        await pilot.pause()
        text = panel_text(app)
        assert text.count("Busy: Slow is running (type stop to stop it)") == 2
        assert body.runs == 1 and "never" not in text and "Executed: Other" not in text
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await pilot.press("o", "enter")
        await app.jobs.wait_idle(since=mark, jobs=2)
        assert "Executed: Other → never" in panel_text(app)


async def test_a_prompt_command_is_rejected_as_busy_before_its_prompt_opens():
    app = CLIApp(menu(
        MenuItem("Slow", shortcut="s", action=(body := Body())),
        MenuItem("Ask", shortcut="a", prompt="Value:", action=lambda v: v),
    ))
    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await type_command(pilot, "a")
        assert not isinstance(app.screen, PromptScreen), "no prompt may open while busy"
        assert "Busy: Slow is running (type stop to stop it)" in panel_text(app)
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await type_command(pilot, "a")
        assert isinstance(app.screen, PromptScreen), "idle again: the prompt opens"


async def test_navigation_clear_and_help_still_work_while_a_command_runs():
    body = Body()
    app = CLIApp(menu(
        MenuItem("Slow", shortcut="s", action=body),
        MenuItem("Sub", shortcut="u", children=[leaf("Inner", "i")]),
    ))
    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await type_command(pilot, "u")
        assert crumbs(app) == ("Home", "Sub")
        await pilot.press("escape")
        assert crumbs(app) == ("Home",)
        await type_command(pilot, "help")
        assert "Navigate menu items" in panel_text(app)
        await type_command(pilot, "clear")
        assert panel_lines(app) == []
        assert app.jobs.busy
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)


# --------------------------------------------------------------------------- stop

async def test_stop_says_nothing_is_running_when_idle():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "stop")
        assert panel_lines(app) == ["Nothing is running"]
        await type_command(pilot, "STOP")
        assert panel_lines(app).count("Nothing is running") == 2


async def test_stop_cancels_a_cancellable_command_which_can_then_run_again():
    app = App("S")
    runs = []

    @app.command("Spin", key="s", cancellable=True)
    def spin(ctx: Context):
        runs.append(1)
        ctx.log("spinning")
        ctx.cancelled.wait(15)
        ctx.check_cancelled()

    async with app.run_test(size=SIZE) as pilot:
        for n in (1, 2):
            mark = app.jobs.mark()
            await pilot.press("s", "enter")
            await pilot.pause()
            await type_command(pilot, "stop")
            await app.jobs.wait_idle(since=mark, jobs=1)
            await pilot.pause()
            assert panel_lines(app).count("Cancelled: Spin") == n and len(runs) == n
        assert app.jobs.state == "idle" and spinner(app)[0] is False


async def test_stop_on_a_command_that_cannot_be_stopped_warns_once_then_abandons_it():
    app = App("S")
    body = Body()
    app.add_command("Stuck", body, key="s")
    app.add_command("Next", lambda: "fresh", key="n")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await type_command(pilot, "stop")
        text = panel_text(app)
        assert "Stuck cannot be stopped cleanly; type stop again to abandon it" in text
        assert app.jobs.state == "running" and not app.jobs.current.cancelled.is_set()
        stuck = app.jobs.current
        await type_command(pilot, "stop")
        assert "Abandoned: Stuck (it did not stop; its output is now ignored)" in panel_text(app)
        assert stuck.outcome == "abandoned" and app.jobs.state == "idle"
        assert spinner(app)[0] is False
        await press_and_wait(pilot, "n", "enter")
        assert panel_lines(app)[-1] == "Executed: Next → fresh"
        body.release.set()


async def test_stop_is_a_typed_command_with_no_key_binding_and_ctrl_c_still_quits():
    assert "stop" in RESERVED_COMMANDS
    actions = {b.action for b in CLIApp.BINDINGS}
    keys = {b.key for b in CLIApp.BINDINGS}
    assert not any("stop" in a for a in actions) and not hasattr(CLIApp, "action_stop")
    assert {"ctrl+c"} <= keys and next(b for b in CLIApp.BINDINGS if b.key == "ctrl+c").action == "quit"
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("ctrl+c")
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        assert app.return_code == 0


async def test_the_help_table_lists_stop_and_the_hint_line_does_not():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "help")
        text = panel_text(app)
        assert "stop + Enter" in text and "Cancel the running command" in text
        assert "stop" not in widget_text(app.query_one("#hint"))


# --------------------------------------------------------------------------- spinner references

async def test_the_spinner_shows_the_command_label_while_a_job_runs_and_goes_off_after():
    app = App("S")
    body = Body()
    app.add_command("Slow", body, key="s")
    async with app.run_test(size=SIZE) as pilot:
        assert spinner(app)[0] is False
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await pilot.pause()
        assert spinner(app) == (True, "Slow")
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await pilot.pause()
        assert spinner(app)[0] is False


async def test_status_and_progress_text_override_the_spinner_label():
    app = App("P")
    steps = [
        (dict(current=3, total=10, label="Work"), "Work 3/10 (30%)"),
        (dict(current=3, label="Work"), "Work 3"),
        (dict(label="Only label"), "Only label"),
        (dict(current=2.5, total=10, label=""), "2.5/10 (25%)"),
        (dict(done=True), "Slow"),
    ]
    reached = [threading.Event() for _ in steps]
    gates = [make_gate() for _ in steps]
    status_seen = threading.Event()
    status_gate = make_gate()

    @app.command("Slow", key="w")
    def work(ctx: Context):
        ctx.status("Compiling")
        status_seen.set()
        status_gate.wait(15)
        for (kwargs, _), reached_event, gate in zip(steps, reached, gates, strict=True):
            ctx.progress(**kwargs)
            reached_event.set()
            gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press("w", "enter")
        await wait_event(status_seen)
        await pilot.pause()
        assert spinner(app) == (True, "Compiling")
        status_gate.set()
        for (_, expected), reached_event, gate in zip(steps, reached, gates, strict=True):
            await wait_event(reached_event)
            await pilot.pause()
            assert spinner(app) == (True, expected)
            gate.set()
        await app.jobs.wait_idle(since=mark, jobs=1)


async def test_manual_and_job_spinner_holders_are_independent():
    app = App("M")
    body = Body()
    app.add_command("Slow", body, key="s")
    async with app.run_test(size=SIZE) as pilot:
        app.start_spinner("manual")
        await pilot.pause()
        assert spinner(app) == (True, "manual")
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await pilot.pause()
        assert spinner(app) == (True, "Slow"), "the job's label wins while it runs"
        app.stop_spinner()
        await pilot.pause()
        assert spinner(app)[0] is True, "a manual stop does not end a job's spinner"
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await pilot.pause()
        assert spinner(app)[0] is False

        app.start_spinner("again")
        await pilot.pause()
        mark = app.jobs.mark()
        body.started.clear()
        body.release.clear()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await pilot.pause()
        assert spinner(app) == (True, "again"), "the manual holder keeps it on after the job ends"
        app.stop_spinner()
        await pilot.pause()
        assert spinner(app)[0] is False


async def test_an_inline_action_gets_no_spinner_of_its_own():
    seen = {}

    def inline():
        seen["spinning"] = app.query_one("#dashboard", Dashboard).spinning

    app = CLIApp(menu(MenuItem("In", shortcut="i", action=inline)))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("i", "enter")
        assert seen == {"spinning": False}


# --------------------------------------------------------------------------- the menu proxies (C1-2)

async def test_a_thread_job_can_swap_the_menu_go_home_and_refresh_it():
    app = App("Orig")
    new_root = MenuItem("Swapped", children=[MenuItem("Fresh", shortcut="f", action=lambda: None)])

    @app.command("Swap", key="s")
    def swap(ctx: Context):
        ctx.set_menu(new_root)

    @app.command("Mutate", key="m")
    def mutate(ctx: Context):
        new_root.children.append(MenuItem("Added", shortcut="a", action=lambda: None))
        ctx.refresh_menu()

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "s", "enter")
        assert crumbs(app) == ("Swapped",)
        nav = app.query_one("#nav-bar")
        assert [i.label for i in nav.items if isinstance(i.label, str)][:1] == ["Fresh"]
        await press_and_wait(pilot, "f", "enter")
        assert panel_lines(app)[-1] == "Executed: Fresh"


async def test_a_thread_job_can_go_home_from_a_submenu():
    app = App("Home")
    app.group("Sub", key="u")

    @app.command("Sub/Go", key="g")
    def go(ctx: Context):
        ctx.go_home()

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "u")
        assert crumbs(app) == ("Home", "Sub")
        await press_and_wait(pilot, "g", "enter")
        assert crumbs(app) == ("Home",)


async def test_an_async_job_can_use_the_menu_proxies_too():
    app = App("Async")
    other = MenuItem("Other", children=[leaf("Leaf", "l")])

    @app.command("Swap", key="s")
    async def swap(ctx: Context):
        ctx.set_menu(other)
        ctx.refresh_menu()
        ctx.go_home()

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "s", "enter")
        assert crumbs(app) == ("Other",)


async def test_the_proxies_work_from_a_thread_while_a_prompt_is_open():
    app = CLIApp(menu(MenuItem("Ask", shortcut="a", prompt="Value:", action=lambda v: v), leaf("Old", "o")))
    swapped = MenuItem("After", children=[leaf("Behind", "b2")])
    entered = threading.Event()

    def background(ctx: Context):
        entered.set()
        ctx.set_menu(swapped)
        ctx.refresh_menu()
        ctx.go_home()

    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "a")
        assert isinstance(app.screen, PromptScreen)
        mark = app.jobs.mark()
        assert app.jobs.submit(JobSpec("Background", background)) is not None
        await app.jobs.wait_idle(since=mark, jobs=1)
        assert entered.is_set() and isinstance(app.screen, PromptScreen) and app.is_running
        assert crumbs(app) == ("After",), "the menu behind the prompt was swapped"


async def test_a_bad_menu_from_a_job_is_the_jobs_error_not_a_crash():
    app = App("Bad")

    @app.command("Bad", key="b2")
    def bad(ctx: Context):
        ctx.set_menu("not a menu")  # type: ignore[arg-type]

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "b", "2", "enter")
        assert "Error in Bad: menu must be a MenuItem, not str" in panel_text(app)
        assert app.is_running


async def test_ui_calls_from_a_job_that_outlives_the_app_do_nothing():
    app = App("Late")
    body = Body()
    seen = []

    @app.command("Late", key="l")
    def late(ctx: Context):
        body.started.set()
        body.release.wait(15)
        ctx.set_menu(MenuItem("Too late"))
        ctx.go_home()
        ctx.log("nobody listens")
        seen.append("finished quietly")

    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("l", "enter")
        await wait_event(body.started)
    body.release.set()
    for t in threading.enumerate():
        if t.name.startswith("cli-interface-job-"):
            t.join(10)
    assert seen == ["finished quietly"]


# --------------------------------------------------------------------------- hello, startup and the panel before mount

async def test_the_first_event_delivered_is_hello_with_the_app_name(monkeypatch):
    seen = []
    original = CLIApp._sink_event
    monkeypatch.setattr(CLIApp, "_sink_event", lambda self, event: (seen.append(event), original(self, event))[1])
    app = App("Hello App")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        first = seen[0]
        assert first["kind"] == "hello" and first["app"] == "Hello App" and first["proto"] == 1
        assert first["source"] == "inprocess" and first["version"] == cli_interface.__version__
        assert first["pid"] == os.getpid()
        assert [e["kind"] for e in seen].count("hello") == 1
        assert panel_lines(app) == [], "hello writes nothing"


async def test_output_written_before_mount_keeps_its_place_ahead_of_hello(monkeypatch):
    seen = []
    original = CLIApp._sink_event
    monkeypatch.setattr(CLIApp, "_sink_event", lambda self, event: (seen.append(event["kind"]), original(self, event))[1])
    app = App("Early")
    app.panel.log("buffered before mount")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert seen[:2] == ["log", "hello"]
        assert panel_lines(app) == ["buffered before mount"]


async def test_a_second_on_mount_does_not_send_a_second_hello(monkeypatch):
    seen = []
    original = CLIApp._sink_event
    monkeypatch.setattr(CLIApp, "_sink_event", lambda self, event: (seen.append(event["kind"]), original(self, event))[1])

    class Twice(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()
            super().on_mount()

    app = Twice(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert seen.count("hello") == 1


async def test_the_panel_works_before_the_app_has_mounted(make_app):
    app = make_app(leaf("A", "a"))
    app.panel.log("early", "WARNING")
    app.panel.table([{"k": 1}])
    app.panel.clear()
    app.panel.log("late")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert panel_lines(app) == ["late"]


async def test_startup_hooks_run_at_mount_and_commands_are_busy_until_they_finish():
    app = App("Startup")
    gate = make_gate()
    entered = threading.Event()
    app.add_command("Cmd", lambda: "ran", key="c")

    @app.on_startup
    def slow_start(ctx: Context):
        ctx.log("startup running")
        entered.set()
        gate.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await wait_event(entered)
        await type_command(pilot, "c")
        text = panel_text(app)
        assert "startup running" in text and "Busy: startup is running (type stop to stop it)" in text
        mark = app.jobs.mark()
        gate.set()
        await app.jobs.wait_idle(since=mark, jobs=1)
        await press_and_wait(pilot, "c", "enter")
        assert panel_lines(app)[-1] == "Executed: Cmd → ran"


async def test_a_late_on_startup_registration_raises():
    app = App("Late")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        with pytest.raises(RuntimeError, match="on_startup hooks must be registered before the app starts"):
            app.on_startup(lambda: None)
        app.before_command(lambda: None)
        app.after_command(lambda: None)
        app.on_shutdown(lambda: None)


def test_the_hook_decorators_return_the_function_and_work_as_plain_calls():
    app = App("Decorators")

    def fn() -> None: ...

    assert app.on_startup(fn) is fn and app.on_shutdown(fn) is fn
    assert app.before_command(fn) is fn and app.after_command(fn) is fn
    assert app.on_startup("not callable") == "not callable"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- quitting

async def test_exit_with_nothing_running_is_immediate_and_unchanged():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.exit(return_code=4)
        assert app.return_code == 4


async def test_exit_stops_a_cooperative_job_well_inside_the_grace_period():
    app = App("Q", quit_grace=5.0)
    started = threading.Event()
    seen = {}

    @app.command("Coop", key="c")
    def coop(ctx: Context):
        started.set()
        seen["cancelled"] = ctx.cancelled.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c", "enter")
        await wait_event(started)
        job = app.jobs.current
        t0 = time.monotonic()
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        elapsed = time.monotonic() - t0
        assert elapsed < 3.0 and app.return_code == 0
        assert seen["cancelled"] is True and not job.abandoned


async def test_exit_with_an_uncooperative_job_waits_the_grace_period_then_abandons_it():
    app = App("Q", quit_grace=0.3)
    body = Body()
    app.add_command("Deaf", body, key="d")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d", "enter")
        await wait_event(body.started)
        job = app.jobs.current
        t0 = time.monotonic()
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        elapsed = time.monotonic() - t0
        assert job.abandoned and 0.25 <= elapsed < 5.0, elapsed
        body.release.set()


async def test_the_first_typed_q_starts_the_wait_and_the_second_quits_now():
    app = App("Q", quit_grace=60.0)
    body = Body()
    app.add_command("Deaf", body, key="d")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d", "enter")
        await wait_event(body.started)
        await type_command(pilot, "q")
        assert app.return_code is None
        assert "Stopping Deaf" in panel_text(app)
        t0 = time.monotonic()
        await pilot.press("q", "enter")
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        assert time.monotonic() - t0 < 5.0 and app.return_code == 0
        body.release.set()


async def test_exit_from_another_thread_goes_through_the_same_sequence():
    app = App("Q", quit_grace=5.0)
    started = threading.Event()

    @app.command("Coop", key="c")
    def coop(ctx: Context):
        started.set()
        ctx.cancelled.wait(15)

    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c", "enter")
        await wait_event(started)
        t = threading.Thread(target=lambda: app.exit(return_code=2), daemon=True)
        t.start()
        t.join(10)
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        assert app.return_code == 2


async def test_double_exit_with_a_hanging_shutdown_hook_and_a_stuck_job_exits_once_and_fast(monkeypatch):
    calls = []
    original = CLIApp.request_exit
    monkeypatch.setattr(CLIApp, "request_exit", lambda self, *a: (calls.append(a), original(self, *a))[1])
    app = App("Q", quit_grace=2.0)
    body, hang = Body(), make_gate()
    app.add_command("Deaf", body, key="d")
    app.on_shutdown(lambda: hang.wait(15))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d", "enter")
        await wait_event(body.started)
        t0 = time.monotonic()
        app.exit()
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        elapsed = time.monotonic() - t0
        body.release.set()
        hang.set()
    assert len(calls) == 1, calls
    assert elapsed < 1.0, f"{elapsed:.2f}s against a grace of 2.0"


async def test_shutdown_hooks_run_on_the_exit_path_before_the_app_ends():
    app = App("Q", quit_grace=5.0)
    order = []

    @app.on_shutdown
    def sync_hook(ctx: Context):
        order.append("sync")

    @app.on_shutdown
    async def async_hook():
        order.append("async")

    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
    assert order == ["sync", "async"]


async def test_the_capture_is_installed_once_per_mount_and_released_on_exit():
    app = App("C")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert CAPTURE.refs == 1
    assert CAPTURE.refs == 0


async def test_a_leftover_job_after_a_pilot_teardown_is_abandoned_quietly():
    app = App("Teardown")
    body = Body()
    app.add_command("Slow", body, key="s")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await wait_event(body.started)
        job = app.jobs.current
    assert job.abandoned and job.outcome == "abandoned"
    body.release.set()


async def test_exit_after_the_app_is_gone_is_harmless():
    app = App("Gone")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    app.exit()
    app.emit({"kind": "log"})
    app.push_log("after exit")
    assert app.jobs.submit(JobSpec("x", lambda: None)) is None


async def test_settle_is_enough_to_read_a_threads_output(make_app):
    def noisy(ctx: Context):
        for i in range(5):
            ctx.log(f"n{i}")

    app = make_app(MenuItem("Noisy", shortcut="n", action=noisy))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n", "enter")
        await settle(pilot)
        assert panel_lines(app) == [f"n{i}" for i in range(5)] + ["Executed: Noisy"]


async def test_typing_while_a_job_runs_is_still_echoed_into_the_input():
    body = Body()
    app = CLIApp(menu(MenuItem("Slow", shortcut="s", action=body)))
    async with app.run_test(size=SIZE) as pilot:
        mark = app.jobs.mark()
        await pilot.press("s", "enter")
        await wait_event(body.started)
        await pilot.press("x", "y")
        assert app.query_one("#command-input", Input).value == "xy"
        body.release.set()
        await app.jobs.wait_idle(since=mark, jobs=1)


# --------------------------------------------------------------------------- floods and self-exit

async def test_a_flooding_job_never_loses_its_result_and_any_drop_notice_has_the_exact_shape():
    import re

    app = App("Flood", max_lines=5000)

    @app.command("Flood", key="f")
    def flood(ctx: Context):
        for i in range(20_000):
            print(f"line {i}")
        return "done"

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "f", "enter", timeout=60)
        lines = panel_lines(app)
        assert "Executed: Flood → done" in lines, "the protected result is never dropped"
        tail = lines[lines.index("Executed: Flood → done") + 1:]
        assert len(tail) <= 1 and all("more log record(s) dropped" in ln for ln in tail), "only the closing notice may follow"
        assert len(lines) <= 5000
        for line in lines:
            if "dropped" in line:
                assert re.fullmatch(r"\d+ (more )?log record\(s\) dropped \(UI busy\)", line), line
        assert app.jobs.state == "idle" and spinner(app)[0] is False


@pytest.mark.parametrize("lane", ["thread", "loop"])
async def test_a_job_that_exits_the_app_itself_ends_it_with_its_code_and_promptly(lane):
    app = App("SelfExit", quit_grace=5.0)
    outcomes = []

    if lane == "thread":
        @app.command("Go", key="g")
        def go(ctx: Context):
            app.exit(return_code=5)
            ctx.cancelled.wait(10)
            outcomes.append("returned")
    else:
        @app.command("Go", key="g")
        async def go(ctx: Context):
            app.exit(return_code=5)
            await asyncio.sleep(0)
            outcomes.append("returned")

    async with app.run_test(size=SIZE) as pilot:
        t0 = time.monotonic()
        await pilot.press("g", "enter")
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=15)
        assert app.return_code == 5 and time.monotonic() - t0 < 5.0
