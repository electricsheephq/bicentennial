"""X02a wiring acceptance on G17's real T1 lives; no model or live Hermes."""

import ast
import json
import os
import subprocess
import sys
import time
from contextlib import ExitStack, closing
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.audit.readback import FAILING
from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS
from bicentennial.director.compiler.check import Voids
from bicentennial.director.compiler.hermes import compile_script, hermes_call
from bicentennial.director.wire import chat
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HarnessFailed, PinMismatch
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items.reader_keys import life_keys
from bicentennial.items.templates import g1, g2
from bicentennial.ledger import BlobStore, Guard, apply_masks
from bicentennial.probe.scripted_reader import failing_stage
from bicentennial.runner import life as runner
from bicentennial.runner.life import CAUSES, STEP_S, LifeRun, PluginWake, run_life
from bicentennial.runner.lock import LockMismatch, SessionGate, build_lock
from bicentennial.sandbox.envserver.state import trace
from bicentennial.sandbox.envserver.tools_g2 import ACTION_TOOLS
from bicentennial.sandbox.surfaces import surface_hash
from bicentennial.score.invariants import run_invariants
from bicentennial.systems.hermes_plugin import MARKER, PluginCell
from bicentennial.systems.registry import REGISTRY, SystemRefused, load
from bicentennial.world.db import open_world
from bicentennial.world.targeted import crosses_cold_restart, load_tier, t1_lives

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name("fake_life_worker.py")
ENTRY = load(REGISTRY / "hermes-native.toml")


@pytest.fixture(scope="module")
def lives(tmp_path_factory):
    root = tmp_path_factory.mktemp("x02-lives")
    start = time.monotonic()
    generated = t1_lives(load_tier(ROOT / "tiers/life_specs/t1.toml"),
                         {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}, root=root)
    print(f"fixture_build_ms={int((time.monotonic() - start) * 1000)}", flush=True)
    result = {}
    for t in generated:
        with ExitStack() as stack:
            worlds = {b: (stack.enter_context(closing(open_world(t.out_dir / f"world.{b}.db"))), cut)
                      for b, cut in zip(("B0", "B1"), t.twin.cuts, strict=True)}
            keys = {r["item_id"]: r for r in life_keys(t.twin.compiled, t.schedule, worlds)}
            for branch in ("B0", "B1"):
                items = json.loads((t.out_dir / f"items.{branch}.json").read_bytes())
                ids = {i["item_id"] for i in items}
                records = [r for r in t.twin.compiled.records if r["item_id"] in ids]
                compiled = compile_script(t.out_dir, branch, t.schedule, worlds[branch][0], items=items, step_s=STEP_S)
                timeline = root / f"timeline-{t.life}-{branch}.json"
                timeline.write_text(json.dumps({turn["user"]: [s["index"], turn["n"], s["kind"]]
                    for s in compiled.script["sessions"] for turn in s["turns"]}))
                result[t.life, branch] = dict(t=t, branch=branch, items=items, records=records,
                    keys={iid: keys[iid] for iid in sorted(ids)}, compiled=compiled, timeline=timeline)
    yield result
    for t in generated:
        t.twin.b1.close()


@pytest.fixture(autouse=True)
def harness(monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    made, calls, closed = [], [], []
    init, session, close = adapter.HermesAdapter.__init__, adapter.HermesAdapter.run_session, adapter.HermesAdapter.close

    def construct(self, *args, **kwargs):
        init(self, *args, **kwargs)
        made.append(self)

    def run(self, index, **kwargs):
        calls.append((self, index))
        return session(self, index, **kwargs)

    def finish(self):
        closed.append(self)
        return close(self)

    monkeypatch.setattr(adapter.HermesAdapter, "__init__", construct)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run)
    monkeypatch.setattr(adapter.HermesAdapter, "close", finish)
    yield SimpleNamespace(made=made, calls=calls, closed=closed)
    assert all(closed.count(a) == 1 for a in made)
    for a in made:
        for pid in a.pids:
            with pytest.raises(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)


def drive(case, tmp_path, *, arm="system", extra=(), **kwargs):
    pins = build_lock(**json.loads((ROOT / "tests/fixtures/run/contracts.json").read_bytes())["contracts"]["lock"])
    arguments = dict(arm=arm, entry=ENTRY, life_dir=case["t"].out_dir, branch=case["branch"],
        items=case["items"], records=case["records"], keys=case["keys"], scratch=tmp_path,
        run="x02-fake", attempt=0, gate=SessionGate(pins), current_lock=lambda: pins, voids=Voids(),
        harness_pin=dict(ENTRY["artifact"]),
        worker_argv=[sys.executable, str(FAKE), "--timeline", str(case["timeline"]), *extra])
    start = time.monotonic()
    try:
        result = run_life(**(arguments | kwargs))
    except BaseException as error:
        print(f"run_life {case['t'].life} {case['branch']} {arm} "
              f"wall_ms={int((time.monotonic() - start) * 1000)} raised={type(error).__name__}", flush=True)
        raise
    print(f"run_life {case['t'].life} {result.branch} {arm} wall_ms={int((time.monotonic() - start) * 1000)} "
          f"digest={result.stable_digest} stopped={result.stopped} audit={result.audit}", flush=True)
    return result


