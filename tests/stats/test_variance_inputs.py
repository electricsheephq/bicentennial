"""Hand-computed control moments and deterministic latent matching."""

import math
import re
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from statistics import NormalDist

import pytest

from bicentennial.ocsim.model import CellModel, LatentParams
from bicentennial.stats import variance_inputs
from bicentennial.stats.variance_inputs import (
    ACTION_LEVELS,
    TIMING_LEVELS,
    CellMoments,
    ControlRecord,
    VarianceInputs,
    bin_item,
    cut_locations,
    estimate,
    match,
    score_covariance,
    to_latent,
)

FAKE_X = ((1000, 1000), (0, 1000), (-1000, 0))


def records(scores=FAKE_X, *, arm="F", cell="X", run="A"):
    return [ControlRecord(arm, run, f"L{life}", cell, 20, f"{cell}:{life}:{i}", v, v)
            for life, values in enumerate(scores, 1) for i, v in enumerate(values)]


def both_arms(scores=FAKE_X, *, cell="X"):
    return records(scores, cell=cell) + records(scores, arm="C", cell=cell)


def moment(inputs, arm="F", cell="X"):
    return next(m for m in inputs.moments if (m.arm, m.cell) == (arm, cell))


def sheppard(r):
    return match(r, ((-1000, 1000),), ((0.0,),), ((0.0, 0.0),), (1,))


def direct_inputs(*, twin_r=0.0, fc_r=0.5, aa_r=None):
    moments = tuple(CellMoments(arm, "X", 2, 4, Fraction(), Fraction(), Fraction(),
                                Fraction(2), Fraction(),
                                ((-1000, 4), (0, 0), (1000, 4))) for arm in ("C", "F"))
    return VarianceInputs(
        moments=moments, timing_cells=frozenset(), icc=Fraction(), icc_raw=None,
        rho_x=0.0, rho_x_raw=None, rho_a=0.0, rho_a_raw=None,
        reader_var=(("F", None), ("C", None)), twin_r=twin_r, fc_r=fc_r, aa_r=aa_r,
        df=(("aa", "F", "X", 6), ("fc", "F", "X", 6), ("twin", "F", "X", 2)),
        n_nonresult=0, n_aa_unpaired=0, flags=(),
    )


def test_anova_fake_x():
    inputs = estimate(records())
    m = moment(inputs)
    assert (m.n_lives, m.n_bundles) == (3, 6)
    assert m.mean == Fraction(1000, 3)
    assert m.msb == Fraction(3500000, 3)
    assert m.msw == Fraction(1000000, 3)
    assert m.n0 == Fraction(2)
    assert m.sigma2_life_raw == Fraction(1250000, 3)
    assert inputs.icc_raw == inputs.icc == Fraction(5, 9)
    assert m.level_counts == ((-1000, 2), (0, 4), (1000, 6))
    assert ("twin", "F", "X", 3) in inputs.df
    assert estimate(iter(reversed(records()))) == inputs


def test_negative_icc():
    inputs = estimate(records(((1000, -1000), (1000, -1000), (-1000, 1000))))
    m = moment(inputs)
    assert m.msb == Fraction()
    assert m.msw == Fraction(2000000)
    assert m.sigma2_life_raw == Fraction(-1000000)
    assert inputs.icc_raw == Fraction(-1)
    assert inputs.icc == Fraction()
    assert "icc_truncated" in inputs.flags


def test_reader_variance_identical():
    inputs = estimate(records() + records(run="A_prime"))
    assert dict(inputs.reader_var)["F"] == Fraction()
    assert inputs.aa_r == 1.0
    assert ("aa", "F", "X", 9) in inputs.df
    assert inputs.n_aa_unpaired == 0


def test_reader_variance_one_difference_of_four():
    base = records(((0, 1000), (-1000, 0)))
    rerun = [replace(r, run="A_prime") for r in base]
    rerun[0] = replace(rerun[0], b0=1000, b1=1000)
    assert dict(estimate(base + rerun).reader_var)["F"] == Fraction(125000)


