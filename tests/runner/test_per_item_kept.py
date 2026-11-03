"""Opt-in item isolation, pre-session evidence, and bounded failure retention."""

import json
import runpy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import sha256_canon
from bicentennial.contracts.repro_bundle import check_repro_bundle
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.genres.g1_software.repo import workspace_hash
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.harness.hermes.plugin_host import SETTLE_THREADS
from bicentennial.probe.scripted_reader import failing_stage
from bicentennial.runner import kept
from bicentennial.runner.hermes_score import score_item
from bicentennial.sandbox.surfaces import install_hash
from bicentennial.systems.hermes_plugin import PluginCell
from bicentennial.systems.registry import REGISTRY, load

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_probe_live.py")))
lives = HELPERS["lives"]
harness = HELPERS["harness"]
unit_sessions = HELPERS["unit_sessions"]
drive = HELPERS["drive"]
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
PINS = {k + "_sha256": "a" * 64 for k in ("controls", "reader", "scoring", "scorer")}


@pytest.fixture
def observed(lives, unit_sessions, monkeypatch):
    case = lives["t1-g1", "B0"]
    seen, baseline = [], {}
    session = adapter.HermesAdapter.run_session

    def run_session(self, index, **kwargs):
        probe = next(s for s in self.script["sessions"] if s["index"] == index)["kind"] == "probe"
        home = self.paths["hermes_home"]
        if probe:
            assert not (home / "probe-written").exists(), "a preceding item's write reached this clone"
            seen.append(index)
            baseline[index] = dict(listing=tree_listing(home, []),
                digest=install_hash(home, self.volatile, self.server.port),
                workspace=workspace_hash(self.paths["workspace"]))
            (home / "probe-written").write_text("REQUIRED-PROBE-TOKEN")
        else:
            (home / "replay-state").write_text(str(index))
        return session(self, index, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)
    return case, seen, baseline


def run_observed(observed, tmp_path, **kwargs):
    case, seen, baseline = observed
    result = drive(case, tmp_path, probe_mode="per_item", keep_pre_probe=True,
                   live=HELPERS["FakeLive"](), **kwargs)
    assert result.stopped is None
    assert len(result.pre_probe) == len(case["items"]) == len(seen)
    return result


def test_per_item_pre_probe_hashes_bytes_and_context(observed, tmp_path):
    run = run_observed(observed, tmp_path)
    for iid, record in run.pre_probe.items():
        before = observed[2][record.fields["probe_session_index"]]
        assert record.fields["surface_hashes"] == {"HERMES_HOME/.": before["digest"]}
        assert record.fields["workspace_hash"] == before["workspace"]
        assert tree_listing(record.roots[0], []) == before["listing"]
        assert not (record.roots[0] / "probe-written").exists()
        assert (run.retained_roots[iid][0] / "probe-written").read_text() == "REQUIRED-PROBE-TOKEN"
        assert record.fields["probe_slot"] == 0
        inputs = {name: json.loads((record.directory / "context" / f"{digest}.json").read_bytes())
                  for name, digest in record.fields["replay_context"].items()}
        assert all(sha256_canon(inputs[k]) == v for k, v in record.fields["replay_context"].items())
        assert len(inputs["compiled_probe"]["turns"]) == 1
        assert inputs["clock_cadence"]["sim_t_s"] == record.fields["sim_t_s"]
        assert inputs["clock_cadence"]["step_s"] == 60
        assert inputs["attempt_identity"]["attempt_id"]
        assert inputs["resolved_route"]["segment"] == inputs["replay_segment"]["segment"]
        bindings = inputs["director_bindings"]
        assert sha256_canon(bindings["route_table"]) == record.fields["route_table_sha256"]
        assert sha256_canon(bindings["probe_config"]) == record.fields["probe_config_sha256"]
        assert (record.directory / "workspace").is_dir()
    print("largest_pre_probe_bytes", max(kept._bytes(p.directory) for p in run.pre_probe.values()))
    run.cleanup()


def test_per_item_probe_exit_does_not_unsettle_later_items(observed, tmp_path, monkeypatch):
    entry = load(REGISTRY / "holographic.toml")
    entry["settle"] = dict(kind="hook", bound_s=1)
    monkeypatch.setitem(SETTLE_THREADS, "holographic", ("synthetic-settle",))
    def install(self, *args, **kwargs):
        self.baseline = self._listing()
        return self.surface_hash()

    monkeypatch.setattr(PluginCell, "install", install)
    session = adapter.HermesAdapter.run_session
    calls = []
    settle = PluginCell.settle

    def settled(self):
        calls.append(self.adapter.last_session)
        return settle(self)

    def run_session(self, index, **kwargs):
        self.end_threads = ()
        result = session(self, index, **kwargs)
        self.last_session = index
        if result.kind == "probe":
            self.end_threads = ("synthetic-settle",)
        return result

    monkeypatch.setattr(PluginCell, "settle", settled)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)
    run = run_observed(observed, tmp_path, entry=entry)
    assert calls == sorted({i["probe_point"] for i in observed[0]["items"]})
    assert not run.classes
    run.cleanup()


