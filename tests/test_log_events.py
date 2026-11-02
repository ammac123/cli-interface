"""C0-1 / C0-5: log records become `log` events; a custom formatter wins; the panel never raises into the caller."""
from __future__ import annotations

import logging
import threading

import pytest

import cli_interface.display as display_module
from cli_interface.app import attach_logging
from cli_interface.events import validate_event
from cli_interface.log_handler import TUILogHandler
from helpers import SIZE, StubApp, leaf, panel_lines, panel_text, run_threads


class EmitHost:
    """A host with ``emit`` (so the handler sends events) that also has ``push_log`` (the fallback)."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.pushed: list[tuple[str, str]] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)

    def push_log(self, message: str, level: str = "INFO") -> None:
        self.pushed.append((message, level))


def make_record(name="pkg.mod", level=logging.WARNING, msg="hello %s", args=("world",), exc_info=None):
    return logging.LogRecord(name, level, __file__, 7, msg, args, exc_info, None, None)


def test_a_record_becomes_a_log_event_with_logger_levelno_time_and_the_unformatted_message():
    host = EmitHost()
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    record = make_record()
    handler.emit(record)
    (event,) = host.events
    assert validate_event(event) == []
    assert (event["kind"], event["msg"], event["level"], event["levelno"], event["logger"], event["exc"]) == (
        "log", "hello world", "WARNING", 30, "pkg.mod", None
    )
    assert event["t"] == record.created and event["markup"] is False
    assert host.pushed == []


def test_an_exception_is_preformatted_text_never_the_exception_object():
    host = EmitHost()
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    try:
        raise ValueError("kaboom")
    except ValueError:
        import sys

        handler.emit(make_record(msg="failed", args=(), exc_info=sys.exc_info()))
    (event,) = host.events
    assert isinstance(event["exc"], str) and "ValueError: kaboom" in event["exc"] and event["msg"] == "failed"


def test_a_custom_formatter_on_the_handler_still_wins():
    host = EmitHost()
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    handler.setFormatter(logging.Formatter("CUSTOM[%(levelname)s] %(message)s"))
    record = make_record()
    handler.emit(record)
    (event,) = host.events
    assert event["msg"] == "CUSTOM[WARNING] hello world" and event["logger"] is None and event["exc"] is None
    assert event["level"] == "WARNING" and event["levelno"] == 30 and event["t"] == record.created
    assert validate_event(event) == []


def test_a_host_without_emit_gets_the_formatted_line_through_push_log():
    app = StubApp()
    handler = TUILogHandler(app)  # type: ignore[arg-type]
    handler.emit(make_record(name="n", msg="plain", args=()))
    (line, level) = app.pushed[0]
    assert level == "WARNING" and line.endswith("[WARNING] n: plain") and line[2] == ":"


def test_a_detached_handler_emits_nothing_and_a_failing_host_goes_to_handle_error(handle_errors):
    host = EmitHost()
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    handler.detach()
    handler.emit(make_record())
    assert host.events == [] and handler.detached
    live = TUILogHandler(host)  # type: ignore[arg-type]
    host.emit = lambda event: (_ for _ in ()).throw(RuntimeError("down"))  # type: ignore[method-assign]
    live.emit(make_record())
    assert len(handle_errors) == 1


def test_a_bad_percent_format_in_a_record_is_a_handle_error_not_a_crash(handle_errors):
    host = EmitHost()
    TUILogHandler(host).emit(make_record(msg="%d", args=("x",)))  # type: ignore[arg-type]
    assert len(handle_errors) == 1 and host.events == []


async def test_logger_records_render_as_time_level_logger_message_and_the_traceback_follows(make_app, unique_logger):
    import re

    lg = unique_logger("render")
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        lg.warning("plain [/x] warning")
        try:
            raise KeyError("missing")
        except KeyError:
            lg.exception("it failed")
        await pilot.pause()
        lines = panel_lines(app)
        assert re.fullmatch(rf"\d\d:\d\d:\d\d \[WARNING\] {re.escape(lg.name)}: plain \[/x\] warning", lines[0])
        assert re.fullmatch(rf"\d\d:\d\d:\d\d \[ERROR\] {re.escape(lg.name)}: it failed", lines[1])
        assert lines[2] == "Traceback (most recent call last):" and lines[-1] == "KeyError: 'missing'"


async def test_a_custom_formatter_changes_what_the_panel_shows(make_app, unique_logger):
    lg = unique_logger("fmt2")
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        attachment = attach_logging(app, lg)
        attachment.handler.setFormatter(logging.Formatter(">>> %(message)s <<<"))
        lg.info("custom")
        await pilot.pause()
        assert panel_lines(app) == [">>> custom <<<"]


# --------------------------------------------------------------------------- C0-5: the UI thread never sees a sink error

async def test_push_log_emit_and_panel_calls_never_raise_when_the_renderer_fails(make_app, monkeypatch):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        real = display_module.PanelRenderer.emit

        def broken(self, event):
            raise RuntimeError("renderer down")

        monkeypatch.setattr(display_module.PanelRenderer, "emit", broken)
        before = app._inbox.write_errors
        app.push_log("one")
        app.emit({"kind": "log", "level": "INFO", "msg": "two", "v": 1, "t": 0.0})
        app.panel.log("three")
        app.panel.table([{"a": 1}])
        run_threads(lambda: app.push_log("from a thread"))
        await pilot.pause()
        assert app._inbox.write_errors >= before + 4
        monkeypatch.setattr(display_module.PanelRenderer, "emit", real)
        app.push_log("recovered")
        await pilot.pause()
        assert "recovered" in panel_text(app) and app.is_running


async def test_a_logging_call_on_the_ui_thread_survives_a_failing_renderer(make_app, unique_logger, monkeypatch, handle_errors):
    lg = unique_logger("c05")
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        attach_logging(app, lg)
        monkeypatch.setattr(display_module.PanelRenderer, "emit", lambda self, e: (_ for _ in ()).throw(ValueError("x")))
        lg.info("does not raise")
        await pilot.pause()
    assert handle_errors == []


def test_emit_is_callable_from_any_thread_before_mount_and_after_exit_without_raising(make_app):
    app = make_app(leaf("A", "a"))
    done = threading.Event()

    def poke():
        app.emit({"kind": "log", "level": "INFO", "msg": "early", "v": 1, "t": 0.0})
        app.push_log("also early")
        done.set()

    run_threads(poke)
    assert done.is_set()


@pytest.mark.parametrize("junk", [None, 5, [], "text", {"kind": "unknown"}, {}])
async def test_emit_ignores_junk_without_raising_in_a_running_app(make_app, junk):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        app.emit(junk)  # type: ignore[arg-type]
        await pilot.pause()
        assert app.is_running
