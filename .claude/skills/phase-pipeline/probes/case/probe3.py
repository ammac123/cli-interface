import asyncio, io, logging, sys, contextlib, threading
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem

lg = logging.getLogger("probe3"); lg.setLevel(logging.INFO)
errs = []
class App2(CLIApp):
    def on_mount(self):
        try:
            self.call_from_thread(lambda: None)
        except RuntimeError as e:
            errs.append(str(e))
        lg.info("from on_mount (UI thread)")

async def main():
    app = App2(MenuItem("Home", children=[MenuItem("x", shortcut="x", action=lambda: lg.info("from menu action"))]))
    attach_logging(app, lg, exclusive=True)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("x")
            await pilot.pause()
    print("direct call_from_thread on UI thread:", errs)
    print("logging errors on stderr:", err.getvalue().count("--- Logging error ---"))
asyncio.run(main())
