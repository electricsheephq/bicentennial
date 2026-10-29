"""Hand-computed §11 lane hours and breach edges; no runner or clock."""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from bicentennial.runner.occupancy import (
    SHARED,
    ArmLifeSpan,
    Breach,
    LaneCapacity,
    LaneHours,
    WorkBound,
    WorkTerm,
    classify_breach,
    lane_hours,
    project,
)

SOL = LaneCapacity("sol", concurrency=20, accounts=2, rate_per_min=180)
HOUR_MS = 3_600_000


def test_sol_concurrency_and_runner_cap():
    # 2,880,000,000 / (3,600,000 * 40) = 20;
    # 100,000 / (60 * 180 * 2) = 125/27.
    assert lane_hours(SOL, 2_880_000_000, 100_000) == LaneHours(
        Fraction(20), Fraction(125, 27), Fraction(20), "concurrency")
    assert lane_hours(replace(SOL, runner_cap=30), 2_880_000_000, 100_000) == LaneHours(
        Fraction(80, 3), Fraction(125, 27), Fraction(80, 3), "concurrency")
    assert lane_hours(replace(SOL, runner_cap=50), 2_880_000_000, 100_000) == lane_hours(
        SOL, 2_880_000_000, 100_000)


def test_glm_rate_bound():
    glm = LaneCapacity("glm", concurrency=8, accounts=1, rate_per_min=60)
    # 288,000,000 / (3,600,000 * 8) = 10; 72,000 / 3,600 = 20.
    assert lane_hours(glm, 288_000_000, 72_000) == LaneHours(
        Fraction(10), Fraction(20), Fraction(20), "rate")


def test_no_rate_term():
    result = lane_hours(replace(SOL, rate_per_min=None), 2_880_000_000, 100_000)
    assert result == LaneHours(Fraction(20), None, Fraction(20), "concurrency")
    assert type(result.concurrency_h) is type(result.hours) is Fraction


def test_capacity_tie_and_zero_work():
    lane = LaneCapacity("tie", concurrency=1, accounts=1, rate_per_min=1)
    assert lane_hours(lane, HOUR_MS, 60) == LaneHours(
        Fraction(1), Fraction(1), Fraction(1), "both")
    assert lane_hours(lane, 0, 0) == LaneHours(
        Fraction(0), Fraction(0), Fraction(0), "both")
    assert lane_hours(replace(lane, rate_per_min=None), 0, 0) == LaneHours(
        Fraction(0), None, Fraction(0), "concurrency")


def test_shared_work_once_and_lanes_separate():
    sol = replace(SOL, rate_per_min=None)
    glm = LaneCapacity("glm", concurrency=8, accounts=1, rate_per_min=60)
    terms = [
        WorkTerm("sol", "A", "board", "replay", 1_440_000_000, 0),
        WorkTerm("sol", "B", "board", "replay", 720_000_000, 0),
        WorkTerm("sol", SHARED, "board", "ctrl", 720_000_000, 0),
        WorkTerm("glm", "A", "board", "replay", 288_000_000, 72_000),
    ]
    result = project(iter([sol, glm]), iter(terms))
    assert {key: value.hours for key, value in result.work.items()} == {
        ("A", "sol", "board"): Fraction(10),
        ("B", "sol", "board"): Fraction(5),
        ("A", "glm", "board"): Fraction(20),
    }
    assert {key: value.hours for key, value in result.occupancy.items()} == {
        ("sol", "board"): Fraction(20), ("glm", "board"): Fraction(20),
    }
    assert {key: value.with_pause_h for key, value in result.work_bounds.items()} == {
        ("A", "sol", "board"): Fraction(25, 2),
        ("B", "sol", "board"): Fraction(25, 4),
        ("A", "glm", "board"): Fraction(25),
    }
    assert all(bound.fits for bound in result.work_bounds.values())


