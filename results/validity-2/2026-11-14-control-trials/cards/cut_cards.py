"""Cut each arm's card to the round's 80 target items, the rows of the frozen task list (TASKS.json).

A card lists every item its arm scored. The round reads only the target items, so the entries of the other ten (one
`recall-value` item on each life), which hold scores that were never read, are left out. Every other field of the card
is kept unchanged, and the cut card is written in the card's own canonical form.

Usage: python3 -I cut_cards.py TASKS.json OUT_DIR RUN_DIR [RUN_DIR ...]
Each RUN_DIR holds the arm's card.json and is named by the arm's label (F1 ... O3). Writes OUT_DIR/<label>.json and
prints {label: sha256 of the full card.json} as JSON, the hashes listed in full-card-sha256.json.
"""
import hashlib
import json
import sys
from pathlib import Path


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def main(argv):
    tasks, out, runs = Path(argv[0]), Path(argv[1]), [Path(a) for a in argv[2:]]
    targets = {row["item_id"] for row in json.loads(tasks.read_text())["rows"]}
    full = {}
    for run in runs:
        raw = (run / "card.json").read_bytes()
        card = json.loads(raw)
        if canon(card) != raw:
            raise SystemExit(f"{run.name}: card.json is not in canonical form")
        kept = [item for item in card["items"] if item["item_id"] in targets]
        if {item["item_id"] for item in kept} != targets or len(kept) != len(targets):
            raise SystemExit(f"{run.name}: the card does not hold each target item exactly once")
        card["items"] = kept
        (out / f"{run.name}.json").write_bytes(canon(card))
        full[run.name] = hashlib.sha256(raw).hexdigest()
    print(json.dumps(full, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
