"""Canonical logical exports, independent of SQLite layout and insertion order."""

import json
import sqlite3
from hashlib import sha256

from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS, validate

from .db import JSON_COLUMNS, TABLES


def _rows(db: sqlite3.Connection, table: str) -> list[dict]:
    return [{k: json.loads(v) if k in JSON_COLUMNS or (table == 'attr' and k == 'value')
             else v for k, v in dict(row).items()} for row in db.execute(f'SELECT * FROM {table}')]


def export_jsonl(db: sqlite3.Connection) -> bytes:
    lines = [canon({'table': table, 'row': row}) for table in TABLES for row in _rows(db, table)]
    return b'\n'.join(sorted(lines)) + b'\n'


def world_hash(db: sqlite3.Connection) -> str:
    return sha256(export_jsonl(db)).hexdigest()


def export_world(db: sqlite3.Connection) -> dict:
    canary = json.loads((SCHEMAS / 'world.schema.json').read_bytes())['properties']['canary']['enum'][0]
    value = {'canary': canary, **{table: sorted(_rows(db, table), key=canon)
             for table in ('entity', 'attr', 'event', 'fact', 'link', 'lineage')}}
    validate('world', value)
    return value
