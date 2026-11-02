import asyncio, sys, logging, io, contextlib, warnings
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
warnings.simplefilter("always")
from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem

lg = logging.getLogger("probe"); lg.setLevel(logging.INFO); lg.propagate = False
async def async_action():
    return 42
def sync_logs():
    lg.info("hello from UI thread")

async def main():
    menu = MenuItem("Home", children=[
        MenuItem("Async", shortcut="a", action=async_action),
        MenuItem("Logs",  shortcut="l", action=sync_logs),
    ])
    app = CLIApp(menu)
    lines = []
    async with app.run_test() as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        orig = app.panel.log
        app.panel.log = lambda m, lvl="INFO": (lines.append((lvl, m)), orig(m, lvl))
        await pilot.press("a"); await pilot.pause()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            await pilot.press("l"); await pilot.pause()
    for l in lines: print("panel:", l)
    print("stderr from handler:", err.getvalue().strip().splitlines()[-1:] )
asyncio.run(main())
