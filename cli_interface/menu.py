"""
Menu model: ``MenuItem`` (a node in the menu tree), ``MenuState`` (navigation
position), and the shortcut rules (``RESERVED_COMMANDS``, ``find_shortcut_conflicts``).

``MenuItem``, ``RESERVED_COMMANDS`` and ``find_shortcut_conflicts`` are public and
re-exported by ``cli_interface``. The rest (``MenuState``, ``item_label``,
``item_value``, ``reserved_action``, ``normalize_shortcut``, ``make_nav_cell``) is
internal to the package.
"""
from __future__ import annotations
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, fields
from reprlib import recursive_repr
from types import MappingProxyType
from typing import Any, Literal

_log = logging.getLogger(__name__)


@dataclass(repr=False)
class MenuItem:
    """
    One node in the menu tree. An item with ``children`` is a submenu; an item
    without is a leaf. Every string field is rendered literally (no markup).

    ``label``         — text shown in the nav bar and the breadcrumb. May be a
                        no-argument callable returning the text (see below).
    ``shortcut``      — what the user types, followed by Enter, to activate the
                        item. Case-insensitive and may be several characters.
                        Empty means no shortcut. Leading and trailing whitespace is
                        ignored, so a whitespace-only shortcut means no shortcut.
                        Reserved and duplicate shortcuts are reported by
                        ``find_shortcut_conflicts``.
    ``description``   — free-form text. The UI does not display it.
    ``children``      — the submenu entries. Leave empty for a leaf.
    ``action``        — callable run when a leaf is activated. It is called with
                        no arguments, or with the prompted string when ``prompt``
                        is set. It runs synchronously on the UI thread. An exception
                        is caught and shown as an ERROR line. A return value other
                        than ``None`` is shown after the ``Executed:`` line (unless
                        ``secret`` is set).
    ``prompt``        — if set, a modal input dialog with this text opens first and
                        the typed string (possibly empty) is passed to ``action``.
                        Cancelling with Esc skips the action. The typed value is
                        never echoed by the app.
    ``current_value`` — optional value shown after the label as ``(value)`` in the
                        nav bar. Display only: the app never changes it. May be a
                        no-argument callable; ``None`` (or a callable returning
                        ``None``) shows no value. Shown as ``••••`` when ``secret``
                        is set; a callable is then never called.
    ``secret``        — masks the prompt input (``Input(password=True)``) and
                        ``current_value``, hides the action's return value, and
                        redacts the typed value from an exception message (best
                        effort). ``repr()`` prints ``current_value`` as ``'***'``.
                        An action that logs the value itself is not covered.

    A callable ``label`` or ``current_value`` takes no arguments and is called on the UI
    thread: once per item for each repaint of the nav bar, and (label only) each time the
    breadcrumb, an ``Executed:`` / ``Error in`` line, a prompt title or a shortcut-conflict
    message is built. Keep it cheap and free of side effects. The result goes through
    ``str()``; if the call (or the ``str()``) raises an ``Exception``, ``<error>`` is shown
    instead and the failure is logged at DEBUG on ``cli_interface.menu``. The label in an
    ``Executed:`` line is read before the action runs.
    """

    label: str | Callable[[], str]
    shortcut: str = ""
    description: str = ""
    children: list[MenuItem] = field(default_factory=list)
    action: Callable[..., Any] | None = None
    prompt: str | None = None
    current_value: Any = None
    secret: bool = False

    @recursive_repr()
    def __repr__(self) -> str:
        parts = []
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "current_value" and self.secret and value is not None:
                value = "***"
            parts.append(f"{f.name}={value!r}")
        return f"{self.__class__.__qualname__}({', '.join(parts)})"

    @property
    def is_leaf(self) -> bool:
        """True if the item has no ``children``: activating it runs its ``action``."""
        return not self.children


ReservedAction = Literal["quit", "back", "clear", "help"]

