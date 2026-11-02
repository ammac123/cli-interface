## Phase 0 documentation: final report

Docs are written and nothing in the code changed. Last full run: 467 passed, 1 xfailed, and `uv run python -c "import cli_interface.app, cli_interface.example_menu, main"` succeeds. No git commands that change state were run.

### 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/README.md`: was 0 bytes, now 208 lines. It covers what it is, install, quickstart, output, logging, prompts and secrets, shortcuts and reserved commands, known limitations, running the demo and tests, and a Pilot test example.
- `/Users/andrewmacleod/workspace/cli_interface/CHANGELOG.md`: new, 102 lines, Keep a Changelog style. Heading is `[Unreleased] - Phase 0`, with Changed (behaviour), Added, Removed and Fixed.
  - Changed includes the Back cell moving from `esc` to `b`.
  - Fixed lists F1, F2, F3, F4, F6, F8 and the `²` crash.
  - Added lists the dev-only test suite.
- `cli_interface/app.py`: module docstring, `CLIApp` class docstring, `__init__`, `panel`, `push_log`, `start_spinner`, `stop_spinner`, `on_input_submitted`, `attach_logging` and `run()`. Four comments.
- `cli_interface/log_handler.py`: docstrings for the module, `PanelInbox` (class, `__init__`, `open`, `close`, `put`, `dropped`), `TUILogHandler`, `LogAttachment` (class, `__init__`, `active`, `detach`, `share`) and `_Lease`.
- `cli_interface/display.py`: module docstring, class docstring (markup, UI thread only, `max_lines`, scroll modes) and every public method. Two helper comments.
- `cli_interface/menu.py`: module docstring, a full `MenuItem` docstring covering every field (including `secret` and `current_value`), a comment block for `RESERVED_COMMANDS`, `find_shortcut_conflicts`, `MenuState`, `breadcrumb` and `select_by_shortcut`.
- `cli_interface/widgets.py`: `PromptScreen` (class and `__init__`, including `secret=`), `Dashboard`, `NavBar` and the `_compute_item_width` limitation.
- `cli_interface/theme.py`: three comments (`_BACK`/`_EXIT` markers, `LEVEL_STYLES`, `_HINT_TEXT`).
- `cli_interface/example_menu.py`: the stale "Settings (uses logging)" comment is now accurate (only the `Executed:` line shows, because no handler is attached). Also a note on the module logger, the secret-prompt demo, and the literal-bracket sample.
- `main.py`: one comment saying `basicConfig` is deliberately absent.
- `.claude/skills/phase-pipeline/probes/api/probe4.py` and `pkg/smoke_test.py`: a comment-only "BASELINE REPRO" header (carry-forward 16). `.claude/` is gitignored, so this won't show in `git diff`.

Not touched: `tests/`, `pyproject.toml`, `uv.lock`, `.gitignore`.

### 2. Docstring coverage by module
- **app**: `CLIApp` (keys, typed-command precedence, sync actions, async not awaited, subclassing hazard), `strict_shortcuts` and `max_lines`, `push_log` (threading, buffering, bound, ordering caveat), spinner (not refcounted, Pilot hazard), `attach_logging`, `run()`.
  - `attach_logging` covers `level=`, `exclusive` restoring on `detach`, repeat-attach lease and warning, UI thread only, no auto-detach after exit, and root propagation for a named logger.
- **log_handler**: the full `PanelInbox` lifecycle and `put` semantics. `LogAttachment` includes the warning that direct construction bypasses the app's auto-detach.
- **display**: every public method, including `markup=` on `log` and `text`, `Text` pass-through, highlighting rules, UI thread only, `clear`, and `table` header semantics.
- **menu**: every `MenuItem` field, `RESERVED_COMMANDS`, `find_shortcut_conflicts` (including what it does not detect) and `MenuState`.
- **widgets**: `PromptScreen` with `secret=`, plus `Dashboard` and `NavBar`.

### 3. README snippets
I extracted all 6 fenced python blocks from `README.md` programmatically and ran them (`scratchpad/phase0/docs/readme_snippets.py`). The quickstart runs as `__main__`, with its `app.run()` replaced by a scripted `run_test`. All 14 checks passed:
- **Quickstart**: shortcuts, the prompt flow, no `'8080'` echo, and exit code 0.
- **Output snippet**: literal brackets, `markup=True`, `Text`, json and table.
- **Logging snippet**: `attach_logging` from a worker thread plus `push_log`, with handlers and level restored after `detach`.
- **Logging claims**: repeat attach gives a lease and warns, `exclusive` restore, `push_log` before start shown on start, and ignored after exit with a late attachment staying until detached.
- **Secret prompt**: masked input, no value echo.
- **Typed commands**: `esc` is an unknown command, `Q` quits, `b` at the root is a no-op, and position numbers work.
- **Conflicts snippet**: `find_shortcut_conflicts` returns 2, strict raises `ValueError`, and non-strict gives 2 `UserWarning`s plus panel WARNING lines.
- **Pilot snippet**: the example test for your own app.

