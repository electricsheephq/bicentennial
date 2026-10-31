"""Bar-2 common-bundle pilot contributions and sample SDs (PREREG §2/§7)."""

import math
import statistics
from fractions import Fraction

from bicentennial.stats.core import contributions


def pair_contributions(bundles, a, b, tracks, lives) -> dict[str, Fraction]:
    """Use pair-valid means in milli; include every run life, including zeros.

    Inputs have already passed the base builder's shape and support checks.
    ValueError here signals a caller programming error.
    """
    left, right = ({tuple(row[:4]): row[4] for row in bundles[arm]} for arm in (a, b))
    if left.keys() != right.keys():
        raise ValueError("bundle identities differ")
    groups = {}
    for key in sorted(left):
        _, life, track, keep = key
        if left[key] is not None and right[key] is not None:
            groups.setdefault((track, life, keep), []).append((left[key], right[key]))
    scores_a, scores_b = {}, {}
    valid = {track: set() for track in sorted(tracks)}
    for track in valid:
        keeps = ("K100", "K10") if track == "Keep" else ("K100",)
        for life in sorted(lives):
            rows = [groups.get((track, life, keep), []) for keep in keeps]
            if not all(rows):
                continue
            means = [[sum((Fraction(pair[side]) for pair in group), Fraction(0)) / len(group)
                      for group in rows] for side in (0, 1)]
            values = [Fraction(1, 4) * v[0] + Fraction(3, 4) * v[1]
                      if track == "Keep" else v[0] for v in means]
            scores_a[track, life], scores_b[track, life] = values
            valid[track].add(life)
    return contributions(scores_a, scores_b, valid, lives=lives)


def sigma_d(bundles, pairs, tracks, lives) -> tuple[float, dict[tuple[str, str], float]]:
    """Median pair SD in raw-scale percentage points, using sample variance."""
    deviations = {}
    for a, b in sorted(pairs):
        values = pair_contributions(bundles, a, b, tracks, lives)
        deviations[a, b] = math.sqrt(float(statistics.variance(
            [Fraction(c, 10) for c in values.values()])))
    if not deviations:
        raise ValueError("at least one pair is required")
    return statistics.median(deviations.values()), deviations
