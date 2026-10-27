"""Offline acceptance for the lossy S6a bridge; spike code runs only in copies."""

import ast
import json
import os
import runpy
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.genres.g1_software.world import (
    PROCESS,
    build_golden,
    golden_schedule,
    load_golden,
    world_meta,
)
from bicentennial.render.export_s6a import (
    ASSISTANT,
    EXPORTER,
    FORMAT,
    JOIN,
    LOSSY,
    PLACEHOLDER_STATE,
    export_bytes,
    export_s6a,
    write_s6a,
)
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import _canary, seal, stream_hash
from bicentennial.world import create_world, world_hash
from bicentennial.world import db as writers
from bicentennial.world.processes import mint
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = ROOT / "tests/fixtures/g1_golden_tidewater.toml"
GOLDEN_SHA256 = "4df024d7cbaaaf2e281eb07a1e3058f41f30339a99f28182b87b87e1506196e6"
TOKEN = "TOK-4410"


def states(schedule):
    return {p.index: dict(PLACEHOLDER_STATE) for p in schedule.sessions}


def golden_world(golden_path, workdir, *, branch="B0"):
    golden = load_golden(golden_path)
    schedule = golden_schedule(golden)
    db = create_world(Path(workdir) / "world.db", world_meta(schedule.seed, len(schedule.sessions)))
    try:
        build_golden(db, golden, schedule)
        principal = mint(schedule, PROCESS, "entities", "entity", golden.principal, 0)
        result = cut(db, schedule, branch=branch, principal_id=principal, expected_state=states(schedule))
        return db, schedule, result
    except BaseException:
        db.close()
        raise


def export_golden(golden_path, workdir, *, branch="B0") -> dict:
    db, schedule, result = golden_world(golden_path, workdir, branch=branch)
    try:
        return export_s6a(db, result, schedule)
    finally:
        db.close()


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    db, schedule, result = golden_world(GOLDEN_PATH, tmp_path_factory.mktemp("g10-golden"))
    yield db, schedule, result, export_s6a(db, result, schedule)
    db.close()


def build_world(path, *, tool=False, wake=None):
    schedule = build_schedule("g10-tool", "life-a", named("t0-micro", sessions=3, wake=wake))
    db = create_world(path, dict(generator_version="g10", genre="G1", seed="g10-tool", scale=3))
    writers.insert_entity(db, id="principal", kind="person", canonical_name="Synthetic lead",
                          aliases_json=[], created_t=0, retired_t=None)
    write_sessions(db, schedule)

    def event(eid, t, kind="turn", channel="chat", payload=None):
        writers.insert_event(db, id=eid, t_sim=t, kind=kind, channel=channel, actor_id="principal",
                             audience_json=["agent"], visibility="shared", salience=500,
                             payload_json={} if payload is None else payload)

    for plan in schedule.sessions:
        for n, t in enumerate(plan.turn_t, 1):
            event(f"chat-{plan.index}-{n}", t + 60)
    writers.insert_fact(db, id="fact-a", subject_id="principal", predicate="deploy_code", object=TOKEN,
                        polarity="affirm", modality="stated", strength=1000, speech_act="assert")
    writers.insert_locked_token(db, token_id="token-a", fact_id="fact-a", kind="code", value=TOKEN)
    writers.insert_link(db, event_id="chat-1-1", fact_id="fact-a", role="assert")
    if tool:
        payload = {"tool": {"name": "repo.read", "args": {"path": "log.txt"}},
                   "result": {"stdout": f"output {TOKEN} end"}}
        event("tool-event", schedule.sessions[2].turn_t[1] + 61, "tool", "tool_result", payload)
        writers.insert_link(db, event_id="tool-event", fact_id="fact-a", role="assert")
    result = cut(db, schedule, branch="B0", principal_id="principal", expected_state=states(schedule))
    return db, schedule, result


@pytest.fixture
def small(tmp_path):
    db, schedule, result = build_world(tmp_path / "world.db")
    yield db, schedule, result
    db.close()


def shape(life):
    return [(s["index"], len(s["turns"]), s.get("restart_after_turn"),
             s.get("long_session", False), s.get("gap_before", False), sorted(s))
            for s in life["sessions"]]


