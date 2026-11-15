"""Read validity round 2's live oracle smoke for the finalists only (results/validity-2/PLAN.md §5).

Per v3 template: pairs are the twin bundles (two items, B0 and B1), and a pair scores its lower twin: right > 0,
confidently wrong < 0, no credit = 0. A finalist is kept only with no confidently wrong pair and at most one pair
without credit (100 or 80 on five pairs). Items labelled unreadable_state count as scored (#524, #537).
Usage: read_smoke.py OUT_DIR
"""
import json
import sys
from collections import Counter, defaultdict

FINALISTS = ("drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3")


def main(out):
    outcomes = json.load(open(f"{out}/outcomes.json"))
    seen = Counter(i["template_ref"] for i in outcomes.values())
    for ref in FINALISTS:
        if not seen[ref]:
            raise SystemExit(f"no items for {ref}: refs seen {sorted(seen)}")
    bundles = defaultdict(list)
    for item in outcomes.values():
        if item["template_ref"] in FINALISTS:
            bundles[(item["template_ref"], item["twin_bundle"])].append(item)
    for ref in FINALISTS:
        pairs = [items for (r, _), items in sorted(bundles.items()) if r == ref]
        if any(len(items) != 2 or {i["branch"] for i in items} != {"B0", "B1"} for items in pairs):
            raise SystemExit(f"{ref}: a bundle is not one B0 and one B1 item")
        right = wrong = none = 0
        verdicts = Counter()
        for items in pairs:
            low = min(i["score_milli"] for i in items)
            right, wrong, none = right + (low > 0), wrong + (low < 0), none + (low == 0)
            verdicts.update((i["branch"], i["base_verdict"]) for i in items)
        net = 100 * (right - wrong) / len(pairs)
        keep = wrong == 0 and none <= 1
        reruns = sum(i["infra_reruns"] for items in pairs for i in items)
        print(f"{ref}: pairs {len(pairs)} right {right} wrong {wrong} no-credit {none} net {net:g} "
              f"-> {'KEEP' if keep else 'DROP'}; infra reruns {reruns}; verdicts {sorted(verdicts.items())}")


if __name__ == "__main__":
    main(sys.argv[1])
