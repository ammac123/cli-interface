WP-1 is implemented. `uv run pytest tests/test_params.py -q` gives 94 passed, 3 skipped (the 3 pydantic tests, since pydantic is not installed in the project env). With pydantic in an ephemeral env (`uv run --no-project --with pydantic ...`, no project files touched) all 97 pass. `ruff check` is clean on the three files and `mypy` is clean on `params.py` and `settings.py`. mypy is configured in pyproject and I used its settings.

## Files (all new, nothing else edited)
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/params.py`
  - Covers P3.1 and the schema part of C2-1.
  - `MISSING`, `Param`, `Secret`, `ParamSpec`, `Kind`, `ParamError`, `FormContext`.
  - `specs_from_signature(fn, *, strict)`, `specs_from_dataclass`, `specs_from_argparse(parser, meta)`.
  - `convert`, `validate_all`, `initial_text`, `call_with_ctx`, `pack`, `resolve_choices`, with the signatures and error strings from the plan.
  - Extra public helpers: `build_spec(name, annotation, default, meta)` and `dataclass_default(f)`.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/settings.py`
  - Covers P3.2 (model side) and C2-2 (`secret_values`).
  - `Field`, `Group`, `describe`, `get_value`, `set_value`, `reset_defaults`, `format_value`, `secret_values`.
- `/Users/andrewmacleod/workspace/cli_interface/tests/test_params.py`
  - Covers every WP-1 acceptance bullet.
  - Includes a subprocess test with textual and pydantic blocked in `sys.modules`, and a test that `import cli_interface` works with pydantic absent.

Neither module imports Textual or pydantic at module level. `specs_from_signature` imports `jobs._asks_context` lazily inside the function (read-only); `jobs` pulls in Textual transitively, so a module-level import would have broken the purity requirement.

## Decisions for WP-3/4
1. **`describe()` is flat and depth-first.**
   - Each `Group` precedes its children, and `Field.name` and `Group.name` are dotted paths from the root.
   - To build the tree, recurse on name prefixes. Do not call `describe` on nested objects, because secret and dotted-name matching depend on the root path.
   - `Field.spec.name` is the bare leaf name, so `form-field-<name>` ids contain no dots, which Textual ids cannot have.
2. **`describe` validates the model.** It raises `TypeError` for a class, a frozen dataclass (including a nested one), a frozen pydantic model, or anything that is not a dataclass or pydantic v2 instance. WP-4 can call it once at registration for the `TypeError` checks.
3. **`describe` skips fields.** It omits private (`_x`), pydantic-frozen, and unsupported-type fields (a `dict` field, for example). It does not raise, which differs from `specs_from_dataclass`, which raises.
4. **Secret fields and `get_value`.**
   - `SecretStr` fields come out as text with `secret=True`.
   - `get_value` unwraps secret wrappers.
   - `set_value` re-wraps them, including for `SecretStr | None` when the current value is `None`.
   - `Field.default` is also unwrapped.
5. **`validate`.** Only a raised `ValueError` matters. The return value is ignored, because a boolean-returning validator would otherwise replace the field's value with the boolean. Other exceptions propagate.
6. **`pack(specs, values, target)`.** `target` is a dataclass class, an `ArgumentParser` or `argparse.Namespace` (both give a `Namespace`). Anything else raises `TypeError`.
7. **Positional-only parameter with a default.** It is skipped, since it cannot be delivered as a keyword. The plan only specified the no-default case, which raises `ValueError`.
8. **Text fields.**
   - `""` is "empty" for text, but whitespace-only text is kept as typed.
   - A `None` raw value for text means "unspecified" and gives the default, or "Required" if there is none.
9. **Empty-input rule.** An optional field returns `None` even when it has a default (`int | None = 5` cleared gives `None`, as in D2).
10. **`format_value`.** It collapses newlines to a space and truncates to 40 characters including a trailing "…". `bool` formats as `True`/`False`, and `""` stays `""` (not "-").
11. **Annotation resolution.** `specs_from_signature` uses `inspect.signature(eval_str=True)`, then a per-parameter fallback that evals strings against the function's globals. I did not use a separate `get_type_hints` call for functions, because the result is the same. Locally defined names referenced in annotations under `from __future__ import annotations` cannot be resolved and count as unsupported.
12. **argparse specifics.**
    - Help and version actions are skipped.
    - `BooleanOptionalAction`, `nargs` as an integer, and `store_const` raise `ValueError`.
    - `nargs="*"` with a `None` default gives `[]`.
    - `%(default)s` style help is substituted.

## Notes for WP-4
- A signature like `def act(value)` used with `prompt=` will derive a `value` field. WP-4 should skip derivation for prompt items.
- Resolve choices, then pass `choices` to `validate_all`. A callable `spec.choices` with no resolved list is treated as empty ("No choices available").

## Requests for changes in files I don't own
- `/Users/andrewmacleod/workspace/cli_interface/scripts/check_dist.py`: `PACKAGE_MODULES` needs `"params"` and `"settings"` added, plus `"settings_menu"` once WP-4 lands. `tests/test_check_dist.py::test_the_allowlists_name_every_module_the_package_and_the_examples_actually_have` currently fails because of the two new modules. Nothing in WP-1..4's ownership lists covers this file.

## Not verified
- Textual 0.80 compatibility (not applicable to WP-1).
- Pydantic below the version resolved by uv today. I did not note the exact version, but 97 tests pass under it.
- Full-suite status: a full run timed out in the background and I did not read its result. Before that, my `-x` run stopped at the `check_dist` failure above, after 167 passed. WP-2/3 test files were excluded from my runs.