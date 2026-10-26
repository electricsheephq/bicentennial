"""Replay driver for spike S6a: runs the micro-life through a pinned Hermes against the director.

Each life session is a fresh Hermes session in a fresh worker process (HERMES_HOME is the run's
own home). The director is started under the upstream helper so only it holds the upstream
environment; Hermes gets a placeholder key and a proxy that points back at the director, so any
other egress attempt is recorded and refused. Paths come from flags and environment variables:

    S6A_HERMES   the pinned Hermes checkout (its .venv is used)
    S6A_HELPER   the upstream-env helper (live mode only)
    S6A_SCRATCH  regenerable bulk: homes/<run>, work/<run>
    S6A_EVIDENCE ledgers, timings and logs
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
NICE = ["nice", "-n", "19", "taskpolicy", "-b"]
AUX_TASKS = ["compression", "title_generation", "vision", "approval", "mcp", "memory_query_rewrite", "curator",
             "skills_hub", "tts_audio_tags", "voice_chat", "triage_specifier", "kanban_decomposer",
             "profile_describer", "goal_judge", "monitor", "moa_reference", "moa_aggregator", "review"]
PLACEHOLDER_KEY = "placeholder-not-a-key"


def env(name: str) -> Path:
    v = os.environ.get(name)
    if not v:
        sys.exit(f"set {name}")
    return Path(v)


def marker() -> dict:
    cmd = os.environ.get("S6A_BUSY_CMD", "")
    if not cmd:
        return {"exit": None, "glm": None}
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    try:
        return {"exit": r.returncode, "glm": bool(json.loads(r.stdout.strip() or "{}").get("glm"))}
    except ValueError:
        return {"exit": r.returncode, "glm": None}


def wait_for_machine(log):
    """Exit 11 means no CPU-heavy work: wait. Exit 10 is fine here (1-2 light Hermes processes)."""
    while True:
        m = marker()
        if shutil.disk_usage("/").free < 150e9:
            sys.exit("disk below 150 GB free: stopping")
        if m["exit"] != 11:
            return m
        log(f"marker exit 11; waiting 60 s ({m})")
        time.sleep(60)


def hermes_config(port: int, a) -> dict:
    base = f"http://127.0.0.1:{port}"
    aux = {t: {"provider": "auto", "model": f"bicentennial-aux-{t}", "base_url": f"{base}/aux/{t}/v1",
               "api_key": PLACEHOLDER_KEY} for t in AUX_TASKS}
    aux["compression"]["model"] = "bicentennial-summariser"
    cfg = {
        "model": {"default": "bicentennial-main", "provider": "custom", "base_url": f"{base}/main/v1",
                  "api_key": PLACEHOLDER_KEY, "context_length": a.context_length},
        "auxiliary": aux,
        "memory": {"memory_enabled": True, "user_profile_enabled": True, "provider": ""},
        "telemetry": {"shared_metrics": {"enabled": False, "send": False}},
        "updates": {"check": False},
        "auth": {"adopt_external_logins": False},
    }
    if a.toolsets != "default":
        cfg["platform_toolsets"] = {"acp": a.toolsets.split(",")}
    if a.threshold_tokens:
        cfg["compression"] = {"enabled": True, "threshold_tokens": a.threshold_tokens, "protect_last_n": a.protect_last_n}
    return cfg


class Egress(threading.Thread):
    """Samples the worker's sockets and resident memory once a second; records any non-loopback endpoint."""
    def __init__(self):
        super().__init__(daemon=True)
        self.pids, self.seen, self.samples, self.stop = set(), set(), 0, False
        self.rss: dict[int, list[int]] = {}  # pid -> RSS samples, KiB

    def run(self):
        while not self.stop:
            for pid in list(self.pids):
                rss = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
                if rss.isdigit():
                    self.rss.setdefault(pid, []).append(int(rss))
                r = subprocess.run(["lsof", "-a", "-i", "-P", "-n", "-p", str(pid)], capture_output=True, text=True)
                self.samples += 1
                for line in r.stdout.splitlines()[1:]:
                    name = line.split()[-2] if line.endswith(")") else line.split()[-1]
                    if not all(h in ("127.0.0.1", "[::1]", "localhost", "*") for h in _hosts(name)):
                        self.seen.add(name)
            time.sleep(1)


def _hosts(name: str) -> list[str]:
    return [part.rsplit(":", 1)[0] for part in name.replace("->", " ").split()]


