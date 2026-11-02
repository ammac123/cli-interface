# WP-6 report (console script `cli_interface/cli.py`)

WP-6 is done. `cli_interface/cli.py` is new, about 120 lines, and implements D2 and D9 as specified. Ruff 0.17.3 and mypy 2.4.1 are clean on it. All WP-6 acceptance items pass, with one caveat: the literal `uv run --no-sync cli-interface ...` form cannot pass against the shared `.venv` until it is synced (see section 7). I did not commit and touched no other file. One TUI process was launched by mistake during testing and killed (see section 7).

## 1. Files changed
- `/Users/andrewmacleod/workspace/cli_interface/cli_interface/cli.py` (new). It is the only file I touched, and it is covered by P1.4c.
- `main(argv: Sequence[str] | None = None) -> int` is the entry point.
- A `if __name__ == "__main__": raise SystemExit(main())` guard makes it runnable as `python -m cli_interface.cli`.
- Imports are `._version.__version__`, `.app.CLIApp`, `.menu.MenuItem`, with stdlib otherwise.
- Private helpers: `_TargetError`, `_positive_int`, `_build_parser`, `_is_dotted_name`, `_takes_app`, `_load_menu`.

## 2. Behaviour as built
- **Parser.**
  - `prog="cli-interface"` is hardcoded, so help is stable under `python -m` and the Windows shim.
  - Flags are `target` (positional, no metavar), `--strict-shortcuts`, `--max-lines N` and `--version` (prints `cli-interface 0.1.0`). `-h` and `--help` come from argparse.
  - `--max-lines` accepts positive ints only.
  - All help text is ASCII.
- **Flow.**
  1. `parse_args`.
  2. Build `CLIApp(MenuItem("cli-interface"), strict_shortcuts=..., [max_lines=...])`, passing `max_lines` only if the flag was given.
  3. Prepend the cwd to `sys.path`.
  4. Resolve the target.
  5. `app.set_menu(menu)`.
  6. `app.run()`.
  7. Return `app.return_code or 0`.
- **Target resolution.**
  - The spec is `module:attr`. Both parts must be dotted identifiers, otherwise exit 2 with "target must look like module:attr".
  - The module is imported with `importlib.import_module`, then the attr is walked with `getattr`.
  - A `MenuItem` is used as is.
  - A callable is called with the `CLIApp` if it has at least one required positional parameter (checked with `inspect.signature`). Otherwise it is called with no arguments. A callable with no inspectable signature is also called with no arguments.
  - Anything else exits 2.
  - A result that is not a `MenuItem` exits 2.
- **Errors via `parser.error` (exit 2).**
  - Bare invocation, which gives "the following arguments are required: target".
  - A bad spec format, an `ImportError` on import, a missing attribute, a target that is not a `MenuItem` or callable, a callable returning the wrong type, and a bad `--max-lines`.
  - A strict-shortcuts `ValueError` from `set_menu`. The message is `shortcut conflicts (--strict-shortcuts):` followed by the full problem list from `find_shortcut_conflicts`, one per line.
- **Exit 1 with a traceback.** An exception raised inside the user's `build_menu`, or at module import time (other than `ImportError`), propagates.

## 3. Deviations and decisions
None from D2. These are choices where D2 was silent.
- **`ImportError` becomes exit 2 with no traceback.** This includes an `ImportError` raised inside the target module, such as `import missing_dep`. The message is `cannot import module 'X': <exc text>`. I read D2's "import failure" this way. `SyntaxError` and other import-time exceptions propagate with a traceback.
- **Step order follows D2.** The `CLIApp` is constructed before the target is parsed, so even `nocolon` builds an App, though it is never run.
- **The strict-conflict message has a header line.** `shortcut conflicts (--strict-shortcuts):` is followed by the problem list. D2 only asked for the problem list.
- **`importlib.invalidate_caches()` runs before each import.** It prevents stale directory caches when a test writes a module and calls `main()` twice in one process.
- **`--max-lines` help text hardcodes "(default: 5000)".** It will drift if `app._DEFAULT_MAX_LINES` changes. I did not import the private name.
- **Non-strict conflicts warn to stderr before the TUI starts.**
  - The line reads `.../cli.py:NNN: ShortcutConflictWarning: ...` followed by the `app.set_menu(menu)` source line. The call-site attribution is correct under D7's `stacklevel=3`.
  - The same problems appear as WARNING lines in the panel once the app is mounted.
- **`SystemExit` escapes `main()`.** `parse_args` and `parser.error` raise `SystemExit`, as D2 specifies for `--help` and `--version`. `main()` returns an `int` only on the normal path, so tests need `pytest.raises(SystemExit)` for the exit-2 paths.

## 4. Cross-package requests
None. For the Tester: `tests/test_regression.py` and the rest of the suite already break on the WP-7 move (a `test_demo.py` collection error, for one). That is the expected plan §5 breakage.

## 5. What `main()` mutates in-process (for the Tester)
- **`sys.path`.**
  - `os.getcwd()` is inserted at index 0 only if `sys.path[0] != cwd`, and is never removed. Repeated calls from the same cwd do not stack, but `chdir` between calls does.
  - The insert happens after argparse succeeds, so it also happens on the target-error paths (`nocolon`, bad module, wrong return type, strict conflict).
  - It does not happen for `--help`, `--version`, a missing target or a bad `--max-lines`.
  - Restoring via `monkeypatch.setattr(sys, "path", list(sys.path))` or `monkeypatch.syspath_prepend` covers it.
