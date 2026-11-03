"""Keep incidental decoys affect diagnostics without changing first-match scoring."""

import copy
import json
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.controls import cache
from bicentennial.items import reader_keys as keys_module
from bicentennial.items.reader_keys import life_keys, reader_keys
from bicentennial.packs import build
from bicentennial.packs.catalogue import generate, load_catalogue
from bicentennial.probe.scripted_reader import item_report, read
from bicentennial.score.check_selftest import g2_cases, score_plan
from bicentennial.world import open_world, world_hash

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = [dict(name="hermes", version="test", sha256="a" * 64)]


def catalogue():
    return load_catalogue(ROOT / "packs/catalogue-v0.toml",
                          c7_path=ROOT / "specs/ring0/c7-partial.json",
                          tier_path=ROOT / "tiers/life_specs/t0.toml")


@pytest.fixture
def incidental(tmp_path):
    life = generate(catalogue().by_id()["g2-keep-incidental-mft-1"], out_dir=tmp_path / "life")
    try:
        with closing(open_world(life.out_dir / "world.B0.db", readonly=True)) as db:
            worlds = dict(B0=(db, life.twin.cuts[0]), B1=(life.twin.b1, life.twin.cuts[1]))
            cases = g2_cases(life.twin.compiled, worlds, life.schedule,
                             build._templates(life, life.twin.compiled.records), life=life.life)
            yield life, worlds, cases
    finally:
        life.twin.b1.close()


def decoy_tokens(case):
    return {t for o in case.item["options"] if case.roles[o["option_id"]] == "decoy"
            for t in o["tokens"]}


def test_item1_keep_incidental_visible_decoys_are_planted(incidental):
    life, worlds, cases = incidental
    keys = {k["item_id"]: k for k in life_keys(life.twin.compiled, life.schedule, worlds)}
    for case in cases:
        key = keys[case.item["item_id"]]
        expected = sorted((dict(token=t, kind="planted") for t in decoy_tokens(case)), key=lambda c: c["token"])
        assert expected
        assert key["competing"] == expected
        assert not set(key["required"]) & {c["token"] for c in key["competing"]}


def test_item1_keep_incidental_future_decoy_is_not_competing(incidental):
    life, worlds, cases = incidental
    for case in cases:
        db, cut = worlds[case.record["branch"]]
        token = sorted(decoy_tokens(case))[0]
        fid = db.execute("SELECT fact_id FROM locked_token WHERE value=?", (token,)).fetchone()[0]
        # A later session in the schedule exists beyond the copied probe point.
        item = copy.deepcopy(case.item)
        item["probe_point"] = len(life.schedule.sessions) - 1
        rows = tuple(dict(r, session_id=life.schedule.sessions[-1].session_id) if fid in r["fact_ids"]
                     else dict(r, session_id=life.schedule.sessions[0].session_id) for r in cut.rows)
        future = replace(cut, rows=rows)
        key = reader_keys(db, life.schedule, future, item, case.record, twin=case.twin)
        assert {c["token"] for c in key["competing"]} == decoy_tokens(case) - {token}
        assert all(c["kind"] == "planted" for c in key["competing"])


def test_item1_unmarked_options_are_not_planted(incidental):
    life, worlds, cases = incidental
    for case in cases:
        db, cut = worlds[case.record["branch"]]
        # The same visible options without the template's declaration gain no planted keys.
        item = dict(case.item, decision_table_ref="drift-booking-v1")
        record = dict(case.record, template_id="drift-booking")
        key = reader_keys(db, life.schedule, cut, item, record, twin=case.twin)
        assert not key["competing"]


@pytest.mark.parametrize("true,decoy,verdict,count", [
    (True, False, "PASS", 0), (True, True, "PASS", 1),
    (False, True, "FAIL_MEMORY", 1), (False, False, "OMISSION", 0),
], ids=["true-only", "true-and-decoy", "decoy-only", "neither"])
def test_item2_keep_incidental_first_match_and_counters(incidental, true, decoy, verdict, count):
    life, worlds, cases = incidental
    keys = {k["item_id"]: k for k in life_keys(life.twin.compiled, life.schedule, worlds)}
    for case in cases:
        item, key = case.item, keys[case.item["item_id"]]
        other = next(o for o in item["options"] if case.roles[o["option_id"]] == "decoy")
        context = "\n".join([*(item["options"][0]["tokens"] if true else []),
                             *(other["tokens"] if decoy else [])])
        result = read(reader_view(item), key, context, mode="api")
        score = score_plan(case, result.plan.steps)
        assert score.base_verdict == verdict
        assert score.score_milli == {"PASS": 1000, "FAIL_MEMORY": -1000, "OMISSION": 0}[verdict]
        assert result.competing == dict(stale=0, planted=count, twin=0)
        expected = item["options"][0] if true else other if decoy else next(
            o for o in item["options"] if not o["tokens"])
        assert result.selected_option == expected["option_id"]
        assert result.competing_present == ((other["option_id"],) if true and decoy else ())
        report = item_report(result, key, failed=verdict != "PASS")
        assert report["competing"]["planted"] == count
        assert report["competing_present"] == list(result.competing_present)


