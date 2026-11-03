WP-4 is done. The full suite gives 1957 passed with 1 deselected, run after the last edit (211 s). The deselected test is `tests/test_packaging.py::test_the_dependency_groups_separate_test_lint_and_dev`, which fails because of the orchestrator's pydantic addition to the `test` group; it needs a one-line fix (see requests). `ruff` is clean, and `mypy cli_interface examples scripts` (the CI invocation) is clean. Textual 0.80 was not run.

## Files changed
- `cli_interface/app.py`
- `cli_interface/commands.py`
- `cli_interface/settings_menu.py` (new)
- `cli_interface/__init__.py`
- `scripts/check_dist.py`: added `params`, `settings` and `settings_menu` to `PACKAGE_MODULES`. `tests/test_check_dist.py` needed no change.
- `tests/test_public_api.py`: `PUBLIC_NAMES` gains `Param` and `Secret`; the "thirteen names" test is now "fifteen"; the "original eleven" test excludes the two new names.
- `tests/test_params_app.py` (new, 52 tests, all through Pilot)
- `tests/test_commands.py`: no edit needed. The X-1 test now passes.

## Scope mapping
- **P3.1, C2-1**
  - `add_command` and `command` take `params=` and `confirm=`.
  - `params=None` derives from the signature in non-strict mode, and `True` is strict. `False` is legacy, and a dataclass class, an `ArgumentParser` or a sequence of specs is also accepted.
  - `_execute_item` runs `ensure_idle`, then choices, then the form, then the confirm, then `jobs.submit`. The job gets `kwargs` and `secrets` on `JobSpec`.
  - Dataclass and parser delivery use a new `_FormCommand` subclass in `app.py`, which holds `pack_target`, `pack_param`, `initial` and `job_label`.
  - Registration fails early with `ValueError` naming the command, for example an unsupported parameter without a default, a positional-only parameter, no single receiving parameter, a field that is not a parameter, or a required parameter with no field.
  - Choices that raise log `Cannot open form: <msg>` and open nothing.
- **P3.3**
  - `confirm=` accepts `True` ("Run <label>?") or a str shown literally; any other type raises `TypeError`.
  - The dialog uses `ConfirmScreen` with Yes and Cancel buttons and focus on Cancel. It opens after the form, and cancelling is silent.
- **P3.2**
  - `App.settings(path, model, *, save, secret, reset, key)` is implemented in `commands.py`, with the tree built in `settings_menu.py`. It has one leaf per field, a submenu per nested model and a "Reset to defaults" leaf with a confirm.
  - A callable model is called on entering the group. If it raises, or returns something that is not a model, the app logs `Settings unavailable: <msg>` and does not navigate.
  - Edit forms are prefilled with the current value through `_FormCommand.initial`. A secret field is not prefilled, and an empty submit keeps the value.
  - `save(ctx)` runs on the job thread after an edit or reset and is skipped if nothing changed. If it raises, the change is rolled back; reset is rolled back the same way.
  - `_activate` calls `on_enter` before `MenuState.enter()`, and returns early if `enter()` returns False.
- **C2-2**
  - `CLIApp.add_secret`, `add_secret_source` and `secret_values` exist and are thread-safe.
  - A form submit adds the values of masked fields (including list values and non-str ones) to the redaction set.
  - `settings()` registers a provider only after attaching succeeds.
  - Redaction is tested in the panel, `ctx.log`, `print`, error text and a captured logger record, including one logged after the job ends.
- **C2-3**
  - `App(capture_loggers=..., capture_level=...)` is validated up front. A bare str raises `TypeError`, and an unknown level raises `ValueError`.
  - Loggers attach in the new `CLIApp._after_mount()` hook, which `App` overrides, and detach on exit.
- **X-1**: `commands._first_doc_line` excludes `functools.partial` and `partialmethod`.
- **Public API**: `__all__` now has 15 names (`Param`, `Secret` added).

## Deviations from the plan or wave-1 contracts
1. `build_settings_group` returns `(group, secret_provider)` rather than just the group, so the provider is registered only after the attach succeeds.
2. An edit form's spec is renamed to `value`, so the field id is `form-field-value`. This avoids clashing with `ctx` and with dotted names. The job label is "Set <field label>", as D4 intended. The reset job keeps the label "Reset to defaults".
3. `on_enter` itself logs the `Settings unavailable: <msg>` warning and returns False; `_activate` only handles an unexpected raise.
4. The `capture_loggers` once-guard checks for an active attachment on that logger instead of using a flag. This survives a re-run and still stops a second `on_mount` from attaching twice.
5. `params=None` and the decorator are non-strict; only `params=True` is strict. I read "strict=True for explicit/decorator use" that way.
6. `params=<ArgumentParser>` has no way to mark secrets, because the public API has no `meta` argument.
7. A settings secret provider reads only the secret field names found at build time, so it avoids calling `describe` for every log record.
8. `_attach` is named `_cmd_attach`, because Textual's `MessagePump` already has an `_attach`.

## Observations and caveats
- WP-2 behaviour: a required `Literal` or Enum `Select` with no default pre-selects its first option, so it can never show "Required". My test asserts `""` for that field.
- Fatal errors: I did not change `_fatal_error`. It already passes `show_locals=False`, so form values are covered by that, not by a test that goes through the form path. `test_the_fatal_traceback_does_not_print_form_values` only shows the handler hides a local holding a password; it does not exercise the form path.
- Redaction applies to text fields only. A secret inside a returned dict or table is not redacted (the C2-4 limit).
- The `examples/` commands take only `ctx` or no arguments, so they are unaffected by auto-derived forms.

## Requests for files I don't own
- `tests/test_packaging.py`: `test_the_dependency_groups_separate_test_lint_and_dev` must expect `{"pytest", "pytest-asyncio", "pydantic"}` for `groups["test"]`. It is failing now because of the orchestrator's pyproject change.

## Unverified
- Textual 0.80 was not run.
- Stale pid 67596 was not touched. I tried `pkill` on my own mistaken background run, but it was denied, and that run finished harmlessly.