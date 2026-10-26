"""Spike S2 checker for one Hermes run: prompt dates, stored timestamps, file times, SQL 'now'.

Reads run.json and ledger.jsonl from --run-dir and the Hermes home, and writes an aggregate
JSON (counts only, no content) to --out. state.db is copied to a scratch dir before it is
read, so the home is never opened for writing.
"""

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
import tsscan

STARTED = re.compile(r"Conversation started: (\w+), (\w+) (\d{2}), (\d{4})")
TEXT_SUFFIXES = {".json", ".jsonl", ".md", ".yaml", ".yml", ".log", ".txt", ".toml", ".lock", ""}
SQL_NOW = re.compile(r"CURRENT_(?:TIMESTAMP|DATE|TIME)|'now'|unixepoch\(\s*\)", re.IGNORECASE)
MAX_FILE = 5 * 1024 * 1024


def session_of(win_run, wall):
    for s in win_run["sessions"]:
        # strict bounds: the driver leaves a 1 s gap between sessions, so windows never overlap
        if s["wall_start"] - 0.5 <= wall <= s["wall_end"] + 0.5:
            return s["index"]
    return None


def wall_date_strings(run):
    out = set()
    for s in run["sessions"]:
        for t in (s["wall_start"], s["wall_end"]):
            d = datetime.fromtimestamp(t, timezone.utc)
            out |= {d.strftime("%Y-%m-%d"), d.strftime("%B %d, %Y"), d.strftime("%b %d, %Y")}
    return out


def check_prompts(run, ledger):
    sessions = {s["index"]: s for s in run["sessions"]}
    wall_strings = wall_date_strings(run)
    out = {"requests": 0, "main_requests": 0, "per_session": {}}
    for line in ledger.read_text().splitlines():
        r = json.loads(line)
        body = r.get("body") or {}
        if not r["path"].endswith("/chat/completions"):
            continue
        out["requests"] += 1
        idx = session_of(run, r["wall_received"])
        ps = out["per_session"].setdefault(str(idx), {"started_lines": [], "expected_day": None,
                                                     "wall_date_hits_by_role": {}, "requests": 0})
        ps["requests"] += 1
        if idx in sessions:
            ps["expected_day"] = datetime.fromtimestamp(sessions[idx]["sim_start"], timezone.utc).strftime("%A, %B %d, %Y")
        for m in body.get("messages") or []:
            c = m.get("content")
            c = c if isinstance(c, str) else json.dumps(c)
            for w in wall_strings:
                if w in c:
                    ps["wall_date_hits_by_role"][m["role"]] = ps["wall_date_hits_by_role"].get(m["role"], 0) + c.count(w)
            if m.get("role") == "system":
                for sm in STARTED.finditer(c):
                    line_ = f"{sm.group(1)}, {sm.group(2)} {sm.group(3)}, {sm.group(4)}"
                    if line_ not in ps["started_lines"]:
                        ps["started_lines"].append(line_)
        if body.get("tools"):
            out["main_requests"] += 1
    for ps in out["per_session"].values():
        ps["prompt_date_matches_sim"] = ps["started_lines"] == [ps["expected_day"]] if ps["started_lines"] else None
    return out


def scan_db(path, win):
    tmp = Path(tempfile.mkdtemp(prefix="s2db-"))
    try:
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(path) + suffix)
            if src.exists():
                shutil.copy2(src, tmp / (path.name + suffix))
        con = sqlite3.connect(tmp / path.name)
        tables = con.execute("SELECT name, type, sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
        now_ddl = [{"object": n, "type": t} for n, t, sql in tables if SQL_NOW.search(sql or "")]
        cols = {}
        shadow = {n for n, t, _ in tables if t == "table" and any(
            n.endswith(s) for s in ("_data", "_idx", "_content", "_docsize", "_config", "_segments", "_segdir", "_stat"))}
        for name, typ, sql in tables:
            if typ != "table" or name in shadow or "VIRTUAL TABLE" in (sql or "").upper():
                continue
            try:
                cur = con.execute(f'SELECT * FROM "{name}"')
            except sqlite3.Error:
                continue
            names = [d[0] for d in cur.description]
            for row in cur:
                for col, v in zip(names, row):
                    counts = {}
                    tsscan.classify_value(v, win, counts)
                    if counts:
                        agg = cols.setdefault(f"{name}.{col}", {})
                        for k, n in counts.items():
                            agg[k] = agg.get(k, 0) + n
        con.close()
        return {"columns": cols, "now_in_schema": now_ddl}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def scan_files(home, win):
    files, mtimes, total = {}, {}, {}
    for root, dirs, names in os.walk(home):
        for n in names:
            p = Path(root) / n
            rel = str(p.relative_to(home))
            try:
                st = p.lstat()
            except OSError:
                continue
            c = win.classify(st.st_mtime)
            mtimes[c] = mtimes.get(c, 0) + 1
            if ".db" in n or p.suffix not in TEXT_SUFFIXES or st.st_size > MAX_FILE or p.is_symlink():
                continue
            try:
                text = p.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            counts = {}
            if p.suffix == ".json":
                try:
                    tsscan.classify_json(json.loads(text), win, counts)
                except ValueError:
                    tsscan.classify_text(text, win, counts)
            elif p.suffix == ".jsonl":
                for ln in text.splitlines():
                    try:
                        tsscan.classify_json(json.loads(ln), win, counts)
                    except ValueError:
                        tsscan.classify_text(ln, win, counts)
            else:
                tsscan.classify_text(text, win, counts)
            for k, v in counts.items():
                total[k] = total.get(k, 0) + v
            if any(k != "other" for k in counts):
                files[rel] = {k: v for k, v in counts.items() if k != "other"}
    return {"files_with_run_timestamps": files, "totals": total, "file_mtimes": mtimes}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--home", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    run_dir, home = Path(a.run_dir), Path(a.home)
    run = json.loads((run_dir / "run.json").read_text())
    win = tsscan.Windows(run)
    dbs = {}
    for p in sorted(home.rglob("*.db")):
        dbs[str(p.relative_to(home))] = scan_db(p, win)
    result = {"run": {k: run[k] for k in ("shim", "passthrough", "t0", "gap_days") if k in run},
              "sessions": [{k: s[k] for k in ("index", "exit", "session_id")} for s in run["sessions"]],
              "prompts": check_prompts(run, run_dir / "ledger.jsonl"),
              "databases": dbs, "files": scan_files(home, win)}
    Path(a.out).write_text(json.dumps(result, indent=2, sort_keys=True))
    print(json.dumps(result["prompts"], indent=1))


if __name__ == "__main__":
    main()
