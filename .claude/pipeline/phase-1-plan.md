# Phase 1 plan (planner, round 1): `cli_interface` public API and packaging

Baseline `4cab69a`, branch `phase-1`. Nothing was edited. I ran read-only `uvx --offline ruff@0.17.3 ... --no-cache` and `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null`.

**Measured baseline**
- mypy (`--python-version 3.11 --check-untyped-defs --warn-unused-ignores --warn-redundant-casts --strict-equality`) reports 2 errors. The ledger's `app.py:158/161` is stale: they are now `app.py:230` and `233`. Cause: `_spinner_handle = None` (lines 180-181) is inferred as `None`, so the `set_interval` assignments fail. Typing both handles `Timer | None` fixes it.
- ruff 0.17.3 with `E4,E7,E9,F,UP,B` and target py311 reports 10 errors in the package, none in the Tester's files.
  - `menu.py:8` UP035.
  - `log_handler.py:43,181,226,294,304` UP037.
  - `display.py:225` B905.
  - `example_menu.py:5,79,80` UP035/UP037.
- The same ruff selection reports 22 errors in `tests/`: 18 E741 (a variable named `l`), 3 UP035 (conftest, helpers, test_secrets), 1 UP031 (`test_secrets.py:267`).
- textual 0.80.0 itself requires `rich>=13.3.3`, so lowest-direct can never exercise a `rich` floor of 13.0.

Waves: **W1** = WP-1, WP-2, WP-3. **W2** = WP-4, WP-5. **W3** = WP-6, WP-7.

---

## 1. Design decisions

### Contracts that cross work packages (exact names)

**WP-1 provides, in `cli_interface/menu.py`.** Existing `find_shortcut_conflicts(root) -> list[str]` keeps its signature and its message texts. `tests/test_shortcuts.py:44-56` pins those messages verbatim, and the reported key stays the normalized lowercase key.
```python
@dataclass(repr=False)
class MenuItem:
    label: str | Callable[[], str]          # widened
    shortcut: str = ""
    description: str = ""
    children: list[MenuItem] = field(default_factory=list)
    action: Callable[..., Any] | None = None
    prompt: str | None = None
    current_value: Any = None               # a callable is called with no args at render time
    secret: bool = False

ReservedAction = Literal["quit", "back", "clear", "help"]
RESERVED_ACTIONS: Mapping[str, ReservedAction]
#   {"q":"quit","quit":"quit","exit":"quit","b":"back","back":"back","clear":"clear","help":"help","?":"help"}
RESERVED_COMMANDS: frozenset[str] = frozenset(RESERVED_ACTIONS)    # value unchanged (test_shortcuts.py:23)
def reserved_action(text: str) -> ReservedAction | None            # text.strip().lower() lookup
def normalize_shortcut(shortcut: str) -> str                       # shortcut.strip().lower()
def item_label(item: MenuItem) -> str                              # never raises Exception; "<error>" on failure; str() of the result
def item_value(item: MenuItem) -> Any                              # None = no value; calls a callable; "<error>" on failure
class _NavCell(MenuItem):                                          # @dataclass(repr=False); the Exit/Back sentinel
    kind: Literal["exit", "back"] = "exit"
def make_nav_cell(kind: Literal["exit", "back"]) -> _NavCell       # Exit with shortcut "q", or Back with shortcut "b"
class MenuState:   # existing API kept, plus:
    def set_root(self, root: MenuItem) -> None                     # stack = [(root, 0)]
    def home(self) -> bool                                         # pop to root; True if the stack changed
    def prune(self) -> bool                                        # drop levels no longer reachable from root; clamp indices; True if it shrank
    # breadcrumb now uses item_label; select_by_shortcut compares normalize_shortcut on both sides
```
- **Reachability test.** `prune` checks a level by identity: `any(c is menu for c in parent.children)` and `menu.children` non-empty.
- **Sentinel test.** Anyone detecting the sentinel uses `isinstance(item, _NavCell)`. `==` is forbidden because the dataclass `__eq__` compares fields.
- **`kind` dispatch.** `kind == "exit"` quits; `kind == "back"` goes back.

**WP-1 provides, in `cli_interface/widgets.py`.**
- `Dashboard.crumbs: reactive[tuple[str, ...] | None] = reactive(None)`. `render()` uses `crumbs` when it is not `None`, otherwise `location.split("|")`.
- `Dashboard.location` stays a settable `reactive[str]`, the "|"-joined display string. About 25 test assertions read it, and baseline `app.py` still assigns it during W1.
- `NavBar.items`, `NavBar.selected`, `_compute_item_width(item)`, `_render_item(i, item)` and `_layout_rows(width)` keep their signatures. `test_shortcuts.py:356` calls `_render_item` directly.

**WP-2 provides `cli_interface/warning_types.py` (new).**
```python
class ShortcutConflictWarning(UserWarning): ...
class LoggingAttachWarning(UserWarning): ...
```

**WP-3 provides.**
- `cli_interface/_version.py` containing exactly `__version__ = "0.1.0"`.
- An empty `cli_interface/py.typed`.
- The `[project.scripts]` line `cli-interface = "cli_interface.cli:main"`.

**WP-4 provides, in `cli_interface/app.py` and `theme.py`.**
```python
class CLIApp(App):
    def __init__(self, menu: MenuItem, *, strict_shortcuts: bool = False,
                 max_lines: int | None = 5000, **kwargs: Any) -> None
        # TypeError: menu is not a MenuItem. ValueError: strict conflicts, or max_lines not None / positive int (bool rejected).
    def set_menu(self, menu: MenuItem) -> None
    def refresh_menu(self) -> None
    def go_home(self) -> None
    def _validate_menu(self, menu: MenuItem) -> None      # private; must be callable before super().__init__()
def attach_logging(...)                                    # signature unchanged; warns LoggingAttachWarning, stacklevel=2
def run(menu: MenuItem, *, strict_shortcuts: bool = False, max_lines: int | None = 5000) -> int   # returns app.return_code or 0
```
- `theme._BACK` and `theme._EXIT` are deleted. `theme.py` moves to WP-4 so the tree stays importable between W1 and W2.

**WP-5 provides `cli_interface/__init__.py`:** the D4 `__all__` and `__version__`.

