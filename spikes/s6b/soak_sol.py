"""Sustained-concurrency soak on the Sol lane (spike S6b, step 4): C requests held in flight for a fixed window.

The payloads are the forwarded bodies of a finished run's write turns and compactions (the director's own
request blobs, so synthetic micro-life content only), replayed in the source run's order and mix. As in
ramp_sol.py, each call is the S6b director's own upstream call made in this process, so the director's code
stays the login store's only reader. Calls are never retried, so every refusal is seen; a worker pauses after
a refusal. It stops at once on 3 consecutive quota refusals (checked as results arrive, before every send),
on any 401 or 403 (the director stops itself), and at a call ceiling sized under the shared upstream cap.
Before the first call it refuses to start when the planned window would not fit under that ceiling, and names
the window that would. Records per-minute completions, in-flight samples, tokens, the limit headers and the
refusal body's redacted shape, never a raw body or a request header:

    sol-env.sh python3.14 soak_sol.py --source <evidence>/r7b-write --out <dir> --budget-file <file>
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

from compression import zstd
from ramp_sol import KEEP, QUOTA_HDRS
from sol_director import EFFORT, MODEL, Director, marker_state

HERE = Path(__file__).resolve().parent
KINDS = ("write_turn", "summariser")  # the summariser kind is the compaction request


def payloads(source: Path, kinds=KINDS) -> list[dict]:
    """The source run's forwarded bodies of the given kinds, from its ledger blobs, in ledger order."""
    out = []
    for line in (source / "ledger" / "ledger.jsonl").read_text().splitlines():
        rec = json.loads(line)
        for u in rec.get("upstream") or []:
            if rec.get("type") == "request" and u.get("kind") in kinds and u.get("ok") and u.get("req"):
                h = u["req"]
                body = json.loads(zstd.decompress((source / "ledger" / "blobs" / h[:2] / f"{h}.json.zst").read_bytes()))
                out.append({"kind": u["kind"], "hash": h, "body": body, "t_ms": u.get("t_ms") or 0})
    missing = [k for k in kinds if not any(p["kind"] == k for p in out)]
    if missing:
        sys.exit(f"{source}: no forwarded {', '.join(missing)} body; the soak needs the source run's full mix")
    return out


def plan(pays: list[dict], inflight: int, duration: float, ceiling: int) -> dict:
    """Calls the window needs at the source run's mean latency (the mix weights it), against the ceiling."""
    mean_s = max(0.1, statistics.mean(p["t_ms"] for p in pays) / 1000)
    est = round(inflight * duration / mean_s)
    return {"mean_latency_s": round(mean_s, 2), "est_calls": est, "ceiling": ceiling, "fits": est <= ceiling,
            "max_fitting_duration_s": int(ceiling * mean_s / inflight)}


def ceiling_for(budget_file: Path, cap: int, max_calls: int, reserve: int) -> int:
    raw = budget_file.read_text() if budget_file.exists() else ""
    used = json.loads(raw)["total"] if raw.strip() else 0
    return max(0, min(max_calls, cap - used - reserve))


def tok(u: dict) -> dict:
    u = u or {}
    return {"input": u.get("input_tokens"), "output": u.get("output_tokens"),
            "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
            "cached": (u.get("input_tokens_details") or {}).get("cached_tokens")}


def pct(ms: list[float]) -> dict:
    q = lambda f: ms[round(f * (len(ms) - 1))] if ms else None
    return {"p50_s": statistics.median(ms) if ms else None, "p90_s": q(0.9), "p95_s": q(0.95),
            "mean_s": round(statistics.mean(ms), 2) if ms else None}


def overloaded(c: dict) -> bool:
    """A server_overloaded refusal: by category, or by its redacted code or type (HTTP status aside)."""
    return not c["ok"] and (c.get("category") == "overload" or "overload" in json.dumps(
        [c.get("body_shape"), c.get("error_obj")]).lower())


