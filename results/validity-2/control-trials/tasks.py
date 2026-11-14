"""Validity round 2: freeze TASKS.json before arm 1 (results/validity-2/DECLARATION.md §3).

Usage: python tasks.py --packs PACKS_DIR --spec SPEC.toml --draw DRAW.json --commit SHA --edition 3 --out TASKS.json
Lists every item of TARGET_TEMPLATES from sealed records and pack tables. Requires ten G1 lives, one twin pair
per target template per life, and corrected/hedged config twins. No count questions are read. TASKS.json keeps
round 1's canonical header and row fields and sorting. Prints counts, labels and hash prefixes only (exit 3 on refusal).
"""

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.items.templates.g1 import TEMPLATES, TEMPLATES_V3

# Maintainers may drop a finalist after the oracle smoke by editing this one tuple.
TARGET_TEMPLATES = ("drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3", "wake-loop-v1")
EDITION = 3

CATALOGUE = {f"{t.template_id}-v{t.version}": t for t in (*TEMPLATES, *TEMPLATES_V3)}
TABLES = {ref: {t["table_id"] for t in CATALOGUE[ref].decision_tables} for ref in TARGET_TEMPLATES}
VERSIONS = {ref.rsplit("-v", 1)[0]: int(ref.rsplit("-v", 1)[1]) for ref in TARGET_TEMPLATES}


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
    """Round 2's target rows, or a refusal reason (counts and labels only)."""
    rows = []
    for genre, rec, item in records:
        tid, version = rec["template_id"], rec["template_version"]
        if tid not in VERSIONS:
            continue
        ref = f"{tid}-v{version}"
        if version != VERSIONS[tid]:
            return None, f"the pack carries {ref}, not the v{VERSIONS[tid]} template"
        if item is None:
            return None, f"a {ref} record has no item in the pack"
        table = item["decision_table_ref"]
        if table not in TABLES[ref] or rec["bundle_id"] is None or genre != "G1":
            return None, f"a {ref} item is not a G1 twin with its declared decision table"
        rows.append(dict(life=rec["life"], branch=rec["branch"], item_id=rec["item_id"], template_ref=ref,
                         bundle_id=rec["bundle_id"], decision_table_ref=table))
    rows.sort(key=lambda r: (r["life"], r["branch"], r["item_id"]))
    g1 = {rec["life"] for genre, rec, _ in records if genre == "G1"}
    g2 = {rec["life"] for genre, rec, _ in records if genre == "G2"}
    pairs = Counter((r["life"], r["template_ref"], r["bundle_id"]) for r in rows)
    per_template = Counter(ref for _, ref, _ in pairs)
    per_life = Counter((life, ref) for life, ref, _ in pairs)
    branches = {b: sorted(r["branch"] for r in rows if r["bundle_id"] == b) for _, _, b in pairs}
    n = 10 * len(TARGET_TEMPLATES)
    if not (len(rows) == 2 * n and len(pairs) == n and set(pairs.values()) == {2}
            and all(v == ["B0", "B1"] for v in branches.values()) and len(g1) == 10 and not g2
            and per_template == dict.fromkeys(TARGET_TEMPLATES, 10)
            and set(per_life) == {(life, ref) for life in g1 for ref in TARGET_TEMPLATES}):
        return None, (f"action tasks {len(rows)} in {len(pairs)} pairs over {len(g1)} G1 lives: not {2 * n} tasks in {n}"
                      " twin pairs, 10 per target template, one pair per G1 life (ten G1 lives only)")
    tables = {b: sorted(r["decision_table_ref"] for r in rows if r["bundle_id"] == b)
              for _, ref, b in pairs if ref == "drift-config-v3"}
    if any(v != sorted(TABLES["drift-config-v3"]) for v in tables.values()):
        return None, "a drift-config-v3 pair does not carry one corrected and one hedged table"
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
    print("pack_hash", header["pack_hash"][:12], "tasks sha256", file_sha256(args.out)[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main())
