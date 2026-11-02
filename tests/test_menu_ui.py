"""P1.2a, CF-2, CF-5, CF-6, CF-7, CF-13, CF-14, CF-15 as the user sees them: nav bar, breadcrumb, panel, dialogs."""
from __future__ import annotations

import logging

import pytest
from rich.text import Text

from cli_interface import CLIApp, MenuItem
from cli_interface.menu import RESERVED_ACTIONS, _NavCell
from cli_interface.theme import _DIM_FG, _HINT_TEXT, _ORANGE
from cli_interface.widgets import Dashboard, NavBar, PromptScreen
from helpers import (
    SIZE, Calls, leaf, menu, panel_lines, panel_text, read_panel, type_command, wait_for, widget_lines, widget_text,
)

HINT_LINE_1 = "  ↑ ↓  navigate   Enter  select   Esc  back   ·  type a shortcut + Enter"
HINT_LINE_2 = "  q + Enter  quit   PgUp / PgDn  scroll output   Home / End  top / bottom"


def nav_of(app: CLIApp) -> NavBar:
    return app.query_one("#nav-bar", NavBar)


# --------------------------------------------------------------------------- P1.2a: callables in the nav bar

async def test_callable_label_and_value_are_drawn_in_the_nav_bar():
    state = {"mode": "fast", "port": 8080}
    app = CLIApp(menu(
        MenuItem(lambda: f"Mode {state['mode']}", shortcut="m", children=[leaf("Leaf", "l")]),
        MenuItem("Port", shortcut="p", current_value=lambda: state["port"], action=lambda: None),
    ))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = widget_text(nav_of(app))
        assert "m Mode fast ›" in text and "p Port (8080)" in text
        state.update(mode="slow", port=9090)
        app.refresh_menu()
        await pilot.pause()
        text = widget_text(nav_of(app))
        assert "m Mode slow ›" in text and "p Port (9090)" in text
        assert "fast" not in text and "8080" not in text


async def test_a_value_callable_returning_none_hides_the_value_and_zero_or_false_still_show():
    values = {"v": None}
    app = CLIApp(menu(
        MenuItem("Maybe", shortcut="m", current_value=lambda: values["v"], action=lambda: None),
        MenuItem("Zero", shortcut="z", current_value=lambda: 0, action=lambda: None),
        MenuItem("Off", shortcut="o", current_value=lambda: False, action=lambda: None),
        MenuItem("Plain", shortcut="p", current_value=None, action=lambda: None),
    ))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = widget_text(nav_of(app))
        assert "m Maybe " in text and "m Maybe (" not in text and "p Plain " in text and "p Plain (" not in text
        assert "z Zero (0)" in text and "o Off (False)" in text
        values["v"] = "now"
        app.refresh_menu()
        await pilot.pause()
        assert "m Maybe (now)" in widget_text(nav_of(app))


async def test_non_string_callable_results_are_shown_through_str():
    app = CLIApp(menu(MenuItem(lambda: 7, shortcut="a", current_value=lambda: 1.5, action=lambda: None)))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "a 7 (1.5)" in widget_text(nav_of(app))


async def test_a_raising_callable_shows_the_error_marker_logs_at_debug_and_the_app_stays_alive(caplog):
    def boom() -> str:
        raise ValueError("kaput")

    app = CLIApp(menu(
        MenuItem(boom, shortcut="e", action=lambda: "done"),
        MenuItem("Val", shortcut="v", current_value=boom, action=lambda: None),
    ))
    with caplog.at_level(logging.DEBUG, logger="cli_interface.menu"):
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            text = widget_text(nav_of(app))
            assert "e <error>" in text and "v Val (<error>)" in text
            await type_command(pilot, "e")
            assert "Executed: <error> → done" in panel_text(app)
            assert app.is_running and app.return_code is None
    debug = [r for r in caplog.records if r.name == "cli_interface.menu" and r.levelno == logging.DEBUG]
    assert debug and all(r.exc_info for r in debug)
    assert any(isinstance(r.exc_info[1], ValueError) for r in debug if r.exc_info)


async def test_a_secret_items_value_callable_is_never_called_and_shows_the_mask():
    calls: list[str] = []

    def spy() -> str:
        calls.append("called")
        return "hunter2"

    seen: list[str] = []
    app = CLIApp(menu(
        MenuItem("Token", shortcut="t", secret=True, current_value=spy, prompt="Token:", action=seen.append),
        MenuItem("Bare", shortcut="r", secret=True, action=lambda: None),
    ))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = widget_text(nav_of(app))
        assert "t Token (••••)" in text and "hunter2" not in text
        assert "r Bare" in text and "r Bare (" not in text, "a secret without a value shows no mask"
        await type_command(pilot, "t")
        await pilot.press("x", "enter")
        await pilot.pause()
        app.refresh_menu()
        await pilot.pause()
        assert seen == ["x"]
        assert calls == [] and "hunter2" not in panel_text(app) + widget_text(nav_of(app))


