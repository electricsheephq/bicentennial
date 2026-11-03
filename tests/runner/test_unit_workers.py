"""Worker scheduling, shared floors, deterministic collection and cause preservation."""

import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from itertools import permutations
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest
from test_t1 import environment, installed, prepare  # noqa: F401
from test_t2lite import Stack, live_settings, scenario  # noqa: F401

from bicentennial.runner import t1, t2lite, units
from bicentennial.runner.guard import Marker
from bicentennial.runner.life import LifeRun
from bicentennial.runner.probe_live import LatchStop, LiveCredentialStop, LiveStop


def context(roots=2):
    return SimpleNamespace(roots=roots, entry={"name": "hermes-native"}, plugin_source=None,
                           model_cache=None, worker_argv=None)


def pack(life="life", probes=1, replay=10):
    return SimpleNamespace(life=life, schedule=SimpleNamespace(sessions=range(replay)),
                           items={b: [None] * probes for b in ("B0", "B1")})


def arm(key="system", plugin=False):
    return units.Arm(key, {"name": "holographic" if plugin else "hermes-native"})


def unit(tmp_path, key, p=None, branch="B0", plugin=False):
    a = arm(key, plugin)
    return units.Unit(a, p or pack(), branch, tmp_path / key / "scratch", tmp_path / key / "out")


def result(p, branch, key, slot):
    run = LifeRun(key, p.life, branch, 0)
    return units.UnitResult({key: {"score": 1000}}, [{"arm": key}], True, (run,), 1, None,
                            {"arm": key, "slot": slot, "attempts": 1})


def test_bounded_slots_reverse_completion_fixed_merge(tmp_path):
    queue = [unit(tmp_path, str(i)) for i in range(3)]
    entered, release, ended = Barrier(4), [Event() for _ in queue], [Event() for _ in queue]
    active, maximum, slots, finish = 0, 0, set(), []
    lock = Lock()

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            assert slot not in slots
            slots.add(slot)
        entered.wait(timeout=5)
        assert release[int(key)].wait(5)
        with lock:
            slots.remove(slot)
            active -= 1
            finish.append(key)
        ended[int(key)].set()
        return result(p, b, key, slot)

    with ThreadPoolExecutor(1) as controller:
        future = controller.submit(units.schedule, context(3), queue, units._Guard(Stack()), execute=execute)
        entered.wait(timeout=5)
        for i in (2, 1, 0):
            release[i].set()
            assert ended[i].wait(5)
        collected = future.result(timeout=10)
    runs, timings = [], []
    values = collected.merge(runs, timings)
    assert maximum == 3 and not active and finish == ["2", "1", "0"]
    assert list(values) == [u.identity for u in queue]
    assert [r.arm for r in runs] == ["0", "1", "2"]
    assert [t["arm"] for t in timings] == ["0", "1", "2"]
    assert sorted(t["slot"] for t in timings) == [0, 1, 2]
    assert [v.probes[0]["arm"] for v in values.values()] == ["0", "1", "2"]


def test_ready_plugin_waits_for_shared_floor_nonplugin_can_start(tmp_path):
    p = pack()
    floor = replace(arm(), key="no_memory", role="no_memory")
    queue = [unit(tmp_path, "plugin", p, plugin=True),
             units.Unit(floor, p, "B0", tmp_path / "floor", tmp_path / "floor-out"),
             unit(tmp_path, "native", p)]
    native_started, floor_started, finish_floor = Event(), Event(), Event()
    events = []

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        events.append((key, "start"))
        if key == "no_memory":
            floor_started.set()
            assert finish_floor.wait(5)
        elif key == "native":
            native_started.set()
            assert finish_floor.wait(5)
        else:
            assert ("no_memory", "end") in events
            assert p.life + b in stops
        events.append((key, "end"))
        return result(p, b, key, slot)

    with ThreadPoolExecutor(1) as controller:
        future = controller.submit(units.schedule, context(), queue, units._Guard(Stack()), execute=execute)
        assert floor_started.wait(5) and native_started.wait(5)
        finish_floor.set()
        collected = future.result(timeout=10)
    assert not collected.errors
    assert set(collected.results) == {u.identity for u in queue}
    assert events.count(("no_memory", "start")) == 1
    cached = units.schedule(context(1), queue[:1], units._Guard(Stack()),
                            floor_stops={p.life + "B0": None}, execute=execute)
    assert len(cached.results) == 1 and not cached.errors


def test_longest_ready_first_ties_in_card_order(tmp_path):
    queue = [unit(tmp_path, "short", pack("s", 1)), unit(tmp_path, "long-a", pack("a", 4)),
             unit(tmp_path, "long-b", pack("b", 4))]
    seen = []

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        seen.append(key)
        assert slot == 0
        return result(p, b, key, slot)

    collected = units.schedule(context(1), queue, units._Guard(Stack()), spec=units.T2_SPEC, execute=execute)
    assert not collected.errors
    assert seen == ["long-a", "long-b", "short"]
    assert units.predicted_seconds(queue[1]) == 10 * 43 + 4 * 49
    assert list(collected.results) == [u.identity for u in queue]


