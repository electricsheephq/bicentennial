"""Synthetic variance, probability and quadrature checks for #245."""

import math
from fractions import Fraction
from statistics import variance

import pytest

from bicentennial.canon import canon
from bicentennial.ocsim import gaussian as g
from bicentennial.ocsim import model, run

from .test_run import tiny_config, tiny_raw


def design():
    return model.LatentParams((model.CellModel(
        "X", (-1000, 0, 1000), (-0.5, 0.5), -200, 600, 40, 60),), 0.3, 0.4, 1, 0)


def test_variance_keyed_pairs():
    params, alloc, margins = design(), {("X", 2): 100}, {"X": 5}
    pairs = tuple(f"p{i}" for i in range(4000))
    effects = model.life_effects(params, pairs, "variance", 0)
    targets = model.expected_units(params, effects, margins)
    from bicentennial.ocsim import locate
    scores = model.cell_scores(model.sample_bundles(params, {(*k, 2): v for k, v in targets.items()},
        alloc, pairs, "variance", 0, solver=locate.table_solver(params)))
    observed = variance(float(scores["S", p, "X"] - (scores["F", p, "X"]
                        + scores["C", p, "X"]) / 2) for p in pairs)
    _, sigma = g.moments(params, alloc, margins)
    assert abs(observed / sigma[0][0] - 1) <= 0.05, (observed, sigma)


@pytest.mark.parametrize("binding", [False, True])
def test_end_to_end_wilson_overlap(monkeypatch, binding):
    raw = tiny_raw()
    raw["lives"] = [{**raw["lives"][1], "life": f"p{i}"} for i in range(24)]
    raw["probe_only"]["anchor_tokens"] = {life["life"]: 0 for life in raw["lives"]}
    raw["passover"] = {"failed": "0/1", "blocked": "0/1"}
    raw["control_failure"], raw["params"]["sigma_d2"] = "0/1", 0.0.hex()
    raw["rows"][0]["rate"] = "1/1"
    for lane in raw["lanes"]:
        lane["concurrency"] = 50
    raw["alloc_by_b"] = {"50": [["X", 2, 25], ["X", 3, 25]]}
    inputs = run.parse_inputs(canon(raw), ladder=((24, 50),))
    config = tiny_config(alternatives=("LITERAL",), ladder=((24, 50),),
                         constants={**run.test_constants(), "DRAWS": 999})
    # At the central-t critical effect size, power is near one half.
    _, sigma = g.moments(inputs.params, inputs.alloc_by_b[50], {"X": 0})
    margin = Fraction(str(g.t95(23) * math.sqrt(sigma[0][0] / 24)))
    if binding:
        margin = Fraction(15)
    _, sigma = g.moments(inputs.params, inputs.alloc_by_b[50], {"X": margin})
    bound = Fraction(str(math.sqrt(sigma[0][0] * 23) / 24 * (1 - 2 / 207) ** 1.5)) if binding else Fraction(1000)
    prediction = g.predict(inputs.params, (24, 50), inputs.alloc_by_b[50], {"X": margin},
                           "LITERAL", se_bound=bound)
    lo, hi = prediction["gaussian_ppm"]
    assert 300_000 < lo <= hi < 700_000 and hi - lo <= 20_000
    if binding:
        assert 499_999 <= hi <= 500_001
    ctx = run.PointContext(inputs, config, (24, 50), bounds={"LITERAL": bound})
    monkeypatch.setattr(run, "audit_selected", lambda rep: False)
    ctx.phase = "cross-check"
    case = "LITERAL|base|none|interior"
    margins = (run.MarginConfig("interior", (("X", margin),), None),)
    count = sum(run.evaluate(ctx, rep, (case,), margins=margins)[case].certified[0]
                for rep in range(2000))
    z = g.NORMAL.inv_cdf(0.9995)
    center = (count + z * z / 2) / (2000 + z * z)
    radius = z * math.sqrt(count * (2000 - count) / 2000 + z * z / 4) / (2000 + z * z)
    assert center - radius <= hi / 1e6 and center + radius >= lo / 1e6, (count, prediction)


@pytest.mark.parametrize("df,t,tail", [(1, 1, 0.25), (2, math.sqrt(2), (1 - 1 / math.sqrt(2)) / 2),
    (1, 6.313751514675041, 0.05), (9, 1.8331129326536335, 0.05), (23, 1.7138715277470473, 0.05)])
