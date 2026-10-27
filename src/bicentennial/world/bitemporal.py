"""Valid truth and record-time belief; insertion rules are enforced by SQL."""

import json
import sqlite3

from .db import JSON
from .db import insert_attr as insert_attr


def as_valid(db: sqlite3.Connection, entity_id: str, key: str, t: int) -> JSON:
    row = db.execute('SELECT value FROM attr WHERE entity_id=? AND key=? '
                     'AND valid_from_t <= ? AND (valid_to_t IS NULL OR ? < valid_to_t)',
                     (entity_id, key, t, t)).fetchone()
    return json.loads(row[0]) if row else None


def as_known(db: sqlite3.Connection, entity_id: str, key: str, t: int) -> JSON:
    row = db.execute('SELECT value FROM attr WHERE entity_id=? AND key=? '
                     'AND recorded_t <= ? AND valid_from_t <= ? ORDER BY valid_from_t DESC LIMIT 1',
                     (entity_id, key, t, t)).fetchone()
    return json.loads(row[0]) if row else None
