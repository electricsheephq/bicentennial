"""Exact control-arm moments and their ordered-probit planning inputs."""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from statistics import NormalDist

from bicentennial.ocsim.model import CellModel, LatentParams, phi2

ACTION_LEVELS = (-1000, 0, 1000)
TIMING_LEVELS = (-1000, -250, 0, 125, 375, 625, 875, 1000)
_NORMAL = NormalDist()


@dataclass(frozen=True)
class ControlRecord:
    arm: str
    run: str
    life: str
    cell: str
    checkpoint: int
    bundle: str
    b0: int | None
    b1: int | None

    def __post_init__(self) -> None:
        if self.arm not in ("F", "C"):
            raise ValueError('arm must be "F" or "C"')
        if self.run not in ("A", "A_prime"):
            raise ValueError('run must be "A" or "A_prime"')
        if (any(not isinstance(v, str) for v in (self.life, self.cell, self.bundle))
                or type(self.checkpoint) is not int or self.checkpoint < 0):
            raise ValueError("ids must be str and checkpoint an int >= 0")
        if any(v is not None and (type(v) is not int or not -1000 <= v <= 1000)
               for v in (self.b0, self.b1)):
            raise ValueError("item scores must be None or ints in [-1000, 1000]")


@dataclass(frozen=True)
class CellMoments:
    arm: str
    cell: str
    n_lives: int
    n_bundles: int
    mean: Fraction
    msb: Fraction | None
    msw: Fraction | None
    n0: Fraction | None
    sigma2_life_raw: Fraction | None
    level_counts: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class VarianceInputs:
    moments: tuple[CellMoments, ...]
    timing_cells: frozenset[str]
    icc: Fraction
    icc_raw: Fraction | None
    rho_x: float
    rho_x_raw: float | None
    rho_a: float
    rho_a_raw: float | None
    reader_var: tuple[tuple[str, Fraction | None], ...]
    twin_r: float | None
    fc_r: float | None
    aa_r: float | None
    df: tuple[tuple[str, str, str, int], ...]
    n_nonresult: int
    n_aa_unpaired: int
    flags: tuple[str, ...]


def bin_item(value: int, timing: bool) -> int:
    """Bin a scored item; estimate supplies the cell id on support errors."""
    if type(value) is int:
        if value in (ACTION_LEVELS if not timing else (-1000, -250, 0, 1000)):
            return value
        if timing and 0 < value < 1000:
            return 125 + 250 * ((value - 1) // 250)
    raise ValueError(f"item value {value} outside its support")


def _mean(values) -> Fraction:
    return sum(values, Fraction()) / len(values)


def _score(record: ControlRecord) -> int:
    return min(record.b0, record.b1)


def _covariance(xs, ys) -> Fraction:
    mx, my = _mean(xs), _mean(ys)
    return sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)),
               Fraction()) / (len(xs) - 1)


def _cell_moments(arm, cell, lives, records, levels, binned) -> CellMoments:
    means = {life: _mean(values) for life, values in lives.items()}
    n = sum(len(values) for values in lives.values())
    grand = sum((sum(values) for values in lives.values()), Fraction()) / n
    count = len(lives)
    msb = msw = n0 = variance = None
    if count >= 2 and n > count:
        ssb = sum((len(values) * (means[life] - grand) ** 2
                   for life, values in lives.items()), Fraction())
        ssw = sum(((v - means[life]) ** 2
                   for life, values in lives.items() for v in values), Fraction())
        msb, msw = ssb / (count - 1), ssw / (n - count)
        n0 = (n - Fraction(sum(len(v) ** 2 for v in lives.values()), n)) / (count - 1)
        variance = (msb - msw) / n0
    counts = dict.fromkeys(levels, 0)
    for record in records:
        for value in binned[(record.arm, record.run, record.bundle)]:
            counts[value] += 1
    return CellMoments(arm, cell, count, n, grand, msb, msw, n0, variance,
                       tuple(counts.items()))


def _pearson(groups, statistic, flags):
    sxx = syy = sxy = Fraction()
    degrees = {}
    for (arm, _life, cell), pairs in sorted(groups.items()):
        xs, ys = zip(*pairs, strict=True)
        mx, my = _mean(xs), _mean(ys)
        sxx += sum(((x - mx) ** 2 for x in xs), Fraction())
        syy += sum(((y - my) ** 2 for y in ys), Fraction())
        sxy += sum(((x - mx) * (y - my) for x, y in pairs), Fraction())
        key = (statistic, arm, cell)
        degrees[key] = degrees.get(key, 0) + len(pairs) - 1
    if sxx * syy == 0:
        flags.add(f"{statistic}_undefined")
        value = None
    else:
        ratio = sxy ** 2 / (sxx * syy)
        value = (1 if sxy >= 0 else -1) * math.sqrt(ratio)
    return value, [(*key, value) for key, value in sorted(degrees.items())]