def test_two_arms_one_shared_floor_and_identity_paths(tmp_path):
    ctx = context()
    ctx.packs = [pack()]
    # The artifacts differ while the entry names are identical.
    arms = [replace(arm("a"), plugin_source="artifact-a"), replace(arm("b"), plugin_source="artifact-b")]
    queue = units.make_units(ctx, arms, tmp_path / "scratch", tmp_path / "out")
    seen = []

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        assert scratch == tmp_path / "scratch" / key / p.life / b
        assert out == tmp_path / "out" / key / p.life / b
        seen.append((key, b, config.plugin_source))
        return result(p, b, key, slot)

    collected = units.schedule(ctx, queue, units._Guard(Stack()), execute=execute)
    assert not collected.errors
    assert len(collected.results) == 6 and len(seen) == 6
    assert [k for k, b, src in seen].count("no_memory") == 2
    for u in queue:
        assert collected.results[u.identity].runs[0].arm == u.arm.key
    with pytest.raises(ValueError, match="duplicate"):
        units.make_units(ctx, [arms[0], arms[0]], tmp_path, tmp_path)


@pytest.mark.parametrize("code", ["isolation", "gate_refused", "credential_stop", "spend_stop", "crash"])
@pytest.mark.parametrize("order", list(permutations(range(2))))
def test_secondary_stop_never_outranks_cause(code, order):
    error = {"isolation": t1.T1Refused("isolation"), "gate_refused": t1.GateRefused("busy"),
             "credential_stop": LiveCredentialStop("upstream_401"), "spend_stop": t1.T1Refused("spend_stop"),
             "crash": RuntimeError("unexpected crash")}[code]
    errors = [error, LatchStop("stopped")]
    chosen = units.reduce_refusals(errors[i] for i in order)
    assert chosen is error
    if code != "crash":
        assert units.refusal_code(chosen) == code
    else:
        # A crash also wins against an independently raised real stop.
        assert units.reduce_refusals([LiveStop("real"), chosen]) is error


@pytest.mark.parametrize("order", list(permutations(range(3))))
def test_all_workers_finish_partial_runs_and_no_new_start(tmp_path, order):
    queue = [unit(tmp_path, str(i)) for i in range(4)]
    entered = Barrier(4)
    release, ended = [Event() for _ in range(3)], [Event() for _ in range(3)]
    live = units._Guard(Stack())
    seen = []

    def execute(ctx, p, b, key, scratch, live, out, stops, *, slot, config):
        i = int(key)
        seen.append(i)
        assert i < 3
        entered.wait(timeout=5)
        if i == 0:
            with live.launch:
                live.stopped.set()
        assert live.stopped.wait(5)
        assert release[i].wait(5)
        ended[i].set()
        error = t1.T1Refused("isolation") if i == 0 else LatchStop("stopped")
        raise units.UnitRefusal(error, (LifeRun(key, p.life, b, 0),), {"arm": key, "slot": slot})

    with ThreadPoolExecutor(1) as controller:
        future = controller.submit(units.schedule, context(3), queue, live, execute=execute)
        entered.wait(timeout=5)
        assert live.stopped.wait(5)
        for i in order:
            release[i].set()
            assert ended[i].wait(5)
        collected = future.result(timeout=10)
    runs, timings = [], []
    with pytest.raises(t1.T1Refused, match="isolation"):
        collected.merge(runs, timings)
    assert sorted(seen) == [0, 1, 2]
    assert [r.arm for r in runs] == ["0", "1", "2"]
    assert [t["arm"] for t in timings] == ["0", "1", "2"]


@pytest.mark.parametrize("cause_code", ["isolation", "gate_refused", "credential_stop", "crash"])
def test_pool_unobserved_egress_publishes_isolation(scenario, monkeypatch, cause_code):  # noqa: F811
    original = t2lite.schedule
    boundary = Barrier(2)
    stopped = Event()

    def parallel(ctx, queue, live, **kw):
        a = queue[0]
        b = replace(a, arm=replace(a.arm, key="second", role="system"), scratch=a.scratch / "second", out=a.out / "second")

        def execute(ctx, p, branch, key, scratch, live, out, stops, *, slot, config):
            boundary.wait(timeout=5)
            try:
                if key == a.arm.key:
                    if cause_code == "isolation":
                        units._isolation(LifeRun(key, p.life, branch, 0, egress={"unsampled": ["synthetic worker"]}))
                    if cause_code == "gate_refused":
                        raise t1.GateRefused("busy")
                    if cause_code == "credential_stop":
                        raise LiveCredentialStop("upstream_401")
                    raise RuntimeError("unexpected crash")
                assert stopped.wait(5)
                units._check_stop(live)
            except Exception as error:
                with live.launch:
                    live.stopped.set()
                stopped.set()
                raise units.UnitRefusal(error, (LifeRun(key, p.life, branch, 0),),
                    dict(life=p.life, branch=branch, arm=key, slot=slot, start_ms=0, end_ms=1, attempts=1)) from error

        return original(ctx, [a, b], live, roots=2, execute=execute)

    monkeypatch.setattr(t2lite, "schedule", parallel)
    assert scenario.invoke() == (70 if cause_code == "crash" else 3)
    assert t2lite._read(scenario.out, "refusal.json") == {
        "code": "tool_failure" if cause_code == "crash" else cause_code}
    if cause_code == "credential_stop":
        receipt = t2lite._read(scenario.out, "receipt.json")
        assert [u["arm"] for u in receipt["units"]] == ["no_memory", "second"]


