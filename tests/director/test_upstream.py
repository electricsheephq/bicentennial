"""R17a: only scripted loopback HTTP, virtual waits, and synthetic credentials."""

import ast
import http.client
import json
import runpy
import threading
import unittest
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.director.upstream import (
    Holds,
    LiveResponder,
    Pacer,
    Upstream,
    forward,
)
from bicentennial.ledger import Guard
from bicentennial.runner.guard import Marker
from bicentennial.runner.spend import Price, Spend

ROOT = Path(__file__).resolve().parents[2]
CORE = runpy.run_path(str(ROOT / "tests/director/test_core.py"))
no_egress = CORE["no_egress"]
SENTINEL = "PRIVATE_PROVIDER_SENTINEL"
PRICE = Price(0, 400_000)


class Clock:
    def __init__(self):
        self.now, self.lock, self.local, self.sleeps = 0.0, threading.Lock(), threading.local(), []

    def __call__(self):
        with self.lock:
            self.local.last = self.now
            return self.now

    def sleep(self, delay):
        assert delay > 0
        with self.lock:
            self.sleeps.append(delay)
            self.now += delay


def frames(*events):
    return b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in events)


def completed(model="probe-model", text="ok", usage=None):
    return frames({"type": "response.output_item.done", "item": {
        "type": "message", "content": [{"type": "output_text", "text": text}]}},
        {"type": "response.completed", "response": {"model": model, "usage": usage}})


def chat(model="probe-model", text="ok", **kw):
    return json.dumps({"model": model, "choices": [{"message": {"content": text}, "finish_reason": "length"}], **kw}).encode()


def error(category, status=200):
    return status, {}, frames({"type": "error", "code": category, "message": SENTINEL, "detail": SENTINEL})


