# Phase 0 plan: F1, F2, F3, F4, F6, F8, `main.py`, demo

All paths are under `/Users/andrewmacleod/workspace/cli_interface`. Baseline is `fdb8069` on branch `phase-0`. `whiteboard.py` is out of scope.

I reproduced the bugs on Textual 8.2.8 and used the results below to shape the design:

- `exp1` and `exp3b` show `handleError` tracebacks and a record from a background thread that never reaches the panel.
- `exp7` baseline: 135 rec/s and 20,103 `RichLog.write` calls for 300 records via `TUILogHandler`, versus 377k rec/s for a queued handler.
- `NavBar` crashes with `MarkupError` on a label like `Run [/x]` or a `current_value` like `[/v]`. This is the same bug class as F1, in the widgets.
- `Rule("a [/x] b")` raises `MarkupError`. `Table` titles, headers and cell strings are also markup-parsed: `m[i][j]` is mangled and `[/z]` crashes.
- `rich.markup.escape` and `textual.markup.escape` both mangle a backslash next to `[`. `C:\data\[/tmp]` renders as `C:\data\\[/tmp]`, and `x\[y` loses its backslash. Rich `Text` objects and `Label(markup=False)` render every sample exactly.
- `phrases.py` contains no markup, so converting Dashboard/status to `Text` is safe.
- `on_unmount` fires on the App both under `run_test` and under `run(headless=True)`.
- A subclass `on_mount` runs before `CLIApp.on_mount`. When a subclass calls `super().on_mount()`, the base handler runs twice, so anything I add to `on_mount` must be idempotent.
- `press("d")` fires nothing, but `press("d","enter")` works, so `CLIApp.on_key` is confirmed dead code.
- Typed `Q` currently falls through to a consumer shortcut `q`, because the reserved check is case-sensitive.
- Direct `RichLog.write(Text)` runs at about 13k rec/s with the highlighter and 23k without. `max_lines` trimming works. `RichLog.highlighter(Text)` returns a copy, not the same object.

---

## 1. Design decisions

### D1. F1: build `Text` objects. Do not use `escape()`.

Hard rules, shared by WP-1, WP-2 and WP-3:

- **H1.** `display.py` never passes a markup string to `RichLog.write()`.
  - It always writes `rich.text.Text` or another Rich renderable.
  - In the same change, `app.py` sets `RichLog(markup=False)`.
  - Without H1, flipping the flag alone would show raw tags everywhere.
- **H2.** No package calls `escape()` on consumer strings. Surfaces and fixes:

| Surface | Fix |
|---|---|
| `DisplayPanel.log` and `text` | Write `Text`. Markup is opt-in per call (`markup=True`). |
| `Rule` titles (`rule`, `json`, `array`, `pretty` titles) | `Rule(Text(title))` |
| `Table` title, column headers (including CSV headers), cells | Wrap as `Text`. Cells that are already `Text` or other Rich renderables pass through unchanged. |
| `PromptScreen` title and prompt Labels | `Label(..., markup=False)` |
| `NavBar` labels, shortcuts, `current_value` | `render()` returns `Text` |
| `Dashboard` crumbs and spinner label | `render()` returns `Text` |

`_HINT_TEXT` and the `PromptScreen` hint Label contain only framework-authored theme markup, so they keep their markup.

**Display-panel details (WP-1):**

- Keep `RichLog(highlight=True)` in `app.py`.
- For `Text` output, call the highlighter explicitly: `t = w.highlighter(t)`, using the returned copy. Skip it when `w.highlight` is false, and guard with `getattr(w, "highlighter", None)`. Otherwise log lines lose their number and string colouring.
- A consumer-supplied `Text` is passed through as a copy with the level style applied underneath via `stylize_before`. It is not highlighted.
- `markup=True` calls `Text.from_markup(msg, style=...)`. On `rich.errors.MarkupError` it falls back to plain `Text(msg)`. A bad opt-in must never kill the UI.

### D2. F6: drop the fade and bound the RichLog

- Remove the log-mode buffer, `_render_log_buffer`, the `_log_only` flag and the per-record re-render.
- `log()` is always one `write()` call.
- The fade is dropped, not simplified. It styled the two oldest entries of a 100-entry window, which are scrolled off-screen under auto-scroll. Restyling stored `Strip`s is impossible without re-rendering, which is the cost F6 removes.
- `CLIApp` creates the RichLog with `max_lines=self._max_lines`, which defaults to 5000. This applies in log and content modes.
- `CLIApp.__init__` gains a keyword-only `max_lines`, so a huge table or JSON dump can raise the cap.
- The `auto_scroll` / `scroll_home` / `ensure_latest_visible` behaviour is unchanged.

### D3. F2: one app-level, thread-safe, bounded inbox

Log records from any source go through a single per-app inbox. This preserves ordering across handlers and is the stepping stone for Phase 2. In Phase 2:

- Entries widen from `(message, level)` to Event objects.
- `_write` becomes `panel.emit(event)`.
- `Context.log` calls `CLIApp.push_log`.

`CLIApp.push_log` is now callable from any thread. `TUILogHandler` is thin.

```python
# cli_interface/log_handler.py   (WP-1 provides; WP-2 consumes)
_INBOX_MAXLEN = 10_000          # module constant; tests may monkeypatch before constructing the app

class PanelInbox:
    dropped: int                                   # cumulative dropped-record count
    def __init__(self, app: "CLIApp", maxlen: int | None = None) -> None   # None -> _INBOX_MAXLEN read at call time
    def open(self, loop: asyncio.AbstractEventLoop) -> None   # UI thread only, idempotent
    def close(self) -> None                                    # any thread, idempotent, terminal
    def put(self, message: str, level: str = "INFO") -> None   # any thread, never blocks, never raises
```

