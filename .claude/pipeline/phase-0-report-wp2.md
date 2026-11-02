## WP-2 report (the app)

WP-2 is implemented as specified in `cli_interface/app.py`. All five probes and every WP-2 acceptance criterion pass. I made no deviations from the plan and have no cross-package requests.

### 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py` is the only file I edited.
- No git state was changed, no `tests/` was created and `pyproject.toml` was not touched.
- My scratch scripts are in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp2/`:
  - `verify.py`: 60 checks, all pass. The Tester can port it.
  - `modal.py` and `extra.py`.
  - Probe copies.

### 2. Changes, mapped to plan steps (D1, D3, D4, D5, D6, C2, C6)
1. **Imports and constant (step 1).**
   - Added `asyncio` and `warnings`.
   - Imported `LogAttachment`, `PanelInbox` and `find_shortcut_conflicts`, and dropped `TUILogHandler`.
   - Added `_DEFAULT_MAX_LINES = 5000`.
2. **`__init__` (step 2, F8, F6).**
   - New signature: `(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)`.
   - Before `super().__init__`, `find_shortcut_conflicts(menu)` runs.
   - With `strict_shortcuts=True` and any problems, it raises `ValueError("\n".join(problems))`. Otherwise it issues one `warnings.warn(p, UserWarning, stacklevel=2)` per problem and keeps the list in `self._menu_warnings`.
   - After `super().__init__` it sets `_inbox = PanelInbox(self)`, `_attachments`, `_max_lines`.
3. **`compose` (step 3, H1, F6).** `RichLog(..., markup=False, max_lines=self._max_lines)`. This lands together with WP-1's `Text`-only `display.py`.
4. **`on_mount` (step 4, F2).**
   - Existing lines are kept. Then it calls `_ = self.panel` to prime the cache.
   - Then `self._inbox.open(asyncio.get_running_loop())`, which is idempotent.
   - Then it pops each `_menu_warnings` entry and logs it at WARNING. The pop-once pattern holds even if `on_mount` runs twice via `super().on_mount()`.
5. **`on_unmount` (step 5, F3).** It calls `_inbox.close()`, then `detach()` on each attachment in reverse order, then clears the list.
6. **`push_log` (step 6, C2, F2).** It delegates to `self._inbox.put(message, level)` and has a one-line docstring saying it is safe from any thread.
7. **`_show_help` (step 7, F8).** The two rows use the exact D6 strings: `<shortcut> + Enter` / `Activate item by its shortcut (shown in yellow)` and `<number> + Enter` / `Activate item by position`.
8. **`_execute_item` (step 8, F4).** `PromptScreen(item.label, item.prompt, secret=item.secret)`.
9. **`_run_action` (step 9, F4).**
   - The info line is `Executed: {label}` with no value echo. ` → {result}` is added only when `result is not None and not item.secret`.
   - The error line redacts the value with `***` when `item.secret and value`.
10. **`on_input_submitted` (step 10, F8).** Reserved commands compare against `cmd.lower()`. `select_by_shortcut` and the digit logic are unchanged. `on_key` is deleted.
11. **`attach_logging` (step 11, C6, F3).**
    - New signature: `(app, logger=None, *, exclusive=False, level=None) -> LogAttachment`.
    - It prunes inactive attachments and returns the existing active attachment for the same logger object, ignoring the new arguments.
    - Otherwise it creates a `LogAttachment`, appends it to `app._attachments` and returns it.

### 3. Deviations from the plan
None. Two implementation choices:
- Mount-time shortcut warnings go through `self.push_log`, not `panel.log`. They therefore take the inbox's UI path and appear after any pre-mount backlog, in FIFO order.
- The `attach_logging` docstring was left at the original text plus one added line.

### 4. Cross-package requests
None.

### 5. Acceptance criteria and probe results

**Probes** (unedited, run from `.claude/skills/phase-pipeline/probes/`, via `uv run --project`):
- **`io/exp1_logging_threads.py`** passes. It was run from a scratch copy whose only change is `press("a")` to `press("a", "enter")`, per the plan's probe caveat.
  - Main-thread, action and background-thread records are all shown.
  - There is no `handleError` or `RuntimeError` output.
  - No handlers are left on the logger after exit, and a background log after exit is silent.
- **`io/exp2_after_exit.py`** passes. I ran it from the scratch directory.
  - 334 records were emitted by the worker after exit, with 0 logging-error lines and 0 handlers left.
  - `exp2_stacks.txt` was written in scratch and is empty. The repo is clean of stray files.
- **`io/exp7_throughput.py`**
  - Before (plan baseline), 300 records: 135 rec/s producer-blocked, 20,103 `RichLog.write` calls.
  - After, 300 records: about 255k rec/s producer, and exactly 300 `write` calls with 300 lines held.
  - After, 2000 records: 138k rec/s producer, 2000 writes (1:1).
  - After, append mode: 301 writes for 300 records, which is the one `rule` plus 300.
  - My own end-to-end figure for 5000 background-thread records, measured until all lines are in the panel: 0.47 s (about 10.5k rec/s).
  - UI-thread `push_log` direct path: about 17.9k rec/s.
- **`pkg/typed_markup_test.py`** passes: `return_code = None`. My `verify.py` also confirms the panel shows `Unknown command: '[/x]'`.
- **`pkg/edge_test.py`**
  - `crash_case` passes: the app is still running and `return_code` is `None`.
  - `main_thread_log_case` passes: the record is shown, with no stderr output.
  - The post-exit log leaves no handler and no stderr output.
  - My `verify.py` also confirms the panel shows `Error in Boom: bad key [/section] in config`.

**WP-2 criteria** (60 checks in `verify.py`, 0 failures):
- **Prompted action.**
  - `Executed: Set Port → port → 8080` is shown, with no `'8080'`.
  - A secret item shows `Executed: Set Tok` with no suffix and no value.
  - A secret item's error is redacted to `bad token *** rejected [/x]`.
  - The `PromptScreen` Input has `password is False` for a plain item and `True` for a secret item.
- **F8**
  - Typed `Q`, `Quit`, `EXIT`, `HELP`, `B`, `Back`, `Clear` and `?` act as the reserved commands.
  - `press("d")` alone leaves the input at `"d"` and nothing fires; `press("d","enter")` fires.
  - `"on_key" not in CLIApp.__dict__`.
  - The help rows and the real `#hint` widget contain the exact strings. The hint now reads `type a shortcut + Enter`, which also covers WP-3's "not verified" item.
  - A conflicting menu issues 2 `UserWarning`s with the filename pointing at the caller, then one WARNING line in the panel after mount.
  - The panel warning is not duplicated when a subclass `on_mount` calls `super().on_mount()`, or when the subclass logs before `super()`.
  - A consumer `q` shortcut never runs.
  - `strict_shortcuts=True` raises `ValueError`. A clean menu gives no warnings.
