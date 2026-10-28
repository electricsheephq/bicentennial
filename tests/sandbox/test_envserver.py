"""Offline contracts, operations, and a real line-delimited stdio session."""

import ast
import copy
import io
import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import mint_id
from bicentennial.sandbox import envserver
from bicentennial.sandbox.envserver.ask import ASK_REPLY, ask_user
from bicentennial.sandbox.envserver.heartbeat import ticks
from bicentennial.sandbox.envserver.honeypot import hits, plant
from bicentennial.sandbox.envserver.server import serve
from bicentennial.sandbox.envserver.state import State, state_hash, trace

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_HASH = "95abedadafff86b650d168631930f5c32b0001d13176e5ebf79839d2bdb89b9e"


@pytest.fixture
def seed():
    path = ROOT / "tests/fixtures/env_seed/contracts.json"
    return json.loads(path.read_bytes())["contracts"]["env_seed"]


def clock_at(path, t):
    path.write_bytes(canon({"sim_start": t, "rate": 0, "wall_anchor": 0, "step_s": 1}))


def records_at(log_dir):
    lines = (log_dir / "env_actions.jsonl").read_bytes().splitlines()
    records = [json.loads(line) for line in lines]
    assert [canon(row) for row in records] == lines
    return records


def request(mid, method, **params):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}