**State machine:** `new -> open -> closed`. It is guarded by one `threading.Lock`, which is never held while calling UI code.

**`open(loop)`:**

- Captures `self._loop = loop` and `self._ui_ident = threading.get_ident()` at open time.
- Never reads `app._loop` or `app._thread_id`. Both are reset at exit.
- If a backlog exists, sets `_wake_pending = True` and calls `loop.call_soon(self._on_wake)`.

**`put()` decision, made under the lock:**

1. `closed`: return, a silent no-op.
2. `open` and `get_ident() == _ui_ident` (UI path):
   - Drain the whole backlog synchronously.
   - Then call `app.panel.log(message, level)` directly.
   - This keeps FIFO order and makes "UI-thread records are written directly" true in every case.
   - The drain is bounded by maxlen, so the worst case is a one-off stall of about 0.8 s. This only happens when the UI is already behind.
3. Otherwise (a non-UI thread, or state `new`, which includes UI-thread calls before mount) the record is enqueued:
   - Under the lock: if `len(dq) >= maxlen`, then `dq.popleft()`, `dropped += 1` and `_dropped_pending += 1`. After that, `append`.
   - Use a plain `deque`, not `deque(maxlen)`, so the drop counter is exact.
   - If `open` and no wake is pending, set `_wake_pending = True`.
   - Then call `loop.call_soon_threadsafe(self._on_wake)` outside the lock. On `RuntimeError` (loop closed), mark the inbox closed.

**`_on_wake()` (UI loop):**

- Drain with a time budget of about 15 ms.
- If entries remain, reschedule with `loop.call_soon(self._on_wake)` and leave `_wake_pending` set.
- Check emptiness and clear `_wake_pending` in the same lock acquisition, so a wakeup is never lost.
- If `_dropped_pending` is non-zero, first write `"<n> log record(s) dropped (UI busy)"` at WARNING, then reset the counter.

**Write path:**

- `_write` wraps the `panel.log` call in a thread-local re-entrancy guard. A re-entrant record is dropped, which prevents recursion.
- In the scheduled drain, `_write` swallows `Exception`. Never let an exception reach asyncio's logger, which would route back into the handler.
- On the direct UI path, exceptions propagate to `emit`.

**`close()`:** sets closed, clears the queue and drops the loop reference.

```python
class TUILogHandler(logging.Handler):
    def __init__(self, app: "CLIApp") -> None            # signature unchanged; same Formatter as today
    @property
    def detached(self) -> bool
    def detach(self) -> None                             # idempotent; later emit() is a no-op
    def emit(self, record: logging.LogRecord) -> None    # format -> app.push_log(msg, record.levelname); Exception -> handleError
```

### D4. F3: detach handle that restores exactly what it changed

```python
class LogAttachment:                                     # log_handler.py (WP-1)
    handler: TUILogHandler
    logger: logging.Logger
    def __init__(self, app: "CLIApp", logger: logging.Logger | None = None, *,
                 exclusive: bool = False, level: int | str | None = None) -> None   # attaches immediately
    @property
    def active(self) -> bool
    def detach(self) -> None                             # idempotent, lock-guarded, callable from any thread
    def __enter__(self) -> "LogAttachment"
    def __exit__(self, *exc: object) -> None             # calls detach()
```

**Attach behaviour:**

- `logger=None` means the root logger, tested with `is None`.
- `exclusive=True` removes the host's handlers via `removeHandler` and remembers only the ones it removed in `_removed`.
- `level` is not `None`: `logger.setLevel(level)`, remembering the previous level and the value it set.
- Then `addHandler(handler)`.

**Detach behaviour:**

- Run once. Call `handler.detach()`, `removeHandler(handler)` and `handler.close()`.
- Re-add only the handlers in `_removed` that are not already on the logger, in original order. Skip any `TUILogHandler` that is `detached`, so nested exclusive attachments cannot resurrect dead handlers.
- Never restore a snapshot of the handler list. A handler the host added during the attachment must survive.
- Restore the level only if `logger.level` still equals the value this attachment set.
- Queued-but-undrained entries are not lost on detach, because they live in the app inbox.

**App-level behaviour:**

- `attach_logging(app, logger=None, *, exclusive=False, level=None) -> LogAttachment`.
- **Dedup rule:** if `app` already has an active attachment for the same logger object, return that attachment unchanged and ignore the new arguments. This prevents stacked duplicate handlers and duplicate lines. Different app instances get separate handlers.
- `CLIApp` keeps `self._attachments`. `on_unmount` calls `self._inbox.close()` and then `detach()` on each attachment in reverse order. A host's handlers come back automatically at exit.

### D5. F4: no echo, secret prompts

- `MenuItem.secret: bool = False` is appended as the last dataclass field, so positional compatibility is kept.
- `PromptScreen(item_label, prompt, *, secret=False)` creates `Input(password=secret)`.
- **"Executed:" line:** it is now `Executed: <label>` for all prompted items, with no value echo. For `secret=True` items the `→ result` suffix is also suppressed.
- **Error line:** for secret items, occurrences of the value in `str(exc)` are replaced with `***`, best effort.
- The `NavBar` shows `••••` instead of `current_value` for `secret=True` items, and uses the same width in the layout estimate.

