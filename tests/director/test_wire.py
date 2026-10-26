"""Synthetic wire fixtures; recorded S7 inputs are read only through explicit opt-in."""

import ast
import copy
import json
import os
import re
import runpy
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from bicentennial.canon import canon
from bicentennial.director.wire import chat, embeddings, responses, writeturn

ROOT = Path(__file__).resolve().parents[2]
MEM = {"type": "function", "function": {"name": "memory", "parameters": {"type": "object"}}}
CHAT = {"model": "alias", "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "system", "content": "synthetic policy"},
                     {"role": "user", "content": "synthetic question"}],
        "tools": [MEM, {"type": "function", "function": {"name": "todo"}}],
        "reasoning_effort": "medium"}
CALL = {"id": "bcw00001", "type": "function", "function": {"name": "memory", "arguments": "{}"}}
RITEMS = [{"type": "message", "role": "assistant", "content": "synthetic answer"},
          {"type": "function_call", "call_id": "bcw00001", "name": "memory", "arguments": "{}"}]
RBODY = {"model": "alias", "stream": False, "input": RITEMS, "instructions": "synthetic policy",
         "tools": [{"type": "function", "name": "memory"}, {"type": "function", "name": "todo"}],
         "reasoning": {"effort": "medium"}, "store": False}


@pytest.mark.parametrize("message", [
    {"role": "assistant", "content": "synthetic answer"},
    {"role": "assistant", "content": "", "tool_calls": [CALL]},
    {"role": "assistant", "content": "answer", "reasoning_content": "synthetic reasoning", "tool_calls": [CALL]},
    {"content": "", "tool_calls": [], "reasoning_content": ""},
])
def test_chat_round_trip_and_spike_parity(message):
    body = chat.parse_request(CHAT)
    response = chat.build_response(body, message, response_id="bc-synthetic", created=123)
    chunks = chat.sse_chunks(response)
    assert chat.parse_sse(chat.sse_bytes(response)) == chunks
    assert chat.chunks_to_response(chunks) == response
    spike = _spike_functions("chat")
    assert spike["sse_chunks"](response) == chunks
    assert response["usage"]["estimated"] is True
    assert response["usage"]["total_tokens"] == sum(response["usage"][k] for k in
                                                       ("prompt_tokens", "completion_tokens"))


def test_chat_request_defaults_preservation_and_isolation():
    original = copy.deepcopy(CHAT)
    parsed = chat.parse_request(CHAT)
    parsed["messages"][0]["content"] = "changed"
    assert CHAT == original
    assert parsed["reasoning_effort"] == "medium"
    minimal = chat.parse_request({"model": "alias", "messages": []})
    assert minimal["tools"] == [] and minimal["stream"] is False


@pytest.mark.parametrize("delta", [{"model": None}, {"messages": "bad"}, {"stream": 1},
                                   {"messages": [{"role": "unknown"}]}, {"tools": ["bad"]}])
def test_chat_request_rejects_invalid_routing_fields(delta):
    with pytest.raises(ValueError, match="invalid_chat_request"):
        chat.parse_request(CHAT | delta)


def test_usage_exact_rule_and_separate_process_determinism():
    body = CHAT | {"messages": [{"role": "user", "content": "é羊"}]}
    response = chat.build_response(body, {"content": "é"})
    def serialize(obj):
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    assert chat.usage_estimate(body, response) == {
        "prompt_tokens": (len(serialize(body["messages"])) + len(serialize(body["tools"])) + 3) // 4,
        "completion_tokens": (len(serialize(response["choices"][0]["message"])) + 3) // 4,
        "estimated": True}
    code = (
        "import json; from bicentennial.director.wire.chat import usage_estimate; "
        "print(json.dumps(usage_estimate({'messages':[{'role':'user','content':'é羊'}]}, "
        "{'choices':[{'message':{'role':'assistant','content':'ok'}}]}),sort_keys=True))"
    )
    outputs = [subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True).stdout
               for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0]) == {"prompt_tokens": 10, "completion_tokens": 9, "estimated": True}


def test_responses_round_trip_and_spike_parity():
    items = responses.typed(RITEMS)
    usage = {"input_tokens": 17, "output_tokens": 4}
    # Pin the spike's only nondeterministic input; both serializers see the same identity.
    with patch("time.time_ns", return_value=123):
        raw = responses.sse_bytes(items, usage, "synthetic-model")
        spike = _spike_functions("responses")
        assert spike["sse_bytes"](items, usage, "synthetic-model") == raw
    events = responses.parse_sse(raw)
    assert [e["item"] for e in events if e["type"] == "response.output_item.done"] == items
    assert events[-1]["response"]["usage"] == usage
    assert events[-1]["response"]["output"] == []  # S6b carries output through done frames.
    assert [e["sequence_number"] for e in events] == list(range(len(events)))
    reframed = b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)
    assert responses.parse_sse(reframed) == events


