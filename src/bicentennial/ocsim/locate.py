"""Tabulated monotone inversion of the expected bundle minimum."""

import math
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass
from statistics import NormalDist

from bicentennial.ocsim import model

GRID_LOW, GRID_HIGH = -10.0, 10.0
STEP_EXP, MAX_STEP_EXP = 8, 12
BOUND_MILLI = 0.05


@dataclass(frozen=True)
class LocationTable:
    cell: str
    rho_t: float
    step_exp: int
    thetas: tuple[float, ...]
    values: tuple[float, ...]
    bound_milli: float
    max_correction: float


def interpolation_bound(cell: model.CellModel, rho_t: float, step_exp: int) -> float:
    """Bound the linear interpolation error in milli."""
    if not model._finite(rho_t) or not -1 <= rho_t <= 1:
        raise ValueError("rho_t out of range")
    if rho_t == -1:
        return math.inf
    c = math.sqrt((1 - rho_t) / (1 + rho_t))
    return ((cell.levels[-1] - cell.levels[0]) * 2.0**(-2 * step_exp) / 8
            * (2 * NormalDist().pdf(1.0) + c / math.pi))


def build_table(cell: model.CellModel, rho_t: float) -> LocationTable:
    """Tabulate the first grid meeting the bound, correcting downward noise."""
    for step_exp in range(STEP_EXP, MAX_STEP_EXP + 1):
        bound = interpolation_bound(cell, rho_t, step_exp)
        if bound <= BOUND_MILLI:
            break
    else:
        raise ValueError("location table: no grid step meets the bound; use the exact solver")
    h = 2.0**-step_exp
    thetas = tuple(GRID_LOW + j * h for j in range(20 * 2**step_exp + 1))
    values = []
    max_correction = 0.0
    for theta in thetas:
        computed = model.expected_min(cell, rho_t, theta)
        value = max(values[-1], computed) if values else computed
        max_correction = max(max_correction, value - computed)
        values.append(value)
    return LocationTable(cell.cell, rho_t, step_exp, thetas, tuple(values), bound,
                         max_correction)


def locate(table: LocationTable, cell: model.CellModel, target: float) -> float | str:
    """Invert the table with monotone IEEE operations and bracket clamping.

    For t1 < t2, bisect_left gives brackets q1 <= q2. In the same bracket,
    subtraction of a constant, division by a positive constant, multiplication
    by h > 0, addition of a constant and clamping are monotone in the target.
    In different brackets, theta_hat(t1) <= thetas[q1] <= thetas[q2 - 1]
    <= theta_hat(t2). The ends follow low < finite theta < high, with the
    +/-10 clamps outside every bracket. Fixed latents therefore give monotone
    item draws as the target increases.
    """
    if table.cell != cell.cell:
        raise ValueError(f"location table is for cell {table.cell}")
    if not model._finite(target):
        raise ValueError("targets must be finite")
    if len(cell.levels) == 1 or target >= cell.levels[-1]:
        return "high"
    if target <= cell.levels[0]:
        return "low"
    q = bisect_left(table.values, target)
    if q == 0:
        return table.thetas[0]
    if q == len(table.values):
        return table.thetas[-1]
    h = 2.0**-table.step_exp
    theta = table.thetas[q - 1] + h * (
        (target - table.values[q - 1]) / (table.values[q] - table.values[q - 1]))
    return min(table.thetas[q], max(table.thetas[q - 1], theta))


def table_solver(params: model.LatentParams) -> Callable[[model.CellModel, float], float | str]:
    """Build one table per cell and close over the twin correlation."""
    tables = {cell.cell: build_table(cell, params.rho_t) for cell in params.cells}

    def solve(cell, target):
        if cell.cell not in tables:
            raise KeyError(f"unknown cell: {cell.cell}")
        return locate(tables[cell.cell], cell, target)

    return solve


def midpoint_error(table: LocationTable, cell: model.CellModel) -> float:
    """Measure the largest interpolation residual at theta bracket midpoints."""
    if table.cell != cell.cell:
        raise ValueError(f"location table is for cell {table.cell}")
    return max(abs(model.expected_min(cell, table.rho_t, (lo + hi) / 2)
                   - (left + right) / 2)
               for lo, hi, left, right in zip(
                   table.thetas[:-1], table.thetas[1:],
                   table.values[:-1], table.values[1:], strict=True))
