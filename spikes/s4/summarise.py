"""Spike S4 summary and the model-B (C-2) cost table.

Reads the run record and the director ledger (neither holds harness text, model text or a header
value) and writes results/summary.json; computes each swap-model candidate's cost per board from
S6a's measured token counts per life, scaled with the PREREG-v0.3 §11 board formula, and writes
results/model_b.json.

    python3 summarise.py --evidence <dir with run.json and director-ledger.jsonl>
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
S6A = HERE.parent / "s6a" / "results"
# Public list prices, USD per 1M tokens (cache-hit input, cache-miss input, output), read 2026-10-26.
PRICES = {
    "glm-5.3 (z.ai coding plan, subscription)": {"family": "Zhipu", "hit": 0.0, "miss": 0.0, "out": 0.0,
                                                 "source": "subscription: $0 marginal"},
    "deepseek-v4-pro, peak": {"family": "DeepSeek", "hit": 0.044, "miss": 1.32, "out": 3.96,
                              "source": "https://api-docs.deepseek.com/quick_start/pricing"},
    "deepseek-v4-pro, off-peak": {"family": "DeepSeek", "hit": 0.022, "miss": 0.66, "out": 1.98,
                                  "source": "https://api-docs.deepseek.com/quick_start/pricing"},
    "MiniMax-M3, standard, <= 512K input": {"family": "MiniMax", "hit": 0.06, "miss": 0.30, "out": 1.20,
                                            "source": "https://platform.minimax.io/docs/guides/pricing-paygo"},
}
BOARD = {"n_L": 48, "n_keep": 12, "f": 0.5, "b": 150, "sessions": 200, "turns_per_session": 5,
         "compactions_per_life": 80, "probe_calls_per_turn": 2.25, "resume_controls_double_P": True,
         "swap_share": 0.5, "cache_hit_share": 0.8, "n_rob": 8, "P_W_over_P": 0.1, "full_window_prompt": 32000}


def summary(ev: Path) -> dict:
    run = json.loads((ev / "run.json").read_text())
    led = [json.loads(x) for x in (ev / "director-ledger.jsonl").read_text().splitlines()]
    steps = []
    for s in run["steps"]:
        recs = [r for r in led if r["run"] == s["step"]]
        sys_counts = Counter(e.get("subtype") for e in s["system_events"])
        steps.append({k: s[k] for k in ("step", "mode", "marker_exit", "exit", "wall_s", "expected_tool", "check",
                                        "check_ok", "expected_tool_ok", "valid", "session", "non_loopback_endpoints",
                                        "context_window", "compact_boundaries", "mcp_servers", "num_turns")}
                     | {"tool_calls": s["tool_calls"], "fork_has_new_session_id": s.get("fork_has_new_session_id"),
                        "system_event_counts": dict(sys_counts),
                        "api_retry": [e for e in s["system_events"] if e.get("subtype") == "api_retry"],
                        "requests": [{k: r.get(k) for k in ("seq", "method", "path", "status", "stream", "n_messages",
                                                            "n_tools", "usage", "stop_reason", "tool_use", "stripped",
                                                            "t_ms", "injected_429")}
                                     | {"upstream_status": [u["status"] for u in r["upstream"]],
                                        "role": "compaction" if s["step"] == "compact" else "main_turn"}
                                     for r in recs]})
    inj = next(r for r in led if r.get("injected_429"))
    nxt = next(r for r in led if r["t"] > inj["t"])
    up = [u for r in led for u in r["upstream"]]
    return {"claude_version": run["claude_version"], "upstream_model": run["model"], "harness_alias": run["alias"],
            "steps": steps, "valid_steps": sum(s["valid"] for s in steps), "n_steps": len(steps),
            "requests": len(led), "upstream_calls": sum(u["status"] != 0 for u in up),
            "statuses": dict(Counter(r["status"] for r in led)), "paths": dict(Counter(r["path"] for r in led)),
            "credential_classes": dict(Counter(r["credential"] for r in led)),
            "dropped_header_names": sorted({h for r in led for h in r["dropped_header_names"]}),
            "body_keys": sorted({k for r in led for k in r.get("body_keys", [])}),
            "query_keys": sorted({k for r in led for k in r["query_keys"]}),
            "stripped_fields": sorted({k for r in led for k in r.get("stripped") or []}),
            "served_models": sorted({r.get("served_model") for r in led if r.get("served_model")}),
            "non_loopback_endpoints": sum(s["non_loopback_endpoints"] for s in steps),
            "injected_429": {"step": inj["run"], "next_request_after_s": round(nxt["t"] - inj["t"], 2),
                             "next_status": nxt["status"]}}


def model_b() -> dict:
    m = json.loads((S6A / "measurements.json").read_text())["runs"]["write"]
    proj = json.loads((S6A / "projection.json").read_text())
    B = BOARD
    wt_in, wt_out = m["write_turn"]["prompt_tokens"]["mean"], m["write_turn"]["completion_tokens"]["mean"]
    sm_in, sm_out = m["summariser"]["prompt_tokens"]["mean"], m["summariser"]["completion_tokens"]["mean"]

    def life(prompt):  # (input, output) tokens: R per life, P per life (probe calls sized like write turns)
        turns = B["sessions"] * B["turns_per_session"]
        r = (turns * prompt + B["compactions_per_life"] * sm_in, turns * wt_out + B["compactions_per_life"] * sm_out)
        k = B["b"] * B["probe_calls_per_turn"] * (2 if B["resume_controls_double_P"] else 1)
        return r, (k * prompt, k * wt_out)

    def board(prompt):  # Cost_board = n_L [R(1+f) + 2P] + n_keep [R_cap(1+f) + 2P], R_cap = R
        r, p = life(prompt)
        unit = [r[i] * (1 + B["f"]) + 2 * p[i] for i in (0, 1)]
        tot = [(B["n_L"] + B["n_keep"]) * u for u in unit]
        swap = [B["swap_share"] * t for t in tot]
        comparator = [B["n_rob"] * (r[i] * (1 + B["f"]) + 2 * B["P_W_over_P"] * p[i]) for i in (0, 1)]  # δ_W = 1
        return {"board_tokens_in_out": tot, "swap_share_in_out": swap, "comparator_in_out": comparator}

    def usd(tokens, pr):
        tin, tout = tokens
        h = B["cache_hit_share"]
        return round(tin / 1e6 * (h * pr["hit"] + (1 - h) * pr["miss"]) + tout / 1e6 * pr["out"], 1)

    readings = {"micro_life_prompt": board(wt_in), "full_window_prompt": board(B["full_window_prompt"])}
    rows = []
    for name, pr in PRICES.items():
        row = {"candidate": name, "family": pr["family"], "source": pr["source"], "price_read": "2026-10-26",
               "usd_per_1m": {k: pr[k] for k in ("hit", "miss", "out")}}
        for rd, v in readings.items():
            row[rd] = {"swap_share_usd": usd(v["swap_share_in_out"], pr),
                       "study_comparator_usd": 0.0 if pr["family"] == "Zhipu" else usd(v["comparator_in_out"], pr)}
        rows.append(row)
    lane = next(s for s in proj["sensitivity"] if s["latency_x"] == 1 and s["C"] == 8)
    glm_lane_h = B["swap_share"] * lane["board"]["lane_work_h"]
    return {"assumptions": B, "s6a_inputs": {"write_turn_in": wt_in, "write_turn_out": wt_out,
                                             "summariser_in": sm_in, "summariser_out": sm_out},
            "readings": readings, "rows": rows,
            "glm_lane": {"board_lane_h_at_x1": lane["board"]["lane_work_h"], "swap_share_lane_h": glm_lane_h,
                         "wall_h_at_C8": round(glm_lane_h / 8, 1), "C_needed_24h": round(glm_lane_h / 24, 1),
                         "max_swap_share_at_C8": round(24 * 8 / lane["board"]["lane_work_h"], 3)}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", default=str(HERE / "results"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary(Path(a.evidence)), indent=1) + "\n")
    (out / "model_b.json").write_text(json.dumps(model_b(), indent=1) + "\n")


if __name__ == "__main__":
    main()
