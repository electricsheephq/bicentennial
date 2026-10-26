"""Spike S1 shape test: offline, deterministic, stdlib only. Ready for a CI job (the repository has none yet).

The fixtures are minimized request shapes recorded on the pinned harness versions (no harness or life text):
every one must classify to its expected role, and deliberately unseen shapes must classify as unknown.
"""

import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import roles

FIX = json.loads((HERE / "fixtures" / "shapes.json").read_text())
SOURCES = {s["source"]: s for s in FIX["sources"]}
TOOLS = [{"type": "function", "function": {"name": "memory"}}]


@pytest.mark.parametrize("name", sorted(SOURCES))
def test_every_recorded_request_classifies_to_its_role(name):
    src = SOURCES[name]
    got = roles.walk(roles.Context.of(src["ctx"]), src["rows"])
    wrong = [(r["seq"], r["expected"], g) for r, g in zip(src["rows"], got, strict=True) if g[0] != r["expected"]]
    assert not wrong
    assert all(g[1] in roles.METHODS and g[0] in roles.ROLES for g in got)
    n_comp = sum(g[0] == "compaction" for g in got)
    if src["harness_compactions"] is not None:  # the harness's own markers count the same compactions
        assert n_comp == src["harness_compactions"]


def test_coverage_of_the_pinned_harnesses():
    seen = {(s["harness"], r["expected"]) for s in FIX["sources"] for r in s["rows"]}
    for h in ("hermes-glm", "hermes-sol", "claude-code", "codex"):
        assert (h, "compaction") in seen and (h, "replay_main") in seen
    assert {("hermes-glm", "title"), ("hermes-sol", "title"), ("hermes-glm", "write_turn"),
            ("hermes-sol", "probe_main"), ("claude-code", "aux")} <= seen


def test_fixtures_hold_no_text():
    def strings(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from strings(v)
        elif isinstance(o, list):
            for v in o:
                yield from strings(v)
        elif isinstance(o, str):
            yield o
    for s in FIX["sources"]:
        for v in strings(s):
            assert re.fullmatch(r"[\w./:@?=,+-]{0,512}", v), v


# ---- unseen shapes fail closed ----------------------------------------------------------------------------
def chat(*msgs, tools=TOOLS, path="/main/v1/chat/completions", model="m"):
    return {"method": "POST", "path": path, "body": {"model": model, "messages": list(msgs), "tools": tools}}


def ctx1(text="scripted turn one", **kw):
    return roles.Context(expected=[{"kind": "replay", "hash": roles.h16(text)}], **kw)


@pytest.mark.parametrize("req", [
    chat({"role": "user", "content": "an unscripted turn"}),  # main frame, not the cursor's turn
    chat({"role": "user", "content": "scripted turn one"}, tools=[]),  # the turn, but no tools: not the main frame
    chat({"role": "user", "content": "x"}, {"role": "assistant", "tool_calls": [{"id": "never-issued"}]},
         {"role": "tool", "tool_call_id": "never-issued", "content": "r"}),  # a call id nobody issued
    {"method": "POST", "path": "/v1/embeddings", "body": {"input": "x"}},  # an unknown wire
    {"method": "GET", "path": "/v1/files", "body": None},  # an unknown GET
    {"method": "POST", "path": "/v1/responses", "body": {"model": "m", "input": "a fresh shape"}},
    {"method": "POST", "path": "/v1/messages", "body": {"model": "m", "messages": [
        {"role": "user", "content": [{"type": "text", "text": "an unseen anthropic shape"}]}]}},
])
def test_unseen_shapes_are_unknown(req):
    assert roles.classify(req, ctx1())[:2] == ("unknown", "unknown")


def test_conflicting_evidence_fails_closed():
    title = roles.Signature("t", "title", "system", 6, roles.h16("Title:"))
    comp = roles.Signature("c", "compaction", "last_user", 8, roles.h16("Compact!"))
    c = ctx1(signatures=(title, comp), aliases={"summ": roles.alias("compaction")})
    both = chat({"role": "system", "content": "Title: x"}, {"role": "user", "content": "Compact! now"})
    assert roles.classify(both, c)[0] == "unknown"  # two marker roles
    on_alias = chat({"role": "system", "content": "Title: x"}, {"role": "user", "content": "y"}, model="summ")
    assert roles.classify(on_alias, c)[0] == "unknown"  # a title marker on a compaction-only alias
    # the scripted turn carried inside a compaction request is not a cursor match (Claude Code's auto-compaction)
    inside = chat({"role": "user", "content": [{"type": "text", "text": "scripted turn one"},
                                               {"type": "text", "text": "Compact! summarise"}]})
    assert roles.classify(inside, c)[:2] == ("compaction", "shape")


# ---- the rule on synthetic bodies, one per wire -------------------------------------------------------------
def test_cursor_retry_issued_ids_and_aliases_chat():
    c = ctx1(path_aliases={"/aux/compression/": roles.alias("compaction")},
             aliases={"mem-summary": roles.alias("summariser"), "mem-extract": roles.alias("extraction"),
                      "fast": roles.alias("aux", "title")})
    turn = chat({"role": "system", "content": "s"}, {"role": "user", "content": "  scripted turn one\n"})
    res = roles.classify(turn, c)
    assert res[:2] == ("replay_main", "cursor")
    roles.advance(c, res, ["call_1"], "write_turn")
    assert roles.classify(turn, c)[:2] == ("replay_main", "cursor")  # the same turn again: a retry
    back = chat({"role": "user", "content": "scripted turn one"}, {"role": "assistant", "tool_calls": [{"id": "call_1"}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "ok"})
    assert roles.classify(back, c)[:2] == ("write_turn", "cursor")
    other = {"role": "user", "content": "q"}
    assert roles.classify(chat(other, tools=[], path="/aux/compression/v1/chat/completions"), c)[:2] == (
        "compaction", "model_alias")
    assert roles.classify(chat(other, model="mem-summary"), c)[0] == "summariser"
    assert roles.classify(chat(other, model="mem-extract"), c)[0] == "extraction"
    assert roles.classify(chat(other, model="fast"), c)[0] == "aux"
    title = roles.Signature("t", "title", "system", 6, roles.h16("Title:"))
    c.signatures = (title,)
    assert roles.classify(chat({"role": "system", "content": "Title: x"}, other, model="fast"), c)[:2] == (
        "title", "model_alias")


def test_responses_wire():
    comp = roles.Signature("c", "compaction", "last_user", 8, roles.h16("Compact!"))
    c = ctx1(signatures=(comp,))
    tools = [{"type": "function", "name": "shell"}]
    msg = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "scripted turn one"}]}
    req = {"method": "POST", "path": "/v1/responses", "body": {"model": "m", "input": [msg], "tools": tools}}
    res = roles.classify(req, c)
    assert res[:2] == ("replay_main", "cursor")
    roles.advance(c, res, ["call_9"])
    out = [msg, {"type": "function_call", "call_id": "call_9"}, {"type": "function_call_output", "call_id": "call_9"}]
    assert roles.classify(dict(req, body={"model": "m", "input": out, "tools": tools}), c)[:2] == ("replay_main", "cursor")
    ask = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Compact! please"}]}
    assert roles.classify(dict(req, body={"model": "m", "input": [msg, ask]}), c)[:2] == ("compaction", "shape")
    assert roles.classify({"method": "POST", "path": "/v1/responses/compact", "body": {}}, c)[:2] == (
        "compaction", "shape")


