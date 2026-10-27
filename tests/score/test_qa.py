"""S02: the QA envelope scorer, answer-type matchers and calibration, checked against K14."""

import copy
import json
from fractions import Fraction
from pathlib import Path

import pytest

from bicentennial.contracts.run import validate
from bicentennial.score.answer_types import kendall_tau, matches, normalize, set_f1
from bicentennial.score.calibration import (
    assertion_precision,
    brier,
    ece,
    selective_accuracy,
)
from bicentennial.score.qa import QAResult, parse_envelope, score_qa

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ["Seat request: a window seat, WINDOW-7401, on every flight."]
OTHER_EVENT = "Lunch is at noon in room four."


def load(path):
    return json.loads((ROOT / path).read_bytes())


def k14_example():
    return load("tests/fixtures/scoring/contracts.json")["contracts"]["item_outcome"]


def known_item(kind="entity", value="WINDOW-7401"):
    item = load("schemas/fixtures/gen/item.json")
    item["options"][0]["envelope"].update(type=kind, value=value)
    validate("item", item)
    return item


def never_observed_item():
    item = load("schemas/fixtures/gen/unknown-item.json")
    validate("item", item)
    return item


def env(kind, value, confidence=1000, citation=None):
    return {"type": kind, "value": value, "confidence_milli": confidence, "citation": citation}


UNKNOWN = env("unknown", None, 0)


def outcome(result):
    """Spec "Agreement with K14": the result must validate as an item_outcome."""
    item = k14_example()
    unknown = result.envelope is not None and result.envelope["type"] == "unknown"
    item.update(stage="remember", envelope=copy.deepcopy(result.envelope),
                score_milli=result.score_milli, failure_class=result.failure_class,
                selected_option=None if unknown else "option-a",
                worst_case_milli=-1000 if result.failure_class == "SYSTEM_FAILURE"
                else result.score_milli)
    validate("item_outcome", item)
    return item


def score(item, envelope, evidence=EVIDENCE, **options):
    result = score_qa(item, envelope, evidence_texts=evidence, **options)
    outcome(result)
    return result


# --- Answer types (DESIGN §7.5): (type, gold, a right answer, a wrong answer, tolerance_s).
ANSWER_TYPES = [
    ("entity", "WINDOW-7401", "WINDOW-7401", "AISLE-9201", 0),
    ("datetime", 1767225600, 1767225660, 1767225661, 60),
    ("number", "0.50", "0.5", "0.51", 0),
    ("number", 12, "12.000", "12.001", 0),
    ("set", ["a", "b", "c"], ["c", "a", "b"], ["a", "b", "b"], 0),
    ("ordered_list", ["a", "b", "c"], ["a", "b", "c"], ["b", "a", "c"], 0),
    ("span", "The Blue  Door", "  the blue\ndoor ", "the red door", 0),
    ("citation", "event-1", "EVENT-1", "event-2", 0),
    ("boolean", True, True, False, 0),
    ("premise_correction", "The meeting was never moved.", "the meeting was\tNEVER moved.",
     "The meeting moved.", 0),
    ("env_state", {"enabled": True, "level": 2}, {"level": 2, "enabled": True},
     {"enabled": False, "level": 2}, 0),
]


@pytest.mark.parametrize("kind,gold,right,wrong,tolerance", ANSWER_TYPES)
def test_golden_answer_type(kind, gold, right, wrong, tolerance):
    item = known_item(kind, gold)
    hit = score(item, env(kind, right), tolerance_s=tolerance)
    assert hit == QAResult(env(kind, right), 1000, None, True)
    miss = score(item, env(kind, wrong), tolerance_s=tolerance)
    assert miss == QAResult(env(kind, wrong), -1000, None, False)


