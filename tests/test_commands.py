"""P2.2 / P2.4 / C1-7: App and @app.command: tree building, errors, shortcut conflicts, late registration."""
from __future__ import annotations

import functools
import inspect
import threading
import warnings

import pytest

from cli_interface import App, CLIApp, Context, MenuItem, ShortcutConflictWarning
from cli_interface.menu import _CommandItem
from helpers import SIZE, crumbs, panel_text, press_and_wait, wait_event


def noop() -> None: ...


def labels(item: MenuItem) -> list[str]:
    return [c.label for c in item.children]  # type: ignore[misc]


def tree(item: MenuItem) -> list:
    return [(c.label, c.shortcut, type(c).__name__, tree(c)) for c in item.children]


def root(app: App) -> MenuItem:
    return app._state.root


def conflicts(caught):
    return [w for w in caught if issubclass(w.category, ShortcutConflictWarning)]


# --------------------------------------------------------------------------- construction

def test_app_is_a_cliapp_whose_root_and_title_are_its_name():
    app = App("My tool")
    assert isinstance(app, CLIApp) and root(app).label == "My tool" and app.title == "My tool"
    assert root(app).children == []


def test_app_default_name_and_non_string_names():
    assert App().title == "cli-interface"
    with pytest.raises(TypeError, match="name must be a str"):
        App(MenuItem("x"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        App(None)  # type: ignore[arg-type]


def test_app_forwards_the_cliapp_options():
    with pytest.raises(ValueError, match="max_lines"):
        App("x", max_lines=0)
    for bad in (-1, float("nan"), float("inf"), True, "2", None):
        with pytest.raises(ValueError, match="quit_grace"):
            App("x", quit_grace=bad)  # type: ignore[arg-type]
    assert App("x", quit_grace=0).jobs._grace == 0
    assert App("x", strict_shortcuts=True)._strict_shortcuts is True


def test_capture_loggers_is_not_an_app_option_in_phase_2():
    with pytest.raises(TypeError):
        App("x", capture_loggers=True)  # type: ignore[call-arg]


def test_the_classic_cliapp_still_works_beside_app():
    classic = CLIApp(MenuItem("Home", children=[MenuItem("A", shortcut="a", action=noop)]))
    assert not isinstance(classic, App) and labels(classic._state.root) == ["A"]


# --------------------------------------------------------------------------- building the tree

def test_command_creates_the_submenu_and_a_leaf_with_the_key_as_shortcut():
    app = App("x")

    @app.command("Run/Extract", key="e")
    def extract(ctx: Context) -> None: ...

    (run,) = root(app).children
    assert run.label == "Run" and not run.is_leaf and run.action is None
    (leaf,) = run.children
    assert isinstance(leaf, _CommandItem) and leaf.label == "Extract" and leaf.shortcut == "e"
    assert leaf.action is extract and leaf.command_path == ("Run", "Extract") and leaf.cancellable is False


def test_the_decorator_returns_the_function_unchanged():
    app = App("x")

    def fn() -> int:
        return 1

    assert app.command("A")(fn) is fn
    part = functools.partial(fn)
    assert app.command("B")(part) is part
    assert fn() == 1 and fn.__name__ == "fn"


def test_commands_in_one_group_share_the_group_and_nested_paths_create_every_level():
    app = App("x")
    app.add_command("Run/A", noop, key="a")
    app.add_command("Run/B", noop, key="b2")
    app.add_command("Deep/er/est/Leaf", noop, key="l")
    app.add_command("Top", noop, key="t")
    assert labels(root(app)) == ["Run", "Deep", "Top"]
    assert labels(root(app).children[0]) == ["A", "B"]
    deepest = root(app).children[1].children[0].children[0]
    assert deepest.label == "est" and deepest.children[0].command_path == ("Deep", "er", "est", "Leaf")


def test_cancellable_and_description_are_stored_on_the_leaf():
    app = App("x")

    def documented():
        """First line wins.

        More text.
        """

    app.add_command("A", documented, cancellable=True)
    app.add_command("B", documented, description="explicit")
    app.add_command("C", lambda: None)
    app.add_command("D", functools.partial(documented))
    a, b, c, d = root(app).children
    assert a.cancellable is True and b.cancellable is False
    assert (a.description, b.description, c.description) == ("First line wins.", "explicit", "")
    assert d.description == "", "a partial does not pick up the docstring of its class"


def test_a_callable_label_in_the_tree_is_never_called_while_registering():
    calls = []
    app = App("x")
    app.set_menu(MenuItem("Root", children=[MenuItem(lambda: calls.append(1) or "dynamic", children=[])]))
    app.add_command("Other/Cmd", noop)
    assert calls == []


def test_group_creates_submenus_and_later_commands_join_them():
    app = App("x")
    app.group("Run", key="r", description="Things to run")
    app.add_command("Run/X", noop, key="x")
    (run,) = root(app).children
    assert (run.label, run.shortcut, run.description) == ("Run", "r", "Things to run")
    assert labels(run) == ["X"]
    app.group("Deep/Nested", key="d")
    assert root(app).children[1].children[0].shortcut == "d"


def test_group_on_an_existing_submenu_updates_only_what_is_given():
    app = App("x")
    app.add_command("Run/X", noop)
    app.group("Run", key="r")
    app.group("Run", description="desc")
    app.group("Run")
    run = root(app).children[0]
    assert (run.shortcut, run.description) == ("r", "desc")
    app.group("Run", key="z")
    assert run.shortcut == "z"


def test_a_group_can_be_created_empty_and_is_not_mistaken_for_a_command():
    app = App("x")
    app.group("Empty")
    app.group("Empty")
    with pytest.raises(ValueError):
        app.add_command("Empty", noop)


# --------------------------------------------------------------------------- errors

def test_a_duplicate_path_raises_value_error_and_changes_nothing():
    app = App("x")
    app.add_command("Run/X", noop, key="x")
    before = tree(root(app))
    with pytest.raises(ValueError, match="already registered"):
        app.add_command("Run/X", noop, key="y")
    assert tree(root(app)) == before


def test_a_path_through_a_command_raises_value_error():
    app = App("x")
    app.add_command("Run", noop)
    with pytest.raises(ValueError, match="is a command"):
        app.add_command("Run/Inner", noop)
    with pytest.raises(ValueError, match="is a command"):
        app.group("Run/Sub")
    with pytest.raises(ValueError, match="it is a command"):
        app.group("Run")
    assert labels(root(app)) == ["Run"]


def test_a_command_cannot_replace_an_existing_group():
    app = App("x")
    app.add_command("Run/X", noop)
    with pytest.raises(ValueError):
        app.add_command("Run", noop)


@pytest.mark.parametrize("path", ["", "/", "A/", "/A", "A//B", " ", "A/ /B", "A/\t"])
def test_empty_paths_and_empty_segments_are_rejected(path):
    app = App("x")
    with pytest.raises(ValueError, match="invalid path"):
        app.add_command(path, noop)
    with pytest.raises(ValueError):
        app.command(path)
    with pytest.raises(ValueError):
        app.group(path)
    assert root(app).children == []


def test_a_bare_decorator_without_parentheses_is_a_clear_type_error_not_a_silent_replacement():
    app = App("x")
    with pytest.raises(TypeError, match="path must be a str"):
        app.command(noop)  # type: ignore[arg-type]
    assert root(app).children == []


def test_argument_types_are_checked():
    app = App("x")
    with pytest.raises(TypeError, match="callable"):
        app.add_command("A", "not callable")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="key must be a str"):
        app.add_command("A", noop, key=5)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="key must be a str"):
        app.group("A", key=5)  # type: ignore[arg-type]
    assert root(app).children == []