def test_item1_other_template_keys_byte_identical_on_built_t0_and_t1(tmp_path, monkeypatch):
    original = build._prepare
    seen, changed, artifact_changes = {}, {}, {}

    def audited(life, worlds, path, tier, rel, row, spec, entries, common_pins):
        before_worlds = {b: world_hash(db) for b, (db, _) in worlds.items()}
        current = life_keys(life.twin.compiled, life.schedule, worlds)
        # The former rule has no template-declared planted values; all other rules run verbatim.
        with monkeypatch.context() as patch:
            patch.setattr(keys_module, "planted_tokens", lambda item: ())
            previous = life_keys(life.twin.compiled, life.schedule, worlds)
        records = {r["item_id"]: r for r in life.twin.compiled.records}
        assert len(current) == len(previous)
        for old, new in zip(previous, current, strict=True):
            iid = new["item_id"]
            assert old["item_id"] == iid
            template = records[iid]["template_id"]
            seen.setdefault(tier, set()).add(template)
            if template != "keep-incidental":
                assert canon(old) == canon(new), (tier, rel, iid)
            else:
                assert canon(old) != canon(new), (tier, rel, iid)
                assert dict(new, competing=old["competing"]) == old
                assert all(c["kind"] == "planted" for c in new["competing"])
                changed.setdefault(tier, []).append([rel, iid])
            item = next(i for i in life.twin.compiled.items if i["item_id"] == iid)
            contexts = ["", *("\n".join(o["tokens"]) for o in item["options"]),
                        "\n".join(t for o in item["options"] for t in o["tokens"])]
            for context in contexts:
                before = read(reader_view(item), old, context, mode="api")
                after = read(reader_view(item), new, context, mode="api")
                assert replace(after, competing=before.competing) == before, (tier, rel, iid)
        baseline = tmp_path / "previous" / tier / rel
        code_sha256 = cache.code_sha256
        with monkeypatch.context() as patch:
            patch.setattr(keys_module, "planted_tokens", lambda item: ())
            # Fixed pre-erratum pin; no source or git history is needed for the old build.
            patch.setattr(cache, "code_sha256", lambda files, **kw:
                          "1080557adb04b83a22f3638b969a382377536655ef713b86288c25ee87583131"
                          if tuple(files) == cache.CONTROL_FILES else code_sha256(files, **kw))
            old_pack = original(life, worlds, baseline, tier, rel, row, spec, entries, common_pins)
        new_pack = original(life, worlds, path, tier, rel, row, spec, entries, common_pins)
        old_files = {p.relative_to(baseline).as_posix(): p.read_bytes()
                     for p in baseline.rglob("*") if p.is_file()}
        new_files = {p.relative_to(path).as_posix(): p.read_bytes()
                     for p in path.rglob("*") if p.is_file()}
        assert old_files.keys() == new_files.keys()
        different = sorted(p for p in old_files if old_files[p] != new_files[p])
        expected = ["sealed/controls.json", "sealed/pack.json"]
        if any(r["template_id"] == "keep-incidental" for r in records.values()):
            expected += ["sealed/build_log.json", "sealed/reader_keys.jsonl"]
        assert different == sorted(expected), (tier, rel, different)
        assert {k for k in old_pack[2] if old_pack[2][k] != new_pack[2][k]} == {
            "controls_sha256", "controls_key_sha256"}
        for arm in ("full_history", "no_memory", "oracle_evidence"):
            old_control = json.loads(old_files["sealed/controls.json"])["arms"][arm]
            new_control = json.loads(new_files["sealed/controls.json"])["arms"][arm]
            assert old_control["items"] == new_control["items"], (tier, rel, arm)
            assert old_control["bundles"] == new_control["bundles"], (tier, rel, arm)
        artifact_changes.setdefault(tier, {})[rel] = different
        assert before_worlds == {b: world_hash(db) for b, (db, _) in worlds.items()}
        return new_pack

    monkeypatch.setattr(build, "_prepare", audited)
    for tier in ("T0", "T1"):
        build.build_tier(tier, tmp_path, harness_artifacts=ARTIFACTS)
    assert set(seen) == set(changed) == {"T0", "T1"}
    assert len(seen["T0"]) > 2 and len(seen["T1"]) > 2
    (tmp_path / "key_changes.json").write_text(json.dumps(changed, sort_keys=True))
    print("PACK_ARTIFACT_CHANGES", json.dumps(artifact_changes, sort_keys=True))
