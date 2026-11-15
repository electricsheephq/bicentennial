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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    label = "card"
    try:
        tasks = json.loads(Path(argv[0]).read_bytes())
        out = Path(argv[1])
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
            ready[label] = canon(card)
            full[label] = hashlib.sha256(raw).hexdigest()
        out.mkdir(parents=True, exist_ok=True)
        for label, payload in ready.items():
            (out / f"{label}.json").write_bytes(payload)
        print(json.dumps(full, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        print(label, file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
