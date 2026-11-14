"""Ordinary-turn timing and the retained shutdown settle, without listening sockets."""

import errno
import inspect
import os
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from bicentennial.audit.source_damage import SourceBaseline
from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter

FAULTS = {n: [dict(kind=k)] for k, n in (("kill", 2), ("restart", 3), ("compaction", 4))}


def fake_session(root, wait, mode="boundary", faults=FAULTS, compact_turns=(), compact_drains=(), upgrades=None,
                 baseline=None, thread_names=None, observed=None, spawned=None, stopped_after=None, made=None,
                 residue_checks=None):
    """compact_turns: turns that record a compaction request; compact_drains: short drains (by drain call number)
    during which one is recorded. upgrades collects each short drain's upgrade() answer. spawned collects the kill
    flag at each spawn; stopped_after stops the director from that turn; made receives the adapter."""
    root.mkdir()
    a = object.__new__(adapter.HermesAdapter)
    if made is not None:
        made.append(a)
    a._receipt_sessions, a.background_threads, a._baseline_threads = {}, [], baseline
    a.clock = SimpleNamespace(step_s=60)
    turns = [dict(n=n, user=str(n), assistant="done") for n in range(1, 6)]
    a.script = {"sessions": [dict(index=1, kind="replay", turns=turns)]}
    a.schedule = SimpleNamespace(at=lambda index, n: faults.get(n, []))
    a.turn_wait_s, a.kill_mode = wait, mode
    a.paths = dict(root=root, hermes_home=root, home=root)
    a.entry, a.volatile, a.active_memory_providers = {"surfaces": []}, [], []
    a.entrypoint, a.before_shutdown, a._fired = "test-double", None, set()
    a.director = SimpleNamespace(ctx=SimpleNamespace(cursor=0), route={"alias": "scripted"}, start_session=lambda *args: None,
        control=lambda: dict(stopped=stopped_after is not None and history >= stopped_after, write_failures=0,
                             inflight=0), summariser_requests=0)
    a.egress = SimpleNamespace(forking=nullcontext())
    a._gate, a.records = lambda readings: None, lambda: []
    a.after_kill = False
    a._end = lambda: setattr(a, "after_kill", False) or ()  # the real end clears the flag
    source = SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, root)], [])
    history = 0

    def call(**kw):
        nonlocal history
        if a._held:
            with pytest.raises(adapter.HarnessKilled):
                a._on_hold(dict(session=a._held[0], turn=a._held[1]))
            return None
        history += 1
        a.director.summariser_requests += history in compact_turns
        result = dict(ok=True, final="done", history=history)
        if thread_names is not None:
            result["alive_threads"] = thread_names[history - 1]
        return result

    def kill():
        a._worker_killed()  # this fixture's worker is live when killed
        if residue_checks is not None and not (root / "ipc.fifo").exists():
            os.mkfifo(root / "ipc.fifo")

    a._worker = SimpleNamespace(call=call, kill=kill)
    def spawn(*args):  # as the real _spawn_open: check first; only a clean end clears the flag
        if spawned is not None:
            spawned.append(a.after_kill)
        if residue_checks is not None:
            receipt = source.receipt(after_kill=a.after_kill)
            residue_checks.append(receipt)
            if receipt is not None:
                receipt["_path"].unlink()  # as run_life does before the later surface hash
        return "session", history, False

    a._spawn_open = spawn
    drains = []

    def drain(*args, upgrade=None):
        drains.append(args if upgrade is None else (*args, "upgrade"))
        if upgrade is not None:
            a.director.summariser_requests += len(drains) in compact_drains
            if upgrades is not None:
                upgrades.append(upgrade())
        return 0

    a._drain = drain
    result = a.run_session(1, sim_t_s=0, lock_hash="a" * 64, attempt_id="attempt")
    if observed is not None:
        observed.extend(result.timings_ms["background_threads"])
    stable = asdict(result)
    stable.pop("timings_ms")
    return drains, canon(stable)


def test_every_default_wait_is_one_second():
    # The default is written at each entry point, so one test checks they agree (#388).
    from bicentennial.director.compiler.check import check_compile
    from bicentennial.report import t2lite_flips
    from bicentennial.runner import compare, life, t1, t2lite
    entries = (adapter.HermesAdapter, life.run_life, compare.run_t1, t1.prepare, t2lite.run_t2lite,
               t2lite._receipt, t2lite_flips.rerun_command, t2lite_flips.flip_report, check_compile)
    assert [inspect.signature(f).parameters["turn_wait_s"].default for f in entries] == [1.0] * len(entries)
    assert t1.T1Context.__dataclass_fields__["turn_wait_s"].default == 1.0


