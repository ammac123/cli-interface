# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There is no tagged release yet; the work
is grouped by roadmap phase. Baseline for Phase 0 is commit `fdb8069`.

## [Unreleased] - Phase 0 (hardening)

### Changed (behaviour)

Output and markup
- **Markup is off by default.** `panel.log` and `panel.text` show `[/x]`, `matrix[i][j]` and Windows paths
  literally. Opt in per call with `markup=True` (an unparseable string falls back to plain text), or pass a
  `rich.text.Text`.
- Table cells, headers and titles, rule titles, `json`/`array`/`pretty` titles, menu labels, shortcuts,
  `current_value`, prompt title and text, breadcrumbs, return values, exception text and typed commands are all
  literal. A label that deliberately contained markup (`"[bold]Run[/]"`) now shows the tags.
- `CLIApp` creates its `RichLog` with `markup=False`.

Scrollback
- The output panel is capped at `max_lines` (default 5000, `CLIApp(menu, max_lines=...)`) in every mode.
  Log mode used to keep 100 entries; content mode (json, table, ...) used to be unbounded. A larger dump now
  loses its head.

Prompts and secrets
- The `Executed:` line no longer echoes the prompted value: a "Password" prompt gave
  `Executed: Password('hunter2')` and now gives `Executed: Password`. A returned result is still shown after
  `→`, so an action that returns its input still displays it. A `secret` item gets no `→ result` suffix, and the
  value is redacted from its error text.

Shortcuts and commands
- **Reserved commands are case-insensitive** and always win: `Q`, `Quit`, `HELP`, `B` and `Clear` now work.
  `Q` used to fall through to a consumer shortcut `q`.
- **Shortcut conflicts** (reserved or duplicate on one menu level) now emit a `UserWarning` when `CLIApp` is
  built and a WARNING line in the panel at start-up. `CLIApp(menu, strict_shortcuts=True)` raises `ValueError`.
- **The Back cell now shows `b` instead of `esc`.** `esc` typed was never a command, so the yellow text did not
  work when typed; `b` is reserved and does. The Esc key still goes back. The Exit cell still shows `q`.
- Single-key shortcuts never fired because the input takes the key. The hint now reads "type a shortcut +
  Enter" (was "type a shortcut or command") and the help table lists `<shortcut> + Enter` and
  `<number> + Enter`.

Logging
- `CLIApp.push_log` is safe from any thread. Worker threads never wait on the UI (they used to block until the
  UI handled each record, which could deadlock). Records are queued, at most 10,000; beyond that the oldest are
  dropped and a "N log record(s) dropped" WARNING says how many.
- A record logged on the UI thread is written immediately (it used to be dropped with `RuntimeError`). Records
  logged before start are shown on start; handlers are silent after the app exits (no `handleError` output).
- `attach_logging` now returns a `LogAttachment` (it returned `None`; callers that ignore the result still
  work). The app detaches every attachment at exit, and `exclusive=True` restores the removed handlers.
- A repeat `attach_logging` for the same app and logger no longer stacks a handler: it returns a lease on
  the existing attachment (`share()`), and warns if `exclusive` or `level` was passed and ignored.

Demo and API signature
- The demo no longer enables DEBUG logging for the whole process (`main.py`). Its Worker Demo captures logs
  exclusively only while the worker runs, then restores the root logger's handlers and level; a second press
  while it runs logs a warning.
- `CLIApp.__init__` gains the keyword-only `strict_shortcuts` and `max_lines`. Positional use is unaffected.

### Added
- `MenuItem.secret`: masks the prompt input and the nav-bar `current_value` (`••••`), and `repr()` prints
  `'***'`.
- `PromptScreen(item_label, prompt, *, secret=False)`.
- `CLIApp(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)`.
- `attach_logging(app, logger=None, *, exclusive=False, level=None) -> LogAttachment`. The new `level=` sets
  the logger's level for the lifetime of the attachment.
- `LogAttachment` (`active`, `detach()`, `share()`, `logger`, `handler`, and use as a context manager). It
  restores exactly what it changed: removed handlers, and the level if nobody else changed it. Handlers the host
  added meanwhile are kept.
- `RESERVED_COMMANDS` (`q`, `quit`, `exit`, `b`, `back`, `clear`, `help`, `?`) and
  `find_shortcut_conflicts(menu)` in `cli_interface.menu`.
- `markup=` (keyword-only) on `DisplayPanel.log` and `DisplayPanel.text`; both also accept a `rich.text.Text`.
- `PanelInbox` (the bounded, thread-safe queue behind `push_log`) in `cli_interface.log_handler`. It is
  internal and not meant for consumers.
- Demo: a "Set Token" item (`k`) under Settings that shows a masked prompt.
- Docs: `README.md` (it was empty), this changelog, and docstrings for the public API.
- Dev only (not shipped): a pytest and Pilot suite in `tests/` (467 tests and one strict xfail for a known,
  harness-only timer teardown race), the `dev` dependency group (`pytest>=9.2.0`, `pytest-asyncio>=1.4.1`) and
  the pytest configuration in `pyproject.toml`. The suite passes on Python 3.11 with Textual 0.80, and on 3.13
  and 3.14 with Textual 8.2.8. `.gitignore` now excludes `.vscode/` and `.claude/`.

### Removed
- The fade of the oldest log lines, and with it the 100-entry log buffer, the per-record re-render of that
  buffer and the log-mode flag. Each `panel.log` call is now one `RichLog.write`.
- `CLIApp.on_key`: it never ran, because the command input consumes the keys.
- `theme._MAX_LOG_LINES`.
- `logging.basicConfig(level=logging.DEBUG)` in `main.py`: importing or running it no longer configures
  logging.

### Fixed
- **F1:** any `[/x]` in a log message, return value, exception text or typed command crashed the app with
  `MarkupError`, and `matrix[i][j]` or Windows paths were mangled. The same applied to menu labels, values,
  prompts and the header.
- **F2:** `TUILogHandler` dropped records logged on the UI thread with `RuntimeError`, and a worker thread
  blocked on the UI for every record, which could deadlock when the UI waited for the worker.
- **F3:** `attach_logging` had no detach, so the handler outlived the app (318 records after exit produced 637
  error lines) and `exclusive=True` permanently removed the host's handlers.
- **F4:** prompted values were echoed in the log, and the prompt input was not masked.
- **F6:** once log mode passed 100 lines every record re-rendered all 100 (about 3,700 down to about 104
  records/s), and content mode had no line limit.
- **F8:** reserved commands silently overrode consumer shortcuts and duplicates went unchecked, and the hint
  advertised single-key shortcuts that never fired.
- A typed superscript digit such as `²` crashed the app (`str.isdigit()` is true for it, `int()` raises
  `ValueError`). It is now an unknown command.
