# Phase 1 Tester report (step 4)

**Summary:** the suite is green and extended. Counts, with all runs on the final files:

| Environment | Result |
|---|---|
| Python 3.13.7, textual 8.2.8, rich 15.0.0 (locked) | **885 passed**, 0 failed, 0 xfail, 0 warnings, ~91-98 s wall |
| Python 3.11.16, textual 0.80.0, rich 13.3.3 (lowest-direct, scratch copy) | **885 passed**, ~84-91 s |
| Python 3.14.7, locked versions (bonus, scratch copy) | 885 passed, 94 s |

- `uv run ruff check cli_interface examples scripts tests` reports "All checks passed!". The tests had 22 errors before.
- **No suspected code bugs.** No test needed an xfail.
- I ran `uv sync --locked` once on the shared `.venv`, which refreshed the `cli-interface` shim; it now reads `from cli_interface.cli import main`. I did not touch `uv.lock`. No `dist/` was built, and the `.ruff_cache` I created is removed.
- Most of the wall time is Pilot waits. CPU time is ~25 s.

## 1. Files changed

**Modified under `tests/`:**
- `conftest.py`
- `helpers.py`
- `test_attach_logging.py`
- `test_demo.py`
- `test_display_limits.py`
- `test_inbox.py`
- `test_regression.py`
- `test_secrets.py`
- `test_shortcuts.py`

`test_markup.py` is unchanged; it gains cases only through the new hostile sample in `helpers.py`.

**New under `tests/`** (384 tests):
- `test_public_api.py` (26)
- `test_menu_model.py` (53)
- `test_menu_ui.py` (48)
- `test_menu_updates.py` (35)
- `test_lifecycle.py` (37)
- `test_cli.py` (63)
- `test_check_dist.py` (90)
- `test_packaging.py` (32)

**New helpers:**
- `type_command` in `helpers.py`.
- `"a|b"` added to `HOSTILE`.

**Pytest config diff** (`[tool.pytest.ini_options]` in `pyproject.toml`):
```
-    # the package's own UserWarnings (shortcut conflicts, ignored attach arguments) fail a test unless it expects them
-    'error:.*(reserved command and will never reach|only the first is reachable|were ignored because):UserWarning',
+    # the package's own warning categories fail a test unless it expects them
+    "error::cli_interface.ShortcutConflictWarning",
+    "error::cli_interface.LoggingAttachWarning",
     "error::pytest.PytestUnhandledThreadExceptionWarning",
```

## 2. Scope ID to proving tests

All paths are under `tests/`. `::name*` means every test whose name starts with that prefix.

**P1.1 (`__init__`, `__all__`, `py.typed`, `__version__`)**
- `test_public_api.py`:
  - `::test_all_is_exactly_the_documented_public_api`
  - `::test_every_name_in_all_resolves_on_the_package`
  - `::test_a_star_import_brings_in_exactly_the_public_names`
  - `::test_the_facade_names_are_the_real_objects`
  - `::test_version_matches_the_installed_distribution_metadata`
  - `::test_version_has_a_single_source_that_pyproject_reads`
  - `::test_the_package_ships_the_py_typed_marker`
  - `::test_importing_the_package_configures_no_logging`

**P1.2a (callable labels and values)**
- `test_menu_model.py`: the `item_label`, `item_value`, breadcrumb and callable-label conflict tests (the first 11 tests, the breadcrumb test and the two conflict tests).
- `test_menu_ui.py`:
  - `::test_callable_label_and_value_are_drawn_in_the_nav_bar`
  - `::test_a_value_callable_returning_none_hides_the_value_and_zero_or_false_still_show`
  - `::test_non_string_callable_results_are_shown_through_str`
  - `::test_a_raising_callable_shows_the_error_marker_logs_at_debug_and_the_app_stays_alive`
  - `::test_a_secret_items_value_callable_is_never_called_and_shows_the_mask`
  - `::test_each_callable_runs_once_per_render_pass`
  - `::test_a_render_started_inside_a_callable_leaves_the_outer_pass_consistent`
  - `::test_callable_labels_appear_in_the_breadcrumb_and_follow_refresh_menu`
  - `::test_a_callable_label_is_used_for_the_no_action_line_and_the_prompt_title`
