# cli-interface

A keyboard-driven terminal UI (built on [Textual](https://textual.textualize.io/)) that turns a tree of
`MenuItem`s into a navigable menu with a scrolling output panel. An action is a plain Python callable; it
writes to the panel with `app.panel.*`, and logs from other code and threads can be routed into the same
panel. A menu can also be run straight from the command line with `cli-interface module:attr`.

Status: Phase 1 (public API and packaging) is done; see `CHANGELOG.md`. The version is 0.1.0 and there is no
tagged release yet. Later phases (a job runner, subprocess support and a headless mode) are planned but not
implemented.

## Install

Requires Python 3.11 or newer. It depends on `textual>=0.80,<9` and `rich>=13.3.3`, which are installed with
it, and ships `py.typed`.

```bash
uv sync                       # create .venv with the package and the dev group (pytest, ruff, mypy)
uv add /path/to/cli_interface # or add it to another project
```

The test suite passes on Python 3.11 to 3.14, with Textual 0.80.0 (and Rich 13.3.3) as well as 8.2.8.

## The public API

Everything below is imported from the package itself:

```python
from cli_interface import CLIApp, MenuItem, run, attach_logging
```

| Name | What it is |
|---|---|
| `MenuItem` | One node of the menu tree. |
| `CLIApp` | The Textual app that shows a tree: `CLIApp(menu, *, strict_shortcuts=False, max_lines=5000)`. |
| `run` | `run(menu, *, strict_shortcuts=False, max_lines=5000) -> int`: build a `CLIApp`, run it, return the exit code. |
| `attach_logging` | Route a Python logger into the output panel. |
| `LogAttachment` | What `attach_logging` returns. Exported as a return type only: do not construct it yourself. |
| `DisplayPanel` | The type of `app.panel`. |
| `RESERVED_COMMANDS` | The typed commands that always win over a shortcut. |
| `find_shortcut_conflicts` | List the reserved and duplicate shortcuts in a menu. |
| `ShortcutConflictWarning`, `LoggingAttachWarning` | The two warning categories (both `UserWarning` subclasses). |
| `__version__` | The package version, the same as the installed distribution's. |

`PanelInbox`, `TUILogHandler`, `MenuState`, `PromptScreen`, `Dashboard`, `NavBar` and the colour theme are
internal. They still import from their submodules, but may change without notice.

## Quickstart

```python
from cli_interface import CLIApp, MenuItem


def hello() -> str:
    app.panel.log("Hello from an action")        # `app` is looked up when the action runs
    return "done"


def set_port(value: str) -> None:
    app.panel.log(f"port is now {int(value)}")


menu = MenuItem("Home", children=[
    MenuItem("Say hello", shortcut="h", action=hello),
    MenuItem("Settings", shortcut="s", children=[
        MenuItem("Set port", shortcut="p", prompt="Port (1-65535):", action=set_port),
    ]),
])
app = CLIApp(menu)

if __name__ == "__main__":
    app.run()
```

The examples below extend this module: they use its `app`, `menu`, `hello`, `MenuItem` and `CLIApp`.

Use the arrow keys and Enter, or type a shortcut and press Enter (`h` Enter runs "Say hello", which prints
`Executed: Say hello → done`). `MenuItem` fields: `label`, `shortcut`, `description` (not displayed),
`children`, `action`, `prompt`, `current_value` (shown as `(value)`; display only) and `secret`. An action
runs synchronously on the UI thread, so a long action freezes the UI: start a thread for slow work
(see Logging). An exception in an action is caught and shown as an `ERROR` line. `async` actions are not
awaited.

`CLIApp(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)` takes the root `MenuItem` (its children are
the first menu level; `TypeError` if it is not a `MenuItem`) and passes the other keyword arguments to
`textual.app.App`.

- `strict_shortcuts=True` raises `ValueError` for a reserved or duplicate shortcut instead of warning
  (see Shortcuts).
- `max_lines` is the output scrollback in lines. `None` keeps every line. Any other value must be a positive
  `int`: `0`, a negative number, `True`, a string or a float raises `ValueError`.

### `run(menu)`

`run` is the shortest way to launch a menu. `menu` is required (there is no built-in demo any more), and it
returns the app's exit code (0 unless the app set another):

```python
from cli_interface import MenuItem, run


def greet() -> str:
    return "hello"                                # shown as: Executed: Greet → hello


simple = MenuItem("Home", children=[MenuItem("Greet", shortcut="g", action=greet)])

if __name__ == "__main__":
    raise SystemExit(run(simple, max_lines=20_000))
```

`run` does not hand the app back, so an action that needs `app.panel`, the spinner or `set_menu` cannot reach
it. For those, build the `CLIApp` yourself, as in the Quickstart, or build it with a placeholder root and
`set_menu` the real menu once the actions can see the app (this is what the demo and the `cli-interface`
command do):

```python
def build_menu(app: CLIApp) -> MenuItem:
    def hello() -> None:
        app.panel.log("Hello from an action")

    return MenuItem("Home", children=[MenuItem("Say hello", shortcut="h", action=hello)])


app2 = CLIApp(MenuItem("Home"))
app2.set_menu(build_menu(app2))
```

## Output

`app.panel` is available once the app is running (inside actions) and must be used on the UI thread.

```python
from rich.text import Text


def report() -> None:
    p = app.panel
    p.clear()
    p.rule("Report")
    p.log("matrix[i][j] and [/x] are shown literally", "INFO")
    p.log("[bold green]styled[/]", markup=True)                 # opt in to Rich markup
    p.log(Text("also styled", style="bold cyan"), "WARNING")    # or pass a Text
    p.json({"port": 8080, "debug": False}, title="Config")
    p.table([{"name": "api", "status": "ok"}], title="Services")
```

Methods: `log`, `text`, `rule`, `json`, `table`, `csv`, `array`, `pretty`, `renderable`, `clear`.

- **Markup is off by default** everywhere: log lines, text, table headers and cells, titles, menu labels,
  prompts and typed commands are literal. Only `log` and `text` accept `markup=True`; markup that does not
  parse falls back to plain text. A `Text` you pass to `log` or `text`, and a Rich renderable in a table cell
  or given to `renderable()`, is used as given.
- `json`, `table`, `csv`, `array` and `pretty` scroll to the top of the panel; call `clear()` first if the new
  content should stand alone.
- The panel keeps the last `max_lines` lines (default 5000) for log lines and content alike, so a huge table
  or JSON dump loses its head. Pass `max_lines=None` to keep everything.

## Logging from other code and threads

```python
import logging
import threading

from cli_interface import attach_logging

job_log = logging.getLogger("myjob")


def start_job() -> None:
    capture = attach_logging(app, job_log, level=logging.INFO)   # UI thread, app running

    def work() -> None:
        try:
            for i in range(3):
                job_log.info("step %d", i)                       # shown in the panel
            app.push_log("job finished", "WARNING")              # direct, from any thread
        finally:
            capture.detach()                                     # safe from any thread

    threading.Thread(target=work, daemon=True).start()
```

- `attach_logging(app, logger=None, *, exclusive=False, level=None)` sends a logger's records to the panel
  (`None` means the root logger). It returns a `LogAttachment`; `detach()` or a `with` block undoes exactly
  what it changed. The app detaches everything at exit. Create attachments only through `attach_logging`:
  constructing a `LogAttachment` directly is discouraged (it is not blocked, but it skips the app's
  bookkeeping, so you must `detach()` it yourself).
- `level=` sets the logger's level while attached. Without it, the root logger's default (WARNING) drops INFO.
- `exclusive=True` removes the logger's existing handlers (for example the stderr handler) and `detach()`
  restores them. For a named logger, records still propagate to the root logger's handlers.
- A repeat `attach_logging` for the same app and logger adds no second handler: it returns a lease
  (`share()`) and emits a `LoggingAttachWarning` if you passed `exclusive` or `level`, which are ignored.
- Call it on the UI thread while the app is running. An attachment made after the app has exited is not
  detached for you.
- `app.push_log(message, level="INFO")` is safe from any thread and does not block a worker thread. At most
  10,000 records wait for the UI; beyond that the oldest are dropped and a warning line says how many.
  Records pushed before the app starts are shown on start; after it exits they are ignored.

## Prompts and secrets

```python
token = MenuItem("Set token", shortcut="k", prompt="API token:", secret=True,
                 action=lambda value: app.panel.log(f"token has {len(value)} characters"))
```

A `prompt` opens a dialog first (Enter confirms, Esc cancels and skips the action) and passes the typed string
to the action. The app never echoes it: the `Executed:` line shows only the label, plus `→ result` when the
action returns something. `secret=True` also masks the input and the `current_value` (`••••`), hides the
action's result, redacts the value from error text on a best-effort basis, and prints `'***'` in `repr()`. If
the app itself crashes, its traceback is printed without local variables so a secret held in one is not shown.
An action that logs or returns the value itself is not covered.

## Shortcuts and reserved commands

- Every shortcut is typed in full and confirmed with Enter. Single keys never fire. The yellow text in the nav
  bar is exactly what to type, including the Exit (`q`) and Back (`b`) cells. The Esc key also goes back, but
  typing `esc` is not a command.
- A shortcut is compared case-insensitively with surrounding whitespace stripped: `" X "` matches a typed `x`,
  and a whitespace-only shortcut means no shortcut. The nav bar shows the stripped text.
- Matching order: a reserved command, then an item shortcut on the current level (the first match wins), then
  a position number (`2` selects the second item; Exit and Back have no number).
- Reserved commands: `q`, `quit`, `exit`, `b`, `back`, `clear`, `help`, `?` (`RESERVED_COMMANDS`). They always
  win over a consumer shortcut. An item whose shortcut is reserved is still reachable by arrow keys and Enter,
  or by position. Reserved words are detected after stripping, so a shortcut of `" q "` is reported too.
- Reserved and duplicate shortcuts are detected whenever a menu is installed: in `CLIApp(menu)`, `set_menu`
  and `refresh_menu`. By default each problem emits a `ShortcutConflictWarning` and appears as a WARNING line
  in the panel once the app is running. With `strict_shortcuts=True` they raise `ValueError` instead.
  `find_shortcut_conflicts(menu)` returns the problems as a list.

```python
from cli_interface import find_shortcut_conflicts

clash = MenuItem("Home", children=[
    MenuItem("Quick run", shortcut="q", action=hello),     # `q` is reserved: it quits
    MenuItem("Alpha", shortcut="x", action=hello),
    MenuItem("Beta", shortcut="X", action=hello),          # same as Alpha, ignoring case
])
print(len(find_shortcut_conflicts(clash)))                  # 2
try:
    CLIApp(clash, strict_shortcuts=True)
except ValueError as exc:
    print("refused:", exc.args[0].splitlines()[0])
```

### Warning categories

`ShortcutConflictWarning` and `LoggingAttachWarning` are `UserWarning` subclasses, so filter or escalate them
by category (Python's default filter shows each distinct message once per source location):

```python
import warnings

from cli_interface import LoggingAttachWarning, ShortcutConflictWarning

with warnings.catch_warnings():
    warnings.simplefilter("error", ShortcutConflictWarning)        # a conflict now raises
    try:
        CLIApp(clash)
    except ShortcutConflictWarning as exc:
        print("conflict:", exc)

warnings.filterwarnings("ignore", category=LoggingAttachWarning)   # silence it for the whole process
```

In pytest, the same by category in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
filterwarnings = ["error::cli_interface.ShortcutConflictWarning"]
```

## Changing the menu while it runs

A `label` or a `current_value` can be a no-argument callable, and the menu can be replaced or refreshed from
code:

```python
state = {"count": 0, "mode": "fast"}


def bump() -> None:
    state["count"] += 1                     # the nav bar repaints after an action, so the label updates


def add_item() -> None:
    live.children.append(MenuItem(f"Extra {len(live.children)}", shortcut=f"e{len(live.children)}"))
    app.refresh_menu()                      # the children changed: re-read the tree


live = MenuItem("Home", children=[
    MenuItem(lambda: f"Bumped {state['count']}x", shortcut="u", action=bump),   # callable label
    MenuItem("Mode", shortcut="m", current_value=lambda: state["mode"]),        # callable value
    MenuItem("Add item", shortcut="a", action=add_item),
])
app.set_menu(live)                          # replace the whole menu (legal before the app starts)


def from_a_worker_thread() -> None:
    state["mode"] = "slow"
    app.call_from_thread(app.refresh_menu)  # hand the call to the UI thread
```

**Callable labels and values.**
- They are called with no arguments, on the UI thread. A callable value is called once per item for each
  repaint of the nav bar; a callable label also each time the breadcrumb, an `Executed:` or `Error in` line, a
  prompt title or a conflict message is built. Keep them cheap and free of side effects.
- The result goes through `str()`. A value of `None` (or a callable returning `None`) shows no value.
- If the callable raises an `Exception`, the text `<error>` is shown instead and the traceback is logged at
  DEBUG on the `cli_interface.menu` logger (a `BaseException` such as `KeyboardInterrupt` propagates).
- A callable `current_value` is never called for a `secret` item, which shows `••••`.
- The label in the `Executed:` line (and in `Error in <label>:`) is read before the action runs, so an action
  that changes its own label still logs the label of the item you chose.

**`set_menu(menu)`, `refresh_menu()` and `go_home()`.**
- `set_menu(menu)` replaces the whole tree: back to the root, first item selected. `TypeError` if `menu` is not
  a `MenuItem`. The new tree is checked like the constructor's: in strict mode a conflict raises `ValueError`
  and the old menu stays; otherwise each problem warns. If the check raises (a warning escalated to an error
  included), the old menu and its warning state are left as they were.
- `refresh_menu()` re-reads the tree after you edited it in place: callable labels and values are called
  again and added or removed children appear. It stays on the current level and selection, and falls back to
  the nearest level that still exists if the current one was removed. It checks the tree again and warns only
  about problems it has not reported before.
- `go_home()` returns to the root level, and does nothing at the root.
- All three are UI-thread only. From another thread, use `app.call_from_thread(app.refresh_menu)`, as above;
  they are not yet thread-safe on their own. `call_from_thread` raises `RuntimeError` once the app has exited.
- All three are legal before the app starts, after it has exited and with a prompt dialog open.
- None of them clears or writes to the output panel, except the WARNING lines for shortcut conflicts.

`start_spinner()` and `stop_spinner()` do nothing before the app has started and after it has exited (they
used to raise).

## Running a menu from the command line

The `cli-interface` console script runs a menu defined in your own module:

```bash
cli-interface mypkg.menus:build_menu
cli-interface mypkg.menus:build_menu --strict-shortcuts --max-lines 20000
cli-interface --version
cli-interface --help
```

The target is `module:attr` (`attr` may be dotted, like `Holder.make`). It names either a `MenuItem` or a
callable that returns one. A callable with a required positional parameter is called with the `CLIApp` that
will show the menu, so its actions can use `app.panel`; any other callable is called with no arguments. For
example, a module `menus.py` in the current directory:

```python
# menus.py
from cli_interface import CLIApp, MenuItem


def build_menu(app: CLIApp) -> MenuItem:
    def hello() -> None:
        app.panel.log("Hello from an action")

    return MenuItem("Home", children=[MenuItem("Say hello", shortcut="h", action=hello)])
```

```bash
cli-interface menus:build_menu
```

- The current directory is put first on `sys.path`, so a module next to you is found without installing it.
- `--strict-shortcuts` turns a reserved or duplicate shortcut into an error. `--max-lines N` sets the
  scrollback (a positive integer; the default is 5000). Without `--strict-shortcuts`, a conflict prints a
  `ShortcutConflictWarning` on stderr before the UI starts (pointing at `cli.py`, not at your module) and
  shows as a WARNING line in the panel.
- Exit codes: 0, or the exit code the app set, after a normal run. 2 for a usage error: no target (a bare
  `cli-interface` prints "the following arguments are required: target" and exits 2), a target that is not
  `module:attr`, a module or attribute that cannot be found, a target that is neither a `MenuItem` nor a
  callable or whose result is not a `MenuItem`, a bad `--max-lines`, or a conflict under `--strict-shortcuts`.
  1, with a traceback, for an exception raised inside your own code: a `build_menu` that raises, or an error
  while importing your module (an `ImportError` raised inside your module is your error and gets a
  traceback; only a missing target module or parent package exits 2).
- `--help` and `--version` need no terminal. Running a menu does: see Known limitations.

## Examples

`examples/` holds the demo: it shows the JSON, table, CSV, log, array and pretty-print output, a worker thread
with exclusive log capture, a spinner, a callable label and values, a prompt and a masked token prompt. It
uses only the public API (`examples/example_menu.py` defines `build_menu(app)`). From a checkout, at the
repository root:

```bash
uv run python -m examples.main                           # the supported launcher
uv run cli-interface examples.example_menu:build_menu    # the same menu through the console script
```

`examples/` is in the source distribution but not in the wheel, so these commands need a checkout (or an
unpacked sdist). `python examples/main.py` does not work: run it as a module.

## Known limitations

- **No non-TTY run path yet.** A menu needs a real terminal. Run with stdin or stdout piped (or from cron) and
  it hangs or prints escape codes. Only `--help` and `--version` work without a TTY.
- **Windows and macOS runners.** CI is configured for Ubuntu, macOS and Windows, but the workflow has not run
  on GitHub yet and the suite was run locally on macOS only. Windows is untested.
- **Where warnings point.** A `ShortcutConflictWarning` raised through `run(menu)` is attributed to `app.py`
  rather than to your call (on every Python version), and one raised by the console script to `cli.py`. A
  `CLIApp(menu)`, `set_menu` or `refresh_menu` call is attributed to your call.
- **`set_menu`, `refresh_menu` and `go_home` are UI-thread only.** There are no thread-safe proxies yet: use
  `app.call_from_thread(...)` from another thread.
- A callable label or value that keeps raising logs a DEBUG record each time it is evaluated, which can be
  many records per interaction.
- After `refresh_menu` drops a level that no longer exists, the selection is clamped rather than reset, so
  the highlight can land on any item of the level it falls back to.
- Numeric shortcuts that shadow a position number (`"2"` on the first item) are not reported.
- Nav-bar cell widths count characters, not terminal columns, so double-width characters (CJK, emoji) in a
  label can make a row overflow.
- Ordering is first-in first-out only among `push_log` records (and logging routed through `attach_logging`).
  Direct `app.panel` calls are written at once and can appear ahead of queued records.
- Output beyond `max_lines` lines is discarded oldest-first, so a large table or JSON dump loses its head
  (unless `max_lines=None`).

## Development and tests

```bash
uv sync                                        # .venv with the package and the dev group
uv run pytest -q                               # 885 passed
uv run ruff check cli_interface examples scripts tests
uv run mypy cli_interface examples scripts
uv build --out-dir dist                        # sdist, then a wheel built from it
python scripts/check_dist.py dist/*.tar.gz dist/*.whl   # fail if anything outside the allowlist ships
```

`scripts/check_dist.py` is standard-library only. It checks the built archives against the shipping allowlist
(no `tests/`, `.claude/`, `uv.lock` or demo modules in the package; `examples/` in the sdist only), the
required members, the metadata and that the versions agree; it exits 1 on any violation.

CI (`.github/workflows/ci.yml`, on pushes to `main` and on pull requests) has three jobs: `lint` (ruff and
mypy, Python 3.13); `test`, a matrix of Ubuntu, macOS and Windows on Python 3.11 to 3.14 with the locked
versions, plus two Ubuntu legs (3.11 and 3.14) that resolve the lowest direct dependencies and assert that Textual
0.80.0 was installed (Rich then resolves to 13.3.3; each leg also smoke-tests the console script); and `build`, which builds the sdist and
wheel, runs `check_dist.py` and installs the wheel into a clean virtual environment.

Tests drive the real app with Textual's Pilot; for your own app:

```python
import asyncio

from textual.widgets import RichLog


async def check() -> None:
    global app
    app = CLIApp(menu)                           # a fresh app; actions look up `app` when they run
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("h", "enter")          # type the shortcut, then Enter
        await pilot.pause()
        lines = app.query_one("#display-panel", RichLog).lines
        assert "Executed: Say hello" in "\n".join(strip.text for strip in lines)


asyncio.run(check())
```

`run_test` shuts the app down when the `async with` block ends, spinner timers included, so no extra
`app.exit()` is needed. Never start the real TUI (`app.run()`, `run(menu)` or `cli-interface ...`) from a test
or any non-TTY process.
