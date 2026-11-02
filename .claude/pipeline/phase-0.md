# Phase 0 ledger
baseline: fdb8069c702d99d6b2b51a36a66ea1f8804ba6ff   branch: phase-0   whiteboard in scope: no
commits: allowed (local checkpoint at close; nothing pushed)
round: CLOSED

Pre-existing changes, not part of the phase:
- `.gitignore` adds `.vscode/` and `.claude/`. The user made this edit; leave it out of the phase commit.
- `whiteboard.py` is no longer in the working tree (the user removed it).

Scope: F1, F2, F3, F4, F6, F8, and removing `basicConfig` from `main.py`. The Tester builds the pytest and Pilot harness and turns the probes into tests.

| role | agent id | owns | status |
|---|---|---|---|
| Planner (plan#1) | a4ccc62fbf6ee8220 | — | done → phase-0-plan.md |
| Executor WP-1 | afc55a617dc1e2796 | display.py, log_handler.py | done → phase-0-report-wp1.md |
| Executor WP-3 | a589bc19284932280 | menu.py, widgets.py, theme.py | done → phase-0-report-wp3.md |
| Executor WP-2 | add98bd5ce1f08c4c | app.py | done → phase-0-report-wp2.md |
| Executor WP-4 | a536ff2f9548da208 | main.py, example_menu.py | done → phase-0-report-wp4.md |
| Reviewer | ab8c59b83c6a24395 | — | review#2 APPROVED → phase-0-review-2.md |
| Tester | ab71eb6628a08e5e2 | tests/, pyproject test config, uv.lock | test#2 green → phase-0-test-2.md |
| Integrator (int#1, int#2) | a8337eca279fc4c87 | — | int#2 INTEGRATED → phase-0-integration-2.md |
| Documenter | ac8f6f88cafd225b6 | docstrings/comments, README.md, CHANGELOG.md | done → phase-0-docs.md |
| Planner (plan#2, gaps) | ae311ddcd71c1b593 | — | done → phase-0-plan-2.md |

## Log
- setup: branch phase-0 created from fdb8069
- step 1: Planner spawned (Plan, sonnet)
- step 1: plan#1 received. 4 work packages: WP-1 display+log_handler, WP-2 app, WP-3 menu+widgets+theme, WP-4 main+example_menu. Checked that file ownership is disjoint.
- Open questions decided with the planner's defaults; to raise with the user at close:
  - Q1: warn by default, with strict_shortcuts=True to raise
  - Q2: no markup opt-in for labels
  - Q3: max_lines=5000
  - Q4: case-insensitive reserved commands
  - Q5: no warning for digit shadowing
- step 2: run in two waves to avoid transient import breaks (R3). Wave 1: WP-1 and WP-3. Wave 2: WP-2 and WP-4.
- step 2: wave 1 spawned (WP-1, WP-3; general-purpose, sonnet)
- step 2: WP-3 done. All acceptance criteria pass, and output is identical to fdb8069. Deviation: a key that is both reserved and duplicated gets only the reserved message. Flagged for review: the pre-existing bug where #prompt-hint has height 0 and is invisible.
- step 2: WP-1 done. 84 checks pass. Deviations: highlight is off when text() has an explicit style; table.title style kept; LogAttachment rolls back if attach fails; Text inputs are copied. WP-1 and WP-2 must land together, because push_log writes off-thread until WP-2 lands.
- step 2: wave 2 spawned (WP-2, WP-4)
- step 2: WP-2 done. No deviations. All 5 probes pass; 60 checks pass. exp7: 300 records went from 20,103 writes to 300 writes. smoke_test has 2 expected failures (single-key v; worker attachment scope).
- step 2: WP-4 done. 36 checks pass. Deviation: also catches NoMatches in stop_spinner. Flagged: attach_logging dedup returns the host's attachment, so a scoped detach() would detach the host's.
- step 3: review#1 spawned (Plan, sonnet). Diff: 8 files, +465 −157. Rulings requested on A (dedup vs detach), B (prompt-hint), C (NoMatches), D (WP-1 deviations), E (timers).
- step 3: review#1 returned CHANGES_REQUESTED.
  - Major issue 1: the dedup in attach_logging returns the host's attachment. Fix: a lease handle (WP-1) plus share() and a warning (WP-2).
  - Minors 2–9, all to be fixed: WP-1 #2–4, WP-2 #5–7, WP-3 #8, WP-4 #9.
  - Rulings: A is a defect. B (prompt-hint) is deferred to Phase 1 UI polish. C is accepted. D: all accepted. E is deferred.
  - Fix round 1 sent to all 4 executors via SendMessage.
- fix#1: WP-3 done (#8: masked __repr__ with recursive_repr; 127 checks pass; 0 rendering diffs)
- fix#1: WP-1 done (#1 _Lease + share(); #2 clamp maxlen; #3 guard removed, 4 comments added; #4 _as_text reuse; 112 checks pass)
- fix#1: WP-4 done (#9: import moved to top, nested finally; 36 checks pass; host-attach dedup check passes)
- fix#1: WP-2 done (#1 share() + UserWarning; #5 comment; #6 docstring; #7 isdecimal; 77 checks pass; all probes pass)
- step 3: review#2 sent to the reviewer via SendMessage
- step 3: review#2 APPROVED. All 9 issues fixed, no regressions. Carried forward: attach-after-exit (Phase 2), prompt-hint and timers (deferred), direct panel.log bypassing FIFO (Phase 2), R5 stall.
- step 4: Tester spawned (general-purpose, sonnet)
- step 4: test#1 done. 447 tests: 446 passed, 1 xfail (strict); mutation check found 0 real survivors. The orchestrator confirmed 446 passed, 1 xfailed in 63.8 s. The xfail is a pre-existing crash: a late spinner tick hits NoMatches after exit (app.py:245-251, 275-278). Sent to the reviewer for classification.
- step 4: reviewer ruled ROUTE tester fix. The spinner NoMatches is harness-only:
  - A real quit goes through exit(), and Timer._tick then returns early. 145 real quits produced 0 crashes.
  - The guard `if not self.is_running: return` is deferred to Phase 1 "timer lifecycle", together with ruling E.
  - Tester follow-ups sent via SendMessage: replace the stop_spinner workarounds with exit(), rework the xfail, add positive tests, 5 suite-quality minors.
  - Correction: I had told the user a real run crashes with return_code 1. That is wrong.
- step 4: test#2 green. 452 tests: 451 passed, 1 strict xfail (harness-only timer race, Phase 1). Filters are message-based; the leak guard is autouse. Orchestrator re-ran the suite to confirm.
- step 5: Integrator spawned (Plan, sonnet)
- step 5: int#1 returned GAPS.
  - G1: the unique_logger id() name reuse picks up pytest capture handlers. It fails on 3.11 with textual 0.80.
  - G2: the Back cell advertises `esc`, which doesn't work when typed.
  - 18 items carried forward (see the report). Health: 3.11, 3.13 and 3.14 all pass; textual 0.80 works; mypy has the same 2 errors; pyright is clean.
  - The integrator's stray .mypy_cache was removed.
- step 1 (round 2): gap Planner spawned, scoped to G1, G2 and carry-forward #1
- step 1 (round 2): plan#2 done.
  - G1: module-level itertools.count(), plus an assert that the name is unused.
  - G2: option (a), the Back sentinel shows `b`.
  - CF1: switch the test to rich Text.
  - WP-A (app.py) goes to the existing WP-2 executor. WP-B (tests) goes to the existing Tester.
  - New carry-forwards: shortcuts with surrounding whitespace never match; the hard-coded sc=2 width estimate.
- step 2 (round 2): WP-A and WP-B sent via SendMessage
- round 2: WP-A done (Back sentinel shows b, plus 1 comment; test_shortcuts 69 passed)
- round 2: WP-B done (G1 counter plus assert; CF1 rich Text; 15 shortcut tests and 1 fixture self-test; 467 passed, 1 xfail ×3 on 3.13 and ×3 on 3.11/textual 0.80; mutation: 6 Back-cell tests fail)
- step 3 (round 2): review#3 sent to the reviewer
- step 3 (round 2): reviewer hit the session rate limit mid-review; resumed via SendMessage after the reset
- step 3 (round 2): review#3 APPROVED. Minor [TESTER] item: the unique_logger assert misfires when pytest.main() runs twice in-process; fix is a skip-until-free loop. Sent to the Tester.
- round 2: Tester applied the skip-until-free loop; 467 passed, 1 xfail; two in-process runs pass (the repro is real)
- step 5 (round 2): int#2 sent to the integrator via SendMessage
- step 5 (round 2): int#2 INTEGRATED. G1, G2 and CF1 closed. 467 passed, 1 xfail on 3.13 and on 3.11/textual 0.80. 19 carry-forward items.
- step 6: Documenter spawned (general-purpose, sonnet)
- step 6: docs done.
  - README is 208 lines and CHANGELOG is new. AST check confirms only docstrings and comments changed. All README snippets were run.
  - The orchestrator removed the README link to the gitignored phases.md.
- close: final suite 467 passed, 1 xfailed. phases.md updated with the carry-forward items.
  - Local commit 4cab69a on phase-0, not pushed. The user's .gitignore edit was left unstaged.
- after close: user accepted the defaults Q1–Q5; whiteboard is out of Phase 1. phase-0 fast-forward merged into main locally. Next: /clear, then "run phase 1".
