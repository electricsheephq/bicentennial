"""Offline tests for the S6a director and ramp (loopback only). Run: python3.14 -m unittest test_s6a"""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import director
import ramp
import verify

HERE = Path(__file__).resolve().parent
MEM = {"type": "function", "function": {"name": "memory", "parameters": {"type": "object"}}}
TODO = {"type": "function", "function": {"name": "todo", "parameters": {"type": "object"}}}


def make(tmp, **kw):
    return director.Director(SimpleNamespace(**{
        "life": str(HERE / "micro_life.json"), "ledger_dir": str(tmp / "ledger"), "budget_file": str(tmp / "b.json"),
        "budget_cap": 50, "run": "t", "model": "up", "mode": "stub", "write_turns": True, "measure_overhead": False,
        "chars_per_token": 4.0, "context_length": 64000, "aliases": "m", "timeout": 10, "lane_rewrite": ""} | kw))


def turn_body(d):
    return {"model": "bicentennial-main", "stream": True, "stream_options": {"include_usage": True},
            "reasoning_effort": "medium", "tools": [MEM, TODO],
            "messages": [{"role": "system", "content": "s"}, {"role": "user", "content": d.expected[0]["user"]}]}


def serve(test, handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    test.addCleanup(lambda: (srv.shutdown(), srv.server_close()))
    return srv.server_address[1]


def records(tmp, kind):
    return [r for r in map(json.loads, (tmp / "ledger" / "ledger.jsonl").read_text().splitlines()) if r["type"] == kind]


class Upstream(BaseHTTPRequestHandler):
    seen, reject, log_message = [], set(), lambda *a: None

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Upstream.seen.append(body)
        bad = sorted(Upstream.reject & set(body))
        out = {"error": {"message": f"Unsupported parameter: {bad[0]}"}} if bad else {"model": "up", "choices": [
            {"index": 0, "finish_reason": "tool_calls", "message": {"role": "assistant", "content": "", "tool_calls": [
                {"id": "u1", "type": "function", "function": {"name": "memory", "arguments": "{}"}}]}}]}
        data = json.dumps(out).encode()
        self.send_response(400 if bad else 200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class Director(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_refresh_and_response_attempts_reconcile_with_budget(self):
        d = make(self.tmp)
        d.budget.take("t", "refresh")
        d.ledger.append({"type": "refresh", "status": 200})
        d.budget.take("t", "aux")
        d.ledger.append({"type": "request", "upstream": [{"category": None}]})
        self.assertEqual(verify.check_ledger(self.tmp)["upstream_attempts"], 2)
        self.assertEqual(json.loads((self.tmp / "b.json").read_text())["total"], 2)

    def post_aux(self, d, handler):  # an aux request whose client hangs up during the (slowed) upstream call
        port, real = serve(self, handler), d.upstream
        d.upstream = lambda body, kind: (time.sleep(0.4), real(body, kind))[1]
        body = json.dumps({"messages": [{"role": "user", "content": "title"}]}).encode()
        s = socket.create_connection(("127.0.0.1", port))
        s.sendall(b"POST /aux/title_generation/v1/chat/completions HTTP/1.1\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        s.close()
        time.sleep(1.0)

    def test_record_survives_hangup_and_send_error(self):  # finding 1
        for fail_send in (False, True):
            self.tmp = Path(tempfile.mkdtemp())
            d = make(self.tmp, write_turns=False)

            class H(director.make_handler(d)):
                def _send(self, code, obj):
                    if fail_send:
                        raise BrokenPipeError(32, "Broken pipe")
                    return super()._send(code, obj)
            self.post_aux(d, H)
            reqs, errs = records(self.tmp, "request"), records(self.tmp, "send_error")
            self.assertEqual(len(reqs), 1)
            self.assertTrue(reqs[0]["client_disconnected"])
            self.assertIn([e["request_seq"] for e in errs], [[reqs[0]["seq"]]] + [[]] * (not fail_send))  # a real send may fail too
            res = verify.check_ledger(self.tmp)
            self.assertEqual(res["chain_breaks"], 0)
            self.assertEqual(res["upstream_attempts"], json.loads((self.tmp / "b.json").read_text())["by_run"]["t"])

    def live(self, reject=()):
        Upstream.seen, Upstream.reject = [], set(reject)
        os.environ["BICENTENNIAL_UPSTREAM_OPENAI_URL"] = f"http://127.0.0.1:{serve(self, Upstream)}/v4"
        os.environ["BICENTENNIAL_UPSTREAM_KEY"] = "test-placeholder"
        self.addCleanup(lambda: [os.environ.pop(k) for k in ("BICENTENNIAL_UPSTREAM_OPENAI_URL", "BICENTENNIAL_UPSTREAM_KEY")])
        d = make(self.tmp, mode="live")
        body = turn_body(d)
        code, _, rec = d.handle("/main/v1/chat/completions", body)
        self.assertEqual((code, rec["served"]), (200, "write_tool_calls"))
        return d, body, rec

    def test_inference_parameters_forwarded(self):  # finding 2
        d, body, rec = self.live()
        self.assertEqual(Upstream.seen, [{"model": "up", "stream": False, "reasoning_effort": "medium", "tools": [MEM],
                                          "messages": body["messages"] + [{"role": "user", "content": director.WRITE_SUFFIX}]}])
        self.assertTrue(rec["write_turn_readback"])

    def test_rejected_parameter_fallback_recorded(self):  # finding 2: fallback and disclosure
        d, body, rec = self.live(reject={"reasoning_effort"})
        self.assertEqual([u.get("category") for u in rec["upstream"]], ["param_rejected:reasoning_effort", None])
        self.assertNotIn("reasoning_effort", Upstream.seen[1])
        self.assertFalse(rec["write_turn_readback"])
        self.assertEqual(d.rejections[0]["keys"], ["reasoning_effort"])
        self.assertEqual(json.loads((self.tmp / "b.json").read_text())["by_run"]["t"], 2)

    def test_failed_write_turn_counted(self):  # PR thread: the replay driver stops on this
        d = make(self.tmp, budget_cap=0)
        _, _, rec = d.handle("/main/v1/chat/completions", turn_body(d))
        self.assertEqual((rec["write_turn_failed"], d.write_failures), ("budget_or_stop", 1))

    def test_torn_ledger_refuses_resume(self):  # finding 5
        root = self.tmp / "ledger"
        director.Ledger(root, director.Guard()).append({"type": "request"})
        director.Ledger(root, director.Guard()).append({"type": "request"})  # an intact ledger resumes
        self.assertEqual(verify.check_ledger(self.tmp)["chain_breaks"], 0)
        with open(root / "ledger.jsonl", "a") as f:
            f.write('{"seq": 3, "prev_')
        with self.assertRaisesRegex(SystemExit, "torn"):
            director.Ledger(root, director.Guard())


class Redact(unittest.TestCase):
    def test_a_token_split_at_the_input_cut_is_dropped(self):  # S6c review 2, R2-F3
        email = director.redact("1" * 4090 + " someone@example.com tail")
        self.assertNotIn("someo", email)
        uuid = director.redact("1" * 4090 + " 0123abcd-1234-1234-1234-123456789abc")
        self.assertNotIn("1234-1", uuid)
        self.assertEqual(len(director.redact("P" * (8 << 20))), 600)  # a long body with no separators keeps its 600
        self.assertEqual(director.redact("a@b.co and 1234567"), "<email> and <n>")


class Ramp(unittest.TestCase):
    def test_quota_streak_stops_level_below_threshold(self):  # finding 3: 13 ok then 3 quota, 3/16 < 25%
        n, lock = [0], threading.Lock()

        def call(i):
            with lock:
                n[0] += 1
                k = n[0]
            time.sleep(0.1 if k > 13 else 0)  # the refusals arrive after every success
            return {"ok": True, "status": 200, "t_ms": 1} if k <= 13 else {"ok": False, "status": 429, "category": "quota"}
        state = {"quota_streak": 0, "quota_stop": False}
        ramp.run_level(8, call, lambda: True, state)
        self.assertTrue(state["quota_stop"])

    def test_streak_spans_levels_and_unfunded_calls_not_sent(self):  # and the PR thread on unfunded levels
        state = {"quota_streak": 2, "quota_stop": False}
        res = ramp.run_level(1, lambda i: {"ok": False, "status": 429, "category": "quota"}, lambda: True, state)
        self.assertEqual([(c["sent"], c.get("reason")) for c in res], [(True, None), (False, "quota_stop")])
        left = iter([True] * 3)
        res = ramp.run_level(2, lambda i: {"ok": True}, lambda: next(left, False), {"quota_streak": 0, "quota_stop": False})
        self.assertEqual([c.get("reason") for c in res if not c["sent"]], ["budget"])


if __name__ == "__main__":
    unittest.main()