A negative control (a changed assertion) made the harness fail, as it should. I also ran the real demo in a pty: `uv run python main.py` and `uv run cli-interface` both draw the menu and exit 0 on `q` Enter. `uv add /path/to/cli_interface` works from a scratch consumer project.

### 4. Tests, imports and unchanged behaviour
- `uv run pytest -q` gives 467 passed, 1 xfailed, run again after the last prose edits.
- The import command above succeeds.
- **AST check.** I saved the pre-docs files to scratch first. `astcheck.py` parses each file, strips docstrings (module, class and function), and compares `ast.dump` against the snapshot. All 11 `.py` files are equal.
  - Negative control: adding one real statement to a scratch copy is reported as DIFF.
  - Every deleted line in the diff is an old docstring line, or a line that only gained a trailing comment.
- No file in `tests/` or `pyproject.toml` changed. The only repo files modified after my snapshot are the `.py` files, `README.md`, `CHANGELOG.md` and the two probes. `.claude/pipeline/phase-0.md` was also newer, but I did not write it.
- `git diff --stat fdb8069` (the new untracked files are not in it, so I counted them separately):
  ```
   .gitignore                    |   4 +
   README.md                     | 207 +   (208 lines now, after the last edits)
   cli_interface/app.py          | 242
   cli_interface/display.py      | 199
   cli_interface/example_menu.py |  45
   cli_interface/log_handler.py  | 314
   cli_interface/menu.py         | 118
   cli_interface/theme.py        |   7
   cli_interface/widgets.py      | 142
   main.py                       |   4
   pyproject.toml                |  19
   uv.lock                       |  76
   12 files changed, 1196 insertions(+), 181 deletions(-)
  ```
  - `CHANGELOG.md` is untracked: 102 lines added.
  - The doc-only delta for this step is +397 lines and -38 lines across the 8 `.py` files.
  - `tests/` is untracked.

### 5. Things the docs can't honestly describe (reported, not fixed)
1. **Sentinel collision.** `_activate` checks `description == "__exit__"` or `"__back__"` first. I confirmed that a consumer item with `description="__exit__"` quits the app. `MenuItem`'s docstring says not to use those values.
2. **`MenuItem.description` is never displayed.** It only serves as the internal sentinel marker, and the docs say so.
3. **`push_log` on the UI thread can raise.** The direct write path propagates exceptions, which contradicts the plan's "never raises" contract. The `PanelInbox.put` docstring states what actually happens.
4. **Dropped-record notice.** It is issued once per drain, so sustained overflow can produce several notices. I worded the docs as "a WARNING says how many".
5. **Help and hint text left alone on purpose.** integration-2 §4 suggested editing them, but they are code and tests pin them. The `b`/`q`/Esc explanation lives in the README and docstrings only. Carry-forward 15 (the `q` row lacks "+ Enter") stays open.
6. **README roadmap link.** The one-line pointer to `.claude/skills/phase-pipeline/phases.md` won't resolve for anyone who clones the repo, because the `.gitignore` edit now excludes `.claude/`.
7. **Known limitations documented as limitations, not fixes.**
   - Shortcuts with surrounding whitespace never match, and the conflict check misses them.
   - Digit shortcuts shadow position numbers, also unreported.
   - `NavBar` counts a shortcut as 2 columns, so long shortcuts can overflow a row.
   - `max_lines` is unvalidated for `None` or `<= 0`.
   - A `|` in a label splits the breadcrumb.
   - `attach_logging` mutates `app._attachments` without a lock, so it is UI-thread only.
   - A subclass calling `super().on_mount()` runs the base handler twice and creates duplicate timers (verified: 2 timers versus 1).
   - Secret redaction covers exception text only.
   - `async` actions are not awaited (F5, Phase 2).
8. **Declared Python version.** `requires-python` is still `>=3.13` in `pyproject.toml`, although the suite passes on 3.11. The README says "3.13 or newer" as declared.