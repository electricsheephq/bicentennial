"""Minimal director for spike S6a: an OpenAI chat-completions proxy on 127.0.0.1.

For every request it classifies the role, serves scripted assistant turns by cursor, runs a
write turn before each scripted turn, forwards live roles to an upstream named only by
environment variables, and appends one hash-chained record to a JSONL ledger. Request and
response bodies are stored by content hash (zstd). Spike-grade: stdlib only, Python 3.14+.

Upstream: BICENTENNIAL_UPSTREAM_OPENAI_URL (base; "/chat/completions" is appended) and
BICENTENNIAL_UPSTREAM_KEY. Incoming Authorization headers are never read, stored or forwarded.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import re
import select
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from compression import zstd
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROLES = ("replay_main", "write_turn", "summariser", "probe_main", "aux", "unknown")
WRITE_TOOLS = {"memory"}  # Hermes native memory's declared write tool (provisional until C-6)
# PROVISIONAL write-turn suffix (PREREG §10); the frozen text is completion slot C-6.
WRITE_SUFFIX = (
    "[Memory checkpoint, provisional text] Before this turn is answered, decide whether anything in the "
    "conversation so far is worth keeping in long-term memory for future sessions. If so, call the memory "
    "tool now. If not, reply with the single word: none. Any text you write here is discarded.")
REVIEW_PREFIX = "Review the conversation above and"  # Hermes background-review fork (shape signature)
# The declared wire adaptations (alias substitution, non-streaming). Every other harness key, such as
# reasoning_effort, is forwarded unchanged unless the upstream rejects it by name (omitted, recorded).
TRANSPORT_KEYS = {"model", "stream", "stream_options"}
MSG_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}


def canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class Guard:
    """Refuses to persist anything containing the upstream credential (stop condition)."""
    def __init__(self):
        self.secret = os.environ.get("BICENTENNIAL_UPSTREAM_KEY", "").encode()

    def check(self, data: bytes) -> bytes:
        if self.secret and self.secret in data:
            os.write(2, b"FATAL: credential reached a ledger write; stopping\n")
            os._exit(3)
        return data


class Ledger:
    """Append-only JSONL; each record carries prev_hash and its own hash over the canonical body."""
    def __init__(self, root: Path, guard: Guard):
        self.root, self.guard, self.lock = root, guard, threading.Lock()
        (root / "blobs").mkdir(parents=True, exist_ok=True)
        self.path, self.prev, self.seq = root / "ledger.jsonl", "0" * 64, 0
        if self.path.exists():  # resume the chain only from an intact ledger; a torn tail fails closed
            raw = self.path.read_text()
            if raw and not raw.endswith("\n"):
                raise SystemExit(f"{self.path}: last record is torn; refusing to resume this ledger")
            for line in raw.splitlines():
                rec = json.loads(line)
                self.prev, self.seq = rec["hash"], rec["seq"]

    def blob(self, obj) -> str:
        data = self.guard.check(canon(obj))
        h = hashlib.sha256(data).hexdigest()
        p = self.root / "blobs" / h[:2] / f"{h}.json.zst"
        if not p.exists():
            p.parent.mkdir(exist_ok=True)
            tmp = p.with_suffix(f".tmp{threading.get_ident()}")
            tmp.write_bytes(zstd.compress(data))
            os.replace(tmp, p)
        return h

    def append(self, rec: dict) -> dict:
        with self.lock:
            self.seq += 1
            rec = {"seq": self.seq, "prev_hash": self.prev, **rec}
            rec["hash"] = hashlib.sha256(self.prev.encode() + canon(rec)).hexdigest()
            line = self.guard.check(canon(rec)) + b"\n"
            with open(self.path, "ab") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self.prev = rec["hash"]
            return rec


class Budget:
    """Upstream call counter shared by every director and the ramp (file lock)."""
    def __init__(self, path: Path, cap: int):
        self.path, self.cap = path, cap

    def take(self, run: str, kind: str) -> bool:
        with open(self.path, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            raw = f.read()
            b = json.loads(raw) if raw.strip() else {"total": 0, "by_run": {}, "by_kind": {}}
            if b["total"] >= self.cap:
                return False
            b["total"] += 1
            b["by_run"][run] = b["by_run"].get(run, 0) + 1
            b["by_kind"][kind] = b["by_kind"].get(kind, 0) + 1
            f.seek(0), f.truncate(), f.write(json.dumps(b))
            return True


_marker = {"t": 0.0, "state": None}


def marker_state() -> dict:
    """The gauntlet busy marker (cached 60 s): exit code and glm flag."""
    if time.time() - _marker["t"] > 60:
        cmd = os.environ.get("BICENTENNIAL_BUSY_CMD")
        st = {"exit": None, "glm": None}
        if cmd:
            try:
                r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                st = {"exit": r.returncode, "glm": bool(json.loads(r.stdout.strip() or "{}").get("glm"))}
            except (subprocess.SubprocessError, ValueError):
                pass
        _marker.update(t=time.time(), state=st)
    return dict(_marker["state"])


def refusal_category(status: int, text: str) -> str:
    t = text.lower()
    if re.search(r"quota|balance|usage limit|insufficient|exceeded your|\b(1113|1304|1308|1310)\b", t):
        return "quota"
    if re.search(r"overload|\b1305\b", t):
        return "overload"
    if re.search(r"concurren|\b1302\b", t):
        return "concurrency"
    if status == 429 or re.search(r"rate|frequen|too many|\b1303\b", t):
        return "rate"
    return "other"


def redact(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", text, flags=re.I)
    return re.sub(r"\d{6,}", "<n>", text)[:600]


class Director:
    def __init__(self, a):
        self.a, self.guard = a, Guard()
        self.ledger = Ledger(Path(a.ledger_dir), self.guard)
        self.budget = Budget(Path(a.budget_file), a.budget_cap)
        life = json.loads(Path(a.life).read_text())
        self.expected = [{"kind": "replay", "session": s["index"], "turn": i, **t}
                         for s in life["sessions"] for i, t in enumerate(s["turns"], 1)]
        self.expected += [{"kind": "probe", "session": p["index"], "turn": i, **t}
                          for p in life.get("probes", []) for i, t in enumerate(p["turns"], 1)]
        self.cursor, self.current = 0, None
        self.id_roles: dict[str, tuple[str, str]] = {}  # tool_call_id -> (role, subrole)
        self.pending: dict[str, dict] = {}  # director-issued write ids -> scripted turn
        self.lock, self.inflight, self.n_ids = threading.Lock(), 0, 0
        self.write_turns, self.measure_overhead = a.write_turns, a.measure_overhead
        self.quota_streak, self.stopped, self.write_failures = 0, False, 0
        self.omit, self.rejections = set(), []  # keys the upstream rejected by name: omitted from then on
        self.rewrites = json.loads(Path(a.lane_rewrite).read_text()) if a.lane_rewrite else []
        self.url = os.environ.get("BICENTENNIAL_UPSTREAM_OPENAI_URL", "").rstrip("/") + "/chat/completions"
        self.key = os.environ.get("BICENTENNIAL_UPSTREAM_KEY", "")

    # ---- upstream ------------------------------------------------------------------------------
    def upstream_retry(self, body: dict, kind: str, rec: dict) -> dict:
        """Director-originated calls retry transient refusals twice (5 s, 15 s); each try is counted."""
        for wait in (5, 15, None):
            up = self.upstream(body, kind)
            rec["upstream"].append(self._strip(up))
            if up.get("category", "").startswith("param_rejected"):  # repeat once without the key
                up = self.upstream(body, kind)
                rec["upstream"].append(self._strip(up))
            if up["ok"] or up["category"] not in ("overload", "concurrency", "rate") or wait is None:
                return up
            time.sleep(wait)

    def upstream(self, body: dict, kind: str) -> dict:
        """One counted upstream call. Returns a sub-record; never raises; never logs the URL or key."""
        m = marker_state()
        waited = 0.0
        while m.get("glm") and waited < 7200:
            time.sleep(60), _marker.update(t=0)
            waited += 60
            m = marker_state()
        sub = {"kind": kind, "model": self.a.model, "marker": m, "glm_wait_s": waited, "load": os.getloadavg()}
        if self.stopped or m.get("glm") or not self.budget.take(self.a.run, kind):
            return {**sub, "status": 0, "category": "budget_or_stop", "ok": False, "t_ms": 0}
        wire = {k: v for k, v in body.items() if k not in TRANSPORT_KEYS | self.omit}
        wire["messages"] = [{k: v for k, v in msg.items() if k not in self.omit} for msg in body["messages"]]
        n_rw = 0
        for msg in wire["messages"]:  # disclosed lane-compatibility rewrite (off unless --lane-rewrite)
            for old, new in self.rewrites:
                if isinstance(msg.get("content"), str) and old in msg["content"]:
                    n_rw += msg["content"].count(old)
                    msg["content"] = msg["content"].replace(old, new)
        sub["lane_rewrites"] = n_rw
        wire.update(model=self.a.model, stream=False)
        sub["dropped_keys"] = sorted(self.omit & (set(body) | {k for m in body["messages"] for k in m}))
        sub["req"], sub["wire"] = self.ledger.blob(wire), wire
        if self.a.mode == "stub":
            return {**sub, **self._stub(wire, kind)}
        req = urllib.request.Request(self.url, data=json.dumps(wire).encode(), method="POST", headers={
            "Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        t0 = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=self.a.timeout) as r:
                resp, status = json.loads(r.read()), r.status
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            e.close()
            cat = refusal_category(e.code, text)
            named = {k for k in set(wire) | {k for m in wire["messages"] for k in m} if k not in MSG_KEYS | {
                "messages", "model", "stream", "tools"} and re.search(rf"(?<!\w){k}(?!\w)", text)}
            if e.code == 400 and named:  # record the exact rejection; the caller repeats without the key
                self.omit |= named
                cat = "param_rejected:" + ",".join(sorted(named))
                self.rejections.append({"keys": sorted(named), "status": e.code, "body_redacted": redact(text)})
            self._streak(cat)
            return {**sub, "status": e.code, "category": cat, "ok": False, "body_redacted": redact(text),
                    "t_ms": round((time.monotonic() - t0) * 1000)}
        except Exception as e:  # network errors: record the class only (messages can carry the host)
            return {**sub, "status": -1, "category": f"error:{type(e).__name__}", "ok": False,
                    "t_ms": round((time.monotonic() - t0) * 1000)}
        self.quota_streak = 0
        sub.update(status=status, ok=True, t_ms=round((time.monotonic() - t0) * 1000), resp=self.ledger.blob(resp),
                   usage=resp.get("usage"), served_model=resp.get("model"), body=resp)
        return sub

    def _streak(self, cat: str):
        self.quota_streak = self.quota_streak + 1 if cat == "quota" else 0
        if self.quota_streak >= 3:
            self.stopped = True

    def _stub(self, wire, kind):  # development only: no network; never used for a measurement
        tools = [t["function"]["name"] for t in wire.get("tools") or []]
        msg = {"role": "assistant", "content": f"stub {kind}"}
        if kind == "write_turn" and "memory" in tools and len(wire["messages"]) % 3 == 0:
            msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "stub", "type": "function", "function": {
                "name": "memory", "arguments": json.dumps({"action": "add", "target": "memory",
                                                           "content": "stub note"})}}]}
        resp = {"model": "stub", "choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}
        return {"status": 200, "ok": True, "t_ms": 0, "resp": self.ledger.blob(resp), "usage": resp["usage"],
                "body": resp}

    # ---- classification ---------------------------------------------------------------------------
    def classify(self, path: str, body: dict) -> tuple[str, str, dict | None]:
        msgs = body.get("messages") or []
        last = msgs[-1] if msgs else {}
        if last.get("role") == "tool":  # 1. cursor: a tool-call id this director issued or forwarded
            ids = []  # the trailing tool results and the calls they answer (the harness may split one call)
            for msg in reversed(msgs):
                if msg.get("role") == "tool":
                    ids.append(msg.get("tool_call_id", ""))
                    continue
                if msg.get("role") == "assistant":
                    ids += [tc.get("id", "") for tc in msg.get("tool_calls") or []]
                break
            for tid in ids:
                if tid in self.id_roles:
                    return self.id_roles[tid][0], self.id_roles[tid][1], self.pending.get(tid)
        m = re.match(r"^/aux/([a-z_]+)/", path)  # 2. alias: the per-task base URL and model name
        if m:
            return ("summariser", "compression", None) if m.group(1) == "compression" else ("aux", m.group(1), None)
        text = _text(last.get("content")) if last.get("role") == "user" else ""
        if text and self.cursor < len(self.expected) and self.expected[self.cursor]["user"] in text:  # 1. cursor
            turn = self.expected[self.cursor]
            return ("replay_main" if turn["kind"] == "replay" else "probe_main"), "cursor", turn
        if text and self.current and self.current["user"] in text:  # the harness re-sent the current turn
            return ("replay_main" if self.current["kind"] == "replay" else "probe_main"), "retry", self.current
        if text.startswith(REVIEW_PREFIX):  # 3. shape signature
            return "aux", "background_review", None
        return "unknown", "", None

    # ---- serving ----------------------------------------------------------------------------------
    def handle(self, path: str, body: dict) -> tuple[int, dict | None, dict]:
        with self.lock:
            role, sub, turn = self.classify(path, body)
            if role in ("replay_main", "probe_main") and sub == "cursor":
                self.cursor, self.current = self.cursor + 1, turn
        rec = {"role": role, "subrole": sub, "cursor": turn and {"session": turn["session"], "turn": turn["turn"]},
               "model_in": body.get("model"), "n_messages": len(body.get("messages") or []),
               "n_tools": len(body.get("tools") or []), "req_chars": len(canon(body)), "upstream": []}
        if role == "unknown":
            return 400, {"error": {"message": "director: unclassified request refused (fail closed)"}}, rec
        if role == "replay_main" and sub == "retry":  # served from the script; no second write turn
            rec["served"] = "script_retry"
            return 200, self._resp(body, {"role": "assistant", "content": turn["assistant"]}), rec
        if role in ("replay_main", "write_turn"):
            if role == "replay_main" and self.measure_overhead:
                self.measure_overhead = False
                probe = dict(body, max_tokens=1)
                self.upstream_retry(probe, "overhead_measure", rec)
                rec["overhead_chars"] = {"system": len(_text(body["messages"][0].get("content"))),
                                         "tools_json": len(canon(body.get("tools") or []))}
            if role == "replay_main" and self.write_turns:
                msg = self.write_turn(body, turn, rec)
                if msg:
                    return 200, self._resp(body, msg), rec
            msg = {"role": "assistant", "content": turn["assistant"]}
            rec["served"] = "script"
            return 200, self._resp(body, msg), rec
        # live roles: summariser, aux, probe_main
        kind = {"summariser": "summariser", "probe_main": "probe"}.get(role, "aux")
        up = self.upstream(body, kind)
        rec["upstream"].append(self._strip(up))
        if up.get("category", "").startswith("param_rejected"):  # repeat once without the key
            up = self.upstream(body, kind)
            rec["upstream"].append(self._strip(up))
        if not up["ok"]:
            code = up["status"] if up["status"] > 0 else 503
            return code, {"error": {"message": f"director: upstream refused ({up['category']})"}}, rec
        resp = up["body"]
        for tc in (resp["choices"][0]["message"].get("tool_calls") or []):
            self.id_roles[tc["id"]] = (role, "tool_results" if sub in ("cursor", "retry") else sub)
        rec["served"] = "forward"
        return 200, self._stream_or_json(body, resp), rec

    def write_turn(self, body: dict, turn: dict, rec: dict) -> dict | None:
        """PREREG §10: the harness's own request plus the uniform suffix, tools filtered to write tools."""
        wt = dict(body)
        wt["messages"] = list(body["messages"]) + [{"role": "user", "content": WRITE_SUFFIX}]
        wt["tools"] = [t for t in body.get("tools") or [] if t.get("function", {}).get("name") in WRITE_TOOLS]
        if not wt["tools"]:
            return None
        up = self.upstream_retry(wt, "write_turn", rec)
        # readback on the forwarded body: the harness request plus the suffix and the tool filter, with
        # only the declared adaptations; an omitted (rejected) key fails it
        expect = {k: v for k, v in body.items() if k not in TRANSPORT_KEYS}
        rec["write_turn_readback"] = up.get("wire") == expect | {
            "messages": wt["messages"], "tools": wt["tools"], "model": self.a.model, "stream": False}
        if not up["ok"]:
            rec["write_turn_failed"] = up["category"]
            self.write_failures += 1  # the replay driver reads this and stops the run
            return None
        calls = [tc for tc in up["body"]["choices"][0]["message"].get("tool_calls") or []
                 if tc.get("function", {}).get("name") in WRITE_TOOLS]
        rec["write_calls"] = len(calls)
        if not calls:
            return None
        out = []
        with self.lock:
            for tc in calls:
                self.n_ids += 1
                tid = f"bcw{self.n_ids:05d}"
                self.id_roles[tid], self.pending[tid] = ("write_turn", "tool_results"), turn
                out.append({"id": tid, "type": "function", "function": tc["function"]})
        rec["served"] = "write_tool_calls"
        return {"role": "assistant", "content": "", "tool_calls": out}

    @staticmethod
    def _strip(up: dict) -> dict:
        return {k: v for k, v in up.items() if k not in ("body", "wire")}

    def _usage(self, body: dict, msg: dict) -> dict:
        pt = math.ceil(len(canon(body.get("messages")) + canon(body.get("tools") or [])) / self.a.chars_per_token)
        ct = math.ceil(len(canon(msg)) / self.a.chars_per_token)
        return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct, "estimated": True}

    def _resp(self, body: dict, msg: dict) -> dict:
        resp = {"id": f"bc-{time.time_ns()}", "object": "chat.completion", "created": int(time.time()),
                "model": body.get("model"), "usage": self._usage(body, msg),
                "choices": [{"index": 0, "message": msg,
                             "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}]}
        return self._stream_or_json(body, resp)

    @staticmethod
    def _stream_or_json(body: dict, resp: dict) -> dict:
        resp = dict(resp, model=body.get("model"))  # the harness sees its own alias
        return {"__sse__": sse_chunks(resp)} if body.get("stream") else resp


def sse_chunks(resp: dict) -> list[dict]:
    msg, base = resp["choices"][0]["message"], {"id": resp.get("id", "bc"), "object": "chat.completion.chunk",
                                                "created": resp.get("created", 0), "model": resp.get("model")}
    delta = {"role": "assistant"}
    if msg.get("content"):
        delta["content"] = msg["content"]
    if msg.get("reasoning_content"):
        delta["reasoning_content"] = msg["reasoning_content"]
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{"index": i, **tc} for i, tc in enumerate(msg["tool_calls"])]
    return [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": resp["choices"][0]["finish_reason"]}]},
            {**base, "choices": [], "usage": resp.get("usage")}]


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def make_handler(d: Director):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet; the ledger is the log
            pass

        def _send(self, code: int, obj):
            if isinstance(obj, dict) and "__sse__" in obj:
                data = b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in obj["__sse__"]) + b"data: [DONE]\n\n"
                ctype = "text/event-stream"
            else:
                data, ctype = json.dumps(obj).encode(), "application/json"
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return data

        def do_CONNECT(self):  # proxied egress attempts from the harness: record host:port, refuse
            d.ledger.append({"type": "egress", "run": d.a.run, "target": self.path, "t": time.time()})
            self._send(403, {"error": "egress refused by director"})

        def do_GET(self):
            if self.path.startswith("http"):
                return self.do_CONNECT()
            if self.path.startswith("/_control"):
                return self._send(200, {"inflight": d.inflight, "cursor": d.cursor, "stopped": d.stopped,
                                        "write_failures": d.write_failures, "param_rejections": d.rejections})
            ok = self.path.rstrip("/").endswith("/models")
            body = {"object": "list", "data": [{"id": m, "object": "model", "context_length": d.a.context_length}
                                               for m in d.a.aliases.split(",")]} if ok else {"error": "not found"}
            d.ledger.append({"type": "request", "run": d.a.run, "method": "GET", "path": self.path, "role": "aux",
                             "subrole": "metadata", "status": 200 if ok else 404, "t": time.time()})
            self._send(200 if ok else 404, body)

        def do_POST(self):
            if self.path.startswith("http"):
                return self.do_CONNECT()
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path.startswith("/_control"):
                cmd = json.loads(raw or b"{}")
                for k in ("write_turns", "measure_overhead"):
                    if k in cmd:
                        setattr(d, k, bool(cmd[k]))
                return self._send(200, {"ok": True, "cursor": d.cursor})
            t0, d.inflight = time.time(), d.inflight + 1
            auth = "authorization" in {k.lower() for k in self.headers.keys()}
            try:
                body = json.loads(raw)
                code, out, rec = d.handle(self.path, body)
                rec.update(req=d.ledger.blob(body), resp=d.ledger.blob(out), status=code)
            except Exception as e:
                code, out = 500, {"error": {"message": "director error"}}
                rec = {"role": "unknown", "subrole": f"director_error:{type(e).__name__}", "status": 500}
            try:  # the record is appended before any send, so a failed send can never lose it
                r, _, _ = select.select([self.connection], [], [], 0)  # a client that already hung up reads b""
                gone = bool(r) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                gone = True
            led = d.ledger.append({"type": "request", "run": d.a.run, "method": "POST", "path": self.path,
                                   "incoming_auth_dropped": auth, "t": t0, "t_ms": round((time.time() - t0) * 1000),
                                   "load": os.getloadavg(), "client_disconnected": gone, **rec})
            try:
                self._send(code, out)
            except OSError as e:  # a hang-up after the check: noted, never a second request record
                self.close_connection = True
                d.ledger.append({"type": "send_error", "run": d.a.run, "request_seq": led["seq"],
                                 "client_disconnected": True, "error": type(e).__name__, "t": time.time()})
            finally:
                d.inflight -= 1

    return H


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--life", required=True)
    p.add_argument("--ledger-dir", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--budget-cap", type=int, default=400)
    p.add_argument("--run", required=True)
    p.add_argument("--model", default="glm-5.3")
    p.add_argument("--mode", choices=["live", "stub"], default="live")
    p.add_argument("--write-turns", action="store_true")
    p.add_argument("--measure-overhead", action="store_true")
    p.add_argument("--chars-per-token", type=float, default=4.0)
    p.add_argument("--context-length", type=int, default=131072)
    p.add_argument("--aliases", default="bicentennial-main,bicentennial-summariser,bicentennial-aux")
    p.add_argument("--timeout", type=float, default=300)
    p.add_argument("--lane-rewrite", default="", help="JSON [[from, to], ...] applied to forwarded text")
    a = p.parse_args()
    if a.mode == "live" and not os.environ.get("BICENTENNIAL_UPSTREAM_KEY"):
        sys.exit("live mode needs the upstream environment (run under the helper)")
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(Director(a)))
    print(f"director ready on 127.0.0.1:{a.port} run={a.run} mode={a.mode}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
