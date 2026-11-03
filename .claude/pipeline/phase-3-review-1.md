CHANGES_REQUESTED

Scope: I read all source modules and the diff, and skimmed the test names. I also ran FormScreen and ConfirmScreen under real Textual 0.80.0 (an existing scratchpad venv, using Pilot). The form with int, Literal, list[Literal], bool, a masked secret and an Optional Literal built, validated and returned the right dict, and the Confirm `y` key worked. I did not run the pytest suite on 0.80, because that venv has no pytest.

Overall the secret handling is sound. Details are under item 1 below.

## BLOCKER/MAJOR (fix this round)

1. [WP-2] MAJOR cli_interface/widgets.py:149 (`_safe_id`, used at :225) - The regex is `[^\w-]`, and `\w` is Unicode. A parameter named `größe` or `名前` gives the widget id `form-field-größe`. I confirmed on Textual 0.80 and 8.x that this raises `BadIdentifier` while the form composes, which crashes the app when the user picks the command. Two names can also collapse to the same id (`a.b` and `a_b`), which gives `DuplicateIds`. The WP-2 report says it sanitises with `[^A-Za-z0-9_-]`, but the code does not. Required fix: use the ASCII-only class `[^A-Za-z0-9_-]`, and make the ids unique. For example, on a collision append the field index, or always use the index as a suffix and look widgets up through `self._inputs`. Add a test with a non-ASCII name and a colliding pair.

2. [WP-4] MAJOR cli_interface/app.py:1041 (`_submit_command`, called from the `_on_form` and `_on_answer` callbacks on the UI thread) - `pack(item.params, values, target)` runs unguarded on the UI thread. A params dataclass whose `__post_init__` raises ValueError is a common validation pattern. Any exception from it escapes the screen callback and kills the whole TUI through Textual's fatal handler. It should be a normal error line. Required fix: wrap the pack step in `try/except Exception`. On failure log `Cannot run <label>: <msg>` as ERROR through `self.panel.log`, with the secrets redacted, and return without submitting. The secrets were already added at the top of `_submit_command`, so redaction works. Add a test using a dataclass with a raising `__post_init__`.

   Related, and I rate it MINOR: `FormScreen._submit` (via `params.py:634`) lets non-ValueError exceptions from a user `validate=` callable propagate and crash the app. This matches WP-1's stated choice. Preferably catch Exception there too and show it inline as "Invalid value".

## MINOR/NIT carry-forward

- [WP-1] The ParamError text from a user `validate` (params.py:636) is not masked for secret fields, although `convert_fn` errors are masked. The message appears only inline in the form, so it is not a leak. Mask it anyway for symmetry.
- [WP-1] A mutable default is aliased across calls. `convert` returns `spec.default` itself, so a dataclass `default_factory=list` is evaluated once and the same list object goes to every run. `ParamSpec.__repr__` also shows a secret's code-supplied default. For settings, a pydantic `default_factory` is called at describe time.
- [WP-1] `settings.secret_values` (settings.py:186) is dead in the product, because `settings_menu.secret_strings` re-implements it. Remove it or use it.
- [WP-1/2] A required Literal or Enum choice with no default preselects its first option, so it can never show "Required". This is a known, silent default. Document it or add a "(choose)" blank.
- [WP-4] Secrets only accumulate. A very short secret such as a PIN of "1" will garble every later job's output through `redact_text`. Consider a minimum length or a documented caveat.
- [WP-4] Settings edit and reset: `reset_defaults` can raise partway through (for example pydantic `validate_assignment`) before `changed` is returned, so there is no rollback in that case. Roll back from the `before` dict, not from `changed`.
- [WP-4] Entering a factory-backed settings group replaces `source.obj` and rebuilds the children while an edit job may still be running on the old object. The job closes over the old `obj`, so the UI could show a freshly built object before `save` finishes. It is benign but racy.
- [WP-4] `add_command("Settings/Foo")` can graft a child into a `_SettingsGroup`, and the next rebuild (`root.children[:] =`) deletes it. Refuse this in `_cmd_walk`.
- [WP-4] A busy race loses the typed form data: if a job starts while a form is open, `submit` only warns "Busy". It is acceptable. The dialogs are not auto-closed on quit, which is also fine.
- [WP-4] `choices` callables and `initial()` run on the UI thread (the plan allows this).
- [WP-4] The fatal-traceback test does not go through the form path. The code is safe because `_fatal_error` uses `show_locals=False`.
- Docs are still pending for the document step: README and CHANGELOG are not updated. The auto-form behaviour change for existing commands (a command with extra supported-type parameters now opens a form, and `params=False` opts out) is in the docstring and tested (test_params_app.py:293), but it must be in the CHANGELOG.

