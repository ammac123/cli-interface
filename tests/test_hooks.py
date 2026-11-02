"""P2.4: on_startup / on_shutdown / before_command / after_command, and the quit sequence that runs the shutdown hooks."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest

from cli_interface.context import Context
from cli_interface.jobs import JobSpec
from helpers import make_gate, wait_event
from jobrig import Rig


def job_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("cli-interface-job-")]


def join_job_threads(timeout: float = 10.0) -> None:
    for t in job_threads():
        t.join(timeout)
    assert job_threads() == []


class Quit:
    """Counts calls of the exit callback and lets a test await the first one."""

    def __init__(self) -> None:
        self.calls: list[float] = []
        self.first = asyncio.Event()
        self.t0 = time.monotonic()

    def __call__(self) -> None:
        self.calls.append(time.monotonic() - self.t0)
        self.first.set()

    async def wait(self, timeout: float = 10.0) -> None:
        await asyncio.wait_for(self.first.wait(), timeout)


# --------------------------------------------------------------------------- before_command / after_command

async def test_hooks_run_before_hooks_then_body_then_result_then_after_hooks_in_registration_order(make_rig):
    rig: Rig = make_rig()
    order: list[str] = []

    rig.mgr.add_hook("before", lambda: order.append("before1"))
    rig.mgr.add_hook("before", lambda ctx: order.append("before2"))
    rig.mgr.add_hook("after", lambda ctx: order.append(f"after1:{ctx.job.outcome}:{rig.host.kinds()[-1]}"))
    rig.mgr.add_hook("after", lambda: order.append("after2"))
    await rig.run(lambda ctx: order.append("body"), "Cmd")
    assert order == ["before1", "before2", "body", "after1:ok:result", "after2"]
    assert rig.host.lines() == ["Executed: Cmd"], "successful hooks add no output"


async def test_hooks_accept_sync_and_async_functions_with_or_without_a_ctx(make_rig):
    rig = make_rig()
    seen: list[str] = []

    async def async_ctx(ctx):
        seen.append(f"async ctx {type(ctx).__name__}")

    async def async_bare():
        seen.append("async bare")

    def sync_ctx(ctx: Context):
        seen.append(f"sync ctx {type(ctx).__name__}")

    for fn in (async_ctx, async_bare, sync_ctx, lambda: seen.append("sync bare")):
        rig.mgr.add_hook("before", fn)
    await rig.run(lambda: seen.append("body"), "Cmd")
    assert seen == ["async ctx Context", "async bare", "sync ctx Context", "sync bare", "body"]


async def test_a_before_hook_that_raises_vetoes_the_command(make_rig):
    rig = make_rig()
    ran: list[str] = []

    def veto():
        raise PermissionError("not today")

    rig.mgr.add_hook("before", lambda: ran.append("first"))
    rig.mgr.add_hook("before", veto)
    rig.mgr.add_hook("before", lambda: ran.append("third"))
    rig.mgr.add_hook("after", lambda ctx: ran.append(f"after:{ctx.job.outcome}:{ctx.job.error}"))
    job = await rig.run(lambda: ran.append("body"), "Guarded")
    assert ran == ["first", "after:error:not today"], "body and later before hooks are skipped; after hooks still run"
    err = rig.host.of_kind("error")[0]
    assert job.outcome == "error" and (err["label"], err["message"], err["exc_type"]) == (
        "Guarded", "not today", "PermissionError"
    )
    assert rig.host.lines() == ["Error in Guarded: not today"]


async def test_an_async_before_hook_can_veto_too(make_rig):
    rig = make_rig()

    async def veto():
        raise RuntimeError("async veto")

    rig.mgr.add_hook("before", veto)
    ran = []
    job = await rig.run(lambda: ran.append("body"), "G")
    assert ran == [] and job.outcome == "error" and rig.host.of_kind("error")[0]["message"] == "async veto"


async def test_a_failing_after_hook_reports_an_error_but_does_not_change_the_outcome(make_rig):
    rig = make_rig()
    seen = []

    def bad_after():
        raise ValueError("after exploded")

    rig.mgr.add_hook("after", bad_after)
    rig.mgr.add_hook("after", lambda ctx: seen.append(ctx.job.outcome))
    job = await rig.run(lambda: "fine", "Cmd")
    assert job.outcome == "ok" and seen == ["ok"], "the next after hook still runs"
    assert rig.host.lines() == ["Executed: Cmd → fine", "Error in Cmd (after_command): after exploded"]
    assert rig.host.of_kind("error")[0]["exc_type"] == "ValueError"


async def test_after_hooks_see_the_error_and_the_outcome_of_a_failed_command(make_rig):
    rig = make_rig()
    seen = []
    rig.mgr.add_hook("after", lambda ctx: seen.append((ctx.job.outcome, ctx.job.error, ctx.job.state)))
    await rig.run(lambda: 1 / 0, "Div")
    assert seen == [("error", "division by zero", "running")]
    assert rig.mgr.completed == 1 and rig.mgr.state == "idle"


async def test_after_hooks_run_after_a_cancelled_command_too(make_rig):
    rig = make_rig()
    started, seen = threading.Event(), []
    rig.mgr.add_hook("after", lambda ctx: seen.append(ctx.job.outcome))

    def cooperative(ctx: Context):
        started.set()
        ctx.cancelled.wait(15)
        ctx.check_cancelled()

    mark = rig.mgr.mark()
    rig.submit(cooperative, "Coop", cancellable=True)
    await wait_event(started)
    rig.mgr.request_cancel()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert seen == ["cancelled"] and rig.host.lines() == ["Cancelled: Coop"]


async def test_a_command_cancelled_while_its_before_hook_runs_never_starts(make_rig):
    rig = make_rig()
    entered, release = threading.Event(), make_gate()
    ran = []

    def slow_before(ctx: Context):
        entered.set()
        release.wait(15)

    rig.mgr.add_hook("before", slow_before)
    mark = rig.mgr.mark()
    job = rig.submit(lambda ctx: ran.append("body"), "Late", cancellable=True)
    await wait_event(entered)
    rig.mgr.request_cancel()
    release.set()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert ran == [] and job.outcome == "cancelled"


async def test_after_hooks_do_not_run_for_an_abandoned_command(make_rig):
    rig = make_rig()
    started, release = threading.Event(), make_gate()
    seen = []
    rig.mgr.add_hook("after", lambda ctx: seen.append("after"))

    def stuck(ctx: Context):
        started.set()
        release.wait(15)

    job = rig.submit(stuck, "Stuck")
    await wait_event(started)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    release.set()
    join_job_threads()
    assert job.outcome == "abandoned" and seen == []


async def test_hooks_run_for_every_command_and_see_the_shared_state(make_rig):
    rig = make_rig()
    rig.mgr.add_hook("before", lambda ctx: setattr(ctx.state, "n", getattr(ctx.state, "n", 0) + 1))
    rig.mgr.add_hook("after", lambda ctx: ctx.log(f"command {ctx.state.n}"))
    await rig.run(lambda: None, "One")
    await rig.run(lambda ctx: None, "Two")
    assert rig.host.log_lines() == [("INFO", "command 1"), ("INFO", "command 2")]
    assert rig.host.state.n == 2


# --------------------------------------------------------------------------- hooks follow the job's lane

async def test_the_hooks_of_an_inline_job_run_inline_and_of_a_thread_job_in_a_thread(make_rig):
    rig = make_rig()
    where: list[tuple[str, bool, str]] = []

    def hook(tag):
        def run():
            t = threading.current_thread()
            where.append((tag, threading.get_ident() == rig.host.ui_ident, t.name))

        return run

    rig.mgr.add_hook("before", hook("before"))
    rig.mgr.add_hook("after", hook("after"))
    inline = rig.submit(lambda: None, "Inline")
    assert inline.state == "done", "sync hooks keep an inline job synchronous"
    assert [(tag, ui) for tag, ui, _ in where] == [("before", True), ("after", True)]
    where.clear()
    job = await rig.run(lambda ctx: None, "Threaded")
    assert [(tag, ui) for tag, ui, _ in where] == [("before", False), ("after", False)]
    assert all(name.startswith(f"cli-interface-job-{job.id}") for _, _, name in where)


async def test_an_async_hook_runs_on_the_loop_even_for_an_inline_body(make_rig):
    rig = make_rig()
    where = []

    async def hook():
        where.append(("hook", threading.get_ident() == rig.host.ui_ident))

    rig.mgr.add_hook("before", hook)
    job = await rig.run(lambda: where.append(("body", threading.get_ident() == rig.host.ui_ident)), "Inline")
    assert job.lane == "inline" and where == [("hook", True), ("body", True)]


async def test_hooks_that_use_the_menu_proxies_never_deadlock_in_either_lane(make_rig):
    rig = make_rig()
    rig.mgr.add_hook("before", lambda ctx: ctx.refresh_menu())
    rig.mgr.add_hook("after", lambda ctx: ctx.go_home())
    await rig.run(lambda: None, "Inline", timeout=10)
    await rig.run(lambda ctx: ctx.set_menu("m"), "Thread", timeout=10)

    async def async_job(ctx: Context):
        ctx.go_home()

    await rig.run(async_job, "Async", timeout=10)
    names = [n for n, _ in rig.host.ui_calls]
    assert names.count("refresh_menu") == 3 and names.count("go_home") == 4 and names.count("set_menu") == 1


# --------------------------------------------------------------------------- on_startup

async def test_startup_hooks_run_in_order_as_one_job_named_startup_and_say_nothing_on_success(make_rig):
    rig = make_rig()
    order: list[Any] = []
    rig.mgr.add_hook("startup", lambda ctx: order.append(("one", ctx.job.label, ctx.job.kind)))
    rig.mgr.add_hook("startup", lambda: order.append(("two",)))

    async def three(ctx):
        order.append(("three", threading.get_ident() == rig.host.ui_ident))

    rig.mgr.add_hook("startup", three)
    mark = rig.mgr.mark()
    rig.mgr.start()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert order == [("one", "startup", "startup"), ("two",), ("three", True)]
    assert rig.host.events == [], "a hook job emits nothing on success, not even a result"
    assert rig.mgr.completed == 1


async def test_start_without_hooks_runs_nothing_and_a_second_start_is_ignored(make_rig):
    rig = make_rig()
    rig.mgr.start()
    assert rig.mgr.completed == 0 and not rig.mgr.busy and rig.host.events == []
    runs = []
    rig2 = make_rig()
    rig2.mgr.add_hook("startup", lambda: runs.append(1))
    rig2.mgr.start()
    rig2.mgr.start()
    await rig2.mgr.wait_idle(since=0, jobs=1)
    assert runs == [1]


async def test_commands_are_rejected_as_busy_while_the_startup_hooks_run(make_rig):
    rig = make_rig()
    entered, release = threading.Event(), make_gate()

    def slow_startup():
        entered.set()
        release.wait(15)

    rig.mgr.add_hook("startup", slow_startup)
    mark = rig.mgr.mark()
    rig.mgr.start()
    await wait_event(entered)
    assert rig.mgr.busy and rig.mgr.submit(JobSpec("Early", lambda: None)) is None
    assert rig.host.log_lines() == [("WARNING", "Busy: startup is running (type stop to stop it)")]
    release.set()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert (await rig.run(lambda: None, "Now")).outcome == "ok"


async def test_a_failing_startup_hook_reports_an_error_and_the_rest_still_run(make_rig):
    rig = make_rig()
    ran = []

    def broken():
        raise OSError("no config")

    rig.mgr.add_hook("startup", broken)
    rig.mgr.add_hook("startup", lambda: ran.append("second"))
    mark = rig.mgr.mark()
    rig.mgr.start()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    err = rig.host.of_kind("error")
    assert ran == ["second"] and len(err) == 1
    assert (err[0]["label"], err[0]["message"], err[0]["exc_type"]) == ("startup", "no config", "OSError")
    assert rig.mgr.state == "idle", "the app keeps running"
    assert (await rig.run(lambda: None, "Fine")).outcome == "ok"


async def test_registering_a_startup_hook_after_start_raises(make_rig):
    rig = make_rig()
    rig.mgr.start()
    with pytest.raises(RuntimeError, match="on_startup hooks must be registered before the app starts"):
        rig.mgr.add_hook("startup", lambda: None)
    rig.mgr.add_hook("before", lambda: None)  # the other hooks may be added at any time
    rig.mgr.add_hook("shutdown", lambda: None)


async def test_startup_does_not_run_on_a_closed_manager(make_rig):
    rig = make_rig()
    ran = []
    rig.mgr.add_hook("startup", lambda: ran.append(1))
    rig.mgr.close()
    rig.mgr.start()
    assert ran == [] and rig.mgr.completed == 0


# --------------------------------------------------------------------------- quit and on_shutdown

async def test_quit_with_nothing_running_and_no_hooks_exits_at_once(make_rig):
    rig = make_rig()
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    assert len(quit_.calls) == 1 and rig.host.events == []


async def test_quit_asks_a_running_job_to_stop_even_when_it_is_not_cancellable_and_waits_for_it(make_rig):
    rig = make_rig(quit_grace=5.0)
    entered, seen = threading.Event(), {}

    def polite(ctx: Context):
        entered.set()
        seen["cancelled"] = ctx.cancelled.wait(15)
        return "tidy"

    job = rig.submit(polite, "Polite")
    await wait_event(entered)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    assert quit_.calls == [], "the exit waits for the job"
    assert "Stopping Polite" in rig.host.log_lines()[0][1] and rig.host.log_lines()[0][0] == "WARNING"
    await quit_.wait()
    assert seen["cancelled"] is True and job.outcome == "ok" and not job.abandoned
    assert len(quit_.calls) == 1 and quit_.calls[0] < 4.0


async def test_quit_abandons_a_job_that_ignores_the_request_after_the_grace_period(make_rig):
    rig = make_rig(quit_grace=0.2)
    entered, release = threading.Event(), make_gate()

    def deaf(ctx: Context):
        entered.set()
        release.wait(15)

    job = rig.submit(deaf, "Deaf")
    await wait_event(entered)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await quit_.wait()
    assert job.abandoned and len(quit_.calls) == 1
    assert 0.15 <= quit_.calls[0] < 5.0, quit_.calls
    assert rig.host.log_lines()[-1][1].startswith("Abandoned: Deaf")
    release.set()
    join_job_threads()


async def test_a_second_quit_skips_the_wait_and_exits_exactly_once(make_rig):
    rig = make_rig(quit_grace=30.0)
    entered, release = threading.Event(), make_gate()

    def deaf(ctx: Context):
        entered.set()
        release.wait(15)

    job = rig.submit(deaf, "Deaf")
    await wait_event(entered)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    assert quit_.calls == []
    rig.mgr.begin_quit(quit_)
    assert len(quit_.calls) == 1 and job.abandoned and quit_.calls[0] < 5.0
    release.set()
    join_job_threads()
    assert len(quit_.calls) == 1


async def test_a_quit_after_the_exit_completed_calls_the_callback_again(make_rig):
    rig = make_rig()
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    rig.mgr.begin_quit(quit_)
    assert len(quit_.calls) == 2


async def test_quit_is_ignored_after_close(make_rig):
    rig = make_rig()
    rig.mgr.close()
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    assert quit_.calls == []


async def test_new_commands_are_refused_while_the_app_is_quitting(make_rig):
    rig = make_rig(quit_grace=30.0)
    entered, release = threading.Event(), make_gate()

    def coop(ctx: Context):
        entered.set()
        release.wait(15)

    rig.submit(coop, "Coop")
    await wait_event(entered)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    assert rig.mgr.submit(JobSpec("More", lambda: None)) is None
    assert rig.host.log_lines()[-1] == ("WARNING", "Busy: Coop is stopping")
    release.set()
    await quit_.wait()
    assert rig.mgr.submit(JobSpec("After exit", lambda: None)) is None
    assert rig.host.log_lines()[-1] == ("WARNING", "Busy: the app is exiting")


async def test_shutdown_hooks_run_in_order_after_the_job_has_stopped_and_before_the_exit(make_rig):
    rig = make_rig(quit_grace=5.0)
    order: list[str] = []
    entered = threading.Event()
    rig.mgr.add_hook("shutdown", lambda ctx: order.append(f"sync1:{threading.current_thread().daemon}"))

    async def async_hook(ctx):
        order.append("async2")

    rig.mgr.add_hook("shutdown", async_hook)
    rig.mgr.add_hook("shutdown", lambda: order.append("bare3"))

    def body(ctx: Context):
        entered.set()
        ctx.cancelled.wait(15)
        order.append("job stopped")

    rig.submit(body, "Working")
    await wait_event(entered)
    quit_ = Quit()

    def then():
        order.append("exit")
        quit_()

    rig.mgr.begin_quit(then)
    await quit_.wait()
    assert order == ["job stopped", "sync1:True", "async2", "bare3", "exit"]
    assert rig.host.of_kind("error") == [], "hooks add no output on success"


async def test_shutdown_hooks_run_even_with_nothing_running(make_rig):
    rig = make_rig()
    order = []
    rig.mgr.add_hook("shutdown", lambda: order.append("hook"))
    quit_ = Quit()
    rig.mgr.begin_quit(lambda: (order.append("exit"), quit_()))
    await quit_.wait()
    assert order == ["hook", "exit"]


async def test_a_hanging_shutdown_hook_is_bounded_by_the_grace_and_the_next_one_still_runs(make_rig):
    rig = make_rig(quit_grace=0.2)
    release = make_gate()
    order = []

    def hangs():
        release.wait(15)

    async def async_hangs():
        await asyncio.Event().wait()

    rig.mgr.add_hook("shutdown", hangs)
    rig.mgr.add_hook("shutdown", async_hangs)
    rig.mgr.add_hook("shutdown", lambda: order.append("third ran"))
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await quit_.wait()
    assert order == ["third ran"] and len(quit_.calls) == 1
    assert 0.35 <= quit_.calls[0] < 6.0, quit_.calls
    release.set()
    join_job_threads()


async def test_a_failing_shutdown_hook_is_dropped_and_the_exit_proceeds(make_rig):
    rig = make_rig()
    order = []

    def broken():
        raise RuntimeError("shutdown failure")

    rig.mgr.add_hook("shutdown", broken)
    rig.mgr.add_hook("shutdown", lambda: order.append("next"))
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await quit_.wait()
    assert order == ["next"] and len(quit_.calls) == 1
    assert rig.host.of_kind("error") == [] and rig.host.log_lines() == []


async def test_double_quit_with_hanging_shutdown_hooks_and_a_stuck_job_exits_once_and_fast(make_rig):
    rig = make_rig(quit_grace=2.0)
    entered, release = threading.Event(), make_gate()

    def hang_hook():
        release.wait(15)

    def deaf(ctx: Context):
        entered.set()
        release.wait(15)

    rig.mgr.add_hook("shutdown", hang_hook)
    rig.mgr.add_hook("shutdown", hang_hook)
    rig.submit(deaf, "Deaf")
    await wait_event(entered)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    rig.mgr.begin_quit(quit_)
    await quit_.wait()
    release.set()
    join_job_threads()
    assert len(quit_.calls) == 1, "request_exit exactly once"
    assert quit_.calls[0] < 1.0, f"a second quit must not wait for the hooks ({quit_.calls[0]:.2f}s of grace 2.0)"


async def test_a_second_quit_during_the_hook_phase_exits_at_once_and_skips_the_remaining_hooks(make_rig):
    rig = make_rig(quit_grace=30.0)
    entered, release = threading.Event(), make_gate()
    ran = []

    def first_hook():
        entered.set()
        release.wait(15)

    rig.mgr.add_hook("shutdown", first_hook)
    rig.mgr.add_hook("shutdown", lambda: ran.append("second hook"))
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await wait_event(entered)
    assert quit_.calls == []
    rig.mgr.begin_quit(quit_)
    assert len(quit_.calls) == 1 and quit_.calls[0] < 5.0
    release.set()
    join_job_threads()
    assert ran == [] and len(quit_.calls) == 1


async def test_a_double_quit_with_a_hanging_hook_and_no_job_exits_once(make_rig):
    rig = make_rig(quit_grace=30.0)
    entered, release = threading.Event(), make_gate()

    def hang():
        entered.set()
        release.wait(15)

    rig.mgr.add_hook("shutdown", hang)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await wait_event(entered)
    rig.mgr.begin_quit(quit_)
    release.set()
    join_job_threads()
    assert len(quit_.calls) == 1


async def test_close_does_not_run_the_shutdown_hooks(make_rig):
    rig = make_rig()
    ran = []
    rig.mgr.add_hook("shutdown", lambda: ran.append(1))
    rig.mgr.close()
    assert ran == [] and job_threads() == []


async def test_shutdown_hook_jobs_are_named_shutdown_and_run_on_their_lane(make_rig):
    rig = make_rig()
    seen = []

    async def async_hook(ctx):
        seen.append((ctx.job.label, ctx.job.kind, ctx.job.lane))

    def sync_hook(ctx):
        seen.append((ctx.job.label, ctx.job.kind, ctx.job.lane))

    rig.mgr.add_hook("shutdown", sync_hook)
    rig.mgr.add_hook("shutdown", async_hook)
    quit_ = Quit()
    rig.mgr.begin_quit(quit_)
    await quit_.wait()
    assert seen == [("shutdown", "shutdown", "thread"), ("shutdown", "shutdown", "loop")]
