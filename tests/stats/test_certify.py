"""Issue #240: written under measurement hold; intended for GitHub CI."""

from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from itertools import product

import pytest

from bicentennial.stats import certify as module
from bicentennial.stats.certify import (
    REASON_LABELS,
    Board,
    Bounds,
    Eligibility,
    _estimate,
    _replicates,
    cell_admission,
    cell_statistics,
    certify,
)

PAIRS = ("p0", "p1", "p2", "p3")
BOARD = Board("season", "text", True, 24, 150)
OPTIONS = {"seed": "certify-fixture", "name": "act", "draws": 16}


@pytest.fixture
def tight_draw(monkeypatch):
    # Enumerate all 16 assignments for four pairs; shared across all cells.
    def fake(seed, unit, attempt, name):
        assert seed == OPTIONS["seed"] and name == OPTIONS["name"]
        assert unit[:2] == ("stats", "certify")
        return (attempt >> int(unit[-1][-1])) & 1

    monkeypatch.setattr(module, "draw", fake)


def fixture(margins=(20,), noise=Fraction(1, 10)):
    pairs = {f"c{i}": PAIRS for i in range(len(margins))}
    scores = {(k, p): Fraction(margins[i]) + (-noise if j % 2 == 0 else noise)
              for i, k in enumerate(pairs) for j, p in enumerate(PAIRS)}
    controls = {(k, p): (-40, 40) for k in pairs for p in PAIRS}
    return pairs, scores, controls


def decision(data, **overrides):
    pairs, scores, controls = data
    kwargs = dict(required=tuple(pairs), eligibility=dict.fromkeys(pairs, Eligibility(False, 1)),
                  admissions=dict.fromkeys(pairs, "ADMITTED"), board=BOARD, **OPTIONS)
    kwargs.update(overrides)
    result = certify(pairs, scores, controls, **kwargs)
    assert all(reason.split(":", 1)[0] in REASON_LABELS for reason in result.reasons)
    return result


def test_four_pair_gate_and_exact_se_hand_worked(monkeypatch):
    pairs = {"c": PAIRS}
    controls = {("c", p): (10 * i, 10 * i + 20) for i, p in enumerate(PAIRS)}
    scores = dict.fromkeys(controls, 60)
    signs = ((1, 1, 1, 1), (-1, -1, -1, -1), (1, 1, -1, -1), (-1, -1, 1, 1))
    vectors = [dict(zip(PAIRS, row, strict=True)) for row in signs]
    rows = _replicates(pairs, scores, controls, vectors)
    assert tuple(row[0][0] for row in rows) == (25, 25, 15, 35)
    assert tuple(row[0][3] for row in rows) == (35, 35, 45, 25)
    monkeypatch.setattr(module, "draw", lambda seed, unit, r, name: int(vectors[r][unit[-1]] == 1))
    cell, = cell_statistics(pairs, scores, controls, seed="hand", name="gate", draws=4)
    assert cell.floor == 15 and cell.ceiling == 35
    assert cell.support == 4 and not cell.blocked
    assert cell.gate.point == 25 and cell.gate.se2 == 50
    assert cell.gate.se_milli == 7071
    assert cell.gate.lower == 15 and cell.gate.interval == (15, 35)
    assert cell.margin.se2 == 50


def pooled_fixture():
    pairs = {"c": PAIRS}
    controls = {("c", p): (10 * i - 10, 10 * i + 10) for i, p in enumerate(PAIRS[:3])}
    scores = {("c", "p0"): 40, ("c", "p3"): 40}
    return pairs, scores, controls


