"""Offline acceptance for the T1 scripted-model wiring stubs."""

import ipaddress
import json
import math
import os
import runpy
import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.director.scripted import VECTOR_SCALE, ScriptedResponder
from bicentennial.director.wire import chat, embeddings, responses
from bicentennial.director.wire.writeturn import expected_write_body
from bicentennial.systems.registry import load

ROOT = Path(__file__).resolve().parents[2]
ENTRY = load(ROOT / "systems/registry/hermes-native.toml")
ROLES = ("write_turn", "memory_write", "compaction", "summariser", "extraction", "title", "aux")


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch):
    seen = {"loopback": 0, "non_loopback": 0}
    real_connect = socket.socket.connect

    def connect(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        try:
            loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
        seen["loopback" if loopback else "non_loopback"] += 1
        if not loopback:
            raise OSError("non-loopback socket refused")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    return seen


def responder(**kw):
    return ScriptedResponder({**ENTRY, "embedding_dim": 8, **kw})


def body(wire, messages=None, names=("memory",), limit=None):
    messages = messages if messages is not None else [
        {"role": "system", "content": "ignore system text"},
        {"role": "user", "content": "old"},
        {"role": "assistant", "content": "earlier answer"},
        {"role": "user", "content": "latest é\nverbatim"},
    ]
    tools = [{"type": "function", "name": name, "parameters": {
        "type": "object", "properties": {"content": {"type": "string"}}}} for name in names]
    if wire == "chat":
        tools = [{"type": "function", "function": {k: v for k, v in t.items() if k != "type"}} for t in tools]
    out = {"model": "input-model", "tools": tools,
           "messages" if wire == "chat" else "input": messages}
    if limit is not None:
        out["max_tokens" if wire == "chat" else "max_output_tokens"] = limit
    return out


# The test's role names, as R08's Director sends them: (ledger role, subrole).
LEDGER = {"write_turn": ("write_turn", "cursor"), "memory_write": ("memory_write", "background_review"),
          "compaction": ("summariser", "compression"), "summariser": ("aux", "summariser"),
          "extraction": ("aux", "extraction"), "title": ("aux", "title_generation"),
          "aux": ("aux", "other_task")}


REVIEW_PROMPT = "Review the conversation above and consider saving to memory if appropriate."


def prompted(request, wire):
    """A memory_write request as the harness sends it: its own prompt is the last user message."""
    key = "messages" if wire == "chat" else "input"
    users = [m for m in request[key] if m.get("type", "message") == "message" and m.get("role") == "user"]
    if users and users[-1].get("content") == REVIEW_PROMPT:
        return request
    return {**request, key: [*request[key], {"role": "user", "content": REVIEW_PROMPT}]}


def call(role="write_turn", wire="chat", request=None):
    request = body(wire) if request is None else request
    if role == "memory_write":
        request = prompted(request, wire)
    return Call(*LEDGER.get(role, (role, "")), wire, request, "route-model", {"session": 1, "turn": 1},
                "attempt-one")


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("role", ROLES)
def test_identity_usage_and_purity(role, wire):
    request = body(wire)
    before = deepcopy(request)
    c = call(role, wire, request)
    r = responder()
    reply = r.respond(c)
    assert request == before
    assert canon(asdict(reply)) == canon(asdict(r.respond(c)))
    assert (reply.status, reply.served_by, reply.served, reply.model, reply.upstream) == (
        200, "scripted", "scripted", c.model, [])
    msg = {"role": "assistant", "content": reply.text}
    if reply.tool_calls:
        msg["tool_calls"] = [{"type": "function", "function": tc} for tc in reply.tool_calls]
    usage_body = c.body if wire == "chat" else {"messages": responses.typed(c.body["input"]),
                                               "tools": c.body["tools"]}
    est = chat.usage_estimate(usage_body, {"choices": [{"message": msg}]})
    n_in, n_out = est["prompt_tokens"], est["completion_tokens"]
    keys = ("prompt_tokens", "completion_tokens") if wire == "chat" else ("input_tokens", "output_tokens")
    assert reply.usage == {keys[0]: n_in, keys[1]: n_out, "total_tokens": n_in + n_out, "estimated": True}
    if role in ("write_turn", "memory_write"):
        assert len(reply.tool_calls) == 1 and reply.text == ""
    else:
        assert reply.tool_calls == ()
        assert reply.text == ("Session" if role == "title" else "" if role == "aux"
                              else "old\nearlier answer\nlatest é\nverbatim")


def test_two_process_hashseed_determinism():
    cases = [asdict(call(role, wire)) for wire in ("chat", "responses", "responses_compact") for role in ROLES]
    cases += [asdict(call("embeddings", "embeddings", {"input": ["Alpha beta", "", "猫 é"]}))]
    payload = canon({"entry": {**ENTRY, "embedding_dim": 8}, "calls": cases})
    program = """
import json, sys
from dataclasses import asdict
from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder
data = json.loads(sys.stdin.buffer.read())
responder = ScriptedResponder(data['entry'])
sys.stdout.buffer.write(canon([asdict(responder.respond(Call(**c))) for c in data['calls']]))
"""
    outputs = [subprocess.run([sys.executable, "-c", program], input=payload, capture_output=True,
                              check=True, env={**os.environ, "PYTHONHASHSEED": seed}).stdout
               for seed in ("0", "random")]
    assert outputs[0] == outputs[1]
    assert len(json.loads(outputs[0])) == len(cases)


class ContentBlindDict(dict):
    def __getitem__(self, key):
        if key in ("gold", "manifest", "future"):
            raise AssertionError("forbidden content access")
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self[key] if key in self else default


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_content_blind_write(wire):
    request = ContentBlindDict(body(wire), gold="trap", manifest="trap", future="trap")
    key = "messages" if wire == "chat" else "input"
    request[key] = [ContentBlindDict(m) for m in request[key]]
    for forbidden in ("gold", "manifest", "future"):
        with pytest.raises(AssertionError, match="forbidden content"):
            request.get(forbidden)
    reply = responder().respond(call(request=request, wire=wire))
    assert json.loads(reply.tool_calls[0]["arguments"])["content"] == "latest é\nverbatim"


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("role", ["write_turn", "memory_write"])
def test_write_body_latest_verbatim_and_schema_limit(wire, role):
    trigger = body(wire, names=("session_search", "memory"))
    write = expected_write_body(trigger, wire, "write-model", None)
    assert len(write["tools"]) == 1
    reply = responder().respond(call(role, wire, write))
    assert len(reply.tool_calls) == 1
    tc = reply.tool_calls[0]
    assert set(tc) == {"name", "arguments"} and tc["name"] == ENTRY["write_tools"][0]["tool"]
    args = {"action": "add", "target": "memory", "content": "latest é\nverbatim"}
    assert tc["arguments"].encode() == canon(args)
    tool = write["tools"][0]["function"] if wire == "chat" else write["tools"][0]
    for limit in (0, 8):
        tool["parameters"]["properties"]["content"]["maxLength"] = limit
        cut = responder().respond(call(role, wire, write))
        assert json.loads(cut.tool_calls[0]["arguments"])["content"] == args["content"][:limit]


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("role", ["write_turn", "memory_write"])
def test_write_stores_the_users_words_without_the_hermes_memory_block(wire, role):
    # Pinned Hermes appends a turn's prefetched memory to the user text, or adds it as its own part (#197)
    block = ("<memory-context>\n[System note: The following is recalled memory context, NOT new user input.]"
             "\n\nan earlier fact\n</memory-context>")
    for content in ("latest é\nverbatim\n\n" + block, "latest é\nverbatim\n\n" + block + "\n\nplug-in:\n\n" + block,
                    [{"type": "text", "text": "latest é\nverbatim"}, {"type": "text", "text": block}]):
        messages = [{"role": "user", "content": "old"}, {"role": "user", "content": content}]
        reply = responder().respond(call(role, wire, body(wire, messages=messages)))
        assert json.loads(reply.tool_calls[0]["arguments"])["content"] == "latest é\nverbatim"


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_no_offered_write_tool_or_no_user_is_empty(wire):
    for request in (body(wire, names=()), body(wire, names=("session_search",)),
                    body(wire, messages=[{"role": "assistant", "content": "no user"}])):
        for role in ("write_turn", "memory_write"):
            reply = responder().respond(call(role, wire, request))
            assert reply.text == "" and reply.tool_calls == ()
    reply = responder(write_tools=[]).respond(call(wire=wire))
    assert reply.text == "" and reply.tool_calls == ()


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_text_parts_join_and_non_message_items(wire):
    part = "text" if wire == "chat" else "input_text"
    messages = [{"role": "user", "content": [{"type": part, "text": "a "},
                {"type": "image_url", "image_url": "ignored"}, {"type": part, "text": "猫"}]}]
    request = body(wire, messages)
    if wire != "chat":
        request["input"].insert(0, {"type": "function_call_output", "role": "user", "output": "ignore"})
    reply = responder().respond(call(wire=wire, request=request))
    assert json.loads(reply.tool_calls[0]["arguments"])["content"] == "a 猫"
    assert responder().respond(call("extraction", wire, request)).text == "a 猫"
    if wire != "chat":
        request["input"] = "raw input"
        assert responder().respond(call(wire=wire, request=request)).tool_calls[0]["arguments"] == (
            canon({"action": "add", "target": "memory", "content": "raw input"}).decode())


@pytest.mark.parametrize("wire", ["chat", "responses", "responses_compact"])
@pytest.mark.parametrize("role", ["compaction", "summariser", "extraction"])
def test_extractive_cuts(wire, role):
    request = body(wire, [{"role": "user", "content": "u" * 300},
                          {"role": "assistant", "content": "a" * 300},
                          {"role": "tool", "content": "ignored"}])
    assert responder().respond(call(role, wire, request)).text == "u" * 240 + "\n" + "a" * 240
    limit_key = "max_tokens" if wire == "chat" else "max_output_tokens"
    request[limit_key] = 61
    assert responder().respond(call(role, wire, request)).text == "u" * 240 + "\naaa"
    request[limit_key] = 0
    assert responder().respond(call(role, wire, request)).text == ""
    request = body(wire, [{"role": "user", "content": "猫" * 300}], limit=1)
    assert responder().respond(call(role, wire, request)).text == "猫"
    request = body(wire, [{"role": "user", "content": "x" * 300}] * 20)
    assert responder().respond(call(role, wire, request)).text == ("\n".join(["x" * 240] * 20))[:4096]
    if wire == "chat":
        request.update(max_tokens=20, max_completion_tokens=1)
        assert responder().respond(call(role, wire, request)).text == "xxxx"


def test_hand_computed_vector_zero_and_normalisation():
    # D=8: token coordinates 1..7; shared coordinate 0 rounds S/sqrt(2) to 707106781.
    # sha256(alpha) starts 8ed3f6ad685b959e ad: 1 + h%7 = 1, sign -.
    # sha256(beta)  starts f44e64e75f3948e9 f7: 1 + h%7 = 4, sign -.
    # Alpha beta: sum(count^2)=2, so each token coordinate is -S/sqrt(4) = -500000000.
    reply = responder().respond(call("embeddings", "embeddings", {
        "input": ["Alpha beta", "", "alpha alpha 猫", "one four"]}))
    assert reply.embedding[0] == [707106781, -500000000, 0, 0, -500000000, 0, 0, 0]
    assert reply.embedding[1] == [0] * 8
    # one (+1) and four (-1) both hash to coordinate 7: cancellation stays zero.
    assert reply.embedding[3] == [0] * 8
    assert reply.scale == VECTOR_SCALE and reply.usage["estimated"] is True
    canon(asdict(reply))  # no float anywhere in the Reply
    for vector in embeddings.to_wire(reply.embedding, reply.scale):
        assert math.sqrt(sum(x * x for x in vector)) == pytest.approx(1 if any(vector) else 0, abs=2e-9)
    single = responder().respond(call("embeddings", "embeddings", {"input": "ALPHA alpha"}))
    # count=-2, sum(count^2)=4: -2*S/sqrt(8) rounds to -707106781.
    assert single.embedding == [[707106781, -707106781, 0, 0, 0, 0, 0, 0]]


@pytest.mark.parametrize("role", ["replay_main", "probe_main", "unknown", "other"])
def test_unsupported_roles_raise(role):
    with pytest.raises(ValueError, match="unsupported scripted role"):
        responder().respond(call(role))


def test_restrictive_entry_and_embedding_shapes():
    for entry in ({**ENTRY, "name": "unmapped"}, {**ENTRY, "structured_formats": {"facts": {}}},
                  {**ENTRY, "write_tools": [{"tool": "unmapped"}]}):
        with pytest.raises(ValueError):
            ScriptedResponder(entry)
    for dimension in (None, 0, -1, True):
        with pytest.raises(ValueError, match="embedding_dim"):
            responder(embedding_dim=dimension).respond(call("embeddings", "embeddings", {"input": "x"}))
    for request in ({"input": [1, 2]}, {"input": [[1, 2]]}, {"input": []}, {"input": "x", "dimensions": 7}):
        with pytest.raises(ValueError):
            responder().respond(call("embeddings", "embeddings", request))
    with pytest.raises(ValueError, match="embeddings wire"):
        responder().respond(call("embeddings"))
    with pytest.raises(ValueError, match="unsupported scripted wire"):
        responder().respond(call("title", "other"))
    for value in (-1, True, "1"):
        request = body("chat")
        request["max_tokens"] = value
        with pytest.raises(ValueError, match="output-token limit"):
            responder().respond(call("extraction", request=request))
        request = body("chat")
        request["tools"][0]["function"]["parameters"]["properties"]["content"]["maxLength"] = value
        with pytest.raises(ValueError, match="maxLength"):
            responder().respond(call(request=request))


def test_socket_guard_refuses_non_loopback(socket_guard):
    with socket.socket() as sock, pytest.raises(OSError, match="non-loopback"):
        sock.connect(("192.0.2.1", 443))
    assert socket_guard["non_loopback"] == 1


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_full_fake_replay_has_no_sockets(wire, tmp_path, socket_guard):
    # Reuse R08's compiled micro-life, recorded shape rehydration, decoder and ledger validator.
    fixture = runpy.run_path(str(Path(__file__).with_name("test_core.py")))
    r = responder()
    director = fixture["make"](tmp_path, r)
    source = fixture["FIX"][fixture["WIRE_SOURCE"][wire]]
    row = next(row for row in source["rows"] if row["expected"] == "replay_main")
    path = row["shape"]["path"]
    count = 0
    try:
        for session in fixture["SCRIPT"]["sessions"]:
            turns = [t for t in session["turns"] if t["kind"] == "replay"]
            if not turns:
                continue  # S04 owns probe sessions; R09 explicitly refuses probe_main.
            fixture["start"](director, tmp_path, session=session["index"])
            for turn in turns:
                _, _, request = fixture["rehydrate"](row, {}, "synthetic system prompt")
                key = "messages" if wire == "chat" else "input"
                request[key] = [{"role": "user", "content": turn["user"]}]
                status, headers, data = director.handle("POST", path, {}, canon(request))
                assert status == 200
                text, ids = fixture["answer"](headers["Content-Type"], data)
                assert text == "" and len(ids) == 1
                if wire == "chat":
                    request[key] += [{"role": "assistant", "content": "", "tool_calls": [
                        {"id": ids[0], "type": "function", "function": {"name": "memory", "arguments": "{}"}}]},
                        {"role": "tool", "tool_call_id": ids[0], "content": "ok"}]
                else:
                    request[key] += [{"type": "function_call", "call_id": ids[0], "name": "memory", "arguments": "{}"},
                                     {"type": "function_call_output", "call_id": ids[0], "output": "ok"}]
                status, headers, data = director.handle("POST", path, {}, canon(request))
                assert status == 200
                assert fixture["answer"](headers["Content-Type"], data) == (turn["assistant"], [])
                count += 1
    finally:
        director.close()
    assert count == 60
    records = fixture["records"](tmp_path)
    assert len(records) == 2 * count
    assert all(r["role"] != "unknown" and r["status"] == 200 for r in records)
    writes = [r for r in records if "write_turn_readback" in r]
    assert len(writes) == count and all(r["write_turn_readback"] for r in writes)
    assert director.write_failures == 0
    assert socket_guard == {"loopback": 0, "non_loopback": 0}


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_director_routed_titles_and_compactions(wire, tmp_path):
    # Recorded title and compaction shapes reach the responder as R08 routes them.
    fixture = runpy.run_path(str(Path(__file__).with_name("test_core.py")))
    director = fixture["make"](tmp_path, responder())
    rows = fixture["FIX"][fixture["WIRE_SOURCE"][wire]]["rows"]
    try:
        fixture["start"](director, tmp_path, session=1)
        for expected in ("title", "compaction"):
            row = next(row for row in rows if row["expected"] == expected)
            method, path, request = fixture["rehydrate"](row, {}, "synthetic system prompt")
            status, headers, data = director.handle(method, path, {}, canon(request))
            assert status == 200
            text, ids = fixture["answer"](headers["Content-Type"], data)
            assert ids == []
            assert text == "Session" if expected == "title" else text != "Session"
    finally:
        director.close()
    roles = {(r["role"], r["subrole"]) for r in fixture["records"](tmp_path) if r.get("status") == 200}
    assert ("aux", "title_generation") in roles and ("summariser", "compression") in roles


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("answer", ["stored", "refused: memory full", "error: bad target"])
def test_no_second_write_after_its_tool_result(wire, answer):
    """A background review that offers the write tool gets one write; its tool result, whatever it
    says, ends the review with an empty reply instead of a duplicate write."""
    request = prompted(body(wire), wire)
    first = responder().respond(call("memory_write", wire, request))
    assert json.loads(first.tool_calls[0]["arguments"])["content"] == "latest é\nverbatim"
    key = "messages" if wire == "chat" else "input"
    tc = first.tool_calls[0]
    if wire == "chat":
        request[key] += [{"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": tc}]}, {"role": "tool", "tool_call_id": "c1",
                                                                  "content": answer}]
    else:
        request[key] += [{"type": "function_call", "call_id": "c1", **tc},
                         {"type": "function_call_output", "call_id": "c1", "output": answer}]
    for role in ("memory_write", "write_turn"):
        reply = responder().respond(call(role, wire, request))
        assert reply.text == "" and reply.tool_calls == ()
    request[key].append({"role": "user", "content": "a new turn"})
    again = responder().respond(call("memory_write", wire, request))
    assert json.loads(again.tool_calls[0]["arguments"])["content"] == "a new turn"


