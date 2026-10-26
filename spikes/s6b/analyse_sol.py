"""Aggregate S6b measurements and project PREREG-v0.1 §11 at the Sol lane's measured concurrency.

    python3.14 analyse_sol.py --evidence <dir> --write r7b-write --ramp ramp/ramp.json --soak soak/soak.json \
        --quota quota/readings.txt --out results/

S6a's measures, formulas and grid (spikes/s6a/analyse.py), unchanged. The Responses wire reports input and
output tokens, which are mapped onto S6a's prompt and completion fields. A turn with no write turn makes no
model call, so its harness-only time is S6a's scripted measure (spikes/s6a/results/measurements.json).
C is the soak's effective concurrency when a soak ran (Little's law over its ok calls: busy seconds over the
send window), else the ramp's level, labelled "burst, not sustained". The quota extrapolation is a bound, from
one account at one time of day: a reading that did not move bounds the burn by its resolution.
Writes measurements.json and projection.json (small aggregates only).
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "s6a"))
from analyse import grid, load, projection, run_measures, stats

S6A = json.loads((HERE.parent / "s6a" / "results" / "measurements.json").read_text())
SAME = ("turn_s", "turn_ex_compaction_s_mean", "session_total_s", "session_fixed_s", "restart_s", "rss_kib")


def sol_load(evid: Path, run: str):
    rows, led, summ = load(evid, run)
    for r in led:
        for u in r.get("upstream", []):
            us = u.get("usage") or {}
            if us:
                u["usage"] = {"prompt_tokens": us.get("input_tokens"), "completion_tokens": us.get("output_tokens"),
                              "reasoning_tokens": (us.get("output_tokens_details") or {}).get("reasoning_tokens"),
                              "cached_tokens": (us.get("input_tokens_details") or {}).get("cached_tokens")}
    m = run_measures(rows, led, summ)
    ups = [u for r in led if r.get("type") == "request" for u in r.get("upstream", []) if u.get("ok")]
    m["extra_tokens"] = {k: {f: stats([u["usage"].get(f) for u in ups if u["kind"] == k and u.get("usage")])
                             for f in ("reasoning_tokens", "cached_tokens")} for k in ("write_turn", "summariser")}
    m["rss_peak_kib"] = max([w["peak"] for w in summ.get("worker_rss_kib", [])] or [0])
    m["upstream_attempts"] = sum(len(r.get("upstream", [])) for r in led if r.get("type") == "request")
    m["refusals"] = sorted({(u.get("status"), u.get("category")) for r in led for u in r.get("upstream", [])
                            if not u.get("ok")})
    m["effort_is_pin"] = sum(bool(u.get("effort_is_pin")) for r in led for u in r.get("upstream", []))
    m["served_models"] = sorted({str(u.get("served_model")) for u in ups})
    m["retries"] = retries(led)
    m["aux_effort"] = {sub: {"n": len(us), "pinned": sum(bool(u.get("effort_is_pin")) for u in us),
                             "no_reasoning": sum(u.get("reasoning") is None for u in us)}
                       for sub in sorted({r.get("subrole") for r in led if r.get("role") in ("aux", "summariser")})
                       if (us := [u for r in led if r.get("type") == "request" and r.get("role") in ("aux", "summariser")
                                  and r.get("subrole") == sub for u in r.get("upstream", [])])}
    return m


def retries(led: list[dict]) -> dict:
    """Every refused upstream attempt in the run: which request, how the director handled it, the wait."""
    rows = [{"request_seq": r["seq"], "role": r.get("role"), "kind": u.get("kind"), "status": u.get("status"),
             "category": u.get("category"), "t_ms": u.get("t_ms"), "retry_wait_s": u.get("retry_wait_s"),
             "served": r.get("served"), "retry_after": (u.get("limit_headers") or {}).get("retry-after"),
             "code": json.dumps([u.get("body_shape"), u.get("error_obj")])[:300]}
            for r in led if r.get("type") == "request" for u in r.get("upstream", []) if not u.get("ok")]
    over = [x for x in rows if x["category"] == "overload" or "overload" in x["code"].lower()]
    n = sum(len(r.get("upstream", [])) for r in led if r.get("type") == "request")
    wait = {}  # a request's latency with and without the director's retry waits
    for r in led:
        if r.get("type") == "request" and r.get("upstream"):
            k = r["upstream"][-1].get("kind")
            up = sum(u.get("t_ms") or 0 for u in r["upstream"]) / 1000
            w = sum(u.get("retry_wait_s") or 0 for u in r["upstream"])
            wait.setdefault(k, {"with": [], "without": []})
            wait[k]["with"].append(up + w)
            wait[k]["without"].append(up)
    return {"attempts": n, "refused": len(rows), "n429": sum(x["status"] == 429 for x in rows),
            "server_overloaded": len(over), "overloaded_per_1000": round(1000 * len(over) / max(1, n), 1),
            "retry_wait_s_total": sum(x["retry_wait_s"] or 0 for x in rows), "events": rows,
            "request_s": {k: {"with_waits": stats(v["with"]), "without_waits": stats(v["without"])} for k, v in wait.items()}}


RATES = {"1 account (planning, 90% of the ~200/min burst threshold)": 180, "2 accounts (hypothetical)": 360}


def requests(rows: list[dict], led: list[dict], inputs: dict) -> tuple[dict, dict]:
    """Upstream requests (attempts, retries included) per unit, by kind, and the §11 inputs that make the lane
    reading count requests: at latency x1 the lane-work term then sums requests, not seconds. A scripted turn's
    own upstream requests (0 when every scripted turn is served from the script) are folded into the write term."""
    reqs = [r for r in led if r.get("type") == "request"]
    att = lambda pred: sum(1 for r in reqs for u in r.get("upstream", []) if pred(r, u))
    turns = [r for r in reqs if r.get("role") == "replay_main" and r.get("subrole") == "cursor"]
    probes = [r for r in reqs if r.get("role") == "probe_main" and r.get("subrole") == "cursor"]
    n_sess = max(1, len({(r["phase"], r["session"]) for r in rows}))
    q = {"scripted_per_turn": att(lambda r, u: r.get("role") == "replay_main" and u["kind"] != "write_turn")
         / max(1, len(turns)),
         "write_per_turn": att(lambda r, u: u["kind"] == "write_turn") / max(1, len(turns)),
         "compaction_per_compaction": att(lambda r, u: u["kind"] == "summariser")
         / max(1, sum(r.get("role") == "summariser" for r in reqs)),
         "aux_per_session": att(lambda r, u: u["kind"] == "aux") / n_sess,
         "probe_per_probe_turn": att(lambda r, u: u["kind"] == "probe") / max(1, len(probes)),
         "sessions": n_sess, "turns": len(turns), "probe_turns": len(probes)}
    ri = dict(inputs, upstream_turn_s=q["write_per_turn"] + q["scripted_per_turn"],
              summariser_s=q["compaction_per_compaction"], aux_per_session_s=q["aux_per_session"],
              probe_upstream_s=q["probe_per_probe_turn"])
    return q, ri


def rate_grid(rows: list[dict], ri: dict) -> list[dict]:
    """Each S6a grid cell plus the request-rate bound N_req / R_s; the verdict is max(lane time, N_req / R_s)."""
    n = {}
    for r in rows:
        key = (r["L"], r["cuts"], r["cadence"])
        if key not in n:
            kw = {"b": 100, "L_rob": 4} if r["cuts"] == "cuts 1-2" else {}
            pr = projection(ri, lat=1.0, C=1, L=r["L"], cadence=r["cadence"], **kw)
            n[key] = {run: round(pr[run]["lane_work_h"] * 3600) for run in ("board", "robustness")}
        for run in ("board", "robustness"):
            q = r[run]
            q["N_req"] = n[key][run]
            for label, rs in RATES.items():
                rate_h = round(q["N_req"] / rs / 60, 1)
                q.setdefault("rate", {})[label] = {"rate_h": rate_h, "fits": max(q["lane_h"], rate_h) <= 24}
    return rows


def soak_level(soak: dict) -> dict:
    ok = [c for c in soak["calls"] if c["ok"]]
    busy = sum(c["t_ms"] for c in ok) / 1000
    window = soak["last_send_s"] or soak["wall_s"]
    in_window = sum(c["t_done_s"] <= window for c in ok)
    return {"C_effective": round(busy / window, 1), "ok_per_min_send_window": round(in_window / window * 60, 1),
            "mean_ok_call_s": round(busy / max(1, len(ok)), 2), "inflight_target": soak["inflight_target"],
            "sustained_at_target": soak["sustained"], "n429": soak["n429"], "server_overloaded": soak["server_overloaded"],
            "sent": soak["sent"], "utc": [soak["utc_start"], soak["utc_end"]], "ended_by": soak["ended_by"]}


def quota(path: Path, r7_calls: int, soak: dict | None, board_calls: dict) -> dict:
    """Readings are whole percentages: an unmoved reading bounds the burn by one step (an upper bound only)."""
    rd = []
    for line in path.read_text().splitlines() if path.exists() else []:
        m = re.match(r"(\S+) (\S+) (\S+) weekly_free (\S+) session_free (\S+)", line)
        if m:
            rd.append({"utc": m[1], "when": m[2], "plan": m[3], "weekly_free": m[4], "session_free": m[5]})
    pairs = {}
    for a, b in itertools.pairwise(rd):
        try:
            pairs[f"{a['when']}->{b['when']}"] = {"weekly_pts": float(a["weekly_free"]) - float(b["weekly_free"]),
                                                    "session_pts": float(a["session_free"]) - float(b["session_free"])}
        except ValueError:
            continue
    soak_calls = soak["sent"] if soak else 0
    per_call_ub = 1.0 / soak_calls if soak_calls and pairs.get("before-soak->after-soak", {}).get("weekly_pts") == 0 else None
    return {"readings": rd, "burn_points": pairs, "resolution_pts": 1, "r7b_calls": r7_calls, "soak_calls": soak_calls,
            "weekly_pts_per_call_upper_bound": per_call_ub,
            "board_calls": board_calls,
            "board_weekly_pts_upper_bound": {k: round(v * per_call_ub, 1) for k, v in board_calls.items()} if per_call_ub
            else None,
            "note": "extrapolation from one account at one time of day; an upper bound from an unmoved whole-percent reading"}


def compare(r7: dict) -> list[dict]:
    """r7 (Sol) against S6a's r6 (GLM, parameters forwarded) and r3 (GLM, parameters stripped)."""
    out = []
    for name, m in (("r7b Sol", r7), ("r6 GLM forwarded", S6A["runs"]["write"]), ("r3 GLM stripped", S6A["runs"]["compare"])):
        w = m["write_turn"]
        out.append({"run": name, "write_turn_latency_s": w["latency_s"], "prompt_tokens": w["prompt_tokens"],
                    "completion_tokens": w["completion_tokens"], "memory_calls": w["memory_tool_calls"],
                    "readback_ok": w["readback_ok"], "summariser_s": m["summariser"]["latency_s"],
                    "summariser_completion_tokens": m["summariser"]["completion_tokens"],
                    "aux_s": m["aux"]["latency_s"], "probe_turn_s": m["probe"]["turn_s"]} | {k: m[k] for k in SAME})
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", required=True)
    p.add_argument("--write", required=True)
    p.add_argument("--ramp", default="ramp/ramp.json")
    p.add_argument("--soak", default="", help="the soak's soak.json, relative to --evidence")
    p.add_argument("--quota", default="quota/readings.txt")
    p.add_argument("--out", default="results")
    a = p.parse_args()
    evid, out = Path(a.evidence), Path(a.out)
    out.mkdir(exist_ok=True)
    w = sol_load(evid, a.write)
    if not w["complete"] or w["unknown"]:
        sys.exit("the run has an unfinished session, a failed write turn or an unknown request; not projecting")
    ramp = json.loads((evid / a.ramp).read_text())
    ramp_s = {k: v for k, v in ramp.items() if k != "levels"} | {
        "levels": [{k: v for k, v in lv.items() if k != "calls"} for lv in ramp["levels"]]}
    inputs = {"turn_ex_comp_s": w["turn_ex_compaction_s_mean"],
              "upstream_turn_s": w["write_turn"]["upstream_s_per_turn"]["mean"],
              "summariser_s": w["summariser"]["latency_s"].get("mean", 0.0), "session_fixed_s": w["session_fixed_s"]["mean"],
              "comp_per_sprint": w["summariser"]["calls"] / max(1, w["long_sessions"]),
              "probe_turn_s": w["probe"]["turn_s"]["mean"], "probe_upstream_s": w["probe"]["upstream_s_per_turn"],
              "probe_fixed_s": w["probe"]["fixed_s"]["mean"], "aux_per_session_s": w["aux"]["upstream_s_per_session"],
              "plain_turn_s": S6A["runs"]["scripted"]["turn_ex_compaction_s_mean"]}
    rss_gib = w["rss_kib"]["mean"] / 2**20
    soak = json.loads((evid / a.soak).read_text()) if a.soak else None
    lvl = soak_level(soak) if soak else None
    C = math.floor(lvl["C_effective"]) if lvl else ramp["sustained_concurrency"]
    C_label = (f"soak, effective (Little's law; {soak['n429']} 429s at {soak['inflight_target']} in flight)" if lvl
               else "burst, not sustained (ramp)")
    Cs = sorted({8, 16, 24, 32, C})
    sens = [{"latency_x": lat, "C": c, **projection(inputs, lat=lat, C=c)} for lat in (0.5, 1.0, 1.5) for c in Cs]
    cuts = [("none", {}), ("1: b=100", {"b": 100}), ("2: + L_rob=4", {"b": 100, "L_rob": 4}),
            ("3: + L=24", {"b": 100, "L_rob": 4, "L": 24})]
    rows, led, _ = load(evid, a.write)
    call_s = statistics.mean(u["t_ms"] / 1000 for r in led if r.get("type") == "request"
                             for u in r.get("upstream", []) if u.get("ok"))
    q_req, ri = requests(rows, led, inputs)
    board_calls = {f"L=48 {n}": round(projection(ri, C=1, **kw)["board"]["lane_work_h"] * 3600) for n, kw in cuts[:3:2]}
    q = quota(evid / a.quota, w["upstream_attempts"], soak, board_calls)
    rate = lvl["ok_per_min_send_window"] if lvl else None
    q["board_requests_per_min_over_24h"] = {k: round(v / 1440, 1) for k, v in board_calls.items()}
    q["soak_ok_per_min"] = rate
    soak_s = {k: v for k, v in soak.items() if k != "calls"} if soak else None
    (out / "measurements.json").write_text(json.dumps({"runs": {"write": w}, "ramp": ramp_s, "soak": soak_s,
                                                       "soak_level": lvl, "compare": compare(w), "quota": q}, indent=1))
    c_eff = {label: {"r7b_mean_call_s": round(rs / 60 * call_s, 1), **({"soak_mean_call_s": round(
        rs / 60 * lvl["mean_ok_call_s"], 1)} if lvl else {})} for label, rs in RATES.items()}
    (out / "projection.json").write_text(json.dumps({"requests_per_unit": q_req, "request_rates_per_min": RATES,
                                                     "C_eff_at_rate": c_eff, "mean_request_s": round(call_s, 2),
        "inputs_s": inputs, "C_measured": C, "C_label": C_label, "C_burst": ramp["sustained_concurrency"],
        "C_measured_is_ramp_ceiling": not lvl and ramp["binding_limit"].startswith("none"), "quota": q,
        "sensitivity": sens, "cuts_at_C_measured": [{"cut": n, **projection(inputs, C=C, **kw)} for n, kw in cuts],
        "rss_gib": round(rss_gib, 3), "rss_peak_gib": round(w["rss_peak_kib"] / 2**20, 3),
        "grid": rate_grid(grid(inputs, rss_gib, Cs=Cs), ri)}, indent=1))
    print(json.dumps({"inputs_s": inputs, "C": C, "C_label": C_label, "at_C": projection(inputs, C=C), "quota": q},
                     indent=1))


if __name__ == "__main__":
    main()
