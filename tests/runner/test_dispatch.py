"""Frozen checkpoint-dispatch clauses, with no runner or upstream calls."""

from dataclasses import FrozenInstanceError
from hashlib import sha256

import pytest

from bicentennial import keyed
from bicentennial.canon import canon
from bicentennial.runner import dispatch as dispatch_module
from bicentennial.runner.dispatch import (
    DISPATCH_DRAW_LABEL,
    ArmEvents,
    DispatchResult,
    NonArrival,
    PassOver,
    anchor_order,
    dispatch,
)

UNIT = ("seed", "life-1", "B0", 20)
CAUSES = ("replay_stopped", "life_bound", "start_window")


def test_anchor_order_oracle_and_identity():
    refs = [sha256(str(i).encode()).hexdigest() for i in range(40)]
    expected = sorted(refs, key=lambda ref: (
        int.from_bytes(sha256(canon(["s", ["L", "anchor", "order"], 0, ref])).digest()[:8], "big"), ref))
    actual = anchor_order("s", "L", reversed(refs))
    assert actual == expected and sorted(actual) == sorted(refs) and len(set(actual)) == len(refs)
    assert anchor_order("other", "L", refs) != actual
    assert anchor_order("s", "other", refs) != actual


def test_anchor_order_ties(ordered_draws):
    assert anchor_order("s", "L", ["c", "a", "b"]) == ["a", "b", "c"]


def _followed_order(seed, arm_ids):
    """Observe every rank by passing over the prefix already observed."""
    arms = {arm_id: ArmEvents(arrival_time=10) for arm_id in arm_ids}
    order = []
    for _ in arm_ids:
        result = dispatch(seed, *UNIT[1:], arms)
        order.append(result.followed_arm)
        arms[result.followed_arm] = ArmEvents(pass_over=PassOver(0, "replay_stopped"))
    return order


@pytest.fixture
def ordered_draws(monkeypatch):
    """Pin alphabetical order to isolate timing from the real keyed order."""
    monkeypatch.setattr(dispatch_module, "draw", lambda seed, unit, attempt, name: 0)


def test_order_matches_keyed_draw_and_survives_resume_and_input_reordering():
    arm_ids = tuple(f"arm-{i:02d}" for i in range(12))
    expected = sorted(arm_ids, key=lambda arm_id: (
        keyed.draw("seed", ("life-1", "B0", "20", arm_id), 0, "dispatch"), arm_id,
    ))
    first = _followed_order("seed", arm_ids)
    _followed_order("unrelated-block", arm_ids)
    assert first == expected
    assert _followed_order("seed", arm_ids) == first
    assert _followed_order("seed", tuple(reversed(arm_ids))) == first


def test_order_changes_with_seed():
    arm_ids = tuple(f"arm-{i:02d}" for i in range(12))
    assert _followed_order("seed", arm_ids) != _followed_order("other-seed", arm_ids)


def test_draw_uses_complete_unit_attempt_zero_and_frozen_label(monkeypatch):
    calls = []

    def record_draw(seed, unit, attempt, name):
        calls.append((seed, unit, attempt, name))
        return {"a": 9, "b": 2}[unit[-1]]

    monkeypatch.setattr(dispatch_module, "draw", record_draw)
    arms = {"a": ArmEvents(arrival_time=1), "b": ArmEvents(arrival_time=2)}
    assert dispatch("s", "L", "B1", 120, arms).followed_arm == "b"
    assert DISPATCH_DRAW_LABEL == "dispatch"
    assert calls == [
        ("s", ("L", "B1", "120", "a"), 0, "dispatch"),
        ("s", ("L", "B1", "120", "b"), 0, "dispatch"),
    ]


def test_draw_ties_use_arm_id(ordered_draws):
    assert _followed_order("seed", ("c", "a", "b")) == ["a", "b", "c"]


def test_waiting_arm_holds_release_and_can_later_arrive(ordered_draws):
    arms = {
        "a": ArmEvents(pass_over=PassOver(40, "replay_stopped")),
        "b": ArmEvents(),
        "c": ArmEvents(arrival_time=5),
    }
    assert dispatch(*UNIT, arms) == DispatchResult("b", None, None, 0, False)
    arms["b"] = ArmEvents(arrival_time=80)
    assert dispatch(*UNIT, arms) == DispatchResult("b", 80, 80, 0, False)


@pytest.mark.parametrize(("arrival", "release", "lag"), [
    (20, 90, 70), (90, 90, 0), (120, 120, 0),
])
def test_release_uses_latest_prefix_pass_over(ordered_draws, arrival, release, lag):
    # Keyed rank and chronological pass-over order need not agree.
    arms = {
        "a": ArmEvents(pass_over=PassOver(90, "life_bound")),
        "b": ArmEvents(pass_over=PassOver(30, "start_window")),
        "c": ArmEvents(arrival_time=arrival),
        "d": ArmEvents(pass_over=PassOver(999, "replay_stopped")),
    }
    assert dispatch(*UNIT, arms) == DispatchResult("c", arrival, release, lag, False)


