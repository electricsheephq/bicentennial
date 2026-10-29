"""SPEC-C C6 arithmetic and direct equivalence with the current certify."""

import re
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from math import gcd, lcm
from unittest.mock import patch

import pytest

from bicentennial import keyed
from bicentennial.ocsim import fastcert as fc
from bicentennial.ocsim.fastboard import CellSums, PairCell, to_board_inputs
from bicentennial.stats import certify, seeds, tcal

ROWS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


@pytest.fixture(scope="module")
def hand():
    return fc.WeightCache.from_matrix(("p", "q"), ROWS)


def values(f, w):
    return tuple(Fraction(f.center + sum(c * (1 if bits >> b & 1 else -1)
                                        for c, bits in zip(f.coef, w.bits, strict=True)), f.den)
                 for b in range(w.draws))


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def make_cs(pairs, entries, coverage=None, shortfall=None):
    cells = tuple(sorted({k for k, _ in entries}))
    coverage = coverage or {k: Fraction(1) for k in cells}
    return CellSums(cells, tuple(pairs), entries, {k: 1 for k in cells},
                    {k: 0 for k in cells}, coverage,
                    shortfall or {k: "infrastructure" if coverage[k] < Fraction(95, 100)
                                  else None for k in cells})


def test_hand_cache_counts_moments(hand):
    assert hand.bits == (3, 5)
    assert hand.colsum == (0, 0)
    assert hand.gram == ((4, 0), (0, 4))
    assert hand.packed(64) is hand.packed(64)
    assert hand.packed(3) == (1 + (1 << 3), 1 + (1 << 6))
    f = fc.Functional((3, -1), 0, 1, 2)
    assert values(f, hand) == (2, 4, -4, -2)
    for threshold, count in ((0, 2), (-3, 1), (-4, 0), (5, 4), (6, 4), (-10, 0)):
        assert fc.count_below(f, hand, threshold) == count
    shifted = replace(f, center=5, den=2)
    assert values(shifted, hand) == tuple(map(Fraction, (3.5, 4.5, 0.5, 1.5)))
    assert fc.count_below(shifted, hand, 1) == 1
    assert fc.count_below(shifted, hand, 2) == 2
    assert fc.moments(f, hand) == (0, 40)
    assert fc.se2(f, hand) == 10
    assert fc.se2(shifted, hand) == Fraction(5, 2)
    for center in (-10, 0, 30):
        constant = fc.Functional((0, 0), center, 1, 2)
        assert fc.count_below(constant, hand, center) == 0
        assert fc.count_below(constant, hand, center + 1) == 4
    with pytest.raises(FrozenInstanceError):
        hand.draws = 1
    with pytest.raises(FrozenInstanceError):
        f.center = 1


def test_indices_seeds_and_screen(hand):
    assert fc.UNCALIBRATED_PPM == 50_000
    assert seeds.CERTIFY_SEED == "bicentennial-certify-v1"
    assert seeds.CERTIFY_NAME == "certification"
    assert tcal.index(10_000, tcal.ppm(tcal.ONE_SIDED_PPM, 24)) == 399
    assert tcal.index(10_000, tcal.ppm(tcal.ONE_SIDED_PPM, 48)) == 449
    assert tcal.index(10_000, 50_000) == 499
    assert tcal.index(4, 50_000) == 0
    assert all(tcal.index(4, tcal.ppm(tcal.ONE_SIDED_PPM, n)) == 0 for n in (0, 1))
    f = fc.Functional((3, -1), 0, 1, 2)
    assert fc.screen(f, hand, -10, (0,)) is True
    assert fc.screen(f, hand, 5, (0,)) is False
    assert fc.screen(f, hand, -3, (0,)) is None
    assert fc.screen(f, hand, 0, (0,)) is None


@pytest.mark.parametrize("gaps,expected,replicates,reduced", (
    ((400, 200), "NOT_ADMITTED", (30, 40, 20, 30), fc.Functional((5, -5), 30, 1, 2)),
    ((600, 500), "ADMITTED", (55, 60, 50, 55), fc.Functional((5, -5), 110, 2, 2)),
))
def test_admission_hand(hand, gaps, expected, replicates, reduced):
    cs = make_cs(hand.pairs, {("X", p): PairCell(1, 100, True, 1, 0, gap)
                              for p, gap in zip(hand.pairs, gaps, strict=True)})
    gap = dict(fc.gap_functionals(cs, ("X",), hand))["X"]
    assert gap == reduced
    assert values(gap, hand) == replicates
    assert fc.count_below(gap, hand, 30) == int(expected == "NOT_ADMITTED")
    assert fc.admissions(cs, hand, required=("X",)) == (("X", expected),)
    bi = to_board_inputs(cs, {"p": 0, "q": 1})
    ref = certify._replicates(bi.pairs, bi.scores, bi.controls,
                             tuple(dict(zip(hand.pairs, row, strict=True)) for row in ROWS))
    assert tuple(row[0][2] for row in ref) == replicates


