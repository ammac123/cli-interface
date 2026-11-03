"""Phase 3 plumbing: JobSpec.kwargs/secrets, secret redaction through the runner and log handler, command-item and settings-group model."""
from __future__ import annotations

import logging
import sys
from typing import Any

from cli_interface import Context
from cli_interface.jobs import JobSpec
from cli_interface.log_handler import TUILogHandler
from cli_interface.menu import (
    MenuItem, MenuState, _CommandItem, _SettingsGroup, find_shortcut_conflicts, make_command_item,
)

SECRET = "hunter2-s3cr3t"


def everything(rig) -> str:
    return repr(rig.host.events)


# --------------------------------------------------------------------------- kwargs delivery

async def test_kwargs_reach_a_sync_function_alongside_ctx(make_rig):
    rig = make_rig()
    seen = {}

    def body(ctx: Context, n: int, name: str = "x"):
        seen.update(ctx=ctx, n=n, name=name)

    job = await rig.run(body, kwargs={"n": 3})
    assert job.outcome == "ok" and isinstance(seen["ctx"], Context)
    assert (seen["n"], seen["name"]) == (3, "x")


async def test_kwargs_reach_an_async_function_alongside_ctx(make_rig):
    rig = make_rig()
    seen = {}

    async def body(ctx: Context, *, n: int):
        seen.update(ctx=ctx, n=n)

    job = await rig.run(body, kwargs={"n": 3})
    assert job.outcome == "ok" and isinstance(seen["ctx"], Context) and seen["n"] == 3


async def test_kwargs_work_with_a_positional_only_ctx(make_rig):
    rig = make_rig()
    seen = {}

    def body(ctx, /, n=0):
        seen.update(ctx=ctx, n=n)

    job = await rig.run(body, kwargs={"n": 5})
    assert job.outcome == "ok" and seen["n"] == 5 and isinstance(seen["ctx"], Context)


async def test_a_job_without_kwargs_is_unchanged(make_rig):
    rig = make_rig()
    seen = []

    def body(ctx: Context, value=None):
        seen.append(value)

    job = await rig.run(body, value="typed")
    assert job.outcome == "ok" and seen == ["typed"]
    assert JobSpec("x", body).kwargs == {} and JobSpec("x", body).secrets == ()


async def test_kwargs_do_not_leak_between_jobs(make_rig):
    rig = make_rig()
    seen = []

    def body(n: int = 0):
        seen.append(n)

    await rig.run(body, kwargs={"n": 1})
    await rig.run(body)
    assert seen == [1, 0]


def test_repr_of_a_spec_hides_kwargs_and_secrets():
    spec = JobSpec("x", print, kwargs={"p": "visible-value"}, secrets=("another-secret",))
    text = repr(spec)
    assert "visible-value" not in text and "another-secret" not in text


# --------------------------------------------------------------------------- redaction through the runner

async def test_spec_secrets_are_redacted_from_log_print_return_and_error(make_rig):
    rig = make_rig(capture=True)

    def body(ctx: Context):
        ctx.log.info(f"logging {SECRET}")
        print(f"printing {SECRET}")
        return f"returning {SECRET}"

    def failing():
        raise ValueError(f"bad {SECRET}")

    job = await rig.run(body, secrets=(SECRET,))
    assert job.outcome == "ok"
    bad = await rig.run(failing, "Failing", secrets=(SECRET,))
    assert bad.outcome == "error"
    assert SECRET not in everything(rig)
    assert any("logging ***" in line for line in rig.host.lines())
    assert any("printing ***" in line for line in rig.host.lines())
    assert any("returning ***" in line for line in rig.host.lines())
    assert "bad ***" in rig.host.of_kind("error")[0]["message"]


async def test_secrets_from_the_host_provider_are_redacted(make_rig):
    rig = make_rig()
    rig.host.secret_values = lambda: (SECRET,)  # type: ignore[attr-defined]

    def body(ctx: Context):
        ctx.log.info(f"token={SECRET}")
        return SECRET

    job = await rig.run(body)
    assert job.outcome == "ok" and SECRET not in everything(rig)
    assert "token=***" in rig.host.lines()[0]


async def test_a_raising_host_provider_is_skipped_and_other_sources_still_apply(make_rig):
    rig = make_rig()

    def boom():
        raise RuntimeError("provider down")

    rig.host.secret_values = boom  # type: ignore[attr-defined]

    def body(ctx: Context):
        ctx.log.info(f"token={SECRET}")

    job = await rig.run(body, secrets=(SECRET,))
    assert job.outcome == "ok" and SECRET not in everything(rig)


async def test_a_host_without_a_provider_runs_as_before(make_rig):
    rig = make_rig()
    assert not hasattr(rig.host, "secret_values")
    job = await rig.run(lambda: "fine")
    assert job.outcome == "ok" and rig.host.lines() == ["Executed: Job → fine"]


async def test_the_prompted_secret_value_is_still_redacted_and_empty_secrets_are_ignored(make_rig):
    rig = make_rig()
    rig.host.secret_values = lambda: ("", SECRET)  # type: ignore[attr-defined]

    def body(value):
        raise ValueError(f"{value} / {SECRET} / keep")

    job = await rig.run(body, value="typed-value", secret=True, secrets=("",))
    assert job.outcome == "error"
    message = rig.host.of_kind("error")[0]["message"]
    assert message == "*** / *** / keep"


