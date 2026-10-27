"""Linear deadline corrections, including the fault-crossing diagnostic."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact

from .common import (
    PATHS,
    G1Template,
    action,
    chain_facts,
    kill_points,
    linking,
    mentions,
    name,
    position,
    repo_state,
    step,
    surfaced,
    value,
)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftChain(G1Template):
    chain_id: str = "deadline-0"
    depth: int = 1
    path: str = "docs/decisions.md"
    fault: bool = False

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        if type(self.depth) is not int or not 1 <= self.depth <= 6:
            raise ValueError(self.chain_id)
        ids, s, p = chain_facts(db, schedule, self.chain_id, self.depth, t)
        if (set(mentions(db, s, p, t, "retract")) != set(ids[:-1])
                or decisive_fact(db, s, p, t, "as_known") != ids[-1]
                or any(surfaced(db, f, t) for f in ids) or self.path not in PATHS.values()
                or name(db, s) in repo_state(db, schedule, k)[self.path]):
            raise ValueError(self.chain_id)
        spans = linking(db, ids, t)
        positions = [position(schedule, db.execute("SELECT t_sim FROM event WHERE id=?", (e,)).fetchone()[0])
                     for e in spans]
        kills = [(s, n) for _, s, n in kill_points(schedule, k)]
        if (self.fault and not any(all(p <= kill for p in positions) for kill in kills)
                or not self.fault and any(p <= kill for p in positions for kill in kills)):
            raise ValueError(self.chain_id)
        options = tuple(action(key, (f,), step(self.path, name(db, s), value(db, f)))
                        for key, f in [("current", ids[-1]), *[(f"other-{j + 1}", f) for j, f in enumerate(ids[:-1])]])
        return (Instance(key=f"chain-{self.chain_id}", probe_point=k,
                         prompt=f"Record the {name(db, s)} {p.replace('_', ' ')} in {self.path}.",
                         options=(*options, action("refrain")), gold_spans=spans, decisive_fact_id=ids[-1],
                         decision_table_ref="drift-chain-fault-v1" if self.fault else "drift-chain-v1"),)
