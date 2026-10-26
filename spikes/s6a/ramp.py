"""Concurrency ramp on the agent's model lane (spike S6a, SPEC item 6).

Level n sends 2n tiny requests (max_tokens <= 32) through n concurrent workers. Levels 1, 2, 4,
8, 16, then 24 only if 16 is clean. Stops at the first level with >= 25% refusals or not fully
funded, and at once on 3 consecutive quota refusals. Records status codes and a refusal category
per call, never raw bodies. Run under the upstream helper:

    upstream-env.sh python3.14 ramp.py --out <dir> --budget-file <file>
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from director import Budget, marker_state, refusal_category


def one(url: str, key: str, model: str, i: int) -> dict:
    body = {"model": model, "max_tokens": 16, "stream": False,
            "messages": [{"role": "user", "content": f"Reply with the number {i} and nothing else."}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read())
        return {"status": r.status, "ok": True, "t_ms": round((time.monotonic() - t0) * 1000),
                "usage": resp.get("usage"), "served_model": resp.get("model")}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "ok": False, "category": refusal_category(e.code, e.read().decode("utf-8", "replace")),
                "t_ms": round((time.monotonic() - t0) * 1000)}
    except Exception as e:  # the class only: messages can carry the host
        return {"status": -1, "ok": False, "category": f"error:{type(e).__name__}",
                "t_ms": round((time.monotonic() - t0) * 1000)}


def run_level(n: int, call, take, state: dict) -> list[dict]:
    """2n calls through n workers; budget is taken per call as it starts. The quota streak is updated
    as results arrive, so 3 in a row stop the calls not yet started (the stop spans levels)."""
    lock = threading.Lock()

    def task(i):
        with lock:
            if state["quota_stop"]:
                return {"i": i, "sent": False, "reason": "quota_stop"}
        if not take():
            return {"i": i, "sent": False, "reason": "budget"}
        c = {"i": i, "sent": True, **call(i)}
        with lock:
            state["quota_streak"] = state["quota_streak"] + 1 if c.get("category") == "quota" else 0
            state["quota_stop"] |= state["quota_streak"] >= 3
        return c

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(task, range(2 * n)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--model", default="glm-5.3")
    p.add_argument("--max-calls", type=int, default=120)
    a = p.parse_args()
    url = os.environ["BICENTENNIAL_UPSTREAM_OPENAI_URL"].rstrip("/") + "/chat/completions"
    key = os.environ["BICENTENNIAL_UPSTREAM_KEY"]
    budget, used, levels, out = Budget(Path(a.budget_file), 400), 0, [], Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    state = {"quota_streak": 0, "quota_stop": False}
    for n in (1, 2, 4, 8, 16, 24):
        if n == 24 and not (levels and levels[-1]["level"] == 16 and levels[-1]["refused"] == 0):
            break
        if used + 2 * n > a.max_calls:
            break
        m = marker_state()
        while m.get("glm"):
            time.sleep(60)
            m = marker_state()
        t0 = time.monotonic()
        res = run_level(n, lambda i: one(url, key, a.model, i), lambda: budget.take("ramp", "ramp"), state)
        wall = time.monotonic() - t0
        calls = [c for c in res if c["sent"]]
        used += len(calls)
        ok = [c for c in calls if c["ok"]]
        refused = [c for c in calls if not c["ok"]]
        lv = {"level": n, "sent": len(calls), "complete": len(calls) == 2 * n, "ok": len(ok), "refused": len(refused),
              "statuses": sorted({c["status"] for c in calls}),
              "categories": {k: sum(1 for c in refused if c["category"] == k) for k in {c["category"] for c in refused}},
              "p50_ms": statistics.median([c["t_ms"] for c in ok]) if ok else None,
              "max_ms": max([c["t_ms"] for c in ok]) if ok else None, "wall_s": round(wall, 2),
              "ok_per_min": round(len(ok) / wall * 60, 1), "served_models": sorted({str(c.get("served_model")) for c in ok}),
              "marker": m, "load": os.getloadavg(), "calls": calls}
        levels.append(lv)
        print(json.dumps({k: v for k, v in lv.items() if k != "calls"}), flush=True)
        if state["quota_stop"] or not lv["complete"] or len(calls) and len(refused) / len(calls) >= 0.25:
            break
        time.sleep(5)
    clean = [lv["level"] for lv in levels if lv["complete"] and lv["refused"] == 0]
    first_bad = next((lv for lv in levels if lv["sent"] and lv["refused"] / lv["sent"] >= 0.25), None)
    summary = {"model": a.model, "calls": used, "levels": levels,
               "sustained_concurrency": max(clean) if clean else 0,
               "binding_limit": ("quota" if state["quota_stop"] else
                                 max(first_bad["categories"], key=first_bad["categories"].get) if first_bad
                                 else "none reached (ramp ceiling)")}
    (out / "ramp.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "levels"}))


if __name__ == "__main__":
    main()
