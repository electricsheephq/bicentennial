"""Seeded properties use K10 keyed draws, with 200 cases per property."""

import json
import sqlite3
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import draw, shuffle, uniform_int
from bicentennial.world import (
    as_known,
    as_valid,
    create_world,
    export_jsonl,
    export_world,
    open_world,
    unit,
    world_hash,
)
from bicentennial.world import db as writers
from bicentennial.world.bitemporal import insert_attr

CASES = 200
META = dict(generator_version='g01', genre='software-partner', seed='g01-properties', scale=1)
FIXTURE = json.loads(Path('schemas/fixtures/gen/world.json').read_bytes())
SIX = ('entity', 'event', 'attr', 'fact', 'link', 'lineage')


def number(case, name, lo, hi):
    return uniform_int('g01-properties', unit('life', 'core', str(case)), 0, name, lo, hi)


def build(path, case=0, reverse=False):
    db = create_world(path, META)
    for table in SIX:
        for row in FIXTURE[table]:
            getattr(writers, f'insert_{table}')(db, **row)
    fact_id = FIXTURE['fact'][0]['id']
    event_id = FIXTURE['event'][0]['id']
    writers.insert_commitment(db, fact_id=fact_id, trigger_kind='tuesday',
                              window_open_t=10, window_close_t=20, lures_json=['early', 'late'])
    writers.insert_plant(db, fact_id=fact_id, carrier_event_id=event_id, kind='quoted')
    writers.insert_forget_request(db, event_id=event_id, covered_fact_ids_json=[fact_id])
    writers.insert_locked_token(db, token_id='token', fact_id=fact_id, kind='code', value='CODE')
    writers.insert_fact_surface(db, fact_id=fact_id, surface='notes', from_t=0)
    indexes = shuffle('g01-properties', unit('life', 'sessions', str(case)), 0, 'order', range(5))
    if reverse:
        indexes.reverse()
    for index in indexes:
        writers.insert_session(db, idx=index, t_start=number(case, f'start-{index}', -100, 100),
                               t_end=1000, kind=f'work-{case}')
    db.commit()
    return db


@pytest.fixture
def populated(tmp_path):
    db = build(tmp_path / 'world.sqlite')
    yield db
    db.close()


def test_append_only_every_table(populated):
    assert set(writers.TABLES) == {r[0] for r in populated.execute(
        "SELECT name FROM sqlite_schema WHERE type='table'")}
    assert len(writers.TABLES) == 13
    for case in range(CASES):
        for table in writers.TABLES:
            before = [tuple(row) for row in populated.execute(f'SELECT * FROM {table}')]
            rowids = [r[0] for r in populated.execute(f'SELECT rowid FROM {table}')]
            rowid = rowids[number(case, table, 0, len(rowids) - 1)]
            column = populated.execute(f'PRAGMA table_info({table})').fetchone()['name']
            for statement in (f'UPDATE {table} SET {column}={column} WHERE rowid=?',
                              f'DELETE FROM {table} WHERE rowid=?'):
                with pytest.raises(sqlite3.IntegrityError, match='append-only'):
                    populated.execute(statement, (rowid,))
                assert [tuple(r) for r in populated.execute(f'SELECT * FROM {table}')] == before
    # REPLACE internally deletes existing rows; recursive triggers must catch it too.
    for table in writers.TABLES:
        before = export_jsonl(populated)
        with pytest.raises(sqlite3.IntegrityError):
            populated.execute(f'INSERT OR REPLACE INTO {table} SELECT * FROM {table}')
        assert export_jsonl(populated) == before


def history(db, case):
    key = f'history-{case}'
    start = number(case, 'start', -50, 50)
    rows = []
    for index in range(number(case, 'length', 2, 7)):
        end = start + number(case, f'duration-{index}', 1, 20)
        recorded = max(0, start) + number(case, f'lag-{index}', 0, 30)
        rows.append(dict(entity_id=FIXTURE['entity'][0]['id'], key=key,
                         value={'revision': index, 'recorded': recorded}, valid_from_t=start,
                         valid_to_t=end, recorded_t=recorded, source_event_id='source'))
        start = end + number(case, f'gap-{index}', 0, 5)
    rows[-1]['valid_to_t'] = None
    for row in shuffle('g01-properties', unit('life', 'history', str(case)), 0, 'insert', rows):
        insert_attr(db, **row)
    return rows


