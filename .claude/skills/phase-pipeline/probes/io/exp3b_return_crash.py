"""Exp3b: action return value / exception message containing a Rich closing tag."""
import asyncio, logging, threading
from common import make_app, panel_text, attach_logging

def ret_markup(): return "copied 3 files to out/[/tmp]"
def raise_markup(): raise ValueError("bad key [/x] in config")
log = logging.getLogger("exp3b"); log.propagate = False; log.setLevel(logging.INFO)

async def run(key, fn):
    app = make_app(("Act", key, fn))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press(key); await pilot.pause(); await pilot.pause()
        alive = app.is_running
    print(f"{fn.__name__:13s} -> app alive after action: {alive}; return_code={app.return_code}; exc={type(app._exception).__name__ if app._exception else None}")

async def bg_markup():
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        attach_logging(app, log)
        t = threading.Thread(target=lambda: log.info("path is out/[/tmp] ok")); t.start()
        while t.is_alive(): await asyncio.sleep(0.01)
        await pilot.pause()
        print("bg-thread record with '[/tmp]' shown in panel:", "path is out" in panel_text(app), "| app alive:", app.is_running)

async def main():
    await run("r", ret_markup)
    await run("e", raise_markup)
    await bg_markup()
asyncio.run(main())
