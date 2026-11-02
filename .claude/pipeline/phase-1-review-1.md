APPROVED

No blocker or major issue remains in the executors' files. Two minor defects (issues 1 and 2) are worth a quick fix round BEFORE step 4, because the Tester will pin their output text. Everything else is nit, deferred, or Tester/Docs-owned.

## 1. Issues

1. **[WP-4] minor, fix before step 4.** `cli_interface/app.py:516,521` (`_run_action`).
   - The label is resolved AFTER the action runs, so callable labels can describe the wrong item.
   - I reproduced it on a Pilot run. A toggle labelled `lambda: "Turn off" if st["on"] else "Turn on"` logs `Executed: Turn off` after the user chose "Turn on".
   - A label that depends on state the action destroys (`Item {items[0]}` with an action that clears `items`) logs `Executed: <error>`, and the same happens in the `Error in` line.
   - Fix: compute `label = item_label(item)` once, before `item.action(...)` and outside the `try`. `item_label` never raises `Exception`. Use `label` in both the `Executed:` and `Error in` lines.
   - Knock-on: the shipped demo's line becomes `Executed: Worker Demo`, not `... (running)`. WP-7 needs no code change, but the Tester must not pin the `(running)` text from the WP-7 hand-off.

2. **[WP-6] minor, fix before step 4.** `cli_interface/cli.py:80-81`.
   - Any `ImportError` becomes exit 2 with no traceback, including one raised inside the user's module.
   - A circular import, `cannot import name X`, or a missing dependency deep in the user's code loses its frames. Only the message survives.
   - Fix: convert to `_TargetError` only when `isinstance(exc, ModuleNotFoundError) and exc.name and (module_name == exc.name or module_name.startswith(exc.name + "."))`. Otherwise re-raise so the traceback propagates, like other import-time errors. The Tester will pin whichever behaviour ships.

3. **[WP-6] nit.** `cli_interface/cli.py:34`.
   - The `--help` epilog says `cli-interface examples.example_menu:build_menu`. That module is not in the wheel, which I confirmed in a clean venv: it exits 2 with `No module named 'examples'`.
   - Fix: use a generic `pkg.mod:build_menu`.

4. **[WP-6] nit.** `cli_interface/cli.py:54`. The help text hardcodes `(default: 5000)`. Import `_DEFAULT_MAX_LINES` from `.app`, or drop the number.

5. **[WP-1] minor, DEFER to Phase 2.** `cli_interface/menu.py:111,123`.
   - Each render of a raising callable logs a full-traceback DEBUG record. My probe with a raising label plus value and a root DEBUG attach gave about 21 records for 5 interactions, and it did not loop.
   - It conforms to D6. A first-failure-per-(item, field) dedupe would be better once Phase 2 reworks callable evaluation.

6. **[WP-1] nit.** `cli_interface/widgets.py:276-280`.
   - If `render()` is re-entered, the inner call's `finally` sets `_snap = None` and the outer pass silently loses its snapshot. It falls back to direct evaluation and does not crash.
   - If `render()` raises, the `finally` cleans up correctly.
   - Fix: `prev = self._snap` before the `try`, and `self._snap = prev` in the `finally`.

7. **[WP-4] nit.** `cli_interface/theme.py:27-35`.
   - Hint lines are 72 and 81 characters, within D16's 85-character budget.
   - At an 80-column terminal the content width is 76, so line 2 wraps and `#hint {height: 2}` clips the last word. At 85 columns or more it fits.
   - Baseline was no better: its 82-character line 1 also wrapped at 80 columns and clipped line 2 entirely.
   - Optional: trim line 2 to 76 characters or fewer. Otherwise carry it forward.

8. **[WP-4] nit.** `cli_interface/app.py:437-440`. The `clear` and `help / ?` help rows lack "+ Enter", unlike the `q` and `b` rows. This is outside CF-15 and optional.

**[TESTER] items for step 4**
- **T1 (major for CI):** `ruff check tests` reports 22 errors (E741 `l`, UP035, UP031). The CI `lint` job (`ruff check ... tests`) stays red until they are fixed.
- **T2 (CF-3):** `pyproject.toml:49-53` `filterwarnings` still uses the message-regex form. Switch it to the category form from plan §4.
- **T3 (CF-1):** remove the strict xfail on `test_late_timer_ticks_after_teardown_are_harmless`.
- **T4 (CF-12):** fix the demo-coupled tests.
  - `conftest.py`: `from examples import example_worker`.
  - `helpers.build_demo_app`: use WP-7's snippet.
  - `test_demo.py`: collection error.
  - `test_real_run.py`: two fixture errors.
  - `test_regression.py:88`: pins the old `run` signature.