class FakeUpstream:
    def __init__(self, clock, script, default=None):
        self.clock, self.script, self.default = clock, list(script), default
        self.seen, self.lock, self.errors = [], threading.Lock(), []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                with owner.lock:
                    owner.seen.append({"path": self.path, "headers": dict(self.headers),
                                       "body": json.loads(body), "raw": body, "t": clock()})
                    reply = owner.script.pop(0) if owner.script else owner.default
                    if reply is None:
                        owner.errors.append("unexpected request")
                        reply = (500, {}, b"{}")
                status, headers, data = reply
                self.send_response(status)
                for key, value in headers.items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        class Server(ThreadingHTTPServer):
            request_queue_size = 128

        self.server = Server(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()
        assert self.errors == []


@pytest.fixture(autouse=True)
def offline_and_canonical(no_egress, monkeypatch):
    real = LiveResponder.respond

    def checked(self, call):
        reply = real(self, call)
        canon(asdict(reply))
        return reply

    monkeypatch.setattr(LiveResponder, "respond", checked)
    yield
    assert no_egress["outbound"] == 0


@pytest.fixture
def setup(tmp_path):
    servers = []

    def make(script=(), *, default=None, clock=None, wire="responses", rate=0, burst=10,
             cap=10**9, price=PRICE, spend=None, account="account_a", holds=None, **upkw):
        clock = clock or Clock()
        server = FakeUpstream(clock, script, default)
        servers.append(server)
        spend = spend or Spend(tmp_path / f"spend-{len(servers)}.json", cap, price)
        pacer = Pacer(rate, burst, threading.Event(), clock, clock.sleep)
        holds = holds or Holds(clock=clock, sleep=clock.sleep)
        up = Upstream("fake", "probe-model", server.url, wire, spend, price, 1000, **upkw)
        responder = LiveResponder(account, pacer, lambda: {"Authorization": "Bearer synthetic"}, [up], holds,
                                  sleep=clock.sleep)
        return responder, server, clock, up

    yield make
    for server in servers:
        server.close()


def call(wire="responses", model="probe-model", body=None, run_key="attempt-1"):
    return Call("aux", "title_generation", wire, body or {}, model, None, run_key)


def tries(reply):
    return [d for d in reply.upstream if d["kind"] == "try"]


def assert_windows(times, bound=190, width=60000):
    times = sorted(times)
    end = 0
    for i, start in enumerate(times):
        while end < len(times) and times[end] < start + width:
            end += 1
        assert end - i <= bound


class TestPacing(unittest.TestCase):
    def bucket(self, rate=180, burst=10, **kw):
        clock, stop = Clock(), threading.Event()
        return Pacer(rate, burst, stop, clock, clock.sleep, **kw), clock, stop

    def assert_windows(self, times, bound):
        times = sorted(times)
        for start in times:
            self.assertLessEqual(sum(start <= t < start + 60 for t in times), bound)

    def test_window_bound_with_injected_clock(self):
        bucket, clock, _ = self.bucket()
        times = []
        for n in range(400):
            if n == 200:
                clock.now += 120
            bucket.acquire()
            times.append(clock.local.last)
        self.assert_windows(times, 190)
        self.assertEqual(times[:10], [0] * 10)
        self.assertTrue(clock.sleeps)

    def test_four_threads_share_one_bucket(self):
        bucket, clock, _ = self.bucket()
        times, errors, lock, start = [], [], threading.Lock(), threading.Barrier(4)

        def worker():
            try:
                start.wait(timeout=2)
                local = []
                for _ in range(100):
                    bucket.acquire()
                    local.append(clock.local.last)
                with lock:
                    times.extend(local)
            except Exception as e:
                errors.append(type(e).__name__)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual((errors, len(times)), ([], 400))
        self.assert_windows(times, 190)

    def test_zero_rate_and_window_validation(self):
        bucket, clock, stop = self.bucket(rate=0)
        self.assertEqual([bucket.acquire() for _ in range(100)], [0] * 100)
        self.assertEqual(clock.sleeps, [])
        stop.set()
        self.assertIsNone(bucket.acquire())
        for rate, burst in ((190, 10), (180, 20), (0, 200), (-1, 10), (180, 0), (float("nan"), 10)):
            with self.assertRaises(ValueError):
                self.bucket(rate, burst)
        self.bucket(190, 10, allow=True)


@pytest.mark.parametrize("value,expected", [("20", 20000), ("2", 5000), ("Wed, 21 Oct 2026 07:28:00 GMT", 60000)])
def test_retry_after(setup, value, expected):
    r, server, _, _ = setup([(429, {"retry-after": value}, b"{}"), (200, {}, completed())])
    reply = r.respond(call())
    assert reply.status == 200
    assert [d["t_sent_ms"] for d in tries(reply)] == [0, expected]
    assert len(server.seen) == 2


def test_defer_applies_to_second_upstream(setup):
    r, server, clock, up = setup([(429, {"retry-after": "20"}, b"{}"), (200, {}, completed()), (200, {}, completed())])
    r.upstreams["second"] = replace(up, model="second")
    nested = []

    def sleep(seconds):
        if not nested:
            nested.append(r.respond(call(model="second")))
        clock.sleep(seconds)

    r.sleep = sleep
    assert r.respond(call()).status == 200
    assert nested[0].status == 200
    assert server.seen[1]["body"]["model"] == "second"
    assert server.seen[1]["t"] == 20


def test_final_retry_after_is_honoured(setup):
    script = [(429, {}, b"{}")] * 3 + [(429, {"retry-after": "120"}, b"{}"), (200, {}, completed())]
    r, server, _, _ = setup(script)
    reply = r.respond(call())
    ts = [d["t_sent_ms"] for d in tries(reply)]
    assert reply.status == 200 and ts[-1] - ts[-2] >= 120000
    assert len(server.seen) == 5


def test_no_synthesised_429(setup):
    r, server, _, _ = setup([(429, {}, b"{}"), (429, {}, b"{}"), (200, {}, completed())])
    reply = r.respond(call())
    assert reply.status == 200
    assert [d["category"] for d in tries(reply)] == ["rate", "rate", None]
    assert [d["retry_wait_s"] for d in tries(reply)] == [5, 15, 0]
    assert len(server.seen) == 3


@pytest.mark.parametrize("code", [400, 401, 403, 404, 413, 422])
def test_invalid_request_and_auth_stop_without_read(setup, monkeypatch, code):
    r, server, _, _ = setup([(code, {}, b"ignored")])
    read = Mock(side_effect=AssertionError("body must not be read"))
    monkeypatch.setattr(http.client.HTTPResponse, "read", read)
    reply = r.respond(call())
    assert reply.status == 503 and len(server.seen) == 1
    expected = f"upstream_{code}" if code in (401, 403) else f"upstream_invalid_request_{code}"
    assert r.state()["stop_reason"] == expected
    assert tries(reply)[0]["stop_reason"] == expected
    assert r.respond(call()).served == "live_stopped"
    read.assert_not_called()


BARE = {"type": "response.failed", "response": {"status": "failed", "error": None}}
GENERIC = {"type": "response.failed", "response": {"error": {"code": "server_error"}}}
USAGE = {"type": "error", "code": "usage_limit_reached", "message": "The usage limit has been reached"}
RATE = {"type": "error", "code": "rate_limit_exceeded", "message": "Rate limit reached for requests"}


@pytest.mark.parametrize("events,category,stopped", [
    ((USAGE, BARE), "quota", False), ((RATE, BARE), "rate", False), ((RATE, GENERIC), "rate", False),
    (({"type": "response.failed", "response": {"error": USAGE}}, {"type": "error", "code": "server_error"}), "quota", False),
    (({"type": "error", "message": "Unauthorized: invalid token for credit endpoint"},), "auth_sse", True),
    (({"type": "error", "status": 403, "error": {"code": "server_is_overloaded"}},), "auth_sse", True),
])
def test_round3_shapes(setup, events, category, stopped):
    clock = Clock()
    r, server, _, _ = setup([(200, {}, frames(*events))] * (4 if category == "rate" else 1), clock=clock,
                            holds=Holds(clock=clock, sleep=clock.sleep, max_hold_s=0))
    reply = r.respond(call())
    assert reply.status == 503
    assert tries(reply)[-1]["category"] == category
    assert r.state()["stopped"] is stopped
    assert len(server.seen) == (4 if category == "rate" else 1)
    if stopped:
        assert r.state()["stop_reason"] == "upstream_sse_auth"
    else:
        assert reply.served == "live_hold_expired"


def test_incomplete_max_output_tokens(setup):
    raw = frames({"type": "response.output_text.delta", "delta": "half an answer about quota"},
                 {"type": "response.incomplete", "response": {"model": "probe-model", "incomplete_details": {
                     "reason": "max_output_tokens"}}})
    r, _, _, _ = setup([(200, {}, raw)])
    reply = r.respond(call())
    assert (reply.status, reply.text) == (200, "half an answer about quota")


def test_output_text_naming_auth_quota_or_rate(setup):
    text = "Unauthorized 401: invalid token; usage limit and quota exceeded; rate limit, overloaded"
    r, _, _, _ = setup([(200, {}, completed(text=text))])
    reply = r.respond(call())
    assert (reply.status, reply.text, r.state()["stopped"], tries(reply)[0]["category"]) == (200, text, False, None)


def test_breaker(setup):
    other, over, ok = (200, {}, frames(BARE)), error("server_is_overloaded"), (200, {}, completed())
    r, server, _, _ = setup([other, other, over, ok, other, other, *[over] * 4])
    codes = []
    for i in range(6):
        codes.append(r.respond(call()).status)
        assert r.state()["stopped"] is (i == 5)
    assert codes == [503, 503, 200, 503, 503, 503]
    assert r.state()["stop_reason"] == "upstream_failures_3_in_a_row"
    assert server.script == []


def test_three_unparsed(setup):
    r, server, _, _ = setup([(200, {}, b"data: {broken}\n\n" + completed())] * 3)
    r.values["failure_streak"] = 2
    for i in range(3):
        assert r.respond(call()).status == 503
        assert r.state()["failure_streak"] == 2
        assert r.state()["stopped"] is (i == 2)
    assert r.state()["stop_reason"] == "upstream_unparsed_3_in_a_row"
    assert r.respond(call()).served == "live_stopped"
    assert len(server.seen) == 3


@pytest.mark.parametrize("code", [200, 503])
def test_oversize(setup, monkeypatch, code):
    r, _, _, _ = setup([(code, {}, b"x" * 33)])
    monkeypatch.setattr(forward, "MAX_BODY", 32)
    real, reads = http.client.HTTPResponse.read, []

    def read(self, n=None):
        reads.append(n)
        return real(self, n)

    monkeypatch.setattr(http.client.HTTPResponse, "read", read)
    parse = Mock(side_effect=AssertionError("oversize must not be parsed"))
    monkeypatch.setattr(forward, "parse_sse", parse)
    reply = r.respond(call())
    assert reply.status == 503 and tries(reply)[0]["category"] == "error:oversize"
    assert reads == [33]
    parse.assert_not_called()


def test_long_first_error(setup):
    clock = Clock()
    raw = frames({"type": "error", "message": "x" * 2200}, RATE)
    r, server, _, _ = setup([(200, {}, raw)] * 4, clock=clock,
                            holds=Holds(clock=clock, sleep=clock.sleep, max_hold_s=0))
    reply = r.respond(call())
    assert reply.served == "live_hold_expired"
    assert [d["category"] for d in tries(reply)] == ["rate"] * 4
    assert len(server.seen) == 4


@pytest.mark.parametrize("status", [201, 202, 206])
def test_completed_under_other_2xx(setup, status):
    r, _, _, _ = setup([(status, {}, completed())])
    assert r.respond(call()).status == 503


def test_error_scope_top_level(setup):
    raw = frames({"type": "response.completed", "response": {"model": "probe-model", "tools": [{
        "parameters": {"properties": {"error": {"description": "Unauthorized quota"}}}}]}})
    r, _, _, _ = setup([(200, {}, raw)])
    assert r.respond(call()).status == 200


def test_in_stream_overload(setup):
    raw = frames({"type": "response.failed", "response": {"instructions": "x" * 3000, "tools": [{}] * 40,
                 "error": {"code": "server_is_overloaded"}}})
    r, _, _, _ = setup([(200, {}, raw), (200, {}, completed())])
    reply = r.respond(call())
    assert reply.status == 200
    assert [d["category"] for d in tries(reply)] == ["overload", None]
    assert r.state()["failure_streak"] == 0


def run_threads(worker, n):
    errors = []

    def checked(i):
        try:
            worker(i)
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=checked, args=(i,)) for i in range(n)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(t.is_alive() for t in threads)
    assert errors == []


