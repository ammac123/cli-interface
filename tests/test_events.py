"""P2.1 / C0-1 / C0-2: the event schema v1 (events.py): shapes, validation, drop policy, JSON lines, redaction."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from cli_interface import events
from cli_interface.events import (
    DROPPABLE_KINDS,
    KINDS,
    LOCAL_KINDS,
    PROTECTED_KINDS,
    SCHEMA_VERSION,
    dumps,
    is_droppable,
    level_number,
    make_action,
    make_clear,
    make_error,
    make_hello,
    make_json,
    make_log,
    make_log_from_record,
    make_progress,
    make_table,
    make_text,
    make_result,
    redact_event,
    redact_text,
    validate_event,
)

BASE = {"v", "t", "kind"}

ALL_EVENTS = {
    "hello": lambda: make_hello("app", version="1.2", pid=42),
    "log": lambda: make_log("m", "warning", logger="x.y"),
    "progress": lambda: make_progress(id="p", label="L", current=1, total=2),
    "text": lambda: make_text("t", style="bold", stream="stderr"),
    "json": lambda: make_json({"a": [1, 2]}, "T", pretty=True, scroll="top"),
    "table": lambda: make_table([{"a": 1}], ["a"], "T"),
    "result": lambda: make_result("L", summary="s", exit_code=0),
    "error": lambda: make_error("L", "m", exc_type="ValueError", traceback="tb"),
    "clear": make_clear,
    "action": lambda: make_action("begin"),
}


# --------------------------------------------------------------------------- the constants

def test_schema_version_and_kind_tables():
    assert SCHEMA_VERSION == 1
    assert KINDS == ("hello", "log", "progress", "text", "json", "table", "result", "error")
    assert LOCAL_KINDS == frozenset({"clear", "action"})
    assert DROPPABLE_KINDS == frozenset({"log", "text"})
    assert PROTECTED_KINDS == frozenset({"hello", "progress", "json", "table", "result", "error", "clear", "action"})
    assert DROPPABLE_KINDS.isdisjoint(PROTECTED_KINDS)


@pytest.mark.parametrize("kind", ["log", "text"])
def test_log_and_text_are_droppable(kind):
    assert is_droppable({"kind": kind})


@pytest.mark.parametrize(
    "event",
    [{"kind": k} for k in ("hello", "progress", "json", "table", "result", "error", "clear", "action", "mystery")]
    + [{}, {"kind": None}, {"kind": 3}, {"kind": ["log"]}],
)
def test_every_other_kind_unknown_kinds_included_is_protected(event):
    assert not is_droppable(event)


@pytest.mark.parametrize(
    "level, number",
    [("DEBUG", 10), ("INFO", 20), ("WARNING", 30), ("ERROR", 40), ("CRITICAL", 50), ("warning", 30), ("Info", 20),
     ("TRACE", 0), ("", 0), ("NOTSET", 0), (30, 0), (None, 0)],
)
def test_level_number(level, number):
    assert level_number(level) == number


def test_level_number_ignores_levels_registered_with_logging():
    logging.addLevelName(5, "TRACE")
    try:
        assert level_number("TRACE") == 0
    finally:
        logging.addLevelName(5, "Level 5")


# --------------------------------------------------------------------------- exact shapes (plan 1.5)

def test_hello_fields():
    ev = make_hello("my-app", version="1.0")
    assert set(ev) == BASE | {"app", "proto", "source", "pid", "version"}
    assert ev["kind"] == "hello" and ev["v"] == 1 and ev["proto"] == 1
    assert ev["app"] == "my-app" and ev["source"] == "inprocess" and ev["version"] == "1.0"
    assert isinstance(ev["pid"], int) and not isinstance(ev["pid"], bool)
    assert make_hello("a", source="subprocess", pid=7)["source"] == "subprocess"
    assert make_hello("a", pid=7)["pid"] == 7
    assert make_hello("a")["version"] is None


def test_log_fields_and_defaults():
    ev = make_log("hi")
    assert set(ev) == BASE | {"level", "levelno", "msg", "logger", "exc", "markup"}
    assert (ev["level"], ev["levelno"], ev["msg"], ev["logger"], ev["exc"], ev["markup"]) == (
        "INFO", 20, "hi", None, None, False
    )


def test_log_uppercases_the_level_and_derives_levelno():
    ev = make_log("m", "warning")
    assert ev["level"] == "WARNING" and ev["levelno"] == 30
    assert make_log("m", "nonsense")["levelno"] == 0
    assert make_log("m", "info", levelno=25)["levelno"] == 25
    assert make_log("m", markup=True)["markup"] is True


def test_log_t_defaults_to_now_and_can_be_given():
    assert make_log("m", t=123.5)["t"] == 123.5
    assert isinstance(make_log("m")["t"], float) and make_log("m")["t"] > 1_000_000_000


def test_progress_fields():
    ev = make_progress(id="x", label="L", current=3, total=10, done=True)
    assert set(ev) == BASE | {"id", "label", "current", "total", "done"}
    assert (ev["id"], ev["label"], ev["current"], ev["total"], ev["done"]) == ("x", "L", 3, 10, True)
    d = make_progress()
    assert (d["id"], d["label"], d["current"], d["total"], d["done"]) == ("default", "", None, None, False)


def test_text_fields_and_obj_only_when_given():
    ev = make_text("t")
    assert set(ev) == BASE | {"text", "style", "markup", "stream", "rule"}
    assert (ev["style"], ev["markup"], ev["stream"], ev["rule"]) == (None, False, None, False)
    marker = object()
    with_obj = make_text("t", obj=marker, rule=True, stream="stdout", markup=True, style="dim")
    assert set(with_obj) == BASE | {"text", "style", "markup", "stream", "rule", "obj"}
    assert with_obj["obj"] is marker and with_obj["rule"] is True and with_obj["stream"] == "stdout"


def test_json_fields():
    data = {"k": [1]}
    ev = make_json(data)
    assert set(ev) == BASE | {"data", "title", "pretty", "scroll"}
    assert ev["data"] is data and ev["title"] == "" and ev["pretty"] is False and ev["scroll"] == "end"
    assert make_json(1, "T", pretty=True, scroll="top")["scroll"] == "top"


def test_table_fields_copy_rows_and_headers_into_lists():
    rows, headers = [{"a": 1}], ("a",)
    ev = make_table(rows, headers, "T")
    assert set(ev) == BASE | {"rows", "headers", "title", "scroll"}
    assert ev["rows"] == rows and ev["rows"] is not rows and ev["headers"] == ["a"]
    assert make_table(iter([[1, 2]]))["rows"] == [[1, 2]]
    assert make_table([])["headers"] is None and make_table([])["scroll"] == "end"


def test_result_fields():
    ev = make_result("L")
    assert set(ev) == BASE | {"label", "status", "summary", "exit_code"}
    assert (ev["status"], ev["summary"], ev["exit_code"]) == ("ok", None, None)
    assert make_result("L", status="cancelled", summary="s", exit_code=3)["status"] == "cancelled"


def test_error_fields():
    ev = make_error("L", "boom")
    assert set(ev) == BASE | {"label", "message", "exc_type", "traceback", "exit_code"}
    assert (ev["label"], ev["message"], ev["exc_type"], ev["traceback"], ev["exit_code"]) == ("L", "boom", None, None, None)


def test_local_only_kinds():
    assert set(make_clear()) == BASE and make_clear()["kind"] == "clear"
    ev = make_action("end")
    assert set(ev) == BASE | {"phase"} and ev["phase"] == "end"


def test_constructors_coerce_text_fields_to_str():
    assert make_log(5)["msg"] == "5"
    assert make_text(5)["text"] == "5"
    assert make_result(5)["label"] == "5"
    assert make_error(5, 6)["message"] == "6"
    assert make_progress(id=1, label=2)["id"] == "1"


@pytest.mark.parametrize("kind", list(ALL_EVENTS))
def test_every_constructor_output_validates(kind):
    ev = ALL_EVENTS[kind]()
    assert ev["kind"] == kind and ev["v"] == 1
    assert validate_event(ev) == []


# --------------------------------------------------------------------------- validate_event negatives

def mutate(event_kind, **changes):
    ev = ALL_EVENTS[event_kind]()
    for key, value in changes.items():
        if value is KeyError:
            del ev[key]
        else:
            ev[key] = value
    return ev


@pytest.mark.parametrize(
    "kind, changes",
    [
        ("log", {"v": 2}),
        ("log", {"v": True}),
        ("log", {"t": float("nan")}),
        ("log", {"t": float("inf")}),
        ("log", {"t": "now"}),
        ("log", {"kind": 3}),
        ("log", {"msg": KeyError}),
        ("log", {"msg": 3}),
        ("log", {"level": "info"}),
        ("log", {"levelno": "20"}),
        ("log", {"levelno": True}),
        ("log", {"logger": 3}),
        ("log", {"exc": 3}),
        ("log", {"markup": "no"}),
        ("log", {"job": "1"}),
        ("log", {"job": True}),
        ("log", {"extra": 1}),
        ("hello", {"source": "elsewhere"}),
        ("hello", {"pid": 1.5}),
        ("hello", {"app": None}),
        ("hello", {"proto": KeyError}),
        ("progress", {"current": "3"}),
        ("progress", {"total": float("nan")}),
        ("progress", {"done": 1}),
        ("progress", {"id": 1}),
        ("text", {"stream": "stdin"}),
        ("text", {"rule": None}),
        ("text", {"style": 1}),
        ("text", {"text": b"x"}),
        ("json", {"scroll": "middle"}),
        ("json", {"pretty": "yes"}),
        ("json", {"data": KeyError}),
        ("json", {"title": 1}),
        ("table", {"rows": "abc"}),
        ("table", {"rows": [1, 2]}),
        ("table", {"headers": [1]}),
        ("table", {"headers": "ab"}),
        ("table", {"scroll": None}),
        ("result", {"status": "error"}),
        ("result", {"summary": 3}),
        ("result", {"exit_code": "0"}),
        ("result", {"exit_code": True}),
        ("error", {"message": KeyError}),
        ("error", {"traceback": 1}),
        ("error", {"exc_type": 1}),
        ("action", {"phase": "middle"}),
        ("clear", {"phase": "begin"}),
    ],
)
def test_validate_event_reports_a_broken_event(kind, changes):
    assert validate_event(mutate(kind, **changes)) != []


def test_validate_event_reports_an_unknown_kind_and_non_mappings():
    assert any("unknown kind" in p for p in validate_event({"v": 1, "t": 1.0, "kind": "mystery"}))
    assert validate_event({}) != []
    assert validate_event("a string") != []  # type: ignore[arg-type]
    assert validate_event(None) != []  # type: ignore[arg-type]
    assert validate_event([("kind", "log")]) != []  # type: ignore[arg-type]


def test_validate_event_names_the_field_and_never_the_value():
    problems = validate_event(mutate("log", msg=12345678))
    assert problems and "msg" in problems[0] and "12345678" not in " ".join(problems)


def test_validate_event_allows_job_everywhere_and_obj_only_on_text():
    for kind in ALL_EVENTS:
        ev = ALL_EVENTS[kind]()
        ev["job"] = 3
        assert validate_event(ev) == [], kind
    ok = mutate("text", obj=object())
    assert validate_event(ok) == []
    assert validate_event(mutate("log", obj=object())) != []


def test_validate_event_accepts_rows_as_dicts_lists_or_tuples():
    for rows in ([{"a": 1}], [[1, 2]], [(1, 2)], []):
        assert validate_event(make_table(rows)) == []


# --------------------------------------------------------------------------- JSON lines

@pytest.mark.parametrize("kind", list(ALL_EVENTS))
def test_dumps_round_trips_every_kind(kind):
    ev = ALL_EVENTS[kind]()
    line = dumps(ev)
    assert "\n" not in line
    assert json.loads(line) == ev


def test_dumps_drops_obj_and_does_not_mutate_the_event():
    marker = object()
    ev = make_text("plain fallback", obj=marker)
    decoded = json.loads(dumps(ev))
    assert "obj" not in decoded and decoded["text"] == "plain fallback"
    assert ev["obj"] is marker


def test_dumps_stringifies_unknown_values():
    decoded = json.loads(dumps(make_json({"when": Path("/x"), "bag": {1}})))
    assert decoded["data"] == {"when": str(Path("/x")), "bag": "{1}"}


def test_dumps_survives_non_string_keys_and_cycles():
    cyc: list = []
    cyc.append(cyc)
    decoded = json.loads(dumps(make_json({(1, 2): "v", 3: cyc})))
    assert decoded["data"] == {"(1, 2)": "v", "3": ["<circular>"]}


def test_dumps_output_is_one_line_even_with_newlines_in_values():
    line = dumps(make_text("a\nb\r\nc"))
    assert "\n" not in line and "\r" not in line
    assert json.loads(line)["text"] == "a\nb\r\nc"


# --------------------------------------------------------------------------- make_log_from_record

def record(msg="m", args=(), level=logging.WARNING, exc_info=None, stack_info=None, name="pkg.mod"):
    rec = logging.LogRecord(name, level, __file__, 10, msg, args, exc_info, None, None)
    rec.stack_info = stack_info
    return rec


def test_log_from_record_carries_logger_levelno_t_and_the_merged_message():
    rec = record("count %d of %s", (3, "x"), logging.ERROR)
    ev = make_log_from_record(rec)
    assert validate_event(ev) == []
    assert (ev["msg"], ev["level"], ev["levelno"], ev["logger"], ev["exc"]) == ("count 3 of x", "ERROR", 40, "pkg.mod", None)
    assert ev["t"] == rec.created and ev["markup"] is False


def test_log_from_record_msg_is_not_a_formatted_line():
    ev = make_log_from_record(record("plain"))
    assert ev["msg"] == "plain"
    assert "WARNING" not in ev["msg"] and "pkg.mod" not in ev["msg"]


def test_log_from_record_formats_the_exception_into_exc_text_not_an_object():
    try:
        raise ValueError("kaboom")
    except ValueError:
        rec = record("failed", exc_info=sys.exc_info())
    ev = make_log_from_record(rec)
    assert isinstance(ev["exc"], str) and ev["exc"].startswith("Traceback") and "ValueError: kaboom" in ev["exc"]
    assert ev["msg"] == "failed"
    assert rec.exc_text is None, "the record is not mutated"
    dumps(ev)


def test_log_from_record_reuses_cached_exc_text_and_skips_empty_exc_info():
    rec = record("m")
    rec.exc_text = "cached trace"
    assert make_log_from_record(rec)["exc"] == "cached trace"
    assert make_log_from_record(record("m", exc_info=(None, None, None)))["exc"] is None


def test_log_from_record_appends_stack_info():
    ev = make_log_from_record(record("m", stack_info="Stack (most recent call last):\n  File x"))
    assert ev["exc"] is not None and "Stack (most recent call last)" in ev["exc"]


def test_log_from_record_with_bad_percent_args_propagates_like_the_stdlib():
    with pytest.raises(TypeError):
        make_log_from_record(record("%d", ("not a number",)))


def test_log_from_record_unregistered_level_name():
    rec = record("m", level=7)
    assert make_log_from_record(rec)["levelno"] == 7


# --------------------------------------------------------------------------- redaction

def test_redact_text_replaces_every_secret_longest_first():
    assert redact_text("pass and password", ["pass", "password"]) == "*** and ***"
    assert redact_text("abc", ["abc", "abcd"]) == "***"
    assert redact_text("a-b-a", ["a"]) == "***-b-***"


@pytest.mark.parametrize("secrets", [[], [""], ["", ""]])
def test_redact_text_with_nothing_to_hide_returns_the_text_unchanged(secrets):
    assert redact_text("untouched", secrets) == "untouched"


def test_redact_text_treats_a_bare_string_as_one_secret_and_ignores_non_strings():
    assert redact_text("my secret here", "secret") == "my *** here"
    assert redact_text("12345 x", [12345, "x"]) == "12345 ***"  # type: ignore[list-item]


def test_redact_text_is_literal_not_a_regex():
    assert redact_text("a.c abc [x] (y)", [".", "[x]", "(y)"]) == "a***c abc *** ***"


def test_redact_text_a_short_secret_cannot_match_inside_the_mask():
    assert redact_text("a*b", ["*"]) == "a***b"


def test_redact_text_accepts_a_generator():
    assert redact_text("x y", (s for s in ["y"])) == "x ***"


REDACTED_FIELDS = {
    "log": ("msg", "exc"),
    "text": ("text",),
    "progress": ("label",),
    "result": ("label", "summary"),
    "error": ("label", "message", "traceback"),
}


@pytest.mark.parametrize("kind, fields", REDACTED_FIELDS.items())
def test_redact_event_masks_exactly_the_listed_string_fields(kind, fields):
    base = {
        "log": make_log("S-msg", logger="S-logger", exc="S-exc"),
        "text": make_text("S-text", style="S-style"),
        "progress": make_progress(id="S-id", label="S-label"),
        "result": make_result("S-label", summary="S-summary"),
        "error": make_error("S-label", "S-message", exc_type="S-type", traceback="S-tb"),
    }[kind]
    out = redact_event(base, ["S"])
    for name, value in base.items():
        if name in fields:
            assert out[name] == value.replace("S", "***"), name
        else:
            assert out[name] == value, name


def test_redact_event_returns_a_copy_and_never_mutates_the_input():
    ev = make_log("secret!")
    out = redact_event(ev, ["secret"])
    assert out is not ev and ev["msg"] == "secret!" and out["msg"] == "***!"
    assert redact_event(ev, []) is not ev


def test_redact_event_leaves_json_table_clear_and_unknown_kinds_alone():
    payload = {"k": "secret"}
    ev = make_json(payload)
    assert redact_event(ev, ["secret"])["data"] is payload
    tbl = make_table([{"a": "secret"}])
    assert redact_event(tbl, ["secret"])["rows"] == [{"a": "secret"}]
    assert redact_event({"kind": "mystery", "msg": "secret"}, ["secret"])["msg"] == "secret"
    assert redact_event({"msg": "secret"}, ["secret"]) == {"msg": "secret"}


def test_redact_event_ignores_non_string_field_values_and_empty_secrets():
    ev = make_result("L", summary=None)
    assert redact_event(ev, ["x"])["summary"] is None
    assert redact_event(make_log("hello"), [""])["msg"] == "hello"


# --------------------------------------------------------------------------- the module is standalone

def test_events_loads_standalone_without_textual_or_rich(tmp_path):
    script = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('events_standalone', {str(Path(events.__file__))!r})\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['events_standalone'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "ev = mod.make_log('hi')\n"
        "assert mod.validate_event(ev) == [] and mod.dumps(ev)\n"
        "bad = [m for m in sys.modules if m.split('.')[0] in ('textual', 'rich', 'cli_interface')]\n"
        "assert not bad, bad\n"
        "print('OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=30, cwd=tmp_path
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "OK", proc.stderr
