"""P2.2 / P2.3: the job runner (JobManager) on a fake host: lanes, state machine, events, errors, stop, abandon, waits."""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

import pytest

from cli_interface import jobs as jobs_module
from cli_interface import outcome as outcome_module
from cli_interface.capture import CAPTURE
from cli_interface.context import Context, JobCancelled
from cli_interface.events import validate_event
from cli_interface.jobs import Job, JobSpec, SpinnerRefs
from helpers import make_gate, wait_event


def has_runner_frames(trace: str) -> bool:
    return any(f'File "{m.__file__}"' in trace for m in (jobs_module, outcome_module))


def job_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name.startswith("cli-interface-job-")]


def join_job_threads(timeout: float = 10.0) -> None:
    for t in job_threads():
        t.join(timeout)
    assert job_threads() == []


class Probe:
    """Records what a job body saw, and gates it."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = make_gate()
        self.finished = threading.Event()
        self.seen: dict[str, Any] = {}


# --------------------------------------------------------------------------- inline lane

async def test_an_inline_job_completes_inside_submit_without_a_thread_or_a_spinner(make_rig):
    rig = make_rig()
    ran = []
    job = rig.submit(lambda: ran.append(threading.current_thread()) or "done", "Plain")
    assert isinstance(job, Job) and job.state == "done" and job.outcome == "ok" and job.lane == "inline"
    assert ran == [threading.current_thread()]
    assert rig.mgr.state == "idle" and not rig.mgr.busy and rig.mgr.current is None
    assert rig.mgr.completed == 1 and rig.host.lines() == ["Executed: Plain → done"]
    assert rig.host.spinner_calls == [] and rig.host.changes == ["Plain", None]
    assert job_threads() == []


async def test_job_attributes(make_rig):
    rig = make_rig()
    first = rig.submit(lambda: None, "One", path=("G", "One"))
    second = rig.submit(lambda: None, "Two")
    assert (first.id, second.id) == (1, 2) and first.label == "One" and first.path == ("G", "One")
    assert first.kind == "command" and first.cancellable is False and first.abandoned is False
    assert isinstance(first.cancelled, threading.Event) and not first.cancelled.is_set()
    assert first.cancelled is not second.cancelled, "a new Event per job"
    assert first.started is not None and first.ended is not None and first.ended >= first.started
    assert first.error is None and "One" in repr(first)


async def test_the_return_value_events_come_before_the_result(make_rig):
    rig = make_rig()
    rig.submit(lambda: {"a": 1}, "Dict")
    rig.submit(lambda: [{"x": 1}], "Rows")
    rig.submit(lambda: "line1\nline2", "Multi")
    rig.submit(lambda: "short", "Short")
    rig.submit(lambda: None, "Nothing")
    assert rig.host.kinds() == ["json", "result", "table", "result", "text", "result", "result", "result"]
    assert [e["summary"] for e in rig.host.of_kind("result")] == [None, None, None, "short", None]
    assert all(e["job"] in (1, 2, 3, 4, 5) for e in rig.host.events)
    assert all(validate_event(e) == [] for e in rig.host.events)


async def test_inline_jobs_have_busy_state_capture_and_traceback_just_like_threaded_ones(make_rig):
    rig = make_rig(capture=True)
    seen = {}

    def body():
        seen["busy"] = rig.mgr.busy
        seen["state"] = rig.mgr.state
        print("inline print")
        raise RuntimeError("inline boom")

    job = rig.submit(body, "Inline")
    assert seen == {"busy": True, "state": "running"} and job.outcome == "error" and job.error == "inline boom"
    assert [(e["kind"], e.get("job")) for e in rig.host.events if e["kind"] == "text"] == [("text", 1)]
    assert rig.host.events[0]["text"] == "inline print" and rig.host.events[0]["stream"] == "stdout"
    err = rig.host.of_kind("error")[0]
    assert err["label"] == "Inline" and err["message"] == "inline boom" and err["exc_type"] == "RuntimeError"
    assert err["traceback"].startswith("Traceback") and "inline boom" in err["traceback"]


async def test_inline_jobs_run_on_the_ui_thread_and_a_prompt_value_is_bound(make_rig):
    rig = make_rig()
    seen = []
    rig.submit(lambda value: seen.append((value, threading.get_ident())), "Typed", value="typed")
    assert seen == [("typed", threading.get_ident())]


# --------------------------------------------------------------------------- thread lane

async def test_a_thread_job_runs_on_a_named_daemon_thread_and_ends_with_the_result(make_rig):
    rig = make_rig()
    probe = Probe()

    def body(ctx: Context):
        t = threading.current_thread()
        probe.seen.update(name=t.name, daemon=t.daemon, ident=t.ident, ctx=ctx)
        probe.started.set()
        probe.release.wait(15)
        return "result-text"

    mark = rig.mgr.mark()
    job = rig.submit(body, "Threaded")
    assert job.state == "running" and job.lane == "thread" and rig.mgr.busy and rig.mgr.current is job
    await wait_event(probe.started)
    assert probe.seen["name"] == f"cli-interface-job-{job.id}" and probe.seen["daemon"] is True
    assert probe.seen["ident"] != threading.get_ident()
    assert isinstance(probe.seen["ctx"], Context) and probe.seen["ctx"].job is job
    assert rig.host.spinner_calls == [("acquire", "Threaded")]
    probe.release.set()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert job.outcome == "ok" and job.state == "done" and rig.host.lines() == ["Executed: Threaded → result-text"]
    assert rig.host.spinner_calls[-1][0] == "release" and rig.host.flushes >= 1
    join_job_threads()


async def test_a_thread_job_orders_log_print_panel_and_value_events_with_the_result_last(make_rig):
    rig = make_rig(capture=True)

    def body(ctx: Context):
        ctx.log("first")
        print("printed")
        ctx.panel.text("panel text")
        sys.stderr.write("to stderr\n")
        ctx.status("working")
        return {"answer": 42}

    await rig.run(body, "Ordered")
    assert [(e["kind"], e.get("msg") or e.get("text") or e.get("label") or "") for e in rig.host.events] == [
        ("log", "first"), ("text", "printed"), ("text", "panel text"), ("text", "to stderr"),
        ("progress", "working"), ("json", ""), ("result", "Ordered"),
    ]
    assert [e["stream"] for e in rig.host.of_kind("text")] == ["stdout", None, "stderr"]
    assert {e["job"] for e in rig.host.events} == {1}


async def test_a_partial_last_line_is_flushed_ahead_of_the_result_in_every_lane(make_rig):
    rig = make_rig(capture=True)

    def inline():
        sys.stdout.write("inline tail")
        return "r"

    def threaded(ctx: Context):
        sys.stdout.write("thread tail")
        return "r"

    async def looped(ctx: Context):
        sys.stderr.write("loop tail")
        return "r"

    for fn, label in ((inline, "I"), (threaded, "T"), (looped, "L")):
        await rig.run(fn, label)
    assert rig.host.kinds() == ["text", "result"] * 3
    assert [e["text"] for e in rig.host.of_kind("text")] == ["inline tail", "thread tail", "loop tail"]
    assert [e["stream"] for e in rig.host.of_kind("text")] == ["stdout", "stdout", "stderr"]


async def test_the_job_context_is_visible_to_the_body_but_not_to_threads_it_spawns(make_rig):
    rig = make_rig(capture=True)

    def body(ctx: Context):
        t = threading.Thread(target=lambda: print("from grandchild"))
        t.start()
        t.join(10)
        print("from the job")

    await rig.run(body, "Spawner")
    by_text = {e["text"]: e for e in rig.host.of_kind("text")}
    assert by_text["from the job"]["job"] == 1
    assert "job" not in by_text["from grandchild"], "the spawned thread's output is app-level"


async def test_a_context_is_passed_in_its_own_slot_beside_the_prompt_value(make_rig):
    rig = make_rig()
    got = []
    await rig.run(lambda ctx, v: got.append((type(ctx).__name__, v)), "A", value="typed")
    await rig.run(lambda v, ctx: got.append((v, type(ctx).__name__)), "B", value="typed")
    assert got == [("Context", "typed"), ("typed", "Context")]


async def test_a_command_item_style_spec_runs_in_a_thread_without_a_context_parameter(make_rig):
    rig = make_rig()
    names = []
    job = await rig.run(lambda: names.append(threading.current_thread().name), "Cmd", threaded=True)
    assert job.lane == "thread" and names == [f"cli-interface-job-{job.id}"]


async def test_a_thread_job_that_raises_gives_an_error_event_without_runner_frames(make_rig):
    rig = make_rig()

    def body(ctx: Context):
        raise ValueError("bad input")

    job = await rig.run(body, "Raiser")
    err = rig.host.of_kind("error")[0]
    assert job.outcome == "error" and job.error == "bad input"
    assert (err["label"], err["message"], err["exc_type"]) == ("Raiser", "bad input", "ValueError")
    assert "ValueError: bad input" in err["traceback"] and not has_runner_frames(err["traceback"])
    assert rig.host.kinds() == ["error"], "no result event after an error"
    assert validate_event(err) == []


async def test_system_exit_in_a_job_is_an_error_not_an_exit(make_rig):
    rig = make_rig()

    def body(ctx: Context):
        raise SystemExit("leave")

    job = await rig.run(body, "Quitter")
    assert job.outcome == "error" and rig.host.of_kind("error")[0]["exc_type"] == "SystemExit"


async def test_a_wrong_arity_prompt_action_is_a_job_error_not_a_crash(make_rig):
    rig = make_rig()
    job = rig.submit(lambda: None, "NoArg", value="unexpected")
    assert job.outcome == "error" and "positional argument" in rig.host.of_kind("error")[0]["message"]


# --------------------------------------------------------------------------- loop lane

async def test_an_async_job_runs_on_the_ui_loop_with_capture_and_a_spinner(make_rig):
    rig = make_rig(capture=True)
    seen = {}

    async def body(ctx: Context):
        seen["thread"] = threading.get_ident()
        seen["task"] = asyncio.current_task().get_name()
        print("async print")
        ctx.log("async log")
        await asyncio.sleep(0)
        return 7

    job = await rig.run(body, "Async")
    assert job.lane == "loop" and seen["thread"] == rig.host.ui_ident
    assert seen["task"].startswith("cli-interface-job-")
    assert rig.host.lines() == ["async print", "async log", "Executed: Async → 7"]
    assert rig.host.spinner_calls[0] == ("acquire", "Async") and rig.host.spinner_calls[-1][0] == "release"
    assert job_threads() == []


async def test_an_async_action_without_a_context_parameter_is_awaited_too(make_rig):
    rig = make_rig()

    async def body():
        await asyncio.sleep(0)
        return "awaited"

    job = await rig.run(body, "Legacy async")
    assert job.lane == "loop" and rig.host.lines() == ["Executed: Legacy async → awaited"]


async def test_a_sync_function_returning_an_awaitable_has_it_awaited(make_rig):
    rig = make_rig()

    async def inner():
        await asyncio.sleep(0)
        return {"k": "v"}

    job = await rig.run(lambda: inner(), "Returns coroutine")
    assert job.lane == "inline" and job.outcome == "ok"
    assert rig.host.kinds() == ["json", "result"] and rig.host.of_kind("json")[0]["data"] == {"k": "v"}


async def test_an_async_job_that_raises_is_an_error(make_rig):
    rig = make_rig()

    async def body():
        raise KeyError("gone")

    job = await rig.run(body, "AsyncBoom")
    err = rig.host.of_kind("error")[0]
    assert job.outcome == "error" and err["exc_type"] == "KeyError" and not has_runner_frames(err["traceback"])


# --------------------------------------------------------------------------- secrets

async def test_a_secret_job_masks_every_output_path_and_hides_the_return_value(make_rig):
    rig = make_rig(capture=True)

    def body(ctx: Context, value):
        ctx.log(f"using {value}")
        print(f"printing {value}")
        sys.stderr.write(f"err {value}\n")
        ctx.panel.text(f"text {value}")
        ctx.panel.json({"k": value})
        ctx.status(f"status {value}")
        ctx.progress(1, 2, f"label {value}")
        return f"returned {value}"

    await rig.run(body, "Login hunter2", value="hunter2", secret=True)
    blob = repr(rig.host.events)
    assert "hunter2" not in blob and "***" in blob
    result = rig.host.of_kind("result")[0]
    assert result["summary"] is None and result["label"] == "Login ***"
    assert rig.host.kinds().count("json") == 1, "only the job's own json; none for the return value"
    assert "returned" not in blob


async def test_a_secret_job_error_has_the_secret_masked_in_message_traceback_and_chain(make_rig):
    rig = make_rig()

    def body(ctx: Context, value):
        api_key = value
        try:
            raise ConnectionError(f"refused for {api_key}")
        except ConnectionError as cause:
            raise RuntimeError(f"login failed ({value})") from cause

    job = await rig.run(body, "Login", value="hunter2", secret=True)
    err = rig.host.of_kind("error")[0]
    assert "hunter2" not in repr(rig.host.events) and "hunter2" not in repr(job)
    assert err["message"] == "login failed (***)" and "refused for ***" in err["traceback"]


# --------------------------------------------------------------------------- busy, stop, abandon

async def test_a_second_submit_while_busy_is_rejected_with_one_warning_and_no_state_change(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    first = rig.submit(slow, "Slow")
    await wait_event(probe.started)
    assert rig.mgr.submit(JobSpec("Other", lambda: None)) is None
    assert rig.host.log_lines() == [("WARNING", "Busy: Slow is running (type stop to stop it)")]
    assert rig.mgr.current is first and rig.mgr.state == "running" and rig.mgr.completed == 0
    assert rig.mgr.ensure_idle() is False
    assert len(rig.host.log_lines()) == 2
    probe.release.set()
    await rig.mgr.wait_idle(since=0, jobs=1)
    assert rig.mgr.ensure_idle() is True and len(rig.host.log_lines()) == 2, "idle: no warning"


async def test_the_busy_warning_while_stopping_says_stopping(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    rig.submit(slow, "Slow", cancellable=True)
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    assert rig.mgr.state == "cancelling"
    assert rig.mgr.submit(JobSpec("Other", lambda: None)) is None
    assert rig.host.log_lines()[-1] == ("WARNING", "Busy: Slow is stopping")
    probe.release.set()
    await rig.mgr.wait_idle(since=0, jobs=1)


async def test_stop_when_nothing_runs_says_so_at_info_level(make_rig):
    rig = make_rig()
    rig.mgr.request_cancel()
    assert rig.host.log_lines() == [("INFO", "Nothing is running")]
    rig.mgr.request_cancel(source="quit")
    assert len(rig.host.log_lines()) == 1, "a quit-time cancel with nothing running is silent"


async def test_stop_cancels_a_cancellable_job_which_ends_cancelled(make_rig):
    rig = make_rig()
    probe = Probe()

    def cooperative(ctx: Context):
        probe.started.set()
        probe.seen["cancelled_flag"] = ctx.cancelled.wait(15)
        ctx.check_cancelled()
        return "not reached"

    mark = rig.mgr.mark()
    job = rig.submit(cooperative, "Coop", cancellable=True)
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    assert job.state == "cancelling" and rig.mgr.state == "cancelling" and job.cancelled.is_set()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert probe.seen["cancelled_flag"] is True and job.outcome == "cancelled" and not job.abandoned
    assert rig.host.lines() == ["Cancelled: Coop"]
    assert rig.host.of_kind("result")[0]["status"] == "cancelled" and rig.mgr.state == "idle"


async def test_a_body_that_returns_normally_after_a_cancel_request_is_ok(make_rig):
    rig = make_rig()
    probe = Probe()

    def polite(ctx: Context):
        probe.started.set()
        ctx.cancelled.wait(15)
        return "finished early"

    mark = rig.mgr.mark()
    job = rig.submit(polite, "Polite", cancellable=True)
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert job.outcome == "ok" and rig.host.lines()[-1] == "Executed: Polite → finished early"


async def test_stop_cancels_an_async_job_at_its_next_await(make_rig):
    rig = make_rig()
    started = asyncio.Event()

    async def forever(ctx: Context):
        started.set()
        await asyncio.Event().wait()

    mark = rig.mgr.mark()
    job = rig.submit(forever, "Forever", cancellable=True)
    await asyncio.wait_for(started.wait(), 10)
    rig.mgr.request_cancel()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert job.outcome == "cancelled" and rig.host.lines() == ["Cancelled: Forever"]


async def test_first_stop_on_a_non_cancellable_job_only_warns_and_leaves_the_flag_clear(make_rig):
    rig = make_rig()
    probe = Probe()

    def stubborn(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    job = rig.submit(stubborn, "Stubborn")
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    assert rig.host.log_lines() == [("WARNING", "Stubborn cannot be stopped cleanly; type stop again to abandon it")]
    assert rig.mgr.state == "running" and not job.cancelled.is_set() and job.outcome is None
    probe.release.set()
    await rig.mgr.wait_idle(since=0, jobs=1)
    assert job.outcome == "ok"


async def test_second_stop_abandons_the_job_and_its_later_output_is_dropped(make_rig):
    rig = make_rig(capture=True)
    probe = Probe()
    base_refs = CAPTURE.refs

    def stubborn(ctx: Context):
        probe.started.set()
        probe.release.wait(15)
        ctx.log("late log")
        print("late print")
        ctx.panel.text("late panel")
        probe.finished.set()
        return "late result"

    job = rig.submit(stubborn, "Stubborn")
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    assert job.abandoned and job.outcome == "abandoned" and job.state == "done" and job.cancelled.is_set()
    assert rig.mgr.state == "idle" and rig.mgr.current is None and rig.mgr.completed == 1
    assert rig.host.log_lines()[-1] == (
        "WARNING", "Abandoned: Stubborn (it did not stop; its output is now ignored)"
    )
    assert rig.host.spinner_calls[-1][0] == "release"
    assert CAPTURE.refs == base_refs + 1, "an abandoned thread keeps the capture installed until it exits"
    before = list(rig.host.events)
    probe.release.set()
    await wait_event(probe.finished)
    join_job_threads()
    assert rig.host.events == before, "nothing the abandoned job does reaches the host"
    assert rig.host.of_kind("result") == [] and CAPTURE.refs == base_refs
    other = await rig.run(lambda: "next", "Next")
    assert other.outcome == "ok", "a new job is accepted at once"


async def test_a_cancelled_but_unresponsive_job_is_abandoned_by_the_second_stop(make_rig):
    rig = make_rig()
    probe = Probe()

    def deaf(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    job = rig.submit(deaf, "Deaf", cancellable=True)
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    assert job.state == "cancelling"
    rig.mgr.request_cancel()
    assert job.abandoned and rig.mgr.state == "idle"
    probe.release.set()
    join_job_threads()


async def test_stop_from_the_quit_source_cancels_any_job_without_warnings(make_rig):
    rig = make_rig()
    probe = Probe()

    def waits(ctx: Context):
        probe.started.set()
        probe.release.wait(15)
        return ctx.cancelled.is_set()

    mark = rig.mgr.mark()
    job = rig.submit(waits, "Waits")
    await wait_event(probe.started)
    rig.mgr.request_cancel(source="quit")
    assert job.cancelled.is_set() and rig.host.log_lines() == []
    probe.release.set()
    await rig.mgr.wait_idle(since=mark, jobs=1)
    assert rig.host.of_kind("result")[0]["summary"] == "True"


async def test_an_abandoned_async_job_is_cancelled_and_the_manager_is_free(make_rig):
    rig = make_rig()
    started = asyncio.Event()

    async def swallows_cancel(ctx: Context):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.Event().wait()

    job = rig.submit(swallows_cancel, "Swallower", cancellable=True)
    await asyncio.wait_for(started.wait(), 10)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    assert job.abandoned and job.outcome == "abandoned"
    assert (await rig.run(lambda: 1, "After")).outcome == "ok"


async def test_an_abandoned_async_job_that_ignores_cancellation_is_swallowed_even_though_it_runs_on_the_ui_thread(
    make_rig, capsys
):
    rig = make_rig(capture=True)
    started, resume, done = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def stubborn(ctx: Context):
        started.set()
        while not resume.is_set():
            try:
                await resume.wait()
            except asyncio.CancelledError:
                continue
        print("late print from the abandoned job")
        sys.stderr.write("late stderr from the abandoned job\n")
        ctx.log("late log")
        done.set()

    job = rig.submit(stubborn, "Stubborn", cancellable=True)
    await asyncio.wait_for(started.wait(), 10)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    assert job.abandoned
    before, _ = list(rig.host.events), capsys.readouterr()
    resume.set()
    await asyncio.wait_for(done.wait(), 10)
    seen = capsys.readouterr()
    assert "late" not in seen.out + seen.err, "an abandoned job must not reach the terminal, wherever it runs"
    assert rig.host.events == before


# --------------------------------------------------------------------------- the wait API

async def test_wait_idle_with_since_and_jobs_cannot_return_before_the_job_even_if_called_first(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    mark = rig.mgr.mark()
    waiter = asyncio.ensure_future(rig.mgr.wait_idle(since=mark, jobs=1, timeout=10))
    await asyncio.sleep(0)
    assert not waiter.done(), "nothing has completed yet, although the manager is idle"
    rig.submit(slow, "Slow")
    await wait_event(probe.started)
    await asyncio.sleep(0)
    assert not waiter.done()
    probe.release.set()
    await waiter
    assert rig.mgr.completed == 1


async def test_wait_idle_returns_at_once_when_idle_and_flushes_the_host(make_rig):
    rig = make_rig()
    await rig.mgr.wait_idle()
    assert rig.host.flushes == 1
    await rig.mgr.wait_idle(since=rig.mgr.mark(), jobs=0)


async def test_mark_counts_completed_jobs_including_abandoned_and_failed_ones(make_rig):
    rig = make_rig()
    assert rig.mgr.mark() == 0
    rig.submit(lambda: None, "ok")
    rig.submit(lambda: 1 / 0, "bad")
    assert rig.mgr.mark() == rig.mgr.completed == 2


async def test_wait_idle_timeout_raises_with_a_state_dump_naming_the_job_and_its_thread(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    rig.submit(slow, "Slow job")
    await wait_event(probe.started)
    with pytest.raises(TimeoutError) as info:
        await rig.mgr.wait_idle(timeout=0.2)
    text = str(info.value)
    assert "state=running" in text and "'Slow job'" in text and "lane=thread" in text
    assert "thread stack" in text and "wait" in text


async def test_the_timeout_dump_repr_and_abandoned_line_never_show_a_secret(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context, value):
        probe.started.set()
        probe.release.wait(15)

    job = rig.submit(slow, "Login", value="hunter2-pw", secret=True)
    await wait_event(probe.started)
    with pytest.raises(TimeoutError) as info:
        await rig.mgr.wait_idle(timeout=0.2)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    shown = str(info.value) + repr(job) + str(job) + repr(rig.host.events)
    assert "hunter2-pw" not in shown


async def test_wait_until_is_rechecked_on_state_changes_and_times_out_with_a_dump(make_rig):
    rig = make_rig()
    probe = Probe()

    def slow(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    rig.submit(slow, "Slow", cancellable=True)
    await wait_event(probe.started)
    waiter = asyncio.ensure_future(rig.mgr.wait_until(lambda m: m.state == "cancelling", timeout=10))
    await asyncio.sleep(0)
    assert not waiter.done()
    rig.mgr.request_cancel()
    await waiter
    with pytest.raises(TimeoutError, match="state=cancelling"):
        await rig.mgr.wait_until(lambda m: m.state == "idle", timeout=0.1)
    probe.release.set()
    await rig.mgr.wait_idle(since=0, jobs=1)


async def test_waits_raise_after_close_instead_of_hanging(make_rig):
    rig = make_rig()
    rig.mgr.close()
    with pytest.raises(RuntimeError):
        await rig.mgr.wait_idle(since=1, jobs=1, timeout=0.5)
    with pytest.raises(RuntimeError):
        await rig.mgr.wait_until(lambda m: False, timeout=0.5)


async def test_close_wakes_a_pending_waiter(make_rig):
    rig = make_rig()
    waiter = asyncio.ensure_future(rig.mgr.wait_until(lambda m: m.completed > 5, timeout=10))
    await asyncio.sleep(0)
    rig.mgr.close()
    with pytest.raises(RuntimeError):
        await waiter


# --------------------------------------------------------------------------- close

async def test_close_abandons_a_running_job_quietly_and_never_waits_for_its_thread(make_rig):
    rig = make_rig()
    probe = Probe()

    def noncooperative(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    job = rig.submit(noncooperative, "Hang")
    await wait_event(probe.started)
    rig.mgr.close()
    rig.mgr.close()
    assert job.abandoned and job.outcome == "abandoned" and job.cancelled.is_set()
    assert rig.host.log_lines() == [], "no 'Abandoned:' line at teardown"
    assert rig.mgr.submit(JobSpec("late", lambda: None)) is None and rig.host.log_lines() == []
    probe.release.set()
    join_job_threads()


def test_completing_after_the_loop_is_closed_raises_nothing_in_the_thread(thread_errors):
    from jobrig import Rig

    loop = asyncio.new_event_loop()
    probe = Probe()
    holder: dict[str, Any] = {}

    async def setup():
        rig = Rig()
        holder["rig"] = rig

        def body(ctx: Context):
            probe.started.set()
            probe.release.wait(15)
            probe.finished.set()

        holder["job"] = rig.submit(body, "Outlives the loop")
        await wait_event(probe.started)
        rig.mgr.close()
        await asyncio.sleep(0)

    try:
        loop.run_until_complete(setup())
    finally:
        loop.run_until_complete(asyncio.sleep(0))
        loop.close()
    probe.release.set()
    assert probe.finished.wait(10)
    join_job_threads()
    assert thread_errors == []


# --------------------------------------------------------------------------- spinner references

def test_spinner_refs_count_independent_holders_and_report_the_newest_label():
    refs = SpinnerRefs()
    assert refs.count == 0 and refs.label is None
    a = refs.acquire("first")
    b = refs.acquire("second")
    assert refs.count == 2 and refs.label == "second" and a != b
    assert refs.release(b) is True and refs.label == "first"
    assert refs.release(b) is False, "releasing twice is harmless"
    assert refs.release(a) is True and refs.count == 0 and refs.label is None
    assert refs.release(999) is False
    assert refs.acquire() != refs.acquire()


async def test_each_non_inline_job_acquires_and_releases_one_spinner_reference(make_rig):
    rig = make_rig()
    await rig.run(lambda ctx: None, "T")

    async def a():
        return None

    await rig.run(a, "A")
    await rig.run(lambda: None, "I")
    assert rig.host.spinner_calls == [("acquire", "T"), ("release", 1), ("acquire", "A"), ("release", 2)]


async def test_an_abandoned_job_releases_its_spinner_reference(make_rig):
    rig = make_rig()
    probe = Probe()

    def hang(ctx: Context):
        probe.started.set()
        probe.release.wait(15)

    rig.submit(hang, "Hang")
    await wait_event(probe.started)
    rig.mgr.request_cancel()
    rig.mgr.request_cancel()
    assert [c[0] for c in rig.host.spinner_calls] == ["acquire", "release"]
    probe.release.set()
    join_job_threads()


# --------------------------------------------------------------------------- misc contracts

def test_job_cancelled_is_exported_from_context_and_is_an_exception():
    assert issubclass(JobCancelled, Exception)


async def test_unknown_hook_kind_is_rejected_and_a_non_callable_is_ignored(make_rig):
    rig = make_rig()
    with pytest.raises(ValueError):
        rig.mgr.add_hook("sometimes", lambda: None)  # type: ignore[arg-type]
    rig.mgr.add_hook("before", "not callable")  # type: ignore[arg-type]
    rig.mgr.add_hook("shutdown", None)  # type: ignore[arg-type]
    await rig.run(lambda: None, "Fine")
    assert rig.host.lines() == ["Executed: Fine"]


# --------------------------------------------------------------------------- random operation sequences keep the machine consistent

@pytest.mark.parametrize("seed", range(6))
async def test_random_submit_stop_and_release_sequences_never_wedge_the_manager(make_rig, seed):
    import random

    rng = random.Random(seed)
    rig = make_rig(capture=True)
    gates: list[threading.Event] = []
    agates: list[asyncio.Event] = []
    started = 0

    def check() -> None:
        mgr = rig.mgr
        assert mgr.state in ("idle", "running", "cancelling")
        assert mgr.busy == (mgr.current is not None) == (mgr.state != "idle")
        if mgr.current is not None:
            assert mgr.current.state in ("running", "cancelling") and mgr.current.outcome is None

    for _ in range(60):
        op = rng.choice(["thread", "thread", "async", "inline", "release", "stop", "stop", "gap"])
        if op in ("thread", "async", "inline"):
            gate, agate = make_gate(), asyncio.Event()
            gates.append(gate)
            agates.append(agate)
            cancellable = rng.random() < 0.5
            if op == "thread":
                def body(ctx: Context, gate=gate):
                    print("thread output")
                    gate.wait(15)
                    return "t"
            elif op == "async":
                async def body(ctx: Context, agate=agate):
                    print("async output")
                    await agate.wait()
                    return "a"
            else:
                def body(gate=gate):
                    return "i"
            before = rig.mgr.completed
            job = rig.mgr.submit(JobSpec(f"{op}{started}", body, cancellable=cancellable))
            if job is None:
                assert rig.mgr.busy and rig.mgr.completed == before
            else:
                started += 1
        elif op == "release":
            for gate in gates:
                gate.set()
            for agate in agates:
                agate.set()
        elif op == "stop":
            rig.mgr.request_cancel()
        for _ in range(3):
            await asyncio.sleep(0)
        check()
    for gate in gates:
        gate.set()
    for agate in agates:
        agate.set()
    await rig.mgr.wait_idle(timeout=15)
    check()
    assert rig.mgr.state == "idle" and rig.mgr.completed == started and started > 5
    acquires = [c for c in rig.host.spinner_calls if c[0] == "acquire"]
    releases = [c for c in rig.host.spinner_calls if c[0] == "release"]
    assert len(acquires) == len(releases)
    join_job_threads()
    assert CAPTURE.refs == 1, "only the rig's own reference is left once every thread has ended"
    for event in rig.host.events:
        assert validate_event(event) == [], event