- Review-2 pinned behaviour 1 (label read before the action):
  - `test_menu_ui.py::test_the_executed_line_uses_the_label_as_it_was_before_the_action_ran`
  - `test_menu_ui.py::test_a_label_that_depends_on_state_the_action_clears_still_reads_cleanly`
  - `test_menu_ui.py::test_an_error_line_uses_the_label_as_it_was_before_the_action_ran`
  - `test_demo.py::test_the_worker_demo_label_shows_running_while_it_runs_but_the_executed_line_does_not` (the `Executed: Worker Demo` pin)
- Width with a callable label: `test_menu_ui.py::test_the_computed_width_of_a_cell_equals_its_rendered_width_for_shortcuts_of_every_length`.

**P1.2b and CF-4 (`set_menu`, `refresh_menu`, `go_home`, `_validate_menu`)**
- `test_menu_updates.py` covers all of the following:
  - `set_menu`:
    - `::test_set_menu_returns_to_the_new_root_with_the_first_item_selected`
    - `::test_set_menu_leaves_the_output_panel_alone`
    - `::test_set_menu_warns_at_the_callers_line_and_logs_each_problem_to_the_panel`
    - `::test_set_menu_warns_afresh*`
    - `::test_strict_mode_raises_value_error_and_keeps_the_old_menu`
    - `::test_a_warning_escalated_to_an_error_leaves_the_old_menu_in_place*`
    - `::test_set_menu_rejects_anything_but_a_menu_item[*]`
    - `::test_the_constructor_rejects_anything_but_a_menu_item[*]`
  - Before mount and after exit:
    - `::test_set_menu_before_the_app_starts*`
    - `::test_a_strict_conflict_before_the_app_starts*`
    - `::test_the_menu_methods_are_legal_before_the_app_starts`
    - `::test_the_menu_methods_are_legal_after_the_app_has_exited`
  - `refresh_menu`:
    - `::test_refresh_menu_shows_in_place_edits_and_keeps_the_stack_and_selection`
    - `::test_refresh_menu_falls_back_to_the_nearest_level*`
    - `::test_refresh_menu_clamps_the_selection*`
    - `::test_refresh_menu_warns_only_for_new_problems_and_again_after_one_disappears`
    - `::test_strict_mode_refresh_menu_raises_before_touching_the_view`
  - `go_home`:
    - `::test_go_home_from_three_levels_down*`
    - `::test_go_home_at_the_root_does_nothing`
  - With a prompt open and from a worker thread:
    - `::test_the_menu_methods_work_while_a_prompt_dialog_is_open`
    - `::test_the_menu_methods_can_be_called_from_a_worker_thread_through_call_from_thread`
    - `::test_the_menu_methods_work_from_a_worker_thread_while_a_prompt_is_open`
  - Shared validation hook (CF-4):
    - `::test_the_constructor_set_menu_and_refresh_menu_all_validate_through_the_same_hook`
    - `::test_the_constructor_validates_before_anything_else_exists`

**P1.3 (declared support and relock)**
- `test_packaging.py`:
  - `::test_python_3_11_or_newer_is_required`
  - `::test_the_runtime_dependencies_are_exactly_rich_and_textual`
  - `::test_rich_has_a_floor_and_no_ceiling` (pins `>=13.3.3`, per D12)
  - `::test_textual_has_a_floor_and_a_ceiling_below_the_next_major`
  - `::test_the_installed_dependencies_satisfy_the_declared_ranges`
  - `::test_the_classifiers_name_python_3_11_to_3_14_and_a_typed_package`
  - `::test_the_lock_file_records_the_same_requirements_as_pyproject`
  - `::test_the_locked_versions_satisfy_the_declared_ranges`

