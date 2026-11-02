"""Exp2: real app.run() path. Worker thread keeps logging after the app exits."""
import io, logging, sys, threading, time, faulthandler
faulthandler.dump_traceback_later(20, exit=True, file=open("exp2_stacks.txt","w"))
from common import CLIApp, MenuItem, attach_logging

log = logging.getLogger("exp2"); log.setLevel(logging.INFO); log.propagate = False
stop = threading.Event(); counts = {"emitted": 0}
def worker():
    while not stop.is_set():
        log.info("tick"); counts["emitted"] += 1
        time.sleep(0.001)

class A(CLIApp):
    def on_mount(self):
        super().on_mount()
        attach_logging(self, log)
        threading.Thread(target=worker, daemon=True, name="w").start()
        self.set_timer(0.5, self.exit)

app = A(MenuItem("Home", children=[MenuItem("x", action=lambda: None)]))
t0 = time.time()
app.run(headless=True, size=(100, 30))
print(f"app.run returned after {time.time()-t0:.2f}s; app._loop now: {app._loop!r}")
errbuf = io.StringIO(); old = sys.stderr; sys.stderr = errbuf
n0 = counts["emitted"]; time.sleep(0.5); n1 = counts["emitted"]
sys.stderr = old; stop.set()
errs = [l for l in errbuf.getvalue().splitlines() if l.startswith(("RuntimeError", "--- Logging error"))]
print(f"records emitted by worker in 0.5s after exit: {n1-n0}; logging-error lines: {len(errs)}; first: {errs[:2]}")
print("handlers left on logger:", [type(h).__name__ for h in log.handlers])
