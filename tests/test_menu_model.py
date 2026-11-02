"""P1.2a (callable labels and values), CF-2, CF-5, CF-7 and the MenuState additions, at the model level."""
from __future__ import annotations

import ast
import logging
import types
from pathlib import Path

import pytest

from cli_interface.menu import (
    RESERVED_ACTIONS,
    RESERVED_COMMANDS,
    MenuItem,
    MenuState,
    _NavCell,
    find_shortcut_conflicts,
    item_label,
    item_value,
    make_nav_cell,
    normalize_shortcut,
    reserved_action,
)
from helpers import leaf, menu

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- P1.2a: callable labels

def test_a_plain_label_is_returned_as_is():
    assert item_label(MenuItem("Plain")) == "Plain"


def test_a_callable_label_is_called_each_time_it_is_read():
    state = {"n": 0}

    def label() -> str:
        state["n"] += 1
        return f"calls={state['n']}"

    item = MenuItem(label)
    assert (item_label(item), item_label(item)) == ("calls=1", "calls=2")


def test_a_non_string_label_result_goes_through_str():
    assert item_label(MenuItem(lambda: 42)) == "42"


def test_a_raising_label_callable_yields_the_error_marker_and_a_debug_record(caplog):
    with caplog.at_level(logging.DEBUG, logger="cli_interface.menu"):
        assert item_label(MenuItem(lambda: 1 / 0)) == "<error>"
    records = [r for r in caplog.records if r.name == "cli_interface.menu"]
    assert records and records[0].levelno == logging.DEBUG and records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], ZeroDivisionError)


def test_a_label_whose_str_raises_yields_the_error_marker():
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("no text for you")

    assert item_label(MenuItem(lambda: Hostile())) == "<error>"


def test_a_base_exception_in_a_label_callable_propagates():
    def label() -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        item_label(MenuItem(label))


# --------------------------------------------------------------------------- P1.2a: callable values

def test_item_value_passes_plain_values_and_none_through():
    assert item_value(MenuItem("a")) is None
    assert item_value(MenuItem("a", current_value=0)) == 0
    assert item_value(MenuItem("a", current_value="x")) == "x"


def test_item_value_calls_a_callable_with_no_arguments_and_none_means_no_value():
    assert item_value(MenuItem("a", current_value=lambda: 8080)) == 8080
    assert item_value(MenuItem("a", current_value=lambda: None)) is None


def test_a_raising_value_callable_yields_the_error_marker_and_a_debug_record(caplog):
    with caplog.at_level(logging.DEBUG, logger="cli_interface.menu"):
        assert item_value(MenuItem("a", current_value=lambda: 1 / 0)) == "<error>"
    assert any(r.name == "cli_interface.menu" and r.exc_info for r in caplog.records)


def test_a_base_exception_in_a_value_callable_propagates():
    def value() -> str:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        item_value(MenuItem("a", current_value=value))


def test_the_breadcrumb_reads_callable_labels():
    mode = {"on": False}
    inner = MenuItem(lambda: "Mode on" if mode["on"] else "Mode off", children=[MenuItem("Leaf")])
    state = MenuState(MenuItem(lambda: "Root", children=[inner]))
    state.enter()
    assert state.breadcrumb == ["Root", "Mode off"]
    mode["on"] = True
    assert state.breadcrumb == ["Root", "Mode on"]


def test_conflict_messages_show_the_text_of_callable_labels():
    root = MenuItem(
        lambda: "Dynamic root",
        children=[leaf("Quit it", "q"), MenuItem(lambda: "Calc", shortcut="x"), leaf("X2", "x")],
    )
    assert find_shortcut_conflicts(root) == [
        "Dynamic root: shortcut 'q' on 'Quit it' is a reserved command and will never reach this item",
        "Dynamic root: shortcut 'x' is used by 'Calc', 'X2'; only the first is reachable by shortcut",
    ]


def test_conflict_detection_survives_a_raising_label_callable():
    root = menu(leaf("A", "x"), MenuItem(lambda: 1 / 0, shortcut="x", action=lambda: None))
    assert find_shortcut_conflicts(root) == [
        "Home: shortcut 'x' is used by 'A', '<error>'; only the first is reachable by shortcut"
    ]


