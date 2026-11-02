"""
Console script: ``cli-interface module:attr`` shows a menu in the terminal UI.

``attr`` (dotted names allowed) is a ``MenuItem`` or a callable that returns one. A
callable with a required positional parameter is called with the ``CLIApp`` that will
show the menu, so its actions can use ``app.panel``; any other callable is called with no
arguments. See ``main`` for the flags and exit codes.
"""

import argparse
import importlib
import inspect
import os
import sys
from collections.abc import Sequence
from typing import Any

from ._version import __version__
from .app import _DEFAULT_MAX_LINES, CLIApp
from .menu import MenuItem


class _TargetError(Exception):
    """The target cannot be resolved to a menu; ``main`` reports it as a usage error (exit 2)."""


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, not {text!r}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli-interface",
        description="Run a cli_interface menu as a terminal UI.",
        epilog="example: cli-interface pkg.mod:build_menu",
    )
    parser.add_argument(
        "target",
        help=(
            "the menu to run, as module:attr (attr may be dotted). attr is a MenuItem or a "
            "callable returning one. A callable with a required positional parameter is "
            "called with the CLIApp, any other callable with no arguments. The current "
            "directory is searched for modules first."
        ),
    )
    parser.add_argument(
        "--strict-shortcuts",
        action="store_true",
        help="exit with an error, instead of warning, when a shortcut is reserved or duplicated on one level",
    )
    parser.add_argument(
        "--max-lines",
        type=_positive_int,
        metavar="N",
        help=f"scrollback of the output panel in lines, a positive integer (default: {_DEFAULT_MAX_LINES})",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _is_dotted_name(text: str) -> bool:
    return all(part.isidentifier() for part in text.split("."))


def _takes_app(func: Any) -> bool:
    """True if ``func`` has a required positional parameter (it is then called with the app)."""
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return any(p.kind in positional and p.default is inspect.Parameter.empty for p in parameters)


def _load_menu(target: str, app: CLIApp) -> MenuItem:
    """
    Import the module of ``target`` (``module:attr``), walk ``attr`` and return the menu.

    Raises ``_TargetError`` for a bad spec, a missing attribute, a target that is not a
    ``MenuItem`` or a callable, or a result that is not a ``MenuItem``, and for a
    ``ModuleNotFoundError`` naming the target module or one of its parent packages. Any
    other exception, an ``ImportError`` raised inside the module included, propagates
    with its traceback.
    """
    module_name, colon, attr_path = target.partition(":")
    if not (colon and _is_dotted_name(module_name) and _is_dotted_name(attr_path)):
        raise _TargetError(f"target must look like module:attr, not {target!r}")
    importlib.invalidate_caches()
    try:
        obj: Any = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (module_name == exc.name or module_name.startswith(exc.name + ".")):
            raise _TargetError(f"cannot import module {module_name!r}: {exc}") from exc
        raise
    for name in attr_path.split("."):
        try:
            obj = getattr(obj, name)
        except AttributeError as exc:
            raise _TargetError(f"module {module_name!r} has no attribute {name!r} (resolving {attr_path!r})") from exc
    if not isinstance(obj, MenuItem):
        if not callable(obj):
            raise _TargetError(f"{target!r} is neither a MenuItem nor a callable (got {type(obj).__name__})")
        obj = obj(app) if _takes_app(obj) else obj()
        if not isinstance(obj, MenuItem):
            raise _TargetError(f"{target!r} returned {type(obj).__name__}, not a MenuItem")
    return obj


def main(argv: Sequence[str] | None = None) -> int:
    """
    Entry point of the ``cli-interface`` console script: parse ``argv`` (default
    ``sys.argv[1:]``), load the menu named by ``TARGET`` and run it in the terminal UI.

    Flags: ``--strict-shortcuts`` (a reserved or duplicate shortcut is an error, not a
    warning), ``--max-lines N`` (scrollback, a positive integer), ``--version``, ``-h``.
    The current directory is put first on ``sys.path`` so a module next to you is found.

    Returns 0, or the exit code the app set. A usage problem (no target, bad spec,
    module or attribute not found, wrong type, bad ``--max-lines``, a strict-mode
    shortcut conflict) is reported by argparse as ``SystemExit(2)``; ``--help`` and
    ``--version`` print and raise ``SystemExit(0)``. An exception raised by the user's own
    code, including a ``build_menu`` that raises, propagates with its traceback (Python
    then exits 1). Running the menu needs a real terminal; ``--help``, ``--version`` and
    the error paths do not.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    options: dict[str, Any] = {"strict_shortcuts": args.strict_shortcuts}
    if args.max_lines is not None:
        options["max_lines"] = args.max_lines
    app = CLIApp(MenuItem("cli-interface"), **options)
    cwd = os.getcwd()
    if not sys.path or sys.path[0] != cwd:
        sys.path.insert(0, cwd)
    try:
        menu = _load_menu(args.target, app)
    except _TargetError as exc:
        parser.error(str(exc))
    try:
        app.set_menu(menu)
    except ValueError as exc:
        parser.error(f"shortcut conflicts (--strict-shortcuts):\n{exc}")
    app.run()
    return app.return_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