async def test_each_callable_runs_once_per_render_pass():
    label_calls, value_calls = [], []

    def label() -> str:
        label_calls.append(1)
        return "Dyn"

    def value() -> str:
        value_calls.append(1)
        return "v"

    app = CLIApp(menu(MenuItem(label, shortcut="d", current_value=value, action=lambda: None), leaf("Other", "o")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        label_calls.clear()
        value_calls.clear()
        rendered = nav.render()
        assert isinstance(rendered, Text) and "d Dyn (v)" in rendered.plain
        assert (len(label_calls), len(value_calls)) == (1, 1)
        nav.render()
        assert (len(label_calls), len(value_calls)) == (2, 2), "a new pass reads the current text again"


async def test_a_render_started_inside_a_callable_leaves_the_outer_pass_consistent():
    app_ref: list[CLIApp] = []
    outer_started = []
    second_calls: list[int] = []

    def first() -> str:
        if not outer_started:
            outer_started.append(1)
            nav_of(app_ref[0]).render()  # a nested pass, started while the outer one is resolving
        return "First"

    def second() -> str:
        second_calls.append(1)
        return "Second"

    app = CLIApp(menu(MenuItem(first, shortcut="f", action=lambda: None), MenuItem(second, shortcut="s", action=lambda: None)))
    app_ref.append(app)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        outer_started.clear()
        second_calls.clear()
        text = nav.render().plain
        assert "f First" in text and "s Second" in text
        assert len(second_calls) == 2, "once for the nested pass and once for the outer pass, not once per measurement"
        second_calls.clear()
        nav.render()
        assert len(second_calls) == 1


# --------------------------------------------------------------------------- P1.2a: breadcrumb and Executed lines

async def test_callable_labels_appear_in_the_breadcrumb_and_follow_refresh_menu():
    mode = {"label": "Alpha"}
    inner = MenuItem(lambda: mode["label"], shortcut="i", children=[leaf("Leaf", "l")])
    app = CLIApp(menu(inner))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "i")
        assert dash.render().plain.startswith(" Home › Alpha\n")
        mode["label"] = "Beta"
        app.refresh_menu()
        await pilot.pause()
        assert dash.render().plain.startswith(" Home › Beta\n") and dash.location == "Home|Beta"


async def test_the_executed_line_uses_the_label_as_it_was_before_the_action_ran():
    on = {"state": False}

    def toggle() -> None:
        on["state"] = not on["state"]

    app = CLIApp(menu(
        MenuItem(lambda: "Turn off" if on["state"] else "Turn on", shortcut="t", action=toggle),
    ))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "t")
        await type_command(pilot, "t")
        lines = [ln for ln in panel_lines(app) if ln.startswith("Executed")]
        assert lines == ["Executed: Turn on", "Executed: Turn off"]


async def test_a_label_that_depends_on_state_the_action_clears_still_reads_cleanly():
    state = {"name": "Item 1"}

    def label() -> str:
        return state["name"]  # raises KeyError once the state is cleared

    app = CLIApp(menu(MenuItem(label, shortcut="c", action=state.clear)))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "c")
        text = panel_text(app)
        assert "Executed: Item 1" in text and "<error>" not in text


async def test_an_error_line_uses_the_label_as_it_was_before_the_action_ran():
    state = {"name": "Fail 1"}

    def action() -> None:
        state.clear()
        raise RuntimeError("kaput")

    app = CLIApp(menu(MenuItem(lambda: state["name"], shortcut="f", action=action)))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "f")
        text = panel_text(app)
        assert "Error in Fail 1: kaput" in text and "<error>" not in text and app.is_running


async def test_a_callable_label_is_used_for_the_no_action_line_and_the_prompt_title():
    app = CLIApp(menu(
        MenuItem(lambda: "Dynamic menu", shortcut="n"),
        MenuItem(lambda: "Dynamic prompt", shortcut="p", prompt="Value:", action=lambda v: None),
    ))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "n")
        assert "Dynamic menu: no action bound" in panel_text(app)
        await type_command(pilot, "p")
        assert isinstance(app.screen, PromptScreen)
        assert "Dynamic prompt" in widget_text(app.screen.query_one("#prompt-title"))


# --------------------------------------------------------------------------- CF-6 / CF-5: widths and whitespace