### D6. F8: shortcuts

**Single-key shortcuts: stop advertising them.**

- The `Input` consumes the keys.
- Instant firing would collide with typed commands (`clear`, `help`, `exit`, `back`, `quit`) and with multi-digit positions, and some shortcuts would be instant while others needed Enter.
- Typed shortcut plus Enter already works.
- Delete the dead `CLIApp.on_key`.

**Exact wording (the two packages must agree).**

- `theme.py` `_HINT_TEXT`, line 1 tail:
  - `type a shortcut or command` becomes `type a shortcut + Enter`.
  - The visible width goes from 85 to 82 characters. Do not make it longer.
- `app.py` `_show_help` rows:
  - `{"Key / Command": "<shortcut> + Enter", "Action": "Activate item by its shortcut (shown in yellow)"}`
  - `{"Key / Command": "<number> + Enter", "Action": "Activate item by position"}`
  - These replace the old `<letter>` and `1 … 9` rows. All other rows stay.

**Reserved commands.** `RESERVED_COMMANDS = {q, quit, exit, b, back, clear, help, ?}`.

- Matching is now case-insensitive, via `cmd.lower()`. This is consistent with `select_by_shortcut`, which already lower-cases.
- Reserved commands win over consumer shortcuts. The first duplicate wins, as today.

**Warn, don't raise, by default.**

- A collision is degraded, not broken. The outcome is deterministic, and the item stays reachable by arrows, Enter and its position number.
- Raising would break the user's existing apps at startup. `whiteboard.py` uses `q` for Quick Run (W6), and it is out of scope this phase.
- Opt-in strictness: `CLIApp(menu, strict_shortcuts=True)` raises `ValueError("\n".join(problems))` before `super().__init__()`.
- Otherwise:
  - Each problem is emitted with `warnings.warn(msg, UserWarning, stacklevel=2)` at construction.
  - Because warnings are invisible once the TUI owns the screen, each problem is also logged to the panel at WARNING on first mount. Use a pop-once pattern, since `on_mount` can run twice.
- Revisit the default (flip to raise) in Phase 1.

```python
# menu.py
RESERVED_COMMANDS: frozenset[str]
def find_shortcut_conflicts(root: MenuItem) -> list[str]
```

- It walks the whole tree, with a visited-set cycle guard.
- It lower-cases shortcuts and skips empty ones.
- `path` is the labels from the root to the menu, joined with `" > "`.
- Message formats (tests should match substrings):
  - Duplicate: `f"{path}: shortcut {key!r} is used by {', '.join(map(repr, labels))}; only the first is reachable by shortcut"`
  - Reserved: `f"{path}: shortcut {key!r} on {label!r} is a reserved command and will never reach this item"`
  - `key` is the lower-cased shortcut.

### D7. Cross-package contracts

| # | Provider | Consumer | Contract |
|---|---|---|---|
| C1 | WP-1 `log_handler.py` | WP-2 | `PanelInbox`, `LogAttachment`, `TUILogHandler` exactly as in D3 and D4 |
| C2 | WP-2 `CLIApp.push_log(message, level="INFO")` | WP-1 `TUILogHandler.emit` | Any thread; delegates to `self._inbox.put` |
| C3 | existing | WP-1 `PanelInbox` | `CLIApp.panel` and `DisplayPanel.log(message, level)` (signature unchanged) |
| C4 | WP-3 `menu.py` | WP-2, WP-4 | `MenuItem.secret`, `RESERVED_COMMANDS`, `find_shortcut_conflicts` |
| C5 | WP-3 `widgets.py` | WP-2 | `PromptScreen(item_label, prompt, *, secret=False)` |
| C6 | WP-2 `attach_logging(...) -> LogAttachment` | WP-4 | See D4 |
| C7 | WP-1 `display.py` | all | Markup is off by default. `log(..., *, markup=False)` and `text(..., *, markup=False)` are keyword-only additions. |

**The old constant `_MAX_LOG_LINES`:**

- Today it is defined at `theme.py:18` and imported only at `display.py:15`.
- WP-3 deletes it from `theme.py`. WP-1 removes the import from `display.py`.
- There is no replacement in `theme.py`.
- WP-2 defines `_DEFAULT_MAX_LINES = 5000` locally in `app.py`.
- Nobody imports a name another package is about to add or remove, so any completion order works.

### D8. Demo and `main.py`

- Remove `logging.basicConfig(level=logging.DEBUG)` from `main.py`.
- In `example_menu.run_worker`:
  - Attach for the duration of the worker run with `attach_logging(app, exclusive=True, level=logging.DEBUG)`.
  - Detach in the thread's `finally`.
  - Guard against a double start with a `threading.Event`.
  - Remove `root.setLevel(...)` and the unused `TUILogHandler` import.
  - Guard `call_from_thread(app.stop_spinner)` against `RuntimeError`, which is raised if the app has already exited.

---

## 2. Behaviour changes users will notice

1. **Markup is off by default.**
   - `panel.log("[red]x[/]")` and `panel.text(...)` show literal brackets.
   - Opt in with `markup=True`, or pass `rich.text.Text`.
   - Table cells, headers and titles, rule titles, `json`/`array`/`pretty` titles and typed commands are literal.
   - `RichLog` itself is created with `markup=False`.
   - Previously `[/x]` crashed or mangled output (`matrix[i][j]`, Windows paths).
