"""Static inventory of clock reads in a Hermes checkout (spike S2). Prints JSON counts.

Classes, by line, over non-test Python sources:
  mixed_clock   a kernel file time (st_mtime / getmtime / st_ctime) used on a line with a
                wall reader (time.time(), datetime.now, a "now" variable): under the shim the
                two sides come from different clocks
  sql_now       SQLite 'now' / CURRENT_TIMESTAMP / unixepoch() in a SQL string: the shim
                cannot reach it
  monotonic     time.monotonic() / perf_counter(): durations; never see a simulated jump
  wall_reads    time.time() / datetime.now() / utcnow() / date.today() calls: simulated
Usage: python inventory_guards.py <hermes checkout>
"""

import json
import re
import sys
from pathlib import Path

MTIME = re.compile(r"\b(st_mtime|st_ctime|getmtime|getctime)\b")
WALL = re.compile(r"time\.time\(\)|datetime\.now\(|\.utcnow\(\)|date\.today\(\)|\bnow\b")
SQL_NOW = re.compile(r"""['"][^'"]*(?:'now'|CURRENT_TIMESTAMP|CURRENT_DATE|unixepoch\(\s*\))""", re.IGNORECASE)
MONO = re.compile(r"time\.monotonic\(|perf_counter\(")
WALL_CALL = re.compile(r"time\.time\(\)|time\.time_ns\(\)|datetime\.now\(|\.utcnow\(\)|date\.today\(\)|_hermes_now\(\)")


def main():
    root = Path(sys.argv[1])
    out = {"mixed_clock": {}, "sql_now": {}, "monotonic_lines": 0, "wall_read_lines": 0, "files_scanned": 0}
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root).as_posix()
        if rel.startswith((".venv/", "tests/", "node_modules/")) or "/tests/" in rel or "/node_modules/" in rel:
            continue
        out["files_scanned"] += 1
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for n, line in enumerate(lines, 1):
            code = line.split("#", 1)[0]
            if MTIME.search(code) and WALL.search(code):
                out["mixed_clock"].setdefault(rel, []).append(n)
            if SQL_NOW.search(code):
                out["sql_now"].setdefault(rel, []).append(n)
            if MONO.search(code):
                out["monotonic_lines"] += 1
            if WALL_CALL.search(code):
                out["wall_read_lines"] += 1
    out["mixed_clock_files"] = len(out["mixed_clock"])
    out["mixed_clock_lines"] = sum(len(v) for v in out["mixed_clock"].values())
    print(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
