Fixed review issue 1 ([WP-2] MAJOR, `_safe_id`). Not committed.

Files changed:
- cli_interface/widgets.py
- tests/test_forms.py (3 new tests appended)

Id scheme:
- `_safe_id` now uses `[^A-Za-z0-9_-]`, so non-ASCII characters become `_`.
- New `_field_keys(names)` runs once in `FormScreen.__init__` and stores `self._keys`. A name whose sanitised form equals itself keeps its key, so `form-field-<name>` and `form-error-<name>` are unchanged for normal names. Any other name gets `<safe>_<index>`, and a trailing `_` is added if that is already taken, so keys stay unique.
- `_compose_field` uses `self._keys[spec.name]`. Submit, focus-first-error and error display already go through the `self._inputs` and `self._errors` dicts keyed by the real field name, so they did not change.
- Example: `a.b` becomes `a_b_0` and `a_b` stays `a_b`. `größe` becomes `gr__e_0`.

Tests added in tests/test_forms.py:
- `test_a_non_ascii_field_name_composes_and_submits`: `größe` and `名前` compose with ASCII ids and submit their values.
- `test_colliding_field_names_each_keep_their_own_widget`: `a.b` and `a_b` get different ids and return their own values.
- `test_an_error_on_one_colliding_field_shows_under_that_field`: the error shows under `a.b` only, and nothing is submitted.
These new tests use `screen._inputs` and `screen._errors`, because the id-based helpers do not work for the new keys.

Results:
- `uv run pytest tests/test_forms.py tests/test_params_app.py -q`: 100 passed. No id problems in test_params_app.py.
- `uv run ruff check cli_interface/widgets.py tests/test_forms.py`: all checks passed.
- `uv run mypy cli_interface/widgets.py`: no issues.

I did not re-run the new tests against the old code to confirm they fail there. The collision and non-ASCII cases should fail on the old code, but that is unverified.