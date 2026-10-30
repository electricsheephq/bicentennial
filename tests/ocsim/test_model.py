"""Hand values, keyed coupling and validation for the M2 bundle model."""

import math
import random
import re
from bisect import bisect_left
from dataclasses import FrozenInstanceError, fields, replace
from fractions import Fraction
from statistics import NormalDist

import pytest

from bicentennial.controls import cache
from bicentennial.keyed import draw
from bicentennial.ocsim import model
from bicentennial.ocsim.model import (
    ARMS,
    BISECTION_STEPS,
    LOCATION_BOUND,
    SIMPSON_INTERVALS,
    CellModel,
    LatentParams,
    LifeEffects,
    cell_scores,
    default_tau,
    expected_min,
    expected_units,
    interpolation,
    life_effects,
    phi2,
    sample_bundles,
    solve_location,
)


@pytest.fixture
def cell():
    return CellModel("X", (-1000, 0, 1000), (-0.5, 0.5), -200.0, 600.0, 0.0, 0.0)


@pytest.fixture
def params(cell):
    return LatentParams((cell,), 0.25, 0.6, 0.3, 0.2)


def targets_for(value, *, pairs=("p",), checkpoints=(20,), arms=ARMS):
    return {(arm, pair, "X", ckpt): value
            for arm in arms for pair in pairs for ckpt in checkpoints}


@pytest.mark.parametrize("rho,expected", [(-0.5, 1 / 6), (0.0, 1 / 4), (0.5, 1 / 3)])
def test_phi2_origin(rho, expected):
    assert phi2(0.0, 0.0, rho) == pytest.approx(expected, abs=1e-12, rel=0)
    assert phi2(0.0, 0.0, rho) == pytest.approx(
        0.25 + math.asin(rho) / (2 * math.pi), abs=1e-12, rel=0)


def test_phi2_closed_forms():
    normal = NormalDist()
    assert phi2(0.3, -0.2, 0) == normal.cdf(0.3) * normal.cdf(-0.2)
    assert phi2(0.3, -0.2, 1) == normal.cdf(-0.2)
    assert phi2(0.3, -0.2, -1) == max(0, normal.cdf(0.3) + normal.cdf(-0.2) - 1)


@pytest.mark.parametrize("rho,expected", [(0, -500), (0.5, -1000 / 3),
                                           (-0.5, -2000 / 3), (1, 0)])
def test_expected_min_two_levels(cell, rho, expected):
    binary = replace(cell, levels=(-1000, 1000), cuts=(0.0,))
    assert expected_min(binary, rho, 0) == pytest.approx(expected, abs=1e-9, rel=0)


def test_expected_min_three_levels(cell):
    normal = NormalDist()
    expected = -1000 + 1000 * normal.cdf(0.5) ** 2 + 1000 * normal.cdf(-0.5) ** 2
    assert expected_min(cell, 0, 0) == pytest.approx(expected, abs=1e-9, rel=0)


@pytest.mark.parametrize("theta", [-1.0, 0.0, 0.7])
def test_location_round_trip(cell, theta):
    target = expected_min(cell, 0.3, theta)
    assert abs(solve_location(cell, 0.3, target) - theta) < 1e-9


@pytest.mark.parametrize("levels,cuts", [((-1000, 0, 1000), (-0.5, 0.5)),
    ((-1000, -250, 0, 125, 375, 625, 875, 1000), (-1.5, -1, -0.5, 0, 0.5, 1, 1.5))])
@pytest.mark.parametrize("rho", [-0.5, 0.3, 0.98])
def test_interior_target_inversion(levels, cuts, rho):
    from bicentennial.ocsim import locate
    cell = CellModel("X", levels, cuts, -200, 600, 0, 0)
    table = locate.build_table(cell, rho)
    for target in (-400, 0, 283.3, 950):
        assert abs(expected_min(cell, rho, solve_location(cell, rho, target)) - target) <= 1e-6
        assert abs(expected_min(cell, rho, locate.locate(table, cell, target)) - target) <= (
            table.bound_milli + table.max_correction)


