"""Spike S4 driver: Claude Code headless (`claude -p`, stream-json) against the S4 director.

Isolation is S2's recipe: a fresh HOME and CLAUDE_CONFIG_DIR under --root, a project directory under
$TMPDIR (outside the home tree, so no ancestor instruction file is loaded), ANTHROPIC_BASE_URL on the
director at 127.0.0.1, the placeholder key, and non-essential traffic, the autoupdater, telemetry and
error reporting off. The environment is built from a short allow-list, so no other credential is
present. The director, not Claude Code, runs under --upstream-wrapper, which alone supplies the
upstream key. S1's socket monitor (lsof on the process tree) records any non-loopback endpoint.

Steps: five main turns (Bash, Read, Edit, the fixture MCP tool, Bash), one with an injected 429;
then --resume, --resume --fork-session, /compact and a recall turn after it. One Claude Code process
at a time under nice -n 19, each step gated on the busy marker. Bulk goes to --root; the minimized
run record (no harness or model text) goes to --evidence.

    python3 run_s4.py --root <fresh dir> --evidence <dir> --upstream-wrapper <script> --busy-cmd <cmd>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "s2" / "claude"))
from run_claude import monitor

NICE = ["nice", "-n", "19"]
KEEP = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL")
ALIAS = "bicentennial-cc-main"
MCP_TOOL = "mcp__fixture__fixture_lookup"
GAMMA = "G-5582"  # mcp_fixture.TABLE["gamma"]
NOTES0, NOTES1 = "alpha=7\nbeta=11\n", "alpha=7\nbeta=12\n"
# (name, mode, prompt, expected tool, check, inject a 429 on this step's n-th request)
STEPS = [
    ("t1", "new", ("Use the Bash tool to run exactly this command: printf 'alpha=7\\nbeta=11\\n' > notes.txt && "
     "wc -l < notes.txt\nThen reply with the number it printed."), "Bash", ("file", NOTES0), 0),
    ("t2", "continue", ("Use the Read tool to read notes.txt in the current directory, then reply with the value "
     "of beta only."), "Read", ("answer", "11"), 0),
    ("t3", "continue", ("Use the Edit tool to change the line beta=11 to beta=12 in notes.txt. Reply 'done' when "
     "finished."), "Edit", ("file", NOTES1), 1),
    ("t4", "continue", ("Call the fixture_lookup tool from the fixture MCP server with key gamma, then reply with "
     "the value it returned."), MCP_TOOL, ("answer", GAMMA), 0),
    ("t5", "continue", "Use the Bash tool to run: cat notes.txt\nThen reply with the value of beta only.", "Bash",
     ("answer", "12"), 0),
    ("resume", "resume", ("Without using any tools: what value did the fixture lookup return earlier in this "
     "conversation?"), None, ("answer", GAMMA), 0),
    ("fork", "fork", "Without using any tools: what value does beta have now, according to this conversation?",
     None, ("answer", "12"), 0),
    ("compact", "resume", "/compact", None, ("compact", None), 0),
    ("post_compact", "resume", ("Without using any tools: what value did the fixture lookup return for gamma "
     "earlier in this conversation?"), None, ("answer", GAMMA), 0),
]


def gate(cmd: str, log) -> int:
    """The busy marker before each live step: exit 11 waits (60 s re-check); 0 and 10 proceed."""
    while cmd:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
        if r.returncode != 11:
            return r.returncode
        log("marker exit 11; waiting 60 s")
        time.sleep(60)
    return -1


def start_director(a, root: Path, step: str, inject: int, log):
    port_file = root / f"director-{step}.port"
    while True:
        port_file.unlink(missing_ok=True)
        cmd = ["bash", a.upstream_wrapper, *NICE, sys.executable, "-I", str(HERE / "anthropic_director.py"),
               "--port-file", str(port_file), "--ledger", str(a.evidence_path / "director-ledger.jsonl"),
               "--budget-file", str(root / "budget.json"), "--strip-file", str(root / "strip.json"),
               "--stop-file", str(root / "STOP"), "--bodies-dir", str(root / "bodies" / step), "--run", step,
               "--max-calls", str(a.max_calls), "--inject-429", str(inject), "--model", a.model]
        with open(root / f"director-{step}.stderr", "w") as err:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=err)
        for _ in range(200):
            if port_file.exists():
                return proc, int(port_file.read_text())
            if proc.poll() is not None:
                break
            time.sleep(0.1)
        if proc.poll() == 75:  # GLM paused by the release gauntlet: wait and retry, never work around it
            log("upstream paused (75); waiting 60 s")
            time.sleep(60)
            continue
        proc.kill()
        sys.exit(f"director did not start (exit {proc.poll()})")


def events(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            out.append(ev)
    return out


def digest(evs: list[dict]) -> dict:
    """Shapes only: tool calls and their error flags, system event subtypes, compaction, the result."""
    calls, results, sys_ev, compact = {}, {}, [], []
    for ev in evs:
        content = (ev.get("message") or {}).get("content")
        for b in content if isinstance(content, list) else []:
            if b.get("type") == "tool_use":
                calls[b.get("id")] = b.get("name")
            elif b.get("type") == "tool_result":
                results[b.get("tool_use_id")] = bool(b.get("is_error"))
        if ev.get("type") == "system":
            sys_ev.append({k: ev.get(k) for k in ("subtype", "attempt", "max_retries", "retry_delay_ms",
                                                  "error_status", "error") if k in ev})
            if ev.get("subtype") == "compact_boundary":
                cm = ev.get("compact_metadata") or {}
                compact.append({k: cm.get(k) for k in ("trigger", "pre_tokens", "post_tokens", "duration_ms")})
    res = next((e for e in reversed(evs) if e.get("type") == "result"), {})
    return {"tool_calls": [{"name": n, "result_is_error": results.get(i)} for i, n in calls.items()],
            "system_events": sys_ev, "compact_boundaries": compact, "session_id": res.get("session_id"),
            "result_subtype": res.get("subtype"), "result_is_error": res.get("is_error"),
            "num_turns": res.get("num_turns"), "answer": res.get("result") or "",
            "context_window": {m: u.get("contextWindow") for m, u in (res.get("modelUsage") or {}).items()},
            "mcp_servers": next(({s.get("name"): s.get("status") for s in e.get("mcp_servers") or []}
                                 for e in evs if e.get("subtype") == "init"), {})}


def fresh_paths(root: str, evidence: str) -> tuple[Path, Path]:
    """Absolute paths (Claude Code runs in another directory), refusing to reuse a root or an earlier run's
    evidence, whose ledger the director would append to."""
    r, ev = Path(root).resolve(), Path(evidence).resolve()
    if r.exists():
        sys.exit("root already exists: refusing to reuse it")
    if any((ev / f).exists() for f in ("director-ledger.jsonl", "run.json")):
        sys.exit("evidence already holds a run: refusing to combine runs")
    return r, ev


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="fresh scratch dir (must not exist)")
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--upstream-wrapper", required=True, help="runs the director with the upstream environment")
    ap.add_argument("--busy-cmd", default="")
    ap.add_argument("--model", default="glm-5.3")
    ap.add_argument("--max-calls", type=int, default=120)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    root, ev = fresh_paths(a.root, a.evidence)
    home, config, out = root / "home", root / "config", root / "out"
    for d in (home, config, out):
        d.mkdir(parents=True)
    ev.mkdir(parents=True, exist_ok=True)
    a.evidence_path = ev
    project = Path(tempfile.mkdtemp(prefix="s4-cc-project-"))
    mcp_cfg = root / "mcp.json"
    mcp_cfg.write_text(json.dumps({"mcpServers": {"fixture": {
        "command": sys.executable, "args": ["-I", str(HERE / "mcp_fixture.py")]}}}))
    log = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True, check=False).stdout.strip()
    base_env = {k: os.environ[k] for k in KEEP if k in os.environ}
    base_env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "TZ": "UTC",
                     "ANTHROPIC_API_KEY": "placeholder", "ANTHROPIC_MODEL": ALIAS,
                     "ANTHROPIC_DEFAULT_HAIKU_MODEL": ALIAS, "ANTHROPIC_SMALL_FAST_MODEL": ALIAS,
                     "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1", "DISABLE_AUTOUPDATER": "1",
                     "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1", "CLAUDE_CODE_ENABLE_TELEMETRY": "0"})
    run = {"claude_version": version, "model": a.model, "alias": ALIAS, "steps": []}
    sid = None
    for name, mode, prompt, tool, check, inject in STEPS:
        marker = gate(a.busy_cmd, log)
        if (root / "STOP").exists():
            log("stop file present; ending the run")
            break
        director, port = start_director(a, root, name, inject, log)
        env = dict(base_env, ANTHROPIC_BASE_URL=f"http://127.0.0.1:{port}")
        cmd = ["claude", "-p", prompt, "--output-format", "stream-json", "--verbose", "--mcp-config", str(mcp_cfg),
               "--strict-mcp-config", "--allowedTools", f"Bash,Read,Edit,{MCP_TOOL}"]
        cmd += {"new": [], "continue": ["--continue"], "resume": ["--resume", str(sid)],
                "fork": ["--resume", str(sid), "--fork-session"]}[mode]
        t0 = time.time()
        proc = subprocess.Popen(NICE + cmd, cwd=project, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        seen, stop = set(), threading.Event()
        mon = threading.Thread(target=monitor, args=(proc, seen, stop), daemon=True)
        mon.start()
        try:
            so, se = proc.communicate(timeout=a.timeout)
        except subprocess.TimeoutExpired:
            proc.kill()  # our own child, by handle
            so, se = proc.communicate(timeout=15)
        stop.set()
        mon.join(timeout=5)
        director.terminate()
        director.wait(timeout=10)
        (out / f"{name}.stdout").write_text(so)
        (out / f"{name}.stderr").write_text(se)
        (out / f"{name}.endpoints").write_text("\n".join(sorted(seen)))
        d = digest(events(so))
        sid = sid or d["session_id"]
        kind, want = check
        if kind == "file":
            ok = (project / "notes.txt").exists() and (project / "notes.txt").read_text() == want
        elif kind == "answer":
            ok = want in d["answer"]
        else:
            ok = bool(d["compact_boundaries"])
        tool_ok = tool is None or any(c["name"] == tool and c["result_is_error"] is False for c in d["tool_calls"])
        same = d["session_id"] == sid
        step = {"step": name, "mode": mode, "marker_exit": marker, "exit": proc.returncode,
                "wall_s": round(time.time() - t0, 1), "expected_tool": tool, "check": kind, "check_ok": ok,
                "expected_tool_ok": tool_ok, "valid": bool(ok and tool_ok and d["result_subtype"] == "success"
                                                           and not d["result_is_error"]),
                "session": "same" if same else "new", "non_loopback_endpoints": len(seen), "injected_429": inject,
                **{k: v for k, v in d.items() if k not in ("answer", "session_id")}}
        if mode == "fork":
            step["fork_has_new_session_id"] = not same and bool(d["session_id"])
        run["steps"].append(step)
        log(f"{name}: exit={proc.returncode} valid={step['valid']} tools={[c['name'] for c in d['tool_calls']]} "
            f"endpoints={len(seen)} {step['wall_s']} s")
        (ev / "run.json").write_text(json.dumps(run, indent=2))
        time.sleep(1.0)
    run["project_files"] = sorted(p.name for p in project.iterdir())
    (ev / "run.json").write_text(json.dumps(run, indent=2))
    shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    main()
