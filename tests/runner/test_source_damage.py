"""Source receipts and per-arm events through socket-free live unit fixtures."""

import json
import os
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401
from test_unreadable_state import harness, lives, unit, unit_sessions  # noqa: F401

from bicentennial.harness.hermes import adapter
from bicentennial.runner import life, t2, t2lite, units


def seed_store(monkeypatch, malformed=False):
    measure = life._surface_bytes

    def seeded(surfaces):
        nonlocal malformed
        root = surfaces[0][1]
        db = root / "test.db"
        if not db.exists():
            with sqlite3.connect(db) as con:
                con.execute("CREATE TABLE facts(text)")
            if malformed:
                db.write_bytes(b"SQLite format 3\x00" + b"broken" * 100)
                db.with_name("test.db-wal").touch()
                malformed = False
        return measure(surfaces)

    monkeypatch.setattr(life, "_surface_bytes", seeded)


@pytest.mark.parametrize("kind", ["database", "fifo", "root"])
def test_source_damage_scores_once_and_restores(lives, unit_sessions, tmp_path, monkeypatch, kind):  # noqa: F811
    seed_store(monkeypatch)
    original, cleanup = adapter.HermesAdapter.run_session, life.LifeRun.cleanup

    def damage(self, index, **kw):
        result = original(self, index, **kw)
        if result.kind == "probe":
            root = self.paths["hermes_home"]
            if kind == "database":
                (root / "test.db").write_bytes(b"SQLite format 3\x00" + b"broken" * 100)
                (root / "test.db-wal").touch()
            elif kind == "fifo":
                os.mkfifo(root / "bad-entry")
            else:
                root.rename(root.with_name("removed-by-system"))
                root.write_bytes(b"system replaced root")
        return result

    def release(run):
        receipt, = run.source_receipts
        canonical = Path(receipt["root"])
        assert canonical.is_dir()
        with sqlite3.connect((canonical / "test.db").as_uri() + "?mode=ro", uri=True) as con:
            assert con.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        cleanup(run)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", damage)
    monkeypatch.setattr(life.LifeRun, "cleanup", release)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 1
    run, = result.runs
    assert run.stopped[:2] == ("SYSTEM_FAILURE", "invalid_store" if kind == "database" else "invalid_surface")
    assert not run.restore_failures
    assert all(row["infra_reruns"] == 0 for row in result.scores.values())
    kept = Path(run.source_receipts[0]["kept"])
    assert kept.lstat() and not run._root.exists()
    if kind == "root":
        assert kept.read_bytes() == b"system replaced root"
    diagnostic = json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes())
    assert diagnostic["attempts"][0]["source_receipts"] == run.source_receipts


@pytest.mark.parametrize("fault", ["copy", "checker", "baseline", "busy", "harness_path"])
def test_unattributed_fault_redoes_unit(lives, unit_sessions, tmp_path, monkeypatch, fault):  # noqa: F811
    seed_store(monkeypatch, malformed=fault == "baseline")
    original, read = adapter.HermesAdapter.run_session, Path.open
    failed, checking = [], []
    clone = life.clone_tree

    def copy(source, target):
        result = clone(source, target)
        if fault == "copy" and not failed and target.parent.parent.name == "probe" and (target / "test.db").exists():
            failed.append(True)
            (target / "test.db").write_bytes(b"SQLite format 3\x00" + b"broken" * 100)
            (target / "test.db-wal").touch()
        return result

    def opened(path, *args, **kw):
        if fault == "checker" and checking and path.name == "test.db":
            raise OSError("injected checker read fault")
        return read(path, *args, **kw)

    def session(self, index, **kw):
        checking.clear()
        result = original(self, index, **kw)
        if result.kind == "probe" and (not failed or fault == "copy" and len(failed) == 1):
            failed.append(True)
            if fault in ("baseline", "copy"):
                from bicentennial.systems.hermes_plugin import checkpoint_sqlite
                checkpoint_sqlite([self.paths["hermes_home"]])
            if fault == "checker":
                checking.append(True)
            if fault == "harness_path":
                (self.paths["hermes_home"] / "config.yaml").unlink(missing_ok=True)
                os.mkfifo(self.paths["hermes_home"] / "config.yaml")
            raise adapter.HarnessFailed("checkpoint_busy") if fault == "busy" else OSError("injected fault")
        return result

    monkeypatch.setattr(life, "clone_tree", copy)
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2
    first, final = result.runs
    assert first.stopped[0] == "INFRA_FAILURE" and final.stopped is None
    assert not first.source_receipts and all(r["infra_reruns"] == 1 for r in result.scores.values())
    from bicentennial.runner.hermes_score import infrastructure_counts
    assert infrastructure_counts(result.runs) == {"system": {first.stopped[1]: 1}}


