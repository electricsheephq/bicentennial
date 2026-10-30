"""Offline T0 acceptance over installed public micro packs."""

import ast
import json
import os
import runpy
import shutil
import stat
import subprocess
import sys
import time
import unicodedata
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.harness import egress
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.keyed import uniform_int
from bicentennial.packs import build
from bicentennial.packs.catalogue import load_catalogue
from bicentennial.packs.install import install
from bicentennial.runner import t0
from bicentennial.score.invariants import SystemFault, Verdict, adapter_invariants
from bicentennial.systems.registry import REGISTRY, ZERO_HASH, load

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module", autouse=True)
def synthetic_egress():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(egress, "_out", lambda argv: "8" if argv[:3] == ["ps", "-o", "rss="] else "")
        yield


def test_commit_ignores_git_location_variables(git_checkouts, monkeypatch):
    monkeypatch.setattr(t0, "REPO", git_checkouts.checkout)
    clean = t0._commit()
    assert clean == git_checkouts.head
    assert clean != git_checkouts.other_head
    for name, value in git_checkouts.conflict.items():
        monkeypatch.setenv(name, value)
    assert t0._commit() == clean


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    root = tmp_path_factory.mktemp("t0-installed")
    catalogue = load_catalogue(ROOT / "packs/catalogue-v0.toml",
        c7_path=ROOT / "specs/ring0/c7-partial.json", tier_path=ROOT / "tiers/life_specs/t0.toml")
    rows = catalogue.by_id()
    names = ["g2-keep-incidental-mft-1", "g2-drift-booking-mft-1", "g2-keep-forget-mft-1",
             "g2-recall-count-mft-1", "g2-drift-asof-dir-2", "g1-recall-value-mft-1"]
    names.append(rows["g2-drift-asof-dir-2"].baseline)
    start = time.monotonic_ns()
    try:
        with pytest.MonkeyPatch.context() as patch:
            # A11: small-row fixtures cannot satisfy the tier-wide shares.
            # Follow G19's test-local stub; production distribution gates stay intact.
            patch.setattr(build, "check_distribution", lambda packs, **kwargs:
                          SimpleNamespace(ok=True, to_obj=lambda: {}))
            built = build.build_tier("T0", root / "build", harness_artifacts=[
                load(REGISTRY / "hermes-native.toml")["artifact"]], rows=[rows[n] for n in names])
    finally:
        print(f"fixture build_attempt_ms={(time.monotonic_ns() - start) // 1_000_000}")
    built_ms = (time.monotonic_ns() - start) // 1_000_000
    start = time.monotonic_ns()
    digest = install(root / "build/T0", root / "installed")
    print(f"fixture build_ms={built_ms} install_ms={(time.monotonic_ns() - start) // 1_000_000}")
    assert digest == built["pack_hash"]
    try:
        yield root / "installed", built["index"], digest
    finally:
        for path in [root / "installed", *sorted((root / "installed").rglob("*"))]:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)


def packs(installed):
    root, index, _ = installed
    return [t0._Pack(root, rel) for rel in sorted(index["packs"])]


def snapshotter(root):
    count = 0

    def snapshot(adapter):
        nonlocal count
        path = root / str(count)
        count += 1
        path.mkdir(parents=True)
        (path / "checkpoint.bin").write_bytes(adapter.checkpoint())
        return (path,)
    return snapshot


def test_installed_reference_branch_drives(installed, tmp_path):
    for pack in packs(installed):
        start = time.monotonic_ns()
        for branch in ("B0", "B1"):
            results, outcomes, roots = t0.drive_branch(pack, branch, ReferenceStore,
                bound_s=t0.REFERENCE_BOUND_S, snapshot=snapshotter(tmp_path / pack.pack["pack_id"] / branch))
            expected = {i["item_id"] for i in pack.pack["items"]
                        if pack.records[i["item_id"]]["branch"] == branch}
            assert set(results) == set(outcomes) == expected
            assert all(r["failure_class"] != "SYSTEM_FAILURE" for r in outcomes.values())
            assert bool(roots) == bool(expected)
            assert canon(list(outcomes.values()))
        elapsed_ms = (time.monotonic_ns() - start) // 1_000_000
        print(f"{pack.meta['row']['id']} branch_drive_ms={elapsed_ms}")
        assert elapsed_ms < 60_000


def test_reference_no_update_kill_packs(tmp_path, monkeypatch):
    catalogue = load_catalogue(ROOT / "packs/catalogue-v0.toml",
        c7_path=ROOT / "specs/ring0/c7-partial.json", tier_path=ROOT / "tiers/life_specs/t0.toml")
    rows = catalogue.by_id()
    names = ["g1-drift-quote-dir-2", "g2-drift-no-update-dir-2"]
    names += [rows[n].baseline for n in names]
    # As in installed(), a row subset cannot satisfy the tier-wide shares.
    monkeypatch.setattr(build, "check_distribution", lambda packs, **kwargs:
                        SimpleNamespace(ok=True, to_obj=lambda: {}))
    built = build.build_tier("T0", tmp_path / "build", harness_artifacts=[
        load(REGISTRY / "hermes-native.toml")["artifact"]], rows=[rows[n] for n in names])
    destination = tmp_path / "installed"
    digest = install(tmp_path / "build/T0", destination)
    fixture = destination, built["index"], digest
    out = tmp_path / "out"
    assert run(fixture, out) == 0
    for rel in built["index"]["packs"]:
        card = json.loads((out / rel / "card.json").read_bytes())
        assert card["gate_verdict"] == "PASS"
        assert len(card["items"]) == 2
        assert all(item["score_milli"] == 1000 for item in card["items"])
        verdicts = {v["invariant"]: v for v in json.loads((out / rel / "invariants.json").read_bytes())}
        kill = "kill" in rel
        assert verdicts["INV-NEW"]["members"] == (2 if kill else 0)
        assert verdicts["INV-NEW"]["status"] == ("PASS" if kill else "NOT_EXERCISED")


def test_ingest_and_forget_from_installed_world(installed, tmp_path):
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-keep-forget-mft-1")
    for branch in ("B0", "B1"):
        ingested, selectors = [], []

        class Spy(ReferenceStore):
            def ingest(self, event, recorded=ingested):
                recorded.append(event)
                super().ingest(event)

            def forget(self, selector, recorded=selectors):
                recorded.append(selector)
                super().forget(selector)

        t0.drive_branch(pack, branch, Spy, bound_s=5, snapshot=snapshotter(tmp_path / branch))
        assert ingested == json.loads((pack.root / f"visible/events.{branch}.json").read_bytes())["events"]
        if branch == "B0":
            assert selectors and all(s.keys() == {"event_ids"} for s in selectors)
            db = t0.open_world(pack.root / "sealed/life/world.B0.db", readonly=True)
            try:
                requests = {r["event_id"]: json.loads(r["covered_fact_ids_json"])
                            for r in db.execute("SELECT * FROM forget_request")}
                tokens = db.execute("SELECT fact_id, value FROM locked_token").fetchall()
                expected = []
                for index, event in enumerate(ingested):
                    if event["event_id"] in requests:
                        needles = [unicodedata.normalize("NFC", r["value"]) for r in tokens
                                   if r["fact_id"] in requests[event["event_id"]]]
                        expected.append(dict(event_ids=sorted(e["event_id"] for e in ingested[:index + 1]
                            if any(token in unicodedata.normalize("NFC", e["text"]) for token in needles))))
                assert selectors == expected
            finally:
                db.close()
        else:
            assert selectors == []


def test_settle_false_is_system_failure(installed, tmp_path):
    class Unsettled(ReferenceStore):
        def settle(self, bound_s):
            return False

    pack = packs(installed)[0]
    results, outcomes, _ = t0.drive_branch(pack, "B0", Unsettled,
        bound_s=5, snapshot=snapshotter(tmp_path))
    assert not results
    assert outcomes and all(i["failure_class"] == "SYSTEM_FAILURE" for i in outcomes.values())


@pytest.mark.parametrize("reason,system", [("query_failed", True), ("ingest_failed", True),
    ("tool_failed", True), ("drain_failed", True), ("forget_unsettled", True),
    ("turn_timeout", True), ("session_end_failed", True),
    ("open_failed", False), ("unknown", False)])
def test_harness_failure_cause(reason, system):
    class Broken(ReferenceStore):
        def query(self, task, now):
            raise HarnessFailed(reason)

    with pytest.raises(SystemFault if system else HarnessFailed):
        t0._Guarded(Broken()).query({}, 0)


def test_refusal_escapes_guard():
    class Refused(ReferenceStore):
        def settle(self, bound_s):
            raise GateRefused("marker")

    with pytest.raises(GateRefused):
        t0._Guarded(Refused()).settle(5)


def test_answer_contract_keyed_cases():
    class Answer(ReferenceStore):
        def query(self, task, now):
            return self.reply

    adapter = Answer()
    for draw in range(200):
        confidence = uniform_int("t0-guard", ("answer",), draw, "confidence", -200, 1200)
        adapter.reply = dict(output="evidence", citations=["event"], confidence_milli=confidence)
        if 0 <= confidence <= 1000:
            assert t0._Guarded(adapter).query({}, 0) == adapter.reply
        else:
            with pytest.raises(SystemFault):
                t0._Guarded(adapter).query({}, 0)
    for reply in (None, {}, dict(output="ok", citations=[False], confidence_milli=1000),
                  dict(output="ok", citations=[], confidence_milli=True)):
        adapter.reply = reply
        with pytest.raises(SystemFault):
            t0._Guarded(adapter).query({}, 0)


def test_purity():
    from bicentennial import cli

    for module in (t0, cli):
        _pure_module(module)


def _pure_module(module):
    tree = ast.parse(Path(module.__file__).read_bytes())
    forbidden = {"socket", "ssl", "http", "urllib", "requests", "random"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] not in forbidden for a in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.module.split(".")[0] not in forbidden
            assert node.module != "bicentennial.director.upstream"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "lcm" not in node.value.casefold()
        for field in ("id", "attr", "name", "arg"):
            value = getattr(node, field, None)
            assert not isinstance(value, str) or "lcm" not in value.casefold()
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func) in ("os.environ.get", "os.getenv"):
                assert node.args[0].value == "PYTHONHASHSEED"
        if isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            assert node.slice.value == "PYTHONHASHSEED"


