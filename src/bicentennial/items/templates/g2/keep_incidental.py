"""An incidental entry detail among look-alike decoys."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact
from bicentennial.world.processes import mint
from bicentennial.world.scale import DECOY_MIN_RATIO

from .common import G2Template, action, fact, linking, name, slot_key, step, value


@dataclass(frozen=True, kw_only=True, eq=False)
class KeepIncidental(G2Template):
    detail_id: str = "gate"

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        facts = []
        while db.execute("SELECT 1 FROM fact WHERE id=?", (f := mint(
                schedule, "incidental", self.detail_id, "fact", "detail", len(facts)),)).fetchone():
            facts.append(f)
        if len(facts) < DECOY_MIN_RATIO + 1:
            raise ValueError(self.detail_id)
        d = fact(db, facts[0])
        s, p = d["subject_id"], d["predicate"]
        if decisive_fact(db, s, p, t, "as_known") != facts[0]:
            raise ValueError(facts[0])
        key = f"detail-{self.detail_id}"
        slot = slot_key(schedule, self, key)
        options = tuple(action("code" if j == 0 else f"decoy-{j}", (f,),
                               step("send_mail", slot, {"place": name(db, s), p: value(db, f)}))
                        for j, f in enumerate(facts)) + (action("refrain"),)
        return (Instance(key=key, probe_point=k,
                         prompt=f"A delivery is coming to {name(db, s)}; send the courier the entry details.",
                         options=options, gold_spans=linking(db, (facts[0],), t), decisive_fact_id=facts[0],
                         decision_table_ref="keep-incidental-v1"),)
