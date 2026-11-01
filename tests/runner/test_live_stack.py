"""Probe-only routing and the real live stack against synthetic loopback upstreams."""

import base64
import json
import os
import runpy
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from bicentennial.director import roles
from bicentennial.director.responder import Call, Reply
from bicentennial.director.upstream import BURST, RATE_PER_MIN
from bicentennial.director.upstream import login as custody
from bicentennial.director.upstream.router import ProbeLiveRouter
from bicentennial.runner import live as stack

UP = runpy.run_path(str(Path(__file__).resolve().parents[1] / "director/test_upstream.py"))
Clock, FakeUpstream, completed, no_egress = (UP[k] for k in ("Clock", "FakeUpstream", "completed", "no_egress"))


class RecordingResponder:
    wire = "responses"

    def __init__(self, side):
        self.side, self.calls = side, []

    def respond(self, call):
        self.calls.append(call)
        return Reply(200, self.side, self.side, call.model)

    def state(self):
        return {f"{self.side}_sends": len(self.calls), "stopped": False}

    def served_identities(self):
        return {"gpt-6.1-sol": "served-sol"}


def call(role="probe_main", wire="chat", subrole="", model="gpt-6.1-sol"):
    body = {"messages": [{"role": "user", "content": "synthetic probe"}], "max_tokens": 123}
    if wire == "responses":
        body = {"input": "synthetic probe"}
    return Call(role, subrole, wire, body, model, {"session": 1, "turn": 1}, "fake-attempt")


@pytest.mark.parametrize("role", sorted(set(roles.ROLES) | roles.MAIN_ROLES | {"embeddings", "future_role"}))
def test_router_only_probe_main_is_live(role):
    scripted, live = RecordingResponder("scripted"), RecordingResponder("live")
    router = ProbeLiveRouter(scripted, live)
    request = call(role)
    reply = router.respond(request)
    assert reply.served_by == ("live" if role == "probe_main" else "scripted")
    assert live.calls == ([request] if role == "probe_main" else [])
    assert scripted.calls == ([] if role == "probe_main" else [request])


@pytest.mark.parametrize("subrole", ["summariser", "title_generation", "extraction", "vision"])
def test_aux_subroles_stay_scripted(subrole):
    scripted, live = RecordingResponder("scripted"), RecordingResponder("live")
    router = ProbeLiveRouter(scripted, live)
    assert router.respond(call("aux", subrole=subrole)).served_by == "scripted"
    assert len(scripted.calls) == 1 and live.calls == []


@pytest.mark.parametrize("wire", ["embeddings", "responses_compact", "anthropic"])
def test_live_unsupported_wire_never_forwarded(wire):
    scripted, live = RecordingResponder("scripted"), RecordingResponder("live")
    router = ProbeLiveRouter(scripted, live, live_roles={"probe_main", "embeddings"})
    reply = router.respond(call("embeddings" if wire == "embeddings" else "probe_main", wire=wire))
    assert (reply.status, reply.served) == (503, "live_unsupported")
    assert live.calls == scripted.calls == []
    assert router.state()["live_calls_by_role"] == {}


def test_router_merges_state_counts_by_role_and_delegates_identities():
    scripted, live = RecordingResponder("scripted"), RecordingResponder("live")
    router = ProbeLiveRouter(scripted, live, live_roles={"probe_main", "title"})
    for role in ("probe_main", "probe_main", "title", "write_turn"):
        router.respond(call(role))
    assert router.state() == {
        "scripted_sends": 1, "live_sends": 3, "stopped": False,
        "scripted": {"scripted_sends": 1, "stopped": False},
        "live": {"live_sends": 3, "stopped": False},
        "live_calls_by_role": {"probe_main": 2, "title": 1},
    }
    assert router.served_identities() == live.served_identities()


@pytest.fixture
def home(tmp_path):
    claims = {"exp": 4102444800, "sub": "synthetic-user", custody.AUTH_CLAIM: {
        "chatgpt_account_id": "synthetic-account"}}
    segment = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    (tmp_path / "auth.json").write_text(json.dumps({"tokens": {
        "access_token": f"e30.{segment}.fake-signature", "refresh_token": "synthetic-refresh"}}))
    return tmp_path


