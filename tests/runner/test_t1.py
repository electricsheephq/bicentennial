"""T1 acceptance over installed real lives and the offline Hermes worker."""

import ast
import json
import sys
import time
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.director.compiler.check import check_compile
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items.checks.env import steps
from bicentennial.items.checks.fixtures import execute, execute_repo
from bicentennial.items.protocol import CANARY
from bicentennial.keyed import choice
from bicentennial.packs.build import build_tier
from bicentennial.packs.install import install
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.probe.scripted_reader import read
from bicentennial.runner import t1
from bicentennial.runner.hermes_score import MISSING, Infra, score_item
from bicentennial.runner.life import STEP_S, LifeRun
from bicentennial.runner.lock import LockMismatch
from bicentennial.sandbox.envserver.state import State
from bicentennial.score.check_selftest import _score, score_plan
from bicentennial.score.invariants import GATED_T1, INVARIANTS
from bicentennial.score.qa import score_qa
from bicentennial.systems.registry import REGISTRY, SystemRefused, load
from bicentennial.world.db import open_world
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule

FAKE = Path(__file__).with_name("fake_life_worker.py")


def measured(name="hermes-native"):
    entry = load(REGISTRY / f"{name}.toml")
    for field in ("sha256",):
        if entry["artifact"][field] == "0" * 64:
            entry["artifact"][field] = "1" * 64
    entry["fresh_install_hash"] = "1" * 64
    return entry


def writable(root):
    for path in [root, *sorted(root.rglob("*"))]:
        path.chmod(path.stat().st_mode | 0o200)


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    root = tmp_path_factory.mktemp("t1-installed")
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    start = time.monotonic()
    build_tier("T1", root / "b", harness_artifacts=[artifact])
    print(f"T1 build_ms={int((time.monotonic() - start) * 1000)}", flush=True)
    start = time.monotonic()
    digest = install(root / "b/T1", root / "inst")
    print(f"T1 install_ms={int((time.monotonic() - start) * 1000)}", flush=True)
    timelines = {}
    index = json.loads((root / "inst/index.json").read_bytes())
    for rel in sorted(index["packs"]):
        life_dir = root / "inst" / rel / "sealed/life"
        life = json.loads((life_dir / "life.json").read_bytes())
        schedule = build_schedule(life["seed"], life["life"], named(life["scale"]))
        for b in ("B0", "B1"):
            db = open_world(life_dir / f"world.{b}.db", readonly=True)
            try:
                compiled = compile_script(life_dir, b, schedule, db,
                    items=json.loads((life_dir / f"items.{b}.json").read_bytes()), step_s=STEP_S)
            finally:
                db.close()
            path = root / f"timeline-{life['life']}-{b}.json"
            path.write_bytes(canon({t["user"]: [s["index"], t["n"], s["kind"]]
                for s in compiled.script["sessions"] for t in s["turns"]}))
            timelines[life["life"], b] = path

    def worker(life, branch, arm):
        return [sys.executable, str(FAKE), "--timeline", str(timelines[life, branch])]

    yield SimpleNamespace(root=root / "inst", digest=digest, worker=worker)
    writable(root / "inst")


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    monkeypatch.setattr(t1, "check_compile", lambda *a, **kw: {"ok": True})


def prepare(installed, **kwargs):
    return t1.prepare(**(dict(system="hermes-native", entry=measured(),
        packs=installed.root, pack_hash=installed.digest, worker_argv=installed.worker) | kwargs))


def test_fixture_and_pins(installed):
    ctx = prepare(installed)
    required = json.loads((SCHEMAS / "card_ring0.schema.json").read_bytes())["properties"]["pins"]["required"]
    assert set(ctx.pins) == set(required) - {"masks_hash"}
    assert ctx.roots == 2
    for pack in ctx.packs:
        actual = t1._boundaries((pack,))
        for name, digest in actual.items():
            assert digest == pack.manifest["pins"][name], (pack.rel, name, digest)
    assert len(ctx.packs) == 2
    assert ctx.current_lock() == ctx.lock