def _life_correlations(lives, moments, flags):
    positive = {key: max(Fraction(), m.sigma2_life_raw or Fraction())
                for key, m in moments.items()}
    means = {key: {life: _mean(values) for life, values in rows.items()}
             for key, rows in lives.items()}
    numerator, denominator = Fraction(), 0.0
    for arm in ("F", "C"):
        cells = sorted(cell for a, cell in lives if a == arm)
        for i, cell in enumerate(cells):
            for other in cells[i + 1:]:
                left, right = (arm, cell), (arm, other)
                if moments[left].msw is None or moments[right].msw is None:
                    continue  # an undefined cell is skipped by pooling, as in the ICC
                common = sorted(means[left].keys() & means[right].keys())
                if len(common) >= 2:
                    numerator += _covariance([means[left][life] for life in common],
                                             [means[right][life] for life in common])
                    denominator += math.sqrt(positive[left] * positive[right])
    rho_x, rho_x_raw = _correlation(numerator, denominator, 0.0, 0.95, "rho_x", flags)
    return positive, rho_x, rho_x_raw


def _correlation(numerator, denominator, low, high, name, flags):
    if denominator == 0:
        flags.add(f"{name}_undefined")
        return 0.0, None
    raw = float(numerator) / denominator
    value = min(high, max(low, raw))
    if value != raw:
        flags.add(f"{name}_clamped")
    return value, raw


def _twin_limit(rho_t: float) -> float:
    """The largest sigma_d2 <= (1 + rho_t)/2 that A1's check rho_t >= 2*sigma_d2 - 1 accepts.

    The plain float (1 + rho_t)/2 can fail that check by an ulp (rho_t = 0.1, say).
    """
    limit = (1.0 + rho_t) / 2
    while 2 * limit - 1 > rho_t:
        limit = math.nextafter(limit, -math.inf)
    return limit


