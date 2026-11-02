VERDICT: GAPS

Phase 0 is functionally sound: every in-scope finding is fixed and covered by tests that would fail on regression. I found two small defects in this phase's own deliverables that are cheap to fix. Both are worth fixing before the phase closes. Neither touches the Phase 1-4 design.

Housekeeping: my first, mis-configured `uvx mypy` run left a `.mypy_cache/` in the repo root. It is self-ignored and safe to delete. Everything else I ran used scratch directories under `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/integrator/`. `git status --short` is identical to what I saw at the start.

## 1. Finding traceability

| Finding | Code | Covering tests (a regression would fail them) | Status |
|---|---|---|---|
| F1 markup | `display.py` `_as_text`, `_styled`, `_title`, `_cell`; `log`/`text` take `markup=False`; `app.py:189` `RichLog(markup=False)`; `widgets.py` `Label(markup=False)`, `Text` from `Dashboard.render` and `NavBar.render` | `test_markup.py` (201 tests): hostile matrix × ~17 surfaces, `markup=True` opt-in and fallback. Also `test_shortcuts.py::test_a_superscript_digit_is_an_unknown_command_not_a_crash`. | Fixed |
| F2 log handler / UI thread / deadlock | `log_handler.py` `PanelInbox`, `TUILogHandler.emit`; `app.py` `push_log`, `on_mount` calls `open()` | `test_inbox.py`: UI-thread put, FIFO, stress, no lost wakeups, overflow, pre-mount, post-exit, `test_ui_join_on_a_worker_logging_a_thousand_records_does_not_deadlock` | Fixed |
| F3 detach / restore | `LogAttachment`, `_Lease`/`share()`; `attach_logging` returns a handle; `CLIApp.on_unmount` detaches | `test_attach_logging.py` (40 tests): exact restore, host handler added mid-attach, level not clobbered, lease semantics, restore at exit and on crash | Fixed |
| F4 secrets | `MenuItem.secret` plus masked `__repr__`; `PromptScreen(secret=)` uses `Input(password=)`; `app.py:299-305` (no value echo, no result suffix, redaction); `widgets._value_text` | `test_secrets.py` (26 tests); `test_demo.py::test_set_token_shows_a_masked_input_and_never_echoes_the_value` | Fixed |
| F6 re-render / cap | `display.py` `log` is one `write()`; `app.py:192` `max_lines=5000` | `test_display_limits.py` (13 tests): one write per call, the buffer machinery is gone, cap in log and content mode, throughput floor | Fixed |
| F8 reserved/duplicate/single-key | `menu.py` `RESERVED_COMMANDS`, `find_shortcut_conflicts`; `app.py:106-110` warn or `strict_shortcuts`; `on_key` removed; `theme.py` hint and help wording | `test_shortcuts.py` (69 tests), `test_regression.py::test_probe4_single_key_does_nothing_and_key_plus_enter_fires`. See gap G2 for one hole in the help claim. | Fixed, with a residual (G2) |
| `main.py` `basicConfig` | `main.py` | `test_demo.py::test_importing_main_in_a_fresh_interpreter_configures_no_logging` and `test_executing_main_as_a_module_does_not_start_the_app_or_touch_root` | Fixed |

## 2. Gaps (must be done in Phase 0)

### G1. `unique_logger` fixture has a latent name-reuse flake
- **Type:** defect in the test harness, which is a Phase 0 deliverable.
- **Scenario:**
  - `tests/conftest.py:61` names loggers `tests.{prefix}.{id(made)}.{n}`.
  - `id(made)` can repeat after an earlier test's list is freed. The factory then returns an old logger that is still in `loggerDict` with `propagate=False`.
  - pytest 9.2's `catching_logs.__enter__` attaches its `LogCaptureHandler`s to every non-propagating logger, so that logger starts the test with two foreign handlers.
  - Tests that assert exact handler lists then fail. About 18 assertions of the form `lg.handlers == [...]` are exposed.