def test_pooled_pair_uses_moving_gate_and_point_is_all_positive():
    pairs, scores, controls = pooled_fixture()
    vectors = [dict(zip(PAIRS, row, strict=True)) for row in
               ((1, -1, -1, 1), (-1, 1, 1, -1), (1, 1, 1, 1))]
    rows = _replicates(pairs, scores, controls, vectors)
    # First: own gate=0, pooled=(0+10+0)/3; second: own=20,
    # pooled=(20+10+20)/3. Both the own gate and pooled gate move.
    assert tuple(row[0][0] for row in rows) == (Fraction(10, 3), Fraction(50, 3), 10)
    assert tuple(row[0][3] for row in rows) == (Fraction(115, 3), Fraction(65, 3), 35)
    cell, = cell_statistics(pairs, scores, controls, **OPTIONS)
    assert cell.margin.point == rows[-1][0][3] == 35
    assert cell.pooled_pairs == ("p3",) and cell.support == 3 and not cell.blocked
    excluded = _replicates(pairs, scores, controls, vectors, exclude_pooled=True)
    assert tuple(row[0][3] for row in excluded) == (40, 20, 40)
    sensitivity, = cell_statistics(pairs, scores, controls, exclude_pooled=True, **OPTIONS)
    assert sensitivity.score_pairs == ("p0",) and sensitivity.pooled_pairs == ()
    assert sensitivity.support == cell.support and sensitivity.gate == cell.gate


def test_multiple_pooled_pairs_share_one_gate_error():
    pairs, _, controls = pooled_fixture()
    pairs["c"] = (*PAIRS, "p4")
    scores = {("c", "p3"): 40, ("c", "p4"): 40}
    vectors = [dict(zip(pairs["c"], row, strict=True)) for row in
               ((1, -1, -1, 1, -1), (-1, 1, 1, -1, 1))]
    rows = _replicates(pairs, scores, controls, vectors)
    assert tuple(row[0][3] for row in rows) == (Fraction(110, 3), Fraction(70, 3))
    assert all(row[0][3] == 40 - row[0][0] for row in rows)
    gate = _estimate(Fraction(10), tuple(row[0][0] for row in rows))
    margin = _estimate(Fraction(30), tuple(row[0][3] for row in rows))
    assert margin.se2 == gate.se2 == Fraction(400, 9)


def test_fractional_system_and_controls_use_same_weight_and_exact_scale():
    pairs = {"c": ("p0", "p1")}
    controls = {("c", "p0"): (Fraction(-4, 3), Fraction(2, 3)),
                ("c", "p1"): (Fraction(-6, 7), Fraction(8, 7))}
    scores = {("c", "p0"): 20 - Fraction(1, 3), ("c", "p1"): 20 + Fraction(1, 7)}
    vectors = [{"p0": 1, "p1": -1}, {"p0": -1, "p1": 1}, {"p0": 1, "p1": 1}]
    rows = _replicates(pairs, scores, controls, vectors)
    assert tuple(row[0][0] for row in rows) == (Fraction(-1, 3), Fraction(1, 7), Fraction(-2, 21))
    assert all(row[0][1] == row[0][0] + 20 and row[0][3] == 20 for row in rows)


@pytest.mark.parametrize("blocks,expected", [
    ({"p0": 0, "p1": 1, "p2": 2, "p3": 3}, (15, 35)),
    ({"p0": 0, "p1": 2, "p2": 2, "p3": 5}, (10, 30)),
    (dict.fromkeys(PAIRS, 7), (None, 25)),
])
def test_half_gates_by_distinct_blocks_including_odd(blocks, expected):
    controls = {("c", p): (10 * i, 10 * i + 20) for i, p in enumerate(PAIRS)}
    cell, = cell_statistics({"c": PAIRS}, {}, controls, block_of=blocks, **OPTIONS)
    assert cell.half_gates == expected


def test_half_gates_use_only_valid_control_blocks():
    pairs, scores, controls = pooled_fixture()
    cell, = cell_statistics(pairs, scores, controls,
                            block_of={"p0": 1, "p1": 2, "p2": 3, "p3": 0}, **OPTIONS)
    assert cell.half_gates == (0, 15)


