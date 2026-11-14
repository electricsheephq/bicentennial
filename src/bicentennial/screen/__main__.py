"""Build and screen unregistered cards offline; stdout has template counts only."""

import argparse
import inspect
import os
import re
import subprocess
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from bicentennial import cue_words
from bicentennial.anchors import report as anchors
from bicentennial.canon import canon
from bicentennial.controls.battery import HEURISTICS, POLICIES, _pairs, _plan
from bicentennial.packs.build import REPO_ROOT, build_tier
from bicentennial.packs.scoring import case_from_obj, control_input
from bicentennial.score.check_selftest import score_plan
from bicentennial.world.targeted import PlacementError
from bicentennial.world.twin import IndependenceError

from .candidates import CANDIDATES


def counts(values):
    if not values or any(v is None for v in values):
        raise ValueError("no scored candidate pairs")
    return dict(pairs=len(values), right=sum(v > 0 for v in values),
                confidently_wrong=sum(v < 0 for v in values), no_credit=values.count(0),
                net_pair_points_milli=sum(values), net_pair_score=str(Fraction(sum(values), 10 * len(values))))


def evaluate(root, template, tasks=None):
    """Select whole candidate pairs; item details go only to the JSON report."""
    paths = sorted(Path(root).rglob("sealed/pack.json"))
    ids = {r["item_id"] for p in paths for r in anchors.load(p.parent / "records.json")
           if (r["template_id"], r["template_version"]) == (template.template_id, template.version)}
    if tasks is None:
        # Only a run without a selection writes one; a supplied file is never touched.
        tasks = Path(root).parent / "tasks.json"
        tasks.write_bytes(canon(dict(rows=[dict(item_id=i) for i in sorted(ids)])))
    selected = {r["item_id"] for r in anchors.load(Path(tasks))["rows"]}
    if not selected or not selected <= ids:
        raise ValueError("tasks must select candidate items")
    report = anchors.screen(root, tasks)
    rows = {r["item_id"]: r for r in report["items"]}
    values = {n: [p["anchors"][n]["score_milli"] for p in report["pairs"]]
              for n in ("naive_rag", *anchors.ANCHORS)}
    values.update({n: [] for n in ("oracle_evidence", *POLICIES, *HEURISTICS)})
    for path in paths:
        directory = path.parent.parent
        inp = control_input(directory)
        cases = [case_from_obj(c) for c in anchors.load(path.parent / "scoring.json")["cases"]
                 if c["item"]["item_id"] in selected]
        keys = {k["item_id"]: k for k in inp.keys}
        oracle = anchors.load(path.parent / "controls.json")["arms"]["oracle_evidence"]
        oracle_items = {i["item_id"]: i for i in oracle["items"]}
        for c in cases:
            iid = c.item["item_id"]
            visible = [e for e in inp.events[c.life][c.record["branch"]] if e["t_sim"] <= c.t_sim]
            tokens = [(e, set(re.findall(r"\w+", e["text"].lower()))) for e in visible]
            rows[iid]["vocabulary"] = {w: dict(visible_events=sum(w in ts for _, ts in tokens),
                oracle_span=any(w in ts and e["event_id"] in keys[iid]["oracle_spans"] for e, ts in tokens))
                for w in sorted(set(re.findall(r"\w+", c.item["prompt"].lower())))}
            rows[iid]["oracle_evidence"] = oracle_items[iid]
            rows[iid]["battery"] = {}
        for pair in _pairs(cases):
            bid = pair[0].bundle["bundle_id"]
            values["oracle_evidence"].append(next(b["score_milli"] for b in oracle["bundles"]
                                                   if b["bundle_id"] == bid))
            for name in (*POLICIES, *HEURISTICS):
                scores = []
                for c in pair:
                    asked, plan = _plan(c, name, pair)
                    value = score_plan(c, plan, asked=asked).score_milli
                    rows[c.item["item_id"]]["battery"][name] = value
                    scores.append(value)
                values[name].append(min(scores))
    report["rows"] = {n: counts(vs) for n, vs in values.items()}
    return report


