from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from .menu import MenuItem

if TYPE_CHECKING:
    from .app import CLIApp, DisplayPanel

log = logging.getLogger(__name__)

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

def build_example_menu(
    get_panel: Callable[[], "DisplayPanel"],
    get_app: Callable[[], "CLIApp"] | None = None,
) -> MenuItem:
    """
    Build the demo menu.

    ``get_panel`` is a lazy callable that returns the DisplayPanel once the
    app is mounted. ``get_app`` is an optional lazy callable for features
    that need direct app access (e.g. the spinner).
    """

    # -- Demo: JSON ---------------------------------------------------------
    def show_json() -> None:
        p = get_panel()
        p.clear()
        p.json(_SAMPLE_CONFIG, title="Application Config")

    # -- Demo: Table --------------------------------------------------------
    def show_table() -> None:
        p = get_panel()
        p.clear()
        p.table(_SAMPLE_USERS, title="Team Directory")

    # -- Demo: CSV ----------------------------------------------------------
    def show_csv() -> None:
        p = get_panel()
        p.clear()
        p.csv(_SAMPLE_CSV, title="Service Health")

    # -- Demo: Log lines ----------------------------------------------------
    def show_logs() -> None:
        p = get_panel()
        p.clear()
        p.rule("Recent Events")
        p.log("Application started on port 8080", "INFO")
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
        p = get_panel()
        p.clear()
        p.array(_SAMPLE_ARRAY, title="Allowed IP Addresses")

    # -- Demo: Pretty object ------------------------------------------------
    def show_pretty() -> None:
        p = get_panel()
        p.clear()
        p.pretty(_SAMPLE_OBJECT, title="Pipeline Definition")

    # -- Demo: Mixed / dashboard view ---------------------------------------
    def show_mixed() -> None:
        p = get_panel()
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
        if get_app is None:
            return
        app = get_app()
        p   = get_panel()
        p.clear()
        p.log("Background job started — watch the dashboard header for the spinner.", "INFO")
        app.start_spinner()  # cycles through loading phrases

        def _finish() -> None:
            app.stop_spinner()
            p.log("Background job finished.", "INFO")

        app.set_timer(6.0, _finish)

    # -- Demo: prompted action ----------------------------------------------
    def set_port(value: str) -> str:
        try:
            port = int(value)
            if not (1 <= port <= 65535):
                raise ValueError("out of range")
            log.info("Port set to %d", port)
            return f"port → {port}"
        except ValueError as exc:
            log.warning("Invalid port %r: %s", value, exc)
            return f"invalid: {value!r}"

    # -- Settings (uses logging) --------------------------------------------
    def set_volume(level: int):
        def _action():
            log.info("Volume set to %d%%", level)
            return level
        return _action

    def toggle_debug() -> None:
        log.warning("Debug mode toggled")

    def reset_all() -> None:
        log.warning("All settings reset to defaults")

    # -- Menu tree ----------------------------------------------------------
    view_output_children = [
        MenuItem("JSON Config",    shortcut="j", action=show_json),
        MenuItem("Table",          shortcut="t", action=show_table),
        MenuItem("CSV",            shortcut="c", action=show_csv),
        MenuItem("Log Lines",      shortcut="l", action=show_logs),
        MenuItem("Array",          shortcut="a", action=show_array),
        MenuItem("Pretty Object",  shortcut="p", action=show_pretty),
        MenuItem("Mixed View",     shortcut="m", action=show_mixed),
    ]
    if get_app is not None:
        view_output_children.append(
            MenuItem("Spinner Demo", shortcut="s", action=start_spinner_demo)
        )

    return MenuItem(
        label="Home",
        children=[
            MenuItem(
                label="View Output",
                shortcut="v",
                children=view_output_children,
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
                    MenuItem("Toggle Debug", shortcut="d", action=toggle_debug),
                    MenuItem(
                        "Set Port",
                        shortcut="p",
                        prompt="Enter port number (1–65535):",
                        action=set_port,
                    ),
                    MenuItem("Reset All", shortcut="x", action=reset_all),
                ],
            ),
        ],
    )
