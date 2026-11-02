"""Exp4: reruns through real menu actions (type shortcut + Enter)."""
import asyncio, io, logging, sys, faulthandler
faulthandler.dump_traceback_later(40, exit=True)
from common import make_app, panel_text, attach_logging

log = logging.getLogger("exp4"); log.propagate = False; log.setLevel(logging.DEBUG)
def act_log(): log.warning("FROM-ACTION-MAINTHREAD")
def act_print(): print("PRINTED-BY-FOREIGN-CODE"); sys.stderr.write("STDERR-BY-FOREIGN-CODE\n")
def act_raise(): raise ValueError("bad key [/x] in config")
def act_raise_plain(): raise KeyError("missing")
R = []
def out(*a): R.append(" ".join(map(str, a)))

async def main():
    app = make_app(("Log", "l", act_log), ("Print", "p", act_print), ("RaisePlain", "k", act_raise_plain))
    async with app.run_test(size=(120, 40)) as pilot:
        attach_logging(app, log)
        app._original_stderr = io.StringIO(); app._original_stdout = io.StringIO()
        await pilot.press("l", "enter"); await pilot.pause()
        t = panel_text(app)
        out("action ran:", "Executed: Log" in t, "| log record from action shown:", "FROM-ACTION-MAINTHREAD" in t)
        out("   handleError text:", [l for l in app._original_stderr.getvalue().splitlines() if l.startswith("RuntimeError")][:1])
        await pilot.press("p", "enter"); await pilot.pause()
        t = panel_text(app)
        out("action ran:", "Executed: Print" in t, "| print() in panel:", "PRINTED-BY" in t, "| stderr in panel:", "STDERR-BY" in t)
        await pilot.press("k", "enter"); await pilot.pause()
        out("plain exception shown as:", [l for l in panel_text(app).splitlines() if "Error in" in l])
    app2 = make_app(("Raise", "e", act_raise))
    async with app2.run_test(size=(120, 40)) as pilot:
        app2._original_stderr = io.StringIO()
        await pilot.press("e", "enter"); await pilot.pause(); await pilot.pause()
        out("raise with '[/x]' in message -> app running:", app2.is_running, "| exc:", type(app2._exception).__name__ if app2._exception else None)
try:
    asyncio.run(main())
except Exception as e:
    out("outer raised", type(e).__name__)
sys.__stdout__.write("\n".join(R) + "\n")