- **T5:** `test_shortcuts.py` has a collection error (`_BACK`, `_EXIT` import).
  - I ran it in a patched scratch copy (import stubbed, plus the conftest and helpers swaps). 83 tests passed and 12 failed.
  - All 12 map to the expected categories: the hint pin `len(first) == 82` (now 72, with line 2 at 81, which is still within the 85 budget), and the description-based sentinel assertions (`is_sentinel` plus `.description == _EXIT/_BACK`, at lines 402 and 455 and the `CELLS` parametrisation).
  - Conflict message texts, the warning-filename test, the CF-6 width tests and direct `_render_item` calls all pass.
  - Rewrite the sentinel checks with `isinstance(x, _NavCell)` and `.kind`.
- **T6:** new tests per plan §5. Executor notes to carry in:
  - CF-17 must compute its secret at runtime. A literal in the source still shows in the traceback's code context.
  - `check_dist.py` main() also compares against the repo `_version.py` (0.1.0). Use synthetic positives at 0.1.0, or call `check_artifact()` directly.
  - `cli.main` mutates `sys.path` and `sys.modules`, and its error paths raise `SystemExit` (use `pytest.raises`).
  - Under the planned `error::...ShortcutConflictWarning` filter, a non-strict CLI conflict raises the warning inside `set_menu`. Use `pytest.warns`.

**[DOCS] items for step 6**
- README: line 14 "Python 3.13", line 185 `uv run python main.py`, no-argument `run()`, `CLIApp` parameters, the `|` breadcrumb caveat (now fixed), `_BACK`/`_EXIT` wording, the whitespace-shortcut caveat, the `max_lines` caveat.
- CHANGELOG: bare `cli-interface` now exits 2; `run(menu)` is required; the demos moved to `examples/`; `start_spinner`/`stop_spinner` are no-ops outside the running window; Python >= 3.11; new API.
- Docstrings: `LogAttachment` direct construction is discouraged, but not blocked. `item_value` does not mask secrets, so callers must. Add short docstrings for `reserved_action`, `normalize_shortcut`, `make_nav_cell` and `MenuState.set_root/home/prune`.

## 2. Rulings

