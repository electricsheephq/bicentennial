"""Read-only G1 targets, repository plans and provisional C-7 data."""

import json
import re
from dataclasses import dataclass

from bicentennial.genres.g1_software.codebase_model import PATHS, state_at
from bicentennial.genres.g1_software.world import EXPLICIT
from bicentennial.items.compile import _id
from bicentennial.items.levers import wake_points
from bicentennial.items.protocol import CANARY, Option, Template
from bicentennial.world.processes import mint

PICKUP_W = 5
LEVER_MIX_LABEL = "provisional pending PREREG-v0.5"
PRIMARY_LEVER = {"RECALL-VERB": "distance_sessions", "DRIFT-CUR": "chain_depth",
                 "WAKE-LOOP": "wake_events", "TUE-EVENT": "distance_sessions"}
PREDICATE_KINDS = ("holds", "changed")
REPO_TOOLS = ({"name": "set_entry", "op": "set", "path_arg": "path",
               "key_arg": "name", "value_arg": "value"},)
REPO_TOOLS_BY_NAME = {t["name"]: t for t in REPO_TOOLS}
VISIBLE = "e.t_sim < ? AND EXISTS (SELECT 1 FROM json_each(e.audience_json) WHERE value='agent')"


@dataclass(frozen=True, kw_only=True, eq=False)
class G1Template(Template):
    checkpoint: int | None = None

    def __post_init__(self):
        super().__post_init__()

    def probe(self, schedule):
        k = schedule.scale.checkpoints[-1] if self.checkpoint is None else self.checkpoint
        if type(k) is not int or k not in schedule.scale.checkpoints:
            raise ValueError(self.ref)
        return k, schedule.sessions[k - 1].t_end

    @property
    def lever_mix(self):
        return dict(label=LEVER_MIX_LABEL, primary=PRIMARY_LEVER[self.cell_id],
                    value=getattr(self, "depth", None), others="neutral", rungs="uncalibrated (v0.2)")


def linking(db, fact_ids, t):
    ids = tuple(sorted(set(fact_ids)))
    marks = ",".join("?" for _ in ids)
    return tuple(r[0] for r in db.execute(
        "SELECT DISTINCT e.id FROM event e JOIN link l ON l.event_id=e.id "
        f"WHERE l.fact_id IN ({marks}) AND {VISIBLE} ORDER BY e.id", (*ids, t)))


def visible(db, eid, t):
    return bool(db.execute(f"SELECT 1 FROM event e WHERE e.id=? AND {VISIBLE}", (eid, t)).fetchone())


def fact(db, fid):
    row = db.execute("SELECT * FROM fact WHERE id=?", (fid,)).fetchone()
    if row is None:
        raise ValueError(fid)
    return row


def token(db, f):
    rows = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (f,)).fetchall()
    if len(rows) != 1:
        raise ValueError(f)
    return rows[0][0]


def value(db, f):
    return json.loads(fact(db, f)["object"])


def name(db, e):
    row = db.execute("SELECT canonical_name FROM entity WHERE id=?", (e,)).fetchone()
    if row is None:
        raise ValueError(e)
    return row[0]


def kind(db, e):
    row = db.execute("SELECT kind FROM entity WHERE id=?", (e,)).fetchone()
    if row is None:
        raise ValueError(e)
    return row[0]


def surfaced(db, f, t):
    return bool(db.execute("SELECT 1 FROM fact_surface WHERE fact_id=? AND from_t < ?", (f, t)).fetchone())


def mentions(db, s, p, t, role="assert"):
    return tuple(r[0] for r in db.execute(
        "SELECT f.id FROM fact f JOIN link l ON l.fact_id=f.id JOIN event e ON e.id=l.event_id "
        f"WHERE f.subject_id=? AND f.predicate=? AND l.role=? AND {VISIBLE} "
        "GROUP BY f.id ORDER BY min(e.t_sim), f.id", (s, p, role, t)))


def chain_facts(db, schedule, chain_id, depth, t):
    ids = tuple(mint(schedule, "corrections", chain_id, "fact", "value", j) for j in range(depth + 2))
    rows = [fact(db, f) for f in ids[:-1]]
    s, p = rows[0]["subject_id"], rows[0]["predicate"]
    times = [db.execute("SELECT min(e.t_sim) FROM event e JOIN link l ON l.event_id=e.id "
                        "WHERE l.fact_id=? AND l.role='assert'", (f,)).fetchone()[0] for f in ids[:-1]]
    if db.execute("SELECT 1 FROM fact WHERE id=?", (ids[-1],)).fetchone() or mentions(db, s, p, t) != ids[:-1]:
        raise ValueError(chain_id)
    if any(a >= b for a, b in zip(times, times[1:], strict=False)):
        raise ValueError(chain_id)
    return ids[:-1], s, p


def repo_state(db, schedule, k):
    return state_at(db, schedule.sessions[k - 1].t_end - 1)


def position(schedule, t):
    for p in schedule.sessions:
        if p.t_start <= t < p.t_end:
            return p.index, sum(turn <= t for turn in p.turn_t)
    raise ValueError(schedule.life)


def kill_points(schedule, k):
    return tuple(row for row in wake_points(schedule) if row[0] == "kill" and row[1] <= k)


def step(path, name, value):
    if (path not in PATHS.values() or type(name) is not str or not re.fullmatch(r"[a-z][a-z_ ]*[a-z]", name)
            or type(value) is not str or not EXPLICIT.fullmatch(value)):
        raise ValueError("set_entry")
    return {"tool": {"name": "set_entry", "args": {"path": path, "name": name, "value": value}}}


def apply_steps(state, steps):
    result = {p: dict(entries) for p, entries in state.items()}
    for entry in steps:
        tool = entry["tool"]
        if tool["name"] not in REPO_TOOLS_BY_NAME:
            raise ValueError("set_entry")
        args = tool["args"]
        step(**args)
        result[args["path"]][args["name"]] = args["value"]
    return result


def action(key, facts=(), *steps):
    return Option(key=key, token_fact_ids=tuple(facts), plan={"steps": list(steps)})


def role(key):
    return re.sub(r"-\d+$", "", key)


def option_roles(template, db, schedule):
    return {i.key: {_id(schedule.seed, schedule.life, "option", [template.ref, i.key, o.key]): role(o.key)
                    for o in i.options} for i in template.instances(db, schedule)}


def table(table_id, *, gold, timed, admissible, disqualifiers=()):
    return dict(canary=CANARY, table_id=table_id, gold=gold, timed=timed, admissible=list(admissible),
                disqualifiers=[dict(predicate=p, verdict=v, tuesday_class=c) for p, v, c in disqualifiers],
                benign_extras=[])


def repo_checks(template, db, schedule, *, check_type=None):
    """Build constant OR-groups, reducing changed to end-state holds because G1 templates
    refuse preexisting target names and drift-config's S0 holds the original, not the hedge.
    RepoCheck is imported here so importing the templates never loads the repository layer.
    """
    if check_type is None:
        from bicentennial.items.checks.repo import RepoCheck as check_type
    result = {}
    for i in template.instances(db, schedule):
        tab = next(t for t in template.decision_tables if t["table_id"] == i.decision_table_ref)
        names = [*tab["admissible"], *(r["predicate"] for r in tab["disqualifiers"])]
        result[i.key] = {p: tuple(tuple(check_type(kind="constant", **s["tool"]["args"])
                                            for s in o.plan["steps"])
                                  for o in i.options if role(o.key) == p.split(":")[1] and o.plan["steps"])
                         for p in names}
    return result
