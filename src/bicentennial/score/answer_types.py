"""Deterministic answer-type matchers (DESIGN §7.5). The LLM judge is out of scope."""

import unicodedata
from decimal import Decimal
from fractions import Fraction
from itertools import combinations

from bicentennial.canon import canon

TEXT_TYPES = ("span", "premise_correction", "citation")


def normalize(text: str) -> str:
    """NFC, then casefold, then each whitespace run collapsed to one space, then stripped."""
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _keys(values) -> list[bytes]:
    return [canon(value) for value in values]


def _tolerance(tolerance_s):
    if type(tolerance_s) is not int or tolerance_s < 0:
        raise ValueError("tolerance_s: non-negative integer seconds required")


def matches(gold: dict, answer: dict, *, tolerance_s: int = 0) -> bool:
    """Compare two envelopes of the same type; UNKNOWN belongs to the rubric (score_qa)."""
    _tolerance(tolerance_s)
    kind = gold["type"]
    if kind == "unknown":
        raise ValueError("unknown is scored by the rubric, not matched")
    if answer["type"] != kind:
        return False
    g, a = gold["value"], answer["value"]
    if kind in ("entity", "boolean"):
        return type(g) is type(a) and g == a
    if kind == "datetime":
        return abs(a - g) <= tolerance_s
    if kind == "number":
        return Decimal(str(g)) == Decimal(str(a))
    if kind == "set":
        answered = _keys(a)
        # A duplicate element in the answer is malformed and scores false.
        return len(answered) == len(set(answered)) and set(answered) == set(_keys(g))
    if kind == "ordered_list":
        return _keys(g) == _keys(a)
    if kind in TEXT_TYPES:
        return normalize(g) == normalize(a)
    if kind == "env_state":
        return canon(g) == canon(a)
    raise ValueError(f"unsupported answer type: {kind}")


def _typed(gold, answer, kind):
    if gold["type"] != kind or answer["type"] != kind:
        raise ValueError(f"{kind} envelopes required")
    return gold["value"], answer["value"]


def set_f1(gold: dict, answer: dict) -> Fraction:
    """Diagnostic F1 over distinct canonical elements; two empty sets agree exactly (1)."""
    g, a = (set(_keys(values)) for values in _typed(gold, answer, "set"))
    if not g and not a:
        return Fraction(1)
    return Fraction(2 * len(g & a), len(g) + len(a))


def kendall_tau(gold: dict, answer: dict) -> Fraction | None:
    """Diagnostic tau-a over the shared elements; None below 2 shared or on a repeated element."""
    g, a = (_keys(values) for values in _typed(gold, answer, "ordered_list"))
    if len(g) != len(set(g)) or len(a) != len(set(a)):
        return None  # a repeated element has no single rank
    rank = {key: index for index, key in enumerate(a)}
    shared = [key for key in g if key in rank]
    if len(shared) < 2:
        return None
    # shared is in gold order, so a pair is concordant when the answer keeps that order.
    signs = [1 if rank[x] < rank[y] else -1 for x, y in combinations(shared, 2)]
    return Fraction(sum(signs), len(signs))