def source(db):
    row = {**FIXTURE['event'][0], 'id': 'source', 't_sim': 0}
    writers.insert_event(db, **row)


def test_generated_intervals_and_known_property(populated):
    source(populated)
    entity = FIXTURE['entity'][0]['id']
    for case in range(CASES):
        rows = history(populated, case)
        for left, right in zip(rows, rows[1:], strict=False):
            assert left['valid_to_t'] <= right['valid_from_t']
        for row in rows:
            assert as_valid(populated, entity, row['key'], row['valid_from_t']) == row['value']
        victim = rows[number(case, 'victim', 0, len(rows) - 1)]
        before = export_jsonl(populated)
        # A different start still overlaps, including the unbounded final interval.
        overlap = {**victim, 'valid_from_t': victim['valid_from_t'] - 1,
                   'valid_to_t': victim['valid_from_t'] + 1}
        with pytest.raises(sqlite3.IntegrityError, match='overlapping'):
            insert_attr(populated, **overlap)
        assert export_jsonl(populated) == before
        for t in range(-60, rows[-1]['recorded_t'] + rows[-1]['valid_from_t'] + 70):
            eligible = [r for r in rows if r['recorded_t'] <= t and r['valid_from_t'] <= t]
            expected = max(eligible, key=lambda r: r['valid_from_t'])['value'] if eligible else None
            known = as_known(populated, entity, victim['key'], t)
            assert known == expected
            assert known is None or known['recorded'] <= t
        with pytest.raises(sqlite3.IntegrityError, match='recorded before source'):
            insert_attr(populated, **{**rows[0], 'key': f'early-{case}', 'recorded_t': -1})


def test_late_revelation_fixture(populated):
    source(populated)
    entity = FIXTURE['entity'][0]['id']
    for case in range(CASES):
        shift = 0 if case == 0 else number(case, 'shift', 0, 1000)
        key = f'late-{case}'
        for value, start, end, recorded in (('X', 0, 10, 0), ('Y', 10, None, 20)):
            insert_attr(populated, entity_id=entity, key=key, value=value,
                        valid_from_t=start + shift, valid_to_t=None if end is None else end + shift,
                        recorded_t=recorded + shift, source_event_id='source')
        assert as_valid(populated, entity, key, shift + 15) == 'Y'
        assert as_known(populated, entity, key, shift + 15) == 'X'
        assert as_known(populated, entity, key, shift + 20) == 'Y'
        assert as_valid(populated, entity, key, shift - 1) is None
        assert as_known(populated, entity, key, shift - 1) is None


def test_export_and_hash_across_orders_and_processes(tmp_path):
    paths = []
    expected = []
    for case in range(CASES):
        first_path = tmp_path / f'{case}.sqlite'
        second_path = tmp_path / f'{case}-reverse.sqlite'
        first = build(first_path, case)
        second = build(second_path, case, reverse=True)
        try:
            raw = export_jsonl(first)
            assert raw.endswith(b'\n')
            assert raw.splitlines() == sorted(raw.splitlines())
            assert all(canon(json.loads(line)) == line for line in raw.splitlines())
            assert {json.loads(line)['table'] for line in raw.splitlines()} == set(writers.TABLES)
            assert world_hash(first) == world_hash(second) == sha256(raw).hexdigest()
            expected.append(world_hash(first))
            paths.append(str(first_path))
            value = export_world(first)
            validate('world', value)
            assert value == FIXTURE
            assert all(value[table] == sorted(value[table], key=canon) for table in SIX)
        finally:
            first.close()
            second.close()
    code = (
        'import json,sys; from bicentennial.world import open_world,world_hash; '
        'result=[]\n'
        'for path in json.load(sys.stdin):\n'
        ' db=open_world(path); result.append(world_hash(db)); db.close()\n'
        'print(json.dumps(result))'
    )
    outputs = []
    for hashseed in ('0', 'random'):
        output = subprocess.run([sys.executable, '-c', code], input=json.dumps(paths), text=True,
                                env={'PYTHONHASHSEED': hashseed}, capture_output=True, check=True)
        outputs.append(json.loads(output.stdout))
    assert outputs == [expected, expected]


