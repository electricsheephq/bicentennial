"""Offline K14 scoring wire contracts and stable/volatile partition acceptance."""

import copy
import json
import os
import re
import subprocess
import sys
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
    ("entity", "entity-1"), ("datetime", 1767225600), ("number", 12),
    ("number", "0.125"), ("number", "01.5"), ("set", ["a", "b"]),
    ("ordered_list", ["b", "a"]), ("span", "a quote"), ("citation", "event-1"),
    ("boolean", True), ("unknown", None), ("premise_correction", "the premise is false"),
    ("env_state", {"enabled": True}),
])
def test_answer_types_and_confidence_boundaries(kind, value):
    item = example("item_outcome")
    item["envelope"].update(type=kind, value=value)
    if kind == "unknown":
        item["envelope"].update(confidence_milli=0, citation=None)
        item["selected_option"] = None
    validate("item_outcome", item)
    item["envelope"]["confidence_milli"] = 1001
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("kind,value", [("boolean", 1), ("number", True),
    ("number", "1e5"), ("number", "1."), ("set", {}), ("env_state", []), ("entity", ""),
    ("datetime", "2026-01-01"), ("datetime", True)])
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
        dict(cell_id="act-1", correct=1, eligible=2, accuracy_milli=1000,
             blocked=0, na_exposure=0, na_clock=0)),
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


TRACKS = ["Wake", "Drift", "Tuesday", "Rachael", "Keep", "Recall", "Faults"]
# K12 golden option envelopes (schemas/fixtures/gen/item.json there), copied verbatim.
K12_ENVELOPES = [{"confidence_milli": 1000, "type": "entity", "value": "WINDOW-7401"},
                 {"confidence_milli": 0, "type": "unknown", "value": None}]


def action(**change):
    item = example("item_outcome")
    item.update(stage="act", envelope=None, base_verdict="PASS", score_milli=1000,
                accuracy_correct=True)
    item.update(change)
    if "worst_case_milli" not in change:
        failure = item["failure_class"]
        item["worst_case_milli"] = -1000 if failure == "SYSTEM_FAILURE" else item["score_milli"]
    return item


def two_bundle_card():
    card = example("card_ring0")
    for suffix in ("c", "d"):
        card["items"].append(dict(copy.deepcopy(card["items"][0]), item_id=f"item-{suffix}",
                                  selected_option=f"option-{suffix}"))
    card["bundles"].append(dict(copy.deepcopy(card["bundles"][0]), bundle_id="bundle-2",
                                items=["item-c", "item-d"]))
    card["coverage"].update(assigned=2, scored=2)
    return card


@pytest.mark.parametrize("name,track,stage", [("recall_remember_qa", "Recall", "remember"),
                                              ("faults_survive_qa", "Faults", "survive")])
def test_recall_and_faults_qa_fixtures_validate(name, track, stage):
    value = json.loads((FIXTURES / f"{name}.json").read_bytes())["value"]
    assert (value["track"], value["stage"]) == (track, stage)
    validate("item_outcome", value)


@pytest.mark.parametrize("track", TRACKS)
def test_k12_tracks_on_items_and_card_rows(track):
    item = example("item_outcome")
    item["track"] = track
    validate("item_outcome", item)
    card = example("card_ring0")
    for row in (card["aggregates"][0], card["diagnostics"][0],
                *(rows[0] for rows in card["sensitivity"].values())):
        row["track"] = track
    validate("card_ring0", card)


@pytest.mark.parametrize("track", ["Hands", "Flatten"])
@pytest.mark.parametrize("where", ["item", "aggregate", "sensitivity", "diagnostic"])
def test_tracks_outside_v0_are_rejected(track, where):
    card = example("card_ring0")
    row = {"item": card["items"][0], "aggregate": card["aggregates"][0],
           "sensitivity": card["sensitivity"]["minus_one_at_zero"][0],
           "diagnostic": card["diagnostics"][0]}[where]
    row["track"] = track
    with pytest.raises(ValueError):
        validate("card_ring0", card)


@pytest.mark.parametrize("envelope", K12_ENVELOPES)
def test_k12_golden_option_envelope_copies_into_outcome(envelope):
    item = example("item_outcome")
    item["envelope"] = dict(copy.deepcopy(envelope), citation=None)
    if envelope["type"] == "unknown":
        item["selected_option"] = None
    validate("item_outcome", item)