def test_matchers_edges():
    gold = env("entity", "WINDOW-7401")
    assert not matches(gold, env("span", "WINDOW-7401"))  # a type mismatch is false
    with pytest.raises(ValueError):
        matches(UNKNOWN, UNKNOWN)  # the rubric scores unknown
    with pytest.raises(ValueError):
        matches(gold, gold, tolerance_s=-1)
    stamp = env("datetime", 100)
    assert matches(stamp, env("datetime", 100)) and not matches(stamp, env("datetime", 101))
    assert matches(stamp, env("datetime", 40), tolerance_s=60)
    assert not matches(env("boolean", True), env("entity", "True"))
    assert not matches(env("set", ["1"]), env("set", [1]))  # canon bytes differ
    assert normalize("  Cafe\u0301 \n\t  NOIR ") == normalize("caf\u00e9 noir") == "caf\u00e9 noir"


def test_set_f1_and_kendall_tau_are_diagnostics():
    assert set_f1(env("set", ["a", "b", "c"]), env("set", ["b", "c", "d"])) == Fraction(2, 3)
    assert set_f1(env("set", []), env("set", [])) == 1
    assert set_f1(env("set", ["a"]), env("set", [])) == 0
    order = env("ordered_list", ["a", "b", "c", "d"])
    # Six pairs, one discordant (b, c): (5 - 1) / 6.
    assert kendall_tau(order, env("ordered_list", ["a", "c", "b", "d"])) == Fraction(2, 3)
    assert kendall_tau(order, env("ordered_list", ["d", "c", "b", "a"])) == -1
    # Only the shared elements count: a and b, reversed.
    assert kendall_tau(env("ordered_list", ["a", "b", "x"]),
                       env("ordered_list", ["y", "b", "a"])) == -1
    assert kendall_tau(order, env("ordered_list", ["a", "z"])) is None
    assert kendall_tau(order, env("ordered_list", ["a", "a", "b"])) is None
    with pytest.raises(ValueError):
        set_f1(order, order)


# --- The PREREG §3 QA table, one row each, on a known gold.
@pytest.mark.parametrize("value,confidence,expected,correct", [
    ("WINDOW-7401", 1000, 1000, True),   # correct, asserted
    ("WINDOW-7401", 500, 1000, True),    # the threshold asserts
    ("WINDOW-7401", 499, 500, True),     # correct, hedged
    ("WINDOW-7401", 0, 500, True),
    ("AISLE-9201", 499, -500, False),    # wrong, hedged
    ("AISLE-9201", 0, -500, False),
    ("AISLE-9201", 500, -1000, False),   # wrong, asserted
    ("AISLE-9201", 1000, -1000, False),
])
def test_qa_table_answered_rows(value, confidence, expected, correct):
    result = score(known_item(), env("entity", value, confidence))
    assert (result.score_milli, result.failure_class, result.correct) == (expected, None, correct)


def test_qa_table_unknown_missing_unparseable_and_system_failure():
    item = known_item()
    assert score(item, UNKNOWN) == QAResult(UNKNOWN, 0, None, None)
    assert score(item, None) == QAResult(None, -1000, None, None)
    assert score(item, parse_envelope("I think it was the window seat.")) == \
        QAResult(None, -1000, None, None)
    crashed = QAResult(None, 0, "SYSTEM_FAILURE", None)
    assert outcome(crashed)["worst_case_milli"] == -1000
    # The system-failure check comes first, whatever the envelope.
    for envelope in (env("entity", "WINDOW-7401"), UNKNOWN, None):
        assert score(item, envelope, system_failure=True) == crashed


def test_never_observed_rows():
    item = never_observed_item()
    assert score(item, UNKNOWN, evidence=[]) == QAResult(UNKNOWN, 1000, None, None)
    asserted = score(item, env("entity", "WINDOW-7401"), evidence=[])
    assert (asserted.score_milli, asserted.correct) == (-1000, False)
    hedged = score(item, env("entity", "WINDOW-7401", 200), evidence=[])
    assert (hedged.score_milli, hedged.correct) == (-500, False)


