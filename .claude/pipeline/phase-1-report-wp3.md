# WP-3 report (packaging, lint config, CI, dist check)

WP-3 is implemented as specified, with two small deviations (`.gitignore` is an extra hatch force-adds, and the CI `python` call goes through `uv run`). Nothing was committed. All scratch work is under `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp3/`. There is no `dist/` in the repo, and `.venv` and `tests/` were not touched.

## 1. Files changed or created
- `/Users/andrewmacleod/workspace/cli_interface/pyproject.toml` (modified)
  - Section 4 verbatim.
  - `[tool.pytest.ini_options]` stays in its original position. I checked it byte-for-byte against the baseline copy and it is identical.
  - `[tool.ruff]` and `[tool.mypy]` are appended at the end.
- `/Users/andrewmacleod/workspace/cli_interface/uv.lock` (relocked, never hand-edited)
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/_version.py` (new): `__version__ = "0.1.0"` and nothing else.
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/py.typed` (new, empty)
- `/Users/andrewmacleod/workspace/cli_interface/scripts/check_dist.py` (new, stdlib only)
- `/Users/andrewmacleod/workspace/cli_interface/.github/workflows/ci.yml` (new)

## 2. Scope IDs
- **P1.1b:** `py.typed`, and `_version.py` as the single `__version__` source via `[tool.hatch.version] path`. The `Typing :: Typed` classifier is also added.
- **P1.3:**
  - `requires-python>=3.11`, `rich>=13.3.3` (the D12 deviation from the ledger's `>=13`), and `textual>=0.80,<9`.
  - Classifiers 3.11 to 3.14, and the dynamic version.
  - The `[project.scripts]` line is `cli-interface = "cli_interface.cli:main"`.
  - Relocked.
- **P1.4a:** sdist `only-include = ["cli_interface","examples","README.md","LICENSE","CHANGELOG.md"]`, plus `exclude` for `__pycache__` and `*.py[cod]`. The wheel is `packages = ["cli_interface"]`. The D14 split holds: `examples/` is in the sdist only.
- **P1.5:**
  - Dependency groups `test`, `lint` and `dev`.
  - `scripts/check_dist.py`.
  - `ci.yml` with `lint`, `test` and `build` jobs.
- **CF-16 config:** `[tool.ruff]` with E4, E7, E9, F, UP and B, line length 120, target py311. `[tool.mypy]` with the section 4 flags. There is no `files` key, as the plan says.

## 3. Deviations and settled facts
- **Hatch force-added sdist files, settled empirically.**
  - I built with `only-include = ["cli_interface"]` in a scratch copy. Hatch always adds `PKG-INFO`, `pyproject.toml`, `README.md`, `LICENSE` and `.gitignore`.
  - `.gitignore` is not in the plan's expected extras, so it is a deviation. It is now explicitly in `SDIST_ALLOW`.
  - `CHANGELOG.md` and `examples/` are not force-added, which is why they are in `only-include`.
  - The wheel has no extras beyond the allowlist: `dist-info/{METADATA,WHEEL,RECORD,entry_points.txt,licenses/LICENSE}`.
  - A scratch build with decoy `tests/`, `.claude/`, `scripts/`, `.github/`, `main.py`, `examples/__pycache__` and `examples/foo.pyc` confirmed none of them ship. `examples/*.py` ships in the sdist only.
  - A missing `examples/` directory does not error the build.
- **Version check goes beyond the archives (a decision to confirm).**
  - I first compared only the archive contents (PKG-INFO/METADATA version, `_version.py` member, sdist root name, dist-info directory name).
  - A lone wheel at 0.2.0 that agreed with itself then passed. So `check_dist.py` also reads the repo's `cli_interface/_version.py`, found via `Path(__file__).resolve().parents[1]`. If that file is absent it prints a `note:` and skips.
  - **The Tester should know this.** A synthetic positive archive must use the repo's real version (0.1.0), or it will fail the comparison when the script is run from inside the repo.
- **Module pattern.** I kept the plan's `[A-Za-z_]+\.py`, so a future module with digits in its name would need an allowlist edit. This is not a deviation.
- **CI differences from the plan text.**
  - Action pins are `actions/checkout@v6` and `astral-sh/setup-uv@v7`. I confirmed both tags exist with `git ls-remote` and read their `action.yml` (node24, inputs `python-version` and `enable-cache` present). I added `persist-credentials: false`, `permissions: contents: read`, and `enable-cache: true`.
  - The build job runs `uv run --no-project python scripts/check_dist.py dist/*.tar.gz dist/*.whl` instead of bare `python`, because `setup-uv` does not put `python` on PATH. This is the same command otherwise.
  - The lowest-direct textual 0.80.0 assertion uses `importlib.metadata` instead of `uv pip list`.
  - The build job also checks `py.typed` via `importlib.resources`, and that `import examples` fails from a clean venv. These are in section 6 but not in the section 2 text.
- **Relock.** `uv lock --offline` failed: `mypy>=2.4` is not in the offline cache as registry metadata. The plain network `uv lock` worked, so nothing was hand-edited.
- **Stale entry point.**
  - The shared `.venv/bin/cli-interface` still reads `from cli_interface.app import run`. It stays stale until someone syncs.
  - `uv run --no-sync` still works: importing `menu`, `widgets` and `app` through it succeeded.
  - Anyone who runs plain `uv run` will resync `.venv` to the new lock and groups. Executors should keep using `--no-sync`.

## 4. Cross-package requests
- **To the Tester:** `scripts/` has no `__init__.py`, so load `check_dist.py` with importlib or run it as a subprocess.
  - The importable API is `main(argv) -> int` and `check_artifact(path) -> (problems, [(source, version)])`.
  - Output format: `ok`/`FAIL <path>` on stdout, and `error: <archive name>: <member>: <reason>` on stderr. It exits 1 on any violation, including an unreadable archive or an unsupported file type. It exits 2 on usage errors.
  - Wildcard arguments are expanded by the script when the shell does not.
- **Unexpected change by someone else:** `cli_interface/__init__.py` became modified partway through my run. It is WP-5's file (wave 2) and I did not touch it. The orchestrator should check who changed it.
- **Hand-off for later waves and the Integrator:**
  - The lint, test-smoke and build jobs fail until WP-6 (`cli.py`) and WP-7 (`examples/`) land.
  - `ruff check ... examples` also needs `examples/` to exist.
  - In the plan's lowest-direct commands, `.python-version` (3.13) plus `--no-sync` prints a harmless "incompatible environment" warning. It still works.

## 5. Acceptance results
- **tomllib parse:** OK. `requires-python` is `>=3.11`, the dependencies are as specified, the script is `cli_interface.cli:main`, and the version is dynamic.
- **`uv lock --check`:** passes both with `--offline` and online.
- **Lock contents (23 packages).**

| Package | Locked version |
|---|---|
| textual | 8.2.8 |
| rich | 15.0.0 |
| ruff | 0.17.3 |
| mypy | 2.4.1 |
| pytest | 9.2.0 |
| pytest-asyncio | 1.4.1 |

  - Also added: ast-serialize 0.13.1, librt 0.16.0, mypy-extensions 1.1.0, pathspec 1.1.1.
  - The lock now has `requires-python >=3.11` and a `>=3.15` resolution marker.
  - `uv sync --locked` into a scratch venv worked for the lint group on 3.13 and the test group on 3.11.
- **`uv build --offline --out-dir <scratch>/dist`:** OK. It builds the sdist, then the wheel from the sdist.
- **Interim `check_dist.py` on the real archives (final script, rebuilt):** exit 1 with exactly 10 problems. These are the planned ones:
  - sdist: `cli_interface/example_menu.py` and `example_worker.py` unexpected; `cli_interface/cli.py`, `examples/__init__.py`, `examples/example_menu.py`, `examples/example_worker.py` and `examples/main.py` missing.
  - wheel: `example_menu.py` and `example_worker.py` unexpected; `cli.py` missing.
  - Nothing else flagged, so `warning_types.py`, `py.typed` and `_version.py` are fine. `Requires-Python`, the rich/textual specifiers, the version, and `entry_points.txt` pass.
- **Positive control:** a synthetic sdist and wheel, built from the real ones with `cli.py` and `examples/*` added and `example_*` removed, exit 0 under Python 3.11 and 3.14 (isolated mode). Each archive alone also passes.
- **Negative controls (final script).** About 40 synthetic archives made in the scratch directory, never in the repo. All exit 1 with a specific message, for both sdist and wheel:
  - extra `tests/x.py`, `uv.lock`, `.claude/y`, `.github/...`, `scripts/...`, `main.py`, `.python-version`, `__pycache__/*.pyc` or `whiteboard/...`; a stray file; `example_menu.py` in the package;
  - `examples/main.py` in the wheel;
  - missing `py.typed`; missing `entry_points.txt`; a wrong script line;
  - wrong `Requires-Python`, wrong rich floor, wrong textual specifier;
  - an sdist root that does not match its version; a `..` path;
  - an sdist at 0.3.0 next to a wheel at 0.1.0;
  - a lone self-consistent 0.2.0 wheel (caught by the repo `_version.py` comparison);
  - a non-gzip `.tar.gz`; a `.zip`.
- **ruff 0.17.3** on `scripts/check_dist.py` with the exact flags from the task, and with the `pyproject.toml` config: all checks passed.
- **mypy 2.4.1** with the exact flags, and with the `pyproject.toml` config: no issues found.
- **YAML:** parsed with PyYAML fetched ephemerally by online `uvx` (the offline cache only had an unusable `pyyaml` cp27 wheel). Nothing was added to the project. The parse showed the triggers, concurrency, jobs, matrix (3 OS × 4 Python × `locked`, plus the two ubuntu lowest-direct `include` legs, which become separate combinations), step `if`/`shell` fields, and the bash blocks. I also read it by eye.
- **Risk 1 (textual 0.80 on Python 3.14), checked locally on a rsync'd snapshot in scratch.**
  - Lowest-direct on 3.11.16 and on 3.14.7 both resolve textual 0.80.0 and rich 13.3.3.
  - Both give 467 passed, 1 xfailed.
  - The snapshot was taken mid-W1 with the other executors' partial edits, so this is evidence, not proof.
  - Based on this, no marker-split floor is needed so far.

## 6. Not verified
- The CI YAML never runs here: no GitHub-Actions-specific checking (an actionlint-style check was not available), no Windows or macOS legs, and the runner-specific behaviour of `setup-uv` and `uv python` downloads is untested.
- Windows behaviour of `check_dist.py`. It uses `posixpath` and regex on member names and `PurePath` on the artifact path. The globbing of unexpanded wildcards is untested on Windows.
- The final green `check_dist.py` run on real archives. That needs WP-6 and WP-7 and is for the Integrator.
- The console-script smoke and clean-venv steps in the CI. The `cli_interface.cli:main` target does not exist yet, so they were never run end to end.