"""Hand nodes, monotonicity and bounded error for tabulated locations."""

import math
from dataclasses import FrozenInstanceError, fields, replace
from statistics import NormalDist

import pytest

from bicentennial.ocsim import locate, model

RHOS = (-0.5, 0.0, 0.5, 0.9)


@pytest.fixture(scope="module")
def cells():
    return {
        "S2": model.CellModel("S2", (-1000, 1000), (0.0,), -200.0, 600.0, 0.0, 0.0),
        "X": model.CellModel("X", (-1000, 0, 1000), (-0.5, 0.5),
                             -200.0, 600.0, 0.0, 0.0),
    }


@pytest.fixture(scope="module")
def tables(cells):
    return {(name, rho): locate.build_table(cell, rho)
            for name, cell in cells.items() for rho in RHOS}


def test_exact_origin_node(cells, tables):
    cell = cells["S2"]
    table = tables[("S2", 0.0)]
    assert model.expected_min(cell, 0.0, 0.0) == -500.0
    assert table.thetas[2560] == 0.0
    assert table.values[2560] == -500.0
    assert locate.locate(table, cell, -500.0) == 0.0
    assert abs(model.solve_location(cell, 0.0, -500.0)) < 1e-12


@pytest.mark.parametrize("j,theta", [(2000, -2.1875), (2560, 0.0), (3000, 1.71875)])
def test_node_value_returns_node(cells, tables, j, theta):
    table = tables[("S2", 0.5)]
    assert table.thetas[j] == theta
    assert table.values[j - 1] < table.values[j]
    assert locate.locate(table, cells["S2"], table.values[j]) == theta


def test_frozen_api_grid_and_fields(tables):
    assert (locate.GRID_LOW, locate.GRID_HIGH) == (-10.0, 10.0)
    assert locate.GRID_HIGH == model.LOCATION_BOUND
    assert (locate.STEP_EXP, locate.MAX_STEP_EXP, locate.BOUND_MILLI) == (8, 12, 0.05)
    table = tables[("X", 0.5)]
    assert tuple(field.name for field in fields(table)) == (
        "cell", "rho_t", "step_exp", "thetas", "values", "bound_milli", "max_correction")
    assert table.cell == "X"
    assert table.rho_t == 0.5
    assert table.step_exp == 8
    assert len(table.thetas) == len(table.values) == 5121
    assert table.thetas == tuple(-10.0 + j / 256 for j in range(5121))
    assert table.bound_milli == locate.interpolation_bound(
        model.CellModel("X", (-1000, 0, 1000), (-0.5, 0.5), -200, 600, 0, 0), 0.5, 8)
    assert table.max_correction >= 0.0
    with pytest.raises(FrozenInstanceError):
        table.step_exp = 9


@pytest.mark.parametrize("name", ["S2", "X"])
def test_ends_and_single_level(cells, tables, name):
    cell = cells[name]
    table = tables[(name, 0.5)]
    for target, expected in ((-1001.0, "low"), (-1000.0, "low"),
                              (1000.0, "high"), (1001.0, "high")):
        assert locate.locate(table, cell, target) == expected
        assert model.solve_location(cell, 0.5, target) == expected
    single = replace(cell, levels=(125,), cuts=())
    single_table = locate.build_table(single, 0.5)
    for target in (-1000.0, 125.0, 1000.0):
        assert locate.locate(single_table, single, target) == "high"
        assert model.solve_location(single, 0.5, target) == "high"


@pytest.mark.parametrize("rho", RHOS)
def test_monotone_targets(cells, tables, rho):
    table = tables[("X", rho)]
    targets = [-999.5 + 1999 * j / 2000 for j in range(2001)]
    locations = [locate.locate(table, cells["X"], t) for t in targets]
    assert all(type(theta) is float for theta in locations)
    assert locations == sorted(locations)
    assert all(a <= b for a, b in zip(table.values[:-1], table.values[1:], strict=True))
    for j in (2000, 2560, 3000):
        target = table.values[j]
        adjacent = [math.nextafter(target, -math.inf), target,
                    math.nextafter(target, math.inf)]
        answers = [locate.locate(table, cells["X"], t) for t in adjacent]
        assert answers == sorted(answers)


