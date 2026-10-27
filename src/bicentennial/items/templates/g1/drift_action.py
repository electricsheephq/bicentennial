"""Config corrections versus hedges, and a quoted no-update control."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance, decisive_fact

from .common import (
    PATHS,
    G1Template,
    action,
    chain_facts,
    fact,
    kind,
    linking,
    mentions,
    name,
    repo_state,
    step,
    surfaced,
    value,
    visible,
)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftAction(G1Template):
    chain_id: str = "setting-fix"

    @property
    def depth(self):
        return 1

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        (p, h), s, predicate = chain_facts(db, schedule, self.chain_id, 1, t)
        path = PATHS["constant"]
        links = db.execute("SELECT event_id, role FROM link WHERE fact_id=?", (h,)).fetchall()
        if (kind(db, s) != "constant" or not surfaced(db, p, t)
                or repo_state(db, schedule, k)[path].get(name(db, s)) != value(db, p)
                or db.execute("SELECT 1 FROM fact_surface WHERE fact_id=?", (h,)).fetchone()
                or len(links) != 1 or links[0]["role"] != "assert" or not visible(db, links[0][0], t)):
            raise ValueError(h)
        corrected = fact(db, h)["speech_act"] == "assert"
        retracts = mentions(db, s, predicate, t, "retract")
        if (corrected and (retracts != (p,) or not db.execute(
                "SELECT 1 FROM link WHERE event_id=? AND fact_id=? AND role='retract'", (links[0][0], p)).fetchone())
                or not corrected and (fact(db, h)["speech_act"] != "hedge" or retracts or db.execute(
                    "SELECT 1 FROM link WHERE fact_id=? AND role='retract'", (p,)).fetchone())
                or decisive_fact(db, s, predicate, t, "as_known") != (h if corrected else p)):
            raise ValueError(h)
        update = action("update", (h,), step(path, name(db, s), value(db, h)))
        keep = action("keep", () if corrected else (h,))
        return (Instance(key=f"config-{self.chain_id}", probe_point=k,
                         prompt=f"Bring {name(db, s)} in {path} up to date.",
                         options=(update, keep) if corrected else (keep, update), gold_spans=linking(db, (p, h), t),
                         decisive_fact_id=h, decision_table_ref=(
                             "drift-config-corrected-v1" if corrected else "drift-config-hedged-v1")),)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftQuote(G1Template):
    chain_id: str = "setting-quote"

    @property
    def depth(self):
        return 0

    def instances(self, db, schedule):
        k, t = self.probe(schedule)
        (d, q), s, p = chain_facts(db, schedule, self.chain_id, 1, t)
        path = PATHS["constant"]
        if (kind(db, s) != "constant" or fact(db, q)["speech_act"] != "quote"
                or mentions(db, s, p, t, "retract") or decisive_fact(db, s, p, t, "as_known") != d
                or any(surfaced(db, f, t) for f in (d, q)) or name(db, s) in repo_state(db, schedule, k)[path]):
            raise ValueError(q)
        return (Instance(key=f"quote-{self.chain_id}", probe_point=k,
                         prompt=f"Add the {name(db, s)} setting to {path}.",
                         options=(action("current", (d, q), step(path, name(db, s), value(db, d))),
                                  action("other-1", (q,), step(path, name(db, s), value(db, q))), action("refrain")),
                         gold_spans=linking(db, (d, q), t), decisive_fact_id=d, decision_table_ref="drift-quote-v1"),)
