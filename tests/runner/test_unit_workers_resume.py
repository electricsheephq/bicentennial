"""Arm admission identity, interruption and spend-stop regressions."""

import runpy
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event, current_thread

import pytest
from test_t1 import environment, installed, prepare  # noqa: F401
from test_t2lite import Stack, live_settings, scenario  # noqa: F401
from test_unit_workers import context, result, unit

from bicentennial.canon import sha256_canon
from bicentennial.director.upstream.holds import Holds
from bicentennial.runner import t1, units
from bicentennial.runner.guard import Marker
from bicentennial.runner.lock import LockMismatch, attempt_id, lock_hash
from bicentennial.runner.probe_live import LatchStop, ProbeLiveLeg

_PREPARE = t1.prepare


def test_t2_only_refusals_are_discovered():
    shared = runpy.run_path(str(Path(__file__).resolve().parents[1] / "test_developer_doc.py"))
    assert units.T2_ONLY_REFUSALS <= shared["_code_refusals"]()


def test_t1_and_t2lite_never_raise_t2_only_on_busy(installed, scenario, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(10, False, "synthetic"))
    monkeypatch.setattr(t1, "prepare", _PREPARE)
    with pytest.raises(t1.T1Refused, match="^roots_below_min$"):
        prepare(installed, spec=units.T2_SPEC)
    assert prepare(installed).roots == 1
    original = t1.prepare
    called = []

    def preparing(**kw):
        # Exercise the spec actually selected by the T2-lite caller using real admission.
        ctx = original(system="hermes-native", entry=prepare_entry,
            packs=installed.root, pack_hash=installed.digest, worker_argv=installed.worker,
            spec=kw.get("spec", units.T1_SPEC))
        assert ctx.roots == 1
        called.append(ctx)
        return scenario.ctx

    prepare_entry = prepare(installed).entry
    monkeypatch.setattr(t1, "prepare", preparing)
    assert scenario.invoke() == 0
    assert len(called) == 1


def test_one_slot_uses_calling_thread_and_interrupt_unwinds(tmp_path):
    caller, seen = current_thread(), []
    live = units._Guard(Stack())

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        try:
            assert current_thread() is caller
            seen.append("body")
            raise KeyboardInterrupt
        finally:
            seen.append("finally")

    with pytest.raises(KeyboardInterrupt):
        units.schedule(context(1), [unit(tmp_path, "a")], live, execute=execute)
    assert seen == ["body", "finally"]
    assert live.stopped.is_set()


def test_two_slot_coordinator_interrupt_stops_at_boundary(tmp_path, monkeypatch):
    live = units._Guard(Stack())
    running, boundary, stopped = Event(), Event(), Event()
    seen, futures = [], []
    executor = units.ThreadPoolExecutor

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        seen.append(key)
        running.set()
        assert boundary.wait(5)
        assert live.stopped.wait(5)
        # A real session boundary uses this exact check, before spawning its worker.
        with pytest.raises(LatchStop):
            ProbeLiveLeg(live, None, None, None).check_session(None)
        stopped.set()
        return result(p, b, key, slot)

    class QueuedSecond(executor):
        def submit(self, function, *args):
            if futures:
                # Keep one admitted future unstarted until coordinator cancellation.
                future = units.Future()
            else:
                future = super().submit(function, *args)
            futures.append(future)
            return future

    def interrupt(active, **kw):
        assert running.wait(5)
        boundary.set()
        raise KeyboardInterrupt

    monkeypatch.setattr(units, "ThreadPoolExecutor", QueuedSecond)
    monkeypatch.setattr(units, "wait", interrupt)
    with pytest.raises(KeyboardInterrupt):
        units.schedule(context(2), [unit(tmp_path, k) for k in ("a", "b", "c")], live, execute=execute)
    assert live.stopped.is_set()
    assert futures[1].cancelled()
    assert seen == ["a"] and stopped.is_set()