@pytest.mark.parametrize("system,code", [("nomemory", "unknown_system"), ("no-memory", "harness_not_hermes")])
def test_system_preflight(installed, monkeypatch, system, code):
    monkeypatch.setattr(adapter.HermesAdapter, "__init__", lambda *a, **kw: pytest.fail("adapter constructed"))
    with pytest.raises(t1.T1Refused) as caught:
        prepare(installed, system=system, entry=None)
    assert caught.value.code == code


def test_unmeasured_and_missing_input(installed, monkeypatch):
    monkeypatch.setattr(adapter.HermesAdapter, "__init__", lambda *a, **kw: pytest.fail("adapter constructed"))
    with pytest.raises(SystemRefused) as caught:
        prepare(installed, entry=None)
    assert any(r.startswith("unmeasured:") for r in caught.value.reasons)
    with pytest.raises(t1.T1Refused, match="missing_input"):
        prepare(installed, worker_argv=None)
    with pytest.raises(t1.T1Refused, match="missing_input"):
        prepare(installed, system="holographic", entry=measured("holographic"))


@pytest.mark.parametrize("code", ["tier", "harness_artifact_mismatch", "tier_composition", "c7_missing", "c7_changed"])
def test_pack_preflight(installed, monkeypatch, code):
    monkeypatch.setattr(adapter.HermesAdapter, "__init__", lambda *a, **kw: pytest.fail("adapter constructed"))
    if code in ("tier", "harness_artifact_mismatch", "tier_composition"):
        real = t1.verify

        def altered(*args, **kwargs):
            index = real(*args, **kwargs)
            if code == "tier":
                index["tier"] = "T0"
            elif code == "harness_artifact_mismatch":
                index["harness_artifacts"] = []
            else:
                index["packs"] = {}
            return index

        monkeypatch.setattr(t1, "verify", altered)
    elif code == "c7_missing":
        real = t1.c7_entries

        def missing(path):
            entries = real(path)
            entries.pop(next(iter(prepare_refs(installed))))
            return entries

        monkeypatch.setattr(t1, "c7_entries", missing)
    else:
        real = t1.c7.entry
        monkeypatch.setattr(t1.c7, "entry", lambda *a, **kw: real(*a, **kw) | {"entry_sha256": "f" * 64})
    with pytest.raises(t1.T1Refused) as caught:
        prepare(installed)
    assert caught.value.code == code


def prepare_refs(installed):
    index = json.loads((installed.root / "index.json").read_bytes())
    records = json.loads((installed.root / sorted(index["packs"])[0] / "sealed/records.json").read_bytes())
    return sorted({f"{r['template_id']}-v{r['template_version']}" for r in records})


def test_marker(installed, monkeypatch):
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", "printf '{}'; exit 11")
    with pytest.raises(t1.T1Refused, match="machine guard refused: marker exit 11"):
        prepare(installed)
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", "printf '{}'; exit 10")
    assert prepare(installed).roots == 1


def test_tamper(installed, monkeypatch):
    path = installed.root / "index.json"
    original = path.read_bytes()
    try:
        path.chmod(0o644)
        path.write_bytes(original + b" ")
        with pytest.raises(PinnedArtifactChanged):
            prepare(installed)
    finally:
        path.write_bytes(original)
        path.chmod(0o444)


def test_t0_install_is_refused(tmp_path, monkeypatch):
    from bicentennial.packs import build

    # X01/G19 precedent: a one-row T0 fixture cannot meet tier-wide shares.
    monkeypatch.setattr(build, "check_distribution", lambda *a, **kw:
        SimpleNamespace(ok=True, to_obj=lambda: {}))
    catalogue = build.load_catalogue(t1.REPO / "packs/catalogue-v0.toml",
        c7_path=t1.REPO / "specs/ring0/c7-partial.json",
        tier_path=t1.REPO / "tiers/life_specs/t0.toml")
    row = catalogue.by_id()["g2-keep-incidental-mft-1"]
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    build_tier("T0", tmp_path / "b", harness_artifacts=[artifact], rows=[row])
    root = tmp_path / "inst"
    digest = install(tmp_path / "b/T0", root)
    try:
        with pytest.raises(t1.T1Refused, match="tier"):
            t1.prepare(system="hermes-native", entry=measured(), packs=root,
                pack_hash=digest, worker_argv=[sys.executable, str(FAKE)])
    finally:
        writable(root)


