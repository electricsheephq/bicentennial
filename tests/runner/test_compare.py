"""T1 ordered gates, offline corpus attribution and publication acceptance."""

import ast
import json
import os
import runpy
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial import cli
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.controls.cache import ControlsTampered
from bicentennial.corpus.run import CaseResult
from bicentennial.harness import egress
from bicentennial.harness.hermes import adapter, plugin_host
from bicentennial.harness.hermes.adapter import HarnessFailed, PinMismatch
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.keyed import choice
from bicentennial.ledger import BlobStore, Guard, LedgerBusy, stable_digest
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.report.determinism import determinism_check
from bicentennial.report.receipt import loop_time
from bicentennial.runner import compare, t0, t1
from bicentennial.runner.lock import LockMismatch
from bicentennial.sandbox import fixedroot
from bicentennial.score.classes import IDENTITY, outcome
from bicentennial.score.invariants import GATED_T1, INVARIANTS, Verdict
from bicentennial.systems.controls import WIPED_LABEL
from bicentennial.systems.registry import SystemRefused

# Reuse the installed real packs, compiled fake worker and executed policy evidence.
shared = runpy.run_path(str(Path(__file__).with_name("test_t1.py")))
installed, policy, replay = (shared[k] for k in ("installed", "policy", "replay"))
measured = shared["measured"]
SUBSET = ("g1-recall-value-dir-2.wipe_on_restart", "g2-drift-asof-dir-1.stale_wins")
STABLE = ("card.json", "junit.xml", "invariants.json", "corpus.json", "controls.json")
RESULTS = (*STABLE, "receipt.json")


@pytest.fixture(scope="module", autouse=True)
def synthetic_egress():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(egress, "_out", lambda argv: "8" if argv[:3] == ["ps", "-o", "rss="] else "")
        yield


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    monkeypatch.setattr(plugin_host, "assert_niced", lambda pid: None)
    monkeypatch.setattr(t1, "check_compile", lambda *a, **kw: {"ok": True})


@pytest.fixture(scope="module")
def cases():
    all_cases = compare.load_corpus(compare.CORPUS_PATH)
    result = tuple(c for c in all_cases if c.case_id in SUBSET)
    assert len(result) == 2
    return result


def fake_case(case, factory, **kwargs):
    assert kwargs["infra"] == compare.INFRA
    return CaseResult(case.case_id, "PASS", "", None) if factory.arm == "system" else CaseResult(
        case.case_id, "FAIL", "mismatch", case.items[0])


def invoke(installed, out, **kwargs):
    return compare.run_t1(**(dict(system="hermes-native", packs_dir=installed.root,
        pack_hash=installed.digest, out=out, entry=measured(), worker_argv=installed.worker) | kwargs))


def read(out, arm="system", name="card.json"):
    return json.loads((out / arm / name).read_bytes())


def properties(out, arm):
    root = ET.parse(out / arm / "junit.xml").getroot()
    return {p.attrib["name"]: p.attrib["value"] for p in root[0].findall("properties/property")}


def valid(out):
    for arm in compare.GATED:
        card, receipt = read(out, arm), read(out, arm, "receipt.json")
        validate("card_ring0", card)
        validate("receipt", receipt)
        assert card["run_status"] == receipt["run_status"]


def no_results(out):
    assert not any(p.name in RESULTS for p in out.rglob("*") if p.is_file())
    assert not (out / "work").exists() and not (out / "corpus-work").exists()


@pytest.fixture(scope="module")
def completed(installed, cases, tmp_path_factory):
    root = tmp_path_factory.mktemp("compare-full")
    patch = pytest.MonkeyPatch()
    patch.setattr(fixedroot, "PARENT", os.path.realpath(tmp_path_factory.mktemp("fixedroot")))
    patch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    patch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    patch.setattr(adapter, "assert_niced", lambda pid: None)
    patch.setattr(plugin_host, "assert_niced", lambda pid: None)
    patch.setattr(t1, "check_compile", lambda *a, **kw: {"ok": True})
    patch.setattr(compare, "load_corpus", lambda path: cases)
    patch.setattr(compare, "run_case", fake_case)
    real, runs, gates = t1.run_life, [], []
    gate = compare.t1_gate

    def drive(**kwargs):
        result = real(**kwargs)
        runs.append(result)
        return result

    def gated(*args, **kwargs):
        result = gate(*args, **kwargs)
        gates.append(result.to_obj())
        return result

    patch.setattr(t1, "run_life", drive)
    patch.setattr(compare, "t1_gate", gated)
    try:
        for name in ("one", "two"):
            out = root / name
            code = invoke(installed, out)
            assert code == 0, gates[-2:]
            assert read(out)["gate_verdict"] == "CONFORMANCE_PASS", gates[-2:]
            assert read(out, "wiped")["gate_verdict"] == "FAIL", gates[-2:]
            assert read(out, "system", "controls.json")["floor_mismatches"] == [], gates[-2:]
            assert not (out / "work").exists() and not (out / "corpus-work").exists()
        assert len(runs) == 24
        for arm in compare.GATED:
            for name in STABLE:
                left, right = ((root / p / arm / name).read_bytes() for p in ("one", "two"))
                if left != right:
                    detail = determinism_check(left, right) if name == "card.json" else name
                    pytest.fail(f"STOP: stable output differs: {detail}")
            card = (root / "one" / arm / "card.json").read_bytes()
            print(f"compare {arm} card_sha256={sha256(card).hexdigest()}", flush=True)
    finally:
        # Undo before yielding: later tests in this module use the real run_case and load_corpus.
        patch.undo()
    yield SimpleNamespace(root=root, runs=runs, gates=gates)


