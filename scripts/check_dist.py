"""Check built cli-interface archives against the shipping allowlist.

Usage, after building into a scratch or ignored directory::

    uv build --out-dir dist
    python scripts/check_dist.py dist/*.tar.gz dist/*.whl

Takes sdist (.tar.gz) and wheel (.whl) paths (wildcards the shell leaves alone are expanded) and
prints ``ok`` or ``FAIL`` per archive, then each problem on stderr. Exit codes: 0 when every archive
passes, 1 on any violation (including an unreadable archive or an unsupported file type), 2 for a
usage error such as no arguments. Standard library only. Archive member names are handled as POSIX
strings, so the check behaves the same on every host OS.

What it enforces:

- Every member is on the allowlist and none is on the deny list. The sdist may hold only the package,
  ``examples/``, README, LICENSE, CHANGELOG, PKG-INFO, pyproject.toml and .gitignore (which hatch adds
  itself); the wheel only the package, ``py.typed`` and its dist-info. Never ``tests/``, ``.claude/``,
  ``.github/``, ``scripts/``, ``uv.lock``, ``main.py``, bytecode, or demo modules inside ``cli_interface/``.
  ``examples/`` is shipped in the sdist and must not be in the wheel.
- The required members are present: every package module and ``py.typed`` in both archives, the
  ``examples/`` modules in the sdist, and the console-script entry point in the wheel.
- The metadata has the expected values (the constants below, kept in step with ``pyproject.toml``):
  Requires-Python, the ``rich`` and ``textual`` specifiers, and the ``cli-interface = cli_interface.cli:main``
  script.
- The versions agree: PKG-INFO / METADATA, the archive's ``_version.py``, the sdist root and dist-info
  directory names, and the repository's own ``cli_interface/_version.py`` (so a stale ``dist/`` fails
  after a version bump; the comparison is skipped with a note if that file is absent).

Update the constants below when the module list, the dependency floors or the Python floor change.
"""

import argparse
import glob
import posixpath
import re
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from email.message import Message
from email.parser import HeaderParser
from pathlib import Path, PurePath

PACKAGE = "cli_interface"
MODULE = r"[A-Za-z_]+"

PACKAGE_MODULES = (
    "__init__",
    "_version",
    "app",
    "capture",
    "cli",
    "commands",
    "context",
    "display",
    "events",
    "jobs",
    "log_handler",
    "menu",
    "outcome",
    "params",
    "phrases",
    "settings",
    "settings_menu",
    "theme",
    "widgets",
    "warning_types",
)
EXAMPLE_MODULES = ("__init__", "app_demo", "example_menu", "example_worker", "main")

REQUIRES_PYTHON = ">=3.13"
REQUIRED_DEPENDENCIES = {
    "rich": frozenset({">=13.3.3"}),
    "textual": frozenset({">=0.80", "<9"}),
}
SCRIPT_NAME = "cli-interface"
SCRIPT_TARGET = "cli_interface.cli:main"
REPO_VERSION_FILE = Path(__file__).resolve().parents[1] / PACKAGE / "_version.py"

# Files hatch adds to the sdist regardless of only-include: PKG-INFO, pyproject.toml, the readme, the
# license files and .gitignore. CHANGELOG.md and examples/ are in only-include, so they are listed explicitly.
SDIST_ALLOW = (
    r"PKG-INFO",
    r"pyproject\.toml",
    r"README\.md",
    r"LICENSE",
    r"CHANGELOG\.md",
    r"\.gitignore",
    rf"{PACKAGE}/{MODULE}\.py",
    rf"{PACKAGE}/py\.typed",
    rf"examples/{MODULE}\.py",
)
WHEEL_ALLOW = (
    rf"{PACKAGE}/{MODULE}\.py",
    rf"{PACKAGE}/py\.typed",
)
WHEEL_DIST_INFO_FILES = r"(?:METADATA|WHEEL|RECORD|entry_points\.txt|licenses/LICENSE|LICENSE)"

