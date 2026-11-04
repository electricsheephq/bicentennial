"""Rebuild test-file weights from one complete set of saved CI shard logs."""

import argparse
import json
import math
import re
import sys
from pathlib import Path

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "tests/shard_weights.json"
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\S+ ")


def unique_object(pairs):
    result = {}
    for path, seconds in pairs:
        if path in result:
            raise ValueError(f"duplicate file: {path}")
        result[path] = seconds
    return result


def read_logs(paths):
    total = None
    seen = set()
    table = {}
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = TIMESTAMP.sub("", raw, count=1)
            if not line.startswith("shard-durations v1"):
                continue
            fields = line.split(maxsplit=4)
            if len(fields) != 5 or fields[:2] != ["shard-durations", "v1"]:
                raise ValueError("malformed shard-durations v1 line")
            index, count = int(fields[2]), int(fields[3])
            if count < 2 or not 0 <= index < count:
                raise ValueError("shard index or total out of range")
            if total is not None and count != total:
                raise ValueError("mixed shard totals")
            total = count
            if index in seen:
                raise ValueError(f"repeated shard index: {index}")
            seen.add(index)
            weights = json.loads(fields[4], object_pairs_hook=unique_object)
            if not isinstance(weights, dict) or any(
                not isinstance(name, str) or not name or type(seconds) not in (int, float)
                or not math.isfinite(seconds) or seconds < 0
                for name, seconds in weights.items()
            ):
                raise ValueError("expected an object of file paths to finite nonnegative seconds")
            for name, seconds in weights.items():
                if name in table:
                    raise ValueError(f"file in two shards: {name}")
                table[name] = round(seconds, 1)
    if total is None:
        raise ValueError("no shard-durations v1 lines")
    if seen != set(range(total)):
        raise ValueError("missing shard index")
    return table


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", metavar="LOG", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        table = read_logs(args.logs)
        args.out.write_text(json.dumps(table, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    except (OSError, ValueError, OverflowError) as exc:
        print("shard weights: " + " ".join(str(exc).splitlines()), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
