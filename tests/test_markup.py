"""F1: consumer strings are literal everywhere; markup is opt-in; nothing crashes."""
from __future__ import annotations

import json

import pytest
from rich.text import Text
from textual.widgets import Input, RichLog

from cli_interface.menu import MenuItem
from cli_interface.theme import LEVEL_STYLES
from cli_interface.widgets import Dashboard, NavBar, PromptScreen
from helpers import (
    HOSTILE, SIZE, color_of, leaf, line_segments, read_panel, widget_text,
)

WIDE = [{"filler": "." * 60}]  # titles wrap on narrow tables, so give the table room

# surface name -> (call on the panel, text that must appear verbatim)
SURFACES = {
    "log": (lambda p, s: p.log(s), lambda s: s),
    "log-warning": (lambda p, s: p.log(s, "WARNING"), lambda s: s),
    "log-text-object": (lambda p, s: p.log(Text(s, style="bold")), lambda s: s),
    "text": (lambda p, s: p.text(s), lambda s: s),
    "text-styled": (lambda p, s: p.text(s, style="bold red"), lambda s: s),
    "rule": (lambda p, s: p.rule(s), lambda s: s),
    "json-title": (lambda p, s: p.json({"k": 1}, title=s), lambda s: s),
    "array-title": (lambda p, s: p.array([1], title=s), lambda s: s),
    "pretty-title": (lambda p, s: p.pretty(1, title=s), lambda s: s),
    "table-title": (lambda p, s: p.table(WIDE, title=s), lambda s: s),
    "table-header-list": (lambda p, s: p.table([[1]], headers=[s]), lambda s: s),
    "table-cell": (lambda p, s: p.table([{"c": s}]), lambda s: s),
    "table-dict-key": (lambda p, s: p.table([{s: 1}]), lambda s: s),
    "csv": (lambda p, s: p.csv(f'"{s}",b\n"{s}",2', title=s), lambda s: s),
    "renderable-str": (lambda p, s: p.renderable(s), lambda s: s),
    "json-data": (lambda p, s: p.json({"k": s}), lambda s: json.dumps(s)),
    "json-str": (lambda p, s: p.json(json.dumps({"k": s})), lambda s: json.dumps(s)),
    "array-data": (lambda p, s: p.array([s]), lambda s: repr(s)),
    "pretty-data": (lambda p, s: p.pretty({"k": s}), lambda s: repr({"k": s})),
}


@pytest.mark.parametrize("sample", HOSTILE)
@pytest.mark.parametrize("surface", SURFACES)
async def test_panel_surface_renders_hostile_text_verbatim_and_the_app_survives(make_app, surface, sample):
    call, expected = SURFACES[surface]
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        call(app.panel, sample)
        text = await read_panel(pilot)
        assert expected(sample) in text, text
        assert app.is_running and app.return_code is None


async def test_no_str_is_ever_passed_to_richlog_write(make_app, monkeypatch):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        widget = app.query_one("#display-panel", RichLog)
        written: list[object] = []
        original = widget.write
        monkeypatch.setattr(widget, "write", lambda content, *a, **k: (written.append(content), original(content, *a, **k))[1])
        for sample in HOSTILE:
            for call, _ in SURFACES.values():
                call(app.panel, sample)
        app.panel.log("[bold]x[/bold]", markup=True)
        app.panel.log("bad [/x]", markup=True)
        assert written
        strings = [c for c in written if isinstance(c, str)]
        assert strings == [], f"markup-capable str reached RichLog.write: {strings[:3]}"


