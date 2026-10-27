"""Version-one G1 catalogue; target variants use dataclasses.replace."""

from .common import G1Template, option_roles, repo_checks, table
from .drift_action import DriftAction, DriftQuote
from .drift_chain import DriftChain
from .recall_value import RecallValue
from .tuesday_trigger import TuesdayTrigger
from .wake_open_loop import WakeLoop

__all__ = ["TEMPLATES", "G1_MUTANT_ROLES", "G1Template", "DriftAction", "DriftQuote", "DriftChain",
           "RecallValue", "TuesdayTrigger", "WakeLoop", "option_roles", "repo_checks"]


def _table(ident, admissible=(), wrong=(), *, gold="act", timed=False):
    return table(ident, gold=gold, timed=timed, admissible=admissible,
                 disqualifiers=tuple((p, "FAIL_MEMORY", "false_alarm" if timed else None) for p in wrong))


def _template(cls, ident, cell, direction, *, twin="fork", tables=(), **targets):
    return cls(template_id=ident, version=1, cell_id=cell, kind="act" if tables else "qa", twin_type=twin,
               direction=direction, semantics="as_known", decision_tables=tables, **targets)


TEMPLATES = (
    _template(DriftChain, "drift-chain", "DRIFT-CUR", "recency", tables=(
        _table("drift-chain-v1", ("holds:current",), ("changed:other",)),)),
    _template(DriftChain, "drift-chain-fault", "DRIFT-CUR", "verbatim retention", chain_id="deadline-1", fault=True,
              tables=(_table("drift-chain-fault-v1", ("holds:current",), ("changed:other",)),)),
    _template(DriftAction, "drift-config", "DRIFT-CUR", "extraction and consolidation", twin="trigger", tables=(
        _table("drift-config-corrected-v1", ("holds:update",)),
        _table("drift-config-hedged-v1", wrong=("changed:update",), gold="refrain"))),
    _template(DriftQuote, "drift-quote", "DRIFT-CUR", "verbatim retention", tables=(
        _table("drift-quote-v1", ("holds:current",), ("changed:other",)),)),
    _template(RecallValue, "recall-value", "RECALL-VERB", "verbatim retention", twin=None),
    _template(TuesdayTrigger, "tue-ticket", "TUE-EVENT", "retrieval breadth", twin="lure", tables=(
        _table("tue-ticket-cancelled-v1", wrong=("changed:book", "changed:lure"), gold="refrain", timed=True),
        _table("tue-ticket-due-v1", ("holds:book",), ("changed:lure",), timed=True))),
    _template(WakeLoop, "wake-loop", "WAKE-LOOP", "extraction and consolidation", tables=(
        _table("wake-loop-v1", ("holds:loop",)),)),
)
G1_MUTANT_ROLES = {t["table_id"]: {"stale": tuple(r for r in ("other", "update", "book")
                                               if f"changed:{r}" in [d["predicate"] for d in t["disqualifiers"]]),
                                  "planted": ("lure",) if any(d["predicate"] == "changed:lure"
                                                            for d in t["disqualifiers"]) else ()}
                   for template in TEMPLATES for t in template.decision_tables}
