"""Aggregate S6a measurements and compute the PREREG-v0.1 §11 24-hour projection.

    python3.14 analyse.py --evidence <dir> --scripted <run> --write <run> --overhead <run> \
        [--parallel <runA>,<runB>] [--probes <run>] [--compare <run>] --out results/

Reads each run's timings.csv and ledger; writes measurements.json and projection.json (small
aggregates only). Every number carries its sample size.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import statistics as st
from pathlib import Path

import life as life_mod

H24 = 24 * 3600.0


def stats(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"n": 0}
    q = lambda p: xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]
    return {"n": len(xs), "mean": round(st.mean(xs), 3), "p50": round(q(0.5), 3), "p90": round(q(0.9), 3),
            "min": round(xs[0], 3), "max": round(xs[-1], 3)}


def load(evid: Path, run: str) -> tuple[list[dict], list[dict], dict]:
    d = evid / run
    rows = list(csv.DictReader(open(d / "timings.csv")))
    led = [json.loads(x) for x in open(d / "ledger" / "ledger.jsonl")]
    return rows, led, json.loads((d / "summary.json").read_text())


def sec(rows, what, phase="life"):
    return [int(r["t_ms"]) / 1000 for r in rows if r["what"] == what and r["phase"] == phase]


def run_measures(rows, led, summ) -> dict:
    reqs = [r for r in led if r.get("type") == "request"]
    ups = [u for r in reqs for u in r.get("upstream", [])]
    by = lambda kind: [u for u in ups if u["kind"] == kind]
    ok = lambda us: [u for u in us if u.get("ok")]
    tok = lambda us, k: stats([(u.get("usage") or {}).get(k) for u in ok(us)])
    turns = [r for r in reqs if r.get("role") == "replay_main" and r.get("subrole") == "cursor"]
    per_turn_calls = [sum(1 for u in r["upstream"] if u["kind"] == "write_turn") for r in turns]
    sessions = sorted({r["session"] for r in rows if r["phase"] == "life"}, key=int)
    fixed = []
    for s in sessions:
        rs = [r for r in rows if r["phase"] == "life" and r["session"] == s]
        tot = sum(int(r["t_ms"]) for r in rs if r["what"] == "session_total")
        fixed.append((tot - sum(int(r["t_ms"]) for r in rs if r["what"] == "turn")) / 1000)
    # Compaction runs inside a turn: attribute each summariser call to the life turn whose window holds it
    windows = [(float(r["t_wall"]), float(r["t_wall"]) + int(r["t_ms"]) / 1000) for r in rows
               if r["what"] == "turn" and r["phase"] == "life" and r.get("t_wall")]
    comp = [(r["t"], u["t_ms"] / 1000) for r in reqs if r.get("role") == "summariser" for u in r["upstream"]]
    comp_in_turn = sum(d for t, d in comp if any(a <= t <= b for a, b in windows))
    # A paused upstream (marker glm=true) is waiting, not work: take each pause out of its turn
    pauses = [(r["t"], u.get("glm_wait_s", 0)) for r in reqs for u in r.get("upstream", []) if u.get("glm_wait_s")]
    paused = lambda a, b: sum(w for t, w in pauses if a <= t <= b)
    life_turns = [int(r["t_ms"]) / 1000 - (paused(float(r["t_wall"]), float(r["t_wall"]) + int(r["t_ms"]) / 1000)
                                           if r.get("t_wall") else 0)
                  for r in rows if r["what"] == "turn" and r["phase"] == "life"]
    probe_turns = [r for r in reqs if r.get("role") == "probe_main" and r.get("subrole") == "cursor"]
    n_sess, roles = max(1, len({(r["phase"], r["session"]) for r in rows})), {}
    for r in reqs:
        k = f"{r.get('role')}/{r.get('subrole')}"
        roles[k] = roles.get(k, 0) + 1
    return {
        "roles": roles, "unknown": sum(1 for r in reqs if r.get("role") == "unknown"),
        "egress_records": sum(1 for r in led if r.get("type") == "egress"),
        "egress_non_loopback_sockets": summ.get("egress_non_loopback", []), "egress_samples": summ.get("egress_samples"),
        "session_total_s": stats(sec(rows, "session_total")), "session_fixed_s": stats(fixed),
        "spawn_import_s": stats(sec(rows, "spawn_import")), "open_s": stats(sec(rows, "open")),
        "close_s": stats(sec(rows, "close")), "drain_s": stats(sec(rows, "drain")),
        "turn_s": stats(life_turns), "restart_s": stats(sec(rows, "restart")),
        "glm_pauses": {"n": len(pauses), "s": round(sum(w for _, w in pauses), 1)},
        "compaction_in_turns": {"calls": len(comp), "in_turn_windows": sum(1 for t, _ in comp if any(
            a <= t <= b for a, b in windows)), "s": round(comp_in_turn, 1), "windows": len(windows)},
        # a run without turn windows (no t_wall) counts every summariser call as inside a turn
        "turn_ex_compaction_s_mean": (round((sum(life_turns) - (comp_in_turn if windows else sum(d for _, d in comp)))
                                            / len(life_turns), 3) if life_turns else None),
        "long_sessions": len({r["session"] for r in rows if r["what"] == "turn" and int(r["turn"]) > 5}),
        "write_turn": {"turns": len(turns), "calls_per_turn": stats(per_turn_calls),
                       "latency_s": stats([u["t_ms"] / 1000 for u in ok(by("write_turn"))]),
                       "refused": sum(1 for u in by("write_turn") if not u.get("ok")),
                       "prompt_tokens": tok(by("write_turn"), "prompt_tokens"),
                       "completion_tokens": tok(by("write_turn"), "completion_tokens"),
                       "memory_tool_calls": sum(r.get("write_calls", 0) for r in turns),
                       "readback_ok": sum(1 for r in turns if r.get("write_turn_readback")),
                       "upstream_s_per_turn": stats([sum(u["t_ms"] for u in r["upstream"] if u["kind"] == "write_turn")
                                                     / 1000 for r in turns])},
        "summariser": {"calls": len(by("summariser")), "latency_s": stats([u["t_ms"] / 1000 for u in ok(by("summariser"))]),
                       "prompt_tokens": tok(by("summariser"), "prompt_tokens"),
                       "completion_tokens": tok(by("summariser"), "completion_tokens")},
        "aux": {"calls": len(by("aux")), "latency_s": stats([u["t_ms"] / 1000 for u in ok(by("aux"))]),
                "upstream_s_per_session": round(sum(u["t_ms"] for u in by("aux")) / 1000 / n_sess, 3)},
        "rss_kib": stats([w["mean"] for w in summ.get("worker_rss_kib", [])]),
        "write_tool_results": sum(1 for r in reqs if r.get("role") == "write_turn" and r.get("subrole") == "tool_results"),
        "param_rejections": (summ.get("director") or {}).get("param_rejections", []),
        "dropped_keys": sorted({k for u in ups for k in u.get("dropped_keys", [])}),
        "probe": {"turn_s": stats(sec(rows, "turn", "probe")), "calls": len(by("probe")),
                  "upstream_s_per_turn": round(sum(u["t_ms"] for u in by("probe")) / 1000 / len(probe_turns), 3)
                  if probe_turns else None,
                  "latency_s": stats([u["t_ms"] / 1000 for u in ok(by("probe"))]),
                  "fixed_s": stats([a + b for a, b in zip(sec(rows, "spawn_import", "probe"), sec(rows, "open", "probe"))])},
        "overhead": [{"chars": r["overhead_chars"], "prompt_tokens": [(u.get("usage") or {}).get("prompt_tokens")
                                                                       for u in r["upstream"] if u["kind"] == "overhead_measure"]}
                     for r in reqs if r.get("overhead_chars")],
        "marker_exits": sorted({r["marker_exit"] for r in rows}), "glm_flags": sorted({r["glm"] for r in rows}),
        "load1": stats([float(r["load1"]) for r in rows]),
    }


CADENCES = ("every turn", "every 2nd turn", "once per session + before compaction")  # hypothetical options


def projection(m: dict, lat: float = 1.0, C: float = 8, b: int = 150, L: int = 48, L_rob: int = 8,
               f: float = 0.5, ctrl: float = 1.0, delta_w: int = 1, S: int = 200, turns: int = 5,
               sprint_share: float = 0.2, comp_per_sprint: float | None = None, cadence: str = CADENCES[0]) -> dict:
    """PREREG-v0.1 §11, with the assumptions named in REPORT.md (A1-A14). Seconds unless noted.

    Each term is computed twice: as job wall time (every second of a job holds a lane slot; the
    conservative reading) and as lane time (only the seconds spent on the model upstream, aux included)."""
    cps = m["comp_per_sprint"] if comp_per_sprint is None else comp_per_sprint
    u_turn = m["upstream_turn_s"]
    t_write = m["turn_ex_comp_s"] - u_turn + lat * u_turn  # scale only the upstream share
    t_plain = m["plain_turn_s"]  # a turn with no write turn: the scripted run's turn, compaction removed
    t_comp = lat * m["summariser_s"]
    n_comp = sprint_share * S * cps
    n_write = {CADENCES[0]: S * turns, CADENCES[1]: S * math.ceil(turns / 2), CADENCES[2]: S + n_comp}[cadence]
    e_probe = m["probe_fixed_s"] + m["probe_turn_s"] - m["probe_upstream_s"] + lat * m["probe_upstream_s"]
    R = S * m["session_fixed_s"] + n_write * t_write + (S * turns - n_write) * t_plain + n_comp * t_comp
    P = b * e_probe * (1 + ctrl)
    R_up = n_write * lat * u_turn + n_comp * t_comp + S * lat * m["aux_per_session_s"]
    P_up = b * lat * (m["probe_upstream_s"] + m["aux_per_session_s"]) * (1 + ctrl)  # a probe episode is a session
    L_keep = max(6, math.ceil(L / 4))
    k, L_curve = 3, min(L_rob, L_keep)

    def board(R, P):  # R_cap = R (A6)
        return L * (R * (1 + f) + 2 * P) + L_keep * (R * (1 + f) + 2 * P)

    def rob(R, P):  # R_B = R, P_B = P (A9); r_c = 0.15 R, p_c = P/4, P_W = 0.1 P, P_K = 0.2 P (A8)
        r_c, p_c, P_W, P_K = 0.15 * R, P / 4, 0.1 * P, 0.2 * P
        return (L_rob * (3 * 2 * k * (r_c + p_c) + R * (1 + f) + 2 * P + delta_w * (R * (1 + f) + 2 * P_W) + 0.2 * P)
                + L_curve * 2 * (R * (1 + f) + 2 * P_K))

    cp = R + e_probe  # a life's B0 write-turn chain, then the last checkpoint's probe episode (A10)
    out = {"R_h": R / 3600, "P_h": P / 3600, "R_lane_h": R_up / 3600, "P_lane_h": P_up / 3600,
           "critical_path_h": cp / 3600, "compactions_per_life": n_comp, "write_turns_per_life": n_write}
    for name, fn in (("board", board), ("robustness", rob)):
        W, W_up = fn(R, P), fn(R_up, P_up)
        wall, wall_up = max(cp, W / C), max(cp, W_up / C)
        out[name] = {"work_h": W / 3600, "work_over_C_h": W / C / 3600, "wall_h": wall / 3600,
                     "fits_24h": wall <= H24, "C_needed": (math.ceil(W / H24) if cp < H24 else None),
                     "lane_work_h": W_up / 3600, "lane_work_over_C_h": W_up / C / 3600, "lane_wall_h": wall_up / 3600,
                     "lane_fits_24h": wall_up <= H24, "lane_C_needed": (math.ceil(W_up / H24) if cp < H24 else None),
                     "J_for_C": math.ceil(C * W / W_up)}  # lane reading: concurrent jobs keeping C lane slots busy
    return out


def grid(inputs: dict, rss_gib: float) -> list[dict]:
    """Board size x §11 cuts 1-2 x lane concurrency x latency x write cadence, both readings."""
    rows = []
    for L, (cut, kw), C, lat, cad in itertools.product((24, 32, 48), (("none", {}), ("cuts 1-2", {"b": 100, "L_rob": 4})),
                                                     (8, 16, 24), (0.5, 1.0, 1.5), CADENCES):
        pr = projection(inputs, lat=lat, C=C, L=L, cadence=cad, **kw)
        rows.append({"L": L, "cuts": cut, "C": C, "latency_x": lat, "cadence": cad, "cp_h": round(pr["critical_path_h"], 2)}
                    | {run: {"job_h": round(q["wall_h"], 1), "job_fits": q["fits_24h"], "lane_h": round(q["lane_wall_h"], 1),
                             "lane_fits": q["lane_fits_24h"], "J": q["J_for_C"], "J_gib": round(q["J_for_C"] * rss_gib, 1)}
                       for run, q in ((r, pr[r]) for r in ("board", "robustness"))})
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--evidence", required=True)
    p.add_argument("--scripted", required=True)
    p.add_argument("--write", required=True)
    p.add_argument("--overhead", required=True)
    p.add_argument("--parallel", default="")
    p.add_argument("--probes", default="", help="take the probe measures from this run instead of --write")
    p.add_argument("--compare", default="", help="an earlier write run to report beside --write")
    p.add_argument("--ramp", default="ramp/ramp.json")
    p.add_argument("--out", default="results")
    a = p.parse_args()
    evid, out = Path(a.evidence), Path(a.out)
    out.mkdir(exist_ok=True)
    runs = {k: run_measures(*load(evid, getattr(a, k))) for k in ("scripted", "write", "overhead")}
    if a.compare:
        runs["compare"] = run_measures(*load(evid, a.compare)) | {"run": a.compare}
    par = {}
    if a.parallel:
        for r in a.parallel.split(","):
            par[r] = run_measures(*load(evid, r))
    ramp = json.loads((evid / a.ramp).read_text())
    ramp_s = {k: v for k, v in ramp.items() if k != "levels"}
    ramp_s["levels"] = [{k: v for k, v in lv.items() if k != "calls"} for lv in ramp["levels"]]
    if a.probes:
        runs["probes"] = run_measures(*load(evid, a.probes))
        runs["write"]["probe_from"] = a.probes
        runs["write"]["probe"] = runs["probes"]["probe"]
    sc = runs["scripted"]
    for r, pm in par.items():  # parallel roots: the same scripted life, two at once, against the single run
        pm["vs_single"] = {k: round(pm[k]["mean"] / sc[k]["mean"], 3) for k in ("session_total_s", "turn_s", "open_s")}
        pm["vs_single"]["turn_p50"] = round(pm["turn_s"]["p50"] / sc["turn_s"]["p50"], 3)
    w = runs["write"]
    inputs = {"turn_ex_comp_s": w["turn_ex_compaction_s_mean"],
              "upstream_turn_s": w["write_turn"]["upstream_s_per_turn"]["mean"],
              "summariser_s": w["summariser"]["latency_s"].get("mean", 0.0), "session_fixed_s": w["session_fixed_s"]["mean"],
              "comp_per_sprint": w["summariser"]["calls"] / max(1, w["long_sessions"]),
              "probe_turn_s": w["probe"]["turn_s"]["mean"], "probe_upstream_s": w["probe"]["upstream_s_per_turn"],
              "probe_fixed_s": w["probe"]["fixed_s"]["mean"], "aux_per_session_s": w["aux"]["upstream_s_per_session"],
              "plain_turn_s": sc["turn_ex_compaction_s_mean"]}
    rss_gib = max([r["rss_kib"]["mean"] for r in runs.values() if r["rss_kib"]["n"]] or [0]) / 2**20  # largest run mean
    C_meas = ramp["sustained_concurrency"]
    sens = [{"latency_x": lat, "C": C, **projection(inputs, lat=lat, C=C)}
            for lat in (0.5, 1.0, 1.5) for C in sorted({8, 16, 24, 32, C_meas})]
    cuts = [("none", {}), ("1: b=100", {"b": 100}), ("2: + L_rob=4", {"b": 100, "L_rob": 4}),
            ("3: + L=24", {"b": 100, "L_rob": 4, "L": 24})]
    cut_rows = [{"cut": n, **projection(inputs, C=C_meas, **kw)} for n, kw in cuts]
    alt = [{"variant": n, **projection(inputs, C=C_meas, **kw)} for n, kw in (
        ("one compaction per sprint", {"comp_per_sprint": 1}), ("no resume-only controls", {"ctrl": 0.0}),
        ("f = 1", {"f": 1.0}), ("delta_W = 0", {"delta_w": 0}))]
    life = json.loads(Path(life_mod.__file__).with_name("micro_life.json").read_text())
    (out / "measurements.json").write_text(json.dumps({"runs": runs, "parallel": par, "ramp": ramp_s,
                                                       "bundles": life_mod.bundles_hostable(life)}, indent=1))
    (out / "projection.json").write_text(json.dumps({"inputs_s": inputs, "C_measured": C_meas, "sensitivity": sens,
                                                     "cuts_at_C_measured": cut_rows, "assumption_variants_at_C_measured": alt,
                                                     "rss_gib": round(rss_gib, 3), "grid": grid(inputs, rss_gib)}, indent=1))
    print(json.dumps({"inputs_s": inputs, "C": C_meas, "at_C": projection(inputs, C=C_meas)}, indent=1))


if __name__ == "__main__":
    main()
