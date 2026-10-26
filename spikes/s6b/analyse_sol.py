"""Aggregate S6b measurements and project PREREG-v0.1 §11 at the Sol lane's measured concurrency.

    python3.14 analyse_sol.py --evidence <dir> --write r7-write --ramp ramp/ramp.json --out results/

S6a's measures, formulas and grid (spikes/s6a/analyse.py), unchanged. The Responses wire reports input and
output tokens, which are mapped onto S6a's prompt and completion fields. A turn with no write turn makes no
model call, so its harness-only time is S6a's scripted measure (spikes/s6a/results/measurements.json).
Writes measurements.json and projection.json (small aggregates only).
"""

from __future__ import annotations

import argparse
import json
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
    return m


def compare(r7: dict) -> list[dict]:
    """r7 (Sol) against S6a's r6 (GLM, parameters forwarded) and r3 (GLM, parameters stripped)."""
    out = []
    for name, m in (("r7 Sol", r7), ("r6 GLM forwarded", S6A["runs"]["write"]), ("r3 GLM stripped", S6A["runs"]["compare"])):
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
    C = ramp["sustained_concurrency"]
    Cs = sorted({8, 16, 24, 32, C})
    sens = [{"latency_x": lat, "C": c, **projection(inputs, lat=lat, C=c)} for lat in (0.5, 1.0, 1.5) for c in Cs]
    cuts = [("none", {}), ("1: b=100", {"b": 100}), ("2: + L_rob=4", {"b": 100, "L_rob": 4}),
            ("3: + L=24", {"b": 100, "L_rob": 4, "L": 24})]
    (out / "measurements.json").write_text(json.dumps({"runs": {"write": w}, "ramp": ramp_s, "compare": compare(w)},
                                                      indent=1))
    (out / "projection.json").write_text(json.dumps({
        "inputs_s": inputs, "C_measured": C, "C_measured_is_ramp_ceiling": ramp["binding_limit"].startswith("none"),
        "sensitivity": sens, "cuts_at_C_measured": [{"cut": n, **projection(inputs, C=C, **kw)} for n, kw in cuts],
        "rss_gib": round(rss_gib, 3), "rss_peak_gib": round(w["rss_peak_kib"] / 2**20, 3),
        "grid": grid(inputs, rss_gib, Cs=Cs)}, indent=1))
    print(json.dumps({"inputs_s": inputs, "C": C, "at_C": projection(inputs, C=C)}, indent=1))


if __name__ == "__main__":
    main()
