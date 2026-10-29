"""Exact chain-slot schedules and checkpoint dispatch for OC simulation."""

from dataclasses import dataclass, replace
from fractions import Fraction
from heapq import heappop, heappush
from math import lcm

from bicentennial.keyed import draw, shuffle, uniform_int
from bicentennial.runner.dispatch import ArmEvents, PassOver, dispatch
from bicentennial.runner.occupancy import (
    ArmLifeSpan,
    Breach,
    LaneCapacity,
    classify_breach,
)
from bicentennial.runner.projection import LIFE_BOUND_MS

KINDS = ("base", "stress_slow", "stress_fast")
BRANCHES = ("B0", "B1")
LANES = ("pinned", "swap")
SYSTEM = "S"
PROBE_ONLY = ("C", "F")
STRESS_FACTOR = Fraction(3, 2)
CAUSES = ("start_window", "life_bound", "failed", "blocked")
STATUSES = ("OK", "SYSTEM_FAILURE", "BLOCKED")


@dataclass(frozen=True)
class LifeSpec:
    life: str
    b0_tokens: tuple[int, ...]
    b1_tokens: tuple[int, ...]
    fork: int
    swap: int
    b0_probe_tokens: tuple[int, ...]
    b1_probe_tokens: tuple[int, ...]


@dataclass(frozen=True)
class Row:
    row: str
    rate: int | Fraction


@dataclass(frozen=True)
class Capacity:
    pinned: int
    swap: int


@dataclass(frozen=True)
class PassOverRates:
    failed: int | Fraction
    blocked: int | Fraction


@dataclass(frozen=True)
class ScheduleDesign:
    lives: tuple[LifeSpec, ...]
    rows: tuple[Row, ...]
    checkpoints: tuple[int, ...]
    capacity: Capacity
    passover: PassOverRates
    control_failure: int | Fraction
    system_rate: int | Fraction | None = None
    system_passovers: bool = True


@dataclass(frozen=True)
class Segment:
    lane: str
    first: int
    last: int
    duration_ms: int
    session_offset: tuple[tuple[int, int], ...]
    arrival_offset: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class Layout:
    b0: tuple[Segment, ...]
    b1: tuple[Segment, ...]
    own_ms: int


@dataclass(frozen=True)
class Prepared:
    design: ScheduleDesign
    layouts: dict[tuple[str, bool, str], Layout]


@dataclass(frozen=True)
class Draws:
    arm_order: dict[str, tuple[str, ...]]
    stress_order: tuple[str, ...]
    stops: dict[tuple[str, str], tuple[str, int]]
    control_failed: frozenset[tuple[str, str]]
    dispatch_seed: str
    step_block: int


@dataclass(frozen=True)
class ArmLife:
    row: str
    life: str
    slow: bool
    first_ms: int | None
    end_ms: int | None
    last_ms: int | None
    own_ms: int
    cause: str | None
    label: str | None
    breach: Breach | None


@dataclass(frozen=True)
class Release:
    release_ms: int
    followed: str | None
    arrival_ms: int | None
    lag_ms: int
    unmatched: bool


@dataclass(frozen=True)
class Schedule:
    kind: str
    slow: frozenset[str]
    block_first: tuple[int, ...]
    sent: dict[tuple[str, str, str, int], int]
    system: dict[tuple[str, str, int], str]
    controls: dict[tuple[str, str, int], Release]
    control_failed: frozenset[tuple[str, str]]
    arm_lives: dict[tuple[str, str], ArmLife]
    post_swap: dict[tuple[str, int], bool]
    t1_ms: int


def _exact(value: int | Fraction) -> bool:
    return type(value) is int or isinstance(value, Fraction)