def test_reader_variance_absent_and_unpaired():
    base = estimate(records())
    assert dict(base.reader_var) == {"F": None, "C": None}
    assert "no_aa:F" in base.flags
    orphan = replace(records()[0], run="A_prime", bundle="orphan")
    inputs = estimate(records() + [orphan])
    assert inputs.n_aa_unpaired == 1
    assert inputs.reader_var == base.reader_var
    assert inputs.moments == base.moments
    assert inputs.aa_r is None


def test_twin_positive_closed_end():
    inputs = estimate(both_arms())
    params, flags = to_latent(inputs)
    assert inputs.twin_r == 1.0
    assert params.rho_t == 1.0
    assert "twin_default" not in flags
    assert inputs.fc_r == 1.0
    assert params.sigma_d2 == 0.99
    for cell in params.cells:
        assert cell.sigma_f == math.sqrt(Fraction(1250000, 3))
        assert cell.sigma_c == cell.sigma_f


def test_twin_negative_end():
    rows = [replace(r, b1=-r.b0) for r in both_arms(((1000, -1000),) * 2)]
    inputs = estimate(rows)
    params, _ = to_latent(inputs)
    assert inputs.twin_r == -1.0
    assert params.rho_t <= -1 + 1e-9
    assert params.sigma_d2 <= (1 + params.rho_t) / 2


def test_twin_constant_defaults():
    inputs = estimate(both_arms(((0, 0), (0, 0))))
    params, flags = to_latent(inputs)
    assert inputs.twin_r is None
    assert "twin_undefined" in inputs.flags
    assert "twin_default" in flags
    assert params.rho_t == 0.0


def test_sheppard_map():
    assert sheppard(0.5) == pytest.approx(math.sin(math.pi / 4), abs=1e-9)
    assert sheppard(0.0) == pytest.approx(0.0, abs=1e-12)
    assert sheppard(1.0) == 1.0
    assert sheppard(-1.0) == -1.0
    assert score_covariance((-1000, 1000), (0.0,), 0.0, 0.0, 0.0) == 0.0
    assert score_covariance((-1000, 1000), (0.0,), 0.0, 0.0, 1.0) == 1000000.0


def test_cuts_two_levels():
    cuts, theta_f, theta_c = cut_locations((-1000, 1000), (3, 1), (1, 3))
    assert cuts == pytest.approx((0.0,), abs=1e-12)
    assert theta_f == pytest.approx(-0.5244005127080407, abs=1e-12)
    assert theta_c == pytest.approx(0.5244005127080407, abs=1e-12)


def test_cuts_add_half_at_empty_level():
    normal = NormalDist()
    cuts, theta_f, theta_c = cut_locations(ACTION_LEVELS, (3, 0, 1), (1, 0, 3))
    zf = (normal.inv_cdf(7 / 11), normal.inv_cdf(8 / 11))
    zc = (normal.inv_cdf(3 / 11), normal.inv_cdf(4 / 11))
    assert cuts == pytest.approx(tuple((f + c) / 2 for f, c in zip(zf, zc, strict=True)))
    assert cuts[0] < cuts[1]
    assert theta_f == pytest.approx(sum(c - f for f, c in zip(zf, zc, strict=True)) / 4)
    assert theta_c == -theta_f


def test_rho_x_zero_with_raw_timing_y():
    rows = records() + records(((1000, 1000), (0, 0), (800, 800)), cell="Y")
    inputs = estimate(rows, timing_cells=frozenset({"Y"}))
    y = moment(inputs, cell="Y")
    assert y.mean == Fraction(600)
    assert y.msw == Fraction()
    assert y.msb == Fraction(560000)
    assert y.n0 == Fraction(2)
    assert y.sigma2_life_raw == Fraction(280000)
    assert inputs.rho_x_raw == inputs.rho_x == 0.0
    assert "rho_x_undefined" not in inputs.flags


def test_rho_x_upper_clamp():
    inputs = estimate(records() + records(cell="Y"))
    assert inputs.rho_x_raw == pytest.approx(1.4)
    assert inputs.rho_x == 0.95
    assert "rho_x_clamped" in inputs.flags


