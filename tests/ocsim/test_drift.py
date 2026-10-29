"""Hand-derived drift cases, explicit scopes and exact validation messages."""

import re
from fractions import Fraction

import pytest

from bicentennial.ocsim.drift import (
    ALL_UNITS,
    ARMS,
    DAY_MS,
    DRIFT_CASES,
    LITERAL,
    SWAP_GATE,
    DriftCase,
    DriftScope,
    drift_points,
    drifted_targets,
)

H = 3_600_000
FLOOR_CEILING = {"X": (-200.0, 600.0)}


@pytest.fixture
def target_args():
    return {
        "floor_ceiling": dict(FLOOR_CEILING),
        "expected": {(arm, "pair-000", "X"): value
                     for arm, value in zip(ARMS, (-200.0, 600.0, 200.0), strict=True)},
        "times": {(arm, "pair-000", 2): Fraction(10) for arm in ARMS},
        "post_swap": {("pair-000", 2): False},
        "checkpoints": (2,),
        "case": DriftCase("step+5", "step", 1),
        "scope": ALL_UNITS,
        "t1_ms": 20,
        "step_start_ms": 0,
    }


def test_public_constants_and_case_order():
    assert DAY_MS == 24 * H
    assert ARMS == ("F", "C", "S")
    assert [(case.name, case.kind, case.sign, case.phase) for case in DRIFT_CASES] == [
        ("none", "none", 0, 0),
        ("step+5", "step", 1, 0),
        ("step-5", "step", -1, 0),
        ("trend+5", "trend", 1, 0),
        ("trend-5", "trend", -1, 0),
        ("cycle0", "cycle", 0, 0),
        ("cycle90", "cycle", 0, 1),
        ("cycle180", "cycle", 0, 2),
        ("cycle270", "cycle", 0, 3),
    ]
    assert LITERAL.drifts == frozenset({
        ("F", False), ("F", True), ("C", False), ("C", True), ("S", False),
    })
    assert ALL_UNITS.drifts == frozenset((arm, post) for arm in ARMS for post in (False, True))
    assert SWAP_GATE.drifts == frozenset({("F", False), ("C", False), ("S", False)})


@pytest.mark.parametrize(("case", "t_ms", "value"), [
    (DriftCase("step+5", "step", 1), 21_599_999, Fraction(0)),
    (DriftCase("step+5", "step", 1), Fraction(43_199_999, 2), Fraction(0)),
    (DriftCase("step+5", "step", 1), 21_600_000, Fraction(5)),
    (DriftCase("step+5", "step", 1), Fraction(43_200_001, 2), Fraction(5)),
    (DriftCase("step-5", "step", -1), 21_600_000, Fraction(-5)),
    (DriftCase("trend+5", "trend", 1), 0, Fraction(0)),
    (DriftCase("trend+5", "trend", 1), 16_200_000, Fraction(9, 4)),
    (DriftCase("trend+5", "trend", 1), 36_000_000, Fraction(5)),
    (DriftCase("trend+5", "trend", 1), 40_000_000, Fraction(5)),
    (DriftCase("trend-5", "trend", -1), Fraction(16_200_000), Fraction(-9, 4)),
    (DriftCase("none", "none"), Fraction(1, 2), Fraction(0)),
])
def test_drift_points_step_trend_none(case, t_ms, value):
    actual = drift_points(case, t_ms, t1_ms=36_000_000, step_start_ms=21_600_000)
    assert isinstance(actual, Fraction)
    assert actual == value


@pytest.mark.parametrize(("phase", "t_ms", "value"), [
    (0, 0, 0.0), (0, 6 * H, 3.0), (0, 12 * H, 0.0), (0, 18 * H, -3.0),
    (1, 0, 3.0), (3, 0, -3.0), (2, 6 * H, -3.0),
    (0, DAY_MS + 6 * H, 3.0),
    (3, 24 * H, -3.0),
])
def test_cycle_quarter_turns(phase, t_ms, value):
    actual = drift_points(
        DriftCase("cycle", "cycle", phase=phase), t_ms,
        t1_ms=2 * DAY_MS, step_start_ms=0,
    )
    assert isinstance(actual, float)
    assert actual == value


def test_cycle_at_three_hours():
    actual = drift_points(
        DriftCase("cycle0", "cycle"), Fraction(3 * H), t1_ms=10 * H, step_start_ms=0,
    )
    assert actual == pytest.approx(2.1213203435596424, abs=1e-12, rel=0)