def test_tidewater_structure(golden):
    _, schedule, result, life = golden
    micro = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
    assert shape(life) == shape(micro)
    assert [s["index"] for s in life["sessions"]] == list(range(1, 11))
    assert [len(s["turns"]) for s in life["sessions"]] == [5, 5, 5, 5, 5, 15, 5, 5, 5, 5]
    assert [(s["index"], s["restart_after_turn"]) for s in life["sessions"]
            if "restart_after_turn" in s] == [(5, 2)]
    assert [s["index"] for s in life["sessions"] if s.get("long_session")] == [6]
    assert [s["index"] for s in life["sessions"] if s.get("gap_before")] == [8]
    assert set(life) == {"genre", "seed", "synthetic", "export", "sessions", "probes"}
    assert (life["genre"], life["seed"], life["synthetic"], life["probes"]) == ("G1", "6101", True, [])
    assert life["export"] == {
        "canary": _canary(), "format": FORMAT, "exporter": EXPORTER, "lossy": True,
        "lossy_mappings": ["tool_as_user", "rows_joined", "assistant_placeholder", "wall_time",
                           "session_fields", "no_probes", "no_gold"],
        "life": schedule.life, "branch": "B0", "world_hash": result.world_hash,
        "schedule_sha256": result.schedule_sha256, "stream_hash": stream_hash(result.rows), "tool_rows": 0}
    assert life["export"]["lossy"] is True
    assert tuple(life["export"]["lossy_mappings"]) == LOSSY
    for session in life["sessions"]:
        for turn in session["turns"]:
            assert set(turn) == {"user", "assistant"}
            assert turn["assistant"] == ASSISTANT == "Noted."


def test_tidewater_content_and_counts(golden):
    _, schedule, result, life = golden
    assert len(result.rows) == 92
    assert Counter(r["kind"] for r in result.rows) == {
        "filler": 51, "sprint_log": 32, "statement": 8, "notice": 1}
    users = []
    for plan, session in zip(schedule.sessions, life["sessions"], strict=True):
        counts = []
        for n, turn in enumerate(session["turns"], 1):
            rows = [r for r in result.rows if r["turn_key"] == f"{plan.session_id}/t{n}"]
            assert turn["user"] == JOIN.join(r["text"] for r in rows)
            counts.append(len(rows))
            users.append(turn["user"].strip())
        if plan.index == 6:
            assert counts == [4, 4] + [3] * 13
    assert len(users) == len(set(users)) == 60
    assert all(users)
    locations = {"6432": [(1, 2), (5, 1)], "6543": [(5, 1)], "release/ember": [(1, 3)],
                 "Python 3.12": [(2, 1)], "JSON lines": [(2, 2)], "defaults to off": [(2, 3)],
                 "under 50 characters": [(3, 1)]}
    for token, expected in locations.items():
        assert [(s["index"], n) for s in life["sessions"] for n, t in enumerate(s["turns"], 1)
                if token in t["user"]] == expected


def test_no_ids_or_turn_canary(golden):
    db, schedule, result, life = golden
    ids = [r[0] for table, column in (("entity", "id"), ("event", "id"), ("fact", "id"),
                                    ("locked_token", "token_id"))
           for r in db.execute(f"SELECT {column} FROM {table}")]
    ids += [p.session_id for p in schedule.sessions]
    ids += [r["call_id"] for r in result.rows if r["call_id"] is not None]
    ids += [r["event_id"] for r in result.rows]
    assert scan_script(life, ids, []) == []
    assert _canary() not in canon(life["sessions"]).decode()


def test_export_is_read_only_and_does_not_commit(small):
    db, schedule, result = small
    before = world_hash(db), db.total_changes, db.in_transaction, canon(result.rows), canon(result.sessions)
    assert db.in_transaction

    def readonly(action, *args):
        return sqlite3.SQLITE_OK if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ) else sqlite3.SQLITE_DENY

    db.set_authorizer(readonly)
    try:
        export_s6a(db, result, schedule)
    finally:
        db.set_authorizer(None)
    assert before == (world_hash(db), db.total_changes, db.in_transaction,
                      canon(result.rows), canon(result.sessions))


