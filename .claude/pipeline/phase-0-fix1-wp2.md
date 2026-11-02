## WP-2 review round 1 fixes: all four issues are done in `/Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py`

`app.py` is the only file I edited, and no git state was changed. `LogAttachment.share()` was already in `log_handler.py` (it returns a `_Lease`) when I wired issue 1, so issue 1 is verified end to end.

### Changes per issue
- **Issue 5.** The line in `on_mount` now reads `_ = self.panel  # prime the cached panel; query_one fails once a modal is active`.
- **Issue 6.** The `attach_logging` docstring now says "Call on the UI thread while the app is running."
- **Issue 7.** `cmd.isdigit()` is now `cmd.isdecimal()` in `on_input_submitted`. Typing `²` plus Enter no longer reaches `int(cmd)`.
- **Issue 1.**
  - On a dedup hit, `attach_logging` now returns `existing.share()`.
  - If `exclusive` is true or `level is not None`, it first calls `warnings.warn("attach_logging: 'exclusive' and 'level' were ignored because an attachment already exists for this logger", UserWarning, stacklevel=2)`.
  - The docstring gains one sentence: "If the logger is already attached, returns a handle sharing it (detaching that handle leaves the attachment in place) and warns if exclusive or level was passed."
  - `_attachments` only ever holds real attachments, never leases. `on_unmount` is unchanged.

### Verification
Scratch dir: `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp2/`.

`verify.py` now has 77 checks and all pass (`FAILS: []`).
- **Dedup check, updated.**
  - The second `attach_logging` returns a distinct handle, `a2 is not a1` and `isinstance(a2, type(a1))`.
  - It shares `handler` and `logger` with the first, and exactly one `TUILogHandler` is on the logger.
  - A call with `exclusive` or `level` emits exactly one `UserWarning`, and the warning's filename is the caller's.
  - A plain second call emits no warning.
  - Detaching a lease leaves the owner active and its handler attached. A second lease `detach()` is idempotent.
  - Once the owner detaches, the lease's `active` is False.
  - The original F3 check still passes: after the owner's `detach()`, the host handlers and level are restored.
- **New t4 scenario.**
  - Setup: root has a sentinel host StreamHandler at WARNING. `host = attach_logging(app)`, then `scoped = attach_logging(app, exclusive=True, level=logging.DEBUG)`.
  - A `UserWarning` mentioning "ignored" fires, and `scoped` is a distinct handle sharing the host's handler.
  - There is exactly one `TUILogHandler` on root. The host StreamHandler is kept and the level stays at WARNING, so the arguments really were ignored.
  - After `scoped.detach()`, `host.active` is True and a later `logging.getLogger("t4x").warning(...)` still reaches the panel.
  - `with attach_logging(app) as lease: lease.detach()` leaves the host active.
  - At app exit root's handlers and level equal the sentinel state.
- **`²` check.** `²` plus Enter leaves the app running with `return_code None`. The panel shows `Unknown command: '²'`, and `1` plus Enter still activates by position.

Probes, re-run after the fixes:
- **exp1** (scratch copy with `press("a", "enter")`): main-thread, action and background-thread records are all shown. There is no `handleError` output and no handlers are left on the logger. The background log after exit is silent.
- **exp2** (run from scratch): 396 records were emitted after exit, with 0 logging-error lines and 0 handlers left.
- **exp7:**
  - 300 records: about 255k rec/s producer, 300 `write` calls, 300 lines held.
  - Append mode: 301 writes.
  - 2000 records: 2000 writes.
  - The baseline was 135 rec/s and 20,103 writes for 300 records.
- **typed_markup_test:** `return_code = None`.
- **edge_test:**
  - `crash_case` leaves the app running with `return_code` None.
  - `main_thread_log` shows its record, and the post-exit log is silent with no handlers left.
- **modal check:** both records appear after prompt submit and cancel. The inbox stays `open` and the attachment stays active.
- **smoke_test:** 2 FAILs, the same two expected ones. Single-key `v` no longer navigates, and the consumer-logger check fails because the worker's attachment is now scoped. The worker demo, restore at exit and clean exit pass.

Nothing is unverified. There are no cross-package requests.