@pytest.mark.parametrize("read_error", [None, OSError, ValueError])
def test_nonprobe_proven_cause_counts_incidental(lives, unit_sessions, tmp_path, monkeypatch, read_error):  # noqa: F811
    original = adapter.HermesAdapter.run_session
    records, pending = adapter.HermesAdapter.records, []

    def session(self, index, **kw):
        if index == 1:
            self.director.start_session(index, kw["sim_t_s"], kw["lock_hash"], kw["attempt_id"],
                                        self.paths["root"] / "ledger")
            pending.append(dict(seq=1, attempt_id=kw["attempt_id"], cursor=dict(session=index), role="unknown", status=400))
            raise adapter.HarnessFailed("worker_protocol")
        return original(self, index, **kw)

    def rows(self):
        if pending:
            row = pending.pop()
            if read_error:
                raise read_error("injected ledger read fault")
            return [row, dict(row, attempt_id="foreign"), dict(row, cursor=dict(session=2))]
        return records(self)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    monkeypatch.setattr(adapter.HermesAdapter, "records", rows)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 1
    assert result.runs[0].stopped == ("SYSTEM_FAILURE", "worker_protocol", 1)
    assert result.runs[0].incidental_unknown_400 == (0 if read_error else 1)


@pytest.mark.parametrize("tier,control", [("t2", None), ("t2lite", None), ("t2", "no_memory")])
def test_infrastructure_disclosure_all_attempts(tier, control, request, monkeypatch):
    state = request.getfixturevalue("t2_scenario" if tier == "t2" else "scenario")
    original = units.run_life

    def run(**kw):
        found = original(**kw)
        if kw["attempt"] == 0:
            return replace(found, stopped=("INFRA_FAILURE", "checkpoint_busy", 1),
                classes={i["item_id"]: ("INFRA_FAILURE", "checkpoint_busy") for i in kw["items"]})
        return replace(found, incidental_unknown_400=1)

    monkeypatch.setattr(units, "run_life", run)
    assert state.invoke(**({"control": control} if control else {})) == 0
    runner = t2 if tier == "t2" else t2lite
    counts = runner._read(state.out, "disclosures.json")["infrastructure_events"]
    assert counts == {arm: {"checkpoint_busy": 4, "incidental_unknown_400": 4}
                      for arm in ([control] if control else ["no_memory", "system"])}


def test_unit_diagnostics_keep_every_attempt(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    """A voided attempt keeps its record beside the scored one (part 1's review: the list is cumulative)."""
    original = units.run_life

    def run(**kw):
        found = original(**kw)
        if kw["attempt"] == 0:
            return replace(found, stopped=("INFRA_FAILURE", "checkpoint_busy", 1),
                classes={i["item_id"]: ("INFRA_FAILURE", "checkpoint_busy") for i in kw["items"]})
        return replace(found, incidental_unknown_400=1)

    monkeypatch.setattr(units, "run_life", run)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2
    assert json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes()) == dict(attempts=[
        dict(attempt=0, stopped=["INFRA_FAILURE", "checkpoint_busy", 1], incidental_unknown_400=0,
             infra_item_labels=["checkpoint_busy"]),
        dict(attempt=1, stopped=None, incidental_unknown_400=1)])
