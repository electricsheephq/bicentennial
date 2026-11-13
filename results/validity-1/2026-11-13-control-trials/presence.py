"""Validity round 1 (#505, #506), read after the table: on how many items the needed fact was in the probe turn's
first request, by template, for each control arm given; and each pack's scripted naive-retrieval report.

Counts only: it prints template refs, booleans and counts, never item ids, text or paths.

  python -I presence.py --packs PACKS [--tasks TASKS.json] [--scripted OTHER_PACKS ...] [LABEL=RUN ...]

--packs is the pack the arms ran on. With --tasks, only the frozen list's target items are counted; without it, every
item of the four templates of #505 and #506 (any version). For each naive-retrieval arm it also counts the items whose
first request matches the pack's scripted report. --scripted adds another pack's scripted report, over that pack's
items of the four templates.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

FAMILIES = ("drift-chain-fault", "drift-config", "drift-quote", "recall-count")


def family(ref):
    return ref is not None and ref.rsplit("-v", 1)[0] in FAMILIES


def scripted(packs):
    """({(life, item_id): in_context}, {(life, item_id): template ref}) from a pack's sealed files."""
    report, refs = {}, {}
    for sealed in sorted(Path(packs).glob("pack/*/*/*/sealed")):
        records = json.loads((sealed / "records.json").read_text())
        lives = {r["life"] for r in records}
        if len(lives) != 1:
            raise SystemExit("a sealed life's records do not name exactly one life")
        life = lives.pop()
        for r in records:
            refs[(life, r["item_id"])] = f"{r['template_id']}-v{r['template_version']}"
        for rep in json.loads((sealed / "naive_rag.json").read_text())["arm"]["reports"]:
            report[(life, rep["item_id"])] = rep.get("in_context")
    return report, refs


def show(counts):
    refs = sorted({ref for ref, _ in counts})
    return " | ".join(f"{ref} {counts[(ref, True)]} of {sum(n for (r, _), n in counts.items() if r == ref)}"
                      for ref in refs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", required=True)
    ap.add_argument("--tasks")
    ap.add_argument("--scripted", action="append", default=[])
    ap.add_argument("arms", nargs="*", metavar="LABEL=RUN")
    a = ap.parse_args()
    report, refs = scripted(a.packs)
    targets = None
    if a.tasks:
        targets = {(r["life"], r["branch"], r["item_id"]) for r in json.loads(Path(a.tasks).read_text())["rows"]}
    keys = {(life, iid) for life, _, iid in targets} if targets is not None else {k for k in refs if family(refs[k])}
    print("scripted report, the arms' pack:", show(Counter((refs[k], report.get(k)) for k in keys)))
    for n, other in enumerate(a.scripted, 1):
        rep, rf = scripted(other)
        print(f"scripted report, other pack {n}:",
              show(Counter((rf[k], rep.get(k)) for k in rf if family(rf[k]))))
    for spec in a.arms:
        label, run = spec.split("=", 1)
        run = Path(run)
        arm = json.loads((run / "control.json").read_text())["arm"]
        counts, equal, total = Counter(), 0, 0
        for f in sorted((run / arm).glob("*/*/t2lite_probes.json")):
            life, branch = f.parent.parent.name, f.parent.name
            for r in json.loads(f.read_text()) or []:
                key = (life, r.get("item_id"))
                if targets is not None and (life, branch, r.get("item_id")) not in targets:
                    continue
                if targets is None and not family(refs.get(key)):
                    continue
                first = (r.get("shadow") or {}).get("in_context_initial")
                counts[(refs.get(key), first)] += 1
                total += 1
                equal += first is not None and first == report.get(key)
        line = f"{label} {arm}: needed fact in the first request: {show(counts)}"
        if arm == "naive_rag":
            line += f" | equal to the scripted report on {equal} of {total}"
        print(line)


if __name__ == "__main__":
    main()