- **A (hatch force-adds `.gitignore`): ACCEPT.** Plan D10 told the executor to allowlist any hatch extras. The file is inert, and its content (the user's uncommitted edit) is irrelevant to correctness. I confirmed hatch ships it in a scratch build.
- **B (`check_dist` compares against the repo `_version.py`): ACCEPT.**
  - It closes a real hole: a self-consistent lone 0.2.0 wheel would otherwise pass. It skips with a `note:` if the file is absent.
  - Running it against a stale dist after a version bump fails, which is the desired behaviour.
  - Note for the Tester: unit-test `check_artifact()` directly or keep synthetic positives at 0.1.0.
- **C (cached refs via `_bind_view`, lazy bind, spinner no-ops): ACCEPT.**
  - D17 explicitly allows "refs cached at mount", so this is not a deviation. `screen_stack[0]` is empty before mount and after exit.
  - The lazy bind handles Textual's subclass-`on_mount`-first ordering.
  - I verified the three methods with a `PromptScreen` open and via `call_from_thread`, and `start_spinner`/`stop_spinner`/`_tick_spinner`/`_cycle_*` after exit. All were safe.
  - A spinner tick with a prompt open used to raise `NoMatches`, so this is also a fix. The silent no-op is documented in the docstring.
- **D (stale submenu resync, strict `refresh_menu`, selection clamp, `set_menu` rollback): ACCEPT all four.**
  - Strict `refresh_menu` raising before prune and repaint matches the constructor and `set_menu` semantics.
  - `set_menu` rollback is correct. It restores state both on a strict `ValueError` and when a `ShortcutConflictWarning` is escalated to an error. I tested both.
  - Clamping matches D7 ("clamp the selection").
  - Observations only, no action: after a prune that shrinks the stack, `_display_selected` is clamped rather than reset, so the highlight can land on an arbitrary item of the shallower level. A stale leaf (not a submenu) still executes after an in-place edit without `refresh_menu`, which is baseline behaviour.
- **E (warnings via `run(menu)` point at app.py): ACCEPT.** Python 3.11 has no `skip_file_prefixes`. Distinct texts still print once each. DEFER to Phase 2: use `skip_file_prefixes` on 3.12+ with a stacklevel fallback.
- **F (hint and help rows): ACCEPT.** D16 is met (72 and 81 characters, within the 85 budget; line 1 still contains "type a shortcut + Enter"). It is no worse at 80 columns than baseline, and better (see issue 7). `clear` and `help` lacking "+ Enter" is outside CF-15. The 80-column layout is a carry-forward.
- **G (`Executed:` label resolved after the action): DEFECT [WP-4], minor.** See issue 1 for the failure case and the fix.
- **H (`cli.py`):**
  - ImportError inside the target module: DEFECT [WP-6], minor (issue 2).
  - `CLIApp` built before the target is parsed: ACCEPT. It is D2's specified order, and `build_menu(app)` needs the app.
  - Hardcoded `(default: 5000)`: ACCEPT as a nit (issue 4).
  - `SystemExit` escaping `main()`: ACCEPT. It is argparse convention, and D2 says to use `parser.error`.
- **I (NavBar shows the stripped but not lowercased shortcut; `item_value` does not mask): ACCEPT.**
  - Stripping only matches WP-1's explicit work item. Lowercasing would visibly regress uppercase shortcuts, though D8's wording is looser.
  - `_value_text` guards secrets before calling anything, and `item_value` is internal (not in `__all__`). I traced every call path: a secret item's value callable is never invoked, and its repr is masked.
- **J (WP-7):**
  - The `Debug mode toggled on|off` message is a necessary consequence of the callable-value dogfood. ACCEPT.
  - The worker-flag ordering changes are correct and fix real races (the flag was set before an attach that can raise, and a late `clear()` could erase a newer run's guard). ACCEPT.
  - Two-step commit for `main.py`: not worth it. The file was 7 lines. A pure-`git mv` first commit would hold a `main.py` that calls `run()` with no menu, which now raises `TypeError`, and that would break `git bisect`. Commit once.

## 3. Scope ID coverage

| ID | Where | Verdict |
|---|---|---|
| P1.1 | `cli_interface/__init__.py:11-22` (11-name `__all__`); `_version.py:1`; empty `py.typed`; `pyproject.toml:27` (hatch version); `Typing :: Typed` classifier | done |
| P1.2a | `menu.py:105,115,128-139`; `widgets.py:147,185,195,228`; `app.py:495,501,516,521,471` | done |
| P1.2b | `app.py:275,299,314,321`, `_bind_view` 341 | done |
| P1.3 | `pyproject.toml:6-9`; `uv.lock` (`uv lock --check` passes in my scratch copy) | done |
| P1.4a | `pyproject.toml:30-35`; `scripts/check_dist.py` | done |
| P1.4b | `examples/*` (git mv); `cli_interface/example_*.py` and `main.py` removed | done |
| P1.4c | `cli.py:96`; `pyproject.toml:20-21` | done |
| P1.5 | `pyproject.toml:55-66`; `.github/workflows/ci.yml`; `scripts/check_dist.py` | done (CI YAML is read-only verified; Windows and macOS legs are unverifiable here) |
| CF-1 | `app.py:198-200,376-402,447-458,486-491` | done in code; xfail removal is T3 |
| CF-2 | `app.py:600-612`; `menu.py:85-102` | done |
| CF-3 | `warning_types.py`; `app.py:330,695`; facade | categories done; pyproject filter is T2 |
| CF-4 | `app.py:321` | done |
| CF-5 | `menu.py:101,164,278-284`; `widgets.py:198,230` | done |
| CF-6 | `widgets.py:195-202` | done |
| CF-7 | `menu.py:128-139`; `app.py:463,526-531` | done |
| CF-8 | `app.py:704-717` | done |
| CF-9 | `__init__.py` | done |
| CF-10 | `app.py:177-180` | done |
| CF-11 | `examples/example_menu.py:14-15,169-170`, per-action `with capture_settings()` | done |
| CF-12 | tests | Tester (T4/T5) |
| CF-13 | `widgets.py:69-70` | done |
| CF-14 | `widgets.py:114-127`; `app.py:471-473` | done |
| CF-15 | `app.py:435-436`; `theme.py:27-35` | done |
| CF-16 | ruff clean and mypy clean on `cli_interface`, `examples`, `scripts` | done for owned files; `tests/` is T1 |
| CF-17 | `app.py:629-639` | done; my fatal-error probe showed no secret leak on Textual 8.2.8 and 0.80.0, and Textual's default leaked in the negative control |

## 4. Carry-forward

- **Phase 2:**
  - `skip_file_prefixes` for warning attribution.
  - Thread-safe proxies for `set_menu`, `refresh_menu` and `go_home` (D7).
  - Dedupe for callable-failure DEBUG logs.
  - 80-column hint layout.
  - `prune` selection reset.
  - F7, the no-TTY run path (already open).
  - The `_fatal_error` override is a private Textual hook. If Textual renames it, the secret protection silently stops, so keep its regression test.
- **Integrator (step 5):**
  - The shared `.venv/bin/cli-interface` shim still targets `app:run` until `uv sync`. The literal `uv run --no-sync cli-interface` fails until then. CI is unaffected.
  - The 3.14 + textual 0.80 lowest-direct claim (467 passed) came from a mid-W1 snapshot. Re-run the full suite there with the final code.
  - The Windows and macOS CI legs are unverifiable locally.
  - `git add` the untracked files: `.github`, `scripts`, `cli.py`, `_version.py`, `py.typed`, `warning_types.py`, `examples/__init__.py`.
  - Action tags `checkout@v6` and `setup-uv@v7` were checked by WP-3 via `git ls-remote`, not by me.

## 5. What I ran

- `git diff -M 4cab69a`: read in full, plus every new file and the executor reports.
- Lint and types: `uvx --offline ruff@0.17.3 check --no-cache cli_interface examples scripts` passes. The same on `tests` reports 22 errors. `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null cli_interface examples scripts` reports no issues in 16 files.
- Full suite in the repo `.venv` (py3.13, textual 8.2.8): 357 passed, 2 failed, 4 errors. That is exactly the plan §5 list. Same result on py3.11 with textual 0.80.0 (WP-4's scratch venv).
- Masked tests: in a scratch copy `$R/src` (`$R` = `<scratchpad>/review`), I patched the `_BACK`/`_EXIT` import, the conftest import and `build_demo_app`, then ran `test_shortcuts.py` plus `test_real_run.py`. Result: 83 passed, 12 failed, all mapped as in T5. `cli_interface.__file__` resolved to the scratch copy.
- Packaging, in the scratch copy:
  - `uv build --offline --out-dir $R/dist` built the sdist and wheel.
  - `check_dist.py` printed "all artifacts pass".
  - Negative controls all exit 1: `tests/x.py`, `uv.lock` and `.env` in the sdist; in the wheel, a dropped `py.typed`, a demo module in the package, `examples/` shipped, a wrong script line, and a version mismatch.
  - `uv lock --check --offline` passes.
- Clean-venv wheel install (py3.11): `--version` gives `cli-interface 0.1.0`; `--help` is ASCII. A bare call, `nocolon`, a missing module and `--max-lines 0` all exit 2. `py.typed` is present, `examples` is not importable, and `__version__` equals the installed metadata version.
- In-process `cli.main`, with a scratch target module and `CLIApp.run` patched:
  - A `MenuItem`, a callable taking the app, and a dotted attr all resolve.
  - A strict conflict exits 2.
  - A wrong return type, a non-callable target and a missing attr exit 2.
  - A `build_menu` that raises propagates its traceback.
  - `--max-lines` is forwarded.
- Pilot probes on Textual 8.2.8:
  - `set_menu`, `refresh_menu`, `go_home`, `start_spinner` and `stop_spinner` before mount, with a `PromptScreen` open via `call_from_thread` from a worker thread, and after exit.
  - Prune after removing a level.
  - Secret callable never called (nav shows `••••`).
  - `<error>` fallback.
  - Warning filename is the caller, dedupe works, and strict and warning-as-error rollback both hold.
  - Fatal-traceback secret check on both Textual versions, with a negative control.
  - Raising-callable DEBUG probe.
  - Example menu run end to end: Volume logs once, no handler leak, and the Worker Demo label toggles.
  - Reproduction of issue 1.
  - Hint wrap measured at widths 80, 85 and 90.
- Repo state: `git status --porcelain` shows only the executors' changes. All my scratch files are under `<scratchpad>/review`. Ignored `__pycache__` directories pre-existed.