- **`sys.modules`.** The target module and its parent packages stay imported. A later call that reuses the module name gets the stale module, so use unique per-test names or `monkeypatch.delitem(sys.modules, name, raising=False)`.
- **`importlib.invalidate_caches()`** is a global, harmless effect.
- **Warnings.**
  - Under the default filters a non-strict conflict prints once per location.
  - Under the planned pytest `filterwarnings = error::...ShortcutConflictWarning`, the warning becomes an exception in `set_menu`. It is not a `ValueError`, so it does not take the exit-2 branch. Tests of the non-strict path must use `pytest.warns` or `-W` overrides.
- The cwd and `os.environ` are untouched.

## 6. Acceptance results

**Static checks**
- `uvx --offline ruff@0.17.3 check --no-cache cli_interface/cli.py` gives "All checks passed!".
- `uv run --no-sync --offline --with mypy==2.4.1 mypy --cache-dir=/dev/null cli_interface/cli.py` gives "Success: no issues found in 1 source file".

**Shared `.venv`, via `uv run --no-sync python -m cli_interface.cli ... </dev/null`**

| Argument | Exit | Output |
|---|---|---|
| `--version` | 0 | `cli-interface 0.1.0` |
| `--help \| cat` | 0 | ASCII only (`grep -P '[^\x00-\x7F]'` finds nothing) |
| (none) | 2 | `cli-interface: error: the following arguments are required: target` |
| `nocolon` | 2 | `target must look like module:attr, not 'nocolon'` |
| `no.such.mod:x` | 2 | `cannot import module 'no.such.mod': No module named 'no'` |
| `examples.example_menu:nosuch` | 2 | `module 'examples.example_menu' has no attribute 'nosuch' (resolving 'nosuch')` |

**Real console-script shim.** I built a wheel into the scratch dir `wp6/dist` (`uv build --wheel --out-dir`) and installed it into the scratch venv `wp6/venv`. The shared `.venv` and the repo were untouched. From `wp6/elsewhere`, which holds the scratch target modules:

| Command | Exit | Result |
|---|---|---|
| `--version` | 0 | `cli-interface 0.1.0` |
| `--help` | 0 | |
| `--help` and `--version` under `PYTHONIOENCODING=ascii` | 0 | No `UnicodeEncodeError` |
| (bare) | 2 | |
| `nocolon` | 2 | |
| `no.such.mod:x` | 2 | |
| `t_menu:bad_type` | 2 | `'t_menu:bad_type' returned str, not a MenuItem` |
| `--strict-shortcuts t_menu:conflicts` | 2 | Header line plus 2 problem lines |
| `--max-lines 0 t_menu:ROOT` | 2 | `argument --max-lines: must be a positive integer, not '0'` |
| `t_menu:boom` | 1 | Traceback ending `RuntimeError: boom in build_menu`; resolved from cwd by the shim with the cwd off the path |
| `t_menu:ROOT` from an empty dir | 2 | `cannot import module 't_menu': No module named 't_menu'` |

**In-process harness (`CLIApp.run` monkeypatched, cwd off `sys.path`)**
- Targets that resolved with exit 0 and the expected root label:
  - a `MenuItem` object;
  - a zero-argument callable;
  - a callable taking `app` (it received a real `CLIApp`);
  - `optional_app(app=None)`, called with no arguments;
  - `star_args(*args)`, called with no arguments;
  - the dotted attrs `Holder.MENU` and `Holder.make` (a staticmethod);
  - `pkg.menus:build_menu`.
- `--strict-shortcuts` and `--max-lines 123` reach the `CLIApp` (`_strict_shortcuts=True`, `_max_lines=123`). `--max-lines` omitted leaves it at 5000.
- A `return_code` of 7 comes back as the return value 7.
- Every other error path above also holds in-process (`SystemExit(2)`).

**End to end with Textual `run_test()` driving the real `main()` flow**
- The scratch target, the `pkg.menus` target and `examples.example_menu:build_menu` from the repo root all mount. The app reports the right root label ("Home" for the example, 3 children) and `view_ready=True`.
- This passed on Python 3.13 with textual 8.2.8 and on Python 3.11 with textual 0.80.0 (the `wp4/v080` venv).

## 7. Not verified or caveats
- **Literal `uv run --no-sync cli-interface --version` against the shared `.venv` cannot pass until a sync.**
  - Its shim still calls the old `cli_interface.app:run`. I ran `.venv/bin/cli-interface --version </dev/null`, which fails with `TypeError: run() missing 1 required positional argument: 'menu'` and exit 1.
  - The same acceptance is verified through the scratch-wheel venv and `python -m cli_interface.cli`.
  - The Integrator's clean-env run will cover the real shim.
- **A TUI process was launched by mistake once.** In a shim test I `cd`'d into `wp6/`, where `t_menu.py` also lives, so the target resolved and the app started in a non-TTY shell. It spun at about 100% CPU, which is the known F7 hang, and I killed it. No such process remains. I then reran the negative control from an empty directory, which exits 2 as expected.
- The real TUI was never launched. Only `run_test()` was used.
- Windows, Python 3.14 and `sys.argv[0]` forms other than the macOS shim are unverified. `prog` is hardcoded to limit exposure.
- Python 3.11 and textual 0.80 were exercised through the harness and `python -m` only, not the shim.
- An `async def build_menu` returns a coroutine, so it exits 2 as "returned coroutine, not a MenuItem". Python also prints a "coroutine was never awaited" RuntimeWarning after the error. I left this alone as an edge case.
- A target that points at `cli_interface.cli:main` would recurse. I ignored it as a pathological case.

Scratch files are under `/private/tmp/claude-501/-Users-andrewmacleod-workspace-cli-interface/a45b262d-f323-4864-9108-4e881756f65b/scratchpad/wp6/`:
- `t_menu.py`
- `pkg/`
- `broken_import.py`
- `harness.py`
- `harness2.py`
- `e2e.py`
- `dist/`
- `venv/`
- `elsewhere/`
- `emptydir/`