**WP-6 provides `cli_interface/cli.py`:** `def main(argv: Sequence[str] | None = None) -> int`.

**WP-7 provides.**
- `examples/example_menu.py`: `def build_menu(app: CLIApp) -> MenuItem`.
- `examples/example_worker.py`: `log`, `run(steps=14, delay=0.35)`.
- `examples/main.py`: `def main() -> int`, run as `python -m examples.main` from the repo root.
- An empty `examples/__init__.py`.

### D1-D19

| # | Decision (recommended default) | Why |
|---|---|---|
| **D1** | `run(menu)` takes a required `menu`, so `run()` raises `TypeError`. Bare `cli-interface` is an argparse usage error: exit 2 and "the following arguments are required: target". `run()` returns `int`. Nothing falls back to a demo. | The demos leave the wheel. `test_regression.py:88` pins the old signature and is expected to break. |
| **D2** | Spec is `module:attr`, with a dotted attr allowed. The target is a `MenuItem`, or a callable returning one. A callable with at least one required positional parameter is called with the `CLIApp`; otherwise it is called with no arguments. Flags: `--strict-shortcuts`, `--max-lines N` (positive int), `--version`, `-h/--help`. The CLI prepends `os.getcwd()` to `sys.path`, as `python -m` and uvicorn do. Flow: `app = CLIApp(MenuItem("cli-interface"), strict_shortcuts=..., [max_lines=...])`, resolve the target, `app.set_menu(menu)`, `app.run()`, then `return app.return_code or 0`. | Console scripts do not put cwd on the path, so `examples.example_menu:build_menu` would fail from the repo root. Passing the app removes the old `ref`-list and `get_app` lambdas and lets the Worker and Spinner demos work through the console script. It also dogfoods `set_menu` before mount. Phase 2 supersedes this with `App` and `Context`. |
| | Exit codes: 0 or the app's `return_code`; 2 for usage, import or attr failure, wrong return type, or a strict-shortcut `ValueError` (reported with `parser.error`). Exceptions raised inside the user's `build_menu` propagate with a traceback. | |
| | All argparse and `--version` text is ASCII-only. | A Windows cp1252 console would raise `UnicodeEncodeError` on `--help`. |
| | `--help` and `--version` exit inside argparse before any app exists, so no TTY is needed. No non-TTY run path (F7 stays out of scope). | |
| **D3** | Hatch dynamic version from `cli_interface/_version.py` via `[tool.hatch.version] path`. `__init__` does `from ._version import __version__`. The value stays `0.1.0`. | One regex-readable source that works without installing. A bump to 0.2.0 is the user's call. |
| **D4** | `__all__` has exactly 11 names: `CLIApp`, `DisplayPanel`, `LogAttachment`, `LoggingAttachWarning`, `MenuItem`, `RESERVED_COMMANDS`, `ShortcutConflictWarning`, `__version__`, `attach_logging`, `find_shortcut_conflicts`, `run`. Excluded: `PanelInbox`, `TUILogHandler`, `MenuState`, `PromptScreen`, `Dashboard`, `NavBar`, `theme`, and `DisplayPanel`'s helpers. `LogAttachment` is exported only as the return type. Direct construction is discouraged in the docstring only, with no runtime block. | `tests/test_attach_logging.py` constructs it about 25 times with `StubApp`. `RESERVED_COMMANDS` and `find_shortcut_conflicts` are already documented as public. Dropping either is a one-line change. |
| **D5** | Two categories in `warning_types.py`. `ShortcutConflictWarning` is emitted by `_validate_menu`. `LoggingAttachWarning` is emitted by `attach_logging` for the "were ignored because" case. pytest `filterwarnings`: `"error::cli_interface.ShortcutConflictWarning"`, `"error::cli_interface.LoggingAttachWarning"`, and the existing `"error::pytest.PytestUnhandledThreadExceptionWarning"`. | Message-regex filters break silently on rewording. `UserWarning` subclassing keeps `pytest.warns(UserWarning, match=...)` working in `test_attach_logging.py` and elsewhere. |
| **D6** | `label: str \| Callable[[], str]`. `current_value` may be a no-argument callable, and its result `None` means no value is shown. Callables are called on the UI thread, once per item per NavBar render pass (a per-render snapshot), and on every breadcrumb, `Executed:` and `Error in` text build. They must be cheap and side-effect free. An `Exception` is caught and shown as `<error>`, with a DEBUG log on `cli_interface.menu` including `exc_info`; `BaseException` propagates. Results go through `str()`. A callable is never called for `secret` items, which show `••••` whenever `current_value is not None`. | The widget repaints often, so the snapshot keeps layout and render consistent. A raising callable must not crash the app. Receiving the app is deferred to Phase 2's `Context`. |
| **D7** | All three methods are UI-thread only; from another thread use `app.call_from_thread(app.refresh_menu)`. They are legal before mount: the model updates, warnings are queued in `_menu_warnings` and shown by `on_mount`, and the view is skipped. They must work with a `PromptScreen` on top (see D17). The output panel is never touched. | Consistent with `panel` and `start_spinner`; Phase 2 adds thread-safe proxies. |
| | `set_menu(menu)`: check `isinstance(menu, MenuItem)`; validate the new tree; in strict mode a conflict raises `ValueError` before any state change. Otherwise swap the tree, set the stack to `[root]`, selection to 0, breadcrumb to `[label(root)]`, clear the reported set, and warn. | |
| | `refresh_menu()`: re-validate the current tree, then `prune()` the stack, clamp the selection and repaint. Items from callables are re-read and the NavBar repaint is forced. | |
| | `go_home()`: `MenuState.home()`, selection 0, repaint. It is a no-op at root, does no validation, and the panel is untouched. | |
| | **Warning mechanics.** Each warning is a `ShortcutConflictWarning` whose `filename` is the consumer's call site (`test_shortcuts.py:87` asserts `w.filename == __file__`). `stacklevel=3` is correct when `_validate_menu` is called straight from `__init__`, `set_menu` or `refresh_menu`. When the app is mounted, each new problem also goes to the panel as a WARNING line. Dedupe via a reported-problems set: `set_menu` clears it, `refresh_menu` only surfaces problems not already in it, and a problem that disappears is removed so it can re-warn. | |
| **D8** | Strip, no warning. One `normalize_shortcut` is used everywhere: conflict check, `select_by_shortcut`, NavBar display and width. A whitespace-only shortcut becomes "no shortcut". Duplicates and reserved words are detected after stripping, so `" q "` is reported. | Mutating the field would be bypassed by later assignment. Normalizing at use sites cannot be bypassed. |
| **D9** | `max_lines`: `None` means unbounded, passed straight to `RichLog(max_lines=None)`. Anything other than `None` or a positive `int` (bool excluded) raises `ValueError`, before `super().__init__()`. Keyword-only and the default 5000 are unchanged (pinned at `test_regression.py:43`). CLI `--max-lines` accepts positive ints only. | Matches the Textual semantics. `0` currently trims nothing but still advances `_start_line`. |
| **D10** | `scripts/check_dist.py` is stdlib-only and runnable locally: `python scripts/check_dist.py ARTIFACT [ARTIFACT ...]`. It takes `.tar.gz` and `.whl` paths and exits 1 on any violation. Allowlists (regexes, directory members ignored): see below. | A CI-only check cannot be verified locally. |
| **D11** | CI shape: see WP-3. 3.14 with textual 0.80 is flagged as a risk; see section 7. | |
| **D12** | Declare `rich>=13.3.3` instead of the ledger's literal `rich>=13`. | Under textual 0.80 the resolver cannot pick below 13.3.3, so the literal floor is untestable. Reversible in one line; raise at close. |
| **D13** | mypy covers `cli_interface`, `examples` and `scripts`, not `tests/`. ruff covers all four paths. There is no `ruff format` and no `RUF` rules. | Formatting would rewrite the aligned-assignment style in every file. |
| **D14** | The sdist includes `examples/`; the wheel does not. | The README points at the examples and they are small. |
| **D15** | The Exit/Back cells are built with `make_nav_cell`; their shortcuts are `q` and `b`, defined beside `RESERVED_ACTIONS`. | One place for the "sentinel shortcuts must be reserved" convention. |
| **D16** | Help `q` and `b` rows and the hint `q` entry gain "+ Enter". Constraint: both plain hint lines stay at or below 85 characters and the first still contains "type a shortcut + Enter". If it does not fit, move the `q` entry to line 2. | `test_shortcuts.py:323-327` pins the width budget; the Tester updates the exact `82`. |
| **D17** | Every internal widget lookup (`_refresh_view`, `_tick_spinner`, both `_cycle_*`, the `action_move_*` actions, `set_menu`/`refresh_menu`/`go_home`) goes through the base screen (`self.screen_stack[0]`) or refs cached at mount. `self.query_one` resolves on the active screen, so with a `PromptScreen` open it raises `NoMatches`, even today in a spinner tick. | A consumer calling `refresh_menu()` through `call_from_thread` while a prompt is open must not crash. |
| **D18** | CF-17: override `CLIApp._fatal_error` to build `Traceback(show_locals=False, width=None, suppress=[rich])`. The rest is a copy of Textual's body: `self.bell()`, append `Segments(self.console.render(traceback, self.console.options))` to `self._exit_renderables`, then `self._close_messages_no_wait()`. Verified: the body is identical in textual 0.80.0 and 8.2.8. | The override is dead but harmless if Textual drops the method. |
| **D19** | CF-11: the demo logger is `logging.getLogger("examples.example_menu")` (a fixed name), with `propagate = False`. Settings actions run inside `with attach_logging(app, log, level=logging.INFO):` per call. `attach_logging` is documented as UI-thread and while-running, which holds inside an action. The demo's lazy attach, with no pre-run attach, is the chosen mechanism. | `propagate=False` prevents each record appearing twice while the Worker Demo's exclusive root capture is on. |

