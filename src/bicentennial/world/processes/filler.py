"""Factless low-salience filler for every slot no other process occupied."""

from ..db import insert_event
from ..scale import TURNS
from . import LOW_SALIENCE, check_common, check_tokens, mint, slot


def write_filler(db, schedule, *, principal) -> int:
    """Run last in a life; makes no draw and links no fact."""
    check_common(db, schedule, [principal], (), ())
    occupied, count = {t for (t,) in db.execute("SELECT t_sim FROM event")}, 0
    for k in range(1, len(schedule.sessions) + 1):
        for n in range(1, TURNS + 1):
            if (t := slot(schedule, k, n)) not in occupied:
                insert_event(db, id=mint(schedule, "filler", "slots", "event", "event", (k - 1) * TURNS + n),
                             t_sim=t, kind="filler", channel="chat", actor_id=principal, audience_json=["agent"],
                             visibility="shared", salience=LOW_SALIENCE, payload_json={})
                count += 1
    check_tokens(db)
    return count
