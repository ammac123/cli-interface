"""P1.3 / P1.4 / P1.5 / CF-12 / CF-16: project metadata, lock, build configuration, CI and the demos' new home."""
from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
PROJECT = PYPROJECT["project"]
LOCK = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
CI = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def requirement(name: str) -> Requirement:
    (found,) = [Requirement(text) for text in PROJECT["dependencies"] if Requirement(text).name == name]
    return found


# --------------------------------------------------------------------------- P1.3: declared support

def test_python_3_11_or_newer_is_required():
    assert PROJECT["requires-python"] == ">=3.11"
    assert sys.version_info >= (3, 11)


def test_the_runtime_dependencies_are_exactly_rich_and_textual():
    assert sorted(Requirement(text).name for text in PROJECT["dependencies"]) == ["rich", "textual"]


def test_rich_has_a_floor_and_no_ceiling():
    assert {str(s) for s in requirement("rich").specifier} == {">=13.3.3"}


def test_textual_has_a_floor_and_a_ceiling_below_the_next_major():
    assert {str(s) for s in requirement("textual").specifier} == {">=0.80", "<9"}


def test_the_installed_dependencies_satisfy_the_declared_ranges():
    from importlib.metadata import version

    for name in ("rich", "textual"):
        assert Version(version(name)) in requirement(name).specifier, name


def test_the_classifiers_name_python_3_11_to_3_14_and_a_typed_package():
    classifiers = PROJECT["classifiers"]
    for minor in range(11, 15):
        assert f"Programming Language :: Python :: 3.{minor}" in classifiers
    assert "Typing :: Typed" in classifiers


def test_the_lock_file_records_the_same_requirements_as_pyproject():
    (own,) = [p for p in LOCK["package"] if p["name"] == "cli-interface"]
    declared = {item["name"]: item["specifier"] for item in own["metadata"]["requires-dist"]}
    assert declared == {"rich": ">=13.3.3", "textual": ">=0.80,<9"}
    assert LOCK["requires-python"] == ">=3.11"


def test_the_locked_versions_satisfy_the_declared_ranges():
    locked = {p["name"]: Version(p["version"]) for p in LOCK["package"] if "version" in p}
    assert locked["rich"] in requirement("rich").specifier
    assert locked["textual"] in requirement("textual").specifier
    assert locked["textual"] in SpecifierSet(">=0.80,<9")


# --------------------------------------------------------------------------- P1.4: what ships

def test_the_version_is_dynamic_and_read_from_the_package():
    assert "version" in PROJECT["dynamic"] and "version" not in PROJECT
    assert PYPROJECT["tool"]["hatch"]["version"]["path"] == "cli_interface/_version.py"
    assert (REPO / "cli_interface" / "_version.py").is_file()


def test_the_console_script_points_at_the_cli_module():
    assert PROJECT["scripts"] == {"cli-interface": "cli_interface.cli:main"}
    module, _, attribute = PROJECT["scripts"]["cli-interface"].partition(":")
    assert callable(getattr(importlib.import_module(module), attribute))


def test_the_wheel_ships_only_the_package():
    assert PYPROJECT["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == ["cli_interface"]


def test_the_sdist_has_an_explicit_include_list_without_tests_tooling_or_the_lock():
    sdist = PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]
    only_include = sdist["only-include"]
    assert {"cli_interface", "examples"} <= set(only_include)
    for excluded in ("tests", ".claude", ".github", "scripts", "uv.lock", "main.py", ".venv"):
        assert excluded not in only_include
    assert not [entry for entry in only_include if entry.startswith(("tests", ".claude", "uv.lock"))]
    assert "**/__pycache__" in sdist["exclude"]


@pytest.mark.parametrize("name", ["README.md", "LICENSE", "CHANGELOG.md"])
def test_the_files_the_sdist_includes_exist(name):
    assert name in PYPROJECT["tool"]["hatch"]["build"]["targets"]["sdist"]["only-include"]
    assert (REPO / name).is_file()


# --------------------------------------------------------------------------- P1.4b / CF-12: the demos live in examples/

def test_the_demos_moved_out_of_the_package_and_the_root():
    assert not (REPO / "main.py").exists()
    assert not list((REPO / "cli_interface").glob("example_*.py"))
    for name in ("__init__", "example_menu", "example_worker", "main"):
        assert (REPO / "examples" / f"{name}.py").is_file()


