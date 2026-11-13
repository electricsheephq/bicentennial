"""Edition-2 T2 packs (#505, #506): built only from v2 pieces, and accepted by the unchanged run gate."""

from contextlib import closing
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.items.editions import BY_REF, C7_FILES
from bicentennial.packs import build
from bicentennial.packs.manifest import file_sha256
from bicentennial.runner import t1
from bicentennial.score.check_selftest import mutant_roles, selftest
from bicentennial.world import targeted as t
from bicentennial.world.db import open_world

from .test_build import A

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "tiers/life_specs/t2.toml"
# The four v2 prompts as built on the first public life of each genre (t2-g1-1, t2-g2-1).
PROMPTS = {
    "drift-chain-fault-v2": {'Record the general release deadline in docs/decisions.md, as one line of the form '
                             '"- general release: <deadline>" (the entry name is exactly "general release").'},
    "drift-config-v2": {"Check retry interval in config/settings.toml. If a firm correction replaced its value, set "
                        "the new value; if a new value was only raised as a possibility, leave the file unchanged."},
    "drift-quote-v2": {"Add the lock timeout setting to config/settings.toml. Use the value that was set for it "
                       "directly; a value that was only reported or quoted later does not replace it."},
    "recall-count-v2": {"How many times did the date of Trip 2 change? For the citation, quote a single line from "
                        "just one of the messages that stated it; never join lines or messages."},
}
V1_OF = {f"{tid}-v2": f"{tid}-v1" for tid in ("drift-chain-fault", "drift-config", "drift-quote", "recall-count")}


@pytest.fixture(scope="module")
def edition2(tmp_path_factory):
    out = tmp_path_factory.mktemp("edition2")
    result = build.build_tier("T2", out, harness_artifacts=A, spec_path=SPEC, edition=2)
    return SimpleNamespace(root=out / "T2", result=result,
                           packs={rel: t1._pack(out / "T2", rel) for rel in sorted(result["index"]["packs"])})


@pytest.fixture(scope="module")
def edition1(tmp_path_factory):
    spec = t.load_tier(SPEC)
    spec["lives"] = [spec["lives"][0], spec["lives"][5]]
    out = tmp_path_factory.mktemp("edition1")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "load_tier", lambda path: spec)
        result = build.build_tier("T2", out, harness_artifacts=A)
    return tuple(t1._pack(out / "T2", rel) for rel in sorted(result["index"]["packs"]))


def ref(record):
    return f"{record['template_id']}-v{record['template_version']}"


def test_v2_instances_equal_v1_but_prompt_and_table(edition2):
    spec, seen = t.load_tier(SPEC), set()
    for pack in edition2.packs.values():
        items = {i["item_id"]: i for i in pack.pack["items"]}
        for record in pack.records.values():
            if ref(record) not in V1_OF:
                continue
            seen.add(ref(record))
            k = items[record["item_id"]]["probe_point"]
            v1, v2 = t.repoint_templates(spec, [replace(BY_REF[r], checkpoint=k)
                                                for r in (V1_OF[ref(record)], ref(record))])
            with closing(open_world(pack.life_dir / f"world.{record['branch']}.db", readonly=True)) as db:
                (a,), (b,) = v1.instances(db, pack.schedule), v2.instances(db, pack.schedule)
            assert b.key == record["instance_key"] and b.prompt == items[record["item_id"]]["prompt"]
            assert asdict(replace(b, prompt=a.prompt, decision_table_ref=a.decision_table_ref)) == asdict(a)
            assert b.prompt != a.prompt
            assert b.decision_table_ref == (None if a.decision_table_ref is None
                                            else a.decision_table_ref.removesuffix("-v1") + "-v2")
    assert seen == set(V1_OF)


def test_v2_prompts_on_one_life(edition2):
    prompts = {}
    for rel in ("pack/G1/t2-g1-1/4", "pack/G2/t2-g2-1/9"):
        pack = edition2.packs[rel]
        items = {i["item_id"]: i for i in pack.pack["items"]}
        for record in pack.records.values():
            if ref(record) in V1_OF:
                prompts.setdefault(ref(record), set()).add(items[record["item_id"]]["prompt"])
    assert prompts == PROMPTS


def test_edition2_pack(edition2):
    index, entries = edition2.result["index"], build.c7_entries(ROOT / C7_FILES[2])
    assert len(index["packs"]) == 10
    swapped = {v1 for v1 in V1_OF.values()}
    v2_cases = []
    for pack in edition2.packs.values():
        assert pack.manifest["pins"]["c7_sha256"] == file_sha256(ROOT / C7_FILES[2])
        assert pack.manifest["pins"]["c7_entries"] == {
            r: entries[r]["entry_sha256"] for r in pack.manifest["pins"]["c7_entries"]}
        assert not {ref(r) for r in pack.records.values()} & swapped
        for case in pack.cases.values():
            if ref(case.record) not in V1_OF:
                continue
            template = BY_REF[ref(case.record)]
            if case.table is None:
                assert case.item["stage"] != "act" and case.item["decision_table_ref"] == template.ref
            else:
                assert case.table in template.decision_tables and case.table["table_id"].endswith("-v2")
                assert case.item["decision_table_ref"] == case.table["table_id"]
                v2_cases.append(case)
    report = selftest(v2_cases)
    assert report.ok and v2_cases
    rows = {(r["table_id"], r["kind"]) for r in report.rows if r["ok"]}
    roles = mutant_roles()
    for table_id in {c.table["table_id"] for c in v2_cases}:
        assert (table_id, "gold") in rows
        if roles[table_id]["stale"]:
            assert (table_id, "stale") in rows


def test_run_gate_accepts_both_editions(edition1, edition2):
    t1._check_c7(edition1)
    t1._check_c7(tuple(edition2.packs.values()))
    assert {ref(r) for p in edition1 for r in p.records.values()} & set(V1_OF.values())


def test_run_gate_refuses_a_tampered_v2_entry(edition2, monkeypatch):
    real = t1.c7_entries

    def tampered(path):
        entries = real(path)
        if "drift-quote-v2" in entries:
            entries["drift-quote-v2"] = dict(entries["drift-quote-v2"], entry_sha256="f" * 64)
        return entries

    monkeypatch.setattr(t1, "c7_entries", tampered)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition2.packs.values()))
    assert caught.value.code == "c7_changed"


def test_run_gate_refuses_an_unknown_ref(edition2):
    pack = next(p for p in edition2.packs.values() if p.genre == "G1")
    records = {i: dict(r, template_version=9) if r["template_id"] == "drift-quote" else r
               for i, r in pack.records.items()}
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7((replace(pack, records=records),))
    assert caught.value.code == "c7_missing"


def test_run_gate_refuses_two_entries_for_one_ref(monkeypatch):
    real = t1.c7_entries

    def split(path):
        entries = real(path)
        if path.name == Path(C7_FILES[2]).name:
            entries["drift-asof-v1"] = dict(entries["drift-asof-v1"], entry_sha256="f" * 64)
        return entries

    monkeypatch.setattr(t1, "c7_entries", split)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(())
    assert caught.value.code == "c7_changed"
