"""Hand-derived schedule fixtures from SPEC-B §B1.7."""

import re
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from bicentennial.keyed import draw, shuffle, uniform_int
from bicentennial.ocsim.schedule import (
    BRANCHES,
    CAUSES,
    KINDS,
    LANES,
    PROBE_ONLY,
    STATUSES,
    STRESS_FACTOR,
    SYSTEM,
    Capacity,
    Draws,
    Layout,
    LifeSpec,
    PassOverRates,
    Release,
    Row,
    ScheduleDesign,
    Segment,
    chain_slots,
    draw_all,
    layout,
    prepare,
    project,
    session_ms,
    slow_rows,
    unit_times,
)
from bicentennial.runner.occupancy import Breach, LaneCapacity
from bicentennial.runner.projection import LIFE_BOUND_MS

H = 3_600_000
P0, P1 = "pair-000", "pair-001"


@pytest.fixture
def f1():
    return ScheduleDesign(
        (
            LifeSpec(P0, (1000, 2000, 1000), (2000, 1000), 2, 3, (1000, 0), (0, 0)),
            LifeSpec(P1, (1000, 1000, 1000), (1000, 1000), 2, 3, (0, 0), (0, 0)),
        ),
        (Row("A", 3600),), (2, 3), Capacity(2, 2), PassOverRates(0, 0), 0,
    )


@pytest.fixture
def draws():
    return Draws({P0: ("A", "S"), P1: ("A", "S")}, ("A",), {}, frozenset(), "fake", 1)


def hours(*values):
    return tuple(int(Fraction(value) * H) for value in values)


def sends(schedule, row, pair):
    return tuple(schedule.sent[row, pair, branch, c] for branch in BRANCHES for c in (2, 3))


def releases(schedule, pair):
    return tuple(schedule.controls[pair, branch, c].release_ms
                 for branch in BRANCHES for c in (2, 3))


def changed_life(design, **fields):
    return replace(design, lives=(replace(design.lives[0], **fields), *design.lives[1:]))


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def test_api_and_frozen_records(f1, draws):
    assert KINDS == ("base", "stress_slow", "stress_fast")
    assert BRANCHES == ("B0", "B1")
    assert LANES == ("pinned", "swap")
    assert PROBE_ONLY == ("C", "F")
    assert SYSTEM == "S"
    assert STRESS_FACTOR == Fraction(3, 2)
    assert CAUSES == ("start_window", "life_bound", "failed", "blocked")
    assert STATUSES == ("OK", "SYSTEM_FAILURE", "BLOCKED")
    prepared = prepare(f1)
    schedule = project(prepared, "base", draws)
    records = (f1, f1.lives[0], f1.rows[0], f1.capacity, f1.passover, prepared,
               draws, prepared.layouts["A", False, P0], schedule,
               schedule.arm_lives["A", P0], schedule.controls[P0, "B0", 2],
               prepared.layouts["A", False, P0].b0[0])
    for record in records:
        field = next(iter(record.__dataclass_fields__))
        with pytest.raises(FrozenInstanceError):
            setattr(record, field, getattr(record, field))


def test_f1_keyed_dispatch_order():
    for pair in (P0, P1):
        for branch in BRANCHES:
            for c in (2, 3):
                order = sorted(("A", "S"), key=lambda arm, pair=pair, branch=branch, c=c: (
                    draw("fake", (pair, branch, str(c), arm), 0, "dispatch"), arm
                ))
                assert order == (["S", "A"] if pair == P1 and branch == "B0"
                                 else ["A", "S"])


def test_f1_layout(f1):
    prepared = prepare(f1)
    assert prepared.design.system_rate == 3600
    assert f1.system_rate is None
    assert layout(prepared, "A", P0, False) == Layout(
        (Segment("pinned", 1, 2, 4 * H, ((1, 0), (2, H)), ((2, 3 * H),)),
         Segment("swap", 3, 3, H, ((3, 0),), ((3, H),))),
        (Segment("pinned", 2, 2, 2 * H, ((2, 0),), ((2, 2 * H),)),
         Segment("swap", 3, 3, H, ((3, 0),), ((3, H),))),
        5 * H,
    )
    assert layout(prepared, "A", P1, False).own_ms == 3 * H
    assert layout(prepared, "S", P0, True).own_ms == 27_000_000
    assert layout(prepared, "S", P1, True).own_ms == 9 * H // 2
    assert len(prepared.layouts) == 2 * 2 * 2


