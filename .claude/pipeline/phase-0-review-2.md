VERDICT: APPROVED

Round 2 re-review: all nine round-1 issues are fixed. I found no new issues and no regressions.

## What I checked

I re-read the changed areas in the current diff (8 files, +510 −161): `log_handler.py`, `app.py`, `display.py`, `menu.py` and `example_menu.py`.

I re-ran everything:
- **Executor `verify.py` scripts:** WP-1 112/112, WP-2 `FAILS: []`, WP-3 127 OK, WP-4 36/36.
- **My earlier scripts:**
  - `t1.py`: stress test of 20.5k records from 8 threads plus the UI thread, with no loss, duplicates or reordering. `maxlen=0` no longer raises.
  - `t2.py`: 6 real `run()` cycles hammered through exit, with 0 `handleError` calls, 0 thread exceptions and 0 handlers left.
  - `t4.py`: the dedup/detach scenario.
- **Probes:**
  - `edge_test`: `crash_case` and the post-exit checks are clean.
  - `typed_markup_test`: `return_code = None`.
  - `exp2` (run from a scratch directory): 394 post-exit records, 0 logging-error lines, no handlers left.
  - `exp7` with args: 300 records give 300 `write` calls at about 257k rec/s, 2000 records give 2000 writes, and append mode gives 301.
  - `smoke_test`: 16 PASS and exactly the 2 predicted FAILs (single-key `v`, scoped worker attachment).
  - `realrun`: no worker traceback and root restored.
- **WP-4's `host_attach.py`:** PASS.
- **Imports:** `cli_interface.app`, `example_menu` and `main` import cleanly. `git status` shows only the 8 expected files plus `.gitignore`, and I left nothing in the repo.

I also wrote a new script, `review/t11.py`, covering the lease semantics, `isdecimal`, and the masked repr. All of it passes.

## Per-issue confirmation

1. **Lease (issue 1, WP-1 + WP-2). Fixed.**
   - **`t4.py`:** it now reports `same object: False`, and `host.active` stays True after `scoped.detach()`. The later record is shown and root is restored.
   - **`t11.py`:**
     - A plain repeat attach is silent. `level=` and `exclusive=` each give exactly one `UserWarning`, with the filename of the caller.
     - Every lease satisfies `isinstance(..., LogAttachment)` and shares the owner's `handler` and `logger`.
     - There is exactly one `TUILogHandler` on root. The host StreamHandler and level are kept, and `app._attachments` holds only real attachments.
     - A double `detach()` and a `with` plus manual `detach()` leave the owner active.
     - 8 threads × 50 detaches leave the owner active, and the record is still shown.
     - When the owner detaches first, every lease goes inactive and the handler is gone.
     - A re-attach afterwards is a real attachment again, and `exclusive=True` plus `level=` are honoured.
     - Exit with an outstanding lease restores root exactly.
   - **WP-1's `_Lease.share()` deviation:** accepted. It returns `self._base.share()`, so a lease of a lease binds the real base, which I confirmed.
   - The plan's "returns the same object" criterion is now "returns a handle sharing the same `handler` and `logger`, with exactly one `TUILogHandler` on the logger". The Tester should write it that way.
2. **`maxlen <= 0` (WP-1). Fixed.** `max(1, ...)` clamps it (`log_handler.py:75`), so `put` no longer raises. WP-1's checks cover 0, 1 and -5, `dropped` is exact, and there is one notice. The clamp deviation is accepted.
3. **Dead guard and comments (WP-1). Fixed.** `_write` no longer has the redundant `busy` check; the one in `put` stays. Four concise comments were added, and they match the code: busy-drop, lock scope, UI-thread FIFO drain, and the no-lost-wakeup rule. I re-checked the lock and wake logic and found nothing changed.
4. **`_styled` (WP-1). Fixed.** It now reuses `_as_text`. The `Text` pass-through, the markup fallback and the highlight rules are unchanged, and the F1 checks still pass.
5. **`_ = self.panel` comment (WP-2). Fixed.**
6. **`attach_logging` docstring (WP-2). Fixed.** It now says UI thread only, and it describes the lease and warning behaviour. The attach-after-exit leak stays deferred to Phase 2, as ruled.
7. **Digit command crash (WP-2). Fixed.**
   - `isdecimal()` is used.
   - `²` plus Enter leaves the app alive and shows `Unknown command: '²'`.
   - `٣` (Arabic digit three) and `1` still work, since `int()` accepts all decimal digits.
8. **`MenuItem.__repr__` (WP-3). Fixed.**
   - Secret `current_value` prints `'***'`, including in nested children. Non-secret siblings are unchanged.
   - `str()` and `!r` do not leak it. A non-secret item's repr is identical to the stock dataclass repr.
   - `@dataclass(repr=False)` plus `@recursive_repr()` keeps `eq` and cycles safe.
   - The `'***'` instead of `'••••'` deviation is accepted. It keeps the repr ASCII and matches the exception redaction.
9. **`example_menu.py` (WP-4). Fixed.** `NoMatches` is a module-level import. The nested `finally` chain (`detach`, then `stop_spinner`, then `worker_running.clear()`) is correct. It is a bit deep but fine, and WP-4's mid-run exit checks still pass.

## Tester focus (final code)

