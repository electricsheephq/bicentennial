"""Validity round 1: the frozen task list (TASKS.json) that results/validity-1/DECLARATION.md §3 posts before arm 1.

Usage: python tasks.py --packs PACKS_DIR --spec SPEC.toml --draw DRAW.json --commit SHA --edition 2 --out TASKS.json
Lists the target items from the pack's own records (sealed/records.json, with each item's decision_table_ref from
sealed/pack.json): every item of a v2 template, action items on both branches and count questions as the pack keeps
them. Writes canonical JSON (bicentennial.canon.canon) with a header (commit, edition, spec sha256, draw sha256, pack
hash as Milestone 1 computes it: bicentennial.packs.manifest.tree_sha256 of --packs) and rows sorted by (life,
branch, item_id), each with life, branch, item_id, template_ref, bundle_id (or null) and decision_table_ref (null for
a count question, whose template has no decision table). Refuses (exit 3) unless there are exactly 30 action tasks in
15 twin pairs (5 per action template, one pair per G1 life) and 5 count questions (one per G2 life), and refuses any
other version of the four templates. Prints counts and the file's sha256 only.
"""

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon

ACTION = ("drift-chain-fault", "drift-config", "drift-quote")
COUNT = "recall-count"
TABLES = {"drift-chain-fault": {"drift-chain-fault-v2"}, "drift-quote": {"drift-quote-v2"},
          "drift-config": {"drift-config-corrected-v2", "drift-config-hedged-v2"}}
EDITION = 2


def pack_tree_hash(packs):
    from bicentennial.packs.manifest import tree_sha256
    return tree_sha256(packs)


def file_sha256(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def pack_records(packs):
    """[(genre, record, item)] for every record of every life in the pack, as the pack keeps them."""
    out = []
    for sealed in sorted(Path(packs).glob("pack/*/*/*/sealed")):
        pack = json.loads((sealed / "pack.json").read_text())
        items = {i["item_id"]: i for i in pack["items"]}
        for record in json.loads((sealed / "records.json").read_text()):
            out.append((pack["genre"], record, items.get(record["item_id"])))
    return out


def target_rows(records):
    """The v2 rows, or a refusal reason (counts and labels only)."""
    rows = []
    for genre, rec, item in records:
        tid, version = rec["template_id"], rec["template_version"]
        if tid not in (*ACTION, COUNT):
            continue
        ref = f"{tid}-v{version}"
        if version != EDITION:
            return None, f"the pack carries {ref}, not the v{EDITION} template"
        if item is None:
            return None, f"a {ref} record has no item in the pack"
        table = item["decision_table_ref"] if tid in ACTION else None
        if tid in ACTION and (table not in TABLES[tid] or rec["bundle_id"] is None or genre != "G1"):
            return None, f"a {ref} item is not a G1 twin with a v{EDITION} decision table"
        if tid == COUNT and (rec["bundle_id"] is not None or genre != "G2" or rec["branch"] != "B0"):
            return None, f"a {ref} item is not a single G2 question on B0"
        rows.append(dict(life=rec["life"], branch=rec["branch"], item_id=rec["item_id"], template_ref=ref,
                         bundle_id=rec["bundle_id"], decision_table_ref=table))
    rows.sort(key=lambda r: (r["life"], r["branch"], r["item_id"]))
    g1 = {rec["life"] for genre, rec, _ in records if genre == "G1"}
    g2 = {rec["life"] for genre, rec, _ in records if genre == "G2"}
    action = [r for r in rows if r["bundle_id"] is not None]
    count = [r for r in rows if r["bundle_id"] is None]
    pairs = Counter((r["life"], r["template_ref"], r["bundle_id"]) for r in action)
    per_template = Counter(ref for _, ref, _ in pairs)
    per_life = Counter((life, ref) for life, ref, _ in pairs)
    branches = {b: sorted(r["branch"] for r in action if r["bundle_id"] == b) for _, _, b in pairs}
    if not (len(action) == 30 and len(pairs) == 15 and set(pairs.values()) == {2}
            and all(v == ["B0", "B1"] for v in branches.values()) and len(g1) == 5
            and per_template == {f"{t}-v{EDITION}": 5 for t in ACTION}
            and set(per_life) == {(life, f"{t}-v{EDITION}") for life in g1 for t in ACTION}):
        return None, (f"action tasks {len(action)} in {len(pairs)} pairs over {len(g1)} G1 lives: not 30 tasks in 15"
                      " twin pairs, 5 per action template, one pair per G1 life")
    if not (len(count) == 5 and len(g2) == 5 and sorted(r["life"] for r in count) == sorted(g2)):
        return None, (f"count questions {len(count)} over {len(g2)} G2 lives: not 5 questions, one per G2 life")
    return rows, None


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--packs", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--draw", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--edition", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit) or args.edition != EDITION:
        parser.error(f"--commit must be a 40-character sha and --edition {EDITION}")
    rows, refusal = target_rows(pack_records(args.packs))
    if refusal:
        print("REFUSED:", refusal)
        return 3
    header = dict(commit=args.commit, edition=args.edition, spec_sha256=file_sha256(args.spec),
                  draw_sha256=file_sha256(args.draw), pack_hash=pack_tree_hash(args.packs))
    args.out.write_bytes(canon(dict(header=header, rows=rows)))
    print("target items", len(rows), dict(sorted(Counter(r["template_ref"] for r in rows).items())))
    print("pack_hash", header["pack_hash"][:12], "tasks sha256", file_sha256(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
