"""Issue #247: frozen calibration and shared order statistics, for CI execution."""

from fractions import Fraction

import pytest

from bicentennial.stats import certify, core, tcal


def test_certify_uses_the_same_frozen_tables():
    assert certify._ONE_SIDED_PPM is tcal.ONE_SIDED_PPM
    assert certify._TWO_SIDED_PPM is tcal.TWO_SIDED_PPM


def test_table_shape_and_order():
    one, two = tcal.ONE_SIDED_PPM, tcal.TWO_SIDED_PPM
    assert len(one) == len(two) == 199
    assert all(a <= b for a, b in zip(one, one[1:], strict=False))
    assert all(a <= b for a, b in zip(two, two[1:], strict=False))
    assert all(t <= o for o, t in zip(one, two, strict=True))


@pytest.mark.parametrize("table,units,expected", [
    (tcal.TWO_SIDED_PPM, 2, 0),
    (tcal.TWO_SIDED_PPM, 4, 119),
    (tcal.TWO_SIDED_PPM, 24, 17_294),
    (tcal.TWO_SIDED_PPM, 200, 24_026),
    (tcal.ONE_SIDED_PPM, 2, 0),
    (tcal.ONE_SIDED_PPM, 3, 174),
    (tcal.ONE_SIDED_PPM, 200, 48_791),
])
def test_table_literal_values(table, units, expected):
    assert tcal.ppm(table, units) == expected


@pytest.mark.parametrize("table", [tcal.ONE_SIDED_PPM, tcal.TWO_SIDED_PPM])
def test_ppm_caps_at_200(table):
    assert tcal.ppm(table, 250) == tcal.ppm(table, 200)


@pytest.mark.parametrize("table", [tcal.ONE_SIDED_PPM, tcal.TWO_SIDED_PPM])
@pytest.mark.parametrize("units", [-1, 0, 1])
def test_ppm_below_two_units(table, units):
    assert tcal.ppm(table, units) == 0


@pytest.mark.parametrize("draws,quantile,expected", [
    (10_000, 0, 0),
    (10_000, 1_000_000, 9999),
    (4, 250_000, 0),  # Exact rank: ceil(1) - 1.
    (4, 250_001, 1),  # Just above an integer rank must round upward.
    (1, 17_294, 0),
    (1, 982_706, 0),
])
def test_index_inverse_empirical_cdf(draws, quantile, expected):
    assert tcal.index(draws, quantile) == expected


def test_24_unit_10_000_draw_indices():
    two = tcal.ppm(tcal.TWO_SIDED_PPM, 24)
    assert (tcal.index(10_000, two), tcal.index(10_000, 1_000_000 - two)) == (172, 9827)


def test_shared_order_statistics(monkeypatch):
    n, draws = 24, 1000
    # Zero-sum powers of two give replicate 2*r/n for bit-pattern r.
    # Reverse the patterns so both consumers must sort the same distinct list.
    values = [1 << life for life in range(n - 1)] + [-(2**(n - 1) - 1)]
    replicates = tuple(Fraction(2 * r, n) for r in reversed(range(draws)))

    def controlled_draw(seed, unit, attempt, name):
        assert seed == "shared" and name == "headline"
        assert unit[:2] == ("stats", "bootstrap")
        return ((draws - 1 - attempt) >> int(unit[-1])) & 1

    monkeypatch.setattr(core, "draw", controlled_draw)
    ordered = sorted(replicates)
    two = tcal.ppm(tcal.TWO_SIDED_PPM, n)
    expected = (ordered[tcal.index(draws, two)],
                ordered[tcal.index(draws, 1_000_000 - two)])
    estimate = certify._estimate(Fraction(0), replicates, units=n)
    assert estimate.interval == expected
    assert core.bootstrap_ci(values, seed="shared", name="headline", draws=draws) == expected
