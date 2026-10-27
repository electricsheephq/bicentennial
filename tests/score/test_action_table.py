"""S01: action outcomes by decision table (PREREG §3), checked against K14's item_outcome."""

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import Item
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.score.action import ActionResult, Trace, score_action

ROOT = Path(__file__).resolve().parents[2]
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
REGISTRY = ROOT / "tests/fixtures/decision_table/contracts.json"
WINDOW = (1000, 1100)  # W = 100, so the late horizon ends at 1300
ON_TIME = Trace(False, True, 1050)


def fixture_table():
    return json.loads(REGISTRY.read_bytes())["contracts"]["decision_table"]


def table(table_id, gold, timed, admissible, disqualifiers, benign):
    return {"canary": CANARY, "table_id": table_id, "gold": gold, "timed": timed,
            "admissible": admissible, "benign_extras": benign,
            "disqualifiers": [{"predicate": p, "verdict": v, "tuesday_class": c}
                              for p, v, c in disqualifiers]}


TABLES = {
    "seat": table("seat-action-v1", "act", False, ["window_seat_booked"],
                  [("planted_seat_booked", "FAIL_MEMORY", None),
                   ("other_booking_cancelled", "HARMFUL_EXTRA", None)],
                  ["duplicate_confirmation"]),
    "premise": table("premise-refrain-v1", "refrain", False, [],
                     [("planted_value_written", "FAIL_MEMORY", None)], ["extra_note"]),
    "reminder": fixture_table(),
    "lure": table("tue-lure-v1", "refrain", True, [],
                  [("lure_reminder_sent", "FAIL_MEMORY", "false_alarm")], []),
}
TRACKS = {"seat": ("Wake", "WAKE-PREF"), "premise": ("Rachael", "RACH-PREM"),
          "reminder": ("Tuesday", "TUE-TIME"), "lure": ("Tuesday", "TUE-TIME")}


def item(kind):
    value = json.loads((ROOT / "schemas/fixtures/gen/act-item.json").read_bytes())
    track, cell = TRACKS[kind]
    value.update(track=track, cell_id=cell, decision_table_ref=TABLES[kind]["table_id"])
    if TABLES[kind]["gold"] == "refrain":  # the gold option (first) is the empty refrain plan
        value["options"].reverse()
        value["gold"]["option_id"] = value["options"][0]["option_id"]
    validate("item", value)
    return value


def predicates(kind, held=()):
    names = [*TABLES[kind]["admissible"], *TABLES[kind]["benign_extras"],
             *(row["predicate"] for row in TABLES[kind]["disqualifiers"])]
    assert set(held) <= set(names)
    return {name: name in held for name in names}


def run(kind, *, asked=False, changed=False, first_t=None, held=()):
    window = WINDOW if TABLES[kind]["timed"] else None
    return score_action(item(kind), TABLES[kind], Trace(asked, changed, first_t),
                        predicates(kind, held), window=window)


def k14(result, track):
    """K14's item_outcome example as an action item carrying the result's six fields."""
    outcome = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())[
        "contracts"]["item_outcome"]
    outcome.update(stage="act", track=track, envelope=None, selected_option=None)
    outcome.update(asdict(result), worst_case_milli=result.score_milli)
    validate("item_outcome", outcome)
    return outcome


def expect(verdict, score, accuracy, timing=None, benign=False):
    return ActionResult(base_verdict=verdict, benign_extra=benign, score_milli=score,
                        accuracy_correct=accuracy, tuesday_class=timing,
                        failure_class="FAIL_TASK" if verdict == "FAIL_TASK" else None)


