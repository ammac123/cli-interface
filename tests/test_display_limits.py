"""F6: one write per record, no re-render, bounded scrollback, and a loose throughput floor."""
from __future__ import annotations

import threading
import time

import pytest
from textual.widgets import RichLog

from cli_interface.app import CLIApp
from cli_interface.display import DisplayPanel
from helpers import SIZE, leaf, menu, panel_lines, run_threads, wait_for

THROUGHPUT_FLOOR = 2000  # records/second; measured rates are 5-10x higher


class WriteSpy:
    def __init__(self, widget: RichLog, monkeypatch: pytest.MonkeyPatch) -> None:
        self.writes = 0
        self.clears = 0
        write, clear = widget.write, widget.clear

        def counting_write(*a, **k):
            self.writes += 1
            return write(*a, **k)

        def counting_clear(*a, **k):
            self.clears += 1
            return clear(*a, **k)

        monkeypatch.setattr(widget, "write", counting_write)
        monkeypatch.setattr(widget, "clear", counting_clear)


def richlog(app) -> RichLog:
    return app.query_one("#display-panel", RichLog)


async def test_every_log_call_is_exactly_one_write_and_never_a_rerender(make_app, monkeypatch):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        spy = WriteSpy(richlog(app), monkeypatch)
        for i in range(300):
            app.panel.log(f"line {i}", "INFO")
        assert spy.writes == 300
        assert spy.clears == 0
        await pilot.pause()
        assert len(richlog(app).lines) == 300


async def test_records_through_push_log_are_one_write_each_on_both_paths(make_app, monkeypatch):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        spy = WriteSpy(richlog(app), monkeypatch)
        for i in range(100):
            app.push_log(f"ui {i}")
        run_threads(lambda: [app.push_log(f"bg {i}") for i in range(100)])
        await wait_for(lambda: spy.writes == 200, what="200 writes")
        await pilot.pause()
        assert spy.writes == 200 and spy.clears == 0


def test_fade_and_log_buffer_machinery_is_gone():
    for name in ("_log_buffer", "_render_log_buffer", "_log_only"):
        assert not hasattr(DisplayPanel, name)
    panel = DisplayPanel(RichLog())
    for name in ("_log_buffer", "_render_log_buffer", "_log_only"):
        assert not hasattr(panel, name)


async def test_default_scrollback_cap_is_5000_lines(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        assert richlog(app).max_lines == 5000
        await pilot.pause()
        for i in range(5200):
            app.panel.log(f"row {i}")
        await pilot.pause()
        lines = panel_lines(app)
        assert len(lines) == 5000
        assert lines[-1] == "row 5199" and lines[0] == "row 200"


async def test_max_lines_is_configurable_and_bounds_log_mode(make_app):
    app = make_app(leaf("A", "a"), max_lines=50)
    async with app.run_test(size=SIZE) as pilot:
        assert richlog(app).max_lines == 50
        await pilot.pause()
        for i in range(300):
            app.panel.log(f"line {i}")
        await pilot.pause()
        lines = panel_lines(app)
        assert len(lines) == 50
        assert lines[-1] == "line 299" and "line 0" not in lines


async def test_max_lines_bounds_content_mode_too(make_app):
    app = make_app(leaf("A", "a"), max_lines=50)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.table([{"a": i} for i in range(200)])
        app.panel.json({"k": list(range(300))})
        app.panel.array(list(range(100)))
        await pilot.pause()
        assert 0 < len(richlog(app).lines) <= 50


async def test_records_from_a_background_thread_respect_max_lines(make_app):
    app = make_app(leaf("A", "a"), max_lines=50)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        run_threads(lambda: [app.push_log(f"r{i}") for i in range(200)])
        await wait_for(lambda: any(ln == "r199" for ln in panel_lines(app)))
        assert len(richlog(app).lines) <= 50


@pytest.mark.parametrize("positional", [50, False])
def test_max_lines_and_strict_shortcuts_are_keyword_only(positional):
    with pytest.raises(TypeError):
        CLIApp(menu(leaf("A", "a")), positional)  # type: ignore[misc]


async def test_clear_empties_the_panel_and_restores_auto_scroll(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.table([{"a": 1}])
        assert richlog(app).auto_scroll is False
        app.panel.clear()
        await pilot.pause()
        assert richlog(app).auto_scroll is True and len(richlog(app).lines) == 0


async def test_scroll_behaviour_after_actions_is_unchanged(make_app):
    app = None

    def show_table():
        app.panel.table([{"a": 1}])

    def say():
        app.panel.log("hello")

    app = make_app(leaf("Table", "t", show_table), leaf("Say", "s", say))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("t", "enter")
        await pilot.pause()
        assert richlog(app).auto_scroll is False, "content stays snapped to the top after a table"
        await pilot.press("s", "enter")
        await pilot.pause()
        assert richlog(app).auto_scroll is True, "a log-only action resumes following the tail"


async def test_direct_panel_log_throughput_floor(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        n = 1000
        start = time.perf_counter()
        for i in range(n):
            app.panel.log(f"line {i}", "INFO")
        rate = n / (time.perf_counter() - start)
        assert rate > THROUGHPUT_FLOOR, f"{rate:.0f} rec/s"


async def test_end_to_end_background_throughput_floor(make_app, unique_logger):
    from cli_interface.app import attach_logging

    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        n = 3000
        start = time.perf_counter()
        t = threading.Thread(target=lambda: [lg.info("record %d", i) for i in range(n)], daemon=True)
        t.start()
        await wait_for(lambda: len(richlog(app).lines) >= n, timeout=30, what=f"{n} lines")
        rate = n / (time.perf_counter() - start)
        t.join(timeout=5)
        assert rate > THROUGHPUT_FLOOR, f"{rate:.0f} rec/s"
