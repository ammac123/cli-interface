"""F2: the thread-safe, bounded panel inbox (PanelInbox) and CLIApp.push_log."""
from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest

import cli_interface.log_handler as log_handler
from cli_interface.app import CLIApp, attach_logging
from cli_interface.log_handler import LogAttachment, PanelInbox
from helpers import (
    SIZE, StubApp, join_all, leaf, menu, panel_lines, panel_text, run_threads, wait_for,
)


@pytest.fixture
async def env():
    """(stub app, open inbox, loop) with the inbox opened on the test's running loop (the 'UI thread')."""
    app = StubApp()
    inbox = PanelInbox(app, maxlen=100_000)
    loop = asyncio.get_running_loop()
    inbox.open(loop)
    return app, inbox, loop


def make_inbox(maxlen=None):
    app = StubApp()
    return app, PanelInbox(app, maxlen)


# --------------------------------------------------------------------------- ordering and delivery

async def test_ui_thread_put_is_written_immediately(env):
    app, inbox, _ = env
    inbox.put("ui-direct", "ERROR")
    assert app.panel.out == [("ui-direct", "ERROR")]


async def test_background_put_arrives_once_the_loop_runs(env):
    app, inbox, _ = env
    run_threads(lambda: inbox.put("from-thread"))
    await wait_for(lambda: app.panel.messages == ["from-thread"])


async def test_fifo_per_producer_across_threads(env):
    app, inbox, _ = env
    run_threads(*[
        (lambda k=k: [inbox.put(f"T{k}-{i:04d}") for i in range(300)]) for k in range(3)
    ])
    await wait_for(lambda: len(app.panel.out) == 900)
    for k in range(3):
        seq = [int(m.split("-")[1]) for m in app.panel.messages if m.startswith(f"T{k}-")]
        assert seq == list(range(300))


async def test_stress_threads_plus_ui_puts_no_loss_dup_or_reorder(env):
    app, inbox, _ = env
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
    await wait_for(lambda: len(app.panel.out) >= total, timeout=15)
    msgs = app.panel.messages
    assert len(msgs) == total and len(set(msgs)) == total
    for k in [*range(producers), "ui"]:
        seq = [int(m.split(":")[1]) for m in msgs if m.split(":")[0] == str(k)]
        assert seq == sorted(seq), f"producer {k} reordered"


async def test_no_lost_wakeups_across_many_small_bursts(env):
    app, inbox, _ = env
    for i in range(100):
        run_threads(lambda i=i: inbox.put(f"burst-{i}"))
        await wait_for(lambda i=i: f"burst-{i}" in app.panel.messages, timeout=5, what=f"burst-{i}")


async def test_ui_put_with_backlog_drains_backlog_first_without_duplicates(env):
    app, inbox, _ = env
    run_threads(lambda: [inbox.put(f"bg{i}") for i in range(5)])
    assert app.panel.out == [], "loop is not running, so nothing has been written yet"
    inbox.put("ui-after")
    assert app.panel.messages == [f"bg{i}" for i in range(5)] + ["ui-after"]
    for _ in range(5):
        await asyncio.sleep(0.01)
    assert app.panel.messages == [f"bg{i}" for i in range(5)] + ["ui-after"]


async def test_default_cap_delivers_ten_thousand_records():
    app, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    run_threads(lambda: [inbox.put(f"d{i}") for i in range(10_000)])
    await wait_for(lambda: len(app.panel.out) == 10_000, timeout=20)
    assert inbox.dropped == 0
    assert app.panel.messages[0] == "d0" and app.panel.messages[-1] == "d9999"


# --------------------------------------------------------------------------- never blocks

async def test_background_puts_complete_while_the_loop_thread_is_blocked(env):
    app, inbox, _ = env
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
    await wait_for(lambda: len(app.panel.out) == 10_000, timeout=20)


# --------------------------------------------------------------------------- bounded

@pytest.mark.parametrize("cap, effective", [(100, 100), (5, 5), (1, 1), (0, 1), (-5, 1)])
async def test_overflow_keeps_newest_records_plus_one_notice_placed_first(cap, effective):
    app, inbox = make_inbox(cap)
    inbox.open(asyncio.get_running_loop())
    total = 1000
    t = threading.Thread(target=lambda: [inbox.put(f"r{i}") for i in range(total)], daemon=True)
    t.start()
    t.join(timeout=10)  # loop blocked meanwhile
    assert not t.is_alive()
    await wait_for(lambda: len(app.panel.out) == effective + 1, what="records + notice")
    dropped = total - effective
    assert inbox.dropped == dropped
    notices = [(m, lv) for m, lv in app.panel.out if "dropped" in m]
    assert notices == [(f"{dropped} log record(s) dropped (UI busy)", "WARNING")]
    assert app.panel.out[0] == notices[0]
    records = [m for m in app.panel.messages if m.startswith("r")]
    assert records == [f"r{i}" for i in range(total - effective, total)]


async def test_cap_is_read_from_the_module_constant_when_not_given(monkeypatch):
    monkeypatch.setattr(log_handler, "_INBOX_MAXLEN", 25)
    app, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    t = threading.Thread(target=lambda: [inbox.put(f"m{i}") for i in range(200)], daemon=True)
    t.start()
    t.join(timeout=10)
    await wait_for(lambda: len(app.panel.out) == 26)
    assert [m for m in app.panel.messages if m.startswith("m")] == [f"m{i}" for i in range(175, 200)]
    assert inbox.dropped == 175


