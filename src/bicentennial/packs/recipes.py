"""Minimal, explicitly placed material for the real G1 and G2 templates."""

from bicentennial.genres.g1_software import world as g1
from bicentennial.genres.g1_software.codebase_model import PROCESS, write_commit
from bicentennial.genres.g2_assistant.preferences import Pref, write_preferences
from bicentennial.genres.g2_assistant.world import (
    finish,
    write_entity,
    write_forget,
    write_people,
)
from bicentennial.world.db import insert_entity
from bicentennial.world.lineage import atomic
from bicentennial.world.processes import check_tokens, mint
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.processes.forget import verify
from bicentennial.world.processes.incidental import Detail, write_details
from bicentennial.world.schedule import write_sessions
from bicentennial.world.targeted import Recipe


def _g1(template):
    def recipe(db, schedule, placement):
        e, total = placement.evidence_session, len(schedule.sessions)
        entities = {}
        with atomic(db):
            write_sessions(db, schedule)
            for kind, names in [("person", ("Heron", "Wren")),
                                *((kind, values[0]) for kind, values in g1.KINDS.items())]:
                for i, name in enumerate(names):
                    ident = mint(schedule, PROCESS, "entities", "entity", kind, i)
                    insert_entity(db, id=ident, kind=kind, canonical_name=name, aliases_json=[],
                                  created_t=schedule.sessions[0].t_start, retired_t=None)
                    entities[kind, name] = ident
            p, wren = entities["person", "Heron"], entities["person", "Wren"]
            if template in ("drift-chain", "drift-chain-fault"):
                fault = template == "drift-chain-fault"
                write_corrections(db, schedule, [Chain(
                    id="deadline-1" if fault else "deadline-0",
                    subject=entities["milestone", "general release" if fault else "beta release"],
                    key="deadline", stem="DUE", depth=1, at=((e - 1, 2), (e, 2)))], principal=p)
            elif template in ("drift-config", "drift-quote"):
                config = template == "drift-config"
                ident = "setting-fix" if config else "setting-quote"
                write_corrections(db, schedule, [Chain(
                    id=ident, subject=entities["constant", "batch_size" if config else "flush_timeout_ms"],
                    key="value", stem="CONST", depth=1 if config else 0,
                    mention=None if config else "quote", at=((e - 1, 2), (e, 2)))], principal=p)
                if config:
                    write_commit(db, schedule, unit_id=ident, n=0,
                                 fact_id=mint(schedule, "corrections", ident, "fact", "value", 0), author=wren)
            elif template in ("recall-value", "wake-loop"):
                wake = template == "wake-loop"
                g1.write_statements(db, schedule, [g1.Statement(
                    id="decision-1" if wake else "decision-0",
                    subject=entities["decision", "retry policy" if wake else "queue backend"],
                    key="choice", stem="DECISION", at=(e, 3 if wake else 2))], principal=p)
            else:
                write_commitments(db, schedule, [Commitment(
                    id="commitment-1", subject=entities["commitment", "release checklist"],
                    predicate="deliver", stem="TASK", trigger="event",
                    cue_subject=entities["ticket", "schema migration"], cue_key="status", cue_stem="TICKET",
                    lures=(entities["ticket", "load test"],), sender=wren, cancelled=True,
                    channel="chat", notice_channel="chat", made=(1, 1), due=(total, 1))], principal=p)
            g1.tail_filler(db, schedule, principal=p)
            write_filler(db, schedule, principal=p)
            check_tokens(db)
            verify(db)
        return p
    return recipe


def _g2(template):
    def recipe(db, schedule, placement):
        e, total = placement.evidence_session, len(schedule.sessions)
        people = write_people(db, schedule)
        p, persons = people.principal, people.people

        def ent(kind, key):
            return write_entity(db, schedule, kind=kind, key=key, name=key.title())

        with atomic(db):
            if template in ("drift-booking", "drift-asof", "drift-no-update"):
                control = template == "drift-no-update"
                write_preferences(db, schedule, [Pref(
                    id="seat-short" if control else "seat-long", domain="seat",
                    scope=("context", "short_haul" if control else "long_haul"), stem="SEAT",
                    depth=0 if control else 1, mention="hedge" if control else None,
                    at=((e - 1, 3), (e, 3)) if control else ((e - 1, 2), (e, 2)))], principal=p)
            elif template in ("keep-incidental", "keep-neighbour"):
                neighbour = template == "keep-neighbour"
                places = persons[4:8] if neighbour else tuple(ent("place", f"place-{j}") for j in range(1, 5))
                write_details(db, schedule, [Detail(
                    id="nbday" if neighbour else "gate", subject=places[0],
                    predicate="birthday" if neighbour else "gate_code", stem="BDAY" if neighbour else "GATE",
                    decoys=places[1:], at=tuple((e, j) for j in ((1, 3, 4, 5) if neighbour else (1, 2, 3, 4))))],
                    principal=p, ratio=3)
                if neighbour:
                    write_forget(db, schedule, key="neigh", subject=persons[4], covered=(("address", "ADDR"),),
                                 neighbours=(("phone", "PHONE"),), principal=p, summaries=0, at=((1, 2), (total, 2)))
            elif template == "keep-forget":
                write_forget(db, schedule, key="ex", subject=persons[2], covered=(("address", "ADDR"),),
                             neighbours=(("birthday", "BDAY"),), principal=p, summaries=0, at=((e - 1, 2), (e, 2)))
            elif template == "recall-count":
                write_corrections(db, schedule, [Chain(
                    id="plan-trip", subject=ent("trip", "trip"), key="date", stem="DATE", depth=1,
                    at=((e - 1, 2), (e, 2)))], principal=p)
            else:
                trip, passport, lure = ent("trip", "trip"), ent("purchase", "passport"), ent("purchase", "lure")
                write_commitments(db, schedule, [Commitment(
                    id="passport", subject=trip, predicate="book", stem="TRIP", trigger="event",
                    cue_subject=passport, cue_key="delivery", cue_stem="PARCEL", sender=persons[1],
                    lures=(lure,), cancelled=True, made=(1, 1), due=(total, 1))], principal=p)
        finish(db, schedule, principal=p)
        return p
    return recipe


RECIPES: dict[tuple[str, str], Recipe] = {
    **{("G1", t): _g1(t) for t in ("drift-chain", "drift-chain-fault", "drift-config", "drift-quote",
                                  "recall-value", "wake-loop", "tue-ticket")},
    **{("G2", t): _g2(t) for t in ("drift-booking", "drift-asof", "drift-no-update", "keep-incidental",
                                  "keep-neighbour", "keep-forget", "recall-count", "tue-passport")},
}
