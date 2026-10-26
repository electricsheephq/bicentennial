"""Offline tests for the S6b director (fake tokens, a loopback fake upstream). Run: python3.14 -m unittest test_s6b"""

import base64
import http.client
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import textwrap
import time
import unittest
import urllib.error
import urllib.request
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import sol_director as sd

LIFE = Path(__file__).resolve().parent.parent / "s6a" / "micro_life.json"
ACCT, EMAIL, RES, USER = "acct-FAKE-0000-test", "nobody-fake@example.invalid", "fake-region", "user-FAKE-0000"
MEM = {"type": "function", "name": "memory", "parameters": {"type": "object"}, "strict": False}
TODO = {"type": "function", "name": "todo", "parameters": {"type": "object"}, "strict": False}


def jwt(exp_in, n=0):
    seg = [base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode() for x in (
        {"alg": "none"}, {"exp": int(time.time() + exp_in), "iat": int(time.time()), "n": n, "email": EMAIL,
                          sd.AUTH_CLAIM: {"chatgpt_account_id": ACCT, "chatgpt_data_residency": RES, "chatgpt_user_id": USER}})]
    return ".".join(seg) + ".fake-signature"


def store(tmp, exp_in=3600):
    p = tmp / "auth.json"
    p.write_text(json.dumps({"OPENAI_API_KEY": None, "tokens": {"id_token": jwt(exp_in, 9), "access_token": jwt(exp_in),
                             "refresh_token": "rt-fake-0", "account_id": ACCT}, "last_refresh": "x"}, indent=2) + "\n")
    os.chmod(p, 0o600)
    return p


def sse(*items, usage=None, terminal="response.completed", echo=None):
    evs = [{"type": "response.created", "response": {"id": "r1", "safety_identifier": echo}}] * bool(echo) + [{"type": "response.output_item.done", "output_index": i, "item": it} for i, it in enumerate(items)]
    evs.append({"type": terminal, "response": {"id": "r1", "status": "completed", "model": "gpt-6.1-sol",
                                               "usage": usage or {"input_tokens": 7, "output_tokens": 3}}})
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in evs)


class Resp:  # an in-memory upstream stream: no socket
    status, headers = 200, {}

    def __init__(self, raw):
        self.raw = raw

    def read(self, size=-1):
        return self.raw if size < 0 else self.raw[:size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def frames(*evs) -> bytes:
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode() for e in evs)


AUX = {"instructions": sd.TITLE_SIG, "input": [{"type": "message", "role": "user", "content": "x"}]}
CALL = {"type": "function_call", "call_id": "call_up1", "name": "memory", "arguments": "{}", "status": "completed"}
MSG = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "a title"}]}


