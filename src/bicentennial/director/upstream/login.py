"""Plan login custody (C'): the director alone reads and refreshes the real login.

Harness homes contain only placeholder_auth(); request identity headers are rebuilt.
The caller supplies BICENTENNIAL_SOL_BASE_URL, BICENTENNIAL_SOL_TOKEN_URL,
BICENTENNIAL_SOL_CLIENT_ID and BICENTENNIAL_SOL_AUTH outside the repository.
Call reexec_niced BEFORE open_login: exec would drop the non-inheritable holder.
Hold one home per account for the process lifetime, before building any responder.
No credential or identity header value is logged. Callers ledger drain()/Stop.records.
"""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import http.client
import json
import os
import re
import ssl
import sys
import tempfile
import threading
import time
from compression import zstd
from pathlib import Path
from typing import NoReturn

from bicentennial.canon import canon
from bicentennial.ledger.guard import CredentialLeak
from bicentennial.runner.guard import REFUSED_EXIT

from .forward import MAX_BODY

IDENTITY = {"originator": "hermes-agent", "User-Agent": "HermesAgent/0.22.2"}
IDENTITY_NAMES = frozenset({"authorization", "chatgpt-account-id", "x-openai-internal-codex-residency"})
REFRESH_SKEW_S, READ_GRACE_S, SNAPSHOT_WAIT_S = 300, 1.0, 30.0
AUTH_CLAIM, MIN_NEEDLE = "https://api.openai.com/auth", 8
CREDENTIAL_STOPS = ("upstream_401", "upstream_403", "upstream_sse_auth")
ENV_STORE = "BICENTENNIAL_SOL_AUTH"
HOME_HOLDERS = {}


class Stop(Exception):
    """Fixed-vocabulary refusal, with safe startup rows for the caller."""
    records: tuple[dict, ...] = ()


def hold_home(store) -> int:
    fd = None
    try:
        path = Path(store).with_name("holder.lock").resolve()
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_CLOEXEC, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if fd is not None:
            os.close(fd)
        raise Stop("home_busy" if isinstance(exc, BlockingIOError) else f"home_unusable:{type(exc).__name__}") from None
    HOME_HOLDERS[path] = fd
    return fd


def full_sync(fd):
    fcntl.fcntl(fd, fcntl.F_FULLFSYNC) if hasattr(fcntl, "F_FULLFSYNC") else os.fsync(fd)


def sync_folder(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC) if hasattr(fcntl, "F_FULLFSYNC") else os.fsync(fd)
    finally:
        os.close(fd)


def durable_write(path, data: str, *, link=False, keep_on_error=False):
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.tmp", dir=path.parent)
    complete = False
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(data)
            stream.flush()
            full_sync(stream.fileno())
        (os.link if link else os.replace)(tmp, path)
        sync_folder(path.parent)
        complete = True
    finally:
        if complete or not keep_on_error:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(tmp)


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))


def lease_id(store):
    try:
        return json.loads(store.with_name("lease.json").read_text()).get("lease_id")
    except (OSError, ValueError, AttributeError):
        return None


def jwt_claims(token) -> dict:
    try:
        part = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def account_pin(token) -> str:
    claims = jwt_claims(token)
    auth = claims.get(AUTH_CLAIM)
    auth = auth if isinstance(auth, dict) else {}
    account, *users = [v if isinstance(v, str) else "" for v in (
        auth.get("chatgpt_account_id"), auth.get("chatgpt_user_id"), auth.get("user_id"), claims.get("sub"))]
    return hashlib.sha256(b"bicentennial-pin\0" + account.encode() + b"\0" + next(filter(None, users), "").encode()).hexdigest()


def account_headers(token) -> dict:
    auth, out = jwt_claims(token).get(AUTH_CLAIM), {}
    auth = auth if isinstance(auth, dict) else {}
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


def install_placeholder(hermes_home) -> Path:
    path = Path(hermes_home) / "auth.json"
    data = json.dumps(placeholder_auth(), indent=1)
    try:
        durable_write(path, data, link=True)
    except FileExistsError:
        if path.read_bytes() != data.encode():
            raise Stop("harness_home_has_auth") from None
    return path


