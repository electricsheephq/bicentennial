"""Exact integer wild-bootstrap functionals, counts and certification."""

from dataclasses import dataclass, field
from fractions import Fraction
from math import gcd, lcm

from bicentennial import keyed
from bicentennial.stats import certify, tcal

UNCALIBRATED_PPM = 50_000


def _pairs(pairs):
    pairs = tuple(pairs)
    if any(not isinstance(p, str) for p in pairs) or len(set(pairs)) != len(pairs):
        raise ValueError("pairs must be unique strings")
    return pairs


def _draws(draws):
    if type(draws) is not int or draws < 1:
        raise ValueError("draws must be an integer >= 1")


@dataclass(frozen=True)
class WeightCache:
    pairs: tuple[str, ...]
    draws: int
    bits: tuple[int, ...]
    colsum: tuple[int, ...]
    gram: tuple[tuple[int, ...], ...]
    _packed: dict[int, tuple[int, ...]] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def _from_bits(cls, pairs, draws, bits):
        return cls(pairs, draws, bits, tuple(2 * b.bit_count() - draws for b in bits),
                   tuple(tuple(draws - 2 * (a ^ b).bit_count() for b in bits) for a in bits))

    @classmethod
    def from_seed(cls, pairs, seed: str, name: str, draws: int) -> "WeightCache":
        pairs = _pairs(pairs)
        _draws(draws)
        bits = tuple(sum((keyed.draw(seed, ("stats", "certify", p), b, name) & 1) << b
                         for b in range(draws)) for p in pairs)
        return cls._from_bits(pairs, draws, bits)

    @classmethod
    def from_matrix(cls, pairs, rows) -> "WeightCache":
        pairs = _pairs(pairs)
        rows = tuple(tuple(row) for row in rows)
        _draws(len(rows))
        if any(len(row) != len(pairs) or any(type(v) is not int or v not in (-1, 1)
                                            for v in row) for row in rows):
            raise ValueError("weights must supply +1 or -1 for every pair")
        bits = tuple(sum(int(row[p] == 1) << b for b, row in enumerate(rows))
                     for p in range(len(pairs)))
        return cls._from_bits(pairs, len(rows), bits)

    def packed(self, lane_bits: int) -> tuple[int, ...]:
        if lane_bits not in self._packed:
            # Byte expansion avoids repeated growth of a B*L-bit accumulator.
            width = (lane_bits + 7) // 8
            if lane_bits % 8 == 0:
                self._packed[lane_bits] = tuple(int.from_bytes(b"".join(
                    ((bits >> b) & 1).to_bytes(width, "little") for b in range(self.draws)
                ), "little") for bits in self.bits)
            else:
                self._packed[lane_bits] = tuple(sum(((bits >> b) & 1) << (lane_bits * b)
                                                   for b in range(self.draws)) for bits in self.bits)
        return self._packed[lane_bits]


@dataclass(frozen=True)
class Functional:
    coef: tuple[int, ...]
    center: int
    den: int
    units: int