class Upstream(BaseHTTPRequestHandler):
    script, seen, log_message = [], [], lambda *a: None

    def do_POST(self):
        Upstream.seen.append(({k.lower(): v for k, v in self.headers.items()}, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
        code, data = Upstream.script.pop(0) if Upstream.script else (200, sse(MSG))
        self.send_response(code)
        self.send_header("Content-Type", "text/event-stream" if code == 200 else "application/json")
        self.send_header("x-codex-primary-used-percent", "42")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data[:len(data) // 2])
        self.wfile.flush()
        time.sleep(0.05)  # a stream in two parts: the director must buffer all of it
        self.wfile.write(data[len(data) // 2:])


def serve(test, handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
    return srv.server_address[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        Upstream.script, Upstream.seen = [], []

    def make(self, mode="live", post=None, exp_in=3600, clock=time.monotonic, sleep=None, **kw):
        os.environ["BICENTENNIAL_SOL_BASE_URL"] = f"http://127.0.0.1:{serve(self, Upstream)}/backend-api/codex"
        self.addCleanup(os.environ.pop, "BICENTENNIAL_SOL_BASE_URL", None)
        login = sd.Login(store(self.tmp, exp_in), "http://127.0.0.1:9/never", "client-fake", post=post or self.no_post)
        a = SimpleNamespace(**{"life": str(LIFE), "ledger_dir": str(self.tmp / "ledger"), "budget_file": str(
            self.tmp / "b.json"), "budget_cap": 50, "run": "t", "model": sd.MODEL, "mode": mode, "write_turns": True,
            "chars_per_token": 4.0, "context_length": 272000, "timeout": 10, "rate_per_min": 0} | kw)
        return sd.Director(a, login=login if mode == "live" else None, clock=clock, sleep=sleep)

    def no_post(self, *a):
        raise AssertionError("no refresh expected")

    def http(self, d, method, path, body=None, headers=None):
        port = serve(self, sd.make_handler(d))
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, headers=headers or {},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read()

    def records(self, kind=None):
        recs = [json.loads(x) for x in (self.tmp / "ledger" / "ledger.jsonl").read_text().splitlines()]
        return [r for r in recs if kind is None or r["type"] == kind]

    def turn(self, d, k=0, extra=()):
        return {"model": sd.MODEL, "instructions": "You are Hermes.", "stream": True, "store": False,
                "include": ["reasoning.encrypted_content"], "reasoning": {"effort": "medium", "summary": "auto"},
                "tools": [MEM, TODO], "tool_choice": "auto", "prompt_cache_key": "k",
                "input": [{"type": "message", "role": "user", "content": d.expected[k]["user"]}, *extra]}


class Clock:
    def __init__(self):
        self.now, self.lock, self.local, self.sleeps = 0.0, threading.Lock(), threading.local(), []

    def __call__(self):
        with self.lock:
            self.local.last = self.now
            return self.now

    def sleep(self, delay):
        assert delay > 0  # acquisition must sleep rather than spin
        with self.lock:
            self.sleeps.append(delay)
            self.now += delay


class Pacing(unittest.TestCase):
    def bucket(self, rate=180, burst=10, **kw):
        clock, stop = Clock(), threading.Event()
        return sd.Pacer(rate, burst, stop, clock, clock.sleep, **kw), clock, stop

    def assert_windows(self, times, bound):
        times = sorted(times)
        for start in times:  # every possible maximal half-open window starts at a send
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
            except Exception as e:  # noqa: BLE001 - capture thread failures for the owning test
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


class S6c(Base):
    def test_stop_releases_all_director_waiters(self):
        d = self.make(rate_per_min=1, burst=1)
        d.urlopen = lambda *a, **kw: Resp(sse(MSG))
        first = d.upstream(AUX, "aux", {})  # empty the bucket
        waiting = threading.Barrier(5)
        d.pacer.sleep = lambda delay: (waiting.wait(timeout=3), d.stop_event.wait(delay))
        calls, errors = [], []

        def worker():
            try:
                calls.append(d.upstream(AUX, "aux", {}))
            except Exception as e:  # noqa: BLE001 - capture thread failures for the owning test
                errors.append(type(e).__name__)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        waiting.wait(timeout=3)
        d.stop("test_stop")
        for t in threads:
            t.join(timeout=2)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual((errors, [u["category"] for u in calls]), ([], ["budget_or_stop"] * 4))
        self.assertEqual(json.loads((self.tmp / "b.json").read_text())["total"], 1)  # only the first send was charged
        self.assertAlmostEqual(d.summary()["pace_wait_ms"], first["pace_wait_ms"] + sum(u["pace_wait_ms"] for u in calls))
        self.assertGreater(d.summary()["pace_wait_ms"], 0)
        d.pacer.acquire = mock.Mock(side_effect=AssertionError("stopped director waited"))
        self.assertEqual(d.upstream(AUX, "aux", {})["category"], "budget_or_stop")

    def test_defaults_disabled_ledger_and_stub_bypass(self):
        d = self.make(mode="stub", rate_per_min=180, burst=1)
        d.pacer.acquire = mock.Mock(side_effect=AssertionError("stub paced"))
        self.assertEqual(d.upstream(AUX, "aux", {})["pace_wait_ms"], 0)
        self.assertFalse(self.records("pacing")[-1]["enabled"])
        d = self.make(rate_per_min=0)
        self.assertEqual(self.records("pacing")[-1]["rate_per_min"], 0)
        del d.a.rate_per_min
        default = sd.Director(d.a, login=d.login)
        self.assertEqual((default.pacer.rate * 60, default.pacer.burst), (180, 10))

    def test_invalid_request_stops_after_one_call_without_sentinel(self):
        import analyse_sol as an
        for code in (400, 404, 413, 422):
            self.tmp = Path(tempfile.mkdtemp())
            d, calls = self.make(), []

            def refuse(*a, code=code, calls=calls, **kw):
                calls.append(1)
                raise urllib.error.HTTPError("http://fake.invalid", code, "bad", {}, io.BytesIO(b"{}"))
            d.urlopen = refuse
            _, _, rec = d.handle(AUX, {})
            d.handle(AUX, {})
            self.assertEqual((calls, d.stop_reason), ([1], f"upstream_invalid_request_{code}"))
            self.assertFalse(d.login.sentinel.exists())
            with mock.patch.object(an, "load", return_value=([], [{"type": "request", "seq": 1, **rec}], {})), \
                    mock.patch.object(an, "run_measures", return_value={}):
                self.assertTrue(an.sol_load(self.tmp, "fake")["invalid_evidence"])

    def test_three_unparsed_calls_hold_breaker_and_stop_without_sentinel(self):
        d = self.make()
        d.urlopen = mock.Mock(return_value=Resp(b"data: {broken}\n\n" + sse(MSG)))
        d.failure_streak = 2
        for n in range(3):
            self.assertEqual(d.handle(AUX, {})[0], 503)
            self.assertEqual((d.failure_streak, d.stopped), (2, n == 2))
        d.handle(AUX, {})
        self.assertEqual((d.urlopen.call_count, d.stop_reason), (3, "upstream_unparsed_3_in_a_row"))
        self.assertFalse(d.login.sentinel.exists())

    def test_bounded_success_and_http_error_reads_never_parse_or_store_oversize(self):
        for code in (200, 503):
            self.tmp = Path(tempfile.mkdtemp())
            d = self.make()
            body = mock.Mock(wraps=io.BytesIO(b"PRIVATE-OVERSIZE" + b"x" * sd.MAX_BODY))
            if code == 200:
                response = Resp(b"")
                response.read = body.read
                d.urlopen = lambda *a, response=response, **kw: response
            else:
                d.urlopen = mock.Mock(side_effect=urllib.error.HTTPError("http://fake.invalid", code, "bad", {}, body))
            with mock.patch.object(d, "_scrub") as scrub, mock.patch.object(sd, "parse_sse") as parse:
                up = d.upstream(AUX, "aux", {})
            body.read.assert_called_once_with(sd.MAX_BODY + 1)
            scrub.assert_not_called()
            parse.assert_not_called()
            self.assertEqual((up["category"], up["forward"], up["ok"]), ("error:oversize", False, False))
            self.assertFalse({"raw", "resp", "events", "body_redacted", "body_shape"} & up.keys())
            for blob in (self.tmp / "ledger" / "blobs").rglob("*.zst"):
                self.assertNotIn(b"PRIVATE-OVERSIZE", zstd.decompress(blob.read_bytes()))

    def test_refresh_log_is_drained_once_by_two_threads(self):
        class RacyLog(list):
            gate = threading.Barrier(2)

            def __bool__(self):
                n = len(self)
                if n:
                    try:
                        self.gate.wait(timeout=0.5)
                    except threading.BrokenBarrierError:
                        pass
                return n > 0

        d, results, errors = self.make(), [], []
        d.login.log = RacyLog([{"type": "refresh", "status": 200}])
        d.login.token = lambda: "fake"
        d.urlopen = lambda *a, **kw: Resp(sse(MSG))

        def worker():
            try:
                results.append(d.upstream(AUX, "aux", {}))
            except Exception as e:  # noqa: BLE001 - capture thread failures for the owning test
                errors.append(type(e).__name__)
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=3)
        self.assertEqual((errors, len(results), len(self.records("refresh")), d.login.log), ([], 2, 1, []))

    def test_soak_exception_is_counted_and_releases_slot(self):
        import soak_sol
        d = self.make()
        d.upstream = mock.Mock(side_effect=ValueError("private exception text"))
        pays = [{"body": AUX, "kind": "write_turn", "hash": "fake"}]
        res = soak_sol.soak(d, pays, 1, 1, 1, pause=0, sample_s=0.01)
        self.assertEqual((res["sent"], res["inflight_final"], res["categories"]), (1, 0, {"director_exception": 1}))
        call = res["calls"][0]
        self.assertEqual((call["error"], call["unsent"]), ("ValueError", False))
        self.assertNotIn("private exception text", json.dumps(res) + json.dumps(self.records("soak")))

    def test_count_only_summary_tracks_recovery_overload_rate_and_breaker(self):
        clock = Clock()
        d = self.make(rate_per_min=180, burst=1, clock=clock, sleep=clock.sleep)
        overload = frames({"type": "error", "code": "server_overloaded"})
        script = iter([(503, b"{}"), (200, sse(MSG)), *[(200, overload)] * 4,
                       (429, b'{"error":"usage limit"}'), (529, b'{"error":"usage limit"}')])

        def send(*a, **kw):
            code, raw = next(script)
            if code != 200:
                raise urllib.error.HTTPError("http://fake.invalid", code, "bad", {}, io.BytesIO(raw))
            return Resp(raw)
        d.urlopen = send
        records = []
        with mock.patch.object(sd.time, "sleep"):
            for _ in range(4):
                records.append(d.handle(AUX, {})[2])
        summary = json.loads((self.tmp / "ledger" / "summary.json").read_text())
        self.assertEqual(summary["upstream_tries"], {"overload": 5, "ok": 1, "quota": 2})
        self.assertEqual(summary["retries"], {"overload": {"recovered": 1, "unrecovered": 3}})
        self.assertEqual((summary["in_stream_overloads"], summary["http_429s"], summary["breaker_stops"]), (4, 1, 1))
        self.assertEqual(summary["http_overloads"], {"502": 0, "503": 1, "529": 1})
        self.assertEqual(summary["requests_per_min"], {"p50": 4.5, "max": 8})
        self.assertAlmostEqual(summary["pace_wait_ms"], sum(u["pace_wait_ms"] for r in records for u in r["upstream"]))
        self.assertGreater(summary["pace_wait_ms"], 2000)
        self.assertNotIn("body", json.dumps(summary))
        self.assertNotIn("header", json.dumps(summary))

    def test_analysis_accepts_old_ledgers_without_pacing_fields(self):
        import analyse_sol as an
        old = [{"type": "request", "seq": 1, "role": "aux", "upstream": [
            {"kind": "aux", "ok": True, "category": None, "status": 200, "t_ms": 2}]}]
        with mock.patch.object(an, "load", return_value=([], old, {})), \
                mock.patch.object(an, "run_measures", return_value={}):
            res = an.sol_load(self.tmp, "old")
        self.assertEqual((res["pace_wait_ms"], res["paced_request_rate"], res["invalid_evidence"]),
                         (0, {"p50": 0, "max": 0}, False))


class Fix1(Base):
    def test_flat_soak_and_ramp_ledgers_reconcile(self):
        import verify
        d = self.make(budget_cap=100)
        d.budget.take("t", "refresh")
        d.ledger.append({"type": "refresh", "status": 200})
        for kind in ("soak", "ramp"):
            for _ in range(20):
                d.budget.take("t", kind)
                d.ledger.append({"type": kind, "ok": True})
        self.assertEqual(verify.check_ledger(self.tmp)["upstream_attempts"], 41)
        self.assertEqual(json.loads(d.budget.path.read_text())["by_run"]["t"], 41)

    def test_paced_plan_reserves_waiters_and_fits_ten_minutes(self):
        import soak_sol
        pays = [{"t_ms": 6240}]
        pl = soak_sol.plan(pays, 24, 600, 1900, rate=180, burst=10)
        self.assertEqual((pl["est_calls"], pl["fits"], pl["max_fitting_duration_s"]), (1834, True, 622))
        self.assertFalse(soak_sol.plan(pays, 24, 600, 1833, rate=180, burst=10)["fits"])
        self.assertEqual(soak_sol.plan(pays, 24, 600, 1900)["est_calls"], 2308)
        args = ["soak_sol.py", "--source", "fake", "--out", str(self.tmp), "--budget-file", str(self.tmp / "b"),
                "--duration", "600", "--max-calls", "1900", "--budget-cap", "2000", "--rate-per-min", "180",
                "--burst", "10", "--plan-only"]
        with mock.patch.object(sys, "argv", args), mock.patch.object(soak_sol, "payloads", return_value=pays), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as output, self.assertRaises(SystemExit) as ex:
            soak_sol.main()
        self.assertEqual(ex.exception.code, 0)
        self.assertEqual(json.loads(output.getvalue())["est_calls"], 1834)

    def test_soak_service_intervals_exclude_pace_waits_and_keep_old_files(self):
        import analyse_sol as an
        soak = {"calls": [{"ok": True, "t_start_s": 7, "t_ms": 5000, "t_done_s": 15}],
                "last_send_s": 10, "wall_s": 15, "inflight_mean": 2, "inflight_target": 2, "sustained": True,
                "n429": 0, "server_overloaded": 0, "sent": 1, "utc_start": 0, "utc_end": 15, "ended_by": "duration"}
        self.assertEqual(an.soak_level(soak)["C_effective"], 0.3)
        soak["calls"][0]["pace_wait_ms"] = 2000
        result = an.soak_level(soak)
        self.assertEqual(result["C_effective"], 0.1)
        self.assertEqual(result["inflight_sampled_mean_label"], "workers including pace waits")

    def test_backoff_checks_stop_each_second_and_keeps_sleep_seam(self):
        d = self.make()
        d.urlopen = mock.Mock(side_effect=urllib.error.HTTPError("http://fake.invalid", 429, "bad", {}, io.BytesIO(b"{}")))
        with mock.patch.object(sd.time, "sleep", side_effect=lambda _: d.stop("test_stop")) as sleep:
            d.handle(AUX, {})
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [1])
        self.assertEqual(d.urlopen.call_count, 1)

    def test_summary_io_failure_never_escapes_upstream(self):
        d = self.make()
        (self.tmp / "ledger" / "summary.tmp").mkdir()
        d.urlopen = mock.Mock(side_effect=urllib.error.HTTPError("http://fake.invalid", 400, "bad", {}, io.BytesIO(b"{}")))
        with mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            up = d.upstream(AUX, "aux", {})
        self.assertEqual((up["status"], d.stop_reason), (400, "upstream_invalid_request_400"))
        self.assertIn("summary_write_error:IsADirectoryError", err.getvalue())
        (self.tmp / "ledger" / "summary.tmp").rmdir()
        with mock.patch.object(sd.os, "replace", side_effect=OSError("private failure text")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(d.summary()["upstream_tries"], {"other": 1})
        self.assertNotIn("private failure text", err.getvalue())

    def test_unparsed_streak_survives_failed_tries_and_resets_on_forward(self):
        d = self.make()
        unparsed = b"data: {broken}\n\n" + sse(MSG)
        script = iter([unparsed, unparsed, sse(MSG), unparsed, 429, unparsed, 503, unparsed])

        def send(*a, **kw):
            raw = next(script)
            if isinstance(raw, int):
                raise urllib.error.HTTPError("http://fake.invalid", raw, "bad", {}, io.BytesIO(b"{}"))
            return Resp(raw)
        d.urlopen = mock.Mock(side_effect=send)
        with mock.patch.object(sd.time, "sleep"):
            for streak in (1, 2, 0, 1, 2, 3):
                d.handle(AUX, {})
                self.assertEqual(d.unparsed_streak, streak)
        self.assertEqual((d.urlopen.call_count, d.stop_reason), (8, "upstream_unparsed_3_in_a_row"))

    def refresh_shape(self, response, *, startup_only=False):
        import verify
        seed = self.make()
        login = sd.Login(store(self.tmp, exp_in=60), "http://127.0.0.1:9/never", "client-fake",
                         on_refresh=lambda: seed.budget.take("t", "refresh"))
        with mock.patch.object(sd.urllib.request, "urlopen", side_effect=response):
            d = sd.Director(seed.a, login=login)
        if not startup_only:
            _, _, rec = d.handle(AUX, {})
            d.ledger.append({"type": "request", **rec})
        self.assertTrue(d.stopped)
        self.assertEqual((verify.check_ledger(self.tmp)["upstream_attempts"],
                          json.loads(d.budget.path.read_text())["by_run"]["t"]), (1, 1))
        self.assertEqual(d.login.log, [])
        return self.records("refresh")[-1]

    def test_refresh_network_failure_reconciles(self):
        row = self.refresh_shape(urllib.error.URLError("private host"))
        self.assertEqual((row["status"], row["error"]), (-1, "refresh_error:URLError"))
        self.assertNotIn("private host", json.dumps(row))

    def test_refresh_non_json_response_reconciles(self):
        self.refresh_shape([Resp(b"<html>not json</html>")])

    def test_refresh_list_response_reconciles(self):
        self.refresh_shape([Resp(b"[]")])

    def test_startup_refresh_failure_drains_without_any_upstream_call(self):
        self.refresh_shape(urllib.error.URLError("private host"), startup_only=True)

    def test_summary_separates_stop_labels_from_failure_breaker(self):
        d = self.make()
        for reason, count in (("upstream_unparsed_3_in_a_row", 0), ("upstream_failures_3_in_a_row", 1),
                              ("upstream_invalid_request_400", 0), ("director_exit", 0)):
            d.stop_reason = ""
            d.stop(reason)
            result = json.loads((self.tmp / "ledger" / "summary.json").read_text())
            self.assertEqual(result["breaker_stops"], count)
            self.assertEqual(result["stop_reason"], reason)

    def test_sigterm_with_four_pace_waiters_keeps_budget_equal_to_ledger(self):
        import verify
        # R2-F1: every woken waiter must finish its release before the interpreter exits. Each child release is
        # slowed by 50 ms so that a missing grace wait leaves the file truncated or the reservations leaked.
        script = textwrap.dedent('''
            import sys, threading, time
            from pathlib import Path
            sys.path.insert(0, sys.argv[2])
            import sol_director as sd
            import test_s6b as t
            root = Path(sys.argv[1])
            real_director, real_server, real_flock = sd.Director, sd.ThreadingHTTPServer, sd.fcntl.flock
            def slow_flock(f, op):
                real_flock(f, op)
                if threading.current_thread() is not threading.main_thread():
                    time.sleep(0.05)
            sd.fcntl.flock = slow_flock
            def director(a):
                login = sd.Login(t.store(root), "http://127.0.0.1:9/never", "client-fake")
                d = real_director(a, login=login, urlopen=lambda *a, **kw: t.Resp(t.sse(t.MSG)))
                def sleep(delay):
                    with open(root / "waiting", "a") as f:
                        f.write(f"{threading.get_ident()}\\n")
                    d.stop_event.wait(delay)
                d.pacer.sleep = sleep
                return d
            def server(*a):
                srv = real_server(*a)
                (root / "port").write_text(str(srv.server_address[1]))
                return srv
            sd.Director, sd.ThreadingHTTPServer = director, server
            sys.argv = ["sol_director.py", "--port", "0", "--life", str(t.LIFE), "--ledger-dir", str(root / "ledger"),
                        "--budget-file", str(root / "b.json"), "--run", "t", "--rate-per-min", "1", "--burst", "1"]
            sd.os.environ["BICENTENNIAL_SOL_AUTH"] = str(root / "auth.json")
            sd.os.environ["BICENTENNIAL_SOL_BASE_URL"] = "http://127.0.0.1:9/never"
            sd.main()
        ''')
        proc = subprocess.Popen([sys.executable, "-B", "-c", script, str(self.tmp), str(Path(__file__).resolve().parent)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def waiting() -> int:
            path = self.tmp / "waiting"
            return len(set(path.read_text().split())) if path.exists() else 0

        def post():
            req = urllib.request.Request(f"http://127.0.0.1:{port}{sd.MOUNT}/responses", data=json.dumps(AUX).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    response.read()
            except OSError:
                pass
        try:
            deadline = time.monotonic() + 5
            while not (self.tmp / "port").exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            port = int((self.tmp / "port").read_text())
            post()
            waiters = [threading.Thread(target=post, daemon=True) for _ in range(4)]
            for w in waiters:
                w.start()
            deadline = time.monotonic() + 5
            while waiting() < 4 and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(waiting(), 4)
            proc.terminate()
            _, err = proc.communicate(timeout=10)
            for w in waiters:
                w.join(timeout=2)
            self.assertEqual(proc.returncode, 0, err)
            budget = json.loads((self.tmp / "b.json").read_text())  # parses: never left truncated
            self.assertEqual((budget["by_run"]["t"], verify.check_ledger(self.tmp)["upstream_attempts"]), (1, 1))
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()

    def test_sigterm_during_pace_wait_releases_budget_reservation(self):
        import verify
        # Reuse the verdict's two real HTTP calls and SIGTERM, exercising main() itself.
        script = textwrap.dedent('''
            import sys
            from pathlib import Path
            sys.path.insert(0, sys.argv[2])
            import sol_director as sd
            import test_s6b as t
            root = Path(sys.argv[1])
            real_director, real_server = sd.Director, sd.ThreadingHTTPServer
            def director(a):
                login = sd.Login(t.store(root), "http://127.0.0.1:9/never", "client-fake")
                d = real_director(a, login=login, urlopen=lambda *a, **kw: t.Resp(t.sse(t.MSG)))
                def sleep(delay):
                    (root / "waiting").write_text("ready")
                    d.stop_event.wait(delay)
                d.pacer.sleep = sleep
                return d
            def server(*a):
                srv = real_server(*a)
                (root / "port").write_text(str(srv.server_address[1]))
                return srv
            sd.Director, sd.ThreadingHTTPServer = director, server
            sys.argv = ["sol_director.py", "--port", "0", "--life", str(t.LIFE), "--ledger-dir", str(root / "ledger"),
                        "--budget-file", str(root / "b.json"), "--run", "t", "--rate-per-min", "1", "--burst", "1"]
            sd.os.environ["BICENTENNIAL_SOL_AUTH"] = str(root / "auth.json")
            sd.os.environ["BICENTENNIAL_SOL_BASE_URL"] = "http://127.0.0.1:9/never"
            sd.main()
        ''')
        proc = subprocess.Popen([sys.executable, "-B", "-c", script, str(self.tmp), str(Path(__file__).resolve().parent)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def await_file(name):
            deadline = time.monotonic() + 5
            while not (self.tmp / name).exists() and proc.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue((self.tmp / name).exists(), name)

        def post():
            req = urllib.request.Request(f"http://127.0.0.1:{port}{sd.MOUNT}/responses", data=json.dumps(AUX).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=5) as response:
                    response.read()
            except OSError:
                pass  # the waiting client's connection may close during process exit
        try:
            await_file("port")
            port = int((self.tmp / "port").read_text())
            post()
            waiter = threading.Thread(target=post, daemon=True)
            waiter.start()
            await_file("waiting")
            proc.terminate()
            _, err = proc.communicate(timeout=5)
            waiter.join(timeout=2)
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual((json.loads((self.tmp / "b.json").read_text())["by_run"]["t"],
                              verify.check_ledger(self.tmp)["upstream_attempts"]), (1, 1))
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.communicate(timeout=5)


class Login(Base):
    def test_refresh_rotation_lock_atomic_write(self):
        p, calls = store(self.tmp, exp_in=120), []  # within the 5-minute skew

        def post(url, fields):
            calls.append(fields["refresh_token"])
            time.sleep(0.1)
            return 200, {"access_token": jwt(3600, 1), "refresh_token": f"rt-fake-{len(calls)}", "id_token": jwt(3600, 2)}
        login = sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=post)
        out = []
        ts = [threading.Thread(target=lambda: out.append(login.token())) for _ in range(4)]
        [t.start() for t in ts], [t.join() for t in ts]
        saved = json.loads(p.read_text())
        self.assertEqual((calls, len(set(out)), saved["tokens"]["refresh_token"]), (["rt-fake-0"], 1, "rt-fake-1"))
        self.assertEqual(out[0], saved["tokens"]["access_token"])  # persisted before the new token is used
        self.assertTrue(p.read_text().startswith('{\n  "OPENAI_API_KEY": null') and p.read_text().endswith("}\n"))
        self.assertEqual((saved["tokens"]["account_id"], stat.S_IMODE(p.stat().st_mode)), (ACCT, 0o600))
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["auth.json", "auth.json.lock"])
        self.assertEqual(login.token(), out[0])  # fresh now: no second refresh
        self.assertEqual(login.log[0]["rotated"], True)

    def test_refresh_failure_stops_without_retry(self):
        for resp, reason in (((401, {}), "token_endpoint_401"), ((403, {}), "token_endpoint_403"),
                             ((500, {}), "refresh_failed_500"),
                             ((200, {"access_token": "x", "refresh_token": "rt-fake-0"}), "refresh_no_new_refresh_token"),
                             ((200, {"access_token": "x"}), "refresh_no_new_refresh_token")):
            self.tmp = Path(tempfile.mkdtemp())
            calls = []
            d = self.make(post=lambda u, f, r=resp: (calls.append(1), r)[1], exp_in=60)
            before = json.loads((self.tmp / "auth.json").read_text())["tokens"]
            self.assertEqual((d.stopped, d.stop_reason, len(calls)), (True, reason, 1))
            self.assertEqual(json.loads((self.tmp / "auth.json").read_text())["tokens"], before)
            _, _, rec = d.handle(self.turn(d), {})  # stopped: no upstream call, no second refresh
            self.assertEqual((len(Upstream.seen), len(calls), rec["write_turn_failed"]), (0, 1, "budget_or_stop"))

    def test_refresh_failure_is_latched_for_queued_callers(self):
        calls = []
        d = self.make(post=lambda u, f: (calls.append(f["refresh_token"]), time.sleep(0.2), (401, {}))[2])
        store(self.tmp, exp_in=60)  # expiring now: both callers need a refresh
        out = []
        ts = [threading.Thread(target=lambda: out.append(d.handle(AUX, {})[0])) for _ in range(2)]
        [t.start() for t in ts], [t.join() for t in ts]
        self.assertEqual((calls, out, d.stop_reason, len(Upstream.seen)), (["rt-fake-0"], [503, 503],
                                                                          "token_endpoint_401", 0))
        with self.assertRaisesRegex(sd.Stop, "token_endpoint_401"):  # the login itself refuses, not only the flag
            d.login.token()
        self.assertEqual(calls, ["rt-fake-0"])

    def test_write_back_failure_stops_before_the_refresh_token_is_reused(self):
        calls, real = [], os.replace
        d = self.make(post=lambda u, f: (calls.append(f["refresh_token"]), (200, {
            "access_token": jwt(3600, 1), "refresh_token": f"rt-fake-{len(calls)}"}))[1])
        store(self.tmp, exp_in=60)

        def replace(src, dst):
            if Path(dst).name == "auth.json":
                raise OSError(28, "No space left on device")
            return real(src, dst)
        with mock.patch.object(sd.os, "replace", side_effect=replace):
            codes = [d.handle(AUX, {})[0] for _ in range(2)]
        self.assertEqual((calls, codes, d.stop_reason, len(Upstream.seen)), (["rt-fake-0"], [503, 503],
                                                                            "login_error:OSError", 0))
        with self.assertRaises(sd.Stop):
            d.login.token()
        self.assertEqual(calls, ["rt-fake-0"])

    def test_any_exception_after_rotation_is_latched_by_class_only(self):
        p, calls, real = store(self.tmp, exp_in=60), [], json.dumps
        login = sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=lambda u, f: (calls.append(
            f["refresh_token"]), (200, {"access_token": jwt(3600, 1), "refresh_token": "rt-fake-1"}))[1])

        def dumps(obj, *a, **kw):  # an allocation failure while the rotated store is serialised
            if isinstance(obj, dict) and "tokens" in obj:
                raise MemoryError("rt-fake-1 would be in a message")
            return real(obj, *a, **kw)
        with mock.patch.object(sd.json, "dumps", side_effect=dumps):
            for _ in range(2):
                with self.assertRaisesRegex(sd.Stop, "^login_error:MemoryError$"):
                    login.token()
        self.assertEqual((calls, login.dead), (["rt-fake-0"], "login_error:MemoryError"))
        self.assertEqual(json.loads(login.sentinel.read_text())["reason"], "login_error:MemoryError")

    def test_a_login_stop_is_persisted_for_the_next_process(self):
        p, calls = store(self.tmp, exp_in=60), []
        post = lambda u, f: (calls.append(f["refresh_token"]), (401, {}))[1]
        with self.assertRaisesRegex(sd.Stop, "token_endpoint_401"):
            sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=post).token()
        sentinel = p.with_name("auth.json.stopped")
        saved = json.loads(sentinel.read_text())
        self.assertEqual((sorted(saved), saved["reason"], stat.S_IMODE(sentinel.stat().st_mode)),
                         (["reason", "t"], "token_endpoint_401", 0o600))
        self.assertTrue(saved["t"].endswith("Z"))
        self.assertNotIn("rt-fake", sentinel.read_text())
        second = sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=post)  # a new process, same store
        with self.assertRaisesRegex(sd.Stop, "^login_latched:token_endpoint_401$"):
            second.token()
        store(self.tmp, exp_in=3600)  # even with a fresh access token: no use until the owner clears it
        with self.assertRaises(sd.Stop):
            sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=post).token()
        self.assertEqual(calls, ["rt-fake-0"])


class Wire(Base):
    def test_header_rebuild_and_no_secret_anywhere(self):
        d = self.make()
        title = {"model": sd.MODEL, "instructions": sd.TITLE_SIG + " Rules...", "stream": True, "store": False,
                 "input": [{"type": "message", "role": "user", "content": d.expected[0]["user"]}]}
        hin = {"Authorization": "Bearer " + sd.placeholder_auth()["providers"]["openai-codex"]["tokens"]["access_token"],
               "ChatGPT-Account-ID": "placeholder-account", "session_id": "sess-1", "x-client-request-id": "k"}
        Upstream.script = [(200, sse(MSG, echo=USER))]  # the backend echoes the user id (safety_identifier)
        code, out = self.http(d, "POST", sd.MOUNT + "/responses", title, hin)
        h, wire = Upstream.seen[0]
        self.assertEqual((code, out), (200, sse(MSG, echo="redacted-by-director")))
        real = json.loads((self.tmp / "auth.json").read_text())["tokens"]["access_token"]
        self.assertEqual((h["authorization"], h["chatgpt-account-id"], h["x-openai-internal-codex-residency"]),
                         ("Bearer " + real, ACCT, RES))
        self.assertEqual((h["originator"], h["session_id"], h["x-client-request-id"]), ("hermes-agent", "sess-1", "k"))
        self.assertEqual(wire["input"][0]["content"], [{"type": "input_text", "text": d.expected[0]["user"]}])
        rec = self.records("request")[0]
        self.assertEqual((rec["role"], rec["subrole"], rec["upstream"][0]["limit_headers"]),
                         ("aux", "title_generation", {"x-codex-primary-used-percent": "42"}))
        self.assertEqual((rec["upstream"][0]["scrubbed"], set(rec["in_headers"]) & sd.IDENTITY_NAMES,
                          "session_id" in rec["in_headers"]), (1, set(), True))
        needles = [n.encode() for n in (real, "rt-fake-0", ACCT, EMAIL, RES, USER, *sd.IDENTITY_NAMES)]
        for f in (self.tmp / "ledger").rglob("*"):
            if f.is_file():
                data = zstd.decompress(f.read_bytes()) if f.suffix == ".zst" else f.read_bytes()
                self.assertFalse([n for n in needles if n in data], f.name)

    def test_guard_refuses_a_secret(self):
        d = self.make()
        with mock.patch.object(sd.os, "_exit", side_effect=SystemExit(3)), self.assertRaises(SystemExit), \
                mock.patch.object(sd.os, "write") as w:
            d.ledger.append({"note": "acct " + ACCT})
        self.assertEqual(w.call_args[0][1], b"FATAL: tokens.account_id reached a ledger write at ['note']; stopping\n")
        self.assertEqual(sd._where(json.dumps({"sse": sse(dict(MSG, user=ACCT)).decode()}).encode(), ACCT),
                         ["sse", "sse:response.output_item.done", "item", "user"])
        hits = sd.scan(d.login, [str(self.tmp)])["hits"]  # the store itself holds every needle; the ledger none
        self.assertEqual((hits["tokens.access_token"], hits["tokens.account_id"]), (1, 1))
        self.assertFalse(sd.scan(d.login, [str(self.tmp / "ledger")])["hits"])

    def test_sse_buffered_then_replayed_with_usage(self):
        d = self.make()
        Upstream.script = [(200, sse(CALL, usage={"input_tokens": 11, "output_tokens": 5}))]
        probe = d.expected.index(next(t for t in d.expected if t["kind"] == "probe"))
        d.cursor = probe
        code, out, rec = d.handle(self.turn(d, probe), {})
        self.assertEqual((code, out, rec["served"]), (200, sse(CALL, usage={"input_tokens": 11, "output_tokens": 5}),
                                                      "forward"))
        self.assertEqual((rec["role"], rec["upstream"][0]["usage"]["input_tokens"]), ("probe_main", 11))
        nxt = self.turn(d, probe, [CALL, {"type": "function_call_output", "call_id": "call_up1", "output": "ok"}])
        self.assertEqual(d.classify(nxt)[:2], ("probe_main", "tool_results"))


    def test_crlf_and_cr_event_boundaries(self):
        lf = sse(CALL, MSG)
        self.assertEqual(len(sd.parse_sse(lf)), 3)
        for eol in (b"\r\n", b"\r"):
            self.assertEqual(sd.parse_sse(lf.replace(b"\n", eol)), sd.parse_sse(lf))

    def test_a_raw_line_separator_inside_a_json_string(self):
        ev = {"type": "response.output_item.done", "item": dict(CALL, arguments='{"content": "a\u2028b\u2029c\x85d"}')}
        raw = f"event: {ev['type']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n".encode()
        self.assertEqual(sd.parse_sse(raw), [ev])

    def test_sse_auth_error_in_an_http_200_is_never_replayed(self):
        words = "Unauthorized: invalid token, token expired, access denied, invalid_api_key 401 403"
        model_text = [{"type": "response.output_text.delta", "delta": words},  # model output: never searched
                      {"type": "response.function_call_arguments.delta", "delta": words},
                      {"type": "response.output_item.done", "item": dict(CALL, arguments=json.dumps({"content": words}))},
                      {"type": "response.completed", "response": {"status": "completed", "output": [dict(MSG, content=[
                          {"type": "output_text", "text": words}])]}}]
        cases = [({"type": "error", "code": "invalid_api_key", "message": "Incorrect API key provided"}, True),
                 ({"type": "error", "error": {"code": "token_expired", "message": "Provided token is expired"}}, True),
                 ({"type": "error", "status": 403, "message": "Forbidden"}, True),
                 ({"type": "response.failed", "response": {"status": "failed", "error": {
                     "code": "invalid_api_key", "message": "Your authentication token is invalid"}}}, True),
                 ({"type": "error", "message": "Unauthorized"}, True),  # message only, as Hermes reads it
                 ({"type": "error", "message": "Your authentication token is invalid"}, True),
                 ({"type": "error", "error": {"message": "Unauthorized"}}, True),
                 ({"type": "error", "code": "gateway_auth_failed", "message": "Access denied"}, True),
                 ({"type": "error", "code": "invalid_request_error", "message": "Failed to extract accountid from token"},
                  True),
                 ({"type": "response.failed", "response": {"status": "failed", "error": {
                     "code": "unknown_error", "message": "Invalid token: access denied"}}}, True),
                 ({"type": "response.in_progress", "error": {"message": "Token revoked"}}, True),  # any truthy error
                 ({"type": "error", "detail": "Failed to extract accountid from token"}, True),
                 ({"type": "error", "code": "server_error", "message": "An error occurred"}, False),
                 ({"type": "error", "code": "server_is_overloaded", "message": "Our servers are overloaded"}, False),
                 ({"type": "response.failed", "response": {"status": "failed", "error": {  # auth words: stop
                     "code": "server_is_overloaded", "message": "Unauthorized retries are overloaded"}}}, True),
                 ({"type": "error", "message": "Unauthorized: invalid token for credit endpoint"}, True),
                 ({"type": "error", "status": 403, "error": {"code": "server_is_overloaded"}}, True),
                 ({"type": "error", "code": "insufficient_quota", "message": "You exceeded your current quota"}, False),
                 (model_text, False)]
        for ev, auth in cases:
            self.tmp = Path(tempfile.mkdtemp())
            d, n = self.make(), []
            raw = frames(*(ev if isinstance(ev, list) else [ev]))
            d.urlopen = lambda req, timeout, n=n, raw=raw: (n.append(1), Resp(raw))[1]
            with mock.patch.object(sd.time, "sleep"):
                code, out, rec = d.handle(AUX, {})
            self.assertEqual((rec["upstream"][0]["category"] == "auth_sse", d.stopped), (auth, auth), ev)
            self.assertEqual((self.tmp / "auth.json.stopped").exists(), auth)  # a later process refuses too
            if ev is not model_text:  # every error object: a neutral 503, never the stream
                self.assertEqual((code, json.loads(out)), (503, sd.NEUTRAL_503), ev)
            if auth:
                self.assertEqual((d.stop_reason, len(n)), ("upstream_sse_auth", 1))
                d.handle(AUX, {})  # stopped: no further upstream call
                self.assertEqual(len(n), 1)
        self.assertEqual((code, out), (200, raw))  # model text: forwarded byte for byte

    def test_an_incomplete_response_is_classified_without_its_output_text(self):
        d = self.make(write_turns=False)
        inc = {"type": "response.incomplete", "response": {"id": "r1", "status": "incomplete", "incomplete_details": {
            "reason": "max_output_tokens"}, "output": [dict(MSG, content=[{"type": "output_text", "text":
                                                               "they hit their quota and the billing limit"}])]}}
        Upstream.script = [(200, f"event: {inc['type']}\ndata: {json.dumps(inc)}\n\n".encode())]
        up = d.upstream(AUX, "aux", {})
        self.assertEqual((up["ok"], up["forward"], up["category"], d.stopped), (False, True, "other", False))

    def test_a_refusal_echoing_identity_headers_persists_no_value(self):
        d = self.make()
        echo = json.dumps({"error": {"type": "invalid_request_error", "code": "missing_header", "param": "Authorization",
                                     "message": f"Missing Authorization or ChatGPT-Account-ID header (account {ACCT}, "
                                                f"X-OpenAI-Internal-Codex-Residency: {RES})"}}).encode()
        Upstream.script = [(400, echo), (200, sse(MSG, echo=RES))]
        title = dict(AUX, input=[{"type": "message", "role": "user", "content": "x"}])
        self.assertEqual([self.http(d, "POST", sd.MOUNT + "/responses", title)[0] for _ in range(2)], [503, 503])
        self.assertEqual((d.stop_reason, len(Upstream.seen)), ("upstream_invalid_request_400", 1))
        real = json.loads((self.tmp / "auth.json").read_text())["tokens"]["access_token"]
        self.assertEqual(self.records("request")[0]["upstream"][0]["error_obj"]["param"], "Authorization")  # a name
        needles = [n.encode() for n in (real, "rt-fake-0", ACCT, EMAIL, USER)]  # residency is not a needle
        files = [f for f in (self.tmp / "ledger").rglob("*") if f.is_file()]
        self.assertGreater(len(files), 3)
        for f in files:
            data = zstd.decompress(f.read_bytes()) if f.suffix == ".zst" else f.read_bytes()
            self.assertFalse([n for n in needles if n in data], f.name)


class Roles(Base):
    def test_each_request_kind(self):
        d = self.make(mode="stub", write_turns=False)
        t0 = self.turn(d)
        cases = [
            (dict(t0, instructions=sd.TITLE_SIG + " x", tools=[]), ("aux", "title_generation")),
            ({"input": [{"type": "message", "role": "user", "content": sd.SUMMARY_SIG + ". Turns: ..."}]},
             ("summariser", "compression")),
            (t0, ("replay_main", "cursor")),
            (t0, ("replay_main", "retry")),
            (self.turn(d, 0, [{"type": "message", "role": "user", "content": sd.REVIEW_PREFIX + " save"}]),
             ("aux", "background_review")),
            ({"input": [{"type": "message", "role": "user", "content": "something else"}]}, ("unknown", "")),
        ]
        for body, want in cases:
            code, out, rec = d.handle(body, {})
            self.assertEqual((rec["role"], rec["subrole"]), want)
            self.assertEqual(code, 400 if want[0] == "unknown" else 200)
            self.assertTrue(code == 400 or out.startswith(b"event: response.created"))

    def test_write_turn_suffix_readback_and_tool_results(self):
        d = self.make(mode="stub")
        Upstream.script = []
        body = self.turn(d)
        body["input"].insert(0, {"type": "message", "role": "assistant", "content": "earlier"})  # 2 items + suffix
        code, out, rec = d.handle(body, {})
        self.assertEqual((rec["served"], rec["write_calls"], rec["write_turn_readback"]), ("write_tool_calls", 1, True))
        wire = json.loads(zstd.decompress((self.tmp / "ledger" / "blobs" / rec["upstream"][0]["req"][:2] / (
            rec["upstream"][0]["req"] + ".json.zst")).read_bytes()))
        self.assertEqual((wire["input"][-1], wire["tools"], wire["reasoning"]), (sd.SUFFIX_ITEM, [MEM], body["reasoning"]))
        self.assertTrue(sd.readback(body, wire, sd.MODEL))
        for bad in ({**wire, "include": []}, {k: v for k, v in wire.items() if k != "include"}, {**wire, "model": "x"},
                    {**wire, "input": wire["input"][:-1] + [{**sd.SUFFIX_ITEM, "role": "developer"}]},
                    {**wire, "input": [{**wire["input"][0], "content": [{"type": "input_text", "text": "edited"}]}]
                     + wire["input"][1:]}, {**wire, "tools": [MEM, TODO]}):
            self.assertFalse(sd.readback(body, bad, sd.MODEL))
        cid = [e["item"]["call_id"] for e in sd.parse_sse(out) if e.get("item", {}).get("type") == "function_call"]
        nxt = dict(body, input=body["input"] + [{"type": "function_call", "call_id": cid[0], "name": "memory",
                                                "arguments": "{}"},
                                               {"type": "function_call_output", "call_id": cid[0], "output": "saved"}])
        _, out, rec = d.handle(nxt, {})
        self.assertEqual((rec["role"], rec["served"], cid), ("write_turn", "script", ["bcw00001"]))
        self.assertIn(d.expected[0]["assistant"], out.decode())

    def test_typed_parts_keep_content_order_and_role(self):
        items = [{"type": "message", "role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
                 {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "u2"}]},
                 CALL, {"type": "function_call_output", "call_id": "c", "output": "plain string stays"},
                 {"type": "message", "role": "developer", "content": ""}]
        out = sd.typed(items)
        self.assertEqual([o.get("role") for o in out], [i.get("role") for i in items])
        self.assertEqual(out[0]["content"], [{"type": "input_text", "text": "u1"}])
        self.assertEqual(out[1]["content"], [{"type": "output_text", "text": "a1"}])
        self.assertEqual(out[2:5], items[2:5])
        self.assertEqual(out[5]["content"], [{"type": "input_text", "text": ""}])
        self.assertEqual(sd.typed("hi"), [{"type": "message", "role": "user", "content": [{"type": "input_text",
                                                                                            "text": "hi"}]}])
        self.assertTrue(all(map(sd._untyped_eq, out, items)))


class Serving(Base):
    def test_record_survives_hangup_and_send_error(self):  # S6a's fix, ported
        for fail_send in (False, True):
            self.tmp, Upstream.seen = Path(tempfile.mkdtemp()), []
            d = self.make(write_turns=False)
            real = d.upstream
            d.upstream = lambda *a: (time.sleep(0.4), real(*a))[1]

            class H(sd.make_handler(d)):
                def _send(self, code, data, ctype="application/json"):
                    if fail_send:
                        raise BrokenPipeError(32, "Broken pipe")
                    return super()._send(code, data, ctype)
            port = serve(self, H)
            body = json.dumps({"instructions": sd.TITLE_SIG, "input": [{"role": "user", "content": "x"}]}).encode()
            s = socket.create_connection(("127.0.0.1", port))
            s.sendall(b"POST %s/responses HTTP/1.1\r\nContent-Length: %d\r\n\r\n%s" % (sd.MOUNT.encode(), len(body), body))
            s.close()
            time.sleep(1.0)
            reqs, errs = self.records("request"), self.records("send_error")
            self.assertEqual((len(reqs), reqs[0]["client_disconnected"], len(Upstream.seen)), (1, True, 1))
            seqs = [e["request_seq"] for e in errs]  # a natural hang-up may also fail the real send
            self.assertEqual(seqs, [reqs[0]["seq"]]) if fail_send else self.assertIn(seqs, ([], [reqs[0]["seq"]]))

    def test_unknown_paths_fail_closed_and_metadata_is_local(self):
        d = self.make()
        for method, path in (("GET", "/v1/models"), ("POST", "/main/v1/chat/completions"),
                             ("POST", sd.MOUNT + "/responses/compact"), ("GET", sd.MOUNT + "/other")):
            self.assertEqual(self.http(d, method, path, {} if method == "POST" else None)[0], 404)
        self.assertEqual(self.http(d, "GET", sd.MOUNT + "/api/tags")[0], 404)
        code, out = self.http(d, "GET", sd.MOUNT + "/models?client_version=99.0.0")
        self.assertEqual((code, json.loads(out)["models"][0]["slug"]), (200, "gpt-6.1-sol"))
        code, out = self.http(d, "GET", "/backend-api/wham/usage")
        self.assertEqual((code, json.loads(out)["rate_limit"]), (200, None))
        self.assertEqual([(r["role"], r["subrole"]) for r in self.records("request")],
                         [("unknown", "path_refused")] * 4 + [("metadata", "local_server_probe"), ("metadata", "catalog"),
                                                               ("metadata", "usage_probe")])
        self.assertEqual((Upstream.seen, (self.tmp / "b.json").exists()), ([], False))

    def test_no_synthesised_429(self):
        quota = json.dumps({"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached",
                                      "resets_in_seconds": 999}}).encode()
        rate = json.dumps({"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"}}).encode()
        d = self.make()
        aux = {"instructions": sd.TITLE_SIG, "input": [{"type": "message", "role": "user", "content": "x"}]}
        with mock.patch.object(sd.time, "sleep"):
            Upstream.script = [(429, rate), (429, rate), (200, sse(MSG))]  # absorbed with backoff
            code, out, rec = d.handle(aux, {})
            self.assertEqual((code, [u["category"] for u in rec["upstream"]]), (200, ["rate", "rate", None]))
            self.assertEqual([u["retry_wait_s"] for u in rec["upstream"]], [5, 15, 0])  # each wait is recorded
            Upstream.script = [(429, rate)] * 4  # still refused after the backoff: a neutral 503, never a 429
            code, out, rec = d.handle(aux, {})
            self.assertEqual((code, len(rec["upstream"]), rec["served"]), (503, 4, "neutral_503"))
            Upstream.script = [(200, sse(MSG))]
            d.handle(aux, {})  # a success ends the streak
            for i in range(3):  # usage limit: no retry; the third unrecovered failure in a row stops the director
                Upstream.script = [(429, quota)]
                code, out, rec = d.handle(aux, {})
                self.assertEqual((code, rec["upstream"][0]["category"], d.stopped), (503, "quota", i == 2))
                self.assertNotRegex(out.decode().lower(), r"quota|usage|limit|rate|429|billing")
        self.assertEqual(d.stop_reason, "upstream_failures_3_in_a_row")
        self.assertEqual(rec["upstream"][0]["body_shape"]["error"], {"type": "usage_limit_reached", "message": "str",
                                                                     "resets_in_seconds": "int"})
        d2 = self.make()  # a 401 stops at once: no retry, no refresh, no second credential
        Upstream.script = [(401, b'{"error": {"message": "expired"}}')]
        code, out, rec = d2.handle(aux, {})
        self.assertEqual((code, d2.stop_reason, len(rec["upstream"])), (503, "upstream_401", 1))
        with self.assertRaisesRegex(sd.Stop, "^login_latched:upstream_401$"):  # the next process refuses too
            sd.Login(self.tmp / "auth.json", "http://127.0.0.1:9/never", "client-fake", post=self.no_post).token()


class Ramp(Base):
    def test_in_stream_overload_is_retryable_behind_a_long_echo(self):
        d = self.make(write_turns=False)
        failed = {"type": "response.failed", "response": {"id": "r1", "status": "failed", "tools": [MEM] * 40,
                  "instructions": "x" * 3000, "error": {"type": "service_unavailable_error", "code": "server_is_overloaded"}}}
        Upstream.script = [(200, f"event: response.failed\ndata: {json.dumps(failed)}\n\n".encode())]
        up = d.upstream(AUX, "aux", {})
        self.assertEqual((up["ok"], up["category"]), (False, "overload"))
        self.assertIn(up["category"], sd.RETRYABLE)

    def test_an_unsent_call_does_not_break_the_quota_streak(self):  # the race behind the intermittent stop
        from ramp import run_level
        seq = iter([{"category": "quota"}, {"category": "quota"}, {"category": "budget_or_stop", "unsent": True},
                    {"category": "quota"}])
        state = {"quota_streak": 0, "quota_stop": False}
        for _ in range(2):  # level 1 twice, one worker each: a fixed arrival order; the streak spans levels
            run_level(1, lambda i: next(seq), lambda: True, state)
        self.assertEqual((state["quota_streak"], state["quota_stop"]), (3, True))

    def test_ramp_never_retries_and_stops_on_quota(self):
        import ramp_sol
        quota = json.dumps({"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached"}}).encode()
        d, state = self.make(), {"quota_streak": 0, "quota_stop": False}
        Upstream.script = [(429, b'{"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"}}')]
        lv = ramp_sol.level(d, 4, state)  # one 429 among 8: complete but not sustained, and never retried
        self.assertEqual((lv["sent"], lv["n429"], lv["sustained"], len(Upstream.seen)), (8, 1, False, 8))
        self.assertEqual(lv["quota_headers_last"]["x-codex-primary-used-percent"], "42")
        Upstream.script = [(429, quota)] * 8
        lv = ramp_sol.level(d, 4, state)  # 3 quota refusals in a row stop the calls not yet started (the ramp's
        # own stop: the director's breaker guards the Hermes path, upstream_retry, which the ramp does not use)
        self.assertTrue(state["quota_stop"] and 3 <= lv["sent"] < 8)
        self.assertEqual((len(Upstream.seen), len(self.records("ramp"))), (8 + lv["sent"], 8 + lv["sent"]))
        self.assertNotIn(ACCT, (self.tmp / "ledger" / "ledger.jsonl").read_text())


class Soak(Base):
    QUOTA = json.dumps({"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached"}}).encode()

    def source(self, d):  # a finished run's ledger: forwarded write-turn and compaction blobs, plus noise
        led = sd.Ledger(self.tmp / "src" / "ledger", d.guard)
        bodies = [dict(self.turn(d, k), input=sd.typed(self.turn(d, k)["input"] + [sd.SUFFIX_ITEM]), tools=[MEM])
                  for k in range(3)]  # as the director stores a forwarded body: typed parts
        comp = {"model": sd.MODEL, "instructions": "You are Hermes.", "stream": True, "store": False,
                "reasoning": {"effort": "medium"}, "input": [{"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": sd.SUMMARY_SIG + " the turns so far"}]}]}
        ups = [{"kind": "write_turn", "ok": True, "req": led.blob(b), "t_ms": 40} for b in bodies]
        ups += [{"kind": "summariser", "ok": True, "req": led.blob(comp), "t_ms": 200},
                {"kind": "aux", "ok": True, "req": led.blob(AUX), "t_ms": 10},  # not a soak payload
                {"kind": "write_turn", "ok": False, "req": led.blob({"x": 1}), "t_ms": 5}]  # a failed call: skipped
        for u in ups:
            led.append({"type": "request", "upstream": [u]})
        return self.tmp / "src", bodies + [comp]

    def test_holds_inflight_for_the_window_with_the_source_mix(self):
        import soak_sol
        d = self.make(write_turns=False, budget_cap=2000, run="soak")
        src, bodies = self.source(d)
        pays = soak_sol.payloads(src)
        real = d.upstream  # a call of 0.3 s, so a slot's ledger write is short against its call
        d.upstream = lambda *a: (time.sleep(0.3), real(*a))[1]
        self.assertEqual(([p["kind"] for p in pays], [p["body"] for p in pays]),
                         (["write_turn"] * 3 + ["summariser"], bodies))
        res = soak_sol.soak(d, pays, inflight=4, duration=1.5, ceiling=1000, sample_s=0.1)
        self.assertEqual((res["ended_by"], res["refused"], res["sustained"], res["inflight_max"]), ("duration", 0, True, 4))
        self.assertGreaterEqual(res["inflight_mean"], 3)  # a slot is refilled as soon as its call returns
        self.assertEqual((res["server_overloaded"], res["n429"]), (0, 0))
        self.assertLessEqual(res["latency_ok"]["p50_s"], res["latency_ok"]["p95_s"])
        self.assertEqual((res["sent"], len(Upstream.seen)), (res["ok"], res["ok"]))
        self.assertGreater(res["sent"], 8)
        self.assertEqual(sum(m["ok"] for m in res["per_minute"]), res["ok"])
        self.assertEqual(sum(m["input_tokens"] for m in res["per_minute"]), 7 * res["ok"])  # the fake usage
        self.assertEqual(res["by_kind"]["write_turn"]["output_tokens"] + res["by_kind"]["summariser"]["output_tokens"],
                         3 * res["ok"])
        self.assertEqual(res["effort_is_pin"], res["sent"])
        self.assertEqual(res["quota_headers_last"]["x-codex-primary-used-percent"], "42")
        for _, wire in Upstream.seen:  # every send is a source body, unchanged
            self.assertIn(wire, bodies)
        self.assertEqual({c["n"] % 4 for c in res["calls"]}, {0, 1, 2, 3})  # round robin over the mix
        self.assertEqual(len(self.records("soak")), res["sent"])
        text = (self.tmp / "ledger" / "ledger.jsonl").read_text()
        self.assertNotIn(ACCT, text)
        self.assertNotIn("authorization", text.lower())

    def test_three_quota_refusals_stop_before_the_next_send(self):
        import soak_sol
        d = self.make(write_turns=False, budget_cap=2000, run="soak")
        pays = soak_sol.payloads(self.source(d)[0])
        Upstream.script = [(429, self.QUOTA)] * 40
        res = soak_sol.soak(d, pays, inflight=4, duration=5.0, ceiling=1000, pause=1.0, sample_s=0.1)
        self.assertEqual((res["ended_by"], res["sustained"]), ("quota_3_in_a_row", False))
        self.assertTrue(3 <= res["sent"] <= 4 and res["sent"] == len(Upstream.seen) == res["n429"])
        self.assertLess(res["wall_s"], 3)  # stopped at once, not at the window's end
        shape = json.loads(res["refusal_shapes"][0])
        self.assertEqual((shape["status"], shape["category"], shape["body_shape"]["error"]["type"]),
                         (429, "quota", "usage_limit_reached"))
        self.assertEqual(res["per_minute"][0]["n429"], res["sent"])
        self.assertTrue(soak_sol.overloaded({"ok": False, "category": "rate", "error_obj": {"code": "server_overloaded"}}))
        self.assertFalse(soak_sol.overloaded({"ok": False, "category": "quota", "error_obj": {"type": "usage_limit"}}))

    def test_call_ceiling_and_plan(self):
        import soak_sol
        d = self.make(write_turns=False, budget_cap=2000, run="soak")
        pays = soak_sol.payloads(self.source(d)[0])
        res = soak_sol.soak(d, pays, inflight=4, duration=5.0, ceiling=10, sample_s=0.1)
        self.assertEqual((res["ended_by"], res["sent"], len(Upstream.seen)), ("call_ceiling", 10, 10))
        self.assertFalse(res["sustained"])
        pl = soak_sol.plan(pays, inflight=24, duration=180, ceiling=500)  # mean 0.08 s, floored at 0.1 s
        self.assertEqual((pl["fits"], pl["est_calls"], pl["max_fitting_duration_s"]), (False, 43200, 2))
        self.assertTrue(soak_sol.plan([dict(p, t_ms=7000) for p in pays], 24, 180, 700)["fits"])  # ~617 calls
        b = self.tmp / "budget.json"
        b.write_text(json.dumps({"total": 600, "by_run": {}, "by_kind": {}}))
        self.assertEqual(soak_sol.ceiling_for(b, 1400, 700, 50), 700)
        b.write_text(json.dumps({"total": 900, "by_run": {}, "by_kind": {}}))
        self.assertEqual(soak_sol.ceiling_for(b, 1400, 700, 50), 450)
        with self.assertRaises(SystemExit):  # no compaction body in the source: refuse, never a write-only soak
            soak_sol.payloads(self.source(d)[0], kinds=("write_turn", "probe"))