def test_interior_no_noise_sampler(cell, monkeypatch):
    params = LatentParams((cell,), 0, 0, 1, 0)
    margin, count = Fraction(25, 3), 4000
    targets = expected_units(params, life_effects(params, ("p",), "interior", 0), {"X": margin})
    draws = iter(v for i in range(count) for v in
                 (0, NormalDist().inv_cdf((i + 0.5) / count), 0,
                  NormalDist().inv_cdf((i + 0.5) / count), 0,
                  NormalDist().inv_cdf((i + 0.5) / count), 0))
    monkeypatch.setattr(model, "_normal", lambda rng: next(draws))
    scores = cell_scores(sample_bundles(params, {(*k, 20): v for k, v in targets.items()},
        {("X", 20): count}, ("p",), "interior", 0))
    s = {arm: scores[arm, "p", "X"] for arm in ARMS}
    for arm in ARMS:
        assert abs(s[arm] - targets[arm, "p", "X"] / 10) <= 2000 / (2 * count) / 10
    assert abs(s["S"] - (s["F"] + s["C"]) / 2 - margin) <= 2000 / count / 10


def test_location_monotone(cell):
    locations = [solve_location(cell, 0.3, t) for t in (-900, -500, -100, 0, 400, 900)]
    assert locations == sorted(locations)


def test_location_ends_and_single_level(cell):
    assert solve_location(cell, 0.3, -1000) == "low"
    assert solve_location(cell, 0.3, -1001) == "low"
    assert solve_location(cell, 0.3, 1000) == "high"
    assert solve_location(cell, 0.3, 1001) == "high"
    singleton = replace(cell, levels=(125,), cuts=())
    for target in (-1000, 125, 1000):
        assert solve_location(singleton, 0.3, target) == "high"
    assert expected_min(singleton, 0.3, -2) == 125.0


@pytest.mark.parametrize("cut,end,reach", [
    # E(10) = -1000 + 2000*Phi(-2)**2 is below 0; E(-10) = -1000 + 2000*Phi(2)**2 is above it.
    (12.0, 10.0, -998.96486), (-12.0, -10.0, 910.03461)])
def test_location_bracket_must_enclose_target(cut, end, reach):
    cell = CellModel("X", (-1000, 1000), (cut,), -200, 600, 0, 0)
    assert expected_min(cell, 0, end) == pytest.approx(reach, abs=1e-5, rel=0)
    message = "location bracket [-10, 10] does not enclose the target"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        solve_location(cell, 0, 0)
    assert str(exc.value) == message


def test_location_bracket_clamps_a_miss_no_score_can_see():
    # E(10) = 1000 - 1000 * (1 - Phi(5)**2), about 1000 - 5.7e-4 at rho_t 0, so a target 1e-4 below
    # the top lies outside the bracket by less than BRACKET_TOL_MILLI and clamps to the end, as before.
    cell = CellModel("Y", (-1000, 0, 1000), (-5.0, 5.0), -200, 600, 0, 0)
    target = 1000 - 1e-4
    assert target - model.BRACKET_TOL_MILLI < expected_min(cell, 0, 10) < target
    assert solve_location(cell, 0, target) == pytest.approx(10.0, abs=1e-9)


def test_exact_margin(params):
    effects = life_effects(params, ("p",), "seed", 0)
    assert interpolation(params.cell("X"), 10) == 0.625
    assert interpolation(params.cell("X"), Fraction(10)) == 0.625
    assert default_tau(params.cell("X"), params.rho_a, 0.625) == 0
    units = expected_units(params, effects, {"X": 10})
    floor, ceiling, system = (units[(arm, "p", "X")] for arm in ARMS)
    assert (floor, ceiling, system) == (-200.0, 600.0, 300.0)
    assert system - (floor + ceiling) / 2 == 100.0
    assert all(type(value) is float for value in units.values())


def test_expected_units_interpolates_before_clipping(params, cell):
    noisy = replace(cell, sigma_f=100.0, sigma_c=200.0)
    params = replace(params, cells=(noisy,))
    effects = LifeEffects({("F", "p", "X"): -20.0, ("C", "p", "X"): 0.0,
                           ("S", "p", "X"): 3.0})
    units = expected_units(params, effects, {"X": 0}, tau={"X": 0.0})
    # Unclipped F=-2200, C=600: S=(-2200+600)/2=-800.
    assert units == {("F", "p", "X"): -1000.0, ("C", "p", "X"): 600.0,
                     ("S", "p", "X"): -800.0}
    assert expected_units(params, effects, {"X": 0}, tau={"X": 1000.0})[
        ("S", "p", "X")] == 1000.0
    negative_system = LifeEffects({**effects.x, ("S", "p", "X"): -3.0})
    assert expected_units(params, negative_system, {"X": 0}, tau={"X": 1000.0})[
        ("S", "p", "X")] == -1000.0


