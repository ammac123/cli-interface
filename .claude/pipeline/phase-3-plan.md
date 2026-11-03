# Phase 3 plan (lean, 4 WPs)

Baseline 646c781, branch phase-3. Textual locked 8.2.8, pyproject range is >=0.80,<9. Python 3.14.7 is used here; the project supports >=3.13.

## 1. Design decisions

**D1. Param schema.** It lives in the new `cli_interface/params.py`, which uses only the stdlib. It never imports pydantic or Textual.
```python
MISSING: Final            # sentinel for "no default"
@dataclass(frozen=True) class Param: label:str|None=None; help:str=""; choices:Iterable|Callable|None=None; secret:bool=False; validate:Callable[[Any],Any]|None=None; min:float|None=None; max:float|None=None
@dataclass(frozen=True) class Secret(Param): secret:bool=True      # use as Annotated[str, Secret()]
Kind = Literal["text","int","float","bool","choice","multi","path","list"]
@dataclass(frozen=True) class ParamSpec:
    name:str; kind:Kind; label:str; help:str=""; default:Any=MISSING; optional:bool=False
    choices:Iterable|Callable|None=None; item_kind:Kind|None=None   # item_kind is for kind="list"
    secret:bool=False; min:float|None=None; max:float|None=None
    validate:Callable[[Any],Any]|None=None; enum_type:type|None=None; convert_fn:Callable[[str],Any]|None=None  # convert_fn = argparse type=
    @property required -> default is MISSING and not optional
class ParamError(ValueError)
class FormContext: state: SimpleNamespace          # all that choices=/model= callables see before a job exists
```
- Derivation functions:
  - `specs_from_signature(fn, *, strict: bool) -> list[ParamSpec]`
  - `specs_from_dataclass(cls) -> list[ParamSpec]`
  - `specs_from_argparse(parser, meta: Mapping[str, Param] | None = None) -> list[ParamSpec]`
- Signature rules:
  - Use `inspect.signature(fn, eval_str=True)` plus `get_type_hints(include_extras=True)`, falling back to the raw annotation.
  - Skip any parameter for which `jobs._asks_context` is true (read-only import; WP-3 must not rename it), and skip `*args` and `**kwargs`.
  - Unwrap `Annotated`; the first `Param` in the extras supplies the metadata.
  - `T | None` and `Optional[T]` set `optional=True`.
  - Type mapping:
    - `str` -> text; `int` -> int; `float` -> float; `Path` -> path.
    - `bool` -> bool (a Switch). An optional bool becomes a choice with Yes, No and none.
    - `Literal[...]` and `Enum` -> choice. An Enum's value is the member and its label is the name.
    - `list[T]` -> list; with `choices=` it becomes multi.
    - A parameter with no annotation takes the type of its default, otherwise text.
  - Positional-only without a default raises `ValueError`.
- Unsupported types:
  - `strict=False` (auto mode for `add_command`) skips a parameter that has a default, so legacy functions keep running with their defaults.
  - A parameter with an unsupported type and no default raises `ValueError` naming the command and the parameter.
- Dataclass fields use `get_type_hints`, `default` / `default_factory`, and `Param` from `Annotated` or `field(metadata={"param": Param(...)})`. A nested dataclass field raises `ValueError`; nesting is `app.settings` territory.
- argparse reads `parser._actions`:
  - store, store_true and store_false map to text, bool and so on; `type=int|float|Path` is recognised.
  - Any other `type=` callable becomes `convert_fn`.
  - `choices` becomes choice; `nargs` of `+` or `*` becomes list; `required`, `default` and `help` carry over; `dest` is the name.
  - Subparsers, count, append and custom actions raise `ValueError`.
  - Secrets come from `meta`.
- `choices=` is an iterable of values or `(value, label)` pairs, or a callable with 0 or 1 positional arguments. The callable receives a `FormContext`.
  - `resolve_choices(spec, fctx) -> list[tuple[Any, str]]` is called by the app on the UI thread when the form opens.
  - An exception there logs `Cannot open form: <msg>` and opens nothing.
  - Empty choices on a required field give the field error "No choices available".

