import json
import math
import random
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from statistics import NormalDist, mean, stdev
from time import perf_counter

import pytest

from bicentennial.keyed import uniform_int
from bicentennial.ocsim import fitcheck as f
from bicentennial.ocsim import model, run
from bicentennial.stats.variance_inputs import ControlRecord, estimate


@pytest.fixture(autouse=True)
def under_one_minute():
    from time import perf_counter
    started = perf_counter()
    yield
    assert perf_counter() - started < 60


def params():
    return model.LatentParams((
        model.CellModel("A", (-1000, 0, 1000), (-.5, .5), -100, 150, 70, 90),
        model.CellModel("B", (-1000, -250, 0, 125, 375, 625, 875, 1000),
                        (-1.5, -1, -.5, 0, .5, 1, 1.5), -100, 200, 400, 450)), .3, .4, 1, .45)


def rule(p):
    return {c.cell: [(x, y, 1 / 36) for x in (-3, -1.5, -.5, .5, 1.5, 3)
                     for y in (-3, -1.5, -.5, .5, 1.5, 3)] for c in p.cells}


def design(p, lives=16, bundles=30):
    return {(c.cell, str(i)): (bundles, bundles, bundles) for c in p.cells for i in range(lives)}


def records(p, d, rep=0, points=None):
    names = sorted({life for _, life in d})
    effects = model.life_effects(p, names, f.SEED, rep)
    out, solve = [], f.solver(p)
    for (cell_id, life), (nf, nc, shared) in sorted(d.items()):
        c = p.cell(cell_id)
        latents = model.bundle_latents(p, {(cell_id, 0): nf + nc - shared}, [life], f.SEED, rep)[(life, cell_id, 0)]
        xs = ([effects.x[(a, life, cell_id)] for a in ("F", "C")] if points is None else
              points[cell_id][uniform_int(f.SEED, ("fixture", life, cell_id), rep, "point", 0, len(points[cell_id]) - 1)][:2])
        for a, n, base, sd, x in zip(("F", "C"), (nf, nc), (c.f0, c.c0), (c.sigma_f, c.sigma_c), xs, strict=True):
            theta = solve(c, max(-1000, min(1000, base + sd * x)))
            indices = range(n) if a == "F" else (*range(shared), *range(nf, nf + nc - shared))
            for i in indices:
                b0, b1 = model.item_pair(c, theta, *latents[a][i])
                out.append(ControlRecord(a, "A", life, cell_id, 0, f"{life}-{cell_id}-{i}", b0, b1))
    return out


def test_a_exact_and_validation():
    p = params()
    d = design(p, 4, 5)
    d[("A", "0")] = (3, 5, 2)
    rs = records(p, d)
    raw = replace(next(r for r in rs if r.cell == "B"), b0=200, b1=300)
    rs = [raw if (r.arm, r.bundle) == (raw.arm, raw.bundle) else r for r in rs]
    sums, _ = f.prepare(rs, {"B"})
    got = f.statistics(sums, ("A", "B"), sorted({r.life for r in rs}), exact=True)
    for m in estimate(rs, timing_cells=frozenset({"B"})).moments:
        for family, value in (("mean", m.mean), ("msw", m.msw), ("life", m.sigma2_life_raw)):
            assert got[(family, m.arm, m.cell)] == value
            assert isinstance(value, Fraction)
    for bad in (rs + [rs[0]], rs + [replace(rs[0], arm="C", run="A_prime", life="conflict")],
                [replace(rs[0], b0=5)]):
        with pytest.raises(ValueError):
            f.prepare(bad, {"B"})
    assert f.prepare(rs + [replace(rs[0], run="A_prime", b0=None)], {"B"})[0] == sums