def test_study_occupies_board_run_with_separate_work_bounds():
    lane = LaneCapacity("lane", concurrency=2, accounts=1)
    terms = [
        WorkTerm("lane", "A", "board", "replay", 4 * HOUR_MS, 0),
        WorkTerm("lane", "A", "study", "replay", 6 * HOUR_MS, 0),
        WorkTerm("lane", SHARED, "board", "ctrl", 2 * HOUR_MS, 0),
    ]
    result = project([lane], terms)
    # Divide request-ms by (3,600,000 * 2): board 2 h, study 3 h,
    # shared 1 h; board occupancy is (4 + 6 + 2) / 2 = 6 h.
    assert result.occupancy == {
        ("lane", "board"): LaneHours(Fraction(6), None, Fraction(6), "concurrency"),
    }
    assert result.work == {
        ("A", "lane", "board"): LaneHours(Fraction(2), None, Fraction(2), "concurrency"),
        ("A", "lane", "study"): LaneHours(Fraction(3), None, Fraction(3), "concurrency"),
    }
    # Each work bound applies its own 5/4 pause factor and 96 h limit.
    assert result.work_bounds == {
        ("A", "lane", "board"): WorkBound(Fraction(2), Fraction(5, 2), Fraction(96), True),
        ("A", "lane", "study"): WorkBound(Fraction(3), Fraction(15, 4), Fraction(96), True),
    }
    image = WorkTerm("lane", "A", "image", "replay", 8 * HOUR_MS, 0)
    # Image occupancy is 8 / 2 = 4 h on the same lane, in its own run.
    assert project([lane], [*terms, image]).occupancy == {
        ("lane", "board"): LaneHours(Fraction(6), None, Fraction(6), "concurrency"),
        ("lane", "image"): LaneHours(Fraction(4), None, Fraction(4), "concurrency"),
    }


def test_terms_are_aggregated_before_capacity_maximum():
    lane = LaneCapacity("mixed", concurrency=1, accounts=1, rate_per_min=1)
    terms = [WorkTerm("mixed", "A", "board", "replay", 2 * HOUR_MS, 0),
             WorkTerm("mixed", "A", "board", "probe", 0, 120)]
    result = project([lane], terms)
    # max(2, 0) + max(0, 2) would incorrectly give 4 h; totals give max(2, 2) = 2.
    expected = LaneHours(Fraction(2), Fraction(2), Fraction(2), "both")
    assert result.work == {("A", "mixed", "board"): expected}
    assert result.occupancy == {("mixed", "board"): expected}


@pytest.mark.parametrize("owner", ["A", SHARED])
def test_duplicate_term_identity_rejected_even_with_different_counts(owner):
    term = WorkTerm("sol", owner, "board", "probe", 1, 1)
    with pytest.raises(ValueError, match="duplicate work term"):
        project([SOL], [term, replace(term, request_ms=2, n_req=3)])


def test_work_bound_edge_and_runs_separate():
    sol = replace(SOL, rate_per_min=None)
    terms = [WorkTerm("sol", "A", run, "replay", 11_059_200_000, 0)
             for run in ("board", "study", "image")]
    result = project([sol], terms)
    # 11,059,200,000 / 144,000,000 = 384/5 h; (384/5) * (5/4) = 96 h.
    at = WorkBound(Fraction(384, 5), Fraction(96), Fraction(96), True)
    assert result.work_bounds == {("A", "sol", run): at for run in ("board", "study", "image")}
    over = project([sol], [replace(terms[0], request_ms=11_059_200_001), *terms[1:]])
    assert over.work_bounds[("A", "sol", "board")] == WorkBound(
        Fraction(11_059_200_001, 144_000_000),
        Fraction(11_059_200_001, 115_200_000), Fraction(96), False)
    assert over.work_bounds[("A", "sol", "study")] == at
    assert over.work_bounds[("A", "sol", "image")] == at


def test_work_bounds_do_not_sum_lanes_or_systems_or_shared_work():
    sol = replace(SOL, rate_per_min=None)
    second = replace(sol, name="second")
    terms = [WorkTerm(lane, owner, "board", "replay", 11_059_200_000, 0)
             for lane in ("sol", "second") for owner in ("A", "B", SHARED)]
    result = project([sol, second], terms)
    assert len(result.work_bounds) == 4
    assert all(bound == WorkBound(Fraction(384, 5), Fraction(96), Fraction(96), True)
               for bound in result.work_bounds.values())
    assert {key: value.hours for key, value in result.occupancy.items()} == {
        ("sol", "board"): Fraction(1152, 5), ("second", "board"): Fraction(1152, 5)}


