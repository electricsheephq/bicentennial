"""Offline K14 scoring wire contracts and stable/volatile partition acceptance."""

import copy
import json
import re
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.bundle import bundle_outcome
from bicentennial.contracts.run import SCHEMAS, validate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/scoring"
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"


def example(name):
    return json.loads((FIXTURES / "contracts.json").read_bytes())["contracts"][name]


def outcome(score=1000, failure=None, *, second=False):
    item = example("item_outcome")
    item.update(score_milli=score, failure_class=failure,
                worst_case_milli=-1000 if failure == "SYSTEM_FAILURE" else score)
    if second:
        item["item_id"] = "item-b"
    if score is None or failure == "SYSTEM_FAILURE":
        item["envelope"] = None
    return item


def property_paths(node, prefix):
    for key, child in node.get("properties", {}).items():
        path = f"{prefix}.{key}"
        yield path
        yield from property_paths(child, path)
    if "items" in node:
        yield from property_paths(node["items"], prefix + "[]")


def test_stable_field_table_exactly_covers_schema_property_paths():
    rows = re.findall(r"^\| `([^`]+)` \| (stable|volatile) \| ([^\n]+) \|$",
                      (ROOT / "docs/scoring/STABLE-FIELDS.md").read_text(), re.MULTILINE)
    expected = {}
    for name, prefix, stability in (("card_ring0", "card", "stable"),
                                     ("receipt", "receipt", "volatile")):
        schema = json.loads((SCHEMAS / f"{name}.schema.json").read_bytes())
        expected.update(dict.fromkeys(property_paths(schema, prefix), stability))
    assert len(rows) == len({path for path, _, _ in rows})
    assert {path: stability for path, stability, _ in rows} == expected
    assert all("RING0 §" in source or "PREREG §" in source for _, _, source in rows)


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_every_fixture_is_canonical_and_carries_canary(path):
    raw = path.read_bytes()
    value = json.loads(raw)
    assert value["canary"] == CANARY
    assert canon(value) == raw


@pytest.mark.parametrize("name", ["raw_float", "nonresult_scored", "system_failure_scored"])
def test_invalid_fixtures_are_rejected(name):
    specimen = json.loads((FIXTURES / f"{name}.json").read_bytes())
    value = json.loads(specimen["raw_json"]) if "raw_json" in specimen else specimen["value"]
    with pytest.raises(ValueError):
        validate(specimen["contract"], value)


@pytest.mark.parametrize("left,right,expected", [
    ((500, None), (1000, None), (500, None)),
    ((1000, None), (None, "BLOCKED"), (None, "BLOCKED")),
    ((None, "BLOCKED"), (None, "N/A_EXPOSURE"), (None, "BLOCKED")),
    ((None, "N/A_EXPOSURE"), (None, "N/A_CLOCK"), (None, "N/A_EXPOSURE")),
    ((0, "SYSTEM_FAILURE"), (1000, None), (0, "SYSTEM_FAILURE")),
    ((0, "FAIL_TASK"), (1000, None), (0, "FAIL_TASK")),
    ((0, None), (0, "SYSTEM_FAILURE"), (0, "SYSTEM_FAILURE")),
    ((0, "FAIL_TASK"), (0, "SYSTEM_FAILURE"), (0, "SYSTEM_FAILURE")),
    ((-1000, None), (0, "SYSTEM_FAILURE"), (-1000, None)),
])
def test_e11_table_is_symmetric_and_preserves_items(left, right, expected):
    a, b = outcome(*left), outcome(*right, second=True)
    before = copy.deepcopy((a, b))
    result = dict(score_milli=expected[0], failure_class=expected[1])
    assert bundle_outcome(a, b) == result
    assert bundle_outcome(b, a) == result
    assert (a, b) == before


@pytest.mark.parametrize("label", list(example("card_ring0")["labels"]))
@pytest.mark.parametrize("operation", ["missing", "changed"])
def test_every_fixed_label_is_required_and_exact(label, operation):
    card = example("card_ring0")
    if operation == "missing":
        del card["labels"][label]
    else:
        card["labels"][label] += " altered"
    with pytest.raises(ValueError):
        validate("card_ring0", card)


def test_scripted_label_is_optional_only_at_t0():
    card = example("card_ring0")
    card["tier"] = "T0"
    del card["labels"]["scripted_model"]
    validate("card_ring0", card)


@pytest.mark.parametrize("change", [
    {"score_milli": 1001}, {"score_milli": -1001}, {"score_milli": True},
    {"score_milli": None}, {"worst_case_milli": None},
    {"failure_class": "INFRA_FAILURE"}, {"infra_reruns": 3},
    {"infra_reruns": -1}, {"infra_reruns": True},
    {"failure_class": "FAIL_TASK"}, {"failure_class": "SYSTEM_FAILURE"},
    {"accuracy_correct": True}, {"envelope": None}, {"tuesday_class": "late"},
    {"competing_present": ["option-a"]}, {"competing_present": ["x", "x"]},
    {"selected_option": None}, {"extra": "not allowed"},
])
def test_item_semantic_and_structural_rejections(change):
    item = example("item_outcome")
    item.update(change)
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("failure", ["BLOCKED", "N/A_EXPOSURE", "N/A_CLOCK"])
def test_nonresults_and_worst_case_null(failure):
    item = outcome(None, failure)
    validate("item_outcome", item)
    item["worst_case_milli"] = 0
    with pytest.raises(ValueError):
        validate("item_outcome", item)


