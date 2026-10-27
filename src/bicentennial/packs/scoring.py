"""Stored replay scoring for controls and API-mode readers."""

import json
from dataclasses import asdict
from pathlib import Path

from bicentennial.canon import sha256_canon
from bicentennial.controls.cache import code_sha256
from bicentennial.controls.common import ControlInput
from bicentennial.items.checks.repo import RepoCheck
from bicentennial.items.protocol import CANARY
from bicentennial.score.check_selftest import Case, score_plan
from bicentennial.score.qa import score_qa

from .manifest import PinnedArtifactChanged

SCORING_FILES = ("items/checks/env.py", "items/checks/fixtures.py", "items/checks/repo.py",
                 "packs/scoring.py", "score/check_selftest.py")


def case_obj(case):
    obj = asdict(case)
    if case.checks is not None:
        obj["checks"] = {p: [[asdict(c) for c in group] for group in case.checks[p]]
                         for p in sorted(case.checks)}
    obj["window"] = list(case.window) if case.window is not None else None
    return obj


def case_from_obj(obj):
    values = dict(obj)
    if obj["checks"] is not None:
        values["checks"] = {p: tuple(tuple(RepoCheck(**c) for c in group) for group in obj["checks"][p])
                            for p in sorted(obj["checks"])}
    values["window"] = tuple(obj["window"]) if obj["window"] is not None else None
    return Case(**values)


def scoring_obj(cases, evidence):
    return dict(canary=CANARY, code_sha256=code_sha256(SCORING_FILES),
                cases=[case_obj(c) for c in sorted(cases, key=lambda c: c.item["item_id"])],
                evidence={i: list(evidence[i]) for i in sorted(evidence)})


def make_score(obj):
    if obj["code_sha256"] != code_sha256(SCORING_FILES):
        raise PinnedArtifactChanged(("scoring_code",))
    cases = {c["item"]["item_id"]: case_from_obj(c) for c in obj["cases"]}

    def score(item, result):
        if obj["code_sha256"] != code_sha256(SCORING_FILES):
            raise PinnedArtifactChanged(("scoring_code",))
        iid = item["item_id"]
        if iid not in cases or result.item_id != iid or result.mode != "api":
            raise ValueError(iid)
        if item["stage"] != "act":
            return score_qa(item, result.envelope, evidence_texts=obj["evidence"][iid])
        return score_plan(cases[iid], list(result.plan.steps))

    return score


def control_input(pack_dir):
    root = Path(pack_dir)

    def load(rel):
        return json.loads((root / rel).read_bytes())

    pack = load("sealed/pack.json")
    pack["controls"] = {n: "not run in v0.1" for n in sorted(pack["controls"])}
    pack["hashes"].pop("controls", None)
    keys = tuple(json.loads(line) for line in (root / "sealed/reader_keys.jsonl").read_bytes().splitlines())
    events = {life: {b: load(f"visible/events.{b}.json")["events"] for b in ("B0", "B1")}
              for life in sorted(pack["lives"])}
    return ControlInput(pack, keys, events, load("sealed/meta.json")["now"],
                        sha256_canon(load("sealed/scoring.json")))