WIDTH_SHORTCUTS = ["a", "bb", "ccc", "dddd", "eeeee", "ffffff", "ggggggg", "hhhhhhhh", "iiiiiiiii", "jjjjjjjjjj"]


async def test_the_computed_width_of_a_cell_equals_its_rendered_width_for_shortcuts_of_every_length():
    items = [leaf(f"Item {n}", sc, current_value=n if n % 2 else None) for n, sc in enumerate(WIDTH_SHORTCUTS, 1)]
    items += [leaf("Spaced", "  s  "), MenuItem("Sub", "u", children=[leaf("c", "c")])]
    items += [MenuItem(lambda: "Dyn", shortcut="dy", current_value=lambda: "v", action=lambda: None)]
    app = CLIApp(menu(*items))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        nav.selected = len(nav.items) - 1  # a selected cell is drawn narrower, so keep it out of the comparison
        for i, item in enumerate(nav.items[:-1]):
            assert nav._compute_item_width(item) == len(nav._render_item(i, item).plain), item.label
        exit_cell = nav.items[-1]
        assert isinstance(exit_cell, _NavCell)
        nav.selected = 0
        assert nav._compute_item_width(exit_cell) == len(nav._render_item(len(nav.items) - 1, exit_cell).plain)


async def test_a_longer_shortcut_widens_the_cell_by_exactly_its_length():
    app = CLIApp(menu(leaf("Same", "a"), leaf("Same", "abcdef")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        assert nav._compute_item_width(nav.items[1]) - nav._compute_item_width(nav.items[0]) == 5


@pytest.mark.parametrize("width", [30, 47, 60])
async def test_rows_never_hold_more_than_the_terminal_width(width):
    items = [leaf(f"Label {n}", chr(97 + n) * (n % 5 + 1)) for n in range(12)]
    app = CLIApp(menu(*items))
    async with app.run_test(size=(width, 30)) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        nav.selected = len(nav.items) - 1
        for row in nav._layout_rows(nav.size.width):
            drawn = sum(len(nav._render_item(i, nav.items[i]).plain) for i in row if i != nav.selected)
            assert drawn <= nav.size.width or len(row) == 1


async def test_a_shortcut_with_surrounding_whitespace_is_displayed_stripped_and_works_typed():
    calls = Calls()
    app = CLIApp(menu(MenuItem("Padded", shortcut="  x ", action=calls.action("padded"))))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = widget_text(nav_of(app))
        assert "x Padded" in text and " x  Padded" not in text
        await type_command(pilot, "x")
        await type_command(pilot, " X ")
        assert calls.names == ["padded", "padded"]


# --------------------------------------------------------------------------- CF-7: the sentinels

@pytest.mark.parametrize("description", ["__exit__", "__back__"])
async def test_a_consumer_item_whose_description_looks_like_a_sentinel_runs_its_action(description):
    calls = Calls()
    app = CLIApp(menu(
        MenuItem("Consumer", shortcut="c", description=description, action=calls.action("consumer")),
        MenuItem("Sub", shortcut="s", description=description, children=[leaf("Inner", "i", calls.action("inner"))]),
    ))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "c")
        await type_command(pilot, "1")
        await pilot.press("enter")
        await pilot.pause()
        assert calls.names == ["consumer"] * 3 and app.is_running and app.return_code is None
        await type_command(pilot, "s")
        assert dash.location == "Home|Sub" and app.is_running
        await type_command(pilot, "i")
        assert calls.names[-1] == "inner" and dash.location == "Home|Sub"


@pytest.mark.parametrize("description", ["__exit__", "__back__"])
async def test_a_consumer_item_whose_description_looks_like_a_sentinel_is_drawn_like_any_other_item(description):
    app = CLIApp(menu(MenuItem("Consumer", shortcut="c", description=description, action=lambda: None)))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = nav_of(app)
        assert nav.selected == 0 and not isinstance(nav.items[0], _NavCell)
        selected_style = str(nav._render_item(0, nav.items[0]).style)
        assert _ORANGE in selected_style and _DIM_FG not in selected_style
        nav.selected = 1
        assert isinstance(nav.items[1], _NavCell) and _DIM_FG in str(nav._render_item(1, nav.items[1]).style)


async def test_the_real_exit_cell_quits_when_selected_and_confirmed_with_enter():
    app = CLIApp(menu(leaf("A", "a"), leaf("C", "c")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down", "down", "enter")
        await wait_for(lambda: app.return_code is not None, what="app to exit")
        assert app.return_code == 0


async def test_the_real_back_cell_goes_up_when_selected_and_confirmed_with_enter():
    calls = Calls()
    app = CLIApp(menu(MenuItem("Sub", shortcut="s", children=[leaf("Inner", "i", calls.action("inner"))])))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "s")
        assert isinstance(nav_of(app).items[-1], _NavCell) and nav_of(app).items[-1].kind == "back"
        await pilot.press("down", "enter")
        await pilot.pause()
        assert dash.location == "Home" and calls.names == [] and app.is_running
        assert nav_of(app).items[-1].kind == "exit"


# --------------------------------------------------------------------------- CF-2: dispatch through RESERVED_ACTIONS

async def reserved_setup(pilot) -> None:
    pilot.app.panel.log("marker-line")
    await type_command(pilot, "s")  # into the submenu, so "back" has somewhere to go
    assert pilot.app.query_one("#dashboard", Dashboard).location == "Home|Sub"


@pytest.mark.parametrize("case", ["as-is", "upper"])
@pytest.mark.parametrize("command, action", sorted(RESERVED_ACTIONS.items()))
async def test_every_reserved_command_triggers_its_mapped_action(command, action, case):
    app = CLIApp(menu(MenuItem("Sub", shortcut="s", children=[leaf("Inner", "i")])))
    typed = command if case == "as-is" else command.upper()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await reserved_setup(pilot)
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, typed)
        if action == "quit":
            await wait_for(lambda: app.return_code is not None, what="app to exit")
        elif action == "back":
            assert dash.location == "Home" and app.is_running
        elif action == "clear":
            assert panel_lines(app) == [] and dash.location == "Home|Sub"
        else:
            assert "Navigate menu items" in await read_panel(pilot)
        if action != "quit":
            assert "Unknown command" not in panel_text(app)


# --------------------------------------------------------------------------- CF-14: a pipe in a label

async def test_a_label_containing_a_pipe_is_one_crumb():
    app = CLIApp(menu(MenuItem("a|b", shortcut="s", children=[MenuItem("c|d|e", shortcut="t", children=[leaf("Leaf", "l")])])))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "s")
        await type_command(pilot, "t")
        assert dash.render().plain.startswith(" Home › a|b › c|d|e\n")
        assert dash.crumbs == ("Home", "a|b", "c|d|e")
        assert dash.location == "Home|a|b|c|d|e"
        assert "Home › a|b › c|d|e" in widget_text(dash)


