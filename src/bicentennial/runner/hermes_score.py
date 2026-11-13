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
UNREADABLE = object()


def unreadable_counts(runs, keep=None):
    """Count, per arm, the items scored as unreadable_state: labelled items in the scored attempt of each unit that
    reach the scorer's act path, as runner/units.py _score_run and score_item route them: no cause class, an OK audit
    (a failed audit makes every unclassed item INFRA_FAILURE) and a reader result (a missing one is Infra). With keep
    (T2-lite --only), only the kept items, which are the ones published. A unit's runs are contiguous and number their
    attempts from 0, so a run is scored when the next run of its arm, life and branch starts another unit (attempt 0,
    as in a T2-lite repetition) or there is none. An attempt voided by a harness fault is not counted. An arm with no
    run here (a fully cached floor) has no key."""
    runs = list(runs)
    counts = {arm: 0 for arm in sorted({run.arm for run in runs})}
    for n, run in enumerate(runs):
        key = (run.arm, run.life, run.branch)
        later = next((r for r in runs[n + 1:] if (r.arm, r.life, r.branch) == key), None)
        if (later is None or later.attempt == 0) and run.audit.get("status") == "OK":
            counts[run.arm] += sum(label == "unreadable_state" and not run.classes.get(iid, (None, None))[0]
                                   and iid in run.results and (keep is None or iid in keep)
                                   for iid, label in run.item_labels.items())
    return counts


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
            if act is UNREADABLE:
                predicates = {name: False for name in case.checks}
                trace = Trace(False, True, case.t_sim)
            elif case.seed is None:
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
