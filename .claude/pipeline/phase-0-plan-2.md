## Round 2 plan: G1, G2 and Carry-forward item 1

I read the integrator report, D6, `app.py`, `menu.py`, `theme.py`, `widgets.py`, `conftest.py` and `test_shortcuts.py`. I did not run anything beyond one read-only check. `Text.from_markup(_HINT_TEXT).plain` equals `Content.from_markup(...).plain`, and the first line is 82 characters.

### 1. Decisions

- **G1: confirm the integrator's fix and add a guard.**
  - Use a module-level `_UNIQUE = itertools.count()` in `tests/conftest.py`.
  - Drop both `id(made)` and the per-factory `counter`.
  - Name loggers `f"tests.{prefix}.{next(_UNIQUE)}"`. Nothing in the tests parses the name format. `test_inbox.py:403` only uses `re.escape(lg.name)`.
  - Refinement: assert in the factory that the name is not already in `logging.Logger.manager.loggerDict`. If reuse ever returns, the fixture then fails loudly instead of flaking.
  - Under xdist each worker is its own process with its own `loggerDict`, so uniqueness per process is enough.
  - No package change or package review is needed.
- **G2: choose (a). The Back sentinel displays `b`.**
  - **D6 and RESERVED_COMMANDS.** D6 fixed the reserved set at exactly eight words and made "stop advertising what doesn't work" the rule. `b` is already in that set and already dispatches to back. (a) needs no reserved-set change, no new dispatch branch and no edit to the two sources of truth (Carry-forward 2).
  - **(b) widens a public contract.** It makes `esc` a word that consumers can no longer use as a shortcut. The hint already documents the physical key as `Esc`, and typing the three letters "esc" is not a command. (b) also forces edits to `test_reserved_commands_value` and to `app.py` dispatch, and adds a word the Documenter must explain.
  - **Phase 2.** A built-in `stop` will need the same two-place edit. Adding `esc` now adds a ninth word for no user benefit.
  - **What stays the same.** The Esc key binding (`app.py:73`), the hint's "Esc back" and the help row "Esc | Go back one level" are all accurate and stay unchanged. The help row "b / back" also stays.
- **Mismatch audit: no other displayed shortcut is broken by the app's own cells.**
  - The Exit sentinel `q` is reserved and works.
  - Consumer items whose shortcut is reserved or duplicated are displayed but unreachable. That is the already-handled warn or strict path (D6), not a new gap. The new test must use conflict-free menus.
  - Edge case, out of scope, record as carry-forward: a consumer shortcut with leading or trailing whitespace (`" x"`) is displayed but never matches. `on_input_submitted` strips the typed text, and `select_by_shortcut` does not strip the stored shortcut.
  - Side effect: `widgets.py:157` hard-codes `sc = 2` for the shortcut width, which under-counts multi-character shortcuts. `esc` was one of them. After the fix the sentinels are exact. Consumer shortcuts of two or more characters are still mis-estimated. That is pre-existing, so list it as a carry-forward and do not fix it here.
- **Carry-forward item 1: do it.** It is two lines in `tests/test_shortcuts.py`, and it unblocks collection at the textual 0.80 floor.

### 2. Work packages

#### WP-A: package code. Owner: the `app.py` executor. Owned file: `cli_interface/app.py`

1. At `cli_interface/app.py:257`, change `MenuItem("Back", shortcut="esc", description=_BACK)` to `shortcut="b"`.
   - Add a short comment above or beside it: sentinel shortcuts must be typeable, so each must be in `RESERVED_COMMANDS`.
2. Change nothing else. Specifically:
   - Leave `menu.py` alone.
   - Leave `theme.py` alone.
   - Leave `_show_help` alone.
   - Leave the `Binding("escape", ...)` alone.

**Acceptance criteria**
- In a submenu, the Back cell renders `b Back` with `b` in yellow (`#e5c07b`).
- Typing `b` + Enter in a submenu returns to the parent.
- The Exit cell at the root is still `q Exit`.
- The `git diff` of the package for this round is one line plus the comment.

#### WP-B: tests. Owner: the Tester. Owned files: `tests/conftest.py`, `tests/test_shortcuts.py`

**G1: `tests/conftest.py`, fixture at lines 54-66**
1. Add a module-level `_UNIQUE = itertools.count()`. `itertools` is already imported.
2. Delete `counter = itertools.count()` at line 57.
3. Replace line 61 with `name = f"tests.{prefix}.{next(_UNIQUE)}"`.
4. Add `assert name not in logging.Logger.manager.loggerDict, name` before `getLogger(name)`.

**Carry-forward 1: `tests/test_shortcuts.py`**
5. Line 7: replace `from textual.content import Content` with `from rich.text import Text`.
6. Line 323: use `Text.from_markup(_HINT_TEXT).plain.split("\n")`.

**New test: `tests/test_shortcuts.py`, new section after the wording section (the end of the file, about line 349)**
7. Add a helper `displayed_shortcut(nav, i)`.
   - It renders `cell = nav._render_item(i, nav.items[i])`.
   - It returns the concatenation of the `cell.plain[s.start:s.end]` pieces for spans whose `str(s.style) == _YELLOW`, or `None` if there are none.
   - Import `_YELLOW` from `cli_interface.theme` and `NavBar` from `cli_interface.widgets`.
   - The point is that the shortcut comes from what NavBar draws, not from `MenuItem.shortcut`.
   - If span styles turn out not to be comparable, fall back to `widget_lines` plus `color_of`.
   - Use menus of 5 items or fewer at `SIZE` so everything is on one page.
