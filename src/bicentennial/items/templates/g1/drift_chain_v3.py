"""Validity round 2's fault-chain finalist: the K3 card's variant-0 prompt (#534)."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance

from .drift_chain import DriftChain


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftChainV3(DriftChain):
    BINDING_FIELDS = ("chain_id", "depth")

    def __post_init__(self):
        super().__post_init__()
        if self.fault is not True:
            raise ValueError(self.chain_id)

    @property
    def lever_mix(self):
        return dict(super().lever_mix, departure=(
            "validity round 2 (results/validity-2/PLAN.md §4): varies lever 1, no cue in the prompt, "
            "instead of the cell's primary lever (chain_depth)"))

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt='Record every milestone in docs/decisions.md as one line, "- <name>: <target>", where <name> matches how each milestone was named in chat, in lower case and with nothing added, and <target> gives its current target code after all corrections.',
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref=i.decision_table_ref.removesuffix("-v1") + "-v3"),)