def test_resume_lock(installed):
    _, index, digest = installed
    for pack in packs(installed):
        lock = t0._lock(index, pack, dict(name="reference_store", surfaces=[]), digest, False)
        assert lock["pack_hash"] == digest
        assert lock["harness_artifacts"] == index["harness_artifacts"]
        assert lock["account_pool"] == []
        assert lock["analysis_commit"] == lock["benchmark_commit"] == lock["director_commit"]


@pytest.mark.parametrize("system", sorted(t0.REFERENCE_SYSTEMS))
def test_reference_lock_tracks_inherited_code(installed, tmp_path, monkeypatch, system):
    _, index, digest = installed
    pack = packs(installed)[0]
    files = ("api/contract.py", "api/adapters/reference_store.py", "api/adapters/bm25.py",
             "api/adapters/mutants.py", "director/scripted.py")
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / "src/bicentennial" / relative, target)
    original_hash = t0.code_sha256
    monkeypatch.setattr(t0, "code_sha256", lambda paths: original_hash(paths, root=tmp_path))
    entry = dict(name=system, surfaces=[])
    before = t0._lock(index, pack, entry, digest, False)["system_artifacts"]
    module = system if system in ("reference_store", "bm25") else "mutants"
    paths = ("api/contract.py", f"api/adapters/{module}.py")
    if system != "reference_store":
        paths += ("api/adapters/reference_store.py",)
    assert before[0]["sha256"] == original_hash(paths, root=tmp_path)
    reference = tmp_path / "api/adapters/reference_store.py"
    reference.write_bytes(reference.read_bytes() + b"\n# changed inherited query\n")
    after = t0._lock(index, pack, entry, digest, False)["system_artifacts"]
    assert after[0]["sha256"] != before[0]["sha256"]


def test_corpus_equality_deferred(installed, tmp_path):
    corpus = pytest.importorskip("bicentennial.corpus.run", reason="S12 not on base")
    catalogue = load_catalogue(ROOT / "packs/catalogue-v0.toml",
        c7_path=ROOT / "specs/ring0/c7-partial.json", tier_path=ROOT / "tiers/life_specs/t0.toml")
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-keep-forget-mft-1")
    row = catalogue.by_id()[pack.meta["row"]["id"]]
    case = SimpleNamespace(catalogue_row=row.id, template=pack.template.ref,
        c7_entry_sha256=pack.manifest["pins"]["c7_entries"][pack.template.ref],
        levers=row.micro_spec().to_obj(pack.template), case_id=row.id,
        fault_points=pack.schedule.fault_lite(), items=sorted(pack.records),
        **{k: pack.meta["generator"][k] for k in (
            "generator_version", "world_hash_b0", "world_hash_b1", "history_set_hash")})
    with corpus.regenerate(case, root=tmp_path / "corpus", catalogue=catalogue) as (life, worlds, keys, items):
        for branch in ("B0", "B1"):
            assert [e for _, e in pack.events[branch]] == build.api_events(worlds[branch][1])
            expected = corpus.drive(life, branch, worlds, keys, items, ReferenceStore,
                                     oracle=False, forget=True, bound_s=5)
            results, _, _ = t0.drive_branch(pack, branch, ReferenceStore, bound_s=5,
                                            snapshot=snapshotter(tmp_path / "snap" / branch))
            assert [corpus.outcome(results[i]) for i in sorted(results)] == expected


def test_recomputed_c7(installed, tmp_path, monkeypatch):
    from dataclasses import replace

    freeze = ROOT / "specs/ring0/c7-partial.json"
    for pack in packs(installed):
        t0._check_c7(pack, freeze)
    pack = packs(installed)[0]
    copied = tmp_path / "c7.json"
    obj = json.loads(freeze.read_bytes())
    del obj["entries"][pack.template.ref]
    copied.write_bytes(canon(obj))
    with pytest.raises(t0.T0Refused, match="c7_missing"):
        t0._check_c7(pack, copied)
    templates = t0.TEMPLATES_BY_GENRE[pack.meta["genre"]]
    changed = replace(pack.template, statement_id="decision-changed")
    monkeypatch.setitem(templates, pack.template.template_id, changed)
    with pytest.raises(t0.T0Refused, match="c7_changed"):
        t0._check_c7(pack, freeze)


def test_retry_classification(installed, tmp_path, monkeypatch):
    pack = packs(installed)[0]
    calls = []

    class Intermittent(ReferenceStore):
        def query(self, task, now):
            calls.append(task["task_id"])
            if len(calls) <= 2:
                raise HarnessFailed("ipc")
            return super().query(task, now)

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Intermittent)
    results, outcomes, roots, factories = t0._attempts(installed[1], pack, "B0",
        dict(name="reference_store", surfaces=[]), installed[2], False, tmp_path, 0,
        bound_s=5, host_options={})
    try:
        assert results and roots and len(factories) == 3
        assert all(o["infra_reruns"] == 2 for o in outcomes.values())
    finally:
        t0._remove_units(factories)
    assert not list(tmp_path.rglob("checkpoint.bin"))


@pytest.mark.parametrize("system", [False, True])
def test_exhausted_or_system_cause(installed, tmp_path, monkeypatch, system):
    class Broken(ReferenceStore):
        def query(self, task, now):
            raise HarnessFailed("query_failed" if system else "ipc")

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Broken)
    results, outcomes, _, factories = t0._attempts(installed[1], packs(installed)[0], "B0",
        dict(name="reference_store", surfaces=[]), installed[2], False, tmp_path, 0,
        bound_s=5, host_options={})
    try:
        assert not results
        assert len(factories) == (1 if system else 3)
        assert {o["failure_class"] for o in outcomes.values()} == {
            "SYSTEM_FAILURE" if system else "BLOCKED"}
    finally:
        t0._remove_units(factories)


def test_retry_lock_change_refuses(installed, tmp_path, monkeypatch):
    class Broken(ReferenceStore):
        def query(self, task, now):
            raise HarnessFailed("ipc")

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Broken)
    commits = iter(["1" * 40, "1" * 40, "2" * 40])
    monkeypatch.setattr(t0, "_commit", lambda: next(commits))
    with pytest.raises(t0.LockMismatch) as raised:
        t0._attempts(installed[1], packs(installed)[0], "B0", dict(name="reference_store", surfaces=[]),
            installed[2], False, tmp_path, 0, bound_s=5, host_options={})
    assert raised.value.fields == ("analysis_commit", "benchmark_commit", "director_commit")


@pytest.fixture
def fake_hosts(installed, tmp_path, monkeypatch):
    created = []

    class FakeHost(ReferenceStore):
        write_clipped, write_max_length = 0, None

        def fields(self):
            return {"actor": "not_delivered", "text": "full", "time": "session_clock"}

        def __init__(self, entry, **options):
            super().__init__()
            self.options = options
            self.paths = dict(workspace=options["root"] / "workspace")
            self.paths["workspace"].mkdir()
            self.store = options["root"] / "store"
            self.store.mkdir()
            self.closed = 0
            self.log = []
            self.records, self.egress = list, SimpleNamespace(summary=dict)
            created.append(self)

        def surfaces(self):
            (self.store / "events.json").write_bytes(self.checkpoint())
            return [(self.store, [])]

        def close(self):
            self.closed += 1
            assert self.closed == 1

        def settle(self, bound_s):
            self.log.append("settle")
            return True

        def begin_session(self, index):
            assert index > 1 and self.log[-1] == "settle"
            self.log.append("begin_session")

        def probe(self, task, now):
            assert self.log[-1] == "settle"
            self.log.append("probe")
            return ()

    monkeypatch.setattr(t0, "HermesMemoryHost", FakeHost)
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-keep-forget-mft-1")
    entry = load(REGISTRY / "hermes-native.toml")
    lock = t0._lock(installed[1], pack, entry, installed[2], True)
    factory = t0._Factory(pack, "B0", tmp_path / "unit", entry, lock, real=True)
    yield factory, created
    factory.close()


def test_owned_host_drive(fake_hosts):
    factory, created = fake_hosts
    results, outcomes, roots = t0.drive_branch(factory.pack, "B0", factory,
        bound_s=5, snapshot=factory.snapshot)
    factory.close()
    assert results and outcomes and roots
    assert all(h.closed == 1 for h in created)
    for host in created:
        assert host.options["sim_epoch_s"] == 0
        assert factory.pack.manifest["canary"].encode() not in (
            host.paths["workspace"] / "pack/answer_key.json").read_bytes()


def test_invariant_hosts_closed(fake_hosts):
    factory, created = fake_hosts
    verdicts = factory.invariants(5)
    assert all(v.status == "PASS" for v in verdicts.values())
    assert created and all(h.closed == 1 for h in created)


def test_invariant_injected_context(fake_hosts, monkeypatch):
    factory, created = fake_hosts
    probed, queried = [], []

    def probe(host, task, now):
        assert host.log[-1] == "settle"
        answer = ReferenceStore.query(host, task, now)
        # Extracted facts need not contain a complete event or cite its id.
        host.blocks = tuple(text.split()[-1] for text in answer["output"].splitlines())
        host.cached_task = (task, now)
        probed.append((task, now))
        return host.context_blocks()

    def query(host, task, now):
        if hasattr(host, "cached_task"):
            assert (task, now) == host.cached_task
        queried.append((task, now))
        return dict(output="", citations=[], confidence_milli=0)

    monkeypatch.setattr(t0.HermesMemoryHost, "probe", probe)
    monkeypatch.setattr(t0.HermesMemoryHost, "context_blocks", lambda host: host.blocks, raising=False)
    monkeypatch.setattr(t0.HermesMemoryHost, "query", query)
    verdicts = factory.invariants(5)
    assert verdicts["INV-NEW"].status == verdicts["INV-VERB"].status == "PASS"
    assert all(v.status == "PASS" for v in verdicts.values())
    assert probed == queried and all(now == 100 for _, now in probed)
    assert created and all(host.closed == 1 for host in created)


