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


@pytest.mark.parametrize("role", ["system", "developer"])
def test_responses_system_text_in_input_is_read_for_markers(role):
    title = roles.Signature("t", "title", "system", 6, roles.h16("Title:"))
    c = ctx1(signatures=(title,))
    tools = [{"type": "function", "name": "shell"}]
    turn = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "scripted turn one"}]}
    sys_msg = {"type": "message", "role": role, "content": [{"type": "input_text", "text": "Title: x"}]}
    via_input = {"method": "POST", "path": "/v1/responses", "body": {"model": "m", "input": [sys_msg, turn],
                                                                     "tools": tools}}
    via_field = {"method": "POST", "path": "/v1/responses", "body": {"model": "m", "instructions": "Title: x",
                                                                     "input": [turn], "tools": tools}}
    assert roles.classify(via_input, c)[:2] == roles.classify(via_field, c)[:2] == ("title", "shape")


@pytest.mark.parametrize("body", [
    {"model": "m", "messages": [{"role": "user", "content": "scripted turn one"},
                                {"role": "assistant", "tool_calls": ["not-a-dict"]},
                                {"role": "tool", "tool_call_id": "x", "content": "r"}], "tools": TOOLS},
    {"model": "m", "messages": [{"role": "user", "content": "scripted turn one"},
                                {"role": "assistant", "tool_calls": 7},
                                {"role": "tool", "tool_call_id": "x", "content": "r"}], "tools": TOOLS},
    {"model": ["m"], "messages": [{"role": "user", "content": "scripted turn one"}], "tools": TOOLS},
    {"model": "m", "messages": [{"role": "user", "content": "scripted turn one"}], "tools": 3},
])
def test_malformed_chat_bodies_are_unknown(body):
    req = {"method": "POST", "path": "/v1/chat/completions", "body": body}
    assert roles.classify(req, ctx1(aliases={"fast": roles.alias("aux")}))[:2] == ("unknown", "unknown")


TURN = {"role": "user", "content": "scripted turn one"}
RTOOLS = [{"type": "function", "name": "shell"}]
WIRE_PATH = {"openai_chat": "/v1/chat/completions", "openai_responses": "/v1/responses", "anthropic": "/v1/messages"}


def _wire_body(wire: str, items: list, **kw) -> dict:
    key = "input" if wire == "openai_responses" else "messages"
    return {"method": "POST", "path": WIRE_PATH[wire], "body": {"model": "m", key: items, "tools": RTOOLS, **kw}}


@pytest.mark.parametrize("wire", sorted(WIRE_PATH))
def test_non_object_elements_and_content_parts_are_unknown(wire):
    c = ctx1()
    assert roles.classify(_wire_body(wire, [TURN]), c)[0] == "replay_main"
    assert roles.classify(_wire_body(wire, [TURN, 1]), c)[:2] == ("unknown", "unknown")
    part = {"type": "input_text" if wire == "openai_responses" else "text", "text": "scripted turn one"}
    assert roles.classify(_wire_body(wire, [{"role": "user", "content": [part]}]), c)[0] == "replay_main"
    assert roles.classify(_wire_body(wire, [{"role": "user", "content": [part, 1]}]), c)[:2] == ("unknown", "unknown")


@pytest.mark.parametrize("bad", [{"role": "user", "content": "x"}, False, 7])
def test_responses_input_of_an_unseen_type_is_unknown(bad):
    title = roles.Signature("t", "title", "system", 6, roles.h16("Title:"))
    req = {"method": "POST", "path": "/v1/responses", "body": {"model": "m", "input": bad, "instructions": "Title: x"}}
    assert roles.classify(req, ctx1(signatures=(title,)))[:2] == ("unknown", "unknown")
    req["body"]["input"] = "x"
    assert roles.classify(req, ctx1(signatures=(title,)))[:2] == ("title", "shape")


def _batch(wire: str, sibling) -> list:
    """A scripted turn, then one call batch answering an issued call and a sibling whose id is `sibling`."""
    if wire == "openai_chat":
        return [TURN, {"role": "assistant", "tool_calls": [{"id": "issued"}, {"id": sibling}]},
                {"role": "tool", "tool_call_id": "issued", "content": "r"},
                {"role": "tool", "tool_call_id": sibling, "content": "r"}]
    if wire == "openai_responses":
        return [TURN, {"type": "function_call", "call_id": "issued"}, {"type": "function_call", "call_id": sibling},
                {"type": "function_call_output", "call_id": "issued"},
                {"type": "function_call_output", "call_id": sibling}]
    return [TURN, {"role": "assistant", "content": [{"type": "tool_use", "id": "issued"},
                                                     {"type": "tool_use", "id": sibling}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "issued"},
                                         {"type": "tool_result", "tool_use_id": sibling}]}]


@pytest.mark.parametrize("wire", sorted(WIRE_PATH))
@pytest.mark.parametrize("sibling", [2, None, ""])
def test_call_ids_that_are_not_non_empty_strings_are_unknown(wire, sibling):
    c = ctx1()
    c.issued["issued"] = "probe_main"
    assert roles.classify(_wire_body(wire, _batch(wire, "sib")), c)[:2] == ("probe_main", "cursor")
    assert roles.classify(_wire_body(wire, _batch(wire, sibling)), c)[:2] == ("unknown", "unknown")


