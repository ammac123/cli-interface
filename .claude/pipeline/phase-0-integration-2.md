VERDICT: INTEGRATED

G1, G2 and Carry-forward item 1 are closed, and I found no regressions and nothing half-finished. The repo is untouched: `git status --short` is identical to my round-1 snapshot, and the stray `.mypy_cache/` from round 1 is gone. All runs used scratch copies and `-p no:cacheprovider`.

## 1. Closure

| Item | Evidence | Status |
|---|---|---|
| G2: Back cell advertised `esc`, which does not work typed | `app.py:257-258` now builds `MenuItem("Back", shortcut="b", ...)` with a comment that sentinel shortcuts must be typeable and in `RESERVED_COMMANDS`. A render probe shows the root nav as `q Exit` and a submenu nav as `l Leaf   b Back`, with both sentinel keys in yellow. The coordinator calls this option (a). It is my option (b), which adds no new reserved word. `esc` typed is still an unknown command, but nothing advertises it any more. The Esc key binding and the hint's "Esc back" are unchanged. | Closed |
| G2 regression coverage | 15 new tests in `tests/test_shortcuts.py`. `displayed_shortcut()` reads the yellow spans NavBar actually draws, not `MenuItem.shortcut`. `test_every_displayed_shortcut_activates_its_item` has 10 cases across root, submenu and deep levels, and covers an uppercase key, a multi-character key (`go`, `dd`) and an item with no shortcut. Others check that the sentinel shortcuts are reserved commands, that the Back cell reads `b Back` while Esc still works, and that a demo walk uses only displayed shortcuts. The reviewer mutation-checked it: reverting Back to `esc` failed 6 tests, changing Exit to `x` failed 3, and drawing an extra character in the consumer shortcut failed 14. | Closed |
| G1: `unique_logger` name reuse | `tests/conftest.py` now uses a module-level `_UNIQUE` counter. A skip-until-free loop (`name not in logging.Logger.manager.loggerDict`) replaced the reviewer-flagged assert. Two in-process `pytest.main(...)` runs of `tests/test_attach_logging.py` both pass (exit codes 0 and 0). A self-test, `test_unique_logger_hands_out_distinct_loggers_that_start_with_no_handlers`, was added. | Closed |
| Carry-forward 1: `textual.content` import in tests | `tests/test_shortcuts.py` now imports `rich.text.Text`. The hint test uses `Text.from_markup(_HINT_TEXT).plain`. In round 1 I verified this gives identical text. | Done |

## 2. Results

- **Full suite, repo env (3.13, textual 8.2.8):** 467 passed, 1 xfailed, 69.56 s. The xfail is still the strict timer-lifecycle one. The count is 451 plus 16 new tests (15 shortcut tests and the fixture self-test).
- **Full suite, `venv311low` (Python 3.11.16, textual 0.80.0), scratch copy of package, tests, `pyproject.toml` and `main.py`:** 467 passed, 1 xfailed, 63.18 s. This is the configuration where G1 failed 3 of 3 times in round 1, and it is now clean.
- **Lint:** `ruff --select F` over `cli_interface`, `main.py` and `tests` passes.
- **Package diff this round:** one line plus a comment, at `app.py:257-258`.

## 3. Updated carry-forward list

