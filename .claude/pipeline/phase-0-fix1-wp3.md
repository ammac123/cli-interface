## WP-3 review round 1, issue 8: done

I changed one file, `/Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py`. `widgets.py` and `theme.py` are unchanged, and I did not touch `#prompt-hint`.

### What changed
- `MenuItem` is now `@dataclass(repr=False)` with an explicit `__repr__`. The new imports are `fields` from `dataclasses` and `recursive_repr` from `reprlib`.
- `__repr__` walks `fields(self)` and prints `name=value!r` for each field, in the dataclass default format `MenuItem(label=..., ..., secret=...)`. It uses `self.__class__.__qualname__`, as the dataclass default does.
- When `secret` is true and `current_value is not None`, `current_value` prints as `'***'`. The stored value is not changed. I used `***` instead of `••••` so the repr stays ASCII, and it matches the `***` used for exception redaction. `••••` stays in the NavBar.
- Items with `current_value=None` print as `None` even when secret, which is the same as the default.
- `children` still recurses through each child's own `__repr__`, so secrets nested in children are masked and non-secret siblings are not.
- `@recursive_repr()` replaces a cycle with `...` the way the dataclass default does. Without it, a cyclic tree would hit `RecursionError`.
- `eq` is unchanged. `dataclasses.replace` and `==` still work.

### Verification
All commands were run with `uv run`.
- **`verify.py`:** 127 checks pass, up from 112. I added 15 checks to `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp3/verify.py`:
  - **Non-secret repr unchanged:** the repr equals a stock-dataclass reference class with the same fields, for 7 cases. They cover default values, an int, a string, `False`, an action, a string with quotes and brackets, and a nested tree.
  - **Secret with `current_value=None`:** the repr equals the default.
  - **Secret masking:** a secret item with `current_value="SECRET123"` has no `SECRET123` in `repr`, `str` or an f-string `!r`. The repr shows `current_value='***'` and `secret=True`.
  - **Children:** a secret child nested under a parent is masked, a plain sibling's `current_value='visible'` is kept, and the stored value is untouched.
  - **Cycles:** a cyclic non-secret tree and a cyclic secret tree both terminate with `...`, and the secret one stays masked.
  - **Eq and replace:** `dataclasses.replace` and `==` still work.
- **Rendering comparison:** against `fdb8069`, still 75 snapshots with 0 diffs.
- **Imports and conflicts:** `import cli_interface.app` works, and `find_shortcut_conflicts(build_example_menu(...))` still returns `[]`.

My earlier report (sent before this request) still stands. Hardening only: as the review notes, Textual's fatal traceback with `show_locals=True` can still print the `value` local, which is Phase 1 material.