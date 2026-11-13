"""Version two of the fault-crossing deadline chain: the prompt names the exact entry the check reads (#505)."""

from dataclasses import dataclass

from bicentennial.items.protocol import Instance

from .common import fact, name
from .drift_chain import DriftChain


@dataclass(frozen=True, kw_only=True, eq=False)
class DriftChainV2(DriftChain):
    # v1's entry in items/bindings.py BINDING_FIELDS; that map is keyed by class path.
    BINDING_FIELDS = ("chain_id", "depth")

    def __post_init__(self):
        super().__post_init__()
        if self.fault is not True:
            raise ValueError(self.chain_id)

    def instances(self, db, schedule):
        i, = super().instances(db, schedule)
        current = fact(db, i.decisive_fact_id)
        n, p = name(db, current["subject_id"]), current["predicate"].replace("_", " ")
        return (Instance(key=i.key, probe_point=i.probe_point,
                         prompt=f'Record the {n} {p} in {self.path}, as one line of the form "- {n}: <{p}>" '
                                f'(the entry name is exactly "{n}").',
                         options=i.options, gold_spans=i.gold_spans, decisive_fact_id=i.decisive_fact_id,
                         decision_table_ref="drift-chain-fault-v2"),)
