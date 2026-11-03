"""Item 1: checkpoint settledness belongs to replay's real store, never probe clones."""

import inspect
import runpy
import sys
from pathlib import Path

import pytest

from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.plugin_host import SETTLE_THREADS
from bicentennial.runner import life as runner
from bicentennial.systems.hermes_plugin import PluginCell
from bicentennial.systems.registry import REGISTRY, load

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_probe_live.py")))
lives = HELPERS["lives"]
harness = HELPERS["harness"]
unit_sessions = HELPERS["unit_sessions"]
drive = HELPERS["drive"]


def base_behaviour():
    """A monkeypatched copy of base's extra call; needs no repository history."""
    source = inspect.getsource(runner.run_life)
    anchor = "                            checkpoints.append(probe.checkpoint)\n"
    assert source.count(anchor) == 1
    source = source.replace(anchor, anchor + "                            settle_checkpoint(probe.checkpoint)\n")
    namespace = dict(vars(runner))
    exec(compile(source, "<base-settle-behaviour>", "exec"), namespace)
    return namespace["run_life"]


@pytest.fixture
def scenario(lives, unit_sessions, monkeypatch):
    case = lives["t1-g1", "B0"]
    probes = {p.index: p for p in case["compiled"].probes}
    checkpoint = case["compiled"].probes[0].checkpoint
    first = next(p.index for p in probes.values() if p.checkpoint == checkpoint)
    assert len([p for p in probes.values() if p.checkpoint == checkpoint]) >= 2
    calls, observed, exits = [], [], []
    state = dict(dirty_probe=True, dirty_replay=False)

    # Installation is a stand-in; the real PluginCell.settle and runner clone/swap logic remain in use.
    def install(self, *args, **kwargs):
        self.baseline = self._listing()
        return self.surface_hash()

    monkeypatch.setattr(PluginCell, "install", install)
    monkeypatch.setitem(SETTLE_THREADS, "holographic", ("synthetic-settle",))
    settle = PluginCell.settle

    def observe(self):
        result = settle(self)
        calls.append((self.adapter.last_session, result.reason))
        observed.append((self.adapter.paths["hermes_home"] / "settle-store").read_text())
        return result

    monkeypatch.setattr(PluginCell, "settle", observe)
    session = adapter.HermesAdapter.run_session

    def run_session(self, index, **kwargs):
        self.end_threads = None  # just as the real adapter clears its previous exit on entry
        store = self.paths["hermes_home"] / "settle-store"
        if index in probes:
            assert store.read_text() == f"replay-{probes[index].checkpoint}"
        result = session(self, index, **kwargs)
        # Writing inside a probe must be discarded by swap-back, before the next session.
        store.write_text(f"probe-{index}" if index in probes else f"replay-{index}")
        dirty = (state["dirty_probe"] and index == first) or (state["dirty_replay"] and index == checkpoint)
        self.end_threads = ("synthetic-settle",) if dirty else ()
        self.last_session = index
        exits.append((index, self.end_threads))
        return result

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)
    return dict(case=case, checkpoint=checkpoint, first=first, state=state,
                calls=calls, observed=observed, exits=exits)


def run(scenario, tmp_path, monkeypatch, *, kind="hook", behaviour=None):
    entry = load(REGISTRY / ("hermes-native.toml" if kind == "absent" else "holographic.toml"))
    if kind != "absent":
        entry["settle"] = dict(kind=kind, bound_s=1 if kind == "hook" else 0)
    function = behaviour or runner.run_life
    monkeypatch.setitem(drive.__globals__, "run_life", function)
    unsettled = []

    def trace(frame, event, arg):
        if frame.f_code is not function.__code__:
            return None
        if event == "return":
            unsettled.extend(frame.f_locals["unsettled"])
        return trace

    # Inspect the runner's internal record without adding a production evidence field for a test.
    previous = sys.gettrace()
    sys.settrace(trace)
    try:
        result = drive(scenario["case"], tmp_path, entry=entry, live=HELPERS["FakeLive"]())
    finally:
        sys.settrace(previous)
    assert result.stopped is None
    scores = HELPERS["scored"](scenario["case"], "t1-g1", result)
    for item in scenario["case"]["items"]:
        iid = item["item_id"]
        if iid in result.classes:
            cls, label = result.classes[iid]
            scores[iid] = HELPERS["score_item"](item, cls=cls, label=label, result=None, envelope=None,
                act=None, case=None, scoring_evidence=None, keys=None, stored_roots=None,
                retained_roots=None, attempt=0)
    return result, scores, unsettled


def test_item1_probe_exit_cannot_reclassify_checkpoint(scenario, tmp_path, monkeypatch):
    scenario["state"]["dirty_probe"] = False
    clean, clean_scores, _ = run(scenario, tmp_path / "clean", monkeypatch)
    scenario["calls"].clear()
    scenario["observed"].clear()
    scenario["state"]["dirty_probe"] = True
    result, scores, unsettled = run(scenario, tmp_path / "probe-exit", monkeypatch)
    checkpoints = sorted({p.checkpoint for p in scenario["case"]["compiled"].probes})
    assert result.classes == clean.classes == {}
    assert scores == clean_scores  # includes earlier QA answers and later action sessions
    assert unsettled == []
    assert scenario["calls"] == [(k, "drained") for k in checkpoints]
    assert scenario["observed"] == [f"replay-{k}" for k in checkpoints]
    assert (scenario["first"], ("synthetic-settle",)) in scenario["exits"]
    assert set(scores) == {i["item_id"] for i in scenario["case"]["items"]}


def test_item1_unsettled_replay_classes_every_item_once(scenario, tmp_path, monkeypatch):
    scenario["state"].update(dirty_probe=False, dirty_replay=True)
    result, scores, unsettled = run(scenario, tmp_path, monkeypatch)
    assert result.classes == {i["item_id"]: ("SYSTEM_FAILURE", "unsettled")
        for i in scenario["case"]["items"] if i["probe_point"] == scenario["checkpoint"]}
    assert unsettled == [scenario["checkpoint"]]
    assert all(scores[iid]["failure_class"] == "SYSTEM_FAILURE" and scores[iid]["score_milli"] == 0
               for iid in result.classes)
    assert scenario["calls"][0] == (scenario["checkpoint"], "cut_at_exit")
    assert len(result.results) == len(scenario["case"]["items"])


@pytest.mark.parametrize("kind", ["absent", "none"])
def test_item1_other_settle_kinds_match_base(scenario, tmp_path, monkeypatch, kind):
    changed, changed_scores, changed_unsettled = run(scenario, tmp_path / "changed", monkeypatch, kind=kind)
    base, base_scores, base_unsettled = run(scenario, tmp_path / "base", monkeypatch,
                                           kind=kind, behaviour=base_behaviour())
    assert changed.classes == base.classes == {}
    assert changed.envelopes == base.envelopes
    assert changed.results == base.results
    assert changed_scores == base_scores
    assert changed_unsettled == base_unsettled == []