def test_f1_base(f1, draws):
    schedule = project(prepare(f1), "base", draws)
    assert schedule.block_first == (0, 6 * H)
    for row in ("A", "S"):
        assert sends(schedule, row, P0) == hours(3, 5, 6, 7)
        assert sends(schedule, row, P1) == hours(8, 9, 9, 10)
    for (pair, branch, c), release in schedule.controls.items():
        followed = "S" if pair == P1 and branch == "B0" else "A"
        arrival = schedule.sent[followed, pair, branch, c]
        assert release == Release(arrival, followed, arrival, 0, False)
    assert schedule.t1_ms == 10 * H
    assert schedule.slow == frozenset()
    assert set(schedule.system.values()) == {"OK"}
    assert schedule.post_swap == {(pair, c): c == 3 for pair in (P0, P1) for c in (2, 3)}
    for record in schedule.arm_lives.values():
        assert record.cause is None
        assert record.label is None
        assert record.breach == Breach(None, None, None)
        assert record.end_ms is None
        assert record.last_ms == (7 * H if record.life == P0 else 10 * H)
    times = unit_times(schedule)
    expected = (Fraction(9 * H, 2), Fraction(6 * H), Fraction(17 * H, 2), Fraction(19 * H, 2))
    assert expected[0] == Fraction(16_200_000)
    for arm in ("C", "F", "S"):
        assert tuple(times[arm, pair, c] for pair in (P0, P1) for c in (2, 3)) == expected
    assert all(isinstance(t, Fraction) for t in times.values())


def test_f1_stress_slow(f1, draws):
    # At 4H A.B1 (0,1,0) beats S.B1 (0,1,1) and pair-001.
    # At 6H S.B1 (0,1,1) and pair-001 A.B0 (1,0,0) take the two free slots.
    # At 8H S.B0 (1,0,1) beats A.B1 (1,1,0): B0 first.
    # Pair-001 A.B1 starts at 9H, and S.B1 at 10H.
    schedule = project(prepare(f1), "stress_slow", draws)
    assert schedule.slow == frozenset({"S"})
    assert schedule.block_first == (0, 6 * H)
    assert schedule.t1_ms == 13 * H
    assert sends(schedule, "S", P0) == hours("4.5", "7.5", 9, "10.5")
    assert sends(schedule, "S", P1) == hours(11, "12.5", "11.5", 13)
    assert sends(schedule, "A", P0) == hours(3, 5, 6, 7)
    assert sends(schedule, "A", P1) == hours(8, 9, 10, 11)
    assert schedule.controls[P1, "B0", 2] == Release(11 * H, "S", 11 * H, 0, False)
    assert schedule.controls[P1, "B1", 2] == Release(10 * H, "A", 10 * H, 0, False)
    assert schedule.controls[P1, "B1", 3] == Release(11 * H, "A", 11 * H, 0, False)


def test_f1_stress_fast(f1, draws):
    schedule = project(prepare(f1), "stress_fast", draws)
    assert schedule.slow == frozenset({"A"})
    assert schedule.block_first == (0, 7 * H)
    assert schedule.t1_ms == 13 * H
    assert sends(schedule, "A", P0) == hours("4.5", "7.5", 7, "8.5")
    assert sends(schedule, "S", P0) == hours(3, 5, 8, 9)
    assert sends(schedule, "A", P1) == hours(10, "11.5", "11.5", 13)
    assert sends(schedule, "S", P1) == hours(10, 11, 11, 12)
    assert releases(schedule, P0) == hours("4.5", "7.5", 7, "8.5")
    assert releases(schedule, P1) == hours(10, 11, "11.5", 13)
    assert tuple(r.followed for r in schedule.controls.values()) == (
        "A", "A", "A", "A", "S", "S", "A", "A"
    )


def f3(f1, order, b_rate=3600, system_rate=3600):
    design = replace(f1, lives=(f1.lives[1],), rows=(Row("A", 3600), Row("B", b_rate)),
                     capacity=Capacity(1, 1), system_rate=system_rate)
    design = changed_life(design, life=P0)
    draws = Draws({P0: order}, ("A", "B"), {}, frozenset(), "fake", 0)
    return project(prepare(design), "base", draws)


