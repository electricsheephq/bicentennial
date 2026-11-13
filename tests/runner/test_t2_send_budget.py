"""T2 sends per arm (#507): floor first, then the system, each with its own max_sends; the stop record."""

import json
import runpy
from dataclasses import replace
from pathlib import Path

import pytest
from test_t2 import read, t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.canon import canon
from bicentennial.director.upstream import forward
from bicentennial.runner import live as live_module
from bicentennial.runner import stop_record, t2, units

ITEM_IDS = ("t1-g1-shared", "t1-g2-shared", "action", "unreached")


def trace(monkeypatch, plant=None):
    """Keep each live reply's try diagnostics in the run's records, as the director's ledger rows hold them."""
    inner = units.run_life

    def traced(**kw):
        guard, replies = kw["live"], []

        class Live:
            def __getattr__(self, name):
                return getattr(guard, name)

            def respond(self, call):
                reply = guard.respond(call)
                if plant is not None:
                    reply = replace(reply, upstream=tuple(plant(kw, guard)))
                replies.append(reply)
                return reply

        run = inner(**(kw | {"live": Live()}))
        return replace(run, records=run.records + tuple(dict(role="probe_main", served_by="live", upstream=[
            dict(role="probe_main", served_by="live", diagnostics=list(r.upstream))]) for r in replies))

    monkeypatch.setattr(units, "run_life", traced)


def real_stack(monkeypatch, s, retry_at=()):
    """The real live stack over a fake transport; the sends listed in retry_at get a retryable 503."""
    helpers = runpy.run_path(str(Path(__file__).with_name("test_live_stack.py")))
    helpers["home"].__wrapped__(s.home)
    stacks, sent = [], []

    def build(*args, **kwargs):
        stack = live_module.build_live_stack(*args, **(kwargs | {"rate": 0}))
        stack.inner.inner.sleep = lambda seconds: None
        stacks.append(stack)
        return stack

    def send(up, data, headers):
        sent.append(len(data))
        retry = len(sent) in retry_at
        return dict(status=503 if retry else 200, category="server" if retry else None, retry_after_s=None,
            body_shape=None, body_read_error=None, n_unparsed=0, n_dropped_items=0,
            served_model=None if retry else "synthetic-identity", usage={"input_tokens": 2, "output_tokens": 1},
            text="ok", tool_calls=(), forward=not retry, stop_reason=None)

    monkeypatch.setattr(t2, "build_live_stack", build)
    monkeypatch.setattr(forward, "send", send)
    return stacks, sent


