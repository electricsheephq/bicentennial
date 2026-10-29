"""Issue #223: exact estimands, permutation tails, keyed CIs and Holm."""

import os
import subprocess
import sys
from fractions import Fraction
from itertools import product
from pathlib import Path

import pytest

from bicentennial import keyed
from bicentennial.stats import core, tcal
from bicentennial.stats.core import bootstrap_ci, contributions, holm, sign_flip_p


@pytest.mark.parametrize("keep_lives", [("l3", "l1", "l2"), ("l1",)])
def test_contribution_mean_equals_independent_headline(keep_lives):
    lives = ("l3", "l1", "l2")
    valid = {"Wake": ("l3", "l1", "l2"), "Keep": keep_lives}
    a = {("Wake", "l1"): Fraction(8, 3), ("Wake", "l2"): 5,
         ("Wake", "l3"): -2, ("Keep", "l1"): 9,
         ("Keep", "l2"): -1, ("Keep", "l3"): Fraction(7, 2)}
    b = {("Wake", "l1"): Fraction(2, 3), ("Wake", "l2"): 1,
         ("Wake", "l3"): 1, ("Keep", "l1"): 1,
         ("Keep", "l2"): 2, ("Keep", "l3"): Fraction(1, 2)}
    a = {key: value for key, value in a.items() if key[1] in valid[key[0]]}
    b = {key: value for key, value in b.items() if key[1] in valid[key[0]]}
    # Independently average each system's track means, then subtract headlines.
    headline_a = sum((sum((Fraction(a[track, life]) for life in lives), Fraction(0))
                      / len(lives) for track, lives in valid.items()), Fraction(0)) / 2
    headline_b = sum((sum((Fraction(b[track, life]) for life in lives), Fraction(0))
                      / len(lives) for track, lives in valid.items()), Fraction(0)) / 2
    result = contributions(a, b, valid, lives=lives)
    assert sum(result.values(), Fraction(0)) / 3 == headline_a - headline_b
    assert list(result) == ["l1", "l2", "l3"]
    assert all(isinstance(value, Fraction) for value in result.values())
    if len(keep_lives) == 1:
        # Keep's contribution is multiplied by 3, not diluted across 3 lives.
        assert result == {"l1": Fraction(13), "l2": Fraction(2), "l3": Fraction(-3, 2)}
    else:
        assert result == {"l1": Fraction(5), "l2": Fraction(1, 2), "l3": Fraction(0)}
    assert contributions(dict(reversed(tuple(a.items()))), dict(reversed(tuple(b.items()))),
                         dict(reversed(tuple(valid.items()))), lives=tuple(reversed(lives))) == result


def test_budget_subset_uses_same_common_set_reweighting():
    # All scores are already K10 scores; the declared Keep subset is k1,k2.
    a = {("Wake", "k1"): 4, ("Wake", "k2"): 2, ("Keep", "k1"): 6}
    b = dict.fromkeys(a, 0)
    result = contributions(a, b, {"Wake": ("k2", "k1"), "Keep": ("k1",)}, lives=("k1", "k2"))
    assert result == {"k1": Fraction(8), "k2": Fraction(1)}
    assert sum(result.values()) / 2 == Fraction(9, 2)


def test_contributions_include_life_without_any_valid_bundle():
    lives = ("l3", "l2", "l1")
    valid = {"Wake": ("l1", "l2"), "Keep": ("l1",)}
    a = {("Wake", "l1"): 4, ("Wake", "l2"): 2, ("Keep", "l1"): 6}
    b = dict.fromkeys(a, 0)
    result = contributions(a, b, valid, lives=lives)
    # Weights are 3/(2*2) for Wake and 3/(2*1) for Keep.
    assert result == {"l1": Fraction(12), "l2": Fraction(3, 2), "l3": Fraction(0)}
    assert list(result) == ["l1", "l2", "l3"]
    assert isinstance(result["l3"], Fraction)
    headline_difference = sum(
        (sum((Fraction(a[track, life]) - Fraction(b[track, life]) for life in track_lives),
             Fraction(0)) / len(track_lives) for track, track_lives in valid.items()),
        Fraction(0)) / len(valid)
    assert sum(result.values(), Fraction(0)) / len(lives) == headline_difference == Fraction(9, 2)


