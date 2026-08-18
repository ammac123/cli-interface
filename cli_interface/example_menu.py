import logging
from .menu import MenuItem

log = logging.getLogger(__name__)


def build_example_menu() -> MenuItem:
    def set_volume(level: int):
        def _action():
            log.info("Volume set to %d", level)
            return level
        return _action

    def toggle_fullscreen():
        log.info("Toggled fullscreen")

    def reset_all():
        log.warning("All settings reset to defaults")

    return MenuItem(
        label="Home",
        children=[
            MenuItem(
                label="Audio",
                shortcut="a",
                description="Audio settings",
                children=[
                    MenuItem("Volume Low", shortcut="1", action=set_volume(25)),
                    MenuItem("Volume Medium", shortcut="2", action=set_volume(50)),
                    MenuItem("Volume High", shortcut="3", action=set_volume(100)),
                ],
            ),
            MenuItem(
                label="Display",
                shortcut="d",
                description="Display settings",
                children=[
                    MenuItem("Toggle Fullscreen", shortcut="f", action=toggle_fullscreen),
                    MenuItem(
                        label="Resolution",
                        shortcut="r",
                        children=[
                            MenuItem("1080p", shortcut="1", action=lambda: log.info("Resolution: 1080p")),
                            MenuItem("1440p", shortcut="2", action=lambda: log.info("Resolution: 1440p")),
                            MenuItem("4K", shortcut="3", action=lambda: log.info("Resolution: 4K")),
                        ],
                    ),
                ],
            ),
            MenuItem("Reset All", shortcut="x", action=reset_all),
        ],
    )
