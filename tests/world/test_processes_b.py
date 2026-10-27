"""G04 plants and forget requests: seeded loops over K10 keyed draws, 200 cases per property."""

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from bicentennial.keyed import choice, uniform_int
from bicentennial.world import (
    create_world,
    export_jsonl,
    export_world,
    lineage,
    unit,
    world_hash,
)
from bicentennial.world import db as writers
from bicentennial.world.lineage import Ev, closure, record
from bicentennial.world.processes import forget, plants
from bicentennial.world.processes.forget import forget_request, request_forget, verify
from bicentennial.world.processes.plants import (
    PLANT_KINDS,
    PLANT_SPEECH_ACTS,
    Current,
    Rejection,
    plant,
    rejection,
    write_authority_rule,
    write_plant,
)
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions

CASES = 200
LIFE = 'life-a'
SHAPES = ('none', 'stated', 'observed', 'superseded', 'retracted', 'hidden', 'same-time',
          'unauthorised', 'authorised')
FIXTURE = json.loads((Path(__file__).parents[2] / 'schemas/fixtures/gen/world.json').read_bytes())


def base(path, seed):
    db = create_world(path, {'generator_version': 'g04', 'genre': 'G2', 'seed': seed, 'scale': 3})
    schedule = build_schedule(seed, LIFE, named('t0-micro', sessions=3))
    write_sessions(db, schedule)
    for name in ('principal', 'third', 'authorised', 'subject', 'other'):
        writers.insert_entity(db, id=name, kind='person', canonical_name=f'{name.title()}-7401',
                              aliases_json=[], created_t=0, retired_t=None)
    return db, [s.turn_t for s in schedule.sessions]


def ev(t, channel='chat', actor='principal', audience=('agent',)):
    return Ev(t_sim=t, kind='message', channel=channel, actor_id=actor, audience=audience,
              visibility='shared', salience=500)


def g01(db, event_id, t, fact=None, role='assert', channel='chat', audience=('agent',), **fields):
    """Evidence through G01's writers: an optional new fact, an event if new, and one link."""
    if fact and fields:
        writers.insert_fact(db, id=fact, **({'subject_id': 'subject', 'predicate': 'pred', 'polarity': 'affirm',
                                             'modality': 'stated', 'strength': 1000, 'speech_act': 'assert'} | fields))
    if not db.execute('SELECT 1 FROM event WHERE id = ?', (event_id,)).fetchone():
        writers.insert_event(db, id=event_id, t_sim=t, kind='message', channel=channel, actor_id='principal',
                             audience_json=list(audience), visibility='shared', salience=500, payload_json={})
    if fact:
        writers.insert_link(db, event_id=event_id, fact_id=fact, role=role)


def refused(db, fn, *args, **kwargs):
    """A refusal adds no row and keeps a row inserted earlier in the same uncommitted transaction."""
    marker = f"marker-{db.execute('SELECT count(*) FROM entity').fetchone()[0]}"
    writers.insert_entity(db, id=marker, kind='marker', canonical_name=marker, aliases_json=[],
                          created_t=0, retired_t=None)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        fn(*args, **kwargs)
    assert export_jsonl(db) == before
    assert db.in_transaction and db.execute('SELECT 1 FROM entity WHERE id = ?', (marker,)).fetchone()


def plant_draws(c):
    u = unit('g04', 'plants', str(c))

    def pick(name, seq):
        return choice('g04-properties', u, 0, name, seq)
    kind = pick('kind', sorted(PLANT_KINDS))
    return dict(kind=kind, channel=pick('channel', PLANT_KINDS[kind]), shape=pick('shape', SHAPES),
                speech_act=pick('speech_act', PLANT_SPEECH_ACTS), polarity=pick('polarity', ('affirm', 'negate')),
                strength=uniform_int('g04-properties', u, 0, 'strength', 0, 1000), actor=pick('actor', ('principal', 'third')),
                evidence_object=pick('evidence_object', ('v-true', 'v-plant')),
                evidence_polarity=pick('evidence_polarity', ('affirm', 'negate')))