# --- Citations (DESIGN §7.5: a right value with the wrong event is wrong).
def test_right_value_with_non_evidence_citation_is_wrong():
    evidence = [*EVIDENCE]
    elsewhere = env("entity", "WINDOW-7401", citation={"quote": "lunch is at noon",
                                                       "context_offset": 3})
    assert OTHER_EVENT.casefold().startswith("lunch is at noon")
    assert score(known_item(), elsewhere, evidence) == QAResult(elsewhere, -1000, None, False)
    cited = env("entity", "WINDOW-7401", citation={"quote": "A WINDOW  seat, window-7401",
                                                   "context_offset": 3})
    assert score(known_item(), cited, evidence) == QAResult(cited, 1000, None, True)
    hedged = dict(cited, confidence_milli=300)
    assert score(known_item(), hedged, evidence).score_milli == 500
    blank = env("entity", "WINDOW-7401", citation={"quote": "  ", "context_offset": 0})
    assert score(known_item(), blank, evidence).correct is False
    assert score(known_item(), cited, []).correct is False  # no evidence event to match
    wrong = dict(cited, value="AISLE-9201")  # a matching citation never rescues a wrong value
    assert score(known_item(), wrong, evidence).score_milli == -1000


def test_score_qa_rejects_caller_errors():
    with pytest.raises(ValueError):
        score_qa(dict(known_item(), stage="act"), UNKNOWN, evidence_texts=[])
    with pytest.raises(ValueError):
        score_qa(known_item(), UNKNOWN, evidence_texts=EVIDENCE[0])
    with pytest.raises(ValueError):
        score_qa(known_item(), {"type": "entity", "value": "x", "confidence_milli": 1},
                 evidence_texts=[])


# --- parse_envelope agrees with K14 in both directions.
def k14_accepts(envelope):
    item = k14_example()
    unknown = type(envelope) is dict and envelope.get("type") == "unknown"
    confidence = envelope.get("confidence_milli") if type(envelope) is dict else None
    points = 0 if unknown else 500 if type(confidence) is int and confidence < 500 else 1000
    item.update(envelope=envelope, score_milli=points, worst_case_milli=points,
                selected_option=None if unknown else "option-a")
    try:
        validate("item_outcome", item)
    except ValueError:
        return False
    return True


CITATION = {"quote": "entity-1", "context_offset": 0}
# Copied from K14's tests/test_scoring_contracts.py acceptance and rejection tables.
K14_ACCEPTED = [env(kind, value, 0 if kind == "unknown" else 1000,
                    None if kind == "unknown" else CITATION) for kind, value in [
    ("entity", "entity-1"), ("datetime", 1767225600), ("number", 12),
    ("number", "0.125"), ("number", "01.5"), ("set", ["a", "b"]),
    ("ordered_list", ["b", "a"]), ("span", "a quote"), ("citation", "event-1"),
    ("boolean", True), ("unknown", None), ("premise_correction", "the premise is false"),
    ("env_state", {"enabled": True}),
]] + [env("entity", "WINDOW-7401", 1000), env("entity", "entity-1", 0),
      env("entity", "entity-1", 1000, {"quote": "x", "context_offset": 99})]
K14_REJECTED = [env(kind, value, 1000, CITATION) for kind, value in [
    ("boolean", 1), ("number", True), ("number", "1e5"), ("number", "1."), ("set", {}),
    ("env_state", []), ("entity", ""), ("datetime", "2026-01-01"), ("datetime", True),
    ("entity_id", "entity-1"), ("date", "2026-01-01"), ("verbatim_span", "a quote"),
    ("environment_state", {"enabled": True}), ("action_trace", [{"tool": "set"}]),
]] + [
    env("entity", "entity-1", 1001), env("entity", "entity-1", -1),
    env("entity", "entity-1", True), env("entity", "entity-1", "800"),
    env("unknown", None, 1), env("unknown", None, 0, CITATION), env("unknown", "x", 0),
    env("UNKNOWN", None, 0),
    env("entity", "e", 1000, {"quote": "", "context_offset": 0}),
    env("entity", "e", 1000, {"quote": "two\nlines", "context_offset": 0}),
    env("entity", "e", 1000, {"quote": "q", "context_offset": -1}),
    env("entity", "e", 1000, {"quote": "q"}),
    env("entity", "e", 1000, {"quote": "q", "context_offset": 0, "event": "e"}),
    env("entity", "e", 1000, "a quote"),
    dict(env("entity", "e"), extra=1),
]