class RateBound(unittest.TestCase):
    def test_request_counts_and_rate_verdict(self):
        import analyse_sol as an
        up = lambda k, ok=True: {"kind": k, "ok": ok, "t_ms": 1000}
        led = [{"type": "request", "role": "replay_main", "subrole": "cursor", "upstream": [up("write_turn", False),
                                                                                           up("write_turn")]},
               {"type": "request", "role": "replay_main", "subrole": "cursor", "upstream": [up("write_turn")]},
               {"type": "request", "role": "summariser", "upstream": [up("summariser", False), up("summariser")]},
               {"type": "request", "role": "aux", "upstream": [up("aux"), up("aux")]},
               {"type": "request", "role": "probe_main", "subrole": "cursor", "upstream": [up("probe")] * 3}]
        rows = [{"phase": "life", "session": "1", "what": "turn", "turn": "6"}, {"phase": "probe", "session": "1"}]
        inputs = {"turn_ex_comp_s": 10, "upstream_turn_s": 6, "summariser_s": 90, "session_fixed_s": 29,
                  "comp_per_sprint": 2, "probe_turn_s": 30, "probe_upstream_s": 20, "probe_fixed_s": 26,
                  "aux_per_session_s": 5, "plain_turn_s": 2}
        q, ri = an.requests(rows, led, inputs)
        self.assertEqual((q["write_per_turn"], q["compaction_per_compaction"], q["aux_per_session"],
                          q["probe_per_probe_turn"], q["scripted_per_turn"]), (1.5, 2.0, 1.0, 3.0, 0.0))
        self.assertEqual(ri["comp_per_sprint"], 1.0)  # one logical compaction: its retry is counted once, in q
        pr = an.projection(ri, C=1, L=48)  # S = 200, 5 turns, 80 compactions, b = 150 probes doubled by controls
        R, P = 1000 * 1.5 + 40 * 2.0 + 200 * 1.0, 150 * (3.0 + 1.0) * 2  # 40 compactions of 2 attempts each
        self.assertAlmostEqual(pr["R_lane_h"] * 3600, R)
        self.assertAlmostEqual(pr["P_lane_h"] * 3600, P)
        rows = an.rate_grid(an.grid(inputs, 0.2, Cs=(24,)), ri)
        cell = next(r for r in rows if (r["L"], r["cuts"], r["latency_x"], r["cadence"]) == (48, "none", 1.0, "every turn"))
        b = cell["board"]
        self.assertEqual(b["N_req"], round(60 * (R * 1.5 + 2 * P)))  # (L + L_keep) lives, f = 0.5
        one, two = b["rate"].values()
        self.assertEqual((one["rate_h"], two["rate_h"]), (round(b["N_req"] / 180 / 60, 1), round(b["N_req"] / 360 / 60, 1)))
        self.assertEqual(one["fits"], b["lane_fits"] and b["N_req"] / 180 / 60 <= 24)
        edge = an.rate_grid([{"L": 48, "cuts": "none", "cadence": "every turn", "board": {"lane_h": 24.0, "lane_fits": False},
                              "robustness": {"lane_h": 1.0, "lane_fits": True}}], ri)[0]["board"]  # 24.04 h shown as 24.0
        self.assertFalse(any(v["fits"] for v in edge["rate"].values()))


    def test_lane_time_at_the_workload_c_k_equals_the_rate_bound(self):
        import analyse_sol as an
        inputs = {"turn_ex_comp_s": 10, "upstream_turn_s": 6, "summariser_s": 60, "session_fixed_s": 29,
                  "comp_per_sprint": 2, "probe_turn_s": 30, "probe_upstream_s": 12, "probe_fixed_s": 26,
                  "aux_per_session_s": 5, "plain_turn_s": 2}
        ri = dict(inputs, upstream_turn_s=1.0, summariser_s=1.0, aux_per_session_s=1.25, probe_upstream_s=3.0)
        capped = set()
        for k, kw in ((1, {}), (2, an.CUTS_12)):
            c = an.achievable(inputs, ri, k, **kw)
            lane = an.projection(inputs, C=1, **kw)["board"]["lane_work_h"]
            n = an.projection(ri, C=1, **kw)["board"]["lane_work_h"] * 3600
            self.assertAlmostEqual(c["mean_request_s"], lane * 3600 / n, places=3)  # the workload's own mix
            if c["capped"]:  # the machine binds: C stops at its cap and lane time exceeds the rate bound
                self.assertEqual((round(c["C"], 2), c["J"]), (c["C_machine"], c["J_max"]))
                self.assertGreater(c["lane_h"], c["rate_h"])
            else:
                self.assertAlmostEqual(c["lane_h"], c["rate_h"], places=2)  # Little's law at C_k
                self.assertEqual(c["fits"], n / (k * 180) / 60 <= 24)
            capped.add(c["capped"])
        self.assertEqual(capped, {False, True})

    def test_no_positive_concurrency_refuses_to_project(self):
        import analyse_sol as an
        self.assertEqual(an.measured_C({"C_effective": 20.58}, {"sustained_concurrency": 48}), 20)
        for lvl, ramp in (({"C_effective": 0.0}, {"sustained_concurrency": 48}), ({"C_effective": 0.4}, {}),
                          (None, {"sustained_concurrency": 0}), (None, {})):
            with self.assertRaises(SystemExit) as e:
                an.measured_C(lvl, ramp)
            self.assertIn("no positive concurrency", str(e.exception.code))

