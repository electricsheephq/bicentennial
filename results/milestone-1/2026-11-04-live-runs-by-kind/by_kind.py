"""Milestone 1: live T2 runs beside the live no-memory floor and the pack's scripted controls, by kind of task.

Usage: python by_kind.py --packs PACKS_DIR RUN_DIR [RUN_DIR ...]
Prints, in order: A header (tier, system, model, effort, 12-character pack hash and pins); B scored action pairs by kind
per arm; C the naive-retrieval control's flags by kind and the pack's stored rows; D single tasks by kind; E per life,
with sign-flip p-values; F agreement between runs; G quiz items by cell; H action pairs the live tier does not score;
I full-history fits. Pairs are the pack's own bundles; a pair's score is bicentennial.score.bundle.twin_min.
Prints counts, labels and 12-character hash prefixes only: never task text, answers, item or bundle ids, served
identity values, or paths.
"""

import argparse
import json
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from bicentennial.score.bundle import twin_min
from bicentennial.stats.core import sign_flip_p

LABELS = {("DRIFT-CUR", "fork"): "Drift, value twins", ("DRIFT-CUR", "trigger"): "Drift, correction twins",
          ("WAKE-LOOP", "fork"): "Wake"}
SCRIPTED = ("naive retrieval (scripted)", "oracle evidence (scripted)", "floor (scripted)")
SEED = "milestone-1-by-kind"


def label(kind):
    return LABELS.get(kind, f"{kind[0]}/{kind[1]}")


def kind_order(kind):
    order = list(LABELS)
    return (order.index(kind) if kind in order else len(order), kind)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def points(scores):
    return f"{Fraction(sum(scores), len(scores)) / 10:.1f}" if scores else "n/a"


def load_packs(packs):
    """Per life: the three scripted arms as {items, reports, bundles} keyed by id, the pack rows, fits."""
    lives = {}
    for sealed in sorted(packs.glob("pack/*/*/*/sealed")):
        controls = json.loads((sealed / "controls.json").read_text())
        naive = json.loads((sealed / "naive_rag.json").read_text())
        arms = {SCRIPTED[0]: naive["arm"], SCRIPTED[1]: controls["arms"]["oracle_evidence"],
                SCRIPTED[2]: controls["arms"]["no_memory"]}
        life = {b["life"] for b in naive["arm"]["bundles"]}
        assert len(life) == 1, "a sealed life's bundles name more than one life"
        life = life.pop()
        lives[life] = {
            "bundles": naive["arm"]["bundles"],
            "arms": {name: {"items": {i["item_id"]: i for i in arm["items"]},
                            "reports": {r["item_id"]: r for r in arm["reports"]},
                            "bundles": {b["bundle_id"]: b for b in arm["bundles"]}} for name, arm in arms.items()},
            "rows": naive["rows"],
            "fits": controls["arms"]["full_history"]["fits"],
        }
    return lives


def load_run(run):
    card = json.loads((run / "card.json").read_text())
    system = {}
    for key, value in json.loads((run / "outcomes.json").read_text()).items():
        life, _branch, item_id = key.split("/", 2)
        assert (life, item_id) not in system, "item id repeats within a life"
        system[(life, item_id)] = value
    floor = {}
    for key, unit in json.loads((run / "no_memory.json").read_text()).items():
        life, _branch = key.split("/", 1)
        for item_id, value in unit["outcomes"].items():
            assert (life, item_id) not in floor, "floor item id repeats within a life"
            floor[(life, item_id)] = value
    return card, system, floor