@pytest.mark.parametrize("name", ["S2", "X"])
@pytest.mark.parametrize("rho", RHOS)
def test_accuracy_against_exact_solver(cells, tables, name, rho):
    cell = cells[name]
    table = tables[(name, rho)]
    normal = NormalDist()
    c = math.sqrt((1 - rho) / (1 + rho))
    for j in range(201):
        target = -999.5 + 1999 * j / 200
        theta = locate.locate(table, cell, target)
        assert type(theta) is float
        residual = abs(model.expected_min(cell, rho, theta) - target)
        assert residual <= table.bound_milli + table.max_correction + 1e-6
        exact = model.solve_location(cell, rho, target)
        slope = sum((hi - lo) * 2 * normal.pdf(theta - cut) * normal.cdf(c * (theta - cut))
                    for lo, hi, cut in zip(cell.levels[:-1], cell.levels[1:],
                                           cell.cuts, strict=True))
        if slope > 10:
            assert abs(theta - exact) <= 1e-3


@pytest.mark.parametrize("rho,c", [(0.0, 1.0), (0.5, 1 / math.sqrt(3)),
                                   (-0.9, math.sqrt(19)), (-0.999, math.sqrt(1999))])
def test_bound_arithmetic(cells, rho, c):
    expected = 2000 * (2 * NormalDist().pdf(1.0) + c / math.pi) / 524288
    assert locate.interpolation_bound(cells["X"], rho, 8) == pytest.approx(
        expected, abs=1e-15, rel=0)
    assert locate.interpolation_bound(cells["X"], rho, 9) == pytest.approx(
        expected / 4, abs=1e-15, rel=0)


def test_refines_to_first_step_meeting_bound(cells):
    cell = cells["X"]
    assert locate.interpolation_bound(cell, -0.999, 8) > locate.BOUND_MILLI
    table = locate.build_table(cell, -0.999)
    assert table.step_exp == 9
    assert len(table.thetas) == 10241
    assert table.bound_milli <= locate.BOUND_MILLI
    assert table.bound_milli == locate.interpolation_bound(cell, -0.999, 9)


def test_running_max_exact_dip(cells, monkeypatch):
    thetas = tuple(-10.0 + j / 256 for j in range(5121))

    def synthetic(cell, rho_t, theta):
        return thetas[2559] - 1e-9 if theta == thetas[2560] else theta

    monkeypatch.setattr(model, "expected_min", synthetic)
    table = locate.build_table(cells["X"], 0.0)
    assert table.thetas == thetas
    assert all(a <= b for a, b in zip(table.values[:-1], table.values[1:], strict=True))
    assert table.values[2560] == table.values[2559]
    assert table.max_correction == pytest.approx(1e-9, abs=1e-15, rel=0)


@pytest.mark.parametrize("rho", [-1.01, 1.01, float("nan"), float("inf"), -float("inf")])
def test_invalid_rho(cells, rho):
    for function, args in ((locate.interpolation_bound, (cells["X"], rho, 8)),
                            (locate.build_table, (cells["X"], rho))):
        with pytest.raises(ValueError) as exc:
            function(*args)
        assert str(exc.value) == "rho_t out of range"


@pytest.mark.parametrize("rho", [-1.0, math.nextafter(-1.0, 0.0)])
def test_no_grid_step_meets_bound(cells, rho):
    with pytest.raises(ValueError) as exc:
        locate.build_table(cells["X"], rho)
    assert str(exc.value) == "location table: no grid step meets the bound; use the exact solver"
    assert locate.interpolation_bound(cells["X"], -1.0, 12) == math.inf


def test_wrong_cell(cells, tables):
    table = tables[("X", 0.0)]
    with pytest.raises(ValueError) as exc:
        locate.locate(table, cells["S2"], 0.0)
    assert str(exc.value) == "location table is for cell X"
    with pytest.raises(ValueError) as exc:
        locate.midpoint_error(table, cells["S2"])
    assert str(exc.value) == "location table is for cell X"


