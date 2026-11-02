"""F3: LogAttachment, attach_logging, the shared-attachment lease, and teardown at app exit."""
from __future__ import annotations

import asyncio
import logging
import threading
import warnings

import pytest

from cli_interface import LoggingAttachWarning
from cli_interface.app import CLIApp, attach_logging
from cli_interface.log_handler import LogAttachment, PanelInbox
from helpers import (
    SIZE, StubApp, StubSink, leaf, menu, panel_text, run_threads, tui_handlers, wait_for,
)


def named_or_root(kind: str, unique_logger):
    if kind == "root":
        return logging.getLogger(), None
    lg = unique_logger()
    return lg, lg


# --------------------------------------------------------------------------- the unique_logger fixture itself

def test_unique_logger_hands_out_distinct_loggers_that_start_with_no_handlers(unique_logger):
    first, second = unique_logger("x"), unique_logger("x")
    assert first is not second and first.name != second.name
    assert first.handlers == [] and second.handlers == []
    assert first.propagate is False and second.propagate is False


# --------------------------------------------------------------------------- LogAttachment (unit)

@pytest.mark.parametrize("kind", ["named", "root"])
@pytest.mark.parametrize("exclusive", [False, True])
@pytest.mark.parametrize("level", [None, "DEBUG"])
def test_detach_restores_exactly_the_handlers_and_level_it_changed(kind, exclusive, level, unique_logger):
    logger, arg = named_or_root(kind, unique_logger)
    host1, host2 = logging.NullHandler(), logging.NullHandler()
    logger.addHandler(host1)
    logger.addHandler(host2)
    logger.setLevel(logging.WARNING)
    handlers_before, level_before = list(logger.handlers), logger.level

    attachment = LogAttachment(StubApp(), arg, exclusive=exclusive, level=level)

    assert attachment.logger is logger and attachment.active
    assert attachment.handler in logger.handlers
    assert (host1 in logger.handlers) is (not exclusive)
    assert logger.level == (logging.DEBUG if level else logging.WARNING)

    attachment.detach()
    assert not attachment.active
    assert logger.handlers == handlers_before and logger.level == level_before
    attachment.detach()
    assert logger.handlers == handlers_before and logger.level == level_before


def test_logger_none_means_the_root_logger():
    attachment = LogAttachment(StubApp())
    try:
        assert attachment.logger is logging.getLogger()
        assert attachment.handler in logging.getLogger().handlers
    finally:
        attachment.detach()


def test_a_handler_the_host_adds_mid_attachment_survives_detach(unique_logger):
    lg = unique_logger()
    base = logging.NullHandler()
    lg.addHandler(base)
    attachment = LogAttachment(StubApp(), lg, exclusive=True)
    mid = logging.NullHandler()
    lg.addHandler(mid)
    attachment.detach()
    assert base in lg.handlers and mid in lg.handlers and attachment.handler not in lg.handlers


def test_level_is_not_clobbered_if_the_host_changed_it_during_the_attachment(unique_logger):
    lg = unique_logger(level=logging.WARNING)
    attachment = LogAttachment(StubApp(), lg, level=logging.DEBUG)
    lg.setLevel(logging.ERROR)
    attachment.detach()
    assert lg.level == logging.ERROR


def test_level_is_restored_when_unchanged_by_the_host(unique_logger):
    lg = unique_logger(level=logging.WARNING)
    attachment = LogAttachment(StubApp(), lg, level=logging.DEBUG)
    attachment.detach()
    assert lg.level == logging.WARNING


def test_notset_level_is_restored_and_string_levels_are_accepted(unique_logger):
    lg = unique_logger(level=logging.NOTSET)
    attachment = LogAttachment(StubApp(), lg, level="INFO")
    assert lg.level == logging.INFO
    attachment.detach()
    assert lg.level == logging.NOTSET


def test_without_level_the_logger_level_is_never_touched(unique_logger):
    lg = unique_logger(level=logging.ERROR)
    attachment = LogAttachment(StubApp(), lg)
    lg.setLevel(logging.INFO)
    attachment.detach()
    assert lg.level == logging.INFO


def test_a_bad_level_raises_and_rolls_back_the_removed_host_handlers(unique_logger):
    lg = unique_logger()
    host = logging.NullHandler()
    lg.addHandler(host)
    with pytest.raises(ValueError):
        LogAttachment(StubApp(), lg, exclusive=True, level="NOPE")
    assert lg.handlers == [host]