**P1.4a (what ships)**
- `test_packaging.py`:
  - `::test_the_wheel_ships_only_the_package`
  - `::test_the_sdist_has_an_explicit_include_list_without_tests_tooling_or_the_lock`
  - `::test_the_files_the_sdist_includes_exist[*]`
  - `::test_the_version_is_dynamic_and_read_from_the_package`
- `test_check_dist.py`, entire file:
  - Positive sdist and wheel, plus a positive built from the real repository file set.
  - Allowlist-versus-disk sync check.
  - 19 sdist and 12 wheel forbidden-member cases, each asserting the specific deny reason. That includes `tests/`, `.claude/`, `uv.lock`, and `example_*` in the wheel.
  - Missing required members, including `py.typed`.
  - Wrong console-script line, 8 wrong-metadata variants for each archive kind, and wrong version.
  - A lone self-consistent wheel at another version, which fails against the repo `_version.py`.
  - Unreadable, missing and wrong-type archives, path traversal, symlinks, and non-ASCII names.
  - `main()` exit codes 0, 1 and 2, wildcard expansion, and standalone `python -I scripts/check_dist.py` runs.

**P1.4b (demos moved)**
- `test_packaging.py`:
  - `::test_the_demos_moved_out_of_the_package_and_the_root`
  - `::test_the_old_demo_modules_can_no_longer_be_imported_from_the_package`
  - `::test_the_demos_import_the_library_only_through_its_public_facade`
  - `::test_the_demo_builder_has_the_documented_shape`
  - `::test_examples_main_is_runnable_as_a_module_and_importing_it_starts_nothing`
  - `::test_examples_main_builds_the_demo_app_and_returns_the_apps_exit_code`
- `test_demo.py`:
  - `::test_importing_examples_main_in_a_fresh_interpreter_configures_no_logging`
  - `::test_executing_examples_main_as_a_module_does_not_start_the_app_or_touch_root`

**P1.4c (console script)**
- `test_cli.py`, entire file:
  - Resolution of:
    - a `MenuItem`;
    - a zero-argument callable;
    - an app-taking callable (receives the real `CLIApp`);
    - `app=None`, `*args` and `**kwargs` callables (called with no arguments);
    - a required keyword-only parameter (raises `TypeError`);
    - dotted attrs;
    - packages;
    - the repo demo `examples.example_menu:build_menu` from the repo root.
  - `sys.path` handling and `sys.argv` defaulting.
  - Flags reaching the app, with an init-kwargs recorder showing `max_lines` is absent when the flag is omitted.
  - Bad `--max-lines` values, return-code propagation, and strict and non-strict conflicts.
  - Every exit-2 path.
  - Review-2 pinned behaviour 4:
    - A missing dependency inside the target module or a submodule raises `ModuleNotFoundError`.
    - A failed `from x import y` raises plain `ImportError`.
    - A `SyntaxError` or a raising `build_menu` propagates.
  - Subprocess runs of `python -m cli_interface.cli` and the installed `cli-interface` shim, with `stdin=DEVNULL`:
    - `--version`;
    - `--help`, ASCII with `PYTHONIOENCODING=ascii`, showing the `pkg.mod:build_menu` epilog and `(default: 5000)`;
    - a bare invocation (exit 2);
    - a missing module (exit 2, no traceback);
    - cwd resolution proven by a wrong return type (exit 2);
    - a failure inside the target (exit 1 with a traceback).
  - Entry-point metadata (`importlib.metadata`).

**P1.5 (ruff, mypy, CI, build check)**
- `test_packaging.py`:
  - `::test_ruff_is_configured*`
  - `::test_mypy_is_configured*`
  - `::test_the_dependency_groups*`
  - `::test_the_ci_matrix_covers_three_operating_systems_and_python_3_11_to_3_14`
  - `::test_the_ci_has_lowest_direct_legs*`
  - `::test_the_ci_installs_the_locked_versions`
  - `::test_the_ci_runs_lint_types_tests_the_console_script_and_the_dist_check`
  - `::test_the_ci_dist_check_covers_both_archives`
  - `::test_the_ci_runs_on_pushes_to_main_and_on_pull_requests`
  - `::test_the_dist_check_script_is_standard_library_only`
