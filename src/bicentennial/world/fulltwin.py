"""Full-length twins over planned fixtures, with default-world diagnostics."""

import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.genres.g1_software.world import build_g1, world_meta
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.items.bindings import Binding, compile_bound
from bicentennial.items.templates.g1 import TEMPLATES as G1
from bicentennial.items.templates.g2 import TEMPLATES as G2
from bicentennial.render.session_cut import cut

from . import create_world, fixtureplan, open_world, planned
from .processes import mint
from .scale import named
from .schedule import build_schedule
from .targeted import MIN_DISTANCE_SESSIONS, expected_state, seed_text
from .twin import TwinLife, twin_life


@dataclass(frozen=True)
class Candidate:
    template: object
    fields: tuple[tuple[str, object], ...]
    fixture: tuple[str, str]

    def binding(self, checkpoint):
        return Binding(self.template.template_id, self.fields, checkpoint)


# These are logical writer keys, never discovered by probing minted ids. Omit
# surfaced statements and non-context/non-stated preferences by design. Constant
# chains remain listed for diagnostics even when their surface checks refuse.
FIXTURES = {
    "drift-chain": (("chain", "deadline-0", dict(chain_id="deadline-0", depth=1)),
                    ("chain", "deadline-1", dict(chain_id="deadline-1", depth=2)),
                    ("chain", "constraint-0", dict(chain_id="constraint-0", depth=1))),
    "drift-config": tuple(("chain", key, dict(chain_id=key))
                          for key in ("constant-0", "constant-1")),
    "drift-quote": tuple(("chain", key, dict(chain_id=key))
                         for key in ("constant-0", "constant-1")),
    "recall-value": tuple(("statement", key, dict(statement_id=key)) for key in (
        "constraint-1", "constraint-2", "constraint-3", "decision-0", "decision-1")),
    "wake-loop": tuple(("statement", key, dict(statement_id=key))
                       for key in ("decision-0", "decision-1")),
    "tue-ticket": tuple(("commitment", key, dict(commitment_id=key))
                        for key in ("commitment-0", "commitment-1")),
    "drift-asof": (("preference", "seat-long", dict(pref_id="seat-long")),),
    "drift-booking": (("preference", "seat-long", dict(pref_id="seat-long")),),
    "drift-no-update": (("preference", "seat-short", dict(pref_id="seat-short")),),
    "keep-forget": (("forget", "ex", dict(forget_key="ex")),),
    "keep-neighbour": (("forget", "ex", dict(forget_key="ex", predicate="birthday")),),
    "keep-incidental": tuple(("detail", key, dict(detail_id=key))
                             for key in ("gate", "parking")),
    "recall-count": (("attribute", "trip/trip/date", dict(
        entity_kind="trip", entity_key="trip", attr_key="date")),),
    "tue-passport": (("commitment", "passport", dict(commitment_id="passport")),),
}
FIXTURES["drift-chain-fault"] = FIXTURES["drift-chain"]


def candidates(genre):
    if genre not in ("G1", "G2"):
        raise ValueError("genre")
    return tuple(Candidate(t, tuple(sorted(fields.items())), (kind, key))
                 for t in (G1 if genre == "G1" else G2)
                 for kind, key, fields in FIXTURES[t.template_id])


def validate_budget(budget):
    fixtureplan.validate_budget(budget)


def accepts(binding, compile_one):
    try:
        branch = compile_one(binding)
    except ValueError:
        return False
    return (len(branch.entries) == 1
            and branch.entries[0][1]["evidence_session"] is not None
            and binding.checkpoint - branch.entries[0][1]["evidence_session"]
            >= MIN_DISTANCE_SESSIONS)


def _world(genre, life, seed, directory):
    scale = named("full")
    schedule = build_schedule(seed_text(seed), life, scale)
    path = Path(directory) / "world.B0.db"
    if genre == "G1":
        db = create_world(path, world_meta(seed_text(seed), 200))
        try:
            principal = build_g1(db, schedule).principal
            db.commit()
        except BaseException:
            db.close()
            path.unlink(missing_ok=True)
            raise
    elif genre == "G2":
        existed = path.exists()
        try:
            base = build_base(path, seed=seed_text(seed), life=life, scale=scale)
        except BaseException:
            if not existed:  # build_base reserved the file before a writer failed
                path.unlink(missing_ok=True)
            raise
        db, principal = base.db, base.people.principal
        if base.schedule.to_json() != schedule.to_json():
            db.close()
            path.unlink(missing_ok=True)
            raise ValueError("composition")
    else:
        raise ValueError("genre")
    return db, schedule, principal


def _compiler(db, schedule, principal, genre):
    pre = cut(db, schedule, branch="B0", principal_id=principal,
              expected_state=expected_state(genre, schedule)(db))
    templates = G1 if genre == "G1" else G2

    def compile_one(binding):
        return compile_bound(db, schedule, pre, templates, (binding,))

    return compile_one


@dataclass(frozen=True)
class FullTwin:
    twin: TwinLife
    bindings: tuple[Binding, ...]
    prompts: dict[tuple[str, int], tuple[str, ...]]


