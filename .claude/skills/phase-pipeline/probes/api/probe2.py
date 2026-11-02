import asyncio, sys
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from textual.widgets import Input
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem

log = []
orig = CLIApp.on_input_submitted
def spy(self, event):
    log.append(("base", event.value))
    return orig(self, event)
CLIApp.on_input_submitted = spy
orig_exit = CLIApp.exit
def spy_exit(self, *a, **k):
    log.append(("exit",))
    return orig_exit(self, *a, **k)
CLIApp.exit = spy_exit

class Sub(CLIApp):
    busy = True
    def on_input_submitted(self, event: Input.Submitted):
        if not self.busy: return
        log.append(("sub", event.value))
        event.stop()
        event.input.clear()

async def scenario(cls, keys, label):
    log.clear()
    ran = []
    menu = MenuItem("Home", children=[MenuItem("Quick Run", shortcut="q", action=lambda: ran.append(1))])
    app = cls(menu)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press(*keys)
        await pilot.pause()
    print(f"{label}: log={log} quick_run_action_ran={bool(ran)}")

async def main():
    await scenario(CLIApp, ["q", "enter"], "A plain CLIApp, item shortcut 'q'")
    await scenario(Sub, ["s","t","o","p","enter"], "B subclass busy, types 'stop'")
    await scenario(Sub, ["q","enter"], "C subclass busy, types 'q'")
asyncio.run(main())
