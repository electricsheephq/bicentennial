"""Source receipts and per-arm events through socket-free live unit fixtures."""

import errno
import json
import os
import shutil
import socket
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401
from test_unreadable_state import harness, lives, unit, unit_sessions  # noqa: F401

from bicentennial.audit.source_damage import SourceBaseline
from bicentennial.canon import canon
from bicentennial.harness.hermes import adapter
from bicentennial.runner import life, t2, t2lite, units
from bicentennial.runner.hermes_score import infrastructure_counts


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


@pytest.mark.parametrize("kind", ["database", "fifo", "root", "symlink", "link_bytes", "cross", "copy_fail"])
def test_source_damage_scores_once_and_restores(lives, unit_sessions, tmp_path, monkeypatch, kind):  # noqa: F811
    seed_store(monkeypatch)
    original, cleanup = adapter.HermesAdapter.run_session, life.LifeRun.cleanup
    roots = []
    outside = tmp_path / "outside"
    outside.write_bytes(b"credential-needle")
    rename, copy = os.rename, shutil.copy2

    def move(source, target):
        if "source_damage" in Path(target).parts:
            raise OSError(errno.EXDEV, "injected cross-device move")
        return rename(source, target)

    def copied(source, target, **kw):
        if kind == "copy_fail":
            Path(target).write_bytes(b"partial")  # a copy that fails partway
            raise PermissionError("injected copy failure")
        return copy(source, target, **kw)

    if kind in ("cross", "copy_fail"):
        monkeypatch.setattr(os, "rename", move)
        monkeypatch.setattr(shutil.move, "__defaults__", (copied,))

    def damage(self, index, **kw):
        result = original(self, index, **kw)
        if result.kind == "probe":
            root = self.paths["hermes_home"]
            roots.append(root)
            if kind == "database":
                (root / "test.db").write_bytes(b"SQLite format 3\x00" + b"broken" * 100)
                (root / "test.db-wal").touch()
            elif kind == "fifo":
                os.mkfifo(root / "bad-entry")
            else:
                root.rename(root.with_name("removed-by-system"))
                if kind == "symlink":
                    root.symlink_to(os.path.relpath(outside, root.parent))
                elif kind == "link_bytes":
                    os.symlink(b"missing-\xff", os.fsencode(root))  # link text that is not UTF-8
                else:
                    root.write_bytes(b"system replaced root")
        return result

    def release(run):
        canonical = roots[0]
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
    receipt, = run.source_receipts
    assert not run._root.exists()
    assert run.retention_failures == (["PermissionError"] if kind == "copy_fail" else [])
    if kind in ("symlink", "link_bytes", "fifo", "copy_fail"):
        assert "kept" not in receipt
        assert not [p for p in (tmp_path / "out/source_damage").glob("**/*") if not p.is_dir()]
    else:
        kept = tmp_path / "out" / receipt["kept"]
        assert kept.is_file() and not kept.is_symlink()
        if kind != "database":
            assert kept.read_bytes() == b"system replaced root"
        else:  # its WAL goes beside it, under the name SQLite looks for
            assert receipt["kept_sidecars"] == [receipt["kept"] + "-wal"]
            assert (tmp_path / "out" / receipt["kept_sidecars"][0]).is_file()
    if kind == "symlink":
        assert receipt["kind"] == "symlink" and receipt["link"] == os.path.relpath(outside, roots[0].parent)
        t2lite._scan(tmp_path / "out", [b"credential-needle"])
    if kind == "link_bytes":
        assert receipt["link"] == "missing-\\xff" and receipt["link_hex"] == b"missing-\xff".hex()
    diagnostic = json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes())
    assert diagnostic["attempts"][0]["source_receipts"] == run.source_receipts
    assert receipt["surface"] == "HERMES_HOME/."
    assert receipt["path"] == ("test.db" if kind == "database" else "bad-entry" if kind == "fifo" else ".")
    assert receipt["kind"] == (kind if kind in ("fifo", "symlink") else "symlink" if kind == "link_bytes" else "file")
    assert all(not Path(v).is_absolute() for v in receipt.values() for v in (v if isinstance(v, list) else [v])
               if isinstance(v, str))


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


def test_counts_every_attempt():
    def run(stopped, labels=(), incidental=0):
        return life.LifeRun("system", "life", "B0", 0, stopped=stopped,
                            infra_item_labels=labels, incidental_unknown_400=incidental)
    assert infrastructure_counts([
        run(("SYSTEM_FAILURE", "turn_timeout", 1), ("turn_timeout", "audit", "audit")),
        run(("INFRA_FAILURE", "checkpoint_busy", 1), ("audit",)),
        run(None, ("no_result", "no_result", "audit"), 2),
        run(("SYSTEM_FAILURE", "invalid_surface", 1)),
    ]) == {"system": {"turn_timeout": 1, "audit": 2, "checkpoint_busy": 1,
                     "no_result": 1, "incidental_unknown_400": 2}}


