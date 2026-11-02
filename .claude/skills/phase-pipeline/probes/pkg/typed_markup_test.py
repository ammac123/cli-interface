import asyncio
from cli_interface.app import CLIApp
from cli_interface.menu import MenuItem

async def main():
    app = CLIApp(MenuItem("Home", children=[MenuItem("A", shortcut="a", action=lambda: None)]))
    try:
        async with app.run_test() as pilot:
            await pilot.press("[", "/", "x", "]", "enter")
            await pilot.pause()
    except Exception as exc:
        print("crashed:", type(exc).__name__, str(exc)[:100])
    print("return_code =", app.return_code)

asyncio.run(main())
