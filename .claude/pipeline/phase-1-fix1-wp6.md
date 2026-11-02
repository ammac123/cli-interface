# WP-6 review fix round 1 (cli.py)

All three fixes (review issues 2, 3, 4) are applied in `/Users/andrewmacleod/workspace/cli_interface/cli_interface/cli.py`, the only file I touched. Ruff 0.17.3 and mypy 2.4.1 are clean on it, and all four requested acceptance checks pass. Nothing was committed, no `uv sync`, `tests/` untouched, and no TUI was launched (the `ps` check afterwards shows no leftover process).

## Fixes
- **Issue 2, `cli.py:80-83` (minor).** The import handler is now `except ModuleNotFoundError as exc`.
  - The failure becomes a `_TargetError`, and so exit 2, only when `exc.name` is set and `module_name == exc.name or module_name.startswith(exc.name + ".")`. That means the target module or one of its parent packages is itself missing.
  - Any other `ImportError` is no longer caught: a missing dependency inside the target module, a "cannot import name", or a circular import. Bare `raise` re-raises a `ModuleNotFoundError` that isn't the target's own, and a plain `ImportError` is never caught here. Both propagate with their traceback and exit 1.
- **Issue 3, `cli.py:34` (nit).** The `--help` epilog is now `example: cli-interface pkg.mod:build_menu`.
- **Issue 4, `cli.py:54` (nit).** `--max-lines` help is now an f-string using `_DEFAULT_MAX_LINES`, imported at `cli.py:12` as `from .app import _DEFAULT_MAX_LINES, CLIApp`. The help still reads `(default: 5000)`.

## Results
These ran as `python -m cli_interface.cli ... </dev/null` from the scratch dir `wp6/elsewhere`, which has no TUI-launching targets.

| Target | Exit | Output |
|---|---|---|
| `no.such.mod:x` | 2 | `cannot import module 'no.such.mod': No module named 'no'` |
| `t_menu_missing:x` (module missing) | 2 | `cannot import module 't_menu_missing': No module named 't_menu_missing'` |
| `pkg.sub:x` (`pkg` exists, `pkg.sub` doesn't) | 2 | `cannot import module 'pkg.sub': No module named 'pkg.sub'` |
| `nested.nosuch:x` (same case, second control) | 2 | `cannot import module 'nested.nosuch': No module named 'nested.nosuch'` |
| `broken_import:x` (module does `import definitely_not_installed_xyz`) | 1 | Full traceback, ending `ModuleNotFoundError: No module named 'definitely_not_installed_xyz'` |
| `nested.inner:x` (`import missing_dep_inner` inside a submodule) | 1 | Full traceback, ending `ModuleNotFoundError: No module named 'missing_dep_inner'` |
| `cannot_import_name:x` (`from t_menu import not_there`) | 1 | Full traceback, ending `ImportError: cannot import name 'not_there' from 't_menu' (...)` |
| `t_menu:nosuch` (unchanged attribute path) | 2 | `module 't_menu' has no attribute 'nosuch' (resolving 'nosuch')` |

- **`--help`.** It exits 0 and is ASCII-only (`grep -P '[^\x00-\x7F]'` count 0). It shows `--max-lines N ... (default: 5000)` and the epilog `example: cli-interface pkg.mod:build_menu`. `--version` exits 0 and prints `cli-interface 0.1.0`.
- **Regression.**
  - The in-process harness (`wp6/harness2.py`) still resolves all 10 happy-path targets with exit 0.
  - The `run_test()` end-to-end harness (`wp6/e2e.py`) still mounts a scratch target and `examples.example_menu:build_menu` from the repo root.
  - Both ran on the shared `.venv` (Python 3.13, textual 8.2.8). I did not rerun the Python 3.11 / textual 0.80.0 variant.

## Update for the Tester
Update the plan's description of the exit-2 import paths. Only a missing target module or parent package exits 2. An `ImportError` raised from inside a target module's own imports is now a traceback with exit 1. The sys.path, sys.modules and warnings notes in my earlier report are unchanged.

New scratch fixtures, all in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp6/elsewhere/`:
- `cannot_import_name.py`
- `nested/__init__.py`
- `nested/inner.py`
- `help.txt`
