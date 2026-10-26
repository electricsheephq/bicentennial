"""Fold the per-run check.json / guards.json files of spike S2 into one aggregate summary.

Usage: python summarise.py <evidence dir> <out.json>
Only counts, dates and booleans are copied; ledgers, bodies and logs stay in the evidence dir.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "common"))
import tsscan

CHILD = re.compile(r"(wall_date|child_py|child_node|code_py)=(\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})?)")


def child_clocks(run_dir):
    """Clock readings that tool children printed back, classified sim/wall (from tool results)."""
    run = json.loads((run_dir / "run.json").read_text())
    win, out = tsscan.Windows(run), {}
    ledger = run_dir / "ledger.jsonl"
    if not ledger.exists():
        return out
    seen = set()
    for line in ledger.read_text().splitlines():
        for kind, stamp in CHILD.findall(line.replace("\\n", " ")):
            if (kind, stamp) in seen:
                continue
            seen.add((kind, stamp))
            counts = {}
            tsscan.classify_text(stamp, win, counts)
            for c in counts:
                key = "sim" if c.startswith("sim") else c
                out.setdefault(kind, {}).setdefault(key, 0)
                out[kind][key] += 1
    return out


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def hermes(run_dir):
    c = json.loads((run_dir / "check.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    db = c["databases"].get("state.db", {})
    out = {
        "shim": c["run"]["shim"], "passthrough": c["run"].get("passthrough", False),
        "sessions": [{"index": s["index"], "exit": s["exit"], "sim_start": iso(s["sim_start"]) if run["shim"] else "wall",
                      "wall_seconds": round(s["wall_end"] - s["wall_start"], 1)} for s in run["sessions"]],
        "prompt": {k: {"conversation_started": v["started_lines"], "expected": v["expected_day"],
                       "match": v["prompt_date_matches_sim"], "requests": v["requests"],
                       "wall_date_strings_by_role": v["wall_date_hits_by_role"]}
                   for k, v in c["prompts"]["per_session"].items()},
        "state_db_columns": {k: v for k, v in db.get("columns", {}).items() if any(x != "other" for x in v)},
        "state_db_now_in_schema": db.get("now_in_schema", []),
        "other_dbs": sorted(k for k in c["databases"] if k != "state.db"),
        "files_with_run_timestamps": c["files"]["files_with_run_timestamps"],
        "file_mtimes": c["files"]["file_mtimes"],
        "tool_child_clocks": child_clocks(run_dir),
    }
    g = run_dir / "guards.json"
    if g.exists():
        out["guard_probe"] = json.loads(g.read_text())
    return out


def claude(run_dir):
    c = json.loads((run_dir / "check.json").read_text())
    run = json.loads((run_dir / "run.json").read_text())
    tc = run_dir / "transcripts.count"
    return {
        "preload": c["run"]["preload"],
        "sessions": [{"index": s["index"], "exit": s["exit"], "non_loopback_endpoints": s.get("non_loopback_endpoints"),
                      "sim_start": iso(s["sim_start"]) if run["shim"] else "wall",
                      "wall_seconds": round(s["wall_end"] - s["wall_start"], 1)} for s in run["sessions"]],
        "requests": c["prompts"]["requests"], "message_requests": c["prompts"]["message_requests"],
        "prompt": {k: {"todays_date": v["today_lines"], "expected": v["expected_day"],
                       "match": v["prompt_date_matches_sim"], "wall_day_strings": v["wall_day_hits"]}
                   for k, v in c["prompts"]["per_session"].items()},
        "context_files_loaded": c["prompts"]["context_files_loaded"],
        "context_files_outside_isolation": c["prompts"]["context_files_outside_isolation"],
        "files_with_run_timestamps": c["files"]["files_with_run_timestamps"],
        "file_mtimes": c["files"]["file_mtimes"],
        "transcripts_after_both_sessions": int(tc.read_text()) if tc.exists() else None,
        "tool_child_clocks": child_clocks(run_dir),
    }


def main():
    ev, out = Path(sys.argv[1]), Path(sys.argv[2])
    summary = {"hermes": {}, "claude_code": {}}
    for d in sorted(ev.glob("hermes-*")):
        if (d / "check.json").exists():
            summary["hermes"][d.name[len("hermes-"):]] = hermes(d)
    for d in sorted(ev.glob("cc-*")):
        if (d / "check.json").exists():
            summary["claude_code"][d.name[len("cc-"):]] = claude(d)
    inv = ev / "hermes-inventory.json"
    if inv.exists():
        i = json.loads(inv.read_text())
        summary["hermes_static_inventory"] = {k: i[k] for k in ("files_scanned", "mixed_clock_files", "mixed_clock_lines",
                                                                "monotonic_lines", "wall_read_lines")}
        summary["hermes_static_inventory"]["mixed_clock_modules"] = sorted(i["mixed_clock"])
        summary["hermes_static_inventory"]["sql_now"] = i["sql_now"]
    out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
