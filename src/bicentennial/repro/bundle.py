"""Build and rerun a text-free replay-from-schedule reproduction bundle."""

import json

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.items.protocol import CANARY

from .ddmin import Constraints, Oracle, Shrink


def build_bundle(*, system: str, life: dict, events, constraints: Constraints,
                 shrink: Shrink, oracle: str, target: str, threshold: int) -> dict:
    """Return a detached, validated replay recipe, without corpus stocking fields."""
    events = list(events)
    positions = {event: index for index, event in enumerate(events)}
    known = set(events)
    if any(not group <= known for group in constraints.groups) or any(
            d not in known or not sources <= known for d, sources in constraints.requires):
        raise ValueError("unknown constraint event id")
    groups = [sorted(group, key=positions.__getitem__) for group in constraints.groups]
    groups.sort(key=lambda group: positions[group[0]])
    requires = [[d, sorted(sources, key=positions.__getitem__)]
                for d, sources in constraints.requires]
    requires.sort(key=lambda row: (positions[row[0]], row[1]))
    bundle = {
        "canary": CANARY,
        "repro_version": "v0.1",
        "repro_class": "replay-from-schedule",
        "system": system,
        "life": life,
        "schedule": {"events": events, "kept": list(shrink.kept),
                     "groups": groups, "requires": requires},
        "failure": {"oracle": oracle, "signature": target, "threshold": threshold},
        "frequency": {"failures": shrink.failures, "runs": shrink.runs},
        "minimality": {"claim": "budget-exhausted" if shrink.exhausted
                       else "1-minimal-under-tested", "tests": shrink.tests},
    }
    validate("repro_bundle", bundle)
    return json.loads(canon(bundle))


def rerun(bundle: dict, oracle: Oracle) -> int:
    """Count the same failure over all recorded attempt indices."""
    validate("repro_bundle", bundle)
    kept = tuple(bundle["schedule"]["kept"])
    target = bundle["failure"]["signature"]
    return sum(oracle(kept, attempt) == target
               for attempt in range(bundle["frequency"]["runs"]))