**D2. Validation and conversion.** Pure functions in `params.py`:
```python
convert(spec, raw, choices=None) -> Any                 # raises ParamError(msg)
validate_all(specs, raw: Mapping[str,Any], choices: Mapping[str,Sequence[tuple[Any,str]]]|None=None) -> tuple[dict[str,Any], dict[str,str]]  # (values, errors); all errors are collected
initial_text(spec) -> str                                # prefill: "" for MISSING, None and secrets
call_with_ctx(fn, ctx)                                   # calls fn() or fn(ctx) by arity
pack(specs, values, target) -> Any                       # dataclass instance or argparse.Namespace
```
- Raw types per kind:
  - text, int, float, path and list: `str`.
  - bool: `bool`.
  - choice: the option value, or `None` for blank.
  - multi: a list of option values.
- Empty-input rules:
  - Empty means `None` if the field is optional (`int | None`, so clearing the field unsets it).
  - Otherwise, a text field accepts `""` unless it has no default (then "Required").
  - Any other kind falls back to the default, and gives "Required" if there is none.
- Number rules:
  - int uses `int(raw.strip())`; error "Enter a whole number".
  - float must be finite (nan and inf are rejected); error "Enter a number".
  - `min` and `max` give "Must be at least N" and "Must be at most N".
- Path rules: `Path(raw)`, with no `~` expansion.
- List rules: split on commas, strip, drop empties, convert each item with `item_kind`.
- Choice rules: the value must be one of the choices, otherwise "Choose one of: a, b".
- `validate` may raise `ValueError(msg)`, which becomes the field error. Cross-field validation is out of scope.

**D3. Forms.**
- Widgets live in `widgets.py`:
```python
class FormScreen(ModalScreen[dict[str, Any] | None]):
    def __init__(self, title: str, specs: Sequence[ParamSpec], *, choices: Mapping[str, Sequence[tuple[Any, str]]] | None = None,
                 initial: Mapping[str, Any] | None = None, submit_label: str = "Run")
class ConfirmScreen(ModalScreen[bool]):
    def __init__(self, title: str, message: str, *, yes: str = "Yes", no: str = "No")
```
- Widget ids are fixed so tests can rely on them:
  - `form-field-<name>`, `form-error-<name>`, `form-submit`, `form-cancel`.
  - `confirm-yes`, `confirm-no`.
- Widget per kind:
  - text, int, float, path and list -> `Input(password=spec.secret)`.
  - bool -> `Switch`.
  - choice -> `Select` (blank allowed only if optional).
  - multi -> `SelectionList`.
- Each field has a Label (label plus help) and an inline error `Static`. Text is shown literally (`markup=False`).
- Submitting:
  - Enter in an Input, or the Submit button, calls `validate_all`.
  - Errors show inline, focus goes to the first bad field, and the form stays open.
  - On success it calls `dismiss(values)`.
- Cancelling: Esc or the Cancel button calls `dismiss(None)`. Nothing runs and nothing is logged, like `PromptScreen`.
- Input messages need `event.stop()` so that `CLIApp.on_input_submitted` is not hit.
- `ConfirmScreen`: the **No** button has initial focus. Esc and `n` give False, `y` gives True, and Enter activates the focused button.
- Wiring to the runner (`app.py`, in `_execute_item`):
  1. `jobs.ensure_idle()`.
  2. If the item has params: resolve choices, then push `FormScreen`.
  3. If it has `confirm`: push `ConfirmScreen`. The order is form, then confirm.
  4. Call `self.jobs.submit(replace(spec_from_item(item, None, ()), kwargs=values, secrets=<secret values>))`.
