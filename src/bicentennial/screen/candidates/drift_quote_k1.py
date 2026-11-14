"""drift-quote-K1: four exact prompt texts; screening only."""

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
            Instance(key=i.key, probe_point=i.probe_point, prompt='Add the missing timeout entry to the settings file config/settings.toml, under its name exactly as written in our conversation. Use the figure set directly, not one only reported or quoted later.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='In the settings file config/settings.toml, add the timeout entry still missing, named exactly as in our conversation. Take the figure set directly; figures only reported or quoted later do not replace the directly set figure.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Work out which timeout entry the settings file config/settings.toml still lacks, and add the entry under its exact name in our conversation, using the figure set directly rather than any figure reported or quoted later.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Complete the settings file config/settings.toml by adding its missing timeout entry, named exactly as in our conversation; use the directly set figure, and ignore any figure only reported or quoted later.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