def test_tool_flattening(tmp_path):
    db, schedule, result = build_world(tmp_path / "tool.db", tool=True)
    try:
        life = export_s6a(db, result, schedule)
        rows = [r for r in result.rows if r["turn_key"] == f"{schedule.sessions[2].session_id}/t2"]
        payload = db.execute("SELECT payload_json FROM event WHERE id = 'tool-event'").fetchone()[0]
        assert payload == ('{"result":{"stdout":"output TOK-4410 end"},'
                           '"tool":{"args":{"path":"log.txt"},"name":"repo.read"}}')
        assert life["sessions"][2]["turns"][1]["user"] == rows[0]["text"] + JOIN + payload
        assert life["export"]["tool_rows"] == 1
        assert scan_script(life, [rows[1]["call_id"]], []) == []
    finally:
        db.close()


@pytest.mark.parametrize("wake", ["kill", "gap", "swap", "restart", "compaction"])
def test_wakes(tmp_path, wake):
    db, schedule, result = build_world(tmp_path / "wake.db", wake=wake)
    try:
        if wake in ("kill", "gap"):
            session = export_s6a(db, result, schedule)["sessions"][2]
            key, value = ("restart_after_turn", 1) if wake == "kill" else ("gap_before", True)
            assert session[key] == value
        else:
            with pytest.raises(ValueError):
                export_s6a(db, result, schedule)
    finally:
        db.close()


@pytest.mark.parametrize("field", ["world_hash", "schedule_sha256", "life"])
def test_identity_refusals(small, field):
    db, schedule, result = small
    with pytest.raises(ValueError, match={"world_hash": "world hash", "schedule_sha256": "schedule hash",
                                        "life": "life mismatch"}[field]):
        export_s6a(db, replace(result, **{field: "wrong"}), schedule)


@pytest.mark.parametrize("field", ["missing", "indices", "long_sprint", "wake_before", "fault_points"])
def test_session_refusals(small, field):
    db, schedule, result = small
    sessions = [dict(s) for s in result.sessions]
    if field == "missing":
        sessions.pop()
    else:
        key, value = {"indices": ("index", 99), "long_sprint": ("long_sprint", True),
                      "wake_before": ("wake_before", ["gap"]),
                      "fault_points": ("fault_points", [{"kind": "kill", "session": 1, "turn": 1}])}[field]
        sessions[0][key] = value
    with pytest.raises(ValueError, match="session"):
        export_s6a(db, replace(result, sessions=tuple(sessions)), schedule)


@pytest.mark.parametrize("bad", ["hash", "unknown-session", "plan-order", "seq", "t0", "past-last",
                                 "noncanonical-key", "decreasing", "reversed", "empty-turn",
                                 "whitespace", "duplicate", "duplicate-across-sessions"])
def test_row_and_user_refusals(small, bad):
    db, schedule, result = small
    rows = [dict(r) for r in result.rows]
    error = {"hash": "row hash", "unknown-session": "unknown session", "plan-order": "plan order",
             "seq": "seq", "t0": "turn key", "past-last": "turn key", "noncanonical-key": "turn key",
             "decreasing": "decreasing", "reversed": "seq", "empty-turn": "empty turn",
             "whitespace": "user text", "duplicate": "user text", "duplicate-across-sessions": "user text"}[bad]
    if bad == "hash":
        rows[0]["sha256"] = "0" * 64
    elif bad == "plan-order":
        rows = rows[5:10] + rows[:5] + rows[10:]
    elif bad == "reversed":
        rows.reverse()
    elif bad == "empty-turn":
        rows.pop(0)
        for n, row in enumerate(rows[:4], 1):
            rows[n - 1] = seal(row | {"seq": n})
    else:
        if bad == "unknown-session":
            rows[0]["session_id"] = "unknown"
        elif bad == "seq":
            rows[0]["seq"] = 2
        elif bad in ("t0", "past-last", "noncanonical-key"):
            suffix = {"t0": "0", "past-last": "6", "noncanonical-key": "01"}[bad]
            rows[0]["turn_key"] = f"{schedule.sessions[0].session_id}/t{suffix}"
        elif bad == "decreasing":
            rows[0]["turn_key"], rows[1]["turn_key"] = rows[1]["turn_key"], rows[0]["turn_key"]
        elif bad == "whitespace":
            rows[0]["text"] = " \t\n "
        else:
            target = 1 if bad == "duplicate" else 5
            rows[target]["text"] = " \n" + rows[0]["text"] + "\t "
        rows = [seal(row) for row in rows]
    with pytest.raises(ValueError, match=error):
        export_s6a(db, replace(result, rows=tuple(rows)), schedule)


