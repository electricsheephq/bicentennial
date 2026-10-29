"""S-17's average probe-only load reserve, without stressing probe rates."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

from bicentennial.ocsim import schedule

PROBE_ONLY_LOAD = ("C", "CEIL", "F", "RAG")
DAY_MS = schedule.LIFE_BOUND_MS


@dataclass(frozen=True)
class ProbeOnlyLoad:
    tokens: Mapping[tuple[str, str, str, int], int]
    anchor_tokens: Mapping[str, int]
    rates: Mapping[str, int | Fraction]


def lane_load(load: ProbeOnlyLoad, lives: Sequence[schedule.LifeSpec],
              checkpoints: tuple[int, ...]) -> dict[str, tuple[int, int]]:
    """Ceil each probe set separately; absent probe keys contribute zero."""
    ids = {life.life for life in lives}
    for key, tokens in sorted(load.tokens.items()):
        if (not isinstance(key, tuple) or len(key) != 4
                or key[0] not in PROBE_ONLY_LOAD or key[1] not in ids
                or key[2] not in schedule.BRANCHES or type(key[3]) is not int
                or key[3] not in checkpoints):
            raise ValueError(f"bad probe-only key: {key}")
        if type(tokens) is not int or tokens < 0:
            raise ValueError("probe-only tokens must be ints >= 0")
    if set(load.anchor_tokens) != ids:
        raise ValueError("anchor tokens must name every life")
    if any(type(v) is not int or v < 0 for v in load.anchor_tokens.values()):
        raise ValueError("probe-only tokens must be ints >= 0")
    arms = sorted({key[0] for key in load.tokens} | {"anchor"})
    for arm in arms:
        rate = load.rates.get(arm)
        if (not (type(rate) is int or isinstance(rate, Fraction)) or rate <= 0):
            raise ValueError(f"probe-only rate for {arm} must be a positive int or Fraction")
    result = {}
    for life in sorted(ids):
        pinned = sum(schedule.session_ms(load.rates[arm], tokens)
                     for (arm, owner, _, _), tokens in sorted(load.tokens.items())
                     if owner == life)
        result[life] = (pinned, schedule.session_ms(load.rates["anchor"],
                                                  load.anchor_tokens[life]))
    return result


def reserves(load, lives, checkpoints) -> tuple[int, int]:
    values = lane_load(load, lives, checkpoints).values()
    return tuple(-((-max((v[i] for v in values), default=0)) // DAY_MS)
                 for i in (0, 1))


def capacity(lanes: tuple[schedule.LaneCapacity, schedule.LaneCapacity],
             reserve: tuple[int, int]) -> schedule.Capacity:
    if len(lanes) != 2 or tuple(lane.name for lane in lanes) != schedule.LANES:
        raise ValueError("lanes must be the pinned and swap lanes, in that order")
    return schedule.Capacity(*(schedule.chain_slots(lane, r)
                               for lane, r in zip(lanes, reserve, strict=True)))


def relabel(load: ProbeOnlyLoad, lives: Sequence[schedule.LifeSpec],
            pairs: Sequence[str]) -> ProbeOnlyLoad:
    """Keep a prefix of the already-validated input lives, renaming by position."""
    names = {life.life: pair for life, pair in zip(lives, pairs, strict=True)}
    return ProbeOnlyLoad(
        {(a, names[who], branch, c): n
         for (a, who, branch, c), n in sorted(load.tokens.items()) if who in names},
        {names[who]: n for who, n in sorted(load.anchor_tokens.items()) if who in names},
        dict(sorted(load.rates.items())),
    )