def contradicts(d):
    """Evidence L contradicts plant P: the same object with opposite polarity, or both affirm different objects."""
    if d['evidence_object'] == 'v-plant':
        return d['evidence_polarity'] != d['polarity']
    return d['evidence_polarity'] == d['polarity'] == 'affirm'


def plant_case(path, c, twin=None, extra=False, shape=None):
    """Replay case c; with a Twin, write the twin world through G01's writers with the same ids."""
    d = plant_draws(c)
    parts = set((shape or d['shape']).split('+'))
    db, (s1, s2, s3) = base(path, f'g04-{c}')
    t = s3[0]
    if extra:
        write_plant(db, life=LIFE, key='extra', kind='third_party_claim', carrier=ev(s2[3], 'mail', 'third'),
                    subject_id='other', predicate='extra', object='v-extra', polarity='affirm',
                    speech_act='assert', strength=500)
    if parts & {'stated', 'observed', 'superseded', 'retracted', 'hidden', 'same-time'}:
        value = (d['evidence_object'], d['evidence_polarity'])
        if twin and twin.evidence_fact_id == 'f-l':
            value = (twin.evidence_object, twin.evidence_polarity)
        g01(db, 'e-l', t if 'same-time' in parts else s1[1], 'f-l', object=value[0], polarity=value[1],
            modality='observed' if 'observed' in parts else 'stated',
            channel='tool_result' if 'observed' in parts else 'chat',
            audience=('principal',) if 'hidden' in parts else ('agent',))
        if 'superseded' in parts:
            g01(db, 'e-agree', s2[0], 'f-agree', object='v-plant', polarity=d['polarity'])
        if 'retracted' in parts:
            g01(db, 'e-retract', s2[0], 'f-l', role='retract')
    if parts & {'unauthorised', 'authorised'}:
        write_authority_rule(db, life=LIFE, key='rule', event=ev(s1[2]), authorised_id='authorised', predicate='pred')
    actor = 'third' if 'unauthorised' in parts else 'authorised' if 'authorised' in parts else d['actor']
    claim = dict(subject_id='subject', predicate='pred', object='v-plant', polarity=d['polarity'],
                 speech_act=d['speech_act'], strength=d['strength'])
    if twin is None:
        return db, write_plant(db, life=LIFE, key='plant', kind=d['kind'], carrier=ev(t, d['channel'], actor), **claim)
    writers.insert_event(db, id=twin.carrier_event_id, t_sim=t, kind='message', channel=d['channel'],
                         actor_id=twin.actor_id, audience_json=['agent'], visibility='shared', salience=500,
                         payload_json={})
    writers.insert_fact(db, id=twin.fact_id, modality='stated', **claim)
    writers.insert_link(db, event_id=twin.carrier_event_id, fact_id=twin.fact_id, role='assert')
    return db, None


def render_inputs(db, event_id):
    head = tuple(db.execute('SELECT channel, kind FROM event WHERE id = ?', (event_id,)).fetchone())
    rows = db.execute(
        'SELECT l.fact_id, l.role, f.speech_act, f.strength, f.polarity, f.modality, n.canonical_name FROM link l '
        'JOIN fact f ON f.id = l.fact_id JOIN entity n ON n.id = f.subject_id WHERE l.event_id = ? '
        'ORDER BY l.fact_id, l.role', (event_id,))
    return head, [(*r[:5], 'stated' if r[5] == 'planted' else r[5], r[6]) for r in rows]


def keys(lines):
    rows = [json.loads(line) for line in lines]
    return {(r['table'], r['row'].get('id') or r['row'].get('fact_id')) for r in rows}


