"""Exact PREREG v0.4 lane work; a chain lower bound is not occupancy."""

from dataclasses import asdict, dataclass, fields, replace
from fractions import Fraction
from math import ceil, floor

from bicentennial.canon import milli

LIFE_BOUND_MS = 86_400_000
W_MAX_MS = 345_600_000
PAUSE_A = Fraction(1, 4)
Q = 3
N_ROB, N_ROB_CUT = 8, 4
N_L_BAR5, N_L_CUT = 48, 24
B_PLAN, B_CUT = 150, 100
UNDETERMINED = "undetermined: no occupancy projection"


@dataclass(frozen=True)
class Cost:
    requests: int | Fraction = 0
    upstream_ms: int | Fraction = 0
    wall_ms: int | Fraction = 0
    held_ms: int | Fraction = 0
    input_tokens: int | Fraction = 0
    output_tokens: int | Fraction = 0

    def __post_init__(self):
        if any(type(v) is not int and not isinstance(v, Fraction) for v in asdict(self).values()):
            raise TypeError("cost requires exact numbers")

    def __add__(self, other):
        if not isinstance(other, Cost):
            return NotImplemented
        return Cost(**{f.name: getattr(self, f.name) + getattr(other, f.name) for f in fields(self)})

    def __mul__(self, k):
        if type(k) is not int and not isinstance(k, Fraction):
            raise TypeError("cost multiplier requires an exact number")
        return Cost(**{f.name: getattr(self, f.name) * k for f in fields(self)})

    __rmul__ = __mul__

    def to_obj(self):
        return {k: round(v) for k, v in asdict(self).items()}


def cmax(a, b):
    return Cost(**{f.name: max(getattr(a, f.name), getattr(b, f.name)) for f in fields(a)})


@dataclass(frozen=True)
class Lane:
    name: str
    rate_per_min: int
    concurrency_per_account: int
    accounts: int

    def __post_init__(self):
        if any(type(v) is not int or v <= 0 for v in
               (self.rate_per_min, self.concurrency_per_account, self.accounts)):
            raise ValueError("lane capacity requires positive integers")


def lane_ms(cost, lane):
    return max(Fraction(cost.upstream_ms, lane.concurrency_per_account * lane.accounts),
               Fraction(cost.requests * 60_000, lane.rate_per_min * lane.accounts))


@dataclass(frozen=True, kw_only=True)
class Terms:
    R: Cost
    e_probe: Cost
    critical_path_ms: int | Fraction
    b: int = B_PLAN
    f: Fraction = Fraction(1, 2)
    ctrl: int = 1
    R_cap: Cost | None = None
    r_share: Fraction = Fraction(3, 20)
    p_share: Fraction = Fraction(1, 4)
    pk_share: Fraction = Fraction(1, 5)
    pw_share: Fraction = Fraction(1, 10)
    R_B: Cost | None = None
    pb_share: int | Fraction = 1
    delta_w: int = 1
    C_learn: Cost | None = None
    C_erase: Cost | None = None


def P(t):
    return t.e_probe * t.b * (1 + t.ctrl)


def n_keep(n_L):
    return max(6, ceil(Fraction(n_L, 4)))


def board(t, n_L):
    probes, rc = P(t), cmax(t.R_cap or t.R, t.R)
    return (t.R * (1 + t.f) + probes * 2) * n_L + (rc * (1 + t.f) + probes * 2) * n_keep(n_L)


def study(t, n_L, n_rob):
    probes, rc = P(t), cmax(t.R_cap or t.R, t.R)
    cells = (t.R * t.r_share + probes * t.p_share) * (3 * 2 * Q)
    replication = (t.R_B or t.R) * (1 + t.f) + probes * t.pb_share * 2
    swap = (t.R * (1 + t.f) + probes * t.pw_share * 2) * t.delta_w
    added = (t.C_learn or Cost()) + (t.C_erase or Cost())
    curve = (rc * (1 + t.f) + probes * t.pk_share * 2) * (2 * min(n_rob, n_keep(n_L)))
    return (cells + replication + swap + probes * Fraction(1, 5) + added) * n_rob + curve


