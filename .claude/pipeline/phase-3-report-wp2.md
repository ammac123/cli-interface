WP-2 is done: FormScreen and ConfirmScreen are in place and `uv run pytest tests/test_forms.py` gives 45 passed. `ruff check` and `mypy` are clean on both files. `tests/test_menu_ui.py` and `tests/test_public_api.py` still pass (132 passed together with the new tests). I did not run the full suite, and nothing was run on Textual 0.80, because only 8.2.8 is installed.

**Files changed**
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py`:
  - **P3.1 (form UI):** adds `FormScreen`, with the plan's constructor and ids `form-field-<name>`, `form-error-<name>`, `form-submit` and `form-cancel`.
  - **P3.3 (dialog):** adds `ConfirmScreen`, with the plan's constructor and ids `confirm-yes` and `confirm-no`.
  - Existing classes are untouched. The module now imports `MISSING`, `ParamSpec`, `initial_text` and `validate_all` from `.params` at the top.
- `/Users/andrewmacleod/workspace/cli_interface/tests/test_forms.py` (new, 45 tests):
  - **Form UI (P3.1):** every acceptance bullet. That is one widget type per kind, masked secret field, and error handling that keeps the form open, shows the message inline and focuses the first bad field. A valid submit returns the typed dict, with int and None conversions, and Esc and the Cancel button give None. Enter in an input does not reach the host's `on_input_submitted`, including when the form has errors.
  - **Confirm dialog (P3.3):** initial focus on `confirm-no`; Enter gives False, `y` gives True, Esc and `n` give False.
  - **Literal text:** the whole `HOSTILE` matrix goes through titles, labels, help, validation errors, choice labels and button labels in both dialogs.
  - **Extra behaviour:** prefill from defaults and `initial`, optional versus required choice, empty choices, an empty form, a dotted field name, and a double dismiss producing a single result.

**Behaviour**
- Focus starts on the first field, or on the submit button if the form has no fields.
- Required choices have no blank option and start on their default, or on the first option if there is none.
- With empty choices the Select is allowed to be blank, so `validate_all` reports the error.
- A multi field's list follows the order of the choices.
- `initial` values go through `initial_text(replace(spec, default=value))`, so formatting stays in `params.py`.

**Deviations from the plan**
- Widget ids use a sanitized name: any character outside `[A-Za-z0-9_-]` becomes `_`. A dotted name like `db.host` would otherwise make an invalid Textual id. Normal identifier names are unchanged. WP-4 should look fields up by the spec name's sanitized form.
- I added a guard so a form or dialog answers only once (for example Enter pressed twice quickly).
- The Yes/No (or Cancel) buttons take whatever labels the caller passes; D5's "Yes and Cancel" is then the caller's choice.
- Textual's `MessagePump` already uses an attribute called `_closing`, so my first guard of that name hung screen removal. It is now `_answered`. Nothing for others to do.

**Requests for changes in files I don't own:** none. `params.py` from WP-1 exists and matched the contract: `MISSING`, `ParamSpec`, `initial_text` and `validate_all` imported and worked.

**Unverified on Textual 0.80**
- **Select sentinel:** in 8.2.8 the blank sentinel is `Select.NULL` and `Select.BLANK` is gone. I avoided naming either. A blank Select is created by leaving `value` out, and read through `select.is_blank()`, which I believe exists in 0.80.
- **Select options:** I pass them as `(Text(label), value)` tuples, with `allow_blank=` and `prompt=` keyword arguments.
- **SelectionList:** I pass `(Text, value, bool)` tuples and read `.selected`. The tests call `SelectionList.select(value)`, which I believe is in 0.80.
- **Other widgets:** `Switch(value=...)`, `Input(password=...)`, `Static(markup=False)`, `Label(markup=False)`, `Button(Text(...))` and `VerticalScroll` are all 0.80-era API, as far as I know.
- **Test helper:** the tests call the private `app.screen._compositor.render_strips()` to read all the text drawn on screen. If the lowest-direct run fails there, that helper is the first place to look.

**Test-writing note for later phases**
- A Textual Button ignores a second click within about 0.2s of the first, so a test that clicks the same button twice needs a short `pilot.pause(0.3)` in between.