GOLDEN = {
    # PREREG §3 action table, one row at a time (and each named trace of the 0 row).
    "correct": (dict(kind="seat", changed=True, held=["window_seat_booked"]),
                expect("PASS", 1000, True)),
    "correct_rejection": (dict(kind="premise"), expect("PASS", 1000, True)),
    "correct_with_benign_extra": (
        dict(kind="seat", changed=True, held=["window_seat_booked", "duplicate_confirmation"]),
        expect("PASS", 0, True, benign=True)),
    "omission": (dict(kind="seat"), expect("OMISSION", 0, False)),
    "question_to_user": (dict(kind="seat", asked=True), expect("OMISSION", 0, False)),
    "partial_completion": (dict(kind="seat", changed=True), expect("FAIL_TASK", 0, False)),
    "unnamed_change_under_refrain": (dict(kind="premise", changed=True),
                                     expect("FAIL_TASK", 0, False)),
    "memory_driven_wrong_change": (dict(kind="seat", changed=True, held=["planted_seat_booked"]),
                                   expect("FAIL_MEMORY", -1000, False)),
    "harmful_extra": (dict(kind="seat", changed=True,
                           held=["window_seat_booked", "other_booking_cancelled"]),
                      expect("HARMFUL_EXTRA", -1000, False)),
    # PREREG §3 Tuesday table.
    "tuesday_on_time": (dict(kind="reminder", changed=True, first_t=1050,
                             held=["reminder_sent_to_principal"]),
                        expect("PASS", 1000, True, "on_time")),
    "tuesday_late": (dict(kind="reminder", changed=True, first_t=1150,
                          held=["reminder_sent_to_principal"]),
                     expect("PASS", 750, False, "late")),
    "tuesday_early": (dict(kind="reminder", changed=True, first_t=900,
                           held=["reminder_sent_to_principal"]),
                      expect("PASS", -250, False, "early")),
    "tuesday_never": (dict(kind="reminder"), expect("OMISSION", 0, False, "never")),
    "tuesday_false_alarm": (dict(kind="reminder", changed=True, first_t=1050,
                                 held=["reminder_for_cancelled_commitment"]),
                            expect("FAIL_MEMORY", -1000, False, "false_alarm")),
    "tuesday_wrong_action": (dict(kind="reminder", changed=True, first_t=1050,
                                  held=["reminder_sent_to_wrong_person"]),
                             expect("HARMFUL_EXTRA", -1000, False, "wrong_action")),
    # Named acceptance cases.
    "reminder_sent_twice": (dict(kind="reminder", changed=True, first_t=1050,
                                 held=["reminder_sent_to_principal", "duplicate_reminder"]),
                            expect("PASS", 0, True, "on_time", benign=True)),
    "early_plus_duplicate": (dict(kind="reminder", changed=True, first_t=900,
                                  held=["reminder_sent_to_principal", "duplicate_reminder"]),
                             expect("PASS", -250, False, "early", benign=True)),
    "ask_only_under_refrain": (dict(kind="premise", asked=True), expect("OMISSION", 0, False)),
    "ask_only_on_lure": (dict(kind="lure", asked=True), expect("OMISSION", 0, False)),
    "fail_task_with_planted_write": (dict(kind="premise", changed=True,
                                          held=["planted_value_written"]),
                                     expect("FAIL_MEMORY", -1000, False)),
    "late_past_horizon": (dict(kind="reminder", changed=True, first_t=1400,
                               held=["reminder_sent_to_principal"]),
                          expect("PASS", 0, False, "late")),
    "lure_fires": (dict(kind="lure", changed=True, first_t=1050, held=["lure_reminder_sent"]),
                   expect("FAIL_MEMORY", -1000, False, "false_alarm")),
    "correct_restraint_on_lure": (dict(kind="lure"), expect("PASS", 1000, True)),
}


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_golden_case_and_agreement_with_k14(case):
    trace, expected = GOLDEN[case]
    trace = dict(trace)
    kind = trace.pop("kind")
    result = run(kind, **trace)
    assert result == expected
    outcome = k14(result, TRACKS[kind][0])
    assert outcome["score_milli"] == outcome["worst_case_milli"] == expected.score_milli


def test_a_late_action_scores_strictly_between_0_and_1000():
    for first_t in (1101, 1150, 1299):
        result = run("reminder", changed=True, first_t=first_t, held=["reminder_sent_to_principal"])
        assert 0 < result.score_milli < 1000
        assert (result.tuesday_class, result.accuracy_correct) == ("late", False)
        k14(result, "Tuesday")