def post_form(url, fields) -> tuple[int, dict]:
    match = re.fullmatch(r"https://([A-Za-z0-9.-]+)(?::([0-9]{1,5}))?(/[^\s#]*)?", url)
    if not match:
        raise Stop("refresh_error:scheme")
    def encode(value):
        return "".join(chr(b) if b in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~" else f"%{b:02X}" for b in value.encode())
    try:
        host, port, path = match.groups()
        conn = http.client.HTTPSConnection(host, int(port) if port else None, timeout=30, context=ssl.create_default_context())
        with contextlib.closing(conn):
            body = "&".join(encode(k) + "=" + encode(v) for k, v in fields.items())
            conn.request("POST", path or "/", body=body, headers={
                "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
            response = conn.getresponse()
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                raise Stop("refresh_error:oversize")
            return (200, json.loads(raw)) if response.status == 200 else (response.status, {})
    except Stop as exc:
        raise exc from None
    except Exception as exc:
        raise Stop(f"refresh_error:{type(exc).__name__}") from None


class Login:
    """Single-use refresh chain, serialized and durably quarantined across failures."""
    def __init__(self, store, token_url, client_id, *, post=post_form, on_refresh=None, on_unsent=None):
        self.path, self.token_url, self.client_id, self.post = Path(store), token_url, client_id, post
        self.sentinel = self.path.with_name(self.path.name + ".stopped")
        self.lock, self.log, self._needles = threading.Lock(), [], {}
        self.dead, self.posted, self.pin = "", False, None
        self.on_refresh, self.on_unsent = on_refresh, on_unsent

    def _sentinel(self, reason):
        replace = self.sentinel.exists() and json.loads(self.sentinel.read_text()).get("reason") == "refresh_in_flight"
        durable_write(self.sentinel, json.dumps({"reason": reason, "t": utc()}) + "\n", link=not replace)

    def latch(self, reason, persist=True):
        self.dead = self.dead or reason
        try:
            if persist:
                self._sentinel(self.dead)
        except FileExistsError:
            pass
        except Exception as exc:
            self.log.append({"type": "sentinel_error", "error": type(exc).__name__, "t": int(time.time() * 1000)})

    def refuse(self, reason):
        with self.lock:
            self.latch(reason)

    def _auth_lock(self):
        try:
            fd = os.open(self.path.with_name(self.path.name + ".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        except OSError as exc:
            raise Stop(f"home_unusable:{type(exc).__name__}") from None
        try:
            return os.fdopen(fd)
        except Exception:
            os.close(fd)
            raise

    def snapshot(self):
        with self._auth_lock() as stream:
            deadline = time.monotonic() + SNAPSHOT_WAIT_S
            while True:
                try:
                    fcntl.flock(stream, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise Stop("auth_lock_busy") from None
                    time.sleep(0.1)
            return json.loads(self.path.read_text()), lease_id(self.path)

    def token(self) -> str:
        with self.lock, self._auth_lock() as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            if self.dead:
                raise Stop(self.dead) from None
            try:
                self.posted = False
                if self.sentinel.exists():
                    raise Stop(f"login_latched:{json.loads(self.sentinel.read_text()).get('reason', '')}")
                raw = self.path.read_text()
                store = json.loads(raw)
                token = store["tokens"]["access_token"]
                pin = account_pin(token)
                if self.pin is not None and pin != self.pin:
                    raise Stop("account_changed")
                self.pin = pin
                self._learn(store)
                if jwt_claims(token).get("exp", 0) - time.time() > REFRESH_SKEW_S:
                    return token
                return self._refresh(raw, store)
            except Stop as exc:
                self.latch(str(exc), persist=self.posted)
                raise exc from None
            except Exception as exc:
                self.latch(f"login_error:{type(exc).__name__}", persist=self.posted)
                raise Stop(self.dead) from None

    def _refresh(self, raw, store):
        old = store["tokens"]["refresh_token"]
        if self.on_refresh and not self.on_refresh():
            raise Stop("refresh_budget")
        try:
            self._sentinel("refresh_in_flight")
        except Exception as exc:
            self.log.append({"type": "sentinel_error", "error": type(exc).__name__, "t": int(time.time() * 1000)})
            if self.on_refresh and self.on_unsent:
                self.on_unsent()
            raise Stop("refresh_sentinel_failed") from None
        self.posted = True
        try:
            status, body = self.post(self.token_url, {"grant_type": "refresh_token", "refresh_token": old, "client_id": self.client_id})
        except Exception as exc:
            self.log.append({"type": "refresh", "status": -1, "t": int(time.time() * 1000),
                             "error": str(exc) if isinstance(exc, Stop) else type(exc).__name__})
            raise exc from None
        body = body if isinstance(body, dict) else {}
        claims = jwt_claims(body.get("access_token"))
        exp, iat = claims.get("exp"), claims.get("iat")
        self.log.append({"type": "refresh", "status": status, "t": int(time.time() * 1000),
                         "lifetime_s": exp - iat if type(exp) is int and type(iat) is int else None,
                         "rotated": bool(body.get("refresh_token")) and body.get("refresh_token") != old})
        if status in (401, 403):
            raise Stop(f"token_endpoint_{status}")
        if status != 200 or not body.get("access_token"):
            raise Stop(f"refresh_failed_{status}")
        if not body.get("refresh_token") or body["refresh_token"] == old:
            raise Stop("refresh_no_new_refresh_token")
        store["tokens"].update({k: body[k] for k in ("access_token", "refresh_token", "id_token") if body.get(k)})
        if "last_refresh" in store:
            store["last_refresh"] = utc()
        self._learn(store)
        lines = raw.splitlines()
        indent = len(lines[1]) - len(lines[1].lstrip()) if len(lines) > 1 else None
        durable_write(self.path, json.dumps(store, indent=indent or None) + ("\n" if raw.endswith("\n") else ""), keep_on_error=True)
        if account_pin(store["tokens"]["access_token"]) != self.pin:
            raise Stop("account_changed")
        if json.loads(self.sentinel.read_text()).get("reason") == "refresh_in_flight":
            self.sentinel.unlink()
            sync_folder(self.path.parent)
        return store["tokens"]["access_token"]

    @staticmethod
    def _needles_of(store, base):
        needles = dict(base)
        for name, token in store["tokens"].items():
            if isinstance(token, str):
                needles[token] = f"tokens.{name}"
                for key, value in jwt_claims(token).items():
                    for k, v in (value.items() if isinstance(value, dict) else [(key, value)]):
                        if isinstance(v, str) and re.search(r"account|user|email|org|^sub$", k):
                            needles.setdefault(v, f"claim.{k}")
        return needles

    def _learn(self, store):
        self._needles = self._needles_of(store, self._needles)

    def needles(self):
        return dict(self._needles)

    def learn_only(self, store=None):
        if store is not None:
            return self._needles_of(store, {})
        self._learn(json.loads(self.path.read_text()))
        return self.needles()

    def drain(self):
        with self.lock:
            rows, self.log = self.log, []
            return rows


def _pins(path, reason):
    try:
        try:
            pins = json.loads(path.read_text())
        except FileNotFoundError:
            pins = {}
        if not isinstance(pins, dict):
            raise ValueError
        return pins
    except (OSError, ValueError):
        raise Stop(reason) from None


def open_login(store, token_url, client_id, run, *, post=post_form, on_refresh=None, on_unsent=None) -> Login:
    if not isinstance(run, str) or not run or "\n" in run:
        raise ValueError("invalid run")
    login = Login(store, token_url, client_id, post=post, on_refresh=on_refresh, on_unsent=on_unsent)
    try:
        hold_home(store)
        login.log.append({"type": "holder", "lease": login.path.with_name("lease.json").exists()})
        snapshot, lid = login.snapshot()
        login.pin = account_pin(snapshot["tokens"]["access_token"])
        path = login.path.with_name("director-pin.json")
        pins = _pins(path, "pin_file_unreadable")
        mine = {"lease_id": lid, "pin": login.pin}
        if run in pins:
            entry = pins[run]
            if not isinstance(entry, dict) or not mine.keys() <= entry.keys():
                raise Stop("pin_file_unreadable")
            if {k: entry[k] for k in mine} != mine:
                raise Stop("run_pin_conflict")
        login.token()
        if run not in pins:
            try:
                durable_write(path, json.dumps(pins | {run: mine | {"t": utc()}}) + "\n")
            except OSError as exc:
                raise Stop(f"home_unusable:{type(exc).__name__}") from None
    except Exception as exc:
        stop = exc if isinstance(exc, Stop) else Stop(f"login_error:{type(exc).__name__}")
        stop.records = tuple(login.drain())
        raise stop from None
    return login


def auth_for(login, pacer):
    """Own the post-wait readmission loop; LiveResponder must not admit it twice."""
    def auth():
        while True:
            start = pacer.clock()
            token = login.token()
            headers = {"Authorization": "Bearer " + token, **IDENTITY, **account_headers(token)}
            if pacer.clock() - start <= READ_GRACE_S or pacer.acquire() is None:
                return headers
    auth.handles_readmission = True
    return auth


class CredentialResponder:
    def __init__(self, inner, login):
        self.inner, self.login, self.lock, self.latched = inner, login, threading.Lock(), False

    def respond(self, call):
        reply = self.inner.respond(call)
        reason = self.inner.state()["stop_reason"]
        if reason not in CREDENTIAL_STOPS:
            for attempt in reply.upstream:
                if attempt.get("kind") != "try":
                    continue
                reason = {401: "upstream_401", 403: "upstream_403"}.get(attempt.get("status"),
                    "upstream_sse_auth" if attempt.get("category") == "auth_sse" else reason)
                if reason in CREDENTIAL_STOPS:
                    break
        with self.lock:
            if reason in CREDENTIAL_STOPS and not self.latched:
                self.login.refuse(reason)
                self.latched = True
        return reply

    def state(self):
        return dict(self.inner.state(), login_stop=self.login.dead or None)

    def stop(self, reason):
        return self.inner.stop(reason)

    def served_identities(self):
        return self.inner.served_identities()


class NeedleGuard:
    def __init__(self, login, base=None):
        self.login, self.base = login, base

    def check(self, data):
        if self.base is not None:
            data = self.base.check(data)
        for value, label in self.login.needles().items():
            if len(value) >= MIN_NEEDLE and any(n in data for n in (value.encode(), canon(value)[1:-1])):
                with self.login.lock:
                    self.login.log.append({"type": "guard", "label": label})
                raise CredentialLeak(f"{label} reached a ledger write")
        return data


def scan(login, paths, run=None) -> dict:
    store, lid = login.snapshot()
    if run is not None:
        pins = _pins(login.path.with_name("director-pin.json"), "pin_file_invalid")
        if run not in pins:
            raise Stop("no_run_pin")
        entry = pins[run]
        if not isinstance(entry, dict) or not {"pin", "lease_id"} <= entry.keys():
            raise Stop("pin_file_invalid")
        if entry["lease_id"] != lid:
            raise Stop("lease_changed")
        if entry["pin"] != account_pin(store["tokens"]["access_token"]):
            raise Stop("account_changed")
    paths = list(map(Path, paths))
    for path in paths:
        if not path.exists():
            raise Stop("scan_path_missing")
    needles, files, hits, unreadable = login.learn_only(store), 0, {}, 0
    def walk_error(exc):
        nonlocal unreadable
        unreadable += 1
    for path in paths:
        candidates = ([path] if path.is_file() else
                      (Path(root) / name for root, _, names in os.walk(path, onerror=walk_error) for name in names))
        for file in candidates:
            if not file.is_file():
                continue
            files += 1
            try:
                data = file.read_bytes()
                data = zstd.decompress(data) if file.suffix == ".zst" else data
            except (OSError, zstd.ZstdError):
                unreadable += 1
                continue
            labels = {label for value, label in needles.items() if len(value) >= MIN_NEEDLE
                      and any(n in data for n in (value.encode(), canon(value)[1:-1]))}
            for label in labels:
                hits[label] = hits.get(label, 0) + 1
    return {"files_scanned": files, "needles": sum(len(s) >= MIN_NEEDLE for s in needles), "hits": hits, "unreadable": unreadable}


def exit_on_refusal(stop) -> NoReturn:
    sys.stderr.write(str(stop) + "\n")
    raise SystemExit(REFUSED_EXIT)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scan plan-lane artifacts for credential needles")
    parser.add_argument("--scan", required=True, action="store_true")
    parser.add_argument("--run")
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)
    try:
        result = scan(Login(os.environ[ENV_STORE], "", ""), args.paths, args.run)
    except Exception as exc:
        stop = exc if isinstance(exc, Stop) else Stop(f"login_error:{type(exc).__name__}")
        print(canon({"refused": str(stop)}).decode())
        return REFUSED_EXIT
    print(canon(result).decode())
    return int(bool(result["hits"] or result["unreadable"]))


if __name__ == "__main__":
    raise SystemExit(main())
