"""Edge cases: markup in action errors, main-thread logging, post-exit logging."""
from __future__ import annotations

import asyncio
import io
import logging
import sys

from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem


def boom() -> None:
    raise ValueError("bad key [/section] in config")


async def crash_case() -> None:
    app = CLIApp(MenuItem("Home", children=[MenuItem("Boom", shortcut="x", action=boom)]))
    try:
        async with app.run_test() as pilot:
            await pilot.press("x", "enter")
            await pilot.pause()
            print("crash_case: app still running after action raised markup-y error:", app.is_running)
    except Exception as exc:  # noqa: BLE001
        print("crash_case: app crashed ->", type(exc).__name__, str(exc)[:120])
    print("crash_case: return_code =", app.return_code)


async def main_thread_log_case() -> None:
    log = logging.getLogger("consumer")
    log.setLevel(logging.INFO)
    app = CLIApp(MenuItem("Home", children=[MenuItem("Do", shortcut="d", action=lambda: log.info("hello from action"))]))
    buf = io.StringIO()
    async with app.run_test() as pilot:
        attach_logging(app, log)
        old = sys.stderr
        sys.stderr = buf
        try:
            await pilot.press("d", "enter")
            await pilot.pause()
        finally:
            sys.stderr = old
        shown = [s.text for s in app.query_one("#display-panel").lines]
    err = [l for l in buf.getvalue().splitlines() if "Error" in l or "must run" in l]
    print("main_thread_log: shown in panel:", any("hello from action" in s for s in shown))
    print("main_thread_log: stderr:", err[:3])
    # After exit: handler still attached, log again
    buf2 = io.StringIO()
    old = sys.stderr
    sys.stderr = buf2
    try:
        log.info("after exit")
    finally:
        sys.stderr = old
    err2 = [l for l in buf2.getvalue().splitlines() if "Error" in l]
    print("post_exit_log: handlers still attached:", [type(h).__name__ for h in log.handlers])
    print("post_exit_log: stderr:", err2[:3])


def basicconfig_stream_case() -> None:
    logging.basicConfig(level=logging.DEBUG)
    h = logging.getLogger().handlers[0]
    print("main.py basicConfig handler stream is sys.__stderr__ (same fd Textual draws on):",
          getattr(h, "stream", None) is sys.__stderr__)


if __name__ == "__main__":
    asyncio.run(crash_case())
    asyncio.run(main_thread_log_case())
    basicconfig_stream_case()
