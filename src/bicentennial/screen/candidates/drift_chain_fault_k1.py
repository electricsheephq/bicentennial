"""drift-chain-fault-K1: four exact prompt texts; screening only."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.items.templates.g1.drift_chain import DriftChain


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftChainV3(DriftChain):
    BINDING_FIELDS = ('chain_id', 'depth')
    variant: int = 0

    def __post_init__(self):
        super().__post_init__()
        if self.fault is not True:
            raise ValueError(self.chain_id)

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        table = i.decision_table_ref.removesuffix("-v1") + "-v3"
        return ((
            Instance(key=i.key, probe_point=i.probe_point, prompt='Record the current target of the milestone after the beta in docs/decisions.md, as one line of the form "- <name>: <value>", where <name> is the milestone name exactly as written in our conversation.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='In docs/decisions.md, write one line "- <name>: <value>" giving the latest agreed target of the milestone after the beta, with <name> exactly as our conversation names the milestone.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Add an entry to docs/decisions.md recording the current target of the milestone following the beta, as one line "- <name>: <value>" using the milestone name exactly as written in our conversation.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Put in docs/decisions.md the current target of the milestone after the beta: one line "- <name>: <value>", with <name> being the milestone name exactly as written in our conversation.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
