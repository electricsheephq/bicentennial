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
from threading import Event, Thread
from types import SimpleNamespace

import pytest
import test_hermes_adapter as acceptance
from test_hermes_adapter import FAKE, make, session

from bicentennial.harness import egress
from bicentennial.harness.hermes import adapter, config

PROTOCOL = Path(__file__).with_name("fake_protocol_worker.py")


@pytest.fixture(autouse=True)
def fast_drain(monkeypatch):
    monkeypatch.setattr(egress, "_out", lambda argv: "8" if argv[:3] == ["ps", "-o", "rss="] else "")
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
        os.waitid(os.P_PID, worker.proc.pid, os.WEXITED | os.WNOWAIT)
    worker.kill()
    time.sleep(0.05)  # delivery of SIGKILL to the child; a zombie cannot keep writing
    size = heartbeat.stat().st_size
    time.sleep(0.1)
    assert heartbeat.stat().st_size == size
    assert worker.proc.poll() is not None


def test_clean_exit_signals_group_before_reaping_leader(workers, monkeypatch):
    worker, events = workers("normal"), []
    a = object.__new__(adapter.HermesAdapter)
    a._worker = worker
    real_wait = worker.proc.wait

    def reap(*args, **kwargs):
        result = real_wait(*args, **kwargs)
        events.append("reap")
        return result

    def signal_group(pid, sig):
        assert "reap" not in events, "killpg ran after the leader was reaped"
        assert (pid, sig) == (worker.proc.pid, signal.SIGKILL)
        assert os.waitid(os.P_PID, pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is not None
        events.append("signal")  # recording fake: the leader is already dead and has no children

    monkeypatch.setattr(worker.proc, "wait", reap)
    monkeypatch.setattr(os, "killpg", signal_group)
    a._end()
    worker.kill()  # a later close must not signal the now-reusable pgid
    assert events == ["signal", "reap"]


@pytest.mark.parametrize("phase", ["end", "own-exit"])
def test_zombie_only_group_is_reaped_without_faking_killpg(workers, phase):
    worker = workers("normal" if phase == "end" else "exit-after-ready")
    if phase == "end":
        a = object.__new__(adapter.HermesAdapter)
        a._worker = worker
        a._end()
    else:
        # Observe a spontaneous exit without reaping or changing Popen.returncode.
        assert os.waitid(os.P_PID, worker.proc.pid, os.WEXITED | os.WNOWAIT) is not None
        worker.kill()
    assert worker._reaped and worker.proc.returncode == 0
    with pytest.raises(ChildProcessError):
        os.waitid(os.P_PID, worker.proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG)
    worker.kill()  # idempotent after reap


@pytest.mark.parametrize("clean", [False, True])
def test_interrupted_reap_retry_never_signals_again(workers, monkeypatch, clean):
    worker, discarded = workers("normal"), []
    worker.egress = SimpleNamespace(discard=discarded.append)
    real_wait, real_killpg, signals = worker.proc.wait, os.killpg, []

    def signal_group(pid, sig):
        assert not signals, "retried cleanup signaled a reaped pid"
        signals.append(pid)
        real_killpg(pid, sig)

    def interrupted_wait(*args, **kwargs):
        real_wait(*args, **kwargs)
        raise KeyboardInterrupt

    def unexpected_waitid(*args):
        pytest.fail("retried cleanup called waitid on a reaped pid")

    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", signal_group)
        patch.setattr(worker.proc, "wait", interrupted_wait)
        with pytest.raises(KeyboardInterrupt):
            worker.kill()
        assert worker.proc.returncode is not None and not worker._reaped
        patch.setattr(os, "waitid", unexpected_waitid)
        worker.kill(clean=clean)
        worker.kill()
    assert worker._reaped and signals == [worker.proc.pid]
    assert discarded == [worker.proc.pid]


def test_killpg_permission_error_with_running_leader_is_not_ignored(workers, monkeypatch):
    worker = workers("normal")

    def denied(pid, sig):
        raise PermissionError("fixture permission denial")

    with monkeypatch.context() as patch:
        patch.setattr(os, "killpg", denied)
        with pytest.raises(PermissionError, match="fixture permission denial"):
            worker.kill()
    assert not worker._reaped and worker.proc.returncode is None


def test_concurrent_kill_cannot_signal_after_reap(workers, monkeypatch):
    worker, errors, signals = workers("normal"), [], []
    reaped, release, attempted, done = Event(), Event(), Event(), Event()
    real_wait, real_killpg = worker.proc.wait, os.killpg

    def reap(*args, **kwargs):
        result = real_wait(*args, **kwargs)
        reaped.set()
        assert release.wait(2), "test did not release reap hook"
        return result

    def signal_group(pid, sig):
        assert not reaped.is_set(), "concurrent killpg ran after reap"
        signals.append(pid)
        real_killpg(pid, sig)

    def kill(second=False):
        if second:
            attempted.set()
        try:
            worker.kill()
        except BaseException as exc:
            errors.append(exc)
        finally:
            if second:
                done.set()

    monkeypatch.setattr(worker.proc, "wait", reap)
    monkeypatch.setattr(os, "killpg", signal_group)
    first, second = Thread(target=kill), Thread(target=kill, args=(True,))
    first.start()
    try:
        assert reaped.wait(2)
        second.start()
        assert attempted.wait(2)
        assert not done.wait(0.05), "second cleanup escaped serialization during reap"
    finally:
        release.set()
        first.join(2)
        if second.ident is not None:
            second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert not errors
    assert signals == [worker.proc.pid]


def test_clean_exit_timeout_still_kills_and_reaps(workers, monkeypatch):
    worker = workers("normal")
    a = object.__new__(adapter.HermesAdapter)
    a._worker = worker
    monkeypatch.setattr(adapter, "EXIT_TIMEOUT_S", 0)
    monkeypatch.setattr(os, "waitid", lambda *args: None)  # leader has not reported exit before the deadline
    with pytest.raises(adapter.HarnessFailed, match="exit_timeout"):
        a._end()
    assert worker._reaped and worker.proc.returncode is not None
    worker.kill()


@pytest.mark.parametrize("phase", ["startup", "open", "turn", "end"])
def test_protocol_deadline_includes_partial_lines(workers, phase):
    t0 = time.monotonic()
    with pytest.raises(adapter.HarnessFailed, match=phase + "_timeout"):
        worker = workers("stall-" + phase)
        if phase != "startup":
            worker.call(op=phase)
    assert time.monotonic() - t0 < 1.8


@pytest.mark.parametrize("errors", [(UnicodeDecodeError("utf8", b"x", 0, 1, "synthetic"), ValueError()),
                                   (OSError(), subprocess.SubprocessError())])
def test_sampler_recovers_any_exception(monkeypatch, errors):
    from bicentennial.runner import t0

    sampler, done = egress.Egress(interval_s=0.001), Event()
    pending, sample = list(errors), sampler.sample

    def output(argv):
        if argv[0] == "lsof":
            return "header\nworker 40 user 3u IPv4 0 0t0 TCP 192.0.2.1:443"
        return "8" if argv[2] == "rss=" else ""

    def flaky():
        if pending:
            raise pending.pop(0)
        sample()
        done.set()

    monkeypatch.setattr(egress, "_out", output)
    monkeypatch.setattr(sampler, "sample", flaky)
    sampler.add(40)
    sampler.start()
    try:
        assert done.wait(2) and sampler.is_alive()
    finally:
        sampler.stop()
    assert sampler.summary()["failed_samples"] == {type(e).__name__: 1 for e in errors}
    assert sampler.summary()["non_loopback"] == ["192.0.2.1:443"]
    with pytest.raises(t0.T0Refused, match="upstream_record"):
        t0._audit([SimpleNamespace(hosts=[SimpleNamespace(records=list, egress=sampler)])])


@pytest.mark.parametrize("discard", [False, True])
def test_stop_samples_late_pid_and_remembers_discard(monkeypatch, discard):
    sampler, done = egress.Egress(interval_s=100), Event()
    sample = sampler.sample
    monkeypatch.setattr(sampler, "sample", lambda: (sample(), done.set()))
    sampler.start()
    try:
        assert done.wait(2)
        sampler.add(40)
        if discard:
            sampler.discard(40)
    finally:
        sampler.stop()
    summary = sampler.summary()
    assert summary["alive_at_stop"] and summary["failed_samples"] == {}
    assert summary["per_pid_samples"] == {"40": 1 if discard else 2}
    assert summary["unsampled"] == []


@pytest.mark.parametrize("name", ["", "worker-3.stderr", "host-2.stderr"])
def test_registration_gone_pid_names_worker(monkeypatch, tmp_path, name):
    from bicentennial.runner import t0

    sampler = egress.Egress()
    monkeypatch.setattr(egress, "_out", lambda argv: "")  # already gone at registration
    if name:
        proc = SimpleNamespace(pid=40, returncode=0, stdin=SimpleNamespace(fileno=lambda: 0))
        monkeypatch.setattr(adapter.subprocess, "Popen", lambda *a, **kw: proc)
        monkeypatch.setattr(adapter.os, "set_blocking", lambda *a: None)
        monkeypatch.setattr(adapter._Worker, "call", lambda self: {"ready": True})
        adapter._Worker([], {}, tmp_path, tmp_path / name, sampler).kill()
    else:
        sampler.add(40)
        sampler.discard(40)
    assert sampler.summary()["unsampled"] == [f"egress unsampled pid=40 log={name}"]
    sampler.alive_at_stop = True
    with pytest.raises(t0.T0Refused, match="egress_unobserved"):
        t0._audit([SimpleNamespace(hosts=[SimpleNamespace(records=list, egress=sampler)])])


def test_sampler_death_outside_sample(monkeypatch):
    sampler = egress.Egress()
    monkeypatch.setattr("threading.excepthook", lambda args: None)
    monkeypatch.setattr(sampler._halt, "wait", lambda seconds: (_ for _ in ()).throw(ValueError()))
    sampler.start()
    sampler.join(2)
    assert not sampler.is_alive()
    monkeypatch.setattr(sampler, "sample", lambda: (_ for _ in ()).throw(ValueError()))
    sampler.stop()
    assert sampler.summary()["alive_at_stop"] is False
    assert sampler.summary()["failed_samples"] == {"ValueError": 1}


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
    assert sampled == [41]
    sampler.discard(40)
    sampler.sample()
    assert sampled == [41]


def test_sampler_non_loopback_detail(monkeypatch):
    sampler, commands = egress.Egress(), []
    assert sampler.summary()["non_loopback_seen"] == []

    def output(argv):
        if argv[:2] == ["ps", "-A"]:
            assert argv == ["ps", "-A", "-o", "pid=,ppid=,pgid="]
            return "40 1 40\n41 1 41\n42 1 42\n"
        if argv[0] == "ps":
            if argv[2] == "comm=":
                commands.append(argv)
                return f"/synthetic/path with spaces/worker {argv[-1]}\n"
            return "8\n"
        names = ["127.0.0.1:1234", "[::1]:1234"] if argv[-1] == "42" else ["*:5353", "*:5353", "192.0.2.1:443"]
        return "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n" + "\n".join(
            f"worker {argv[-1]} user 3u IPv4 0 0t0 TCP {name}" for name in names)

    monkeypatch.setattr(egress, "_out", output)
    sampler.add(40)
    sampler.add(42)
    sampler.sample()
    assert sampler.summary() == dict(samples=5, per_pid_samples={"40": 3, "42": 2}, rss_peak_kib=8,
        alive_at_stop=False, failed_samples={}, unsampled=[],
        non_loopback=["*:5353", "192.0.2.1:443"], non_loopback_seen=[
            "egress name=*:5353 pid=40 comm=worker 40 samples=3",
            "egress name=192.0.2.1:443 pid=40 comm=worker 40 samples=3"])
    sampler.discard(40)
    sampler.add(41)
    sampler.sample()
    assert sampler.summary()["non_loopback_seen"] == [
        "egress name=*:5353 pid=40 comm=worker 40 samples=5",
        "egress name=192.0.2.1:443 pid=40 comm=worker 40 samples=5"]
    sampler.add(40)
    sampler.sample()
    assert all(row.endswith("samples=7") for row in sampler.summary()["non_loopback_seen"])
    assert commands == [["ps", "-o", "comm=", "-p", str(pid)] for pid in (40, 41)]



@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_sampler_unbound_sockets_platform_scope(monkeypatch, platform):
    sampler, commands = egress.Egress(), []
    rows = ["TCP *:* (CLOSED)", "UDP *:*", "ICMP *:*", "UDP *:5353", "TCP *:8080 (LISTEN)",
            "TCP 10.0.0.1:50000->192.0.2.1:443 (ESTABLISHED)",
            "TCP 127.0.0.1:50000->192.0.2.2:443 (ESTABLISHED)",
            "TCP 192.0.2.3:50000->127.0.0.1:443 (ESTABLISHED)", "UDP 127.0.0.1:5353"]

    def output(argv):
        if argv[:2] == ["ps", "-A"]:
            return "40 1 40\n41 1 41\n"
        if argv[0] == "ps":
            if argv[2] == "comm=":
                commands.append(int(argv[-1]))
                return f"/synthetic/worker{argv[-1]}\n"
            return "8\n"
        selected = rows[:2] if argv[-1] == "40" else rows
        return "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n" + "\n".join(
            f"worker {argv[-1]} user 3u IPv4 0 0t0 {row}" for row in selected)

    monkeypatch.setattr(egress, "PLATFORM", platform)
    monkeypatch.setattr(egress, "_out", output)
    assert not egress.loopback("*:*")
    # Pid 40 holds only unbound TCP and UDP sockets, so on macOS it has no endpoint and no command lookup
    alone = egress.Egress()
    alone.add(40)
    unbound = [] if platform == "darwin" else ["*:*"]
    assert alone.summary() == dict(samples=1, per_pid_samples={"40": 1}, rss_peak_kib=8, non_loopback=unbound,
        alive_at_stop=False, failed_samples={}, unsampled=[],
        non_loopback_seen=[f"egress name={name} pid=40 comm=worker40 samples=1" for name in unbound])
    assert commands == ([] if platform == "darwin" else [40])
    commands.clear()
    sampler.add(40)
    sampler.add(41)
    sampler.sample()
    names = ["*:*", "*:5353", "*:8080", "10.0.0.1:50000->192.0.2.1:443",
             "127.0.0.1:50000->192.0.2.2:443", "192.0.2.3:50000->127.0.0.1:443"]
    first = 41 if platform == "darwin" else 40
    assert sampler.summary() == dict(samples=5, per_pid_samples={"40": 3, "41": 2}, rss_peak_kib=8,
        alive_at_stop=False, failed_samples={}, unsampled=[],
        non_loopback=names, non_loopback_seen=[
            f"egress name={name} pid={first if name == '*:*' else 41} "
            f"comm=worker{first if name == '*:*' else 41} samples={3 if name == '*:*' and platform == 'linux' else 2}" for name in names])
    assert commands == ([41] if platform == "darwin" else [40, 41])


@pytest.mark.parametrize("failure", ["timeout", "empty"])
def test_sampler_comm_failure_keeps_observation(monkeypatch, failure):
    # A failed command lookup is diagnostic only: the endpoint still counts, and a later sample fills the name.
    sampler, fail = egress.Egress(), [True]

    def output(argv):
        if argv[:2] == ["ps", "-A"]:
            return "40 1 40\n"
        if argv[0] == "ps":
            if argv[2] == "comm=":
                if fail.pop() if fail else False:
                    if failure == "timeout":
                        raise subprocess.TimeoutExpired(argv, 30)
                    return ""
                return "/synthetic/worker\n"
            return "8\n"
        return ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                "worker 40 user 3u IPv4 0 0t0 TCP 192.0.2.1:443")

    monkeypatch.setattr(egress, "_out", output)
    sampler.add(40)
    summary = sampler.summary()
    assert (summary["samples"], summary["non_loopback"]) == (1, ["192.0.2.1:443"])
    assert summary["non_loopback_seen"] == ["egress name=192.0.2.1:443 pid=40 comm= samples=1"]
    sampler.sample()
    assert sampler.summary()["non_loopback_seen"] == [
        "egress name=192.0.2.1:443 pid=40 comm=worker samples=2"]

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
    settings = {"context": {"fixture_key": "fixture"}, "plugins": {"holographic": {"depth": 2}}}
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


