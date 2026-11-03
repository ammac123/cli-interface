"""P1.1 / CF-9 / CF-3: the package facade, its version and typing marker, and the warning categories."""
from __future__ import annotations

import importlib.metadata
import importlib.resources
import json
import logging
import re
import subprocess
import sys
import tomllib
import typing
import warnings
from pathlib import Path

import pytest

import cli_interface
from cli_interface import (
    CLIApp,
    LogAttachment,
    LoggingAttachWarning,
    MenuItem,
    ShortcutConflictWarning,
    attach_logging,
)
from helpers import SIZE, leaf, menu

REPO = Path(__file__).resolve().parent.parent

PUBLIC_NAMES = {
    "App",
    "CLIApp",
    "Context",
    "DisplayPanel",
    "LogAttachment",
    "LoggingAttachWarning",
    "MenuItem",
    "Param",
    "RESERVED_COMMANDS",
    "Secret",
    "ShortcutConflictWarning",
    "__version__",
    "attach_logging",
    "find_shortcut_conflicts",
    "run",
}
INTERNAL_NAMES = ["PanelInbox", "TUILogHandler", "Job", "JobManager", "MenuState", "PromptScreen", "Dashboard", "NavBar", "theme"]


# --------------------------------------------------------------------------- P1.1a: the facade

def test_all_is_exactly_the_documented_public_api():
    assert set(cli_interface.__all__) == PUBLIC_NAMES
    assert len(cli_interface.__all__) == len(PUBLIC_NAMES), "no name listed twice"


def test_every_name_in_all_resolves_on_the_package():
    for name in cli_interface.__all__:
        assert hasattr(cli_interface, name), name


@pytest.mark.parametrize("name", INTERNAL_NAMES)
def test_internal_names_are_not_exported(name):
    assert name not in cli_interface.__all__
    namespace: dict[str, object] = {}
    exec("from cli_interface import *", namespace)  # noqa: S102
    assert name not in namespace


def test_a_star_import_brings_in_exactly_the_public_names():
    namespace: dict[str, object] = {}
    exec("from cli_interface import *", namespace)
    assert set(namespace) - {"__builtins__"} == PUBLIC_NAMES


def test_the_facade_names_are_the_real_objects():
    from cli_interface.app import CLIApp as AppClass
    from cli_interface.app import attach_logging as attach
    from cli_interface.app import run as run_function
    from cli_interface.display import DisplayPanel
    from cli_interface.menu import RESERVED_COMMANDS, find_shortcut_conflicts

    assert cli_interface.CLIApp is AppClass and cli_interface.attach_logging is attach
    assert cli_interface.run is run_function and cli_interface.DisplayPanel is DisplayPanel
    assert cli_interface.MenuItem is MenuItem
    assert cli_interface.RESERVED_COMMANDS is RESERVED_COMMANDS
    assert cli_interface.find_shortcut_conflicts is find_shortcut_conflicts


# --------------------------------------------------------------------------- CF-9: LogAttachment is a return type

def test_log_attachment_is_exported_as_the_return_type_of_attach_logging():
    assert "LogAttachment" in cli_interface.__all__
    assert typing.get_type_hints(attach_logging)["return"] is LogAttachment


async def test_attach_logging_returns_a_log_attachment(make_app, unique_logger):
    app = make_app(leaf("A", "a"))
    lg = unique_logger()
    async with app.run_test(size=SIZE):
        assert isinstance(attach_logging(app, lg), LogAttachment)


def test_log_attachment_is_exported_without_its_collaborators():
    assert not hasattr(cli_interface, "PanelInbox")
    assert not hasattr(cli_interface, "TUILogHandler")


# --------------------------------------------------------------------------- __version__ and py.typed

def test_version_is_a_release_string():
    assert re.fullmatch(r"\d+\.\d+\.\d+([abc]\d+|\.dev\d+|rc\d+)?", cli_interface.__version__)


def test_version_matches_the_installed_distribution_metadata():
    assert cli_interface.__version__ == importlib.metadata.version("cli-interface")


def test_version_has_a_single_source_that_pyproject_reads():
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert "version" in project["project"]["dynamic"] and "version" not in project["project"]
    source = REPO / project["tool"]["hatch"]["version"]["path"]
    declared = re.search(r"""^__version__\s*=\s*["']([^"']+)["']\s*$""", source.read_text(encoding="utf-8"), re.M)
    assert declared is not None and declared.group(1) == cli_interface.__version__


def test_the_package_ships_the_py_typed_marker():
    marker = importlib.resources.files("cli_interface").joinpath("py.typed")
    assert marker.is_file() and marker.read_bytes() == b""


IMPORT_PROBE = """
import json, logging, sys
root = logging.getLogger()
before = ([type(h).__name__ for h in root.handlers], root.level)
import cli_interface
after = ([type(h).__name__ for h in root.handlers], root.level)
print(json.dumps({"before": before, "after": after}))
"""


