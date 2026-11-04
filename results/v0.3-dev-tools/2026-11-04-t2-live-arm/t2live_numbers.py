"""#391 slice 10: print the live T2 arm's numbers from its own files, for RESULT.md.

Usage: PYTHONPATH=<checkout>/src <venv python 3.12+> -s -P t2live_numbers.py <run dir>  (-I would drop PYTHONPATH)
Reads card.json, units.json, spend.json and receipt.json; recomputes the arm time from units.json with the runner's
own calculate_arm_times and checks it against the stored value. Prints numbers only: no paths, logins or answers.
"""

import json
import statistics
import sys
from pathlib import Path

from bicentennial.runner.arm_time import calculate_arm_times, units_json_inputs

HOUR_MS = 3_600_000


def load(run, name):
    return json.loads((run / name).read_text())


def minutes(ms):
    return f"{ms / 60000:.1f} min"


def main(run):
    card, units, spend, receipt = (load(run, n) for n in ("card.json", "units.json", "spend.json", "receipt.json"))
    stored = units["arm_time"]
    again = calculate_arm_times(*units_json_inputs(units))
    same = {a: (stored["arms"][a]["arm_time_ms"], again["arms"][a]["arm_time_ms"]) for a in again["arms"]}
    print("tier", card["tier"], "system", card.get("system"), "pack_hash", card.get("pack_hash", "")[:12])
    print("slots", units["slots"], "admitted", units.get("admitted_slots"))
    print("wall", minutes(units["end_ms"] - units["start_ms"]), "monotonic", minutes(units["t_end_ms"]))
    for arm, (a, b) in same.items():
        info = stored["arms"][arm]
        print(f"arm {arm}: arm_time {minutes(a)} ({a} ms; recomputed {b} ms, {'equal' if a == b else 'DIFFERENT'});"
              f" replay {minutes(info['replay_ms'])}; outside units {minutes(info['outside_ms'])};"
              f" {len(info['units'])} units; {'within' if a <= HOUR_MS else 'over'} the 1 h target"
              f" ({a / HOUR_MS:.2f} h)")
    print("floor_replay", minutes(stored["floor_replay_ms"]))
    by_arm = {}
    for row in units["units"]:
        by_arm.setdefault(row["arm"], []).append(row)
    for arm, rows in sorted(by_arm.items()):
        spans = sorted(r["t_end_ms"] - r["t_start_ms"] for r in rows)
        print(f"units {arm}: {len(rows)}; span min {minutes(spans[0])}, median {minutes(statistics.median(spans))},"
              f" max {minutes(spans[-1])}; attempts {sum(r.get('attempts', 1) for r in rows)};"
              f" pre_probe {minutes(sum(r.get('pre_probe_ms', 0) for r in rows))}; keep {minutes(sum(r.get('keep_ms', 0) for r in rows))}")
    for arm, rows in sorted(by_arm.items()):
        for r in sorted(rows, key=lambda r: (r["life"], r["branch"])):
            print(f"  {arm} {r['life']} {r['branch']}: span {minutes(r['t_end_ms'] - r['t_start_ms'])};"
                  f" predicted {r['predicted_s']} s; attempts {r['attempts']}; slot {r['slot']};"
                  f" pre_probe {minutes(r['pre_probe_ms'])}; keep {minutes(r['keep_ms'])};"
                  f" start {minutes(r['t_start_ms'])} end {minutes(r['t_end_ms'])}")
    print("card counts", json.dumps(card["counts"], sort_keys=True))
    print("items", len(card["items"]), "not_scored_live", len(card["not_scored_live"]))
    print("spend", json.dumps({k: v for k, v in spend.items() if not isinstance(v, (dict, list))}, sort_keys=True))
    unit_min = {arm: sum(r["t_end_ms"] - r["t_start_ms"] for r in rows) for arm, rows in by_arm.items()}
    print("unit time summed", {a: minutes(v) for a, v in sorted(unit_min.items())}, "total", minutes(sum(unit_min.values())))
    roles = {r["role"]: r["ms"] for r in receipt["runtime_by_role"]}
    total = sum(roles.values())
    print("director request time by role", {k: minutes(v) for k, v in sorted(roles.items())}, "total", minutes(total),
          f"({100 * total / sum(unit_min.values()):.0f}% of the summed unit time)")
    print("tokens by role", json.dumps({r["role"]: [r["input"], r["output"]] for r in receipt["tokens_by_role"]}, sort_keys=True))
    print("latency_ms", json.dumps(receipt["latency_summary"], sort_keys=True))
    print("load average at the run's end (1, 5, 15 min)", [v / 1000 for v in receipt["load_milli"]])
    print("background", json.dumps(receipt["background"], sort_keys=True))
    print("run_status", receipt["run_status"], "turn_wait_s", receipt["turn_wait_s"], "spend_micro_usd", receipt["spend_micro_usd"],
          "store_growth_bytes", receipt["store_growth_bytes"])


if __name__ == "__main__":
    main(Path(sys.argv[1]))
