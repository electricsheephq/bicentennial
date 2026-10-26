"""Offline tests for the S6b director (fake tokens, a loopback fake upstream). Run: python3.14 -m unittest test_s6b"""

import base64
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
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

    def make(self, mode="live", post=None, exp_in=3600, **kw):
        os.environ["BICENTENNIAL_SOL_BASE_URL"] = f"http://127.0.0.1:{serve(self, Upstream)}/backend-api/codex"
        self.addCleanup(os.environ.pop, "BICENTENNIAL_SOL_BASE_URL", None)
        login = sd.Login(store(self.tmp, exp_in), "http://127.0.0.1:9/never", "client-fake", post=post or self.no_post)
        a = SimpleNamespace(**{"life": str(LIFE), "ledger_dir": str(self.tmp / "ledger"), "budget_file": str(
            self.tmp / "b.json"), "budget_cap": 50, "run": "t", "model": sd.MODEL, "mode": mode, "write_turns": True,
            "chars_per_token": 4.0, "context_length": 272000, "timeout": 10} | kw)
        return sd.Director(a, login=login if mode == "live" else None)

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

    def test_sse_auth_error_in_an_http_200_is_never_replayed(self):
        class Resp:  # an in-memory upstream stream: no socket
            status, headers = 200, {}

            def __init__(self, raw):
                self.raw = raw

            def read(self):
                return self.raw

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        cases = [({"type": "error", "code": "invalid_api_key", "message": "Incorrect API key provided"}, True),
                 ({"type": "error", "error": {"code": "token_expired", "message": "Provided token is expired"}}, True),
                 ({"type": "error", "status": 403, "message": "Forbidden"}, True),
                 ({"type": "response.failed", "response": {"status": "failed", "error": {
                     "code": "invalid_api_key", "message": "Your authentication token is invalid"}}}, True),
                 ({"type": "error", "code": "server_error", "message": "An error occurred"}, False)]
        for ev, auth in cases:
            self.tmp = Path(tempfile.mkdtemp())
            d, n = self.make(), []
            raw = f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode()
            d.urlopen = lambda req, timeout, n=n, raw=raw: (n.append(1), Resp(raw))[1]
            code, out, rec = d.handle(AUX, {})
            self.assertEqual((rec["upstream"][0]["category"] == "auth_sse", d.stopped), (auth, auth), ev)
            if auth:
                self.assertEqual((code, json.loads(out), d.stop_reason), (503, sd.NEUTRAL_503, "upstream_sse_auth"))
                self.assertNotRegex(out.decode().lower(), r"api key|token|auth|401|403|forbidden")
                d.handle(AUX, {})  # stopped: no further upstream call
                self.assertEqual(len(n), 1)


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
            Upstream.script = [(429, rate)] * 4  # still refused after the backoff: a neutral 503, never a 429
            code, out, rec = d.handle(aux, {})
            self.assertEqual((code, len(rec["upstream"]), rec["served"]), (503, 4, "neutral_503"))
            for i in range(3):  # usage limit: no retry; the third in a row stops the director
                Upstream.script = [(429, quota)]
                code, out, rec = d.handle(aux, {})
                self.assertEqual((code, rec["upstream"][0]["category"], d.stopped), (503, "quota", i == 2))
                self.assertNotRegex(out.decode().lower(), r"quota|usage|limit|rate|429|billing")
        self.assertEqual(rec["upstream"][0]["body_shape"]["error"], {"type": "usage_limit_reached", "message": "str",
                                                                     "resets_in_seconds": "int"})
        d2 = self.make()  # a 401 stops at once: no retry, no refresh, no second credential
        Upstream.script = [(401, b'{"error": {"message": "expired"}}')]
        code, out, rec = d2.handle(aux, {})
        self.assertEqual((code, d2.stop_reason, len(rec["upstream"])), (503, "upstream_401", 1))


class Ramp(Base):
    def test_ramp_never_retries_and_stops_on_quota(self):
        import ramp_sol
        quota = json.dumps({"error": {"type": "usage_limit_reached", "message": "The usage limit has been reached"}}).encode()
        d, state = self.make(), {"quota_streak": 0, "quota_stop": False}
        Upstream.script = [(429, b'{"error": {"code": "rate_limit_exceeded", "message": "Rate limit reached"}}')]
        lv = ramp_sol.level(d, 4, state)  # one 429 among 8: complete but not sustained, and never retried
        self.assertEqual((lv["sent"], lv["n429"], lv["sustained"], len(Upstream.seen)), (8, 1, False, 8))
        self.assertEqual(lv["quota_headers_last"]["x-codex-primary-used-percent"], "42")
        Upstream.script = [(429, quota)] * 8
        lv = ramp_sol.level(d, 4, state)  # 3 quota refusals in a row stop the calls not yet started
        self.assertTrue(state["quota_stop"] and d.stopped and 3 <= lv["sent"] < 8)
        self.assertEqual(len(self.records("ramp")), 8 + lv["sent"])
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


if __name__ == "__main__":
    unittest.main()