def test_f3_keyed_dispatch_order():
    for branch in BRANCHES:
        for c, expected in ((2, ["A", "B", "S"]), (3, ["A", "S", "B"])):
            assert sorted(("A", "B", "S"), key=lambda arm, branch=branch, c=c: (
                draw("fake", (P0, branch, str(c), arm), 0, "dispatch"), arm
            )) == expected


def assert_breach(schedule, row, cause, label, first, end, own):
    record = schedule.arm_lives[row, P0]
    assert record.cause == cause
    assert record.label == label
    assert record.first_ms == first
    assert record.end_ms == end
    assert record.last_ms == (None if first is None else end)
    assert record.own_ms == own
    assert record.breach == Breach(cause, label, end)


def test_f3_v1(f1):
    schedule = f3(f1, ("A", "S", "B"), system_rate=46_800)
    assert_breach(schedule, "A", "life_bound", "BLOCKED", 0, 24 * H, 3 * H)
    assert_breach(schedule, "S", "life_bound", "SYSTEM_FAILURE", 2 * H, 26 * H, 39 * H)
    assert_breach(schedule, "B", "start_window", "BLOCKED", None, 24 * H, 3 * H)
    assert schedule.arm_lives["S", P0].breach.bound_ms == 93_600_000
    assert set(schedule.system.values()) == {"SYSTEM_FAILURE"}
    assert unit_times(schedule)["S", P0, 2] is None
    assert unit_times(schedule)["S", P0, 3] is None
    assert releases(schedule, P0) == hours(2, 3, 26, 26)
    assert schedule.block_first == (0,)
    assert schedule.t1_ms == 26 * H
    for c in (2, 3):
        assert schedule.controls[P0, "B1", c] == Release(26 * H, None, None, 0, True)
        assert schedule.controls[P0, "B0", c] == Release(c * H, "A", c * H, 0, False)


def test_f3_v2(f1):
    schedule = f3(f1, ("S", "B", "A"), b_rate=46_800)
    assert_breach(schedule, "S", "life_bound", "BLOCKED", 0, 24 * H, 3 * H)
    assert_breach(schedule, "B", "life_bound", "SYSTEM_FAILURE", 2 * H, 26 * H, 39 * H)
    assert_breach(schedule, "A", "start_window", "BLOCKED", None, 24 * H, 3 * H)
    for c in (2, 3):
        assert schedule.system[P0, "B0", c] == "OK"
        assert schedule.system[P0, "B1", c] == "BLOCKED"
        assert unit_times(schedule)["S", P0, c] == Fraction(c * H)
        assert schedule.controls[P0, "B1", c] == Release(26 * H, None, None, 0, True)
    assert schedule.controls[P0, "B0", 2] == Release(26 * H, "S", 2 * H, 24 * H, False)
    assert schedule.controls[P0, "B0", 3] == Release(24 * H, "S", 3 * H, 21 * H, False)
    assert unit_times(schedule)["C", P0, 2] == Fraction(26 * H)
    assert unit_times(schedule)["C", P0, 3] == Fraction(25 * H)


def test_f3_v3(f1):
    schedule = f3(f1, ("A", "B", "S"), b_rate=46_800)
    assert_breach(schedule, "S", "start_window", "BLOCKED", None, 24 * H, 3 * H)
    assert_breach(schedule, "A", "life_bound", "BLOCKED", 0, 24 * H, 3 * H)
    assert_breach(schedule, "B", "life_bound", "SYSTEM_FAILURE", 2 * H, 26 * H, 39 * H)
    assert set(schedule.system.values()) == {"BLOCKED"}
    assert releases(schedule, P0) == hours(2, 3, 26, 26)
    for c in (2, 3):
        assert schedule.controls[P0, "B0", c].followed == "A"
        assert schedule.controls[P0, "B1", c].unmatched


