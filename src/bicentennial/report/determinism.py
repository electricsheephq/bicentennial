"""Byte identity and the first differing stable field, in the published order."""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass

from bicentennial.canon import canon

FIELD_ORDER = (
    "card.canary",
    "card.tier",
    "card.system",
    "card.run_status",
    "card.pins",
    "card.pins.benchmark_commit",
    "card.pins.generator_commit",
    "card.pins.director_commit",
    "card.pins.scorer_commit",
    "card.pins.pack_hash",
    "card.pins.seed_hash",
    "card.pins.harness_hash",
    "card.pins.system_hash",
    "card.pins.route_table_hash",
    "card.pins.write_turn_package_hash",
    "card.pins.environment_boundary_hash",
    "card.pins.repository_boundary_hash",
    "card.pins.masks_hash",
    "card.masked_ledger_digest",
    "card.labels",
    "card.labels.signal",
    "card.labels.filters",
    "card.labels.rungs",
    "card.labels.voice",
    "card.labels.act",
    "card.labels.scripted_model",
    "card.items",
    "card.items[].item_id",
    "card.items[].cell_id",
    "card.items[].stage",
    "card.items[].track",
    "card.items[].base_verdict",
    "card.items[].benign_extra",
    "card.items[].failure_class",
    "card.items[].infra_reruns",
    "card.items[].score_milli",
    "card.items[].worst_case_milli",
    "card.items[].accuracy_correct",
    "card.items[].tuesday_class",
    "card.items[].envelope",
    "card.items[].envelope.type",
    "card.items[].envelope.value",
    "card.items[].envelope.confidence_milli",
    "card.items[].envelope.citation",
    "card.items[].envelope.citation.quote",
    "card.items[].envelope.citation.context_offset",
    "card.items[].selected_option",
    "card.items[].competing_present",
    "card.items[].carry_over",
    "card.items[].stage_attribution",
    "card.bundles",
    "card.bundles[].bundle_id",
    "card.bundles[].cell_id",
    "card.bundles[].life",
    "card.bundles[].twin_type",
    "card.bundles[].items",
    "card.bundles[].score_milli",
    "card.bundles[].failure_class",
    "card.aggregates",
    "card.aggregates[].stage",
    "card.aggregates[].track",
    "card.aggregates[].score_milli",
    "card.sensitivity",
    "card.sensitivity.minus_one_at_zero",
    "card.sensitivity.minus_one_at_zero[].stage",
    "card.sensitivity.minus_one_at_zero[].track",
    "card.sensitivity.minus_one_at_zero[].score_milli",
    "card.sensitivity.minus_one_at_minus_two",
    "card.sensitivity.minus_one_at_minus_two[].stage",
    "card.sensitivity.minus_one_at_minus_two[].track",
    "card.sensitivity.minus_one_at_minus_two[].score_milli",
    "card.worst_case",
    "card.worst_case[].stage",
    "card.worst_case[].track",
    "card.worst_case[].score_milli",
    "card.worst_case[].blocked",
    "card.twin_consistency",
    "card.twin_consistency[].track",
    "card.twin_consistency[].consistent",
    "card.twin_consistency[].scored",
    "card.twin_consistency[].consistency_milli",
    "card.singletons",
    "card.singletons[].item_id",
    "card.singletons[].life",
    "card.per_item_accuracy",
    "card.per_item_accuracy[].cell_id",
    "card.per_item_accuracy[].correct",
    "card.per_item_accuracy[].eligible",
    "card.per_item_accuracy[].accuracy_milli",
    "card.per_item_accuracy[].blocked",
    "card.per_item_accuracy[].na_exposure",
    "card.per_item_accuracy[].na_clock",
    "card.coverage",
    "card.coverage.assigned",
    "card.coverage.scored",
    "card.coverage.blocked",
    "card.coverage.na_exposure",
    "card.coverage.na_clock",
    "card.coverage.coverage_milli",
    "card.controls",
    "card.controls.wiped_store",
    "card.controls.no_memory_floor",
    "card.controls.oracle_evidence",
    "card.controls.full_history",
    "card.controls.naive_rag",
    "card.diagnostics",
    "card.diagnostics[].track",
    "card.diagnostics[].competing_milli",
    "card.diagnostics[].carry_over_milli",
    "card.carry_over_milli",
    "card.competing_milli",
    "card.volatile_surface_paths",
    "card.volatile_surface_paths[].surface",
    "card.volatile_surface_paths[].path",
    "card.voids",
    "card.voids.checked",
    "card.voids.voided",
    "card.voids.void_milli",
    "card.violations",
    "card.violations[].track",
    "card.violations[].fail_memory",
    "card.violations[].harmful_extra",
    "card.violations[].harmful_omission",
    "card.gate_verdict",
)
ARRAY_KEYS = {
    "card.items": "item_id",
    "card.singletons": "item_id",
    "card.bundles": "bundle_id",
    "card.aggregates": ("stage", "track"),
    "card.sensitivity.minus_one_at_zero": ("stage", "track"),
    "card.sensitivity.minus_one_at_minus_two": ("stage", "track"),
    "card.worst_case": ("stage", "track"),
    "card.twin_consistency": "track",
    "card.diagnostics": "track",
    "card.violations": "track",
    "card.per_item_accuracy": "cell_id",
    "card.volatile_surface_paths": ("surface", "path"),
}