def test_with_block_detaches_on_exit_including_on_error(unique_logger):
    lg = unique_logger()
    with LogAttachment(StubApp(), lg) as attachment:
        assert attachment.active and attachment.handler in lg.handlers
    assert not attachment.active and lg.handlers == []
    with pytest.raises(RuntimeError):
        with LogAttachment(StubApp(), lg) as attachment:
            raise RuntimeError("boom")
    assert not attachment.active and lg.handlers == []


def test_emit_after_detach_is_a_noop_and_the_format_is_unchanged(unique_logger):
    app = StubApp()
    lg = unique_logger("emit")
    attachment = LogAttachment(app, lg)
    lg.info("one")
    handler = attachment.handler
    attachment.detach()
    lg.info("two")
    handler.emit(logging.LogRecord("x", logging.INFO, "f", 1, "three", (), None))
    assert handler.detached
    assert [m for m, _ in app.pushed if "one" in m] and len(app.pushed) == 1
    message, level = app.pushed[0]
    assert level == "INFO" and f"[INFO] {lg.name}: one" in message


def test_concurrent_detaches_restore_only_once(unique_logger):
    lg = unique_logger()
    host = logging.NullHandler()
    lg.addHandler(host)
    before = list(lg.handlers)
    attachment = LogAttachment(StubApp(), lg, exclusive=True, level=logging.DEBUG)
    run_threads(*[attachment.detach for _ in range(16)])
    assert lg.handlers == before


def test_nested_exclusive_attachments_do_not_resurrect_a_dead_handler(unique_logger):
    lg = unique_logger()
    host = logging.NullHandler()
    lg.addHandler(host)
    a1 = LogAttachment(StubApp(), lg, exclusive=True)
    a2 = LogAttachment(StubApp(), lg, exclusive=True)  # removes a1's handler
    a1.detach()
    a2.detach()
    assert lg.handlers == [host]
    assert not tui_handlers(lg)


def test_exclusive_on_a_named_logger_leaves_the_root_handlers_alone(unique_logger):
    root_before = list(logging.getLogger().handlers)
    lg = unique_logger()
    lg.addHandler(logging.NullHandler())
    attachment = LogAttachment(StubApp(), lg, exclusive=True)
    assert logging.getLogger().handlers == root_before
    attachment.detach()


async def test_records_queued_in_the_inbox_still_render_after_detach(unique_logger):
    app, sink = StubApp(), StubSink()
    inbox = PanelInbox(sink)
    app.push_log = inbox.put  # type: ignore[method-assign]
    inbox.open(asyncio.get_running_loop())
    lg = unique_logger("queued")
    attachment = LogAttachment(app, lg)
    t = threading.Thread(target=lambda: [lg.info("q%d", i) for i in range(5)], daemon=True)
    t.start()
    t.join(timeout=5)  # loop blocked: records are queued, not yet written
    attachment.detach()
    await wait_for(lambda: len(sink.out) == 5)
    assert [m.rsplit(": ", 1)[1] for m in sink.messages] == [f"q{i}" for i in range(5)]


# --------------------------------------------------------------------------- the lease (unit)

def test_share_returns_a_lease_sharing_handler_and_logger_with_exactly_one_handler(unique_logger):
    lg = unique_logger()
    base = LogAttachment(StubApp(), lg)
    lease = base.share()
    assert lease is not base and isinstance(lease, LogAttachment)
    assert lease.handler is base.handler and lease.logger is base.logger
    assert lease.active and base.active
    assert len(tui_handlers(lg)) == 1
    base.detach()


def test_releasing_a_lease_never_touches_the_logger_or_the_owner(unique_logger):
    lg = unique_logger()
    host = logging.NullHandler()
    lg.addHandler(host)
    base = LogAttachment(StubApp(), lg)
    lease = base.share()
    lease.detach()
    assert not lease.active and base.active and base.handler in lg.handlers and not base.handler.detached
    lease.detach()
    assert base.active and base.handler in lg.handlers
    base.detach()
    assert lg.handlers == [host]


def test_lease_with_block_and_with_plus_manual_detach_leave_the_owner_active(unique_logger):
    lg = unique_logger()
    base = LogAttachment(StubApp(), lg)
    with base.share() as lease:
        assert lease.active
    assert not lease.active and base.active
    with base.share() as lease2:
        lease2.detach()
    assert not lease2.active and base.active and base.handler in lg.handlers
    base.detach()