def test_stop_releases_waiters(setup):
    r, server, _, up = setup([(200, {}, completed())], rate=1, burst=1)
    assert r.respond(call()).status == 200
    waiting = threading.Barrier(5)
    r.pacer.sleep = lambda delay: (waiting.wait(timeout=3), r.pacer.stop.wait(delay))
    replies, errors = [], []

    def worker():
        try:
            replies.append(r.respond(call()))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    waiting.wait(timeout=3)
    r.stop("test_stop")
    for thread in threads:
        thread.join(timeout=2)
    assert not any(t.is_alive() for t in threads)
    assert errors == [] and len(replies) == 4
    assert all(p.served == "live_stopped" and not tries(p)[0]["sent"] for p in replies)
    assert all(tries(p)[0]["charged"] == 0 for p in replies)
    assert len(server.seen) == 1
    data = json.loads(up.spend.path.read_bytes())
    assert data["settled_calls"] == 5 and data["open"] == {} and data["settled"] == 400


def test_backoff_checks_stop_each_second(setup):
    r, server, _, _ = setup([(429, {}, b"{}")])
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        r.stop("backoff_stop")

    r.sleep = sleep
    assert r.respond(call()).status == 503
    assert sleeps == [1] and len(server.seen) == 1


@pytest.mark.parametrize("accounts", [1, 2])
def test_offline_soak(setup, accounts):
    responders = [setup(default=(200, {}, completed()), rate=180, price=Price(0, 0), account="account_0")]
    for i in range(1, accounts):
        responders.append(setup(default=(200, {}, completed()), rate=180, price=Price(0, 0),
                                spend=responders[0][3].spend, account=f"account_{i}"))
    replies = [[] for _ in responders]

    def worker(i):
        account = i // 8
        r = responders[account][0]
        for _ in range(125):
            replies[account].append(r.respond(call(run_key=f"attempt-{i}")))

    run_threads(worker, accounts * 8)
    for (r, server, _, _), results in zip(responders, replies, strict=True):
        categories = Counter(d["category"] for p in results for d in tries(p))
        assert len(results) == len(server.seen) == r.state()["sends"] == 1000, (categories, r.state())
        assert all(p.status == 200 for p in results)
        assert not any(p.status == 429 for p in results)
        assert_windows([d["t_sent_ms"] for p in results for d in tries(p)])


