from __future__ import annotations

import itertools
import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

import pytest

from cli_interface.app import CLIApp
from cli_interface.capture import CAPTURE
from cli_interface.menu import MenuItem
from cli_interface.log_handler import TUILogHandler
from helpers import GATES, ThreadWatch


_UNIQUE = itertools.count()


def _is_pytest_handler(handler: logging.Handler) -> bool:
    return type(handler).__module__.startswith("_pytest")


@pytest.fixture(autouse=True)
def root_logger_guard(request):
    """Restore the root logger after every test (ignoring pytest's own capture handlers) and fail the test
    if it leaked a TUILogHandler onto root. Opt out with @pytest.mark.allow_tui_handler_leak."""
    root = logging.getLogger()
    level = root.level
    saved = [h for h in root.handlers if not _is_pytest_handler(h)]
    yield root
    leaked = [h for h in root.handlers if isinstance(h, TUILogHandler) and h not in saved]
    for h in list(root.handlers):
        if not _is_pytest_handler(h) and h not in saved:
            root.removeHandler(h)
    for h in saved:
        if h not in root.handlers:
            root.addHandler(h)
    root.setLevel(level)
    if leaked and request.node.get_closest_marker("allow_tui_handler_leak") is None:
        pytest.fail(f"test leaked a TUILogHandler onto the root logger: {leaked}", pytrace=False)


@pytest.fixture(autouse=True)
def runtime_guard():
    """After every test: release the job gates, let job threads end, then require that no capture ref, app route,
    job thread or replaced stdout/stderr is left over. A leak is repaired first so it fails only the test that made it."""
    stdout, stderr = sys.stdout, sys.stderr
    GATES.clear()
    yield
    for gate in GATES:
        gate.set()
    GATES.clear()
    for thread in threading.enumerate():
        if thread.name.startswith("cli-interface-job-") and thread is not threading.current_thread():
            thread.join(10)
    problems = []
    alive = [t.name for t in threading.enumerate() if t.name.startswith("cli-interface-job-")]
    if alive:
        problems.append(f"job threads still alive: {alive}")
    if CAPTURE.refs != 0:
        problems.append(f"CAPTURE.refs == {CAPTURE.refs}")
    if CAPTURE._routes:
        problems.append(f"{len(CAPTURE._routes)} app route(s) still open")
    if sys.stdout is not stdout or sys.stderr is not stderr:
        problems.append("sys.stdout / sys.stderr were not restored (is-identity)")
    if problems:
        CAPTURE._refs = 0
        CAPTURE._holds = 0
        CAPTURE._outer.clear()
        CAPTURE._proxies.clear()
        CAPTURE._routes.clear()
        sys.stdout, sys.stderr = stdout, stderr
        pytest.fail("; ".join(problems), pytrace=False)


@pytest.fixture
def make_rig():
    """Factory for a JobManager over a fake host (call it inside an async test body)."""
    from jobrig import Rig

    made: list[Rig] = []

    def factory(**kwargs: Any) -> Rig:
        made.append(Rig(**kwargs))
        return made[-1]

    yield factory
    for rig in made:
        rig.close()


@pytest.fixture
def host_root(root_logger_guard):
    """Root logger configured like a host application: one sentinel handler at WARNING."""
    import io

    root = root_logger_guard
    sentinel = logging.StreamHandler(io.StringIO())
    sentinel.name = "host-sentinel"
    root.addHandler(sentinel)
    root.setLevel(logging.WARNING)
    root.sentinel = sentinel  # type: ignore[attr-defined]
    return root


@pytest.fixture
def unique_logger():
    """Factory for hermetic loggers: unique name, no propagation, DEBUG level, cleaned afterwards."""
    made: list[logging.Logger] = []

    def factory(prefix: str = "t", level: int = logging.DEBUG) -> logging.Logger:
        while True:  # skip names already taken, e.g. by an earlier in-process pytest run
            name = f"tests.{prefix}.{next(_UNIQUE)}"
            if name not in logging.Logger.manager.loggerDict:
                break
        lg = logging.getLogger(name)
        lg.propagate = False
        lg.setLevel(level)
        made.append(lg)
        return lg

    yield factory
    leaked = [(lg.name, h) for lg in made for h in lg.handlers if isinstance(h, TUILogHandler)]
    for lg in made:
        for h in list(lg.handlers):
            lg.removeHandler(h)
    if leaked:
        pytest.fail(f"test leaked a TUILogHandler onto a logger: {leaked}", pytrace=False)


@pytest.fixture
def handle_errors(monkeypatch: pytest.MonkeyPatch) -> list[logging.LogRecord]:
    """Records every Handler.handleError call (i.e. every 'Logging error' that would be printed)."""
    calls: list[logging.LogRecord] = []
    monkeypatch.setattr(logging.Handler, "handleError", lambda self, record: calls.append(record))
    return calls


@pytest.fixture
def thread_errors(monkeypatch: pytest.MonkeyPatch) -> list[threading.ExceptHookArgs]:
    """Records unhandled exceptions raised in threads."""
    calls: list[threading.ExceptHookArgs] = []
    monkeypatch.setattr(threading, "excepthook", lambda args: calls.append(args))
    return calls


@pytest.fixture
def make_app() -> Callable[..., CLIApp]:
    """CLIApp factory: make_app(item, item, ..., **CLIApp kwargs) with a 'Home' root menu."""

    def factory(*items: MenuItem, **kwargs: Any) -> CLIApp:
        return CLIApp(MenuItem("Home", children=list(items)), **kwargs)

    return factory


class GatedWorker:
    """Stands in for example_worker.run: logs through the real worker logger, then waits for release()."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.runs = 0
        self.threads = ThreadWatch()

    def __call__(self) -> None:
        from examples import example_worker

        self.runs += 1
        self.started.set()
        example_worker.log.info("Worker starting")
        example_worker.log.debug("heartbeat OK")
        self.release.wait(15)
        example_worker.log.info("Worker finished")


@pytest.fixture
def gated_worker(monkeypatch: pytest.MonkeyPatch):
    """Replace the demo worker with a deterministic, gated one; always release and join its thread afterwards."""
    from examples import example_worker

    gate = GatedWorker()
    monkeypatch.setattr(example_worker, "run", gate)
    yield gate
    gate.release.set()
    gate.threads.join()


@pytest.fixture
def fast_worker(monkeypatch: pytest.MonkeyPatch):
    """The real demo worker, shortened to a few quick steps. Yields a ThreadWatch for its thread."""
    from examples import example_worker

    original = example_worker.run
    watch = ThreadWatch()
    monkeypatch.setattr(example_worker, "run", lambda: original(steps=4, delay=0.03))
    yield watch
    watch.join()
