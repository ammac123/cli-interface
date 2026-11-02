"""P1.4a / P1.5: scripts/check_dist.py against synthetic archives (a real build is the integrator's job)."""
from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "check_dist.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dist_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_dist = load_script()
VERSION = check_dist.repo_version()
PACKAGE_FILES = [f"cli_interface/{m}.py" for m in check_dist.PACKAGE_MODULES] + ["cli_interface/py.typed"]
EXAMPLE_FILES = [f"examples/{m}.py" for m in check_dist.EXAMPLE_MODULES]


def metadata(
    version: str = VERSION or "0.0.0",
    *,
    requires_python: str | None = ">=3.11",
    rich: str | None = "rich>=13.3.3",
    textual: str | None = "textual<9,>=0.80",
) -> str:
    lines = ["Metadata-Version: 2.4", "Name: cli-interface", f"Version: {version}"]
    if requires_python is not None:
        lines.append(f"Requires-Python: {requires_python}")
    lines += [f"Requires-Dist: {requirement}" for requirement in (rich, textual) if requirement is not None]
    return "\n".join(lines) + "\n\nTUI frontend.\n"


def sdist_files(version: str = VERSION or "0.0.0") -> dict[str, str]:
    files = {
        "PKG-INFO": metadata(version),
        "pyproject.toml": "[project]\n",
        "README.md": "readme\n",
        "LICENSE": "license\n",
        "CHANGELOG.md": "changes\n",
        ".gitignore": "__pycache__/\n",
    }
    files.update({name: "" for name in PACKAGE_FILES + EXAMPLE_FILES})
    files["cli_interface/_version.py"] = f'__version__ = "{version}"\n'
    return files


def wheel_files(version: str = VERSION or "0.0.0") -> dict[str, str]:
    dist_info = f"cli_interface-{version}.dist-info"
    files = {name: "" for name in PACKAGE_FILES}
    files["cli_interface/_version.py"] = f'__version__ = "{version}"\n'
    files.update({
        f"{dist_info}/METADATA": metadata(version),
        f"{dist_info}/WHEEL": "Wheel-Version: 1.0\n",
        f"{dist_info}/RECORD": "",
        f"{dist_info}/entry_points.txt": "[console_scripts]\ncli-interface = cli_interface.cli:main\n",
        f"{dist_info}/licenses/LICENSE": "license\n",
    })
    return files


def build_sdist(
    path: Path,
    version: str = VERSION or "0.0.0",
    *,
    add: Mapping[str, str] | None = None,
    drop: tuple[str, ...] = (),
    replace: Mapping[str, str] | None = None,
    root: str | None = None,
    outside: Mapping[str, str] | None = None,
    symlinks: tuple[str, ...] = (),
) -> Path:
    files = {**sdist_files(version), **(replace or {}), **(add or {})}
    for name in drop:
        del files[name]
    root = root or f"cli_interface-{version}"
    with tarfile.open(path, "w:gz") as tar:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name, text in (outside or {}).items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        for name in symlinks:
            link = tarfile.TarInfo(f"{root}/{name}")
            link.type = tarfile.SYMTYPE
            link.linkname = "/etc/passwd"
            tar.addfile(link)
    return path


def build_wheel(
    path: Path,
    version: str = VERSION or "0.0.0",
    *,
    add: Mapping[str, str] | None = None,
    drop: tuple[str, ...] = (),
    replace: Mapping[str, str] | None = None,
) -> Path:
    files = {**wheel_files(version), **(replace or {}), **(add or {})}
    for name in drop:
        del files[name]
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return path


@pytest.fixture
def sdist(tmp_path: Path) -> Path:
    return build_sdist(tmp_path / f"cli_interface-{VERSION}.tar.gz")


@pytest.fixture
def wheel(tmp_path: Path) -> Path:
    return build_wheel(tmp_path / f"cli_interface-{VERSION}-py3-none-any.whl")


def problems_of(path: Path) -> list[str]:
    return check_dist.check_artifact(str(path))[0]


