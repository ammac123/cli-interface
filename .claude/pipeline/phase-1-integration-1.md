INTEGRATED

Phase 1 is complete as code, packaging and CI. I found no gaps inside P1.1–P1.5 or CF-1–CF-17. One thing stays open before the commit is releasable: README.md and CHANGELOG.md are unmodified, and the README ships as the PyPI long description. It still says "Requires Python 3.13", "no top-level facade yet" and `uv run python main.py`. That is the step-6 Documenter's job per the ledger, so it is not a Phase 1 code gap. Details are in carry-forward A.

## 1. Gaps
None.

The Risk 1 worry is closed. textual 0.80.0 and rich 13.3.3 on Python 3.14.7 pass the full suite on the final code (885 passed).

## 2. Results

All runs were on a scratch copy under `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/integrator/`, never in the repo. The repo's `git status --porcelain` is byte-identical before and after (37 lines), and `uv.lock` is unchanged. No pytest summary line shows `skipped`, so the CF-17 locals control ran on every environment.

### Test runs
| Environment | Command shape | Result |
|---|---|---|
| 3.13.15, textual 8.2.8, rich 15.0.0 (locked, full dev group) | `uv sync --locked`; ruff; mypy; pytest | ruff "All checks passed!"; mypy "no issues in 16 source files"; **885 passed** in 91.7 s. `import cli_interface` printed `0.1.0 11 8.2.8 15.0.0 0.1.0`. |
| 3.12.14, textual 8.2.8 (locked, `--group test` only, as CI) | pytest | **885 passed**, 97.5 s |
| 3.11.16, lowest-direct | `uv sync --resolution lowest-direct --no-default-groups --group test` | resolved textual 0.80.0, rich 13.3.3, pytest 9.2.0, pytest-asyncio 1.4.1. **885 passed**, 90.0 s |
| 3.14.7, lowest-direct | same | resolved textual 0.80.0, rich 13.3.3. **885 passed**, 83.9 s |

The lowest-direct environments also passed:
- `cli-interface --version` printed `cli-interface 0.1.0`.
- `--help` printed ASCII text.
- A bare call exited 2.
- A bad target exited 2.

The lowest-direct runs sat in two parallel suites and the 3.12 run came later. All were green, so no rerun was needed.

The CI lint job replica (`uv sync --locked --no-default-groups --group lint`, 3.13) gave ruff clean and mypy clean on 16 files. That confirms the lint job needs no test-group packages.

### Build and lock
- `uv build --out-dir $SCR/dist` ran in the pristine copy and built `cli_interface-0.1.0.tar.gz` (37,326 B) and `cli_interface-0.1.0-py3-none-any.whl` (35,428 B).
- `uv run --no-project python scripts/check_dist.py ...`, as CI does, printed `ok` for both archives, then `all artifacts pass`, exit 0.
- `uv lock --check` passed (23 packages), and `cmp uv.lock` against the repo's copy is identical.
- sdist members (22):
  - `.gitignore`, `CHANGELOG.md`, `LICENSE`, `PKG-INFO`, `README.md`, `pyproject.toml`
  - `cli_interface/{__init__,_version,app,cli,display,log_handler,menu,phrases,theme,warning_types,widgets}.py` and `cli_interface/py.typed`
  - `examples/{__init__,example_menu,example_worker,main}.py`
  - There is no `tests/`, `.claude/`, `.github/`, `scripts/`, `uv.lock`, `main.py` or `.python-version`.
  - `.gitignore` is the only hatch force-add. It carries the user's `.vscode/` and `.claude/` lines and is allowlisted.
- wheel members: the 11 package modules, `py.typed`, and `dist-info/{METADATA,RECORD,WHEEL,entry_points.txt,licenses/LICENSE}`. There is no `examples/`.
- Metadata:
  - `Requires-Python: >=3.11`
  - `Requires-Dist: rich>=13.3.3` and `textual<9,>=0.80`
  - classifiers for Python 3 and 3.11–3.14, plus `Typing :: Typed`
  - `Version: 0.1.0`
  - `[console_scripts] cli-interface = cli_interface.cli:main`
  - There is no `License` field or classifier (carry-forward G).