def test_two_slot_spend_stop_reaches_other_session_boundary(tmp_path):
    stack, started, stopped = Stack(), Barrier(2), Event()
    live = units._Guard(stack)
    seen = []

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        seen.append(key)
        started.wait(timeout=5)
        if key == "a":
            stack.values["spend_stopped"] = True
            units._check_stop(live)
        assert live.stopped.wait(5)
        try:
            ProbeLiveLeg(live, None, None, None).check_session(None)
        except LatchStop:
            stopped.set()
            raise
        pytest.fail("spend stop did not stop the other unit")

    collected = units.schedule(context(2), [unit(tmp_path, k) for k in ("a", "b", "c")], live, execute=execute)
    assert sorted(seen) == ["a", "b"] and stopped.is_set()
    assert any(isinstance(e, LatchStop) for e in collected.errors)
    assert units.refusal_code(units.reduce_refusals(collected.errors)) == "spend_stop"
    with pytest.raises(t1.T1Refused, match="^spend_stop$"):
        collected.merge([], [])


def record_admission(monkeypatch, records):
    def attempts(ctx, p, b, role, scratch, live, runs, out, stops):
        digest, identity = ctx.gate.start_session(ctx.current_lock(), role, p.life, b, 1, 0)
        records.append(dict(role=role, digest=digest, identity=identity,
            lock=ctx.lock, pins=ctx.pins, current=ctx.current_lock()))
        return result(p, b, role, 0)

    monkeypatch.setattr(units, "_unit_attempts", attempts)


def test_two_system_arms_have_distinct_session_attempts_and_holds(installed, tmp_path, monkeypatch):  # noqa: F811
    ctx, records = prepare(installed), []
    record_admission(monkeypatch, records)
    p = ctx.packs[0]
    queue = [units.Unit(units.Arm.from_context(ctx, key), p, "B0", tmp_path / key, tmp_path / key / "out")
             for key in ("a", "b")]
    collected = units.schedule(ctx, queue, units._Guard(Stack()), roots=2)
    collected.merge([], [])
    identities = {r["identity"] for r in records}
    assert len(identities) == 2
    assert {r["role"] for r in records} == {"system"}
    assert identities == {attempt_id(lock_hash(ctx.lock), k, p.life, "B0", 1, 0) for k in ("a", "b")}
    holds = Holds()
    # Director passes the admitted attempt identity as Call.run_key to the live stack.
    for identity in identities:
        holds.hold(identity, "quota")
    assert len(holds.active) == 2
    holds.release(next(iter(identities)))
    assert len(holds.active) == 1
    # The serial role key retains precisely the original admission result.
    serial = units._ArmContext(ctx, units.Arm.from_context(ctx))
    assert serial.gate.start_session(serial.current_lock(), "system", p.life, "B0", 1, 0) == (
        ctx.gate.start_session(ctx.current_lock(), "system", p.life, "B0", 1, 0))


def test_two_arm_locks_and_pins_use_each_entry(installed, tmp_path, monkeypatch):  # noqa: F811
    ctx, records = prepare(installed), []
    record_admission(monkeypatch, records)
    entries = [ctx.entry | dict(artifact=ctx.entry["artifact"] | dict(sha256=d * 64),
                               read_tools=["read_" + d]) for d in ("a", "b")]
    arms = [replace(units.Arm.from_context(ctx, key), entry=entry)
            for key, entry in zip(("a", "b"), entries, strict=True)]
    queue = [units.Unit(a, ctx.packs[0], "B0", tmp_path / a.key, tmp_path / a.key / "out") for a in arms]
    collected = units.schedule(ctx, queue, units._Guard(Stack()), roots=2)
    collected.merge([], [])
    assert len({r["digest"] for r in records}) == 2
    for row in records:
        entry = next(e for e in entries if row["lock"]["system_artifacts"] == [e["artifact"]])
        expected = t1._lock(ctx.index, ctx.packs, entry, ctx.table, ctx.pack_hash)
        assert row["lock"] == row["current"] == expected
        assert row["digest"] == lock_hash(expected)
        assert row["pins"]["system_hash"] == sha256_canon([entry["artifact"]])
    own = units._ArmContext(ctx, arms[0])
    # Fresh checks must still detect a changed arm entry against its detached baseline.
    own.gate.start_session(own.current_lock(), "system", ctx.packs[0].life, "B0", 1, 0)
    monkeypatch.setitem(arms[0].entry, "read_tools", ["changed"])
    with pytest.raises(LockMismatch):
        own.gate.start_session(own.current_lock(), "system", ctx.packs[0].life, "B0", 2, 0)
