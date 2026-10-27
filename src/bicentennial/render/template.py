"""Template-lane renderer: phrase-bank clauses filled only from locked tokens and fact rows."""

import json
import sqlite3
import unicodedata
from dataclasses import dataclass
from functools import cache
from typing import NamedTuple

from bicentennial.contracts.run import SCHEMAS
from bicentennial.keyed import choice
from bicentennial.world import unit

from .dates import channel_stamp, relative_date, zone
from .phrasebank import SLOT, Phrase, PhraseBank, default_bank

ROLES = ("retract", "assert", "mention")


class Slot(NamedTuple):
    name: str
    start: int
    end: int
    fact_id: str
    token_id: str | None


@dataclass(frozen=True)
class Render:
    event_id: str
    text: str
    lane: str
    template_id: str
    voice: str
    fact_ids: tuple[str, ...]
    gold_critical: bool
    slots: tuple[Slot, ...]

    def stream_render(self) -> dict:
        return {"lane": self.lane, "template_id": self.template_id, "voice": self.voice}


@cache
def _canary() -> str:
    return json.loads((SCHEMAS / "world.schema.json").read_bytes())["properties"]["canary"]["enum"][0]


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _one(db: sqlite3.Connection, sql: str, *args) -> sqlite3.Row:
    row = db.execute(sql, args).fetchone()
    if row is None:
        raise ValueError(f"missing row for {args!r}")
    return row


def _fill(phrase: Phrase, values: dict[str, tuple[str, str | None]], fact_id: str,
          offset: int, slots: list[Slot]) -> str:
    # Split and concatenate, never str.format, so a token holding "{object}" stays literal.
    parts = SLOT.split(phrase.text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            out.append(part)
            continue
        value, token_id = values[part]
        start = offset + sum(map(len, out))
        slots.append(Slot(part, start, start + len(value), fact_id, token_id))
        out.append(value)
    return "".join(out)


def render_event(db: sqlite3.Connection, event_id: str, *, life: str, tz: str,
                 bank: PhraseBank | None = None) -> Render:
    """Read-only: the text depends only on the event, its linked facts' rows, meta.seed, life, tz and bank."""
    bank = bank or default_bank()
    zone(tz)
    event = _one(db, "SELECT t_sim, channel FROM event WHERE id = ?", event_id)
    if event["channel"] not in bank.channels:
        raise ValueError(f"unknown channel: {event['channel']!r}")
    seed = _one(db, "SELECT seed FROM meta")["seed"]
    key = unit(life, "render", event_id)
    links = sorted(db.execute("SELECT fact_id, role FROM link WHERE event_id = ?", (event_id,)),
                   key=lambda r: (ROLES.index(r["role"]), r["fact_id"].encode()))
    gold = db.execute("SELECT 1 FROM forget_request WHERE event_id = ? UNION ALL "
                      "SELECT 1 FROM plant WHERE carrier_event_id = ?", (event_id, event_id)).fetchone() is not None
    fact_ids: list[str] = []
    linked_tokens: list[str] = []
    clauses: list[tuple[Phrase, dict, str]] = []
    for i, link in enumerate(links):
        fact = _one(db, "SELECT * FROM fact WHERE id = ?", link["fact_id"])
        fid = fact["id"]
        fact_ids += [] if fid in fact_ids else [fid]
        modality = "retracted" if link["role"] == "retract" else fact["modality"]
        cell = bank.cell(fact["speech_act"], modality, fact["strength"], fact["polarity"])
        tokens = db.execute("SELECT token_id, value FROM locked_token WHERE fact_id = ?", (fid,)).fetchall()
        commitment = db.execute("SELECT trigger_kind, window_open_t FROM commitment WHERE fact_id = ?",
                                (fid,)).fetchone()
        planted = db.execute("SELECT 1 FROM plant WHERE fact_id = ?", (fid,)).fetchone()
        gold = gold or bool(tokens or commitment or planted) or link["role"] == "retract" or (
            fact["modality"] in ("retracted", "planted") or fact["speech_act"] in ("hedge", "propose", "quote"))
        if len(tokens) > 1:
            raise ValueError(f"fact {fid} has more than one locked token")
        if tokens:
            obj = (tokens[0]["value"], tokens[0]["token_id"])
            linked_tokens.append(obj[0])
        elif type(value := json.loads(fact["object"])) is str:
            obj = (value, None)
        else:
            raise ValueError(f"fact {fid}: a non-string object must be a locked token")
        subject = _one(db, "SELECT canonical_name FROM entity WHERE id = ?", fact["subject_id"])
        values = {"subject": (subject["canonical_name"], None), "object": obj,
                  "predicate": (fact["predicate"].replace("_", " "), None)}
        clauses.append((choice(seed, key, 0, f"clause#{i}", cell), values, fid))
        if commitment is not None and commitment["trigger_kind"] == "time":
            when = relative_date(event["t_sim"], commitment["window_open_t"], tz)
            clauses.append((bank.when, {"when": (when, None)}, fid))
    style = bank.channels[event["channel"]]
    stamp = channel_stamp(event["t_sim"], tz, style)
    prefix = {"chat": stamp + " ", "log": stamp + " ", "mail": stamp + "\n\n"}.get(style, "")
    slots: list[Slot] = []
    if clauses:
        body = []
        for phrase, values, fid in clauses:
            offset = len(prefix) + sum(len(b) + 1 for b in body)
            body.append(_fill(phrase, values, fid, offset, slots))
        text, ids = prefix + " ".join(body), [phrase.phrase_id for phrase, _, _ in clauses]
    else:
        phrase = choice(seed, key, 0, "factless", bank.factless)
        text, ids = prefix + phrase.text, [phrase.phrase_id]
    _postconditions(db, text, fact_ids, linked_tokens)
    return Render(event_id, text, "template", f"{bank.bank_id}:" + "+".join(ids), "template",
                  tuple(fact_ids), gold, tuple(slots))


def _postconditions(db: sqlite3.Connection, text: str, fact_ids: list[str], tokens: list[str]) -> None:
    normal = _nfc(text)
    if any(_nfc(t) != t or t not in normal for t in tokens):
        raise ValueError("a linked locked token is not NFC or not present in the render")
    # RING0 §1: a token may occur only in its own evidence events. This read can only raise.
    others = db.execute("SELECT value FROM locked_token WHERE fact_id NOT IN (SELECT value FROM json_each(?))",
                        (json.dumps(fact_ids),))
    if any(_nfc(row["value"]) in normal for row in others):
        raise ValueError("an unlinked fact's locked token occurs in the render")
    if _canary() in text:
        raise ValueError("the canary GUID occurs in the render")
