"""P2.2 / F5: what a finished job shows: the return-value mapping (value_events) and the error event."""
from __future__ import annotations

import collections
import types
from typing import Any

import pytest
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from cli_interface import jobs, outcome
from cli_interface.events import validate_event
from cli_interface.outcome import exception_event, value_events


class StrSub(str):
    pass


class Multiline:
    def __str__(self) -> str:
        return "first\nsecond"


class BrokenStr:
    def __str__(self) -> str:
        raise RuntimeError("no str for you")

    def __repr__(self) -> str:
        return "<BrokenStr>"


class Broken:
    def __str__(self) -> str:
        raise RuntimeError("no str")

    def __repr__(self) -> str:
        raise RuntimeError("no repr either")


def kinds(events: list[dict[str, Any]]) -> list[str]:
    return [e["kind"] for e in events]


# --------------------------------------------------------------------------- no content, a one-line summary

@pytest.mark.parametrize("value", [None, "", ])
def test_none_and_empty_string_have_no_summary_and_no_events(value):
    assert value_events(value, secret=False) == ([], None)


@pytest.mark.parametrize(
    "value, summary",
    [
        ("done", "done"),
        ("  padded  ", "  padded  "),
        (StrSub("subclass"), "subclass"),
        ("x" * 10_000, "x" * 10_000),
        (42, "42"),
        (1.5, "1.5"),
        (True, "True"),
        (False, "False"),
        (0, "0"),
        (b"ab", "b'ab'"),
        (bytearray(b"a"), "bytearray(b'a')"),
        (BrokenStr(), "<BrokenStr>"),
        (Broken(), "<Broken>"),
        ({}, "{}"),
        ([], "[]"),
        ((), "()"),
        (set(), "set()"),
        (frozenset(), "frozenset()"),
        (collections.OrderedDict(), "OrderedDict()"),
    ],
)
def test_single_line_values_become_the_summary_with_no_content_events(value, summary):
    assert value_events(value, secret=False) == ([], summary)


def test_a_str_subclass_is_treated_as_a_plain_string():
    events, summary = value_events(StrSub("a\nb"), secret=False)
    assert kinds(events) == ["text"] and events[0]["text"] == "a\nb" and summary is None


# --------------------------------------------------------------------------- a text block

@pytest.mark.parametrize("value, text", [("a\nb", "a\nb"), ("line\n", "line\n"), ("\n", "\n"), (Multiline(), "first\nsecond")])
def test_a_value_with_a_newline_becomes_a_text_block_and_no_summary(value, text):
    events, summary = value_events(value, secret=False)
    assert kinds(events) == ["text"] and summary is None
    assert events[0]["text"] == text and events[0]["markup"] is False and "obj" not in events[0]
    assert validate_event(events[0]) == []


# --------------------------------------------------------------------------- json

@pytest.mark.parametrize(
    "value",
    [{"a": 1}, [1, 2], (1, 2), [[1, 2], [3]], [{"a": 1}, 2], [{}], {"a": [1, {"b": 2}]}, {1: 2},
     collections.OrderedDict(a=1), types.MappingProxyType({"a": 1}), [None], ["a", "b"]],
)
def test_mappings_and_sequences_become_one_json_block_scrolled_to_the_end(value):
    events, summary = value_events(value, secret=False)
    assert kinds(events) == ["json"] and summary is None
    ev = events[0]
    assert ev["scroll"] == "end" and ev["pretty"] is False and ev["title"] == ""
    assert ev["data"] == dict(value) if isinstance(value, types.MappingProxyType) else ev["data"] == value
    assert validate_event(ev) == []


@pytest.mark.parametrize("value", [{1}, frozenset({1}), {"a": object()}, [object()], {"k": {1}}])
def test_a_value_json_cannot_encode_is_a_pretty_block(value):
    events, summary = value_events(value, secret=False)
    assert kinds(events) == ["json"] and events[0]["pretty"] is True and summary is None


def test_the_json_payload_is_a_shallow_copy_not_the_callers_object():
    original = {"a": 1}
    (ev,), _ = value_events(original, secret=False)
    assert ev["data"] == original and ev["data"] is not original
    biglist = [1, 2]
    (ev,), _ = value_events(biglist, secret=False)
    assert ev["data"] is not biglist


# --------------------------------------------------------------------------- tables