@pytest.mark.parametrize("target", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_target(cells, tables, target):
    with pytest.raises(ValueError) as exc:
        locate.locate(tables[("X", 0.0)], cells["X"], target)
    assert str(exc.value) == "targets must be finite"


def test_clamps_and_leftmost_plateau(cells):
    table = locate.LocationTable("X", 0.0, 8, (-1 / 256, 0.0, 1 / 256, 2 / 256),
                                 (-10.0, 0.0, 0.0, 10.0), 0.0, 0.0)
    assert locate.locate(table, cells["X"], -10.005) == -1 / 256
    assert locate.locate(table, cells["X"], 10.005) == 2 / 256
    for target in (-20.0, 20.0):
        with pytest.raises(ValueError) as exc:
            locate.locate(table, cells["X"], target)
        assert str(exc.value) == "location bracket [-10, 10] does not enclose the target"
    assert locate.locate(table, cells["X"], 0.0) == 0.0
    assert locate.locate(table, cells["X"], -5.0) == -1 / 512
    assert locate.locate(table, cells["X"], 5.0) == 3 / 512


@pytest.mark.parametrize("cut", [12.0, -12.0])
def test_bracket_miss_raises_like_the_exact_solver(cut):
    # A cut beyond the grid leaves target 0 outside every table value, by about 999 or 910 milli.
    cell = model.CellModel("X", (-1000, 1000), (cut,), -200.0, 600.0, 0.0, 0.0)
    table = locate.build_table(cell, 0.0)
    assert min(abs(table.values[0]), abs(table.values[-1])) > 900
    message = "location bracket [-10, 10] does not enclose the target"
    for solve in (locate.table_solver(model.LatentParams((cell,), 0.0, 0.0, 0.0, 0.0)),
                  lambda c, t: model.solve_location(c, 0.0, t)):
        with pytest.raises(ValueError) as exc:
            solve(cell, 0.0)
        assert str(exc.value) == message


def test_bracket_miss_within_tolerance_clamps_like_the_exact_solver():
    # E(10) is about 1000 - 5.7e-4, so a target 1e-4 below the top misses by less than the tolerance.
    cell = model.CellModel("Y", (-1000, 0, 1000), (-5.0, 5.0), -200.0, 600.0, 0.0, 0.0)
    table = locate.build_table(cell, 0.0)
    target = 1000 - 1e-4
    assert target - model.BRACKET_TOL_MILLI < table.values[-1] < target
    assert locate.locate(table, cell, target) == table.thetas[-1] == 10.0
    assert model.solve_location(cell, 0.0, target) == pytest.approx(10.0, abs=1e-9)


def test_table_solver_builds_once_per_cell(cells, tables, monkeypatch):
    calls = []

    def build(cell, rho_t):
        calls.append((cell.cell, rho_t))
        return tables[(cell.cell, rho_t)]

    monkeypatch.setattr(locate, "build_table", build)
    params = model.LatentParams(tuple(cells.values()), 0.0, 0.0, 0.5, 0.0)
    solver = locate.table_solver(params)
    assert calls == [("S2", 0.5), ("X", 0.5)]
    for cell in cells.values():
        for target in (-500.0, 0.0, 500.0):
            assert solver(cell, target) == locate.locate(tables[(cell.cell, 0.5)], cell, target)
    assert calls == [("S2", 0.5), ("X", 0.5)]
    with pytest.raises(KeyError) as exc:
        solver(replace(cells["X"], cell="Y"), 0.0)
    assert exc.value.args == ("unknown cell: Y",)


def test_midpoint_error_definition(cells, tables):
    table = tables[("S2", 0.0)]
    expected = max(abs(model.expected_min(cells["S2"], 0.0, (lo + hi) / 2)
                       - (left + right) / 2)
                   for lo, hi, left, right in zip(
                       table.thetas[:-1], table.thetas[1:],
                       table.values[:-1], table.values[1:], strict=True))
    assert locate.midpoint_error(table, cells["S2"]) == expected
    assert expected <= table.bound_milli + table.max_correction + 1e-6