def test_full_run(completed, installed, cases):
    out = completed.root / "one"
    assert {p.name for p in out.iterdir()} == {"system", "wiped"}
    valid(out)
    expected = {i["item_id"] for p in t1.prepare(system="hermes-native", packs=installed.root,
        pack_hash=installed.digest, entry=measured(), worker_argv=installed.worker).packs
        for i in p.pack["items"]}
    for arm in compare.GATED:
        card = read(out, arm)
        assert {i["item_id"] for i in card["items"]} == expected
        assert card["run_status"] == "COMPLETE" and card["controls"]["wiped_store"] == "FAIL"
        assert "scripted_model" in card["labels"]
        invariants = read(out, arm, "invariants.json")
        assert [v["invariant"] for v in invariants] == list(INVARIANTS)
        assert read(out, arm, "corpus.json") == [fake_case(c, SimpleNamespace(arm=arm),
            infra=compare.INFRA).to_obj() for c in cases]
        controls = read(out, arm, "controls.json")
        assert set(controls) == {"canary", "label", "wipes", "floor_mismatches"}
        assert len(controls["wipes"]) == 4 and controls["floor_mismatches"] == []
        ms, busy = loop_time(read(out, arm, "receipt.json"))
        assert ms > 0 and busy is False
        receipt = read(out, arm, "receipt.json")
        pooled = [f for f in completed.runs[:12] if f.arm in (
            ("system", "no_memory") if arm == "system" else ("wiped",))]
        assert receipt["store_growth_bytes"] == sum(f.store_growth_bytes for f in pooled) > 0
        assert receipt["process_ids"] == sorted({p for f in pooled for p in f.process_ids})
        assert all(f.process_ids for f in pooled)
        roles = {r["role"] for f in pooled for r in f.records if r.get("type") == "request"}
        assert {r["role"] for r in receipt["tokens_by_role"]} == roles
        for key, index in (("input", 0), ("output", 1)):
            assert receipt["tokens"][key] == sum(f.tokens_by_role[r][index]
                for f in pooled for r in f.tokens_by_role) > 0
        suites = ET.parse(out / arm / "junit.xml").getroot()
        names = [s.attrib["name"] for s in suites]
        prefix = f"ring0.T1.hermes-native.{arm}"
        assert names == [prefix, prefix + ".invariants", prefix + ".corpus"] + (
            ["ring0.T1.hermes-native.no_memory"] if arm == "system" else [])
        props = properties(out, arm)
        assert props["t1.write_clipped"] == "0"
        assert props["t1.forget_kept"] == '{"ambiguous":0,"same_text":0,"unattributed":0}'
        assert "t1.write_max_length" not in props
        assert props["t1.fields"] == canon({"actor": "not_delivered", "text": "full",
                                            "time": "session_clock"}).decode()
        assert all(props[k] == v for k, v in compare.DISCLOSURES)
        assert not any(k in props for k, _ in compare.PLUGIN_DISCLOSURES)
        assert all(props[k] == "0" for k in ("isolation.unknown_requests", "isolation.forwarded",
                                             "no_memory.gold_in_context"))
        if arm == "wiped":
            assert props["wiped.label"] == WIPED_LABEL
        records = [r for f in completed.runs[:12] if f.arm == arm
                   for r in compare._masked(f.records, f.run_values)]
        first = next(f for f in completed.runs if f.arm == arm)
        assert stable_digest(records, first.run_values) == card["masked_ledger_digest"]
    for name in ("one", "two"):
        for path in (completed.root / name).rglob("*.json"):
            stack = [json.loads(path.read_bytes())]
            while stack:
                value = stack.pop()
                assert type(value) is not float, path
                if isinstance(value, dict):
                    stack.extend(value.values())
                elif isinstance(value, list):
                    stack.extend(value)


def verdicts(arm, changes=None):
    changes = changes or {}
    return tuple(Verdict(name, changes.get(name, "NOT_EXERCISED" if name == "INV-FORGET" else
        "PASS" if arm == "system" else "FAIL"), 0, 0, (), (), (), ()) for name in INVARIANTS)


@pytest.fixture
def synth(replay, monkeypatch, cases):
    run = replay.run()
    arms = {a: replace(r, verdicts=verdicts(a)) if a in compare.GATED else r
            for a, r in run.arms.items()}
    run = replace(run, arms=arms)
    monkeypatch.setattr(t1, "prepare", lambda **kwargs: run.ctx)
    monkeypatch.setattr(compare, "run_arms", lambda ctx, **kwargs: replace(run, ctx=ctx))
    monkeypatch.setattr(compare, "load_corpus", lambda path: cases)
    monkeypatch.setattr(compare, "run_case", fake_case)
    return run


def set_run(monkeypatch, run):
    monkeypatch.setattr(compare, "run_arms", lambda ctx, **kwargs: run)


def test_corpus_delivery_properties_include_retries_and_clones(synth, installed, tmp_path, monkeypatch):
    seen, attempts = {arm: [] for arm in compare.GATED}, {}

    class Host(ReferenceStore):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.write_clipped, self.write_max_length = 0, 3
            self.forget_kept = {("row", "synthetic"): "ambiguous"}

        def begin_session(self, index):
            pass

        def ingest(self, event):
            self.write_clipped += int(len(event["text"]) > self.write_max_length)
            super().ingest(event)

        def fields(self):
            return {"actor": "not_delivered", "text": "clipped:3", "time": "session_clock"}

    def drive(case, factory, **kwargs):
        key = (factory.arm, case.case_id)
        attempts[key] = attempts.get(key, 0) + 1
        for _ in range(2):
            host = factory()
            seen[factory.arm].append(host)
            for i, text in enumerate(("abc", "long event")):
                host.ingest(dict(event_id=str(i), t_sim=i, kind="message", actor="fixture", text=text))
            host.begin_session(2)
        return (CaseResult(case.case_id, "INFRA_FAILURE", "infra", None) if attempts[key] == 1 else
                fake_case(case, factory, **kwargs))

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    monkeypatch.setattr(compare, "run_case", drive)
    out = tmp_path / "out"
    assert invoke(installed, out) == 0
    assert set(attempts.values()) == {2}
    for arm in compare.GATED:
        props = properties(out, arm)
        assert len(seen[arm]) == 4 * len(attempts) // len(compare.GATED)
        assert props["t1.write_clipped"] == str(sum(h.write_clipped for h in seen[arm]))
        assert props["t1.forget_kept"] == canon(dict(
            ambiguous=len(seen[arm]), same_text=0, unattributed=0)).decode()
        assert props["t1.write_max_length"] == "3"
        assert props["t1.fields"] == canon(seen[arm][0].fields()).decode()
    floor = ET.parse(out / "system/junit.xml").getroot()[-1]
    assert not {p.attrib["name"] for p in floor.findall("properties/property")} & {
        "t1.write_clipped", "t1.write_max_length", "t1.fields"}


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt, SystemExit])
def test_write_failure_cleans_results(synth, installed, tmp_path, monkeypatch, capsys, error):
    out, calls = tmp_path / "out", []
    real = compare.write_run

    def write(directory, **kwargs):
        calls.append(directory)
        if len(calls) == 2:
            raise error("second arm")
        return real(directory, **kwargs)

    monkeypatch.setattr(compare, "write_run", write)
    if error is OSError:
        assert invoke(installed, out) == 70
        stderr = capsys.readouterr().err
        assert stderr.splitlines()[0] == "tool_failure"
        assert "Traceback (most recent call last):" in stderr and "OSError: second arm" in stderr
    else:
        with pytest.raises(error, match="second arm"):
            invoke(installed, out)
    assert len(calls) == 2
    no_results(out)
    assert not (out / "staging").exists() and not (out / "refusal.json").exists()