@pytest.fixture
def make_stack(home, monkeypatch, no_egress):
    built = []
    real_open = custody.open_login

    def forbidden_refresh(*args):
        pytest.fail("unexpected refresh of synthetic login")

    def open_fake(*args, **kwargs):
        return real_open(*args, post=forbidden_refresh, **kwargs)

    monkeypatch.setattr(custody, "open_login", open_fake)

    def make(base_url="https://fake.invalid/v1", **kwargs):
        options = dict(login_home=home, token_url="https://fake.invalid/token", client_id="fake-client",
                       run="fake-run", base_url=base_url, max_output_tokens=1000, max_sends=20)
        options.update(kwargs)
        result = stack.build_live_stack(home / "spend.json", **options)
        built.append(result)
        return result

    yield make
    for live in built:
        live.close()
    assert no_egress["outbound"] == 0


@pytest.fixture
def transport(make_stack, monkeypatch):
    clock, servers = Clock(), []
    real_pacer, real_holds, real_live = stack.Pacer, stack.Holds, stack.LiveResponder
    monkeypatch.setattr(stack, "Pacer", lambda rate, burst, stop: real_pacer(rate, burst, stop, clock, clock.sleep))
    monkeypatch.setattr(stack, "Holds", lambda: real_holds(clock=clock, sleep=clock.sleep))
    monkeypatch.setattr(stack, "LiveResponder", lambda *args, **kwargs: real_live(*args, sleep=clock.sleep, **kwargs))

    def make(script, **kwargs):
        server = FakeUpstream(clock, script)
        servers.append(server)
        live = make_stack(server.url, **kwargs)
        return ProbeLiveRouter(RecordingResponder("scripted"), live), live, server, clock

    yield make
    for server in servers:
        server.close()


def test_stack_configuration_and_close_releases_hold(make_stack, home):
    live = make_stack()
    responder = live.inner.inner
    upstream = live.upstreams["gpt-6.1-sol"]
    assert upstream.name == "sol" and upstream.wire == "responses" and upstream.effort == "medium"
    assert upstream.send_cap is False and upstream.max_output_tokens == 1000
    assert upstream.spend.policy == {"cap": 0, "price": {"input_per_million": 0, "output_per_million": 0}}
    assert responder.pacer.rate == RATE_PER_MIN / 60 and responder.pacer.burst == BURST
    assert responder.auth.handles_readmission is True and responder.max_sends == 20
    path = (home / "holder.lock").resolve()
    fd = custody.HOME_HOLDERS[path]
    os.fstat(fd)
    with pytest.raises(custody.Stop, match="^home_busy$"):
        make_stack()
    assert custody.HOME_HOLDERS[path] == fd
    live.close()
    live.close()
    assert path not in custody.HOME_HOLDERS
    with pytest.raises(OSError):
        os.fstat(fd)
    reopened = make_stack()
    assert reopened is not live


def test_stack_overrides(make_stack):
    live = make_stack(model="other-model", effort="high", rate=60, burst=2, max_sends=0)
    responder = live.inner.inner
    assert live.upstreams["other-model"].effort == "high"
    assert responder.pacer.rate == 1 and responder.pacer.burst == 2
    request = call(model="other-model")
    reply = ProbeLiveRouter(RecordingResponder("scripted"), live).respond(request)
    assert reply.served == "live_spend_stop" and live.state()["sends"] == 0


@pytest.mark.parametrize("max_sends", [None, True, 1.5, -1])
def test_stack_requires_integer_send_limit(make_stack, max_sends):
    with pytest.raises(ValueError, match="invalid responder configuration"):
        make_stack(max_sends=max_sends)


def test_failed_login_releases_its_hold(make_stack, home):
    (home / "auth.json").write_text("{}")
    with pytest.raises(custody.Stop):
        make_stack()
    assert (home / "holder.lock").resolve() not in custody.HOME_HOLDERS
    fd = custody.hold_home(home / "auth.json")
    os.close(fd)
    custody.HOME_HOLDERS.pop((home / "holder.lock").resolve())


def gate_first_build(monkeypatch):
    """The first build waits inside open_login until released, then fails; later builds go through."""
    entered, inside, go = [], threading.Event(), threading.Event()
    real = custody.open_login

    def gated(*args, **kwargs):
        entered.append(threading.current_thread().name)
        if len(entered) == 1:
            inside.set()
            go.wait(5)
            raise custody.Stop("login_error:Synthetic")
        return real(*args, **kwargs)

    monkeypatch.setattr(custody, "open_login", gated)
    return entered, inside, go