def test_glm_hold_and_boundary(setup):
    clock, states, reads = Clock(), iter([True, True, False]), []

    def marker():
        reads.append(clock())
        return Marker(0, next(states), "test")

    holds = Holds(clock=clock, sleep=clock.sleep, marker=marker)
    r, server, _, _ = setup([(200, {}, completed())], clock=clock, holds=holds, glm_plan=True)
    reply = r.respond(call())
    assert reply.status == 200
    assert [d for d in reply.upstream if d["kind"] == "hold"] == [{"kind": "hold", "reason": "glm", "held_ms": 120000}]
    assert reads == [0, 60, 120] and server.seen[0]["t"] == 120
    assert tries(reply)[0]["t_ms"] == 0
    assert holds.at_boundary("attempt-1") == {"reasons": ["glm"], "held_ms": 120000}
    assert holds.at_boundary("attempt-1") == {"reasons": [], "held_ms": 0}


@pytest.mark.parametrize("raises", [False, True])
def test_unreadable_marker_holds(setup, raises):
    clock = Clock()

    def marker():
        if raises:
            raise OSError("synthetic marker unreadable")
        return Marker(None, None, "unreadable")

    holds = Holds(clock=clock, sleep=clock.sleep, marker=marker, max_hold_s=120)
    r, server, _, _ = setup(clock=clock, holds=holds, glm_plan=True)
    assert r.respond(call()).served == "live_hold_expired"
    assert server.seen == [] and clock.now == 120


