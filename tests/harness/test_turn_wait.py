"""Ordinary-turn timing and the retained shutdown settle, without listening sockets."""

import inspect
from contextlib import nullcontext
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter

FAULTS = {n: [dict(kind=k)] for k, n in (("kill", 2), ("restart", 3), ("compaction", 4))}


def fake_session(root, wait, mode="boundary", faults=FAULTS, compact_turns=(), compact_drains=(), upgrades=None):
    """compact_turns: turns that record a compaction request; compact_drains: short drains (by drain call number)
    during which one is recorded. upgrades collects each short drain's upgrade() answer."""
    root.mkdir()
    a = object.__new__(adapter.HermesAdapter)
    turns = [dict(n=n, user=str(n), assistant="done") for n in range(1, 6)]
    a.script = {"sessions": [dict(index=1, kind="replay", turns=turns)]}
    a.schedule = SimpleNamespace(at=lambda index, n: faults.get(n, []))
    a.turn_wait_s, a.kill_mode = wait, mode
    a.paths = dict(root=root, hermes_home=root, home=root)
    a.entry, a.volatile, a.active_memory_providers = {"surfaces": []}, [], []
    a.entrypoint, a.before_shutdown, a._fired = "test-double", None, set()
    a.director = SimpleNamespace(route={"alias": "scripted"}, start_session=lambda *args: None,
        control=lambda: dict(stopped=False, write_failures=0, inflight=0), summariser_requests=0)
    a.egress = SimpleNamespace(forking=nullcontext())
    a._gate, a._end, a.records = lambda readings: None, lambda: (), lambda: []
    history = 0

    def call(**kw):
        nonlocal history
        if a._held:
            a._fired.add(a._held)
            return None
        history += 1
        a.director.summariser_requests += history in compact_turns
        return dict(ok=True, final="done", history=history)

    a._worker = SimpleNamespace(call=call, kill=lambda: None)
    a._spawn_open = lambda *args: ("session", history, False)
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
