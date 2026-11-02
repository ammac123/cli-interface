"""Exp3: markup injection in log/text/return values; print() capture; basicConfig StreamHandler stream."""
import asyncio, io, logging, sys, threading
logging.basicConfig(level=logging.DEBUG)          # same as main.py:4
from common import make_app, panel_text, attach_logging

def ret_markup(): return "saved to C:\\data\\[/tmp]"   # plausible foreign return value
def prints(): print("PRINTED-BY-FOREIGN-CODE"); sys.stderr.write("STDERR-BY-FOREIGN-CODE\n")

async def main():
    app = make_app(("Ret", "r", ret_markup), ("Print", "p", prints))
    async with app.run_test(size=(120, 40)) as pilot:
        p = app.panel
        p.log("matrix[i][j] = 3", "INFO")
        p.log("tags: [bold]x[/bold] done", "INFO")
        txt = panel_text(app)
        print("log 'matrix[i][j] = 3' rendered as:", [l for l in txt.splitlines() if "matrix" in l])
        print("log '[bold]x[/bold]' rendered as:   ", [l for l in txt.splitlines() if "tags" in l])
        try:
            p.log("closing [/x] tag", "INFO"); print("log '[/x]': ok")
        except Exception as e:
            print("log '[/x]' raised:", type(e).__name__, str(e)[:60])
        # print capture
        h = logging.getLogger().handlers[0]
        print("basicConfig handler stream is sys.stderr during run:", h.stream is sys.stderr,
              "| is real terminal stderr:", h.stream is sys.__stderr__, "| sys.stderr now:", type(sys.stderr).__name__)
        await pilot.press("p"); await pilot.pause()
        print("print() output in panel:", "PRINTED-BY-FOREIGN-CODE" in panel_text(app),
              "| stderr write in panel:", "STDERR-BY-FOREIGN-CODE" in panel_text(app))
        # action whose return value contains a closing tag
        await pilot.press("r"); await pilot.pause()
        print("app still running after 'Ret' action:", app.is_running)
    print("app return_code:", app.return_code, "| exception:", type(app._exception).__name__ if app._exception else None)

asyncio.run(main())
