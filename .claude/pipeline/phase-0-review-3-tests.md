ROUTE: tester fix

No package change now. Defer the `app.py` guard to Phase 1, to be done together with ruling E (the timer lifecycle). The fix spec is below, in case you want to pull it into Phase 0 anyway.

## 1. Classification: a pre-existing latent bug that only the Pilot harness can trigger

The premise that quitting a real `run()` with a spinner active shows a traceback with `return_code` 1 is not supported by the evidence. The tester inferred it from `run_test` runs under load. I could not reproduce it in a real `run()`.

**Evidence**
- **Real `app.run(headless=True)`, spinner active, quit via `app.exit()`:** 145 quits, 0 crashes (every `return_code` was 0).
  - 60 quits with the exit phase varied against the 83 ms tick (`review/t12.py`).
  - 60 quits with 3 in-process GIL-burner threads (`review/t13.py`).
  - 25 demo "Worker Demo" mid-run quits, where the worker spinner is active by design (`review/t14.py`).
- **Why a real quit is safe:**
  - Textual's `Timer._tick` (`textual/timer.py`) does `if app._exit: return` before invoking a callback.
  - `App.exit()` sets `_exit = True` synchronously (`textual/app.py:1283`).
  - Every quit path in this app goes through `exit()`: `q`/`quit`/`exit`, the Exit sentinel, and Ctrl+C. Ctrl+C is bound to `quit`, and `action_quit` just calls `self.exit()` (`app.py:4460`).
- **Why the tests hit it:** `run_test.__aexit__` calls `app._shutdown()` directly (`textual/app.py:2214-2216`), without `exit()`, so `_exit` stays False. `_shutdown` then runs `_close_all()`, which prunes the screens, while the 1/12 s timer is still alive. A tick landing in that window raises `NoMatches`, and `__aexit__` re-raises it (`app.py:2218`).
- **Measured, 3 burner threads, 50 trials each (`review/t15.py`):**
  - Leaving `run_test` with the spinner running and no `exit()`: 50/50 `NoMatches`.
  - Calling `app.exit()` first: 50/50 clean.
- The code is unchanged since `fdb8069` (the same three unguarded `query_one` calls). It is not a Phase 0 acceptance criterion; WP-4's criterion is about the worker thread's traceback.

