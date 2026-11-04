"""Hand-computed isolated schedules, the floor kept out of every arm, and measured overhead."""

from copy import deepcopy

import pytest

from bicentennial.runner.arm_time import calculate_arm_times


def row(life, start, end, arm="system", slot=0, attempts=1):
    return dict(life=life, branch="B0", arm=arm, slot=slot,
                start_ms=start, end_ms=end, attempts=attempts)


def test_one_slot_sums_whole_attempt_spans_and_outside():
    rows = [row("u1", 10, 40, attempts=3), row("u2", 50, 70)]
    original = deepcopy(rows)
    result = calculate_arm_times(1, rows, 0, 100)
    arm = result["arms"]["system"]
    assert arm == dict(arm_time_ms=100, replay_ms=50, slots=1, outside_ms=50, elapsed_ms=100,
                       units=[dict(arm="system", life="u1", branch="B0", start_order=0, duration_ms=30),
                              dict(arm="system", life="u2", branch="B0", start_order=1, duration_ms=20)])
    assert result["floor_replay_ms"] == 0
    assert result["timings"] == rows == original
    assert (result["start_ms"], result["end_ms"]) == (0, 100)
    assert result["timings"][0] is not rows[0]


def test_start_order_and_card_ties():
    # Start order u2 (3), u1 (10), u3 (8) yields slots ending at 11 and 10.
    rows = [row("u1", 1, 11), row("u2", 0, 3), row("u3", 3, 11)]
    arm = calculate_arm_times(2, rows, 0, 11)["arms"]["system"]
    assert [u["life"] for u in arm["units"]] == ["u2", "u1", "u3"]
    assert arm["replay_ms"] == arm["arm_time_ms"] == 11
    # Card order wins the tie: 3,10,8 gives 11; sorting by completion gives 3,8,10 and 13.
    tied = [row("u2", 0, 3), row("u1", 0, 10), row("u3", 0, 8)]
    arm = calculate_arm_times(2, tied, 0, 10)["arms"]["system"]
    assert [u["life"] for u in arm["units"]] == ["u2", "u1", "u3"]
    assert arm["replay_ms"] == 11


def test_interleaved_arms_leave_out_floor_and_union_overhead():
    rows = [row("floor", 2, 6, "no_memory"), row("a1", 3, 13, "a", 1),
            row("b1", 8, 14, "b"), row("a2", 14, 21, "a", 1), row("b2", 23, 25, "b")]
    result = calculate_arm_times(2, rows, 0, 30)
    # Union [2,21] + [23,25] = 21, so all arms pay 9 outside units. Neither arm replays the floor.
    a, b = (result["arms"][key] for key in ("a", "b"))
    assert (a["outside_ms"], b["outside_ms"]) == (9, 9)
    assert (a["replay_ms"], b["replay_ms"]) == (10, 6)
    assert (a["arm_time_ms"], b["arm_time_ms"]) == (19, 15)
    assert [u["start_order"] for u in a["units"]] == [1, 3]
    assert [u["arm"] for u in b["units"]] == ["b", "b"]
    assert result["floor_replay_ms"] == 4
    for arm in result["arms"].values():
        assert arm["arm_time_ms"] >= max(u["duration_ms"] for u in arm["units"])


def test_fresh_floor_on_two_slots_counts_only_beside_the_arm():
    rows = [row("f1", 0, 8, "no_memory"), row("s1", 1, 4, slot=1),
            row("f2", 4, 10, "no_memory", 1), row("s2", 8, 13)]
    result = calculate_arm_times(2, rows, 0, 13)
    # The system's own replay 3,5 finishes at 5; the union covers the run. The floor alone takes 8.
    assert result["arms"]["system"]["replay_ms"] == 5
    assert result["arms"]["system"]["arm_time_ms"] == 5
    assert result["floor_replay_ms"] == 8


def test_same_start_order_gives_the_same_time_with_or_without_the_floor():
    fresh = calculate_arm_times(2, [row("f1", 0, 8, "no_memory"), row("f2", 0, 6, "no_memory", 1),
                                    row("s1", 8, 11), row("s2", 8, 13, slot=1)], 0, 15)
    cached = calculate_arm_times(2, [row("s1", 0, 3), row("s2", 0, 5, slot=1)], 0, 7)
    assert fresh["arms"]["system"]["arm_time_ms"] == cached["arms"]["system"]["arm_time_ms"] == 7
    assert (fresh["floor_replay_ms"], cached["floor_replay_ms"]) == (8, 0)


def test_empty_and_cached_floor_and_clock_tolerance():
    assert calculate_arm_times(2, [], 0, 10)["arms"] == {}
    result = calculate_arm_times(2, [row("s", -1000, 1100)], 0, 100)
    assert result["floor_replay_ms"] == 0
    assert result["arms"]["system"]["outside_ms"] == 0
    assert result["arms"]["system"]["arm_time_ms"] == 2100
    assert calculate_arm_times(2, [row("f", 0, 5, "no_memory")], 0, 10)["floor_replay_ms"] == 5


@pytest.mark.parametrize("slots,rows,start,end", [
    (0, [], 0, 10), (-1, [], 0, 10), (1, [row("s", 3, 2)], 0, 10),
    (2, [row("s", 0, 1, slot=-1)], 0, 10), (2, [row("s", 0, 1, slot=2)], 0, 10),
    (1, [row("s", -1001, 1)], 0, 10), (1, [row("s", 0, 1011)], 0, 10),
    (1, [], 10, 0), (1, [row("s", 0, float("inf"))], 0, 10),
])
def test_invalid_inputs(slots, rows, start, end):
    with pytest.raises(ValueError):
        calculate_arm_times(slots, rows, start, end)
