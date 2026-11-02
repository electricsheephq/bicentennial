"""Compare published reference_store T0 cards (aggregates, gate verdict, run status): OLD_RUN NEW_RUN (exit 0/1/2)."""

import argparse
import json
import os
import sys
from pathlib import Path

# The compared fields' allowed values, read from the card_ring0 schema so they cannot drift from it.
CARD = json.loads((Path(__file__).resolve().parents[1] / "schemas/card_ring0.schema.json").read_bytes())["properties"]
VERDICTS, STATUSES = set(CARD["gate_verdict"]["enum"]), set(CARD["run_status"]["enum"])
ROW = CARD["aggregates"]["items"]["properties"]
STAGES, TRACKS = set(ROW["stage"]["enum"]), set(ROW["track"]["enum"])
LOW, HIGH = ROW["score_milli"]["minimum"], ROW["score_milli"]["maximum"]


def read_aggregates(root):
    root = Path(root)
    pack_root = root / "pack"
    if not pack_root.is_dir():
        raise ValueError(f"{root}: missing pack directory")
    result = {}
    def unreadable(error):
        raise error

    paths = []
    for directory, children, files in os.walk(pack_root, onerror=unreadable):
        if "card.json" in files:
            paths.append(Path(directory) / "card.json")
        elif not children:
            raise ValueError(f"{directory}: missing card.json")
    for path in sorted(paths):
        card = json.loads(path.read_bytes())
        if card["system"] != "reference_store" or card["tier"] != "T0":
            raise ValueError(f"{path}: expected reference_store T0 card")
        if not isinstance(card["aggregates"], list):
            raise ValueError(f"{path}: malformed aggregates")
        aggregates = {}
        for row in card["aggregates"]:
            if type(row) is not dict or row.keys() != ROW.keys():
                raise ValueError(f"{path}: malformed aggregate")
            stage, track, score = row["stage"], row["track"], row["score_milli"]
            if stage not in STAGES or track not in TRACKS or (
                    score is not None and (type(score) is not int or not LOW <= score <= HIGH)):
                raise ValueError(f"{path}: malformed aggregate")
            key = f"{stage}/{track}"
            if key in aggregates:
                raise ValueError(f"{path}: duplicate aggregate {key}")
            aggregates[key] = score
        verdict, status = card["gate_verdict"], card["run_status"]
        if verdict not in VERDICTS or status not in STATUSES:
            raise ValueError(f"{path}: malformed gate verdict or run status")
        result[path.parent.relative_to(root).as_posix()] = dict(
            aggregates=aggregates, gate_verdict=verdict, run_status=status)
    if not result:
        raise ValueError(f"{root}: no reference T0 cards")
    return result


def differences(old, new, prefix=""):
    """Yield every changed leaf, retaining identities and missing values."""
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(old.keys() | new.keys()):
            path = f"{prefix}/{key}" if prefix else key
            if key not in old:
                yield f"{path}: <missing> -> {json.dumps(new[key], sort_keys=True)}"
            elif key not in new:
                yield f"{path}: {json.dumps(old[key], sort_keys=True)} -> <missing>"
            else:
                yield from differences(old[key], new[key], path)
    elif isinstance(old, list) and isinstance(new, list):
        yield from differences(dict(enumerate(old)), dict(enumerate(new)), prefix)
    elif old != new or type(old) is not type(new):
        yield f"{prefix}: {json.dumps(old)} -> {json.dumps(new)}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old_run")
    parser.add_argument("new_run")
    args = parser.parse_args(argv)
    try:
        changes = list(differences(read_aggregates(args.old_run), read_aggregates(args.new_run)))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"unreadable T0 input: {exc}", file=sys.stderr)
        return 2
    for change in changes:
        print(change)
    return int(bool(changes))


if __name__ == "__main__":
    raise SystemExit(main())
