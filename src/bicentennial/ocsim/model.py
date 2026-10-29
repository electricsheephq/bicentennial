"""Two-layer bundle model with keyed life effects and ordered-probit twins."""

import math
import random
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from statistics import NormalDist

from bicentennial.keyed import draw

ARMS = ("F", "C", "S")
SIMPSON_INTERVALS = 128
BISECTION_STEPS = 64
LOCATION_BOUND = 10.0
_NORMAL = NormalDist()


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


@dataclass(frozen=True)
class CellModel:
    cell: str
    levels: tuple[int, ...]
    cuts: tuple[float, ...]
    f0: float
    c0: float
    sigma_f: float
    sigma_c: float

    def __post_init__(self):
        if (not self.levels
                or any(type(v) is not int or not -1000 <= v <= 1000 for v in self.levels)
                or any(a >= b for a, b in zip(self.levels[:-1], self.levels[1:], strict=True))):
            raise ValueError("levels must be strictly increasing ints in [-1000, 1000]")
        if (len(self.cuts) != len(self.levels) - 1
                or any(not _finite(v) for v in self.cuts)
                or any(a >= b for a, b in zip(self.cuts[:-1], self.cuts[1:], strict=True))):
            raise ValueError("cuts must be len(levels)-1 strictly increasing finite floats")
        if (not all(_finite(v) for v in (self.f0, self.c0, self.sigma_f, self.sigma_c))
                or self.f0 >= self.c0 or self.sigma_f < 0 or self.sigma_c < 0):
            raise ValueError(f"cell {self.cell}: need finite f0 < c0 and sigma >= 0")


@dataclass(frozen=True)
class LatentParams:
    cells: tuple[CellModel, ...]
    rho_x: float
    rho_a: float
    rho_t: float
    sigma_d2: float
    sigma_r2: float | None = None

    def __post_init__(self):
        ids = [cell.cell for cell in self.cells]
        if (not ids or any(not isinstance(cell, str) for cell in ids)
                or ids != sorted(set(ids))):
            raise ValueError("cells must be nonempty, unique and sorted")
        for field, low, high in (("rho_x", 0, 0.95), ("rho_a", -0.95, 0.95),
                                 ("rho_t", -1, 1), ("sigma_d2", 0, 0.99)):
            value = getattr(self, field)
            if not _finite(value) or not low <= value <= high:
                raise ValueError(f"{field} out of range")
        if self.rho_t < 2 * self.sigma_d2 - 1:
            raise ValueError("rho_t must be >= 2*sigma_d2 - 1")
        if self.sigma_r2 is not None and (
                not _finite(self.sigma_r2) or not 0 <= self.sigma_r2 <= 1 - self.sigma_d2):
            raise ValueError("sigma_r2 out of range")

    def cell(self, cell_id: str) -> CellModel:
        for cell in self.cells:
            if cell.cell == cell_id:
                return cell
        raise KeyError(f"unknown cell: {cell_id}")


@dataclass(frozen=True)
class LifeEffects:
    x: Mapping[tuple[str, str, str], float]


def phi2(h: float, k: float, rho: float) -> float:
    if rho == 1:
        return _NORMAL.cdf(min(h, k))
    if rho == -1:
        return max(0.0, _NORMAL.cdf(h) + _NORMAL.cdf(k) - 1)
    product = _NORMAL.cdf(h) * _NORMAL.cdf(k)
    if rho == 0:
        return product
    step = math.asin(rho) / SIMPSON_INTERVALS

    def integrand(t):
        numerator = max(0.0, h * h + k * k - 2 * h * k * math.sin(t))
        return math.exp(-numerator / (2 * math.cos(t) ** 2))

    total = integrand(0.0) + integrand(math.asin(rho))
    for i in range(1, SIMPSON_INTERVALS):
        total += (4 if i % 2 else 2) * integrand(i * step)
    value = product + step * total / (6 * math.pi)
    # The end panel can overshoot within about 1e-4 of |rho| = 1; the Frechet bounds are exact.
    return min(_NORMAL.cdf(min(h, k)), max(0.0, _NORMAL.cdf(h) + _NORMAL.cdf(k) - 1, value))