- Delivery of the validated values to the action:
  - kwargs by default, merged after the `ctx` binding.
  - With `params=<dataclass class>`, one instance goes to the sole non-Context parameter.
  - With `params=<ArgumentParser>`, an `argparse.Namespace` goes to the sole non-Context parameter.
  - A mismatch with the function's signature raises `ValueError` at registration.
- Submit still honours the existing Busy rule, because `submit()` re-checks.
- Commands without params and without confirm take the unchanged path.

**D4. `app.settings`.**
```python
App.settings(path: str, model: Any | Callable[[FormContext], Any], *, save: Callable | None = None,
             secret: Iterable[str] = (), reset: bool = True, key: str = "") -> None
```
- `model` is a dataclass instance or a pydantic v2 `BaseModel` instance. A callable is called with a `FormContext` and returns the instance.
- Passing a class raises `TypeError`. Frozen dataclasses raise `TypeError`.
- Pydantic is duck-typed (`model_fields` and `model_validate` present); it is never imported.
- Structure:
  - It registers a `_SettingsGroup` at `path`, using the same path walk and shortcut check as `add_command`.
  - Children are one leaf per scalar field, one submenu per nested model, and a "Reset to defaults" leaf.
  - A group is populated at registration if the model is an instance, and is (re)built on entering when the model is a callable.
  - `is_leaf` is always False for the group.
  - `_activate` calls `item.on_enter()` before `MenuState.enter()`. If it returns False, a WARNING `Settings unavailable: <msg>` is logged and navigation stops.
- Live values:
  - Each leaf is a `_CommandItem` with `current_value=lambda: format_value(get(resolve(), name))`.
  - That reuses the existing nav-bar `(value)` display.
  - The leaf has `secret=True` for secret fields, so the display shows `••••` and the callable is never called.
- Editing a field:
  - Opening a leaf opens a one-field `FormScreen` (`params=(spec,)`) through the same machinery.
  - For a secret field the spec is `optional=True` with no prefill, and an empty submit (`None`) means "unchanged".
  - The action runs as a job named "Set <field>" on a thread. It sets the attribute, then calls `save(ctx)`.
- Save semantics:
  - `save` is called after every successful edit or reset, on the job thread, with the real `Context`.
  - It is not called if nothing changed.
  - If `save` raises, the in-memory value is rolled back and the job ends with an ERROR.
  - Its return value is ignored.
  - `save=None` means in-memory only.
- Reset:
  - The leaf has `confirm="Reset all <label> settings to their defaults?"`.
  - The job resets recursively and in place (nested objects are mutated, not replaced).
  - Fields with no default are skipped.
  - It then saves once, if anything changed.
- Pydantic details:
  - Default comes from `field.get_default(call_default_factory=True)`.
  - Help comes from `description`.
  - `Param` is found in `metadata` or `json_schema_extra["param"]`.
  - `SecretStr` is handled as secret text (read with `get_secret_value()`, written by re-wrapping).
  - A validation error raised by `setattr` just surfaces as the job's ERROR line.
- `settings.py` is pure. Contract:
```python
@dataclass(frozen=True) class Field: name:str; spec:ParamSpec; secret:bool; default:Any   # default may be MISSING
@dataclass(frozen=True) class Group: name:str; label:str
describe(obj, secret: Collection[str]) -> list[Field | Group]   # secret matches a bare or dotted name, or Param.secret
get_value(obj, name) -> Any
set_value(obj, name, value) -> None
reset_defaults(obj, secret: Collection[str]) -> list[str]       # dotted names that changed
format_value(value) -> str                                      # None -> "-", Enum -> name, list -> "a, b", truncated at 40 chars
secret_values(obj, secret: Collection[str]) -> list[str]        # recursive, non-empty strings only
```
- `app.settings` is built in the new `settings_menu.py` (`build_settings_group(app, path_segments, model, save, secret, reset, key) -> _SettingsGroup`).

**D5. `confirm=`.**
- The `add_command` and `command` keyword is `confirm: bool | str = False`.
  - `True` shows "Run <label>?".
  - A str is shown literally.
  - Any other type raises `TypeError`.