def check_twin(tmp_path, c, shape=None):
    shape = shape or plant_draws(c)['shape']
    db, p = plant_case(tmp_path / f'p{c}-{shape}.db', c, shape=shape)
    carrier = db.execute('SELECT * FROM event WHERE id = ?', (p.carrier_event_id,)).fetchone()
    assert p.kind == plant_draws(c)['kind'] and p.twin.channel == p.channel == carrier['channel']
    parts = set(shape.split('+'))
    evidence = bool(parts & {'stated', 'observed'}) and contradicts(plant_draws(c))
    basis = ('contradiction' if 'stated' in parts else 'verification') if evidence else (
        'authority_rule' if 'unauthorised' in parts else None)
    assert (p.rejection and p.rejection.basis) == basis
    if p.rejection:
        e = db.execute('SELECT * FROM event WHERE id = ?', (p.rejection.evidence_event_id,)).fetchone()
        assert e['t_sim'] < carrier['t_sim'] and 'agent' in json.loads(e['audience_json'])
        assert db.execute("SELECT 1 FROM link WHERE event_id = ? AND fact_id = ? AND role = 'assert'",
                          (e['id'], p.rejection.evidence_fact_id)).fetchone()
    db1, _ = plant_case(tmp_path / f't{c}-{shape}.db', c, twin=p.twin, shape=shape)
    a, b = set(export_jsonl(db).splitlines()), set(export_jsonl(db1).splitlines())
    expected = {('fact', p.fact_id), ('plant', p.fact_id)}
    expected |= {('event', p.carrier_event_id)} if 'unauthorised' in shape else set()
    expected |= {('fact', 'f-l')} if evidence else set()
    assert keys(a - b) == expected and keys(b - a) == expected - {('plant', p.fact_id)}
    assert rejection(db1, p.fact_id, p.carrier_event_id) is None
    assert render_inputs(db, p.carrier_event_id) == render_inputs(db1, p.carrier_event_id)
    export_world(db)
    export_world(db1)
    return p


def test_plant_property_loop(tmp_path):
    for c in range(CASES):
        check_twin(tmp_path, c)
    draws = [plant_draws(c) for c in range(CASES)]
    assert {d['shape'] for d in draws} == set(SHAPES)
    assert {(d['polarity'], d['evidence_polarity'], d['evidence_object']) for d in draws
            if d['shape'] in ('stated', 'observed')} == {(a, b, o) for a in ('affirm', 'negate')
                                                          for b in ('affirm', 'negate') for o in ('v-true', 'v-plant')}


def test_contradiction_precedes_authority(tmp_path):
    c = next(c for c in range(CASES) if contradicts(plant_draws(c)))
    p = check_twin(tmp_path, c, shape='stated+unauthorised')
    assert p.twin.actor_id == 'authorised' and p.twin.evidence_fact_id == 'f-l'
    assert (p.twin.evidence_object, p.twin.evidence_polarity) == ('v-plant', plant_draws(c)['polarity'])
    c = next(c for c in range(CASES) if not contradicts(plant_draws(c)))
    p = check_twin(tmp_path, c, shape='stated+unauthorised')
    assert p.rejection.basis == 'authority_rule' and p.twin.evidence_fact_id is None


def test_false_premise_current_is_judged_apart(tmp_path):
    db, (s1, _, s3) = base(tmp_path / 'w.db', 'g04-fp')
    g01(db, 'e-old', s1[0], 'f-old', predicate='pref', object='v-old')
    p = write_plant(db, life=LIFE, key='fp', kind='false_premise', carrier=ev(s3[0]), subject_id='subject',
                    predicate='pred', object='v-plant', polarity='affirm', speech_act='quote', strength=700,
                    current=Current('subject', 'pref', 'v-now'))
    q = db.execute('SELECT * FROM fact WHERE id = ?', (p.current_fact_id,)).fetchone()
    assert (q['modality'], q['polarity'], q['strength'], q['speech_act'], q['object']) == (
        'stated', 'affirm', 1000, 'assert', '"v-now"')
    assert db.execute("SELECT 1 FROM link WHERE event_id = ? AND fact_id = ? AND role = 'assert'",
                      (p.carrier_event_id, q['id'])).fetchone()
    assert p.rejection is None and p.twin.evidence_fact_id is None and p.twin.actor_id == 'principal'
    g01(db, 'e-l', s1[1], 'f-l', object='v-true')
    p = plant(db, p.fact_id)
    assert (p.rejection.basis, p.rejection.evidence_fact_id, p.twin.evidence_fact_id) == ('contradiction',) + ('f-l',) * 2
    assert plants.plants(db) == (p,)