class Failures(Base):
    """Round 3: only a clean completed or incomplete stream is replayed; every other result is a neutral 503."""
    def run_raw(self, *raws, n=None, **kw):
        d, n = self.make(write_turns=False, **kw), [] if n is None else n
        script = list(raws)
        d.urlopen = lambda req, timeout: (n.append(1), Resp(script.pop(0) if script else frames(
            {"type": "response.completed", "response": {"status": "completed"}})))[1]
        with mock.patch.object(sd.time, "sleep"):
            code, out, rec = d.handle(AUX, {})
        return d, code, out, rec, n

    def test_round3_shapes_get_a_neutral_503_and_no_replay(self):
        bare = {"type": "response.failed", "response": {"status": "failed", "error": None}}
        generic = {"type": "response.failed", "response": {"status": "failed", "error": {"code": "server_error"}}}
        usage = {"type": "error", "code": "usage_limit_reached", "message": "The usage limit has been reached"}
        rate = {"type": "error", "code": "rate_limit_exceeded", "message": "Rate limit reached for requests"}
        failed_usage = {"type": "response.failed", "response": {"status": "failed", "error": {
            "code": "usage_limit_reached", "message": "The usage limit has been reached"}}}
        cases = [((usage, bare), "quota", False), ((rate, bare), "rate", False), ((rate, generic), "rate", False),
                 ((failed_usage, {"type": "error", "code": "server_error"}), "quota", False),
                 (({"type": "error", "message": "Unauthorized: invalid token for credit endpoint"},), "auth_sse", True),
                 (({"type": "error", "status": 403, "error": {"code": "server_is_overloaded", "message":
                    "Our servers are overloaded"}},), "auth_sse", True)]
        for evs, cat, stop in cases:
            self.tmp = Path(tempfile.mkdtemp())
            raw = frames(*evs)
            d, code, out, rec, n = self.run_raw(*[raw] * 4)
            self.assertEqual((code, json.loads(out), rec["served"]), (503, sd.NEUTRAL_503, "neutral_503"), evs)
            self.assertEqual((rec["upstream"][-1]["category"], d.stopped), (cat, stop), evs)
            self.assertEqual(rec["upstream"][0]["frame_types"], [e["type"] for e in evs])
            self.assertEqual(len(n), 4 if cat == "rate" else 1)  # rate is retried with backoff; quota and auth not

    def test_incomplete_max_output_tokens_is_forwarded_unchanged(self):
        inc = frames({"type": "response.output_text.delta", "delta": "half an answer about quota"},
                     {"type": "response.incomplete", "response": {"status": "incomplete", "incomplete_details": {
                         "reason": "max_output_tokens"}}})
        d, code, out, rec, n = self.run_raw(inc)
        self.assertEqual((code, out, rec["served"], d.failure_streak, len(n)), (200, inc, "forward", 0, 1))

    def test_output_text_naming_auth_quota_or_rate_is_forwarded_unchanged(self):
        words = "Unauthorized 401: invalid token; the usage limit and quota were exceeded; rate limit, overloaded"
        raw = frames({"type": "response.output_text.delta", "delta": words},
                     {"type": "response.output_item.done", "item": dict(MSG, content=[{"type": "output_text",
                                                                                      "text": words}])},
                     {"type": "response.completed", "response": {"status": "completed"}})
        d, code, out, rec, _ = self.run_raw(raw)
        self.assertEqual((code, out, d.stopped, rec["upstream"][0]["category"]), (200, raw, False, None))

    def test_breaker_stops_after_three_unrecovered_failures(self):
        d = self.make(write_turns=False)
        ok = frames({"type": "response.completed", "response": {"status": "completed"}})
        over = frames({"type": "error", "code": "server_is_overloaded", "message": "Our servers are overloaded"})
        other = frames({"type": "response.failed", "response": {"status": "failed", "error": None}})
        quota = frames({"type": "error", "code": "insufficient_quota", "message": "You exceeded your current quota"})
        plan = [other, quota, over, ok, other, quota, over, over, over, over]  # an overload recovered, then 3 unrecovered
        d.urlopen = lambda req, timeout: Resp(plan.pop(0))
        with mock.patch.object(sd.time, "sleep"):
            codes = [d.handle(AUX, {})[0] for _ in range(4)]
            self.assertEqual((codes, d.failure_streak, d.stopped), ([503, 503, 200, 503], 1, False))
            self.assertEqual(d.handle(AUX, {})[0], 503)
            self.assertFalse(d.stopped)
            self.assertEqual((d.handle(AUX, {})[0], d.stopped, d.stop_reason),
                             (503, True, "upstream_failures_3_in_a_row"))
        self.assertEqual(plan, [])
        self.assertFalse((self.tmp / "auth.json.stopped").exists())  # not a login stop

    def test_write_turn_naming_identity_headers_persists_byte_identical(self):
        d = self.make()
        text = "Discuss Authorization and preauthorization, then save the note."
        reply = sse(dict(CALL, arguments=json.dumps({"content": "Authorization: preauthorization noted"})))
        Upstream.script = [(200, reply)]
        body = self.turn(d)
        body["input"].insert(0, {"type": "message", "role": "assistant", "content": text})
        code, _ = self.http(d, "POST", sd.MOUNT + "/responses", body)
        rec = self.records("request")[0]

        def load(h):
            return zstd.decompress((self.tmp / "ledger" / "blobs" / h[:2] / f"{h}.json.zst").read_bytes())
        sent_body, sent_wire = Upstream.seen[0][1], json.loads(load(rec["upstream"][0]["req"]))
        self.assertEqual((code, rec["served"], rec["write_turn_readback"]), (200, "write_tool_calls", True))
        self.assertEqual(sent_wire, sent_body)  # exactly the forwarded request
        self.assertEqual(json.loads(load(rec["req"])), body)  # exactly the harness request
        self.assertTrue(sd.readback(json.loads(load(rec["req"])), sent_wire, sd.MODEL))  # the persisted round trip
        self.assertEqual(json.loads(load(rec["upstream"][0]["resp"]))["sse"].encode(), reply)  # the bytes received

    def test_sentinel_is_published_atomically(self):
        p, real, seen = store(self.tmp, exp_in=60), json.dumps, []

        def dumps(obj, *a, **kw):
            if isinstance(obj, dict) and "reason" in obj:
                seen.append(p.with_name("auth.json.stopped").exists())  # while the content is serialised
            return real(obj, *a, **kw)
        login = sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=lambda u, f: (401, {}))
        with mock.patch.object(sd.json, "dumps", side_effect=dumps), self.assertRaises(sd.Stop):
            login.token()
        self.assertEqual(seen, [False])
        self.assertEqual((json.loads(login.sentinel.read_text())["reason"], stat.S_IMODE(login.sentinel.stat().st_mode)),
                         ("token_endpoint_401", 0o600))
        self.assertEqual(sorted(x.name for x in self.tmp.iterdir()), ["auth.json", "auth.json.lock", "auth.json.stopped"])

    def test_a_failed_sentinel_write_still_stops(self):
        calls, real = [], json.dumps

        def dumps(obj, *a, **kw):
            if isinstance(obj, dict) and "reason" in obj:
                raise OSError(28, "No space left on device")
            return real(obj, *a, **kw)
        login = sd.Login(store(Path(tempfile.mkdtemp()), exp_in=60), "http://127.0.0.1:9/never", "client-fake",
                         post=lambda u, f: (calls.append(1), (401, {}))[1])
        d = self.make()  # the director path: an upstream 401 whose sentinel cannot be written
        Upstream.script = [(401, b'{"error": {"message": "expired"}}')]
        with mock.patch.object(sd.json, "dumps", side_effect=dumps):
            for _ in range(2):  # the in-process latch holds
                with self.assertRaisesRegex(sd.Stop, "^token_endpoint_401$"):
                    login.token()
            code = d.handle(AUX, {})[0]
        self.assertEqual((calls, code, d.login.dead, d.stop_reason), ([1], 503, "upstream_401", "upstream_401"))
        self.assertEqual((login.sentinel.exists(), [x["error"] for x in login.log + d.login.log
                                                    if x["type"] == "sentinel_error"]), (False, ["OSError"] * 2))
        with self.assertRaisesRegex(sd.Stop, "^upstream_401$"):
            d.login.token()

    def test_refresh_budget_latches_in_process_only(self):
        p, calls = store(self.tmp, exp_in=60), []
        login = sd.Login(p, "http://127.0.0.1:9/never", "client-fake", post=lambda u, f: (calls.append(1), (401, {}))[1],
                         on_refresh=lambda: False)
        for _ in range(2):
            with self.assertRaisesRegex(sd.Stop, "^refresh_budget$"):
                login.token()
        self.assertEqual((calls, login.sentinel.exists()), ([], False))  # the refresh token was never sent