8. Build a conflict-free fixture menu with a `Calls` recorder:
   - a leaf `Alpha` `a`;
   - a leaf `Zed` `Z` (uppercase);
   - a submenu `Gadgets` `go` (multi-character), containing a leaf `Inner` `i` and a submenu `Deep` `dd` that has a leaf child;
   - a leaf `Plain` with no shortcut.
9. Add a parametrized test, `test_every_displayed_shortcut_activates_its_item`.
   - It is parametrized over the menu level (`root`, `Gadgets`, `Gadgets > Deep`) and over item index.
   - Each case uses a fresh app with `run_test(size=SIZE)`.
   - It navigates to the level by typing the displayed shortcuts.
   - It reads `nav.items` and the displayed shortcut for item `i`.
   - It types that shortcut with the existing `type_command` and checks the effect:
     - **Leaf:** `calls.names == [label]`.
     - **Submenu:** `dash.location` ends with `label`.
     - **Exit sentinel:** `wait_for(lambda: app.return_code is not None)`.
     - **Back sentinel:** location equals the parent's.
     - **Item with no displayed shortcut (`Plain`):** assert `displayed_shortcut` is `None`, and skip typing.
   - Also assert that the last item of every level is the sentinel (Exit at the root, Back elsewhere).
10. Add `test_sentinel_shortcuts_are_reserved_commands`.
    - For the root and for one submenu, the displayed shortcut of the sentinel (lower-cased) must be in `RESERVED_COMMANDS`.
    - This permanently guards against a G2 recurrence.
11. Add `test_back_cell_reads_b_and_esc_key_still_goes_back`.
    - In a submenu, `widget_text(nav)` contains `b Back` and does not contain `esc`.
    - Pressing the `escape` key returns to the parent.
12. Add one demo-based test using `build_demo_app()`. It only navigates and runs no actions, so there are no worker or spinner side effects.
    - At the root, type the displayed shortcut for Settings (`s`), then Audio (`a`). That is depth 3.
    - Type the displayed Back shortcut twice and assert the location is `Home`.
    - Type the displayed Exit shortcut and assert the app exits with `return_code == 0`.
13. Add a tiny fixture self-test in `conftest.py` or `test_attach_logging.py`: two `unique_logger("x")` calls return distinct loggers with `handlers == []`.
14. The reserved-set pin `test_reserved_commands_value` (`test_shortcuts.py:23`) needs no change under (a). No existing test pins the text `esc`.

**Acceptance criteria**
- The full suite is green. The previous baseline was 451 passed and 1 strict xfail. Expect the count to rise by the new tests, with still no unexpected failures and the same single xfail.
- Rerun the full suite 3 times, because G1 is a flake class.
- `tests/test_shortcuts.py` collects with no `textual.content` import.
- Mutation check: temporarily revert WP-A's one-line change. The new tests must fail on the Back cell (typed `esc` gives "Unknown command"), then pass again after restoring it.
- Optional, if the integrator has the 3.11 and textual 0.80 environment from round 1: `test_attach_logging.py::test_nested_exclusive_attachments_do_not_resurrect_a_dead_handler` passes in a full run, and `test_shortcuts.py` collects.

### 3. Visible behaviour change

- The Back cell in every submenu now reads `b Back`, where it used to read `esc Back`. The `b` is in yellow.
- Typing `b` + Enter works as before. The Esc key works as before.
- Nothing else is visible. The hint still says "Esc back" and the help table is unchanged.
- Note for the Documenter: the "help and hint wording for q and esc" item (Carry-forward 14) is now consistent. The doc sentence should say that the Back cell shows `b` and the Esc key also goes back.

### 4. Risks

- **Test coupling.** The new test uses `NavBar._render_item`, a private method. If a later phase renames or reshapes it, the test needs a one-line update. The black-box fallback is `widget_lines` plus colour.
- **Pagination.** NavBar shows two rows per page. The new test's menus must stay on one page at `SIZE` (140 wide). Do not point the generic loop at the full demo menu. That is why step 12 only navigates.
- **Lost cue.** Users lose the visual "esc" cue on the Back cell. The hint line still carries it, and I judge this acceptable.
- **Consumers with a `b` shortcut in a submenu.** They are already warned, since `b` is reserved. After (a) the Back cell and the conflicted item both display `b`, but the typed `b` goes to Back, as D6 already specifies. The panel's WARNING line explains it.
- **Factory assert.** It could only fire if some other code registers a logger named `tests.<prefix>.<n>`. I found none. The other `tests.*` names are `tests.other`, `tests.scoped`, `tests.hosted` and `tests.consumer.walkthrough`.
- **Out of scope, record as carry-forward:**
  - the whitespace-shortcut edge;
  - the `sc = 2` width estimate for multi-character shortcuts.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/tests/conftest.py
- /Users/andrewmacleod/workspace/cli_interface/tests/test_shortcuts.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/tests/helpers.py