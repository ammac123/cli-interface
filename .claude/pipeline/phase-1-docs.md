# Documenter (step 6) report, Phase 1

Docs now match the code. Only docstrings and comments changed in the code files; the AST check below shows this. pytest: 885 passed. ruff and mypy are clean. The README snippets all ran headless.

## 1. Files changed

**Docs**
- `/Users/andrewmacleod/workspace/cli_interface/README.md`: rewritten, about 440 lines.
  - Python 3.11+, install, and the 11-name facade as a table.
  - `CLIApp` and `run` signatures, with the `max_lines` rules.
  - A "Changing the menu" section: callable labels and values (D6), `set_menu`/`refresh_menu`/`go_home` (D7), shortcut normalisation, the two warning categories and how to filter them.
  - A console-script section: target contract, flags, exit codes, cwd on `sys.path`.
  - Examples, honest known limitations, and development/CI.
  - All the stale claims are gone.
- `/Users/andrewmacleod/workspace/cli_interface/CHANGELOG.md`: new `## [Unreleased] - Phase 1 (public API and packaging)` section above Phase 0.
  - Groups: Changed (behaviour), Added, Removed, Fixed, Notes.
  - The intro line now names both baselines.

**Docstrings and comments only**
- `cli_interface/__init__.py`, `warning_types.py`, `menu.py`, `app.py`, `widgets.py`, `log_handler.py`, `display.py`, `theme.py`, `cli.py`.
- `examples/main.py`, `example_menu.py`, `example_worker.py`.
- `scripts/check_dist.py`.
- Specifics:
  - `menu.py`: `reserved_action`, `normalize_shortcut`, `make_nav_cell`, `item_label`, `item_value` (states it does not mask secrets and callers must), `MenuState.set_root`/`home`/`prune` and the properties. The `find_shortcut_conflicts` docstring now says it also runs on `set_menu`/`refresh_menu`.
  - `app.py`: the `CLIApp` class docstring, `set_menu`/`refresh_menu`/`go_home`, `run`. A `set_menu` rollback comment and a `_fatal_error` comment were also added.
  - `widgets.py`: `_snap` comment.
  - `log_handler.py`: `LogAttachment` ("create only via `attach_logging`; discouraged, not blocked").
  - `check_dist.py`: module docstring (usage, exit codes 0/1/2, what it enforces) plus a one-line docstring on every function.

**Files I deliberately did not touch**
- `cli_interface/_version.py`: hatch and `check_dist` parse that single line, and tests pin it.
- `cli_interface/phrases.py`: not touched in this phase.
- `examples/__init__.py`: see section 4.

**Git status**
- It shows the two new ` M` lines (README, CHANGELOG).
- `examples/example_worker.py` went from `R ` to `RM`, from its new module docstring.
- No new untracked files in the repo.
- `.pytest_cache` (Oct 31) and the root `__pycache__` (Nov 1) were already there. No `dist/`, `.ruff_cache` or `.mypy_cache`.

## 2. Docstring coverage and carry-forward A

Counts come from `doc_coverage.py`. It scans public names via the AST and excludes Textual hooks. Before 71/101, after 97/101.

| Module | Before | After |
|---|---|---|
| `__init__` | 1/1 | 1/1 |
| `app` | 12/12 | 12/12 |
| `cli` | 1/2 | 2/2 |
| `display` | 14/14 | 14/14 |
| `log_handler` | 14/15 | 15/15 |
| `menu` | 12/22 | 21/21 (the script lists `selected_index` twice, getter and setter) |
| `theme` | 0/1 | 1/1 |
| `warning_types` | 3/3 | 3/3 |
| `widgets` | 5/5 | 5/5 |
| `examples/example_menu`, `example_worker`, `main` | 3/6 | 6/6 |
| `scripts/check_dist` | 6/16 | 16/16 |

- Gaps left by design: `_version.py` and `phrases.py` (module docstring and `get_phrase`). `examples/__init__.py` stays empty (below).
- `__all__` coverage: every public method of `CLIApp`, `DisplayPanel`, `MenuItem` and `LogAttachment` is documented, plus `run`, `attach_logging`, `find_shortcut_conflicts` and the two warning classes.

**Carry-forward A, item by item: all done.**
- README:
  - Python 3.13 reference replaced by 3.11+.
  - "No facade yet" removed, and imports use the facade.
  - `uv run python main.py` and the "uv run cli-interface" demo launcher replaced by `python -m examples.main` and `cli-interface examples.example_menu:build_menu`.
  - No-arg `run()` replaced by the `run(menu)` rules.
  - `CLIApp` parameters and `max_lines` rules documented.
  - Whitespace-shortcut, `|`-crumb, 2-column-width and `_BACK`/`_EXIT` caveats removed.
  - The Pilot `app.exit()` caveat and the subclass `super().on_mount()` limitation are gone (see section 5).