def test_schedule_and_commit_refusals(installed, monkeypatch):
    real = t1._json

    def wrong_schedule(path):
        obj = real(path)
        return obj | {"schedule_sha256": "f" * 64} if path.name == "history.B0.json" else obj

    with monkeypatch.context() as patch:
        patch.setattr(t1, "_json", wrong_schedule)
        with pytest.raises(t1.T1Refused, match="schedule_mismatch"):
            prepare(installed)
    monkeypatch.setattr(t1.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout="not-a-commit"))
    with pytest.raises(t1.T1Refused, match="benchmark_commit"):
        prepare(installed)


def test_scratch_and_compile_refusals(installed, tmp_path, monkeypatch):
    ctx = prepare(installed)
    monkeypatch.setattr(t1, "run_life", lambda **kw: pytest.fail("arm started"))
    with pytest.raises(t1.T1Refused, match="scratch_exists"):
        t1.run_arms(ctx, scratch=tmp_path)
    monkeypatch.setattr(t1, "check_compile", lambda *a, **kw: dict(ok=False, branches={
        "B1": dict(calls=1, mismatches=[{}]), "B0": dict(calls=1, mismatches=[])}))
    scratch = tmp_path / "failed"
    with pytest.raises(t1.T1Refused) as caught:
        t1.run_arms(ctx, scratch=scratch)
    assert caught.value.code == "check_compile" and caught.value.fields == ("B1",)
    assert not scratch.exists()


def test_firewall():
    source = Path(t1.__file__).read_text()
    allowed = {"json", "subprocess", "hashlib", "dataclasses", "pathlib", "concurrent"}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module]
            for name in names:
                assert name.split(".")[0] in allowed or name.startswith("bicentennial.")
                assert "director.upstream" not in name
        if isinstance(node, ast.Name):
            assert "l" + "cm" not in node.id.lower()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "l" + "cm" not in node.value.lower()
    assert "os.environ" not in source and "os.getenv" not in source
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            assert not isinstance(node.value, (ast.Dict, ast.Set, ast.List))


def projection(run):
    return canon({a: [r.outcomes, r.bundles, [v.to_obj() for v in r.verdicts or ()]]
        for a, r in run.arms.items()})


def action_score(case, ev):
    if case.seed is None:
        return _score(case, [], ev)[0]
    state = State(case.seed)
    for row in ev["records"]:
        if row["type"] == "action" and row["ok"] is True and row["state_changed"]:
            state.call(row["tool"], row["args"])
    return _score(case, ev["records"], state.state)[0]


@pytest.fixture(scope="module")
def completed(installed, tmp_path_factory):
    root = tmp_path_factory.mktemp("t1-runs")
    patch = pytest.MonkeyPatch()
    patch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    patch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    patch.setattr(adapter, "assert_niced", lambda pid: None)
    ctx, calls, cleaned, checks, expected = prepare(installed), [], [], [], {}
    real, cleanup = t1.run_life, LifeRun.cleanup
    cache = {}
    by_life = {p.life: p for p in ctx.packs}

    def compile_spy(life_dir, **kw):
        assert kw["entry"]["name"] == "hermes-native"
        assert kw["route_table"] == t1._routes("hermes-native")
        assert kw["step_s"] == STEP_S and kw["harness_pin"] == ctx.harness_pin
        checks.append(life_dir)
        return {"ok": True}

    def drive(**kw):
        life = json.loads((kw["life_dir"] / "life.json").read_bytes())["life"]
        key = (life, kw["arm"], kw["branch"])
        calls.append((*key, kw["attempt"]))
        assert list(kw["visible"]) == ["answer_key.json"]
        assert CANARY.encode() not in kw["visible"]["answer_key.json"]
        assert kw["honeypot_token"] == by_life[life].meta["honeypot_token"]
        start = time.monotonic()
        try:
            run = real(**kw)
        finally:
            print(f"run_life {key} a{kw['attempt']} wall_ms={int((time.monotonic() - start) * 1000)}", flush=True)
        assert run.stopped is None, (key, run.stopped, run.audit)
        cache[key] = run
        for item in kw["items"]:
            iid = item["item_id"]
            pack = by_life[life]
            expected[kw["arm"], iid] = (action_score(pack.cases[iid], run.act[iid])
                if item["stage"] == "act" else score_qa(item, run.envelopes[iid],
                    evidence_texts=pack.scoring["evidence"][iid]))
        return run

    def finish(run):
        cleaned.append(run)
        cleanup(run)

    patch.setattr(t1, "check_compile", compile_spy)
    patch.setattr(t1, "run_life", drive)
    patch.setattr(LifeRun, "cleanup", finish)
    try:
        first = t1.run_arms(ctx, scratch=root / "one")
        assert len(cleaned) == 12 and len({id(r) for r in cleaned}) == 12
        assert len(checks) == 2
        assert not (root / "one").exists()
        # Check stop conditions before spending a second full run.
        system = {v.invariant: v.status for v in first.arms["system"].verdicts}
        assert all(system[n] == "PASS" for n in GATED_T1), system
        wiped = first.arms["wiped"]
        assert any(v.status == "FAIL" for v in wiped.verdicts)
        for p in ctx.packs:
            assert any(wiped.outcomes[i["item_id"]]["stage_attribution"] == "retained"
                for i in p.pack["items"]), (p.life, wiped.outcomes)
        second = t1.run_arms(ctx, scratch=root / "two")
        if projection(first) != projection(second):
            different = next((a, iid) for a in first.arms for iid in first.arms[a].outcomes
                if first.arms[a].outcomes[iid] != second.arms[a].outcomes[iid])
            pytest.fail(f"determinism first differing item={different}")
        assert len(cleaned) == 24 and len({id(r) for r in cleaned}) == 24
        assert len(checks) == 4
        assert not list(root.rglob("a[0-9]*"))
        print(f"T1 deterministic_sha256={sha256(projection(first)).hexdigest()}", flush=True)
        yield SimpleNamespace(ctx=ctx, first=first, cache=cache, calls=calls[:12], expected=expected)
    finally:
        patch.undo()


