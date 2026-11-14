"""drift-chain-fault-K3: four exact prompt texts; screening only."""

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
            Instance(key=i.key, probe_point=i.probe_point, prompt='Record every milestone in docs/decisions.md as one line, "- <name>: <target>", where <name> matches how each milestone was named in chat, in lower case and with nothing added, and <target> gives its current target code after all corrections.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Write one line per milestone into docs/decisions.md in this form: "- <name>: <target>". Use each milestone name just as written in chat, lower case, nothing added; use its current target code once all corrections apply.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='In docs/decisions.md, add a line "- <name>: <target>" per milestone: <name> copied exactly as chat named this milestone, lower case and alone; <target> its latest firm target code after corrections.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='List each milestone in docs/decisions.md, one line apiece shaped "- <name>: <target>", taking <name> verbatim as named in chat (lower case, nothing extra) and <target> as its current target code once all corrections apply.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
