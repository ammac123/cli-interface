Tester report, Phase 3. I found 2 real code bugs, with 3 failing tests, and left both unfixed as instructed. The full suite gives 2001 passed and 3 failed; those 3 are the bug tests below, and nothing else fails.

## Tests added
All are in `/Users/andrewmacleod/workspace/cli_interface/tests/test_phase3_e2e.py` (41 tests, `ruff check` clean). They use the consumer API (`App`, `Context`, `Param`, `Secret`), `run_test`, and real key presses (tab, type, space, enter, ctrl+u, y/n/escape).

| Deliverable | Tests |
|---|---|
| 1a consumer-sketch flow | 3 |
| 1b settings flow | 4 |
| 1c confirm flow | 6 |
| 1d hostile matrix | 16 |
| 1e non-ASCII, colliding names and `__post_init__` | 5 + 3 bug tests (below) |
| 2 real run in a subprocess | 3 |

- **1a:** a `Select` with `Param(choices=lambda c: c.state...)`, an `int | None` field, a bool Switch and a masked Secret, all filled by key presses.
  - The secret is not visible on screen while typed (the field shows `•`), nor in the panel, nav bar or screen after the job ends.
  - A later job (`Probe`) logs the secret through `ctx.log`, `print` and an attached logger, and all three show `***`. A warning logged after the job ends is also redacted.
  - The other two tests cover empty-optional/default handling with choices re-resolved on each open, and an inline error that moves focus.
- **1b:** nested settings submenu, live nav label, one save per change and none for an unchanged value, reset with `n` then `y`, and a failing save that rolls back. A secret setting is masked and redacted from a later save error and a later command's log. An empty secret submit keeps the value.
- **1c:** four ways of declining a destructive action run nothing (parametrized: Enter on the default Cancel, Escape, and `n`, plus a case that Yes by keyboard runs once). Form then confirm is cancelled at each stage; an invalid form never reaches the confirm. Opening a form and then starting a job externally gives a Busy warning with no crash.
- **1d:** each of the 8 `HOSTILE` strings goes through form labels, help, defaults, choice and multi-choice labels, a validation message, the confirm text and the job result (8 tests). The same 8 go through settings labels, values, help and validation messages (8 tests). No `MarkupError` anywhere and all text renders literally.
- **1e:** non-ASCII parameter names (`größe`, `名前`, `ß`) work end to end. Colliding argparse dests (`a.b`, `a_b`, `a b`) each keep their own value and error. Non-ASCII settings fields also work. A params dataclass whose `__post_init__` raises is covered both with and without confirm: it gives a redacted "Cannot run" error line, the app stays up, and the next try runs.
- **2:** a subprocess runs `App.run(headless=True, auto_pilot=...)`; each test takes about 1.3 s.
  - Quitting with ctrl+q while a form is open exits with code 0, no traceback, and no secret in stdout, stderr or the dumped screen. The same holds with a confirm open.
  - A submitted secret never reaches stdout or stderr. The panel dump shows `***` for `ctx.log`, `print`, a logger record and the return value.

## Mutation pass
I ran 22 mutations, one file at a time, each backed up to the scratchpad `mut/` directory with its shasum checked after every restore. Each ran against `test_phase3_e2e.py` first, then the executors' test files if it survived. All 22 were killed.