@pytest.mark.parametrize("use_pre", [False, True])
def test_attribution_post_probe_retrieved_pre_probe_unknown(observed, tmp_path, use_pre):
    run = run_observed(observed, tmp_path, pre_probe_attribution=use_pre)
    iid, record = next(iter(run.pre_probe.items()))
    result, keys = SimpleNamespace(in_context=False), dict(required=["REQUIRED-PROBE-TOKEN"])
    pre = failing_stage(result, keys, failed=True, retained_roots=record.roots)
    post_roots = (run._root / "probe" / str(record.fields["probe_session_index"]) / "0",)
    post = failing_stage(result, keys, failed=True, retained_roots=post_roots)
    actual = failing_stage(result, keys, failed=True, retained_roots=run.retained_roots[iid])
    assert (pre, post) == ("unknown", "retrieved")
    assert actual == (pre if use_pre else post)
    run.cleanup()


def publish(run, scores, out, **kwargs):
    return kept.keep_failed(run, scores, out, canary=CANARY, pins=PINS, pack_hash="b" * 64, **kwargs)


def mixed_scores(run):
    ids = list(run.pre_probe)
    return [dict(item_id=iid, score_milli=1000 if n == 0 else 0,
                 failure_class="SYSTEM_FAILURE" if n == 2 else None) for n, iid in enumerate(ids)]


def test_failed_passed_crashed_and_excluded_kept(observed, tmp_path):
    run = run_observed(observed, tmp_path / "attempt")
    scores = mixed_scores(run)
    ids = [s["item_id"] for s in scores]
    out = tmp_path / "out"
    rows = publish(run, scores, out, excluded={ids[-1]})
    assert len(rows) == len(ids)
    for row in rows:
        target = out / "kept" / run.life / run.branch / row["item_id"]
        expected = row["item_id"] not in (ids[0], ids[-1])
        assert target.exists() is expected
        assert (row["bytes"] > 0) is expected
        if expected:
            bundle = json.loads((target / "bundle.json").read_bytes())
            check_repro_bundle(bundle)
            assert kept._bytes(target) == row["bytes"]
            assert not (target / "surfaces/0/probe-written").exists()
    assert json.loads((out / "kept/index.json").read_bytes()) == rows
    run.cleanup()
    assert (out / "kept" / run.life / run.branch / ids[2] / "bundle.json").is_file()