def test_floor_near_its_cap_leaves_the_system_its_full_cap(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    stacks, sent = real_stack(monkeypatch, s)
    # Four floor units use all four sends; one shared counter would have refused the first system send.
    assert s.invoke(max_sends=4) == 0
    assert stacks[0].state()["sends"] == len(sent) == 8
    live = read(s.out, "disclosures.json")["live"]
    assert live["sends"] == 8
    assert live["max_sends"] == 4
    assert live["phase_sends"] == dict(floor=4, system=4)
    assert [a for a, _, _ in s.executed[:4]] == ["no_memory"] * 4  # every floor before any system unit


def test_system_over_its_cap_is_a_spend_stop_with_a_record(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    trace(monkeypatch)
    # The first system send is retried once, so the system needs five sends against its four.
    stacks, sent = real_stack(monkeypatch, s, retry_at={5})
    assert s.invoke(slots=1, max_sends=4) == 3
    assert read(s.out, "refusal.json") == {"code": "spend_stop"}
    assert stacks[0].state()["sends"] == len(sent) == 8
    record = read(s.out, "attempts.json")
    assert record["totals"] == dict(max_sends=4, cap=8, phase="system", sends=8, identity_check=0, attempts=8,
                                    unattributed=0)
    attempts = record["attempts"]
    assert [a["sent"] for a in attempts if a["arm"] == "no_memory"] == [1] * 4
    system = {(a["life"], a["branch"]): a for a in attempts if a["arm"] == "system"}
    # Run in admission order (t1-g2 first, the longer); the cap refuses the last unit's only send.
    assert {k: (a["sent"], a["resent"], a["refused"]) for k, a in system.items()} == {
        ("t1-g2", "B0"): (2, 1, 0), ("t1-g2", "B1"): (1, 0, 0), ("t1-g1", "B0"): (1, 0, 0), ("t1-g1", "B1"): (0, 0, 1)}
    latest = max(attempts, key=lambda a: a["last_sent_ms"] or -1)
    assert latest is system["t1-g1", "B0"]
    assert record["cap_reached_in"] == dict(arm="system", life="t1-g1", branch="B0", attempt=0)
    # One clock: the cap's refusal follows the last send.
    refused = system["t1-g1", "B1"]
    assert refused["first_refused_ms"] >= latest["last_sent_ms"] and refused["last_sent_ms"] is None


def test_cached_floor_gives_the_system_its_cap_after_the_identity_check(t2_scenario, tmp_path, monkeypatch):  # noqa: F811
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache) == 0
    s.executed.clear()
    stacks, sent = real_stack(monkeypatch, s)
    assert s.invoke(cache=cache, max_sends=4) == 0
    assert all(arm == "system" for arm, _, _ in s.executed)
    assert len(sent) == 5
    disclosures = read(s.out, "disclosures.json")
    assert disclosures["identity_check"]["tries"] == 1
    assert disclosures["live"]["phase_sends"] == dict(floor=1, system=4)
    assert disclosures["live"]["max_sends"] == 4


def test_control_run_stays_one_phase(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    assert s.invoke("fake", control="no_memory") == 0
    assert not hasattr(s.stacks[-1], "phases")
    live = read(s.out.with_name("fake"), "disclosures.json")["live"]
    assert "max_sends" not in live and "phase_sends" not in live
    trace(monkeypatch)
    stacks, sent = real_stack(monkeypatch, s)
    # One phase: the four control units share the one cap, as before.
    assert s.invoke(control="no_memory", max_sends=3) == 3
    assert read(s.out, "refusal.json") == {"code": "spend_stop"}
    assert len(sent) == 3
    assert read(s.out, "attempts.json")["totals"] == dict(max_sends=3, cap=3, phase="no_memory", sends=3,
        identity_check=0, attempts=3, unattributed=0)


def fake_record(s, monkeypatch):
    """A slot-1 system run whose t1-g1/B0 retries on INFRA and whose t1-g1/B1 send the cap refuses."""
    s.behaviour[("system", "t1-g1", "B0")] = "503"
    clock = iter(range(1000, 10**6, 10))

    def plant(kw, guard):
        values = guard.stack.values
        if (kw["arm"], kw["life_dir"].name, kw["branch"]) == ("system", "t1-g1", "B1"):
            values["spend_stopped"] = True
            # Sends no ledger row attributes, to show the remainder.
            values["sends"] = values.get("sends", 0) + 1
            return [{"kind": "try", "try": 1, "sent": False, "t_refused_ms": next(clock)}]
        values["sends"] = values.get("sends", 0) + 1
        return [dict({"try": 1}, kind="try", sent=True, t_sent_ms=next(clock), served_model="synthetic-identity",
                     sent_sha256="f" * 64)]

    trace(monkeypatch, plant)


def test_stop_record_names_sends_causes_and_where_the_cap_was_reached(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    fake_record(s, monkeypatch)
    assert s.invoke(slots=1) == 3
    assert read(s.out, "refusal.json") == {"code": "spend_stop"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json", "receipt.json", "custody.json", "attempts.json"}
    data = (s.out / "attempts.json").read_bytes()
    assert not any(token.encode() in data for token in (*ITEM_IDS, "synthetic-identity", "f" * 64))
    record = json.loads(data)
    key = ("arm", "life", "branch", "attempt")
    rows = {tuple(a[k] for k in key): a for a in record["attempts"]}
    # Card order within each phase, as the receipt lists them.
    assert list(rows) == [*(("no_memory", life, b, 0) for life in ("t1-g1", "t1-g2") for b in ("B0", "B1")),
        *(("system", "t1-g1", "B0", n) for n in range(3)), ("system", "t1-g1", "B1", 0),
        ("system", "t1-g2", "B0", 0), ("system", "t1-g2", "B1", 0)]
    for n in range(3):
        row = rows["system", "t1-g1", "B0", n]
        assert row["infra"] == {"unavailable": 1} and row["score_infra"] == {"synthetic": 1}
        assert row["sent"] == 1 and row["audit"] == "OK" and row["stopped"] is None
    assert rows["system", "t1-g2", "B0", 0]["stopped"] == ["SYSTEM_FAILURE", "turn_timeout"]
    assert rows["system", "t1-g2", "B0", 0]["score_infra"] == {}
    stopped = rows["system", "t1-g1", "B1", 0]
    assert (stopped["sent"], stopped["refused"], stopped["last_sent_ms"]) == (0, 1, None)
    assert stopped["first_refused_ms"] > rows["system", "t1-g1", "B0", 2]["last_sent_ms"]
    assert record["cap_reached_in"] == dict(arm="system", life="t1-g1", branch="B0", attempt=2)
    # The fake's phase boundary is the four floor sends; the trigger's send has no ledger row.
    assert record["totals"] == dict(max_sends=100, cap=104, phase="system", sends=10, identity_check=0,
                                    attempts=9, unattributed=1)


@pytest.mark.parametrize("mode,code", [("canary", "canary"), ("socket", "isolation")])
def test_invalid_refusals_publish_no_stop_record(t2_scenario, monkeypatch, mode, code):  # noqa: F811
    s = t2_scenario
    s.mode = mode
    trace(monkeypatch)
    assert s.invoke() == 3
    assert read(s.out, "refusal.json")["code"] == code
    assert {p.name for p in s.out.iterdir()} == {"refusal.json"}


def test_needle_in_stop_record_is_a_credential_scan(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    s.mode = "spend"
    monkeypatch.setattr(t2, "stop_record", lambda **kw: canon({"planted": "synthetic-access-token"}))
    assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": "credential_scan"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json"}


def test_builder_failure_leaves_the_refusal_as_before(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    s.mode = "spend"

    def broken(tries):
        raise RuntimeError("synthetic builder failure")

    monkeypatch.setattr(stop_record, "_sends", broken)
    assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": "spend_stop"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json", "receipt.json", "custody.json"}
    assert stop_record.build(runs=[None], labels=(), stack=None, max_sends=1, cap=1, phase="floor",
                             identity_tries=()) is None


def test_cap_reached_in_only_on_a_spend_stop():
    # A credential or live stop never reached the cap: the record must not name an attempt (#507 review).
    from types import SimpleNamespace as N
    tries = [dict(kind="try", sent=True, t_sent_ms=5)]
    run = N(arm="system", life="t1-g1", branch="B0", attempt=0, classes={}, stopped=None, audit={"status": "OK"},
            records=(dict(upstream=[dict(served_by="live", diagnostics=tries)]),))
    stack = N(state=lambda: {"sends": 1})
    named = dict(arm="system", life="t1-g1", branch="B0", attempt=0)
    for code, expected in (("spend_stop", named), ("credential_stop", None), ("live_stop", None)):
        record = json.loads(stop_record.build(runs=[run], labels=(), stack=stack, max_sends=100, cap=100,
                                              phase="floor", identity_tries=(), code=code))
        assert record["cap_reached_in"] == expected and record["totals"]["sends"] == 1


def test_live_floor_stop_relabels_the_plugin_system_as_in_one_schedule(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    monkeypatch.setattr(units, "is_plugin", lambda name: True)
    # The live floor stops as the system does on t1-g2/B0 only: that system unit's turn timeouts are the harness's.
    s.behaviour[("no_memory", "t1-g2", "B0")] = "stopped"
    assert s.invoke() == 0
    card = read(s.out, "card.json")
    classes = {(r["branch"], r["item_id"]): r["failure_class"] for r in card["items"]
               if r["life"] == "t1-g2" and r["item_id"] in ("action", "unreached")}
    assert classes == {("B0", "action"): "BLOCKED", ("B0", "unreached"): "BLOCKED",
                       ("B1", "action"): "SYSTEM_FAILURE", ("B1", "unreached"): "SYSTEM_FAILURE"}


def test_live_stack_send_phase(tmp_path, monkeypatch):
    helpers = runpy.run_path(str(Path(__file__).with_name("test_live_stack.py")))
    (tmp_path / "login").mkdir()
    home = helpers["home"].__wrapped__(tmp_path / "login")
    stack = live_module.build_live_stack(tmp_path / "spend.json", login_home=home, run="synthetic",
        token_url="https://synthetic.invalid/token", client_id="synthetic-client",
        base_url="https://synthetic.invalid/v1", max_output_tokens=16, max_sends=2)
    try:
        responder = stack.inner.inner
        stack._active = 1
        try:
            with pytest.raises(RuntimeError):
                stack.send_phase(3)
        finally:
            stack._active = 0  # close waits for calls in flight
        responder.values["sends"] = 2
        assert stack.send_phase(3) == 2 and responder.max_sends == 5
        with pytest.raises(ValueError):
            stack.send_phase(-1)
    finally:
        stack.close()