## Review focus results

1. Secrets.
   - **Panel, logs, errors, results:** these are covered. The form values of masked fields are added to the app redaction set before `jobs.submit`. `_collect_secrets` unions `spec.secrets` and the host provider at job launch. `TUILogHandler` redacts on all three paths. The panel line and the exception event are redacted.
   - **Reprs:** `JobSpec.kwargs` and `JobSpec.secrets` are `repr=False`. `Job.__repr__` shows no values. The nav-bar value of a secret item is masked without calling `current_value`.
   - **Prefill:** secrets are never prefilled. `initial_text` returns "" for a secret, and the settings edit leaf also passes `initial=None`.
   - **Empty submit and settings rollback:** an empty submit keeps the secret, because the optional field gives None and `edit` returns early. The settings rollback uses `get_value` and `set_value`, which unwrap and re-wrap SecretStr.
   - **Fatal output:** `_fatal_error` is unchanged and uses `show_locals=False`.
   - **Locks:** the shared secret set is locked correctly, and a raising source is skipped.
   - **Known limit:** a secret inside a returned json or table is not redacted (C2-4 deferred).
2. Correctness. bool-vs-int, Optional, Literal, Enum, list and nan/inf handling looked right. `_match_option` prefers an exact type match. `_execute_item` runs ensure_idle, then choices, then form, then confirm, then submit, as planned, and prompt items skip derivation. The `_SettingsGroup` rebuild on enter works, and a False return from `on_enter` or `enter()` stops navigation. The two crash defects above are the exceptions.
3. Conformance: see the deviation line below.
4. Backward compatibility.
   - **Existing add_command/MenuItem users and public API:** unaffected. `__all__` has 15 names.
   - **Imports:** `params` and `settings` import neither pydantic nor Textual at module level. The `jobs` import in `specs_from_signature` is lazy. `widgets` imports `params`, which is a stdlib-only module. `check_dist` is updated.
   - **Auto-derived forms:** a legacy function with a defaulted supported-type parameter now opens a form. This is the planned behaviour change and is tested. An unsupported-type parameter with a default is skipped, so those functions still run. A parameter of unsupported type without a default now fails at registration instead of at run time. That is acceptable, and it should be in the CHANGELOG.
5. Textual 0.80 compatibility. Confidence is high for the form and confirm widgets. I checked the 0.80 source: `Select.is_blank`, `Select.BLANK`, `allow_blank` and `prompt`, `SelectionList.select` and `.selected`, `Static` and `Label` `markup=`, `Input(password=)`, and `Button(label)` all exist. I also ran a live smoke test on 0.80.0 and it passed. I did not check `ModalScreen` generics or the CSS properties beyond that smoke test, and I did not run the suite.
6. Scope creep and dead code: only `settings.secret_values` (above). `build_spec` and `dataclass_default` are extra public helpers inside `params`, which is fine. C2-3 and X-1 were in scope.

## Executor deviations

- WP-1 flat dotted `describe()`, `describe` raising TypeError, secret `get_value` unwrapping and the positional-only skip: accept.
- WP-2 sanitised widget ids: accept the idea, reject the implementation (MAJOR 1). WP-2 `_answered` guard: accept.
- WP-3 `enter()` returns False on empty children: accept.
- WP-4 #1 `build_settings_group` returns (group, provider): accept.
- WP-4 #2 edit spec renamed `value`: accept.
- WP-4 #3 `on_enter` logs the warning itself: accept.
- WP-4 #4 attachment check for the logger once-guard: accept.
- WP-4 #5 `None` is non-strict and `True` is strict: accept.
- WP-4 #6 an ArgumentParser cannot mark secrets: accept as a documented limit, and add a `meta` path later.
- WP-4 #7 the settings provider reads the field names fixed at build time: accept. One side effect is that a factory model's secret names change only on re-enter.
- WP-4 #8 `_cmd_attach`: accept.
- Orchestrator's pydantic test-group addition: accept.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/params.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/settings_menu.py
- /Users/andrewmacleod/workspace/cli_interface/tests/test_params_app.py