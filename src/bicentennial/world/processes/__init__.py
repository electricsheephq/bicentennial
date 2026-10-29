"""Shared helpers for keyed world processes: slots, ids, locked tokens and rows."""

import re
import unicodedata

from bicentennial.canon import canon
from bicentennial.keyed import mint_id, uniform_int

from .. import db as rows
from .. import unit
from ..scale import TURNS

HARD, SOFT = 1000, 500
SALIENCE, LOW_SALIENCE = 500, 100
SURFACES = ("mail", "notes", "repo", "tracker", "calendar")
REREAD = ("mail", "notes", "calendar", "tracker")
TOKEN_KINDS = ("number", "name", "date", "code")
STEM, NUMBER = re.compile(r"[A-Z]{2,12}"), re.compile(r"(?<![0-9])[0-9]{6}(?![0-9])")


def slot(schedule, session, turn) -> int:
    if (type(session) is not int or type(turn) is not int
            or not (1 <= session <= len(schedule.sessions) and 1 <= turn <= TURNS)):
        raise ValueError("slot outside the schedule")
    return schedule.sessions[session - 1].turn_t[turn - 1]


def mint(schedule, process, unit_id, table, part, n) -> str:
    return mint_id(canon([schedule.seed, schedule.life, process, unit_id, table, part]).decode(), n)


def pair(schedule, d) -> int:
    """The number a commitment's made token reserves for its cancellation, in both twins."""
    return uniform_int(schedule.seed, unit(schedule.life, "commitments", "pair"), 0, f"pair:{d}", 100000, 999999)


def token_value(db, schedule, process, unit_id, part, n, stem, *, paired=False) -> str:
    """Mint STEM-dddddd, retrying taken numbers and token containment collisions.

    Reserve each commitment's cancellation number and value in both twins, so a cancel flip moves
    no other draw. With paired=True, check the made and cancellation values together.
    """
    if type(stem) is not str or not STEM.fullmatch(stem):
        raise ValueError("token stem must match ^[A-Z]{2,12}$")
    values = {v for (v,) in db.execute("SELECT value FROM locked_token")}
    values |= {f"{v.rsplit('-', 1)[0]}-{pair(schedule, int(d))}" for (v,) in db.execute(
        "SELECT t.value FROM commitment c JOIN locked_token t ON t.fact_id = c.fact_id") for d in NUMBER.findall(v)}
    taken = {d for v in values for d in NUMBER.findall(v)}
    # No attempt can escape a token contained in the fixed prefix (for example, REQ-).
    if any(v in f"{stem}-" for v in values):
        raise ValueError("token stem contains a locked token")
    key, attempt = unit(schedule.life, process, unit_id), 0
    while True:
        d = uniform_int(schedule.seed, key, attempt, f"token:{part}:{n}", 100000, 999999)
        numbers = (d, pair(schedule, d)) if paired else (d,)
        candidates = [f"{stem}-{number}" for number in numbers]
        if (len(set(numbers)) == len(numbers) and not any(str(number) in taken for number in numbers)
                and not any(a in b or b in a for a in candidates for b in values)):
            return candidates[0]
        attempt += 1


def check_tokens(db) -> None:
    check_values([v for (v,) in db.execute("SELECT value FROM locked_token ORDER BY value")])


def check_values(values) -> None:
    if any(unicodedata.normalize("NFC", v) != v or len(v) < 4 for v in values):
        raise ValueError("locked token is not NFC or shorter than 4 characters")
    if len(set(values)) != len(values) or any(a != b and a in b for a in values for b in values):
        raise ValueError("locked token duplicates or is a substring of another")


def check_common(db, schedule, entities, specs, stems) -> None:
    """The refusals every writer shares; callers run them all before the first insert."""
    meta = db.execute("SELECT seed FROM meta").fetchall()
    if len(meta) != 1 or meta[0][0] != schedule.seed:
        raise ValueError("world seed does not match schedule")
    for e in entities:
        if type(e) is not str or not db.execute("SELECT 1 FROM entity WHERE id=?", (e,)).fetchone():
            raise ValueError(f"unknown entity: {e!r}")
    ids = [s.id for s in specs]
    if any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("spec ids must be unique nonempty strings")
    if any(type(s) is not str or not STEM.fullmatch(s) for s in stems):
        raise ValueError("token stem must match ^[A-Z]{2,12}$")
    if any(type(s.surfaces) is not tuple or not set(s.surfaces) <= set(SURFACES) for s in specs):
        raise ValueError("unknown surface")
    if any(getattr(s, "token_kind", "code") not in TOKEN_KINDS for s in specs):
        raise ValueError("unknown token kind")


def check_at(schedule, at, m) -> None:
    if at is not None:
        if type(at) is not tuple or len(at) != m or any(type(p) is not tuple or len(p) != 2 for p in at):
            raise ValueError("at needs one (session, turn) pair per event")
        for p in at:
            slot(schedule, *p)


class Unit:
    """One spec's keyed draws and rows; every id depends only on the unit and the part."""

    def __init__(self, db, schedule, process, spec):
        self.db, self.schedule, self.process, self.spec = db, schedule, process, spec
        self.u, self.times, self.surfaced = unit(schedule.life, process, spec.id), {}, set()

    def draw(self, name, lo, hi) -> int:
        return uniform_int(self.schedule.seed, self.u, 0, name, lo, hi)

    def id(self, table, part, n=0) -> str:
        return mint(self.schedule, self.process, self.spec.id, table, part, n)

    def event(self, part, n, t, *, kind, channel, actor, salience=SALIENCE) -> str:
        self.times[eid := self.id("event", part, n)] = (t, channel)
        rows.insert_event(self.db, id=eid, t_sim=t, kind=kind, channel=channel, actor_id=actor,
                          audience_json=["agent"], visibility="shared", salience=salience, payload_json={})
        return eid

    def fact(self, part, n, subject, predicate, stem, *, strength=HARD, act="assert", polarity="affirm",
             value=None) -> tuple[str, str]:
        fid, kind = self.id("fact", part, n), getattr(self.spec, "token_kind", "code")
        value = value or token_value(self.db, self.schedule, self.process, self.spec.id, part, n, stem)
        rows.insert_fact(self.db, id=fid, subject_id=subject, predicate=predicate, object=value,
                         polarity=polarity, modality="stated", strength=strength, speech_act=act)
        rows.insert_locked_token(self.db, token_id=self.id("token", part, n), fact_id=fid, kind=kind, value=value)
        return fid, value

    def link(self, eid, fid, role, surfaces=()) -> None:
        """Declared surfaces for asserted facts; a re-readable channel surfaces what it carries."""
        rows.insert_link(self.db, event_id=eid, fact_id=fid, role=role)
        t, channel = self.times[eid]
        found = set(surfaces if role == "assert" else ()) | ({channel} & set(REREAD) if role != "retract" else set())
        for row in sorted({(fid, s, t) for s in found} - self.surfaced):
            rows.insert_fact_surface(self.db, fact_id=row[0], surface=row[1], from_t=row[2])
            self.surfaced.add(row)

    def attr(self, subject, key, value, t, eid, valid_to_t=None) -> None:
        rows.insert_attr(self.db, entity_id=subject, key=key, value=value, valid_from_t=t,
                         valid_to_t=valid_to_t, recorded_t=t, source_event_id=eid)