- **Evidence:**
  - Python 3.11 with textual 0.80.0 and pytest 9.2: `tests/test_attach_logging.py::test_nested_exclusive_attachments_do_not_resurrect_a_dead_handler` failed in 3 of 3 full runs. It passes when its module is run alone.
  - Debug prints in a scratch copy of the tests showed the same logger name used twice, the second time with `[LogCaptureHandler, LogCaptureHandler]` already on it.
  - Replacing `id(made)` with a module-level `itertools.count()` in the scratch copy made it pass.
  - It passes on the repo's own configurations: 3.13, 3.11 and 3.14, each with textual 8.2.8. That is luck of memory layout, not correctness.
- **Why it matters now:** the green suite is the phase gate, and Phase 1's CI matrix (3 OSes × 4 Pythons, lowest-direct) will hit it.
- **Files:** `tests/conftest.py` only.
- **Fix:** a module-level `_UNIQUE = itertools.count()` and `f"tests.{prefix}.{next(_UNIQUE)}"`. Tests only, and no package review is needed.

### G2. The Back cell advertises an `esc` shortcut that does not work when typed
- **Type:** defect, help text versus behaviour, in wording this phase wrote.
- **Scenario:**
  - In any submenu, NavBar renders the Back cell as `esc Back`, with `esc` in shortcut yellow. I checked the colour with a render probe.
  - This phase's help row says `<shortcut> + Enter: Activate item by its shortcut (shown in yellow)`.
  - Typing `esc` + Enter gives `Unknown command: 'esc'`, and the breadcrumb stays put. I reproduced this in the demo run and in `scratchpad/phase0/integrator/scripts/nav_esc.py`.
  - The Exit cell (`q`) works because `q` is reserved.
  - This contradicts F8's own acceptance ("make shortcuts work, or remove them from help"). It is not covered by ruling B, because that concerned pre-existing `#prompt-hint` text. This help string is new.
- **Files:** `cli_interface/app.py` (`_build_display_items`, the sentinel at about line 257), and optionally `menu.py`. No test currently pins the text `esc`.
- **Suggested fix (smallest, no new reserved word):** change the Back sentinel's displayed shortcut from `"esc"` to `"b"`. `b` is already reserved, so typing it works. The Esc key binding and the hint's "Esc back" are unchanged.
- **Alternative:** add `esc` to the back group in `on_input_submitted` and to `RESERVED_COMMANDS`, then update `test_reserved_commands_value`. This widens the reserved set, and Phase 2 is about to add `stop`.
- **New test either way:** for every item NavBar displays in a menu (children plus the Exit/Back sentinel), typing its shortcut + Enter activates it.

Round size: both fixes are S, with no design change. G1 can be fixed and tested without a package-code review.

## 3. Carry-forward

