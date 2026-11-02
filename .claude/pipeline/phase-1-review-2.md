All fixes from round 1 check out, and nothing regressed.

APPROVED

## Verification of fix round 1

I read the real diffs and `cli.py`, then re-ran the checks. The suite shows the same plan §5 set and nothing new.

**WP-4, issue 1: label read before the action. Correct and complete.**
- `app.py:513`: `label = item_label(item)` runs once, outside the `try`, before `item.action(...)`. Both the `Executed:` line (:517) and the `Error in` line (:522) use it.
- Probe on Textual 8.2.8 (py3.13) and 0.80.0 (py3.11):
  - The toggle that read `Executed: Turn off` in review #1 now logs `Executed: Turn on`.
  - An action that clears the state its own label depends on logs `Executed: Item 1`, not `<error>`.
  - A failing action logs `Error in Fail True: kaput`.
  - The secret-prompt item's value callable was never called, and the typed value `hunter2` does not appear in the panel.
- The shipped demo's Worker Demo line becomes `Executed: Worker Demo`. I did not run the demo again in this round.

**WP-4, issue 7: hint line 2 shortened. Correct.**
- `theme.py:27-35`. Plain-text lengths are 72 and 73, measured with `Text.from_markup(_HINT_TEXT)`.
- Line 1 is unchanged and still contains "type a shortcut + Enter".
- Line 2 is now `  q + Enter  quit   PgUp / PgDn  scroll output   Home / End  top / bottom`, so "jump to" is dropped.
- At an 80-column terminal the `#hint` content width is 76, so it wraps to 2 rows and nothing is clipped. Same result on both Textual versions.
- Nothing in `tests/` mentions the dropped wording ("jump to", "top / bottom", "PgUp / PgDn", "Home / End").

**WP-4, issue 8: help rows. Correct.**
- `app.py:439-440`: the rows are now `clear + Enter` and `help  /  ? + Enter`.
- The `help` command renders them as expected.
- The table's first column was already wide enough, so layout is unchanged.

**WP-6, issues 2, 3, 4. Correct.**
- `cli.py:80-83`: only `ModuleNotFoundError` with `exc.name` equal to the target module, or one of its parent packages, becomes a `_TargetError` and exits 2. Anything else propagates with a traceback and exit 1.
- Exit codes I measured through `python -m cli_interface.cli`:

| Target | Exit |
|---|---|
| `no.such.mod:x` | 2 |
| `missing_top:x` | 2 |
| `pk2.nosuch:x` (package exists, submodule missing) | 2 |
| `pk2.inner:x` (module found, a dependency inside it is missing) | 1 |
| `broken_dep:x` (module found, a dependency inside it is missing) | 1 |
| `cannot_name:x` (`from tm import not_there`) | 1, traceback ending `ImportError: cannot import name ...` |
| `tm:missing` (attribute not found) | 2 |
| `tm:nomenu` (callable returns a non-`MenuItem`) | 2 |

- The epilog is now `example: cli-interface pkg.mod:build_menu`.
- The `--max-lines` help uses `_DEFAULT_MAX_LINES` and still reads `(default: 5000)`. The private-name import from `.app` is lint-clean.

**WP-1, issue 6: `_snap` save and restore. Correct.**
- `widgets.py:276-281`: `prev = self._snap` before the `try`, and the `finally` restores `prev`.
- Probe: a label callable that calls `nav.render()` during an outer render leaves the outer snapshot as the same non-`None` object. `_snap` is `None` once the outer render finishes.

**Mistake of mine:** I once ran `cli-interface tm:good`, which launched the TUI with no TTY and hung (the known F7 behaviour). I killed it, and `ps` shows no process left. No repo files changed.

## Commands run
- `ruff 0.17.3` on `cli_interface examples scripts`: all checks passed.
- `mypy 2.4.1` on the same paths: no issues in 16 files.
- `pytest -q -p no:cacheprovider --continue-on-collection-errors` (py3.13, textual 8.2.8): 357 passed, 2 failed, 4 errors.
  - The 2 failures are `test_regression::test_push_log_and_panel_surface_is_unchanged` and `test_late_timer_ticks_after_teardown_are_harmless` (XPASS strict).
  - The 4 errors are the collection errors in `test_demo.py` and `test_shortcuts.py`, plus the two `test_real_run.py` demo-fixture errors.
- Probe: label timing, hint width, help rows and nested render, on both Textual versions.
- Probe: CLI exit codes, as in the table above.
- `git status`: only the executors' changes, `tests/` untouched.

## Final summary for the Tester (step 4)

**Behaviours that changed in fix round 1 and must be pinned**
1. **`Executed:` and `Error in` label timing.**
   - The label is resolved once, before the action runs.
   - Example: a toggle with label `lambda: "Turn off" if on else "Turn on"` logs `Executed: Turn on`.
   - An action that clears the state its label reads still logs the pre-action text, not `<error>`.
   - A failing action logs `Error in <pre-action label>: <message>`.
   - The demo's Worker Demo line is `Executed: Worker Demo`, without `(running)`. Do not use WP-7's hand-off text that says `(running)`.
