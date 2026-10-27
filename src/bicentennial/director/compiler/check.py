"""Runner-side preconditions; no harness is imported by these checks."""

import json
from fractions import Fraction

from bicentennial.canon import milli, sha256_canon
from bicentennial.genres.g2_assistant.envseed import probe_envseed
from bicentennial.items.tags import check_precondition


def precondition_holds(item, *, repo_tree_hash, env_state_hash, probe_env_state_hash):
    try:
        obj = json.loads(item["precondition"])
        own_hash = obj.get("env_state_hash") if type(obj) is dict else None
        repo_ok = check_precondition(item["precondition"], repo_tree_hash=repo_tree_hash, env_state_hash=own_hash)
    except (TypeError, KeyError) as error:
        raise ValueError("invalid precondition") from error
    if obj["after_session"] != item["probe_point"]:
        raise ValueError("precondition checkpoint mismatch")
    return repo_ok and env_state_hash == probe_env_state_hash


def expected_probe_env(db, genre, p, k):
    if genre == "G1":
        return sha256_canon({})
    if genre == "G2":
        return probe_envseed(db, p, k).env_state_hash
    raise ValueError("unknown genre")


def void_outcome(item):
    """Cause packet for the runner's S06 outcome(..., cause=...) / two-rerun loop."""
    return {"item_id": item["item_id"], "cause": "INFRA_FAILURE"}


class Voids:
    def __init__(self):
        self.records = {}
        self.diagnostics = []

    def record(self, item_id, arm, holds, *, call=None, expected_sha256=None, got_sha256=None):
        if (item_id, arm) in self.records:
            raise ValueError("duplicate precondition record")
        if type(holds) is not bool:
            raise ValueError("holds must be boolean")
        self.records[item_id, arm] = holds
        self.diagnostics.append(dict(item_id=item_id, arm=arm, holds=holds, call=call,
                                     expected_sha256=expected_sha256, got_sha256=got_sha256))

    def voided(self):
        return {item for (item, _), holds in self.records.items() if not holds}

    def summary(self):
        checked, voided = len({i for i, _ in self.records}), len(self.voided())
        return dict(checked=checked, voided=voided, void_milli=milli(Fraction(voided, checked)) if checked else None)
