"""Read-only G2 targets, option plans and decision-table data."""

import json
import re
from dataclasses import dataclass

from bicentennial.genres.g2_assistant.envseed import TOOLS, env_key
from bicentennial.items.compile import _id
from bicentennial.items.protocol import CANARY, Option, Template
from bicentennial.world.processes import mint

TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}
PREDICATE_KINDS = ("holds", "leaks", "repeated", "wrote")
VISIBLE = "e.t_sim < ? AND EXISTS (SELECT 1 FROM json_each(e.audience_json) WHERE value='agent')"


@dataclass(frozen=True, kw_only=True, eq=False)
class G2Template(Template):
    checkpoint: int | None = None

    def __post_init__(self):
        super().__post_init__()

    def probe(self, schedule):
        k = schedule.scale.checkpoints[-1] if self.checkpoint is None else self.checkpoint
        if type(k) is not int or k not in schedule.scale.checkpoints:
            raise ValueError(self.ref)
        return k, schedule.sessions[k - 1].t_end


def entity(schedule, kind, key):
    return mint(schedule, "g2-entities", kind, "entity", key, 0)


def linking(db, fact_ids, t):
    ids = tuple(sorted(set(fact_ids)))
    marks = ",".join("?" for _ in ids)
    return tuple(r[0] for r in db.execute(
        "SELECT DISTINCT e.id FROM event e JOIN link l ON l.event_id=e.id "
        f"WHERE l.fact_id IN ({marks}) AND {VISIBLE} ORDER BY e.id", (*ids, t)))


def visible(db, event_id, t):
    return bool(db.execute(f"SELECT 1 FROM event e WHERE e.id=? AND {VISIBLE}", (event_id, t)).fetchone())


def token(db, fact_id):
    rows = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fact_id,)).fetchall()
    if len(rows) != 1:
        raise ValueError(fact_id)
    return rows[0][0]


def name(db, entity_id):
    row = db.execute("SELECT canonical_name FROM entity WHERE id=?", (entity_id,)).fetchone()
    if row is None:
        raise ValueError(entity_id)
    return row[0]


def fact(db, fact_id):
    row = db.execute("SELECT * FROM fact WHERE id=?", (fact_id,)).fetchone()
    if row is None:
        raise ValueError(fact_id)
    return row


def value(db, fact_id):
    return json.loads(fact(db, fact_id)["object"])


def assertions(db, subject, predicate, t, *, stated_only=False):
    return tuple((r[0], r[1]) for r in db.execute(
        "SELECT f.id, min(e.t_sim) FROM fact f JOIN link l ON l.fact_id=f.id "
        "JOIN event e ON e.id=l.event_id WHERE f.subject_id=? AND f.predicate=? "
        f"AND l.role='assert' AND {VISIBLE} "
        + ("AND f.speech_act='assert' " if stated_only else "")
        + "GROUP BY f.id ORDER BY min(e.t_sim), f.id", (subject, predicate, t)))


def retractions(db, subject, predicate, t):
    return tuple((r[0], r[1], r[2]) for r in db.execute(
        "SELECT DISTINCT e.id, e.t_sim, f.id FROM event e JOIN link l ON l.event_id=e.id "
        "JOIN fact f ON f.id=l.fact_id WHERE f.subject_id=? AND f.predicate=? "
        f"AND l.role='retract' AND {VISIBLE} ORDER BY e.t_sim, e.id, f.id", (subject, predicate, t)))


def preference(db, schedule, pref_id, t):
    e = entity(schedule, "preference", f"pref-{pref_id}")
    row = db.execute("SELECT value FROM attr WHERE entity_id=? AND key='preference' "
                     "AND recorded_t < ? AND valid_from_t < ? ORDER BY valid_from_t DESC LIMIT 1",
                     (e, t, t)).fetchone()
    meta = json.loads(row[0]) if row else {}
    if meta.get("provenance") != "stated" or meta.get("scope", [None])[0] != "context":
        raise ValueError(e)
    return e, meta["domain"], meta["scope"][1]


def slot_key(schedule, template, instance_key):
    return env_key(schedule.seed, "item", f"{template.ref}/{instance_key}")


def step(tool, key, value):
    t = TOOLS_BY_NAME.get(tool)
    if t is None or t["op"] not in ("set", "add"):
        raise ValueError(tool)
    return {"tool": {"name": tool, "args": {t["key_arg"]: key, t["value_arg"]: value}}}


def action(key, facts=(), *steps):
    return Option(key=key, token_fact_ids=tuple(facts), plan={"steps": list(steps)})


def answer(key, facts=(), kind="unknown", value=None):
    return Option(key=key, token_fact_ids=tuple(facts), envelope={"type": kind, "value": value})


def role(key):
    return re.sub(r"-\d+$", "", key)


def option_roles(template, db, schedule):
    return {i.key: {_id(schedule.seed, schedule.life, "option", [template.ref, i.key, o.key]): role(o.key)
                    for o in i.options} for i in template.instances(db, schedule)}


def table(table_id, *, gold, timed, admissible, disqualifiers=(), benign=()):
    return dict(canary=CANARY, table_id=table_id, gold=gold, timed=timed, admissible=list(admissible),
                disqualifiers=[dict(predicate=p, verdict=v, tuesday_class=c) for p, v, c in disqualifiers],
                benign_extras=list(benign))