def test_extra_unit_preserves_existing_draws():
    for case in range(CASES):
        ids = [str(index) for index in range(number(case, 'units', 1, 30))]
        def draws(unit_ids, case=case):
            return {uid: [draw(str(case), unit('life', 'process', uid), attempt, name)
                          for attempt in range(3) for name in ('time', 'value')]
                    for uid in unit_ids}
        before = draws(ids)
        position = number(case, 'position', 0, len(ids))
        after = draws(ids[:position] + ['extra'] + ids[position:])
        assert all(after[uid] == before[uid] for uid in ids)
        assert unit('life', 'process', str(case)) == ('life', 'process', str(case))
    for invalid in ('', None, 1):
        with pytest.raises(ValueError):
            unit('life', 'process', invalid)


def test_readonly_existing_file_and_connections(tmp_path):
    for case in range(CASES):
        path = tmp_path / f'ro-{case}?#.sqlite'
        writer = create_world(path, META)
        writer.close()
        before = path.read_bytes()
        with pytest.raises(FileExistsError):
            create_world(path, META)
        assert path.read_bytes() == before
        with pytest.raises(ValueError, match='writers require create_world'):
            open_world(path, readonly=False)
        reader = open_world(path, readonly=True)
        try:
            assert reader.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                writers.insert_session(reader, idx=0, t_start=0, t_end=1, kind='work')
            assert not reader.execute('SELECT * FROM session').fetchall()
        finally:
            reader.close()


def test_json_canonical_foreign_keys_and_integer_constraints(populated):
    assert populated.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert not populated.execute('PRAGMA foreign_key_check').fetchall()
    cases = [
        ('INSERT INTO entity VALUES(?,?,?,?,?,?)', ('new', 'person', 'New', '[ "alias" ]', 0, None)),
        ('INSERT INTO entity VALUES(?,?,?,?,?,?)', ('new', 'person', 'New', '[1.2]', 0, None)),
        ('INSERT INTO entity VALUES(?,?,?,?,?,?)', ('new', 'person', 'New', '{}', 0, None)),
        ('INSERT INTO session VALUES(?,?,?,?)', (6, 0.5, 10, 'work')),
        ('INSERT INTO session VALUES(?,?,?,?)', (6, 10, 10, 'work')),
        ('INSERT INTO locked_token VALUES(?,?,?,?)', ('new', FIXTURE['fact'][0]['id'], 'code', 'abc')),
        ('INSERT INTO locked_token VALUES(?,?,?,?)', ('new', 'missing', 'code', 'ABCD')),
        ('INSERT INTO fact_surface VALUES(?,?,?)', ('missing', 'notes', 0)),
        ('INSERT INTO fact_surface VALUES(?,?,?)', (FIXTURE['fact'][0]['id'], 'chat', 0)),
        ('INSERT INTO forget_request VALUES(?,?)', (FIXTURE['event'][0]['id'], '["missing"]')),
    ]
    before = export_jsonl(populated)
    for statement, args in cases:
        with pytest.raises(sqlite3.IntegrityError):
            populated.execute(statement, args)
        assert export_jsonl(populated) == before
    with pytest.raises(TypeError, match='unsupported canonical JSON type'):
        writers.insert_fact(populated, **{**FIXTURE['fact'][0], 'id': 'float', 'object': {'x': 1.2}})


def test_json_values_round_trip_and_all_export_rows_sorted(populated):
    source(populated)
    entity = FIXTURE['entity'][0]['id']
    for case in range(CASES):
        value = [None, True, False, number(case, 'int', -1000, 1000),
                 {'unicode': 'λ雪', 'nested': [case]}][case % 5]
        insert_attr(populated, entity_id=entity, key=f'json-{case}', value=value,
                    valid_from_t=0, valid_to_t=None, recorded_t=0, source_event_id='source')
        assert as_valid(populated, entity, f'json-{case}', 0) == value
        assert as_known(populated, entity, f'json-{case}', 0) == value
    exported = export_world(populated)
    validate('world', exported)
    for table in SIX:
        assert list(map(canon, exported[table])) == sorted(map(canon, exported[table]))
