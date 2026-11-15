"""Print the run records of validity round 2's two pre-draw checks without any score (results/validity-2/DECLARATION.md §8).

The oracle smoke (#535) and the anchor check (#536) ran on the public lives. Their cards also hold scores that were never
read (the anchor check's, and the smoke's for every template but the three finalists), so this prints operational fields
only: times, units, probe items, item reruns, compaction, sends, run status and the served identity (a sha256 prefix).
Usage: python records.py LABEL=RUN_DIR ...   (writes JSON to standard output)
"""
import json
import sys
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path


def stamp(ms):
    return datetime.fromtimestamp(ms / 1000, UTC).isoformat(timespec="seconds")


def record(run):
    card = json.loads((run / "card.json").read_text())
    units = json.loads((run / "units.json").read_text())
    spend = json.loads((run / "spend.json").read_text())
    receipt = json.loads((run / "receipt.json").read_text())
    control = json.loads((run / "control.json").read_text())
    return dict(
        control=control["arm"], tier=card["tier"], model=card["model"], effort=card["effort"],
        pack_hash=card["pack_hash"][:12], start=stamp(units["start_ms"]), end=stamp(units["end_ms"]),
        units=card["counts"]["units"], probe_items=len(card["items"]),
        item_reruns=sum(item["infra_reruns"] for item in card["items"]),
        compacted=any(r["role"] == "summariser" and (r["input"] or r["output"]) for r in receipt["tokens_by_role"]),
        sends=spend["settled_calls"], run_status=receipt["run_status"],
        served_identity=sha256(card["served_identity"].encode()).hexdigest()[:12])


def main(argv):
    out = {}
    for arg in argv:
        label, _, path = arg.partition("=")
        out[label] = record(Path(path))
    print(json.dumps(out, indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
