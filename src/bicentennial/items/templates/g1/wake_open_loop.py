"""An unsurfaced repository decision surviving an in-life cold start."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance

from .common import PATHS, action, fact, kind, name, position, repo_state, step, value
from .recall_value import RecallValue


@dataclass(frozen=True, kw_only=True, eq=False)
class WakeLoop(RecallValue):
    statement_id: str = "decision-1"

    def instances(self, db, schedule):
        base, = super().instances(db, schedule)
        f, k = base.decisive_fact_id, base.probe_point
        s = fact(db, f)["subject_id"]
        path = PATHS.get(kind(db, s))
        asserts = db.execute("SELECT e.t_sim FROM event e JOIN link l ON l.event_id=e.id "
                             "WHERE l.fact_id=? AND l.role='assert' ORDER BY e.t_sim, e.id", (f,)).fetchall()
        if (path is None or name(db, s) in repo_state(db, schedule, k)[path]
                or not asserts or any(position(schedule, r[0])[0] >= k for r in asserts)):
            raise ValueError(f)
        return (Instance(key=f"loop-{self.statement_id}", probe_point=k,
                         prompt="Pick up where we left off in the repository.", duty=True,
                         options=(action("loop", (f,), step(path, name(db, s), value(db, f))), action("refrain")),
                         gold_spans=base.gold_spans, decisive_fact_id=f, decision_table_ref="wake-loop-v1"),)