class Worker:
    def __init__(self, a, home: Path, port: int, egress: Egress, log_path: Path):
        hermes = env("S6A_HERMES")
        e = {k: v for k, v in os.environ.items() if not k.startswith("BICENTENNIAL_")}
        proxy = f"http://127.0.0.1:{port}"
        e.update(HERMES_HOME=str(home), HOME=str(home / "fakehome"), PYTHONPATH=str(hermes),
                 PYTHONDONTWRITEBYTECODE="1", HERMES_DISABLE_LAZY_INSTALLS="1", HERMES_ACP_SKIP_CONFIGURED_MCP="1",
                 HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy, http_proxy=proxy, https_proxy=proxy,
                 NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        self.t0 = time.monotonic()
        self.p = subprocess.Popen(NICE + [str(hermes / ".venv/bin/python"), str(HERE / "hermes_worker.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=open(log_path, "ab"),
                                  text=True, env=e, cwd=str(home / "workspace"))
        egress.pids.add(self.p.pid)
        self.egress = egress
        self.ready = json.loads(self.p.stdout.readline())
        self.ready["t_spawn_ms"] = round((time.monotonic() - self.t0) * 1000)

    def call(self, **cmd) -> dict:
        self.p.stdin.write(json.dumps(cmd) + "\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError("worker exited")
        return json.loads(line)

    def kill(self):
        self.p.send_signal(signal.SIGKILL)
        self.p.wait()
        self.egress.pids.discard(self.p.pid)

    def close(self):
        t0 = time.monotonic()
        out = self.call(op="end")
        self.p.wait(timeout=300)
        out["t_ms"] = round((time.monotonic() - t0) * 1000)  # end op plus process exit
        self.egress.pids.discard(self.p.pid)
        return out


def control(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/_control", timeout=10) as r:
        return json.loads(r.read())


def drain(port: int, quiet_s: float = 3.0, cap_s: float = 240.0) -> float:
    """Wait until the director has had no request in flight for quiet_s (background aux calls)."""
    t0, calm = time.monotonic(), None
    while time.monotonic() - t0 < cap_s:
        if control(port)["inflight"] == 0:
            calm = calm or time.monotonic()
            if time.monotonic() - calm >= quiet_s:
                break
        else:
            calm = None
        time.sleep(0.5)
    return round((time.monotonic() - t0) * 1000)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", required=True)
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--life", default=str(HERE / "micro_life.json"))
    p.add_argument("--sessions", default="1-10")
    p.add_argument("--probes", action="store_true")
    p.add_argument("--write-turns", action="store_true")
    p.add_argument("--measure-overhead", action="store_true")
    p.add_argument("--mode", choices=["live", "stub"], default="live")
    p.add_argument("--toolsets", default="memory,session_search,todo")
    p.add_argument("--context-length", type=int, default=64000)
    p.add_argument("--threshold-tokens", type=int, default=0)
    p.add_argument("--protect-last-n", type=int, default=20)
    p.add_argument("--lane-rewrite", default="")
    p.add_argument("--chars-per-token", type=float, default=4.0)
    p.add_argument("--budget-cap", type=int, default=400)
    p.add_argument("--seed-home", default="", help="start from a copy of this earlier run's final home")
    a = p.parse_args()

    scratch, evid = env("S6A_SCRATCH"), env("S6A_EVIDENCE")
    home, work, out = scratch / "homes" / a.run, scratch / "work" / a.run, evid / a.run
    if home.exists() or out.exists():
        sys.exit(f"run {a.run} already exists; pick a new run name")
    if a.seed_home:  # a copy, so the earlier run's home stays as it ended
        shutil.copytree(scratch / "homes" / a.seed_home, home, symlinks=True)
    for d in (home / "workspace", home / "fakehome", work, out):
        d.mkdir(parents=True, exist_ok=True)
    logf = open(out / "replay.log", "a")

    def log(msg):
        logf.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
        logf.flush()

    lo, hi = (int(x) for x in a.sessions.split("-"))
    life = json.loads(Path(a.life).read_text())
    life["sessions"] = [s for s in life["sessions"] if lo <= s["index"] <= hi]
    life["probes"] = life.get("probes", []) if a.probes else []
    (work / "life.json").write_text(json.dumps(life))
    (home / "config.yaml").write_text(json.dumps(hermes_config(a.port, a), indent=1))

    dcmd = NICE + [sys.executable, str(HERE / "director.py"), "--port", str(a.port), "--life", str(work / "life.json"),
                   "--ledger-dir", str(out / "ledger"), "--budget-file", str(evid / "budget.json"),
                   "--budget-cap", str(a.budget_cap), "--run", a.run, "--mode", a.mode,
                   "--chars-per-token", str(a.chars_per_token), "--context-length", str(a.context_length)]
    dcmd += ["--lane-rewrite", a.lane_rewrite] * bool(a.lane_rewrite)
    dcmd += ["--write-turns"] * a.write_turns + ["--measure-overhead"] * a.measure_overhead
    if a.mode == "live":
        dcmd = [str(env("S6A_HELPER"))] + dcmd
    director = subprocess.Popen(dcmd, stdout=subprocess.PIPE, stderr=open(out / "director.log", "ab"), text=True)
    log(director.stdout.readline().strip())

    egress = Egress()
    egress.start()
    rows, t_run = [], time.monotonic()
    plan = [("life", s) for s in life["sessions"]] + [("probe", s) for s in life["probes"]]
    try:
        for kind, sess in plan:
            m = wait_for_machine(log)
            t_s = time.monotonic()
            w = Worker(a, home, a.port, egress, out / "hermes.log")
            opened = w.call(op="open", session_id=None, cwd=str(home / "workspace"))
            base = {"run": a.run, "phase": kind, "session": sess["index"], "marker_exit": m["exit"],
                    "glm": m["glm"]}
            for what, ms in (("spawn_import", w.ready["t_spawn_ms"]), ("open", opened["t_ms"])):
                rows.append({**base, "turn": 0, "what": what, "t_ms": ms, "ok": opened["ok"], "load1": os.getloadavg()[0]})
            for i, t in enumerate(sess["turns"], 1):
                t_wall = time.time()
                r = w.call(op="turn", text=t["user"])
                rows.append({**base, "turn": i, "what": "turn", "t_ms": r["t_ms"], "ok": r["ok"], "t_wall": t_wall,
                             "load1": os.getloadavg()[0], "final": r["final"][:200] if kind == "probe" else ""})
                log(f"{kind} {sess['index']}.{i} ok={r['ok']} {r['t_ms']} ms err={r.get('error')}")
                if not r["ok"] or not r["final"]:
                    raise RuntimeError(f"turn failed: {kind} {sess['index']}.{i}")
                if a.write_turns and kind == "life" and control(a.port).get("write_failures"):
                    raise RuntimeError(f"write turn failed at {sess['index']}.{i}: run invalid, stopping")
                if sess.get("restart_after_turn") == i:  # restart wake: SIGKILL at a turn boundary
                    w.kill()
                    t_k = time.monotonic()
                    w = Worker(a, home, a.port, egress, out / "hermes.log")
                    re_open = w.call(op="open", session_id=opened["session_id"], cwd=str(home / "workspace"))
                    rows.append({**base, "turn": i, "what": "restart", "t_ms": round((time.monotonic() - t_k) * 1000),
                                 "ok": re_open["ok"] and re_open["history"] > 0, "load1": os.getloadavg()[0]})
                    log(f"restart after {sess['index']}.{i}: resumed history={re_open['history']}")
            rows.append({**base, "turn": 0, "what": "drain", "t_ms": drain(a.port), "ok": True,
                         "load1": os.getloadavg()[0]})
            rows.append({**base, "turn": 0, "what": "close", "t_ms": w.close()["t_ms"], "ok": True,
                         "load1": os.getloadavg()[0]})
            rows.append({**base, "turn": 0, "what": "session_total", "t_ms": round((time.monotonic() - t_s) * 1000),
                         "ok": True, "load1": os.getloadavg()[0]})
    finally:
        egress.stop = True
        ctl = control(a.port) if director.poll() is None else {}
        director.terminate()
        director.wait(timeout=30)
        with open(out / "timings.csv", "w", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=["run", "phase", "session", "turn", "what", "t_ms", "ok", "load1",
                                               "marker_exit", "glm", "t_wall", "final"], extrasaction="ignore")
            wr.writeheader()
            wr.writerows(rows)
        (out / "summary.json").write_text(json.dumps({
            "run": a.run, "wall_ms": round((time.monotonic() - t_run) * 1000), "director": ctl,
            "egress_non_loopback": sorted(egress.seen), "egress_samples": egress.samples,
            "worker_rss_kib": [{"peak": max(v), "mean": round(sum(v) / len(v)), "n": len(v)} for v in egress.rss.values()],
            "args": {k: v for k, v in vars(a).items()}}, indent=1))
        log("done")


if __name__ == "__main__":
    main()
