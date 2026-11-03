WP-3 is implemented and my own tests pass. The existing suite is green except `test_check_dist.py::test_the_allowlists_name_every_module_the_package_and_the_examples_actually_have`, which fails because of WP-1's new modules.

**Files changed (only the four I own)**
- `cli_interface/jobs.py`
  - `JobSpec` gains `kwargs: Mapping[str, Any]` (default `{}`) and `secrets: tuple[str, ...]` (default `()`), both `repr=False`. (C2-1 plumbing)
  - `_plan` now passes `{**bound_ctx_kwargs, **spec.kwargs}` to the call. `bind_call` is unchanged and `_asks_context` is not renamed. (C2-1 plumbing)
  - `_launch` takes its secrets from a new `_collect_secrets(spec)`: the union of `spec.value` (only when `spec.secret`), `spec.secrets`, and `getattr(host, "secret_values")()`. A provider that raises is skipped (logged at DEBUG), and empty or non-str values are dropped and de-duplicated. (C2-2)
- `cli_interface/log_handler.py`
  - `TUILogHandler.emit` redacts via `app.secret_values()` when the host has it, and a raising provider means no redaction. (C2-2)
  - It covers the default path (`msg` and `exc` through `redact_event`), the custom-formatter path, and the `push_log` fallback (`redact_text`). `events._REDACT_FIELDS["log"]` already covers `msg` and `exc`, so no handler-side field workaround was needed.
- `cli_interface/menu.py`
  - `ParamSpec` is imported under `TYPE_CHECKING` only.
  - `_CommandItem` gains `params: tuple = ()`, `deliver = "kwargs"` and `confirm: str | None = None`.
  - `make_command_item` gains matching optional `params`, `deliver` and `confirm` keywords.
  - New `_SettingsGroup(MenuItem)` with `on_enter: Callable[[], bool] | None = None`, and an `is_leaf` that is always False. (P3.3 and the settings plumbing)
  - `MenuState.enter()` returns False for an item with no children.
- `tests/test_job_params.py` (new, 22 tests): kwargs delivery for sync, async and positional-only `ctx`; no kwargs leaking between jobs; the `JobSpec` repr; redaction from `ctx.log`, print, return value and error text; the host provider, including a raising one; `TUILogHandler` on each path; and the menu model and `find_shortcut_conflicts`.

**Deviations from the plan**
- The plan only says to guard `enter()` against an empty-children edge case, so the behaviour is my choice. A non-leaf with empty children returns False and does not push a level, which is consistent with `prune()` dropping empty levels. WP-4's `_activate` should call `on_enter` first, then `enter()`, and treat a False from `enter()` as "nothing to open". If you want `enter()` to push an empty group, it is a one-line change.

**Requests for files I don't own**
- `scripts/check_dist.py` or the test's allowlists need `params` and `settings` added (WP-4 or the orchestrator). `settings.py` is not on disk yet, but the test's message already lists it.
- No changes needed to `tests/jobrig.py` or `events.py`. `FakeHost` works as is, and I set `secret_values` on the instance in tests.

**Verification**
- `tests/test_job_params.py`: 22 passed.
- `ruff check` is clean on my four files, and `mypy` on `jobs.py`, `log_handler.py` and `menu.py` is clean (it passes only now that `params.py` exists).
- Full suite run with `--ignore=tests/test_forms.py --ignore=tests/test_params.py` and the deselect you specified: 1762 passed, 1 failed (the `check_dist` test above), 1 deselected.
- `tests/test_forms.py` (WP-2, in progress) appears to hang on `test_escape_dismisses_with_none`, which stalled my first full-suite run for over 10 minutes. I did not touch it. I also could not kill that stalled pytest process (the permission check denied it), so it and a second verbose run (`scratchpad/wp3v.log`) may still be running.
- Not verified: the full suite including WP-1's and WP-2's tests, and the `app.py` and `commands.py` integration, which is WP-4's.