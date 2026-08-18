import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import CLIApp


class TUILogHandler(logging.Handler):
    """Routes Python log records into the TUI log panel."""

    def __init__(self, app: "CLIApp") -> None:
        super().__init__()
        self._app = app
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            level = record.levelname
            self._app.call_from_thread(self._app.push_log, msg, level)
        except Exception:
            self.handleError(record)
