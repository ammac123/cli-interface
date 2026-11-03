All three failures are CODE BUGS, none is a TEST BUG. I read the Tester's notes and checked A and C against the source and the installed Textual copies. I did not open tests/test_phase3_e2e.py itself. C comes from reading the bindings, not from running anything. A was run on Textual 0.80.0 and 8.2.8, and the results were identical.

**(A) Select default not shown: CODE BUG [WP-2], MAJOR.**
- **Location:** `cli_interface/widgets.py` ~267-271, `FormScreen._make_input`.
- **Cause:** `select.value = value` is assigned before mount, so the `SelectCurrent` label never updates. The form shows the "Select" prompt while the default is silently submitted.
- **Fix:** pass the value to the constructor, but only when it matches an option. In a probe on 0.80.0 and 8.2.8:
  - `Select(opts, allow_blank=False, value='b')` mounts and shows "Beta".
  - `allow_blank=True, value='b'` also shows "Beta".
  - Omitting `value` gives a blank Select when blank is allowed, and the first option when it is not.
  - A value that is not among the choices raises `InvalidSelectValueError` at mount.
- **Implementation:** build `kw = {}`. Look up `match = next((v for v, _ in options if v is not MISSING and v == value), <none>)`. If a match is found, set `kw["value"] = match` (the option's own object). Call `Select(items, allow_blank=allow_blank, prompt=..., id=..., **kw)`. Then delete the `select.value = value` assignment.
- **Cases:** a `None` or `MISSING` default, or a default that is not among the choices, leaves `value` unset. That gives a blank Select when `allow_blank` is true, otherwise the first option, which is the existing behaviour. Never name `Select.BLANK` or `Select.NULL`.

**(B) `validate=` raising a non-ValueError: CODE BUG [WP-1], MAJOR (low effort).**
- **Location:** `cli_interface/params.py:632-636`.
- **Fix:** catch `Exception`, not just `ValueError`:
  - `except ValueError as exc: msg = str(exc) or "Invalid value"`
  - `except Exception: msg = "Invalid value"`
  - then `raise ParamError("Invalid value" if spec.secret else msg) from None`
- **Masking:** the message must be masked for secret fields, for both branches. The validator sees the raw value and its message may quote it. Use `from None`, and do not log the exception message.
- **Existing behaviour:** non-secret ValueError messages stay as they are. Add a test for a secret field with a validator whose message contains the value.

**(C) Ctrl+C under a modal: not a regression, MINOR carry-forward.**
- `PromptScreen`, `FormScreen` and `ConfirmScreen` bind only Esc (and n/y on the confirm). `ctrl+c` is bound only on `CLIApp` (`app.py:259`).
- Textual does not pass app-level non-priority bindings through a modal screen, so `PromptScreen` behaves the same. I expect that, but I did not run a `PromptScreen` check. Ctrl+Q still quits.
- No fix is needed this round. If wanted later, add `Binding("ctrl+c", "app.quit")` or make the app binding `priority=True`; that is Phase 4 or documentation territory.