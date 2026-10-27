"""R17b: synthetic tmp_path logins, in-memory token POSTs and loopback upstreams only."""

import ast
import base64
import contextlib
import hashlib
import json
import os
import runpy
import stat
import subprocess
import sys
import textwrap
import threading
from compression import zstd
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from bicentennial.canon import canon
from bicentennial.director.upstream import login as sd
from bicentennial.ledger import CredentialLeak, Guard, Ledger

ROOT = Path(__file__).resolve().parents[2]
UP = runpy.run_path(str(ROOT / "tests/director/test_upstream.py"))
CORE, Clock, completed, frames, call = (UP[k] for k in ("CORE", "Clock", "completed", "frames", "call"))
upstream_setup, no_egress, offline_and_canonical = (UP[k] for k in ("setup", "no_egress", "offline_and_canonical"))
NOW = 1800000000
ACCT, EMAIL, RES, USER = "acct-FAKE-1234-sol", "fake-user@example.invalid", "fake-residency", "user-FAKE-sol-1234"
RUN, URL, CLIENT = "fake-run", "https://fake.invalid/token", "fake-client"


@pytest.fixture
def setup(upstream_setup):
    def make(*args, **kwargs):
        kwargs.setdefault("account", "fake-account")
        return upstream_setup(*args, **kwargs)
    return make


def same(actual, expected):
    # A failed assertion must never render credentials, paths, headers or token stores.
    if actual != expected:
        pytest.fail("synthetic value comparison failed", pytrace=False)


def encoded(claims):
    part = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"e30.{part}.fake-signature"


def jwt(exp_in=3600, n=0, **auth):
    return encoded({"exp": NOW + exp_in, "iat": NOW - 60, "email": EMAIL, "sub": USER,
                    sd.AUTH_CLAIM: {"chatgpt_account_id": ACCT, "chatgpt_user_id": USER,
                                    "chatgpt_data_residency": RES, **auth}, "fake_serial": n})


def store(tmp, exp_in=3600):
    path = tmp / "auth.json"
    path.write_text(json.dumps({"OPENAI_API_KEY": None, "tokens": {"id_token": jwt(exp_in, 99),
                    "access_token": jwt(exp_in), "refresh_token": "rt-fake-0", "account_id": ACCT},
                    "last_refresh": "fake-before"}, indent=2) + "\n")
    return path


def close_holders(tmp):
    for path in list(sd.HOME_HOLDERS):
        if path.is_relative_to(tmp):
            os.close(sd.HOME_HOLDERS.pop(path))


@pytest.fixture(autouse=True)
def custody(tmp_path, monkeypatch):
    monkeypatch.setattr(sd.time, "time", lambda: NOW)
    yield
    close_holders(tmp_path)


@pytest.fixture
def home(tmp_path):
    return store(tmp_path)


def login(home, **kw):
    return sd.Login(home, URL, CLIENT, **kw)


def open_login(home, **kw):
    return sd.open_login(home, URL, CLIENT, RUN, **kw)


def rotated(*args):
    return 200, {"access_token": jwt(3600, 1), "refresh_token": "rt-fake-rotated", "id_token": jwt(3600, 2)}


def attach(responder, auth):
    responder.auth = sd.auth_for(auth, responder.pacer)
    return sd.CredentialResponder(responder, auth)


