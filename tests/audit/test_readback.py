"""R10 acceptance: the write-turn audit (S7 Part A promoted).

The 32 spike cases run on the spike's own small synthetic fixtures. The kit cases audit ledgers that R08's director
writes over loopback for an offline fake harness. The two recorded S6 runs hold request bodies and store text, so
they live outside the repository and are named only by environment variable; without it those cases skip.
"""

import ast
import copy
import hashlib
import json
import os
import runpy
import shutil
import tempfile
from compression import zstd
from pathlib import Path

import pytest

from bicentennial.audit import effects as ef
from bicentennial.audit import readback as rb
from bicentennial.director.routes import RouteTable
from bicentennial.keyed import mint_id
from bicentennial.runtime.faultlite import FaultLite

ROOT = Path(__file__).resolve().parents[2]
SUFFIX = runpy.run_path(str(ROOT / "spikes/s7/readback.py"))["SUFFIX"]  # the spike's provisional text, not copied
MODELS = {"chat": "glm-5.3", "responses": "gpt-6.1-sol"}
PART_A = json.loads((ROOT / "spikes/s7/results/partA.json").read_text())
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
CORE = runpy.run_path(str(ROOT / "tests/director/test_core.py"))
SCRIPT, ROUTES = CORE["SCRIPT"], CORE["ROUTES"]
RECORDED = {"r6": ("chat", "glm-5.3", "BICENTENNIAL_S7_R6_LEDGER", "BICENTENNIAL_S7_R6_HOME"),
            "r7c": ("responses", "gpt-6.1-sol", "BICENTENNIAL_S7_R7C_LEDGER", "BICENTENNIAL_S7_R7C_HOME")}


def run(data, wire):
    """The spike's audit call, adapted: the life's turns and ids, the pinned models, a hook over the stores."""
    rows, blobs, life, stores = data
    return rb.audit(rows, blobs, rb.turns_from_life(life), wire, fmt="s6", model_for=lambda s: MODELS[wire],
                    suffix=SUFFIX, write_tools=("memory",), id_needles=rb.life_ids(life),
                    effects=lambda calls, requests, w: ef.effects(calls, requests, stores, w))


