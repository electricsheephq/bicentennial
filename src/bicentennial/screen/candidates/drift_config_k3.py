"""drift-config-K3: four exact prompt texts; screening only."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.items.templates.g1.drift_action import DriftAction


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftActionV3(DriftAction):
    BINDING_FIELDS = ('chain_id',)
    variant: int = 0

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        table = i.decision_table_ref.removesuffix("-v1") + "-v3"
        return ((
            Instance(key=i.key, probe_point=i.probe_point, prompt='Check config/settings.toml. If an entry was firmly corrected after it was committed, set its corrected content; if new content was only raised as a possibility, or only quoted or reported, leave such an entry unchanged. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Review every entry in config/settings.toml. Where an entry was firmly corrected after being committed, write its corrected content. Where an entry only had new content floated as a possibility, or quoted or reported, keep it as it stands. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Look over config/settings.toml entry by entry: an entry firmly corrected since it was committed gets its corrected content; an entry whose new content was only raised as a possibility, or only quoted or reported, stays unchanged. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Apply to config/settings.toml only firm corrections made after an entry was committed, writing each corrected content; an entry whose new content was only raised as a possibility, or only quoted or reported, keeps its current content. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