@pytest.mark.parametrize("kind,value", [
    ("entity_id", "entity-1"), ("date", "2026-01-01"), ("time", "12:00"),
    ("verbatim_span", "a quote"), ("UNKNOWN", None),
    ("false_premise_correction", "the premise is false"),
    ("environment_state", {"enabled": True}), ("action_trace", [{"tool": "set"}]),
])
def test_answer_type_spellings_outside_k12_are_rejected(kind, value):
    item = example("item_outcome")
    item["envelope"].update(type=kind, value=value)
    if value is None:
        item["envelope"].update(confidence_milli=0, citation=None)
        item["selected_option"] = None
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("change", [
    {},
    dict(benign_extra=True, score_milli=0),
    dict(base_verdict="FAIL_TASK", failure_class="FAIL_TASK", score_milli=0, accuracy_correct=False),
    dict(base_verdict="FAIL_MEMORY", score_milli=-1000, accuracy_correct=False),
    dict(base_verdict="HARMFUL_EXTRA", score_milli=-1000, accuracy_correct=False),
    dict(base_verdict="OMISSION", score_milli=0, accuracy_correct=False),
    dict(track="Tuesday", tuesday_class="on_time"),
    dict(track="Tuesday", tuesday_class="late", score_milli=500, accuracy_correct=False),
])
def test_action_verdict_class_score_and_accuracy_accepted(change):
    validate("item_outcome", action(**change))


@pytest.mark.parametrize("change", [
    dict(base_verdict="FAIL_TASK", failure_class=None),
    dict(base_verdict="PASS", failure_class="FAIL_TASK", score_milli=0, accuracy_correct=False),
    dict(base_verdict="FAIL_TASK", failure_class="FAIL_TASK", score_milli=0),
    dict(base_verdict="HARMFUL_EXTRA", accuracy_correct=False),
    dict(base_verdict="FAIL_MEMORY", score_milli=0, accuracy_correct=False),
    dict(base_verdict="FAIL_MEMORY", score_milli=-1000),
    dict(accuracy_correct=False),
    dict(base_verdict="OMISSION", score_milli=0),
    dict(track="Tuesday", tuesday_class="late", score_milli=500),
    dict(track="Tuesday", tuesday_class="early", score_milli=-250),
])
def test_action_verdict_class_score_and_accuracy_rejected(change):
    with pytest.raises(ValueError):
        validate("item_outcome", action(**change))


UNKNOWN = dict(type="unknown", value=None, confidence_milli=0, citation=None)


@pytest.mark.parametrize("item", [
    dict(example("item_outcome"), selected_option=None, envelope=UNKNOWN),
    dict(example("item_outcome"), selected_option="option-empty", envelope=UNKNOWN),
    action(selected_option=None),
], ids=["null-option", "empty-token-option", "action-null-option"])
def test_competing_options_require_a_selected_token_option(item):
    validate("item_outcome", item)
    item["competing_present"] = ["option-b"]
    with pytest.raises(ValueError):
        validate("item_outcome", item)


def test_action_items_have_no_carry_over():
    item = action()
    validate("item_outcome", item)
    item["carry_over"] = True
    with pytest.raises(ValueError):
        validate("item_outcome", item)


@pytest.mark.parametrize("value,valid", [(0, True), (1000, True), (1001, False), (-1, False),
                                         (True, False)])
def test_system_competing_share_is_a_milli_share(value, valid):
    card = example("card_ring0")
    card["competing_milli"] = value
    if valid:
        validate("card_ring0", card)
    else:
        with pytest.raises(ValueError):
            validate("card_ring0", card)
    del card["competing_milli"]
    with pytest.raises(ValueError):
        validate("card_ring0", card)


def test_per_item_accuracy_rows_disclose_excluded_counts():
    card = example("card_ring0")
    row = dict(cell_id="act-1", correct=1, eligible=2, accuracy_milli=500,
               blocked=1, na_exposure=0, na_clock=2)
    card["per_item_accuracy"] = [row]
    validate("card_ring0", card)
    for key in ("blocked", "na_exposure", "na_clock"):
        for bad in (-1, None, True):
            card["per_item_accuracy"] = [dict(row, **{key: bad})]
            with pytest.raises(ValueError):
                validate("card_ring0", card)
        card["per_item_accuracy"] = [{k: v for k, v in row.items() if k != key}]
        with pytest.raises(ValueError):
            validate("card_ring0", card)


