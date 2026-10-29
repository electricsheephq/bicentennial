"""Exact PREREG-v0.4 §4 admission and §7 cell gates and certification.

Callers supply raw penalised pair scores on common valid bundles, the board's
own pinned-reader controls after the last block, and probe-filtered naive RAG.
This module does not run arms, establish provenance, or decide required cells.
Results retain diagnostics even when no certificate can be issued. Stability
is descriptive, not an error rate or a power guarantee.
Bounds use t-calibrated percentiles to correct the wild bootstrap's reduced
variance and normal tails when there are few resampling units.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from math import isqrt
from typing import Literal

from bicentennial.keyed import draw
from bicentennial.stats.core import Score, _fraction, _scaled

type Key = tuple[str, str]
type Verdict = Literal["CLEAR", "FAIL", "UNRESOLVED", "BLOCKED"]
type Admission = Literal["ADMITTED", "NOT_ADMITTED"]
type Outcome = Literal["NO_CERTIFICATE", "NOT_CERTIFIED", "DEFERRED", "CERTIFIED"]

# Cell-specific labels append :<cell>; all other labels stand alone.
REASON_LABELS = (
    "board_kind", "image_season_only", "image_planning_size", "unsealed",
    "n_lives", "bundles", "se", "na_reader", "coverage_system",
    "coverage_infrastructure", "blocked", "not_admitted", "admission_undefined",
    "empty_scores", "empty_controls", "r_a", "r_b",
)

# p_n = Phi(-t_{n-1, 1-alpha} * sqrt(n/(n-1))), alpha = .05 or .025.
# Computed from the t distribution (regularised incomplete beta) and checked
# against published t quantiles.
_ONE_SIDED_PPM = (  # n = 2..200 resampling units; parts per million
    0, 174, 3290, 8575, 13644, 17914, 21414, 24285, 26663, 28656,
    30345, 31794, 33047, 34142, 35106, 35961, 36724, 37409, 38027, 38588,
    39099, 39567, 39996, 40391, 40757, 41096, 41411, 41704, 41979, 42235,
    42476, 42702, 42916, 43117, 43307, 43487, 43657, 43819, 43972, 44119,
    44258, 44391, 44518, 44639, 44755, 44866, 44973, 45075, 45173, 45268,
    45358, 45446, 45530, 45611, 45689, 45764, 45837, 45907, 45975, 46041,
    46105, 46167, 46226, 46284, 46340, 46395, 46448, 46499, 46549, 46598,
    46645, 46691, 46735, 46779, 46821, 46862, 46902, 46941, 46980, 47017,
    47053, 47089, 47123, 47157, 47190, 47222, 47254, 47285, 47315, 47344,
    47373, 47401, 47429, 47456, 47482, 47508, 47534, 47559, 47583, 47607,
    47630, 47653, 47676, 47698, 47720, 47741, 47762, 47782, 47802, 47822,
    47842, 47861, 47879, 47898, 47916, 47934, 47951, 47968, 47985, 48002,
    48018, 48034, 48050, 48066, 48081, 48096, 48111, 48126, 48140, 48154,
    48168, 48182, 48196, 48209, 48222, 48235, 48248, 48260, 48273, 48285,
    48297, 48309, 48321, 48332, 48344, 48355, 48366, 48377, 48388, 48399,
    48409, 48420, 48430, 48440, 48450, 48460, 48469, 48479, 48489, 48498,
    48507, 48516, 48525, 48534, 48543, 48552, 48561, 48569, 48577, 48586,
    48594, 48602, 48610, 48618, 48626, 48634, 48641, 48649, 48656, 48664,
    48671, 48678, 48686, 48693, 48700, 48707, 48714, 48720, 48727, 48734,
    48740, 48747, 48753, 48760, 48766, 48772, 48779, 48785, 48791,
)
_TWO_SIDED_PPM = (  # n = 2..200 resampling units; parts per million
    0, 0, 119, 954, 2432, 4109, 5738, 7225, 8551, 9722,
    10757, 11671, 12483, 13207, 13856, 14439, 14966, 15445, 15881, 16280,
    16646, 16983, 17294, 17582, 17850, 18099, 18332, 18550, 18754, 18946,
    19126, 19296, 19456, 19608, 19752, 19888, 20017, 20140, 20258, 20369,
    20476, 20577, 20675, 20768, 20857, 20943, 21025, 21104, 21179, 21252,
    21322, 21390, 21455, 21518, 21579, 21637, 21694, 21749, 21802, 21853,
    21903, 21951, 21998, 22043, 22087, 22129, 22171, 22211, 22250, 22288,
    22325, 22361, 22396, 22430, 22463, 22496, 22527, 22558, 22588, 22617,
    22646, 22674, 22701, 22728, 22754, 22779, 22804, 22829, 22852, 22876,
    22898, 22921, 22943, 22964, 22985, 23005, 23025, 23045, 23064, 23083,
    23102, 23120, 23138, 23155, 23173, 23190, 23206, 23222, 23238, 23254,
    23269, 23285, 23299, 23314, 23328, 23343, 23357, 23370, 23384, 23397,
    23410, 23423, 23435, 23448, 23460, 23472, 23484, 23495, 23507, 23518,
    23529, 23540, 23551, 23562, 23572, 23582, 23593, 23603, 23612, 23622,
    23632, 23641, 23651, 23660, 23669, 23678, 23687, 23696, 23704, 23713,
    23721, 23729, 23738, 23746, 23754, 23762, 23769, 23777, 23785, 23792,
    23799, 23807, 23814, 23821, 23828, 23835, 23842, 23849, 23856, 23862,
    23869, 23875, 23882, 23888, 23894, 23901, 23907, 23913, 23919, 23925,
    23931, 23936, 23942, 23948, 23953, 23959, 23964, 23970, 23975, 23981,
    23986, 23991, 23996, 24001, 24006, 24011, 24016, 24021, 24026,
)


@dataclass(frozen=True)
class Estimate:
    point: Fraction
    lower: Fraction
    interval: tuple[Fraction, Fraction]
    se2: Fraction
    se_milli: int
    replicates: tuple[Fraction, ...]
    units: int


@dataclass(frozen=True)
class CellResult:
    cell: str
    pairs: tuple[str, ...]
    valid_pairs: tuple[str, ...]
    score_pairs: tuple[str, ...]
    pooled_pairs: tuple[str, ...]
    support: int
    blocked: bool
    floor: Fraction | None
    ceiling: Fraction | None
    gate: Estimate | None
    half_gates: tuple[Fraction | None, Fraction | None]
    gap: Estimate | None
    arm: Estimate | None
    margin: Estimate | None
    verdict: Verdict | None


@dataclass(frozen=True)
class Eligibility:
    na_reader: bool
    coverage: Fraction
    shortfall: Literal["system", "infrastructure"] | None = None

    def __post_init__(self):
        object.__setattr__(self, "coverage", _fraction(self.coverage))
        if type(self.na_reader) is not bool or not 0 <= self.coverage <= 1:
            raise ValueError("invalid reader status or coverage")
        if self.shortfall not in (None, "system", "infrastructure"):
            raise ValueError("unknown coverage shortfall")
        if self.coverage < Fraction(95, 100) and self.shortfall is None:
            raise ValueError("coverage shortfall needs a cause")


@dataclass(frozen=True)
class Board:
    kind: Literal["season", "delta", "pilot", "developer"]
    profile: Literal["text", "image"]
    sealed: bool
    n_lives: int
    b: int

    def __post_init__(self):
        if self.kind not in ("season", "delta", "pilot", "developer"):
            raise ValueError("unknown board kind")
        if self.profile not in ("text", "image") or type(self.sealed) is not bool:
            raise ValueError("invalid profile or seal")
        _count(self.n_lives, "n_lives", minimum=0)
        _count(self.b, "b", minimum=0)


@dataclass(frozen=True)
class Bounds:
    n_L: int = 24
    b: int = 150
    se: Fraction = Fraction(5)

    def __post_init__(self):
        _count(self.n_L, "n_L")
        _count(self.b, "b")
        object.__setattr__(self, "se", _fraction(self.se))
        if self.se < 0:
            raise ValueError("SE bound must be nonnegative")


@dataclass(frozen=True)
class Certification:
    outcome: Outcome
    reasons: tuple[str, ...]
    cells: tuple[CellResult, ...]
    mean_margin: Estimate | None
    r_a: bool | None
    r_b: tuple[tuple[str, bool | None], ...]
    stability: Fraction | None


def _count(value: int, label: str, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")


def _mean(values: Collection[Fraction]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


@dataclass(frozen=True)
class _Series:
    point: Fraction
    center: Fraction
    coefficients: tuple[tuple[str, int], ...]
    scale: int

    def at(self, weights: Mapping[str, int]) -> Fraction:
        return self.center + Fraction(sum(weights[p] * c for p, c in self.coefficients),
                                      self.scale)


def _series(point: Fraction, coefficients: Mapping[str, Fraction], *,
            center: Fraction | None = None) -> _Series:
    items = tuple(sorted(coefficients.items()))
    integers, scale = _scaled(items)
    return _Series(point, point if center is None else center,
                   tuple((p, c) for (p, _), c in zip(items, integers, strict=True)), scale)


def _wild(values: Mapping[str, Fraction]) -> _Series | None:
    if not values:
        return None
    center = _mean(tuple(values.values()))
    return _series(center, {p: (v - center) / len(values) for p, v in values.items()})


@dataclass(frozen=True)
class _Cell:
    cell: str
    pairs: tuple[str, ...]
    valid: tuple[str, ...]
    scored: tuple[str, ...]
    pooled: tuple[str, ...]
    floor: Fraction | None
    ceiling: Fraction | None
    halves: tuple[Fraction | None, Fraction | None]
    series: tuple[_Series | None, ...]  # gate, arm, gap, margin


def _prepare(pairs, scores, controls, block_of, exclude_pooled) -> tuple[_Cell, ...]:
    if any(not isinstance(k, str) for k in pairs):
        raise TypeError("cell IDs must be strings")
    universe = {}
    for k in sorted(pairs):
        if any(not isinstance(p, str) for p in pairs[k]):
            raise TypeError("pair IDs must be strings")
        universe[k] = tuple(sorted(set(pairs[k])))
    for mapping in (scores, controls):
        for key in mapping:
            if (not isinstance(key, tuple) or len(key) != 2
                    or key[0] not in universe or key[1] not in universe[key[0]]):
                raise ValueError(f"key outside pairs: {key!r}")
    arm = {key: _score(value) for key, value in scores.items()}
    control = {}
    for key, value in controls.items():
        if not isinstance(value, tuple) or len(value) != 2:
            raise ValueError("controls must be (floor, ceiling) tuples")
        control[key] = tuple(_score(v) for v in value)
    first = None
    if block_of is not None:
        # The run's blocks fix the halves, whether or not a block kept its controls.
        run = {p for all_pairs in universe.values() for p in all_pairs}
        if any(p not in block_of for p in run):
            raise ValueError("block_of must include every pair")
        if any(type(block_of[p]) is not int for p in run):
            raise TypeError("block IDs must be integers")
        blocks = sorted({block_of[p] for p in run})
        first = set(blocks[:len(blocks) // 2])
    result = []
    for k, all_pairs in universe.items():
        floors = {p: control[k, p][0] for p in all_pairs if (k, p) in control}
        ceilings = {p: control[k, p][1] for p in floors}
        gates = {p: (floors[p] + ceilings[p]) / 2 for p in floors}
        values = {p: arm[k, p] for p in all_pairs if (k, p) in arm
                  and (not exclude_pooled or p in gates)}
        pooled = tuple(p for p in values if p not in gates)
        gate, system = _wild(gates), _wild(values)
        gap = _wild({p: ceilings[p] - floors[p] for p in floors})
        margin = None
        if gate is not None and system is not None:
            # Each missing control uses the SAME perturbed pooled gate.
            gate_weights = {p: (Fraction(int(p in values)) + Fraction(len(pooled), len(gates)))
                            / len(values) for p in gates}
            point = system.point - sum((gate_weights[p] * gates[p] for p in gates), Fraction(0))
            coefficients = {p: (values[p] - system.point) / len(values) for p in values}
            for p in gates:
                coefficients[p] = coefficients.get(p, Fraction(0)) - gate_weights[p] * (gates[p] - gate.point)
            margin = _series(point, coefficients, center=system.point - gate.point)
        halves = (None, None)
        if first is not None:
            split = (tuple(gates[p] for p in gates if block_of[p] in first),
                     tuple(gates[p] for p in gates if block_of[p] not in first))
            halves = tuple(_mean(part) if part else None for part in split)
        result.append(_Cell(k, all_pairs, tuple(gates), tuple(values), pooled,
                            _mean(tuple(floors.values())) if floors else None,
                            _mean(tuple(ceilings.values())) if ceilings else None,
                            halves, (gate, system, gap, margin)))
    return tuple(result)


def _score(value: Score) -> Fraction:
    value = _fraction(value)
    if not -100 <= value <= 100:
        raise ValueError("raw scores must lie in [-100, 100]")
    return value


def _replicate(cell: _Cell, weights: Mapping[str, int]) -> tuple[Fraction | None, ...]:
    return tuple(series.at(weights) if series is not None else None for series in cell.series)


def _replicates(
    pairs: Mapping[str, Collection[str]], scores: Mapping[Key, Score],
    controls: Mapping[Key, tuple[Score, Score]],
    weight_vectors: Sequence[Mapping[str, int]], *, exclude_pooled: bool = False,
) -> tuple[tuple[tuple[Fraction | None, ...], ...], ...]:
    """Explicit-weight test seam: [replicate][sorted cell][gate, arm, gap, margin]."""
    cells = _prepare(pairs, scores, controls, None, exclude_pooled)
    for weights in weight_vectors:
        if any(p not in weights or type(weights[p]) is not int or weights[p] not in (-1, 1)
               for cell in cells for p in cell.pairs):
            raise ValueError("weights must supply +1 or -1 for every pair")
    return tuple(tuple(_replicate(cell, weights) for cell in cells) for weights in weight_vectors)


def _estimate(point: Fraction, replicates: Sequence[Fraction], *, units: int) -> Estimate:
    ordered = sorted(replicates)
    draws = len(ordered)
    # Cap on the conservative side; fewer than two units use the extrema.
    one = _ONE_SIDED_PPM[min(units, 200) - 2] if units >= 2 else 0
    two = _TWO_SIDED_PPM[min(units, 200) - 2] if units >= 2 else 0

    def percentile(ppm):
        return ordered[max(0, (draws * ppm + 999_999) // 1_000_000 - 1)]

    mean = _mean(ordered)
    se2 = _mean(tuple(v * v for v in ordered)) - mean * mean
    scaled = se2 * 1_000_000
    return Estimate(point, percentile(one), (percentile(two), percentile(1_000_000 - two)),
                    se2, isqrt(scaled.numerator // scaled.denominator), tuple(replicates), units)


def cell_statistics(
    pairs: Mapping[str, Collection[str]], scores: Mapping[Key, Score],
    controls: Mapping[Key, tuple[Score, Score]], *, seed: str, name: str,
    draws: int = 10_000, groups: Mapping[str, str] | None = None,
    block_of: Mapping[str, int] | None = None, exclude_pooled: bool = False,
) -> tuple[CellResult, ...]:
    """Return sorted immutable cells; pooled gate is ``cell.gate.point``.

    Groups and blocks cover the whole pair universe; integer block IDs encode
    start order, and the run's blocks fix the gate halves. Exclusion drops only
    arm scores with missing controls; it never changes control support or the
    run universe.
    Empty score/control sets yield undefined estimates where appropriate.
    """
    _count(draws, "draws")
    cells = _prepare(pairs, scores, controls, block_of, exclude_pooled)
    pair_ids = sorted({p for cell in cells for p in cell.pairs})
    if groups is not None and any(p not in groups for p in pair_ids):
        raise ValueError("groups must include every pair")
    ids = {p: groups[p] if groups is not None else p for p in pair_ids}
    if any(not isinstance(group, str) for group in ids.values()):
        raise TypeError("group IDs must be strings")
    units = tuple(("stats", "certify", group) for group in sorted(set(ids.values())))
    samples = [[[] for _ in cell.series] for cell in cells]
    for r in range(draws):
        signs = {unit[-1]: 1 if draw(seed, unit, r, name) & 1 else -1 for unit in units}
        weights = {p: signs[ids[p]] for p in pair_ids}
        for cell, columns in zip(cells, samples, strict=True):
            for column, value in zip(columns, _replicate(cell, weights), strict=True):
                if value is not None:
                    column.append(value)
    result = []
    for cell, columns in zip(cells, samples, strict=True):
        gate, arm, gap, margin = tuple(
            _estimate(series.point, values, units=len({ids[p] for p, _ in series.coefficients}))
            if series is not None else None
            for series, values in zip(cell.series, columns, strict=True))
        blocked = 4 * len(cell.valid) < 3 * len(cell.pairs)
        verdict = None
        if arm is not None and gate is not None:
            verdict = ("BLOCKED" if blocked else "CLEAR" if arm.interval[0] >= gate.point
                       else "FAIL" if arm.interval[1] < gate.point else "UNRESOLVED")
        result.append(CellResult(cell.cell, cell.pairs, cell.valid, cell.scored, cell.pooled,
                                 len(cell.valid), blocked, cell.floor, cell.ceiling, gate,
                                 cell.halves, gap, arm, margin, verdict))
    return tuple(result)


def cell_admission(cell: CellResult, naive_rag: CellResult) -> Admission | None:
    """§4: caller supplies naive RAG after §11 probe-only exclusions.

    Naive RAG must come from cell_statistics(..., exclude_pooled=True):
    admission uses the surviving pairs only (PREREG-v0.4 §7, l.526).
    """
    if cell.cell != naive_rag.cell or cell.pairs != naive_rag.pairs:
        raise ValueError("admission requires the same cell universe")
    if (cell.blocked or naive_rag.verdict in (None, "BLOCKED")
            or 4 * len(naive_rag.score_pairs) < 3 * len(cell.pairs) or cell.gap is None):
        return None
    if naive_rag.pooled_pairs:
        raise ValueError("admission uses surviving pairs only: "
                         "compute naive RAG with exclude_pooled=True")
    if cell.gap.lower < 30 or naive_rag.verdict == "CLEAR":
        return "NOT_ADMITTED"
    return "ADMITTED"


def certify(
    pairs: Mapping[str, Collection[str]], scores: Mapping[Key, Score],
    controls: Mapping[Key, tuple[Score, Score]], *, required: Collection[str],
    eligibility: Mapping[str, Eligibility], admissions: Mapping[str, Admission | None],
    board: Board, seed: str, name: str, draws: int = 10_000,
    bounds: Bounds | None = None, groups: Mapping[str, str] | None = None,
    block_of: Mapping[str, int] | None = None, exclude_pooled: bool = False,
) -> Certification:
    """Certify one declared profile, retaining all computed diagnostics.

    ``admissions`` comes from cell_admission, not from the system's display
    verdict. Required cells must be nonempty and unique. Missing eligibility
    or admission is an input error; explicit admission None defers.
    """
    required = tuple(sorted(required))
    if not required or len(set(required)) != len(required):
        raise ValueError("required cells must be nonempty and unique")
    for mapping in (eligibility, admissions):
        if any(k not in pairs for k in mapping):
            raise ValueError("metadata outside pairs")
        if any(k not in pairs or k not in mapping for k in required):
            raise ValueError("missing required cell metadata")
    if any(v not in (None, "ADMITTED", "NOT_ADMITTED") for v in admissions.values()):
        raise ValueError("unknown admission")
    bounds = bounds if bounds is not None else Bounds()
    cells = cell_statistics(pairs, scores, controls, seed=seed, name=name, draws=draws,
                            groups=groups, block_of=block_of, exclude_pooled=exclude_pooled)
    selected = tuple(c for c in cells if c.cell in required)
    margins = tuple(c.margin for c in selected)
    mean_margin = None
    stability = None
    if all(m is not None for m in margins):
        joint = tuple(_mean(tuple(row)) for row in zip(*(m.replicates for m in margins), strict=True))
        # Margin coefficients retain every pair in S_k union V_k, including zeros.
        margin_units = {groups[p] if groups is not None else p
                        for c in selected for p in (*c.score_pairs, *c.valid_pairs)}
        mean_margin = _estimate(_mean(tuple(m.point for m in margins)), joint,
                                units=len(margin_units))
        passes = sum(avg >= 0 and all(m.replicates[r] >= -10 for m in margins)
                     for r, avg in enumerate(joint))
        stability = Fraction(passes, draws)
    r_a = mean_margin.lower >= 0 if mean_margin is not None else None
    r_b = tuple((c.cell, c.margin.lower >= -10 if c.margin is not None else None) for c in selected)
    impossible, blocks, deferrals = [], [], []
    if board.kind not in ("season", "delta"):
        impossible.append("board_kind")
    if board.profile == "image":
        if board.kind != "season":
            impossible.append("image_season_only")
        if board.n_lives == 8 and board.b == 40:
            impossible.append("image_planning_size")
    if not board.sealed:
        impossible.append("unsealed")
    if board.n_lives < bounds.n_L:
        impossible.append("n_lives")
    if board.b < bounds.b:
        impossible.append("bundles")
    for c in selected:
        k, e = c.cell, eligibility[c.cell]
        if c.margin is not None and c.margin.se2 > bounds.se * bounds.se:
            impossible.append(f"se:{k}")
        if e.na_reader:
            blocks.append(f"na_reader:{k}")
        if e.coverage < Fraction(95, 100):
            (blocks if e.shortfall == "system" else deferrals).append(f"coverage_{e.shortfall}:{k}")
        if c.blocked:
            deferrals.append(f"blocked:{k}")
        if admissions[k] != "ADMITTED":
            deferrals.append(f"not_admitted:{k}" if admissions[k] == "NOT_ADMITTED"
                             else f"admission_undefined:{k}")
        if c.arm is None:
            deferrals.append(f"empty_scores:{k}")
        if c.gate is None:
            deferrals.append(f"empty_controls:{k}")
    failures = ((["r_a"] if r_a is False else [])
                + [f"r_b:{k}" for k, passed in r_b if passed is False])
    if impossible:
        outcome, reasons = "NO_CERTIFICATE", impossible
    elif blocks:
        outcome, reasons = "NOT_CERTIFIED", blocks
    elif deferrals:
        outcome, reasons = "DEFERRED", deferrals
    elif failures:
        outcome, reasons = "NOT_CERTIFIED", failures
    else:
        outcome, reasons = "CERTIFIED", []
    return Certification(outcome, tuple(reasons), cells, mean_margin, r_a, r_b, stability)
