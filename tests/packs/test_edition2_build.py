"""Edition-2 T2 packs (#505, #506): built from v2 pieces, with separate control and system admission."""

import json
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
    t1._check_c7(edition1, control=True)
    t1._check_c7(tuple(edition2.packs.values()), control=True)
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


def test_run_gate_refuses_v1_and_v2_of_one_template_in_one_pack(edition2):
    # Each ref has its own valid C-7 entry and pin; only the mix is wrong.
    pack = next(p for p in edition2.packs.values() if p.genre == "G1")
    record = next(r for r in pack.records.values() if r["template_id"] == "drift-quote")
    v1 = dict(record, item_id=record["item_id"] + "-v1", template_version=1)
    pins = dict(pack.manifest["pins"], c7_entries=dict(pack.manifest["pins"]["c7_entries"], **{
        "drift-quote-v1": build.c7_entries(ROOT / C7_FILES[1])["drift-quote-v1"]["entry_sha256"]}))
    mixed = replace(pack, records={**pack.records, v1["item_id"]: v1}, manifest=dict(pack.manifest, pins=pins))
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7((mixed,))
    assert caught.value.code == "c7_edition"


def test_run_gate_refuses_packs_from_two_editions(edition1, edition2):
    g2 = next(p for p in edition1 if p.genre == "G2")
    assert "recall-count-v1" in {ref(r) for r in g2.records.values()}
    t1._check_c7((g2,))
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7((*(p for p in edition2.packs.values() if p.genre == "G1"), g2))
    assert caught.value.code == "c7_edition"


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


def test_system_run_refuses_unadmitted_v2(edition2):
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition2.packs.values()), control=False)
    assert caught.value.code == "template_not_admitted"


def test_system_run_accepts_only_admitted_v2(edition2):
    packs = tuple(replace(p, records={iid: r for iid, r in p.records.items()
                                     if ref(r) != "recall-count-v2"})
                  for p in edition2.packs.values())
    t1._check_c7(packs, control=False)


def admissions_with_count():
    record = json.loads(t1.TEMPLATE_ADMISSIONS.read_bytes())
    record["admitted"]["recall-count-v2"] = dict(
        record["admitted"]["drift-quote-v2"],
        entry_sha256=build.c7_entries(ROOT / C7_FILES[2])["recall-count-v2"]["entry_sha256"])
    return record


def test_shipped_admissions_match_their_frozen_entries_and_result():
    """The shipped record admits exactly round 1's cleared versions, at their frozen C-7 content, with the scope and
    label their result page states."""
    record = json.loads(t1.TEMPLATE_ADMISSIONS.read_bytes())
    entries = build.c7_entries(ROOT / C7_FILES[2])
    assert set(record["admitted"]) == {"drift-chain-fault-v2", "drift-config-v2", "drift-quote-v2"}
    for ref, admission in record["admitted"].items():
        assert admission["reading"] == "cleared" and admission["round"] == "validity-1"
        assert admission["entry_sha256"] == entries[ref]["entry_sha256"]
        assert admission["scope"] == "fresh-seed follow-up (#394)"
        assert admission["labels"] == ["near-solved by naive retrieval"]
        page = (ROOT / admission["result"]).read_text()
        assert f"`{ref.removesuffix('-v2')}` v2" in page and "near-solved by naive retrieval" in page


def test_system_run_accepts_all_v2_when_admitted(edition2, tmp_path, monkeypatch):
    path = tmp_path / "admissions.json"
    path.write_text(json.dumps(admissions_with_count()))
    monkeypatch.setattr(t1, "TEMPLATE_ADMISSIONS", path)
    t1._check_c7(tuple(edition2.packs.values()), control=False)


@pytest.mark.parametrize("change", [dict(entry_sha256="f" * 64), dict(reading="format validated")])
def test_system_run_refuses_wrong_admission(edition2, tmp_path, monkeypatch, change):
    record = admissions_with_count()
    record["admitted"]["drift-quote-v2"].update(change)
    path = tmp_path / "admissions.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(t1, "TEMPLATE_ADMISSIONS", path)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition2.packs.values()))
    assert caught.value.code == "template_not_admitted"


@pytest.mark.parametrize("entry", [None, "cleared", [], {"reading": "cleared"}])
def test_system_run_refuses_a_malformed_entry(edition2, tmp_path, monkeypatch, entry):
    # Every other v2 ref is admitted, so the refusal comes from this one entry alone.
    record = admissions_with_count()
    record["admitted"]["drift-quote-v2"] = entry
    path = tmp_path / "admissions.json"
    path.write_text(json.dumps(record))
    monkeypatch.setattr(t1, "TEMPLATE_ADMISSIONS", path)
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition2.packs.values()))
    assert caught.value.code == "template_not_admitted"


@pytest.mark.parametrize("content", [None, "{", "[]", "null", "{}", '{"admitted": []}',
                                     '{"admitted": {"drift-quote-v2": null}}'])
def test_admissions_missing_or_malformed(edition1, edition2, tmp_path, monkeypatch, content):
    path = tmp_path / "admissions.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(t1, "TEMPLATE_ADMISSIONS", path)
    reads, real = [], t1._json

    def read(path):
        reads.append(path)
        return real(path)

    monkeypatch.setattr(t1, "_json", read)
    t1._check_c7(edition1, control=False)
    t1._check_c7(edition1, control=True)
    t1._check_c7(tuple(edition2.packs.values()), control=True)
    assert path not in reads
    with pytest.raises(t1.T1Refused) as caught:
        t1._check_c7(tuple(edition2.packs.values()), control=False)
    assert caught.value.code == "template_not_admitted"
    assert reads == [path]
