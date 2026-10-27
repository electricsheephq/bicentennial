"""Pack bytes, build gates and runner-sealed scoring acceptance."""

import ast
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack, closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.controls import cache
from bicentennial.genres.g1_software.world import GENERATOR_VERSION as G1_VERSION
from bicentennial.genres.g2_assistant.world import GENERATOR_VERSION as G2_VERSION
from bicentennial.items.bundle import compile_life
from bicentennial.items.compile import compile_branch
from bicentennial.keyed import mint_id, shuffle
from bicentennial.packs import build, scoring
from bicentennial.packs import manifest as mf
from bicentennial.sandbox.envserver.honeypot import plant
from bicentennial.score.check_selftest import score_plan
from bicentennial.score.qa import score_qa

ROOT = Path(__file__).resolve().parents[2]
A = [dict(name="hermes", version="test", sha256="a" * 64)]
CANARY = json.loads((SCHEMAS / "pack.schema.json").read_bytes())["properties"]["canary"]["enum"][0]


def catalogue():
    return build.load_catalogue(ROOT / "packs/catalogue-v0.toml",
                                c7_path=ROOT / "specs/ring0/c7-partial.json",
                                tier_path=ROOT / "tiers/life_specs/t0.toml")


def load(path):
    return json.loads(path.read_bytes())


def agent_copy(value):
    if isinstance(value, dict):
        return {k: agent_copy(v) for k, v in value.items() if k != "canary"}
    if isinstance(value, list):
        return [agent_copy(v) for v in value]
    return value


def audit_life(t, path, cases):
    """Compare packaged bytes with the still-available generator inputs."""
    compiled = t.twin.compiled
    expected = {r["item_id"] for r in compiled.records if r["bundle_id"] or r["branch"] == "B0"}
    assert {c.item["item_id"] for c in cases} == expected
    for source in t.out_dir.iterdir():
        if source.is_file() and not source.name.startswith("items."):
            assert (path / "sealed/life" / source.name).read_bytes() == source.read_bytes()
    for cut in t.twin.cuts:
        rows = [r for r in cut.rows if "agent" in r["audience"]]
        events = load(path / f"visible/events.{cut.branch}.json")["events"]
        assert events == [dict(event_id=r["event_id"], t_sim=r["t_sim"], kind="message",
                               actor=r["actor"], text=build.content(r)) for r in rows]
        assert all(CANARY not in e["text"] for e in events)
        assert load(path / f"sealed/life/items.{cut.branch}.json") == [
            c.item for c in cases if c.record["branch"] == cut.branch]
    pins = load(path / "manifest.json")["pins"]
    for name, field in (("environment_boundary_hash", "env_state_hash"),
                        ("repository_boundary_hash", "repo_tree_hash")):
        assert pins[name] == sha256_canon({t.life: {cut.branch: {
            str(s["index"]): s["expected_state"][field] for s in cut.sessions} for cut in t.twin.cuts}})
    if t.genre == "G1":
        for c in cases:
            for predicate, groups in (c.checks or {}).items():
                if predicate.startswith("changed:"):
                    assert groups and all(group for group in groups)
                    assert all(check.value != c.state0[check.path].get(check.name)
                               for group in groups for check in group)
    else:
        with ExitStack() as stack, pytest.MonkeyPatch.context() as mp:
            worlds = {b: (stack.enter_context(closing(build.open_world(
                t.out_dir / f"world.{b}.db", readonly=True))), cut)
                for b, cut in zip(("B0", "B1"), t.twin.cuts, strict=True)}
            # G1's helper is being compared only for history/later-mention rules;
            # its repository-only fields are deliberately not evaluated on G2.
            mp.setattr(build, "Case", SimpleNamespace)
            mp.setattr(build, "option_roles", lambda *a: {r["instance_key"]: {} for r in compiled.records})
            mp.setattr(build, "repo_checks", lambda *a: {r["instance_key"]: {} for r in compiled.records})
            mp.setattr(build, "repo_state", lambda *a: {})
            comparison = build.g1_cases(compiled, worlds, t.schedule,
                                        build._templates(t, compiled.records), life=t.life)
            assert [(c.item["item_id"], c.history, c.later_mention) for c in comparison] == [
                (c.item["item_id"], c.history, c.later_mention) for c in cases]


