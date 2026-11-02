"""F8: shortcut + Enter, case-insensitive reserved commands, conflict detection and wording."""
from __future__ import annotations

import warnings

import pytest
from rich.text import Text
from textual.widgets import Input

from cli_interface import ShortcutConflictWarning
from cli_interface.app import CLIApp
from cli_interface.menu import RESERVED_COMMANDS, MenuItem, MenuState, _NavCell, find_shortcut_conflicts
from cli_interface.theme import _HINT_TEXT, _YELLOW
from cli_interface.widgets import Dashboard, NavBar
from helpers import (
    SIZE, Calls, build_demo_app, color_of, leaf, line_segments, menu, panel_lines, panel_text, quiet_app, read_panel,
    wait_for, widget_text,
)

# ============================================================================ find_shortcut_conflicts


def test_reserved_commands_value():
    assert RESERVED_COMMANDS == frozenset({"q", "quit", "exit", "b", "back", "clear", "help", "?", "stop"})


def test_conflict_messages_cover_reserved_duplicates_case_and_levels():
    root = menu(
        leaf("Quit item", "q"), leaf("Word", "Quit"), leaf("X1", "x"), leaf("X2", "X"), leaf("Other", "o"),
        MenuItem("NoShortcut", action=lambda: None),
        MenuItem("Sub", "s", children=[leaf("Sub X", "x"), leaf("Sub O", "o"), leaf("H", "HELP"), leaf("Q1", "?")]),
        label="Root",
    )
    assert find_shortcut_conflicts(root) == [
        "Root: shortcut 'q' on 'Quit item' is a reserved command and will never reach this item",
        "Root: shortcut 'quit' on 'Word' is a reserved command and will never reach this item",
        "Root: shortcut 'x' is used by 'X1', 'X2'; only the first is reachable by shortcut",
        "Root > Sub: shortcut 'help' on 'H' is a reserved command and will never reach this item",
        "Root > Sub: shortcut '?' on 'Q1' is a reserved command and will never reach this item",
    ]


def test_the_same_shortcut_at_different_levels_is_allowed():
    root = menu(leaf("A", "a"), MenuItem("B", "k", children=[leaf("A2", "a")]), label="R")
    assert find_shortcut_conflicts(root) == []


def test_clean_tree_and_leaf_root_yield_nothing():
    assert find_shortcut_conflicts(menu(leaf("A", "a"), leaf("B", "c"))) == []
    assert find_shortcut_conflicts(MenuItem("leaf")) == []


def test_a_key_that_is_reserved_and_shared_gets_one_reserved_message_per_item_and_no_duplicate_message():
    problems = find_shortcut_conflicts(menu(leaf("a", "q"), leaf("b", "Q")))
    assert len(problems) == 2
    assert all("reserved command" in p and "only the first" not in p for p in problems)


def test_cyclic_trees_terminate():
    cycle = menu(leaf("a", "a"), label="C")
    cycle.children.append(cycle)
    assert find_shortcut_conflicts(cycle) == []
    inner = menu(leaf("a", "x"), leaf("b", "x"), label="C2")
    sub = MenuItem("S", "s", children=[inner])
    inner.children.append(sub)
    problems = find_shortcut_conflicts(menu(sub, label="Top"))
    assert len(problems) == 1 and "Top > S > C2" in problems[0]


def test_select_by_shortcut_stays_case_insensitive_and_first_match_wins():
    state = MenuState(menu(leaf("first", "Z"), leaf("second", "z")))
    assert state.select_by_shortcut("z").label == "first"
    assert state.select_by_shortcut("Z").label == "first"
    assert state.select_by_shortcut("nope") is None


# ============================================================================ construction-time behaviour

CONFLICTED = (leaf("Quit it", "q"), leaf("X1", "x"), leaf("X2", "X"))


def test_conflicts_raise_one_user_warning_per_problem_pointing_at_the_caller():
    with pytest.warns(ShortcutConflictWarning) as record:
        CLIApp(menu(*CONFLICTED))
    messages = [str(w.message) for w in record]
    assert len(messages) == 2
    assert any("reserved command" in m for m in messages) and any("only the first is reachable" in m for m in messages)
    assert all(w.filename == __file__ for w in record)


def test_a_clean_menu_emits_no_warnings_with_or_without_strict_mode():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        CLIApp(menu(leaf("A", "a")))
        CLIApp(menu(leaf("A", "a")), strict_shortcuts=True)


def test_strict_shortcuts_raises_value_error_listing_every_problem():
    root = menu(*CONFLICTED)
    expected = "\n".join(find_shortcut_conflicts(root))
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # strict mode must raise ValueError, not warn
        with pytest.raises(ValueError) as exc:
            CLIApp(root, strict_shortcuts=True)
    assert str(exc.value) == expected and "\n" in expected


