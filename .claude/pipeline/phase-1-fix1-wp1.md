Review fix round 1 for WP-1 is done: issue 6 is fixed in `widgets.py`, and ruff, mypy and the acceptance script (now with a re-entry check) all pass. I did not commit and edited only `/Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py`.

**The change** is in `NavBar.render()`, `widgets.py:276-281`. It now saves `prev = self._snap` before setting `self._snap = {}`, and the `finally` restores `self._snap = prev` instead of setting `None`. A nested `render()` therefore leaves the outer pass's snapshot intact. At top level `prev` is `None`, so behaviour there is unchanged. The `_snap` attribute and `_resolve` are untouched.

**Results**
- **ruff:** `uvx --offline ruff@0.17.3 check --no-cache --target-version py311 --select E4,E7,E9,F,UP,B cli_interface/menu.py cli_interface/widgets.py` printed "All checks passed!".
- **mypy:** `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null --python-version 3.11 --check-untyped-defs cli_interface/menu.py cli_interface/widgets.py` printed "no issues found in 2 source files".
- **Acceptance script:** `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp1/accept.py` prints ALL OK.
  - I added the re-entry check. A label callable calls `nav.render()` once during an outer render, and the check asserts the outer snapshot is the same object before and after the nested call, and that `_snap` is `None` once the outer render finishes. The old `= None` code would have left `after` as `None`.
  - I did not run that check against the old code to confirm it fails there.
- **Full suite:** I could not get a clean run.
  - **Cause:** `uv run --no-sync pytest -q -p no:cacheprovider` stops at two collection errors. `tests/test_demo.py` fails on `ModuleNotFoundError: No module named 'cli_interface.example_menu'`, and `tests/test_shortcuts.py` fails on `ImportError: cannot import name '_BACK' from 'cli_interface.theme'`.
  - **Not from this fix:** these are the expected breaks from plan section 5. The working tree now contains the later waves (WP-4 through WP-7: `theme.py` without `_BACK`, `examples/`, `cli.py`), so they come from the demo move and the `theme._BACK` deletion.
  - **Last good run:** the full suite last ran before those packages landed, giving 467 passed and 1 xfailed with WP-1 in place. The re-entry fix is a one-line save and restore, and I did not rerun the suite with the later waves excluded.