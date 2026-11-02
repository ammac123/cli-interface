# Tester follow-ups (review-3 ruling) are done

All follow-ups are in place and nothing started failing when the `stop_spinner()` workarounds were removed. The suite is now 452 tests: 451 pass and 1 is a strict xfail. I changed only `tests/`, `pyproject.toml` and, earlier, `uv.lock`; there are no package changes.

## What I changed, per item

**1. Replaced the `stop_spinner()` workarounds with the real quit path**
- `test_real_run.py` (mid-worker real run): deleted the `stop_spinner()` line, since `app.exit()` already followed it.
- `test_demo.py` (`test_closing_the_app_mid_run_is_clean_and_root_is_restored`): now calls `app.exit()` while the worker is still mid-run and its spinner is active.
- `test_demo.py` (`test_spinner_demo_starts_the_spinner`): now calls `app.exit()` at the end.
- `test_markup.py` (Dashboard sample test): now calls `app.exit()` at the end.
- `grep stop_spinner tests/` now only matches the intentional positive test in `test_regression.py`.

**2. Reworked the xfail test.** It is now `test_regression.py::test_late_timer_ticks_after_teardown_are_harmless`.
- It is still `xfail(strict=True)`.
- The reason string now describes the harness-only race, says the code is unchanged since `fdb8069`, and ends with "Phase 1 timer lifecycle, ruling E".
- The test no longer starts or stops the spinner. It leaves `run_test` and then calls `_tick_spinner()`, `_cycle_phrase()` and `_cycle_spinner_phrase()` directly. Each is tried separately and the failures are collected, so all three are reported when the guard is missing.
- Once the Phase 1 guard lands, the test turns into an XPASS failure, which prompts removing the mark.

**3. Added the positive tests**
- `test_regression.py::test_quitting_through_exit_with_a_spinner_running_leaves_run_test_cleanly`:
  - It is parametrised with no label and with `"busy"`. No label also starts the phrase-rotation timer.
  - It calls `start_spinner()`, lets the 1/12 s timer tick for 0.2 s, calls `app.exit()`, and leaves `run_test` with no exception and `return_code == 0`.
- `test_real_run.py::test_quitting_through_exit_with_a_spinner_running_in_a_real_run_returns_zero`:
  - It is a real `app.run(headless=True)` run with the spinner active.
  - It is parametrised with pauses of 0.0, 0.05 and 0.2 s before `exit()`, so the quit lands at different points in the tick.
  - It asserts `return_code == 0`.

**4. Suite-quality minors**
- `test_markup.py::test_an_invalid_style_string_does_not_kill_the_ui`: dropped the `try/except`. It now calls `text("x", style="notastyle zz")` directly and asserts the app is still running with `return_code is None`. It passes, so `text()` really does tolerate an invalid style.
- `test_demo.py::test_building_the_demo_app_emits_no_warnings`: now a sync test with its own `warnings.catch_warnings()` and `simplefilter("error")`, so it no longer depends on the global filter.
- `pyproject.toml` filters, with one deviation from your instruction:
  - I did not use `error::UserWarning:cli_interface`. The module field matches the module the warning is attributed to. The package warns with `stacklevel=2`, so the construction-time conflict warnings are attributed to the caller (tests or helpers).
  - I confirmed it: with `module='cli_interface'`, constructing a conflicting `CLIApp` raised nothing.
  - Instead I used a message-based filter, `error:.*(reserved command and will never reach|only the first is reachable|were ignored because):UserWarning`. It is exactly the package's warnings. A foreign `UserWarning` is now just a warning and no longer fails the suite.
  - I also added `error::pytest.PytestUnhandledThreadExceptionWarning`.
  - I checked all of this with a throwaway test file, since deleted. The conflict, duplicate and ignored-argument warnings each fail the test, a stray thread exception fails it, a foreign `UserWarning` does not, and `pytest.warns` still works.
- Thread lookup:
  - `helpers.demo_worker_threads()` and `settle_demo_workers()` (which relied on the `"(_run)"` thread name) are gone.
  - There is a new `helpers.ThreadWatch`. It snapshots `threading.enumerate()` at fixture setup and offers `alive()`, `await settle()` and `join()`.
  - `gated_worker` exposes it as `gated_worker.threads`, and `fast_worker` now yields a `ThreadWatch`.
  - No package change was needed.
- Leaked `TUILogHandler`s:
  - I chose the autouse guard rather than a per-module fixture.
  - `root_logger_guard` now fails the test at teardown if a `TUILogHandler` is left on root. The opt-out marker `@pytest.mark.allow_tui_handler_leak` is registered in `pyproject.toml`.
  - `unique_logger` does the same check for the loggers it hands out.
  - The unused `no_tui_handlers_left` fixture is removed.
  - This flagged one real leak in my own test, `test_a_host_built_tui_handler_still_works_...` in `test_regression.py`. The host-built handler was never removed, so the test now removes it. No test needs the opt-out marker.

## Results

**Three full runs on an idle machine:**

| Run | Result | Time |
|---|---|---|
| 1 | 451 passed, 1 xfailed, 0 failed, 0 skipped | 67.28 s |
| 2 | 451 passed, 1 xfailed, 0 failed, 0 skipped | 67.21 s |
| 3 | 451 passed, 1 xfailed, 0 failed, 0 skipped | 67.44 s |

**Under the 8-burner load:**
- The full suite gave 451 passed, 1 xfailed in 91.29 s.
- I then ran the spinner, mid-run and dashboard tests three more times under load. Each run gave 15 passed and 1 xfailed.
- The `exit()` path is clean under contention, as the review predicted.

**Nothing started failing when the workarounds were removed.** That includes the demo mid-run close test, which now quits with the worker's spinner active. `pyflakes` is clean apart from the intentional `_MAX_LOG_LINES` `ImportError` check in `test_regression.py`.

**Phase doc:** I did not write the item 4 note about the Pilot-test hazard ("call `app.exit()` before leaving `run_test` if a spinner is running"), since that belongs in the phase doc, outside my edit scope. The xfail reason carries it for now.

## Test counts per module

| Module | Tests |
|---|---|
| `test_markup.py` | 201 |
| `test_shortcuts.py` | 69 |
| `test_attach_logging.py` | 40 |
| `test_inbox.py` | 40 |
| `test_regression.py` | 30 (29 pass, 1 xfail) |
| `test_secrets.py` | 26 |
| `test_demo.py` | 23 |
| `test_display_limits.py` | 13 |
| `test_real_run.py` | 10 |
| Total | 452 |

Files changed in this round, all under `/Users/andrewmacleod/workspace/cli_interface/`:
- `pyproject.toml`
- `tests/conftest.py`
- `tests/helpers.py`
- `tests/test_demo.py`
- `tests/test_markup.py`
- `tests/test_real_run.py`
- `tests/test_regression.py`