"""
The demo menu: ``build_menu(app)`` returns a tree that shows each kind of output (JSON,
table, CSV, log lines, array, pretty object), a spinner, a background worker whose logs
are captured exclusively, and Settings items with callable values, a prompt and a secret
prompt. It uses only the public ``cli_interface`` API.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from cli_interface import CLIApp, LogAttachment, MenuItem, attach_logging

from . import example_worker

# Logger for the Settings actions. A fixed name, and propagate off: each action attaches it to
# the panel for the length of the call, and records must not also reach the root logger, where
# the Worker Demo's exclusive capture would show them a second time.
log = logging.getLogger("examples.example_menu")
log.propagate = False

# ---------------------------------------------------------------------------
# Sample data for demo outputs
# ---------------------------------------------------------------------------

_SAMPLE_CONFIG = {
    "server": {"host": "localhost", "port": 8080, "debug": True, "workers": 4},
    "database": {
        "url": "postgresql://localhost/mydb",
        "pool_size": 10,
        "timeout": 30,
    },
    "features": {
        "auth": True,
        "metrics": True,
        "cache": False,
        "rate_limit": {"enabled": True, "requests_per_minute": 120},
    },
    "logging": {"level": "INFO", "format": "json", "output": "stdout"},
}

_SAMPLE_USERS = [
    {"Name": "Alice Chen",    "Role": "Engineer",  "Team": "Backend",  "Status": "Active"},
    {"Name": "Bob Okafor",    "Role": "Designer",  "Team": "Product",  "Status": "Active"},
    {"Name": "Carol Santos",  "Role": "Manager",   "Team": "Platform", "Status": "On leave"},
    {"Name": "David Kim",     "Role": "Engineer",  "Team": "Frontend", "Status": "Active"},
    {"Name": "Eve Larsson",   "Role": "Analyst",   "Team": "Data",     "Status": "Active"},
    {"Name": "Frank Mueller", "Role": "Engineer",  "Team": "Backend",  "Status": "Inactive"},
]

_SAMPLE_CSV = """\
host,port,latency_ms,requests_sec,status
api-01,443,12,1840,healthy
api-02,443,8,2100,healthy
api-03,443,150,310,degraded
api-04,443,9,1950,healthy
db-primary,5432,2,940,healthy
db-replica,5432,3,880,healthy
cache-01,6379,1,4200,healthy
"""

_SAMPLE_ARRAY = [
    "192.168.1.1", "192.168.1.2", "192.168.1.3",
    "10.0.0.1",    "10.0.0.2",
    "172.16.0.5",  "172.16.0.6",  "172.16.0.7",  "172.16.0.8",
]

_SAMPLE_OBJECT = {
    "pipeline": "ci-main",
    "stages": ["lint", "test", "build", "deploy"],
    "matrix": {"python": ["3.11", "3.12", "3.13"], "os": ["ubuntu", "macos"]},
    "env": {"CI": True, "CACHE_VERSION": 7, "ARTIFACT_RETENTION_DAYS": 14},
}


# ---------------------------------------------------------------------------
# Menu builder
# ---------------------------------------------------------------------------

def build_menu(app: CLIApp) -> MenuItem:
    """
    Build the demo menu. ``app`` is the CLIApp that will show it: the actions use
    its panel, spinner and ``go_home()``. Usable as a ``cli-interface`` target, run from
    the repository root (``examples/`` is not in the wheel)::

        cli-interface examples.example_menu:build_menu
    """

    # -- Demo: JSON ---------------------------------------------------------
    def show_json() -> None:
        p = app.panel
        p.clear()
        p.json(_SAMPLE_CONFIG, title="Application Config")

    # -- Demo: Table --------------------------------------------------------
    def show_table() -> None:
        p = app.panel
        p.clear()
        p.table(_SAMPLE_USERS, title="Team Directory")

    # -- Demo: CSV ----------------------------------------------------------
    def show_csv() -> None:
        p = app.panel
        p.clear()
        p.csv(_SAMPLE_CSV, title="Service Health")

    # -- Demo: Log lines ----------------------------------------------------
    def show_logs() -> None:
        p = app.panel
        p.clear()
        p.rule("Recent Events")
        p.log("Application started on port 8080", "INFO")
        p.log("Loaded config[server][port] = 8080", "DEBUG")  # brackets are literal by default
        p.log("Database connection pool initialised (10 connections)", "DEBUG")
        p.log("User alice@example.com authenticated", "INFO")
        p.log("Cache miss rate above threshold: 42%", "WARNING")
        p.log("User bob@example.com authenticated", "INFO")
        p.log("Slow query detected: 1.8s on users.find_by_email", "WARNING")
        p.log("Failed to reach upstream service: timeout after 5000ms", "ERROR")
        p.log("Circuit breaker OPEN for payments-service", "CRITICAL")
        p.log("Retry succeeded on attempt 3", "INFO")
        p.log("Graceful shutdown initiated", "INFO")

    # -- Demo: Array --------------------------------------------------------
    def show_array() -> None:
        p = app.panel
        p.clear()
        p.array(_SAMPLE_ARRAY, title="Allowed IP Addresses")

    # -- Demo: Pretty object ------------------------------------------------
    def show_pretty() -> None:
        p = app.panel
        p.clear()
        p.pretty(_SAMPLE_OBJECT, title="Pipeline Definition")

    # -- Demo: Mixed / dashboard view ---------------------------------------
    def show_mixed() -> None:
        p = app.panel
        p.clear()
        p.rule("System Overview")
        p.table(
            [
                {"Component": "API",      "Instances": "4", "Healthy": "4", "CPU": "23%"},
                {"Component": "Database", "Instances": "2", "Healthy": "2", "CPU": "11%"},
                {"Component": "Cache",    "Instances": "1", "Healthy": "1", "CPU": "4%"},
            ],
            title="",
        )
        p.rule("Active Config Snapshot")
        p.json({"port": 8080, "debug": False, "workers": 4, "cache": False})
        p.rule("Last 5 Events")
        p.log("Deployment pipeline-47 completed in 3m 12s", "INFO")
        p.log("Auto-scaled API from 3 → 4 instances", "INFO")
        p.log("Cache miss rate above threshold: 42%", "WARNING")
        p.log("User admin@corp.com changed rate_limit config", "INFO")
        p.log("Replica db-replica lag: 0.3s", "DEBUG")

    # -- Demo: spinner ------------------------------------------------------
    def start_spinner_demo() -> None:
        p = app.panel
        p.clear()
        p.log("Background job started — watch the dashboard header for the spinner.", "INFO")
        app.start_spinner()  # cycles through loading phrases

        def _finish() -> None:
            app.stop_spinner()
            p.log("Background job finished.", "INFO")

        app.set_timer(6.0, _finish)

    # -- Settings: the menu reads these values through callables (current_value), so it
    # always shows the live ones.
    settings = {"port": 8080, "debug": False}

    def capture_settings() -> LogAttachment:
        # Attached per call, on the UI thread while the app runs, and detached when the call ends.
        return attach_logging(app, log, level=logging.INFO)

    # -- Demo: prompted action ----------------------------------------------
    def set_port(value: str) -> str:
        with capture_settings():
            try:
                port = int(value)
                if not (1 <= port <= 65535):
                    raise ValueError("out of range")
            except ValueError as exc:
                log.warning("Invalid port %r: %s", value, exc)
                return f"invalid: {value!r}"
            settings["port"] = port
            log.info("Port set to %d", port)
            return f"port → {port}"

    # -- Demo: worker with exclusive log capture ----------------------------
    worker_running = threading.Event()

    def run_worker() -> None:
        p = app.panel
        if worker_running.is_set():
            p.log("Worker already running", "WARNING")
            return
        p.clear()
        p.rule("Worker Output")
        p.log("Launching background worker — logs captured exclusively in this panel", "INFO")

        # Exclusive capture lasts only for this run; detach() restores the
        # root logger's original handlers and level.
        capture = attach_logging(app, exclusive=True, level=logging.DEBUG)
        worker_running.set()  # after the attach, which can raise (warnings as errors)

        app.start_spinner(label="worker running…")

        def _finish() -> None:  # on the UI thread
            worker_running.clear()
            app.stop_spinner()
            app.refresh_menu()  # the Worker Demo label is a callable: show it idle again

        def _run() -> None:
            try:
                example_worker.run()
            finally:
                try:
                    capture.detach()
                finally:
                    try:
                        app.call_from_thread(_finish)
                    except RuntimeError:  # the app has already exited
                        worker_running.clear()

        threading.Thread(target=_run, daemon=True).start()

    def worker_label() -> str:
        return "Worker Demo (running)" if worker_running.is_set() else "Worker Demo"

    # -- Demo: secret prompt (the app never echoes the typed value; this logs only its length)
    def set_token(value: str) -> None:
        app.panel.log(f"Token accepted ({len(value)} chars)")

    def set_volume(level: int) -> Callable[[], int]:
        def _action() -> int:
            with capture_settings():
                log.info("Volume set to %d%%", level)
            return level
        return _action

    def toggle_debug() -> None:
        settings["debug"] = not settings["debug"]
        with capture_settings():
            log.warning("Debug mode toggled %s", "on" if settings["debug"] else "off")

    def reset_all() -> None:
        settings.update(port=8080, debug=False)
        with capture_settings():
            log.warning("All settings reset to defaults")
        app.go_home()

    # -- Menu tree ----------------------------------------------------------
    return MenuItem(
        label="Home",
        children=[
            MenuItem(
                label="View Output",
                shortcut="v",
                children=[
                    MenuItem("JSON Config",    shortcut="j", action=show_json),
                    MenuItem("Table",          shortcut="t", action=show_table),
                    MenuItem("CSV",            shortcut="c", action=show_csv),
                    MenuItem("Log Lines",      shortcut="l", action=show_logs),
                    MenuItem("Array",          shortcut="a", action=show_array),
                    MenuItem("Pretty Object",  shortcut="p", action=show_pretty),
                    MenuItem("Mixed View",     shortcut="m", action=show_mixed),
                    MenuItem("Spinner Demo",   shortcut="s", action=start_spinner_demo),
                ],
            ),
            MenuItem(
                label=worker_label,
                shortcut="w",
                action=run_worker,
                description="Run a background worker whose logs are captured exclusively in the TUI",
            ),
            MenuItem(
                label="Settings",
                shortcut="s",
                children=[
                    MenuItem(
                        label="Audio",
                        shortcut="a",
                        children=[
                            MenuItem("Volume Low",    shortcut="1", action=set_volume(25)),
                            MenuItem("Volume Medium", shortcut="2", action=set_volume(50)),
                            MenuItem("Volume High",   shortcut="3", action=set_volume(100)),
                        ],
                    ),
                    MenuItem(
                        "Toggle Debug",
                        shortcut="d",
                        action=toggle_debug,
                        current_value=lambda: "on" if settings["debug"] else "off",
                    ),
                    MenuItem(
                        "Set Port",
                        shortcut="p",
                        prompt="Enter port number (1–65535):",
                        action=set_port,
                        current_value=lambda: settings["port"],
                    ),
                    MenuItem(
                        "Set Token",
                        shortcut="k",
                        prompt="Enter API token:",
                        secret=True,
                        action=set_token,
                    ),
                    MenuItem("Reset All", shortcut="x", action=reset_all),
                ],
            ),
        ],
    )