- **`max_lines` and `markup`.** `max_lines` is 5000 by default. `CLIApp(menu, max_lines=50)` gives `max_lines == 50`, and 200 records leave `len(lines) <= 50`. `RichLog.markup is False`.
- **`attach_logging`.**
  - A second call returns the same object and leaves one handler. The new arguments are ignored.
  - `detach()` restores handlers and level.
  - Re-attach after detach gives a new object.
  - The root logger is restored exactly at app exit, for the exclusive root case, and the named logger too.
  - `app._attachments` is cleared at exit.
- **`push_log`.**
  - From a background thread, a record appears after one `pause()`.
  - A `join(timeout=5)` on a worker logging 1000 records from the UI thread finishes in well under 2 s, and all 1000 records are shown.
  - After exit, `push_log` and logger records are silent, with zero `handleError` calls.
- **Modal check** (suggested by the advisor, `modal.py`).
  - After a `PromptScreen` is pushed and submitted, then pushed again and cancelled, the inbox state is still `open`. The attachment is still active.
  - A UI-thread record and a background-thread record both appear. So a screen's unmount does not close the inbox.

**`pkg/smoke_test.py`** (run for information) shows 2 expected FAILs and 15 PASSes. Both FAILs are covered by the plan's section 4 "smoke_test needs two changes" note. They are not regressions.
- Step 1, "single-key `v` navigates", now leaves the input at `'v'` without navigating. That is the new F8 behaviour, and the Tester inverts this assertion.
- Step 9 depended on the worker's root attachment leaking. The attachment is now scoped to the worker run. WP-4's in-flight `example_menu.py` provided that scoping in the run.
- The rest pass, including the worker demo, the worker logs reaching the panel, the root logger restored at exit, and a clean exit with `return_code=0`.

**Not verified:**
- Real interactive terminal use. Everything ran under `run_test` or `run(headless=True)`.
- `api/probe4.py`, which breaks because `on_key` is gone (R7). The Tester owns converting it.

**Not touched:** the duplicate `set_interval` timers when `on_mount` runs twice (pre-existing, R4).