### Clean-venv wheel install (3.11.16, run from a directory without `examples/`)
Installing the wheel pulled textual 8.2.8 and rich 15.0.0.
- `--version` printed `cli-interface 0.1.0`, exit 0.
- `--help </dev/null` exited 0 with ASCII text.
- A bare call exited 2.
- `no-such-target` exited 2.
- `no.such.mod:x` exited 2 ("cannot import module").
- `examples.example_menu:build_menu` exited 2 ("No module named 'examples'").
- `py.typed` is present, and `import examples` raises `ModuleNotFoundError`.
- `__version__ == importlib.metadata.version("cli-interface") == "0.1.0"`, with 11 names in `__all__`.

### Repo shim
`PYTHONDONTWRITEBYTECODE=1 uv run --no-sync cli-interface --version </dev/null` printed `cli-interface 0.1.0`, exit 0. The `.venv/bin/cli-interface` shim imports `cli_interface.cli:main`, and a bare call gives the argparse "target required" error.

### Demo under Pilot
The script is `$SCR/demo_pilot.py`. It used only the public API plus `examples`, with `cli_interface.__file__` and `examples.__file__` confirmed to be the scratch copy. I shortened the worker to 4 steps of 0.4 s.
- Driven through `CLIApp(MenuItem("Home"))` plus `set_menu(examples.example_menu.build_menu(app))`:
  - View Output: the `j`, `t`, `c`, `l` and `m` views rendered and the breadcrumb was `Home > View Output`.
  - Settings > Audio > Volume Low: "Volume set to 25%" appeared exactly once, with an `Executed: Volume Low` line.
  - Toggle Debug logged once and the nav showed `Toggle Debug (on)`. Set Port 9090 logged once and the nav showed `Set Port (9090)`.
  - The Set Token prompt: `hunter2` never appeared in the panel, only "Token accepted (7 chars)".
  - Reset All returned to the `Home` breadcrumb through `go_home`.
  - Worker Demo: the nav showed `Worker Demo (running)` and the spinner was on. A Volume High action during the exclusive root capture logged exactly once. On finish the panel read `Executed: Worker Demo` with no "(running)" text, the spinner went off, and the label returned to `Worker Demo` after `refresh_menu`.
  - No `TUILogHandler` was left on any logger.
- `cli_interface.cli.main(["examples.example_menu:build_menu"])` with `CLIApp.run` patched to a `run_test` driver returned 0. The root breadcrumb was `Home`, JSON Config rendered, and Volume Medium logged once.

### Probes
Both were copied to the scratch dir, with `common.py`'s path pointed at the scratch copy. Results match the Tester's figures.

| Probe | 3.13 / textual 8.2.8 | 3.11 / 0.80.0 | 3.14 / 0.80.0 |
|---|---|---|---|
| `exp2_after_exit.py` | 0.51 s, 395 post-exit records, 0 logging-error lines, no handlers left | 0.51 s, 394 records | 0.51 s, 389 records |
| `exp6_exit_latency.py thread` | 0.31 s | 0.32 s | 0.31 s |
| `exp6_exit_latency.py worker` | 3.01 s | 3.01 s | 3.01 s |

The 3.01 s figure for a blocking `thread=True` worker is the same as baseline. Both probes call `super().on_mount()` in a subclass, which is safe now that `on_mount` is idempotent.

### Dead and duplicated code
I ran vulture on `cli_interface`, `examples` and `scripts` and filtered out Textual and Rich hooks.
- Dead code: only `MenuState.move` (`menu.py:275`). It is unused even by tests and predates Phase 1 (baseline `menu.py:179`).
- `PanelInbox.dropped` is flagged but is used by tests and predates Phase 1.
- Duplication, both deliberate or trivial:
  - `_refresh_view` writes both `Dashboard.location` and `Dashboard.crumbs`.
  - The `MenuItem` `TypeError` check appears in both `CLIApp.__init__` and `set_menu`.
