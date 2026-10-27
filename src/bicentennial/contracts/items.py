"""Scorer-sealed items and bundles; reader projection exposes only options."""

import re
import unicodedata
from dataclasses import asdict, dataclass

from .run import register_check, validate
from .world import Contract, bounded, unique


def check_item(value):
    options = value["options"]
    if not options or options[0]["option_id"] != value["gold"]["option_id"]:
        raise ValueError("item: gold must be the first option")
    unique([option["option_id"] for option in options], "options")
    if sum(not option["tokens"] for option in options) > 1:
        raise ValueError("item: at most one empty-token option")
    prompt = unicodedata.normalize("NFC", value["prompt"])
    for option in options:
        for token in option["tokens"]:
            token = unicodedata.normalize("NFC", token)
            if len(token) < 4 or token in prompt:
                raise ValueError("item: short token or token present in prompt")
        expected = "plan" if value["stage"] == "act" else "envelope"
        if expected not in option or ({"plan", "envelope"} - {expected}) & option.keys():
            raise ValueError("item: stage and option payload disagree")
        if expected == "plan":
            if not option["tokens"] and option["plan"]["steps"]:
                raise ValueError("item: empty-token plan must refrain")
        else:
            envelope = option["envelope"]
            bounded(envelope["confidence_milli"], "confidence_milli")
            if envelope["confidence_milli"] != (1000 if option["tokens"] else 0):
                raise ValueError("item: Ring 0 confidence disagrees with tokens")
            if not option["tokens"] and envelope["type"] != "unknown":
                raise ValueError("item: empty-token envelope must be UNKNOWN")
            if envelope["type"] == "number" and not (
                type(envelope["value"]) is int or isinstance(envelope["value"], str)
                and re.fullmatch(r"-?[0-9]+(?:\.[0-9]+)?", envelope["value"])
            ):
                raise ValueError("item: number must be an integer or decimal string")
    if value["gold"]["never_observed"] and (
        value["stage"] == "act" or options[0]["tokens"]
        or options[0]["envelope"]["type"] != "unknown"
    ):
        raise ValueError("item: never_observed gold must be empty-token UNKNOWN")


def check_bundle(value):
    if len(value["items"]) != 2 or len(set(value["items"])) != 2:
        raise ValueError("bundle: exactly two distinct B0/B1 item ids required")


@dataclass(frozen=True)
class Item(Contract):
    _name = "item"
    canary: str
    item_id: str
    stage: str
    track: str
    cell_id: str
    probe_point: int
    prompt: str
    options: list[dict]
    gold: dict
    gold_spans: list[str]
    decision_table_ref: str
    precondition: str | None
    memory_tag: str
    labels: list[str]


@dataclass(frozen=True)
class Bundle(Contract):
    _name = "bundle"
    canary: str
    bundle_id: str
    cell_id: str
    twin_type: str
    items: list[str]
    decisive_fact_id: str


def reader_view(item: Item | dict) -> dict:
    value = asdict(item) if isinstance(item, Item) else item
    validate("item", value)
    # Canonical round trip also detaches the reader's options from scorer data.
    import json

    from bicentennial.canon import canon

    return json.loads(canon({key: value[key] for key in ("item_id", "prompt", "options")}))


register_check("item", check_item)
register_check("bundle", check_bundle)
