WP-4 is done. `app.py` and `theme.py` are ruff-clean and mypy-clean (0 errors, down from 2–3). Pilot acceptance prints ALL OK on Python 3.13 with textual 8.2.8, and on Python 3.11 with textual 0.80.0 and rich 13.3.3. The existing suite shows 2 failures and 1 collection error, all listed as expected in plan §5. I did not commit and touched no other file.

## 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py`
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/theme.py`: `_BACK` and `_EXIT` deleted, and `_HINT_TEXT` reworded.

## 2. Changes by scope ID
- **P1.2a read sites.**
  - `_execute_item` ("no action bound" and the `PromptScreen` title), the `Executed:` and `Error in` lines in `_run_action`, and the breadcrumb in `_refresh_view` all use `item_label`.
  - The label is resolved after the action runs.
  - `app.py` has no `item_value` read sites, so no secret masking is needed there.
  - Both `dash.crumbs = tuple(labels)` and `dash.location = "|".join(labels)` are set. `_refresh_view` always ends with `nav.refresh(layout=True)`, plus `dash.refresh()`.
  - This fixes the mypy error at the old `app.py:380`.
- **P1.2b.**
  - `set_menu`, `refresh_menu` and `go_home` are added.
  - `set_menu` raises `TypeError` for a non-`MenuItem`.
  - They work before mount, after exit, and with a `PromptScreen` open (D17), including through `call_from_thread`.
  - `set_menu` and `go_home` repaint with the "navigating" phrase.
  - `go_home` does nothing at the root, with no selection reset.
- **CF-1.**
  - The three tick methods guard on `self.is_running` and on a live dashboard ref.
  - `_spinner_handle`, `_spinner_phrase_handle` and the new `_phrase_handle` are typed `Timer | None`.
  - `on_mount` creates `_phrase_handle` only if it is `None`.
  - `on_unmount` stops and clears all three, before closing the inbox.
  - The strict xfail test now XPASSes.
- **CF-2.** `on_input_submitted` dispatches through `reserved_action(cmd)`. There are no reserved-word tuples left in `app.py`.
- **CF-4.**
  - `_validate_menu(menu)` returns nothing and is callable before `super().__init__()`.
  - In strict mode it raises `ValueError("\n".join(problems))`.
  - Otherwise it warns with `ShortcutConflictWarning` at `stacklevel=3`.
  - It dedupes through a reported set: `set_menu` clears it, a problem that disappears can warn again.
  - Each new problem goes to the panel as a WARNING line via `push_log` when mounted, otherwise to `_menu_warnings`.
  - It is called directly from `__init__`, `set_menu` and `refresh_menu`.
- **CF-7.**
  - `_build_display_items` uses `make_nav_cell`.
  - `_activate` dispatches on `isinstance(item, _NavCell)` and `.kind`.
  - Submenu lookup uses identity.
- **CF-8 and CF-10.**
  - `run(menu, *, strict_shortcuts=False, max_lines=5000) -> int` forwards both options and returns `app.return_code or 0`.
  - `run()` with no menu raises `TypeError`.
  - `max_lines: int | None`. `None` is unbounded; `0`, `-1`, `True`, `"5"` and `1.5` raise `ValueError`.
  - Both `menu` and `max_lines` are validated before `super().__init__()`.
- **CF-14 app half.** Done in `_refresh_view` (see P1.2a above).
- **CF-15.**
  - Help rows read `q / quit / exit + Enter` and `b / back + Enter`.
  - The hint now measures 72 and 81 characters on its two lines.
  - Line 1 still contains "type a shortcut + Enter".
  - `q + Enter  quit` moved to the start of line 2, because it did not fit on line 1.
  - At 80 columns line 2 wraps, and what gets clipped is the end of "jump to top / bottom".
- **CF-16.** Both files are clean on ruff 0.17.3 with `E4,E7,E9,F,UP,B` and on mypy 2.4.1. mypy on the whole package (12 files) is also clean.
- **CF-17.** `_fatal_error` is overridden with `Traceback(show_locals=False, width=None, suppress=[rich])`.
  - I checked a secret held in a runtime-computed local: absent with the override, present with Textual's default.
  - A literal secret in the source line still shows in the code context. The Tester's test must compute the secret at runtime.
- **attach_logging.** Now warns `LoggingAttachWarning` (same text, `stacklevel=2`).
- **Docstrings fixed because they became false.** Module, class (public API list), `__init__` (`max_lines`, warning category), `start_spinner` (the testing paragraph is gone), `attach_logging`, `run`.

## 3. Deviations and decisions
- **Widget refs are cached.**
  - `_dashboard`, `_navbar` and `_rich_log` are cached by `_bind_view()`, which `on_mount` calls. They are cleared at the start of `on_unmount`.
  - `_view_ready` is a property over those refs.
  - Reason: `screen_stack[0]` is empty before mount and after exit.
- **Lazy bind in `start_spinner`.**
  - Textual runs a subclass's `on_mount` before the base one. My first draft silently dropped `start_spinner()` called from a subclass `on_mount`.
  - `start_spinner` now binds lazily when running, unbound and not yet unmounted (an `_unmounted` flag).
  - Verified on Textual 8.2.8 and 0.80.0.
- **Spinner methods are no-ops outside the running window.** `start_spinner` and `stop_spinner` do nothing before mount and after exit. Previously they raised Textual errors.
- **`_activate` on a stale submenu.** If the item is no longer among the current children, it resyncs the view and returns. Previously it entered whatever was selected.
- **`refresh_menu` and the status phrase.** It does not reroll the idle phrase (`_refresh_view(None)`).
- **Strict mode in `refresh_menu`.** A conflict raises `ValueError` before prune and repaint. The plan didn't say.
- **Prune and selection.** After a prune the selection is clamped, not reset to 0.
- **`set_menu` rollback.**
  - It saves and restores `_reported` and `_menu_warnings` on any exception, including a warning escalated to an error. The old tree stays intact.
  - It drops panel lines queued for the old tree.
- **D7 "panel never touched".** I read it as never cleared or written to, except for conflict WARNING lines. `set_menu` and `go_home` left the panel text identical.
- **`run(menu)` warning filename.** Warnings raised through `run(menu)` point at `app.py` rather than the caller. Python 3.11 has no `skip_file_prefixes`.
- **Help rows not changed.** `clear` and `help / ?` still lack "+ Enter". The plan only covered `q` and `b`.

## 4. Cross-package requests
None.
- The Tester needs WP-5 to re-export `ShortcutConflictWarning` and `LoggingAttachWarning` for the `filterwarnings` category form.
- Until WP-7 lands, the root `main.py` calls `run()` with no arguments and raises `TypeError` (plan risk 4).

## 5. Results
**Self-checks**
- ruff 0.17.3 on both files: "All checks passed!".
- mypy 2.4.1 on both files: "no issues found in 2 source files".
- `uv run --no-sync python -c "import cli_interface.app"`: OK.

**Pilot acceptance** (`/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp4/accept.py`): about 75 checks, all passing. It covers:
- `set_menu` resets stack, breadcrumb and selection; `refresh_menu` keeps the stack.
- `refresh_menu` prunes a removed level; `go_home` from depth 3 and at the root.
- Warning dedupe, call-site filenames and the panel WARNING line.
- All three methods with a `PromptScreen` open, and via `call_from_thread`.
- `on_mount` twice leaves one `_phrase_handle`; ticks and lifecycle calls after exit don't raise.
- `description="__exit__"` and `"__back__"` consumer items run normally.
- Every `RESERVED_ACTIONS` key, in lower and upper case.
- `max_lines` validation and unbounded `None` (6500 lines kept).
- A `|` in a label stays one crumb.
- A raising callable label shows `<error>` and the app stays up.
- `run()` forwards options and returns `return_code`.
- `LoggingAttachWarning` at the call site.
- A subclass `on_mount` calling `start_spinner`.

**Timer stop.** A real check recorded `stop()` on all three `Timer` objects when the app exits.

**Probes** (run from the scratch dir, so no stray files):
- `exp2_after_exit.py`: returned in 0.51s, 0 logging-error lines, no handlers left.
- `exp6_exit_latency.py thread`: 0.32s.
- `exp6_exit_latency.py worker`: 3.01s. A baseline `4cab69a` export gives the same 3.01s, because the blocking thread worker holds exit, not the timers.
- `probes/pkg/smoke_test.py`: not run, not applicable (it imports the moved demos).

**Suite** (`uv run --no-sync pytest -q -p no:cacheprovider --continue-on-collection-errors`): 382 passed, 2 failed, 1 collection error. Identical on textual 0.80.0 / Python 3.11. All three are listed in §5:
- `tests/test_shortcuts.py`: collection error, `_BACK` and `_EXIT` removed from `theme`. Expected.
- `tests/test_regression.py::test_push_log_and_panel_surface_is_unchanged`: pins the old `run` signature. Expected.
- `tests/test_regression.py::test_late_timer_ticks_after_teardown_are_harmless`: XPASS(strict). Expected, and it means CF-1 works.

**Unmasked run.** A scratch copy of `tests/` patched to the post-WP-4 expectations passed 467 of 467 once `main.py` was copied in for `test_demo`. Without that copy one `test_demo` test fails, because the copy has no `REPO/main.py`.
- Patches: sentinel via `_NavCell`, hint first line 72 characters, the `run` signature, and the xfail marker removed.
- `test_shortcuts.py` alone, with only the import stubbed, fails 12: the hint `== 82` assertion and the description-based sentinel assertions. All expected.
- `test_demo`, `test_real_run` and `conftest` still pass because WP-7 hasn't removed the old demos yet.

## 6. Not verified
- Windows and Python 3.14.
- Real-terminal rendering; only headless Pilot, including 80x24 for the hint.
- `set_menu` and the other methods called concurrently from a thread without `call_from_thread` (documented as unsupported).
- The CLI flow (WP-6) and the demos (WP-7), which don't exist yet.