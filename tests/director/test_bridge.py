"""Literal S7 translation expectations; no spike imports or transport."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from bicentennial.director.responder import Call, Reply
from bicentennial.director.upstream import Holds, LiveResponder, Pacer, Upstream
from bicentennial.director.upstream.bridge import (
    ResponsesBridge,
    chat_usage,
    to_responses,
)
from bicentennial.runner.spend import Price, Spend


class RecordingLive:
    def __init__(self, effort="medium"):
        self.upstreams = {"probe-model": SimpleNamespace(effort=effort)}
        self.calls = []

    def respond(self, call):
        self.calls.append(call)
        return Reply(200, "live", "live", call.model, "answer",
                     tool_calls=({"name": "lookup", "arguments": "{}"},),
                     usage={"input_tokens": 13, "output_tokens": 5})

    def state(self):
        return {"stopped": False, "stop_reason": None, "sends": len(self.calls)}

    def served_identities(self):
        return {"probe-model": "served-probe-model"}


def call(body, wire="chat"):
    return Call("probe_main", "probe", wire, body, "probe-model", {"session": 1, "turn": 1}, "attempt-1")


def test_literal_message_tool_parity():
    body = {
        "model": "harness-alias", "stream": True, "stream_options": {"include_usage": True},
        "max_tokens": 77, "max_completion_tokens": 88, "reasoning_effort": "low",
        "messages": [
            {"role": "system", "content": "System"},
            {"role": "developer", "content": [{"type": "text", "text": "Develop"},
                                               {"type": "text", "text": "er"}]},
            {"role": "user", "content": [{"type": "text", "text": "Ask"}]},
            {"role": "assistant", "content": "Looking", "tool_calls": [
                {"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{\"q\":1}"}}]},
            {"role": "tool", "tool_call_id": "call-1", "content": "Found"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call-2", "type": "function", "function": {"name": "finish", "arguments": "{}"}}]},
            {"role": "user", "content": ""},
            {"role": "assistant", "content": ""},
        ],
        "tools": [
            {"type": "function", "function": {"name": "lookup", "description": "Look up", "parameters": {
                "type": "object", "properties": {"q": {"type": "integer"}}}}},
            {"type": "function", "function": {"name": "finish"}},
        ],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
        "parallel_tool_calls": False,
    }
    assert to_responses(body, effort="high") == {
        "instructions": "System\n\nDeveloper", "store": False, "reasoning": {"effort": "high"},
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Ask"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Looking"}]},
            {"type": "function_call", "call_id": "call-1", "name": "lookup", "arguments": "{\"q\":1}"},
            {"type": "function_call_output", "call_id": "call-1", "output": "Found"},
            {"type": "function_call", "call_id": "call-2", "name": "finish", "arguments": "{}"},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": ""}]},
        ],
        "tools": [
            {"type": "function", "name": "lookup", "description": "Look up", "parameters": {
                "type": "object", "properties": {"q": {"type": "integer"}}}},
            {"type": "function", "name": "finish", "description": "", "parameters": {}},
        ],
        "tool_choice": {"type": "function", "name": "lookup"}, "parallel_tool_calls": False,
    }


@pytest.mark.parametrize("choice", ["auto", "none", "required"])
def test_literal_string_tool_choice(choice):
    assert to_responses({"messages": [], "tool_choice": choice, "parallel_tool_calls": True}, effort="medium") == {
        "instructions": "", "input": [], "store": False, "reasoning": {"effort": "medium"},
        "tool_choice": choice, "parallel_tool_calls": True,
    }


@pytest.mark.parametrize("body,reason", [
    ({"temperature": 0}, "bridge_unmapped_key:temperature"),
    ({"z_extra": 1, "a_extra": 2}, "bridge_unmapped_key:a_extra"),
    ({"messages": [{"role": "alien", "content": "text"}]}, "bridge_unsupported_role"),
    ({"tools": [{"type": "web_search"}]}, "bridge_unsupported_tool"),
    ({"messages": [{"role": "user", "content": "text", "tool_calls": [
        {"type": "function"}]}]}, "bridge_unsupported_tool_call"),
    ({"messages": [{"role": "assistant", "content": None, "tool_calls": [
        {"type": "other"}]}]}, "bridge_unsupported_tool_call"),
    ({"tool_choice": {"type": "other"}}, "bridge_unsupported_tool_choice"),
    ({"tool_choice": 1}, "bridge_unsupported_tool_choice"),
    ({"messages": [{"role": "user", "content": [{"type": "image_url"}]}]}, "bridge_unsupported_content"),
])
def test_fail_closed_records_reason(body, reason):
    inner = RecordingLive()
    bridge = ResponsesBridge(inner)
    with pytest.raises(ValueError, match=f"^{reason}$"):
        bridge.respond(call(body))
    assert inner.calls == []
    assert bridge.state() == {"stopped": True, "stop_reason": reason, "sends": 0}


@pytest.mark.parametrize("effort", ["medium", "low", "high"])
def test_bridge_reads_upstream_effort_and_preserves_call(effort):
    inner = RecordingLive(effort)
    bridge = ResponsesBridge(SimpleNamespace(inner=inner, respond=inner.respond, state=inner.state,
                                            served_identities=inner.served_identities))
    original = call({"messages": [{"role": "user", "content": "hello"}], "reasoning_effort": "ignored"})
    reply = bridge.respond(original)
    assert inner.calls == [replace(original, wire="responses", body={
        "instructions": "", "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "hello"}]}], "store": False, "reasoning": {"effort": effort}})]
    assert original.wire == "chat" and original.body["reasoning_effort"] == "ignored"
    assert reply.usage == {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}
    assert reply.text == "answer" and reply.tool_calls == ({"name": "lookup", "arguments": "{}"},)
    assert bridge.served_identities() == inner.served_identities()
    assert bridge.state() == inner.state()


def test_unpinned_real_upstream_refused(tmp_path):
    import threading

    price = Price(0, 0)
    up = Upstream("sol", "probe-model", "https://fake.invalid/v1", "responses",
                  Spend(tmp_path / "spend.json", 0, price), price, 100)
    inner = LiveResponder("fake-account", Pacer(0, 1, threading.Event()), lambda: {}, [up], Holds())
    with pytest.raises(ValueError, match="^bridge_effort_unpinned$"):
        ResponsesBridge(inner)


class StoppableLive(RecordingLive):
    def __init__(self):
        super().__init__()
        self.stops = []

    def stop(self, reason):
        self.stops.append(reason)


@pytest.mark.parametrize("wire,body", [("chat", {"messages": [{"role": "user", "content": "hello"}]}),
                                       ("responses", {"input": "native"})])
def test_failure_latch_forwards_nothing_more(wire, body):
    inner = StoppableLive()
    bridge = ResponsesBridge(inner)
    with pytest.raises(ValueError, match="^bridge_unmapped_key:temperature$"):
        bridge.respond(call({"temperature": 0}))
    reply = bridge.respond(call(body, wire=wire))
    assert (reply.status, reply.served, reply.served_by, reply.model) == (503, "live_stopped", "live", "probe-model")
    assert inner.calls == [] and inner.stops == ["bridge_unmapped_key:temperature"]


def test_model_without_live_upstream_names_the_route():
    inner = StoppableLive()
    bridge = ResponsesBridge(inner)
    with pytest.raises(ValueError, match="^bridge_no_upstream$"):
        bridge.respond(replace(call({"messages": []}), model="other-model"))
    assert inner.calls == [] and inner.stops == ["bridge_no_upstream"]
    assert bridge.state()["stop_reason"] == "bridge_no_upstream"


def test_native_responses_pass_through():
    inner = RecordingLive()
    bridge = ResponsesBridge(inner)
    original = call({"input": "native", "reasoning": {"effort": "low"}}, wire="responses")
    reply = bridge.respond(original)
    assert inner.calls == [original]
    assert reply.usage == {"input_tokens": 13, "output_tokens": 5}


def test_chat_usage_asymmetric_tokens():
    assert chat_usage({"input_tokens": 101, "output_tokens": 7, "total_tokens": 999}) == {
        "prompt_tokens": 101, "completion_tokens": 7, "total_tokens": 108}
    assert chat_usage({"input_tokens": 0, "output_tokens": 0}) == {
        "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


@pytest.mark.parametrize("usage", [None, [], "bad", {}, {"input_tokens": 1}, {"output_tokens": 1},
                                   {"input_tokens": True, "output_tokens": 2},
                                   {"input_tokens": 2, "output_tokens": False},
                                   {"input_tokens": "1", "output_tokens": 2},
                                   {"input_tokens": 1, "output_tokens": 2.0}])
def test_malformed_usage_is_none(usage):
    assert chat_usage(usage) is None