def _spike_functions(wire):
    # Execute only the frozen codec definitions, never director/auth/server setup.
    source = ROOT / "spikes" / ("s6a/director.py" if wire == "chat" else "s6b/sol_director.py")
    names = {"sse_chunks"} if wire == "chat" else {
        "typed", "parse_sse", "sse_bytes", "error_objects", "_error_text", "sse_auth_error",
        "sol_category"}
    nodes = [node for node in ast.parse(source.read_text()).body if
             isinstance(node, ast.FunctionDef) and node.name in names or
             isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and
                                                  t.id in {"SSE_AUTH", "ERROR_FIELDS"} for t in node.targets)]
    namespace = {"json": json, "re": re, "time": time}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


@pytest.mark.parametrize("ending", [b"\n", b"\r", b"\r\n"])
def test_sse_parser_promoted_line_endings_and_unparsed_marker(ending):
    raw = b': comment\nevent: ignored\ndata: {"type":\ndata: "ok"}\n\ndata: nope\n\ndata: []\n\ndata: [DONE]\n\n'
    raw = raw.replace(b"\n", ending)
    expected = [{"type": "ok"}, {"type": "director.unparsed"}, {"type": "director.unparsed"}]
    assert responses.parse_sse(raw) == expected
    assert _spike_functions("responses")["parse_sse"](raw) == expected


def test_typed_strings_roles_and_opaque_items():
    assert responses.typed("x") == [{"type": "message", "role": "user",
                                     "content": [{"type": "input_text", "text": "x"}]}]
    assert responses.typed(RITEMS)[0]["content"][0]["type"] == "output_text"
    assert responses.typed(RITEMS)[1] == RITEMS[1]
    assert responses.typed(responses.typed(RITEMS)) == responses.typed(RITEMS)


@pytest.mark.parametrize(("error", "category"), [
    ({"message": "invalid_api_key PROVIDER-SENTINEL"}, "auth_sse"),
    ({"status_code": 403, "message": "PROVIDER-SENTINEL"}, "auth_sse"),
    ({"message": "quota PROVIDER-SENTINEL"}, "quota"),
    ({"message": "concurrent PROVIDER-SENTINEL"}, "concurrency"),
    ({"code": "rate_limit_exceeded", "message": "PROVIDER-SENTINEL"}, "rate"),
    ({"message": "overloaded PROVIDER-SENTINEL"}, "overload"),
    # In-stream errors have no HTTP status: S6b never labels them by number.
    ({"status": 429, "message": "PROVIDER-SENTINEL"}, "other"),
    ({"status": 503, "message": "PROVIDER-SENTINEL"}, "other"),
    ({"status": 500, "message": "PROVIDER-SENTINEL"}, "other"),
    ({"code": "invalid_value", "message": "item 15029 PROVIDER-SENTINEL"}, "other"),
    ({"message": "max_output_tokens must be <= 512 PROVIDER-SENTINEL"}, "other"),
    ({"message": "PROVIDER-SENTINEL"}, "other"),
])
def test_error_extraction_returns_only_categories(error, category):
    for event in ({"type": "error", **error}, {"response": {"error": error}}, {"error": error}):
        extracted = responses.error_objects(event)
        assert extracted == [{"category": category}]
        auth = responses.sse_auth_error([event])
        assert auth == (category == "auth_sse")
        assert "PROVIDER-SENTINEL" not in json.dumps([extracted, auth])
        spike = _spike_functions("responses")
        assert auth == spike["sse_auth_error"]([event])
        basis = [{k: o[k] for k in spike["ERROR_FIELDS"] if k in o} for o in spike["error_objects"](event)]
        assert category == ("auth_sse" if auth else spike["sol_category"](0, json.dumps(basis)))


def test_errors_ignore_model_output_and_handle_scalar_errors():
    event = {"type": "response.output_text.delta", "delta": "invalid_api_key",
             "response": {"output": [{"error": "invalid_api_key"}]}, "arguments": "forbidden"}
    assert responses.error_objects(event) == []
    assert responses.sse_auth_error([event]) is False
    assert responses.error_objects({"error": "forbidden PROVIDER-SENTINEL"}) == [{"category": "auth_sse"}]


@pytest.mark.parametrize(("wire", "body"), [("chat", CHAT), ("responses", RBODY),
                                          ("responses", RBODY | {"input": "synthetic question"})])
def test_write_body_matches_independent_s7_and_preserves_trigger(wire, body):
    audit = runpy.run_path(str(ROOT / "spikes" / "s7" / "readback.py"))
    before = copy.deepcopy(body)
    expected = audit["expected"](body, wire)
    got = writeturn.expected_write_body(body, wire, audit["MODELS"][wire], audit["SUFFIX"])
    assert got == expected
    assert writeturn.readback(got, expected)
    assert body == before
    got["tools"][0]["type"] = "changed"
    assert body == before


