"""R12 acceptance in CI: the Hermes adapter driving tests/harness/fake_worker.py (no Hermes, no network), the egress
sampler's loopback rule, the honeypot count and the worker's import boundary."""

import ast
import json
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.director.responder import Reply
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.harness import egress
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HarnessFailed, HermesAdapter
from bicentennial.harness.hermes.config import CONFIG_DEVIATIONS
from bicentennial.ledger import verify
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.envserver.honeypot import plant
from bicentennial.systems.registry import REGISTRY, SystemRefused, load

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).resolve().with_name("fake_worker.py")
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
compile_micro_life = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
SCRIPT = compile_micro_life(dict(LIFE, sessions=LIFE["sessions"][:4], probes=[]))  # sessions 1-4, 20 turns
ENTRY = load(REGISTRY / "hermes-native.toml")
LOCK, BASE, STEP, DAY = "ab" * 32, 1_600_000_000, 60, 86400
ROUTES = {"routes": [{"system": "hermes-native", "segment": seg, "probe_model": "probe-model", "alias": alias,
                      "summariser": "summary-model", "vision": None, "served_by": "scripted"}
                     for seg, alias in (("seg0", "bicentennial-main"), ("seg1", "bicentennial-swap"))]}
FAULTS = [{"kind": "kill", "session": 2, "turn": 2}, {"kind": "restart", "session": 3, "turn": 3},
          {"kind": "swap", "session": 4, "turn": None}]
CURSORS = {(s["index"], t["n"]) for s in SCRIPT["sessions"] for t in s["turns"]}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)  # the fake sends nothing in the background
    for name in ("BICENTENNIAL_BUSY_CMD", "BICENTENNIAL_OPERATOR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def niced(monkeypatch):
    pids, real = [], adapter.assert_niced

    def check(pid):
        real(pid)
        pids.append(pid)

    monkeypatch.setattr(adapter, "assert_niced", check)
    return pids


def make(scratch, name, *, entry=ENTRY, faults=FAULTS, script=SCRIPT, routes=ROUTES, responder=None, **kw):
    root = scratch / name
    root.mkdir()
    kw.setdefault("worker_argv", [sys.executable, str(FAKE)])
    kw.setdefault("harness_pin", dict(ENTRY["artifact"]))
    return HermesAdapter(entry, script=script, route_table=RouteTable.load(routes),
                         schedule=FaultLite.load(faults, script), responder=responder or ScriptedResponder(entry),
                         clock=SimClock(root / "clock.json", BASE, STEP), root=root, scratch=scratch,
                         life="s6a-micro", branch="B0", run=f"run-{name}", gate_poll_s=0,
                         **kw)


def session(a, index):
    return a.run_session(index, sim_t_s=BASE + index * DAY, lock_hash=LOCK, attempt_id=f"attempt-s{index}")


def spawn_log(home, log):
    def hook(reason):  # runs before the spawn's config write, so it sees the previous spawn's alias
        path = home / "config.yaml"
        log.append((reason, json.loads(path.read_bytes())["model"]["default"] if path.exists() else None))
    return hook


def run_life(tmp_path, name, **kw):
    log = []
    a = make(tmp_path, name, before_spawn=spawn_log(tmp_path / name / "hermes-home", log), **kw)
    _, token = plant(a.paths["workspace"], f"run-{name}")
    try:
        results = [session(a, i) for i in range(1, 5)]
    finally:
        summary = a.close()
    return a, results, log, summary, token


def check_ledger(a):
    recs = a.records()
    script = [(r["cursor"]["session"], r["cursor"]["turn"]) for r in recs if r.get("served") == "script"]
    assert len(script) == 20 and set(script) == CURSORS  # exactly one per cursor
    assert not [r for r in recs if r.get("served") == "script_retry"]
    writes = [r for r in recs if r.get("served") == "write_tool_calls"]
    assert len(writes) == 20 and all(r["write_turn_readback"] is True for r in writes)
    assert not [r for r in recs if r.get("role") == "unknown"]
    counts = verify(a.paths["root"] / "ledger")
    assert counts["records"] == len(recs) and counts["chain_breaks"] == counts["truncated_tail"] == 0
    assert counts["bad_blobs"] == 0
    return recs


def test_replay_with_kill_restart_and_swap(tmp_path, niced):
    digests, pids = [], []
    for name in ("a", "b"):
        a, results, log, summary, token = run_life(tmp_path, name)
        check_ledger(a)
        assert [(r.turns_ok, r.finals_matched) for r in results] == [(5, 5)] * 4
        assert [row for r in results for row in r.restarts] == [
            {"after_turn": 2, "kind": "kill", "mode": "boundary", "history_before": 8, "history_after": 8},
            {"after_turn": 3, "kind": "restart", "mode": "clean", "history_before": 12, "history_after": 12}]
        assert log == [("session_start", None), ("session_start", "bicentennial-main"),
                       ("kill", "bicentennial-main"), ("session_start", "bicentennial-main"),
                       ("restart", "bicentennial-main"), ("session_start", "bicentennial-main")]
        assert json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())["model"]["default"] == \
            "bicentennial-swap"  # session 4's config
        for r in results:
            canon(asdict(r))
            assert r.entrypoint == "test-double" and r.compaction_expected is False and len(r.surface_hash) == 64
            assert r.gate == ({"exit": 0, "state": "unset"},) * (2 if r.restarts else 1) and r.reset is None
            turns = SCRIPT["sessions"][r.session - 1]["turns"]
            assert r.finals == tuple((t["n"], t["assistant"]) for t in turns)
        assert a.harness_record() == {"name": "hermes-agent", "version": "v0.22.2", "commit": None,
                                      "sha256": ENTRY["artifact"]["sha256"], "entrypoint": "test-double",
                                      "config_deviations": ["model.context_length",
                                                            "auxiliary.compression.context_length",
                                                            "agent.environment_probe"],
                                      "plugin_config": {}, "active_memory_providers": ["holographic"], "memory": True}
        assert a.honeypot_hits(token) == 0 and summary["non_loopback"] == []
        assert len(a.pids) == 6 and not a.director.control()["stopped"]
        digests.append(a.stable_digest())
        pids += a.pids
    assert niced == pids  # every spawned pid passed assert_niced
    assert digests[0] == digests[1]


