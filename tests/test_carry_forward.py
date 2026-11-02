"""Phase 0/1 carry-forward items closed in Phase 2: C0-7, C1-1, C1-3 (render), C1-4 (app), C1-5, C1-6, C1-8."""
from __future__ import annotations

import ast
import importlib.util
import logging
import textwrap
import threading
import warnings
from pathlib import Path

import pytest
from rich.cells import cell_len
from textual.widgets import RichLog

from cli_interface import App, CLIApp, Context, LoggingAttachWarning, MenuItem, ShortcutConflictWarning, run
from cli_interface.app import attach_logging
from cli_interface.menu import MenuState, _NavCell, make_nav_cell
from cli_interface.warning_types import warn_external
from cli_interface.widgets import Dashboard, NavBar
from helpers import (
    SIZE, crumbs, leaf, make_gate, menu, panel_text, press_and_wait, tui_handlers, type_command, wait_event,
)

REPO = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- C1-1: warnings point at the caller

def conflicted() -> MenuItem:
    return menu(MenuItem("Quit it", shortcut="q", action=lambda: None))


def shortcut_warnings(caught):
    return [w for w in caught if issubclass(w.category, ShortcutConflictWarning)]


def test_cliapp_construction_warns_at_the_callers_line():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        CLIApp(conflicted())
    (w,) = shortcut_warnings(caught)
    assert w.filename == __file__


def test_run_menu_warns_at_the_callers_file_not_at_app_py(monkeypatch):
    ran = []
    monkeypatch.setattr(CLIApp, "run", lambda self, *a, **k: ran.append(self))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert run(conflicted()) == 0
    (w,) = shortcut_warnings(caught)
    assert w.filename == __file__ and len(ran) == 1


def test_set_and_refresh_menu_warn_at_the_callers_file():
    app = CLIApp(menu(leaf("Fine", "f")))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        app.set_menu(conflicted())
        app.set_menu(menu(MenuItem("Help it", shortcut="help", action=lambda: None)))
    assert [w.filename for w in shortcut_warnings(caught)] == [__file__, __file__]


def write_scratch(tmp_path: Path, name: str, source: str):
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def test_warn_external_points_at_the_first_frame_outside_the_package_however_deep(tmp_path):
    module, path = write_scratch(tmp_path, "scratch_warner", """
        from cli_interface.warning_types import warn_external, ShortcutConflictWarning

        def trigger():
            warn_external("from scratch", ShortcutConflictWarning)

        def middle():
            trigger()

        def outer():
            middle()
    """)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        module.outer()
    (w,) = caught
    assert w.filename == str(path) and w.lineno == 5 and str(w.message) == "from scratch"






def test_warn_external_called_directly_from_a_test_points_at_the_test():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_external("direct", UserWarning)
    assert caught[0].filename == __file__


# --------------------------------------------------------------------------- C0-7: attach_logging after exit

async def test_attach_logging_after_exit_warns_and_returns_an_inert_handle(make_app, unique_logger):
    lg = unique_logger()
    keep = logging.NullHandler()
    lg.addHandler(keep)
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
    level_before, handlers_before = lg.level, list(lg.handlers)
    with pytest.warns(LoggingAttachWarning, match="the app has exited; nothing attached") as record:
        attachment = attach_logging(app, lg, exclusive=True, level=logging.ERROR)
    assert len(record) == 1 and record[0].filename == __file__
    assert attachment.active is False and attachment.logger is lg
    assert lg.handlers == handlers_before == [keep] and lg.level == level_before
    assert tui_handlers(lg) == []
    attachment.detach()
    attachment.detach()
    assert lg.handlers == [keep] and lg.level == level_before
    with attachment:
        pass
    lg.info("after exit")  # nothing attached: must not raise or reach anything


async def test_attach_logging_after_exit_leaves_the_root_logger_alone(make_app, host_root):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        pass
    before = (list(host_root.handlers), host_root.level)
    with pytest.warns(LoggingAttachWarning):
        attach_logging(app, exclusive=True, level="DEBUG")
    assert (list(host_root.handlers), host_root.level) == before