def assert_flagged(problems: list[str], *needles: str) -> None:
    joined = "\n".join(problems)
    assert problems, "expected the archive to be rejected"
    for needle in needles:
        assert needle in joined, f"{needle!r} not in:\n{joined}"


# --------------------------------------------------------------------------- the positive controls

def test_the_repository_declares_a_readable_version():
    assert VERSION and re.fullmatch(r"\d+\.\d+\.\d+.*", VERSION)


def test_a_well_formed_sdist_has_no_problems(sdist):
    problems, versions = check_dist.check_artifact(str(sdist))
    assert problems == []
    assert versions == [("PKG-INFO", VERSION), ("_version.py", VERSION)]


def test_a_well_formed_wheel_has_no_problems(wheel):
    problems, versions = check_dist.check_artifact(str(wheel))
    assert problems == []
    assert versions == [("METADATA", VERSION), ("_version.py", VERSION)]


def test_main_returns_zero_and_prints_one_ok_line_per_artifact(sdist, wheel, capsys):
    assert check_dist.main([str(sdist), str(wheel)]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [f"ok   {sdist}", f"ok   {wheel}", "all artifacts pass"] and err == ""


def test_the_real_file_set_of_the_repository_passes_the_allowlist(tmp_path):
    sdist_members = {
        f"{folder}/{path.name}": path.read_text(encoding="utf-8")
        for folder in ("cli_interface", "examples")
        for path in sorted((REPO / folder).glob("*.py"))
    }
    sdist_members["cli_interface/py.typed"] = ""
    wheel_members = {name: text for name, text in sdist_members.items() if name.startswith("cli_interface/")}
    sdist = build_sdist(tmp_path / "real.tar.gz", replace=sdist_members)
    wheel = build_wheel(tmp_path / "real.whl", replace=wheel_members)
    assert problems_of(sdist) == [] and problems_of(wheel) == []


def test_the_allowlists_name_every_module_the_package_and_the_examples_actually_have():
    on_disk = {p.stem for p in (REPO / "cli_interface").glob("*.py")}
    assert on_disk == set(check_dist.PACKAGE_MODULES)
    assert {p.stem for p in (REPO / "examples").glob("*.py")} == set(check_dist.EXAMPLE_MODULES)


# --------------------------------------------------------------------------- the sdist negatives

SDIST_FORBIDDEN = [
    ("tests/test_x.py", "tests/ must not ship"),
    ("tests/conftest.py", "tests/ must not ship"),
    (".claude/pipeline/phase-1.md", ".claude/ must not ship"),
    (".github/workflows/ci.yml", ".github/ must not ship"),
    ("scripts/check_dist.py", "scripts/ must not ship"),
    ("uv.lock", "uv.lock must not ship"),
    ("main.py", "main.py must not ship"),
    (".python-version", ".python-version must not ship"),
    ("cli_interface/__pycache__/app.cpython-313.pyc", "bytecode cache directory"),
    ("examples/__pycache__/x.cpython-313.pyc", "bytecode cache directory"),
    ("cli_interface/stale.pyc", "compiled bytecode"),
    ("whiteboard/notes.md", "whiteboard material"),
    ("whiteboard.md", "whiteboard material"),
    ("cli_interface/example_menu.py", "demo modules belong in examples/"),
    ("cli_interface/example_worker.py", "demo modules belong in examples/"),
    ("notes.txt", "not on the allowlist"),
    ("cli_interface/sub/extra.py", "not on the allowlist"),
    ("cli_interface/data.json", "not on the allowlist"),
    ("examples/readme.txt", "not on the allowlist"),
]


@pytest.mark.parametrize("member, reason", SDIST_FORBIDDEN)
def test_an_sdist_with_a_forbidden_member_is_rejected_with_a_specific_reason(tmp_path, member, reason):
    archive = build_sdist(tmp_path / "bad.tar.gz", add={member: "x"})
    assert_flagged(problems_of(archive), f"{member}: {reason}")


def test_main_exits_one_and_names_the_archive_and_member_on_stderr(tmp_path, capsys):
    archive = build_sdist(tmp_path / "bad.tar.gz", add={"tests/test_x.py": ""})
    assert check_dist.main([str(archive)]) == 1
    out, err = capsys.readouterr()
    assert out == f"FAIL {archive}\n"
    assert "error: bad.tar.gz: tests/test_x.py: tests/ must not ship" in err
    assert "1 problem(s) found" in err


@pytest.mark.parametrize("missing", ["cli_interface/py.typed", "cli_interface/cli.py", "cli_interface/_version.py",
                                     "cli_interface/warning_types.py", "examples/main.py", "examples/__init__.py"])
def test_an_sdist_missing_a_required_member_is_rejected(tmp_path, missing):
    archive = build_sdist(tmp_path / "bad.tar.gz", drop=(missing,))
    assert_flagged(problems_of(archive), f"{missing}: required member is missing")


def test_an_sdist_with_a_stale_name_for_the_package_directory_is_rejected(tmp_path):
    archive = build_sdist(tmp_path / "bad.tar.gz", root="cli_interface-9.9.9")
    assert_flagged(problems_of(archive), "does not match PKG-INFO version")


def test_an_sdist_member_outside_the_root_is_rejected(tmp_path):
    archive = build_sdist(tmp_path / "bad.tar.gz", outside={"elsewhere/file.py": "x"})
    assert_flagged(problems_of(archive), "elsewhere/file.py: outside the sdist root")


def test_an_sdist_with_a_path_traversal_member_is_rejected(tmp_path):
    archive = build_sdist(tmp_path / "bad.tar.gz", add={"cli_interface/../../evil.py": "x"})
    assert_flagged(problems_of(archive), "unsafe member name")


def test_an_sdist_with_a_symlink_member_is_rejected(tmp_path):
    archive = build_sdist(tmp_path / "bad.tar.gz", symlinks=("link.py",))
    assert_flagged(problems_of(archive), "link.py: not a regular file")


# --------------------------------------------------------------------------- the wheel negatives

WHEEL_FORBIDDEN = [
    ("tests/test_x.py", "tests/ must not ship"),
    (".claude/y", ".claude/ must not ship"),
    ("scripts/check_dist.py", "scripts/ must not ship"),
    ("uv.lock", "uv.lock must not ship"),
    ("main.py", "main.py must not ship"),
    ("cli_interface/example_menu.py", "demo modules belong in examples/"),
    ("cli_interface/example_worker.py", "demo modules belong in examples/"),
    ("examples/main.py", "examples/ ships in the sdist only"),
    ("examples/__init__.py", "examples/ ships in the sdist only"),
    ("cli_interface/__pycache__/app.cpython-313.pyc", "bytecode cache directory"),
    ("cli_interface/extra.txt", "not on the allowlist"),
    ("stray.py", "not on the allowlist"),
]


@pytest.mark.parametrize("member, reason", WHEEL_FORBIDDEN)
def test_a_wheel_with_a_forbidden_member_is_rejected_with_a_specific_reason(tmp_path, member, reason):
    archive = build_wheel(tmp_path / "bad.whl", add={member: "x"})
    assert_flagged(problems_of(archive), f"{member}: {reason}")


@pytest.mark.parametrize("missing", ["cli_interface/py.typed", "cli_interface/cli.py", "cli_interface/warning_types.py",
                                     f"cli_interface-{VERSION}.dist-info/entry_points.txt"])
def test_a_wheel_missing_a_required_member_is_rejected(tmp_path, missing):
    archive = build_wheel(tmp_path / "bad.whl", drop=(missing,))
    assert_flagged(problems_of(archive), f"{missing}: required member is missing")


@pytest.mark.parametrize("script_line", [
    "cli-interface = cli_interface.app:run",
    "cli-interface = cli_interface.cli:other",
    "other-name = cli_interface.cli:main",
    "",
])
def test_a_wheel_with_the_wrong_console_script_is_rejected(tmp_path, script_line):
    entry_points = f"[console_scripts]\n{script_line}\n"
    archive = build_wheel(tmp_path / "bad.whl", replace={f"cli_interface-{VERSION}.dist-info/entry_points.txt": entry_points})
    assert_flagged(problems_of(archive), "missing console script 'cli-interface = cli_interface.cli:main'")


def test_a_console_script_in_the_wrong_section_does_not_count(tmp_path):
    entry_points = "[gui_scripts]\ncli-interface = cli_interface.cli:main\n"
    archive = build_wheel(tmp_path / "bad.whl", replace={f"cli_interface-{VERSION}.dist-info/entry_points.txt": entry_points})
    assert_flagged(problems_of(archive), "missing console script")


# --------------------------------------------------------------------------- metadata, for both kinds

def metadata_variants() -> list[tuple[str, str, str]]:
    return [
        ("python", metadata(requires_python=">=3.10"), "Requires-Python is '>=3.10'"),
        ("python-missing", metadata(requires_python=None), "Requires-Python is ''"),
        ("rich-floor", metadata(rich="rich>=13.0.0"), "Requires-Dist rich is [['>=13.0.0']]"),
        ("rich-missing", metadata(rich=None), "Requires-Dist rich is missing"),
        ("textual-floor", metadata(textual="textual<9,>=0.70"), "Requires-Dist textual is [['<9', '>=0.70']]"),
        ("textual-no-ceiling", metadata(textual="textual>=0.80"), "Requires-Dist textual is [['>=0.80']]"),
        ("textual-wrong-ceiling", metadata(textual="textual<10,>=0.80"), "Requires-Dist textual is [['<10', '>=0.80']]"),
        ("textual-missing", metadata(textual=None), "Requires-Dist textual is missing"),
    ]


@pytest.mark.parametrize("name, text, reason", metadata_variants(), ids=[v[0] for v in metadata_variants()])
def test_an_sdist_with_wrong_metadata_is_rejected(tmp_path, name, text, reason):
    archive = build_sdist(tmp_path / "bad.tar.gz", replace={"PKG-INFO": text})
    assert_flagged(problems_of(archive), reason)


@pytest.mark.parametrize("name, text, reason", metadata_variants(), ids=[v[0] for v in metadata_variants()])
def test_a_wheel_with_wrong_metadata_is_rejected(tmp_path, name, text, reason):
    archive = build_wheel(tmp_path / "bad.whl", replace={f"cli_interface-{VERSION}.dist-info/METADATA": text})
    assert_flagged(problems_of(archive), reason)


def test_metadata_may_spell_the_textual_specifier_in_either_order(tmp_path):
    for spelling in ("textual<9,>=0.80", "textual>=0.80,<9", "textual (>=0.80,<9)", "textual >= 0.80, < 9"):
        archive = build_wheel(
            tmp_path / "ok.whl", replace={f"cli_interface-{VERSION}.dist-info/METADATA": metadata(textual=spelling)}
        )
        assert problems_of(archive) == [], spelling


# --------------------------------------------------------------------------- versions

def test_a_wheel_whose_dist_info_directory_disagrees_with_its_metadata_is_rejected(tmp_path):
    archive = build_wheel(tmp_path / "bad.whl", replace={f"cli_interface-{VERSION}.dist-info/METADATA": metadata("9.9.9")})
    assert_flagged(problems_of(archive), "does not match METADATA version '9.9.9'")


def test_an_archive_whose_metadata_and_shipped_version_disagree_is_a_version_mismatch(tmp_path, capsys):
    archive = build_wheel(tmp_path / "bad.whl", replace={"cli_interface/_version.py": '__version__ = "9.9.9"\n'})
    assert check_dist.main([str(archive)]) == 1
    assert "version mismatch" in capsys.readouterr().err


def test_an_sdist_and_a_wheel_of_different_versions_are_a_version_mismatch(tmp_path, capsys):
    sdist = build_sdist(tmp_path / "a.tar.gz", "9.9.9")
    wheel = build_wheel(tmp_path / "a.whl")
    assert problems_of(sdist) == [] and problems_of(wheel) == []
    assert check_dist.main([str(sdist), str(wheel)]) == 1
    assert "version mismatch" in capsys.readouterr().err


def test_a_lone_self_consistent_archive_of_another_version_still_fails_against_the_repository_version(tmp_path, capsys):
    wheel = build_wheel(tmp_path / "other.whl", "9.9.9")
    assert problems_of(wheel) == []
    assert check_dist.main([str(wheel)]) == 1
    err = capsys.readouterr().err
    assert "version mismatch" in err and "repo _version.py=" in err and "9.9.9" in err


def test_an_unreadable_repository_version_is_noted_and_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(check_dist, "REPO_VERSION_FILE", tmp_path / "missing" / "_version.py")
    wheel = build_wheel(tmp_path / "other.whl", "9.9.9")
    assert check_dist.main([str(wheel)]) == 0
    assert "note:" in capsys.readouterr().out


# --------------------------------------------------------------------------- unreadable input and usage

def test_a_file_that_is_not_a_gzip_tarball_is_rejected_not_crashed_on(tmp_path):
    bad = tmp_path / "bad.tar.gz"
    bad.write_bytes(b"this is not a tarball")
    assert_flagged(problems_of(bad), "cannot read archive")
    assert check_dist.main([str(bad)]) == 1


def test_a_file_that_is_not_a_zip_is_rejected_not_crashed_on(tmp_path):
    bad = tmp_path / "bad.whl"
    bad.write_bytes(b"PK nope")
    assert_flagged(problems_of(bad), "cannot read archive")


def test_a_missing_file_is_rejected(tmp_path, capsys):
    assert check_dist.main([str(tmp_path / "absent.whl")]) == 1
    assert "cannot read archive" in capsys.readouterr().err


def test_an_unsupported_archive_type_is_rejected(tmp_path):
    other = tmp_path / "dist.zip"
    other.write_bytes(b"")
    assert_flagged(problems_of(other), "unsupported artifact type")


def test_main_without_arguments_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        check_dist.main([])
    assert exit_info.value.code == 2


def test_wildcards_the_shell_did_not_expand_are_expanded(tmp_path, capsys):
    build_wheel(tmp_path / "one.whl")
    build_sdist(tmp_path / "one.tar.gz")
    assert check_dist.main([str(tmp_path / "one.*")]) == 0
    assert capsys.readouterr().out.count("ok  ") == 2


def test_every_failing_archive_is_reported_not_just_the_first(tmp_path, capsys):
    bad_sdist = build_sdist(tmp_path / "a.tar.gz", add={"uv.lock": ""})
    bad_wheel = build_wheel(tmp_path / "b.whl", add={"tests/x.py": ""})
    assert check_dist.main([str(bad_sdist), str(bad_wheel)]) == 1
    err = capsys.readouterr().err
    assert "a.tar.gz: uv.lock: uv.lock must not ship" in err and "b.whl: tests/x.py: tests/ must not ship" in err
    assert "2 problem(s) found" in err


def test_non_ascii_member_names_are_reported_without_crashing(tmp_path, capsys):
    archive = build_sdist(tmp_path / "bad.tar.gz", add={"café.py": ""})
    assert check_dist.main([str(archive)]) == 1
    err = capsys.readouterr().err
    assert err.isascii() and "caf" in err


# --------------------------------------------------------------------------- runnable locally, stdlib only

def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )


def test_the_script_runs_standalone_and_exits_zero_on_good_archives(sdist, wheel):
    done = run_script(str(sdist), str(wheel))
    assert done.returncode == 0 and "all artifacts pass" in done.stdout and done.stderr == ""


def test_the_script_runs_standalone_and_exits_one_on_a_bad_archive(tmp_path):
    bad = build_sdist(tmp_path / "bad.tar.gz", add={"tests/test_x.py": ""})
    done = run_script(str(bad))
    assert done.returncode == 1 and "tests/ must not ship" in done.stderr


def test_the_script_without_arguments_exits_two():
    done = run_script()
    assert done.returncode == 2 and "usage:" in done.stderr