def test_anthropic_wire_trailing_system_and_continuation():
    note = roles.Signature("n", roles.CONTINUATION, "last_user", 7, roles.h16("[notice"))
    c = ctx1(signatures=(note,))
    tools = [{"name": "Bash"}]
    user = {"role": "user", "content": [{"type": "text", "text": "<reminder>"}, {"type": "text", "text": "scripted turn one"}]}
    env = {"role": "system", "content": "environment"}  # mid-conversation system context is not a turn
    req = {"method": "POST", "path": "/v1/messages", "body": {"model": "m", "messages": [user, env], "tools": tools}}
    res = roles.classify(req, c)
    assert res[:2] == ("replay_main", "cursor")
    roles.advance(c, res, ["toolu_1"])
    use = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1"}]}
    result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1"}]}
    body = {"model": "m", "messages": [user, use, result, env], "tools": tools}
    assert roles.classify(dict(req, body=body), c)[:2] == ("replay_main", "cursor")
    ping = {"role": "user", "content": [{"type": "text", "text": "[notice] a background task finished"}]}
    body = {"model": "m", "messages": [user, {"role": "assistant", "content": "a"}, ping], "tools": tools}
    assert roles.classify(dict(req, body=body), c)[2]["turn"] == roles.CONTINUATION
    assert roles.classify(dict(req, body=body), roles.Context(signatures=(note,)))[0] == "unknown"
    assert roles.classify({"method": "POST", "path": "/v1/messages/count_tokens", "body": {}}, c)[0] == "aux"


def test_shape_keeps_no_text():
    s = roles.shape(chat({"role": "system", "content": "secret system text"}, {"role": "user", "content": "hello"}))
    assert "secret" not in json.dumps(s) and "hello" not in json.dumps(s)
    assert s["seq"] == "su" and s["len"] == {"system": 18, "last_user": 5}