def kind_stats(sent: list[dict], kind: str) -> dict:
    ks = [c for c in sent if c["kind"] == kind]
    ms = sorted(c["t_ms"] / 1000 for c in ks if c["ok"])
    return {"sent": len(ks), "ok": len(ms), **pct(ms),
            **{f"{f}_tokens": sum(c["usage"][f] or 0 for c in ks if c["ok"]) for f in ("input", "output", "reasoning", "cached")}}


def soak(d: Director, pays: list[dict], inflight: int, duration: float, ceiling: int, pause: float = 5.0,
         sample_s: float = 1.0) -> dict:
    lock, state = threading.Lock(), {"quota_streak": 0, "quota_stop": False, "taken": 0, "inflight": 0, "ended": ""}
    calls, samples, t0, utc0 = [], [], time.monotonic(), time.time()
    deadline, m0, load0 = t0 + duration, marker_state(), os.getloadavg()  # Sol does not use GLM

    def gate() -> int | None:  # the stop is checked before every send; the first reason to stop is kept
        with lock:
            why = ("quota_3_in_a_row" if state["quota_stop"] else (d.stop_reason or "director_stop") if d.stopped
                   else "duration" if time.monotonic() >= deadline else "call_ceiling" if state["taken"] >= ceiling
                   else "")
            if why:
                state["ended"] = state["ended"] or why
                return None
            state["taken"] += 1
            state["inflight"] += 1
            return state["taken"] - 1

    def worker():
        while (n := gate()) is not None:
            p = pays[n % len(pays)]
            ts = time.monotonic() - t0
            up = d.upstream(p["body"], f"soak_{p['kind']}", {"session_id": str(uuid.uuid5(uuid.NAMESPACE_OID, p["hash"]))})
            c = {"n": n, "kind": p["kind"], "payload": p["hash"], "t_start_s": round(ts, 2),
                 "t_done_s": round(time.monotonic() - t0, 2), "effort_is_pin": up.get("effort_is_pin"),
                 **{k: up[k] for k in KEEP if k in up}, "usage": tok(up.get("usage"))}
            c["unsent"] = up["category"] == "budget_or_stop"
            with lock:
                state["inflight"] -= 1
                state["quota_streak"] = state["quota_streak"] + 1 if c.get("category") == "quota" else 0
                state["quota_stop"] |= state["quota_streak"] >= 3
                calls.append(c)
            if not c["unsent"]:
                d.ledger.append({"type": "soak", "run": d.a.run, "t": time.time(), **c})
            if not c["ok"] and not c["unsent"]:
                time.sleep(pause)

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(inflight)]
    [t.start() for t in ts]
    while any(t.is_alive() for t in ts):
        with lock:
            samples.append((round(time.monotonic() - t0, 1), state["inflight"]))
        time.sleep(sample_s)
    [t.join() for t in ts]
    wall = time.monotonic() - t0
    sent = sorted((c for c in calls if not c["unsent"]), key=lambda c: c["n"])
    ok, refused = [c for c in sent if c["ok"]], [c for c in sent if not c["ok"]]
    last_send = max((c["t_start_s"] for c in sent), default=0.0)
    window = [n for t, n in samples if sample_s <= t <= last_send]  # after start-up, while sends still started
    ended = state["ended"]
    minutes = []
    for i in range(int(wall // 60) + 1):
        done = [c for c in sent if i * 60 <= c["t_done_s"] < (i + 1) * 60]
        hdrs = [c.get("limit_headers") or {} for c in sorted(done, key=lambda c: c["t_done_s"])]
        minutes.append({"minute": i, "ok": sum(c["ok"] for c in done), "refused": sum(not c["ok"] for c in done),
                        "n429": sum(c["status"] == 429 for c in done),
                        "input_tokens": sum(c["usage"]["input"] or 0 for c in done if c["ok"]),
                        "output_tokens": sum(c["usage"]["output"] or 0 for c in done if c["ok"]),
                        "quota_headers_last": {h: next((x[h] for x in reversed(hdrs) if h in x), None)
                                               for h in QUOTA_HDRS}})
    hdrs = [c.get("limit_headers") or {} for c in sorted(sent, key=lambda c: c["t_done_s"])]
    return {"model": MODEL, "effort": EFFORT, "inflight_target": inflight, "duration_s": duration,
            "ceiling": ceiling, "ended_by": ended, "stop_reason": d.stop_reason, "sent": len(sent), "ok": len(ok),
            "refused": len(refused), "n429": sum(c["status"] == 429 for c in sent),
            "server_overloaded": (no := sum(map(overloaded, sent))), "overloaded_per_1000": round(1000 * no / max(1, len(sent)), 1),
            "latency_ok": pct(sorted(c["t_ms"] / 1000 for c in ok)),
            "utc_start": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(utc0)),
            "utc_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(utc0 + wall)),
            "statuses": sorted({c["status"] for c in sent}),
            "categories": {k: sum(c["category"] == k for c in refused) for k in {c["category"] for c in refused}},
            "sustained": ended == "duration" and not refused,
            "last_send_s": last_send, "wall_s": round(wall, 2), "drain_s": round(wall - last_send, 2),
            "inflight_min": min(window, default=0), "inflight_mean": round(statistics.mean(window), 1) if window else 0,
            "inflight_max": max((n for _, n in samples), default=0),
            "ok_per_min": round(len(ok) / max(wall, 1e-9) * 60, 1), "per_minute": minutes,
            "by_kind": {k: kind_stats(sent, k) for k in KINDS},
            "effort_is_pin": sum(bool(c.get("effort_is_pin")) for c in sent),
            "served_models": sorted({str(c.get("served_model")) for c in ok}),
            "quota_headers_first": {h: next((x[h] for x in hdrs if h in x), None) for h in QUOTA_HDRS},
            "quota_headers_last": {h: next((x[h] for x in reversed(hdrs) if h in x), None) for h in QUOTA_HDRS},
            "refusal_shapes": sorted({json.dumps({k: c.get(k) for k in ("status", "category", "body_shape", "error_obj")},
                                                 sort_keys=True) for c in refused}),
            "refusal_limit_header_names": sorted({h for c in refused for h in c.get("limit_headers") or {}}),
            "marker": {"start": m0, "end": marker_state()}, "load": {"start": load0, "end": os.getloadavg()},
            "payloads": {"n": len(pays), "by_kind": {k: sum(p["kind"] == k for p in pays) for k in KINDS}},
            "calls": sent}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", required=True, help="the finished run's evidence dir (its ledger and blobs)")
    p.add_argument("--out", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--budget-cap", type=int, default=1400)
    p.add_argument("--max-calls", type=int, default=700)
    p.add_argument("--reserve", type=int, default=50, help="calls kept under the cap for the readings after")
    p.add_argument("--inflight", type=int, default=24)
    p.add_argument("--duration", type=float, default=180)
    p.add_argument("--pause", type=float, default=5.0, help="a worker's pause after a refusal")
    p.add_argument("--run", default="soak")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--plan-only", action="store_true")
    a = p.parse_args()
    out = Path(a.out)
    pays = payloads(Path(a.source))
    pl = plan(pays, a.inflight, a.duration, ceiling_for(Path(a.budget_file), a.budget_cap, a.max_calls, a.reserve))
    print(json.dumps(pl), flush=True)
    if a.plan_only or not pl["fits"]:
        sys.exit(0 if a.plan_only else f"the planned window needs ~{pl['est_calls']} calls over a ceiling of "
                 f"{pl['ceiling']}; run with --duration {pl['max_fitting_duration_s']} or less")
    while marker_state().get("exit") == 11:  # exit 11: no new load on the machine
        time.sleep(60)
    out.mkdir(parents=True, exist_ok=True)
    d = Director(SimpleNamespace(budget_file=a.budget_file, budget_cap=a.budget_cap, mode="live", run=a.run,
                                 ledger_dir=str(out / "ledger"), life=str(HERE.parent / "s6a" / "micro_life.json"),
                                 model=MODEL, write_turns=False, timeout=a.timeout, chars_per_token=4.0))
    res = soak(d, pays, a.inflight, a.duration, pl["ceiling"], a.pause) | {"plan": pl, "source": Path(a.source).name}
    (out / "soak.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k not in ("calls", "per_minute")}))


if __name__ == "__main__":
    main()
