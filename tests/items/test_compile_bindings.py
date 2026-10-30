"""Bindings preserve compiler identity while allowing repeated template designs."""

from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from typing import ClassVar

import pytest

from bicentennial.genres.g1_software.world import world_meta
from bicentennial.items.bindings import Binding, compile_bound
from bicentennial.items.c7 import freeze
from bicentennial.items.templates.g1 import TEMPLATES, DriftChain
from bicentennial.render.session_cut import cut
from bicentennial.world import create_world
from bicentennial.world.db import insert_entity
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions
from bicentennial.world.twin import plan, twin_life

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = next(t for t in TEMPLATES if t.template_id == "drift-chain")


def binding(key="deadline-0", checkpoint=3, **fields):
    return Binding(TEMPLATE.template_id, tuple(dict(chain_id=key, depth=1, **fields).items()), checkpoint)


@pytest.fixture
def world(tmp_path):
    s = build_schedule("1", "bindings", named("t0-micro", sessions=3))
    s = replace(s, scale=replace(s.scale, checkpoints=(2, 3)), sessions=tuple(
        replace(p, probe_point=True) if p.index == 2 else p for p in s.sessions))
    db = create_world(tmp_path / "base.db", world_meta("1", 3))
    write_sessions(db, s)
    for name, kind in (("principal", "person"), ("alpha", "milestone"), ("beta", "milestone")):
        insert_entity(db, id=name, kind=kind, canonical_name=name, aliases_json=[],
                      created_t=s.sessions[0].t_start, retired_t=None)
    write_corrections(db, s, [Chain(id=f"deadline-{j}", subject=name, key="deadline",
        stem="DUE", depth=1, at=((1, j + 1), (2, j + 1)))
        for j, name in enumerate(("alpha", "beta"))], principal="principal")
    write_filler(db, s, principal="principal")
    db.commit()
    def state(db):
        return {p.index: dict(repo_tree_hash="a" * 64, env_state_hash="b" * 64)
                for p in s.sessions}
    pre = cut(db, s, branch="B0", principal_id="principal", expected_state=state(db))
    yield db, s, pre, state
    db.close()


def test_two_fixtures_ids_and_plan(world, tmp_path):
    db, s, pre, state = world
    bindings = (binding(), binding("deadline-1"))
    branch = compile_bound(db, s, pre, TEMPLATES, bindings)
    assert branch == compile_bound(db, s, pre, reversed(TEMPLATES), reversed(bindings))
    assert {m["instance_key"] for _, m in branch.entries} == {"chain-deadline-0", "chain-deadline-1"}
    assert len({i["item_id"] for i, _ in branch.entries}) == 2
    options = [o["option_id"] for i, _ in branch.entries for o in i["options"]]
    assert len(set(options)) == len(options)
    assert {f.key for f in plan(db, s, branch, principal_id="principal")} == {
        (TEMPLATE.template_id, f"chain-deadline-{j}") for j in range(2)}
    twin = twin_life(db, s, TEMPLATES, bindings=bindings, world_path=tmp_path / "b1.db",
                     out_dir=tmp_path / "branches", principal_id="principal", expected_state=state)
    try:
        assert len({b["bundle_id"] for b in twin.compiled.bundles}) == 2
        assert len(twin.compiled.items) == 4
    finally:
        twin.b1.close()


@pytest.mark.parametrize("checkpoints", [(3, 3), (2, 3)])
def test_duplicate_binding(world, checkpoints):
    db, s, pre, _ = world
    with pytest.raises(ValueError, match="^duplicate binding$"):
        compile_bound(db, s, pre, TEMPLATES, [binding(checkpoint=k) for k in checkpoints])


@pytest.mark.parametrize("b,message", [
    (Binding("absent", (), 3), "binding:template"),
    (Binding("drift-chain", (("chain_id", "deadline-0"),), 3), "binding:field"),
    (binding(fault=True), "binding:field"),
    (Binding("drift-chain", (("chain_id", "deadline-0"), ("depth", 1), ("depth", 1)), 3), "binding:field"),
    (binding(checkpoint=1), "binding:checkpoint"),
    (binding(checkpoint=True), "binding:checkpoint"),
])
def test_refusals(world, b, message):
    db, s, pre, _ = world
    with pytest.raises(ValueError, match=f"^{message}$"):
        compile_bound(db, s, pre, TEMPLATES, [b])


@dataclass(frozen=True, kw_only=True, eq=False)
class Declared(DriftChain):
    BINDING_FIELDS: ClassVar = ("chain_id", "depth")
    count: int = 2

    def instances(self, db, schedule):
        return super().instances(db, schedule) * self.count


@dataclass(frozen=True, kw_only=True, eq=False)
class Undeclared(DriftChain):
    pass


@pytest.mark.parametrize("count", [0, 2])
def test_instance_count(world, count):
    db, s, pre, _ = world
    t = Declared(**vars(TEMPLATE), count=count)
    with pytest.raises(ValueError, match="^binding:instances$"):
        compile_bound(db, s, pre, [t], [binding()])
    if count == 2:
        assert len(compile_bound(db, s, pre, [replace(t, count=1)], [binding()]).entries) == 1


def test_undeclared_and_duplicate_template(world):
    db, s, pre, _ = world
    with pytest.raises(ValueError, match="^binding:field$"):
        compile_bound(db, s, pre, [Undeclared(**vars(TEMPLATE))], [binding()])
    with pytest.raises(ValueError, match="^duplicate template id$"):
        compile_bound(db, s, pre, [TEMPLATE, TEMPLATE], [])


@pytest.mark.parametrize("change", [dict(branch="B2"), dict(life="wrong"),
    dict(world_hash="wrong"), dict(schedule_sha256="wrong")])
def test_cut_identity(world, change):
    db, s, pre, _ = world
    with pytest.raises(ValueError, match="identity mismatch"):
        compile_bound(db, s, replace(pre, **change), TEMPLATES, [binding()])


def test_seed_identity(world):
    db, s, pre, _ = world
    with pytest.raises(ValueError, match="identity mismatch"):
        compile_bound(db, replace(s, seed="wrong"), pre, TEMPLATES, [binding()])


def test_c7_registry_unchanged(world):
    db, s, pre, _ = world
    before = freeze(ROOT)
    compile_bound(db, s, pre, TEMPLATES, [binding("deadline-1", checkpoint=2)])
    assert freeze(ROOT) == before
    assert TEMPLATE.chain_id == "deadline-0" and TEMPLATE.checkpoint is None


def test_fields_sorted():
    b = Binding("example", (("z", 1), ("a", 2)), 20)
    assert b.fields == (("a", 2), ("z", 1))
    with pytest.raises(FrozenInstanceError):
        b.checkpoint = 60
