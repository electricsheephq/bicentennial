"""Integer-only life scales and their pre-generation constraints."""

from dataclasses import dataclass
from fractions import Fraction

TURNS = 5
SESSION_S = 3_600
TURN_S = HEARTBEAT_S = 720
ORDINARY_GAP_S = (3_600, 39_600)
LONG_GAP_S = (604_800, 1_814_400)
FULL_SPAN_S = (1_814_400, 15_724_800)
DECOY_MIN_RATIO = 3
ANCHOR_T = 1_700_000_000
WORLD_TZ = "Europe/Paris"
SPRINT_FACTOR = Fraction(5, 4)
BLOCK = 25
DEV_WINDOW = 16_384
FULL_WINDOW = 131_072
PROVISIONAL: dict[str, str] = {
    "span": "provisional pending PREREG-v0.5",
    "decoy_ratio": "provisional pending PREREG-v0.5",
    "dev_window": "provisional C-5",
    "full_window": "illustrative; C-4 open",
    "heartbeat_s": "provisional; no PREREG value",
}


@dataclass(frozen=True, kw_only=True)
class Scale:
    name: str
    sessions: int
    window: int
    checkpoints: tuple[int, ...]
    kill: int | None
    swap: int | None
    restart: int | None
    compaction: int | None
    sprint_ranges: tuple[tuple[int, int], ...]
    long_gap_ranges: tuple[tuple[int, int], ...]


def named(name, *, sessions=None, wake=None) -> Scale:
    if name not in ("t0-micro", "t1", "full"):
        raise ValueError("unknown scale")
    if name == "t0-micro":
        if wake not in (None, "kill", "swap", "restart", "compaction", "gap"):
            raise ValueError("unknown wake")
        scale = Scale(name=name, sessions=sessions, window=DEV_WINDOW,
                      checkpoints=(sessions,),
                      **{k: sessions if wake == k else None
                         for k in ("kill", "swap", "restart", "compaction")},
                      sprint_ranges=(),
                      long_gap_ranges=((sessions, sessions),) if wake == "gap" else ())
    else:
        count = 20 if name == "t1" else 200
        if wake is not None or (sessions is not None and
                                (type(sessions) is not int or sessions != count)):
            raise ValueError("preset sessions and wakes are fixed")
        scale = Scale(name=name, sessions=count,
                      window=DEV_WINDOW if name == "t1" else FULL_WINDOW,
                      checkpoints=(10, 20) if name == "t1" else (20, 60, 120, 200),
                      kill=-(-11 * count // 20), swap=-(-3 * count // 4),
                      restart=None, compaction=None,
                      sprint_ranges=((2, 10), (12, 20)) if name == "t1" else
                      tuple((k, k + BLOCK - 1) for k in range(1, 201, BLOCK)),
                      long_gap_ranges=((1, 10), (11, 20)) if name == "t1" else
                      ((1, 20), (21, 60), (61, 120), (121, 200)))
    check(scale)
    return scale


def candidates(scale: Scale, bounds: tuple[int, int]) -> list[int]:
    """Ascending sessions excluding session one and all fixed fault points."""
    fixed = (scale.kill, scale.swap, scale.restart, scale.compaction)
    return [k for k in range(bounds[0], bounds[1] + 1) if k >= 2 and k not in fixed]


def check(scale: Scale) -> None:
    s = scale.sessions
    if scale.name not in ("t0-micro", "t1", "full") or type(s) is not int:
        raise ValueError("unknown scale or non-integer session count")
    micro = scale.name == "t0-micro"
    if (micro and not 1 <= s <= 3) or (not micro and s != (20 if scale.name == "t1" else 200)):
        raise ValueError("invalid session count")
    window = FULL_WINDOW if scale.name == "full" else DEV_WINDOW
    checkpoints = (s,) if micro else ((10, 20) if s == 20 else (20, 60, 120, 200))
    if (type(scale.window) is not int or scale.window != window or
            scale.checkpoints != checkpoints or
            any(type(k) is not int for k in scale.checkpoints)):
        raise ValueError("window and checkpoints are fixed")
    fixed = (scale.kill, scale.swap, scale.restart, scale.compaction)
    if any(k is not None and type(k) is not int for k in fixed):
        raise ValueError("fault sessions must be integers")
    if micro:
        if (sum(k is not None for k in fixed) + len(scale.long_gap_ranges) > 1 or
                any(k is not None and (s == 1 or k != s) for k in fixed) or
                scale.sprint_ranges or (scale.long_gap_ranges and
                                       (s == 1 or scale.long_gap_ranges != ((s, s),)))):
            raise ValueError("micro permits only one final-session wake")
    elif fixed != (-(-11 * s // 20), -(-3 * s // 4), None, None):
        raise ValueError("preset fault points are fixed")
    for ranges in (scale.sprint_ranges, scale.long_gap_ranges):
        if type(ranges) is not tuple:
            raise ValueError("ranges must be tuples")
        occupied = set()
        for bounds in ranges:
            if (type(bounds) is not tuple or len(bounds) != 2 or
                    any(type(k) is not int for k in bounds) or
                    not 1 <= bounds[0] <= bounds[1] <= s):
                raise ValueError("invalid session range")
            values = set(range(bounds[0], bounds[1] + 1))
            if occupied.intersection(values) or not candidates(scale, bounds):
                raise ValueError("overlapping or empty candidate range")
            occupied.update(values)
    ranges = scale.sprint_ranges
    if scale.name == "t1" and (len(ranges) != 2 or
                              sum(hi < scale.kill for lo, hi in ranges) != 1 or
                              sum(lo > scale.kill for lo, hi in ranges) != 1):
        raise ValueError("t1 needs a sprint on each side of the kill")
    if scale.name == "full":
        if len(ranges) < 8 or any(not any(b <= lo <= hi < b + BLOCK for lo, hi in ranges)
                                 for b in range(1, s + 1, BLOCK)):
            raise ValueError("full needs a sprint range inside every block")
        g = len(scale.long_gap_ranges)
        spans = [s * SESSION_S + (s - 1 - g) * ordinary + g * long
                 for ordinary, long in zip(ORDINARY_GAP_S, LONG_GAP_S, strict=True)]
        if spans[0] < FULL_SPAN_S[0] or spans[1] > FULL_SPAN_S[1]:
            raise ValueError("full span falls outside provisional bounds")