def test_default_tau(cell):
    equal = replace(cell, sigma_f=100.0, sigma_c=100.0)
    assert default_tau(equal, 0, 0.5) == math.sqrt(5000)
    assert default_tau(equal, 1, 0.5) == 0.0
    ceiling_only = replace(cell, sigma_c=200.0)
    assert default_tau(ceiling_only, 0, 0.5) == math.sqrt(30000)


def test_default_tau_floors_negative_variance(cell):
    # The helper is also defined for supplied lambda values beyond interpolation's range.
    equal = replace(cell, sigma_f=100.0, sigma_c=100.0)
    assert default_tau(equal, 0, 2) == 0.0


def test_correlation_helpers():
    assert model._corr_pair(1.0, 2.0, 0.0) == (1.0, 2.0)
    assert model._corr_pair(1.0, 2.0, 0.6) == pytest.approx((1.0, 2.2), abs=1e-12, rel=0)
    assert model._equicorr(3.0, 4.0, 0.0) == 4.0
    assert model._corr_pair(1.0, 2.0, 1.0) == (1.0, 1.0)
    assert model._corr_pair(1.0, 2.0, -1.0) == (1.0, -1.0)


def test_determinism_and_common_random_numbers(params, cell):
    params = replace(params, cells=(replace(cell, sigma_f=10.0, sigma_c=20.0),))
    effects = life_effects(params, ("p",), "seed", 2)
    assert effects == life_effects(params, ("p",), "seed", 2)
    zero = expected_units(params, effects, {"X": 0})
    ten = expected_units(params, effects, {"X": 10})
    assert zero == expected_units(params, effects, {"X": 0})
    for arm in ("F", "C"):
        assert zero[(arm, "p", "X")] == ten[(arm, "p", "X")]
    alloc = {("X", 20): 4}
    first_targets = {(*key, 20): value for key, value in zero.items()}
    second_targets = {(*key, 20): value for key, value in ten.items()}
    first = sample_bundles(params, first_targets, alloc, ("p",), "seed", 2)
    assert first == sample_bundles(params, first_targets, alloc, ("p",), "seed", 2)
    second = sample_bundles(params, second_targets, alloc, ("p",), "seed", 2)
    controls = {key: value for key, value in first_targets.items() if key[0] != "S"}
    dropped = sample_bundles(params, controls, alloc, ("p",), "seed", 2)
    for arm in ("F", "C"):
        key = (arm, "p", "X", 20)
        assert first[key] == second[key] == dropped[key]


def test_pairs_keep_draws_across_design_sizes_and_order(params):
    small = life_effects(params, ("p",), "seed", 3)
    large = life_effects(params, ("q", "p"), "seed", 3)
    assert small.x == {key: value for key, value in large.x.items() if key[1] == "p"}
    assert large == life_effects(params, ("p", "q"), "seed", 3)
    alloc = {("X", 20): 2}
    small_bundles = sample_bundles(params, targets_for(0), alloc, ("p",), "seed", 3)
    large_bundles = sample_bundles(
        params, targets_for(0, pairs=("q", "p")), alloc, ("q", "p"), "seed", 3)
    assert small_bundles == {k: v for k, v in large_bundles.items() if k[1] == "p"}


def test_point_masses(params):
    targets = {("F", "p", "X", 20): 1001.0, ("C", "p", "X", 20): -1001.0,
               ("S", "p", "X", 20): 1000.0}
    result = sample_bundles(params, targets, {("X", 20): 3}, ("p",), "seed", 0)
    assert result == {("F", "p", "X", 20): (1000,) * 3,
                      ("C", "p", "X", 20): (-1000,) * 3,
                      ("S", "p", "X", 20): (1000,) * 3}
    assert all(type(v) is int for values in result.values() for v in values)


def test_point_masses_consume_all_draws(params, monkeypatch):
    calls = []

    def normal(rng):
        calls.append(rng)
        return 0.0

    monkeypatch.setattr(model, "_normal", normal)
    args = (params, {("S", "p", "X", 20): 1000}, {("X", 20): 2}, ("p",), "seed", 0)
    sample_bundles(*args)
    assert len(calls) == 2 * (1 + 2 * len(ARMS))
    assert all(rng is calls[0] for rng in calls)


