"""Offline regressions for the nine fixes dispatched against PR #78 / 50f1fbf."""

import importlib.util
import io
import json
import os
import runpy
import signal
import subprocess
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_hermes_adapter as acceptance
from test_hermes_adapter import FAKE, make, session

from bicentennial.harness import egress
from bicentennial.harness.hermes import adapter, config

PROTOCOL = Path(__file__).with_name("fake_protocol_worker.py")


@pytest.fixture(autouse=True)
def fast_drain(monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    # Functional fakes do not exercise macOS scheduling policy (covered by the original niceness test).
    real = subprocess.Popen

    def scheduling_stub(argv, *args, **kwargs):
        if argv[0] == "nice" and (str(PROTOCOL) in argv or str(FAKE) in argv):
            start = argv.index(str(PROTOCOL) if str(PROTOCOL) in argv else str(FAKE)) - 1
            argv = argv[start:]
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(adapter.subprocess, "Popen", scheduling_stub)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)


@pytest.fixture
def workers(tmp_path, monkeypatch):
    """Retain even failed constructors, so a failing base regression never leaves processes behind."""
    spawned, real = [], subprocess.Popen

    def capture(argv, *args, **kwargs):
        proc = real(argv, *args, **kwargs)
        if str(PROTOCOL) in argv:
            spawned.append(proc)
        return proc

    monkeypatch.setattr(adapter.subprocess, "Popen", capture)
    for name in ("STARTUP_TIMEOUT_S", "OPEN_TIMEOUT_S", "TURN_TIMEOUT_S", "END_TIMEOUT_S"):
        monkeypatch.setattr(adapter, name, 0.5, raising=False)
    yield lambda mode: adapter._Worker([sys.executable, str(PROTOCOL), mode, str(tmp_path)],
                                      {"PATH": os.defpath}, tmp_path, tmp_path / "stderr")
    for proc in spawned:
        if proc.poll() is None and os.getpgid(proc.pid) == proc.pid:
            os.killpg(proc.pid, signal.SIGKILL)
        elif proc.poll() is None:
            proc.kill()
        proc.wait()
    child = tmp_path / "child"
    if child.exists():
        try:
            os.kill(int(child.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("mode,error", [("malformed", json.JSONDecodeError), ("invalid-ready", Exception)])
def test_startup_failure_reaps_worker(workers, tmp_path, mode, error):
    with pytest.raises(error):
        workers(mode)
    pid = int((tmp_path / "pid").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_startup_interrupt_reaps_worker(workers, monkeypatch, tmp_path):
    def interrupt(self, **op):
        deadline = time.monotonic() + 2
        while not (tmp_path / "pid").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise KeyboardInterrupt

    monkeypatch.setattr(adapter._Worker, "call", interrupt)
    with pytest.raises(KeyboardInterrupt):
        workers("normal")
    with pytest.raises(ProcessLookupError):
        os.kill(int((tmp_path / "pid").read_text()), 0)


@pytest.mark.parametrize("parent_exited", [False, True])
def test_kill_owns_tree_even_after_parent_exit(workers, tmp_path, parent_exited):
    worker = workers("tree")
    deadline = time.monotonic() + 2
    heartbeat = tmp_path / "heartbeat"
    while not heartbeat.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    if parent_exited:
        assert worker.call(op="end")["ok"]
        worker.proc.wait(timeout=2)
    worker.kill()
    time.sleep(0.05)  # delivery of SIGKILL to the child; a zombie cannot keep writing
    size = heartbeat.stat().st_size
    time.sleep(0.1)
    assert heartbeat.stat().st_size == size
    assert worker.proc.poll() is not None


@pytest.mark.parametrize("phase", ["startup", "open", "turn", "end"])
def test_protocol_deadline_includes_partial_lines(workers, phase):
    t0 = time.monotonic()
    with pytest.raises(adapter.HarnessFailed, match=phase + "_timeout"):
        worker = workers("stall-" + phase)
        if phase != "startup":
            worker.call(op=phase)
    assert time.monotonic() - t0 < 1.8


def test_sampler_keeps_orphaned_group_members(monkeypatch):
    sampler, sampled = egress.Egress(), []

    def output(argv):
        if argv[:2] == ["ps", "-A"]:
            # Worker 40 has exited; child 41 was adopted by init but still belongs to group 40.
            return "41 1 40\n" if "pgid" in argv[-1] else "41 1\n"
        if argv[0] == "ps":
            return "8" if argv[-1] == "41" else ""
        sampled.append(int(argv[-1]))
        return "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"

    monkeypatch.setattr(egress, "_out", output)
    sampler.add(40)  # registered workers are session/group leaders
    sampler.sample()
    assert sampled == [41]
    sampler.discard(40)
    sampler.sample()
    assert sampled == [41]


def test_relative_checkout_is_absolute_before_spawn(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(adapter, "verify_pin", lambda checkout, pin: "fake-pin")
    # Replace only transport: capture the executable that would otherwise fail in workspace's cwd.
    seen, real = [], adapter._Worker

    def spawn(argv, *args, **kwargs):
        seen.append(argv[0])
        return real([sys.executable, str(FAKE)], *args, **kwargs)

    monkeypatch.setattr(adapter, "_Worker", spawn)
    a = make(tmp_path, "relative", faults=[], checkout=Path("checkout"), worker_argv=None)
    try:
        session(a, 1)
    finally:
        a.close()
    assert seen == [str(tmp_path / "checkout" / ".venv" / "bin" / "python")]
    assert a.checkout == (tmp_path / "checkout").resolve()


@pytest.mark.parametrize("dirname", ["tmp", "workspace", "home", "hermes-home"])
@pytest.mark.parametrize("on_wake", [False, True])
def test_symlink_run_dirs_refused(tmp_path, dirname, on_wake):
    root, outside = tmp_path / "run", tmp_path / "outside"
    outside.mkdir()
    if not on_wake:
        root.mkdir()
        (root / dirname).symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="symlink|outside"):
            config.layout(root, tmp_path)
        return

    def hook(reason):
        path = root / dirname
        # Preserve its original contents; the fixture owns both these directories.
        path.rename(root / (dirname + "-original"))
        path.symlink_to(outside, target_is_directory=True)

    a = make(tmp_path, "run", faults=[], before_spawn=hook)
    try:
        with pytest.raises(ValueError, match="symlink|outside"):
            session(a, 1)
        assert not a.pids
        assert not list(outside.iterdir())
    finally:
        a.close()


def test_inactive_plugin_is_refused_and_active_list_recorded(tmp_path):
    # The fake uses a fixed list of supported fixture providers, never echoes arbitrary configuration.
    a = make(tmp_path, "inactive", faults=[], plugin="missing")
    try:
        with pytest.raises(adapter.HarnessFailed, match="plugin_inactive"):
            session(a, 1)
        assert a._worker.proc.poll() is not None
        assert a.harness_record()["active_memory_providers"] == ["holographic"]
    finally:
        a.close()


@pytest.mark.parametrize("providers", [["holographic"], None])
def test_real_worker_reports_agent_memory_providers(monkeypatch, providers):
    """Execute worker.main with fake Hermes modules; do not import or run Hermes."""
    emitted = []
    agent = SimpleNamespace()
    if providers is not None:
        agent._memory_manager = SimpleNamespace(providers=[SimpleNamespace(name=n) for n in providers])
    state = SimpleNamespace(agent=agent, session_id="fake", history=[])
    manager = SimpleNamespace(create_session=lambda cwd: state, end_all_sessions=lambda: None)
    modules = {
        "acp_adapter.entry": {"_load_env": lambda: None, "_setup_logging": lambda: None},
        "agent.ssl_verify": {"install_truststore": lambda: None},
        "acp_adapter.session": {"SessionManager": lambda: manager},
        "gateway.session_context": {"clear_session_vars": lambda: None, "set_session_vars": lambda: None},
    }
    for name, attrs in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    worker = runpy.run_path(str(adapter.WORKER))
    worker["main"].__globals__["emit"] = emitted.append
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"op":"open","cwd":"fake"}\n{"op":"end"}\n'))
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # restore the worker's chatter redirection on fixture exit
    worker["main"]()
    assert emitted[1].get("active_memory_providers") == (providers or [])


def test_plugin_config_survives_every_spawn_and_is_recorded(tmp_path):
    settings = {"context": {"engine": "fixture"}, "plugins": {"holographic": {"depth": 2}}}
    a = make(tmp_path, "settings", plugin="holographic", plugin_config=settings)
    try:
        session(a, 1)
        result = session(a, 2)  # boundary kill and resume both rewrite config.yaml
        cfg = json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())
        assert cfg["context"] == settings["context"] and cfg["plugins"] == settings["plugins"]
        assert a.harness_record()["plugin_config"] == settings
        assert result.active_memory_providers == ("holographic",)
    finally:
        a.close()


def test_plugin_config_deep_merge_without_mutating_input():
    settings = {"memory": {"fixture": {"enabled": True}}, "agent": {"fixture": 1}}
    cfg = config.hermes_config(4321, "bicentennial-main", plugin_config=settings)
    assert cfg["memory"]["memory_enabled"] and cfg["memory"]["fixture"] == {"enabled": True}
    assert cfg["agent"] == {"environment_probe": False, "fixture": 1}
    cfg["memory"]["fixture"]["enabled"] = False
    assert settings["memory"]["fixture"]["enabled"] is True


@pytest.mark.parametrize("settings", [
    {"model": {}}, {"auxiliary": {}}, {"agent": {"environment_probe": False}}, {"agent": None},
    {"memory": {"provider": "other"}},
])
def test_plugin_config_cannot_override_owned_routes(settings):
    with pytest.raises(ValueError, match="owned"):
        config.hermes_config(4321, "bicentennial-main", plugin_config=settings)


def test_main_context_deviation_is_disclosed():
    assert "model.context_length" in config.CONFIG_DEVIATIONS


@pytest.mark.parametrize("mode", ["boundary", "held"])
def test_existing_replay_acceptance_with_fake_scheduling(tmp_path, monkeypatch, mode):
    """Functional acceptance only: the unmodified original tests retain real scheduling/sampler checks."""
    if mode == "held":
        acceptance.test_held_kill_is_not_delivered_and_resumes(tmp_path)
    else:
        niced = []
        monkeypatch.setattr(adapter, "assert_niced", niced.append)
        acceptance.test_replay_with_kill_restart_and_swap(tmp_path, niced)


def test_live_digest_mismatch_is_failure_with_diff(tmp_path, monkeypatch):
    """Run the actual live-test assertion with stub adapters; its Hermes gate is never invoked."""
    spec = importlib.util.spec_from_file_location("fake_live", Path(__file__).with_name("test_hermes_live.py"))
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    monkeypatch.setattr(live, "checkout", lambda: Path("fake"))
    monkeypatch.setattr(live, "verify_pin", lambda *args: None)
    # Stub records satisfy the existing per-run counts; only digest inequality is injected.
    script = {"sessions": [{"index": i, "turns": [{"n": j} for j in range(6)]} for i in range(10)]}
    monkeypatch.setattr(live, "compile_micro_life", lambda life: script)
    recs = [{"served": "script", "cursor": {"session": s["index"], "turn": t["n"]}} for s in script["sessions"]
            for t in s["turns"]]
    result = SimpleNamespace(gate=[], summariser_records=0, finals_matched=60, entrypoint=live.ENTRYPOINT,
                             session=5, restarts=[{"after_turn": 2, "history_after": 1, "history_before": 1}],
                             timings_ms={})
    def run_once(scratch, name, *args):
        fake = SimpleNamespace(
            director=SimpleNamespace(control=lambda: {"write_failures": 0, "stopped": False}),
            records=lambda: recs, egress=SimpleNamespace(summary=lambda: {"per_pid_samples": {}, "non_loopback": []}),
            server=SimpleNamespace(port=1 if name == "a" else 2), pids=[], paths={"root": scratch},
            harness_record=lambda: {"entrypoint": live.ENTRYPOINT}, honeypot_hits=lambda token: 0,
            stable_digest=lambda: name, close=lambda: None)
        return fake, [result], "fake", time.monotonic()

    monkeypatch.setattr(live, "run_once", run_once)
    monkeypatch.setattr(live, "verify", lambda path: {"chain_breaks": 0, "truncated_tail": 0, "bad_blobs": 0})
    monkeypatch.setattr(live, "first_difference", lambda *args: {"fixture": "digest mismatch"})
    try:
        with pytest.raises(AssertionError):
            live.test_live_micro_life_twice(tmp_path)
    except pytest.xfail.Exception:
        pytest.fail("digest mismatch was hidden as xfail")
    assert json.loads((tmp_path / "live-digest-diff.json").read_bytes()) == {"fixture": "digest mismatch"}