@pytest.mark.parametrize("wire", ["chat", "responses", "responses_compact", "embeddings"])
def test_usage_uses_the_wire_keys(wire):
    if wire == "embeddings":
        reply = responder().respond(Call("embeddings", "embedding", "embeddings", {
            "model": "m", "input": ["a b"]}, "route-model", None, "attempt-one"))
        assert set(reply.usage) == {"prompt_tokens", "total_tokens", "estimated"}
        assert reply.usage["total_tokens"] == reply.usage["prompt_tokens"]
        return
    reply = responder().respond(call("compaction", wire, body("chat" if wire == "chat" else "responses")))
    n_in, n_out = ("prompt_tokens", "completion_tokens") if wire == "chat" else ("input_tokens", "output_tokens")
    assert set(reply.usage) == {n_in, n_out, "total_tokens", "estimated"}
    assert reply.usage["total_tokens"] == reply.usage[n_in] + reply.usage[n_out]


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_memory_write_never_stores_the_harness_prompt(wire):
    """The harness's memory-write prompt is the request's last user message; the write carries the
    conversation's latest user message before it, and a prompt with no conversation gets no write."""
    reply = responder().respond(call("memory_write", wire, body(wire)))
    content = json.loads(reply.tool_calls[0]["arguments"])["content"]
    assert content == "latest é\nverbatim" and REVIEW_PROMPT not in content
    alone = responder().respond(call("memory_write", wire, body(wire, messages=[])))
    assert alone.text == "" and alone.tool_calls == ()
