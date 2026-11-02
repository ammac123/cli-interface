"""P2.3 / F9: the process-wide output capture (CAPTURE): install and restore, routing, line buffering, ANSI."""
from __future__ import annotations

import contextlib
import contextvars
import io
import sys
import threading
from collections.abc import Callable
from typing import Any

import pytest

from cli_interface.capture import CAPTURE
from helpers import SIZE, leaf, menu, panel_text, run_threads


class Fake(io.StringIO):
    """A stream with a tty and a descriptor, standing in for the terminal."""

    def isatty(self) -> bool:
        return True

    def fileno(self) -> int:
        return 99

    buffer_marker = "raw-buffer"


class Wire:
    """A capture installed over a fake stdout/stderr pair, with an app-level route and a recorder."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.out, self.err = Fake(), Fake()
        monkeypatch.setattr(sys, "stdout", self.out)
        monkeypatch.setattr(sys, "stderr", self.err)
        self.events: list[dict[str, Any]] = []
        self.ui = threading.get_ident()
        CAPTURE.acquire()
        self.token = CAPTURE.open_app(self.events.append, self.ui)
        self.released = False

    def job(self, job_id: int = 5):
        jc = CAPTURE.open_job(self.events.append, job_id)
        return jc

    def run_in_job(self, jc, fn: Callable[[], Any]) -> Any:
        def body() -> Any:
            jc.activate()
            return fn()

        return contextvars.copy_context().run(body)

    def close(self) -> None:
        if not self.released:
            self.released = True
            CAPTURE.close_app(self.token)
            CAPTURE.release()


@pytest.fixture
def make_wire(monkeypatch):
    """Factory: call it inside the test body (pytest re-points sys.stdout between setup and call)."""
    made: list[Wire] = []

    def factory() -> Wire:
        made.append(Wire(monkeypatch))
        return made[-1]

    yield factory
    for w in made:
        w.close()


def texts(events: list[dict[str, Any]]) -> list[str]:
    return [e["text"] for e in events]


# --------------------------------------------------------------------------- install, refcount and restore

def test_install_wraps_both_streams_and_the_last_release_restores_them_by_identity(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    assert not CAPTURE.installed and CAPTURE.refs == 0
    CAPTURE.acquire()
    assert CAPTURE.installed and CAPTURE.refs == 1
    assert sys.stdout is not out and sys.stderr is not err
    CAPTURE.release()
    assert sys.stdout is out and sys.stderr is err
    assert not CAPTURE.installed and CAPTURE.refs == 0


def test_nested_acquires_install_once_and_only_the_last_release_restores(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.acquire()
    proxy = sys.stdout
    CAPTURE.acquire()
    CAPTURE.acquire()
    assert sys.stdout is proxy and CAPTURE.refs == 3
    CAPTURE.release()
    CAPTURE.release()
    assert sys.stdout is proxy and CAPTURE.installed
    CAPTURE.release()
    assert sys.stdout is out and CAPTURE.refs == 0


def test_an_extra_release_is_harmless(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.release()
    CAPTURE.release()
    assert CAPTURE.refs == 0 and sys.stdout is out
    CAPTURE.acquire()
    CAPTURE.release()
    CAPTURE.release()
    assert CAPTURE.refs == 0 and sys.stdout is out


def test_a_stream_swapped_by_a_third_party_is_not_restored_over(monkeypatch):
    original = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original)
    CAPTURE.acquire()
    proxy = sys.stdout
    third_party = io.StringIO()
    sys.stdout = third_party
    CAPTURE.release()
    assert sys.stdout is third_party, "the third party's stream must stay"
    assert not CAPTURE.installed
    assert proxy is not original


def test_the_proxy_keeps_working_as_a_pass_through_after_it_was_swapped_out(monkeypatch):
    original = io.StringIO()
    monkeypatch.setattr(sys, "stdout", original)
    CAPTURE.acquire()
    proxy = sys.stdout
    sys.stdout = io.StringIO()
    CAPTURE.release()
    proxy.write("late write")
    assert original.getvalue() == "late write"


def test_reinstall_rewraps_the_streams_after_an_outside_restore_while_refs_are_held(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.acquire()
    proxy = sys.stdout
    sys.stdout = out  # Textual leaving its redirect, say
    assert not CAPTURE.installed
    CAPTURE.reinstall()
    assert CAPTURE.installed and sys.stdout is not out
    assert sys.stdout._wrapped is out
    CAPTURE.reinstall()  # idempotent: no double wrapping
    assert sys.stdout._wrapped is out
    CAPTURE.release()
    assert sys.stdout is out
    assert proxy is not sys.stdout


def test_reinstall_with_no_refs_does_nothing(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.reinstall()
    assert sys.stdout is out and not CAPTURE.installed


# --------------------------------------------------------------------------- hold / unhold (outer guard)

def test_nested_holds_install_one_outer_proxy_and_the_last_unhold_restores_the_streams(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    CAPTURE.hold()
    outer = sys.stdout
    CAPTURE.hold()
    assert sys.stdout is outer and sys.stdout is not out and CAPTURE.installed
    CAPTURE.unhold()
    assert sys.stdout is outer
    CAPTURE.unhold()
    assert sys.stdout is out and sys.stderr is err and not CAPTURE.installed


def test_a_hold_survives_a_textual_like_redirect_and_the_inner_proxy_goes_over_it(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.hold()
    outer = sys.stdout
    with contextlib.redirect_stdout(io.StringIO()) as redirected:
        CAPTURE.acquire()
        inner = sys.stdout
        assert inner is not outer and inner._wrapped is redirected
        CAPTURE.release()
        assert sys.stdout is redirected
    assert sys.stdout is outer
    CAPTURE.unhold()
    assert sys.stdout is out


def test_the_outer_proxy_outlives_unhold_while_an_abandoned_ref_is_held(monkeypatch):
    out, err = io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)
    CAPTURE.hold()
    CAPTURE.acquire()
    CAPTURE.acquire()  # the abandoned job's ref
    CAPTURE.release()
    CAPTURE.unhold()
    assert sys.stdout is not out and CAPTURE.installed
    CAPTURE.release()
    assert sys.stdout is out and sys.stderr is err and CAPTURE.refs == 0


def test_a_stream_swapped_by_a_third_party_is_not_restored_over_by_unhold(monkeypatch):
    monkeypatch.setattr(sys, "stdout", io.StringIO())
    CAPTURE.hold()
    other = io.StringIO()
    sys.stdout = other
    CAPTURE.unhold()
    assert sys.stdout is other


def test_reinstall_does_not_stack_a_second_proxy_over_the_outer_one(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.hold()
    outer = sys.stdout
    CAPTURE.acquire()
    CAPTURE.reinstall()
    assert sys.stdout is outer
    CAPTURE.release()
    CAPTURE.unhold()
    assert sys.stdout is out


def test_an_unbalanced_unhold_is_harmless(monkeypatch):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    CAPTURE.unhold()
    assert sys.stdout is out and CAPTURE._holds == 0
    CAPTURE.hold()
    CAPTURE.unhold()
    CAPTURE.unhold()
    assert sys.stdout is out and CAPTURE._holds == 0


# --------------------------------------------------------------------------- inside a job

def test_print_and_stderr_in_a_job_become_line_buffered_text_events(make_wire):
    wire = make_wire()
    jc = wire.job(7)

    def body():
        print("hello")
        print("two\nlines")
        sys.stderr.write("oops\n")
        sys.stdout.write("no newline yet")

    wire.run_in_job(jc, body)
    assert [(e["text"], e["stream"], e["job"]) for e in wire.events] == [
        ("hello", "stdout", 7), ("two", "stdout", 7), ("lines", "stdout", 7), ("oops", "stderr", 7),
    ]
    for e in wire.events:
        assert e["kind"] == "text" and e["markup"] is False and e["rule"] is False
    assert wire.out.getvalue() == "" and wire.err.getvalue() == "", "job output is not forwarded to the terminal"


def test_the_partial_last_line_is_flushed_on_demand_and_not_before(make_wire):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: sys.stdout.write("partial"))
    assert wire.events == []
    jc.flush()
    assert texts(wire.events) == ["partial"]
    jc.flush()
    assert texts(wire.events) == ["partial"], "flushing twice does not repeat it"


def test_partial_lines_of_stdout_and_stderr_are_kept_apart(make_wire):
    wire = make_wire()
    jc = wire.job()

    def body():
        sys.stdout.write("out-")
        sys.stderr.write("err-")
        sys.stdout.write("end\n")
        sys.stderr.write("end\n")

    wire.run_in_job(jc, body)
    assert [(e["stream"], e["text"]) for e in wire.events] == [("stdout", "out-end"), ("stderr", "err-end")]


def test_closing_the_job_capture_flushes_a_partial_line(make_wire):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: print("tail", end=""))
    jc.close()
    assert texts(wire.events) == ["tail"]


def test_an_empty_write_and_a_blank_line(make_wire):
    wire = make_wire()
    jc = wire.job()
    result = wire.run_in_job(jc, lambda: (sys.stdout.write(""), print()))
    assert result[0] == 0
    assert texts(wire.events) == [""], "a blank line is an (empty) text event"


def test_write_returns_the_length_and_rejects_non_strings(make_wire):
    wire = make_wire()
    jc = wire.job()
    assert wire.run_in_job(jc, lambda: sys.stdout.write("abc\n")) == 4
    with pytest.raises(TypeError):
        sys.stdout.write(b"bytes")  # type: ignore[arg-type]


def test_writelines_goes_line_by_line(make_wire):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: sys.stdout.writelines(["a\n", "b\n"]))
    assert texts(wire.events) == ["a", "b"]


@pytest.mark.parametrize(
    "raw, clean",
    [
        ("\x1b[31mred\x1b[0m", "red"),
        ("\x1b[1;38;5;196mbold\x1b[m done", "bold done"),
        ("\x1b]0;window title\x07visible", "visible"),
        ("\x1b]8;;http://x\x1b\\link\x1b]8;;\x1b\\", "link"),
        ("\x1b[2Kcleared", "cleared"),
        ("a\x00b\x07c\x08d", "abcd"),
        ("tab\there", "tab\there"),
        ("progress 10%\rprogress 50%\rprogress 100%", "progress 100%"),
        ("done\r", "done"),
        ("unicode é中\U0001f600", "unicode é中\U0001f600"),
    ],
)
def test_ansi_sequences_and_control_characters_are_stripped(make_wire, raw, clean):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: print(raw))
    assert texts(wire.events) == [clean]


def test_a_very_long_line_is_split_not_lost(make_wire):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: sys.stdout.write("x" * 150_000))
    jc.flush()
    assert sum(len(t) for t in texts(wire.events)) == 150_000
    assert all(len(t) <= 65_536 for t in texts(wire.events)) and len(wire.events) >= 3


def test_isatty_is_false_and_fileno_raises_inside_a_job_but_delegate_outside(make_wire):
    wire = make_wire()
    jc = wire.job()
    assert sys.stdout.isatty() is True and sys.stdout.fileno() == 99
    inside = wire.run_in_job(jc, lambda: (sys.stdout.isatty(), sys.stderr.isatty()))
    assert inside == (False, False)

    def fileno():
        with pytest.raises(io.UnsupportedOperation):
            sys.stdout.fileno()
        with pytest.raises(io.UnsupportedOperation):
            sys.stderr.fileno()

    wire.run_in_job(jc, fileno)


def test_flush_inside_a_job_does_not_touch_the_terminal(make_wire):
    wire = make_wire()
    jc = wire.job()
    calls: list[str] = []
    wire.out.flush = lambda: calls.append("flush")  # type: ignore[method-assign]
    wire.run_in_job(jc, lambda: sys.stdout.flush())
    assert calls == []
    sys.stdout.flush()
    assert calls == ["flush"]


def test_unknown_attributes_delegate_to_the_wrapped_stream_and_bypass_capture(make_wire):
    make_wire()
    assert sys.stdout.buffer_marker == "raw-buffer"
    assert sys.stdout.getvalue() == ""
    with pytest.raises(AttributeError):
        sys.stdout.no_such_attribute  # noqa: B018


def test_two_jobs_have_separate_buffers_and_ids(make_wire):
    wire = make_wire()
    a, b = wire.job(1), wire.job(2)
    wire.run_in_job(a, lambda: sys.stdout.write("from-a"))
    wire.run_in_job(b, lambda: print("from-b"))
    a.flush()
    assert [(e["job"], e["text"]) for e in wire.events] == [(2, "from-b"), (1, "from-a")]


# --------------------------------------------------------------------------- outside a job: routing rows

def test_a_ui_thread_write_outside_a_job_is_passed_through_only(make_wire):
    wire = make_wire()
    print("ui line")
    sys.stderr.write("ui err\n")
    assert wire.events == []
    assert wire.out.getvalue() == "ui line\n" and wire.err.getvalue() == "ui err\n"


def test_a_user_thread_without_the_job_context_gives_an_app_level_event_and_still_forwards(make_wire):
    wire = make_wire()
    run_threads(lambda: print("from a spawned thread"), lambda: sys.stderr.write("spawned err\n"))
    assert sorted((e["stream"], e["text"]) for e in wire.events) == [
        ("stderr", "spawned err"), ("stdout", "from a spawned thread"),
    ]
    assert all("job" not in e for e in wire.events)
    assert "from a spawned thread" in wire.out.getvalue() and "spawned err" in wire.err.getvalue()


def test_a_thread_started_by_a_job_inherits_no_job_context(make_wire):
    wire = make_wire()
    jc = wire.job(9)

    def body():
        run_threads(lambda: print("grandchild"))
        print("child")

    wire.run_in_job(jc, body)
    by_text = {e["text"]: e for e in wire.events}
    assert by_text["child"]["job"] == 9
    assert "job" not in by_text["grandchild"]
    assert "grandchild" in wire.out.getvalue() and "child\n" not in wire.out.getvalue().replace("grandchild", "")


def test_app_level_partial_lines_are_per_thread(make_wire):
    wire = make_wire()
    gate_a, gate_b = threading.Event(), threading.Event()

    def writer(tag: str, mine: threading.Event, other: threading.Event):
        sys.stdout.write(f"{tag}-start ")
        mine.set()
        other.wait(10)
        sys.stdout.write(f"{tag}-end\n")

    t1 = threading.Thread(target=writer, args=("A", gate_a, gate_b))
    t2 = threading.Thread(target=writer, args=("B", gate_b, gate_a))
    t1.start()
    t2.start()
    t1.join(10)
    t2.join(10)
    assert sorted(texts(wire.events)) == ["A-start A-end", "B-start B-end"]


def test_closing_the_app_route_stops_app_level_events_and_flushes_partials(make_wire):
    wire = make_wire()
    run_threads(lambda: sys.stdout.write("half"))
    assert wire.events == []
    CAPTURE.close_app(wire.token)
    assert texts(wire.events) == ["half"]
    wire.events.clear()
    run_threads(lambda: print("after close"))
    assert wire.events == []
    assert "after close" in wire.out.getvalue(), "still passes through to the terminal"


# --------------------------------------------------------------------------- abandoned and closed jobs

def test_writes_of_an_abandoned_job_are_swallowed(make_wire):
    wire = make_wire()
    jc = wire.job()
    wire.run_in_job(jc, lambda: sys.stdout.write("buffered-partial"))
    jc.abandon()
    jc.abandon()
    jc.flush()
    seen = wire.run_in_job(jc, lambda: (print("late"), sys.stderr.write("late err\n"), sys.stdout.write("x")))
    assert seen[0] is None
    assert wire.events == []
    assert wire.out.getvalue() == "" and wire.err.getvalue() == ""


def test_an_abandoned_job_is_swallowed_on_the_ui_thread_too(make_wire):
    wire = make_wire()
    jc = wire.job()
    jc.abandon()
    wire.run_in_job(jc, lambda: print("ui-thread late"))
    assert wire.out.getvalue() == ""


def test_after_the_app_route_closes_a_job_thread_is_swallowed_but_the_ui_thread_passes_through(make_wire):
    wire = make_wire()
    jc = wire.job()
    CAPTURE.close_app(wire.token)

    def ui_write():
        print("on the ui thread")

    wire.run_in_job(jc, ui_write)
    assert "on the ui thread" in wire.out.getvalue(), "so a leaked context cannot hide a crash traceback"
    errors: list[BaseException] = []

    def job_thread():
        try:
            jc.activate()
            print("on a job thread")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    run_threads(job_thread)
    assert errors == []
    assert "on a job thread" not in wire.out.getvalue()
    assert wire.events == []


def test_a_closed_job_capture_passes_ui_thread_writes_through(make_wire):
    wire = make_wire()
    jc = wire.job()
    jc.close()
    jc.close()
    wire.run_in_job(jc, lambda: print("after close"))
    assert wire.events == [] and "after close" in wire.out.getvalue()


def test_an_emit_that_raises_never_breaks_print(make_wire):
    wire = make_wire()
    def bad(event):
        raise RuntimeError("sink down")

    jc = CAPTURE.open_job(bad, 1)
    wire.run_in_job(jc, lambda: print("still fine"))


def test_a_write_made_while_an_event_is_being_emitted_is_not_captured_again(make_wire):
    wire = make_wire()
    seen: list[dict] = []

    def noisy(event):
        seen.append(event)
        print("echo from the sink")  # would recurse forever if captured

    jc = CAPTURE.open_job(noisy, 3)
    wire.run_in_job(jc, lambda: print("first"))
    assert texts(seen) == ["first"]


# --------------------------------------------------------------------------- under a real (headless) app

async def test_under_run_test_the_proxy_sits_over_textuals_redirect_and_ui_writes_still_reach_it(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert CAPTURE.installed and CAPTURE.refs == 1
        proxy = sys.stdout
        assert type(proxy).__module__ == "cli_interface.capture"
        assert type(proxy._wrapped).__name__ == "_PrintCapture", "Textual's own redirect is what we wrap"
        assert proxy.isatty() is True and proxy.fileno() == -1
        printed: list[tuple[str, bool]] = []
        app._print = lambda text, stderr=False: printed.append((text, stderr))  # type: ignore[method-assign]
        print("ui-thread print")
        sys.stderr.write("ui-thread stderr\n")
        assert ("ui-thread print", False) in printed and ("ui-thread stderr\n", True) in printed
        await pilot.pause()
        assert "ui-thread print" not in panel_text(app), "UI-thread output outside a job is not captured"


async def test_streams_and_refs_are_restored_after_the_app_exits(make_app):
    before = (sys.stdout, sys.stderr)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert (sys.stdout, sys.stderr) != before
    assert (sys.stdout, sys.stderr) == before
    assert CAPTURE.refs == 0 and not CAPTURE.installed


async def test_two_apps_in_one_process_share_one_proxy_with_a_ref_each(make_app):
    first, second = make_app(leaf("A", "a")), make_app(leaf("B", "x"))
    async with first.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert CAPTURE.refs == 1
    async with second.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert CAPTURE.refs == 1
    assert CAPTURE.refs == 0


async def test_a_second_on_mount_does_not_acquire_the_capture_twice():
    from cli_interface.app import CLIApp

    class Twice(CLIApp):
        def on_mount(self) -> None:
            super().on_mount()
            super().on_mount()

    app = Twice(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert CAPTURE.refs == 1
    assert CAPTURE.refs == 0
