"""P2.2 / C1-2 / C0-1: Context, JobLog, JobEmitter (job tag, redaction, dead gate) and JobCancelled."""
from __future__ import annotations

import csv
import dataclasses
import io
import json
import logging
import math
import threading
from types import SimpleNamespace
from typing import Any

import pytest
from rich.text import Text

from cli_interface import Context
from cli_interface.context import JobCancelled, JobEmitter, JobLog
from cli_interface.context import Context as ContextClass
from cli_interface.display import DisplayPanel
from cli_interface.events import make_json, make_log, make_table, make_text, validate_event
from helpers import SIZE, leaf, panel_text


class Host:
    """A fake JobHost that records the UI calls made for a job."""

    def __init__(self) -> None:
        self.state = SimpleNamespace(count=1)
        self.events: list[dict[str, Any]] = []
        self.calls: list[tuple[Any, ...]] = []

    def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def on_ui_thread(self) -> bool:
        return True

    def call_ui(self, fn, *args, **kwargs):
        self.calls.append((fn.__name__, *args))
        return fn(*args, **kwargs)

    def post_ui(self, fn, *args) -> None:
        self.calls.append(("post", fn.__name__, *args))

    def set_menu(self, menu) -> None:
        self.calls.append(("set_menu_impl", menu))

    def refresh_menu(self) -> None:
        self.calls.append(("refresh_menu_impl",))

    def go_home(self) -> None:
        self.calls.append(("go_home_impl",))


class Rig:
    def __init__(self, secrets=(), dead=False) -> None:
        self.host = Host()
        self.dead = dead
        self.emitter = JobEmitter(self.host.emit, 7, list(secrets), lambda: self.dead)
        self.job = SimpleNamespace(id=7, cancelled=threading.Event())
        self.panel = DisplayPanel(emitter=self.emitter)
        self.ctx = ContextClass(self.job, self.host, self.panel, self.emitter)  # type: ignore[arg-type]

    @property
    def events(self) -> list[dict[str, Any]]:
        return self.host.events


@pytest.fixture
def rig() -> Rig:
    return Rig()


# --------------------------------------------------------------------------- the public surface

def test_context_is_the_public_class():
    assert Context is ContextClass


def test_context_surface(rig):
    ctx = rig.ctx
    assert ctx.job is rig.job and ctx.panel is rig.panel
    assert isinstance(ctx.log, JobLog)
    assert isinstance(ctx.cancelled, threading.Event) and ctx.cancelled is rig.job.cancelled
    for name in ("progress", "status", "check_cancelled", "set_menu", "refresh_menu", "go_home"):
        assert callable(getattr(ctx, name)), name
    assert not hasattr(ctx, "app"), "no ctx.app in Phase 2"
    assert not hasattr(ctx, "ask") and not hasattr(ctx, "require")


def test_state_is_the_apps_live_namespace(rig):
    assert rig.ctx.state is rig.host.state
    rig.ctx.state.extra = "shared"
    assert rig.host.state.extra == "shared"
    rig.host.state = SimpleNamespace(replaced=True)
    assert rig.ctx.state.replaced is True


def test_cancelled_is_a_threading_event_other_threads_can_wait_on(rig):
    results: list[bool] = []
    t = threading.Thread(target=lambda: results.append(rig.ctx.cancelled.wait(10)))
    t.start()
    rig.job.cancelled.set()
    t.join(10)
    assert results == [True]


def test_check_cancelled_raises_job_cancelled_only_when_set(rig):
    rig.ctx.check_cancelled()
    rig.job.cancelled.set()
    with pytest.raises(JobCancelled):
        rig.ctx.check_cancelled()


def test_job_cancelled_is_an_ordinary_exception():
    assert issubclass(JobCancelled, Exception)
    assert not issubclass(JobCancelled, (KeyboardInterrupt, SystemExit))


# --------------------------------------------------------------------------- ctx.log

def test_ctx_log_default_event(rig):
    rig.ctx.log("hello")
    (ev,) = rig.events
    assert (ev["kind"], ev["level"], ev["levelno"], ev["msg"], ev["logger"], ev["markup"]) == (
        "log", "INFO", 20, "hello", None, False
    )
    assert ev["job"] == 7 and validate_event(ev) == []


@pytest.mark.parametrize("method, level, number", [
    ("debug", "DEBUG", 10), ("info", "INFO", 20), ("warning", "WARNING", 30), ("error", "ERROR", 40),
    ("critical", "CRITICAL", 50),
])
def test_ctx_log_level_methods(rig, method, level, number):
    getattr(rig.ctx.log, method)("m")
    (ev,) = rig.events
    assert (ev["level"], ev["levelno"], ev["msg"]) == (level, number, "m")