def audited_builder(original):
    def wrapped(t, path, **kwargs):
        result = original(t, path, **kwargs)
        audit_life(t, path, result[1])
        return result
    return wrapped


def test_one_pack(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "check_distribution", lambda packs, **kw:
                        SimpleNamespace(ok=True, to_obj=lambda: {}))
    row = catalogue().by_id()["g2-keep-incidental-mft-1"]
    result = build.build_tier("T0", tmp_path, harness_artifacts=A, rows=[row])
    assert len(result["index"]["packs"]) == 1


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("packs")
    observations = dict(packs=[], distribution=[], rows=[])
    check, distribution, generate = build.check_pack, build.check_distribution, build.generate

    def checked(cases):
        report = check(cases)
        observations["packs"].append(tuple(cases))
        if not report.ok:
            print("pack gate", [c.item["item_id"] for c in cases], report.failures)
        return report

    def distributed(packs, **kw):
        report = distribution(packs, **kw)
        observations["distribution"].append((packs, kw, report))
        if not report.ok:
            print("distribution gate", report.failures)
        return report

    def generated(row, **kw):
        observations["rows"].append(row.id)
        return generate(row, **kw)

    start = time.monotonic()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "check_pack", checked)
        mp.setattr(build, "check_distribution", distributed)
        mp.setattr(build, "generate", generated)
        mp.setattr(build, "_build_pack", audited_builder(build._build_pack))
        result = build.build_tier("T0", out, harness_artifacts=A)
    observations["seconds"] = time.monotonic() - start
    print("T0 packs", len(result["index"]["packs"]), "skipped", len(result["index"]["catalogue"]["skipped"]),
          "seconds", observations["seconds"])
    return out / "T0", result, observations


def test_t0_build(built):
    root, result, observed = built
    assert len(result["index"]["packs"]) == len([r for r in catalogue().rows if r.gate is None])
    assert len(observed["packs"]) == len(result["index"]["packs"])
    assert len(observed["distribution"]) == 1
    assert len(observed["distribution"][0][0]) == len(observed["packs"])
    assert root.is_dir()
    index = result["index"]
    assert index["catalogue"]["skipped"] == [dict(id=r.id, gate=r.gate) for r in catalogue().rows if r.gate]
    assert index["generator_versions"] == {"G1": G1_VERSION, "G2": G2_VERSION}
    assert index["generator_version"] == "+".join(sorted({G1_VERSION, G2_VERSION}))
    assert index["harness_artifacts"] == A
    assert index["pins"]["harness_pin"] == sha256_canon(A)
    assert index["seed_hash"] == sha256_canon(index["seeds_manifest"])
    assert index["seeds_manifest"] == build.seeds_manifest(dict(
        build.load_tier(ROOT / "tiers/life_specs/t0.toml"), seeds=list(catalogue().seeds())))
    assert index["rendered_history_set_hash"] == sha256_canon({
        rel: load(root / rel / "manifest.json")["pins"]["history_set_hash"] for rel in index["packs"]})


def test_t1_build(tmp_path, monkeypatch):
    calls = []
    distribution = build.check_distribution

    def distributed(packs, **kw):
        report = distribution(packs, **kw)
        calls.append((packs, kw, report))
        return report

    monkeypatch.setattr(build, "check_distribution", distributed)
    monkeypatch.setattr(build, "_build_pack", audited_builder(build._build_pack))
    result = build.build_tier("T1", tmp_path, harness_artifacts=A)
    index = result["index"]
    assert set(index["packs"]) == {"pack/G1/t1-g1/1", "pack/G2/t1-g2/2"}
    spec = build.load_tier(ROOT / "tiers/life_specs/t1.toml")
    assert index["not_exercised"] == sorted(spec["not_exercised"])
    assert index["seeds_manifest"]["seeds"] == [1, 2]
    assert "scripted_model" in index["labels"]
    assert len(calls) == 1 and len(calls[0][0]) == 2
    assert calls[0][1]["not_exercised"] == spec["not_exercised"]
    assert calls[0][2].ok
    assert calls[0][2].shares["Keep"]["restraint"].startswith("n/a:")
    assert "restraint:Keep" in calls[0][2].unmet
    for rel in index["packs"]:
        pack_dir = tmp_path / "T1" / rel
        pack = load(pack_dir / "sealed/pack.json")
        records = load(pack_dir / "sealed/records.json")
        assert {r["template_id"] for r in records} == set(spec["selection"][pack["genre"].lower()])
        assert not {i["cell_id"] for i in pack["items"]} & set(spec["not_exercised"])