| # | Item | Target phase |
|---|---|---|
| 1 | Tests still import `textual.content.Content` (`tests/test_shortcuts.py:7,323`), which does not exist in textual 0.80. Collection fails at the declared floor. `rich.text.Text.from_markup(_HINT_TEXT).plain` gives identical text, verified. Bundle with G1 if a round runs anyway. | Phase 1 (lowest-direct CI) |
| 2 | Reserved commands have two sources of truth: `menu.RESERVED_COMMANDS` and the inline tuples in `app.py:372-382`. The tests pin both. Phase 2's built-in `stop` would need edits in both places. Derive dispatch from one table. | Phase 1 or 2 |
| 3 | `filterwarnings` matches message text. Rewording a warning silently disables the error filter. Add a `ShortcutConflictWarning(UserWarning)` category (backward compatible). The same category also lets consumers filter by class. | Phase 1 |
| 4 | `run(menu)` cannot pass `strict_shortcuts` or `max_lines`. | Phase 1 (facade and console script) |
| 5 | The conflict check lives inline in `CLIApp.__init__`. Phase 1's `set_menu()` and `refresh_menu()` will need an extracted `_validate_menu()` that re-runs the check and re-warns. | Phase 1 |
| 6 | `LogAttachment.__init__` is public and attaches immediately. A directly constructed one bypasses `app._attachments`: no dedup, no auto-detach at exit, and `exclusive=True` handlers are not restored. The facade should export it as a return type and document that, or make the constructor private. Keep `PanelInbox` and `TUILogHandler` out of `__all__`. | Phase 1 |
| 7 | The demo's "Settings (uses logging)" items (Volume, Toggle Debug, Set Port, Reset All) now log into the void. I confirmed with stderr discarded that the panel shows only `Executed:` lines. With no handler, INFO is dropped and WARNING goes to stderr, which Textual redirects. Baseline only showed them in the panel after the Worker Demo had permanently attached a handler (the F3 leak). Attach a named-logger capture on `cli_interface.example_menu` when the demo moves. The worker logs under `cli_interface.example_worker`, so there is no double display. | Phase 1 (demos move to `examples/`) |
| 8 | Phase 2 `emit` shape: `TUILogHandler.emit` flattens each record to `"HH:MM:SS [LEVEL] name: msg"` before the inbox. The structured `log` event needs `logger`, `levelno`, `t` and `exc` captured at the handler and formatted in the renderer. `test_logger_records_have_timestamp_level_and_logger_name` will need adapting. | Phase 2 |
| 9 | The inbox's drop-oldest policy is right for `log` but wrong for `result`, `error`, `progress` and `hello` events. Add a per-kind policy or a non-droppable lane. | Phase 2 |
| 10 | `PanelInbox(app)` calls `app.panel.log`. The headless sink needs `PanelInbox(sink)`. Tests already use `StubApp`, so the change is mechanical. | Phase 2 and 4 |
| 11 | Secret redaction handles one `value` via `str.replace` on exception text. Phase 3's multi-parameter forms and `app.settings(secret={...})` need a redaction set applied to the log path as well. Review-1 noted that Textual's fatal traceback `show_locals=True` can print the `value` local. | Phase 3 (traceback hardening: Phase 1) |
| 12 | The `NavBar`/`Dashboard` breadcrumb joins labels with `"|"` and splits on it (R9), so a label containing `|` splits wrongly. | Phase 1 UI polish |
| 13 | `max_lines` has no validation or documentation for `None` or `<=0`. `max_lines=0` makes `RichLog` trim nothing but still advance `_start_line`. | Phase 1 |
| 14 | The hint says `q quit` and the help says `q / quit / exit: Quit the application`. Neither says "+ Enter", unlike the new `<shortcut> + Enter` rows. Cosmetic. | Phase 1 UI polish |
| 15 | The probes under `.claude/skills/phase-pipeline/probes/` (`api/probe4.py`, `pkg/smoke_test.py`) assert baseline behaviour and now "fail" by design. Mark them as baseline repros. | Orchestrator or Documenter |
| 16 | `tests/` coupling to the demos. These will break when demos move to `examples/`: `conftest.py` (`gated_worker`, `fast_worker` patch `cli_interface.example_worker`, 12 references), `helpers.build_demo_app` (4), all of `test_demo.py` (41, including the `main` subprocess tests that locate `main.py` relative to the repo root), the two demo tests in `test_real_run.py` (11), and `test_regression.py` (no-arg `run`). The core modules (`test_markup`, `test_shortcuts`, `test_inbox`, `test_attach_logging`, `test_secrets`, `test_display_limits`) only use `cli_interface.app/menu/widgets/log_handler`. | Phase 1 |
| 17 | Timer lifecycle, as ruled: the three unguarded `query_one` calls in the spinner and phrase callbacks, the duplicate `set_interval` on `super().on_mount()`, and the strict xfail test. Document the Pilot hazard for consumers: call `app.exit()` before leaving `run_test` if a spinner is running. | Phase 1 |
| 18 | Quoted annotations (`"CLIApp"`) are redundant under `from __future__ import annotations`. Ruff UP037/UP035, `zip(strict=)` and similar style fixes. Cosmetic. | Phase 1 (ruff) |

