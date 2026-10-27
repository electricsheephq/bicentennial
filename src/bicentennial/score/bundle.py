"""Matched twins retain their items; only their projection takes the minimum (E11)."""

from bicentennial.contracts.bundle import NONRESULTS, bundle_outcome
from bicentennial.contracts.run import validate


def make_bundle(identity, a, b) -> dict:
    if not isinstance(identity, dict) or identity.keys() != {"bundle_id", "cell_id",
                                                            "twin_type", "life"}:
        raise ValueError("make_bundle: exact identity keys required")
    if (a["stage"], a["track"]) != (b["stage"], b["track"]) or any(
            item["cell_id"] != identity["cell_id"] for item in (a, b)):
        raise ValueError("make_bundle: twins must share stage, track and identity cell")
    value = dict(identity, items=sorted([a["item_id"], b["item_id"]]), **bundle_outcome(a, b))
    validate("bundle_outcome", value)
    return value


def twin_min(a, b, *, minus_one=None, worst=False) -> int | None:
    if any(item["failure_class"] in NONRESULTS for item in (a, b)):
        return None
    values = [item["worst_case_milli" if worst else "score_milli"] for item in (a, b)]
    return min(minus_one if minus_one is not None and value == -1000 else value
               for value in values)