- The dialog is `ConfirmScreen` with the title "Confirm" and the buttons Yes and Cancel. Focus starts on Cancel.
- It opens after `ensure_idle()` and, when there is a form, after the form.
- Cancelling is silent and no job starts.
- The stored form is `_CommandItem.confirm: str | None`.

**D6. Secrets (C2-2).**
- `CLIApp` gets a shared set:
  - `add_secret(value: str) -> None`
  - `add_secret_source(fn: Callable[[], Iterable[str]]) -> None`
  - `secret_values() -> tuple[str, ...]` (the union; a provider that raises is skipped).
- Registration:
  - A form submit calls `add_secret` for the value of every secret field. That makes the redaction set shared and sticky for the session.
  - `settings()` registers a provider that returns the current values of secret fields.
- `JobManager._launch` builds `job._secrets` as the union of `spec.value`, `spec.secrets` and `getattr(host, "secret_values", lambda: ())()`.
  - `JobSpec` gains `kwargs: Mapping[str, Any] = field(default_factory=dict, repr=False)` and `secrets: tuple[str, ...] = field(default=(), repr=False)`.
  - Redaction therefore covers `ctx.log`, the panel, the print capture, return values and error text, through the existing `JobEmitter`.
- `TUILogHandler.emit` redacts with `app.secret_values()` when the host has that method. Loggers attached with `attach_logging` or `capture_loggers` are therefore redacted too.
- The kwargs are bound by `_plan`: `{**ctx_kwargs, **spec.kwargs}`.
- Known limits:
  - The redaction set is a snapshot taken at launch.
  - A secret split across table cells or lines is not caught.
  - A thread spawned by a secret job is not redacted.
  - Writes to `app.panel` outside any job are not redacted.

**D7. C2-3, C2-4, X-1.**
- C2-3 is included: `App(name, *, capture_loggers: Sequence[str | logging.Logger] = (), capture_level: int | str | None = None, ...)`.
  - `CLIApp.on_mount` ends by calling a no-op `self._after_mount()`, which `App` overrides.
  - The override runs `attach_logging(self, logger, level=capture_level)` once per logger and is guarded by a once-flag.
  - Detach already happens on exit.
- C2-4 is excluded. It needs an `obj` slot on the json and table events and touches the events, display and redaction paths. Carry it to Phase 4.
- X-1: in `commands._first_doc_line`, use `inspect.isroutine(fn) and not isinstance(fn, functools.partial | functools.partialmethod)`. The existing test then passes on 3.14.
- Also carried forward: the self-exit "Stopping X" WARNING and `PanelInbox._deliver` write-error logging. They are not in scope.

**D8. API and compatibility.**
- `__all__` grows from 13 to 15 names: add `Param` and `Secret`. `FormScreen`, `ConfirmScreen`, `ParamSpec` and `FormContext` stay internal. `tests/test_public_api.py::PUBLIC_NAMES` must be updated.
- `add_command` and `command` gain `params: Sequence[ParamSpec] | type | argparse.ArgumentParser | bool | None = None` (None = derive from the signature, False = legacy) and `confirm`. Defaults leave existing calls unchanged.
- `MenuItem` is untouched. `_CommandItem` gains `params`, `deliver` and `confirm`. `make_command_item` gains the matching keywords, all optional.
- `JobSpec` gains defaulted fields, and `bind_call` is unchanged.
- pyproject: add `pydantic>=2` to the `test` dependency group only (the orchestrator refreshes `uv.lock`). It is not a runtime dependency and gets no extra.
- Behaviour change to flag: an existing command whose function has extra supported-type parameters now opens a form instead of running with its defaults. `params=False` opts out.

## 2. Work packages

File ownership is disjoint; I checked each file appears in exactly one WP.

**WP-1: schema, conversion, model introspection (pure).**
- Owns:
  - `cli_interface/params.py` (new)
  - `cli_interface/settings.py` (new)
  - `tests/test_params.py` (new, covers both modules)