def blobs(result):
    return BlobStore(result._root / "run" / "ledger" / "blobs", Guard([]))


def isolation(case, result, *, unknown=False):
    assert result.egress["non_loopback"] == []
    assert not [r for r in result.records if r.get("role") == "unknown"] or unknown
    assert all(r.get("served_by") in (None, "scripted") for r in result.records)
    assert all(u.get("served_by") == "scripted" or u.get("error") for r in result.records for u in r.get("upstream", []))
    assert not any(u.get("diagnostics") for r in result.records for u in r.get("upstream", []))
    expected = {(c.session, c.turn, canon(hermes_call(c.call["name"], c.call["args"])))
                for c in case["compiled"].calls}
    for row in result.records:
        if row.get("served") != "script_tool_calls":
            continue
        body = json.loads(blobs(result).get(row["resp"]))
        for call in body["choices"][0]["message"]["tool_calls"]:
            f = call["function"]
            if f["name"] == "terminal":
                assert (row["cursor"]["session"], row["cursor"]["turn"],
                        canon(dict(name=f["name"], args=json.loads(f["arguments"])))) in expected


def loop_checks(case, result, harness):
    script = case["compiled"].script
    assert [index for _, index in harness.calls] == [s["index"] for s in script["sessions"]]
    order = [s["index"] for s in script["sessions"]]
    assert order[order.index(10) + 1] == 21
    for s, actual in zip(script["sessions"], result.sessions, strict=True):
        if s["kind"] == "replay":
            assert actual.finals_matched == len(s["turns"])
    kill = next(s for s in result.sessions if s.session == 11)
    assert [r["kind"] for r in kill.restarts] == ["kill"]
    for row in result.records:
        cursor = row.get("cursor")
        if row.get("role") != "replay_main" or cursor["session"] > 20:
            continue
        assert row["model_in"] == ("bicentennial-main" if cursor["session"] < 15 else "bicentennial-swap")
        plan = case["t"].schedule.sessions[cursor["session"] - 1]
        assert row["sim_now"] == plan.turn_t[cursor["turn"] - 1]


@pytest.mark.parametrize("life,branch", [(life, branch) for life in ("t1-g1", "t1-g2") for branch in ("B0", "B1")])
def test_system(lives, tmp_path, harness, life, branch):
    case = lives[life, branch]
    result = drive(case, tmp_path)
    assert result.stopped is None
    assert result.audit == {"status": "OK", "failures": []}
    assert len(result.results) == len(case["items"])
    assert result.transforms == ()
    assert all(r.in_context for iid, r in result.results.items()
               if r.kind == "qa" and case["keys"][iid]["required"])
    for p in case["compiled"].probes:
        if result.results[p.item_ids[0]].kind == "qa":
            assert result.results[p.item_ids[0]].carry_over is False
    for item in case["items"]:
        if item["stage"] == "act":
            assert item["item_id"] in result.act
            r = result.results[item["item_id"]]
            if life == "t1-g2" and r.plan.steps:
                records = result.act[item["item_id"]]["records"]
                assert trace(records, ACTION_TOOLS)[2] is not None
                assert all(any(a.get("type") == "action" and a["ok"] and a["tool"] == s["tool"]["name"]
                               and a["args"] == s["tool"]["args"] for a in records) for s in r.plan.steps)
    loop_checks(case, result, harness)
    isolation(case, result)
    if life == "t1-g1" and branch == "B0":
        assert result.expected_call_ids
        assert run_invariants([], tier="T1", requests=result.post_restart_requests,
                              expected_call_ids=result.expected_call_ids)["INV-PAIR"].status == "PASS"
    if life == "t1-g2":
        assert result.expected_call_ids == ()
    assert result.verified_empty["taken"] == "before configuration"
    assert result.store_growth_bytes > 0
    assert result.process_ids == tuple(harness.made[0].pids) and result.process_ids
    roles = {r["role"] for r in result.records if r.get("type") == "request"}
    assert set(result.tokens_by_role) == roles
    assert all(i > 0 and o > 0 for i, o in result.tokens_by_role.values())
    with pytest.raises(FrozenInstanceError):
        result.arm = "changed"
    result.cleanup()
    assert not result._root.exists()


