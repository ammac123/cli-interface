"""
Warning categories emitted by ``cli_interface``. Both subclass ``UserWarning``, so an
existing ``UserWarning`` filter still matches them. Filter or escalate by category::

    warnings.simplefilter("error", ShortcutConflictWarning)
"""
import os
import warnings

_PKG_PREFIX = os.path.dirname(__file__) + os.sep


class ShortcutConflictWarning(UserWarning):
    """
    A menu has a reserved or duplicate shortcut (see ``find_shortcut_conflicts``).

    Emitted once per problem by ``CLIApp(menu)``, ``set_menu``, ``refresh_menu`` and, for
    ``App``, ``add_command`` / ``@command`` / ``group``, when ``strict_shortcuts`` is off;
    with it on they raise ``ValueError`` instead. The warning points at the caller outside
    the package.
    """


class LoggingAttachWarning(UserWarning):
    """
    ``attach_logging`` ignored ``exclusive`` or ``level`` because the app already has an
    active attachment for that logger, or attached nothing because the app has already
    exited (it then returns an inert handle).
    """


def warn_external(message: str, category: type[Warning]) -> None:
    """Warn with the location of the nearest caller outside the ``cli_interface`` package."""
    warnings.warn(message, category, skip_file_prefixes=(_PKG_PREFIX,))