def test_held_kill_is_not_delivered_and_resumes(tmp_path):
    a, results, log, _, _ = run_life(tmp_path, "held", kill_mode="held")
    recs = check_ledger(a)
    assert any(r.get("served") == "script" and r["cursor"] == {"session": 2, "turn": 2} for r in recs)
    assert [(r.turns_ok, r.finals_matched) for r in results] == [(5, 5), (4, 4), (5, 5), (5, 5)]
    held = results[1].restarts
    assert len(held) == 1 and held[0]["mode"] == "held" and held[0]["after_turn"] == 2
    assert held[0]["history_after"] >= held[0]["history_before"] == 4
    assert [reason for reason, _ in log].count("kill") == 1
    assert [n for n, _ in results[1].finals] == [1, 3, 4, 5]  # no final for the held-killed turn


def wipe(home, reported):
    def hook(reason):
        if reason == "kill":  # S10's positive control: the session rows are gone on wake
            shutil.rmtree(home / "fake-sessions")
            return reported
    return hook


def test_control_wipe_continues_with_a_fresh_session(tmp_path):
    a = make(tmp_path, "w", before_spawn=wipe(tmp_path / "w" / "hermes-home", True))
    try:
        results = [session(a, i) for i in (1, 2)]
    finally:
        a.close()
    assert results[0].reset is None and results[1].reset == "control_wipe"
    assert results[1].restarts == ({"after_turn": 2, "kind": "kill", "mode": "boundary", "history_before": 8,
                                    "history_after": 0},)
    assert (results[1].turns_ok, results[1].finals_matched) == (5, 5)