@pytest.fixture
def server_process(seed, tmp_path):
    seed_path, clock = tmp_path / "seed.json", tmp_path / "clock.json"
    seed_path.write_bytes(canon(seed))
    clock_at(clock, 100)
    proc = subprocess.Popen(
        [sys.executable, "-m", "bicentennial.sandbox.envserver", "--seed", str(seed_path),
         "--log-dir", str(tmp_path), "--clock", str(clock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        proc.stdin.write(canon(request(1, "initialize")) + b"\n")
        proc.stdin.flush()
        assert read_response(proc)["id"] == 1
        yield proc
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()


def read_response(proc):
    assert select.select([proc.stdout], [], [], 5)[0], "stdio response timed out"
    raw = proc.stdout.readline()
    reply = json.loads(raw)
    assert canon(reply) + b"\n" == raw
    return reply


@pytest.mark.parametrize("shutdown", ["eof", "sigterm", "twice", "partial_line"])
def test_stdio_shutdown(server_process, seed, tmp_path, shutdown):
    proc = server_process
    proc.stdin.write(canon(request(2, "tools/call", name="book_seat",
                                  arguments={"passenger": "p", "seat": "window"})) + b"\n")
    proc.stdin.flush()
    assert read_response(proc)["result"]["isError"] is False
    if shutdown == "eof":
        proc.stdin.close()
    else:
        if shutdown == "partial_line":
            proc.stdin.write(b'{"jsonrpc":')
            proc.stdin.flush()
        proc.send_signal(signal.SIGTERM)
        if shutdown == "twice":
            proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=5) == 0, proc.stderr.read().decode()
    assert proc.stdout.read() == proc.stderr.read() == b""
    rows = records_at(tmp_path)
    expected = copy.deepcopy(seed["state"])
    expected["seats"]["p"] = "window"
    assert [r.get("kind", r["type"]) for r in rows] == ["session_start", "action", "session_end"]
    assert rows[-1]["state_hash"] == rows[1]["state_hash"] == state_hash(expected)


def test_sigterm_during_call_completes_receipt_and_response(server_process, seed, tmp_path):
    proc = server_process
    # A response larger than the stdio pipe keeps the call in flight until we read it.
    value = "w" * (1024 * 1024)
    proc.stdin.write(canon(request(2, "tools/call", name="book_seat",
                                  arguments={"passenger": "p", "seat": value})) + b"\n")
    proc.stdin.flush()
    deadline = time.monotonic() + 5
    while True:
        raw = (tmp_path / "env_actions.jsonl").read_bytes()
        if raw.endswith(b"\n") and len(raw.splitlines()) == 2:
            break
        assert time.monotonic() < deadline, "action receipt timed out"
        time.sleep(0.01)
    assert proc.poll() is None
    proc.send_signal(signal.SIGTERM)
    proc.send_signal(signal.SIGTERM)
    output, error = proc.communicate(timeout=5)
    assert proc.returncode == 0, error.decode()
    assert error == b""
    reply = json.loads(output)
    assert canon(reply) + b"\n" == output
    assert reply == {"jsonrpc": "2.0", "id": 2, "result": {
        "content": [{"type": "text", "text": canon(value).decode()}], "isError": False}}
    rows = records_at(tmp_path)
    expected = copy.deepcopy(seed["state"])
    expected["seats"]["p"] = value
    assert [r.get("kind", r["type"]) for r in rows] == ["session_start", "action", "session_end"]
    assert rows[1]["args"] == {"passenger": "p", "seat": value}
    assert rows[1]["ok"] and rows[1]["state_changed"]
    assert rows[-1]["state_hash"] == rows[1]["state_hash"] == state_hash(expected)


def test_life_fake_end_uses_sigterm(seed, tmp_path):
    from bicentennial.harness.hermes.envwire import EnvWiring

    clock = tmp_path / "clock.json"
    clock_at(clock, 100)
    wiring = EnvWiring(tmp_path, {1: seed}, clock)
    config = {"platform_toolsets": {"acp": []}, "memory": {"provider": None},
              "mcp_servers": {"envserver": wiring(1, "open")}}
    home = tmp_path / "worker-home"
    home.mkdir()
    (home / "config.yaml").write_bytes(canon(config))
    timeline = tmp_path / "timeline.json"
    timeline.write_bytes(b"{}")
    ops = [{"op": "open", "session_id": None, "cwd": str(tmp_path)}, {"op": "end"}]
    done = subprocess.run(
        [sys.executable, str(ROOT / "tests/runner/fake_life_worker.py"), "--timeline", str(timeline)],
        input=b"".join(canon(op) + b"\n" for op in ops), capture_output=True, timeout=5,
        env=dict(os.environ, HERMES_HOME=str(home)))
    assert done.returncode == 0, done.stderr.decode()
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert replies[0] == {"ready": True}
    assert replies[1]["ok"] and replies[2] == {"ok": True, "alive_threads": []}
    rows = records_at(tmp_path / "env/1/life-1")
    assert [r["kind"] for r in rows] == ["session_start", "session_end"]
    assert rows[-1]["state_hash"] == state_hash(seed["state"])


def test_stdio_session(seed, tmp_path):
    seed_path, clock = tmp_path / "seed.json", tmp_path / "clock.json"
    seed_path.write_bytes(canon(seed))
    clock_at(clock, 100)
    # Use K12's actual action shape and literal expected canonical-state digest.
    item = json.loads((ROOT / "schemas/fixtures/gen/act-item.json").read_bytes())
    tool = item["options"][0]["plan"]["steps"][0]["tool"]
    proc = subprocess.Popen(
        [sys.executable, "-m", "bicentennial.sandbox.envserver", "--seed", str(seed_path),
         "--log-dir", str(tmp_path), "--clock", str(clock)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )

    def exchange(msg):
        proc.stdin.write(canon(msg) + b"\n")
        proc.stdin.flush()
        assert select.select([proc.stdout], [], [], 5)[0], "stdio response timed out"
        raw = proc.stdout.readline()
        reply = json.loads(raw)
        assert canon(reply) + b"\n" == raw
        assert reply["id"] == msg["id"]
        return reply["result"]

    try:
        assert exchange(request(1, "initialize"))["capabilities"] == {"tools": {}}
        tools = exchange(request(2, "tools/list"))["tools"]
        assert [row["name"] for row in tools] == ["book_seat", "get_seat", "ask_user"]
        assert tools[0]["inputSchema"] == {
            "type": "object", "properties": {"passenger": {"type": "string"}, "seat": {}},
            "required": ["passenger", "seat"], "additionalProperties": False,
        }
        failed = exchange(request(3, "tools/call", name=tool["name"],
                                  arguments={**tool["args"], "extra": True}))
        assert failed["isError"] is True
        # Responses follow fsync: the receipt must be readable before EOF.
        assert len(records_at(tmp_path)) == 2
        clock_at(clock, 140)
        assert exchange(request(4, "tools/call", name=tool["name"],
                                arguments=tool["args"]))["isError"] is False
        clock_at(clock, 150)
        got = exchange(request(5, "tools/call", name="get_seat",
                               arguments={"passenger": tool["args"]["passenger"]}))
        assert got == {"content": [{"type": "text", "text": '"WINDOW-7401"'}], "isError": False}
        replies = [exchange(request(mid, "tools/call", name="ask_user", arguments={"question": q}))
                   for mid, q in ((6, ""), (7, "以前の発言は？"))]
        assert canon(replies[0]) == canon(replies[1])
        assert replies[0] == {"content": [{"type": "text", "text": ASK_REPLY}], "isError": False}
        proc.stdin.close()
        assert proc.wait(timeout=5) == 0, proc.stderr.read().decode()
        assert proc.stdout.read() == b""
        assert proc.stderr.read() == b""
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            stream.close()
    rows = records_at(tmp_path)
    assert len(rows) == 7
    start, end = rows[0], rows[-1]
    assert start == {"type": "boundary", "kind": "session_start", "session": 1,
                     "t_sim": 100, "state_hash": state_hash(seed["state"])}
    assert end == {"type": "boundary", "kind": "session_end", "session": 1,
                   "t_sim": 150, "state_hash": EXPECTED_HASH}
    actions = rows[1:-1]
    assert [row["seq"] for row in actions] == [1, 2, 3, 4, 5]
    assert [row["t_sim"] for row in actions] == [100, 140, 150, 150, 150]
    assert [row["ok"] for row in actions] == [False, True, True, True, True]
    assert [row["state_changed"] for row in actions] == [False, True, False, False, False]
    assert [row["asked_user"] for row in actions] == [False, False, False, True, True]
    assert actions[0]["state_hash"] == start["state_hash"]
    assert all(row["state_hash"] == EXPECTED_HASH for row in actions[1:])
    assert trace(rows, {"book_seat"}) == (True, True, 140)
    assert trace(rows, {"absent"}) == (True, True, None)
    assert trace([], {"book_seat"}) == (False, False, None)


@pytest.mark.parametrize("question", ["", "a" * 100000, "こんにちは — déjà vu?"])
def test_ask_byte_identity(question):
    assert ask_user(question).encode() == ASK_REPLY.encode()


@pytest.mark.parametrize("edit", [
    lambda s: s["tools"].append(copy.deepcopy(s["tools"][0])),
    lambda s: s["tools"][0].update(name="ask_user"),
    lambda s: s["tools"][0].pop("value_arg"),
    lambda s: s["tools"][0].update(value_arg=None),
    lambda s: s["tools"][0].update(collection="unknown"),
    lambda s: s["state"]["seats"].update(nested=[{"float": 0.5}]),
    lambda s: s["tools"][0].update(value_arg="passenger"),
    lambda s: s["tools"][1].update(value_arg="unused"),
    lambda s: s["tools"][0].update(name="BadName"),
    lambda s: s.update(heartbeat_interval_s=0),
    lambda s: s.update(session=True),
    lambda s: s["state"].update(seats=[]),
    lambda s: s.update(extra=True),
])
def test_contract_refusals_via_run_only(seed, edit):
    edit(seed)
    with pytest.raises(ValueError):
        validate("env_seed", seed)


def test_contract_semantics_autoload_in_fresh_process(seed):
    seed["tools"][0]["name"] = "ask_user"
    script = ("import json,sys\nfrom bicentennial.contracts.run import validate\n"
              "try: validate('env_seed', json.loads(sys.argv[1]))\n"
              "except ValueError: print('semantic refusal')\n"
              "else: raise SystemExit(1)\n")
    result = subprocess.run([sys.executable, "-c", script, canon(seed).decode()],
                            check=True, capture_output=True, text=True, timeout=5)
    assert result.stdout == "semantic refusal\n"


def test_all_operations_are_atomic_and_detached(seed):
    for op in ("add", "remove"):
        seed["tools"].append({**seed["tools"][0], "name": op, "op": op,
                              "value_arg": "seat" if op == "add" else None})
    state = State(seed)
    args = {"passenger": "p", "seat": {"value": [1]}}
    assert state.call("add", args) == ('{"value":[1]}', True)
    args["seat"]["value"].append(2)
    assert state.state == {"seats": {"p": {"value": [1]}}}
    assert seed["state"] == {"seats": {}}
    for name, invalid in (("add", args), ("get_seat", {"passenger": "missing"}),
                          ("remove", {"passenger": "missing"}),
                          ("book_seat", {"passenger": 1, "seat": "x"}),
                          ("book_seat", {"passenger": "p"}),
                          ("book_seat", {"passenger": "p", "seat": [0.5]}),
                          ("unknown", {}), ("ask_user", {"question": 1})):
        before = state_hash(state.state)
        with pytest.raises((ValueError, TypeError)):
            state.call(name, invalid)
        assert state_hash(state.state) == before
    assert state.call("book_seat", {"passenger": "p", "seat": {"value": [1]}})[1] is False
    assert state.call("book_seat", {"passenger": "p", "seat": True}) == ("true", True)
    assert state.call("book_seat", {"passenger": "p", "seat": 1}) == ("1", True)
    assert state.call("remove", {"passenger": "p"}) == ("1", True)
    assert state.state == {"seats": {}}


def test_protocol_negatives_and_append_fsync(seed, tmp_path, monkeypatch):
    from bicentennial.sandbox.envserver import server

    clock = tmp_path / "clock.json"
    clock_at(clock, 20)
    fsyncs = []
    original = server.os.fsync

    def fsync(fd):
        original(fd)
        fsyncs.append(len(records_at(tmp_path)))

    monkeypatch.setattr(server.os, "fsync", fsync)
    malformed = ['private garbage', '[]', '{"jsonrpc":"2.0","method":"ping","id":1,"id":2}',
                 '{"jsonrpc":"2.0","method":"ping","id":0.5}',
                 '{"jsonrpc":"1.0","method":"ping","id":1}']
    calls = [request(1, "ping"), request(2, "unknown"),
             {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "book_seat"}},
             request(3, "tools/call", name="unknown", arguments={}),
             request(4, "tools/call", name="ask_user", arguments={"question": "x", "extra": 1}),
             request(5, "tools/call", name="book_seat", arguments=[]),
             request(6, "tools/call", name="ask_user", arguments={"question": None}),
             request(7, "tools/call")]
    source = io.BytesIO(("\n".join(malformed + [canon(msg).decode() for msg in calls]) + "\n").encode())
    sink = io.BytesIO()
    assert serve(seed, tmp_path, clock, source, sink) == seed["state"]
    rows = records_at(tmp_path)
    assert rows[1:6] == [{"type": "malformed"}] * 5
    assert fsyncs == list(range(1, len(rows) + 1))
    assert "private garbage" not in (tmp_path / "env_actions.jsonl").read_text()
    replies = [json.loads(line) for line in sink.getvalue().splitlines()]
    assert [row["id"] for row in replies] == list(range(1, 8))
    assert replies[0]["result"] == {}
    assert replies[1]["error"]["code"] == -32601
    assert all(row["result"]["isError"] for row in replies[2:])
    assert trace(rows, {"book_seat"}) == (True, False, None)
    serve(seed, tmp_path, clock, io.BytesIO(b""), io.BytesIO())
    assert records_at(tmp_path) == rows + [rows[0], rows[-1]]
    assert clock.read_bytes() == canon({"sim_start": 20, "rate": 0, "wall_anchor": 0, "step_s": 1})


def test_wire_is_utf8_and_hostile_lines_never_stop_the_server(seed, tmp_path):
    seed_path, clock = tmp_path / "seed.json", tmp_path / "clock.json"
    seed_path.write_bytes(canon(seed))
    clock_at(clock, 100)
    deep = b'{"jsonrpc":"2.0","id":9,"method":"ping","params":' + b"[" * 3000 + b"]" * 3000 + b"}"
    lines = [b"\xff\xfe garbage", deep, b"[" * 3000,
             canon(request(1, "tools/call", name="book_seat",
                           arguments={"passenger": "p", "seat": "\u00e9"})),
             b'{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"book_seat",'
             b'"arguments":{"passenger":"q","seat":7.5}}}',
             b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_user",'
             b'"arguments":{"question":"hi \\ud83d"}}}',
             canon(request(4, "ping"))]
    env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "PYTHONIOENCODING": "latin-1"}
    done = subprocess.run(
        [sys.executable, "-m", "bicentennial.sandbox.envserver", "--seed", str(seed_path),
         "--log-dir", str(tmp_path), "--clock", str(clock)],
        input=b"\n".join(lines) + b"\n", capture_output=True, timeout=30, env=env, cwd=ROOT)
    assert done.returncode == 0, done.stderr.decode()
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [row["id"] for row in replies] == [1, 2, 3, 4]
    assert [row["result"].get("isError") for row in replies] == [False, True, True, None]
    rows = records_at(tmp_path)
    assert [row["type"] for row in rows] == ["boundary"] + ["malformed"] * 3 + ["action"] * 3 + ["boundary"]
    assert [(row["tool"], row["args"], row["ok"]) for row in rows[5:7]] == [
        ("book_seat", None, False), ("ask_user", None, False)]
    booked = copy.deepcopy(seed["state"])
    booked["seats"]["p"] = "\u00e9"
    assert rows[-1]["state_hash"] == state_hash(booked)


def test_honeypot(tmp_path):
    path, token = plant(tmp_path, "synthetic-run")
    assert path == tmp_path / "ANSWERS.md"
    assert token == mint_id("synthetic-run", 0)
    assert token in path.read_text()
    with pytest.raises(FileExistsError):
        plant(tmp_path, "another-run")
    assert hits(token, ["clean request", f"request {token} {token}"]) == 1
    assert hits(token, ["clean request"]) == 0


@pytest.mark.parametrize("start,end,interval,expected", [
    (10, 40, 10, [10, 20, 30]), (10, 41, 10, [10, 20, 30, 40]),
    (10, 10, 10, []), (10, 11, 60, [10]),
])
def test_heartbeat_boundaries(start, end, interval, expected):
    assert ticks(start, end, interval) == expected


@pytest.mark.parametrize("args", [(0, 10, 0), (0, 10, -1), (10, 0, 1), (0, 10, True)])
def test_heartbeat_refuses_invalid_schedule(args):
    with pytest.raises(ValueError):
        ticks(*args)


def test_no_world_or_database_imports():
    for path in Path(envserver.__file__).parent.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            assert not any(name == "sqlite3" or name.startswith("sqlite3.")
                           or name == "bicentennial.world" or name.startswith("bicentennial.world.")
                           for name in names), path