@pytest.mark.parametrize("cause,status,attempts", [("ipc", "INFRA_FAILURE", 3),
                                                  ("query_failed", "FAIL", 1)])
def test_invariant_probe_fault_attribution(fake_hosts, monkeypatch, cause, status, attempts):
    factory, created = fake_hosts
    original = t0.HermesMemoryHost.probe
    failed = []

    def probe(host, task, now):
        if task["task_id"] == "new-b":
            failed.append(host.options["root"])
            raise HarnessFailed(cause)
        return original(host, task, now)

    monkeypatch.setattr(t0.HermesMemoryHost, "probe", probe)
    verdicts = factory.invariants(5)
    assert verdicts["INV-NEW"].status == status
    assert verdicts["INV-NEW"].infra == (("new-a", "new-b") if cause == "ipc" else ())
    assert len(failed) == len(set(failed)) == attempts
    assert all(v.status == "PASS" for name, v in verdicts.items() if name != "INV-NEW")
    assert created and all(host.closed == 1 for host in created)


def test_invariant_factory_refusal(fake_hosts, monkeypatch):
    factory, created = fake_hosts

    def refuse(*args, **kwargs):
        raise GateRefused("marker")

    monkeypatch.setattr(t0, "HermesMemoryHost", refuse)
    with pytest.raises(GateRefused):
        factory.invariants(5)
    assert created == []
    # The refusal remains captured; teardown also re-raises it unless acknowledged.
    factory.refusals.clear()


def test_invariant_adapter_refusal(fake_hosts, monkeypatch):
    factory, created = fake_hosts

    def refuse(self, bound_s):
        raise GateRefused("marker")

    # Capture a refusal thrown after construction, before S05 converts it.
    original = t0.HermesMemoryHost
    monkeypatch.setattr(original, "settle", refuse)
    with pytest.raises(GateRefused):
        factory.invariants(5)
    assert created and all(h.closed == 1 for h in created)
    factory.refusals.clear()


def preflight(installed, **changes):
    args = dict(system="reference_store", packs=installed[0], selected=["all"],
                pack_hash=installed[2])
    return t0._preflight(**(args | changes))


def test_preflight_resolves_packs(installed):
    index, selected, rows, entry, _, admission, options, bound_s = preflight(installed)
    assert index == installed[1]
    assert [p.rel for p in selected] == sorted(index["packs"])
    assert len(selected) == len(rows) == 7
    assert entry == dict(name="reference_store", surfaces=[])
    assert admission.admitted and options == {} and bound_s == 5
    chosen = selected[0]
    assert preflight(installed, selected=[chosen.rel])[1][0].rel == chosen.rel
    assert preflight(installed, selected=[chosen.pack["pack_id"]])[1][0].rel == chosen.rel


@pytest.mark.parametrize("changes,code", [
    (dict(system="nomemory"), "unknown_system"),
    (dict(system="../outside"), "unknown_system"),
    (dict(system="no-memory"), "harness_not_hermes"),
    (dict(system="hermes-native", entry=load(REGISTRY / "hermes-native.toml") |
          dict(fresh_install_hash=ZERO_HASH)), "unmeasured:fresh_install_hash"),
    (dict(selected=["unknown"]), "unknown_pack"),
    (dict(selected=["all", "unknown"]), "unknown_pack"),
    (dict(mode="hermes"), "mode_unavailable:hermes"),
    (dict(workers=0), "positive integer roots required"),
    (dict(pack_hash="0" * 64), "pinned_artifact_changed"),
])
def test_preflight_refusals(installed, changes, code, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("a preflight refusal constructed a host")

    monkeypatch.setattr(t0, "HermesMemoryHost", forbidden)
    with pytest.raises((t0.T0Refused, t0.SystemRefused, t0.PinnedArtifactChanged)) as raised:
        preflight(installed, **changes)
    error = raised.value
    assert code in (*getattr(error, "reasons", ()), getattr(error, "code", ""))


def test_preflight_busy_marker(installed, monkeypatch):
    from bicentennial.runner.guard import Marker

    monkeypatch.setattr(t0, "read_marker", lambda: Marker(11, False, "busy"))
    with pytest.raises(t0.T0Refused, match="marker exit 11"):
        preflight(installed)


def fake_worker_python(checkout):
    python = checkout / ".venv/bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text("#!/bin/sh\ncat >/dev/null\necho '{\"applicable\":{},\"installed\":{},\"dists\":[]}'\n")
    python.chmod(0o755)


def test_preflight_registry_requirements(installed, tmp_path):
    entry = load(REGISTRY / "hermes-native.toml") | dict(fresh_install_hash="1" * 64)
    with pytest.raises(t0.T0Refused, match="missing_input"):
        preflight(installed, system="hermes-native", entry=entry)
    fake_worker_python(tmp_path)
    prepared = preflight(installed, system="hermes-native", entry=entry,
                         host_overrides={"checkout": tmp_path})
    assert prepared[6]["checkout"] == tmp_path
    assert prepared[6]["harness_pin"] == installed[1]["harness_artifacts"][0]


def test_preflight_c7_before_host(installed, tmp_path, monkeypatch):
    fake_worker_python(tmp_path)
    entry = load(REGISTRY / "hermes-native.toml") | dict(fresh_install_hash="1" * 64)
    original = t0.c7_entries

    def missing(path):
        entries = dict(original(path))
        del entries[packs(installed)[0].template.ref]
        return entries

    monkeypatch.setattr(t0, "c7_entries", missing)
    with pytest.raises(t0.T0Refused, match="c7_missing"):
        preflight(installed, system="hermes-native", entry=entry, hermes=tmp_path)


def test_parallel_pack_invariants_and_baseline(installed, tmp_path):
    index, selected, by_row, entry, _, _, _, bound_s = preflight(installed)
    adapter_verdicts = adapter_invariants(ReferenceStore, bound_s=bound_s)
    assert all(v.status == "PASS" for v in adapter_verdicts.values())
    for pack in selected:
        factories = []
        try:
            results, outcomes, roots, made = t0._branches(index, pack, entry, installed[2], False,
                tmp_path / pack.pack["pack_id"] / "main", 2, bound_s=bound_s, host_options={})
            factories.extend(made)
            baseline = {}
            if any(t0._verb_member(pack, i) for i in pack.pack["items"]):
                twin = by_row[pack.meta["row"]["baseline"]]
                twin_results, _, _, made = t0._branches(index, twin, entry, installed[2], False,
                    tmp_path / pack.pack["pack_id"] / "baseline", 1, bound_s=bound_s, host_options={})
                factories.extend(made)
                baseline = t0._baseline_context(pack, twin, twin_results)
                assert baseline and all(baseline.values())
            verdicts = t0._pack_invariants(pack, results, outcomes, roots, baseline, adapter_verdicts)
            assert [v["invariant"] for v in verdicts] == list(t0.INVARIANTS)
            by_inv = {v["invariant"]: v for v in verdicts}
            if pack.meta["row"]["id"] == "g2-keep-forget-mft-1":
                assert by_inv["INV-FORGET"]["status"] == "PASS"
                assert by_inv["INV-FORGET"]["members"] >= 1
            if pack.meta["row"]["id"] == "g2-drift-asof-dir-2":
                assert by_inv["INV-VERB"]["status"] == "PASS"
                assert by_inv["INV-VERB"]["members"] == 1
            assert canon(verdicts)
        finally:
            t0._remove_units(factories)


def test_refused_branches_remove_units(installed, tmp_path, monkeypatch):
    class Refused(ReferenceStore):
        def query(self, task, now):
            raise GateRefused("marker")

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Refused)
    with pytest.raises(GateRefused):
        t0._branches(installed[1], packs(installed)[0], dict(name="reference_store", surfaces=[]),
            installed[2], False, tmp_path, 2, bound_s=5, host_options={})
    assert not list(tmp_path.rglob("checkpoint.bin"))


@pytest.mark.parametrize("malformed", [False, True])
def test_host_unknown_cause_is_infrastructure(fake_hosts, monkeypatch, malformed):
    factory, _ = fake_hosts
    host = factory()

    def query(task, now):
        if malformed:
            return {"output": "invalid answer"}
        raise ValueError("host IPC decode")

    monkeypatch.setattr(host.host, "query", query)
    with pytest.raises(SystemFault if malformed else ValueError):
        t0._Guarded(host).query({}, 0)


def run(installed, out, **changes):
    return t0.run_t0(**(dict(system="reference_store", packs=["all"], packs_dir=installed[0],
                            pack_hash=installed[2], out=out) | changes))


@pytest.mark.parametrize("always", [False, True])
def test_pack_invariant_scan_reruns(installed, tmp_path, monkeypatch, always):
    from bicentennial.score import invariants

    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-keep-forget-mft-1")
    original = invariants.search_store
    scans = []

    def search(root, needles):
        if "main" in Path(root).parts:
            scans.append(root)
            if always or len(scans) == 1:
                raise OSError("store scan failed")
        return original(root, needles)

    monkeypatch.setattr(invariants, "search_store", search)
    out = tmp_path / "out"
    assert run(installed, out, packs=[pack.rel]) == (2 if always else 0)
    verdicts = {v["invariant"]: v for v in json.loads((out / pack.rel / "invariants.json").read_bytes())}
    forget = verdicts["INV-FORGET"]
    assert forget["members"] >= 1
    assert forget["status"] == ("INFRA_FAILURE" if always else "PASS")
    assert forget["reasons"] == (["infra"] if always else [])
    assert scans and scans.count(scans[0]) == (3 if always else 2)
    for filename, schema in (("card.json", "card_ring0"), ("receipt.json", "receipt")):
        value = json.loads((out / pack.rel / filename).read_bytes())
        validate(schema, value)
        assert value["run_status"] == ("BLOCKED" if always else "COMPLETE")