def test_an_unreported_missing_session_still_fails(tmp_path):
    a = make(tmp_path, "u", before_spawn=wipe(tmp_path / "u" / "hermes-home", False))
    try:
        session(a, 1)
        with pytest.raises(HarnessFailed, match="resume_failed"):
            session(a, 2)
    finally:
        a.close()


def test_config_is_written_after_the_spawn_hook(tmp_path):
    home, seen = tmp_path / "c" / "hermes-home", []

    def restore_install_state(reason):  # a wipe that also removes config.yaml, before every spawn
        (home / "config.yaml").unlink(missing_ok=True)
        seen.append(reason)
        return True

    a = make(tmp_path, "c", before_spawn=restore_install_state)
    try:
        results = [session(a, i) for i in (1, 2)]
    finally:
        a.close()
    assert seen == ["session_start", "session_start", "kill"]
    assert [(r.turns_ok, r.finals_matched, r.reset) for r in results] == [(5, 5, "control_wipe")] * 2
    cfg = json.loads((home / "config.yaml").read_bytes())
    assert cfg["model"] == dict(cfg["model"], default="bicentennial-main",
                                base_url=f"http://127.0.0.1:{a.server.port}/main/v1")


class ProbeResponder(ScriptedResponder):
    def respond(self, call):
        if call.role == "probe_main":
            return Reply(200, "probe", "scripted", call.model, text=f"probe answer {call.cursor['turn']}")
        return super().respond(call)


def test_probe_finals_are_returned(tmp_path):
    script = compile_micro_life(dict(LIFE, sessions=LIFE["sessions"][:1]))  # one replay session, then probes
    a = make(tmp_path, "p", faults=[], script=script, responder=ProbeResponder(ENTRY))
    try:
        results = [session(a, i) for i in (1, 2)]
    finally:
        a.close()
    assert results[1].kind == "probe" and results[1].finals_matched == 0
    assert results[1].finals == ((1, "probe answer 1"), (2, "probe answer 2"))


def test_a_plugin_entry_runs_on_the_harness_pin(tmp_path, monkeypatch):
    """A1: the pin checked is the harness's own (here a stand-in git checkout), not the plug-in's artifact."""
    repo = tmp_path / "harness"
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)  # untracked, as in a real checkout
    (repo / "README").write_text("stand-in harness\n")
    for argv in (["init", "-q"], ["add", "README"], ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                                       "commit", "-q", "-m", "pin"]):
        subprocess.run(["git", "-C", str(repo), *argv], check=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", "HEAD"], capture_output=True,
                             check=True).stdout
    pin = {"name": "hermes-agent", "version": "v0.22.2", "sha256": sha256(archive).hexdigest()}
    plugin = dict(ENTRY, name="hermes-holographic", write_tools=[], recall=None, read_tools=[],
                  artifact={"name": "holographic", "version": "v1.0.0", "sha256": "1" * 64})
    routes = {"routes": [dict(ROUTES["routes"][0], system="hermes-holographic")]}
    monkeypatch.setattr(adapter, "WORKER", FAKE)
    kw = dict(entry=plugin, faults=[], routes=routes, plugin="holographic", worker_argv=None, checkout=repo)
    with pytest.raises(adapter.PinMismatch):
        make(tmp_path, "bad", **kw, harness_pin=dict(pin, sha256="0" * 64))
    a = make(tmp_path, "plug", **kw, harness_pin=pin)
    try:
        result = session(a, 1)
    finally:
        a.close()
    assert result.entrypoint == adapter.ENTRYPOINT and (result.turns_ok, result.finals_matched) == (5, 5)
    assert a.harness_record() == {**pin, "commit": a.commit, "entrypoint": adapter.ENTRYPOINT,
                                  "config_deviations": list(CONFIG_DEVIATIONS), "plugin_config": {},
                                  "active_memory_providers": ["holographic"], "memory": True}
    assert json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())["memory"]["provider"] == "holographic"


def marker(tmp_path, first):
    script, count = tmp_path / "marker.sh", tmp_path / "marker.count"
    script.write_text('n=$(cat "$1" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$1"\n'
                      f'echo \'{{"state": "fake"}}\'; [ "$n" -ge 2 ] && exit 0; exit {first}\n')
    return f"sh {shlex.quote(str(script))} {shlex.quote(str(count))}", count


