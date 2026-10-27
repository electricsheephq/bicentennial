"""Scoring semantics. Import once before using run.validate for these contracts."""

import re
from fractions import Fraction
from itertools import pairwise

from bicentennial.canon import milli
from bicentennial.contracts.run import register_check, validate

NONRESULTS = ("BLOCKED", "N/A_EXPOSURE", "N/A_CLOCK")
DISQUALIFIERS = ("FAIL_MEMORY", "HARMFUL_EXTRA")  # PREREG §3 step 1: score -1
TIMING = {"on_time": (1000, 1000), "late": (0, 1000), "early": (-250, -250)}  # §3 Tuesday table


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _ordered(keys, label):
    # One valid byte order per array (RING0 §4): strictly increasing, so keys are unique.
    _require(all(a < b for a, b in pairwise(keys)), f"{label}: not sorted and unique")


def _score(value, low=-1000):
    _require(value is None or low <= value <= 1000, "score_milli: out of range")


def _scored(record):
    score, failure = record["score_milli"], record["failure_class"]
    _score(score)
    _require((score is None) == (failure in NONRESULTS), "non-result must have null score")
    if failure in ("SYSTEM_FAILURE", "FAIL_TASK"):
        _require(score == 0, "system/task failure must score 0")


def _action_score(item):
    # PREREG §3: disqualifier, then the base score, then the benign-extra cap at min(base, 0).
    verdict, timing = item["base_verdict"], item["tuesday_class"]
    if timing in ("false_alarm", "wrong_action"):
        _require(verdict in DISQUALIFIERS, "Tuesday false alarm or wrong action must disqualify")
    if verdict in DISQUALIFIERS or item["failure_class"] is not None:
        return
    if verdict != "PASS":
        low = high = 0
    elif item["track"] == "Tuesday" and timing is not None:
        # A passing execution takes its timing score; a correct restraint (a lure) has no class.
        _require(timing in TIMING, "a passing Tuesday action needs its timing class")
        low, high = TIMING[timing]
    else:
        low = high = 1000
    if item["benign_extra"]:
        low, high = min(low, 0), min(high, 0)
    _require(low <= item["score_milli"] <= high, "action score disagrees with PREREG §3")


def _item(item):
    _scored(item)
    score, failure = item["score_milli"], item["failure_class"]
    expected = -1000 if failure == "SYSTEM_FAILURE" else score
    _require(item["worst_case_milli"] == expected, "worst-case row mismatch")
    _require(item["infra_reruns"] <= 2, "infra_reruns: at most two")
    options = item["competing_present"]
    _ordered(options, "competing_present")
    _require(item["selected_option"] not in options, "selected option is not competing")
    action, envelope = item["stage"] == "act", item["envelope"]
    # RING0 §1: a competing option is present but unselected, so the reader selected a token option.
    _require(not options or (item["selected_option"] is not None
             and (envelope is None or envelope["type"] != "unknown")),
             "competing options require a selected token option")
    accuracy = item["accuracy_correct"]
    _require((accuracy is None) == (not action or score is None), "accuracy eligibility mismatch")
    if action and score is not None:
        verdict = item["base_verdict"]
        _require((verdict == "FAIL_TASK") == (failure == "FAIL_TASK"), "FAIL_TASK verdict/class mismatch")
        _require(verdict not in DISQUALIFIERS or score == -1000, "disqualifier must score -1000")
        # PREREG §3: correct is the +1 base with no disqualifier; a Tuesday execution only on time,
        # and a correct restraint on a lure (no execution, so no class) is correct too.
        _require(accuracy == (verdict == "PASS" and failure is None and (
            item["track"] != "Tuesday" or item["tuesday_class"] in ("on_time", None))),
            "accuracy disagrees with verdict and class")
        _action_score(item)
    _require(item["tuesday_class"] is None or (action and item["track"] == "Tuesday"),
             "Tuesday class outside Tuesday action")
    if action:
        _require(envelope is None, "action envelope must be null")
        _require(item["carry_over"] is False, "carry-over is QA-only")
        if item["benign_extra"] and score is not None:
            _require(score <= 0, "benign-extra cap exceeded")
    elif envelope is None:
        _require(score is None or failure == "SYSTEM_FAILURE" or score == -1000,
                 "missing QA envelope must score -1000 unless system failure/non-result")
    if envelope is not None and not action and failure is None and score is not None:
        # PREREG §3 QA table: UNKNOWN 0 (+1 on a never-observed gold); else ±1 asserted, ±0.5 hedged.
        allowed = ((0, 1000) if envelope["type"] == "unknown" else
                   (1000, -1000) if envelope["confidence_milli"] >= 500 else (500, -500))
        _require(score in allowed, "QA score disagrees with PREREG §3")
    if envelope is not None:
        _require(envelope["confidence_milli"] <= 1000, "confidence exceeds 1000")
        kind, value = envelope["type"], envelope["value"]
        if kind == "unknown":
            _require(value is None and envelope["confidence_milli"] == 0
                     and envelope["citation"] is None, "invalid unknown envelope")
        elif kind == "boolean":
            _require(type(value) is bool, "boolean value required")
        elif kind == "datetime":  # K12 times are integer simulated Unix seconds
            _require(type(value) is int, "integer datetime required")
        elif kind == "number":  # K12's number rule, so a copied option envelope validates
            _require(type(value) is int or (type(value) is str and re.fullmatch(
                r"-?[0-9]+(?:\.[0-9]+)?", value)), "exact number required")
        elif kind in ("set", "ordered_list"):
            _require(type(value) is list, "array value required")
        elif kind == "env_state":
            _require(type(value) is dict, "state object required")
        else:
            _require(type(value) is str and bool(value), "nonempty text value required")
        if item["selected_option"] is None:
            _require(kind == "unknown", "null option must emit unknown")


