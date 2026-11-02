"""A simulated background worker for the Worker Demo: ``run()`` reports only through ``logging``."""
from __future__ import annotations

import logging
import random
import time

log = logging.getLogger(__name__)

_EVENTS = [
    (logging.DEBUG,    "heartbeat OK"),
    (logging.DEBUG,    "cache hit — skipping fetch"),
    (logging.INFO,     "processed batch #{batch}"),
    (logging.INFO,     "checkpoint saved at step {i}"),
    (logging.INFO,     "upstream responded in {ms}ms"),
    (logging.WARNING,  "upstream latency spike: {ms}ms — still within SLA"),
    (logging.WARNING,  "retry #{retry} after transient failure"),
    (logging.ERROR,    "connection reset by peer — queuing for retry"),
]


def run(steps: int = 14, delay: float = 0.35) -> None:
    """
    Simulate a background worker.  All output goes through ``logging`` —
    no print statements — so the caller controls where it ends up.
    """
    log.info("Worker starting — %d steps planned", steps)
    for i in range(1, steps + 1):
        time.sleep(delay)
        level, tmpl = random.choice(_EVENTS)
        msg = tmpl.format(
            i=i,
            batch=i * 10,
            ms=random.randint(8, 1800),
            retry=random.randint(1, 3),
        )
        log.log(level, "step %d/%d — %s", i, steps, msg)

    log.info("Worker finished — all %d steps complete", steps)
