"""Small synthetic fixtures only; never read recorded runs or a real Hermes home."""

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import readback as rb
from compression import zstd


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
                "messages": copy.deepcopy(body["messages"]) + [{"role": "user", "content": rb.SUFFIX}]}
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
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": rb.SUFFIX}]}])
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


class Readback(unittest.TestCase):
    def audit(self, data, wire):
        return rb.audit(*data, wire)

    def test_matching_both_wires(self):
        for wire in rb.MODELS:
            with self.subTest(wire=wire):
                result = self.audit(fixture(wire), wire)
                self.assertEqual(result["A1"]["matches"], 1)
                self.assertEqual(result["A1"]["mismatches"], [])
                self.assertEqual(result["A1"]["flag_disagreements"], [])
                self.assertEqual(result["A2"]["raw_hits"], 0)
                self.assertEqual(result["A3"]["failures"], [])
                self.assertEqual(result["A3"]["executed"], 1)
                self.assertEqual(result["A4"]["gaps"], [])
                self.assertEqual(result["A5"]["matches"], 2)
                self.assertEqual(result["A5"]["text_hits"], [])
                self.assertNotIn("saved note", json.dumps(result))
                self.assertNotIn("discarded draft", json.dumps(result))

    def test_mismatch_kinds_both_wires(self):
        for wire in rb.MODELS:
            key = "messages" if wire == "chat" else "input"
            for kind in ("extra", "message", "tool", "suffix", "model", "stream", "adaptation"):
                with self.subTest(wire=wire, kind=kind):
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
                    else:
                        sent.pop("reasoning_effort" if wire == "chat" else "reasoning")
                    result = self.audit(data, wire)
                    self.assertEqual(len(result["A1"]["mismatches"]), 1)
                    self.assertEqual(result["A1"]["flag_disagreements"], [1])
                    if kind == "tool":
                        self.assertEqual(result["A3"]["failures"][0]["kind"], "non_write_offered")

    def test_boundary_and_inherited_collision(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, _, _ = data
            sent = blobs[rows[0]["upstream"][0]["req"]]
            sent["leak"] = "later question FACT-ID-ONE event_one"
            result = self.audit(data, wire)["A2"]
            self.assertEqual(result["introduced_hits"], 3)
            blobs[rows[0]["req"]]["leak"] = sent["leak"]
            result = self.audit(data, wire)["A2"]
            self.assertEqual(result["raw_hits"], 3)
            self.assertEqual(result["introduced_hits"], 0)

    def test_non_write_attempt_and_unissued_execution(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, _, _ = data
            response = blobs[rows[0]["upstream"][0]["resp"]]
            if wire == "chat":
                response["choices"][0]["message"]["tool_calls"].append(
                    {"id": "bad-id", "function": {"name": "other", "arguments": "{}"}})
            else:
                response["sse"] += 'data: {"type":"response.output_item.done","item":' + json.dumps(
                    {"type": "function_call", "call_id": "bad-id", "name": "other", "arguments": "{}"}) + '}\n\n'
            result = self.audit(data, wire)["A3"]
            self.assertEqual((result["non_write_attempts"], result["non_write_blocked"]), (1, 1))
            self.assertEqual(result["failures"], [])
            if wire == "chat":
                blobs[rows[0]["resp"]]["choices"][0]["message"]["tool_calls"][0]["id"] = "bad-id"
            else:
                blobs[rows[0]["resp"]]["sse"] = blobs[rows[0]["resp"]]["sse"].replace("bcw00001", "bad-id")
            self.assertTrue(self.audit(data, wire)["A3"]["failures"])

    def test_effect_gap_and_refusal(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, _, _ = data
            last = blobs[rows[-1]["req"]]
            if wire == "chat":
                last["messages"][0]["content"] = "empty snapshot"
            else:
                last["instructions"] = "empty snapshot"
            a4 = self.audit(data, wire)["A4"]
            self.assertEqual(a4["gaps"], ["bcw00001"])
            self.assertIn("absent_from_next_session", a4["calls"][0]["operations"][0]["reasons"])
            follow = blobs[rows[1]["req"]]
            item = follow["messages" if wire == "chat" else "input"][-1]
            item["content" if wire == "chat" else "output"] = '{"success":false}'
            a4 = self.audit(data, wire)["A4"]
            self.assertEqual((a4["applied"], a4["refused"], a4["gaps"]), (0, 1, []))

    def test_effect_patch_remove_whitespace(self):
        calls = [{"record": 1, "session": 1, "id": "bcw00001", "arguments": json.dumps(
            {"target": "memory", "action": "add", "content": "old  note"}), "result": '{"success":true}'},
            {"record": 2, "session": 1, "id": "bcw00002", "arguments": json.dumps({"target": "memory", "operations": [
                {"action": "patch", "old_text": "old note", "new_text": "new note"}]}), "result": '{"success":true}'},
            {"record": 4, "session": 2, "id": "bcw00003", "arguments": json.dumps(
                {"target": "memory", "action": "remove", "old_text": "new note"}), "result": '{"success":true}'}]
        reqs = [({"seq": 3, "role": "replay_main", "cursor": {"session": 2, "turn": 1}}, {"instructions": "new\nnote"}),
                ({"seq": 5, "role": "replay_main", "cursor": {"session": 3, "turn": 1}}, {"instructions": "empty"})]
        result = rb.effects(calls, reqs, {"memory": ""}, "responses")
        self.assertEqual(result["gaps"], [])
        self.assertEqual(result["calls"][0]["operations"][0]["superseded_by"], ["bcw00002:1", "bcw00003:1"])
        self.assertFalse(result["calls"][-1]["operations"][0]["visible_next_session"])

    def test_discard_and_script_mismatch(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, _, _ = data
            last = blobs[rows[-1]["req"]]
            if wire == "chat":
                last["messages"].append({"role": "assistant", "content": "prefix discarded draft suffix"})
            else:
                last["input"].append({"type": "message", "role": "assistant", "content": "prefix discarded draft suffix"})
            result = self.audit(data, wire)["A5"]
            self.assertEqual(result["text_hits"], [{"record": 3, "write_record": 1}])
            obj = blobs[rows[-1]["resp"]]
            if wire == "chat":
                obj["choices"][0]["message"]["content"] = "wrong"
            else:
                obj["sse"] = obj["sse"].replace("later script", "wrong")
            self.assertEqual(self.audit(data, wire)["A5"]["script_failures"], [3])

    def test_probe_boundary_and_non_write_result(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, life, _ = data
            life["probes"] = [{"index": "P1", "turns": [{"user": "future probe question"}]}]
            blobs[rows[0]["upstream"][0]["req"]]["leak"] = "future probe question"
            self.assertEqual(self.audit(data, wire)["A2"]["introduced_hits"], 1)
            follow = blobs[rows[1]["req"]]
            if wire == "chat":
                follow["messages"].append({"role": "tool", "tool_call_id": "rogue", "content": "{}"})
            else:
                follow["input"].append({"type": "function_call_output", "call_id": "rogue", "output": "{}"})
            self.assertEqual(self.audit(data, wire)["A3"]["failures"],
                             [{"record": 1, "kind": "unissued_execution", "call": "rogue"}])

    def test_configuration_collision_is_not_conversation(self):
        for wire in rb.MODELS:
            data = fixture(wire)
            rows, blobs, _, _ = data
            blobs[rows[-1]["req"]]["configuration"] = "discarded draft"
            result = self.audit(data, wire)["A5"]
            self.assertEqual(result["text_hits"], [])
            self.assertEqual(result["non_content_collisions"], [{"record": 3, "write_record": 1}])

    def test_chain_and_blob_validation(self):
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
            self.assertEqual(len(rb.load(root)[0]), 1)
            path.write_bytes(zstd.compress(rb.canon({"tampered": True})))
            with self.assertRaisesRegex(ValueError, "blob_hash:1"):
                rb.load(root)
            row["seq"] = 2
            ledger.write_bytes(rb.canon(row) + b"\n")
            with self.assertRaisesRegex(ValueError, "chain:1"):
                rb.load(root)
            ledger.write_bytes(rb.canon(row))
            with self.assertRaisesRegex(ValueError, "torn"):
                rb.load(root)


if __name__ == "__main__":
    unittest.main()
