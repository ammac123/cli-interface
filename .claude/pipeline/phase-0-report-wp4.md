## WP-4 report: demo and `main.py`

All WP-4 acceptance criteria were verified end-to-end. WP-2's `app.py` had landed (`LogAttachment`-based `attach_logging`, `on_unmount`, `PromptScreen(..., secret=item.secret)`) when I ran the checks, and I re-checked it just before reporting. I touched only my two files. No git state-changing commands were run, and I created no `tests/` and did not edit `pyproject.toml`.

### 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/main.py`: removed `import logging` and `logging.basicConfig(...)`. The `run` import and `__main__` guard are unchanged.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/example_menu.py`: reworked `run_worker`, added the secret-prompt demo item, and added one literal-bracket log sample.

### 2. Changes mapped to plan steps (D8 / WP-4)
- **`main.py`:** `basicConfig` is gone.
- **`run_worker`, double-start guard:**
  - `worker_running = threading.Event()` is created in the `build_example_menu` scope.
  - If it is set, the action logs `Worker already running` at WARNING and returns.
  - Otherwise it sets the event.
- **`run_worker`, scoped capture:**
  - It calls `capture = attach_logging(app, exclusive=True, level=logging.DEBUG)`.
  - I removed `root.setLevel` and the unused `TUILogHandler` import.
- **`run_worker`, thread `finally`:**
  - `capture.detach()`.
  - Then `app.call_from_thread(app.stop_spinner)` in a try/except.
  - Then `worker_running.clear()`.
- **Secret prompt:**
  - `Set Token` (`shortcut="k"`, `prompt="Enter API token:"`, `secret=True`) sits under Settings, before Reset All.
  - `set_token` logs `Token accepted (N chars)`.
- **Optional bracket sample:** `show_logs` now also logs `Loaded config[server][port] = 8080` at DEBUG.

### 3. Deviation
- **The `stop_spinner` guard also catches `NoMatches`.** The plan said to catch `RuntimeError`; I ship `except (RuntimeError, NoMatches)` with `NoMatches` imported lazily from `textual.css.query` inside `run_worker`.
  - **Real `app.run()`:** `app._loop` is `None` after exit, so `call_from_thread` raises `RuntimeError`, which the guard handles. I checked this with `app.run(headless=True, auto_pilot=...)`: the worker thread produced no traceback and `handleError` was never called.
  - **`run_test`:** `app._loop` is not reset after the app exits. The call is therefore scheduled on the still-running test loop, where `query_one("#dashboard")` raises `NoMatches`, and it reaches the worker thread's excepthook as a traceback. A `RuntimeError`-only guard would fail "closing mid-run produces no traceback" in `run_test` tests, which is how the Tester will run it.
  - Narrowing to `(RuntimeError, NoMatches)` covers both cases without hiding other bugs in `stop_spinner`.

### 4. Cross-package requests and notes
- No file changes are needed outside my files.
- **Observation for WP-2 and the orchestrator (dedup vs scoped detach):**
  - Suppose the host already has an active root attachment on the same app. Then `attach_logging(app, exclusive=True, level=DEBUG)` returns that existing attachment and ignores `exclusive` and `level`.
  - The worker's `capture.detach()` would then detach the host's attachment.
  - The demo cannot hit this, because `run()` never attaches root.
  - Consumers who copy the pattern could. Possible fixes are a "created by this call" flag on the return value or a ref-count. Treat this as an observation, not a blocker.
- **Note for the Tester:**
  - After app exit, tests must yield to the loop (`await asyncio.sleep`) while waiting for the worker thread.
  - Blocking the loop with `time.sleep` leaves the worker stuck in `call_from_thread(...).result()`. That is a test artefact, not a bug.

### 5. Acceptance criteria
All checked against the final files. The final `git diff` of `main.py` and `example_menu.py` was reviewed, and `app.py` had the new `attach_logging` at the last re-check.

Scratch scripts are in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp4/`: `verify.py` (36 checks, all pass), `realrun.py` (real `app.run`) and `midrun.py`.

- **`import main` adds no root handlers and sets no level.** Verified: root handlers and level are identical before and after the import.
- **Worker Demo (`w`, Enter) via `run_test` with a sentinel host handler on root and level WARNING.**
  - While running there is exactly one `TUILogHandler` on root, the host handler is removed, the level is DEBUG and the spinner is running.
  - After the worker ends, root handlers and level are exactly restored and the spinner is stopped.
  - Worker lines, including DEBUG ones, reach the panel.
  - A restart after finishing works.
  - After app exit the root logger is still restored.
- **Second press while running.** Logs `Worker already running` and leaves exactly one `TUILogHandler`.
- **Closing the app mid-run.**
  - Under `run_test`, with a slowed worker: no thread excepthook calls, no `handleError`, the worker thread finishes, and root is restored at exit and after the worker ends.
  - Under real `app.run(headless=True)`: clean, and root is restored.
- **`find_shortcut_conflicts(build_example_menu(...)) == []`.** Verified with and without `get_app`, after adding `k`.
- **`Set Token` (`s`, Enter, `k`, Enter).** The PromptScreen's Input has `password is True`. Typing `hunter2` gives `Executed: Set Token` with no result suffix and `Token accepted (7 chars)`. `hunter2` never appears in the panel.
- **Set Port (non-secret).** The Input is not masked, and the panel shows `Executed: Set Port → port → 8080`.
- **Literal-bracket sample.** `Loaded config[server][port] = 8080` renders verbatim, and the app stays alive.

Nothing is unverified.