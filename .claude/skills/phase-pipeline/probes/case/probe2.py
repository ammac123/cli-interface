"""Probe: logging from the UI thread via attach_logging; asyncio.Event cross-loop reuse."""
import asyncio, io, logging, sys, contextlib, threading
sys.path.insert(0, "/Users/andrewmacleod/workspace/cli_interface")
from cli_interface.app import CLIApp, attach_logging
from cli_interface.menu import MenuItem

lg = logging.getLogger("probe")
lg.setLevel(logging.INFO)

async def main():
    app = CLIApp(MenuItem("Home"))
    attach_logging(app, lg, exclusive=True)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        lg.info("logged before app.run")
        async with app.run_test() as pilot:
            lg.info("logged from UI thread")
            await pilot.pause()
    print("stderr contains 'Logging error':", err.getvalue().count("--- Logging error ---"))
    print([l for l in err.getvalue().splitlines() if l.startswith("RuntimeError")])

asyncio.run(main())

# asyncio.Event created outside loop, waited in two different asyncio.run loops (as two extraction runs would)
ev = asyncio.Event()
async def waiter():
    try:
        await asyncio.wait_for(ev.wait(), 0.05)
    except TimeoutError:
        return "timeout"
def run_in_thread():
    return asyncio.run(waiter())
for i in range(2):
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("r", (lambda: (run_in_thread()))()) if True else None)
    try:
        t.start(); t.join()
    except Exception as e:
        print(e)
    print("run", i+1, "->", out.get("r"))
