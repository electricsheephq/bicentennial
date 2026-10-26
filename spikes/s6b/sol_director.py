"""Director for spike S6b: the S6a director's ledger, budget and write turns on the Codex Responses wire.

Credential model C': Hermes runs its native openai-codex provider with a placeholder token and
HERMES_CODEX_BASE_URL pointing at this director's /backend-api/codex mount. The director alone holds the
real login. It reads the bench login store in-process, refreshes it under a lock, replaces the inbound
Authorization, and rebuilds the account headers from the token's claims. No header value is ever logged.

Routes under the mount MOUNT (any other path fails closed with 404, recorded):
    POST MOUNT + "/responses"     SSE: buffered, classified and recorded before it is replayed to Hermes
    GET  MOUNT + "/models"        a pinned catalog naming the pinned model (no upstream call)
    GET  USAGE_PATH               the usage probe: a fixed neutral body (no upstream call)

Environment, from the local helper and never the repo: BICENTENNIAL_SOL_BASE_URL (upstream base;
"/responses" is appended), BICENTENNIAL_SOL_TOKEN_URL, BICENTENNIAL_SOL_CLIENT_ID and BICENTENNIAL_SOL_AUTH
(the login store). Declared adaptations: the model alias, store-and-forward SSE, typed text parts, and the
rebuilt identity headers. Every other request key (reasoning, include, store, tools...) is forwarded unchanged.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import json
import math
import os
import re
import select
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from compression import zstd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "s6a"))
from director import REVIEW_PREFIX, WRITE_SUFFIX, WRITE_TOOLS, Budget, Ledger, _text, canon, marker_state, redact

MODEL, EFFORT = "gpt-6.1-sol", "medium"  # the pin (Hermes sends agent.reasoning_effort; recorded per call)
MOUNT = "/backend-api/codex"
USAGE_PATH = "/backend-api/wham/usage"
# Hermes' local-server detection waterfall (agent/model_metadata.py): a known shape, answered 404 and recorded
LOCAL_PROBES = ("/api/v1/models", "/api/tags", "/v1/props", "/props", "/version")
TITLE_SIG = "You name chat sessions."  # Hermes title_generation instructions (shape signature)
SUMMARY_SIG = "You are a summarization agent creating a context checkpoint"  # Hermes compression prompt
SUFFIX_ITEM = {"type": "message", "role": "user", "content": [{"type": "input_text", "text": WRITE_SUFFIX}]}
PASS_HEADERS = ("session_id", "x-client-request-id")  # forwarded verbatim; everything else is rebuilt
IDENTITY = {"originator": "hermes-agent", "User-Agent": "HermesAgent/0.22.2"}  # Hermes' own at the official host
REFRESH_SKEW_S = 300
AUTH_CLAIM = "https://api.openai.com/auth"  # the JWT claim namespace (a claim name, not an endpoint)
RETRYABLE = ("rate", "overload", "concurrency", "server")
NEUTRAL_503 = {"error": {"message": "director: upstream unavailable, retry later", "type": "director_unavailable"}}
IDENTITY_NAMES = {"authorization", "chatgpt-account-id", "x-openai-internal-codex-residency"}  # not in in_headers
# underscore codes, and the pinned Hermes' spaced auth phrases (agent/error_classifier.py _AUTH_PATTERNS). This
# decides only when to stop: a failed stream is never replayed, and the failure breaker catches a false negative
SSE_AUTH = re.compile(r"invalid[ _]api[ _]key|invalid[ _]token|token[ _](expired|invalid|revoked)|unauthori[sz]ed|"
                      r"authentication|permission_denied|forbidden|account_deactivated|access[ _]denied|"
                      r"gateway_auth_failed|failed to extract accountid from token", re.IGNORECASE)
ERROR_FIELDS = ("code", "type", "status", "status_code", "message", "detail")  # provider-authored; never output
TERMINAL = ("response.completed", "response.failed", "response.incomplete", "error")


class Stop(Exception):
    """A stop condition: the director makes no further upstream or token-endpoint call."""


def jwt_claims(token) -> dict:
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def account_headers(token: str) -> dict:
    """ChatGPT-Account-ID and residency from the token's claims, as Hermes' agent/codex_headers.py does."""
    auth, out = jwt_claims(token).get(AUTH_CLAIM) or {}, {}
    if isinstance(auth.get("chatgpt_account_id"), str) and auth["chatgpt_account_id"]:
        out["ChatGPT-Account-ID"] = auth["chatgpt_account_id"]
    res = auth.get("chatgpt_data_residency") or auth.get("chatgpt_compute_residency")
    if isinstance(res, str) and res.strip():
        out["x-openai-internal-codex-residency"] = res.strip()
    return out


def placeholder_auth() -> dict:
    """A Hermes auth store holding an unsigned, obviously fake JWT: its exp is far off, so Hermes never
    refreshes it, and its account id is fake. The director replaces both on the way upstream."""
    seg = [base64.urlsafe_b64encode(json.dumps(x).encode()).rstrip(b"=").decode() for x in (
        {"alg": "none", "typ": "JWT"},
        {"exp": 4102444800, "iat": 1700000000, AUTH_CLAIM: {"chatgpt_account_id": "placeholder-account"}})]
    tokens = {"access_token": ".".join(seg) + ".placeholder-signature", "refresh_token": "placeholder-not-a-token"}
    return {"version": 1, "active_provider": "openai-codex", "providers": {"openai-codex": {
        "tokens": tokens, "last_refresh": "2026-10-26T00:00:00Z", "auth_mode": "chatgpt"}}}


def _post_form(url: str, fields: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode(), method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        e.close()
        return e.code, {}
    except Exception as e:  # the class only: messages can carry the host
        raise Stop(f"refresh_error:{type(e).__name__}") from None


class Login:
    """The bench login store. The director is its only reader and its only refresher (refresh tokens are
    single-use). Refresh runs under a process lock and a file lock; the rotated pair is written back
    atomically, in the file's own format, before the new access token is used. Any failure under the lock
    (a refused or failed refresh, a failed write-back) is latched: every later caller gets the same Stop and
    no caller reaches the token endpoint again, so a consumed refresh token is never sent twice.
    A stop after a token POST, or a refused credential, is also persisted as a sentinel beside the store (the
    reason and a UTC time, never a token), so a later process refuses too, until the owner has looked and
    removed it. The stops that write it: token_endpoint_401/403, refresh_failed_<status>,
    refresh_no_new_refresh_token, refresh_error:<class> and login_error:<class> once the POST was sent, and the
    director's upstream_401/403 and upstream_sse_auth. A stop before any POST (refresh_budget, an unreadable
    store) latches in this process only: the refresh token was never sent."""
    def __init__(self, path, token_url: str, client_id: str, post=_post_form, on_refresh=None):
        self.path, self.token_url, self.client_id, self.post = Path(path), token_url, client_id, post
        self.on_refresh, self.lock, self.secrets, self.log = on_refresh, threading.Lock(), {}, []
        self.dead, self.posted = "", False  # the latched failure; whether this refresh reached the token endpoint
        self.sentinel = self.path.with_name(self.path.name + ".stopped")

    def latch(self, reason: str, persist: bool = True):
        """Latch a login stop in this process and, if persist, on disk; the first reason is kept. The sentinel
        is written complete to a 0600 temporary file, then linked into place (atomic, and never replacing an
        earlier first stop). Never raises: if the sentinel cannot be written, the in-process latch still holds."""
        self.dead = self.dead or reason
        tmp = self.sentinel.with_name(f".{self.sentinel.name}.tmp{os.getpid()}.{threading.get_ident()}")
        try:
            if persist:
                with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                    f.write(json.dumps({"reason": reason, "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
                            + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.link(tmp, self.sentinel)
        except FileExistsError:  # already latched on disk
            pass
        except Exception as e:  # noqa: BLE001 - not writable: recorded by class; the in-process latch holds
            self.log.append({"type": "sentinel_error", "error": type(e).__name__, "t": time.time()})
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    def token(self) -> str:
        with self.lock, os.fdopen(os.open(self.path.with_name(self.path.name + ".lock"), os.O_CREAT | os.O_RDWR,
                                          0o600)) as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            if self.dead:
                raise Stop(self.dead)
            try:
                self.posted = False
                if self.sentinel.exists():  # an earlier process latched a login stop: no POST, ever
                    raise Stop(f"login_latched:{json.loads(self.sentinel.read_text()).get('reason', '')}")
                raw = self.path.read_text()
                store = json.loads(raw)
                at = store["tokens"]["access_token"]
                self._learn(store)
                if jwt_claims(at).get("exp", 0) - time.time() > REFRESH_SKEW_S:
                    return at
                return self._refresh(raw, store)  # persisted before it returns
            except Stop as e:
                self.latch(str(e), persist=self.posted)
                raise
            except Exception as e:  # noqa: BLE001 - any failure after a POST may have consumed the refresh token
                self.latch(f"login_error:{type(e).__name__}", persist=self.posted)  # the class only, never a message
                raise Stop(self.dead) from None

    def _refresh(self, raw: str, store: dict) -> str:
        old = store["tokens"]["refresh_token"]
        if self.on_refresh and not self.on_refresh():
            raise Stop("refresh_budget")
        self.posted = True
        status, body = self.post(self.token_url, {"grant_type": "refresh_token", "refresh_token": old,
                                                  "client_id": self.client_id})
        c = jwt_claims(body.get("access_token"))
        self.log.append({"type": "refresh", "status": status, "t": time.time(), "lifetime_s": c.get("exp", 0) - c.get(
            "iat", 0), "rotated": bool(body.get("refresh_token")) and body.get("refresh_token") != old})
        if status in (401, 403):
            raise Stop(f"token_endpoint_{status}")
        if status != 200 or not body.get("access_token"):
            raise Stop(f"refresh_failed_{status}")
        if not body.get("refresh_token") or body["refresh_token"] == old:
            raise Stop("refresh_no_new_refresh_token")
        store["tokens"].update({k: body[k] for k in ("access_token", "refresh_token", "id_token") if body.get(k)})
        if "last_refresh" in store:
            store["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._learn(store)
        lines = raw.splitlines()
        indent = len(lines[1]) - len(lines[1].lstrip()) if len(lines) > 1 else None
        data = json.dumps(store, indent=indent or None) + ("\n" if raw.endswith("\n") else "")
        tmp = self.path.with_name(f".{self.path.name}.tmp{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
        return store["tokens"]["access_token"]

    def _learn(self, store: dict):
        """Every token, and every account, user or email value in their claims, becomes a guard needle
        (value -> a label naming only the field)."""
        for name, tok in store["tokens"].items():
            if isinstance(tok, str):
                self.secrets[tok] = f"tokens.{name}"
                for k, v in jwt_claims(tok).items():  # top-level claims and the namespaced auth/profile claims
                    for kk, vv in (v.items() if isinstance(v, dict) else [(k, v)]):
                        if isinstance(vv, str) and re.search(r"account|user|email|org|^sub$", kk):
                            self.secrets.setdefault(vv, f"claim.{kk}")

    def learn_only(self) -> dict:
        """Read-only (no lock, no refresh): the needles, for --scan."""
        self._learn(json.loads(self.path.read_text()))
        return self.secrets


class Guard:
    """Refuses to persist anything containing a credential, account id or email (stop condition)."""
    def __init__(self, login: Login | None):
        self.login = login

    def check(self, data: bytes) -> bytes:
        for s, label in list(self.login.secrets.items() if self.login else ()):
            if len(s) >= 8 and s.encode() in data:  # name the field and its JSON path, never the value
                os.write(2, f"FATAL: {label} reached a ledger write at {_where(data, s)}; stopping\n".encode())
                os._exit(3)
        return data


def _where(data: bytes, s: str):
    """The key path to the first string holding s; an SSE text is walked event by event."""
    def walk(o, path):
        if isinstance(o, str):
            if s in o and o.startswith(("event:", "data:")):
                return next(filter(None, (walk(e, [*path, f"sse:{e.get('type')}"]) for e in parse_sse(o.encode()))), path)
            return path if s in o else None
        kids = o.items() if isinstance(o, dict) else enumerate(o) if isinstance(o, list) else ()
        return next(filter(None, (walk(v, [*path, str(k)]) for k, v in kids)), None)
    try:
        return walk(json.loads(data), [])
    except ValueError:
        return "non-json"


def scan(login: Login, paths: list[str]) -> dict:
    """Counts of credential, account and email needles in files (zstd blobs decompressed); never a value."""
    needles, files, hits = login.learn_only(), 0, {}
    for f in [q for p in map(Path, paths) for q in ([p] if p.is_file() else p.rglob("*")) if q.is_file()]:
        files += 1
        data = f.read_bytes()
        data = zstd.decompress(data) if f.suffix == ".zst" else data
        for s, label in needles.items():
            if len(s) >= 8 and s.encode() in data:
                hits[label] = hits.get(label, 0) + 1
    return {"files_scanned": files, "needles": sum(len(s) >= 8 for s in needles), "hits": hits}


def typed(items) -> list:
    """Plain-string message content becomes one typed text part; content, order and role are unchanged."""
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    return [dict(it, content=[{"type": "output_text" if it.get("role") == "assistant" else "input_text",
                               "text": it["content"]}])
            if isinstance(it, dict) and it.get("type", "message") == "message" and isinstance(it.get("content"), str)
            else it for it in items or []]


def readback(body: dict, wire: dict | None, model: str) -> bool:
    """The forwarded write turn equals the harness request plus the suffix item and the write-tool filter,
    modulo only the declared adaptations (model, stream, typed parts). Checked by inverting each adaptation,
    independently of the forwarding code."""
    if not wire or set(wire) != set(body) | {"model", "stream", "tools"}:
        return False
    if any(wire[k] != v for k, v in body.items() if k not in ("model", "stream", "input", "tools")):
        return False
    if (wire["model"], wire["stream"]) != (model, True):
        return False
    if wire["tools"] != [t for t in body.get("tools") or [] if t.get("name") in WRITE_TOOLS]:
        return False
    sent, mine = wire.get("input") or [], body.get("input") or []
    return len(sent) == len(mine) + 1 and sent[-1] == SUFFIX_ITEM and all(map(_untyped_eq, sent, mine))


def _untyped_eq(w, b) -> bool:
    if isinstance(b, dict) and isinstance(b.get("content"), str) and isinstance(w, dict):
        part = w.get("content") or [{}]
        return (len(part) == 1 and part[0].get("text") == b["content"] and part[0].get("type") in (
            "input_text", "output_text") and {**w, "content": None} == {**b, "content": None})
    return w == b


def parse_sse(raw: bytes) -> list[dict]:
    events = []  # CRLF, CR and LF line endings are all valid SSE; after normalising, only \n ends a line
    for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.split("\n") if line.startswith("data:"))
        if data and data != "[DONE]":
            try:
                ev = json.loads(data)
            except ValueError:
                ev = None
            events.append(ev if isinstance(ev, dict) else {"type": "director.unparsed"})  # a non-object too
    return events


def sse_bytes(items: list[dict], usage: dict, model: str) -> bytes:
    """A Responses SSE stream for a director-served reply: one delta per message, items, then completed."""
    rid, evs = f"resp_bc{time.time_ns()}", []
    evs.append({"type": "response.created", "response": {"id": rid, "object": "response", "status": "in_progress",
                                                         "model": model}})
    for i, it in enumerate(items):
        if it["type"] == "message":
            evs.append({"type": "response.output_text.delta", "output_index": i, "content_index": 0,
                        "delta": it["content"][0]["text"]})
        evs.append({"type": "response.output_item.done", "output_index": i, "item": it})
    evs.append({"type": "response.completed", "response": {"id": rid, "object": "response", "status": "completed",
                                                           "model": model, "output": [], "usage": usage}})
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(dict(e, sequence_number=n))}\n\n".encode()
                    for n, e in enumerate(evs))


def error_objects(e: dict) -> list[dict]:
    """The provider-authored error objects of one event: an error event itself, and the truthy error or
    response.error of any event. Never model output (output text deltas, response.output, call arguments)."""
    objs = [e] if e.get("type") == "error" else []
    resp = e.get("response") if isinstance(e.get("response"), dict) else {}
    objs += [resp.get("error"), e.get("error")]
    return [o if isinstance(o, dict) else {"message": o} for o in objs if o]


def _error_text(o: dict, etype) -> str:
    return " ".join(str(o[k]) for k in ERROR_FIELDS if o.get(k) is not None and o.get(k) != etype)


def sse_auth_error(events: list[dict]) -> bool:
    """An in-stream auth failure inside an HTTP 200: an error object (above) of any frame whose code, type,
    status, message or detail names an auth refusal. It only latches the stop; the stream is never replayed."""
    return any(SSE_AUTH.search(_error_text(o, e.get("type"))) or any(str(o.get(k)) in ("401", "403") for k in (
        "code", "status", "status_code")) for e in events for o in error_objects(e))


def sol_category(status: int, text: str) -> str:
    t = text.lower()
    if re.search(r"usage[ _]limit|quota|insufficient|exceeded your|billing", t):
        return "quota"
    if status in (401, 403):
        return f"auth_{status}"
    if re.search(r"concurren", t):
        return "concurrency"
    if status == 429 or re.search(r"rate.?limit|too many", t):
        return "rate"
    if status in (502, 503, 529) or re.search(r"overload|capacity", t):
        return "overload"
    return "server" if status >= 500 else "other"


def shape(obj, key=""):
    """The JSON structure of a refusal body: keys and value types; code/type/param strings kept, redacted."""
    if isinstance(obj, dict):
        return {k: shape(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shape(v) for v in obj[:3]]
    if isinstance(obj, str):
        return redact(obj)[:80] if key in ("code", "type", "param") else "str"
    return type(obj).__name__


class Director:
    def __init__(self, a, login: Login | None = None, urlopen=urllib.request.urlopen):
        self.a, self.urlopen = a, urlopen
        self.budget = Budget(Path(a.budget_file), a.budget_cap)
        self.login = login if login is not None or a.mode == "stub" else Login(
            os.environ["BICENTENNIAL_SOL_AUTH"], os.environ["BICENTENNIAL_SOL_TOKEN_URL"],
            os.environ["BICENTENNIAL_SOL_CLIENT_ID"], on_refresh=lambda: self.budget.take(a.run, "refresh"))
        self.failure_streak, self.stopped, self.stop_reason, self.write_failures = 0, False, "", 0
        self.streak_lock = threading.Lock()
        self.guard = Guard(self.login)
        try:  # learn the needles before any ledger write (this refreshes only if the token is expiring)
            self.login and self.login.token()
        except Stop as e:
            self.stop(str(e))
        self.ledger = Ledger(Path(a.ledger_dir), self.guard)
        life = json.loads(Path(a.life).read_text())
        self.expected = [{"kind": "replay", "session": s["index"], "turn": i, **t}
                         for s in life["sessions"] for i, t in enumerate(s["turns"], 1)]
        self.expected += [{"kind": "probe", "session": p["index"], "turn": i, **t}
                          for p in life.get("probes", []) for i, t in enumerate(p["turns"], 1)]
        self.cursor, self.current = 0, None
        self.id_roles: dict[str, tuple[str, str]] = {}  # call_id -> (role, subrole)
        self.pending: dict[str, dict] = {}  # director-issued write call_ids -> scripted turn
        self.lock, self.inflight, self.n_ids = threading.Lock(), 0, 0
        self.write_turns = a.write_turns
        self.url = os.environ.get("BICENTENNIAL_SOL_BASE_URL", "").rstrip("/") + "/responses"

    def stop(self, reason: str, login: bool = False):
        self.stopped, self.stop_reason = True, self.stop_reason or reason
        if login and self.login:  # the credential was refused: a re-login is an owner step, so no later run uses it
            self.login.latch(reason)

    # ---- upstream ------------------------------------------------------------------------------
    def upstream_retry(self, body: dict, kind: str, rec: dict, fwd: dict) -> dict:
        """Upstream 429s and overloads are absorbed here with backoff (5, 15, 45 s); each try is counted.
        Hermes never sees a 429. Three results in a row that still fail after their retries (any class) stop
        the director; a retry that recovers never counts, and a call never sent is not a result."""
        for wait in (5, 15, 45, None):
            up = self.upstream(body, kind, fwd)
            retry = not (up["forward"] or up["category"] not in RETRYABLE or wait is None)
            rec["upstream"].append({k: v for k, v in up.items() if k not in ("raw", "events", "wire")}
                                   | {"t_end": time.time(), "retry_wait_s": wait if retry else 0})
            if not retry:
                with self.streak_lock:  # concurrent upstream calls (two Hermes processes)
                    if up["forward"]:
                        self.failure_streak = 0
                    elif not (up["ok"] or up["category"] == "budget_or_stop"):  # served but unparsed: held
                        self.failure_streak += 1
                    if self.failure_streak >= 3:
                        self.stop("upstream_failures_3_in_a_row")
                return up
            time.sleep(wait)

    def upstream(self, body: dict, kind: str, fwd: dict) -> dict:
        """One counted upstream call; the whole SSE stream is buffered. Never raises; never logs a header."""
        wire = dict(body, model=self.a.model, stream=True, input=typed(body.get("input")))
        data = json.dumps(wire).encode()
        sub = {"kind": kind, "model": self.a.model, "reasoning": body.get("reasoning"), "effort_is_pin": (body.get(
            "reasoning") or {}).get("effort") == EFFORT, "marker": marker_state(),
               "load": os.getloadavg(), "typed_parts": sum(isinstance(it, dict) and isinstance(it.get("content"), str)
                                                          for it in body.get("input") or [])}
        sub["req"], sub["wire"], sub["forward"] = self.ledger.blob(json.loads(data)), json.loads(data), False
        token = ""
        try:
            token = self.login.token() if self.login and not self.stopped else ""
        except Stop as e:
            self.stop(str(e))
        while self.login and self.login.log:
            self.ledger.append({"run": self.a.run, **self.login.log.pop(0)})
        if self.stopped or not self.budget.take(self.a.run, kind):
            return {**sub, "status": 0, "category": "budget_or_stop", "ok": False, "t_ms": 0}
        t0 = time.monotonic()
        if self.a.mode == "stub":
            raw, status, hdrs = self._stub(wire, kind), 200, {}
        else:
            req = urllib.request.Request(self.url, data=data, method="POST", headers={
                "Authorization": f"Bearer {token}", "Content-Type": "application/json",
                "Accept": "text/event-stream", **IDENTITY, **account_headers(token), **fwd})
            try:
                with self.urlopen(req, timeout=self.a.timeout) as r:
                    raw, status, hdrs = r.read(), r.status, dict(r.headers)
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):  # latched before the body read, which can fail or stall
                    self.stop(f"upstream_{e.code}", login=True)
                try:
                    text, hdrs = self._scrub(e.read(), sub).decode("utf-8", "replace"), dict(e.headers or {})
                except Exception as x:  # noqa: BLE001 - a truncated or stalled body: the class only, status kept
                    return {**sub, "status": e.code, "category": sol_category(e.code, ""), "ok": False,
                            "body_read_error": type(x).__name__, "t_ms": round((time.monotonic() - t0) * 1000)}
                finally:
                    try:
                        e.close()
                    except Exception:  # noqa: BLE001, S110 - cleanup only: the record above is always returned
                        pass
                cat = sol_category(e.code, text)
                try:
                    body_shape = shape(json.loads(text))
                except ValueError:
                    body_shape = "non-json"
                return {**sub, "status": e.code, "category": cat, "ok": False, "body_redacted": redact(text),
                        "body_shape": body_shape, "limit_headers": _limit_headers(hdrs), "error_obj": _err_obj(text),
                        "t_ms": round((time.monotonic() - t0) * 1000)}
            except Exception as e:  # network errors: the class only (messages can carry the host)
                return {**sub, "status": -1, "category": f"error:{type(e).__name__}", "ok": False,
                        "t_ms": round((time.monotonic() - t0) * 1000)}
        raw = self._scrub(raw, sub)
        events = parse_sse(raw)
        types = [e.get("type") for e in events]
        errs = [o for e in events for o in error_objects(e)]
        done = next((e for e in reversed(events) if e.get("type") in TERMINAL), {})
        resp = done.get("response") if isinstance(done.get("response"), dict) else {}
        clean = status == 200 and not errs and "response.failed" not in types  # no error object or failed frame
        ok = clean and done.get("type") == "response.completed"  # served (the measurement tools count it)
        n_unparsed = types.count("director.unparsed")
        forward = (ok or clean and done.get("type") == "response.incomplete") and not n_unparsed  # max_output_tokens
        basis = [{k: o[k] for k in ERROR_FIELDS if k in o} for o in errs]  # error objects only, never model text
        cat = None if ok else sol_category(0, json.dumps(basis))  # for stats and retries, never forwarding
        if sse_auth_error(events):
            cat = "auth_sse"
            self.stop("upstream_sse_auth", login=True)
        sub.update(status=status, ok=ok, forward=forward, n_unparsed=n_unparsed, category=cat, t_ms=round((time.monotonic() - t0) * 1000),
                   frame_types=[t for i, t in enumerate(types) if not i or t != types[i - 1]],
                   resp=self.ledger.blob({"sse": raw.decode("utf-8", "replace")}), usage=resp.get("usage"),
                   served_model=resp.get("model"), n_events=len(events), limit_headers=_limit_headers(hdrs),
                   raw=raw, events=events)
        if not ok:
            sub["body_shape"] = shape(done)
        return sub

    def _scrub(self, data: bytes, sub: dict) -> bytes:
        """The upstream echoes account-identifying values (observed: response.safety_identifier carries the
        user id). Each one is replaced by a fixed placeholder before the stream is stored or replayed."""
        for s in sorted(list(self.login.secrets) if self.login else (), key=len, reverse=True):  # a refresh can add
            if len(s) >= 8 and s.encode() in data:
                sub["scrubbed"] = sub.get("scrubbed", 0) + data.count(s.encode())
                data = data.replace(s.encode(), b"redacted-by-director")
        return data

    def _stub(self, wire: dict, kind: str) -> bytes:  # development only: no network; never a measurement
        names = [t.get("name") for t in wire.get("tools") or []]
        if kind == "write_turn" and "memory" in names and len(wire["input"]) % 3 == 0:
            item = {"type": "function_call", "call_id": "call_stub", "name": "memory", "status": "completed",
                    "arguments": json.dumps({"action": "add", "target": "memory", "content": "stub note"})}
        else:
            item = {"type": "message", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": f"stub {kind}"}]}
        return sse_bytes([item], {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}, "stub")

    # ---- classification ---------------------------------------------------------------------------
    def classify(self, body: dict) -> tuple[str, str, dict | None]:
        items = typed(body.get("input"))
        last = items[-1] if items else {}
        if last.get("type") == "function_call_output":  # 1. cursor: a call_id this director issued or forwarded
            ids = []
            for it in reversed(items):
                if it.get("type") not in ("function_call_output", "function_call"):
                    break
                ids.append(it.get("call_id", ""))
            for cid in ids:
                if cid in self.id_roles:
                    return self.id_roles[cid][0], self.id_roles[cid][1], self.pending.get(cid)
        users = [it for it in items if it.get("type", "message") == "message" and it.get("role") == "user"]
        first = _text(users[0].get("content")) if users else ""
        if (body.get("instructions") or "").startswith(TITLE_SIG):  # 2. shape signatures (before the cursor:
            return "aux", "title_generation", None  # a title request carries the opening user turn)
        if first.startswith(SUMMARY_SIG) or (body.get("instructions") or "").startswith(SUMMARY_SIG):
            return "summariser", "compression", None
        text = _text(last.get("content")) if last.get("role") == "user" else ""
        if text and self.cursor < len(self.expected) and self.expected[self.cursor]["user"] in text:  # 3. cursor
            turn = self.expected[self.cursor]
            return ("replay_main" if turn["kind"] == "replay" else "probe_main"), "cursor", turn
        if text and self.current and self.current["user"] in text:  # the harness re-sent the current turn
            return ("replay_main" if self.current["kind"] == "replay" else "probe_main"), "retry", self.current
        if text.startswith(REVIEW_PREFIX):
            return "aux", "background_review", None
        return "unknown", "", None

    # ---- serving ----------------------------------------------------------------------------------
    def handle(self, body: dict, fwd: dict) -> tuple[int, bytes, dict]:
        """Returns (status, SSE or JSON bytes, record). Nothing is sent before the caller appends the record."""
        with self.lock:
            role, sub, turn = self.classify(body)
            if role in ("replay_main", "probe_main") and sub == "cursor":
                self.cursor, self.current = self.cursor + 1, turn
        rec = {"role": role, "subrole": sub, "cursor": turn and {"session": turn["session"], "turn": turn["turn"]},
               "model_in": body.get("model"), "reasoning_in": body.get("reasoning"),
               "n_items": len(body.get("input") or []), "n_tools": len(body.get("tools") or []),
               "req_chars": len(canon(body)), "upstream": []}
        if role == "unknown":
            return 400, b'{"error": {"message": "director: unclassified request refused (fail closed)"}}', rec
        if role in ("replay_main", "write_turn"):
            if role == "replay_main" and sub == "cursor" and self.write_turns:
                calls = self.write_turn(body, turn, rec, fwd)
                if calls:
                    return 200, sse_bytes(calls, self._usage(body, calls), body.get("model")), rec
            msg = {"type": "message", "role": "assistant", "status": "completed",
                   "content": [{"type": "output_text", "text": turn["assistant"]}]}
            rec["served"] = "script_retry" if sub == "retry" else "script"
            return 200, sse_bytes([msg], self._usage(body, [msg]), body.get("model")), rec
        kind = {"summariser": "summariser", "probe_main": "probe"}.get(role, "aux")  # live roles
        up = self.upstream_retry(body, kind, rec, fwd)
        if not up["forward"]:  # any failure, of any status or shape: Hermes would act on its status or text
            rec["served"] = "neutral_503"
            return 503, json.dumps(NEUTRAL_503).encode(), rec
        for e in up["events"]:
            it = e.get("item") or {}
            if e.get("type") == "response.output_item.done" and it.get("type") == "function_call":
                self.id_roles[it.get("call_id", "")] = (role, "tool_results" if sub in ("cursor", "retry") else sub)
        rec["served"] = "forward"
        return 200, up["raw"], rec

    def write_turn(self, body: dict, turn: dict, rec: dict, fwd: dict) -> list | None:
        """PREREG §10: the harness's own request plus the uniform suffix item, tools filtered to write tools."""
        tools = [t for t in body.get("tools") or [] if t.get("name") in WRITE_TOOLS]
        if not tools:
            return None
        up = self.upstream_retry(dict(body, input=list(body.get("input") or []) + [SUFFIX_ITEM], tools=tools),
                                 "write_turn", rec, fwd)
        rec["write_turn_readback"] = readback(body, up.get("wire"), self.a.model)
        if not up["ok"] or up.get("n_unparsed"):
            rec["write_turn_failed"] = up["category"]
            self.write_failures += 1  # the replay driver reads this and stops the run
            return None
        calls = [e["item"] for e in up["events"] if e.get("type") == "response.output_item.done"
                 and (e.get("item") or {}).get("type") == "function_call" and e["item"].get("name") in WRITE_TOOLS]
        rec["write_calls"] = len(calls)
        out = []
        with self.lock:
            for c in calls:
                self.n_ids += 1
                cid = f"bcw{self.n_ids:05d}"
                self.id_roles[cid], self.pending[cid] = ("write_turn", "tool_results"), turn
                out.append({"type": "function_call", "call_id": cid, "name": c["name"],
                            "arguments": c.get("arguments") or "{}", "status": "completed"})
        rec["served"] = "write_tool_calls" if out else None
        return out

    def _usage(self, body: dict, items: list) -> dict:
        it = math.ceil(len(canon(body.get("instructions") or "") + canon(body.get("input")) + canon(
            body.get("tools") or [])) / self.a.chars_per_token)
        ot = math.ceil(len(canon(items)) / self.a.chars_per_token)
        return {"input_tokens": it, "output_tokens": ot, "total_tokens": it + ot, "estimated": True}