def fake(rep):
    def pick(label, lo, hi):
        return keyed.uniform_int("fastcert-fakes", (label,), rep, "fake", lo, hi)

    pairs = tuple(f"pair-{i:03d}" for i in range(pick("pairs", 2, 12)))
    cells = tuple(f"cell-{i}" for i in range(pick("cells", 1, 3)))
    entries, coverage = {}, {}
    for k in cells:
        coverage[k] = (Fraction(1), Fraction(19, 20), Fraction(9, 10))[pick(k + "cov", 0, 2)]
        drop_c, drop_s = pick(k + "dc", 0, 40), pick(k + "ds", 0, 20)
        for p in pairs:
            label = k + p
            n, nc = pick(label + "n", 1, 6), pick(label + "nc", 1, 6)
            # Include both admission outcomes and heterogeneous denominators.
            floor = pick(label + "f", -700, -200) * nc
            ceiling = min(1000 * nc, floor + pick(k + "gap", 100, 1400) * nc)
            valid = pick(label + "control", 0, 99) >= drop_c
            scored = pick(label + "score", 0, 99) >= drop_s
            if rep % 31 == 0:
                scored = False
            if rep % 37 == 0:
                valid = False
            entries[k, p] = PairCell(n if scored else 0,
                                     pick(label + "sum", -1000 * n, 1000 * n) if scored else 0,
                                     valid, nc, floor, ceiling)
    return make_cs(pairs, entries, coverage), Fraction((1, 5, 100)[pick("se", 0, 2)])


def compare_functionals(cs, w, prepared):
    margins, joint = fc.margin_functionals(cs, cs.cells, w)
    gaps = dict(fc.gap_functionals(cs, cs.cells, w))
    with patch.object(fc, "_reduce", lambda coef, center, den, units:
                      fc.Functional(tuple(coef), center, den, units)):
        raw_margins = dict(fc.margin_functionals(cs, cs.cells, w)[0])
        raw_gaps = dict(fc.gap_functionals(cs, cs.cells, w))
    for k, margin in margins:
        cell = next(c for c in prepared if c.cell == k)
        for functional, raw, series in ((margin, raw_margins[k], cell.series[3]),
                                        (gaps[k], raw_gaps[k], cell.series[2])):
            assert (functional is None) == (series is None)
            if functional is None:
                continue
            assert Fraction(functional.center, functional.den) == series.center
            assert Fraction(raw.center, raw.den) == series.center
            ref = dict(series.coefficients)
            for p, coef, raw_coef in zip(w.pairs, functional.coef, raw.coef, strict=True):
                assert Fraction(coef, functional.den) == Fraction(ref.get(p, 0), series.scale)
                assert Fraction(raw_coef, raw.den) == Fraction(ref.get(p, 0), series.scale)
            assert functional.units == len(series.coefficients)
            assert gcd(functional.center, functional.den, *functional.coef) == 1
            # A common positive factor before reduction leaves every value intact.
            expanded = fc.Functional(tuple(7 * c for c in functional.coef),
                                     7 * functional.center, 7 * functional.den, functional.units)
            assert fc._reduce(expanded.coef, expanded.center, expanded.den, expanded.units) == functional
            assert fc.se2(expanded, w) == fc.se2(functional, w)
            for threshold in (0, -10, 30):
                indices = (tcal.index(w.draws, tcal.ppm(tcal.ONE_SIDED_PPM, functional.units)),
                           tcal.index(w.draws, 50_000))
                count = fc.count_below(functional, w, threshold)
                assert count == sum(v < threshold for v in values(functional, w))
                assert fc.count_below(expanded, w, threshold) == count
                screened = fc.screen(functional, w, threshold, indices)
                if screened is not None:
                    assert all((count <= i) == screened for i in indices)
    if joint is not None:
        columns = [values(f, w) for _, f in margins]
        assert values(joint, w) == tuple(sum(row) / len(row) for row in zip(*columns, strict=True))