def test_pack_layout_and_cache(built, tmp_path):
    root, result, observed = built
    rows = catalogue().by_id()
    stale = []
    for rel, identity in result["index"]["packs"].items():
        path = root / rel
        pack, meta = load(path / "sealed/pack.json"), load(path / "sealed/meta.json")
        manifest = load(path / "manifest.json")
        row = rows[meta["row"]["id"]]
        template = build.TEMPLATES_BY_GENRE[row.genre][row.template]
        assert rel == f"pack/{row.genre}/{row.track}/{template.template_id}@{template.version}/{row.lever_key}/{row.seed}"
        assert meta["row"]["baseline"] == row.baseline
        assert manifest["pack_id"] == pack["pack_id"] == mint_id(canon(["pack", "T0", rel]).decode(), 0)
        assert identity == dict(pack_id=pack["pack_id"], tree_sha256=mf.tree_sha256(path))
        validate("pack", pack)
        records = load(path / "sealed/records.json")
        assert records == sorted(records, key=lambda r: r["item_id"])
        assert all(r["bundle_id"] is not None or r["branch"] == "B0" for r in records)
        assert [i["item_id"] for i in pack["items"]] == sorted(r["item_id"] for r in records)
        assert pack["qa_order"] == sorted(i["item_id"] for i in pack["items"] if i["stage"] != "act")
        if not row.twin:
            assert len(pack["items"]) == len(pack["qa_order"]) == 1
            assert meta["singleton_lives"] == {pack["items"][0]["item_id"]: meta["life"]}
        key_bytes = (path / "sealed/reader_keys.jsonl").read_bytes()
        keys = [json.loads(line) for line in key_bytes.splitlines()]
        for key in keys:
            validate("reader_keys", key)
        assert key_bytes == b"".join(canon(k) + b"\n" for k in sorted(keys, key=lambda k: k["item_id"]))
        assert pack["hashes"]["reader_keys"] == sha256(key_bytes).hexdigest()
        inp = scoring.control_input(path)
        assert inp.pack["controls"] == {n: "not run in v0.1" for n in pack["controls"]}
        assert "controls" not in inp.pack["hashes"]
        entry = cache.read_entry(path / "sealed/controls.json", cache.cache_key(inp, harness_pin=sha256_canon(A)),
                                 expected_sha256=pack["hashes"]["controls"])
        assert entry is not None and entry["broken"] == []
        assert (path / "sealed/controls.json").read_bytes() == canon(entry)
        assert pack["controls"] == cache.pack_controls(entry)
        log = load(path / "sealed/build_log.json")
        fork_ids = {i for b in pack["bundles"] if b["twin_type"] == "fork" for i in b["items"]}
        stale.extend(r for r in log["competing"] if r["kind"] == "stale" and r["item_id"] in fork_ids)
        files = {p.relative_to(path).as_posix(): dict(sha256=sha256(p.read_bytes()).hexdigest(), size=p.stat().st_size)
                 for p in path.rglob("*") if p.is_file() and p != path / "manifest.json"}
        assert manifest["files"] == files
        assert manifest["visible"] == sorted(p for p in files if p.startswith("visible/"))
        assert manifest["sealed"] == sorted(p for p in files if p.startswith("sealed/"))
        assert set(manifest["pins"]["c7_entries"]) == {template.ref}
        assert manifest["pins"]["c7_entries"][template.ref] == build.c7_entries(
            ROOT / "specs/ring0/c7-partial.json")[template.ref]["entry_sha256"]
        labels = load(SCHEMAS / "card_ring0.schema.json")["properties"]["labels"]["properties"]
        assert manifest["labels"] == {k: v["enum"][0] for k, v in labels.items() if k != "scripted_model"}
        for file in path.rglob("*.json"):
            data = load(file)
            assert all(record["canary"] == CANARY for record in data) if isinstance(data, list) else data["canary"] == CANARY
        honeypot = load(path / manifest["honeypot"])
        honeypot_root = tmp_path / pack["pack_id"]
        honeypot_root.mkdir()
        _, token = plant(honeypot_root, canon(["honeypot", pack["pack_id"]]).decode())
        assert honeypot["reference_answer_token"] == meta["honeypot_token"] == token
        # X01/X02 strip metadata headers, including env-seed headers, when
        # materialising. No canary occurs outside those metadata fields.
        assert all(CANARY.encode() not in canon(agent_copy(load(p)))
                   for p in (path / "visible").iterdir())
    assert stale and all(r["score_milli"] == -1000 for r in stale)
    assert all(build.check_pack(cases).ok for cases in observed["packs"])