@pytest.mark.parametrize("phase", ["drain", "end"])
@pytest.mark.parametrize("stopped,added_failures,error", [
    (True, 0, "director_stopped"),
    (False, 1, "write_failure"),
    (True, 1, "director_stopped"),
    (False, 0, None),
])
def test_session_shutdown_checks_director(tmp_path, monkeypatch, phase, stopped, added_failures, error):
    a = make(tmp_path, "shutdown", faults=[])
    a.director.write_failures = 7  # earlier failures must not reject a clean session
    real_call, real_drain = adapter._Worker.call, a._drain
    opened, drains, ended, injected = [], [], [], []

    def inject():
        a.director.stopped = stopped
        a.director.write_failures += added_failures
        injected.append(phase)

    def call(worker, **op):
        out = real_call(worker, **op)
        if op.get("op") == "open":
            opened.append(out["session_id"])
        elif op.get("op") == "end":
            assert out["ok"]  # a successful acknowledgment must not hide a director failure
            ended.append(True)
            if phase == "end":
                inject()
        return out

    def drain():
        elapsed = real_drain()
        drains.append(elapsed)
        if phase == "drain" and len(drains) == len(acceptance.SCRIPT["sessions"][0]["turns"]) + 1:
            inject()
        return elapsed

    monkeypatch.setattr(adapter._Worker, "call", call)
    monkeypatch.setattr(a, "_drain", drain)
    try:
        if error:
            with pytest.raises(adapter.HarnessFailed, match=f"^{error}$"):
                session(a, 1)
        else:
            result = session(a, 1)
            assert result == adapter.SessionResult(
                session=1, kind="replay", acp_session_id=opened[0], entrypoint="test-double",
                turns_ok=5, finals_matched=5, restarts=(), compaction_expected=False, summariser_records=0,
                surface_hash=adapter.surface_hash(a.paths["hermes_home"], a.volatile),
                gate=({"exit": 0, "state": "unset"},), timings_ms=result.timings_ms,
                finals=tuple((t["n"], t["assistant"]) for t in acceptance.SCRIPT["sessions"][0]["turns"]),
                active_memory_providers=("holographic",))
        assert injected == [phase] and ended == [True]
        assert a._worker._reaped and a._worker.proc.returncode == 0
    finally:
        a.close()


