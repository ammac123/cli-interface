"""
``App``: a ``CLIApp`` whose menu is built from functions registered with ``@app.command``.
Re-exported by ``cli_interface``.
"""
from __future__ import annotations

import argparse
import dataclasses
import functools
import inspect
import logging
from collections.abc import Callable, Collection, Sequence
from typing import Any, Literal, TypeVar

from .app import _DEFAULT_MAX_LINES, _DEFAULT_QUIT_GRACE, CLIApp, _FormCommand, attach_logging
from .jobs import _asks_context, _signature
from .menu import MenuItem, _CommandItem, make_command_item
from .params import ParamSpec, specs_from_argparse, specs_from_dataclass, specs_from_signature
from .settings_menu import build_settings_group

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
    routine = inspect.isroutine(fn) and not isinstance(fn, functools.partial | functools.partialmethod)
    doc = inspect.getdoc(fn) if routine else None
    return doc.splitlines()[0].strip() if doc else ""


ParamsArg = Sequence[ParamSpec] | type | argparse.ArgumentParser | bool | None
_P = inspect.Parameter


def _confirm_text(confirm: bool | str, label: str) -> str | None:
    if confirm is False:
        return None
    if confirm is True:
        return f"Run {label}?"
    if not isinstance(confirm, str):
        raise TypeError(f"confirm must be a bool or a str, not {type(confirm).__name__}")
    if not confirm.strip():
        raise ValueError("confirm must not be blank")
    return confirm


def _form_params(fn: Callable[..., Any]) -> list[inspect.Parameter]:
    sig = _signature(fn)
    if sig is None:
        return []
    return [p for p in sig.parameters.values() if p.kind not in (_P.VAR_POSITIONAL, _P.VAR_KEYWORD) and not _asks_context(p)]


def _check_fits(fn: Callable[..., Any], names: Collection[str]) -> None:
    sig = _signature(fn)
    if sig is None:
        return
    takes_any = any(p.kind is _P.VAR_KEYWORD for p in sig.parameters.values())
    known = {p.name for p in _form_params(fn) if p.kind is not _P.POSITIONAL_ONLY}
    for p in _form_params(fn):
        if p.name not in names and p.default is _P.empty:
            raise ValueError(f"required parameter '{p.name}' has no field")
    for name in names:
        if name not in known and not takes_any:
            raise ValueError(f"field '{name}' is not a parameter of the function")


def _packed_param(fn: Callable[..., Any], what: str) -> str:
    candidates = _form_params(fn)
    if len(candidates) != 1 or candidates[0].kind is _P.POSITIONAL_ONLY:
        raise ValueError(f"params={what} needs exactly one keyword-capable parameter besides the Context to receive it")
    return candidates[0].name


def _resolve_params(
    fn: Callable[..., Any], params: ParamsArg,
) -> tuple[tuple[ParamSpec, ...], Literal["kwargs", "dataclass", "namespace"], Any, str]:
    # (specs, how they are delivered, what to pack them into, the parameter that receives the pack)
    if params is False:
        return (), "kwargs", None, ""
    if params is None or params is True:
        return tuple(specs_from_signature(fn, strict=params is True)), "kwargs", None, ""
    if isinstance(params, type):
        specs = tuple(specs_from_dataclass(params))
        return specs, "dataclass", params, _packed_param(fn, "a dataclass")
    if isinstance(params, argparse.ArgumentParser):
        return tuple(specs_from_argparse(params)), "namespace", None, _packed_param(fn, "a parser")
    if isinstance(params, Sequence) and not isinstance(params, str | bytes) and all(isinstance(p, ParamSpec) for p in params):
        specs = tuple(params)
        _check_fits(fn, [s.name for s in specs])
        return specs, "kwargs", None, ""
    raise TypeError(
        f"params must be None, a bool, a sequence of ParamSpec, a dataclass or an ArgumentParser, not {type(params).__name__}"
    )


