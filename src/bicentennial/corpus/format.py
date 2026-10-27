"""Strict, text-free regression recipes with canonical JSONL framing."""

import json
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.items.protocol import CANARY

CORPUS_VERSION = "v0.1"
CONTROLS = ("no_memory", "oracle_evidence")
MUTANTS = ("forget_cached_output", "forget_ignored", "orphan_tool_result",
           "reset_cached_output", "stale_wins", "truncate_after_compaction", "wipe_on_restart")
REFERENCE_STUBS = tuple(sorted(("bm25", "reference_store", *MUTANTS)))
ADAPTER_NAMES = tuple(sorted(CONTROLS + REFERENCE_STUBS))
PASS_ORACLE = "reference_store"
OUTCOME_KEYS = tuple(sorted(("item_id", "selected_option", "competing_present", "in_context",
                             "missing_required", "competing", "forbidden_in_context", "recall")))
REPO = Path(__file__).resolve().parents[3]
CORPUS_PATH = REPO / "corpus/public/v0.1.jsonl"
_LEVER_KEYS = {"genre", "seed", "sessions", "distance", "wake", "recipe", "template"}
_HASH_FIELDS = ("c7_entry_sha256", "world_hash_b0", "world_hash_b1", "history_set_hash")


def _require(condition, field):
    if not condition:
        raise ValueError(field)


def _object(value, keys, field):
    _require(type(value) is dict and value.keys() == set(keys), field)


def _integer(value, field, minimum=0):
    _require(type(value) is int and value >= minimum, field)


def _id(value, field):
    _require(type(value) is str and re.fullmatch(r"bcw-[0-9a-f]{16}", value), field)


def _ids(value, field, *, nonempty=False):
    _require(type(value) is list and (not nonempty or value), field)
    for ident in value:
        _id(ident, field)
    _require(value == sorted(set(value)), field)


def _leaves(value, field):
    """Refuse arbitrary strings and non-JSON scalar types at every depth."""
    kind = type(value)
    if kind is dict:
        _require(all(type(k) is str for k in value), field)
        for key in sorted(value):
            _leaves(key, field)
            _leaves(value[key], key)
    elif kind is list:
        for child in value:
            _leaves(child, field)
    elif kind is str:
        _require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:@/+-]*", value), field)
    else:
        _require(kind in (int, bool, type(None)), field)


def check_source(source):
    if type(source) is str and source.startswith("equal_run:"):
        raise ValueError("equal_run needs a board roster (v0.2)")
    admitted = tuple(f"control:{n}" for n in CONTROLS) + tuple(
        f"reference_stub:{n}" for n in REFERENCE_STUBS if n != PASS_ORACLE)
    if type(source) is not str or source not in admitted:
        raise ValueError("corpus source must be a control or a reference stub")
    return source.split(":", 1)[1]


@dataclass(frozen=True, kw_only=True)
class Case:
    case_id: str
    source: str
    catalogue_row: str
    generator_version: str
    genre: str
    seed: int
    recipe: str
    template: str
    c7_entry_sha256: str
    levers: dict
    fault_points: list
    world_hash_b0: str
    world_hash_b1: str
    history_set_hash: str
    items: list
    expected: dict

    def to_obj(self):
        return asdict(self)


def _check_levers(obj):
    levers = obj["levers"]
    _require(type(levers) is dict and set(levers) in
             (_LEVER_KEYS, _LEVER_KEYS | {"schedule_seed"}), "levers")
    for field in ("genre", "seed", "recipe", "template"):
        _require(levers[field] == obj[field] and type(levers[field]) is type(obj[field]), field)
    for field in ("seed", "sessions", "distance", "schedule_seed"):
        if field in levers:
            _integer(levers[field], field)
    _require(1 <= levers["sessions"] <= 3, "sessions")
    _require(levers["distance"] < levers["sessions"], "distance")
    _require(levers["wake"] in ("none", "kill", "swap", "restart", "compaction", "gap"), "wake")
    _require(levers["wake"] == "none" or
             (levers["sessions"] >= 2 and levers["distance"] >= 1), "wake")


def _check_faults(rows, sessions):
    _require(type(rows) is list, "fault_points")
    order = []
    for row in rows:
        _object(row, ("kind", "session", "turn"), "fault_points")
        _require(row["kind"] in ("restart", "compaction", "kill", "swap"), "kind")
        _integer(row["session"], "session", 1)
        _require(row["session"] <= sessions, "session")
        if row["turn"] is not None:
            _integer(row["turn"], "turn", 1)
        _require((row["kind"] == "kill") == (row["turn"] is not None), "turn")
        order.append((row["session"], row["turn"] is not None, row["turn"], row["kind"]))
    _require(order == sorted(set(order)), "fault_points")


