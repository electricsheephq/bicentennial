"""Report-only Gaussian D = S - (F+C)/2, in points: ideal schedule, no drift.

Scores are unclipped; pass-overs, failures and deferrals are ignored. The
delta approximation freezes bundle noise at each arm's mean target (solved
location), adding it to the exact linear life covariance. Bundle minimum
moments use exact phi2 sums; cross-arm moments condition on the shared draw.
Values are bit-reproducible on one platform, as solve_location's are; the
run manifest records that platform. No float escapes predict().
"""

import math
from statistics import NormalDist

from bicentennial.ocsim import model

PANELS = 1536
NORMAL = NormalDist()


def integral(fn, low, high):
    """Fixed Simpson quadrature with sixth-order Richardson correction."""
    h = (high - low) / PANELS
    ends = fn(low) + fn(high)
    odd = even = coarse_odd = coarse_even = 0.0
    for i in range(1, PANELS):
        value = fn(low + i * h)
        if i % 2:
            odd += value
        else:
            even += value
            if i % 4:
                coarse_odd += value
            else:
                coarse_even += value
    fine = h / 3 * (ends + 4 * odd + 2 * even)
    coarse = 2 * h / 3 * (ends + 4 * coarse_odd + 2 * coarse_even)
    return (16 * fine - coarse) / 15


def nct_tail(critical, df, delta):
    lognorm = (1 - df / 2) * math.log(2) - math.lgamma(df / 2)

    def integrand(r):
        density = (math.exp(lognorm) if df == 1 else 0.0) if r == 0 else math.exp(
            lognorm + (df - 1) * math.log(r) - r * r / 2)
        return density * NORMAL.cdf(delta - critical * r / math.sqrt(df))

    return min(1.0, max(0.0, integral(integrand, max(0, math.sqrt(df) - 12),
                                        math.sqrt(df) + 12)))


def t95(df):
    low, high = 0.0, 8.0
    for _ in range(42):
        mid = (low + high) / 2
        if nct_tail(mid, df, 0) > 0.05:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def bracket(marginals):
    return [math.floor(1_000_000 * max(0, 1 - sum(1 - p for p in marginals))),
            math.ceil(1_000_000 * min(marginals))]


def bundle_variance(cell, params, margin):
    lam = model.interpolation(cell, margin)
    targets = (cell.f0, cell.c0, cell.f0 + lam * (cell.c0 - cell.f0))
    locations = [model.solve_location(cell, params.rho_t, t) for t in targets]
    weights = (-0.5, -0.5, 1.0)
    variances = []
    for theta, target in zip(locations, targets, strict=True):
        second = cell.levels[0] ** 2
        if not isinstance(theta, str):
            second += sum((hi * hi - lo * lo) * model.phi2(theta - c, theta - c,
                          params.rho_t) for lo, hi, c in zip(
                              cell.levels[:-1], cell.levels[1:], cell.cuts, strict=True))
        else:
            second = target * target
        variances.append(max(0, second - target * target))
    value = sum(w * w * v for w, v in zip(weights, variances, strict=True))
    if params.sigma_d2:
        scale = math.sqrt(1 - params.sigma_d2)
        rho = max(-1, min(1, (params.rho_t - params.sigma_d2) / scale ** 2))

        def cross(g, i, j):
            means = []
            for a in (i, j):
                theta = locations[a]
                means.append(targets[a] if isinstance(theta, str) else cell.levels[0] + sum(
                    (hi - lo) * model.phi2((theta + math.sqrt(params.sigma_d2) * g - c) / scale,
                    (theta + math.sqrt(params.sigma_d2) * g - c) / scale, rho)
                    for lo, hi, c in zip(cell.levels[:-1], cell.levels[1:], cell.cuts, strict=True)))
            return (means[0] - targets[i]) * (means[1] - targets[j]) * NORMAL.pdf(g)

        value += sum(2 * weights[i] * weights[j] * integral(lambda g, i=i, j=j: cross(g, i, j), -9, 9)
                     for i in range(3) for j in range(i))
    return max(0, value) / 100


def moments(params, alloc, margins):
    cells = [c for c in params.cells if c.cell in margins]
    coefficients, noise = [], []
    for cell in cells:
        lam = model.interpolation(cell, margins[cell.cell])
        coefficients.append(((lam - 0.5) * -cell.sigma_f / 10,
                             (lam - 0.5) * cell.sigma_c / 10,
                             model.default_tau(cell, params.rho_a, lam) / 10))
        count = sum(v for (k, _), v in alloc.items() if k == cell.cell)
        noise.append(bundle_variance(cell, params, margins[cell.cell]) / count)
    covariance = []
    for i, (f, c, s) in enumerate(coefficients):
        covariance.append([])
        for j, (g, d, t) in enumerate(coefficients):
            life = (f * g + c * d + params.rho_a * (f * d + c * g) + s * t)
            covariance[-1].append(life * (1 if i == j else params.rho_x)
                                  + (noise[i] if i == j else 0))
    return [float(margins[c.cell]) for c in cells], covariance


def predict(params, point, alloc, margins, alternative, *, swaps=()):
    n, _ = point
    if n < 2:
        return None
    if alternative == "PRE_SWAP":
        # Unequal per-pair allocations are heteroscedastic, outside this t model.
        scopes = [{key: v for key, v in alloc.items() if key[1] < swap} for swap in swaps]
        if not scopes or any(scope != scopes[0] for scope in scopes):
            return None
        alloc = scopes[0]
    if any(not sum(v for (k, _), v in alloc.items() if k == cell) for cell in margins):
        return None
    means, sigma = moments(params, alloc, margins)
    variances = [sigma[i][i] for i in range(len(means))]
    joint = sum(map(sum, sigma)) / len(means) ** 2
    tests = [(sum(means) / len(means), joint, 0)] + list(zip(means, variances, [-10] * len(means), strict=True))
    critical = t95(n - 1)

    def probabilities(cut):
        return [nct_tail(cut, n - 1, (mean - bar) * math.sqrt(n / variance))
                if variance else float(mean >= bar) for mean, variance, bar in tests]

    # Wild-bootstrap SE uses divisor n, giving sqrt(n-1)/n times population SD.
    ses = [math.sqrt(v * (n - 1)) / n for v in variances]
    def pooled_cdf(value):
        return sum(NORMAL.cdf(((value / se) ** (2 / 3) - 1 + 2 / (9 * (n - 1)))
                   / math.sqrt(2 / (9 * (n - 1)))) if se else 1 for se in ses) / len(ses)
    low, high = 0.0, max(ses) * 10
    for _ in range(48):
        mid = (low + high) / 2
        if pooled_cdf(mid) < 0.95:
            low = mid
        else:
            high = mid
    return {"gaussian_ppm": bracket(probabilities(critical)),
            "uncalibrated_ppm": bracket(probabilities(NORMAL.inv_cdf(0.95))),
            "cell_se": {c.cell: f"{math.ceil(se * 1000)}/1000" for c, se in zip(
                [c for c in params.cells if c.cell in margins], ses, strict=True)},
            "gaussian_se_p95": f"{math.ceil(high * 1000)}/1000"}
