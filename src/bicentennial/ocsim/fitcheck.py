"""Report-only, life-cluster control fit check; calibration governs flags."""

import math
from fractions import Fraction
from functools import cache
from statistics import NormalDist

from bicentennial.keyed import uniform_int
from bicentennial.ocsim import locate, model
from bicentennial.stats.variance_inputs import bin_item

SEED = "bicentennial-fitcheck-v1"
LIFE_NODES = 6
SHARED_NODES = 5
FAMILIES = ("mean", "msw", "life", "gate")
UNIT = ("ocsim", "fitcheck")


@cache
def normal_rule(n):
    """Gauss--Hermite for N(0,1), via normalized Hermite recurrence."""
    if n < 1:
        raise ValueError("need at least one quadrature node")
    roots = []
    z = 0.0
    for i in range(1, (n + 1) // 2 + 1):
        if i == 1:
            z = math.sqrt(2 * n + 1) - 1.85575 * (2 * n + 1) ** (-1 / 6)
        elif i == 2:
            z -= 1.14 * n ** 0.426 / z
        elif i == 3:
            z = 1.86 * z - 0.86 * roots[0][0]
        elif i == 4:
            z = 1.91 * z - 0.91 * roots[1][0]
        else:
            z = 2 * z - roots[i - 3][0]
        for _ in range(30):
            p, previous = math.pi ** (-0.25), 0.0
            for j in range(1, n + 1):
                p, previous = (z * math.sqrt(2 / j) * p
                               - math.sqrt((j - 1) / j) * previous), p
            derivative = math.sqrt(2 * n) * previous
            change = p / derivative
            z -= change
            if abs(change) < 1e-14:
                break
        roots.append((z, 2 / (derivative ** 2 * math.sqrt(math.pi))))
    return tuple(sorted((sign * x * math.sqrt(2), w)
                        for i, (x, w) in enumerate(roots)
                        for sign in ((1,) if n % 2 and i == len(roots) - 1 else (-1, 1))))


solver = cache(locate.table_solver)


def prepare(records, timing_cells=frozenset()):
    """Return (sums, design), after estimate's validation and Run-A filter.

    Sums map (arm, cell, life) to [n, sum, sum_squares]. Design maps
    (cell, life) to (n_F, n_C, shared_valid_bundle_ids), including zeros.
    """
    indexed, identities, sums, ids = set(), {}, {}, {}
    for r in records:
        key, identity = (r.arm, r.run, r.bundle), (r.life, r.cell, r.checkpoint)
        if key in indexed:
            raise ValueError(f"duplicate record: {r.arm} {r.run} {r.bundle}")
        if r.bundle in identities and identities[r.bundle] != identity:
            raise ValueError(f"bundle {r.bundle} has conflicting life/cell/checkpoint")
        indexed.add(key)
        identities[r.bundle] = identity
        for value in (r.b0, r.b1):
            if value is not None:
                try:
                    bin_item(value, r.cell in timing_cells)
                except ValueError as error:
                    raise ValueError(f"cell {r.cell}: {error}") from None
        if r.run != "A" or r.b0 is None or r.b1 is None:
            continue
        key = (r.arm, r.cell, r.life)
        row = sums.setdefault(key, [0, 0, 0])
        y = min(r.b0, r.b1)
        row[0] += 1
        row[1] += y
        row[2] += y * y
        ids.setdefault(key, set()).add(r.bundle)
    if not sums:
        raise ValueError("no valid run-A records")
    lives = sorted({life for _, _, life in sums})
    cells = sorted({cell for _, cell, _ in sums})
    design = {(cell, life): (sums.get(("F", cell, life), [0])[0],
                            sums.get(("C", cell, life), [0])[0],
                            len(ids.get(("F", cell, life), set())
                                & ids.get(("C", cell, life), set())))
              for cell in cells for life in lives}
    return sums, design


def statistics(sums, cells, lives, *, exact=False):
    """Repeated life names are distinct draws, including in gate and ANOVA."""
    divide = Fraction if exact else lambda x, y: x / y
    result = {}
    for cell in cells:
        for arm in ("F", "C"):
            rows = [sums[(arm, cell, life)] for life in lives if (arm, cell, life) in sums]
            n, total, squares = map(sum, zip(*rows, strict=True)) if rows else (0, 0, 0)
            count = len(rows)
            mean = divide(total, n) if n else None
            msw = life_var = None
            if count >= 2 and n > count:
                between = sum(divide(s * s, k) for k, s, _ in rows) - divide(total * total, n)
                msw = (squares - sum(divide(s * s, k) for k, s, _ in rows)) / (n - count)
                n0 = (n - divide(sum(k * k for k, _, _ in rows), n)) / (count - 1)
                life_var = (between / (count - 1) - msw) / n0
            for family, value in zip(FAMILIES, (mean, msw, life_var), strict=False):
                result[(family, arm, cell)] = value
        gates = [(divide(sums[("F", cell, life)][1], sums[("F", cell, life)][0])
                  + divide(sums[("C", cell, life)][1], sums[("C", cell, life)][0])) / 2
                 for life in lives if all((a, cell, life) in sums for a in ("F", "C"))]
        result[("gate", "F+C", cell)] = ((sum(g * g for g in gates)
            - sum(gates) ** 2 / len(gates)) / (len(gates) - 1) if len(gates) > 1 else None)
    return result


def clipped_moments(base, sigma):
    """Exact mean and variance of clip(base + sigma*Z, -1000, 1000)."""
    if sigma == 0:
        return max(-1000, min(1000, base)), 0.0
    normal = NormalDist()
    lower, upper = (-1000 - base) / sigma, (1000 - base) / sigma
    below, above = normal.cdf(lower), 1 - normal.cdf(upper)
    mass = 1 - below - above
    density = normal.pdf(lower) - normal.pdf(upper)
    mean = 1000 * (above - below) + base * mass + sigma * density
    second = (1e6 * (below + above) + (base**2 + sigma**2) * mass
              + 2 * base * sigma * density
              + sigma**2 * (lower * normal.pdf(lower) - upper * normal.pdf(upper)))
    return mean, max(0.0, second - mean**2)


def model_values(params, design, *, rule=None, nodes=LIFE_NODES, shared=SHARED_NODES):
    """Integrate at the design; rule maps cells to (x_F, x_C, weight) rows."""
    solve, result = solver(params), {}
    for cell in params.cells:
        points = (rule[cell.cell] if rule is not None else
                  [(x, params.rho_a * x + math.sqrt(1 - params.rho_a ** 2) * u, w * v)
                   for x, w in normal_rule(nodes) for u, v in normal_rule(nodes)])
        means, seconds, within = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
        cross = gate_second = 0.0
        for xf, xc, weight in points:
            targets = [max(-1000, min(1000, base + sd * x)) for base, sd, x in
                       ((cell.f0, cell.sigma_f, xf), (cell.c0, cell.sigma_c, xc))]
            locations = [solve(cell, t) for t in targets]
            targets = [cell.levels[0] if theta == "low" else cell.levels[-1]
                       if theta == "high" else t for theta, t in zip(locations, targets, strict=True)]
            for a, (theta, target) in enumerate(zip(locations, targets, strict=True)):
                variance = 0.0 if isinstance(theta, str) else max(0.0,
                    cell.levels[0] ** 2 + sum((hi * hi - lo * lo) * model.phi2(
                        theta - cut, theta - cut, params.rho_t) for lo, hi, cut in zip(
                            cell.levels[:-1], cell.levels[1:], cell.cuts, strict=True)) - target ** 2)
                means[a] += weight * target
                seconds[a] += weight * target ** 2
                within[a] += weight * variance
            gate_second += weight * ((targets[0] + targets[1]) / 2) ** 2
            if params.sigma_d2 and not any(isinstance(t, str) for t in locations):
                scale = math.sqrt(1 - params.sigma_d2)
                rho = max(-1, min(1, (params.rho_t - params.sigma_d2) / scale ** 2))
                for g, w in normal_rule(shared):
                    conditional = [cell.levels[0] + sum((hi - lo) * model.phi2(
                        (theta + math.sqrt(params.sigma_d2) * g - cut) / scale,
                        (theta + math.sqrt(params.sigma_d2) * g - cut) / scale, rho)
                        for lo, hi, cut in zip(cell.levels[:-1], cell.levels[1:],
                                              cell.cuts, strict=True)) for theta in locations]
                    cross += weight * w * (conditional[0] - targets[0]) * (conditional[1] - targets[1])
        for a, arm in enumerate(("F", "C")):
            for family, value in zip(FAMILIES, (means[a], within[a], seconds[a] - means[a] ** 2), strict=False):
                result[(family, arm, cell.cell)] = value
        counts = [v for (k, _), v in design.items() if k == cell.cell and v[0] and v[1]]
        noise = sum((within[0] / nf + within[1] / nc + 2 * cross * s / (nf * nc)) / 4
                    for nf, nc, s in counts) / len(counts) if counts else 0
        result[("gate", "F+C", cell.cell)] = gate_second - (sum(means) / 2) ** 2 + noise
        result[("K", "F+C", cell.cell)] = cross
        if rule is None:
            for arm, base, sigma in (("F", cell.f0, cell.sigma_f), ("C", cell.c0, cell.sigma_c)):
                result[("mean", arm, cell.cell)], result[("life", arm, cell.cell)] = clipped_moments(base, sigma)
    return result


@cache
def draws(lives, resamples, unit):
    return tuple(tuple(lives[uniform_int(SEED, unit, r, f"life-{j}", 0, len(lives) - 1)]
                       for j in range(len(lives))) for r in range(resamples))


def bootstrap(sums, cells, lives, resamples, unit=UNIT):
    """Cluster SEs; each draw position is a distinct, implicitly relabelled life."""
    if resamples < 2:
        raise ValueError("need at least two resamples")
    totals, squares, counts = {}, {}, {}
    for selected in draws(tuple(lives), resamples, unit):
        for key, value in statistics(sums, cells, selected).items():
            if value is not None:
                totals[key] = totals.get(key, 0.0) + value
                squares[key] = squares.get(key, 0.0) + value * value
                counts[key] = counts.get(key, 0) + 1
    return {key: (math.sqrt(max(0, (squares[key] - total ** 2 / resamples) / (resamples - 1)))
                  if counts[key] == resamples else 0.0) for key, total in totals.items()}


def family_stat(zs):
    return sum(z * z for z in zs) / len(zs) if zs and all(z is not None for z in zs) else None


def evaluate(sums, design, values, resamples, unit=UNIT):
    cells, lives = sorted({k for k, _ in design}), sorted({life for _, life in design})
    observed = statistics(sums, cells, lives, exact=True)
    ses = bootstrap(sums, cells, lives, resamples, unit)
    zs = {key: (float(value - values[key]) / ses[key]
                if value is not None and ses.get(key, 0) > 0 else None)
          for key, value in observed.items()}
    return observed, ses, zs, {f: family_stat([z for key, z in zs.items() if key[0] == f]) for f in FAMILIES}


def simulate(params, design, rep, *, prefix="cal", rule=None):
    """Sample sufficient sums using the model's exact bundle stream."""
    lives = sorted({life for _, life in design})
    names = {life: f"{prefix}-{i}" for i, life in enumerate(lives)}
    effects = model.life_effects(params, list(names.values()), SEED, rep)
    solve, sums = solver(params), {}
    for (cell_id, life), (nf, nc, matched) in sorted(design.items()):
        cell, name = params.cell(cell_id), names[life]
        n = nf + nc - matched
        latents = model.bundle_latents(params, {(cell_id, 0): n}, [name], SEED, rep)[(name, cell_id, 0)]
        if rule is None:
            xs = [effects.x[(arm, name, cell_id)] for arm in ("F", "C")]
        else:
            # Weighted categorical rule, using a separate keyed stream.
            u = uniform_int(SEED, ("ocsim", "fitcheck-rule", name, cell_id), rep, "point", 0, 2**53 - 1) / 2**53
            index, cumulative = 0, rule[cell_id][0][2]
            while cumulative < u and index + 1 < len(rule[cell_id]):
                index += 1
                cumulative += rule[cell_id][index][2]
            xs = rule[cell_id][index][:2]
        for arm, count, base, sd, x in zip(("F", "C"), (nf, nc), (cell.f0, cell.c0),
                                          (cell.sigma_f, cell.sigma_c), xs, strict=True):
            indices = range(count) if arm == "F" else (*range(matched), *range(nf, n))
            theta = solve(cell, max(-1000, min(1000, base + sd * x)))
            ys = [min(model.item_pair(cell, theta, *latents[arm][i])) for i in indices]
            if count:
                sums[(arm, cell_id, life)] = [count, sum(ys), sum(y * y for y in ys)]
    return sums


def calibrate(params, design, *, datasets=200, resamples=2000, rule=None):
    """Calibrate each family's 95th percentile, counting undefined datasets."""
    if datasets < 1:
        raise ValueError("need calibration datasets")
    values = model_values(params, design, rule=rule)
    samples = {f: [] for f in FAMILIES}
    for d in range(datasets):
        stats = evaluate(simulate(params, design, d, rule=rule), design, values, resamples,
                         ("ocsim", f"fitcheck-calibration-{d}"))[3]
        for f, value in stats.items():
            if value is not None:
                samples[f].append(value)
    return {f: {"threshold": (f"{sorted(v)[math.ceil(.95 * len(v)) - 1]:.9f}" if v else "undefined"),
                "undefined": datasets - len(v)} for f, v in samples.items()}


def chi95(k):
    """Invert the regularized lower gamma series (positive integer df)."""
    def cdf(x):
        a, term, total = k / 2, 1 / (k / 2), 1 / (k / 2)
        for j in range(1, 1000):
            term *= x / (a + j)
            total += term
            if term < total * 1e-15:
                break
        return total * math.exp(-x + a * math.log(x) - math.lgamma(a))
    lo, hi = 0.0, float(k + 100)
    for _ in range(60):
        mid = (lo + hi) / 2
        if cdf(mid / 2) < .95:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def check(records, params, *, timing_cells=frozenset(), resamples=2000, datasets=200,
          rule=None, thresholds=None):
    """Return a report with integer/string leaves; never alter a verdict."""
    sums, design = prepare(records, timing_cells)
    if {k for k, _ in design} != {c.cell for c in params.cells}:
        raise ValueError("records and model must name the same cells")
    thresholds = calibrate(params, design, datasets=datasets, resamples=resamples, rule=rule) if thresholds is None else thresholds
    values = model_values(params, design, rule=rule)
    observed, ses, zs, stats = evaluate(sums, design, values, resamples)
    entries = [{"family": f, "arm": a, "cell": c, "observed": f"{float(v):.6f}" if v is not None else "undefined",
                "model": f"{model_values_map:.6f}", "SE": f"{ses.get((f, a, c), 0):.6f}",
                "z": round(zs[(f, a, c)] * 1000) if zs[(f, a, c)] is not None else "undefined"}
               for (f, a, c), v in observed.items()
               for model_values_map in [values[(f, a, c)]]]
    families = []
    for f in FAMILIES:
        k = sum(key[0] == f for key in observed)
        threshold, stat = thresholds[f]["threshold"], stats[f]
        families.append({"family": f, "K": k, "mean_z2": round(stat * 1000) if stat is not None else "undefined",
                         "threshold": round(float(threshold) * 1000) if threshold != "undefined" else "undefined",
                         "chi_reference": round(chi95(k) / k * 1000),
                         "flag": "cannot check" if stat is None or threshold == "undefined" else
                         ("flag" if stat > float(threshold) else "pass"), "undefined": thresholds[f]["undefined"]})
    return {"seed": SEED, "R": resamples, "D": datasets, "entries": entries, "families": families,
            "listed": [e for e in entries if (z := zs[(e["family"], e["arm"], e["cell"])]) is not None and abs(z) > 2.58],
            "timing_cells": sorted(timing_cells)}


def card_lines(result):
    lines = ["## Fit check (bar-2 controls)",
             "A flag blocks the PREREG-v1 freeze until an owner ruling on #245 (decision 2); it never changes a simulated verdict.",
             "msw, gate and the cross-arm term use a 36-point Gauss–Hermite rule; on heavily clipped cells their model values carry quadrature error."]
    lines += [f"{f['family']}: {f['flag']}; mean z²={f['mean_z2']}/1000; calibrated threshold={f['threshold']}/1000; χ²(K, .95)/K={f['chi_reference']}/1000 (for reference); undefined calibration datasets={f['undefined']}" for f in result["families"]]
    lines += [f"{e['family']} {e['arm']} {e['cell']}: z={e['z']}/1000" for e in result["listed"]]
    if result["timing_cells"]:
        lines.append("timing cells: raw scores against the model's binned levels")
    return lines