def test_f2_swap_stop_and_ready_cancellation(f1, draws):
    draws = replace(draws, stops={("S", P0): ("failed", 3), ("A", P1): ("blocked", 2)})
    schedule = project(prepare(f1), "base", draws)
    record = schedule.arm_lives["S", P0]
    assert (record.cause, record.label, record.end_ms, record.last_ms, record.breach) == (
        "failed", "SYSTEM_FAILURE", 4 * H, 4 * H, None
    )
    assert schedule.system[P0, "B0", 2] == "OK"
    assert tuple(schedule.system[P0, b, c] for b, c in (("B0", 3), ("B1", 2), ("B1", 3))) == (
        "SYSTEM_FAILURE", "SYSTEM_FAILURE", "SYSTEM_FAILURE"
    )
    assert schedule.block_first == (0, 4 * H)
    record = schedule.arm_lives["A", P1]
    assert (record.first_ms, record.end_ms, record.cause, record.label, record.breach) == (
        4 * H, 5 * H, "blocked", "BLOCKED", None
    )
    assert not any(key[:2] == ("A", P1) for key in schedule.sent)
    assert sends(schedule, "S", P1) == hours(7, 8, 7, 8)
    assert schedule.controls[P1, "B1", 2] == Release(7 * H, "S", 7 * H, 0, False)
    assert schedule.controls[P1, "B1", 3] == Release(8 * H, "S", 8 * H, 0, False)
    assert schedule.t1_ms == 8 * H


def test_f2_first_request_stop_reuses_slot_at_zero(f1, draws):
    schedule = project(prepare(f1), "base", replace(draws, stops={("A", P0): ("failed", 1)}))
    record = schedule.arm_lives["A", P0]
    assert (record.first_ms, record.end_ms, record.last_ms) == (0, 0, 0)
    assert record.cause == "failed"
    assert record.label == "SYSTEM_FAILURE"
    assert record.breach is None
    assert schedule.block_first == (0, 0)
    assert not any(key[:2] == ("A", P0) for key in schedule.sent)
    assert schedule.sent["S", P0, "B1", 2] == 4 * H
    assert schedule.sent["S", P0, "B1", 3] == 5 * H


def test_durations():
    assert session_ms(Fraction(10, 3), 1000) == 3334
    assert session_ms(Fraction(10, 3) * Fraction(3, 2), 1000) == 5000
    assert session_ms(3600, 0) == 0


def test_stress_half(f1, draws):
    design = replace(f1, rows=(Row("A", 1), Row("B", 2), Row("D", 3)))
    draws = replace(draws, arm_order={pair: ("A", "B", "D", "S") for pair in (P0, P1)},
                    stress_order=("D", "A", "B"))
    prepared = prepare(design)
    assert prepared.design.system_rate == 3
    assert slow_rows(prepared, "stress_slow", draws) == frozenset({"S", "D"})
    assert slow_rows(prepared, "stress_fast", draws) == frozenset({"D", "A"})
    assert slow_rows(prepared, "base", draws) == frozenset()


def test_keyed_draws(f1):
    prepared = prepare(f1)
    draws = draw_all(prepared, "sim", 0)
    assert draws == draw_all(prepared, "sim", 0)
    assert any(draw_all(prepared, "sim", rep).arm_order != draws.arm_order for rep in range(1, 10))
    assert draws.arm_order[P0] == tuple(shuffle(
        "sim", ("ocsim", "arm-order", P0), 0, "arm-order", ["A", "S"]
    ))
    assert draws.stress_order == tuple(shuffle("sim", ("ocsim", "stress"), 0, "stress", ["A"]))
    assert draws.dispatch_seed == "ocsim-dispatch:%016x" % draw(
        "sim", ("ocsim", "dispatch"), 0, "dispatch-seed"
    )
    assert draws.step_block == uniform_int("sim", ("ocsim", "step"), 0, "step-block", 0, 1)
    for rates, expected in ((PassOverRates(1, 0), "failed"), (PassOverRates(0, 1), "blocked"),
                            (PassOverRates(0, 0), None)):
        dr = draw_all(prepare(replace(f1, passover=rates)), "sim", 0)
        assert set(dr.stops) == ({(row, pair) for row in ("A", "S") for pair in (P0, P1)}
                                 if expected else set())
        assert all(cause == expected and 1 <= session <= 3 for cause, session in dr.stops.values())
        for (row, pair), (_, session) in dr.stops.items():
            assert session == uniform_int(
                "sim", ("ocsim", "passover", row, pair), 0, "passover-session", 1, 3
            )
    for rate in (0, 1):
        dr = draw_all(prepare(replace(f1, control_failure=rate)), "sim", 0)
        assert dr.control_failed == (frozenset((arm, pair) for arm in ("C", "F")
                                              for pair in (P0, P1)) if rate else frozenset())
    dr = draw_all(prepare(replace(f1, passover=PassOverRates(1, 0), system_passovers=False)), "sim", 0)
    assert set(dr.stops) == {("A", P0), ("A", P1)}


