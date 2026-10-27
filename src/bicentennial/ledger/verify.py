"""Silent chain and referenced-blob verification; counts contain no values."""

import json
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon

from .blobs import BlobCorrupt, BlobStore


def _scan(path):
    raw = path.read_bytes()
    counts = dict(records=0, chain_breaks=0, truncated_tail=int(bool(raw) and
                  not raw.endswith(b"\n")), bad_blobs=0, missing_lock_fields=0)
    prev, records = "0" * 64, []
    # Only \n ends a line: splitlines() would also split on \r, hiding a one-byte tamper.
    lines = raw.split(b"\n")[:-1] if raw.endswith(b"\n") else raw.split(b"\n")
    for index, line in enumerate(lines if raw else [], 1):
        try:
            rec = json.loads(line)
            if not isinstance(rec, dict):
                raise ValueError
            counts["records"] += 1
            records.append(rec)
            counts["missing_lock_fields"] += int(not {"lock_hash", "attempt_id"} <= rec.keys())
            body = {k: v for k, v in rec.items() if k != "hash"}
            good = (rec.get("seq") == index and type(rec.get("seq")) is int and
                    rec.get("prev_hash") == prev and
                    sha256(prev.encode() + canon(body)).hexdigest() == rec.get("hash") and
                    canon(rec) == line)
            counts["chain_breaks"] += int(not good)
            prev = rec["hash"] if isinstance(rec.get("hash"), str) else "0" * 64
        except (ValueError, TypeError, UnicodeError):
            counts["chain_breaks"] += 1
    return counts, records, prev


def verify(root) -> dict:
    root = Path(root)
    counts, records, _ = _scan(root / "ledger.jsonl")
    store = BlobStore(root / "blobs", None)
    for rec in records:
        upstream = rec.get("upstream", [])
        for row in [rec] + (upstream if isinstance(upstream, list) else []):
            if not isinstance(row, dict):
                continue
            for key in ("req", "resp"):
                if key in row:
                    try:
                        store.get(row[key])
                    except BlobCorrupt:
                        counts["bad_blobs"] += 1
    return counts
