# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There is no tagged release yet; the work
is grouped by roadmap phase. Baseline for Phase 0 is commit `fdb8069`; for Phase 1 it is `4cab69a`; for
Phase 2 it is `23a8ed1`.

## [Unreleased] - Phase 2 (job runner and Context)

### Added
- **`App` and `@app.command`.** `App(name="cli-interface", *, strict_shortcuts=False, max_lines=5000,
  quit_grace=2.0, **textual_kwargs)` is a `CLIApp` whose menu is built from functions:
  `@app.command("Group/Name", key="", cancellable=False, description=None)`, `app.add_command(path, fn, ...)` and
  `app.group(path, key=..., description=...)`. Paths create submenus; an empty segment, a taken path or a path
  through a command is a `ValueError`; shortcut conflicts are reported like those of `CLIApp(menu)`, and a menu
  edited while the app runs is refreshed. `from cli_interface import ...` now exposes 13 names: `App` and
  `Context` are the additions.
- **Every action is a job** (`jobs.py`, `JobManager`, reached as `app.jobs`). An `async` action is awaited on the
  UI event loop; a function that takes a `Context`, and every `@app.command` function, runs in a daemon thread
  (`cli-interface-job-N`); a plain context-free `MenuItem` action still runs inline on the UI thread. One job runs
  at a time: a second start is rejected (not queued) with a `Busy: <label> is running (type stop to stop it)`
  WARNING, before any prompt opens. The spinner is held for the length of a thread or async job and shows its
  label, `ctx.status` or `ctx.progress` text; the public `start_spinner` / `stop_spinner` keep their meaning.
- **`Context`** (`context.py`): `panel` (a thread-safe `DisplayPanel` tagged with the job), `log` (callable, plus
  `debug`, `info`, `warning`, `error`, `critical`), `progress(current, total, label, *, id, done)`, `status(text)`,
  `cancelled` (a `threading.Event`, new per job), `check_cancelled()`, `state` (the app's shared
  `SimpleNamespace`, also `CLIApp.state`), `job`, and the thread-safe `set_menu`, `refresh_menu` and `go_home`.
  A function asks for it with a `Context` annotation (also `Context | None` and `Optional[Context]`) or an
  unannotated `ctx` / `context` parameter; a prompt's text goes to the first other positional parameter.
- **`stop`**, a reserved typed command (it joins `RESERVED_COMMANDS` and the help table; no key is bound). A
  `cancellable=True` job is cancelled by the first `stop` (`ctx.cancelled` is set and an async job's task is
  cancelled, ending `Cancelled: <label>`); for any other job the first `stop` only warns, and a second `stop`
  abandons the job (`Abandoned: <label>` WARNING). With nothing running it says `Nothing is running`.
- **Quit policy.** `q`, Exit, Ctrl+C or `exit()` (any thread) sets `ctx.cancelled` on the running job, gives it
  `quit_grace` seconds (new keyword of `CLIApp` and `App`, default 2.0), runs the `on_shutdown` hooks (each bounded
  by `quit_grace`), then abandons whatever is still running and exits. A job that ignores cancellation is
  abandoned, its output is ignored and its daemon thread dies with the process. A second `q` skips the wait.
- **Hooks:** `on_startup`, `on_shutdown`, `before_command` and `after_command` on `CLIApp` and `App`, as
  decorators or calls. Each takes `fn(ctx)` or `fn()`, sync or async, and runs in registration order.
  `before_command` can veto a command by raising. `after_command` runs after the result line for every job
  except an abandoned one.
- **Return values are shown by type** (`outcome.py`): `None` shows nothing; a one-line `str` or any other object
  goes on the `Executed: <label> → value` line; a multi-line `str` is a text block; a `dict`, `list`, `tuple` or
  `set` is JSON; a non-empty list or tuple of dicts is a table; a Rich renderable is rendered; `bytes` and empty
  containers show their `repr()`. The content comes before the `Executed:` line. A secret job shows no return
  value.
