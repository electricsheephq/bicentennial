"""Reader-made unreadable G1 workspaces are scored, with no socket or live model."""

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest
import test_probe_live as helpers
from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.contracts.run import validate
from bicentennial.harness.hermes import adapter
from bicentennial.runner import life, t2, t2lite, units
from bicentennial.runner.diagnostics import Diagnostics
from bicentennial.runner.hermes_score import (
    MISSING,
    UNREADABLE,
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


def damage_probe(monkeypatch, case, damage):
    probe, original, visited = act_probe(case), adapter.HermesAdapter.run_session, []

    def session(self, index, **kw):
        result = original(self, index, **kw)
        visited.append(index)
        if index == probe.index:
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
            assert run.act[iid] is UNREADABLE
            scored = expected(case["cases"][iid])
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
        assert all(result.act[iid] is UNREADABLE for iid in result.item_labels)


def test_sentinel_uses_each_items_changed_matches_neither_row(lives):
    case = lives["t1-g1", "B0"]
    for item in case["items"]:
        if item["stage"] != "act":
            continue
        iid = item["item_id"]
        reader = SimpleNamespace(selected_option=None, competing_present=(), carry_over=False,
                                 in_context=True, kind="act")
        row = score_item(item, cls=None, label=None, result=reader, envelope=MISSING,
            act=UNREADABLE, case=case["cases"][iid], scoring_evidence=None, keys=case["keys"][iid],
            stored_roots=None, retained_roots=None, attempt=0)
        scored = expected(case["cases"][iid])
        assert not isinstance(row, Infra)
        assert row["failure_class"] == scored.failure_class
        assert row["score_milli"] == row["worst_case_milli"] == scored.score_milli
        assert row["selected_option"] is None and row["competing_present"] == []
        validate("item_outcome", row)


@pytest.mark.parametrize("tier", ["t2", "t2lite"])
def test_unreadable_disclosure_counts_by_arm(tier, request, monkeypatch):
    state = request.getfixturevalue("t2_scenario" if tier == "t2" else "scenario")
    original = units.run_life

    def labelled(**kw):
        run = original(**kw)
        return replace(run, item_labels={kw["items"][0]["item_id"]: "unreadable_state"}
                       if kw["branch"] == "B0" else {})

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
    def run(arm, life_name, branch, attempt, labelled, cls=None, audit="OK"):
        return life.LifeRun(arm, life_name, branch, attempt,
                            item_labels={"i": "unreadable_state"} if labelled else {},
                            classes={"i": cls} if cls else {}, audit={"status": audit})

    runs = [run("system", "L1", "B0", 0, True), run("system", "L1", "B0", 1, False),  # voided, then its redo
            run("system", "L1", "B1", 0, True),  # scored
            run("no_memory", "L1", "B0", 0, True), run("no_memory", "L1", "B0", 0, True),  # two repetitions
            run("system", "L2", "B0", 0, True, ("INFRA_FAILURE", "x")),  # classed, so not scored as unreadable
            run("system", "L3", "B0", 2, True, audit="INFRA_FAILURE")]  # a final attempt whose audit failed
    assert unreadable_counts(runs) == {"no_memory": 2, "system": 1}
    assert unreadable_counts([]) == {}


def test_diagnostics_skips_an_unreadable_state(tmp_path, monkeypatch):
    diag = Diagnostics(tmp_path / "diag", tmp_path / "home")
    puts = []
    monkeypatch.setattr(diag, "_put", lambda rel, make: puts.append(rel))
    monkeypatch.setattr(diag, "_workspace", lambda rel, run, session: puts.append(rel + "/workspace"))
    run = SimpleNamespace(act={"i1": UNREADABLE}, records=())
    diag._item("L/B0/0/i1", {"item_id": "i1", "stage": "act"}, run, None, None, 3, 1, {}, None)
    assert "L/B0/0/i1/act.json" not in puts and "L/B0/0/i1/workspace" in puts
    assert diag.skips == [dict(path="L/B0/0/i1/act.json", reason="unreadable state")]
    assert diag.failures == []
