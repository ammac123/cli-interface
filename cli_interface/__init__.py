"""
cli_interface: a menu-driven terminal UI with a live output panel.

The public API is the names in ``__all__``; import them from this package::

    from cli_interface import App, Context, MenuItem

``App`` (with ``@app.command``) and ``Context`` are the job API; ``CLIApp``, ``MenuItem``
and ``run`` are the menu API that ``App`` builds on.

``LogAttachment`` is exported as the return type of ``attach_logging`` only: create
one through that function. ``PanelInbox``, ``TUILogHandler``, ``Job``, ``MenuState`` and
the widgets are internal. Importing the package does not configure logging.
"""

from ._version import __version__
from .app import CLIApp, attach_logging, run
from .commands import App
from .context import Context
from .display import DisplayPanel
from .log_handler import LogAttachment
from .menu import RESERVED_COMMANDS, MenuItem, find_shortcut_conflicts
from .warning_types import LoggingAttachWarning, ShortcutConflictWarning

__all__ = [
    "App",
    "CLIApp",
    "Context",
    "DisplayPanel",
    "LogAttachment",
    "LoggingAttachWarning",
    "MenuItem",
    "RESERVED_COMMANDS",
    "ShortcutConflictWarning",
    "__version__",
    "attach_logging",
    "find_shortcut_conflicts",
    "run",
]