def compare_reference(cs, bound, draws, *, check_functionals=True, supplied=None):
    w = fc.WeightCache.from_seed(cs.pairs, seeds.CERTIFY_SEED, seeds.CERTIFY_NAME, draws)
    # The cache's columns follow pair identity, not its input position.
    for p, bits in zip(w.pairs, w.bits, strict=True):
        assert bits & 1 == keyed.draw(seeds.CERTIFY_SEED, ("stats", "certify", p),
                                     0, seeds.CERTIFY_NAME) & 1
    bi = to_board_inputs(cs, {p: i for i, p in enumerate(cs.pairs)})
    adm = fc.admissions(cs, w, required=cs.cells)
    supplied = adm if supplied is None else supplied
    ref = certify.certify(
        bi.pairs, bi.scores, bi.controls, required=cs.cells,
        eligibility={k: certify.Eligibility(False, bi.coverage[k], bi.shortfall[k]) for k in cs.cells},
        admissions=dict(supplied), board=certify.Board("season", "text", True, len(cs.pairs), 150),
        seed=seeds.CERTIFY_SEED, name=seeds.CERTIFY_NAME, draws=draws,
        bounds=certify.Bounds(len(cs.pairs), 150, bound), block_of=bi.block_of,
    )
    assert adm == tuple((c.cell, certify.cell_admission(
        c, replace(c, verdict="UNRESOLVED", score_pairs=c.pairs, pooled_pairs=()),
    )) for c in ref.cells)
    dec = fc.decide(cs, w, required=cs.cells, se_bound=bound, n_lives=len(cs.pairs), b=150,
                    mode="full", admissions=supplied)
    auto = fc.decide(cs, w, required=cs.cells, se_bound=bound, n_lives=len(cs.pairs), b=150,
                     admissions=supplied)
    assert (dec.outcome, dec.reasons) == (ref.outcome, ref.reasons)
    assert dec.se2 == tuple((c.cell, c.margin.se2 if c.margin else None) for c in ref.cells)
    assert dec.admissions == tuple(supplied)
    estimates = (("mean", ref.mean_margin), *((c.cell, c.margin) for c in ref.cells))
    assert dec.lower == tuple((k, est.lower if est else None,
                               sorted(est.replicates)[tcal.index(draws, 50_000)] if est else None)
                              for k, est in estimates)
    non_bootstrap = all(reason == "r_a" or reason.startswith("r_b:") for reason in ref.reasons)
    unc = non_bootstrap and all(upper is not None and upper >= (-10 if i else 0)
                               for i, (_, _, upper) in enumerate(dec.lower))
    assert dec.certified == (ref.outcome == "CERTIFIED", unc)
    assert (auto.outcome, auto.certified, auto.se2, auto.admissions) == (
        dec.outcome, dec.certified, dec.se2, dec.admissions)
    assert auto.lower is auto.reasons is None
    if supplied == adm:
        assert fc.decide(cs, w, required=cs.cells, se_bound=bound, n_lives=len(cs.pairs),
                         b=150) == auto
    if check_functionals:
        compare_functionals(cs, w, certify._prepare(bi.pairs, bi.scores, bi.controls, None, False))
    return dec, ref


def test_200_keyed_fakes():
    not_admitted = blocked = 0
    for rep in range(200):
        cs, bound = fake(rep)
        dec, ref = compare_reference(cs, bound, 200)
        not_admitted += any(v == "NOT_ADMITTED" for _, v in dec.admissions)
        blocked += any(c.blocked for c in ref.cells)
    assert not_admitted >= 20
    assert blocked >= 10


@pytest.mark.parametrize("rep", (1, 2, 3))
def test_10000_draw_fakes(rep):
    cs, bound = fake(rep)
    compare_reference(cs, bound, 10_000, check_functionals=False)