def test_rho_x_lower_clamp():
    reverse = tuple(tuple(-v for v in values) for values in FAKE_X)
    inputs = estimate(records() + records(reverse, cell="Y"))
    assert inputs.rho_x_raw == pytest.approx(-1.4)
    assert inputs.rho_x == 0.0
    assert "rho_x_clamped" in inputs.flags


def test_rho_a_anova_correction():
    inputs = estimate(both_arms())
    assert inputs.rho_a_raw == 1.0
    assert inputs.rho_a == 0.95
    assert "rho_a_clamped" in inputs.flags
    assert inputs.fc_r == 1.0
    assert ("fc", "F", "X", 9) in inputs.df


def test_rho_a_lower_clamp():
    reverse = tuple(tuple(-v for v in values) for values in FAKE_X)
    inputs = estimate(records() + records(reverse, arm="C"))
    assert inputs.rho_a_raw == -1.0
    assert inputs.rho_a == -0.95
    assert "rho_a_clamped" in inputs.flags


def test_sigma_d2_constraints():
    assert sheppard(0.5) == pytest.approx(math.sqrt(2) / 2, abs=1e-9)
    inputs = direct_inputs()
    params, flags = to_latent(inputs)
    assert params.rho_t == pytest.approx(0.0, abs=1e-12)
    assert params.sigma_d2 == pytest.approx(0.5, abs=1e-12)
    assert "sigma_d2_constrained" in flags
    negative, flags = to_latent(replace(inputs, fc_r=-0.2))
    assert negative.sigma_d2 == 0.0
    assert "sigma_d2_zero" in flags
    absent, flags = to_latent(replace(inputs, fc_r=None))
    assert absent.sigma_d2 == 0.0
    assert "sigma_d2_zero" in flags


@pytest.mark.parametrize("rho_t", [-2.0**-64, 0.1, 0.3, -0.3, 0.0, 1.0, -1.0])
def test_twin_limit_passes_the_model_check(rho_t):
    # (1 + rho_t)/2 itself fails A1's check at 0.1, 0.3 and -2**-64 (a bisection's 0).
    limit = variance_inputs._twin_limit(rho_t)
    assert limit <= (1 + rho_t) / 2
    assert 2 * limit - 1 <= rho_t
    assert (1 + rho_t) / 2 - limit < 1e-15
    cell = CellModel("X", (-1000, 1000), (0.0,), -200.0, 600.0, 0.0, 0.0)
    assert LatentParams((cell,), 0.0, 0.0, rho_t, min(limit, 0.99)).sigma_d2 == min(limit, 0.99)


def test_sigma_r2_constraint_precedes_twin_constraint():
    inputs = direct_inputs(twin_r=1.0, fc_r=0.8, aa_r=0.2)
    params, flags = to_latent(inputs)
    cuts, tf, tc = cut_locations(ACTION_LEVELS, (4, 0, 4), (4, 0, 4))
    stable = match(0.2, (ACTION_LEVELS,), (cuts,), ((tf, tf),), (6,))
    assert tc == -tf
    assert params.sigma_d2 == pytest.approx(stable, abs=1e-12)
    assert params.sigma_r2 == pytest.approx(1 - stable, abs=1e-12)
    assert "sigma_d2_constrained" in flags
    negative, _ = to_latent(replace(inputs, aa_r=-1.0))
    assert negative.sigma_d2 == 0.0
    assert negative.sigma_r2 == 1.0
    assert to_latent(replace(inputs, aa_r=None))[0].sigma_r2 is None


@pytest.mark.parametrize(
    ("floor", "ceiling", "timing", "expected"),
    [
        ((-1000, 0, 0, 0, 0), (0, 0, 0, 1000, 1000), False, (-200.0, 400.0)),
        ((0, 0), (100, 100), True, (-100.0, 200.0)),
        ((900, 900), (1000, 1000), True, (700.0, 1000.0)),
    ],
)
def test_planning_floor_ceiling(floor, ceiling, timing, expected):
    rows = records((floor, floor)) + records((ceiling, ceiling), arm="C")
    inputs = estimate(rows, timing_cells=frozenset({"X"}) if timing else frozenset())
    params, _ = to_latent(inputs)
    assert (params.cell("X").f0, params.cell("X").c0) == expected


