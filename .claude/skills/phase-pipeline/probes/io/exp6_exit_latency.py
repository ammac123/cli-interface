"""Exp6: app.exit() while a thread=True worker is busy (blocking 3s). How long until app.run() returns / process exits?"""
import sys, time, faulthandler
faulthandler.dump_traceback_later(30, exit=True)
from common import CLIApp, MenuItem
mode = sys.argv[1]
def blocking(): time.sleep(3); return "done"
class A(CLIApp):
    def on_mount(self):
        super().on_mount()
        if mode == "worker": self.run_worker(blocking, thread=True, exclusive=True)
        else:
            import threading; threading.Thread(target=blocking, daemon=True).start()
        self.set_timer(0.3, self.exit)
t0 = time.time()
A(MenuItem("Home", children=[MenuItem("x", action=lambda: None)])).run(headless=True, size=(80, 24))
sys.__stdout__.write(f"[{mode}] app.run() returned after {time.time()-t0:.2f}s (exit requested at 0.3s)\n")