def test_write_plant_refusals(tmp_path):
    db, (_, _, s3) = base(tmp_path / 'w.db', 'g04-refusals')
    good = dict(life=LIFE, key='k', kind='third_party_claim', carrier=ev(s3[0]), subject_id='subject',
                predicate='pred', object='v', polarity='affirm', speech_act='assert', strength=500)
    for change in ({'kind': 'nope'}, {'kind': 'poisoned_tool_output', 'carrier': ev(s3[0], 'tool_result')},
                   {'kind': 'forged_agreement', 'carrier': ev(s3[0], 'tool_result')},
                   {'kind': 'forged_agreement', 'current': Current('subject', 'now', 'v')},
                   {'speech_act': 'hedge'}, {'object': 7}, {'predicate': 'forget'},
                   {'predicate': 'authorised_for'}, {'carrier': ev(s3[0], audience=('principal',))},
                   {'carrier': ev(s3[-1] + 10 ** 6)}):
        refused(db, write_plant, db, **(good | change))
    write_plant(db, **good)
    refused(db, write_plant, db, **good)
    refused(db, write_authority_rule, db, life=LIFE, key='r', event=ev(s3[1], 'tool_result'),
            authorised_id='authorised', predicate='pred')


def test_plant_refuses_token_flip_and_ties(tmp_path):
    db, (s1, _, s3) = base(tmp_path / 'a.db', 'g04-ties')
    g01(db, 'e-l', s1[1], 'f-l', object='v-true')
    p = write_plant(db, life=LIFE, key='p', kind='forged_agreement', carrier=ev(s3[0], 'mail'), subject_id='subject',
                    predicate='pred', object='v-plant', polarity='affirm', speech_act='assert', strength=500)
    writers.insert_locked_token(db, token_id='tok', fact_id='f-l', kind='code', value='CODE-1')
    with pytest.raises(ValueError):
        plant(db, p.fact_id)
    claim = dict(life=LIFE, key='p2', kind='false_premise', carrier=ev(s3[1]), subject_id='subject',
                 predicate='pred', object='v-plant', polarity='affirm', speech_act='assert', strength=500)
    refused(db, write_plant, db, **claim)
    for values in (('v-a', 'v-b'), ('v-a', 'v-a')):
        for order in ('ab', 'ba'):
            db, (s1, _, s3) = base(tmp_path / f'{values[1]}-{order}.db', 'g04-ties')
            for name in order:
                g01(db, 'e-l', s1[1], f'f-{name}', object=values['ab'.index(name)])
            refused(db, write_plant, db, **claim)
    db, (s1, _, s3) = base(tmp_path / 'read.db', 'g04-ties')
    g01(db, 'e-l', s1[1], 'f-a', object='v-a')
    assert write_plant(db, **claim).rejection == Rejection('contradiction', 'f-a', 'e-l')
    g01(db, 'e-l2', s1[1], 'f-b', object='v-a')
    with pytest.raises(ValueError):
        plants.plants(db)