- `test_check_dist.py` as above.
- These are text-level checks on `ci.yml`; I did not execute the YAML.

**CF-1 (timer lifecycle)**
- `test_lifecycle.py`:
  - `::test_on_unmount_stops_all_three_timers_and_forgets_them`
  - `::test_stop_spinner_stops_both_spinner_timers*`
  - `::test_starting_the_spinner_twice_keeps_one_timer_of_each_kind`
  - `::test_a_second_on_mount_does_not_start_a_second_phrase_timer`
  - `::test_late_ticks_after_the_app_has_exited_are_harmless`
  - `::test_the_spinner_methods_do_nothing_before_the_app_starts`
  - `::test_a_tick_advances_the_spinner_frame_while_the_app_is_running`
- `test_regression.py::test_late_timer_ticks_after_teardown_are_harmless` (strict xfail removed; now passes).
- `test_menu_updates.py::test_a_spinner_tick_with_a_prompt_dialog_open_does_not_raise_and_still_animates`.

**CF-2 (single source for reserved commands)**
- `test_menu_model.py`:
  - `::test_reserved_actions_maps_each_command_to_one_of_four_actions`
  - `::test_reserved_commands_is_derived_from_reserved_actions`
  - `::test_reserved_actions_is_read_only`
  - `::test_reserved_action_*`
  - `::test_the_app_module_holds_no_literal_collection_of_reserved_words` (AST check)
- `test_menu_ui.py::test_every_reserved_command_triggers_its_mapped_action` (16 cases: each key, as-is and upper-case).

**CF-3 (warning categories)**
- `test_public_api.py`:
  - `::test_both_warning_categories_are_user_warnings`
  - `::test_a_shortcut_conflict_warns_with_its_own_category_and_still_matches_user_warning`
  - `::test_a_repeat_attach_with_ignored_arguments_warns_with_its_own_category`
  - `::test_the_pytest_filters_escalate_the_shortcut_conflict_category`
  - `::test_the_pytest_filters_escalate_the_ignored_attach_arguments_warning`
  - `::test_a_plain_user_warning_with_the_old_message_text_is_not_escalated`
  - `::test_pyproject_filters_are_by_category_not_by_message`
- I also tightened existing `pytest.warns(UserWarning, ...)` sites to the package categories in `test_attach_logging.py`, `test_inbox.py`, `test_shortcuts.py`, `test_demo.py` and `test_lifecycle.py`.
- UserWarning back-compat is still proven by `test_public_api` (`pytest.warns(UserWarning, match="reserved command")` and the `issubclass` test).

**CF-5 (shortcut whitespace)**
- `test_menu_model.py`: `::test_normalize_shortcut*`, `::test_a_reserved_word_hidden_by_whitespace*`, `::test_shortcuts_differing_only_in_whitespace_are_duplicates`, `::test_a_whitespace_only_shortcut_counts_as_no_shortcut`, `::test_select_by_shortcut_ignores_whitespace_on_both_sides`.
- `test_menu_ui.py::test_a_shortcut_with_surrounding_whitespace_is_displayed_stripped_and_works_typed`.

**CF-6 (NavBar width)**
- `test_menu_ui.py`:
  - `::test_the_computed_width_of_a_cell_equals_its_rendered_width_for_shortcuts_of_every_length` (shortcut lengths 1-10, padded, callable and nav cells)
  - `::test_a_longer_shortcut_widens_the_cell_by_exactly_its_length`
  - `::test_rows_never_hold_more_than_the_terminal_width[30|47|60]`

