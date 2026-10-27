"""Current preference and a later mention that leaves the preference unchanged."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact

from .common import (
    G2Template,
    action,
    assertions,
    linking,
    preference,
    retractions,
    slot_key,
    step,
    value,
)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftBooking(G2Template):
    pref_id: str = "seat-long"
    control: bool = False

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        e, domain, ref = preference(db, schedule, self.pref_id, t)
        d = decisive_fact(db, e, "value", t, "as_known")
        facts = assertions(db, e, "value", t)
        times = dict(facts)
        others = [f for f, _ in facts if f != d]
        later = [f for f in others if d in times and times[f] > times[d]]
        updates = retractions(db, e, "value", t)
        if d not in times or (self.control and (updates or not later)) or (not self.control and not updates):
            raise ValueError(e)
        key = f"pref-{self.pref_id}"
        slot = slot_key(schedule, self, key)
        options = [action("current", (d, later[0]) if self.control else (d,),
                          step("book", slot, {domain: value(db, d)}))]
        options.extend(action(f"other-{j}", (f,), step("book", slot, {domain: value(db, f)}))
                       for j, f in enumerate(others, 1))
        options.append(action("refrain"))
        value_facts = tuple(r[0] for r in db.execute(
            "SELECT id FROM fact WHERE subject_id=? AND predicate='value' ORDER BY id", (e,)))
        return (Instance(key=key, probe_point=k,
                         prompt=f"Book a {domain} for my next {ref.replace('_', ' ')} flight.",
                         options=tuple(options), gold_spans=linking(db, value_facts, t), decisive_fact_id=d,
                         decision_table_ref="drift-no-update-v1" if self.control else "drift-booking-v1"),)
