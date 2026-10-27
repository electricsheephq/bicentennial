"""Derived-artifact lineage and the shared G04 row helpers; G04 writes rows and never commits."""

import json
from contextlib import contextmanager
from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.keyed import mint_id

from . import unit
from .db import insert_event, insert_fact, insert_lineage, insert_link

ARTIFACT_KINDS = ('event', 'fact')


@contextmanager
def atomic(db):
    """A refused call adds no row and leaves the caller's transaction open."""
    if not db.in_transaction:
        db.execute('BEGIN')
    db.execute('SAVEPOINT g04')
    try:
        yield
    except BaseException:
        db.execute('ROLLBACK TO g04')
        db.execute('RELEASE g04')
        raise
    db.execute('RELEASE g04')


@dataclass(frozen=True, kw_only=True)
class Ev:
    t_sim: int
    kind: str
    channel: str
    actor_id: str
    audience: tuple[str, ...]
    visibility: str
    salience: int


def ids(db, life, process, key):
    seed = db.execute('SELECT seed FROM meta').fetchone()[0]
    run_key = canon([seed, *unit(life, process, key)]).decode()
    return lambda n: mint_id(run_key, n)


def write_event(db, event_id, ev: Ev, channels) -> None:
    if ev.channel not in channels:
        raise ValueError('channel not allowed')
    if 'agent' not in ev.audience:
        raise ValueError('the agent must be in the audience')
    if not db.execute('SELECT 1 FROM session WHERE t_start <= ?1 AND ?1 < t_end', (ev.t_sim,)).fetchone():
        raise ValueError('event outside every session')
    if db.execute('SELECT 1 FROM event WHERE id = ?', (event_id,)).fetchone():
        raise ValueError('repeated key')
    insert_event(db, id=event_id, t_sim=ev.t_sim, kind=ev.kind, channel=ev.channel, actor_id=ev.actor_id,
                 audience_json=list(ev.audience), visibility=ev.visibility, salience=ev.salience, payload_json={})


def write_fact(db, fact_id, event_id, *, subject_id, predicate, object, polarity='affirm',
               modality='stated', strength=1000, speech_act='assert') -> None:
    insert_fact(db, id=fact_id, subject_id=subject_id, predicate=predicate, object=object,
                polarity=polarity, modality=modality, strength=strength, speech_act=speech_act)
    insert_link(db, event_id=event_id, fact_id=fact_id, role='assert')


def on_record(db, fact_id, t):
    """(record time, latest asserting event, smallest id on a tie) if the fact is on record at t."""
    seen = [(r['role'], r['t_sim'], r['id']) for r in db.execute(
        'SELECT l.role, e.t_sim, e.id, e.audience_json FROM link l JOIN event e ON e.id = l.event_id '
        'WHERE l.fact_id = ?', (fact_id,)) if r['t_sim'] < t and 'agent' in json.loads(r['audience_json'])]
    if any(role == 'retract' for role, _, _ in seen):
        return None
    best = min(((-ts, eid) for role, ts, eid in seen if role == 'assert'), default=None)
    return best and (-best[0], best[1])


@dataclass(frozen=True)
class Closure:
    facts: frozenset
    events: frozenset
    other: frozenset


def closure(db, fact_ids) -> Closure:
    found = {'fact': set(), 'event': set()}
    other, frontier = set(), sorted(set(fact_ids))
    while frontier:
        rows = db.execute(f'SELECT artifact_kind, artifact_id FROM lineage WHERE source_fact_id IN '
                          f'({",".join("?" * len(frontier))})', frontier).fetchall()
        new = {aid for kind, aid in rows if kind == 'fact'} - found['fact']
        for kind, aid in rows:
            if kind in found:
                found[kind].add(aid)
            else:
                other.add((kind, aid))
        frontier = sorted(new)
    return Closure(frozenset(found['fact']), frozenset(found['event']), frozenset(other))


def record(db, *, artifact_kind, artifact_id, sources: tuple[str, ...]) -> None:
    with atomic(db):
        if artifact_kind not in ARTIFACT_KINDS:
            raise ValueError('unknown artifact kind')
        artifact = db.execute(f'SELECT * FROM {artifact_kind} WHERE id = ?', (artifact_id,)).fetchone()
        if artifact is None:
            raise ValueError('missing artifact')
        if not sources or len(set(sources)) != len(sources):
            raise ValueError('empty or duplicate sources')
        if any(not db.execute('SELECT 1 FROM fact WHERE id = ?', (s,)).fetchone() for s in sources):
            raise ValueError('a source is not a fact')
        if artifact_kind == 'fact' and set(sources) & ({artifact_id} | closure(db, [artifact_id]).facts):
            raise ValueError('lineage cycle')
        if artifact_kind == 'event' and any(not db.execute(
                'SELECT 1 FROM link l JOIN event e ON e.id = l.event_id WHERE l.fact_id = ? AND e.t_sim < ?',
                (s, artifact['t_sim'])).fetchone() for s in sources):
            raise ValueError('a derivative must follow its source')
        for source in sorted(sources):
            insert_lineage(db, artifact_id=artifact_id, artifact_kind=artifact_kind, source_fact_id=source)
