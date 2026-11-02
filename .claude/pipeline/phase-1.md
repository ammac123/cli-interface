# Phase 1 ledger
baseline: 4cab69a9e3cea0a74fb7756990f0476b5b550786   branch: phase-1 (from main)   whiteboard in scope: no
commits: allowed (local checkpoint at close; nothing pushed)
round: CLOSED (plan#1 / review#2 / test#1 / int#1 / docs)

Pre-existing changes, not part of the phase:
- `.gitignore` adds `.vscode/` and `.claude/` (user's edit; leave unstaged).

Scope: phases.md "Phase 1: public API and packaging" table plus "Carried forward from Phase 0 → Phase 1".

## Scope IDs (every WP, review, test and integration check cites these)
Phase table:
- P1.1 `__init__` facade with `__all__`, `py.typed`, `__version__`
- P1.2 `set_menu()`, `refresh_menu()`, `go_home()`; labels and values can be callables
- P1.3 `requires-python>=3.11`, declare `rich>=13`, `textual>=0.80,<9`; relock
- P1.4 explicit sdist include list (no tests/, .claude/, uv.lock); demos to `examples/`; console script `cli-interface pkg.mod:build_menu`
- P1.5 ruff + mypy; CI ubuntu/macos/windows × 3.11–3.14 with lowest-direct; build allowlist check (runnable locally)
Carry-forward:
- CF-1 timer lifecycle: `is_running` guard in `_tick_spinner`/`_cycle_spinner_phrase`/`_cycle_phrase`; store all timer handles; idempotent `on_mount`; stop timers in `on_unmount`; remove strict xfail `test_late_timer_ticks_after_teardown_are_harmless`
- CF-2 `RESERVED_COMMANDS` single source for dispatch (remove inline tuples in app.py)
- CF-3 `ShortcutConflictWarning(UserWarning)`; pytest filterwarnings by category (keep coverage of the attach_logging "were ignored because" warning)
- CF-4 extract `_validate_menu()` used by `set_menu()`/`refresh_menu()`
- CF-5 shortcuts with leading/trailing whitespace: strip or reject
- CF-6 NavBar `_compute_item_width`: `sc = 2` → `len(shortcut) + 1`
- CF-7 Exit/Back sentinel collision with consumer `description="__exit__"/"__back__"`: private sentinel object
- CF-8 `run(menu)` passes `strict_shortcuts` and `max_lines`
- CF-9 `LogAttachment` exported as a return type only; `PanelInbox`, `TUILogHandler` not in `__all__`
- CF-10 validate and document `max_lines` for `None` and `<=0`
- CF-11 demo "Settings" items log into nothing: attach capture for the demo logger after the move
- CF-12 tests/demo coupling (conftest gated_worker/fast_worker, helpers.build_demo_app, test_demo.py, test_real_run.py demo tests, test_shortcuts.py demo walk, no-arg run() in test_regression.py)
- CF-13 `#prompt-hint` height 0
- CF-14 `|` in a label splits the breadcrumb
- CF-15 hint and help `q` rows lack "+ Enter"
- CF-16 ruff style (quoted annotations, UP rules, `zip(strict=)`); mypy 2 baseline errors app.py:158, 161
- CF-17 Textual fatal traceback `show_locals=True` can print a secret `value` local

| role | agent id | owns | status |
|---|---|---|---|
| Planner (plan#1) | a606118f650b45bb9 | — | done → phase-1-plan.md |
| Executor WP-1 | a7a7a0330a2f8e97a | menu.py, widgets.py | done → phase-1-report-wp1.md |
| Executor WP-2 | ab382f48ab93e8c9a | log_handler.py, display.py, phrases.py, warning_types.py | done → phase-1-report-wp2.md |
| Executor WP-3 | a4cedb1a94368e7be | pyproject.toml (not pytest table), uv.lock, _version.py, py.typed, scripts/check_dist.py, .github/workflows/ci.yml | running (W1) |

## Log
- setup: branch phase-1 created from main @ 4cab69a. Setup answers taken from phases.md user decisions (2026-11-01): whiteboard out, branch from main.
- step 1: plan#1 received → phase-1-plan.md. 7 WPs, 3 waves: W1 = WP-1 menu+widgets, WP-2 leaf modules+warning_types, WP-3 packaging/CI/check_dist; W2 = WP-4 app+theme, WP-5 facade; W3 = WP-6 cli.py, WP-7 examples/. Ownership disjoint (checked). Tester owns tests/ and [tool.pytest.ini_options].
- Decisions D1–D19 taken with the planner's defaults; to raise at close: D1 run(menu) required / bare cli-interface exits 2, D2 target contract (+app param, cwd on sys.path), D3 version stays 0.1.0, D4 11-name __all__, D5 two warning categories, D6 render-time callables + "<error>", D8 strip whitespace silently, D9 None=unbounded, D12 rich>=13.3.3 (not >=13), D14 sdist ships examples/.
- Planner notes: mypy baseline errors are now app.py:230/233 (ledger's 158/161 stale). Expected test breakage between step 2 and 4 is listed in plan §5 (conftest, helpers, test_demo, test_real_run, test_shortcuts, test_regression).
- step 2: wave 1 spawned (WP-1, WP-2, WP-3; general-purpose, sonnet)
- step 2: WP-2 done. warning_types.py added; 5 UP037 + 1 B905 fixed; phrases.py untouched (clean). No deviations. Suite 467 passed, 1 xfail.
- step 2: WP-1 done. All contracts in; ALL OK acceptance script; suite 467 passed, 1 xfail. Deviations: NavBar shows stripped (not lowercased) shortcut; snapshot attr `_snap`; make_nav_cell raises ValueError on unknown kind; item_value doesn't mask secrets (caller must). Cross-pkg: app.py:380 PromptScreen(item.label) now a mypy error → WP-4 (already planned). Interim visual-only: baseline app builds plain MenuItem nav cells until WP-4.
- step 2: wave 2 spawned early (WP-4, WP-5) — their deps (WP-1, WP-2, and WP-3's _version.py) are in the tree; WP-3 still finishing pyproject/lock/CI.
- step 2: WP-5 done. 11-name __all__, star-import clean, logging untouched, filterwarnings category resolution works. No deviations. Note: LogAttachment 'discouraged' docstring left to step 6. __version__ vs importlib.metadata unverified (needs sync) → Tester/Integrator.
- step 2: WP-3 done. pyproject per plan §4 (pytest table byte-identical); relock needed network (offline lacked mypy metadata), not hand-edited; lock: textual 8.2.8, rich 15.0.0, ruff 0.17.3, mypy 2.4.1. check_dist interim: exactly the 10 planned problems; ~40 negative controls exit 1. Deviations: hatch force-adds .gitignore to sdist (allowlisted); check_dist also compares the repo _version.py; CI uses `uv run --no-project python` for check_dist; extra build-job checks. Risk 1: lowest-direct on 3.11 and 3.14.7 both resolve textual 0.80.0/rich 13.3.3, 467 passed (mid-W1 snapshot). .venv cli-interface shim stale until sync. The __init__.py change WP-3 saw was WP-5 (expected).
- step 2: WP-4 done. ruff/mypy clean (whole package mypy 0 errors). ~75 Pilot checks pass on 3.13/8.2.8 and 3.11/0.80.0. Suite: 382 passed, 2 failed + 1 collection error, all §5-expected (test_shortcuts _BACK/_EXIT import; run signature pin; xfail now XPASS strict). Deviations: widget refs cached via _bind_view (screen_stack[0] empty pre-mount); lazy bind in start_spinner for subclass on_mount; spinner methods no-op outside running window; _activate resyncs on stale submenu; strict refresh_menu raises before prune; selection clamped after prune; set_menu rollback; warnings via run(menu) point at app.py (no skip_file_prefixes on 3.11); clear/help rows not given '+ Enter'; q hint moved to line 2.
- step 2: wave 3 spawned (WP-6, WP-7)
- step 2: WP-6 done. cli.py per D2; ruff/mypy clean; error paths exit 2, build_menu exceptions exit 1 with traceback; verified via python -m, scratch-wheel shim, in-process harness, run_test() e2e on 3.13/8.2.8 and 3.11/0.80. Choices: ImportError (incl. inside target) → exit 2 no traceback; CLIApp built before target parse; strict message header line; invalidate_caches; '(default: 5000)' hardcoded; SystemExit escapes main(). Shared .venv shim stale until sync. One accidental non-TTY TUI launch was killed (F7).
- step 2: WP-7 done. git mv demos → examples/; build_menu(app); facade-only imports; D19 capture (propagate=False, per-action attach); callable value/label dogfood; Reset All → go_home. ~75 Pilot checks ALL OK on 3.13/8.2.8 and 3.11/0.80. Suite after move: 357 passed, 2 failed, 4 errors — all §5-expected. Deviations: Toggle Debug message now 'toggled on|off'; worker flag ordering/race fixes; Executed line shows '(running)' label. main.py won't survive as a rename (similarity <50%). Tester hand-off for CF-12 in report §5. README:185 stale → Documenter.
- step 3: review#1 spawned (Plan, sonnet). Diff: 14 tracked files +899 −255 plus 7 new. Rulings requested A–J on executor deviations. Reviewer told §5 test breakage is expected.
- step 3: review#1 APPROVED, with 2 minors to fix before step 4 (#1 WP-4 Executed/Error label resolved after action → resolve before; #2 WP-6 ImportError inside user module loses traceback → only ModuleNotFoundError for the target itself) and nits (#3, #4 WP-6 help epilog/default; #6 WP-1 _snap re-entry; #7 WP-4 hint line 2 ≤76 chars; #8 WP-4 clear/help rows + Enter). #5 (DEBUG log dedupe) deferred to Phase 2.
  - Rulings: A, B, C, D, E, F, I, J ACCEPT; G DEFECT (=#1); H partial DEFECT (=#2). J: single commit (no two-step main.py rename).
  - Tester items T1–T6 (22 ruff errors in tests, filterwarnings category form, xfail removal, CF-12 demo coupling, test_shortcuts sentinel/hint rewrites, new tests per plan §5). Docs items listed for step 6.
- fix#1 sent: WP-4 (#1, #7, #8), WP-6 (#2, #3, #4), WP-1 (#6) via SendMessage
- fix#1: WP-1 done (#6 _snap save/restore at widgets.py:276-281; ruff/mypy clean; acceptance ALL OK incl. re-entry check)
- fix#1: WP-6 done (#2 only target's own ModuleNotFoundError → exit 2, else traceback exit 1; #3 generic epilog; #4 _DEFAULT_MAX_LINES in help; ruff/mypy clean; 8 import-path controls pass)
- fix#1: WP-4 done (#1 label resolved before action at app.py:513; #7 hint line 2 now 73 chars, fits 80 cols; #8 clear/help rows + Enter; Pilot ALL OK on 3.13/8.2.8 and 3.11/0.80; suite same §5 failures)
- step 3: review#2 (fix check) sent to the reviewer via SendMessage
- step 3: review#2 APPROVED. All fix-round-1 items verified on 3.13/8.2.8 and 3.11/0.80; ruff/mypy clean (16 files); suite = §5 set. Final summary for the Tester in phase-1-review-2.md (pinned behaviours 1–5, T1–T6). Reviewer briefly launched a non-TTY TUI (F7) and killed it.
- step 4: Tester spawned (general-purpose, sonnet)
- step 4: test#1 green. 885 passed (418 → +384 new across 8 new files, plus repairs), 0 xfail, on 3.13/8.2.8 locked, 3.11/0.80.0+rich 13.3.3 lowest-direct, and 3.14/8.2.8. ruff clean incl. tests. Mutation check: 36 mutations, 35 caught, 1 equivalent survivor (is_running half of _tick_spinner guard; refs-cleared half still guards). No suspected code bugs. Tester ran `uv sync --locked` on shared .venv (shim refreshed). Not verified: 3.14 + textual 0.80 on final code; real build; Windows.
- orchestrator re-ran: `uv run --locked pytest` 885 passed in 97.5 s; ruff clean (cli_interface examples scripts tests); mypy clean (16 files).
- step 5: Integrator spawned (Plan, sonnet)
- step 5: int#1 hit the session rate limit mid-run (reset 2:50am AEDT); resumed via SendMessage at 11:31 AEDT 2026-11-02. User asked to use cheaper models for simpler agent tasks (e.g. Documenter, mechanical work); Reviewer/Integrator/Planner stay sonnet.
- step 5: int#1 INTEGRATED, no gaps. 885 passed on 3.13/8.2.8 locked, 3.12 locked, 3.11 and 3.14 lowest-direct (textual 0.80.0, rich 13.3.3) — Risk 1 closed. uv build + check_dist all-pass; uv lock --check ok; clean-venv wheel install ok; shim ok; demo under Pilot ok; probes match. No gaps. Open before releasable: README/CHANGELOG stale (step 6). Carry-forward A–H in the report; user decisions D/E/F/G flagged.
- step 6: Documenter spawned (general-purpose, sonnet)
- step 6: docs done. README rewritten (~440 lines), CHANGELOG Phase 1 section, public-API docstring coverage 97/101 (gaps by design: _version.py, phrases.py, empty examples/__init__.py). All 12 README python blocks and the bash lines run headless (56 ok on 3.13/8.2.8 and on 3.11/0.80). Orchestrator re-verified: AST-equivalence (docstrings stripped) 16 files, 0 problems; pytest 885 passed; ruff and mypy clean. Documenter reversed two stale claims after probing (subclass super().on_mount() is harmless; Pilot app.exit() caveat gone).
- close: final suite 885 passed. phases.md updated (Phase 1 status + 'Carried forward from Phase 1'). Local commit 71a0e49 on phase-1, not pushed; user's .gitignore edit left unstaged. Model use: all subagents sonnet; user asked on 2026-11-02 for discretion on cheaper models for simpler tasks. Next: user decisions D1–D14 + merge phase-1 into main, then /clear and 'run phase 2'.
