"""P2.2: plain Phase 1 actions keep working as jobs: same panel lines, same call shapes, new return-value blocks."""
from __future__ import annotations

import sys

import pytest
from rich.text import Text
from textual.widgets import RichLog

from cli_interface.menu import MenuItem
from helpers import SIZE, leaf, panel_lines, panel_text, press_and_wait, run_command, settle, type_command


def log_widget(app) -> RichLog:
    return app.screen_stack[0].query_one("#display-panel", RichLog)


# --------------------------------------------------------------------------- the pinned lines

async def test_a_zero_argument_action_ends_with_exactly_executed_label(make_app):
    ran = []
    app = make_app(MenuItem("Plain", shortcut="p", action=lambda: ran.append(1)))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        assert ran == [1], "an inline action has completed when press returns"
        assert panel_lines(app) == ["Executed: Plain"]


@pytest.mark.parametrize("value, shown", [("text", "text"), (42, "42"), (1.5, "1.5"), (True, "True"), (b"ab", "b'ab'")])
async def test_a_scalar_return_value_follows_the_arrow_on_the_same_line(make_app, value, shown):
    app = make_app(MenuItem("Ret", shortcut="r", action=lambda: value))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r", "enter")
        assert panel_lines(app) == [f"Executed: Ret → {shown}"]


@pytest.mark.parametrize("value", [None, ""])
async def test_none_and_an_empty_string_give_no_arrow(make_app, value):
    app = make_app(MenuItem("Ret", shortcut="r", action=lambda: value))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r", "enter")
        assert panel_lines(app) == ["Executed: Ret"]


async def test_an_error_gives_the_pinned_header_then_dim_plain_traceback_lines_and_the_app_survives(make_app):
    def boom():
        raise ValueError("nope [/x]")

    app = make_app(MenuItem("Boom", shortcut="b2", action=boom), leaf("Fine", "f", lambda: "ok"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"b2", "enter")
        lines = panel_lines(app)
        assert lines[0] == "Error in Boom: nope [/x]"
        assert lines[1] == "Traceback (most recent call last):" and lines[-1] == "ValueError: nope [/x]"
        assert not any("jobs.py" in ln or "outcome.py" in ln for ln in lines)
        assert any("raise ValueError" in ln for ln in lines), "the failing source line is shown"
        trace_line = log_widget(app).lines[1]
        assert all("dim" in str(seg.style) or seg.style is not None and seg.style.dim for seg in trace_line if seg.text.strip())
        assert app.is_running
        await pilot.press("f", "enter")
        assert panel_lines(app)[-1] == "Executed: Fine → ok"


async def test_an_error_traceback_shows_chained_causes(make_app):
    def chained():
        try:
            raise KeyError("inner")
        except KeyError as exc:
            raise RuntimeError("outer") from exc

    app = make_app(MenuItem("Chain", shortcut="c", action=chained))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("c", "enter")
        text = panel_text(app)
        assert "Error in Chain: outer" in text and "KeyError: 'inner'" in text
        assert "direct cause of the following exception" in text


async def test_an_action_without_an_action_still_says_no_action_bound(make_app):
    app = make_app(MenuItem("Folder-less", shortcut="n"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n", "enter")
        assert panel_lines(app) == ["Folder-less: no action bound"]


# --------------------------------------------------------------------------- call shapes

async def test_a_prompt_action_gets_the_typed_value_which_is_never_echoed(make_app):
    got = []
    app = make_app(MenuItem("Ask", shortcut="a", prompt="Name:", action=lambda v: got.append(v) or f"hi {v}"))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "a")
        await pilot.press(*"Ann", "enter")
        await pilot.pause()
        assert got == ["Ann"]
        assert panel_lines(app) == ["Executed: Ask → hi Ann"], "only the action's own return value is shown"


async def test_a_cancelled_prompt_runs_nothing(make_app):
    got = []
    app = make_app(MenuItem("Ask", shortcut="a", prompt="Name:", action=lambda v: got.append(v)))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "a")
        await pilot.press("escape")
        await pilot.pause()
        assert got == [] and panel_lines(app) == []


async def test_a_varargs_action_gets_the_prompt_value_and_nothing_without_a_prompt(make_app):
    got = []
    app = make_app(
        MenuItem("Star", shortcut="s", action=lambda *a: got.append(a)),
        MenuItem("Star ask", shortcut="t", prompt="Value:", action=lambda *a: got.append(a)),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        await type_command(pilot, "t")
        await pilot.press("x", "enter")
        await pilot.pause()
        assert got == [(), ("x",)]


async def test_a_secret_action_shows_no_value_and_no_result_and_masks_the_error(make_app):
    def action(value):
        if value == "boom":
            raise RuntimeError(f"bad token {value}")
        return f"secret result {value}"

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=action))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "l")
        await pilot.press(*"hunter2", "enter")
        await pilot.pause()
        assert panel_lines(app) == ["Executed: Login"]
        await type_command(pilot, "l")
        await pilot.press(*"boom", "enter")
        await pilot.pause()
        text = panel_text(app)
        assert "Error in Login: bad token ***" in text and "boom" not in text.replace("bad token ***", "")
        assert "hunter2" not in text and "secret result" not in text