def test_percentile_indices_population_variance_and_integer_sqrt():
    result = _estimate(Fraction(20), tuple(Fraction(i) for i in range(40)))
    assert result.lower == 1  # ceil(.05*40)-1
    assert result.interval == (0, 38)  # bootstrap_ci's inverse empirical CDF
    assert result.se2 == Fraction(533, 4)
    assert result.se_milli == 11543
    single = _estimate(Fraction(7, 3), (Fraction(7, 3),))
    assert single.lower == Fraction(7, 3) and single.se2 == 0


@pytest.mark.parametrize("margins,outcome,reasons", [
    ((20, 20, 20, 20), "CERTIFIED", ()),
    ((0,), "NOT_CERTIFIED", ("r_a",)),
    ((10, 10, 10, -15), "NOT_CERTIFIED", ("r_b:c3",)),
])
def test_certification_margin_fakes(tight_draw, margins, outcome, reasons):
    result = decision(fixture(margins))
    assert result.outcome == outcome and result.reasons == reasons
    assert result.r_a is ("r_a" not in reasons)
    assert result.stability == (Fraction(11, 16) if margins == (0,) else Fraction(outcome == "CERTIFIED"))
    assert all(c.margin is not None and c.margin.se2 == Fraction(1, 400) for c in result.cells)


@pytest.mark.parametrize("eligibility,outcome,reason", [
    (Eligibility(True, 1), "NOT_CERTIFIED", "na_reader:c0"),
    (Eligibility(False, Fraction(94, 100), "system"), "NOT_CERTIFIED", "coverage_system:c0"),
    (Eligibility(False, Fraction(94, 100), "infrastructure"), "DEFERRED", "coverage_infrastructure:c0"),
    (Eligibility(False, Fraction(95, 100)), "CERTIFIED", None),
])
def test_eligibility_causes(tight_draw, eligibility, outcome, reason):
    result = decision(fixture(), eligibility={"c0": eligibility})
    assert result.outcome == outcome
    assert result.reasons == (() if reason is None else (reason,))
    assert result.mean_margin is not None and result.stability == 1


@pytest.mark.parametrize("admission,reason", [
    ("NOT_ADMITTED", "not_admitted:c0"), (None, "admission_undefined:c0"),
])
def test_admission_defers_certification(tight_draw, admission, reason):
    result = decision(fixture(), admissions={"c0": admission})
    assert result.outcome == "DEFERRED" and result.reasons == (reason,)


def test_control_support_below_three_quarters_defers_and_retains_scores(tight_draw):
    pairs, scores, controls = fixture()
    del controls["c0", "p2"]
    del controls["c0", "p3"]
    result = decision((pairs, scores, controls))
    assert result.outcome == "DEFERRED" and result.reasons == ("blocked:c0",)
    cell, = result.cells
    assert cell.verdict == "BLOCKED" and cell.support == 2
    assert cell.pooled_pairs == ("p2", "p3") and cell.score_pairs == PAIRS
    assert cell.margin is not None and result.mean_margin is not None


@pytest.mark.parametrize("board,reasons", [
    (replace(BOARD, kind="pilot"), ("board_kind",)),
    (replace(BOARD, kind="developer"), ("board_kind",)),
    (replace(BOARD, kind="delta", profile="image"), ("image_season_only",)),
    (replace(BOARD, profile="image", n_lives=8, b=40),
     ("image_planning_size", "n_lives", "bundles")),
    (replace(BOARD, sealed=False), ("unsealed",)),
    (replace(BOARD, n_lives=23), ("n_lives",)),
    (replace(BOARD, b=149), ("bundles",)),
])
def test_board_cannot_issue_certificate(tight_draw, board, reasons):
    result = decision(fixture(), board=board)
    assert result.outcome == "NO_CERTIFICATE" and result.reasons == reasons
    assert result.r_a and result.stability == 1 and result.cells[0].margin is not None


