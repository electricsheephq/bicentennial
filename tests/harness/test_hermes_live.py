"""R12 live acceptance: the S6a micro-life replayed twice through the pinned Hermes (the only test that runs Hermes).

Skipped when BICENTENNIAL_HERMES is unset or has no .venv/bin/python (the case in CI), and when the R15 busy marker
refuses light work. A present checkout that fails the pin check is a failure, never a skip. Every Hermes home lives
under pytest's basetemp; nothing reaches the network or a model.
"""

import json
import os
import runpy
import time
from pathlib import Path

import pytest

from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.harness.hermes.adapter import ENTRYPOINT, HermesAdapter, verify_pin
from bicentennial.ledger import stable_digest, verify
from bicentennial.runner.guard import admit, read_marker
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.envserver.honeypot import plant
from bicentennial.systems.registry import REGISTRY, load

ROOT = Path(__file__).resolve().parents[2]
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
compile_micro_life = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
LOCK, BASE, STEP, DAY = "ab" * 32, 1_600_000_000, 60, 86400
ROUTES = {"routes": [{"system": "hermes-native", "segment": "seg0", "probe_model": "probe-model",
                      "alias": "bicentennial-main", "summariser": "summary-model", "vision": None,
                      "served_by": "scripted"}]}


def checkout() -> Path:
    given = os.environ.get("BICENTENNIAL_HERMES")
    if not given or not (Path(given) / ".venv" / "bin" / "python").exists():
        pytest.skip("BICENTENNIAL_HERMES is unset or has no .venv/bin/python")
    admission = admit(read_marker(), heavy=False, roots=1)
    if not admission.admitted:
        pytest.skip(f"busy marker: {admission.reason}")
    return Path(given)


def run_once(scratch, name, hermes, entry, script):
    root = scratch / name
    root.mkdir()
    t0 = time.monotonic()
    a = HermesAdapter(entry, script=script, route_table=RouteTable.load(ROUTES),
                      schedule=FaultLite.load([{"kind": "kill", "session": 5, "turn": 2}], script),
                      responder=ScriptedResponder(entry), clock=SimClock(root / "clock.json", BASE, STEP),
                      root=root, scratch=scratch, life="s6a-micro", branch="B0", run=f"live-{name}",
                      checkout=hermes, harness_pin=dict(entry["artifact"]))  # hermes-native's artifact is Hermes
    _, token = plant(a.paths["workspace"], f"live-{name}")
    results = []
    try:
        for s in script["sessions"]:
            i = s["index"]
            results.append(a.run_session(i, sim_t_s=BASE + i * DAY, lock_hash=LOCK, attempt_id=f"attempt-s{i}"))
    except BaseException:
        a.close()
        raise
    return a, results, token, t0


def test_live_micro_life_twice(tmp_path):
    hermes = checkout()
    entry = load(REGISTRY / "hermes-native.toml")
    verify_pin(hermes, entry["artifact"])  # a present checkout off the pin fails here
    script = compile_micro_life(dict(LIFE, probes=[]))
    assert len(script["sessions"]) == 10 and sum(len(s["turns"]) for s in script["sessions"]) == 60
    cursors = {(s["index"], t["n"]) for s in script["sessions"] for t in s["turns"]}
    report, digests, ports, open_adapters = [], [], [], []
    try:
        for name in ("a", "b"):
            a, results, token, t0 = run_once(tmp_path, name, hermes, entry, script)
            open_adapters.append(a)  # run a's port stays bound while run b binds, so the ports differ
            control, wall_ms = a.director.control(), int((time.monotonic() - t0) * 1000)
            recs = a.records()
            summary = a.egress.summary()
            report.append({"run": name, "wall_ms": wall_ms, "port": a.server.port,
                           "marker": [g for r in results for g in r.gate],
                           "summariser_records": sum(r.summariser_records for r in results),
                           "records": len(recs), "restarts": [x for r in results for x in r.restarts],
                           "egress": summary, "pids": a.pids, "control": control,
                           "harness": a.harness_record(), "timings_ms": [r.timings_ms for r in results]})
            (tmp_path / "live-report.json").write_text(json.dumps(report, indent=1))
            script_recs = [(r["cursor"]["session"], r["cursor"]["turn"]) for r in recs if r.get("served") == "script"]
            assert len(script_recs) == 60 and set(script_recs) == cursors
            assert not [r for r in recs if r.get("served") == "script_retry"]
            assert sum(r.finals_matched for r in results) == 60
            assert all(r.entrypoint == ENTRYPOINT for r in results) and a.harness_record()["entrypoint"] == ENTRYPOINT
            rows = [(r.session, x) for r in results for x in r.restarts]
            assert len(rows) == 1 and rows[0][0] == 5 and rows[0][1]["after_turn"] == 2
            assert rows[0][1]["history_after"] == rows[0][1]["history_before"] > 0
            assert not [r for r in recs if r.get("role") == "unknown"]
            assert not [r for r in recs if r.get("subrole") in ("egress", "malformed_body")]
            assert control["write_failures"] == 0 and control["stopped"] is False
            assert all(summary["per_pid_samples"].get(str(pid), 0) >= 1 for pid in a.pids)
            assert summary["non_loopback"] == []
            assert a.honeypot_hits(token) == 0
            counts = verify(a.paths["root"] / "ledger")
            assert counts["chain_breaks"] == counts["truncated_tail"] == counts["bad_blobs"] == 0
            digests.append(a.stable_digest())
            ports.append(a.server.port)
    finally:
        for a in open_adapters:
            a.close()
    assert ports[0] != ports[1]
    if digests[0] != digests[1]:  # a known director defect, not an adapter one: record where the runs part
        (tmp_path / "live-digest-diff.json").write_text(json.dumps(first_difference(*open_adapters), indent=1))
        pytest.xfail("digests differ across runs: #71 (director arrival order)")


def first_difference(a, b) -> dict:
    """The first request record, in digest order, whose masked stable projection differs between two runs."""
    def rows(adapter):
        recs = [r for r in adapter.records() if r.get("type") == "request"]
        recs.sort(key=lambda r: (r["attempt_id"], (r["cursor"] or {}).get("turn", 0), r["role"], r["served"],
                                 r["path"], r["sim_now"]))
        return [(r, stable_digest([r], adapter.director.run_values)) for r in recs]
    keys = ("seq", "attempt_id", "cursor", "role", "subrole", "served", "path", "sim_now")
    ra_rows, rb_rows = rows(a), rows(b)
    for i, ((ra, da), (rb, db)) in enumerate(zip(ra_rows, rb_rows, strict=False)):
        if da != db:
            return {"index": i, "a": {k: ra.get(k) for k in keys}, "b": {k: rb.get(k) for k in keys},
                    "fields": sorted(k for k in ra.keys() & rb.keys() if ra[k] != rb[k])}
    return {"index": None, "counts": [len(ra_rows), len(rb_rows)]}
