"""Cut canonical cards to one pack's frozen ranking and descriptive entries."""

import hashlib
import json
import re
import sys
from pathlib import Path


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def key(row):
    return tuple(row[k] for k in ("life", "branch", "item_id"))


def outcome_counts(items):
    """The kept items' outcome counts, by the card builder's rules (report/t2_card.py `_row_counts`) and the
    runner's (runner/t2.py `infra`), so the full count less the kept count publishes nothing of an unread item."""
    return dict(kept_copies=sum(item["repro"] is not None for item in items),
                null_citation=sum(item["envelope"] is not None and item["envelope"]["type"] != "unknown"
                                  and item["envelope"]["citation"] is None for item in items),
                infra=sum(item["failure_class"] == "BLOCKED" for item in items))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = "card"
    try:
        tasks = json.loads(Path(argv[0]).read_bytes())
        out = Path(argv[1])
        if out.exists():
            raise ValueError
        targets = [key(r) for r in tasks["rows"] + tasks["descriptive"]]
        if len(set(targets)) != len(targets) or not argv[2:]:
            raise ValueError
        ready, full = {}, {}
        for argument in argv[2:]:
            candidate, sep, run = argument.partition("=")
            label = candidate if re.fullmatch(r"[ABC]\.(?:F[12]|R[12]|O[123]|H[12]|[BGW]1)", candidate) else "card"
            if not sep or label == "card" or candidate[0] != tasks["header"]["pack"] or candidate in full:
                raise ValueError
            raw = (Path(run) / "card.json").read_bytes()
            card = json.loads(raw)
            if canon(card) != raw:
                raise ValueError
            kept = [item for item in card["items"] if key(item) in set(targets)]
            if len(kept) != len(targets) or {key(item) for item in kept} != set(targets):
                raise ValueError
            card["items"] = kept
            card["counts"] = dict(card["counts"], **outcome_counts(kept))
            ready[label] = canon(card)
            full[label] = hashlib.sha256(raw).hexdigest()
        out.mkdir(parents=True)
        for label, payload in ready.items():
            (out / f"{label}.json").write_bytes(payload)
        print(json.dumps(full, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print(label, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