def test_powered_image_season_and_text_delta_with_parameterized_bounds(tight_draw):
    image = replace(BOARD, profile="image", n_lives=16, b=80)
    assert decision(fixture(), board=image, bounds=Bounds(16, 80, 5)).outcome == "CERTIFIED"
    assert decision(fixture(), board=replace(BOARD, kind="delta")).outcome == "CERTIFIED"
    # Even a caller-supplied low bound cannot certify the explicit planning board.
    result = decision(fixture(), board=replace(image, n_lives=8, b=40), bounds=Bounds(8, 40, 5))
    assert result.reasons == ("image_planning_size",)


@pytest.mark.parametrize("noise,outcome", [(Fraction(10), "CERTIFIED"),
                                         (Fraction(10_000_001, 1_000_000), "NO_CERTIFICATE")])
def test_se_bound_is_exact_not_rounded(tight_draw, noise, outcome):
    result = decision(fixture(noise=noise))
    assert result.outcome == outcome
    assert result.cells[0].margin.se2 == noise * noise / 4
    assert result.cells[0].margin.se_milli == 5000
    assert result.reasons == (() if outcome == "CERTIFIED" else ("se:c0",))


def test_outcome_precedence_and_all_defined_diagnostics(tight_draw):
    data = fixture((0,))
    kwargs = dict(eligibility={"c0": Eligibility(True, 1)}, admissions={"c0": None})
    assert decision(data, board=replace(BOARD, sealed=False), **kwargs).reasons == ("unsealed",)
    assert decision(data, **kwargs).reasons == ("na_reader:c0",)
    result = decision(data, admissions={"c0": None})
    assert result.outcome == "DEFERRED" and result.reasons == ("admission_undefined:c0",)
    assert result.r_a is False and result.r_b == (("c0", True),)
    assert result.mean_margin.lower < 0 and result.stability == Fraction(11, 16)


@pytest.mark.parametrize("empty,expected", [
    ("scores", ("empty_scores:c0",)),
    ("controls", ("blocked:c0", "empty_controls:c0")),
])
def test_empty_required_sets_defer_with_undefined_diagnostics(tight_draw, empty, expected):
    pairs, scores, controls = fixture()
    result = decision((pairs, {} if empty == "scores" else scores,
                       {} if empty == "controls" else controls))
    assert result.outcome == "DEFERRED" and result.reasons == expected
    assert result.mean_margin is None and result.r_a is None and result.stability is None
    assert result.cells[0].margin is None and result.cells[0].verdict is None
    assert result.r_b == (("c0", None),)


@pytest.mark.parametrize("score,verdict", [(0, "CLEAR"), (-1, "FAIL"), (None, "UNRESOLVED")])
def test_display_verdicts_against_point_gate(tight_draw, score, verdict):
    data = fixture((0,), noise=Fraction(1) if score is None else Fraction(0))
    pairs, scores, controls = data
    if score is not None:
        scores = dict.fromkeys(scores, score)
    cell, = cell_statistics(pairs, scores, controls, **OPTIONS)
    assert cell.verdict == verdict


def test_display_blocked_and_undefined_and_empty_universe(tight_draw):
    pairs, scores, controls = fixture()
    partial = {key: value for key, value in controls.items() if key[1] in PAIRS[:2]}
    blocked, = cell_statistics(pairs, scores, partial, **OPTIONS)
    assert blocked.verdict == "BLOCKED"
    for arm, control in (({}, controls), (scores, {}), ({}, {})):
        cell, = cell_statistics(pairs, arm, control, **OPTIONS)
        assert cell.verdict is None
    empty, = cell_statistics({"c0": ()}, {}, {}, block_of={}, **OPTIONS)
    assert empty.verdict is None and empty.half_gates == (None, None)


def admission_fixture(gap=80, naive_score=-20, support=4, valid=4):
    pairs = {"c0": PAIRS}
    controls = {("c0", p): (-Fraction(gap, 2), Fraction(gap, 2)) for p in PAIRS[:valid]}
    cell, = cell_statistics(pairs, {}, controls, **OPTIONS)
    naive, = cell_statistics(pairs, {("c0", p): naive_score for p in PAIRS[:support]}, controls, **OPTIONS)
    return cell, naive