def test_fractional_draw_thresholds_and_all_draws_consumed(f1, monkeypatch):
    import bicentennial.ocsim.schedule as module

    calls = []
    original = module.uniform_int

    def recording(seed, unit, rep, name, lo, hi):
        calls.append((unit, name, lo, hi))
        return original(seed, unit, rep, name, lo, hi)

    monkeypatch.setattr(module, "uniform_int", recording)
    rates = PassOverRates(Fraction(1, 3), Fraction(1, 2))
    design = replace(f1, passover=rates, control_failure=Fraction(2, 3))
    dr = draw_all(prepare(design), "sim", 2)
    for row in ("A", "S"):
        for pair in (P0, P1):
            unit = ("ocsim", "passover", row, pair)
            u = uniform_int("sim", unit, 2, "passover", 0, 5)
            expected = "failed" if u < 2 else "blocked" if u < 5 else None
            assert dr.stops.get((row, pair), (None,))[0] == expected
    for arm in PROBE_ONLY:
        for pair in (P0, P1):
            u = uniform_int("sim", ("ocsim", "control-infra", arm, pair), 2, "control-infra", 0, 2)
            assert ((arm, pair) in dr.control_failed) == (u < 2)
    assert sum(name == "passover-session" for _, name, _, _ in calls) == 4
    calls.clear()
    draw_all(prepare(replace(f1, system_passovers=False)), "sim", 2)
    assert sum(name == "passover-session" for _, name, _, _ in calls) == 4
    assert sum(name == "control-infra" for _, name, _, _ in calls) == 4


def test_purity_and_common_random_numbers(f1):
    prepared = prepare(f1)
    dr = draw_all(prepared, "sim", 0)
    original = replace(dr, arm_order=dict(dr.arm_order), stops=dict(dr.stops))
    layouts = dict(prepared.layouts)
    for kind in KINDS:
        assert project(prepared, kind, dr) == project(prepared, kind, dr)
    assert dr == original
    assert prepared.layouts == layouts


def test_projection_reuses_prepared_durations(f1, draws, monkeypatch):
    import bicentennial.ocsim.schedule as module

    prepared = prepare(f1)

    def unexpected_duration(*args, **kwargs):
        pytest.fail("projection recomputed a task duration")

    monkeypatch.setattr(module, "session_ms", unexpected_duration)
    for kind in KINDS:
        assert project(prepared, kind, draws).t1_ms > 0


def test_sorted_output_keys(f1):
    design = replace(f1, rows=(Row("Z", 3600), Row("A", 3600)), lives=tuple(reversed(f1.lives)))
    prepared = prepare(design)
    dr = draw_all(prepared, "sim", 0)
    shuffled = replace(dr, arm_order=dict(reversed(tuple(dr.arm_order.items()))),
                       stops=dict(reversed(tuple(dr.stops.items()))))
    assert list(prepared.layouts) == sorted(prepared.layouts)
    assert list(dr.arm_order) == sorted(dr.arm_order)
    assert list(dr.stops) == sorted(dr.stops)
    schedule = project(prepared, "stress_slow", dr)
    assert schedule == project(prepared, "stress_slow", shuffled)
    for mapping in (schedule.sent, schedule.system, schedule.controls, schedule.arm_lives,
                    schedule.post_swap, unit_times(schedule)):
        assert list(mapping) == sorted(mapping)
    assert schedule.control_failed == dr.control_failed


def test_chain_slots():
    lane = LaneCapacity("pinned", concurrency=4, accounts=3, runner_cap=10)
    assert chain_slots(lane) == 10
    assert chain_slots(lane, reserve=2) == 8
    assert chain_slots(LaneCapacity("swap", 2, 3)) == 6


@pytest.mark.parametrize("fork", (1, 2))
def test_fork_at_first_session_or_swap(f1, draws, fork):
    life = LifeSpec(P0, (1, 1, 1), (1,) * (4 - fork), fork, 2, (1, 0), (1, 0))
    design = replace(f1, lives=(life,), rows=(Row("A", 1),), capacity=Capacity(4, 4))
    prepared = prepare(design)
    plan = layout(prepared, "A", P0, False)
    assert tuple(s.lane for s in plan.b1) == (("pinned", "swap") if fork == 1 else ("swap",))
    assert plan.own_ms == 4
    dr = replace(draws, arm_order={P0: ("A", "S")}, step_block=0)
    schedule = project(prepared, "base", dr)
    assert sends(schedule, "A", P0) == (2, 4, 2, 4)
    assert schedule.arm_lives["A", P0].cause is None