**Why defer**
- There is no end-user exposure.
- The proper fix is a timer-lifecycle change (the idle-phrase timer handle isn't even stored), which is ruling E territory and belongs in Phase 1.
- Pulling it into Phase 0 forces another review and test loop on `app.py` for a harness-only hazard.

The one real consequence is for consumers who write their own Pilot tests and end them with a spinner running. That belongs in the Phase 1 backlog.

## 2. Exact fix spec (Phase 1, or Phase 0 if you override)

- **Owner:** WP-2, `cli_interface/app.py`.
- **Guard:** add `if not self.is_running: return` as the first line of each of the three timer callbacks: `_tick_spinner`, `_cycle_spinner_phrase` and `_cycle_phrase`.
  - `_shutdown` sets `_running = False` on its first line, before `_close_all()`, so this closes the window exactly.
  - I verified it with a subclass that applies the guard. 50/50 `run_test` teardowns with no `exit()` were clean, and direct `_tick_spinner()`, `_cycle_phrase()` and `_cycle_spinner_phrase()` calls after exit were harmless (`review/t16.py`).
  - The alternative is `try: ... except NoMatches: return`, which is wordier.
- **Optional hardening:** also stop `_spinner_handle`, `_spinner_phrase_handle` and the idle-phrase timer in `on_unmount`, storing the idle timer's handle first.
- **Ruling E (duplicate `set_interval` on `super().on_mount()`):** stays deferred. In Phase 1, fold it together with this change into one "timer lifecycle" fix: store all three handles, make `on_mount` idempotent, and stop them in `on_unmount`.

## 3. Tester follow-ups (the actual route)

1. **Replace the `stop_spinner()` workarounds with `app.exit()`.** Where `app.exit()` is already called, just delete the workaround. The workarounds hide the scenario the tests claim to cover: the demo worker's spinner is running when the user quits.
   - `tests/test_real_run.py:120`: delete the `app.stop_spinner()` line. `app.exit()` already follows it. I ran the test in a scratch copy without the line, 3/3 passes.
   - `tests/test_demo.py:223` (mid-run close under `run_test`): replace it with `app.exit()`.
   - `tests/test_demo.py:125` (spinner demo): replace it with `app.exit()`.
   - `tests/test_markup.py:295` (dashboard sample): replace it with `app.exit()`.
   - I ran those three replacements in a scratch copy: 9/9 passed, 3 runs in a row. The idle-machine suite passes with them, and the 3-burner experiment above shows `exit()` stays clean under contention.
   - The worker's later `call_from_thread(app.stop_spinner)` still hits the `(RuntimeError, NoMatches)` guard, so WP-4's guard remains exercised.
2. **Fix the xfail test or retire it.**
   - Correct the reason string to say this is a harness-only teardown race: `run_test` shuts down without `exit()`, and a real quit goes through `exit()`, which makes `Timer._tick` return early.
   - Keep `xfail(strict=True)` so it flips red when Phase 1 lands the guard. Reference "Phase 1 timer lifecycle, ruling E".
   - Better: also change it so it exercises the real late-tick shape. Prefer a direct `_tick_spinner()`, `_cycle_phrase()` and `_cycle_spinner_phrase()` call after exit, since the current body also calls `stop_spinner()` first.
3. **Add positive tests:**
   - `run_test`: `start_spinner()`, `app.exit()`, leave the context with no exception. This is the real quit path, and it is deterministic.
   - Real `app.run(headless=True)`: spinner active, `exit()`, `return_code == 0`.
4. **Record the harness hazard in the phase doc.** Consumer Pilot tests must call `app.exit()` before leaving `run_test` if a spinner is running.

## 4. Suite quality: skim of `conftest.py`, `helpers.py` and samples

I checked every test with no assert-like call via an AST scan. The suite looks solid overall: strong helpers, joins with timeouts, no `skip`, 48 self-run mutants, and the order-independence check. Findings:

- **[TESTER] minor: `tests/test_markup.py:170-175` (`test_an_invalid_style_string_does_not_kill_the_ui`)** wraps `app.panel.text("x", style="notastyle zz")` in `try/except Exception: pass`, so it passes even if `text()` raises. WP-1 claims `text()` tolerates an invalid style. Assert it doesn't raise (drop the `try`), keeping `app.is_running`.
- **[TESTER] minor: `tests/test_demo.py:53` (`test_building_the_demo_app_emits_no_warnings`)** has no assertion of its own. It relies on the global `filterwarnings = error::UserWarning`, so it becomes vacuous under `-W default` or `-o filterwarnings=`. Wrap the call in `warnings.catch_warnings(); warnings.simplefilter("error")` as the sibling test at `tests/test_shortcuts.py:90` does.
- **[TESTER] minor: `error::UserWarning` filter in `pyproject.toml`.** It does not hide problems, because it fails tests on any unexpected `UserWarning`. The side effect is that a third-party `UserWarning` after a dependency upgrade fails the whole suite. Keep it, but consider narrowing it to `error::UserWarning:cli_interface` (module filter) or documenting why it's global. I'd also add `error::pytest.PytestUnhandledThreadExceptionWarning`, so an unexpected thread exception in any test fails it.
- **[TESTER] minor: `tests/helpers.py` `demo_worker_threads()`** finds the demo worker by `t.name.endswith("(_run)")`. That relies on Python's thread-naming convention, and `settle_demo_workers` goes vacuous if the name changes. Better: give the demo thread an explicit name (a WP-4 one-liner), or snapshot `threading.enumerate()` before and after.
- **[TESTER] minor: `root_logger_guard` (autouse)** silently cleans up leaked handlers, so a leaked `TUILogHandler` in a test that doesn't use `no_tui_handlers_left` goes unnoticed. Consider making the guard assert that no `TUILogHandler` remains on root after each test (excluding tests that intentionally leave one), or applying `no_tui_handlers_left` to the real-app modules.
- **[TESTER] info: `tests/test_real_run.py` lines 27, 61 and `tests/test_inbox.py:497`** use `time.sleep(0.001)` in hammer threads only, not on the loop thread. That is fine. No fixed sleeps gate assertions, and the `asyncio.sleep(0.05)` calls in `test_inbox.py` are negative-check yields, as documented.

Nothing else found: no leftover cross-test state beyond the root logger (restored per test), the `unique_logger` fixture (unique names, handlers cleared), the `gated_worker` fixture (released and joined), and `fast_worker` (joined).

I changed nothing in the repo. My scratch scripts are in `.../scratchpad/phase0/review/` (`t12.py`–`t16.py`, `tests_copy/`).