def test_arrival_before_later_pass_over_still_counts(ordered_draws):
    arms = {
        "a": ArmEvents(pass_over=PassOver(100, "replay_stopped")),
        "b": ArmEvents(arrival_time=20, pass_over=PassOver(30, "life_bound")),
        "c": ArmEvents(arrival_time=1),
    }
    assert dispatch(*UNIT, arms) == DispatchResult("b", 20, 100, 80, False)


@pytest.mark.parametrize("arrival", [30, 40])
def test_arrival_at_or_after_own_pass_over_does_not_count(ordered_draws, arrival):
    arms = {
        "a": ArmEvents(arrival_time=arrival, pass_over=PassOver(30, "life_bound")),
        "b": ArmEvents(arrival_time=10),
    }
    assert dispatch(*UNIT, arms) == DispatchResult("b", 10, 30, 20, False)


def test_all_arms_passed_over_release_at_latest_time_unmatched(ordered_draws):
    arms = {
        "a": ArmEvents(pass_over=PassOver(90, "replay_stopped")),
        "b": ArmEvents(pass_over=PassOver(10, "life_bound")),
        "c": ArmEvents(pass_over=PassOver(50, "start_window")),
    }
    assert dispatch(*UNIT, arms) == DispatchResult(None, None, 90, 0, True)


@pytest.mark.parametrize("kind", ["fault_fork", "aa_rerun", "comparator_chain"])
def test_other_chain_arrivals_cannot_release_or_prevent_pass_over(ordered_draws, kind):
    evidence = (NonArrival(1, kind),)
    arms = {"a": ArmEvents(non_arrivals=evidence), "b": ArmEvents(arrival_time=2)}
    assert dispatch(*UNIT, arms) == DispatchResult("a", None, None, 0, False)
    arms["a"] = ArmEvents(pass_over=PassOver(30, "replay_stopped"), non_arrivals=evidence)
    assert dispatch(*UNIT, arms) == DispatchResult("b", 2, 30, 28, False)
    arms["a"] = ArmEvents(arrival_time=20, non_arrivals=evidence)
    assert dispatch(*UNIT, arms) == DispatchResult("a", 20, 20, 0, False)


@pytest.mark.parametrize("cause", CAUSES)
def test_each_frozen_pass_over_cause_is_accepted(cause):
    assert dispatch(*UNIT, {"a": ArmEvents(pass_over=PassOver(7, cause))}) == (
        DispatchResult(None, None, 7, 0, True)
    )


@pytest.mark.parametrize("cause", ["quota", "hold", "pending_infra", "unknown", "", None])
def test_other_causes_are_rejected(cause):
    with pytest.raises(ValueError, match="pass-over cause"):
        PassOver(1, cause)


@pytest.mark.parametrize("time", [0.0, 1.5, True, "1"])
def test_event_times_require_exact_integers(time):
    with pytest.raises(TypeError, match="integer milliseconds"):
        ArmEvents(arrival_time=time)
    with pytest.raises(TypeError, match="integer milliseconds"):
        PassOver(time, "life_bound")
    with pytest.raises(TypeError, match="integer milliseconds"):
        NonArrival(time, "fault_fork")


def test_negative_event_times_are_rejected():
    with pytest.raises(ValueError, match="block's first request"):
        ArmEvents(arrival_time=-1)
    with pytest.raises(ValueError, match="block's first request"):
        PassOver(-1, "life_bound")
    with pytest.raises(ValueError, match="block's first request"):
        NonArrival(-1, "fault_fork")


@pytest.mark.parametrize("time", [0, (1 << 80) + 1])
def test_zero_and_large_times_remain_exact_without_independent_bound(time):
    result = dispatch(*UNIT, {"a": ArmEvents(arrival_time=time)})
    assert result == DispatchResult("a", time, time, 0, False)
    assert type(result.release_time) is int
    assert type(result.lag) is int


def test_empty_eligible_set_is_exhausted_without_inventing_a_time():
    assert dispatch(*UNIT, {}) == DispatchResult(None, None, None, 0, True)


def test_records_are_frozen_and_dispatch_leaves_input_unchanged():
    non_arrival = NonArrival(1, "fault_fork")
    passed = PassOver(30, "life_bound")
    evidence = [non_arrival]
    events = ArmEvents(arrival_time=20, pass_over=passed, non_arrivals=evidence)
    evidence.clear()
    assert events.non_arrivals == (non_arrival,)
    arms = {"a": events}
    before = dict(arms)
    result = dispatch(*UNIT, arms)
    assert arms == before
    assert result == dispatch(*UNIT, arms)
    for record, field, value in (
        (non_arrival, "time", 5), (passed, "time", 5),
        (events, "arrival_time", 5), (result, "lag", 5),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(record, field, value)


def test_malformed_nested_records_are_rejected():
    with pytest.raises(TypeError, match="PassOver record"):
        ArmEvents(pass_over=30)
    with pytest.raises(TypeError, match="NonArrival records"):
        ArmEvents(non_arrivals=(1,))
    with pytest.raises(ValueError, match="non-arrival kind"):
        NonArrival(1, "own_chain")
