"""Shared unit ownership, admission constants, and threaded latch boundaries."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, fields, replace
from itertools import permutations
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from test_t1 import environment, installed, prepare  # noqa: F401
from test_t2lite import Stack, live_settings, scenario  # noqa: F401

from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.items.protocol import CANARY
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner import t1, t2lite, units
from bicentennial.runner.guard import Marker
from bicentennial.runner.life import LifeRun
from bicentennial.runner.probe_live import LiveCredentialStop, LiveStop


def test_canary_forced_interleaving(monkeypatch):
    guard = units._Guard(Stack())
    barrier, canary_done = Barrier(2), Event()

    def interleaved(body):
        barrier.wait(timeout=5)
        if body == {"content": "clean"}:
            assert canary_done.wait(timeout=5)
        return canon(body)

    monkeypatch.setattr(units, "canon", interleaved)

    def send(text):
        reply = guard.respond(Call("probe_main", "", "chat", {"content": text}, t2lite.MODEL, None, "synthetic"))
        if text == CANARY:
            canary_done.set()
        return reply

    with ThreadPoolExecutor(max_workers=2) as pool:
        clean, canary = pool.submit(send, "clean"), pool.submit(send, CANARY)
        assert canary.result(timeout=10).status == 503
        clean.result(timeout=10)
    assert guard.canary
    guard.canary = False
    assert guard.canary
    monkeypatch.setattr(units, "canon", canon)
    assert send("later clean").status == 503
    assert not guard.stack.calls


def test_stop_latch_survives_clean_state():
    guard = units._Guard(Stack())
    guard.stopped.set()
    assert guard.state()["stopped"] is True
    with pytest.raises(LiveStop, match="stopped"):
        units._check_stop(guard)
    assert guard.stopped.is_set()


def test_refusal_reduction_all_orders():
    errors = [t1.T1Refused("canary"), t1.T1Refused("honeypot"), LiveCredentialStop("upstream_401"),
              t1.T1Refused("spend_stop"), LiveStop("stopped"), t1.T1Refused("isolation")]
    assert units.reduce_refusals([]) is None
    for offset, expected in enumerate(errors):
        for order in permutations(errors[offset:]):
            assert units.reduce_refusals(order) is expected
    # Equal-priority reasons also have a stable winner.
    a, b = t1.T1Refused("a"), t1.T1Refused("b")
    assert units.reduce_refusals([b, a]) is units.reduce_refusals([a, b]) is a


def test_floor_stop_belongs_to_returned_unit(scenario, monkeypatch):  # noqa: F811
    scenario.mode = "relabel"
    collect, returned = t2lite._collect_unit, []
    foreign = LifeRun("no_memory", "other", "B1", 0, stopped=("SYSTEM_FAILURE", "end_timeout", 42))

    def interleave(runs, *args, **kwargs):
        result = collect(runs, *args, **kwargs)
        returned.append(result)
        runs.append(foreign)
        return result

    monkeypatch.setattr(t2lite, "_collect_unit", interleave)
    assert scenario.invoke() == 0
    floor = t2lite._read(scenario.out, "no_memory.json")
    assert set(map(tuple, floor["stops"].values())) == {("SYSTEM_FAILURE", "turn_timeout", 5)}
    for result in returned:
        assert result.stop == result.runs[-1].stopped == ("SYSTEM_FAILURE", "turn_timeout", 5)
        assert result.attempts == len(result.runs) == 1


def test_refusing_partial_run_reaches_caller(scenario, monkeypatch):  # noqa: F811
    seen = []

    def stopped(**kw):
        seen.append(kw["live"])
        ledger = kw["scratch"] / kw["branch"] / "run/ledger"
        store = BlobStore(ledger / "blobs", Guard([]))
        rows = [{"type": "request", "role": "probe_main", "seq": 1, "t_ms": 5,
                 "req": store.put({"content": kw["honeypot_token"]}),
                 "resp": store.put({"usage": {"prompt_tokens": 2, "completion_tokens": 1}})}]
        (ledger / "ledger.jsonl").write_bytes(b"".join(canon(row) + b"\n" for row in rows))
        raise LiveCredentialStop("upstream_401")

    monkeypatch.setattr(units, "run_life", stopped)
    assert scenario.invoke() == 3
    assert t2lite._read(scenario.out, "refusal.json") == {"code": "honeypot"}
    assert len(seen) == 1 and seen[0].stopped.is_set()


def test_t1_spec_constants():
    assert units.T1_SPEC.pack_tier == "T1"
    assert units.T1_SPEC.composition == ("G1", "G2")
    assert units.T1_SPEC.roots == 2
    assert units.T1_SPEC.context_roots(Marker(0, False, "synthetic"), None) == 2
    assert units.T1_SPEC.context_roots(Marker(10, False, "synthetic"), None) == 1
    with pytest.raises(FrozenInstanceError):
        units.T1_SPEC.roots = 1


@pytest.mark.parametrize("marker_exit,roots", [(0, 2), (10, 1)])
def test_prepare_explicit_spec_equal_default(installed, monkeypatch, marker_exit, roots):  # noqa: F811
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(marker_exit, False, "synthetic"))
    default, explicit = prepare(installed), prepare(installed, spec=units.T1_SPEC)
    for field in fields(default):
        left, right = getattr(default, field.name), getattr(explicit, field.name)
        if field.name == "current_lock":
            assert left() == right()
        elif field.name == "gate":
            assert vars(left) == vars(right)
        else:
            assert left == right
    assert explicit.roots == roots
    calls, admit = [], t1.admit

    def admitted(marker, **kw):
        calls.append(kw["roots"])
        return admit(marker, **kw)

    monkeypatch.setattr(t1, "admit", admitted)
    prepare(installed, spec=units.T1_SPEC)
    assert calls == [2]


def test_prepare_spec_roots_rule_gets_admission(installed, monkeypatch):  # noqa: F811
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(0, False, "synthetic"))
    spec = replace(units.T1_SPEC, roots=3, context_roots=lambda marker, admission: admission.max_roots)
    assert prepare(installed, spec=spec).roots == 3


@pytest.mark.parametrize("damage,code", [("tier", "tier"), ("composition", "tier_composition")])
def test_spec_pack_mismatch_refuses(installed, monkeypatch, damage, code):  # noqa: F811
    verify = t1.verify

    def altered(*args, **kwargs):
        index = verify(*args, **kwargs)
        if damage == "tier":
            index["tier"] = "T0"
        else:
            index["packs"] = {}
        return index

    monkeypatch.setattr(t1, "verify", altered)
    with pytest.raises(t1.T1Refused) as caught:
        prepare(installed, spec=units.T1_SPEC)
    assert caught.value.code == code


def test_unit_refusal_carries_runs_and_timing(scenario, tmp_path, monkeypatch):  # noqa: F811
    def stopped(**kw):
        raise LiveStop("synthetic stop")

    monkeypatch.setattr(units, "run_life", stopped)
    live = units._Guard(Stack())
    ctx = SimpleNamespace(**(vars(scenario.ctx) | {"turn_wait_s": 3.0}))
    with pytest.raises(units.UnitRefusal) as caught:
        units._unit(ctx, ctx.packs[0], "B0", "system", tmp_path / "attempt", live, tmp_path / "unit")
    error = caught.value
    assert isinstance(error.error, LiveStop)
    assert len(error.runs) == error.timing["attempts"] == 1
    assert error.runs[0].arm == "system" and error.runs[0].attempt == 0
    assert live.stopped.is_set()
