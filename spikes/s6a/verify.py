"""Ledger and secret checks for spike S6a. Prints counts only, never a matched value.

    python3.14 verify.py <run-dir>...          # hash chain, blob integrity, role counts
    upstream-env.sh python3.14 verify.py --scan <dir-or-file>...   # credential/endpoint scan
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import sys
from compression import zstd
from pathlib import Path
from urllib.parse import urlparse

from director import canon


def check_ledger(run: Path) -> dict:
    prev, roles, bad_chain, bad_blob, truncated, n = "0" * 64, collections.Counter(), 0, 0, 0, 0
    lines = (run / "ledger" / "ledger.jsonl").read_text().splitlines()
    for i, line in enumerate(lines):
        try:
            rec = json.loads(line)
        except ValueError:
            truncated += 1 if i == len(lines) - 1 else 0
            bad_chain += 0 if i == len(lines) - 1 else 1
            continue
        n += 1
        h = rec.pop("hash")
        if rec["prev_hash"] != prev or hashlib.sha256(prev.encode() + canon(rec)).hexdigest() != h:
            bad_chain += 1
        prev = h
        roles[f"{rec.get('type')}:{rec.get('role', '-')}"] += 1
        for ref in [rec.get("req"), rec.get("resp")] + [u.get(k) for u in rec.get("upstream", []) for k in ("req", "resp")]:
            if ref:
                p = run / "ledger" / "blobs" / ref[:2] / f"{ref}.json.zst"
                if not p.exists() or hashlib.sha256(zstd.decompress(p.read_bytes())).hexdigest() != ref:
                    bad_blob += 1
    return {"run": run.name, "records": n, "chain_breaks": bad_chain, "truncated_tail": truncated,
            "bad_blobs": bad_blob, "roles": dict(roles)}


def scan(paths: list[Path]) -> dict:
    needles = [os.environ.get("BICENTENNIAL_UPSTREAM_KEY", "").encode()]
    for var in ("BICENTENNIAL_UPSTREAM_OPENAI_URL", "BICENTENNIAL_UPSTREAM_ANTHROPIC_URL"):
        host = urlparse(os.environ.get(var, "")).hostname
        needles.append(host.encode() if host else b"")
    needles = [x for x in needles if x]
    if not needles:
        sys.exit("--scan needs the upstream environment (run under the helper)")
    files = hits = 0
    for root in paths:
        for f in ([root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]):
            files += 1
            data = f.read_bytes()
            if f.suffix == ".zst":
                data = zstd.decompress(data)
            hits += sum(1 for x in needles if x in data)
    return {"files_scanned": files, "needles": len(needles), "hits": hits}


if __name__ == "__main__":
    if sys.argv[1] == "--scan":
        print(json.dumps(scan([Path(p) for p in sys.argv[2:]])))
    else:
        for r in sys.argv[1:]:
            print(json.dumps(check_ledger(Path(r))))