def test_full_run(completed):
    ctx, run = completed.ctx, completed.first
    expected_calls = [(p.life, a, b, 0) for p in ctx.packs for a in t1.UNIT_ORDER for b in ("B0", "B1")]
    # Branches execute concurrently; collection, unit order and attempts are fixed.
    for offset in range(0, 12, 2):
        assert sorted(completed.calls[offset:offset + 2]) == sorted(expected_calls[offset:offset + 2])
    all_ids = {i["item_id"] for p in ctx.packs for i in p.pack["items"]}
    bundle_ids = {b["bundle_id"] for p in ctx.packs for b in p.pack["bundles"]}
    assert run.crossing and set(run.crossing) <= bundle_ids
    assert run.singleton_lives == {i: v for p in ctx.packs for i, v in p.meta["singleton_lives"].items()}
    assert set(run.duty_items) == {i for p in ctx.packs for i in p.meta["duty_items"]}
    assert run.not_exercised == tuple(ctx.index["not_exercised"])
    for arm, result in run.arms.items():
        assert set(result.outcomes) == all_ids
        assert {b["bundle_id"] for b in result.bundles} == bundle_ids
        assert result.voids["voided"] == 0 and result.voids["checked"] == len(all_ids)
        for iid, value in result.outcomes.items():
            validate("item_outcome", value)
            score = completed.expected[arm, iid]
            if value["stage"] == "act":
                assert {k: value[k] for k in asdict(score)} == asdict(score)
            else:
                assert value["score_milli"] == score.score_milli
        for value in result.bundles:
            validate("bundle_outcome", value)
        assert result.honeypot_hits == 0
    system = run.arms["system"]
    assert tuple(v.invariant for v in system.verdicts) == INVARIANTS
    statuses = {v.invariant: v.status for v in system.verdicts}
    assert all(statuses[n] == "PASS" for n in GATED_T1)
    assert statuses["INV-FORGET"] == "NOT_EXERCISED"
    assert system.transforms == () and True in system.recall
    wiped = {v.invariant: v.status for v in run.arms["wiped"].verdicts}
    assert wiped["INV-VERB"] == wiped["INV-PAIR"] == "FAIL"
    assert run.arms["no_memory"].verdicts is None
    assert not any(r.in_context is True for u in run.arms["no_memory"].units for r in u.runs[-1].results.values())


