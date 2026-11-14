"""drift-config-K4: four exact prompt texts; screening only."""

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
            Instance(key=i.key, probe_point=i.probe_point, prompt='Bring config/settings.toml up to date, applying firm corrections only, and only to settings entries (deadlines, rules and decisions stay out), keeping entry names exactly as written in chat. Where a settings entry was later firmly corrected, write what it was corrected to. Where a new figure was only raised as a possibility, or only reported or quoted, change nothing. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Update config/settings.toml so it reflects all firm corrections to settings entries and nothing else; deadlines, rules and decisions stay out, and entry names stay exactly as written in chat. If an entry had its figure firmly corrected later, set what it was corrected to; if a change was merely floated as a possibility, or merely reported or quoted, leave it alone. Never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Apply all firm corrections to config/settings.toml, settings entries only (deadlines, rules and decisions stay out), using entry names exactly as written in chat: whenever an entry was firmly corrected after its first figure, write what it was corrected to. Possibilities only raised, and figures only reported or quoted, change nothing; never add entries.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
            Instance(key=i.key, probe_point=i.probe_point, prompt='Make config/settings.toml match all firm corrections made in chat to settings entries (deadlines, rules and decisions stay out), under entry names exactly as written in chat: an entry firmly corrected after its first figure gets what it was corrected to. Anything only raised as a possibility, or only reported or quoted, changes nothing, and entries are never added.',
                     options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id, decision_table_ref=table),
        )[self.variant],)