DENY = (
    (r"(?:^|/)__pycache__(?:/|$)", "bytecode cache directory"),
    (r"\.py[co]$", "compiled bytecode"),
    (r"(?:^|/)whiteboard", "whiteboard material"),
    (r"^tests/", "tests/ must not ship"),
    (r"^\.claude/", ".claude/ must not ship"),
    (r"^\.github/", ".github/ must not ship"),
    (r"^scripts/", "scripts/ must not ship"),
    (r"^uv\.lock$", "uv.lock must not ship"),
    (r"^main\.py$", "main.py must not ship"),
    (r"^\.python-version$", ".python-version must not ship"),
    (rf"^{PACKAGE}/example_", "demo modules belong in examples/, not in the package"),
)
WHEEL_DENY = ((r"^examples/", "examples/ ships in the sdist only"),)

SMALL_TEXT_FILES = ("PKG-INFO", "METADATA", "entry_points.txt", "_version.py")
MAX_TEXT_BYTES = 1 << 20
VERSION_LINE = re.compile(r"""^__version__\s*=\s*["']([^"']+)["']\s*$""", re.MULTILINE)
REQUIREMENT = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:\[[^\]]*\])?\s*\(?\s*([^;()]*?)\s*\)?\s*(?:;(.*))?$"
)


def ascii_text(text: str) -> str:
    """``text`` with non-ASCII characters escaped, so output is safe on any console encoding."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def read_archive(path: str) -> tuple[list[str], dict[str, str], list[str]]:
    """Return file member names, the decoded small text members by name, and read problems."""
    names: list[str] = []
    texts: dict[str, str] = {}
    problems: list[str] = []
    if path.lower().endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as tar:
            for member in tar.getmembers():
                name = member.name.removeprefix("./").rstrip("/")
                if member.isdir():
                    continue
                if not member.isfile():
                    problems.append(f"{name}: not a regular file")
                    continue
                names.append(name)
                if posixpath.basename(name) in SMALL_TEXT_FILES and member.size <= MAX_TEXT_BYTES:
                    handle = tar.extractfile(member)
                    if handle is not None:
                        texts[name] = handle.read().decode("utf-8", "replace")
    elif path.lower().endswith(".whl"):
        with zipfile.ZipFile(path) as wheel:
            for info in wheel.infolist():
                if info.is_dir():
                    continue
                names.append(info.filename)
                if posixpath.basename(info.filename) in SMALL_TEXT_FILES and info.file_size <= MAX_TEXT_BYTES:
                    texts[info.filename] = wheel.read(info).decode("utf-8", "replace")
    else:
        problems.append("unsupported artifact type (expected .tar.gz or .whl)")
    return names, texts, problems


def unsafe_name(name: str) -> bool:
    """True for an archive member name that is absolute, climbs with ``..`` or looks like a drive path."""
    return name.startswith("/") or ".." in name.split("/") or "\\" in name or bool(re.match(r"[A-Za-z]:", name))


def check_files(names: Sequence[str], allow: Sequence[str], deny: Sequence[tuple[str, str]]) -> list[str]:
    """Problems for member names that are unsafe, match a deny pattern, or match no allow pattern."""
    problems: list[str] = []
    for name in names:
        if unsafe_name(name):
            problems.append(f"{name}: unsafe member name")
            continue
        reason = next((why for pattern, why in deny if re.search(pattern, name, re.IGNORECASE)), None)
        if reason is not None:
            problems.append(f"{name}: {reason}")
        elif not any(re.fullmatch(pattern, name) for pattern in allow):
            problems.append(f"{name}: not on the allowlist")
    return problems


def check_required(names: Sequence[str], required: Sequence[str]) -> list[str]:
    """A problem for each required member name that is not in ``names``."""
    present = set(names)
    return [f"{name}: required member is missing" for name in required if name not in present]


def parse_requirement(line: str) -> tuple[str, frozenset[str]] | None:
    """Return the normalised project name and specifier set, or None for extras-only or unparsable lines."""
    match = REQUIREMENT.match(line)
    if match is None:
        return None
    name, specifiers, marker = match.groups()
    if marker is not None and "extra" in marker:
        return None
    normalised = re.sub(r"[-_.]+", "-", name).lower()
    return normalised, frozenset(part.replace(" ", "") for part in specifiers.split(",") if part.strip())


def check_metadata(message: Message) -> list[str]:
    """Problems with Requires-Python and the rich and textual Requires-Dist specifiers."""
    problems: list[str] = []
    requires_python = str(message.get("Requires-Python", "")).replace(" ", "")
    if requires_python != REQUIRES_PYTHON:
        problems.append(f"Requires-Python is {requires_python!r}, expected {REQUIRES_PYTHON!r}")
    requirements: dict[str, list[frozenset[str]]] = {}
    for line in message.get_all("Requires-Dist") or []:
        parsed = parse_requirement(str(line))
        if parsed is not None:
            requirements.setdefault(parsed[0], []).append(parsed[1])
    for name, expected in REQUIRED_DEPENDENCIES.items():
        found = requirements.get(name)
        if found != [expected]:
            shown = [sorted(spec) for spec in found] if found else "missing"
            problems.append(f"Requires-Dist {name} is {shown}, expected {sorted(expected)}")
    return problems


def version_of(text: str | None) -> str | None:
    """The ``__version__`` assigned in the text of a ``_version.py``, or None."""
    match = VERSION_LINE.search(text or "")
    return match.group(1) if match else None


def repo_version() -> str | None:
    """The version in this repository's ``cli_interface/_version.py``, or None if unreadable."""
    try:
        return version_of(REPO_VERSION_FILE.read_text(encoding="utf-8"))
    except OSError:
        return None