**Allowlists for D10** (sdist root `cli_interface-<ver>/`; patterns are flat):
- **sdist allows:** `PKG-INFO`, `pyproject.toml`, `README.md`, `LICENSE`, `CHANGELOG.md`, `cli_interface/[A-Za-z_]+\.py`, `cli_interface/py.typed`, `examples/[A-Za-z_]+\.py`.
- **wheel allows:** `cli_interface/[A-Za-z_]+\.py`, `cli_interface/py.typed`, and `cli_interface-<ver>.dist-info/(METADATA|WHEEL|RECORD|entry_points.txt|licenses/LICENSE|LICENSE)`.
- **Anything else fails.** Explicit deny messages for `tests/`, `.claude/`, `.github/`, `scripts/`, `uv.lock`, `main.py`, `.python-version`, `__pycache__`, `*.pyc`, `whiteboard`, and `example_*` inside `cli_interface/`.
- **Required members.**
  - Package files in both archives: `cli_interface/{__init__,_version,app,cli,display,log_handler,menu,phrases,theme,widgets,warning_types}.py` and `cli_interface/py.typed`.
  - sdist only: `examples/{__init__,example_menu,example_worker,main}.py`.
  - wheel only: `entry_points.txt`, whose content must contain `cli-interface = cli_interface.cli:main`.
- **Metadata (stdlib parse).**
  - `Requires-Python: >=3.11`.
  - A `rich>=13.3.3` Requires-Dist.
  - A textual Requires-Dist whose specifier set equals `{">=0.80", "<9"}`.
  - The wheel and sdist versions equal each other and equal `_version.py`.
- **Hatch extras.** The executor must record any extra file hatch force-adds and add it to the allowlist explicitly. Expected extras are `PKG-INFO`, `pyproject.toml`, and license files.

---

## 2. Work packages

**Self-check commands for every executor** (they do not touch `.venv` or `uv.lock`; the config reads from `pyproject.toml` once WP-3 lands):
```
uvx --offline ruff@0.17.3 check --no-cache --target-version py311 --select E4,E7,E9,F,UP,B <owned files>
uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null --python-version 3.11 --check-untyped-defs <owned files>   # report only errors in owned files
uv run --no-sync python -c "import cli_interface.<module>"
```
WP-3 runs `uv sync`, `uv lock` and `uv build` only with `UV_PROJECT_ENVIRONMENT=<scratch dir>`, never against the shared `.venv`.