@pytest.mark.parametrize("arm,error", [("system", "fault"), ("system", "interrupt"), ("no_memory", "fault")])
def test_damage_during_exception(lives, unit_sessions, tmp_path, monkeypatch, arm, error):  # noqa: F811
    original, run, indices = adapter.HermesAdapter.run_session, units.run_life, []

    def session(self, index, **kw):
        result = original(self, index, **kw)
        if not indices:
            indices.append(index)
            os.mkfifo(self.paths["hermes_home"] / "bad-entry")
            raise KeyboardInterrupt() if error == "interrupt" else adapter.HarnessFailed("director_stopped")
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    monkeypatch.setattr(units, "run_life", lambda **kw: run(**(kw | dict(arm=arm))))
    if error == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            unit(lives["t1-g1", "B0"], tmp_path)
        return
    result = unit(lives["t1-g1", "B0"], tmp_path)
    first = result.runs[0]
    assert not first.restore_failures
    if arm == "no_memory":
        assert result.attempts == 2 and not first.source_receipts
        assert first.stopped == ("INFRA_FAILURE", "director_stopped", indices[0])
    else:
        assert result.attempts == 1
        assert first.stopped == ("SYSTEM_FAILURE", "invalid_surface", indices[0])
        assert first.superseded_causes == ["director_stopped"]
        diagnostic = json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes())
        assert diagnostic["attempts"][0]["superseded_causes"] == ["director_stopped"]
        assert infrastructure_counts(result.runs) == {"system": {}}


@pytest.mark.parametrize("replacement", [b"", b"another format", "schema"])
def test_non_damage_database_replacement(tmp_path, replacement):
    path = tmp_path / "test.db"
    if replacement != "schema":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE t(x)")
    baseline = SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, tmp_path)], [])
    if replacement == "schema":
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE t(x)")
            db.execute("PRAGMA writable_schema=ON")
            db.execute("UPDATE sqlite_master SET sql='CREATE TABLE t(x BOGUS() )' WHERE name='t'")
        with pytest.raises(sqlite3.DatabaseError, match="^malformed database schema"):
            with sqlite3.connect(path) as db:
                db.execute("PRAGMA quick_check")
    else:
        path.write_bytes(replacement)
    assert baseline.receipt() is None


def test_output_scan_does_not_follow_links(tmp_path):
    target, out = tmp_path / "outside", tmp_path / "out"
    target.write_bytes(b"credential-needle")
    out.mkdir()
    (out / "link").symlink_to(target)
    t2lite._scan(out, [b"credential-needle"])
    with pytest.raises(t2lite.t1.T1Refused, match="credential_scan"):
        t2lite._scan(out, [os.fsencode(target)])  # link text itself is scanned
    (out / "regular").write_bytes(target.read_bytes())
    with pytest.raises(t2lite.t1.T1Refused, match="credential_scan"):
        t2lite._scan(out, [b"credential-needle"])


def surface(path):
    return SourceBaseline([({"root": "HERMES_HOME", "relative": "."}, path)], [])


def valid_db(path):
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE t(x)")
    db.commit()
    db.close()


def test_receipt_names_that_are_not_utf8(tmp_path):
    baseline = surface(tmp_path)
    try:
        os.mkfifo(os.fsencode(tmp_path) + b"/bad-\xff")
    except OSError as error:
        if error.errno != errno.EILSEQ:
            raise
        pytest.skip("this filesystem refuses names that are not UTF-8")
    receipt = baseline.receipt()
    assert receipt["path"] == "bad-\\xff" and receipt["path_hex"] == b"bad-\xff".hex()
    canon({k: v for k, v in receipt.items() if not k.startswith("_")})  # writes as UTF-8 JSON


def test_harness_temp_name_gives_no_cover(tmp_path):
    # The harness writes its config through a regular temporary file, which no rule charges.
    baseline = surface(tmp_path)
    os.mkfifo(tmp_path / ".config.yaml.bad")
    receipt = baseline.receipt()
    assert (receipt["path"], receipt["kind"]) == (".config.yaml.bad", "fifo")


def test_special_sidecar_is_not_opened(tmp_path):
    valid_db(tmp_path / "test.db")
    baseline = surface(tmp_path)
    journal = tmp_path / "test.db-journal"
    os.mkfifo(journal)
    found = []
    worker = threading.Thread(target=lambda: found.append(baseline.receipt()), daemon=True)
    worker.start()
    worker.join(10)
    try:
        assert not worker.is_alive(), "the checker opened the database through its FIFO journal"
    finally:
        if worker.is_alive():  # release the blocked open so the thread can end
            os.close(os.open(journal, os.O_WRONLY | os.O_NONBLOCK))
            worker.join(10)
    receipt, = found
    assert (receipt["path"], receipt["kind"]) == ("test.db-journal", "fifo")