- CHANGELOG: bare `cli-interface` exits 2, `run(menu)` required, demos moved, spinner no-ops, Python >= 3.11 and the new API are all covered.
- Docstrings: `LogAttachment`, `item_value`, `reserved_action`, `normalize_shortcut`, `make_nav_cell`, `MenuState.set_root/home/prune` and the `find_shortcut_conflicts` fix are all done.

**Scope-ID to CHANGELOG bullet**
- P1.1: Added "A public facade".
- P1.2: Added `set_menu`/`refresh_menu`/`go_home`, and Changed "Menu labels and values".
- P1.3: Changed "`requires-python` is now `>=3.11`" and the Tooling bullet (lock).
- P1.4: Added Packaging, Added console script, and Changed "demos moved to `examples/`".
- P1.5: Added Tooling, CI and `check_dist`.
- CF-1: Fixed "Timers after shutdown", and Removed (the xfail).
- CF-2: Fixed "Reserved words in one place".
- CF-3: Changed (warning classes), Added (warning classes), Dev only (`filterwarnings` by category).
- CF-4: Changed "Shortcut conflicts are checked on `set_menu` and `refresh_menu`".
- CF-5: Changed "Shortcuts are compared with surrounding whitespace stripped".
- CF-6: Fixed "Nav-bar width".
- CF-7: Changed "`theme._BACK`/`_EXIT` removed".
- CF-8: Changed "`run()` requires a menu".
- CF-9: Added facade.
- CF-10: Changed "`max_lines` is validated".
- CF-11: Changed "Demo".
- CF-12: Added "Dev only" bullet.
- CF-13: Fixed "prompt hint".
- CF-14: Fixed "label containing `|`", and Added `Dashboard.crumbs`.
- CF-15: Fixed "+ Enter", and Changed (hint text).
- CF-16: Added Tooling.
- CF-17: Fixed "crash traceback".

The CHANGELOG also covers the callable-label timing, the `ImportError` exit-code rule, the warning-attribution limit and the packaging/version decisions, under Notes.

## 3. README snippets run

The harness is `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/docs/readme_harness.py`.

**How it works**
- It extracts every fenced block from `README.md` itself and `exec`s the python blocks in order, in one namespace, with `__name__="readme"`.
- `CLIApp.run` is replaced by a function that raises, so the TUI can never start.
- It then drives the objects the snippets defined with `run_test()`.
- Results: 56 ok and 0 FAIL on Python 3.13 / Textual 8.2.8 / Rich 15.0.0, and 56 ok and 0 FAIL on Python 3.11 / Textual 0.80.0 / Rich 13.3.3.
- Outputs are in `harness_out_313.txt` and `harness_out_311.txt` in the same directory.

**Python blocks (12)**

| Block | What was checked |
|---|---|
| Facade import | executes |
| Quickstart | `h` runs `hello` and shows `Executed: Say hello → done`; Settings > Set port runs with a prompt |
| `run(simple, max_lines=20_000)` | returns 0 and forwards the option; `Executed: Greet → hello`; `run()` raises `TypeError` |
| `build_menu(app)` + `set_menu` | the action logs through `app.panel` |
| Output (`report`) | literal markup, `Text`, JSON and table all render |
| Logging (`start_job`) | steps 0 to 2 and "job finished" appear; no handler is left on `myjob` |
| Token | the value is never shown |
| Shortcut conflicts | prints 2 and `refused: ...` |
| Warning filters | `ShortcutConflictWarning` raised under `simplefilter("error")` |
| Dynamic menu | see below |
| `menus.py` file | written to a scratch dir and driven through `cli.main` |
| Pilot test | `asyncio.run(check())` ran its own assertion |

- Dynamic menu: callable label and value render; the nav bar repaints after an action; `Executed:` shows the pre-action label; `add_item` plus `refresh_menu` works; `call_from_thread(app.refresh_menu)` from a real worker thread works; `set_menu` and `go_home` work while running; all three are legal before mount.
- I also checked `CLIApp(max_lines=0/-1/True/"5"/1.5)` raises `ValueError`, `None` is accepted, and a non-`MenuItem` raises `TypeError`.
- The toml block parses, and pytest's `parse_warning_filter` resolves it to `ShortcutConflictWarning`.
- Leaving `run_test` with a spinner running raises nothing.

**Bash lines**
- Run for real, with no TTY via `uv run --no-sync` and `</dev/null`: `cli-interface --version` (prints `cli-interface 0.1.0`), `--help` (ASCII), and a bare invocation (exit 2).
- Run in-process through `cli.main`, with `CLIApp.run` patched to a Pilot driver:
  - `menus:build_menu` from a scratch dir.
  - `mypkg.menus:build_menu`, plain and with `--strict-shortcuts --max-lines 20000`; flags reach the app.
  - `examples.example_menu:build_menu` from the repo root.
  - `python -m examples.main`, via `main()`.
  - A module that is not in the cwd exits 2.