@pytest.mark.parametrize("life", ["t1-g1", "t1-g2"])
def test_wiped(lives, tmp_path, harness, life):
    case = lives[life, "B0"]
    result = drive(case, tmp_path, arm="wiped")
    assert result.stopped is None
    assert result.audit["status"] == "OK"
    assert "A4.gaps" in result.audit["failures"]
    assert result.audit["a4_gaps"] == "expected: the wiped arm restores the fresh install at every wake"
    records = {r["item_id"]: r for r in case["records"]}
    retained = [iid for iid, r in result.results.items() if r.kind == "qa" and r.in_context is False
                and crosses_cold_restart(case["t"].schedule, records[iid]["evidence_session"],
                                         next(i["probe_point"] for i in case["items"] if i["item_id"] == iid))
                and failing_stage(r, case["keys"][iid], failed=True, stored_roots=result.stored_roots.get(iid),
                                  retained_roots=result.retained_roots[iid]) == "retained"]
    assert retained
    assert len(result.hooks[0].records()) == len(harness.made[0].pids)
    isolation(case, result)
    if life == "t1-g1":
        assert result.expected_call_ids
        assert run_invariants([], tier="T1", requests=result.post_restart_requests,
                              expected_call_ids=result.expected_call_ids)["INV-PAIR"].status == "FAIL"
    result.cleanup()
    assert not result._root.exists()


@pytest.mark.parametrize("life", ["t1-g1", "t1-g2"])
def test_no_memory(lives, tmp_path, harness, life):
    case = lives[life, "B0"]
    result = drive(case, tmp_path, arm="no_memory")
    assert result.kill is None
    assert result.expected_call_ids == ()
    assert result.post_restart_requests == ()
    assert result.stopped is None
    assert result.audit == {"status": "OK", "failures": []}
    assert all(s["kind"] == "probe" for s in harness.made[0].script["sessions"])
    assert not any(r.in_context is True for r in result.results.values())
    for row in result.records:
        if row.get("type") == "request":
            body = json.loads(blobs(result).get(row["req"]))
            assert not {"memory", "session_search"} & {t["function"]["name"] for t in body.get("tools", [])}
    isolation(case, result)

    result.cleanup()
    assert not result._root.exists()


@pytest.fixture
def completed_sessions(monkeypatch):
    """Unit boundary: consume scripted sessions without worker or responder effects."""
    def run_session(self, index, **kwargs):
        session = next(s for s in self.script["sessions"] if s["index"] == index)
        turns = len(session["turns"])
        return adapter.SessionResult(index, session["kind"], "unit-session", "test-double", turns, turns,
            (), False, 0, surface_hash(self.paths["hermes_home"], self.volatile), (), {})

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)


@pytest.mark.parametrize("arm", ["system", "wiped"])
@pytest.mark.parametrize("other_failure", [False, True])
def test_audit_effect_gaps_by_arm(lives, tmp_path, monkeypatch, completed_sessions, arm, other_failure):
    report = {section: dict.fromkeys(keys, []) for section, keys in FAILING.items()}
    report["A4"]["gaps"] = ["missing write"]
    report["A4"]["calls"] = [dict(call="missing write", applied=True,
        operations=[dict(store_satisfied=False, next_session_satisfied=False)])]
    if other_failure:
        report["A1"]["mismatches"] = ["different request"]
    monkeypatch.setattr(runner, "load_ledger", lambda *args: ([], {}, "unit-ledger"))
    monkeypatch.setattr(runner, "audit", lambda *args, **kwargs: report)
    result = drive(lives["t1-g1", "B0"], tmp_path, arm=arm)
    try:
        assert result.stopped is None
        assert result.audit["status"] == ("OK" if arm == "wiped" and not other_failure else "INFRA_FAILURE")
        assert result.audit["failures"] == (["A1.mismatches"] if other_failure else []) + ["A4.gaps"]
        if arm == "wiped":
            assert result.audit["a4_gaps"] == "expected: the wiped arm restores the fresh install at every wake"
        else:
            assert "a4_gaps" not in result.audit
    finally:
        result.cleanup()


@pytest.mark.parametrize("arm,applied,status,unclassified", [
    ("wiped", (True, None), "INFRA_FAILURE", 1),
    ("wiped", (True,), "OK", None),
    ("wiped", None, "INFRA_FAILURE", "unknown"),
    ("system", (True, None), "INFRA_FAILURE", None),
])
def test_audit_unclassified_effect_gaps(lives, tmp_path, monkeypatch, completed_sessions,
                                       arm, applied, status, unclassified):
    report = {section: dict.fromkeys(keys, []) for section, keys in FAILING.items()}
    report["A4"]["gaps"] = ["missing write"]
    if applied is not None:
        report["A4"]["calls"] = [dict(call=f"write-{n}", applied=value,
            operations=[dict(store_satisfied=False, next_session_satisfied=False)])
            for n, value in enumerate(applied)]
        report["A4"]["gaps"] = [c["call"] for c in report["A4"]["calls"]]
    monkeypatch.setattr(runner, "load_ledger", lambda *args: ([], {}, "unit-ledger"))
    monkeypatch.setattr(runner, "audit", lambda *args, **kwargs: report)
    result = drive(lives["t1-g1", "B0"], tmp_path, arm=arm)
    try:
        assert result.stopped is None
        assert result.audit["status"] == status
        assert result.audit["failures"] == ["A4.gaps"]
        if unclassified is not None:
            assert result.audit["a4_unclassified"] == unclassified
            assert "a4_gaps" not in result.audit
        else:
            assert "a4_unclassified" not in result.audit
            assert ("a4_gaps" in result.audit) == (arm == "wiped")
    finally:
        result.cleanup()