2. **Hint text.**
   - Line 1: `  ↑ ↓  navigate   Enter  select   Esc  back   ·  type a shortcut + Enter`, 72 characters.
   - Line 2: `  q + Enter  quit   PgUp / PgDn  scroll output   Home / End  top / bottom`, 73 characters.
   - The existing `test_shortcuts.py:327` `len(first) == 82` becomes 72.
   - Keep the `len(second) <= 85` budget. Both lines fit the 76-column content width of an 80-column terminal (`#hint` is 2 rows, nothing clipped).
   - The `q` entry is "q + Enter  quit" and sits at the start of line 2.
3. **Help table rows.**
   - Rows are `b / back + Enter`, `q / quit / exit + Enter`, `clear + Enter` and `help  /  ? + Enter`.
   - Existing tests only match the Action column for `clear` and `help`.
4. **CLI import exit codes.**
   - Exit 2 with a one-line `parser.error` only when the target module, or a parent package of it, is itself missing (`ModuleNotFoundError` whose `name` is the module or a prefix of it).
   - Any other `ImportError` or `ModuleNotFoundError` raised from inside a found module propagates with a traceback and exit 1.
   - Other exit-2 paths are unchanged: bad spec, missing attribute, non-callable, wrong return type, strict conflict, bad `--max-lines`.
   - The `--help` epilog is `pkg.mod:build_menu`, and the `--max-lines` help shows `(default: 5000)`.
5. **`NavBar` render re-entry.** A nested `render()` leaves the outer snapshot intact, and `_snap` is `None` afterwards. This is optional to test.

**Restated T1–T6 list**
- **T1 (major for CI):** `ruff check tests` reports 22 errors (E741 variable `l`, UP035, UP031). Fix them or the CI lint job (`ruff check cli_interface examples scripts tests`) stays red.
- **T2 (CF-3):** replace the message-regex `filterwarnings` line in `[tool.pytest.ini_options]` (`pyproject.toml:49-53`) with the category form:
  - `"error::cli_interface.ShortcutConflictWarning"`
  - `"error::cli_interface.LoggingAttachWarning"`
  - keep `"error::pytest.PytestUnhandledThreadExceptionWarning"`
  - Keep coverage of the `attach_logging` "were ignored because" warning.
- **T3 (CF-1):** remove the strict xfail on `test_regression.py::test_late_timer_ticks_after_teardown_are_harmless`. It now passes.
- **T4 (CF-12):** fix the demo coupling.
  - `conftest.py` (lines 118, 131, 143): `from examples import example_worker`.
  - `helpers.build_demo_app`: replace with `app = CLIApp(MenuItem("Home"), **kw); app.set_menu(examples.example_menu.build_menu(app)); return app`.
  - `test_demo.py`: update the `build_example_menu` import, `import main`, and `REPO / "main.py"` (now `examples/main.py`, function `main`).
  - `test_real_run.py`: the two demo tests depend on the fixed fixtures.
  - `test_regression.py:88-89`: update the pin on the `run` signature (`menu` required; `strict_shortcuts` and `max_lines` keyword-only; returns `int`).
- **T5:** `test_shortcuts.py` collection error.
  - Remove the `_BACK`/`_EXIT` import from `theme`.
  - Rewrite the sentinel checks to `isinstance(x, _NavCell)` with `.kind` (`"exit"` or `"back"`). This covers `is_sentinel` and the `.description == _EXIT/_BACK` assertions around lines 387, 401, 409, 412, 454 and 460, plus the `CELLS` parametrisation.
  - Update the hint test (item 2 above).
  - In my patched scratch run, 83 passed and 12 failed. All 12 were the hint pin and the description-based sentinel assertions.
- **T6:** new tests per plan §5 for P1.1 to P1.5 and the carry-forward IDs. Notes:
  - **CF-17:** compute the secret at runtime, because a literal in the source still appears in the traceback's code context.
  - **`check_dist.py`:** `main()` also compares against the repo `_version.py` (0.1.0). Use synthetic positives at 0.1.0, or call `check_artifact()` directly.
  - **`cli.main`:** it mutates `sys.path` and `sys.modules`, so restore them. Its error paths raise `SystemExit` (use `pytest.raises`).
  - **Warnings:** under the planned `error::...ShortcutConflictWarning` filter, a non-strict conflict in the CLI path raises inside `set_menu`. Use `pytest.warns` for that path.
  - **Do not launch the TUI** from a non-TTY test (F7).

**Docs and carry-forward, unchanged from review #1**
- `[DOCS]` items for step 6 are the same.
- Phase 2 and Integrator carry-forwards are the same.