@pytest.mark.parametrize("level, name, number", [
    ("warning", "WARNING", 30), ("ERROR", "ERROR", 40), (logging.WARNING, "WARNING", 30), (logging.DEBUG, "DEBUG", 10),
])
def test_ctx_log_accepts_a_level_name_or_number(rig, level, name, number):
    rig.ctx.log("m", level)
    assert (rig.events[-1]["level"], rig.events[-1]["levelno"]) == (name, number)


def test_ctx_log_keeps_the_markup_flag_and_str_converts_the_message(rig):
    rig.ctx.log("[bold]x[/bold]", markup=True)
    rig.ctx.log.info("b", markup=True)
    rig.ctx.log(12345)
    assert [e["markup"] for e in rig.events] == [True, True, False]
    assert rig.events[2]["msg"] == "12345"


def test_ctx_log_is_tagged_and_passes_through_the_emitter_not_the_host_directly(rig):
    rig.dead = True
    rig.ctx.log("ignored")
    assert rig.events == []


# --------------------------------------------------------------------------- progress and status

def test_progress_event_fields(rig):
    rig.ctx.progress(3, 10, "Working", id="step", done=False)
    (ev,) = rig.events
    assert (ev["kind"], ev["id"], ev["label"], ev["current"], ev["total"], ev["done"], ev["job"]) == (
        "progress", "step", "Working", 3, 10, False, 7
    )
    assert validate_event(ev) == []


def test_progress_defaults(rig):
    rig.ctx.progress()
    (ev,) = rig.events
    assert (ev["id"], ev["label"], ev["current"], ev["total"], ev["done"]) == ("default", "", None, None, False)


def test_progress_numbers_are_normalised(rig):
    rig.ctx.progress(2.5, 5.0)
    rig.ctx.progress(float("nan"), float("inf"))
    rig.ctx.progress("not a number", object())  # type: ignore[arg-type]
    rig.ctx.progress(1, 2, done=True)
    cur_tot = [(e["current"], e["total"]) for e in rig.events]
    assert cur_tot == [(2.5, 5.0), (None, None), (None, None), (1, 2)]
    assert rig.events[3]["done"] is True
    assert all(validate_event(e) == [] for e in rig.events)
    assert not any(isinstance(e["current"], float) and math.isnan(e["current"]) for e in rig.events)


def test_status_is_a_progress_with_id_status_and_no_numbers(rig):
    rig.ctx.status("Compiling")
    (ev,) = rig.events
    assert (ev["kind"], ev["id"], ev["label"], ev["current"], ev["total"], ev["done"]) == (
        "progress", "status", "Compiling", None, None, False
    )


# --------------------------------------------------------------------------- the menu proxies (C1-2)

def test_set_menu_refresh_menu_and_go_home_hop_to_the_ui_through_the_host(rig):
    from cli_interface.menu import MenuItem

    root = MenuItem("New")
    rig.ctx.set_menu(root)
    rig.ctx.refresh_menu()
    rig.ctx.go_home()
    assert rig.host.calls == [
        ("set_menu", root), ("set_menu_impl", root),
        ("refresh_menu",), ("refresh_menu_impl",),
        ("go_home",), ("go_home_impl",),
    ]


def test_the_proxies_do_nothing_once_the_job_is_dead(rig):
    from cli_interface.menu import MenuItem

    rig.dead = True
    rig.ctx.set_menu(MenuItem("X"))
    rig.ctx.refresh_menu()
    rig.ctx.go_home()
    assert rig.host.calls == []


def test_an_exception_from_the_ui_call_reaches_the_job(rig):
    def boom(menu):
        raise ValueError("bad menu")

    rig.host.set_menu = boom  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="bad menu"):
        rig.ctx.set_menu("nope")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- ctx.panel goes through the emitter

def test_every_panel_method_is_tagged_with_the_job(rig):
    p = rig.ctx.panel
    p.log("a")
    p.text("b")
    p.rule("c")
    p.json({"k": 1})
    p.table([{"a": 1}])
    p.csv("a,b\n1,2")
    p.array([1])
    p.pretty({1})
    p.renderable(Text("t"))
    p.clear()
    assert len(rig.events) == 10 and {e["job"] for e in rig.events} == {7}


# --------------------------------------------------------------------------- JobEmitter

def test_emitter_tags_the_job_and_does_not_touch_the_callers_event():
    host = Host()
    emitter = JobEmitter(host.emit, 3, [], lambda: False)
    event = make_log("x")
    emitter.emit(event)
    assert "job" not in event and host.events[0]["job"] == 3 and host.events[0] is not event


def test_emitter_without_secrets_passes_payloads_and_obj_through_untouched():
    host = Host()
    emitter = JobEmitter(host.emit, 3, [], lambda: False)
    data = {"k": "v"}
    marker = Text("styled")
    emitter.emit(make_json(data, pretty=True))
    emitter.emit(make_text("plain", obj=marker))
    assert host.events[0]["data"] is data and host.events[0]["pretty"] is True
    assert host.events[1]["obj"] is marker