# --------------------------------------------------------------------------- the log handler

class EmitHost:
    def __init__(self, secrets: Any = None) -> None:
        self.events: list[dict[str, Any]] = []
        self.pushed: list[tuple[str, str]] = []
        if secrets is not None:
            self.secret_values = secrets

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)


class PushOnlyHost:
    def __init__(self, secrets: Any) -> None:
        self.pushed: list[tuple[str, str]] = []
        self.secret_values = secrets

    def push_log(self, message: str, level: str = "INFO") -> None:
        self.pushed.append((message, level))


def record(msg: str, exc_info: Any = None) -> logging.LogRecord:
    return logging.LogRecord("pkg", logging.WARNING, __file__, 1, msg, (), exc_info, None, None)


def test_a_logged_secret_is_redacted_in_message_and_traceback():
    host = EmitHost(lambda: (SECRET,))
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    try:
        raise ValueError(f"nope {SECRET}")
    except ValueError:
        handler.emit(record(f"login with {SECRET}", sys.exc_info()))
    (event,) = host.events
    assert SECRET not in repr(event)
    assert event["msg"] == "login with ***" and "nope ***" in event["exc"]


def test_redaction_also_covers_a_custom_formatter_and_the_push_log_fallback():
    host = EmitHost(lambda: (SECRET,))
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    handler.setFormatter(logging.Formatter("CUSTOM %(message)s"))
    handler.emit(record(f"x {SECRET}"))
    assert host.events[0]["msg"] == "CUSTOM x ***"
    push = PushOnlyHost(lambda: (SECRET,))
    TUILogHandler(push).emit(record(f"y {SECRET}"))  # type: ignore[arg-type]
    assert SECRET not in push.pushed[0][0] and "y ***" in push.pushed[0][0]


def test_the_handler_reads_the_secret_set_at_emit_time():
    secrets: list[str] = []
    host = EmitHost(lambda: tuple(secrets))
    handler = TUILogHandler(host)  # type: ignore[arg-type]
    handler.emit(record(f"a {SECRET}"))
    secrets.append(SECRET)
    handler.emit(record(f"b {SECRET}"))
    assert [e["msg"] for e in host.events] == [f"a {SECRET}", "b ***"]


def test_the_handler_works_without_a_provider_and_survives_a_raising_one():
    plain = EmitHost()
    TUILogHandler(plain).emit(record("plain"))  # type: ignore[arg-type]
    assert plain.events[0]["msg"] == "plain"

    def boom():
        raise RuntimeError("down")

    broken = EmitHost(boom)
    TUILogHandler(broken).emit(record("still logged"))  # type: ignore[arg-type]
    assert broken.events[0]["msg"] == "still logged"


# --------------------------------------------------------------------------- menu model

def test_a_command_item_defaults_are_unchanged_and_new_fields_are_empty():
    item = make_command_item("Run", lambda: None)
    assert isinstance(item, _CommandItem)
    assert (item.params, item.deliver, item.confirm) == ((), "kwargs", None)
    assert item.is_leaf and item.command_path == ("Run",)


def test_make_command_item_stores_params_deliver_and_confirm():
    spec = object()
    item = make_command_item(["G", "Run"], lambda: None, key="r", params=[spec], deliver="namespace", confirm="Sure?")  # type: ignore[list-item]
    assert item.params == (spec,) and isinstance(item.params, tuple)
    assert (item.deliver, item.confirm, item.shortcut) == ("namespace", "Sure?", "r")


def test_a_settings_group_is_never_a_leaf_even_without_children():
    group = _SettingsGroup("Settings", shortcut="s")
    assert group.children == [] and group.is_leaf is False and group.on_enter is None
    group.children.append(MenuItem("child"))
    assert group.is_leaf is False
    assert isinstance(group, MenuItem)


def test_find_shortcut_conflicts_walks_settings_groups():
    group = _SettingsGroup("Settings", shortcut="s", children=[MenuItem("a", shortcut="x"), MenuItem("b", shortcut="X")])
    root = MenuItem("root", children=[group, MenuItem("other", shortcut="s")])
    problems = find_shortcut_conflicts(root)
    assert len(problems) == 2
    assert any("'x'" in p for p in problems) and any("'s'" in p for p in problems)
    assert find_shortcut_conflicts(MenuItem("root", children=[_SettingsGroup("Settings")])) == []


def test_entering_a_group_without_children_does_not_navigate_or_raise():
    group = _SettingsGroup("Settings")
    state = MenuState(MenuItem("root", children=[group]))
    assert state.enter() is False
    assert state.current_menu is state.root and state.selected_item is group
    assert state.prune() is False


def test_entering_a_group_with_children_navigates_and_goes_back():
    child = MenuItem("child")
    group = _SettingsGroup("Settings", children=[child])
    state = MenuState(MenuItem("root", children=[group]))
    assert state.enter() is True
    assert state.current_menu is group and state.selected_item is child
    assert state.back() is True and state.current_menu is state.root


def test_enter_on_a_leaf_is_still_false():
    state = MenuState(MenuItem("root", children=[MenuItem("leaf", action=lambda: None)]))
    assert state.enter() is False