def test_kill_residue_is_not_charged(tmp_path, monkeypatch):
    valid_db(tmp_path / "test.db")
    baseline = surface(tmp_path)
    os.mkfifo(tmp_path / "ipc.fifo")
    monkeypatch.chdir(tmp_path)  # a short relative name, within the socket path limit
    with socket.socket(socket.AF_UNIX) as server:
        server.bind("ipc.sock")
    assert baseline.receipt(after_kill=True) is None
    assert baseline.receipt()["path"] == "ipc.fifo"
    (tmp_path / "test.db").write_bytes(b"SQLite format 3\x00" + b"broken" * 100)
    assert baseline.receipt(after_kill=True)["rule"] == "sqlite_malformed"  # a kill cannot leave this


@pytest.mark.parametrize("kind", ["fifo", "socket"])
def test_root_replaced_by_kill_residue(tmp_path, monkeypatch, kind):
    root = tmp_path / "s"
    root.mkdir()
    baseline = surface(root)
    root.rmdir()
    if kind == "fifo":
        os.mkfifo(root)
    else:
        monkeypatch.chdir(tmp_path)  # a short relative name, within the socket path limit
        with socket.socket(socket.AF_UNIX) as server:
            server.bind("s")
    assert baseline.receipt(after_kill=True) is None  # judged as the same entry inside the root would be
    receipt = baseline.receipt()
    assert (receipt["rule"], receipt["kind"], receipt["label"]) == ("not_a_directory", kind, "invalid_surface")


def test_earlier_infrastructure_voids_a_damaged_attempt(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    """Damage never causes a rerun, but an infrastructure item earlier in the same attempt voids that attempt.

    The contract records an infrastructure item only after two reruns (score/classes.py), and a rerun replays the
    whole unit, as for every system failure; the voided attempt's receipt stays in the unit diagnostics."""
    original = units.run_life
    receipt = dict(surface="HERMES_HOME/.", path="state.db", rule="sqlite_malformed", kind="file",
                   label="invalid_store")

    def run(**kw):
        found = original(**kw)
        if kw["attempt"] == 0:
            first, *rest = [i["item_id"] for i in kw["items"]]
            return replace(found, stopped=("SYSTEM_FAILURE", "invalid_store", 1), source_receipts=[dict(receipt)],
                classes={first: ("INFRA_FAILURE", "shadow_error"),
                         **{iid: ("SYSTEM_FAILURE", "invalid_store") for iid in rest}})
        return found

    monkeypatch.setattr(units, "run_life", run)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2 and result.stop is None
    assert all(scored["failure_class"] != "SYSTEM_FAILURE" for scored in result.scores.values())
    assert json.loads((tmp_path / "out/unit_diagnostics.json").read_bytes()) == dict(attempts=[
        dict(attempt=0, stopped=["SYSTEM_FAILURE", "invalid_store", 1], incidental_unknown_400=0,
             infra_item_labels=["shadow_error"], source_receipts=[receipt]),
        dict(attempt=1, stopped=None, incidental_unknown_400=0)])


def test_residue_after_harness_kill_redoes_unit(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    original, fired = adapter.HermesAdapter.run_session, []

    def stalled(self, index, **kw):
        result = original(self, index, **kw)
        if not fired:
            fired.append(True)
            os.mkfifo(self.paths["hermes_home"] / "ipc.fifo")  # left by the worker the harness now kills
            self.after_kill = True  # as a spawn with no clean end leaves it (tests/harness/test_turn_wait.py)
            raise adapter.HarnessFailed("drain_timeout")
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", stalled)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2
    first = result.runs[0]
    assert first.stopped[:2] == ("INFRA_FAILURE", "drain_timeout") and not first.source_receipts


def test_without_source_checks_no_source_is_watched(lives, unit_sessions, tmp_path, monkeypatch):  # noqa: F811
    # T1's call leaves run_life's default, which watches no source: T1 keeps no evidence (runner/t1.py).
    built, run, real = [], units.run_life, life.SourceBaseline

    def record(surfaces, excluded):
        built.append(list(surfaces))
        return real(surfaces, excluded)

    monkeypatch.setattr(life, "SourceBaseline", record)
    monkeypatch.setattr(units, "run_life", lambda **kw: run(**{k: v for k, v in kw.items() if k != "source_checks"}))
    unit(lives["t1-g1", "B0"], tmp_path)
    assert built and not any(built)
