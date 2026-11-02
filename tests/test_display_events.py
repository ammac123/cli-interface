"""P2.1 / C0-4 / F1: the event renderer (PanelRenderer) and the DisplayPanel facade over the event queue."""
from __future__ import annotations

import inspect
import threading
import time

import pytest
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from cli_interface import events
from cli_interface.display import DisplayPanel, PanelRenderer
from cli_interface.theme import LEVEL_STYLES
from cli_interface.events import (
    make_action, make_clear, make_error, make_hello, make_json, make_log, make_progress, make_result, make_table,
    make_text,
)
from helpers import SIZE, color_of, run_threads


class Host(App):
    def __init__(self, **log_kwargs) -> None:
        super().__init__()
        self._log_kwargs = {"wrap": True, "markup": False, "highlight": True, "auto_scroll": True, **log_kwargs}

    def compose(self) -> ComposeResult:
        yield RichLog(id="log", **self._log_kwargs)


def lines_of(log: RichLog) -> list[str]:
    return [s.text.rstrip() for s in log.lines]


def style_of(log: RichLog, needle: str):
    for strip in reversed(log.lines):
        if needle in strip.text:
            return [(seg.text, seg.style) for seg in strip]
    raise AssertionError(needle)


class Recorder:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def emit(self, event: dict) -> None:
        self.events.append(event)


# --------------------------------------------------------------------------- the renderer draws each kind

async def test_hello_progress_unknown_and_malformed_events_write_nothing_and_do_not_raise():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        for event in (make_hello("app"), make_progress(label="x", current=1, total=2), {"kind": "mystery", "text": "boo"},
                      {"no": "kind"}, {"kind": None}, {"kind": 5}, {"kind": "action"}):
            renderer.emit(event)
        await pilot.pause()
        assert lines_of(log) == []


async def test_result_lines_are_executed_with_an_optional_arrow_and_cancelled():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_result("Build", summary="42"))
        renderer.emit(make_result("Bare"))
        renderer.emit(make_result("Empty", summary=""))
        renderer.emit(make_result("Stopped", status="cancelled"))
        renderer.emit(make_result("[/x] label", summary="matrix[i][j]"))
        await pilot.pause()
        assert lines_of(log) == [
            "Executed: Build → 42", "Executed: Bare", "Executed: Empty", "Cancelled: Stopped",
            "Executed: [/x] label → matrix[i][j]",
        ]
        assert color_of(style_of(log, "Executed: Bare")[0][1]) == "#98c379"
        assert color_of(style_of(log, "Cancelled")[0][1]) == "#e5c07b"


async def test_an_error_event_is_a_header_line_then_dim_plain_traceback_lines():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_error("Boom", "bad [/x]", exc_type="ValueError",
                                 traceback="Traceback (most recent call last):\n  File \"x.py\", line 1, in f\nValueError: bad [/x]\n"))
        renderer.emit(make_error("Plain", "no traceback"))
        await pilot.pause()
        assert lines_of(log) == [
            "Error in Boom: bad [/x]", "Traceback (most recent call last):", '  File "x.py", line 1, in f',
            "ValueError: bad [/x]", "Error in Plain: no traceback",
        ]
        assert color_of(style_of(log, "Error in Boom")[0][1]) == "#e06c75"
        assert all(getattr(s, "dim", False) for t, s in style_of(log, "Traceback (most") if t.strip())


async def test_a_log_event_without_a_logger_is_the_message_and_with_one_the_formatted_line():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        t = time.mktime((2024, 5, 6, 7, 8, 9, 0, 0, -1))
        renderer.emit(make_log("bare message", "WARNING"))
        renderer.emit(make_log("with logger", "WARNING", logger="pkg.mod", t=t))
        renderer.emit(make_log("with exc", "ERROR", logger="x", t=t, exc="Traceback (most recent call last):\nKeyError: 'k'"))
        await pilot.pause()
        assert lines_of(log) == [
            "bare message", "07:08:09 [WARNING] pkg.mod: with logger", "07:08:09 [ERROR] x: with exc",
            "Traceback (most recent call last):", "KeyError: 'k'",
        ]
        assert color_of(dict(style_of(log, "bare message"))["bare message"]) == "#e5c07b"


async def test_a_log_events_text_is_literal_unless_markup_is_set_and_bad_markup_falls_back():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_log("[bold]x[/bold] [/y]"))
        renderer.emit(make_log("[bold]styled[/bold] ok", markup=True))
        renderer.emit(make_log("broken [/zz]", markup=True))
        await pilot.pause()
        assert lines_of(log) == ["[bold]x[/bold] [/y]", "styled ok", "broken [/zz]"]
        assert dict(style_of(log, "styled"))["styled"].bold is True