def test_scoring_roundtrip_and_replay(built, monkeypatch):
    root, result, observed = built
    original = {c.item["item_id"]: c for cases in observed["packs"] for c in cases}
    seen = set()
    for rel in result["index"]["packs"]:
        path = root / rel
        obj = load(path / "sealed/scoring.json")
        assert (path / "sealed/scoring.json").read_bytes() == canon(obj)
        assert obj["code_sha256"] == cache.code_sha256(scoring.SCORING_FILES)
        assert sha256_canon(obj) == load(path / "manifest.json")["pins"]["scoring_sha256"]
        score = scoring.make_score(obj)
        keys = {k["item_id"]: k for k in scoring.control_input(path).keys}
        for raw in obj["cases"]:
            case = scoring.case_from_obj(raw)
            assert case == original[case.item["item_id"]]
            assert scoring.case_from_obj(scoring.case_obj(case)) == case
            item = case.item
            key = keys[item["item_id"]]
            context = "\n".join(key["required"])
            reader_result = build.read(reader_view(item), key, context, mode="api")
            expected = (score_plan(case, list(reader_result.plan.steps)) if case.table else
                        score_qa(item, reader_result.envelope, evidence_texts=obj["evidence"][item["item_id"]]))
            assert score(item, reader_result) == expected
            seen.add("G1" if case.checks else "G2" if case.seed else "qa")
            with pytest.raises(ValueError, match=item["item_id"]):
                score(item, replace(reader_result, mode="hermes"))
        with pytest.raises(ValueError, match="unknown"):
            score(dict(item_id="unknown"), reader_result)
    assert seen == {"G1", "G2", "qa"}
    with pytest.raises(mf.PinnedArtifactChanged) as exc:
        scoring.make_score(dict(obj, code_sha256="0" * 64))
    assert exc.value.fields == ("scoring_code",)
    monkeypatch.setattr(scoring, "code_sha256", lambda *a: "0" * 64)
    with pytest.raises(mf.PinnedArtifactChanged):
        score(item, reader_result)


def test_determinism_random_hashseed(built, tmp_path):
    root, result, _ = built
    code = ("import json,sys; from bicentennial.packs.build import build_tier; "
            "print(json.dumps(build_tier('T0',sys.argv[1],harness_artifacts=" + repr(A) + ")))")
    child = subprocess.run([sys.executable, "-c", code, str(tmp_path)], cwd=ROOT,
                           env={**os.environ, "PYTHONHASHSEED": "random"}, capture_output=True, text=True, timeout=120)
    assert child.returncode == 0, child.stderr
    second = json.loads(child.stdout)
    assert second["pack_hash"] == result["pack_hash"]
    assert (tmp_path / "T0/index.json").read_bytes() == (root / "index.json").read_bytes()
    first_files = mf.file_manifest(root)
    assert mf.file_manifest(tmp_path / "T0") == first_files
    for rel in first_files:
        assert (root / rel).read_bytes() == (tmp_path / "T0" / rel).read_bytes(), rel