def test_planning_lower_shift_and_common_gap():
    inputs = direct_inputs(twin_r=None, fc_r=None)
    rows = (
        replace(moment(inputs, "C"), mean=Fraction(-900)),
        replace(moment(inputs, "F"), mean=Fraction(-1000)),
    )
    params, _ = to_latent(replace(inputs, moments=rows))
    assert (params.cell("X").f0, params.cell("X").c0) == (-1000.0, -700.0)
    rows += (
        replace(moment(inputs, "C"), cell="Y", mean=Fraction(1000)),
        replace(moment(inputs, "F"), cell="Y", mean=Fraction()),
    )
    params, _ = to_latent(replace(inputs, moments=rows))
    assert [c.c0 - c.f0 for c in params.cells] == [550.0, 550.0]


@pytest.mark.parametrize(
    ("value", "expected"),
    [(-1000, -1000), (-250, -250), (0, 0), (1, 125), (250, 125), (251, 375),
     (500, 375), (501, 625), (750, 625), (751, 875), (999, 875), (1000, 1000)],
)
def test_timing_binning(value, expected):
    assert bin_item(value, True) == expected


@pytest.mark.parametrize("value", ACTION_LEVELS)
def test_action_binning(value):
    assert bin_item(value, False) == value


def test_binning_only_changes_items_and_counts():
    rows = both_arms(((250, 251), (750, 999)))
    rows += [replace(r, run="A_prime", b0=0, b1=0) for r in rows]
    inputs = estimate(rows, timing_cells=frozenset({"X"}))
    m = moment(inputs)
    assert m.mean == Fraction(1125, 2)
    assert m.msb == Fraction(389376)
    assert m.msw == Fraction(62002, 4)
    assert m.sigma2_life_raw == Fraction(747751, 4)
    assert dict(inputs.reader_var)["F"] == Fraction(843001, 4)
    assert m.level_counts == tuple(zip(TIMING_LEVELS, (0, 0, 0, 2, 2, 2, 2, 0), strict=True))
    assert inputs.twin_r == 1.0


def test_all_item_pearsons_use_bins():
    rows = both_arms(((1, 250, 251),) * 2)
    rows = [replace(r, b1={1: 250, 250: 1, 251: 251}[r.b0]) for r in rows]
    rows = [replace(r, b0=500, b1=500) if r.arm == "C" and r.b0 == 251 else r
            for r in rows]
    rerun = [replace(r, run="A_prime", b0=500 if r.b0 == 251 else r.b0,
                     b1=500 if r.b1 == 251 else r.b1) for r in rows]
    inputs = estimate(rows + rerun, timing_cells=frozenset({"X"}))
    assert inputs.twin_r == inputs.fc_r == inputs.aa_r == 1.0
    assert dict(inputs.reader_var)["F"] == Fraction(62001, 6)


@pytest.mark.parametrize("arm", ["S", "", None])
def test_validation_arm(arm):
    with pytest.raises(ValueError, match=re.escape('arm must be "F" or "C"')):
        replace(records()[0], arm=arm)


@pytest.mark.parametrize("run", ["B", "", None])
def test_validation_run(run):
    with pytest.raises(ValueError, match=re.escape('run must be "A" or "A_prime"')):
        replace(records()[0], run=run)


@pytest.mark.parametrize(
    "changes", [{"life": 1}, {"cell": None}, {"bundle": 2}, {"checkpoint": -1},
                {"checkpoint": True}, {"checkpoint": 1.0}],
)
def test_validation_ids_checkpoint(changes):
    with pytest.raises(ValueError, match=re.escape("ids must be str and checkpoint an int >= 0")):
        replace(records()[0], **changes)


@pytest.mark.parametrize("field", ["b0", "b1"])
@pytest.mark.parametrize("value", [True, False, 1.0, "0", -1001, 1001])
def test_validation_item_scores(field, value):
    with pytest.raises(ValueError, match=re.escape("item scores must be None or ints in [-1000, 1000]")):
        replace(records()[0], **{field: value})


def test_validation_duplicate():
    row = records()[0]
    with pytest.raises(ValueError, match=re.escape("duplicate record: F A X:1:0")):
        estimate([row, row])