def test_monotone_coupling(params):
    alloc = {("X", 20): 8}
    low = sample_bundles(params, targets_for(-300, arms=("S",)), alloc, ("p",), "seed", 0)
    high = sample_bundles(params, targets_for(200, arms=("S",)), alloc, ("p",), "seed", 0)
    key = ("S", "p", "X", 20)
    assert all(a <= b for a, b in zip(low[key], high[key], strict=True))


def test_support_and_item_types_by_replaying_bundle_stream(params):
    targets = targets_for(0)
    result = sample_bundles(params, targets, {("X", 20): 4}, ("p",), "seed", 4,
                            solver=lambda cell, target: 0.0)
    rng = random.Random(draw("seed", ("ocsim", "bundles", "p", "X", "20"), 4, "bundles"))
    normal = NormalDist()

    def next_normal():
        return normal.inv_cdf((rng.getrandbits(52) + 0.5) * 2.0**-52)

    cell = params.cell("X")
    rho_e = (params.rho_t - params.sigma_d2) / (1 - params.sigma_d2)
    expected = {arm: [] for arm in ARMS}
    for _ in range(4):
        g = next_normal()
        for arm in ARMS:
            h0, h1 = next_normal(), next_normal()
            e1 = rho_e * h0 + math.sqrt(1 - rho_e * rho_e) * h1
            z0 = math.sqrt(params.sigma_d2) * g + math.sqrt(1 - params.sigma_d2) * h0
            z1 = math.sqrt(params.sigma_d2) * g + math.sqrt(1 - params.sigma_d2) * e1
            item0 = cell.levels[bisect_left(cell.cuts, z0)]
            item1 = cell.levels[bisect_left(cell.cuts, z1)]
            assert type(item0) is type(item1) is int
            expected[arm].append(min(item0, item1))
    assert result == {(arm, "p", "X", 20): tuple(expected[arm]) for arm in ARMS}
    assert all(type(v) is int and v in cell.levels for scores in result.values() for v in scores)


def test_identical_twins_equal_first_item(params, monkeypatch):
    params = replace(params, rho_t=1.0, sigma_d2=0.0)
    # g, then (h0, h1) for F, C, S. h1 must not affect either item.
    normals = iter((99.0, -1.0, 88.0, 0.0, 77.0, 1.0, 66.0))
    monkeypatch.setattr(model, "_normal", lambda rng: next(normals))
    result = sample_bundles(params, targets_for(0), {("X", 20): 1}, ("p",), "seed", 0,
                            solver=lambda cell, target: 0.0)
    assert result == {("F", "p", "X", 20): (-1000,), ("C", "p", "X", 20): (0,),
                      ("S", "p", "X", 20): (1000,)}


