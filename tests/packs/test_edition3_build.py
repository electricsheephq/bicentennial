"""Edition 3 builds the three exact finalists; only control runs may use its packs."""

from contextlib import closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.items.editions import BY_REF, C7_FILES
from bicentennial.packs import build
from bicentennial.packs.manifest import file_sha256
from bicentennial.runner import t1
from bicentennial.score.check_selftest import mutant_roles, selftest
from bicentennial.screen.candidates import CANDIDATES
from bicentennial.world import targeted
from bicentennial.world.db import open_world

from .test_build import A

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tiers/life_specs/t2.toml"
SWAPPED = {"drift-chain-fault", "drift-config", "drift-quote"}


@pytest.fixture(scope="module")
def edition3(tmp_path_factory):
    out = tmp_path_factory.mktemp("edition3")
    result = build.build_tier("T2", out, harness_artifacts=A, spec_path=SPEC, edition=3)
    return SimpleNamespace(result=result,
                           packs={rel: t1._pack(out / "T2", rel) for rel in sorted(result["index"]["packs"])})


@pytest.fixture(scope="module")
def edition2(tmp_path_factory):
    spec = targeted.load_tier(SPEC)
    spec["lives"] = [spec["lives"][0]]
    out = tmp_path_factory.mktemp("edition2")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "load_tier", lambda path: spec)
        result = build.build_tier("T2", out, harness_artifacts=A, edition=2)
    return tuple(t1._pack(out / "T2", rel) for rel in sorted(result["index"]["packs"]))


def ref(record):
    return f"{record['template_id']}-v{record['template_version']}"


def test_edition3_pack_and_v3_selftest(edition3):
    entries = build.c7_entries(ROOT / C7_FILES[3])
    assert len(edition3.result["index"]["packs"]) == 10
    cases = []
    for pack in edition3.packs.values():
        assert pack.manifest["pins"]["c7_sha256"] == file_sha256(ROOT / C7_FILES[3])
        assert pack.manifest["pins"]["c7_entries"] == {
            r: entries[r]["entry_sha256"] for r in pack.manifest["pins"]["c7_entries"]}
        assert all(r["template_version"] == 3 for r in pack.records.values() if r["template_id"] in SWAPPED)
        assert all(r["template_version"] == 1 for r in pack.records.values() if r["template_id"] not in SWAPPED)
        for case in pack.cases.values():
            if case.record["template_id"] in SWAPPED:
                assert case.item["stage"] == "act"
                assert case.table in BY_REF[ref(case.record)].decision_tables
                assert case.table["table_id"].endswith("-v3")
                assert case.item["decision_table_ref"] == case.table["table_id"]
                cases.append(case)
    report = selftest(cases)
    assert cases and report.ok
    rows = {(r["table_id"], r["kind"]) for r in report.rows if r["ok"]}
    roles = mutant_roles()
    tables = {table["table_id"] for tid in SWAPPED for table in BY_REF[f"{tid}-v3"].decision_tables}
    assert {c.table["table_id"] for c in cases} == tables
    for table_id in tables:
        assert (table_id, "gold") in rows
        if roles[table_id]["stale"]:
            assert (table_id, "stale") in rows


def test_v3_prompts_on_first_public_g1_life_equal_variant_zero(edition3):
    pack = edition3.packs["pack/G1/t2-g1-1/4"]
    items = {i["item_id"]: i for i in pack.pack["items"]}
    seen = set()
    for record in pack.records.values():
        tid = record["template_id"]
        if tid not in SWAPPED:
            continue
        item = items[record["item_id"]]
        candidate, = targeted.repoint_templates(targeted.load_tier(SPEC), (
            replace(CANDIDATES[f"{tid}-K3"][0], checkpoint=item["probe_point"]),))
        with closing(open_world(pack.life_dir / f"world.{record['branch']}.db", readonly=True)) as db:
            screened, = candidate.instances(db, pack.schedule)
        assert item["prompt"].encode() == screened.prompt.encode()
        seen.add(tid)
    assert seen == SWAPPED


def test_run_gate_accepts_control_and_refuses_system(edition3):
    packed = tuple(edition3.packs.values())
    t1._check_c7(packed, control=True)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(packed, control=False)
    assert caught.value.code == "template_not_admitted"


def test_run_gate_refuses_editions2_and3_together(edition2, edition3):
    t1._check_c7(edition2, control=True)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7((*edition2, *edition3.packs.values()), control=True)
    assert caught.value.code == "c7_edition"


def test_run_gate_refuses_v2_and_v3_of_one_template_in_one_pack(edition3):
    pack = next(p for p in edition3.packs.values() if p.genre == "G1")
    record = next(r for r in pack.records.values() if r["template_id"] == "drift-quote")
    v2 = dict(record, item_id=record["item_id"] + "-v2", template_version=2)
    pins = dict(pack.manifest["pins"], c7_entries=dict(pack.manifest["pins"]["c7_entries"], **{
        "drift-quote-v2": build.c7_entries(ROOT / C7_FILES[2])["drift-quote-v2"]["entry_sha256"]}))
    mixed = replace(pack, records={**pack.records, v2["item_id"]: v2}, manifest=dict(pack.manifest, pins=pins))
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7((mixed,), control=True)
    assert caught.value.code == "c7_edition"


def test_run_gate_refuses_a_tampered_v3_entry(edition3, monkeypatch):
    real = t1.c7_entries

    def tampered(path):
        entries = real(path)
        if "drift-quote-v3" in entries:
            entries["drift-quote-v3"] = dict(entries["drift-quote-v3"], entry_sha256="f" * 64)
        return entries

    monkeypatch.setattr(t1, "c7_entries", tampered)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition3.packs.values()), control=True)
    assert caught.value.code == "c7_changed"


def test_t1_builds_edition3(tmp_path):
    result = build.build_tier("T1", tmp_path, harness_artifacts=A, edition=3)
    packed = tuple(t1._pack(tmp_path / "T1", rel) for rel in sorted(result["index"]["packs"]))
    assert {p.genre for p in packed} == {"G1", "G2"}
    assert all(p.manifest["pins"]["c7_sha256"] == file_sha256(ROOT / C7_FILES[3]) for p in packed)
    assert {ref(r) for p in packed for r in p.records.values() if r["template_id"] in SWAPPED} == {
        f"{tid}-v3" for tid in SWAPPED}
    t1._check_c7(packed, control=True)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(packed)
    assert caught.value.code == "template_not_admitted"
