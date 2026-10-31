from __future__ import annotations

import asyncio
import logging
import threading
import time
import warnings
from typing import Any, Callable

from rich.text import Text
from textual.geometry import Region
from textual.widget import Widget
from textual.widgets import RichLog

from cli_interface.app import CLIApp
from cli_interface.log_handler import TUILogHandler
from cli_interface.menu import MenuItem

SIZE = (140, 40)

# The hostile-string matrix from the plan and the review.
HOSTILE = ["[/x]", "matrix[i][j]", "C:\\data\\[/tmp]", "x\\[y", "[bold]x[/bold]", "[", "]["]


def leaf(label: str, shortcut: str = "", action: Callable[..., Any] | None = None, **kw: Any) -> MenuItem:
    return MenuItem(label, shortcut=shortcut, action=action or (lambda: None), **kw)


def menu(*items: MenuItem, label: str = "Home") -> MenuItem:
    return MenuItem(label, children=list(items))


class Calls:
    """Action factory that records which actions ran."""

    def __init__(self) -> None:
        self.log: list[tuple[str, tuple]] = []

    def action(self, name: str, result: Any = None) -> Callable[..., Any]:
        def run(*args: Any) -> Any:
            self.log.append((name, args))
            return result

        return run

    @property
    def names(self) -> list[str]:
        return [n for n, _ in self.log]


# --------------------------------------------------------------------------- reading the UI

def panel_lines(app: Any) -> list[str]:
    log = app.screen_stack[0].query_one("#display-panel", RichLog)
    return [s.text.rstrip() for s in log.lines]


def panel_text(app: Any) -> str:
    return "\n".join(panel_lines(app))


async def read_panel(pilot: Any) -> str:
    await pilot.pause()
    return panel_text(pilot.app)


def widget_lines(widget: Widget) -> list[str]:
    region = Region(0, 0, widget.outer_size.width, widget.outer_size.height)
    return ["".join(seg.text for seg in strip).rstrip() for strip in widget.render_lines(region)]


def widget_text(widget: Widget) -> str:
    return "\n".join(widget_lines(widget))


# --------------------------------------------------------------------------- waiting

async def wait_for(predicate: Callable[[], Any], timeout: float = 5.0, interval: float = 0.01, what: str = "") -> None:
    """Poll from a coroutine, yielding to the event loop between checks."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what or predicate}")
        await asyncio.sleep(interval)


def wait_until(predicate: Callable[[], Any], timeout: float = 5.0, interval: float = 0.01, what: str = "") -> None:
    """Poll from plain synchronous code."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout}s waiting for {what or predicate}")
        time.sleep(interval)


def join_all(threads: list[threading.Thread], timeout: float = 10.0) -> None:
    for t in threads:
        t.join(timeout)
    alive = [t.name for t in threads if t.is_alive()]
    assert not alive, f"threads still alive after {timeout}s: {alive}"


def run_threads(*targets: Callable[[], Any], timeout: float = 10.0) -> None:
    threads = [threading.Thread(target=t, daemon=True) for t in targets]
    for t in threads:
        t.start()
    join_all(threads, timeout)


# --------------------------------------------------------------------------- logging helpers

def tui_handlers(logger: logging.Logger) -> list[TUILogHandler]:
    return [h for h in logger.handlers if isinstance(h, TUILogHandler)]


def plain(value: Any) -> str:
    return value.plain if isinstance(value, Text) else str(value)


# --------------------------------------------------------------------------- inbox stubs

class StubPanel:
    def __init__(self) -> None:
        self.out: list[tuple[str, str]] = []
        self.fail: Exception | None = None
        self.failed_attempts = 0

    def log(self, message: str, level: str = "INFO") -> None:
        if self.fail is not None:
            self.failed_attempts += 1
            raise self.fail
        self.out.append((message, level))

    @property
    def messages(self) -> list[str]:
        return [m for m, _ in self.out]


class StubApp:
    """Minimal app for PanelInbox and LogAttachment unit tests: it only needs .panel and .push_log."""

    def __init__(self) -> None:
        self.panel = StubPanel()
        self.pushed: list[tuple[str, str]] = []

    def push_log(self, message: str, level: str = "INFO") -> None:
        self.pushed.append((message, level))


def line_segments(app: Any, needle: str) -> list[tuple[str, Any]]:
    """(text, rich Style) for every segment of the last panel line containing `needle`."""
    log = app.screen_stack[0].query_one("#display-panel", RichLog)
    for strip in reversed(log.lines):
        if needle in strip.text:
            return [(seg.text, seg.style) for seg in strip]
    raise AssertionError(f"no panel line contains {needle!r}")


def color_of(style: Any) -> str | None:
    return style.color.name if style is not None and style.color is not None else None


def quiet_app(*items: MenuItem, **kwargs: Any) -> CLIApp:
    """Build an app whose menu may have shortcut conflicts, discarding the construction warnings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return CLIApp(menu(*items), **kwargs)


def build_demo_app(**kwargs: Any) -> CLIApp:
    """The demo menu wired the same way cli_interface.app.run() does."""
    from cli_interface.example_menu import build_example_menu

    ref: list[CLIApp] = []
    demo_menu = build_example_menu(get_panel=lambda: ref[0].panel, get_app=lambda: ref[0])
    app = CLIApp(demo_menu, **kwargs)
    ref.append(app)
    return app


class ThreadWatch:
    """Snapshot of the live threads at fixture setup; alive() lists the threads started since."""

    def __init__(self) -> None:
        self._baseline = set(threading.enumerate())

    def alive(self) -> list[threading.Thread]:
        me = threading.current_thread()
        return [t for t in threading.enumerate() if t not in self._baseline and t is not me and t.is_alive()]

    async def settle(self, timeout: float = 10.0) -> None:
        """Yield to the loop until they finish (a worker's call_from_thread needs the loop to answer)."""
        await wait_for(lambda: not self.alive(), timeout=timeout, what="worker threads to finish")

    def join(self, timeout: float = 10.0) -> None:
        join_all(self.alive(), timeout)