def test_twin_branch_uses_the_residual_correlation(params, monkeypatch):
    # rho_e = (0.6 - 0.2)/(1 - 0.2) = 0.5 puts item1 at sqrt(0.8)*0.5 = 0.447, below the
    # cut at 0.5 (level 0); rho_t = 0.6 itself would put it at 0.537 (level 1000).
    params = replace(params, rho_t=0.6, sigma_d2=0.2)
    normals = iter((0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    monkeypatch.setattr(model, "_normal", lambda rng: next(normals))
    result = sample_bundles(params, targets_for(0), {("X", 20): 1}, ("p",), "seed", 0,
                            solver=lambda cell, target: 0.0)
    assert result[("F", "p", "X", 20)] == (0,)


@pytest.mark.parametrize("h,k,rho", [
    (-0.006136, -0.006136, math.nextafter(-1.0, 0.0)),
    (0.006, -0.006, math.nextafter(1.0, 0.0)),
    (-2.0, 1.5, -0.9999),
    (-0.006, -0.006, -0.99999),
])
def test_phi2_stays_within_frechet_bounds(h, k, rho):
    # Unclamped, Simpson's rule puts these outside the bounds by about 2.2e-4, 2.2e-4,
    # 1e-11 and 1.5e-5 (the third from the t = 0 end, the others from the end panel).
    normal = NormalDist()
    value = phi2(h, k, rho)
    assert max(0.0, normal.cdf(h) + normal.cdf(k) - 1) <= value <= normal.cdf(min(h, k))


def test_cuts_include_equality_in_lower_level(params, monkeypatch):
    params = replace(params, rho_t=1.0, sigma_d2=0.0)
    normals = iter((0.0, -0.5, 9.0, 0.5, 9.0, 0.0, 9.0))
    monkeypatch.setattr(model, "_normal", lambda rng: next(normals))
    result = sample_bundles(params, targets_for(0), {("X", 20): 1}, ("p",), "seed", 0,
                            solver=lambda cell, target: 0.0)
    assert result[("F", "p", "X", 20)] == (-1000,)
    assert result[("C", "p", "X", 20)] == (0,)


def test_cell_scores_exact_fractions():
    bundles = {("F", "p", "X", 20): (1000, 0), ("F", "p", "X", 60): (-1000,),
               ("C", "p", "X", 20): (1000, 1000, 0), ("S", "p", "X", 20): ()}
    result = cell_scores(bundles)
    assert result == {("F", "p", "X"): Fraction(0), ("C", "p", "X"): Fraction(200, 3)}
    assert all(type(value) is Fraction for value in result.values())
    assert cell_scores({}) == {}


@pytest.mark.parametrize("levels", [(), (0, 0), (1, -1), (False,), (0.0,),
                                    (-1001,), (1001,), ("0",)])
def test_validation_levels(cell, levels):
    message = "levels must be strictly increasing ints in [-1000, 1000]"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(cell, levels=levels)
    assert str(exc.value) == message


@pytest.mark.parametrize("cuts", [(), (0.0,), (0.0, 0.0), (1.0, -1.0),
                                  (math.nan, 1.0), (-1.0, math.inf), ("0", 1.0)])
def test_validation_cuts(cell, cuts):
    message = "cuts must be len(levels)-1 strictly increasing finite floats"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(cell, cuts=cuts)
    assert str(exc.value) == message


@pytest.mark.parametrize("changes", [{"f0": 600.0}, {"f0": 601.0}, {"f0": math.nan},
                                     {"c0": math.inf}, {"sigma_f": -1.0},
                                     {"sigma_c": -1.0}, {"sigma_f": math.inf},
                                     {"sigma_c": math.nan}])
def test_validation_cell_parameters(cell, changes):
    message = "cell X: need finite f0 < c0 and sigma >= 0"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(cell, **changes)
    assert str(exc.value) == message


@pytest.mark.parametrize("ids", [(), ("X", "X"), ("Y", "X")])
def test_validation_cells(params, cell, ids):
    message = "cells must be nonempty, unique and sorted"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(params, cells=tuple(replace(cell, cell=cell_id) for cell_id in ids))
    assert str(exc.value) == message


@pytest.mark.parametrize("field,value", [("rho_x", -0.01), ("rho_x", 0.96),
                                        ("rho_a", -0.96), ("rho_a", 0.96),
                                        ("rho_t", -1.01), ("rho_t", 1.01),
                                        ("sigma_d2", -0.01), ("sigma_d2", 1.0),
                                        ("rho_x", math.nan), ("rho_a", math.inf),
                                        ("rho_t", math.nan), ("sigma_d2", math.inf)])
def test_validation_parameter_ranges(params, field, value):
    message = f"{field} out of range"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(params, **{field: value})
    assert str(exc.value) == message


def test_validation_twin_feasibility(params):
    message = "rho_t must be >= 2*sigma_d2 - 1"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(params, rho_t=0.0, sigma_d2=0.6)
    assert str(exc.value) == message


@pytest.mark.parametrize("value", [-0.01, 0.81, math.inf, math.nan])
def test_validation_reader_variance(params, value):
    message = "sigma_r2 out of range"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        replace(params, sigma_r2=value)
    assert str(exc.value) == message


@pytest.mark.parametrize("margin", [-50, 50])
def test_validation_lambda(cell, margin):
    message = "cell X: margin gives lambda outside [0, 1]"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        interpolation(cell, margin)
    assert str(exc.value) == message


@pytest.mark.parametrize("margins", [{}, {"Y": 0}, {"X": 0, "Y": 0}])
def test_validation_margins(params, margins):
    message = "margins must name every cell exactly"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        expected_units(params, LifeEffects({}), margins)
    assert str(exc.value) == message


@pytest.mark.parametrize("key,count,target_key", [
    (("X", 20), -1, ("F", "p", "X", 20)),
    (("X", 20), True, ("F", "p", "X", 20)),
    (("X", 20), 1.0, ("F", "p", "X", 20)),
    (("X", 20), 0, ("Q", "p", "X", 20)),
    (("X", 20), 0, ("F", "q", "X", 20)),
    (("X", 20), 0, ("F", "p", "Y", 20)),
    (("X", 20), 0, ("F", "p", "X", 60)),
])
def test_validation_alloc_and_target_keys(params, key, count, target_key):
    bad_key = key if type(count) is not int or count < 0 else target_key
    message = f"bad alloc or target key: {bad_key}"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        sample_bundles(params, {target_key: 0.0}, {key: count}, ("p",), "seed", 0)
    assert str(exc.value) == message


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_validation_targets_finite(params, value):
    message = "targets must be finite"
    with pytest.raises(ValueError, match=re.escape(message)) as exc:
        sample_bundles(params, targets_for(value), {("X", 20): 0}, ("p",), "seed", 0)
    assert str(exc.value) == message


@pytest.mark.parametrize("pairs", [("p", "p"), ("p", 1), (["p"],)])
def test_validation_pairs(params, pairs):
    message = "pairs must be unique strings"
    for call in (lambda: life_effects(params, pairs, "seed", 0),
                 lambda: sample_bundles(params, {}, {}, pairs, "seed", 0)):
        with pytest.raises(ValueError, match=re.escape(message)) as exc:
            call()
        assert str(exc.value) == message


def test_frozen_dataclasses_and_cell_lookup(params, cell):
    assert ARMS == ("F", "C", "S")
    assert [field.name for field in fields(CellModel)] == [
        "cell", "levels", "cuts", "f0", "c0", "sigma_f", "sigma_c"]
    assert [field.name for field in fields(LatentParams)] == [
        "cells", "rho_x", "rho_a", "rho_t", "sigma_d2", "sigma_r2"]
    assert [field.name for field in fields(LifeEffects)] == ["x"]
    assert params.cell("X") is cell
    with pytest.raises(KeyError, match=re.escape("unknown cell: Y")) as exc:
        params.cell("Y")
    assert exc.value.args == ("unknown cell: Y",)
    for instance, field, value in ((cell, "f0", 0.0), (params, "rho_x", 0.0),
                                   (LifeEffects({}), "x", {})):
        with pytest.raises(FrozenInstanceError):
            setattr(instance, field, value)


@pytest.mark.parametrize("bits", [0, 2**52 - 1])
def test_normal_uniform_extremes_are_open(bits):
    class ExtremeRandom:
        def getrandbits(self, width):
            assert width == 52
            return bits

    uniform = (bits + 0.5) * 2.0**-52
    assert 0.0 < uniform < 1.0
    expected = NormalDist().inv_cdf(uniform)
    assert math.isfinite(expected)
    assert model._normal(ExtremeRandom()) == expected


def test_solver_hook_high(params):
    calls = []

    def solver(cell, target):
        calls.append((cell, target))
        return "high"

    targets = targets_for(-400.0)
    result = sample_bundles(params, targets, {("X", 20): 2}, ("p",), "seed", 0,
                            solver=solver)
    assert set(result) == set(targets)
    assert all(values == (1000, 1000) for values in result.values())
    assert calls == [(params.cell("X"), -400.0)] * len(ARMS)


def test_explicit_exact_solver_matches_default(params):
    args = (params, targets_for(125.0), {("X", 20): 3}, ("p",), "seed", 0)
    default = sample_bundles(*args)
    explicit = sample_bundles(
        *args, solver=lambda cell, target: solve_location(cell, params.rho_t, target))
    assert explicit == default


def test_phi2_rounding_cannot_make_exponent_positive(monkeypatch):
    exp = math.exp
    exponents = []

    def checked_exp(value):
        assert value <= 0.0
        exponents.append(value)
        return exp(value)

    monkeypatch.setattr(model.math, "sin", lambda t: math.nextafter(1.0, math.inf))
    monkeypatch.setattr(model.math, "exp", checked_exp)
    phi2(1.0, 1.0, 0.5)
    assert len(exponents) == SIMPSON_INTERVALS + 1


def test_frozen_numerics_and_bisection_steps(cell, monkeypatch):
    assert SIMPSON_INTERVALS == 128
    assert BISECTION_STEPS == 64
    assert LOCATION_BOUND == 10.0
    midpoints = []

    def identity(cell, rho_t, theta):
        midpoints.append(theta)
        return theta

    monkeypatch.setattr(model, "expected_min", identity)
    assert solve_location(cell, 0.3, 1.25) == 1.25
    # The two bracket checks come first, then the 64 bisection midpoints.
    assert midpoints[:2] == [-10.0, 10.0]
    assert len(midpoints) == 2 + 64
    assert midpoints[2:7] == [0.0, 5.0, 2.5, 1.25, 0.625]
    assert all(-10.0 <= value <= 10.0 for value in midpoints)


def test_rng_uses_keyed_attempt():
    args = ("seed", ("ocsim", "life", "p"), 7, "life")
    expected = random.Random(draw(*args))
    actual = model._rng(*args)
    assert [actual.getrandbits(52) for _ in range(3)] == [
        expected.getrandbits(52) for _ in range(3)]


def test_life_stream_draw_order_and_system_independence(params, cell, monkeypatch):
    params = replace(params, cells=(cell, replace(cell, cell="Y")))
    values = iter(float(v) for v in range(1, 10))
    keys = []

    def rng(seed, unit, rep, name):
        keys.append((seed, unit, rep, name))
        return None

    monkeypatch.setattr(model, "_rng", rng)
    monkeypatch.setattr(model, "_normal", lambda rng: next(values))
    effects = life_effects(params, ("p",), "seed", 7)
    assert keys == [("seed", ("ocsim", "life", "p"), 7, "life")]
    root = math.sqrt(0.75)
    expected = {("F", "p", "X"): 0.5 * 1 + root * 4,
                ("C", "p", "X"): 0.5 * 2.2 + root * 6.4,
                ("S", "p", "X"): 0.5 * 3 + root * 6,
                ("F", "p", "Y"): 0.5 * 1 + root * 7,
                ("C", "p", "Y"): 0.5 * 2.2 + root * 10.6,
                ("S", "p", "Y"): 0.5 * 3 + root * 9}
    assert effects.x == pytest.approx(expected, abs=1e-12, rel=0)


def test_reader_variance_is_carried_without_changing_generation(params):
    other = replace(params, sigma_r2=0.8)
    effects = life_effects(params, ("p",), "seed", 0)
    assert effects == life_effects(other, ("p",), "seed", 0)
    assert expected_units(params, effects, {"X": 0}) == expected_units(other, effects, {"X": 0})
    args = (targets_for(0), {("X", 20): 2}, ("p",), "seed", 0)
    assert sample_bundles(params, *args) == sample_bundles(other, *args)


def test_target_subset_zero_allocation_and_empty_inputs(params):
    targets = {("C", "p", "X", 20): 0.0, ("S", "p", "X", 60): 1000.0}
    result = sample_bundles(params, targets, {("X", 20): 0, ("X", 60): 1}, ("p",), "seed", 0)
    assert result == {("C", "p", "X", 20): (), ("S", "p", "X", 60): (1000,)}
    assert sample_bundles(params, {}, {}, (), "seed", 0) == {}
    assert life_effects(params, (), "seed", 0) == LifeEffects({})


def test_model_package_stays_outside_control_files():
    # CONTROL_FILES expands the control/reader import closure at import time.
    assert not any(path.startswith("ocsim/") for path in cache.CONTROL_FILES)


def test_expected_units_default_tau_and_zero_sensitivity(params, cell):
    params = replace(params, cells=(replace(cell, sigma_f=100.0, sigma_c=100.0),), rho_a=0.0)
    effects = LifeEffects({("F", "p", "X"): 0.0, ("C", "p", "X"): 0.0,
                           ("S", "p", "X"): 1.0})
    default = expected_units(params, effects, {"X": 0})
    explicit = expected_units(params, effects, {"X": 0}, tau={"X": math.sqrt(5000)})
    sensitivity = expected_units(params, effects, {"X": 0}, tau={"X": 0.0})
    assert default == explicit
    assert default[("S", "p", "X")] == 200 + math.sqrt(5000)
    assert sensitivity[("S", "p", "X")] == 200.0
    for arm in ("F", "C"):
        assert default[(arm, "p", "X")] == sensitivity[(arm, "p", "X")]


@pytest.mark.parametrize("rho_t,sigma_d2", [(-1.0, 0.0), (0.98, 0.99), (1.0, 0.99)])
def test_sampling_feasible_correlation_boundaries(params, rho_t, sigma_d2):
    params = replace(params, rho_t=rho_t, sigma_d2=sigma_d2)
    result = sample_bundles(params, targets_for(0), {("X", 20): 2}, ("p",), "seed", 0,
                            solver=lambda cell, target: 0.0)
    assert all(type(v) is int and v in params.cell("X").levels
               for scores in result.values() for v in scores)