def fixture(wire):
    life = {"sessions": [{"index": 1, "turns": [{"user": "opening question", "assistant": "first script"}]},
                         {"index": 2, "turns": [{"user": "later question", "assistant": "later script"}]}],
            "facts": [{"id": "FACT-ID-ONE"}], "events": {"event_one": {"session": 2}}}
    blobs = {}
    def blob(obj):
        key = str(len(blobs))
        blobs[key] = obj
        return key
    args = json.dumps({"target": "memory", "action": "add", "content": "saved note"})
    def response(text, calls=()):
        if wire == "chat":
            return {"choices": [{"message": {"role": "assistant", "content": text, "tool_calls": [
                {"id": cid, "type": "function", "function": {"name": name, "arguments": a}}
                for cid, name, a in calls]}}]}
        items = [{"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}]
        items += [{"type": "function_call", "call_id": cid, "name": name, "arguments": a} for cid, name, a in calls]
        return {"sse": "".join("data: " + json.dumps({"type": "response.output_item.done", "item": it}) +
                               "\n\n" for it in items) + "data: [DONE]\n\n"}
    if wire == "chat":
        memory = {"type": "function", "function": {"name": "memory"}}
        other = {"type": "function", "function": {"name": "other"}}
        body = {"model": "alias", "stream": True, "stream_options": {}, "reasoning_effort": "medium",
                "messages": [{"role": "system", "content": "initial"},
                             {"role": "user", "content": "opening question"}], "tools": [memory, other]}
        sent = {"model": "glm-5.3", "stream": False, "reasoning_effort": "medium", "tools": [memory],
                "messages": copy.deepcopy(body["messages"]) + [{"role": "user", "content": SUFFIX}]}
        follow = dict(body, messages=copy.deepcopy(body["messages"]) + [
            {"role": "assistant", "content": "", "tool_calls": [{"id": "bcw00001", "type": "function",
                "function": {"name": "memory", "arguments": args}}]},
            {"role": "tool", "tool_call_id": "bcw00001", "content": '{"success":true}'}])
        next_body = dict(body, messages=[{"role": "system", "content": "saved note"},
                                         {"role": "user", "content": "later question"}])
    else:
        memory, other = {"type": "function", "name": "memory"}, {"type": "function", "name": "other"}
        body = {"model": "alias", "stream": False, "instructions": "initial", "reasoning": {"effort": "medium"},
                "input": [{"type": "message", "role": "user", "content": "opening question"}],
                "tools": [memory, other], "store": False}
        sent = dict(body, model="gpt-6.1-sol", stream=True, tools=[memory], input=[
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "opening question"}]},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": SUFFIX}]}])
        follow = dict(body, input=copy.deepcopy(body["input"]) + [
            {"type": "function_call", "call_id": "bcw00001", "name": "memory", "arguments": args},
            {"type": "function_call_output", "call_id": "bcw00001", "output": '{"success":true}'}])
        next_body = dict(body, instructions="saved note", input=[
            {"type": "message", "role": "user", "content": "later question"}])
    origin = {"seq": 1, "role": "replay_main", "cursor": {"session": 1, "turn": 1}, "req": blob(body),
                  "resp": blob(response("", [("bcw00001", "memory", args)])), "served": "write_tool_calls",
                  "write_turn_readback": True, "upstream": [{"kind": "write_turn", "req": blob(sent),
                  "resp": blob(response("discarded draft", [("upstream-id", "memory", args)]))}]}
    rows = [origin, {"seq": 2, "role": "write_turn", "cursor": {"session": 1, "turn": 1}, "req": blob(follow),
                        "resp": blob(response("first script")), "served": "script"},
            {"seq": 3, "role": "replay_main", "cursor": {"session": 2, "turn": 1}, "req": blob(next_body),
                 "resp": blob(response("later script")), "served": "script"}]
    return rows, blobs, life, {"memory": "saved note", "user": ""}


def test_matching_both_wires():
    for wire in MODELS:
        result = run(fixture(wire), wire)
        assert result["A1"]["matches"] == 1
        assert result["A1"]["mismatches"] == []
        assert result["A1"]["flag_disagreements"] == []
        assert result["A2"]["raw_hits"] == 0
        assert result["A3"]["failures"] == []
        assert result["A3"]["executed"] == 1
        assert result["A4"]["gaps"] == []
        assert result["A5"]["matches"] == 2
        assert result["A5"]["text_hits"] == []
        assert "saved note" not in json.dumps(result)
        assert "discarded draft" not in json.dumps(result)


def test_mismatch_kinds_both_wires():
    for wire in MODELS:
        key = "messages" if wire == "chat" else "input"
        expect = {"extra": ["extra"], "message": [key], "tool": ["tools"], "suffix": [key], "model": ["model"],
                  "stream": ["stream"], "coerced": ["stream"],
                  "adaptation": ["reasoning_effort" if wire == "chat" else "reasoning"]}
        for kind, keys in expect.items():
            data = fixture(wire)
            rows, blobs, _, _ = data
            sent = blobs[rows[0]["upstream"][0]["req"]]
            if kind == "extra":
                sent["extra"] = True
            elif kind == "message":
                sent[key][0]["content"] = "changed"
            elif kind == "tool":
                sent["tools"].append({"type": "function", "function": {"name": "other"}}
                                     if wire == "chat" else {"type": "function", "name": "other"})
            elif kind == "suffix":
                sent[key].pop()
            elif kind == "model":
                sent["model"] = "different-model"
            elif kind == "stream":
                sent["stream"] = not sent["stream"]
            elif kind == "coerced":  # equal under Python ==, a different body on the wire
                sent["stream"] = int(sent["stream"])
            else:
                sent.pop("reasoning_effort" if wire == "chat" else "reasoning")
            result = run(data, wire)
            assert [m["keys"] for m in result["A1"]["mismatches"]] == [keys]
            assert result["A1"]["flag_disagreements"] == [1]
            if kind == "tool":
                assert result["A3"]["failures"][0]["kind"] == "non_write_offered"


def test_flag_disagreement_on_a_matching_body():
    for wire in MODELS:
        for flag in (False, None):
            data = fixture(wire)
            if flag is None:
                del data[0][0]["write_turn_readback"]
            else:
                data[0][0]["write_turn_readback"] = flag
            a1 = run(data, wire)["A1"]
            assert (a1["mismatches"], a1["flag_disagreements"]) == ([], [1])


def test_pending_reply_and_extra_copies():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        sent = blobs[rows[0]["upstream"][0]["req"]]
        sent["leak"] = "first script"  # the cursor turn's reply: served only after the write turn
        hits = run(data, wire)["A2"]["introduced"]
        assert [(h["kind"], h["id"]) for h in hits] == [("pending_assistant", "1:1:assistant")]
        blobs[rows[0]["req"]]["note"] = "later question"
        sent["leak"], sent["note"] = "later question", "later question"  # one copy more than the harness
        a2 = run(data, wire)["A2"]
        assert (a2["raw_hits"], a2["introduced_hits"]) == (1, 1)


def test_boundary_and_inherited_collision():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        sent = blobs[rows[0]["upstream"][0]["req"]]
        sent["leak"] = "later question FACT-ID-ONE event_one"
        result = run(data, wire)["A2"]
        assert result["introduced_hits"] == 3
        blobs[rows[0]["req"]]["leak"] = sent["leak"]
        result = run(data, wire)["A2"]
        assert result["raw_hits"] == 3
        assert result["introduced_hits"] == 0


def test_non_write_attempt_and_unissued_execution():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        response = blobs[rows[0]["upstream"][0]["resp"]]
        if wire == "chat":
            response["choices"][0]["message"]["tool_calls"].append(
                {"id": "bad-id", "function": {"name": "other", "arguments": "{}"}})
        else:
            response["sse"] += 'data: {"type":"response.output_item.done","item":' + json.dumps(
                {"type": "function_call", "call_id": "bad-id", "name": "other", "arguments": "{}"}) + '}\n\n'
        result = run(data, wire)["A3"]
        assert (result["non_write_attempts"], result["non_write_blocked"]) == (1, 1)
        assert result["failures"] == []
        if wire == "chat":
            blobs[rows[0]["resp"]]["choices"][0]["message"]["tool_calls"][0]["id"] = "bad-id"
        else:
            blobs[rows[0]["resp"]]["sse"] = blobs[rows[0]["resp"]]["sse"].replace("bcw00001", "bad-id")
        assert run(data, wire)["A3"]["failures"]


def test_non_write_call_reaching_the_harness():
    for wire in MODELS:
        for where in ("served", "history_only"):
            data = fixture(wire)
            rows, blobs, _, _ = data
            up, served, follow = (blobs[rows[0]["upstream"][0]["resp"]], blobs[rows[0]["resp"]],
                                  blobs[rows[1]["req"]])
            cid = "bcw00002" if where == "served" else "up-term"
            if wire == "chat":
                up["choices"][0]["message"]["tool_calls"].append(
                    {"id": "up-term", "function": {"name": "terminal", "arguments": "{}"}})
                call = {"id": cid, "type": "function", "function": {"name": "terminal", "arguments": "{}"}}
                if where == "served":
                    served["choices"][0]["message"]["tool_calls"].append(call)
                    follow["messages"][-2]["tool_calls"].append(call)
                    follow["messages"].append({"role": "tool", "tool_call_id": cid, "content": "{}"})
                else:  # the call lands in the next request's history with no result
                    follow["messages"][-2]["tool_calls"].append(call)
            else:
                item = {"type": "function_call", "call_id": cid, "name": "terminal", "arguments": "{}"}
                up["sse"] += "data: " + json.dumps({"type": "response.output_item.done", "item": dict(
                    item, call_id="up-term")}) + "\n\n"
                if where == "served":
                    served["sse"] = served["sse"].replace("data: [DONE]", "data: " + json.dumps(
                        {"type": "response.output_item.done", "item": item}) + "\n\ndata: [DONE]")
                    follow["input"] += [item, {"type": "function_call_output", "call_id": cid, "output": "{}"}]
                else:
                    follow["input"].append(item)
            a3 = run(data, wire)["A3"]
            kinds = {f["kind"] for f in a3["failures"]}
            assert (a3["non_write_attempts"], a3["non_write_blocked"]) == (1, 0)
            assert "non_write_reached_harness" in kinds
            if where == "served":
                assert "call_count" in kinds


def test_inherited_non_write_history_is_not_a_forwarded_call():
    for wire in MODELS:
        for with_result in (False, True):
            data = fixture(wire)
            rows, blobs, _, _ = data
            if wire == "chat":
                old = [{"role": "assistant", "content": "", "tool_calls": [{"id": "review-term", "type": "function",
                       "function": {"name": "terminal", "arguments": "{}"}}]}]
                old += [{"role": "tool", "tool_call_id": "review-term", "content": "{}"}] * with_result
            else:
                old = [{"type": "function_call", "call_id": "review-term", "name": "terminal", "arguments": "{}"}]
                old += [{"type": "function_call_output", "call_id": "review-term", "output": "{}"}] * with_result
            key = "messages" if wire == "chat" else "input"
            for row in rows:  # the same older history in the trigger, the forwarded body and every later request
                items = blobs[row["req"]][key]
                items[1:1] = copy.deepcopy(old)
            sent = blobs[rows[0]["upstream"][0]["req"]][key]
            sent[1:1] = copy.deepcopy(old)
            up = blobs[rows[0]["upstream"][0]["resp"]]
            if wire == "chat":
                up["choices"][0]["message"]["tool_calls"].append(
                    {"id": "review-term", "function": {"name": "terminal", "arguments": "{}"}})
            else:
                up["sse"] += "data: " + json.dumps({"type": "response.output_item.done", "item": old[0]}) + "\n\n"
            a3 = run(data, wire)["A3"]
            assert (a3["non_write_attempts"], a3["non_write_blocked"], a3["failures"]) == (1, 1, [])


def test_inherited_call_with_a_new_result():
    for wire in MODELS:
        for where in (1, 2):  # the new result in the following request, or only in a later one
            data = fixture(wire)
            rows, blobs, _, _ = data
            if wire == "chat":
                old = {"role": "assistant", "content": "", "tool_calls": [{"id": "review-term", "type": "function",
                       "function": {"name": "terminal", "arguments": "{}"}}]}
                new = {"role": "tool", "tool_call_id": "review-term", "content": "{}"}
            else:
                old = {"type": "function_call", "call_id": "review-term", "name": "terminal", "arguments": "{}"}
                new = {"type": "function_call_output", "call_id": "review-term", "output": "{}"}
            key = "messages" if wire == "chat" else "input"
            for row in rows:
                blobs[row["req"]][key].insert(1, copy.deepcopy(old))
            blobs[rows[0]["upstream"][0]["req"]][key].insert(1, copy.deepcopy(old))
            blobs[rows[where]["req"]][key].insert(2, new)
            up = blobs[rows[0]["upstream"][0]["resp"]]
            if wire == "chat":
                up["choices"][0]["message"]["tool_calls"].append(
                    {"id": "review-term", "function": {"name": "terminal", "arguments": "{}"}})
            else:
                up["sse"] += "data: " + json.dumps({"type": "response.output_item.done", "item": old}) + "\n\n"
            a3 = run(data, wire)["A3"]
            assert (a3["non_write_attempts"], a3["non_write_blocked"]) == (1, 0)
            assert {"record": 1, "kind": "non_write_reached_harness", "call": "review-term"} in a3["failures"]


def test_reasoning_served_beside_write_calls():
    for wire in MODELS:
        for text, flagged in (("discarded draft", [1]), ("", [])):
            data = fixture(wire)
            rows, blobs, _, _ = data
            served = blobs[rows[0]["resp"]]
            if wire == "chat":
                served["choices"][0]["message"]["reasoning_content"] = text
            else:
                item = {"type": "reasoning", "summary": [{"type": "summary_text", "text": text}] if text else []}
                served["sse"] = served["sse"].replace("data: [DONE]", "data: " + json.dumps(
                    {"type": "response.output_item.done", "item": item}) + "\n\ndata: [DONE]")
            assert run(data, wire)["A5"]["served_write_text"] == flagged


def test_text_served_beside_write_calls():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        assert run(data, wire)["A5"]["served_write_text"] == []
        served = blobs[rows[0]["resp"]]
        if wire == "chat":
            served["choices"][0]["message"]["content"] = "discarded draft"
        else:
            served["sse"] = served["sse"].replace('"text": ""', '"text": "discarded draft"')
        assert run(data, wire)["A5"]["served_write_text"] == [1]


def test_effect_encompassing_patch():
    def call(rec, args):
        return {"record": rec, "session": 1, "id": f"bcw{rec:05d}", "arguments": json.dumps(args),
                "result": '{"success":true}'}
    calls = [call(1, {"target": "memory", "action": "add", "content": "alpha note"}),
             call(2, {"target": "memory", "action": "add", "content": "beta note"}),
             call(3, {"target": "memory", "action": "patch", "old_text": "alpha note\nbeta note",
                      "new_text": "combined note"})]
    reqs = [({"seq": 4, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "combined note"})]
    result = ef.effects(calls, reqs, {"memory": "combined note"}, "responses")
    assert result["gaps"] == []
    assert [r["operations"][0]["superseded_by"] for r in result["calls"][:2]] == [["bcw00003:1"]] * 2


def test_scripted_response_with_a_tool_call():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        scripted = blobs[rows[1]["resp"]]
        if wire == "chat":
            scripted["choices"][0]["message"]["tool_calls"] = [
                {"id": "x1", "type": "function", "function": {"name": "other", "arguments": "{}"}}]
        else:
            item = {"type": "function_call", "call_id": "x1", "name": "other", "arguments": "{}"}
            scripted["sse"] = scripted["sse"].replace("data: [DONE]", "data: " + json.dumps(
                {"type": "response.output_item.done", "item": item}) + "\n\ndata: [DONE]")
        result = run(data, wire)
        assert result["A5"]["script_failures"] == [2]
        assert {"record": 2, "kind": "scripted_tool_call"} in result["A3"]["failures"]


def test_results_split_across_continuations():
    second = json.dumps({"target": "memory", "action": "add", "content": "second note"})
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, stores = data
        stores["memory"] = "saved note\nsecond note"
        key = "messages" if wire == "chat" else "input"
        follow = blobs[rows[1]["req"]]
        if wire == "chat":
            blobs[rows[0]["resp"]]["choices"][0]["message"]["tool_calls"].append(
                {"id": "bcw00002", "type": "function", "function": {"name": "memory", "arguments": second}})
            up = blobs[rows[0]["upstream"][0]["resp"]]["choices"][0]["message"]["tool_calls"]
            up.append({"id": "upstream-2", "type": "function", "function": {"name": "memory", "arguments": second}})
            follow[key][-2]["tool_calls"].append(copy.deepcopy(up[-1]) | {"id": "bcw00002"})
            tail = {"role": "tool", "tool_call_id": "bcw00002", "content": '{"success":true}'}
        else:
            def extra(cid):
                return "data: " + json.dumps({"type": "response.output_item.done", "item": {
                    "type": "function_call", "call_id": cid, "name": "memory", "arguments": second}}) + "\n\n"
            for blob, cid in ((blobs[rows[0]["resp"]], "bcw00002"), (blobs[rows[0]["upstream"][0]["resp"]], "upstream-2")):
                blob["sse"] = blob["sse"].replace("data: [DONE]", extra(cid) + "data: [DONE]")
            follow[key].insert(-1, {"type": "function_call", "call_id": "bcw00002", "name": "memory",
                                    "arguments": second})
            tail = {"type": "function_call_output", "call_id": "bcw00002", "output": '{"success":true}'}
        later = copy.deepcopy(follow)
        later[key].append(tail)
        rows.insert(2, dict(rows[1], seq=2.5, req=str(len(blobs))))
        blobs[str(len(blobs))] = later
        result = run(data, wire)
        assert (result["A3"]["executed"], result["A3"]["failures"]) == (2, [])
        assert result["A4"]["executed"] == 2


def test_refused_malformed_write_is_reported():
    def call(args, result):
        return [{"record": 1, "session": 1, "id": "bcw00001", "arguments": args, "result": result}]
    reqs = [({"seq": 2, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "empty"})]
    refusal = '{"success":false,"error":"content required"}'
    for args in (json.dumps({"action": "add"}), json.dumps({"action": "rename", "content": "x"}), "not json"):
        out = ef.effects(call(args, refusal), reqs, {"memory": ""}, "responses")
        assert (out["executed"], out["refused"], out["gaps"]) == (1, 1, [])
        assert out["calls"][0]["operations"][0]["reasons"] == ["hermes_refused", "malformed_operation"]
    with pytest.raises(ValueError, match="empty_memory_content"):
        ef.effects(call(json.dumps({"action": "add"}), '{"success":true}'), reqs, {"memory": ""}, "responses")


def test_streamed_text_disagreeing_with_items():
    data = fixture("responses")
    rows, blobs, _, _ = data
    delta = "data: " + json.dumps({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                                   "delta": "discarded draft"}) + "\n\n"
    honest = "data: " + json.dumps({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                                    "delta": "first script"}) + "\n\n"
    scripted = blobs[rows[1]["resp"]]
    scripted["sse"] = honest + scripted["sse"]
    assert run(data, "responses")["A5"]["script_failures"] == []
    scripted["sse"] = delta + scripted["sse"].replace(honest, "")
    result = run(data, "responses")["A5"]
    assert result["script_failures"] == [2]
    blobs[rows[0]["resp"]]["sse"] = delta + blobs[rows[0]["resp"]]["sse"]
    assert run(data, "responses")["A5"]["served_write_text"] == [1]


def test_streamed_message_without_its_item():
    data = fixture("responses")
    rows, blobs, _, _ = data
    def ev(**e):
        return "data: " + json.dumps(e) + "\n\n"
    msg = {"type": "message", "id": "m1", "role": "assistant", "content": [{"type": "output_text", "text": "first script"}]}
    honest = ev(type="response.output_text.delta", item_id="m1", output_index=0, content_index=0, delta="first script")
    honest += ev(type="response.output_item.done", output_index=0, item=msg)
    blobs[rows[1]["resp"]] = {"sse": honest + "data: [DONE]\n\n"}
    assert run(data, "responses")["A5"]["script_failures"] == []
    extra = ev(type="response.output_text.delta", item_id="m2", output_index=1, content_index=0, delta="first script")
    blobs[rows[1]["resp"]] = {"sse": honest + extra + "data: [DONE]\n\n"}  # a second message, never completed
    assert run(data, "responses")["A5"]["script_failures"] == [2]


def test_later_turn_results_in_a_delayed_continuation():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        key = "messages" if wire == "chat" else "input"
        def blob(obj, blobs=blobs):
            blobs[str(len(blobs))] = obj
            return str(len(blobs) - 1)
        def renamed(obj):  # the first write's blobs, as a second write issuing bcw00002
            raw = json.dumps(obj).replace("bcw00001", "bcw00002").replace("upstream-id", "upstream-2")
            return json.loads(raw.replace("saved note", "second note").replace("discarded draft", "other draft"))
        args2 = json.dumps({"target": "memory", "action": "add", "content": "second note"})
        if wire == "chat":
            call2 = [{"role": "assistant", "content": "", "tool_calls": [{"id": "bcw00002", "type": "function",
                      "function": {"name": "memory", "arguments": args2}}]},
                     {"role": "tool", "tool_call_id": "bcw00002", "content": '{"success":true}'}]
            again = {"role": "tool", "tool_call_id": "bcw00001", "content": '{"success":true}'}
        else:
            call2 = [{"type": "function_call", "call_id": "bcw00002", "name": "memory", "arguments": args2},
                     {"type": "function_call_output", "call_id": "bcw00002", "output": '{"success":true}'}]
            again = {"type": "function_call_output", "call_id": "bcw00001", "output": '{"success":true}'}
        second = blobs[rows[2]["req"]]
        rows[2] = dict(rows[0], seq=3, cursor={"session": 2, "turn": 1}, req=rows[2]["req"],
                       resp=blob(renamed(blobs[rows[0]["resp"]])),
                       upstream=[{"kind": "write_turn", "req": blob(rb.expected(second, wire, MODELS[wire], SUFFIX, ("memory",))),
                                  "resp": blob(renamed(blobs[rows[0]["upstream"][0]["resp"]]))}])
        cont = copy.deepcopy(second)
        cont[key] += copy.deepcopy(call2)
        later_script = json.loads(json.dumps(blobs[rows[1]["resp"]]).replace("first script", "later script"))
        rows.append({"seq": 4, "role": "write_turn", "cursor": {"session": 2, "turn": 1}, "req": blob(cont),
                     "resp": blob(later_script), "served": "script"})
        late = copy.deepcopy(blobs[rows[1]["req"]])  # a delayed continuation of the first turn
        late[key][-1:-1] = copy.deepcopy(call2)
        late[key].append(again)
        rows.append({"seq": 5, "role": "write_turn", "cursor": {"session": 1, "turn": 1}, "req": blob(late),
                     "resp": rows[1]["resp"], "served": "script"})
        a3 = run(data, wire)["A3"]
        assert (a3["executed"], a3["failures"]) == (2, [])
        late[key].insert(-1, dict(again, **{"tool_call_id" if wire == "chat" else "call_id": "rogue"}))
        assert {"record": 1, "kind": "unissued_execution", "call": "rogue"} in run(data, wire)["A3"]["failures"]


def test_refused_call_with_an_unhashable_action():
    reqs = [({"seq": 2, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "empty"})]
    for action in ([], {}):
        calls = [{"record": 1, "session": 1, "id": "bcw00001", "result": '{"success":false}',
                  "arguments": json.dumps({"action": action, "content": "x"})}]
        out = ef.effects(calls, reqs, {"memory": ""}, "responses")
        assert out["calls"][0]["operations"][0]["reasons"] == ["hermes_refused", "malformed_operation"]
        calls[0]["result"] = '{"success":true}'
        with pytest.raises(ValueError, match="unknown_memory_action"):
            ef.effects(calls, reqs, {"memory": ""}, "responses")


def test_replay_turn_without_a_write_turn():
    for wire in MODELS:
        data = fixture(wire)
        rows = data[0]
        rows[0]["subrole"] = rows[2]["subrole"] = "cursor"
        assert run(data, wire)["A1"]["missing_write_turns"] == [3]
        rows[2]["subrole"] = "retry"  # a re-sent turn is served from the script, with no second write turn
        assert run(data, wire)["A1"]["missing_write_turns"] == []


def test_draft_in_a_chat_tool_result():
    data = fixture("chat")
    rows, blobs, _, _ = data
    blobs[rows[-1]["req"]]["messages"].append({"role": "tool", "tool_call_id": "bcw00001", "content": "discarded draft"})
    a5 = run(data, "chat")["A5"]
    assert (a5["text_hits"], a5["tool_channel_hits"]) == ([], [{"record": 3, "write_record": 1}])


def test_reasoning_on_a_scripted_reply():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        scripted = blobs[rows[1]["resp"]]
        if wire == "chat":
            scripted["choices"][0]["message"]["reasoning_content"] = "discarded draft"
        else:
            item = {"type": "reasoning", "summary": [{"type": "summary_text", "text": "discarded draft"}]}
            scripted["sse"] = scripted["sse"].replace("data: [DONE]", "data: " + json.dumps(
                {"type": "response.output_item.done", "item": item}) + "\n\ndata: [DONE]")
        assert run(data, wire)["A5"]["script_failures"] == [2]


def test_effect_removed_then_added_again():
    def call(rec, args):
        return {"record": rec, "session": 1, "id": f"bcw{rec:05d}", "arguments": json.dumps(args),
                "result": '{"success":true}'}
    calls = [call(1, {"target": "memory", "action": "add", "content": "saved note"}),
             call(2, {"target": "memory", "action": "remove", "old_text": "saved note"}),
             call(3, {"target": "memory", "action": "add", "content": "saved note"})]
    reqs = [({"seq": 4, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "saved note"})]
    result = ef.effects(calls, reqs, {"memory": "saved note"}, "responses")
    assert result["gaps"] == []
    assert [r["operations"][0]["superseded_by"] for r in result["calls"]] == [["bcw00002:1", "bcw00003:1"], ["bcw00003:1"], []]
    result = ef.effects(calls[:2], reqs, {"memory": "saved note"}, "responses")  # without the re-addition
    assert result["gaps"] == ["bcw00001", "bcw00002"]
    assert "remove_still_present" in result["calls"][1]["operations"][0]["reasons"]


def test_effect_patch_leaves_its_old_span():
    def run(old, new, store):
        calls = [{"record": 1, "session": 1, "id": "bcw00001", "result": '{"success":true}', "arguments": json.dumps(
            {"target": "memory", "action": "patch", "old_text": old, "new_text": new})}]
        reqs = [({"seq": 2, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": store})]
        return ef.effects(calls, reqs, {"memory": store}, "responses")
    out = run("old note", "new note", "old note\nnew note")
    assert out["gaps"] == ["bcw00001"]
    assert out["calls"][0]["operations"][0]["reasons"][-2:] == ["replaced_span_still_present", "replaced_span_visible_next_session"]
    assert run("old note", "new note", "new note")["gaps"] == []
    assert run("note", "a new note", "a new note")["gaps"] == []  # the new text keeps the old span


def test_staged_and_unparseable_results():
    def call(result):
        return [{"record": 1, "session": 1, "id": "bcw00001", "result": result,
                 "arguments": json.dumps({"target": "memory", "action": "add", "content": "note"})}]
    reqs = [({"seq": 2, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "empty"})]
    staged = ef.effects(call('{"success": true, "staged": true, "pending_id": "p1"}'), reqs, {"memory": ""}, "responses")
    assert (staged["applied"], staged["refused"], staged["staged"], staged["gaps"]) == (0, 0, 1, [])
    assert staged["calls"][0]["operations"][0]["reasons"] == ["staged_not_applied"]
    for bad in ("Error executing tool memory: boom", '"ok"'):
        out = ef.effects(call(bad), reqs, {"memory": ""}, "responses")
        assert (out["applied"], out["gaps"]) == (0, ["bcw00001"])
        assert "unclassified_result" in out["calls"][0]["operations"][0]["reasons"]


def test_effect_gap_and_refusal():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        last = blobs[rows[-1]["req"]]
        if wire == "chat":
            last["messages"][0]["content"] = "empty snapshot"
        else:
            last["instructions"] = "empty snapshot"
        a4 = run(data, wire)["A4"]
        assert a4["gaps"] == ["bcw00001"]
        assert "absent_from_next_session" in a4["calls"][0]["operations"][0]["reasons"]
        follow = blobs[rows[1]["req"]]
        item = follow["messages" if wire == "chat" else "input"][-1]
        item["content" if wire == "chat" else "output"] = '{"success":false}'
        a4 = run(data, wire)["A4"]
        assert (a4["applied"], a4["refused"], a4["gaps"]) == (0, 1, [])


def test_effect_patch_remove_whitespace():
    calls = [{"record": 1, "session": 1, "id": "bcw00001", "arguments": json.dumps(
        {"target": "memory", "action": "add", "content": "old  note"}), "result": '{"success":true}'},
        {"record": 2, "session": 1, "id": "bcw00002", "arguments": json.dumps({"target": "memory", "operations": [
            {"action": "patch", "old_text": "old note", "new_text": "new note"}]}), "result": '{"success":true}'},
        {"record": 4, "session": 2, "id": "bcw00003", "arguments": json.dumps(
            {"target": "memory", "action": "remove", "old_text": "new note"}), "result": '{"success":true}'}]
    reqs = [({"seq": 3, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "new\nnote"}),
            ({"seq": 5, "role": "replay_main", "cursor": {"session": 3, "turn": 1}}, {"instructions": "empty"})]
    result = ef.effects(calls, reqs, {"memory": ""}, "responses")
    assert result["gaps"] == []
    assert result["calls"][0]["operations"][0]["superseded_by"] == ["bcw00002:1", "bcw00003:1"]
    assert not result["calls"][-1]["operations"][0]["visible_next_session"]


def test_discard_and_script_mismatch():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        last = blobs[rows[-1]["req"]]
        if wire == "chat":
            last["messages"].append({"role": "assistant", "content": "prefix discarded draft suffix"})
        else:
            last["input"].append({"type": "message", "role": "assistant", "content": "prefix discarded draft suffix"})
        result = run(data, wire)["A5"]
        assert result["text_hits"] == [{"record": 3, "write_record": 1}]
        obj = blobs[rows[-1]["resp"]]
        if wire == "chat":
            obj["choices"][0]["message"]["content"] = "wrong"
        else:
            obj["sse"] = obj["sse"].replace("later script", "wrong")
        assert run(data, wire)["A5"]["script_failures"] == [3]


def test_probe_boundary_and_non_write_result():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, life, _ = data
        life["probes"] = [{"index": "P1", "turns": [{"user": "future probe question"}]}]
        blobs[rows[0]["upstream"][0]["req"]]["leak"] = "future probe question"
        assert run(data, wire)["A2"]["introduced_hits"] == 1
        follow = blobs[rows[1]["req"]]
        if wire == "chat":
            follow["messages"].append({"role": "tool", "tool_call_id": "rogue", "content": "{}"})
        else:
            follow["input"].append({"type": "function_call_output", "call_id": "rogue", "output": "{}"})
        assert run(data, wire)["A3"]["failures"] == [{"record": 1, "kind": "unissued_execution", "call": "rogue"}]


def test_draft_in_a_later_tool_channel():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        last = blobs[rows[-1]["req"]]
        text = "prefix discarded draft suffix"
        if wire == "chat":
            last["messages"].append({"role": "assistant", "content": "", "tool_calls": [
                {"id": "x1", "type": "function", "function": {"name": "memory", "arguments": text}}]})
        else:
            last["input"].append({"type": "function_call_output", "call_id": "x1", "output": text})
        a5 = run(data, wire)["A5"]
        assert (a5["text_hits"], a5["tool_channel_hits"]) == ([], [{"record": 3, "write_record": 1}])


def test_configuration_collision_is_not_conversation():
    for wire in MODELS:
        data = fixture(wire)
        rows, blobs, _, _ = data
        blobs[rows[-1]["req"]]["configuration"] = "discarded draft"
        result = run(data, wire)["A5"]
        assert result["text_hits"] == []
        assert result["non_content_collisions"] == [{"record": 3, "write_record": 1}]


def test_chain_and_blob_validation():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        data = rb.canon({"synthetic": True})
        digest = hashlib.sha256(data).hexdigest()
        path = root / "blobs" / digest[:2] / f"{digest}.json.zst"
        path.parent.mkdir(parents=True)
        path.write_bytes(zstd.compress(data))
        row = {"seq": 1, "prev_hash": "0" * 64, "req": digest}
        row["hash"] = hashlib.sha256(row["prev_hash"].encode() + rb.canon(row)).hexdigest()
        ledger = root / "ledger.jsonl"
        ledger.write_bytes(rb.canon(row) + b"\n")
        assert len(rb.load(root, "s6")[0]) == 1
        path.write_bytes(zstd.compress(rb.canon({"tampered": True})))
        with pytest.raises(ValueError, match="blob_hash:1"):
            rb.load(root, "s6")
        row["seq"] = 2
        ledger.write_bytes(rb.canon(row) + b"\n")
        with pytest.raises(ValueError, match="chain:1"):
            rb.load(root, "s6")
        ledger.write_bytes(rb.canon(row))
        with pytest.raises(ValueError, match="torn"):
            rb.load(root, "s6")


# ---- the recorded S6 runs (local only) -----------------------------------------------------------------------
def section_diff(got, want):
    """The differing top-level and section keys, never their values."""
    out = []
    for k in sorted(set(got) | set(want)):
        g, w = got.get(k), want.get(k)
        if isinstance(g, dict) and isinstance(w, dict):
            out += [f"{k}.{kk}" for kk in sorted(set(g) | set(w)) if g.get(kk) != w.get(kk)]
        elif g != w:
            out.append(k)
    return out


@pytest.mark.parametrize("name", sorted(RECORDED))
def test_recorded_run_reproduces_part_a(name):
    wire, model, ledger_var, home_var = RECORDED[name]
    ledger, home = os.environ.get(ledger_var), os.environ.get(home_var)
    if not ledger or not home:
        pytest.skip(f"{ledger_var} or {home_var} unset: the recorded run is local-only evidence")
    rows, blobs, digest = rb.load(Path(ledger), "s6")
    want = {k: v for k, v in PART_A["runs"][name].items() if k != "wire"}
    assert digest == want["ledger_sha256"]
    table = RouteTable.load({"routes": [{"system": "hermes", "segment": "seg0", "probe_model": model,
                                         "alias": "bicentennial-main", "summariser": model, "vision": None,
                                         "served_by": "live"}]})
    model_for, mode = rb.route_models(table, "hermes", FaultLite.load([], CORE["compile_micro_life"](LIFE)))
    report = rb.audit(rows, blobs, rb.turns_from_life(LIFE), wire, fmt="s6", model_for=model_for, suffix=SUFFIX,
                      write_tools=("memory",), id_needles=rb.life_ids(LIFE), effects=ef.hermes(home))
    got = dict(ledger_records=len(rows), ledger_sha256=digest, blobs_verified=len(blobs), **report)
    assert got == want, section_diff(got, want)
    assert rb.failures(report) == [] and mode == "live" and rb.run_status(report, mode) == "OK"


# ---- kit ledgers from R08's own director ---------------------------------------------------------------------
def kit_replay(root, wire, **kw):
    """R08's both-wires replay: the fake harness against the director over loopback; -> the ledger root."""
    fake = CORE["Fake"]()
    d = CORE["make"](root, fake, **kw)
    server = CORE["serve"](d)
    try:
        CORE["replay"](CORE["WIRE_SOURCE"][wire], d, fake, root, server.port)
    finally:
        CORE["shutdown"](server)
        d.close()
    return root / "ledger"


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    cache = {}

    def get(wire, write_prompt=None):
        if (wire, write_prompt) not in cache:
            root = tmp_path_factory.mktemp(f"kit-{wire}")
            kw = {} if write_prompt is None else {"write_prompt": write_prompt}
            cache[wire, write_prompt] = kit_replay(root, wire, **kw)
        return cache[wire, write_prompt]
    return get


def kit_audit(loaded, wire, suffix=None, write_tools=("memory",)):
    rows, blobs, _ = loaded
    model_for, mode = rb.route_models(RouteTable.load(ROUTES), "hermes", FaultLite.load([], SCRIPT))
    report = rb.audit(rows, blobs, rb.turns_from_script(SCRIPT), wire, fmt="kit", model_for=model_for, suffix=suffix,
                      write_tools=write_tools, id_needles=rb.life_ids(SCRIPT) + [("script.canary", SCRIPT["canary"])])
    return report, mode


@pytest.mark.parametrize("wire", sorted(CORE["WIRE_SOURCE"]))
def test_kit_replay_audits_clean(wire, kit):
    report, mode = kit_audit(rb.load(kit(wire), "kit"), wire)
    a1, a2, a3, a5 = (report[k] for k in ("A1", "A2", "A3", "A5"))
    assert (a1["write_records"], a1["forwarded"], a1["matches"]) == (60, 60, 60)
    assert a1["mismatches"] == a1["flag_disagreements"] == a1["missing_write_turns"] == []
    assert a2["introduced_hits"] == 0
    assert (a3["failures"], a3["offered"], a3["executed"]) == ([], 60, 14 if wire == "chat" else 1)
    assert (a5["scripted"], a5["matches"]) == (60, 60)
    assert a5["script_failures"] == a5["missing_scripts"] == a5["served_write_text"] == a5["whole_content_hits"] == []
    assert report["A4"] is None and rb.failures(report) == ["A4.no_effects_hook"]
    assert mode == "scripted" and rb.run_status(report, mode) == "INFRA_FAILURE"
    text = json.dumps(report)  # record numbers, labels and codes only: no write draft, no fake text
    assert "discard me" not in text and "fake" not in text


@pytest.mark.parametrize("wire", sorted(CORE["WIRE_SOURCE"]))
def test_kit_suffix_change_fails_readback(wire, kit):
    prompt = "Synthetic write prompt."
    rows, blobs, digest = rb.load(kit(wire, prompt), "kit")
    assert kit_audit((rows, blobs, digest), wire, suffix=prompt)[0]["A1"]["matches"] == 60
    row = next(r for r in rows if any(u["role"] == "write_turn" for u in r["upstream"]))
    req = row["upstream"][0]["req"]
    assert sum(u.get("req") == req for r in rows for u in r.get("upstream", [])) == 1
    item = blobs[req]["messages" if wire == "chat" else "input"][-1]
    if wire == "chat":
        assert item["content"] == prompt
        item["content"] = "Synthetic write prompt, edited."
    else:
        assert item["content"][0]["text"] == prompt
        item["content"][0]["text"] = "Synthetic write prompt, edited."
    report, _ = kit_audit((rows, blobs, digest), wire, suffix=prompt)
    a1 = report["A1"]
    assert a1["matches"] == 59
    assert a1["mismatches"] == [{"record": row["seq"], "attempt": 1, "keys": ["messages" if wire == "chat" else "input"]}]
    assert a1["flag_disagreements"] == [row["seq"]]
    assert "A1.mismatches" in rb.failures(report)
    assert rb.run_status(report, "scripted") == "INFRA_FAILURE"


@pytest.mark.parametrize("wire", sorted(CORE["WIRE_SOURCE"]))
def test_kit_call_id_provenance(wire, kit):
    rows, blobs, digest = rb.load(kit(wire), "kit")
    row = next(r for r in rows if r.get("served") == "write_tool_calls")
    old = rb.output(blobs[row["resp"]], wire)[0][0]["id"]
    new = mint_id(row["attempt_id"], 10**6)
    for h, obj in blobs.items():  # the forged id everywhere the harness carried it: only its provenance is wrong
        blobs[h] = json.loads(json.dumps(obj).replace(old, new))
    assert rb.output(blobs[row["resp"]], wire)[0][0]["id"] == new
    a3 = kit_audit((rows, blobs, digest), wire)[0]["A3"]
    assert a3["failures"] == [{"record": row["seq"], "kind": "call_provenance_or_result", "call": new}]


def test_kit_failed_write_turn_and_unnamed_non_write_call(kit):
    rows, blobs, digest = rb.load(kit("chat"), "kit")
    failed, other = [r for r in rows if r.get("served") == "script" and r.get("write_turn_readback")][:2]
    del failed["upstream"][0]["resp"]  # a responder error records the write body and no reply
    failed["write_turn_failed"] = "error_runtimeerror"
    reply = copy.deepcopy(blobs[other["upstream"][0]["resp"]])  # replies are content-addressed and shared
    reply["tool_calls"].append({"name": "terminal", "arguments": "{}"})
    blobs["synthetic-reply"] = reply
    other["upstream"][0]["resp"] = "synthetic-reply"
    report, _ = kit_audit((rows, blobs, digest), "chat")
    assert report["A3"]["failures"] == [{"record": failed["seq"], "kind": "write_turn_failed"}]
    assert [(c["call"], c["blocked"]) for c in report["A3"]["non_write_calls"]] == [(f"{other['seq']}:1:1", True)]
    assert (report["A1"]["matches"], report["A5"]["write_texts_checked"]) == (60, 59)


def test_kit_integrity(kit, tmp_path):
    for n, change in enumerate(("byte", "blob")):
        root = tmp_path / str(n)
        shutil.copytree(kit("chat"), root)
        assert rb.load(root, "kit")[0]
        if change == "byte":
            raw = bytearray((root / "ledger.jsonl").read_bytes())
            raw[len(raw) // 2] ^= 0x01
            (root / "ledger.jsonl").write_bytes(bytes(raw))
            match = "ledger_integrity:chain_breaks"
        else:
            next((root / "blobs").rglob("*.json.zst")).unlink()
            match = "ledger_integrity:bad_blobs"
        with pytest.raises(ValueError, match=match):
            rb.load(root, "kit")
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "ledger.jsonl").write_bytes(b"")
    with pytest.raises(ValueError, match="ledger_integrity:records"):
        rb.load(tmp_path / "empty", "kit")


def test_passive_system_gets_no_write_turn(kit):
    report, _ = kit_audit(rb.load(kit("chat"), "kit"), "chat", write_tools=())
    kinds = [f["kind"] for f in report["A3"]["failures"]]
    assert kinds.count("write_turn_without_write_tools") == 60
    assert report["A1"]["missing_write_turns"] == []
    assert report["A3"]["executed"] == 0


# ---- the Hermes hook, run status, independence ---------------------------------------------------------------
def test_hermes_hook_reads_only_the_stores(tmp_path):
    home = tmp_path / "home"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text("saved note\n", encoding="utf-8")
    secret = home / "auth.json"
    secret.write_text("{}", encoding="utf-8")
    secret.chmod(0)
    try:
        rows, blobs, life, _ = fixture("chat")
        report = rb.audit(rows, blobs, rb.turns_from_life(life), "chat", fmt="s6", model_for=lambda s: MODELS["chat"],
                          suffix=SUFFIX, write_tools=("memory",), id_needles=rb.life_ids(life),
                          effects=ef.hermes(home))
        assert (report["A4"]["executed"], report["A4"]["applied"], report["A4"]["gaps"]) == (1, 1, [])
        (home / "memories" / "MEMORY.md").unlink()
        (home / "memories" / "MEMORY.md").symlink_to(secret)
        with pytest.raises(ValueError, match="hermes_store_symlink:memory"):
            ef.hermes(home)
    finally:
        secret.chmod(0o600)
    with pytest.raises(ValueError, match="missing_hermes_home"):
        ef.hermes(tmp_path / "absent")


def test_run_status_and_failures():
    report = run(fixture("chat"), "chat")
    assert rb.failures(report) == []
    assert rb.run_status(report, "scripted") == rb.run_status(report, "live") == "OK"
    report["A3"]["failures"].append({"record": 1, "kind": "call_count"})
    assert rb.failures(report) == ["A3.failures"]
    assert (rb.run_status(report, "scripted"), rb.run_status(report, "live")) == ("INFRA_FAILURE", "UNATTRIBUTED")
    report["A2"]["hits"].append({"record": 1})  # inherited hits and substring collisions are reported only
    report["A5"]["text_hits"].append({"record": 1})
    report["A4"] = None
    assert rb.failures(report) == ["A3.failures", "A4.no_effects_hook"]
    with pytest.raises(ValueError, match="unknown_mode"):
        rb.run_status(report, "other")


def test_audit_imports_no_director_and_no_egress():
    banned = ("bicentennial.director", "socket", "http", "urllib", "subprocess")
    for path in sorted((ROOT / "src/bicentennial/audit").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or "", *(f"{node.module}.{a.name}" for a in node.names)]
                     if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                assert not any(name == b or name.startswith(b + ".") for b in banned), (path.name, name)


def test_malformed_action_values_never_reach_the_report():
    reqs = [({"seq": 2, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "empty"})]
    for action in ({"content": "private memory draft"}, ["private memory draft"], "private memory draft"):
        calls = [{"record": 1, "session": 1, "id": "bcw00001", "result": '{"success":false}',
                  "arguments": json.dumps({"action": action, "content": "x"})}]
        out = ef.effects(calls, reqs, {"memory": ""}, "responses")
        assert out["calls"][0]["operations"][0]["action"] is None
        assert "private memory draft" not in json.dumps(out)


@pytest.mark.parametrize("body", [{"input": "plain text"}, {"input": [101, 202]}, {"input": ["a", "b"]},
                                  {"input": None}, {"model": "m"}])
def test_history_scans_take_every_responses_input_shape(body):
    conv, tool, _ = rb.channels(body, "responses")
    assert [c for c in conv if c] == (["plain text"] if body.get("input") == "plain text" else [])
    assert tool == [] and rb.calls_in(body, "responses") == set() and rb.results(body, "responses") == {}
