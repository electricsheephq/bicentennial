"""Independent rational witnesses for the bar-2 pilot estimator."""

import math
import statistics
from fractions import Fraction
from itertools import combinations

import pytest

from bicentennial.stats import pilot


def test_three_pairs_median_and_even_median():
    lives, tracks = ("l0", "l1", "l2"), ("Wake", "Tuesday")
    bundles = {arm: [[f"{t}-{life}", life, t, "K100", slope * i]
                     for t in tracks for life, i in zip(lives, (-1, 0, 1), strict=True)]
               for arm, slope in (("a", 0), ("b", 10), ("c", 60))}
    pairs = list(combinations(bundles, 2))
    # Equal track weights and complete support give c_l=(slope_a-slope_b)*i.
    expected = {p: math.sqrt(float(statistics.variance([Fraction(d * i, 10) for i in (-1, 0, 1)])))
                for p, d in zip(pairs, (-10, -60, -50), strict=True)}
    assert sorted(expected.values()) == [1.0, 5.0, 6.0]
    assert statistics.mean(expected.values()) != statistics.median(expected.values())
    assert pilot.sigma_d(bundles, pairs, tracks, lives) == (statistics.median(expected.values()), expected)
    even = pairs[:2]
    assert pilot.sigma_d(bundles, even, tracks, lives) == (
        statistics.median([expected[p] for p in even]), {p: expected[p] for p in even})


def test_keep_weight_and_missing_k10():
    lives = ("l0", "l1", "l2")
    a = [["x", "l0", "Keep", "K100", 40], ["y", "l0", "Keep", "K100", 80],
         ["x", "l0", "Keep", "K10", 100], ["z", "l1", "Keep", "K100", 200],
         ["z", "l1", "Keep", "K10", 300], ["w", "l2", "Keep", "K100", 999],
         ["w", "l2", "Keep", "K10", 900]]
    b = [r[:4] + [None if r[0] == "w" and r[3] == "K10" else 0] for r in a]
    # Only two lives support Keep. Reweight by 3/2; average K100 before weighting.
    expected = dict(zip(lives, (Fraction(3, 2) * (Fraction(40 + 80, 8) + Fraction(300, 4)),
                               Fraction(3, 2) * (Fraction(200, 4) + Fraction(900, 4)),
                               Fraction(0)), strict=True))
    bundles = {"a": a, "b": b}
    assert pilot.pair_contributions(bundles, "a", "b", ("Keep",), lives) == expected
    sd = math.sqrt(float(statistics.variance([v / 10 for v in expected.values()])))
    assert pilot.sigma_d(bundles, [("a", "b")], ("Keep",), lives) == (sd, {("a", "b"): sd})


def test_non_keep_ignores_k10_and_unit():
    lives = ("l0", "l1", "l2")
    bundles = {arm: [[f"b{i}", life, "Wake", keep, score]
                     for i, life in enumerate(lives) for keep, score in
                     (("K100", i * 10 if arm == "a" else 0),
                      ("K10", 999 if arm == "a" else -999))] for arm in ("a", "b")}
    expected = {life: Fraction(i * 10) for i, life in enumerate(lives)}
    assert pilot.pair_contributions(bundles, "a", "b", ("Wake",), lives) == expected
    milli_sd = math.sqrt(float(statistics.variance(list(expected.values()))))
    sd = math.sqrt(float(statistics.variance([c / 10 for c in expected.values()])))
    assert milli_sd == sd * 10 == 10
    assert pilot.sigma_d(bundles, [("a", "b")], ("Wake",), lives) == (sd, {("a", "b"): sd})


def test_pair_validity_and_zero_life():
    lives = ("l0", "l1", "l2")
    scores = {"a": (30, 90, 60, None), "b": (0, None, 20, 10), "c": (10, 20, 30, 40)}
    bundles = {arm: [[bid, life, "Wake", "K100", score]
                     for bid, life, score in zip(("x", "y", "z", "w"),
                                                ("l0", "l0", "l1", "l2"), values, strict=True)]
               for arm, values in scores.items()}
    # a/b drops y and w; a/c retains y but drops w; b/c retains w but drops y.
    expected = {("a", "b"): [Fraction(45), Fraction(60), Fraction(0)],
                ("a", "c"): [Fraction(135, 2), Fraction(45), Fraction(0)],
                ("b", "c"): [Fraction(-10), Fraction(-10), Fraction(-30)]}
    deviations = {}
    for (a, b), values in expected.items():
        assert pilot.pair_contributions(bundles, a, b, ("Wake",), lives) == dict(zip(lives, values, strict=True))
        deviations[a, b] = math.sqrt(float(statistics.variance([c / 10 for c in values])))
    assert pilot.sigma_d(bundles, list(expected), ("Wake",), lives) == (
        statistics.median(deviations.values()), deviations)


@pytest.mark.parametrize("tracks", [(), ("Wake",)])
def test_empty_track_guard(tracks):
    with pytest.raises(ValueError, match="track"):
        pilot.pair_contributions({"a": [], "b": []}, "a", "b", tracks, ("l0", "l1"))


def test_pair_and_identity_guards():
    with pytest.raises(ValueError, match="pair"):
        pilot.sigma_d({}, [], ("Wake",), ("l0", "l1"))
    with pytest.raises(ValueError, match="identities"):
        pilot.pair_contributions({"a": [["b", "l0", "Wake", "K100", 0]], "b": []},
                                 "a", "b", ("Wake",), ("l0", "l1"))