2. **Menu labels, shortcuts, `current_value`, prompt title and prompt text, and breadcrumbs are literal.**
   - A consumer who deliberately put markup in a label (`"[bold]Run[/]"`) now sees the literal tags. See open question Q2.
3. **The "Executed:" line no longer echoes prompt values.**
   - For secret items, the result and any matching text in an exception message are also suppressed or redacted.
4. **`MenuItem(secret=True)`** masks the prompt input and the `current_value` in the nav bar. This is new.
5. **Reserved commands are case-insensitive.**
   - `Q`, `Quit`, `HELP`, `B` and `Clear` now work.
   - Previously `Q` could trigger a consumer shortcut `q`.
6. **Single-key shortcuts** (a shortcut key without Enter) never worked.
   - The hint and help now say "shortcut + Enter".
   - `CLIApp.on_key` is removed.
7. **The fade of the oldest log entries is gone.** It was invisible in practice.
8. **Scrollback limits changed.**
   - Log mode used to keep 100 entries and now keeps 5000 lines, set by `CLIApp(menu, max_lines=...)`.
   - Content mode (json, table, etc.) used to be unbounded and now keeps the last 5000 lines. Larger dumps lose their head.
9. **`CLIApp.push_log` is safe to call from any thread.**
   - Worker records never block on the UI and cannot deadlock.
   - The inbox is bounded at 10k entries. Overflow drops the oldest and adds one "N log record(s) dropped" WARNING line.
10. **UI-thread log records are written immediately instead of raising `RuntimeError`.**
    - Records logged before mount are buffered and shown on mount.
    - After the app exits, handlers are silent. There is no `handleError` spam.
11. **`attach_logging` returns a `LogAttachment`** (it returned `None`). Callers that ignore the return value still work.
    - It gained an optional `level=`.
    - Attachments auto-detach at app exit, and `exclusive=True` restores the host's handlers.
    - A second attach for the same app and logger returns the existing attachment, ignoring the new arguments, instead of stacking a duplicate handler.
12. **Shortcut conflicts** (reserved or duplicate) emit a `UserWarning` at `CLIApp(...)` construction and a WARNING line in the panel at mount.
    - `strict_shortcuts=True` raises `ValueError`.
13. **`main.py` no longer configures DEBUG logging.**
14. **The demo's worker run** attaches exclusively only while the worker runs, then restores the root logger's handlers and level.
15. **`CLIApp.__init__`** gains keyword-only `strict_shortcuts` and `max_lines`.
    - Previously only `menu` and `**kwargs` were accepted, so there is no positional break.

---

## 3. Work packages

File ownership is disjoint:

| WP | Files |
|---|---|
| WP-1 | `cli_interface/display.py`, `cli_interface/log_handler.py` |
| WP-2 | `cli_interface/app.py` |
| WP-3 | `cli_interface/menu.py`, `cli_interface/widgets.py`, `cli_interface/theme.py` |
| WP-4 | `main.py`, `cli_interface/example_menu.py` |

No `__init__.py`, `pyproject.toml` or `example_worker.py` changes.

All four can run in parallel because the contracts are fixed. Each executor codes against the contracts and must not edit another package's files. If a contract is not yet in the tree, verify with a local stub and report. The orchestrator should re-run the WP-2 and WP-4 smoke checks once WP-1 and WP-3 have landed.

Executors keep comments and docstrings minimal.

### WP-1: output pipeline (F1 display side, F2, F3 core, F6 display side)

**Owns:** `cli_interface/display.py`, `cli_interface/log_handler.py`.

**Provides:** C1, C7.

**Consumes:** C2 (`app.push_log`) and C3 (`app.panel.log`). Verify with a stub app object that exposes `.panel.log` and `.push_log`, plus a bare Textual `App` hosting a `RichLog`. Do not depend on WP-2.

**`display.py` steps** (anchors are the original lines):

1. L15: drop `_MAX_LOG_LINES` from the import. Keep `LEVEL_STYLES`, `_DIM_FG`, `_ORANGE`.
2. L42-53: delete `_log_buffer` and `_log_only`. `clear()` keeps `_w.clear()`, `_scrolled_to_top = False` and `auto_scroll = True`.
3. L58-61: `_enter_content_mode` only sets `auto_scroll = False`.
4. L83-118: delete `_render_log_buffer` and the buffer logic. `log()` becomes:
   - `log(self, message: str | Text, level: str = "INFO", *, markup: bool = False) -> None`
   - It is one `self._w.write(self._styled(message, LEVEL_STYLES.get(level.upper(), ""), markup))`.
5. Add a private helper `_styled(content, style, markup) -> Text` implementing the D1 rules: `Text` pass-through copy, markup opt-in with `MarkupError` fallback, explicit highlighter call.
6. L128-134: `text(self, content: str | Text, style: str = "", *, markup: bool = False)` goes through `_styled`.
7. Titles: `rule`, `json`, `array`, `pretty` and `table(title=...)` use `Rule(Text(title), ...)` or `Table(title=Text(title))`.
8. L158-181:
   - Column headers become `Text(str(col))`.
   - A cell that is a `str`, or is not renderable (`not rich.protocol.is_renderable(v)`), becomes `Text(str(v))`. Any other Rich renderable passes through.
9. Remove every remaining `self._log_only = ...` line (L125, L130, L186, L212).
10. Trim the stale class docstring about fade and log mode, keeping it minimal. Note that `DisplayPanel` methods are UI-thread-only and that the thread-safe entry is `CLIApp.push_log`.