- No leftovers from the removed `_BACK`/`_EXIT` sentinels or unused `theme` constants. ruff F401 is clean.

### Public API coherence (11 names)
- Consistency:
  - Names and signatures are consistent. `menu` is the first positional argument and the options are keyword-only on `CLIApp` and `run`.
  - Bad menu type raises `TypeError` everywhere.
  - Invalid `max_lines` and strict-mode conflicts raise `ValueError`.
  - Non-strict conflicts emit `ShortcutConflictWarning`, and ignored attach options emit `LoggingAttachWarning`.
  - Both warning categories subclass `UserWarning`, so older `pytest.warns(UserWarning, ...)` still works.
- `examples/` needs only the facade (`CLIApp`, `LogAttachment`, `MenuItem`, `attach_logging`). The only private touches are in tests.
- The README's old submodule imports (`cli_interface.app`, `cli_interface.menu`) still work.
- Phase 2 names: `App`, `Context`, `Param`, `Secret` and `@app.command` are all free. Module-level `run(menu)` does not collide with a future `App.run()`. `CLIApp` remains the Textual host.
- Two shapes that Phase 2 will supersede (carry-forward E):
  - `run(menu)` cannot hand back the app, so an action that needs `app.panel` must use `CLIApp(MenuItem("Home"))` plus `set_menu(build_menu(app))`.
  - The CLI's `build_menu(app)` rule (a required positional parameter receives the app) goes with it.
- One doc nit for step 6: the `find_shortcut_conflicts` docstring says "CLIApp calls this at construction", but `set_menu` and `refresh_menu` call it too.

### CI YAML (read) and Windows audit (read)
- `.github/workflows/ci.yml`:
  - Actions: `actions/checkout@v6` and `astral-sh/setup-uv@v7` both exist (`git ls-remote --tags` found `v6` and `v7`).
  - Triggers are push to main and pull_request. Permissions are `contents: read`, concurrency cancels in progress, and `timeout-minutes` is 20.
  - The test matrix is 3 OS × 4 Python versions, locked, plus two `include` legs (ubuntu 3.11 and 3.14, lowest-direct). Because `resolution` would overwrite `locked`, those two become new combinations, giving 14 legs.
  - Every bash-syntax step has `shell: bash`: the textual-floor assert, the console-script smoke (`</dev/null`, `|| status=$?`), and the build job's venv step. The non-bash steps (`uv sync`, `uv run --no-sync pytest -q`) are plain commands that also work in pwsh.
  - The build job is ubuntu-only, so `$venv/bin` is fine.
  - The Windows `.exe` shim is found by `test_cli.shim()` via `shutil.which(..., path=<python dir>)`, which is PATHEXT-aware.
- Windows audit of `tests/` and `scripts/` (all clean):
  - All 13 `read_text`/`write_text` calls pass `encoding="utf-8"`, and there is no bare `open()`.
  - Paths put into `-c` probes use `{repo!r}` or `sys.argv`.
  - Synthetic archives use POSIX `TarInfo` names. Symlink cases use `TarInfo.SYMTYPE`, not `os.symlink`, and the unreadable-archive cases use garbage bytes, not chmod.
  - There is no `/dev/null`, `signal` or `fcntl` in Python code.
  - Subprocess output is ASCII (`PYTHONIOENCODING=ascii` for `--help`).

### Spot-checks of tests against their claims
All four assert what the report claims.
- CF-6: the width test compares `_compute_item_width` to `len(_render_item(...).plain)` for shortcuts of length 1–10, whitespace-padded, callable and nav cells.
- CF-2: the AST test fails if `app.py` holds any literal collection with two or more reserved words.
- CF-17: the secret is computed at runtime. The control test calls Textual's own `_fatal_error` and skips only if Textual stops printing locals. It did not skip on any environment.
- P1.1: `test_version_matches_the_installed_distribution_metadata` is a hard assert, not a skip.

