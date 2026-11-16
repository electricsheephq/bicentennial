"""Parked-original attribution through the offline unit path."""

import errno
import json
import os
import shutil
import stat
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_unreadable_state import damage_probe, helpers, unit

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.runner import life

lives = helpers.lives
harness = helpers.harness
unit_sessions = helpers.unit_sessions
completed_sessions = helpers.HELPERS["completed_sessions"]


@pytest.mark.parametrize("changed,failure,arm,attempts", [
    ("MEMORY.md", "effects", "system", 1), ("USER.md", "A4.gaps", "system", 1),
    (None, "effects", "system", 3), ("MEMORY.md", "A3.missing", "system", 3),
    ("MEMORY.md", "other_effect", "system", 3), ("MEMORY.md", "effects", "wiped", 3),
    ("other", None, "system", 1), ("MEMORY.md", None, "system", 1),
    ("MEMORY.md", "ledger", "system", 3), ("MEMORY.md", "audit", "system", 3),
    ("USER.md", "mixed", "system", 3), (None, "A4.gaps", "system", 3),
    (None, None, "system", 1),
    ("other", "A4.gaps", "system", 3), ("USER.md", "A4.gaps", "scripted", 1),
    ("USER.md", "classed", "system", 3),
])
def test_parked_memory(lives, unit_sessions, tmp_path, monkeypatch, request, changed, failure, arm, attempts):
    case = lives["t1-g1", "B0"]
    if arm == "scripted":
        request.getfixturevalue("completed_sessions")
        monkeypatch.setattr(life, "load_ledger", lambda *a: ([], {}, None))

    def damage(workspace):
        if changed:
            parked = next((workspace.parent / "hermes-home").parent.glob(".hermes-home.original-*"))
            path = parked / ("other" if changed == "other" else "memories/" + changed)
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"\xff" if failure == "effects" else b"changed")

    probe, _ = damage_probe(monkeypatch, case, damage)
    if failure == "classed":
        monkeypatch.setattr(life, "_probe_code", lambda *a, **k: "known_infra" if k.get("session") == probe.index else None)
    if failure in ("effects", "other_effect") and (not changed or failure == "other_effect"):
        read, effects = Path.read_text, life.hermes_effects

        def with_store(home, **kw):
            path = home / "memories" / ("USER.md" if changed else "MEMORY.md")
            path.parent.mkdir(exist_ok=True)
            path.touch()
            return effects(home, **kw)

        monkeypatch.setattr(life, "hermes_effects", with_store)

        def fault(path, *args, **kw):
            if path.name == ("USER.md" if failure == "other_effect" else "MEMORY.md"):
                raise UnicodeError("injected effects read")
            return read(path, *args, **kw)

        monkeypatch.setattr(Path, "read_text", fault)
    elif failure in ("ledger", "audit"):
        def fault(*args, **kw):
            raise ValueError("injected audit failure")
        monkeypatch.setattr(life, "load_ledger" if failure == "ledger" else "audit", fault)
    elif failure and failure != "effects":
        a4_failure(monkeypatch, ("user" if changed == "USER.md" else "memory",),
                   ["A4.gaps", "A3.missing"] if failure == "mixed" else [
                       "A4.gaps" if failure == "classed" else failure])
    if arm == "scripted":
        run = helpers.drive(case, tmp_path)
        assert run.audit["failures"] == ["A4.gaps"]
        assert run.parked_receipts and not run.classes
        return
    result = unit(case, tmp_path, arm=arm)
    assert result.attempts == attempts
    run = result.runs[0]
    receipts = run.parked_receipts
    diag = json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes())["attempts"][0] if changed or failure else {}
    if changed:
        assert any(r["surface"] == "HERMES_HOME/." and r["path"] == (
            "." if changed == "other" else "memories/" + changed) for r in receipts)
        assert diag["parked_receipts"] == receipts
    else:
        assert not receipts
    if failure in ("A4.gaps", "A3.missing", "mixed", "classed"):
        assert run.audit_phase["phase"] == "audit"
    if failure in ("effects", "other_effect", "ledger", "audit"):
        assert canon(run.audit) == b'{"failures":["audit_exception"],"status":"INFRA_FAILURE"}'
        assert run.audit_phase["phase"] == ("effects" if "effect" in failure else failure)
        if "effect" in failure:
            assert run.audit_phase["path"] == "memories/" + (
                "USER.md" if failure == "other_effect" else "MEMORY.md")
        else:
            assert run.audit_phase == {"phase": failure}
        assert diag["audit_phase"] == run.audit_phase
    if attempts == 1 and failure:
        assert set(run.classes.values()) == {("SYSTEM_FAILURE", "system_audit_failure")}
        assert {row.get("label") for row in result.probes} == {"system_audit_failure"}
        assert all(row["failure_class"] == "SYSTEM_FAILURE" and row["infra_reruns"] == 0
                   for row in result.scores.values())
    elif failure:
        assert all(row["infra_reruns"] == 2 for row in result.scores.values())
        if failure == "classed":
            assert all(run.classes[iid] == ("INFRA_FAILURE", "known_infra") for iid in probe.item_ids)
    else:
        assert not run.classes and not run.audit_phase
        if not changed:
            assert not (tmp_path / "out/unit_diagnostics.json").exists()