def _check_outcome(obj):
    _object(obj, OUTCOME_KEYS, "expected")
    _id(obj["item_id"], "item_id")
    if obj["selected_option"] is not None:
        _id(obj["selected_option"], "selected_option")
    _ids(obj["competing_present"], "competing_present")
    for field in ("in_context", "forbidden_in_context"):
        _require(obj[field] is None or type(obj[field]) is bool, field)
    _integer(obj["missing_required"], "missing_required")
    _object(obj["competing"], ("planted", "stale", "twin"), "competing")
    for field in sorted(obj["competing"]):
        _integer(obj["competing"][field], field)
    recall = obj["recall"]
    if recall is not None:
        _object(recall, ("k", "hits", "of", "milli"), "recall")
        for field in sorted(recall):
            _integer(recall[field], field)
        _require(recall["k"] == 5 and recall["of"] > 0, "recall")
        _require(recall["hits"] <= min(recall["k"], recall["of"]) and
                 recall["milli"] <= 1000, "recall")


def check_case(obj) -> Case:
    _object(obj, (f.name for f in fields(Case)), "case")
    source = check_source(obj["source"])
    _leaves(obj, "case")
    _require(obj["case_id"] == f"{obj['catalogue_row']}.{source}", "case_id")
    _require(obj["genre"] in ("G1", "G2"), "genre")
    _integer(obj["seed"], "seed")
    _require(type(obj["generator_version"]) is str, "generator_version")
    _require(type(obj["template"]) is str and
             re.fullmatch(r"[a-z0-9][a-z0-9-]*-v[1-9][0-9]*", obj["template"]), "template")
    template_id = obj["template"].rsplit("-v", 1)[0]
    _require(type(obj["catalogue_row"]) is str and re.fullmatch(
        re.escape(f"{obj['genre'].lower()}-{template_id}-") + r"(?:mft|inv|dir)-[1-9][0-9]*",
        obj["catalogue_row"]), "catalogue_row")
    _require(obj["recipe"] == f"catalogue-v0:{obj['template']}", "recipe")
    for field in _HASH_FIELDS:
        _require(type(obj[field]) is str and re.fullmatch(r"[0-9a-f]{64}", obj[field]), field)
    _check_levers(obj)
    _check_faults(obj["fault_points"], obj["levers"]["sessions"])
    _ids(obj["items"], "items", nonempty=True)
    _object(obj["expected"], ADAPTER_NAMES, "expected")
    for name in ADAPTER_NAMES:
        expected = obj["expected"][name]
        if type(expected) is str and expected == "system_failure":
            _require(name not in (*CONTROLS, PASS_ORACLE), "expected")
            continue
        _require(type(expected) is list, "expected")
        for result in expected:
            _check_outcome(result)
        _require([r["item_id"] for r in expected] == obj["items"], "item_id")
    source_result = obj["expected"][source]
    _require(source_result == "system_failure" or any(
        a["selected_option"] != b["selected_option"] for a, b in
        zip(source_result, obj["expected"][PASS_ORACLE], strict=True)), "source")
    return Case(**json.loads(canon(obj)))


def dump_corpus(cases) -> bytes:
    checked = sorted((check_case(c.to_obj()) for c in cases), key=lambda c: c.case_id)
    ids = [c.case_id for c in checked]
    _require(len(ids) == len(set(ids)), "case_id")
    header = dict(canary=CANARY, corpus=CORPUS_VERSION, cases=len(checked))
    return b"\n".join([canon(header), *(canon(c.to_obj()) for c in checked)]) + b"\n"


def _canonical_line(line):
    try:
        obj = json.loads(line)
        canonical = canon(obj)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ValueError("line") from None
    _require(line == canonical + b"\n", "line")
    return obj


def load_corpus(path) -> tuple[Case, ...]:
    lines = Path(path).read_bytes().splitlines(keepends=True)
    _require(bool(lines), "header")
    header = _canonical_line(lines[0])
    _object(header, ("canary", "corpus", "cases"), "header")
    _require(header["canary"] == CANARY, "canary")
    _require(header["corpus"] == CORPUS_VERSION, "corpus")
    _integer(header["cases"], "cases")
    _require(header["cases"] == len(lines) - 1, "cases")
    cases = tuple(check_case(_canonical_line(line)) for line in lines[1:])
    ids = [c.case_id for c in cases]
    _require(ids == sorted(set(ids)), "case_id")
    return cases
