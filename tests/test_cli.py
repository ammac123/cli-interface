"""P1.4c: the ``cli-interface module:attr`` console script. The TUI is never started: ``CLIApp.run`` is replaced."""
from __future__ import annotations

import asyncio
import importlib.metadata
import itertools
import os
import shutil
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from textual.widgets import RichLog

from cli_interface import CLIApp, ShortcutConflictWarning, __version__, cli
from cli_interface.menu import item_label
from cli_interface.widgets import Dashboard, NavBar
from helpers import SIZE

REPO = Path(__file__).resolve().parent.parent
PREFIX = "clitgt"
_COUNTER = itertools.count()


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(autouse=True)
def headless_run(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Never start the real TUI: CLIApp.run becomes a headless run_test that records what the app showed."""
    seen: dict[str, Any] = {"runs": 0, "views": [], "apps": [], "return_code": 0}

    def fake_run(self: CLIApp, *args: Any, **kwargs: Any) -> None:
        async def probe() -> None:
            async with self.run_test(size=SIZE) as pilot:
                await pilot.pause()
                nav = self.query_one("#nav-bar", NavBar)
                seen["views"].append({
                    "crumbs": self.query_one("#dashboard", Dashboard).crumbs,
                    "labels": [item_label(i) for i in nav.items],
                    "max_lines": self.query_one("#display-panel", RichLog).max_lines,
                    "panel": "\n".join(s.text for s in self.query_one("#display-panel", RichLog).lines),
                })
                self.exit(return_code=seen["return_code"])

        seen["runs"] += 1
        seen["apps"].append(self)
        asyncio.run(probe())

    monkeypatch.setattr(CLIApp, "run", fake_run)
    return seen


@pytest.fixture
def workdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A scratch cwd that is on neither sys.path nor '' until main() puts it there; modules it imports are dropped."""
    cwd = os.getcwd()
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p not in ("", cwd)])
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    for name in [n for n in sys.modules if n.startswith(PREFIX)]:
        del sys.modules[name]


def new_name(base: str = "menus") -> str:
    return f"{PREFIX}{next(_COUNTER)}_{base}"