@pytest.mark.parametrize(("kind", "sign", "time", "values"), [
    ("step", 1, 10, (-200.0, 650.0, 225.0)),
    ("step", -1, 10, (-200.0, 550.0, 175.0)),
    ("trend", 1, 9, (-200.0, 622.5, 211.25)),
])
def test_floor_ceiling_gate_acceptance(target_args, kind, sign, time, values):
    target_args["case"] = DriftCase("acceptance", kind, sign)
    target_args["times"] = {(arm, "pair-000", 2): Fraction(time) for arm in ARMS}
    actual = drifted_targets(**target_args)
    assert actual == {(arm, "pair-000", "X", 2): value
                      for arm, value in zip(ARMS, values, strict=True)}
    assert actual[("S", "pair-000", "X", 2)] == (
        actual[("F", "pair-000", "X", 2)] + actual[("C", "pair-000", "X", 2)]
    ) / 2


def test_clipping_at_both_limits(target_args):
    target_args["floor_ceiling"] = {"Y": (-200.0, 960.0), "Z": (-900.0, -100.0)}
    target_args["expected"] = {
        ("C", "pair-000", "Y"): 960.0,
        ("S", "pair-000", "Y"): 380.0,
        ("S", "pair-000", "Z"): -1000.0,
    }
    assert drifted_targets(**target_args) == {
        ("C", "pair-000", "Y", 2): 1000.0,
        ("S", "pair-000", "Y", 2): 405.0,
        ("S", "pair-000", "Z", 2): -1000.0,
    }


@pytest.mark.parametrize(("scope", "ceiling", "system"), [
    (LITERAL, (600.0, 650.0, 650.0, 650.0), (200.0, 200.0, 225.0, 200.0)),
    (ALL_UNITS, (600.0, 650.0, 650.0, 650.0), (200.0, 225.0, 225.0, 225.0)),
    (SWAP_GATE, (600.0, 600.0, 650.0, 600.0), (200.0, 200.0, 225.0, 200.0)),
])
def test_f1_base_schedule_scopes(target_args, scope, ceiling, system):
    units = (("pair-000", 2), ("pair-000", 3), ("pair-001", 2), ("pair-001", 3))
    # B1.7 test 2 unit times, written directly in milliseconds; no schedule import.
    unit_times = (
        Fraction(9 * H, 2), Fraction(6 * H), Fraction(17 * H, 2), Fraction(19 * H, 2),
    )
    target_args.update(
        expected={(arm, pair, "X"): value
                  for arm, value in zip(ARMS, (-200.0, 600.0, 200.0), strict=True)
                  for pair in ("pair-001", "pair-000")},
        times={(arm, pair, ckpt): time for arm in ARMS
               for (pair, ckpt), time in zip(units, unit_times, strict=True)},
        post_swap={(pair, ckpt): ckpt == 3 for pair, ckpt in units},
        checkpoints=(2, 3), scope=scope, t1_ms=10 * H, step_start_ms=6 * H,
    )
    actual = drifted_targets(**target_args)
    assert list(actual) == sorted(actual)
    assert [actual[("F", pair, "X", ckpt)] for pair, ckpt in units] == [-200.0] * 4
    assert tuple(actual[("C", pair, "X", ckpt)] for pair, ckpt in units) == ceiling
    assert tuple(actual[("S", pair, "X", ckpt)] for pair, ckpt in units) == system
    if scope == LITERAL:
        gate = (actual[("F", "pair-000", "X", 3)] + actual[("C", "pair-000", "X", 3)]) / 2
        assert gate == 225.0
        assert (actual[("S", "pair-000", "X", 3)] - gate) / 10 == -2.5


@pytest.mark.parametrize("case", DRIFT_CASES)
def test_none_times_leave_expected_unchanged(target_args, case):
    target_args["case"] = case
    target_args["times"] = {key: None for key in target_args["times"]}
    assert drifted_targets(**target_args) == {
        (*key, 2): value for key, value in target_args["expected"].items()
    }