def test_cause_generated_crash_is_a_kept_miss(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    item = next(i for i in case["items"] if i["stage"] != "act")
    session = adapter.HermesAdapter.run_session

    def crash(self, index, **kwargs):
        if next(s for s in self.script["sessions"] if s["index"] == index)["kind"] == "probe":
            raise HarnessFailed("turn_failed")
        return session(self, index, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", crash)
    run = drive(case, tmp_path / "attempt", items=[item], probe_mode="per_item", keep_pre_probe=True)
    cls, label = run.classes[item["item_id"]]
    score = score_item(item, cls=cls, label=label, result=None, envelope=None, act=None, case=None,
                       scoring_evidence=None, keys=None, stored_roots=None, retained_roots=None, attempt=0)
    assert score["failure_class"] == "SYSTEM_FAILURE" and score["score_milli"] == 0
    rows = publish(run, [score], tmp_path / "out")
    assert rows[0]["bytes"] > 0
    run.cleanup()


def test_crash_keeps_reached_copies_and_marks_unreached(lives, unit_sessions, tmp_path, monkeypatch):
    case = lives["t1-g1", "B0"]
    items = case["items"]
    session = adapter.HermesAdapter.run_session

    def crash(self, index, **kwargs):
        if next(s for s in self.script["sessions"] if s["index"] == index)["kind"] == "probe":
            raise HarnessFailed("turn_failed")
        return session(self, index, **kwargs)

    monkeypatch.setattr(adapter.HermesAdapter, "run_session", crash)
    run = drive(case, tmp_path / "attempt", items=items, probe_mode="per_item", keep_pre_probe=True)
    assert run.stopped is not None and len(items) >= 3
    reached = set(run.pre_probe)
    assert len(reached) == 1
    # The crash stops the life, so every later item is a SYSTEM_FAILURE miss (scored 0) that no probe reached.
    assert all(run.classes[i["item_id"]] == ("SYSTEM_FAILURE", "turn_failed") for i in items)
    scores = [dict(item_id=i["item_id"], score_milli=0, failure_class="SYSTEM_FAILURE") for i in items]
    out = tmp_path / "out"
    rows = publish(run, scores, out)
    assert sorted(r["item_id"] for r in rows) == sorted(i["item_id"] for i in items)
    for row in rows:
        if row["item_id"] in reached:
            assert row["reached"] is True and row["bytes"] > 0
            assert (out / row["kept"] / "bundle.json").is_file()
        else:
            assert row == dict(life=run.life, branch=run.branch, item_id=row["item_id"], reached=False,
                               kept=None, bytes=0)
    assert json.loads((out / "kept/index.json").read_bytes()) == rows
    run.cleanup()


def test_capture_off_refuses(observed, tmp_path):
    run = run_observed(observed, tmp_path / "attempt")
    iid = next(iter(run.pre_probe))
    with pytest.raises(kept.KeptRefused, match="^pre_probe_missing$"):
        publish(replace(run, pre_probe=None), [dict(item_id=iid, score_milli=0, failure_class=None)], tmp_path / "out")
    assert not (tmp_path / "out").exists()
    run.cleanup()


def test_kept_cap_refuses_without_losing_copy(observed, tmp_path, monkeypatch):
    run = run_observed(observed, tmp_path / "attempt")
    monkeypatch.setattr(kept, "KEPT_CAP_BYTES", 1)
    with pytest.raises(kept.KeptRefused, match="^kept_cap$"):
        publish(run, mixed_scores(run), tmp_path / "out")
    assert all(p.directory.exists() for p in run.pre_probe.values())
    assert not list((tmp_path / "out").rglob("bundle.json"))
    run.cleanup()


@pytest.mark.parametrize("location", ["surface", "context"])
def test_credential_scan_removes_candidate(observed, tmp_path, location):
    run = run_observed(observed, tmp_path / "attempt")
    iid, record = next(iter(run.pre_probe.items()))
    path = record.roots[0] / "planted" if location == "surface" else record.directory / "context/planted"
    path.write_bytes(b"x" * ((1 << 20) - 3) + b"PLANTED-NEEDLE")
    with pytest.raises(kept.KeptRefused, match="^credential_scan$"):
        publish(run, [dict(item_id=iid, score_milli=0, failure_class=None)], tmp_path / "out",
                credential_needles=[b"PLANTED-NEEDLE"])
    assert not record.directory.exists()
    assert not list((tmp_path / "out").rglob("*"))
    run.cleanup()


def test_missing_snapshot_refuses(observed, tmp_path):
    run = run_observed(observed, tmp_path / "attempt")
    with pytest.raises(kept.KeptRefused, match="^pre_probe_missing$"):
        publish(run, [dict(item_id="unsent", score_milli=0, failure_class="SYSTEM_FAILURE")], tmp_path / "out")
    run.cleanup()


def test_pre_attribution_requires_copy(lives, tmp_path):
    with pytest.raises(ValueError, match="requires keep_pre_probe"):
        drive(lives["t1-g1", "B0"], tmp_path, pre_probe_attribution=True)


def test_ring0_opt_in_records_each_slot(lives, unit_sessions, tmp_path):
    case = lives["t1-g1", "B0"]
    run = drive(case, tmp_path, keep_pre_probe=True, live=HELPERS["FakeLive"]())
    assert run.stopped is None
    for probe in case["compiled"].probes:
        for slot, iid in enumerate(probe.item_ids):
            record = run.pre_probe[iid]
            assert record.fields["probe_slot"] == slot
            assert record.fields["probe_session_index"] == probe.index
    assert len({p.directory for p in run.pre_probe.values()}) == len(case["items"])
    run.cleanup()


def test_g2_pre_probe_environment_seed(lives, unit_sessions, tmp_path):
    case = lives["t1-g2", "B0"]
    item = next(i for i in case["items"] if i["stage"] != "act")
    run = drive(case, tmp_path, arm="no_memory", items=[item], probe_mode="per_item", keep_pre_probe=True)
    assert run.stopped is None
    record = run.pre_probe[item["item_id"]]
    digest = record.fields["replay_context"]["environment_inputs"]
    inputs = json.loads((record.directory / "context" / f"{digest}.json").read_bytes())
    assert inputs["seed"]["state"]
    assert record.fields["environment_hash"] == sha256_canon(inputs["seed"]["state"])
    assert inputs["envwire_root"]
    run.cleanup()


def test_cap_counts_previously_kept_units(observed, tmp_path, monkeypatch):
    from dataclasses import replace

    run = run_observed(observed, tmp_path / "attempt")
    iid = next(iter(run.pre_probe))
    score = [dict(item_id=iid, score_milli=0, failure_class=None)]
    publish(run, score, tmp_path / "out")
    observed[1].clear()
    second = run_observed(observed, tmp_path / "another")
    second = replace(second, branch="B1")
    existing = kept._bytes(tmp_path / "out/kept")
    monkeypatch.setattr(kept, "KEPT_CAP_BYTES", existing + 1)
    with pytest.raises(kept.KeptRefused, match="^kept_cap$"):
        publish(second, score, tmp_path / "out")
    assert (tmp_path / "out/kept" / run.life / "B0" / iid).is_dir()
    assert not (tmp_path / "out/kept" / run.life / "B1" / iid).exists()
    run.cleanup()
    second.cleanup()
