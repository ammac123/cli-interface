"""
``App``: a ``CLIApp`` whose menu is built from functions registered with ``@app.command``.
Re-exported by ``cli_interface``.
"""
from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from .app import _DEFAULT_MAX_LINES, _DEFAULT_QUIT_GRACE, CLIApp
from .menu import MenuItem, _CommandItem, make_command_item

_F = TypeVar("_F", bound=Callable[..., Any])


def _segments(path: str) -> tuple[str, ...]:
    if not isinstance(path, str):  # a bare ``@app.command`` passes the function here
        raise TypeError(f"path must be a str such as 'Group/Name', not {type(path).__name__}")
    segments = tuple(path.split("/"))
    if not all(segment.strip() for segment in segments):
        raise ValueError(f"invalid path: {path!r}")
    return segments


def _is_command(item: MenuItem) -> bool:
    return isinstance(item, _CommandItem) or item.action is not None


def _child(parent: MenuItem, segment: str) -> MenuItem | None:
    for child in parent.children:
        if isinstance(child.label, str) and child.label == segment:  # never call a callable label
            return child
    return None


def _first_doc_line(fn: Callable[..., Any]) -> str:
    doc = inspect.getdoc(fn) if inspect.isroutine(fn) else None
    return doc.splitlines()[0].strip() if doc else ""


def _remove(parent: MenuItem, node: MenuItem) -> None:
    parent.children[:] = [child for child in parent.children if child is not node]  # by identity


class App(CLIApp):
    """
    A ``CLIApp`` that builds its menu from decorated functions::

        app = App("My tool")

        @app.command("Run/Extract", key="e", cancellable=True)
        async def extract(ctx: Context) -> str: ...

        app.run()

    ``name`` is the root menu's label and the app's title; the keyword options are those of
    ``CLIApp`` (``strict_shortcuts``, ``max_lines``, ``quit_grace``), and the rest goes to
    Textual. A command function runs as a job: an ``async`` one on the event loop, any other
    in a daemon thread even if it takes no ``Context`` (take a ``ctx: Context`` parameter for
    progress, logging and cancellation). One command runs at a time. Its return value is shown
    by type (``str``, ``dict`` / ``list`` as JSON, a list of dicts as a table, a Rich renderable,
    ``None`` for nothing). The hooks ``on_startup``, ``on_shutdown``, ``before_command`` and
    ``after_command``, the ``panel``, ``state`` and the rest of the API are inherited from
    ``CLIApp``; a ``MenuItem`` tree can still be installed with ``set_menu``, which replaces the
    registered commands.
    """

    def __init__(
        self,
        name: str = "cli-interface",
        *,
        strict_shortcuts: bool = False,
        max_lines: int | None = _DEFAULT_MAX_LINES,
        quit_grace: float = _DEFAULT_QUIT_GRACE,
        **kwargs: Any,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be a str, not {type(name).__name__}")
        super().__init__(
            MenuItem(name),
            strict_shortcuts=strict_shortcuts,
            max_lines=max_lines,
            quit_grace=quit_grace,
            **kwargs,
        )
        self.title = name  # after Textual's own __init__ set it; the hello event reads it

    def command(
        self,
        path: str,
        *,
        key: str = "",
        cancellable: bool = False,
        description: str | None = None,
    ) -> Callable[[_F], _F]:
        """
        Decorator: register the function as the command at ``path`` (``"Group/Name"``; the
        groups are created) and return it unchanged. See ``add_command``.
        """
        _segments(path)  # fail here, not when the function is decorated

        def register(fn: _F) -> _F:
            self.add_command(path, fn, key=key, cancellable=cancellable, description=description)
            return fn

        return register

    def add_command(
        self,
        path: str,
        fn: Callable[..., Any],
        *,
        key: str = "",
        cancellable: bool = False,
        description: str | None = None,
    ) -> None:
        """
        Register ``fn`` as the command at ``path``: ``"/"``-separated, the last segment is the
        label and the others are submenus, created as needed. ``key`` is the shortcut.
        ``cancellable`` lets the first ``stop`` cancel it. ``description`` defaults to the
        first line of the docstring.

        ``ValueError`` if the path is empty or has an empty segment, is already taken, or goes
        through a command. A shortcut that is reserved or duplicated on its level is reported
        like ``CLIApp(menu)`` does: with ``strict_shortcuts`` it raises ``ValueError`` and
        nothing is registered, otherwise it warns (``ShortcutConflictWarning``, attributed to
        the caller). Once the app has started the menu is refreshed.
        """
        segments = _segments(path)
        if not callable(fn):
            raise TypeError(f"command {path!r}: fn must be callable, not {type(fn).__name__}")
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {type(key).__name__}")
        leaf = make_command_item(
            segments, fn, key=key, cancellable=cancellable,
            description=description or _first_doc_line(fn),
        )
        parent, depth = self._cmd_walk(segments)
        if depth == len(segments):
            raise ValueError(f"command path {path!r} is already registered")
        node: MenuItem = leaf
        for segment in reversed(segments[depth:-1]):
            node = MenuItem(segment, children=[node])
        parent.children.append(node)
        self._cmd_check(lambda: _remove(parent, node))

    def group(self, path: str, *, key: str = "", description: str = "") -> None:
        """
        Create the submenu at ``path`` (and the ones above it), or set the ``key`` and
        ``description`` of one that exists; an empty ``key`` or ``description`` leaves the
        current one. ``ValueError`` if the path is invalid or ends at, or goes through, a
        command. Shortcuts are checked as for ``add_command``.
        """
        segments = _segments(path)
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {type(key).__name__}")
        target, depth = self._cmd_walk(segments)
        if depth == len(segments):
            if _is_command(target):
                raise ValueError(f"cannot create group {path!r}: it is a command")
            old = (target.shortcut, target.description)
            target.shortcut = key or target.shortcut
            target.description = description or target.description

            def undo() -> None:
                target.shortcut, target.description = old
        else:
            node = MenuItem(segments[-1], shortcut=key, description=description)
            for segment in reversed(segments[depth:-1]):
                node = MenuItem(segment, children=[node])
            target.children.append(node)

            def undo() -> None:
                _remove(target, node)
        self._cmd_check(undo)

    def _cmd_walk(self, segments: tuple[str, ...]) -> tuple[MenuItem, int]:
        # The deepest existing item on the path and how many segments lead to it; all of them
        # when the whole path exists. ValueError when a command is in the way.
        node = self._state.root
        for depth, segment in enumerate(segments):
            child = _child(node, segment)
            if child is None:
                return node, depth
            if depth < len(segments) - 1 and _is_command(child):
                raise ValueError(
                    f"cannot add {'/'.join(segments)!r}: {'/'.join(segments[:depth + 1])!r} is a command"
                )
            node = child
        return node, len(segments)

    def _cmd_check(self, undo: Callable[[], None]) -> None:
        # Check the edited tree like set_menu does; on any exception (strict mode, or a warning
        # filter that turns the warning into an error) take the edit back and re-raise.
        queued = list(self._menu_warnings)
        try:
            self._validate_menu(self._state.root)
        except Exception:
            undo()
            self._menu_warnings[:] = queued
            raise
        self.post_ui(self.refresh_menu)  # does nothing before the app has started