def threads(function, n):
    errors, results = [], []
    def run():
        try:
            results.append(function())
        except Exception as exc:
            errors.append(type(exc).__name__)
    workers = [threading.Thread(target=run) for _ in range(n)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(5)
    assert not any(worker.is_alive() for worker in workers)
    same(errors, [])
    return results


def pin_entry(home, **entry):
    path = home.with_name("director-pin.json")
    path.write_text(json.dumps({RUN: {"pin": sd.account_pin(json.loads(home.read_text())["tokens"]["access_token"]),
                                    "lease_id": None, **entry}}))
    return path


def test_refresh_rotation_lock_atomic_write(tmp_path):
    path, calls, entered, release = store(tmp_path, 120), [], threading.Event(), threading.Event()
    def post(url, fields):
        calls.append(fields["refresh_token"])
        entered.set()
        assert release.wait(3)
        return rotated()
    auth, out = login(path, post=post), []
    workers = [threading.Thread(target=lambda: out.append(auth.token())) for _ in range(4)]
    for worker in workers:
        worker.start()
    assert entered.wait(3)
    release.set()
    for worker in workers:
        worker.join(3)
    assert not any(worker.is_alive() for worker in workers)
    saved = json.loads(path.read_text())
    same((calls, len(set(out)), len(out), saved["tokens"]["refresh_token"]), (["rt-fake-0"], 1, 4, "rt-fake-rotated"))
    same(out[0], saved["tokens"]["access_token"])
    assert path.read_text().startswith('{\n  "OPENAI_API_KEY": null') and path.read_text().endswith("}\n")
    same(saved["tokens"]["account_id"], ACCT)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert sorted(x.name for x in tmp_path.iterdir()) == ["auth.json", "auth.json.lock"]
    same(auth.token(), out[0])
    assert auth.log[0]["rotated"] is True


@pytest.mark.parametrize("response,reason", [
    ((401, {}), "token_endpoint_401"), ((403, {}), "token_endpoint_403"), ((500, {}), "refresh_failed_500"),
    ((200, {"access_token": "fake-access", "refresh_token": "rt-fake-0"}), "refresh_no_new_refresh_token"),
    ((200, {"access_token": "fake-access"}), "refresh_no_new_refresh_token"),
])
def test_refresh_failure_stops_without_retry(tmp_path, setup, response, reason):
    path, calls = store(tmp_path, 60), []
    before = path.read_bytes()
    auth = login(path, post=lambda *a: (calls.append(1), response)[1])
    for _ in range(2):
        with pytest.raises(sd.Stop, match=f"^{reason}$"):
            auth.token()
    same(path.read_bytes(), before)
    r, server, _, _ = setup()
    wrapped = attach(r, auth)
    assert wrapped.respond(call()).status == 503
    assert len(calls) == 1 and not server.seen
    assert wrapped.state()["login_stop"] == reason


def test_refresh_failure_is_latched_for_queued_callers(tmp_path, setup):
    path, calls = store(tmp_path, 60), []
    auth = login(path, post=lambda *a: (calls.append(1), (401, {}))[1])
    r, server, _, _ = setup()
    wrapped = attach(r, auth)
    assert threads(lambda: wrapped.respond(call()).status, 2) == [503, 503]
    assert calls == [1] and server.seen == []
    assert auth.dead == "token_endpoint_401"


@pytest.mark.parametrize("operation", ["replace", "full_sync"])
def test_c3_store_write_failure_preserves_successor(tmp_path, monkeypatch, operation):
    path, calls = store(tmp_path, 60), []
    before, replace, full = path.read_bytes(), sd.os.replace, sd.full_sync
    count = []
    def fail_replace(src, dst):
        if Path(dst) == path:
            raise OSError("fake failure")
        return replace(src, dst)
    def fail_sync(fd):
        count.append(1)
        if len(count) == 2:
            raise OSError("fake sync failure")
        return full(fd)
    auth = login(path, post=lambda *a: (calls.append(1), rotated())[1])
    monkeypatch.setattr(sd.os if operation == "replace" else sd, operation, fail_replace if operation == "replace" else fail_sync)
    failures = []
    for _ in range(2):
        with pytest.raises(sd.Stop, match="^login_error:OSError$") as caught:
            auth.token()
        failures.append(caught.value)
    assert failures[0].__suppress_context__
    same(path.read_bytes(), before)
    temps = list(tmp_path.glob(".auth.json.tmp*"))
    assert len(temps) == 1 and stat.S_IMODE(temps[0].stat().st_mode) == 0o600
    same(json.loads(temps[0].read_text())["tokens"]["refresh_token"], "rt-fake-rotated")
    same(json.loads(temps[0].read_text())["tokens"]["access_token"], jwt(3600, 1))
    assert calls == [1]
    assert json.loads(auth.sentinel.read_text())["reason"] == "login_error:OSError"
    with pytest.raises(sd.Stop, match="^login_latched:login_error:OSError$"):
        login(path).token()


def test_any_exception_after_rotation_is_latched_by_class_only(tmp_path, monkeypatch):
    path, calls, dumps = store(tmp_path, 60), [], sd.json.dumps
    auth = login(path, post=lambda *a: (calls.append(1), rotated())[1])
    def fail(obj, *a, **kw):
        if isinstance(obj, dict) and "tokens" in obj:
            raise MemoryError("fake successor would be in message")
        return dumps(obj, *a, **kw)
    monkeypatch.setattr(sd.json, "dumps", fail)
    for _ in range(2):
        with pytest.raises(sd.Stop, match="^login_error:MemoryError$"):
            auth.token()
    assert calls == [1] and json.loads(auth.sentinel.read_text())["reason"] == "login_error:MemoryError"


def test_a_login_stop_is_persisted_for_the_next_process(tmp_path):
    path, calls = store(tmp_path, 60), []
    auth = login(path, post=lambda *a: (calls.append(1), (401, {}))[1])
    with pytest.raises(sd.Stop, match="^token_endpoint_401$"):
        auth.token()
    saved = json.loads(auth.sentinel.read_text())
    assert sorted(saved) == ["reason", "t"] and saved["reason"] == "token_endpoint_401"
    assert saved["t"].endswith("Z") and stat.S_IMODE(auth.sentinel.stat().st_mode) == 0o600
    assert b"rt-fake" not in auth.sentinel.read_bytes()
    store(tmp_path)
    for _ in range(2):
        with pytest.raises(sd.Stop, match="^login_latched:token_endpoint_401$"):
            login(path).token()
    assert calls == [1]


def test_sentinel_is_published_atomically(tmp_path, monkeypatch):
    path, dumps, seen = store(tmp_path, 60), json.dumps, []
    auth = login(path, post=lambda *a: (401, {}))
    def record(obj, *a, **kw):
        if isinstance(obj, dict) and "reason" in obj:
            seen.append(auth.sentinel.exists())
            if auth.sentinel.exists():
                assert isinstance(json.loads(auth.sentinel.read_text()), dict)
        return dumps(obj, *a, **kw)
    monkeypatch.setattr(sd.json, "dumps", record)
    with pytest.raises(sd.Stop):
        auth.token()
    assert seen == [False, True]
    assert stat.S_IMODE(auth.sentinel.stat().st_mode) == 0o600
    assert sorted(x.name for x in tmp_path.iterdir()) == ["auth.json", "auth.json.lock", "auth.json.stopped"]


def test_failed_sentinel_write_still_stops_and_releases_budget(tmp_path, setup, monkeypatch):
    path, calls, budget, unsent = store(tmp_path, 60), [], [], []
    auth = login(path, post=lambda *a: calls.append(1), on_refresh=lambda: (budget.append(1), True)[1],
                 on_unsent=lambda: unsent.append(1))
    dumps = sd.json.dumps
    def fail(obj, *a, **kw):
        if isinstance(obj, dict) and "reason" in obj:
            raise OSError("fake no space")
        return dumps(obj, *a, **kw)
    r, server, _, _ = setup([(401, {}, b"{}")])
    other = tmp_path / "fake-other-home"
    other.mkdir()
    fresh = login(store(other))
    wrapped = attach(r, fresh)
    monkeypatch.setattr(sd.json, "dumps", fail)
    for _ in range(2):
        with pytest.raises(sd.Stop, match="^refresh_sentinel_failed$") as caught:
            auth.token()
    assert caught.value.__suppress_context__
    assert wrapped.respond(call()).status == 503 and len(server.seen) == 1
    assert fresh.dead == "upstream_401" and calls == [] and budget == unsent == [1]
    assert not auth.sentinel.exists() and not fresh.sentinel.exists()
    assert [row["error"] for row in auth.log + fresh.log] == ["OSError", "OSError"]
    with pytest.raises(sd.Stop, match="^upstream_401$"):
        fresh.token()


def test_refresh_budget_latches_in_process_only(tmp_path):
    calls = []
    auth = login(store(tmp_path, 60), post=lambda *a: calls.append(1), on_refresh=lambda: False)
    with mock.patch.object(sd, "durable_write", wraps=sd.durable_write) as write:
        for _ in range(2):
            with pytest.raises(sd.Stop, match="^refresh_budget$"):
                auth.token()
        write.assert_not_called()
    assert not auth.sentinel.exists() and not calls


def test_successful_refresh_syncs_rotated_store_and_unlinks(tmp_path):
    auth, order = login(store(tmp_path, 60), post=rotated), []
    full, folder = sd.full_sync, sd.sync_folder
    def sync(fd):
        order.append("file")
        return full(fd)
    def sync_dir(path):
        order.append("folder")
        return folder(path)
    with mock.patch.object(sd, "full_sync", sync), mock.patch.object(sd, "sync_folder", sync_dir):
        token = auth.token()
    assert order == ["file", "folder", "file", "folder", "folder"]
    assert not auth.sentinel.exists()
    same(json.loads(auth.path.read_text())["tokens"]["access_token"], token)
    with mock.patch.object(sd.fcntl, "F_FULLFSYNC", 999, create=True), mock.patch.object(sd.fcntl, "fcntl") as fs:
        sd.full_sync(123)
        fs.assert_called_once_with(123, 999)
    with mock.patch.object(sd, "fcntl", SimpleNamespace()), mock.patch.object(sd.os, "fsync") as fs:
        sd.full_sync(123)
        fs.assert_called_once_with(123)


def test_cx6_folder_sync_flushes_drive_cache(tmp_path):
    if not hasattr(sd.fcntl, "F_FULLFSYNC"):
        pytest.skip("F_FULLFSYNC is macOS only")
    calls, real = [], sd.fcntl.fcntl
    def record(fd, op, *a):
        calls.append((stat.S_ISDIR(os.fstat(fd).st_mode), op))
        return real(fd, op, *a)
    with mock.patch.object(sd.fcntl, "fcntl", record):
        sd.durable_write(tmp_path / "fake.json", "{}\n")
    assert (True, sd.fcntl.F_FULLFSYNC) in calls


def test_refused_post_keeps_first_stop(tmp_path):
    observed = []
    def refuse(*a):
        observed.append(json.loads(auth.sentinel.read_text())["reason"])
        return 401, {}
    auth = login(store(tmp_path, 60), post=refuse)
    with pytest.raises(sd.Stop, match="^token_endpoint_401$"):
        auth.token()
    auth.latch("upstream_403")
    assert observed == ["refresh_in_flight"]
    assert json.loads(auth.sentinel.read_text())["reason"] == auth.dead == "token_endpoint_401"


@pytest.mark.parametrize("field", ["chatgpt_account_id", "chatgpt_user_id"])
def test_changed_identity_before_refresh_makes_no_post(home, field):
    calls, auth = [], login(home)
    auth.token()
    data = json.loads(home.read_text())
    data["tokens"]["access_token"] = jwt(60, **{field: "different-fake-seat"})
    home.write_text(json.dumps(data))
    auth.post = lambda *a: calls.append(1)
    for _ in range(2):
        with pytest.raises(sd.Stop, match="^account_changed$"):
            auth.token()
    assert not calls and not auth.sentinel.exists()


def test_changed_account_after_refresh_is_durable_stop(tmp_path):
    path = store(tmp_path, 60)
    changed = jwt(3600, chatgpt_account_id="different-fake-account")
    auth = login(path, post=lambda *a: (200, {"access_token": changed, "refresh_token": "rt-fake-next"}))
    with pytest.raises(sd.Stop, match="^account_changed$"):
        auth.token()
    assert auth.posted and json.loads(auth.sentinel.read_text())["reason"] == "account_changed"
    same(json.loads(path.read_text())["tokens"]["access_token"], changed)
    with pytest.raises(sd.Stop, match="^login_latched:account_changed$"):
        login(path).token()


def test_pin_hash_and_user_fallbacks():
    expected = hashlib.sha256(b"bicentennial-pin\0fake-account\0fake-user").hexdigest()
    for auth, top in (({"chatgpt_user_id": "fake-user", "user_id": "fake-ignored"}, {"sub": "fake-ignored"}),
                      ({"user_id": "fake-user"}, {"sub": "fake-ignored"}), ({}, {"sub": "fake-user"})):
        same(sd.account_pin(encoded({sd.AUTH_CLAIM: {"chatgpt_account_id": "fake-account", **auth}, **top})), expected)
    same(sd.account_pin(encoded({})), hashlib.sha256(b"bicentennial-pin\0\0").hexdigest())


@pytest.mark.parametrize("claims", [[], None, "fake-payload", {sd.AUTH_CLAIM: "fake-auth"},
    {sd.AUTH_CLAIM: {"chatgpt_account_id": None}}, {"sub": 123}, {sd.AUTH_CLAIM: {"chatgpt_user_id": 123}}])
def test_d2_pin_handles_malformed_claims(claims):
    same(sd.account_pin(encoded(claims)), sd.account_pin(encoded({})))


@pytest.mark.parametrize("auth,top", [({"chatgpt_account_id": None}, {}), ({}, {"sub": 123}), ("fake-auth", {})])
def test_d2_login_accepts_malformed_identity_without_post(home, auth, top):
    data = json.loads(home.read_text())
    token = encoded({"exp": NOW + 3600, sd.AUTH_CLAIM: auth, **top})
    data["tokens"]["access_token"] = token
    home.write_text(json.dumps(data))
    auth = login(home, post=lambda *a: pytest.fail("unexpected POST"))
    same(auth.token(), token)
    assert not auth.sentinel.exists()


def test_stop_waits_for_refresh_before_latching(tmp_path, setup):
    auth, entered, release, waiting = login(store(tmp_path, 60)), threading.Event(), threading.Event(), threading.Event()
    original = auth.lock
    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "stopper":
                waiting.set()
            original.acquire()
        def __exit__(self, *a):
            original.release()
    auth.lock = ObservedLock()
    def post(*a):
        entered.set()
        assert release.wait(3)
        return rotated()
    auth.post = post
    errors = []
    def refresh():
        try:
            auth.token()
        except Exception as exc:
            errors.append(type(exc).__name__)
    r, server, _, _ = setup([(401, {}, b"{}")])
    # The upstream stop is independent of a refresh on another request.
    wrapper = sd.CredentialResponder(r, auth)
    worker = threading.Thread(target=refresh)
    stopper = threading.Thread(target=lambda: wrapper.respond(call()), name="stopper")
    worker.start()
    try:
        assert entered.wait(3)
        assert json.loads(auth.sentinel.read_text())["reason"] == "refresh_in_flight"
        stopper.start()
        assert waiting.wait(3) and stopper.is_alive()
    finally:
        release.set()
        worker.join(3)
        if stopper.ident:
            stopper.join(3)
    assert not worker.is_alive() and not stopper.is_alive() and not errors
    assert len(server.seen) == 1 and json.loads(auth.sentinel.read_text())["reason"] == "upstream_401"


def child(tmp, script):
    return subprocess.Popen([sys.executable, "-B", "-c", textwrap.dedent(script), str(tmp), str(NOW)],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def finish(proc):
    if proc.poll() is None:
        proc.terminate()
    return proc.communicate(timeout=5)


def test_second_director_exits_busy_without_writing(home, tmp_path):
    owner = child(tmp_path, '''
        import sys
        from pathlib import Path
        from bicentennial.director.upstream import login as sd
        sd.time.time = lambda: int(sys.argv[2])
        sd.open_login(Path(sys.argv[1]) / "auth.json", "", "fake-client", "fake-run")
        print("held", flush=True)
        sys.stdin.read(1)
    ''')
    try:
        same(owner.stdout.readline(), "held\n")
        def snapshot():
            return [(p.name, p.stat().st_size, stat.S_IMODE(p.stat().st_mode), p.stat().st_mtime_ns)
                    for p in sorted(tmp_path.iterdir())]
        before = snapshot()
        proc = child(tmp_path, '''
            import sys
            from pathlib import Path
            from bicentennial.director.upstream import login as sd
            try:
                sd.open_login(Path(sys.argv[1]) / "auth.json", "", "fake-client", "fake-run")
            except sd.Stop as stop:
                assert not stop.records
                sd.exit_on_refusal(stop)
        ''')
        out, err = proc.communicate(timeout=5)
        same((proc.returncode, out, err), (3, "", "home_busy\n"))
        same(snapshot(), before)
        with pytest.raises(sd.Stop, match="^home_busy$"):
            open_login(home)
    finally:
        _, err = finish(owner)
        same(err, "")


def test_holder_exclusive_and_not_inheritable(home):
    fd = sd.hold_home(home)
    assert not os.get_inheritable(fd)
    assert stat.S_IMODE(home.with_name("holder.lock").stat().st_mode) == 0o600
    with pytest.raises(sd.Stop, match="^home_busy$"):
        sd.hold_home(home)
    assert sd.HOME_HOLDERS[home.with_name("holder.lock").resolve()] == fd


def test_kill_after_post_before_replace_quarantines(tmp_path):
    path, before = store(tmp_path, 60), None
    before = path.read_bytes()
    proc = child(tmp_path, '''
        import os, sys
        from pathlib import Path
        from bicentennial.director.upstream import login as sd
        sd.time.time = lambda: int(sys.argv[2])
        path, real = Path(sys.argv[1]) / "auth.json", sd.os.replace
        def die(src, dst):
            if Path(dst) == path:
                os._exit(137)
            return real(src, dst)
        sd.os.replace = die
        sd.Login(path, "", "fake-client", post=lambda *a: (
            200, {"access_token": "fake-access-next", "refresh_token": "rt-fake-next"})).token()
    ''')
    out, err = proc.communicate(timeout=5)
    same((proc.returncode, out, err), (137, "", ""))
    same(path.read_bytes(), before)
    auth = login(path, post=lambda *a: pytest.fail("quarantined POST"))
    assert json.loads(auth.sentinel.read_text())["reason"] == "refresh_in_flight"
    with pytest.raises(sd.Stop, match="^login_latched:refresh_in_flight$"):
        auth.token()


def test_a5_open_error_class_only_and_nothing_written(tmp_path, capsys):
    with pytest.raises(sd.Stop, match="^home_unusable:FileNotFoundError$") as caught:
        open_login(tmp_path / "fake-missing" / "auth.json")
    assert caught.value.__suppress_context__ and caught.value.records == ()
    with pytest.raises(SystemExit) as exited:
        sd.exit_on_refusal(caught.value)
    assert exited.value.code == 3
    same(capsys.readouterr(), ("", "home_unusable:FileNotFoundError\n"))
    assert list(tmp_path.iterdir()) == []


def test_a5_flock_error_closes_descriptor(home, monkeypatch):
    opened, real = [], sd.os.open
    def record(*a, **kw):
        fd = real(*a, **kw)
        opened.append(fd)
        return fd
    monkeypatch.setattr(sd.os, "open", record)
    monkeypatch.setattr(sd.fcntl, "flock", mock.Mock(side_effect=PermissionError("fake denial")))
    with pytest.raises(sd.Stop, match="^home_unusable:PermissionError$") as caught:
        sd.hold_home(home)
    assert caught.value.__suppress_context__ and len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    assert not sd.HOME_HOLDERS


@pytest.mark.parametrize("entrypoint", ["token", "snapshot", "open"])
def test_a5_auth_lock_error_is_class_only(home, monkeypatch, entrypoint):
    real, calls = sd.os.open, []
    def deny(path, *a, **kw):
        if Path(path).name == "auth.json.lock":
            raise PermissionError("fake denial")
        return real(path, *a, **kw)
    monkeypatch.setattr(sd.os, "open", deny)
    auth = login(home, post=lambda *a: calls.append(1))
    with pytest.raises(sd.Stop, match="^home_unusable:PermissionError$") as caught:
        open_login(home) if entrypoint == "open" else getattr(auth, entrypoint)()
    assert caught.value.__suppress_context__
    assert not calls and not auth.dead and not auth.sentinel.exists()


@pytest.mark.parametrize("method", ["snapshot", "token"])
def test_a5_auth_lock_fdopen_error_is_unchanged(home, monkeypatch, method):
    error = OSError("fake fdopen failure")
    monkeypatch.setattr(sd.os, "fdopen", mock.Mock(side_effect=error))
    with pytest.raises(OSError) as caught:
        getattr(login(home), method)()
    assert caught.value is error and not isinstance(caught.value, sd.Stop)


def test_startup_holder_row_pin_entries_and_hidden_identity(home, tmp_path):
    path = home.with_name("director-pin.json")
    path.write_text(json.dumps({"fake-earlier": {"lease_id": None, "pin": "fake-earlier-pin", "t": "fake-earlier"}}))
    home.with_name("lease.json").write_text(json.dumps({"lease_id": "fake-lease", "consumer": "fake-consumer"}))
    auth = open_login(home)
    rows = auth.drain()
    assert rows == [{"type": "holder", "lease": True}]
    pins = json.loads(path.read_text())
    assert pins["fake-earlier"]["t"] == "fake-earlier"
    same((pins[RUN]["lease_id"], pins[RUN]["t"]), ("fake-lease", "2027-01-15T08:00:00Z"))
    same(pins[RUN]["pin"], sd.account_pin(jwt()))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    for value in (pins[RUN]["pin"], "fake-lease", ACCT, USER, str(home)):
        same(value.encode() in canon(rows), False)


def test_cx1_restart_keeps_binding_and_refuses_rebind(home, tmp_path):
    open_login(home)
    close_holders(tmp_path)
    path = home.with_name("director-pin.json")
    before = path.read_bytes()
    open_login(home)
    close_holders(tmp_path)
    same(path.read_bytes(), before)
    home.with_name("lease.json").write_text(json.dumps({"lease_id": "fake-lease-changed"}))
    with pytest.raises(sd.Stop, match="^run_pin_conflict$"):
        open_login(home)
    close_holders(tmp_path)
    same(path.read_bytes(), before)
    sd.open_login(home, URL, CLIENT, "fake-run-2")
    pins = json.loads(path.read_text())
    same(pins[RUN], json.loads(before)[RUN])
    same(pins["fake-run-2"]["lease_id"], "fake-lease-changed")


def test_cx1_restart_on_other_account_refuses_run(home, tmp_path):
    open_login(home)
    close_holders(tmp_path)
    path = pin_entry(home, pin="fake-other-account-pin")
    before = path.read_bytes()
    with pytest.raises(sd.Stop, match="^run_pin_conflict$"):
        open_login(home)
    same(path.read_bytes(), before)


@pytest.mark.parametrize("contents", ["{broken-json", "[]", '{"fake-run":null}', '{"fake-run":{}}'])
def test_e4_and_cx1_invalid_pin_refuses_without_overwrite(tmp_path, contents):
    path, calls, refreshes = store(tmp_path, 60), [], []
    pins = path.with_name("director-pin.json")
    pins.write_text(contents)
    with pytest.raises(sd.Stop, match="^pin_file_unreadable$") as caught:
        open_login(path, post=lambda *a: calls.append(1), on_refresh=lambda: refreshes.append(1))
    assert caught.value.records == ({"type": "holder", "lease": False},)
    same(pins.read_text(), contents)
    assert calls == refreshes == [] and not path.with_name("auth.json.stopped").exists()


def test_cx9_conflict_before_refresh_never_charges(tmp_path):
    path, calls = store(tmp_path, 60), []
    pins = pin_entry(path, pin="fake-other-account-pin")
    before = pins.read_bytes()
    with pytest.raises(sd.Stop, match="^run_pin_conflict$"):
        open_login(path, post=lambda *a: calls.append(1), on_refresh=lambda: calls.append(2))
    assert not calls
    same(pins.read_bytes(), before)


@pytest.mark.parametrize("expiring", [False, True])
def test_cx2_cx10_pin_write_failure_class_only_with_refresh_records(tmp_path, monkeypatch, expiring):
    path, posts, refreshes = store(tmp_path, 60 if expiring else 3600), [], []
    real = sd.tempfile.mkstemp
    def deny(*a, **kw):
        if kw.get("prefix", "").startswith(".director-pin"):
            raise PermissionError("fake pin denial")
        return real(*a, **kw)
    monkeypatch.setattr(sd.tempfile, "mkstemp", deny)
    with pytest.raises(sd.Stop, match="^home_unusable:PermissionError$") as caught:
        open_login(path, post=lambda *a: (posts.append(1), rotated())[1],
                   on_refresh=lambda: (refreshes.append(1), True)[1])
    assert caught.value.__suppress_context__
    rows = caught.value.records
    assert rows[0] == {"type": "holder", "lease": False}
    assert len(posts) == len(refreshes) == sum(row["type"] == "refresh" for row in rows) == int(expiring)
    assert not path.with_name("director-pin.json").exists()
    # Every failed start retains custody, including a failure after a charged POST.
    with pytest.raises(sd.Stop, match="^home_busy$") as busy:
        open_login(path)
    assert busy.value.records == ()


@pytest.mark.parametrize("run", [None, "", "fake\nrun", 1])
def test_invalid_run_is_value_error_and_precedes_holder(home, run):
    with pytest.raises(ValueError, match="^invalid run$"):
        sd.open_login(home, URL, CLIENT, run)
    assert not home.with_name("holder.lock").exists()


def test_startup_snapshot_failure_has_safe_records(home):
    home.write_text("fake-bad-json")
    with pytest.raises(sd.Stop, match="^login_error:JSONDecodeError$") as caught:
        open_login(home)
    assert caught.value.__suppress_context__
    assert caught.value.records == ({"type": "holder", "lease": False},)


def test_drain_once_by_two_threads(home):
    auth = login(home)
    row = {"type": "refresh", "status": 200, "t": NOW * 1000, "lifetime_s": 3600, "rotated": True}
    auth.log.append(row)
    barrier = threading.Barrier(2)
    def drain():
        barrier.wait(3)
        return auth.drain()
    batches = threads(drain, 2)
    assert sorted(map(len, batches)) == [0, 1]
    assert [r for batch in batches for r in batch] == [row] and auth.drain() == []


@pytest.mark.parametrize("shape,reason", [("network", "refresh_error:OSError"),
                                         ("non-json", "refresh_error:JSONDecodeError"), ("list", "refresh_failed_200")])
def test_refresh_row_shapes(tmp_path, monkeypatch, shape, reason):
    path = store(tmp_path, 60)
    fake_connection(monkeypatch, body={"network": b"{}", "non-json": b"<html>", "list": b"[]"}[shape],
                    error=OSError("fake private host") if shape == "network" else None)
    with pytest.raises(sd.Stop, match=f"^{reason}$") as caught:
        open_login(path)
    rows = [row for row in caught.value.records if row["type"] == "refresh"]
    assert len(rows) == 1
    row = rows[0]
    assert row["t"] == NOW * 1000 and row["status"] == (200 if shape == "list" else -1)
    if shape == "list":
        assert row["lifetime_s"] is None and row["rotated"] is False
    else:
        assert row["error"] == reason
    assert b"private host" not in canon(rows)


def fake_connection(monkeypatch, *, status=200, body=b'{"fake":true}', error=None):
    seen = []
    class Connection:
        def __init__(self, host, port, **kw):
            seen.append({"host": host, "port": port, **kw})
            if error:
                raise error
        def request(self, method, path, **kw):
            seen[-1].update(method=method, path=path, **kw)
        def getresponse(self):
            return self
        def read(self, n):
            seen[-1]["bound"] = n
            return body[:n]
        def close(self):
            seen[-1]["closed"] = True
    Connection.status = status
    monkeypatch.setattr(sd.http.client, "HTTPSConnection", Connection)
    return seen


@pytest.mark.parametrize("url", ["http://fake.invalid/token", "https://fake.invalid/#fake", "https://fake.invalid:123456/",
                                 "https://fake.invalid/ fake", "https://fake@fake.invalid/", "https://fake.invalid\n"])
def test_post_form_rejects_scheme_before_connection(monkeypatch, url):
    seen = fake_connection(monkeypatch)
    with pytest.raises(sd.Stop, match="^refresh_error:scheme$"):
        sd.post_form(url, {})
    assert seen == []


@pytest.mark.parametrize("status", [200, 401, 302])
def test_post_form_json_status_and_encoding(monkeypatch, status):
    seen = fake_connection(monkeypatch, status=status, body=b'{"fake":true}' if status == 200 else b"not json")
    same(sd.post_form("https://fake.invalid:443/token", {
        "grant_type": "refresh_token", "refresh_token": "rt-fake+0/x", "client_id": "fake-client"}),
        (status, {"fake": True} if status == 200 else {}))
    assert len(seen) == 1 and seen[0]["bound"] == sd.MAX_BODY + 1 and seen[0]["closed"]
    same(seen[0]["body"], "grant_type=refresh_token&refresh_token=rt-fake%2B0%2Fx&client_id=fake-client")
    same((seen[0]["host"], seen[0]["port"], seen[0]["timeout"], seen[0]["method"], seen[0]["path"]),
         ("fake.invalid", 443, 30, "POST", "/token"))
    assert seen[0]["context"].check_hostname
    same(seen[0]["headers"], {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})


def test_post_form_oversize(monkeypatch):
    monkeypatch.setattr(sd, "MAX_BODY", 16)
    seen = fake_connection(monkeypatch, body=b"x" * 17)
    with pytest.raises(sd.Stop, match="^refresh_error:oversize$"):
        sd.post_form(URL, {})
    assert seen[0]["bound"] == 17 and seen[0]["closed"]


def test_post_form_exception_is_class_only(monkeypatch):
    fake_connection(monkeypatch, error=OSError("fake-secret-host"))
    with pytest.raises(sd.Stop, match="^refresh_error:OSError$") as caught:
        sd.post_form(URL, {})
    assert caught.value.__suppress_context__


def test_post_form_default_path_and_utf8_encoder(monkeypatch):
    seen = fake_connection(monkeypatch)
    sd.post_form("https://fake.invalid", {"fake key": "fake~é"})
    same((seen[0]["path"], seen[0]["body"]), ("/", "fake%20key=fake~%C3%A9"))


def scan_main(home, target, monkeypatch, capsys, *, expected=None):
    monkeypatch.setenv(sd.ENV_STORE, str(home))
    learning = mock.patch.object(sd.Login, "_learn", side_effect=AssertionError("learned before refusal")) if expected else contextlib.nullcontext()
    with learning:
        code = sd.main(["--scan", "--run", RUN, str(target)])
    streams = capsys.readouterr()
    same(streams.err, "")
    result = json.loads(streams.out)
    if expected:
        assert code == 3
        same(result, {"refused": expected})
    return code, result


@pytest.mark.parametrize("kind,reason", [("missing", "no_run_pin"), ("lease", "lease_changed"),
    ("account", "account_changed"), ("unreadable", "pin_file_invalid"), ("lock", "auth_lock_busy")])
def test_scan_refusals_before_learning(home, tmp_path, monkeypatch, capsys, kind, reason):
    target = tmp_path / "fake-clean"
    target.write_text("synthetic body")
    if kind != "missing":
        pin_entry(home)
    if kind == "lease":
        home.with_name("lease.json").write_text(json.dumps({"lease_id": "fake-new-lease"}))
    if kind == "account":
        data = json.loads(home.read_text())
        data["tokens"]["access_token"] = jwt(chatgpt_account_id="fake-new-account")
        home.write_text(json.dumps(data))
    if kind == "unreadable":
        home.with_name("director-pin.json").unlink()
        home.with_name("director-pin.json").mkdir()
    with contextlib.ExitStack() as stack:
        if kind == "lock":
            stream = stack.enter_context(home.with_name("auth.json.lock").open("w"))
            sd.fcntl.flock(stream, sd.fcntl.LOCK_EX)
            monkeypatch.setattr(sd, "SNAPSHOT_WAIT_S", 0)
        scan_main(home, target, monkeypatch, capsys, expected=reason)


@pytest.mark.parametrize("contents", ["{broken-json", "[]", "null", '"fake-file"', '{"fake-run":[]}',
                                     '{"fake-run":"fake-entry"}', '{"fake-run":null}', '{"fake-run":{}}',
                                     '{"fake-run":{"lease_id":null}}'])
def test_e4_scan_invalid_pins_before_learning(home, tmp_path, monkeypatch, capsys, contents):
    home.with_name("director-pin.json").write_text(contents)
    scan_main(home, tmp_path / "fake-target", monkeypatch, capsys, expected="pin_file_invalid")
    same(home.with_name("director-pin.json").read_text(), contents)


@pytest.mark.parametrize("lease", [None, "bad json", '["fake-not-object"]'])
def test_scan_matching_run_and_unparseable_lease(home, tmp_path, monkeypatch, capsys, lease):
    pin_entry(home)
    if lease:
        home.with_name("lease.json").write_text(lease)
    target = tmp_path / "fake-target"
    target.write_text("synthetic body " + ACCT)
    code, result = scan_main(home, target, monkeypatch, capsys)
    assert code == 1 and result["files_scanned"] == 1 and result["hits"] == {"tokens.account_id": 1}


def test_cx4_scan_checks_and_learns_one_snapshot(home, tmp_path, monkeypatch):
    pin_entry(home)
    target = tmp_path / "fake-target"
    target.write_text(ACCT)
    real, reads = Path.read_text, []
    def read(path, *a, **kw):
        if path == home:
            reads.append(1)
            if len(reads) > 1:
                return json.dumps({"tokens": {"account_id": "fake-other-account"}})
        return real(path, *a, **kw)
    monkeypatch.setattr(Path, "read_text", read)
    result = sd.scan(login(home), [target], RUN)
    assert reads == [1] and result["hits"] == {"tokens.account_id": 1}


def test_cx8_scan_waits_for_shared_auth_lock(home, tmp_path, monkeypatch):
    pin_entry(home)
    target = tmp_path / "fake-target"
    target.write_text(ACCT)
    with home.with_name("auth.json.lock").open("w") as stream:
        sd.fcntl.flock(stream, sd.fcntl.LOCK_EX)
        monkeypatch.setattr(sd, "SNAPSHOT_WAIT_S", 0)
        auth = login(home)
        with pytest.raises(sd.Stop, match="^auth_lock_busy$"):
            sd.scan(auth, [target], RUN)
        assert auth.needles() == {}
        real, released, reads, waiting = Path.read_text, [], [], threading.Event()
        sleep = sd.time.sleep
        def read(path, *a, **kw):
            if path == home:
                reads.append(bool(released))
            return real(path, *a, **kw)
        def pause(delay):
            waiting.set()
            return sleep(delay)
        def release():
            assert waiting.wait(3)
            released.append(1)
            sd.fcntl.flock(stream, sd.fcntl.LOCK_UN)
        monkeypatch.setattr(sd, "SNAPSHOT_WAIT_S", 3)
        monkeypatch.setattr(sd.time, "sleep", pause)
        monkeypatch.setattr(Path, "read_text", read)
        worker = threading.Thread(target=release)
        worker.start()
        try:
            result = sd.scan(auth, [target], RUN)
        finally:
            worker.join(4)
        assert not worker.is_alive() and reads == [True]
        assert result["hits"] == {"tokens.account_id": 1}


def test_scan_cli_clean_corrupt_and_hits(home, tmp_path, monkeypatch, capsys):
    pin_entry(home)
    tree = tmp_path / "fake-artifacts"
    tree.mkdir()
    (tree / "fake.log").write_text("synthetic safe body")
    code, result = scan_main(home, tree, monkeypatch, capsys)
    assert code == 0 and result["hits"] == {} and result["unreadable"] == 0
    (tree / "fake.log").write_text(ACCT)
    code, result = scan_main(home, tree, monkeypatch, capsys)
    assert code == 1 and result["hits"] == {"tokens.account_id": 1}
    (tree / "fake.log").write_text("safe body")
    (tree / "fake.json.zst").write_bytes(b"fake corrupt zstd")
    code, result = scan_main(home, tree, monkeypatch, capsys)
    assert code == 1 and result["unreadable"] == 1 and not result["hits"]


def test_scan_counts_files_once_per_label_and_escaped_needles(home, tmp_path):
    auth = login(home)
    needle = "fake-backslash\\user"
    data = json.loads(home.read_text())
    data["tokens"]["access_token"] = jwt(chatgpt_user_id=needle)
    home.write_text(json.dumps(data))
    target = tmp_path / "fake.json.zst"
    target.write_bytes(zstd.compress(canon({"one": needle, "two": needle})))
    result = sd.scan(auth, [target])
    assert result["hits"] == {"claim.chatgpt_user_id": 1} and result["files_scanned"] == 1


def test_needles_guard_base_escaped_and_names(home, monkeypatch):
    data = json.loads(home.read_text())
    needle = "fake-backslash\\user"
    data["tokens"]["access_token"] = jwt(chatgpt_user_id=needle)
    home.write_text(json.dumps(data))
    auth = login(home)
    auth.token()
    guard = sd.NeedleGuard(auth, Guard(["FAKE_BASE_NEEDLE"]))
    monkeypatch.setenv("FAKE_BASE_NEEDLE", "fake-base-secret")
    with pytest.raises(CredentialLeak, match="^credential reached a ledger write$"):
        guard.check(canon({"fake": "fake-base-secret"}))
    with pytest.raises(CredentialLeak, match="^claim.chatgpt_user_id reached a ledger write$"):
        guard.check(canon({needle: needle}))
    assert auth.drain() == [{"type": "guard", "label": "claim.chatgpt_user_id"}]
    same(guard.check(canon({"note": "authorization"})), canon({"note": "authorization"}))
    same(RES in auth.needles(), False)


def test_guard_refuses_secret_label_only(home):
    auth = login(home)
    auth.token()
    with pytest.raises(CredentialLeak, match="^tokens.account_id reached a ledger write$"):
        sd.NeedleGuard(auth).check(canon({ACCT: ACCT}))
    assert auth.drain() == [{"type": "guard", "label": "tokens.account_id"}]


def test_needle_snapshot_does_not_wait_for_refresh_lock(home):
    auth = login(home)
    auth.token()
    before = auth.needles()
    with auth.lock:
        same(auth.needles(), before)
        before.clear()
        assert auth.needles()


@pytest.mark.parametrize("status,raw,reason", [(401, b"{}", "upstream_401"), (403, b"{}", "upstream_403"),
    (200, frames({"type": "error", "message": "Unauthorized fake token"}), "upstream_sse_auth")])
def test_credential_stops_latch(home, setup, status, raw, reason):
    auth, posts = login(home), []
    r, server, _, _ = setup([(status, {}, raw)])
    wrapped = attach(r, auth)
    assert wrapped.respond(call()).status == 503 and len(server.seen) == 1
    assert wrapped.state()["login_stop"] == reason
    assert json.loads(auth.sentinel.read_text())["reason"] == reason
    with mock.patch.object(auth, "refuse", wraps=auth.refuse) as refuse:
        assert wrapped.respond(call()).status == 503
        refuse.assert_not_called()
    second = login(home, post=lambda *a: posts.append(1))
    with pytest.raises(sd.Stop, match=f"^login_latched:{reason}$"):
        second.token()
    assert not posts
    same(wrapped.served_identities(), r.served_identities())
    wrapped.stop("fake-stop")


@pytest.mark.parametrize("kind,reason,n", [("invalid", "upstream_invalid_request_400", 1),
                                         ("unparsed", "upstream_unparsed_3_in_a_row", 3)])
def test_noncredential_stops_do_not_latch(home, setup, kind, reason, n):
    auth = login(home)
    r, server, _, _ = setup([(400, {}, b"fake invalid request")] if kind == "invalid" else [(200, {}, b"fake unparsed")] * 3)
    wrapped = attach(r, auth)
    for _ in range(n):
        assert wrapped.respond(call()).status == 503
    assert len(server.seen) == n and wrapped.state()["stop_reason"] == reason
    assert not auth.dead and not auth.sentinel.exists()


def test_placeholder_idempotent_and_no_login_needles(home, tmp_path):
    harness = tmp_path / "fake-harness"
    harness.mkdir()
    path = sd.install_placeholder(harness)
    first, before = path.read_bytes(), path.stat().st_mtime_ns
    same(sd.install_placeholder(harness), path)
    same(path.read_bytes(), first)
    assert path.stat().st_mtime_ns == before and stat.S_IMODE(path.stat().st_mode) == 0o600
    token = json.loads(first)["providers"]["openai-codex"]["tokens"]["access_token"]
    claims = sd.jwt_claims(token)
    assert claims["exp"] == 4102444800 and claims[sd.AUTH_CLAIM]["chatgpt_account_id"] == "placeholder-account"
    assert sd.scan(login(home), [harness])["hits"] == {}
    path.write_text("fake different auth")
    before = path.read_bytes()
    with pytest.raises(sd.Stop, match="^harness_home_has_auth$"):
        sd.install_placeholder(harness)
    same(path.read_bytes(), before)


def test_import_boundaries():
    tree = ast.parse(Path(sd.__file__).read_text())
    for node in ast.walk(tree):
        names = [n.name for n in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        assert not any(name.startswith(("urllib", "spikes")) for name in names)


def test_header_rebuild_through_r08_and_scan_all_artifacts(home, tmp_path, setup, monkeypatch, capsys):
    auth = open_login(home)
    r, server, _, up = setup([(200, {}, completed(text="hi")), (200, {}, completed()), (401, {}, b"{}")], send_cap=False)
    wrapped = attach(r, auth)
    d = CORE["make"](tmp_path, wrapped)
    d.guard = sd.NeedleGuard(auth, base=Guard([]))
    CORE["start"](d, tmp_path)
    streams = []
    try:
        body = dict(CORE["TITLE"], input=[{"type": "message", "role": "user", "content": "hello"}])
        result = CORE["post"](d, "/aux/title_generation/v1/responses", body)
        assert result[0] == 200
        headers = {k.lower(): v for k, v in server.seen[0]["headers"].items()}
        same(headers["authorization"], "Bearer " + jwt())
        same((headers["chatgpt-account-id"], headers["x-openai-internal-codex-residency"]), (ACCT, RES))
        same((headers["originator"], headers["user-agent"]), ("hermes-agent", "HermesAgent/0.22.2"))
        assert "max_output_tokens" not in server.seen[0]["body"]
        assert UP["tries"](r.respond(call()))[0]["reserved"] == up.price.cost(len(server.seen[1]["raw"]), up.max_output_tokens)
        # Force a successful refresh, then a refused upstream credential, before draining.
        store(tmp_path, 60)
        auth.post = rotated
        assert wrapped.respond(call()).status == 503
        assert auth.dead == "upstream_401"
        for row in auth.drain():
            d.ledger.append(row)
        assert sd.scan(auth, [tmp_path / "ledger"])["hits"] == {}
        monkeypatch.setenv(sd.ENV_STORE, str(home))
        assert sd.main(["--scan", "--run", RUN, str(tmp_path / "ledger")]) == 0
        streams.extend(capsys.readouterr())
        with pytest.raises(SystemExit) as exited:
            sd.exit_on_refusal(sd.Stop("home_busy"))
        assert exited.value.code == 3
        streams.extend(capsys.readouterr())
        # Capture a real module CLI, with only tmp_path synthetic configuration.
        proc = subprocess.run([sys.executable, "-B", "-m", "bicentennial.director.upstream.login", "--scan",
                               "--run", RUN, str(tmp_path / "ledger")], capture_output=True, text=True, timeout=5)
        assert proc.returncode == 0
        streams.extend((proc.stdout, proc.stderr))
    finally:
        d.close()
    artifacts = tmp_path / "fake-streams"
    artifacts.mkdir()
    for index, stream in enumerate(streams):
        (artifacts / f"stream-{index}.log").write_text(stream)
    # The log rows are also checked through a real Ledger, whose guard runs before schema validation.
    with contextlib.closing(Ledger(tmp_path / "fake-extra-ledger", sd.NeedleGuard(auth), lock_hash="ab" * 32,
                                  attempt_id="fake-attempt")) as ledger:
        for row in auth.drain():
            ledger.append(row)
    assert sd.scan(auth, [tmp_path / "ledger", artifacts, tmp_path / "fake-extra-ledger"])["hits"] == {}
    pins = json.loads(home.with_name("director-pin.json").read_text())
    credentials = [jwt(), jwt(60), jwt(3600, 1), jwt(3600, 2), jwt(3600, 99), "rt-fake-0", "rt-fake-rotated",
                   ACCT, USER, EMAIL, pins[RUN]["pin"], "fake-lease", str(home)]
    for tree in (tmp_path / "ledger", artifacts, tmp_path / "fake-extra-ledger"):
        for path in tree.rglob("*"):
            if path.is_file():
                data = path.read_bytes()
                data = zstd.decompress(data) if path.suffix == ".zst" else data
                for value in credentials:
                    same(value.encode() in data, False)
                for name in sd.IDENTITY_NAMES:
                    same(name.encode() in data.lower(), False)


def test_echo_guard_stops_admission_before_harness_response(home, tmp_path, setup):
    auth = open_login(home)
    auth.drain()
    r, server, _, _ = setup([(200, {}, completed(text="hi " + USER))])
    wrapped = attach(r, auth)
    d = CORE["make"](tmp_path, wrapped)
    d.guard = sd.NeedleGuard(auth, base=Guard([]))
    CORE["start"](d, tmp_path)
    try:
        body = dict(CORE["TITLE"], input=[{"type": "message", "role": "user", "content": "hello"}])
        with pytest.raises(CredentialLeak, match="^claim.sub reached a ledger write$"):
            CORE["post"](d, "/aux/title_generation/v1/responses", body)
        assert d.stopped and len(server.seen) == 1
        assert (tmp_path / "ledger" / "ledger.jsonl").read_bytes() == b""
        # Caller drains A2's safe failure row and can persist it after the failed request.
        rows = auth.drain()
        assert rows == [{"type": "guard", "label": "claim.sub"}]
        for row in rows:
            d.ledger.append(row)
        assert sd.scan(auth, [tmp_path / "ledger"])["hits"] == {}
    finally:
        d.close()


def test_expiring_token_refreshes_after_pace_wait(tmp_path, setup, monkeypatch):
    path, refreshed = store(tmp_path, 302), []
    r, server, clock, _ = setup(default=(200, {}, completed()), rate=1 / 6, burst=1)
    def post(*a):
        refreshed.append(clock.now)
        return rotated()
    auth = login(path, post=post)
    wrapped = attach(r, auth)
    monkeypatch.setattr(sd.time, "time", lambda: NOW + clock.now)
    assert [wrapped.respond(call()).status for _ in range(2)] == [200, 200]
    assert list(map(round, refreshed)) == [360]
    same(server.seen[0]["headers"]["Authorization"] == server.seen[1]["headers"]["Authorization"], False)
    same(server.seen[1]["headers"]["Authorization"], "Bearer " + json.loads(path.read_text())["tokens"]["access_token"])
    assert len(auth.drain()) == 1


def test_refused_refresh_after_wait_is_charged_and_unsent(tmp_path, setup, monkeypatch):
    path, refreshes = store(tmp_path, 302), []
    r, server, clock, up = setup(default=(200, {}, completed()), rate=1 / 6, burst=1)
    auth = login(path, post=lambda *a: (401, {}), on_refresh=lambda: (refreshes.append(1), True)[1])
    wrapped = attach(r, auth)
    monkeypatch.setattr(sd.time, "time", lambda: NOW + clock.now)
    assert wrapped.respond(call()).status == 200
    before = json.loads(up.spend.path.read_text())["settled"]
    reply = wrapped.respond(call())
    assert reply.status == 503 and len(server.seen) == 1 and refreshes == [1]
    assert UP["tries"](reply)[0]["charged"] == 0
    assert json.loads(up.spend.path.read_text())["settled"] == before
    assert auth.drain()[0]["status"] == 401


@pytest.mark.parametrize("blocked,admissions,bearer", [(30, 3, 3), (0, 2, 2)])
def test_post_wait_blocking_read_is_readmitted(home, setup, monkeypatch, blocked, admissions, bearer):
    r, server, clock, _ = setup(default=(200, {}, completed()), rate=180, burst=1)
    auth, reads = login(home), []
    def token():
        reads.append(clock.now)
        if len(reads) == 2 and blocked:
            clock.sleep(blocked)
        return f"fake-bearer-{len(reads)}"
    monkeypatch.setattr(auth, "token", token)
    r.pacer.acquire = mock.Mock(wraps=r.pacer.acquire)
    wrapped = attach(r, auth)
    first, second = wrapped.respond(call()), wrapped.respond(call())
    assert first.status == second.status == 200 and r.pacer.acquire.call_count == admissions
    same(server.seen[-1]["headers"]["Authorization"], f"Bearer fake-bearer-{bearer}")
    sent = UP["tries"](second)[0]["t_sent_ms"]
    assert abs(sent - (1000 / 3 + blocked * 1000)) <= 1
    # A3: auth_for's readmission is excluded from LiveResponder's pace_wait_ms.
    assert abs(UP["tries"](second)[0]["pace_wait_ms"] - 1000 / 3) <= 1


def test_no_wait_reads_token_once(home, setup, monkeypatch):
    r, _, _, _ = setup([(200, {}, completed())])
    auth = login(home)
    monkeypatch.setattr(auth, "token", mock.Mock(return_value="fake-bearer"))
    assert attach(r, auth).respond(call()).status == 200
    auth.token.assert_called_once_with()


def test_login_stop_on_post_wait_read_settles_unsent(home, setup, monkeypatch):
    r, server, _, up = setup()
    auth = login(home)
    auth.latch("refresh_budget", persist=False)
    r.pacer.acquire = mock.Mock(return_value=1000)
    wrapped = attach(r, auth)
    reply = wrapped.respond(call())
    assert reply.status == 503 and server.seen == []
    assert UP["tries"](reply)[0]["charged"] == 0
    assert wrapped.state()["stop_reason"] == "responder_error:stop" and wrapped.state()["login_stop"] == "refresh_budget"
    spent = json.loads(up.spend.path.read_text())
    assert spent["open"] == {} and spent["settled"] == 0
    r.pacer.acquire.assert_called_once_with()


def test_auth_for_stop_during_readmission_returns_last_headers(home, setup, monkeypatch):
    r, server, clock, _ = setup()
    auth = login(home)
    def token():
        clock.sleep(30)
        return "fake-bearer"
    def acquire():
        r.pacer.stop.set()
        return None
    monkeypatch.setattr(auth, "token", token)
    r.pacer.acquire = mock.Mock(side_effect=[0, None])
    # Real acquire returns None only after stop: inject that stop on the second admission.
    n = []
    def admit():
        n.append(1)
        return 0 if len(n) == 1 else acquire()
    r.pacer.acquire.side_effect = admit
    reply = attach(r, auth).respond(call())
    assert reply.status == 503 and not server.seen
    assert UP["tries"](reply)[0]["charged"] == 0


def test_scan_learns_only_supplied_snapshot(home, tmp_path):
    auth = login(home)
    auth.token()
    data = json.loads(home.read_text())
    old_refresh = data["tokens"]["refresh_token"]
    data["tokens"]["refresh_token"] = "rt-fake-new-for-scan"
    home.write_text(json.dumps(data))
    target = tmp_path / "fake-target"
    target.write_text(old_refresh)
    assert sd.scan(auth, [target])["hits"] == {}


def test_post_form_close_failure_is_class_only(monkeypatch):
    fake_connection(monkeypatch)
    monkeypatch.setattr(sd.http.client.HTTPSConnection, "close", mock.Mock(side_effect=OSError("fake private host")))
    with pytest.raises(sd.Stop, match="^refresh_error:OSError$") as caught:
        sd.post_form(URL, {})
    assert caught.value.__suppress_context__


@pytest.mark.parametrize("indent,newline", [(None, False), (1, True), (4, False)])
def test_refresh_preserves_store_format(tmp_path, indent, newline):
    path = store(tmp_path, 60)
    data = json.loads(path.read_text())
    del data["last_refresh"]
    path.write_text(json.dumps(data, indent=indent) + ("\n" if newline else ""))
    auth = login(path, post=rotated)
    auth.token()
    saved = json.loads(path.read_text())
    same(path.read_text(), json.dumps(saved, indent=indent) + ("\n" if newline else ""))
    assert "last_refresh" not in saved


def test_refresh_learns_old_and_successor_needles(tmp_path):
    path = store(tmp_path, 60)
    old = json.loads(path.read_text())["tokens"]
    auth = login(path, post=rotated)
    auth.token()
    needles = auth.needles()
    for value in list(old.values()) + [jwt(3600, 1), jwt(3600, 2), "rt-fake-rotated"]:
        same(value in needles, True)


def test_refusal_at_startup_returns_holder_and_refresh_row(tmp_path):
    path, refreshes = store(tmp_path, 60), []
    with pytest.raises(sd.Stop, match="^token_endpoint_401$") as caught:
        open_login(path, post=lambda *a: (401, {}), on_refresh=lambda: (refreshes.append(1), True)[1])
    assert refreshes == [1]
    assert caught.value.records == ({"type": "holder", "lease": False}, {
        "type": "refresh", "status": 401, "t": NOW * 1000, "lifetime_s": None, "rotated": False})
    canon(caught.value.records)


@pytest.mark.parametrize("blocked,admissions,bearer", [(30, 3, 3), (0, 2, 2)])
def test_auth_adapter_readmission_without_socket(home, monkeypatch, blocked, admissions, bearer):
    clock = Clock()
    pacer = UP["Pacer"](180, 1, threading.Event(), clock, clock.sleep)
    pacer.acquire = mock.Mock(wraps=pacer.acquire)
    auth, reads = login(home), []
    def token():
        reads.append(clock.now)
        if len(reads) == 2 and blocked:
            clock.sleep(blocked)
        return f"fake-bearer-{len(reads)}"
    monkeypatch.setattr(auth, "token", token)
    headers = sd.auth_for(auth, pacer)
    assert headers.handles_readmission is True
    for _ in range(2):
        pacer.acquire()
        last = headers()
    assert pacer.acquire.call_count == admissions
    same(last["Authorization"], f"Bearer fake-bearer-{bearer}")
    assert abs(clock.now - (1 / 3 + blocked)) < 0.001


def test_startup_sentinel_failure_returns_budget_and_safe_records(tmp_path, monkeypatch):
    path, posts, budget, unsent = store(tmp_path, 60), [], [], []
    real = sd.durable_write
    def deny(path, data, **kw):
        if path.name.endswith(".stopped"):
            raise OSError("fake sentinel write failure")
        return real(path, data, **kw)
    monkeypatch.setattr(sd, "durable_write", deny)
    with pytest.raises(sd.Stop, match="^refresh_sentinel_failed$") as caught:
        open_login(path, post=lambda *a: posts.append(1), on_refresh=lambda: (budget.append(1), True)[1],
                   on_unsent=lambda: unsent.append(1))
    assert not posts and budget == unsent == [1]
    assert caught.value.records == ({"type": "holder", "lease": False}, {
        "type": "sentinel_error", "error": "OSError", "t": NOW * 1000})
    assert not path.with_name("auth.json.stopped").exists()


@pytest.mark.parametrize("managed", [False, True])
def test_live_readmission_in_memory_transport(home, tmp_path, monkeypatch, managed):
    clock, seen, reads, admissions = Clock(), [], [], []
    price = UP["Price"](0, 400_000)
    spend = UP["Spend"](tmp_path / "fake-spend.json", 10**9, price)
    up = UP["Upstream"]("fake", "probe-model", "https://fake.invalid/v1", "responses", spend, price, 1000, send_cap=False)
    pacer = UP["Pacer"](180, 1, threading.Event(), clock, clock.sleep)
    token = ["fake-before-readmit"]
    def bearer():
        reads.append(clock.now)
        if len(reads) == 1:
            clock.sleep(30)
        return token[0]
    def acquire():
        admissions.append(1)
        if len(admissions) == 2:
            clock.sleep(30)
            token[0] = "fake-after-readmit"
        return 0
    pacer.acquire = acquire
    auth = login(home)
    monkeypatch.setattr(auth, "token", bearer)
    headers = sd.auth_for(auth, pacer) if managed else lambda: {"Authorization": "Bearer " + bearer()}
    def send(up, data, headers):
        seen.append((json.loads(data), headers))
        return dict(status=200, category=None, retry_after_s=None, body_shape=None, body_read_error=None,
                    n_unparsed=0, n_dropped_items=0, served_model="probe-model", usage=None, text="hi",
                    tool_calls=(), forward=True, stop_reason=None)
    monkeypatch.setattr(UP["forward"], "send", send)
    responder = UP["LiveResponder"]("fake-account", pacer, headers, [up], UP["Holds"](clock=clock, sleep=clock.sleep))
    reply = responder.respond(call(body={"max_output_tokens": 50}))
    assert reply.status == 200 and len(admissions) == len(reads) == 2
    assert reads == [0, 60] and "max_output_tokens" not in seen[0][0]
    same(seen[0][1]["Authorization"], "Bearer fake-after-readmit")
    assert UP["tries"](reply)[0]["reserved"] == price.cost(0, 1000)
    assert UP["tries"](reply)[0]["t_sent_ms"] == 60000