@pytest.mark.parametrize("changes", [{"life": "other"}, {"cell": "Y"}, {"checkpoint": 60}])
def test_validation_conflicting_bundle(changes):
    row = records()[0]
    with pytest.raises(ValueError, match=re.escape("bundle X:1:0 has conflicting life/cell/checkpoint")):
        estimate([row, replace(row, arm="C", **changes)])


@pytest.mark.parametrize(("value", "timing"), [(-250, False), (1, False), (-400, True)])
def test_validation_support(value, timing):
    row = replace(records()[0], b0=value)
    with pytest.raises(ValueError, match=re.escape(f"cell X: item value {value} outside its support")):
        estimate([row], timing_cells=frozenset({"X"}) if timing else frozenset())


@pytest.mark.parametrize("rows", [[], records(run="A_prime"),
                                 [replace(records()[0], b0=None)]])
def test_validation_no_valid_run_a(rows):
    with pytest.raises(ValueError, match=re.escape("no valid run-A records")):
        estimate(rows)


@pytest.mark.parametrize("missing", ["F", "C"])
def test_latent_missing_arm(missing):
    inputs = estimate(records(arm="C" if missing == "F" else "F"))
    with pytest.raises(ValueError, match=re.escape(f"cell X lacks arm {missing}")):
        to_latent(inputs)


def test_latent_gap_exceeds_scale():
    with pytest.raises(ValueError, match=re.escape("gap exceeds the scale")):
        to_latent(estimate(both_arms()), gap_floor=2001)


def test_round_trip_into_a1():
    rows = both_arms() + both_arms(cell="Y")
    rows += [replace(r, run="A_prime") for r in rows]
    inputs = estimate(rows)
    first = to_latent(inputs)
    assert first == to_latent(estimate(iter(reversed(rows))))
    params, flags = first
    assert isinstance(params, LatentParams)
    assert all(isinstance(cell, CellModel) for cell in params.cells)
    assert [cell.cell for cell in params.cells] == ["X", "Y"]
    assert params.sigma_r2 == 0.0
    assert flags == tuple(sorted(set(flags)))


def test_nonresults_excluded_everywhere():
    rows = both_arms() + [replace(r, run="A_prime") for r in both_arms()]
    base = estimate(rows)
    invalid = [ControlRecord(arm, run, "L9", "X", 60, "bad", b0, b1)
               for arm, run, b0, b1 in (("F", "A", None, 1000),
                                        ("C", "A", -1000, None),
                                        ("F", "A_prime", None, None))]
    inputs = estimate(rows + invalid)
    assert replace(inputs, n_nonresult=0) == base
    assert inputs.n_nonresult == 3
    assert inputs.n_aa_unpaired == 0
    scored_failures = estimate(records(((0, -1000), (0, -1000))))
    assert scored_failures.n_nonresult == 0
    assert moment(scored_failures).n_bundles == 4


def test_invalid_partner_is_unpaired():
    a = replace(records()[0], b0=None)
    aprime = replace(records()[0], run="A_prime")
    inputs = estimate(records()[1:] + [a, aprime])
    assert inputs.n_nonresult == 1
    assert inputs.n_aa_unpaired == 1
    assert dict(inputs.reader_var)["F"] is None


def test_anova_undefined_and_icc_undefined():
    inputs = estimate(both_arms(((1000,), (0,))))
    m = moment(inputs)
    assert m.msb is m.msw is m.n0 is m.sigma2_life_raw is None
    assert inputs.icc == Fraction()
    assert inputs.icc_raw is None
    assert {"anova_undefined:F:X", "anova_undefined:C:X", "icc_undefined",
            "rho_x_undefined", "rho_a_undefined"} <= set(inputs.flags)
    params, _ = to_latent(inputs)
    assert params.cell("X").sigma_f == params.cell("X").sigma_c == 0.0
    constant = estimate(both_arms(((0, 0), (0, 0))))
    assert constant.icc_raw is None
    assert "icc_undefined" in constant.flags


def test_icc_one_uses_positive_life_variance():
    inputs = estimate(both_arms(((1000, 1000), (0, 0))))
    assert inputs.icc == Fraction(1)
    assert "icc_one" in inputs.flags
    assert moment(inputs).sigma2_life_raw == Fraction(500000)
    params, _ = to_latent(inputs)
    assert params.cell("X").sigma_f == math.sqrt(500000)


