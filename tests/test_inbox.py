"""F2: the thread-safe, bounded panel inbox (PanelInbox) and CLIApp.push_log."""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest

import cli_interface.log_handler as log_handler
from cli_interface import ShortcutConflictWarning
from cli_interface.app import CLIApp, attach_logging
from cli_interface.log_handler import LogAttachment, PanelInbox
from helpers import (
    SIZE, StubApp, StubSink, join_all, leaf, menu, panel_lines, panel_text, run_threads, wait_for,
)


@pytest.fixture
async def env():
    """(stub app, open inbox, loop) with the inbox opened on the test's running loop (the 'UI thread')."""
    sink = StubSink()
    inbox = PanelInbox(sink, maxlen=100_000)
    loop = asyncio.get_running_loop()
    inbox.open(loop)
    return sink, inbox, loop


def make_inbox(maxlen=None):
    sink = StubSink()
    return sink, PanelInbox(sink, maxlen)


# --------------------------------------------------------------------------- ordering and delivery

async def test_ui_thread_put_is_written_immediately(env):
    sink, inbox, _ = env
    inbox.put("ui-direct", "ERROR")
    assert sink.out == [("ui-direct", "ERROR")]


async def test_background_put_arrives_once_the_loop_runs(env):
    sink, inbox, _ = env
    run_threads(lambda: inbox.put("from-thread"))
    await wait_for(lambda: sink.messages == ["from-thread"])


async def test_fifo_per_producer_across_threads(env):
    sink, inbox, _ = env
    run_threads(*[
        (lambda k=k: [inbox.put(f"T{k}-{i:04d}") for i in range(300)]) for k in range(3)
    ])
    await wait_for(lambda: len(sink.out) == 900)
    for k in range(3):
        seq = [int(m.split("-")[1]) for m in sink.messages if m.startswith(f"T{k}-")]
        assert seq == list(range(300))


async def test_stress_threads_plus_ui_puts_no_loss_dup_or_reorder(env):
    sink, inbox, _ = env
    producers, per = 8, 500
    threads = [
        threading.Thread(target=lambda k=k: [inbox.put(f"{k}:{i}") for i in range(per)], daemon=True)
        for k in range(producers)
    ]
    for t in threads:
        t.start()
    for i in range(200):
        inbox.put(f"ui:{i}")
        await asyncio.sleep(0)
    join_all(threads)
    total = producers * per + 200
    await wait_for(lambda: len(sink.out) >= total, timeout=15)
    msgs = sink.messages
    assert len(msgs) == total and len(set(msgs)) == total
    for k in [*range(producers), "ui"]:
        seq = [int(m.split(":")[1]) for m in msgs if m.split(":")[0] == str(k)]
        assert seq == sorted(seq), f"producer {k} reordered"


async def test_no_lost_wakeups_across_many_small_bursts(env):
    sink, inbox, _ = env
    for i in range(100):
        run_threads(lambda i=i: inbox.put(f"burst-{i}"))
        await wait_for(lambda i=i: f"burst-{i}" in sink.messages, timeout=5, what=f"burst-{i}")


async def test_ui_put_with_backlog_drains_backlog_first_without_duplicates(env):
    sink, inbox, _ = env
    run_threads(lambda: [inbox.put(f"bg{i}") for i in range(5)])
    assert sink.out == [], "loop is not running, so nothing has been written yet"
    inbox.put("ui-after")
    assert sink.messages == [f"bg{i}" for i in range(5)] + ["ui-after"]
    for _ in range(5):
        await asyncio.sleep(0.01)
    assert sink.messages == [f"bg{i}" for i in range(5)] + ["ui-after"]


async def test_default_cap_delivers_ten_thousand_records():
    sink, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    run_threads(lambda: [inbox.put(f"d{i}") for i in range(10_000)])
    await wait_for(lambda: len(sink.out) == 10_000, timeout=20)
    assert inbox.dropped == 0
    assert sink.messages[0] == "d0" and sink.messages[-1] == "d9999"


# --------------------------------------------------------------------------- never blocks

async def test_background_puts_complete_while_the_loop_thread_is_blocked(env):
    sink, inbox, _ = env
    elapsed: list[float] = []

    def producer():
        t0 = time.perf_counter()
        for i in range(10_000):
            inbox.put(f"b{i}")
        elapsed.append(time.perf_counter() - t0)

    t = threading.Thread(target=producer, daemon=True)
    t.start()
    t.join(timeout=10)  # blocks the loop thread; a put that waited for the loop would deadlock here
    assert not t.is_alive(), "put() blocked on the (blocked) event loop"
    assert elapsed and elapsed[0] < 2.0, elapsed
    await wait_for(lambda: len(sink.out) == 10_000, timeout=20)


