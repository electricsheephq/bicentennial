"""E30 arrival accounting uses raw director evidence without listening sockets."""

import json
import runpy
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.contracts.run import validate
from bicentennial.director import core
from bicentennial.director.roles import MAIN_ROLES
from bicentennial.harness.hermes.adapter import HermesAdapter
from bicentennial.report.receipt import background_summary as summarize_background
from bicentennial.report.receipt import build_receipt

ROOT = Path(__file__).resolve().parents[2]


def background_summary(*args, **kwargs):
    return summarize_background(*args, **kwargs, main_roles=MAIN_ROLES)


def request(seq, t, turn=None, *, session="s1", quoted=None, role=None, subrole="cursor"):
    return dict(type="request", seq=seq, t=t, attempt_id=session, role=role or (
        "replay_main" if turn else "memory_write"), subrole=subrole,
        cursor=dict(session=1, turn=turn) if turn else None, quoted_turn=quoted)


@pytest.mark.parametrize("kind", ["replay", "probe"])
def test_quote_attribution_uses_director_blobs_and_arrival(tmp_path, monkeypatch, kind):
    shared = runpy.run_path(str(ROOT / "tests/director/test_core.py"))
    script = dict(shared["SCRIPT"], sessions=[dict(index=1, kind=kind, turns=[
        dict(n=n, kind=kind, user=f"scripted turn {n}", assistant="done", tool_calls=[])
        for n in (1, 2)])])
    d = shared["make"](tmp_path, shared["Fake"](), script=script)
    shared["start"](d, tmp_path)
    a = object.__new__(HermesAdapter)
    a.director, a.paths = d, {"root": tmp_path}
    a._receipt_sessions = {"attempt-s1": (1, d.session_sim_t_s, d.clock.step_s, d.ctx.cursor)}
    timestamp = [100]
    monkeypatch.setattr(core, "time", SimpleNamespace(time=lambda: timestamp[0] / 1000, monotonic=time.monotonic))

    class FakeWorker:
        def send(self, t, texts, status=200, **extra):
            timestamp[0] = t
            body = dict(model="bicentennial-main",
                tools=[dict(type="function", function=dict(name="terminal", parameters={}))],
                messages=[dict(role="user", content=s) for s in texts])
            body.update(extra)
            actual, _, _ = d.handle("POST", "/v1/chat/completions", {}, json.dumps(body).encode())
            assert actual == status

    worker = FakeWorker()
    marker = shared["SYN"]["hermes_background_review"]
    try:
        # A refused main request has a cursor but never advanced the director's reached-turn window.
        worker.send(50, ["scripted turn 1"], status=400, temperature=0.5)
        worker.send(60, ["scripted turn 1", "scripted turn 2", marker])
        worker.send(100, ["scripted turn 1"])
        worker.send(200, ["scripted turn 2"])
        worker.send(237, ["scripted turn 1", marker])
        worker.send(245, ["scripted turn 1", "scripted turn 2", marker])
        worker.send(250, [marker])  # sim_now is the clock fallback: not a quote of turn 2
        worker.send(190, ["scripted turn 1", marker])  # dispatch order differs from arrival order
        raw = a.records()
        attributed = a.background_records()
        assert a.records() == raw  # derived attribution never enters the ledger
        assert attributed[1]["quoted_turn"] == 1
        assert d.ctx.cursor == 2  # the matcher view did not mutate the live director
        assert [r.get("quoted_turn") for r in attributed[-4:]] == [1, 2, None, 1]
        summary = background_summary("system", [attributed])
        assert summary["late"] == dict(count=1, max_delay_ms=37)
        assert summary["unattributed"] == dict(count=1)
    finally:
        d.close()


def test_late_is_per_attempt_and_there_is_no_session_end_count():
    # An s1 request quoting turn 1 is late against s1's turn 2; an s2 request quoting turn 1 has no s2 turn 2 to be
    # late against and never borrows s1's. A request the next session records without a quote of its own turns (one
    # still in flight when the old worker was reaped) counts as unattributed.
    rows = [request(1, 100, 1), request(2, 200, 2), request(3, 260, quoted=1),
            request(4, 300, 1, session="s2"), request(5, 320, session="s2", quoted=1), request(6, 330, session="s2")]
    result = background_summary("system", [rows])
    assert result["late"] == dict(count=1, max_delay_ms=60)
    assert result["unattributed"] == dict(count=1)
    assert set(result) == {"arm", "late", "unattributed", "threads_at_turn_start"}


def test_independent_ledgers_and_unattributed_never_guess():
    rows = [request(1, 100, 1), request(2, 200, 2), request(3, 201)]
    other = [request(1, 50, 1, session="s2")]
    result = background_summary("system", [rows, other], [0, 2, 1, None])
    assert result["unattributed"] == dict(count=1)
    assert result["late"]["count"] == 0
    assert result["threads_at_turn_start"] == dict(count=2, max_alive=2)


def receipt():
    return build_receipt(run_status="COMPLETE", wall_start_ms=0, wall_end_ms=1,
        latency_ms=[], load_milli=[0, 0, 0], busy_marker_readings=[], tokens_by_role={},
        runtime_by_role={}, spend_micro_usd=0, store_growth_bytes=0, process_ids=[], ports=[],
        temporary_paths=[], raw_body_digest="0" * 64,
        background=[background_summary("system")], turn_wait_s=0.5)


@pytest.mark.parametrize("key", ["background", "turn_wait_s", "units"])
def test_new_receipt_keys_are_required(key):
    value = receipt()
    assert value["turn_wait_s"] == "0.5"
    del value[key]
    with pytest.raises(ValueError):
        validate("receipt", value)


@pytest.mark.parametrize("part", ["late", "unattributed", "threads_at_turn_start"])
def test_background_fields_are_closed_required_and_bounded(part):
    value = receipt()
    target = value["background"][0][part]
    target["extra"] = 0
    with pytest.raises(ValueError):
        validate("receipt", value)
    del target["extra"]
    del target["count"]
    with pytest.raises(ValueError):
        validate("receipt", value)
    target["count"] = -1
    with pytest.raises(ValueError):
        validate("receipt", value)


@pytest.mark.parametrize("key", ["life", "branch", "arm", "slot", "start_ms", "end_ms", "attempts"])
def test_unit_fields_are_required_and_closed(key):
    value = receipt()
    unit = dict(life="life", branch="B0", arm="system", slot=0, start_ms=0, end_ms=1, attempts=1)
    value["units"] = [unit]
    validate("receipt", value)
    old = unit.pop(key)
    with pytest.raises(ValueError):
        validate("receipt", value)
    unit[key] = old
    unit["extra"] = 1
    with pytest.raises(ValueError):
        validate("receipt", value)
