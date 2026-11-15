"""Parked-original attribution through the offline unit path."""

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_unreadable_state import damage_probe, helpers, unit

from bicentennial.canon import canon
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
    elif failure:
        monkeypatch.setattr(life, "audit", lambda *a, **k: {})
        monkeypatch.setattr(life, "failures", lambda report: ["A4.gaps", "A3.missing"]
                            if failure == "mixed" else ["A4.gaps" if failure == "classed" else failure])
        monkeypatch.setattr(life, "run_status", lambda *a: "INFRA_FAILURE")
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
        assert run.audit_phase == {"phase": "audit"}
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
        assert run.stopped[1] == "workspace_state"
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
