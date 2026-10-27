"""Twin pairing and bundle-only unfiltered selection (Amendment 1)."""

from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import draw
from bicentennial.world import unit

from .compile import _id
from .protocol import CANARY


def unfiltered_sample(seed, life, units) -> frozenset[str]:
    tracks = {}
    for uid, track in sorted(units):
        tracks.setdefault(track, []).append(uid)
    selected = []
    for track in sorted(tracks):
        ranked = sorted(tracks[track], key=lambda uid: (draw(seed, unit(life, "unfiltered", track), 0, uid), uid))
        selected.extend(ranked[:(2 * len(ranked) + 5) // 10])
    return frozenset(selected)


@dataclass(frozen=True)
class Compiled:
    life: str
    items: tuple[dict, ...]
    bundles: tuple[dict, ...]
    records: tuple[dict, ...]

    def singleton_lives(self):
        return {r["item_id"]: self.life for r in self.records if r["bundle_id"] is None}

    def duty_items(self):
        return frozenset(r["item_id"] for r in self.records if r["duty"])


def compile_life(b0, b1) -> Compiled:
    if b0.branch != "B0" or b1.branch != "B1" or any(
            getattr(b0, key) != getattr(b1, key) for key in ("life", "seed", "schedule_sha256")):
        raise ValueError("incompatible branches")
    branches = [{(m["template_id"], m["instance_key"]): (i, m) for i, m in b.entries} for b in (b0, b1)]
    bundles, membership, tracks = [], {}, {}
    for key in sorted(branches[0].keys() | branches[1].keys()):
        pair = [branch.get(key) for branch in branches]
        if not any(e is not None and e[1]["twin_type"] is not None for e in pair):
            continue
        if any(e is None for e in pair):
            raise ValueError("unpaired twin key")
        (i0, m0), (i1, m1) = pair
        if any(i0[k] != i1[k] for k in ("cell_id", "track", "stage", "probe_point")) or any(
                m0[k] != m1[k] for k in ("template_version", "twin_type", "decisive_fact_id")):
            raise ValueError("twin metadata mismatch")
        payload = "plan" if i0["stage"] == "act" else "envelope"
        golds = [i["options"][0][payload] for i in (i0, i1)]
        # QA confidence is derived from tokens; only type/value constitute the answer.
        if payload == "envelope":
            golds = [{k: g[k] for k in ("type", "value")} for g in golds]
        if canon(golds[0]) == canon(golds[1]):
            raise ValueError("twins require different gold actions or answers")
        bid = _id(b0.seed, b0.life, "bundle", [f"{key[0]}-v{m0['template_version']}", key[1]])
        bundle = dict(canary=CANARY, bundle_id=bid, cell_id=i0["cell_id"], twin_type=m0["twin_type"],
                      items=[i0["item_id"], i1["item_id"]], decisive_fact_id=m0["decisive_fact_id"])
        validate("bundle", bundle)
        bundles.append(bundle)
        tracks[bid] = i0["track"]
        membership.update((i["item_id"], bid) for i in (i0, i1))
    selected = unfiltered_sample(b0.seed, b0.life, tracks.items())
    entries = sorted((*b0.entries, *b1.entries), key=lambda e: e[0]["item_id"])
    branch_ids = {i["item_id"]: b.branch for b in (b0, b1) for i, _ in b.entries}
    records = []
    for item, meta in entries:
        bid = membership.get(item["item_id"])
        record = meta | dict(canary=CANARY, item_id=item["item_id"], life=b0.life,
                             branch=branch_ids[item["item_id"]],
                             bundle_id=bid, unfiltered_sample=bid in selected,
                             filter_log="not run (v0.2)", rungs="uncalibrated (v0.2)")
        validate("item_record", record)
        records.append(record)
    return Compiled(b0.life, tuple(i for i, _ in entries), tuple(sorted(bundles, key=lambda b: b["bundle_id"])), tuple(records))
