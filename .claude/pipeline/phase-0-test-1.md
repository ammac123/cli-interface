# Phase 0 Tester report

I built a pytest suite of 447 tests. Three full runs on an idle machine each gave 446 passed, 0 failed, 0 skipped and 1 xfailed. I found no failures that point at the Phase 0 code. Under heavy CPU load I found one pre-existing timing race in the spinner (see section 3). I did not change any package code.

## 1. Files created or changed

**Config**
- `pyproject.toml`:
  - Dev group (`uv add --dev`): `pytest>=9.2.0`, `pytest-asyncio>=1.4.1`.
  - `[tool.pytest.ini_options]`: `testpaths=["tests"]`, `pythonpath=["."]`, `asyncio_mode="auto"`, `asyncio_default_fixture_loop_scope="function"`, `faulthandler_timeout=60`, `filterwarnings=["error::UserWarning"]`.
  - The `error::UserWarning` filter means any unexpected shortcut-conflict warning fails a test. Tests that expect the warning use `pytest.warns`.
- `uv.lock`: updated, as expected.

**Support files**
- `tests/conftest.py` fixtures:
  - `root_logger_guard` (autouse). It restores root handlers and level after every test and ignores pytest's own capture handlers.
  - `host_root`: root configured like a host app, with a sentinel handler at WARNING.
  - `unique_logger`: unique name, `propagate=False`, cleaned up afterwards.
  - `handle_errors`: spy on `Handler.handleError`.
  - `thread_errors`: spy on `threading.excepthook`.
  - `make_app`: app factory.
  - `no_tui_handlers_left`.
  - `gated_worker`: deterministic stand-in for the demo worker, released and joined at teardown.
  - `fast_worker`: the real worker, shortened to a few quick steps.
- `tests/helpers.py` holds pure helpers that tests import directly, because `parametrize` needs `HOSTILE` at import time:
  - `HOSTILE`, `panel_text`, `read_panel`, `widget_text`, `wait_for` (async, polling), `wait_until` (sync), `join_all` and `run_threads` (both with timeouts).
  - `StubApp`/`StubPanel`, `build_demo_app`, `quiet_app`, `Calls`.

**Test modules**

| Module | Tests |
|---|---|
| `test_markup.py` (F1) | 201 |
| `test_shortcuts.py` (F8) | 69 |
| `test_inbox.py` (F2) | 40 |
| `test_attach_logging.py` (F3 and lease) | 40 |
| `test_regression.py` | 27 (26 pass, 1 xfail) |
| `test_secrets.py` (F4) | 26 |
| `test_demo.py` (demo, `main.py`, converted `smoke_test`) | 23 |
| `test_display_limits.py` (F6) | 13 |
| `test_real_run.py` (sync `app.run(headless=True)` tests) | 8 |
| Total | 447 |

The suite has no `skip` marks. The only non-pass is the one xfail described in section 3.

## 2. Results of the 3 full runs (`uv run pytest -q`)

| Run | Passed | Failed | Skipped | xfailed | Time |
|---|---|---|---|---|---|
| 1 | 446 | 0 | 0 | 1 | 63.78 s |
| 2 | 446 | 0 | 0 | 1 | 64.05 s |
| 3 | 446 | 0 | 0 | 1 | 63.91 s |

Extra checks:
- **Reverse module order:** 446 passed, so there is no order dependence.
- **Eight busy-loop processes on 8 cores, 3 runs:** all 446 passed, 1 xfailed, at about 91 s each. The only flake found is described in section 4.

## 3. Failures

**There are no failures in the suite as delivered.** One finding is in package code, but it is out of Phase 0 scope. It is recorded as an `xfail(strict=True)`, not left as a red test.

**Finding: `CLIApp._tick_spinner` can raise at teardown**
- **Test id:** `tests/test_regression.py::test_a_late_spinner_tick_after_the_app_has_exited_is_harmless`.
- **Reproduction:** `start_spinner()` followed by app exit.
  - Under CPU load, the 1/12 s spinner timer sometimes fires after the screen is gone.
  - `query_one("#dashboard")` then raises `NoMatches: No nodes match '#dashboard' on Screen(id='_default')`.
  - Under `run_test`, `__aexit__` re-raises it at `textual/app.py:2218`. In a real `run()` it would show as a crash traceback with `return_code` 1 when the user quits while a spinner is active.
  - It reproduced in 3 of 4 loaded runs of the `test_markup.py -k dashboard` tests, and in the demo mid-run exit test.
- **Test form:** the xfail test is a deterministic repro. It calls `app._tick_spinner()` after the app has exited, which is what a late tick does.
- **My assessment:** code bug, pre-existing.
  - `git diff fdb8069 -- cli_interface/app.py` does not touch `_tick_spinner` (the code was introduced in the baseline).
  - It is not a Phase 0 acceptance criterion. The WP-4 "no traceback" criterion is about the worker thread, and my mid-run exit tests assert that.