def test_pack_invariant_rerun_keeps_known_failure(installed, tmp_path, monkeypatch):
    from dataclasses import replace

    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-keep-forget-mft-1")
    original, calls = t0.run_invariants, []

    def evaluate(evidence, **kwargs):
        verdicts = original(evidence, **kwargs)
        calls.append(len(calls))
        forget = verdicts["INV-FORGET"]
        # The first attempt finds a store hit beside a scan fault; any later attempt would hide the hit.
        verdicts["INV-FORGET"] = (replace(forget, status="FAIL", failed=("forget-hit",), infra=("forget-scan",),
                                          reasons=("infra", "store_hit")) if len(calls) == 1 else
                                  replace(forget, status="INFRA_FAILURE", failed=(), infra=("forget-hit",),
                                          reasons=("infra",)))
        return verdicts

    monkeypatch.setattr(t0, "run_invariants", evaluate)
    out = tmp_path / "out"
    assert run(installed, out, packs=[pack.rel]) == 1
    assert len(calls) == 1
    verdicts = {v["invariant"]: v for v in json.loads((out / pack.rel / "invariants.json").read_bytes())}
    assert verdicts["INV-FORGET"]["status"] == "FAIL" and verdicts["INV-FORGET"]["failed"] == ["forget-hit"]
    card = json.loads((out / pack.rel / "card.json").read_bytes())
    assert card["gate_verdict"] == "FAIL"
    for filename in ("card.json", "receipt.json"):
        assert json.loads((out / pack.rel / filename).read_bytes())["run_status"] == "BLOCKED"


def test_pack_invariant_session_wakes(fake_hosts, installed, tmp_path, monkeypatch):
    fake_worker_python(tmp_path)
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-drift-booking-mft-1")
    members = {i["item_id"] for i in pack.pack["items"]
               if pack.records[i["item_id"]]["evidence_session"] == 2 and i["probe_point"] == 3}
    assert members and members == {i["item_id"] for i in pack.pack["items"]}
    assert not any(kind in ("restart", "kill") and 2 < session <= 3
                   for kind, session, _ in pack.schedule.wakes())
    empty_audit = t0._audit([])
    monkeypatch.setattr(t0, "_audit", lambda factories, *a: dict(empty_audit))
    original = t0.run_invariants
    observed = []

    def observe(evidence, **kwargs):
        observed.append({e.item["item_id"] for e in evidence if e.crosses_restart})
        return original(evidence, **kwargs)

    monkeypatch.setattr(t0, "run_invariants", observe)
    for real in (False, True):
        out = tmp_path / str(real)
        options = dict(system="hermes-native", hermes=tmp_path,
                       entry=load(REGISTRY / "hermes-native.toml") | dict(fresh_install_hash="1" * 64)) if real else {}
        assert run(installed, out, packs=[pack.rel], **options) == 0
        xml = ET.parse(out / pack.rel / "junit.xml").getroot()
        injection = xml.findall(".//property[@name='t0.injection']")
        assert [p.attrib["value"] for p in injection] == ([
            "The session-start memory snapshot is read; other harness prompt injection is not exercised."
        ] if real else [])
        verdicts = {v["invariant"]: v for v in json.loads((out / pack.rel / "invariants.json").read_bytes())}
        assert observed[-1] == (members if real else set())
        assert verdicts["INV-NEW"]["members"] == (len(members) if real else 0)
        assert verdicts["INV-NEW"]["status"] == ("PASS" if real else "NOT_EXERCISED")


def no_floats(value):
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for child in value.values():
            no_floats(child)
    elif isinstance(value, list):
        for child in value:
            no_floats(child)


def validate_outputs(out, installed):
    for rel in sorted(installed[1]["packs"]):
        directory = out / rel
        for filename, schema in (("card.json", "card_ring0"), ("receipt.json", "receipt")):
            data = (directory / filename).read_bytes()
            value = json.loads(data)
            validate(schema, value)
            assert data == canon(value)
        xml = ET.parse(directory / "junit.xml").getroot()
        assert xml.tag == "testsuites" and set(xml.attrib) == {"name", "tests", "failures", "errors"}
        assert len(xml) == 3
        for suite in xml:
            assert suite.tag == "testsuite"
            assert set(suite.attrib) == {"name", "tests", "failures", "errors", "skipped"}
            cases = suite.findall("testcase")
            assert int(suite.attrib["tests"]) == len(cases)
            assert len({c.attrib["name"] for c in cases}) == len(cases)
            assert all(c.attrib.keys() == {"name", "classname"} and len(c) <= 1 for c in cases)
            for case in cases:
                for detail in case:
                    assert detail.tag in {"failure", "error", "skipped"}
                    assert set(detail.attrib) == {"type", "message"} and not len(detail)
            for tag, count in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
                assert int(suite.attrib[count]) == sum(c.find(tag) is not None for c in cases)
        for count in ("tests", "failures", "errors"):
            assert int(xml.attrib[count]) == sum(int(s.attrib[count]) for s in xml)
        if shutil.which("xmllint"):
            subprocess.run(["xmllint", "--noout", "--schema", str(ROOT / "schemas/junit.xsd"),
                            str(directory / "junit.xml")], capture_output=True, check=True)
        invariants = json.loads((directory / "invariants.json").read_bytes())
        assert [v["invariant"] for v in invariants] == list(t0.INVARIANTS)
    for path in sorted(out.rglob("*.json")):
        no_floats(json.loads(path.read_bytes()))


def test_reference_whole_run(installed, tmp_path, monkeypatch):
    out, baselines, times = tmp_path / "out", [], {}
    mixed = False
    original_branch, original_report = t0._branches, t0._report_pack

    def branches(*args, **kwargs):
        if "baseline" in Path(args[5]).parts:
            baselines.append(args[1].meta["row"]["id"])
        result = original_branch(*args, **kwargs)
        if mixed:
            summary = (dict(non_loopback=["192.0.2.1:443"], non_loopback_seen=["auxiliary endpoint"])
                       if "baseline" in Path(args[5]).parts else
                       dict(non_loopback=[], unsampled=["egress unsampled pid=40 log=worker.stderr"]))
            result[3][0].hosts.append(SimpleNamespace(records=list, egress=SimpleNamespace(summary=lambda: summary)))
        return result

    def report(pack, *args, **kwargs):
        result = original_report(pack, *args, **kwargs)
        times[pack.meta["row"]["id"]] = t0.time.time_ns() // 1_000_000 - args[-1]
        return result

    monkeypatch.setattr(t0, "_branches", branches)
    monkeypatch.setattr(t0, "_report_pack", report)
    assert run(installed, out) == 0
    assert {p.name for p in out.iterdir()} == {
        "pack", "adapter_invariants.json", "relations.json", "relations.xml"}
    validate_outputs(out, installed)
    assert all(v["status"] == "PASS" for v in json.loads((out / "adapter_invariants.json").read_bytes()))
    assert len(times) == 7 and all(ms < 60_000 for ms in times.values())
    print("whole_run_pack_ms=" + json.dumps(times, sort_keys=True))
    print("xmllint=" + str(shutil.which("xmllint")))
    for pack in packs(installed):
        card = json.loads((out / pack.rel / "card.json").read_bytes())
        verdicts = {v["invariant"]: v for v in json.loads((out / pack.rel / "invariants.json").read_bytes())}
        assert card["masked_ledger_digest"] == sha256(b"[]").hexdigest()
        assert "scripted_model" not in card["labels"]
        assert card["controls"]["wiped_store"] == "not run at T0"
        assert card["controls"]["naive_rag"] == "not run in v0.1"
        if pack.meta["row"]["id"] == "g2-keep-forget-mft-1":
            assert verdicts["INV-FORGET"]["status"] == "PASS"
            assert verdicts["INV-FORGET"]["members"] >= 1
        if pack.meta["row"]["id"] == "g2-drift-asof-dir-2":
            assert verdicts["INV-VERB"]["status"] == "PASS"
            assert verdicts["INV-VERB"]["members"] == 1
            assert pack.meta["row"]["baseline"] in baselines
        if pack.meta["row"]["id"] == "g2-recall-count-mft-1":
            assert len(card["items"]) == 1 and card["bundles"] == []
            assert card["singletons"] == [dict(item_id=card["items"][0]["item_id"], life=pack.meta["life"])]
            assert card["gate_verdict"] == "PASS"
    relations = json.loads((out / "relations.json").read_bytes())["relations"]
    assert len(relations) == 1
    assert (relations[0]["row"], relations[0]["base"], relations[0]["test"]) == (
        "g2-drift-asof-dir-2", next(p.meta["row"]["baseline"] for p in packs(installed)
                                 if p.meta["row"]["id"] == "g2-drift-asof-dir-2"), "DIR")
    mixed, out = True, tmp_path / "mixed"
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-drift-asof-dir-2")
    assert run(installed, out, packs=[pack.rel]) == 3
    assert json.loads((out / "refusal.json").read_bytes()) == dict(
        code="upstream_record", fields=[], detail=["auxiliary endpoint"])


