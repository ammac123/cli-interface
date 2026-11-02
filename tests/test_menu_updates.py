"""P1.2b / CF-4: set_menu(), refresh_menu(), go_home() and the shared menu validation."""
from __future__ import annotations

import asyncio

import pytest

from cli_interface import CLIApp, MenuItem, ShortcutConflictWarning, find_shortcut_conflicts
from cli_interface.menu import _NavCell, item_label
from cli_interface.widgets import Dashboard, NavBar, PromptScreen
from helpers import (
    SIZE, Calls, color_of, leaf, line_segments, menu, panel_lines, panel_text, read_panel, type_command,
)

CONFLICTED = (leaf("Quit it", "q"), leaf("X1", "x"), leaf("X2", "X"))


def flat(text: str) -> str:
    return " ".join(text.split())


def view(app: CLIApp) -> tuple[Dashboard, NavBar]:
    return app.query_one("#dashboard", Dashboard), app.query_one("#nav-bar", NavBar)


def shown(nav: NavBar) -> list[str]:
    return [item_label(item) for item in nav.items]


def deep_menu(calls: Calls | None = None) -> MenuItem:
    calls = calls or Calls()
    deepest = MenuItem("Deepest", shortcut="d", children=[leaf("Bottom", "b1", calls.action("bottom")), leaf("Floor", "f")])
    middle = MenuItem("Middle", shortcut="m", children=[leaf("Mid leaf", "l"), deepest])
    return menu(leaf("First", "1x"), MenuItem("Top", shortcut="t", children=[leaf("Top leaf", "tl"), middle]), label="Home")


async def enter_deepest(pilot) -> None:
    for shortcut in ("t", "m", "d"):
        await type_command(pilot, shortcut)
    assert pilot.app.query_one("#dashboard", Dashboard).crumbs == ("Home", "Top", "Middle", "Deepest")


# --------------------------------------------------------------------------- set_menu on a running app

async def test_set_menu_returns_to_the_new_root_with_the_first_item_selected():
    old, new = Calls(), Calls()
    app = CLIApp(menu(
        MenuItem("Sub", shortcut="s", children=[leaf("Old leaf", "o", old.action("old")), leaf("Second", "t")]),
        label="Old",
    ))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await type_command(pilot, "s")
        await pilot.press("down")
        assert nav.selected == 1 and dash.crumbs == ("Old", "Sub")
        app.set_menu(menu(leaf("New A", "n", new.action("A")), leaf("New B", "m"), label="New"))
        await pilot.pause()
        assert dash.crumbs == ("New",)
        assert nav.selected == 0 and shown(nav) == ["New A", "New B", "Exit"]
        assert isinstance(nav.items[-1], _NavCell) and nav.items[-1].kind == "exit"
        await type_command(pilot, "o")
        assert "Unknown command: 'o'" in panel_text(app) and old.names == []
        await type_command(pilot, "n")
        assert new.names == ["A"]
        await pilot.press("enter")  # the selected item is the first one again
        assert new.names == ["A", "A"]


async def test_set_menu_leaves_the_output_panel_alone():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        app.panel.log("keep this line")
        app.panel.log("and this one", "WARNING")
        before = panel_lines(app)
        app.set_menu(menu(leaf("B", "n"), label="Other"))
        app.refresh_menu()
        app.go_home()
        await pilot.pause()
        assert panel_lines(app) == before


async def test_set_menu_accepts_a_menu_that_is_a_bare_leaf():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        app.set_menu(MenuItem("Lonely"))
        await pilot.pause()
        dash, nav = view(app)
        assert dash.crumbs == ("Lonely",) and shown(nav) == ["Exit"]


async def test_set_menu_warns_at_the_callers_line_and_logs_each_problem_to_the_panel():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        with pytest.warns(ShortcutConflictWarning) as record:
            app.set_menu(menu(*CONFLICTED))
        assert len(record) == 2 and all(w.filename == __file__ for w in record)
        assert flat(await read_panel(pilot)) == " ".join(find_shortcut_conflicts(menu(*CONFLICTED)))
        assert color_of(line_segments(app, "Home: shortcut 'q'")[0][1]) == "#e5c07b"


async def test_set_menu_warns_afresh_for_a_new_tree_even_when_the_old_one_had_the_same_problem():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE):
        for _ in range(2):
            with pytest.warns(ShortcutConflictWarning) as record:
                app.set_menu(menu(*CONFLICTED))
            assert len(record) == 2