def test_b_expectations(capsys):
    p = params()
    d, points = design(p), rule(p)
    expected = f.model_values(p, d, rule=points)
    samples = {k: [] for k in expected if k[0] != "K"}
    started = perf_counter()
    for rep in range(300):
        sums, _ = f.prepare(records(p, d, rep, points), {"B"})
        for k, v in f.statistics(sums, ("A", "B"), sorted({life for _, life in d})).items():
            samples[k].append(v)
    for k, vs in samples.items():
        se = stdev(vs) / math.sqrt(len(vs))
        assert abs(mean(vs) - expected[k]) < 4 * se, (k, mean(vs), expected[k], se)
    with capsys.disabled():
        print("EXPECTATION seconds", perf_counter() - started)
        ses = f.bootstrap(sums, ("A", "B"), sorted({life for _, life in d}), 2000)
        print("MINIMUM BOOTSTRAP SE", {family: min(v for k, v in ses.items() if k[0] == family) for family in f.FAMILIES})
        for c in p.cells:
            residuals = []
            for xf, xc, _ in points[c.cell]:
                for base, sd, x in ((c.f0, c.sigma_f, xf), (c.c0, c.sigma_c, xc)):
                    target = max(-1000, min(1000, base + sd*x))
                    theta = f.solver(p)(c, target)
                    if not isinstance(theta, str):
                        residuals.append(abs(model.expected_min(c, p.rho_t, theta) - target))
            assert max(residuals) < f.locate.BOUND_MILLI
            print("LOCATION residual", c.cell, max(residuals))
            k = ("gate", "F+C", c.cell)
            print("M1 shift", c.cell, expected[("K", "F+C", c.cell)] / 60 / (stdev(samples[k]) / math.sqrt(300)))
            frozen = f.model_values(replace(p, cells=tuple(replace(x, sigma_f=0, sigma_c=0) for x in p.cells)), d, rule=points)
            for a in ("F", "C"):
                k = ("msw", a, c.cell)
                print("M2 shift", a, c.cell, (frozen[k] - expected[k]) / (stdev(samples[k]) / math.sqrt(300)))


def clipped(mu, sd):
    n = NormalDist()
    a, b = (-1000 - mu) / sd, (1000 - mu) / sd
    mass = n.cdf(b) - n.cdf(a)
    m = -1000 * n.cdf(a) + 1000 * (1 - n.cdf(b)) + mu * mass + sd * (n.pdf(a) - n.pdf(b))
    second = 1e6 * (1 - mass) + (mu * mu + sd * sd) * mass + 2 * mu * sd * (n.pdf(a) - n.pdf(b)) + sd * sd * (a * n.pdf(a) - b * n.pdf(b))
    return m, second - m * m