def test_a_list_of_dicts_is_a_table_with_the_first_rows_keys_as_headers():
    rows = [{"name": "a", "n": 1}, {"name": "b", "n": 2, "extra": 3}]
    events, summary = value_events(rows, secret=False)
    assert kinds(events) == ["table"] and summary is None
    ev = events[0]
    assert ev["headers"] == ["name", "n"] and ev["rows"] == rows and ev["scroll"] == "end" and ev["title"] == ""
    assert validate_event(ev) == []


def test_a_tuple_of_dicts_is_a_table_too():
    assert kinds(value_events(({"a": 1},), secret=False)[0]) == ["table"]


def test_table_keys_become_strings():
    (ev,), _ = value_events([{1: "x"}], secret=False)
    assert ev["headers"] == ["1"] and ev["rows"] == [{"1": "x"}]


@pytest.mark.parametrize("value", [[[1, 2], [3, 4]], [{"a": 1}, 2], [{"a": 1}, [2]], [{}], [{}, {}]])
def test_anything_that_is_not_all_non_empty_dicts_is_json_not_a_table(value):
    assert kinds(value_events(value, secret=False)[0]) == ["json"]


# --------------------------------------------------------------------------- rich renderables

def test_a_text_is_kept_as_obj_with_its_plain_fallback():
    value = Text("styled", style="bold red")
    events, summary = value_events(value, secret=False)
    assert kinds(events) == ["text"] and summary is None
    assert events[0]["obj"] is value and events[0]["text"] == "styled"
    assert validate_event(events[0]) == []


@pytest.mark.parametrize("value", [Panel("x"), Table(), Syntax("x = 1", "python")])
def test_other_renderables_keep_obj_and_fall_back_to_their_type_name(value):
    events, summary = value_events(value, secret=False)
    assert kinds(events) == ["text"] and summary is None
    assert events[0]["obj"] is value and events[0]["text"] == f"<{type(value).__name__}>"


def test_str_wins_over_renderable():
    assert value_events("plain", secret=False) == ([], "plain")


# --------------------------------------------------------------------------- secret jobs and robustness

@pytest.mark.parametrize("value", ["pw", {"k": "pw"}, [{"a": "pw"}], Text("pw"), 5, "a\nb", b"pw"])
def test_a_secret_job_shows_no_return_value_at_all(value):
    assert value_events(value, secret=True) == ([], None)


def test_value_events_never_raises():
    class Hostile(dict):
        def __bool__(self):
            raise RuntimeError("no bool")

    assert value_events(Hostile(a=1), secret=False) == ([], "{'a': 1}")


def test_a_cyclic_value_does_not_raise():
    cyc: list = []
    cyc.append(cyc)
    events, _ = value_events(cyc, secret=False)
    assert kinds(events) == ["json"] and events[0]["pretty"] is True


# --------------------------------------------------------------------------- the error event (F5)

def assert_no_runner_frames(trace: str) -> None:
    for module in (jobs, outcome):
        assert f'File "{module.__file__}"' not in trace, module.__name__


def forged(filename: str, body: str = "raise ValueError('inner')") -> Any:
    """A function whose frame claims to live in ``filename`` (a runner file)."""
    namespace: dict[str, Any] = {}
    exec(compile(f"def boom():\n    {body}\n", filename, "exec"), namespace)  # noqa: S102
    return namespace["boom"]


def test_exception_event_shape():
    try:
        raise KeyError("missing")
    except KeyError as exc:
        ev = exception_event(exc, "My label", [])
    assert validate_event(ev) == []
    assert ev["kind"] == "error" and ev["label"] == "My label" and ev["message"] == "'missing'"
    assert ev["exc_type"] == "KeyError" and ev["exit_code"] is None
    assert ev["traceback"].startswith("Traceback (most recent call last):") and ev["traceback"].rstrip().endswith("KeyError: 'missing'")


def test_the_traceback_has_no_runner_frames():
    boom_jobs, boom_outcome = forged(jobs.__file__), forged(outcome.__file__)

    def caller():
        boom_jobs()

    def caller2():
        boom_outcome()

    for fn in (caller, caller2):
        try:
            fn()
        except ValueError as exc:
            ev = exception_event(exc, "L", [])
        trace = ev["traceback"]
        assert_no_runner_frames(trace)
        assert "test_outcome.py" in trace and "ValueError: inner" in trace


def test_runner_frames_are_trimmed_from_chained_causes_too():
    boom = forged(jobs.__file__, "raise OSError('root cause')")
    try:
        try:
            boom()
        except OSError as root:
            raise RuntimeError("wrapper") from root
    except RuntimeError as exc:
        trace = exception_event(exc, "L", [])["traceback"]
    assert_no_runner_frames(trace)
    assert "OSError: root cause" in trace and "RuntimeError: wrapper" in trace
    assert "direct cause of the following exception" in trace


