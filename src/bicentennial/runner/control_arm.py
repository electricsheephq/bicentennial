"""T2 live control arms: one probe-only arm whose probe turn starts with a pinned control's returned text."""

import json
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from bicentennial.anchors.report import ANCHORS, header
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.contracts.items import reader_view
from bicentennial.controls.common import check
from bicentennial.controls.naive_rag import NaiveRag
from bicentennial.packs.scoring import control_input
from bicentennial.probe.scripted_reader import api_task
from bicentennial.runner.units import NO_MEMORY_KEYS, Arm, Unit

CONTROL_ARMS = NO_MEMORY_KEYS
# Each text arm's factory, oracle flag, and sealed key entry (anchors have none).
_CONTROLS = {"naive_rag": (NaiveRag, False, "naive_rag.json"),
             "oracle_evidence": (OracleEvidence, True, "controls.json"),
             **{name: (factory, False, None) for name, factory in ANCHORS.items()}}
# One frame for all text arms: the control's text, then the unchanged probe turn.
FRAME = "Context for the request below:\n<context>\n{}\n</context>\n\n"
FRAME_SHA256 = sha256(FRAME.encode()).hexdigest()


def block(text):
    return FRAME.format(text)


def with_blocks(script, probes, blocks):
    """Start each probe turn's user text with its item's block; every other byte of the script stays."""
    items = {p.index: p.item_ids for p in probes}
    if set(blocks) != {iid for ids in items.values() for iid in ids}:
        raise ValueError("probe blocks differ from the probe items")
    return dict(script, sessions=[dict(s, turns=[dict(t, user=block(blocks[items[s["index"]][t["n"] - 1]]) + t["user"])
        for t in s["turns"]]) if s["kind"] == "probe" else s for s in script["sessions"]])


def probe_blocks(pack, control):
    """{(life, branch): {item_id: text}}: the pinned control's output for each item at the item's own probe time."""
    factory, oracle, _ = _CONTROLS[control]
    inp = control_input(pack.dir)
    check(inp)
    keys = {k["item_id"]: k for k in inp.keys}
    adapters, blocks = {}, {}
    for branch in ("B0", "B1"):
        for item in pack.items[branch]:
            iid = item["item_id"]
            key = keys[iid]
            if (key["life"], key["branch"]) != (pack.life, branch):
                raise ValueError("reader key names another life or branch")
            if branch not in adapters:
                adapters[branch] = factory()
                for event in inp.events[pack.life][branch]:
                    adapters[branch].ingest(event)
            # The task and time the pinned control reads (probe/scripted_reader.py read_api, controls/common.py).
            answer = adapters[branch].query(api_task(reader_view(item), key, oracle=oracle), inp.now[iid])
            blocks.setdefault((pack.life, branch), {})[iid] = answer["output"]
    return blocks


def control_key_sha256(pack, control):
    if control == "no_memory" or _CONTROLS[control][2] is None:
        return None
    return json.loads((Path(pack.dir) / "sealed" / _CONTROLS[control][2]).read_bytes())["key_sha256"]


def anchor_metadata(control):
    """Only anchor arms add provenance; existing control records keep their bytes."""
    if control not in ANCHORS:
        return {}
    definition = header()["anchors"][control]
    return dict(anchor=dict(name=control, **{k: definition[k] for k in (
        "version", "spec_sha256", "code_sha256")}))


def control_units(ctx, control, scratch, out, diagnostics=None):
    """One probe-only unit per life and branch, in the floor's order; a text arm carries its blocks."""
    if control not in CONTROL_ARMS:
        raise ValueError("unknown control arm")
    floor = Arm.from_context(ctx, "no_memory")
    if control != "no_memory":
        floor = replace(floor, key=control, probe_blocks={
            k: v for p in ctx.packs for k, v in probe_blocks(p, control).items()})
    if diagnostics is not None:
        floor = replace(floor, diagnostics=diagnostics)
    return tuple(Unit(floor, p, b, Path(scratch) / floor.key / p.life / b, Path(out) / floor.key / p.life / b)
                 for p in ctx.packs for b in ("B0", "B1"))