def test_bprime_quadrature(capsys):
    p = params()
    smooth = replace(p, cells=tuple(replace(c, sigma_f=40, sigma_c=50) for c in p.cells))
    life_pass, inner_pass = [], []
    for nodes in range(1, 13):
        v = f.model_values(p, design(p), nodes=nodes)
        errors = [abs(v[(family, a, c.cell)] - target) / tolerance
                  for c in p.cells for a, mu, sd in (("F", c.f0, c.sigma_f), ("C", c.c0, c.sigma_c))
                  for family, target, tolerance in zip(("mean", "life"), clipped(mu, sd), (1, 1000), strict=True)]
        low = f.model_values(smooth, design(smooth), nodes=nodes, shared=32)
        high = f.model_values(smooth, design(smooth), nodes=2*nodes, shared=32)
        smooth_error = max(abs(low[k]-high[k]) for k in low if k[0] in ("msw", "gate", "K"))
        if max(errors) < 1 and smooth_error < 1000:
            life_pass.append(nodes)
        low = f.model_values(smooth, design(smooth), shared=nodes)
        high = f.model_values(smooth, design(smooth), shared=2*nodes)
        inner_error = max(abs(low[k]-high[k]) for k in low if k[0] in ("msw", "gate", "K"))
        if inner_error < 1000:
            inner_pass.append(nodes)
        with capsys.disabled():
            print("NODE CANDIDATE", nodes, "clipped normalized errors", max(errors), "smooth", smooth_error, "inner", inner_error)
    with capsys.disabled():
        print("MINIMUM NODES", life_pass[0], inner_pass[0])
    assert (f.LIFE_NODES, f.SHARED_NODES) == (life_pass[0], inner_pass[0])
    for candidate in (smooth, p):
        started = perf_counter()
        v = f.model_values(candidate, design(candidate))
        chosen_seconds = (perf_counter() - started) / 2
        doubled = f.model_values(candidate, design(candidate), nodes=2*f.LIFE_NODES, shared=2*f.SHARED_NODES)
        for c in candidate.cells:
            for a, mu, sd in (("F", c.f0, c.sigma_f), ("C", c.c0, c.sigma_c)):
                m, var = clipped(mu, sd)
                assert abs(v[("mean", a, c.cell)] - m) < 1
                assert abs(v[("life", a, c.cell)] - var) < 1000
                with capsys.disabled():
                    print("CLOSED FORM errors", c.cell, a, abs(v[("mean", a, c.cell)]-m), abs(v[("life", a, c.cell)]-var))
        errors = {k: abs(v[k] - doubled[k]) for k in v if k[0] in ("msw", "gate", "K")}
        if candidate == smooth:
            assert max(errors.values()) < 1000
        with capsys.disabled():
            print("QUADRATURE", candidate == smooth, "chosen seconds/cell", chosen_seconds, "chosen+doubled seconds/cell", (perf_counter()-started)/2, "errors", errors)
    interior = replace(smooth, rho_t=.5)
    started = perf_counter()
    v = f.model_values(interior, design(interior))
    chosen_seconds = (perf_counter() - started) / 2
    doubled = f.model_values(interior, design(interior), nodes=12, shared=10)
    errors = {k: abs(v[k]-doubled[k]) for k in v if k[0] in ("msw", "gate", "K")}
    assert max(errors.values()) < 1000
    with capsys.disabled():
        print("INTERIOR CORRELATION chosen seconds/cell", chosen_seconds, "errors", errors)


def test_c_chi():
    for k, value in ((1, 3.841459), (2, 5.991465), (10, 18.307038), (20, 31.410433)):
        assert abs(f.chi95(k) - value) < 1e-5


def test_d_f_card_determinism():
    p = params()
    rs = records(p, design(p, 6, 8))
    thresholds = {x: {"threshold": "100", "undefined": 0} for x in f.FAMILIES}
    def check(rows):
        return f.check(rows, p, timing_cells={"B"}, resamples=40, thresholds=thresholds)
    result = check(rs)
    shuffled = rs[:]
    random.Random(42).shuffle(shuffled)
    assert json.dumps(result) == json.dumps(check(rs)) == json.dumps(check(shuffled))
    def scalar_types(value):
        if isinstance(value, dict):
            return all(scalar_types(v) for v in value.values())
        if isinstance(value, list):
            return all(scalar_types(v) for v in value)
        return type(value) in (int, str)
    assert scalar_types(result)
    card = "\n".join(f.card_lines(result))
    assert "never changes a simulated verdict" in card and "for reference" in card
    assert "raw scores against the model's binned levels" in card
    assert "src/bicentennial/ocsim/fitcheck.py" in run.c8_paths(Path(__file__).resolve().parents[2])
    single = check([r for r in rs if r.life == "0"])
    assert all(x["flag"] == "cannot check" for x in single["families"])


