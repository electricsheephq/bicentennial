"""Pack manifest; importing this module installs all generator semantic checks."""

import re
import unicodedata
from dataclasses import dataclass

from . import stream as _stream  # noqa: F401 -- install session/event checks
from .items import Bundle, Item
from .run import register_check, validate
from .world import Contract, unique


def check_pack(value):
    unique(value["lives"], "lives")
    ids = [item["item_id"] for item in value["items"]]
    unique(ids, "items")
    unique([bundle["bundle_id"] for bundle in value["bundles"]], "bundles")
    unique(value["qa_order"], "qa_order")
    qa_ids = {item["item_id"] for item in value["items"] if item["stage"] != "act"}
    if set(value["qa_order"]) != qa_ids:
        raise ValueError("pack: qa_order must contain exactly the QA item ids")
    by_id = {item["item_id"]: item for item in value["items"]}
    for item in value["items"]:
        validate(Item._name, item)
    for bundle in value["bundles"]:
        validate(Bundle._name, bundle)
        if any(i not in by_id or by_id[i]["cell_id"] != bundle["cell_id"]
               for i in bundle["items"]):
            raise ValueError("pack: bundle item missing or from a different cell")
    # RING0 §1: no locked token may occur in any probe prompt, another item's included.
    prompts = [unicodedata.normalize("NFC", item["prompt"]) for item in value["items"]]
    for item in value["items"]:
        for option in item["options"]:
            for token in option["tokens"]:
                if any(unicodedata.normalize("NFC", token) in p for p in prompts):
                    raise ValueError("pack: a locked token occurs in a probe prompt")
    # DESIGN §5.1a: each action item is in exactly one twin bundle. Survive bundles may hold QA items.
    members = [i for bundle in value["bundles"] for i in bundle["items"]]
    unique(members, "bundle items")
    if {item["item_id"] for item in value["items"] if item["stage"] == "act"} - set(members):
        raise ValueError("pack: every action item belongs to a bundle")
    for control in value["controls"].values():
        if isinstance(control, str) and control != "not run in v0.1":
            raise ValueError("pack: invalid control placeholder")
    for key, digest in value["hashes"].items():
        if not key or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("pack: hashes must map artifact names to SHA-256 digests")


@dataclass(frozen=True)
class Pack(Contract):
    _name = "pack"
    canary: str
    pack_id: str
    tier: str
    genre: str
    seeds: list[int]
    lives: list[str]
    items: list[dict]
    bundles: list[dict]
    qa_order: list[str]
    controls: dict
    hashes: dict


register_check("pack", check_pack)