@pytest.mark.parametrize("holds", [False, True])
def test_rerun_shares_voids_unit(lives, tmp_path, monkeypatch, completed_sessions, holds):
    case = lives["t1-g1", "B0"]
    monkeypatch.setattr(runner, "precondition_holds", lambda *args, **kwargs: holds)
    voids = Voids()
    first = drive(case, tmp_path / "first", voids=voids)
    try:
        assert first.stopped is None
        records, diagnostics = dict(voids.records), list(voids.diagnostics)
        assert records == {(i["item_id"], "system"): holds for i in case["items"]}
        second = drive(case, tmp_path / "second", attempt=1, voids=voids)
        try:
            assert second.attempt == 1 and second._root != first._root
            assert second.stopped is None
            assert len(second.sessions) == len(case["compiled"].script["sessions"])
            assert second.classes == first.classes
            assert voids.records == records and voids.diagnostics == diagnostics
            assert sorted(d["item_id"] for d in voids.diagnostics) == sorted(i["item_id"] for i in case["items"])
        finally:
            second.cleanup()
    finally:
        first.cleanup()


def test_no_memory_kill_unit(lives, tmp_path, completed_sessions):
    result = drive(lives["t1-g1", "B0"], tmp_path, arm="no_memory")
    try:
        assert result.stopped is None
        assert result.kill is None
        assert result.expected_call_ids == ()
        assert result.post_restart_requests == ()
    finally:
        result.cleanup()


@pytest.mark.parametrize("void_checkpoint", [False, True])
def test_rerun_shares_voids(lives, tmp_path, monkeypatch, void_checkpoint):
    case = lives["t1-g2", "B0"]
    if void_checkpoint:
        real = runner.expected_probe_env
        monkeypatch.setattr(runner, "expected_probe_env",
            lambda db, genre, p, k: "f" * 64 if k == 10 else real(db, genre, p, k))
    voids = Voids()
    first = drive(case, tmp_path / "first", voids=voids)
    try:
        assert first.stopped is None
        records, diagnostics = dict(voids.records), list(voids.diagnostics)
        assert len(records) == len(case["items"])
        assert set(records.values()) == ({False, True} if void_checkpoint else {True})
        second = drive(case, tmp_path / "second", attempt=1, voids=voids)
        try:
            assert second.attempt == 1 and second._root != first._root
            assert second.stopped is None
            assert len(second.results) == len(case["items"])
            assert second.classes == first.classes
            assert voids.records == records
            assert voids.diagnostics == diagnostics
            assert sorted(d["item_id"] for d in voids.diagnostics) == sorted(i["item_id"] for i in case["items"])
        finally:
            second.cleanup()
    finally:
        first.cleanup()


@pytest.mark.parametrize("holds", [False, True])
def test_rerun_void_mismatch(lives, tmp_path, monkeypatch, harness, holds):
    case = lives["t1-g2", "B0"]
    probe = case["compiled"].probes[0]
    voids = Voids()
    voids.record(probe.item_ids[0], "no_memory", not holds)
    records, diagnostics = dict(voids.records), list(voids.diagnostics)
    monkeypatch.setattr(runner, "precondition_holds", lambda *args, **kwargs: holds)
    result = drive(case, tmp_path, arm="no_memory", attempt=1, voids=voids)
    try:
        assert result.stopped == ("INFRA_FAILURE", "void_mismatch", probe.index)
        assert set(result.classes.values()) == {("INFRA_FAILURE", "void_mismatch")}
        assert not harness.calls
        assert voids.records == records and voids.diagnostics == diagnostics
    finally:
        result.cleanup()


@pytest.mark.parametrize("extra,label,session", [
    (("--fail-turn", "5"), "turn_failed", 5),
    (("--fail-turn", "21"), "turn_failed", 21),
    (("--drop-recall",), "error_recalltoolmissing", 21),
    (("--no-tools-in-probe",), "unknown_400", 21),
])
def test_failure_codes(lives, tmp_path, harness, extra, label, session):
    case = lives["t1-g1", "B0"]
    result = drive(case, tmp_path, extra=extra)
    cls = "SYSTEM_FAILURE" if label == "turn_failed" else "INFRA_FAILURE"
    assert result.stopped == (cls, label, session)
    assert harness.calls[-1][1] == session
    assert not any(iid not in result.classes for iid in (i["item_id"] for i in case["items"]))
    assert set(result.classes.values()) == {(cls, label)}
    isolation(case, result, unknown=label == "unknown_400")
    result.cleanup()
    assert not result._root.exists()