async def test_overflow_before_open_is_bounded_and_reported_on_open():
    app, inbox = make_inbox(3)
    for i in range(5):
        inbox.put(f"pre{i}")  # state 'new': UI-thread puts are enqueued too
    run_threads(lambda: inbox.put("pre-bg"))
    assert app.panel.out == []
    inbox.open(asyncio.get_running_loop())
    await wait_for(lambda: len(app.panel.out) == 4)
    assert app.panel.messages == ["3 log record(s) dropped (UI busy)", "pre3", "pre4", "pre-bg"]
    assert inbox.dropped == 3


async def test_dropped_count_is_cumulative_and_each_notice_reports_only_new_drops():
    app, inbox = make_inbox(10)
    inbox.open(asyncio.get_running_loop())

    def burst(tag):
        t = threading.Thread(target=lambda: [inbox.put(f"{tag}{i}") for i in range(30)], daemon=True)
        t.start()
        t.join(timeout=10)

    burst("a")
    await wait_for(lambda: any(m.startswith("a29") for m in app.panel.messages))
    burst("b")
    await wait_for(lambda: any(m.startswith("b29") for m in app.panel.messages))
    notices = [m for m in app.panel.messages if "dropped" in m]
    assert notices == ["20 log record(s) dropped (UI busy)", "20 log record(s) dropped (UI busy)"]
    assert inbox.dropped == 40


# --------------------------------------------------------------------------- lifecycle

async def test_puts_before_open_are_buffered_and_shown_in_order():
    app, inbox = make_inbox()
    inbox.put("pre-ui-1")
    run_threads(lambda: inbox.put("pre-bg-2"))
    inbox.put("pre-ui-3")
    assert app.panel.out == []
    inbox.open(asyncio.get_running_loop())
    await wait_for(lambda: len(app.panel.out) == 3)
    assert app.panel.messages == ["pre-ui-1", "pre-bg-2", "pre-ui-3"]


async def test_open_twice_is_harmless(env):
    app, inbox, loop = env
    inbox.open(loop)
    inbox.open(loop)
    inbox.put("after-reopen")
    assert app.panel.messages == ["after-reopen"]


async def test_put_after_close_is_a_silent_noop_everywhere(unique_logger, handle_errors, thread_errors):
    app = StubApp()
    inbox = PanelInbox(app)
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
    assert app.panel.messages == ["before-close"]
    assert handle_errors == [] and thread_errors == []
    attachment.detach()


async def test_close_is_terminal_open_does_not_revive_it():
    app, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    inbox.close()
    inbox.open(asyncio.get_running_loop())
    inbox.put("reopen")
    run_threads(lambda: inbox.put("reopen-bg"))
    await asyncio.sleep(0.05)
    assert app.panel.out == []


async def test_close_discards_queued_records():
    app, inbox = make_inbox()
    inbox.open(asyncio.get_running_loop())
    t = threading.Thread(target=lambda: [inbox.put(f"q{i}") for i in range(5)], daemon=True)
    t.start()
    t.join(timeout=5)
    inbox.close()
    await asyncio.sleep(0.05)
    assert app.panel.out == []


async def test_closed_event_loop_makes_the_inbox_close_cleanly():
    dead = asyncio.new_event_loop()
    dead.close()
    app, inbox = make_inbox()
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
    assert app.panel.out == []


# --------------------------------------------------------------------------- re-entrancy and errors

async def test_reentrant_record_inside_panel_log_is_dropped_on_the_direct_path(env):
    app, inbox, _ = env
    depth: list[int] = []
    original = app.panel.log

    def nested(message, level="INFO"):
        depth.append(1)
        if len(depth) < 50:
            inbox.put("nested-" + message)
        return original(message, level)

    app.panel.log = nested  # type: ignore[method-assign]
    inbox.put("outer")
    assert len(depth) == 1 and app.panel.messages == ["outer"]


async def test_reentrant_record_inside_panel_log_is_dropped_on_the_scheduled_path(env):
    app, inbox, _ = env
    depth: list[int] = []
    original = app.panel.log

    def nested(message, level="INFO"):
        depth.append(1)
        if len(depth) < 50:
            inbox.put("nested-" + message)
        return original(message, level)

    app.panel.log = nested  # type: ignore[method-assign]
    run_threads(lambda: inbox.put("bg-outer"))
    await wait_for(lambda: app.panel.messages == ["bg-outer"])
    await asyncio.sleep(0.05)
    assert len(depth) == 1 and app.panel.messages == ["bg-outer"]


async def test_scheduled_drain_swallows_write_errors_and_keeps_going(env):
    app, inbox, loop = env
    reported: list[dict] = []
    loop.set_exception_handler(lambda _loop, context: reported.append(context))
    app.panel.fail = ValueError("boom")
    run_threads(lambda: inbox.put("lost"))
    await wait_for(lambda: app.panel.failed_attempts == 1, what="the failing write to be attempted")
    app.panel.fail = None
    run_threads(lambda: inbox.put("kept"))
    await wait_for(lambda: app.panel.messages == ["kept"])
    assert reported == [], "a write error must not reach asyncio's logger (it would loop back into the handler)"


async def test_direct_path_error_reaches_the_caller_and_handle_error(unique_logger, handle_errors):
    app = StubApp()
    inbox = PanelInbox(app)
    app.push_log = inbox.put  # type: ignore[method-assign]
    inbox.open(asyncio.get_running_loop())
    with pytest.raises(ValueError):
        app.panel.fail = ValueError("boom")
        inbox.put("x")
    lg = unique_logger()
    attachment = LogAttachment(app, lg)
    lg.info("via logging")
    assert len(handle_errors) == 1
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
        assert [l for l in lines if l.startswith("pre-")] == ["pre-ui", "pre-bg"]


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
    with pytest.warns(UserWarning, match="reserved command"):
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
        recs = [l for l in lines if "rec-" in l]
        notices = [l for l in lines if "dropped" in l]
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