def _reduce(coef, center, den, units):
    g = gcd(center, den, *coef)
    return Functional(tuple(c // g for c in coef), center // g, den // g, units)


def _required(cs, required, w):
    required = tuple(sorted(required))
    if not required or len(set(required)) != len(required):
        raise ValueError("required cells must be nonempty and unique")
    if any(k not in cs.cells for k in required):
        raise ValueError("missing required cell metadata")
    for p in cs.pairs:
        if p not in w.pairs:
            raise ValueError(f"pair {p} has no weights")
    return required


def margin_functionals(cs, required, w: WeightCache):
    required = _required(cs, required, w)
    result, joint_pairs = [], set()
    for k in required:
        entries = {p: cs.entries[k, p] for p in cs.pairs}
        scored = {p: e for p, e in entries.items() if e.n_valid}
        valid = {p: e for p, e in entries.items() if e.control_valid and e.n_control}
        s, v = len(scored), len(valid)
        if not s or not v:
            result.append((k, None))
            continue
        support = scored.keys() | valid.keys()
        joint_pairs.update(support)
        q = len(scored.keys() - valid.keys())
        n = lcm(*(e.n_valid for e in scored.values()), *(e.n_control for e in valid.values()))
        alpha = {p: e.s_sum * (n // e.n_valid) for p, e in scored.items()}
        gamma = {p: (e.f_sum + e.c_sum) * (n // e.n_control) for p, e in valid.items()}
        a, g = sum(alpha.values()), sum(gamma.values())
        coef = tuple(
            (2 * v * v * (s * alpha[p] - a) if p in scored else 0)
            - (s * (int(p in scored) * v + q) * (v * gamma[p] - g) if p in valid else 0)
            for p in w.pairs
        )
        result.append((k, _reduce(coef, 2 * s * v * v * a - s * s * v * g,
                                  20 * n * s * s * v * v, len(support))))
    joint = None
    if all(f is not None for _, f in result):
        ld = lcm(*(f.den for _, f in result))
        joint = _reduce(tuple(sum(f.coef[p] * (ld // f.den) for _, f in result)
                              for p in range(len(w.pairs))),
                        sum(f.center * (ld // f.den) for _, f in result),
                        len(result) * ld, len(joint_pairs))
    return tuple(result), joint


def gap_functionals(cs, required, w: WeightCache):
    required = _required(cs, required, w)
    result = []
    for k in required:
        valid = {p: cs.entries[k, p] for p in cs.pairs
                 if cs.entries[k, p].control_valid and cs.entries[k, p].n_control}
        v = len(valid)
        if not v:
            result.append((k, None))
            continue
        n = lcm(*(e.n_control for e in valid.values()))
        delta = {p: (e.c_sum - e.f_sum) * (n // e.n_control) for p, e in valid.items()}
        total = sum(delta.values())
        result.append((k, _reduce(tuple(v * delta[p] - total if p in valid else 0
                                        for p in w.pairs),
                                  v * total, 10 * n * v * v, v)))
    return tuple(result)


def _validate(f, w):
    if len(f.coef) != len(w.pairs) or f.den <= 0:
        raise ValueError("functional does not match the weight cache")


def _lanes(f, w, threshold):
    _validate(f, w)
    m = sum(abs(c) for c in f.coef)
    q = -((-(threshold * f.den - f.center + sum(f.coef))) // 2)
    width = 64 * ((m.bit_length() + 2 + 63) // 64)
    return m, q, width


def count_below(f: Functional, w: WeightCache, threshold: int) -> int:
    m, q, width = _lanes(f, w, threshold)
    if q > m:
        return w.draws
    if q <= -m:
        return 0
    ones = ((1 << (width * w.draws)) - 1) // ((1 << width) - 1)
    high = 1 << (width - 1)
    value = sum(c * col for c, col in zip(f.coef, w.packed(width), strict=True))
    value += (high - q) * ones
    return w.draws - (value & (high * ones)).bit_count()


def moments(f: Functional, w: WeightCache) -> tuple[int, int]:
    _validate(f, w)
    return (sum(c * col for c, col in zip(f.coef, w.colsum, strict=True)),
            sum(a * b * w.gram[p][q] for p, a in enumerate(f.coef)
                for q, b in enumerate(f.coef)))


def se2(f: Functional, w: WeightCache) -> Fraction:
    total, square = moments(f, w)
    return Fraction(w.draws * square - total * total, w.draws**2 * f.den**2)


def screen(f: Functional, w: WeightCache, threshold: int, indices: tuple[int, ...]):
    total, square = moments(f, w)
    mu = Fraction(total, w.draws)
    variance = Fraction(square, w.draws) - mu * mu
    t = threshold * f.den - f.center
    a2 = (mu - t)**2
    if t < mu and w.draws * variance < (min(indices) + 1) * (variance + a2):
        return True
    if t > mu and w.draws * a2 > max(indices) * (variance + a2):
        return False
    return None


def _indices(f, w):
    return (tcal.index(w.draws, tcal.ppm(tcal.ONE_SIDED_PPM, f.units)),
            tcal.index(w.draws, UNCALIBRATED_PPM))


def _passes(f, w, threshold):
    indices = _indices(f, w)
    screened = screen(f, w, threshold, indices)
    if screened is not None:
        return screened, screened
    count = count_below(f, w, threshold)
    return tuple(count <= i for i in indices)


def _admissions(cs, w, required, *, use_screen):
    result = []
    for k, f in gap_functionals(cs, required, w):
        if f is None or 4 * f.units < 3 * len(cs.pairs):
            value = None
        else:
            index = _indices(f, w)[0]
            passed = screen(f, w, 30, (index,)) if use_screen else None
            if passed is None:
                passed = count_below(f, w, 30) <= index
            value = "ADMITTED" if passed else "NOT_ADMITTED"
        result.append((k, value))
    return tuple(result)


def admissions(cs, w: WeightCache, *, required):
    return _admissions(cs, w, required, use_screen=True)


@dataclass(frozen=True)
class Decision:
    outcome: str
    certified: tuple[bool, bool]
    se2: tuple[tuple[str, Fraction | None], ...]
    reasons: tuple[str, ...] | None
    lower: tuple[tuple[str, Fraction | None, Fraction | None], ...] | None
    admissions: tuple[tuple[str, str | None], ...]


def _lower(f, w):
    if f is None:
        return None, None
    _, _, width = _lanes(f, w, 0)
    ones = ((1 << (width * w.draws)) - 1) // ((1 << width) - 1)
    high = 1 << (width - 1)
    # S_b = 2 D_b - sum(coef); offset signed S lanes before unpacking.
    packed = 2 * sum(c * col for c, col in zip(f.coef, w.packed(width), strict=True))
    packed += (high - sum(f.coef)) * ones
    mask = (1 << width) - 1
    values = sorted(f.center + ((packed >> (width * b)) & mask) - high
                    for b in range(w.draws))
    return tuple(Fraction(values[i], f.den) for i in _indices(f, w))


def decide(cs, w: WeightCache, *, required, se_bound: Fraction, n_lives: int, b: int,
           mode: str = "decide", admissions=None) -> Decision:
    required = _required(cs, required, w)
    if mode not in ("decide", "full"):
        raise ValueError('mode must be "decide" or "full"')
    bounds = certify.Bounds(n_lives, b, se_bound)
    certify.Board("season", "text", True, n_lives, b)
    if admissions is None:
        admissions = _admissions(cs, w, required, use_screen=mode != "full")
    admissions = tuple(admissions)
    if len(admissions) != len(required) or sorted(k for k, _ in admissions) != list(required):
        raise ValueError("missing required cell metadata")
    adm = dict(admissions)
    if any(v not in ("ADMITTED", "NOT_ADMITTED", None) for v in adm.values()):
        raise ValueError("unknown admission")
    admissions = tuple((k, adm[k]) for k in required)
    cells, joint = margin_functionals(cs, required, w)
    variances = tuple((k, se2(f, w) if f is not None else None) for k, f in cells)
    impossible, blocks, deferrals = [], [], []
    for k, variance in variances:
        entries = [cs.entries[k, p] for p in cs.pairs]
        v = sum(e.control_valid and e.n_control > 0 for e in entries)
        s = sum(e.n_valid > 0 for e in entries)
        if variance is not None and variance > bounds.se**2:
            impossible.append(f"se:{k}")
        if cs.coverage[k] < Fraction(95, 100):
            (blocks if cs.shortfall[k] == "system" else deferrals).append(
                f"coverage_{cs.shortfall[k]}:{k}")
        if 4 * v < 3 * len(cs.pairs):
            deferrals.append(f"blocked:{k}")
        if adm[k] != "ADMITTED":
            deferrals.append(f"not_admitted:{k}" if adm[k] == "NOT_ADMITTED"
                             else f"admission_undefined:{k}")
        if not s:
            deferrals.append(f"empty_scores:{k}")
        if not v:
            deferrals.append(f"empty_controls:{k}")
    earlier = (("NO_CERTIFICATE", impossible) if impossible else
               ("NOT_CERTIFIED", blocks) if blocks else
               ("DEFERRED", deferrals) if deferrals else None)
    if mode == "decide" and earlier:
        return Decision(earlier[0], (False, False), variances, None, None, admissions)
    lowers = None
    failures = []
    if mode == "full":
        lowers = tuple((k, *_lower(f, w)) for k, f in (("mean", joint), *cells))
        passed = [True, True]
        for i, (k, cal, unc) in enumerate(lowers):
            threshold = -10 if i else 0
            if cal is None or cal < threshold:
                passed[0] = False
            if unc is None or unc < threshold:
                passed[1] = False
            if cal is not None and cal < threshold:
                failures.append(f"r_b:{k}" if i else "r_a")
    else:
        passed = list(_passes(joint, w, 0))
        if any(passed):
            for _, f in cells:
                cell_pass = _passes(f, w, -10)
                passed = [a and c for a, c in zip(passed, cell_pass, strict=True)]
                if not any(passed):
                    break
    if earlier:
        outcome, reasons = earlier
        passed = [False, False]
    else:
        outcome = "CERTIFIED" if passed[0] else "NOT_CERTIFIED"
        reasons = failures
    return Decision(outcome, tuple(passed), variances,
                    tuple(reasons) if mode == "full" else None, lowers, admissions)
