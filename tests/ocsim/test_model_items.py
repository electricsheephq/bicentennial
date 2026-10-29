"""Item seams, frozen sampler compatibility and the margin clamp."""

import math
import random
from bisect import bisect_left
from dataclasses import replace
from functools import lru_cache
from statistics import NormalDist

import pytest

from bicentennial.keyed import draw
from bicentennial.ocsim import locate, model


@pytest.fixture(scope="module")
def params():
    timing = model.CellModel(
        "T", (-1000, -250, 0, 125, 375, 625, 875, 1000),
        (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5), -200.0, 600.0, 0.0, 0.0)
    action = model.CellModel("X", (-1000, 0, 1000), (-0.5, 0.5),
                             -200.0, 600.0, 0.0, 0.0)
    return model.LatentParams((timing, action), 0.25, 0.6, 0.3, 0.2)


@pytest.fixture(scope="module")
def solver(params):
    return locate.table_solver(params)


def old_bundles(params, targets, alloc, seed, rep, solver):
    """The valid-input sampler at 67d0502, independent of the item seams."""
    units = {}
    for (arm, pair, cell_id, ckpt), target in targets.items():
        units.setdefault((pair, cell_id, ckpt), {})[arm] = target
    rho_e = (params.rho_t - params.sigma_d2) / (1 - params.sigma_d2)
    rho_e = max(-1.0, min(1.0, rho_e))
    normal = NormalDist()

    def noise(rng):
        return normal.inv_cdf((rng.getrandbits(52) + 0.5) * 2.0**-52)

    result = {}
    for (pair, cell_id, ckpt), arm_targets in sorted(units.items()):
        cell = params.cell(cell_id)
        locations = {arm: (model.solve_location(cell, params.rho_t, target) if solver is None
                           else solver(cell, target)) for arm, target in arm_targets.items()}
        values = {arm: [] for arm in arm_targets}
        rng = random.Random(draw(seed, ("ocsim", "bundles", pair, cell_id, str(ckpt)),
                                 rep, "bundles"))
        for _ in range(alloc[(cell_id, ckpt)]):
            g = noise(rng)
            for arm in model.ARMS:
                e0, z1 = noise(rng), noise(rng)
                e1 = rho_e * e0 + math.sqrt(1 - rho_e * rho_e) * z1
                if arm not in locations:
                    continue
                theta = locations[arm]
                if theta == "low":
                    value = cell.levels[0]
                elif theta == "high":
                    value = cell.levels[-1]
                else:
                    item0 = cell.levels[bisect_left(
                        cell.cuts, theta + (math.sqrt(params.sigma_d2) * g
                                           + math.sqrt(1 - params.sigma_d2) * e0))]
                    item1 = cell.levels[bisect_left(
                        cell.cuts, theta + (math.sqrt(params.sigma_d2) * g
                                           + math.sqrt(1 - params.sigma_d2) * e1))]
                    value = min(item0, item1)
                values[arm].append(value)
        for arm, scores in values.items():
            result[(arm, pair, cell_id, ckpt)] = tuple(scores)
    return result


def test_equivalence_with_frozen_sampler(params, solver, monkeypatch):
    # Cache repeated exact inversions, keeping the solver=None dispatch exercised.
    monkeypatch.setattr(model, "solve_location", lru_cache(None)(model.solve_location))
    pairs = ("pair-000", "pair-001", "pair-002")
    alloc = {("T", 2): 3, ("T", 3): 0, ("X", 2): 2, ("X", 3): 4}
    keys = [(arm, pair, cell, ckpt)
            for pair in pairs for cell, ckpt in alloc for arm in model.ARMS]
    values = (-1000, -400.0, 0.0, 950.0, 1000)
    targets = {key: values[i % len(values)] for i, key in enumerate(keys)}
    for solve in (None, solver):
        for seed in ("a", "b"):
            for rep in range(5):
                items = model.sample_items(params, targets, alloc, pairs, seed, rep, solver=solve)
                bundles = model.sample_bundles(
                    params, targets, alloc, pairs, seed, rep, solver=solve)
                expected = old_bundles(params, targets, alloc, seed, rep, solve)
                assert list(items) == list(bundles) == list(expected)
                assert {key: tuple(min(p) for p in v) for key, v in items.items()} == expected
                assert bundles == expected
                only_s = {key: value for key, value in targets.items() if key[0] == "S"}
                subset = model.sample_items(
                    params, only_s, alloc, pairs, seed, rep, solver=solve)
                assert subset == {key: value for key, value in items.items() if key[0] == "S"}
                assert model.sample_bundles(
                    params, only_s, alloc, pairs, seed, rep, solver=solve
                ) == old_bundles(params, only_s, alloc, seed, rep, solve)


