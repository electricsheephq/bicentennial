"""Build a stable card from outcomes and caller-supplied run identity."""

import json
from fractions import Fraction
from pathlib import Path

import bicentennial.contracts.run as run
from bicentennial.canon import canon, milli, sha256_canon
from bicentennial.ledger import stable_digest
from bicentennial.score.aggregate import reduce


def _shares(items):
    qa = [i for i in items if i["stage"] != "act"]
    return dict(competing_milli=milli(Fraction(sum(bool(i["competing_present"]) for i in items),
                                             len(items))) if items else 0,
                carry_over_milli=milli(Fraction(sum(i["carry_over"] for i in qa), len(qa))) if qa else 0)


def assemble(*, tier, mode, system_entry, run_status, pins, ledger_records, run_values,
             items, bundles, singleton_lives=None, duty_items=frozenset(), controls, voids=None) -> dict:
    """Return the provisional card, without a gate verdict or final validation."""
    if tier not in ("T0", "T1") or mode not in ("api", "hermes"):
        raise ValueError("unsupported Ring 0 tier or mode")
    schema = json.loads((run.SCHEMAS / "card_ring0.schema.json").read_bytes())["properties"]
    if set(pins) != set(schema["pins"]["required"]) - {"masks_hash"}:
        raise ValueError("exactly twelve caller pins required")
    if set(controls) != set(schema["controls"]["required"]):
        raise ValueError("exactly five controls required")
    if voids is not None and (set(voids) != {"checked", "voided", "void_milli"}
                             or type(voids["checked"]) is not int or voids["checked"] <= 0):
        raise ValueError("void summary requires three keys and positive checked count")
    items = sorted(items.values() if isinstance(items, dict) else items, key=lambda i: i["item_id"])
    bundles = sorted(bundles, key=lambda b: b["bundle_id"])
    r = reduce(items, bundles, singleton_lives=singleton_lives, duty_items=duty_items)
    paths = [(s["root"] if s["relative"] == "." else s["root"] + "/" + s["relative"], p)
             for s in system_entry["surfaces"] for p in s["volatile_paths"]]
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate volatile surface path")
    labels = {k: v["enum"][0] for k, v in schema["labels"]["properties"].items()
              if k != "scripted_model" or tier == "T1" or mode == "hermes"}
    card = dict(canary=schema["canary"]["enum"][0], tier=tier, system=system_entry["name"],
                run_status=run_status, pins=dict(pins, masks_hash=sha256_canon(json.loads(
                    Path(run.__file__).with_name("masks.json").read_bytes()))),
                masked_ledger_digest=stable_digest(ledger_records, run_values), labels=labels,
                items=items, bundles=bundles,
                singletons=[dict(item_id=i, life=life) for i, life in sorted(
                    (singleton_lives or {}).items())],
                **{k: r[k] for k in ("aggregates", "sensitivity", "worst_case",
                                     "twin_consistency", "violations")},
                per_item_accuracy=r["accuracy"]["cells"],
                coverage={k: v for k, v in r["coverage"].items() if k != "incomplete"},
                controls=controls, **_shares(items),
                diagnostics=[dict(track=t, **_shares([i for i in items if i["track"] == t]))
                             for t in sorted({i["track"] for i in items})],
                volatile_surface_paths=[dict(surface=s, path=p) for s, p in sorted(paths)],
                voids=voids if voids is not None else dict(checked=0, voided=0, void_milli=None))
    return json.loads(canon(card))


def finalize(provisional, gate_verdict) -> bytes:
    """Copy, validate and serialize a card with its caller's gate verdict."""
    card = json.loads(canon(provisional))
    card["gate_verdict"] = gate_verdict
    run.validate("card_ring0", card)
    return canon(card)
