"""Spike S1 fresh captures: Claude Code and Codex, each against the 127.0.0.1 recording stub only.

Isolation (S2's recipe, extended to Codex): a fresh HOME, a fresh CLAUDE_CONFIG_DIR or CODEX_HOME under
--root, a project directory under $TMPDIR (outside the home tree, so no ancestor instruction file is
loaded), the base URL pointing at the stub, a placeholder key, non-essential traffic, autoupdate and
telemetry off, and a socket monitor on the process tree that records any non-loopback endpoint. No login
of any kind is used: Codex gets a custom model provider whose key is a placeholder in an env var.

One harness process at a time, each under nice -n 19, each gated on the busy marker (exit 11 waits).
The user turns are the S6a micro-life's synthetic replay turns; three carry a STUB_ directive, so tool
calls, their results and (Claude Code) a subagent on the small-fast alias appear. Writes into --out: ledger.jsonl (full bodies: scratch only), turns.json,
per-turn stdout, and run.json (exits, compaction markers, endpoints).

    python3.14 capture.py claude --root <fresh dir> --out <dir> [--turns 30] [--compact]
    python3.14 capture.py codex  --root <fresh dir> --out <dir> [--turns 20] [--limit 6000] --inflate 1000
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
from run_claude import monitor  # the S2 socket monitor (lsof on the process tree)

NICE = ["nice", "-n", "19", "taskpolicy", "-b"]
BUSY = os.environ.get("S1_BUSY_CMD", "")
TOOL_TURNS = {3: "STUB_RUN: echo s1-tool-probe-a", 17: "STUB_RUN: echo s1-tool-probe-b",  # a subagent on the fast alias
              9: 'STUB_TOOL: Agent {"description": "s1 probe", "prompt": "Reply done.", "subagent_type": "Explore"}'}
KEEP = ("PATH", "LANG", "LC_ALL", "TERM", "TMPDIR", "USER", "LOGNAME", "SHELL")
CC_MAIN, CC_FAST, CODEX_MAIN = "bicentennial-cc-main", "bicentennial-cc-fast", "bicentennial-codex-main"


def gate(log):
    """The busy marker before every harness process: exit 11 waits (60 s re-check); 0 and 10 proceed."""
    while BUSY:
        r = subprocess.run(BUSY, shell=True, capture_output=True, text=True, check=False)
        if r.returncode != 11:
            return r.returncode
        log("marker exit 11; waiting 60 s")
        time.sleep(60)


def prompts(n: int) -> list[str]:
    life = json.loads((HERE.parent / "s6a" / "micro_life.json").read_text())
    users = [t["user"] for s in life["sessions"] for t in s["turns"]]
    out = []
    for i in range(1, n + 1):
        p = users[(i - 1) % len(users)]
        out.append(p + (f"\n{TOOL_TURNS[i]}\n" if i in TOOL_TURNS else ""))
    return out


def start_stub(out: Path, inflate: int):
    ledger, port_file = out / "ledger.jsonl", out / "stub.port"
    for f in (ledger, port_file):
        f.unlink(missing_ok=True)
    with open(out / "stub.stderr", "w") as err:
        stub = subprocess.Popen(NICE + [sys.executable, "-I", str(HERE / "capture_stub.py"), "--ledger", str(ledger),
                                        "--port-file", str(port_file), "--inflate", str(inflate)],
                                stdout=subprocess.DEVNULL, stderr=err)
    for _ in range(100):
        if port_file.exists() and port_file.read_text().strip():
            return stub, int(port_file.read_text())
        time.sleep(0.1)
    stub.kill()
    sys.exit("stub did not start")


def run_one(cmd, cwd, env, timeout, out: Path, tag: str) -> dict:
    t0 = time.time()
    proc = subprocess.Popen(NICE + cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    seen, stop = set(), threading.Event()
    mon = threading.Thread(target=monitor, args=(proc, seen, stop), daemon=True)
    mon.start()
    try:
        so, se = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()  # our own child, by handle
        try:
            so, se = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            so, se = "", "killed; pipes still held"
    stop.set()
    mon.join(timeout=5)
    (out / f"{tag}.stdout").write_text(so)
    (out / f"{tag}.stderr").write_text(se)
    return {"tag": tag, "exit": proc.returncode, "wall_s": round(time.time() - t0, 1), "endpoints": sorted(seen)}


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


def boundaries(text: str) -> int:
    return sum(e.get("type") == "system" and e.get("subtype") == "compact_boundary" for e in events(text))


def claude(a, root: Path, out: Path, log) -> dict:
    home, config = root / "home", root / "config"
    for d in (home, config):
        d.mkdir(parents=True)
    project = Path(tempfile.mkdtemp(prefix="s1-cc-project-"))
    stub, port = start_stub(out, a.inflate)
    env = {k: os.environ[k] for k in KEEP if k in os.environ}
    env.update({"HOME": str(home), "CLAUDE_CONFIG_DIR": str(config), "TZ": "UTC",
                "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}", "ANTHROPIC_API_KEY": "placeholder",
                "ANTHROPIC_MODEL": CC_MAIN, "ANTHROPIC_DEFAULT_HAIKU_MODEL": CC_FAST,
                "ANTHROPIC_SMALL_FAST_MODEL": CC_FAST, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1", "DISABLE_TELEMETRY": "1", "DISABLE_ERROR_REPORTING": "1",
                "CLAUDE_CODE_ENABLE_TELEMETRY": "0"})
    entry = [shutil.which("claude") or "claude"]
    ps = prompts(a.turns) + (["/compact"] if a.compact else [])
    runs = []
    try:
        for i, p in enumerate(ps, 1):
            gate(log)
            cmd = entry + ["-p", p, "--output-format", "stream-json", "--verbose", "--allowedTools", "Bash,Agent"]
            cmd += ["--continue"] * (i > 1)
            runs.append(run_one(cmd, project, env, a.timeout, out, f"turn{i:02d}"))
            log(f"claude turn {i} exit={runs[-1]['exit']} {runs[-1]['wall_s']} s")
    finally:
        stub.terminate()
        stub.wait(timeout=10)
    marks = {"stream_compact_boundary": sum(boundaries((out / f"{r['tag']}.stdout").read_text()) for r in runs),
             "transcript_compact_boundary": sum(boundaries(f.read_text()) for f in (config / "projects").rglob("*.jsonl"))}
    shutil.rmtree(project, ignore_errors=True)
    return {"turns": ps, "runs": runs, "markers": marks, "aliases": {"main": CC_MAIN, "fast": CC_FAST}}


def codex(a, root: Path, out: Path, log) -> dict:
    home, chome = root / "home", root / "codex-home"
    for d in (home, chome):
        d.mkdir(parents=True)
    project = Path(tempfile.mkdtemp(prefix="s1-codex-project-"))
    stub, port = start_stub(out, a.inflate)
    (chome / "config.toml").write_text(
        f'model = "{CODEX_MAIN}"\nmodel_provider = "s1stub"\nmodel_auto_compact_token_limit = {a.limit}\n'
        'approval_policy = "never"\nsandbox_mode = "read-only"\ncheck_for_update_on_startup = false\n'
        '[features]\nplugins = false\nremote_plugin = false\nplugin_sharing = false\napps = false\n'
        'tool_suggest = false\nskill_mcp_dependency_install = false\n'
        '[analytics]\nenabled = false\n[feedback]\nenabled = false\n[history]\npersistence = "none"\n'
        f'[model_providers.s1stub]\nname = "s1stub"\nbase_url = "http://127.0.0.1:{port}/v1"\n'
        'env_key = "S1_STUB_KEY"\nwire_api = "responses"\nrequires_openai_auth = false\n')
    env = {k: os.environ[k] for k in KEEP if k in os.environ}
    env.update({"HOME": str(home), "CODEX_HOME": str(chome), "TZ": "UTC", "S1_STUB_KEY": "placeholder"})
    entry = [shutil.which("codex") or "codex", "exec"]
    ps, runs, compacted_at = prompts(a.turns), [], None
    try:
        for i, p in enumerate(ps, 1):
            gate(log)
            cmd = entry + (["resume", "--last"] if i > 1 else []) + ["--json", "--skip-git-repo-check", p]
            runs.append(run_one(cmd, project, env, a.timeout, out, f"turn{i:02d}"))
            log(f"codex turn {i} exit={runs[-1]['exit']} {runs[-1]['wall_s']} s")
            if runs[-1]["exit"] != 0 and i == 1:
                break  # a refusal (for example, a login demand) is reported as is; never worked around
            n = rollout_counts(chome)["compacted"]
            compacted_at = compacted_at or (i if n else None)
            if compacted_at and i >= compacted_at + 2:
                break
    finally:
        stub.terminate()
        stub.wait(timeout=10)
    shutil.rmtree(project, ignore_errors=True)
    return {"turns": ps[:len(runs)], "runs": runs, "markers": rollout_counts(chome), "compacted_after_turn": compacted_at,
            "limit": a.limit, "aliases": {"main": CODEX_MAIN}}


def rollout_counts(chome: Path) -> dict:
    """Codex's own compaction markers: compacted items in the rollout, and how many carry a replacement history."""
    items = [e.get("payload") or {} for f in chome.glob("sessions/**/rollout-*.jsonl") for e in events(f.read_text())
             if e.get("type") == "compacted"]
    return {"compacted": len(items), "compacted_with_replacement": sum(bool(i.get("replacement_history")) for i in items)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("harness", choices=["claude", "codex"])
    p.add_argument("--root", required=True, help="fresh dir for the homes (must not exist)")
    p.add_argument("--out", required=True)
    p.add_argument("--turns", type=int, default=30)
    p.add_argument("--compact", action="store_true", help="claude: one /compact after the turns")
    p.add_argument("--inflate", type=int, default=5500, help="reported input tokens per user message")
    p.add_argument("--limit", type=int, default=6000, help="codex: model_auto_compact_token_limit")
    p.add_argument("--timeout", type=int, default=240)
    a = p.parse_args()
    root, out = Path(a.root), Path(a.out)
    if root.exists():
        sys.exit("root already exists: refusing to reuse it")
    out.mkdir(parents=True, exist_ok=True)

    def log(msg):
        with open(out / "capture.log", "a") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

    res = (claude if a.harness == "claude" else codex)(a, root, out, log)
    res |= {"harness": a.harness, "inflate": a.inflate,
            "version": subprocess.run([shutil.which(a.harness) or a.harness, "--version"], capture_output=True,
                                      text=True, check=False, env={"PATH": os.environ["PATH"], "HOME": str(root / "home")}).stdout.strip()}
    (out / "turns.json").write_text(json.dumps(res["turns"], indent=1))
    (out / "run.json").write_text(json.dumps({k: v for k, v in res.items() if k != "turns"}, indent=1))
    print(json.dumps({"runs": [(r["tag"], r["exit"]) for r in res["runs"]], "markers": res["markers"]}))


if __name__ == "__main__":
    main()