def test_runner_frames_are_trimmed_from_implicit_contexts_and_exception_groups():
    boom = forged(outcome.__file__, "raise OSError('ctx')")
    try:
        try:
            boom()
        except OSError:
            raise RuntimeError("during handling")  # noqa: B904
    except RuntimeError as exc:
        trace = exception_event(exc, "L", [])["traceback"]
    assert_no_runner_frames(trace)
    assert "OSError: ctx" in trace
    assert "During handling of the above exception" in trace
    try:
        raise ExceptionGroup("group", [_raise(boom)])
    except ExceptionGroup as exc:
        trace = exception_event(exc, "L", [])["traceback"]
    assert_no_runner_frames(trace)
    assert "OSError: ctx" in trace and "ExceptionGroup: group" in trace


def _raise(fn):
    try:
        fn()
    except Exception as exc:
        return exc
    raise AssertionError("did not raise")


def test_chained_causes_and_contexts_are_kept():
    try:
        try:
            raise ValueError("first")
        except ValueError as first:
            raise TypeError("second") from first
    except TypeError as exc:
        trace = exception_event(exc, "L", [])["traceback"]
    assert trace.index("ValueError: first") < trace.index("TypeError: second")


def test_a_trace_made_only_of_runner_frames_is_kept_rather_than_emptied():
    boom = forged(jobs.__file__)
    try:
        boom()
    except ValueError as exc:
        exc.__traceback__ = exc.__traceback__.tb_next  # only the forged frame is left
        trace = exception_event(exc, "L", [])["traceback"]
    assert "ValueError: inner" in trace


def test_secrets_are_masked_in_label_message_and_traceback():
    def leak():
        raise ValueError("bad token hunter2 in request")

    try:
        leak()
    except ValueError as exc:
        ev = exception_event(exc, "Login hunter2", ["hunter2"])
    assert "hunter2" not in repr(ev)
    assert ev["label"] == "Login ***" and ev["message"] == "bad token *** in request"
    assert "bad token *** in request" in ev["traceback"]


def test_a_secret_in_a_raise_from_chain_is_masked_everywhere():
    try:
        try:
            raise ConnectionError("password=hunter2 refused")
        except ConnectionError as inner:
            raise RuntimeError("login failed") from inner
    except RuntimeError as exc:
        ev = exception_event(exc, "L", ["hunter2"])
    assert "hunter2" not in repr(ev) and "password=*** refused" in ev["traceback"]


def test_a_local_variable_never_appears_in_the_traceback():
    def handler():
        api_key = "LOCAL-VALUE-12345"
        raise ValueError(f"failed ({len(api_key)} chars)")

    try:
        handler()
    except ValueError as exc:
        trace = exception_event(exc, "L", [])["traceback"]
    assert "LOCAL-VALUE-12345" not in trace and "api_key =" not in trace.replace('api_key = "LOCAL', "")


def test_a_huge_message_and_traceback_are_capped_with_head_and_tail_kept():
    big = "H" * 20_000 + "M" * 200_000 + "T" * 20_000
    try:
        raise ValueError(big)
    except ValueError as exc:
        ev = exception_event(exc, "L", [])
    for field in ("message", "traceback"):
        value = ev[field]
        assert len(value) <= 50_000
        assert "middle omitted" in value
    assert ev["message"].startswith("H") and ev["message"].endswith("T")
    assert ev["traceback"].rstrip().endswith("T")


def test_an_exception_whose_str_raises_still_gives_an_event():
    class Odd(Exception):
        def __str__(self) -> str:
            raise RuntimeError("no str")

    try:
        raise Odd()
    except Odd as exc:
        ev = exception_event(exc, "L", [])
    assert validate_event(ev) == [] and ev["exc_type"] == "Odd" and ev["message"]


def test_exception_event_without_a_traceback_object():
    ev = exception_event(ValueError("never raised"), "L", [])
    assert ev["message"] == "never raised" and "ValueError: never raised" in ev["traceback"]


def test_no_show_locals_anywhere_in_the_package():
    import ast
    from pathlib import Path

    package = Path(outcome.__file__).parent
    found = []
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.keyword) and node.arg in ("show_locals", "capture_locals"):
                value = node.value
                if not (isinstance(value, ast.Constant) and value.value is False):
                    found.append(f"{path.name}:{node.lineno}")
    assert found == []