| # | Item | Target phase |
|---|---|---|
| 1 | Reserved commands have two sources of truth: `menu.RESERVED_COMMANDS` and the inline tuples in `app.py`. The sentinel shortcuts now also depend on the "must be reserved" convention. Tests pin it (`sentinel_shortcuts_are_reserved_commands`), but Phase 2's `stop` still needs edits in two places. Derive dispatch from one table. | Phase 1 or 2 |
| 2 | Add a `ShortcutConflictWarning(UserWarning)` category. The `filterwarnings` regex matches message text, so rewording a warning silently disables the error filter. | Phase 1 |
| 3 | `run(menu)` cannot pass `strict_shortcuts` or `max_lines`. | Phase 1 |
| 4 | Extract `_validate_menu()` from `CLIApp.__init__`, so `set_menu()` and `refresh_menu()` re-run the conflict check and re-warn. | Phase 1 |
| 5 | `LogAttachment.__init__` is public and attaches immediately. A directly constructed one is not registered with `app._attachments`, so it is never auto-detached. Export it as a return type or document that, and keep `PanelInbox` and `TUILogHandler` out of `__all__`. | Phase 1 |
| 6 | The demo's "Settings (uses logging)" items log into the void. I confirmed that with stderr discarded the panel shows only `Executed:` lines. Attach a named-logger capture (`cli_interface.example_menu`) when the demo moves. | Phase 1 (`examples/`) |
| 7 | **New:** a shortcut with leading or trailing whitespace is displayed but never matches. I confirmed `MenuItem("A", " x ")` is displayed, `select_by_shortcut("x")` returns `None` (typed input is stripped), and `find_shortcut_conflicts` reports `[]`. Strip or reject it in the conflict check or in `MenuItem`. | Phase 1 (Phase 3 for generated menus) |
| 8 | **New:** `NavBar._compute_item_width` hard-codes `sc = 2`, which is exact only for single-character shortcuts. I confirmed shortcut `'gadget'` is estimated at 7 columns but renders 10. Use `len(shortcut) + 1`. Row packing can overflow. | Phase 1 |
| 9 | `TUILogHandler` flattens each record to a string before the inbox. The structured `log` event needs `logger`, `levelno`, `t` and `exc` captured at the handler and formatted in the renderer. `test_logger_records_have_timestamp_level_and_logger_name` will need adapting. | Phase 2 |
| 10 | The inbox's drop-oldest policy is wrong for `result`, `error`, `progress` and `hello` events. Add a per-kind policy or a non-droppable lane. | Phase 2 |
| 11 | `PanelInbox(app)` calls `app.panel.log`. The headless sink needs `PanelInbox(sink)`. Tests already use `StubApp`, so the change is mechanical. | Phase 2 and 4 |
| 12 | Secret redaction handles one value via `str.replace` on exception text. Phase 3's multi-parameter forms and `app.settings(secret={...})` need a redaction set, applied to the log path too. Textual's fatal traceback uses `show_locals=True` and can print the `value` local. | Phase 3 (traceback hardening: Phase 1) |
| 13 | The breadcrumb joins labels with `"|"` and splits on it, so a label containing `|` splits wrongly (R9). | Phase 1 UI polish |
| 14 | `max_lines` has no validation or documentation for `None` or `<=0`. `max_lines=0` trims nothing but still advances `_start_line`. | Phase 1 |
| 15 | The hint says `q quit` and the help says `q / quit / exit: Quit the application`. Neither says "+ Enter", unlike the `<shortcut> + Enter` rows. Cosmetic. | Phase 1 UI polish |
| 16 | The probes under `.claude/skills/phase-pipeline/probes/` (`api/probe4.py`, `pkg/smoke_test.py`) assert baseline behaviour and now "fail" by design. Mark them as baseline repros. | Orchestrator or Documenter |
| 17 | `tests/` coupling to the demos will break when they move to `examples/`: `conftest.py` (`gated_worker`, `fast_worker`), `helpers.build_demo_app`, all of `test_demo.py` (including the `main` subprocess tests), the two demo tests in `test_real_run.py`, and the no-arg `run()` use in `test_regression.py`. The new demo walk test in `test_shortcuts.py` is demo-coupled too. Core modules are unaffected. | Phase 1 |
| 18 | Timer lifecycle, as ruled: the three unguarded `query_one` calls in the spinner and phrase callbacks, the duplicate `set_interval`, and the strict xfail test. Document the Pilot hazard for consumers: call `app.exit()` before leaving `run_test` if a spinner is running. | Phase 1 |
| 19 | Style: redundant quoted annotations, ruff UP rules, and `zip(strict=)`. | Phase 1 (ruff) |

Removed from the round-1 list: the `textual.content` test import.

## 4. Documenter additions

- **Back and Exit cells:**
  - The Back cell shows `b` and the Exit cell shows `q`.
  - Each displayed (yellow) shortcut is exactly what you type, followed by Enter.
  - The Esc key also goes back (key binding), but `esc` typed is not a command.
  - Say that in the help, hint and README wording.
- **Consumer shortcut caveats:**
  - Multi-character consumer shortcuts are supported (`go`, `dd`).
  - Shortcuts must not have leading or trailing whitespace until Carry-forward item 7 lands.
  - Very long shortcuts can mis-estimate NavBar row width until item 8 lands.
- **Tests:**
  - The suite is now 467 tests plus 1 strict xfail. `unique_logger` is collision-safe, with a self-test.
  - `displayed_shortcut()` reads the yellow spans NavBar draws.
  - The suite runs on 3.11 with textual 0.80, 3.13 and 3.14 (3.14 was checked in round 1).
- **Contributor note:** a sentinel shortcut must stay typeable, so it must be in `RESERVED_COMMANDS`. `tests/test_shortcuts.py::test_sentinel_shortcuts_are_reserved_commands` enforces it.
- **Round-1 Documenter notes still stand.** The `CHANGELOG` entry for `esc` to `b` needs to say that the displayed Back shortcut changed from `esc` to `b`.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
- /Users/andrewmacleod/workspace/cli_interface/tests/conftest.py
- /Users/andrewmacleod/workspace/cli_interface/tests/test_shortcuts.py