def test_builds_serialise_so_a_failed_build_keeps_another_hold(make_stack, home, monkeypatch):
    entered, inside, go = gate_first_build(monkeypatch)
    results = {}

    def build(name):
        try:
            results[name] = make_stack()
        except custody.Stop as exc:
            results[name] = exc

    first = threading.Thread(target=build, args=("A",), name="A")
    first.start()
    assert inside.wait(5)
    second = threading.Thread(target=build, args=("B",), name="B")
    second.start()
    second.join(0.3)
    assert second.is_alive() and entered == ["A"]
    go.set()
    first.join(5)
    second.join(5)
    assert entered == ["A", "B"] and isinstance(results["A"], custody.Stop)
    path = (home / "holder.lock").resolve()
    assert custody.HOME_HOLDERS[path] is not None
    with pytest.raises(custody.Stop, match="^home_busy$"):
        custody.hold_home(home / "auth.json")


def test_close_waits_for_a_build_in_flight(make_stack, home, monkeypatch):
    active = make_stack()
    entered, inside, go = gate_first_build(monkeypatch)
    failed = threading.Thread(target=lambda: pytest.raises(custody.Stop, make_stack), name="A")
    failed.start()
    assert inside.wait(5)
    closer = threading.Thread(target=active.close)
    closer.start()
    closer.join(0.3)
    assert closer.is_alive() and not active.closed
    go.set()
    failed.join(5)
    closer.join(5)
    assert active.closed and (home / "holder.lock").resolve() not in custody.HOME_HOLDERS


def test_bridge_failure_stops_the_real_stack(make_stack):
    live = make_stack()
    with pytest.raises(ValueError, match="^bridge_unmapped_key:temperature$"):
        live.respond(replace(call(), body={"temperature": 0}))
    assert live.inner.inner.state()["stopped"] is True
    assert live.inner.inner.state()["stop_reason"] == "bridge_unmapped_key:temperature"
    reply = live.respond(call())
    assert (reply.status, reply.served) == (503, "live_stopped") and live.state()["sends"] == 0


def test_probe_round_trip_and_max_sends(transport):
    router, live, server, _ = transport([
        (200, {}, completed(model="gpt-6.1-sol", usage={"input_tokens": 13, "output_tokens": 5}))], max_sends=1)
    reply = router.respond(call())
    assert (reply.status, reply.served, reply.text) == (200, "live", "ok")
    assert reply.usage == {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18}
    assert server.seen[0]["path"] == "/v1/responses"
    assert server.seen[0]["body"] == {
        "model": "gpt-6.1-sol", "stream": True, "store": False, "instructions": "",
        "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "synthetic probe"}]}], "reasoning": {"effort": "medium"},
    }
    assert router.served_identities() == {"gpt-6.1-sol": "gpt-6.1-sol"}
    assert router.respond(call("write_turn")).served_by == "scripted"
    assert [router.respond(call()).served for _ in range(2)] == ["live_spend_stop", "live_spend_stop"]
    assert live.state()["spend_stopped"] and live.state()["sends"] == 1 and len(server.seen) == 1
    assert router.state()["live_calls_by_role"] == {"probe_main": 1}


def test_429_held_and_retried(transport):
    rate = (429, {"Retry-After": "7"}, b'{"error":{"code":"rate_limit"}}')
    router, live, server, clock = transport([rate] * 4 + [(200, {}, completed(model="gpt-6.1-sol"))])
    reply = router.respond(call())
    assert reply.status == 200 and len(server.seen) == 5
    assert any(d["kind"] == "hold" and d["reason"] == "rate" and d["held_ms"] >= 60000
               for d in reply.upstream)
    assert clock.now >= 125 and live.state()["sends"] == 5
    assert live.inner.inner.holds.at_boundary("fake-attempt") == {"reasons": ["rate"], "held_ms": 60000}


def test_401_stops_stack_and_no_further_send(transport):
    router, live, server, _ = transport([(401, {}, b"{}")])
    first = router.respond(call())
    assert first.status == 503
    assert live.state()["stopped"] and live.state()["stop_reason"] == "upstream_401"
    assert live.state()["login_stop"] == "upstream_401"
    assert router.respond(replace(call(), wire="responses", body={"input": "again"})).served == "live_stopped"
    assert len(server.seen) == 1 and router.state()["live_calls_by_role"] == {}
