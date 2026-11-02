"""
Run the demo menu. The supported launcher is ``python -m examples.main`` from the
repository root (running this file directly fails: it uses relative imports). To go through
the console script instead: ``cli-interface examples.example_menu:build_menu``.
"""
from __future__ import annotations

from cli_interface import CLIApp, MenuItem

from .example_menu import build_menu

# Deliberately no logging.basicConfig here: configuring the root logger is the host's
# decision, and importing or running this demo must not change it.


def main() -> int:
    """Show the demo menu and return the app's exit code. Needs a real terminal."""
    # build_menu needs the app (its actions use the panel and spinner), so the app is built
    # first with a placeholder root and the real menu is set before it runs.
    app = CLIApp(MenuItem("Home"))
    app.set_menu(build_menu(app))
    app.run()
    return app.return_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
