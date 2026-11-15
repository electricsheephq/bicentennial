"""Freeze the follow-up's ranking and descriptive items before any arm runs."""

import argparse
import json
import re
import sys
from collections import Counter
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.items.editions import BY_REF

TARGET_TEMPLATES = ("drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3", "wake-loop-v1")
DESCRIPTIVE = {"G1": "recall-value-v1", "G2": "drift-asof-v1"}
UNREAD = "recall-count-v1"
EDITION = 3
PACKS = ("A", "B", "C")
TABLES = {ref: {t["table_id"] for t in BY_REF[ref].decision_tables} for ref in TARGET_TEMPLATES}
VERSIONS = {ref.rsplit("-v", 1)[0]: int(ref.rsplit("-v", 1)[1]) for ref in TARGET_TEMPLATES}
ROW_FIELDS = ("life", "branch", "item_id", "template_ref", "bundle_id", "decision_table_ref")
HEADER_FIELDS = {"commit", "edition", "spec_sha256", "draw_sha256", "pack_hash", "pack"}


class Refused(ValueError):
    """Only public-safe labels and fixed explanations belong in this exception."""


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("command arguments")


def file_sha256(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def pack_tree_hash(path):
    from bicentennial.packs.manifest import tree_sha256
    return tree_sha256(path)


def pack_records(packs):
    records = []
    for sealed in sorted(Path(packs).glob("pack/*/*/*/sealed")):
        pack = json.loads((sealed / "pack.json").read_bytes())
        items = {i["item_id"]: i for i in pack["items"]}
        records.extend((pack["genre"], rec, items.get(rec["item_id"]))
                       for rec in json.loads((sealed / "records.json").read_bytes()))
    return records


def row(rec, item):
    return dict(life=rec["life"], branch=rec["branch"], item_id=rec["item_id"],
                template_ref=f"{rec['template_id']}-v{rec['template_version']}",
                bundle_id=rec.get("bundle_id"), decision_table_ref=item.get("decision_table_ref"))


def ordered(rows):
    return sorted(rows, key=lambda r: (r["life"], r["branch"], r["item_id"]))


def target_rows(records):
    """Exactly one B0/B1 action pair per ranking kind per G1 life."""
    lives = {g: {r["life"] for genre, r, _ in records if genre == g} for g in DESCRIPTIVE}
    if len(lives["G1"]) != 5 or len(lives["G2"]) != 5 or lives["G1"] & lives["G2"]:
        return None, "pack composition must be five G1 and five G2 lives"
    rows = []
    for genre, rec, item in records:
        tid = rec["template_id"]
        if tid not in VERSIONS:
            continue
        ref = f"{tid}-v{rec['template_version']}"
        if rec["template_version"] != VERSIONS[tid]:
            return None, "ranking template version"
        if (genre != "G1" or item is None or item.get("stage") != "act"
                or item.get("decision_table_ref") not in TABLES[ref] or not rec.get("bundle_id")):
            return None, "ranking item must be a G1 action twin with its declared decision table"
        rows.append(row(rec, item))
    groups = {}
    for r in rows:
        groups.setdefault((r["life"], r["template_ref"], r["bundle_id"]), []).append(r)
    per_life = Counter((life, ref) for life, ref, _ in groups)
    if (len(rows) != 40 or len(groups) != 20
            or per_life != {(life, ref): 1 for life in lives["G1"] for ref in TARGET_TEMPLATES}
            or any(sorted(r["branch"] for r in pair) != ["B0", "B1"] for pair in groups.values())
            or len({(r["life"], r["branch"], r["item_id"]) for r in rows}) != 40):
        return None, "ranking tasks must be 40 items in 20 twin pairs, one per kind per G1 life"
    if any(sorted(r["decision_table_ref"] for r in pair) != sorted(TABLES["drift-config-v3"])
           for (_, ref, _), pair in groups.items() if ref == "drift-config-v3"):
        return None, "config twins must carry one corrected and one hedged table"
    return ordered(rows), None


def descriptive_rows(records):
    """One non-action, non-twin descriptive item per life of its declared genre."""
    rows = []
    for genre, rec, item in records:
        ref = f"{rec['template_id']}-v{rec['template_version']}"
        if ref not in DESCRIPTIVE.values():
            continue
        if (DESCRIPTIVE.get(genre) != ref or item is None or item.get("stage") == "act"
                or rec.get("bundle_id") is not None):
            return None, "descriptive item must be non-action and non-twin on its declared genre"
        rows.append(row(rec, item))
    wanted = {(r["life"], DESCRIPTIVE[g]) for g, r, _ in records if g in DESCRIPTIVE}
    if Counter((r["life"], r["template_ref"]) for r in rows) != dict.fromkeys(wanted, 1):
        return None, "descriptive items must be one per life of the declared genre"
    return ordered(rows), None


def main(argv=None):
    parser = Parser(description=__doc__)
    for key in ("packs", "spec", "draw", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    for key in ("pack", "commit", "edition"):
        parser.add_argument("--" + key, required=True)
    try:
        args = parser.parse_args(argv)
        if args.pack not in PACKS or args.edition != str(EDITION) or not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
            raise Refused("pack, edition or commit")
        records = pack_records(args.packs)
        rows, reason = target_rows(records)
        if reason:
            raise Refused(reason)
        descriptive, reason = descriptive_rows(records)
        if reason:
            raise Refused(reason)
        header = dict(commit=args.commit.lower(), edition=EDITION, spec_sha256=file_sha256(args.spec),
                      draw_sha256=file_sha256(args.draw), pack_hash=pack_tree_hash(args.packs), pack=args.pack)
        payload = canon(dict(header=header, rows=rows, descriptive=descriptive))
        args.out.write_bytes(payload)
        print(args.pack, "target items", len(rows), "descriptive items", len(descriptive))
        print("pack hash", header["pack_hash"][:12], "tasks hash", sha256(payload).hexdigest()[:12])
        return 0
    except Refused as error:
        print("REFUSED:", error)
        return 3
    except (OSError, ValueError, KeyError, TypeError):
        print("REFUSED: task inputs")
        return 3


if __name__ == "__main__":
    sys.exit(main())
