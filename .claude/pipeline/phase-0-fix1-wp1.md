## WP-1 review round 1: fixes done

All four issues are fixed in `display.py` and `log_handler.py` only. Both files are updated on disk, and `uv run python -c "import cli_interface.display, cli_interface.log_handler, cli_interface.app"` imports cleanly. `verify.py` now runs 112 checks and all pass (84 before, plus 28 new).

### Changes per issue
**Issue 1 (major): lease handle.** `/Users/andrewmacleod/workspace/cli_interface/cli_interface/log_handler.py`
- New `LogAttachment.share() -> LogAttachment` returns `_Lease(self)`.
- New private `_Lease(LogAttachment)`, about 15 lines. It does not call `LogAttachment.__init__`, so it never touches the logger.
  - It copies `handler` and `logger` from the base.
  - `active` is `not self._released and self._base.active`.
  - `detach()` only sets `_released = True`, so a double detach is harmless and no lock is needed.
  - `__enter__` and `__exit__` are inherited, so `with` releases the lease through the overridden `detach()`.
- **Contract for WP-2:** call `existing.share()` on a dedup hit. The lease satisfies `isinstance(x, LogAttachment)`.

**Issue 2 (minor): `maxlen <= 0` no longer raises.** In `PanelInbox.put`, `maxlen` is now `max(1, ...)`.
- A cap of 0 or a negative value behaves as a cap of 1: only the newest record survives, `dropped` is counted exactly, and one notice is shown.
- I chose the clamp over `if self._dq and ...` because it makes the effective minimum capacity explicit.

**Issue 3 (minor): dead guard removed, comments added.**
- `_write` no longer checks `busy`; it only sets and resets it. The guard in `put` stays.
- Four one-line comments in `PanelInbox`, as requested:
  - `busy` drops records logged while the panel is writing.
  - The lock only guards state and is never held across UI calls.
  - The UI thread drains the backlog before its direct write, to keep FIFO order.
  - The emptiness check and the `_wake_pending` clear share one lock acquisition.

**Issue 4 (minor): `_styled` reuses `_as_text`.** `/Users/andrewmacleod/workspace/cli_interface/cli_interface/display.py`
- The `Text` branch is now `return _as_text(content, style)`.
- The plain path uses `_as_text(content, style)`. The `MarkupError` fallback uses it too.
- `str(content)` coercion is kept once, up front.

### Verification
Harness: `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/3ebbbff1-44e5-4ddc-af74-a25109ab5199/scratchpad/phase0/wp1/verify.py` (112/112 pass). It still uses a bare `App` with a stub `push_log`.

New lease checks:
- `isinstance(lease, LogAttachment)`, shared `handler` and `logger`, and exactly one `TUILogHandler` on the logger.
- A lease's `detach()` leaves the base active and its handler still on the logger.
- A double detach on a lease is harmless, and so is detaching it after the base has detached.
- A lease used with `with` works, and so does `with` plus a manual `detach()` inside.
- When the base detaches, `active` becomes False on every lease, and the logger's handlers and level are restored.
- 8 leases detached 3 times each concurrently leave the base active.
- The host-plus-scoped scenario: after the lease is detached, the host's attachment is still active and still on the logger.

New `maxlen` checks, for `maxlen` of 0, 1 and -5:
- Background and UI puts never raise.
- `dropped` equals 49 after 50 background puts.
- The newest record survives.
- Exactly one dropped notice appears.

### Deviation
- One small addition not in your spec: `_Lease.share()` returns `self._base.share()`. Without it, `lease.share()` would wrap the lease. Leasing a released lease would then report inactive even though the base is live. My first run caught this as a failing check.

### Notes for WP-2 and the Tester
- With the lease, the plan's "returns the same object" criterion becomes "returns a handle sharing the same `handler` and `logger`". There is exactly one `TUILogHandler` on the logger.
- I did not touch `app.py`. WP-2 owns returning `existing.share()` and warning about ignored `exclusive` and `level`.