"""drift-config-K1: four exact prompt texts; screening only."""

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
            Instance(key=i.key, probe_point=i.probe_point, prompt='Check the retry entry in config/settings.toml against what the team decided. If the team later firmly corrected its figure, set the corrected figure under the same entry name; if a new figure was only floated as a possibility, leave the file unchanged.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Look at the retry entry of config/settings.toml and check it against what was agreed. When its figure was later firmly replaced, write the replacement under the same entry name; when a new figure was merely suggested as a possibility, leave the file alone.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Bring the retry entry of config/settings.toml up to date against what the team settled: if the team firmly corrected its figure later, apply the corrected figure under the same entry name; if a new figure was only tentatively floated, keep the file unchanged.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Review the retry entry in config/settings.toml against what the team decided. Where the team later firmly corrected its figure, put the corrected figure under the same entry name; where a new figure was only tentatively suggested, leave the file unchanged.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