**`log_handler.py` steps:** rewrite the file (22 lines today) with `from __future__ import annotations`, `_INBOX_MAXLEN`, `PanelInbox`, `TUILogHandler` and `LogAttachment`, exactly as specified in D3 and D4.

**Acceptance criteria:**

- **F1**
  - `log` of each of these shows the text verbatim and raises nothing: `"matrix[i][j] = 3"`, `"closing [/x] tag"`, `"C:\\data\\[/tmp]"`, `"x\\[y"`, `"[bold]x[/bold]"`.
  - `log("[bold]hi[/bold]", markup=True)` shows `hi`.
  - `log("bad [/x]", markup=True)` does not raise and shows the text.
  - `text("[/x]", style="bold")` is literal.
  - The `title=` of `rule`, `json`, `array`, `pretty` and `table` accepts `"[/y]"`.
  - A table cell `"[/w]"` and a header `"h[i]"` are literal. A `Text` cell keeps its style.
  - No `write()` call receives a markup string (H1).
- **F6**
  - After N log calls, `RichLog.write` was called exactly N times.
  - With `max_lines=M`, `len(lines) <= M`.
  - Direct write throughput is well above 2,000 rec/s on a 120x40 pilot.
  - `_log_buffer` and `_render_log_buffer` do not exist.
- **F2**
  - From the UI thread with an empty backlog, `put` is visible after a single `pilot.pause()`.
  - `put` from background threads, even with the loop blocked, never blocks: 10k puts in under 1 s.
  - Entries arrive in FIFO order across threads.
  - With `maxlen=100` and a blocked loop, the result is at most 100 entries plus exactly one dropped-notice line, and `inbox.dropped` is correct.
  - A UI-thread `put` with a backlog drains the backlog first, so the ordering is preserved.
  - A UI-thread `join()` on a worker that is logging 1000 records finishes (no deadlock).
  - `put` before `open()` is buffered and shown in order after `open()`.
  - After `close()`, `put` is a silent no-op: no exception and no `handleError`.
  - `call_soon_threadsafe` raising `RuntimeError` closes the inbox cleanly.
  - Calling `open()` twice is harmless.
- **F3**
  - Before and after `exclusive=True` plus `detach()`, the logger's handlers and level are the same.
  - A handler the host added mid-attachment survives `detach()`.
  - The level is restored only if it is still the value the attachment set.
  - `detach()` is idempotent, thread-safe and also works via `with`.
  - `emit` after `detach` is a no-op.

### WP-2: the app (F1 wiring, F2/F3 wiring, F4 app side, F6 compose, F8 app side)

**Owns:** `cli_interface/app.py`.

**Provides:** C2, C6, `CLIApp.__init__(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)` and `on_unmount`.

**Consumes:** C1, C4, C5, C7. Build against the contracts and verify once WP-1 and WP-3 are in the tree.

**Steps** (anchors are the original lines):

1. **Imports (L1-19).** Add `asyncio` and `warnings`. Import `LogAttachment` and `PanelInbox` from `.log_handler`, and drop `TUILogHandler`. Import `find_shortcut_conflicts` from `.menu`. Add `_DEFAULT_MAX_LINES = 5000`.
2. **`__init__` (L94-103).**
   - New signature: `(self, menu: MenuItem, *, strict_shortcuts: bool = False, max_lines: int = _DEFAULT_MAX_LINES, **kwargs: Any)`.
   - Before `super().__init__`: `problems = find_shortcut_conflicts(menu)`.
   - If `strict_shortcuts` and there are problems: raise `ValueError("\n".join(problems))`.
   - Otherwise issue `warnings.warn(p, UserWarning, stacklevel=2)` for each problem, and keep them in `self._menu_warnings`.
   - After `super().__init__`: set `self._inbox = PanelInbox(self)`, `self._attachments: list[LogAttachment] = []` and `self._max_lines`.
3. **`compose` (L166-172).** `RichLog(id="display-panel", highlight=True, markup=False, wrap=True, auto_scroll=True, max_lines=self._max_lines)`. This must land together with WP-1's H1.
4. **`on_mount` (L181-184).** Keep the existing lines. Then:
   - `_ = self.panel`, to prime the cached `DisplayPanel`.
   - `self._inbox.open(asyncio.get_running_loop())`.
   - Log each `self._menu_warnings` entry at WARNING, then clear the list. This must be idempotent: `on_mount` can run twice via `super().on_mount()`.
5. **New `on_unmount`.** Call `self._inbox.close()`, then `detach()` each of `reversed(self._attachments)`, then clear the list.
6. **`push_log` (L189-190).** `self._inbox.put(message, level)`. Add a one-line docstring saying it is callable from any thread.
7. **`_show_help` (L207-208).** Use the exact two rows from D6.
8. **`_execute_item` (L256).** `PromptScreen(item.label, item.prompt, secret=item.secret)`.
9. **`_run_action` (L260-275).** Implement the D5 behaviour. In outline:
   - Info line: `Executed: {item.label}`, plus ` → {result}` only when `result is not None and not item.secret`.
   - Error line: `text = str(exc)`, and `text.replace(value, "***")` when `item.secret and value`. Then `Error in {item.label}: {text}`.
10. **`on_input_submitted` (L332-366).**
    - Compute `low = cmd.lower()` and compare the four reserved groups against `low`.
    - Keep `select_by_shortcut(cmd)` and the digit logic unchanged.
    - **Delete `on_key` (L368-376).**
