"""Spike S2 driver: two Hermes sessions on simulated time, 3 days apart, against the local stub.

Session 1 runs at sim t0 and session 2 at t0 + gap. Each session is a fresh ``hermes chat -q``
process. The director writes clock.json before each one; the shim (``--shim-dir`` on
PYTHONPATH) reads it. ``--no-shim`` runs the same script on wall time as a control.

Outbound HTTP(S) is pointed at a closed local port, so nothing but the 127.0.0.1 stub is
reachable. Writes run.json (windows, exit codes) and the stub ledger into --evidence-dir.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STUB = HERE.parent / "stub" / "recording_stub.py"
NICE = ["nice", "-n", "19", "taskpolicy", "-b"]

PROBE = ("date -u +wall_date=%Y-%m-%dT%H:%M:%SZ; "
         "python3 -c \"import datetime as d;print('child_py=' + d.datetime.now(d.timezone.utc).isoformat())\"; "
         "echo \"child_env pythonpath=${PYTHONPATH:+set} clockfile=${BICENTENNIAL_CLOCK_FILE:+set}\"")
CODE = ("import datetime as d, os, time\n"
        "print('code_py=' + d.datetime.now(d.timezone.utc).isoformat())\n"
        "print('code_env clockfile=' + ('set' if os.environ.get('BICENTENNIAL_CLOCK_FILE') else 'unset'))\n")

SESSIONS = [
    "Session one. Please note this for later.\n"
    "STUB_MEMORY: Ada prefers green tea.\n"
    f"STUB_RUN: {PROBE}\n",
    "Session two. What does Ada prefer?\n"
    f"STUB_RUN: {PROBE}\n"
    f"STUB_TOOL: execute_code {json.dumps({'code': CODE})}\n",
]


def write_clock(path, sim_start):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"sim_start": sim_start, "wall_anchor": time.time(), "rate": 1.0}))
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hermes-dir", required=True, help="pinned Hermes checkout with .venv")
    ap.add_argument("--home", required=True, help="fresh HERMES_HOME (created; must not exist)")
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--shim-dir", default=str(HERE.parent / "clockshim"))
    ap.add_argument("--t0", type=float, required=True, help="sim epoch seconds of session 1")
    ap.add_argument("--gap-days", type=float, default=3.0)
    ap.add_argument("--no-shim", action="store_true")
    ap.add_argument("--passthrough", action="store_true",
                    help="add terminal.env_passthrough for the clock variable (reaches execute_code)")
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()

    hermes_dir, home, ev = Path(a.hermes_dir), Path(a.home), Path(a.evidence_dir)
    if home.exists():
        sys.exit(f"home already exists: refusing to reuse it ({home.name})")
    home.mkdir(parents=True)
    ev.mkdir(parents=True, exist_ok=True)
    ledger, port_file, clock = ev / "ledger.jsonl", ev / "stub.port", home.parent / f"{home.name}.clock.json"
    for f in (ledger, port_file):
        f.unlink(missing_ok=True)

    stub = subprocess.Popen(NICE + [sys.executable, "-I", str(STUB), "--ledger", str(ledger), "--port-file", str(port_file)],
                            stdout=subprocess.DEVNULL, stderr=open(ev / "stub.stderr", "w"))
    for _ in range(100):
        if port_file.exists() and port_file.read_text().strip():
            break
        time.sleep(0.1)
    port = int(port_file.read_text())
    (home / "config.yaml").write_text(
        "model:\n  provider: custom\n  default: stub-model\n"
        f"  base_url: http://127.0.0.1:{port}/v1\n  api_key: placeholder\n"
        "timezone: UTC\n"
        + ("terminal:\n  env_passthrough:\n  - BICENTENNIAL_CLOCK_FILE\n" if a.passthrough else ""))

    env = {k: v for k, v in os.environ.items() if not k.startswith(("HERMES_", "OPENAI_", "ANTHROPIC_", "OPENROUTER_"))}
    env.update({"HERMES_HOME": str(home), "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
                "ALL_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1,localhost", "PYTHONDONTWRITEBYTECODE": "1"})
    for k in ("http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        env[k] = env[k.upper()]
    if not a.no_shim:
        env["PYTHONPATH"] = a.shim_dir
        env["BICENTENNIAL_CLOCK_FILE"] = str(clock)
    else:
        env.pop("PYTHONPATH", None)

    run = {"shim": not a.no_shim, "passthrough": a.passthrough, "t0": a.t0, "gap_days": a.gap_days, "sessions": []}
    try:
        for i, prompt in enumerate(SESSIONS):
            sim_start = a.t0 + i * a.gap_days * 86400
            if not a.no_shim:
                write_clock(clock, sim_start)
            wall0 = time.time()
            proc = subprocess.run(NICE + [str(hermes_dir / ".venv" / "bin" / "python"), str(hermes_dir / "hermes"),
                                          "chat", "-Q", "--yolo", "-q", prompt],
                                  cwd=home, env=env, capture_output=True, text=True, check=False, timeout=a.timeout)
            wall1 = time.time()
            (ev / f"session{i + 1}.stdout").write_text(proc.stdout)
            (ev / f"session{i + 1}.stderr").write_text(proc.stderr)
            dur = wall1 - wall0
            run["sessions"].append({
                "index": i + 1, "exit": proc.returncode, "wall_start": wall0, "wall_end": wall1,
                "sim_start": sim_start if not a.no_shim else wall0,
                "sim_end": (sim_start + dur) if not a.no_shim else wall1,
                "session_id": next((ln.split(":", 1)[1].strip() for ln in (proc.stdout + proc.stderr).splitlines()
                                    if ln.startswith("session_id:")), None)})
            time.sleep(1.0)
    finally:
        stub.terminate()
        stub.wait(timeout=10)
    (ev / "run.json").write_text(json.dumps(run, indent=2))
    if clock.exists():
        shutil.copy(clock, ev / "clock.last.json")
    print(json.dumps({"sessions": [(s["index"], s["exit"], s["session_id"]) for s in run["sessions"]]}))


if __name__ == "__main__":
    main()