@pytest.fixture(scope="module")
def policy(installed):
    """Pure executed evidence for policy tests, independent of sandbox admission.

    This never substitutes for the full fake-worker acceptance fixture.
    """
    ctx, cache = prepare(installed), {}
    for pack in ctx.packs:
        for arm in t1.UNIT_ORDER:
            for b in ("B0", "B1"):
                results, envelopes, act = {}, {}, {}
                for item in pack.items[b]:
                    iid, case = item["item_id"], pack.cases[item["item_id"]]
                    context = "\n".join(pack.keys[iid]["required"]) if arm == "system" else ""
                    result = results[iid] = read(reader_view(item), pack.keys[iid], context, mode="hermes")
                    if item["stage"] != "act":
                        envelopes[iid] = result.envelope
                    elif pack.genre == "G1":
                        act[iid] = execute_repo(case.state0, list(result.plan.steps))
                    else:
                        rows, _ = execute(case.seed, steps({"plan": {"steps": list(result.plan.steps)}}), t_sim=case.t_sim)
                        act[iid] = {"records": list(rows)}
                cache[pack.life, arm, b] = LifeRun(arm, pack.life, b, 0,
                    results=results, envelopes=envelopes, act=act, audit={"status": "OK", "failures": []})
    return SimpleNamespace(ctx=ctx, cache=cache)


@pytest.fixture
def replay(policy, monkeypatch, tmp_path):
    calls, cleaned, voids = [], [], {}

    def drive(**kw):
        life = json.loads((kw["life_dir"] / "life.json").read_bytes())["life"]
        key = life, kw["arm"], kw["branch"]
        pack = next(p for p in policy.ctx.packs if p.life == life)
        assert list(kw["visible"]) == ["answer_key.json"]
        assert CANARY.encode() not in kw["visible"]["answer_key.json"]
        assert kw["honeypot_token"] == pack.meta["honeypot_token"]
        if kw["arm"] == "no_memory":
            assert kw["plugin_source"] is None
        calls.append((*key, kw["attempt"]))
        if kw["arm"] in voids:
            assert kw["voids"] is voids[kw["arm"]]
        voids[kw["arm"]] = kw["voids"]
        kw["gate"].start_session(kw["current_lock"](), kw["arm"], life, kw["branch"], 1, kw["attempt"])
        for item in kw["items"]:
            if (item["item_id"], kw["arm"]) not in kw["voids"].records:
                kw["voids"].record(item["item_id"], kw["arm"], True)
        return replace(policy.cache[key], attempt=kw["attempt"], stored_roots={}, retained_roots={}, _root=None)

    monkeypatch.setattr(LifeRun, "cleanup", lambda r: cleaned.append(r))

    def run(mutate=lambda r: r, ctx=None):
        calls.clear()
        cleaned.clear()
        voids.clear()
        monkeypatch.setattr(t1, "run_life", lambda **kw: mutate(drive(**kw)))
        scratch = tmp_path / "run"
        try:
            return t1.run_arms(ctx or policy.ctx, scratch=scratch)
        finally:
            assert not scratch.exists()
            assert len(cleaned) == len(calls)
            assert len({id(r) for r in cleaned}) == len(cleaned)

    return SimpleNamespace(run=run, calls=calls, cleaned=cleaned)


@pytest.mark.parametrize("persistent", [False, True])
def test_infra_reruns(policy, replay, persistent):
    pack = policy.ctx.packs[0]
    iid = pack.items["B0"][0]["item_id"]

    def mutate(run):
        if (run.life, run.arm, run.branch) == (pack.life, "system", "B0") and (persistent or run.attempt == 0):
            return replace(run, classes=run.classes | {iid: ("INFRA_FAILURE", "void")})
        return run

    result = replay.run(mutate)
    unit = next(u for u in result.arms["system"].units if (u.life, u.branch) == (pack.life, "B0"))
    assert [r.attempt for r in unit.runs] == ([0, 1, 2] if persistent else [0, 1])
    assert len([c for c in replay.calls if c[:3] == (pack.life, "system", "B0")]) == (3 if persistent else 2)
    assert all(result.arms["system"].outcomes[i["item_id"]]["infra_reruns"] == (2 if persistent else 1)
        for i in pack.items["B0"])
    if persistent:
        assert result.arms["system"].outcomes[iid]["failure_class"] == "BLOCKED"
        assert result.arms["system"].labels[iid] == ("INFRA_FAILURE", "void")