- **Where in the code:** `cli_interface/app.py:245-246` (`_tick_spinner`). `_cycle_spinner_phrase` at 248-251 and `_cycle_phrase` at 275-278 have the same unguarded `query_one`.
- **For the reviewer:**
  - Remove the `xfail` mark to turn it into a hard failure.
  - Alternatively, guard the tick, or stop the spinner timers in `on_unmount`.
  - Strict xfail means the suite goes red if someone fixes it, which prompts removing the mark.
- **What I did in the other tests:**
  - Tests that exit with a spinner running now call `app.stop_spinner()` first.
  - Those are `test_markup.py` dashboard tests, `test_spinner_demo_starts_the_spinner`, `test_closing_the_app_mid_run_...` and the real-run mid-run exit test.
  - The worker is still mid-run in the mid-run tests, so what they check is unchanged.

## 4. Flaky tests

- **Spinner race:** the only flake I found. It is described above, and I removed the exposure from the tests that merely end with a spinner running.
- **`test_scheduled_drain_swallows_write_errors_and_keeps_going`:** this was a fixed `asyncio.sleep(0.1)` before clearing the failure flag. I replaced it with a deterministic wait on a `failed_attempts` counter in `StubPanel`.
- **Real-run hammer test:** the first draft flooded the app, so `pilot.press` stalled for about 4 s waiting for an idle UI. I now press before the hammer starts and throttle it to about 1k rec/s. The test takes 0.6 s.
- **Design choices that avoid timing assumptions:**
  - Loop-blocked scenarios block the loop with `thread.join(timeout)`, not `time.sleep`. The producer finishing proves `put` never blocked.
  - The demo worker is a gated stand-in, so double start and mid-run exit are deterministic.
  - Throughput floors are 2,000 rec/s against measured rates of 7-15k.
  - Every thread join has a timeout, and nothing leaves threads running.
  - Negative checks ("nothing arrives") use short yields that cannot cause false failures.

**Mutation check (my own addition).**
- I applied 48 deliberate regressions to a scratch copy of the package.
  - These included markup parsing, lease semantics, secret masking and redaction, case sensitivity, restore-on-exit, demo guards, `main.py` logging, and cap clamping.
  - 46 were caught on the first pass.
  - The two initial survivors were an equivalent mutant and a badly designed one.
  - I re-tested the second with a better mutant and strengthened the assertion. That left 0 real survivors.
- **Equivalent mutant:** removing the `closed` early return in `PanelInbox.put` has no observable effect, because the record is queued but never written.

## 5. Coverage against the review's Tester focus list

1. **Shared attachments, via the lease: covered** (`test_attach_logging.py`).
   - Host attach followed by scoped `exclusive`/`level` attach gives exactly one `UserWarning` (filename is the caller), one `TUILogHandler`, and the host still capturing after the lease is detached.
   - Double `detach()`, `with`, and `with` plus manual `detach()`.
   - Owner detaching first makes leases inactive.
   - `share()` on a lease binds the base.
   - Re-attach afterwards is a real attachment with `exclusive`/`level` honoured.
   - Exit with outstanding leases.
   - Concurrent lease detaches from threads.
   - No "same object" assertion anywhere; it asserts `is not` plus shared `handler` and `logger`.
2. **Inbox overflow: covered** (`test_inbox.py`).
   - Blocked loop with `_INBOX_MAXLEN` monkeypatched, giving at most `cap` records and exactly one notice.
   - The notice is first, or immediately before the first survivor in the real app test, and `dropped` is exact.
   - Caps 0, 1 and -5 clamp to 1.
   - Overflow before `open()`.
   - Cumulative `dropped` across bursts.
3. **Post-exit and teardown: covered.**
   - A worker keeps logging after exit under `run_test` (yielding with `await asyncio.sleep`) and under a real `run(headless=True)`, with zero `handleError`, zero thread excepthooks and no handler left.
   - A subclass `on_unmount` that logs, with and without `super()`.
   - A crash path restores handlers under both `run_test` and `run()` (`return_code == 1`).
4. **Concurrency: covered.**
   - Stress test: 8 threads plus UI puts with no loss, duplicates or reordering, and per-producer FIFO.
   - UI `join(timeout=5)` on a worker logging 1000 records.
   - Re-entrancy dropped on both the direct and scheduled paths.
   - `call_soon_threadsafe` `RuntimeError` closes the inbox.
   - Pre-mount records shown after mount.
   - `on_mount` run twice via a subclass `super()`.