def test_void_checkpoint(lives, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    real = runner.expected_probe_env
    monkeypatch.setattr(runner, "expected_probe_env", lambda db, genre, p, k: "f" * 64 if k == 10 else real(db, genre, p, k))
    voids = Voids()
    result = drive(case, tmp_path, voids=voids)
    assert result.stopped is None
    expected = {i["item_id"] for i in case["items"] if i["probe_point"] == 10}
    assert voids.voided() == expected
    assert result.classes == {iid: ("INFRA_FAILURE", "void") for iid in sorted(expected)}
    assert len(result.results) == len(case["items"])
    result.cleanup()
    assert not result._root.exists()


def test_lock_refusal_after_three(lives, tmp_path, harness):
    case = lives["t1-g1", "B0"]
    pins = build_lock(**json.loads((ROOT / "tests/fixtures/run/contracts.json").read_bytes())["contracts"]["lock"])

    def current():
        if len(harness.calls) >= 3:
            return pins | {"benchmark_commit": "f" * 40}
        return pins

    # Detect the launch denial separately, so it cannot masquerade as a lock test.
    probe = drive(case, tmp_path / "preflight")
    probe.cleanup()
    harness.calls.clear()
    with pytest.raises(LockMismatch):
        drive(case, tmp_path / "refused", current_lock=current, gate=SessionGate(pins))
    assert [index for _, index in harness.calls] == [1, 2, 3]
    assert harness.closed == harness.made


@pytest.mark.parametrize("kind", [SystemRefused, PinMismatch, LockMismatch, GateRefused])
def test_construction_refusals_escape(lives, tmp_path, monkeypatch, kind):
    error = kind(["fixture_refusal"]) if kind in (SystemRefused, LockMismatch) else kind("fixture_refusal")

    def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(runner, "HermesAdapter", refuse)
    with pytest.raises(kind) as caught:
        drive(lives["t1-g1", "B0"], tmp_path)
    assert caught.value is error


def test_determinism(lives, tmp_path):
    case = lives["t1-g1", "B0"]
    a, b = drive(case, tmp_path / "one"), drive(case, tmp_path / "two")
    if a.stable_digest != b.stable_digest:
        schema = json.loads((SCHEMAS / "ledger-record.schema.json").read_bytes())["properties"]
        stable = {k for k, prop in schema.items() if prop["x-stability"] == "stable"}
        digests = {k for k in stable if schema[k].get("pattern") == "^[0-9a-f]{64}$"}

        def projection(result):
            # Use the ledger's named masks and digest exception, solely for diagnostics.
            return sorted((dict(apply_masks({k: v for k, v in row.items() if k in stable - digests},
                                            result.run_values),
                                **{k: row[k] for k in sorted(digests) if k in row})
                           for row in result.records if row.get("type") == "request"), key=canon)

        left, right = projection(a), projection(b)
        first = next(((i, left[i] if i < len(left) else None, right[i] if i < len(right) else None)
                      for i in range(max(len(left), len(right)))
                      if i >= min(len(left), len(right)) or left[i] != right[i]), None)
        pytest.fail(f"stable digest mismatch {a.stable_digest} != {b.stable_digest}; first differing record={first}")

    def results(r):
        return [(iid, v.selected_option, v.in_context, list(v.competing_present), v.carry_over, v.envelope)
                for iid, v in sorted(r.results.items())]

    assert canon(results(a)) == canon(results(b))
    assert canon(a.envelopes) == canon(b.envelopes)
    print(f"determinism digests={a.stable_digest},{b.stable_digest}", flush=True)
    a.cleanup()
    b.cleanup()
    assert not a._root.exists() and not b._root.exists()


def test_embeddings_are_skipped(lives, tmp_path):
    case = lives["t1-g1", "B0"]
    result = drive(case, tmp_path, extra=("--embeddings-after-restart",))
    assert result.stopped is None
    assert any(r.get("path", "").endswith("/embeddings") for r in result.records)
    assert all(wire in ("chat", "responses") and "input" not in body for wire, body in result.post_restart_requests)
    assert run_invariants([], tier="T1", requests=result.post_restart_requests,
                          expected_call_ids=result.expected_call_ids)["INV-PAIR"].status == "PASS"
    isolation(case, result)
    result.cleanup()
    assert not result._root.exists()


def plugin_source(tmp_path):
    source = tmp_path / "provider"
    source.mkdir()
    (source / "provider.py").write_text("# archive-pinned stand-in\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=test", "-c", "user.email=test@example.invalid",
                                               "commit", "-qm", "fake pin"]):
        subprocess.run(["git", "-C", str(source), *args], check=True)
    archive = subprocess.run(["git", "-C", str(source), "archive", "--format=tar", "HEAD"], capture_output=True, check=True)
    entry = load(REGISTRY / "holographic.toml")
    entry["artifact"]["sha256"] = sha256(archive.stdout).hexdigest()
    return source, entry