@pytest.mark.parametrize("gap,naive,expected", [
    (80, -20, "ADMITTED"), (30, -20, "ADMITTED"),
    (29, -20, "NOT_ADMITTED"), (80, 0, "NOT_ADMITTED"),
])
def test_cell_admission_gap_boundary_and_naive_clear(tight_draw, gap, naive, expected):
    assert cell_admission(*admission_fixture(gap=gap, naive_score=naive)) == expected


def test_cell_admission_uses_lower_gap_bound_not_point(tight_draw):
    pairs = {"c0": PAIRS}
    controls = {("c0", p): (-15, 14 if i % 2 == 0 else 16) for i, p in enumerate(PAIRS)}
    cell, = cell_statistics(pairs, {}, controls, **OPTIONS)
    naive, = cell_statistics(pairs, dict.fromkeys(controls, -20), controls, **OPTIONS)
    assert cell.gap.point == 30 and cell.gap.lower == 29
    assert cell_admission(cell, naive) == "NOT_ADMITTED"


@pytest.mark.parametrize("case", ["blocked_cell", "blocked_naive", "undefined_naive", "low_naive_support"])
def test_cell_admission_each_no_verdict_case(tight_draw, case):
    cell, naive = admission_fixture()
    if case == "blocked_cell":
        cell, naive = admission_fixture(valid=2)
    elif case == "blocked_naive":
        _, naive = admission_fixture(valid=2)
    elif case == "undefined_naive":
        _, naive = admission_fixture(support=0)
    else:
        _, naive = admission_fixture(support=2)
        assert naive.verdict == "FAIL"
    assert cell_admission(cell, naive) is None
    assert cell_admission(*admission_fixture(support=3)) == "ADMITTED"


def test_joint_resampling_and_exact_key_contract(monkeypatch):
    data = fixture((20, 20))
    calls = []

    def fake(seed, unit, attempt, name):
        calls.append((seed, unit, attempt, name))
        return (attempt >> int(unit[-1][-1])) & 1

    monkeypatch.setattr(module, "draw", fake)
    a, b = cell_statistics(*data, **OPTIONS)
    assert a.arm.replicates == b.arm.replicates and a.margin.replicates == b.margin.replicates
    assert calls == [(OPTIONS["seed"], ("stats", "certify", p), r, OPTIONS["name"])
                     for r in range(16) for p in PAIRS]
    vectors = [dict(zip(PAIRS, row, strict=True)) for row in product((-1, 1), repeat=4)]
    rows = _replicates(*data, vectors)
    assert all(row[0] == row[1] for row in rows)


def test_grouped_resampling_only_plus_or_minus_one_deviation(monkeypatch):
    pairs, scores, _ = pooled_fixture()
    controls = {("c", p): (2 * i - 20, 2 * i + 20) for i, p in enumerate(PAIRS[:3])}
    calls = []

    def fake(seed, unit, r, name):
        calls.append(unit)
        return r & 1

    monkeypatch.setattr(module, "draw", fake)
    cell, = cell_statistics(pairs, scores, controls, groups=dict.fromkeys(PAIRS, "one"), **OPTIONS)
    assert set(cell.margin.replicates) == {Fraction(37), Fraction(39)}
    assert cell.margin.point == 39 and cell.margin.se2 == 1
    assert calls == [("stats", "certify", "one")] * 16
    with pytest.raises(ValueError, match="every pair"):
        cell_statistics(pairs, scores, controls, groups={"p0": "one"}, **OPTIONS)


