"""PREREG-v0.4 §§2 and 7 statistics, using only exact arithmetic and keyed draws."""

from collections.abc import Collection, Mapping, Sequence
from fractions import Fraction
from math import lcm

from bicentennial.keyed import draw

type Score = Fraction | int
type Values = Mapping[str, Score] | Sequence[Score]


def _fraction(value: Score) -> Fraction:
    """Refuse inexact numeric inputs rather than silently accepting floats."""
    if type(value) is not int and not isinstance(value, Fraction):
        raise TypeError("values must be Fraction or int")
    return Fraction(value)


def _ordered_values(values: Values) -> tuple[tuple[str, Fraction], ...]:
    """Sort life mappings; give sequence positions stable string identities."""
    if isinstance(values, Mapping):
        if any(not isinstance(life, str) for life in values):
            raise TypeError("life keys must be strings")
        items = tuple((life, _fraction(values[life])) for life in sorted(values))
    elif isinstance(values, Sequence):
        items = tuple((str(i), _fraction(value)) for i, value in enumerate(values))
    else:
        raise TypeError("values must be a life mapping or an ordered sequence")
    if not items:
        raise ValueError("at least one life is required")
    return items


def _scaled(items: tuple[tuple[str, Fraction], ...]) -> tuple[list[int], int]:
    """Scale rational scores by their denominators' least common multiple."""
    denominator = lcm(*(value.denominator for _, value in items))
    return [value.numerator * (denominator // value.denominator)
            for _, value in items], denominator


def contributions(
    scores_a: Mapping[tuple[str, str], Score],
    scores_b: Mapping[tuple[str, str], Score],
    valid: Mapping[str, Collection[str]],
    *, lives: Collection[str],
) -> dict[str, Fraction]:
    """Return the §2 (lines 135–139) common-set contributions c_l.

    Scores are flat {(track_id, life_id): Fraction | int} mappings. Each score
    must already be a within-life mean over bundles valid for both systems.
    valid is {track_id: collection_of_common_valid_life_ids}; IDs are strings.
    lives explicitly gives the life universe L: every life of the run, even
    those with no common-valid bundle on any track. It must include the union
    of the valid sets, otherwise ValueError is raised. No score may occur
    outside valid, and both systems must score every valid pair.
    Empty tracks (including an empty track family) raise ValueError, as do
    extra or missing scores. Output includes every life in sorted order;
    lives with no valid bundle contribute Fraction(0).

    Each term has weight len(L) / (len(valid) * len(valid[track])). For the
    budget row (§2, lines 140–147), pass the Keep subset as lives and the K10
    scores and valid sets for all included tracks; the same reweighting applies.
    """
    if not valid:
        raise ValueError("at least one track is required")
    support = {}
    life_ids = dict.fromkeys(sorted(lives))
    for track in sorted(valid):
        track_lives = dict.fromkeys(sorted(valid[track]))
        if not track_lives:
            raise ValueError(f"empty common valid set for track {track!r}")
        if any(life not in life_ids for life in track_lives):
            raise ValueError("lives must include every life in the valid sets")
        support[track] = track_lives
    for scores in (scores_a, scores_b):
        for track, life in sorted(scores):
            if track not in support or life not in support[track]:
                raise ValueError(f"score outside valid set: {(track, life)!r}")
        for track, track_lives in support.items():
            for life in track_lives:
                if (track, life) not in scores:
                    raise ValueError(f"missing score: {(track, life)!r}")
    result = dict.fromkeys(sorted(life_ids), Fraction(0))
    for track, track_lives in support.items():
        weight = Fraction(len(result), len(support) * len(track_lives))
        for life in track_lives:
            key = (track, life)
            result[life] += weight * (_fraction(scores_a[key]) - _fraction(scores_b[key]))
    return result


def sign_flip_p(values: Values, *, seed: str, name: str) -> Fraction:
    """Return the two-sided sign-flip p-value from §7, line 489.

    values is a nonempty {life_id: Fraction | int} mapping (sorted by ID) or
    an ordered sequence (life IDs are its zero-based positions as strings).
    Compare absolute sums, counting ties. Fractions are scaled by the LCM
    of their denominators; all comparisons use integers.

    PREREG implies exhaustive enumeration for n <= 20 and 100,000 fixed-seed
    draws otherwise. Exact p is k / 2**n. For Monte Carlo we include the
    observed assignment separately: p = (k + 1) / 100,001. §7 does not specify
    that correction; it is the issue #223 convention. Zero observed sums
    give p = 1 in either branch.

    A draw's unit is ("stats", "sign_flip", life_id), its attempt is the
    zero-based replicate, and its name is name. One unbiased low bit gives
    the Rademacher sign. No ambient random state or hash order is used.
    """
    items = _ordered_values(values)
    integers, _ = _scaled(items)
    observed = abs(sum(integers))
    if observed == 0:
        return Fraction(1)
    n = len(integers)
    if n <= 20:
        # Start all-negative, then change just the bit flipped by Gray code.
        total = -sum(integers)
        count = int(abs(total) >= observed)
        previous_gray = 0
        for assignment in range(1, 1 << n):
            gray = assignment ^ (assignment >> 1)
            changed = gray ^ previous_gray
            index = changed.bit_length() - 1
            total += (2 if gray & changed else -2) * integers[index]
            count += abs(total) >= observed
            previous_gray = gray
        return Fraction(count, 1 << n)
    units = tuple(("stats", "sign_flip", life) for life, _ in items)
    count = 0
    for replicate in range(100_000):
        total = sum(value if draw(seed, unit, replicate, name) & 1 else -value
                    for unit, value in zip(units, integers, strict=True))
        count += abs(total) >= observed
    return Fraction(count + 1, 100_001)


def bootstrap_ci(
    values: Values, *, seed: str, name: str, draws: int = 10_000,
    level: Fraction = Fraction(95, 100),
) -> tuple[Fraction, Fraction]:
    """Return a percentile wild cluster CI over lives (§7, lines 489, 523–524).

    values has the same nonempty mapping/sequence shape as sign_flip_p.
    Each replicate is mean + mean(w_l * (c_l - mean)), with independent
    Rademacher weights. This is a scalar headline CI; joint cell/control
    resampling for certification is outside this function's scope.

    Sort B=draws replicates ascending. For q=(1-level)/2 and r=(1+level)/2,
    the zero-based endpoint indices are max(0, ceil(B*q)-1) and
    max(0, ceil(B*r)-1), respectively: inverse empirical CDF, no interpolation.
    PREREG specifies the bootstrap, count and weights; issue #223 specifies
    percentiles, and this function fixes their otherwise unspecified indices.
    Require a positive integer draws and 0 < level < 1 (Fraction or int).

    Draw unit ("stats", "bootstrap", life_id), attempt=zero-based replicate,
    name=name separates this stream from the sign-flip stream. Computation
    uses a common integer scale, returning only exact Fraction endpoints.
    """
    items = _ordered_values(values)
    if type(draws) is not int or draws <= 0:
        raise ValueError("draws must be a positive integer")
    level = _fraction(level)
    if not 0 < level < 1:
        raise ValueError("level must lie strictly between zero and one")
    integers, scale = _scaled(items)
    n = len(integers)
    total = sum(integers)
    deviations = [n * value - total for value in integers]
    units = tuple(("stats", "bootstrap", life) for life, _ in items)
    replicates = []
    for replicate in range(draws):
        perturbation = sum(value if draw(seed, unit, replicate, name) & 1 else -value
                           for unit, value in zip(units, deviations, strict=True))
        replicates.append(n * total + perturbation)
    replicates.sort()
    indices = []
    for quantile in ((1 - level) / 2, (1 + level) / 2):
        rank = quantile * draws
        ceiling = (rank.numerator + rank.denominator - 1) // rank.denominator
        indices.append(max(0, ceiling - 1))
    denominator = n * n * scale
    return (Fraction(replicates[indices[0]], denominator),
            Fraction(replicates[indices[1]], denominator))


def holm(
    p_values: Mapping[str, Score], *, alpha: Fraction = Fraction(5, 100),
) -> dict[str, tuple[Fraction, bool]]:
    """Return {hypothesis: (adjusted_p, reject)} using Holm (§7, line 492).

    p_values is a mapping in the family's declared input order. Sort by p
    stably, so ties keep that order; the output also keeps input order.
    For sorted p_(i), i=0..M-1, adjusted_p_(i) is
    min(1, max_{j<=i} ((M-j)*p_(j))). Reject when adjusted_p <= alpha.
    p-values and alpha must be exact Fraction or int in [0, 1]. An empty
    family returns {}. Input order is intentional here, including for ties.
    """
    alpha = _fraction(alpha)
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must lie between zero and one")
    values = {hypothesis: _fraction(value) for hypothesis, value in p_values.items()}
    if any(not 0 <= value <= 1 for value in values.values()):
        raise ValueError("p-values must lie between zero and one")
    adjusted = {}
    running = Fraction(0)
    for i, hypothesis in enumerate(sorted(values, key=values.__getitem__)):
        running = min(Fraction(1), max(running, (len(values) - i) * values[hypothesis]))
        adjusted[hypothesis] = (running, running <= alpha)
    return {hypothesis: adjusted[hypothesis] for hypothesis in values}
