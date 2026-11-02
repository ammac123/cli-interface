"""
Warning categories emitted by ``cli_interface``. Both subclass ``UserWarning``, so an
existing ``UserWarning`` filter still matches them. Filter or escalate by category::

    warnings.simplefilter("error", ShortcutConflictWarning)
"""


class ShortcutConflictWarning(UserWarning):
    """
    A menu has a reserved or duplicate shortcut (see ``find_shortcut_conflicts``).

    Emitted once per problem by ``CLIApp(menu)``, ``set_menu`` and ``refresh_menu``
    when ``strict_shortcuts`` is off; with it on they raise ``ValueError`` instead.
    """


class LoggingAttachWarning(UserWarning):
    """
    ``attach_logging`` ignored ``exclusive`` or ``level`` because the app already has an
    active attachment for that logger.
    """
