"""The menu tree behind ``App.settings``: one leaf per field, a submenu per nested model, a reset leaf."""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Collection
from typing import Any

from .app import CLIApp, _FormCommand
from .context import Context
from .menu import _SettingsGroup
from .params import FormContext, call_with_ctx
from .settings import Field, Group, _is_model, describe, format_value, get_value, reset_defaults, set_value

_RESET_LABEL = "Reset to defaults"


class _Source:
    """The model instance, or a factory that is called each time the settings are entered."""

    def __init__(self, model: Any) -> None:
        self.factory: Callable[..., Any] | None = None if _is_model(model) else model
        self.obj: Any = model if self.factory is None else None
        self.secret_names: list[str] = []


def _roll_back(obj: Any, old: dict[str, Any]) -> None:
    for name, value in old.items():
        set_value(obj, name, value)


def _edit_leaf(
    source: _Source, field: Field, trail: tuple[str, ...], save: Callable[..., Any] | None,
) -> _FormCommand:
    name = field.name
    spec = dataclasses.replace(field.spec, name="value", optional=field.spec.optional or field.secret)

    def edit(ctx: Context, value: Any) -> None:
        obj = source.obj
        if field.secret and value is None:  # an empty submit keeps the secret
            return
        old = get_value(obj, name)
        if value == old:
            return
        set_value(obj, name, value)
        if save is not None:
            try:
                call_with_ctx(save, ctx)
            except BaseException:
                _roll_back(obj, {name: old})
                raise

    return _FormCommand(
        spec.label, description=spec.help, action=edit, secret=field.secret,
        current_value=lambda: format_value(get_value(source.obj, name)),
        command_path=(*trail, spec.label), params=(spec,), job_label=f"Set {spec.label}",
        initial=None if field.secret else lambda: {"value": get_value(source.obj, name)},
    )


def _reset_leaf(
    source: _Source, secret: Collection[str], save: Callable[..., Any] | None, trail: tuple[str, ...],
) -> _FormCommand:
    def reset(ctx: Context) -> None:
        obj = source.obj
        before = {f.name: get_value(obj, f.name) for f in describe(obj, secret) if isinstance(f, Field)}
        changed = reset_defaults(obj, secret)
        if changed and save is not None:
            try:
                call_with_ctx(save, ctx)
            except BaseException:
                _roll_back(obj, {n: before[n] for n in changed})
                raise

    return _FormCommand(
        _RESET_LABEL, action=reset, command_path=(*trail, _RESET_LABEL),
        confirm=f"Reset all {trail[-1]} settings to their defaults?",
    )


def _populate(
    root: _SettingsGroup, source: _Source, trail: tuple[str, ...],
    save: Callable[..., Any] | None, secret: Collection[str], reset: bool,
) -> None:
    items = describe(source.obj, secret)
    top = _SettingsGroup("")
    groups: dict[str, tuple[_SettingsGroup, tuple[str, ...]]] = {"": (top, trail)}
    names: list[str] = []
    for item in items:
        parent, parent_trail = groups[item.name.rpartition(".")[0]]
        if isinstance(item, Group):
            sub = _SettingsGroup(item.label)
            groups[item.name] = (sub, (*parent_trail, item.label))
            parent.children.append(sub)
        else:
            parent.children.append(_edit_leaf(source, item, parent_trail, save))
            if item.secret:
                names.append(item.name)
    if reset:
        top.children.append(_reset_leaf(source, secret, save, trail))
    root.children[:] = top.children
    source.secret_names = names


def build_settings_group(
    app: CLIApp,
    segments: tuple[str, ...],
    model: Any,
    save: Callable[..., Any] | None,
    secret: Collection[str],
    reset: bool,
    key: str,
) -> tuple[_SettingsGroup, Callable[[], list[str]]]:
    """
    The group for ``app.settings`` and the function that lists the current values of its secret
    fields. An instance is described now (``TypeError`` if it cannot be edited); a factory is
    called, and the group rebuilt, each time the group is entered.
    """
    if isinstance(model, type):
        raise TypeError(f"settings model must be an instance, not the class {model.__name__}")
    source = _Source(model)
    if source.factory is not None and not callable(source.factory):
        raise TypeError(
            f"settings model must be a dataclass or pydantic v2 instance, or a function returning one, "
            f"not {type(model).__name__}"
        )
    group = _SettingsGroup(segments[-1], shortcut=key)

    def populate() -> None:
        _populate(group, source, segments, save, secret, reset)

    if source.factory is None:
        populate()
    else:
        factory = source.factory

        def on_enter() -> bool:
            try:
                source.obj = call_with_ctx(factory, FormContext(state=app.state))
                populate()
            except Exception as exc:
                app.panel.log(f"Settings unavailable: {exc}", "WARNING")
                return False
            return True

        group.on_enter = on_enter

    def secret_strings() -> list[str]:
        obj = source.obj
        found: list[str] = []
        if obj is None:
            return found
        for name in source.secret_names:
            try:
                value = get_value(obj, name)
            except Exception:
                continue
            items = value if isinstance(value, list | tuple | set | frozenset) else [value]
            found.extend(i for i in items if isinstance(i, str) and i)
        return found

    return group, secret_strings