def stable_files(out):
    names = {"card.json", "junit.xml", "invariants.json", "adapter_invariants.json", "relations.json"}
    return {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*")) if p.name in names}


def test_reference_determinism_and_workers(installed, tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    assert run(installed, first) == run(installed, second, workers=2) == 0
    assert stable_files(first) == stable_files(second)
    print("card_sha256=" + json.dumps({p: sha256(data).hexdigest() for p, data in stable_files(first).items()
                                      if p.endswith("card.json")}, sort_keys=True))


def cli_command(installed, out, *extra):
    return [sys.executable, "-m", "bicentennial.cli", "t0", "--system", "reference_store", "--pack", "all",
            "--packs", str(installed[0]), "--pack-hash", installed[2], "--out", str(out), *extra]


def test_cli_subprocess_determinism(installed, tmp_path):
    outputs, failures = [], []
    for name in ("one", "two"):
        out = tmp_path / name
        result = subprocess.run(cli_command(installed, out), capture_output=True, text=True,
                                env=dict(os.environ, PYTHONHASHSEED="0"))
        if result.returncode and ("PermissionError: [Errno 1]" in result.stderr or
                                   "taskpolicy: setpriority(): Operation not permitted" in result.stderr):
            failures.append(result.stderr.splitlines()[-1])
        else:
            assert result.returncode == 0, result.stderr
            outputs.append(stable_files(out))
    if failures:
        pytest.skip("sandbox scheduling denied: " + "; ".join(failures))
    assert outputs[0] == outputs[1]
    print("subprocess_card_sha256=" + json.dumps({p: sha256(data).hexdigest() for p, data in outputs[0].items()
                                                 if p.endswith("card.json")}, sort_keys=True))


@pytest.mark.parametrize("system,failed", [
    ("forget_ignored", {"INV-FORGET"}), ("stale_wins", {"INV-NEW"}),
    ("wipe_on_restart", {"INV-VERB", "INV-NEW", "INV-PAIR"})])
def test_mutant_whole_runs(installed, tmp_path, system, failed):
    out = tmp_path / "out"
    assert run(installed, out, system=system) == 1
    verdicts = json.loads((out / "adapter_invariants.json").read_bytes())
    assert {v["invariant"] for v in verdicts if v["status"] == "FAIL"} == failed
    assert all(json.loads(p.read_bytes())["gate_verdict"] == "FAIL" for p in out.rglob("card.json"))
    validate_outputs(out, installed)


@pytest.mark.parametrize("kind,code,failure", [("settle", 1, "SYSTEM_FAILURE"),
    ("twice", 0, None), ("always", 2, "BLOCKED"), ("system", 1, "SYSTEM_FAILURE")])
def test_whole_run_failure_classes(installed, tmp_path, monkeypatch, kind, code, failure):
    attempts = {}
    original = t0._attempts

    def isolated(*args, **kwargs):
        # The selected baseline row is also driven independently as an auxiliary.
        # Count attempts within each drive, rather than sharing query counts across drives.
        attempts.clear()
        return original(*args, **kwargs)

    class Broken(ReferenceStore):
        def settle(self, bound_s):
            return kind != "settle"

        def query(self, task, now):
            iid = task["task_id"]
            if iid.startswith(("verb-", "new-", "pair-", "forget-")):
                # Two failed attempts per invariant, then a clean attempt of all its probes.
                iid = iid.split("-")[0]
            attempts[iid] = attempts.get(iid, 0) + 1
            if kind == "system":
                raise HarnessFailed("query_failed")
            if kind == "always" or kind == "twice" and attempts[iid] <= 2:
                raise HarnessFailed("ipc")
            return super().query(task, now)

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Broken)
    monkeypatch.setattr(t0, "_attempts", isolated)
    out = tmp_path / "out"
    assert run(installed, out) == code
    validate_outputs(out, installed)
    for path in sorted(out.rglob("card.json")):
        card = json.loads(path.read_bytes())
        assert card["run_status"] == ("BLOCKED" if kind == "always" else "COMPLETE")
        if failure:
            assert all(i["failure_class"] == failure for i in card["items"])
        if kind == "twice":
            assert all(i["infra_reruns"] == 2 for i in card["items"])


@pytest.mark.parametrize("scenario", ["system-blocked", "fail-blocked", "honeypot-blocked", "blocked"])
def test_known_failure_wins_over_blocked(installed, tmp_path, monkeypatch, scenario):
    selected = [next(p for p in packs(installed) if p.meta["row"]["id"] == name)
                for name in ("g2-keep-forget-mft-1", "g2-keep-incidental-mft-1")]
    if scenario != "fail-blocked":
        selected = selected[:1]
    original = t0._Factory.__call__
    attempts = {}
    evaluate = t0.run_invariants
    evaluations = []

    def invariants(evidence, **kwargs):
        verdicts = evaluate(evidence, **kwargs)
        evaluations.append(verdicts)
        return verdicts

    def construct(factory):
        if "adapter" in factory.unit.parts:
            return original(factory)
        key = (factory.pack.rel, factory.branch)
        attempts[key] = attempts.get(key, 0) + 1
        system = (scenario == "system-blocked" and factory.branch == "B0" or
                  scenario == "fail-blocked" and factory.pack.rel == selected[0].rel)

        class Broken(ReferenceStore):
            def query(self, task, now):
                raise HarnessFailed("query_failed" if system else "ipc")

        return Broken()

    monkeypatch.setattr(t0._Factory, "__call__", construct)
    monkeypatch.setattr(t0, "run_invariants", invariants)
    if scenario == "honeypot-blocked":
        monkeypatch.setattr(t0, "hits", lambda token, texts: 1)
    out = tmp_path / "out"
    code = run(installed, out, packs=[p.rel for p in selected])
    assert len(evaluations) == len(selected)
    expected = 2 if scenario == "blocked" else 1
    assert code == expected
    for n, pack in enumerate(selected):
        card = json.loads((out / pack.rel / "card.json").read_bytes())
        validate("card_ring0", card)
        gate = ("INVALID" if scenario == "honeypot-blocked" else
                "BLOCKED" if scenario == "blocked" or n == 1 else "FAIL")
        assert card["gate_verdict"] == gate
        assert card["run_status"] == ("COMPLETE" if scenario == "fail-blocked" and n == 0 else "BLOCKED")
        for item in card["items"]:
            branch = pack.records[item["item_id"]]["branch"]
            system = (scenario == "system-blocked" and branch == "B0" or
                      scenario == "fail-blocked" and n == 0)
            assert item["failure_class"] == ("SYSTEM_FAILURE" if system else "BLOCKED")
    assert attempts
    assert all(count == (1 if scenario == "fail-blocked" and rel == selected[0].rel or
                         scenario == "system-blocked" and branch == "B0" else 3)
               for (rel, branch), count in attempts.items())


@pytest.mark.parametrize("baseline_cause,selected_failure", [
    ("ipc", False), ("ipc", True), ("query_failed", False)])
def test_baseline_fault_verdict(installed, tmp_path, monkeypatch, baseline_cause, selected_failure):
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-drift-asof-dir-2")
    members = sorted(i["item_id"] for i in pack.pack["items"] if t0._verb_member(pack, i))
    assert members
    original = t0._Factory.__call__
    baseline_attempts = []

    def construct(factory):
        if "baseline" in factory.unit.parts:
            baseline_attempts.append(factory.unit)

            class Broken(ReferenceStore):
                def query(self, task, now):
                    raise HarnessFailed(baseline_cause)

            return Broken()
        if selected_failure and "main" in factory.unit.parts:
            class FailedMember(ReferenceStore):
                def query(self, task, now):
                    if task["task_id"] == members[0]:
                        raise HarnessFailed("query_failed")
                    return super().query(task, now)

            return FailedMember()
        return original(factory)

    monkeypatch.setattr(t0._Factory, "__call__", construct)
    out = tmp_path / "out"
    blocked = baseline_cause == "ipc"
    assert run(installed, out, packs=[pack.rel]) == (1 if selected_failure else 2 if blocked else 0)
    verdicts = {v["invariant"]: v for v in json.loads((out / pack.rel / "invariants.json").read_bytes())}
    verb = verdicts["INV-VERB"]
    assert verb["status"] == ("FAIL" if selected_failure else "INFRA_FAILURE" if blocked else "INCONCLUSIVE")
    assert verb["infra"] == (members if blocked else [])
    assert verb["failed"] == ([members[0]] if selected_failure else [])
    # The twin has a probe in B0; its empty B1 branch never reaches query.
    assert len(baseline_attempts) == (4 if blocked else 2)
    card = json.loads((out / pack.rel / "card.json").read_bytes())
    validate("card_ring0", card)
    assert card["run_status"] == ("BLOCKED" if blocked else "COMPLETE")
    assert card["gate_verdict"] == ("FAIL" if selected_failure else "BLOCKED" if blocked else "PASS")
    receipt = json.loads((out / pack.rel / "receipt.json").read_bytes())
    validate("receipt", receipt)
    assert receipt["timings"] == []
    assert receipt["run_status"] == card["run_status"]
    if not selected_failure:
        assert all(i["failure_class"] not in ("SYSTEM_FAILURE", "BLOCKED") for i in card["items"])


def test_clean_baseline_card_bytes(installed, tmp_path, monkeypatch):
    pack = next(p for p in packs(installed) if p.meta["row"]["id"] == "g2-drift-asof-dir-2")
    first, second = tmp_path / "one", tmp_path / "two"
    assert run(installed, first, packs=[pack.rel]) == 0
    original = t0._pack_invariants

    def without_baseline_infra(*args, **kwargs):
        kwargs.pop("baseline_infra", None)
        return original(*args, **kwargs)

    monkeypatch.setattr(t0, "_pack_invariants", without_baseline_infra)
    assert run(installed, second, packs=[pack.rel]) == 0
    assert stable_files(first) == stable_files(second)


@pytest.mark.parametrize("fault,status,code,count", [
    (HarnessFailed("ipc"), "INFRA_FAILURE", 2, 3),
    (HarnessFailed("query_failed"), "FAIL", 1, 1),
    (HarnessFailed("turn_timeout"), "FAIL", 1, 1),
    (ValueError("host decode"), "INFRA_FAILURE", 2, 3)])
@pytest.mark.parametrize("close_fault", [False, True])
def test_invariant_fault_attribution(fake_hosts, installed, tmp_path, monkeypatch,
                                     fault, status, code, count, close_fault):
    fake_worker_python(tmp_path)
    factory, created = fake_hosts
    original = t0.HermesMemoryHost.query
    original_close = t0.HermesMemoryHost.close
    failures = []

    def query(host, task, now):
        if task["task_id"] == "new-b":
            failures.append(host.options["root"])
            raise fault
        return original(host, task, now)

    def close(host):
        original_close(host)
        if close_fault and host.options["root"] in failures:
            raise HarnessFailed("end_failed")

    monkeypatch.setattr(t0.HermesMemoryHost, "query", query)
    monkeypatch.setattr(t0.HermesMemoryHost, "close", close)
    empty_audit = t0._audit([])
    monkeypatch.setattr(t0, "_audit", lambda factories, *a: dict(empty_audit))
    out = tmp_path / "out"
    assert run(installed, out, system="hermes-native", packs=[factory.pack.rel], hermes=tmp_path,
               entry=factory.entry | dict(fresh_install_hash="1" * 64)) == code
    verdicts = json.loads((out / "adapter_invariants.json").read_bytes())
    expected = adapter_invariants(ReferenceStore, bound_s=5)
    for verdict in verdicts:
        assert Verdict(**verdict).to_obj() == verdict
        if verdict["invariant"] != "INV-NEW":
            assert verdict == expected[verdict["invariant"]].to_obj()
            continue
        assert verdict["status"] == status
        assert verdict["members"] == 2 and verdict["uninformative"] == 0
        assert verdict["infra"] == (["new-a", "new-b"] if status == "INFRA_FAILURE" else [])
        assert verdict["failed"] == (["new-a", "new-b"] if status == "FAIL" else [])
        assert verdict["inconclusive"] == []
        assert verdict["reasons"] == (["infra"] if status == "INFRA_FAILURE" else ["system_failure"])
    assert len(failures) == count and len(set(failures)) == count
    assert created and all(host.closed == 1 for host in created)
    card = json.loads((out / factory.pack.rel / "card.json").read_bytes())
    validate("card_ring0", card)
    assert card["run_status"] == ("BLOCKED" if status == "INFRA_FAILURE" else "COMPLETE")
    assert card["gate_verdict"] == ("BLOCKED" if status == "INFRA_FAILURE" else "FAIL")
    assert not (out / "work").exists()


def test_invariant_close_refusal_after_system_fault(fake_hosts, monkeypatch):
    factory, created = fake_hosts
    original_query, original_close = t0.HermesMemoryHost.query, t0.HermesMemoryHost.close
    failures = []

    def query(host, task, now):
        if task["task_id"] == "new-b":
            failures.append(host.options["root"])
            raise HarnessFailed("query_failed")
        return original_query(host, task, now)

    def close(host):
        original_close(host)
        if host.options["root"] in failures:
            raise GateRefused("marker")

    monkeypatch.setattr(t0.HermesMemoryHost, "query", query)
    monkeypatch.setattr(t0.HermesMemoryHost, "close", close)
    with pytest.raises(GateRefused):
        factory.invariants(5)
    assert len(failures) == 1
    assert created and all(host.closed == 1 for host in created)
    factory.refusals.clear()


@pytest.mark.parametrize("always", [False, True])
def test_invariant_snapshot_infrastructure(fake_hosts, installed, tmp_path, monkeypatch, always):
    fake_worker_python(tmp_path)
    factory, created = fake_hosts
    original = t0._Factory.snapshot
    attempts = []

    def snapshot(attempt, adapter):
        if "INV-FORGET" in attempt.unit.parts:
            attempts.append(attempt.unit)
            if always or len(attempts) <= 2:
                raise OSError("snapshot failed")
        return original(attempt, adapter)

    monkeypatch.setattr(t0._Factory, "snapshot", snapshot)
    empty_audit = t0._audit([])
    monkeypatch.setattr(t0, "_audit", lambda factories, *a: dict(empty_audit))
    out = tmp_path / "out"
    assert run(installed, out, system="hermes-native", packs=[factory.pack.rel], hermes=tmp_path,
               entry=factory.entry | dict(fresh_install_hash="1" * 64)) == (2 if always else 0)
    assert len(attempts) == len(set(attempts)) == 3
    assert [p.name for p in attempts] == ["a0", "a1", "a2"]
    verdicts = json.loads((out / "adapter_invariants.json").read_bytes())
    expected = adapter_invariants(ReferenceStore, bound_s=5)
    for verdict in verdicts:
        assert Verdict(**verdict).to_obj() == verdict
        if always and verdict["invariant"] == "INV-FORGET":
            assert verdict == Verdict("INV-FORGET", "INFRA_FAILURE", 3, 0, (), (),
                ("forget-1", "forget-2", "forget-store"), ("infra",)).to_obj()
        else:
            assert verdict == expected[verdict["invariant"]].to_obj()
    assert created and all(host.closed == 1 for host in created)
    card = json.loads((out / factory.pack.rel / "card.json").read_bytes())
    validate("card_ring0", card)
    assert card["run_status"] == ("BLOCKED" if always else "COMPLETE")
    assert card["gate_verdict"] == ("BLOCKED" if always else "PASS")
    assert not (out / "work").exists()


@pytest.mark.parametrize("fault", [HarnessFailed("worker_start"), OSError("serve bind failed")])
def test_invariant_construction_infrastructure(fake_hosts, monkeypatch, fault):
    factory, created = fake_hosts
    calls = []

    def broken(*args, **kwargs):
        calls.append(kwargs["root"])
        raise fault

    monkeypatch.setattr(t0, "HermesMemoryHost", broken)
    verdicts = factory.invariants(5)
    assert len(calls) == len(set(calls)) == 3 * len(t0.INVARIANTS)
    assert all(v.status == "INFRA_FAILURE" and v.reasons == ("infra",)
               and not v.failed and not v.inconclusive and v.infra for v in verdicts.values())
    assert created == []


def assert_no_results(out):
    assert not any(p.name in {"card.json", "receipt.json", "junit.xml"} for p in out.rglob("*"))


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt, SystemExit])
def test_write_failure_cleans_results(installed, tmp_path, monkeypatch, capsys, error):
    out, calls = tmp_path / "out", []
    real = t0.write_run

    def write(directory, **kwargs):
        calls.append(directory)
        if len(calls) == 2:
            raise error("second pack")
        return real(directory, **kwargs)

    monkeypatch.setattr(t0, "write_run", write)
    if error is OSError:
        assert run(installed, out) == 70
        stderr = capsys.readouterr().err
        assert stderr.splitlines()[0] == "tool_failure"
        assert "Traceback (most recent call last):" in stderr and "OSError: second pack" in stderr
    else:
        with pytest.raises(error, match="second pack"):
            run(installed, out)
    assert len(calls) == 2
    assert_no_results(out)
    assert not (out / "staging").exists() and not (out / "refusal.json").exists()


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_pack_move_failure_rolls_back(installed, tmp_path, monkeypatch, capsys, error):
    out, moves = tmp_path / "out", []
    real = t0.os.replace

    def move(source, target):
        source, target = Path(source), Path(target)
        if source.parent == out / "staging":
            moves.append(source.name)
            if source.name == "pack":
                raise error("pack move")
        return real(source, target)

    monkeypatch.setattr(t0.os, "replace", move)
    if error is OSError:
        assert run(installed, out) == 70
        assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    else:
        with pytest.raises(error, match="pack move"):
            run(installed, out)
    assert moves == ["adapter_invariants.json", "relations.json", "relations.xml", "pack"]
    assert_no_results(out)
    assert not any(out.iterdir())


