"""Plants with genuine twins; rejection evidence and the twin are derived from rows at read time."""

import json
from dataclasses import dataclass

from bicentennial.canon import canon

from ..db import insert_plant
from ..lineage import Ev, atomic, ids, on_record, write_event, write_fact

PLANT_KINDS = {kind: ('chat', 'mail') for kind in ('forged_agreement', 'third_party_claim', 'false_premise')}
PLANT_SPEECH_ACTS = ('assert', 'quote')
RESERVED = ('authorised_for', 'forget')


@dataclass(frozen=True)
class Current:
    subject_id: str
    predicate: str
    object: str


@dataclass(frozen=True)
class Rejection:
    basis: str
    evidence_fact_id: str
    evidence_event_id: str


@dataclass(frozen=True)
class Twin:
    fact_id: str
    carrier_event_id: str
    channel: str
    actor_id: str
    evidence_fact_id: str | None
    evidence_object: str | None
    evidence_polarity: str | None


@dataclass(frozen=True)
class Plant:
    fact_id: str
    carrier_event_id: str
    kind: str
    channel: str
    current_fact_id: str | None
    rejection: Rejection | None
    twin: Twin


def _latest(db, rows, t, value):
    """The candidate on record at t with the greatest record time; equal values tie to the smallest id."""
    found = sorted((-rec[0], row['id'], rec[1], row) for row in rows if (rec := on_record(db, row['id'], t)))
    top = [x for x in found if x[0] == found[0][0]] if found else []
    if len({value(x[3]) for x in top}) > 1:
        raise ValueError('candidates share a record time with different values')
    return (top[0][3], top[0][2]) if top else (None, None)


def _judge(db, fact_id, event_id):
    p = db.execute('SELECT * FROM fact WHERE id = ?', (fact_id,)).fetchone()
    carrier = db.execute('SELECT * FROM event WHERE id = ?', (event_id,)).fetchone()
    if p is None or carrier is None:
        raise ValueError('unknown fact or event')
    t, actor = carrier['t_sim'], carrier['actor_id']
    last, last_ev = _latest(db, db.execute(
        "SELECT * FROM fact WHERE subject_id = ? AND predicate = ? AND modality IN ('stated', 'observed') "
        'AND id != ?', (p['subject_id'], p['predicate'], fact_id)), t, lambda r: (r['object'], r['polarity']))
    auth, auth_ev = _latest(db, db.execute(
        "SELECT * FROM fact WHERE predicate = 'authorised_for' AND object = ? AND modality = 'stated'",
        (canon(p['predicate']).decode(),)), t, lambda r: (r['subject_id'], r['polarity']))
    differs = last is not None and (last['object'], last['polarity']) != (p['object'], p['polarity'])
    unauthorised = auth is not None and auth['subject_id'] != actor
    if differs:
        verdict = Rejection('contradiction' if last['modality'] == 'stated' else 'verification', last['id'], last_ev)
    else:
        verdict = Rejection('authority_rule', auth['id'], auth_ev) if unauthorised else None
    evidence = (last['id'], json.loads(p['object']), p['polarity']) if differs else (None, None, None)
    twin = Twin(fact_id, event_id, carrier['channel'], auth['subject_id'] if unauthorised else actor, *evidence)
    return verdict, twin


def rejection(db, fact_id, event_id) -> Rejection | None:
    return _judge(db, fact_id, event_id)[0]


def plant(db, fact_id) -> Plant:
    rows = db.execute('SELECT * FROM plant WHERE fact_id = ?', (fact_id,)).fetchall()
    if len(rows) != 1:
        raise ValueError('expected exactly one plant row')
    kind, carrier = rows[0]['kind'], rows[0]['carrier_event_id']
    verdict, twin = _judge(db, fact_id, carrier)
    if twin.evidence_fact_id and db.execute('SELECT 1 FROM locked_token WHERE fact_id IN (?, ?)',
                                            (fact_id, twin.evidence_fact_id)).fetchone():
        raise ValueError('a value flip would move a locked token')
    current = [r[0] for r in db.execute("SELECT fact_id FROM link WHERE event_id = ? AND role = 'assert' "
                                        'AND fact_id != ? ORDER BY fact_id', (carrier, fact_id))]
    if kind != 'false_premise' or not current:
        current = [None]
    if len(current) != 1:
        raise ValueError('a carrier holds at most one current fact')
    return Plant(fact_id, carrier, kind, twin.channel, current[0], verdict, twin)


def plants(db) -> tuple[Plant, ...]:
    return tuple(plant(db, r[0]) for r in db.execute('SELECT DISTINCT fact_id FROM plant ORDER BY fact_id'))


def write_plant(db, *, life, key, kind, carrier: Ev, subject_id, predicate, object: str, polarity,
                speech_act, strength, current: Current | None = None) -> Plant:
    with atomic(db):
        if kind not in PLANT_KINDS:
            raise ValueError('unknown plant kind')
        if speech_act not in PLANT_SPEECH_ACTS:
            raise ValueError('a plant asserts or quotes')
        if current is not None and kind != 'false_premise':
            raise ValueError('only a false premise carries a current fact')
        claims = [(predicate, object)] + ([(current.predicate, current.object)] if current else [])
        if any(type(o) is not str for _, o in claims) or any(p in RESERVED for p, _ in claims):
            raise ValueError('plant objects are strings on unreserved predicates')
        mint = ids(db, life, 'plants', key)
        write_event(db, mint(0), carrier, PLANT_KINDS[kind])
        write_fact(db, mint(1), mint(0), subject_id=subject_id, predicate=predicate, object=object,
                   polarity=polarity, modality='planted', strength=strength, speech_act=speech_act)
        insert_plant(db, fact_id=mint(1), carrier_event_id=mint(0), kind=kind)
        if current is not None:
            write_fact(db, mint(2), mint(0), subject_id=current.subject_id, predicate=current.predicate,
                       object=current.object)
        return plant(db, mint(1))


def write_authority_rule(db, *, life, key, event: Ev, authorised_id, predicate) -> str:
    with atomic(db):
        if type(predicate) is not str or predicate in RESERVED:
            raise ValueError('an authority rule names an unreserved predicate')
        mint = ids(db, life, 'authority', key)
        write_event(db, mint(0), event, ('chat', 'mail'))
        write_fact(db, mint(1), mint(0), subject_id=authorised_id, predicate='authorised_for', object=predicate)
        return mint(1)
