"""Hand arithmetic and exact C7 validation for the average-load reserve."""

import re
from dataclasses import replace
from fractions import Fraction

import pytest

from bicentennial.ocsim import reserve, schedule


@pytest.fixture(scope="module")
def load():
    lives = tuple(schedule.LifeSpec(f"life-{letter}", (1, 1, 1), (1, 1), 2, 3,
                                    (0, 0), (0, 0)) for letter in "abc")
    tokens = {(a, life.life, branch, c): 1000 if i == 0 else 2000
              for i, life in enumerate(lives) for a in ("C", "F", "RAG")
              for branch in schedule.BRANCHES for c in (2, 3)}
    tokens["F", "life-c", "B0", 2] += 1
    return lives, reserve.ProbeOnlyLoad(tokens, {"life-a": 5000, "life-b": 0, "life-c": 0},
                                       {a: 3600 for a in (*reserve.PROBE_ONLY_LOAD, "anchor")})


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def test_hand_load_relabel_and_reserves(load):
    lives, source = load
    assert reserve.lane_load(source, lives, (2, 3)) == {
        "life-a": (12 * 3_600_000, 5 * 3_600_000),
        "life-b": (24 * 3_600_000, 0), "life-c": (24 * 3_600_000 + 3600, 0)}
    for n, expected in ((1, (1, 1)), (2, (1, 1)), (3, (2, 1))):
        pairs = tuple(f"pair-{i:03d}" for i in range(n))
        relabelled = reserve.relabel(source, lives[:n], pairs)
        selected = tuple(replace(life, life=p) for life, p in zip(lives[:n], pairs, strict=True))
        assert reserve.reserves(relabelled, selected, (2, 3)) == expected
        assert {key[1] for key in relabelled.tokens} == set(pairs)
        assert set(relabelled.anchor_tokens) == set(pairs)
        assert all("life-" not in key[1] for key in relabelled.tokens)
    assert "life-c" in source.anchor_tokens  # relabelling never mutates the source
    zero = replace(source, tokens={}, anchor_tokens={life.life: 0 for life in lives})
    assert reserve.reserves(zero, lives, (2, 3)) == (0, 0)
    ceiling = replace(zero, tokens={("CEIL", "life-a", "B0", 3): 1})
    assert reserve.lane_load(ceiling, lives, (2, 3))["life-a"] == (3600, 0)


def test_task_ceiling_and_unstressed_rates(load):
    lives, source = load
    tiny = replace(source, tokens={("F", "life-a", branch, 2): 1 for branch in schedule.BRANCHES},
                   anchor_tokens={life.life: 0 for life in lives},
                   rates={"F": Fraction(1, 3), "anchor": Fraction(1, 3)})
    assert reserve.lane_load(tiny, lives, (2, 3))["life-a"] == (2, 0)


def test_capacity_hand_and_order():
    lanes = (schedule.LaneCapacity("pinned", 4, 3, runner_cap=10),
             schedule.LaneCapacity("swap", 2, 1))
    assert reserve.capacity(lanes, (2, 1)) == schedule.Capacity(8, 1)
    with rejects("reserve must leave at least one chain slot"):
        reserve.capacity(lanes, (2, 2))
    with rejects("lanes must be the pinned and swap lanes, in that order"):
        reserve.capacity(lanes[::-1], (0, 0))
    with rejects("rate-bound lane pinned: slots need an owner ruling"):
        reserve.capacity((replace(lanes[0], rate_per_min=60), lanes[1]), (0, 0))


@pytest.mark.parametrize("key", (("bad", "life-a", "B0", 2),
                                    ("F", "life-z", "B0", 2),
                                    ("F", "life-a", "bad", 2),
                                    ("F", "life-a", "B0", 4)))
def test_bad_probe_key(load, key):
    lives, source = load
    with rejects(f"bad probe-only key: {key}"):
        reserve.lane_load(replace(source, tokens={key: 1}), lives, (2, 3))


@pytest.mark.parametrize("value", (-1, True, 1.0, "1"))
def test_bad_tokens(load, value):
    lives, source = load
    with rejects("probe-only tokens must be ints >= 0"):
        reserve.lane_load(replace(source, tokens={("F", "life-a", "B0", 2): value}), lives, (2, 3))
    with rejects("probe-only tokens must be ints >= 0"):
        reserve.lane_load(replace(source, anchor_tokens={"life-a": value, "life-b": 0, "life-c": 0}),
                          lives, (2, 3))


@pytest.mark.parametrize("rate", (None, 0, -1, True, 1.0))
def test_bad_or_missing_rate(load, rate):
    lives, source = load
    rates = dict(source.rates)
    rates.pop("F")
    if rate is not None:
        rates["F"] = rate
    with rejects("probe-only rate for F must be a positive int or Fraction"):
        reserve.lane_load(replace(source, rates=rates), lives, (2, 3))


def test_anchor_universe_and_rate(load):
    lives, source = load
    for anchors in ({}, {**source.anchor_tokens, "life-z": 0}):
        with rejects("anchor tokens must name every life"):
            reserve.lane_load(replace(source, anchor_tokens=anchors), lives, (2, 3))
    with rejects("probe-only rate for anchor must be a positive int or Fraction"):
        reserve.lane_load(replace(source, rates={"F": 1, "C": 1, "RAG": 1}), lives, (2, 3))
