"""Chat-only value recall with a span citation."""

from dataclasses import dataclass

from bicentennial.genres.g1_software.codebase_model import PROCESS
from bicentennial.items.protocol import Instance, Option, decisive_fact
from bicentennial.world.processes import mint

from .common import G1Template, fact, linking, mentions, name, surfaced, value


@dataclass(frozen=True, kw_only=True, eq=False)
class RecallValue(G1Template):
    statement_id: str = "decision-0"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        f = mint(schedule, PROCESS, self.statement_id, "fact", "value", 0)
        row = fact(db, f)
        s, p = row["subject_id"], row["predicate"]
        if (f not in mentions(db, s, p, t) or mentions(db, s, p, t, "retract") or surfaced(db, f, t)
                or decisive_fact(db, s, p, t, "as_known") != f):
            raise ValueError(f)
        return (Instance(key=f"recall-{self.statement_id}", probe_point=k,
                         prompt=f"What {p.replace('_', ' ')} was set for the {name(db, s)}? Cite where it was said.",
                         options=(Option(key="value", token_fact_ids=(f,),
                                         envelope={"type": "span", "value": value(db, f)}),
                                  Option(key="unknown", token_fact_ids=(), envelope={"type": "unknown", "value": None})),
                         gold_spans=linking(db, (f,), t), decisive_fact_id=f),)