def test_readback_requires_keys_types_and_accepts_only_declared_typing():
    expected = {"stream": False, "input": [{"role": "user", "content": "x"}], "count": 1}
    sent = expected | {"input": responses.typed(expected["input"])}
    assert writeturn.readback(sent, expected)
    assert not writeturn.readback(sent | {"extra": None}, expected)
    assert not writeturn.readback(sent | {"stream": 0}, expected)
    assert not writeturn.readback(sent | {"count": 1.0}, expected)
    assert not writeturn.readback({k: v for k, v in sent.items() if k != "count"}, expected)
    sent["input"][0]["content"][0]["text"] = "changed"
    assert not writeturn.readback(sent, expected)
    assert not writeturn.readback({"input": [{"content": "x"}]}, {"input": [{"content": []}]})
    # Only typed()'s role-appropriate part, with no extra keys, matches an untyped item.
    part = sent["input"][0]["content"][0]
    part["text"] = "x"
    assert writeturn.readback(sent, expected)
    for wrong in ({"type": "output_text"}, {"extra": 1}):
        assert not writeturn.readback(sent | {"input": [{**sent["input"][0], "content": [part | wrong]}]},
                                      expected)
    nan = json.loads('{"model": "m", "temperature": NaN}')
    assert writeturn.readback(nan, json.loads('{"model": "m", "temperature": NaN}'))  # as S7 A1
    with pytest.raises(ValueError, match="unsupported_write_wire"):
        writeturn.expected_write_body(CHAT, "anthropic", "m", "suffix")


@pytest.mark.parametrize("value", ["synthetic text", ["one", "two"], [1, 2], [[1], [2, 3]]])
def test_embeddings_request_and_http_round_trip(value):
    request = {"model": "synthetic-embedding", "input": value, "dimensions": 3}
    assert embeddings.parse_request(json.loads(canon(request))) == request
    vectors = [[1, -2, 0], [3, 4, -5]]
    canonical = canon(vectors)
    wire = embeddings.build_response(vectors, 1000, request["model"], prompt_tokens=7)
    decoded = json.loads(json.dumps(wire))
    assert decoded == wire
    assert decoded["data"][0]["embedding"] == [0.001, -0.002, 0.0]
    assert [[round(x * 1000) for x in item["embedding"]] for item in decoded["data"]] == vectors
    assert decoded["model"] == request["model"]
    assert decoded["usage"] == {"prompt_tokens": 7, "total_tokens": 7}
    assert canon(vectors) == canonical
    with pytest.raises(TypeError):
        canon(wire)  # Edge floats cannot enter canonical storage/hashing.


@pytest.mark.parametrize("value", [[], "", [True], [1.0], ["x", 1], [[1], []]])
def test_embeddings_rejects_unsupported_inputs(value):
    with pytest.raises(ValueError, match="invalid_embeddings_request"):
        embeddings.parse_request({"model": "m", "input": value})


@pytest.mark.parametrize(("vectors", "scale"), [([[1.0]], 1000), ([[True]], 1000),
                                                ([[1]], 0), ([[1]], True), ([[1], [2, 3]], 1000)])
def test_embeddings_rejects_noninteger_or_ragged_vectors(vectors, scale):
    with pytest.raises(ValueError, match="invalid_integer_vectors"):
        embeddings.to_wire(vectors, scale)


@pytest.mark.skipif(not os.environ.get("BICENTENNIAL_S7_LEDGERS"), reason="S7 ledger readback is opt-in")
def test_s7_ledgers_count_only_readback():
    """Never assert on, persist, or print ledger/body values, even on a failed comparison."""
    audit = runpy.run_path(str(ROOT / "spikes" / "s7" / "readback.py"))
    roots = os.environ["BICENTENNIAL_S7_LEDGERS"].split(os.pathsep)
    if len(roots) != 2:
        pytest.fail("readback_error:expected_two_ledgers", pytrace=False)
    pins = ("cbab9d5ad491eb39c4afb2f28183e7447f48ec093d4ef72e7cc777ec4fc11b90",
            "c163b2077b324b55ea18e012225634e0e3da9fa25c47946d32ffb5a3ada7f6f2")
    totals = []
    try:
        for root, wire, pin in zip(roots, ("chat", "responses"), pins, strict=True):
            rows, blobs, digest = audit["load"](Path(root))
            if digest != pin:
                raise ValueError("ledger_pin")
            records = matches = 0
            for row in rows:
                for upstream in row.get("upstream", []):
                    if upstream.get("kind") != "write_turn":
                        continue
                    records += 1
                    expected = writeturn.expected_write_body(blobs[row["req"]], wire,
                                                            audit["MODELS"][wire], audit["SUFFIX"])
                    matches += writeturn.readback(blobs[upstream["req"]], expected)
            totals.append((records, matches, records - matches))
    except Exception as error:
        pytest.fail(f"readback_error:{type(error).__name__}", pytrace=False)
    for records, matches, mismatches in totals:
        print(f"records={records} matches={matches} mismatches={mismatches}")
    if totals != [(60, 60, 0), (60, 60, 0)]:
        pytest.fail("readback_error:count_or_mismatch", pytrace=False)
