"""Probe exchanges on both director wires, with decisions fixed per cursor."""

import json

from bicentennial.canon import canon
from bicentennial.director.responder import Call, Reply
from bicentennial.score.exposure import context_text

from .argtemplate import recall_call
from .scripted_reader import _copy, _inputs, read

# The text that ends an action probe's turn once its plan is done. It equals the compiler's replay
# text (director.compiler.hermes.ASSISTANT), and it is never empty: Hermes answers an empty reply
# with retries that wait on the simulated clock.
CLOSING = "Noted."


class RecallToolMissing(ValueError):
    """The request did not offer the declared recall tool."""


class PlanToolMissing(ValueError):
    """The request did not offer a compiled plan tool."""


def plain_step(step):
    return {"name": step["tool"]["name"], "arguments": canon(step["tool"]["args"]).decode()}


def _earlier_body(value):
    if isinstance(value, bytes):
        value = json.loads(value)
    if not isinstance(value, dict) or not ("messages" in value or "input" in value):
        return value
    return {key: [item for item in content if not isinstance(item, dict) or
                  item.get("role") not in ("system", "developer")]
            if key in ("messages", "input") and isinstance(content, list) else content
            for key, content in value.items() if key != "instructions"}


def _calls(call):
    if call.wire not in ("chat", "responses"):
        raise ValueError("unsupported probe wire")
    items = call.body.get("messages" if call.wire == "chat" else "input", [])
    if isinstance(items, str):
        items = [{"role": "user", "content": items}]
    users = [i for i, item in enumerate(items) if item.get("role") == "user"]
    if not users:
        raise ValueError("probe requires a user message")
    tail = items[users[-1] + 1:]
    if call.wire == "chat":
        return [c["function"] for item in tail if item.get("role") == "assistant"
                for c in item.get("tool_calls", [])]
    return [item for item in tail if item.get("type") == "function_call"]


class ProbeResponder:
    def __init__(self, inner, entry, probes, readers, *, earlier, step_call=plain_step):
        if probes.keys() != readers.keys():
            raise ValueError("probe and reader ids differ")
        self.inner, self.earlier, self.step_call = inner, earlier, step_call
        self.readers, self.cursors, self.recalls = {}, {}, {}
        self.decisions, self.latest = {}, {}
        for iid in sorted(probes):
            cursor = probes[iid]
            if not isinstance(cursor, (tuple, list)) or len(cursor) != 2 or any(
                    type(n) is not int or n < 1 for n in cursor):
                raise ValueError("invalid probe cursor")
            cursor = tuple(cursor)
            if cursor in self.cursors:
                raise ValueError("duplicate probe cursor")
            view, keys = readers[iid]
            _inputs(view, keys)
            if view["item_id"] != iid:
                raise ValueError("reader map id differs")
            self.cursors[cursor] = iid
            self.readers[iid] = _copy([view, keys])
            self.recalls[iid] = recall_call(entry, keys["recall_query"])

    def results(self):
        return dict(self.latest)

    def respond(self, call: Call) -> Reply:
        if call.role != "probe_main":
            return self.inner.respond(call)
        if call.subrole not in ("cursor", "retry", "tool_results"):
            raise ValueError("unsupported probe subrole")
        cursor = call.cursor
        if not isinstance(cursor, dict):
            raise ValueError("unknown probe cursor")
        position = (cursor.get("session"), cursor.get("turn"))
        if position not in self.cursors:
            raise ValueError("unknown probe cursor")
        iid = self.cursors[position]
        recall = self.recalls[iid]
        calls = _calls(call)
        offered = [t["function"]["name"] if call.wire == "chat" else t["name"]
                   for t in call.body.get("tools", [])]
        if recall is not None and recall["name"] not in offered:
            raise RecallToolMissing("recall tool not offered")
        if recall is not None and call.subrole in ("cursor", "retry"):
            return self._reply(call, calls=(_copy(recall),))
        offset = int(recall is not None)
        count = len(calls)
        key = (call.run_key, *position)
        if call.subrole == "tool_results" and count < max(1, offset):
            raise ValueError("missing tool exchange")
        if key not in self.decisions:
            if count != offset:
                raise ValueError("decision exchange missing")
            view, keys = self.readers[iid]
            # The current turn bounds the earlier exchanges: its own row is written only after this reply (#352).
            prior = self.earlier(call.run_key, *position)
            earlier = context_text([_earlier_body(v) for v in prior])
            self.decisions[key] = read(view, keys, context_text(call.body), mode="hermes", earlier=earlier)
        result = self.decisions[key]
        self.latest[iid] = result
        if recall is not None and (not calls or calls[0]["name"] != recall["name"]):
            raise ValueError("recall exchange differs")
        if result.kind == "qa":
            if count != offset:
                raise ValueError("second QA exchange")
            return self._reply(call, text=canon(result.envelope).decode())
        compiled = tuple(self.step_call(_copy(step)) for step in result.plan.steps)
        if any(step["name"] not in offered for step in compiled):
            raise PlanToolMissing("plan tool not offered")
        emitted = calls[offset:]
        if len(emitted) > len(compiled) or [c["name"] for c in emitted] != [
                step["name"] for step in compiled[:len(emitted)]]:
            raise ValueError("out-of-order plan calls")
        remaining = compiled[len(emitted):len(emitted) + 1]
        if not remaining:  # the plan is done, or a refrain plan has no step
            return self._reply(call, text=CLOSING)
        return self._reply(call, calls=remaining)

    @staticmethod
    def _reply(call, *, text="", calls=()):
        return Reply(200, "probe_reader", "scripted", call.model, text=text, tool_calls=calls, usage=None)
