"""Kept index bytes depend on unit identity rather than completion order."""

import json
from dataclasses import replace

from bicentennial.items.protocol import CANARY
from bicentennial.runner import kept
from bicentennial.runner.life import LifeRun

PINS = {key + "_sha256": "a" * 64 for key in ("controls", "reader", "scoring", "scorer")}


def captured(root, life, branch):
    records = {}
    for iid in ("z", "a"):
        directory = root / life / branch / iid
        surface = directory / "surfaces/0"
        surface.mkdir(parents=True)
        (surface / "state").write_bytes(b"pre-probe")
        fields = dict(surface_hashes={"HERMES_HOME/.": "b" * 64}, workspace_hash="b" * 64,
                      environment_hash="b" * 64, sim_t_s=10, probe_session_index=11, probe_slot=0,
                      route_table_sha256="b" * 64, probe_config_sha256="b" * 64,
                      replay_context={key: "b" * 64 for key in (
                          "canonical_paths", "director_bindings", "attempt_identity", "resolved_route",
                          "replay_segment", "clock_cadence", "compiled_probe", "workspace_inputs",
                          "environment_inputs")})
        records[iid] = kept.PreProbe(directory, (surface,), 5, fields)
    return LifeRun("system", life, branch, 0, pre_probe=records)


def test_kept_index_identical_in_both_unit_orders(tmp_path):
    outputs = []
    for n, identities in enumerate([[("z", "B1"), ("a", "B0")], [("a", "B0"), ("z", "B1")]]):
        root = tmp_path / str(n)
        out = root / "out"
        for life, branch in identities:
            run = captured(root / "attempt", life, branch)
            scores = [dict(item_id=iid, score_milli=0, failure_class="SYSTEM_FAILURE") for iid in run.pre_probe]
            # Include an unreached miss as well as both captured failed items.
            run = replace(run, stopped=("SYSTEM_FAILURE", "turn_failed", 11))
            scores.append(dict(item_id="unreached", score_milli=0, failure_class="SYSTEM_FAILURE"))
            kept.keep_failed(run, scores, out, pack_hash="c" * 64, pins=PINS, canary=CANARY)
            for iid in run.pre_probe:
                assert (out / "kept" / life / branch / iid / "surfaces/0/state").read_bytes() == b"pre-probe"
        outputs.append((out / "kept/index.json").read_bytes())
    assert outputs[0] == outputs[1]
    rows = json.loads(outputs[0])
    assert [(r["life"], r["branch"], r["item_id"]) for r in rows] == [
        (life, branch, iid) for life, branch in [("a", "B0"), ("z", "B1")]
        for iid in ("a", "unreached", "z")]
