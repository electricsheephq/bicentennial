"""Passport event commitment, cancellation and other-parcel lures."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.world.processes import mint

from .common import G2Template, action, fact, slot_key, step, value, visible


@dataclass(frozen=True, kw_only=True, eq=False)
class TuesdayTrigger(G2Template):
    commitment_id: str = "passport"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)

        def m(table, part, n=0):
            return mint(schedule, "commitments", self.commitment_id, table, part, n)

        c, cue, trigger = m("fact", "made"), m("fact", "cue"), m("event", "trigger")
        row = db.execute("SELECT * FROM commitment WHERE fact_id=?", (c,)).fetchone()
        if row is None or row["trigger_kind"] != "event" or row["window_close_t"] != t:
            raise ValueError(c)
        fact(db, cue)
        if not visible(db, trigger, t) or not visible(db, m("event", "made"), t):
            raise ValueError(trigger)
        lures = []
        while db.execute("SELECT 1 FROM fact WHERE id=?", (f := m("fact", "lure", len(lures)),)).fetchone():
            lures.append(f)
        if not lures:
            raise ValueError(c)
        cancel = m("event", "cancel")
        cancelled = visible(db, cancel, t)
        key = f"commitment-{self.commitment_id}"
        slot = slot_key(schedule, self, key)
        options = tuple(action("book" if j == 0 else f"lure-{j}", (c, f),
                               step("book", slot, {"trip": value(db, c), "delivery": value(db, f)}))
                        for j, f in enumerate((cue, *lures)))
        refrain = action("refrain", (m("fact", "cancel"),) if cancelled else ())
        return (Instance(key=key, probe_point=k,
                         prompt="Here is today's check-in. Take care of anything that is now due.",
                         options=(refrain, *options) if cancelled else (*options, refrain),
                         gold_spans=(m("event", "made"), trigger, *((cancel,) if cancelled else ())),
                         decisive_fact_id=c, duty=not cancelled, decision_table_ref=(
                             "tue-passport-cancelled-v1" if cancelled else "tue-passport-due-v1")),)