def test_visible_leaks(built):
    root, result, _ = built
    for rel in result["index"]["packs"]:
        path = root / rel
        pack = load(path / "sealed/pack.json")
        records = load(path / "sealed/records.json")
        keys = scoring.control_input(path).keys
        with ExitStack() as stack:
            worlds = {b: (stack.enter_context(closing(build.open_world(
                path / f"sealed/life/world.{b}.db", readonly=True))), None) for b in ("B0", "B1")}
            needles = build._needles(pack["items"], records, pack["bundles"], keys, worlds)
        visible = {p.relative_to(path).as_posix(): p.read_bytes() for p in (path / "visible").iterdir()}
        assert mf.leaks(visible, needles) == []
        target = "visible/events.B0.json"
        assert mf.leaks(dict(visible, **{target: visible[target] + pack["items"][0]["item_id"].encode()}),
                        needles) == [(target, "item_id")]
        assert (target, "reader_key") in mf.leaks(dict(visible, **{target: visible[target] + canon(keys[0])}), needles)


def report(ok):
    return SimpleNamespace(ok=ok, to_obj=lambda: {})


def assert_refusal(tmp_path, reason, rows=None):
    with pytest.raises(build.PackRefused) as exc:
        build.build_tier("T0", tmp_path, harness_artifacts=A,
                         rows=rows or [catalogue().by_id()["g2-keep-incidental-mft-1"]])
    assert exc.value.reason == str(exc.value) == reason
    assert all(not (tmp_path / name).exists() for name in ("T0", "T0.staging", "T0.work"))


@pytest.mark.parametrize("gate", ["check_pack", "check_distribution", "controls", "controls_broken"])
def test_gate_refusals(tmp_path, monkeypatch, gate):
    if gate == "controls_broken":
        monkeypatch.setattr(cache, "MIN_GAP_MILLI", 2001)
    elif gate == "controls":
        def broken(*a, **kw):
            raise ValueError("self_check")
        monkeypatch.setattr(build, "compute", broken)
    else:
        monkeypatch.setattr(build, gate, lambda *a, **kw: report(False))
    assert_refusal(tmp_path, gate)


def test_competing_context_refusal(tmp_path, monkeypatch):
    seen = []
    reader = build.read

    def read(view, key, ctx, **kw):
        assert ctx
        seen.append(key)
        return reader(view, key, ctx, **kw)

    monkeypatch.setattr(build, "read", read)
    monkeypatch.setattr(build, "make_score", lambda obj: lambda *a: SimpleNamespace(score_milli=0))
    assert_refusal(tmp_path, "competing_context", [catalogue().by_id()["g2-drift-booking-mft-1"]])
    assert seen and any(c["kind"] == "stale" for c in seen[0]["competing"])


def test_c7_refusal(tmp_path, monkeypatch):
    entries = build.c7_entries(ROOT / "specs/ring0/c7-partial.json")
    template = build.TEMPLATES_BY_GENRE["G2"]["keep-incidental"]
    entries[template.ref]["decision_tables"][0]["admissible"].append("holds:changed")
    copy_path = tmp_path / "c7.json"
    copy_path.write_bytes(canon(dict(entries=entries)))
    original = build.c7_entries
    # Only the per-pack gate reads the altered copy; the catalogue remains its
    # validated frozen input, so this exercises c7 rather than catalogue syntax.
    monkeypatch.setattr(build, "c7_entries", lambda path: original(copy_path))
    assert_refusal(tmp_path, "c7")


def test_abstention_only_refusal(tmp_path, monkeypatch):
    template = build.TEMPLATES_BY_GENRE["G2"]["recall-count"]
    generate = build.generate

    class Abstention(type(template)):
        def instances(self, db, schedule):
            return tuple(replace(i, options=(i.options[-1],), gold_spans=(),
                                 decisive_fact_id=None, never_observed=True)
                         for i in super().instances(db, schedule))

    def generated(*a, **kw):
        t = generate(*a, **kw)
        with ExitStack() as stack:
            branches = [compile_branch(stack.enter_context(closing(build.open_world(
                t.out_dir / f"world.{cut.branch}.db", readonly=True))), t.schedule, cut,
                (Abstention(**vars(template)),)) for cut in t.twin.cuts]
            compiled = compile_life(*branches)
        assert all(i["gold"]["never_observed"] for i in compiled.items)
        return replace(t, twin=replace(t.twin, compiled=compiled))

    monkeypatch.setattr(build, "generate", generated)
    assert_refusal(tmp_path, "abstention_only", [catalogue().by_id()["g2-recall-count-mft-1"]])