def test_non_glm_never_reads_marker(setup):
    marker = Mock(side_effect=AssertionError("non-glm read marker"))
    r, _, _, _ = setup([(200, {}, completed())], holds=Holds(marker=marker))
    assert r.respond(call()).status == 200
    marker.assert_not_called()


@pytest.mark.parametrize("release", [True, False])
def test_quota_hold(setup, release):
    clock, polls = Clock(), []

    def sleep(seconds):
        polls.append(seconds)
        clock.sleep(seconds)
        if release and len(polls) == 2:
            holds.release("attempt-1")

    holds = Holds(clock=clock, sleep=sleep)
    script = [error("insufficient_quota")] + ([(200, {}, completed())] if release else [])
    r, server, _, _ = setup(script, clock=clock, holds=holds)
    reply = r.respond(call())
    assert reply.served == ("live" if release else "live_hold_expired")
    assert len(server.seen) == (2 if release else 1)
    assert [d["held_ms"] for d in reply.upstream if d["kind"] == "hold"] == [120000 if release else 7200000]
    assert holds.at_boundary("attempt-1") == {"reasons": ["quota"], "held_ms": 120000 if release else 7200000}


def test_rate_hold(setup):
    r, server, _, _ = setup([(429, {}, b"{}")] * 4 + [(200, {}, completed())])
    reply = r.respond(call())
    assert reply.status == 200 and len(server.seen) == 5
    assert [d for d in reply.upstream if d["kind"] == "hold"] == [{"kind": "hold", "reason": "rate", "held_ms": 60000}]
    assert tries(reply)[-1]["t_sent_ms"] == 125000


def test_repeated_holds_share_one_call_budget(setup):
    clock, states = Clock(), iter([True, False, False])
    holds = Holds(clock=clock, sleep=clock.sleep, marker=lambda: Marker(0, next(states), "test"), max_hold_s=120)
    r, server, _, _ = setup([error("insufficient_quota")], clock=clock, holds=holds, glm_plan=True)
    reply = r.respond(call())
    assert reply.served == "live_hold_expired" and clock.now == 120 and len(server.seen) == 1
    assert [d["held_ms"] for d in reply.upstream if d["kind"] == "hold"] == [60000, 60000]