- Provides: D1, D2 and D4's `settings.py` contract exactly as written above.
- Consumes: `jobs._asks_context` (read-only).
- Acceptance:
  - `import cli_interface.params` and `import cli_interface.settings` work with pydantic absent. A test blocks the import via `sys.modules` and asserts both modules still import.
  - A signature test matrix covers str, int, float, bool, Path, Enum, Literal, Optional, `list[str]`, `list[Literal]`, Annotated plus Param, Secret, default inference, unsupported-with-default skipped in non-strict mode, unsupported-without-default raising, and positional-only.
  - Dataclass and argparse derivations are tested, including the unsupported argparse actions.
  - `convert` covers empty input for each kind, `int | None` empty giving None, nan/inf, min/max, `validate` raising, and Literal int values.
  - `validate_all` returns all errors at once.
  - A choices callable is tested with 0 and 1 arguments.
  - Settings introspection is tested for dataclass and (via `importorskip`) pydantic v2, including nesting, reset recursion in place, fields without defaults skipped, frozen dataclass `TypeError`, class-instead-of-instance `TypeError`, secret by bare and dotted name, SecretStr, and `format_value`.
- Scope: P3.1 (schema, conversion), P3.2 (model side), C2-1 (schema part), C2-2 (`secret_values`).
- Wave 1.

**WP-2: form and confirm widgets.**
- Owns: `cli_interface/widgets.py` (FormScreen and ConfirmScreen added; existing classes unchanged) and `tests/test_forms.py` (new).
- Provides: the two screen classes and ids from D3.
- Consumes: `ParamSpec`, `MISSING` and `validate_all` from `params.py`.
- Tests mount each screen in a minimal Textual host app under Pilot (`App.run_test`).
- Acceptance:
  - One widget of the right type renders per kind: Input, Switch, Select, SelectionList.
  - A secret field has `password=True`.
  - Submitting with errors keeps the screen open, shows the message in `form-error-<name>`, and focuses the first bad field.
  - A valid submit dismisses with the typed dict, including `int` and `None` conversions.
  - Esc dismisses with None.
  - Enter in an Input does not reach the host app's `on_input_submitted` (assert that).
  - ConfirmScreen: initial focus is `confirm-no`; Enter returns False; `y` returns True; Esc returns False.
  - Text is literal: a label like `[/x]` renders without a MarkupError.
  - Textual API calls (`Select.BLANK`, `allow_blank`, `SelectionList`) work on 8.2.8 and on the lowest supported 0.80. Verify against the 0.80 source or docs and use `getattr` fallbacks where they differ; the orchestrator runs the lowest-direct environment at the end.
- Scope: P3.1 (form UI), P3.3 (dialog).
- Wave 1. It codes against the WP-1 contract. Its tests need `params.py` to exist, so either start it after WP-1 or run its tests once WP-1 has landed.

**WP-3: runner and logging plumbing, and menu model.**
- Owns:
  - `cli_interface/jobs.py`
  - `cli_interface/log_handler.py`
  - `cli_interface/menu.py`
  - `tests/test_job_params.py` (new)
- Changes:
  - `JobSpec.kwargs` and `JobSpec.secrets` (both `repr=False`).
  - `_plan` merges `spec.kwargs` into the call kwargs.
  - `_launch` unions the secrets, including `getattr(host, "secret_values", ...)`.
  - `TUILogHandler.emit` redacts via `app.secret_values()` when present, covering message and exc text. Check the `log` fields in `events._REDACT_FIELDS`; `events.py` is not owned, so redact in the handler itself if the fields fall short.
  - `menu.py`: `_CommandItem` gains `params: tuple = ()`, `deliver: Literal["kwargs","dataclass","namespace"] = "kwargs"` and `confirm: str | None = None`. `make_command_item` gains matching optional keywords. Add `_SettingsGroup(MenuItem)` with `on_enter: Callable[[], bool] | None = None` and `is_leaf` always False.
  - `ParamSpec` is imported only under `TYPE_CHECKING`.