def flat(text: str) -> str:
    return " ".join(text.split())  # panel rows wrap; rejoin them


async def test_each_problem_is_logged_to_the_panel_once_at_warning_level():
    app = quiet_app(*CONFLICTED)
    async with app.run_test(size=SIZE) as pilot:
        text = flat(await read_panel(pilot))
        assert text == " ".join(find_shortcut_conflicts(menu(*CONFLICTED))), "exactly the problems, each once, nothing else"
        first_segment_style = line_segments(app, "Home: shortcut 'q'")[0][1]
        assert color_of(first_segment_style) == "#e5c07b"


@pytest.mark.parametrize("pre_super", [False, True])
async def test_panel_warnings_are_not_duplicated_when_a_subclass_runs_on_mount_via_super(pre_super):
    class Sub(CLIApp):
        def on_mount(self) -> None:
            if pre_super:
                self.push_log("before super")
            super().on_mount()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        app = Sub(menu(*CONFLICTED))
    async with app.run_test(size=SIZE) as pilot:
        text = flat(await read_panel(pilot))
        problems = " ".join(find_shortcut_conflicts(menu(*CONFLICTED)))
        assert text == (f"before super {problems}" if pre_super else problems)


async def test_a_clean_menu_logs_nothing_at_mount(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        assert await read_panel(pilot) == ""


async def test_first_duplicate_wins_and_matching_is_case_insensitive():
    calls = Calls()
    app = quiet_app(leaf("X1", "x", calls.action("X1")), leaf("X2", "X", calls.action("X2")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("x", "enter")
        await pilot.press("X", "enter")
        await pilot.pause()
        assert calls.names == ["X1", "X1"]


# ============================================================================ reserved commands, any case

def variants(cmd: str) -> list[str]:
    return sorted({cmd, cmd.upper(), cmd.title()})


async def type_command(pilot, text: str) -> None:
    pilot.app.query_one("#command-input", Input).value = text
    await pilot.press("enter")
    await pilot.pause()


@pytest.mark.parametrize("cmd", [v for c in ("q", "quit", "exit") for v in variants(c)])
async def test_quit_commands_exit_in_any_case(make_app, cmd):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, cmd)
        await wait_for(lambda: app.return_code is not None, what="app to exit")
        assert app.return_code == 0


@pytest.mark.parametrize("cmd", [v for c in ("b", "back") for v in variants(c)])
async def test_back_commands_go_up_one_level_in_any_case(make_app, cmd):
    app = make_app(MenuItem("Sub", shortcut="s", children=[leaf("Leaf", "l")]))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        dash = app.query_one("#dashboard", Dashboard)
        assert dash.crumbs == ("Home", "Sub")
        await type_command(pilot, cmd)
        assert dash.crumbs == ("Home",) and app.is_running


@pytest.mark.parametrize("cmd", variants("clear"))
async def test_clear_command_empties_the_panel_in_any_case(make_app, cmd):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        app.panel.log("marker-line")
        await pilot.pause()
        assert "marker-line" in panel_text(app)
        await type_command(pilot, cmd)
        assert panel_lines(app) == []


@pytest.mark.parametrize("cmd", [v for c in ("help", "?") for v in variants(c)])
async def test_help_commands_show_the_help_table_in_any_case(make_app, cmd):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, cmd)
        assert "Key / Command" in panel_text(app) and "Navigate menu items" in panel_text(app)


@pytest.mark.parametrize("cmd", sorted(RESERVED_COMMANDS))
@pytest.mark.parametrize("case", ["as-is", "upper"])
async def test_a_consumer_shortcut_equal_to_a_reserved_command_never_runs(cmd, case):
    calls = Calls()
    typed = cmd if case == "as-is" else cmd.upper()
    app = quiet_app(MenuItem("Consumer", shortcut=cmd, action=calls.action("consumer")), leaf("Other", "o"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, typed)
        assert calls.names == [], f"{typed!r} reached the consumer item instead of the reserved command"
        assert "Unknown command" not in panel_text(app)


@pytest.mark.parametrize("word", ["quitt", "exi", "helpme", "backk", "clears", "bb"])
async def test_near_misses_of_reserved_words_are_ordinary_shortcuts(word):
    calls = Calls()
    app = CLIApp(menu(MenuItem("Near", shortcut=word, action=calls.action("near"))))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, word)
        assert calls.names == ["near"] and app.is_running


# ============================================================================ single key vs key + Enter

async def test_a_shortcut_key_alone_does_nothing_and_with_enter_it_fires():
    calls = Calls()
    app = CLIApp(menu(MenuItem("D", shortcut="d", action=calls.action("D"))))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d")
        await pilot.pause()
        assert calls.names == []
        assert app.query_one("#command-input", Input).value == "d"
        await pilot.press("enter")
        await pilot.pause()
        assert calls.names == ["D"]
        assert app.query_one("#command-input", Input).value == ""


async def test_a_single_navigation_key_does_not_navigate_until_enter(make_app):
    app = make_app(MenuItem("View", shortcut="v", children=[leaf("Leaf", "l")]))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await pilot.press("v")
        await pilot.pause()
        assert dash.crumbs == ("Home",) and app.query_one("#command-input", Input).value == "v"
        await pilot.press("enter")
        await pilot.pause()
        assert dash.crumbs == ("Home", "View")


async def test_shortcut_matching_ignores_case_and_surrounding_spaces():
    calls = Calls()
    app = CLIApp(menu(MenuItem("D", shortcut="d", action=calls.action("D"))))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "D")
        await type_command(pilot, "  d  ")
        assert calls.names == ["D", "D"]