def test_owner_detach_makes_every_lease_inactive_and_restores_the_logger(unique_logger):
    lg = unique_logger(level=logging.WARNING)
    host = logging.NullHandler()
    lg.addHandler(host)
    before = list(lg.handlers)
    base = LogAttachment(StubApp(), lg, exclusive=True, level=logging.DEBUG)
    leases = [base.share() for _ in range(3)]
    base.detach()
    assert not any(lease.active for lease in leases)
    assert lg.handlers == before and lg.level == logging.WARNING
    for lease in leases:
        lease.detach()
    assert lg.handlers == before


def test_share_of_a_lease_binds_the_base_not_the_lease(unique_logger):
    lg = unique_logger()
    base = LogAttachment(StubApp(), lg)
    lease = base.share()
    lease.detach()
    again = lease.share()
    assert again.active, "a lease of a released lease must still be live while the base is"
    base.detach()
    assert not again.active


def test_concurrent_lease_detaches_leave_the_owner_active(unique_logger):
    lg = unique_logger()
    base = LogAttachment(StubApp(), lg)
    leases = [base.share() for _ in range(8)]
    run_threads(*[(lambda lease=lease: [lease.detach() for _ in range(3)]) for lease in leases])
    assert base.active and base.handler in lg.handlers and not any(lease.active for lease in leases)
    base.detach()


# --------------------------------------------------------------------------- attach_logging (app level)

async def test_old_call_forms_still_work_and_return_a_log_attachment(make_app, unique_logger, host_root):
    app = make_app(leaf("A", "a"))
    named = unique_logger()
    async with app.run_test(size=SIZE):
        by_logger = attach_logging(app, named)
        assert isinstance(by_logger, LogAttachment) and by_logger.logger is named
        attach_logging(app, unique_logger(), exclusive=True)  # return value ignored
        on_root = attach_logging(app)
        assert on_root.logger is host_root
        assert on_root.handler in host_root.handlers and host_root.sentinel in host_root.handlers
        exclusive_root = attach_logging(app, logging.getLogger("tests.other"), exclusive=True)
        assert exclusive_root.active
        assert len(tui_handlers(host_root)) == 1


async def test_attach_twice_gives_a_shared_lease_and_exactly_one_handler(make_app, unique_logger):
    lg = unique_logger()
    pre = logging.NullHandler()
    lg.addHandler(pre)
    lg.setLevel(logging.WARNING)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        first = attach_logging(app, lg)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            plain_repeat = attach_logging(app, lg)  # a plain repeat must not warn
        assert plain_repeat is not first and isinstance(plain_repeat, LogAttachment)
        assert plain_repeat.handler is first.handler and plain_repeat.logger is first.logger
        assert len(tui_handlers(lg)) == 1 and lg.handlers == [pre, first.handler]


@pytest.mark.parametrize("kwargs", [{"exclusive": True}, {"level": logging.DEBUG}])
async def test_repeat_attach_with_ignored_arguments_warns_once_and_changes_nothing(make_app, unique_logger, kwargs):
    lg = unique_logger(level=logging.WARNING)
    pre = logging.NullHandler()
    lg.addHandler(pre)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        first = attach_logging(app, lg)
        with pytest.warns(LoggingAttachWarning, match="were ignored because") as record:
            lease = attach_logging(app, lg, **kwargs)
        assert len(record) == 1 and record[0].filename == __file__
        assert lease.handler is first.handler
        assert pre in lg.handlers and lg.level == logging.WARNING and len(tui_handlers(lg)) == 1


async def test_host_attach_then_scoped_attach_keeps_the_host_capturing(make_app, host_root):
    """The demo's pattern against a host that already attached root: the scoped detach must not end the host's capture."""
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        host = attach_logging(app)
        with pytest.warns(LoggingAttachWarning, match="were ignored because") as record:
            scoped = attach_logging(app, exclusive=True, level=logging.DEBUG)
        assert len(record) == 1
        assert scoped is not host and scoped.handler is host.handler
        assert len(tui_handlers(host_root)) == 1
        assert host_root.sentinel in host_root.handlers and host_root.level == logging.WARNING
        scoped.detach()
        assert host.active and not scoped.active
        logging.getLogger("tests.scoped").warning("STILL-CAPTURED")
        await pilot.pause()
        assert "STILL-CAPTURED" in panel_text(app)
        with attach_logging(app) as lease:
            lease.detach()
        assert host.active
    assert host_root.sentinel in host_root.handlers and not tui_handlers(host_root)
    assert host_root.level == logging.WARNING