def change_plan(result, schedule, **updates):
    plan = replace(schedule.sessions[0], **updates)
    schedule = replace(schedule, sessions=(plan, *schedule.sessions[1:]))
    session = dict(result.sessions[0], long_sprint=plan.long_sprint, wake_before=list(plan.wake_before),
                   fault_points=[dict(f) for f in plan.fault_points])
    return replace(result, sessions=(session, *result.sessions[1:]),
                   schedule_sha256=sha256(schedule.to_json()).hexdigest()), schedule


@pytest.mark.parametrize("kind", ["swap", "restart", "compaction", "unknown"])
def test_unsupported_fault_refusal(small, kind):
    db, schedule, result = small
    result, schedule = change_plan(result, schedule, fault_points=({"kind": kind, "session": 1, "turn": 1},))
    with pytest.raises(ValueError, match="unsupported fault"):
        export_s6a(db, result, schedule)


def test_multiple_kills_refusal(small):
    db, schedule, result = small
    result, schedule = change_plan(result, schedule, fault_points=tuple(
        {"kind": "kill", "session": 1, "turn": n} for n in (1, 2)))
    with pytest.raises(ValueError, match="multiple kills"):
        export_s6a(db, result, schedule)


@pytest.mark.parametrize("turn", [0, -1, 5, 6, True, "1", None])
def test_invalid_kill_turn_refusal(small, turn):
    db, schedule, result = small
    result, schedule = change_plan(result, schedule, fault_points=({"kind": "kill", "session": 1, "turn": turn},))
    with pytest.raises(ValueError, match="kill must precede"):
        export_s6a(db, result, schedule)


@pytest.mark.parametrize("wake", ["swap", "restart", "compaction", "kill", "unknown"])
def test_non_gap_wake_refusal(small, wake):
    db, schedule, result = small
    result, schedule = change_plan(result, schedule, wake_before=(wake,))
    with pytest.raises(ValueError, match="unsupported wake"):
        export_s6a(db, result, schedule)


def test_preserves_cut_order_even_at_equal_times(small):
    db, schedule, result = small
    first = result.rows[0]
    extra = seal(first | {"event_id": "aaa-extra", "text": "  Unchanged tail.  ", "seq": 2})
    rows = [dict(first), extra]
    for row in result.rows[1:]:
        rows.append(seal(row | {"seq": row["seq"] + 1}) if row["session_id"] == first["session_id"] else row)
    life = export_s6a(db, replace(result, rows=tuple(rows)), schedule)
    assert life["sessions"][0]["turns"][0]["user"] == first["text"] + JOIN + extra["text"]


GUARD = """
import socket
real_connect = socket.socket.connect
def connect(sock, address):
    if address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise OSError('non-loopback connection refused')
    return real_connect(sock, address)
socket.socket.connect = connect
"""

WALK = """
import json
from pathlib import Path
from types import SimpleNamespace
import director
from test_s6a import MEM
root = Path.cwd()
d = director.Director(SimpleNamespace(
    life=str(root / 'micro_life.json'), ledger_dir=str(root / 'ledger'),
    budget_file=str(root / 'b.json'), budget_cap=0, run='g10', model='none',
    mode='stub', write_turns=False, measure_overhead=False, chars_per_token=4.0,
    context_length=64000, aliases='m', timeout=1, lane_rewrite=''))
life = json.loads((root / 'micro_life.json').read_bytes())
for session in life['sessions']:
    for n, turn in enumerate(session['turns'], 1):
        code, response, rec = d.handle('/main/v1/chat/completions', {
            'model': 'bicentennial-main', 'tools': [MEM], 'messages': [
                {'role': 'system', 'content': 's'}, {'role': 'user', 'content': turn['user']}]})
        assert code == 200, rec
        assert rec['role'] == 'replay_main', rec
        assert rec['served'] == 'script', rec
        assert rec['cursor'] == {'session': session['index'], 'turn': n}, rec
        assert rec['upstream'] == [], rec
        assert response['choices'][0]['message']['content'] == 'Noted.', response
assert d.cursor == 60, d.cursor
print('60 scripted turns; 0 upstream calls')
"""