def test_decision_classes_and_precedence():
    pairs = ("p", "q", "r", "s")
    good = {("X", p): PairCell(1, 600, True, 1, -200, 600) for p in pairs}
    cs = make_cs(pairs, good)
    dec, _ = compare_reference(cs, Fraction(5), 200)
    assert dec.outcome == "CERTIFIED"
    for score, outcome in ((100, "NOT_CERTIFIED"), (200, "CERTIFIED")):
        other = replace(cs, entries={k: replace(e, s_sum=score) for k, e in good.items()})
        dec, _ = compare_reference(other, Fraction(5), 200)
        assert dec.outcome == outcome
    # A positive joint margin still fails R-b in the negative cell.
    entries = {**{("X", p): replace(e, s_sum=-100) for (_, p), e in good.items()},
               **{("Y", p): e for (_, p), e in good.items()}}
    dec, _ = compare_reference(make_cs(pairs, entries), Fraction(5), 200)
    assert dec.reasons == ("r_b:X",)
    for coverage, shortfall, outcome in ((Fraction(9, 10), "infrastructure", "DEFERRED"),
                                        (Fraction(9, 10), "system", "NOT_CERTIFIED")):
        other = replace(cs, coverage={"X": coverage}, shortfall={"X": shortfall})
        dec, _ = compare_reference(other, Fraction(5), 200)
        assert dec.outcome == outcome
    noisy = replace(cs, entries={key: replace(e, s_sum=-1000 if key[1] == "p" else 1000)
                                for key, e in good.items()})
    noisy = replace(noisy, coverage={"X": Fraction(9, 10)}, shortfall={"X": "system"})
    dec, _ = compare_reference(noisy, Fraction(1), 200)
    assert dec.outcome == "NO_CERTIFICATE"
    # Admission is an explicit input; an undefined value defers even with full support.
    dec, _ = compare_reference(cs, Fraction(5), 200, supplied=(("X", None),))
    assert dec.reasons == ("admission_undefined:X",)


def test_full_never_screens_and_pair_order(hand):
    cs = make_cs(hand.pairs, {("mean", p): PairCell(1, 150, True, 1, -200, 600)
                              for p in hand.pairs})
    # Cell ID "mean" is allowed: only the first lower is R-a's joint.
    dec, _ = compare_reference(cs, Fraction(5), 200)
    assert dec.reasons == ("r_a",)
    with patch.object(fc, "screen", side_effect=AssertionError("full mode screened")):
        full = fc.decide(cs, hand, required=cs.cells, se_bound=Fraction(5), n_lives=2,
                         b=150, mode="full")
    assert full.lower == (("mean", Fraction(-5), Fraction(-5)),
                          ("mean", Fraction(-5), Fraction(-5)))
    reversed_w = fc.WeightCache.from_matrix(tuple(reversed(hand.pairs)),
                                           tuple(tuple(reversed(row)) for row in ROWS))
    assert fc.decide(cs, reversed_w, required=cs.cells, se_bound=Fraction(5), n_lives=2,
                     b=150, mode="full") == full
    assert fc.decide(replace(cs, pairs=tuple(reversed(cs.pairs))), hand, required=cs.cells,
                     se_bound=Fraction(5), n_lives=2, b=150, mode="full") == full


def test_required_subset_and_zero_coefficients():
    pairs = ("p", "q", "r", "s")
    entries = {(k, p): PairCell(1, 200, True, 1, -200, 600)
               for k in ("X", "Y") for p in pairs}
    entries["Y", "p"] = PairCell(0, 0, False, 0, 0, 0)
    entries["Y", "q"] = PairCell(0, 0, False, 0, 0, 0)
    cs = make_cs(pairs, entries)
    w = fc.WeightCache.from_seed((*pairs, "unused"), "subset", "test", 200)
    margins, joint = fc.margin_functionals(cs, ("X",), w)
    assert margins == (("X", fc.Functional((0,) * 5, 0, 1, 4)),)
    assert joint == margins[0][1]
    assert fc.gap_functionals(cs, ("X",), w) == (("X", fc.Functional((0,) * 5, 80, 1, 4)),)
    # Zero coefficients still count their resampling units in the union.
    all_cells, joint = fc.margin_functionals(cs, ("Y", "X"), w)
    assert tuple(k for k, _ in all_cells) == ("X", "Y")
    assert dict(all_cells)["Y"].units == 2
    assert joint.units == 4
    bi = to_board_inputs(cs, {p: i for i, p in enumerate(pairs)})
    ref = certify.certify(
        bi.pairs, bi.scores, bi.controls, required=("X",),
        eligibility={"X": certify.Eligibility(False, Fraction(1))},
        admissions={"X": "ADMITTED"}, board=certify.Board("season", "text", True, 4, 150),
        seed="subset", name="test", draws=200, bounds=certify.Bounds(4, 150, Fraction(5)),
        block_of=bi.block_of,
    )
    dec = fc.decide(cs, w, required=("X",), se_bound=Fraction(5), n_lives=4, b=150, mode="full")
    assert (dec.outcome, dec.reasons) == (ref.outcome, ref.reasons) == ("CERTIFIED", ())
    assert dec.admissions == (("X", "ADMITTED"),)


