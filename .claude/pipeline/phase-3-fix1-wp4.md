WP-4 fix for `_submit_command` is done. Nothing committed.

Files changed:
- cli_interface/app.py
  - The `pack(...)` call in `_submit_command` is wrapped in `try/except Exception`. On failure it logs `Cannot run {item_label(item)}: {redact_text(str(exc), self.secret_values())}` at ERROR through `self.panel.log` and returns without calling `self.jobs.submit`.
  - Added `redact_text` to the existing `.events` import.
- tests/test_params_app.py
  - Added `test_a_params_dataclass_that_raises_logs_an_error_redacted_and_keeps_the_app_running`, parametrized over `ValueError` and `RuntimeError`. The dataclass has a `Secret()` field `token`, and its `__post_init__` raises with the typed secret and the user name in the message. The test drives the form through Pilot and asserts:
    - `app.is_running` and the form is closed
    - the panel contains `Cannot run Login: token *** is rejected for ann`
    - the secret is absent from the panel
    - the command never ran, no job is busy, and no `Executed` line appears

Results:
- `uv run pytest tests/test_params_app.py -q`: 54 passed in 20.61s.
- `uv run ruff check cli_interface/app.py tests/test_params_app.py`: all checks passed.
- `uv run mypy cli_interface/app.py`: no issues in 1 source file.

I did not run the new tests against the unfixed code, so I have not confirmed they fail without the change.

I did not touch widgets.py, tests/test_forms.py, or the non-ValueError `validate=` path in FormScreen (the MINOR item in the review), since that is outside the listed scope.