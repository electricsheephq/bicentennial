"""Cause-first item outcomes (PREREG §7; ERRATA E10)."""

from dataclasses import asdict

from bicentennial.contracts.run import validate
from bicentennial.score.action import ActionResult, Trace, score_action
from bicentennial.score.qa import QAResult

IDENTITY = {"item_id", "cell_id", "stage", "track", "selected_option",
            "competing_present", "carry_over", "stage_attribution"}


class RerunRequired(Exception):
    """Benchmark infrastructure failed before exhausting its two reruns."""


def outcome(identity, result, *, cause=None, infra_reruns=0) -> dict:
    """Project a scorer result or runner-attributed cause into the K14 contract."""
    if not isinstance(identity, dict) or identity.keys() != IDENTITY:
        raise ValueError("outcome: exact identity keys required")
    if type(infra_reruns) is not int or not 0 <= infra_reruns <= 2:
        raise ValueError("outcome: infra_reruns must be an integer from 0 to 2")
    if identity["stage"] not in ("act", "remember", "survive"):
        raise ValueError("outcome: invalid stage")
    value = dict(identity, infra_reruns=infra_reruns, base_verdict=None, benign_extra=False,
                 accuracy_correct=None, tuesday_class=None, envelope=None,
                 score_milli=None, worst_case_milli=None, failure_class=None)
    if cause is None:
        action = isinstance(result, ActionResult)
        if not (action or isinstance(result, QAResult)) or action != (identity["stage"] == "act"):
            raise ValueError("outcome: result type must match stage")
        if action:
            value.update(asdict(result), worst_case_milli=result.score_milli)
        else:
            value.update((key, getattr(result, key)) for key in
                         ("envelope", "score_milli", "failure_class"))
            value["worst_case_milli"] = (-1000 if value["failure_class"] == "SYSTEM_FAILURE"
                                         else value["score_milli"])
    else:
        if result is not None or cause not in ("SYSTEM_FAILURE", "INFRA_FAILURE",
                                               "N/A_EXPOSURE", "N/A_CLOCK"):
            raise ValueError("outcome: invalid cause or result supplied with cause")
        if cause == "INFRA_FAILURE":
            if infra_reruns < 2:
                raise RerunRequired("benchmark infrastructure failure: rerun required")
            cause = "BLOCKED"
        value["failure_class"] = cause
        if cause == "SYSTEM_FAILURE":
            value.update(score_milli=0, worst_case_milli=-1000,
                         accuracy_correct=False if identity["stage"] == "act" else None)
    validate("item_outcome", value)
    return value


def score_act(item, table, trace, predicates, *, commitment=None) -> ActionResult:
    """Adapt R11a's trace tuple and G01's commitment row to S01."""
    if type(trace) is not tuple or len(trace) != 3:
        raise ValueError("score_act: a three-element trace tuple required")
    window = ((commitment["window_open_t"], commitment["window_close_t"])
              if hasattr(commitment, "keys") else None)  # a dict or G01's sqlite3.Row
    return score_action(item, table, Trace(*trace), predicates, window=window)
