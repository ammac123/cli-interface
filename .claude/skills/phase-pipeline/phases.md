# cli_interface: review findings and phase plan

Source: a four-agent review on 2026-10-30, covering the API, the `whiteboard.py` case study, packaging, and I/O and concurrency.

All findings were reproduced in automated runs on Textual 8.2.8, except the ones listed under "Inferred" below. Line numbers refer to commit `fdb8069` plus the untracked `whiteboard.py`.

**Goal (user):** a portable front end with a clean, documented API. It should display the output of other programs and scripts, and run them with specific parameters and settings, so that two codebases can be connected with minimal changes.

## Findings: `whiteboard.py` (the user's integration)

| ID | Problem | Where | Fix |
|---|---|---|---|
| W1 | `app.panel()` calls a property and raises `TypeError`, so no extraction can start from the Run menu | whiteboard.py:280, 290, 298, 305 | Use `app.panel` |
| W2 | `event.stop()` doesn't block `CLIApp.on_input_submitted`. Typing `exit` or `q` mid-run closes the UI while the thread keeps the process alive. A second run can also start. | whiteboard.py:95 | `event.prevent_default()`, or a framework hook (Phase 2) |
| W3 | The worker thread touches the UI directly: spinner, panel and menu. The spinner timer is created on the wrong thread. | whiteboard.py:208-263 | `call_from_thread` |
| W4 | The `asyncio.Event` stop signal is shared across threads. Setting it doesn't wake the worker, and later runs fail with "bound to a different event loop". | whiteboard.py:52, 81 | `threading.Event` |
| W5 | Menu closures keep the placeholder `Config()`. If the credential prompt is cancelled or `Config.load()` fails, editing any setting saves defaults over `config.toml`. | whiteboard.py:272, 148-199, 875 | Read the config from the app at call time |
| W6 | The Quick Run shortcut `q` quits the app instead | whiteboard.py:344 | Use another key |
| W7 | The password is echoed to the log, typed unmasked, and shown in "show all settings" | whiteboard.py:505, 818; F4 | |
| W8 | The SIGTERM handlers do nothing when idle and never exit mid-run, so `kill` doesn't work | whiteboard.py:114-123 | Remove them |

Smaller issues:
- The Playwright check always reports "Ready".
- "Reset all" and "Delete filter set" have no confirmation.
- `super().on_mount()` runs the framework's startup twice, creating duplicate timers.

## Findings: framework

| ID | Problem | Where |
|---|---|---|
| F1 | All output is parsed as Rich markup. Any `[/x]` in a return value, exception or typed command crashes the app with `MarkupError`. `matrix[i][j]` and Windows paths are mangled. | display.py:97, 103, 115, 132; app.py:269, 273, 366 |
| F2 | `TUILogHandler` always uses `call_from_thread`. Records logged on the UI thread are dropped with `RuntimeError`. Worker threads block until the UI handles each record, which deadlocks if the UI waits on the worker. | log_handler.py:20 |
| F3 | `attach_logging` has no detach, so the handler outlives the app: 318 records after exit produced 637 error lines. `exclusive=True` permanently removes the host's handlers. | app.py:383-403 |
| F4 | Prompt values are echoed (`Executed: Password('secret')`) and the prompt input isn't masked | app.py:267; widgets.py:81 |
| F5 | Actions run synchronously on the UI thread. `async` actions are never awaited. There is no busy state, cancel or result rendering, and tracebacks are reduced to `str(exc)`. | app.py:248-275 |
| F6 | Once log mode passes 100 lines it re-renders all 100 per record, dropping from about 3,700 to about 104 records/s. The RichLog has no `max_lines` in other modes. | display.py:101-118 |
| F7 | There is no non-TTY path. Piped or cron runs ignore `--help`, write about 22 KB of escape codes to stderr, and hang. | app.py:406 |
| F8 | Reserved commands (`q`, `b`, `clear`, `help`, `?`) silently override consumer shortcuts, and duplicates aren't checked. Single-key shortcuts never fire because the Input takes the key, although help advertises them. | app.py:339-376 |
| F9 | `print()` and stderr from consumer code never reach the panel | — |