def test_determinism_sorted_inputs_and_frozen_results():
    pairs, scores, controls = fixture((20, 10))
    first = decision((pairs, scores, controls))
    reordered = ({k: tuple(reversed(v)) for k, v in reversed(tuple(pairs.items()))},
                 dict(reversed(tuple(scores.items()))), dict(reversed(tuple(controls.items()))))
    second = decision(reordered, required=("c1", "c0"))
    assert first == second
    assert repr(first).encode() == repr(second).encode()
    assert all(isinstance(value, Fraction) for c in first.cells for value in c.margin.replicates)
    with pytest.raises(FrozenInstanceError):
        first.cells[0].support = 99
    with pytest.raises(FrozenInstanceError):
        first.outcome = "DEFERRED"
    assert all(reason.split(":", 1)[0] in REASON_LABELS for reason in first.reasons)


@pytest.mark.parametrize("where", ["score", "floor", "ceiling", "coverage", "se"])
@pytest.mark.parametrize("value", [0.5, True])
def test_floats_and_boolean_numeric_inputs_refused(where, value):
    pairs, scores, controls = fixture()
    with pytest.raises(TypeError, match="Fraction or int"):
        if where == "coverage":
            Eligibility(False, value)
        elif where == "se":
            Bounds(se=value)
        else:
            if where == "score":
                scores["c0", "p0"] = value
            else:
                controls["c0", "p0"] = (value, 40) if where == "floor" else (-40, value)
            cell_statistics(pairs, scores, controls, **OPTIONS)


@pytest.mark.parametrize("draws", [0, -1, True, Fraction(2), 2.0])
def test_invalid_draw_counts_refused(draws):
    with pytest.raises(ValueError, match="draws"):
        cell_statistics(*fixture(), **dict(OPTIONS, draws=draws))


@pytest.mark.parametrize("mapping", ["scores", "controls"])
@pytest.mark.parametrize("key", [("unknown", "p0"), ("c0", "unknown"), "malformed"])
def test_keys_outside_universe_refused(mapping, key):
    pairs, scores, controls = fixture()
    (scores if mapping == "scores" else controls)[key] = 0 if mapping == "scores" else (-40, 40)
    with pytest.raises(ValueError, match="outside pairs"):
        cell_statistics(pairs, scores, controls, **OPTIONS)


def test_validation_of_blocks_weights_metadata_and_ranges():
    data = fixture()
    with pytest.raises(ValueError, match="block_of"):
        cell_statistics(*data, block_of={}, **OPTIONS)
    with pytest.raises(TypeError, match="block IDs"):
        cell_statistics(*data, block_of=dict.fromkeys(PAIRS, 1.0), **OPTIONS)
    with pytest.raises(ValueError, match="weights"):
        _replicates(*data, [dict.fromkeys(PAIRS, 0)])
    with pytest.raises(ValueError, match="nonempty and unique"):
        decision(data, required=())
    with pytest.raises(ValueError, match="metadata"):
        decision(data, eligibility={})
    with pytest.raises(ValueError, match="metadata"):
        decision(data, admissions={"c0": "ADMITTED", "unknown": None})
    with pytest.raises(ValueError, match="cause"):
        Eligibility(False, Fraction(94, 100))
    data[1]["c0", "p0"] = 101
    with pytest.raises(ValueError, match="raw scores"):
        cell_statistics(*data, **OPTIONS)


def test_required_cells_have_equal_weight_and_r_b_boundary_is_inclusive(tight_draw):
    pairs = {"c0": PAIRS, "c1": ("p0",)}
    controls = {(k, p): (-40, 40) for k in pairs for p in pairs[k]}
    scores = {(k, p): 20 if k == "c0" else -10 for k, p in controls}
    result = decision((pairs, scores, controls))
    assert result.outcome == "CERTIFIED" and result.mean_margin.point == 5
    assert result.r_b == (("c0", True), ("c1", True)) and result.stability == 1
    subset = decision((pairs, scores, controls), required=("c0",),
                      eligibility={"c0": Eligibility(False, 1), "c1": Eligibility(True, 1)},
                      admissions={"c0": "ADMITTED", "c1": "NOT_ADMITTED"})
    assert subset.outcome == "CERTIFIED" and subset.mean_margin.point == 20
    assert len(subset.cells) == 2 and subset.r_b == (("c0", True),)