# --------------------------------------------------------------------------- CF-5: shortcut whitespace

def test_normalize_shortcut_strips_and_lowercases():
    assert normalize_shortcut(" Q ") == "q"
    assert normalize_shortcut("\tHelp\n") == "help"
    assert normalize_shortcut("   ") == "" and normalize_shortcut("") == ""


def test_a_reserved_word_hidden_by_whitespace_is_reported_under_its_normalized_key():
    problems = find_shortcut_conflicts(menu(leaf("Padded quit", " q "), leaf("Trailing", "Help ")))
    assert problems == [
        "Home: shortcut 'q' on 'Padded quit' is a reserved command and will never reach this item",
        "Home: shortcut 'help' on 'Trailing' is a reserved command and will never reach this item",
    ]


def test_shortcuts_differing_only_in_whitespace_are_duplicates():
    problems = find_shortcut_conflicts(menu(leaf("One", "x"), leaf("Two", " x"), leaf("Three", "x ")))
    assert problems == ["Home: shortcut 'x' is used by 'One', 'Two', 'Three'; only the first is reachable by shortcut"]


def test_a_whitespace_only_shortcut_counts_as_no_shortcut():
    assert find_shortcut_conflicts(menu(leaf("One", "  "), leaf("Two", "\t"), leaf("Three", " "))) == []
    state = MenuState(menu(leaf("One", "  "), leaf("Two", "")))
    assert state.select_by_shortcut("") is None and state.select_by_shortcut("   ") is None


def test_select_by_shortcut_ignores_whitespace_on_both_sides():
    state = MenuState(menu(leaf("Padded", "  x  "), leaf("Other", "o")))
    assert state.select_by_shortcut("x").label == "Padded"
    assert state.select_by_shortcut(" X ").label == "Padded"


# --------------------------------------------------------------------------- CF-2: one source for reserved commands

def test_reserved_actions_maps_each_command_to_one_of_four_actions():
    assert dict(RESERVED_ACTIONS) == {
        "q": "quit", "quit": "quit", "exit": "quit",
        "b": "back", "back": "back",
        "clear": "clear",
        "help": "help", "?": "help",
    }
    assert set(RESERVED_ACTIONS.values()) == {"quit", "back", "clear", "help"}


def test_reserved_commands_is_derived_from_reserved_actions():
    assert RESERVED_COMMANDS == frozenset(RESERVED_ACTIONS)
    assert isinstance(RESERVED_COMMANDS, frozenset)


def test_reserved_actions_is_read_only():
    with pytest.raises(TypeError):
        RESERVED_ACTIONS["new"] = "quit"
    assert isinstance(RESERVED_ACTIONS, types.MappingProxyType)


@pytest.mark.parametrize("command, action", sorted(RESERVED_ACTIONS.items()))
def test_reserved_action_matches_case_insensitively_and_ignores_surrounding_whitespace(command, action):
    for typed in (command, command.upper(), f"  {command.title()}\t"):
        assert reserved_action(typed) == action


@pytest.mark.parametrize("typed", ["", "  ", "quitt", "x", "1", "q q", "hel"])
def test_reserved_action_is_none_for_anything_else(typed):
    assert reserved_action(typed) is None


def test_the_app_module_holds_no_literal_collection_of_reserved_words():
    tree = ast.parse((REPO / "cli_interface" / "app.py").read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Tuple | ast.List | ast.Set):
            words = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len([w for w in words if w.lower() in RESERVED_COMMANDS]) >= 2:
                offenders.append(ast.unparse(node))
    assert not offenders, offenders


# --------------------------------------------------------------------------- CF-7: the Exit and Back sentinels

def test_nav_cells_are_nav_cell_instances_with_a_kind():
    exit_cell, back_cell = make_nav_cell("exit"), make_nav_cell("back")
    assert isinstance(exit_cell, _NavCell) and exit_cell.kind == "exit"
    assert isinstance(back_cell, _NavCell) and back_cell.kind == "back"
    assert isinstance(exit_cell, MenuItem) and exit_cell.is_leaf