@pytest.mark.parametrize("envelope", K14_ACCEPTED)
def test_parse_envelope_accepts_what_k14_accepts(envelope):
    assert k14_accepts(envelope)
    assert parse_envelope(json.dumps(envelope)) == envelope


@pytest.mark.parametrize("envelope", K14_REJECTED)
def test_parse_envelope_rejects_what_k14_rejects(envelope):
    assert not k14_accepts(envelope)
    assert parse_envelope(json.dumps(envelope)) is None


ENTITY = '{"type": "entity", "value": "WINDOW-7401", "confidence_milli": 800}'


@pytest.mark.parametrize("text", [
    "not json", "", "   ", "[]", json.dumps([json.loads(ENTITY)]), "null", '"entity"',
    '{"type": "entity", "value": "WINDOW-7401", "confidence_milli": 800, "note": 1}',
    '{"type": "entity", "value": "WINDOW-7401", "confidence_milli": 800.0}',
    '{"type": "entity", "value": "WINDOW-7401", "confidence_milli": 8e2}',
    '{"type": "number", "value": NaN, "confidence_milli": 800}',
    '{"type": "number", "value": Infinity, "confidence_milli": 800}',
    '{"type": "number", "value": -Infinity, "confidence_milli": 800}',
    '{"type": "set", "value": [NaN], "confidence_milli": 800}',
    '{"type": "number", "value": 1e5, "confidence_milli": 800}',
    '{"type": "entity", "value": "x", "value": "y", "confidence_milli": 800}',
    '{"type": "entity", "value": "WINDOW-7401"}',
    ENTITY + " trailing prose", "Answer: " + ENTITY,
    "```json\n```json\n" + ENTITY + "\n```\n```",  # at most one fence is unwrapped
    "```python\n" + ENTITY + "\n```", "```json " + ENTITY + "```",
    "```json\n" + ENTITY + "\n```\nThat is my answer.",
    "[" * 100000, '{"type": "number", "value": ' + "9" * 5000 + ', "confidence_milli": 1}',
])
def test_parse_envelope_returns_none_for_malformed_text(text):
    assert parse_envelope(text) is None


def test_parse_envelope_never_raises_on_non_text():
    for value in (None, 7, b"{}", ["{}"]):
        assert parse_envelope(value) is None


def test_parse_envelope_unwraps_one_fence_and_defaults_citation():
    expected = env("entity", "WINDOW-7401", 800)
    assert parse_envelope(ENTITY) == expected
    assert parse_envelope("\n  ```json\n" + ENTITY + "\n```  \n") == expected
    assert parse_envelope("```\n" + ENTITY + "\n```") == expected
    assert parse_envelope("```json\r\n" + ENTITY + "\r\n```") == expected
    # A JSON decimal keeps its text, so it arrives as K14's decimal string.
    decimal = parse_envelope('{"type": "number", "value": 0.125, "confidence_milli": 600}')
    assert decimal == env("number", "0.125", 600)
    assert score(known_item("number", "0.1250"), decimal).score_milli == 1000


@pytest.mark.parametrize("text", [
    '{"type": "set", "value": [0.5], "confidence_milli": 1000}',  # the connector's case
    '{"type": "ordered_list", "value": [1.5, 2], "confidence_milli": 1000}',
    '{"type": "env_state", "value": {"level": 2.5}, "confidence_milli": 1000}',
    '{"type": "env_state", "value": {"levels": [{"x": 1.0}]}, "confidence_milli": 1000}',
    '{"type": "entity", "value": 0.5, "confidence_milli": 1000}',
    '{"type": "span", "value": 2.50, "confidence_milli": 1000}',
    '{"type": "number", "value": [2.5], "confidence_milli": 1000}',
    '{"type": "entity", "value": "WINDOW-7401", "confidence_milli": 800.0}',
    '{"type": "number", "value": 2.5, "confidence_milli": 800.0}',
    '{"type": "entity", "value": "e", "confidence_milli": 1000,'
    ' "citation": {"quote": "q", "context_offset": 0.0}}',
])
def test_a_float_outside_a_number_scalar_is_malformed(text):
    assert parse_envelope(text) is None