def test_publication_order_and_bytes(installed, tmp_path, monkeypatch):
    out, moves, staged = tmp_path / "out", [], {}
    real = t0.os.replace

    def move(source, target):
        source, target = Path(source), Path(target)
        if source.parent == out / "staging":
            moves.append(source.name)
            assert target == out / source.name
            files = source.rglob("*") if source.is_dir() else (source,)
            staged.update({p.relative_to(out / "staging"): p.read_bytes()
                           for p in files if p.is_file()})
        return real(source, target)

    monkeypatch.setattr(t0.os, "replace", move)
    assert run(installed, out) == 0
    assert moves == ["adapter_invariants.json", "relations.json", "relations.xml", "pack"]
    assert {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()} == staged
    assert not (out / "staging").exists()


def test_preflight_tool_failure(installed, tmp_path, monkeypatch, capsys):
    def broken(**kwargs):
        raise RuntimeError("preflight failed")

    monkeypatch.setattr(t0, "_preflight", broken)
    out = tmp_path / "out"
    assert run(installed, out) == 70
    stderr = capsys.readouterr().err
    assert stderr.splitlines()[0] == "tool_failure"
    assert "RuntimeError: preflight failed" in stderr
    assert not out.exists()


def test_refusal_write_failure_cleans_results(installed, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    real = Path.write_bytes

    def refused(*args, **kwargs):
        raise t0.T0Refused("test_refusal")

    def write(path, data):
        if path == out / "refusal.json":
            real(path, data[:1])
            raise OSError("refusal write")
        return real(path, data)

    monkeypatch.setattr(t0, "_execute", refused)
    monkeypatch.setattr(Path, "write_bytes", write)
    assert run(installed, out) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    assert not any(out.iterdir())


def test_pack_move_failure_rolls_back_despite_cleanup_failure(installed, tmp_path, monkeypatch, capsys):
    out, cache = tmp_path / "out", tmp_path / "cache"
    cache.mkdir()
    (cache / "keep").write_bytes(b"cache")
    real_move, real_remove = t0.os.replace, t0.shutil.rmtree

    def move(source, target):
        if Path(source) == out / "staging/pack":
            raise OSError("pack move")
        return real_move(source, target)

    def remove(path, *args, **kwargs):
        if Path(path) == out / "staging":
            raise OSError("cleanup failed")
        return real_remove(path, *args, **kwargs)

    monkeypatch.setattr(t0.os, "replace", move)
    monkeypatch.setattr(t0.shutil, "rmtree", remove)
    assert run(installed, out, cache=cache) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    assert {p.name for p in out.iterdir()} == {"staging"}
    assert (cache / "keep").read_bytes() == b"cache"


def test_pack_move_failure_rolls_back_preserves_cache(installed, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    cache = out / "pack"
    real_controls, real_move = t0._controls, t0.os.replace

    def controls(pack, index, cache):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "keep").write_bytes(b"cache")
        return real_controls(pack, index, cache)

    def move(source, target):
        if Path(source) == out / "staging/pack":
            raise OSError("pack move")
        return real_move(source, target)

    monkeypatch.setattr(t0, "_controls", controls)
    monkeypatch.setattr(t0.os, "replace", move)
    assert run(installed, out, cache=cache) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    assert_no_results(out)
    assert {p.name for p in out.iterdir()} == {"pack"}
    assert (cache / "keep").read_bytes() == b"cache"


def test_cache_at_staging_survives_failure(installed, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    cache = out / "staging"
    real_controls = t0._controls

    def controls(pack, index, cache):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "keep").write_bytes(b"cache")
        return real_controls(pack, index, cache)

    monkeypatch.setattr(t0, "_controls", controls)
    # The cache occupies the staging path, so staging cannot start; the cache must survive.
    assert run(installed, out, cache=cache) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    assert_no_results(out)
    assert (cache / "keep").read_bytes() == b"cache"


@pytest.mark.parametrize("changes,code", [
    (dict(system="nomemory"), "unknown_system"), (dict(system="no-memory"), "harness_not_hermes"),
    (dict(system="hermes-native", entry=load(REGISTRY / "hermes-native.toml") |
          dict(fresh_install_hash=ZERO_HASH)), "unmeasured:fresh_install_hash"),
    (dict(packs=["unknown"]), "unknown_pack"), (dict(pack_hash="0" * 64), "pinned_artifact_changed"),
    (dict(mode="hermes"), "mode_unavailable:hermes")])
def test_library_refusals(installed, tmp_path, capsys, changes, code):
    out = tmp_path / "out"
    assert run(installed, out, **changes) == 3
    assert code in capsys.readouterr().err
    assert_no_results(out)


@pytest.mark.parametrize("extra,seed,code", [
    ([], "random", "hashseed"), (["--workers", "0"], "0", "usage"),
    (["--unknown"], "0", "usage")])
def test_cli_preconditions(installed, tmp_path, extra, seed, code):
    out = tmp_path / "out"
    result = subprocess.run(cli_command(installed, out, *extra), capture_output=True, text=True,
                            env=dict(os.environ, PYTHONHASHSEED=seed))
    assert result.returncode == 3 and code in result.stderr
    assert_no_results(out)


def test_cli_dispatch_order(installed, tmp_path, monkeypatch):
    from bicentennial import cli

    calls = []
    monkeypatch.setattr(cli, "reexec_niced", lambda args: calls.append(args))
    monkeypatch.setattr(cli, "run_t0", lambda **args: calls.append(args) or 2)
    args = cli_command(installed, tmp_path / "out")[3:]
    assert cli.main(args) == 2
    assert calls[0] == ["-m", "bicentennial.cli", *args]
    assert calls[1]["workers"] == 1 and calls[1]["mode"] == "api"


def test_existing_out_and_operator_refused(installed, tmp_path, monkeypatch, capsys):
    assert run(installed, tmp_path) == 3
    assert "out_exists" in capsys.readouterr().err
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    assert run(installed, tmp_path / "operator", system="lcm-x") == 3
    assert "benchmark_operator_forbidden" in capsys.readouterr().err


def test_busy_before_host(installed, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", "printf '{\"glm\":false,\"state\":\"busy\"}'; exit 11")
    monkeypatch.setattr(t0, "HermesMemoryHost", lambda *a, **kw: pytest.fail("host constructed"))
    entry = load(REGISTRY / "hermes-native.toml") | dict(fresh_install_hash="1" * 64)
    assert run(installed, tmp_path / "out", system="hermes-native", entry=entry, hermes=tmp_path) == 3
    assert "marker exit 11" in capsys.readouterr().err


def test_last_pack_spend_refuses_before_publication(installed, tmp_path, monkeypatch, capsys):
    original, receipts = t0.build_receipt, []

    def positive(**kwargs):
        receipt = original(**kwargs)
        receipts.append(receipt)
        if len(receipts) == len(installed[1]["packs"]):
            receipt["spend_micro_usd"] = 1
        return receipt

    monkeypatch.setattr(t0, "build_receipt", positive)
    out = tmp_path / "out"
    assert run(installed, out) == 3
    assert "SpendRefused" in capsys.readouterr().err
    assert len(receipts) == 7
    assert_no_results(out)
    assert json.loads((out / "refusal.json").read_bytes())["code"] == "SpendRefused"


def test_run_lock_mismatch_is_durable(installed, tmp_path, monkeypatch):
    original, changed = t0._commit, False

    class Broken(ReferenceStore):
        def query(self, task, now):
            nonlocal changed
            if task["task_id"] not in {"verb-1", "verb-2", "verb-3", "new-a", "new-b",
                                      "pair-call", "pair-result", "forget-1", "forget-2"}:
                changed = True
                raise HarnessFailed("ipc")
            return super().query(task, now)

    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Broken)
    monkeypatch.setattr(t0, "_commit", lambda: "2" * 40 if changed else original())
    out = tmp_path / "out"
    assert run(installed, out, workers=1) == 3
    assert_no_results(out)
    assert json.loads((out / "refusal.json").read_bytes()) == dict(code="lock_mismatch",
        fields=["analysis_commit", "benchmark_commit", "director_commit"])


@pytest.mark.parametrize("mutation", ["append", "mode"])
def test_installed_mutation_refused(installed, tmp_path, mutation, capsys):
    copied = tmp_path / "installed"
    shutil.copytree(installed[0], copied)
    target = copied / sorted(installed[1]["packs"])[0] / "sealed/pack.json"
    try:
        target.chmod(0o644)
        if mutation == "append":
            target.write_bytes(target.read_bytes() + b" ")
            target.chmod(0o444)
        out = tmp_path / "out"
        assert run(installed, out, packs_dir=copied) == 3
        assert "pinned_artifact_changed" in capsys.readouterr().err
        assert_no_results(out)
    finally:
        for p in [copied, *sorted(copied.rglob("*"))]:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_second_verify_precedes_any_result(installed, tmp_path, monkeypatch):
    original, calls = t0.verify, []

    def verify(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2:
            raise t0.PinnedArtifactChanged(["test_pin"])
        return original(*args, **kwargs)

    monkeypatch.setattr(t0, "verify", verify)
    out = tmp_path / "out"
    assert run(installed, out) == 3
    assert len(calls) == 2 and "lock" in calls[1]
    assert_no_results(out)
    assert json.loads((out / "refusal.json").read_bytes())["fields"] == ["test_pin"]


def test_c7_whole_run_refusal_before_host(installed, tmp_path, monkeypatch):
    fake_worker_python(tmp_path)
    original = t0.c7_entries

    def missing(path):
        entries = dict(original(path))
        del entries[packs(installed)[0].template.ref]
        return entries

    monkeypatch.setattr(t0, "c7_entries", missing)
    monkeypatch.setattr(t0, "HermesMemoryHost", lambda *a, **kw: pytest.fail("host constructed"))
    entry = load(REGISTRY / "hermes-native.toml") | dict(fresh_install_hash="1" * 64)
    out = tmp_path / "out"
    assert run(installed, out, system="hermes-native", entry=entry, hermes=tmp_path) == 3
    assert_no_results(out)


@pytest.mark.parametrize("during", ["factory", "settle"])
def test_invariant_refusal_is_exit_three(installed, tmp_path, monkeypatch, during):
    def refuse(*a, **kw):
        raise GateRefused("marker")

    if during == "factory":
        monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", refuse)
    else:
        class Refused(ReferenceStore):
            def settle(self, bound_s):
                raise GateRefused("marker")

        monkeypatch.setitem(t0.REFERENCE_SYSTEMS, "reference_store", Refused)
    out = tmp_path / "out"
    assert run(installed, out) == 3
    assert_no_results(out)


@pytest.mark.parametrize("rows,egress,refused", [
    ([dict(served_by="scripted", upstream=[dict(served_by="scripted", diagnostics=[])])], [], False),
    ([dict(upstream=[dict(error="failed")])], [], False),
    ([dict(served_by="live")], [], True),
    ([dict(served_by="scripted", upstream=[dict(served_by="live")])], [], True),
    ([dict(upstream=[dict(served_by="scripted", diagnostics=["forward"])])], [], True),
    ([], ["remote:443"], True)])
def test_audit_scripted_attempt_boundary(tmp_path, rows, egress, refused):
    host = SimpleNamespace(records=lambda: rows,
        egress=SimpleNamespace(summary=lambda: dict(non_loopback=egress, failed_samples={"ValueError": 1})),
        paths=dict(root=tmp_path), gate=[], pids=[], server=SimpleNamespace(port=1234), growth=0,
        director=SimpleNamespace(run_values=dict(sandbox_root=str(tmp_path), director_port="1234")))
    factories = [SimpleNamespace(hosts=[host])]
    if refused:
        with pytest.raises(t0.T0Refused, match="upstream_record"):
            t0._audit(factories)
    else:
        assert t0._audit(factories)["records"] == rows
        assert t0._audit(factories * 2)["failed_samples"] == {"ValueError": 2}


@pytest.mark.parametrize("egress", [True, False, "both"])
def test_audit_refusal_detail(installed, tmp_path, monkeypatch, capsys, egress):
    endpoint = "egress name=*:* pid=40 comm=worker samples=2"
    rows = [dict(served_by="live"), dict(req="request-7", upstream=[
        dict(served_by="live"), dict(served_by="scripted", diagnostics=["synthetic"]),
        dict(error="refused"), dict(served_by="scripted")])]
    summary = dict(non_loopback=["*:*"], non_loopback_seen=[endpoint]) if egress else dict(non_loopback=[])
    summary["alive_at_stop"] = False
    host = SimpleNamespace(records=lambda: [] if egress is True else rows,
                           egress=SimpleNamespace(summary=lambda: summary))

    def execute(*args, **kwargs):
        t0._audit([SimpleNamespace(hosts=[host])])

    monkeypatch.setattr(t0, "_execute", execute)
    out = tmp_path / "out"
    assert run(installed, out) == 3
    assert_no_results(out)
    assert capsys.readouterr().err == "upstream_record\n"
    assert json.loads((out / "refusal.json").read_bytes()) == dict(code="upstream_record", fields=[],
        detail=([endpoint] if egress else []) + ([] if egress is True else ["record id=0 served_by=live",
            "record id=request-7 served_by=live", "record id=request-7 served_by=scripted diagnostics"]))


def test_response_usage_streams(tmp_path):
    store = t0.BlobStore(tmp_path / "ledger/blobs", t0.Guard([]))
    req = store.put(dict(messages=[]))
    responses = [dict(usage=dict(prompt_tokens=5, completion_tokens=2)),
                 dict(sse=[dict(usage=None), dict(usage=dict(input_tokens=7, output_tokens=3))]),
                 dict(sse=[dict(type="response.completed", response=dict(usage=dict(input_tokens=11,
                                                                                   output_tokens=4)))])]
    rows = [dict(type="request", req=req, resp=store.put(r), role="extraction", t_ms=10)
            for r in responses]
    host = SimpleNamespace(records=lambda: rows,
        egress=SimpleNamespace(summary=lambda: dict(non_loopback=[])),
        paths=dict(root=tmp_path), gate=[], pids=[], server=SimpleNamespace(port=1234), growth=0,
        director=SimpleNamespace(run_values=dict(sandbox_root=str(tmp_path), director_port="1234")))
    audited = t0._audit([SimpleNamespace(hosts=[host])])
    assert audited["tokens"] == dict(extraction=(23, 9))
    assert audited["runtime"] == dict(extraction=30)


@pytest.fixture
def stub_hosts(tmp_path, monkeypatch):
    from bicentennial.harness.hermes.plugin_host import WORKER

    write_tree = runpy.run_path(str(ROOT / "tests/harness/hermes_stub.py"))["write_tree"]
    created, denied = [], []
    raw = t0.HermesMemoryHost

    class SpyHost(raw):
        def __init__(self, *args, **kwargs):
            if denied:
                raise denied[0]
            try:
                super().__init__(*args, **kwargs)
            except Exception as error:
                denied.append(error)
                raise
            self.close_calls, self.calls = 0, []
            created.append(self)

        def ingest(self, event):
            try:
                return super().ingest(event)
            except PermissionError as error:
                denied.append(error)
                raise

        def settle(self, bound_s):
            self.calls.append("settle")
            return super().settle(bound_s)

        def checkpoint(self):
            assert self.calls[-1] == "settle"
            self.calls.append("checkpoint")
            return super().checkpoint()

        def probe(self, task, now):
            assert self.calls[-1] == "settle"
            self.calls.append("probe")
            return super().probe(task, now)

        def begin_session(self, index):
            assert index > 1 and self.calls[-1] == "settle"
            self.calls.append("begin_session")
            return super().begin_session(index)

        def close(self):
            self.close_calls += 1
            assert self.close_calls == 1
            # Audit before the runner removes the unit.
            assert not self.egress.summary()["non_loopback"]
            assert all(r.get("served_by") != "live" and all(
                a.get("served_by") == "scripted" or "error" in a for a in r.get("upstream", []))
                for r in self.records())
            result = super().close()
            for pid in self.pids:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    pytest.fail(f"worker survived: {pid}")
            visible = self.paths["workspace"] / "pack"
            for path in sorted(visible.rglob("*")):
                if path.is_file():
                    assert build.CANARY.encode() not in path.read_bytes()
            return result

    monkeypatch.setattr(t0, "HermesMemoryHost", SpyHost)

    def options(mode="none", max_length=None):
        checkout = write_tree(tmp_path / ("stub-" + mode), log=tmp_path / (mode + "-calls.jsonl"), mode=mode,
                              max_length=max_length)
        return dict(system="hermes-native", entry=load(REGISTRY / "hermes-native.toml") |
                    dict(fresh_install_hash="1" * 64), host_overrides=dict(
                    checkout=checkout, worker_argv=[sys.executable, str(WORKER)]))

    yield options, created, denied
    assert all(host.close_calls == 1 for host in created)


def test_actual_stub_host_outputs_and_determinism(installed, tmp_path, stub_hosts):
    options, created, denied = stub_hosts
    kwargs = options()
    outputs = []
    for name in ("one", "two"):
        out = tmp_path / name
        code = run(installed, out, **kwargs)
        if denied:
            raise denied[0]
        assert code in (0, 1)
        validate_outputs(out, installed)
        outputs.append(stable_files(out))
    assert outputs[0] == outputs[1]
    assert created and all(h.close_calls == 1 for h in created)
    print("stub_card_sha256=" + json.dumps({p: sha256(data).hexdigest() for p, data in outputs[0].items()
                                          if p.endswith("card.json")}, sort_keys=True))


@pytest.mark.parametrize("limit", [None, 3])
def test_t0_delivery_properties_count_all_hosts_and_repeat(installed, tmp_path, stub_hosts, limit):
    options, created, denied = stub_hosts
    kwargs = options(max_length=limit)
    repeated = []
    for name in ("one", "two"):
        first = len(created)
        out = tmp_path / name
        assert run(installed, out, **kwargs) in (0, 1)
        assert not denied
        hosts = created[first:]
        expected = sum(h.write_clipped for h in hosts)
        assert hosts and (expected > 0 if limit is not None else expected == 0)
        rows = []
        for rel in sorted(installed[1]["packs"]):
            suite = ET.parse(out / rel / "junit.xml").getroot()[0]
            props = {p.attrib["name"]: p.attrib["value"] for p in suite.findall("properties/property")}
            assert props["t0.write_clipped"] == str(expected)
            assert props["t0.fields"] == canon({"actor": "not_delivered", "text":
                "full" if limit is None else f"clipped:{limit}", "time": "session_clock"}).decode()
            if limit is None:
                assert "t0.write_max_length" not in props
            else:
                assert props["t0.write_max_length"] == str(limit)
            rows.append(ET.tostring(suite.find("properties")))
        repeated.append(rows)
    assert repeated[0] == repeated[1]
    reference = tmp_path / "reference"
    assert run(installed, reference) == 0
    for rel in installed[1]["packs"]:
        props = ET.parse(reference / rel / "junit.xml").getroot().findall(".//property")
        assert not {p.attrib["name"] for p in props} & {
            "t0.write_clipped", "t0.write_max_length", "t0.fields"}


def test_actual_stub_keep_on_remove(installed, tmp_path, stub_hosts):
    options, _, denied = stub_hosts
    out = tmp_path / "out"
    code = run(installed, out, **options("keep_on_remove"))
    if denied:
        raise denied[0]
    assert code == 1
    verdicts = json.loads((out / "adapter_invariants.json").read_bytes())
    assert next(v for v in verdicts if v["invariant"] == "INV-FORGET")["status"] == "FAIL"


def test_stub_busy_after_start(installed, tmp_path, stub_hosts, monkeypatch):
    from bicentennial.harness.hermes import plugin_host
    from bicentennial.runner.guard import Marker

    options, created, _ = stub_hosts
    monkeypatch.setattr(plugin_host, "read_marker", lambda: Marker(11, False, "busy"))
    out = tmp_path / "out"
    assert run(installed, out, **options()) == 3
    assert created and all(h.pids == [] for h in created)
    assert_no_results(out)
    assert json.loads((out / "refusal.json").read_bytes())["code"] == "gate_refused"


def test_close_error_preserves_system_cause(installed, tmp_path):
    class Broken(ReferenceStore):
        def query(self, task, now):
            raise ValueError("system call")

        def close(self):
            raise HarnessFailed("cleanup")

    results, outcomes, _ = t0.drive_branch(packs(installed)[0], "B0", Broken, bound_s=5,
                                          snapshot=snapshotter(tmp_path))
    assert not results and all(o["failure_class"] == "SYSTEM_FAILURE" for o in outcomes.values())


def test_model_cache_prepare(installed, tmp_path, monkeypatch):
    from bicentennial.systems import hermes_plugin as hp

    cache = tmp_path / "models"
    cache.mkdir()
    (cache / "weights").write_bytes(b"fixture")
    monkeypatch.setitem(hp.WORKER_ENV, "holographic", {"MODEL_HOME": "{model_cache}"})
    kw = dict(system="holographic", hermes=tmp_path, plugin_source=tmp_path,
              host_overrides={"worker_argv": ["fake"]})
    with pytest.raises(t0.T0Refused, match="^missing_input$"):
        preflight(installed, **kw)
    prepared = preflight(installed, model_cache=cache, **kw)
    assert prepared[6]["extra_env"] == {"MODEL_HOME": str(cache)}
    assert prepared[6]["model_cache_sha256"] == hp.cache_digest(cache, t0.T0Refused)


@pytest.mark.parametrize("changed", [False, True])
def test_model_cache_end_digest_and_property(installed, tmp_path, monkeypatch, changed):
    from bicentennial.systems import hermes_plugin as hp

    cache = tmp_path / "models"
    cache.mkdir()
    model = cache / "weights"
    model.write_bytes(b"fixture")
    digest = hp.cache_digest(cache, t0.T0Refused)
    # Reference hosts keep this finalization test independent of worker scheduling.
    prepared = list(preflight(installed, selected=[packs(installed)[0].rel]))
    prepared[6] = dict(model_cache=cache, model_cache_sha256=digest)
    monkeypatch.setattr(t0, "_preflight", lambda **kw: tuple(prepared))
    if changed:
        real = t0._report_pack

        def mutate(*args, **kw):
            report = real(*args, **kw)
            model.write_bytes(b"changed")
            return report

        monkeypatch.setattr(t0, "_report_pack", mutate)
    out = tmp_path / "out"
    code = run(installed, out)
    if changed:
        assert code == 3
        assert json.loads((out / "refusal.json").read_bytes())["code"] == "model_cache_changed"
        assert_no_results(out)
    else:
        assert code in (0, 1, 2)
        xml = next(out.rglob("junit.xml")).read_text()
        assert 'name="t0.model_cache" value="sha256:' + digest + '"' in xml
