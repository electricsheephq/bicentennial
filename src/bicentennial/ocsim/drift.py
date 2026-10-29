"""Expected-score drift with exact schedule times and explicit unit scopes."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

DAY_MS = 86_400_000
ARMS = ("F", "C", "S")


@dataclass(frozen=True)
class DriftCase:
    name: str
    kind: str
    sign: int = 0
    phase: int = 0

    def __post_init__(self):
        if self.kind not in ("none", "step", "trend", "cycle"):
            raise ValueError("unknown drift case")
        if (self.kind in ("step", "trend") and (
                type(self.sign) is not int or self.sign not in (1, -1))
                or self.kind == "cycle" and (
                    type(self.phase) is not int or self.phase not in (0, 1, 2, 3)
                    or self.sign != 0)
                or self.kind == "none" and (self.sign != 0 or self.phase != 0)):
            raise ValueError("bad drift case parameters")


DRIFT_CASES = (
    DriftCase("none", "none"),
    DriftCase("step+5", "step", 1),
    DriftCase("step-5", "step", -1),
    DriftCase("trend+5", "trend", 1),
    DriftCase("trend-5", "trend", -1),
    DriftCase("cycle0", "cycle", 0, 0),
    DriftCase("cycle90", "cycle", 0, 1),
    DriftCase("cycle180", "cycle", 0, 2),
    DriftCase("cycle270", "cycle", 0, 3),
)


@dataclass(frozen=True)
class DriftScope:
    drifts: frozenset[tuple[str, bool]]

    def __post_init__(self):
        if (not isinstance(self.drifts, frozenset)
                or any(not isinstance(item, tuple) or len(item) != 2
                       or item[0] not in ARMS or type(item[1]) is not bool
                       for item in self.drifts)):
            raise ValueError("drift scope must hold (arm, post_swap) pairs with arm in F, C, S")


LITERAL = DriftScope(frozenset({
    ("F", False), ("F", True), ("C", False), ("C", True), ("S", False),
}))
ALL_UNITS = DriftScope(frozenset({(a, p) for a in ARMS for p in (False, True)}))
SWAP_GATE = DriftScope(frozenset({("F", False), ("C", False), ("S", False)}))


def _validate_bounds(t1_ms, step_start_ms):
    if type(t1_ms) is not int or t1_ms <= 0:
        raise ValueError("t1 must be a positive int")
    if type(step_start_ms) is not int or step_start_ms < 0:
        raise ValueError("step start must be an int >= 0")


def drift_points(
    case: DriftCase, t_ms: int | Fraction, *, t1_ms: int, step_start_ms: int,
) -> Fraction | float:
    if (not (type(t_ms) is int or isinstance(t_ms, Fraction)) or t_ms < 0):
        raise ValueError("drift time must be an int or Fraction >= 0")
    _validate_bounds(t1_ms, step_start_ms)
    t = Fraction(t_ms)
    if case.kind == "none":
        return Fraction(0)
    if case.kind == "step":
        return Fraction(5 * case.sign if t >= step_start_ms else 0)
    if case.kind == "trend":
        return 5 * case.sign * min(Fraction(1), t / t1_ms)
    u = t / DAY_MS + Fraction(case.phase, 4)
    f = u - u.numerator // u.denominator
    quarter = 4 * f
    if quarter.denominator == 1:
        return 3.0 * (0.0, 1.0, 0.0, -1.0)[quarter.numerator]
    return 3.0 * math.sin(math.tau * float(f))


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def drifted_targets(
    floor_ceiling: Mapping[str, tuple[float, float]],
    expected: Mapping[tuple[str, str, str], float],
    times: Mapping[tuple[str, str, int], Fraction | None],
    post_swap: Mapping[tuple[str, int], bool],
    checkpoints: Sequence[int], case: DriftCase, scope: DriftScope,
    *, t1_ms: int, step_start_ms: int,
) -> dict[tuple[str, str, str, int], float]:
    _validate_bounds(t1_ms, step_start_ms)
    if (not checkpoints or any(type(c) is not int or c < 1 for c in checkpoints)
            or any(a >= b for a, b in zip(checkpoints[:-1], checkpoints[1:], strict=True))):
        raise ValueError("checkpoints must be strictly increasing ints >= 1")
    for key, a0 in expected.items():
        if (not isinstance(key, tuple) or len(key) != 3 or key[0] not in ARMS
                or not isinstance(key[1], str) or not isinstance(key[2], str)):
            raise ValueError(f"bad expected key: {key}")
        if not isinstance(a0, float) or not math.isfinite(a0) or not -1000 <= a0 <= 1000:
            raise ValueError("expected scores must be finite floats in [-1000, 1000]")
        cell = key[2]
        bounds = floor_ceiling.get(cell)
        if (not isinstance(bounds, tuple) or len(bounds) != 2
                or not all(_finite(v) for v in bounds) or bounds[0] >= bounds[1]):
            raise ValueError(f"cell {cell}: need finite f0 < c0")
    result = {}
    for (arm, pair, cell), a0 in sorted(expected.items()):
        f0, c0 = floor_ceiling[cell]
        for ckpt in checkpoints:
            time_key = (arm, pair, ckpt)
            swap_key = (pair, ckpt)
            if time_key not in times:
                raise ValueError(f"missing unit time: {time_key}")
            if swap_key not in post_swap:
                raise ValueError(f"missing swap state: {swap_key}")
            t = times[time_key]
            value = a0
            if t is not None:
                dv = float(drift_points(case, t, t1_ms=t1_ms, step_start_ms=step_start_ms))
                if (arm, post_swap[swap_key]) in scope.drifts and dv != 0.0:
                    value = a0 + (10.0 * dv) * (a0 - f0) / (c0 - f0)
                    value = min(1000.0, max(-1000.0, value))
            result[(arm, pair, cell, ckpt)] = value
    return result