async def test_empty_input_plus_enter_runs_the_selected_item():
    calls = Calls()
    app = CLIApp(menu(MenuItem("First", shortcut="f", action=calls.action("first"))))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("enter")
        await pilot.pause()
        assert calls.names == ["first"]


def test_cliapp_defines_no_on_key_handler():
    assert "on_key" not in vars(CLIApp)
    assert not hasattr(CLIApp, "on_key")


# ============================================================================ digits

async def test_a_number_plus_enter_activates_by_position_and_bad_numbers_are_unknown():
    calls = Calls()
    app = CLIApp(menu(MenuItem("One", shortcut="x", action=calls.action("one")), MenuItem("Two", shortcut="y", action=calls.action("two"))))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "2")
        await type_command(pilot, "1")
        assert calls.names == ["two", "one"]
        for bad in ("0", "3", "99", "-1", "1.5"):
            await type_command(pilot, bad)
        text = panel_text(app)
        for bad in ("0", "3", "99", "-1", "1.5"):
            assert f"Unknown command: {bad!r}" in text
        assert calls.names == ["two", "one"] and app.is_running


async def test_a_superscript_digit_is_an_unknown_command_not_a_crash(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "²")
        assert "Unknown command: '²'" in panel_text(app)
        assert app.is_running and app.return_code is None
        await type_command(pilot, "1")
        assert "Executed: A" in panel_text(app)


async def test_a_non_ascii_decimal_digit_selects_by_position_when_in_range():
    calls = Calls()
    items = [MenuItem(n, shortcut=s, action=calls.action(n)) for n, s in (("One", "x"), ("Two", "y"), ("Three", "z"))]
    app = CLIApp(menu(*items))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "٣")  # ARABIC-INDIC DIGIT THREE
        assert calls.names == ["Three"]


async def test_a_non_ascii_decimal_digit_out_of_range_is_unknown():
    app = CLIApp(menu(leaf("One", "x"), leaf("Two", "y")))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "٣")
        assert "Unknown command: '٣'" in panel_text(app)
        assert app.is_running


# ============================================================================ wording

def test_hint_text_has_the_new_wording_within_its_width_budget():
    first, second = Text.from_markup(_HINT_TEXT).plain.split("\n")
    assert "type a shortcut + Enter" in first
    assert "or command" not in first and "type a shortcut or command" not in _HINT_TEXT
    assert len(first) == 72 and len(second) <= 85