async def test_text_events_literal_styled_stderr_markup_rule_and_obj():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_text("plain [/x]"))
        renderer.emit(make_text("on stderr", stream="stderr"))
        renderer.emit(make_text("explicit", style="bold red", stream="stderr"))
        renderer.emit(make_text("[bold]m[/bold]", markup=True))
        renderer.emit(make_text("bad [/q]", markup=True))
        renderer.emit(make_text("Title [/x]", rule=True))
        renderer.emit(make_text("", rule=True))
        renderer.emit(make_text("fallback", obj=Text("from obj", style="italic")))
        renderer.emit(make_text("<Panel>", obj=Panel(Text("inside panel"))))
        renderer.emit(make_text("<Table>", obj=Table()))
        await pilot.pause()
        text = "\n".join(lines_of(log))
        for needle in ("plain [/x]", "on stderr", "explicit", "m", "bad [/q]", "Title [/x]", "from obj", "inside panel"):
            assert needle in text, needle
        assert "fallback" not in text and "[bold]" not in text
        assert color_of(dict(style_of(log, "on stderr"))["on stderr"]) == "#e5c07b"
        explicit = dict(style_of(log, "explicit"))["explicit"]
        assert explicit.bold and explicit.color.name == "red", "an explicit style beats the stderr colour"
        assert dict(style_of(log, "from obj"))["from obj"].italic


async def test_json_events_str_data_as_given_unserialisable_data_as_pretty_and_a_title_rule():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_json({"a": [1, 2], "b": "[/x]"}, "Config [/t]"))
        renderer.emit(make_json('{"raw": true}'))
        renderer.emit(make_json({1, 2}))
        renderer.emit(make_json(object, pretty=True))
        renderer.emit(make_json([1, {"k": float}], pretty=False))
        await pilot.pause()
        text = "\n".join(lines_of(log))
        assert "Config [/t]" in text and '"a": [' in text and '"b": "[/x]"' in text
        assert '{"raw": true}' in text and "{1, 2}" in text
        assert "<class 'object'>" in text


async def test_table_events_with_dict_rows_list_rows_headers_and_literal_cells():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_table([{"name": "[/x]", "n": 1}, {"name": "b"}], title="T [/t]"))
        renderer.emit(make_table([["a", Text("styled", style="bold red"), None]], headers=["h[i]", "b", "c"]))
        renderer.emit(make_table([{"x": 1, "y": 2}], headers=["y"]))
        renderer.emit(make_table([]))
        renderer.emit(make_table([[1, 2], [3, 4]]))
        await pilot.pause()
        text = "\n".join(lines_of(log))
        for needle in ("T [/t]", "[/x]", "name", "h[i]", "None", "styled"):
            assert needle in text, needle
        style = dict(style_of(log, "styled"))["styled"]
        assert style.bold and style.color.name == "red"


async def test_max_lines_bounds_json_and_table_events():
    async with Host(max_lines=40).run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_json({f"key{i}": i for i in range(500)}))
        renderer.emit(make_table([{"n": i} for i in range(500)]))
        await pilot.pause()
        assert len(log.lines) <= 40


async def test_clear_and_action_events_keep_the_scroll_state_machine_of_the_old_panel():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_action("begin"))
        renderer.emit(make_table([{"a": 1}], scroll="top"))
        assert log.auto_scroll is False, "content mode"
        renderer.emit(make_action("end"))
        assert log.auto_scroll is False, "an action that used a content method stays where it put the view"
        renderer.emit(make_clear())
        assert log.auto_scroll is True and lines_of(log) == []
        renderer.emit(make_action("begin"))
        renderer.emit(make_log("plain"))
        renderer.emit(make_action("end"))
        assert log.auto_scroll is True


async def test_scroll_end_blocks_do_not_enter_content_mode():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        renderer = PanelRenderer(log)
        renderer.emit(make_json({"k": 1}, scroll="end"))
        renderer.emit(make_table([{"a": 1}], scroll="end"))
        assert log.auto_scroll is True


# --------------------------------------------------------------------------- the DisplayPanel facade

def test_a_panel_needs_exactly_one_of_a_widget_or_an_emitter():
    with pytest.raises(TypeError):
        DisplayPanel()
    with pytest.raises(TypeError):
        DisplayPanel(RichLog(), emitter=Recorder())  # type: ignore[arg-type]


async def test_the_legacy_widget_constructor_still_renders_immediately():
    async with Host().run_test(size=SIZE) as pilot:
        log = pilot.app.query_one(RichLog)
        panel = DisplayPanel(log)
        panel.log("immediate")
        panel.table([{"a": 1}])
        panel.clear()
        panel.rule("r")
        assert not hasattr(panel, "_log_buffer")
        await pilot.pause()
        assert lines_of(log)[0].startswith("─") or "r" in lines_of(log)[0]