async def test_strict_mode_raises_value_error_and_keeps_the_old_menu():
    calls = Calls()
    app = CLIApp(menu(leaf("Old", "o", calls.action("old")), label="Old root"), strict_shortcuts=True)
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        before = panel_lines(app)
        bad = menu(*CONFLICTED)
        with pytest.raises(ValueError) as error:
            app.set_menu(bad)
        assert str(error.value) == "\n".join(find_shortcut_conflicts(bad))
        await pilot.pause()
        assert dash.crumbs == ("Old root",) and shown(nav) == ["Old", "Exit"] and panel_lines(app) == before
        await type_command(pilot, "o")
        assert calls.names == ["old"]
        app.set_menu(menu(leaf("Clean", "c"), label="Clean root"))  # a clean menu is still accepted
        await pilot.pause()
        assert dash.crumbs == ("Clean root",)


async def test_a_warning_escalated_to_an_error_leaves_the_old_menu_in_place_and_nothing_queued():
    app = CLIApp(menu(leaf("Old", "o")))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        with pytest.raises(ShortcutConflictWarning):  # the pytest filters turn it into an exception
            app.set_menu(menu(*CONFLICTED))
        await pilot.pause()
        assert dash.crumbs == ("Home",) and shown(nav) == ["Old", "Exit"] and panel_lines(app) == []
        with pytest.warns(ShortcutConflictWarning) as record:  # the problems were not recorded as reported
            app.set_menu(menu(*CONFLICTED))
        assert len(record) == 2


@pytest.mark.parametrize("bad", [None, "Home", 3, ["a"], MenuItem, {"label": "x"}])
async def test_set_menu_rejects_anything_but_a_menu_item(bad):
    app = CLIApp(menu(leaf("A", "a")))
    with pytest.raises(TypeError):
        app.set_menu(bad)
    async with app.run_test(size=SIZE) as pilot:
        with pytest.raises(TypeError):
            app.set_menu(bad)
        await pilot.pause()
        assert shown(view(app)[1]) == ["A", "Exit"]


@pytest.mark.parametrize("bad", [None, "Home", 3, ["a"], MenuItem])
def test_the_constructor_rejects_anything_but_a_menu_item(bad):
    with pytest.raises(TypeError):
        CLIApp(bad)


# --------------------------------------------------------------------------- before the app starts and after it ends

async def test_set_menu_before_the_app_starts_swaps_the_tree_and_warns_at_once_but_logs_on_start():
    app = CLIApp(menu(leaf("A", "a")))
    with pytest.warns(ShortcutConflictWarning) as record:
        app.set_menu(menu(*CONFLICTED, label="Swapped"))
    assert len(record) == 2 and all(w.filename == __file__ for w in record)
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        assert dash.crumbs == ("Swapped",) and shown(nav) == ["Quit it", "X1", "X2", "Exit"]
        text = flat(await read_panel(pilot))
        assert text == " ".join(find_shortcut_conflicts(menu(*CONFLICTED, label="Swapped")))


async def test_a_strict_conflict_before_the_app_starts_raises_and_changes_nothing():
    app = CLIApp(menu(leaf("A", "a")), strict_shortcuts=True)
    with pytest.raises(ValueError):
        app.set_menu(menu(*CONFLICTED))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert shown(view(app)[1]) == ["A", "Exit"] and panel_lines(app) == []


def test_the_menu_methods_are_legal_before_the_app_starts():
    app = CLIApp(menu(leaf("A", "a")))
    app.refresh_menu()
    app.go_home()
    app.set_menu(menu(leaf("B", "n")))
    app.refresh_menu()
    app.go_home()