def test_full_wait_drain_calls_equal_baseline(tmp_path):
    drains, stable = fake_session(tmp_path / "current", 3.0)
    # Five turns and session end all retain the no-argument call shape.
    assert drains == [(), (), (), (), (), ()]
    assert stable == canon(dict(session=1, kind="replay", acp_session_id="session", entrypoint="test-double",
        turns_ok=5, finals_matched=5, restarts=[
            dict(after_turn=2, kind="kill", mode="boundary", history_before=2, history_after=2),
            dict(after_turn=3, kind="restart", mode="clean", history_before=3, history_after=3)],
        compaction_expected=True, summariser_records=0,
        surface_hash="4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        gate=[], finals=[[1, "done"], [2, "done"], [3, "done"], [4, "done"], [5, "done"]], reset=None,
        active_memory_providers=[], end_threads=[]))


@pytest.mark.parametrize("mode", ["boundary", "held"])
def test_fault_turns_and_session_end_keep_full_wait(tmp_path, mode):
    drains, _ = fake_session(tmp_path / mode, 1.0, mode=mode)
    assert drains == [(1.0, "upgrade"), (), (), (), (1.0, "upgrade"), ()]


@pytest.mark.parametrize("wait", [0.5, 1.0, 3.0])
def test_drain_waits_for_continuous_quiet(monkeypatch, wait):
    clock = SimpleNamespace(now=1.0, sleeps=[])
    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(adapter.time, "sleep", sleep)
    monkeypatch.setattr(adapter, "_now", lambda: clock.now)
    # Work arrives after an initially quiet sample, so the quiet window must start again.
    a = SimpleNamespace(director=SimpleNamespace(control=lambda: {"inflight": int(1.1 <= clock.now < 1.6)}))
    adapter.HermesAdapter._drain(a, wait)
    assert clock.now >= 1.6 + wait
    assert all(s == min(0.5, wait / 4) for s in clock.sleeps)


def test_default_drain_loop_equals_baseline(monkeypatch):
    assert adapter.DRAIN_QUIET_S == 3.0
    clock = SimpleNamespace(now=1.0, sleeps=[])
    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(adapter.time, "sleep", sleep)
    monkeypatch.setattr(adapter, "_now", lambda: clock.now)
    a = SimpleNamespace(director=SimpleNamespace(control=lambda: {"inflight": 0}))
    assert adapter.HermesAdapter._drain(a) == 3000
    assert clock.now == 4.0
    assert clock.sleeps == [0.5, 0.5, 0.5, 0.5, 0.5, 0.5]


def test_compaction_request_keeps_full_wait(tmp_path):
    # No scheduled fault: T1 and T2-lite compact under sprint pressure. Turn 2 records a compaction request, so its
    # settle is full; turn 3's arrives during its quiet time, so that short drain's upgrade() turns true.
    upgrades = []
    drains, _ = fake_session(tmp_path / "pressure", 1.0, faults={}, compact_turns={2}, compact_drains={3},
                             upgrades=upgrades)
    assert drains == [(1.0, "upgrade"), (), (1.0, "upgrade"), (1.0, "upgrade"), (1.0, "upgrade"), ()]
    assert upgrades == [False, True, False, False]
    drains, _ = fake_session(tmp_path / "default", 3.0, faults={}, compact_turns={2})
    assert drains == [()] * 6


def test_drain_upgrade_extends_quiet_to_full(monkeypatch):
    clock = SimpleNamespace(now=1.0, sleeps=[])
    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(adapter.time, "sleep", sleep)
    monkeypatch.setattr(adapter, "_now", lambda: clock.now)
    a = SimpleNamespace(director=SimpleNamespace(control=lambda: {"inflight": 0}))
    assert adapter.HermesAdapter._drain(a, 0.5, upgrade=lambda: False) == 500
    clock.now, clock.sleeps = 1.0, []
    # A compaction request recorded at 1.2 s: the quiet window, begun at 1.0 s, now has to reach 3.0 s.
    assert adapter.HermesAdapter._drain(a, 0.5, upgrade=lambda: clock.now >= 1.2) == 3250
    assert clock.now == 4.25  # the first 0.5 s sample at or past 4.0 s
    assert clock.sleeps == [0.125, 0.125] + [0.5] * 6


def test_drain_reads_inflight_before_upgrade(monkeypatch):
    clock = SimpleNamespace(now=1.0, sleeps=[])
    def sleep(seconds):
        clock.sleeps.append(seconds)
        clock.now += seconds
    monkeypatch.setattr(adapter.time, "monotonic", lambda: clock.now)
    monkeypatch.setattr(adapter.time, "sleep", sleep)
    monkeypatch.setattr(adapter, "_now", lambda: clock.now)
    recorded = []
    def control():
        # A compaction request is counted and leaves inflight just before this sample (the director's order).
        if clock.now >= 1.5 and not recorded:
            recorded.append(1)
        return {"inflight": 0}
    a = SimpleNamespace(director=SimpleNamespace(control=control))
    assert adapter.HermesAdapter._drain(a, 0.5, upgrade=lambda: bool(recorded)) == 3000


