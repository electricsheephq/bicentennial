"""drift-quote-K3: four exact prompt texts; screening only."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.items.templates.g1.drift_action import DriftQuote


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftQuoteV3(DriftQuote):
    BINDING_FIELDS = ('chain_id',)
    variant: int = 0

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        table = i.decision_table_ref.removesuffix("-v1") + "-v3"
        return ((
            Instance(key=i.key, probe_point=i.probe_point, prompt='Write into config/settings.toml every settings entry decided firmly in chat (deadlines, rules and decisions stay out), named exactly as in chat, each at its latest figure stated directly, adding any entry this file lacks; any figure only reported or quoted later replaces nothing.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Put every settings entry firmly decided in chat into config/settings.toml (deadlines, rules and decisions stay out), under its name exactly as written in chat and at its latest directly stated figure, adding any entry missing there; later reports or quotes of another figure change nothing.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='config/settings.toml should hold every settings entry decided firmly in chat, deadlines, rules and decisions aside. Write each one under its exact chat name at its latest figure given directly, adding whatever entry this file lacks; any figure merely reported or quoted afterwards replaces nothing.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Record in config/settings.toml all settings entries decided firmly in chat (never deadlines, rules or decisions), each named exactly as in chat and at its latest figure someone stated directly, including any entry still missing; figures only reported or quoted later replace nothing.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
