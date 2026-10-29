"""Pure Keep tier zeroing and exact track weighting (PREREG-v0.4 §3)."""

from fractions import Fraction

from bicentennial.sandbox.bytes import TIERS, over_tier


def tier_scores(scores, *, store_bytes, raw_bytes, can_cap):
    """Return {tier: {score: Fraction, cause: str | None}} for all Keep tiers.

    scores and store_bytes map tiers to the measured score and the store size
    above the empty-store baseline. A capping system runs once per tier, so it
    supplies both for every tier. A non-capping system runs once, at K100: its
    natural size decides where that one score is used. Scores retain their
    input units (including milli units), without rounding or normalisation.
    """
    if set(scores) - TIERS.keys():
        raise ValueError("scores name an unknown Keep tier")
    if set(store_bytes) - TIERS.keys():
        raise ValueError("store sizes name an unknown Keep tier")
    required = TIERS.keys() if can_cap else {"K100"}
    if required - scores.keys():
        raise ValueError("missing measured Keep tier score")
    if required - store_bytes.keys():
        raise ValueError("missing measured Keep tier store size")
    result = {}
    for tier in TIERS:
        measured = tier if can_cap else "K100"
        over = over_tier(store_bytes[measured], raw_bytes, tier)
        score = Fraction() if over else Fraction(scores[measured])
        cause = ("over_cap" if can_cap else "unsupported") if over else None
        result[tier] = dict(score=score, cause=cause)
    return result


def t_keep(t_k100, t_k10):
    """Return the exact Keep track score, in the inputs' units."""
    return (Fraction(t_k100) + 3 * Fraction(t_k10)) / 4