def test_turn_wait_never_exceeds_session_end(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.75)
    drains, _ = fake_session(tmp_path / "bounded", 1.0)
    assert drains == [()] * 6


@pytest.mark.parametrize("mode", ["boundary", "held"])
def test_harness_kills_mark_the_next_source_check(tmp_path, mode):
    # audit/source_damage.py: a FIFO or socket after a harness kill is a killed process's residue.
    seen, checks = [], []
    fake_session(tmp_path / "faults", 1.0, mode=mode, spawned=seen, residue_checks=checks)
    assert seen == [False, True, False]  # session start, after the kill at turn 2, after the clean restart at turn 3
    assert checks[:2] == [None, None]  # the scheduled live kill excuses its FIFO at the next check
    assert checks[2]["rule"] == "unsupported_entry"  # persistent residue counts after the clean restart
    made = []
    with pytest.raises(adapter.HarnessFailed, match="^director_stopped$"):
        fake_session(tmp_path / "stopped", 1.0, faults={}, stopped_after=1, made=made)
    assert made[0].after_kill is True  # the failure path killed the worker before any clean end


def test_clean_end_clears_the_kill_flag():
    a = object.__new__(adapter.HermesAdapter)
    a.after_kill, a._worker = True, SimpleNamespace(call=lambda **kw: {"ok": True}, kill=lambda clean=False: None)
    a._end()
    assert a.after_kill is False  # the worker ended by itself


@pytest.fixture
def spawn_adapter(monkeypatch, tmp_path):
    a = object.__new__(adapter.HermesAdapter)
    a.after_kill, a._worker = True, None
    a.check_sources, a.before_spawn, a.env_server, a._wiped = None, None, None, False
    a.paths = dict(hermes_home=tmp_path, workspace=tmp_path, logs=tmp_path, home=tmp_path, root=tmp_path)
    monkeypatch.setattr(adapter, "validate_paths", lambda paths: None)
    monkeypatch.setattr(adapter, "write_config", lambda *args, **kw: None)
    monkeypatch.setattr(adapter, "hermes_config", lambda *args, **kw: {})
    monkeypatch.setattr(adapter, "worker_env", lambda *args: {})
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    a.server, a.clock, a.checkout, a.extra_env = SimpleNamespace(port=0), SimpleNamespace(path=tmp_path), None, None
    a._alias, a.plugin, a.plugin_config, a.memory, a.toolsets = "scripted", None, None, None, ()
    a.window, a.context_engine, a.plugins_enabled, a.scripted, a.argv, a.pids, a.egress = (
        None, None, False, True, [], [], None)
    procs, real = [], subprocess.Popen

    def spawn(argv, *args, **kw):
        # Pipe/group tests do not exercise macOS scheduling policy.
        proc = real(argv[argv.index(sys.executable):], *args, **kw)
        procs.append(proc)
        return proc

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    yield a
    for proc in procs:
        if proc.poll() is None:
            os.killpg(proc.pid, adapter.signal.SIGKILL)
        proc.wait()
        proc.stdin.close()
        proc.stdout.close()


@pytest.mark.parametrize("before", [False, True])
def test_spawn_keeps_the_kill_flag_until_a_clean_end(spawn_adapter, before):
    a, seen = spawn_adapter, []
    a.after_kill = before
    a.check_sources = lambda: seen.append(a.after_kill)
    a.argv = [sys.executable, "-c", "import sys,time; print('{\"ready\":true}', flush=True); "
        "sys.stdin.readline(); print('{\"ok\":true,\"session_id\":\"s\",\"history\":0}', flush=True); time.sleep(30)"]
    try:
        a._spawn_open("session_start", None, {"spawn": [], "open": []})
        assert seen == [before]  # the pre-spawn check sees the state before this spawn
        assert a.after_kill is before  # a spawn neither marks a kill nor clears an earlier one
        a._worker.kill()
        assert a.after_kill is True  # real live-worker cleanup reports its kill
    finally:
        if a._worker is not None:
            a._worker.kill()


