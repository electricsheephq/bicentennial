"""Spike S2 checker for one Claude Code run: prompt date, stored timestamps, file times, isolation.

Reads run.json and ledger.jsonl from --run-dir and the run's isolated root (HOME and
CLAUDE_CONFIG_DIR) plus its project dir, and writes aggregate counts (no content) to --out.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import tsscan

TODAY = re.compile(r"Today's date is (?:now )?(\d{4}-\d{2}-\d{2})")
LOADED = re.compile(r"Contents of (\S+?) \(")


def session_of(run, wall):
    for s in run["sessions"]:
        # strict bounds: the driver leaves a 1 s gap between sessions, so windows never overlap
        if s["wall_start"] - 0.5 <= wall <= s["wall_end"] + 0.5:
            return s["index"]
    return None


def check_prompts(run, ledger, allowed_roots):
    out = {"requests": 0, "message_requests": 0, "per_session": {}, "context_files_loaded": 0,
           "context_files_outside_isolation": 0}
    if not ledger.exists():
        return out
    wall_days = {datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")
                 for s in run["sessions"] for t in (s["wall_start"], s["wall_end"])}
    for line in ledger.read_text().splitlines():
        r = json.loads(line)
        out["requests"] += 1
        if not r["path"].split("?")[0].endswith("/messages"):
            continue
        out["message_requests"] += 1
        body = json.dumps(r.get("body") or {})
        idx = session_of(run, r["wall_received"])
        ps = out["per_session"].setdefault(str(idx), {"today_lines": [], "expected_day": None, "wall_day_hits": 0})
        s = next((x for x in run["sessions"] if x["index"] == idx), None)
        if s:
            ps["expected_day"] = datetime.fromtimestamp(s["sim_start"], timezone.utc).strftime("%Y-%m-%d")
        for m in TODAY.finditer(body):
            if m.group(1) not in ps["today_lines"]:
                ps["today_lines"].append(m.group(1))
        ps["wall_day_hits"] += sum(body.count(d) for d in wall_days)
        for m in LOADED.finditer(body):
            out["context_files_loaded"] += 1
            if not any(m.group(1).startswith(str(a)) for a in allowed_roots):
                out["context_files_outside_isolation"] += 1
    for ps in out["per_session"].values():
        ps["prompt_date_matches_sim"] = (ps["today_lines"] == [ps["expected_day"]]) if ps["today_lines"] else None
    return out


def scan_tree(base, win, label, files, mtimes, totals):
    for root, _dirs, names in os.walk(base):
        for n in names:
            p = Path(root) / n
            try:
                st = p.lstat()
            except OSError:
                continue
            c = win.classify(st.st_mtime)
            mtimes[c] = mtimes.get(c, 0) + 1
            if st.st_size > 5 * 1024 * 1024 or p.is_symlink():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            counts = {}
            if p.suffix == ".jsonl":
                for ln in text.splitlines():
                    try:
                        tsscan.classify_json(json.loads(ln), win, counts)
                    except ValueError:
                        tsscan.classify_text(ln, win, counts)
            elif p.suffix == ".json" or n.endswith(".json") or ".json." in n:
                try:
                    tsscan.classify_json(json.loads(text), win, counts)
                except ValueError:
                    tsscan.classify_text(text, win, counts)
            else:
                tsscan.classify_text(text, win, counts)
            for k, v in counts.items():
                totals[k] = totals.get(k, 0) + v
            rel = f"{label}/" + re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "<session>", str(p.relative_to(base)))
            rel = re.sub(r"projects/[^/]+", "projects/<cwd>", rel)
            rel = re.sub(r"\.\d{13}$", ".<ms>", rel)
            if any(k != "other" for k in counts):
                agg = files.setdefault(rel, {})
                for k, v in counts.items():
                    if k != "other":
                        agg[k] = agg.get(k, 0) + v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--project-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run_dir, root, project = Path(a.run_dir), Path(a.root), Path(a.project_dir)
    run = json.loads((run_dir / "run.json").read_text())
    win = tsscan.Windows(run)
    files, mtimes, totals = {}, {}, {}
    scan_tree(root / "config", win, "config", files, mtimes, totals)
    scan_tree(root / "home", win, "home", files, mtimes, totals)
    scan_tree(project, win, "project", files, mtimes, totals)
    allowed = [root, project, project.resolve()]
    result = {"run": {k: run[k] for k in ("preload", "t0", "gap_days", "shim")},
              "sessions": [{k: s.get(k) for k in ("index", "exit", "non_loopback_endpoints")} for s in run["sessions"]],
              "prompts": check_prompts(run, run_dir / "ledger.jsonl", allowed),
              "files": {"files_with_run_timestamps": files, "totals": totals, "file_mtimes": mtimes}}
    Path(a.out).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
