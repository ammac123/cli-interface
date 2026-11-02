# WP-B (tests) is done

All of WP-B steps 1-14 are in place. The full suite is green: 467 passed and 1 strict xfail in each of 3 runs in the repo environment. The same suite also passes on Python 3.11 with textual 0.80.0. Only `tests/` was touched this round, with no package code and no pyproject changes.

**WP-A dependency:** it has landed. `cli_interface/app.py:258` now reads `MenuItem("Back", shortcut="b", description=_BACK)`, and `grep -n 'shortcut="b", description=_BACK' cli_interface/app.py` finds it.

## What I changed, per step

**G1: `tests/conftest.py` (steps 1-4)**
- Added a module-level `_UNIQUE = itertools.count()`.
- Dropped both `id(made)` and the per-factory `counter`.
- Loggers are now named `f"tests.{prefix}.{next(_UNIQUE)}"`.
- The factory asserts `name not in logging.Logger.manager.loggerDict` before calling `getLogger`, so a reused name fails loudly instead of flaking.

**Carry-forward 1: `tests/test_shortcuts.py` (steps 5-6)**
- Replaced `from textual.content import Content` with `from rich.text import Text`.
- The hint test now uses `Text.from_markup(_HINT_TEXT).plain.split("\n")`.

**New tests in `tests/test_shortcuts.py` (steps 7-12), 15 in all**
- **`displayed_shortcut(nav, i)` helper (step 7).**
  - It renders `nav._render_item(i, nav.items[i])`.
  - It joins the text of the spans whose style is `_YELLOW`, and returns `None` if there are none.
  - So the shortcut comes from what NavBar draws, not from `MenuItem.shortcut`.
- **Fixture menu (step 8).**
  - Conflict-free, with a `Calls` recorder and at most 5 cells per level.
  - Items: `Alpha`/`a`, `Zed`/`Z` (uppercase), `Gadgets`/`go` (multi-character) containing `Inner`/`i` and `Deep`/`dd`, and `Plain` with no shortcut.
  - `Deep` holds one leaf, `Bottom`/`x`.
- **`test_every_displayed_shortcut_activates_its_item` (step 9).**
  - It has 10 parametrised cases: root with 5 cells, Gadgets with 3 and Deep with 2.
  - Each case runs in a fresh app and navigates to its level by typing the displayed shortcuts.
  - It asserts the last cell is the sentinel (Exit at the root, Back elsewhere).
  - It then types the displayed shortcut and checks the effect:
    - leaf: its action ran;
    - submenu: the location changed;
    - Back: the parent's location;
    - Exit: `return_code == 0`.
    - `Plain` must display no shortcut.
- **`test_sentinel_shortcuts_are_reserved_commands` (step 10):** 3 cases (root, Gadgets, Deep), asserting the displayed sentinel shortcut is in `RESERVED_COMMANDS`.
- **`test_back_cell_reads_b_back_and_the_escape_key_still_goes_back` (step 11):** the nav bar text contains `b Back` and no `esc`, and the `escape` key returns to the parent.
- **`test_demo_walk_using_only_the_shortcuts_the_nav_bar_displays` (step 12):** the demo menu, navigation only, no actions.
  - It types the displayed shortcuts into Settings then Audio, reaching `Home|Settings|Audio`.
  - It uses the displayed Back shortcut twice, ending at `Home`.
  - It types the displayed Exit shortcut and asserts `return_code == 0`.

**Fixture self-test (step 13):**
- `test_attach_logging.py::test_unique_logger_hands_out_distinct_loggers_that_start_with_no_handlers` checks that two `unique_logger("x")` calls return distinct, handler-free, non-propagating loggers.

**Step 14:** nothing to change. `test_reserved_commands_value` is untouched and no test pins the text `esc`.

## Results

**Three full runs, repo environment (Python 3.13, textual 8.2.8), `uv run pytest -q`:**

| Run | Result | Time |
|---|---|---|
| 1 | 467 passed, 1 xfailed, 0 failed, 0 skipped | 71.27 s |
| 2 | 467 passed, 1 xfailed, 0 failed, 0 skipped | 70.89 s |
| 3 | 467 passed, 1 xfailed, 0 failed, 0 skipped | 71.13 s |

The only xfail is still the strict timer-lifecycle one, `test_late_timer_ticks_after_teardown_are_harmless`. The count went up by 16 over the previous 451 passed (15 new shortcut tests and 1 fixture self-test). `pyflakes` is clean apart from the intentional `_MAX_LOG_LINES` `ImportError` check in `test_regression.py`.

**Python 3.11.16 with textual 0.80.0 and rich 15.0.0:**
- I reused the integrator's `venv311low` and ran against a scratch copy of the current tree.
- Three full runs gave 467 passed and 1 xfailed each (65.15 s, 65.11 s, 65.11 s).
- `test_shortcuts.py` collects with no `textual.content` import.
- `test_nested_exclusive_attachments_do_not_resurrect_a_dead_handler` passes in the full runs, where the integrator saw it fail 3 of 3 times before the G1 fix.

## Mutation check

- I ran it on a scratch copy, `.../scratchpad/phase0/tester/mut2/`, and confirmed `cli_interface` imported from the copy. I did not touch the repo.
- I reverted WP-A's line there: `MenuItem("Back", shortcut="esc", description=_BACK)`.
- Six of the new tests failed, and they are exactly the Back-cell ones:
  - `test_every_displayed_shortcut_activates_its_item[gadgets-2]` and `[deep-1]`. Typing `esc` + Enter left the location at `Home|Gadgets` instead of `Home`.
  - `test_sentinel_shortcuts_are_reserved_commands[gadgets]` and `[deep]`. `'esc'` is not in `RESERVED_COMMANDS`.
  - `test_back_cell_reads_b_back_and_the_escape_key_still_goes_back`. The nav bar text was `l Leaf   esc Back`.
  - `test_demo_walk_using_only_the_shortcuts_the_nav_bar_displays`. The location stayed at `Home|Settings|Audio`.
- The root-level cases passed, as expected, because the Exit sentinel `q` is reserved. Everything else in `test_shortcuts.py` still passed.
- Against the real tree, all 15 new tests pass.

## Failures

None.

Scratch work is in `.../scratchpad/phase0/tester/mut2/` and `.../scratchpad/phase0/tester/py311/`.