- Provides: the contracts above, which WP-4 uses.
- Acceptance:
  - A job with `kwargs={"n": 3}` receives `n=3` alongside `ctx`, for both an async and a sync function.
  - Positional-only parameters are not broken.
  - A secret in `spec.secrets` is redacted from `ctx.log`, print, a return value and an error message.
  - A secret returned by a host's `secret_values()` is redacted.
  - `FakeHost` in `tests/jobrig.py` does not need to change (it lacks `secret_values`, and that is fine).
  - `TUILogHandler` redacts a logged secret.
  - `repr(JobSpec(..., kwargs={"p": "x"}))` does not contain the value.
  - `_SettingsGroup` is non-leaf even when it has no children, and `find_shortcut_conflicts` still works.
  - `MenuState.enter()` works on a group with no children (guard against an empty-children edge case).
  - Existing tests stay green.
- Scope: C2-2, plumbing for C2-1, P3.3.
- Wave 1.

**WP-4: integration, `App` API, and settings tree.**
- Owns:
  - `cli_interface/app.py`
  - `cli_interface/commands.py`
  - `cli_interface/settings_menu.py` (new)
  - `cli_interface/__init__.py` (export `Param`, `Secret`; docstring)
  - `pyproject.toml`
  - `tests/test_params_app.py` (new)
  - `tests/test_public_api.py` and `tests/test_commands.py` (edit only what must change)
- Contents:
  - `commands.py`: `params=` and `confirm=` on `command` and `add_command`; derivation at registration with fail-early errors; `App.settings`; `capture_loggers` and `capture_level`; the X-1 fix.
  - `app.py`: `_execute_item` flow (idle check, choices, form, confirm, `submit`), `_activate` calling `on_enter`, `add_secret`, `add_secret_source`, `secret_values`, the `_after_mount()` hook, and `add_secret` on form submit.
  - `settings_menu.py`: `build_settings_group(...)` implementing D4.
- Consumes: WP-1, WP-2 and WP-3 contracts.
- Acceptance, all through Pilot (the user types the shortcut then Enter, as in existing tests):
  - A command with `filter: Literal[...]`, `limit: int = 4`, `headless: bool = True` and `password: Annotated[str, Secret()]` opens a form. Submitting valid values runs the job with correctly typed kwargs; invalid values leave the form open with inline errors.
  - A `choices` callable using `c.state` is resolved at open time.
  - Esc runs nothing.
  - Opening is rejected with a Busy warning while a job runs.
  - A command with `confirm=True` or a str message: No/Esc runs nothing, Yes runs the job.
  - Dataclass and argparse `params=` deliver an instance and a Namespace respectively.
  - Legacy `add_command` with no extra parameters is unchanged. With extra supported parameters it shows a form, and `params=False` restores the old behaviour.
  - Settings:
    - nested dataclass submenus appear;
    - labels update live after an edit;
    - an edit calls `save` once;
    - a `save` that raises rolls back the value;
    - reset asks for confirmation and writes defaults in place;
    - a callable model is resolved on entering;
    - pydantic v2 works under `importorskip`;
    - a secret field is shown `••••` and an empty submit keeps the value.
  - A secret value typed into a masked form field or stored in a secret setting never appears in the panel, in a log record from an attached logger, or in an error message.
  - `capture_loggers=["x"]` routes `logging.getLogger("x").info(...)` to the panel (with `capture_level`) and detaches on exit.
  - `__all__` has the 15 names, and the `tests/test_public_api.py` list matches.
  - Previously failing `test_cancellable_and_description_are_stored_on_the_leaf` now passes on 3.14.
- Scope: P3.1, P3.2, P3.3, C2-1, C2-2, C2-3, X-1.
- Wave 2 (needs WP-1, WP-2 and WP-3 merged).

