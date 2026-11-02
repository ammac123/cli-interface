import asyncio, sys
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")

# 1. Facade import
try:
    from cli_interface import CLIApp  # noqa
    print("1. facade import OK")
except ImportError as e:
    print("1. facade import FAILS:", e)

from textual.widgets import Input
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem

calls = []

# 2. Subclass overriding on_mount (calls super) and on_input_submitted (event.stop)
class Sub(CLIApp):
    def on_mount(self):
        calls.append("sub.on_mount")
        super().on_mount()
    def on_input_submitted(self, event: Input.Submitted):
        calls.append("sub.on_input_submitted")
        event.stop()   # whiteboard.py:95 believes this blocks CLIApp's handler

orig_mount = CLIApp.on_mount
def spy_mount(self):
    calls.append("CLIApp.on_mount")
    return orig_mount(self)
CLIApp.on_mount = spy_mount

async def main():
    quick_ran = []
    menu = MenuItem("Home", children=[
        MenuItem("Quick Run", shortcut="q", action=lambda: quick_ran.append(1)),
        MenuItem("Show", shortcut="s", action=lambda: None),
    ])
    app = Sub(menu)
    async with app.run_test() as pilot:
        await pilot.pause()
        print("2a. on_mount calls:", calls.count("CLIApp.on_mount"), "x CLIApp.on_mount")
        # 4. app.panel() as whiteboard.py:280 does
        try:
            app.panel()
        except TypeError as e:
            print("4. app.panel() ->", e)
        # 3. shortcut 'q' declared by consumer
        await pilot.press("q", "enter")
        await pilot.pause()
        print("2b. sub handler ran:", "sub.on_input_submitted" in calls,
              "| quick_run action ran:", bool(quick_ran),
              "| app exited (base handler ran despite event.stop):", app._exit_renderables is not None or app.return_code is not None)

asyncio.run(main())
