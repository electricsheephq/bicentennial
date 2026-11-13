"""Version two of the correction count: the prompt makes a one-line citation enough (#506)."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance
from bicentennial.items.templates.g2.common import entity, name
from bicentennial.items.templates.g2.recall_count import RecallCount


@dataclass(frozen=True, kw_only=True, eq=False)
class RecallCountV2(RecallCount):
    # v1's entry in items/bindings.py BINDING_FIELDS; that map is keyed by class path.
    BINDING_FIELDS = ("entity_kind", "entity_key", "attr_key")

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        a, n = self.attr_key.replace("_", " "), name(db, entity(schedule, self.entity_kind, self.entity_key))
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt=f"How many times did the {a} of {n} change? For the citation, quote a single line "
                                "from just one of the messages that stated it; never join lines or messages.",
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id),)
