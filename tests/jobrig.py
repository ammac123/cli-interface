"""A fake ManagerHost and a rig around a JobManager, for tests that need no Textual."""
from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from types import SimpleNamespace
from typing import Any

from cli_interface.capture import CAPTURE
from cli_interface.display import DisplayPanel
from cli_interface.jobs import JobManager, JobSpec


class FakeHost:
    """Everything JobManager asks of the app, recorded. The thread that builds it is the 'UI thread'."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self.ui_ident = threading.get_ident()
        self.state = SimpleNamespace()
        self.events: list[dict[str, Any]] = []
        self.changes: list[str | None] = []
        self.spinner_calls: list[tuple[str, Any]] = []
        self._tokens = 0
        self.exits: list[tuple[Any, int, Any]] = []
        self.flushes = 0
        self.ui_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fail_set_menu: Exception | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    # -- JobHost
    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def on_ui_thread(self) -> bool:
        return threading.get_ident() == self.ui_ident

    def call_ui(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        if self.on_ui_thread():
            return fn(*args, **kwargs)
        fut: concurrent.futures.Future[Any] = concurrent.futures.Future()

        def run() -> None:
            try:
                fut.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # noqa: BLE001
                fut.set_exception(exc)

        self._loop.call_soon_threadsafe(run)
        return fut.result(timeout=10)

    def post_ui(self, fn: Any, *args: Any) -> None:
        self._loop.call_soon_threadsafe(fn, *args)

    def set_menu(self, menu: Any) -> None:
        self.ui_calls.append(("set_menu", (menu,)))
        if self.fail_set_menu is not None:
            raise self.fail_set_menu

    def refresh_menu(self) -> None:
        self.ui_calls.append(("refresh_menu", ()))

    def go_home(self) -> None:
        self.ui_calls.append(("go_home", ()))

    # -- ManagerHost
    def panel_for(self, emitter: Any) -> DisplayPanel:
        return DisplayPanel(emitter=emitter)

    def spinner_acquire(self, label: str) -> int:
        self._tokens += 1
        self.spinner_calls.append(("acquire", label))
        return self._tokens

    def spinner_release(self, token: int) -> None:
        self.spinner_calls.append(("release", token))

    def job_changed(self, job: Any) -> None:
        self.changes.append(None if job is None else job.label)

    def flush_inbox(self) -> None:
        self.flushes += 1

    def request_exit(self, result: Any, return_code: int, message: Any) -> None:
        self.exits.append((result, return_code, message))

    # -- reading what happened
    def kinds(self) -> list[str]:
        return [e["kind"] for e in self.events]

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["kind"] == kind]

    def log_lines(self) -> list[tuple[str, str]]:
        return [(e["level"], e["msg"]) for e in self.events if e["kind"] == "log"]

    def lines(self) -> list[str]:
        """The panel lines the renderer would draw for the lifecycle events (Executed / Cancelled / Error / log text)."""
        out = []
        for e in self.events:
            if e["kind"] == "log":
                out.append(e["msg"])
            elif e["kind"] == "text":
                out.append(e["text"])
            elif e["kind"] == "result":
                label = e["label"]
                out.append(f"Cancelled: {label}" if e["status"] == "cancelled" else
                           f"Executed: {label}" + (f" → {e['summary']}" if e["summary"] else ""))
            elif e["kind"] == "error":
                out.append(f"Error in {e['label']}: {e['message']}")
        return out


class Rig:
    """A JobManager over a FakeHost, with the output capture installed when asked."""

    def __init__(self, *, capture: bool = False, quit_grace: float = 2.0) -> None:
        self.loop = asyncio.get_running_loop()
        self.host = FakeHost(self.loop)
        self.mgr = JobManager(self.host, quit_grace=quit_grace)  # type: ignore[arg-type]
        self._token: object | None = None
        self._capturing = False
        if capture:
            CAPTURE.acquire()
            self._capturing = True
            self._token = CAPTURE.open_app(self.host.emit, self.host.ui_ident)

    def close(self) -> None:
        self.mgr.close()
        if self._capturing:
            self._capturing = False
            if self._token is not None:
                CAPTURE.close_app(self._token)
            CAPTURE.release()

    # -- helpers
    def submit(self, fn: Any, label: str = "Job", **kw: Any) -> Any:
        return self.mgr.submit(JobSpec(label, fn, **kw))

    async def run(self, fn: Any, label: str = "Job", *, timeout: float = 10.0, **kw: Any) -> Any:
        """Submit and wait for it to finish; returns the Job."""
        mark = self.mgr.mark()
        job = self.submit(fn, label, **kw)
        assert job is not None, "the job was rejected"
        await self.mgr.wait_idle(since=mark, jobs=1, timeout=timeout)
        return job