@pytest.mark.parametrize("audit_failure", [False, True])
def test_system_class_precedes_reader_and_audit(policy, replay, audit_failure):
    pack = policy.ctx.packs[0]
    item = next(i for i in pack.items["B0"] if t1._crosses(pack, i))
    iid = item["item_id"]

    def mutate(run):
        if (run.life, run.arm, run.branch) == (pack.life, "system", "B0"):
            assert iid in run.results
            return replace(run, classes={iid: ("SYSTEM_FAILURE", "unsettled")},
                audit={"status": "INFRA_FAILURE", "failures": ["A1.x"]} if audit_failure else run.audit)
        return run

    arm = replay.run(mutate).arms["system"]
    assert arm.outcomes[iid]["failure_class"] == "SYSTEM_FAILURE"
    assert arm.outcomes[iid]["score_milli"] == 0
    if audit_failure:
        assert all(arm.outcomes[i["item_id"]]["failure_class"] == "BLOCKED" for i in pack.items["B0"] if i != item)
    assert arm.labels[iid] == ("SYSTEM_FAILURE", "unsettled")
    unit = next(u for u in arm.units if (u.life, u.branch) == (pack.life, "B0"))
    assert len(unit.runs) == (3 if audit_failure else 1)
    if audit_failure:
        assert unit.runs[-1].audit["failures"] == ["A1.x"]


@pytest.mark.parametrize("field,label", [("envelopes", "no_final"), ("act", "no_act"), ("results", "no_result")])
def test_missing(policy, replay, field, label):
    pack = policy.ctx.packs[0]
    item = next(i for i in pack.items["B0"] if (i["stage"] == "act") == (field == "act"))
    iid = item["item_id"]

    def mutate(run):
        if (run.life, run.arm, run.branch) == (pack.life, "system", "B0"):
            return replace(run, **{field: {i: v for i, v in getattr(run, field).items() if i != iid}})
        return run

    arm = replay.run(mutate).arms["system"]
    assert arm.labels[iid] == ("INFRA_FAILURE", label)
    assert arm.outcomes[iid]["failure_class"] == "BLOCKED"


@pytest.mark.parametrize("name,same,reruns", [("holographic", True, 2), ("holographic", False, 0),
                                           ("hermes-native", True, 0)])
@pytest.mark.parametrize("label", t1.RELABEL)
def test_plugin_reclassification(policy, replay, name, same, reruns, label):
    ctx = replace(policy.ctx, entry=measured(name), plugin_source="test-only")
    pack = ctx.packs[0]
    iid = pack.items["B0"][0]["item_id"]

    def mutate(run):
        if run.life == pack.life and run.branch == "B0" and run.arm in ("system", "no_memory"):
            session = 21 if run.arm == "system" or same else 22
            return replace(run, classes={iid: ("SYSTEM_FAILURE", label)}, stopped=("SYSTEM_FAILURE", label, session))
        return run

    arm = replay.run(mutate, ctx).arms["system"]
    unit = next(u for u in arm.units if (u.life, u.branch) == (pack.life, "B0"))
    assert len(unit.runs) == reruns + 1
    assert unit.reclassified == ((iid,) if reruns else ())
    assert arm.outcomes[iid]["failure_class"] == ("BLOCKED" if reruns else "SYSTEM_FAILURE")


@pytest.mark.parametrize("genre", ["G1", "G2"])
def test_executed_evidence_not_gold_plan(policy, replay, genre):
    pack = next(p for p in policy.ctx.packs if p.genre == genre)
    item = next(i for i in pack.items["B0"] if i["stage"] == "act" and pack.cases[i["item_id"]].table["gold"] == "act")
    iid, case = item["item_id"], pack.cases[item["item_id"]]
    ev = case.state0 if genre == "G1" else {"records": []}

    def mutate(run):
        if (run.life, run.arm, run.branch) == (pack.life, "system", "B0"):
            assert run.results[iid].selected_option == item["gold"]["option_id"]
            return replace(run, act=run.act | {iid: ev})
        return run

    value = replay.run(mutate).arms["system"].outcomes[iid]
    expected = action_score(case, ev)
    assert {k: value[k] for k in asdict(expected)} == asdict(expected)
    gold = next(o for o in item["options"] if o["option_id"] == item["gold"]["option_id"])
    assert expected != score_plan(case, gold["plan"]["steps"])