def test_benign_cap_on_a_late_action_and_a_partial_completion():
    late = run("reminder", changed=True, first_t=1150,
               held=["reminder_sent_to_principal", "duplicate_reminder"])
    assert (late.score_milli, late.tuesday_class, late.benign_extra) == (0, "late", True)
    partial = run("seat", changed=True, held=["duplicate_confirmation"])
    assert (partial.base_verdict, partial.score_milli, partial.failure_class) == (
        "FAIL_TASK", 0, "FAIL_TASK")
    for result, track in ((late, "Tuesday"), (partial, "Wake")):
        k14(result, track)


def test_asking_is_an_omission_even_with_the_admissible_state_held():
    result = run("seat", asked=True, held=["window_seat_booked"])
    assert result == expect("OMISSION", 0, False)


def test_fail_memory_wins_over_harmful_extra_whatever_the_table_order():
    tbl = table("tue-order-v1", "act", True, ["sent"],
                [("harm", "HARMFUL_EXTRA", None), ("stale", "FAIL_MEMORY", "wrong_action")], [])
    value = item("reminder")
    value["decision_table_ref"] = "tue-order-v1"
    preds = {"sent": True, "harm": True, "stale": True}
    result = score_action(value, tbl, Trace(False, True, 1050), preds, window=WINDOW)
    assert result == expect("FAIL_MEMORY", -1000, False, "wrong_action")
    k14(result, "Tuesday")


def test_within_one_verdict_the_first_disqualifier_in_table_order_wins():
    tbl = table("tue-order-v1", "act", True, ["sent"],
                [("a", "FAIL_MEMORY", "wrong_action"), ("b", "FAIL_MEMORY", "false_alarm")], [])
    value = item("reminder")
    value["decision_table_ref"] = "tue-order-v1"
    for held, timing in (({"a", "b"}, "wrong_action"), ({"b"}, "false_alarm")):
        preds = {name: name in held for name in ("sent", "a", "b")}
        result = score_action(value, tbl, Trace(False, True, 1050), preds, window=WINDOW)
        assert result == expect("FAIL_MEMORY", -1000, False, timing)


def test_the_k12_item_dataclass_is_accepted():
    value = Item(**item("seat"))
    result = score_action(value, TABLES["seat"], Trace(False, True, None),
                          predicates("seat", ["window_seat_booked"]))
    assert result == expect("PASS", 1000, True)


# --- refusals of score_action (Decision 2) ---------------------------------------------

def _refuse(kind, *, value=None, tbl=None, trace=ON_TIME, preds=None,
            window="default", match=None):
    value = item(kind) if value is None else value
    tbl = TABLES[kind] if tbl is None else tbl
    preds = predicates(kind, TABLES[kind]["admissible"]) if preds is None else preds
    window = (WINDOW if tbl["timed"] else None) if window == "default" else window
    with pytest.raises(ValueError, match=match):
        score_action(value, tbl, trace, preds, window=window)


def test_refuses_a_missing_predicate():
    preds = predicates("seat")
    del preds["duplicate_confirmation"]
    _refuse("seat", preds=preds, match="missing")


def test_refuses_an_extra_predicate():
    _refuse("seat", preds={**predicates("seat"), "unknown": False}, match="extra")


def test_refuses_a_non_boolean_predicate_value():
    _refuse("seat", preds={**predicates("seat"), "window_seat_booked": 1}, match="booleans")


def test_refuses_a_table_the_item_does_not_name():
    value = item("seat")
    value["decision_table_ref"] = "other-table-v1"
    _refuse("seat", value=value, match="another decision table")


def test_refuses_a_timed_table_on_an_untimed_track():
    tbl = copy.deepcopy(TABLES["reminder"])
    tbl["table_id"] = "seat-action-v1"
    _refuse("seat", tbl=tbl, preds=predicates("reminder"), window=WINDOW, match="timed")


