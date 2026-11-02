## WP-1 report (output pipeline)

WP-1 is implemented as specified, with a few small deviations listed in section 3. My 84 scratch checks all pass. Do not run any real-app probe until WP-2 lands (see section 4).

### 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py`: `DisplayPanel` now builds `Text` objects instead of markup strings, and every `log()` is a single `write()`. The fade, log buffer and `_log_only` are gone.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py`: rewritten with `PanelInbox`, `TUILogHandler` and `LogAttachment`.

No other file was touched. No git state was changed.

### 2. Changes, mapped to findings and plan steps
**`display.py`**
- **Steps 1-3, 9 (F6):**
  - The `_MAX_LOG_LINES` import is dropped.
  - `_log_buffer`, `_log_only`, `_render_log_buffer` and the fade logic are deleted. This includes the `_log_only` lines in `rule`, `text`, `csv` and `renderable`.
  - `clear()` keeps the `_w.clear()`, `_scrolled_to_top = False` and `auto_scroll = True` lines.
  - `_enter_content_mode` only sets `auto_scroll = False`.
- **Steps 4-6 (F1, D1, C7):**
  - New `log(message: str | Text, level="INFO", *, markup=False)`.
  - New `text(content: str | Text, style="", *, markup=False)`.
  - Both go through the private `_styled(content, style, markup, highlight=True)`:
    - A `Text` input is copied, with the level style applied via `stylize_before`. It is not highlighted.
    - `markup=True` uses `Text.from_markup(msg, style=...)` and falls back to plain `Text` on `MarkupError`.
    - Otherwise the result is plain `Text(msg, style=...)`.
    - Plain and markup strings go through the highlighter. It is skipped when `w.highlight` is false or `w.highlighter` is missing (`getattr` guard).
- **Steps 7-8 (F1 surfaces):**
  - Module helpers `_as_text`, `_title` and `_cell` were added.
  - Titles for `rule`, `json`, `array` and `pretty` are wrapped as `Text`.
  - Table title and column headers (including CSV headers) are wrapped as `Text`.
  - A cell that is a `str` or not renderable becomes `Text(str(v))`. Any other Rich renderable, such as a `Text` cell, passes through.
- **Not in the plan:** `renderable(str)` now goes through `_styled`, so it never sends a raw `str` to `write()`. Other objects pass through unchanged.
- **Step 10:** the class docstring is trimmed. It notes that methods are UI-thread-only and that `CLIApp.push_log` is the thread-safe entry.

**`log_handler.py`** (C1, D3, D4)
- **`PanelInbox`** follows D3:
  - State machine `new -> open -> closed`, guarded by one lock that is never held during UI calls.
  - `open(loop)` captures the loop and UI thread ident, and wakes immediately if a backlog exists.
  - `put()` is a silent no-op when closed.
  - On the UI thread while open, `put()` drains the backlog (and any dropped notice) in FIFO order and then writes directly.
  - Otherwise `put()` enqueues. On overflow it uses `popleft`, `dropped += 1` and `_dropped_pending += 1`. It schedules one `call_soon_threadsafe(_on_wake)`, and a `RuntimeError` closes the inbox.
  - `_on_wake` drains with a 15 ms budget and reschedules with `call_soon`. It emits the `"<n> log record(s) dropped (UI busy)"` WARNING line before the surviving entries. It checks emptiness and clears `_wake_pending` under the same lock acquisition.
  - A thread-local re-entrancy guard sits at the top of `put()` and again in `_write`.
  - `_INBOX_MAXLEN` is read at `put` time.
- **`TUILogHandler`** has `detached`, `detach()` and `emit`. `emit` calls `app.push_log(msg, levelname)`, is a no-op once detached, and calls `handleError` on `Exception`. The formatter is unchanged.
- **`LogAttachment`** follows D4:
  - `logger=None` means root, tested with `is None`.
  - `exclusive` removes the host's handlers and remembers only those in `_removed`.
  - `level` stores the previous level and the value read back after `setLevel`, with a separate "changed" flag.
  - `detach()` is lock-guarded and idempotent. It re-adds only the removed handlers that are not already present, skips detached `TUILogHandler`s, and restores the level only if the logger still holds the value this attachment set.
  - The class also provides `active`, `__enter__` and `__exit__`.

