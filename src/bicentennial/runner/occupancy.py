"""Exact §11 lane accounting and breach classification for supplied spans.

This module does not schedule work or infer life spans from lane hours.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction

from bicentennial.runner.projection import LIFE_BOUND_MS, PAUSE_A, W_MAX_MS

SHARED = "__shared__"
_RUN_OF_RECORD = {"board": "board", "study": "board", "image": "image"}


def _integer(name: str, value: int, *, minimum: int | None = None) -> None:
    if type(value) is not int:
        raise TypeError(f"{name} requires an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")


def _name(name: str, value: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{name} requires a string")
    if not value:
        raise ValueError(f"{name} must not be empty")


@dataclass(frozen=True)
class LaneCapacity:
    """C-11 capacity; rate is supplied only where request rate binds."""

    name: str
    concurrency: int
    accounts: int
    rate_per_min: int | None = None
    runner_cap: int | None = None

    def __post_init__(self) -> None:
        _name("name", self.name)
        for name in ("concurrency", "accounts", "rate_per_min", "runner_cap"):
            value = getattr(self, name)
            if value is not None or name in ("concurrency", "accounts"):
                _integer(name, value, minimum=1)


@dataclass(frozen=True)
class WorkTerm:
    """One uniquely named term; request_ms is total upstream try time."""

    lane: str
    owner: str
    run: str
    kind: str
    request_ms: int
    n_req: int

    def __post_init__(self) -> None:
        for name in ("lane", "owner", "run", "kind"):
            _name(name, getattr(self, name))
        if self.run not in ("board", "study", "image"):
            raise ValueError("run must be board, study or image")
        _integer("request_ms", self.request_ms, minimum=0)
        _integer("n_req", self.n_req, minimum=0)


@dataclass(frozen=True)
class ArmLifeSpan:
    """Caller-supplied times on one clock, including the row's own time."""

    arm: str
    life: str
    replaying: bool
    block_first_ms: int
    first_request_ms: int
    last_ms: int
    own_ms: int

    def __post_init__(self) -> None:
        _name("arm", self.arm)
        _name("life", self.life)
        if type(self.replaying) is not bool:
            raise TypeError("replaying requires a bool")
        for name in ("block_first_ms", "first_request_ms", "last_ms", "own_ms"):
            _integer(name, getattr(self, name))
        if not self.block_first_ms <= self.first_request_ms <= self.last_ms:
            raise ValueError("span times must be in chronological order")
        if self.own_ms < 0:
            raise ValueError("own_ms must be nonnegative")


@dataclass(frozen=True)
class LaneHours:
    concurrency_h: Fraction
    rate_h: Fraction | None
    hours: Fraction
    bound: str


def lane_hours(lane: LaneCapacity, request_ms: int, n_req: int) -> LaneHours:
    """Return both §11 terms and their maximum; ties are bound by 'both'."""
    _integer("request_ms", request_ms, minimum=0)
    _integer("n_req", n_req, minimum=0)
    concurrency = lane.concurrency * lane.accounts
    if lane.runner_cap is not None:
        concurrency = min(concurrency, lane.runner_cap)
    concurrency_h = Fraction(request_ms, 3_600_000 * concurrency)
    rate_h = (Fraction(n_req, 60 * lane.rate_per_min * lane.accounts)
              if lane.rate_per_min is not None else None)
    if rate_h is None or concurrency_h > rate_h:
        return LaneHours(concurrency_h, rate_h, concurrency_h, "concurrency")
    if rate_h > concurrency_h:
        return LaneHours(concurrency_h, rate_h, rate_h, "rate")
    return LaneHours(concurrency_h, rate_h, concurrency_h, "both")


@dataclass(frozen=True)
class WorkBound:
    work_h: Fraction
    with_pause_h: Fraction
    limit_h: Fraction
    fits: bool


@dataclass(frozen=True)
class Projection:
    """Only used groups appear; work keys are (owner, lane, run).

    Occupancy keys are (lane, run of record), with study work counted in its
    board's run (PREREG-v0.4 §11). Work bounds stay per board, study and Image.
    SHARED is reserved and never a work key.
    The returned dictionaries are fresh for each call.
    """

    work: dict[tuple[str, str, str], LaneHours]
    occupancy: dict[tuple[str, str], LaneHours]
    work_bounds: dict[tuple[str, str, str], WorkBound]


def project(lanes: Iterable[LaneCapacity], terms: Iterable[WorkTerm]) -> Projection:
    """Aggregate counts before applying lane capacity, counting each term once.

    Occupancy keys are (lane, run of record), with study work counted in its
    board's run (PREREG-v0.4 §11). Work bounds stay per board, study and Image.
    Duplicate lane names, unknown lanes and duplicate term identities are errors.
    Neither lanes nor runs are summed to enforce the work bound.
    """
    capacities = {}
    for lane in lanes:
        if lane.name in capacities:
            raise ValueError(f"duplicate lane: {lane.name}")
        capacities[lane.name] = lane

    work_totals: dict[tuple[str, str, str], tuple[int, int]] = {}
    occupancy_totals: dict[tuple[str, str], tuple[int, int]] = {}
    seen = set()
    for term in terms:
        if term.lane not in capacities:
            raise ValueError(f"unknown lane: {term.lane}")
        identity = (term.lane, term.owner, term.run, term.kind)
        if identity in seen:
            raise ValueError(f"duplicate work term: {identity}")
        seen.add(identity)
        occupancy_key = (term.lane, _RUN_OF_RECORD[term.run])
        request_ms, n_req = occupancy_totals.get(occupancy_key, (0, 0))
        occupancy_totals[occupancy_key] = (request_ms + term.request_ms, n_req + term.n_req)
        if term.owner != SHARED:
            work_key = (term.owner, term.lane, term.run)
            request_ms, n_req = work_totals.get(work_key, (0, 0))
            work_totals[work_key] = (request_ms + term.request_ms, n_req + term.n_req)

    work = {key: lane_hours(capacities[key[1]], *totals)
            for key, totals in work_totals.items()}
    occupancy = {key: lane_hours(capacities[key[0]], *totals)
                 for key, totals in occupancy_totals.items()}
    limit_h = Fraction(W_MAX_MS, 3_600_000)
    bounds = {}
    for key, hours in work.items():
        with_pause_h = hours.hours * (1 + PAUSE_A)
        bounds[key] = WorkBound(hours.hours, with_pause_h, limit_h, with_pause_h <= limit_h)
    return Projection(work, occupancy, bounds)


@dataclass(frozen=True)
class Breach:
    cause: str | None
    label: str | None
    bound_ms: int | None


def classify_breach(span: ArmLifeSpan) -> Breach:
    """Classify start-window breaches first, then life breaches, with strict >."""
    if not span.replaying:
        return Breach(None, None, None)
    if span.first_request_ms - span.block_first_ms > LIFE_BOUND_MS:
        return Breach("start_window", "BLOCKED", span.block_first_ms + LIFE_BOUND_MS)
    if span.last_ms - span.first_request_ms > LIFE_BOUND_MS:
        label = "SYSTEM_FAILURE" if span.own_ms > LIFE_BOUND_MS else "BLOCKED"
        return Breach("life_bound", label, span.first_request_ms + LIFE_BOUND_MS)
    return Breach(None, None, None)
