"""Read-only generator world export and shared canonical contract codec."""

import json
from dataclasses import asdict, dataclass
from typing import ClassVar

from bicentennial.canon import canon

from .run import register_check, validate


class Contract:
    """Frozen records validate on both wire boundaries; nested rows are JSON."""

    _name: ClassVar[str]

    def to_json(self) -> bytes:
        value = asdict(self)
        validate(self._name, value)
        return canon(value)

    @classmethod
    def from_json(cls, raw: str | bytes):
        value = json.loads(raw)
        validate(cls._name, value)
        return cls(**value)


def unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label}: duplicate identity")


def bounded(value, label):
    if not 0 <= value <= 1000:
        raise ValueError(f"{label}: expected 0..1000")


def check_world(value):
    for table in ("entity", "event", "fact"):
        unique([row["id"] for row in value[table]], table)
    for row in value["entity"]:
        if row["retired_t"] is not None and row["retired_t"] < row["created_t"]:
            raise ValueError("entity: retirement precedes creation")
    for row in value["attr"]:
        if row["valid_to_t"] is not None and row["valid_to_t"] < row["valid_from_t"]:
            raise ValueError("attr: inverted validity interval")
    for table, field in (("event", "salience"), ("fact", "strength")):
        for row in value[table]:
            bounded(row[field], field)
    entities = {row["id"] for row in value["entity"]}
    events = {row["id"] for row in value["event"]}
    facts = {row["id"] for row in value["fact"]}
    for row in value["attr"]:
        if row["entity_id"] not in entities or row["source_event_id"] not in events:
            raise ValueError("attr: unresolved entity or source event")
    for row in value["fact"]:
        if row["subject_id"] not in entities:
            raise ValueError("fact: unresolved subject")
    for row in value["link"]:
        if row["event_id"] not in events or row["fact_id"] not in facts:
            raise ValueError("link: unresolved event or fact")
    for row in value["lineage"]:
        if row["source_fact_id"] not in facts:
            raise ValueError("lineage: unresolved source fact")


@dataclass(frozen=True)
class World(Contract):
    _name = "world"
    canary: str
    entity: list[dict]
    attr: list[dict]
    event: list[dict]
    fact: list[dict]
    link: list[dict]
    lineage: list[dict]


register_check("world", check_world)
