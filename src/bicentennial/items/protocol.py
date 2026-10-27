"""Data-only template protocol; fork/value, genuine/source, lure and trigger/trigger."""

import json
import re
from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.world import as_known, as_valid

_ITEM = json.loads((SCHEMAS / "item.schema.json").read_bytes())["properties"]
CELL_IDS = tuple(_ITEM["cell_id"]["enum"])
CANARY = _ITEM["canary"]["enum"][0]
TWIN_TYPES = tuple(json.loads((SCHEMAS / "bundle.schema.json").read_bytes())
                   ["properties"]["twin_type"]["enum"])
TRACK_BY_PREFIX = {"WAKE": "Wake", "DRIFT": "Drift", "TUE": "Tuesday", "RACH": "Rachael",
                   "KEEP": "Keep", "RECALL": "Recall", "FAULT": "Faults"}
ACT_CELLS = frozenset(("WAKE-LOOP", "WAKE-PREF", "WAKE-SWAP", "DRIFT-CUR", "DRIFT-PART",
                       "DRIFT-PROC", "TUE-TIME", "TUE-EVENT", "TUE-CUE", "TUE-RULE",
                       "RACH-PLANT", "RACH-PREM", "KEEP-INC", "KEEP-FORGET", "KEEP-NEIGH"))
DEFERRED_CELLS = frozenset(("RACH-PLANT", "RACH-PREM", "FAULT-DUP"))
DIRECTIONS = ("verbatim retention", "extraction and consolidation", "recency", "retrieval breadth", "none")
SEMANTICS = ("as_valid", "as_known")


def cell_track(cell_id):
    return TRACK_BY_PREFIX[cell_id.split("-", 1)[0]]


def cell_stage(cell_id):
    return "A" if cell_id in ACT_CELLS else "S" if cell_id.startswith("FAULT-") else "R"


@dataclass(frozen=True, kw_only=True)
class Option:
    key: str
    token_fact_ids: tuple[str, ...]
    envelope: dict | None = None
    plan: dict | None = None


@dataclass(frozen=True, kw_only=True)
class Instance:
    key: str
    probe_point: int
    prompt: str
    options: tuple[Option, ...]
    gold_spans: tuple[str, ...]
    decisive_fact_id: str | None
    never_observed: bool = False
    decision_table_ref: str | None = None
    duty: bool = False


@dataclass(frozen=True, kw_only=True, eq=False)
class Template:
    template_id: str
    version: int
    cell_id: str
    kind: str
    twin_type: str | None
    direction: str
    semantics: str
    decision_tables: tuple[dict, ...] = ()

    def __post_init__(self):
        if (type(self.template_id) is not str or not re.fullmatch(r"[a-z][a-z0-9-]*", self.template_id)
                or type(self.version) is not int or self.version < 1):
            raise ValueError("invalid template identity")
        if self.cell_id not in CELL_IDS or self.cell_id in DEFERRED_CELLS:
            raise ValueError("unknown or deferred cell")
        if self.kind not in ("qa", "act") or (self.kind == "act") != (cell_stage(self.cell_id) == "A"):
            raise ValueError("template kind and cell disagree")
        if self.twin_type not in (*TWIN_TYPES, None) or self.kind == "act" and self.twin_type is None:
            raise ValueError("invalid twin type")
        if self.direction not in DIRECTIONS or self.semantics not in SEMANTICS:
            raise ValueError("invalid direction or semantics")
        if bool(self.decision_tables) != (self.kind == "act"):
            raise ValueError("decision tables required exactly for act")
        for table in self.decision_tables:
            validate("decision_table", table)
        ids = [t["table_id"] for t in self.decision_tables]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate table ids")

    @property
    def ref(self):
        return f"{self.template_id}-v{self.version}"

    @property
    def track(self):
        return cell_track(self.cell_id)

    def instances(self, db, schedule) -> tuple[Instance, ...]:
        raise NotImplementedError


def decisive_fact(db, subject_id, predicate, t, semantics):
    if semantics not in SEMANTICS:
        raise ValueError("invalid semantics")
    value = (as_valid if semantics == "as_valid" else as_known)(db, subject_id, predicate, t)
    if value is None:
        return None
    condition = ("valid_from_t <= ? AND (valid_to_t IS NULL OR ? < valid_to_t)"
                 if semantics == "as_valid" else "recorded_t <= ? AND valid_from_t <= ?")
    row = db.execute(f"SELECT source_event_id FROM attr WHERE entity_id=? AND key=? AND {condition} "
                     "AND value=? ORDER BY valid_from_t DESC LIMIT 1",
                     (subject_id, predicate, t, t, canon(value).decode())).fetchone()
    facts = db.execute("SELECT f.id FROM fact f JOIN link l ON l.fact_id=f.id "
                       "WHERE f.subject_id=? AND f.predicate=? AND f.object=? "
                       "AND l.event_id=? AND l.role='assert' ORDER BY f.id",
                       (subject_id, predicate, canon(value).decode(), row[0])).fetchall()
    if len(facts) != 1:
        raise ValueError("decisive assertion must identify one fact")
    return facts[0][0]