# --------------------------------------------------------------------------- bounded

@pytest.mark.parametrize("cap, effective", [(100, 100), (5, 5), (1, 1), (0, 1), (-5, 1)])
async def test_overflow_keeps_newest_records_plus_one_notice_placed_first(cap, effective):
    sink, inbox = make_inbox(cap)
    inbox.open(asyncio.get_running_loop())
    total = 1000
    t = threading.Thread(target=lambda: [inbox.put(f"r{i}") for i in range(total)], daemon=True)
    t.start()
    t.join(timeout=10)  # loop blocked meanwhile
    assert not t.is_alive()
    await wait_for(lambda: len(sink.out) == effective + 1, what="records + notice")
    dropped = total - effective
    assert inbox.dropped == dropped
    notices = [(m, lv) for m, lv in sink.out if "dropped" in m]
    assert notices == [(f"{dropped} log record(s) dropped (UI busy)", "WARNING")]
    assert sink.out[0] == notices[0]
    records = [m for m in sink.messages if m.startswith("r")]
    assert records == [f"r{i}" for i in range(total - effective, total)]


async def test_cap_is_read_from_the_module_constant_when_not_given(monkeypatch):
    monkeypatch.setattr(log_handler, "_INBOX_MAXLEN", 25)
    sink, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    t = threading.Thread(target=lambda: [inbox.put(f"m{i}") for i in range(200)], daemon=True)
    t.start()
    t.join(timeout=10)
    await wait_for(lambda: len(sink.out) == 26)
    assert [m for m in sink.messages if m.startswith("m")] == [f"m{i}" for i in range(175, 200)]
    assert inbox.dropped == 175


async def test_overflow_before_open_is_bounded_and_reported_on_open():
    sink, inbox = make_inbox(3)
    for i in range(5):
        inbox.put(f"pre{i}")  # state 'new': UI-thread puts are enqueued too
    run_threads(lambda: inbox.put("pre-bg"))
    assert sink.out == []
    inbox.open(asyncio.get_running_loop())
    await wait_for(lambda: len(sink.out) == 4)
    assert sink.messages == ["3 log record(s) dropped (UI busy)", "pre3", "pre4", "pre-bg"]
    assert inbox.dropped == 3


async def test_dropped_count_is_cumulative_and_each_notice_reports_only_new_drops():
    sink, inbox = make_inbox(10)
    inbox.open(asyncio.get_running_loop())

    def burst(tag):
        t = threading.Thread(target=lambda: [inbox.put(f"{tag}{i}") for i in range(30)], daemon=True)
        t.start()
        t.join(timeout=10)

    burst("a")
    await wait_for(lambda: any(m.startswith("a29") for m in sink.messages))
    burst("b")
    await wait_for(lambda: any(m.startswith("b29") for m in sink.messages))
    notices = [m for m in sink.messages if "dropped" in m]
    assert notices == ["20 log record(s) dropped (UI busy)", "20 log record(s) dropped (UI busy)"]
    assert inbox.dropped == 40


# --------------------------------------------------------------------------- lifecycle

async def test_puts_before_open_are_buffered_and_shown_in_order():
    sink, inbox = make_inbox()
    inbox.put("pre-ui-1")
    run_threads(lambda: inbox.put("pre-bg-2"))
    inbox.put("pre-ui-3")
    assert sink.out == []
    inbox.open(asyncio.get_running_loop())
    await wait_for(lambda: len(sink.out) == 3)
    assert sink.messages == ["pre-ui-1", "pre-bg-2", "pre-ui-3"]


async def test_open_twice_is_harmless(env):
    sink, inbox, loop = env
    inbox.open(loop)
    inbox.open(loop)
    inbox.put("after-reopen")
    assert sink.messages == ["after-reopen"]


async def test_put_after_close_is_a_silent_noop_everywhere(unique_logger, handle_errors, thread_errors):
    app, sink = StubApp(), StubSink()
    inbox = PanelInbox(sink)
    app.push_log = inbox.put  # type: ignore[method-assign]
    inbox.open(asyncio.get_running_loop())
    lg = unique_logger()
    attachment = LogAttachment(app, lg)
    inbox.put("before-close")
    inbox.close()
    inbox.close()
    inbox.put("x")
    run_threads(lambda: inbox.put("from-thread"), lambda: lg.info("logger-from-thread"))
    lg.info("logger-from-ui")
    for _ in range(5):
        await asyncio.sleep(0.01)
    assert sink.messages == ["before-close"]
    assert handle_errors == [] and thread_errors == []
    attachment.detach()