async def test_attaching_before_mount_still_buffers_and_is_detached_at_exit(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    attachment = attach_logging(app, lg)
    assert attachment.active and len(tui_handlers(lg)) == 1
    lg.info("buffered before mount")
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert "buffered before mount" in panel_text(app)
    assert lg.handlers == [] and not attachment.active


async def test_a_job_thread_may_attach_logging_and_it_is_undone_at_exit(unique_logger):
    lg = unique_logger()
    app = App("Attach")
    got = {}

    @app.command("Attach", key="a")
    def attach(ctx: Context):
        got["attachment"] = attach_logging(app, lg)
        lg.info("logged inside the job")

    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "a", "enter")
        assert got["attachment"].active and "logged inside the job" in panel_text(app)
    assert lg.handlers == [] and not got["attachment"].active


# --------------------------------------------------------------------------- C1-3: a raising label while rendering

async def test_a_raising_label_logs_one_debug_record_across_many_renders_of_the_nav_bar(make_app, caplog):
    def bad():
        raise RuntimeError("label boom")

    app = make_app(MenuItem(bad, shortcut="x", action=lambda: None))
    with caplog.at_level(logging.DEBUG, logger="cli_interface.menu"):
        async with app.run_test(size=SIZE) as pilot:
            nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
            await pilot.pause()
            for _ in range(5):
                text = nav.render().plain
                assert "<error>" in text
            await pilot.press("x", "enter")
            assert "Executed: <error>" in panel_text(app)
    records = [r for r in caplog.records if r.name == "cli_interface.menu" and "label raised" in r.getMessage()]
    assert len(records) == 1


# --------------------------------------------------------------------------- C1-4: refresh_menu selection

async def test_refresh_menu_resets_the_selection_when_it_dropped_a_level_and_keeps_it_otherwise():
    deepest = MenuItem("Deepest", shortcut="d", children=[leaf("D1", "e1"), leaf("D2", "e2")])
    middle = MenuItem("Middle", shortcut="m", children=[leaf("M1", "m1"), leaf("M2", "m2"), leaf("M3", "m3"), deepest])
    root = menu(MenuItem("Top", shortcut="t", children=[middle]))
    app = CLIApp(root)
    async with app.run_test(size=SIZE) as pilot:
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        await type_command(pilot, "t")
        await type_command(pilot, "m")
        await pilot.press("down", "down")
        assert nav.selected == 2
        middle.children[0].label = "renamed"
        app.refresh_menu()
        await pilot.pause()
        assert nav.selected == 2, "nothing was dropped: the selection stays"
        await type_command(pilot, "d")
        await pilot.press("down")
        assert nav.selected == 1 and crumbs(app) == ("Home", "Top", "Middle", "Deepest")
        middle.children.remove(deepest)
        app.refresh_menu()
        await pilot.pause()
        assert crumbs(app) == ("Home", "Top", "Middle") and nav.selected == 0


# --------------------------------------------------------------------------- C1-5: the crash handler stays and stays tested

def test_the_fatal_error_override_exists_and_never_shows_locals():
    app_py = REPO / "cli_interface" / "app.py"
    tree = ast.parse(app_py.read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CLIApp")
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "_fatal_error")
    shown = [kw.value for n in ast.walk(method) if isinstance(n, ast.Call) for kw in n.keywords if kw.arg == "show_locals"]
    assert len(shown) == 1 and isinstance(shown[0], ast.Constant) and shown[0].value is False


def crash_tests(module: str) -> list[ast.FunctionDef]:
    tree = ast.parse((REPO / "tests" / f"{module}.py").read_text(encoding="utf-8"))
    return [
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and ("fatal" in node.name or "crash" in node.name)
    ]


@pytest.mark.parametrize("module", ["test_lifecycle", "test_real_run"])
def test_the_crash_regression_tests_are_not_skipped_or_xfailed(module):
    guarded = crash_tests(module)
    assert guarded, f"no crash tests found in {module}"
    for fn in guarded:
        for dec in fn.decorator_list:
            text = ast.unparse(dec)
            assert "skip" not in text and "xfail" not in text, f"{fn.name} is {text}"
        calls = {ast.unparse(n.func) for n in ast.walk(fn) if isinstance(n, ast.Call)}
        assert not calls & {"pytest.skip", "pytest.xfail"}, fn.name


def test_the_three_cf_17_tests_exist_by_name():
    names = {f.name for f in ast.walk(ast.parse((REPO / "tests" / "test_lifecycle.py").read_text(encoding="utf-8")))
             if isinstance(f, ast.FunctionDef)}
    assert {
        "test_the_fatal_traceback_does_not_print_local_variables",
        "test_control_textuals_own_handler_prints_locals",
        "test_a_crash_in_a_real_run_ends_the_app_and_prints_no_locals",
    } <= names