async def test_the_hint_widget_shows_the_new_wording(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        hint = widget_text(app.query_one("#hint"))
        assert "type a shortcut + Enter" in hint and "or command" not in hint


async def test_help_table_has_the_exact_new_rows_and_dropped_the_old_ones(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "help")
        lines = panel_lines(app)
        shortcut_row = next(ln for ln in lines if "<shortcut> + Enter" in ln)
        number_row = next(ln for ln in lines if "<number> + Enter" in ln)
        assert "Activate item by its shortcut (shown in yellow)" in shortcut_row
        assert "Activate item by position" in number_row
        text = "\n".join(lines)
        assert "<letter>" not in text and "1 … 9" not in text
        for row in ("Navigate menu items", "Go back one level", "Quit the application", "Show this help", "Clear the display panel"):
            assert row in text


# ============================================================================ every displayed shortcut works

def displayed_shortcut(nav: NavBar, i: int) -> str | None:
    """The shortcut NavBar actually draws for item i (its yellow spans), not MenuItem.shortcut."""
    cell = nav._render_item(i, nav.items[i])
    drawn = "".join(cell.plain[s.start:s.end] for s in cell.spans if str(s.style) == _YELLOW)
    return drawn or None


def gadget_menu(calls: Calls) -> CLIApp:
    deep = MenuItem("Deep", "dd", children=[leaf("Bottom", "x", calls.action("Bottom"))])
    gadgets = MenuItem("Gadgets", "go", children=[leaf("Inner", "i", calls.action("Inner")), deep])
    return CLIApp(menu(
        leaf("Alpha", "a", calls.action("Alpha")),
        leaf("Zed", "Z", calls.action("Zed")),
        gadgets,
        leaf("Plain", "", calls.action("Plain")),
    ))


# (level id, labels to enter, number of cells including the sentinel)
LEVELS = [("root", (), 5), ("gadgets", ("Gadgets",), 3), ("deep", ("Gadgets", "Deep"), 2)]
CELLS = [pytest.param(path, size, i, id=f"{name}-{i}") for name, path, size in LEVELS for i in range(size)]


async def enter_by_displayed_shortcut(pilot, labels: tuple[str, ...]) -> None:
    nav = pilot.app.query_one("#nav-bar", NavBar)
    for label in labels:
        i = next(n for n, item in enumerate(nav.items) if item.label == label)
        shortcut = displayed_shortcut(nav, i)
        assert shortcut, f"{label!r} displays no shortcut"
        await type_command(pilot, shortcut)


def is_sentinel(item: MenuItem) -> bool:
    return isinstance(item, _NavCell)


def nav_kind(item: MenuItem) -> str | None:
    return item.kind if isinstance(item, _NavCell) else None


@pytest.mark.parametrize("path, size, i", CELLS)
async def test_every_displayed_shortcut_activates_its_item(path, size, i):
    calls = Calls()
    app = gadget_menu(calls)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await enter_by_displayed_shortcut(pilot, path)
        dash = app.query_one("#dashboard", Dashboard)
        nav = app.query_one("#nav-bar", NavBar)
        here = ("Home", *path)
        assert dash.crumbs == here and len(nav.items) == size
        assert is_sentinel(nav.items[-1]) and (nav_kind(nav.items[-1]) == "exit") is (not path)
        item = nav.items[i]
        shortcut = displayed_shortcut(nav, i)
        if item.label == "Plain":
            assert shortcut is None, "an item without a shortcut must not display one"
            return
        assert shortcut, f"{item.label!r} displays no shortcut"
        await type_command(pilot, shortcut)
        if nav_kind(item) == "exit":
            await wait_for(lambda: app.return_code is not None, what="the app to exit")
            assert app.return_code == 0
        elif nav_kind(item) == "back":
            assert dash.crumbs == ("Home", *path[:-1])
        elif item.children:
            assert dash.crumbs == (*here, item.label)
        else:
            assert calls.names == [item.label]
        assert "Unknown command" not in panel_text(app)


@pytest.mark.parametrize("path", [(), ("Gadgets",), ("Gadgets", "Deep")], ids=["root", "gadgets", "deep"])
async def test_sentinel_shortcuts_are_reserved_commands(path):
    app = gadget_menu(Calls())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await enter_by_displayed_shortcut(pilot, path)
        nav = app.query_one("#nav-bar", NavBar)
        sentinel = displayed_shortcut(nav, len(nav.items) - 1)
        assert sentinel is not None and sentinel.lower() in RESERVED_COMMANDS


async def test_back_cell_reads_b_back_and_the_escape_key_still_goes_back():
    app = CLIApp(menu(MenuItem("Sub", "s", children=[leaf("Leaf", "l")])))
    async with app.run_test(size=SIZE) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        await type_command(pilot, "s")
        assert dash.crumbs == ("Home", "Sub")
        shown = widget_text(app.query_one("#nav-bar", NavBar))
        assert "b Back" in shown and "esc" not in shown.lower()
        await pilot.press("escape")
        await pilot.pause()
        assert dash.crumbs == ("Home",)


async def test_demo_walk_using_only_the_shortcuts_the_nav_bar_displays():
    app = build_demo_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        dash = app.query_one("#dashboard", Dashboard)
        nav = app.query_one("#nav-bar", NavBar)
        await enter_by_displayed_shortcut(pilot, ("Settings", "Audio"))
        assert dash.crumbs == ("Home", "Settings", "Audio")
        back = displayed_shortcut(nav, len(nav.items) - 1)
        assert nav_kind(nav.items[-1]) == "back" and back
        await type_command(pilot, back)
        assert dash.crumbs == ("Home", "Settings")
        await type_command(pilot, displayed_shortcut(nav, len(nav.items) - 1))
        assert dash.crumbs == ("Home",)
        exit_shortcut = displayed_shortcut(nav, len(nav.items) - 1)
        assert nav_kind(nav.items[-1]) == "exit" and exit_shortcut
        await type_command(pilot, exit_shortcut)
        await wait_for(lambda: app.return_code is not None, what="the app to exit")
        assert app.return_code == 0