## 3. Scope ID closure table
Line numbers are current. "Test" names a file under `tests/`.

| ID | Code | Proving test | Status |
|---|---|---|---|
| P1.1 | `cli_interface/__init__.py:1-22` (11-name `__all__`); `_version.py:1`; `py.typed`; `pyproject.toml` hatch version path and `Typing :: Typed` | `test_public_api.py` (`__all__` exact, every name resolves, star-import, real objects, version equals metadata, `py.typed`, no logging configured) | closed |
| P1.2a | `menu.py:52-53,105-125` (`item_label`/`item_value`); `widgets.py:147-190` (`_value_text`, `_resolve`); `app.py:471,495,501,513-522` | `test_menu_model.py` (first ~11); `test_menu_ui.py` (callable label/value, `<error>`, secret never called, once per render, label read before action) | closed |
| P1.2b | `app.py:275` (`set_menu`), `:299` (`refresh_menu`), `:314` (`go_home`), `:321` (`_validate_menu`) | `test_menu_updates.py` (35 tests: before mount, after exit, prompt open, worker thread, strict rollback) | closed |
| P1.3 | `pyproject.toml [project]` (`requires-python >=3.11`, `rich>=13.3.3`, `textual>=0.80,<9`); `uv.lock` | `test_packaging.py` (requires-python, deps, classifiers, lock matches pyproject); `uv lock --check` passes (D12 and `rich>=13.3.3` are user decisions, carry-forward G) | closed |
| P1.4a | `pyproject.toml [tool.hatch.build.targets.sdist] only-include`; `scripts/check_dist.py` | `test_check_dist.py` (90); real build passes `check_dist` | closed |
| P1.4b | `examples/{__init__,example_menu,example_worker,main}.py`; old files gone | `test_packaging.py` (moved, old not importable, facade-only imports, `build_menu` shape); `test_demo.py` | closed |
| P1.4c | `cli.py:94-117` (`main`); `pyproject.toml [project.scripts]` | `test_cli.py` (63, including subprocess and shim); clean-venv wheel run | closed |
| P1.5 | `pyproject.toml [tool.ruff]/[tool.mypy]/[dependency-groups]`; `.github/workflows/ci.yml`; `check_dist.py` | `test_packaging.py` (ruff, mypy, groups, CI matrix, lowest-direct legs); ruff and mypy clean on locked and lint-only envs | closed locally; Windows/macOS legs unverified |
| CF-1 | `app.py:198-200,376-402,447-458,486-491` | `test_lifecycle.py` (timers, ticks after exit); strict xfail removed from `test_regression.py` | closed |
| CF-2 | `app.py:601-612`; `menu.py:85-98` | `test_menu_model.py` (AST check, `RESERVED_ACTIONS`); `test_menu_ui.py` (16 reserved-command cases) | closed |
| CF-3 | `warning_types.py`; `app.py:330,693-698`; `pyproject.toml` filterwarnings | `test_public_api.py` (categories, escalation, old regex gone) | closed |
| CF-4 | `app.py:321`, called from `__init__`, `set_menu`, `refresh_menu` | `test_menu_updates.py` (shared validation hook) | closed |
| CF-5 | `menu.py:101` (`normalize_shortcut`) and its use sites; `widgets.py:197-199,230` | `test_menu_model.py`; `test_menu_ui.py` | closed |
| CF-6 | `widgets.py:195-201` | `test_menu_ui.py` (width equals rendered width, lengths 1–10) | closed |
| CF-7 | `menu.py:128-139` (`_NavCell`, `make_nav_cell`); `app.py:463,527-531` | `test_menu_model.py`; `test_menu_ui.py` (consumer `__exit__`/`__back__` runs its action) | closed |
| CF-8 | `app.py:705-718` | `test_lifecycle.py` (`run` forwards options); `test_regression.py` signature pin | closed |
| CF-9 | `__init__.py:14-25` | `test_public_api.py` (internals not exported, `LogAttachment` exported) | closed |
| CF-10 | `app.py:177-180` | `test_lifecycle.py` (11 bad values, `None` unbounded, 5100 lines kept) | closed |
| CF-11 | `examples/example_menu.py:11-15,169-171` | `test_demo.py` (log once, once under worker capture, no handler leak) | closed |
| CF-12 | tests repaired: `conftest.py`, `helpers.py`, `test_demo.py`, `test_real_run.py` via fixtures, `test_shortcuts.py`, `test_regression.py` | all green on four Pythons | closed |
| CF-13 | `widgets.py:69-73` | `test_menu_ui.py` (prompt hint shown, two cases) | closed |
| CF-14 | `widgets.py:111-130`; `app.py:471-473` | `test_menu_ui.py` (pipe label is one crumb); `test_markup.py` sample `a|b` | closed |
| CF-15 | `theme.py:26-35`; `app.py:435-440` | `test_menu_ui.py` (hint text pinned, help rows with "+ Enter") | closed |
| CF-16 | ruff and mypy clean on `cli_interface`, `examples`, `scripts`, `tests` (ruff) | the CI-equivalent runs above | closed |
| CF-17 | `app.py:630-640` (`_fatal_error` with `show_locals=False`) | `test_lifecycle.py` (3 tests; ran, not skipped, on textual 0.80.0 and 8.2.8) | closed |