def test_unexpected_cause_survives_collector_and_exit70(scenario, monkeypatch, capsys):  # noqa: F811
    cause = ValueError("original diagnostic")

    def crash(**kw):
        raise RuntimeError("unit crash") from cause

    monkeypatch.setattr(units, "run_life", crash)
    scenario.ctx.turn_wait_s = 3.0
    p = scenario.ctx.packs[0]
    runs, timings = [], []
    with pytest.raises(RuntimeError, match="unit crash") as caught:
        t2lite._collect_unit(runs, timings, scenario.ctx, p, "B0", "system", scenario.out / "s",
                             units._Guard(Stack()), scenario.out / "o")
    assert caught.value.__cause__ is cause
    assert "original diagnostic" in "".join(traceback.format_exception(caught.value))
    assert len(timings) == 1
    assert scenario.invoke() == 70
    assert t2lite._read(scenario.out, "refusal.json") == {"code": "tool_failure"}
    assert "original diagnostic" in capsys.readouterr().err


def test_t2_busy_refuses_before_expensive_preparation(installed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(10, False, "synthetic"))
    monkeypatch.setattr(t1, "prepare_cache", lambda *a: pytest.fail("cache preparation"))
    monkeypatch.setattr(t1, "worker_properties", lambda *a: pytest.fail("worker built"))
    monkeypatch.setattr(t1, "_pack", lambda *a: pytest.fail("pack built"))
    with pytest.raises(t1.T1Refused, match="roots_below_min"):
        prepare(installed, spec=units.T2_SPEC)


def test_t2_idle_roots_and_pack_refusal_order(installed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(0, False, "synthetic"))
    with pytest.raises(t1.T1Refused, match="^tier$"):
        prepare(installed, spec=units.T2_SPEC)
    verify = t1.verify

    def t2_index(*a, **kw):
        return verify(*a, **kw) | {"tier": "T2"}

    monkeypatch.setattr(t1, "verify", t2_index)
    with pytest.raises(t1.T1Refused, match="tier_composition"):
        prepare(installed, spec=units.T2_SPEC)
    # Keep the real T1 fixture; only the composition is shortened for the admission test.
    assert prepare(installed, spec=replace(units.T2_SPEC, composition=("G1", "G2"))).roots == 8
    assert units.T2_SPEC.composition == ("G1",) * 5 + ("G2",) * 5


def test_actual_unit_failure_latches_before_next_start(tmp_path, monkeypatch):
    seen = []

    def attempts(ctx, p, b, role, scratch, live, runs, out, stops):
        seen.append(p.life)
        raise t1.T1Refused("isolation")

    monkeypatch.setattr(units, "_unit_attempts", attempts)
    queue = [unit(tmp_path, "a", pack("first")), unit(tmp_path, "b", pack("second"))]
    collected = units.schedule(context(1), queue, units._Guard(Stack()))
    assert seen == ["first"]
    assert len(collected.errors) == 1
    with pytest.raises(t1.T1Refused, match="isolation"):
        collected.merge([], [])


def test_arm_settings_role_slot_and_attempt_scratch(scenario, tmp_path, monkeypatch):  # noqa: F811
    ctx = scenario.ctx
    ctx.turn_wait_s = 3.0
    original, seen = units.run_life, []
    argv = ["synthetic-worker"]
    config = units.Arm("candidate", {"name": "hermes-native"}, "candidate-artifact", None,
                       lambda life, branch, role: argv)

    def drive(**kw):
        seen.append(kw)
        return original(**kw)

    monkeypatch.setattr(units, "run_life", drive)
    value = units._unit(ctx, ctx.packs[0], "B0", config.key, tmp_path / config.key,
                       units._Guard(Stack()), tmp_path / "out", slot=3, config=config)
    assert value.timing["slot"] == 3 and value.timing["arm"] == "candidate"
    assert value.runs[0].arm == "candidate"
    assert seen[0]["entry"] == config.entry and seen[0]["plugin_source"] == "candidate-artifact"
    assert seen[0]["worker_argv"] == argv and seen[0]["arm"] == "system"
    assert seen[0]["scratch"] == tmp_path / "candidate" / "0"
