"""Append planned fixtures, then rebuild away only shadowed filler events."""

import json
from dataclasses import asdict, replace

from bicentennial.canon import canon
from bicentennial.genres.g1_software import world as g1
from bicentennial.genres.g1_software.codebase_model import write_commit
from bicentennial.genres.g2_assistant import world as g2
from bicentennial.genres.g2_assistant.preferences import write_preferences
from bicentennial.keyed import choice

from . import unit
from .db import insert_entity
from .export import export_jsonl
from .processes import check_tokens, mint, slot
from .processes.commitments import write_commitments
from .processes.corrections import write_corrections
from .processes.filler import write_filler
from .processes.forget import verify
from .processes.incidental import write_details
from .twin import Flip, apply


def shadowed(db):
    return frozenset(r[0] for r in db.execute(
        "SELECT f.id FROM event f WHERE f.kind='filler' AND EXISTS "
        "(SELECT 1 FROM event e WHERE e.t_sim=f.t_sim AND e.kind!='filler')"))


def write_extra(genre, db, schedule, plan, principal):
    default = {r["id"] for r in db.execute("SELECT id FROM event")}
    default_times = {r[0] for r in db.execute("SELECT t_sim FROM event WHERE kind!='filler'")}
    actors = tuple(r[0] for r in db.execute(
        "SELECT id FROM entity WHERE kind='person' AND id!=? ORDER BY id", (principal,)))
    for f in plan.fixtures:
        actor = choice(schedule.seed, unit(schedule.life, "fixture-plan", f.key), 0, "actor", actors)
        for e in f.entities:
            if genre == "G1":
                insert_entity(db, id=e.id, kind=e.kind, canonical_name=e.name, aliases_json=[],
                              created_t=schedule.sessions[0].t_start, retired_t=None)
            else:
                if g2.write_entity(db, schedule, kind=e.kind, key=e.key, name=e.name) != e.id:
                    raise ValueError("plan:entity")
        for writer, spec in f.calls:
            if writer == "commit":
                write_commit(db, schedule, unit_id=spec, n=0, author=actor,
                             fact_id=mint(schedule, "corrections", spec, "fact", "value", 0))
            elif writer == "forget":
                g2.write_forget(db, schedule, principal=principal, **asdict(spec))
            elif writer == "details":
                write_details(db, schedule, (spec,), principal=principal, ratio=3)
            else:
                if writer == "commitments":
                    spec = replace(spec, sender=actor)
                writers = {"corrections": write_corrections, "statements": g1.write_statements,
                           "commitments": write_commitments,
                           "preferences": write_preferences}
                writers[writer](db, schedule, (spec,), principal=principal)
        if f.mode == "tue":
            for e in f.events:
                eid = mint(schedule, "commitments", f.key, "event", e.part, 0)
                row = db.execute("SELECT t_sim FROM event WHERE id=?", (eid,)).fetchone()
                if row is None or row[0] != slot(schedule, *e.at):
                    raise ValueError("plan:placement")
    if genre == "G1":
        g1.tail_filler(db, schedule, principal=principal)
        write_filler(db, schedule, principal=principal)
        check_tokens(db)
        verify(db)
        db.commit()
    else:
        g2.finish(db, schedule, principal=principal)
    subjects = {f.subject for f in plan.fixtures}
    counts = {}
    for e in db.execute("SELECT id,kind FROM entity ORDER BY id"):
        part, total = counts.get(e["kind"], (0, 0))
        counts[e["kind"]] = [part + (e["id"] in subjects), total + 1]
    return dict(filler_shadowed=len(shadowed(db)),
                shared_default=sum(r["t_sim"] in default_times
                    for r in db.execute("SELECT id,t_sim FROM event") if r["id"] not in default),
                probed=counts)


def rebuild(db, path):
    lines = export_jsonl(db).splitlines()
    dropped = shadowed(db)
    out = tuple(line for line in lines
                if (r := json.loads(line))["table"] == "event" and r["row"]["id"] in dropped)
    for line in out:
        r = json.loads(line)
        if (r["table"] != "event" or r["row"]["kind"] != "filler"
                or db.execute("SELECT 1 FROM link WHERE event_id=?", (r["row"]["id"],)).fetchone()):
            raise ValueError("rebuild:filler")
    if len(out) != len(dropped):
        raise ValueError("rebuild:export")
    if any(canon(eid) in line for line in lines if line not in out for eid in dropped):
        raise ValueError("rebuild:reference")
    flips = (Flip(("fixture-plan", "filler"), "", "filler", "", out, (),
                  frozenset(), frozenset(dropped)),) if out else ()
    rebuilt = apply(db, flips, path)
    if shadowed(rebuilt):
        rebuilt.close()
        raise ValueError("rebuild:mixed")
    return rebuilt
