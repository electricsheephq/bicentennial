"""Validity round 2's config and quote finalists: each K3 card's variant-0 prompt (#534)."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance

from .drift_action import DriftAction, DriftQuote


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftActionV3(DriftAction):
    BINDING_FIELDS = ("chain_id",)

    @property
    def lever_mix(self):
        return dict(super().lever_mix, departure=(
            "validity round 2 (results/validity-2/PLAN.md §4): varies levers 1 and 4, no cue in the prompt and the "
            "decision rule restated in other words, instead of the cell's primary lever (chain_depth)"))

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt='Check config/settings.toml. If an entry was firmly corrected after it was committed, set its corrected content; if new content was only raised as a possibility, or only quoted or reported, leave such an entry unchanged. Never add entries.',
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref=i.decision_table_ref.removesuffix("-v1") + "-v3"),)


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftQuoteV3(DriftQuote):
    BINDING_FIELDS = ("chain_id",)

    @property
    def lever_mix(self):
        return dict(super().lever_mix, departure=(
            "validity round 2 (results/validity-2/PLAN.md §4): varies lever 1, no cue in the prompt, "
            "instead of the cell's primary lever (chain_depth)"))

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt='Write into config/settings.toml every settings entry decided firmly in chat (deadlines, rules and decisions stay out), named exactly as in chat, each at its latest figure stated directly, adding any entry this file lacks; any figure only reported or quoted later replaces nothing.',
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref=i.decision_table_ref.removesuffix("-v1") + "-v3"),)