# Typed commands handled by the app itself. They match case-insensitively (surrounding
# whitespace is ignored) and always win over a consumer shortcut; the item stays reachable
# by arrow keys, Enter, or its position number. The Exit and Back cells display shortcuts
# from this set so that what they show is what works when typed; keep any new sentinel
# shortcut in it.
RESERVED_ACTIONS: Mapping[str, ReservedAction] = MappingProxyType({
    "q": "quit", "quit": "quit", "exit": "quit",
    "b": "back", "back": "back",
    "clear": "clear",
    "help": "help", "?": "help",
})
RESERVED_COMMANDS: frozenset[str] = frozenset(RESERVED_ACTIONS)

_EXIT_SHORTCUT = "q"
_BACK_SHORTCUT = "b"


def reserved_action(text: str) -> ReservedAction | None:
    """
    The action a typed reserved command triggers (``"quit"``, ``"back"``, ``"clear"`` or
    ``"help"``), or ``None`` if ``text`` is not one. Case-insensitive; surrounding
    whitespace is ignored.
    """
    return RESERVED_ACTIONS.get(text.strip().lower())


def normalize_shortcut(shortcut: str) -> str:
    """
    The form in which shortcuts are compared and matched: surrounding whitespace
    stripped and lower-cased. ``""`` (also from a whitespace-only shortcut) means no
    shortcut. Used by the conflict check, ``MenuState.select_by_shortcut`` and the nav bar.
    """
    return shortcut.strip().lower()


def item_label(item: MenuItem) -> str:
    """
    The label as text. A callable label is called with no arguments and the result goes
    through ``str()``. An ``Exception`` from either is logged at DEBUG on
    ``cli_interface.menu`` and yields ``"<error>"``; a ``BaseException`` propagates.
    """
    try:
        label = item.label
        return str(label() if callable(label) else label)
    except Exception:
        _log.debug("menu item label raised", exc_info=True)
        return "<error>"


def item_value(item: MenuItem) -> Any:
    """
    ``current_value``, called with no arguments if it is callable. ``None`` means no value.
    An ``Exception`` from the callable is logged at DEBUG on ``cli_interface.menu`` and
    yields ``"<error>"``; a ``BaseException`` propagates.

    This does not mask secrets and does not look at ``item.secret``: the caller must
    check it first and neither call nor show the value of a secret item (the nav bar's
    ``_value_text`` does).
    """
    value = item.current_value
    if not callable(value):
        return value
    try:
        return value()
    except Exception:
        _log.debug("menu item current_value raised", exc_info=True)
        return "<error>"


@dataclass(repr=False)
class _NavCell(MenuItem):
    """The Exit and Back cells. Detect with ``isinstance``, never by comparing fields."""

    kind: Literal["exit", "back"] = "exit"


def make_nav_cell(kind: Literal["exit", "back"]) -> _NavCell:
    """
    Build the Exit (shortcut ``q``) or Back (shortcut ``b``) cell that the app appends to
    each menu level. Both shortcuts are reserved commands, so what the cell shows is what
    works when typed. ``ValueError`` for any other ``kind``.
    """
    if kind == "exit":
        return _NavCell("Exit", shortcut=_EXIT_SHORTCUT, kind="exit")
    if kind == "back":
        return _NavCell("Back", shortcut=_BACK_SHORTCUT, kind="back")
    raise ValueError(f"unknown nav cell kind: {kind!r}")


def find_shortcut_conflicts(root: MenuItem) -> list[str]:
    """
    Describe shortcuts that are reserved or duplicated within a menu level.

    Walks the whole tree (cycle-safe) and returns one human-readable string per
    problem; an empty list means the tree is clean. Shortcuts are compared
    case-insensitively and with surrounding whitespace ignored, empty shortcuts are
    skipped, and the same shortcut on different levels is fine. Not detected: a
    numeric shortcut that shadows a position number (``"2"`` on the first item).
    ``CLIApp`` calls this when it is built and again on every ``set_menu`` and
    ``refresh_menu``.
    """
    problems: list[str] = []
    visited: set[int] = set()

    def walk(menu: MenuItem, trail: list[MenuItem]) -> None:
        if id(menu) in visited:
            return
        visited.add(id(menu))
        if not menu.children:
            return
        by_key: dict[str, list[MenuItem]] = {}
        for child in menu.children:
            key = normalize_shortcut(child.shortcut)
            if key:
                by_key.setdefault(key, []).append(child)
        path = ""
        for key, items in by_key.items():
            if key not in RESERVED_COMMANDS and len(items) < 2:
                continue
            path = path or " > ".join(item_label(m) for m in trail)
            if key in RESERVED_COMMANDS:
                for item in items:
                    problems.append(
                        f"{path}: shortcut {key!r} on {item_label(item)!r} is a reserved "
                        f"command and will never reach this item"
                    )
            else:
                labels = ", ".join(repr(item_label(item)) for item in items)
                problems.append(
                    f"{path}: shortcut {key!r} is used by {labels}; "
                    f"only the first is reachable by shortcut"
                )
        for child in menu.children:
            walk(child, [*trail, child])

    walk(root, [root])
    return problems