def build(genre, life, seed, budget, out_dir) -> FullTwin:
    validate_budget(budget)
    out_dir = Path(out_dir)
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise ValueError("out:exists")
    registry = G1 if genre == "G1" else G2
    schedule = build_schedule(seed_text(seed), life, named("full"))
    plan = fixtureplan.plan(genre, schedule, budget, registry)
    missing, parent = [], out_dir.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    stage = scratch = db = twin = None
    try:
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(dir=out_dir.parent, prefix="." + out_dir.name + "."))
        (stage / "scratch").mkdir()
        scratch, _, principal = _world(genre, life, seed, stage / "scratch")
        counts = planned.write_extra(genre, scratch, schedule, plan, principal)
        db = planned.rebuild(scratch, stage / "world.B0.db")
        scratch.close()
        shutil.rmtree(stage / "scratch")
        host(db, schedule, principal, genre, plan, registry)
        twin = twin_life(db, schedule, registry, bindings=plan.bindings,
                         world_path=stage / "world.B1.db", out_dir=stage / "branches",
                         principal_id=principal, expected_state=expected_state(genre, schedule),
                         reserve_alternates=True)
        indices = {p.session_id: p.index for p in schedule.sessions}
        if indices[twin.cuts[0].rows[twin.prefix]["session_id"]] != plan.fork:
            raise ValueError("plan:fork_mismatch")
        (stage / "bindings.json").write_bytes(canon([asdict(b) for b in sorted(
            plan.bindings, key=lambda b: (b.template_id, b.fields, b.checkpoint))]) + b"\n")
        (stage / "plan.json").write_bytes(canon(
            json.loads(fixtureplan.plan_json(plan)) | {"written": counts}) + b"\n")
        db.close()
        twin.b1.close()
        os.rename(stage, out_dir)
    except BaseException:
        for connection in (scratch, db, twin.b1 if twin else None):
            if connection is not None:
                connection.close()
        if stage is not None:
            shutil.rmtree(stage)
        for path in missing:
            path.rmdir()
        raise
    twin = replace(twin, b1=open_world(out_dir / "world.B1.db"))
    records = {r["item_id"]: r for r in twin.compiled.records}
    prompts = {}
    for branch in ("B0", "B1"):
        for checkpoint in sorted({b.checkpoint for b in plan.bindings}):
            prompts[branch, checkpoint] = tuple(i["prompt"] for i in twin.compiled.items
                if records[i["item_id"]]["branch"] == branch and i["probe_point"] == checkpoint)
    return FullTwin(twin, plan.bindings, prompts)


def survey(genre, life, seed, work_dir):
    table = candidates(genre)
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work_dir) as directory:
        db, schedule, principal = _world(genre, life, seed, directory)
        try:
            compile_one = _compiler(db, schedule, principal, genre)
            result = []
            for c in table:
                for k in schedule.scale.checkpoints:
                    try:
                        branch = compile_one(c.binding(k))
                    except ValueError as error:
                        refusal = str(error)
                    else:
                        refusal = None if accepts(c.binding(k), lambda b, v=branch: v) else "distance"
                    result.append((c, k, refusal))
            return tuple(result)
        finally:
            db.close()


def capacity(genre, life, seed, work_dir):
    rows = survey(genre, life, seed, work_dir)
    return {(cell, k): len({c.fixture for c, checkpoint, refusal in rows
                           if c.template.cell_id == cell and checkpoint == k and refusal is None})
            for cell in sorted({c.template.cell_id for c, _, _ in rows})
            for k in named("full").checkpoints}


def host(db, schedule, principal, genre, plan, registry):
    """Check instances first; compiler integrity errors then propagate unchanged."""
    pre = cut(db, schedule, branch="B0", principal_id=principal,
              expected_state=expected_state(genre, schedule)(db))
    lookup = {t.template_id: t for t in registry}
    checked = {}
    for b in plan.bindings:
        t = lookup[b.template_id]
        bound = replace(t, **dict(b.fields), checkpoint=b.checkpoint)
        try:
            instances = tuple(bound.instances(db, schedule))
            if len(instances) != 1:
                raise ValueError("binding:instances")
        except ValueError as error:
            raise ValueError(f"plan:unhostable:{t.cell_id}@{b.checkpoint}:{b.template_id}:{error}") from error
        checked[b.template_id, instances[0].key] = b
    compiled = compile_bound(db, schedule, pre, registry, plan.bindings)
    positions = {r["event_id"]: r["session_id"] for r in pre.rows}
    indices = {p.session_id: p.index for p in schedule.sessions}
    for item, meta in compiled.entries:
        b = checked[meta["template_id"], meta["instance_key"]]
        t = lookup[b.template_id]
        cue = fixtureplan.CUES.get(fixtureplan.qualname(t))
        exempt = mint(schedule, "commitments", dict(b.fields)["commitment_id"], "event", cue, 0) if cue else None
        evidence = [indices[positions[e]] for e in item["gold_spans"] if e != exempt]
        if not evidence or b.checkpoint - max(evidence) < MIN_DISTANCE_SESSIONS:
            raise ValueError(f"plan:distance:{t.cell_id}@{b.checkpoint}:{b.template_id}")
    turns = {}
    for r in pre.rows:
        kinds, facts = turns.setdefault(r["turn_key"], (set(), set()))
        kinds.add(r["kind"])
        facts.update(r["fact_ids"])
    if any("filler" in kinds and facts for kinds, facts in turns.values()):
        raise ValueError("plan:mixed")
    return compiled