- **Full tracebacks (F5).** A failing action shows `Error in <label>: <message>` followed by the whole traceback
  in dim text, with the chained causes, without the runner's own frames or local variables, and capped at 50,000
  characters.
- **`print()` and stderr capture (F9)** (`capture.py`). Inside a job (body, hooks, and what they call on the
  job's thread or task), `print()` and `sys.stderr` writes become panel lines tagged with the job, stderr in the
  warning colour, ANSI and control characters removed. Output from threads the job starts itself shows without
  the job tag. `CLIApp.run_async()` (which `run()` goes through) holds the capture over the real streams until
  Textual has finished tearing down, so an abandoned job's output cannot reach the terminal. `run_test()` is not
  covered.
- **Event schema v1** (`events.py`, standard library only). Every panel write is an event dictionary: `hello`,
  `log`, `progress`, `text`, `json`, `table`, `result` and `error`, each with `v`, `t` and `kind` (and `job`),
  plus the in-process-only `clear` and `action`. The module has constructors, `validate_event`, `dumps` (JSON
  lines), the drop policy and secret redaction. `DisplayPanel` is now a thin facade that builds these events, so
  `app.panel` and `ctx.panel` are safe from any thread and keep their order; `CLIApp.emit(event)` is the one entry
  point. `PanelRenderer` draws the events on the UI thread.
- **The CLI accepts an app.** `cli-interface module:attr` resolves an `App` or `CLIApp` instance, a `MenuItem`,
  or a callable returning an app or a menu. The `build_menu(app)` rule still works (a callable with a required
  positional parameter is called with the placeholder `CLIApp`; if it returns an app, that one runs).
  `--strict-shortcuts` can only tighten an app target and `--max-lines` replaces its scrollback.
- **`examples/app_demo.py`**: `App`, `@app.command`, `Context`, progress, cancel and the four hooks in one file
  (`python -m examples.app_demo` or `cli-interface examples.app_demo:app`).
- **Test hooks on the manager:** `app.jobs.mark()`, `await app.jobs.wait_idle(since=, jobs=, timeout=)` and
  `await app.jobs.wait_until(predicate)`, plus the reads `state`, `busy`, `current` and `completed`.
- `app.panel` works before the app has mounted: what is written then is held and shown on start.
- New modules: `capture.py`, `commands.py`, `context.py`, `events.py`, `jobs.py` and `outcome.py`.
- Dev only (not shipped): 1,742 tests (was 885) with the shared `tests/jobrig.py` rig and new helpers; they were
  run on Python 3.13 with Textual 8.2.8 and, before the floor moved, on Python 3.11 with Textual 0.80.0 and Rich
  13.3.3. `scripts/check_dist.py` knows the new modules and `examples/app_demo.py`.
- Docs: the README covers the job API, the output capture, secret jobs and the limits; the touched internals
  have docstrings.

### Changed (behaviour)

Breaking for code written against Phase 1
- **`requires-python` is now `>=3.13`.** Python 3.11 and 3.12 are no longer supported (Phase 1 had lowered the
  floor to 3.11). The CI matrix is Ubuntu, macOS and Windows on 3.13 and 3.14, plus two Ubuntu lowest-direct
  legs (3.13 and 3.14); ruff targets `py313`, mypy `3.13`, the wheel-install check builds its venv on 3.13, and
  the 3.11 and 3.12 classifiers are gone. The pre-3.12 frame-walk fallback in `warn_external` was removed.
  `.python-version` is 3.14 and `uv.lock` records `>=3.13`.
- **`Dashboard.location` is removed** in favour of `Dashboard.crumbs` (a tuple of labels; the default is
  `("Home",)`). The dead `MenuState.move` is removed too.
- **`stop` is a reserved command.** A consumer shortcut `stop` now gets a `ShortcutConflictWarning` and can no
  longer be typed (the item stays reachable by arrow keys and position).
- **Actions behave differently.** `async` actions are awaited (they used to be called and ignored); a function
  that takes a `Context` runs in a thread; a failing action shows a traceback; a `dict`, `list` or multi-line
  `str` result is shown as content above the `Executed:` line instead of one line (the one-line form is
  unchanged for scalars); a second start while a job runs is rejected.
- **`app.panel` is thread-safe and ordered.** Every panel write goes through the one ordered queue, so direct
  `app.panel` calls no longer appear ahead of queued `push_log` records, and `DisplayPanel(widget)` (drawing
  straight on a `RichLog`, UI thread only) is now the legacy mode: `DisplayPanel(widget=None, *, emitter=None)`
  takes exactly one of the two.
- **`PanelInbox(app)` is now `PanelInbox(sink)`** (an object with `emit(event)`, called on the UI thread). It
  never raises, from any thread. It is internal.
- A `Text` passed as the `title` of `json`, `table`, `csv`, `array` or `pretty` is shown as plain text (its style
  is lost); `rule(Text(...))` keeps it.

Menus and warnings
- `MenuState.prune` resets the selection of the level it falls back to when it drops a level (it used to clamp
  it), so `refresh_menu` lands on the first item then.
- A callable label or value that keeps raising logs its DEBUG record once per item and field, until the callable
  next succeeds (it logged on every render).
- Shortcut-conflict and `attach_logging` warnings point at the first caller outside the package, using
  `warnings.warn(skip_file_prefixes=...)`: a `run(menu)` call is no longer attributed to `app.py`, and the
  console script's warnings no longer point at `cli.py`.
- Nav-bar cell widths count terminal columns (`rich.cells.cell_len`), not characters, so double-width glyphs in a
  label no longer overflow a row.
- `attach_logging` on an app that has exited attaches nothing: it warns (`LoggingAttachWarning`) and returns an
  inert, already-detached `LogAttachment`.
- A `logging` record is now a structured `log` event (logger, level number, time, exception text) and the panel
  formats it; the line shown is the same.

Secrets
- For a job with a secret prompt value, the redaction covers everything the job writes: log, text, progress,
  result and error text, and `json` and `table` payloads (turned into redacted plain text, so `pretty` loses its
  Rich styling). Rich renderables written by such a job are replaced by their type name (a `Text` by its plain text). A `JobSpec` keeps the value
  out of its `repr`.

### Removed
- `Dashboard.location` and `MenuState.move`.
- Support for Python 3.11 and 3.12, and the pre-3.12 `stacklevel` fallback of `warn_external`.

### Fixed
- **F5:** actions ran synchronously on the UI thread, `async` actions were never awaited, there was no busy
  state, cancel or result rendering, and a traceback was reduced to `str(exc)`. Actions are now jobs (see
  Added), and an exception shows the full traceback.
- **F9:** `print()` and stderr output from consumer code never reached the panel; inside a job it now lands
  there, in order with the job's other output.
- **C0-1** (F2/F3 follow-up): the log handler keeps `logger`, `levelno`, time and exception text instead of
  flattening the record to a string.
- **C0-2:** under overflow only `log` and `text` events are dropped, oldest first; `result`, `error`, `progress`,
  `hello`, `json`, `table` and the rest are never dropped, and `progress` is coalesced per job and id.
- **C0-3:** the inbox feeds a sink instead of the app (the seam for a headless sink in Phase 4).
- **C0-4:** `app.panel` calls, `emit`, `push_log` and `logging` records share one first-in first-out order.
- **C0-5:** `push_log` and the inbox never raise on the UI thread, whatever the sink does.
- **C0-6:** the "N log record(s) dropped" notice no longer repeats on every drain during sustained overflow: at
  most one opening and one closing line per episode.
- **C0-7:** an `attach_logging` after the app has exited no longer leaves a handler behind (see Changed).
- **C0-8:** a UI-thread backlog drain no longer holds up a worker thread's `logging` call (about 0.8 s before);
  a drain is bounded to a 15 ms slice per call.
- Thread-safe `set_menu`, `refresh_menu` and `go_home` for jobs (`ctx.set_menu` and friends); the `CLIApp`
  methods themselves stay UI-thread only.
- An abandoned job's output no longer reaches the terminal while Textual tears the app down: the capture is held
  over the real streams for the whole `run()`.

### Known limits
- An abandoned job's thread cannot be killed: it runs on in the background until the process ends, with its
  output, events and `Context` calls ignored. No `after_command` hook runs for it.
- For a job that floods the panel, the closing `N more log record(s) dropped (UI busy)` line can appear after the
  job's `Executed:` line.
- `asyncio.to_thread` (or the default executor) inside an `async` job can delay process exit until that thread
  ends. The framework's own job threads are daemons.
- While Textual suspends the app (`action_suspend_process`), an abandoned job's output can reach the terminal.
- `app.run_async()` (and so `run()`) is covered by the capture guard; `app.run_test()` is not.
- A self-exit (`app.exit()` from inside a thread or async job) shows a `Stopping X` warning, and an async job
  then ends `Cancelled:`.
- Secret jobs: `json`, `table` and `pretty` payloads are redacted into plain text (Rich `Pretty` styling is
  lost); a secret split across table cells or across lines is not caught; threads a secret job starts itself are
  not redacted.
- A `Text` title on `json`, `table`, `csv`, `array` and `pretty` loses its style.
- Not verified: a real terminal on Windows, Python 3.14, and Textual 0.80.0 on Python 3.13 (the CI workflow has
  not run on GitHub yet).

## [Unreleased] - Phase 1 (public API and packaging)

### Changed (behaviour)

Breaking for code written against Phase 0
- **`run()` requires a menu.** `run(menu, *, strict_shortcuts=False, max_lines=5000) -> int`. With no argument it
  used to launch the bundled demo and now raises `TypeError`. It forwards both options to `CLIApp` (it took
  neither) and returns the app's exit code, or 0 when the app set none (it returned `None`).
- **A bare `cli-interface` exits 2** ("the following arguments are required: target"). It used to launch the
  demo menu. The console script is now `cli_interface.cli:main` (was `cli_interface.app:run`); see Added.
- **The demos moved to `examples/`.** `cli_interface.example_menu`, `cli_interface.example_worker` and the root
  `main.py` are gone. Run the demo with `python -m examples.main` from a checkout, or
  `cli-interface examples.example_menu:build_menu` from the repository root. `build_example_menu(get_panel,
  get_app=None)` is now `build_menu(app)` and needs the app. `examples/` is in the sdist, not in the wheel.
- **`theme._BACK` and `theme._EXIT` are removed.** The Exit and Back cells are private `_NavCell` instances. An
  item with `description="__exit__"` or `"__back__"` used to quit or go back; it is now an ordinary item and
  runs its action. Detect the cells with `isinstance`, never by comparing fields.
- **`start_spinner()` and `stop_spinner()` do nothing before the app has started and after it has exited.**
  They used to raise Textual errors.
- **`requires-python` is now `>=3.11`** (was `>=3.13`). The declared dependencies are `rich>=13.3.3` (it was not
  declared) and `textual>=0.80,<9` (the ceiling is new).
- `CLIApp(menu)` raises `TypeError` if `menu` is not a `MenuItem`.
- **`max_lines` is validated**: `None` keeps every line, any other value must be a positive `int`; `0`, a negative
  number, `True`, a string or a float raise `ValueError` (before, none of these were validated or supported).

Menu labels and values
- `MenuItem.label` and `MenuItem.current_value` may be no-argument callables. They run on the UI thread, once per
  item for each repaint of the nav bar, and (label only) each time the breadcrumb, an `Executed:` or `Error in`
  line, a prompt title or a shortcut-conflict message is built. The result goes through `str()`; `None` as a
  value shows nothing; an `Exception` shows `<error>` and logs the traceback at DEBUG on `cli_interface.menu`.
  A callable value is never called for a `secret` item (it shows `••••`).
- The label in the `Executed: ...` and `Error in ...` lines is read before the action runs, so a toggle labelled
  `"Turn off" if on else "Turn on"` logs the label of the item you chose.
- The nav bar already repaints after every action and navigation. Changes made elsewhere need
  `refresh_menu()` (see Added).

Shortcuts and commands
- **Shortcuts are compared with surrounding whitespace stripped**, in matching, display, width and conflict
  detection. `" x "` now matches a typed `x` (it was displayed but never matched), a whitespace-only shortcut
  means no shortcut, and `" q "` is reported as reserved. The nav bar shows the stripped text.
- Shortcut conflicts are checked on `set_menu` and `refresh_menu` as well as on `CLIApp(menu)`. They are
  emitted as `ShortcutConflictWarning`, and the "were ignored" warning from `attach_logging` as
  `LoggingAttachWarning`. Both subclass `UserWarning`, so existing `UserWarning` filters still match; the
  message text is unchanged.
- The key hint no longer shows `q` on the first line. It reads "type a shortcut + Enter" on line 1 and
  "q + Enter  quit   PgUp / PgDn  scroll output   Home / End  top / bottom" on line 2 ("jump to" is dropped),
  and both lines fit an 80-column terminal. The help table's `q`/`quit`/`exit`, `b`/`back`, `clear` and
  `help` rows now say `+ Enter`.

Demo
- The Settings items now log into the panel (they used to log into nothing): each action attaches the demo logger
  for the length of the call, so each message appears once, also while the Worker Demo captures the root
  logger. Toggle Debug logs `Debug mode toggled on` or `off`, and Reset All ends at the root menu.

Dev only
- pytest's `filterwarnings` select the package's warnings by category (`error::cli_interface.ShortcutConflictWarning`
  and `...LoggingAttachWarning`) instead of by message text.

### Added
- **A public facade.** `from cli_interface import ...` exposes exactly `CLIApp`, `DisplayPanel`, `LogAttachment`,
  `LoggingAttachWarning`, `MenuItem`, `RESERVED_COMMANDS`, `ShortcutConflictWarning`, `__version__`,
  `attach_logging`, `find_shortcut_conflicts` and `run`. `LogAttachment` is exported as a return type only;
  `PanelInbox`, `TUILogHandler` and `MenuState` stay internal. Imports from `cli_interface.app`, `.menu`,
  `.display` and `.log_handler` still work.
  The package ships `py.typed`, and `__version__` (0.1.0) is read from `cli_interface/_version.py`.
- `CLIApp.set_menu(menu)`, `CLIApp.refresh_menu()` and `CLIApp.go_home()`. UI thread only (from another thread
  use `app.call_from_thread`); legal before the app starts, after it has exited and with a prompt open; the
  output panel is never touched except for WARNING lines about shortcut conflicts. `set_menu` goes back to the
  root with the first item selected, and if its check raises (strict mode, or a warning turned into an error)
  the old menu stays. `refresh_menu` keeps the current level and selection, and falls back to the nearest level
  that still exists. `go_home` does nothing at the root.
- `ShortcutConflictWarning` and `LoggingAttachWarning` (both `UserWarning`).
- **The `cli-interface module:attr` console script.** `attr` (dotted names allowed) is a `MenuItem` or a callable
  returning one; a callable with a required positional parameter is called with the `CLIApp`, so its actions can
  use `app.panel`. The current directory is put first on `sys.path`. Flags: `--strict-shortcuts`,
  `--max-lines N`, `--version`, `-h`. Exit 0 (or the app's code); 2 for a usage problem (missing or malformed
  target, module or attribute not found, wrong type, bad `--max-lines`, a conflict under `--strict-shortcuts`);
  1 with a traceback for an exception raised inside your own code.
- `Dashboard.crumbs`, the breadcrumb as a tuple of labels. `Dashboard.location` (joined with `|`) is kept.
- `examples/`: `main.py` (`python -m examples.main`), `example_menu.py` (`build_menu(app)`) and
  `example_worker.py`. The demo uses only the public API, a callable label and callable values.
- Packaging: dynamic version, an explicit sdist include list (`cli_interface/`, `examples/`, `README.md`,
  `LICENSE`, `CHANGELOG.md`; hatch adds `PKG-INFO`, `pyproject.toml` and `.gitignore`), and a wheel with the
  package only. `scripts/check_dist.py` (standard library only) fails on anything outside the allowlist, a
  missing member, wrong metadata or a version mismatch; run it after `uv build`.
- Tooling: ruff (`E4,E7,E9,F,UP,B`) and mypy configuration, and the dependency groups `test` (pytest,
  pytest-asyncio), `lint` (ruff, mypy) and `dev` (both; `uv sync` installs it). `cli_interface/`, `examples/` and
  `scripts/` are clean under both tools and `tests/` under ruff (this fixed 10 style findings in the package, 22 in
  `tests/` and the two mypy errors in `app.py`). `uv.lock` is regenerated for the new dependencies (Textual 8.2.8,
  Rich 15.0.0, ruff 0.17.3, mypy 2.4.1).
- CI (`.github/workflows/ci.yml`): `lint`; `test` on Ubuntu, macOS and Windows with Python 3.11 to 3.14 (locked
  versions) plus Ubuntu 3.11 and 3.14 with the lowest direct dependencies (Textual 0.80.0, Rich 13.3.3), each
  leg smoke-testing the console script; and `build` (sdist and wheel, `check_dist.py`, a clean-venv install).
- Dev only (not shipped): 885 tests (was 467 and one xfail), including the new facade, lifecycle, menu update,
  console script, packaging and `check_dist.py` suites; the tests that used the bundled demo now build it from
  `examples/`. They pass on Python 3.11 with Textual 0.80.0 and Rich 13.3.3 (lowest direct versions), on 3.12
  and 3.13 with Textual 8.2.8, and on 3.14 with both.
- Docs: the README is rewritten for the facade, dynamic menus, the console script, the examples and the
  limitations; the public API and the touched internals have docstrings.

### Removed
- The no-argument `run()` and the built-in demo behind it, `cli_interface.example_menu`,
  `cli_interface.example_worker`, the root `main.py` and `build_example_menu`.
- `theme._BACK` and `theme._EXIT`.
- The Python 3.13 floor, the Pilot caveat (call `app.exit()` before leaving `run_test` while a spinner runs) and
  the strict xfail test that covered it.

### Fixed
- **Timers after shutdown.** A spinner or phrase timer tick that landed after the app had shut down (or while a
  prompt was open) could fail against the torn-down screens. All three timers are now kept and stopped on
  unmount, and the tick callbacks do nothing when the app is not running. `on_mount` is idempotent, so a
  subclass may call `super().on_mount()`.
- **Nav-bar width.** A shortcut was counted as 2 columns whatever its length, so a long shortcut could make a row
  overflow. The width now follows the shortcut's length.
- **Reserved words in one place.** Typed commands dispatch through a single table (`RESERVED_ACTIONS`), and
  `RESERVED_COMMANDS` is derived from it, so the two cannot drift apart.
- The prompt dialog's `Enter` / `Esc` hint was invisible (zero height); it now shows.
- A menu label containing `|` was split into several breadcrumb crumbs.
- The key hint and help table did not say `+ Enter` for `q`, `b`, `clear` and `help`.
- If the app crashed, Textual's traceback printed local variables, which could include the typed secret of a
  prompted action. It is now printed without them (this overrides a private Textual hook, `_fatal_error`).
- Activating a submenu from a stale view (the menu was edited after the nav bar was drawn) no longer enters
  whatever item is selected now; the view is resynced instead.

### Notes
- **Callable timing.** A callable label or value is evaluated at paint time, not when the item is created, and
  once per paint. Keep them cheap and free of side effects; a callable that keeps raising logs a DEBUG record
  each time.
- **`ImportError` and the exit code.** `cli-interface` exits 2 (no traceback) only when the target module, or a
  parent package of it, cannot be found. Any other error while importing it, an `ImportError` inside your module
  included, is your code's error: it exits 1 with the traceback.
- **Warnings through `run(menu)`** are attributed to `app.py` instead of your call, on every Python version (the
  code uses a fixed `stacklevel`; `warnings.warn(skip_file_prefixes=...)` needs Python 3.12, and a fix is
  planned). Through the console script they point at `cli.py`. `CLIApp(menu)`, `set_menu` and `refresh_menu`
  point at your call.
- **Provisional decisions (they may change before the first release).**
  - `run(menu)` takes a required `menu` and a bare `cli-interface` exits 2.
  - The console-script target contract: `module:attr`, a callable with a required positional parameter receives
    the `CLIApp`, the current directory goes on `sys.path`.
  - The version stays 0.1.0 (it is not bumped for this phase).
  - The public surface is the 11 names above; two warning categories rather than one; render-time callables with
    the `<error>` fallback; surrounding whitespace in shortcuts is stripped, not rejected; `max_lines=None` means
    unbounded.
  - `rich>=13.3.3` rather than `rich>=13`, because Textual 0.80.0 itself requires `rich>=13.3.3`, so a lower floor
    could not be exercised; and the `textual<9` ceiling.
  - `examples/` ships in the sdist but not in the wheel.
  - The package has no `license` metadata, authors or URLs yet, and `hatchling` is not pinned in `[build-system]`.
- **Known gaps.** There is still no non-TTY run path (`cli-interface pkg:menu` with no terminal hangs or prints
  escape codes; only `--help` and `--version` are TTY-free). The CI workflow has not run on GitHub yet and the
  suite was run locally on macOS only, so the Windows and macOS-runner legs are unverified. `set_menu`,
  `refresh_menu` and `go_home` are UI-thread only and are not yet thread-safe proxies. After `refresh_menu`
  drops a level, the selection is clamped rather than reset.

## [Unreleased] - Phase 0 (hardening)

### Changed (behaviour)

Output and markup
- **Markup is off by default.** `panel.log` and `panel.text` show `[/x]`, `matrix[i][j]` and Windows paths
  literally. Opt in per call with `markup=True` (an unparseable string falls back to plain text), or pass a
  `rich.text.Text`.
- Table cells, headers and titles, rule titles, `json`/`array`/`pretty` titles, menu labels, shortcuts,
  `current_value`, prompt title and text, breadcrumbs, return values, exception text and typed commands are all
  literal. A label that deliberately contained markup (`"[bold]Run[/]"`) now shows the tags.
- `CLIApp` creates its `RichLog` with `markup=False`.

Scrollback
- The output panel is capped at `max_lines` (default 5000, `CLIApp(menu, max_lines=...)`) in every mode.
  Log mode used to keep 100 entries; content mode (json, table, ...) used to be unbounded. A larger dump now
  loses its head.

Prompts and secrets
- The `Executed:` line no longer echoes the prompted value: a "Password" prompt gave
  `Executed: Password('hunter2')` and now gives `Executed: Password`. A returned result is still shown after
  `→`, so an action that returns its input still displays it. A `secret` item gets no `→ result` suffix, and the
  value is redacted from its error text.

Shortcuts and commands
- **Reserved commands are case-insensitive** and always win: `Q`, `Quit`, `HELP`, `B` and `Clear` now work.
  `Q` used to fall through to a consumer shortcut `q`.
- **Shortcut conflicts** (reserved or duplicate on one menu level) now emit a `UserWarning` when `CLIApp` is
  built and a WARNING line in the panel at start-up. `CLIApp(menu, strict_shortcuts=True)` raises `ValueError`.
- **The Back cell now shows `b` instead of `esc`.** `esc` typed was never a command, so the yellow text did not
  work when typed; `b` is reserved and does. The Esc key still goes back. The Exit cell still shows `q`.
- Single-key shortcuts never fired because the input takes the key. The hint now reads "type a shortcut +
  Enter" (was "type a shortcut or command") and the help table lists `<shortcut> + Enter` and
  `<number> + Enter`.

Logging
- `CLIApp.push_log` is safe from any thread. Worker threads never wait on the UI (they used to block until the
  UI handled each record, which could deadlock). Records are queued, at most 10,000; beyond that the oldest are
  dropped and a "N log record(s) dropped" WARNING says how many.
- A record logged on the UI thread is written immediately (it used to be dropped with `RuntimeError`). Records
  logged before start are shown on start; handlers are silent after the app exits (no `handleError` output).
- `attach_logging` now returns a `LogAttachment` (it returned `None`; callers that ignore the result still
  work). The app detaches every attachment at exit, and `exclusive=True` restores the removed handlers.
- A repeat `attach_logging` for the same app and logger no longer stacks a handler: it returns a lease on
  the existing attachment (`share()`), and warns if `exclusive` or `level` was passed and ignored.

Demo and API signature
- The demo no longer enables DEBUG logging for the whole process (`main.py`). Its Worker Demo captures logs
  exclusively only while the worker runs, then restores the root logger's handlers and level; a second press
  while it runs logs a warning.
- `CLIApp.__init__` gains the keyword-only `strict_shortcuts` and `max_lines`. Positional use is unaffected.

### Added
- `MenuItem.secret`: masks the prompt input and the nav-bar `current_value` (`••••`), and `repr()` prints
  `'***'`.
- `PromptScreen(item_label, prompt, *, secret=False)`.
- `CLIApp(menu, *, strict_shortcuts=False, max_lines=5000, **kwargs)`.
- `attach_logging(app, logger=None, *, exclusive=False, level=None) -> LogAttachment`. The new `level=` sets
  the logger's level for the lifetime of the attachment.
- `LogAttachment` (`active`, `detach()`, `share()`, `logger`, `handler`, and use as a context manager). It
  restores exactly what it changed: removed handlers, and the level if nobody else changed it. Handlers the host
  added meanwhile are kept.
- `RESERVED_COMMANDS` (`q`, `quit`, `exit`, `b`, `back`, `clear`, `help`, `?`) and
  `find_shortcut_conflicts(menu)` in `cli_interface.menu`.
- `markup=` (keyword-only) on `DisplayPanel.log` and `DisplayPanel.text`; both also accept a `rich.text.Text`.
- `PanelInbox` (the bounded, thread-safe queue behind `push_log`) in `cli_interface.log_handler`. It is
  internal and not meant for consumers.
- Demo: a "Set Token" item (`k`) under Settings that shows a masked prompt.
- Docs: `README.md` (it was empty), this changelog, and docstrings for the public API.
- Dev only (not shipped): a pytest and Pilot suite in `tests/` (467 tests and one strict xfail for a known,
  harness-only timer teardown race), the `dev` dependency group (`pytest>=9.2.0`, `pytest-asyncio>=1.4.1`) and
  the pytest configuration in `pyproject.toml`. The suite passes on Python 3.11 with Textual 0.80, and on 3.13
  and 3.14 with Textual 8.2.8. `.gitignore` now excludes `.vscode/` and `.claude/`.

### Removed
- The fade of the oldest log lines, and with it the 100-entry log buffer, the per-record re-render of that
  buffer and the log-mode flag. Each `panel.log` call is now one `RichLog.write`.
- `CLIApp.on_key`: it never ran, because the command input consumes the keys.
- `theme._MAX_LOG_LINES`.
- `logging.basicConfig(level=logging.DEBUG)` in `main.py`: importing or running it no longer configures
  logging.

### Fixed
- **F1:** any `[/x]` in a log message, return value, exception text or typed command crashed the app with
  `MarkupError`, and `matrix[i][j]` or Windows paths were mangled. The same applied to menu labels, values,
  prompts and the header.
- **F2:** `TUILogHandler` dropped records logged on the UI thread with `RuntimeError`, and a worker thread
  blocked on the UI for every record, which could deadlock when the UI waited for the worker.
- **F3:** `attach_logging` had no detach, so the handler outlived the app (318 records after exit produced 637
  error lines) and `exclusive=True` permanently removed the host's handlers.
- **F4:** prompted values were echoed in the log, and the prompt input was not masked.
- **F6:** once log mode passed 100 lines every record re-rendered all 100 (about 3,700 down to about 104
  records/s), and content mode had no line limit.
- **F8:** reserved commands silently overrode consumer shortcuts and duplicates went unchecked, and the hint
  advertised single-key shortcuts that never fired.
- A typed superscript digit such as `²` crashed the app (`str.isdigit()` is true for it, `int()` raises
  `ValueError`). It is now an unknown command.