**Waves:** Wave 1 is WP-1, WP-2 and WP-3 in parallel (WP-2's tests wait for WP-1's `params.py`). Wave 2 is WP-4.

## 3. Test notes for the cross-cutting Tester

- Run end to end through Pilot with `CLIApp.run_test(size=SIZE)`, using `tests/helpers.py` (`panel_text`, `wait_for`) and `app.jobs.wait_idle`.
  - Walk full flows: type the shortcut + Enter, fill the fields with `pilot.press`, submit, read the panel.
  - Settings flow: open Settings, enter a nested submenu, edit, check the nav label, reset, confirm.
- Real-run test, following the `tests/test_real_run.py` pattern:
  - Start an example script in a subprocess pty or with `run_test` in a child process.
  - Check that a typed secret never reaches the captured output of the process.
  - Check that quitting while a form is open exits cleanly.
- Sweep the hostile-string matrix (`helpers.HOSTILE`) through form labels, defaults, choices, validation messages and settings values (`[/x]`, `matrix[i][j]`).
- Sampled mutations, about 15 to 20, aimed at:
  - the confirm default focus (flip it to Yes);
  - skipping `add_secret` on submit;
  - the `secret_values()` union in `_launch`;
  - `TUILogHandler` redaction removed;
  - the empty-input rule (`int | None` giving None, the empty-secret "keep" rule);
  - rollback on a failing `save`;
  - reset not being recursive;
  - the Busy check before the form;
  - the order form then confirm;
  - the kwargs merge;
  - the legacy `params=False` path;
  - the X-1 partial check;
  - `Esc` cancel;
  - the `capture_loggers` once-guard;
  - float nan acceptance.
- Compatibility checks: the full existing suite is green; run the `uv build` and `scripts/check_dist.py` checks; assert `import cli_interface` with pydantic not installed.
- Run the lowest-direct (Textual 0.80) environment once, because of the Select, Switch and SelectionList APIs.

## 4. Risks and product decisions I defaulted

1. **Auto forms on existing commands.** Any command function with extra supported parameters now opens a form instead of silently using its defaults. The opt-out is `params=False`. Unsupported-type parameters with defaults are skipped, so legacy code keeps running. Please confirm you want auto-derive as the default, as in the consumer sketch.
2. **Form first, then confirm.** `confirm` text is static and cannot mention the entered values.
3. **Settings edits are jobs.**
   - They are rejected with Busy while another job runs, and they run on a thread so `save` can do IO.
   - `save` runs on every edit and reset (not batched) and rolls the value back if it raises.
4. **Secret settings.** An empty submit means "unchanged", so a secret cannot be cleared through the UI. A secret edit goes through `item.secret=True`, which also hides the job result.
5. **Redaction set is a snapshot at launch**, and `add_secret` entries stay for the session. Writes to `app.panel` outside a job are not redacted. These are documented limits, not fixes.
6. **Frozen dataclasses** are rejected rather than replaced, because there is no parent to re-assign into.
7. **Pydantic.** Validation errors are only caught at assignment (they show as the job's ERROR, not inline). Optional dependency, tests use `importorskip`, and it is added only to the `test` group.
8. **`Secret` is an annotation marker**, not the sketch's `Secret("user_password")` call form. The `ctx.require(...)` form is left for a later phase (decision U11).
9. **C2-4 is deferred** to Phase 4 (not cheap).
10. **Textual 0.80 compatibility** of `Select`, `Switch` and `SelectionList` is unverified. The risk is concentrated in WP-2. Please prioritise the end-of-phase lowest-direct run.
11. **Textual's own fatal-error handler** prints locals. `values` and the form dict are local variables in the new `app.py` flow, so WP-4 must check that `_fatal_error` still scrubs them. The existing `_fatal_error` already handles the prompted `value`.

### Critical Files for Implementation
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/app.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/commands.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/jobs.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/widgets.py
- /Users/andrewmacleod/workspace/cli_interface/cli_interface/menu.py
