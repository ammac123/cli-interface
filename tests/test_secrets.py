"""F4: prompted values are never echoed; secret items are masked, redacted and kept out of repr."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

import pytest
from textual.widgets import Input

from cli_interface.menu import MenuItem
from cli_interface.widgets import NavBar, PromptScreen
from helpers import SIZE, Calls, leaf, panel_lines, panel_text, read_panel, widget_text

SECRET = "hunter2"


async def type_into_prompt(pilot, text: str) -> None:
    for ch in text:
        await pilot.press(ch)
    await pilot.press("enter")
    await pilot.pause()


# --------------------------------------------------------------------------- the prompt screen

async def test_prompt_input_is_masked_only_for_secret_items(make_app):
    app = make_app(
        MenuItem("Port", shortcut="p", prompt="Port:", action=lambda v: None),
        MenuItem("Token", shortcut="k", prompt="Token:", action=lambda v: None, secret=True),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is False
        await pilot.press("escape")
        await pilot.pause()
        await pilot.press("k", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PromptScreen)
        assert app.screen.query_one("#prompt-input", Input).password is True


async def test_typed_secret_characters_are_not_visible_on_screen(make_app):
    app = make_app(MenuItem("Token", shortcut="k", prompt="Token:", action=lambda v: None, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "enter")
        await pilot.pause()
        for ch in SECRET:
            await pilot.press(ch)
        await pilot.pause()
        field_text = widget_text(app.screen.query_one("#prompt-input", Input))
        assert SECRET not in field_text and "hunter" not in field_text
        assert app.screen.query_one("#prompt-input", Input).value == SECRET


def test_prompt_screen_secret_is_keyword_only_and_defaults_to_off():
    assert PromptScreen("label", "prompt")._secret is False
    assert PromptScreen("label", "prompt", secret=True)._secret is True
    with pytest.raises(TypeError):
        PromptScreen("label", "prompt", True)  # type: ignore[misc]


# --------------------------------------------------------------------------- no echo of the typed value

async def test_plain_prompted_item_does_not_echo_the_typed_value(make_app):
    calls = Calls()
    app = make_app(MenuItem("Set Port", shortcut="p", prompt="Port:", action=calls.action("port")))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "8080")
        lines = panel_lines(app)
        assert calls.log == [("port", ("8080",))]
        assert [ln for ln in lines if "Executed" in ln] == ["Executed: Set Port"]
        assert not any("8080" in ln for ln in lines)


async def test_plain_prompted_result_is_shown_but_not_the_value(make_app):
    app = make_app(MenuItem("Set Port", shortcut="p", prompt="Port:", action=lambda v: f"port → {v}"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "8080")
        text = panel_text(app)
        assert "Executed: Set Port → port → 8080" in text
        assert "'8080'" not in text


async def test_non_prompted_result_suffix_is_unchanged(make_app):
    app = make_app(leaf("Answer", "a", lambda: 42), leaf("Nothing", "n", lambda: None))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a", "enter")
        await pilot.press("n", "enter")
        lines = await read_panel(pilot)
        assert "Executed: Answer → 42" in lines
        assert "Executed: Nothing" in lines and "Executed: Nothing →" not in lines


# --------------------------------------------------------------------------- secret items

async def test_secret_value_never_appears_in_any_panel_line_and_has_no_result_suffix(make_app):
    app = make_app(MenuItem("Set Tok", shortcut="k", prompt="Token:", action=lambda v: f"tok {v}", secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("k", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, SECRET)
        lines = panel_lines(app)
        assert not any(SECRET in ln for ln in lines)
        executed = [ln for ln in lines if "Executed" in ln]
        assert len(executed) == 1 and executed[0].endswith("Executed: Set Tok")
        assert "→" not in executed[0]


async def test_secret_item_without_a_prompt_also_suppresses_its_result(make_app):
    app = make_app(MenuItem("S", shortcut="s", action=lambda: "SECRETRESULT", secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("s", "enter")
        text = await read_panel(pilot)
        assert "Executed: S" in text and "SECRETRESULT" not in text


async def test_secret_value_is_redacted_from_exception_text(make_app):
    def reject(value):
        raise RuntimeError(f"bad token {value} rejected [/x]; {value}!")

    app = make_app(MenuItem("Bad Tok", shortcut="j", prompt="Token:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "s3cr3t")
        text = panel_text(app)
        assert "Error in Bad Tok: bad token *** rejected [/x]; ***!" in text
        assert "s3cr3t" not in text
        assert app.is_running


async def test_value_with_markup_like_characters_is_redacted_literally(make_app):
    value = "p[/w]d"

    def reject(v):
        raise ValueError(f"wrong {v}")

    app = make_app(MenuItem("T", shortcut="t", prompt="v:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t", "enter")
        await pilot.pause()
        app.screen.query_one("#prompt-input", Input).value = value
        await pilot.press("enter")
        text = await read_panel(pilot)
        assert "Error in T: wrong ***" in text and value not in text


async def test_empty_secret_value_leaves_the_error_text_untouched(make_app):
    def reject(value):
        raise ValueError("token required")

    app = make_app(MenuItem("Tok", shortcut="t", prompt="Token:", action=reject, secret=True))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t", "enter")
        await pilot.pause()
        await pilot.press("enter")  # submit nothing
        await pilot.pause()
        lines = panel_lines(app)
        assert [ln for ln in lines if "Error in" in ln] == ["Error in Tok: token required"]
        assert app.is_running


async def test_non_secret_error_text_is_not_redacted(make_app):
    def reject(value):
        raise ValueError(f"bad port {value}")

    app = make_app(MenuItem("Port", shortcut="p", prompt="Port:", action=reject))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("p", "enter")
        await pilot.pause()
        await type_into_prompt(pilot, "99999")
        assert "Error in Port: bad port 99999" in panel_text(app)


# --------------------------------------------------------------------------- nav bar masking

async def test_navbar_masks_a_secret_current_value(make_app):
    app = make_app(
        MenuItem("Token", shortcut="k", current_value=SECRET, secret=True, action=lambda: None),
        MenuItem("Pw", shortcut="w", secret=True, action=lambda: None),
        MenuItem("Port", shortcut="p", current_value=8080, action=lambda: None),
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        nav = app.query_one("#nav-bar", NavBar)
        plain = nav.render().plain
        assert "Token (••••)" in plain and SECRET not in plain
        assert "Pw " in plain and "Pw (" not in plain
        assert "Port (8080)" in plain
        assert "Token (••••)" in widget_text(nav) and SECRET not in widget_text(nav)


async def test_navbar_layout_uses_the_masked_width_not_the_raw_width(make_app):
    long_secret = "x" * 300
    secret_app = make_app(
        MenuItem("Token", shortcut="k", current_value=long_secret, secret=True, action=lambda: None),
        MenuItem("Port", shortcut="p", action=lambda: None),
    )
    plain_app = make_app(
        MenuItem("Token", shortcut="k", current_value=long_secret, action=lambda: None),
        MenuItem("Port", shortcut="p", action=lambda: None),
    )
    async with secret_app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        masked_rows = secret_app.query_one("#nav-bar", NavBar).render().plain.split("\n")
    async with plain_app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        raw_rows = plain_app.query_one("#nav-bar", NavBar).render().plain.split("\n")
    assert len(masked_rows) == 1, "the masked secret and the next item fit on one row"
    assert len(raw_rows) > 1, "control: the same long value unmasked forces a wrap"


# --------------------------------------------------------------------------- repr / str

@dataclass
class _Stock:  # reference: the stock dataclass repr with the same field layout as MenuItem
    label: str
    shortcut: str = ""
    description: str = ""
    children: list = field(default_factory=list)
    action: Callable[..., Any] | None = None
    prompt: str | None = None
    current_value: Any = None
    secret: bool = False


_Stock.__qualname__ = "MenuItem"  # the stock repr prints the class name


def build(cls: type, spec: dict) -> Any:
    spec = dict(spec)
    kids = spec.pop("children", [])
    return cls(**spec, children=[build(cls, k) for k in kids])


NON_SECRET_SPECS = [
    dict(label="x"),
    dict(label="a", shortcut="s", description="d", prompt="p", current_value=8080),
    dict(label="a", current_value="hunter2"),
    dict(label="a", current_value=None, action=print),
    dict(label="a", current_value=False),
    dict(label="a", current_value="it's [/x]\n"),
    dict(label="root", current_value=1, children=[
        dict(label="k1", current_value="v"), dict(label="k2", children=[dict(label="k3", shortcut="z")]),
    ]),
]


@pytest.mark.parametrize("spec", NON_SECRET_SPECS, ids=lambda s: s["label"] + str(s.get("current_value")))
def test_non_secret_menu_item_repr_is_identical_to_the_stock_dataclass_repr(spec):
    assert repr(build(MenuItem, spec)) == repr(build(_Stock, spec))


def test_secret_item_without_a_value_has_the_stock_repr():
    assert repr(MenuItem("x", secret=True)) == repr(_Stock("x", secret=True))


def test_secret_value_is_masked_in_repr_str_and_format():
    item = MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    for rendered in (repr(item), str(item), f"{item!r}", f"{item}", "%r" % (item,)):  # noqa: UP031  (%-formatting is the case under test)
        assert "SECRET123" not in rendered
    assert "current_value='***'" in repr(item) and "secret=True" in repr(item)
    assert item.current_value == "SECRET123", "masking must not change the stored value"


def test_secret_children_are_masked_inside_a_parents_repr_and_siblings_are_not():
    secret = MenuItem("Tok", current_value="SECRET123", secret=True)
    parent = MenuItem("P", children=[secret, MenuItem("Plain", current_value="visible")])
    rendered = repr(parent)
    assert "SECRET123" not in rendered and "current_value='visible'" in rendered
    deep = MenuItem("Top", children=[MenuItem("Mid", children=[secret])])
    assert "SECRET123" not in repr(deep)


def test_cyclic_menu_repr_terminates_and_still_masks():
    plain = MenuItem("C", current_value="abc")
    plain.children.append(plain)
    secret = MenuItem("S", current_value="topsecret", secret=True)
    secret.children.append(secret)
    assert "..." in repr(plain)
    assert "..." in repr(secret) and "topsecret" not in repr(secret)


def test_equality_and_replace_still_work_on_secret_items():
    item = MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    assert dataclasses.replace(item, label="n").current_value == "SECRET123"
    assert item == MenuItem("Token", prompt="p", current_value="SECRET123", secret=True)
    assert item != MenuItem("Token", prompt="p", current_value="other", secret=True)


# =========================================================================== Phase 2: secret jobs (threads, loops, tracebacks, payloads)

import ast  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
from pathlib import Path  # noqa: E402

from cli_interface import CLIApp, Context  # noqa: E402
from cli_interface.events import validate_event  # noqa: E402
from helpers import make_gate, type_command, wait_event  # noqa: E402

PACKAGE = Path(__file__).resolve().parent.parent / "cli_interface"
M1_SECRETS = ["hunter2", "123456", 'q"u\\o', "pässwörd"]


def spellings(secret: str) -> set[str]:
    return {secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1], repr(secret)[1:-1],
            ascii(secret)[1:-1]}


async def submit_secret(pilot, secret: str) -> None:
    """Open the prompt of the single secret item (shortcut ``l``), put ``secret`` in it and confirm."""
    app = pilot.app
    mark = app.jobs.mark()
    await type_command(pilot, "l")
    assert isinstance(app.screen, PromptScreen)
    app.screen.query_one("#prompt-input", Input).value = secret
    await pilot.press("enter")
    await app.jobs.wait_idle(since=mark, jobs=1)
    await pilot.pause()


def lane_actions() -> dict[str, Callable[..., Any]]:
    def inline(value):
        raise RuntimeError(f"login failed for {value}")

    def thread(ctx: Context, value):
        raise RuntimeError(f"login failed for {value}")

    async def loop(ctx: Context, value):
        raise RuntimeError(f"login failed for {value}")

    return {"inline": inline, "thread": thread, "loop": loop}


@pytest.mark.parametrize("lane", ["inline", "thread", "loop"])
async def test_a_secret_job_that_raises_shows_a_header_and_traceback_without_the_secret(make_app, lane):
    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=lane_actions()[lane]))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        lines = panel_lines(app)
        assert lines[0] == "Error in Login: login failed for ***"
        assert lines[1] == "Traceback (most recent call last):" and lines[-1] == "RuntimeError: login failed for ***"
        assert SECRET not in panel_text(app) and "jobs.py" not in panel_text(app)


@pytest.mark.parametrize("lane", ["thread", "loop"])
async def test_a_secret_in_the_cause_of_a_raise_from_chain_is_masked(make_app, lane):
    def chained(value):
        try:
            raise ConnectionError(f"password={value} rejected")
        except ConnectionError as cause:
            raise RuntimeError("could not log in") from cause

    async def achained(ctx: Context, value):
        chained(value)

    def tchained(ctx: Context, value):
        chained(value)

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True,
                            action=tchained if lane == "thread" else achained))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        text = panel_text(app)
        assert SECRET not in text and "password=*** rejected" in text
        assert "direct cause of the following exception" in text and "Error in Login: could not log in" in text


async def test_a_local_variable_holding_the_secret_never_reaches_the_panel(make_app):
    def action(ctx: Context, value):
        api_key = value  # noqa: F841
        token = f"Bearer {value}"  # noqa: F841
        raise ValueError("configuration is invalid")

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=action))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        text = panel_text(app)
        assert "configuration is invalid" in text and SECRET not in text and "Bearer" not in text


def test_show_locals_true_appears_nowhere_in_the_package():
    offenders = []
    for path in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg == "show_locals":
                if not (isinstance(node.value, ast.Constant) and node.value.value is False):
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


async def test_a_secret_jobs_log_print_stderr_and_panel_output_are_all_redacted(make_app):
    def action(ctx: Context, value):
        ctx.log(f"log {value}")
        ctx.log.warning(f"warn {value}", markup=True)
        print(f"print {value}")
        sys.stderr.write(f"stderr {value}\n")
        ctx.panel.text(f"panel {value}")
        ctx.panel.log(f"panel log {value}", "ERROR")
        ctx.panel.rule(f"rule {value}")
        ctx.status(f"status {value}")
        ctx.progress(1, 3, f"progress {value}")
        return f"returned {value}"

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=action))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        text = panel_text(app)
        assert SECRET not in text and text.count("***") >= 6
        assert "log ***" in text and "print ***" in text and "stderr ***" in text and "panel ***" in text
        assert panel_lines(app)[-1] == "Executed: Login", "the return value is not shown at all"
        assert "returned" not in text


async def test_the_same_job_without_secret_shows_the_value_so_the_assertions_can_fail(make_app):
    def action(ctx: Context, value):
        ctx.log(f"log {value}")
        print(f"print {value}")
        return f"returned {value}"

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", action=action))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        text = panel_text(app)
        assert f"log {SECRET}" in text and f"print {SECRET}" in text and f"Executed: Login → returned {SECRET}" in text


async def test_an_async_secret_job_masks_its_output_too(make_app):
    async def action(ctx: Context, value):
        ctx.log(f"async {value}")
        print(f"async print {value}")
        return value

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=action))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        assert SECRET not in panel_text(app) and "async ***" in panel_text(app)


async def test_an_empty_secret_value_leaves_a_jobs_text_untouched(make_rig):
    rig = make_rig(capture=True)

    def action(ctx: Context, value):
        ctx.log("plain text stays")
        print("so does this")
        raise ValueError("and this error")

    await rig.run(action, "Login", value="", secret=True)
    assert rig.host.lines() == ["plain text stays", "so does this", "Error in Login: and this error"]


async def test_the_secret_is_absent_from_debug_logs_the_job_repr_and_the_abandoned_line(make_rig, caplog):
    rig = make_rig()
    gate, started = make_gate(), threading.Event()

    def stuck(ctx: Context, value):
        started.set()
        gate.wait(15)

    def boom(ctx: Context, value):
        raise ValueError(f"bad {value}")

    with caplog.at_level(logging.DEBUG):
        await rig.run(boom, "Boom", value=SECRET, secret=True)
        job = rig.submit(stuck, "Stuck", value=SECRET, secret=True)
        await wait_event(started)
        rig.mgr.request_cancel()
        rig.mgr.request_cancel()
        gate.set()
    shown = caplog.text + repr(job) + str(job) + repr(rig.host.events) + repr(rig.mgr._dump())
    assert SECRET not in shown and "Abandoned: Stuck" in repr(rig.host.events)


# ---- M1: json / table / csv / array / pretty payloads of a secret job, end to end

@pytest.mark.parametrize("secret", M1_SECRETS)
async def test_payload_methods_of_a_secret_job_never_show_the_secret_in_any_spelling(make_app, monkeypatch, secret):
    seen: list[dict[str, Any]] = []
    original = CLIApp._sink_event
    monkeypatch.setattr(CLIApp, "_sink_event", lambda self, event: (seen.append(event), original(self, event))[1])

    def leak(ctx: Context, value):
        ctx.panel.json({"token": value, value: [value, {"deep": value}], "pin": 123456}, "title " + value)
        ctx.panel.array([value, (value,), {value}])
        ctx.panel.pretty({"k": value, value: 1})
        ctx.panel.table([{"name": value, value: 1}, {"name": "ok"}], title=value)
        ctx.panel.table([[value, 2], [3, value]], headers=["a", value])
        ctx.panel.csv(f'a,b\n"{value.replace(chr(34), chr(34) * 2)}",2', title=value)

    app = make_app(MenuItem("Leak", shortcut="l", prompt="Secret:", secret=True, action=leak))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, secret)
        text = panel_text(app)
        job_events = [e for e in seen if e.get("job") is not None]
    blob = "\n".join(json.dumps(e, default=str) + repr(e) for e in job_events)
    for form in spellings(secret):
        assert form not in text, ("panel", form)
        assert form not in blob, ("events", form)
    assert "***" in text and "Executed: Leak" in text
    payload_events = [e for e in job_events if e["kind"] in ("json", "table")]
    assert len(payload_events) == 6
    for e in payload_events:
        assert validate_event(e) == [] and e["job"] == 1 and e["scroll"] == "top"
        if e["kind"] == "json":
            assert isinstance(e["data"], str) and e["pretty"] is False
        else:
            assert all(isinstance(k, str) and isinstance(v, str) for row in e["rows"] if isinstance(row, dict)
                       for k, v in row.items())


@pytest.mark.parametrize("secret", M1_SECRETS)
async def test_the_non_secret_control_shows_the_payload_and_keeps_the_same_object(make_app, monkeypatch, secret):
    seen: list[dict[str, Any]] = []
    original = CLIApp._sink_event
    monkeypatch.setattr(CLIApp, "_sink_event", lambda self, event: (seen.append(event), original(self, event))[1])
    payload = {"token": secret}

    def leak(ctx: Context, value):
        ctx.panel.pretty(payload)

    app = make_app(MenuItem("Leak", shortcut="l", prompt="Value:", action=leak))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, secret)
        text = panel_text(app)
        (event,) = [e for e in seen if e["kind"] == "json"]
    assert event["pretty"] is True and event["data"] == payload
    assert "token" in text


async def test_a_threaded_secret_jobs_content_method_is_not_clobbered_by_the_end_of_the_action(make_app):
    def leak(ctx: Context, value):
        ctx.panel.json({"k": value})

    app = make_app(MenuItem("Leak", shortcut="l", prompt="Value:", secret=True, action=leak))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        log = app.screen_stack[0].query_one("#display-panel")
        assert '"k": "***"' in panel_text(app) and log.auto_scroll is False, "content mode survives the action end"


async def test_rich_objects_written_by_a_secret_job_fall_back_to_their_redacted_plain_text(make_app):
    from rich.text import Text

    def action(ctx: Context, value):
        ctx.panel.text(Text(f"text obj {value}", style="bold"))
        ctx.panel.log(Text(f"log obj {value}"), "ERROR")
        ctx.panel.rule(Text(f"rule obj {value}"))
        ctx.panel.renderable(Text(f"renderable {value}"))
        ctx.panel.table([[Text(f"cell {value}")]], headers=[Text(f"head {value}")])  # type: ignore[list-item]
        return Text(f"returned {value}")

    app = make_app(MenuItem("Login", shortcut="l", prompt="Password:", secret=True, action=action))
    async with app.run_test(size=SIZE) as pilot:
        await submit_secret(pilot, SECRET)
        text = panel_text(app)
        assert SECRET not in text
        for expected in ("text obj ***", "log obj ***", "rule obj ***", "renderable ***", "cell ***", "head ***"):
            assert expected in text, expected
        assert "returned" not in text