async def test_the_menu_methods_are_legal_after_the_app_has_exited():
    app = CLIApp(menu(leaf("A", "a")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    app.refresh_menu()
    app.go_home()
    app.set_menu(menu(leaf("B", "n")))
    with pytest.raises(TypeError):
        app.set_menu(None)


# --------------------------------------------------------------------------- refresh_menu

async def test_refresh_menu_shows_in_place_edits_and_keeps_the_stack_and_selection():
    first, second, third = leaf("One", "a"), leaf("Two", "b1"), leaf("Three", "c")
    sub = MenuItem("Sub", shortcut="s", children=[first, second, third])
    app = CLIApp(menu(sub))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await type_command(pilot, "s")
        await pilot.press("down", "down")
        assert nav.selected == 2 and dash.crumbs == ("Home", "Sub")
        second.label = "Two renamed"
        second.current_value = 5
        sub.children.append(leaf("Four", "d"))
        sub.label = "Sub renamed"
        app.refresh_menu()
        await pilot.pause()
        assert dash.crumbs == ("Home", "Sub renamed")
        assert shown(nav) == ["One", "Two renamed", "Three", "Four", "Back"]
        assert nav.selected == 2
        assert "b1 Two renamed (5)" in "\n".join(nav.render().plain.splitlines())


async def test_refresh_menu_falls_back_to_the_nearest_level_that_still_exists():
    root = deep_menu()
    app = CLIApp(root)
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await enter_deepest(pilot)
        middle = root.children[1].children[1]
        middle.children.pop()  # the Deepest level is gone from Middle
        app.refresh_menu()
        await pilot.pause()
        assert dash.crumbs == ("Home", "Top", "Middle") and shown(nav) == ["Mid leaf", "Back"]
        root.children.pop()  # now Top is gone as well
        app.refresh_menu()
        await pilot.pause()
        assert dash.crumbs == ("Home",) and shown(nav) == ["First", "Exit"] and nav.selected == 0


async def test_refresh_menu_clamps_the_selection_when_items_were_removed():
    items = [leaf(f"Item {n}", f"k{n}") for n in range(5)]
    root = menu(*items)
    app = CLIApp(root)
    async with app.run_test(size=SIZE) as pilot:
        _, nav = view(app)
        await pilot.press("down", "down", "down", "down")
        assert nav.selected == 4
        del root.children[2:]
        app.refresh_menu()
        await pilot.pause()
        assert shown(nav) == ["Item 0", "Item 1", "Exit"] and nav.selected == 2


async def test_refresh_menu_warns_only_for_new_problems_and_again_after_one_disappears():
    items = [leaf("X1", "x"), leaf("X2", "k")]
    root = menu(*items)
    app = CLIApp(root)
    async with app.run_test(size=SIZE) as pilot:
        app.refresh_menu()  # clean: a warning would fail the test through the pytest filters
        items[1].shortcut = "x"
        with pytest.warns(ShortcutConflictWarning) as record:
            app.refresh_menu()
        assert len(record) == 1 and record[0].filename == __file__
        app.refresh_menu()  # the same problem again: silent
        app.refresh_menu()
        items[1].shortcut = "k"
        app.refresh_menu()  # fixed: silent
        items[1].shortcut = "x"
        with pytest.warns(ShortcutConflictWarning) as record:
            app.refresh_menu()
        assert len(record) == 1
        root.children.append(leaf("Q", "q"))
        with pytest.warns(ShortcutConflictWarning) as record:
            app.refresh_menu()
        assert len(record) == 1 and "reserved command" in str(record[0].message)
        text = flat(await read_panel(pilot))
        assert text.count("only the first is reachable") == 2 and text.count("reserved command") == 1


async def test_strict_mode_refresh_menu_raises_before_touching_the_view():
    root = deep_menu()
    app = CLIApp(root, strict_shortcuts=True)
    async with app.run_test(size=SIZE) as pilot:
        dash, _ = view(app)
        await enter_deepest(pilot)
        root.children.pop()  # Top is gone ...
        root.children.append(leaf("Dup", "1x"))  # ... and a duplicate shortcut appeared
        with pytest.raises(ValueError, match="1x"):
            app.refresh_menu()
        assert dash.crumbs == ("Home", "Top", "Middle", "Deepest")
        root.children.pop()
        app.refresh_menu()
        await pilot.pause()
        assert dash.crumbs == ("Home",)


# --------------------------------------------------------------------------- go_home

async def test_go_home_from_three_levels_down_returns_to_the_root():
    calls = Calls()
    root = deep_menu(calls)
    app = CLIApp(root)
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await enter_deepest(pilot)
        await pilot.press("down")
        app.panel.log("untouched")
        before = panel_lines(app)
        app.go_home()
        await pilot.pause()
        assert dash.crumbs == ("Home",)
        assert shown(nav) == ["First", "Top", "Exit"] and nav.selected == 0
        assert nav.items[-1].kind == "exit"
        assert panel_lines(app) == before
        await type_command(pilot, "t")
        assert dash.crumbs == ("Home", "Top")


async def test_go_home_at_the_root_does_nothing():
    app = CLIApp(menu(leaf("A", "a"), leaf("B", "c")))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        app.panel.log("untouched")
        before = panel_lines(app)
        app.go_home()
        await pilot.pause()
        assert dash.crumbs == ("Home",) and shown(nav) == ["A", "B", "Exit"] and panel_lines(app) == before
        assert app.is_running


# --------------------------------------------------------------------------- with a prompt dialog open

async def open_prompt(pilot) -> None:
    await type_command(pilot, "s")
    await type_command(pilot, "a")
    assert isinstance(pilot.app.screen, PromptScreen)


def prompt_menu(seen: list[str]) -> MenuItem:
    return menu(MenuItem("Sub", shortcut="s", children=[
        MenuItem("Ask", shortcut="a", prompt="Value:", action=seen.append), leaf("Other", "o"),
    ]))


async def test_the_menu_methods_work_while_a_prompt_dialog_is_open():
    seen: list[str] = []
    app = CLIApp(prompt_menu(seen))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await open_prompt(pilot)
        app.refresh_menu()
        assert dash.crumbs == ("Home", "Sub")
        app.go_home()
        assert dash.crumbs == ("Home",)
        app.set_menu(menu(leaf("Fresh", "f"), label="Fresh root"))
        assert dash.crumbs == ("Fresh root",) and shown(nav) == ["Fresh", "Exit"]
        assert isinstance(app.screen, PromptScreen) and app.is_running
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, PromptScreen) and dash.crumbs == ("Fresh root",)
        assert seen == []


async def test_a_spinner_tick_with_a_prompt_dialog_open_does_not_raise_and_still_animates():
    seen: list[str] = []
    app = CLIApp(prompt_menu(seen))
    async with app.run_test(size=SIZE) as pilot:
        dash, _ = view(app)
        app.start_spinner()
        await open_prompt(pilot)
        frame = dash.spinner_frame
        app._tick_spinner()
        app._cycle_spinner_phrase()
        app._cycle_phrase()
        assert dash.spinner_frame == frame + 1
        await pilot.pause(0.3)
        assert app.is_running and dash.spinner_frame > frame + 1
        await pilot.press("escape")
        app.stop_spinner()


async def test_the_menu_methods_can_be_called_from_a_worker_thread_through_call_from_thread():
    app = CLIApp(menu(MenuItem("Sub", shortcut="s", children=[leaf("Inner", "i")])))
    async with app.run_test(size=SIZE) as pilot:
        dash, nav = view(app)
        await type_command(pilot, "s")
        assert dash.crumbs == ("Home", "Sub")
        await asyncio.to_thread(app.call_from_thread, app.go_home)
        assert dash.crumbs == ("Home",)
        await type_command(pilot, "s")
        await asyncio.to_thread(app.call_from_thread, app.set_menu, menu(leaf("Threaded", "t"), label="From thread"))
        assert dash.crumbs == ("From thread",) and shown(nav) == ["Threaded", "Exit"]
        await asyncio.to_thread(app.call_from_thread, app.refresh_menu)
        assert app.is_running


async def test_the_menu_methods_work_from_a_worker_thread_while_a_prompt_is_open():
    seen: list[str] = []
    app = CLIApp(prompt_menu(seen))
    async with app.run_test(size=SIZE) as pilot:
        dash, _ = view(app)
        await open_prompt(pilot)
        await asyncio.to_thread(app.call_from_thread, app.refresh_menu)
        await asyncio.to_thread(app.call_from_thread, app.go_home)
        assert dash.crumbs == ("Home",) and isinstance(app.screen, PromptScreen) and app.is_running


# --------------------------------------------------------------------------- CF-4: one validation hook

def test_the_constructor_set_menu_and_refresh_menu_all_validate_through_the_same_hook():
    seen: list[MenuItem] = []

    class Spy(CLIApp):
        def _validate_menu(self, menu: MenuItem) -> None:
            seen.append(menu)
            super()._validate_menu(menu)

    root = menu(leaf("A", "a"))
    app = Spy(root)
    assert seen == [root]
    other = menu(leaf("B", "c"))
    app.set_menu(other)
    assert seen == [root, other]
    app.refresh_menu()
    assert seen == [root, other, other]
    app.go_home()
    assert seen == [root, other, other], "go_home does no validation"


def test_the_constructor_validates_before_anything_else_exists():
    with pytest.raises(ValueError):
        CLIApp(menu(*CONFLICTED), strict_shortcuts=True)
    with pytest.raises(ShortcutConflictWarning):
        CLIApp(menu(*CONFLICTED))
