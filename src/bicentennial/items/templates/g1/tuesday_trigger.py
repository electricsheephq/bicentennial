"""Structure-only event tickets: write the promise and the cue answered."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.world.processes import mint

from .common import G1Template, action, fact, name, repo_state, step, value, visible


@dataclass(frozen=True, kw_only=True, eq=False)
class TuesdayTrigger(G1Template):
    commitment_id: str = "commitment-1"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)

        def m(table, part, n=0):
            return mint(schedule, "commitments", self.commitment_id, table, part, n)

        c, cue, trigger = m("fact", "made"), m("fact", "cue"), m("event", "trigger")
        row = db.execute("SELECT * FROM commitment WHERE fact_id=?", (c,)).fetchone()
        if (row is None or row["trigger_kind"] != "event" or row["window_close_t"] != t
                or not visible(db, trigger, t) or not visible(db, m("event", "made"), t)):
            raise ValueError(c)
        lures = []
        while db.execute("SELECT 1 FROM fact WHERE id=?", (f := m("fact", "lure", len(lures)),)).fetchone():
            lures.append(f)
        path = "docs/decisions.md"
        if not lures or any(name(db, fact(db, f)["subject_id"]) in repo_state(db, schedule, k)[path]
                            for f in (c, cue, *lures)):
            raise ValueError(c)
        cancel = m("event", "cancel")
        cancelled = visible(db, cancel, t)
        options = tuple(action("book" if j == 0 else f"lure-{j}", (c, f),
                               *(step(path, name(db, fact(db, fid)["subject_id"]), value(db, fid)) for fid in (c, f)))
                        for j, f in enumerate((cue, *lures)))
        refrain = action("refrain", (m("fact", "cancel"),) if cancelled else ())
        return (Instance(key=f"tue-{self.commitment_id}", probe_point=k,
                         prompt="The latest ticket updates are in. Take care of anything in the repository that is now due.",
                         options=(refrain, *options) if cancelled else (*options, refrain),
                         gold_spans=(m("event", "made"), trigger, *((cancel,) if cancelled else ())),
                         decisive_fact_id=c, duty=not cancelled, decision_table_ref=(
                             "tue-ticket-cancelled-v1" if cancelled else "tue-ticket-due-v1")),)
