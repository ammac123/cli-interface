# cli-interface

A keyboard-driven terminal UI (built on [Textual](https://textual.textualize.io/)) that turns a tree of
`MenuItem`s into a navigable menu with a scrolling output panel. An action is a plain Python callable; it
writes to the panel with `app.panel.*`, and logs from other code and threads can be routed into the same
panel.

Status: Phase 0 (hardening) is done; see `CHANGELOG.md`. The package has no top-level facade yet, so import
from the submodules shown below. Later phases (a public facade, a job runner, subprocess support and a
headless mode) are planned but not implemented.

## Install

Requires Python 3.13 or newer (the declared `requires-python`) and `textual>=0.80`, which brings in `rich`.

```bash
uv sync                       # create .venv with textual and the dev group (pytest)
uv add /path/to/cli_interface # or add it to another project
```

## Quickstart

```python
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem


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
- The panel keeps the last `max_lines` lines (default 5000, `CLIApp(menu, max_lines=...)`) for log lines and
  content alike, so a huge table or JSON dump loses its head.

## Logging from other code and threads

```python
import logging
import threading

from cli_interface.app import attach_logging

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
  what it changed. The app detaches everything at exit.
- `level=` sets the logger's level while attached. Without it, the root logger's default (WARNING) drops INFO.
- `exclusive=True` removes the logger's existing handlers (for example the stderr handler) and `detach()`
  restores them. For a named logger, records still propagate to the root logger's handlers.
- A repeat `attach_logging` for the same app and logger adds no second handler: it returns a lease
  (`share()`) and warns if you passed `exclusive` or `level`, which are ignored.
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
action's result, redacts the value from error text on a best-effort basis, and prints `'***'` in `repr()`. An
action that logs or returns the value itself is not covered.

## Shortcuts and reserved commands

- Every shortcut is typed in full and confirmed with Enter. Single keys never fire. The yellow text in the nav
  bar is exactly what to type, including the Exit (`q`) and Back (`b`) cells. The Esc key also goes back, but
  typing `esc` is not a command.
- Matching order (case-insensitive): a reserved command, then an item shortcut on the current level (the first
  match wins), then a position number (`2` selects the second item; Exit and Back have no number).
- Reserved commands: `q`, `quit`, `exit`, `b`, `back`, `clear`, `help`, `?`. They always win over a consumer
  shortcut. An item whose shortcut is reserved is still reachable by arrow keys and Enter, or by position.
- Reserved and duplicate shortcuts are detected when the app is built. By default each problem raises a
  `UserWarning` and appears as a WARNING line in the panel at start-up. With `strict_shortcuts=True`, `CLIApp`
  raises `ValueError` instead. `cli_interface.menu.find_shortcut_conflicts(menu)` returns the problems as a list.

```python
from cli_interface.menu import find_shortcut_conflicts

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

## Known limitations

- A shortcut with leading or trailing whitespace is displayed but never matches, and the conflict check does
  not report it. Numeric shortcuts that shadow a position number (`"2"` on the first item) are not reported.
- The nav bar counts a shortcut as 2 columns, so long shortcuts can make a row overflow.
- Ordering is first-in first-out only among `push_log` records (and logging routed through `attach_logging`).
  Direct `app.panel` calls are written at once and can appear ahead of queued records.
- Output beyond `max_lines` lines is discarded oldest-first, so a large table or JSON dump loses its head.
  `max_lines` is not validated; use a positive integer.
- A menu label containing `|` is split into separate crumbs in the header.
- Testing with Textual's Pilot: if a spinner is running, call `app.exit()` before leaving `run_test`, or a
  late timer tick can fail against the torn-down screens.
- `CLIApp` subclasses must not call `super().on_mount()`; Textual already runs the base handler.

## Running the demo and the tests

```bash
uv run python main.py        # the demo menu (also: uv run cli-interface)
uv run pytest -q             # 467 passed, 1 xfailed (a known, strict xfail)
```

The demo shows the JSON, table, CSV, log, array and pretty-print output, a worker thread with exclusive log
capture, a spinner, and a masked token prompt.
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
        app.exit()


asyncio.run(check())
```
