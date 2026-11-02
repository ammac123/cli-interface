WP-7 is done. The demos now live in `examples/`, the three old files are gone, and every self-check and acceptance check passes. Nothing is committed.

## 1. Files changed, moved, deleted
Paths are relative to `/Users/andrewmacleod/workspace/cli_interface`.
- **`git mv cli_interface/example_menu.py examples/example_menu.py`, then rewritten.** Scope IDs: P1.4b, CF-11, P1.2a dogfood, CF-16.
  - `build_example_menu(get_panel, get_app=None)` is now `build_menu(app: CLIApp) -> MenuItem`.
  - All `get_app is None` branches are gone, and Spinner Demo is always present.
  - Imports come only from the facade: `from cli_interface import CLIApp, LogAttachment, MenuItem, attach_logging`, plus `from . import example_worker`. There are no `cli_interface.<submodule>` imports.
- **`git mv cli_interface/example_worker.py examples/example_worker.py`.** Content is byte-identical, 0 lines changed. `log = logging.getLogger(__name__)` is now `examples.example_worker`. `run(steps=14, delay=0.35)` is unchanged.
- **`git mv main.py examples/main.py`, then rewritten.** Scope ID: P1.4b.
  - `main() -> int` does `app = CLIApp(MenuItem("Home")); app.set_menu(build_menu(app)); app.run(); return app.return_code or 0`.
  - It ends with `raise SystemExit(main())`. It has no `logging.basicConfig`, and keeps the why-comment saying so.
  - Only `python -m examples.main` is a supported launcher.
- **New: `examples/__init__.py`, empty.**
- **Deleted from the working tree:** `cli_interface/example_menu.py`, `cli_interface/example_worker.py`, `main.py`.

### Git history caveat
- `example_menu.py` shows as a rename in `git diff -M HEAD` (`{cli_interface => examples}/`). `example_worker.py` is a pure rename.
- `main.py` will not survive as a rename at commit time. The rewrite drops similarity below 50%, so `git diff -M --stat` shows `examples/main.py | 20 ++++` and `main.py | 7 --`.
- If the Integrator wants history for `main.py`, commit the pure `git mv` first and the edit second. Otherwise accept it as add plus delete.
- `examples/__init__.py` is untracked and needs adding at integration.

## 2. Behaviour of the new demo
- **CF-11, D19.**
  - `log = logging.getLogger("examples.example_menu")` has a fixed name and `propagate = False`, set at import.
  - Each Settings action runs `with attach_logging(app, log, level=logging.INFO):` through a local helper `capture_settings()`.
  - Nothing stays attached between actions. Level and handlers on the demo logger are restored after each call.
  - Set Token still writes directly with `app.panel.log`.
- **P1.2a dogfood.**
  - Callable `current_value` on Toggle Debug (`on`/`off`) and Set Port (the port number), both read from a small `settings` dict.
  - Callable `label` on the Worker Demo item: `"Worker Demo (running)"` while the worker flag is set, else `"Worker Demo"`.
  - The worker's `_finish` runs on the UI thread through `app.call_from_thread`. It clears the flag, stops the spinner and calls `app.refresh_menu()`.
- **go_home.** Reset All resets port and debug, logs, then calls `app.go_home()`. It ends at `Home`.
- **Worker thread cleanup.**
  - Only `RuntimeError` is caught around `call_from_thread`, in case the app has already exited.
  - `NoMatches` is removed. It was dead code, because spinner methods no longer query widgets (WP-4).

## 3. Deviations and extra decisions
- `LogAttachment` is imported from the facade, for the helper's return type.
- `worker_running.set()` now comes after the root `attach_logging`. Before, a raising attach (for example with `LoggingAttachWarning` escalated to an error) would have left the flag stuck.
- The worker flag is cleared inside the UI-thread `_finish`, or in the `RuntimeError` path. This avoids a restart race in which a late `clear()` could erase a newer run's guard.
- `set_port` is restructured: parse and validate first, then log. Its result strings are unchanged.
- The Toggle Debug message is now `Debug mode toggled on|off`. It was `Debug mode toggled`.
- The Worker Demo's `Executed:` line now reads `Executed: Worker Demo (running)`, because the label is resolved after the action returns. I checked this in the acceptance script.
- No `Spinner Demo` conditional exists any more.

## 4. Cross-package requests
None. `cli_interface/cli.py` was not touched.

## 5. Tester hand-off (CF-12)
**New names**
- Module `examples.example_menu`: `build_menu(app: CLIApp) -> MenuItem`, `log` (logger `examples.example_menu`, `propagate=False`).
- Module `examples.example_worker`: `run(steps=14, delay=0.35)`, `log` (logger `examples.example_worker`, propagates to root as before).
- Module `examples.main`: `main() -> int`. The attribute is `main`, not `run`.
- `pythonpath = ["."]` already makes `examples` importable.

**Replacements**
- **`tests/helpers.py` `build_demo_app(**kw)`:**
  ```python
  from examples.example_menu import build_menu
  app = CLIApp(MenuItem("Home"), **kw)
  app.set_menu(build_menu(app))
  return app
  ```
  The root label must stay `"Home"`, because the tests assert `dash.location == "Home"`.