def test_record_refusals_and_fixture_closure(tmp_path):
    db, (s1, s2, _) = base(tmp_path / 'w.db', 'g04-record')
    g01(db, 'e-1', s1[0], 'd1', object='x')
    g01(db, 'e-2', s1[1], 'd2', object='y')
    g01(db, 'e-same', s1[0])
    record(db, artifact_kind='fact', artifact_id='d2', sources=('d1',))
    record(db, artifact_kind='event', artifact_id='e-2', sources=('d1',))
    for kind, artifact, sources in (('note', 'd2', ('d1',)), ('fact', 'nope', ('d1',)), ('fact', 'd2', ()),
                                    ('fact', 'd2', ('d1', 'd1')), ('fact', 'd1', ('e-1',)),
                                    ('fact', 'd1', ('d2',)), ('fact', 'd1', ('d1',)),
                                    ('event', 'e-same', ('d1',)), ('event', 'e-1', ('d2',))):
        refused(db, record, db, artifact_kind=kind, artifact_id=artifact, sources=sources)
    assert closure(db, ['d1']) == lineage.Closure(frozenset({'d2'}), frozenset({'e-2'}), frozenset())
    assert closure(db, ['d2']) == lineage.Closure(*[frozenset()] * 3)
    fx = create_world(tmp_path / 'fx.db', {'generator_version': 'g04', 'genre': 'G2', 'seed': 's', 'scale': 1})
    for table in ('entity', 'event', 'fact', 'link', 'lineage'):
        for row in FIXTURE[table]:
            getattr(writers, f'insert_{table}')(fx, **row)
    note = FIXTURE['lineage'][0]
    assert closure(fx, [note['source_fact_id']]) == lineage.Closure(
        frozenset(), frozenset(), frozenset({('note', note['artifact_id'])}))


def test_atomic_without_open_transaction(tmp_path):
    db, (s1, _, _) = base(tmp_path / 'w.db', 'g04-atomic')
    db.commit()
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_authority_rule(db, life=LIFE, key='r', event=ev(s1[0], 'tool_result'), authorised_id='authorised',
                             predicate='pred')
    assert export_jsonl(db) == before
    write_authority_rule(db, life=LIFE, key='r', event=ev(s1[0]), authorised_id='authorised', predicate='pred')
    assert db.in_transaction
    db.rollback()
    assert export_jsonl(db) == before


def forget_draws(c):
    u = unit('g04', 'forget', str(c))
    return {name: uniform_int('g04-properties', u, 0, name, lo, hi) for name, lo, hi in (
        ('k', 1, 3), ('m', 1, 3), ('d', 0, 3), ('j', 0, 2), ('decoy', 0, 1), ('mutation', 1, 5))}


def forget_case(path, c, mutation=None):
    """The world of forget case c, the request event and its predicates, and the expected sets."""
    n = forget_draws(c)
    k, m, d, j = n['k'], n['m'], n['d'], n['j']
    db, (s1, s2, s3) = base(path, f'g04-{c}')

    def fact(fid, t, predicate, subject='subject', token=True):
        g01(db, f'e-{fid}', t, fid, subject_id=subject, predicate=predicate, object=f'v-{fid}')
        if token:
            writers.insert_locked_token(db, token_id=f'tok-{fid}', fact_id=fid, kind='code', value=f'TOK-{c}-{fid}')
    covered = [f'c{i}' for i in range(k)]
    for i, fid in enumerate(covered):
        fact(fid, s1[i], f'cov-{i}', token=not (mutation == 3 and i == 0))
    neighbours = [] if mutation == 2 else [f'n{i}' for i in range(m)]
    for i, fid in enumerate(neighbours):
        fact(fid, s1[i + 1], f'nb-{i}')
    omit = mutation == 1 and ('e-s0' if j else 'e-d1')
    parent, chain = 'c0', [f'd{i}' for i in range(1, d + 1)]
    for i, fid in enumerate(chain):
        fact(fid, s2[i], f'summary-{i}')
        record(db, artifact_kind='fact', artifact_id=fid, sources=(parent,))
        if omit != f'e-{fid}':
            record(db, artifact_kind='event', artifact_id=f'e-{fid}', sources=(parent,))
        parent = fid
    summaries = [f'e-s{i}' for i in range(j)]
    for i, eid in enumerate(summaries):
        g01(db, eid, s2[3 + i], covered[i % k], role='mention')
        if omit != eid:
            record(db, artifact_kind='event', artifact_id=eid, sources=(covered[i % k],))
    if mutation == 1 and not d + j:
        g01(db, 'e-copy', s2[0], 'c0', role='mention')
    if n['decoy']:
        fact('y0', s1[0], 'cov-0', subject='other')
    if mutation == 4:
        g01(db, 'e-late', s3[4], 'c0', role='mention')
    if mutation == 5:
        g01(db, 'e-again', s2[0], 'c0')
    predicates = tuple(f'cov-{i}' for i in reversed(range(k)))
    expected = dict(covered=tuple(covered), neighbours=tuple(neighbours), derived_facts=tuple(chain),
                    derived_events=tuple(sorted([f'e-{f}' for f in chain] + summaries)))
    return db, ev(s3[2]), predicates, expected