# --------------------------------------------------------------------------- C1-6: Dashboard.location and MenuState.move are gone

def test_dashboard_has_no_location_and_menu_state_has_no_move():
    assert not hasattr(Dashboard, "location") and not hasattr(MenuState, "move")


async def test_the_dashboard_shows_its_crumbs_only(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        dash = app.screen_stack[0].query_one("#dashboard", Dashboard)
        assert dash.crumbs == ("Home",) and isinstance(dash.crumbs, tuple)
        dash.crumbs = ("x|y", "z", "[/b]")
        assert dash.render().plain.startswith(" x|y › z › [/b]\n")
        assert not hasattr(dash, "location")


async def test_a_fresh_dashboard_defaults_to_home():
    app = CLIApp(menu(leaf("A", "a"), label="Root label"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert crumbs(app) == ("Root label",)


# --------------------------------------------------------------------------- C1-8: widths count terminal cells

CELL_LABELS = [
    "Plain", "中文标签", "日本語 Test", "emoji \U0001f600 x", "\U0001f600", "ｗｉｄｅ", "é combining",
    "한국어", "mixed 中 ASCII \U0001f680", "",
]


def unselected_width(nav: NavBar, item: MenuItem) -> int:
    nav.items = [item, item, item]
    return cell_len(nav._render_item(1, item).plain)


async def test_item_width_equals_the_rendered_cell_width(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        checked = 0
        for label in CELL_LABELS:
            for shortcut in ("", "k", "中", "\U0001f600x"):
                for value in (None, "v", "値", "\U0001f600"):
                    for item in (
                        MenuItem(label, shortcut=shortcut, current_value=value, action=lambda: None),
                        MenuItem(label, shortcut=shortcut, current_value=value, children=[leaf("c", "c")]),
                    ):
                        assert nav._compute_item_width(item) == unselected_width(nav, item), (label, shortcut, value)
                        checked += 1
        assert checked == len(CELL_LABELS) * 4 * 4 * 2


async def test_wide_labels_are_measured_in_cells_not_characters(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        ascii_item = MenuItem("abcd", action=lambda: None)
        wide_item = MenuItem("中文标签", action=lambda: None)
        assert nav._compute_item_width(wide_item) == nav._compute_item_width(ascii_item) + 4, "4 wide glyphs = 8 cells"


async def test_nav_cells_have_the_rendered_width_too(make_app):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        for kind in ("exit", "back"):
            cell = make_nav_cell(kind)  # type: ignore[arg-type]
            assert isinstance(cell, _NavCell)
            assert nav._compute_item_width(cell) == unselected_width(nav, cell)


async def test_a_wide_glyph_label_wraps_to_a_second_row_sooner_than_its_character_count_suggests(make_app):
    wide = "宽" * 20
    app = make_app(*[MenuItem(wide + str(n), shortcut=f"w{n}", action=lambda: None) for n in range(2)])
    async with app.run_test(size=(60, 40)) as pilot:
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        rows = nav._layout_rows(60)
        assert len(rows) >= 2 and all(
            sum(nav._compute_item_width(nav.items[i]) for i in row) <= 60 or len(row) == 1 for row in rows
        )


async def test_the_rendered_nav_bar_never_exceeds_its_width_with_wide_glyphs(make_app):
    items = [MenuItem(f"{'中' * 5}{n}", shortcut=f"s{n}", current_value="値", action=lambda: None) for n in range(6)]
    app = make_app(*items)
    async with app.run_test(size=(50, 30)) as pilot:
        await pilot.pause()
        nav = app.screen_stack[0].query_one("#nav-bar", NavBar)
        text = nav.render().plain
        for line in text.splitlines():
            if "page" in line:
                continue
            assert cell_len(line) <= 50, line
        assert isinstance(app.screen_stack[0].query_one("#display-panel", RichLog), RichLog)


# --------------------------------------------------------------------------- a gate sanity check for the helpers

async def test_wait_event_times_out_with_a_clear_message():
    never = threading.Event()
    with pytest.raises(AssertionError, match="timed out after 0.05s waiting for the thing"):
        await wait_event(never, timeout=0.05, what="the thing")
    assert make_gate().is_set() is False