@pytest.mark.parametrize("fault", [None, "materialize", "void"])
def test_parked_workspace(lives, unit_sessions, tmp_path, monkeypatch, fault):
    case = lives["t1-g1", "B0"]
    probes = case["compiled"].probes
    first = next(p for p, q in zip(probes, probes[1:], strict=False) if p.checkpoint == q.checkpoint)
    damaged = []

    def damage(workspace):
        parked = next(workspace.parent.glob(".workspace.original-*"))
        (parked / "parked-change").write_text("changed")
        damaged.append(True)

    damage_probe(monkeypatch, case, damage, session_index=first.index)
    materialize = life.materialize

    def rebuild(*args, **kw):
        materialize(*args, **kw)
        if damaged and fault == "materialize":
            (kw["root"] / "bad-rebuild").write_text("bad")

    monkeypatch.setattr(life, "materialize", rebuild)
    if fault == "void":
        holds = life.precondition_holds
        def mismatch(*a, **k):
            if damaged:
                raise life.HarnessFailed("void_mismatch")
            return holds(*a, **k)
        monkeypatch.setattr(life, "precondition_holds", mismatch)
    result = unit(case, tmp_path)
    assert result.attempts == (3 if fault else 1)
    run = result.runs[0]
    assert any(r["surface"] == "workspace" for r in run.parked_receipts)
    if fault == "materialize":
        assert run.stopped == ("INFRA_FAILURE", "workspace_state", first.index + 1)
    elif fault == "void":
        assert run.stopped[1] == "void_mismatch"
    elif not fault:
        assert not run.classes and run.stopped is None


def test_docs_name_parked_rules():
    for name in ("t2", "t2lite"):
        text = (Path(__file__).parents[2] / f"docs/developers/{name}.md").read_text()
        assert "system_audit_failure" in text and "parked workspace" in text and "another parked surface" in text


def test_failed_restore_has_no_second_hash(tmp_path):
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    home.mkdir()
    workspace.mkdir()
    run = life.LifeRun("system", "L", "B0", 0)

    @contextmanager
    def fail():
        yield
        raise OSError("restore failed")

    with pytest.raises(OSError):
        with life.ParkedProbe([({"root": "HERMES_HOME", "relative": "."}, home)], workspace,
                              SimpleNamespace(checkpoint=1), 1, run, [1], None) as stack:
            stack.enter_context(stack.watch(fail(), home))
            (home / "changed").write_text("changed")
    assert not run.parked_receipts and run.restore_failures == ["OSError"]


@pytest.mark.parametrize("kind,shared", [("fifo", True), ("fifo", False), ("unreadable", True), ("unreadable_dir", True)])
def test_unhashable_workspace(lives, unit_sessions, tmp_path, monkeypatch, kind, shared):
    case = lives["t1-g1", "B0"]
    clean = unit(case, tmp_path / "clean")
    probes, calls, damaged = case["compiled"].probes, [], []
    first = next(p for p, q in zip(probes, probes[1:], strict=False) if p.checkpoint == q.checkpoint)
    selected = first if shared else probes[-1]
    materialize = life.materialize

    def rebuild(*a, **k):
        calls.append(k["boundary"])
        return materialize(*a, **k)

    def damage(workspace):
        parked = next(workspace.parent.glob(".workspace.original-*")) / "damage"
        damaged.append((parked, workspace / "damage", calls[-1], len(calls)))
        if kind == "fifo":
            os.mkfifo(parked)
        else:
            if kind == "unreadable_dir":
                parked.mkdir()
                (parked / "file").write_text("unreadable")
            else:
                parked.write_text("unreadable")
            parked.chmod(0)

    monkeypatch.setattr(life, "materialize", rebuild)
    damage_probe(monkeypatch, case, damage, session_index=selected.index)
    try:
        result = unit(case, tmp_path / "broken")
    finally:
        for parked, canonical, _, _ in damaged:
            for path in (parked, canonical):
                if path.exists():
                    path.chmod(0o700 if path.is_dir() else 0o600)
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["surface"] == "workspace"]
    assert receipt["session"] == selected.index
    assert receipt["after"] == "unhashable:" + ("ValueError" if kind == "fifo" else "PermissionError")
    if kind == "unreadable_dir":
        assert result.attempts == 3
        assert run.stopped == ("INFRA_FAILURE", "PermissionError", selected.index + 1)
        return
    assert result.attempts == 1 and result.scores == clean.scores
    assert not run.classes and run.stopped is None
    _, _, boundary, count = damaged[0]
    assert calls[count:].count(boundary) == int(shared)


@pytest.mark.parametrize("kind", ["fifo", "unreadable", "elsewhere"])
def test_unhashable_hermes(lives, unit_sessions, tmp_path, monkeypatch, kind):
    case, damaged = lives["t1-g1", "B0"], []

    def damage(workspace):
        home = next(workspace.parent.glob(".hermes-home.original-*"))
        rel = "other" if kind == "elsewhere" else "memories/MEMORY.md"
        path = home / rel
        path.parent.mkdir(exist_ok=True)
        path.unlink(missing_ok=True)
        damaged.extend((path, workspace.parent / "hermes-home" / rel))
        if kind == "unreadable":
            path.write_text("unreadable")
            path.chmod(0)
        else:
            os.mkfifo(path)

    damage_probe(monkeypatch, case, damage, session_index=case["compiled"].probes[-1].index)
    if kind != "unreadable":
        a4_failure(monkeypatch, ("memory",))
    try:
        result = unit(case, tmp_path)
    finally:
        for path in damaged:
            if path.exists():
                path.chmod(0o600)
    run = result.runs[0]
    assert {r["path"] for r in run.parked_receipts} == (
        {"."} if kind == "elsewhere" else {".", "memories/MEMORY.md"})
    assert result.attempts == 3 and not run.classes
    assert all(row["infra_reruns"] == 2 for row in result.scores.values())
    if kind != "elsewhere":
        receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
        assert receipt["after"] == "unhashable:" + (
            "PermissionError" if kind == "unreadable" else "not_regular")
        if kind == "unreadable":
            assert run.audit_phase == {"phase": "effects", "path": "memories/MEMORY.md", "other_failures": [],
                "file_state": {"observation": "unhashable:PermissionError", "state": receipt["after_state"],
                               "reread_raises": False}}