def test_a_result_with_no_id_answers_nothing():
    c = ctx1()
    c.issued["issued"] = "probe_main"
    s = roles.shape(_wire_body("openai_responses", _batch("openai_responses", "sib")))
    assert roles.classify_shape(s, c)[0] == "probe_main"
    s |= {"tail_ids": ["issued", ""], "tail_calls": ["issued", ""]}
    assert roles.classify_shape(s, c)[:2] == ("unknown", "unknown")
    items = [TURN, {"type": "function_call", "call_id": "issued"}, {"type": "function_call"},  # an id-less sibling call
             {"type": "function_call_output", "call_id": "issued"}]
    assert roles.classify(_wire_body("openai_responses", items), c)[:2] == ("unknown", "unknown")


@pytest.mark.parametrize("wire", sorted(WIRE_PATH))
def test_non_string_roles_types_and_texts_are_unknown(wire):
    c = ctx1()
    kind = "input_text" if wire == "openai_responses" else "text"
    ok = {"role": "user", "content": [{"type": kind, "text": "scripted turn one"}]}
    assert roles.classify(_wire_body(wire, [{"role": "user", "content": "other"}, ok]), c)[0] == "replay_main"
    bad = [[{"role": 7, "content": "other"}, ok], [{"content": "other"}, ok],
           [{"role": "user", "content": [*ok["content"], {"type": 7, "text": "ignored"}]}],
           [{"role": "user", "content": [*ok["content"], {"text": "ignored"}]}],
           [{"role": "user", "content": [*ok["content"], {"type": kind, "text": 5}]}]]
    bad += [[{"type": 7}, ok]] if wire == "openai_responses" else []
    for items in bad:
        assert roles.classify(_wire_body(wire, items), ctx1())[:2] == ("unknown", "unknown"), items


@pytest.mark.parametrize("wire", sorted(WIRE_PATH))
@pytest.mark.parametrize("tools", [[1], ["shell"], [{}, None]])
def test_tool_lists_must_hold_objects(wire, tools):
    assert roles.classify(_wire_body(wire, [TURN], tools=[{}]), ctx1())[0] == "replay_main"
    assert roles.classify(_wire_body(wire, [TURN], tools=tools), ctx1())[:2] == ("unknown", "unknown")


def test_malformed_anthropic_parts_are_unknown():
    body = {"model": "m", "messages": [{"role": "user", "content": "x"},
                                       {"role": "assistant", "content": ["bare", {"type": "tool_use", "id": "a"}]},
                                       {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "a"},
                                                                    "bare"]}]}
    req = {"method": "POST", "path": "/v1/messages", "body": body}
    assert roles.classify(req, ctx1())[:2] == ("unknown", "unknown")


def test_anthropic_marker_text_beside_tool_results_is_read():
    comp = roles.Signature("c", "compaction", "last_user", 9, roles.h16("Summarise"))
    c = ctx1(signatures=(comp,))
    c.issued["toolu_1"] = "replay_main"
    use = {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1"}]}

    def req(text):
        result = {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1"},
                                              {"type": "text", "text": text}]}
        return {"method": "POST", "path": "/v1/messages", "body": {"model": "m", "tools": [{"name": "Bash"}],
                                                                   "messages": [TURN, use, result]}}
    assert roles.classify(req("a reminder"), c)[:2] == ("replay_main", "cursor")
    assert roles.classify(req("Summarise the conversation"), c)[:2] == ("compaction", "shape")
    assert roles.shape(req("a reminder"))["user_hashes"] == roles.shape(req("other"))["user_hashes"]  # not a turn


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


# ---- review 1 regressions: a result is matched by its own id; wire metadata must agree with method and path ----
def _f1_requests(result_ids, call_ids):
    chat_ = {"method": "POST", "path": "/v1/chat/completions", "body": {"model": "unseen", "tools": TOOLS, "messages": [
        {"role": "user", "content": "unscripted synthetic turn"},
        {"role": "assistant", "tool_calls": [{"id": c} for c in call_ids]},
        *({"role": "tool", "tool_call_id": r, "content": "synthetic result"} for r in result_ids)]}}
    resp = {"method": "POST", "path": "/v1/responses", "body": {"model": "unseen", "tools": TOOLS, "input": [
        *({"type": "function_call", "call_id": c} for c in call_ids),
        *({"type": "function_call_output", "call_id": r, "output": "synthetic result"} for r in result_ids)]}}
    anth = {"method": "POST", "path": "/v1/messages", "body": {"model": "unseen", "tools": TOOLS, "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": c} for c in call_ids]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": r, "content": "synthetic result"}
                                     for r in result_ids]}]}}
    return [chat_, resp, anth]