1. **Shared attachments, via the lease:**
   - A host attach followed by a scoped attach with `exclusive`/`level` gives one `UserWarning`, one `TUILogHandler`, and the host still capturing after the lease is detached.
   - Double `detach()`, `with`, and `with` plus manual `detach()` on a lease.
   - The owner detaching first makes the leases inactive.
   - `share()` on a lease binds the base.
   - A re-attach after the owner detaches is a real attachment with `exclusive`/`level` honoured.
   - Exit with outstanding leases.
   - Concurrent lease detaches from several threads.
   - The old "same object" assertion must not be used.
2. **Inbox overflow:**
   - A blocked loop with `_INBOX_MAXLEN` monkeypatched small. Assert at most `cap` records plus exactly one dropped notice, placed first, with `dropped` exact.
   - Caps of 0, 1 and -5 (the clamp gives a cap of 1).
   - Overflow before `open()`.
3. **Post-exit and teardown:**
   - A worker that keeps logging after exit, under both `run_test` and a real `run(headless=True)`: zero `handleError` calls, zero thread excepthooks and no handler left. In `run_test`, yield with `await asyncio.sleep`, not `time.sleep`.
   - A subclass `on_unmount` that logs.
   - A crash path restoring the handlers.
4. **Concurrency:**
   - FIFO per producer under multi-thread stress plus UI-thread puts.
   - A UI `join(timeout=5)` on a worker logging 1000 records.
   - Re-entrancy: a record logged from within `panel.log` is dropped.
   - `call_soon_threadsafe` raising `RuntimeError` closes the inbox.
   - Pre-mount records are shown after mount.
   - `on_mount` running twice via a subclass `super().on_mount()`.
5. **F4:**
   - The secret value is absent from every panel line.
   - Exception text redacts the value (best effort, so don't test exotic escaping).
   - An empty secret value.
   - `Input.password` is True on the prompt screen.
   - The NavBar shows `(••••)` and the masked width.
   - `repr`, `str` and `!r` of secret items, including nested ones, contain no secret, and non-secret items are unchanged.
   - A secret item's result suffix is suppressed.
6. **F1:**
   - The hostile-string matrix `[/x]`, `matrix[i][j]`, `C:\data\[/tmp]`, `x\[y`, `[bold]x[/bold]`, `[` and `][`.
   - Surfaces: `log`, `text`, `rule`, `json`, `array`, `pretty`, `table` (title, header, cell and dict key), `csv`, `renderable(str)`, spinner label, typed commands, action returns and errors, NavBar, Dashboard, `PromptScreen`.
   - Assert `return_code is None`.
   - `markup=True` opt-in works and an invalid `markup=True` input falls back to plain text. A `Text` input keeps its style and the caller's object is not mutated.
   - For table titles, use a wide table. Narrow tables wrap the title.
7. **F6:** `write` call count equals the number of records. `len(lines) <= max_lines` in both log mode and content mode. `_log_buffer`, `_render_log_buffer` and `_log_only` are gone. Use a loose throughput threshold (more than 2,000 rec/s).
8. **F8:**
   - Reserved commands in any case: `Q`, `Quit`, `HELP`, `B`, `Clear`, `?`.
   - A consumer `q` or a duplicate shortcut gives a `UserWarning` plus one panel WARNING line (not duplicated on a double `on_mount`), and a reserved item never runs.
   - A key that is reserved and also shared gets one reserved message per item and no duplicate message.
   - `strict_shortcuts=True` raises `ValueError`.
   - `press("d")` alone does nothing, and `press("d","enter")` fires.
   - `CLIApp` has no `on_key`.
   - The exact hint and help strings.
   - A consistency test between `RESERVED_COMMANDS` and the inline handlers in `app.py`.
   - Typed `²` does not crash. A non-ASCII decimal digit such as `٣` is handled.
9. **Demo and `main.py`:**
   - A scoped worker with a sentinel host handler and level.
   - The double-start guard and a restart after the worker finishes.
   - Closing the app mid-run: no traceback, and root restored.
   - The Worker Demo with a host-attached root (expect the `UserWarning`).
   - `import main` leaves root untouched.
   - The `Set Token` item shows a masked input and no value.
   - `find_shortcut_conflicts(build_example_menu(...)) == []`.
10. **Regression:**
    - Positional `MenuItem` (7 args) and `PromptScreen(label, prompt)`.
    - `attach_logging` old call forms: `(app)`, `(app, logger)`, `(app, exclusive=True)`.
    - A subclass overriding `on_mount`/`on_unmount` with and without `super()`.
    - The `DisplayPanel` signatures.
    - Convert `api/probe4.py`, which spied on the removed `on_key`.

## Notes carried forward, none blocking

- **Attach after exit:** `attach_logging` called after the app has exited is not auto-detached. It is documented as "UI thread while running", and full handling is a Phase 2 task.
- **Deferred items:**
  - `#prompt-hint` height 0 (ruling B).
  - The duplicate `set_interval` timers under `super().on_mount()` (ruling E).
- **Direct `panel.log` calls** (the `Executed:` line, `Unknown command`, the demo's `p.log`) bypass the inbox, so FIFO is guaranteed only among `push_log` records. Phase 2's `emit` resolves this.
- **Handler lock stall:** a UI-thread backlog drain runs under the `Handler.handle` lock, so a worker's `logging` call can stall up to about 0.8 s when the UI is already far behind. This is R5, not a deadlock.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/example_menu.py