@pytest.mark.parametrize("kind", ["credential", "worker_protocol"])
def test_fifo_keeps_session_outcome(lives, unit_sessions, tmp_path, monkeypatch, kind):
    case = lives["t1-g1", "B0"]
    error = life.LiveCredentialStop("fixture_stop") if kind == "credential" else life.HarnessFailed(kind)

    def damage(workspace):
        os.mkfifo(next(workspace.parent.glob(".workspace.original-*")) / "damage")
        raise error

    probe, _ = damage_probe(monkeypatch, case, damage)
    if kind == "credential":
        with pytest.raises(life.LiveCredentialStop) as raised:
            unit(case, tmp_path)
        assert raised.value is error
    else:
        result = unit(case, tmp_path)
        assert result.attempts == 1
        assert result.runs[0].stopped == ("SYSTEM_FAILURE", kind, probe.index)


@pytest.mark.parametrize("entry", ["absent", "file", "dir", "link", "parent_link", "parent_file", "fifo"])
def test_native_observations_are_local(tmp_path, entry):
    home = tmp_path / "home"
    home.mkdir()
    memory = home / "memories/MEMORY.md"
    memory.parent.mkdir()
    if entry in ("file", "dir", "parent_link", "parent_file"):
        memory.write_bytes(b"memory")
    if entry == "dir":
        memory.unlink()
        memory.mkdir()
        (memory / "child").write_bytes(b"nested")
    elif entry == "link":
        memory.symlink_to("absent")
    expected = sha256_canon([r for r in tree_listing(home, []) if r["path"].startswith("memories/MEMORY.md")])
    if entry in ("parent_link", "parent_file"):
        memory.parent.rename(home / "elsewhere")
        if entry == "parent_link":
            memory.parent.symlink_to("elsewhere")
        else:
            memory.parent.write_text("not a folder")
        expected = sha256_canon([])
    if entry == "fifo":
        os.mkfifo(memory)
        expected = "unhashable:not_regular"
    os.mkfifo(home / "unrelated")
    values = life.ParkedProbe.hashes(home, True)
    assert values["."] == "unhashable:ValueError"
    assert values["memories/MEMORY.md"] == expected


@pytest.mark.parametrize("phase", ["enter", "exit", "workspace_hash", "workspace_match", "stable", "base_exception"])
def test_observation_errors_preserve_stack_result(tmp_path, monkeypatch, phase):
    from bicentennial.runner import parked

    tmp_path.joinpath("memories").mkdir()
    run = life.LifeRun("system", "L", "B0", 0)
    checkpoints, failure = [1], KeyboardInterrupt() if phase == "base_exception" else PermissionError()
    original = parked.tree_listing

    def fail(*a, **k):
        raise failure

    stack = life.ParkedProbe([({"root": "HERMES_HOME", "relative": "."}, tmp_path)], tmp_path,
                             SimpleNamespace(checkpoint=1), 1, run, checkpoints, "expected")
    if phase in ("enter", "stable", "base_exception"):
        monkeypatch.setattr(parked, "tree_listing", fail)
    if phase == "base_exception":
        with pytest.raises(KeyboardInterrupt) as raised:
            stack.__enter__()
        assert raised.value is failure
        return
    stack.__enter__()
    monkeypatch.setattr(parked, "tree_listing", original if phase == "enter" else fail)
    if phase == "workspace_hash":
        monkeypatch.setattr(parked, "tree_listing", original)
        monkeypatch.setattr(parked, "workspace_hash", fail)
    elif phase == "workspace_match":
        monkeypatch.setattr(parked, "workspace_hash", lambda path: "expected")
    stack.push(lambda *a: True)
    assert stack.__exit__(ValueError, ValueError("session"), None) is True
    assert not checkpoints
    if phase == "stable":
        assert not run.parked_receipts