### 3. Deviations and extras
1. `_styled` has a private `highlight` keyword. `text(..., style=...)` passes `highlight=not style`, which keeps the old behaviour of not colouring numbers or strings over an explicit style. Plain `text()` and `log()` are highlighted.
2. The table title is `Text(title, style="table.title")`, not a bare `Text`. A segment comparison showed a bare `Text` loses the default italic. A `Text(title)` rule title renders identically to the old `str` title (also compared), so no style was needed there.
3. `LogAttachment.__init__` rolls back if attaching fails, for example on a bad `level=` after `exclusive` has removed handlers. Otherwise the host's handlers would be lost. This goes beyond the plan.
4. On the UI-thread path, backlog entries and the dropped notice are written with per-entry exception swallowing. Only the caller's own record propagates to `emit` and then `handleError`, as D3 says.
5. Consumer `Text` objects are copied (log/text output, titles, headers), because `RichLog` calls `expand_tabs` in place and `Rule` mutates its title.
6. `_title` and `_as_text` also accept a `Text` for titles and headers, so `str | Text` works.

### 4. Cross-package requests and notes
- No edits are needed in files I don't own.
- **Landing order:**
  - The on-disk `app.py` still has the old `push_log`, which calls `self.panel.log(...)` directly. The new `TUILogHandler.emit` calls `app.push_log` with no `call_from_thread` hop. Until WP-2 routes `push_log` to `self._inbox.put`, a background-thread log record would write to the `RichLog` off the UI thread.
  - WP-1 and WP-2 must land together. Real-app probes such as exp1 and exp7 are not meaningful until then.
  - WP-2 must also set `RichLog(markup=False)` together with this change (H1).
- WP-2 must call `inbox.open(asyncio.get_running_loop())` from the UI thread only after `app.panel` has been created and cached.
- The full package import (`cli_interface.app`) succeeded on the final tree, with WP-3's edits present.

### 5. Acceptance criteria
`uv run python -c "import cli_interface.display, cli_interface.log_handler"` passes.

All checks are in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp1/verify.py`, which the Tester can port. It runs 84 checks and all pass. It uses a bare Textual `App` with a `RichLog(highlight=True, markup=False, wrap=True)` and a stub `push_log`, and it never imports `app.py`. `cmp_rich.py` in the same directory holds the Rich style comparison for rule and table titles.

- **F1:**
  - All five verbatim samples survive `log`, and `markup=True` gives `hi`.
  - Invalid markup falls back to text, and `text("[/x]", style="bold")` is literal.
  - The `[/y]` title works in `rule`, `json`, `array`, `pretty`, `table` and `csv`.
  - A table cell `[/w]` and header `h[i]` are literal. A `Text` cell keeps its bold red style.
  - A spy on `RichLog.write` saw no `str` argument, including for `renderable(str)`.
  - Highlighting still colours numbers and strings, an invalid style string does not crash, and consumer `Text` is not mutated.
- **F6:**
  - N logs gave exactly N `write()` calls.
  - `max_lines=50` held in both log mode and content mode.
  - Direct write ran at about 12.5k rec/s on a 120x40 pilot.
  - `_log_buffer`, `_render_log_buffer` and `_log_only` no longer exist.
- **F2:**
  - A UI-thread `put` is visible immediately and after a pause.
  - 10k puts from a thread with the loop blocked took about 5 ms.
  - Per-thread FIFO order holds across 3 threads.
  - With `maxlen=100` and a blocked loop (1000 puts): 100 records, exactly one `"900 log record(s) dropped (UI busy)"` line placed first, `dropped == 900`, and the survivors are the newest.
  - Monkeypatching `_INBOX_MAXLEN` is honoured.
  - A UI-thread `put` with a backlog drains it first in FIFO order, with no duplicates after the wake.
  - A UI `join(timeout=5)` on a worker logging 1000 records finishes, and all 1000 records show.
  - Puts before `open` are buffered and shown in order, including one from a background thread.
  - After `close()`, `put` is a silent no-op with no exception and no `handleError`, and the closed state is terminal.
  - A closed loop (`RuntimeError`) closes the inbox cleanly, and `open()` twice is harmless.
  - A re-entrant record is dropped (no recursion) on both the direct and scheduled paths.
  - The scheduled drain swallows write errors, and a direct-path error reaches `handleError`.
  - The default-cap check delivered all 10k records, which also exercises the budgeted reschedule.
- **F3:**
  - For both a named logger and root, with `exclusive` false and true, handlers and level are identical after `detach()`.
  - `detach()` is idempotent, and 16 concurrent detaches restore once.
  - A host handler added mid-attachment survives.
  - A level the host changed is not clobbered, and NOTSET (0) restores correctly.
  - String levels work, and a bad level rolls back.
  - Detached handlers are not resurrected by nested exclusive attachments.
  - `with` works, `emit` after detach is a no-op, and `logger=None` means root.
  - Queued records still render after `detach()`.

**Not verified:**
- C2 against the real `CLIApp.push_log`, because WP-2 is not in the tree. I used a stub that calls `inbox.put`.
- The real-app probes (exp1, exp2, exp7, typed_markup_test, edge_test). They need WP-2 and are meant for the post-merge smoke run.