async def test_owner_detaching_first_deactivates_leases_and_a_reattach_is_a_real_attachment(make_app, host_root):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        owner = attach_logging(app)
        lease = attach_logging(app)
        owner.detach()
        assert not lease.active and not tui_handlers(host_root)
        fresh = attach_logging(app, exclusive=True, level=logging.DEBUG)
        assert fresh.active and fresh is not owner and fresh is not lease
        assert type(fresh) is LogAttachment
        assert len(tui_handlers(host_root)) == 1
        assert host_root.sentinel not in host_root.handlers and host_root.level == logging.DEBUG


async def test_two_apps_get_separate_handlers_on_the_same_logger(make_app, unique_logger):
    lg = unique_logger()
    app1, app2 = make_app(leaf("A", "x")), make_app(leaf("B", "y"))
    async with app1.run_test(size=SIZE):
        async with app2.run_test(size=SIZE):
            a1, a2 = attach_logging(app1, lg), attach_logging(app2, lg)
            assert a1.handler is not a2.handler and len(tui_handlers(lg)) == 2
        assert tui_handlers(lg) == [a1.handler]
    assert lg.handlers == []


async def test_lease_detach_from_threads_leaves_the_host_capturing(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        host = attach_logging(app, lg)
        leases = [attach_logging(app, lg) for _ in range(8)]
        run_threads(*[(lambda lease=lease: [lease.detach() for _ in range(50)]) for lease in leases])
        assert host.active
        lg.warning("still captured")
        await pilot.pause()
        assert "still captured" in panel_text(app)


@pytest.mark.parametrize("exclusive", [False, True])
async def test_root_and_named_loggers_are_restored_exactly_at_app_exit(make_app, unique_logger, host_root, exclusive):
    named = unique_logger(level=logging.WARNING)
    named_host = logging.NullHandler()
    named.addHandler(named_host)
    root_before = (list(host_root.handlers), host_root.level)
    named_before = (list(named.handlers), named.level)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        attach_logging(app, None, exclusive=exclusive, level=logging.DEBUG)
        attach_logging(app, named, exclusive=exclusive, level=logging.DEBUG)
        assert host_root.level == logging.DEBUG and named.level == logging.DEBUG
    assert (list(host_root.handlers), host_root.level) == root_before
    assert (list(named.handlers), named.level) == named_before


async def test_exit_with_outstanding_leases_restores_root(make_app, host_root):
    before = (list(host_root.handlers), host_root.level)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        owner = attach_logging(app, exclusive=True, level=logging.DEBUG)
        with pytest.warns(LoggingAttachWarning):
            lease = attach_logging(app, level=logging.INFO)
        outstanding = attach_logging(app)
    assert not owner.active and not lease.active and not outstanding.active
    assert (list(host_root.handlers), host_root.level) == before


class _Crash(CLIApp):
    def on_mount(self) -> None:
        super().on_mount()
        self.set_timer(0.05, self._explode)

    def _explode(self) -> None:
        raise ZeroDivisionError("crash path")


async def test_app_crash_still_restores_the_hosts_handlers_and_level(host_root):
    before = (list(host_root.handlers), host_root.level)
    app = _Crash(menu(leaf("A", "a")))
    with pytest.raises(ZeroDivisionError):
        async with app.run_test(size=SIZE):
            attach_logging(app, exclusive=True, level=logging.DEBUG)
            assert host_root.sentinel not in host_root.handlers
            await wait_for(lambda: not app.is_running, timeout=5, what="app to crash")
    assert (list(host_root.handlers), host_root.level) == before
    assert not tui_handlers(host_root)


async def test_attachments_are_per_logger_and_survive_a_modal_prompt(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("P", "p", lambda v: None, prompt="value:"))
    async with app.run_test(size=SIZE) as pilot:
        attachment = attach_logging(app, lg)
        await pilot.press("p", "enter")
        await pilot.pause()
        await pilot.press("1", "enter")
        await pilot.pause()
        await pilot.press("p", "enter")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        lg.info("UI-AFTER-MODAL")
        run_threads(lambda: lg.info("BG-AFTER-MODAL"))
        await wait_for(lambda: "BG-AFTER-MODAL" in panel_text(app))
        assert "UI-AFTER-MODAL" in panel_text(app) and attachment.active