def verdict(variants):
    """One card's gate (plan §4). At most one finalist per template is named afterwards, by plan §4's order and the
    cards README rulings 6 and 7, so a card that passes is not yet a finalist."""
    reasons = []
    if set(variants) != {str(v) for v in range(4)}:
        reasons.append("all four prompt variants required")
    for variant, report in variants.items():
        if report.get("placement_succeeded") is False:
            reasons.append(f"variant {variant}: placement failed")
            continue
        if "refusal" in report:
            reasons.append(f"variant {variant}: refused")
            continue
        rows = report["rows"]
        if rows["oracle_evidence"]["net_pair_points_milli"] != 1000 * rows["oracle_evidence"]["pairs"]:
            reasons.append(f"variant {variant}: scripted oracle below 100")
        if any(rows[n]["net_pair_points_milli"] > 350 * rows[n]["pairs"] for n in ("naive_rag", *anchors.ANCHORS)):
            reasons.append(f"variant {variant}: best anchor above 35")
        if any(rows[n]["net_pair_points_milli"] > 0 for n in POLICIES):
            reasons.append(f"variant {variant}: no-memory policy above 0")
    return dict(passes_gate=not reasons, reasons=reasons)


def _write(path, report):
    # Replaced whole after every card, so a later failure keeps the cards already screened.
    part = path.with_name(path.name + ".part")
    part.write_bytes(canon(report) + b"\n")
    os.replace(part, path)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cards", default="all")
    parser.add_argument("--variants", default="0,1,2,3")
    args = parser.parse_args(argv)
    cards = sorted(CANDIDATES) if args.cards == "all" else args.cards.split(",")
    try:
        variants = [int(v) for v in args.variants.split(",")]
        if not cards or len(set(cards)) != len(cards) or any(c not in CANDIDATES for c in cards):
            raise ValueError("unknown or duplicate card")
        if not variants or len(set(variants)) != len(variants) or any(v not in range(4) for v in variants):
            raise ValueError("variants must be distinct integers 0-3")
        if args.out.resolve().is_relative_to((REPO_ROOT / "packs").resolve()):
            raise ValueError("screening output")
    except ValueError as error:
        parser.error(str(error))
    args.out.mkdir(parents=True, exist_ok=False)
    report = dict(header=dict(anchors.header(), spec_sha256=sha256(args.spec.read_bytes()).hexdigest(),
        base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()), cards={})
    for card in cards:
        module = Path(inspect.getsourcefile(type(CANDIDATES[card][0])))
        entry = dict(header=dict(report["header"], module_sha256=sha256(module.read_bytes()).hexdigest(),
                     variant_texts=[r.parts[0] for r in cue_words.template_requests(module.parent) if r.source == module]),
                     variants={})
        for v in variants:
            dest = args.out / card / str(v)
            try:
                build_tier("T2", dest, harness_artifacts=[], spec_path=args.spec, screening=(card, v))
            except (PlacementError, IndependenceError) as error:
                entry["variants"][str(v)] = dict(placement_succeeded=False, refusal=str(error))
                continue
            except ValueError as error:  # any other refusal (PackRefused is one) blocks this variant only
                entry["variants"][str(v)] = dict(stage="build", refusal=f"{type(error).__name__}: {error}")
                continue
            try:
                entry["variants"][str(v)] = dict(evaluate(dest / "T2", CANDIDATES[card][v]), placement_succeeded=True)
            except ValueError as error:
                entry["variants"][str(v)] = dict(placement_succeeded=True, stage="evaluate",
                                                 refusal=f"{type(error).__name__}: {error}")
        entry["verdict"] = verdict(entry["variants"])
        report["cards"][card] = entry
        _write(args.out / "report.json", report)
    for card, entry in report["cards"].items():
        for variant, result in entry["variants"].items():
            for name, row in result.get("rows", {}).items():
                print(card, variant, name, "print-only" if name in HEURISTICS else "", row)
        print(card, entry["verdict"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