def test_rate_work_bound():
    lane = LaneCapacity("rate", concurrency=1, accounts=1, rate_per_min=1)
    # 4,608 requests / 60 = 384/5 h; after pause allowance exactly 96 h.
    term = WorkTerm("rate", "A", "study", "probe", 0, 4608)
    assert project([lane], [term]).work_bounds[("A", "rate", "study")] == WorkBound(
        Fraction(384, 5), Fraction(96), Fraction(96), True)
    assert project([lane], [replace(term, n_req=4609)]).work_bounds[
        ("A", "rate", "study")] == WorkBound(
            Fraction(4609, 60), Fraction(4609, 48), Fraction(96), False)


@pytest.mark.parametrize("duration_h,own_h,label", [
    (25, 25, "SYSTEM_FAILURE"), (25, 20, "BLOCKED"), (25, 24, "BLOCKED"),
    (24, 0, None), (24, 24, None), (24, 25, None),
])
def test_life_bound_and_cutoff(duration_h, own_h, label):
    span = ArmLifeSpan("A", "life", True, 7000, 10_000,
                       10_000 + duration_h * HOUR_MS, own_h * HOUR_MS)
    expected = Breach("life_bound", label, 86_410_000) if label else Breach(None, None, None)
    assert classify_breach(span) == expected


@pytest.mark.parametrize("delay_ms,duration_ms,expected", [
    (86_400_001, 0, Breach("start_window", "BLOCKED", 86_407_000)),
    (86_400_000, 0, Breach(None, None, None)),
    (86_400_001, 90_000_000, Breach("start_window", "BLOCKED", 86_407_000)),
    (86_400_000, 90_000_000, Breach("life_bound", "SYSTEM_FAILURE", 172_807_000)),
    (86_400_000, 86_400_000, Breach(None, None, None)),
])
def test_start_window_edges_and_precedence(delay_ms, duration_ms, expected):
    first = 7000 + delay_ms
    span = ArmLifeSpan("A", "life", True, 7000, first, first + duration_ms, duration_ms)
    assert classify_breach(span) == expected


def test_life_bound_one_millisecond_over():
    span = ArmLifeSpan("A", "life", True, 7000, 10_000, 86_410_001, 86_400_000)
    assert classify_breach(span) == Breach("life_bound", "BLOCKED", 86_410_000)
    assert classify_breach(replace(span, own_ms=86_400_001)) == Breach(
        "life_bound", "SYSTEM_FAILURE", 86_410_000)


def test_probe_only_spans_unclassified_even_when_both_bounds_break():
    first = 7000 + 30 * HOUR_MS
    span = ArmLifeSpan("ctrl", "life", False, 7000, first,
                       first + 30 * HOUR_MS, 30 * HOUR_MS)
    assert classify_breach(span) == Breach(None, None, None)


@pytest.mark.parametrize("bad", [1.0, True, False, Fraction(1), "1", None])
@pytest.mark.parametrize("field", ["concurrency", "accounts", "rate_per_min", "runner_cap"])
def test_capacity_counts_require_integers(field, bad):
    if bad is None and field in ("rate_per_min", "runner_cap"):
        assert getattr(replace(SOL, **{field: bad}), field) is None
    else:
        with pytest.raises(TypeError):
            replace(SOL, **{field: bad})


@pytest.mark.parametrize("bad", [1.0, True, False, Fraction(1), "1", None])
@pytest.mark.parametrize("field", ["request_ms", "n_req"])
def test_work_counts_and_lane_totals_require_integers(field, bad):
    term = WorkTerm("sol", "A", "board", "replay", 1, 1)
    with pytest.raises(TypeError):
        replace(term, **{field: bad})
    totals = {"request_ms": 1, "n_req": 1, field: bad}
    with pytest.raises(TypeError):
        lane_hours(SOL, **totals)


