# Phase 3 ledger
baseline: 646c78164423ed240a83e7378c4830d8c324701d   branch: phase-3 (from main, which already holds Phase 2)   whiteboard in scope: no (file not on disk)
commits: local checkpoint at close only; nothing pushed
mode: LEAN (SKILL.md "Lean mode"): <=4 WPs, plan <=15 KB, executors own their tests, one review round, orchestrator integrates
round: plan#1 (done, 27 KB, over the 15 KB lean target; accepted) / review#1 running / test#0

Environment: uv resolves Python 3.14.7 (`.python-version` = 3.14); project is `requires-python>=3.13`.
Pre-existing failure at baseline: `tests/test_commands.py::test_cancellable_and_description_are_stored_on_the_leaf` (3.14: `inspect.isroutine(functools.partial)` is True, so `commands.py:38` takes the partial class docstring). Fix inside Phase 3 (commands.py is touched anyway).

## Scope IDs
- P3.1 Parameter schema from a signature (incl. `Annotated[..., Param(...)]`), dataclass or argparse parser; form with validation, Select, Switch, masked fields; kwargs delivered to the action
- P3.2 `app.settings(...)` for dataclass or pydantic models: nested submenus, live values, reset with confirmation
- P3.3 `confirm=` on destructive actions
- C2-1 `App.command` takes a parameter schema (this is P3.1's entry point)
- C2-2 shared secret redaction set for forms and `app.settings(secret=...)`
- C2-3 `capture_loggers=` on `App` (consumer sketch)
- C2-4 `Text` titles on json/table/array/pretty/csv lose style (only if cheap)
- X-1 fix the 3.14 partial-docstring failure above
Out of scope: Phase 4 (subprocess, headless, run verb, NaN JSON), the abandon-policy simplification, MINOR carry-forwards not listed.

| role | agent id | owns | status |
|---|---|---|---|
| Documenter (haiku) | af8713a98f3501fdb | CHANGELOG.md, README.md, docstrings only | done -> phase-3-docs.md |
| Tester (test#1) | a53dc70ae91f4b69e | tests/test_phase3_e2e.py | done -> phase-3-test-1.md (41 e2e tests; 22/22 mutations killed; full suite 2001 pass, 3 fail = 2 code bugs) |
| Reviewer (review#1) | ac475e3de39a0a2e5 | read-only | CHANGES_REQUESTED -> phase-3-review-1.md (2 MAJOR, no BLOCKER) |
| Fix WP-2 ids (haiku) | a201f6fb764a08744 | widgets.py, tests/test_forms.py | done -> phase-3-fix1-wp2.md (100 pass with test_params_app) |
| Fix WP-4 pack crash (haiku) | ab58054aaf80b1fd2 | app.py, tests/test_params_app.py | done -> phase-3-fix1-wp4.md (54 pass) |
| Planner | a4c53ffaf4e75ffe1 | - | done -> phase-3-plan.md |
| Executor WP-1 (wave 1) | a270360a6345578d1 | params.py, settings.py, tests/test_params.py | done -> phase-3-report-wp1.md (94 pass, 3 pydantic skips) |
| Executor WP-2 (wave 1) | a626a5c1fddafecbe | widgets.py, tests/test_forms.py | done -> phase-3-report-wp2.md (45 pass) |
| Executor WP-3 (wave 1) | a910404f4055415a8 | jobs.py, log_handler.py, menu.py, tests/test_job_params.py | done -> phase-3-report-wp3.md (22 pass) |
| Executor WP-4 (wave 2) | a8c8573ec577b9632 | app.py, commands.py, settings_menu.py, __init__.py, pyproject.toml, tests/test_params_app.py, scripts/check_dist.py (add params, settings, settings_menu to PACKAGE_MODULES; requested by WP-1) (+ edits to test_public_api, test_commands) | done -> phase-3-report-wp4.md (52 tests; full suite 1957 pass) |

## Log
- setup: branch phase-3 created from main 646c781; baseline full suite on 3.14.7: 1741 passed, 1 failed (the X-1 partial docstring test), 168 s
- step 1: Planner spawned (a4c53ffaf4e75ffe1, sonnet, Plan)
- step 1 -> plan done; ownership disjoint. Product defaults to raise with user at close: auto-derived forms on existing commands (params=False opts out); form then confirm; C2-4 deferred to Phase 4
- step 2 -> wave 1 spawned (WP-1, WP-2, WP-3)
- WP-1 reported: describe() flat depth-first with dotted names; raises TypeError for class/frozen; extra helpers build_spec, dataclass_default; WP-4 must skip derivation for prompt= items and add check_dist modules
- WP-2 reported: widget ids sanitised ([^A-Za-z0-9_-] -> _), answer-once guard; Textual 0.80 unverified (Select blank via is_blank(), SelectionList.select, private _compositor.render_strips in tests) -> check in lowest-direct run
- WP-3 reported: enter() returns False on empty non-leaf (_activate: on_enter then enter; False = nothing to open); _collect_secrets in jobs.py. Stale hung pytest (pid 67596, from WP-3's run) could not be killed (permission denied) - tell user
- orchestrator: added pydantic>=2 to test group in pyproject, uv lock + sync (pydantic 2.14.2); wave-1 tests 164 pass together
- step 2 -> wave 2: WP-4 spawning
- WP-4 reported: full suite 1957 pass (1 deselected: test_packaging dependency-groups, fixed by orchestrator). Deviations: build_settings_group returns (group, provider); edit form field id is form-field-value; params=None non-strict, True strict; ArgumentParser params cannot mark secrets; redaction text-only. Known: required Literal/Enum Select preselects first option
- step 2 done; step 3 next (one Reviewer round)
- step 3 -> review#1 CHANGES_REQUESTED: MAJOR (1) widgets._safe_id Unicode class + id collisions, (2) app._submit_command pack() unguarded. All executor deviations accepted. MINOR list in phase-3-review-1.md -> carry-forward. Fix agents: fresh haiku (lean mode)
- step 3 fixes done (both MAJOR); orchestrator read both diffs OK. Mutation-check the two new regression tests in step 4 (agents did not confirm they fail without the fix)
- step 4 -> Tester spawning
- step 4 test#1: 2 code bugs: (A) FormScreen._make_input sets select.value before mount so the default label isn't shown (widgets.py:267-271); (B) validate= raising non-ValueError kills app (params.py:632-636). Observation: ctrl+c doesn't quit under a modal. Sent to Reviewer for classification
- step 4 classification (phase-3-review-2-classification.md): A MAJOR WP-2, B MAJOR WP-1, C not a regression (MINOR carry-forward: ctrl+c under modals; PromptScreen same). Orchestrator applied A (Select value= in constructor) and B (validate Exception -> 'Invalid value', secret masked) directly (tiny, budget); updated test_params.py (old KeyError-propagates test was pinning the bug). 243 pass over params/forms/e2e/params_app; ruff + mypy clean
- step 5 -> orchestrator checklist
- step 5 (orchestrator checklist, no Integrator agent): locked 3.14/Textual 8.2.8 full suite 2007 pass; ruff + mypy clean; uv build + check_dist ok on sdist and wheel; import cli_interface ok (15 names); lowest-direct (3.13, Textual 0.80.0, Rich 13.3.3, pydantic 2.12.0): 2005 pass, 2 failed = test bug (tests pressed ctrl+q, which Textual 0.80 does not bind; changed to app.run_action('quit')), both then pass on both envs. pydantic floor raised to >=2.12 so lowest-direct can install. Verdict: INTEGRATED (C2-4 deliberately deferred)
- carry-forward added: ctrl+c / ctrl+q do not quit under a modal (CLIApp ctrl+c is non-priority; 0.80 has no ctrl+q); PromptScreen same
- step 6 -> Documenter (haiku)
- step 6 done. Documenter findings: app-wide secret set strips styling from json/table/pretty output (user decision); redaction DOES cover returned dicts/tables (brief was wrong); app.panel.log inside a job is not redacted
- close: final full suite running, then checkpoint commit
