"""Hand-computed Keep tier placement, cause labels and track weights."""

from fractions import Fraction

import pytest

from bicentennial.score.keep import t_keep, tier_scores

TIERS = ("K100", "K30", "K10", "K3")


def test_non_capping_eight_percent_worked_example():
    scores = dict.fromkeys(TIERS, 1)
    result = tier_scores(scores, store_bytes=dict.fromkeys(TIERS, 8), raw_bytes=100,
                         can_cap=False)
    assert result == {
        "K100": {"score": Fraction(1), "cause": None},
        "K30": {"score": Fraction(1), "cause": None},
        "K10": {"score": Fraction(1), "cause": None},
        "K3": {"score": Fraction(0), "cause": "unsupported"},
    }
    assert t_keep(result["K100"]["score"], result["K10"]["score"]) == 1
    assert scores == dict.fromkeys(TIERS, 1)


def test_capping_above_every_reduced_cap():
    scores = {"K100": Fraction(2, 3), "K30": 1, "K10": 1, "K3": 1}
    result = tier_scores(scores, store_bytes=dict.fromkeys(TIERS, 31), raw_bytes=100,
                         can_cap=True)
    assert result["K100"] == {"score": Fraction(2, 3), "cause": None}
    for tier in ("K30", "K10", "K3"):
        assert result[tier] == {"score": Fraction(0), "cause": "over_cap"}
    assert t_keep(result["K100"]["score"], result["K10"]["score"]) == Fraction(1, 6)


@pytest.mark.parametrize("can_cap,cause", [(True, "over_cap"), (False, "unsupported")])
def test_each_tier_reads_its_own_branch(can_cap, cause):
    # A large base-life store does not zero a reduced tier whose own branch fits.
    sizes = {"K100": 90, "K30": 30, "K10": 11, "K3": 3}
    scores = {"K100": 1, "K30": Fraction(2, 3), "K10": Fraction(1, 3), "K3": -1}
    before = scores.copy()
    result = tier_scores(scores, store_bytes=sizes, raw_bytes=100, can_cap=can_cap)
    assert result == {
        "K100": {"score": Fraction(1), "cause": None},
        "K30": {"score": Fraction(2, 3), "cause": None},
        "K10": {"score": Fraction(0), "cause": cause},
        "K3": {"score": Fraction(-1), "cause": None},
    }
    assert scores == before
    assert sizes == {"K100": 90, "K30": 30, "K10": 11, "K3": 3}


@pytest.mark.parametrize("can_cap", [True, False])
@pytest.mark.parametrize("score", [-1, 0, 1, Fraction(1, 3), 1000])
def test_same_score_at_every_tier_is_keep_score(can_cap, score):
    result = tier_scores(dict.fromkeys(TIERS, score), store_bytes=dict.fromkeys(TIERS, 3),
                         raw_bytes=100, can_cap=can_cap)
    assert result == {tier: {"score": Fraction(score), "cause": None} for tier in TIERS}
    actual = t_keep(result["K100"]["score"], result["K10"]["score"])
    assert actual == score
    assert isinstance(actual, Fraction)


def test_measured_scores_are_used_without_mutation():
    scores = {"K100": 1, "K30": Fraction(2, 3), "K10": Fraction(1, 3), "K3": -1}
    before = scores.copy()
    result = tier_scores(scores, store_bytes=dict.fromkeys(TIERS, 0), raw_bytes=100,
                         can_cap=True)
    assert result == {tier: {"score": Fraction(value), "cause": None}
                      for tier, value in before.items()}
    assert t_keep(result["K100"]["score"], result["K10"]["score"]) == Fraction(1, 2)
    assert scores == before


@pytest.mark.parametrize("can_cap", [True, False])
def test_tiers_that_did_not_run_are_absent(can_cap):
    # The board runs K100 and K10; K30 and K3 run only in the robustness study.
    result = tier_scores({"K100": 1, "K10": Fraction(1, 2)},
                         store_bytes={"K100": 8, "K10": 8}, raw_bytes=100, can_cap=can_cap)
    assert result == {"K100": {"score": Fraction(1), "cause": None},
                      "K10": {"score": Fraction(1, 2), "cause": None}}


@pytest.mark.parametrize("can_cap,cause", [(True, "over_cap"), (False, "unsupported")])
@pytest.mark.parametrize("store_bytes,raw_bytes", [(101, 100), (1, 0)])
def test_above_k100_zeroes_every_tier(can_cap, cause, store_bytes, raw_bytes):
    result = tier_scores(dict.fromkeys(TIERS, -1),
                         store_bytes=dict.fromkeys(TIERS, store_bytes),
                         raw_bytes=raw_bytes, can_cap=can_cap)
    assert result == {tier: {"score": Fraction(0), "cause": cause} for tier in TIERS}


@pytest.mark.parametrize("can_cap", [True, False])
def test_tier_scores_rejects_unknown_tiers(can_cap):
    sizes = dict.fromkeys(TIERS, 0)
    with pytest.raises(ValueError, match="^unknown Keep tier$"):
        tier_scores({**dict.fromkeys(TIERS, 1), "unknown": 1},
                    store_bytes=sizes, raw_bytes=100, can_cap=can_cap)
    with pytest.raises(ValueError, match="^unknown Keep tier$"):
        tier_scores(dict.fromkeys(TIERS, 1), store_bytes={**sizes, "unknown": 0},
                    raw_bytes=100, can_cap=can_cap)


@pytest.mark.parametrize("scores,sizes", [
    ({"K100": 1, "K10": 1}, {"K100": 0}),
    ({"K100": 1}, {"K100": 0, "K10": 0}),
])
def test_every_scored_tier_needs_its_store_size(scores, sizes):
    with pytest.raises(ValueError, match="^every scored Keep tier needs its store size$"):
        tier_scores(scores, store_bytes=sizes, raw_bytes=100, can_cap=True)


@pytest.mark.parametrize("can_cap", [True, False])
def test_tier_scores_requires_the_base_life(can_cap):
    with pytest.raises(ValueError, match="^missing K100 base-life measurement$"):
        tier_scores({"K10": 1}, store_bytes={"K10": 0}, raw_bytes=100, can_cap=can_cap)


def test_t_keep_preserves_fractional_milli_units():
    assert t_keep(1, 0) == Fraction(1, 4)
    assert t_keep(0, 1) == Fraction(3, 4)
    assert t_keep(Fraction(-1, 3), Fraction(1, 7)) == Fraction(1, 42)
