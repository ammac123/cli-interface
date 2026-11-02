"""
The job API in one file: ``App``, ``@app.command``, ``Context``, progress, cancel and the
four hooks. Run it with ``python -m examples.app_demo`` from the repository root, or
``cli-interface examples.app_demo:app``. It uses only the public ``cli_interface`` API.
"""
from __future__ import annotations

import asyncio

from cli_interface import App, Context

app = App("Demo")

app.group("Run", key="r")
app.group("Tools", key="t")


@app.on_startup
def ready(ctx: Context) -> None:
    ctx.log("Demo ready. Try Run, then type stop while it counts.")


@app.before_command
def count_run(ctx: Context) -> None:
    ctx.state.runs = getattr(ctx.state, "runs", 0) + 1


@app.after_command
def report(ctx: Context) -> None:
    ctx.log(f"{ctx.job.label}: {ctx.job.outcome} (command {ctx.state.runs})")


@app.on_shutdown
def goodbye(ctx: Context) -> None:
    ctx.log(f"{getattr(ctx.state, 'runs', 0)} command(s) run")


@app.command("Run/Count", key="c", cancellable=True)
async def count(ctx: Context) -> str:
    """Count to 20 on the event loop; type stop to cancel it."""
    steps = 20
    for step in range(1, steps + 1):
        ctx.progress(step, steps, "Counting")
        await asyncio.sleep(0.25)
    return f"Counted to {steps}"


@app.command("Run/Crunch", key="n")
def crunch(ctx: Context) -> dict[str, int]:
    """Do ten steps in a thread, with progress, status text and print()."""
    steps = 10
    done = 0
    for step in range(1, steps + 1):
        ctx.status(f"Crunching step {step}")
        ctx.progress(step, steps, "Crunching")
        print(f"step {step} of {steps}")
        done = step
        if ctx.cancelled.wait(0.3):  # set when the app quits
            break
    return {"steps": done}


@app.command("Tools/Greet", key="g")
def greet() -> str:
    """Return a string; it is shown on the Executed line."""
    return "Hello from the demo"


@app.command("Tools/Table", key="s")
def table() -> list[dict[str, object]]:
    """Return a list of dicts; it is shown as a table."""
    return [
        {"name": "alpha", "size": 12},
        {"name": "beta", "size": 7},
        {"name": "gamma", "size": 31},
    ]


def main() -> int:
    """Run the demo and return the app's exit code. Needs a real terminal."""
    app.run()
    return app.return_code or 0


if __name__ == "__main__":
    raise SystemExit(main())