def test_emitter_goes_silent_the_moment_dead_turns_true():
    state = {"dead": False}
    host = Host()
    emitter = JobEmitter(host.emit, 3, [], lambda: state["dead"])
    emitter.emit(make_log("alive"))
    assert emitter.dead is False
    state["dead"] = True
    emitter.emit(make_log("dead"))
    assert emitter.dead is True and [e["msg"] for e in host.events] == ["alive"]


def test_emitter_masks_secrets_in_every_text_field_and_drops_obj():
    host = Host()
    emitter = JobEmitter(host.emit, 1, ["hunter2"], lambda: False)
    emitter.emit(make_log("pw=hunter2", exc="Traceback hunter2"))
    emitter.emit(make_text("hunter2!", obj=Text("hunter2")))
    emitter.emit({"kind": "progress", "id": "p", "label": "using hunter2", "current": None, "total": None, "done": False,
                  "v": 1, "t": 0.0})
    emitter.emit({"kind": "result", "label": "L hunter2", "status": "ok", "summary": "s hunter2", "exit_code": None,
                  "v": 1, "t": 0.0})
    emitter.emit({"kind": "error", "label": "L hunter2", "message": "m hunter2", "traceback": "t hunter2",
                  "exc_type": None, "exit_code": None, "v": 1, "t": 0.0})
    assert "hunter2" not in json.dumps(host.events, default=str)
    assert host.events[0]["msg"] == "pw=***" and host.events[0]["exc"] == "Traceback ***"
    assert host.events[1]["text"] == "***!" and "obj" not in host.events[1]


@pytest.mark.parametrize("secrets", [[""], ["", ""], [], [None, 5]])
def test_empty_or_non_string_secrets_mask_nothing(secrets):
    host = Host()
    emitter = JobEmitter(host.emit, 1, secrets, lambda: False)  # type: ignore[arg-type]
    event = make_text("untouched", obj=Text("kept"))
    emitter.emit(event)
    assert host.events[0]["text"] == "untouched" and host.events[0]["obj"] is event["obj"]


def test_a_bare_string_is_one_secret():
    host = Host()
    JobEmitter(host.emit, 1, "hunter2", lambda: False).emit(make_log("pw hunter2"))  # type: ignore[arg-type]
    assert host.events[0]["msg"] == "pw ***"


# ---- M1: json / table payloads of a secret job

PLAIN, NUMERIC, QUOTED, UNICODE = "hunter2", "123456", 'q"u\\o', "pässwörd"
SECRETS = [PLAIN, NUMERIC, QUOTED, UNICODE]


def forms(secret: str) -> set[str]:
    return {secret, json.dumps(secret)[1:-1], json.dumps(secret, ensure_ascii=False)[1:-1], repr(secret)[1:-1],
            ascii(secret)[1:-1], repr(repr(secret))[1:-1]}


def leaked(secret: str, events: list[dict[str, Any]]) -> list[str]:
    blob = json.dumps(events, default=str) + "\n" + "\n".join(repr(e) for e in events) + "\n" + "\n".join(
        str(v) for e in events for v in e.values()
    )
    return [form for form in forms(secret) if form and form in blob]


def secret_rig(secret: str) -> Rig:
    return Rig(secrets=[secret])


@pytest.mark.parametrize("secret", SECRETS)
def test_json_payload_of_a_secret_job_is_a_redacted_string(secret):
    r = secret_rig(secret)
    r.panel.json({"token": secret, "list": [1, secret, {"deep": secret}], "tuple": (secret,), "n": 1}, "T")
    (ev,) = r.events
    assert isinstance(ev["data"], str) and ev["pretty"] is False
    assert ev["scroll"] == "top" and ev["job"] == 7 and validate_event(ev) == []
    assert "***" in ev["data"] and leaked(secret, r.events) == []
    assert json.loads(ev["data"])["n"] == 1, "the rest of the payload survives"


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_as_a_dict_key_a_set_member_or_an_int_leaf_is_masked(secret):
    r = secret_rig(secret)
    r.panel.json({secret: "v", "k": {secret}})
    r.panel.array([secret, [secret]])
    r.panel.pretty({"x": secret, secret: [secret]})
    r.panel.json(secret)
    assert len(r.events) == 4 and all(isinstance(e["data"], str) and e["pretty"] is False for e in r.events)
    assert leaked(secret, r.events) == []
    assert all("***" in e["data"] for e in r.events)


def test_an_int_leaf_equal_to_a_numeric_secret_is_masked():
    r = secret_rig(NUMERIC)
    r.panel.json({"pin": 123456, "key": [123456]})
    assert "123456" not in r.events[0]["data"] and "***" in r.events[0]["data"]


