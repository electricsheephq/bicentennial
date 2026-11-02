"""Ordinary-turn timing and the retained shutdown settle, without listening sockets."""

import inspect
from contextlib import nullcontext
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter


def fake_session(root, wait, mode="boundary"):
    root.mkdir()
    a = object.__new__(adapter.HermesAdapter)
    turns = [dict(n=n, user=str(n), assistant="done") for n in range(1, 6)]
    a.script = {"sessions": [dict(index=1, kind="replay", turns=turns)]}
    faults = {n: [dict(kind=k)] for k, n in (("kill", 2), ("restart", 3), ("compaction", 4))}
    a.schedule = SimpleNamespace(at=lambda index, n: faults.get(n, []))
    a.turn_wait_s, a.kill_mode = wait, mode
    a.paths = dict(root=root, hermes_home=root, home=root)
    a.entry, a.volatile, a.active_memory_providers = {"surfaces": []}, [], []
    a.entrypoint, a.before_shutdown, a._fired = "test-double", None, set()
    a.director = SimpleNamespace(route={"alias": "scripted"}, start_session=lambda *args: None,
        control=lambda: dict(stopped=False, write_failures=0, inflight=0))
    a.egress = SimpleNamespace(forking=nullcontext())
    a._gate, a._end, a.records = lambda readings: None, lambda: (), lambda: []
    history = 0

    def call(**kw):
        nonlocal history
        if a._held:
            a._fired.add(a._held)
            return None
        history += 1
        return dict(ok=True, final="done", history=history)

    a._worker = SimpleNamespace(call=call, kill=lambda: None)
    a._spawn_open = lambda *args: ("session", history, False)
    drains = []
    a._drain = lambda *args: drains.append(args) or 0
    result = a.run_session(1, sim_t_s=0, lock_hash="a" * 64, attempt_id="attempt")
    stable = asdict(result)
    stable.pop("timings_ms")
    return drains, canon(stable)


def test_default_drain_calls_equal_baseline(tmp_path):
    default = inspect.signature(adapter.HermesAdapter).parameters["turn_wait_s"].default
    assert default == 3.0
    drains, stable = fake_session(tmp_path / "current", default)
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
    assert drains == [(1.0,), (), (), (), (1.0,), ()]


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


def test_turn_wait_never_exceeds_session_end(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.75)
    drains, _ = fake_session(tmp_path / "bounded", 1.0)
    assert drains == [()] * 6
