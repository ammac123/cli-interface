# BASELINE REPRO (commit fdb8069): this probe describes behaviour from before Phase 0 and is expected to
# "fail" or print different results now. The maintained regression tests are in tests/ (see tests/test_regression.py).
import asyncio, sys, logging, io, contextlib, warnings
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
warnings.simplefilter("always")
from textual.widgets import Input
from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem

hits = []
orig_on_key = CLIApp.on_key
def spy_on_key(self, event):
    hits.append(event.character); return orig_on_key(self, event)
CLIApp.on_key = spy_on_key

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
    err = io.StringIO()
    async with app.run_test() as pilot:
        await pilot.pause()
        attach_logging(app, lg)
        p = app.panel
        orig = p.log
        p.log = lambda m, lvl="INFO": (lines.append((lvl, m)), orig(m, lvl))
        await pilot.press("a"); await pilot.pause()
        print("on_key hits:", hits, "| input value after 'a':", repr(app.query_one('#command-input', Input).value))
        await pilot.press("enter"); await pilot.pause()
        with contextlib.redirect_stderr(err):
            await pilot.press("l", "enter"); await pilot.pause()
    for l in lines: print("panel:", l)
    print("stderr:", [l for l in err.getvalue().splitlines() if "Error" in l or "error" in l][:3])
asyncio.run(main())
