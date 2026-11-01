"""T2-lite report diagnostics; these functions never score an item."""

from bicentennial.score.answer_types import matches, normalize


def value_match(gold_envelope, answer_envelope, *, tolerance_s=0):
    """Match type and value only, regardless of confidence or citation."""
    if answer_envelope is None or answer_envelope["type"] == "unknown":
        return None
    return matches(gold_envelope, answer_envelope, tolerance_s=tolerance_s)


def value_match_normalised(gold_envelope, answer_envelope):
    """Report relaxed entity agreement separately from strict entity scoring."""
    if (answer_envelope is None or gold_envelope["type"] != "entity"
            or answer_envelope["type"] != "entity"):
        return None
    return normalize(gold_envelope["value"]) == normalize(answer_envelope["value"])


def citation_match(citation, evidence_texts):
    """Report the QA quote-containment rule; an absent citation has no diagnostic."""
    if citation is None:
        return None
    quote = normalize(citation["quote"])
    return bool(quote) and any(quote in normalize(text) for text in evidence_texts)