def test_e10_missing_qa_envelope_and_system_failure_are_distinct():
    item = outcome(-1000)
    item["envelope"] = None
    validate("item_outcome", item)
    system = outcome(0, "SYSTEM_FAILURE")
    validate("item_outcome", system)
    system["worst_case_milli"] = 0
    with pytest.raises(ValueError):
        validate("item_outcome", system)


def test_action_accuracy_is_independent_of_benign_extra_cap():
    item = outcome(0)
    item.update(stage="act", base_verdict="PASS", benign_extra=True,
                accuracy_correct=True, envelope=None)
    validate("item_outcome", item)
    item.update(score_milli=1000, worst_case_milli=1000)
    with pytest.raises(ValueError):
        validate("item_outcome", item)
    item.update(score_milli=0, worst_case_milli=-1000,
                failure_class="SYSTEM_FAILURE", accuracy_correct=False)
    validate("item_outcome", item)
    item["accuracy_correct"] = True
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("kind,value", [
    ("entity_id", "entity-1"), ("date", "2026-01-01"), ("time", "12:00"),
    ("number", 12), ("number", "0.125"), ("set", ["a", "b"]),
    ("ordered_list", ["b", "a"]), ("verbatim_span", "a quote"),
    ("citation", "event-1"), ("boolean", True), ("UNKNOWN", None),
    ("false_premise_correction", "the premise is false"),
    ("environment_state", {"enabled": True}), ("action_trace", [{"tool": "set"}]),
])
def test_answer_types_and_confidence_boundaries(kind, value):
    item = example("item_outcome")
    item["envelope"].update(type=kind, value=value)
    if kind == "UNKNOWN":
        item["envelope"].update(confidence_milli=0, citation=None)
        item["selected_option"] = None
    validate("item_outcome", item)
    item["envelope"]["confidence_milli"] = 1001
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("kind,value", [("boolean", 1), ("number", True),
    ("number", "01.5"), ("set", {}), ("environment_state", []), ("entity_id", "")])
def test_envelope_rejects_wrong_value_type(kind, value):
    item = example("item_outcome")
    item["envelope"].update(type=kind, value=value)
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("change", [{"items": ["a"]}, {"items": ["a", "a"]},
    {"items": ["a", "b", "c"]}, {"score_milli": 1001},
    {"failure_class": "BLOCKED"}, {"failure_class": "INFRA_FAILURE"}])
def test_bundle_schema_and_semantics(change):
    bundle = example("bundle_outcome")
    bundle.update(change)
    with pytest.raises(ValueError):
        validate("bundle_outcome", bundle)


@pytest.mark.parametrize("edit", [
    lambda c: c["bundles"][0].update(score_milli=0),
    lambda c: c["bundles"][0].update(items=["missing", "item-b"]),
    lambda c: c["bundles"][0].update(cell_id="other"),
    lambda c: c["items"].append(copy.deepcopy(c["items"][0])),
    lambda c: c["aggregates"][0].update(score_milli=1001),
    lambda c: c["sensitivity"]["minus_one_at_minus_two"][0].update(score_milli=-2001),
    lambda c: c["coverage"].update(coverage_milli=999),
    lambda c: c["coverage"].update(blocked=1),
    lambda c: c["controls"].update(naive_rag="not measured"),
    lambda c: c["controls"].update(full_history="not run in v0.1"),
    lambda c: c["controls"].update(wiped_store="PASS"),
    lambda c: c["controls"].update(wiped_store="uninformative"),
    lambda c: c.update(run_status="INFRA_FAILURE"),
    lambda c: c["diagnostics"][0].update(competing_milli=1001),
    lambda c: c.update(carry_over_milli=1001),
    lambda c: c["per_item_accuracy"].append(
        dict(cell_id="act-1", correct=1, eligible=2, accuracy_milli=1000)),
])
def test_card_rejects_inconsistent_outcomes_and_gate(edit):
    card = example("card_ring0")
    edit(card)
    with pytest.raises(ValueError):
        validate("card_ring0", card)


def test_nonresult_bundle_keeps_system_failure_in_item_and_worst_case():
    card = example("card_ring0")
    card["items"] = [outcome(0, "SYSTEM_FAILURE"), outcome(None, "N/A_EXPOSURE", second=True)]
    card["bundles"][0].update(score_milli=None, failure_class="N/A_EXPOSURE")
    card["coverage"].update(scored=0, na_exposure=1, coverage_milli=0)
    card["gate_verdict"] = "FAIL"
    validate("card_ring0", card)
    assert card["items"][0]["worst_case_milli"] == -1000
    assert card["items"][0]["failure_class"] == "SYSTEM_FAILURE"


@pytest.mark.parametrize("change", [
    {"load_milli": [0, 0]}, {"ports": [65536]}, {"ports": [0]},
    {"wall_end_ms": 99}, {"spend_micro_usd": -1}, {"raw_body_digest": "bad"},
])
def test_receipt_units_and_bounds(change):
    receipt = example("receipt")
    receipt.update(change)
    with pytest.raises(ValueError):
        validate("receipt", receipt)


def test_receipt_allows_signed_store_growth_and_run_infra_status():
    receipt = example("receipt")
    receipt.update(store_growth_bytes=-32, run_status="INFRA_FAILURE")
    validate("receipt", receipt)