11. **`attach_logging` (L383-403).**
    - New signature (D4).
    - Prune inactive attachments.
    - If an active attachment exists for the same logger object, return it.
    - Otherwise create `LogAttachment(app, logger, exclusive=exclusive, level=level)`, append it to `app._attachments` and return it.
    - Keep the docstring minimal.
12. `run()` (L406-418) is unchanged.

**Acceptance criteria:**

- `uv run python .claude/skills/phase-pipeline/probes/io/exp1_logging_threads.py` shows main-thread, action and background-thread records all shown. There is no `RuntimeError` or `handleError`, and no TUI handler is left on the logger after exit.
- `exp2_after_exit.py` (run it from a scratch directory, because it writes `exp2_stacks.txt`) shows 0 logging-error lines after exit and no handler left.
- `typed_markup_test.py`: typing `[/x]` + Enter does not crash. The panel shows `Unknown command: '[/x]'`, and `return_code` is `None` while the app is running.
- `edge_test.py` `crash_case`: an action raising `ValueError("bad key [/section] in config")` leaves the app alive. The panel shows `Error in Boom: bad key [/section] in config`.
- Prompted action: the panel shows `Executed: Set Port → port → 8080` and never `'8080'`. A secret item shows no result suffix and no value in its error text.
- The `PromptScreen` opened for a secret item has `Input.password is True`.
- **F8**
  - Typed `Q`, `Quit`, `HELP`, `B` and `Clear` act as the reserved commands.
  - `press("d")` alone does nothing, and `press("d","enter")` fires.
  - `CLIApp` has no `on_key`.
  - Help and hint contain the exact strings from D6.
  - A conflicting menu produces a `UserWarning`, plus a panel WARNING line after mount.
  - `strict_shortcuts=True` raises `ValueError`.
  - A clean menu produces no warnings.
- RichLog `max_lines == 5000` by default, and `CLIApp(menu, max_lines=50).query_one("#display-panel").max_lines == 50`.
- `attach_logging` twice on the same logger and app yields one handler and returns the same object. `detach()` restores handlers and level. Attachments auto-detach at app exit.
- `push_log` from a background thread appears after a `pause()`.

### WP-3: menu model, widgets, theme (F1 widgets, F4 UI side, F8 validation and wording)

**Owns:** `cli_interface/menu.py`, `cli_interface/widgets.py`, `cli_interface/theme.py`.

**Provides:** C4, C5, and the `_HINT_TEXT` wording.

**Consumes:** none, so it is standalone.

**Steps:**

- `menu.py`:
  - After L14, add `secret: bool = False` as the last field of `MenuItem`.
  - Add `RESERVED_COMMANDS` and `find_shortcut_conflicts` (D6).
  - Add a cycle guard.
  - Leave `select_by_shortcut` as it is.
- `widgets.py`:
  - **`PromptScreen`**
    - L72-85: `__init__(self, item_label, prompt, *, secret=False)`.
    - `Label(..., markup=False)` for the title and the prompt.
    - `Input(id="prompt-input", password=self._secret)`.
    - The hint Label keeps its markup.
  - **`Dashboard.render`**
    - L111-121 returns `Text`.
    - Crumbs are `bold {_ORANGE}` joined by `Text(" › ", style=_DIM_FG)`.
    - The status or spinner line is `" " + (frame + " " + label)` in style `f"{_CYAN} italic"`.
    - The plain text must equal today's text.
  - **`NavBar`**
    - L143-149 `_compute_item_width`: use a shared `_value_text(item)` helper. It returns `"••••"` when `item.secret` and `current_value` is not `None`, otherwise `str(current_value)`.
    - L174-191 `_render_item` returns `Text`, built with `Text(style=...)` and `.append`. The nested shortcut colour must stay layered over the selected-item background.
    - L196-226 `render` returns `Text`: rows joined with `\n`, the "(no options)" case, and the page footer.
    - The plain text of ordinary menus must be unchanged:

      | Item state | Cell layout |
      |---|---|
      | Normal | `"  "` + `"sc "` + label + `" (val)"` + `" ›"` + `"  "` |
      | Selected | `" "` + `"sc "` + label + `" (val)"` + `" ›"` + `" "` (for Back/Exit sentinels, no arrow) |
      | Footer | `"\n  page N of M — keep navigating ↑↓ to reach items on other pages"` |

- `theme.py`:
  - Delete `_MAX_LOG_LINES` (L18).
  - In `_HINT_TEXT` line 1, replace `type a shortcut or command` with `type a shortcut + Enter`. Keep each line at 85 visible characters or fewer.

**Acceptance criteria:**

- `MenuItem("x").secret is False`, and the positional construction `MenuItem("a","b","c",[],f,"p",1)` still works.
- `find_shortcut_conflicts`:
  - A menu with `q` and `Quit`, a duplicate `x` and `X` in one level, and the same shortcut in different levels (allowed) yields the right messages.
  - A clean tree yields `[]`. A cyclic tree terminates.
- `nav.render()` and `dash.render()` return `rich.text.Text`.
  - `.plain` shows labels verbatim for `Run [/x]`, `matrix[i][j]`, `C:\data\[/tmp]`, `x\[y`, `[bold]x`, and for `current_value="[/v]"` and `shortcut="[x]"`. Nothing crashes.
  - Ordinary menus render the same `.plain` text as before.
- `PromptScreen(..., secret=True)` has an Input with `password=True`. With `markup=False`, the title and prompt render brackets literally.
- A `secret=True` item shows `(••••)` instead of its `current_value`.
- Importing `_MAX_LOG_LINES` from `theme` fails, and `_HINT_TEXT` has the new wording.