@pytest.mark.parametrize("machine_class,first", [("light", 11), ("heavy", 10)])
def test_gate_waits_before_any_spawn(tmp_path, monkeypatch, machine_class, first):
    cmd, count = marker(tmp_path, first)
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", cmd)
    seen = []
    a = make(tmp_path, "g", entry=dict(ENTRY, machine_class=machine_class), faults=[],
             before_spawn=lambda reason: seen.append(count.read_text().strip()))
    try:
        result = session(a, 1)
    finally:
        a.close()
    assert result.gate == ({"exit": first, "state": "fake"}, {"exit": 0, "state": "fake"})
    assert seen == ["2"] and len(a.pids) == 1  # no worker before the admitting reading


def test_refusals(tmp_path, monkeypatch):
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    monkeypatch.setattr(adapter, "serve", lambda *a: pytest.fail("a server was started"))
    with pytest.raises(SystemRefused) as refused:
        make(tmp_path, "lcmx", entry=load(REGISTRY / "lcm-x.toml"))
    assert refused.value.reasons == ("benchmark_operator_forbidden",)
    with pytest.raises(SystemRefused) as refused:
        make(tmp_path, "other", entry=dict(ENTRY, harness="other"))
    assert refused.value.reasons == ("harness_not_hermes",)
    for kind in ("kill", "restart", "compaction"):
        with pytest.raises(ValueError, match="needs a turn"):
            make(tmp_path, f"null-{kind}", faults=[{"kind": kind, "session": 2, "turn": None}])
    with pytest.raises(ValueError, match="plug-in"):
        make(tmp_path, "plugin", plugin="Bad Name")
    with pytest.raises(ValueError, match="harness pin"):
        HermesAdapter(ENTRY, script=SCRIPT, route_table=RouteTable.load(ROUTES), schedule=FaultLite.load([], SCRIPT),
                      responder=ScriptedResponder(ENTRY), clock=None, root=tmp_path / "x", scratch=tmp_path,
                      life="s6a-micro", branch="B0", run="run-x")


def test_final_mismatch_fails_the_session(tmp_path):
    script = json.loads(canon(SCRIPT))
    a = make(tmp_path, "m", faults=[])
    a.script = dict(script, sessions=[dict(script["sessions"][0], turns=[
        dict(t, assistant="not what the director serves") for t in script["sessions"][0]["turns"]])])
    try:
        with pytest.raises(HarnessFailed, match="final_mismatch"):
            session(a, 1)
    finally:
        a.close()
    assert a._worker.proc.poll() is not None  # the worker does not outlive a failed session


def test_honeypot_hits_count_request_bodies(tmp_path):
    a = make(tmp_path, "h", faults=[])
    try:
        a.director.start_session(1, BASE + DAY, LOCK, "attempt-s1", a.paths["root"] / "ledger")
        _, token = plant(a.paths["workspace"], "run-h")
        assert a.honeypot_hits(token) == 0
        body = {"model": "bicentennial-aux-title_generation", "messages": [{"role": "user", "content": f"t {token}"}]}
        status, _, _ = a.director.handle("POST", "/aux/title_generation/v1/chat/completions", {},
                                         json.dumps(body).encode())
        assert status == 200 and a.honeypot_hits(token) == 1 and a.honeypot_hits("absent") == 0
    finally:
        a.close()


# ---- egress ----------------------------------------------------------------------------------------------------
LSOF = """COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME
python 7 u 5u IPv4 0x1 0t0 TCP 127.0.0.1:50000->127.0.0.1:4321 (ESTABLISHED)
python 7 u 6u IPv6 0x2 0t0 TCP [::1]:4321 (LISTEN)
python 7 u 7u IPv4 0x3 0t0 TCP 127.0.0.1:50001->192.0.2.10:443 (SYN_SENT)
python 7 u 8u IPv4 0x4 0t0 UDP *:5353
"""