def _validate_design(design: ScheduleDesign) -> None:
    ids = [life.life for life in design.lives]
    if not ids or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("lives must be nonempty with unique str ids")
    checkpoints = design.checkpoints
    if (not checkpoints or any(type(c) is not int or c < 1 for c in checkpoints)
            or any(a >= b for a, b in zip(checkpoints[:-1], checkpoints[1:], strict=True))):
        raise ValueError("checkpoints must be strictly increasing ints >= 1")
    for life in design.lives:
        prefix = f"life {life.life}: "
        if any(type(n) is not int or n < 1 for n in life.b0_tokens + life.b1_tokens):
            raise ValueError(prefix + "session tokens must be ints >= 1")
        for probes in (life.b0_probe_tokens, life.b1_probe_tokens):
            if (len(probes) != len(checkpoints)
                    or any(type(n) is not int or n < 0 for n in probes)):
                raise ValueError(prefix + "probe tokens must be len(checkpoints) ints >= 0")
        if type(life.fork) is not int or not 1 <= life.fork <= checkpoints[0]:
            raise ValueError(prefix + "need 1 <= fork <= first checkpoint")
        n = len(life.b0_tokens)
        if len(life.b1_tokens) != n - life.fork + 1:
            raise ValueError(prefix + "b1_tokens must cover sessions fork..N")
        if type(life.swap) is not int or not 2 <= life.swap <= n:
            raise ValueError(prefix + "need 2 <= swap <= sessions")
        if checkpoints[-1] > n:
            raise ValueError(prefix + "checkpoints exceed its sessions")
    ids = [row.row for row in design.rows]
    if (not ids or any(not isinstance(x, str) or x in (*PROBE_ONLY, SYSTEM) for x in ids)
            or len(set(ids)) != len(ids)):
        raise ValueError("rows must be nonempty unique str ids other than F, C and S")
    for row in design.rows:
        if not _exact(row.rate) or row.rate <= 0:
            raise ValueError(f"row {row.row}: rate must be a positive int or Fraction")
    if design.system_rate is not None and (
        not _exact(design.system_rate) or design.system_rate <= 0
    ):
        raise ValueError("system rate must be a positive int or Fraction")
    if any(type(n) is not int or n < 1
           for n in (design.capacity.pinned, design.capacity.swap)):
        raise ValueError("capacity slots must be ints >= 1")
    rates = (design.passover.failed, design.passover.blocked)
    if any(not _exact(r) or not 0 <= r <= 1 for r in rates) or sum(rates) > 1:
        raise ValueError("pass-over rates must be Fractions in [0, 1] with sum <= 1")
    if not _exact(design.control_failure) or not 0 <= design.control_failure <= 1:
        raise ValueError("control failure rate must be a Fraction in [0, 1]")
    if type(design.system_passovers) is not bool:
        raise ValueError("system_passovers must be a bool")