## 4. Carry-forward
User decisions are marked **[UD]**.

**A. Step 6 (Documenter), required before the commit is releasable**
- README: line 14 ("Python 3.13"), lines 8-10 ("no facade yet", imports from submodules), line 185 (`uv run python main.py` and "also: uv run cli-interface", which now exits 2), the no-argument `run()`, `CLIApp` parameters, the whitespace-shortcut and `max_lines` notes, and the `_BACK`/`_EXIT` wording.
- CHANGELOG: bare `cli-interface` exits 2; `run(menu)` required; demos moved to `examples/`; spinner calls are no-ops outside the running window; Python >= 3.11; the new API.
- Docstrings (from the review): the `LogAttachment` direct-construction note, `item_value` not masking secrets, and short docstrings for `reserved_action`, `normalize_shortcut`, `make_nav_cell` and `MenuState.set_root/home/prune`. Also fix the `find_shortcut_conflicts` docstring mention above.

**B. Phase 2**
- `skip_file_prefixes` on 3.12+ so warnings raised via `run(menu)` point at the caller instead of `app.py:716`.
- Thread-safe proxies for `set_menu`, `refresh_menu` and `go_home`.
- Dedupe the DEBUG log for raising callables (about 21 records for 5 interactions).
- `prune` should reset the selection; today it clamps, so the highlight can land on an arbitrary item.
- The `_fatal_error` override targets a private Textual hook, so keep its regression test.
- Retire `Dashboard.location` in favour of `crumbs`. Remove the dead `MenuState.move` (predates Phase 1).
- Everything already listed under Phase 2 in `phases.md`.

**C. Later phase (F7, no-TTY run path)**
- `cli-interface pkg:menu </dev/null` still hangs or spews escape codes. Only `--help` and `--version` are TTY-free.

**D. Phase 4 [UD]**
- The Phase 1 grammar `cli-interface TARGET` is a bare required positional. The planned `cli-interface run "Settings/Set Port" 8080` will need either `run` reserved as a first-argument subcommand, which is safe because a target must contain `:`, or a different verb. Decide when designing headless mode.