def test_the_old_demo_modules_can_no_longer_be_imported_from_the_package():
    for old in ("cli_interface.example_menu", "cli_interface.example_worker"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(old)


def test_the_demos_import_the_library_only_through_its_public_facade():
    offenders = []
    for path in sorted((REPO / "examples").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("cli_interface."):
                offenders.append(f"{path.name}: from {node.module}")
            if isinstance(node, ast.Import):
                offenders += [f"{path.name}: import {a.name}" for a in node.names if a.name.startswith("cli_interface.")]
    assert offenders == []


def test_the_demo_builder_has_the_documented_shape():
    import inspect
    import typing

    from examples.example_menu import build_menu
    from examples.example_worker import run

    assert list(inspect.signature(build_menu).parameters) == ["app"]
    assert typing.get_type_hints(build_menu)["return"].__name__ == "MenuItem"
    assert list(inspect.signature(run).parameters) == ["steps", "delay"]


def test_examples_main_is_runnable_as_a_module_and_importing_it_starts_nothing():
    probe = (
        "import json, logging, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import examples.main as m\n"
        "print(json.dumps({'main': callable(m.main), 'handlers': len(logging.getLogger().handlers)}))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe, str(REPO)], capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL, cwd=REPO.parent,
    )
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout.splitlines()[-1]) == {"main": True, "handlers": 0}


async def test_examples_main_builds_the_demo_app_and_returns_the_apps_exit_code(monkeypatch):
    from cli_interface import CLIApp
    from examples import main as demo_main
    from helpers import SIZE

    runs: list[CLIApp] = []
    monkeypatch.setattr(CLIApp, "run", lambda self, *a, **k: runs.append(self))
    monkeypatch.setattr(CLIApp, "return_code", property(lambda self: 5))
    assert demo_main.main() == 5
    (app,) = runs
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert app.query_one("#dashboard").location == "Home"
        assert "View Output" in str(app.query_one("#nav-bar").render())


# --------------------------------------------------------------------------- P1.5: lint, types, CI

def test_ruff_is_configured_for_the_project_python_and_the_agreed_rule_families():
    ruff = PYPROJECT["tool"]["ruff"]
    assert ruff["target-version"] == "py311" and ruff["line-length"] == 120
    assert set(ruff["lint"]["select"]) >= {"E4", "E7", "E9", "F", "UP", "B"}


def test_mypy_is_configured_for_the_project_python():
    mypy = PYPROJECT["tool"]["mypy"]
    assert mypy["python_version"] == "3.11" and mypy["check_untyped_defs"] is True


def test_the_dependency_groups_separate_test_lint_and_dev():
    groups = PYPROJECT["dependency-groups"]
    assert {Requirement(r).name for r in groups["test"]} == {"pytest", "pytest-asyncio"}
    assert {Requirement(r).name for r in groups["lint"]} == {"ruff", "mypy"}
    assert {"include-group": "test"} in groups["dev"] and {"include-group": "lint"} in groups["dev"]


def test_the_ci_matrix_covers_three_operating_systems_and_python_3_11_to_3_14():
    for os_name in ("ubuntu-latest", "macos-latest", "windows-latest"):
        assert re.search(rf"^\s+os: \[.*{os_name}.*\]", CI, re.M), os_name
    matrix = re.search(r"^\s+python: \[(.*)\]", CI, re.M)
    assert matrix is not None and re.findall(r'"(3\.\d+)"', matrix.group(1)) == ["3.11", "3.12", "3.13", "3.14"]


def test_the_ci_has_lowest_direct_legs_that_check_the_textual_floor():
    assert "resolution: lowest-direct" in CI
    assert "--resolution lowest-direct" in CI
    assert "== '0.80.0'" in CI


def test_the_ci_installs_the_locked_versions():
    assert "uv sync --locked" in CI


def test_the_ci_runs_lint_types_tests_the_console_script_and_the_dist_check():
    assert "ruff check cli_interface examples scripts tests" in CI
    assert "mypy cli_interface examples scripts" in CI
    assert "pytest" in CI
    assert "cli-interface --version" in CI and "cli-interface --help" in CI
    assert "uv build" in CI and "scripts/check_dist.py" in CI


def test_the_ci_dist_check_covers_both_archives():
    line = next(ln for ln in CI.splitlines() if "scripts/check_dist.py" in ln)
    assert "dist/*.tar.gz" in line and "dist/*.whl" in line


def test_the_ci_runs_on_pushes_to_main_and_on_pull_requests():
    assert re.search(r"^on:\n  push:\n    branches: \[main\]\n  pull_request:", CI, re.M)


def test_the_dist_check_script_is_standard_library_only():
    tree = ast.parse((REPO / "scripts" / "check_dist.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported and imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)


# --------------------------------------------------------------------------- pytest configuration (T2)

def test_pytest_collects_only_tests_and_makes_the_repository_importable():
    options = PYPROJECT["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests"] and options["pythonpath"] == ["."]
    assert options["asyncio_mode"] == "auto"
