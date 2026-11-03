Documenter (step 6) for Phase 3 is done. Nothing is committed. No behaviour changed and tests/ was not touched.

FILES CHANGED BY ME
- CHANGELOG.md: baseline line now includes Phase 3 = 646c781. New top section "## [Unreleased] - Phase 3 (parameters and settings)" with Added, Changed (behaviour) (subgroups: commands with parameters, forms, secrets), Fixed (X-1, raising __post_init__, raising validate=) and Known limits. Phase 2 kept as is. The brief said "## Phase 2 ..." but every prior phase in this file uses "## [Unreleased] - Phase N (...)", and that is what I kept.
- README.md:
  - Status line now says Phase 3 is done.
  - Install paragraph and the CI known-limitation updated to the verified environments (3.14 / Textual 8.2.8; 3.13 / lowest direct versions).
  - Public API: App row gains capture_loggers/capture_level; new Param and Secret rows; the 15-name statement; the internal-names list now includes FormScreen, ConfirmScreen, ParamSpec, FormContext and the params/settings/settings_menu modules.
  - Jobs: @app.command and App signatures and bullets point to the new section.
  - Logging: a capture_loggers bullet.
  - New "## Parameters, forms and settings" section (before "Running a menu..."), with subsections Settings and Secrets.
  - Known limitations: a "Parameters and settings:" group (de-duplicated against the Jobs group).
  - Tests line: about 2,000 tests, about 4 minutes.
- cli_interface/params.py: docstrings for Param and Secret (new module, docstrings only).
- cli_interface/commands.py: App class docstring (capture_loggers/capture_level); settings() TypeError line.
- cli_interface/widgets.py: FormScreen docstring (id sanitisation); ConfirmScreen docstring (confirm-yes / confirm-no ids).
- Not touched: app.py, settings.py, settings_menu.py, __init__.py (their docstrings were already accurate), tests/.

FINDINGS THAT CHANGED THE DOCS (verified with scratch scripts under the scratchpad docs/ dir, outside the repo)
1. Rendering depends on the shared secret set. Once any secret is registered (a settings secret with a non-empty value from startup, a masked form value once submitted, or add_secret), every later job's json, table and pretty output becomes plain text and a renderable shows its type name ("<Panel>"). Confirmed: with and without a registered secret, the same command gives a panel body without the secret and "<Panel>" with it. Documented under CHANGELOG Changed > Secrets and in the README Secrets subsection. Possible product issue for you: a settings secret silently strips styling app-wide.
2. The brief's limit "secret in a returned dict/table is not redacted" is wrong. A returned dict shows "token": "***" and a table cell shows ***. I documented the correct behaviour.
3. The brief's limit "app.panel written outside a job is not redacted" is too narrow. app.panel.log() called from inside a job body also leaks (ctx.panel is redacted). Documented as: use ctx.panel inside a job.
4. Ctrl+C under PromptScreen does not quit (confirmed empirically), the same as for forms and confirm. Documented.

VERIFIED BY RUNNING
- The README Parameters section code, assembled from its python blocks, registers (Deploy/Release, Deploy/Retry, Deploy/Scale, Settings). Release opens a form with the expected fields. Submitting it opens the confirm dialog, and Esc closes it without running.
- Argparse params delivers a Namespace (name='svc', count=7). The Retry dataclass delivers Retry(target='prod', retries=2).
- Literal/Enum/list[Literal] classify as expected. Positional-only without a default raises. An unsupported type without a default raises at registration.
- capture_loggers routes INFO to the panel and detaches on exit.
- Settings nav labels: "Name (app)", "Level (LOW)", "Token (••••)", "Reset to defaults".

NOT VERIFIED BY ME (taken from the ledger and reports)
- Textual 0.80 runs and the lowest-direct pytest run. I did not run them.
- The pydantic settings paths, the save-rollback and reset behaviour, and the Settings unavailable path. These rest on the test suite and code reading.
- A reviewer carry-forward (MINOR): a reset that fails part-way (for example pydantic validate_assignment) is not rolled back. I did not verify it and did not document it.
- The Ctrl+Q statement (not bound on Textual 0.80) comes from the ledger.

CHECKS
- uv run pytest tests/test_public_api.py tests/test_packaging.py tests/test_check_dist.py tests/test_params.py -q: 260 passed.
- uv run ruff check cli_interface: clean.
- uv run mypy cli_interface: no issues in 20 files.
- git diff --stat (after my edits) shows only CHANGELOG.md, README.md, commands.py and widgets.py modified by me. params.py is untracked; I changed only its docstrings. The other modified files were already modified before I started.