class Round4(Base):
    """Round 4: the edge shapes of the round-3 failure path."""
    COMPLETED = frames({"type": "response.completed", "response": {"status": "completed"}})

    def test_an_unreadable_refusal_body_keeps_its_status_and_stops_on_auth(self):
        class Body:
            def __init__(self, close_fails):
                self.close_fails = close_fails

            def read(self, *a):
                raise http.client.IncompleteRead(b"")

            def close(self):
                if self.close_fails:  # a failing cleanup must not replace the record
                    raise OSError(9, "Bad file descriptor")
        for code, close_fails in ((401, False), (403, False), (429, False), (503, False), (401, True), (503, True)):
            self.tmp = Path(tempfile.mkdtemp())
            d, n = self.make(write_turns=False), []

            def refuse(req, timeout, code=code, n=n, close_fails=close_fails):
                n.append(1)
                raise urllib.error.HTTPError("http://upstream.invalid", code, "refused", {}, Body(close_fails))
            d.urlopen = refuse
            with mock.patch.object(sd.time, "sleep"):
                status, out, rec = d.handle(AUX, {})
                d.handle(AUX, {})
            self.assertEqual((status, json.loads(out)), (503, sd.NEUTRAL_503), code)
            u = rec["upstream"][0]
            self.assertEqual((u["status"], u["body_read_error"], "t_ms" in u), (code, "IncompleteRead", True))
            auth = code in (401, 403)
            self.assertEqual((d.stopped, (self.tmp / "auth.json.stopped").exists()), (auth, auth))
            self.assertEqual((len(n), len(rec["upstream"])), (1, 1) if auth else (8, 4))  # 429/503: retried

    def test_a_non_object_json_frame_is_unparsed_not_a_crash(self):
        for frame in (b"data: 123\n\n", b"data: [1]\n\n", b'data: "x"\n\n'):
            d = self.make(write_turns=False)
            d.urlopen = lambda req, timeout, f=frame: Resp(f + self.COMPLETED)
            up = d.upstream(AUX, "aux", {})
            self.assertEqual((up["ok"], up["forward"], up["n_unparsed"]), (True, False, 1), frame)

    def test_an_unparsed_frame_is_served_but_never_replayed(self):
        for raw in (b"data: {broken}\n\n" + self.COMPLETED, self.COMPLETED + b"data: {trunc"):
            d, n = self.make(write_turns=False), []
            d.urlopen = lambda req, timeout, raw=raw, n=n: (n.append(1), Resp(raw))[1]
            d.failure_streak = 2
            code, out, rec = d.handle(AUX, {})
            u = rec["upstream"][0]
            self.assertEqual((code, json.loads(out), u["ok"], u["n_unparsed"] >= 1), (503, sd.NEUTRAL_503, True, True))
            self.assertEqual((d.failure_streak, d.stopped, len(n)), (2, False, 1))  # held, not counted
            self.assertTrue(d.upstream(AUX, "aux", {})["ok"])
        d = self.make(write_turns=False)
        d.urlopen = lambda req, timeout: Resp(self.COMPLETED)
        self.assertEqual(d.handle(AUX, {})[:2], (200, self.COMPLETED))  # a clean control: byte for byte

    def test_a_long_first_error_does_not_hide_a_later_rate_limit(self):
        raw = frames({"type": "error", "message": "x" * 2200},
                     {"type": "error", "code": "rate_limit_exceeded", "message": "Rate limit reached"})
        d, n = self.make(write_turns=False), []
        d.urlopen = lambda req, timeout: (n.append(1), Resp(raw))[1]
        with mock.patch.object(sd.time, "sleep"):
            code, _, rec = d.handle(AUX, {})
        self.assertEqual((code, rec["upstream"][0]["category"], len(n)), (503, "rate", 4))

    def test_completed_under_another_2xx_is_not_served(self):
        for status in (201, 202, 206):
            d = self.make(write_turns=False)
            resp = Resp(self.COMPLETED)
            resp.status = status
            d.urlopen = lambda req, timeout, r=resp: r
            code, out, rec = d.handle(AUX, {})
            self.assertEqual((code, json.loads(out), rec["upstream"][0]["ok"]), (503, sd.NEUTRAL_503, False), status)

    def test_error_scope_is_top_level_and_response_level_only(self):
        echo = frames({"type": "response.completed", "response": {"status": "completed", "tools": [{
            "type": "function", "name": "report", "parameters": {"type": "object", "properties": {
                "error": {"type": "string", "description": "the error to report"}}}}]}})
        d = self.make(write_turns=False)
        d.urlopen = lambda req, timeout: Resp(echo)
        self.assertEqual(d.handle(AUX, {})[:2], (200, echo))  # an echoed tool schema is not an error object

    def test_scripted_usage_counts_instructions(self):
        d = self.make(mode="stub")
        body = self.turn(d)
        base = d._usage(body, [MSG])["input_tokens"]
        more = d._usage(dict(body, instructions="i" * 40000), [MSG])["input_tokens"]
        self.assertAlmostEqual(more - base, 10000, delta=10)

    def test_replay_rejects_flags_the_sol_director_lacks(self):
        import replay
        for extra in (["--measure-overhead"], ["--lane-rewrite", "x"]):
            argv = ["replay.py", "--run", "r", "--port", "1", "--lane", "sol", *extra]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(replay, "env", side_effect=AssertionError(
                    "reached run setup")), mock.patch("sys.stderr"), self.assertRaises(SystemExit) as cm:
                replay.main()
            self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
