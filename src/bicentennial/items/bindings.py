"""Read-only compilation of fixture-bound copies of registry templates."""

from dataclasses import dataclass, replace
from hashlib import sha256

from bicentennial.world import world_hash

from .compile import Branch, _entry

BINDING_FIELDS = {
    "bicentennial.items.templates.g1.drift_chain.DriftChain": ("chain_id", "depth"),
    "bicentennial.items.templates.g1.drift_action.DriftAction": ("chain_id",),
    "bicentennial.items.templates.g1.drift_action.DriftQuote": ("chain_id",),
    "bicentennial.items.templates.g1.recall_value.RecallValue": ("statement_id",),
    "bicentennial.items.templates.g1.wake_open_loop.WakeLoop": ("statement_id",),
    "bicentennial.items.templates.g1.tuesday_trigger.TuesdayTrigger": ("commitment_id",),
    "bicentennial.items.templates.g2.drift_booking.DriftBooking": ("pref_id",),
    "bicentennial.items.templates.g2.recall_count.DriftAsOf": ("pref_id",),
    "bicentennial.items.templates.g2.recall_count.RecallCount": (
        "entity_kind", "entity_key", "attr_key"),
    "bicentennial.items.templates.g2.keep_forget.KeepForget": ("forget_key",),
    "bicentennial.items.templates.g2.keep_forget.KeepNeighbour": ("forget_key", "predicate"),
    "bicentennial.items.templates.g2.keep_incidental.KeepIncidental": ("detail_id",),
    "bicentennial.items.templates.g2.tuesday_trigger.TuesdayTrigger": ("commitment_id",),
}


@dataclass(frozen=True)
class Binding:
    template_id: str
    fields: tuple[tuple[str, object], ...]
    checkpoint: int

    def __post_init__(self):
        object.__setattr__(self, "fields", tuple(sorted(self.fields, key=lambda f: f[0])))


def compile_bound(db, schedule, cut, templates, bindings) -> Branch:
    digest = sha256(schedule.to_json()).hexdigest()
    seed = db.execute("SELECT seed FROM meta").fetchone()[0]
    if (cut.branch not in ("B0", "B1") or cut.life != schedule.life
            or cut.world_hash != world_hash(db) or cut.schedule_sha256 != digest
            or seed != schedule.seed):
        raise ValueError("branch world or schedule identity mismatch")
    templates = tuple(templates)
    lookup = {t.template_id: t for t in templates}
    if len(lookup) != len(templates):
        raise ValueError("duplicate template id")
    entries, seen, counts = [], set(), {}
    for b in sorted(bindings, key=lambda b: (b.template_id, b.fields, b.checkpoint)):
        if b.template_id not in lookup:
            raise ValueError("binding:template")
        t = lookup[b.template_id]
        cls = type(t)
        allowed = BINDING_FIELDS.get(f"{cls.__module__}.{cls.__qualname__}",
                                     getattr(cls, "BINDING_FIELDS", None))
        names = [name for name, _ in b.fields]
        if allowed is None or len(names) != len(set(names)) or set(names) != set(allowed):
            raise ValueError("binding:field")
        if type(b.checkpoint) is not int or b.checkpoint not in schedule.scale.checkpoints:
            raise ValueError("binding:checkpoint")
        bound = replace(t, **dict(b.fields), checkpoint=b.checkpoint)
        instances = tuple(bound.instances(db, schedule))
        if len(instances) != 1:
            raise ValueError("binding:instances")
        i, = instances
        if type(i.key) is not str or not i.key:
            raise ValueError("invalid or duplicate instance key")
        key = t.template_id, i.key
        if key in seen:
            raise ValueError("duplicate binding")
        seen.add(key)
        entries.append(_entry(db, schedule, cut, bound, i))
        key = i.probe_point, t.kind
        counts[key] = counts.get(key, 0) + 1
        if schedule.scale.name == "t1" and counts[key] > (6 if t.kind == "qa" else 2):
            raise ValueError("T1 probe budget exceeded")
    return Branch(cut.life, cut.branch, seed, digest,
                  tuple(sorted(entries, key=lambda e: e[0]["item_id"])))