def fit(t, lane, *, n_L=N_L_BAR5, n_rob=N_ROB):
    out = {}
    for name, cost in (("board", board(t, n_L)), ("study", study(t, n_L, n_rob))):
        time = Fraction(cost.upstream_ms, lane.concurrency_per_account * lane.accounts)
        rate = Fraction(cost.requests * 60_000, lane.rate_per_min * lane.accounts)
        work = lane_ms(cost, lane)
        out[name] = dict(cost=cost.to_obj(), time_mh=milli(time / 3_600_000),
                         rate_mh=milli(rate / 3_600_000), work_mh=milli(work / 3_600_000),
                         with_a_mh=milli(work * (1 + PAUSE_A) / 3_600_000),
                         fits=work * (1 + PAUSE_A) <= W_MAX_MS)
    out["life"] = dict(critical_path_lower_bound_mh=milli(Fraction(t.critical_path_ms, 3_600_000)),
                       lower_bound_exceeds_bound=t.critical_path_ms > LIFE_BOUND_MS, fits=UNDETERMINED)
    out["missing"] = [name for name in ("C_learn", "C_erase") if getattr(t, name) is None]
    out["fits"] = UNDETERMINED
    return out


CUTS = (("none", B_PLAN, N_ROB, N_L_BAR5),
        ("b=100", B_CUT, N_ROB, N_L_BAR5),
        ("+ n_rob=4", B_CUT, N_ROB_CUT, N_L_BAR5),
        ("+ n_L=24", B_CUT, N_ROB_CUT, N_L_CUT))


def cut_order(t, lane):
    rows = [dict(cut=name, b=b, n_L=n_L, n_rob=n_rob,
                 **fit(replace(t, b=b), lane, n_L=n_L, n_rob=n_rob))
            for name, b, n_rob, n_L in CUTS]
    first_work = next((r["cut"] for r in rows if r["board"]["fits"] and r["study"]["fits"]), None)
    return dict(rows=rows, first_fit=None, first_work_fit=first_work, reason=UNDETERMINED)


def breakeven(t, lane, *, n_L, n_rob, bound_ms=W_MAX_MS, a=PAUSE_A):
    """Additional requests per study life, at that study's own mean request time."""
    if n_rob <= 0 or a < 0 or bound_ms < 0:
        raise ValueError("invalid study bound")
    cost = study(t, n_L, n_rob)
    allowed = Fraction(bound_ms, 1 + a)
    rate_remaining = allowed * lane.rate_per_min * lane.accounts / 60_000 - cost.requests
    remaining = rate_remaining / n_rob
    if cost.upstream_ms:
        mean = Fraction(cost.upstream_ms, cost.requests)
        service_remaining = allowed * lane.concurrency_per_account * lane.accounts - cost.upstream_ms
        remaining = min(remaining, service_remaining / (mean * n_rob))
    return max(0, floor(remaining))


def stats(xs):
    values = sorted(xs)
    if any(type(x) is not int for x in values):
        raise TypeError("stats requires integers")
    n = len(values)
    if not n:
        return {"n": 0}
    return dict(n=n, mean=round(Fraction(sum(values), n)), p50=values[ceil(Fraction(n, 2)) - 1],
                p90=values[ceil(Fraction(9 * n, 10)) - 1], min=values[0], max=values[-1])


def role_costs(rows, blobs, sessions: dict[str, int]) -> dict[int, dict[str, Cost]]:
    result = {}
    for row in rows:
        if row.get("type") != "request" or row.get("attempt_id") not in sessions:
            continue
        roles = result.setdefault(sessions[row["attempt_id"]], {})
        for upstream in row.get("upstream", []):
            role = upstream["role"]
            key = role if role != row["role"] else f"{role}/{row['subrole']}"
            diags = upstream.get("diagnostics", [])
            tries = [d for d in diags if d.get("kind") == "try" and d.get("sent") is True]
            usage = (blobs[upstream["resp"]].get("usage") or {}) if upstream.get("resp") else {}
            tokens = [usage.get(k) if type(usage.get(k)) is int else 0
                      for k in ("prompt_tokens", "completion_tokens")]
            cost = Cost(requests=len(tries), upstream_ms=sum(d.get("t_ms", 0) for d in tries),
                        held_ms=sum(d.get("held_ms", 0) for d in diags if d.get("kind") == "hold"),
                        input_tokens=tokens[0], output_tokens=tokens[1])
            roles[key] = roles.get(key, Cost()) + cost
    return result