def bundle_outcome(a, b):
    """Return E11's score/class projection; the caller supplies bundle identity."""
    for item in (a, b):
        validate("item_outcome", item)
    _require(a["cell_id"] == b["cell_id"], "twins must share a cell")
    _require(a["item_id"] != b["item_id"], "twins must be distinct items")
    for failure in NONRESULTS:
        if failure in (a["failure_class"], b["failure_class"]):
            return {"score_milli": None, "failure_class": failure}
    # The minimum's class wins; ties retain system failure, then task failure.
    winner = min((a, b), key=lambda i: (i["score_milli"],
        {"SYSTEM_FAILURE": 0, "FAIL_TASK": 1, None: 2}[i["failure_class"]]))
    return {key: winner[key] for key in ("score_milli", "failure_class")}


def _bundle(bundle):
    _scored(bundle)
    _require(len(bundle["items"]) == 2 and len(set(bundle["items"])) == 2,
             "bundle requires two distinct items")


def _ratio(correct, eligible, result):
    _require(correct <= eligible, "numerator exceeds denominator")
    expected = milli(Fraction(correct, eligible)) if eligible else None
    _require(result == expected, "milli ratio mismatch")


def _card(card):
    from bicentennial.score import aggregate

    if card["tier"] == "T1":
        _require("scripted_model" in card["labels"], "T1 requires scripted model label")
    items = {item["item_id"]: item for item in card["items"]}
    _ordered([item["item_id"] for item in card["items"]], "items")
    bundle_ids = [b["bundle_id"] for b in card["bundles"]]
    _ordered(bundle_ids, "bundles")
    for item in items.values():
        validate("item_outcome", item)
        _require(item["stage_attribution"] != "used", "used never fails at Ring 0")
    for bundle in card["bundles"]:
        validate("bundle_outcome", bundle)
        _ordered(bundle["items"], "bundle items")
        _require(all(i in items for i in bundle["items"]), "unknown bundle item")
        a, b = (items[i] for i in bundle["items"])
        _require(bundle["cell_id"] == a["cell_id"], "bundle cell mismatch")
        _require((a["stage"], a["track"]) == (b["stage"], b["track"]),
                 "twins must share stage and track")
        expected = bundle_outcome(a, b)
        _require(all(bundle[k] == v for k, v in expected.items()), "bundle reduction mismatch")
    # DESIGN §5.1a: each action item is in exactly one bundle, so no outcome is dropped or counted twice.
    members = [i for bundle in card["bundles"] for i in bundle["items"]]
    _require(len(members) == len(set(members)), "an item sits in two bundles")
    _require({i for i, item in items.items() if item["stage"] == "act"} <= set(members),
             "an action item belongs to no bundle")
    # S06 A2: an unbundled QA item is its own unit, so the card names its life.
    ids = [s["item_id"] for s in card.get("singletons", [])]
    _require(ids == sorted(set(ids)), "singletons must be unique and sorted by item id")
    _require(set(ids) == {i for i, item in items.items() if item["stage"] != "act"} - set(members),
             "every unbundled QA item needs exactly one singleton entry")
    bundles, singles = card["bundles"], [(items[s["item_id"]], s["life"]) for s in card.get("singletons", [])]
    _require(card["aggregates"] == aggregate.stage_track_rows(bundles, items, singletons=singles),
             "aggregate recomputation mismatch")
    for key, value in (("minus_one_at_zero", 0), ("minus_one_at_minus_two", -2000)):
        _require(card["sensitivity"][key] == aggregate.stage_track_rows(
            bundles, items, minus_one=value, singletons=singles), "sensitivity recomputation mismatch")
    _require(card["worst_case"] == aggregate.worst_case_rows(bundles, items, singletons=singles),
             "worst-case recomputation mismatch")
    _require(card["twin_consistency"] == aggregate.twin_consistency(bundles, items),
             "twin consistency recomputation mismatch")
    # PREREG §3: per-cell accuracy counts come from the card's own action outcomes.
    counts = {}
    for item in items.values():
        if item["stage"] == "act":
            row = counts.setdefault(item["cell_id"], dict.fromkeys(
                ("correct", "eligible", "blocked", "na_exposure", "na_clock"), 0))
            failure = item["failure_class"]
            if failure in NONRESULTS:
                row[failure.lower().replace("n/a_", "na_")] += 1
            else:
                row["eligible"] += 1
                row["correct"] += item["accuracy_correct"] is True
    _require({row["cell_id"] for row in card["per_item_accuracy"]} == set(counts),
             "per-item accuracy needs exactly one row per action cell")
    for row in card["per_item_accuracy"]:
        expected = counts.get(row["cell_id"])
        _require(expected is not None and all(row[k] == v for k, v in expected.items()),
                 "per-item accuracy disagrees with the card's action outcomes")
    for rows, low in ((card["aggregates"], -1000),
                      (card["sensitivity"]["minus_one_at_zero"], -1000),
                      (card["sensitivity"]["minus_one_at_minus_two"], -2000)):
        _ordered([(row["stage"], row["track"]) for row in rows], "stage/track rows")
        for row in rows:
            _score(row["score_milli"], low)
    _ordered([row["cell_id"] for row in card["per_item_accuracy"]], "per_item_accuracy")
    _ordered([row["track"] for row in card["diagnostics"]], "diagnostics")
    _ordered([(p["surface"], p["path"]) for p in card["volatile_surface_paths"]],
             "volatile_surface_paths")
    for row in card["per_item_accuracy"]:
        _ratio(row["correct"], row["eligible"], row["accuracy_milli"])
    coverage = card["coverage"]
    counts = [sum(b["failure_class"] == c for b in card["bundles"]) for c in NONRESULTS]
    _require([coverage[k] for k in ("blocked", "na_exposure", "na_clock")] == counts,
             "coverage exclusions mismatch")
    _require(coverage["assigned"] == len(card["bundles"])
             and coverage["scored"] == len(card["bundles"]) - sum(counts), "coverage counts mismatch")
    _ratio(coverage["scored"], coverage["assigned"], coverage["coverage_milli"])
    _require(max(card["carry_over_milli"], card["competing_milli"]) <= 1000,
             "system share exceeds 1000")
    for row in card["diagnostics"]:
        _require(max(row["competing_milli"], row["carry_over_milli"]) <= 1000,
                 "diagnostic share exceeds 1000")
    for key, value in card["controls"].items():
        if key != "wiped_store":
            if type(value) is str:
                _require(key == "naive_rag" and value == "not run in v0.1", "invalid control sentinel")
            else:
                _score(value)
    wiped = card["controls"]["wiped_store"]
    _require(wiped != "PASS" or card["gate_verdict"] == "INVALID", "wiped pass invalidates run")
    # RING0 §6: a first run with no baseline card is a labelled conformance PASS.
    if card["gate_verdict"] in ("PASS", "CONFORMANCE_PASS"):
        _require(wiped == "FAIL" and bool(items) and bool(bundle_ids)
                 and card["run_status"] == "COMPLETE", "ineligible Ring 0 PASS")


def _receipt(receipt):
    _require(receipt["wall_end_ms"] >= receipt["wall_start_ms"], "wall time reversed")
    _require(len(receipt["load_milli"]) == 3, "load requires 1-, 5-, 15-minute readings")
    _require(all(port <= 65535 for port in receipt["ports"]), "port exceeds 65535")


for _name, _check in (("item_outcome", _item), ("bundle_outcome", _bundle),
                      ("card_ring0", _card), ("receipt", _receipt)):
    register_check(_name, _check)
