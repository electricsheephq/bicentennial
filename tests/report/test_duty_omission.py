"""A generated duty reaches the T0 card's harmful-omission panel."""

import json
from types import SimpleNamespace

from bicentennial.packs import build
from bicentennial.runner import t0
from bicentennial.score.action import ActionResult
from bicentennial.score.classes import outcome
from packs.test_build import A, catalogue, load


def test_generated_duty_omission_reaches_card(tmp_path, monkeypatch):
    row = catalogue().by_id()["g1-wake-loop-mft-2"]
    with monkeypatch.context() as patch:
        # A single row cannot satisfy the tier-wide distribution shares.
        # Keep generation, pack gates, controls and duty metadata intact.
        patch.setattr(build, "check_distribution", lambda packs, **kwargs:
                      SimpleNamespace(ok=True, to_obj=lambda: {}))
        built = build.build_tier("T0", tmp_path, harness_artifacts=A, rows=[row])

    rel, = built["index"]["packs"]
    pack = t0._Pack(tmp_path / "T0", rel)
    duty_items = frozenset(pack.meta["duty_items"])
    assert duty_items
    assert duty_items == {i["item_id"] for i in pack.pack["items"] if i["stage"] == "act"}
    item_id = sorted(duty_items)[0]
    item = next(i for i in pack.pack["items"] if i["item_id"] == item_id)
    assert item["stage"] == "act"

    outcomes = {}
    for source in pack.pack["items"]:
        result = (ActionResult("OMISSION", False, 0, False, None, None)
                  if source["item_id"] == item_id else
                  ActionResult("PASS", False, 1000, True, None, None))
        outcomes[source["item_id"]] = outcome(t0._identity(source), result)
    assert outcomes[item_id]["base_verdict"] == "OMISSION"

    entry = dict(name="reference_store", surfaces=[])
    lock = t0._lock(built["index"], pack, entry, built["pack_hash"], False)
    controls = load(pack.root / "sealed/controls.json")
    audit = t0._audit([])

    def card():
        report = t0._report_pack(
            pack, entry, lock, outcomes, [], [], controls, audit,
            tmp_path, SimpleNamespace(exit=0), 0)
        return json.loads(report["card"])

    declared = card()
    panel = next(r for r in declared["violations"] if r["track"] == item["track"])
    assert panel["harmful_omission"] == 1

    # Change only the declaration; the omitted item and all outcomes stay identical.
    monkeypatch.setitem(pack.meta, "duty_items", sorted(duty_items - {item_id}))
    undeclared = card()
    assert undeclared["items"] == declared["items"]
    panel = next(r for r in undeclared["violations"] if r["track"] == item["track"])
    assert panel["harmful_omission"] == 0
