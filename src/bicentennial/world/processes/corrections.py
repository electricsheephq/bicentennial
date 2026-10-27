"""Correction chains: supersession by retract links over append-only attr history."""

import unicodedata
from dataclasses import dataclass

from bicentennial.keyed import shuffle

from ..scale import TURNS
from . import HARD, SOFT, Unit, check_at, check_common, check_tokens, slot

MENTIONS = ("hedge", "quote", "third_party", None)


@dataclass(frozen=True, kw_only=True)
class Chain:
    id: str
    subject: str
    key: str
    stem: str
    depth: int
    mention: str | None = None
    third_party: str | None = None
    sibling: str | None = None
    strength: int = HARD
    token_kind: str = "code"
    channel: str = "chat"
    surfaces: tuple[str, ...] = ()
    at: tuple[tuple[int, int], ...] | None = None
    values: tuple[str, ...] | None = None


def _check(db, schedule, chains, principal) -> None:
    check_common(db, schedule, [principal, *(c.subject for c in chains),
                                *(c.third_party for c in chains if c.third_party is not None)],
                 chains, [c.stem for c in chains])
    pairs = [(c.subject, k) for c in chains for k in (c.key, c.sibling) if k is not None]
    if len(set(pairs)) != len(pairs):
        raise ValueError("chains share a (subject, key) pair")
    for c in chains:
        if type(c.depth) is not int or not 0 <= c.depth <= 6 or (c.depth == 0 and c.mention is None):
            raise ValueError("depth must be 0..6, and depth 0 needs a mention")
        if c.mention not in MENTIONS:
            raise ValueError("unknown mention kind")
        if (c.mention == "third_party") != (c.third_party is not None) or c.third_party == principal:
            raise ValueError("a third party is required exactly for a third-party mention, not the principal")
        if any(type(k) is not str or not k for k in (c.key, "-" if c.sibling is None else c.sibling)) or c.sibling == c.key:
            raise ValueError("key and sibling must be distinct nonempty strings")
        if type(c.strength) is not int or not 0 <= c.strength <= HARD:
            raise ValueError("strength must be an int in 0..1000")
        if (m := c.depth + 1 + (c.mention is not None)) > len(schedule.sessions):
            raise ValueError("chain has more events than the life has sessions")
        check_at(schedule, c.at, m)
        if c.at and any(a[0] >= b[0] for a, b in zip(c.at, c.at[1:], strict=False)):
            raise ValueError("chain sessions must strictly increase")
        if c.values is not None and (type(c.values) is not tuple or len(c.values) != m + (c.sibling is not None)
                                     or not all(type(v) is str and unicodedata.normalize("NFC", v) == v
                                                and len(v) >= 4 and "\n" not in v for v in c.values)):
            raise ValueError("values need one NFC token of 4+ characters per fact")


def write_corrections(db, schedule, chains, *, principal) -> None:
    _check(db, schedule, chains := tuple(chains), principal)
    for c in chains:
        w, m = Unit(db, schedule, "corrections", c), c.depth + 1 + (c.mention is not None)
        times = [slot(schedule, *p) for p in c.at or [(k, w.draw(f"turn:{j}", 1, TURNS)) for j, k in enumerate(
            sorted(shuffle(schedule.seed, w.u, 0, "sessions", range(1, len(schedule.sessions) + 1))[:m]))]]
        values, facts = c.values or (None,) * (m + 1), []
        for j, t in enumerate(times):
            mention = c.mention if j > c.depth else None
            e = w.event("event", j, t, kind="statement", channel=c.channel,
                        actor=c.third_party if mention == "third_party" else principal)
            act = mention if mention in ("hedge", "quote") else "assert"
            f, v = w.fact("value", j, c.subject, c.key, c.stem, strength=SOFT if act == "hedge" else c.strength,
                          act=act, value=values[j])
            w.link(e, f, "assert", () if mention else c.surfaces)
            if 1 <= j <= c.depth:
                w.link(e, facts[j - 1], "retract")
            if j <= c.depth:
                w.attr(c.subject, c.key, v, t, e, times[j + 1] if j < c.depth else None)
            if j == 0 and c.sibling is not None:
                fs, vs = w.fact("sibling", 0, c.subject, c.sibling, c.stem, strength=c.strength, value=values[m])
                w.link(e, fs, "assert", c.surfaces)
                w.attr(c.subject, c.sibling, vs, t, e)
            facts.append(f)
    check_tokens(db)
