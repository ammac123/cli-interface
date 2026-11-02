"""Probe Textual dispatch semantics as used by whiteboard.NextGenApp (no repo changes)."""
import asyncio, sys
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from textual.widgets import Input
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem

calls = {"base_mount": 0, "exit_called": 0, "base_submit": 0}

orig_mount = CLIApp.on_mount
def counting_mount(self):
    calls["base_mount"] += 1
    orig_mount(self)
CLIApp.on_mount = counting_mount

orig_submit = CLIApp.on_input_submitted
def counting_submit(self, event):
    calls["base_submit"] += 1
    orig_submit(self, event)
CLIApp.on_input_submitted = counting_submit

class Sub(CLIApp):
    _is_extracting = True
    def on_mount(self):
        super().on_mount()
    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._is_extracting:
            return
        event.stop()
        event.input.clear()
    def exit(self, *a, **k):
        calls["exit_called"] += 1
        return super().exit(*a, **k)

async def main():
    menu = MenuItem("Home", children=[MenuItem("Run", shortcut="r", action=lambda: None)])
    app = Sub(menu)
    async with app.run_test() as pilot:
        await pilot.pause()
        print("CLIApp.on_mount calls:", calls["base_mount"])
        await pilot.press("e", "x", "i", "t", "enter")
        await pilot.pause()
    print("CLIApp.on_input_submitted calls after typing 'exit' while extracting:", calls["base_submit"])
    print("exit() calls:", calls["exit_called"])
    # panel() bug
    try:
        app2 = CLIApp(menu)
        async with app2.run_test() as p2:
            app2.panel()
    except TypeError as e:
        print("app.panel():", e)

asyncio.run(main())