**CF-7 (nav-cell sentinel)**
- `test_menu_model.py`: `::test_nav_cells_are_nav_cell_instances_with_a_kind`, `::test_nav_cell_shortcuts_are_reserved_commands*`, `::test_an_unknown_nav_cell_kind_is_rejected`, `::test_a_consumer_item_is_never_mistaken_for_a_nav_cell[*]`.
- `test_menu_ui.py`:
  - `::test_a_consumer_item_whose_description_looks_like_a_sentinel_runs_its_action[__exit__|__back__]`
  - `::test_a_consumer_item_whose_description_looks_like_a_sentinel_is_drawn_like_any_other_item`
  - `::test_the_real_exit_cell_quits_when_selected_and_confirmed_with_enter`
  - `::test_the_real_back_cell_goes_up_when_selected_and_confirmed_with_enter`
- `test_shortcuts.py`: the rewritten `CELLS` parametrisation and demo walk.

**CF-8 (`run(menu)` forwarding)**
- `test_lifecycle.py`:
  - `::test_run_forwards_max_lines`
  - `::test_run_forwards_an_unbounded_max_lines`
  - `::test_run_forwards_strict_shortcuts*`
  - `::test_run_returns_the_apps_return_code`
  - `::test_run_builds_the_app_runs_it_and_returns_zero_by_default`
  - `::test_run_passes_its_menu_through_to_the_app`
- `test_regression.py::test_run_requires_a_menu_and_takes_the_cliapp_options_by_keyword`.

**CF-9 (what is exported)**
- `test_public_api.py`: `::test_internal_names_are_not_exported[*]`, `::test_log_attachment_is_exported_as_the_return_type_of_attach_logging`, `::test_log_attachment_is_exported_without_its_collaborators`.

**CF-10 (`max_lines`)**
- `test_lifecycle.py`:
  - `::test_max_lines_must_be_none_or_a_positive_int[*]` (11 bad values, including `True`, `"5"` and `1.5`)
  - `::test_valid_max_lines_values_are_accepted`
  - `::test_run_rejects_a_bad_max_lines_before_running`
  - `::test_a_bounded_panel_keeps_only_the_newest_lines`
  - `::test_the_default_panel_is_bounded_at_5000_lines`
  - `::test_max_lines_none_keeps_every_line` (5100 lines kept)

**CF-11 (demo Settings logging)**
- `test_demo.py`:
  - `::test_a_settings_action_logs_once_before_its_executed_line_and_leaves_no_handler_behind`
  - `::test_toggle_debug_logs_each_change_once_and_its_value_follows_in_the_nav_bar`
  - `::test_set_port_updates_the_nav_bar_value_and_an_invalid_port_changes_nothing`
  - `::test_reset_all_restores_the_defaults_and_goes_back_to_the_home_menu`
  - `::test_settings_records_appear_once_even_while_the_worker_demos_exclusive_root_capture_is_active`
  - `::test_the_demo_menu_uses_a_callable_label_and_callable_values`

**CF-12 (demo coupling)**
- Repaired `conftest.py` (fixtures import `examples.example_worker`), `helpers.build_demo_app`, `test_demo.py`, and the `test_real_run.py` demo tests via the fixed fixtures.
- Also repaired the `test_shortcuts.py` demo walk and the `test_regression.py` `run` pin.
- Structural: the `test_packaging.py` P1.4b tests.

**CF-13 (prompt hint height)**
- `test_menu_ui.py::test_the_prompt_dialog_shows_its_enter_and_esc_hint[False|True]`.

**CF-14 (pipe in a label)**
- `test_menu_ui.py::test_a_label_containing_a_pipe_is_one_crumb`
- `test_menu_ui.py::test_the_dashboard_falls_back_to_splitting_location_while_crumbs_is_unset`
- `test_markup.py::test_dashboard_breadcrumbs_status_and_spinner_label_are_literal[a|b]` (new `HOSTILE` sample)

