WP-1 is implemented and everything passes. Both owned files are ruff- and mypy-clean, imports work, the acceptance script prints ALL OK, and the existing suite gives 467 passed, 1 xfailed with no failures from my change. I did not commit and touched nothing but `menu.py` and `widgets.py`.

## 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py`
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py`

## 2. Changes by scope ID

**P1.2a (callable labels and values)**
- `MenuItem.label` is now `str | Callable[[], str]`.
- New `item_label(item)` and `item_value(item)`:
  - Both catch `Exception` only and return `"<error>"` on failure.
  - Both log at DEBUG on `cli_interface.menu` with `exc_info`.
  - `item_label` puts the call and the `str()` inside the same `try`, so a result whose `__str__` raises also becomes `"<error>"`.
  - `item_value` returns `Any`, and `None` means no value.
- `MenuState.breadcrumb` and `find_shortcut_conflicts` use `item_label`. The conflict messages are byte-identical for the existing `test_shortcuts.py:44-56` tree (checked in the script). The path label is only resolved when a level actually has a problem.
- In `widgets.py`, `_value_text` now returns `str | None`:
  - A secret item with a non-`None` `current_value` gives `"••••"` without calling anything.
  - Otherwise it goes through `item_value`, followed by a guarded `str()`.
  - A callable returning `None` hides the value.
- `NavBar.render()` builds a per-render snapshot in `self._snap`, keyed by `id(item)` and cleared in a `finally`. `_resolve` falls back to direct evaluation when `_snap` is `None`, so direct `_render_item` / `_compute_item_width` calls from tests work. Each label and value callable runs once per render pass; the script checks the call counts.
- `render()` now delegates to a new private `_render_page()`.

**CF-5 (shortcut whitespace)**
- New `normalize_shortcut`, which is `strip().lower()`.
- `find_shortcut_conflicts` and `MenuState.select_by_shortcut` use it. A whitespace-only shortcut counts as no shortcut, and `" q "` is reported as reserved.
- `select_by_shortcut` returns `None` for an empty normalized key. Before, an empty key would have matched an item with no shortcut.
- NavBar display and width use `item.shortcut.strip()`.

**CF-6**
- `_compute_item_width` uses `len(stripped shortcut) + 1` (0 if none) and the resolved label and value text.
- The script confirms the width equals `len(_render_item(...).plain)` for unselected cells, for shortcut lengths 1-10 and for every hostile item in the script.

**CF-7**
- `@dataclass(repr=False) class _NavCell(MenuItem)` with `kind: Literal["exit", "back"]`.
- `make_nav_cell(kind)` builds "Exit" with shortcut `q` or "Back" with shortcut `b`. The shortcut constants `_EXIT_SHORTCUT` / `_BACK_SHORTCUT` sit beside `RESERVED_ACTIONS`, and the cells leave `description` empty.
- `widgets.py` detects sentinels with `isinstance(item, _NavCell)` in both places.
- `widgets.py` no longer imports `_BACK` or `_EXIT`.

**CF-2 support**
- `ReservedAction` Literal, `RESERVED_ACTIONS` (a `MappingProxyType`), and `reserved_action(text)`.
- `RESERVED_COMMANDS = frozenset(RESERVED_ACTIONS)`, with the same value as before.

**CF-13**
- `#prompt-hint` is now `height: 2`. With the 1-row top padding, the content area is 1 row and "Enter" / "Esc" render.

**CF-14 (widget half)**
- `Dashboard.crumbs: reactive[tuple[str, ...] | None] = reactive(None)`.
- `render()` uses `crumbs` when it is not `None`, otherwise `location.split("|")`. `location` is unchanged.
- A crumb tuple `("a|b", "c")` renders as `a|b › c`.

**CF-16**
- `menu.py:8` UP035 is fixed (imports come from `collections.abc`). Both files are ruff- and mypy-clean.

**MenuState additions**
- `set_root`, `home` and `prune` follow the contract.
- `prune` truncates at the first level that is not identity-reachable from its parent or has no children. It then clamps every remaining index, and returns `True` only if the stack shrank.
- `home` keeps `stack[:1]`, so the root's stored index is preserved. It returns `True` only if the stack had more than one level.

**Docstrings fixed because they became false**
- `MenuItem` fields: `label`, `shortcut` (the whitespace caveat is gone), `description` (the `__back__` / `__exit__` warning is removed) and `current_value`.
- `find_shortcut_conflicts` ("Not detected: whitespace" is removed), `select_by_shortcut`, the `RESERVED_*` comment, the `Dashboard` docstring and the `_compute_item_width` docstring.

