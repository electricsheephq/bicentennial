"""Offline tests for the S4 director and MCP fixture. Loopback only: a fake upstream on 127.0.0.1."""

from __future__ import annotations

import http.client
import json
import socket
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import anthropic_director as ad
import mcp_fixture
import run_s4
import summarise

UP_KEY = "up-key-0123456789-test"
FOREIGN = "sk-foreign-credential-value-xyz"
BETA = "beta-header-value-qrs"
SSE = (b'event: message_start\ndata: {"type":"message_start","message":{"model":"glm-5.3","usage":{"input_tokens":'
       b'42,"output_tokens":1}}}\n\nevent: content_block_start\ndata: {"type":"content_block_start","index":0,'
       b'"content_block":{"type":"tool_use","id":"t1","name":"Bash","input":{}}}\n\nevent: message_delta\ndata: '
       b'{"type":"message_delta","delta":{"stop_reason":"tool_use"},"usage":{"output_tokens":7}}\n\n')


class FakeUpstream:
    """Scripted replies (status, body bytes); records the path, headers and JSON body of each call."""
    def __init__(self):
        self.replies, self.calls = [], []
        up = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                up.calls.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                 "body": body})
                status, data = up.replies.pop(0) if up.replies else (200, (b'{"model":"glm-5.3","content":[],'
                                                                           b'"usage":{"input_tokens":3}}'))
                self.send_response(status)
                self.send_header("Content-Type", "text/event-stream" if data.startswith(b"event:") else
                                 "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"


@pytest.fixture
def up(monkeypatch):
    u = FakeUpstream()
    monkeypatch.setenv("BICENTENNIAL_UPSTREAM_ANTHROPIC_URL", u.url)
    monkeypatch.setenv("BICENTENNIAL_UPSTREAM_KEY", UP_KEY)
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    yield u
    u.srv.shutdown()


def director(tmp_path: Path, *extra: str) -> ad.Director:
    a = ad.build_parser().parse_args([
        "--port-file", str(tmp_path / "port"), "--ledger", str(tmp_path / "ledger.jsonl"),
        "--budget-file", str(tmp_path / "budget.json"), "--strip-file", str(tmp_path / "strip.json"),
        "--stop-file", str(tmp_path / "STOP"), "--backoff-scale", "0", *extra])
    return ad.Director(a)


HDRS = {"x-api-key": "placeholder", "anthropic-beta": BETA, "anthropic-version": "2023-06-01",
        "User-Agent": "ua-value-abc", "Content-Type": "application/json"}


def msg(**kw) -> bytes:
    return json.dumps({"model": "bicentennial-cc-main", "max_tokens": 64, "stream": False,
                       "messages": [{"role": "user", "content": "hi"}], **kw}).encode()


def ledger(tmp_path: Path) -> list[dict]:
    return [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]


def test_inbound_credentials_dropped_and_upstream_key_sent_as_bearer(up, tmp_path):
    d = director(tmp_path)
    status, _, _, _ = d.serve("POST", "/v1/messages?beta=true", dict(HDRS, Authorization="Bearer placeholder"),
                              msg())
    assert status == 200
    h = up.calls[0]["headers"]
    assert h["authorization"] == f"Bearer {UP_KEY}"
    assert "x-api-key" not in h and "anthropic-beta" not in h and "ua-value-abc" not in json.dumps(h)
    assert h["anthropic-version"] == ad.ANTHROPIC_VERSION
    assert up.calls[0]["path"] == "/v1/messages" and up.calls[0]["body"]["model"] == "glm-5.3"
    rec = ledger(tmp_path)[0]
    assert rec["credential"] == "placeholder" and rec["query_keys"] == ["beta"]
    assert {"authorization", "x-api-key", "anthropic-beta", "anthropic-version"} <= set(rec["dropped_header_names"])


def test_foreign_credential_stops_and_is_never_forwarded(up, tmp_path):
    d = director(tmp_path)
    status, _, _, _ = d.serve("POST", "/v1/messages", dict(HDRS, **{"x-api-key": FOREIGN}), msg())
    assert status == 401 and up.calls == [] and (tmp_path / "STOP").exists()
    assert ledger(tmp_path)[0]["credential"] == "foreign"
    status, _, _, _ = d.serve("POST", "/v1/messages", HDRS, msg())  # the stop file now refuses everything
    assert status == 503 and up.calls == []


@pytest.mark.parametrize("name,value", [("cookie", "session=abc"), ("Cookie", "placeholder"),
                                        ("proxy-authorization", "Bearer placeholder"),
                                        ("anthropic-api-key", FOREIGN)])
def test_every_credential_header_kind_stops(up, tmp_path, name, value):
    d = director(tmp_path)
    status, _, _, _ = d.serve("POST", "/v1/messages", dict(HDRS, **{name: value}), msg())
    assert status == 401 and up.calls == [] and (tmp_path / "STOP").exists()
    assert ledger(tmp_path)[0]["credential"] == "foreign"


def test_placeholder_anthropic_api_key_is_served(up, tmp_path):
    d = director(tmp_path)
    status, _, _, _ = d.serve("POST", "/v1/messages", dict(HDRS, **{"anthropic-api-key": "placeholder"}), msg())
    assert status == 200 and len(up.calls) == 1


def test_duplicate_authorization_headers_are_all_checked(up, tmp_path):
    d = director(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ad.make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    body = msg()
    c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
    c.putrequest("POST", "/v1/messages")
    for k, v in (("Authorization", f"Bearer {FOREIGN}"), ("Authorization", "Bearer placeholder"),
                 ("Content-Type", "application/json"), ("Content-Length", str(len(body)))):
        c.putheader(k, v)
    c.endheaders(body)
    r = c.getresponse()
    r.read()
    srv.shutdown()
    assert r.status == 401 and up.calls == [] and (tmp_path / "STOP").exists()


class Fatal(Exception):
    pass


@pytest.fixture
def fatal(monkeypatch):
    def boom(code):
        raise Fatal(code)
    monkeypatch.setattr(ad.os, "_exit", boom)


def test_key_in_a_reply_stops_before_the_reply_is_written(up, tmp_path, fatal):
    d = director(tmp_path)  # no --bodies-dir, the default
    up.replies = [(200, json.dumps({"model": "glm-5.3", "content": [{"type": "text", "text": UP_KEY}],
                                    "usage": {}}).encode())]
    with pytest.raises(Fatal):
        d.serve("POST", "/v1/messages", HDRS, msg())
    assert not (tmp_path / "ledger.jsonl").exists()


def test_key_in_a_stripped_field_name_never_reaches_the_strip_file(up, tmp_path, fatal):
    d = director(tmp_path)
    up.replies = [(400, json.dumps({"error": {"message": f"unknown field {UP_KEY}"}}).encode())]
    with pytest.raises(Fatal):
        d.serve("POST", "/v1/messages", HDRS, msg(**{UP_KEY: 1}))
    assert not (tmp_path / "strip.json").exists()


@pytest.mark.parametrize("line", [f"{UP_KEY} /v1/messages HTTP/1.1", f"POST /v1/messages {UP_KEY}"])
def test_stdlib_error_replies_echo_no_request_text(up, tmp_path, line):
    d = director(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ad.make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    with socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10) as c:
        c.sendall(f"{line}\r\nHost: x\r\nx-api-key: placeholder\r\nContent-Length: 0\r\n\r\n".encode())
        reply = b""
        while chunk := c.recv(65536):
            reply += chunk
    srv.shutdown()
    assert reply.split(b" ")[1] in (b"400", b"501") and UP_KEY.encode() not in reply and up.calls == []


def test_bad_content_length_and_handler_errors_leave_no_request_text(up, tmp_path, capfd, monkeypatch):
    d = director(tmp_path)
    srv = ad.Server(("127.0.0.1", 0), ad.make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    def send(length: str) -> bytes:
        with socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10) as c:
            c.sendall(f"POST /v1/messages HTTP/1.1\r\nHost: x\r\nx-api-key: placeholder\r\n"
                      f"Content-Length: {length}\r\n\r\n".encode())
            reply = b""
            while chunk := c.recv(65536):
                reply += chunk
        return reply

    reply = send(UP_KEY)
    assert reply.split(b" ")[1] == b"400" and UP_KEY.encode() not in reply and up.calls == []

    def boom(*a):
        raise ValueError(UP_KEY)
    monkeypatch.setattr(d, "serve", boom)
    send("0")
    srv.shutdown()
    err = capfd.readouterr().err
    assert UP_KEY not in err and "handler error ValueError" in err


def test_driver_paths_are_absolute_and_never_combine_runs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root, ev = run_s4.fresh_paths("scratch", "ev")
    assert root.is_absolute() and ev.is_absolute() and root == tmp_path / "scratch"
    (tmp_path / "ev").mkdir()
    (tmp_path / "ev" / "director-ledger.jsonl").write_text("{}\n")
    with pytest.raises(SystemExit):
        run_s4.fresh_paths("scratch", "ev")


def test_summary_of_a_run_stopped_before_the_injected_429(tmp_path):
    step = {k: None for k in ("mode", "marker_exit", "exit", "wall_s", "expected_tool", "check", "check_ok",
                              "expected_tool_ok", "session", "context_window", "compact_boundaries", "mcp_servers",
                              "num_turns")}
    step |= {"step": "t1", "valid": False, "non_loopback_endpoints": 0, "tool_calls": [], "system_events": []}
    (tmp_path / "run.json").write_text(json.dumps({"claude_version": "x", "model": "glm-5.3", "alias": "a",
                                                   "steps": [step]}))
    rec = {"run": "t1", "t": 1.0, "upstream": [], "status": 401, "path": "/v1/messages", "credential": "foreign",
           "dropped_header_names": ["x-api-key"], "query_keys": []}
    (tmp_path / "director-ledger.jsonl").write_text(json.dumps(rec) + "\n")
    s = summarise.summary(tmp_path)
    assert s["injected_429"] is None and s["valid_steps"] == 0 and s["statuses"] == {401: 1}
    (tmp_path / "director-ledger.jsonl").write_text(json.dumps(dict(rec, injected_429=True, status=429)) + "\n")
    assert summarise.summary(tmp_path)["injected_429"] == {"step": "t1", "next_request_after_s": None,
                                                           "next_status": None}
    (tmp_path / "director-ledger.jsonl").unlink()  # no request reached the director
    assert summarise.summary(tmp_path)["requests"] == 0


def test_metadata_user_id_dropped_unless_kept(up, tmp_path):
    d = director(tmp_path)
    d.serve("POST", "/v1/messages", HDRS, msg(metadata={"user_id": "uid-123"}))
    d.serve("POST", "/v1/messages", HDRS, msg(metadata={"user_id": "uid-123", "other": 1}))
    assert "metadata" not in up.calls[0]["body"] and up.calls[1]["body"]["metadata"] == {"other": 1}
    director(tmp_path, "--keep-user-id").serve("POST", "/v1/messages", HDRS, msg(metadata={"user_id": "uid-123"}))
    assert up.calls[2]["body"]["metadata"] == {"user_id": "uid-123"}


def test_ledger_holds_no_header_value_or_key(up, tmp_path):
    d = director(tmp_path)
    up.replies = [(200, SSE)]
    d.serve("POST", "/v1/messages", dict(HDRS, Authorization="Bearer placeholder"), msg(stream=True))
    d.serve("POST", "/v1/messages", dict(HDRS, **{"x-api-key": FOREIGN}), msg())
    d.serve("GET", "/v1/models", HDRS, b"")
    text = (tmp_path / "ledger.jsonl").read_text()
    for value in (UP_KEY, FOREIGN, BETA, "ua-value-abc", "Bearer", "2023-06-01", "application/json"):
        assert value not in text
    rec = ledger(tmp_path)[0]
    assert rec["usage"] == {"input_tokens": 42, "output_tokens": 7} and rec["tool_use"] == ["Bash"]
    assert rec["stream"] is True and rec["stop_reason"] == "tool_use" and "messages" in rec["body_keys"]


def test_strip_and_retry_then_fixed_strip_list(up, tmp_path):
    d = director(tmp_path)
    up.replies = [(400, b'{"error":{"message":"Unrecognized field: context_management"}}'), (200, SSE)]
    status, _, _, _ = d.serve("POST", "/v1/messages", HDRS, msg(stream=True, context_management={"x": 1}))
    assert status == 200 and len(up.calls) == 2
    assert "context_management" in up.calls[0]["body"] and "context_management" not in up.calls[1]["body"]
    rec = ledger(tmp_path)[0]
    assert rec["stripped"] == ["context_management"] and rec["upstream"][0]["fields"] == ["context_management"]
    assert json.loads((tmp_path / "strip.json").read_text()) == ["context_management"]
    d2 = director(tmp_path)  # a restarted director keeps the list: the next request is sent clean
    d2.serve("POST", "/v1/messages", HDRS, msg(context_management={"x": 1}))
    assert len(up.calls) == 3 and "context_management" not in up.calls[2]["body"]


def test_400_naming_a_protected_field_is_not_stripped_and_text_not_forwarded(up, tmp_path):
    d = director(tmp_path)
    up.replies = [(400, b'{"error":{"message":"secret-upstream-text: messages invalid"}}')]
    status, _, data, _ = d.serve("POST", "/v1/messages", HDRS, msg())
    assert status == 400 and len(up.calls) == 1 and b"secret-upstream-text" not in data
    assert ledger(tmp_path)[0]["stripped"] == []


def test_injected_429_never_calls_upstream(up, tmp_path):
    d = director(tmp_path, "--inject-429", "2", "--retry-after", "4")
    assert d.serve("POST", "/v1/messages", HDRS, msg())[0] == 200
    status, _, data, extra = d.serve("POST", "/v1/messages", HDRS, msg())
    assert status == 429 and extra == {"retry-after": "4"} and len(up.calls) == 1
    assert json.loads(data)["error"]["type"] == "rate_limit_error"
    assert d.serve("POST", "/v1/messages", HDRS, msg())[0] == 200
    assert [r.get("injected_429", False) for r in ledger(tmp_path)] == [False, True, False]
    assert json.loads((tmp_path / "budget.json").read_text())["total"] == 2


def test_upstream_429_retried_with_backoff(up, tmp_path):
    d = director(tmp_path)
    up.replies = [(429, b'{"error":{"message":"busy"}}'), (529, b"{}"), (200, SSE)]
    status, _, _, _ = d.serve("POST", "/v1/messages", HDRS, msg(stream=True))
    assert status == 200 and len(up.calls) == 3
    assert [u["status"] for u in ledger(tmp_path)[0]["upstream"]] == [429, 529, 200]


def test_unknown_paths_get_logged_404(up, tmp_path):
    d = director(tmp_path)
    for method, path in (("GET", "/v1/models"), ("POST", "/v1/complete"), ("GET", "/v1/messages")):
        assert d.serve(method, path, HDRS, b"{}")[0] == 404
    assert up.calls == [] and [r["status"] for r in ledger(tmp_path)] == [404, 404, 404]


def test_count_tokens_forwarded(up, tmp_path):
    d = director(tmp_path)
    status, _, _, _ = d.serve("POST", "/v1/messages/count_tokens", HDRS, msg())
    assert status == 200 and up.calls[0]["path"] == "/v1/messages/count_tokens"
    assert ledger(tmp_path)[0]["usage"] == {"input_tokens": 3}


def test_call_cap_and_stop_file(up, tmp_path):
    d = director(tmp_path, "--max-calls", "1")
    assert d.serve("POST", "/v1/messages", HDRS, msg())[0] == 200
    assert d.serve("POST", "/v1/messages", HDRS, msg())[0] == 503 and len(up.calls) == 1
    assert ledger(tmp_path)[1]["upstream"] == [{"status": 0, "category": "cap"}]
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "STOP").touch()
    d2 = director(tmp_path / "x")
    assert d2.serve("POST", "/v1/messages", HDRS, msg())[0] == 503 and len(up.calls) == 1


def test_http_round_trip_with_retry_after_header(up, tmp_path):
    d = director(tmp_path, "--inject-429", "1")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), ad.make_handler(d))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/v1/messages", data=msg(),
                                 headers=HDRS, method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 429 and e.value.headers["retry-after"] == "3"
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200 and json.loads(r.read())["model"] == "glm-5.3"
    srv.shutdown()


def test_mcp_fixture_protocol():
    init = mcp_fixture.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["protocolVersion"] == "2025-06-18" and "tools" in init["result"]["capabilities"]
    assert mcp_fixture.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    assert mcp_fixture.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"][0]["name"] \
        == "fixture_lookup"
    ok = mcp_fixture.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "fixture_lookup", "arguments": {"key": "gamma"}}})["result"]
    assert ok == {"content": [{"type": "text", "text": "gamma = G-5582"}], "isError": False}
    bad = mcp_fixture.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                              "params": {"name": "fixture_lookup", "arguments": {"key": "zeta"}}})["result"]
    assert bad["isError"] is True
    assert mcp_fixture.handle({"jsonrpc": "2.0", "id": 5, "method": "resources/list"})["error"]["code"] == -32601