def request(db, event, predicates, key='forget'):
    return request_forget(db, life=LIFE, key=key, event=event, subject_id='subject', predicates=predicates)


def test_forget_property_loop(tmp_path):
    mutations = set()
    for c in range(CASES):
        db, event, predicates, expected = forget_case(tmp_path / f'f{c}.db', c)
        fr = request(db, event, predicates)
        assert {name: getattr(fr, name) for name in expected} == expected
        assert fr.selector == tuple(sorted(f'TOK-{c}-{f}' for f in expected['covered']))
        assert fr.predicates == tuple(sorted(predicates)) and fr.subject_id == 'subject'
        assert len(fr.request_fact_ids) == len(predicates) and fr == forget_request(db, fr.event_id)
        assert set(fr.derived_events) <= closure(db, fr.covered).events
        assert not set(fr.neighbours) & (set(fr.covered) | set(fr.derived_facts))
        verify(db)
        export_world(db)
        mutation = forget_draws(c)['mutation']
        mutations.add(mutation)
        db, event, predicates, _ = forget_case(tmp_path / f'm{c}.db', c, mutation)
        refused(db, request, db, event, predicates)
    assert mutations == {1, 2, 3, 4, 5}


def test_forget_refusals_and_verify(tmp_path):
    db, event, predicates, _ = forget_case(tmp_path / 'w.db', 0)
    channel = replace(event, channel='tool_result')
    for args in ((event, ()), (event, ('cov-0', 'forget')), (event, ('cov-0', 'cov-0')), (channel, predicates),
                 (event, ('absent',))):
        refused(db, request, db, *args)
    fr = request(db, event, predicates)
    verify(db)
    g01(db, 'e-after', event.t_sim + 1, fr.covered[0], role='mention')
    with pytest.raises(ValueError):
        verify(db)
    db, event, predicates, _ = forget_case(tmp_path / 'v.db', 0)
    fr = request(db, event, predicates)
    g01(db, 'e-again', event.t_sim - 1, fr.covered[0])
    with pytest.raises(ValueError):
        verify(db)


def hashes():
    with tempfile.TemporaryDirectory() as tmp:
        out = [world_hash(plant_case(Path(tmp) / f'p{c}.db', c)[0]) for c in range(10)]
        for c in range(10):
            db, event, predicates, _ = forget_case(Path(tmp) / f'f{c}.db', c)
            request(db, event, predicates)
            out.append(world_hash(db))
    return out


def test_determinism(tmp_path):
    code = (f'import sys; sys.path.insert(0, {str(Path(__file__).parents[1])!r}); '
            'import json; from world.test_processes_b import hashes; print(json.dumps(hashes()))')
    outs = [subprocess.run([sys.executable, '-c', code], check=True, capture_output=True, text=True,
                           env={**os.environ, 'PYTHONHASHSEED': seed}).stdout for seed in ('0', 'random')]
    assert outs[0] == outs[1] and len(set(json.loads(outs[0]))) == 20
    for c in range(50):
        alone = set(export_jsonl(plant_case(tmp_path / f'a{c}.db', c)[0]).splitlines())
        with_extra = set(export_jsonl(plant_case(tmp_path / f'b{c}.db', c, extra=True)[0]).splitlines())
        assert alone < with_extra


def test_import_boundary():
    banned = {'random', 'time', 'socket', 'bicentennial.sandbox'}
    for module in (lineage, plants, forget):
        for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ''] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == b or n.startswith(b + '.') for n in names for b in banned)