def _limit_headers(h: dict) -> dict:
    return {k.lower(): v[:40] for k, v in (h or {}).items() if re.search(r"rate|limit|retry|reset|usage|x-codex", k.lower()) and "turn-state" not in k.lower()}


def _err_obj(text: str) -> dict:
    try:
        err = json.loads(text).get("error") or {}
    except (ValueError, AttributeError):
        err = {}
    err = err if isinstance(err, dict) else {"message": str(err)}
    return {k: redact(str(err[k])) for k in ("message", "type", "code", "param") if err.get(k) is not None}


def catalog(a) -> dict:
    return {"models": [{"slug": a.model, "display_name": a.model, "context_window": a.context_length,
                        "visibility": "list", "priority": 1, "supported_in_api": True}]}


def make_handler(d: Director):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet; the ledger is the log
            pass

        def _send(self, code: int, data: bytes, ctype: str = "application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if code == 503:
                self.send_header("Retry-After", "10")
            self.end_headers()
            self.wfile.write(data)

        def _meta(self, subrole: str, code: int, obj: dict, role: str = "metadata"):
            d.ledger.append({"type": "request", "run": d.a.run, "method": self.command, "path": self.path,
                             "role": role, "subrole": subrole, "status": code,
                             "t": time.time()})
            self._send(code, json.dumps(obj).encode())

        def do_CONNECT(self):  # proxied egress attempts from the harness: record host:port, refuse
            d.ledger.append({"type": "egress", "run": d.a.run, "target": self.path, "t": time.time()})
            self._send(403, b'{"error": "egress refused by director"}')

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path.rstrip("/")
            if self.path.startswith("http"):
                return self.do_CONNECT()
            if path == "/_control":
                return self._send(200, json.dumps({
                    "inflight": d.inflight, "cursor": d.cursor, "stopped": d.stopped, "stop_reason": d.stop_reason,
                    "write_failures": d.write_failures, "failure_streak": d.failure_streak}).encode())
            if path == MOUNT + "/models":
                return self._meta("catalog", 200, catalog(d.a))
            if path == USAGE_PATH:
                return self._meta("usage_probe", 200, {"rate_limit": None, "note": "director: fixed neutral body"})
            if path.removeprefix(MOUNT) in LOCAL_PROBES:
                return self._meta("local_server_probe", 404, {"error": {"message": "director: not a local server"}})
            self._meta("path_refused", 404, {"error": {"message": "director: unknown path (fail closed)"}}, "unknown")

        def do_POST(self):
            if self.path.startswith("http"):
                return self.do_CONNECT()
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if urllib.parse.urlparse(self.path).path.rstrip("/") != MOUNT + "/responses":
                return self._meta("path_refused", 404, {"error": {"message": "director: unknown path (fail closed)"}},
                                  "unknown")
            t0 = time.time()
            with d.lock:  # concurrent request threads
                d.inflight += 1
            names = sorted({k.lower() for k in self.headers} - IDENTITY_NAMES)  # names only; no identity header
            fwd = {k: self.headers[k] for k in PASS_HEADERS if self.headers.get(k)}
            try:
                if self.headers.get("Content-Encoding"):
                    raise ValueError("encoded request body")
                body = json.loads(raw)
                code, out, rec = d.handle(body, fwd)
                rec.update(req=d.ledger.blob(body))
            except Exception as e:
                code, out = 500, b'{"error": {"message": "director error"}}'
                rec = {"role": "unknown", "subrole": f"director_error:{type(e).__name__}"}
            sse = out[:6] in (b"event:", b"data: ")
            try:  # the record is appended before any send, so a failed send can never lose it
                r, _, _ = select.select([self.connection], [], [], 0)  # a client that already hung up reads b""
                gone = bool(r) and self.connection.recv(1, socket.MSG_PEEK) == b""
            except OSError:
                gone = True
            led = d.ledger.append({"type": "request", "run": d.a.run, "method": "POST", "path": self.path,
                                   "in_headers": names, "t": t0, "t_ms": round((time.time() - t0) * 1000),
                                   "load": os.getloadavg(), "client_disconnected": gone, "status": code,
                                   "resp": d.ledger.blob({"sse": out.decode("utf-8", "replace")}), **rec})
            try:
                self._send(code, out, "text/event-stream" if sse else "application/json")
            except OSError as e:  # a hang-up after the check: noted, never a second request record
                self.close_connection = True
                d.ledger.append({"type": "send_error", "run": d.a.run, "request_seq": led["seq"],
                                 "client_disconnected": True, "error": type(e).__name__, "t": time.time()})
            finally:
                with d.lock:
                    d.inflight -= 1

    return H


def main():
    p = argparse.ArgumentParser()
    if sys.argv[1:2] == ["--scan"]:  # under the local helper: python3.14 sol_director.py --scan <dir-or-file>...
        login = Login(os.environ["BICENTENNIAL_SOL_AUTH"], "", "")
        return print(json.dumps(scan(login, sys.argv[2:])))
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--life", required=True)
    p.add_argument("--ledger-dir", required=True)
    p.add_argument("--budget-file", required=True)
    p.add_argument("--budget-cap", type=int, default=400)
    p.add_argument("--run", required=True)
    p.add_argument("--model", default=MODEL)
    p.add_argument("--mode", choices=["live", "stub"], default="live")
    p.add_argument("--write-turns", action="store_true")
    p.add_argument("--chars-per-token", type=float, default=4.0)
    p.add_argument("--context-length", type=int, default=272000)
    p.add_argument("--timeout", type=float, default=900)
    a = p.parse_args()
    if a.mode == "live" and not os.environ.get("BICENTENNIAL_SOL_AUTH"):
        sys.exit("live mode needs the Sol environment (run under the local helper)")
    d = Director(a)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(d))
    print(f"director ready on 127.0.0.1:{a.port} run={a.run} mode={a.mode} model={a.model}", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
