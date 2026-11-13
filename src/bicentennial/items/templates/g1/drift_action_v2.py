"""Version two of the config correction and quote templates: prompts that do not presuppose a change (#506)."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance

from .common import PATHS, fact, name
from .drift_action import DriftAction, DriftQuote


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftActionV2(DriftAction):
    # v1's entry in items/bindings.py BINDING_FIELDS; that map is keyed by class path.
    BINDING_FIELDS = ("chain_id",)

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        n, path = name(db, fact(db, i.decisive_fact_id)["subject_id"]), PATHS["constant"]
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt=f"Check {n} in {path}. If a firm correction replaced its value, set the new value; "
                                "if a new value was only raised as a possibility, leave the file unchanged.",
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref=(
                             "drift-config-corrected-v2" if i.decision_table_ref == "drift-config-corrected-v1"
                             else "drift-config-hedged-v2")),)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftQuoteV2(DriftQuote):
    BINDING_FIELDS = ("chain_id",)

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        n, path = name(db, fact(db, i.decisive_fact_id)["subject_id"]), PATHS["constant"]
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt=f"Add the {n} setting to {path}. Use the value that was set for it directly; "
                                "a value that was only reported or quoted later does not replace it.",
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref="drift-quote-v2"),)
