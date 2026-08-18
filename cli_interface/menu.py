from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any


@dataclass
class MenuItem:
    label: str
    shortcut: str = ""
    description: str = ""
    children: list[MenuItem] = field(default_factory=list)
    action: Callable[[], Any] | None = None
    editable: bool = False
    current_value: Any = None

    @property
    def is_leaf(self) -> bool:
        return not self.children


class MenuState:
    """Tracks navigation position within the menu tree."""

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
        for child in self.current_menu.children:
            if child.shortcut.lower() == key.lower():
                return child
        return None
