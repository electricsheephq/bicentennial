"""Versioned scripted anchors outside the controls pin."""

from fractions import Fraction

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.contract import answer, task_ids
from bicentennial.canon import milli
from bicentennial.controls.common import run_arm
from bicentennial.world.tokens import estimate_tokens

WINDOW = 16384


class Anchor(ReferenceStore):
    recall_basis = "event_quote"
    k = None

    def __init__(self, window=WINDOW):
        self.window = window
        super().__init__()

    def reset(self):
        super().reset()
        self.retrievals = {}

    def visible(self, now):
        return sorted((e for e in self.events.values() if e["t_sim"] <= now),
                      key=lambda e: (e["t_sim"], e["event_id"]))

    def query(self, task, now):
        task_ids(task, now)
        units = self.select(task["prompt"], now)
        self.retrievals[task["task_id"]] = units
        return dict(output="\n".join(text for _, text in units), citations=[e for e, _ in units],
                    confidence_milli=1000) if units else answer()

    def bounded(self, events):
        taken = []
        for event in events:
            text = "\n".join([e["text"] for e in taken] + [event["text"]])
            if estimate_tokens(text) > self.window:
                break
            taken.append(event)
        return [(e["event_id"], e["text"]) for e in sorted(
            taken, key=lambda e: (e["t_sim"], e["event_id"]))]


def quote_recall(key, events, units, k=None):
    hits, fallback, fallback_hits = 0, 0, 0
    for eid in key["oracle_spans"]:
        if eid not in events:
            continue
        required = [t for t in key["required"] if t in events[eid]["text"]]
        recalled = any(e == eid and all(t in text for t in required) for e, text in units)
        hits += recalled
        fallback += not required
        fallback_hits += recalled and not required
    total = len(key["oracle_spans"])
    recall = dict(k=len(units) if k is None else k, hits=hits, of=total,
                  milli=milli(Fraction(hits, total))) if total else None
    return recall, dict(hits=fallback_hits, of=fallback)


def run(inp, adapter_class, *, score, window=WINDOW):
    adapters = []

    def factory():
        adapter = adapter_class(window=window)
        adapters.append(adapter)
        return adapter

    arm = run_arm(inp, factory, score=score)
    owners = {i: a for a in adapters for i in a.retrievals}
    keys = {k["item_id"]: k for k in inp.keys}
    for report in arm["reports"]:
        iid = report["item_id"]
        adapter = owners[iid]
        report["recall"], report["recall_event_id_basis"] = quote_recall(
            keys[iid], adapter.events, adapter.retrievals[iid], adapter.k)
        report["recall_basis"] = adapter.recall_basis
    return arm