def test_twins(params):
    params = replace(params, rho_t=1.0, sigma_d2=0.0)
    targets = {(arm, "p", "X", 2): 0.0 for arm in model.ARMS}
    items = model.sample_items(params, targets, {("X", 2): 30}, ("p",), "a", 0)
    assert all(x0 == x1 for values in items.values() for x0, x1 in values)


@pytest.mark.parametrize("target,expected", [(-1001.0, -1000), (-1000.0, -1000),
                                            (1000.0, 1000), (1001.0, 1000)])
def test_point_masses(params, target, expected):
    items = model.sample_items(params, {("S", "p", "X", 2): target},
                               {("X", 2): 3}, ("p",), "a", 0)
    assert items == {("S", "p", "X", 2): ((expected, expected),) * 3}


def test_latent_prefix_determinism_and_units(params):
    small = model.bundle_latents(params, {("X", 2): 2}, ("p",), "a", 0)
    large = model.bundle_latents(params, {("X", 2): 5}, ("p",), "a", 0)
    assert small == model.bundle_latents(params, {("X", 2): 2}, ("p",), "a", 0)
    for arm in model.ARMS:
        assert small[("p", "X", 2)][arm] == large[("p", "X", 2)][arm][:2]
    alloc = {("X", 3): 0, ("T", 2): 1, ("X", 2): 2}
    all_units = model.bundle_latents(params, alloc, ("q", "p"), "a", 0)
    assert list(all_units) == sorted((p, k, c) for p in ("q", "p") for k, c in alloc)
    selected = [("q", "X", 3), ("p", "X", 2)]
    subset = model.bundle_latents(params, alloc, ("q", "p"), "a", 0,
                                   units=iter(selected))
    assert list(subset) == sorted(selected)
    assert subset == {key: all_units[key] for key in sorted(selected)}
    assert subset[("q", "X", 3)] == {arm: () for arm in model.ARMS}
    assert model.bundle_latents(params, alloc, ("p",), "a", 0, units=[]) == {}
    assert model.sample_items(params, {}, {}, (), "a", 0) == {}


def test_latent_stream_and_draw_order(params, monkeypatch):
    params = replace(params, rho_t=0.0, sigma_d2=0.0)
    calls = []
    normals = iter(float(i) for i in range(1, 15))

    def rng(seed, unit, rep, name):
        calls.append((seed, unit, rep, name))
        return None

    monkeypatch.setattr(model, "_rng", rng)
    monkeypatch.setattr(model, "_normal", lambda rng: next(normals))
    latents = model.bundle_latents(params, {("X", 2): 2}, ("p",), "seed", 7)
    assert calls == [("seed", ("ocsim", "bundles", "p", "X", "2"), 7, "bundles")]
    assert latents == {("p", "X", 2): {
        "F": ((2.0, 3.0), (9.0, 10.0)),
        "C": ((4.0, 5.0), (11.0, 12.0)),
        "S": ((6.0, 7.0), (13.0, 14.0))}}


@pytest.mark.parametrize("eta0,eta1,expected", [(0.7, -0.2, (1000, 0)),
                                               (-0.6, 0.9, (-1000, 1000)),
                                               (0.1, 0.2, (0, 0)),
                                               (-0.5, 0.5, (-1000, 0))])
def test_hand_item_rule(params, eta0, eta1, expected):
    assert model.item_pair(params.cell("X"), 0.0, eta0, eta1) == expected


@pytest.mark.parametrize("theta,expected", [("low", (-1000, -1000)),
                                           ("high", (1000, 1000))])
def test_item_pair_ends(params, theta, expected):
    assert model.item_pair(params.cell("X"), theta, 0.7, -0.2) == expected