I did not dispute any of the deferral rulings.

## 4. Repo health

- **Imports:** `cli_interface`, `cli_interface.app`, `cli_interface.example_menu` and `main` import cleanly.
- **Full suite once, repo environment (3.13.7, textual 8.2.8):** 451 passed, 1 xfailed in 67.08 s (CPU about 26%, so mostly Pilot waits).
  - Slowest test: 2.2 s. Everything else is under 1.2 s, about 0.1-0.15 s each on average. Nothing is excessive.
  - `pytest-xdist` would help CI.
- **Other interpreters (scratch virtualenvs, same textual 8.2.8):**
  - 3.11.16: 451 passed, 1 xfailed, 68.7 s.
  - 3.14.7: 451 passed, 1 xfailed, 64.8 s.
  - No 3.12+ syntax or API in the package or tests, so `requires-python>=3.11` is not blocked. vermin reports a 3.9 minimum for the package and for the tests.
- **Textual lower bound (3.11 with textual 0.80.0, rich 15):**
  - The package imports.
  - The demo walkthrough runs.
  - 381 of 382 tests pass with `test_shortcuts.py` excluded. The one failure is G1.
  - So the declared `textual>=0.80` floor is viable. The blocker is the test import in Carry-forward item 1, plus G1.
- **mypy:** unchanged. The same 2 errors as baseline: `app.py:158` and `161` (`Timer` assigned to a `None`-typed handle), moved from 138/141. No new errors.
- **pyright:** 0 errors, 0 warnings.
- **ruff, F/E9/B rules:** no unused imports or variables. Its only finding is the baseline `zip()` without `strict=` (B905).
- **uv lock:** `uv lock --check` passes. `requires-python` is still `>=3.13` in `uv.lock`, so Phase 1 needs a relock.
- **Build (`uv build`):**
  - The wheel contains only `cli_interface/*.py` and metadata. There is no `tests/`, `main.py` or `py.typed`. The metadata has `Requires-Python: >=3.13`, `Requires-Dist: textual>=0.80.0` (no `rich`), and the console script `cli_interface.app:run`, which is the demo.
  - The sdist contains the package, `tests/` (12 files), `main.py`, `uv.lock`, `.python-version`, `.gitignore`, `LICENSE`, `README.md` and `pyproject.toml`.
  - `.claude/` does not ship, but only because of the user's uncommitted `.gitignore` edit, which hatchling honours. Phase 1 still needs its explicit include list. `.pytest_cache` did not ship.
- **Demo under `run_test` (and again on textual 0.80):**
  - View Output navigation worked.
  - JSON, Table, Log Lines and Spinner demos rendered. The literal `config[server][port]` showed.
  - A typed `[/x]` gave `Unknown command` with the app alive. `HELP` worked.
  - Set Token showed a masked input, `Executed: Set Token` and no leak of the value.
  - Worker Demo: exactly one `TUILogHandler` on root while running. A second press warned. 16 worker lines were shown, and root was restored.
  - `q` + Enter gave `return_code == 0` with no root handlers left.
  - `esc` + Enter gave `Unknown command` (G2).

## 5. Notes for the Documenter

**What users and integrators need documented**
- Markup is off by default everywhere:
  - `panel.log` and `panel.text` take `markup=True`, or a `rich.text.Text`.
  - Table cells, headers and titles, rule titles, labels, prompts and typed commands are literal.
  - An invalid `markup=True` input falls back to plain text.
- `CLIApp(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)`:
  - Conflicts warn (a `UserWarning` at construction plus a panel WARNING line at mount). `strict_shortcuts=True` raises `ValueError`.
  - `max_lines` also bounds content mode. Large JSON or table dumps lose their head.