### WP-4: demo and `main.py`

**Owns:** `main.py`, `cli_interface/example_menu.py`.

**Consumes:** C6 and C4 (`MenuItem(secret=True)`).

**Steps:**

- `main.py`: remove `import logging` and the `basicConfig` call. Leave `from cli_interface.app import run` and the `__main__` guard.
- `example_menu.py` `run_worker` (L181-208):
  - Create `worker_running = threading.Event()` in the `build_example_menu` scope.
  - If it is set, `p.log("Worker already running", "WARNING")` and return.
  - Otherwise set it and call `capture = attach_logging(app, exclusive=True, level=logging.DEBUG)`.
  - Drop `root.setLevel` and the unused `TUILogHandler` import.
  - In `_run()`'s `finally`: `capture.detach()`, then `try: app.call_from_thread(app.stop_spinner) except RuntimeError: pass`, then `worker_running.clear()`.
- Add a secret-prompt demo item under Settings, using the unused shortcut `k`:
  - `MenuItem("Set Token", shortcut="k", prompt="Enter API token:", secret=True, action=set_token)`.
  - `set_token` writes `get_panel().log(f"Token accepted ({len(value)} chars)")`.
- Optional: one literal-bracket sample in `show_logs`, for example `config[server][port] = 8080`.
- The demo menu already has no shortcut conflicts, and the new `k` does not add one.

**Acceptance criteria:**

- `import main` adds no root handlers and sets no level.
- Pressing the Worker Demo item (`w`, then Enter) leaves a `TUILogHandler` on the root logger while the worker runs. After it ends, the root handlers and level are exactly what they were before.
- A second press while it is running logs a warning and adds no second handler.
- Closing the app mid-run produces no traceback from the worker thread.
- `find_shortcut_conflicts(build_example_menu(...))` returns `[]`.
- `Set Token` (`k`, Enter) shows a masked input and an `Executed: Set Token` line with no value.

---

## 4. Test notes for the Tester

### Per-finding proofs and probe mapping

| Finding | Must prove | Probe, rewritten as a test |
|---|---|---|
| F1 | Brackets are literal, nothing crashes, markup is opt-in, and widgets render literally. | `exp3c_debug.py` and `pkg/edge_test.py` `crash_case` are the real reproductions. `pkg/typed_markup_test.py` and `exp3b_return_crash.py` (see the caveat below) also apply. |
| F2 | UI-thread, background-thread, pre-mount and post-exit behaviour, plus no deadlock and boundedness. | `exp1_logging_threads.py`, `exp2_after_exit.py`, `pkg/edge_test.py` `main_thread_log_case` |
| F3 | Detach restores exactly. | `exp1` (handlers after exit), `exp2` (handlers left), `case/probe3.py` and `smoke_test.py` steps 8-9 (exclusive on root) |
| F4 | No echo, masked input, secret redaction. | New tests; there is no probe. |
| F6 | No re-render, bounded lines, throughput. | `exp7_throughput.py` |
| F8 | Case-insensitive reserved commands; conflict warnings. | `api/probe4.py` spied `CLIApp.on_key`, which no longer exists. Invert it into "single key does not fire; key + Enter fires". |
| `main.py` | No logging configured at import. | New test. |
| Demo | `smoke_test.py` adapted, covering the changes below. | `pkg/smoke_test.py` |

**`smoke_test.py` needs two changes:**

- Step 1 asserts that single-key `v` does **not** navigate and that the input keeps `"v"`.
- Steps 8 and 9 must reflect that the worker's attachment is scoped to the worker run. After the worker finishes, the root logger is restored, so a `logging.getLogger("consumer")` record is not shown unless explicitly attached.

### What each finding's tests must assert

- **F1**
  - Use these samples: `[/x]`, `matrix[i][j]`, `C:\data\[/tmp]`, `x\[y`, `[bold]x[/bold]`.
  - Cover `panel.log/text/rule/table/json/array/pretty`, `panel.table` cells and headers, and typed commands.
  - Cover action return values and exception messages.
  - Cover NavBar labels, shortcut and `current_value`, Dashboard crumbs, and `PromptScreen` title and prompt.
  - The app must stay alive (`return_code is None`, `is_running`).
  - `markup=True` renders styled text, and an invalid `markup=True` input falls back to plain text.
- **F2**
  - Records logged on the UI thread appear without a thread hop.
  - Background-thread records appear after a `pause()`.
  - Logging before mount appears after mount.
  - After the app exits, a worker keeps logging for 0.3 s with zero `handleError` calls and no handler left.
  - Boundedness:
    - Monkeypatch `cli_interface.log_handler._INBOX_MAXLEN` to a small value before building the app.
    - Block the loop (for example with `time.sleep` inside the test coroutine) while a thread logs more than the cap.
    - Then assert at most `cap` records plus one "dropped" line.
  - No deadlock: a worker logs 1000 records while the UI thread `join(timeout=5)`s it. Assert the thread is no longer alive and the join returned in time.
- **F3**
  - Handlers and level before attach equal those after `detach()` and after app exit, for both `exclusive=False` and `exclusive=True`, and for a named and the root logger.
  - A host handler added mid-attachment survives.
  - The level is not clobbered if the host changed it.
  - Detaching twice and via `with` both work.
  - Calling `attach_logging` twice returns the same object and leaves one handler.
  - Queued records still render after `detach()`.
