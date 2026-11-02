"""Exp1: TUILogHandler from main thread vs background thread; handler leak after exit."""
import asyncio, io, logging, sys, threading, time
from common import make_app, panel_text, attach_logging

log = logging.getLogger("exp1")
log.setLevel(logging.DEBUG)
log.propagate = False

async def main():
    app = make_app(("Act", "a", lambda: log.warning("FROM-ACTION-MAINTHREAD")))
    errbuf = io.StringIO()
    async with app.run_test(size=(120, 40)) as pilot:
        attach_logging(app, log)
        # capture what logging.handleError prints (headless -> original stderr)
        real_err = app._original_stderr
        app._original_stderr = errbuf
        # 1) log directly on the app thread (test coroutine runs on app loop)
        log.info("FROM-MAIN-THREAD")
        # 2) log via a menu action (main thread)
        await pilot.press("a"); await pilot.pause()
        # 3) log from a background thread
        t = threading.Thread(target=lambda: log.info("FROM-BG-THREAD")); t.start()
        while t.is_alive():
            await asyncio.sleep(0.01)
        await pilot.pause()
        txt = panel_text(app)
        app._original_stderr = real_err
        print("main-thread record shown:   ", "FROM-MAIN-THREAD" in txt)
        print("action record shown:        ", "FROM-ACTION-MAINTHREAD" in txt)
        print("bg-thread record shown:     ", "FROM-BG-THREAD" in txt)
        e = errbuf.getvalue()
        print("handleError output (first lines):")
        print("   ", "\n    ".join([l for l in e.splitlines() if "RuntimeError" in l or "Logging error" in l][:4]))
    # 4) after exit: handler still attached?
    print("handlers still on logger after exit:", [type(h).__name__ for h in log.handlers])
    old = sys.stderr; sys.stderr = io.StringIO()
    t = threading.Thread(target=lambda: log.info("AFTER-EXIT")); t.start(); t.join(timeout=3)
    out = sys.stderr.getvalue(); sys.stderr = old
    print("bg log after exit -> thread hung:", t.is_alive(), "| stderr:", [l for l in out.splitlines() if "RuntimeError" in l][:1])

asyncio.run(main())