@pytest.mark.parametrize("kind", ["head", "root_mode"])
def test_changed_workspace_rebuilt(lives, unit_sessions, tmp_path, monkeypatch, kind):
    case = lives["t1-g1", "B0"]
    probes, builds, damaged, observed = case["compiled"].probes, [], [], []
    first = next(p for p, q in zip(probes, probes[1:], strict=False) if p.checkpoint == q.checkpoint)
    materialize, clone = life.materialize, life.clone_tree

    def rebuild(*a, **k):
        materialize(*a, **k)
        builds.append(k["boundary"])

    def cloning(source, dest):
        if source.name == "workspace" and dest.parent.name == str(first.index + 1):
            observed.append(((source / ".git/HEAD").read_bytes(), source.stat().st_mode & 0o7777))
        return clone(source, dest)

    def damage(workspace):
        parked = next(workspace.parent.glob(".workspace.original-*"))
        expected = ((parked / ".git/HEAD").read_bytes(), parked.stat().st_mode & 0o7777)
        assert expected[1] == 0o755
        damaged.append((parked, workspace, expected, builds[-1], len(builds)))
        if kind == "head":
            (parked / ".git/HEAD").write_text("ref: refs/heads/changed\n")
        else:
            parked.chmod(0o555)

    monkeypatch.setattr(life, "materialize", rebuild)
    monkeypatch.setattr(life, "clone_tree", cloning)
    damage_probe(monkeypatch, case, damage, session_index=first.index)
    try:
        result = unit(case, tmp_path)
    finally:
        for parked, workspace, expected, _, _ in damaged:
            for path in (parked, workspace):
                if path.exists():
                    path.chmod(expected[1])
    run = result.runs[0]
    assert any(r["surface"] == "workspace" and r["session"] == first.index for r in run.parked_receipts)
    _, _, expected, boundary, count = damaged[0]
    assert builds[count:].count(boundary) == 1
    assert observed == [expected]
    assert result.attempts == 1 and run.stopped is None and not run.classes
    assert all(row["base_verdict"] != "VOID" and row["infra_reruns"] == 0 for row in result.scores.values())


@pytest.mark.parametrize("other", ["A1.mismatches", "A3.failures", "raises"])
def test_effects_exception_keeps_other_failure(lives, unit_sessions, tmp_path, monkeypatch, other):
    case, calls = lives["t1-g1", "B0"], []

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"\xff")

    damage_probe(monkeypatch, case, damage)

    original = life.audit

    def audit(*a, **kw):
        calls.append(kw["effects"])
        if other == "raises":
            raise ValueError("effects-free audit failure")
        report = original(*a, **kw)
        report["A1" if other.startswith("A1.") else "A3"][
            "mismatches" if other.startswith("A1.") else "failures"] = [1]
        return report

    monkeypatch.setattr(life, "audit", audit)
    result = unit(case, tmp_path)
    assert result.attempts == 3
    run = result.runs[0]
    assert not run.classes and any(r["path"] == "memories/MEMORY.md" for r in run.parked_receipts)
    assert calls == [None] * 3
    assert run.audit_phase["other_failures"] == (["audit_exception"] if other == "raises" else ["A1.mismatches" if other.startswith("A1.") else other])
    assert canon(run.audit) == b'{"failures":["audit_exception"],"status":"INFRA_FAILURE"}'


def a4_failure(monkeypatch, targets, codes=("A4.gaps",), results=None):
    load = life.load_ledger

    def ledger(*a):
        rows, blobs, extra = load(*a)
        seq = max((r["seq"] for r in rows), default=0) + 1
        calls = [dict(id=f"gap-{i}", function=dict(name="memory", arguments=(
            target if target == "bad-json" else json.dumps({} if target == "default" else {"target": target}))))
            for i, target in enumerate(targets)]
        blob = {"choices": [{"message": {"tool_calls": calls}}]}
        return [*rows, dict(seq=seq, resp="gap-response")], dict(blobs, **{"gap-response": blob}), extra

    def audit(rows, *a, **kw):
        if results is not None:
            calls = [dict(id=f"gap-{i}", record=rows[-1]["seq"], session=1,
                          arguments=json.dumps(dict(target=target, action="add", content=f"missing entry {i}")),
                          result=json.dumps(result)) for i, (target, result) in enumerate(zip(targets, results, strict=True))]
            report = kw["effects"](calls, [], "chat")
            assert report["gaps"] == [c["id"] for c in calls]
            assert [c["applied"] for c in report["calls"]] == [r.get("success") for r in results]
            assert all(not o["in_store"] for c in report["calls"] for o in c["operations"])
            return {"A4": report}
        calls = [dict(call=f"gap-{i}", record=rows[-1]["seq"], applied=True) for i in range(len(targets))]
        return {"A4": dict(gaps=[c["call"] for c in calls], calls=calls)}

    monkeypatch.setattr(life, "load_ledger", ledger)
    monkeypatch.setattr(life, "audit", audit)
    monkeypatch.setattr(life, "failures", lambda report: list(codes))
    monkeypatch.setattr(life, "run_status", lambda *a: "INFRA_FAILURE")


@pytest.mark.parametrize("changed,targets,attempts", [
    (("USER.md",), ("memory",), 3),
    (("MEMORY.md", "USER.md"), ("memory", "user"), 1),
    (("MEMORY.md",), ("memory", "user"), 3),
    (("MEMORY.md",), ("bad-json",), 3),
    (("MEMORY.md",), ([],), 3),
    (("MEMORY.md",), ("unknown",), 3),
    (("MEMORY.md",), ("default",), 1),
])
def test_gaps_require_matching_files(lives, unit_sessions, tmp_path, monkeypatch, changed, targets, attempts):
    case = lives["t1-g1", "B0"]

    def damage(workspace):
        home = next(workspace.parent.glob(".hermes-home.original-*"))
        for name in changed:
            path = home / "memories" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("changed")

    damage_probe(monkeypatch, case, damage)
    a4_failure(monkeypatch, targets)
    result = unit(case, tmp_path)
    assert result.attempts == attempts
    run = result.runs[0]
    assert {r["path"] for r in run.parked_receipts if r["path"] != "."} == {"memories/" + n for n in changed}
    assert set(run.classes.values()) == ({("SYSTEM_FAILURE", "system_audit_failure")} if attempts == 1 else set())
    assert all(row["infra_reruns"] == attempts - 1 for row in result.scores.values())


