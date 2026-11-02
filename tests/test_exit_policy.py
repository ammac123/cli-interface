"""Constraint 3 / P2.2 / P2.3: quitting never waits on a job that will not stop (real app.run, in a subprocess)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

PROBE = textwrap.dedent(
    '''
    import asyncio, json, sys, threading, time

    from cli_interface import App, Context
    from cli_interface.capture import CAPTURE

    MODE = sys.argv[1]
    GRACE = float(sys.argv[2])
    app = App("exit-probe", quit_grace=GRACE)
    app.group("Run", key="r")
    running = threading.Event()
    out = {"mode": MODE}


    def spin(ctx: Context):
        running.set()
        if MODE == "coop":
            ctx.cancelled.wait(30)
            ctx.check_cancelled()
        elif MODE == "noisy":
            while True:
                print("noise " * 20)
        elif MODE == "chatty":
            idle = threading.Event()
            while True:  # about a thousand short lines a second, never reading ctx.cancelled
                print("chatty")
                idle.wait(0.001)
        else:
            print("tick", flush=True)
            idle = threading.Event()
            while True:  # never reads ctx.cancelled
                idle.wait(0.01)


    app.add_command("Run/Spin", spin, key="s", cancellable=(MODE == "coop"))
    app.add_command("Run/Other", lambda: "fresh", key="o")


    def panel_text():
        log = app.screen_stack[0].query_one("#display-panel")
        return "\\n".join(strip.text.rstrip() for strip in log.lines)


    async def auto(pilot):
        await pilot.press("r", "enter", "s", "enter")
        loop = asyncio.get_running_loop()
        out["started"] = await loop.run_in_executor(None, running.wait, 15)
        job = app.jobs.current
        if MODE == "stoptwice":
            await pilot.press(*"stop", "enter")
            out["after_first_stop"] = panel_text()
            await pilot.press(*"stop", "enter")
            out["after_second_stop"] = panel_text()
            out["state_after_abandon"] = app.jobs.state
            mark = app.jobs.mark()
            await pilot.press("o", "enter")
            await app.jobs.wait_idle(since=mark, jobs=1, timeout=15)
            out["after_new_run"] = panel_text()
        out["t_exit"] = time.monotonic()
        app.exit()
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=20)
        out["job_outcome"] = job.outcome
        out["job_abandoned"] = job.abandoned


    t0 = time.monotonic()
    app.run(headless=True, size=(100, 30), auto_pilot=auto)
    out["exit_to_return"] = time.monotonic() - out["t_exit"]
    out["wall"] = time.monotonic() - t0
    out["return_code"] = app.return_code
    out["refs"] = CAPTURE.refs
    out["streams_restored"] = sys.stdout is sys.__stdout__ and sys.stderr is sys.__stderr__
    sys.__stdout__.write("RESULT " + json.dumps(out) + "\\n")
    sys.__stdout__.write("DONE\\n")
    sys.__stdout__.flush()
    '''
)

CONTROL = textwrap.dedent(
    '''
    import asyncio, json, threading, time

    SLEEP = 2.0

    async def with_to_thread():
        task = asyncio.create_task(asyncio.to_thread(time.sleep, SLEEP))
        await asyncio.sleep(0.05)
        task.cancel()

    async def with_daemon_thread():
        threading.Thread(target=time.sleep, args=(SLEEP,), daemon=True).start()
        await asyncio.sleep(0.05)

    t = time.monotonic(); asyncio.run(with_to_thread()); held = time.monotonic() - t
    t = time.monotonic(); asyncio.run(with_daemon_thread()); free = time.monotonic() - t
    print(json.dumps({"to_thread": held, "daemon": free}))
    '''
)


def run_probe(tmp_path: Path, mode: str, grace: float = 0.2) -> tuple[dict, subprocess.CompletedProcess, float]:
    script = tmp_path / "exit_probe.py"
    script.write_text(PROBE, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO), os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}
    t0 = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(script), mode, str(grace)],
        capture_output=True, text=True, timeout=45, cwd=tmp_path, env=env,
    )
    wall = time.monotonic() - t0
    marker = proc.stdout.rfind("RESULT ")  # a flooding abandoned job can leave text just before it on the line
    result = json.loads(proc.stdout[marker + len("RESULT "):].splitlines()[0]) if marker >= 0 else {}
    return result, proc, wall


def assert_clean_exit(proc: subprocess.CompletedProcess, wall: float) -> None:
    assert proc.returncode == 0, (proc.returncode, proc.stderr[-2000:])
    assert "DONE" in proc.stdout, (proc.stdout[-500:], proc.stderr[-2000:])
    assert "Fatal Python error" not in proc.stderr, proc.stderr[-2000:]
    assert "Traceback" not in proc.stderr, proc.stderr[-2000:]
    assert wall < 15, f"the whole run took {wall:.1f}s"


def test_a_job_that_never_reads_the_cancel_flag_cannot_hold_the_exit(tmp_path):
    result, proc, wall = run_probe(tmp_path, "noncoop")
    assert_clean_exit(proc, wall)
    assert result["started"] is True and result["return_code"] == 0
    assert result["job_abandoned"] is True and result["job_outcome"] == "abandoned"
    assert result["exit_to_return"] < 0.2 + 1.2, f"exit to return took {result['exit_to_return']:.2f}s"


def test_a_job_flooding_stdout_through_print_cannot_hold_the_exit_or_abort_the_interpreter(tmp_path):
    result, proc, wall = run_probe(tmp_path, "noisy", grace=0.3)
    assert_clean_exit(proc, wall)
    assert result["return_code"] == 0 and result["job_abandoned"] is True
    assert result["exit_to_return"] < 0.3 + 4, f"exit to return took {result['exit_to_return']:.2f}s"


def test_a_cooperative_cancellable_job_ends_cancelled_and_leaves_the_streams_restored(tmp_path):
    result, proc, wall = run_probe(tmp_path, "coop", grace=5.0)
    assert_clean_exit(proc, wall)
    assert result["job_outcome"] == "cancelled" and result["job_abandoned"] is False
    assert result["refs"] == 0 and result["streams_restored"] is True
    assert result["exit_to_return"] < 3.0, "cooperating means well inside the 5 s grace"


def test_typing_stop_twice_abandons_the_job_releases_busy_and_a_new_run_is_accepted(tmp_path):
    result, proc, wall = run_probe(tmp_path, "stoptwice", grace=0.2)
    assert_clean_exit(proc, wall)
    assert "cannot be stopped cleanly; type stop again to abandon it" in result["after_first_stop"]
    assert "Abandoned: Spin (it did not stop; its output is now ignored)" in result["after_second_stop"]
    assert result["state_after_abandon"] == "idle"
    assert "Executed: Other → fresh" in result["after_new_run"]
    assert result["return_code"] == 0 and result["exit_to_return"] < 1.5


def test_the_to_thread_control_shows_why_jobs_use_their_own_daemon_threads(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-c", CONTROL], capture_output=True, text=True, timeout=45, cwd=tmp_path
    )
    assert proc.returncode == 0, proc.stderr
    timings = json.loads(proc.stdout.strip().splitlines()[-1])
    assert timings["to_thread"] >= 1.5, "asyncio.run waits for a cancelled to_thread sleep to finish"
    assert timings["daemon"] < 0.6, "a daemon thread does not hold asyncio.run"


@pytest.mark.parametrize("grace", [0.0, 0.1])
def test_a_tiny_grace_still_exits_cleanly(tmp_path, grace):
    result, proc, wall = run_probe(tmp_path, "noncoop", grace=grace)
    assert_clean_exit(proc, wall)
    assert result["return_code"] == 0 and result["exit_to_return"] < 1.5


def test_an_abandoned_jobs_output_never_reaches_the_terminal_even_while_textual_tears_down(tmp_path):
    """Pinned by plan 1.4 / review 6: writes of an abandoned job are swallowed. Textual restores the real stdout when it
    leaves its redirect, and CLIApp.run() re-wraps it only after super().run() returns: in between, a job that is
    still printing writes straight to the terminal."""
    result, proc, wall = run_probe(tmp_path, "chatty", grace=0.3)
    assert_clean_exit(proc, wall)
    assert result["return_code"] == 0 and result["job_abandoned"] is True
    cut = proc.stdout.rfind("RESULT ")
    leaked = proc.stdout[: cut if cut >= 0 else len(proc.stdout)].count("chatty")
    assert leaked == 0, f"{leaked} lines of an abandoned job reached the real stdout after the TUI had left its redirect"
