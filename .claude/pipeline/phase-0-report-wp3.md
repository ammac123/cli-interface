## WP-3 report: menu model, widgets, theme

All WP-3 acceptance criteria were checked and pass. The new `NavBar` and `Dashboard` output is identical to `fdb8069`. Only my three files were edited. I did not touch `display.py` or `log_handler.py` (those diffs are WP-1's), and `.gitignore` was already modified before I started. No git state-changing commands were run, and I created no `tests/` and did not edit `pyproject.toml`.

### 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py`: added `MenuItem.secret: bool = False` as the last field, `RESERVED_COMMANDS` and `find_shortcut_conflicts(root)`. `select_by_shortcut` is unchanged.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py`: `PromptScreen` takes `secret=` and uses `Input(password=...)`. The title and prompt labels use `markup=False`. `Dashboard.render`, `NavBar._render_item` and `NavBar.render` now return `rich.text.Text`. A shared `_value_text(item)` helper masks secret values.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/theme.py`: deleted `_MAX_LOG_LINES`, and `_HINT_TEXT` line 1 now ends `type a shortcut + Enter`.

### 2. Changes mapped to the plan
- **C4, D6, F8 validation (`menu.py`)**
  - `find_shortcut_conflicts` walks the tree with a visited set of `id(node)` as the cycle guard.
  - It checks only menus that have children, groups them by `shortcut.lower()` and skips empty shortcuts.
  - `path` is the labels from the root to the menu joined with `" > "`. Messages use the exact formats from D6.
  - Keys are reported in first-appearance order within a menu, then children are recursed in order.
- **C5, D5, F4 and F1 (`PromptScreen`)**
  - The signature is `(item_label, prompt, *, secret=False)`. The existing positional call in `app.py` still works.
  - The hint Label keeps its markup.
- **D1, F1 (`Dashboard`, `NavBar`)**
  - The cell layouts follow the plan table. Inner colours (shortcut yellow, value dim) layer over the selected-item background.
  - The `(no options)` case and the page footer are also `Text`.
- **D5, F4 (`NavBar` masking)**
  - A `secret=True` item with a non-`None` `current_value` shows `(••••)`.
  - `_compute_item_width` uses the same masked text for its width estimate.
  - `_value_text` uses `f"{value}"`, so non-secret formatting is byte-for-byte as before.
- **D6, F8 (`theme.py`)**
  - The hint wording is as specified. Line 1 is 82 visible characters (was 85) and line 2 is 63.
  - `_MAX_LOG_LINES` is gone from `theme.py`. `display.py` no longer references it (WP-1 has landed).

### 3. Deviations from the plan
- **Reserved and duplicate on the same key.** The plan does not say what happens when a key is both reserved and shared by several items. I emit one reserved message per item and no duplicate message for that key. The duplicate wording ("only the first is reachable") would be false there. A Tester who assumes both messages appear would see a different count.
- **Shared subtrees.** The visited-set guard means a subtree reachable from two parents is checked once, under the path where it is first reached.
- Nothing else departs from the plan.

### 4. Cross-package requests
- None required.
- WP-2 can now use `PromptScreen(item.label, item.prompt, secret=item.secret)`, `find_shortcut_conflicts` and `RESERVED_COMMANDS`.
- **Pre-existing bug, not fixed (it is in my file but outside the plan).**
  - `#prompt-hint` has `height: 1` and `padding: 1 0 0 0`, which leaves a content height of 0.
  - The "Enter confirm / Esc cancel" hint is therefore invisible both at `fdb8069` and now (`hint.py` shows `height=0` for both).
  - The one-line fix is `height: 2`, or dropping the top padding. This changes the dialog layout, so it is your call.

### 5. Acceptance criteria
All the following are verified.
- **Same output as the old code.**
  - I imported the `fdb8069` package as `orig_cli`, captured 75 snapshots from it, then compared the same snapshots from the new code.
  - The snapshots cover widths 60, 80 and 120, five menus (including Back/Exit sentinels, a multi-page menu, empty and `current_value` variants), several selected indexes, and `Dashboard` crumbs, status and spinner states.
  - The comparison is exact on `.plain`, on per-segment colour, background, bold, italic and dim from `render_lines`, and on `_compute_item_width`. 0 diffs.
- **`MenuItem`.** `secret` defaults to `False`, and `MenuItem("a","b","c",[],f,"p",1)` still works.
- **`find_shortcut_conflicts`**
  - A menu with `q` and `Quit`, a duplicate `x`/`X`, and the same shortcut at different levels produces exactly the expected messages.
  - A clean tree gives `[]`, and cyclic trees terminate.
  - `find_shortcut_conflicts(build_example_menu(...)) == []`.
- **Literal rendering.**
  - `nav.render()` and `dash.render()` return `Text`.
  - These samples render verbatim and nothing crashes, checked on `.plain` and on a pilot `render_lines` screen:
    - Samples: `Run [/x]`, `matrix[i][j]`, `C:\data\[/tmp]`, `x\[y`, `[bold]x`, `[bold]x[/bold]`, `[/]`, `[`, `][`.
    - NavBar: labels, `current_value="[/v]"` and `shortcut="[x]"`.
    - Dashboard: breadcrumbs, `status` and `spinner_label`.
- **`PromptScreen`** (bare `App` with `run_test`)
  - The positional call has `password is False`.
  - The keyword form works.
  - `secret=True` gives `password is True`.
  - A title and prompt containing brackets render literally.
  - Enter dismisses with the typed value and Esc dismisses with `None`.
- **Secret masking.** A `secret=True` item shows `Token (••••)` with no raw value, and its width estimate matches the masked width.
- **Theme.** Importing `_MAX_LOG_LINES` from `theme` raises `ImportError`, and the hint has the new wording.
- **Imports.** `import cli_interface.app` and `import cli_interface.example_menu` both succeed in the current tree.

Not verified, because they depend on WP-2:
- The new `_HINT_TEXT` shown inside the real `CLIApp`. I only measured it with `Content.from_markup`.
- The end-to-end secret-prompt flow through `_run_action`.

Scratch files are in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp3/`:
- `capture.py`, `compare.py`, `baseline.json`, `new.json`: the old-vs-new rendering comparison.
- `verify.py`: 112 checks.
- `hint.py`: the hint height check.
- `base/orig_cli/`: the `fdb8069` copy.