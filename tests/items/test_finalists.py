"""The registered v3 templates are exactly the screened K3 finalists, at variant 0."""

from contextlib import closing
from dataclasses import asdict, fields, replace
from pathlib import Path

import pytest

from bicentennial.items.editions import BY_REF
from bicentennial.items.templates.g1 import repo_checks
from bicentennial.packs import build
from bicentennial.runner import t1
from bicentennial.screen.candidates import CANDIDATES
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.world import targeted
from bicentennial.world.db import open_world

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tiers/life_specs/t2.toml"
FINALISTS = [(f"{tid}-K3", f"{tid}-v3") for tid in ("drift-config", "drift-quote", "drift-chain-fault")]


@pytest.fixture(scope="module")
def public_g1(tmp_path_factory):
    spec = targeted.load_tier(SPEC)
    spec["lives"] = [row for row in spec["lives"] if row["genre"] == "G1"]
    out = tmp_path_factory.mktemp("public-g1-finalists")
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "load_tier", lambda path: spec)
        result = build.build_tier("T2", out, harness_artifacts=[artifact], spec_path=SPEC, edition=3)
    return tuple(t1._pack(out / "T2", rel) for rel in sorted(result["index"]["packs"]))


@pytest.mark.parametrize("card, ref", FINALISTS)
def test_finalist_fields_and_bindings_equal_variant_zero(card, ref):
    candidate, registered = CANDIDATES[card][0], BY_REF[ref]
    registered_fields = {f.name for f in fields(registered)}
    assert {f.name for f in fields(candidate)} - registered_fields == {"variant"}
    assert candidate.variant == 0
    assert all(getattr(registered, name) == getattr(candidate, name) for name in registered_fields)
    assert registered.BINDING_FIELDS == candidate.BINDING_FIELDS


@pytest.mark.parametrize("card, ref", FINALISTS)
def test_finalist_instances_and_repo_checks_on_every_public_g1_life(public_g1, card, ref):
    spec, seen = targeted.load_tier(SPEC), set()
    for pack in public_g1:
        items = {i["item_id"]: i for i in pack.pack["items"]}
        records = [r for r in pack.records.values() if r["template_id"] == BY_REF[ref].template_id]
        assert len(records) == 2
        for record in records:
            checkpoint = items[record["item_id"]]["probe_point"]
            registered, candidate = targeted.repoint_templates(spec, tuple(
                replace(template, checkpoint=checkpoint) for template in (BY_REF[ref], CANDIDATES[card][0])))
            with closing(open_world(pack.life_dir / f"world.{record['branch']}.db", readonly=True)) as db:
                a, b = registered.instances(db, pack.schedule), candidate.instances(db, pack.schedule)
                assert [asdict(i) for i in a] == [asdict(i) for i in b]
                assert repo_checks(registered, db, pack.schedule) == repo_checks(candidate, db, pack.schedule)
            seen.add((pack.schedule.life, record["branch"]))
    assert seen == {(row["life"], branch) for row in spec["lives"] if row["genre"] == "G1"
                    for branch in ("B0", "B1")}