def tally(scores):
    right = sum(s == 1000 for s in scores if s is not None)
    wrong = sum(s == -1000 for s in scores if s is not None)
    none = sum(s == 0 for s in scores if s is not None)
    nonresult = sum(s is None for s in scores)
    return right, wrong, none, nonresult


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("runs", type=Path, nargs="+")
    args = parser.parse_args()
    pack = load_packs(args.packs)
    runs = [load_run(run) for run in args.runs]

    # A. Header.
    print("== A. Header")
    for n, (card, _, _) in enumerate(runs, 1):
        print(f"run {n}: tier", card["tier"], "system", card["system"], "model", card["model"], "effort",
              card["effort"], "pack_hash", card["pack_hash"][:12])
        print("  pins", json.dumps({k: card["pins"][k][:12] for k in sorted(card["pins"])}))
    print("same pack_hash in every run", len({c["pack_hash"] for c, _, _ in runs}) == 1)
    print("same scorer_commit in every run", len({c["pins"]["scorer_commit"] for c, _, _ in runs}) == 1)

    live_arms = {"floor (live)": runs[0][2]}
    for n, (_, system, _) in enumerate(runs, 1):
        live_arms[f"system (live), run {n}"] = system
    for n, (_, _, floor) in enumerate(runs[1:], 2):
        differ = sum(floor.get(key) != value for key, value in runs[0][2].items()) + len(floor.keys() - runs[0][2].keys())
        print(f"floor items in run {n} that differ from run 1's floor", differ)
    arm_names = list(live_arms) + list(SCRIPTED)

    # Pairs: the pack's bundles; scored when both live twins (first run) are action items with integer scores.
    first = runs[0][1]
    pairs = []
    for life in sorted(pack):
        for bundle in pack[life]["bundles"]:
            a, b = ((life, item_id) for item_id in bundle["items"])
            live = [first[a], first[b]]
            scored = all(is_int(x["score_milli"]) and x["stage"] == "act" for x in live)
            pairs.append({"life": life, "kind": (bundle["cell_id"], bundle["twin_type"]), "keys": (a, b),
                          "bundle_id": bundle["bundle_id"], "scored": scored})

    def pair_score(pair, arm):
        if arm in live_arms:
            outcomes = live_arms[arm]
            return twin_min(outcomes[pair["keys"][0]], outcomes[pair["keys"][1]])
        sealed = pack[pair["life"]]["arms"][arm]
        bundle = sealed["bundles"][pair["bundle_id"]]
        a, b = (sealed["items"][k[1]] for k in pair["keys"])
        assert bundle["score_milli"] == twin_min(a, b), f"{arm}: a sealed bundle disagrees with its items"
        return bundle["score_milli"]

    scored = [p for p in pairs if p["scored"]]
    unscored = [p for p in pairs if not p["scored"]]
    kinds = sorted({p["kind"] for p in scored}, key=kind_order)
    for name, outcomes in live_arms.items():
        mixed = sum(not all(is_int(outcomes[k]["score_milli"]) and outcomes[k]["stage"] == "act" for k in p["keys"])
                    for p in scored)
        print(f"scored pairs (by run 1) not scored in {name}", mixed)

    # B. Scored action pairs by kind.
    print("\n== B. Scored action pairs by kind (pairs, right, wrong, no credit, non-result, net, points)")
    print("scored action pairs", len(scored), {label(k): sum(p["kind"] == k for p in scored) for k in kinds})
    for arm in arm_names:
        print(f"-- {arm}")
        for group, members in [(label(k), [p for p in scored if p["kind"] == k]) for k in kinds] + [("total", scored)]:
            scores = [pair_score(p, arm) for p in members]
            right, wrong, none, nonresult = tally(scores)
            print(f"  {group}: pairs {len(members)} right {right} wrong {wrong} no_credit {none} non_result {nonresult}"
                  f" net {right - wrong} points {points([s for s in scores if s is not None])}")

    # C. Naive-retrieval flags.
    print("\n== C. Naive-retrieval control flags on mean pair score in milli (f floor, r naive, c oracle, scripted)")
    for group, members in [(label(k), [p for p in scored if p["kind"] == k]) for k in kinds] + [("total", scored)]:
        f, r, c = (Fraction(sum(pair_score(p, arm) for p in members), len(members))
                   for arm in (SCRIPTED[2], SCRIPTED[0], SCRIPTED[1]))
        print(f"  {group}: f {float(f):.1f} r {float(r):.1f} c {float(c):.1f} between {f < r < c}"
              f" rag_near_solved {10 * r >= 10 * f + 7 * (c - f)} floor_near_solved {10 * f >= 7 * c}")
    print("pack rows as stored (stage, track, floor, naive_rag, ceiling, between, rag_near_solved, floor_near_solved):"
          " lives")
    rows = Counter((r["stage"], r["track"], r["floor_milli"], r["naive_rag_milli"], r["ceiling_milli"], r["between"],
                    r["rag_near_solved"], r["floor_near_solved"]) for life in pack.values() for r in life["rows"])
    for key, n in sorted(rows.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
        print("  ", *key, n)

    # D. Single tasks by kind.
    print("\n== D. Single tasks in scored action pairs, by kind")
    for arm in arm_names:
        print(f"-- {arm}")
        for k in kinds:
            keys = [key for p in scored if p["kind"] == k for key in p["keys"]]
            if arm in live_arms:
                rows_ = [live_arms[arm][key] for key in keys]
                verdicts = dict(sorted(Counter(str(x["base_verdict"]) for x in rows_).items()))
                absent = sum("in_context" not in x for x in rows_)
                context = "absent (field not in outcomes)" if absent == len(rows_) else (
                    f"{sum(x.get('in_context') is True for x in rows_)} (absent on {absent})")
                print(f"  {label(k)}: tasks {len(rows_)} base_verdict {verdicts} in_context {context}"
                      f" competing_present {sum(bool(x['competing_present']) for x in rows_)}")
            else:
                sealed = {life: pack[life]["arms"][arm] for life in pack}
                items = [sealed[life]["items"][i] for life, i in keys]
                reports = [sealed[life]["reports"][i] for life, i in keys]
                print(f"  {label(k)}: tasks {len(items)} accuracy_correct"
                      f" {sum(x['accuracy_correct'] is True for x in items)}"
                      f" in_context {sum(x['in_context'] is True for x in reports)}")

    # E. Per life.
    print("\n== E. Per life (lives with scored action pairs)")
    lives = sorted({p["life"] for p in scored})
    print("lives", len(lives))
    for arm in arm_names:
        nets = []
        for life in lives:
            right, wrong, _, _ = tally([pair_score(p, arm) for p in scored if p["life"] == life])
            nets.append(right - wrong)
        print(f"  net per life, {arm}:", nets)
    floor_arm = "floor (live)"
    for n in range(1, len(runs) + 1):
        arm = f"system (live), run {n}"
        diffs = {}
        for life in lives:
            values = [(pair_score(p, arm), pair_score(p, floor_arm)) for p in scored if p["life"] == life]
            values = [s - f for s, f in values if s is not None and f is not None]
            diffs[life] = Fraction(sum(values), len(values))
        p = sign_flip_p(diffs, seed=SEED, name=f"pairs-run-{n}")
        print(f"  run {n} pairs: per-life mean difference system minus floor (milli)",
              [str(diffs[life]) for life in lives], "sign_flip_p", p, f"{float(p):.4f}")
        system, floor = runs[n - 1][1], runs[0][2]
        diffs = {}
        for life in lives:
            values = [system[key]["score_milli"] - floor[key]["score_milli"] for key in system
                      if key[0] == life and system[key]["stage"] == "act" and is_int(system[key]["score_milli"])
                      and key in floor and is_int(floor[key]["score_milli"])]
            diffs[life] = Fraction(sum(values), len(values))
        p = sign_flip_p(diffs, seed=SEED, name=f"tasks-run-{n}")
        print(f"  run {n} tasks: per-life mean difference system minus floor (milli)",
              [str(diffs[life]) for life in lives], "sign_flip_p", p, f"{float(p):.4f}")

    # F. Agreement between runs.
    if len(runs) == 2:
        print("\n== F. Agreement between run 1 and run 2")
        one, two = runs[0][1], runs[1][1]
        equal = sum(pair_score(p, "system (live), run 1") == pair_score(p, "system (live), run 2") for p in scored)
        print(f"  scored pairs with equal score {equal} of {len(scored)}")
        keys = sorted(one.keys() & two.keys())
        print("  keys only in one run", len(one.keys() ^ two.keys()))
        scored_diff = Counter(one[k]["cell_id"] for k in keys
                              if (is_int(one[k]["score_milli"]) or is_int(two[k]["score_milli"]))
                              and (one[k]["score_milli"], one[k]["failure_class"])
                              != (two[k]["score_milli"], two[k]["failure_class"]))
        print("  scored tasks whose (score_milli, failure_class) differ", sum(scored_diff.values()),
              dict(sorted(scored_diff.items())))
        verdict = Counter(one[k]["cell_id"] for k in keys if one[k]["stage"] == "act"
                          and (one[k]["base_verdict"] == "PASS") != (two[k]["base_verdict"] == "PASS"))
        print("  action tasks whose pass or fail (base_verdict PASS) differs", sum(verdict.values()),
              dict(sorted(verdict.items())))
        quiz = Counter(one[k]["cell_id"] for k in keys if one[k]["stage"] == "survive"
                       and one[k]["score_milli"] != two[k]["score_milli"])
        print("  quiz items whose score_milli differs", sum(quiz.values()), dict(sorted(quiz.items())))

    # G. Quiz items.
    print("\n== G. Quiz items (stage survive) by cell: +1000, 0, -1000, other, net")
    for arm in arm_names:
        if arm in live_arms:
            rows_ = [x for x in live_arms[arm].values() if x["stage"] == "survive"]
        else:
            rows_ = [x for life in pack.values() for x in life["arms"][arm]["items"].values() if x["stage"] == "survive"]
        by_cell = defaultdict(list)
        for x in rows_:
            by_cell[x["cell_id"]].append(x["score_milli"])
        print(f"-- {arm}: quiz items {len(rows_)}")
        for cell, scores in sorted(by_cell.items()):
            plus, zero, minus = scores.count(1000), scores.count(0), scores.count(-1000)
            print(f"  {cell}: +1000 {plus} 0 {zero} -1000 {minus} other {len(scores) - plus - zero - minus}"
                  f" net {plus - minus}")

    # H. Unscored action pairs.
    print("\n== H. Pairs the live tier does not score (run 1), by kind: right, wrong, no credit")
    print("unscored pairs", len(unscored), "stages", dict(sorted(Counter(
        first[k]["stage"] for p in unscored for k in p["keys"]).items())))
    for k in sorted({p["kind"] for p in unscored}, key=kind_order):
        members = [p for p in unscored if p["kind"] == k]
        print(f"  {label(k)}: pairs {len(members)}")
        for arm in SCRIPTED[:2]:
            right, wrong, none, nonresult = tally([pair_score(p, arm) for p in members])
            print(f"    {arm}: right {right} wrong {wrong} no_credit {none} non_result {nonresult}")

    # I. Full history.
    print("\n== I. Full history fits over lives")
    print("  run", sum(life["fits"]["run"] for life in pack.values()),
          "of", sum(life["fits"]["of"] for life in pack.values()))


if __name__ == "__main__":
    main()