def clean_env(**updates):
    return {k: v for k, v in os.environ.items() if not k.startswith(("BICENTENNIAL_", "S6A_"))} | {
        "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"} | updates


def spike_copy(tmp_path, data):
    here = tmp_path / "spikes/s6a"
    here.mkdir(parents=True)
    (here.parent / "s1").mkdir()
    for name in ("director.py", "replay.py", "ramp.py", "verify.py", "test_s6a.py"):
        shutil.copyfile(ROOT / "spikes/s6a" / name, here / name)
    shutil.copyfile(ROOT / "spikes/s1/roles.py", here.parent / "s1/roles.py")
    (here / "micro_life.json").write_bytes(data)
    return here


@pytest.mark.parametrize("source", ["original", "export"])
def test_spike_suite(golden, tmp_path, source):
    data = ((ROOT / "spikes/s6a/micro_life.json").read_bytes() if source == "original"
            else export_bytes(golden[3]))
    here = spike_copy(tmp_path, data)
    command = GUARD + '\nimport unittest\nunittest.main(module="test_s6a", argv=["x", "-v"])\n'
    proc = subprocess.run([sys.executable, "-c", command], cwd=here, env=clean_env(),
                          capture_output=True, text=True, timeout=60)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert "Ran 9 tests" in output and "\nOK\n" in output


def test_director_walk(golden, tmp_path):
    here = spike_copy(tmp_path, export_bytes(golden[3]))
    proc = subprocess.run([sys.executable, "-c", GUARD + WALK], cwd=here, env=clean_env(),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "60 scripted turns; 0 upstream calls" in proc.stdout


def test_k13_script(golden):
    compile_micro_life = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
    script = compile_micro_life(golden[3])
    validate("script", script)
    assert len(script["sessions"]) == 10


def test_determinism_across_builds_and_hash_seeds(golden, tmp_path):
    expected = export_bytes(golden[3])
    assert sha256(expected).hexdigest() == GOLDEN_SHA256
    for name in ("build-a", "build-b"):
        workdir = tmp_path / name
        workdir.mkdir()
        assert export_bytes(export_golden(GOLDEN_PATH, workdir)) == expected
    code = """
import runpy
import sys
import tempfile
from pathlib import Path
ns = runpy.run_path('tests/render/test_export_s6a.py')
with tempfile.TemporaryDirectory() as workdir:
    life = ns['export_golden'](Path('tests/fixtures/g1_golden_tidewater.toml'), workdir)
    sys.stdout.buffer.write(ns['export_bytes'](life))
"""
    for seed in ("0", "random"):
        proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                              env=clean_env(PYTHONHASHSEED=seed), capture_output=True, timeout=60)
        assert proc.returncode == 0, proc.stderr.decode()
        assert proc.stdout == expected


def test_write_exclusive_and_canonical(golden, tmp_path):
    life = golden[3]
    expected = export_bytes(life)
    assert expected == canon(life) + b"\n"
    path = tmp_path / "life.json"
    assert write_s6a(path, life) is None
    assert path.read_bytes() == expected
    with pytest.raises(FileExistsError):
        write_s6a(str(path), {"different": True})
    assert path.read_bytes() == expected


def test_no_forbidden_imports():
    tree = ast.parse((ROOT / "src/bicentennial/render/export_s6a.py").read_text())
    banned = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess",
              "bicentennial.sandbox", "bicentennial.director", "bicentennial.genres", "spikes")
    modules = [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    modules += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    assert not [name for name in modules if any(name == b or name.startswith(b + ".") for b in banned)]