def test_exact_life_bound(f1, draws):
    # Both branches finish exactly at 24H, before BOUND.
    life = LifeSpec(P0, (12, 12), (12,), 2, 2, (0,), (0,))
    design = replace(f1, lives=(life,), checkpoints=(2,), rows=(Row("A", H),),
                     capacity=Capacity(4, 4), system_rate=H)
    dr = replace(draws, arm_order={P0: ("A", "S")}, step_block=0)
    schedule = project(prepare(design), "base", dr)
    assert schedule.arm_lives["A", P0].last_ms == LIFE_BOUND_MS
    assert schedule.arm_lives["A", P0].breach == Breach(None, None, None)
    assert schedule.arm_lives["S", P0].last_ms == LIFE_BOUND_MS
    assert schedule.arm_lives["S", P0].breach == Breach(None, None, None)
    assert schedule.t1_ms == LIFE_BOUND_MS


def test_exact_start_window_and_bound_slot_reuse(f1, draws):
    # A's bound frees the pinned slot at 24H; assignment precedes WINDOW.
    life = LifeSpec(P0, (24, 1), (1,), 2, 2, (0,), (0,))
    design = replace(f1, lives=(life,), checkpoints=(2,), rows=(Row("A", H),),
                     capacity=Capacity(1, 2), system_rate=1)
    dr = replace(draws, arm_order={P0: ("A", "S")}, step_block=0)
    schedule = project(prepare(design), "base", dr)
    assert schedule.arm_lives["A", P0].cause == "life_bound"
    assert schedule.arm_lives["S", P0].first_ms == LIFE_BOUND_MS
    assert schedule.arm_lives["S", P0].breach == Breach(None, None, None)
    assert schedule.arm_lives["S", P0].last_ms == LIFE_BOUND_MS + 25


@pytest.mark.parametrize("ids", ((), (P0, P0), (17,)))
def test_validation_lives(f1, ids):
    with rejects("lives must be nonempty with unique str ids"):
        prepare(replace(f1, lives=tuple(replace(f1.lives[0], life=x) for x in ids)))


@pytest.mark.parametrize("checkpoints", ((), (2, 2), (3, 2), (0, 2), (True, 3), (2.0, 3)))
def test_validation_checkpoints(f1, checkpoints):
    with rejects("checkpoints must be strictly increasing ints >= 1"):
        prepare(replace(f1, checkpoints=checkpoints))


@pytest.mark.parametrize("tokens", ((0, 2, 1), (True, 2, 1), (1.0, 2, 1), (-1, 2, 1)))
def test_validation_session_tokens(f1, tokens):
    with rejects(f"life {P0}: session tokens must be ints >= 1"):
        prepare(changed_life(f1, b0_tokens=tokens))


@pytest.mark.parametrize("probes", ((0,), (-1, 0), (True, 0), (0.0, 0)))
def test_validation_probe_tokens(f1, probes):
    with rejects(f"life {P0}: probe tokens must be len(checkpoints) ints >= 0"):
        prepare(changed_life(f1, b1_probe_tokens=probes))


@pytest.mark.parametrize("fork", (0, 3, True, 2.0))
def test_validation_fork(f1, fork):
    with rejects(f"life {P0}: need 1 <= fork <= first checkpoint"):
        prepare(changed_life(f1, fork=fork))


def test_validation_b1_coverage(f1):
    with rejects(f"life {P0}: b1_tokens must cover sessions fork..N"):
        prepare(changed_life(f1, b1_tokens=(1000,)))


@pytest.mark.parametrize("swap", (1, 4, True, 3.0))
def test_validation_swap(f1, swap):
    with rejects(f"life {P0}: need 2 <= swap <= sessions"):
        prepare(changed_life(f1, swap=swap))


def test_validation_checkpoints_exceed_sessions(f1):
    with rejects(f"life {P0}: checkpoints exceed its sessions"):
        prepare(replace(f1, checkpoints=(2, 4)))


@pytest.mark.parametrize("ids", ((), ("A", "A"), (1,), ("F",), ("C",), ("S",)))
def test_validation_rows(f1, ids):
    with rejects("rows must be nonempty unique str ids other than F, C and S"):
        prepare(replace(f1, rows=tuple(Row(x, 1) for x in ids)))