@pytest.mark.parametrize("scope", [LITERAL, ALL_UNITS, SWAP_GATE, DriftScope(frozenset())])
def test_none_case_sorted_cartesian_targets(target_args, scope):
    target_args.update(
        case=DriftCase("none", "none"), scope=scope, checkpoints=(2, 3),
        expected={(arm, pair, "X"): value
                  for pair in ("pair-001", "pair-000")
                  for arm, value in zip(ARMS, (-200.0, 600.0, 200.0), strict=True)},
        times={(arm, pair, ckpt): Fraction(10) for arm in ARMS
               for pair in ("pair-001", "pair-000") for ckpt in (2, 3)},
        post_swap={(pair, ckpt): ckpt == 3 for pair in ("pair-001", "pair-000")
                   for ckpt in (2, 3)},
    )
    actual = drifted_targets(**target_args)
    assert actual == {(*key, ckpt): value for key, value in target_args["expected"].items()
                      for ckpt in (2, 3)}
    assert list(actual) == sorted(actual)


def test_unknown_case_kind():
    message = "unknown drift case"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        DriftCase("bad", "unknown")
    assert str(exc.value) == message


@pytest.mark.parametrize(("kind", "sign", "phase"), [
    ("step", 0, 0), ("step", 2, 0), ("trend", 0, 0), ("trend", -2, 0),
    ("cycle", 0, -1), ("cycle", 0, 4), ("cycle", 0, Fraction(1, 2)),
    ("cycle", 1, 0), ("none", 1, 0), ("none", 0, 1),
])
def test_bad_case_parameters(kind, sign, phase):
    message = "bad drift case parameters"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        DriftCase("bad", kind, sign, phase)
    assert str(exc.value) == message


@pytest.mark.parametrize("time", [True, False, -1, Fraction(-1, 2), 1.0, "1", None])
def test_invalid_drift_time(target_args, time):
    message = "drift time must be an int or Fraction >= 0"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drift_points(target_args["case"], time, t1_ms=20, step_start_ms=0)
    assert str(exc.value) == message


@pytest.mark.parametrize("t1_ms", [True, False, 0, -1, 20.0, Fraction(20)])
def test_invalid_last_probe_time(target_args, t1_ms):
    message = "t1 must be a positive int"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drift_points(target_args["case"], 10, t1_ms=t1_ms, step_start_ms=0)
    assert str(exc.value) == message
    target_args["t1_ms"] = t1_ms
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("start", [True, False, -1, 0.0, Fraction(0)])
def test_invalid_step_start(target_args, start):
    message = "step start must be an int >= 0"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drift_points(target_args["case"], 10, t1_ms=20, step_start_ms=start)
    assert str(exc.value) == message
    target_args["step_start_ms"] = start
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("drifts", [
    {("S", False)}, (("S", False),), frozenset({("A", False)}),
    frozenset({("S", 0)}), frozenset({("S",)}), frozenset({"S"}),
    frozenset({("S", False, True)}),
])
def test_invalid_scope(drifts):
    message = "drift scope must hold (arm, post_swap) pairs with arm in F, C, S"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        DriftScope(drifts)
    assert str(exc.value) == message


@pytest.mark.parametrize("key", [
    ("A", "pair-000", "X"), ("S", 0, "X"), ("S", "pair-000", 0),
    ("S", "pair-000"), "S",
])
def test_bad_expected_key(target_args, key):
    target_args["expected"] = {key: 200.0}
    message = f"bad expected key: {key}"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("value", [
    200, True, Fraction(200), "200", float("nan"), float("inf"), float("-inf"),
    -1000.5, 1000.5,
])
def test_invalid_expected_score(target_args, value):
    target_args["expected"][("S", "pair-000", "X")] = value
    message = "expected scores must be finite floats in [-1000, 1000]"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("floor_ceiling", [
    {}, {"X": (float("nan"), 600.0)}, {"X": (-200.0, float("inf"))},
    {"X": (float("-inf"), 600.0)}, {"X": (600.0, 600.0)}, {"X": (700.0, 600.0)},
    {"X": ("floor", 600.0)},
])
def test_invalid_floor_ceiling(target_args, floor_ceiling):
    target_args["floor_ceiling"] = floor_ceiling
    message = "cell X: need finite f0 < c0"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("checkpoints", [(), (0,), (-1,), (True,), (2.0,), (2, 2), (3, 2)])
def test_invalid_checkpoints(target_args, checkpoints):
    target_args["checkpoints"] = checkpoints
    message = "checkpoints must be strictly increasing ints >= 1"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message


@pytest.mark.parametrize("field", ["times", "post_swap"])
def test_missing_unit_keys(target_args, field):
    target_args[field] = {}
    message = ("missing unit time: ('C', 'pair-000', 2)" if field == "times"
               else "missing swap state: ('pair-000', 2)")
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        drifted_targets(**target_args)
    assert str(exc.value) == message