@pytest.mark.parametrize("edit", [
    None,
    lambda c: c["controls"].update(wiped_store="uninformative"),
    lambda c: c["controls"].update(wiped_store="PASS"),
    lambda c: c.update(run_status="INFRA_FAILURE"),
    lambda c: c.update(items=[], bundles=[], coverage=dict(c["coverage"], assigned=0, scored=0,
                                                           coverage_milli=None)),
])
def test_conformance_pass_carries_the_pass_requirements(edit):
    card = example("card_ring0")
    card["gate_verdict"] = "CONFORMANCE_PASS"
    if edit is None:
        validate("card_ring0", card)
        return
    edit(card)
    with pytest.raises(ValueError):
        validate("card_ring0", card)


PATHS = [{"path": "logs/agent.log", "surface": "HERMES_HOME"},
         {"path": "state.lock", "surface": "HERMES_HOME"},
         {"path": "server.log", "surface": "SERVER_DATA"}]


@pytest.mark.parametrize("paths,valid", [
    ([], True), (PATHS, True), (PATHS[::-1], False), ([PATHS[0], PATHS[0]], False),
    ([{"surface": "HERMES_HOME"}], False), ([{"path": "a", "surface": 1}], False),
    ([dict(PATHS[0], extra="x")], False),
])
def test_volatile_surface_paths_are_sorted_unique_pairs(paths, valid):
    card = example("card_ring0")
    card["volatile_surface_paths"] = copy.deepcopy(paths)
    if valid:
        validate("card_ring0", card)
    else:
        with pytest.raises(ValueError):
            validate("card_ring0", card)


def test_two_bundle_card_in_canonical_order_validates():
    validate("card_ring0", two_bundle_card())


def _row(stage, track, **extra):
    return dict(stage=stage, track=track, score_milli=1000, **extra)


@pytest.mark.parametrize("edit", [
    lambda c: c["items"].reverse(),
    lambda c: c["bundles"].reverse(),
    lambda c: c["bundles"][0]["items"].reverse(),
    lambda c: c.update(aggregates=[_row("remember", "Wake"), _row("act", "Wake")]),
    lambda c: c.update(aggregates=[_row("remember", "Wake"), _row("remember", "Wake")]),
    lambda c: c["sensitivity"].update(
        minus_one_at_zero=[_row("remember", "Wake"), _row("act", "Wake")]),
    lambda c: c["sensitivity"].update(
        minus_one_at_minus_two=[_row("remember", "Wake"), _row("remember", "Wake")]),
    lambda c: c.update(per_item_accuracy=[
        dict(cell_id=cell, correct=0, eligible=0, accuracy_milli=None,
             blocked=0, na_exposure=0, na_clock=0) for cell in ("b", "a")]),
    lambda c: c.update(diagnostics=[dict(c["diagnostics"][0], track="Wake"),
                                    dict(c["diagnostics"][0], track="Drift")]),
    lambda c: c.update(diagnostics=[c["diagnostics"][0], c["diagnostics"][0]]),
    lambda c: c["items"][0].update(stage_attribution="used"),
])
def test_card_arrays_have_one_canonical_order(edit):
    card = two_bundle_card()
    edit(card)
    with pytest.raises(ValueError):
        validate("card_ring0", card)


def test_competing_present_is_sorted_and_used_attribution_is_item_level_only():
    item = example("item_outcome")
    item.update(competing_present=["option-b", "option-c"], stage_attribution="used")
    validate("item_outcome", item)
    item["competing_present"].reverse()
    with pytest.raises(ValueError):
        validate("item_outcome", item)


def test_importing_only_run_applies_scoring_checks():
    item = outcome(None, "BLOCKED")
    item["score_milli"] = 0
    code = (
        "import json, sys\n"
        "from bicentennial.contracts.run import validate\n"
        "assert 'bicentennial.contracts.bundle' not in sys.modules\n"
        "try:\n"
        "    validate('item_outcome', json.loads(sys.argv[1]))\n"
        "except ValueError as error:\n"
        "    print(error)\n"
        "else:\n"
        "    raise SystemExit('scored BLOCKED item accepted')\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONHASHSEED="0")
    result = subprocess.run([sys.executable, "-c", code, json.dumps(item)], cwd=ROOT, env=env,
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "non-result must have null score"