def write_module(workdir: Path, source: str, base: str = "menus") -> str:
    name = new_name(base)
    (workdir / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return name


def write_package(workdir: Path, files: dict[str, str], base: str = "pkg") -> str:
    name = new_name(base)
    for relative, source in {"__init__.py": "", **files}.items():
        target = workdir / name / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return name


def run_main(*argv: str) -> int:
    return cli.main(list(argv))


def exit_code_of(*argv: str) -> int:
    with pytest.raises(SystemExit) as exit_info:
        cli.main(list(argv))
    return exit_info.value.code


# --------------------------------------------------------------------------- resolving the target

def test_main_takes_an_optional_argv_and_returns_an_int():
    import inspect
    import typing

    parameters = inspect.signature(cli.main).parameters
    assert list(parameters) == ["argv"] and parameters["argv"].default is None
    assert typing.get_type_hints(cli.main)["return"] is int


def test_a_menu_item_target_is_shown_as_the_root(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import MenuItem
        ROOT = MenuItem("Root", children=[MenuItem("First", shortcut="f"), MenuItem("Second", shortcut="s")])
    """)
    assert run_main(f"{name}:ROOT") == 0
    assert headless_run["runs"] == 1
    assert headless_run["views"][0]["crumbs"] == ("Root",)
    assert headless_run["views"][0]["labels"] == ["First", "Second", "Exit"]


def test_a_zero_argument_callable_is_called_without_arguments(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import MenuItem
        def build_menu():
            return MenuItem("Zero", children=[MenuItem("Leaf", shortcut="l")])
    """)
    assert run_main(f"{name}:build_menu") == 0
    assert headless_run["views"][0]["crumbs"] == ("Zero",)


def test_a_callable_with_a_required_parameter_receives_the_running_app(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import MenuItem
        RECEIVED = []
        def build_menu(app):
            RECEIVED.append(app)
            return MenuItem("With app", children=[MenuItem("Leaf", shortcut="l")])
    """)
    assert run_main(f"{name}:build_menu") == 0
    (received,) = sys.modules[name].RECEIVED
    assert isinstance(received, CLIApp) and received is headless_run["apps"][0]
    assert headless_run["views"][0]["crumbs"] == ("With app",)


@pytest.mark.parametrize(
    "signature, captured, expected",
    [("app=None", "app", None), ("*args", "args", ()), ("**kwargs", "kwargs", {}), ("app=None, *rest", "(app, rest)", (None, ()))],
)
def test_a_callable_without_a_required_positional_parameter_is_called_without_arguments(
    workdir, headless_run, signature, captured, expected
):
    name = write_module(workdir, f"""
        from cli_interface import MenuItem
        CAPTURED = []
        def build_menu({signature}):
            CAPTURED.append({captured})
            return MenuItem("No app")
    """)
    assert run_main(f"{name}:build_menu") == 0
    assert headless_run["views"][0]["crumbs"] == ("No app",)
    assert sys.modules[name].CAPTURED == [expected]


def test_a_callable_whose_only_parameter_is_a_required_keyword_cannot_be_called_and_the_error_shows(workdir, headless_run):
    name = write_module(workdir, "from cli_interface import MenuItem\ndef build_menu(*, app):\n    return MenuItem('x')\n")
    with pytest.raises(TypeError, match="app"):
        run_main(f"{name}:build_menu")
    assert headless_run["runs"] == 0


def test_a_dotted_attribute_path_is_followed(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import MenuItem
        class Holder:
            MENU = MenuItem("Attribute")
            @staticmethod
            def make():
                return MenuItem("Static method")
            class Inner:
                MENU = MenuItem("Nested class")
    """)
    for attr, expected in (("Holder.MENU", "Attribute"), ("Holder.make", "Static method"), ("Holder.Inner.MENU", "Nested class")):
        assert run_main(f"{name}:{attr}") == 0
        assert headless_run["views"][-1]["crumbs"] == (expected,)


def test_a_module_inside_a_package_is_resolved(workdir, headless_run):
    package = write_package(workdir, {"menus.py": """
        from cli_interface import MenuItem
        def build_menu():
            return MenuItem("In package")
    """})
    assert run_main(f"{package}.menus:build_menu") == 0
    assert headless_run["views"][0]["crumbs"] == ("In package",)


def test_the_current_directory_is_searched_first_and_is_put_on_sys_path_once(workdir):
    name = write_module(workdir, """
        from cli_interface import MenuItem
        ROOT = MenuItem("Here")
    """)
    assert str(workdir) not in sys.path and "" not in sys.path
    assert run_main(f"{name}:ROOT") == 0
    assert sys.path[0] == str(workdir)
    assert run_main(f"{name}:ROOT") == 0
    assert sys.path.count(str(workdir)) == 1


def test_the_repository_demo_resolves_from_the_repository_root(monkeypatch, headless_run):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert run_main("examples.example_menu:build_menu") == 0
    view = headless_run["views"][0]
    assert view["crumbs"] == ("Home",)
    assert view["labels"][0] == "View Output" and "Settings" in view["labels"] and view["labels"][-1] == "Exit"


def test_argv_defaults_to_sys_argv(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli-interface", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        cli.main()
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"cli-interface {__version__}"


# --------------------------------------------------------------------------- the options reach the app

@pytest.fixture
def init_kwargs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class Recording(CLIApp):
        def __init__(self, menu: Any, **kwargs: Any) -> None:
            calls.append(kwargs)
            super().__init__(menu, **kwargs)

    monkeypatch.setattr(cli, "CLIApp", Recording)
    return calls


def clean_menu(workdir: Path) -> str:
    name = write_module(workdir, """
        from cli_interface import MenuItem
        ROOT = MenuItem("Clean", children=[MenuItem("Leaf", shortcut="l")])
    """)
    return f"{name}:ROOT"


def test_no_options_leave_the_apps_defaults_alone(workdir, init_kwargs, headless_run):
    assert run_main(clean_menu(workdir)) == 0
    assert init_kwargs == [{"strict_shortcuts": False}]
    assert headless_run["views"][0]["max_lines"] == 5000


def test_max_lines_reaches_the_app(workdir, init_kwargs, headless_run):
    assert run_main("--max-lines", "123", clean_menu(workdir)) == 0
    assert init_kwargs == [{"strict_shortcuts": False, "max_lines": 123}]
    assert headless_run["views"][0]["max_lines"] == 123


def test_strict_shortcuts_reaches_the_app(workdir, init_kwargs):
    assert run_main("--strict-shortcuts", clean_menu(workdir)) == 0
    assert init_kwargs == [{"strict_shortcuts": True}]


def test_options_may_follow_the_target(workdir, init_kwargs):
    assert run_main(clean_menu(workdir), "--strict-shortcuts", "--max-lines", "9") == 0
    assert init_kwargs == [{"strict_shortcuts": True, "max_lines": 9}]


@pytest.mark.parametrize("bad", ["0", "-3", "abc", "1.5", ""])
def test_a_bad_max_lines_is_a_usage_error(workdir, headless_run, capsys, bad):
    assert exit_code_of("--max-lines", bad, clean_menu(workdir)) == 2
    assert "positive integer" in capsys.readouterr().err
    assert headless_run["runs"] == 0


def test_the_apps_return_code_becomes_the_exit_code(workdir, headless_run):
    headless_run["return_code"] = 7
    assert run_main(clean_menu(workdir)) == 7


CONFLICTED = """
    from cli_interface import MenuItem
    ROOT = MenuItem("Conflicted", children=[
        MenuItem("Quit it", shortcut="q", action=lambda: None),
        MenuItem("X1", shortcut="x", action=lambda: None),
        MenuItem("X2", shortcut="x", action=lambda: None),
    ])
"""


def test_strict_shortcuts_turns_a_conflict_into_a_usage_error_listing_every_problem(workdir, headless_run, capsys):
    name = write_module(workdir, CONFLICTED)
    assert exit_code_of("--strict-shortcuts", f"{name}:ROOT") == 2
    err = capsys.readouterr().err
    assert "shortcut conflicts" in err and "--strict-shortcuts" in err
    assert "shortcut 'q' on 'Quit it' is a reserved command" in err
    assert "shortcut 'x' is used by 'X1', 'X2'" in err
    assert headless_run["runs"] == 0


def test_without_strict_shortcuts_a_conflict_warns_and_the_app_still_runs(workdir, headless_run):
    name = write_module(workdir, CONFLICTED)
    with pytest.warns(ShortcutConflictWarning) as record:
        assert run_main(f"{name}:ROOT") == 0
    assert len(record) == 2
    panel = " ".join(headless_run["views"][0]["panel"].split())
    assert "reserved command" in panel and "only the first is reachable" in panel


# --------------------------------------------------------------------------- usage errors exit 2

def test_a_missing_target_is_a_usage_error(headless_run, capsys):
    assert exit_code_of() == 2
    assert "the following arguments are required: target" in capsys.readouterr().err
    assert headless_run["runs"] == 0


@pytest.mark.parametrize("target", ["nocolon", ":attr", "module:", "a b:c", "mod:1x", "mod:a..b", "mod:a-b", ":"])
def test_a_target_that_is_not_module_colon_attr_is_a_usage_error(headless_run, capsys, target):
    assert exit_code_of(target) == 2
    assert "target must look like module:attr" in capsys.readouterr().err
    assert headless_run["runs"] == 0


def test_a_module_that_does_not_exist_is_a_usage_error(workdir, headless_run, capsys):
    assert exit_code_of(f"{new_name('nope')}:x") == 2
    assert "cannot import module" in capsys.readouterr().err
    assert exit_code_of("no.such.mod:x") == 2
    assert headless_run["runs"] == 0


def test_a_missing_submodule_of_an_existing_package_is_a_usage_error(workdir, headless_run, capsys):
    package = write_package(workdir, {})
    assert exit_code_of(f"{package}.nosuch:x") == 2
    assert "cannot import module" in capsys.readouterr().err
    assert headless_run["runs"] == 0


def test_a_missing_attribute_is_a_usage_error(workdir, headless_run, capsys):
    name = write_module(workdir, "from cli_interface import MenuItem\nROOT = MenuItem('r')\n")
    assert exit_code_of(f"{name}:nosuch") == 2
    assert "has no attribute 'nosuch'" in capsys.readouterr().err
    assert exit_code_of(f"{name}:ROOT.nosuch") == 2
    assert headless_run["runs"] == 0


@pytest.mark.parametrize("value", ["5", "'text'", "None", "[1, 2]"])
def test_a_target_that_is_neither_a_menu_nor_a_callable_is_a_usage_error(workdir, headless_run, capsys, value):
    name = write_module(workdir, f"VALUE = {value}\n")
    assert exit_code_of(f"{name}:VALUE") == 2
    assert "neither a MenuItem nor a callable" in capsys.readouterr().err
    assert headless_run["runs"] == 0


@pytest.mark.parametrize("expression, type_name", [("'text'", "str"), ("None", "NoneType"), ("[1]", "list")])
def test_a_callable_returning_the_wrong_type_is_a_usage_error(workdir, headless_run, capsys, expression, type_name):
    name = write_module(workdir, f"def build_menu():\n    return {expression}\n")
    assert exit_code_of(f"{name}:build_menu") == 2
    assert f"returned {type_name}, not a MenuItem" in capsys.readouterr().err
    assert headless_run["runs"] == 0


# --------------------------------------------------------------------------- failures inside the user's code propagate

def test_a_missing_dependency_inside_the_target_module_is_not_reported_as_a_missing_target(workdir, headless_run):
    name = write_module(workdir, "import definitely_not_installed_xyz_9\nROOT = 1\n")
    with pytest.raises(ModuleNotFoundError) as error:
        run_main(f"{name}:ROOT")
    assert error.value.name == "definitely_not_installed_xyz_9"
    assert headless_run["runs"] == 0


def test_a_missing_dependency_inside_a_submodule_propagates_with_its_traceback(workdir, headless_run):
    package = write_package(workdir, {"inner.py": "import definitely_not_installed_xyz_9\n"})
    with pytest.raises(ModuleNotFoundError) as error:
        run_main(f"{package}.inner:x")
    assert error.value.name == "definitely_not_installed_xyz_9"


def test_a_failed_name_import_inside_the_target_module_propagates(workdir, headless_run):
    helper = write_module(workdir, "OTHER = 1\n", "helper")
    name = write_module(workdir, f"from {helper} import not_there\n")
    with pytest.raises(ImportError) as error:
        run_main(f"{name}:x")
    assert type(error.value) is ImportError and "not_there" in str(error.value)


def test_a_syntax_error_in_the_target_module_propagates(workdir, headless_run):
    name = write_module(workdir, "def broken(:\n")
    with pytest.raises(SyntaxError):
        run_main(f"{name}:broken")


def test_an_exception_raised_by_build_menu_propagates(workdir, headless_run):
    name = write_module(workdir, "def build_menu():\n    raise RuntimeError('boom in build_menu')\n")
    with pytest.raises(RuntimeError, match="boom in build_menu"):
        run_main(f"{name}:build_menu")
    assert headless_run["runs"] == 0


# --------------------------------------------------------------------------- the console script as a process

def run_process(args: list[str], cwd: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
        env={**os.environ, **env},
    )


def module_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "cli_interface.cli", *args]


def shim() -> str | None:
    return shutil.which("cli-interface", path=str(Path(sys.executable).parent))


@pytest.fixture(params=["module", "console-script"])
def command(request: pytest.FixtureRequest) -> Callable[..., list[str]]:
    if request.param == "module":
        return module_command
    if shim() is None:
        pytest.skip("the cli-interface console script is not installed next to this interpreter")
    return lambda *args: [shim() or "", *args]


def test_version_prints_ascii_and_exits_zero(command, tmp_path):
    done = run_process(command("--version"), tmp_path, PYTHONIOENCODING="ascii")
    assert done.returncode == 0 and done.stdout.strip() == f"cli-interface {__version__}" and done.stderr == ""


def test_help_is_ascii_only_and_describes_the_interface(command, tmp_path):
    done = run_process(command("--help"), tmp_path, PYTHONIOENCODING="ascii", COLUMNS="100", NO_COLOR="1", PYTHON_COLORS="0")
    assert done.returncode == 0 and done.stderr == ""
    assert done.stdout.isascii()
    text = " ".join(done.stdout.split())  # argparse wraps to the terminal width
    for needle in ("module:attr", "--strict-shortcuts", "--max-lines N", "(default: 5000)", "--version", "usage: cli-interface"):
        assert needle in text, needle
    assert "example: cli-interface pkg.mod:build_menu" in text


def test_a_bare_invocation_exits_two_with_a_usage_message(command, tmp_path):
    done = run_process(command(), tmp_path)
    assert done.returncode == 2 and "the following arguments are required: target" in done.stderr
    assert "Traceback" not in done.stderr


def test_a_missing_module_exits_two_without_a_traceback(command, tmp_path):
    done = run_process(command(f"{new_name('nope')}:x"), tmp_path)
    assert done.returncode == 2 and "cannot import module" in done.stderr and "Traceback" not in done.stderr


def test_a_module_in_the_current_directory_is_found_and_a_wrong_return_type_exits_two(command, tmp_path):
    name = write_module(tmp_path, "def build_menu():\n    return 5\n")
    done = run_process(command(f"{name}:build_menu"), tmp_path)
    assert done.returncode == 2 and "returned int, not a MenuItem" in done.stderr


def test_a_failure_inside_the_target_exits_one_with_a_traceback(command, tmp_path):
    name = write_module(tmp_path, "import definitely_not_installed_xyz_9\n")
    done = run_process(command(f"{name}:x"), tmp_path)
    assert done.returncode == 1 and "Traceback" in done.stderr
    assert "ModuleNotFoundError: No module named 'definitely_not_installed_xyz_9'" in done.stderr


def test_the_console_script_is_registered_in_the_package_metadata():
    (entry,) = [e for e in importlib.metadata.entry_points(group="console_scripts") if e.name == "cli-interface"]
    assert entry.value == "cli_interface.cli:main"
    assert entry.load() is cli.main


# --------------------------------------------------------------------------- Phase 2 / C1-7: an App (or CLIApp) as the target

APP_MODULE = """
    from cli_interface import App, Context

    app = App("Mod app")

    @app.command("Run/Go", key="g")
    def go(ctx: Context):
        return "went"
"""


@pytest.fixture
def demo_modules():
    """examples.app_demo builds a module-level singleton, which Textual cannot run twice: import it afresh."""
    for name in [n for n in sys.modules if n == "examples.app_demo"]:
        del sys.modules[name]
    yield
    for name in [n for n in sys.modules if n == "examples.app_demo"]:
        del sys.modules[name]


def test_an_app_instance_is_run_as_it_is_not_wrapped_or_copied(workdir, headless_run):
    name = write_module(workdir, APP_MODULE)
    assert run_main(f"{name}:app") == 0
    from cli_interface import App

    (app,) = headless_run["apps"]
    assert isinstance(app, App) and app is sys.modules[name].app
    view = headless_run["views"][0]
    assert view["crumbs"] == ("Mod app",) and view["labels"] == ["Run", "Exit"]


def test_a_plain_cliapp_instance_is_a_valid_target_too(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import CLIApp, MenuItem
        APP = CLIApp(MenuItem("Classic", children=[MenuItem("A", shortcut="a")]))
    """)
    assert run_main(f"{name}:APP") == 0
    assert headless_run["apps"][0] is sys.modules[name].APP
    assert headless_run["views"][0]["crumbs"] == ("Classic",)


def test_a_callable_returning_an_app_is_called_and_its_app_is_run(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import App

        def build():
            return App("Built")
    """)
    assert run_main(f"{name}:build") == 0
    assert headless_run["views"][0]["crumbs"] == ("Built",)
    assert type(headless_run["apps"][0]).__name__ == "App"


def test_the_unchanged_build_menu_app_rule_still_hands_the_callable_the_app_that_will_show_the_menu(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import MenuItem

        def build_menu(app):
            return MenuItem("Uses app", children=[MenuItem("Log", shortcut="l", action=lambda: app.panel.log("hi"))])
    """)
    assert run_main(f"{name}:build_menu") == 0
    assert type(headless_run["apps"][0]) is CLIApp
    assert headless_run["views"][0]["crumbs"] == ("Uses app",)


def test_a_callable_with_a_required_parameter_may_also_return_an_app(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import App

        def build(placeholder):
            return App("From param")
    """)
    assert run_main(f"{name}:build") == 0
    assert headless_run["views"][0]["crumbs"] == ("From param",)


def test_max_lines_is_applied_to_an_app_target(workdir, headless_run):
    name = write_module(workdir, APP_MODULE)
    assert run_main("--max-lines", "77", f"{name}:app") == 0
    assert headless_run["views"][0]["max_lines"] == 77


def test_without_options_an_app_target_keeps_its_own_settings(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import App
        app = App("Own", max_lines=33)
    """)
    assert run_main(f"{name}:app") == 0
    assert headless_run["views"][0]["max_lines"] == 33


def test_strict_shortcuts_on_an_app_with_a_conflict_is_a_usage_error_listing_the_problems(workdir, headless_run, capsys):
    name = write_module(workdir, """
        import warnings
        from cli_interface import App
        app = App("Conflicted")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            app.add_command("Quit it", lambda: None, key="q")
            app.add_command("X1", lambda: None, key="x")
            app.add_command("X2", lambda: None, key="x")
    """)
    assert exit_code_of("--strict-shortcuts", f"{name}:app") == 2
    err = capsys.readouterr().err
    assert "shortcut conflicts" in err and "shortcut 'q' on 'Quit it' is a reserved command" in err
    assert "shortcut 'x' is used by 'X1', 'X2'" in err
    assert headless_run["runs"] == 0


def test_strict_shortcuts_on_a_clean_app_just_runs_it(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import App
        app = App("Clean")
        app.add_command("Fine", lambda: None, key="f")
    """)
    assert run_main("--strict-shortcuts", f"{name}:app") == 0
    assert sys.modules[name].app._strict_shortcuts is True and headless_run["runs"] == 1


def test_leaving_the_flag_out_never_loosens_an_app_built_strict(workdir, headless_run):
    name = write_module(workdir, """
        from cli_interface import App
        app = App("Strict", strict_shortcuts=True)
        app.add_command("Fine", lambda: None, key="f")
    """)
    assert run_main(f"{name}:app") == 0
    assert sys.modules[name].app._strict_shortcuts is True


def test_an_object_that_is_not_an_app_a_menu_or_a_callable_still_exits_two_naming_the_alternatives(workdir, headless_run, capsys):
    name = write_module(workdir, "VALUE = 5\n")
    assert exit_code_of(f"{name}:VALUE") == 2
    err = capsys.readouterr().err
    assert "neither a MenuItem nor a callable" in err and "app" in err


def test_a_callable_returning_something_else_names_the_app_option_too(workdir, headless_run, capsys):
    name = write_module(workdir, "def build():\n    return 5\n")
    assert exit_code_of(f"{name}:build") == 2
    assert "returned int, not a MenuItem or an app" in capsys.readouterr().err


def test_the_shipped_app_demo_resolves_as_a_target(monkeypatch, headless_run, demo_modules):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert run_main("examples.app_demo:app") == 0
    (app,) = headless_run["apps"]
    assert app is sys.modules["examples.app_demo"].app
    view = headless_run["views"][0]
    assert view["crumbs"] == ("Demo",) and view["labels"] == ["Run", "Tools", "Exit"]


def test_the_older_example_targets_still_build_a_plain_cliapp(monkeypatch, headless_run):
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for target in ("examples.main:build_menu", "examples.example_menu:build_menu"):
        assert run_main(target) == 0
        assert type(headless_run["apps"][-1]) is CLIApp, target
