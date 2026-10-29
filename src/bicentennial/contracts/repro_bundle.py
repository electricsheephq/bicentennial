"""Cross-field replay bundle checks, discovered by contracts.run.validate."""

import re

from bicentennial.corpus.format import (
    _HASH_FIELDS,
    _check_faults,
    _check_levers,
    _ids,
    _integer,
    _leaves,
    _require,
)
from bicentennial.repro.ddmin import Constraints, is_closed

from .run import register_check

LIFE_FIELDS = frozenset((
    "catalogue_row", "generator_version", "genre", "seed", "recipe", "template",
    "c7_entry_sha256", "levers", "fault_points", "world_hash_b0", "world_hash_b1",
    "history_set_hash", "items",
))


def _check_life(life):
    _require(life.keys() == LIFE_FIELDS, "life")
    _leaves(life, "life")
    _require(life["genre"] in ("G1", "G2"), "genre")
    _integer(life["seed"], "seed")
    _require(type(life["generator_version"]) is str, "generator_version")
    template = life["template"]
    _require(type(template) is str and
             re.fullmatch(r"[a-z0-9][a-z0-9-]*-v[1-9][0-9]*", template), "template")
    template_id = template.rsplit("-v", 1)[0]
    _require(type(life["catalogue_row"]) is str and re.fullmatch(
        re.escape(f"{life['genre'].lower()}-{template_id}-") + r"(?:mft|inv|dir)-[1-9][0-9]*",
        life["catalogue_row"]), "catalogue_row")
    _require(life["recipe"] == f"catalogue-v0:{template}", "recipe")
    for field in _HASH_FIELDS:
        _require(type(life[field]) is str and re.fullmatch(r"[0-9a-f]{64}", life[field]), field)
    _ids(life["items"], "items", nonempty=True)
    _check_levers(life)
    _check_faults(life["fault_points"], life["levers"]["sessions"])


def check_repro_bundle(bundle):
    schedule = bundle["schedule"]
    events, kept = schedule["events"], schedule["kept"]
    _require(len(events) == len(set(events)), "duplicate schedule event")
    positions = {event: index for index, event in enumerate(events)}
    known = set(events)
    _require(bool(kept) and len(kept) == len(set(kept)) and set(kept) <= known,
             "kept must be a nonempty subsequence")
    _require(kept == sorted(kept, key=positions.__getitem__), "kept schedule order")

    groups = schedule["groups"]
    for group in groups:
        _require(bool(group) and len(group) == len(set(group)) and set(group) <= known,
                 "invalid group")
        _require(group == sorted(group, key=positions.__getitem__), "group member order")
    _require(groups == sorted(groups, key=lambda group: positions[group[0]]), "group order")
    requirements = []
    for row in schedule["requires"]:
        _require(type(row) is list and len(row) == 2 and type(row[0]) is str
                 and type(row[1]) is list, "requirement shape")
        derivative, sources = row
        _require(derivative in known and bool(sources)
                 and all(type(source) is str for source in sources), "invalid requires")
        _require(len(sources) == len(set(sources)) and set(sources) <= known,
                 "invalid requires sources")
        _require(sources == sorted(sources, key=positions.__getitem__), "source order")
        requirements.append((derivative, frozenset(sources)))
    _require(schedule["requires"] == sorted(schedule["requires"],
             key=lambda row: (positions[row[0]], row[1])), "requirement order")
    constraints = Constraints(tuple(frozenset(group) for group in groups), tuple(requirements))
    _require(is_closed(kept, constraints), "kept is not closed")
    failures, runs = bundle["frequency"]["failures"], bundle["frequency"]["runs"]
    threshold = bundle["failure"]["threshold"]
    _require(1 <= threshold <= runs and threshold <= failures <= runs, "frequency")
    _integer(bundle["minimality"]["tests"], "tests", 1)
    _check_life(bundle["life"])


register_check("repro_bundle", check_repro_bundle)
