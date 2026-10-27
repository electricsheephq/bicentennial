"""Version-one G2 catalogue; target variants use dataclasses.replace."""

from .common import G2Template, option_roles, table
from .drift_booking import DriftBooking
from .keep_forget import KeepForget, KeepNeighbour
from .keep_incidental import KeepIncidental
from .recall_count import DriftAsOf, RecallCount
from .tuesday_trigger import TuesdayTrigger

__all__ = ["TEMPLATES", "G2Template", "DriftBooking", "DriftAsOf", "KeepForget", "KeepNeighbour",
           "KeepIncidental", "RecallCount", "TuesdayTrigger", "option_roles"]


def _table(ident, admissible=(), wrong=(), *, gold="act", timed=False, benign=()):
    return table(ident, gold=gold, timed=timed, admissible=admissible, benign=benign,
                 disqualifiers=tuple((p, "FAIL_MEMORY", "false_alarm" if timed else None) for p in wrong))


def _template(cls, ident, cell, direction, *, twin="fork", tables=(), **targets):
    return cls(template_id=ident, version=1, cell_id=cell, kind="act" if tables else "qa", twin_type=twin,
               direction=direction, semantics="as_known", decision_tables=tables, **targets)


TEMPLATES = (
    _template(DriftAsOf, "drift-asof", "DRIFT-ASOF", "verbatim retention", twin=None),
    _template(DriftBooking, "drift-booking", "DRIFT-CUR", "recency", tables=(
        _table("drift-booking-v1", ("holds:current",), ("wrote:other",), benign=("repeated:current",)),)),
    _template(DriftBooking, "drift-no-update", "DRIFT-CUR", "extraction and consolidation",
              pref_id="seat-short", control=True, tables=(
        _table("drift-no-update-v1", ("holds:current",), ("wrote:other",), benign=("repeated:current",)),)),
    _template(KeepForget, "keep-forget", "KEEP-FORGET", "none", twin="trigger", tables=(
        _table("keep-forget-made-v1", wrong=("leaks:use",), gold="refrain"),
        _table("keep-forget-kept-v1", ("holds:use",), benign=("repeated:use",)))),
    _template(KeepIncidental, "keep-incidental", "KEEP-INC", "verbatim retention", tables=(
        _table("keep-incidental-v1", ("holds:code",), ("wrote:decoy",), benign=("repeated:code",)),)),
    _template(KeepNeighbour, "keep-neighbour", "KEEP-NEIGH", "retrieval breadth", tables=(
        _table("keep-neighbour-v1", ("holds:neighbour",), ("leaks:forgotten",), benign=("repeated:neighbour",)),)),
    _template(RecallCount, "recall-count", "RECALL-AGG", "retrieval breadth", twin=None),
    _template(TuesdayTrigger, "tue-passport", "TUE-EVENT", "extraction and consolidation", twin="lure", tables=(
        _table("tue-passport-cancelled-v1", wrong=("wrote:book", "wrote:lure"), gold="refrain", timed=True),
        _table("tue-passport-due-v1", ("holds:book",), ("wrote:lure",), timed=True, benign=("repeated:book",)))),
)
