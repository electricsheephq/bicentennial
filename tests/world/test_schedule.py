"""Seeded schedule properties and offline K12/K13/G01 consumer contracts."""

import ast
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict, fields, replace
from fractions import Fraction
from pathlib import Path
from zoneinfo import available_timezones

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import choice, mint_id, uniform_int
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.world import create_world, tokens, unit, world_hash
from bicentennial.world import scale as scales
from bicentennial.world.scale import Scale, check, named
from bicentennial.world.schedule import (
    SessionPlan,
    build_schedule,
    ticks,
    write_sessions,
)

CANARY = "c168e5f8-3948-4553-8554-7aa162054723"


def contracts(schedule):
    points = schedule.fault_lite()
    validate("fault-lite", points)
    skeleton = {"canary": CANARY, "life_id": schedule.life, "genre": "G1", "harness": "hermes",
                "sessions": [{"index": s.index, "kind": "replay", "turns": [
                    {"n": n, "kind": "replay", "user": "A turn.", "assistant": None,
                     "tool_calls": []} for n in range(1, 6)]} for s in schedule.sessions]}
    assert FaultLite.load(points, skeleton).to_obj() == points
    for s in schedule.sessions:
        validate("session", {"canary": CANARY, "index": s.index, "kind": "work",
                             "wake_before": list(s.wake_before),
                             "fault_points": list(s.fault_points), "long_sprint": s.long_sprint,
                             "est_tokens": s.min_tokens, "probe_point": s.probe_point,
                             "expected_state": {"env_state_hash": "0" * 64,
                                                "repo_tree_hash": "0" * 64}})


def assert_timeline(schedule):
    assert schedule.tz == "Europe/Paris"
    assert schedule.sessions[0].t_start == 1_700_000_000
    assert schedule.sessions[0].gap_before_s is None
    assert [s.index for s in schedule.sessions] == list(range(1, schedule.scale.sessions + 1))
    key = canon([schedule.seed, schedule.life, "session"]).decode()
    for s in schedule.sessions:
        assert s.session_id == mint_id(key, s.index)
        assert s.t_end - s.t_start == 3_600
        assert s.turn_t == s.heartbeats == tuple(s.t_start + n for n in (0, 720, 1440, 2160, 2880))
        assert len(s.wake_before) <= 1
        if s.index > 1:
            assert s.t_start == schedule.sessions[s.index - 2].t_end + s.gap_before_s
            bounds = scales.LONG_GAP_S if "gap" in s.wake_before else scales.ORDINARY_GAP_S
            assert bounds[0] <= s.gap_before_s <= bounds[1]
            assert s.gap_before_s == uniform_int(
                schedule.seed, unit(schedule.life, "schedule", f"gap-{s.index}"),
                0, "seconds", *bounds)
        assert s.long_sprint == (s.kind == "sprint")
        assert s.min_tokens == (tokens.sprint_floor(schedule.scale.window) if s.long_sprint else 0)
    assert [s.index for s in schedule.sessions if s.probe_point] == list(schedule.scale.checkpoints)
    rows = schedule.fault_lite() + [dict(kind="gap", session=s.index, turn=None)
                                   for s in schedule.sessions if "gap" in s.wake_before]
    rows.sort(key=lambda r: (r["session"], r["turn"] is not None, r["turn"], r["kind"]))
    assert schedule.wakes() == [(r["kind"], r["session"], r["turn"]) for r in rows]
    for ranges, prefix, selected in [
        (schedule.scale.sprint_ranges, "sprint", [s.index for s in schedule.sessions if s.long_sprint]),
        (schedule.scale.long_gap_ranges, "long-gap",
         [s.index for s in schedule.sessions if "gap" in s.wake_before]),
    ]:
        fixed = (schedule.scale.kill, schedule.scale.swap, schedule.scale.restart, schedule.scale.compaction)
        expected = [choice(schedule.seed, unit(schedule.life, "schedule", f"{prefix}-{i}"),
                           0, "session", [k for k in range(lo, hi + 1) if k >= 2 and k not in fixed])
                    for i, (lo, hi) in enumerate(ranges)]
        assert selected == sorted(expected)


