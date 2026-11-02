# cli-interface

A keyboard-driven terminal UI (built on [Textual](https://textual.textualize.io/)) that turns a tree of
`MenuItem`s into a navigable menu with a scrolling output panel. An action is a plain Python callable. With
`App` and `@app.command` it runs as a job, on the event loop or in a thread, with progress, cancellation, hooks
and captured `print()` output; it writes to the panel with `app.panel.*` or `ctx.panel.*`, and logs from other
code and threads can be routed into the same panel. A menu or an app can also be run straight from the command
line with `cli-interface module:attr`.

Status: Phase 2 (the job runner and `Context`) is done; see `CHANGELOG.md`. The version is 0.1.0 and there is no
tagged release yet. Later phases (typed parameters and settings, subprocess support and a headless mode) are
planned but not implemented.

## Install

Requires Python 3.13 or newer. It depends on `textual>=0.80,<9` and `rich>=13.3.3`, which are installed with
it, and ships `py.typed`.

```bash
uv sync                       # create .venv with the package and the dev group (pytest, ruff, mypy)
uv add /path/to/cli_interface # or add it to another project
```

The suite is run locally on Python 3.13 with the locked Textual 8.2.8 (Phase 2 was also run on Python 3.11
with Textual 0.80.0 and Rich 13.3.3, before the floor moved to 3.13). Python 3.14, and Textual 0.80.0 on
Python 3.13, are in the CI matrix but have not been run yet; see Known limitations.

## The public API

Everything below is imported from the package itself:

```python
from cli_interface import App, CLIApp, Context, MenuItem, run, attach_logging
```

| Name | What it is |
|---|---|
| `MenuItem` | One node of the menu tree. |
| `App` | A `CLIApp` whose menu is built from functions registered with `@app.command`: `App(name="cli-interface", *, strict_shortcuts=False, max_lines=5000, quit_grace=2.0)`. See Jobs. |
| `Context` | What a job function may ask for: panel, log, progress, cancellation, shared state and thread-safe menu calls. See Jobs. |
| `CLIApp` | The Textual app that shows a tree: `CLIApp(menu, *, strict_shortcuts=False, max_lines=5000, quit_grace=2.0)`. |
| `run` | `run(menu, *, strict_shortcuts=False, max_lines=5000) -> int`: build a `CLIApp`, run it, return the exit code. |
| `attach_logging` | Route a Python logger into the output panel. |
| `LogAttachment` | What `attach_logging` returns. Exported as a return type only: do not construct it yourself. |
| `DisplayPanel` | The type of `app.panel` and `ctx.panel`. |
| `RESERVED_COMMANDS` | The typed commands that always win over a shortcut (`q`, `b`, `clear`, `help`, `stop` and their aliases). |
| `find_shortcut_conflicts` | List the reserved and duplicate shortcuts in a menu. |
| `ShortcutConflictWarning`, `LoggingAttachWarning` | The two warning categories (both `UserWarning` subclasses). |
| `__version__` | The package version, the same as the installed distribution's. |

`PanelInbox`, `TUILogHandler`, `Job`, `JobManager`, `MenuState`, `PromptScreen`, `Dashboard`, `NavBar`, the
colour theme and the event dictionaries of `cli_interface.events` (schema version 1) are internal. They still
import from their submodules, but may change without notice. Some `CLIApp` methods (`emit`, `loop`, `call_ui`,
`post_ui`, `on_ui_thread`, `panel_for`, `spinner_acquire`, `spinner_release`, `job_changed`, `flush_inbox`,
`request_exit`) are public only because the job runner calls them: they are not consumer API.

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
`children`, `action`, `prompt`, `current_value` (shown as `(value)`; display only) and `secret`. Every action
runs as a job. A plain action that takes no `Context` runs inline on the UI thread, so a long one freezes the UI:
make it `async`, or give it a `ctx: Context` parameter so that it runs in a thread (see Jobs). An exception in
an action is caught and shown as an `Error in <label>:` line followed by its traceback.

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

`app.panel` (and `ctx.panel` inside a job) may be called from any thread. Each call queues an event, and the
lines appear in the order they were written. Written before the app has started, the output is held and shown on
start; written after it has exited, it is ignored.

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
  content should stand alone. A `Text` passed as their `title` is shown as plain text, without its style (a
  `Text` given to `rule()` keeps it).
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
- Call it on the UI thread while the app is running. After the app has exited, `attach_logging` attaches
  nothing: it warns (`LoggingAttachWarning`) and returns an inert, already-detached handle.
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
action returns a one-line value (other results are shown above it, see Jobs). `secret=True` also masks the
input and the `current_value` (`••••`), hides the action's result, redacts the value from error text on a
best-effort basis, and prints `'***'` in `repr()`. If the app itself crashes, its traceback is printed without local variables so a secret held in one is not shown.
An action that logs or returns the value itself is not covered.

In a job, the typed value is also redacted from everything the job writes: `ctx.log`, `ctx.panel`, `print()`
and stderr output, progress text, error messages and tracebacks show `***` instead. The return value of such a
job is never shown. The redaction is best effort:
- `json`, `table`, `csv`, `array` and `pretty` output is turned into plain text before it is redacted, so it
  loses its Rich styling (`pretty` becomes plain `pprint` text), and `renderable()` output is replaced by its type
  name (a `Text` by its plain text).
- A secret split across two table cells, or across two lines, is not caught.
- Threads that the job starts itself write unredacted, because their output is not tagged with the job.

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
  DEBUG on the `cli_interface.menu` logger, once per item and field until the callable next succeeds (a
  `BaseException` such as `KeyboardInterrupt` propagates).
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
  the nearest level that still exists if the current one was removed (the first item is then selected). It
  checks the tree again and warns only about problems it has not reported before.
- `go_home()` returns to the root level, and does nothing at the root.
- On `CLIApp` all three are UI-thread only. From another thread use `app.call_from_thread(app.refresh_menu)`,
  as above (`call_from_thread` raises `RuntimeError` once the app has exited), or, inside a job, the thread-safe
  `ctx.set_menu(menu)`, `ctx.refresh_menu()` and `ctx.go_home()` (see Jobs).
- All three are legal before the app starts, after it has exited and with a prompt dialog open.
- None of them clears or writes to the output panel, except the WARNING lines for shortcut conflicts.

`start_spinner()` and `stop_spinner()` do nothing before the app has started and after it has exited (they
used to raise).

## Jobs: `App`, commands and `Context`

Every action runs as a job. `App` is a `CLIApp` whose menu is built from decorated functions, and a job function
can take a `Context` for its panel, log, progress and cancellation. This section is a module of its own: its
`app` is an `App`, not the `CLIApp` of the Quickstart.

```python
import asyncio

from cli_interface import App, Context

app = App("Demo")
app.group("Run", key="r")                       # optional: give a submenu a shortcut


@app.command("Run/Count", key="c", cancellable=True)
async def count(ctx: Context) -> str:           # async: runs on the UI event loop
    for step in range(1, 6):
        ctx.progress(step, 5, "Counting")       # the spinner reads "Counting 3/5 (60%)"
        await asyncio.sleep(0.2)
    return "Counted to 5"                       # shown as: Executed: Count → Counted to 5


@app.command("Run/Crunch", key="n")
def crunch(ctx: Context) -> dict:               # sync: runs in a daemon thread
    step = 0
    for step in range(1, 4):
        ctx.status(f"Crunching step {step}")
        print(f"step {step}")                   # print() and stderr inside a job land in the panel
        if ctx.cancelled.wait(0.1):             # set by stop and by quit
            break
    return {"steps": step}                      # a dict is shown as JSON


@app.command("Tools/Table", key="t")
def table() -> list[dict]:                      # takes no Context, and still runs in a thread
    """A list of dicts is shown as a table."""
    return [{"name": "alpha", "size": 12}, {"name": "beta", "size": 7}]


if __name__ == "__main__":
    app.run()
```

- `@app.command(path, *, key="", cancellable=False, description=None)` registers the function and returns it
  unchanged. `path` is `"Group/Name"`: the last segment is the label and the ones before it are submenus,
  created as needed (`app.group(path, key=...)` creates one with a shortcut). `ValueError` for an empty
  segment, a path that is taken or one that goes through a command. `app.add_command(path, fn, ...)` is the
  same without the decorator, and it works while the app runs. Shortcut problems are reported like those of
  `CLIApp(menu)` (a `ShortcutConflictWarning`, or `ValueError` under `strict_shortcuts`).
- `key` is the shortcut. `cancellable=True` lets the first `stop` cancel the job (see below). `description`
  defaults to the first line of the docstring and is not displayed.
- `App(name="cli-interface", *, strict_shortcuts=False, max_lines=5000, quit_grace=2.0, **textual_kwargs)`.
  `name` is the root label and the window title. `CLIApp` takes the same `quit_grace`; `run(menu)` does not.
- Registering commands is not the only way: `CLIApp(MenuItem(...))` actions get the same job treatment, and the
  Context-taking and `async` ones work there too.

### Where an action runs

| Action | Runs |
|---|---|
| `async def` (or a function that returns an awaitable) | as a task on the UI event loop |
| any `@app.command` function, and any function that asks for a `Context` | in a daemon thread named `cli-interface-job-N` |
| a plain `MenuItem(action=fn)` that does not ask for a `Context` | inline on the UI thread (a long one freezes the UI) |

A function asks for the context with a parameter annotated `Context` (also `Context | None` or
`Optional[Context]`) or, if unannotated, named `ctx` or `context`. For a `MenuItem` with a `prompt`, the typed
text goes to the first other positional parameter: `def set_port(ctx: Context, value: str)`.

### `Context`

| Member | What it does |
|---|---|
| `ctx.panel` | The output panel for this job (a `DisplayPanel`): `log`, `table`, `json`, ... |
| `ctx.log(msg, level="INFO", *, markup=False)` | A log line. Also `ctx.log.debug`, `.info`, `.warning`, `.error`, `.critical`. |
| `ctx.progress(current, total, label, *, id="default", done=False)` | Shown as the spinner label while the job runs: `label current/total (pct%)`. `done=True` clears it. |
| `ctx.status(text)` | Free text for the spinner label. |
| `ctx.cancelled` | A `threading.Event`, new for each job, set by `stop` and by quit. |
| `ctx.check_cancelled()` | Raises if `cancelled` is set; the job then ends as `Cancelled:`. |
| `ctx.state` | The app's shared `SimpleNamespace` (`app.state`), the same for every job and hook. |
| `ctx.job` | The running job: `label`, `outcome`, `error`, `state`, ... |
| `ctx.set_menu(menu)`, `ctx.refresh_menu()`, `ctx.go_home()` | Thread-safe versions of the `CLIApp` methods. |

Everything on `Context` may be called from any thread, including threads the job starts itself, and does
nothing once the job has been abandoned.

### Hooks

```python
@app.on_startup
def ready(ctx: Context) -> None:
    ctx.log("Demo ready")


@app.before_command
def count_runs(ctx: Context) -> None:
    ctx.state.runs = getattr(ctx.state, "runs", 0) + 1


@app.after_command
def report(ctx: Context) -> None:
    ctx.log(f"{ctx.job.label}: {ctx.job.outcome} (command {ctx.state.runs})")


@app.on_shutdown
def cleanup() -> None:                          # fn() and fn(ctx) are both fine
    ...                                         # runs after the running job stopped; the UI is about to close
```

The four hooks are decorators on `CLIApp` and `App`, and plain methods too (`app.on_startup(fn)`). Each takes
`fn(ctx)` or `fn()`, sync or `async`, and they run in registration order.

- `on_startup` runs once after the app has started, as a job named `startup`; commands are rejected as busy
  until it ends. A failure is shown as an error and the app keeps running. Registering one after the app has
  started raises `RuntimeError`.
- `before_command` runs before each command. Raising vetoes it: the body and later `before_command` hooks do not
  run, and the command ends in an error.
- `after_command` runs after the `Executed:`, `Cancelled:` or `Error in` line, for every job except an abandoned
  one. `ctx.job.outcome` is `"ok"`, `"error"` or `"cancelled"` and `ctx.job.error` the error message. If the hook
  fails, the error is shown and the outcome stays.
- `on_shutdown` runs when the app quits through `exit()` (see below), each hook bounded by `quit_grace`; a failure
  is dropped. It does not run if the app crashes.

### Busy, `stop` and quit

- **One job at a time.** Starting a command while another runs (the `startup` hook included) is rejected, not
  queued: a `Busy: <label> is running (type stop to stop it)` WARNING line, before any prompt opens. Navigation,
  `clear`, `help`, `q` and `stop` still work.
- **`stop`** is a typed command (`stop` + Enter), reserved like `q`: no key is bound to it, and a consumer
  shortcut `stop` gets a `ShortcutConflictWarning`. With nothing running it says `Nothing is running`.
  - A `cancellable=True` job: the first `stop` sets `ctx.cancelled`, the spinner reads `Stopping <label> ...`, and
    a task running an `async` function is cancelled at its next `await` (the job ends `Cancelled: <label>`). A
    thread must watch `ctx.cancelled` (or call `ctx.check_cancelled()`) to stop.
  - Any other job: the first `stop` only warns (`<label> cannot be stopped cleanly; type stop again to abandon
    it`) and leaves `ctx.cancelled` clear.
  - A second `stop` abandons the job: the app is free again with an `Abandoned: <label>` WARNING. Python cannot
    kill a thread, so the job's thread runs on in the background, but everything it prints, logs, reports or
    returns from then on is ignored.
- **Quit** (`q`, the Exit cell, Ctrl+C, or `app.exit()` from any thread): a running job gets `ctx.cancelled`
  set, cancellable or not, and `quit_grace` seconds (default 2.0) to finish; then each `on_shutdown` hook runs,
  each bounded by `quit_grace`; a job or hook still running after that is abandoned and the app exits anyway,
  ignoring its output. A second `q` skips the wait. With nothing running and no shutdown hooks, quit is
  immediate.

### What a job's result looks like

The return value is shown by type, above the `Executed: <label>` line (the line carries the value for a one-line
`str`). The error path shows `Error in <label>: <message>` followed by the full traceback in dim text: the
chain of causes included, the runner's own frames and local variables left out, capped at 50,000 characters.

| Return value | Shown |
|---|---|
| `None` | `Executed: <label>` |
| a one-line `str` (or any other object, as `str(value)`) | on the line: `Executed: <label> → value` |
| a multi-line `str` | as a text block |
| a `dict`, `list`, `tuple` or `set` | as JSON (as pretty-printed Python if it is not JSON-serialisable) |
| a non-empty `list` or `tuple` of dicts | as a table; the columns are the first row's keys |
| a Rich renderable (`Text`, `Panel`, `Table`, ...) | rendered |
| an empty container, or `bytes` | its `repr()` on the `Executed:` line |

A job with a secret prompt value shows no return value at all (see Prompts and secrets).

### `print()` and stderr

Inside a job, `print()` and writes to `sys.stderr` become panel lines, in order with the job's other output
(stderr in the warning colour). That covers the body, its hooks and anything they call on the job's own thread
or task. ANSI escapes and control characters are removed, and a carriage return keeps the last segment. Inside a
job `sys.stdout.isatty()` is false and `fileno()` raises `io.UnsupportedOperation`.

A thread the job starts itself is not part of the job: what it prints appears in the panel without the job tag,
and a secret job does not redact it. Output that bypasses `sys.stdout`/`sys.stderr` is not captured:
`sys.__stdout__`, `.buffer`, a handler or `file=` bound to the old stream, and subprocesses. Output on the UI
thread outside a job is not captured either. The capture is on while the app is mounted; it covers `app.run()`
and `app.run_async()` but not `app.run_test()`.

### Testing a job app

`app.jobs.wait_idle()` waits until the manager is idle and the panel's queue is flushed, with no sleeps:

```python
async def check_count() -> None:
    async with app.run_test(size=(140, 40)) as pilot:
        await app.jobs.wait_idle()                       # the startup hook has finished
        mark = app.jobs.mark()
        await pilot.press("r", "enter", "c", "enter")    # Run, then Count
        await app.jobs.wait_idle(since=mark, jobs=1)     # one job has completed since the mark
        assert app.jobs.current is None
        assert app.state.runs == 1


asyncio.run(check_count())
```

## Running a menu from the command line

The `cli-interface` console script runs a menu defined in your own module:

```bash
cli-interface mypkg.menus:build_menu
cli-interface mypkg.menus:build_menu --strict-shortcuts --max-lines 20000
cli-interface --version
cli-interface --help
```

The target is `module:attr` (`attr` may be dotted, like `Holder.make`). It names a `MenuItem`, an `App` or
`CLIApp` instance, or a callable that returns a `MenuItem` or an app. With a `MenuItem`, the script builds the
app that shows it. A callable with a required positional parameter is called with the `CLIApp` that will show
the menu (the `build_menu(app)` rule), so its actions can use `app.panel`; any other callable is called with no
arguments. If it returns an app, that app is run instead. For example, a module `menus.py` in the current
directory:

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
cli-interface examples.app_demo:app    # an App instance: its commands, hooks and quit_grace are used as they are
```

- The current directory is put first on `sys.path`, so a module next to you is found without installing it.
- `--strict-shortcuts` turns a reserved or duplicate shortcut into an error. `--max-lines N` sets the
  scrollback (a positive integer; the default is 5000). With an app target they are applied to that app:
  `--strict-shortcuts` can only tighten it, and `--max-lines` replaces its scrollback. Without
  `--strict-shortcuts`, a conflict prints a `ShortcutConflictWarning` on stderr before the UI starts (pointing
  at the console script's entry point, not at your module) and shows as a WARNING line in the panel.
- Exit codes: 0, or the exit code the app set, after a normal run. 2 for a usage error: no target (a bare
  `cli-interface` prints "the following arguments are required: target" and exits 2), a target that is not
  `module:attr`, a module or attribute that cannot be found, a target that is neither a `MenuItem`, an app nor a
  callable or whose result is neither a `MenuItem` nor an app, a bad `--max-lines`, or a conflict under
  `--strict-shortcuts`.
  1, with a traceback, for an exception raised inside your own code: a `build_menu` that raises, or an error
  while importing your module (an `ImportError` raised inside your module is your error and gets a
  traceback; only a missing target module or parent package exits 2).
- `--help` and `--version` need no terminal. Running a menu does: see Known limitations.

## Examples

`examples/` holds two demos. `example_menu.py` shows the JSON, table, CSV, log, array and pretty-print output,
a worker thread with exclusive log capture, a spinner, a callable label and values, a prompt and a masked
token prompt (it defines `build_menu(app)`). `app_demo.py` is the job API in one file: `App`, `@app.command`,
`Context`, progress, `stop` and the four hooks. Both use only the public API. From a checkout, at the
repository root:

```bash
uv run python -m examples.main                           # the menu demo, the supported launcher
uv run cli-interface examples.example_menu:build_menu    # the same menu through the console script
uv run python -m examples.app_demo                       # the job demo
uv run cli-interface examples.app_demo:app               # the same through the console script
```

`examples/` is in the source distribution but not in the wheel, so these commands need a checkout (or an
unpacked sdist). `python examples/main.py` does not work: run it as a module.

## Known limitations

- **No non-TTY run path yet.** A menu needs a real terminal. Run with stdin or stdout piped (or from cron) and
  it hangs or prints escape codes. Only `--help` and `--version` work without a TTY.
- **CI has not run yet.** `.github/workflows/ci.yml` is configured for Ubuntu, macOS and Windows on Python 3.13
  and 3.14 with the locked versions, plus two Ubuntu legs (3.13 and 3.14) with the lowest direct dependencies
  (Textual 0.80.0, Rich 13.3.3), but the workflow has not run on GitHub yet. Locally the suite was run on
  macOS only, on Python 3.13; Windows, Python 3.14 and Textual 0.80.0 on Python 3.13 are untested.
- **Where warnings point.** A `ShortcutConflictWarning` or `LoggingAttachWarning` points at the first caller
  outside the package (your `CLIApp(menu)`, `set_menu`, `run(menu)` or `add_command` call), and for the console
  script at its entry point.
- Numeric shortcuts that shadow a position number (`"2"` on the first item) are not reported.
- Output beyond `max_lines` lines is discarded oldest-first, so a large table or JSON dump loses its head
  (unless `max_lines=None`).
- Past 10,000 queued log or text records the oldest are dropped, with a `N log record(s) dropped (UI busy)`
  line. For a job that floods the panel, the closing `N more log record(s) dropped (UI busy)` line can appear
  after the job's `Executed:` line.

Jobs:
- **Abandoned jobs keep running.** A thread cannot be killed. A job that ignores cancellation is abandoned after
  `quit_grace` (or a second `stop`), and its thread goes on in the background; the process ends it at exit.
  Whatever the job prints, logs or returns after that is ignored, and no `after_command` hook runs for it (the
  `Abandoned:` WARNING is its last line).
- **`asyncio.to_thread` can delay exit.** The framework's own job threads are daemons. A thread started by
  `asyncio.to_thread` (or the default executor) inside an `async` job is not, and Python waits for it when the
  process ends. Use `threading.Thread(daemon=True)` or a `def` command for blocking work.
- **A self-exit is noisy.** `app.exit()` called from inside a thread or async job shows a `Stopping X` warning,
  and an async job then ends `Cancelled:`.
- **Suspending the app.** While Textual suspends the app (`action_suspend_process`), an abandoned job's output
  can reach the terminal.
- **`run_test()` is not guarded.** The print capture and its guard against abandoned jobs cover `app.run()` and
  `app.run_async()`, not `app.run_test()`.
- **One job at a time**, and no queue: a second start is rejected.
- **Titles.** A `Text` passed as the `title` of `json`, `table`, `csv`, `array` or `pretty` loses its style
  (`rule(Text(...))` keeps it).
- **Secrets.** See Prompts and secrets: JSON and table output is redacted into plain text, a secret split across
  cells or lines is not caught, and threads a secret job starts are not redacted.

## Development and tests

```bash
uv sync                                        # .venv with the package and the dev group
uv run pytest -q                               # about 1,740 tests, about 2.5 minutes
uv run ruff check cli_interface examples scripts tests
uv run mypy cli_interface examples scripts
uv build --out-dir dist                        # sdist, then a wheel built from it
python scripts/check_dist.py dist/*.tar.gz dist/*.whl   # fail if anything outside the allowlist ships
```

`scripts/check_dist.py` is standard-library only. It checks the built archives against the shipping allowlist
(no `tests/`, `.claude/`, `uv.lock` or demo modules in the package; `examples/` in the sdist only), the
required members, the metadata and that the versions agree; it exits 1 on any violation.

CI (`.github/workflows/ci.yml`, on pushes to `main` and on pull requests) has three jobs: `lint` (ruff and
mypy, Python 3.13); `test`, a matrix of Ubuntu, macOS and Windows on Python 3.13 and 3.14 with the locked
versions, plus two Ubuntu legs (3.13 and 3.14) that resolve the lowest direct dependencies and assert that
Textual 0.80.0 was installed (Rich then resolves to 13.3.3; each leg also smoke-tests the console script); and
`build`, which builds the sdist and wheel, runs `check_dist.py` and installs the wheel into a clean virtual
environment (Python 3.13).

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