def test_healthy_audit_bytes(lives, unit_sessions, tmp_path):
    result = unit(lives["t1-g1", "B0"], tmp_path)
    run, = result.runs
    assert canon(run.audit) == b'{"failures":[],"status":"OK"}'
    assert not run.audit_phase and not run.parked_receipts
    assert not (tmp_path / "out/unit_diagnostics.json").exists()


@pytest.mark.parametrize("results,attempts", [
    (({},), 3),
    (({}, {"success": True}), 3),
    (({"success": True}, {"success": True}), 1),
], ids=["unclassified", "mixed", "applied_only"])
def test_r7_gaps_require_applied_writes(lives, unit_sessions, tmp_path, monkeypatch, results, attempts):
    case = lives["t1-g1", "B0"]

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"reader's proving bytes")

    damage_probe(monkeypatch, case, damage, session_index=case["compiled"].probes[-1].index)
    a4_failure(monkeypatch, ("memory",) * len(results), results=results)
    result = unit(case, tmp_path)
    assert result.attempts == attempts
    run = result.runs[0]
    assert any(r["path"] == "memories/MEMORY.md" and r["proven"] for r in run.parked_receipts)
    assert run.audit == dict(status="INFRA_FAILURE", failures=["A4.gaps"])
    assert run.audit_phase["gap_paths"] == ["memories/MEMORY.md"]
    assert run.audit_phase.get("gap_unclassified", []) == [f"gap-{i}" for i, r in enumerate(results) if "success" not in r]
    assert set(run.classes.values()) == ({("SYSTEM_FAILURE", "system_audit_failure")} if attempts == 1 else set())
    assert all(row["infra_reruns"] == attempts - 1 for row in result.scores.values())


@pytest.mark.parametrize("arm", ["effects", "gaps"])
def test_r4_unchanged_io_fault_is_unproven(lives, unit_sessions, tmp_path, monkeypatch, arm):
    case, fault_paths = lives["t1-g1", "B0"], set()
    enter, opening = life.ParkedProbe.__enter__, Path.open

    def baseline(stack):
        for _, home, native in stack.targets:
            if native:
                path = home / "memories/MEMORY.md"
                path.parent.mkdir(exist_ok=True)
                path.write_text("unchanged")
        return enter(stack)

    def damage(workspace):
        home = next(workspace.parent.glob(".hermes-home.original-*"))
        fault_paths.update((home / "memories/MEMORY.md", workspace.parent / "hermes-home/memories/MEMORY.md"))

    def fault(path, mode="r", *a, **kw):
        if path in fault_paths and (arm == "effects" or "b" in mode):
            raise OSError(errno.EIO, "injected storage fault")
        return opening(path, mode, *a, **kw)

    monkeypatch.setattr(life.ParkedProbe, "__enter__", baseline)
    monkeypatch.setattr(Path, "open", fault)
    damage_probe(monkeypatch, case, damage, session_index=case["compiled"].probes[-1].index)
    if arm == "gaps":
        a4_failure(monkeypatch, ("memory",))
    result = unit(case, tmp_path)
    assert result.attempts == 3
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["after"] == "unhashable:OSError" and not receipt["proven"]
    assert receipt["before_state"] == receipt["after_state"]
    assert not run.classes
    assert run.audit_phase["phase"] == ("effects" if arm == "effects" else "audit")
    diag = json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes())["attempts"][0]
    assert diag["parked_receipts"] == run.parked_receipts
    assert all(row["infra_reruns"] == 2 for row in result.scores.values())


@pytest.mark.parametrize("later", ["valid", "invalid", "mode"])
def test_r4_effects_requires_current_explanation(lives, unit_sessions, tmp_path, monkeypatch, later):
    case, changed, writes, reads = lives["t1-g1", "B0"], [], [], []
    probe = case["compiled"].probes[-1 if later == "mode" else 0]
    if later == "mode":
        enter = life.ParkedProbe.__enter__

        def baseline(stack):
            for _, home, native in stack.targets:
                if native:
                    path = home / "memories/MEMORY.md"
                    path.parent.mkdir(exist_ok=True)
                    if not path.exists():
                        path.write_text("readable baseline")
            return enter(stack)

        monkeypatch.setattr(life.ParkedProbe, "__enter__", baseline)

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"\xff")
        if later == "mode":
            path.chmod(0)
        changed.extend((path, workspace.parent / "hermes-home/memories/MEMORY.md"))

    damage_probe(monkeypatch, case, damage, session_index=probe.index)
    session = helpers.adapter.HermesAdapter.run_session
    replay = {s["index"] for s in case["compiled"].script["sessions"] if s["kind"] == "replay"}

    def legitimate(self, index, **kw):
        result = session(self, index, **kw)
        path = self.paths["hermes_home"] / "memories/MEMORY.md"
        if path in changed and index in replay and later != "mode":
            path.write_bytes(b"later legitimate write" + (b"\xff" if later == "invalid" else b""))
            writes.append(index)
        return result

    effects, read = life.hermes_effects, Path.read_text
    active = []

    def final_effects(home, **kw):
        active[:] = [home / "memories/MEMORY.md", False]
        return effects(home, **kw)

    def transient(path, *a, **kw):
        if active and path == active[0]:
            reads.append(path)
            if later == "valid" and not active[1]:
                active[1] = True
                raise OSError(errno.EIO, "final read only")
        return read(path, *a, **kw)

    monkeypatch.setattr(helpers.adapter.HermesAdapter, "run_session", legitimate)
    monkeypatch.setattr(life, "hermes_effects", final_effects)
    monkeypatch.setattr(Path, "read_text", transient)
    try:
        result = unit(case, tmp_path)
    finally:
        if later == "mode":
            for path in changed:
                if path.exists():
                    path.chmod(0o600)
    if later != "mode":
        assert writes
    assert result.attempts == (1 if later == "invalid" else 3)
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["proven"]
    state = run.audit_phase["file_state"]
    assert len(reads) == 2 * result.attempts
    assert state["reread_raises"] == (later == "invalid")
    assert run.audit_phase["other_failures"] == []
    if later == "mode":
        assert state["observation"] == "unhashable:PermissionError"
        assert state["state"] == receipt["after_state"]
        assert state["state"]["mode"] == 0
        assert receipt["before_state"] != receipt["after_state"]
    else:
        assert writes and not state["observation"].startswith("unhashable:")
        assert state["observation"] not in (receipt["before"], receipt["after"])
    assert set(run.classes.values()) == ({("SYSTEM_FAILURE", "system_audit_failure")} if later == "invalid" else set())
    assert all(row["infra_reruns"] == (0 if later == "invalid" else 2) for row in result.scores.values())


