"""Verbatim store; Unicode casefolded word-set overlap, newest tie wins."""

import json
import re

from bicentennial.canon import canon

from ..contract import Adapter, answer, event_copy, integer, shape, task_ids


def tokens(text):
    return re.findall(r"\w+", text.casefold())


class ReferenceStore(Adapter):
    def __init__(self):
        self.reset()

    def reset(self):
        self.events = {}

    def ingest(self, event):
        event = event_copy(event)
        previous = self.events.get(event["event_id"])
        if previous is not None and previous != event:
            raise ValueError("conflicting event_id")
        if previous == event:
            return
        if event["kind"] == "tool_result":
            call = self.events.get(event["call_id"], {})
            if call.get("kind") != "tool_call" or call["t_sim"] > event["t_sim"]:
                raise ValueError("tool_result requires an earlier tool_call")
        self.events[event["event_id"]] = event

    def scores(self, prompt, events):
        return [len(set(tokens(prompt)) & set(tokens(e["text"]))) for e in events]

    def tie(self, event):
        return event["t_sim"], event["event_id"]

    def query(self, task, now):
        task_ids(task, now)
        events = [e for e in self.events.values() if e["t_sim"] <= now]
        ranked = [(score, self.tie(e), e) for score, e in
                  zip(self.scores(task["prompt"], events), events, strict=True) if score > 0]
        return answer([max(ranked, key=lambda row: row[:2])[2]] if ranked else [])

    def checkpoint(self):
        return canon(sorted(self.events.values(), key=lambda e: (e["t_sim"], e["event_id"])))

    def restore(self, data):
        if type(data) is not bytes:
            raise TypeError("checkpoint must be bytes")
        events = json.loads(data)
        if type(events) is not list:
            raise ValueError("checkpoint must contain an event list")
        replacement = ReferenceStore()
        # Calls precede results even when timestamps and ids sort the other way.
        for event in sorted((event_copy(e) for e in events), key=lambda e: e["kind"] == "tool_result"):
            replacement.ingest(event)
        self.events = replacement.events

    def forget(self, selector):
        shape(selector, dict(event_ids=list))
        ids = selector["event_ids"]
        if any(type(i) is not str or not i for i in ids):
            raise ValueError("invalid event ids")
        removed = set(ids)
        removed.update(e["event_id"] for e in self.events.values() if e.get("call_id") in ids)
        self.events = {i: e for i, e in self.events.items() if i not in removed}

    def settle(self, bound_s):
        integer(bound_s)
        return True  # All operations are synchronous; observing this store sees no pending work.

    def stats(self):
        return dict(tokens=sum(len(tokens(e["text"])) for e in self.events.values()), latency_ms=0)