def test_present_none_envelope_and_transforms(policy, replay):
    pack = policy.ctx.packs[0]
    item = next(i for i in pack.items["B0"] if i["stage"] != "act")
    iid = item["item_id"]

    def mutate(run):
        if (run.life, run.arm, run.branch) == (pack.life, "system", "B0"):
            return replace(run, envelopes=run.envelopes | {iid: None}, transforms=(iid,))
        return run

    arm = replay.run(mutate).arms["system"]
    assert arm.outcomes[iid]["score_milli"] == score_qa(item, None, evidence_texts=pack.scoring["evidence"][iid]).score_milli
    assert arm.outcomes[iid]["failure_class"] != "BLOCKED"
    assert arm.transforms == (iid,)


def test_lock_and_gate_refusals(policy, tmp_path, monkeypatch):
    ctx, calls = policy.ctx, []

    monkeypatch.setattr(t1, "_commit", lambda: ctx.lock["benchmark_commit"] if not calls else "f" * 40)

    def drive(**kw):
        kw["gate"].start_session(kw["current_lock"](), kw["arm"], "test", kw["branch"], 1, 0)
        calls.append(kw["branch"])
        return LifeRun(kw["arm"], ctx.packs[0].life, kw["branch"], 0,
            classes={i["item_id"]: ("SYSTEM_FAILURE", "turn_failed") for i in kw["items"]})

    monkeypatch.setattr(t1, "run_life", drive)
    with pytest.raises(LockMismatch) as caught:
        t1.run_arms(replace(ctx, roots=1), scratch=tmp_path / "lock")
    assert caught.value.fields == ("analysis_commit", "benchmark_commit", "director_commit")
    assert calls == ["B0"] and not (tmp_path / "lock").exists()
    error = GateRefused("test")

    def refuse(**kw):
        (kw["scratch"] / "orphan/a0").mkdir(parents=True, exist_ok=True)
        raise error

    monkeypatch.setattr(t1, "run_life", refuse)
    with pytest.raises(GateRefused) as caught:
        t1.run_arms(ctx, scratch=tmp_path / "gate")
    assert caught.value is error and not (tmp_path / "gate").exists()


def test_real_compile_once(policy, tmp_path):
    ctx, pack = policy.ctx, policy.ctx.packs[0]
    result = check_compile(pack.life_dir, entry=load(REGISTRY / "hermes-native.toml"),
        route_table=t1._routes("hermes-native"), harness_pin=ctx.harness_pin, checkout=None,
        scratch=tmp_path / "check", step_s=STEP_S,
        worker_argv=ctx.worker_argv(pack.life, "B0", "check_compile"))
    counts = {b: len(v["mismatches"]) for b, v in result["branches"].items()}
    print(f"real check_compile ok={result['ok']} mismatches={counts}", flush=True)
    assert set(result["branches"]) == {"B0", "B1"}


def test_shared_infra_and_system_precedence():
    # No reader, envelope, action or case is inspected for a preclassified item.
    item = dict(item_id="unit", cell_id="WAKE-VERB", stage="remember", track="Wake")
    args = dict(result=MISSING, envelope=MISSING, act=MISSING, case=None,
        scoring_evidence=None, keys=None, stored_roots=None, retained_roots=None, attempt=0)
    assert score_item(item, cls="INFRA_FAILURE", label="void", **args) == Infra("void")
    value = score_item(item, cls="SYSTEM_FAILURE", label="unsettled", **args)
    assert value["failure_class"] == "SYSTEM_FAILURE" and value["score_milli"] == 0