@pytest.mark.parametrize("bad", [1.0, True, False, Fraction(1), "1", None])
@pytest.mark.parametrize("field", ["block_first_ms", "first_request_ms", "last_ms", "own_ms"])
def test_span_times_require_integers(field, bad):
    span = ArmLifeSpan("A", "life", True, 0, 0, 1, 1)
    with pytest.raises(TypeError):
        replace(span, **{field: bad})


@pytest.mark.parametrize("bad", [0, 1, None, "true"])
def test_replaying_requires_bool(bad):
    with pytest.raises(TypeError):
        ArmLifeSpan("A", "life", bad, 0, 0, 0, 0)


@pytest.mark.parametrize("field", ["concurrency", "accounts", "rate_per_min", "runner_cap"])
@pytest.mark.parametrize("bad", [0, -1])
def test_capacity_must_be_positive(field, bad):
    with pytest.raises(ValueError):
        replace(SOL, **{field: bad})


def test_invalid_work_and_span_values():
    term = WorkTerm("sol", "A", "board", "replay", 0, 0)
    for field in ("request_ms", "n_req"):
        with pytest.raises(ValueError):
            replace(term, **{field: -1})
        with pytest.raises(ValueError):
            lane_hours(SOL, **{"request_ms": 0, "n_req": 0, field: -1})
    with pytest.raises(ValueError, match="run must"):
        replace(term, run="other")
    for times in ((1, 0, 2, 0), (0, 2, 1, 0), (0, 0, 1, -1)):
        with pytest.raises(ValueError):
            ArmLifeSpan("A", "life", True, *times)
    # Clock origins may be negative; only differences matter.
    assert classify_breach(ArmLifeSpan("A", "life", True, -2, -1, 0, 1)) == Breach(
        None, None, None)


@pytest.mark.parametrize("value,field", [
    (SOL, "name"),
    (WorkTerm("sol", "A", "board", "replay", 0, 0), "lane"),
    (WorkTerm("sol", "A", "board", "replay", 0, 0), "owner"),
    (WorkTerm("sol", "A", "board", "replay", 0, 0), "run"),
    (WorkTerm("sol", "A", "board", "replay", 0, 0), "kind"),
    (ArmLifeSpan("A", "life", True, 0, 0, 0, 0), "arm"),
    (ArmLifeSpan("A", "life", True, 0, 0, 0, 0), "life"),
])
def test_identifiers_require_nonempty_strings(value, field):
    with pytest.raises(TypeError):
        replace(value, **{field: 1})
    with pytest.raises(ValueError):
        replace(value, **{field: ""})


def test_inputs_and_breach_are_frozen():
    values = [(SOL, "accounts", 3),
              (WorkTerm("sol", "A", "board", "replay", 0, 0), "n_req", 1),
              (ArmLifeSpan("A", "life", True, 0, 0, 0, 0), "own_ms", 1),
              (Breach(None, None, None), "bound_ms", 1)]
    for value, field, replacement in values:
        with pytest.raises(FrozenInstanceError):
            setattr(value, field, replacement)


def test_unknown_or_duplicate_lanes_rejected():
    with pytest.raises(ValueError, match="duplicate lane"):
        project([SOL, replace(SOL, accounts=1)], [])
    with pytest.raises(ValueError, match="unknown lane"):
        project([SOL], [WorkTerm("missing", "A", "board", "replay", 0, 0)])


def test_empty_and_shared_only_workloads():
    assert project([], []) == project([SOL], [])
    assert project([], []).work == {}
    assert project([], []).occupancy == {}
    assert project([], []).work_bounds == {}
    result = project([replace(SOL, rate_per_min=None)], [
        WorkTerm("sol", SHARED, "board", "ctrl", 720_000_000, 0)])
    assert result.work == result.work_bounds == {}
    assert result.occupancy == {
        ("sol", "board"): LaneHours(Fraction(5), None, Fraction(5), "concurrency")}
