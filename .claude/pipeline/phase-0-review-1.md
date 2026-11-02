VERDICT: CHANGES_REQUESTED

Scope reviewed: the real diff `git diff fdb8069 -- . ':!.gitignore'` (8 files, +469 −157) and the full current files. I did not treat the reports as evidence. I re-ran all four executor `verify.py` scripts: 84, 60, 112 and 36 checks, all pass. `smoke_test.py` gives exactly the 2 predicted FAILs (single-key `v`, and the scoped worker attachment).

My own throwaway scripts are in `.../scratchpad/phase0/review/` (`t1.py`–`t10.py`, `unused.py`). Nothing was written to the repo, and `git status` shows only the 8 expected files plus the user's `.gitignore`.

What I checked:
- **Inbox stress:** 8 threads plus UI-thread puts, 20.5k records. FIFO per producer, no loss, no duplicates, no pending wake. A put after the loop closed closes the inbox cleanly.
- **Exit under load:** 6 real `run(headless=True)` cycles with a thread hammering a logger through start, UI-thread logging, an action and exit. 0 `handleError` calls, 0 thread exceptions, 0 handlers left.
- **Teardown paths:** a subclass overriding `on_unmount` without `super()` still runs the base handler (0 handlers left). Handlers and level are also restored when the app crashes.
- **F1:** 17 surfaces × 7 hostile strings (`[/x]`, `matrix[i][j]`, `C:\data\[/tmp]`, `x\[y`, `[bold]x[/bold]`, `[`, `][`) through the real app. Surfaces: `log`, `text`, `rule`, `json`, `array`, `pretty`, `table` title/header/cell/key, `csv`, `renderable`, spinner label, typed commands, action return values, exception messages, NavBar, Dashboard crumbs and `PromptScreen`. There were no crashes and no mangling. The one apparent miss, table titles, was Rich wrapping the title to a narrow table. A wide table renders them verbatim.
- **Plan conformance:** D1–D8 and C1–C7 match, including the exact message formats, hint and help strings, signatures, `field` order, and the `_MAX_LOG_LINES` removal. `find_shortcut_conflicts(build_example_menu(...))` is `[]`. There are no unused imports.

## 1. Issues (blocking)

**1. [WP-1 + WP-2] major: a deduped `attach_logging` hands out the host's attachment, so a scoped `detach()` destroys it and `exclusive` and `level` are silently ignored.**
- **Where:** `cli_interface/app.py:428-430` (`return existing`) and `cli_interface/log_handler.py:153-205` (`LogAttachment`).
- **Reproduced in `t4.py`:**
  1. The host calls `attach_logging(app)` on root.
  2. A scoped caller (the demo pattern) calls `scoped = attach_logging(app, exclusive=True, level=logging.DEBUG)`.
  3. `scoped is host` is True. The host StreamHandler is still on root and the level is 30, so neither argument was honoured. That is the original F3 symptom of stderr output landing over the TUI.
  4. `scoped.detach()` sets `host.active` to False, and a later `logging.getLogger("x").warning(...)` never reaches the panel.
- **Why it blocks:** D4's headline is that detach "restores exactly what it changed". A deduped caller restores something it never changed. `LogAttachment` is introduced in this phase, so changing its semantics in Phase 2 would be a second break. WP-2 followed the plan as written; the plan design is the defect.
- **Fix (smallest change, per-holder idempotent):**
  - **WP-1:** add a small lease handle (about 12 lines) to `log_handler.py`.
    - It has the same public surface: `handler`, `logger`, `active`, `detach()`, `__enter__` and `__exit__`.
    - It may subclass `LogAttachment` so the annotation and `isinstance` still hold.
    - `active` is `not released and base.active`.
    - `detach()` only marks the lease released and never touches the logger.
    - Add `LogAttachment.share()` returning the lease.
  - **WP-2:**
    - On a dedup hit, return `existing.share()` instead of `existing`.
    - If that call passed `exclusive=True` or `level is not None`, issue `warnings.warn(..., UserWarning, stacklevel=2)` saying the arguments were ignored.
    - Add one docstring sentence covering both points.
    - `on_unmount` is unchanged, because it detaches the real attachments.
  - **WP-4:** no change. `capture.detach()` becomes safe.
- **Why a lease and not a ref-count:** a ref-count on a shared object cannot be idempotent per holder. `with attach_logging(app) as a: a.detach()` would release two references.
- **Plan criterion this changes:** WP-2's "returns the same object" becomes "returns a handle sharing the same `handler` and `logger`, and exactly one `TUILogHandler` is on the logger". The Tester should write it that way.

