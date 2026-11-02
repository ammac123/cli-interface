"""Exp7: throughput of TUILogHandler (blocking round-trip per record), log-mode re-render cost, append-mode growth.
Compared with a non-blocking queued handler sketch."""
import asyncio, collections, io, logging, sys, threading, time, faulthandler
faulthandler.dump_traceback_later(120, exit=True)
from rich.text import Text
from textual.widgets import RichLog
from common import make_app, attach_logging
R = []
def out(*a): sys.__stdout__.write(" ".join(map(str, a)) + "\n"); sys.__stdout__.flush()

class QueuedHandler(logging.Handler):            # design sketch: never blocks the producer
    def __init__(self, app, maxlen=10_000):
        super().__init__(); self.app = app; self.q = collections.deque(maxlen=maxlen); self.scheduled = False; self._qlock = threading.Lock()
    def emit(self, record):
        self.q.append((self.format(record), record.levelname))
        with self._qlock:
            if self.scheduled or self.app._loop is None: return
            self.scheduled = True
        self.app._loop.call_soon_threadsafe(self.drain)
    def drain(self):
        with self._qlock: self.scheduled = False
        w = self.app.query_one("#display-panel", RichLog)
        while self.q:
            msg, lvl = self.q.popleft(); w.write(Text(msg))

async def trial(label, n, append_mode=False, handler="tui"):
    log = logging.getLogger(f"exp7.{label}"); log.propagate = False; log.setLevel(logging.INFO)
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        w = app.query_one("#display-panel", RichLog)
        writes = {"n": 0}; orig = w.write
        def counting(*a, **k): writes["n"] += 1; return orig(*a, **k)
        w.write = counting
        if append_mode: app.panel.rule("x")
        if handler == "tui": attach_logging(app, log)
        else: h = QueuedHandler(app); h.setFormatter(logging.Formatter("%(message)s")); log.addHandler(h)
        done = threading.Event(); t_prod = {}
        def produce():
            t0 = time.perf_counter()
            for i in range(n): log.info("record %d", i)
            t_prod["s"] = time.perf_counter() - t0; done.set()
        t0 = time.perf_counter(); threading.Thread(target=produce).start()
        while not done.is_set(): await asyncio.sleep(0.005)
        await pilot.pause(); total = time.perf_counter() - t0
        out(f"{label:28s} n={n:5d}  producer blocked {t_prod['s']:.2f}s  ({n/t_prod['s']:,.0f} rec/s)  RichLog.write calls={writes['n']:7d}  lines held={len(w.lines)}")

async def main():
    import sys as _s
    for spec in _s.argv[1:]:
        lab, n, mode, h = spec.split(":")
        await trial(lab, int(n), append_mode=(mode=="append"), handler=h)
asyncio.run(main())
sys.__stdout__.write("\n".join(R) + "\n")