def test_no_floats_or_unsorted_output_dicts(policy, replay):
    def walk(value):
        assert not isinstance(value, float)
        if isinstance(value, dict):
            assert list(value) == sorted(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                walk(child)

    result = replay.run()
    for arm in result.arms.values():
        walk(arm.outcomes)
        walk(arm.bundles)
        walk(arm.labels)
        walk(arm.voids)
    walk(policy.ctx.pins)


def test_seeded_executed_scoring(policy):
    """K10 draws select alternative executed plans, independent of reader gold."""
    for pack in policy.ctx.packs:
        for item in pack.pack["items"]:
            iid, case = item["item_id"], pack.cases[item["item_id"]]
            run = policy.cache[pack.life, "system", pack.records[iid]["branch"]]
            for attempt in range(3):
                ev = run.act.get(iid, MISSING)
                if item["stage"] == "act":
                    option = choice("t1-score", (iid,), attempt, "executed-option", item["options"])
                    if pack.genre == "G1":
                        ev = execute_repo(case.state0, option["plan"]["steps"])
                    else:
                        rows, _ = execute(case.seed, steps(option), t_sim=case.t_sim)
                        ev = {"records": list(rows)}
                value = score_item(item, cls=None, label=None, result=run.results[iid],
                    envelope=run.envelopes.get(iid, MISSING), act=ev, case=case,
                    scoring_evidence=pack.scoring["evidence"].get(iid), keys=pack.keys[iid],
                    stored_roots=None, retained_roots=None, attempt=attempt)
                expected = (action_score(case, ev) if item["stage"] == "act" else
                    score_qa(item, run.envelopes[iid], evidence_texts=pack.scoring["evidence"][iid]))
                assert value["score_milli"] == expected.score_milli
                if item["stage"] == "act":
                    assert {k: value[k] for k in asdict(expected)} == asdict(expected)


@pytest.mark.parametrize("has_reader", [False, True])
def test_recall_with_system_failure(policy, replay, has_reader):
    pack = policy.ctx.packs[0]
    item = next(i for i in pack.items["B0"] if t1._crosses(pack, i)
        and policy.cache[pack.life, "system", "B0"].results[i["item_id"]].in_context is True)
    iid = item["item_id"]

    def mutate(run):
        if (run.life, run.arm, run.branch) != (pack.life, "system", "B0"):
            return run
        results = run.results if has_reader else {i: v for i, v in run.results.items() if i != iid}
        return replace(run, results=results, classes={iid: ("SYSTEM_FAILURE", "unsettled")})

    arm = replay.run(mutate).arms["system"]
    expected = {}
    for p in policy.ctx.packs:
        for i in p.pack["items"]:
            if t1._crosses(p, i):
                key = i["item_id"]
                result = policy.cache[p.life, "system", p.records[key]["branch"]].results[key]
                expected[key] = has_reader if key == iid else result.in_context is True
    assert arm.recall == tuple(expected[key] for key in sorted(expected))
    assert arm.outcomes[iid]["failure_class"] == "SYSTEM_FAILURE"


@pytest.mark.parametrize("genre", ["G1", "G2"])
@pytest.mark.parametrize("error", [ValueError, TypeError])
def test_act_state_infrastructure(policy, replay, monkeypatch, genre, error):
    from bicentennial.runner import hermes_score

    pack = next(p for p in policy.ctx.packs if p.genre == genre)
    iid = next(i["item_id"] for i in pack.items["B0"] if i["stage"] == "act")
    original = hermes_score.score_action

    def bad_state(item, *args, **kwargs):
        if item["item_id"] == iid:
            raise error("benchmark-owned state")
        return original(item, *args, **kwargs)

    monkeypatch.setattr(hermes_score, "score_action", bad_state)
    arm = replay.run().arms["system"]
    assert arm.labels[iid] == ("INFRA_FAILURE", "act_state")
    assert arm.outcomes[iid]["failure_class"] == "BLOCKED"


@pytest.mark.parametrize("kind", t1.REFUSALS)
def test_scoring_refusals_are_not_act_state(policy, monkeypatch, kind):
    from bicentennial.runner import hermes_score

    pack = policy.ctx.packs[0]
    item = next(i for i in pack.items["B0"] if i["stage"] == "act")
    iid = item["item_id"]
    run = policy.cache[pack.life, "system", "B0"]
    error = kind(["test"]) if kind in (SystemRefused, PinnedArtifactChanged, LockMismatch) else kind("test")

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(hermes_score, "score_action", refuse)
    with pytest.raises(kind) as caught:
        score_item(item, cls=None, label=None, result=run.results[iid], envelope=MISSING,
            act=run.act[iid], case=pack.cases[iid], scoring_evidence=None, keys=pack.keys[iid],
            stored_roots=None, retained_roots=None, attempt=0)
    assert caught.value is error