@pytest.mark.parametrize("name,count,kill,swap,sprints,gaps,floor", [
    ("t1", 20, 11, 15, 2, 2, 20_480), ("full", 200, 110, 150, 8, 4, 163_840),
])
def test_200_seeded_lives(name, count, kill, swap, sprints, gaps, floor):
    scale = named(name)
    for case in range(200):
        schedule = build_schedule(f"g02-{name}-{case}", "life-a", scale)
        assert len(schedule.sessions) == count
        assert sum(len(s.heartbeats) for s in schedule.sessions) == 5 * count
        assert_timeline(schedule)
        contracts(schedule)
        assert schedule.fault_lite() == [dict(kind="kill", session=kill, turn=1),
                                         dict(kind="swap", session=swap, turn=None)]
        sprint_indices = [s.index for s in schedule.sessions if s.long_sprint]
        gap_indices = [s.index for s in schedule.sessions if s.wake_before == ("gap",)]
        assert len(sprint_indices) == sprints
        assert len(gap_indices) == gaps
        assert not {1, kill, swap}.intersection(sprint_indices + gap_indices)
        assert schedule.sessions[swap - 1].wake_before == ("swap",)
        assert all(s.wake_before == () for s in schedule.sessions
                   if s.index not in gap_indices + [swap])
        assert all(s.min_tokens == floor for s in schedule.sessions if s.long_sprint)
        if name == "t1":
            for selected in (sprint_indices, gap_indices):
                assert 2 <= selected[0] <= 10
                assert selected[1] in (12, 13, 14, 16, 17, 18, 19, 20)
        else:
            assert [((s - 1) // 25) for s in sprint_indices] == list(range(8))
            assert all(lo <= k <= hi for k, (lo, hi) in zip(
                gap_indices, ((2, 20), (21, 60), (61, 120), (121, 200)), strict=True))
            span = schedule.sessions[-1].t_end - schedule.sessions[0].t_start
            assert 1_814_400 <= 3_841_200 <= span <= 15_699_600 <= 15_724_800


@pytest.mark.parametrize("count", [1, 2, 3])
def test_micro_without_wake(count):
    schedule = build_schedule("micro", "life-a", named("t0-micro", sessions=count))
    assert schedule.scale.checkpoints == (count,)
    assert schedule.fault_lite() == []
    assert all(s.wake_before == () for s in schedule.sessions)
    assert_timeline(schedule)
    contracts(schedule)


@pytest.mark.parametrize("count", [2, 3])
@pytest.mark.parametrize("wake", ["kill", "restart", "compaction", "swap", "gap"])
def test_micro_wake(count, wake):
    schedule = build_schedule("micro", "life-a", named("t0-micro", sessions=count, wake=wake))
    expected = [] if wake == "gap" else [dict(kind=wake, session=count, turn=1 if wake == "kill" else None)]
    assert schedule.fault_lite() == expected
    assert schedule.sessions[-1].wake_before == (() if wake == "kill" else (wake,))
    assert schedule.wakes() == [(wake, count, 1 if wake == "kill" else None)]
    assert_timeline(schedule)
    contracts(schedule)


@pytest.mark.parametrize("name,kwargs", [
    ("unknown", {}), ("t1", {"sessions": 5}), ("full", {"sessions": 20}),
    ("t0-micro", {"sessions": 4}), ("t0-micro", {"sessions": 0}), ("t0-micro", {}),
    ("t0-micro", {"sessions": True}), ("t0-micro", {"sessions": 2, "wake": "unknown"}),
    *[("t0-micro", {"sessions": 1, "wake": w}) for w in ("kill", "swap", "restart", "compaction", "gap")],
    *[(name, {"wake": w}) for name in ("t1", "full") for w in ("kill", "gap", "unknown")],
])
def test_named_refusals(name, kwargs):
    with pytest.raises(ValueError):
        named(name, **kwargs)


@pytest.mark.parametrize("base,changes", [
    ("t1", {"name": "unknown"}), ("t1", {"sessions": 5}), ("full", {"sessions": 199}),
    ("t0-micro", {"sessions": 4}), ("t0-micro", {"sessions": 0}),
    ("t1", {"sessions": 20.0}), ("t1", {"window": 24_576}),
    ("full", {"window": 16_384}), ("t0-micro", {"window": 1}),
    ("t1", {"checkpoints": (20,)}), ("full", {"checkpoints": (200,)}),
    ("t0-micro", {"checkpoints": (1,)}), ("t1", {"kill": 10}),
    ("full", {"kill": 109}), ("t1", {"swap": 14}), ("full", {"swap": 149}),
    ("t1", {"restart": 20}), ("full", {"compaction": 200}),
    ("t1", {"compaction": 20}), ("full", {"restart": 200}), ("t1", {"kill": 11.0}),
    ("t1", {"sprint_ranges": ((2, 5), (6, 10))}),
    ("t1", {"sprint_ranges": ((2, 5), (6, 10), (12, 20))}),
    ("t1", {"sprint_ranges": ((2, 12), (13, 20))}),
    ("t1", {"sprint_ranges": ((2, 10), (10, 20))}),
    ("t1", {"sprint_ranges": ((0, 10), (12, 20))}),
    ("t1", {"sprint_ranges": ((2, 10), (12, 21))}),
    ("t1", {"sprint_ranges": ((10, 2), (12, 20))}),
    ("t1", {"sprint_ranges": ((1, 1), (12, 20))}),
    ("t1", {"sprint_ranges": ((11, 11), (12, 20))}),
    ("t1", {"long_gap_ranges": ((1, 1),)}),
    ("t1", {"long_gap_ranges": ((15, 15),)}),
    ("t1", {"long_gap_ranges": ((2, 5), (5, 10))}),
    ("t1", {"long_gap_ranges": ((2, 21),)}),
    ("t1", {"sprint_ranges": ((2,), (12, 20))}),
    ("t1", {"sprint_ranges": [[2, 10], [12, 20]]}),
    ("t1", {"sprint_ranges": ((2.0, 10), (12, 20))}),
    ("full", {"sprint_ranges": tuple((k, k + 24) for k in range(1, 201, 25) if k != 76)}),
    ("full", {"sprint_ranges": ((2, 5), (6, 10), (26, 50), (51, 75), (101, 125),
                                (126, 150), (151, 175), (176, 200))}),
    ("full", {"long_gap_ranges": tuple((k, k) for k in range(2, 14))}),
    ("full", {"long_gap_ranges": ()}),
    ("t0-micro", {"kill": 2, "swap": 2}),
    ("t0-micro", {"restart": 2, "long_gap_ranges": ((2, 2),)}),
    ("t0-micro", {"kill": 1}), ("t0-micro", {"swap": 3}),
    ("t0-micro", {"restart": 1}), ("t0-micro", {"compaction": 1}),
    ("t0-micro", {"long_gap_ranges": ((1, 2),)}),
    ("t0-micro", {"sprint_ranges": ((2, 2),)}),
    ("t0-micro", {"sessions": 1, "checkpoints": (1,), "kill": 1}),
    ("t0-micro", {"sessions": 1, "checkpoints": (1,), "long_gap_ranges": ((1, 1),)}),
])
def test_check_and_build_refusals(base, changes):
    scale = replace(named(base, **({"sessions": 2} if base == "t0-micro" else {})), **changes)
    with pytest.raises(ValueError):
        check(scale)
    with pytest.raises(ValueError):
        build_schedule("seed", "life-a", scale)


def test_preset_fields_constants_and_frozen_shapes():
    assert scales.WORLD_TZ in available_timezones()
    assert scales.SPRINT_FACTOR == Fraction(5, 4)
    assert scales.DECOY_MIN_RATIO == 3
    assert scales.PROVISIONAL == {
        "span": "provisional pending PREREG-v0.5", "decoy_ratio": "provisional pending PREREG-v0.5",
        "dev_window": "provisional C-5", "full_window": "illustrative; C-4 open",
        "heartbeat_s": "provisional; no PREREG value"}
    assert (scales.TURNS, scales.SESSION_S, scales.TURN_S, scales.HEARTBEAT_S, scales.BLOCK) == (5, 3600, 720, 720, 25)
    for name, count in (("t1", 20), ("full", 200)):
        scale = named(name)
        assert scale == named(name, sessions=count)
        assert scale.restart is scale.compaction is None
        assert scale.kill == -(-11 * count // 20)
        assert scale.swap == -(-3 * count // 4)
        assert scale.long_gap_ranges == (((1, 10), (11, 20)) if count == 20 else
                                         ((1, 20), (21, 60), (61, 120), (121, 200)))
        with pytest.raises(FrozenInstanceError):
            scale.sessions = 1
    with pytest.raises(TypeError):
        Scale("t1")


def test_ticks_half_open_and_invalid_intervals():
    assert ticks(10, 20, 3) == [10, 13, 16, 19]
    assert ticks(10, 20, 10) == [10]
    assert ticks(10, 10, 1) == []
    for interval in (0, -1, 1.0, True):
        with pytest.raises(ValueError):
            ticks(10, 20, interval)


def test_wire_shape_is_detached_and_every_field_is_present():
    schedule = build_schedule("wire", "life-a", named("t1"))
    obj = schedule.to_obj()
    assert set(obj) == {"seed", "life", "tz", "estimator", "scale", "sessions"}
    assert set(obj["scale"]) == {f.name for f in fields(Scale)}
    assert set(obj["sessions"][0]) == {f.name for f in fields(SessionPlan)}
    assert obj["estimator"] == tokens.ESTIMATOR
    assert obj["scale"] == json.loads(canon(asdict(schedule.scale)))
    assert obj["sessions"] == json.loads(canon([asdict(s) for s in schedule.sessions]))
    assert schedule.to_json() == canon(obj)
    before = schedule.to_json()
    obj["estimator"]["name"] = "changed"
    obj["sessions"][10]["fault_points"][0]["kind"] = "changed"
    schedule.fault_lite()[0]["kind"] = "changed"
    assert schedule.to_json() == before
    for value, field in ((schedule, "tz"), (schedule.sessions[0], "kind")):
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, "changed")


def test_200_seeded_keyed_gap_independence():
    for case in range(200):
        seed = f"g02-independent-{case}"
        small = build_schedule(seed, "life-a", named("t1"))
        full = build_schedule(seed, "life-a", named("full"))
        for a, b in zip(small.sessions[1:], full.sessions[1:20], strict=True):
            if "gap" not in a.wake_before and "gap" not in b.wake_before:
                assert a.gap_before_s == b.gap_before_s


def child(code, *args, hashseed="0"):
    return subprocess.check_output([sys.executable, "-c", code, *args],
                                   env=dict(os.environ, PYTHONHASHSEED=hashseed), timeout=30)


@pytest.mark.parametrize("name", ["t1", "full"])
def test_schedule_bytes_across_processes_and_seeds(name):
    code = ("import sys; from bicentennial.world.schedule import build_schedule; "
            "from bicentennial.world.scale import named; "
            "sys.stdout.buffer.write(build_schedule(sys.argv[2], 'life-a', named(sys.argv[1])).to_json())")
    first = child(code, name, "deterministic")
    assert first == child(code, name, "deterministic", hashseed="random")
    assert first != child(code, name, "different")


def meta(seed="world-seed", scale=20):
    return dict(generator_version="g02-test", genre="G1", seed=seed, scale=scale)


def test_world_rows_transaction_and_hash_include_sessions(tmp_path):
    schedule = build_schedule("world-seed", "life-a", named("t1"))
    with create_world(tmp_path / "world.db", meta()) as db:
        before = world_hash(db)
        write_sessions(db, schedule)
        assert db.in_transaction
        expected = [(s.index, s.t_start, s.t_end, s.kind) for s in schedule.sessions]
        assert [tuple(r) for r in db.execute("SELECT idx,t_start,t_end,kind FROM session ORDER BY idx")] == expected
        assert world_hash(db) != before
        db.commit()
        assert not db.in_transaction
        assert [tuple(r) for r in db.execute("SELECT idx,t_start,t_end,kind FROM session ORDER BY idx")] == expected


@pytest.mark.parametrize("changes", [{"seed": "wrong"}, {"scale": 200}])
def test_world_meta_mismatch_refused_before_writes(tmp_path, changes):
    with create_world(tmp_path / "world.db", meta(**(dict(seed="world-seed", scale=20) | changes))) as db:
        with pytest.raises(ValueError):
            write_sessions(db, build_schedule("world-seed", "life-a", named("t1")))
        assert db.execute("SELECT count(*) FROM session").fetchone()[0] == 0
        assert not db.in_transaction


def test_world_hash_across_processes(tmp_path):
    code = """
import sys
from bicentennial.world import create_world, world_hash
from bicentennial.world.schedule import build_schedule, write_sessions
from bicentennial.world.scale import named
db = create_world(sys.argv[1], dict(generator_version='g02-test', genre='G1', seed='world-seed', scale=20))
write_sessions(db, build_schedule('world-seed', 'life-a', named('t1')))
db.commit()
print(world_hash(db))
db.close()
"""
    assert child(code, str(tmp_path / "a.db")) == child(code, str(tmp_path / "b.db"), hashseed="random")


def test_generator_import_boundary():
    banned = {"random", "time", "socket", "ssl", "http", "urllib", "bicentennial.sandbox"}
    root = Path(scales.__file__).parent
    for name in ("tokens.py", "scale.py", "schedule.py"):
        for node in ast.walk(ast.parse((root / name).read_text())):
            names = ([n.name for n in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == b or n.startswith(b + ".") for n in names for b in banned)
