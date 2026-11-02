WP-2 is done. The four owned files are ruff-clean and mypy-clean, and the existing suite shows no new failures. No deviations from the plan and no cross-package requests.

**1. Files changed**
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/warning_types.py` (new): `class ShortcutConflictWarning(UserWarning)` and `class LoggingAttachWarning(UserWarning)`, each with a one-line docstring, plus a module docstring. Names match the WP-4 contract exactly.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py`: removed the 5 quoted annotations. It already has `from __future__ import annotations`, so behaviour is unchanged.
  - `app: "CLIApp"` became `app: CLIApp` at lines 43, 181 and 226.
  - `-> "LogAttachment"` became `-> LogAttachment` at lines 294 and 304.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py`: line 225 is now `zip(headers, row, strict=False)`. Strict stays off so ragged CSV rows don't crash.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/phrases.py`: not modified. It was already clean and has no `typing` or `zip` hits.

**2. Scope IDs**
- CF-3 (the categories): `warning_types.py`. WP-4 emits them and the Tester switches `filterwarnings`.
- CF-16 (style) for these files: the 5 UP037 hits in `log_handler.py` and the 1 B905 hit in `display.py`. `phrases.py` and `warning_types.py` were clean.

**3. Deviations:** none.

**4. Cross-package requests:** none. For WP-5 and the Tester: the pytest filter `error::cli_interface.ShortcutConflictWarning` needs both classes re-exported from `cli_interface/__init__.py`, which is WP-5's job. The classes' own `__module__` is `cli_interface.warning_types`.

**5. Acceptance results**
- ruff 0.17.3 (the plan's command, with the 4 owned files listed explicitly): `All checks passed!`. Baseline was 6 errors in these files.
- mypy 2.4.1 with `--python-version 3.11 --check-untyped-defs` on the 4 files: `Success: no issues found in 4 source files`.
- `uv run --no-sync python -c "import cli_interface.warning_types, cli_interface.log_handler, cli_interface.display, cli_interface.phrases"` succeeds.
- `git diff` on `display.py` and `log_handler.py` shows 6 changed lines in total, all the ones listed above.
- Scratch check at `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp2/check.py` passed:
  - Both classes subclass `UserWarning`.
  - Both can be raised and recorded by the `warnings` module.
  - `DisplayPanel.csv` contains `strict=False`.
- Existing suite, `uv run --no-sync pytest -q -p no:cacheprovider`: 467 passed, 1 xfailed, 0 failures. This is the same as the pre-change expectation. The tree already had WP-3 files present (`pyproject.toml`, `uv.lock`, `_version.py`, `py.typed`) and no `menu.py` or `widgets.py` modifications at run time.

**6. Not verified**
- I did not run `zip(..., strict=False)` on a ragged CSV through a live panel. It is identical to the old behaviour by definition, and the existing CSV tests passed.
- `filterwarnings` by category was not exercised, because the facade (WP-5) and the pytest config (Tester) don't exist yet.