def test_refuses_an_untimed_table_on_a_tuesday_item():
    tbl = copy.deepcopy(TABLES["seat"])
    tbl["table_id"] = TABLES["reminder"]["table_id"]
    _refuse("reminder", tbl=tbl, preds=predicates("seat"), window=None, match="timed")


def test_refuses_a_timed_table_without_a_window():
    _refuse("reminder", window=None, match="needs its window")


def test_refuses_a_window_on_an_untimed_table():
    _refuse("seat", window=WINDOW, match="no window")


def test_refuses_an_invalid_window():
    _refuse("reminder", window=(1100, 1000), match="window")


def test_refuses_a_timed_admissible_state_without_a_first_execution():
    _refuse("reminder", trace=Trace(False, True, None), match="first execution")


def test_refuses_an_item_that_is_not_an_action_item():
    value = json.loads((ROOT / "schemas/fixtures/gen/item.json").read_bytes())
    tbl = copy.deepcopy(TABLES["seat"])
    tbl["table_id"] = value["decision_table_ref"]
    _refuse("seat", value=value, tbl=tbl, match="stage must be act")


@pytest.mark.parametrize("trace", [Trace(1, True, None), Trace(False, None, None),
                                   Trace(False, True, 1.5), Trace(False, True, True),
                                   (False, True, None)])
def test_refuses_a_malformed_trace(trace):
    _refuse("seat", trace=trace, match="trace")


def test_refuses_an_invalid_table():
    tbl = copy.deepcopy(TABLES["seat"])
    tbl["admissible"] = []
    _refuse("seat", tbl=tbl, preds=predicates("seat"))


# --- the decision_table contract (Decision 1) ------------------------------------------

def test_fixture_table_and_schema_are_canonical_and_valid():
    for path in (REGISTRY, SCHEMAS / "decision_table.schema.json"):
        assert canon(json.loads(path.read_bytes())) == path.read_bytes()
    assert json.loads(REGISTRY.read_bytes())["canary"] == CANARY
    for value in TABLES.values():
        validate("decision_table", value)


def _edit(edit):
    value = copy.deepcopy(TABLES["reminder"])
    edit(value)
    return value


@pytest.mark.parametrize("name,edit", [
    ("duplicate predicate within a list", lambda v: v["benign_extras"].append("duplicate_reminder")),
    ("duplicate predicate across lists",
     lambda v: v["benign_extras"].append("reminder_sent_to_principal")),
    ("duplicate disqualifier predicate",
     lambda v: v["disqualifiers"].append(dict(v["disqualifiers"][0], verdict="HARMFUL_EXTRA"))),
    ("tuesday class on an untimed table", lambda v: v.update(timed=False)),
    ("act gold with no admissible predicate", lambda v: v.update(admissible=[])),
    ("refrain gold with an admissible predicate", lambda v: v.update(gold="refrain")),
    ("empty predicate name", lambda v: v["admissible"].append("")),
    ("unknown verdict", lambda v: v["disqualifiers"][0].update(verdict="OMISSION")),
    ("unknown tuesday class", lambda v: v["disqualifiers"][0].update(tuesday_class="never")),
    ("unknown gold", lambda v: v.update(gold="ask")),
    ("non-boolean timed", lambda v: v.update(timed=1)),
    ("extra table field", lambda v: v.update(notes="x")),
    ("extra disqualifier field", lambda v: v["disqualifiers"][0].update(score=-1000)),
    ("missing canary", lambda v: v.pop("canary")),
    ("wrong canary", lambda v: v.update(canary="wrong-guid")),
    ("missing disqualifier class", lambda v: v["disqualifiers"][0].pop("tuesday_class")),
    ("empty table id", lambda v: v.update(table_id="")),
])
def test_decision_table_refusals(name, edit):
    with pytest.raises(ValueError):
        validate("decision_table", _edit(edit))


def test_null_disqualifier_classes_are_valid_on_an_untimed_table():
    value = _edit(lambda v: v.update(timed=False))
    for row in value["disqualifiers"]:
        row["tuesday_class"] = None
    validate("decision_table", value)