@pytest.mark.parametrize("lives", [(), ("l1",)])
def test_contributions_refuses_universe_missing_valid_life(lives):
    a = {("Wake", "l1"): 1, ("Keep", "l2"): 2}
    b = dict.fromkeys(a, 0)
    with pytest.raises(ValueError, match="lives must include every life in the valid sets"):
        contributions(a, b, {"Wake": ("l1",), "Keep": ("l2",)}, lives=lives)


@pytest.mark.parametrize("side", ["a", "b"])
@pytest.mark.parametrize("problem", ["missing", "outside_life", "outside_track"])
def test_contributions_refuses_missing_or_outside_scores(side, problem):
    a, b = {("Wake", "l1"): 1}, {("Wake", "l1"): 0}
    target = a if side == "a" else b
    if problem == "missing":
        target.clear()
    elif problem == "outside_life":
        target["Wake", "l2"] = 2
    else:
        target["Keep", "l1"] = 2
    with pytest.raises(ValueError, match="missing score|outside valid set"):
        contributions(a, b, {"Wake": ("l1",)}, lives=("l1",))


@pytest.mark.parametrize("valid", [{}, {"Wake": ()}, {"Wake": ("l1",), "Keep": ()}])
def test_contributions_refuses_empty_support(valid):
    with pytest.raises(ValueError, match="at least one track|empty common valid set"):
        contributions({}, {}, valid, lives=("l1",))


@pytest.mark.parametrize("n", [12, 16, 20])
def test_exact_positive_floor_and_cutoff(n, monkeypatch):
    def forbidden_draw(*args):
        raise AssertionError("n <= 20 must use exhaustive enumeration")

    monkeypatch.setattr(core, "draw", forbidden_draw)
    values = [Fraction(i + 1, 7) for i in range(n)]
    assert sign_flip_p(values, seed="floor", name="primary") == Fraction(2, 2**n)


@pytest.mark.parametrize("n", [1, 12, 24])
def test_all_zero_p_is_one(n):
    assert sign_flip_p([Fraction(0)] * n, seed="zero", name="primary") == Fraction(1)


@pytest.mark.parametrize("values", [
    [Fraction(1, 3), Fraction(-2, 5), Fraction(7, 11), 0, -1],
    [1, 1, -1],
    [1, -1],
])
def test_exact_tail_matches_independent_enumeration(values):
    observed = abs(sum(values))
    count = sum(abs(sum((sign * value for sign, value in zip(signs, values, strict=True)),
                        Fraction(0))) >= observed
                for signs in product((-1, 1), repeat=len(values)))
    expected = Fraction(count, 2**len(values))
    assert sign_flip_p(values, seed="unused", name="primary") == expected
    assert sign_flip_p([-v for v in values], seed="other", name="other") == expected
    assert sign_flip_p([77 * v for v in values], seed="unused", name="primary") == expected


def test_monte_carlo_observed_correction_and_independent_keys(monkeypatch):
    calls = 0
    first = []

    def controlled_draw(seed, unit, attempt, name):
        nonlocal calls
        calls += 1
        if attempt < 2:
            first.append((seed, unit, attempt, name))
        # Only replicate 0 (all +) and replicate 1 (all -) meet |sum|=24.
        return int(attempt == 0 or (attempt > 1 and unit[-1] == "0"))

    monkeypatch.setattr(core, "draw", controlled_draw)
    assert sign_flip_p([1] * 24, seed="mc", name="contrast") == Fraction(3, 100_001)
    assert calls == 100_000 * 24
    assert first == [("mc", ("stats", "sign_flip", str(life)), replicate, "contrast")
                     for replicate in range(2) for life in range(24)]


def test_monte_carlo_seed_reproducibility_and_sensitivity():
    values = {f"life-{i:02}": Fraction((-1)**i * (i + 1), i % 5 + 1)
              for i in range(24)}
    first = sign_flip_p(values, seed="mc-seed-a", name="primary")
    second = sign_flip_p(dict(reversed(tuple(values.items()))), seed="mc-seed-a", name="primary")
    other = sign_flip_p(values, seed="mc-seed-b", name="primary")
    assert isinstance(first, Fraction)
    assert first == second
    assert first != other
    assert 0 < first <= 1
    assert (first * 100_001).denominator == 1