### WP-1 (wave 1): model and widgets
- **Owns:** `cli_interface/menu.py`, `cli_interface/widgets.py`.
- **Consumes:** nothing new. `widgets.py` stops importing `_BACK`/`_EXIT`, so baseline `theme.py` still works until WP-4.
- **Provides:** everything listed under WP-1 above.
- **Work.**
  - **`menu.py`.**
    - Add the types and helpers above, plus `RESERVED_ACTIONS`.
    - Widen `MenuItem.label`.
    - `find_shortcut_conflicts` and `MenuState.breadcrumb` use `item_label` and `normalize_shortcut`.
    - Add `MenuState.set_root`, `home`, `prune`.
    - Update the one-line docs of `shortcut` and `description` only where they are now false.
  - **`widgets.py`.** Fix read sites:
    - `_value_text`: secret masks with no call; the callable goes through `item_value`.
    - `_compute_item_width`: `len(item_label(item))`, and the shortcut term becomes `len(normalize_shortcut(item.shortcut))+1` (or `len(shortcut.strip())+1` for display), replacing `sc = 2`.
    - `_render_item`: use `item_label` and the stripped shortcut.
    - Sentinel detection via `isinstance(item, _NavCell)` in both places (currently `widgets.py:183` and `:211`).
    - `render()` resolves each item once per pass into a per-render snapshot, with direct calls still working when `_render_item` is called by tests.
    - `#prompt-hint { height: 2 }` (CF-13; with `padding: 1 0 0 0` and `height: 1` the content area is 0).
    - `Dashboard.crumbs` per the contract.
  - Both files ruff- and mypy-clean (UP035 in `menu.py:8`).
- **Acceptance.**
  - Both owned files are ruff- and mypy-clean.
  - `uv run --no-sync python -c "import cli_interface.menu, cli_interface.widgets"` succeeds.
  - A scratch script (not committed) checks:
    - `item_label(MenuItem(lambda: 1/0))=="<error>"`.
    - `MenuState.prune` drops a removed level and keeps the root.
    - `normalize_shortcut(" Q ")=="q"` and `find_shortcut_conflicts` reports `" q "`.
    - `isinstance(make_nav_cell("exit"), _NavCell)`, while a plain `MenuItem(description="__exit__")` is not.
    - `make_nav_cell("exit").shortcut` and `make_nav_cell("back").shortcut` are in `RESERVED_COMMANDS`.
    - Conflict message texts are byte-identical for the existing `test_shortcuts.py:44-56` tree.
- **IDs:** P1.2a, CF-5, CF-6, CF-7, CF-13, CF-14 (widget half), CF-16 for these files.

### WP-2 (wave 1): leaf modules and warning categories
- **Owns:** `cli_interface/log_handler.py`, `cli_interface/display.py`, `cli_interface/phrases.py`, `cli_interface/warning_types.py` (new).
- **Work.**
  - `warning_types.py` per the contract.
  - Remove the 5 quoted annotations in `log_handler.py` (lines 43, 181, 226, 294, 304).
  - `display.py:225` becomes `zip(headers, row, strict=False)`. Keep `strict=False`: `True` crashes on ragged CSV rows.
  - Confirm `phrases.py` is clean.
  - No other behaviour change; the `LogAttachment` constructor stays public (about 25 test sites).
- **Acceptance.** Both tools are clean on the 4 files; import succeeds; `git diff` shows no behavioural change outside the listed lines.
- **IDs:** CF-3 (categories), CF-16 for these files.

### WP-3 (wave 1): packaging, lint config, CI, dist check
- **Owns:** `pyproject.toml` (all of it except `[tool.pytest.ini_options]`), `uv.lock`, `cli_interface/_version.py`, `cli_interface/py.typed`, `scripts/check_dist.py`, `.github/workflows/ci.yml`.
- **Work.**
  - Write the `pyproject.toml` from section 4.
  - Relock: try `uv lock --offline` first (ruff 0.17.3 and mypy 2.4.1 are in the uv cache). If it needs the network, stop and report; do not hand-edit the lock.
  - Write `scripts/check_dist.py` per D10.
  - Write the CI file:
    - **Triggers/defaults:** triggers `push` to `main` and `pull_request`; `concurrency` with cancel-in-progress; `fail-fast: false`; `timeout-minutes: 20`.
    - **`lint` job:** ubuntu, Python 3.13, `uv sync --locked --no-default-groups --group lint`, then `ruff check cli_interface examples scripts tests` and `mypy cli_interface examples scripts`.
    - **`test` job:**
      - Matrix: os {ubuntu, macos, windows} × python {3.11, 3.12, 3.13, 3.14}, resolution `locked`.
      - Two extra `include` legs: ubuntu 3.11 and ubuntu 3.14 with `lowest-direct`.
      - Locked legs: `uv sync --locked --no-default-groups --group test`.
      - Lowest legs: `uv sync --resolution lowest-direct --no-default-groups --group test`, plus a step asserting textual is 0.80.0.
      - Every leg: `uv run --no-sync pytest -q`, then a console-script smoke (`cli-interface --version`, `--help`, and a bad target that must exit 2) under `shell: bash`.
    - **`build` job:** ubuntu; `uv build --out-dir dist` (sdist then wheel-from-sdist), `python scripts/check_dist.py dist/*.tar.gz dist/*.whl`, then install the wheel into a clean venv and run `cli-interface --version` and `--help`.
    - The lowest-direct legs run pytest only; ruff and mypy stay on the locked `lint` job, because lint tool floors are not meaningful.
- **Acceptance.**
  - `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` succeeds.
  - `uv lock --check` succeeds (offline or not).
  - `uv build --out-dir <scratch>` succeeds.
  - `python scripts/check_dist.py <scratch>/*.tar.gz <scratch>/*.whl` fails with exactly this interim list: `cli_interface/cli.py` and `cli_interface/warning_types.py`... no: `warning_types.py` is present after WP-2, so the list is only the missing `cli_interface/cli.py` and `examples/*` (WP-6 and WP-7), plus the unexpected `cli_interface/example_menu.py` and `example_worker.py` (WP-7 deletes them). It becomes green at integration.
  - Negative controls (a hand-made tarball in the scratch dir with `tests/x.py`, `uv.lock` or `.claude/y` added) exit 1.
  - The CI YAML parses (`python -c "import json,sys"` is not enough, so read it by eye; no PyYAML dependency is added).