Structural gaps:
- No public API: the `__init__` is empty, the README is 0 bytes and docstring coverage is about 30%. Consumers must write private state (`_state._stack`, `_refresh_view`).
- No parameter model: there is one untyped string prompt per action.
- No context object for actions, which forces the `ref`-list and `get_app` lambda hacks.
- No subprocess support: no argv, env or exit codes.
- Packaging:
  - `requires-python>=3.13` is too strict; the code works on 3.10–3.14 and textual 0.80.
  - `rich` is undeclared, and `textual` has no upper bound.
  - The sdist ships `whiteboard.py`, `uv.lock` and `.claude/`.
  - The demo is the console script.
  - There is no `py.typed`, no tests, lint or CI, and mypy reports 2 errors at app.py:138 and 141.
- About 720–760 of `whiteboard.py`'s 882 lines are glue code:
  - settings editor: ~360
  - job lifecycle: ~140
  - startup: ~80
  - menu plumbing: ~35, plus 37 `rebuild_menu()` calls

  The target is about 80–110 lines.

Inferred, not verified:
- Textual swallowing stderr in a real terminal.
- `basicConfig` output corrupting the screen.
- How the spinner and arrow glyphs render on Windows.
- Single-key shortcuts failing in a real terminal (they failed under Pilot).

## Target design

One event format connects every source to every output:

```
 sources                              one format               outputs
 in-process function ── ctx.* ─────┐
 subprocess ── emit.py (JSON lines)┼─▶ Event {v, kind, …} ─┬─▶ TUI DisplayPanel
 plain stdout/stderr lines ────────┤                       └─▶ headless Rich console / JSONL
 (later) socket attach ────────────┘
```

- **Events** are versioned JSON objects `{"v":1,"t":…,"kind":…}`. The kinds are `hello`, `log`, `progress`, `text`, `json`, `table`, `result` and `error`.
  - In-process code emits them through `ctx`.
  - Subprocesses emit them through the zero-dependency `emit.py`, over the fd named in `CLI_IFACE_FD`. The Windows fallback prefixes stdout lines with `\x1e`.
  - Plain lines become `log` events.
- **One parameter schema,** taken from a signature, dataclass or argparse parser, becomes a TUI form, kwargs, argv or env, or headless CLI flags.
- **Commands are built on `MenuItem`,** so existing menus keep working.

Consumer sketch (naming is final: `App`, `Context`, `@app.command`):

```python
from typing import Annotated
from cli_interface import App, Context, Param, Secret

app = App("NextGen Automation", capture_loggers=["nextgen_automation"])

@app.on_startup
def load(ctx: Context) -> None:
    ctx.state.cfg = Config.load()
    ctx.require(ctx.state.cfg, "user_name", Secret("user_password"), on_done=ctx.state.cfg.save)

@app.command("Run/Extract", key="e", cancellable=True)
async def extract(ctx: Context,
                  filter: Annotated[str, Param(choices=lambda c: list(c.state.cfg.filters))] = "default",
                  sample: int | None = None) -> str:
    combos = ctx.state.cfg.get_filter_combinations(filter)[:sample]
    data = await run_extraction(ctx.state.cfg, combos, stop_event=ctx.cancelled)
    return f"Saved {len(data)} rows"

app.script("Tools/Legacy export", ["python", "-m", "legacy.export"], params={"--out": Path})
app.settings("Settings", model=lambda c: c.state.cfg, save=lambda c: c.state.cfg.save(),
             secret={"user_password"})
app.run()   # TUI on a TTY; headless when piped or with --no-tui
```

`Context` provides a thread-safe panel proxy, `log`, `progress`, `status`, `cancelled` (a `threading.Event`), `state` and an async `ask`.

The runners are `JobSpec`, `Job`, `InProcessRunner` (using `asyncio.to_thread`) and `SubprocessRunner` (using `create_subprocess_exec` and `pass_fds`, with killpg escalation on cancel).

## Phase plan

Effort sizes: S = under half a day, M = 1–2 days, L = more than 2 days.

### Phase 0: fix what's broken (about a day)

**Status: done.** Committed on branch `phase-0`. The pipeline record is in `.claude/pipeline/phase-0*.md`, and the ledger is `phase-0.md`.

None of this is throwaway, because the Phase 2 runner builds on it.