def test_pooled_icc_and_undefined_cell_skipped():
    negative = ((1000, -1000), (1000, -1000), (-1000, 1000))
    inputs = estimate(both_arms() + both_arms(negative, cell="Y")
                      + both_arms(((0,),), cell="Z"))
    assert inputs.icc_raw == Fraction(-7, 21)
    assert inputs.icc == Fraction()
    assert "anova_undefined:F:Z" in inputs.flags
    params, _ = to_latent(inputs)
    assert all(c.sigma_f == c.sigma_c == 0.0 for c in params.cells)


def test_unbalanced_anova_bundle_weighted_mean():
    inputs = estimate(records(((1000,), (0, 0, 0))))
    m = moment(inputs)
    assert m.mean == Fraction(250)
    assert m.msb == Fraction(750000)
    assert m.msw == Fraction()
    assert m.n0 == Fraction(3, 2)
    assert m.sigma2_life_raw == Fraction(500000)


def test_pooled_icc_sets_each_cells_life_sd():
    constant_lives = ((1000, 1000), (0, 0), (-1000, -1000))
    inputs = estimate(both_arms() + both_arms(constant_lives, cell="Y"))
    assert inputs.icc == Fraction(17, 21)
    params, _ = to_latent(inputs)
    assert params.cell("X").sigma_f == math.sqrt(Fraction(4250000, 3))
    assert params.cell("Y").sigma_f == 0.0


def test_item_pearson_centres_within_life():
    rows = records(((0, 1000), (0, 1000)))
    rows = [replace(r, b1=1000 - r.b0) for r in rows]
    inputs = estimate(rows)
    assert inputs.twin_r == -1.0
    assert inputs.df == (("twin", "F", "X", 2),)
    assert inputs.fc_r is inputs.aa_r is None
    assert "fc_undefined" in inputs.flags
    assert "aa_undefined" in inputs.flags


def test_pooled_match_mixed_supports_closed_end():
    levels = (ACTION_LEVELS, TIMING_LEVELS)
    cuts = ((-0.4, 0.6), (-1.4, -0.8, -0.4, 0.0, 0.2, 0.7, 1.3))
    locations = ((0.2, 0.2), (-0.4, -0.4))
    weights = (3, 9)
    assert match(0.0, levels, cuts, locations, weights) == pytest.approx(0.0, abs=1e-12)
    assert match(1.0, levels, cuts, locations, weights) == 1.0


def test_exact_types_frozen_dataclasses_and_flags():
    rows = both_arms() + [replace(r, run="A_prime") for r in both_arms()]
    inputs = estimate(rows)
    for m in inputs.moments:
        for value in (m.mean, m.msb, m.msw, m.n0, m.sigma2_life_raw):
            assert type(value) is Fraction
        assert all(type(v) is int and type(n) is int for v, n in m.level_counts)
        assert type(m.n_lives) is type(m.n_bundles) is int
    assert type(inputs.icc) is type(inputs.icc_raw) is Fraction
    assert all(type(value) is Fraction for arm, value in inputs.reader_var)
    for value in (inputs.rho_x, inputs.rho_a, inputs.rho_a_raw,
                  inputs.twin_r, inputs.fc_r, inputs.aa_r):
        assert type(value) is float
    assert all(type(df) is int for stat, arm, cell, df in inputs.df)
    assert type(inputs.n_nonresult) is type(inputs.n_aa_unpaired) is int
    assert inputs.flags == tuple(sorted(set(inputs.flags)))
    with pytest.raises(FrozenInstanceError):
        inputs.icc = Fraction()
    with pytest.raises(FrozenInstanceError):
        inputs.moments[0].mean = Fraction()
    with pytest.raises(FrozenInstanceError):
        rows[0].b0 = 0


def test_checkpoint_set_is_supplied_and_moments_pool_it():
    rows = [replace(r, checkpoint=0 if r.bundle.endswith(":0") else 123)
            for r in both_arms()]
    assert estimate(rows) == estimate(both_arms())
