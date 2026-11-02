"""Ordinary-turn timing and the retained shutdown settle, without listening sockets."""

import ast
import inspect
import subprocess
from contextlib import nullcontext
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter

BASE = "f6662e6ac4aa2813057d825e987b89f3122c59ff"


def baseline_method(name):
    source = subprocess.run(["git", "show", f"{BASE}:src/bicentennial/harness/hermes/adapter.py"],
        check=True, capture_output=True, text=True).stdout
    cls = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == "HermesAdapter")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    namespace = dict(vars(adapter))
    namespace["_now"] = lambda: adapter._now()
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<baseline adapter>", "exec"), namespace)
    return namespace[name]


def fake_session(root, wait, method=adapter.HermesAdapter.run_session, mode="boundary"):
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
    result = method(a, 1, sim_t_s=0, lock_hash="a" * 64, attempt_id="attempt")
    stable = asdict(result)
    stable.pop("timings_ms")
    return drains, canon(stable)


def test_default_drain_calls_equal_baseline(tmp_path):
    default = inspect.signature(adapter.HermesAdapter).parameters["turn_wait_s"].default
    assert default == 3.0
    current = fake_session(tmp_path / "current", default)
    baseline = fake_session(tmp_path / "baseline", default, baseline_method("run_session"))
    assert current == baseline
    assert current[0] == [()] * 6


@pytest.mark.parametrize("mode", ["boundary", "held"])
def test_fault_turns_and_session_end_keep_full_wait(tmp_path, mode):
    drains, _ = fake_session(tmp_path / mode, 1.0, mode=mode)
    assert drains == [(1.0,), (), (), (1.0,), (1.0,), ()]


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
    def run(method):
        clock = SimpleNamespace(now=1.0, sleeps=[])
        def sleep(seconds):
            clock.sleeps.append(seconds)
            clock.now += seconds
        monkeypatch.setattr(adapter.time, "monotonic", lambda: clock.now)
        monkeypatch.setattr(adapter.time, "sleep", sleep)
        monkeypatch.setattr(adapter, "_now", lambda: clock.now)
        a = SimpleNamespace(director=SimpleNamespace(control=lambda: {"inflight": 0}))
        return method(a), clock.sleeps
    assert run(adapter.HermesAdapter._drain) == run(baseline_method("_drain"))


def test_turn_wait_never_exceeds_session_end(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.75)
    drains, _ = fake_session(tmp_path / "bounded", 1.0)
    assert drains == [()] * 6