async def test_richlog_is_created_with_markup_off_and_highlighting_on(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        widget = app.query_one("#display-panel", RichLog)
        assert widget.markup is False and widget.highlight is True


# --------------------------------------------------------------------------- opt-in markup and Text input

async def test_markup_true_renders_styling_and_strips_the_tags(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log("[bold]hi[/bold] there", "WARNING", markup=True)
        text = await read_panel(pilot)
        assert "hi there" in text and "[bold]" not in text
        segments = dict((t, s) for t, s in line_segments(app, "hi"))
        assert segments["hi"].bold is True and segments[" there"].bold is not True


async def test_text_markup_true_renders_styling(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.text("[red]warm[/red] tone", markup=True)
        text = await read_panel(pilot)
        assert "warm tone" in text and "[red]" not in text
        assert dict(line_segments(app, "warm"))["warm"].color.name == "red"


@pytest.mark.parametrize("bad", ["bad [/x]", "[/]", "oops [/bold] [italic"])
async def test_invalid_markup_with_the_opt_in_falls_back_to_plain_text(make_app, bad):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log(bad, markup=True)
        app.panel.text(bad, markup=True)
        text = await read_panel(pilot)
        assert text.count(bad) == 2
        assert app.is_running


async def test_text_object_keeps_its_own_style_and_is_not_mutated(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        consumer = Text("styled\tpart", style="italic")
        consumer.stylize("bold red", 0, 6)
        before = (consumer.plain, list(consumer.spans), consumer.style)
        app.panel.log(consumer, "ERROR")
        await pilot.pause()
        assert (consumer.plain, list(consumer.spans), consumer.style) == before
        style = dict(line_segments(app, "styled"))["styled"]
        assert style.bold and style.italic and style.color.name == "red"


async def test_text_object_gets_the_level_style_underneath_and_is_not_highlighted(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log(Text("port 8080"), "WARNING")
        app.panel.log("port 8080", "WARNING")
        await pilot.pause()
        log = app.query_one("#display-panel", RichLog)
        consumer_line, plain_line = log.lines[-2], log.lines[-1]
        assert {color_of(s.style) for s in consumer_line if s.text.strip()} == {"#e5c07b"}
        assert len({color_of(s.style) for s in plain_line if s.text.strip()}) >= 2, "plain strings are still highlighted"


# --------------------------------------------------------------------------- level styling and highlighting preserved

@pytest.mark.parametrize("level", sorted(set(LEVEL_STYLES) - {"CRITICAL"}))
async def test_each_level_still_gets_its_own_style(make_app, level):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log("words only", level)
        await pilot.pause()
        style = dict(line_segments(app, "words only"))["words only"]
        expected = {"DEBUG": "#56b6c2", "INFO": "#98c379", "WARNING": "#e5c07b", "ERROR": "#e06c75"}[level]
        assert color_of(style) == expected


async def test_highlighter_still_colours_numbers_and_strings_in_log_lines(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.log("port 8080 'quoted'", "INFO")
        await pilot.pause()
        colours = {color_of(s) for _, s in line_segments(app, "port")}
        assert len(colours) >= 3


async def test_an_invalid_style_string_does_not_kill_the_ui(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.text("x", style="notastyle zz")  # must not raise
        await pilot.pause()
        assert app.is_running and app.return_code is None


async def test_table_text_cell_keeps_its_style_and_other_cells_are_literal(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.panel.table([["[/z]", Text("styled", style="bold red"), 5, None]], headers=["h[i]", "b", "c", "d"], title="t[/q]")
        text = await read_panel(pilot)
        for expected in ("[/z]", "h[i]", "t[/q]", "5", "None"):
            assert expected in text
        style = dict(line_segments(app, "styled"))["styled"]
        assert style.bold and style.color.name == "red"


# --------------------------------------------------------------------------- typed commands, actions, errors

@pytest.mark.parametrize("sample", HOSTILE)
async def test_typed_hostile_command_is_reported_literally_and_the_app_survives(make_app, sample):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.query_one("#command-input", Input).value = sample
        await pilot.press("enter")
        text = await read_panel(pilot)
        assert f"Unknown command: {sample!r}" in text
        assert app.is_running and app.return_code is None


async def test_typing_the_keys_of_a_closing_tag_does_not_crash_the_app(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("[", "/", "x", "]", "enter")
        text = await read_panel(pilot)
        assert "Unknown command: '[/x]'" in text
        assert app.is_running and app.return_code is None


@pytest.mark.parametrize("sample", HOSTILE)
async def test_action_return_value_and_exception_message_are_literal(make_app, sample):
    def boom():
        raise ValueError(sample)

    app = make_app(MenuItem("Ret", shortcut="r", action=lambda: sample), MenuItem("Boom", shortcut="x", action=boom))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("r", "enter")
        await pilot.press("x", "enter")
        text = await read_panel(pilot)
        assert f"Executed: Ret → {sample}" in text
        assert f"Error in Boom: {sample}" in text
        assert app.is_running and app.return_code is None


async def test_an_error_message_that_looks_like_a_closing_tag_leaves_the_app_alive(make_app):
    def boom():
        raise ValueError("bad key [/section] in config")

    app = make_app(MenuItem("Boom", shortcut="x", action=boom))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("x", "enter")
        text = await read_panel(pilot)
        assert "Error in Boom: bad key [/section] in config" in text
        assert app.is_running and app.return_code is None


@pytest.mark.parametrize("sample", HOSTILE)
async def test_hostile_labels_appear_literally_in_executed_and_no_action_lines(make_app, sample):
    app = make_app(MenuItem(sample, shortcut="n"), MenuItem(sample + "!", shortcut="e", action=lambda: None))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("n", "enter")
        await pilot.press("e", "enter")
        text = await read_panel(pilot)
        assert f"{sample}: no action bound" in text
        assert f"Executed: {sample}!" in text
        assert app.is_running


# --------------------------------------------------------------------------- widgets

@pytest.mark.parametrize("sample", HOSTILE)
@pytest.mark.parametrize("selected", [0, 1])
async def test_navbar_renders_label_shortcut_and_value_literally(make_app, sample, selected):
    app = make_app(
        MenuItem(sample, shortcut="[x]", current_value="[/v]", action=lambda: None),
        MenuItem("two", shortcut="t", current_value=sample, children=[leaf("c", "c")]),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.query_one("#nav-bar", NavBar)
        nav.selected = selected
        await pilot.pause()
        rendered = nav.render()
        assert isinstance(rendered, Text)
        assert f"[x] {sample} ([/v])" in rendered.plain
        assert f"t two ({sample})" in rendered.plain
        assert f"[x] {sample} ([/v])" in widget_text(nav)
        assert app.is_running


@pytest.mark.parametrize("sample", HOSTILE)
async def test_dashboard_breadcrumbs_status_and_spinner_label_are_literal(make_app, sample):
    inner = MenuItem(sample, shortcut="i", children=[leaf("Leaf", "l")])
    app = make_app(MenuItem(sample, shortcut="s", children=[inner]))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("s", "enter")
        await pilot.press("i", "enter")
        await pilot.pause()
        dash = app.query_one("#dashboard", Dashboard)
        assert isinstance(dash.render(), Text)
        assert dash.render().plain.startswith(f" Home › {sample} › {sample}\n ")
        assert f"Home › {sample} › {sample}" in widget_text(dash)
        app.start_spinner(label=sample)
        await pilot.pause()
        assert dash.render().plain.endswith(f" {sample}")
        assert f" {sample}" in widget_text(dash).splitlines()[1]
        assert app.is_running and app.return_code is None
        app.exit()


@pytest.mark.parametrize("sample", HOSTILE)
async def test_prompt_screen_title_and_prompt_are_literal(make_app, sample):
    app = make_app(MenuItem(sample, shortcut="p", prompt=f"Prompt {sample}:", action=lambda v: None))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("p", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert sample in widget_text(app.screen.query_one("#prompt-title"))
        assert f"Prompt {sample}:" in widget_text(app.screen.query_one("#prompt-label"))
        assert app.is_running


async def test_framework_authored_hint_keeps_its_markup(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        hint = widget_text(app.query_one("#hint"))
        assert "[/]" not in hint and "navigate" in hint and "select" in hint