## 2. Minor (fix if cheap, none blocking)

2. **[WP-1] `log_handler.py:72`.** With `maxlen <= 0`, `_dq.popleft()` on an empty deque raises `IndexError` out of `put`, which violates "never raises" (reproduced in `t1.py`). Fix: use `if self._dq and len(self._dq) >= maxlen` or clamp with `max(1, maxlen)`.
3. **[WP-1] `log_handler.py:119-120`.** The re-entrancy guard in `_write` is dead: `put` already returns on `busy`, and `_on_wake` can't run while `busy` is set. Keep one guard. Also, `PanelInbox` has no comments on the non-obvious logic. Add 3–4 one-line notes:
   - the lock is never held across UI calls;
   - the UI thread drains the backlog before its direct write, to keep FIFO;
   - `_wake_pending` is cleared under the same lock as the emptiness check;
   - `busy` drops records that are logged while the panel is writing.
4. **[WP-1] `display.py:94-110`.** The `Text` branch of `_styled` duplicates `_as_text`, and `Text(content, style=style)` is also `_as_text(content, style)`. Reuse `_as_text`.
5. **[WP-2] `app.py:206`.** `_ = self.panel` looks like dead code. Add a one-line comment saying it primes the cached panel, since `query_one` fails once a modal is active.
6. **[WP-2] `app.py:406-433`.** `attach_logging` after the app has exited returns an active attachment that nothing detaches (reproduced in `t4.py`; a TUILogHandler stays on root). With `exclusive=True` it would strip the host's handlers permanently. Cheap option: say "UI thread, while the app is running" in the docstring. Full handling can wait for Phase 2.
7. **[WP-2] `app.py:391`, pre-existing and not a regression.** `cmd.isdigit()` followed by `int(cmd)` crashes the whole app on input like `²` (reproduced; baseline has the same lines). It is a one-token fix: `cmd.isdecimal()`. WP-2 is already editing this function.
8. **[WP-3] `menu.py:14`.** The dataclass repr includes `current_value` for a secret item (confirmed: `current_value='SECRET123'`). Fix with an explicit `__repr__` that masks the value when `secret` is true. Do not use `field(repr=False)`, which hides it for every item. This is hardening only. Textual's fatal traceback uses `show_locals=True`, so the `value` local would still print on a non-`Exception` escape. That is Phase 1 material.
9. **[WP-4] `example_menu.py:187`.** The `NoMatches` import is lazy inside `run_worker`, but only `example_worker` and `.app` need to be lazy (circular import). Move it to module top, or leave it. Optionally put `capture.detach()` and `worker_running.clear()` in nested `finally` blocks, so a failing detach can't leave the worker permanently "running".

## 3. Rulings

**A. Scoped detach vs dedup.**
- It is a real defect and it is major (issue 1).
- Fix owners: WP-1 adds the lease and `share()`; WP-2 returns it and warns on ignored arguments; WP-4 is unchanged.

**B. `#prompt-hint` has height 0.**
- Defer. It predates the phase and has no plan item.
- The fix changes the dialog layout, which WP-3's snapshot comparison does not cover.
- Log it in the phase doc for Phase 1 UI polish. The Tester should not assert hint visibility.

**C. WP-4 catching `(RuntimeError, NoMatches)`.**
- Accept.
- Textual's `call_from_thread` raises `RuntimeError` only when `app._loop is None`.
- Under `run_test` (and in the shutdown window) the callback runs, `query_one` raises `NoMatches`, and it propagates through `.result()` into the worker thread.
- The tuple is narrow and does not hide real bugs.

**D. WP-1 deviations.** Accept all six, plus the unplanned `renderable(str)` routing through `_styled`.
- 1. `highlight=not style` on `text()` preserves baseline behaviour. Baseline never highlighted styled `Text`, and did highlight plain strings and log lines.
- 2. `Text(title, style="table.title")` is needed to keep the default italic table title.
- 3. Rolling back a failed attach protects the host's handlers from `exclusive` removal.
- 4. Per-entry swallowing for the drained backlog fits D3, because only the caller's own record propagates to `emit`.
- 5. Copying consumer `Text` is correct, because `RichLog` and `Rule` mutate it.
- 6. Accepting `Text` for titles and headers is harmless widening.
- `renderable(str)` enforces H1 (no str reaches `write`).