def test_spend_refusal_latches(setup):
    r, server, _, up = setup([(200, {}, completed())] * 2, cap=1000)
    assert [r.respond(call()).status for _ in range(2)] == [200, 200]
    for _ in range(2):
        reply = r.respond(call())
        assert reply.served == "live_spend_stop"
        assert tries(reply)[0]["reserved"] is None and tries(reply)[0]["sent"] is False
    assert len(server.seen) == 2
    assert json.loads(up.spend.path.read_bytes())["refused_calls"] == 1


def test_spend_settlement_and_body_cap(setup):
    r, _, _, up = setup([(200, {}, completed(usage={"input_tokens": 10, "output_tokens": 100, "fraction": 1.5,
                                                              "flag": True}))] * 2)
    first = r.respond(call())
    assert first.usage == {"input_tokens": 10, "output_tokens": 100}
    assert tries(first)[0]["charged"] == PRICE.cost(10, 100) == 40
    assert tries(r.respond(call(body={"max_output_tokens": 50})))[0]["reserved"] == 20
    assert json.loads(up.spend.path.read_bytes())["settled"] == 80


def test_two_accounts_share_run_spend(setup, tmp_path):
    spend = Spend(tmp_path / "shared.json", 1000, PRICE)
    a, sa, _, _ = setup([(200, {}, completed())], spend=spend)
    b, sb, _, _ = setup([(200, {}, completed())], spend=spend, account="account_b")
    assert a.respond(call()).status == b.respond(call()).status == 200
    assert a.respond(call()).served == b.respond(call()).served == "live_spend_stop"
    assert len(sa.seen) + len(sb.seen) == 2


def test_identity_alias_drift_through_director(setup, tmp_path):
    r, server, _, _ = setup([(200, {}, chat(model=m)) for m in ("served-v1", "served-v1", "served-v2", "served-v2")], wire="chat")
    d = CORE["make"](tmp_path, r)
    CORE["start"](d, tmp_path)
    try:
        assert [CORE["post"](d, "/aux/title_generation/v1/chat/completions", CORE["TITLE"])[0]
                for _ in range(4)] == [200] * 4
    finally:
        d.close()
    records = CORE["records"](tmp_path)
    diags = [rec["upstream"][0]["diagnostics"][0] for rec in records]
    assert [x.get("identity_changed", False) for x in diags] == [False, False, True, True]
    assert r.state()["identity_drift"] == {"model": "probe-model", "baseline": "served-v1", "served": "served-v2"}
    assert not r.state()["stopped"] and len(server.seen) == 4
    ids = r.served_identities()
    assert ids == {"probe-model": "served-v1"}
    ids.clear()
    assert r.served_identities() == {"probe-model": "served-v1"}


@pytest.mark.parametrize("wire", ["responses", "chat"])
def test_missing_served_model_flags_drift(setup, wire):
    raw = completed(model=None) if wire == "responses" else chat(model=None)
    r, server, _, _ = setup([(200, {}, raw)] * 2, wire=wire)
    for _ in range(2):
        reply = r.respond(call(wire))
        assert reply.status == 200 and reply.model == "probe-model"
        assert tries(reply)[0]["identity_changed"] is True
        assert tries(reply)[0]["served_model"] == "unidentified"
    assert r.state()["identity_drift"]["served"] == "unidentified"
    assert not r.state()["stopped"] and len(server.seen) == 2


def test_aux_summariser_routes_to_summary_model(setup, tmp_path):
    r, server, _, up = setup([(200, {}, chat(model="summary-model"))], wire="chat")
    r.upstreams["summary-model"] = replace(up, model="summary-model")
    seen, original = [], r.respond

    def respond(call):
        seen.append(call)
        return original(call)

    r.respond = respond
    d = CORE["make"](tmp_path, r)
    d.ctx.path_aliases["/aux/summariser/"] = CORE["roles"].alias("summariser")
    CORE["start"](d, tmp_path)
    try:
        body = dict(CORE["TITLE"], model="bicentennial-aux-summariser")
        assert CORE["post"](d, "/aux/summariser/v1/chat/completions", body)[0] == 200
    finally:
        d.close()
    assert seen[0].model == "summary-model"
    assert (seen[0].role, seen[0].subrole) == ("aux", "summariser")
    assert server.seen[0]["body"]["model"] == "summary-model"
    CORE["records"](tmp_path)