# --------------------------------------------------------------------------- shortcut conflicts

def test_strict_mode_raises_at_the_offending_registration_and_leaves_no_trace():
    app = App("x", strict_shortcuts=True)
    app.add_command("Run/A", noop, key="a")
    before = tree(root(app))
    with pytest.raises(ValueError, match="reserved command"):
        app.add_command("Fresh/Group/Quit it", noop, key="q")
    with pytest.raises(ValueError, match="used by"):
        app.add_command("Run/B", noop, key="A")
    assert tree(root(app)) == before, "neither the leaf nor the groups it needed were left behind"


def test_stop_is_a_reserved_shortcut():
    strict = App("x", strict_shortcuts=True)
    with pytest.raises(ValueError, match="'stop'.*reserved command"):
        strict.add_command("Halt", noop, key="stop")
    with pytest.warns(ShortcutConflictWarning, match="reserved command"):
        App("y").add_command("Halt", noop, key="STOP")


def test_non_strict_mode_warns_with_the_callers_file_and_the_decorator_line():
    app = App("x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        line = inspect.currentframe().f_lineno + 1  # type: ignore[union-attr]
        @app.command("Quit it", key="q")
        def quit_it() -> None: ...

        add_line = inspect.currentframe().f_lineno + 1  # type: ignore[union-attr]
        app.add_command("Help it", noop, key="help")
    found = conflicts(caught)
    assert len(found) == 2
    assert found[0].filename == __file__ and found[0].lineno == line
    assert found[1].filename == __file__ and found[1].lineno == add_line
    assert "reserved command" in str(found[0].message)
    assert labels(root(app)) == ["Quit it", "Help it"], "non-strict mode keeps the command"


def test_a_conflict_already_reported_is_not_reported_again_on_the_next_registration():
    app = App("x")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.add_command("Quit it", noop, key="q")
        app.add_command("Fine", noop, key="f")
    assert len(conflicts(caught)) == 1


def test_a_warning_turned_into_an_error_rolls_the_registration_back():
    app = App("x")
    app.add_command("Keep", noop, key="k")
    before = tree(root(app))
    queued = list(app._menu_warnings)
    with warnings.catch_warnings():
        warnings.simplefilter("error", ShortcutConflictWarning)
        with pytest.raises(ShortcutConflictWarning):
            app.add_command("New/Quit it", noop, key="q")
    assert tree(root(app)) == before and app._menu_warnings == queued


def test_a_group_key_conflict_is_checked_and_rolled_back_too():
    strict = App("x", strict_shortcuts=True)
    strict.add_command("Run/X", noop)
    before = tree(root(strict))
    with pytest.raises(ValueError, match="reserved command"):
        strict.group("Run", key="q")
    with pytest.raises(ValueError, match="reserved command"):
        strict.group("Fresh", key="help")
    assert tree(root(strict)) == before, "the changed key and the new group were taken back"


# --------------------------------------------------------------------------- after mount

async def test_registering_after_mount_refreshes_the_menu_and_the_new_command_runs():
    app = App("x")
    app.add_command("First", noop, key="f")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.add_command("Late", lambda: "late result", key="l")
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar")
        assert [i.label for i in nav.items][:2] == ["First", "Late"]
        await press_and_wait(pilot, "l", "enter")
        assert "Executed: Late → late result" in panel_text(app)


async def test_registering_from_another_thread_after_mount_works():
    app = App("x")
    done = threading.Event()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()

        def register():
            app.add_command("Threaded", noop, key="t")
            done.set()

        threading.Thread(target=register, daemon=True).start()
        await wait_event(done)
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar")
        assert "Threaded" in [i.label for i in nav.items]


async def test_a_late_non_strict_conflict_warns_once_and_writes_a_panel_warning():
    app = App("x")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            app.add_command("Quit it", noop, key="q")
        assert len(conflicts(caught)) == 1 and conflicts(caught)[0].filename == __file__
        await pilot.pause()
        assert panel_text(app).count("reserved command") == 1


async def test_a_late_strict_conflict_raises_and_leaves_the_menu_alone():
    app = App("x", strict_shortcuts=True)
    app.add_command("Fine", noop, key="f")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        with pytest.raises(ValueError, match="reserved command"):
            app.add_command("Quit it", noop, key="q")
        await pilot.pause()
        assert labels(root(app)) == ["Fine"] and crumbs(app) == ("x",)


async def test_registering_while_in_a_submenu_keeps_the_current_level():
    app = App("x")
    app.group("Sub", key="s")
    app.add_command("Sub/One", noop, key="o")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await pilot.pause()
        assert crumbs(app) == ("x", "Sub")
        app.add_command("Sub/Two", noop, key="t")
        await pilot.pause()
        assert crumbs(app) == ("x", "Sub")
        nav = app.screen_stack[0].query_one("#nav-bar")
        assert [i.label for i in nav.items][:2] == ["One", "Two"]
