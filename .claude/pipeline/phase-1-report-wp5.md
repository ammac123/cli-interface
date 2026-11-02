WP-5 is done: `cli_interface/__init__.py` is written, ruff-clean and mypy-clean, and every acceptance item passes. I did not commit, and I touched no other file.

**Files changed**
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/__init__.py` (was empty, now 23 lines). Scope IDs: P1.1a, CF-9, CF-16 (ruff/mypy style for this file).

**What it contains**
- A one-line module docstring: `"""cli_interface: a menu-driven terminal UI with a live output panel."""`
- The imports, one source module each:
  - `from ._version import __version__`
  - `from .app import CLIApp, attach_logging, run`
  - `from .display import DisplayPanel`
  - `from .log_handler import LogAttachment`
  - `from .menu import RESERVED_COMMANDS, MenuItem, find_shortcut_conflicts`
  - `from .warning_types import LoggingAttachWarning, ShortcutConflictWarning`
- `__all__` has exactly the 11 D4 names, in D4's order: `CLIApp`, `DisplayPanel`, `LogAttachment`, `LoggingAttachWarning`, `MenuItem`, `RESERVED_COMMANDS`, `ShortcutConflictWarning`, `__version__`, `attach_logging`, `find_shortcut_conflicts`, `run`.

**Deviations:** none.
- D4 says direct construction of `LogAttachment` is "discouraged in the docstring only". The brief said a one-line module docstring and no other docs, so I wrote no such note. It belongs in the step-6 docs, or in the `LogAttachment` class docstring, which is WP-2's file.

**Cross-package requests:** none. The pytest filters `error::cli_interface.ShortcutConflictWarning` and `error::cli_interface.LoggingAttachWarning` now resolve through this re-export.

**Acceptance results**
- Ruff: `uvx --offline ruff@0.17.3 check --no-cache --target-version py311 --select E4,E7,E9,F,UP,B cli_interface/__init__.py` printed "All checks passed!".
- Mypy: `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null --python-version 3.11 --check-untyped-defs --warn-unused-ignores --warn-redundant-casts --strict-equality cli_interface/__init__.py` printed "Success: no issues found in 1 source file". It followed the imports into `app.py` and reported nothing there either, at the moment I ran it.
- Scratch script `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp5/accept.py` run with `uv run --no-sync python` printed "ALL OK". It checks:
  - `sorted(__all__)` equals the D4 list, with 11 unique names.
  - Every name resolves with `getattr`, and `__version__ == "0.1.0"`.
  - `from cli_interface import *` in a fresh namespace yields exactly those 11 names. `PanelInbox`, `TUILogHandler`, `MenuState`, `PromptScreen`, `Dashboard`, `NavBar` and `theme` are absent from both the star-import and `__all__`.
  - Both warning classes subclass `UserWarning`.
  - Resolving `cli_interface.ShortcutConflictWarning` and `cli_interface.LoggingAttachWarning` by import plus `getattr`, as pytest does, works. `warnings.filterwarnings("error", category=...)` then turns a warning of that category into an exception.
- Logging untouched:
  - In a fresh interpreter, `logging.root.handlers` (`[]`) and `logging.root.level` (30, WARNING) are identical before and after the import.
  - The handlers, level and propagate flag of every pre-existing logger are unchanged.
  - The import creates only `cli_interface.menu`, plus `asyncio` and `concurrent.futures` from Textual. None has a handler.
- Warnings: `python -W error -c "import warnings; warnings.simplefilter('error'); import cli_interface"` exits 0 with no output.
- Import footprint: the import loads `textual.app` and `textual.screen`. That is unavoidable, because `CLIApp` is an `App` subclass and has to be re-exported.

**Unverified**
- `__version__` against `importlib.metadata.version("cli-interface")`. That depends on the installed dist-info, which I did not touch (`uv sync` is out of bounds). The Tester or Integrator should check it.
- Whether `import cli_interface` still works once WP-4 finishes. WP-4 may have been mid-edit on `app.py`, but all my checks passed when I ran them.