def estimate(
    records: Iterable[ControlRecord], *, timing_cells: frozenset[str] = frozenset(),
) -> VarianceInputs:
    """Use raw bundle moments and binned items, excluding every nonresult.

    Cross-arm df entries use arm F to identify one contribution per cell;
    their observations are the matched F/C branch pairs. A valid A' row
    without a valid A partner is counted as unpaired.
    """
    indexed, identities, binned = {}, {}, {}
    for record in records:
        key = (record.arm, record.run, record.bundle)
        if key in indexed:
            raise ValueError(f"duplicate record: {record.arm} {record.run} {record.bundle}")
        identity = (record.life, record.cell, record.checkpoint)
        if record.bundle in identities and identities[record.bundle] != identity:
            raise ValueError(f"bundle {record.bundle} has conflicting life/cell/checkpoint")
        identities[record.bundle] = identity
        values = []
        for value in (record.b0, record.b1):
            if value is not None:
                try:
                    values.append(bin_item(value, record.cell in timing_cells))
                except ValueError as error:
                    raise ValueError(f"cell {record.cell}: {error}") from None
        indexed[key] = record
        if len(values) == 2:
            binned[key] = tuple(values)
    valid = {key: indexed[key] for key in sorted(binned)}
    run_a = [r for r in valid.values() if r.run == "A"]
    if not run_a:
        raise ValueError("no valid run-A records")
    flags, lives, by_cell = set(), {}, {}
    for record in run_a:
        key = (record.arm, record.cell)
        lives.setdefault(key, {}).setdefault(record.life, []).append(_score(record))
        by_cell.setdefault(key, []).append(record)
    moments = {}
    for arm, cell in sorted(lives, key=lambda key: (key[1], key[0])):
        levels = TIMING_LEVELS if cell in timing_cells else ACTION_LEVELS
        key = (arm, cell)
        moments[key] = _cell_moments(arm, cell, lives[key], by_cell[key], levels, binned)
        if moments[key].msw is None:
            flags.add(f"anova_undefined:{arm}:{cell}")
    defined = [m for m in moments.values() if m.msw is not None]
    numerator = sum(((m.n_lives - 1) * m.sigma2_life_raw for m in defined), Fraction())
    denominator = sum(((m.n_lives - 1) * (m.sigma2_life_raw + m.msw)
                       for m in defined), Fraction())
    icc_raw = numerator / denominator if denominator > 0 else None
    icc = max(Fraction(), icc_raw) if icc_raw is not None else Fraction()
    if icc_raw is None:
        flags.add("icc_undefined")
    elif icc_raw < 0:
        flags.add("icc_truncated")
    if icc == 1:
        flags.add("icc_one")
    positive, rho_x, rho_x_raw = _life_correlations(lives, moments, flags)
    paired_lives, twin_groups, fc_groups, aa_groups = {}, {}, {}, {}
    reader_sums = {arm: Fraction() for arm in ("F", "C")}
    reader_counts = dict.fromkeys(("F", "C"), 0)
    for record in run_a:
        group = (record.arm, record.life, record.cell)
        key = (record.arm, "A", record.bundle)
        twin_groups.setdefault(group, []).append(binned[key])
        rerun_key = (record.arm, "A_prime", record.bundle)
        if rerun_key in valid:
            reader_sums[record.arm] += (_score(record) - _score(valid[rerun_key])) ** 2
            reader_counts[record.arm] += 1
            aa_groups.setdefault(group, []).extend(zip(binned[key], binned[rerun_key], strict=True))
        other_key = ("C", "A", record.bundle)
        if record.arm == "F" and other_key in valid:
            other = valid[other_key]
            paired_lives.setdefault(record.cell, {}).setdefault(record.life, []).append(
                (_score(record), _score(other)))
            fc_groups.setdefault(group, []).extend(zip(binned[key], binned[other_key], strict=True))
    numerator, denominator = Fraction(), 0.0
    for cell, rows in sorted(paired_lives.items()):
        count, n = len(rows), sum(len(pairs) for pairs in rows.values())
        if count < 2 or n <= count:
            continue
        floor_means, ceiling_means, within = [], [], Fraction()
        for _life, pairs in sorted(rows.items()):
            xs, ys = zip(*pairs, strict=True)
            mx, my = _mean(xs), _mean(ys)
            floor_means.append(mx)
            ceiling_means.append(my)
            within += sum(((x - mx) * (y - my) for x, y in pairs), Fraction())
        correction = within / (n - count) * sum(
            (Fraction(1, len(pairs)) for pairs in rows.values()), Fraction()) / count
        numerator += (count - 1) * (_covariance(floor_means, ceiling_means) - correction)
        denominator += (count - 1) * math.sqrt(positive[("F", cell)] * positive[("C", cell)])
    rho_a, rho_a_raw = _correlation(numerator, denominator, -0.95, 0.95, "rho_a", flags)
    reader = []
    for arm in ("F", "C"):
        n = reader_counts[arm]
        reader.append((arm, reader_sums[arm] / (2 * n) if n else None))
        if not n:
            flags.add(f"no_aa:{arm}")
    twin_r, twin_df = _pearson(twin_groups, "twin", flags)
    fc_r, fc_df = _pearson(fc_groups, "fc", flags)
    aa_r, aa_df = _pearson(aa_groups, "aa", flags)
    n_unpaired = sum(r.run == "A_prime" and (r.arm, "A", r.bundle) not in valid
                     for r in valid.values())
    return VarianceInputs(
        tuple(moments.values()), timing_cells, icc, icc_raw, rho_x, rho_x_raw,
        rho_a, rho_a_raw, tuple(reader), twin_r, fc_r, aa_r,
        tuple(sorted(twin_df + fc_df + aa_df)), len(indexed) - len(valid), n_unpaired,
        tuple(sorted(flags)),
    )


def cut_locations(
    levels: tuple[int, ...], floor_counts: tuple[int, ...], ceiling_counts: tuple[int, ...],
) -> tuple[tuple[float, ...], float, float]:
    """Pool add-half probit cuts and fit the two zero-sum arm locations."""
    zs = []
    for counts in (floor_counts, ceiling_counts):
        total = sum(counts) + Fraction(len(levels), 2)
        cumulative = Fraction()
        z = []
        for count in counts[:-1]:
            cumulative += count + Fraction(1, 2)
            z.append(_NORMAL.inv_cdf(float(cumulative / total)))
        zs.append(z)
    floor_z, ceiling_z = zs
    cuts = tuple((f + c) / 2 for f, c in zip(floor_z, ceiling_z, strict=True))
    theta_f = sum(c - f for f, c in zip(floor_z, ceiling_z, strict=True)) / (2 * len(cuts))
    return cuts, theta_f, -theta_f


def score_covariance(levels, cuts, theta1, theta2, rho) -> float:
    """Use one ordered sum for every covariance, including both variances."""
    deltas = [right - left for left, right in zip(levels[:-1], levels[1:], strict=True)]
    return sum(
        dx * dy * (phi2(theta1 - cx, theta2 - cy, rho)
                   - _NORMAL.cdf(theta1 - cx) * _NORMAL.cdf(theta2 - cy))
        for dx, cx in zip(deltas, cuts, strict=True)
        for dy, cy in zip(deltas, cuts, strict=True)
    )