- Reserved commands are `q`, `quit`, `exit`, `b`, `back`, `clear`, `help` and `?`.
  - They match case-insensitively and always win over consumer shortcuts.
  - A reserved item stays reachable by arrows, Enter, or its position number.
- Shortcuts are typed + Enter. Single keys never fired, and `on_key` is removed. Digits are `isdecimal`, and `²` is an unknown command rather than a crash.
- `MenuItem.secret`:
  - It masks the prompt input and the NavBar value (`••••`), and `repr` prints `'***'`.
  - The `Executed:` line never echoes values. A secret item has no result suffix, and its exception text is redacted, best effort.
- Logging:
  - `CLIApp.push_log` is safe from any thread, never blocks, and drops the oldest records after 10,000 pending, with one "N log record(s) dropped" WARNING.
  - Direct `panel.*` calls are UI-thread only and bypass the inbox, so FIFO order holds only among `push_log` records.
  - `attach_logging` returns a `LogAttachment`. It can be used as a context manager, and it auto-detaches at app exit.
  - A repeat attach on the same logger returns a lease (`share()`), and `exclusive`/`level` on a repeat attach warn and are ignored.
  - Call it on the UI thread while the app is running. It is not auto-detached after exit.
  - `exclusive=True` on a named logger does not stop propagation to root handlers.
- Removed: the fade, the 100-entry log buffer, `CLIApp.on_key`, `theme._MAX_LOG_LINES`, and the `main.py` DEBUG logging.
- The demo's Worker Demo captures logs exclusively only while the worker runs.
- Consumers writing Pilot tests must call `app.exit()` before leaving `run_test` if a spinner is running.

**Stale or missing docstrings**
- `attach_logging`: `level=` is undocumented. "Strip all pre-existing handlers" omits that detach restores them, and the root-propagation caveat is missing.
- `CLIApp`: it has no class or `__init__` docstring, so `strict_shortcuts` and `max_lines` are undocumented.
- `MenuItem`: it has no docstring, and `secret` and `current_value` are undocumented.
- `RESERVED_COMMANDS`: it has no docstring.
- `PromptScreen`: the docstring does not mention `secret=`.
- `DisplayPanel.log` and `.text`: they do not mention `markup`.
- `DisplayPanel.clear`: no docstring.
- `PanelInbox.open`, `.close`, `.put`: no docstring. The same goes for `LogAttachment.active`, `.detach` and `.share`.
- `run()` has no docstring, and it is the console-script demo.
- `example_menu.py`: the "Settings (uses logging)" comment is misleading (Carry-forward item 7).
- The help and hint wording for `q` and `esc` (G2, Carry-forward item 14).

**CHANGELOG entries**
- Behaviour changes:
  - Markup off by default.
  - Reserved commands are case-insensitive. `Q` used to fall through to a consumer `q`.
  - `Executed:` no longer echoes prompt values.
  - Content mode is now capped (it was unbounded), and log mode is 5000 lines (it was 100).
  - UI-thread log records are written immediately (they were dropped with `RuntimeError`), and post-exit handlers are silent.
  - `attach_logging` returns `LogAttachment` (it returned `None`). Repeat attaches are shared instead of stacked.
  - The demo no longer sets DEBUG logging.
- New API:
  - `MenuItem.secret`.
  - `PromptScreen(secret=)`.
  - `CLIApp(strict_shortcuts=, max_lines=)`.
  - `attach_logging(level=)`.
  - `LogAttachment` and `share()`.
  - `RESERVED_COMMANDS` and `find_shortcut_conflicts`.
  - `DisplayPanel.log` and `.text` gain `markup=`.
  - Dev-only: pytest and pytest-asyncio, the `tests/` suite, and the pytest config.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/tests/conftest.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
- /Users/andrewmacleod/workspace/cli_interface/tests/test_shortcuts.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py