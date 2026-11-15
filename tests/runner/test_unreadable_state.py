"""Reader-made unreadable G1 workspaces are scored, with no socket or live model."""

import errno
import json
import os
import stat
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

import pytest
import test_probe_live as helpers
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.contracts.surfaces import tree_hash, tree_listing
from bicentennial.genres.g1_software.diffs import PATHS, read_state, render
from bicentennial.harness.hermes import adapter
from bicentennial.items.checks.repo import RepoCheck, repo_state_predicates
from bicentennial.runner import input_reads, life, t2, t2lite, units
from bicentennial.runner.diagnostics import Diagnostics
from bicentennial.runner.hermes_score import (
    MISSING,
    Infra,
    score_item,
    unreadable_counts,
)
from bicentennial.runner.lock import SessionGate, build_lock
from bicentennial.score.action import Trace, score_action

lives = helpers.lives
harness = helpers.harness
unit_sessions = helpers.unit_sessions
completed_sessions = helpers.HELPERS["completed_sessions"]


def act_probe(case):
    items = {i["item_id"]: i for i in case["items"]}
    return next(p for p in case["compiled"].probes if items[p.item_ids[0]]["stage"] == "act")


def damage_probe(monkeypatch, case, damage, *, session_index=None):
    probe, original, visited = act_probe(case), adapter.HermesAdapter.run_session, []

    def session(self, index, **kw):
        result = original(self, index, **kw)
        visited.append(index)
        if index == (probe.index if session_index is None else session_index):
            if callable(damage):
                damage(self.paths["workspace"])
                return result
            path = self.paths["workspace"] / "docs/decisions.md"
            if damage == "blank":
                path.write_text(path.read_text().replace("# Decisions\n", "# Decisions\n\n", 1))
            elif damage == "deleted":
                path.unlink()
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    return probe, visited


def unit(case, tmp_path, *, arm="system", diagnostics=None):
    entry = helpers.ENTRY
    pins = build_lock(**json.loads((helpers.ROOT /
        "tests/fixtures/run/contracts.json").read_bytes())["contracts"]["lock"])
    ctx = SimpleNamespace(entry=entry, run_id="unreadable-unit", gate=SessionGate(pins),
        current_lock=lambda: pins, harness_pin=dict(entry["artifact"]), hermes=None,
        plugin_source=None, worker_argv=["unused-in-process-worker"], model_cache=None, turn_wait_s=1.0)
    pack = SimpleNamespace(life=case["t"].life, life_dir=case["t"].out_dir, genre="G1",
        items={"B0": case["items"]}, records_b={"B0": case["records"]}, keys=case["keys"],
        cases=case["cases"], visible={}, meta={"honeypot_token": None},
        scoring={"evidence": {i["item_id"]: [] for i in case["items"]}})
    return units._unit_attempts(ctx, pack, "B0", arm, tmp_path / "attempts",
        units._Guard(helpers.FakeLive()), [], tmp_path / "out", diagnostics=diagnostics)


def expected(case):
    return score_action(case.item, case.table, Trace(False, True, case.t_sim),
        {name: False for name in case.checks}, window=case.window)


@pytest.mark.parametrize("kind", ["file", "directory_link", "dangling_link", "self_link", "non_utf8_link"])
def test_live_workspace_root_replaced_scores_empty_and_restores(
        lives, unit_sessions, tmp_path, monkeypatch, kind):
    case = lives["t1-g1", "B0"]
    clean = unit(case, tmp_path / "clean")
    assert not (tmp_path / "clean/out/unit_diagnostics.json").exists()
    assert not getattr(clean.runs[0], "workspace_receipts", [])
    probe = act_probe(case)
    swap, read = life.swap_in, life.read_input
    originals, restored, reads, damaged = [], [], [], []
    target = tmp_path / "link-target"
    target.mkdir()
    for p, data in render({p: {} for p in PATHS.values()}).items():
        (target / p).parent.mkdir(parents=True, exist_ok=True)
        (target / p).write_bytes(data)
    target_info, target_hash = target.stat(), tree_hash(tree_listing(target, []))

    @contextmanager
    def watch(clone, canonical):
        selected = canonical.name == "workspace" and clone.parent.name == str(probe.index)
        if selected:
            info = canonical.lstat()
            originals.append((info.st_dev, info.st_ino, tree_hash(tree_listing(canonical, []))))
        with swap(clone, canonical):
            yield
        if selected:
            info = canonical.lstat()
            assert stat.S_ISDIR(info.st_mode)
            restored.append((info.st_dev, info.st_ino, tree_hash(tree_listing(canonical, []))))
            assert not os.path.lexists(canonical.parent / "absent-target")
            assert not os.path.lexists(canonical.parent / os.fsdecode(b"absent-\xff"))
            damaged.clear()

    def replace_root(workspace):
        workspace.rename(tmp_path / "discarded-reader-clone")
        damaged.append(workspace)
        if kind == "file":
            workspace.write_text("reader replacement")
        elif kind == "non_utf8_link":
            os.symlink(b"absent-\xff", os.fsencode(workspace))
        else:
            workspace.symlink_to(target if kind == "directory_link" else
                                 "absent-target" if kind == "dangling_link" else workspace.name)

    def record_read(workspace, *args):
        if workspace in damaged:
            reads.append(args[0])
        return read(workspace, *args)

    monkeypatch.setattr(life, "swap_in", watch)
    monkeypatch.setattr(life, "read_input", record_read)
    _, visited = damage_probe(monkeypatch, case, replace_root)
    result = unit(case, tmp_path / "broken")
    assert result.attempts == 1 and result.stop is None  # base reruns after the failed root restore
    run, = result.runs
    assert not reads  # base follows directory links and tries every input under other replacements
    assert restored == originals and len(restored) == 1
    assert visited == [s["index"] for s in case["compiled"].script["sessions"]]
    assert run.item_labels == {iid: "unreadable_state" for iid in probe.item_ids}
    failed = tuple((p, "workspace_replaced") for p in sorted(PATHS.values()))
    assert run.unreadable_paths == {iid: failed for iid in probe.item_ids}
    for iid, row in result.scores.items():
        assert not isinstance(row, Infra) and row["infra_reruns"] == 0
        if iid in probe.item_ids:
            assert run.act[iid] == {}
            scored = expected(case["cases"][iid])
            assert row["failure_class"] == scored.failure_class
            assert row["score_milli"] == row["worst_case_milli"] == scored.score_milli
        else:
            assert row == clean.scores[iid]
    receipt = dict(session=probe.index, kind="file" if kind == "file" else "symlink")
    if kind == "non_utf8_link":
        receipt.update(target="absent-\\xff", target_hex=b"absent-\xff".hex())
    elif kind != "file":
        receipt["target"] = str(target) if kind == "directory_link" else (
            "absent-target" if kind == "dangling_link" else "workspace")
    assert run.workspace_receipts == [receipt]
    assert json.loads(canon(run.workspace_receipts)) == [receipt]
    diagnostics = json.loads((tmp_path / "broken/out/unit_diagnostics.json").read_bytes())
    assert diagnostics["attempts"][0]["workspace_receipts"] == [receipt]
    assert not run.restore_failures and not run._root.exists()  # moved entry removed with the attempt
    assert (target.stat().st_dev, target.stat().st_ino) == (target_info.st_dev, target_info.st_ino)
    assert tree_hash(tree_listing(target, [])) == target_hash