@dataclass(frozen=True)
class Determinism:
    identical: bool
    first_field: str | None
    sha256_a: str
    sha256_b: str

    def to_obj(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def stable_projection(raw: bytes) -> dict:
    try:
        card = json.loads(raw)
        if type(raw) is not bytes or not isinstance(card, dict) or canon(card) != raw:
            raise ValueError("expected a canonical JSON object")
    except (TypeError, UnicodeError) as error:
        raise ValueError("invalid canonical JSON object") from error
    return card


def _index(p, rows):
    keys, result = ARRAY_KEYS[p], {}
    for row in rows:
        try:
            key = row[keys] if isinstance(keys, str) else tuple(row[k] for k in keys)
            if key in result:
                raise ValueError("duplicate array key")
            result[key] = row
        except (KeyError, TypeError) as error:
            raise ValueError("invalid array key") from error
    return result


def _children(p, c, x, y):
    if p in ARRAY_KEYS and all(isinstance(v, list) and all(isinstance(r, dict) for r in v)
                               for v in (x, y)):
        a, b = _index(p, x), _index(p, y)
        try:
            keys = sorted(a.keys() | b.keys())
        except TypeError as error:
            raise ValueError("invalid array key") from error
        for key in keys:
            yield p + "[]", f"{c}[{canon(key).decode()}]", a, b, key
    elif isinstance(x, dict) and isinstance(y, dict):
        order = {field: i for i, field in enumerate(FIELD_ORDER)}
        for key in sorted(x.keys() | y.keys(), key=lambda k: (order.get(p + "." + k, len(order)), k)):
            yield p + "." + key, c + "." + key, x, y, key


def _diff(p, c, x, y):
    if canon(x) == canon(y):
        return None
    children = list(_children(p, c, x, y))
    for path, concrete, a, b, key in children:
        if key not in a or key not in b:
            return concrete
        diff = _diff(path, concrete, a[key], b[key])
        if diff is not None:
            return diff
    return c


def stable_fields(card: dict) -> tuple[str, ...]:
    def walk(p, c, value):
        children = list(_children(p, c, value, value))
        if not children:
            yield c
        for path, concrete, a, _, key in children:
            yield from walk(path, concrete, a[key])
    return tuple(walk("card", "card", card))


def determinism_check(a: bytes, b: bytes) -> Determinism:
    x, y = stable_projection(a), stable_projection(b)
    first = None if a == b else _diff("card", "card", x, y)
    assert a == b or first is not None
    return Determinism(a == b, first, hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("a")
    parser.add_argument("b")
    args = parser.parse_args(argv)
    try:
        with open(args.a, "rb") as stream:
            a = stream.read()
        with open(args.b, "rb") as stream:
            b = stream.read()
        result = determinism_check(a, b)
    except (OSError, ValueError) as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    print(canon(result.to_obj()).decode())
    return 0 if result.identical else 1


if __name__ == "__main__":
    sys.exit(main())
