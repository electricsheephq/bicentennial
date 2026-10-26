"""Concurrency ramp on the Sol lane (spike S6b), on the Responses SSE wire. S6a's ramp, ported.

Pacing is disabled (rate 0): this burst ramp measures the refusal threshold.
Level n sends 2n tiny requests through n concurrent workers: levels 4, 8, 16, 24 and 32, then 48 only if 32
had no refusal. Each call is the S6b director's own upstream call, made in this process (no director server
runs alongside), so the director's code stays the login store's only reader. Ramp calls are never retried, so
every refusal is seen. It stops at the first level with >= 25% refusals or not fully funded, at once on 3
consecutive quota refusals (S6a's run_level: checked as results arrive), and on any 401 or 403 (the director
stops itself). A level is sustained when every call was sent and none got a 429. Records status, category,
the refusal body's redacted shape and the limit headers per call, never a raw body or a request header:

    sol-env.sh python3.14 ramp_sol.py --out <dir> --budget-file <file>
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "s6a"))
from ramp import run_level
from sol_director import EFFORT, MODEL, Director, Stop, marker_state

KEEP = ("status", "ok", "category", "t_ms", "served_model", "n_events", "limit_headers", "body_shape", "error_obj",
        "scrubbed", "req", "resp", "pace_wait_ms")
QUOTA_HDRS = ("x-codex-primary-used-percent", "x-codex-secondary-used-percent", "x-codex-primary-window-minutes",
              "x-codex-secondary-window-minutes")


def ramp_body(i: int) -> dict:
    return {"model": MODEL, "instructions": "You are a test endpoint. Reply with the number you are given, nothing else.",
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": f"Number: {i}"}]}],
            "reasoning": {"effort": EFFORT}, "store": False, "stream": True}


def one(d: Director, n: int, i: int) -> dict:
    up = d.upstream(ramp_body(i), "ramp", {"session_id": str(uuid.uuid4())})
    if up["category"] == "budget_or_stop":
        return {"unsent": True, "status": 0, "ok": False, "category": "budget_or_stop"}
    u = up.get("usage") or {}
    c = {k: up[k] for k in KEEP if k in up} | {"usage": {
        "input": u.get("input_tokens"), "output": u.get("output_tokens"),
        "reasoning": (u.get("output_tokens_details") or {}).get("reasoning_tokens"),
        "cached": (u.get("input_tokens_details") or {}).get("cached_tokens")}}
    d.ledger.append({"type": "ramp", "run": d.a.run, "level": n, "i": i, "t": time.time(), **c})
    return c


def level(d: Director, n: int, state: dict) -> dict:
    t0, m = time.monotonic(), marker_state()  # Sol does not use GLM: the glm field does not pause these calls
    res = run_level(n, lambda i: one(d, n, i), lambda: not d.stopped, state)
    wall = time.monotonic() - t0
    calls = [c for c in res if c["sent"] and not c.get("unsent")]
    ok, refused = [c for c in calls if c["ok"]], [c for c in calls if not c["ok"]]
    ms = sorted(c["t_ms"] for c in ok)
    hdrs = [c.get("limit_headers") or {} for c in calls]
    return {"level": n, "sent": len(calls), "complete": len(calls) == 2 * n, "ok": len(ok), "refused": len(refused),
            "n429": sum(c["status"] == 429 for c in calls), "statuses": sorted({c["status"] for c in calls}),
            "categories": {k: sum(c["category"] == k for c in refused) for k in {c["category"] for c in refused}},
            "sustained": len(calls) == 2 * n and not any(c["status"] == 429 for c in calls),
            "p50_ms": statistics.median(ms) if ms else None, "p90_ms": ms[round(0.9 * (len(ms) - 1))] if ms else None,
            "max_ms": ms[-1] if ms else None, "wall_s": round(wall, 2), "ok_per_min": round(len(ok) / wall * 60, 1),
            "served_models": sorted({str(c.get("served_model")) for c in ok}),
            "output_tokens_mean": round(statistics.mean(c["usage"]["output"] or 0 for c in ok), 1) if ok else None,
            "quota_headers_last": {h: next((x[h] for x in reversed(hdrs) if h in x), None) for h in QUOTA_HDRS},
            "refusal_shapes": sorted({json.dumps({k: c.get(k) for k in ("status", "category", "body_shape", "error_obj")},
                                                 sort_keys=True) for c in refused}),
            "refusal_limit_header_names": sorted({h for c in refused for h in c.get("limit_headers") or {}}),
            "marker": m, "load": os.getloadavg(), "calls": calls}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--budget-cap", type=int, default=400)
    p.add_argument("--max-calls", type=int, default=264)
    p.add_argument("--run", default="ramp")
    p.add_argument("--timeout", type=float, default=180)
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        d = Director(SimpleNamespace(budget_file=a.budget_file, budget_cap=a.budget_cap, mode="live", run=a.run,
                                     ledger_dir=str(out / "ledger"), life=str(HERE.parent / "s6a" / "micro_life.json"),
                                     model=MODEL, write_turns=False, rate_per_min=0, timeout=a.timeout, chars_per_token=4.0))
    except Stop as e:
        sys.exit("home_busy: another process holds this login home" if str(e) == "home_busy" else str(e))
    state, levels, used = {"quota_streak": 0, "quota_stop": False}, [], 0
    for n in (4, 8, 16, 24, 32, 48):
        if n == 48 and not (levels and levels[-1]["level"] == 32 and levels[-1]["refused"] == 0):
            break
        if d.stopped or used + 2 * n > a.max_calls:
            break
        lv = level(d, n, state)
        used += lv["sent"]
        levels.append(lv)
        print(json.dumps({k: v for k, v in lv.items() if k != "calls"}), flush=True)
        if state["quota_stop"] or d.stopped or not lv["complete"] or lv["sent"] and lv["refused"] / lv["sent"] >= 0.25:
            break
        time.sleep(5)
    sus = [lv["level"] for lv in levels if lv["sustained"]]
    first_bad = next((lv for lv in levels if lv["sent"] and lv["refused"] / lv["sent"] >= 0.25), None)
    summary = {"model": MODEL, "effort": EFFORT, "calls": used, "levels": levels, "stop_reason": d.stop_reason,
               "sustained_concurrency": max(sus) if sus else 0,
               "first_429_level": next((lv["level"] for lv in levels if lv["n429"]), None),
               "binding_limit": ("quota" if state["quota_stop"] else d.stop_reason if d.stopped else
                                 max(first_bad["categories"], key=first_bad["categories"].get) if first_bad
                                 else "none reached (ramp ceiling)")}
    d.summary()
    (out / "ramp.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "levels"}))


if __name__ == "__main__":
    main()
