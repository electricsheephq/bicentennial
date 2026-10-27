"""Forget requests over traced lineage; neighbours are derived from rows at read time."""

import json
from dataclasses import dataclass

from ..db import insert_forget_request
from ..lineage import Ev, atomic, closure, ids, on_record, write_event, write_fact


@dataclass(frozen=True)
class ForgetRequest:
    event_id: str
    subject_id: str
    predicates: tuple[str, ...]
    request_fact_ids: tuple[str, ...]
    covered: tuple[str, ...]
    selector: tuple[str, ...]
    derived_facts: tuple[str, ...]
    derived_events: tuple[str, ...]
    neighbours: tuple[str, ...]


def _links(db, fact_ids):
    """(fact id, role, event id, t_sim) of every link to any of the facts."""
    marks = ','.join('?' * len(fact_ids))
    return [tuple(r) for r in db.execute(f'SELECT l.fact_id, l.role, e.id, e.t_sim FROM link l JOIN event e '
                                         f'ON e.id = l.event_id WHERE l.fact_id IN ({marks})', fact_ids)]


def forget_request(db, event_id) -> ForgetRequest:
    """Read one request back from rows, re-running every refusal check."""
    row = db.execute('SELECT * FROM forget_request WHERE event_id = ?', (event_id,)).fetchone()
    if row is None:
        raise ValueError('no forget request')
    t = db.execute('SELECT t_sim FROM event WHERE id = ?', (event_id,)).fetchone()[0]
    asks = db.execute("SELECT f.* FROM fact f JOIN link l ON l.fact_id = f.id WHERE l.event_id = ? "
                      "AND l.role = 'assert' AND f.predicate = 'forget' ORDER BY f.id", (event_id,)).fetchall()
    subjects = {r['subject_id'] for r in asks}
    covered = tuple(sorted(json.loads(row['covered_fact_ids_json'])))
    if len(subjects) != 1 or not covered:
        raise ValueError('a request covers facts of one subject')
    (subject,), predicates = subjects, tuple(sorted(json.loads(r['object']) for r in asks))
    tokens = [db.execute('SELECT value FROM locked_token WHERE fact_id = ?', (f,)).fetchall() for f in covered]
    if any(len(found) != 1 for found in tokens):
        raise ValueError('every covered fact needs exactly one locked token')
    lineage = closure(db, covered)
    reach = (*covered, *lineage.facts)
    times = dict(db.execute(f'SELECT id, t_sim FROM event WHERE id IN ({",".join("?" * len(lineage.events))})',
                            tuple(lineage.events)).fetchall())
    # A covered fact's original assertion is its earliest assert-linked event (smallest id on a tie); any other
    # link to it, of any role, and any link to a closure fact, is a copy that lineage must track.
    links = _links(db, covered)
    first = {f: e for f, role, e, ts in sorted(links, key=lambda r: (r[3], r[2]), reverse=True) if role == 'assert'}
    copies = {e for f, _, e, ts in links if ts < t and e != first.get(f)}
    copies |= {e for _, _, e, ts in _links(db, tuple(lineage.facts)) if ts < t}
    if copies - lineage.events:
        raise ValueError('an untracked copy precedes the request')
    if len(times) != len(lineage.events) or any(ts >= t for ts in times.values()) or any(
            ts >= t and e != event_id for _, _, e, ts in _links(db, reach)):
        raise ValueError('a derivative at or after the request')
    marks = ','.join('?' * len(predicates))
    neighbours = tuple(sorted(f['id'] for f in db.execute(
        f"SELECT * FROM fact WHERE subject_id = ? AND predicate NOT IN ({marks}, 'forget') "
        "AND modality IN ('stated', 'observed') AND id IN (SELECT fact_id FROM locked_token "
        'GROUP BY fact_id HAVING count(*) = 1)', (subject, *predicates))
        if f['id'] not in lineage.facts and on_record(db, f['id'], t)))
    if not neighbours:
        raise ValueError('a forget request needs a neighbour')
    return ForgetRequest(event_id, subject, predicates, tuple(r['id'] for r in asks), covered,
                         tuple(sorted(found[0][0] for found in tokens)), tuple(sorted(lineage.facts)),
                         tuple(sorted(lineage.events)), neighbours)


def request_forget(db, *, life, key, event: Ev, subject_id, predicates: tuple[str, ...]) -> ForgetRequest:
    with atomic(db):
        if not predicates or len(set(predicates)) != len(predicates) or any(
                type(p) is not str or p == 'forget' for p in predicates):
            raise ValueError('predicates must be distinct strings other than forget')
        mint = ids(db, life, 'forget', key)
        write_event(db, mint(0), event, ('chat', 'mail'))
        for i, predicate in enumerate(sorted(predicates)):
            write_fact(db, mint(i + 1), mint(0), subject_id=subject_id, predicate='forget', object=predicate)
        marks = ','.join('?' * len(predicates))
        covered = sorted(r[0] for r in db.execute(
            'SELECT DISTINCT f.id FROM fact f JOIN link l ON l.fact_id = f.id JOIN event e ON e.id = l.event_id '
            f'WHERE f.subject_id = ? AND f.predicate IN ({marks}) AND e.t_sim < ?',
            (subject_id, *predicates, event.t_sim)))
        if not covered:
            raise ValueError('a forget request must cover a fact')
        insert_forget_request(db, event_id=mint(0), covered_fact_ids_json=covered)
        return forget_request(db, mint(0))


def verify(db) -> None:
    """Re-run the refusal checks for every request; builders call it before they commit."""
    for row in db.execute('SELECT event_id FROM forget_request ORDER BY event_id').fetchall():
        forget_request(db, row[0])