| Item | Covers | Effort |
|---|---|---|
| Plain text by default; markup is opt-in (`markup=True`) or via `Text`. Escape interpolated strings. | F1 | S |
| Log handler: emit directly on the UI thread, use a bounded non-blocking queue from other threads, and do nothing after exit. `attach_logging` returns a detach handle and restores the original handlers. | F2, F3 | S |
| Stop echoing prompt values; add masked password prompts | F4 | S |
| Set RichLog `max_lines` and remove the re-render on every record | F6 | S |
| Validate reserved and duplicate shortcuts. Make single-key shortcuts work, or remove them from help. | F8 | S |
| Remove `basicConfig` from `main.py` | — | S |
| `whiteboard.py` W1–W8, only if the user puts it in scope | W1–W8 | S |
| pytest and Pilot harness; turn `probes/` into regression tests | — | S–M |

### Phase 1: public API and packaging

**Status: done.** Committed as `71a0e49` on branch `phase-1` (local, not pushed, not yet merged into `main`). The pipeline record is in `.claude/pipeline/phase-1*.md`, and the ledger is `phase-1.md`. 885 tests pass. Every item in the table and every "Phase 1" carry-forward below was closed; the only exceptions are listed under "Carried forward from Phase 1".

| Item | Effort |
|---|---|
| `__init__` facade with `__all__`, `py.typed`, `__version__` | S |
| `set_menu()`, `refresh_menu()`, `go_home()`; labels and values can be callables | S |
| `requires-python>=3.11`, declare `rich>=13`, `textual>=0.80,<9` | S |
| Explicit sdist include list; move the demos to `examples/`; console script `cli-interface pkg.mod:build_menu` | S–M |
| ruff and mypy; CI on ubuntu, macos and windows × Python 3.11–3.14 with lowest-direct resolution; a build allowlist check | M |

### Phase 2: job runner and `Context` (the keystone)