def test_a_number_float_keeps_its_source_text():
    parsed = parse_envelope('{"type": "number", "value": 2.50, "confidence_milli": 1000}')
    assert parsed == env("number", "2.50") and type(parsed["value"]) is str
    assert score(known_item("number", "2.50"), parsed).score_milli == 1000
    # The connector's set case cannot score against a string gold any more.
    gold = known_item("set", ["0.5"])
    text = '{"type": "set", "value": [0.5], "confidence_milli": 1000}'
    assert score(gold, parse_envelope(text)) == QAResult(None, -1000, None, None)


# --- Calibration (PREREG §3; DESIGN §7.2): a hand-computed 20-item fixture.
CALIBRATION = [
    (1000, True), (1000, True), (950, True), (900, False),  # bin 9 (1000 joins bin 9)
    (800, True), (850, True), (800, False),                 # bin 8
    (700, True), (750, False),                              # bin 7
    (600, True), (650, True), (600, False),                 # bin 6
    (500, False), (550, True),                              # bin 5
    (450, False), (400, True),                              # bin 4
    (250, False), (200, False),                             # bin 2
    (0, False), (50, True),                                 # bin 0
]


def test_brier_and_ece_match_hand_computation():
    # Brier: sum of (c - 1000y)^2 in milli^2, per bin:
    #   bin 9: 0 + 0 + 50^2 + 900^2           = 812500
    #   bin 8: 200^2 + 150^2 + 800^2          = 702500
    #   bin 7: 300^2 + 750^2                  = 652500
    #   bin 6: 400^2 + 350^2 + 600^2          = 642500
    #   bin 5: 500^2 + 450^2                  = 452500
    #   bin 4: 450^2 + 600^2                  = 562500
    #   bin 2: 250^2 + 200^2                  = 102500
    #   bin 0: 0^2 + 950^2                    = 902500
    #   total 4830000; Brier = 4830000 / (1000^2 * 20) = 483/2000.
    assert brier(CALIBRATION) == Fraction(483, 2000)
    # ECE: (n_k / N) * |acc_k - conf_k| = |correct_k - sum(c)_k / 1000| / N, per bin:
    #   bin 9: |3 - 3.85| = 0.85    bin 8: |2 - 2.45| = 0.45
    #   bin 7: |1 - 1.45| = 0.45    bin 6: |2 - 1.85| = 0.15
    #   bin 5: |1 - 1.05| = 0.05    bin 4: |1 - 0.85| = 0.15
    #   bin 2: |0 - 0.45| = 0.45    bin 0: |1 - 0.05| = 0.95
    #   sum 3.5; ECE = 3.5 / 20 = 7/40.
    assert ece(CALIBRATION) == Fraction(7, 40)
    assert brier([(1000, True)]) == 0 and ece([(1000, True), (0, False)]) == 0
    assert brier(iter(CALIBRATION)) == Fraction(483, 2000)


def test_selective_accuracy_and_assertion_precision():
    assert selective_accuracy(15, 20, 25) == (Fraction(4, 5), Fraction(3, 4))
    assert selective_accuracy(0, 0, 5) == (0, None)
    assert selective_accuracy(0, 0, 0) == (None, None)
    actions = [(True, True), (True, False), (True, True), (False, True), (False, False)]
    assert assertion_precision(actions) == Fraction(2, 3)
    assert assertion_precision([(False, True), (False, False)]) is None


def test_calibration_empty_denominators_and_bad_inputs():
    assert brier([]) is None and ece([]) is None and assertion_precision([]) is None
    for pairs in ([(1001, True)], [(-1, False)], [(True, True)], [(500, 1)], [(500.0, True)]):
        for metric in (brier, ece):
            with pytest.raises(ValueError):
                metric(pairs)
    for counts in ((2, 1, 3), (1, 2, 1), (-1, 0, 0), (True, 1, 1)):
        with pytest.raises(ValueError):
            selective_accuracy(*counts)
    with pytest.raises(ValueError):
        assertion_precision([(1, True)])
