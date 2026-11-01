"""Build verdict-free T2-lite cards independently of the Ring 0 card path."""

import json

import bicentennial.contracts.run as run
from bicentennial.canon import canon


def _schema():
    return json.loads((run.SCHEMAS / "card_t2lite.schema.json").read_bytes())


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


def build_t2lite_card(*, system, pack_hash, seed_hash, pins, model, effort, served_identity,
                      aa_prime, items, counts, answer_contract_sha256) -> dict:
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
                labels=labels, items=sorted(items, key=lambda row: row["item_id"]), counts=counts)
    validate_t2lite_card(card)
    return json.loads(canon(card))
