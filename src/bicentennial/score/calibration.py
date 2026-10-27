"""Calibration on QA confidence and actions (PREREG §3 Calibration, DESIGN §7.2).

Every result is an exact Fraction, or None when its denominator is 0. QA inputs are
(confidence_milli, correct) pairs from answered items only: unknown, missing and
system-failure items are excluded by the caller.
"""

from fractions import Fraction

BINS = 10  # equal-width bins on [0, 1]


def _answered(pairs) -> list[tuple[int, bool]]:
    pairs = list(pairs)
    for confidence, correct in pairs:
        if type(confidence) is not int or not 0 <= confidence <= 1000 or type(correct) is not bool:
            raise ValueError("pairs: (confidence_milli 0..1000, correct bool) required")
    return pairs


def brier(pairs) -> Fraction | None:
    """Mean of (c/1000 - y)^2."""
    pairs = _answered(pairs)
    if not pairs:
        return None
    return sum((Fraction(c, 1000) - y) ** 2 for c, y in pairs) / len(pairs)


def ece(pairs) -> Fraction | None:
    """Sum over bins of (n_k / N) * |accuracy_k - mean confidence_k|, bin = min(9, c // 100)."""
    pairs = _answered(pairs)
    if not pairs:
        return None
    # (n_k / N) * |acc_k - conf_k| = |sum of y - sum of c/1000| / N within each bin.
    gaps = [Fraction(0)] * BINS
    for c, y in pairs:
        gaps[min(BINS - 1, c // 100)] += y - Fraction(c, 1000)
    return sum(abs(gap) for gap in gaps) / len(pairs)


def selective_accuracy(answered_correct: int, answered: int, total: int):
    """Return (coverage, accuracy): answered / total and correct / answered."""
    counts = (answered_correct, answered, total)
    if any(type(n) is not int for n in counts) or not 0 <= answered_correct <= answered <= total:
        raise ValueError("counts: 0 <= answered_correct <= answered <= total required")
    coverage = Fraction(answered, total) if total else None
    accuracy = Fraction(answered_correct, answered) if answered else None
    return coverage, accuracy


def assertion_precision(pairs) -> Fraction | None:
    """Over action items as (acted, correct) pairs: the share of those acted on that were correct."""
    pairs = list(pairs)
    if any(type(acted) is not bool or type(correct) is not bool for acted, correct in pairs):
        raise ValueError("pairs: (acted bool, correct bool) required")
    acted = [correct for was_acted, correct in pairs if was_acted]
    return Fraction(sum(acted), len(acted)) if acted else None