@pytest.mark.parametrize("rate", (0, -1, True, 1.0, "1"))
def test_validation_row_rate(f1, rate):
    with rejects("row A: rate must be a positive int or Fraction"):
        prepare(replace(f1, rows=(Row("A", rate),)))


@pytest.mark.parametrize("rate", (0, -1, True, 1.0))
def test_validation_system_rate(f1, rate):
    with rejects("system rate must be a positive int or Fraction"):
        prepare(replace(f1, system_rate=rate))


@pytest.mark.parametrize("capacity", (Capacity(0, 1), Capacity(1, -1), Capacity(True, 1), Capacity(1, 1.0)))
def test_validation_capacity(f1, capacity):
    with rejects("capacity slots must be ints >= 1"):
        prepare(replace(f1, capacity=capacity))


@pytest.mark.parametrize("rates", (PassOverRates(-1, 0), PassOverRates(1, 1), PassOverRates(True, 0),
                                 PassOverRates(0, 0.5), PassOverRates(2, 0)))
def test_validation_passover(f1, rates):
    with rejects("pass-over rates must be Fractions in [0, 1] with sum <= 1"):
        prepare(replace(f1, passover=rates))


@pytest.mark.parametrize("rate", (-1, 2, True, 0.5))
def test_validation_control_failure_rate(f1, rate):
    with rejects("control failure rate must be a Fraction in [0, 1]"):
        prepare(replace(f1, control_failure=rate))


def test_validation_system_passovers(f1):
    with rejects("system_passovers must be a bool"):
        prepare(replace(f1, system_passovers=1))


def test_validation_kind(f1, draws):
    with rejects("unknown schedule kind: other"):
        project(prepare(f1), "other", draws)


@pytest.mark.parametrize("tokens", (-1, True, 1.0))
def test_validation_session_ms_tokens(tokens):
    with rejects("tokens must be an int >= 0"):
        session_ms(1, tokens)


def test_validation_rate_bound_lane():
    with rejects("rate-bound lane x: slots need an owner ruling"):
        chain_slots(LaneCapacity("x", 2, 1, rate_per_min=60))


@pytest.mark.parametrize("reserve", (-1, 2, True, Fraction(1, 2)))
def test_validation_reserve(reserve):
    with rejects("reserve must leave at least one chain slot"):
        chain_slots(LaneCapacity("x", 2, 1), reserve)


@pytest.mark.parametrize("order", ({}, {P0: ("A", "A"), P1: ("A", "S")},
                                  {P0: ("A",), P1: ("A", "S")}))
def test_validation_arm_order(f1, draws, order):
    with rejects(f"arm order for {P0} must permute every row"):
        project(prepare(f1), "base", replace(draws, arm_order=order))


@pytest.mark.parametrize("order", ((), ("S",), ("A", "A")))
def test_validation_stress_order(f1, draws, order):
    with rejects("stress order must permute the roster rows"):
        project(prepare(f1), "base", replace(draws, stress_order=order))


@pytest.mark.parametrize("row,pair,stop", (
    ("Z", P0, ("failed", 1)), ("A", "other", ("failed", 1)),
    ("A", P0, ("other", 1)), ("A", P0, ("failed", 0)),
    ("A", P0, ("failed", 4)), ("A", P0, ("failed", True)),
    ("A", P0, ("failed",)), ("A", P0, ("failed", 1.0)),
))
def test_validation_stop(f1, draws, row, pair, stop):
    with rejects(f"bad stop for {row} {pair}"):
        project(prepare(f1), "base", replace(draws, stops={(row, pair): stop}))


@pytest.mark.parametrize("arm,pair", (("A", P0), ("C", "other")))
def test_validation_control_failed(f1, draws, arm, pair):
    with rejects(f"bad control failure: {arm} {pair}"):
        project(prepare(f1), "base", replace(draws, control_failed=frozenset({(arm, pair)})))


@pytest.mark.parametrize("step", (-1, 2, True, 1.0))
def test_validation_step_block(f1, draws, step):
    with rejects("step block out of range"):
        project(prepare(f1), "base", replace(draws, step_block=step))


@pytest.mark.parametrize("seed,rep", ((1, 0), ("sim", -1), ("sim", True), ("sim", 0.0)))
def test_validation_seed_rep(f1, seed, rep):
    with rejects("seed must be str and rep an int >= 0"):
        draw_all(prepare(f1), seed, rep)