def test_replaced_root_keeps_act_state_collision(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]

    def collide(workspace):
        (workspace.parent.parent / "act-state").mkdir()
        workspace.rename(tmp_path / "discarded-clone")
        workspace.write_text("reader replacement")

    probe, _ = damage_probe(monkeypatch, case, collide)
    result = unit(case, tmp_path)
    assert result.attempts == 1
    run, = result.runs
    assert run.stopped == ("SYSTEM_FAILURE", "act_state_collision", probe.index)
    assert not run.item_labels
    assert all(result.scores[iid]["failure_class"] == "SYSTEM_FAILURE" and
               result.scores[iid]["infra_reruns"] == 0 for iid in probe.item_ids)


def test_control_diagnostics_skip_replaced_workspace(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    diag = Diagnostics(tmp_path / "diag", tmp_path / "synthetic-home")
    monkeypatch.setattr(diag, "_needles", lambda: ())

    def replace_root(workspace):
        workspace.rename(tmp_path / "discarded-clone")
        workspace.write_text("reader replacement")

    probe, _ = damage_probe(monkeypatch, case, replace_root)
    result = unit(case, tmp_path, arm="no_memory", diagnostics=diag)
    assert result.attempts == 1 and result.stop is None
    for iid in probe.item_ids:
        top = f"{case['t'].life}/B0/0/{iid}/workspace"
        assert dict(path=top, reason="workspace replaced") in diag.skips
        assert not (diag.root / top).exists()
        assert not any(p.startswith(top + "/") for p in diag.files)
    assert not diag.failures


@pytest.mark.parametrize("fault", ["occupied", "rename"])
def test_workspace_move_fault_redoes_without_deleting(lives, unit_sessions, tmp_path, monkeypatch, fault):
    case, entries, errors = lives["t1-g1", "B0"], [], []
    clean = unit(case, tmp_path / "clean")
    move, rename = life.move_workspace_replacement, Path.rename

    def replace_root(workspace):
        if not entries:
            workspace.rename(tmp_path / "discarded-clone")
            workspace.write_text("reader replacement")
            entries.append((workspace, workspace.stat().st_ino))

    def fail_rename(path, target):
        if entries and path == entries[0][0] and Path(target).name == "workspace-replaced":
            raise OSError("injected rename failure")
        return rename(path, target)

    def checked_move(workspace, folder, receipts, session):
        if not entries or workspace != entries[0][0]:
            return move(workspace, folder, receipts, session)
        parked = folder / "workspace-replaced"
        if fault == "occupied":
            parked.write_text("existing parking entry")
            inode = parked.stat().st_ino
        with pytest.raises(FileExistsError if fault == "occupied" else OSError) as error:
            move(workspace, folder, receipts, session)
        errors.append(type(error.value).__name__)
        assert workspace.stat().st_ino == entries[0][1]
        assert workspace.read_text() == "reader replacement" and not receipts
        if fault == "occupied":
            assert parked.stat().st_ino == inode and parked.read_text() == "existing parking entry"
        else:
            assert not os.path.lexists(parked)
        raise error.value

    damage_probe(monkeypatch, case, replace_root)
    monkeypatch.setattr(life, "move_workspace_replacement", checked_move)
    if fault == "rename":
        monkeypatch.setattr(Path, "rename", fail_rename)
    monkeypatch.setattr(life.LifeRun, "cleanup", lambda self: None)
    result = unit(case, tmp_path / "broken")
    assert errors == ["FileExistsError" if fault == "occupied" else "OSError"]
    assert result.attempts == 2 and result.stop is None
    first, redo = result.runs
    assert first.stopped[0] == "INFRA_FAILURE" and redo.stopped is None
    assert not first.workspace_receipts and not first.source_receipts
    assert result.scores == {iid: dict(row, infra_reruns=1) for iid, row in clean.scores.items()}
    assert entries[0][0].stat().st_ino == entries[0][1]


@pytest.mark.parametrize("fault", ["restore", "before_session", "observation"])
def test_workspace_harness_fault_still_redoes_unit(lives, unit_sessions, tmp_path, monkeypatch, fault):
    case, failed, armed = lives["t1-g1", "B0"], [], []
    probe = act_probe(case)
    swap, clone_tree, lstat = life.swap_in, life.clone_tree, Path.lstat

    @contextmanager
    def broken_restore(clone, canonical):
        with swap(clone, canonical):
            yield
        if canonical.name == "workspace" and clone.parent.name == str(probe.index) and not failed:
            assert stat.S_ISDIR(canonical.lstat().st_mode)
            failed.append(True)
            raise OSError("injected directory restore fault")

    def broken_baseline(canonical, clone):
        if canonical.name == "workspace" and clone.parent.name == str(probe.index) and not failed:
            canonical.rename(canonical.with_name("before-session-original"))
            canonical.write_text("harness replacement before session")
            failed.append(True)
        return clone_tree(canonical, clone)

    def broken_observation(path, *args, **kwargs):
        if path in armed and not failed:
            failed.append(True)
            raise PermissionError("injected workspace observation fault")
        return lstat(path, *args, **kwargs)

    if fault == "restore":
        monkeypatch.setattr(life, "swap_in", broken_restore)
    elif fault == "before_session":
        monkeypatch.setattr(life, "clone_tree", broken_baseline)
    else:
        damage_probe(monkeypatch, case, armed.append)
        monkeypatch.setattr(Path, "lstat", broken_observation)
    result = unit(case, tmp_path)
    assert failed and result.attempts == 2
    first, redo = result.runs
    assert first.stopped[:2] == ("INFRA_FAILURE", {
        "restore": "OSError", "before_session": "ValueError", "observation": "PermissionError"}[fault])
    assert not first.item_labels and not getattr(first, "workspace_receipts", [])
    assert redo.stopped is None and not getattr(redo, "workspace_receipts", [])
    assert first.restore_failures == (["OSError"] if fault == "restore" else [])
    assert all(row["infra_reruns"] == 1 for row in result.scores.values())


def test_workspace_replacement_is_moved_even_on_session_error(lives, unit_sessions, tmp_path, monkeypatch):
    case, workspace = lives["t1-g1", "B0"], []
    probe = act_probe(case)

    def replace_then_fail(path):
        path.rename(tmp_path / "discarded-clone")
        path.symlink_to("absent-target")
        workspace.append(path)
        raise adapter.HarnessFailed("turn_failed")

    damage_probe(monkeypatch, case, replace_then_fail)
    monkeypatch.setattr(life.LifeRun, "cleanup", lambda self: None)
    result = unit(case, tmp_path)
    assert result.attempts == 1  # base's restore fault supersedes the session failure and reruns
    run, = result.runs
    assert run.stopped == ("SYSTEM_FAILURE", "turn_failed", probe.index)
    assert not run.restore_failures
    assert run.workspace_receipts == [dict(session=probe.index, kind="symlink", target="absent-target")]
    assert stat.S_ISDIR(workspace[0].lstat().st_mode)


@pytest.mark.parametrize("damage", ["blank", "deleted"])
def test_live_unreadable_scores_once_and_keeps_other_items(lives, unit_sessions, tmp_path, monkeypatch, damage):
    case = lives["t1-g1", "B0"]
    clean = unit(case, tmp_path / "clean")
    assert all("unreadable_paths" not in row for row in clean.probes)
    probe, visited = damage_probe(monkeypatch, case, damage)
    result = unit(case, tmp_path / "broken")
    assert result.attempts == 1 and result.stop is None
    assert visited == [s["index"] for s in case["compiled"].script["sessions"]]
    run, = result.runs
    assert run.item_labels == {iid: "unreadable_state" for iid in probe.item_ids}
    assert {p["item_id"] for p in result.probes if p.get("label") == "unreadable_state"} == set(probe.item_ids)
    reason = "missing" if damage == "deleted" else "malformed"
    assert all(row["unreadable_paths"] == [["docs/decisions.md", reason]]
               for row in result.probes if row.get("label") == "unreadable_state")
    for iid, row in result.scores.items():
        assert not isinstance(row, Infra)
        assert row["infra_reruns"] == 0
        if iid in probe.item_ids:
            assert set(run.act[iid]) == set(PATHS.values()) - {"docs/decisions.md"}
            c = case["cases"][iid]
            scored = score_action(c.item, c.table, Trace(False, True, c.t_sim),
                                  repo_state_predicates(run.act[iid], c.checks), window=c.window)
            assert row["failure_class"] == scored.failure_class
            assert row["score_milli"] == row["worst_case_milli"] == scored.score_milli <= 0
        else:
            assert row == clean.scores[iid]


@pytest.mark.parametrize("damage,reason", [("file_mode", "permission"), ("dir_mode", "permission"),
    ("dir_exec_mode", "permission"), ("root_mode", "permission"), ("link", "symlink_loop"), ("dir_link", "symlink_loop"), ("fifo", "not_regular"),
    ("link_locked", "symlink_target")])
def test_live_input_damage_scores_partial_once(lives, unit_sessions, tmp_path, monkeypatch, damage, reason):
    case, locked, guards, released = lives["t1-g1", "B0"], [], [], []
    done = Event()

    def break_input(workspace):
        path = workspace / "docs/decisions.md"
        if damage.endswith("mode"):
            path = (workspace if damage == "root_mode" else
                    workspace / "config" if damage in ("dir_mode", "dir_exec_mode") else path)
            locked.append(path)
            # dir_exec_mode keeps the owner's read and removes only execute: the folder can be listed, not entered.
            path.chmod(0o600 if damage == "dir_exec_mode" else 0)
        elif damage == "link_locked":  # a new link into a folder the reader locked, outside the workspace
            target = tmp_path / "locked-target"
            target.mkdir()
            (target / "decisions.md").write_text("# Decisions\n")
            target.chmod(0)
            locked.append(target)
            path.unlink()
            path.symlink_to(target / "decisions.md")
        else:
            if damage == "dir_link":
                path.unlink()
                path = path.parent
                path.rmdir()
            else:
                path.unlink()
            if damage in ("link", "dir_link"):
                path.symlink_to(path.name)
            else:
                os.mkfifo(path)
                # A second name for this FIFO that nothing else touches: the harness later moves the clone aside and
                # restores the original file at the input's path (#564's review).
                handle = tmp_path / "fifo-handle"
                os.link(path, handle)

                def release_regression():
                    # While anything holds the FIFO open for reading, through any name, a non-blocking writer's open
                    # succeeds (with no reader it fails with ENXIO); closing that writer ends a regressed blocking open
                    # or read.
                    while not done.wait(0.05):
                        try:
                            fd = os.open(handle, os.O_WRONLY | os.O_NONBLOCK)
                        except OSError:
                            continue
                        released.append(True)
                        os.close(fd)

                thread = Thread(target=release_regression)
                thread.start()
                guards.append(thread)

    probe, _ = damage_probe(monkeypatch, case, break_input)
    try:
        result = unit(case, tmp_path)
        assert result.attempts == 1 and result.stop is None  # base reruns permission/loop faults
        run, = result.runs
        failed = sorted(p for p in PATHS.values() if damage == "root_mode" or
                        (p.startswith("config/") if damage in ("dir_mode", "dir_exec_mode") else
                         p.startswith("docs/") if damage == "dir_link" else p == "docs/decisions.md"))
        assert run.item_labels == {iid: "unreadable_state" for iid in probe.item_ids}
        for iid in probe.item_ids:
            assert set(run.act[iid]) == set(PATHS.values()) - set(failed)
            assert run.unreadable_paths[iid] == tuple((p, reason) for p in failed)
        assert {row["item_id"] for row in result.probes if "unreadable_paths" in row} == set(probe.item_ids)
        assert all(row["unreadable_paths"] == [[p, reason] for p in failed]
                   for row in result.probes if row["item_id"] in probe.item_ids)
        assert not released  # base opens the FIFO and needs the guard to finish
    finally:
        done.set()
        for thread in guards:
            thread.join()
        for path in locked:
            if path.exists():
                path.chmod(0o700 if path.is_dir() else 0o600)


def test_live_locked_directory_off_the_input_paths_still_cleans_up(lives, unit_sessions, tmp_path, monkeypatch):
    case, locked = lives["t1-g1", "B0"], []

    def lock_extra(workspace):
        extra = workspace / "extra" / "locked"
        extra.mkdir(parents=True)
        (extra / "kept.txt").write_text("a file the reader keeps")
        extra.chmod(0)
        locked.append(extra)

    damage_probe(monkeypatch, case, lock_extra)
    try:
        result = unit(case, tmp_path)  # base: the attempt's cleanup raises PermissionError on the locked folder
        assert result.attempts == 1 and result.stop is None
        run, = result.runs
        assert not run.item_labels and not run.unreadable_paths
        assert run._root is not None and not run._root.exists()
    finally:
        for path in locked:
            if path.exists():
                path.chmod(0o700)


@pytest.mark.parametrize("fault", ["permission", "loop", "eperm_link"])
def test_live_unchanged_raw_read_fault_redoes_unit(lives, unit_sessions, tmp_path, monkeypatch, fault):
    read, armed, failed = input_reads._read_regular, [], []

    def arm(workspace):
        armed.append(workspace)
        if fault == "eperm_link":  # a harmless new link: its target is a readable copy of the input
            path = workspace / "docs/decisions.md"
            copy = tmp_path / f"decisions-{len(armed)}.md"
            copy.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(copy)

    damage_probe(monkeypatch, lives["t1-g1", "B0"], arm)

    def read_regular(target):
        if armed and target == armed[-1] / "docs/decisions.md" and not failed:
            failed.append(target)
            if fault == "loop":
                raise OSError(errno.ELOOP, "loop")
            # EPERM is a sandbox's or the system's refusal, not a mode the reader removed (#564's review)
            raise PermissionError(errno.EPERM if fault == "eperm_link" else errno.EACCES, "injected raw read fault")
        return read(target)

    monkeypatch.setattr(input_reads, "_read_regular", read_regular)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2
    first, redo = result.runs
    assert first.stopped[:2] == ("INFRA_FAILURE", "OSError" if fault == "loop" else "PermissionError")
    assert redo.stopped is None and not first.item_labels and not redo.item_labels
    assert all(row["infra_reruns"] == 1 for row in result.scores.values())



def test_input_behind_a_baseline_link_is_never_charged(tmp_path):
    # The probe listing records a link's target, not what lies behind it: a FIFO there was not shown to be new.
    workspace, outside = tmp_path / "w", tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    os.mkfifo(outside / "decisions.md")
    (workspace / "docs").symlink_to(outside)
    baseline = {"docs": {"kind": "symlink", "target": str(outside)}}
    with pytest.raises(OSError) as caught:
        input_reads.read_input(workspace, "docs/decisions.md", baseline, set())
    assert caught.value.errno == errno.EINVAL
    # The same FIFO where the listing had the file itself is the reader's replacement.
    (workspace / "docs").unlink()
    (workspace / "docs").mkdir()
    os.mkfifo(workspace / "docs/decisions.md")
    assert input_reads.read_input(workspace, "docs/decisions.md", {"docs/decisions.md": {"kind": "file", "mode": 0o644}},
                                  set()) == (None, "not_regular")


def test_folder_read_bit_alone_is_not_the_cause(tmp_path, monkeypatch):
    # Opening a known path needs search (execute) on its folders; their read bit only lists them. So when a folder lost
    # only owner read, a denied open came from elsewhere (an LSM, an ACL, the harness) and stays infrastructure.
    workspace = tmp_path / "w"
    (workspace / "config").mkdir(parents=True)
    (workspace / "config/flags.toml").write_text("a = 1\n")
    baseline = {"config": {"kind": "dir", "mode": 0o755}, "config/flags.toml": {"kind": "file", "mode": 0o644}}

    def denied(target):
        raise PermissionError(errno.EACCES, "denied by a policy, not a mode")

    monkeypatch.setattr(input_reads, "_read_regular", denied)
    repairs = set()
    try:
        (workspace / "config").chmod(0o300)  # read removed, write and search kept
        with pytest.raises(PermissionError):
            input_reads.read_input(workspace, "config/flags.toml", baseline, repairs)
        assert not repairs
        (workspace / "config").chmod(0o600)  # search removed: this alone denies the open, so it is the reader's
        assert input_reads.read_input(workspace, "config/flags.toml", baseline, repairs) == (None, "permission")
        assert repairs == {workspace / "config"}
    finally:
        (workspace / "config").chmod(0o755)


def test_read_regular_never_blocks_on_or_reads_a_fifo(tmp_path):
    # The race backstop: an input replaced by a FIFO after the first stat is opened without blocking and never read.
    path, result = tmp_path / "decisions.md", []
    os.mkfifo(path)
    thread = Thread(target=lambda: result.append(input_reads._read_regular(path)))
    thread.start()
    thread.join(5)
    blocked = thread.is_alive()
    if blocked:  # release a regressed blocking open before failing
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        thread.join()
    assert not blocked
    (data, mode), = result
    assert data is None and stat.S_ISFIFO(mode)

def test_live_harness_read_fault_still_reruns(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    read, calls = life.read_state, []

    def fault(root):
        calls.append(root)
        if len(calls) == 1:
            raise RuntimeError("synthetic harness read fault")
        return read(root)

    monkeypatch.setattr(life, "read_state", fault)
    result = unit(case, tmp_path)
    assert result.attempts == 2
    first, redo = result.runs
    assert first.stopped[:2] == ("INFRA_FAILURE", "RuntimeError")
    assert not first.item_labels and not redo.item_labels
    assert redo.stopped is None
    assert all(row["infra_reruns"] == 1 for row in result.scores.values())


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
@pytest.mark.parametrize("earlier", [False, True])
@pytest.mark.parametrize("incidental", [False, True])
def test_live_act_state_collision_scores_once(lives, unit_sessions, tmp_path, monkeypatch, kind, earlier, incidental):
    case = lives["t1-g1", "B0"]
    entries = []

    def collide(workspace):
        # workspace = <attempt>/B0/run/workspace; the fixed scratch folder is beside run.
        path = workspace.parent.parent / "act-state"
        if kind == "directory":
            path.mkdir()
            (path / "sentinel").write_text("reader entry")
        elif kind == "file":
            path.write_text("reader entry")
        else:
            path.symlink_to("missing-reader-target")
        entries.append((path, path.lstat().st_ino))

    probe = act_probe(case)
    prior = next(p.index for p in case["compiled"].probes if p.index < probe.index)
    damage_probe(monkeypatch, case, collide, session_index=prior if earlier else probe.index)
    records = adapter.HermesAdapter.records

    def rows(self):
        found = records(self)
        current = next((r for r in reversed(found) if (r.get("cursor") or {}).get("session") == probe.index), None)
        if incidental and current:
            row = dict(current, seq=max(r["seq"] for r in found) + 1, cursor=None, role="unknown", status=400,
                subrole="", served="refused_unknown", served_by="scripted", upstream=[])
            validate("ledger-record", row)
            return [*found, row]
        return found

    monkeypatch.setattr(adapter.HermesAdapter, "records", rows)
    # The production unit releases its entire attempt after scoring; keep this test's evidence to inspect it.
    monkeypatch.setattr(life.LifeRun, "cleanup", lambda self: None)
    result = unit(case, tmp_path)
    assert result.attempts == 1
    run, = result.runs
    assert run.stopped == ("SYSTEM_FAILURE", "act_state_collision", probe.index)
    attempt_id = next(r["attempt_id"] for r in run.records if (r.get("cursor") or {}).get("session") == probe.index)
    assert life._probe_code(run.records, attempt_id, probe_live=True) == ("unknown_400" if incidental else None)
    assert run.incidental_unknown_400 == int(incidental)
    diagnostics = tmp_path / "out/unit_diagnostics.json"
    if incidental:
        assert json.loads(diagnostics.read_bytes()) == dict(attempts=[dict(
            attempt=0, stopped=list(run.stopped), incidental_unknown_400=1)])
    else:  # a unit with no incidental row writes no diagnostics file, so its output bytes are unchanged
        assert not diagnostics.exists()
    for iid in probe.item_ids:
        assert run.classes[iid] == ("SYSTEM_FAILURE", "act_state_collision")
        assert result.scores[iid]["failure_class"] == "SYSTEM_FAILURE"
        assert result.scores[iid]["infra_reruns"] == 0
    assert all(run.classes[iid] == ("SYSTEM_FAILURE", "act_state_collision")
               for iid in run.classes if iid not in run.results)
    (path, inode), = entries
    assert path.lstat().st_ino == inode
    if kind == "directory":
        assert stat.S_ISDIR(path.lstat().st_mode)
        assert (path / "sentinel").read_text() == "reader entry"
    elif kind == "file":
        assert path.read_text() == "reader entry"
    else:
        assert stat.S_ISLNK(path.lstat().st_mode) and os.readlink(path) == "missing-reader-target"


@pytest.mark.parametrize("fault", [False, True])
def test_act_state_entry_from_a_failed_session_stays_the_readers(lives, unit_sessions, tmp_path, monkeypatch, fault):
    """A QA session makes the entry, then fails with a probe code and the life continues: the act session's collision
    is still the reader's. An observation fault at that failure claims nothing and keeps the session's own code."""
    case = lives["t1-g1", "B0"]
    probe = act_probe(case)
    prior = next(p for p in case["compiled"].probes if p.index < probe.index)
    original, records, absent = adapter.HermesAdapter.run_session, adapter.HermesAdapter.records, life._act_state_absent
    failing = []

    def session(self, index, **kw):
        result = original(self, index, **kw)
        if index == prior.index:
            (self.paths["workspace"].parent.parent / "act-state").mkdir()
            failing.append(fault)
            raise adapter.HarnessFailed("turn_failed")
        return result

    def observe(root):
        if failing and failing.pop():
            raise PermissionError("injected observation fault")
        return absent(root)

    def rows(self):
        found = records(self)
        current = next((r for r in reversed(found) if (r.get("cursor") or {}).get("session") == prior.index), None)
        if current is None:
            return found
        row = dict(current, seq=max(r["seq"] for r in found) + 1, role="unknown", status=400, subrole="",
            served="refused_unknown", served_by="scripted", upstream=[], cursor=dict(session=prior.index, turn=1))
        validate("ledger-record", row)
        return [*found, row]

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    monkeypatch.setattr(adapter.HermesAdapter, "records", rows)
    monkeypatch.setattr(life, "_act_state_absent", observe)
    result = unit(case, tmp_path)
    assert result.attempts == 3  # the earlier session's own code redoes the unit, so the third attempt is scored
    run = result.runs[-1]
    assert all(run.classes[iid] == ("INFRA_FAILURE", "unknown_400") for iid in prior.item_ids)
    if fault:  # the fault stays in the failing session: the life continues and the act read finds the entry
        assert run.stopped == ("INFRA_FAILURE", "FileExistsError", probe.index)
    else:
        assert run.stopped == ("SYSTEM_FAILURE", "act_state_collision", probe.index)
    # An infrastructure failure on the third attempt is scored BLOCKED (score/classes.py).
    assert all(result.scores[iid]["failure_class"] == ("BLOCKED" if fault else "SYSTEM_FAILURE")
               for iid in probe.item_ids)


def test_act_state_present_before_reader_still_reruns(lives, unit_sessions, tmp_path, monkeypatch):
    case, entries = lives["t1-g1", "B0"], []
    original = adapter.HermesAdapter.__init__

    def construct(self, *args, **kwargs):
        original(self, *args, **kwargs)
        if not entries:
            path = self.paths["root"].parent / "act-state"
            path.mkdir()
            entries.append((path, path.lstat().st_ino))

    monkeypatch.setattr(adapter.HermesAdapter, "__init__", construct)
    monkeypatch.setattr(life.LifeRun, "cleanup", lambda self: None)
    result = unit(case, tmp_path)
    assert result.attempts == 2
    first, redo = result.runs
    assert first.stopped[:2] == ("INFRA_FAILURE", "FileExistsError")
    assert redo.stopped is None
    assert entries[0][0].lstat().st_ino == entries[0][1]
    assert all(row["infra_reruns"] == 1 for row in result.scores.values())


@pytest.mark.parametrize("fault", ["cleanup", "observation"])
def test_act_state_harness_fault_still_reruns(lives, unit_sessions, tmp_path, monkeypatch, fault):
    original = life.shutil.rmtree if fault == "cleanup" else Path.lstat
    failed = []

    def fail(path, *args, **kwargs):
        if Path(path).name == "act-state" and not failed:
            failed.append(path)
            raise PermissionError("synthetic harness fault")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(life.shutil if fault == "cleanup" else Path,
                        "rmtree" if fault == "cleanup" else "lstat", fail)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == 2
    assert result.runs[0].stopped[:2] == ("INFRA_FAILURE", "PermissionError")
    assert result.runs[1].stopped is None
    assert all(row["infra_reruns"] == 1 for row in result.scores.values())


@pytest.mark.parametrize("foreign", [False, True])
def test_unknown_probe_row_session_and_redo(lives, unit_sessions, tmp_path, monkeypatch, foreign):
    records = adapter.HermesAdapter.records

    def rows(self):
        found = records(self)
        current = next((r for r in reversed(found) if r.get("role") == "probe_main"), None)
        if current and self.paths["root"].parents[1].name == "0":
            row = dict(current, seq=max(r["seq"] for r in found) + 1, role="unknown", status=400,
                subrole="", served="refused_unknown", served_by="scripted", upstream=[],
                cursor=dict(session=current["cursor"]["session"] + 1, turn=1) if foreign else None)
            validate("ledger-record", row)
            return [*found, row]
        return found

    monkeypatch.setattr(adapter.HermesAdapter, "records", rows)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == (1 if foreign else 2)
    assert all(row["infra_reruns"] == (0 if foreign else 1) for row in result.scores.values())
    assert all(run.incidental_unknown_400 == 0 for run in result.runs)
    if not foreign:
        assert ("INFRA_FAILURE", "unknown_400") in result.runs[0].classes.values()


@pytest.mark.parametrize("plugin,phase,reply,attempts,label", [
    (True, "open", "not-json", 1, "worker_protocol"),
    (True, "open", '{"ok": false}', 1, "worker_protocol"),
    (True, "open", '{"ok": false, "session_id": null, "history": null, "alive_threads": []}', 3, "open_failed"),
    (True, "startup", "not-json", 3, "JSONDecodeError"),
    (False, "open", "not-json", 3, "JSONDecodeError"),
])
def test_worker_protocol_life_class_and_reruns(lives, tmp_path, monkeypatch, plugin, phase, reply, attempts, label):
    helpers.HELPERS["offline_life_adapter"](monkeypatch)
    init, popen = adapter.HermesAdapter.__init__, adapter.subprocess.Popen
    fake = Path(__file__).parents[1] / "harness/fake_line_worker.py"

    def construct(self, *args, **kwargs):
        # A fake configured provider, selected before spawning, with the real configuration and worker path.
        kwargs["plugin"] = "holographic" if plugin else None
        kwargs["worker_argv"] = [sys.executable, str(fake), phase, reply]
        init(self, *args, **kwargs)
        self.egress.add = self.egress.discard = lambda *args: None

    def spawn(argv, *args, **kwargs):
        if argv[0] == "nice" and str(fake) in argv:
            argv = argv[argv.index(sys.executable):]
        return popen(argv, *args, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "__init__", construct)
    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    monkeypatch.setattr(adapter.HermesAdapter, "_gate", lambda *args: None)
    # The offline sampler has no sampler thread or fork lock; the real session still starts its director.
    original_start = adapter.HermesAdapter.run_session

    def session(self, *args, **kwargs):
        self.egress.forking = nullcontext()
        return original_start(self, *args, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    result = unit(lives["t1-g1", "B0"], tmp_path)
    assert result.attempts == attempts
    cls = "SYSTEM_FAILURE" if attempts == 1 else "INFRA_FAILURE"
    assert [run.stopped[:2] for run in result.runs] == [(cls, label)] * attempts
    assert all(set(run.classes.values()) == {(cls, label)} for run in result.runs)
    if attempts == 1:
        assert all(row["failure_class"] == cls and row["infra_reruns"] == 0 for row in result.scores.values())


@pytest.mark.parametrize("damage", ["blank", "deleted"])
def test_scripted_unreadable_keeps_infrastructure_class(lives, completed_sessions, tmp_path, monkeypatch, damage):
    helpers.HELPERS["offline_life_adapter"](monkeypatch)
    case = lives["t1-g1", "B0"]
    probe, _ = damage_probe(monkeypatch, case, damage)
    result = helpers.drive(case, tmp_path)
    assert result.stopped == ("INFRA_FAILURE", "ValueError", probe.index)
    assert not result.item_labels
    assert all(result.classes[iid] == ("INFRA_FAILURE", "ValueError") for iid in probe.item_ids)


@pytest.mark.parametrize("error", [ValueError, FileNotFoundError, IsADirectoryError, NotADirectoryError,
                                   UnicodeDecodeError, PermissionError, RuntimeError])
def test_live_read_exception_boundary(lives, unit_sessions, tmp_path, monkeypatch, error):
    def fault(root):
        if error is UnicodeDecodeError:
            raise error("utf-8", b"\xff", 0, 1, "invalid byte")
        raise error("synthetic state read failure")

    monkeypatch.setattr(life, "read_state", fault)
    result = helpers.drive(lives["t1-g1", "B0"], tmp_path, live=helpers.FakeLive())
    if error in (PermissionError, RuntimeError):
        assert result.stopped[:2] == ("INFRA_FAILURE", error.__name__)
        assert not result.item_labels
    else:
        assert result.stopped is None and result.item_labels
        assert all(result.act[iid] == {} for iid in result.item_labels)


def test_empty_state_uses_each_items_changed_matches_neither_row(lives):
    case = lives["t1-g1", "B0"]
    for item in case["items"]:
        if item["stage"] != "act":
            continue
        iid = item["item_id"]
        reader = SimpleNamespace(selected_option=None, competing_present=(), carry_over=False,
                                 in_context=True, kind="act")
        row = score_item(item, cls=None, label=None, result=reader, envelope=MISSING,
            act={}, case=case["cases"][iid], scoring_evidence=None, keys=case["keys"][iid],
            stored_roots=None, retained_roots=None, attempt=0)
        scored = expected(case["cases"][iid])
        assert not isinstance(row, Infra)
        assert row["failure_class"] == scored.failure_class
        assert row["score_milli"] == row["worst_case_milli"] == scored.score_milli
        assert row["selected_option"] is None and row["competing_present"] == []
        validate("item_outcome", row)


@pytest.mark.parametrize("write,broken,verdict,score,split", [
    ("stale", "other", "FAIL_MEMORY", -1000, False),
    ("right", "other", "PASS", 1000, False),
    ("benign", "other", "PASS", 0, False),
    ("right", "checked", "FAIL_TASK", 0, False),
    ("right", "all", "FAIL_TASK", 0, False),
    # The admissible checks' file is broken and the stale write sits on another file that parses.
    ("stale", "checked", "FAIL_MEMORY", -1000, True),
])
def test_live_partial_state_scores_surviving_files(lives, unit_sessions, tmp_path, monkeypatch,
                                                  write, broken, verdict, score, split):
    case = dict(lives["t1-g1", "B0"])
    probe = act_probe(case)
    target = next(case["cases"][iid] for iid in probe.item_ids
                  if case["cases"][iid].table["gold"] == "act")
    # Retarget a real sealed template's checks to flags for the cross-file regression; with split, the
    # disqualifiers' checks go to settings instead, so they read from a different file than the admissible ones.
    disqualifying = {row["predicate"] for row in target.table["disqualifiers"]}

    def path_for(name):
        return "config/settings.toml" if split and name in disqualifying else "config/flags.toml"

    checks = {name: tuple(tuple(replace(c, path=path_for(name)) for c in group) for group in groups)
              for name, groups in target.checks.items()}
    table = dict(target.table, benign_extras=["holds:extra"])
    checks["holds:extra"] = ((RepoCheck(kind="constant", path="service/routes.toml",
                                      name="benign", value="extra"),),)
    target = replace(target, checks=checks, table=table)
    case["cases"] = dict(case["cases"], **{target.item["item_id"]: target})
    predicate = (target.table["disqualifiers"][0]["predicate"] if write == "stale"
                 else target.table["admissible"][0])
    written = {}

    def damage(workspace):
        state = read_state(workspace)
        for check in checks[predicate][0]:
            state[check.path][check.name] = check.value
        if write == "benign":
            state["service/routes.toml"]["benign"] = "extra"
        for p, data in render(state).items():
            (workspace / p).write_bytes(data)
        bad = (set(PATHS.values()) if broken == "all" else
               {"config/flags.toml"} if broken == "checked" else {"docs/decisions.md"})
        for p in bad:
            (workspace / p).write_bytes(b"\n" if p.endswith(".md") else b"invalid = [\n")
        written.update({p: entries for p, entries in state.items() if p not in bad})

    damage_probe(monkeypatch, case, damage)
    result = unit(case, tmp_path)
    assert result.attempts == 1 and result.stop is None
    run, = result.runs
    assert run.item_labels == {iid: "unreadable_state" for iid in probe.item_ids}
    assert unreadable_counts(result.runs) == {"system": len(probe.item_ids)}
    iid = target.item["item_id"]
    assert run.act[iid] == written
    row = result.scores[iid]
    assert row["base_verdict"] == verdict
    assert row["score_milli"] == row["worst_case_milli"] == score
    assert row["benign_extra"] is (write == "benign")
    assert row["infra_reruns"] == 0


@pytest.mark.parametrize("path", sorted(PATHS.values()))
def test_live_any_file_harness_fault_is_infrastructure(lives, unit_sessions, tmp_path, monkeypatch, path):
    read, calls = life.read_state, []

    def fault(root):
        current = sorted(PATHS.values())[len(calls)]
        calls.append(current)
        if current == path:
            raise PermissionError("synthetic harness permission fault")
        if len(calls) == 1:
            raise ValueError("reader-made malformed file before harness fault")
        return read(root)

    monkeypatch.setattr(life, "read_state", fault)
    run = helpers.drive(lives["t1-g1", "B0"], tmp_path, live=helpers.FakeLive())
    assert run.stopped[:2] == ("INFRA_FAILURE", "PermissionError")
    assert not run.item_labels and not run.act
    assert unreadable_counts([run]) == {"system": 0}


@pytest.mark.parametrize("tier", ["t2", "t2lite"])
def test_unreadable_disclosure_counts_by_arm(tier, request, monkeypatch):
    state = request.getfixturevalue("t2_scenario" if tier == "t2" else "scenario")
    original = units.run_life

    def labelled(**kw):
        # B0's labelled item has a reader result, so the real scorer would reach its act path; B1's has none, so it
        # would be scored Infra("no_result") and is not counted. The fake scorer here ignores the result.
        run, iid = original(**kw), kw["items"][0]["item_id"]
        reader = SimpleNamespace(selected_option=None, competing_present=(), carry_over=False, in_context=True)
        results = {**run.results, iid: reader} if kw["branch"] == "B0" else run.results
        return replace(run, item_labels={iid: "unreadable_state"}, results=results)

    monkeypatch.setattr(units, "run_life", labelled)
    assert state.invoke() == 0
    runner = t2 if tier == "t2" else t2lite
    assert runner._read(state.out, "disclosures.json")["unreadable_state"] == {"system": 2, "no_memory": 2}


def test_developer_docs_name_label_and_rule():
    for name in ("t2", "t2lite"):
        text = (helpers.ROOT / f"docs/developers/{name}.md").read_text()
        assert "unreadable_state" in text
        assert "never rerun" in text
    assert "no empty lines" in (helpers.ROOT / "docs/genres/G1-software-partner.md").read_text()


def test_unreadable_counts_only_the_scored_attempt():
    def run(arm, life_name, branch, attempt, labelled, cls=None, audit="OK", result=True):
        return life.LifeRun(arm, life_name, branch, attempt, results={"i": object()} if result else {},
                            item_labels={"i": "unreadable_state"} if labelled else {},
                            classes={"i": cls} if cls else {}, audit={"status": audit})

    runs = [run("system", "L1", "B0", 0, True), run("system", "L1", "B0", 1, False),  # voided, then its redo
            run("system", "L1", "B1", 0, True),  # scored
            run("no_memory", "L1", "B0", 0, True), run("no_memory", "L1", "B0", 0, True),  # two repetitions
            run("system", "L2", "B0", 0, True, ("INFRA_FAILURE", "x")),  # classed, so not scored as unreadable
            run("system", "L3", "B0", 2, True, audit="INFRA_FAILURE"),  # a final attempt whose audit failed
            run("system", "L4", "B0", 2, True, result=False)]  # no reader result: scored as Infra("no_result")
    assert unreadable_counts(runs) == {"no_memory": 2, "system": 1}
    # T2-lite --only publishes only the kept system items, and the whole floor.
    assert unreadable_counts(runs, keep={"other"}) == {"no_memory": 2, "system": 0}
    assert unreadable_counts([]) == {}


@pytest.mark.parametrize("partial", [{"config/flags.toml": {"flag": "stale"}}, {}])
def test_diagnostics_writes_partial_state(tmp_path, monkeypatch, partial):
    diag = Diagnostics(tmp_path / "diag", tmp_path / "home")
    puts = []
    monkeypatch.setattr(diag, "_needles", lambda: ())
    monkeypatch.setattr(diag, "_workspace", lambda rel, run, session: puts.append(rel + "/workspace"))
    run = SimpleNamespace(act={"i1": partial}, item_labels={"i1": "unreadable_state"}, records=())
    diag._item("L/B0/0/i1", {"item_id": "i1", "stage": "act"}, run, None, None, 3, 1, {}, None)
    assert json.loads((diag.root / "L/B0/0/i1/act.json").read_bytes()) == partial
    assert "L/B0/0/i1/workspace" in puts
    assert diag.skips == []
    assert diag.failures == []


def _wrapped(cause):
    try:
        try:
            raise cause
        except BaseException as error:
            raise ValueError("missing or malformed repository file") from error
    except ValueError as error:
        return error


@pytest.mark.parametrize("error, reader", [
    (ValueError("invalid decisions entry"), True),
    (_wrapped(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")), True),
    (_wrapped(FileNotFoundError(2, "gone")), True),
    (_wrapped(IsADirectoryError(21, "a directory")), True),
    (_wrapped(NotADirectoryError(20, "not a directory")), True),
    (RecursionError("maximum recursion depth exceeded"), True),
    (FileNotFoundError(2, "gone"), True),
    (_wrapped(OSError(24, "Too many open files")), False),
    (_wrapped(OSError(5, "Input/output error")), False),
    (_wrapped(PermissionError(13, "Permission denied")), False),
])
def test_reader_made_separates_reader_edits_from_harness_faults(error, reader):
    assert life.reader_made(error) is reader


def test_reader_made_on_the_real_parser(tmp_path, monkeypatch):
    from bicentennial.genres.g1_software.diffs import PATHS, read_state

    first = tmp_path / sorted(PATHS.values())[0]
    first.parent.mkdir(parents=True)
    first.mkdir()  # a file replaced by a directory
    with pytest.raises(ValueError) as caught:
        read_state(tmp_path)
    assert life.reader_made(caught.value)
    first.rmdir()
    first.write_text("a = " + "[" * 5000 + "]" * 5000 + "\n")  # nesting deep enough to exhaust the parser
    with pytest.raises((ValueError, RecursionError)) as caught:
        read_state(tmp_path)
    assert life.reader_made(caught.value)

    def exhausted(self, *args, **kwargs):
        raise OSError(24, "Too many open files")

    monkeypatch.setattr(type(first), "read_text", exhausted)
    with pytest.raises(ValueError) as caught:
        read_state(tmp_path)
    assert not life.reader_made(caught.value)
