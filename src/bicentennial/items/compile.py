"""Read-only branch compilation into K12 items and runner metadata."""

import json
import unicodedata
from dataclasses import dataclass
from hashlib import sha256

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import mint_id, shuffle
from bicentennial.render.stream import lint
from bicentennial.world import unit, world_hash

from . import levers, tags
from .protocol import CANARY, cell_stage


@dataclass(frozen=True)
class Branch:
    life: str
    branch: str
    seed: str
    schedule_sha256: str
    entries: tuple[tuple[dict, dict], ...]


def _id(seed, life, process, parts):
    return mint_id(canon([seed, *unit(life, process, canon(parts).decode())]).decode(), 0)


def _options(db, schedule, cut, template, instance, item_id):
    if not instance.options or any(type(o.key) is not str or not o.key for o in instance.options):
        raise ValueError("nonempty option keys required")
    options = {}
    world_tokens = [(r["token_id"], unicodedata.normalize("NFC", r["value"]))
                    for r in db.execute("SELECT * FROM locked_token ORDER BY token_id")]
    for o in instance.options:
        if o.key in options:
            raise ValueError("duplicate option key")
        tokens = []
        for fid in o.token_fact_ids:
            rows = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchall()
            if len(rows) != 1:
                raise ValueError(f"one locked token required: {fid}")
            tokens.append(rows[0][0])
        if len(tokens) != len(set(unicodedata.normalize("NFC", t) for t in tokens)):
            raise ValueError("duplicate option token")
        if template.kind == "qa":
            if o.plan is not None or type(o.envelope) is not dict or set(o.envelope) != {"type", "value"}:
                raise ValueError("QA requires exactly an envelope")
            payload = {"envelope": o.envelope | {"confidence_milli": 1000 if tokens else 0}}
            text = canon(o.envelope["value"]).decode()
        else:
            if o.envelope is not None or type(o.plan) is not dict or set(o.plan) != {"steps"}:
                raise ValueError("act requires exactly a plan")
            payload, text = {"plan": o.plan}, canon(o.plan).decode()
        normal, own = unicodedata.normalize("NFC", text), {unicodedata.normalize("NFC", t) for t in tokens}
        if any(token in normal and token not in own for _, token in world_tokens):
            raise ValueError(f"foreign token in option: {o.key}")
        options[o.key] = dict(option_id=_id(schedule.seed, cut.life, "option", [template.ref, instance.key, o.key]),
                              tokens=tokens, **json.loads(canon(payload)))
    gold = instance.options[0].key
    middle = sorted(key for key, o in options.items() if key != gold and o["tokens"])
    tail = sorted(key for key, o in options.items() if key != gold and not o["tokens"])
    order = [gold, *shuffle(schedule.seed, unit(cut.life, "options", item_id), 0, "order", middle), *tail]
    return [options[key] for key in order]


def _entry(db, schedule, cut, t, i):
    k = i.probe_point
    if type(k) is not int or not any(p.index == k and p.probe_point for p in schedule.sessions):
        raise ValueError("probe point is not a checkpoint")
    item_id = _id(schedule.seed, cut.life, "item", [t.ref, i.key, cut.branch])
    if lint(db, [{"event_id": item_id, "text": i.prompt}]):
        raise ValueError(f"invalid probe prompt: {item_id}")
    rows = {r["event_id"]: r for r in cut.rows}
    indices = {p.session_id: p.index for p in schedule.sessions}
    if bool(i.gold_spans) == i.never_observed or any(
            eid not in rows or not rows[eid]["gold_critical"] or indices[rows[eid]["session_id"]] > k
            for eid in i.gold_spans):
        raise ValueError("invalid gold spans")
    if i.decisive_fact_id is None:
        if not i.never_observed or t.twin_type is not None:
            raise ValueError("decisive fact required")
    elif not db.execute("SELECT 1 FROM fact WHERE id=?", (i.decisive_fact_id,)).fetchone():
        raise ValueError("unknown decisive fact")
    spans = [r["event_id"] for r in cut.rows if r["event_id"] in i.gold_spans]
    values, crossed, evidence_session = levers.compute(db, schedule, cut, gold_spans=spans,
        decisive_fact_id=i.decisive_fact_id, probe_point=k)
    stage = tags.stage(t.kind, crossed)
    if cell_stage(t.cell_id) == "S" and stage == "remember" or i.duty and t.kind != "act":
        raise ValueError("invalid stress cell or QA duty")
    options = _options(db, schedule, cut, t, i, item_id)
    if t.kind == "qa":
        if i.decision_table_ref is not None:
            raise ValueError("QA table reference must be absent")
        table_ref = t.ref
    else:
        table = next((v for v in t.decision_tables if v["table_id"] == i.decision_table_ref), None)
        if table is None or table["timed"] != (t.track == "Tuesday") or (
                (table["gold"] == "act") != bool(options[0]["plan"]["steps"])):
            raise ValueError("decision table disagrees with item")
        table_ref = i.decision_table_ref
    item = dict(canary=CANARY, item_id=item_id, stage=stage, track=t.track, cell_id=t.cell_id,
                probe_point=k, prompt=i.prompt, options=options,
                gold=dict(option_id=options[0]["option_id"], never_observed=i.never_observed),
                gold_spans=spans, decision_table_ref=table_ref, precondition=tags.precondition(cut, k),
                memory_tag=tags.memory_tag(db, [i.decisive_fact_id], schedule.sessions[k - 1].t_end),
                labels=tags.labels(stage, crossed))
    validate("item", item)
    meta = dict(template_id=t.template_id, template_version=t.version, instance_key=i.key,
                twin_type=t.twin_type, direction=t.direction, semantics=t.semantics,
                decisive_fact_id=i.decisive_fact_id, evidence_session=evidence_session,
                crossed=list(crossed), levers=values, duty=i.duty)
    return item, meta


def compile_branch(db, schedule, cut, templates) -> Branch:
    digest = sha256(schedule.to_json()).hexdigest()
    seed = db.execute("SELECT seed FROM meta").fetchone()[0]
    if (cut.branch not in ("B0", "B1") or cut.life != schedule.life or cut.world_hash != world_hash(db)
            or cut.schedule_sha256 != digest or seed != schedule.seed):
        raise ValueError("branch world or schedule identity mismatch")
    templates = sorted(templates, key=lambda t: t.template_id)
    if len({t.template_id for t in templates}) != len(templates):
        raise ValueError("duplicate template id")
    entries, counts = [], {}
    for t in templates:
        instances = sorted(t.instances(db, schedule), key=lambda i: i.key)
        if any(type(i.key) is not str or not i.key for i in instances) or len({i.key for i in instances}) != len(instances):
            raise ValueError("invalid or duplicate instance key")
        for i in instances:
            entries.append(_entry(db, schedule, cut, t, i))
            key = i.probe_point, t.kind
            counts[key] = counts.get(key, 0) + 1
            if schedule.scale.name == "t1" and counts[key] > (6 if t.kind == "qa" else 2):
                raise ValueError("T1 probe budget exceeded")
    return Branch(cut.life, cut.branch, seed, digest, tuple(sorted(entries, key=lambda e: e[0]["item_id"])))