5. **F4: covered** (`test_secrets.py`).
   - Secret value absent from every panel line.
   - Redaction, an empty secret value (the error line is exactly `Error in Tok: token required`), and `Input.password` on the prompt screen.
   - NavBar `(••••)`, with a layout test showing a 300-character secret fits one row masked but wraps unmasked.
   - `repr`, `str` and `!r` of secret items, including nested and cyclic ones.
   - Non-secret repr identical to a stock dataclass.
   - Result suffix suppressed, for prompted and non-prompted items.
   - Plain prompted items do not echo the value.
6. **F1: covered** (`test_markup.py`).
   - 7 hostile strings across 19 panel surfaces: `log`, `text`, `rule`, `json`, `array`, `pretty` (title and data), `table` (title, header, cell, dict key), `csv`, `renderable(str)`.
   - Spinner label, typed commands (including real key presses), action returns and errors, hostile labels in `Executed`/`no action bound` lines.
   - NavBar, Dashboard crumbs, and `PromptScreen` title and prompt.
   - `return_code is None` throughout.
   - Table titles use a wide table.
   - `markup=True` opt-in and invalid-markup fallback.
   - `Text` keeps its style, is not mutated, and is not highlighted.
   - No `str` ever reaches `RichLog.write`.
7. **F6: covered** (`test_display_limits.py`).
   - Write count equals record count on the UI and background paths, and `clear` is never called.
   - `max_lines` in log and content mode, default 5000, and keyword-only.
   - Loose throughput floors.
   - `_log_buffer`, `_render_log_buffer` and `_log_only` are gone.
8. **F8: covered** (`test_shortcuts.py`).
   - Reserved commands in any case.
   - Behavioural `RESERVED_COMMANDS` consistency: every reserved word, as-is and upper-case, with a consumer item sharing that shortcut, never runs the consumer. Near-miss words are ordinary shortcuts.
   - A warning per problem at construction.
   - Exactly the problems, once each, in the panel at WARNING, including for a subclass calling `super().on_mount()`.
   - Strict mode raises `ValueError`, and a clean menu is silent.
   - Single key does nothing and key+Enter fires; no `on_key`.
   - Exact hint (82 characters) and help-row strings, and the old rows gone.
   - `²` does not crash. `٣` selects item 3 with 3 items and is unknown with 2.
   - A key that is reserved and also shared gets one reserved message per item.
9. **Demo and `main.py`: covered** (`test_demo.py`, `test_real_run.py`).
   - Scoped worker with a sentinel host handler and level, then exact restore.
   - Double-start guard and restart.
   - Mid-run close, with no excepthook, no `handleError` and root restored, under both `run_test` and a real run.
   - Worker Demo against a host-attached root, with the expected `UserWarning` and the host still capturing.
   - `import main` in a fresh interpreter leaves root untouched, and `runpy` execution is safe.
   - `Set Token` masked, with no value in the panel.
   - Conflicts `== []` with and without `get_app`.
   - All 8 view-output demos, including the literal-bracket sample.
10. **Regression: covered** (`test_regression.py`).
    - Positional 7-argument `MenuItem` and field order.
    - Signatures of `CLIApp`, `attach_logging`, `DisplayPanel` (9 methods), `PromptScreen` and `push_log`.
    - `PromptScreen` used on its own.
    - Old `attach_logging` call forms.
    - Subclass `on_mount`/`on_unmount` with and without `super()`.
    - A host-built `TUILogHandler`.
    - `api/probe4.py` converted to "single key does nothing; key+Enter fires".
    - `smoke_test.py` converted with both inversions: single-key `v` does not navigate, and the worker's attachment is scoped. The consumer-logger check uses `.warning` on a root-propagating logger so it is not vacuous.

**Probes ported.** Besides the above:
- `exp1`, `exp2`, `exp3b/3c`, `exp7`, `edge_test`, `typed_markup_test`.
- `case/probe3`, `api/probe5`.
- The WP-1 to WP-4 `verify.py` scripts, `host_attach.py`, `realrun.py`, `midrun.py`, `modal.py`.
- The reviewer's `t1`, `t2`, `t4` and `t11`.

**Not covered, per the review's ruling.**
- Attach-after-exit auto-detach.
- `#prompt-hint` height.
- Duplicate `set_interval` timers.
- Global FIFO between `push_log` and direct `panel.log` lines.

## Notes
- **Hint width:** I asserted hint line 1 is exactly 82 visible characters, as WP-3 reported, and line 2 is at most 85.
- **`pilot.press` under flood:** `pilot.press` waits for an idle UI, so it stalls under sustained 1k+ rec/s logging. That is a harness behaviour, and I did not treat it as a code defect.
- **Scratch work:** it is in `.../scratchpad/phase0/tester/` (`mutate.py`, `mutate2.py` and their outputs).
- **Git state:** I changed none. New and changed paths in the repo are `tests/`, `pyproject.toml` and `uv.lock`.