def test_leak_refusal(tmp_path, monkeypatch):
    projection = build.api_events
    generate = build.generate
    leaked = []

    def generated(*a, **kw):
        t = generate(*a, **kw)
        item = t.twin.compiled.items[0]
        leaked.append(canon(next(o for o in item["options"] if o["option_id"] == item["gold"]["option_id"])).decode())
        return t

    def project(cut):
        events = projection(cut)
        events[0]["text"] += leaked[0]
        return events

    monkeypatch.setattr(build, "generate", generated)
    monkeypatch.setattr(build, "api_events", project)
    assert_refusal(tmp_path, "leak")


@pytest.mark.parametrize("version", ["other-version", "", "invalid+version"])
def test_generator_version_refusal(tmp_path, monkeypatch, version):
    generate = build.generate
    calls = []

    def generated(*a, **kw):
        t = generate(*a, **kw)
        calls.append(t)
        return replace(t, manifest=dict(t.manifest, generator_version=version)) if len(calls) == 2 else t

    monkeypatch.setattr(build, "generate", generated)
    rows = [r for r in catalogue().rows if r.genre == "G1" and r.gate is None][:2]
    assert len(rows) == 2
    assert_refusal(tmp_path, "generator_version", rows)


def test_existing_output_and_placement_error(tmp_path, monkeypatch):
    dest = tmp_path / "T0"
    dest.mkdir()
    sentinel = dest / "keep"
    sentinel.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        build.build_tier("T0", tmp_path, harness_artifacts=A)
    assert sentinel.read_bytes() == b"original"
    from bicentennial.world.targeted import PlacementError
    error = PlacementError("placement")

    def fail(*a, **kw):
        raise error

    monkeypatch.setattr(build, "t1_lives", fail)
    with pytest.raises(PlacementError) as exc:
        build.build_tier("T1", tmp_path, harness_artifacts=A)
    assert exc.value is error
    assert not any((tmp_path / n).exists() for n in ("T1", "T1.staging", "T1.work"))


def test_tree_hash_and_leaks_properties(tmp_path):
    records = [(f"file-{i}", mint_id("pack-property", i).encode()) for i in range(12)]
    for seed in range(4):
        root = tmp_path / str(seed)
        root.mkdir()
        for name, value in shuffle(str(seed), ("pack",), 0, "files", records):
            (root / name).write_bytes(value)
        expected = sha256_canon([[n, len(v), sha256(v).hexdigest()] for n, v in sorted(records)])
        assert mf.tree_sha256(root) == expected
        (root / records[0][0]).chmod(0o444)
        assert mf.tree_sha256(root) == expected
        (root / records[0][0]).chmod(0o644)
        files = {n: v for n, v in records}
        needles = {"id": frozenset(v for _, v in records), "absent": frozenset({b"missing"})}
        assert mf.leaks(files, needles) == [(n, "id") for n, _ in sorted(records)]
    link = root / "link"
    link.symlink_to(root / records[0][0])
    with pytest.raises(ValueError, match="link"):
        mf.tree_sha256(root)
    link.unlink()
    os.mkfifo(root / "fifo")
    with pytest.raises(ValueError, match="fifo"):
        mf.tree_sha256(root)
    exc = mf.PinnedArtifactChanged(["z", "a"])
    assert exc.fields == ("a", "z") and str(exc) == "pinned_artifact_changed: a, z"


def test_manifest_import_boundary():
    tree = ast.parse((ROOT / "src/bicentennial/packs/manifest.py").read_bytes())
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert {n for n in imports if n.startswith("bicentennial")} == {
        "bicentennial.canon", "bicentennial.contracts.run"}
