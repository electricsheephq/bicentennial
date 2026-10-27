"""Cause-first scoring of Hermes evidence, shared by the tier runners."""

import json
from dataclasses import dataclass

from bicentennial.canon import canon
from bicentennial.controls.cache import ControlsTampered
from bicentennial.items.checks.env import env_predicates, item_trace
from bicentennial.items.checks.repo import repo_state_predicates
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.probe.scripted_reader import failing_stage
from bicentennial.runner.lock import LockMismatch
from bicentennial.sandbox.envserver.state import State
from bicentennial.score.action import Trace, score_action
from bicentennial.score.classes import outcome
from bicentennial.score.qa import score_qa
from bicentennial.systems.registry import SystemRefused

MISSING = object()


@dataclass(frozen=True)
class Infra:
    label: str


def identity0(item):
    """Identity for an item with no usable reader evidence."""
    return dict(sorted(dict(
        **{k: item[k] for k in ("item_id", "cell_id", "stage", "track")},
        selected_option=None, competing_present=[], carry_over=False,
        stage_attribution=None).items()))


def score_item(item, *, cls, label, result, envelope, act, case, scoring_evidence,
               keys, stored_roots, retained_roots, attempt):
    """Score executed evidence; infrastructure returns a value for unit reruns."""
    identity = identity0(item)
    if cls == "SYSTEM_FAILURE":
        return json.loads(canon(outcome(identity, None, cause=cls, infra_reruns=attempt)))
    if cls == "INFRA_FAILURE":
        return Infra(label)
    if result is MISSING:
        return Infra("no_result")
    if item["stage"] != "act":
        if envelope is MISSING:
            return Infra("no_final")
        scored = score_qa(item, envelope, evidence_texts=scoring_evidence)
    else:
        if act is MISSING:
            return Infra("no_act")
        try:
            if case.seed is None:
                predicates = repo_state_predicates(act, case.checks)
                changed = canon(act) != canon(case.state0)
                trace = Trace(False, changed, case.t_sim if changed else None)
            else:
                rows = act["records"]
                state = State(case.seed)
                for row in rows:
                    if row["type"] == "action" and row["ok"] is True and row["state_changed"]:
                        state.call(row["tool"], row["args"])
                predicates = env_predicates(case.table, case.item, case.roles,
                    seed_state=case.seed["state"], end_state=state.state, rows=rows)
                trace = item_trace(rows, case.item)
            scored = score_action(case.item, case.table, trace, predicates, window=case.window)
        except (ControlsTampered, PinnedArtifactChanged, LockMismatch, SystemRefused):
            raise
        except (ValueError, TypeError):
            return Infra("act_state")
    identity.update(selected_option=result.selected_option,
        competing_present=list(result.competing_present), carry_over=result.carry_over,
        stage_attribution=failing_stage(result, keys, failed=scored.score_milli != 1000,
            stored_roots=stored_roots, retained_roots=retained_roots))
    return json.loads(canon(outcome(identity, scored, infra_reruns=attempt)))