def test_bootstrap_centering_percentile_indices_and_keys(monkeypatch):
    signs = ((0, 0), (1, 0), (0, 1), (1, 1))
    calls = []

    def controlled_draw(seed, unit, attempt, name):
        calls.append((seed, unit, attempt, name))
        return signs[attempt][int(unit[-1])]

    monkeypatch.setattr(core, "draw", controlled_draw)
    # Mean=2, deviations=(-1,+1); replicates in draw order are [2,1,3,2].
    # At n=2 the calibrated tail is zero ppm, selecting both extrema.
    assert bootstrap_ci([1, 3], seed="ci", name="headline", draws=4) == (Fraction(1), Fraction(3))
    assert calls == [("ci", ("stats", "bootstrap", str(life)), replicate, "headline")
                     for replicate in range(4) for life in range(2)]


def test_bootstrap_24_life_calibrated_endpoints_from_keyed_draws():
    seed, name, draws = "tcal-247", "headline", 10_000
    values = {f"life-{i:02}": Fraction((i - 12) * (i + 1), 2 if i % 2 else 3)
              for i in range(24)}
    # All values have denominators dividing six; keep reconstruction in integers.
    n, scale = len(values), 6
    integers = {life: int(value * scale) for life, value in values.items()}
    total = sum(integers.values())
    replicates = sorted(
        n * total + sum((n * value - total)
                        * (1 if keyed.draw(seed, ("stats", "bootstrap", life), attempt, name) & 1
                           else -1)
                        for life, value in integers.items())
        for attempt in range(draws))
    denominator = n * n * scale
    result = bootstrap_ci(values, seed=seed, name=name, draws=draws)
    assert result == (Fraction(replicates[172], denominator),
                      Fraction(replicates[9827], denominator))
    assert all(isinstance(bound, Fraction) for bound in result)


def test_bootstrap_seed_reproducibility_and_sensitivity():
    values = {f"life-{i:02}": Fraction((-1)**i * (i + 1)**3, i + 2)
              for i in range(24)}
    first = bootstrap_ci(values, seed="ci-seed-a", name="headline")
    second = bootstrap_ci(dict(reversed(tuple(values.items()))), seed="ci-seed-a", name="headline")
    other = bootstrap_ci(values, seed="ci-seed-b", name="headline")
    assert first == second
    assert first != other
    assert all(isinstance(bound, Fraction) for bound in first)
    assert first[0] <= first[1]


@pytest.mark.parametrize("values", [[Fraction(7, 3)], [Fraction(7, 3)] * 4])
def test_bootstrap_constant_and_single_draw(values):
    assert bootstrap_ci(values, seed="constant", name="ci", draws=1) == (Fraction(7, 3),) * 2


def test_bootstrap_single_life_retains_uncalibrated_indices(monkeypatch):
    def forbidden_calibration(*args):
        raise AssertionError("a single life must retain the existing indices")

    monkeypatch.setattr(tcal, "ppm", forbidden_calibration)
    monkeypatch.setattr(tcal, "index", forbidden_calibration)
    monkeypatch.setattr(core, "draw", lambda seed, unit, attempt, name: attempt & 1)
    assert bootstrap_ci([Fraction(7, 3)], seed="single", name="ci", draws=40) == (Fraction(7, 3),) * 2


def test_holm_hand_worked_three_hypotheses():
    # Sorted p=.01,.04,.20; Holm products=.03,.08,.20.
    values = {"middle": Fraction(4, 100), "last": Fraction(20, 100), "first": Fraction(1, 100)}
    result = holm(values)
    assert result == {"middle": (Fraction(8, 100), False),
                      "last": (Fraction(20, 100), False), "first": (Fraction(3, 100), True)}
    assert list(result) == list(values)
    assert values["middle"] < Fraction(5, 100)  # Unadjusted rejection disappears.