def test_lanes_and_large_lcm(hand):
    assert fc._lanes(fc.Functional((2**61, 0), 0, 1, 2), hand, 0)[2] == 64
    assert fc._lanes(fc.Functional((2**62, 0), 0, 1, 2), hand, 0)[2] == 128
    for m, width in ((2**61, 64), (2**62, 128), (2**140 + 7, 192)):
        f = fc.Functional((m, -m // 3), 7, 3, 2)
        # Width depends on the sum of absolute coefficients, too.
        assert fc._lanes(f, hand, 0)[2] == width
        for threshold in (-10, 0, 30):
            assert fc.count_below(f, hand, threshold) == sum(v < threshold for v in values(f, hand))
    primes = (7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47)
    pairs = tuple(f"p{i}" for i in range(12))
    cs = make_cs(pairs, {
        ("X", p): PairCell(n, (i * 137 % 1801 - 900) * n + i, True, n, -200 * n, 600 * n)
        for i, (p, n) in enumerate(zip(pairs, primes, strict=True))
    })
    w = fc.WeightCache.from_seed(pairs, "lanes", "test", 200)
    f = fc.margin_functionals(cs, cs.cells, w)[0][0][1]
    assert lcm(*primes) > 10**16
    assert sum(abs(c) for c in f.coef) > 2**64
    assert fc._lanes(f, w, 0)[2] >= 128
    for threshold in (-10, 0, 30):
        assert fc.count_below(f, w, threshold) == sum(v < threshold for v in values(f, w))


def test_validation(hand):
    for draws in (0, -1, True, 1.0, "4"):
        with rejects("draws must be an integer >= 1"):
            fc.WeightCache.from_seed(("p",), "seed", "name", draws)
    with rejects("draws must be an integer >= 1"):
        fc.WeightCache.from_matrix(("p",), ())
    for pairs in (("p", "p"), (1,), (True,)):
        for factory, args in ((fc.WeightCache.from_seed, ("s", "n", 4)),
                              (fc.WeightCache.from_matrix, (ROWS,))):
            with rejects("pairs must be unique strings"):
                factory(pairs, *args)
    for rows in (((1,),), ((1, 0),), ((1, True),), ((1, -1, 1),)):
        with rejects("weights must supply +1 or -1 for every pair"):
            fc.WeightCache.from_matrix(hand.pairs, rows)
    for f in (fc.Functional((1,), 0, 1, 2), fc.Functional((1, 2), 0, 0, 2),
              fc.Functional((1, 2), 0, -1, 2)):
        for call in (lambda f=f: fc.count_below(f, hand, 0), lambda f=f: fc.moments(f, hand),
                     lambda f=f: fc.se2(f, hand), lambda f=f: fc.screen(f, hand, 0, (0,))):
            with rejects("functional does not match the weight cache"):
                call()
    cs = make_cs(hand.pairs, {("X", p): PairCell(1, 100, True, 1, 0, 600) for p in hand.pairs})
    kwargs = dict(required=("X",), se_bound=Fraction(5), n_lives=2, b=150)
    for required, message in (((), "required cells must be nonempty and unique"),
                              (("X", "X"), "required cells must be nonempty and unique"),
                              (("Y",), "missing required cell metadata")):
        for call in (lambda required=required: fc.decide(cs, hand, **{**kwargs, "required": required}),
                     lambda required=required: fc.margin_functionals(cs, required, hand),
                     lambda required=required: fc.gap_functionals(cs, required, hand),
                     lambda required=required: fc.admissions(cs, hand, required=required)):
            with rejects(message):
                call()
    with rejects("pair q has no weights"):
        fc.margin_functionals(cs, ("X",), fc.WeightCache.from_matrix(("p",), ((1,),)))
    with rejects("SE bound must be nonnegative"):
        fc.decide(cs, hand, **{**kwargs, "se_bound": Fraction(-1)})
    for adm in ((), (("Y", "ADMITTED"),), (("X", None), ("X", None))):
        with rejects("missing required cell metadata"):
            fc.decide(cs, hand, **kwargs, admissions=adm)
    with rejects("unknown admission"):
        fc.decide(cs, hand, **kwargs, admissions=(("X", "CLEAR"),))
    with rejects('mode must be "decide" or "full"'):
        fc.decide(cs, hand, **kwargs, mode="other")