def _remove(parent: MenuItem, node: MenuItem) -> None:
    parent.children[:] = [child for child in parent.children if child is not node]  # by identity


def _check_capture(loggers: Sequence[str | logging.Logger], level: int | str | None) -> tuple[logging.Logger, ...]:
    if isinstance(loggers, str | logging.Logger) or not isinstance(loggers, Sequence):
        raise TypeError("capture_loggers must be a sequence of logger names or Logger objects")
    found: list[logging.Logger] = []
    for entry in loggers:
        if isinstance(entry, str):
            found.append(logging.getLogger(entry))
        elif isinstance(entry, logging.Logger):
            found.append(entry)
        else:
            raise TypeError(f"capture_loggers entries must be str or Logger, not {type(entry).__name__}")
    if level is not None and not (
        (isinstance(level, int) and not isinstance(level, bool))
        or (isinstance(level, str) and level.upper() in logging.getLevelNamesMapping())
    ):
        raise ValueError(f"capture_level must be a logging level, not {level!r}")
    return tuple(found)


class App(CLIApp):
    """
    A ``CLIApp`` that builds its menu from decorated functions::

        app = App("My tool")

        @app.command("Run/Extract", key="e", cancellable=True)
        async def extract(ctx: Context) -> str: ...

        app.run()

    ``name`` is the root menu's label and the app's title; the keyword options are those of
    ``CLIApp`` (``strict_shortcuts``, ``max_lines``, ``quit_grace``) plus ``capture_loggers`` and
    ``capture_level`` (named loggers shown in the panel while the app runs), and the rest goes to
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
        capture_loggers: Sequence[str | logging.Logger] = (),
        capture_level: int | str | None = None,
        **kwargs: Any,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be a str, not {type(name).__name__}")
        loggers = _check_capture(capture_loggers, capture_level)
        super().__init__(
            MenuItem(name),
            strict_shortcuts=strict_shortcuts,
            max_lines=max_lines,
            quit_grace=quit_grace,
            **kwargs,
        )
        self.title = name  # after Textual's own __init__ set it; the hello event reads it
        self._capture_loggers = loggers
        self._capture_level = capture_level

    def _after_mount(self) -> None:
        for logger in self._capture_loggers:
            with self._attach_lock:
                attached = any(a.logger is logger and a.active for a in self._attachments)
            if not attached:  # on_mount can run twice
                attach_logging(self, logger, level=self._capture_level)

    def command(
        self,
        path: str,
        *,
        key: str = "",
        cancellable: bool = False,
        description: str | None = None,
        params: ParamsArg = None,
        confirm: bool | str = False,
    ) -> Callable[[_F], _F]:
        """
        Decorator: register the function as the command at ``path`` (``"Group/Name"``; the
        groups are created) and return it unchanged. See ``add_command``.
        """
        segments = _segments(path)  # fail here, not when the function is decorated
        _confirm_text(confirm, segments[-1])

        def register(fn: _F) -> _F:
            self.add_command(
                path, fn, key=key, cancellable=cancellable, description=description,
                params=params, confirm=confirm,
            )
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
        params: ParamsArg = None,
        confirm: bool | str = False,
    ) -> None:
        """
        Register ``fn`` as the command at ``path``: ``"/"``-separated, the last segment is the
        label and the others are submenus, created as needed. ``key`` is the shortcut.
        ``cancellable`` lets the first ``stop`` cancel it. ``description`` defaults to the
        first line of the docstring.

        ``params`` describes the arguments the user is asked for in a form before the command
        runs. ``None`` (default) derives them from the signature: a parameter of a supported
        type (``str``, ``int``, ``float``, ``bool``, ``Path``, ``Enum``, ``Literal``,
        ``list[...]``, optionally ``Optional`` or ``Annotated[..., Param(...)]``) becomes a
        field, and one of another type is skipped if it has a default; the Context parameter is
        never a field. ``True`` is the same but unsupported types raise ``ValueError``.
        ``False`` never shows a form. A dataclass class or an ``argparse.ArgumentParser`` gives
        the fields, and the function then takes one parameter (besides the Context) that
        receives an instance or a ``Namespace``. Otherwise the values arrive as keyword
        arguments. ``confirm`` asks yes or no before running (``True`` or your own text), after
        the form.

        ``ValueError`` if the path is empty or has an empty segment, is already taken, or goes
        through a command, or if ``params`` does not fit the function. A shortcut that is reserved
        or duplicated on its level is reported like ``CLIApp(menu)`` does: with
        ``strict_shortcuts`` it raises ``ValueError`` and nothing is registered, otherwise it
        warns (``ShortcutConflictWarning``, attributed to the caller). Once the app has started
        the menu is refreshed.
        """
        segments = _segments(path)
        if not callable(fn):
            raise TypeError(f"command {path!r}: fn must be callable, not {type(fn).__name__}")
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {type(key).__name__}")
        confirm_text = _confirm_text(confirm, segments[-1])
        try:
            specs, deliver, target, param = _resolve_params(fn, params)
        except ValueError as exc:
            raise ValueError(f"command {path!r}: {exc}") from exc
        leaf = make_command_item(
            segments, fn, key=key, cancellable=cancellable,
            description=description or _first_doc_line(fn),
            params=specs, deliver=deliver, confirm=confirm_text,
        )
        if deliver != "kwargs":
            leaf = _FormCommand(
                **{f.name: getattr(leaf, f.name) for f in dataclasses.fields(leaf)},
                pack_target=target, pack_param=param,
            )
        self._cmd_attach(path, segments, leaf, "command")

    def settings(
        self,
        path: str,
        model: Any,
        *,
        save: Callable[..., Any] | None = None,
        secret: Collection[str] = (),
        reset: bool = True,
        key: str = "",
    ) -> None:
        """
        Add a submenu at ``path`` that edits ``model``: a dataclass or pydantic v2 instance, or
        a function (taking nothing or a ``FormContext`` with ``state``) that returns one and is
        called each time the submenu is opened. Each field is an item showing its value; opening
        it asks for a new one in a form. A nested model is a submenu of its own, and a last item
        resets every field that has a default, after a confirmation.

        An edit or reset runs as a job (so it is refused while another job runs), changes the
        model in place and then calls ``save(ctx)`` (or ``save()``) on the job's thread. If
        ``save`` raises, the change is undone and the job ends in an error; ``None`` keeps the
        change in memory only. ``secret`` names fields (``"token"`` or ``"db.password"``; a
        ``Param(secret=True)`` or ``SecretStr`` field is secret too): they are masked in the menu
        and in the form, their values are redacted from all output, and an empty submit leaves the
        value unchanged. ``key`` is the submenu's shortcut and ``reset=False`` omits the reset
        item.

        ``TypeError`` for a class instead of an instance, a frozen dataclass, or an object that is
        neither a dataclass nor a pydantic v2 model; ``ValueError`` for a bad or taken path.
        """
        segments = _segments(path)
        if isinstance(secret, str) or not isinstance(secret, Collection):
            raise TypeError("secret must be a collection of field names")
        if save is not None and (not callable(save) or inspect.iscoroutinefunction(save)):
            raise TypeError("save must be a plain function")
        if not isinstance(key, str):
            raise TypeError(f"key must be a str, not {type(key).__name__}")
        group, secret_source = build_settings_group(self, segments, model, save, secret, reset, key)
        self._cmd_attach(path, segments, group, "settings")
        self.add_secret_source(secret_source)

    def _cmd_attach(self, path: str, segments: tuple[str, ...], leaf: MenuItem, what: str) -> None:
        parent, depth = self._cmd_walk(segments)
        if depth == len(segments):
            raise ValueError(f"{what} path {path!r} is already registered")
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