def match(
    r: float,
    levels: tuple[tuple[int, ...], ...],
    cuts: tuple[tuple[float, ...], ...],
    locations: tuple[tuple[float, float], ...],
    weights: tuple[int, ...],
) -> float:
    """Invert a pooled item Pearson with explicit supports for all entries.

    The four tuples align by entry. Each entry has its own levels, cuts,
    location pair and within-group df, allowing action and timing cells
    to contribute to the same correlation. Bisection always takes 64 steps.
    """
    entries = tuple(zip(levels, cuts, locations, weights, strict=True))
    variance1 = sum(w * score_covariance(v, c, t1, t1, 1.0)
                    for v, c, (t1, t2), w in entries)
    variance2 = sum(w * score_covariance(v, c, t2, t2, 1.0)
                    for v, c, (t1, t2), w in entries)
    denominator = math.sqrt(variance1 * variance2)

    def implied(rho):
        return sum(w * score_covariance(v, c, t1, t2, rho)
                   for v, c, (t1, t2), w in entries) / denominator

    if r >= implied(1.0):
        return 1.0
    if r <= implied(-1.0):
        return -1.0
    low, high = -1.0, 1.0
    for _ in range(64):
        mid = (low + high) / 2
        if implied(mid) < r:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def to_latent(
    inputs: VarianceInputs, *, gap_floor: int = 300,
) -> tuple[LatentParams, tuple[str, ...]]:
    """Match item correlations and construct A1's constrained planning model."""
    moments = {(m.arm, m.cell): m for m in inputs.moments}
    cells = sorted({m.cell for m in inputs.moments})
    supports, cuts, locations = {}, {}, {}
    for cell in cells:
        for arm in ("F", "C"):
            if (arm, cell) not in moments:
                raise ValueError(f"cell {cell} lacks arm {arm}")
        levels = TIMING_LEVELS if cell in inputs.timing_cells else ACTION_LEVELS
        supports[cell] = levels
        counts = [dict(moments[(arm, cell)].level_counts) for arm in ("F", "C")]
        cut, theta_f, theta_c = cut_locations(
            levels, *(tuple(count[level] for level in levels) for count in counts))
        cuts[cell] = cut
        locations[("F", cell)], locations[("C", cell)] = theta_f, theta_c

    def matched(statistic, value):
        entries = [(arm, cell, df) for stat, arm, cell, df in inputs.df
                   if stat == statistic and df > 0]
        return match(
            value, tuple(supports[cell] for arm, cell, df in entries),
            tuple(cuts[cell] for arm, cell, df in entries),
            tuple((locations[(arm, cell)], locations[("C", cell)]
                   if statistic == "fc" else locations[(arm, cell)])
                  for arm, cell, df in entries),
            tuple(df for arm, cell, df in entries),
        )

    flags = set()
    if inputs.twin_r is None:
        rho_t = 0.0
        flags.add("twin_default")
    else:
        rho_t = matched("twin", inputs.twin_r)
    if inputs.fc_r is None or inputs.fc_r <= 0:
        sigma_d2 = 0.0
        flags.add("sigma_d2_zero")
    else:
        sigma_d2 = min(0.99, max(0.0, matched("fc", inputs.fc_r)))
    sigma_r2 = None if inputs.aa_r is None else 1.0 - matched("aa", inputs.aa_r)
    limits = ([] if sigma_r2 is None else [1.0 - sigma_r2]) + [_twin_limit(rho_t)]
    for limit in limits:
        if sigma_d2 > limit:
            sigma_d2 = max(0.0, limit)
            flags.add("sigma_d2_constrained")
    if sigma_r2 is not None:
        sigma_r2 = min(1.0 - sigma_d2, max(0.0, sigma_r2))
    gap = max(Fraction(gap_floor), _mean([
        moments[("C", cell)].mean - moments[("F", cell)].mean for cell in cells]))
    if gap > 2000:
        raise ValueError("gap exceeds the scale")
    models = []
    for cell in cells:
        floor, ceiling = moments[("F", cell)], moments[("C", cell)]
        mid = (floor.mean + ceiling.mean) / 2
        f0, c0 = mid - gap / 2, mid + gap / 2
        if c0 > 1000:
            f0, c0 = f0 - (c0 - 1000), Fraction(1000)
        if f0 < -1000:
            f0, c0 = Fraction(-1000), c0 + (-1000 - f0)
        variances = []
        for moment in (floor, ceiling):
            if moment.msw is None:
                variance = Fraction()
            elif inputs.icc == 1:
                variance = max(Fraction(), moment.sigma2_life_raw)
            else:
                variance = inputs.icc / (1 - inputs.icc) * moment.msw
            variances.append(math.sqrt(variance))
        models.append(CellModel(cell, supports[cell], cuts[cell], float(f0), float(c0),
                                *variances))
    return (LatentParams(tuple(models), inputs.rho_x, inputs.rho_a, rho_t, sigma_d2,
                         sigma_r2), tuple(sorted(flags)))
