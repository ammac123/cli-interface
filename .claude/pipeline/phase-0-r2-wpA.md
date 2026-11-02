## WP-A done: the Back cell now uses `b`

**Diff.** The only change, in `/Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py` (`_build_display_items`), is the new comment line and the `esc` to `b` edit:
```
+        # Sentinel shortcuts must be typeable, so each must be in RESERVED_COMMANDS.
         sentinel = MenuItem("Exit", shortcut="q", description=_EXIT) if at_root \
-              else MenuItem("Back", shortcut="esc", description=_BACK)
+              else MenuItem("Back", shortcut="b", description=_BACK)
```
- The `Binding("escape", ...)`, `_show_help`, `menu.py` and `theme.py` are untouched.
- No git state was changed.

**Scratch check.** I ran `back.py` and `backcolor.py` in `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp2/` under `run_test`. All checks pass.
- **Root:** the NavBar plain text contains `q Exit`, both at the start and again after returning from the submenu.
- **Submenu:** it renders `b Back` and no `esc Back`. The `b` span style is `#e5c07b` (yellow), which meets the plan's colour criterion.
- **Reserved:** the Back sentinel's shortcut is in `RESERVED_COMMANDS`.
- **Navigation:** typing `b` then Enter returns to the parent. The Esc key still goes back. Selecting the Back cell with the arrow keys and Enter still goes back.

**Regressions.**
- My `verify.py` is still clean, with `FAILS: []`.
- `uv run pytest -q tests/test_shortcuts.py` gives **69 passed in 7.91s**. Nothing failed, including any edits the Tester has in progress.