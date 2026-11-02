import sys
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem
from textual.widgets import RichLog

def panel_text(app):
    w = app.query_one("#display-panel", RichLog)
    return "\n".join(line.text for line in w.lines)

def make_app(*actions):
    root = MenuItem("Home", children=[MenuItem(label, shortcut=sc, action=fn) for (label, sc, fn) in actions] or [MenuItem("noop", action=lambda: None)])
    return CLIApp(root)