def check_sdist(names: list[str], texts: dict[str, str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Return problems and the (source, version) pairs the sdist declares."""
    problems: list[str] = []
    versions: list[tuple[str, str]] = []
    pkg_infos = [name for name in names if re.fullmatch(r"[^/]+/PKG-INFO", name)]
    if len(pkg_infos) != 1:
        problems.append(f"expected exactly one <root>/PKG-INFO, found {len(pkg_infos)}")
        root = names[0].split("/")[0] if names else ""
    else:
        root = pkg_infos[0].split("/")[0]
    relative: list[str] = []
    for name in names:
        head, separator, rest = name.partition("/")
        if head != root or not separator:
            problems.append(f"{name}: outside the sdist root {root}/")
        else:
            relative.append(rest)
    problems += check_files(relative, SDIST_ALLOW, DENY)
    problems += check_required(
        relative,
        [f"{PACKAGE}/{module}.py" for module in PACKAGE_MODULES]
        + [f"{PACKAGE}/py.typed"]
        + [f"examples/{module}.py" for module in EXAMPLE_MODULES],
    )
    if len(pkg_infos) == 1:
        message = HeaderParser().parsestr(texts.get(pkg_infos[0], ""))
        problems += check_metadata(message)
        declared = str(message.get("Version", ""))
        if not declared:
            problems.append("PKG-INFO has no Version")
        else:
            versions.append(("PKG-INFO", declared))
            if root != f"{PACKAGE}-{declared}":
                problems.append(f"sdist root {root!r} does not match PKG-INFO version {declared!r}")
    shipped = version_of(texts.get(f"{root}/{PACKAGE}/_version.py"))
    if shipped is None:
        problems.append(f"{PACKAGE}/_version.py has no readable __version__")
    else:
        versions.append(("_version.py", shipped))
    return problems, versions


def check_wheel(names: list[str], texts: dict[str, str]) -> tuple[list[str], list[tuple[str, str]]]:
    """Return problems and the (source, version) pairs the wheel declares."""
    problems: list[str] = []
    versions: list[tuple[str, str]] = []
    metadata_files = [name for name in names if re.fullmatch(rf"{PACKAGE}-[^/]+\.dist-info/METADATA", name)]
    dist_info_allow: tuple[str, ...] = ()
    if len(metadata_files) != 1:
        problems.append(f"expected exactly one {PACKAGE}-<version>.dist-info/METADATA, found {len(metadata_files)}")
    else:
        dist_info = metadata_files[0].split("/")[0]
        dist_version = dist_info.removeprefix(f"{PACKAGE}-").removesuffix(".dist-info")
        dist_info_allow = (rf"{re.escape(dist_info)}/{WHEEL_DIST_INFO_FILES}",)
        message = HeaderParser().parsestr(texts.get(metadata_files[0], ""))
        problems += check_metadata(message)
        declared = str(message.get("Version", ""))
        if not declared:
            problems.append("METADATA has no Version")
        else:
            versions.append(("METADATA", declared))
            if declared != dist_version:
                problems.append(f"{dist_info} does not match METADATA version {declared!r}")
        problems += check_entry_points(texts.get(f"{dist_info}/entry_points.txt"))
        problems += check_required(names, [f"{dist_info}/entry_points.txt"])
    problems += check_files(names, WHEEL_ALLOW + dist_info_allow, DENY + WHEEL_DENY)
    problems += check_required(
        names,
        [f"{PACKAGE}/{module}.py" for module in PACKAGE_MODULES] + [f"{PACKAGE}/py.typed"],
    )
    shipped = version_of(texts.get(f"{PACKAGE}/_version.py"))
    if shipped is None:
        problems.append(f"{PACKAGE}/_version.py has no readable __version__")
    else:
        versions.append(("_version.py", shipped))
    return problems, versions


def check_entry_points(text: str | None) -> list[str]:
    """A problem unless ``entry_points.txt`` declares the expected ``console_scripts`` line (None: no check)."""
    if text is None:
        return []
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
        elif section == "console_scripts" and "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == SCRIPT_NAME and value.strip() == SCRIPT_TARGET:
                return []
    return [f"entry_points.txt: missing console script '{SCRIPT_NAME} = {SCRIPT_TARGET}'"]


def check_artifact(path: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Check one sdist or wheel: return its problems and the ``(source, version)`` pairs it declares."""
    try:
        names, texts, problems = read_archive(path)
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as error:
        return [f"cannot read archive: {error}"], []
    if problems and not names:
        return problems, []
    if path.lower().endswith(".whl"):
        found, versions = check_wheel(names, texts)
    else:
        found, versions = check_sdist(names, texts)
    return problems + found, versions


def expand(patterns: Sequence[str]) -> list[str]:
    """Expand wildcards that the shell left alone (Windows cmd and PowerShell do not glob)."""
    paths: list[str] = []
    for pattern in patterns:
        matches = sorted(glob.glob(pattern)) if any(char in pattern for char in "*?[") else []
        paths.extend(matches or [pattern])
    return paths


def main(argv: Sequence[str] | None = None) -> int:
    """Check every artifact named in ``argv``; return 0 if all pass, 1 otherwise (usage errors exit 2 via argparse)."""
    parser = argparse.ArgumentParser(description="Check built cli-interface archives against the shipping allowlist.")
    parser.add_argument("artifacts", nargs="+", metavar="ARTIFACT", help="path to a .tar.gz sdist or a .whl wheel")
    paths = expand(parser.parse_args(argv).artifacts)

    failures: list[str] = []
    versions: list[tuple[str, str]] = []
    for path in paths:
        problems, declared = check_artifact(path)
        failures += [f"{PurePath(path).name}: {problem}" for problem in problems]
        versions += [(f"{PurePath(path).name} {source}", value) for source, value in declared]
        print(f"{'FAIL' if problems else 'ok  '} {ascii_text(path)}")
    source_version = repo_version()
    if source_version is None:
        print(f"note: {ascii_text(str(REPO_VERSION_FILE))} has no readable __version__, skipping the source version comparison")
    else:
        versions.append(("repo _version.py", source_version))
    if len({value for _, value in versions}) > 1:
        failures.append("version mismatch: " + ", ".join(f"{source}={value}" for source, value in versions))

    for failure in failures:
        print(f"error: {ascii_text(failure)}", file=sys.stderr)
    if failures:
        print(f"{len(failures)} problem(s) found", file=sys.stderr)
        return 1
    print("all artifacts pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