def test_nav_cell_shortcuts_are_reserved_commands_so_what_they_show_works():
    assert normalize_shortcut(make_nav_cell("exit").shortcut) in RESERVED_COMMANDS
    assert normalize_shortcut(make_nav_cell("back").shortcut) in RESERVED_COMMANDS
    assert reserved_action(make_nav_cell("exit").shortcut) == "quit"
    assert reserved_action(make_nav_cell("back").shortcut) == "back"


def test_an_unknown_nav_cell_kind_is_rejected():
    with pytest.raises(ValueError, match="sideways"):
        make_nav_cell("sideways")


@pytest.mark.parametrize("description", ["__exit__", "__back__", "Exit", "Back"])
def test_a_consumer_item_is_never_mistaken_for_a_nav_cell(description):
    item = MenuItem("Consumer", shortcut="c", description=description, action=lambda: None)
    assert not isinstance(item, _NavCell)


# --------------------------------------------------------------------------- MenuState: set_root, home, prune

def nested() -> tuple[MenuItem, MenuItem, MenuItem, MenuItem]:
    deep = MenuItem("Deep", children=[leaf("D1"), leaf("D2"), leaf("D3")])
    mid = MenuItem("Mid", children=[leaf("M1"), deep])
    top = MenuItem("Top", children=[leaf("T1"), mid, leaf("T3")])
    root = MenuItem("Root", children=[leaf("R1"), top])
    return root, top, mid, deep


def descend(state: MenuState, *indexes: int) -> None:
    for index in indexes:
        state.selected_index = index
        assert state.enter()


def test_set_root_replaces_the_tree_and_resets_the_position():
    root, *_ = nested()
    state = MenuState(root)
    descend(state, 1, 1)
    new_root = menu(leaf("N1"), label="New")
    state.set_root(new_root)
    assert state.root is new_root and state.current_menu is new_root
    assert state.selected_index == 0 and state.breadcrumb == ["New"]


def test_home_pops_to_the_root_and_reports_whether_anything_changed():
    root, *_ = nested()
    state = MenuState(root)
    assert state.home() is False
    descend(state, 1, 1, 1)
    assert state.breadcrumb == ["Root", "Top", "Mid", "Deep"]
    assert state.home() is True
    assert state.current_menu is root and state.breadcrumb == ["Root"]
    assert state.home() is False


def test_prune_keeps_a_valid_stack_untouched():
    root, *_ = nested()
    state = MenuState(root)
    descend(state, 1, 1, 1)
    assert state.prune() is False
    assert state.breadcrumb == ["Root", "Top", "Mid", "Deep"]


def test_prune_drops_a_level_removed_from_its_parent_and_everything_below():
    root, top, mid, deep = nested()
    state = MenuState(root)
    descend(state, 1, 1, 1)
    top.children.remove(mid)
    assert state.prune() is True
    assert state.current_menu is top and state.breadcrumb == ["Root", "Top"]


def test_prune_never_drops_the_root():
    root, top, *_ = nested()
    state = MenuState(root)
    descend(state, 1)
    root.children.clear()
    assert state.prune() is True
    assert state.current_menu is root and state.breadcrumb == ["Root"]
    assert state.prune() is False


def test_prune_drops_a_level_that_became_a_leaf():
    root, top, mid, deep = nested()
    state = MenuState(root)
    descend(state, 1, 1, 1)
    deep.children.clear()
    assert state.prune() is True
    assert state.current_menu is mid


def test_prune_compares_by_identity_not_equality():
    root, top, mid, deep = nested()
    state = MenuState(root)
    descend(state, 1, 1)
    twin = MenuItem("Mid", children=list(mid.children))  # equal fields, a different object
    top.children[1] = twin
    assert twin == mid and twin is not mid
    assert state.prune() is True
    assert state.current_menu is top


def test_prune_clamps_the_selection_of_every_remaining_level():
    root, top, mid, deep = nested()
    state = MenuState(root)
    descend(state, 1)
    state.selected_index = 2
    assert state.current_menu is top and state.selected_index == 2
    del top.children[1:]
    assert state.prune() is False
    assert state.current_menu is top and state.selected_index == 0


def test_prune_clamps_to_the_last_child_not_to_zero():
    root, top, *_ = nested()
    state = MenuState(root)
    descend(state, 1)
    state.selected_index = 2
    top.children.pop()
    state.prune()
    assert state.selected_index == 1
