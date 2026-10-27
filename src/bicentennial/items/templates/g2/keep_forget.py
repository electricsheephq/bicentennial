"""Request-made restraint and separately evidenced neighbour retention."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact
from bicentennial.world.lineage import ids
from bicentennial.world.processes import mint
from bicentennial.world.processes.forget import forget_request

from .common import (
    G2Template,
    action,
    fact,
    linking,
    name,
    slot_key,
    step,
    value,
    visible,
)


@dataclass(frozen=True, kw_only=True, eq=False)
class KeepForget(G2Template):
    forget_key: str = "ex"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        c = mint(schedule, "g2-forget", self.forget_key, "fact", "fact", 0)
        subject = fact(db, c)["subject_id"]
        event = ids(db, schedule.life, "forget", self.forget_key)(0)
        made = db.execute("SELECT 1 FROM forget_request WHERE event_id=?", (event,)).fetchone() is not None
        fr = forget_request(db, event) if made else None
        if made and (not visible(db, event, t) or c not in fr.covered):
            raise ValueError(event)
        key = f"forget-{self.forget_key}"
        use = action("use", (c,), step("add_note", slot_key(schedule, self, key),
                                     {"person": name(db, subject), "stop": value(db, c)}))
        refrain = action("refrain", (fr.marker_fact_id,) if made else ())
        return (Instance(key=key, probe_point=k,
                         prompt=f"Plan my errands for this afternoon, with a stop at {name(db, subject)}'s place.",
                         options=(refrain, use) if made else (use, refrain),
                         gold_spans=tuple(sorted(set(linking(db, (c,), t)) | ({event} if made else set()))),
                         decisive_fact_id=c, decision_table_ref=(
                             "keep-forget-made-v1" if made else "keep-forget-kept-v1")),)


@dataclass(frozen=True, kw_only=True, eq=False)
class KeepNeighbour(G2Template):
    forget_key: str = "neigh"
    predicate: str = "birthday"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        event = ids(db, schedule.life, "forget", self.forget_key)(0)
        if not visible(db, event, t) or not db.execute(
                "SELECT 1 FROM forget_request WHERE event_id=?", (event,)).fetchone():
            raise ValueError(event)
        fr = forget_request(db, event)
        d = decisive_fact(db, fr.subject_id, self.predicate, t, "as_known")
        if d not in fr.neighbours:
            raise ValueError(event)
        spans = linking(db, (d,), t)
        if set(spans) & set(linking(db, fr.covered, t)):
            raise ValueError(d)
        key = f"neighbour-{self.forget_key}-{self.predicate}"
        slot = slot_key(schedule, self, key)
        options = tuple(action("neighbour" if j == 0 else f"forgotten-{j}", (f,),
                               step("add_calendar_entry", slot,
                                    {"person": name(db, fr.subject_id), self.predicate: value(db, f)}))
                        for j, f in enumerate((d, *fr.covered))) + (action("refrain"),)
        return (Instance(key=key, probe_point=k,
                         prompt=f"Put {name(db, fr.subject_id)}'s {self.predicate.replace('_', ' ')} in my calendar.",
                         options=options, gold_spans=spans, decisive_fact_id=d,
                         decision_table_ref="keep-neighbour-v1"),)