@pytest.mark.parametrize("failure", ["spawn", "self_exit"])
def test_failure_after_a_harness_kill_keeps_its_residue_excused(spawn_adapter, monkeypatch, tmp_path, failure):
    # A harness kill left a FIFO; the next worker never starts, or exits by itself during its first open. Until a clean
    # end, nothing tells the killed worker's residue from the next one's, so it stays excused.
    a = spawn_adapter
    baseline = SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, tmp_path)], [])
    os.mkfifo(tmp_path / "ipc.fifo")
    a.after_kill = True
    if failure == "spawn":
        def refuse(*args, **kw):
            raise OSError(errno.EMFILE, "Too many open files")
        monkeypatch.setattr(adapter.subprocess, "Popen", refuse)
        error = OSError
    else:
        a.argv = [sys.executable, "-c", "import sys; print('{\"ready\":true}', flush=True); sys.stdin.readline()"]
        monkeypatch.setattr(adapter, "_group_survivors", lambda pid: [])  # this synthetic worker never forks; no ps
        error = adapter.HarnessFailed
    with pytest.raises(error):
        a._spawn_open("session_start", None, {"spawn": [], "open": []})
    if a._worker is not None:
        a._worker.kill()  # as run_session's failure path
    assert a.after_kill is True
    assert baseline.receipt(after_kill=a.after_kill) is None


@pytest.mark.parametrize("phase", ["startup", "open", "turn"])
def test_timeout_reports_live_kill_and_excuses_fifo(spawn_adapter, monkeypatch, tmp_path, phase):
    a, seen = spawn_adapter, []
    baseline = SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, tmp_path)], [])
    a.after_kill = False
    a.check_sources = lambda: seen.append(a.after_kill)
    code = "import os,sys,time; "
    if phase != "startup":
        code += "print('{\"ready\":true}', flush=True); sys.stdin.readline(); "
    if phase == "turn":
        code += "print('{\"ok\":true,\"session_id\":\"s\",\"history\":0}', flush=True); sys.stdin.readline(); "
    a.argv = [sys.executable, "-c", code + "os.mkfifo('ipc.fifo'); time.sleep(30)"]
    monkeypatch.setattr(adapter, phase.upper() + "_TIMEOUT_S", 0.5)
    with pytest.raises(adapter.HarnessFailed, match=f"^{phase}_timeout$"):
        a._spawn_open("session_start", None, {"spawn": [], "open": []})
        a._worker.call(op="turn", text="wait")
    assert seen == [False]
    assert (a._worker is None) == (phase == "startup")  # constructor timeout precedes assignment
    assert (tmp_path / "ipc.fifo").is_fifo()
    assert a.after_kill is True
    assert baseline.receipt(after_kill=a.after_kill) is None
    assert baseline.receipt()["rule"] == "unsupported_entry"  # the flag alone excuses this FIFO


@pytest.mark.parametrize("clean", [False, True])
def test_leftover_group_kill_does_not_mark_worker_killed(spawn_adapter, monkeypatch, tmp_path, clean):
    a = spawn_adapter
    baseline = SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, tmp_path)], [])
    # The leader exits by itself, leaving a child and FIFO. Keep its pid waitable until group cleanup.
    a.after_kill = False
    code = "import os,time; os.mkfifo('ipc.fifo'); print('{\"ready\":true}', flush=True); "
    code += "pid=os.fork(); time.sleep(30) if pid == 0 else os._exit(0)"
    worker = adapter._Worker([sys.executable, "-c", code], {}, tmp_path, tmp_path / "stderr",
                             on_kill=a._worker_killed)
    os.waitid(os.P_PID, worker.proc.pid, os.WEXITED | os.WNOWAIT)
    signalled, real = [], os.killpg

    def killpg(pid, sig):
        signalled.append(pid)
        real(pid, sig)

    monkeypatch.setattr(adapter.os, "killpg", killpg)
    worker.kill(clean=clean)
    assert signalled == [worker.proc.pid] and worker._reaped
    assert a.after_kill is False  # killing children cannot excuse their exited parent's residue
    assert baseline.receipt(after_kill=a.after_kill)["rule"] == "unsupported_entry"


@pytest.mark.parametrize("exits", [True, False])
def test_closed_pipe_waits_for_the_exit_before_judging_the_kill(spawn_adapter, monkeypatch, tmp_path, exits):
    # A worker leaving by itself closes its pipe before its exit is waitable; the kill that follows must not take it
    # for a live worker. One that closes its pipe and stays is still a live worker after the grace.
    a = spawn_adapter
    a.after_kill = False
    monkeypatch.setattr(adapter, "EOF_SETTLE_S", 10.0 if exits else 0.3, raising=False)  # absent before the grace
    monkeypatch.setattr(adapter, "_group_survivors", lambda pid: [])  # this synthetic worker never forks; no ps
    code = "import os,time; print('{\"ready\":true}', flush=True); os.close(1); "
    code += "time.sleep(0.5); os._exit(0)" if exits else "time.sleep(30)"
    worker = adapter._Worker([sys.executable, "-c", code], {}, tmp_path, tmp_path / "stderr",
                             on_kill=a._worker_killed)
    assert worker.call(op="open") is None  # end of file while the worker is still running
    worker.kill()
    assert worker._reaped
    assert a.after_kill is not exits  # an exit under way is the worker's own; staying past the grace is not
