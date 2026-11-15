"""Parked-original attribution through the offline unit path."""

import json
import os
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
        read, is_file = Path.read_text, Path.is_file
        monkeypatch.setattr(Path, "is_file", lambda p: True if p.name == (
            "USER.md" if changed else "MEMORY.md") else is_file(p))

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
    if kind == "elsewhere":
        assert result.attempts == 3 and not run.classes
        assert all(row["infra_reruns"] == 2 for row in result.scores.values())
    else:
        assert result.attempts == 1
        assert set(run.classes.values()) == {("SYSTEM_FAILURE", "system_audit_failure")}
        assert all(row["failure_class"] == "SYSTEM_FAILURE" and row["infra_reruns"] == 0
                   for row in result.scores.values())
        receipt, = [r for r in run.parked_receipts if r["path"] == "memories/MEMORY.md"]
        assert receipt["after"] == "unhashable:" + (
            "PermissionError" if kind == "unreadable" else "not_regular")
        if kind == "unreadable":
            assert run.audit_phase == {"phase": "effects", "path": "memories/MEMORY.md", "other_failures": []}


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


def a4_failure(monkeypatch, targets, codes=("A4.gaps",)):
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
        calls = [dict(call=f"gap-{i}", record=rows[-1]["seq"]) for i in range(len(targets))]
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