**CF-15 (`+ Enter` in hint and help)**
- `test_menu_ui.py`:
  - `::test_the_hint_text_is_the_two_pinned_lines` (72 and 73 characters)
  - `::test_the_hints_quit_entry_says_plus_enter_and_comes_first_on_line_two`
  - `::test_the_hint_fits_an_80_column_terminal_without_clipping`
  - `::test_the_help_table_lists_every_typed_command_with_plus_enter` (all four help rows)
- `test_shortcuts.py::test_hint_text_has_the_new_wording_within_its_width_budget` (82 repaired to 72, plus the `<= 85` budget kept).

**CF-16 (ruff and mypy)**
- `ruff check tests` is clean (command result; no test shells out to ruff or mypy). I did not run mypy on tests.
- Config is pinned by the `test_packaging.py` ruff, mypy and dependency-group tests.

**CF-17 (fatal traceback locals)**
- `test_lifecycle.py`:
  - `::test_the_fatal_traceback_does_not_print_local_variables` (the secret is computed at run time)
  - `::test_control_textuals_own_handler_prints_locals` (the built-in control; it skips, rather than fails, if a Textual version stops printing locals)
  - `::test_a_crash_in_a_real_run_ends_the_app_and_prints_no_locals`
- It passes on Textual 0.80.0 and 8.2.8.

## 3. Repairs of the old tests

Each repair keeps the original assertion's intent.

- **`conftest.py`**: the `gated_worker`, `fast_worker` and `GatedWorker` imports now use `examples.example_worker`. They still monkeypatch `run` and log through the real worker logger.
- **`helpers.build_demo_app`**: it now builds `CLIApp(MenuItem("Home"))`, then `set_menu(build_menu(app))`. The root label stays "Home", because tests assert `location == "Home"`.
- **`test_demo.py`**:
  - The `with_app` parametrisation is gone, since the demo always has the Spinner item.
  - `build_menu(CLIApp(...))` replaces the old builder call.
  - The `import main` probe became `import examples.main as m`, asserting `m.main.__module__ == "examples.main"` with root handlers and level untouched.
  - `runpy.run_path(main.py)` became `runpy.run_module("examples.main", ...)`.
  - The "ignored" warning check now expects `LoggingAttachWarning`.
- **`test_shortcuts.py`**:
  - The `_BACK`/`_EXIT` import is removed.
  - `is_sentinel` and the kind checks use `isinstance(x, _NavCell)` with `.kind` (`"exit"` or `"back"`), covering `CELLS` and the demo walk.
  - The hint pin 82 became 72, and the `len(second) <= 85` budget is kept.
- **`test_regression.py`**:
  - The old `run` signature pin moved into a new test: `menu` required, `strict_shortcuts` and `max_lines` keyword-only, return type `int` via `get_type_hints`, and `run()` raising `TypeError`.
  - The strict xfail is removed. Teardown ticks now need the real guard.
- **Ruff**:
  - 18 renames of `l` to `ln` or `lease`.
  - 3 `Callable` imports moved to `collections.abc`.
  - 1 `%`-format kept with a `# noqa: UP031`, because %-formatting is exactly the secret-repr case the test exercises.
- **Behaviour-preserving tightening**: existing `pytest.warns(UserWarning...)` sites now name the category.

## 4. Other results

- **Probes** (run from scratch, nothing left in the repo):

| Probe | 3.13 / textual 8.2.8 | 3.11 / textual 0.80.0 |
|---|---|---|
| `io/exp2_after_exit.py` | Returned in 0.51 s, 335 post-exit records, 0 logging-error lines, no handlers left | Same, 394 records |
| `io/exp6_exit_latency.py thread` | 0.31 s | 0.32 s |
| `io/exp6_exit_latency.py worker` | 3.01 s (blocking thread holds exit, same as the baseline) | 3.01 s |

  `pkg/smoke_test.py` was not run (it imports the moved demos).
- **Safety**:
  - No test starts the real TUI.
  - `test_cli.py` replaces `CLIApp.run` with a headless recorder through an autouse fixture local to that module (so `test_real_run` still gets the real `run`).
  - Subprocess tests only pass `--help`, `--version` or error targets, with `stdin=DEVNULL`.