def test_importing_the_package_configures_no_logging():
    out = subprocess.run(
        [sys.executable, "-c", IMPORT_PROBE], capture_output=True, text=True, timeout=60, check=True,
        stdin=subprocess.DEVNULL, cwd=REPO,
    ).stdout
    result = json.loads(out.strip().splitlines()[-1])
    assert result["after"] == result["before"] == [[], logging.WARNING]


# --------------------------------------------------------------------------- CF-3: warning categories

def test_both_warning_categories_are_user_warnings():
    assert issubclass(ShortcutConflictWarning, UserWarning)
    assert issubclass(LoggingAttachWarning, UserWarning)
    assert not issubclass(ShortcutConflictWarning, LoggingAttachWarning)
    assert not issubclass(LoggingAttachWarning, ShortcutConflictWarning)


def test_a_shortcut_conflict_warns_with_its_own_category_and_still_matches_user_warning():
    conflicted = menu(leaf("Quit it", "q"))
    with pytest.warns(ShortcutConflictWarning, match="reserved command"):
        CLIApp(conflicted)
    with pytest.warns(UserWarning, match="reserved command"):
        CLIApp(conflicted)


async def test_a_repeat_attach_with_ignored_arguments_warns_with_its_own_category(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        attach_logging(app, lg)
        with pytest.warns(LoggingAttachWarning, match="were ignored because"):
            attach_logging(app, lg, level=10)


def test_the_pytest_filters_escalate_the_shortcut_conflict_category():
    with pytest.raises(ShortcutConflictWarning, match="reserved command"):
        CLIApp(menu(leaf("Quit it", "q")))


async def test_the_pytest_filters_escalate_the_ignored_attach_arguments_warning(make_app, unique_logger):
    lg = unique_logger()
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE):
        first = attach_logging(app, lg)
        with pytest.raises(LoggingAttachWarning, match="were ignored because"):
            attach_logging(app, lg, exclusive=True)
        assert first.active and len(lg.handlers) == 1


def test_a_plain_user_warning_with_the_old_message_text_is_not_escalated():
    with warnings.catch_warnings(record=True) as caught:  # keeps the filters pytest installed
        warnings.warn("x is a reserved command and will never reach y", UserWarning, stacklevel=1)
        warnings.warn("only the first is reachable; were ignored because", UserWarning, stacklevel=1)
    assert len(caught) == 2


def test_pyproject_filters_are_by_category_not_by_message():
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    filters = config["filterwarnings"]
    assert "error::cli_interface.ShortcutConflictWarning" in filters
    assert "error::cli_interface.LoggingAttachWarning" in filters
    assert "error::pytest.PytestUnhandledThreadExceptionWarning" in filters
    assert not [f for f in filters if "reserved command" in f or "were ignored because" in f or ":UserWarning" in f]


# --------------------------------------------------------------------------- Phase 2: App and Context join the facade

def test_the_public_api_is_exactly_fifteen_names():
    assert len(cli_interface.__all__) == 15 == len(PUBLIC_NAMES)
    assert {"App", "Context"} <= set(cli_interface.__all__)


def test_app_and_context_are_the_real_classes():
    from cli_interface.commands import App as AppClass
    from cli_interface.context import Context as ContextClass

    assert cli_interface.App is AppClass and cli_interface.Context is ContextClass
    assert issubclass(cli_interface.App, cli_interface.CLIApp)


@pytest.mark.parametrize("name", ["Job", "JobManager", "JobEmitter", "JobCancelled", "PanelRenderer", "OutputCapture"])
def test_the_job_machinery_is_not_exported(name):
    assert name not in cli_interface.__all__ and not hasattr(cli_interface, name)


def test_the_original_eleven_names_all_still_resolve():
    original = PUBLIC_NAMES - {"App", "Context", "Param", "Secret"}
    assert len(original) == 11 and all(hasattr(cli_interface, n) for n in original)


ALL_MODULES_PROBE = """
import importlib, json, logging, pkgutil, sys
root = logging.getLogger()
before = ([type(h).__name__ for h in root.handlers], root.level, logging.lastResort is not None)
import cli_interface, examples.app_demo
for info in pkgutil.iter_modules(cli_interface.__path__):
    importlib.import_module("cli_interface." + info.name)
named = {name: [type(h).__name__ for h in logging.getLogger(name).handlers]
         for name in logging.root.manager.loggerDict if name.startswith("cli_interface")}
after = ([type(h).__name__ for h in root.handlers], root.level, logging.lastResort is not None)
print(json.dumps({"before": before, "after": after, "named": named, "stdout_is_original": sys.stdout is sys.__stdout__}))
"""


def test_importing_every_module_and_the_demo_configures_no_logging_and_leaves_the_streams_alone():
    out = subprocess.run(
        [sys.executable, "-c", ALL_MODULES_PROBE], capture_output=True, text=True, timeout=60, check=True,
        stdin=subprocess.DEVNULL, cwd=REPO,
    ).stdout
    result = json.loads(out.strip().splitlines()[-1])
    assert result["after"] == result["before"] == [[], logging.WARNING, True]
    assert all(handlers == [] for handlers in result["named"].values())
    assert result["stdout_is_original"] is True