- **IDs:** P1.1b (`py.typed`, `__version__` source), P1.3, P1.4a, P1.5 config/CI/check, CF-16 config.

### WP-4 (wave 2): `app.py` and `theme.py`
- **Owns:** `cli_interface/app.py`, `cli_interface/theme.py`.
- **Consumes:** WP-1 (menu contracts, `Dashboard.crumbs`, `_NavCell`) and WP-2 (`warning_types`).
- **Size.** About 25 distinct edits, roughly +170 and −40 lines in a 583-line file. One executor can do it in this order:
  1. Lifecycle, types and D17 lookups.
  2. `_validate_menu` and the three public methods.
  3. Dispatch and sentinel changes.
  4. `run`, `max_lines`, `_fatal_error`.
  - If it proves too large, the fallback is to move the `set_menu`/`refresh_menu`/`go_home`/`_validate_menu` group into a new mixin module owned by a separate WP. Not recommended: that splits one file's state across modules.
- **Work.**
  - **CF-1 timers.**
    - Add `if not self.is_running: return` to `_tick_spinner`, `_cycle_spinner_phrase`, `_cycle_phrase`.
    - Store all three handles as `Timer | None`: `_spinner_handle`, `_spinner_phrase_handle`, and a new `_phrase_handle` for the 45-second interval.
    - `on_mount` creates `_phrase_handle` only if it is `None`. `on_unmount` stops and clears all three, before closing the inbox.
    - This also fixes the 2 mypy errors at `app.py:230`, `233`.
  - **CF-2 dispatch.** Replace the inline tuples (`app.py:472-482`) with `reserved_action(cmd)`. A `_NavCell` is dispatched by `kind`.
  - **CF-4, P1.2b.**
    - `_validate_menu(menu)` returns nothing and raises or warns per D7.
    - Call it from `__init__` (before `super().__init__()`, so strict still raises before anything is created), `set_menu` and `refresh_menu`.
    - Dedupe via a reported set.
    - Use the `_view_ready` guard so these methods are legal before mount and after exit.
  - **P1.2a read sites in `app.py`.** `_execute_item`: `"no action bound"` and the `PromptScreen` title. `_run_action`: the `Executed:` and `Error in` lines. `_refresh_view`: the breadcrumb. All use `item_label`. Set both `dash.crumbs = tuple(labels)` and `dash.location = "|".join(labels)`. Always end `_refresh_view` with `nav.refresh(layout=True)`, because assigning an equal list to a reactive does not fire the watcher.
  - **CF-7.** `_build_display_items` uses `make_nav_cell`; `_activate` uses `isinstance(item, _NavCell)`; `_activate` also switches from `item in real_children` / `.index(item)` to identity.
  - **CF-8, CF-10, D1.** The new `run` signature; `max_lines` validation (D9); `compose` passes `max_lines` through.
  - **CF-15.** Help rows `q / quit / exit + Enter` and `b / back + Enter`. `theme._HINT_TEXT` per D16. Delete `_BACK` and `_EXIT` from `theme.py`.
  - **CF-17.** The `_fatal_error` override per D18.
  - **`attach_logging`.** Warn with `LoggingAttachWarning`; the message text is unchanged.
  - **Docstrings.** Minimal; fix only the statements that are now false (class `max_lines`, `run`).
- **Acceptance.**
  - Both files ruff- and mypy-clean (0 mypy errors, down from 2).
  - `import cli_interface.app` succeeds.
  - A scratch Pilot script (not committed) shows:
    - `set_menu` on a mounted app resets the breadcrumb.
    - `refresh_menu` after an in-place edit keeps the stack.
    - `refresh_menu` while a `PromptScreen` is open does not raise.
    - Calling `on_mount` twice yields one `_phrase_handle`.
    - After `run_test` exits, `app._tick_spinner()` returns without raising.
    - A consumer `MenuItem(description="__exit__")` activates normally.
    - Warning filenames equal the call site.
    - `max_lines=0`, `-1`, `True` raise `ValueError`.
    - `run(menu, strict_shortcuts=True)` with a clean menu returns 0 under a monkeypatched `CLIApp.run`.
- **IDs:** P1.2b, CF-1 (code), CF-2, CF-4, CF-8, CF-10, CF-15, CF-17, CF-16 mypy and style for these files.

### WP-5 (wave 2): facade
- **Owns:** `cli_interface/__init__.py`.
- **Consumes:** WP-1, WP-2, WP-3 (`_version`). Every imported name exists by the end of W1 (`CLIApp`, `attach_logging` and `run` already exist at baseline).
- **Work.** About 25 lines: re-export the 11 names with the D4 `__all__`, `from ._version import __version__`, a one-line module docstring.
- **Acceptance.**
  - Ruff- and mypy-clean.
  - `python -c "import cli_interface as c; assert sorted(c.__all__)==sorted([...D4 list...]); [getattr(c,n) for n in c.__all__]"`.
  - `PanelInbox`, `TUILogHandler`, `MenuState` are not importable via `from cli_interface import *`.
  - Importing the package does not touch logging config.
- **IDs:** P1.1a, CF-9.

### WP-6 (wave 3): console script
- **Owns:** `cli_interface/cli.py` (new).
- **Consumes:** WP-4 (`set_menu`, `CLIApp` signature) and WP-3 (`_version`).
- **Work.** Implement D2. Notes:
  - Pass `max_lines` to `CLIApp` only when the flag was given.
  - A `build_menu` that fails the one-positional-parameter test is called with no arguments.
  - Use `raise ... from` throughout (B904).
- **Acceptance.**
  - Ruff- and mypy-clean.
  - `uv run --no-sync cli-interface --version </dev/null` prints an ASCII version and exits 0.
  - `--help </dev/null | cat` exits 0, with ASCII-only help.
  - `cli-interface </dev/null` and `cli-interface nocolon </dev/null` and `cli-interface no.such.mod:x </dev/null` all exit 2 with one-line errors.
  - The wrong return type exits 2.
  - A scratch module outside the repo with `def build_menu(app): return MenuItem(...)` resolves from cwd.
  - A target for the strict-conflict path exits 2 with the problem list.