@pytest.mark.parametrize("kind", ["500", "400", "401", "quota", "chat_error", "non_json"])
def test_error_text_never_reaches_harness(setup, tmp_path, kind):
    clock = Clock()
    payload = json.dumps({"error": {"message": SENTINEL, "detail": SENTINEL}}).encode()
    script = [(int(kind), {}, payload)] * (4 if kind == "500" else 1) if kind.isdigit() else [
        (429, {}, json.dumps({"error": {"code": "insufficient_quota", "message": SENTINEL, "detail": SENTINEL}}).encode())
        if kind == "quota" else (200, {}, payload if kind == "chat_error" else SENTINEL.encode())]
    r, _, _, _ = setup(script, wire="chat", clock=clock, holds=Holds(clock=clock, sleep=clock.sleep, max_hold_s=0))
    replies, original = [], r.respond

    def respond(call):
        reply = original(call)
        replies.append(reply)
        return reply

    r.respond = respond
    d = CORE["make"](tmp_path, r)
    CORE["start"](d, tmp_path)
    try:
        status, _, data = CORE["post"](d, "/aux/title_generation/v1/chat/completions", CORE["TITLE"])
    finally:
        d.close()
    assert status == 503 and b"responder refused" in data and SENTINEL.encode() not in data
    assert SENTINEL.encode() not in canon(asdict(replies[0]))
    CORE["records"](tmp_path)


@pytest.mark.parametrize("code", ["server_error", "insufficient_quota", "rate_limit_exceeded", "invalid_api_key"])
def test_stream_error_text_never_reaches_reply(setup, code):
    clock = Clock()
    r, _, _, _ = setup([error(code)] * (4 if code == "rate_limit_exceeded" else 1), clock=clock,
                       holds=Holds(clock=clock, sleep=clock.sleep, max_hold_s=0))
    reply = r.respond(call())
    assert reply.status == 503 and SENTINEL.encode() not in canon(asdict(reply))


@pytest.mark.parametrize("wire", ["responses", "chat"])
def test_forward_shape_and_auth_guard(setup, tmp_path, monkeypatch, wire):
    raw = completed() if wire == "responses" else chat()
    r, server, _, _ = setup([(200, {}, raw)], wire=wire)
    monkeypatch.setenv("R17A_SYNTHETIC_AUTH", "Bearer synthetic")
    d = CORE["make"](tmp_path, r)
    d.guard = Guard(["R17A_SYNTHETIC_AUTH"])
    CORE["start"](d, tmp_path)
    body = dict(CORE["TITLE"], stream=True, stream_options={"include_usage": True}, custom="kept")
    body["input"] = [{"type": "message", "role": "user", "content": "hello"}]
    try:
        assert CORE["post"](d, f"/aux/title_generation/v1/{'responses' if wire == 'responses' else 'chat/completions'}", body)[0] == 200
    finally:
        d.close()
    request = server.seen[0]
    assert request["headers"]["Authorization"] == "Bearer synthetic"
    assert request["headers"]["Content-Type"] == "application/json"
    assert request["headers"]["Accept"] == ("text/event-stream" if wire == "responses" else "application/json")
    assert request["body"]["model"] == "probe-model" and request["body"]["custom"] == "kept"
    assert request["body"]["stream"] is (wire == "responses")
    if wire == "responses":
        assert request["body"]["input"][0]["content"] == [{"type": "input_text", "text": "hello"}]
    else:
        assert "stream_options" not in request["body"]
    diag = CORE["records"](tmp_path)[0]["upstream"][0]["diagnostics"][0]
    assert diag["sent_sha256"] == sha256(request["raw"]).hexdigest()


