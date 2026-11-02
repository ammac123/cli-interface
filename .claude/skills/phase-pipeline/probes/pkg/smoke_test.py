# BASELINE REPRO (commit fdb8069): this probe describes behaviour from before Phase 0 and is expected to
# "fail" or print different results now. The maintained regression tests are in tests/ (see tests/test_regression.py).
"""Headless smoke test of the example CLIApp using Textual's Pilot."""
from __future__ import annotations

import asyncio
import io
import logging
import sys
import time

from textual.widgets import RichLog

from cli_interface.app import CLIApp
from cli_interface.example_menu import build_example_menu
from cli_interface.log_handler import TUILogHandler
from cli_interface.widgets import Dashboard, PromptScreen


def build_app() -> CLIApp:
    ref: list[CLIApp] = []
    menu = build_example_menu(get_panel=lambda: ref[0].panel, get_app=lambda: ref[0])
    app = CLIApp(menu)
    ref.append(app)
    return app


def lines(app: CLIApp) -> list[str]:
    return [s.text for s in app.query_one("#display-panel", RichLog).lines]


async def main() -> None:
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    app = build_app()
    stderr_buf = io.StringIO()
    real_stderr = sys.stderr
    async with app.run_test(size=(120, 40)) as pilot:
        dash = app.query_one("#dashboard", Dashboard)
        check("mount: breadcrumb is Home", dash.location == "Home", dash.location)
        check("is_headless under run_test", app.is_headless, str(app.is_headless))

        # 1. Shortcut key 'v' enters View Output
        await pilot.press("v")
        await pilot.pause()
        inp = app.query_one("#command-input")
        check("single-key 'v' (no Enter) -> View Output", dash.location == "Home|View Output", f"location={dash.location} input={inp.value!r}")
        inp.value = ""
        await pilot.press("v", "enter")
        await pilot.pause()
        check("typed 'v'+Enter -> View Output", dash.location == "Home|View Output", dash.location)

        # 2. Shortcut 'j' renders JSON
        await pilot.press("j", "enter")
        await pilot.pause()
        out = lines(app)
        check("press 'j' -> JSON rendered", any("server" in l for l in out), f"{len(out)} lines")

        # 3. Escape goes back
        await pilot.press("escape")
        await pilot.pause()
        check("escape -> Home", dash.location == "Home", dash.location)

        # 4. Arrow + Enter navigation into Settings (index 2)
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        check("down,down,enter -> Settings", dash.location == "Home|Settings", dash.location)

        # 5. Typed command + prompt modal
        await pilot.press("p", "enter")
        await pilot.pause()
        check("press 'p' -> PromptScreen", isinstance(app.screen, PromptScreen), type(app.screen).__name__)
        await pilot.press("8", "0", "8", "0", "enter")
        await pilot.pause()
        out = lines(app)
        check("prompt submit -> action result logged", any("port → 8080" in l for l in out), out[-1] if out else "")

        # 6. Help command typed into the input
        await pilot.press(*"help", "enter")
        await pilot.pause()
        check("'help' renders table", any("Navigate menu items" in l for l in lines(app)), "")

        # 7. Untrusted output with Rich markup characters (e.g. output from a foreign script)
        for msg in ["array[0] = 1", "path C:\\tmp\\[x]", "closing tag [/oops] here"]:
            try:
                app.panel.log(msg, "INFO")
                await pilot.pause()
                shown = lines(app)[-1]
                check(f"log untrusted {msg!r}", msg in shown, f"shown as {shown!r}")
            except Exception as exc:  # noqa: BLE001
                check(f"log untrusted {msg!r}", False, f"{type(exc).__name__}: {exc}")

        # 8. Worker demo: attaches TUILogHandler to the ROOT logger, exclusive
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("w", "enter")
        await pilot.pause()
        root = logging.getLogger()
        check(
            "worker demo mutates root logger",
            any(isinstance(h, TUILogHandler) for h in root.handlers),
            f"root.level={logging.getLevelName(root.level)} handlers={[type(h).__name__ for h in root.handlers]}",
        )
        await pilot.pause(6.0)
        out = lines(app)
        check("worker logs reach panel via thread", any("Worker finished" in l for l in out), f"{len(out)} lines")

        # 9. Logging from the app's own thread after attach_logging
        sys.stderr = stderr_buf
        try:
            logging.getLogger("consumer").info("logged from main thread")
            await pilot.pause()
        finally:
            sys.stderr = real_stderr
        err = stderr_buf.getvalue()
        check(
            "main-thread log after attach_logging is displayed",
            any("logged from main thread" in l for l in lines(app)),
            ("stderr: " + err.strip().splitlines()[-1]) if err else "no stderr",
        )

        await pilot.press("q", "enter")
        await pilot.pause()

    root = logging.getLogger()
    check(
        "root logger restored after app exit",
        not any(isinstance(h, TUILogHandler) for h in root.handlers),
        f"handlers={[type(h).__name__ for h in root.handlers]}",
    )
    check("app exited cleanly", app.return_code in (0, None), f"return_code={app.return_code}")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")


if __name__ == "__main__":
    t0 = time.perf_counter()
    asyncio.run(main())
    print(f"elapsed {time.perf_counter() - t0:.1f}s")
