"""Exclusive creation and typed append-only writers; JSON arguments are values."""

import json
import sqlite3
from pathlib import Path
from typing import Literal, TypedDict

from bicentennial.canon import canon

type JSON = str | int | bool | None | list[JSON] | dict[str, JSON]
TABLES = ('meta', 'entity', 'event', 'attr', 'fact', 'link', 'lineage', 'session',
          'commitment', 'plant', 'forget_request', 'locked_token', 'fact_surface')
JSON_COLUMNS = {'aliases_json', 'audience_json', 'payload_json', 'object',
                'lures_json', 'covered_fact_ids_json'}


class Meta(TypedDict):
    generator_version: str
    genre: str
    seed: str
    scale: int


def _canonical_json(raw: str, shape: str) -> bool:
    try:
        value = json.loads(raw)
        return canon(value).decode() == raw and (
            shape == 'any' or (shape == 'object' and type(value) is dict)
            or (shape == 'array' and type(value) is list)
            or (shape == 'strings' and type(value) is list
                and all(type(v) is str and v and '\n' not in v for v in value)))
    except (ValueError, TypeError, RecursionError):
        return False


def _connect(path: Path, mode: str) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + f'?mode={mode}', uri=True)
    db.row_factory = sqlite3.Row
    db.create_function('canonical_json', 2, _canonical_json, deterministic=True)
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA recursive_triggers=ON')
    return db


def create_world(path: str | Path, meta: Meta) -> sqlite3.Connection:
    """Reserve a new file exclusively; callers commit their generated history."""
    path = Path(path)
    with path.open('xb'):
        pass
    db = None
    try:
        db = _connect(path, 'rw')
        db.executescript(Path(__file__).with_name('schema.sql').read_text())
        for table in TABLES:
            for action in ('UPDATE', 'DELETE'):
                db.execute(f'CREATE TRIGGER {table}_{action} BEFORE {action} ON {table} '
                           "BEGIN SELECT RAISE(ABORT, 'append-only'); END")
            # K12 strings must be nonempty and cannot contain newlines.
            columns = db.execute(f'PRAGMA table_info({table})').fetchall()
            checks = [f"NEW.{r['name']} = '' OR instr(NEW.{r['name']}, char(10)) > 0"
                      for r in columns if r['type'] == 'TEXT'
                      and r['name'] not in JSON_COLUMNS and not (table == 'attr' and r['name'] == 'value')]
            if checks:
                db.execute(f'CREATE TRIGGER {table}_strings BEFORE INSERT ON {table} '
                           f"WHEN {' OR '.join(checks)} BEGIN SELECT RAISE(ABORT, 'empty or multiline string'); END")
        insert_meta(db, **meta)
        db.commit()
        return db
    except BaseException:
        # The file was reserved by this call, so a failed build leaves no partial world.
        if db is not None:
            db.close()
        path.unlink(missing_ok=True)
        raise


def open_world(path: str | Path, readonly: bool = True) -> sqlite3.Connection:
    if not readonly:
        raise ValueError('writers require create_world')
    return _connect(Path(path), 'ro')


def _insert(db: sqlite3.Connection, table: str, fields: dict) -> None:
    values = {k: canon(v).decode() if k in JSON_COLUMNS or (table == 'attr' and k == 'value')
              else v for k, v in fields.items() if k != 'db'}
    db.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})',
               tuple(values.values()))


def insert_meta(db: sqlite3.Connection, *, generator_version: str, genre: str, seed: str, scale: int) -> None:
    _insert(db, 'meta', locals())


def insert_entity(db: sqlite3.Connection, *, id: str, kind: str, canonical_name: str,
                  aliases_json: list[str], created_t: int, retired_t: int | None) -> None:
    _insert(db, 'entity', locals())


def insert_event(db: sqlite3.Connection, *, id: str, t_sim: int, kind: str, channel: str,
                 actor_id: str, audience_json: list[str], visibility: str, salience: int,
                 payload_json: dict[str, JSON]) -> None:
    _insert(db, 'event', locals())


def insert_attr(db: sqlite3.Connection, *, entity_id: str, key: str, value: JSON,
                valid_from_t: int, valid_to_t: int | None, recorded_t: int, source_event_id: str) -> None:
    _insert(db, 'attr', locals())


def insert_fact(db: sqlite3.Connection, *, id: str, subject_id: str, predicate: str, object: JSON,
                polarity: Literal['affirm', 'negate'],
                modality: Literal['stated', 'observed', 'inferred_allowed', 'retracted', 'planted'],
                strength: int, speech_act: str) -> None:
    _insert(db, 'fact', locals())


def insert_link(db: sqlite3.Connection, *, event_id: str, fact_id: str,
                role: Literal['assert', 'retract', 'mention']) -> None:
    _insert(db, 'link', locals())


def insert_lineage(db: sqlite3.Connection, *, artifact_id: str, artifact_kind: str, source_fact_id: str) -> None:
    _insert(db, 'lineage', locals())


def insert_session(db: sqlite3.Connection, *, idx: int, t_start: int, t_end: int, kind: str) -> None:
    _insert(db, 'session', locals())


def insert_commitment(db: sqlite3.Connection, *, fact_id: str, trigger_kind: str,
                      window_open_t: int, window_close_t: int, lures_json: list[JSON]) -> None:
    _insert(db, 'commitment', locals())


def insert_plant(db: sqlite3.Connection, *, fact_id: str, carrier_event_id: str, kind: str) -> None:
    _insert(db, 'plant', locals())


def insert_forget_request(db: sqlite3.Connection, *, event_id: str, covered_fact_ids_json: list[str]) -> None:
    _insert(db, 'forget_request', locals())


def insert_locked_token(db: sqlite3.Connection, *, token_id: str, fact_id: str,
                        kind: Literal['number', 'name', 'date', 'code'], value: str) -> None:
    _insert(db, 'locked_token', locals())


def insert_fact_surface(db: sqlite3.Connection, *, fact_id: str,
                        surface: Literal['mail', 'notes', 'repo', 'tracker', 'calendar'], from_t: int) -> None:
    _insert(db, 'fact_surface', locals())