# Round 5: deterministic states and the effects reader's own refusals.
def r5_baseline(monkeypatch, probe, *, absent=False):
    enter = life.ParkedProbe.__enter__

    def baseline(stack):
        for _, home, native in stack.targets:
            if native:
                path = home / "memories/MEMORY.md"
                path.parent.mkdir(exist_ok=True)
                if absent and stack.index == probe.index:
                    path.unlink(missing_ok=True)
                elif not path.exists():
                    path.write_text("baseline")
        return enter(stack)

    monkeypatch.setattr(life.ParkedProbe, "__enter__", baseline)


@pytest.mark.parametrize("fault", ["after", "persistent", "eperm", "eacces"])
def test_r5_unknown_lstat_is_not_change(lives, unit_sessions, tmp_path, monkeypatch, fault):
    case, paths = lives["t1-g1", "B0"], set()
    probe = case["compiled"].probes[-1]
    r5_baseline(monkeypatch, probe)
    lstat, exiting = Path.lstat, life.ParkedProbe.__exit__
    after = []

    def damage(workspace):
        paths.add(workspace.parent / "hermes-home/memories/MEMORY.md")

    def exit_probe(stack, *exc):
        after.append(True)
        try:
            return exiting(stack, *exc)
        finally:
            after.clear()

    def failing(path, *a, **kw):
        if path in paths and (after or fault != "after"):
            code = {"eperm": errno.EPERM, "eacces": errno.EACCES}.get(fault, errno.EIO)
            raise OSError(code, "injected lstat fault")
        return lstat(path, *a, **kw)

    damage_probe(monkeypatch, case, damage, session_index=probe.index)
    monkeypatch.setattr(life.ParkedProbe, "__exit__", exit_probe)
    monkeypatch.setattr(Path, "lstat", failing)
    if fault != "persistent":
        a4_failure(monkeypatch, ("memory",))
    result = unit(case, tmp_path)
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["after_state"] is None and not receipt["proven"]
    assert result.attempts == 3 and not run.classes
    assert all(row["infra_reruns"] == 2 for row in result.scores.values())