@pytest.mark.parametrize("key", [("q", "X", 2), ("p", "Y", 2), ("p", "X", 3),
                                 ("p", "X", True), ("p", "X"), "p"])
def test_invalid_units(params, key):
    with pytest.raises(ValueError) as exc:
        model.bundle_latents(params, {("X", 2): 1}, ("p",), "a", 0, units=[key])
    assert str(exc.value) == f"bad alloc or target key: {key}"


@pytest.mark.parametrize("theta", [float("nan"), float("inf"), -float("inf"), "bad", None])
def test_invalid_theta(params, theta):
    with pytest.raises(ValueError) as exc:
        model.item_pair(params.cell("X"), theta, 0.0, 0.0)
    assert str(exc.value) == 'theta must be a finite float, "low" or "high"'


@pytest.mark.parametrize("sampler", [model.sample_items, model.sample_bundles])
@pytest.mark.parametrize("targets,alloc,pairs,message", [
    ({("bad", "p", "X", 2): float("nan")}, {("X", 2): True}, ("p", "p"),
     "pairs must be unique strings"),
    ({("bad", "p", "X", 2): float("nan")}, {("X", 2): True}, ("p",),
     "bad alloc or target key: ('X', 2)"),
    ({("bad", "p", "X", 2): float("nan")}, {("X", 2): 1}, ("p",),
     "bad alloc or target key: ('bad', 'p', 'X', 2)"),
    ({("S", "p", "X", 2): float("nan"), ("bad", "p", "X", 2): 0.0},
     {("X", 2): 1}, ("p",), "targets must be finite"),
])
def test_shared_validation_order(params, sampler, targets, alloc, pairs, message):
    with pytest.raises(ValueError) as exc:
        sampler(params, targets, alloc, pairs, "a", 0)
    assert str(exc.value) == message


@pytest.mark.parametrize("rho_t,sigma_d2", [(-1.0, 0.0), (0.98, 0.99), (1.0, 0.99)])
def test_frozen_sampler_at_feasible_boundaries(params, rho_t, sigma_d2):
    params = replace(params, rho_t=rho_t, sigma_d2=sigma_d2)
    targets = {(arm, "p", "X", 2): 0.0 for arm in model.ARMS}
    alloc = {("X", 2): 5}
    def solve(cell, target):
        return 0.0

    assert model.sample_bundles(params, targets, alloc, ("p",), "a", 0, solver=solve
                                ) == old_bundles(params, targets, alloc, "a", 0, solve)


def test_table_solver_preserves_item_coupling(params, solver):
    low = {("S", "p", "X", 2): -300.0}
    high = {("S", "p", "X", 2): 200.0}
    args = ({("X", 2): 100}, ("p",), "a", 0)
    first = model.sample_items(params, low, *args, solver=solver)
    second = model.sample_items(params, high, *args, solver=solver)
    for earlier, later in zip(first[("S", "p", "X", 2)],
                              second[("S", "p", "X", 2)], strict=True):
        assert all(x <= y for x, y in zip(earlier, later, strict=True))


def test_margin_clamp_at_gap_floor(params):
    cell = replace(params.cell("X"), f0=100.0 + 2**-43, c0=400.0)
    assert 0.5 + 150 / (cell.c0 - cell.f0) > 1.0
    assert model.interpolation(cell, 15) == 1.0
    with pytest.raises(ValueError) as exc:
        model.interpolation(cell, 16)
    assert str(exc.value) == "cell X: margin gives lambda outside [0, 1]"


@pytest.mark.parametrize("margin,expected", [(-40.0 - 1e-11, 0.0),
                                            (40.0 + 1e-11, 1.0)])
def test_margin_clamp_both_ends(params, margin, expected):
    assert model.interpolation(params.cell("X"), margin) == expected


@pytest.mark.parametrize("margin", [-40.0 - 1e-8, 40.0 + 1e-8, float("nan")])
def test_margin_beyond_clamp_raises(params, margin):
    with pytest.raises(ValueError) as exc:
        model.interpolation(params.cell("X"), margin)
    assert str(exc.value) == "cell X: margin gives lambda outside [0, 1]"
