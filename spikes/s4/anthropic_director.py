"""Spike S4 director: an Anthropic Messages-wire store-and-forward proxy on 127.0.0.1.

It forwards POST /v1/messages (streaming or not) and POST /v1/messages/count_tokens to an upstream
named only by environment variables, and answers every other method or path with a logged 404,
never forwarding it. Each request appends one JSONL ledger record: method, path, model, stream
flag, sorted body key set, status, timing, usage and the body fields it stripped. The ledger holds
no body text and no header value.

Credentials: every inbound Authorization, x-api-key, cookie and anthropic-* header is dropped
(its value is only compared with the placeholder, never stored). A credential other than the
placeholder stops the director (stop condition). The upstream key is sent as
"Authorization: Bearer". Upstream error text is never forwarded to the harness.

Upstream: BICENTENNIAL_UPSTREAM_ANTHROPIC_URL (base; the request path is appended) and
BICENTENNIAL_UPSTREAM_KEY. Optional BICENTENNIAL_BUSY_CMD: GLM use pauses while its "glm" is true.
Spike-grade: stdlib only.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FORWARD = {"/v1/messages", "/v1/messages/count_tokens"}
DROP = re.compile(r"^(authorization|x-api-key|cookie|proxy-authorization|anthropic-.*)$", re.IGNORECASE)
PLACEHOLDER = "placeholder"
PROTECTED = {"model", "messages", "max_tokens", "stream", "system", "tools"}  # never stripped
ANTHROPIC_VERSION = "2023-06-01"
BACKOFF = (5, 15, 45)  # upstream 429/503/529, as in the other directors
ERR_TYPE = {400: "invalid_request_error", 401: "authentication_error", 404: "not_found_error",
            429: "rate_limit_error", 529: "overloaded_error"}


def err_body(status: int, msg: str) -> bytes:
    return json.dumps({"type": "error", "error": {"type": ERR_TYPE.get(status, "api_error"),
                                                  "message": f"director: {msg}"}}).encode()


CRED = ("x-api-key", "authorization", "anthropic-api-key", "proxy-authorization", "cookie")
NO_PLACEHOLDER = ("proxy-authorization", "cookie")  # any value of these is foreign


def header_pairs(headers) -> list[tuple[str, str]]:
    """Every (name, value) occurrence; a dict has one per name, an HTTP message may repeat a name."""
    return list(headers.items()) if isinstance(headers, dict) else list(headers)


def credential_class(headers) -> str:
    """placeholder, absent or foreign, over every occurrence; the value itself is never returned or stored."""
    vals = [(k.lower(), v.strip()) for k, v in header_pairs(headers) if k.lower() in CRED]
    if not vals:
        return "absent"
    ok = all(k not in NO_PLACEHOLDER and v in (PLACEHOLDER, f"Bearer {PLACEHOLDER}") for k, v in vals)
    return "placeholder" if ok else "foreign"


def parse_reply(data: bytes, stream: bool) -> dict:
    """Usage, served model, stop reason and tool_use names from a JSON or SSE reply."""
    out = {"usage": {}, "served_model": None, "stop_reason": None, "tool_use": []}
    evs = []
    if stream:
        for line in data.decode("utf-8", "replace").splitlines():
            if line.startswith("data:"):
                try:
                    evs.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    else:
        try:
            msg = json.loads(data)
        except ValueError:
            return out
        evs = [{"type": "message_start", "message": msg}, {"type": "message_delta", "usage": {},
                                                           "delta": {"stop_reason": msg.get("stop_reason")}}]
        evs += [{"type": "content_block_start", "content_block": b} for b in msg.get("content") or []]
        if "input_tokens" in msg and "content" not in msg:  # count_tokens reply
            out["usage"] = {"input_tokens": msg["input_tokens"]}
    for ev in evs:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") == "message_start":
            m = ev.get("message") or {}
            out["served_model"] = m.get("model")
            out["usage"].update({k: v for k, v in (m.get("usage") or {}).items() if isinstance(v, int)})
        elif ev.get("type") == "message_delta":
            out["usage"].update({k: v for k, v in (ev.get("usage") or {}).items() if isinstance(v, int)})
            out["stop_reason"] = (ev.get("delta") or {}).get("stop_reason") or out["stop_reason"]
        elif ev.get("type") == "content_block_start":
            b = ev.get("content_block") or {}
            if b.get("type") == "tool_use":
                out["tool_use"].append(b.get("name"))
    return out


class Budget:
    """Upstream call counter in a file (shared across director restarts), under a file lock."""
    def __init__(self, path: Path, cap: int):
        self.path, self.cap = path, cap

    def take(self) -> bool:
        with open(self.path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            raw = f.read().strip()
            n = json.loads(raw)["total"] if raw else 0
            if n >= self.cap:
                return False
            f.seek(0), f.truncate(), f.write(json.dumps({"total": n + 1, "cap": self.cap}))
            return True


class Director:
    def __init__(self, a):
        self.a, self.lock, self.n, self.n_messages = a, threading.Lock(), 0, 0
        self.url = os.environ.get("BICENTENNIAL_UPSTREAM_ANTHROPIC_URL", "").rstrip("/")
        self.key = os.environ.get("BICENTENNIAL_UPSTREAM_KEY", "")
        self.budget = Budget(Path(a.budget_file), a.max_calls)
        self.strip_file = Path(a.strip_file)
        self.strip = set(json.loads(self.strip_file.read_text())) if self.strip_file.exists() else set()
        self.ledger, self.stop_file = Path(a.ledger), Path(a.stop_file)
        self.bodies = Path(a.bodies_dir) if a.bodies_dir else None
        self.marker = {"t": 0.0, "glm": False}

    # ---- persistence ------------------------------------------------------------------------------
    def _guard(self, data: bytes) -> bytes:
        if self.key and self.key.encode() in data:
            os.write(2, b"FATAL: the upstream credential reached a write; stopping\n")
            os._exit(3)
        return data

    def log(self, rec: dict):
        with self.lock:
            line = self._guard(json.dumps(rec, sort_keys=True).encode() + b"\n")
            with open(self.ledger, "ab") as f:
                f.write(line)

    def _body(self, seq: int, tag: str, data: bytes):  # full bodies: regenerable scratch only
        if self.bodies:
            self.bodies.mkdir(parents=True, exist_ok=True)
            (self.bodies / f"{seq:04d}.{tag}").write_bytes(self._guard(data))

    def _glm_paused(self) -> bool:
        cmd = os.environ.get("BICENTENNIAL_BUSY_CMD")
        if cmd and time.time() - self.marker["t"] > 60:
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30, check=False)
                self.marker = {"t": time.time(), "glm": bool(json.loads(r.stdout.strip() or "{}").get("glm"))}
            except (subprocess.SubprocessError, ValueError):
                self.marker = {"t": time.time(), "glm": False}
        return self.marker["glm"]

    # ---- upstream ---------------------------------------------------------------------------------
    def send_upstream(self, path: str, wire: dict) -> tuple[int, str, bytes]:
        req = urllib.request.Request(self.url + path, data=json.dumps(wire).encode(), method="POST", headers={
            "Content-Type": "application/json", "anthropic-version": ANTHROPIC_VERSION,
            "Authorization": f"Bearer {self.key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.a.timeout) as r:
                return r.status, r.headers.get("Content-Type", "application/json"), r.read()
        except urllib.error.HTTPError as e:
            data = e.read()
            e.close()
            return e.code, "application/json", data
        except Exception as e:  # noqa: BLE001  network error: the class only (messages can carry the host)
            return -1, "text/plain", type(e).__name__.encode()

    def named_fields(self, wire: dict, text: str) -> set[str]:
        return {k for k in wire if k not in PROTECTED and re.search(rf"(?<![\w-]){re.escape(k)}(?![\w-])", text)}

    def forward(self, path: str, body: dict, rec: dict) -> tuple[int, str, bytes]:
        attempts, waits = rec["upstream"], list(BACKOFF)
        while True:
            wire = {k: v for k, v in body.items() if k not in self.strip}
            wire["model"] = self.a.model
            if isinstance(wire.get("metadata"), dict) and not self.a.keep_user_id:
                md = {k: v for k, v in wire["metadata"].items() if k != "user_id"}
                wire.pop("metadata")
                if md:
                    wire["metadata"] = md
            rec["stripped"] = sorted(set(body) & self.strip)
            if self.stop_file.exists():
                return 503, "application/json", err_body(503, "stopped")
            if self._glm_paused():
                attempts.append({"status": 0, "category": "glm_paused"})
                return 503, "application/json", err_body(503, "upstream paused")
            if not self.budget.take():
                attempts.append({"status": 0, "category": "cap"})
                return 503, "application/json", err_body(503, "call cap reached")
            t0 = time.monotonic()
            status, ctype, data = self.send_upstream(path, wire)
            att = {"status": status, "t_ms": round((time.monotonic() - t0) * 1000)}
            attempts.append(att)
            self._body(rec["seq"], f"up{len(attempts)}", data)
            if status == 400:
                new = self.named_fields(wire, data.decode("utf-8", "replace")) - self.strip
                if new:  # strip the named field on a retry, and from every later request
                    att["category"] = "param_rejected"
                    att["fields"] = sorted(new)
                    with self.lock:
                        self.strip |= new
                        self.strip_file.write_bytes(self._guard(json.dumps(sorted(self.strip)).encode()))
                    continue
            if status in (429, 503, 529) and waits:
                att["category"] = "retry"
                time.sleep(waits.pop(0) * self.a.backoff_scale)
                continue
            return status, ctype, data

    # ---- one request ------------------------------------------------------------------------------
    def serve(self, method: str, path: str, headers: dict, raw: bytes) -> tuple[int, str, bytes, dict]:
        """Returns (status, content type, reply bytes, extra headers) and appends the ledger record."""
        base, _, query = path.partition("?")
        with self.lock:
            self.n += 1
            seq = self.n
            if method == "POST" and base == "/v1/messages":
                self.n_messages += 1
            nth = self.n_messages
        cred = credential_class(headers)
        rec = {"seq": seq, "run": self.a.run, "t": time.time(), "method": method, "path": base,
               "query_keys": sorted(q.split("=")[0] for q in query.split("&") if q), "credential": cred,
               "dropped_header_names": sorted({k.lower() for k, _ in header_pairs(headers) if DROP.match(k)}),
               "upstream": []}
        t0, extra = time.monotonic(), {}
        if cred == "foreign":  # stop condition: never forwarded, and the director stops serving
            self.stop_file.touch()
            status, ctype, data = 401, "application/json", err_body(401, "unexpected credential; stopped")
        elif method != "POST" or base not in FORWARD:
            status, ctype, data = 404, "application/json", err_body(404, "not found")
        else:
            try:
                body = json.loads(raw)
            except ValueError:
                body = None
            if not isinstance(body, dict):
                status, ctype, data = 400, "application/json", err_body(400, "body is not a JSON object")
            else:
                self._body(seq, "req", raw)
                stream = bool(body.get("stream")) and base == "/v1/messages"
                rec.update(model_in=body.get("model"), model_out=self.a.model, stream=stream,
                           body_keys=sorted(body), n_messages=len(body.get("messages") or []),
                           n_tools=len(body.get("tools") or []))
                if base == "/v1/messages" and self.a.inject_429 and nth == self.a.inject_429:
                    rec["injected_429"] = True
                    status, ctype, data = 429, "application/json", err_body(429, "rate limited (injected)")
                    extra = {"retry-after": str(self.a.retry_after)}
                else:
                    status, ctype, data = self.forward(base, body, rec)
                    if 200 <= status < 300:
                        rec.update(parse_reply(data, stream))
                    else:  # upstream error text never reaches the harness
                        status = status if status > 0 else 502
                        ctype, data = "application/json", err_body(status, f"upstream refused ({status})")
        rec.update(status=status, t_ms=round((time.monotonic() - t0) * 1000))
        self._guard(ctype.encode() + b"\n" + data)  # the reply is a write too
        self.log(rec)
        return status, ctype, data, extra


def make_handler(d: Director):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # the ledger is the log
            pass

        def _do(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            status, ctype, data, extra = d.serve(self.command, self.path, self.headers.items(), raw)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        do_POST = do_GET = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = _do

    return H


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=0)
    p.add_argument("--port-file", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--strip-file", required=True)
    p.add_argument("--stop-file", required=True)
    p.add_argument("--bodies-dir", default="")
    p.add_argument("--run", default="s4")
    p.add_argument("--model", default="glm-5.3")
    p.add_argument("--max-calls", type=int, default=120)
    p.add_argument("--inject-429", type=int, default=0, help="answer the n-th /v1/messages request with a 429")
    p.add_argument("--retry-after", type=int, default=3)
    p.add_argument("--backoff-scale", type=float, default=1.0)
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--keep-user-id", action="store_true", help="forward metadata.user_id (dropped by default)")
    return p


def main():
    a = build_parser().parse_args()
    if not os.environ.get("BICENTENNIAL_UPSTREAM_KEY") or not os.environ.get("BICENTENNIAL_UPSTREAM_ANTHROPIC_URL"):
        sys.exit("needs the upstream environment (run under the helper)")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Director(a)))
    tmp = Path(a.port_file + ".tmp")
    tmp.write_text(str(srv.server_address[1]))
    os.replace(tmp, a.port_file)
    srv.serve_forever()


if __name__ == "__main__":
    main()