def test_lsof_names_and_the_loopback_rule():
    names = egress.lsof_names(LSOF)
    assert names == ["127.0.0.1:50000->127.0.0.1:4321", "[::1]:4321", "127.0.0.1:50001->192.0.2.10:443", "*:5353"]
    assert egress.hosts(names[0]) == ["127.0.0.1", "127.0.0.1"] and egress.hosts(names[3]) == ["*"]
    assert [egress.loopback(n) for n in names] == [True, True, False, False]
    assert egress.loopback("localhost:80") and not egress.loopback("")


@pytest.mark.skipif(shutil.which("lsof") is None, reason="lsof is absent")
def test_sampler_follows_descendants():
    child = ("import socket, time; s = socket.socket(); s.bind(('127.0.0.1', 0)); s.listen(); "
             "print('up', flush=True); time.sleep(30)")
    parent = subprocess.Popen(["sh", "-c", f"{shlex.quote(sys.executable)} -c {shlex.quote(child)} & wait"],
                              stdout=subprocess.PIPE, text=True)
    sampler = egress.Egress(interval_s=0.1)
    try:
        assert parent.stdout.readline().strip() == "up"
        sampler.add(parent.pid)
        sampler.start()
        deadline = time.monotonic() + 20
        while len(sampler.summary()["per_pid_samples"]) < 2 and time.monotonic() < deadline:
            time.sleep(0.1)
    finally:
        sampler.stop()
        subprocess.run(["pkill", "-P", str(parent.pid)], check=False)
        parent.kill()
        parent.wait()
    summary = sampler.summary()
    assert len(summary["per_pid_samples"]) >= 2 and summary["non_loopback"] == [] and summary["rss_peak_kib"] > 0


# ---- the worker's import boundary ------------------------------------------------------------------------------
def test_worker_imports_only_the_standard_library():
    tree = ast.parse(adapter.WORKER.read_text())
    top = {a.name for n in tree.body if isinstance(n, ast.Import) for a in n.names}
    top |= {n.module for n in tree.body if isinstance(n, ast.ImportFrom)}
    assert top == {"json", "os", "sys", "time"}
    every = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    every += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
    assert not [m for m in every if m.split(".")[0] == "bicentennial"]
    for path in (ROOT / "src" / "bicentennial").rglob("*.py"):  # and no bicentennial module imports it
        mods = [a.name for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Import) for a in n.names]
        mods += [f"{n.module}.{a.name}" for n in ast.walk(ast.parse(path.read_text()))
                 if isinstance(n, ast.ImportFrom) and n.module for a in n.names]
        assert not [m for m in mods if m.endswith("hermes.worker") or m == "worker"], path


def test_before_shutdown_observes_final_turn_before_end(tmp_path, monkeypatch):
    """The optional observation hook runs once, after drain and before worker end."""
    from types import SimpleNamespace

    order = []
    a = make(tmp_path, "observation", faults=[], before_shutdown=lambda: order.append("before"))
    # Exercise run_session's actual ordering without relying on host process permissions.
    monkeypatch.setattr(a, "_gate", lambda readings: None)
    monkeypatch.setattr(a, "_spawn_open", lambda *args: ("sid", 0, False))
    monkeypatch.setattr(a, "_drain", lambda: order.append("drain") or 0)
    replies = {turn["user"]: turn["assistant"] for turn in SCRIPT["sessions"][0]["turns"]}
    a._worker = SimpleNamespace(call=lambda **kw: order.append("turn") or {
        "ok": True, "final": replies[kw["text"]], "history": 0},
        kill=lambda: None)
    monkeypatch.setattr(a, "_end", lambda: order.append("end") or ())
    try:
        result = session(a, 1)
        assert order[-3:] == ["drain", "before", "end"]
        assert order.count("before") == 1 and order.count("turn") == result.turns_ok == 5
        order.clear()
        a.before_shutdown = None
        session(a, 1)
        assert "before" not in order and order[-1] == "end"
    finally:
        a.close()