- **`tests/conftest.py` fixtures:** change `from cli_interface import example_worker` to `from examples import example_worker`. Monkeypatching `example_worker.run` still works. The menu calls `example_worker.run()` through the module attribute at click time, with no arguments, so `fast_worker`'s `lambda: original(steps=4, delay=0.03)` still fits.
- **`tests/test_demo.py`:**
  - The `with_app` parametrization is obsolete. `build_menu(app)` has no app-less form, and Spinner Demo is always present.
  - The menu tests can pass `CLIApp(MenuItem("Home"))` or a stub.
  - Replace `runpy.run_path(REPO/"main.py")` with `runpy.run_module("examples.main", run_name="not_main")`. `run_path` on `examples/main.py` fails on the relative import because there is no parent package.
  - Assert `callable(ns["main"])`.
  - The fresh-interpreter import probe should import `examples.main` and assert `m.main.__module__ == "examples.main"`. Root handlers and level stay `[]` and `WARNING`.

**Behaviour that changed**
- `item.label == "Worker Demo"` no longer matches, because the label is a callable. Use `item_label`. All other demo labels are still plain `str`, including Home, View Output, Settings, Audio, Set Port, Set Token and Toggle Debug.
- New panel lines from Settings, each appearing exactly once:
  - `Volume set to N%`
  - `Port set to N`
  - `Invalid port 'x': ...`
  - `Debug mode toggled on|off`
  - `All settings reset to defaults`
- Each is followed by the unchanged `Executed: ...` line. The record comes first.
- Unchanged:
  - `Executed: Set Port → port → 8080`
  - `Token accepted (7 chars)`
  - `Worker already running`
  - `Launching background worker`
  - The exclusive-root-capture contract. The Worker Demo still calls `attach_logging(app, exclusive=True, level=DEBUG)`, and with a host-attached root it still warns, now as `LoggingAttachWarning`. `pytest.warns(UserWarning, match="ignored")` still matches.
- Reset All now ends at `Home`.
- The NavBar now shows `Toggle Debug (off)` and `Set Port (8080)`, and `Worker Demo (running)` during a run.
- `tests/test_shortcuts.py` demo walk (`enter_by_displayed_shortcut(("Settings", "Audio"))`) works with these labels. It only needs the `build_demo_app` swap, once the `_BACK`/`_EXIT` import error from WP-4 is fixed.
- Mid-run close: the guard catches only `RuntimeError`.

**Suite state after the move** (`pytest --continue-on-collection-errors`): 357 passed, 2 failed, 4 errors. All are listed in plan §5.
- 2 failed: `test_regression` `test_push_log_and_panel_surface_is_unchanged` and `test_late_timer_ticks_after_teardown_are_harmless` (both WP-4's).
- 4 errors:
  - Collection error in `tests/test_shortcuts.py` (WP-4's `_BACK`/`_EXIT` removal).
  - Collection error in `tests/test_demo.py`.
  - Two `tests/test_real_run.py` demo tests that error on the `gated_worker`/`fast_worker` fixtures.

## 6. Acceptance results
**Self-checks**
- `uvx --offline ruff@0.17.3 check --no-cache examples`: all checks passed.
- `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null examples`: no issues in 4 files.
- `uv run --no-sync python -c "import examples.main"` imports and does not start the app. A fresh interpreter confirms root handlers and level are unchanged.
- `git status` shows `cli_interface/example_menu.py`, `cli_interface/example_worker.py` and `main.py` gone, with staged renames for the first two and for `main.py` (see the caveat above).

**Pilot acceptance** (`/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp7/accept.py`): about 75 checks, ALL OK on Python 3.13 with textual 8.2.8, and on Python 3.11 with textual 0.80.0 using the WP-4 venv at `scratchpad/wp4/v080`. It covers:
- All 7 View Output views and the Spinner Demo render, with no `Error in` lines.
- `Settings > Audio > Volume Low` writes `Volume set to 25%` exactly once, before its `Executed:` line, and leaves no handler or level on the demo logger or root.
- Callable values update in the NavBar after Toggle Debug and Set Port. The invalid-port path logs once and leaves the port alone. The secret token is masked.
- Reset All ends at `Home`.
- With the Worker Demo's exclusive root capture active (one TUI handler on root, the host's handler removed, root at DEBUG), the Volume, Debug, Port and Reset records each appear exactly once, and worker records appear once.
- A second Worker Demo press warns and adds no handler.
- The label reads `(running)` during the run and is plain `Worker Demo` afterwards. Root is restored and a restart works.
- With a host-attached root, `LoggingAttachWarning` is emitted and the host's capture survives.
- A real `app.run(headless)` closed mid-worker returns 0, restores root, and leaves no thread errors.
- No `TUILogHandler` is left on any logger after exit in any scenario.
- `examples.main.main()` with `CLIApp.run` patched builds the `Home` root and returns 0.
- `cli_interface.cli.main(["examples.example_menu:build_menu"])` (WP-6's `cli.py`, which was already present) resolves the demo with `CLIApp.run` patched, from the repo root.

**Controls**
- Negative control: setting `propagate = True` makes 4 "exactly once" checks fail with count 2 under the root capture. This shows the checks discriminate and that `propagate=False` is what gives exactly-once.
- `scratchpad/wp7/midrun_pilot.py` covers the `run_test` variant of a mid-worker close, where the loop outlives the app. It passes on both Textual versions.

## 7. Not verified
- A real `cli-interface` console-script run through a TTY. I only called `cli.main` with `CLIApp.run` patched.
- Windows, Python 3.14, real-terminal rendering.
- Reaching `call_from_thread` after exit on the Python 3.14 event loop.

## 8. For the Documenter (step 6)
`README.md:185` still says `uv run python main.py`. It should become `python -m examples.main` or the `cli-interface examples.example_menu:build_menu` target. The `CHANGELOG.md` mentions of `main.py` are historical, so leave them.