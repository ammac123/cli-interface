## WP-4 review round 1: issue 9 fixed

Both requested changes are in `/Users/andrewmacleod/workspace/cli_interface/cli_interface/example_menu.py`. Re-run `verify.py` passes 36/36 and `realrun.py` is still clean. The dedup check you asked for is also in place and passes.

### Changes
- **Import moved to the top.** `from textual.css.query import NoMatches` is now a module-level import. Only `example_worker` and `.app` stay lazy inside `run_worker`, because of the circular import.
- **Nested cleanup in the worker thread's `finally`.** The exception guard is still `except (RuntimeError, NoMatches)`.
  ```python
  finally:
      try:
          capture.detach()
      finally:
          try:
              app.call_from_thread(app.stop_spinner)
          except (RuntimeError, NoMatches):  # app already exited
              pass
          finally:
              worker_running.clear()
  ```
  A failing `detach()` can no longer leave `worker_running` set. `stop_spinner` is still attempted after a failed detach.

### Verification
- **`verify.py`:** 36/36 pass. It covers the token flow, the worker attach and detach scoping, the double-start guard, restart, and mid-run exit under `run_test` with no excepthook or `handleError` calls.
- **`realrun.py`:** unchanged result. A real `app.run(headless=True)` with an exit mid-run gives no worker traceback, no `handleError`, and root handlers and level restored.
- **`import main` and `import cli_interface.example_menu`:** both import cleanly.

### Dedup check (item 3)
Both pieces are in the tree, so this was not pending.
- `grep -n "def share" cli_interface/log_handler.py` finds line 212 (`LogAttachment.share`) and line 237 (the `_Lease` subclass).
- `grep -n "share()" cli_interface/app.py` finds line 440 (`return existing.share()`).
- The new script is `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp4/host_attach.py`. A host calls `attach_logging(app)` on root, then Worker Demo (`w`, Enter) runs, with the worker slowed for speed.
- Result: **PASS**.
  - During the run, root has exactly one `TUILogHandler`, and the host attachment is still active.
  - After the worker finishes, the host attachment is still active, its handler is still on root, and the root level is unchanged.
- The run emits a `UserWarning` from `attach_logging`, because `exclusive` and `level` are ignored on a dedup hit. That comes from WP-2 and is expected. The demo itself never hits this case, since `run()` never attaches root.

No cross-package requests. I made no deviations in this round.