@pytest.mark.parametrize("fault", ["bytes", "created", "repeat", "stat", "fifo", "tradeoff"])
def test_r5_proven_receipt_needs_explanation(lives, unit_sessions, tmp_path, monkeypatch, fault):
    case, changed, writes, active, faults = lives["t1-g1", "B0"], set(), [], [], []
    probe = case["compiled"].probes[0 if fault in ("stat", "fifo", "tradeoff") else -1]
    r5_baseline(monkeypatch, probe, absent=fault == "created")

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.write_text("reader's new valid bytes")
        changed.add(workspace.parent / "hermes-home/memories/MEMORY.md")

    damage_probe(monkeypatch, case, damage, session_index=probe.index)
    session = helpers.adapter.HermesAdapter.run_session
    replay = {s["index"] for s in case["compiled"].script["sessions"] if s["kind"] == "replay"}

    def later(self, index, **kw):
        result = session(self, index, **kw)
        path = self.paths["hermes_home"] / "memories/MEMORY.md"
        if path in changed and index in replay and fault in ("stat", "fifo", "tradeoff"):
            if fault == "fifo":
                path.unlink(missing_ok=True)
                os.mkfifo(path)
            else:
                path.write_text("later replay's valid bytes")
            writes.append(index)
        return result

    effects, opening, reading, statting = life.hermes_effects, Path.open, Path.read_text, Path.lstat
    is_file, is_link = Path.is_file, Path.is_symlink

    def final(home, **kw):
        active[:] = [home / "memories/MEMORY.md", False]
        return effects(home, **kw)

    def open_fault(path, *a, **kw):
        if active and path == active[0] and fault in ("bytes", "created"):
            faults.append("open")
            raise OSError(errno.EIO, "persistent open fault")
        return opening(path, *a, **kw)

    def text_fault(path, *a, **kw):
        if active and path == active[0] and fault == "repeat":
            faults.append("text")
            raise OSError(errno.EIO, "effects and repeat only")
        return reading(path, *a, **kw)

    def stat_fault(path, *a, **kw):
        if active and path == active[0] and fault == "stat" and not active[1]:
            active[1] = True
            faults.append("stat")
            raise OSError(errno.EIO, "transient final stat fault")
        return statting(path, *a, **kw)

    def file_314(path):
        try:
            if active and path == active[0] and fault == "stat":
                stat_fault(path)
            return is_file(path)
        except OSError:  # Python 3.14 is_file's error-to-False behaviour on older interpreters too.
            return False

    if fault == "fifo":
        # Isolate audit attribution: source-damage scoring and cloning special files are separate rules.
        monkeypatch.setattr(life.SourceBaseline, "receipt", lambda *a, **kw: None)
        monkeypatch.setattr(helpers, "surface_hash", lambda *a, **kw: sha256_canon([]))
        clone = life.clone_tree

        def copy_entry(source, dest):
            if stat.S_ISFIFO(Path(source).lstat().st_mode):
                os.mkfifo(dest)
                return dest
            return shutil.copy2(source, dest)

        monkeypatch.setattr(life, "clone_tree", lambda source, dest: (
            shutil.copytree(source, dest, symlinks=True, copy_function=copy_entry)
            if source.name == "hermes-home" else clone(source, dest)))
    monkeypatch.setattr(helpers.adapter.HermesAdapter, "run_session", later)
    monkeypatch.setattr(life, "hermes_effects", final)
    monkeypatch.setattr(Path, "open", open_fault)
    monkeypatch.setattr(Path, "read_text", text_fault)
    monkeypatch.setattr(Path, "lstat", stat_fault)
    monkeypatch.setattr(Path, "is_file", file_314)
    # The entry is regular: keep the transient fault for is_file (base) or explicit lstat (fixed reader).
    monkeypatch.setattr(Path, "is_symlink", lambda p: False if active and p == active[0] and fault == "stat" else is_link(p))
    if fault in ("stat", "fifo", "tradeoff"):
        a4_failure(monkeypatch, ("memory",))
    result = unit(case, tmp_path)
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["proven"] and not receipt["after"].startswith("unhashable:")
    assert receipt["after_state"] == receipt["before_state"] or fault == "created"
    if fault in ("stat", "fifo", "tradeoff"):
        assert writes
    else:
        assert faults
        assert run.audit_phase["phase"] == "effects"
    if fault == "repeat":
        assert not run.audit_phase["file_state"]["observation"].startswith("unhashable:")
    if fault == "stat":
        assert faults == ["stat"] * result.attempts
    if fault == "fifo":
        assert run.stopped is None and not run.source_receipts
    assert result.attempts == (1 if fault == "tradeoff" else 3)
    assert set(run.classes.values()) == ({("SYSTEM_FAILURE", "system_audit_failure")} if fault == "tradeoff" else set())


@pytest.mark.parametrize("kind", ["denied", "deleted", "link"])
def test_r5_native_positive_controls(lives, unit_sessions, tmp_path, monkeypatch, kind):
    case, damaged = lives["t1-g1", "B0"], []
    probe = case["compiled"].probes[-1]
    r5_baseline(monkeypatch, probe)

    def damage(workspace):
        home = next(workspace.parent.glob(".hermes-home.original-*"))
        path = home / "memories/MEMORY.md"
        if kind == "denied":
            damaged.extend((path.parent, workspace.parent / "hermes-home/memories"))
            path.parent.chmod(0)
        else:
            path.unlink()
            if kind == "link":
                path.symlink_to("absent")

    damage_probe(monkeypatch, case, damage, session_index=probe.index)
    if kind in ("denied", "deleted"):
        a4_failure(monkeypatch, ("memory",))
    try:
        result = unit(case, tmp_path)
    finally:
        for path in damaged:
            if path.exists():
                path.chmod(0o700)
    run = result.runs[0]
    assert result.attempts == (3 if kind == "denied" else 1)
    assert set(run.classes.values()) == (set() if kind == "denied" else {("SYSTEM_FAILURE", "system_audit_failure")})
    assert any(r["path"] == "memories/MEMORY.md" and r["proven"] for r in run.parked_receipts)
    if kind == "denied":
        assert run.audit_phase["phase"] == "effects"
        assert run.audit_phase["file_state"] == dict(
            observation="unhashable:PermissionError", state="denied", reread_raises=False)


# Round 6: an unhashable observation never charges, even with a proving state.
@pytest.mark.parametrize("transient", [True, False])
def test_r6_fifo_effects_fault_is_infrastructure(lives, unit_sessions, tmp_path, monkeypatch, transient):
    case, active, faults = lives["t1-g1", "B0"], [], []
    probe = case["compiled"].probes[-1]
    r5_baseline(monkeypatch, probe)

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.unlink()
        os.mkfifo(path)

    damage_probe(monkeypatch, case, damage, session_index=probe.index)
    effects, lstat = life.hermes_effects, Path.lstat

    def final(home, **kw):
        active[:] = [home / "memories/MEMORY.md", False]
        return effects(home, **kw)

    def fault(path, *a, **kw):
        if transient and active and path == active[0] and not active[1]:
            active[1] = True
            faults.append(path)
            raise OSError(errno.EIO, "transient final effects lstat")
        return lstat(path, *a, **kw)

    monkeypatch.setattr(life, "hermes_effects", final)
    monkeypatch.setattr(Path, "lstat", fault)
    result = unit(case, tmp_path)
    run = result.runs[0]
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["proven"] and receipt["after"] == "unhashable:not_regular"
    assert receipt["after_state"]["kind"] == stat.S_IFIFO
    assert run.stopped is None and not run.source_receipts
    if transient:
        assert faults and run.audit_phase == dict(phase="effects", path="memories/MEMORY.md", other_failures=[],
            file_state=dict(observation="unhashable:not_regular", state=receipt["after_state"], reread_raises=False))
        assert not run.classes and result.attempts == 3
        assert all(row["infra_reruns"] == 2 for row in result.scores.values())
    else:  # Positive control: the effects reader reads the FIFO as empty without opening it.
        assert not faults and run.audit == dict(status="OK", failures=[])
        assert not run.classes and result.attempts == 1