## 3. Deviations from the plan
- **NavBar shortcut display keeps the consumer's case.** It uses `.strip()` rather than `normalize_shortcut`, which would lowercase it. The plan's "or `len(shortcut.strip())+1` for display" allows this. It matches baseline display and keeps width equal to the rendered text. If lowercase display is wanted, say so.
- **The snapshot attribute is `_snap`.** Textual's `Widget` already uses `_render_cache`, so I avoided that name.
- **`item_value` does not check `secret` itself.** The contract puts the mask in `_value_text`, which is where I did it. Any other caller of `item_value` must mask secret items first.
- **`make_nav_cell` raises `ValueError` for an unknown kind.** The plan did not specify this.

## 4. Cross-package requests
- **WP-4 must fix `app.py:380`.** `PromptScreen(item.label, ...)` now fails mypy: `Argument 1 to "PromptScreen" has incompatible type "str | Callable[[], str]"; expected "str"`. The fix is `item_label(item)` and is already in WP-4's plan.
- **Baseline `app.py` still builds its Exit/Back cells as plain `MenuItem(description=_EXIT/_BACK)` until WP-4 lands.**
  - Until then they are not `_NavCell`, so unselected they show normal colour instead of dim.
  - Selected, they show orange instead of dim grey.
  - Both are visual only (plan risk 4), and no existing test caught them.
- **`widgets.py` no longer imports `theme._BACK` / `_EXIT`.** WP-4 can delete them from `theme.py`.

## 5. Acceptance results
- `uvx --offline ruff@0.17.3 check --no-cache --target-version py311 --select E4,E7,E9,F,UP,B cli_interface/menu.py cli_interface/widgets.py` printed "All checks passed!".
- `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null --python-version 3.11 --check-untyped-defs cli_interface/menu.py cli_interface/widgets.py` printed "no issues found in 2 source files".
- `uv run --no-sync python -c "import cli_interface, cli_interface.app, cli_interface.menu, cli_interface.widgets"` succeeded.
- Acceptance script `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp1/accept.py` printed ALL OK. It covers:
  - `item_label(MenuItem(lambda: 1/0)) == "<error>"`, plus the `__str__`-raises case and the DEBUG log record.
  - `prune`: removed levels are dropped, the root is kept, indices are clamped, and a level that became a leaf is dropped. Also `home` and `set_root`.
  - `normalize_shortcut(" Q ") == "q"`, `" q "` reported as reserved, `" x"` and `"x "` reported as duplicates, whitespace-only skipped.
  - Nav cells: `isinstance(make_nav_cell("exit"), _NavCell)` is true, a `MenuItem(description="__exit__")` is not, and both shortcuts are in `RESERVED_COMMANDS`.
  - Existing conflict messages are byte-identical, and callable labels appear in messages.
  - `RESERVED_ACTIONS` content, immutability, and `reserved_action`.
  - Pilot checks of NavBar: callables run once per render pass, a secret callable is never called and shows `••••`, a `None` result hides the value, `<error>` is shown for a raising callable, and widths match the rendered cells.
  - Dashboard `crumbs` / `location` fallback.
  - `#prompt-hint` has outer height 2, content height 1, and renders "Enter" and "Esc".
- `mypy cli_interface/` (whole package) reports 3 errors, none in my files: `app.py:230` and `app.py:233` (the Timer typing, which WP-4 fixes) and `app.py:380` (item 4).
- Existing suite, `uv run --no-sync pytest -q -p no:cacheprovider` run without `-x`: 467 passed, 1 xfailed, so no failures from WP-1. WP-2 and WP-3 edits were present in the tree at the time.
  - The xfail is `test_late_timer_ticks_after_teardown_are_harmless`, which is WP-4's.
  - The hint-width test passes because the hint text lives in `theme.py` (WP-4).

## 6. Not verified
- **Wide characters.** Width uses `len()`, as the plan says, not terminal cell width. The width equality was only checked for ASCII and `<error>` text.
- **Real-app rendering.** I only drove NavBar, Dashboard and PromptScreen in a minimal Pilot host, not the full `CLIApp`.
- **Platform and Python versions.** I did not run Windows or Python 3.14, or textual 0.80 / 8.x. mypy was run for 3.11 syntax on the Python 3.13 venv.
- **WP-4 consumers.** `crumbs` population, `_NavCell` dispatch and `home` / `prune` use from the app are untested here.