- **IDs:** P1.4c.

### WP-7 (wave 3): demos move
- **Owns:** `examples/__init__.py`, `examples/example_menu.py`, `examples/example_worker.py`, `examples/main.py`; deletes `cli_interface/example_menu.py`, `cli_interface/example_worker.py`, `main.py`. Use `git mv` for history.
- **Consumes:** WP-5 (facade) and WP-4 (`set_menu`, `go_home`).
- **Imports.** Facade only: `from cli_interface import CLIApp, MenuItem, attach_logging`, plus `textual.css.query.NoMatches`. Intra-example imports are relative (`from . import example_worker`). No `cli_interface.<submodule>` imports.
- **Work.**
  - `build_menu(app)`: no `get_app is None` branches; `app.panel` is used directly.
  - Settings capture per D19.
  - Dogfood P1.2a: at least one callable `current_value` (Set Port, Toggle Debug) and one callable `label`.
  - "Reset All" ends with `app.go_home()`.
  - `main.py`: `app = CLIApp(MenuItem("Home")); app.set_menu(build_menu(app)); app.run()`, returning `app.return_code or 0` from `main()`. Only `python -m examples.main` is a supported launcher.
  - Ruff- and mypy-clean (UP035/UP037 disappear with the facade imports).
- **Acceptance.**
  - Both tools are clean on `examples/`.
  - `uv run --no-sync python -c "import examples.main"` succeeds without starting the app.
  - A scratch Pilot script shows: View Output renders; `Settings > Audio > Volume Low` writes "Volume set to 25%" exactly once; the Worker Demo, with its exclusive root capture active, still writes each Settings record once; no `TUILogHandler` is left on any logger afterwards.
- **IDs:** P1.4b, CF-11, CF-16 for these files.

---

## 3. Scope ID coverage

| ID | Owner |
|---|---|
| P1.1a (`__init__`, `__all__`) | WP-5 |
| P1.1b (`py.typed`, `__version__` source) | WP-3 |
| P1.2a (callable labels and values) | WP-1 (model and widgets); WP-4 uses them at the app read sites |
| P1.2b (`set_menu`/`refresh_menu`/`go_home`) | WP-4 |
| P1.3 | WP-3 |
| P1.4a (sdist include list), P1.4b (demos move), P1.4c (console script) | WP-3, WP-7, WP-6 respectively |
| P1.5 | WP-3 (config, CI, `check_dist.py`). Per-file cleanliness: see CF-16. |
| CF-1 | WP-4 (code). The Tester removes the xfail marker. |
| CF-2 | WP-4 (dispatch); WP-1 supplies `RESERVED_ACTIONS` |
| CF-3 | WP-2 (categories); WP-4 emits them; the Tester switches `filterwarnings` |
| CF-4 | WP-4 |
| CF-5, CF-6, CF-7, CF-13 | WP-1 (WP-4 consumes `_NavCell`) |
| CF-8 | WP-4 |
| CF-9 | WP-5 |
| CF-10 | WP-4 |
| CF-11 | WP-7 |
| CF-12 | Tester (WP-7 supplies the new module paths) |
| CF-14 | WP-1 (`Dashboard.crumbs`); WP-4 populates it |
| CF-15 | WP-4 (hint in `theme.py`, help rows in `app.py`) |
| CF-16 | Distributed: config in WP-3. Each WP makes its own files ruff- and mypy-clean: menu/widgets WP-1; log_handler/display/phrases/warning_types WP-2; app/theme WP-4 (including the 2 mypy errors); `__init__` WP-5; cli WP-6; examples WP-7. `tests/` (22 ruff hits) goes to the Tester. |
| CF-17 | WP-4 |

---

## 4. Lint and type config (verbatim for `pyproject.toml`)

Everything except `[tool.pytest.ini_options]`, which stays as it is until the Tester edits it.

```toml
[project]
name = "cli-interface"
dynamic = ["version"]
description = "TUI frontend for project settings navigation"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "rich>=13.3.3",
    "textual>=0.80,<9",
]
classifiers = [
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Programming Language :: Python :: 3.14",
    "Typing :: Typed",
]

[project.scripts]
cli-interface = "cli_interface.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.version]
path = "cli_interface/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["cli_interface"]

[tool.hatch.build.targets.sdist]
only-include = ["cli_interface", "examples", "README.md", "LICENSE", "CHANGELOG.md"]
exclude = ["**/__pycache__", "**/*.py[cod]"]

[dependency-groups]
test = ["pytest>=9.2.0", "pytest-asyncio>=1.4.1"]
lint = ["ruff>=0.17", "mypy>=2.4"]
dev = [{ include-group = "test" }, { include-group = "lint" }]

[tool.ruff]
target-version = "py311"
line-length = 120

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "UP", "B"]

[tool.mypy]
python_version = "3.11"
check_untyped_defs = true
warn_unused_ignores = true
warn_redundant_casts = true
no_implicit_optional = true
strict_equality = true
```

- **No `files` key.** Adding `examples` there would error before WP-7 exists. Both tools run with explicit paths: `ruff check cli_interface examples scripts tests` and `mypy cli_interface examples scripts`.
- **No per-file ignores.** The measured tests baseline needs none: the E741 hits are fixable renames.
- **Selection.** I rejected `E501`, `I` and `RUF`: the first two would churn aligned style, and `RUF012` fires on Textual's `BINDINGS` and `CSS`.
- **Verified baseline.** With these flags mypy shows only the 2 `app.py` errors, and ruff shows the 10 package hits listed above.
- **End state.** Every owned file is ruff-clean and mypy-clean. The Tester makes `tests/` ruff-clean; mypy on tests is not required.

**What the Tester changes in `[tool.pytest.ini_options]`:**
```toml
filterwarnings = [
    "error::cli_interface.ShortcutConflictWarning",
    "error::cli_interface.LoggingAttachWarning",
    "error::pytest.PytestUnhandledThreadExceptionWarning",
]
```
Delete the old message regex line and its comment. `pythonpath = ["."]` already makes `examples` importable.