- **Review-2 pinned behaviours:**
  - **1:** covered under P1.2a.
  - **2:** `test_menu_ui.py`, hint tests under CF-15.
  - **3:** the help-row test.
  - **4:** `test_cli.py`.
  - **5:** the nested-render test.

## 5. Mutation check

36 mutations on a scratch copy at `.../scratchpad/tester/mut/`. It has its own venv with an editable install, and `cli_interface.__file__` was confirmed to point at the copy. 35 were caught, 1 survived. The first failing test is shown.

| Mutation | Caught by |
|---|---|
| `Executed:` and `Error in` label read after the action | `test_menu_ui::test_the_executed_line_uses_the_label_as_it_was_before_the_action_ran` |
| Secret value callable still called (still masked) | `test_menu_ui::test_a_secret_items_value_callable_is_never_called_and_shows_the_mask` |
| Same, with the secret value shown unmasked | the same test |
| `description="__exit__"` treated as the Exit sentinel | `test_menu_ui::test_a_consumer_item_whose_description_looks_like_a_sentinel_runs_its_action[__exit__]` |
| Tick methods lose the guard (CF-1) | `test_lifecycle::test_late_ticks_after_the_app_has_exited_are_harmless` |
| `on_unmount` stops no timers | `test_lifecycle::test_on_unmount_stops_all_three_timers_and_forgets_them` |
| `on_mount` starts a second phrase timer | `test_lifecycle::test_a_second_on_mount_does_not_start_a_second_phrase_timer` |
| `show_locals=True` (CF-17) | `test_lifecycle::test_the_fatal_traceback_does_not_print_local_variables` |
| Every `ModuleNotFoundError` becomes exit 2 | `test_cli::test_a_missing_dependency_inside_the_target_module_is_not_reported_as_a_missing_target` |
| Every `ImportError` becomes exit 2 | the same test |
| CLI drops the cwd `sys.path` insert | `test_cli::test_a_menu_item_target_is_shown_as_the_root` |
| check_dist stops denying `tests/` | `test_check_dist::...forbidden_member...[tests/test_x.py-...]` (asserts the specific "tests/ must not ship" reason) |
| check_dist stops requiring `py.typed` | `test_check_dist::test_an_sdist_missing_a_required_member_is_rejected[cli_interface/py.typed]` |
| `__all__` lists `PanelInbox` | `test_public_api::test_all_is_exactly_the_documented_public_api` |
| `py.typed` removed | `test_public_api::test_the_package_ships_the_py_typed_marker` |
| Attach warning downgraded to plain `UserWarning` | `test_public_api::test_a_repeat_attach_with_ignored_arguments_warns_with_its_own_category` |
| Shortcut warning downgraded to plain `UserWarning` | `test_menu_updates::test_set_menu_warns_at_the_callers_line_and_logs_each_problem_to_the_panel` |
| Strict `set_menu` swaps the tree before validating | `test_menu_updates::test_strict_mode_raises_value_error_and_keeps_the_old_menu` |
| `set_menu` or `refresh_menu` skips validation | `test_menu_updates::test_set_menu_warns_at_the_callers_line_and_logs_each_problem_to_the_panel` and `::test_refresh_menu_warns_only_for_new_problems_and_again_after_one_disappears` |
| `refresh_menu` never prunes | `test_menu_updates::test_refresh_menu_falls_back_to_the_nearest_level_that_still_exists` |
| `go_home` clears the panel | `test_menu_updates::test_go_home_from_three_levels_down_returns_to_the_root` |
| `prune` compares by equality | `test_menu_model::test_prune_compares_by_identity_not_equality` |
| `breadcrumb` no longer sets `crumbs` | `test_menu_updates::test_set_menu_returns_to_the_new_root_with_the_first_item_selected` |
| Width uses `sc = 2` (CF-6) | `test_menu_ui::test_the_computed_width_of_a_cell_equals_its_rendered_width_for_shortcuts_of_every_length` |
| `normalize_shortcut` stops stripping | `test_menu_ui::test_a_shortcut_with_surrounding_whitespace_is_displayed_stripped_and_works_typed` |
| `#prompt-hint` height 1 | `test_menu_ui::test_the_prompt_dialog_shows_its_enter_and_esc_hint[False]` |
| `run()` drops `max_lines` | `test_lifecycle::test_run_forwards_max_lines` |
| `run()` drops `strict_shortcuts` | `test_lifecycle::test_run_forwards_strict_shortcuts_so_a_conflict_stops_it_before_the_app_runs` |
| `max_lines` accepts `bool` | `test_lifecycle::test_max_lines_must_be_none_or_a_positive_int[True]` |
| Inline reserved-word tuple back in `app.py` | `test_menu_model::test_the_app_module_holds_no_literal_collection_of_reserved_words` |
| Demo logger propagates | `test_demo::test_a_settings_action_logs_once_before_its_executed_line_and_leaves_no_handler_behind` |
| Help row lost `+ Enter` | `test_menu_ui::test_the_help_table_lists_every_typed_command_with_plus_enter` |
| Hint line 2 lost `+ Enter` | `test_menu_ui::test_the_hint_text_is_the_two_pinned_lines` |
| NavBar without the per-render snapshot | `test_menu_ui::test_each_callable_runs_once_per_render_pass` |

