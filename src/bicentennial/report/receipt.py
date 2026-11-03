"""Caller-measured execution data and zero-spend result publication."""

import json
import os
from fractions import Fraction
from pathlib import Path

from bicentennial.canon import canon, milli, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate


def percentiles(xs) -> dict:
    """Exact nearest-index percentiles, with ties rounded to even."""
    if type(xs) is not list or any(type(x) is not int or x < 0 for x in xs):
        raise ValueError("latencies require a list of nonnegative integers")
    s, n = sorted(xs), len(xs)
    return dict(n=n, **{f"p{p}": s[round(Fraction(p, 100) * (n - 1))] if n else None
                        for p in (50, 90, 95)}, max=s[-1] if n else None)


def _requests(records):
    return sorted((r for r in records if r.get("type") == "request"), key=lambda r: r["seq"])


def ledger_latencies(records) -> list[int]:
    return [r["t_ms"] for r in _requests(records)]


def raw_body_digest(records) -> str:
    return sha256_canon([[r["seq"], r["req"], r["resp"]] for r in _requests(records)])


def busy(marker) -> bool:
    return marker.exit != 0


def load_milli(values):
    if len(values) != 3:
        raise ValueError("three load readings required")
    return [milli(Fraction(v)) for v in values]


def background_summary(arm, ledgers=(), thread_counts=(), *, main_roles) -> dict:
    """Pool independent ledgers, never comparing arrival times across life attempts or sessions.

    quoted_turn is derived with the director's matcher before raw blobs are removed. There is no session-end count:
    the next session starts only after the last one's worker is reaped, so a session's requests are all recorded
    before the next session's first request (RING0 §13 E30).
    """
    late, unattributed = [], 0
    for records in ledgers:
        rows = [r for r in records if r.get("type") == "request"]
        starts = {}
        for r in rows:
            c = r.get("cursor")
            if r.get("role") in main_roles and r.get("subrole") == "cursor" and c and "t" in r:
                key = r["attempt_id"], c["turn"]
                starts[key] = min(starts.get(key, r["t"]), r["t"])
        for r in rows:
            if r.get("role") in main_roles:
                continue
            quoted, arrival = r.get("quoted_turn"), r.get("t")
            if quoted is None:
                unattributed += 1
                continue
            next_start = starts.get((r.get("attempt_id"), quoted + 1))
            if next_start is not None and arrival is not None and arrival > next_start:
                late.append(arrival - next_start)
    counts = [n for n in thread_counts if n is not None]
    return dict(arm=arm, late=dict(count=len(late), max_delay_ms=max(late, default=None)),
        unattributed=dict(count=unattributed),
        threads_at_turn_start=dict(count=sum(n > 0 for n in counts), max_alive=max(counts, default=0)))


def build_receipt(*, run_status, wall_start_ms, wall_end_ms, latency_ms, load_milli,
                  busy_marker_readings, tokens_by_role, runtime_by_role, spend_micro_usd,
                  store_growth_bytes, process_ids, ports, temporary_paths, raw_body_digest,
                  egress_failed_samples=None, timings=None, background=None, turn_wait_s="3.0", units=None) -> dict:
    """Validate a volatile receipt, including caller-summed runtime by role."""
    rows = [dict(role=r, input=v[0], output=v[1]) for r, v in sorted(tokens_by_role.items())]
    receipt = dict(canary=json.loads((SCHEMAS / "receipt.schema.json").read_bytes())[
        "properties"]["canary"]["enum"][0], run_status=run_status,
        wall_start_ms=wall_start_ms, wall_end_ms=wall_end_ms, latency_ms=list(latency_ms),
        latency_summary=percentiles(latency_ms), load_milli=list(load_milli),
        busy_marker_readings=list(busy_marker_readings), tokens_by_role=rows,
        runtime_by_role=[dict(role=r, ms=ms) for r, ms in sorted(runtime_by_role.items())],
        tokens={k: sum(r[k] for r in rows) for k in ("input", "output")},
        spend_micro_usd=spend_micro_usd, store_growth_bytes=store_growth_bytes,
        egress_failed_samples=dict(egress_failed_samples or {}),
        timings=list(timings or []),
        background=list(background or []), turn_wait_s=str(turn_wait_s), units=list(units or []),
        process_ids=sorted(set(process_ids)), ports=sorted(set(ports)),
        temporary_paths=sorted(set(temporary_paths)), raw_body_digest=raw_body_digest)
    validate("receipt", receipt)
    return receipt


def loop_time(receipt):
    return receipt["wall_end_ms"] - receipt["wall_start_ms"], any(receipt["busy_marker_readings"])


class SpendRefused(RuntimeError):
    """A Ring 0 result cannot be published after positive spend."""

    exit_code = 3

    def __init__(self, spend_micro_usd):
        self.spend_micro_usd = spend_micro_usd
        super().__init__(f"Ring 0 spend refused: {spend_micro_usd} micro-USD")


def write_run(run_dir, *, card: bytes, receipt: dict, junit: bytes) -> None:
    """Replace each artifact atomically, publishing card.json last."""
    validate("receipt", receipt)
    if receipt["spend_micro_usd"] > 0:
        raise SpendRefused(receipt["spend_micro_usd"])
    value = json.loads(card)
    try:
        canonical = canon(value)
    except TypeError as error:
        raise ValueError(str(error)) from error
    if card != canonical:
        raise ValueError("card bytes must be canonical")
    validate("card_ring0", value)
    if value["run_status"] != receipt["run_status"]:
        raise ValueError("card and receipt run statuses differ")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("junit.xml", junit), ("receipt.json", canon(receipt)), ("card.json", card)):
        temporary = run_dir / f".{name}.{os.getpid()}.tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
            os.replace(temporary, run_dir / name)
        finally:
            temporary.unlink(missing_ok=True)