@pytest.mark.parametrize("wire", range(3))
@pytest.mark.parametrize("results,calls,want", [
    (["never-issued"], ["issued-call"], "unknown"),  # the review's F1: only the answered call was issued
    (["sibling"], ["issued-call", "sibling"], "unknown"),  # no result answers an issued id
    (["issued-call", "never-issued"], ["issued-call"], "unknown"),  # one result answers no call in the message
    (["issued-call", "other-role"], ["issued-call", "other-role"], "unknown"),  # results of two roles
    (["issued-call", "sibling"], ["issued-call", "sibling"], "probe_main"),  # a harness split (recorded on Hermes)
    (["issued-call"], ["issued-call"], "probe_main"),
])
def test_tool_results_match_by_their_own_ids(wire, results, calls, want):
    c = roles.Context(issued={"issued-call": "probe_main", "other-role": "write_turn"})
    assert roles.classify(_f1_requests(results, calls)[wire], c)[0] == want


@pytest.mark.parametrize("wire,method,path", [
    ("openai_chat", "POST", "/v1/unseen-wire"),  # the review's F2
    ("openai_chat", "DELETE", "/v1/chat/completions"),
    ("openai_responses", "POST", "/v1/messages"),
    ("openai_responses", "GET", "/v1/responses"),
    ("anthropic", "POST", "/v1/chat/completions"),
    ("anthropic", "PUT", "/v1/messages"),
    ("metadata", "POST", "/v1/models"),
])
def test_supplied_wire_must_agree_with_method_and_path(wire, method, path):
    c = roles.Context(expected=[{"kind": "replay", "hash": roles.h16("synthetic turn")}])
    body = {"model": "m", "tools": TOOLS, "messages": [{"role": "user", "content": "synthetic turn"}],
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": "synthetic turn"}]}]}
    req = {"wire": wire, "method": method, "path": path, "body": body}
    assert roles.classify(req, c)[:2] == ("unknown", "unknown")
    assert roles.classify(dict(req, wire=None), c)[0] in ("unknown", "replay_main", "aux")  # derived wire is consistent


@pytest.mark.parametrize("body", [{"model": "summ"}, {"model": "summ", "messages": []}, {"model": "summ", "input": []}])
def test_alias_on_an_empty_body_is_unknown(body):
    c = roles.Context(aliases={"summ": roles.alias("compaction")})
    for path in ("/v1/chat/completions", "/v1/responses", "/v1/messages"):
        assert roles.classify({"method": "POST", "path": path, "body": body}, c)[0] == "unknown"


# ---- review 2 regressions: the sibling exception holds only inside the latest call message -------------------
def _older_issued_requests():
    """The issued call sits only in an older call message; the latest one holds a harness-added sibling."""
    chat_ = {"method": "POST", "path": "/v1/chat/completions", "body": {"model": "unseen", "tools": TOOLS, "messages": [
        {"role": "assistant", "tool_calls": [{"id": "issued"}]},
        {"role": "tool", "tool_call_id": "issued", "content": "older result"},
        {"role": "user", "content": "another turn"},
        {"role": "assistant", "tool_calls": [{"id": "sibling"}]},
        {"role": "tool", "tool_call_id": "issued", "content": "r"}, {"role": "tool", "tool_call_id": "sibling", "content": "r"}]}}
    out = [{"type": "function_call", "call_id": "issued"}, {"type": "function_call_output", "call_id": "issued"}]
    resp = {"method": "POST", "path": "/v1/responses", "body": {"model": "unseen", "tools": TOOLS, "input": [
        *out, {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "another turn"}]},
        {"type": "function_call", "call_id": "sibling"}, {"type": "function_call_output", "call_id": "issued"},
        {"type": "function_call_output", "call_id": "sibling"}]}}
    batch = {"method": "POST", "path": "/v1/responses", "body": {"model": "unseen", "tools": TOOLS, "input": [
        *out, {"type": "function_call", "call_id": "sibling"}, {"type": "function_call_output", "call_id": "issued"},
        {"type": "function_call_output", "call_id": "sibling"}]}}  # an older completed batch, contiguous
    anth = {"method": "POST", "path": "/v1/messages", "body": {"model": "unseen", "tools": TOOLS, "messages": [
        {"role": "assistant", "content": [{"type": "tool_use", "id": "issued"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "issued"}]},
        {"role": "user", "content": [{"type": "text", "text": "another turn"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "sibling"}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "issued"},
                                     {"type": "tool_result", "tool_use_id": "sibling"}]}]}}
    return [chat_, resp, batch, anth]


@pytest.mark.parametrize("i", range(4))
def test_sibling_exception_needs_the_issued_call_in_the_latest_message(i):
    c = roles.Context(issued={"issued": "probe_main"})
    assert roles.classify(_older_issued_requests()[i], c)[:2] == ("unknown", "unknown")


def test_recorded_harness_splits_still_pass():
    rows = {(s["source"], r["seq"]): r for s in FIX["sources"] for r in s["rows"]}
    for key in (("s6a-r6-write", 136), ("s6b-r7c-write", 165)):
        s = rows[key]["shape"]
        c = roles.Context(issued={cid: "probe_main" for cid in s["tail_calls"][:1]})
        assert roles.classify_shape(s, c)[:2] == ("probe_main", "cursor")