- Separate probes:
  - A non-strict conflict warns with the file attributed to `cli.py`.
  - `--strict-shortcuts` exits 2 and prints the problem list.
  - A raising `build_menu` propagates its `RuntimeError`.
  - `python examples/main.py` fails with an `ImportError`.
- Not run, because they would change environments or repeat other checks:
  - `uv sync`, `uv add`.
  - `uv run pytest`, `ruff` and `mypy` were run, but with `--no-sync` and the no-cache flags.
  - `uv build --out-dir dist` and `check_dist.py dist/*`: I built into a scratch `--out-dir`; `check_dist.py` printed `all artifacts pass`, exit 0.
- `check_dist.py` exit codes confirmed: 0 for a pass, 1 for an unreadable archive, 2 for no arguments.

## 4. Mechanical checks

**AST equivalence**
- The script is `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/docs/ast_equiv.py`.
- It uses the literal recipe: strip leading docstrings from every Module/Class/FunctionDef/AsyncFunctionDef via `ast.walk`, and substitute `Pass` only if stripping empties the body.
- Before the first edit the snapshot matched the tree (`diff -r`) and all files compared IDENTICAL. After the final edit all 16 files are IDENTICAL: the 11 in `cli_interface/`, 4 in `examples/` and `scripts/check_dist.py`.
- I re-ran it after every file I edited.
- Adding a docstring to `examples/__init__.py` would have failed this recipe, because the file was empty (`Module(body=[])` before, `[Pass]` after). I reverted it to 0 bytes. The README already says `examples/` is sdist-only.

**Test and lint runs** (each after the final edits)
- `uv run --no-sync pytest -q -p no:cacheprovider`: 885 passed in 94 s.
- `ruff check --no-cache cli_interface examples scripts tests`: All checks passed.
- `mypy --cache-dir=/dev/null cli_interface examples scripts`: no issues in 16 files.
- No test pinned a README or docstring fact, so none needed reporting.

## 5. Things the docs cannot honestly say, or that I was unsure of

- **"The 3 decisions flagged for the user" is not identifiable.**
  - The ledger lists 10 decisions to raise at close: D1, D2, D3, D4, D5, D6, D8, D9, D12 and D14.
  - The integrator's report has four [UD] groups (D to G).
  - I did not invent a count. The CHANGELOG Notes list "Provisional decisions (they may change before the first release)". They are the user-visible ones: required `menu`, the target contract, version stays 0.1.0, the 11 names, two warning classes, render-time callables with `<error>`, strip-not-reject, `None` means unbounded, `rich>=13.3.3` and `textual<9`, examples in the sdist only, no license/authors/URLs metadata and unpinned hatchling.
  - The wording is neutral because the CHANGELOG ships in the sdist.
- **The brief says `run(menu)` warnings point at `app.py` "on Python 3.11".** I probed it on 3.13 and the code has no version branch, so it is true on every version. The docs say that. Through the console script the warning points at `cli.py`, which I verified.
- **I reversed two earlier statements based on probes.**
  - The `CLIApp` "Subclassing" docstring said not to call `super().on_mount()`. `PanelInbox.open` and the phrase timer are idempotent, and `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/docs/probe/probe1.py` showed a `Sub(CLIApp)` that calls `super().on_mount()` has one phrase handle and shows each warning once. The docstring now says it is harmless.
  - The README's Pilot caveat ("call `app.exit()` before leaving `run_test` with a spinner running") is removed, because the CF-1 fix made it false. The harness leaves `run_test` with a spinner running and nothing fails.
- **`call_from_thread` after exit.** The README says it raises `RuntimeError`. I confirmed `RuntimeError: Event loop is closed` after the loop was closed. I did not test every shutdown path.
- **Taken from the code or executor reports, not re-run:**
  - `stop_spinner`/`start_spinner` "used to raise" outside the running window: I read the baseline, which called `query_one` with no guard, but did not execute the baseline.
  - Windows and macOS-runner behaviour. The README and CHANGELOG say the CI workflow has not run on GitHub, the suite ran locally on macOS only, and Windows is untested.
  - The lowest-direct CI legs assert only `textual == 0.80.0` (I corrected an overclaim about Rich).
- **Known limitations stated that the brief did not list**, all from code reading or the reviews:
  - The `selected_index` clamp-not-reset after a prune.
  - A callable that keeps raising logs a DEBUG record per evaluation.
  - Nav-bar widths count characters, not terminal columns.
- **Known gap in the docs:** the API table row for `run` is wider than 120 columns, which is fine in a Markdown table.
