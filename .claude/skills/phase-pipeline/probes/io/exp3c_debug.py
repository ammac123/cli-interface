import asyncio
from common import make_app, panel_text
calls = []
def ret_markup(): calls.append(1); return "copied 3 files to out/[/tmp]"
def ret_plain(): calls.append(2); return "plain"
async def main():
    app = make_app(("Act", "r", ret_markup), ("Plain", "z", ret_plain))
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("z", "enter"); await pilot.pause()
        print("after plain: calls", calls, "| panel:", panel_text(app).splitlines()[-1:])
        await pilot.press("r", "enter"); await pilot.pause(); await pilot.pause()
        print("after markup: calls", calls, "| running:", app.is_running, "| _exception:", repr(app._exception)[:120])
    print("after context exit: return_code", app.return_code, "| _exception:", repr(app._exception)[:160])
asyncio.run(main())