**One survivor, an equivalent mutant:** removing only the `is_running` half of the `_tick_spinner` guard.
- `on_unmount` clears the widget refs first, so the `dash is None` half still guards a late tick.
- Removing the whole guard is caught.
- I did not bend a test to kill it.

## 6. Suspected code bugs

None. Observations that are not bugs:
- **Handlers on non-propagating loggers (pytest 9).** pytest attaches its capture handlers to every non-propagating logger that exists when a test starts. `examples.example_menu` has `propagate=False`, so its `.handlers` contains pytest's handlers during tests.
  - The CF-11 helper therefore asserts "no `TUILogHandler`, level back to `NOTSET`, `propagate` still `False`", not "no handlers".
  - This is a harness fact. The check is not weakened, and `M22` (propagate on) is caught.
- **Benign RuntimeWarning.** `examples/example_menu.py:221` (the `except RuntimeError` path after app exit) can emit "coroutine ... `call_from_thread...run_callback` was never awaited".
  - It appears only if a test ends while the worker is still blocked, as happened once in a failing assertion.
  - It never occurs in the green suite (`-rw` shows 0 warnings).
  - Textual builds the coroutine before the closed-loop `RuntimeError`. I treat it as a Textual or WP-7 wart, not a defect.
- **Order-dependent warning, fixed in the test.** The `examples.main` `runpy` test warned when another test had already imported it (seen during mutation runs). It now clears `sys.modules["examples.main"]` first.

## 7. Unverified

- The Windows legs: the `.exe` shim, path separators in `check_dist.py`, cp1252 behaviour.
- macOS-latest and ubuntu-latest runner specifics.
- The CI YAML never executes; only text-level checks exist.
- A real `uv build`, plus `uv lock --check` and the clean-venv wheel install (the Integrator's job).
- Textual 0.80 on Python 3.14 (plan Risk 1): the new tests never ran there. My 3.14 run used the locked Textual 8.2.8.
- The real TUI under a TTY (F7). Nothing here can detect a hang.
- `go_home()` at the root: I pin only "does nothing", meaning location, items and panel unchanged. The plan text is ambiguous about the selection index there.
- `--help` wrapping at unusual `COLUMNS`: the test normalises whitespace and pins `COLUMNS=100`, `NO_COLOR=1` and `PYTHON_COLORS=0` in its subprocess; I checked it with `COLUMNS=40` and `COLUMNS=120` exported.

Scratch artifacts, nothing in the repo: `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/tester/` (`low311/`, `py314/`, `mut/`, `mutate.py`, `mutation.log`, `low.sh`).