@pytest.mark.parametrize("phase", ["turn", "end"])
@pytest.mark.parametrize("stopped,added_failures,inflight,error", [
    (True, 0, 0, "director_stopped"),
    (False, 1, 0, "write_failure"),
    (False, 0, 1, "director_inflight"),
    (False, 0, 0, None),
    (True, 0, 1, "director_stopped"),
])
def test_session_timeout_checks_director(tmp_path, monkeypatch, phase, stopped, added_failures, inflight, error):
    a = make(tmp_path, "timeout", faults=[])
    a.director.write_failures = 7  # earlier failures must not reclassify a healthy director's timeout
    real_call, injected = adapter._Worker.call, []
    timeout = adapter.HarnessFailed(f"{phase}_timeout")

    def call(worker, **op):
        if op.get("op") == phase:
            a.director.stopped = stopped
            a.director.write_failures += added_failures
            a.director.inflight = inflight
            injected.append(phase)
            raise timeout
        return real_call(worker, **op)

    monkeypatch.setattr(adapter._Worker, "call", call)
    try:
        with pytest.raises(adapter.HarnessFailed, match=f"^{error or str(timeout)}$") as caught:
            session(a, 1)
        assert injected == [phase]
        if error:
            assert caught.value.__cause__ is timeout
        else:
            assert caught.value is timeout
        assert a._worker._reaped and a._worker.proc.returncode is not None
    finally:
        a.director.inflight = 0
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
    {"fallback_providers": [{"provider": "fixture", "model": "fixture"}]},
    {"fallback_model": {"provider": "fixture", "model": "fixture"}},
    {"providers": {"fixture": {"base_url": "https://fixture.invalid/v1"}}},
    {"custom_providers": [{"name": "fixture", "base_url": "https://fixture.invalid/v1"}]},
    {"moa": {"aggregator": {"provider": "fixture", "model": "fixture"}}},
    {"curator": {"auxiliary": {"provider": "fixture", "model": "fixture"}}},
    {"delegation": {"provider": "fixture", "model": "fixture"}},
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