def test_r6_restore_failure_never_charges(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    first, last = case["compiled"].probes[0], case["compiled"].probes[-1]

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/MEMORY.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text("reader's proving bytes")

    damage_probe(monkeypatch, case, damage, session_index=first.index)
    swap = life.swap_in

    @contextmanager
    def failing_restore(clone, canonical):
        with swap(clone, canonical):
            yield
        if canonical.name == "hermes-home" and clone.parent.name == str(last.index):
            raise OSError(errno.EIO, "injected later restore failure")

    monkeypatch.setattr(life, "swap_in", failing_restore)
    a4_failure(monkeypatch, ("memory",))
    result = unit(case, tmp_path)
    run = result.runs[0]
    assert any(r["session"] == first.index and r["path"] == "memories/MEMORY.md" and r["proven"]
               for r in run.parked_receipts)
    assert run.restore_failures == ["OSError"]
    assert run.stopped[2] == last.index and run.audit["failures"] == ["A4.gaps"]
    assert ("SYSTEM_FAILURE", "system_audit_failure") not in run.classes.values()
    assert result.attempts == 3


def test_r6_baseline_lstat_fault_is_unproven(tmp_path, monkeypatch):
    home, workspace = tmp_path / "home", tmp_path / "workspace"
    (home / "memories").mkdir(parents=True)
    workspace.mkdir()
    path = home / "memories/MEMORY.md"
    path.write_text("unchanged")
    lstat, active = Path.lstat, [True]

    def fault(target, *a, **kw):
        if active and target == path:
            raise OSError(errno.EIO, "baseline lstat only")
        return lstat(target, *a, **kw)

    monkeypatch.setattr(Path, "lstat", fault)
    run = life.LifeRun("system", "L", "B0", 0)
    with life.ParkedProbe([({"root": "HERMES_HOME", "relative": "."}, home)], workspace,
                          SimpleNamespace(checkpoint=1), 1, run, [1], None):
        active.clear()
    receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
    assert receipt["before"] == "unhashable:OSError" and receipt["before_state"] is None
    assert receipt["after_state"]["kind"] == stat.S_IFREG and not receipt["proven"]
    assert path.read_text() == "unchanged"


@pytest.mark.parametrize("condition", ["eperm", "parent_file", "not_directory"])
def test_r6_state_fault_origins(tmp_path, monkeypatch, condition):
    parent, rel = tmp_path / "memories", "memories/MEMORY.md"
    if condition == "eperm":
        parent.mkdir()
        parent.chmod(0)
    else:
        parent.write_text("not a directory")
        parent.chmod(0o600)
    lstat = Path.lstat

    def fault(path, *a, **kw):
        if path == tmp_path / rel and condition != "not_directory":
            raise PermissionError(errno.EPERM if condition == "eperm" else errno.EACCES, "injected denial")
        return lstat(path, *a, **kw)

    monkeypatch.setattr(Path, "lstat", fault)
    try:
        assert life.ParkedProbe.state(tmp_path, rel) == ("absent" if condition == "not_directory" else None)
        if condition == "not_directory":
            assert life.ParkedProbe.observe(tmp_path, rel) == sha256_canon([])
    finally:
        parent.chmod(0o700 if condition == "eperm" else 0o600)


@pytest.mark.parametrize("arm", ["gaps", "effects"])
def test_r6_user_receipt_never_explains_memory(lives, unit_sessions, tmp_path, monkeypatch, arm):
    case = lives["t1-g1", "B0"]

    def damage(workspace):
        path = next(workspace.parent.glob(".hermes-home.original-*")) / "memories/USER.md"
        path.parent.mkdir(exist_ok=True)
        path.write_text("reader changed only user")

    damage_probe(monkeypatch, case, damage, session_index=case["compiled"].probes[-1].index)
    if arm == "gaps":
        a4_failure(monkeypatch, ("memory",))
    else:
        effects = life.hermes_effects

        def final(home, **kw):
            (home / "memories/MEMORY.md").write_bytes(b"\xff")
            return effects(home, **kw)

        monkeypatch.setattr(life, "hermes_effects", final)
    result = unit(case, tmp_path)
    run = result.runs[0]
    assert {r["path"] for r in run.parked_receipts if r["path"] != "."} == {"memories/USER.md"}
    if arm == "effects":
        assert run.audit_phase["path"] == "memories/MEMORY.md"
        assert run.audit_phase["file_state"]["reread_raises"]
        assert run.audit_phase["other_failures"] == []
    assert not run.classes and result.attempts == 3
