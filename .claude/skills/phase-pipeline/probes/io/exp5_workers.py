"""Exp5: whiteboard pattern run_worker(coro, thread=True, exclusive=True): does cancel/replace stop W1?
Also: start_spinner() called directly inside the thread coroutine - which loop owns the timer?"""
import asyncio, io, sys, threading, faulthandler
faulthandler.dump_traceback_later(40, exit=True)
from common import make_app, panel_text
R = []; out = lambda *a: R.append(" ".join(map(str, a)))
counters = {"W1": 0, "W2": 0}
info = {}

async def job(name, app, n=40):
    if name == "W1":
        try:
            app.start_spinner(label="from thread")       # direct call, as whiteboard.py:215 does
            h = app._spinner_handle
            info["timer_loop_is_app_loop"] = h._task.get_loop() is app._loop
            info["timer_thread"] = threading.current_thread().name
        except Exception as e:
            info["start_spinner_exc"] = f"{type(e).__name__}: {e}"
    try:
        for _ in range(n):
            await asyncio.sleep(0.02); counters[name] += 1
    except asyncio.CancelledError:
        info[f"{name}_saw_cancel"] = True; raise

async def main():
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        app._original_stderr = io.StringIO()
        w1 = app.run_worker(job("W1", app), exclusive=True, thread=True)
        await asyncio.sleep(0.2)
        w2 = app.run_worker(job("W2", app), exclusive=True, thread=True)   # should replace W1
        await asyncio.sleep(0.05); c_at_cancel = counters["W1"]
        out("W1 state after exclusive replace:", w1.state.name, "| W1 counter at replace:", c_at_cancel)
        await asyncio.sleep(0.4)
        out("W1 counter 0.4s later:", counters["W1"], "(still running?)", counters["W1"] > c_at_cancel, "| W2 counter:", counters["W2"])
        out("W1 coroutine saw CancelledError:", info.get("W1_saw_cancel", False))
        out("start_spinner from thread:", info)
        out("app._spinner_handle still set:", app._spinner_handle is not None)
        await asyncio.sleep(0.6)
try:
    asyncio.run(main())
except BaseException as e:
    out("app.run_test raised at shutdown:", type(e).__name__, e)
sys.__stdout__.write("\n".join(R) + "\n")