def test_noncentral_t_hand_values(df, t, tail):
    assert g.nct_tail(t, df, 0) == pytest.approx(tail, abs=1e-9, rel=0)
    tails = [g.nct_tail(t, df, delta) for delta in (-2, 0, 1, 3)]
    assert all(a < b for a, b in zip(tails, tails[1:], strict=False))


@pytest.mark.parametrize("ps,expected", [([0.5], [500000, 500000]),
    ([0.5, 0.75], [250000, 500000]), ([0.75] * 3, [250000, 750000]),
    ([0.25] * 3, [0, 250000]), ([0.1234567], [123456, 123457])])
def test_bracket_algebra(ps, expected):
    assert g.bracket(ps) == expected


def test_integer_output_and_scopes(monkeypatch):
    params, alloc = design(), {("X", 2): 10, ("X", 3): 30}
    prediction = g.predict(params, (24, 40), alloc, {"X": 5}, "LITERAL")
    def check(value):
        if isinstance(value, dict):
            return all(check(v) for v in value.values())
        if isinstance(value, list):
            return all(check(v) for v in value)
        return type(value) is int or (isinstance(value, str) and value.endswith("/1000")
                                     and value[:-5].isdigit())
    assert check(prediction) and canon(prediction)
    assert prediction["gaussian_ppm"][0] <= prediction["gaussian_ppm"][1]
    assert prediction["gaussian_ppm"] != prediction["uncalibrated_ppm"]
    assert prediction == g.predict(params, (24, 40), alloc, {"X": 5}, "SWAP_GATE")
    pre = g.predict(params, (24, 40), alloc, {"X": 5}, "PRE_SWAP", swaps=(3,) * 24)
    assert pre == g.predict(params, (24, 10), {("X", 2): 10}, {"X": 5}, "LITERAL")
    assert pre != prediction
    assert g.predict(params, (24, 40), alloc, {"X": 5}, "PRE_SWAP", swaps=(2, 3)) is None
    # df=1: P(t > c) = 1/2 - atan(c)/pi; wild SE is s/sqrt(n)*sqrt((n-1)/n).
    monkeypatch.setattr(g, "moments", lambda *args: ([0.0], [[1.0]]))
    hand = g.predict(params, (2, 40), alloc, {"X": 0}, "LITERAL")["uncalibrated_ppm"]
    ppm = 1e6 * (0.5 - math.atan(1.6448536269514722 / math.sqrt(2)) / math.pi)
    assert hand == [math.floor(ppm), math.ceil(ppm)]


def test_se_bound_median_and_nonbinding():
    params, alloc, margins = design(), {("X", 2): 100}, {"X": 10}
    _, sigma = g.moments(params, alloc, margins)
    median = math.sqrt(sigma[0][0] * 23) / 24 * (1 - 2 / 207) ** 1.5
    old = g.predict(params, (24, 100), alloc, margins, "LITERAL")
    bound = g.predict(params, (24, 100), alloc, margins, "LITERAL", se_bound=median)
    assert old["gaussian_ppm"][0] > 900_000
    assert 499_999 <= bound["gaussian_ppm"][1] <= 500_001
    assert old == g.predict(params, (24, 100), alloc, margins, "LITERAL", se_bound=1000)


def test_cell_se_names_follow_the_cells():
    x = design().cells[0]
    y = model.CellModel("Y", (-1000, 0, 1000), (-0.5, 0.5), -100, 300, 20, 90)
    params, alloc = model.LatentParams((x, y), 0.3, 0.4, 1, 0), {("X", 2): 10, ("Y", 2): 30}
    forward = g.predict(params, (24, 40), alloc, {"X": 5, "Y": 5}, "LITERAL")["cell_se"]
    backward = g.predict(params, (24, 40), alloc, {"Y": 5, "X": 5}, "LITERAL")["cell_se"]
    alone = g.predict(design(), (24, 40), {("X", 2): 10}, {"X": 5}, "LITERAL")["cell_se"]
    assert forward == backward and forward["X"] == alone["X"] != forward["Y"]

@pytest.fixture(autouse=True)
def under_one_minute():
    from time import perf_counter
    started = perf_counter()
    yield
    assert perf_counter() - started < 60