async def test_an_async_action_without_a_context_is_awaited(make_app):
    async def action():
        return "awaited"

    app = make_app(MenuItem("Async", shortcut="a", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "a", "enter")
        assert panel_lines(app) == ["Executed: Async → awaited"]


async def test_an_async_prompt_action_is_awaited_with_the_value(make_app):
    async def action(value):
        return value.upper()

    app = make_app(MenuItem("Shout", shortcut="s", prompt="Say:", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await type_command(pilot, "s")
        mark = app.jobs.mark()
        await pilot.press(*"hey", "enter")
        await app.jobs.wait_idle(since=mark, jobs=1)
        assert panel_lines(app)[-1] == "Executed: Shout → HEY"


async def test_an_async_action_that_raises_is_an_error_line_and_the_app_survives(make_app):
    async def action():
        raise OSError("disk")

    app = make_app(MenuItem("Async boom", shortcut="a", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await press_and_wait(pilot, "a", "enter")
        assert panel_lines(app)[0] == "Error in Async boom: disk" and app.is_running


# --------------------------------------------------------------------------- return values by type (visible change)

async def test_a_dict_return_is_a_json_block_after_a_bare_executed_line(make_app):
    app = make_app(MenuItem("Dict", shortcut="d", action=lambda: {"alpha": 1, "beta": [2, 3]}))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d", "enter")
        lines = panel_lines(app)
        assert lines[-1] == "Executed: Dict", "the block comes first, the result line last"
        text = panel_text(app)
        assert '"alpha": 1' in text and '"beta"' in text


async def test_a_list_of_dicts_return_is_a_table(make_app):
    app = make_app(MenuItem("Rows", shortcut="r", action=lambda: [{"name": "a", "n": 1}, {"name": "b", "n": 2}]))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r", "enter")
        text = panel_text(app)
        assert "name" in text and "n" in text and "a" in text and "b" in text
        assert any(ch in text for ch in "┏┌╭┃│"), "drawn as a table"
        assert panel_lines(app)[-1] == "Executed: Rows"


async def test_any_other_list_is_json_not_a_table(make_app):
    app = make_app(MenuItem("Lists", shortcut="l", action=lambda: [[1, 2], [3, 4]]))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("l", "enter")
        text = panel_text(app)
        assert "[" in text and not any(ch in text for ch in "┏┌╭")


async def test_a_multi_line_string_is_a_text_block_and_a_text_object_keeps_its_style(make_app):
    app = make_app(
        MenuItem("Multi", shortcut="m", action=lambda: "first line\nsecond line"),
        MenuItem("Styled", shortcut="s", action=lambda: Text("styled output", style="bold red")),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("m", "enter")
        assert panel_lines(app) == ["first line", "second line", "Executed: Multi"]
        await pilot.press("s", "enter")
        assert panel_lines(app)[-2:] == ["styled output", "Executed: Styled"]


async def test_a_returned_container_leaves_the_panel_in_content_mode_and_a_plain_action_follows_the_end(make_app):
    app = make_app(
        MenuItem("Dict", shortcut="d", action=lambda: {"k": "v"}),
        MenuItem("Plain", shortcut="p", action=lambda: "x"),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("d", "enter")
        await pilot.pause()
        assert log_widget(app).auto_scroll is True, "a return value block is appended at the end, like log lines"
        await pilot.press("p", "enter")
        assert log_widget(app).auto_scroll is True


# --------------------------------------------------------------------------- print and the UI-only API from an inline action

async def test_print_and_stderr_in_a_legacy_action_now_reach_the_panel_before_the_result(make_app):
    def noisy():
        print("hello from print")
        sys.stderr.write("warning on stderr\n")
        print("no newline", end="")
        return "done"

    app = make_app(MenuItem("Noisy", shortcut="n", action=noisy))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("n", "enter")
        assert panel_lines(app) == [
            "hello from print", "warning on stderr", "no newline", "Executed: Noisy → done",
        ]


async def test_legacy_actions_may_still_use_the_ui_only_api_inline(make_app):
    seen = {}

    def busy_action():
        app.start_spinner(label="working")
        seen["spinning"] = app.query_one("#dashboard").spinning
        app.panel.log("from panel")
        app.go_home()
        app.refresh_menu()
        app.stop_spinner()
        return "ok"

    app = make_app(MenuItem("Ui", shortcut="u", action=busy_action))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("u", "enter")
        assert seen == {"spinning": True}
        assert panel_lines(app) == ["from panel", "Executed: Ui → ok"]
        assert app.query_one("#dashboard").spinning is False


async def test_an_inline_action_that_calls_exit_exits_with_its_code_and_no_stopping_noise(make_app):
    app = make_app(MenuItem("Leave", shortcut="x", action=lambda: app.exit(return_code=3)))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("x", "enter")
        await app.jobs.wait_until(lambda m: app.return_code is not None, timeout=10)
        assert app.return_code == 3
        assert "Stopping" not in panel_text(app)


async def test_the_label_in_the_result_line_is_read_before_the_action_runs(make_app):
    state = {"name": "Before"}

    def rename():
        state["name"] = "After"

    app = make_app(MenuItem(lambda: state["name"], shortcut="r", action=rename))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("r", "enter")
        assert panel_lines(app) == ["Executed: Before"]


async def test_a_hostile_label_return_and_error_stay_literal_in_the_new_lines(make_app):
    def boom():
        raise ValueError("[/x]")

    app = make_app(MenuItem("[/x] label", shortcut="b2", action=boom), MenuItem("matrix[i][j]", shortcut="m", action=lambda: "C:\\[/tmp]"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press(*"b2", "enter")
        await pilot.press("m", "enter")
        lines = panel_lines(app)
        assert "Error in [/x] label: [/x]" in lines
        assert lines[-1] == "Executed: matrix[i][j] → C:\\[/tmp]"


async def test_settle_waits_for_a_running_loop_job_and_flushes_the_panel(make_app):
    async def action():
        return "late"

    app = make_app(MenuItem("A", shortcut="a", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a", "enter")
        await settle(pilot)
        assert panel_lines(app) == ["Executed: A → late"]


async def test_run_command_helper_types_and_waits(make_app):
    async def action():
        return 1

    app = make_app(MenuItem("A", shortcut="a", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await run_command(pilot, "a")
        assert panel_lines(app) == ["Executed: A → 1"]