def test_every_method_builds_the_event_the_schema_describes():
    rec = Recorder()
    panel = DisplayPanel(emitter=rec)
    panel.log("m", "warning", markup=True)
    panel.log(Text("styled"), "ERROR")
    panel.text("t", "bold", markup=True)
    panel.text(Text("tt"))
    panel.rule("title")
    panel.rule(Text("styled title"))
    panel.json({"k": 1}, "T")
    panel.table([{"a": 1}], ["a"], "T")
    panel.csv("a,b\n1,2", "C")
    panel.array([1], "A")
    panel.pretty({1}, "P")
    panel.renderable("plain string")
    panel.renderable(Text("rt"))
    panel.renderable(Table())
    panel.renderable(object())
    panel.clear()
    panel.prepare_for_action()
    panel.ensure_latest_visible()
    kinds = [e["kind"] for e in rec.events]
    assert kinds == ["log", "text", "text", "text", "text", "text", "json", "table", "table", "json", "json",
                     "text", "text", "text", "text", "clear", "action", "action"]
    log1, text_obj, text1, text2, rule1, rule2, json1, table1, csv1, array1, pretty1 = rec.events[:11]
    assert (log1["level"], log1["markup"]) == ("WARNING", True)
    assert text_obj["obj"].plain == "styled" and text_obj["style"] == LEVEL_STYLES["ERROR"]
    assert (text1["style"], text1["markup"]) == ("bold", True) and text2["obj"].plain == "tt"
    assert rule1["rule"] is True and rule1["text"] == "title" and rule2["rule"] is True and rule2["obj"].plain == "styled title"
    assert (json1["scroll"], json1["pretty"], json1["title"]) == ("top", False, "T")
    assert (table1["scroll"], table1["headers"], table1["title"]) == ("top", ["a"], "T")
    assert csv1["rows"] == [{"a": "1", "b": "2"}] and csv1["headers"] == ["a", "b"] and csv1["title"] == "C"
    assert (array1["pretty"], array1["scroll"]) == (True, "top") and pretty1["pretty"] is True
    assert [e["phase"] for e in rec.events[-2:]] == ["begin", "end"]
    assert all(events.validate_event(e) == [] for e in rec.events)


def test_the_facade_copies_mutable_payloads_so_later_changes_are_not_rendered():
    rec = Recorder()
    panel = DisplayPanel(emitter=rec)
    rows = [{"a": 1}, ["x", "y"]]
    data = {"k": [1]}
    items = [1, 2]
    bag = {1, 2}
    panel.table(rows)
    panel.json(data)
    panel.array(items)
    panel.pretty(bag)
    rows[0]["a"] = 99
    rows.append({"late": True})
    rows[1].append("z")
    data["new"] = 1
    items.append(3)
    bag.add(3)
    table, js, arr, pr = rec.events
    assert table["rows"] == [{"a": 1}, ["x", "y"]]
    assert js["data"] == {"k": [1]} and arr["data"] == [1, 2] and pr["data"] == {1, 2}


def test_the_facade_copies_text_objects_too():
    rec = Recorder()
    panel = DisplayPanel(emitter=rec)
    styled = Text("orig")
    panel.log(styled)
    panel.text(styled)
    panel.rule(styled)
    panel.renderable(styled)
    styled.append(" changed")
    assert [e["obj"].plain for e in rec.events] == ["orig"] * 4


def test_every_method_works_from_a_thread_and_keeps_its_order():
    rec = Recorder()
    panel = DisplayPanel(emitter=rec)

    def writer() -> None:
        panel.log("one")
        panel.table([{"a": 1}])
        panel.clear()
        panel.text("two")
        panel.json({"x": 1})
        panel.log("three")

    run_threads(writer)
    assert [(e["kind"], e.get("msg") or e.get("text")) for e in rec.events] == [
        ("log", "one"), ("table", None), ("clear", None), ("text", "two"), ("json", None), ("log", "three"),
    ]


def test_panel_emit_passes_a_ready_made_event_through():
    rec = Recorder()
    panel = DisplayPanel(emitter=rec)
    event = make_log("ready")
    panel.emit(event)
    assert rec.events == [event] and rec.events[0] is event


def test_the_public_method_signatures_are_unchanged_from_phase_1():
    sig = {n: str(inspect.signature(getattr(DisplayPanel, n))) for n in
           ("clear", "log", "rule", "text", "json", "table", "csv", "array", "pretty", "renderable")}
    assert sig["log"] == "(self, message: 'str | Text', level: 'str' = 'INFO', *, markup: 'bool' = False) -> 'None'"
    assert sig["text"] == "(self, content: 'str | Text', style: 'str' = '', *, markup: 'bool' = False) -> 'None'"
    assert sig["table"] == "(self, rows: 'list', headers: 'list[str] | None' = None, title: 'str' = '') -> 'None'"
    assert sig["json"] == "(self, data: 'Any', title: 'str' = '') -> 'None'"
    assert sig["rule"] == "(self, title: 'str' = '') -> 'None'" and sig["clear"] == "(self) -> 'None'"


# --------------------------------------------------------------------------- two threads into a real panel

async def test_two_threads_writing_through_a_job_emitter_into_a_real_renderer_keep_per_thread_order(make_app):
    from cli_interface.context import JobEmitter
    from helpers import leaf, panel_lines

    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        threads = []
        for k in range(3):
            panel = DisplayPanel(emitter=JobEmitter(app.emit, k, [], lambda: False))
            threads.append(threading.Thread(target=lambda p=panel, k=k: [p.log(f"T{k}-{i:03d}") for i in range(60)], daemon=True))
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        await app.jobs.wait_idle()
        lines = panel_lines(app)
        for k in range(3):
            assert [ln for ln in lines if ln.startswith(f"T{k}-")] == [f"T{k}-{i:03d}" for i in range(60)]