async def test_close_is_terminal_open_does_not_revive_it():
    sink, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    inbox.close()
    inbox.open(asyncio.get_running_loop())
    inbox.put("reopen")
    run_threads(lambda: inbox.put("reopen-bg"))
    await asyncio.sleep(0.05)
    assert sink.out == []


async def test_close_discards_queued_records():
    sink, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    t = threading.Thread(target=lambda: [inbox.put(f"q{i}") for i in range(5)], daemon=True)
    t.start()
    t.join(timeout=5)
    inbox.close()
    await asyncio.sleep(0.05)
    assert sink.out == []


async def test_closed_event_loop_makes_the_inbox_close_cleanly():
    dead = asyncio.new_event_loop()
    dead.close()
    sink, inbox = make_inbox()
    inbox.open(dead)  # opened with a loop that is already closed
    errors: list[BaseException] = []

    def producer():
        try:
            inbox.put("a")
            inbox.put("b")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    run_threads(producer)
    assert errors == []
    run_threads(lambda: inbox.put("c"))
    # the RuntimeError closed the inbox for good: a live loop cannot revive it
    inbox.open(asyncio.get_running_loop())
    inbox.put("d")
    await asyncio.sleep(0.05)
    assert sink.out == []


# --------------------------------------------------------------------------- re-entrancy and errors

async def test_reentrant_record_inside_the_sink_is_dropped_on_the_direct_path(env):
    sink, inbox, _ = env
    depth: list[int] = []
    original = sink.emit

    def nested(event):
        depth.append(1)
        if len(depth) < 50:
            inbox.put("nested-" + event["msg"])
        return original(event)

    sink.emit = nested  # type: ignore[method-assign]
    inbox.put("outer")
    assert len(depth) == 1 and sink.messages == ["outer"]


async def test_reentrant_record_inside_the_sink_is_dropped_on_the_scheduled_path(env):
    sink, inbox, _ = env
    depth: list[int] = []
    original = sink.emit

    def nested(event):
        depth.append(1)
        if len(depth) < 50:
            inbox.put("nested-" + event["msg"])
        return original(event)

    sink.emit = nested  # type: ignore[method-assign]
    run_threads(lambda: inbox.put("bg-outer"))
    await wait_for(lambda: sink.messages == ["bg-outer"])
    await asyncio.sleep(0.05)
    assert len(depth) == 1 and sink.messages == ["bg-outer"]


async def test_scheduled_drain_swallows_write_errors_and_keeps_going(env):
    sink, inbox, loop = env
    reported: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    sink.fail = ValueError("boom")
    run_threads(lambda: inbox.put("lost"))
    await wait_for(lambda: sink.failed_attempts == 1, what="the failing write to be attempted")
    sink.fail = None
    run_threads(lambda: inbox.put("kept"))
    await wait_for(lambda: sink.messages == ["kept"])
    assert reported == [], "a write error must not reach asyncio's logger (it would loop back into the handler)"


async def test_direct_path_sink_error_never_reaches_the_caller_or_handle_error(unique_logger, handle_errors):
    app, sink = StubApp(), StubSink()
    inbox = PanelInbox(sink)
    app.push_log = inbox.put  # type: ignore[method-assign]
    inbox.open(asyncio.get_running_loop())
    sink.fail = ValueError("boom")
    inbox.put("x")  # C0-5: no raise on the UI thread
    assert sink.failed_attempts == 1 and inbox.write_errors == 1
    lg = unique_logger()
    attachment = LogAttachment(app, lg)
    lg.info("via logging")
    assert handle_errors == [] and sink.failed_attempts == 2 and inbox.write_errors == 2
    attachment.detach()


# --------------------------------------------------------------------------- CLIApp.push_log (integration)