class MenuState:
    """
    Tracks navigation position within the menu tree.

    Holds a stack of ``(menu, selected_index)`` pairs, starting at ``root``.
    ``CLIApp`` owns one; the class is internal and the stack itself is private.
    """

    def __init__(self, root: MenuItem) -> None:
        self.root = root
        self._stack: list[tuple[MenuItem, int]] = [(root, 0)]

    def set_root(self, root: MenuItem) -> None:
        """Replace the whole tree with ``root`` and go to it: the stack becomes ``[(root, 0)]``."""
        self.root = root
        self._stack = [(root, 0)]

    def home(self) -> bool:
        """Pop to the root level, keeping the root's selection. Returns True if the stack changed."""
        if len(self._stack) <= 1:
            return False
        del self._stack[1:]
        return True

    def prune(self) -> bool:
        """
        Bring the stack back in line with the tree after it was edited in place. Walking
        down from the root, keep a level only while it is still one of its parent's
        children (by identity) and still has children; drop it and everything below
        otherwise. The root is always kept. Each remaining selection is clamped to its
        level, not reset. Returns True if the stack shrank.
        """
        keep = 1
        while keep < len(self._stack):
            parent = self._stack[keep - 1][0]
            menu = self._stack[keep][0]
            if not menu.children or not any(child is menu for child in parent.children):
                break
            keep += 1
        shrank = keep < len(self._stack)
        del self._stack[keep:]
        self._stack = [
            (menu, max(0, min(index, len(menu.children) - 1))) for menu, index in self._stack
        ]
        return shrank

    @property
    def current_menu(self) -> MenuItem:
        """The menu whose children are shown: the top of the stack."""
        return self._stack[-1][0]

    @property
    def selected_index(self) -> int:
        """The selected child of ``current_menu``. Assigning clamps it to the child list."""
        return self._stack[-1][1]

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        item, _ = self._stack[-1]
        clamped = max(0, min(value, len(item.children) - 1))
        self._stack[-1] = (item, clamped)

    @property
    def selected_item(self) -> MenuItem | None:
        """The selected child of ``current_menu``, or None if it has no children."""
        children = self.current_menu.children
        if not children:
            return None
        return children[self.selected_index]

    @property
    def breadcrumb(self) -> list[str]:
        """Labels from the root to the current menu."""
        return [item_label(item) for item, _ in self._stack]

    def enter(self) -> bool:
        """Navigate into the selected item. Returns True if navigation happened."""
        item = self.selected_item
        if item is None or item.is_leaf:
            return False
        self._stack.append((item, 0))
        return True

    def back(self) -> bool:
        """Navigate up one level. Returns True if navigation happened."""
        if len(self._stack) <= 1:
            return False
        self._stack.pop()
        return True

    def move(self, delta: int) -> None:
        """Move the selection by ``delta``, clamped. (``CLIApp`` tracks its own highlight and does not use this.)"""
        self.selected_index = self.selected_index + delta

    def select_by_shortcut(self, key: str) -> MenuItem | None:
        """The first child of the current menu whose shortcut equals ``key`` (case-insensitive, whitespace-trimmed)."""
        wanted = normalize_shortcut(key)
        if not wanted:
            return None
        for child in self.current_menu.children:
            if normalize_shortcut(child.shortcut) == wanted:
                return child
        return None
