"""Spike S2 driver: two Claude Code sessions on simulated time, 3 days apart, against the local stub.

Each session is a fresh ``claude -p`` process with:
  an isolated HOME and CLAUDE_CONFIG_DIR (created fresh; the real configuration is never read),
  a working directory under $TMPDIR, outside the user's home tree: Claude Code also loads
  <ancestor>/.claude/CLAUDE.md for every ancestor of the working directory, so a project dir
  under the home directory would pull in the real user memory file whatever HOME says,
  ANTHROPIC_BASE_URL = the 127.0.0.1 stub and ANTHROPIC_API_KEY = placeholder,
  CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 plus the autoupdater, telemetry and error reporting off,
  and a socket monitor (lsof on the process tree) that records any non-loopback endpoint,
  and the Date shim through NODE_OPTIONS=--require (Node build) or BUN_OPTIONS=--preload (native).

--entry is the command to run: ``node <cli.js>`` for a Node build, or the native executable.
Writes run.json and the stub ledger into --evidence-dir.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUB = HERE.parent / "stub" / "recording_stub.py"
SHIM = HERE.parent / "clockshim" / "clock_shim.cjs"
NICE = ["nice", "-n", "19", "taskpolicy", "-b"]

PROBE = ("date -u +wall_date=%Y-%m-%dT%H:%M:%SZ; "
         "node -e \"console.log('child_node=' + new Date().toISOString())\"; "
         "echo \"child_env node_options=${NODE_OPTIONS:+set} clockfile=${BICENTENNIAL_CLOCK_FILE:+set}\"")
SESSIONS = [
    "Session one. Please note: Ada prefers green tea.\nSTUB_RUN: " + PROBE + "\n",
    "Session two. What does Ada prefer?\nSTUB_RUN: " + PROBE + "\n",
]


def _tree(pid):
    pids, todo = [], [pid]
    while todo:
        p = todo.pop()
        pids.append(p)
        out = subprocess.run(["pgrep", "-P", str(p)], capture_output=True, text=True, check=False).stdout
        todo.extend(int(x) for x in out.split())
    return pids


def monitor(proc, seen, stop):
    # Proxy variables make this build fail to reach even the loopback stub, so instead of a
    # blackhole proxy the driver watches the process tree's sockets for non-loopback endpoints.
    while not stop.is_set() and proc.poll() is None:
        pids = ",".join(str(p) for p in _tree(proc.pid))
        out = subprocess.run(["lsof", "-nP", "-a", "-i", "-p", pids], capture_output=True, text=True, check=False).stdout
        for line in out.splitlines()[1:]:
            for ep in re.findall(r"->(\S+)", line):
                host = ep.rsplit(":", 1)[0].strip("[]")
                if host not in ("127.0.0.1", "::1", "localhost"):
                    seen.add(ep)
        stop.wait(0.3)


def write_clock(path, sim_start):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sim_start": sim_start, "wall_anchor": time.time(), "rate": 1.0}))
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entry", nargs="+", required=True, help="e.g. node <cli.js>, or the native executable")
    ap.add_argument("--root", required=True, help="fresh dir for HOME, config dir and project (must not exist)")
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--t0", type=float, required=True)
    ap.add_argument("--gap-days", type=float, default=3.0)
    ap.add_argument("--preload", choices=["node", "bun", "none"], default="node")
    ap.add_argument("--timeout", type=int, default=240)
    a = ap.parse_args()

    root, ev = Path(a.root), Path(a.evidence_dir)
    if root.exists():
        sys.exit("root already exists: refusing to reuse it")
    home, config = root / "home", root / "config"
    for d in (home, config):
        d.mkdir(parents=True)
    project = Path(tempfile.mkdtemp(prefix="s2-cc-project-"))
    ev.mkdir(parents=True, exist_ok=True)
    ledger, port_file, clock = ev / "ledger.jsonl", ev / "stub.port", root / "clock.json"
    for f in (ledger, port_file):
        f.unlink(missing_ok=True)
    stub = subprocess.Popen(NICE + [sys.executable, "-I", str(STUB), "--ledger", str(ledger), "--port-file", str(port_file)],
                            stdout=subprocess.DEVNULL, stderr=open(ev / "stub.stderr", "w"))
    for _ in range(100):
        if port_file.exists() and port_file.read_text().strip():
            break
        time.sleep(0.1)
    port = int(port_file.read_text())

    keep = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL")
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update({
        "HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "TZ": "UTC",
        "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}", "ANTHROPIC_API_KEY": "placeholder",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
    })
    if a.preload != "none":
        env["BICENTENNIAL_CLOCK_FILE"] = str(clock)
        if a.preload == "node":
            env["NODE_OPTIONS"] = f"--require {SHIM}"
        else:
            env["BUN_OPTIONS"] = f"--preload {SHIM}"

    run = {"preload": a.preload, "t0": a.t0, "gap_days": a.gap_days, "shim": a.preload != "none", "sessions": []}
    try:
        for i, prompt in enumerate(SESSIONS):
            sim_start = a.t0 + i * a.gap_days * 86400
            if a.preload != "none":
                write_clock(clock, sim_start)
            wall0 = time.time()
            proc = subprocess.Popen(NICE + a.entry + ["-p", prompt, "--output-format", "json", "--allowedTools", "Bash"],
                                    cwd=project, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            seen, stop = set(), threading.Event()
            mon = threading.Thread(target=monitor, args=(proc, seen, stop), daemon=True)
            mon.start()
            try:
                out, err = proc.communicate(timeout=a.timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
            stop.set()
            mon.join(timeout=5)
            proc.stdout, proc.stderr = out, err
            wall1 = time.time()
            (ev / f"session{i + 1}.stdout").write_text(proc.stdout)
            (ev / f"session{i + 1}.stderr").write_text(proc.stderr)
            try:
                sid = json.loads(proc.stdout).get("session_id")
            except ValueError:
                sid = None
            dur = wall1 - wall0
            shimmed = a.preload != "none"
            run["sessions"].append({"index": i + 1, "exit": proc.returncode, "wall_start": wall0, "wall_end": wall1,
                                    "sim_start": sim_start if shimmed else wall0,
                                    "sim_end": (sim_start + dur) if shimmed else wall1, "session_id": sid,
                                    "non_loopback_endpoints": len(seen)})
            (ev / f"session{i + 1}.endpoints").write_text("\n".join(sorted(seen)))
            time.sleep(1.0)
    finally:
        stub.terminate()
        stub.wait(timeout=10)
    run["project_dir_name"] = project.name
    (ev / "run.json").write_text(json.dumps(run, indent=2))
    print(json.dumps({"sessions": [(s["index"], s["exit"], s["session_id"]) for s in run["sessions"]]}))


if __name__ == "__main__":
    main()