**E. Duplicate `set_interval` timers on `super().on_mount()`.**
- Confirmed deferred under R4.
- The new `on_mount` additions are idempotent: the `panel` priming, `open()`, and the warnings pop-once. I verified this with a subclass.

Not sent back:
- Direct-path `put` exceptions reaching `emit`. D3 says they do, and the C1 "never raises" line is looser. WP-1 followed the specific clause.
- A second `run_test` on the same `CLIApp` instance raising `WaitForScreenTimeout`. The baseline package fails identically, so it is a Textual limitation, not a regression.
- The `smoke_test` FAILs, which the plan predicted.

## 4. Holistic notes

- **Overall:** the phase is in good shape. The four packages fit together with no contract drift. The `Text`-everywhere approach holds up under real-app testing.
- **`PanelInbox` verified:**
  - I found no lock held across UI code, no lost wakeup, and no deadlock.
  - The `_wake_pending` clear and the emptiness check share one lock acquisition.
  - A budgeted reschedule keeps `_wake_pending` set.
  - `open` followed by a concurrent put is safe.
  - `close` is terminal.
  - The loop reference is captured under the lock.
  - Exceptions in the scheduled drain are swallowed.
  - The UI-thread identity is captured at `open`.
  - Exit and crash teardown are clean.
- **Only real defect:** the dedup/detach semantics in issue 1.
- **Residual behaviours to document, not fix:**
  - Direct `panel.log` calls (`Executed:`, `Unknown command` and the demo's `p.log`) bypass the inbox. FIFO is guaranteed only among `push_log` records. Phase 2's `emit` resolves this.
  - A UI-thread drain happens inside `Handler.handle`'s handler lock, so a worker's `logging` call can stall up to about 0.8 s if the UI is already far behind (R5). It is not a deadlock.
  - `RESERVED_COMMANDS` in `menu.py` and the inline tuples in `app.py` duplicate each other. They match today, and a consistency test will keep them aligned.
  - Single-line gaps: the `set_token` demo logs the token length, which is not a secret leak.

## 5. Test focus for the Tester

1. **Lease semantics after the issue 1 fix:**
   - host attach, then scoped attach with `exclusive` and `level`: the `UserWarning` fires, there is one `TUILogHandler`, and the scoped `detach()` leaves the host active and still capturing;
   - double `detach()` and nested `with` on a lease;
   - the owner detaches first, so the lease's `active` is False;
   - everything is torn down at app exit.
2. **Overflow:** a blocked loop with `_INBOX_MAXLEN` monkeypatched small. Assert at most `cap` records plus exactly one dropped notice, placed first, with `dropped` exact. Also `maxlen=0` and `1`, and a pre-`open` overflow.
3. **Post-exit:**
   - a worker that keeps logging after exit, under both `run_test` and a real `run(headless=True)`, with zero `handleError` calls, zero thread excepthooks and no handler left;
   - a subclass `on_unmount` that logs;
   - logging during teardown.
4. **Concurrency:**
   - FIFO under multi-thread stress plus UI-thread puts;
   - a UI `join(timeout)` on a logging worker;
   - the re-entrancy guard (a record logged from within `panel.log`);
   - `call_soon_threadsafe` raising `RuntimeError`.
5. **F4:**
   - a secret value absent from every panel line, including a long run;
   - redaction when the value appears inside an error message;
   - redaction when the exception message has a different escaping (best effort);
   - an empty value;
   - the masked `Input.password`;
   - the NavBar mask and its width;
   - `MenuItem` repr after fix 8.
6. **F1:** the hostile-string matrix across all surfaces, with `return_code is None`. Include `markup=True` opt-in plus its invalid-markup fallback, and `Text` pass-through with its style kept.
7. **F8:**
   - case-insensitive reserved commands;
   - `q`/duplicate warnings plus the panel line, and no duplicate when `on_mount` runs twice;
   - `strict_shortcuts`;
   - `press("d")` alone does nothing;
   - no `on_key`;
   - a drift test between `RESERVED_COMMANDS` and the app's handlers.
8. **Demo:**
   - worker scoping with a sentinel host handler and level;
   - the double-start guard;
   - closing the app mid-run, with the test yielding to the loop (`await asyncio.sleep`) rather than `time.sleep`;
   - `import main` leaves root untouched;
   - `Set Token` shows no value.
9. **Regression:**
   - positional `MenuItem` and `PromptScreen`;
   - `attach_logging` old call forms (`app`, `app, logger`, `exclusive=True`);
   - a subclass overriding `on_mount` with and without `super()`.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/example_menu.py