def session_ms(rate: int | Fraction, tokens: int) -> int:
    """Ceil each task independently, after applying its effective rate."""
    if type(tokens) is not int or tokens < 0:
        raise ValueError("tokens must be an int >= 0")
    if not _exact(rate) or rate <= 0:
        raise ValueError("rate must be a positive int or Fraction")
    return -((-rate.numerator * tokens) // rate.denominator)


def chain_slots(lane: LaneCapacity, reserve: int = 0) -> int:
    if lane.rate_per_min is not None:
        raise ValueError(f"rate-bound lane {lane.name}: slots need an owner ruling")
    slots = lane.concurrency * lane.accounts
    if lane.runner_cap is not None:
        slots = min(slots, lane.runner_cap)
    if type(reserve) is not int or reserve < 0 or slots - reserve < 1:
        raise ValueError("reserve must leave at least one chain slot")
    return slots - reserve


def _segments(life: LifeSpec, checkpoints: tuple[int, ...], rate: int | Fraction,
              branch: str) -> tuple[Segment, ...]:
    first = 1 if branch == "B0" else life.fork
    tokens = life.b0_tokens if branch == "B0" else life.b1_tokens
    probes = dict(zip(checkpoints, life.b0_probe_tokens if branch == "B0"
                      else life.b1_probe_tokens, strict=True))
    segments = []
    for lane, start, stop in (("pinned", first, life.swap - 1),
                              ("swap", max(first, life.swap), len(life.b0_tokens))):
        if start > stop:
            continue
        duration = 0
        sessions, arrivals = [], []
        for s in range(start, stop + 1):
            sessions.append((s, duration))
            duration += session_ms(rate, tokens[s - first])
            if s in probes:
                arrivals.append((s, duration))
                duration += session_ms(rate, probes[s])
        segments.append(Segment(lane, start, stop, duration, tuple(sessions), tuple(arrivals)))
    return tuple(segments)


def prepare(design: ScheduleDesign) -> Prepared:
    """Resolve S's rate and cache every row, speed and life's task layout."""
    _validate_design(design)
    if design.system_rate is None:
        design = replace(design, system_rate=max(row.rate for row in design.rows))
    rates = {row.row: row.rate for row in design.rows}
    rates[SYSTEM] = design.system_rate
    layouts = {}
    for row in sorted(rates):
        for slow in (False, True):
            rate = rates[row] * (STRESS_FACTOR if slow else 1)
            for life in sorted(design.lives, key=lambda item: item.life):
                b0 = _segments(life, design.checkpoints, rate, "B0")
                b1 = _segments(life, design.checkpoints, rate, "B1")
                prefix = 0
                for segment in b0:
                    offsets = dict(segment.session_offset)
                    if life.fork in offsets:
                        prefix += offsets[life.fork]
                        break
                    prefix += segment.duration_ms
                own = max(sum(s.duration_ms for s in b0),
                          prefix + sum(s.duration_ms for s in b1))
                layouts[row, slow, life.life] = Layout(b0, b1, own)
    return Prepared(design, layouts)


def layout(prepared: Prepared, row: str, life: str, slow: bool) -> Layout:
    return prepared.layouts[row, slow, life]


def draw_all(prepared: Prepared, seed: str, rep: int) -> Draws:
    """Draw once per replicate, with no schedule kind or drift case in a key."""
    if not isinstance(seed, str) or type(rep) is not int or rep < 0:
        raise ValueError("seed must be str and rep an int >= 0")
    design = prepared.design
    roster = sorted(row.row for row in design.rows)
    rows = sorted([*roster, SYSTEM])
    lives = sorted(design.lives, key=lambda item: item.life)
    arm_order = {life.life: tuple(shuffle(seed, ("ocsim", "arm-order", life.life),
                                         rep, "arm-order", rows)) for life in lives}
    stress = tuple(shuffle(seed, ("ocsim", "stress"), rep, "stress", roster))
    failed, blocked = Fraction(design.passover.failed), Fraction(design.passover.blocked)
    denominator = lcm(failed.denominator, blocked.denominator)
    stops = {}
    for row in rows:
        for life in lives:
            unit = ("ocsim", "passover", row, life.life)
            u = uniform_int(seed, unit, rep, "passover", 0, denominator - 1)
            session = uniform_int(seed, unit, rep, "passover-session", 1, len(life.b0_tokens))
            cause = ("failed" if u < failed * denominator else
                     "blocked" if u < (failed + blocked) * denominator else None)
            if cause is not None and (row != SYSTEM or design.system_passovers):
                stops[row, life.life] = (cause, session)
    rate = Fraction(design.control_failure)
    controls = frozenset(
        (arm, life.life) for arm in PROBE_ONLY for life in lives
        if uniform_int(seed, ("ocsim", "control-infra", arm, life.life), rep,
                       "control-infra", 0, rate.denominator - 1) < rate.numerator
    )
    dispatch_seed = "ocsim-dispatch:%016x" % draw(
        seed, ("ocsim", "dispatch"), rep, "dispatch-seed"
    )
    step = uniform_int(seed, ("ocsim", "step"), rep, "step-block", 0, len(lives) - 1)
    return Draws(arm_order, stress, stops, controls, dispatch_seed, step)


def _permutation(values: tuple[str, ...], expected: set[str]) -> bool:
    return (len(values) == len(expected) and all(isinstance(v, str) for v in values)
            and set(values) == expected)


def _validate_draws(prepared: Prepared, draws: Draws) -> None:
    design = prepared.design
    roster = {row.row for row in design.rows}
    rows = roster | {SYSTEM}
    lives = {life.life: life for life in design.lives}
    for life in sorted(lives):
        if life not in draws.arm_order or not _permutation(draws.arm_order[life], rows):
            raise ValueError(f"arm order for {life} must permute every row")
    if not _permutation(draws.stress_order, roster):
        raise ValueError("stress order must permute the roster rows")
    for (row, life), stop in draws.stops.items():
        if (row not in rows or life not in lives or not isinstance(stop, tuple)
                or len(stop) != 2 or stop[0] not in ("failed", "blocked")
                or type(stop[1]) is not int or not 1 <= stop[1] <= len(lives[life].b0_tokens)):
            raise ValueError(f"bad stop for {row} {life}")
    for arm, life in draws.control_failed:
        if arm not in PROBE_ONLY or life not in lives:
            raise ValueError(f"bad control failure: {arm} {life}")
    if type(draws.step_block) is not int or not 0 <= draws.step_block < len(lives):
        raise ValueError("step block out of range")


def slow_rows(prepared: Prepared, kind: str, draws: Draws) -> frozenset[str]:
    if kind not in KINDS:
        raise ValueError(f"unknown schedule kind: {kind}")
    _validate_draws(prepared, draws)
    h = (len(prepared.design.rows) + 1) // 2
    if kind == "stress_slow":
        return frozenset((SYSTEM, *draws.stress_order[:h - 1]))
    if kind == "stress_fast":
        return frozenset(draws.stress_order[:h])
    return frozenset()


@dataclass
class _Chain:
    segments: tuple[Segment, ...]
    index: int = 0
    state: str = "unready"


@dataclass
class _Life:
    row: str
    spec: LifeSpec
    plan: Layout
    keys: tuple[tuple[int, int, int], ...]
    first: int | None = None
    end: int | None = None
    last: int | None = None
    cause: str | None = None
    finished: bool = False


def project(prepared: Prepared, kind: str, draws: Draws) -> Schedule:
    """Project non-preemptive segments; reuse dispatch and breach rules."""
    slow = slow_rows(prepared, kind, draws)
    design = prepared.design
    free = {lane: getattr(design.capacity, lane) for lane in LANES}
    waiting = {lane: [] for lane in LANES}
    events, windows = [], set()
    seq = 0
    chains, owners, lives = {}, {}, {}
    block_first = [None] * len(design.lives)
    arrivals = {}

    def push(t, cls, key, index=0):
        nonlocal seq
        heappush(events, (t, cls, seq, key, index))
        seq += 1

    def wait(key):
        chain = chains[key]
        chain.state = "waiting"
        heappush(waiting[chain.segments[chain.index].lane], key)

    for block, spec in enumerate(design.lives):
        for pos, row in enumerate(draws.arm_order[spec.life]):
            plan = layout(prepared, row, spec.life, row in slow)
            keys = ((block, 0, pos), (block, 1, pos))
            life = _Life(row, spec, plan, keys)
            lives[row, spec.life] = life
            for key, segments in zip(keys, (plan.b0, plan.b1), strict=True):
                chains[key] = _Chain(segments)
                owners[key] = life
            wait(keys[0])

    def end(life, t, cause):
        life.end, life.cause = t, cause
        life.last = t if life.first is not None else None
        for key in life.keys:
            chain = chains[key]
            if chain.state == "running":
                free[chain.segments[chain.index].lane] += 1
            chain.state = "dead"

    def start(key, t):
        chain, life = chains[key], owners[key]
        k = chain.index
        segment = chain.segments[k]
        chain.state = "running"
        free[segment.lane] -= 1
        push(t + segment.duration_ms, 0, key, k)
        for c, offset in segment.arrival_offset:
            arrivals[life.row, life.spec.life, BRANCHES[key[1]], c] = t + offset
        if key[1] != 0:
            return
        offsets = dict(segment.session_offset)
        if k == 0:
            life.first = t
            push(t + LIFE_BOUND_MS, 3, key)
            if block_first[key[0]] is None:
                block_first[key[0]] = t
                windows.add((t + LIFE_BOUND_MS, key[0]))
        fork = life.spec.fork
        if segment.first <= fork - 1 <= segment.last or (fork == 1 and k == 0):
            push(t + offsets.get(fork, segment.duration_ms), 2, life.keys[1])
        stop = draws.stops.get((life.row, life.spec.life))
        if stop is not None:
            s = stop[1]
            if segment.first < s <= segment.last or (s == 1 and k == 0):
                push(t + offsets[s], 1, key)

    while events or windows or any(waiting.values()):
        # Initial assignment is at zero; subsequent assignments use the next deadline.
        if events or windows:
            t = min(events[0][0] if events else min(windows)[0],
                    min(windows)[0] if windows else events[0][0])
        else:
            t = 0
        while True:
            while events and events[0][0] == t:
                _, cls, _, key, k = heappop(events)
                chain, life = chains[key], owners[key]
                if life.end is not None or life.finished:
                    continue
                if cls == 0:
                    if chain.state != "running" or chain.index != k:
                        continue
                    free[chain.segments[k].lane] += 1
                    if key[1] == 0 and chain.segments[k].lane == "pinned":
                        stop = draws.stops.get((life.row, life.spec.life))
                        if stop is not None and stop[1] == life.spec.swap:
                            push(t, 1, key)
                    chain.index += 1
                    if chain.index < len(chain.segments):
                        wait(key)
                    else:
                        chain.state = "done"
                    if all(chains[item].state == "done" for item in life.keys):
                        life.finished, life.last = True, t
                elif cls == 1:
                    end(life, t, draws.stops[life.row, life.spec.life][0])
                elif cls == 2:
                    wait(key)
                else:
                    end(life, t, "life_bound")
            for lane in LANES:
                while free[lane] > 0 and waiting[lane]:
                    key = heappop(waiting[lane])
                    chain = chains[key]
                    if chain.state != "waiting" or chain.segments[chain.index].lane != lane:
                        continue
                    start(key, t)
            if not events or events[0][0] != t:
                break
        due = sorted(window for window in windows if window[0] == t)
        for window in due:
            windows.remove(window)
            for row in draws.arm_order[design.lives[window[1]].life]:
                life = lives[row, design.lives[window[1]].life]
                if life.first is None and life.end is None:
                    end(life, t, "start_window")
        if not events and not windows:
            if any(chain.state == "waiting" for chain in chains.values()):
                raise RuntimeError("schedule stalled")
            break

    records = {}
    for key in sorted(lives):
        life = lives[key]
        block = life.keys[0][0]
        bf = block_first[block]
        breach = None
        if life.cause in ("failed", "blocked"):
            label = "SYSTEM_FAILURE" if life.cause == "failed" else "BLOCKED"
        else:
            first, last = life.first, life.last
            if life.cause == "start_window":
                first = last = bf + LIFE_BOUND_MS + 1
            elif life.cause == "life_bound":
                last = first + LIFE_BOUND_MS + 1
            breach = classify_breach(ArmLifeSpan(
                life.row, life.spec.life, True, bf, first, last, life.plan.own_ms
            ))
            assert breach.cause == life.cause
            label = breach.label
        records[key] = ArmLife(life.row, life.spec.life, life.row in slow,
                               life.first, life.end, life.last, life.plan.own_ms,
                               life.cause, label, breach)
    sent = {key: arrivals[key] for key in sorted(arrivals)
            if records[key[:2]].end_ms is None or arrivals[key] <= records[key[:2]].end_ms}
    system, controls, post_swap = {}, {}, {}
    blocks = {life.life: index for index, life in enumerate(design.lives)}
    rows = sorted([row.row for row in design.rows] + [SYSTEM])
    for spec in sorted(design.lives, key=lambda item: item.life):
        bf = block_first[blocks[spec.life]]
        for branch in BRANCHES:
            for c in design.checkpoints:
                key = (spec.life, branch, c)
                system[key] = "OK" if (SYSTEM, *key) in sent else records[SYSTEM, spec.life].label
                arms = {}
                for row in rows:
                    item = (row, *key)
                    if item in sent:
                        arms[row] = ArmEvents(arrival_time=sent[item] - bf)
                    else:
                        record = records[row, spec.life]
                        cause = record.cause if record.cause in CAUSES[:2] else "replay_stopped"
                        arms[row] = ArmEvents(pass_over=PassOver(record.end_ms - bf, cause))
                result = dispatch(draws.dispatch_seed, spec.life, branch, c, arms)
                assert result.release_time is not None
                arrival = None if result.arrival_time is None else result.arrival_time + bf
                controls[key] = Release(result.release_time + bf, result.followed_arm,
                                        arrival, result.lag, result.unmatched)
        for c in design.checkpoints:
            post_swap[spec.life, c] = c >= spec.swap
    t1 = max([*sent.values(), *(release.release_ms for release in controls.values())])
    return Schedule(kind, slow, tuple(block_first), sent, system, controls,
                    draws.control_failed, records, post_swap, t1)


def unit_times(schedule: Schedule) -> dict[tuple[str, str, int], Fraction | None]:
    """Mean run-time sends; a system unit averages only its OK items."""
    units = sorted(schedule.post_swap)
    result = {}
    for arm in (*PROBE_ONLY, SYSTEM):
        for life, c in units:
            if arm == SYSTEM:
                times = [schedule.sent[arm, life, branch, c] for branch in BRANCHES
                         if schedule.system[life, branch, c] == "OK"]
            else:
                times = [schedule.controls[life, branch, c].release_ms for branch in BRANCHES]
            result[arm, life, c] = Fraction(sum(times), len(times)) if times else None
    return result