def test_redirect_not_followed(setup):
    _, target, _, _ = setup()
    r, server, _, _ = setup([(302, {"Location": target.url}, b"redirect")])
    reply = r.respond(call())
    assert reply.status == 503 and tries(reply)[0]["category"] == "other"
    assert len(server.seen) == 1 and target.seen == []


def test_unsupported_and_unknown_are_unsent(setup):
    r, server, _, _ = setup()
    for wire in ("responses_compact", "embeddings", "chat"):
        reply = r.respond(call(wire))
        assert reply.served == "live_unsupported" and tries(reply)[0]["sent"] is False
    assert r.respond(call(model="unknown")).served == "live_no_upstream"
    assert server.seen == []


def test_response_items_and_chat_tools(setup):
    raw = frames({"type": "response.output_text.delta", "delta": "ignored"},
                 {"type": "response.output_item.done", "item": {"type": "message", "content": [
                     {"type": "output_text", "text": "first"}, {"type": "output_text", "text": " second"}]}},
                 {"type": "response.output_item.done", "item": {"type": "function_call", "name": "tool", "arguments": {}}},
                 {"type": "response.output_item.done", "item": {"type": "reasoning"}},
                 {"type": "response.completed", "response": {"model": "probe-model"}})
    r, _, _, _ = setup([(200, {}, raw)])
    reply = r.respond(call())
    assert reply.text == "first second" and reply.tool_calls == ({"name": "tool", "arguments": "{}"},)
    assert tries(reply)[0]["n_dropped_items"] == 1
    raw = json.dumps({"model": "probe-model", "choices": [{"message": {"content": None, "tool_calls": [
        {"function": {"name": "tool", "arguments": "{}"}}]}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 100, "cost": 1.5}}).encode()
    r, _, _, _ = setup([(200, {}, raw)], wire="chat")
    reply = r.respond(call("chat", body={"max_tokens": 50}))
    assert reply.status == 200 and reply.text == "" and reply.tool_calls == ({"name": "tool", "arguments": "{}"},)
    assert tries(reply)[0]["reserved"] == 20 and tries(reply)[0]["charged"] == 40


def test_auth_exception_and_corrupt_spend_never_raise(setup):
    r, server, _, up = setup()

    def auth():
        raise RuntimeError("synthetic auth failure")

    r.auth = auth
    reply = r.respond(call())
    assert reply.served == "live_stopped" and r.state()["stop_reason"] == "responder_error:runtimeerror"
    assert tries(reply)[0]["charged"] == 0 and server.seen == []
    assert json.loads(up.spend.path.read_bytes())["open"] == {}
    r, server, _, up = setup()
    up.spend.path.write_text("broken")
    assert r.respond(call()).status == 503 and server.seen == []
    assert r.state()["stop_reason"] == "responder_error:jsondecodeerror"


def test_max_sends_latches_and_stop_first_reason(setup):
    r, server, _, up = setup([(200, {}, completed())])
    r.max_sends = 1
    assert r.respond(call()).status == 200
    assert r.respond(call()).served == r.respond(call()).served == "live_spend_stop"
    assert len(server.seen) == 1 and json.loads(up.spend.path.read_bytes())["next_id"] == 2
    r.stop("first")
    r.stop("second")
    assert r.state()["stop_reason"] == "first"


def test_upstream_validation(setup):
    r, _, _, up = setup()
    for changes in ({"name": "Bad"}, {"model": ""}, {"wire": "embeddings"}, {"base_url": "file:///fake"},
                    {"base_url": "http://user:pass@127.0.0.1"}, {"max_output_tokens": 0},
                    {"max_output_tokens": True}, {"timeout_s": 0}, {"price": Price(1, 1)}):
        with pytest.raises(ValueError):
            replace(up, **changes)
    with pytest.raises(ValueError):
        LiveResponder("account", r.pacer, r.auth, [up, up], r.holds)


def test_urllib_imports_only_in_forward():
    for path in (ROOT / "src/bicentennial/director/upstream").glob("*.py"):
        modules = [alias.name for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Import)
                   for alias in node.names]
        modules += [node.module or "" for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.ImportFrom)]
        if any(m.split(".")[0] == "urllib" for m in modules):
            assert path.name == "forward.py"
