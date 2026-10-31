"""
Menu model: ``MenuItem`` (a node in the menu tree), ``MenuState`` (navigation
position), and the shortcut rules (``RESERVED_COMMANDS``, ``find_shortcut_conflicts``).
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields
from reprlib import recursive_repr
from typing import Callable, Any


@dataclass(repr=False)
class MenuItem:
    """
    One node in the menu tree. An item with ``children`` is a submenu; an item
    without is a leaf. Every string field is rendered literally (no markup).

    ``label``         — text shown in the nav bar and the breadcrumb.
    ``shortcut``      — what the user types, followed by Enter, to activate the
                        item. Case-insensitive and may be several characters.
                        Empty means no shortcut. It must not start or end with
                        whitespace: typed input is stripped, so such a shortcut is
                        displayed but never matches. Reserved and duplicate
                        shortcuts are reported by ``find_shortcut_conflicts``.
    ``description``   — free-form text. The UI does not display it. The values
                        ``"__back__"`` and ``"__exit__"`` are used internally by
                        the Back and Exit cells; do not use them.
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
                        nav bar. Display only: the app never changes it.
                        Shown as ``••••`` when ``secret`` is set.
    ``secret``        — masks the prompt input (``Input(password=True)``) and
                        ``current_value``, hides the action's return value, and
                        redacts the typed value from an exception message (best
                        effort). ``repr()`` prints ``current_value`` as ``'***'``.
                        An action that logs the value itself is not covered.
    """

    label: str
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
        return not self.children


# Typed commands handled by the app itself. They match case-insensitively and always
# win over a consumer shortcut; the item stays reachable by arrow keys, Enter, or its
# position number. The Exit ("q") and Back ("b") cells display shortcuts from this set so
# that what they show is what works when typed; keep any new sentinel shortcut in it.
RESERVED_COMMANDS: frozenset[str] = frozenset(
    {"q", "quit", "exit", "b", "back", "clear", "help", "?"}
)


def find_shortcut_conflicts(root: MenuItem) -> list[str]:
    """
    Describe shortcuts that are reserved or duplicated within a menu level.

    Walks the whole tree (cycle-safe) and returns one human-readable string per
    problem; an empty list means the tree is clean. Shortcuts are compared
    case-insensitively, empty shortcuts are skipped, and the same shortcut on
    different levels is fine. Not detected: a shortcut with leading or trailing
    whitespace, and a numeric shortcut that shadows a position number (``"2"`` on
    the first item). ``CLIApp`` calls this at construction.
    """
    problems: list[str] = []
    visited: set[int] = set()

    def walk(menu: MenuItem, trail: list[str]) -> None:
        if id(menu) in visited:
            return
        visited.add(id(menu))
        if not menu.children:
            return
        path = " > ".join(trail)
        by_key: dict[str, list[MenuItem]] = {}
        for child in menu.children:
            if child.shortcut:
                by_key.setdefault(child.shortcut.lower(), []).append(child)
        for key, items in by_key.items():
            if key in RESERVED_COMMANDS:
                for item in items:
                    problems.append(
                        f"{path}: shortcut {key!r} on {item.label!r} is a reserved "
                        f"command and will never reach this item"
                    )
            elif len(items) > 1:
                labels = ", ".join(repr(item.label) for item in items)
                problems.append(
                    f"{path}: shortcut {key!r} is used by {labels}; "
                    f"only the first is reachable by shortcut"
                )
        for child in menu.children:
            walk(child, trail + [child.label])

    walk(root, [root.label])
    return problems


class MenuState:
    """
    Tracks navigation position within the menu tree.

    Holds a stack of ``(menu, selected_index)`` pairs, starting at ``root``.
    ``CLIApp`` owns one; the stack itself is internal.
    """

    def __init__(self, root: MenuItem) -> None:
        self.root = root
        self._stack: list[tuple[MenuItem, int]] = [(root, 0)]

    @property
    def current_menu(self) -> MenuItem:
        return self._stack[-1][0]

    @property
    def selected_index(self) -> int:
        return self._stack[-1][1]

    @selected_index.setter
    def selected_index(self, value: int) -> None:
        item, _ = self._stack[-1]
        clamped = max(0, min(value, len(item.children) - 1))
        self._stack[-1] = (item, clamped)

    @property
    def selected_item(self) -> MenuItem | None:
        children = self.current_menu.children
        if not children:
            return None
        return children[self.selected_index]

    @property
    def breadcrumb(self) -> list[str]:
        """Labels from the root to the current menu."""
        return [item.label for item, _ in self._stack]

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
        self.selected_index = self.selected_index + delta

    def select_by_shortcut(self, key: str) -> MenuItem | None:
        """The first child of the current menu whose shortcut equals ``key`` (case-insensitive, no stripping)."""
        for child in self.current_menu.children:
            if child.shortcut.lower() == key.lower():
                return child
        return None