def test_life_surface_before_install(lives, tmp_path, monkeypatch, completed_sessions):
    source, entry = plugin_source(tmp_path)
    entry["surfaces"].append(dict(root="SANDBOX_HOME", relative=".state", volatile_paths=[]))
    construct, install = adapter.HermesAdapter.__init__, PluginCell.install
    installed = []

    def populate(self, *args, **kwargs):
        construct(self, *args, **kwargs)
        directory = self.paths["hermes_home"] if content == "hermes" else self.paths["home"] / ".state"
        directory.mkdir(exist_ok=True)
        (directory / (MARKER if content == "marker" else "stray")).write_bytes(b"")

    def installing(self, *args, **kwargs):
        installed.append(content)
        return install(self, *args, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "__init__", populate)
    monkeypatch.setattr(PluginCell, "install", installing)
    for content in ("stray", "marker", "hermes"):
        kwargs = dict(entry=entry, plugin_source=source)
        if content == "stray":
            with pytest.raises(SystemRefused) as error:
                drive(lives["t1-g1", "B0"], tmp_path / content, **kwargs)
            assert error.value.reasons == ("surface_not_empty",)
            assert installed == []
        else:
            result = drive(lives["t1-g1", "B0"], tmp_path / content, **kwargs)
            assert result.stopped is None
            assert installed[-1] == content
            result.cleanup()


@pytest.mark.parametrize("settled", [True, False])
def test_wiped_plugin(lives, tmp_path, monkeypatch, harness, settled):
    case = lives["t1-g1", "B0"]
    source, entry = plugin_source(tmp_path)
    wiped, real = [], PluginCell.wipe

    def wipe(cell):
        wiped.append(cell)
        return real(cell)

    monkeypatch.setattr(PluginCell, "wipe", wipe)
    if not settled:
        monkeypatch.setattr(PluginCell, "settle", lambda self: SimpleNamespace(settled=False))
    monkeypatch.setattr(runner, "WipeOnWake", lambda *a, **kw: pytest.fail("native wipe constructed for plug-in"))
    result = drive(case, tmp_path / "run", arm="wiped", entry=entry, plugin_source=source,
                   visible={"notes.txt": b"canary-stripped visible input"})
    assert result.stopped is None
    assert isinstance(result.hooks[0], PluginWake)
    assert len(wiped) == len(harness.made[0].pids) - 1
    assert len(result.hooks[0].records()) == len(harness.made[0].pids)
    assert [index for _, index in harness.calls] == [s["index"] for s in case["compiled"].script["sessions"]]
    if not settled:
        assert result.classes == {i["item_id"]: ("SYSTEM_FAILURE", "unsettled") for i in case["items"]}
    assert result.audit["status"] == "OK"
    assert result.audit["failures"] == ["A4.no_effects_hook"]
    assert result.audit["a4"] == "not audited for plug-in providers at v0.1"
    isolation(case, result)
    result.cleanup()
    assert not result._root.exists()