**E. Phase 2 design [UD]**
- D2: the `build_menu(app)` convention with a CLI that detects a required positional parameter and passes the app, plus the `CLIApp(MenuItem("Home"))` then `set_menu` pattern. `Context` supersedes it.
- D1: `run(menu)` with `menu` required, so bare `cli-interface` exits 2 and `run()` raises `TypeError`.
- D4 (11-name `__all__`), D5 (two warning categories), D6 (render-time callables with an `<error>` fallback), D8 (strip, don't reject), D9 (`None` means unbounded).

**F. Version and packaging [UD]**
- D3: version stays 0.1.0.
- D14: the sdist ships `examples/`.
- D12 and the `textual>=0.80,<9` ceiling.

**G. Packaging nits [UD]**
- No `license` metadata or classifier, and no authors or URLs.
- `hatchling` is unpinned in `[build-system]`.
- hatch adds the repo `.gitignore` to the sdist (allowlisted).

**H. Housekeeping**
- A stale ignored `__pycache__/main.cpython-311.pyc` and `main.cpython-313.pyc` sit at the repo root from the deleted `main.py`. They are harmless and ignored.
- The user's `.gitignore` edit (`.claude/`) means none of `.claude/pipeline/*` will ever be committed.

## 5. Commit notes
Do not stage `.gitignore` (the user's edit), `README.md` or `CHANGELOG.md`. The two docs files are untouched until step 6.

Git already holds staged renames (`R`) for `cli_interface/example_menu.py → examples/example_menu.py`, `cli_interface/example_worker.py → examples/example_worker.py` and `main.py → examples/main.py`. The latter two plus `example_menu.py` also carry unstaged edits (`RM`).

Suggested command: `git add cli_interface examples scripts tests .github pyproject.toml uv.lock`. It also records the `cli_interface/example_*.py` deletions. The root `main.py` deletion is already staged as part of the rename.

Files that change (36):
- Modified:
  - `cli_interface/__init__.py`, `app.py`, `display.py`, `log_handler.py`, `menu.py`, `theme.py`, `widgets.py`
  - `pyproject.toml`, `uv.lock`
  - `tests/conftest.py`, `helpers.py`, `test_attach_logging.py`, `test_demo.py`, `test_display_limits.py`, `test_inbox.py`, `test_regression.py`, `test_secrets.py`, `test_shortcuts.py`
- Renamed or moved (with edits):
  - `examples/example_menu.py`
  - `examples/example_worker.py` (unchanged content)
  - `examples/main.py`
- New (untracked):
  - `.github/workflows/ci.yml`
  - `cli_interface/_version.py`, `cli.py`, `py.typed`, `warning_types.py`
  - `examples/__init__.py`
  - `scripts/check_dist.py`
  - `tests/test_check_dist.py`, `test_cli.py`, `test_lifecycle.py`, `test_menu_model.py`, `test_menu_ui.py`, `test_menu_updates.py`, `test_packaging.py`, `test_public_api.py`

`main.py` rename: the new `examples/main.py` has under 50% similarity to the old 7-line `main.py`, so `git diff -M` shows delete plus add. That is expected and was accepted as ruling J; commit it as one commit, with no separate rename-only step.

No stray files in the repo: `scripts/`, `examples/`, `cli_interface/` and `tests/` `__pycache__` directories are ignored, and there is no `dist/`, `build/` or cache dir beyond the pre-existing ignored ones.

Suggested subject: `Phase 1: public facade, set_menu/refresh_menu/go_home, callable labels, packaging, console script, examples/, CI`

## 6. Not verified here
- The Windows CI legs (3.11–3.14) and the macOS and ubuntu runner legs were never run. The Windows reading audit is clean (see section 2). I ran everything locally on macOS arm64, so macOS behaviour is effectively covered but not on a GitHub macOS-latest runner. Ubuntu specifics such as a case-sensitive filesystem and glibc are not covered either.
- The CI YAML was never executed. The action tags exist, but `setup-uv@v7`'s `python-version` input combined with `uv run --no-project` is unverified.
- The real TUI under a TTY (F7). I never started it in a non-TTY shell.
- Locked-resolution suites on 3.14 and 3.11 were not re-run by me. The Tester ran 3.14 locked (885 passed), and I ran 3.12, 3.13 and the two lowest-direct legs.
- The `uv build` and `check_dist` run was on macOS only.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/cli.py
- /Users/andrewmacleod/workspace/cli_interface/pyproject.toml
- /Users/andrewmacleod/workspace/cli_interface/.github/workflows/ci.yml
- /Users/andrewmacleod/workspace/cli_interface/scripts/check_dist.py