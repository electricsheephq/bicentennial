"""QA envelope parsing and the PREREG §3 QA table, in milli (DESIGN §7.2 and §7.5)."""

import json
import re
from dataclasses import asdict, dataclass

from bicentennial.score.answer_types import matches, normalize

# K14's item_outcome envelope (schemas/item_outcome.schema.json and contracts/bundle.py _item).
TYPES = ("entity", "datetime", "number", "set", "ordered_list", "span", "citation",
         "boolean", "unknown", "premise_correction", "env_state")
REQUIRED = {"type", "value", "confidence_milli"}
NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?")
FENCE = re.compile(r"```(?:json)?\r?\n(.*)\n```", re.DOTALL)
ASSERTED = 500  # PREREG §3: a stated confidence >= 0.5 asserts; below it hedges


@dataclass(frozen=True)
class QAResult:
    envelope: dict | None
    score_milli: int
    failure_class: str | None
    correct: bool | None  # null for unknown, missing and system failure


def _refuse(constant):
    raise ValueError(f"non-finite number: {constant}")


def _unique_keys(pairs):
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _value_ok(kind, value) -> bool:
    if kind == "unknown":
        return value is None
    if kind == "boolean":
        return type(value) is bool
    if kind == "datetime":
        return type(value) is int
    if kind == "number":
        return type(value) is int or type(value) is str and NUMBER.fullmatch(value) is not None
    if kind in ("set", "ordered_list"):
        return type(value) is list
    if kind == "env_state":
        return type(value) is dict
    return type(value) is str and bool(value)


def _citation_ok(citation) -> bool:
    if citation is None:
        return True
    return (type(citation) is dict and citation.keys() == {"quote", "context_offset"}
            and type(citation["quote"]) is str
            and re.fullmatch(r"^.+$", citation["quote"]) is not None
            and type(citation["context_offset"]) is int and citation["context_offset"] >= 0)


def valid_envelope(envelope) -> bool:
    """True when envelope is a complete K14 envelope, citation included."""
    if type(envelope) is not dict or envelope.keys() != REQUIRED | {"citation"}:
        return False
    kind, confidence = envelope["type"], envelope["confidence_milli"]
    if kind not in TYPES or type(confidence) is not int or not 0 <= confidence <= 1000:
        return False
    if kind == "unknown" and (confidence != 0 or envelope["citation"] is not None):
        return False
    return _value_ok(kind, envelope["value"]) and _citation_ok(envelope["citation"])


def parse_envelope(text: str) -> dict | None:
    """Return the K14 envelope in agent text, or None when it is missing or malformed."""
    try:
        body = text.strip()
        fenced = FENCE.fullmatch(body)
        if fenced is not None:  # at most one surrounding fence is unwrapped
            body = fenced.group(1)
        envelope = json.loads(body, parse_float=str, parse_constant=_refuse,
                              object_pairs_hook=_unique_keys)
        if type(envelope) is not dict or not REQUIRED <= envelope.keys() <= REQUIRED | {"citation"}:
            return None
        envelope = {"citation": None, **envelope}
        return envelope if valid_envelope(envelope) else None
    except Exception:  # never raise on agent text
        return None


def _cited(citation, evidence_texts) -> bool:
    # DESIGN §7.5: a right value with the wrong event is wrong.
    if citation is None:
        return True
    quote = normalize(citation["quote"])
    return bool(quote) and any(quote in normalize(text) for text in evidence_texts)


def score_qa(item, envelope, *, evidence_texts, tolerance_s=0, system_failure=False) -> QAResult:
    """Score one QA item's envelope (from parse_envelope) under the PREREG §3 QA table."""
    item = item if isinstance(item, dict) else asdict(item)
    if item["stage"] == "act":
        raise ValueError("action items are scored by the action scorer")
    if isinstance(evidence_texts, str):  # a bare string would be read as its characters
        raise ValueError("evidence_texts: a collection of event texts required")
    evidence_texts = tuple(evidence_texts)
    if not all(type(text) is str for text in evidence_texts):
        raise ValueError("evidence_texts: a collection of event texts required")
    if system_failure:  # a director-recorded crash or timeout comes first (K01)
        return QAResult(None, 0, "SYSTEM_FAILURE", None)
    if envelope is None:  # missing or unparseable
        return QAResult(None, -1000, None, None)
    if not valid_envelope(envelope):
        raise ValueError("envelope: pass parse_envelope's result")
    if envelope["type"] == "unknown":
        return QAResult(envelope, 1000 if item["gold"]["never_observed"] else 0, None, None)
    gold_id = item["gold"]["option_id"]
    gold = next(o["envelope"] for o in item["options"] if o["option_id"] == gold_id)
    # A never-observed gold is an UNKNOWN envelope, so any asserted value mismatches its type.
    correct = (gold["type"] != "unknown" and matches(gold, envelope, tolerance_s=tolerance_s)
               and _cited(envelope["citation"], evidence_texts))
    weight = 1000 if envelope["confidence_milli"] >= ASSERTED else 500
    return QAResult(envelope, weight if correct else -weight, None, correct)
