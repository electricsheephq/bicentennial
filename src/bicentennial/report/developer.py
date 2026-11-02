"""Pure paired developer statistics; callers establish card comparability."""

from dataclasses import dataclass
from fractions import Fraction

from bicentennial.canon import milli
from bicentennial.contracts.run import validate
from bicentennial.report.t2lite_flips import _differs, _exclusion, _scored
from bicentennial.stats.core import bootstrap_ci, sign_flip_p

_LABEL = "a developer signal; not predictive of the full tier; confirm on Ring 1 before claiming"
_NO_AA = "no A/A′ pair supplied"
_FEW = "too few lives for a clustered interval"
_LIMIT = "p cannot reach 0.025 unless at least 6 lives differ"
_SCOPE = "covers every arm the run executed"
_FIELDS = ("life", "branch", "item_id", "cell_id", "stage", "score_milli",
           "failure_class", "base_verdict", "not_scored_live")


class DeveloperReportRefused(ValueError):
    """Input refusal with a stable machine-readable code."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _rows(rows):
    if isinstance(rows, (str, bytes, dict)):
        raise DeveloperReportRefused("invalid_rows")
    try:
        iterator = iter(rows)
    except TypeError as error:
        raise DeveloperReportRefused("invalid_rows") from error
    result = {}
    for source in iterator:
        try:
            row = {key: source[key] for key in _FIELDS}
        except (KeyError, TypeError, IndexError) as error:
            raise DeveloperReportRefused("invalid_rows") from error
        if (any(type(row[k]) is not str or not row[k] for k in _FIELDS[:5])
                or row["stage"] not in ("remember", "survive", "act")
                or type(row["not_scored_live"]) is not bool
                or any(row[k] is not None and type(row[k]) is not str
                       for k in ("failure_class", "base_verdict"))
                or row["score_milli"] is not None and type(row["score_milli"]) is not int):
            raise DeveloperReportRefused("invalid_rows")
        key = tuple(row[k] for k in _FIELDS[:3])
        if key in result:
            raise DeveloperReportRefused("invalid_rows")
        result[key] = dict(row)
    return result


def _pair(a, b, code):
    a, b = _rows(a), _rows(b)
    if a.keys() != b.keys():
        raise DeveloperReportRefused(code)
    pairs = []
    for key in sorted(a):
        left, right = a[key], b[key]
        if any(left[k] != right[k] for k in ("cell_id", "stage")):
            raise DeveloperReportRefused("invalid_rows")
        pairs.append((left, right))
    return pairs


@dataclass(frozen=True)
class _Record:
    score_milli: int | None
    failure_class: str | None
    base_verdict: str | None
    stage: str
    genre: str


def _record(row):
    # Project the explicit live-scoring flag onto the shared exclusion helper's shape.
    return _Record(score_milli=row["score_milli"],
                   failure_class=row["failure_class"], base_verdict=row["base_verdict"],
                   stage="act" if row["not_scored_live"] else row["stage"],
                   genre="G2" if row["not_scored_live"] else "")


def _reason(*rows):
    records = [_record(row) for row in rows]
    return _exclusion(*records) or (None if _scored(*records) else "no_int_score")


def _number(value):
    if value is None:
        return None
    value = Fraction(value)
    return dict(numerator=value.numerator, denominator=value.denominator, milli=milli(value))


def _isqrt(n):
    """Integer square root by descending Newton iteration."""
    if not n:
        return 0
    root = 1 << ((n.bit_length() + 1) // 2)
    while True:
        next_root = (root + n // root) // 2
        if next_root >= root:
            return root
        root = next_root


def _wilson(x, n):
    """95% Wilson endpoints in ppm, rounded outward at a 10**12 root scale."""
    if not n:
        return [0, 1_000_000]
    z, scale = Fraction("3.841458820694124"), 10**12
    center = (Fraction(x) + z / 2) / (n + z)
    radius2 = z * (Fraction(x * (n - x), n) + z / 4) / (n + z)**2
    root = _isqrt(radius2.numerator * scale**2 // radius2.denominator)
    radius = Fraction(root if Fraction(root**2, scale**2) == radius2 else root + 1, scale)
    lo = max(Fraction(0), (center - radius) * 1_000_000)
    hi = min(Fraction(1_000_000), (center + radius) * 1_000_000)
    return [lo.numerator // lo.denominator, -(-hi.numerator // hi.denominator)]


def _sample(pairs):
    lives, scored = {}, []
    for a, b in pairs:
        if _reason(a, b) is None:
            delta = Fraction(a["score_milli"] - b["score_milli"], 1000)
            lives.setdefault(a["life"], []).append(delta)
            scored.append((a, b, delta))
    values = {life: sum(xs, Fraction()) / len(xs) for life, xs in sorted(lives.items())}
    return values, scored


def _stats(pairs, *, seed, name):
    values, scored = _sample(pairs)
    estimate = sum(values.values(), Fraction()) / len(values) if values else None
    nonzero = {life: value for life, value in values.items() if value}
    interval = ([_number(x) for x in bootstrap_ci(values, seed=seed, name=name)]
                if len(values) >= 10 else _FEW)
    return dict(life_count=len(values), scored_items=len(scored), excluded_items=len(pairs)-len(scored),
                discordant=dict(current_higher=sum(d > 0 for _, _, d in scored),
                                previous_higher=sum(d < 0 for _, _, d in scored)),
                estimate=_number(estimate), interval=interval,
                p=_number(sign_flip_p(nonzero, seed=seed, name=name) if nonzero else
                          Fraction(1) if values else None),
                direction=("no scored items" if estimate is None else "current higher" if estimate > 0
                           else "previous higher" if estimate < 0 else "equal"))


def _sensitivity(values, discordant):
    n = len(values)
    result = dict(status="not estimable", approximate=True, value=None, life_count=n,
                  discordant_items=discordant, exact_test_limit=_LIMIT)
    if discordant < 5 or n < 2:
        return result
    mean = sum(values.values(), Fraction()) / n
    variance = sum(((v - mean)**2 for v in values.values()), Fraction()) / (n - 1)
    if not variance:
        return result
    # Compute (2.80*s/sqrt(L)) directly, avoiding intermediate root rounding.
    square = Fraction(196, 25) * variance / n
    scaled = square * 10**12
    root = _isqrt(scaled.numerator // scaled.denominator)
    result.update(status="approximate", value=_number(Fraction(root, 10**6)))
    return result


def _band(pairs, *, seed, name):
    if pairs is None:
        return dict(status=_NO_AA, q0=None, scored_items=0, unstable_items=0,
                    wilson_95_ppm=None, assumption="assumes items change independently",
                    comparison=None, sensitivity=dict(status=_NO_AA, approximate=True, value=None,
                        life_count=0, discordant_items=0, exact_test_limit=_LIMIT))
    values, scored = _sample(pairs)
    unstable = sum(_differs(_record(a), _record(b)) for a, b, _ in scored)
    discordant = sum(d != 0 for _, _, d in scored)
    return dict(status="available", q0=_number(Fraction(unstable, len(scored))) if scored else None,
                scored_items=len(scored), unstable_items=unstable,
                wilson_95_ppm=_wilson(unstable, len(scored)),
                assumption="assumes items change independently",
                comparison=_stats(pairs, seed=seed, name=name),
                sensitivity=_sensitivity(values, discordant))


def _taxonomy(rows):
    counts = {}
    for row in rows:
        reason = _reason(row)
        failure = row["failure_class"] or (row["base_verdict"]
                                          if row["base_verdict"] != "PASS" else None)
        if failure or reason:
            key = row["cell_id"], row["stage"], failure or "", reason or ""
            counts[key] = counts.get(key, 0) + 1
    return [dict(cell_id=cell, stage=stage, failure=failure or None,
                 exclusion_reason=reason or None, count=count if not reason else 0,
                 excluded_count=count if reason else 0)
            for (cell, stage, failure, reason), count in sorted(counts.items())]


def _metrics(receipts):
    if receipts is None:
        return None
    if not isinstance(receipts, (tuple, list)) or len(receipts) != 2:
        raise DeveloperReportRefused("invalid_rows")
    a, b = receipts
    try:
        for receipt in receipts:
            validate("receipt", receipt)
    except (ValueError, TypeError) as error:
        raise DeveloperReportRefused("invalid_rows") from error
    def difference(x, y):
        return None if x is None or y is None else x - y
    roles = [{r["role"]: r for r in receipt["tokens_by_role"]} for receipt in receipts]
    return dict(scope=_SCOPE,
                wall_ms=(a["wall_end_ms"]-a["wall_start_ms"])-(b["wall_end_ms"]-b["wall_start_ms"]),
                requests=a["latency_summary"]["n"]-b["latency_summary"]["n"],
                store_growth_bytes=a["store_growth_bytes"]-b["store_growth_bytes"],
                tokens_by_role=[dict(role=role, **{k: roles[0].get(role, {}).get(k, 0)
                    - roles[1].get(role, {}).get(k, 0) for k in ("input", "output")})
                    for role in sorted(roles[0].keys() | roles[1].keys())],
                latency_summary={k: difference(a["latency_summary"][k], b["latency_summary"][k])
                                 for k in ("n", "p50", "p90", "p95", "max")})


def developer_report(current, previous, *, aa=None, receipts=None, seed):
    """Return validated JSON statistics from paired rows, without reading run directories.

    Extra row fields are ignored. Duplicate identities and conflicting cell/stage
    metadata are invalid rows. Fractions use score units (score_milli / 1000).
    Taxonomy exclusions are local to each run; statistical exclusions use both.
    Receipt totals cannot reliably identify their arm coverage and are all labelled.
    """
    if type(seed) is not str:
        raise DeveloperReportRefused("invalid_rows")
    pairs = _pair(current, previous, "items_mismatch")
    if aa is not None and (not isinstance(aa, (tuple, list)) or len(aa) != 2):
        raise DeveloperReportRefused("invalid_rows")
    noise = None if aa is None else _pair(*aa, "aa_prime:items_mismatch")
    cells = sorted({a["cell_id"] for a, _ in pairs}
                   | {a["cell_id"] for a, _ in noise or []})
    result = dict(label=_LABEL,
        cells=[dict(cell_id=cell,
                    diff=_stats([(a, b) for a, b in pairs if a["cell_id"] == cell],
                                seed=seed, name=cell),
                    aa=_band(None if noise is None else [(a, b) for a, b in noise
                                                        if a["cell_id"] == cell],
                             seed=seed, name="aa:" + cell)) for cell in cells],
        pooled=dict(diff=_stats(pairs, seed=seed, name="pooled"),
                    aa=_band(noise, seed=seed, name="aa:pooled")),
        operating_metrics=_metrics(receipts),
        failure_taxonomy=dict(current=_taxonomy([a for a, _ in pairs]),
                              previous=_taxonomy([b for _, b in pairs])))
    validate("developer_report", result)
    return result