---

## 5. Test notes for step 4

### What must be proven, per ID
- **P1.1a/CF-9.** `__all__` equals the D4 set exactly; every name resolves; the excluded names are not in `__all__`; `LogAttachment` is exported; `__version__` equals `importlib.metadata.version("cli-interface")`. Importing the package configures no logging.
- **P1.1b/P1.3.** `py.typed` exists via `importlib.resources`. `tomllib` assertions on `pyproject.toml`: `requires-python`, dependencies, dynamic version, the script line.
- **P1.2a.**
  - Callable label and value render in the NavBar, breadcrumb and `Executed:` line.
  - A raising callable shows `<error>`, the app stays alive, and the failure is logged at DEBUG.
  - A secret item's callable is never invoked and shows `••••`.
  - Width calculation with a callable label.
  - Callable returning `None` hides the value; a non-string result goes through `str()`.
  - Callable labels in conflict messages.
- **P1.2b/CF-4.**
  - `set_menu` resets stack, selection and breadcrumb, and validates (warning category, `filename == __file__`, panel WARNING line).
  - Strict mode raises `ValueError` and leaves the old menu intact.
  - Legal before mount; `TypeError` on a non-`MenuItem`.
  - `refresh_menu` picks up in-place edits, keeps the stack and selection, prunes a removed level, and re-warns only for new problems.
  - `go_home` from depth 3 and at root.
  - All three work with a `PromptScreen` open and via `call_from_thread` from a worker.
  - The panel is untouched by all three.
- **P1.4a.** Unit tests for `scripts/check_dist.py` with synthetic archives: positive, plus negatives for `tests/`, `.claude/`, `uv.lock`, `example_*` in the wheel, missing `py.typed`, wrong version, wrong script line. The real build is the Integrator's.
- **P1.4c.** `main()` with `CLIApp.run` monkeypatched: resolution of `MenuItem` / zero-argument callable / app-taking callable / dotted attr; each error path and its exit code; flags reach `CLIApp`; ASCII-only help; `--help` and `--version` in a subprocess with `stdin=DEVNULL` and no TTY. The `sys.path` mutation must be restored by the test.
- **CF-1.**
  - Remove the xfail marker (the test must now pass).
  - `on_mount` called twice leaves one timer of each kind.
  - `on_unmount` stops all three.
  - Ticks after teardown are harmless, and a spinner tick with a `PromptScreen` open does not raise.
- **CF-2.** For every key of `RESERVED_ACTIONS` (and upper-case), typing it triggers the mapped action; `set(RESERVED_ACTIONS.values())` is the four actions; `RESERVED_COMMANDS == frozenset(RESERVED_ACTIONS)`; a source check that `app.py` has no literal reserved-word tuples.
- **CF-3.** Both classes subclass `UserWarning`; `pytest.warns(ShortcutConflictWarning)` and `pytest.warns(LoggingAttachWarning)`; the `pyproject.toml` filter lines are the category form and the old regex is gone.
- **CF-5.** `" x "` matches typed `x`; `" q "` is reported as reserved; `"x"` and `" x"` are reported as duplicates; display and width use the stripped text; whitespace-only counts as no shortcut.
- **CF-6.** `_compute_item_width(item)` equals the rendered cell width for shortcuts of length 1-10, so rows do not overflow.
- **CF-7.** A consumer leaf with `description="__exit__"` or `"__back__"` runs its action and does not quit or go back; the real Exit and Back cells still work.
- **CF-8/CF-10.** `run()` passes `strict_shortcuts` and `max_lines` (`CLIApp.run` patched); `max_lines=None` is unbounded (more than 5000 lines kept); `0`, `-1`, `True`, `"5"` raise `ValueError`.
- **CF-11.** Settings actions produce their log line exactly once, with and without the Worker Demo's root capture; no handler leaks (the conftest guards cover this).
- **CF-13.** `#prompt-hint` renders at least one line containing "Enter" and "Esc".
- **CF-14.** A label containing `|` shows as one crumb in `dash.render().plain`; add `"a|b"` to the hostile samples.
- **CF-15.** The hint's `q` entry and the help `q` and `b` rows contain "+ Enter".
- **CF-17.** Call `app._fatal_error()` from inside an `except` block holding a secret local and assert the rendered `_exit_renderables` text does not contain it. This must pass on textual 0.80 and 8.x.
- **CF-12.** Update all demo-coupled tests to the new paths (listed below).
- **CF-16.** `tests/` must be ruff-clean: rename `l`, switch `Callable` imports to `collections.abc`, replace the `%` format.

### Tests that will break between step 2 and step 4 (expected; tell the Reviewer)
| File | Why |
|---|---|
| `tests/conftest.py` lines 118, 131, 143 | `from cli_interface import example_worker` raises ImportError, so the `gated_worker` and `fast_worker` fixtures error at setup. |
| `tests/helpers.py` line 172 | `build_demo_app` imports `cli_interface.example_menu.build_example_menu`. |
| `tests/test_demo.py` | Collection error: line 15 imports `build_example_menu`; line 66 `import main` and `REPO / "main.py"` no longer exist. |
| `tests/test_real_run.py` lines 109, 137 | Demo tests use `build_demo_app`, `gated_worker`, `fast_worker`. |
| `tests/test_shortcuts.py` | Collection error at line 12 (`_BACK`, `_EXIT` removed from `theme`); line 446 `build_demo_app`; line 387 `is_sentinel` via `description`. Also lines 401, 409, 412, 454, 460 compare `description` to `_EXIT` / `_BACK`. Line 327 `assert len(first) == 82` fails once the hint changes. |
| `tests/test_regression.py` | `test_late_timer_ticks_after_teardown_are_harmless` becomes XPASS under `strict=True`, which fails. Lines 88-89 pin `list(params(run)) == ["menu"]` and `default is None`. |
| `pyproject.toml` `filterwarnings` | Not a break (the old regex still matches the subclasses) but switch it in step 4. |
| `tests/test_attach_logging.py` line 310, `tests/test_shortcuts.py` line 87 | Stay green only if the `stacklevel` contract in D7 holds. |
| Probe `probes/pkg/smoke_test.py` | It imports `example_menu`. It is already a baseline repro; mark it not applicable. |