@pytest.mark.parametrize("secret", SECRETS)
def test_table_payload_of_a_secret_job_is_redacted_everywhere(secret):
    buf = io.StringIO()
    csv.writer(buf).writerows([["a", "b"], [secret, 2]])
    r = secret_rig(secret)
    r.panel.table([{"name": secret, secret: 1, "n": 5}, {"name": "x"}], title=f"t {secret}")
    r.panel.table([[secret, 2], [3, secret]], headers=["a", secret], title=secret)
    r.panel.csv(buf.getvalue(), title=secret)
    assert [e["kind"] for e in r.events] == ["table", "table", "table"]
    assert leaked(secret, r.events) == []
    first, second, third = r.events
    assert all(isinstance(k, str) and isinstance(v, str) for row in first["rows"] for k, v in row.items())
    assert first["rows"][0] == {"name": "***", "***": "1", "n": "5"} and first["rows"][1] == {"name": "x"}
    assert first["title"] == "t ***" and first["job"] == 7 and validate_event(first) == []
    assert second["rows"] == [["***", "2"], ["3", "***"]] and second["headers"] == ["a", "***"]
    assert third["rows"] == [{"a": "***", "b": "2"}]
    assert all(validate_event(e) == [] for e in r.events)


@pytest.mark.parametrize("secret", SECRETS)
async def test_the_secret_is_gone_from_what_is_actually_rendered(make_app, secret):
    app = make_app(leaf("A", "a"))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        panel = DisplayPanel(emitter=JobEmitter(app.emit, 7, [secret], lambda: False))
        panel.json({"k": secret, secret: [secret]}, secret)
        panel.table([{"c": secret}], title=secret)
        panel.pretty({secret})
        await pilot.pause()
        text = panel_text(app)
    assert "***" in text
    for form in forms(secret):
        assert form not in text, form


def test_non_secret_jobs_keep_the_same_payload_object_and_pretty():
    host = Host()
    emitter = JobEmitter(host.emit, 7, [], lambda: False)
    panel = DisplayPanel(emitter=emitter)
    data = {"k": [1, 2]}
    panel.pretty(data)
    (ev,) = host.events
    assert ev["data"] == data and ev["data"] is not None and ev["pretty"] is True
    direct = make_json(data, pretty=True)
    emitter.emit(direct)
    assert host.events[1]["data"] is data and host.events[1]["pretty"] is True
    assert set(host.events[1]) == set(direct) | {"job"}


def test_secret_job_events_keep_scroll_and_job_and_validate():
    r = secret_rig(PLAIN)
    r.emitter.emit(make_json({"k": PLAIN}, "title", scroll="end"))
    r.emitter.emit(make_table([{"a": PLAIN}], ["a"], scroll="end"))
    assert [e["scroll"] for e in r.events] == ["end", "end"]
    assert all(validate_event(e) == [] and e["job"] == 7 for e in r.events)


@dataclasses.dataclass
class Holder:
    secret: str


@pytest.mark.parametrize("secret", [PLAIN, QUOTED, UNICODE, 'it\'s "both" \\ ok', "tab\there", "emoji \U0001f600 key"])
def test_a_secret_inside_a_dataclass_is_masked_in_every_serialised_spelling(secret):
    r = secret_rig(secret)
    r.panel.json({"obj": Holder(secret)})
    r.panel.pretty(Holder(secret))
    r.panel.table([{"c": Holder(secret)}])
    assert leaked(secret, r.events) == []


def test_exotic_payloads_never_raise_out_of_the_emitter():
    r = secret_rig(PLAIN)
    cyc: list = []
    cyc.append(cyc)

    class Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("no str")

        __repr__ = __str__

    r.panel.json(cyc)
    r.panel.pretty({"x": Unprintable()})
    r.panel.json({(1, "q\"u\\o"): "v"})
    r.emitter.emit({"kind": "table", "rows": 5, "headers": 7, "title": PLAIN, "scroll": "end", "v": 1, "t": 0.0})
    r.emitter.emit({"kind": "json", "data": object(), "title": 3, "pretty": "yes", "v": 1, "t": 0.0})
    assert len(r.events) == 5 and all(e["job"] == 7 for e in r.events)
    assert PLAIN not in json.dumps(r.events, default=str)


def test_a_hand_built_malformed_table_is_replaced_by_an_empty_one_with_a_redacted_title():
    r = secret_rig(PLAIN)
    r.emitter.emit({"kind": "table", "rows": 5, "headers": 7, "title": f"t {PLAIN}", "scroll": "end", "v": 1, "t": 0.0})
    (ev,) = r.events
    assert ev["rows"] == [] and ev["headers"] is None and ev["title"] == "t ***"