def test_firewall_and_no_mutable_module_state():
    source = Path(runner.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {"socket", "ssl", "http", "urllib", "requests", "random", "time", "os"}
    allowed_stdlib = {"json", "shutil", "contextlib", "dataclasses", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden
                assert name.split(".")[0] in allowed_stdlib or name.startswith("bicentennial.")
                assert "director.upstream" not in name
        if isinstance(node, ast.Name):
            assert "l" + "cm" not in node.id.lower()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "l" + "cm" not in node.value.lower()
    assert "os.environ" not in source and "os.getenv" not in source
    for node in tree.body:
        if isinstance(node, ast.Assign):
            assert not isinstance(node.value, (ast.List, ast.Set, ast.Dict))


@pytest.mark.parametrize("label,cls", [*CAUSES, ("group_survivors:123", "INFRA_FAILURE"),
                                       ("new_label", "INFRA_FAILURE")])
def test_failure_cause_table(label, cls):
    assert runner._cause(HarnessFailed(label)) == (cls, label)
    assert runner._cause(ValueError("not emitted")) == ("INFRA_FAILURE", "ValueError")


def test_adapter_failure_labels_are_named():
    tree = ast.parse(Path(adapter.__file__).read_text())
    labels = set()

    def literal_labels(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.IfExp):
            return literal_labels(node.body) | literal_labels(node.orelse)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return literal_labels(node.left)
        return set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call) and (
                isinstance(node.exc.func, ast.Name) and node.exc.func.id == "HarnessFailed"):
            labels.update(literal_labels(node.exc.args[0]))
    worker = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Worker")
    call = next(n for n in worker.body if isinstance(n, ast.FunctionDef) and n.name == "call")
    phases = next(n for n in ast.walk(call) if isinstance(n, ast.Dict))
    assert {k.value for k in phases.keys} == {"startup", "open", "turn", "end"}
    # The formatted timeout label is expanded from the worker's actual phase table.
    labels.update(f"{k.value}_timeout" for k in phases.keys)
    assert "group_survivors:" in labels
    assert labels - {"group_survivors:"} <= dict(CAUSES).keys()


@pytest.mark.parametrize("label,cls", [
    ("turn_timeout", "SYSTEM_FAILURE"), ("end_timeout", "SYSTEM_FAILURE"),
    ("startup_timeout", "INFRA_FAILURE"), ("open_timeout", "INFRA_FAILURE"),
    ("worker_start", "INFRA_FAILURE"), ("director_inflight", "INFRA_FAILURE"),
    ("admission_deadline", "INFRA_FAILURE"),
])
def test_worker_failure_mappings(label, cls):
    assert dict(CAUSES)[label] == cls
    assert runner._cause(HarnessFailed(label)) == (cls, label)


def test_earlier_and_pair_inputs_ignore_torn_tail(tmp_path):
    store = BlobStore(tmp_path / "blobs", Guard([]))
    rows = []
    for turn in (1, 1, 2):
        rows.append(dict(seq=len(rows) + 1, role="probe_main", cursor=dict(session=21, turn=turn),
                         req=store.put(dict(messages=[dict(role="user", content=f"turn {turn}")])),
                         resp=store.put(dict(choices=[]))))
    (tmp_path / "ledger.jsonl").write_bytes(b"".join(canon(r) + b"\n" for r in rows) + b'{"torn":')
    assert runner._earlier(tmp_path, 21) == tuple(store.get(r[k]) for r in rows[:2] for k in ("req", "resp"))
    assert runner._pair_inputs(tmp_path, rows, None, "G1") == ((), ())


@pytest.mark.parametrize("stream", [False, True])
def test_pair_inputs_reads_streamed_and_json_tool_calls(tmp_path, stream):
    # Hermes streams its chat requests, and the director then stores the reply as its chunks.
    store = BlobStore(tmp_path / "blobs", Guard([]))
    msg = {"role": "assistant", "content": "", "tool_calls": [
        {"id": i, "type": "function", "function": {"name": "terminal", "arguments": "{}"}} for i in ("b", "a")]}
    resp = chat.build_response({"model": "m", "messages": []}, msg, response_id="r")
    cursor, after = dict(session=3, turn=2), {"messages": [{"role": "tool", "tool_call_id": "a"}]}
    rows = [dict(seq=1, type="request", path="/main/v1/chat/completions", cursor=cursor,
                 served="script_tool_calls", req=store.put({"messages": []}),
                 resp=store.put({"sse": chat.sse_chunks(resp)} if stream else resp)),
            dict(seq=2, type="request", path="/main/v1/chat/completions", cursor=None,
                 req=store.put(after), resp=store.put({}))]
    assert runner._pair_inputs(tmp_path, rows, (3, 2), "G1") == (("a", "b"), (("chat", after),))


@pytest.mark.parametrize("response", [
    {"usage": {"prompt_tokens": 3, "completion_tokens": 5}},
    {"sse": [{"usage": {"input_tokens": 3, "output_tokens": 5}}, {}]},
    {"sse": [{"response": {"usage": {"input_tokens": 3, "output_tokens": 5}}}]},
])
def test_tokens_read_response_blobs(tmp_path, response):
    store = BlobStore(tmp_path / "blobs", Guard([]))
    rows = [dict(type="request", role="aux", resp=store.put(response))] * 2
    rows += [dict(type="request", role="embeddings", resp=store.put({})), dict(type="diagnostic")]
    assert runner._tokens(tmp_path, rows) == {"aux": (6, 10), "embeddings": (0, 0)}


def test_surface_bytes_counts_regular_files(tmp_path):
    (tmp_path / "installed").write_bytes(b"initial")
    (tmp_path / "alias").symlink_to(tmp_path / "installed")
    surfaces = [(dict(volatile_paths=["installed"]), tmp_path)]
    before = runner._surface_bytes(surfaces)
    (tmp_path / "grown").write_bytes(b"12345")
    assert before == 7 and runner._surface_bytes(surfaces) - before == 5


def test_probe_code_uses_attempt_for_unknown_cursor():
    rows = [dict(attempt_id="before", role="unknown", status=400),
            dict(attempt_id="now", cursor=None, role="unknown", status=400)]
    assert runner._probe_code(rows, "now") == "unknown_400"
    assert runner._probe_code([dict(attempt_id="now", upstream=[dict(error="error_plantoolmissing")])],
                              "now") == "error_plantoolmissing"


def test_cleanup_is_attempt_local_and_idempotent(tmp_path):
    root, sibling = tmp_path / "attempt", tmp_path / "sibling"
    root.mkdir()
    sibling.mkdir()
    result = LifeRun("system", "fixture", "B0", 0, _root=root)
    result.cleanup()
    result.cleanup()
    assert not root.exists() and sibling.exists()


def test_plugin_wake_records_and_reason_validation(tmp_path):
    directory = tmp_path / "surface"
    directory.mkdir()
    (directory / MARKER).touch()
    surface = dict(root="HERMES_HOME", relative=".", volatile_paths=[])
    digest = surface_hash(directory, [])
    calls = []
    hook = PluginWake()
    hook.cell = SimpleNamespace(surfaces=[(surface, directory)], snapshots=[(directory, digest)],
                                adapter=SimpleNamespace(director=SimpleNamespace(run_values={"director_port": "41001"})),
                                wipe=lambda: calls.append("wipe"))
    with pytest.raises(ValueError):
        hook("kill")
    assert hook("session_start") is False
    assert hook("kill") is True and calls == ["wipe"]
    rows = hook.records()
    assert rows[0]["surfaces"][0]["post_wipe_hash"] is None
    assert rows[1]["surfaces"][0]["post_wipe_hash"] == digest
    rows[0]["reason"] = "mutated"
    assert hook.records()[0]["reason"] == "session_start"
    with pytest.raises(ValueError):
        hook("not-a-wake")


@pytest.mark.parametrize("plugin", [False, True])
def test_raised_probe_restores_surfaces_and_keeps_unsettled(lives, tmp_path, monkeypatch, plugin):
    """Failure-policy unit: stop before a worker spawn and inspect the restored trees."""
    case = lives["t1-g1", "B0"]
    seen, hashes = [], {}
    script = {s["index"]: s for s in case["compiled"].script["sessions"]}

    def run_session(self, index, **kwargs):
        seen.append(index)
        home = self.paths["hermes_home"]
        if index == 10:
            (home / "prior-memory").write_bytes(b"canonical state at checkpoint")
            hashes["original"] = surface_hash(home, self.volatile)
        if index == 21:
            (home / "probe-only").write_bytes(b"must remain on retained clone")
            raise HarnessFailed("turn_failed")
        turns = script[index]["turns"]
        return adapter.SessionResult(index, "replay", "unit-session", "test-double", len(turns), len(turns),
            (), False, 0, surface_hash(home, self.volatile), (), {})

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)
    kwargs = {}
    if plugin:
        source, entry = plugin_source(tmp_path)
        kwargs = dict(entry=entry, plugin_source=source)
        monkeypatch.setattr(PluginCell, "settle", lambda self: SimpleNamespace(settled=False))
    result = drive(case, tmp_path / "run", **kwargs)
    assert seen == [*range(1, 11), 21]
    assert result.stopped == ("SYSTEM_FAILURE", "turn_failed", 21)
    home = result._root / "run" / "hermes-home"
    assert surface_hash(home, ENTRY["surfaces"][0]["volatile_paths"]) == hashes["original"]
    assert result.store_growth_bytes == len(b"canonical state at checkpoint")
    assert not (home / "probe-only").exists()
    first_probe = case["compiled"].probes[0]
    assert all((roots[0] / "probe-only").is_file() for iid, roots in result.retained_roots.items()
               if iid in first_probe.item_ids)
    assert all(roots[0] != home for roots in result.retained_roots.values())
    for item in case["items"]:
        label = "unsettled" if plugin and item["probe_point"] == 10 else "turn_failed"
        assert result.classes[item["item_id"]] == ("SYSTEM_FAILURE", label)
    assert not any(s.session > 10 for s in result.sessions)
    result.cleanup()
    assert not result._root.exists()


