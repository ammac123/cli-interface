All three fixes are in `app.py` and `theme.py`. ruff and mypy are clean on both files. The suite shows only the plan-§5 failures. I did not commit and touched no other file.

**Fixes**
1. **Issue 1, `/Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py:513` (`_run_action`).**
   - `label = item_label(item)` is now computed once, before `item.action(...)` and outside the `try`. The `Executed:` line (:517) and the `Error in` line (:522) both use it.
   - The comment above it says the label is read before the action because the action may change it.
2. **Issue 7, `/Users/andrewmacleod/workspace/cli_interface/cli_interface/theme.py:27-35`.**
   - Line 2 now ends `Home / End  top / bottom`. "jump to" is the only wording dropped, and the `q + Enter  quit` entry stays.
   - New plain-text lengths: line 1 is 72 characters (unchanged, still contains "type a shortcut + Enter"). Line 2 is 73, down from 81.
   - Both are at or below the 76-character content width of an 80-column terminal and below D16's 85. The `#hint` widget at `run_test(size=(80, 24))` shows both lines in full, with nothing clipped.
   - The text of line 2 is now `  q + Enter  quit   PgUp / PgDn  scroll output   Home / End  top / bottom`.
3. **Issue 8, `app.py:439-440`.** The help rows are now `clear + Enter` and `help  /  ? + Enter`. The existing tests only match the Action column for these two rows, so none are affected.

**Checks**
- **Pilot acceptance** (`/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp4/accept.py`): ALL OK on Python 3.13 with textual 8.2.8, and on Python 3.11 with textual 0.80.0. I updated the script for the new behaviour and added the reviewer's cases:
  - A toggle labelled `"Turn off" if on else "Turn on"` logs `Executed: Turn on`.
  - A label that depends on state the action clears logs `Executed: Item first`, with no `<error>`.
  - A failing action logs `Error in Fail x: kaput`.
  - The old `Lbl1` check now expects `Executed: Lbl0 → r`.
  - The help check covers the q, b, clear and help rows.
- **Suite** (`uv run --no-sync pytest -q -p no:cacheprovider --continue-on-collection-errors`): 357 passed, 2 failed, 4 errors, the same counts as the review's run. All are plan-§5 rows:
  - Failed: `test_regression.py::test_push_log_and_panel_surface_is_unchanged` (old `run` signature) and `test_late_timer_ticks_after_teardown_are_harmless` (XPASS strict, which means CF-1 works).
  - Errors: collection errors in `test_demo.py` and `test_shortcuts.py`, plus two `test_real_run.py` worker-demo tests, because the demos moved.
  - `tests/` is unmodified.

**Not verified:** the reviewer's note that the shipped demo now logs `Executed: Worker Demo` (WP-7's code), and 80-column rendering in a real terminal. The hint at 80 columns was checked headless only.