def test_cache_at_staging_survives_failure(synth, installed, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    cache = out / "staging"
    real_controls = compare._controls

    def controls(ctx, cache):
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "keep").write_bytes(b"cache")
        return real_controls(ctx, cache)

    monkeypatch.setattr(compare, "_controls", controls)
    # The cache occupies the staging path, so staging cannot start; the cache must survive.
    assert invoke(installed, out, cache=cache) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    no_results(out)
    assert (cache / "keep").read_bytes() == b"cache"


def test_publication_order_and_bytes(synth, installed, tmp_path, monkeypatch):
    out, moves, staged = tmp_path / "out", [], {}
    real = compare.os.replace

    def move(source, target):
        source, target = Path(source), Path(target)
        if source.parent == out / "staging":
            moves.append(source.name)
            assert target == out / source.name
            assert not (out / "system/card.json").exists()
            if source.name == "system":
                assert (out / "wiped/card.json").is_file()
            staged.update({p.relative_to(out / "staging"): p.read_bytes()
                           for p in source.rglob("*") if p.is_file()})
        return real(source, target)

    monkeypatch.setattr(compare.os, "replace", move)
    assert invoke(installed, out) == 0
    assert moves == ["wiped", "system"]
    assert {p.name for p in out.iterdir()} == {"system", "wiped"}
    assert len(staged) == 2 * len(RESULTS)
    assert all((out / rel).read_bytes() == data for rel, data in staged.items())


@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt])
def test_system_move_failure_rolls_back(synth, installed, tmp_path, monkeypatch, capsys, error):
    out, moves = tmp_path / "out", []
    real = compare.os.replace

    def move(source, target):
        source = Path(source)
        if source.parent == out / "staging":
            moves.append(source.name)
            if source.name == "system":
                raise error("system move")
        return real(source, target)

    monkeypatch.setattr(compare.os, "replace", move)
    if error is OSError:
        assert invoke(installed, out) == 70
        assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    else:
        with pytest.raises(error, match="system move"):
            invoke(installed, out)
    assert moves == ["wiped", "system"]
    no_results(out)
    assert not any(out.iterdir())


def test_preflight_tool_failure(installed, tmp_path, monkeypatch, capsys):
    def broken(**kwargs):
        raise RuntimeError("preflight failed")

    monkeypatch.setattr(t1, "prepare", broken)
    out = tmp_path / "out"
    assert invoke(installed, out) == 70
    stderr = capsys.readouterr().err
    assert stderr.splitlines()[0] == "tool_failure"
    assert "RuntimeError: preflight failed" in stderr
    assert not out.exists()