async def test_push_log_on_the_ui_thread_is_visible_after_a_single_pause(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        app.push_log("ui-record", "WARNING")
        await pilot.pause()
        assert "ui-record" in panel_text(app)


async def test_push_log_from_a_background_thread_appears(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        run_threads(lambda: app.push_log("bg-record", "ERROR"))
        await wait_for(lambda: "bg-record" in panel_text(app))


async def test_records_logged_before_mount_are_shown_after_mount_in_order(make_app):
    app = make_app(leaf("A", "a"))
    app.push_log("pre-ui")
    run_threads(lambda: app.push_log("pre-bg"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        lines = panel_lines(app)
        assert [ln for ln in lines if ln.startswith("pre-")] == ["pre-ui", "pre-bg"]


async def test_logger_attached_before_the_app_runs_buffers_until_mount(make_app, unique_logger, handle_errors):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    attach_logging(app, lg)
    lg.info("logged before app.run")
    async with app.run_test(size=SIZE) as pilot:
        lg.info("logged from UI thread")
        await pilot.pause()
        text = panel_text(app)
        assert "logged before app.run" in text and "logged from UI thread" in text
    assert handle_errors == [] and lg.handlers == []


async def test_logger_records_from_an_action_on_the_ui_thread_are_shown(make_app, unique_logger, handle_errors):
    lg = unique_logger()
    app = make_app(leaf("Do", "d", lambda: lg.info("hello from action")))
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        await pilot.press("d", "enter")
        await pilot.pause()
        assert "hello from action" in panel_text(app)
    assert handle_errors == []


async def test_logger_records_have_timestamp_level_and_logger_name(make_app, unique_logger):
    import re

    lg = unique_logger("fmt")
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        lg.warning("formatted")
        await pilot.pause()
        pattern = rf"\d\d:\d\d:\d\d \[WARNING\] {re.escape(lg.name)}: formatted"
        assert re.search(pattern, panel_text(app)), panel_text(app)


class _Sub(CLIApp):
    pre_super = False

    def on_mount(self) -> None:
        if self.pre_super:
            self.push_log("sub-pre-super-record")
        super().on_mount()
        self.push_log("sub-post-super-record")


@pytest.mark.parametrize("pre_super", [False, True])
async def test_subclass_on_mount_calling_super_shows_each_record_and_warning_once(pre_super):
    class Sub(_Sub):
        pass

    Sub.pre_super = pre_super
    conflicted = menu(leaf("Quit it", "q"), leaf("Other", "o"))
    with pytest.warns(ShortcutConflictWarning, match="reserved command"):
        app = Sub(conflicted)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = panel_text(app)
        assert text.count("reserved command") == 1
        assert text.count("sub-post-super-record") == 1
        if pre_super:
            assert text.count("sub-pre-super-record") == 1


async def test_subclass_on_mount_without_calling_super_does_not_break_logging():
    class Sub(CLIApp):
        def on_mount(self) -> None:
            self.push_log("sub-only")

    app = Sub(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "sub-only" in panel_text(app)


async def test_real_app_overflow_is_bounded_with_one_notice_before_the_survivors(make_app, monkeypatch, unique_logger):
    monkeypatch.setattr(log_handler, "_INBOX_MAXLEN", 50)
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        t = threading.Thread(target=lambda: [lg.info("rec-%d", i) for i in range(500)], daemon=True)
        t.start()
        t.join(timeout=10)  # UI loop blocked while the thread logs more than the cap
        assert not t.is_alive()
        await wait_for(lambda: "rec-499" in panel_text(app))
        lines = panel_lines(app)
        recs = [ln for ln in lines if "rec-" in ln]
        notices = [ln for ln in lines if "dropped" in ln]
        assert len(recs) == 50
        assert len(notices) == 1 and "450 log record(s) dropped (UI busy)" in notices[0]
        assert lines.index(notices[0]) + 1 == lines.index(recs[0])
        assert recs[0].endswith("rec-450") and recs[-1].endswith("rec-499")


async def test_ui_join_on_a_worker_logging_a_thousand_records_does_not_deadlock(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        worker = threading.Thread(target=lambda: [lg.info("w%d", i) for i in range(1000)], daemon=True)
        t0 = time.monotonic()
        worker.start()
        worker.join(timeout=5)
        assert not worker.is_alive(), "worker deadlocked against the joining UI thread"
        assert time.monotonic() - t0 < 5
        await wait_for(lambda: "w999" in panel_text(app), timeout=15)
        text = panel_text(app)
        assert all(f"w{i}" in text for i in (0, 500, 999))
        assert text.count("dropped") == 0


async def test_post_exit_logging_from_a_worker_is_silent_under_run_test(
    make_app, unique_logger, handle_errors, thread_errors
):
    lg = unique_logger("postexit", logging.INFO)
    app = make_app(leaf("A", "a"))
    stop = threading.Event()
    emitted: list[int] = []

    def worker():
        while not stop.is_set():
            lg.info("tick")
            emitted.append(1)
            time.sleep(0.001)

    t = threading.Thread(target=worker, daemon=True)
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        t.start()
        await wait_for(lambda: len(emitted) > 5, what="worker started")
        await pilot.pause()
    n0 = len(emitted)
    # yield to the loop (never time.sleep) while the worker keeps logging after exit
    await wait_for(lambda: len(emitted) > n0 + 50, timeout=10, what="records emitted after exit")
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()
    assert lg.handlers == []
    assert handle_errors == [] and thread_errors == []


async def test_push_log_and_logger_calls_after_exit_are_silent(make_app, unique_logger, handle_errors):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        attach_logging(app, lg)
    app.push_log("after exit")
    run_threads(lambda: app.push_log("after exit bg"), lambda: lg.warning("after exit logger"))
    assert handle_errors == []


async def test_subclass_on_unmount_that_logs_does_not_error(make_app, handle_errors, thread_errors):
    class Sub(CLIApp):
        def on_unmount(self) -> None:
            self.push_log("logging while unmounting")
            super().on_unmount()
            self.push_log("logging after super unmount")

    app = Sub(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    assert handle_errors == [] and thread_errors == []


# =========================================================================== Phase 2: events, policy, latency

def log_event(msg: str, level: str = "INFO") -> dict:
    from cli_interface.events import make_log

    return make_log(msg, level)


def protected(kind: str, n: int) -> dict:
    from cli_interface import events

    return {
        "result": lambda: events.make_result(f"r{n}"),
        "error": lambda: events.make_error(f"e{n}", "m"),
        "progress": lambda: events.make_progress(id=f"p{n}", label=str(n)),
        "json": lambda: events.make_json({"n": n}),
        "table": lambda: events.make_table([{"n": n}]),
        "clear": events.make_clear,
        "hello": lambda: events.make_hello("a"),
    }[kind]()


def _fill_from_a_thread(inbox, items) -> None:
    t = threading.Thread(target=lambda: [inbox.put(x) for x in items], daemon=True)
    t.start()
    t.join(timeout=20)
    assert not t.is_alive()


async def test_the_inbox_accepts_a_headless_recording_sink_with_only_an_emit_method():
    class Recorder:
        def __init__(self):
            self.got = []

        def emit(self, event):
            self.got.append(event["kind"])

    rec = Recorder()
    inbox = PanelInbox(rec)
    inbox.open(asyncio.get_running_loop())
    inbox.put(log_event("a"))
    inbox.put(protected("result", 1))
    assert rec.got == ["log", "result"]


async def test_fifo_across_kinds_from_several_threads_and_the_ui_thread(env):
    sink, inbox, _ = env
    kinds = ["log", "result", "progress", "json", "table", "error"]

    def producer(k):
        for i in range(120):
            kind = kinds[i % len(kinds)]
            ev = log_event(f"P{k}-{i}") if kind == "log" else protected(kind, i)
            ev["src"] = (k, i)
            ev["job"] = k
            inbox.put(ev)

    threads = [threading.Thread(target=producer, args=(k,), daemon=True) for k in range(4)]
    for t in threads:
        t.start()
    join_all(threads)
    inbox.flush()
    assert len(sink.events) == 480
    for k in range(4):
        seq = [e["src"][1] for e in sink.events if e["src"][0] == k]
        assert seq == list(range(120)), f"producer {k} reordered"
        assert [e["kind"] for e in sink.events if e["src"][0] == k] == [kinds[i % 6] for i in range(120)]


async def test_ui_thread_puts_interleave_with_queued_thread_events_in_arrival_order(env):
    sink, inbox, _ = env
    _fill_from_a_thread(inbox, [log_event("t1"), protected("result", 1)])
    inbox.put(protected("table", 2))
    _fill_from_a_thread(inbox, [log_event("t2")])
    inbox.put(log_event("ui2"))
    inbox.flush()
    assert [(e["kind"], e.get("msg") or e.get("label") or e.get("rows")) for e in sink.events] == [
        ("log", "t1"), ("result", "r1"), ("table", [{"n": 2}]), ("log", "t2"), ("log", "ui2"),
    ]


async def test_protected_kinds_survive_a_fifty_thousand_record_flood():
    sink, inbox = make_inbox()  # the default cap of 10,000
    inbox.open(asyncio.get_running_loop())
    kinds = ["result", "error", "progress", "json", "table"]
    items, protected_sent = [], []
    for i in range(50_000):
        items.append(log_event(f"flood-{i}"))
        if i % 500 == 0:
            ev = protected(kinds[(i // 500) % 5], i)
            ev["n"] = i
            items.append(ev)
            protected_sent.append(ev)
    t0 = time.perf_counter()
    _fill_from_a_thread(inbox, items)
    elapsed = time.perf_counter() - t0
    assert elapsed < 10, f"{len(items)} puts took {elapsed:.2f}s"
    inbox.flush()
    got = [e for e in sink.events if e["kind"] != "log"]
    assert len(protected_sent) == 100 and len(got) == 100
    assert [e["n"] for e in got] == [e["n"] for e in protected_sent], "delivered in order, none dropped"
    logs = [e["msg"] for e in sink.events if e["kind"] == "log"]
    assert logs[0] == "40000 log record(s) dropped (UI busy)"
    assert logs[1:] == [f"flood-{i}" for i in range(40_000, 50_000)]
    assert inbox.dropped == 40_000 and sink.events[0]["level"] == "WARNING"


async def test_the_notice_comes_before_the_surviving_records_and_has_the_exact_text(env):
    sink, inbox, _ = make_inbox_env(3)
    _fill_from_a_thread(inbox, [log_event(f"r{i}") for i in range(10)])
    inbox.flush()
    assert sink.out == [("7 log record(s) dropped (UI busy)", "WARNING"), ("r7", "INFO"), ("r8", "INFO"), ("r9", "INFO")]


def make_inbox_env(maxlen):
    sink = StubSink()
    inbox = PanelInbox(sink, maxlen)
    loop = asyncio.get_running_loop()
    inbox.open(loop)
    return sink, inbox, loop


async def test_text_events_are_droppable_like_log_events():
    sink, inbox, _ = make_inbox_env(2)
    from cli_interface.events import make_text

    _fill_from_a_thread(inbox, [make_text(f"t{i}") for i in range(5)] + [protected("result", 9)])
    inbox.flush()
    assert [e["kind"] for e in sink.events] == ["log", "text", "text", "result"]
    assert [e["text"] for e in sink.events if e["kind"] == "text"] == ["t3", "t4"]
    assert inbox.dropped == 3


async def test_the_cap_counts_only_droppable_events():
    sink, inbox, _ = make_inbox_env(2)
    _fill_from_a_thread(inbox, [protected("result", i) for i in range(50)] + [log_event("a"), log_event("b")])
    inbox.flush()
    assert inbox.dropped == 0 and len(sink.events) == 52


async def test_two_separate_bursts_give_two_notices_each_with_its_own_count():
    sink, inbox, _ = make_inbox_env(5)
    for tag in "ab":
        _fill_from_a_thread(inbox, [log_event(f"{tag}{i}") for i in range(12)])
        inbox.flush()
    assert [m for m in sink.messages if "dropped" in m] == ["7 log record(s) dropped (UI busy)"] * 2
    assert inbox.dropped == 14


async def test_sustained_overflow_during_a_drain_writes_at_most_a_notice_and_one_closing_line():
    sink, inbox, _ = make_inbox_env(10)
    _fill_from_a_thread(inbox, [log_event(f"a{i}") for i in range(30)])
    bursts: list[int] = []
    real_emit = sink.emit

    def noisy_emit(event):
        real_emit(event)
        if len(bursts) < 3:
            bursts.append(1)
            _fill_from_a_thread(inbox, [log_event(f"during-{len(bursts)}-{i}") for i in range(15)])

    sink.emit = noisy_emit  # type: ignore[method-assign]
    inbox.flush()
    inbox.flush()
    notices = [m for m in sink.messages if "dropped" in m]
    assert len(notices) == 2, notices
    assert notices[0] == "20 log record(s) dropped (UI busy)"
    assert notices[1].endswith("more log record(s) dropped (UI busy)")
    closing = int(notices[1].split()[0])
    assert closing > 0 and inbox.dropped == 20 + closing
    assert sink.messages.index(notices[1]) == len(sink.messages) - 1, "the closing line ends the episode"


async def test_a_quiet_episode_has_no_closing_line():
    sink, inbox, _ = make_inbox_env(4)
    _fill_from_a_thread(inbox, [log_event(f"r{i}") for i in range(9)])
    inbox.flush()
    assert len([m for m in sink.messages if "dropped" in m]) == 1


async def test_put_never_raises_whatever_it_is_given_or_whatever_the_sink_does():
    sink, inbox, _ = make_inbox_env(10)
    sink.fail = RuntimeError("sink down")
    for junk in (None, 123, object(), [], ("kind", "log"), {"kind": "progress", "id": []}, {"no": "kind"}, b"x"):
        inbox.put(junk)  # type: ignore[arg-type]
    inbox.put(log_event("x"))
    inbox.flush()
    assert inbox.write_errors >= 1
    sink.fail = None
    inbox.put(log_event("recovered"))
    assert "recovered" in sink.messages


async def test_put_from_a_thread_never_raises_when_the_sink_raises(thread_errors):
    sink, inbox, _ = make_inbox_env(10)
    sink.fail = ValueError("boom")
    _fill_from_a_thread(inbox, [log_event("a"), protected("result", 1)])
    inbox.flush()
    assert thread_errors == [] and inbox.write_errors == 2 and sink.failed_attempts == 2


async def test_flush_off_the_ui_thread_and_before_open_does_nothing():
    sink, inbox = make_inbox()
    inbox.put(log_event("pre"))
    inbox.flush()
    assert sink.events == []
    inbox.open(asyncio.get_running_loop())
    inbox.put(log_event("queued-by-thread"))
    t = threading.Thread(target=inbox.flush, daemon=True)
    t.start()
    t.join(5)
    assert [m for m in sink.messages if m == "queued-by-thread"] == ["queued-by-thread"]  # delivered once, by the UI thread


async def test_flush_ignores_the_budget_and_delivers_everything_queued():
    sink, inbox, _ = make_inbox_env(20_000)
    _fill_from_a_thread(inbox, [log_event(f"e{i}") for i in range(8000)])
    assert inbox.pending == 8000
    inbox.flush()
    assert inbox.pending == 0 and len(sink.events) == 8000


async def test_pending_counts_queued_events_and_a_closed_inbox_ignores_every_kind():
    sink, inbox, _ = make_inbox_env(100)
    _fill_from_a_thread(inbox, [log_event("a"), protected("json", 1)])
    assert inbox.pending == 2
    inbox.close()
    assert inbox.pending == 0
    for ev in (log_event("x"), protected("result", 1), protected("clear", 0), "text"):
        inbox.put(ev)
        _fill_from_a_thread(inbox, [ev])
    inbox.flush()
    assert sink.events == [] and inbox.pending == 0


async def test_a_string_put_is_a_log_event_at_the_given_level():
    sink, inbox, _ = make_inbox_env(10)
    inbox.put("hello", "ERROR")
    inbox.put("default")
    assert [(e["kind"], e["msg"], e["level"], e["levelno"], e["logger"]) for e in sink.events] == [
        ("log", "hello", "ERROR", 40, None), ("log", "default", "INFO", 20, None),
    ]


async def test_progress_events_are_coalesced_per_job_and_id_keeping_the_newest():
    from cli_interface.events import make_progress

    sink, inbox, _ = make_inbox_env(100)

    def progress(job, pid, n, done=False):
        ev = make_progress(id=pid, label=str(n), current=n, total=10, done=done)
        if job is not None:
            ev["job"] = job
        return ev

    batch = [progress(1, "a", 1), log_event("between"), progress(1, "a", 2), progress(2, "a", 1), progress(1, "b", 1),
             progress(1, "a", 3), progress(None, "a", 1), progress(None, "a", 2)]
    _fill_from_a_thread(inbox, batch)
    assert inbox.pending == 5
    inbox.flush()
    got = [(e.get("job"), e["id"], e["current"]) if e["kind"] == "progress" else e["msg"] for e in sink.events]
    assert got == ["between", (2, "a", 1), (1, "b", 1), (1, "a", 3), (None, "a", 2)]


async def test_a_final_progress_event_is_never_replaced():
    from cli_interface.events import make_progress

    sink, inbox, _ = make_inbox_env(100)
    batch = [make_progress(id="p", current=1), make_progress(id="p", current=2, done=True), make_progress(id="p", current=3)]
    _fill_from_a_thread(inbox, batch)
    inbox.flush()
    assert [(e["current"], e["done"]) for e in sink.events] == [(2, True), (3, False)]


async def test_a_flood_of_progress_events_keeps_the_queue_bounded():
    from cli_interface.events import make_progress

    sink, inbox, _ = make_inbox_env(100)
    _fill_from_a_thread(inbox, [make_progress(id="p", current=i) for i in range(20_000)])
    assert inbox.pending == 1
    inbox.flush()
    assert [e["current"] for e in sink.events] == [19_999]


class SlowSink(StubSink):
    """A sink that costs a fixed amount of CPU per event (a busy wait, not a sleep)."""

    def __init__(self, cost: float) -> None:
        super().__init__()
        self.cost = cost
        self.first = threading.Event()

    def emit(self, event):
        end = time.perf_counter() + self.cost
        while time.perf_counter() < end:
            pass
        self.first.set()
        super().emit(event)


async def test_a_ui_thread_put_with_a_big_backlog_returns_within_the_drain_budget():
    sink = SlowSink(0.001)
    inbox = PanelInbox(sink, 100_000)
    inbox.open(asyncio.get_running_loop())
    _fill_from_a_thread(inbox, [log_event(f"b{i}") for i in range(3000)])  # a full drain would cost about 3 s
    t0 = time.perf_counter()
    inbox.put(log_event("ui"))
    elapsed = time.perf_counter() - t0
    try:
        assert elapsed < 1.2, f"a UI-thread put drained for {elapsed:.3f}s"
        assert 0 < len(sink.events) < 1500 and inbox.pending > 1500, "only a slice was delivered"
        assert "ui" not in sink.messages, "the new event queues behind the backlog"
    finally:
        inbox.close()


async def test_a_workers_logging_call_is_not_held_for_the_whole_backlog(unique_logger):
    """R5 (C0-8): the UI thread drains inside the handler lock; a worker logging at that moment waits one slice, not the lot."""
    from cli_interface.log_handler import TUILogHandler

    sink = SlowSink(0.001)
    inbox = PanelInbox(sink, 100_000)
    inbox.open(asyncio.get_running_loop())

    class Host:
        emit = staticmethod(inbox.put)

        def push_log(self, message, level="INFO"):
            inbox.put(message, level)

    lg = unique_logger("r5")
    handler = TUILogHandler(Host())  # type: ignore[arg-type]
    lg.addHandler(handler)
    _fill_from_a_thread(inbox, [log_event(f"b{i}") for i in range(3000)])
    waited: list[float] = []

    def worker():
        sink.first.wait(10)  # the UI thread is now inside the handler lock, draining
        t0 = time.perf_counter()
        lg.info("from the worker")
        waited.append(time.perf_counter() - t0)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    lg.info("from the ui thread")  # drains one slice while holding the handler lock
    t.join(15)
    try:
        assert not t.is_alive() and waited
        assert waited[0] < 1.2, f"the worker waited {waited[0]:.3f}s on the handler lock (a full drain is 3 s)"
    finally:
        lg.removeHandler(handler)
        inbox.close()


async def test_interleaved_panel_log_table_push_log_and_logging_keep_order_across_threads(make_app, unique_logger):
    lg = unique_logger("c04")
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        attach_logging(app, lg)

        def producer(k):
            for i in range(30):
                tag = f"T{k}-{i:02d}"
                (app.panel.log, lambda m: app.panel.table([{"v": m}]), app.push_log, lg.info)[i % 4](tag)

        threads = [threading.Thread(target=producer, args=(k,), daemon=True) for k in range(4)]
        for t in threads:
            t.start()
        join_all(threads)
        await app.jobs.wait_idle()
        await pilot.pause()
        lines = panel_lines(app)
        for k in range(4):
            seen = [int(ln.split(f"T{k}-")[1][:2]) for ln in lines if f"T{k}-" in ln and "T" in ln]
            assert seen == sorted(seen) and len(seen) == 30, f"producer {k}: {seen}"


async def test_clear_is_ordered_with_content_events_from_a_thread(make_app):
    from textual.widgets import RichLog

    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()

        def writer():
            app.panel.log("before-clear")
            app.panel.table([{"a": 1}])
            app.panel.clear()
            app.panel.log("after-clear")

        run_threads(writer)
        await app.jobs.wait_idle()
        await pilot.pause()
        assert panel_lines(app) == ["after-clear"]
        assert app.screen_stack[0].query_one("#display-panel", RichLog).auto_scroll is True


async def test_a_content_method_from_a_thread_enters_content_mode_on_the_ui_side(make_app):
    from textual.widgets import RichLog

    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        run_threads(lambda: app.panel.table([{"a": 1}]))
        await app.jobs.wait_idle()
        await pilot.pause()
        assert app.screen_stack[0].query_one("#display-panel", RichLog).auto_scroll is False
        assert any("a" in ln for ln in panel_lines(app))