def test_e_duplicate_life(monkeypatch):
    sums = {(a, "X", life): row for a in ("F", "C") for life, row in (("a", [2, 2, 4]), ("b", [2, 10, 52]))}
    got = f.statistics(sums, ["X"], ["a", "a", "b"], exact=True)
    assert got[("mean", "F", "X")] == Fraction(7, 3)
    assert got[("life", "F", "X")] == Fraction(13, 3)
    assert got[("gate", "F+C", "X")] == Fraction(16, 3)
    assert any(len(set(draw)) < 2 for draw in f.draws(("a", "b"), 5, f.UNIT))
    sums[("F", "X", "unused")] = [2, 6, 20]
    sums[("C", "X", "unused")] = [2, 6, 20]
    monkeypatch.setattr(f, "draws", lambda *args: (("a", "a", "b"), ("a", "b", "b")))
    se = f.bootstrap(sums, ["X"], ["a", "b", "unused"], 2)[("mean", "F", "X")]
    assert se == pytest.approx(math.sqrt(Fraction(8, 9)))


def test_j_mean_se():
    sums = {("F", "X", str(i)): [30, 30*i, 30*i*i] for i in range(16)}
    se = f.bootstrap(sums, ["X"], sorted(str(i) for i in range(16)), 2000)[("mean", "F", "X")]
    expected = math.sqrt(sum((i - 7.5)**2 for i in range(16))) / 16
    assert abs(se / expected - 1) < .05


def test_k_family_mean():
    assert f.family_stat([3, 0, 0, 0]) == 2.25
    assert f.family_stat([None, 0]) is None


@pytest.fixture(scope="module")
def calibrated():
    p = replace(params(), cells=(params().cells[0],))
    d = design(p)
    return p, d, f.calibrate(p, d, datasets=80, resamples=250)


def test_i_l_calibration(calibrated, monkeypatch, capsys):
    p, d, thresholds = calibrated
    values = f.model_values(p, d)
    flags, mean_stats = 0, []
    for rep in range(40):
        stats = f.evaluate(f.simulate(p, d, rep, prefix="fresh"), d, values, 250, ("ocsim", f"fresh-{rep}"))[3]
        flags += sum(v > float(thresholds[k]["threshold"]) for k, v in stats.items())
        mean_stats.append(stats["mean"])
    assert flags / 160 <= .12
    assert .7 <= mean(mean_stats) <= 1.5
    threshold = float(thresholds["life"]["threshold"])
    reference = f.chi95(2)/2
    assert threshold > reference
    original = f.evaluate
    def middle(*args, **kwargs):
        observed, ses, zs, stats = original(*args, **kwargs)
        stats["life"] = (threshold + reference)/2
        return observed, ses, zs, stats
    monkeypatch.setattr(f, "evaluate", middle)
    result = f.check(records(p, d), p, thresholds=thresholds, resamples=10)
    assert next(x for x in result["families"] if x["family"] == "life")["flag"] == "pass"
    with capsys.disabled():
        print("CALIBRATION", thresholds, "fresh flags", flags, "mean z2", mean(mean_stats))


def test_g_h_misfit(capsys):
    p = replace(params(), cells=(params().cells[0],))
    points, d = rule(p), design(p, 64, 30)
    thresholds = f.calibrate(p, d, datasets=60, resamples=100, rule=points)
    inflated = replace(p, cells=tuple(replace(c, sigma_f=c.sigma_f*3, sigma_c=c.sigma_c*3) for c in p.cells))
    rs = records(inflated, d, points=points)
    result = f.check(rs, p, rule=points, thresholds=thresholds, resamples=100)
    life = next(x for x in result["families"] if x["family"] == "life")
    assert life["flag"] == "flag" and life["mean_z2"] >= 2*life["threshold"]
    rng = random.Random(30)
    pool = [min(r.b0, r.b1) for r in rs]
    mixed = [replace(r, b0=(y := rng.choice(pool)), b1=y) if rng.random() < .5 else r for r in rs]
    result = f.check(mixed, p, rule=points, thresholds=thresholds, resamples=100)
    assert next(x for x in result["families"] if x["family"] == "msw")["flag"] == "flag"
    with capsys.disabled():
        print("MISFIT", life, result["families"])