- **F4**
  - A prompted item's log line does not contain the typed value, for plain and secret items.
  - A secret item's input has `password=True`.
  - A secret item's exception text is redacted (`***`).
  - The NavBar masks a secret `current_value`.
- **F6**
  - `RichLog.write` call count equals the number of records.
  - `len(lines) <= max_lines`, in both log mode and content mode.
  - Use loose throughput thresholds (more than 2,000 rec/s) to avoid CI flakiness.
- **F8**
  - Typed `Q`, `Quit`, `HELP`, `B` and `Clear` act as the reserved commands.
  - A consumer shortcut `q` triggers a `UserWarning` and a panel WARNING line, and never runs.
  - A duplicate shortcut warns, and the first item wins.
  - `strict_shortcuts=True` raises `ValueError`.
  - A shortcut with Enter fires; a shortcut alone does not.
  - The hint and help contain the exact new strings.
  - There is no `on_key`.

### Probe caveat (important)

The `run()` helper in `exp1` and `exp3b` calls `pilot.press(key)` **without Enter**, so the action never ran at baseline. `exp3b`'s "app alive after action: True" was therefore not evidence that the crash is absent. In every test, press `key` then `"enter"`.

### Pilot tips

- Use `async with app.run_test(size=(120, 40)) as pilot:`, and `await pilot.press("p", "enter")` to run a shortcut. Plain `asyncio.run(...)` inside sync tests works, as the probes do. Real `app.run(headless=True)` (exp2-style) must be called from a sync test with no running loop.
- Read the panel with `"\n".join(s.text for s in app.query_one("#display-panel", RichLog).lines)`. `RichLog` defers writes until it is sized, so `await pilot.pause()` first. Strip trailing spaces. With `wrap=True`, keep the width at 120 or more for substring checks.
- Read widgets with `nav.render().plain` and `dash.render().plain` rather than the screen.
- `Modal` input: `app.screen` is a `PromptScreen`, and `app.screen.query_one("#prompt-input", Input).password`.
- After a background-thread burst, wait with a polling helper, for example `await pilot.pause(0.05)` in a loop with a timeout. Do not `join()` threads on the loop thread, except in the dedicated no-deadlock test, and always give that join a timeout.
- Never call Textual APIs from non-UI threads except `push_log` or logging.
- To detect error spam, spy on `logging.Handler.handleError` (monkeypatch it and count calls). Do not capture stderr, because Textual swaps `sys.stderr` during a run, which is why the probes poke `app._original_stderr`.
- `warnings`: `pytest.warns(UserWarning, match=...)` around `CLIApp(menu)`. No app run is needed for the construction-time warning.
- Hermetic logging: use unique logger names with `propagate=False`. For root-logger tests, snapshot and restore `logging.getLogger().handlers` and `.level` in a fixture, because pytest installs its own handlers on the root logger.
- Add a dev group with pytest and, if the Tester wants it, pytest-asyncio (Tester-owned config).

---

## 5. Risks and open questions

**Risks**

- **R1: Truncated large dumps.** `max_lines=5000` truncates large JSON or table dumps from the top. It is configurable per app, but it is a user-visible change.
- **R2: Labels with intentional markup.** Menu labels that intentionally contain markup now show literal tags. The user's `whiteboard.py` is no longer in the tree, so I could not check whether it does this.
- **R3: Mid-flight imports.** Parallel executors may see transient `ImportError`s from another package's in-progress edit (`find_shortcut_conflicts`, `PanelInbox`, `_MAX_LOG_LINES`). The contract design means the final tree is consistent, but the orchestrator should re-run the WP-2 and WP-4 smoke checks after WP-1 and WP-3 land.
- **R4: Subclass `on_mount` order.** A subclass `on_mount` runs before `CLIApp.on_mount`, and `super().on_mount()` runs the base handler twice, which is why `open()` and the warnings pop are idempotent. The pre-existing duplicate `set_interval` timers (the "smaller issue" in `phases.md`) are not fixed here.
- **R5: Large UI-thread backlog.** A UI-thread record with a large backlog stalls the UI thread for up to about 0.8 s while the backlog drains. It only happens when the UI is already behind.
- **R6: `exclusive=True` on a named logger.** It clears only that logger's handlers. Handlers on the root logger still receive propagated records, as before. I deliberately did not touch `propagate`.
- **R7: Break in `api/probe4.py`.** Deleting `on_key` breaks that probe. This is expected, and the Tester converts it.
- **R8: `RichLog.highlighter` across versions.** It is guarded with `getattr`. It is fine on Textual 8.2.8, and Phase 1's lower bound is 0.80.
- **R9: Breadcrumb separator.** Breadcrumbs are joined with `"|"` and split in `Dashboard.render`, so a label containing `|` splits wrongly. This is cosmetic and left as is.

**Open questions for the user**

- **Q1: Warn or raise by default?** I recommend warn plus an opt-in `strict_shortcuts=True`, and flipping the default in Phase 1.
- **Q2: Markup in labels.** Do any of your menus use markup in labels? If so, we would need an opt-in such as `MenuItem(markup=True)`. I did not add one.
- **Q3: Is a default `max_lines` of 5000 OK?**
- **Q4: Is case-insensitive reserved matching OK?** The alternative is exact-case matching and validating shortcuts case-sensitively.
- **Q5: Digit shortcuts that shadow positional selection.** For example, `shortcut="2"` on the first item. I did not validate this; the demo's `1/2/3` shortcuts are aligned with the positions. Say if you want a warning added.

---

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