def test_refusal_write_failure_cleans_results(synth, installed, tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    real = Path.write_bytes

    def refused(*args, **kwargs):
        raise t1.T1Refused("test_refusal")

    def write(path, data):
        if path == out / "refusal.json":
            real(path, data[:1])
            raise OSError("refusal write")
        return real(path, data)

    monkeypatch.setattr(compare, "_execute", refused)
    monkeypatch.setattr(Path, "write_bytes", write)
    assert invoke(installed, out) == 70
    assert capsys.readouterr().err.splitlines()[0] == "tool_failure"
    assert not any(out.iterdir())


def change_arm(run, arm, **changes):
    return replace(run, arms=run.arms | {arm: replace(run.arms[arm], **changes)})


@pytest.mark.parametrize("changes,code,verdict,status", [
    ({}, 0, "CONFORMANCE_PASS", "COMPLETE"),
    ({"INV-VERB": "FAIL"}, 1, "FAIL", "COMPLETE"),
    ({"INV-NEW": "INFRA_FAILURE"}, 2, "BLOCKED", "BLOCKED"),
    ({"INV-VERB": "FAIL", "INV-NEW": "INFRA_FAILURE"}, 1, "FAIL", "BLOCKED"),
])
def test_gate_matrix(synth, installed, monkeypatch, tmp_path, changes, code, verdict, status):
    set_run(monkeypatch, change_arm(synth, "system", verdicts=verdicts("system", changes)))
    out = tmp_path / "out"
    assert invoke(installed, out) == code
    valid(out)
    assert (read(out)["gate_verdict"], read(out)["run_status"]) == (verdict, status)


def test_baseline_order_and_refusals(synth, installed, monkeypatch, tmp_path, capsys):
    first, second = tmp_path / "one", tmp_path / "two"
    assert invoke(installed, first) == 0
    baseline = first / "system/card.json"
    order, raw = [], compare.check_baseline
    monkeypatch.setattr(compare, "check_baseline", lambda *a, **kw: (order.append("baseline"), raw(*a, **kw))[1])
    monkeypatch.setattr(compare, "run_arms", lambda *a, **kw: (order.append("arms"), synth)[1])
    assert invoke(installed, second, baseline=baseline) == 0
    assert order == ["baseline", "arms"] and read(second)["gate_verdict"] == "PASS"
    for name, data, code in (("mismatch", canon(read(first) | {"pins": read(first)["pins"] |
            {"pack_hash": "f" * 64}}), "baseline_mismatch"),
            ("invalid", baseline.read_bytes() + b"\n", "baseline_invalid")):
        path, out = tmp_path / f"{name}.json", tmp_path / name
        path.write_bytes(data)
        order.clear()
        assert invoke(installed, out, baseline=path) == 3
        assert order == ["baseline"] and not out.exists()
        assert code in capsys.readouterr().err


@pytest.mark.parametrize("persistent", [False, True])
def test_corpus_retry(synth, installed, monkeypatch, tmp_path, cases, persistent):
    calls = []

    def case(c, factory, **kwargs):
        if c == cases[0] and factory.arm == "system":
            calls.append(c.case_id)
            if persistent or len(calls) == 1:
                return CaseResult(c.case_id, "INFRA_FAILURE", "infra", None)
        return fake_case(c, factory, **kwargs)

    monkeypatch.setattr(compare, "run_case", case)
    out = tmp_path / "out"
    assert invoke(installed, out) == (2 if persistent else 0)
    assert len(calls) == (3 if persistent else 2)
    valid(out)


def test_corpus_failure_wins_over_blocked_item(synth, installed, monkeypatch, tmp_path):
    outcomes = dict(synth.arms["system"].outcomes)
    iid = next(iter(outcomes))
    outcomes[iid] = outcome({k: outcomes[iid][k] for k in sorted(IDENTITY)}, None,
                            cause="INFRA_FAILURE", infra_reruns=2)
    # Rebuild bundles so all aggregate inputs remain consistent.
    from bicentennial.score.bundle import make_bundle
    bundles = []
    for pack in synth.ctx.packs:
        for b in pack.pack["bundles"]:
            ident = {k: b[k] for k in ("bundle_id", "cell_id", "twin_type")}
            bundles.append(make_bundle(ident | {"life": pack.life}, *(outcomes[i] for i in b["items"])))
    set_run(monkeypatch, change_arm(synth, "system", outcomes=outcomes,
        bundles=tuple(sorted(bundles, key=lambda b: b["bundle_id"]))))
    monkeypatch.setattr(compare, "run_case", lambda c, f, **kw: CaseResult(c.case_id, "FAIL", "mismatch", c.items[0]))
    out = tmp_path / "out"
    assert invoke(installed, out) == 1
    valid(out)
    assert read(out)["run_status"] == "BLOCKED"


@pytest.mark.parametrize("mode", ["wiped_pass", "no_recall", "wiped_blocked", "both"])
def test_wiped_control(synth, installed, monkeypatch, tmp_path, mode):
    run = synth
    if mode == "no_recall":
        run = change_arm(run, "system", recall=(False,))
    else:
        changes = {n: "PASS" for n in GATED_T1}
        if mode in ("wiped_blocked", "both"):
            changes["INV-VERB"] = "INFRA_FAILURE"
            monkeypatch.setattr(compare, "control_status", lambda *a: pytest.fail("BLOCKED control called"))
        run = change_arm(run, "wiped", verdicts=verdicts("wiped", changes))
        monkeypatch.setattr(compare, "run_case", lambda c, f, **kw: CaseResult(c.case_id, "PASS", "", None))
        if mode == "both":
            run = change_arm(run, "system", verdicts=verdicts("system", {"INV-VERB": "FAIL"}))
    set_run(monkeypatch, run)
    out = tmp_path / "out"
    assert invoke(installed, out) == (2 if mode == "wiped_blocked" else 1)
    valid(out)
    assert read(out)["gate_verdict"] == dict(wiped_pass="INVALID", no_recall="FAIL",
        wiped_blocked="BLOCKED", both="FAIL")[mode]
    blocked = json.loads(properties(out, "system")["gate.wiped_blocked"])
    assert blocked == sorted(blocked)
    assert ("invariant:INV-VERB" in blocked) == (mode in ("wiped_blocked", "both"))
    if mode == "wiped_pass":
        assert read(out, "wiped")["gate_verdict"] == "CONFORMANCE_PASS"
    else:
        assert read(out)["controls"]["wiped_store"] == "uninformative"


def test_forwarded_witness_matches_isolation():
    rows = [dict(upstream=[dict(role="summariser", req=1, error="ValueError")]),
            dict(upstream=[dict(served_by="scripted")]), dict(), dict(upstream=[dict(served_by="upstream")])]
    assert compare._isolated(rows[:3], {}) and compare._forwarded(rows[:3]) == 0
    assert not compare._isolated(rows, {}) and compare._forwarded(rows) == 1


@pytest.mark.parametrize("arm,blocked", [("system", False), ("no_memory", False), ("system", True)])
def test_honeypot(synth, installed, monkeypatch, tmp_path, arm, blocked):
    run = change_arm(synth, arm, honeypot_hits=1)
    if blocked:
        run = change_arm(run, "system", verdicts=verdicts("system", {"INV-NEW": "INFRA_FAILURE"}))
    set_run(monkeypatch, run)
    out = tmp_path / "out"
    assert invoke(installed, out) == 1
    valid(out)
    assert all(read(out, a)["gate_verdict"] == "INVALID" for a in compare.GATED)


def test_plugin_disclosures(synth, installed, monkeypatch, tmp_path):
    ctx = replace(synth.ctx, entry=measured("holographic"), plugin_source=tmp_path / "plugin")
    run = replace(synth, ctx=ctx)
    monkeypatch.setattr(t1, "prepare", lambda **kw: ctx)
    set_run(monkeypatch, run)
    out = tmp_path / "out"
    assert invoke(installed, out, system="holographic", entry=ctx.entry, plugin_source=ctx.plugin_source) == 0
    for a in compare.GATED:
        assert all(properties(out, a)[k] == v for k, v in compare.PLUGIN_DISCLOSURES)


def test_spend_preflight(synth, installed, monkeypatch, tmp_path, capsys):
    raw, calls = compare.build_receipt, []

    def receipt(**kwargs):
        calls.append(1)
        return raw(**kwargs) | {"spend_micro_usd": int(len(calls) == 2)}

    monkeypatch.setattr(compare, "build_receipt", receipt)
    out = tmp_path / "out"
    assert invoke(installed, out) == 3
    assert "SpendRefused" in capsys.readouterr().err
    no_results(out)


@pytest.mark.parametrize("where", ["final", "earlier", "floor", "forwarded", "scripted", "diagnostics", "egress"])
def test_isolation_refusal(synth, installed, monkeypatch, tmp_path, where, capsys):
    arm = "no_memory" if where == "floor" else "system"
    units = list(synth.arms[arm].units)
    f = units[0].runs[-1]
    row = {"served_by": "live"} if where in ("final", "earlier", "floor") else {
        "upstream": [{"served_by": "scripted" if where in ("scripted", "diagnostics") else "live"}]}
    if where == "diagnostics":
        row["upstream"][0]["diagnostics"] = ["synthetic"]
    if where in ("forwarded", "diagnostics"):
        row["req"] = "request-7"
    # Isolation executes before report assembly; the passing row needs no digest fields.
    row["type"] = "diagnostic"
    bad = replace(f, records=(row,), run_values=dict(sandbox_root=str(tmp_path), director_port="32109"))
    endpoint = "egress name=*:* pid=40 comm=worker samples=2"
    if where == "egress":
        bad = replace(bad, records=(), egress=dict(non_loopback=["*:*"], non_loopback_seen=[endpoint]))
    units[0] = replace(units[0], runs=(bad, f) if where == "earlier" else (bad,))
    set_run(monkeypatch, change_arm(synth, arm, units=tuple(units)))
    out = tmp_path / "out"
    assert invoke(installed, out) == (0 if where == "scripted" else 3)
    if where != "scripted":
        no_results(out)
        assert capsys.readouterr().err == "upstream_record\n"
        detail = ("record id=request-7 served_by=scripted diagnostics" if where == "diagnostics" else
                  f"record id={'request-7' if where == 'forwarded' else 0} served_by=live")
        detail = endpoint if where == "egress" else detail
        assert json.loads((out / "refusal.json").read_bytes()) == dict(
            code="upstream_record", fields=[], detail=[detail])


@pytest.mark.parametrize("refused", [t0.T0Refused, t1.T1Refused])
def test_refusal_detail_is_sorted_tuple(refused):
    assert refused("upstream_record").detail == ()
    error = refused("upstream_record", detail=["record id=z served_by=live", "record id=a served_by=live"])
    assert error.detail == ("record id=a served_by=live", "record id=z served_by=live")
    assert str(error) == "upstream_record"


@pytest.mark.parametrize("site", ["corpus", "life", "t0"])
@pytest.mark.parametrize("cause", ["endpoint", "dead", "unsampled", "mixed", "mixed-reversed"])
def test_corpus_egress_refusal_detail(synth, installed, monkeypatch, tmp_path, capsys, site, cause):
    detail = "egress name=*:* pid=40 comm=worker samples=2"
    summary = dict(non_loopback=[], alive_at_stop=cause != "dead", failed_samples={"ValueError": 2},
                   unsampled=["egress unsampled pid=40 log=worker.stderr"] if cause == "unsampled" else [])
    code = "upstream_record" if cause == "endpoint" else "egress_unobserved"
    if cause == "endpoint":
        summary.update(non_loopback=["*:*"], non_loopback_seen=[detail], alive_at_stop=False)
    expected = [detail] if cause == "endpoint" else sorted([
        f"egress sampler alive_at_stop={str(cause != 'dead').lower()}",
        "egress failed_samples type=ValueError count=2", *summary["unsampled"]])
    summaries = [summary]
    if cause.startswith("mixed"):
        code, expected = "upstream_record", [detail]
        summaries = [dict(non_loopback=[], unsampled=["egress unsampled pid=40 log=worker.stderr"]),
                     dict(non_loopback=["*:*"], non_loopback_seen=[detail])]
        if cause == "mixed-reversed":
            summaries.reverse()
    hosts = [SimpleNamespace(records=list, egress=SimpleNamespace(summary=lambda s=s: s)) for s in summaries]

    def case(case, factory, **kwargs):
        factory.hosts.extend(hosts)
        return fake_case(case, factory, **kwargs)

    monkeypatch.setattr(compare, "run_case", case)
    if site == "life":
        units = list(synth.arms["system"].units)
        units[0] = replace(units[0], runs=(replace(units[0].runs[-1], egress=summary),))
        set_run(monkeypatch, change_arm(synth, "system", units=tuple(units)))
        if cause.startswith("mixed"):
            monkeypatch.setattr(compare, "_runs", lambda *a: [SimpleNamespace(records=[], egress=s) for s in summaries])
    if site == "t0":
        monkeypatch.setattr(t0, "_preflight", lambda **kw: None)

        def execute(*args, **kwargs):
            t0._audit([SimpleNamespace(hosts=hosts)])

        monkeypatch.setattr(t0, "_execute", execute)
    out = tmp_path / "out"
    assert (t0.run_t0(system="reference_store", packs=[], packs_dir=tmp_path, pack_hash="a" * 64, out=out)
            if site == "t0" else invoke(installed, out)) == 3
    no_results(out)
    assert capsys.readouterr().err == code + "\n"
    assert json.loads((out / "refusal.json").read_bytes()) == dict(
        code=code, fields=[], detail=expected)


@pytest.mark.parametrize("during", [False, True])
def test_lock_refusal(synth, installed, monkeypatch, tmp_path, during):
    fields = ["analysis_commit", "benchmark_commit", "director_commit"]
    if during:
        def refused(*args, **kwargs):
            raise LockMismatch(fields)
        monkeypatch.setattr(compare, "run_arms", refused)
    else:
        monkeypatch.setattr(t1, "_commit", lambda: "f" * 40)
    out = tmp_path / "out"
    assert invoke(installed, out) == 3
    assert json.loads((out / "refusal.json").read_bytes()) == dict(code="lock_mismatch", fields=fields)
    no_results(out)


@pytest.mark.parametrize("error,code", [(GateRefused("gate"), "gate_refused"),
    (PinMismatch("pin"), "pin_mismatch"), (ControlsTampered("controls"), "pinned_artifact_changed"),
    (PinnedArtifactChanged(["artifact"]), "pinned_artifact_changed"),
    (SystemRefused(["z", "a"]), "a,z")])
def test_refusal_mapping(synth, installed, monkeypatch, tmp_path, capsys, error, code):
    def refused(*args, **kwargs):
        raise error
    monkeypatch.setattr(compare, "run_arms", refused)
    out = tmp_path / "out"
    assert invoke(installed, out) == 3
    assert code in capsys.readouterr().err
    no_results(out)


def test_preconditions(installed, tmp_path, capsys):
    out = tmp_path / "out"
    assert invoke(installed, out, system="nomemory", entry=None) == 3
    assert not out.exists() and "unknown_system" in capsys.readouterr().err
    out.mkdir()
    assert invoke(installed, out) == 3
    assert "out_exists" in capsys.readouterr().err


@pytest.mark.parametrize("fault,status,reason,attempts", [
    (None, "PASS", "", 1), (HarnessFailed("query_failed"), "FAIL", "system_failure", 1),
    (HarnessFailed("ipc"), "INFRA_FAILURE", "infra", 3),
    (LedgerBusy("busy"), "INFRA_FAILURE", "infra", 3),
    (OSError("construction"), "INFRA_FAILURE", "infra", 3),
])
def test_corpus_attribution(policy, cases, monkeypatch, tmp_path, fault, status, reason, attempts):
    constructed = []

    class Host(ReferenceStore):
        def __init__(self, *args, **kwargs):
            constructed.append(self)
            if isinstance(fault, OSError):
                raise fault
            super().__init__()

        def query(self, *args):
            if fault:
                raise fault
            return super().query(*args)

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    for c in cases:
        constructed.clear()
        got = compare.corpus(policy.ctx, "system", (c,), catalogue=catalogue(), work=tmp_path / c.case_id)
        assert [(r.status, r.reason) for r in got] == [(status, reason)]
        assert constructed  # the real factory path ran, so a faked run_case cannot pass this
        # Successful cases construct extra hosts at their scheduled restarts.
        if fault:
            assert len(constructed) >= attempts
            assert len(list((tmp_path / c.case_id).rglob("a*"))) == 0
    assert compare.SYSTEM_CAUSES is t0.SYSTEM_CAUSES


def test_corpus_receipt_inputs(policy, cases, monkeypatch, tmp_path):
    row = dict(type="request", role="probe_main", t_ms=7, seq=1, req="q", resp="r", served_by="scripted")

    class Host(ReferenceStore):
        def __init__(self, *args, **kwargs):
            super().__init__()
            self.gate, self.egress = [dict(exit=10, state="row")], SimpleNamespace(summary=dict)

        def records(self):
            return [row]

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    audit, gates = [], []
    compare.corpus(policy.ctx, "system", cases[:1], catalogue=catalogue(), work=tmp_path / "work",
                   audit=audit, gates=gates)
    assert row in audit and dict(exit=10, state="row") in gates


def test_receipt_counts_corpus(synth):
    base = compare._receipt(synth, "system", "COMPLETE", 0, 10)
    assert loop_time(base) == (10, False)
    row = dict(type="request", role="probe_main", t_ms=7, seq=10**6, req="q", resp="r")
    receipt = compare._receipt(synth, "system", "COMPLETE", 0, 10, corpus_rows=[row],
                               corpus_gates=[dict(exit=10, state="row")])
    # A busy reading taken only while the corpus ran still marks the run busy.
    assert loop_time(receipt) == (10, True)

    def probe_ms(r):
        return sum(x["ms"] for x in r["runtime_by_role"] if x["role"] == "probe_main")

    assert probe_ms(receipt) == probe_ms(base) + 7
    assert receipt["latency_ms"] == [*base["latency_ms"], 7]
    assert receipt["raw_body_digest"] != base["raw_body_digest"]


def test_receipt_timing_pool_order_and_missing_egress(synth):
    arms = {}
    expected = []
    for arm, source in synth.arms.items():
        units = []
        for unit in source.units:
            runs = []
            for n, f in enumerate(unit.runs):
                if arm in ("system", "no_memory") and n == 0:
                    timed = replace(f, timings={"pin_check_ms": 125, "sessions": []},
                                    egress={"samples": 7, "per_pid_samples": {"1": 3},
                                            "sample_ms": 125} if arm == "system" else {})
                    runs.append(timed)
                    expected.append(dict(arm=timed.arm, life=timed.life, branch=timed.branch,
                        attempt=timed.attempt, pin_check_ms=125,
                        egress_pid_samples=7 if arm == "system" else None,
                        egress_sample_ms=125 if arm == "system" else None, sessions=[]))
                else:
                    runs.append(replace(f, timings=None))
            units.append(replace(unit, runs=tuple(runs)))
        arms[arm] = replace(source, units=tuple(units))
    run = replace(synth, arms=arms)
    receipt = compare._receipt(run, "system", "COMPLETE", 0, 10)
    assert receipt["timings"] == sorted(expected, key=lambda row: (
        row["arm"], row["life"], row["branch"], row["attempt"]))
    assert {row["arm"] for row in receipt["timings"]} == {"system", "no_memory"}


def test_execute_pools_lives_and_corpus(synth, installed, tmp_path, monkeypatch, cases):
    arms = {}
    for n, (arm, value) in enumerate(synth.arms.items(), 1):
        units = [replace(u, runs=tuple(replace(f, tokens_by_role={"probe_main": (n, 2 * n)},
            store_growth_bytes=n * 10, process_ids=(100 + n,), egress={"failed_samples": {"ValueError": n}},
            timings={"pin_check_ms": 0, "sessions": []})
            for f in u.runs)) for u in value.units]
        arms[arm] = replace(value, units=tuple(units))
    run = replace(synth, arms=arms)
    set_run(monkeypatch, run)
    attempts, hosts = {}, {arm: [] for arm in compare.GATED}

    class Host(ReferenceStore):
        def __init__(self, entry, **kw):
            super().__init__()
            self.paths = {"root": kw["root"]}
            self.server = SimpleNamespace(port=32109)
            self.director = SimpleNamespace(run_values={})
            self.egress = SimpleNamespace(summary=lambda: {"non_loopback": [],
                "failed_samples": {"ValueError": self.factor}})
            self.write_clipped, self.write_max_length = 0, None
            self.factor = 1 if current[0] == "system" else 2
            self.pids = [900 * self.factor + len(hosts[current[0]])]
            self.gate = [dict(exit=10 if current[0] == "system" else 0)]
            self.surface = kw["root"] / "surface"
            self.surface.mkdir()
            (self.surface / "installed").write_bytes(b"initial")
            blobs = BlobStore(kw["root"] / "ledger/blobs", Guard([]))
            self.rows = [dict(type="request", role="aux", seq=1, t_ms=7,
                req=blobs.put({}), resp=blobs.put({"usage": {
                    "input_tokens": 3 * self.factor, "output_tokens": 5 * self.factor}}))]
            hosts[current[0]].append(self)

        def surfaces(self):
            return [(self.surface, [])]

        def fields(self):
            return dict(actor="not_delivered", text="full", time="session_clock")

        def records(self):
            return self.rows

        def close(self):
            (self.surface / "growth").write_bytes(b"12345678901" * self.factor)

    current = []

    def drive(case, factory, **kw):
        current[:] = [factory.arm]
        key = factory.arm, case.case_id
        attempts[key] = attempts.get(key, 0) + 1
        for _ in range(2):
            factory().close()
        return (CaseResult(case.case_id, "INFRA_FAILURE", "infra", None) if attempts[key] == 1 else
                fake_case(case, factory, **kw))

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    monkeypatch.setattr(compare, "run_case", drive)
    monkeypatch.setattr(compare, "busy", lambda marker: False)
    out = tmp_path / "out"
    assert invoke(installed, out) == 0
    valid(out)
    for arm in compare.GATED:
        receipt = read(out, arm, "receipt.json")
        pooled = compare._runs(run, ("system", "no_memory") if arm == "system" else ("wiped",))
        assert len(receipt["timings"]) == len(pooled)
        count = 4 * len(cases)
        factor = 1 if arm == "system" else 2
        assert len(hosts[arm]) == count
        assert receipt["egress_failed_samples"] == {
            "ValueError": sum(f.egress["failed_samples"]["ValueError"] for f in pooled) + count * factor}
        assert loop_time(receipt)[1] is (arm == "system")
        assert receipt["store_growth_bytes"] == sum(f.store_growth_bytes for f in pooled) + count * 11 * factor
        assert receipt["process_ids"] == sorted({p for f in pooled for p in f.process_ids} |
                                                {p for h in hosts[arm] for p in h.pids})
        assert receipt["tokens_by_role"] == [dict(role="aux", input=count * 3 * factor, output=count * 5 * factor),
            dict(role="probe_main", input=sum(f.tokens_by_role["probe_main"][0] for f in pooled),
                 output=sum(f.tokens_by_role["probe_main"][1] for f in pooled))]
        assert not any(h.paths["root"].exists() for h in hosts[arm])


def catalogue():
    return compare.load_catalogue(compare.REPO / compare.CATALOGUE[0],
        c7_path=compare.REPO / compare.CATALOGUE[1], tier_path=compare.REPO / compare.CATALOGUE[2])


def test_wiped_reference(policy, cases, monkeypatch, tmp_path):
    calls = []

    class Host(ReferenceStore):
        def __init__(self, *args, **kwargs):
            super().__init__()

        def reset(self):
            calls.append("reset")
            super().reset()

        def restore(self, data):
            pytest.fail("wiped restore reached underlying store")

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    c = next(c for c in cases if c.case_id == SUBSET[0])
    raw = compare._WipedHost.__getattr__
    restores = []

    def attr(self, name):
        value = raw(self, name)
        if name == "restore":
            def restore(data):
                before = len(calls)
                value(data)
                assert calls[before:] == ["reset"]
                restores.append(data)
            return restore
        return value

    monkeypatch.setattr(compare._WipedHost, "__getattr__", attr)
    result = compare.corpus(policy.ctx, "wiped", (c,), catalogue=catalogue(), work=tmp_path / "work")
    assert result[0].status == "FAIL" and restores
    assert not hasattr(compare._Host(Host(), []), "begin_session")
    assert not hasattr(compare._Host(Host(), []), "probe")


def test_corpus_held_refusal(synth, installed, monkeypatch, tmp_path, capsys):
    calls = []

    class Host(ReferenceStore):
        def __init__(self, *args, **kwargs):
            super().__init__()

        def reset(self):
            # ReferenceStore construction calls reset too; refuse during drive only.
            if hasattr(self, "events"):
                calls.append("refused")
                raise GateRefused("gate")
            super().reset()

    raw = compare.run_case
    from bicentennial.corpus.run import run_case

    def observe(*args, **kwargs):
        result = run_case(*args, **kwargs)
        calls.append("returned")
        return result

    assert raw is fake_case
    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    monkeypatch.setattr(compare, "run_case", observe)
    out = tmp_path / "out"
    assert invoke(installed, out) == 3
    assert calls == ["refused", "returned"]
    assert "gate_refused" in capsys.readouterr().err
    no_results(out)


def test_corpus_stub(policy, cases, tmp_path, monkeypatch):
    write_tree = runpy.run_path(str(compare.REPO / "tests/harness/hermes_stub.py"))["write_tree"]
    stub = write_tree(tmp_path / "stub", log=tmp_path / "calls.jsonl", mode="none")
    raw, hosts, calls = compare.HermesMemoryHost, [], []

    class Host(raw):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            hosts.append(self)

        def begin_session(self, index):
            result = super().begin_session(index)
            calls.append((id(self), "begin"))
            return result

        def reset(self):
            calls.append((id(self), "reset"))
            return super().reset()

        def close(self):
            calls.append((id(self), "close"))
            return super().close()

    monkeypatch.setattr(compare, "HermesMemoryHost", Host)
    for arm in compare.GATED:
        for c in cases:
            before = len(calls)
            start = time.monotonic_ns()
            result = compare.corpus(policy.ctx, arm, (c,), catalogue=catalogue(),
                work=tmp_path / arm / c.case_id,
                host=dict(checkout=stub, worker_argv=[sys.executable, str(plugin_host.WORKER)]))
            ms = (time.monotonic_ns() - start) // 1_000_000
            print(f"corpus_stub arm={arm} case={c.case_id} status={result[0].status} "
                  f"reason={result[0].reason} wall_ms={ms}", flush=True)
            assert len(result) == 1
            if arm == "wiped":
                log = calls[before:]
                assert all(log[n + 1] == (host, "reset") for n, (host, action) in enumerate(log)
                           if action == "begin")
    assert hosts and all(calls.count((id(h), "close")) == 1 for h in hosts)


def test_cli(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: calls.append(argv))
    monkeypatch.setattr(cli, "run_t1", lambda **kw: calls.append(kw) or 2)
    monkeypatch.setattr(cli, "run_t0", lambda **kw: calls.append(kw) or 0)
    args = ["t1", "--system", "s", "--packs", "p", "--pack-hash", "h", "--out", "o"]
    assert cli.main(args) == 2
    assert calls == [["-m", "bicentennial.cli", *args], dict(system="s", packs_dir="p",
        pack_hash="h", out="o", baseline=None, hermes=None, plugin_source=None, model_cache=None,
        cache=None, sandbox_slot=0)]
    assert cli.main(["t0", "--system", "s", "--pack", "all", "--packs", "p",
                     "--pack-hash", "h", "--out", "o"]) == 0


@pytest.mark.parametrize("args,seed,code", [(["t1", "--bogus"], "0", "usage"),
    (["t1"], "0", "usage"), (["t1", "--system", "s", "--packs", "p", "--pack-hash", "h",
                             "--out", "o"], "random", "hashseed")])
def test_cli_process(args, seed, code):
    result = subprocess.run([sys.executable, "-m", "bicentennial.cli", *args],
        env=dict(os.environ, PYTHONHASHSEED=seed), capture_output=True, text=True)
    assert result.returncode == 3 and code in result.stderr


def test_purity_and_masking():
    tree = ast.parse(Path(compare.__file__).read_text())
    forbidden = ("socket", "ssl", "http", "urllib", "requests", "random", "bicentennial.director.upstream")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            assert not any(n == f or n.startswith(f + ".") for n in names for f in forbidden)
        if isinstance(node, ast.Name):
            assert "l" + "cm" not in node.id.lower()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "l" + "cm" not in node.value.lower()
        if isinstance(node, ast.Call) and ast.unparse(node.func) in ("os.environ.get", "os.getenv"):
            assert node.args[0].value == "PYTHONHASHSEED"
    # Seeded K10 draws cover digest substrings equal to a director port.
    for n in range(30):
        port = str(choice("compare-mask", ("mask",), n, "port", tuple(range(10000, 10100))))
        digest = (port + "a" * 64)[:64]
        values = dict(sandbox_root=f"/sandbox/{n}", director_port=port)
        row = dict(req=digest, resp=digest, req_masked_sha256=digest, resp_masked_sha256=digest,
                   note=f"{values['sandbox_root']}:{port}")
        masked = compare._masked([row], values)[0]
        assert masked["req_masked_sha256"] == masked["resp_masked_sha256"] == digest
        assert port not in masked["note"] and values["sandbox_root"] not in masked["note"]
    assert compare._isolated([{"upstream": [{"error": "refused"}]}], {})
    assert not compare._isolated([{"upstream": [{"served_by": "scripted", "diagnostics": ["bad"]}]}], {})
    assert not compare._isolated([], {"non_loopback": ["remote"]})


@pytest.mark.parametrize("changed", [False, True])
def test_engine_and_cache_disclosures_and_change_refusal(synth, installed, monkeypatch, tmp_path, changed):
    from bicentennial.systems import hermes_plugin as hp

    name = synth.ctx.entry["name"]
    monkeypatch.setitem(hp.ENGINES, name, "fixture_engine")
    cache = tmp_path / "model-cache"
    cache.mkdir()
    model = cache / "weights"
    model.write_bytes(b"before")
    digest = hp.cache_digest(cache, t1.T1Refused)
    ctx = replace(synth.ctx, model_cache=cache, model_cache_sha256=digest)
    run = replace(synth, ctx=ctx)
    monkeypatch.setattr(t1, "prepare", lambda **kw: ctx)
    set_run(monkeypatch, run)
    if changed:
        real = compare.corpus

        def mutate(*args, **kw):
            result = real(*args, **kw)
            model.write_bytes(b"after")
            return result

        monkeypatch.setattr(compare, "corpus", mutate)
    out = tmp_path / "out"
    assert invoke(installed, out, model_cache=cache) == (3 if changed else 0)
    if changed:
        assert json.loads((out / "refusal.json").read_bytes())["code"] == "model_cache_changed"
        no_results(out)
    else:
        for arm in compare.GATED:
            props = properties(out, arm)
            assert props["t1.model_cache"] == "sha256:" + digest
            assert props["t1.engine"] == "context engine selected by context.engine; not loaded in corpus hosts"
            assert props["t1.engine_window"] == ("context_length 65536; the context engine decides when to compress; "
                "compression.threshold_tokens applies to the built-in compressor only")
            assert props["t1.corpus_engine"] == "corpus runs Hermes built-in memory, the system's memory layer as shipped"
            assert all(props[k] == v for k, v in compare.PLUGIN_DISCLOSURES)
