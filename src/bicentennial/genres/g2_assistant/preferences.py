"""G2 preferences: stated chains decide action gold; behaviour and third-party rows are diagnostic only."""

import json
import re
from dataclasses import dataclass

from bicentennial.keyed import uniform_int
from bicentennial.world import db as rows
from bicentennial.world import lineage, unit
from bicentennial.world.processes import (
    HARD,
    LOW_SALIENCE,
    SALIENCE,
    mint,
    slot,
    token_value,
)
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.scale import TURNS

from . import world

PROVENANCE = ("stated", "behaviour", "third_party")
SCOPES = ("global", "context", "person", "venue")
NAME = re.compile(r"[a-z][a-z0-9_]*")


@dataclass(frozen=True, kw_only=True)
class Pref:
    id: str
    domain: str
    stem: str
    scope: tuple[str, str | None]
    provenance: str = "stated"
    depth: int = 0
    mention: str | None = None
    third_party: str | None = None
    strength: int = HARD
    teller: str | None = None
    at: tuple[tuple[int, int], ...] | None = None


def _name(value) -> bool:
    return type(value) is str and NAME.fullmatch(value) is not None


def _check(db, schedule, prefs, principal) -> None:
    world._same_world(db, schedule)
    world._ids(prefs)
    if world._kind(db, principal) != "person":
        raise ValueError("the principal must be a person")
    for p in prefs:
        if type(p.provenance) is not str or p.provenance not in PROVENANCE:
            raise ValueError("unknown provenance")
        if not _name(p.domain):
            raise ValueError("domain must match NAME")
        if type(p.scope) is not tuple or len(p.scope) != 2 or type(p.scope[0]) is not str \
                or p.scope[0] not in SCOPES:
            raise ValueError("scope must be a (kind, ref) pair with a known kind")
        kind, ref = p.scope
        if (ref is None) != (kind == "global"):
            raise ValueError("a ref is None exactly for a global scope")
        if kind == "context" and not _name(ref):
            raise ValueError("a context ref must match NAME")
        if kind in ("person", "venue") and world._kind(db, ref) != kind:
            raise ValueError(f"a {kind} scope needs a {kind} entity")
        if p.provenance == "third_party" and (p.teller == principal or world._kind(db, p.teller) != "person"):
            raise ValueError("a third-party preference needs a teller other than the principal")
        if p.provenance != "third_party" and p.teller is not None:
            raise ValueError("only a third-party preference has a teller")
        if p.provenance != "stated":
            if type(p.depth) is not int or p.depth != 0 or p.mention is not None or p.third_party is not None:
                raise ValueError("a non-stated preference has depth 0 and no mention")
            if type(p.strength) is not int or not 0 <= p.strength <= HARD:
                raise ValueError("strength must be an int in 0..1000")
            if p.at is not None:
                world._check_at(schedule, p.at, 1)
    classes = [(p.domain, p.scope) for p in prefs if p.provenance == "stated"]
    existing = {(v["domain"], tuple(v["scope"])) for v in (json.loads(r[0]) for r in db.execute(
        "SELECT value FROM attr WHERE key = 'preference'")) if v["provenance"] == "stated"}
    if len(set(classes)) != len(classes) or set(classes) & existing:
        raise ValueError("a (domain, scope) class has one stated preference")


def write_preferences(db, schedule, prefs, *, principal) -> dict[str, str]:
    """Each pref id with its entity id. Corrections close intervals through G03; nothing is overwritten."""
    with lineage.atomic(db):
        _check(db, schedule, prefs := tuple(prefs), principal)
        out = {}
        for p in prefs:
            kind, ref = p.scope
            label = "" if kind == "global" else f" ({ref})" if kind == "context" else " ({})".format(
                db.execute("SELECT canonical_name FROM entity WHERE id = ?", (ref,)).fetchone()[0])
            out[p.id] = world.write_entity(db, schedule, kind="preference", key=f"pref-{p.id}",
                                           name=f"{p.domain} preference{label}")
        stated = [p for p in prefs if p.provenance == "stated"]
        write_corrections(db, schedule, [Chain(
            id=f"pref-{p.id}", subject=out[p.id], key="value", stem=p.stem, depth=p.depth, mention=p.mention,
            third_party=p.third_party, strength=p.strength, at=p.at) for p in stated], principal=principal)
        # Reserve unlinked inventory decoys before diagnostic preferences can affect token draws.
        for p in stated:
            value = token_value(db, schedule, "g2-preferences", p.id, "decoy", 0, p.stem)
            fact_id = mint(schedule, "g2-preferences", p.id, "fact", "decoy", 0)
            rows.insert_fact(db, id=fact_id, subject_id=out[p.id], predicate="inventory_decoy", object=value,
                             polarity="affirm", modality="observed", strength=HARD, speech_act="assert")
            rows.insert_locked_token(db, token_id=mint(schedule, "g2-preferences", p.id, "token", "decoy", 0),
                                     fact_id=fact_id, kind="code", value=value)
        anchors = {p.id: mint(schedule, "corrections", f"pref-{p.id}", "event", "event", 0) for p in stated}
        for p in prefs:
            if p.provenance == "stated":
                continue
            told, u = p.provenance == "third_party", unit(schedule.life, "g2-preferences", p.id)
            at = p.at or ((uniform_int(schedule.seed, u, 0, "session", 1, len(schedule.sessions)),
                           uniform_int(schedule.seed, u, 0, "turn", 1, TURNS)),)
            anchors[p.id] = event_id = mint(schedule, "g2-preferences", p.id, "event", "event", 0)
            world._event(db, event_id, slot(schedule, *at[0]), kind="statement" if told else "observation",
                         actor=p.teller if told else principal, salience=SALIENCE if told else LOW_SALIENCE)
            value = token_value(db, schedule, "g2-preferences", p.id, "value", 0, p.stem)
            fact_id = mint(schedule, "g2-preferences", p.id, "fact", "value", 0)
            # A behaviour fact is inferred and unlinked, so no event renders it (G08 Decision 1).
            rows.insert_fact(db, id=fact_id, subject_id=out[p.id], predicate="value", object=value,
                             polarity="affirm", modality="stated" if told else "inferred_allowed",
                             strength=p.strength, speech_act="assert")
            if told:
                rows.insert_link(db, event_id=event_id, fact_id=fact_id, role="assert")
            rows.insert_locked_token(db, token_id=mint(schedule, "g2-preferences", p.id, "token", "value", 0),
                                     fact_id=fact_id, kind="code", value=value)
        for p in prefs:
            t0 = db.execute("SELECT t_sim FROM event WHERE id = ?", (anchors[p.id],)).fetchone()[0]
            rows.insert_attr(db, entity_id=out[p.id], key="preference", value={
                "domain": p.domain, "scope": list(p.scope), "provenance": p.provenance},
                valid_from_t=t0, valid_to_t=None, recorded_t=t0, source_event_id=anchors[p.id])
        return out