def test_holm_cumulative_max_cap_ties_and_boundary():
    # Sorted products=.04,.03,1.2,.9 -> cumulative max and cap=.04,.04,1,1.
    values = {"z": Fraction(1, 100), "a": Fraction(1, 100),
              "large": Fraction(3, 5), "largest": Fraction(9, 10)}
    result = holm(values, alpha=Fraction(4, 100))
    assert list(result) == ["z", "a", "large", "largest"]
    assert result == {"z": (Fraction(4, 100), True), "a": (Fraction(4, 100), True),
                      "large": (Fraction(1), False), "largest": (Fraction(1), False)}
    assert holm({}) == {}


@pytest.mark.parametrize("function", [sign_flip_p, bootstrap_ci])
def test_empty_values_refused(function):
    with pytest.raises(ValueError, match="at least one life"):
        function([], seed="seed", name="name")


@pytest.mark.parametrize("draws", [0, -1, True, Fraction(2)])
def test_invalid_bootstrap_draws_refused(draws):
    with pytest.raises(ValueError, match="positive integer"):
        bootstrap_ci([1, 2], seed="seed", name="name", draws=draws)


@pytest.mark.parametrize("level", [Fraction(0), Fraction(1), Fraction(-1, 10), Fraction(11, 10)])
def test_invalid_bootstrap_level_refused(level):
    with pytest.raises(ValueError, match="^level must lie strictly between zero and one$"):
        bootstrap_ci([1, 2], seed="seed", name="name", level=level)


@pytest.mark.parametrize("level", [Fraction(1, 2), Fraction(2, 3), Fraction(90, 100)])
@pytest.mark.parametrize("values", [[1], [1, 2]])
def test_uncalibrated_bootstrap_level_refused(level, values):
    with pytest.raises(ValueError, match=r"^only the 95% interval is calibrated \(#247\)$"):
        bootstrap_ci(values, seed="seed", name="name", level=level)


@pytest.mark.parametrize("value", [Fraction(-1, 10), Fraction(11, 10)])
def test_invalid_holm_probabilities_refused(value):
    with pytest.raises(ValueError, match="p-values"):
        holm({"h": value})
    with pytest.raises(ValueError, match="alpha"):
        holm({"h": Fraction(1, 2)}, alpha=value)


@pytest.mark.parametrize("value", [0.5, True])
def test_inexact_or_boolean_inputs_refused(value):
    with pytest.raises(TypeError, match="Fraction or int"):
        contributions({("t", "l"): value}, {("t", "l"): 0}, {"t": ("l",)}, lives=("l",))
    for function in (sign_flip_p, bootstrap_ci):
        with pytest.raises(TypeError, match="Fraction or int"):
            function([value], seed="seed", name="name")
    with pytest.raises(TypeError, match="Fraction or int"):
        bootstrap_ci([1], seed="seed", name="name", level=value)
    with pytest.raises(TypeError, match="Fraction or int"):
        holm({"h": value})
    with pytest.raises(TypeError, match="Fraction or int"):
        holm({"h": 1}, alpha=value)


def test_outputs_are_byte_identical_across_hashseeds():
    # Written now for CI/owner execution after the measurement hold lifts.
    code = """
from fractions import Fraction
from bicentennial.stats.core import contributions, sign_flip_p, bootstrap_ci, holm
lives = {"l1", "l2", "l3"}
valid = {track: lives if track == "Wake" else {"l1"} for track in {"Wake", "Keep"}}
a = {(track, life): Fraction(int(life[-1]), 3) for track in valid for life in valid[track]}
b = dict.fromkeys(a, 0)
c = contributions(a, b, valid, lives=lives)
print(repr(c))
print(repr(sign_flip_p(c, seed="hashseed", name="primary")))
print(repr(bootstrap_ci(c, seed="hashseed", name="ci", draws=100)))
# Holm's family order is explicitly declared, including ties.
print(repr(holm({"z": Fraction(1,100), "a": Fraction(1,100), "b": Fraction(1,5)})))
"""
    root = Path(__file__).resolve().parents[2]
    outputs = []
    for hashseed in ("0", "1", "917"):
        env = dict(os.environ, PYTHONHASHSEED=hashseed, PYTHONPATH=str(root / "src"))
        result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env,
                                capture_output=True, check=True)
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