@pytest.mark.parametrize("arm", ["system", "wiped", "no_memory"])
def test_non_plugin_life_gets_worker_env(lives, tmp_path, monkeypatch, harness, arm):
    extra = {"MODEL_HOME": str(tmp_path / "cache")}

    def session(self, index, **kw):
        raise HarnessFailed("turn_failed")

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    result = drive(lives["t1-g1", "B0"], tmp_path / "run", arm=arm, extra_env=extra)
    made = harness.made[0]
    assert made.plugin is None and made.context_engine is None
    assert made.extra_env == (None if arm == "no_memory" else extra)
    result.cleanup()


@pytest.mark.parametrize("arm", ["system", "wiped", "no_memory"])
def test_engine_only_life_uses_plugin_wake_and_env(lives, tmp_path, monkeypatch, harness, arm):
    from bicentennial.director.scripted import WRITE_ARGS
    from bicentennial.systems import hermes_plugin as hp

    name, engine = "fixture-engine", "fixture_engine"
    source, pinned = plugin_source(tmp_path)
    entry = dict(ENTRY, name=name, artifact=pinned["artifact"])
    monkeypatch.setitem(hp.ENGINES, name, engine)
    monkeypatch.setitem(hp.TREES, name, ("HEAD",))
    monkeypatch.setitem(WRITE_ARGS, name, WRITE_ARGS["hermes-native"])
    extra = {"MODEL_HOME": str(tmp_path / "cache")}

    def session(self, index, **kw):
        if self.before_spawn is not None:
            self.before_spawn("session_start")
            self.before_spawn("kill")
        raise HarnessFailed("turn_failed")

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    result = drive(lives["t1-g1", "B0"], tmp_path / "run", arm=arm,
                   entry=entry, plugin_source=source, extra_env=extra)
    made = harness.made[0]
    assert made.context_engine == (None if arm == "no_memory" else engine)
    assert made.extra_env == (None if arm == "no_memory" else extra)
    target = made.paths["hermes_home"] / "plugins" / engine
    assert target.exists() is (arm != "no_memory")
    if arm == "wiped":
        assert isinstance(result.hooks[0], PluginWake)
        assert result.hooks[0].records()[-1]["wake"] is True
    else:
        assert not result.hooks
    result.cleanup()
