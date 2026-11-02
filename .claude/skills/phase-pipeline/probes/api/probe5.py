import asyncio, sys, threading
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem

def foreign_sync():
    print("PRINTED-FROM-ACTION")
def foreign_thread():
    threading.Thread(target=lambda: print("PRINTED-FROM-THREAD")).start()

async def main():
    menu = MenuItem("Home", children=[
        MenuItem("P", shortcut="p", action=foreign_sync),
        MenuItem("T", shortcut="t", action=foreign_thread),
    ])
    app = CLIApp(menu)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("p", "enter"); await pilot.pause()
        await pilot.press("t", "enter"); await pilot.pause(0.3)
        rl = app.query_one("#display-panel")
        text = "\n".join(str(l.text) for l in rl.lines)
        print("panel contains action print:", "PRINTED-FROM-ACTION" in text,
              "| thread print:", "PRINTED-FROM-THREAD" in text)
asyncio.run(main())