Probes that remain useful as sanity checks: `probes/io/exp2_after_exit.py` (attach/detach lifecycle under the new `on_unmount`) and `probes/io/exp6_exit_latency.py` (timer teardown must not slow exit).

---

## 6. Integration verification (step 5)

Run all of this on a scratch copy, because `uv sync --resolution lowest-direct` rewrites `uv.lock`:
```
SCR=<scratchpad>/phase1-int; rsync -a --exclude .venv --exclude .git --exclude __pycache__ --exclude .pytest_cache --exclude dist ./ "$SCR/"; cd "$SCR"
# locked/highest, 3.13
export UV_PROJECT_ENVIRONMENT="$SCR/.venv-high"
uv sync --locked --python 3.13
uv run --no-sync ruff check --no-cache cli_interface examples scripts tests
uv run --no-sync mypy --cache-dir=/dev/null cli_interface examples scripts
uv run --no-sync pytest -q -p no:cacheprovider
uv run --no-sync python -c "import cli_interface as c; print(c.__version__, len(c.__all__))"
# lowest-direct on 3.11 and 3.14
for PY in 3.11 3.14; do
  export UV_PROJECT_ENVIRONMENT="$SCR/.venv-low-$PY"
  uv sync --python $PY --resolution lowest-direct --no-default-groups --group test
  uv pip list --python "$UV_PROJECT_ENVIRONMENT/bin/python" | grep -Ei '^(textual|rich) '     # expect textual 0.80.0, rich 13.3.3
  uv run --no-sync pytest -q -p no:cacheprovider
  uv run --no-sync cli-interface --version </dev/null
  uv run --no-sync cli-interface --help </dev/null | cat
  uv run --no-sync cli-interface </dev/null; echo "exit=$?"        # expect exit=2
done
# build and allowlist
uv build --out-dir "$SCR/dist"
python scripts/check_dist.py "$SCR"/dist/*.tar.gz "$SCR"/dist/*.whl
uv lock --check
# clean-venv install of the wheel
uv venv "$SCR/v" --python 3.11 && uv pip install --python "$SCR/v/bin/python" "$SCR"/dist/*.whl
"$SCR/v/bin/cli-interface" --version </dev/null; "$SCR/v/bin/cli-interface" --help </dev/null | cat
"$SCR/v/bin/python" -c "import importlib.resources as r, cli_interface; assert r.files('cli_interface').joinpath('py.typed').is_file()"
(cd /; "$SCR/v/bin/python" -c "import examples") ; echo "expect ModuleNotFoundError"
```
Also: `git status --porcelain` shows no `tests/`, `.claude/`, `uv.lock` in the sdist; and the working tree's `uv.lock` is unchanged by these commands because they ran on the copy.

**Cannot be verified locally:** the Windows leg (console-script `.exe` shim, path separators in `check_dist.py`, any POSIX assumptions in the 467-test suite, glyph and cp1252 behaviour) and macOS-latest/ubuntu-latest runner specifics. The YAML is never executed; check it by reading, including that `uv sync` flags exist in uv 0.12.5 (they do: `--locked`, `--no-default-groups`, `--group`, `--resolution`).

---

## 7. Risks and open questions

**Questions to raise at close:** D1 (required `menu`), D2 (the target contract, the app parameter, cwd on `sys.path`), D3 (stay at 0.1.0?), D4 (11 names), D5 (two warning categories), D6 (render-time evaluation, `<error>` fallback), D8 (strip, no warning), D9 (`None` = unbounded), D12 (`rich>=13.3.3` instead of the literal `>=13`), D14 (sdist ships `examples/`).

**Risks**
1. **textual 0.80 on Python 3.14 is untested.** Phase 0 verified 0.80 only on 3.11. Both ubuntu lowest-direct legs (3.11 and 3.14) are there to catch it. If the 3.14 leg fails, do not silently exclude it. Preferred fix: a marker-split floor, e.g. `textual>=0.80; python_version<'3.14'` and a higher floor `textual>=N; python_version>='3.14'`, with N found by bisecting locally (uv has 3.14.4 and 3.14.7). Alternatives: an explicit matrix `exclude` plus a documented limitation, or raising the global floor. Run the 3.14 lowest-direct leg locally before relying on CI.
2. **`uv lock` may need the network.** ruff 0.17.3 and mypy 2.4.1 are in the cache, so `--offline` may work. If not, WP-3 stops and reports; do not hand-edit.
3. **Hatch extras in the sdist.** Which files hatch force-adds (`PKG-INFO`, `pyproject.toml`, license files) must be settled empirically by WP-3 and written into the allowlist explicitly.
4. **W1 → W2 transient runtime breakage.** After W1, baseline `app.py` still builds unrecognised sentinels (visual-only effect) and still imports `theme._BACK`/`_EXIT` (kept in `theme.py` until WP-4). Package imports stay valid throughout. `main.py` at the root fails at runtime after WP-4 (`run()` needs a menu) until WP-7 deletes it.
5. **`_fatal_error` is a private Textual hook.** Identical in 0.80.0 and 8.2.8, and covered by a test, but it may drift.
6. **`rich>=13.3.3` deviates from the ledger text** (D12).
7. **`LogAttachment` direct construction is only discouraged**, not blocked (about 25 test sites rely on it).
8. **README/CHANGELOG are left to the Documenter and are stale until step 6:** README line 14 ("Python 3.13 or newer"), line 185 (`uv run python main.py`), `run()`'s no-argument form, `CLIApp` parameters, the `|` breadcrumb limit, `_BACK`/`_EXIT` wording, the whitespace-shortcut caveat, and the `max_lines` caveat. Version stays 0.1.0 unless the user says otherwise.
9. **Phase 2 interaction.** The `build_menu(app)` convention and `crumbs` are Phase 1 shapes; Phase 2's `App`/`Context` supersedes them. No Phase 1 name collides with `App`, `Context`, `Param`, `Secret`.
10. **F7 (no non-TTY path) is still open.** `cli-interface pkg:menu < /dev/null` will still hang or spew escape codes; only `--help` and `--version` are TTY-free.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/pyproject.toml
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/example_menu.py