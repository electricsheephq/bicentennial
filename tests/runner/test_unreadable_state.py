"""Reader-made unreadable G1 workspaces are scored, with no socket or live model."""

import json
import os
import stat
import sys
from contextlib import nullcontext
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_probe_live as helpers
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.contracts.run import validate
from bicentennial.genres.g1_software.diffs import PATHS, read_state, render
from bicentennial.harness.hermes import adapter
from bicentennial.items.checks.repo import RepoCheck, repo_state_predicates
from bicentennial.runner import life, t2, t2lite, units
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


def unit(case, tmp_path):
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
    return units._unit_attempts(ctx, pack, "B0", "system", tmp_path / "attempts",
        units._Guard(helpers.FakeLive()), [], tmp_path / "out")


def expected(case):
    return score_action(case.item, case.table, Trace(False, True, case.t_sim),
        {name: False for name in case.checks}, window=case.window)


@pytest.mark.parametrize("damage", ["blank", "deleted"])
def test_live_unreadable_scores_once_and_keeps_other_items(lives, unit_sessions, tmp_path, monkeypatch, damage):
    case = lives["t1-g1", "B0"]
    clean = unit(case, tmp_path / "clean")
    probe, visited = damage_probe(monkeypatch, case, damage)
    result = unit(case, tmp_path / "broken")
    assert result.attempts == 1 and result.stop is None
    assert visited == [s["index"] for s in case["compiled"].script["sessions"]]
    run, = result.runs
    assert run.item_labels == {iid: "unreadable_state" for iid in probe.item_ids}
    assert {p["item_id"] for p in result.probes if p.get("label") == "unreadable_state"} == set(probe.item_ids)
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
    if fault:
        assert run.stopped[0] == "INFRA_FAILURE"
    else:
        assert run.stopped == ("SYSTEM_FAILURE", "act_state_collision", probe.index)
    assert all(result.scores[iid]["failure_class"] == ("INFRA_FAILURE" if fault else "SYSTEM_FAILURE")
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