**Status: done** (2026-11-03). Branch `phase-2`, from `23a8ed1`; local commit, not pushed. The pipeline record is in `.claude/pipeline/phase-2*.md`, and the ledger is `phase-2.md`. 1,742 tests pass on Python 3.13 with Textual 8.2.8 and with Textual 0.80.0 / Rich 13.3.3. The same phase also dropped Python 3.11 and 3.12 support (`requires-python>=3.13`, the user's decision on 2026-11-03). Cost: about 3.4M reported subagent tokens and about 14 h, so later phases follow the "Lean mode" section of SKILL.md.

| Item | Effort |
|---|---|
| Event schema v1, with `DisplayPanel` as a thread-safe sink | M |
| Every action runs as a job: sync functions in a thread, async functions awaited. Includes `Context`, busy state, a refcounted spinner, a built-in `stop`, rendering of return values by type, and full tracebacks. | M |
| Per-job capture of `print()` and stderr | S–M |
| Public hooks: `on_startup`, `on_shutdown`, `before_command`, `after_command` | S |

### Phase 3: parameters and settings (the largest `whiteboard.py` saving, about 350 lines)

**Status: done** (2026-11-03). Branch `phase-3`, from `646c781`; local commit, not pushed. Pipeline record: `.claude/pipeline/phase-3*.md` (ledger `phase-3.md`). 2,007 tests pass on Python 3.14 with Textual 8.2.8, and the lowest-direct run (Python 3.13, Textual 0.80.0) passed too. Lean mode held the cost down. C2-4 (styled `Text` titles on json/table events) was deferred to Phase 4.

| Item | Effort |
|---|---|
| Parameter schema from a signature, dataclass or argparse, giving forms with validation, Select, Switch and masked fields | M |
| `app.settings(...)` for dataclass or pydantic models: nested submenus, live values, reset with confirmation | M |
| `confirm=` on destructive actions | S |

### Phase 4: external programs and headless mode

| Item | Effort |
|---|---|
| `SubprocessRunner`: streams events and stdout/stderr, reports exit codes, cancels via process group | M |
| `emit.py` and a versioned protocol document | S |
| Headless sink for CI and cron; `cli-interface run "Settings/Set Port" 8080` | M |
| Windows fallback for the event channel | S–M |

### Later

- Socket attach through `CLI_IFACE_ADDR` (M–L).
- Configurable theme and phrases, with an ASCII fallback (M).
- A docs site with mkdocs-material and mkdocstrings (M).
- Snapshot tests with seeded phrases (S).

## Carried forward from Phase 0

Sources:
- integration report `.claude/pipeline/phase-0-integration-2.md` §3, which has the details;
- the Documenter's findings, `phase-0-docs.md` §5;
- the review rulings.

User decisions (2026-11-01):
- The planner's five defaults are accepted:
  - shortcut clashes warn by default (`strict_shortcuts=True` raises);
  - no markup in labels;
  - `max_lines=5000`;
  - reserved commands are case-insensitive;
  - no warning when a digit shortcut shadows a position.
- `whiteboard.py` (W1–W8) stays out of Phase 1.
- `phase-0` was merged into `main` (fast-forward, local only). Phase 1 branches from `main`.

**Phase 1** (all done in Phase 1; kept for reference)

*Timer lifecycle* (rulings E and test-3):
- Add `if not self.is_running: return` to `_tick_spinner`, `_cycle_spinner_phrase` and `_cycle_phrase`.
- Store all timer handles.
- Make `on_mount` idempotent: no duplicate `set_interval`.
- Stop timers in `on_unmount`.
- Remove the strict xfail `test_late_timer_ticks_after_teardown_are_harmless`.

*Shortcuts and reserved commands:*
- Make `RESERVED_COMMANDS` the single source for dispatch. Today the `app.py` inline tuples duplicate it.
- Add a `ShortcutConflictWarning(UserWarning)` category, then switch the pytest `filterwarnings` from a message regex to that category.
- Extract `_validate_menu()` for `set_menu()` and `refresh_menu()`.
- Shortcuts with leading or trailing whitespace are displayed but never match, and are not reported. Strip or reject them.
- Fix NavBar `_compute_item_width`: replace `sc = 2` with `len(shortcut) + 1`.
- Fix the sentinel collision: a consumer `MenuItem(description="__exit__"/"__back__")` acts as Exit or Back. Use a private sentinel object instead.

*API surface:*
- `run(menu)` cannot pass `strict_shortcuts` or `max_lines`.
- `LogAttachment.__init__` is public but bypasses auto-detach. Export it as a return type only, and keep `PanelInbox` and `TUILogHandler` out of `__all__`.
- Validate and document `max_lines` for `None` and `<=0`.

*Demos and tests:*
- Demo "Settings" items log into nothing. Attach a capture for `cli_interface.example_menu` when the demos move to `examples/`.
- Coupling between `tests/` and the demos, which breaks when they move: `conftest` `gated_worker`/`fast_worker`, `helpers.build_demo_app`, `test_demo.py`, the demo tests in `test_real_run.py`, the demo walk in `test_shortcuts.py`, and the no-arg `run()` in `test_regression.py`.

*UI polish and style:*
- `#prompt-hint` has height 0 (ruling B).
- A `|` in a label splits the breadcrumb (R9).
- The hint and help `q` rows lack "+ Enter".
- Ruff style: quoted annotations, UP rules, `zip(strict=)`. mypy still reports the 2 baseline errors at `app.py:158` and `161`.

*Packaging:*
- `requires-python` is still `>=3.13`, but the suite passes on 3.11 with textual 0.80. Relock after changing it.
- The sdist now also ships `tests/`.
- `.claude/` stays out only because of the user's `.gitignore` edit, so an explicit include list is still needed.

*Hardening:* Textual's fatal traceback uses `show_locals=True` and can print a secret `value` local.

**Phase 2**
- `TUILogHandler` flattens records to strings. The `log` event needs `logger`, `levelno`, `t` and `exc`, formatted in the renderer.
- The inbox drops the oldest records. That is wrong for `result`, `error`, `progress` and `hello`: add a per-kind policy or a non-droppable lane.
- `PanelInbox(app)` should become `PanelInbox(sink)` for the headless sink (Phase 4).
- Direct `panel.log` calls bypass the inbox, so FIFO order holds only among `push_log` records. Route everything through `emit`.
- On the UI thread, `push_log` can raise (the direct write path propagates). Decide on "never raises".
- Under sustained overflow, the dropped-record notice repeats once per drain.
- `attach_logging` after app exit is not auto-detached.
- R5: a UI-thread backlog drain can stall a worker's `logging` call by about 0.8 s.

**Phase 3**
- Secret redaction covers a single value in exception text. Forms and `app.settings(secret=...)` need a redaction set that also applies to the log path.

## Carried forward from Phase 1

Sources: integration report `.claude/pipeline/phase-1-integration-1.md` §4, review reports `phase-1-review-1.md` and `phase-1-review-2.md`, and the Documenter's report `phase-1-docs.md` §5.

**Phase 2**
- Warnings raised through `run(menu)` point at `app.py`, not the caller. Use `skip_file_prefixes` on 3.12+ with a `stacklevel` fallback for 3.11.
- `set_menu`, `refresh_menu` and `go_home` are UI-thread only (other threads use `call_from_thread`). Add thread-safe proxies on `Context`.
- A raising callable label or value logs a full-traceback DEBUG record on every render (about 21 records for 5 interactions). Log the first failure per (item, field) only.
- `MenuState.prune` clamps the selection, so the highlight can land on an arbitrary item of the shallower level. Reset it instead.
- `CLIApp._fatal_error` overrides a private Textual hook. If Textual renames it, the secret protection silently stops, so keep its regression test.
- Retire `Dashboard.location` in favour of `Dashboard.crumbs`. Remove the dead `MenuState.move`, which predates Phase 1.
- `run(menu)` cannot hand back the app, so an action that needs `app.panel` must use `CLIApp(MenuItem("Home"))` plus `set_menu(build_menu(app))`. The CLI's rule that a required positional parameter receives the app is the same shape. `App` and `Context` supersede both.
- Nav-bar widths count characters, not terminal columns, so wide glyphs can overflow.

**Phase 4**
- F7 (no non-TTY path) is still open: `cli-interface pkg:menu </dev/null` hangs or emits escape codes, and only `--help` and `--version` are TTY-free.
- The CLI grammar is a bare required `TARGET`. The planned `cli-interface run "Settings/Set Port" 8080` needs either `run` reserved as a first-argument subcommand (safe, because a target must contain `:`) or a different verb. **User decision.**

**Decisions the planner defaulted, to raise with the user** (all provisional, each reversible in a line or two):
- D1: `run(menu)` requires a menu, and bare `cli-interface` exits 2. Neither falls back to a demo.
- D2: the `module:attr` target contract. The target is a `MenuItem` or a callable returning one. A callable with a required positional parameter gets the `CLIApp`. The current directory is prepended to `sys.path`. An `ImportError` inside the user's module is a traceback with exit 1, and only a missing target exits 2.
- D3: the version stays 0.1.0.
- D4: the 11-name `__all__`.
- D5: two warning categories, `ShortcutConflictWarning` and `LoggingAttachWarning`.
- D6: callable labels and values are evaluated at render time with an `<error>` fallback, and a secret item's callable is never called.
- D8: shortcut whitespace is stripped silently, not rejected.
- D9: `max_lines=None` means unbounded.
- D12: `rich>=13.3.3` instead of the `>=13` in the plan, because textual 0.80 pulls in rich 13.3.3 at minimum, so a lower floor can't be tested.
- D14: the sdist ships `examples/` and the wheel does not.

**Packaging nits** (user decision):
- No `license` metadata or classifier, and no authors or URLs.
- `hatchling` is unpinned in `[build-system]`.
- hatch force-adds the repo `.gitignore` to the sdist. It is allowlisted, but it carries the user's `.vscode/` and `.claude/` lines.

**Unverified**
- The Windows and macOS CI legs, and the CI YAML as a whole, have never run. In particular, `setup-uv@v7`'s `python-version` input combined with `uv run --no-project` is untested.
- The real TUI under a TTY was never exercised; only Pilot and `run_test()` were.
- `uv build` and `check_dist.py` ran on macOS only.

**Housekeeping**
- Stale ignored `__pycache__/main.cpython-311.pyc` and `main.cpython-313.pyc` sit at the repo root from the deleted `main.py`. They are harmless.

## Probes

The reproduction scripts in `probes/` were copied from the review's scratchpad. `api/probe4.py` and `pkg/smoke_test.py` assert baseline behaviour and are expected to fail now. The `tests/` suite supersedes all the probes. Run them with `uv run python <file>`.

| Folder | Covers |
|---|---|
| `io/` | `exp1`: logging across threads (F2); `exp2`: logs after exit (F3); `exp3*`: markup and print crashes (F1, F9); `exp4`: reruns; `exp5`: workers; `exp6`: exit latency; `exp7`: throughput (F6). `common.py` is shared. |
| `pkg/` | `smoke_test.py`, `edge_test.py`, `typed_markup_test.py`: install, import and markup edge cases |
| `case/` | `whiteboard.py` probes (W1–W8) |
| `api/` | API probes; `sigproto.py` is a prototype of the signature-to-form schema (Phase 3) |

The full agent reports are in the session transcript at `~/.claude/projects/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199.jsonl`, which is subject to transcript cleanup.

## Carried forward from Phase 2

Sources: `.claude/pipeline/phase-2-review-1.md`, `-review-2.md`, `-review-3-classification.md`, `phase-2-test-1.md` §4 and the plan §6 (decisions U1–U14).

**Phase 3**
- `capture_loggers=` appears in the consumer sketch but was not built (`attach_logging` covers it).
- A job that calls `app.exit()` on itself shows a cosmetic "Stopping X" WARNING, and an async job ends "Cancelled:". Fix: pass a "quit requested by this job" flag into `begin_quit`.
- `PanelInbox._deliver` counts sink exceptions in `write_errors` but never logs them.
- `Text` titles on `json`/`table`/`array`/`pretty`/`csv` lose their style (those events have no `obj` slot).
- Secret redaction: still no shared redaction set for forms and `app.settings(secret=...)`; a secret split across table cells or lines is not caught; threads a secret job spawns are not redacted.
- `App.command` takes no parameter schema yet (Phase 3 `Param`).
- Possible simplification: the abandon-after-grace policy (daemon threads, capture refs, outer guard, `reinstall`) produced most of the edge cases this phase. A hard-exit policy would remove them, at the cost of skipping a stuck job's own cleanup. **User decision** if it keeps causing bugs.

**Phase 4**
- `events.dumps` can emit `NaN`/`Infinity`, which is invalid strict JSON. Fix before the wire protocol.
- While Textual suspends the app (`action_suspend_process`), an abandoned job's output can reach the terminal.
- F7 (no non-TTY path) and the `run` verb decision are still open (see Phase 1 carry-forward).

**Decisions the planner defaulted, to raise with the user** (plan §6; all provisional and reversible): U1 context-free sync `MenuItem` actions run inline on the UI thread; U2 `App` subclasses `CLIApp` and `__all__` has 13 names; U3 own daemon threads instead of `asyncio.to_thread`; U4 a second run while busy is rejected, `quit_grace` 2.0 s, second `stop` abandons; U5 `stop` is reserved; U6 return-value rendering changes; U7 tracebacks always shown; U8 drop-notice rule; U9 capture routing; U10 spinner per job; U11 `Context` has no `app`, `ask` or `require`; U12 `app.jobs.wait_idle` is the public test hook; U13 `attach_logging` after exit warns and returns an inert handle.

## Carried forward from Phase 3

Sources: `.claude/pipeline/phase-3-review-1.md`, `-review-2-classification.md`, `-test-1.md`, `-docs.md`.

**Decision for the user**
- The shared secret set is app-wide. Once any secret is registered (a settings secret with a non-empty value, a submitted masked form value, `add_secret`), every later job's json/table/pretty output renders as plain text and a renderable shows as `<Panel>`. Options: keep (documented), render styled output through a redaction-aware path, or scope the set per command.
- Auto-derived forms on existing commands (`params=False` opts out) and form-then-confirm ordering were planner defaults; both are tested and documented.

**Phase 4**
- C2-4: `Text` titles on json/table/array/pretty/csv lose their style (events have no `obj` slot).
- `ctrl+c` does not quit while a form, confirm or prompt is open (`CLIApp` binds it without `priority`; Textual 0.80 has no `ctrl+q`). Use `Esc` first.
- `app.panel.log()` called from inside a job body is not redacted (use `ctx.panel`); a thread a secret job spawns is not redacted; the redaction set only grows, so a very short secret garbles later output (consider a minimum length).
- `params=<ArgumentParser>` cannot mark secrets (add a `meta` argument).

**Minor (any later phase)**
- `reset_defaults` can raise part-way (for example pydantic `validate_assignment`) before it returns `changed`; roll back from a `before` snapshot.
- Entering a factory-backed settings group replaces `source.obj` while an edit job may still hold the old object.
- `add_command("Settings/Foo")` can graft a child into a `_SettingsGroup`, and the next rebuild deletes it; refuse it in `_cmd_walk`.
- A required Literal/Enum choice with no default preselects its first option, so it never shows "Required".
- `ParamSpec.__repr__` shows a secret's code-supplied default; `convert` returns a mutable `spec.default` by reference.
- `settings.secret_values` is unused (`settings_menu.secret_strings` re-implements it): remove or reuse.
- `choices` callables and `initial()` run on the UI thread.
- A test through the real form path for `_fatal_error` scrubbing; `FormScreen` ids for colliding names are asserted only in `test_forms.py`.
- Carried from Phase 2 and still open: the self-exit "Stopping X" WARNING; `PanelInbox._deliver` write-error logging; the abandon-policy simplification.
