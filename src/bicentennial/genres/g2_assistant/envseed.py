"""Per-session G2 environment seeds: a pure, read-only projection of the world strictly before a cut.

The projection reads only the delivering event, its linked facts' content and attr histories, so a
source twin and its genuine counterpart project identically (DESIGN §5.1a). Labels never enter state.
"""

import json
from dataclasses import dataclass
from functools import cache
from types import MappingProxyType

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.keyed import mint_id
from bicentennial.world import as_known, as_valid
from bicentennial.world.scale import HEARTBEAT_S

from .world import ENV_SURFACES

ENV_ID = "g2-assistant-v1"
COLLECTIONS = ("bookings", "calendar", "inventory", "mail", "notes")
_FIELDS = ("name", "description", "op", "collection", "key_arg", "value_arg")
TOOLS = tuple(MappingProxyType(dict(zip(_FIELDS, row, strict=True))) for row in (
    ("get_mail", "Read one mail message.", "get", "mail", "id", None),
    ("get_note", "Read one note.", "get", "notes", "id", None),
    ("get_calendar_entry", "Read one calendar entry.", "get", "calendar", "id", None),
    ("get_booking", "Read one booking.", "get", "bookings", "id", None),
    ("get_option", "Read one bookable option.", "get", "inventory", "id", None),
    ("book", "Create or change a booking.", "set", "bookings", "id", "booking"),
    ("cancel_booking", "Cancel a booking.", "remove", "bookings", "id", None),
    ("add_note", "Add a note.", "add", "notes", "id", "note"),
    ("send_mail", "Send a mail message.", "add", "mail", "id", "message"),
    ("add_calendar_entry", "Add a calendar entry.", "add", "calendar", "id", "entry"),
))


@dataclass(frozen=True)
class EnvSeed:
    seed: dict
    labels: dict[str, bool]
    env_state_hash: str


@cache
def _canary() -> str:
    return json.loads((SCHEMAS / "env_seed.schema.json").read_bytes())["properties"]["canary"]["enum"][0]


def env_key(seed, kind, ident) -> str:
    return mint_id(canon([seed, "g2-env", kind, ident]).decode(), 0)


def state_at(db, cut) -> tuple[dict, dict[str, bool]]:
    """(state, labels): everything with t_sim, recorded_t or validity at or before the cut."""
    if type(cut) is not int:
        raise ValueError("cut must be an int")
    seed = db.execute("SELECT seed FROM meta").fetchone()[0]
    names = dict(db.execute("SELECT id, canonical_name FROM entity").fetchall())
    state, labels = {c: {} for c in COLLECTIONS}, {}
    marks = ",".join("?" * len(ENV_SURFACES))
    for e in db.execute(f"SELECT id, t_sim, channel, actor_id FROM event WHERE t_sim <= ? AND channel IN ({marks})",
                        (cut, *ENV_SURFACES)).fetchall():
        items = [[names[f[0]], f[1], json.loads(f[2]), f[3], f[4], "hard" if f[5] == 1000 else "soft"]
                 for f in db.execute("SELECT f.subject_id, f.predicate, f.object, f.polarity, f.speech_act, f.strength "
                                     "FROM link l JOIN fact f ON f.id = l.fact_id WHERE l.event_id = ? "
                                     "AND l.role IN ('assert', 'mention')", (e[0],))]
        state[e[2]][env_key(seed, e[2], e[0])] = {"t_sim": e[1], "from": names[e[3]], "items": sorted(items, key=canon)}
    for (entity_id,) in db.execute("SELECT id FROM entity WHERE kind = 'booking' ORDER BY id").fetchall():
        keys = [k for (k,) in db.execute("SELECT DISTINCT key FROM attr WHERE entity_id = ? ORDER BY key", (entity_id,))]
        value = {k: v for k in keys if (v := as_valid(db, entity_id, k, cut)) is not None}
        if value:
            state["bookings"][env_key(seed, "booking", entity_id)] = value
    for entity_id, raw in db.execute(
            "SELECT a.entity_id, a.value FROM attr a JOIN entity n ON n.id = a.entity_id WHERE n.kind = 'preference' "
            "AND a.key = 'preference' AND a.recorded_t <= ? ORDER BY a.entity_id", (cut,)).fetchall():
        meta = json.loads(raw)
        if meta["provenance"] != "stated":
            continue
        kind, ref = meta["scope"]
        scope = [kind, None if kind == "global" else ref if kind == "context" else names[ref]]
        current = as_known(db, entity_id, "value", cut)
        for fact_id, obj in db.execute(
                "SELECT DISTINCT f.id, f.object FROM fact f JOIN link l ON l.fact_id = f.id JOIN event e "
                "ON e.id = l.event_id WHERE f.subject_id = ? AND f.predicate = 'value' AND l.role = 'assert' "
                "AND e.t_sim <= ? ORDER BY f.id", (entity_id, cut)).fetchall():
            key, value = env_key(seed, "option", fact_id), json.loads(obj)
            state["inventory"][key] = {"domain": meta["domain"], "scope": scope, "value": value}
            labels[key] = value == current
    return state, labels


def _seed(db, session, cut) -> EnvSeed:
    state, labels = state_at(db, cut)
    seed = {"canary": _canary(), "env_id": ENV_ID, "session": session, "state": state,
            "tools": [dict(t) for t in TOOLS], "heartbeat_interval_s": HEARTBEAT_S}
    validate("env_seed", seed)
    return EnvSeed(seed, labels, sha256_canon(seed["state"]))


def _bounds(db, k):
    return db.execute("SELECT t_start, t_end FROM session WHERE idx = ?", (k,)).fetchone() if type(k) is int else None


def envseed(db, session) -> EnvSeed:
    """Session k's seed shows the world strictly before the session starts."""
    if (bounds := _bounds(db, session)) is None:
        raise ValueError("unknown session")
    return _seed(db, session, bounds[0] - 1)


def probe_envseed(db, session, checkpoint) -> EnvSeed:
    """A probe session after checkpoint c sees the world up to the end of c."""
    if (bounds := _bounds(db, checkpoint)) is None:
        raise ValueError("unknown checkpoint")
    if type(session) is not int or session < 1 or _bounds(db, session) is not None:
        raise ValueError("a probe index is a positive int that is not a life session")
    return _seed(db, session, bounds[1] - 1)


def env_state_hashes(db) -> dict[int, str]:
    return {k: envseed(db, k).env_state_hash
            for (k,) in db.execute("SELECT idx FROM session ORDER BY idx").fetchall()}