def expected_min(cell: CellModel, rho_t: float, theta: float) -> float:
    value = float(cell.levels[0])
    for low, high, cut in zip(cell.levels[:-1], cell.levels[1:], cell.cuts, strict=True):
        value += (high - low) * phi2(theta - cut, theta - cut, rho_t)
    return value


def solve_location(cell: CellModel, rho_t: float, target: float) -> float | str:
    """Invert the expected minimum with a frozen, monotone bisection.

    For targets t1 < t2, both runs compare against the same mid points until
    the first step where t1 <= E(mid) < t2. There t1 moves left and t2 moves
    right, so theta_hat(t1) <= theta_hat(t2). The map from target to theta_hat
    is therefore monotone even if float rounding perturbs E, and it is
    bit-reproducible on one platform (R8: the platform is recorded).
    Accuracy is |E(theta_hat) - target| <= max slope * 20 * 2**-64, which is
    negligible. Clamping at +/-10 only affects targets within about 1e-20
    milli of an end.
    """
    if len(cell.levels) == 1 or target >= cell.levels[-1]:
        return "high"
    if target <= cell.levels[0]:
        return "low"
    lo, hi = -LOCATION_BOUND, LOCATION_BOUND
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2
        if expected_min(cell, rho_t, mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def interpolation(cell: CellModel, margin: int | Fraction) -> float:
    lam = 0.5 + 10 * margin / (cell.c0 - cell.f0)
    if not 0 <= lam <= 1:
        raise ValueError(f"cell {cell.cell}: margin gives lambda outside [0, 1]")
    return float(lam)


def default_tau(cell: CellModel, rho_a: float, lam: float) -> float:
    variance = ((1 - lam) ** 2 * cell.sigma_f ** 2 + lam ** 2 * cell.sigma_c ** 2
                + 2 * lam * (1 - lam) * rho_a * cell.sigma_f * cell.sigma_c)
    return math.sqrt(max(0.0, max(cell.sigma_f ** 2, cell.sigma_c ** 2) - variance))


def _rng(seed, unit, rep, name):
    return random.Random(draw(seed, unit, rep, name))


def _normal(rng):
    return _NORMAL.inv_cdf((rng.getrandbits(52) + 0.5) * 2.0**-52)


def _corr_pair(z1, z2, rho):
    return z1, rho * z1 + math.sqrt(1 - rho * rho) * z2


def _equicorr(g, h, rho):
    return math.sqrt(rho) * g + math.sqrt(1 - rho) * h


def _validate_pairs(pairs):
    if any(not isinstance(pair, str) for pair in pairs) or len(set(pairs)) != len(pairs):
        raise ValueError("pairs must be unique strings")


def life_effects(params: LatentParams, pairs: Sequence[str], seed: str, rep: int) -> LifeEffects:
    _validate_pairs(pairs)
    effects = {}
    for pair in pairs:
        rng = _rng(seed, ("ocsim", "life", pair), rep, "life")
        gf, gc = _corr_pair(_normal(rng), _normal(rng), params.rho_a)
        s = _normal(rng)
        for cell in params.cells:
            hf, hc = _corr_pair(_normal(rng), _normal(rng), params.rho_a)
            sk = _normal(rng)
            effects[("F", pair, cell.cell)] = _equicorr(gf, hf, params.rho_x)
            effects[("C", pair, cell.cell)] = _equicorr(gc, hc, params.rho_x)
            effects[("S", pair, cell.cell)] = _equicorr(s, sk, params.rho_x)
    return LifeEffects(effects)


def expected_units(
    params: LatentParams, effects: LifeEffects, margins: Mapping[str, int | Fraction], *,
    tau: Mapping[str, float] | None = None,
) -> dict[tuple[str, str, str], float]:
    if set(margins) != {cell.cell for cell in params.cells}:
        raise ValueError("margins must name every cell exactly")
    result = {}
    pairs = sorted({pair for _, pair, _ in effects.x})
    for cell in params.cells:
        lam = interpolation(cell, margins[cell.cell])
        sd = default_tau(cell, params.rho_a, lam) if tau is None else tau[cell.cell]
        for pair in pairs:
            floor = cell.f0 + cell.sigma_f * effects.x[("F", pair, cell.cell)]
            ceiling = cell.c0 + cell.sigma_c * effects.x[("C", pair, cell.cell)]
            system = floor + lam * (ceiling - floor) + sd * effects.x[("S", pair, cell.cell)]
            for arm, value in zip(ARMS, (floor, ceiling, system), strict=True):
                result[(arm, pair, cell.cell)] = float(max(-1000, min(1000, value)))
    return result


def sample_bundles(
    params: LatentParams, targets: Mapping[tuple[str, str, str, int], float],
    alloc: Mapping[tuple[str, int], int], pairs: Sequence[str], seed: str, rep: int, *,
    solver: Callable[[CellModel, float], float | str] | None = None,
) -> dict[tuple[str, str, str, int], tuple[int, ...]]:
    _validate_pairs(pairs)
    cells = {cell.cell: cell for cell in params.cells}
    for key, count in alloc.items():
        if (not isinstance(key, tuple) or len(key) != 2 or key[0] not in cells
                or type(key[1]) is not int or type(count) is not int or count < 0):
            raise ValueError(f"bad alloc or target key: {key}")
    units = {}
    for key, target in targets.items():
        if (not isinstance(key, tuple) or len(key) != 4 or key[0] not in ARMS
                or key[1] not in pairs or key[2] not in cells or type(key[3]) is not int
                or (key[2], key[3]) not in alloc):
            raise ValueError(f"bad alloc or target key: {key}")
        if not _finite(target):
            raise ValueError("targets must be finite")
        arm, pair, cell_id, ckpt = key
        units.setdefault((pair, cell_id, ckpt), {})[arm] = target
    result = {}
    rho_e = (params.rho_t - params.sigma_d2) / (1 - params.sigma_d2)
    # Feasible boundary parameters can round a few ulps outside [-1, 1].
    rho_e = max(-1.0, min(1.0, rho_e))
    for (pair, cell_id, ckpt), arm_targets in sorted(units.items()):
        cell = cells[cell_id]
        locations = {arm: (solve_location(cell, params.rho_t, target) if solver is None
                           else solver(cell, target)) for arm, target in arm_targets.items()}
        values = {arm: [] for arm in arm_targets}
        rng = _rng(seed, ("ocsim", "bundles", pair, cell_id, str(ckpt)), rep, "bundles")
        for _ in range(alloc[(cell_id, ckpt)]):
            g = _normal(rng)
            for arm in ARMS:
                e0, e1 = _corr_pair(_normal(rng), _normal(rng), rho_e)
                if arm not in locations:
                    continue
                theta = locations[arm]
                if theta == "low":
                    value = cell.levels[0]
                elif theta == "high":
                    value = cell.levels[-1]
                else:
                    item0 = cell.levels[bisect_left(
                        cell.cuts, theta + _equicorr(g, e0, params.sigma_d2))]
                    item1 = cell.levels[bisect_left(
                        cell.cuts, theta + _equicorr(g, e1, params.sigma_d2))]
                    value = min(item0, item1)
                values[arm].append(value)
        for arm, scores in values.items():
            result[(arm, pair, cell_id, ckpt)] = tuple(scores)
    return result


def cell_scores(
    bundles: Mapping[tuple[str, str, str, int], tuple[int, ...]],
) -> dict[tuple[str, str, str], Fraction]:
    totals, counts = {}, {}
    for (arm, pair, cell, _), values in bundles.items():
        key = (arm, pair, cell)
        totals[key] = totals.get(key, 0) + sum(values)
        counts[key] = counts.get(key, 0) + len(values)
    return {key: Fraction(total, 10 * counts[key]) for key, total in totals.items() if counts[key]}
