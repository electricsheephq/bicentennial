"""Pure Keep tier zeroing and exact track weighting (PREREG-v0.4 §3)."""

from fractions import Fraction

from bicentennial.sandbox.bytes import TIERS, over_tier


def tier_scores(scores, *, store_bytes, raw_bytes, can_cap):
    """Return {tier: {score: Fraction, cause: str | None}} for each tier that ran.

    Every tier is its own branch (DESIGN's branch table): K100 is the base life,
    and each reduced cap is a separate replay. scores and store_bytes give the
    score and the store size above the empty-store baseline measured in each
    branch the caller ran; K100 is required. A system that cannot cap stores its
    natural size in every branch, so it scores 0 at each tier below that size,
    with the cause "unsupported"; a capping system above a cap gets "over_cap".
    Scores retain their input units (including milli units), without rounding.
    """
    if (set(scores) | set(store_bytes)) - TIERS.keys():
        raise ValueError("unknown Keep tier")
    if set(scores) != set(store_bytes):
        raise ValueError("every scored Keep tier needs its store size")
    if "K100" not in scores:
        raise ValueError("missing K100 base-life measurement")
    result = {}
    for tier in TIERS:
        if tier not in scores:
            continue
        over = over_tier(store_bytes[tier], raw_bytes, tier)
        score = Fraction() if over else Fraction(scores[tier])
        cause = ("over_cap" if can_cap else "unsupported") if over else None
        result[tier] = dict(score=score, cause=cause)
    return result


def t_keep(t_k100, t_k10):
    """Return the exact Keep track score, in the inputs' units."""
    return (Fraction(t_k100) + 3 * Fraction(t_k10)) / 4