async def test_the_dashboard_falls_back_to_splitting_location_while_crumbs_is_unset():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        dash = app.query_one("#dashboard", Dashboard)
        dash.crumbs = None
        dash.location = "x|y|z"
        assert dash.render().plain.startswith(" x › y › z\n")
        dash.crumbs = ("x|y", "z")
        assert dash.render().plain.startswith(" x|y › z\n")


# --------------------------------------------------------------------------- CF-13: the prompt dialog hint

@pytest.mark.parametrize("secret", [False, True])
async def test_the_prompt_dialog_shows_its_enter_and_esc_hint(secret):
    app = CLIApp(menu(MenuItem("Ask", shortcut="a", prompt="Value:", secret=secret, action=lambda v: None)))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "a")
        assert isinstance(app.screen, PromptScreen)
        hint = app.screen.query_one("#prompt-hint")
        rendered = "\n".join(widget_lines(hint))
        assert "Enter" in rendered and "Esc" in rendered and "confirm" in rendered and "cancel" in rendered
        assert any("Enter" in ln and "Esc" in ln for ln in widget_lines(hint))


# --------------------------------------------------------------------------- CF-15: "+ Enter" in the hint and the help table

def test_the_hint_text_is_the_two_pinned_lines():
    first, second = Text.from_markup(_HINT_TEXT).plain.split("\n")
    assert first == HINT_LINE_1 and second == HINT_LINE_2
    assert len(first) == 72 and len(second) == 73


def test_the_hints_quit_entry_says_plus_enter_and_comes_first_on_line_two():
    first, second = Text.from_markup(_HINT_TEXT).plain.split("\n")
    assert "q + Enter  quit" in second and second.lstrip().startswith("q + Enter")
    assert "type a shortcut + Enter" in first


async def test_the_hint_fits_an_80_column_terminal_without_clipping():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        hint = app.query_one("#hint")
        assert hint.size.height == 2
        assert [ln.strip() for ln in widget_lines(hint) if ln.strip()] == [HINT_LINE_1.strip(), HINT_LINE_2.strip()]


async def test_the_help_table_lists_every_typed_command_with_plus_enter():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "help")
        lines = panel_lines(app)
        rows = {
            "b / back + Enter": "Go back (typed command)",
            "q / quit / exit + Enter": "Quit the application",
            "clear + Enter": "Clear the display panel",
            "help  /  ? + Enter": "Show this help",
        }
        for command, action in rows.items():
            assert any(command in ln and action in ln for ln in lines), (command, lines)