| Mutation | Result | Killed by |
|---|---|---|
| M01 confirm default focus set to Yes | killed | e2e declining test (Enter on the default) |
| M02 skip `add_secret` on submit | killed | e2e sketch flow |
| M03 host `secret_values` not unioned in `_collect_secrets` | killed | e2e sketch flow |
| M04 `spec.secrets` dropped | killed | `test_job_params::test_spec_secrets_are_redacted_...` |
| M05 `TUILogHandler` redaction removed | killed | e2e sketch flow |
| M06 blank optional field no longer gives None | killed | `test_params_app::test_every_field_kind_is_delivered...` |
| M07 empty secret submit overwrites the value | killed | e2e `test_an_empty_secret_submit_keeps_the_value` |
| M08 failing save not rolled back | killed | e2e failing-save test |
| M09 reset not recursive | killed | e2e settings session |
| M10 Busy check before the form removed | killed | `test_params_app::test_opening_is_rejected...busy` |
| M11 confirm skipped after a form | killed | e2e form-then-confirm test |
| M12 `spec.kwargs` not delivered | killed | e2e sketch flow |
| M13 `params=False` still derives a form | killed | `test_params_app::...params_false_restores...` |
| M14 X-1 partial check removed | killed | `test_params_app::test_a_partial_does_not_pick_up...` |
| M15 Esc no longer cancels the form | killed | e2e form-then-confirm test |
| M16 `capture_loggers` once-guard removed | killed | `test_params_app::test_capture_loggers_route...` |
| M17 float accepts nan/inf | killed | `test_params::test_float_rules_reject_nan_and_inf` |
| M18 `_safe_id` regex reverted to `[^\w-]` | killed | e2e non-ASCII test |
| M19 no try/except around `pack` | killed | e2e `__post_init__` test |
| M20 colliding field keys not made unique | killed only by `test_forms::test_colliding_field_names_each_keep_their_own_widget` |
| M21 save called even when unchanged | killed | e2e settings session |
| M22 pack error text not redacted | killed | e2e `__post_init__` test |

M20 survives the e2e colliding-names test. Textual only requires ids to be unique among siblings, and each field sits in its own container, so duplicate widget ids do not crash and the submitted values are still correct. Only an id-uniqueness assertion, like the one in `test_forms.py`, detects it. I added nothing for it.

M17 and M19 first errored in my harness because the backup filename contained a `/`. The backup copy failed before anything was written, so nothing was mutated, and I re-ran both successfully.

## Code bugs found (3 failing tests)
**Bug 1: a default or current value in a choice field is not shown in the form.** `cli_interface/widgets.py:267-271` (`FormScreen._make_input`) assigns `select.value = value` before the widget is mounted. The Select's `.value` is then correct, but the `SelectCurrent` label stays `Select.NULL`, so the screen shows the "Select" prompt. The only workaround I verified is passing `value=` to the constructor, as `Select(items, allow_blank=..., value=..., prompt=...)`.
- It affects every Literal, Enum or `choices=` field that has a default (the form shows "Select" while submitting the default silently).
- It also affects settings edit forms for Enum fields, which should show the current value.
- Failing tests: `test_a_choice_field_shows_its_default_option_when_the_form_opens` and `test_the_settings_edit_form_of_a_choice_field_shows_the_current_value`. In both, `.value` is correct but the screen text lacks the label.
- Textual 0.80 was not checked; the reviewer's source check says `value=` exists there.

**Bug 2: a `validate=` callable that raises a non-`ValueError` kills the app.** This is the reviewer's MINOR carry-forward, now confirmed. `params.py:632-636` catches only `ValueError`, so a `ZeroDivisionError` or `TypeError` propagates out of `FormScreen._submit` and Textual's fatal handler exits the app with a traceback. The failing test is `test_a_validate_callable_raising_a_non_value_error_does_not_take_the_app_down`. The suggested fix is to catch `Exception` and show it inline as "Invalid value".

## Observation, not a bug
Ctrl+C does not quit while a form or confirm is open, because the CLIApp `ctrl+c` binding is app-level and a modal screen does not pass it through. Ctrl+Q does quit, and the real-run tests use it. A user may need Esc and then Ctrl+C. I did not check whether `PromptScreen` already behaves the same way.

## Full suite
`uv run pytest -q`: 2001 passed, 3 failed (252 s). The 3 failures are the bug tests above. No hangs.

## Source integrity
After the mutation pass and after the full-suite run, the shasums of every file in `cli_interface/*.py` and `scripts/*.py` matched the originals taken before mutation. `git status --porcelain` is unchanged. I used no git checkout, restore, stash, reset or clean. The stale pytest process (pid 67596) was left alone. Nothing is committed.