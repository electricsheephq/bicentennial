"""Build verdict-free T2-lite cards independently of the Ring 0 card path."""

import json

import bicentennial.contracts.run as run
from bicentennial.canon import canon


def _schema():
    return json.loads((run.SCHEMAS / "card_t2lite.schema.json").read_bytes())


# A Ring 0 row comes from one reader, which selects an option and answers with it. At T2-lite the
# answer is the live model's, while selected_option and competing_present are the shadow reader's
# reading of the same context (#338), so item_outcome checks the answer row without that tie.
_LIVE_ANSWER = "live-answer"


def _check_item(item, *, not_scored_live=False):
    envelope = item["envelope"]
    asserted = envelope is not None and envelope["type"] != "unknown"
    if not_scored_live:
        if (item["stage"] != "act" or any(item[key] is not None for key in (
                "base_verdict", "score_milli", "worst_case_milli", "accuracy_correct", "tuesday_class",
                "envelope", "failure_class", "stage_attribution"))
                or item["benign_extra"] is not False or item["carry_over"] is not False
                or item["infra_reruns"] > 2):
            raise ValueError("t2lite_card:not_scored_live")
    else:
        run.validate("item_outcome", dict(item, competing_present=[],
                                          selected_option=_LIVE_ANSWER if asserted else None))
    # The shadow's own invariants (RING0 §1, §4): one byte order, never selecting a competitor,
    # and a competitor present means the reader selected another token option.
    selected, competing = item["selected_option"], item["competing_present"]
    if (any(a >= b for a, b in zip(competing, competing[1:], strict=False)) or selected in competing
            or (competing and selected is None)):
        raise ValueError("t2lite_card:shadow")


def validate_t2lite_card(card) -> None:
    """Apply the project's structural validator, then local T2-lite semantics."""
    run.validate("card_t2lite", card)
    if card["tier"] != "T2-lite":
        raise ValueError("t2lite_card:tier")
    if "gate_verdict" in card:
        raise ValueError("t2lite_card:gate_verdict")
    digest = card["answer_contract_sha256"]
    if (type(digest) is not str or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)):
        raise ValueError("t2lite_card:answer_contract_sha256")
    if card["profile"] == "probe-live" and card["live_roles"] != ["probe_main"]:
        raise ValueError("t2lite_card:live_roles")
    if not set(_schema()["properties"]["labels"]["required"]) <= card["labels"].keys():
        raise ValueError("t2lite_card:labels")
    # As on the Ring 0 card: one byte order (strictly increasing ids), and each item's own semantics.
    ids = [item["item_id"] for item in card["items"]]
    if any(a >= b for a, b in zip(ids, ids[1:], strict=False)):
        raise ValueError("t2lite_card:items")
    unscored = card["not_scored_live"]
    if unscored != sorted(set(unscored)) or not set(unscored) <= set(ids):
        raise ValueError("t2lite_card:not_scored_live")
    for item in card["items"]:
        _check_item(item, not_scored_live=item["item_id"] in unscored)


def build_t2lite_card(*, system, pack_hash, seed_hash, pins, model, effort, served_identity,
                      aa_prime, items, counts, answer_contract_sha256, not_scored_live) -> dict:
    """Return a fresh validated card; serialize it with canon(card) for stable bytes.

    Only probe_main is live under probe-live; every other role stays scripted.
    Counts are caller-supplied named non-negative integer counters, never scores.
    """
    labels = {name: prop["enum"][0]
              for name, prop in _schema()["properties"]["labels"]["properties"].items()}
    card = dict(tier="T2-lite", system=system, pack_hash=pack_hash, seed_hash=seed_hash,
                pins=pins, model=model, effort=effort, served_identity=served_identity,
                profile="probe-live", live_roles=["probe_main"],
                answer_contract_sha256=answer_contract_sha256, aa_prime=aa_prime,
                labels=labels, items=sorted(items, key=lambda row: row["item_id"]), counts=counts,
                not_scored_live=not_scored_live)
    validate_t2lite_card(card)
    return json.loads(canon(card))
