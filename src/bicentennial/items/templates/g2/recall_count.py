"""Linear correction count and the preference before its last correction."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact

from .common import (
    G2Template,
    answer,
    assertions,
    entity,
    linking,
    name,
    preference,
    retractions,
    value,
)


@dataclass(frozen=True, kw_only=True, eq=False)
class RecallCount(G2Template):
    entity_kind: str = "trip"
    entity_key: str = "trip"
    attr_key: str = "date"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        e = entity(schedule, self.entity_kind, self.entity_key)
        facts = tuple(f for f, _ in assertions(db, e, self.attr_key, t, stated_only=True))
        retracted = {f for _, _, f in retractions(db, e, self.attr_key, t)}
        if len(facts) < 2 or retracted != set(facts[:-1]) or decisive_fact(
                db, e, self.attr_key, t, "as_known") != facts[-1]:
            raise ValueError(e)
        n = len(facts) - 1
        return (Instance(key=f"{self.entity_kind}-{self.entity_key}-{self.attr_key}", probe_point=k,
                         prompt=f"How many times did the {self.attr_key.replace('_', ' ')} of {name(db, e)} change?",
                         options=(answer("count", facts, "number", n), answer("under", facts[:-1], "number", n - 1),
                                  answer("unknown")), gold_spans=linking(db, facts, t), decisive_fact_id=facts[-1]),)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftAsOf(G2Template):
    pref_id: str = "seat-long"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        e, domain, ref = preference(db, schedule, self.pref_id, t)
        changes = retractions(db, e, "value", t)
        if not changes:
            raise ValueError(e)
        change, at, _ = changes[-1]
        b = decisive_fact(db, e, "value", at - 1, "as_known")
        c = decisive_fact(db, e, "value", t, "as_known")
        if b is None or c is None or b == c or not db.execute(
                "SELECT 1 FROM link WHERE event_id=? AND fact_id=? AND role='assert'", (change, c)).fetchone():
            raise ValueError(change)
        facts = tuple(r[0] for r in db.execute("SELECT id FROM fact WHERE subject_id=? AND predicate='value' "
                                             "ORDER BY id", (e,)))
        return (Instance(key=f"pref-{self.pref_id}", probe_point=k,
                         prompt=f"Before my last change, what was my {ref.replace('_', ' ')} {domain} preference?",
                         options=(answer("before", (b, c), "entity", value(db, b)),
                                  answer("current", (c,), "entity", value(db, c)), answer("unknown")),
                         gold_spans=linking(db, facts, at + 1), decisive_fact_id=b),)
