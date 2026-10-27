"""G09 dispatch acceptance, using synthetic worlds and keyed property cases only."""

import ast
import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.keyed import mint_id, uniform_int
from bicentennial.render import channel_stamp, load
from bicentennial.render import session_cut as cutter
from bicentennial.render.session_cut import _chunk, cut
from bicentennial.render.stream import (
    content,
    event_sha256,
    history_set_hash,
    lint,
    render_key,
    seal,
    sessions_bytes,
    sessions_hash,
    stream_bytes,
    stream_hash,
    verify_branch,
    write_branch,
)
from bicentennial.runner.lock import build_lock
from bicentennial.world import create_world, open_world, unit, world_hash
from bicentennial.world import db as writers
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions
from bicentennial.world.tokens import ESTIMATOR, estimate_tokens, sprint_floor

ROOT = Path(__file__).resolve().parents[2]
CANARY = json.loads((SCHEMAS / "stream.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
TOKEN = "TOK-4410"
GOLDEN = "62b91fb384e90e92513585955aa2b0e7a1cffd974c221bf07d283ee2b07a2200"


def fact(db, fid, token):
    writers.insert_fact(db, id=fid, subject_id="principal", predicate="deploy_code", object=token,
                        polarity="affirm", modality="stated", strength=1000, speech_act="assert")
    writers.insert_locked_token(db, token_id=f"{fid}-token", fact_id=fid, kind="code", value=token)


def event(db, eid, t, *, kind="turn", channel="chat", payload=None):
    writers.insert_event(db, id=eid, t_sim=t, kind=kind, channel=channel, actor_id="principal",
                         audience_json=["agent"], visibility="shared", salience=500,
                         payload_json={} if payload is None else payload)


def build(path, seed="g09-t1", scale="t1", token=TOKEN, result=None, omit=None,
          schedule=None, tool_payload=None, tool_kind="tool", tool_channel="tool_result"):
    schedule = schedule or build_schedule(seed, "life-a", named(scale))
    db = create_world(path, dict(generator_version="g09", genre="software-partner",
                                 seed=schedule.seed, scale=schedule.scale.sessions))
    writers.insert_entity(db, id="principal", kind="person", canonical_name="Rin Okafor",
                          aliases_json=[], created_t=0, retired_t=None)
    write_sessions(db, schedule)
    for plan in schedule.sessions:
        for n, t in enumerate(plan.turn_t, 1):
            eid = f"chat-{plan.index:03d}-{n:02d}"
            if (plan.index, n) != omit:
                event(db, eid, t + 60)
    fact(db, "fact-a", token)
    writers.insert_link(db, event_id="chat-001-01", fact_id="fact-a", role="assert")
    if len(schedule.sessions) >= 3:
        plan = schedule.sessions[2]
        payload = {"tool": {"name": "repo.read", "args": {"path": "log.txt"}},
                   "result": {"stdout": f"output {token} end"} if result is None else result}
        event(db, "tool-event", plan.turn_t[1] + 61, kind=tool_kind, channel=tool_channel,
              payload=payload if tool_payload is None else tool_payload)
        writers.insert_link(db, event_id="tool-event", fact_id="fact-a", role="assert")
    db.commit()
    return db, schedule


def states(schedule):
    return {p.index: dict(repo_tree_hash="a" * 64, env_state_hash="b" * 64)
            for p in schedule.sessions}


def cutting(db, schedule, **kwargs):
    return cut(db, schedule, **(dict(branch="B0", principal_id="principal",
                                    expected_state=states(schedule)) | kwargs))


@pytest.fixture
def world(tmp_path):
    db, schedule = build(tmp_path / "world.db")
    yield db, schedule
    db.close()


def chunk_number(row):
    return int(re.search(r"Long debugging sprint, chunk (\d+)\.", row["text"])[1])


def assert_sprints(result, schedule):
    for session, plan in zip(result.sessions, schedule.sessions, strict=True):
        rows = [r for r in result.rows if r["session_id"] == plan.session_id]
        filler = sorted((r for r in rows if r["kind"] == "sprint_log"), key=chunk_number)
        assert bool(filler) == plan.long_sprint == session["long_sprint"]
        assert session["est_tokens"] == estimate_tokens("".join(content(r) for r in rows))
        if filler:
            floor = sprint_floor(schedule.scale.window)
            assert session["est_tokens"] >= floor
            assert estimate_tokens("".join(r["text"] for r in filler)) >= floor
            assert estimate_tokens("".join(r["text"] for r in filler[:-1])) < floor
            for c, row in enumerate(filler):
                assert row["t_sim"] == plan.turn_t[c % len(plan.turn_t)]
                assert row["event_id"] == mint_id(canon([
                    schedule.seed, schedule.life, "sprint", plan.index]).decode(), c)


def test_k12_agreement():
    for name in ("stream", "payload-stream"):
        row = json.loads((SCHEMAS / "fixtures/gen" / f"{name}.json").read_bytes())
        assert event_sha256(row) == row["sha256"]
        assert seal(dict(row)) == row
        if "payload" in row:
            assert sha256_canon(row["payload"]) == row["expected_result_sha256"]


def test_t1(world):
    db, schedule = world
    before = world_hash(db)
    result = cutting(db, schedule)
    assert world_hash(db) == before == result.world_hash
    assert result.schedule_sha256 == sha256(schedule.to_json()).hexdigest()
    assert len(result.sessions) == 20
    assert [r["index"] for r in result.sessions] == list(range(1, 21))
    assert {r["kind"] for r in result.sessions} == {"work"}
    assert sum(r["long_sprint"] for r in result.sessions) == 2
    assert [r["index"] for r in result.sessions if r["probe_point"]] == [10, 20]
    faults = [f for r in result.sessions for f in r["fault_points"]]
    assert faults == schedule.fault_lite() == [dict(kind="kill", session=11, turn=1),
                                               dict(kind="swap", session=15, turn=None)]
    assert_sprints(result, schedule)
    for plan, session in zip(schedule.sessions, result.sessions, strict=True):
        assert session["wake_before"] == list(plan.wake_before)
        assert session["expected_state"] == states(schedule)[plan.index]
        rows = [r for r in result.rows if r["session_id"] == plan.session_id]
        assert [r["seq"] for r in rows] == list(range(1, len(rows) + 1))
        assert {r["turn_key"] for r in rows} == {f"{plan.session_id}/t{n}" for n in range(1, 6)}
        assert [r["t_sim"] for r in rows] == sorted(r["t_sim"] for r in rows)
    for row in result.rows:
        validate("stream", row)
        assert row["sha256"] == event_sha256(row)
    for row in result.sessions:
        validate("session", row)
        assert "sha256" not in row
    assert lint(db, result.rows) == []
    tool = next(r for r in result.rows if r["kind"] == "tool")
    assert tool["render"] == dict(lane="template", template_id=None, voice="sandbox")
    assert tool["call_id"] == mint_id(canon([schedule.seed, schedule.life, "call", "tool-event"]).decode(), 0)


def test_full_scale_offline(tmp_path, monkeypatch, capsys):
    calls = []

    def deny(*args, **kwargs):
        calls.append(True)
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "socket", deny)
    started = perf_counter()
    db, schedule = build(tmp_path / "full.db", seed="g09-full", scale="full")
    result = cutting(db, schedule)
    elapsed = perf_counter() - started
    assert calls == []
    assert len(result.sessions) == 200
    assert sum(r["kind"] != "sprint_log" for r in result.rows) == 1001
    assert sum(r["long_sprint"] for r in result.sessions) == 8
    assert_sprints(result, schedule)
    db.close()
    with capsys.disabled():
        print(f"G09 full unit fixture: rows={len(result.rows)} wall_seconds={elapsed:.6f}; network_calls=0")


def test_tool_output_never_shortened(tmp_path):
    result = {"stdout": "x" * 300_000 + " " + TOKEN}
    db, schedule = build(tmp_path / "large.db", result=result)
    row = next(r for r in cutting(db, schedule).rows if r["kind"] == "tool")
    assert canon(row["payload"]) == canon(result)
    assert content(row) == result["stdout"] and len(content(row)) == 300_009
    assert row["expected_result_sha256"] == sha256_canon(result)
    db.close()


@pytest.mark.parametrize("case", ["unlinked", "canary"])
def test_lint_refuses_payload(tmp_path, monkeypatch, case):
    token = "OTHER-6632" if case == "unlinked" else CANARY
    db, schedule = build(tmp_path / "bad.db", result={"stdout": f"{TOKEN} {token}"})
    if case == "unlinked":
        fact(db, "fact-other", token)
    with pytest.raises(ValueError) as error:
        cutting(db, schedule)
    assert token not in str(error.value)
    if case == "canary":
        assert "canary" in str(error.value)
    monkeypatch.setattr(cutter, "lint", lambda db, rows: [])
    rows = cutting(db, schedule).rows
    assert lint(db, rows) == [("tool-event", "fact-other-token" if case == "unlinked" else "canary")]
    db.close()


def test_tool_missing_linked_token(tmp_path):
    db, schedule = build(tmp_path / "missing.db", result={"stdout": "nothing"})
    with pytest.raises(ValueError, match="missing linked token: tool-event"):
        cutting(db, schedule)
    db.close()


@pytest.mark.parametrize("result", [{"stdout": ["TOK-", "4410"]}, {"TOK-": "4410"}])
def test_tool_split_linked_token(tmp_path, result):
    db, schedule = build(tmp_path / "split.db", result=result)
    with pytest.raises(ValueError, match="missing linked token: tool-event"):
        cutting(db, schedule)
    db.close()


@pytest.mark.parametrize("tool", [{"name": "repo.read", "args": {"path": TOKEN}},
                                  {"name": "repo.read", "args": {TOKEN: "log.txt"}},
                                  {"name": TOKEN, "args": {"path": "log.txt"}}])
def test_tool_linked_token_only_in_call(tmp_path, tool):
    db, schedule = build(tmp_path / "args.db", tool_payload={"tool": tool, "result": {"stdout": "nothing"}})
    with pytest.raises(ValueError, match="missing linked token: tool-event"):
        cutting(db, schedule)
    db.close()


def test_lint_split_token_is_absent(world):
    db, schedule = world
    row = next(r for r in cutting(db, schedule).rows if r["kind"] == "tool")
    fact(db, "fact-other", "OTHER-6632")
    half = len(CANARY) // 2
    for payload in ({"out": ["OTHER-", "6632"]}, {"OTHER-": "6632"}, {"c": [CANARY[:half], CANARY[half:]]}):
        assert lint(db, [row | {"payload": payload}]) == []
    assert lint(db, [row | {"tool": {"name": "OTHER-", "args": {"x": "6632"}}}]) == []
    assert lint(db, [row | {"payload": {"out": ["x OTHER-6632 y"]}}]) == [("tool-event", "fact-other-token")]


def test_lint_nested_keys_nfc_and_roles(world):
    db, schedule = world
    row = next(r for r in cutting(db, schedule).rows if r["kind"] == "tool")
    fact(db, "fact-other", "caf\u00e9")
    altered = row | {"payload": {"nested": [{"cafe\u0301": "ordinary"}]}}
    assert lint(db, [altered, altered]) == [("tool-event", "fact-other-token")]
    assert lint(db, [row | {"tool": {"name": "read", "args": {"x": "cafe\u0301"}}}]) == [
        ("tool-event", "fact-other-token")]
    writers.insert_link(db, event_id="tool-event", fact_id="fact-other", role="mention")
    assert lint(db, [altered]) == []
    assert content({"payload": {"z": ["last", {"b": "two", "a": "one"}], "a": 42}}) == "lastonetwo"


def golden_schedule():
    return build_schedule("g09-golden", "life-a", named("t1"))


def test_filler_golden():
    schedule = golden_schedule()
    plan = schedule.sessions[1]
    text = _chunk(schedule, plan, 0, 0)
    header = (channel_stamp(plan.turn_t[0], schedule.tz, "chat") + " "
              "Long debugging sprint, chunk 1. Here is the next log excerpt from the soak run:\n")
    assert text.startswith(header) and text.endswith("\nWhat stands out?")
    lines = text.removeprefix(header).removesuffix("\nWhat stands out?").splitlines()
    assert len(lines) == 20
    services = set()
    for i, line in enumerate(lines):
        row = json.loads(line)
        assert set(row) == {"ts", "level", "svc", "msg", "batch", "segment", "retry"}
        assert i * 7 <= int(row["ts"][2:-1]) <= i * 7 + 6
        assert row["level"] in cutter.LEVELS and row["msg"] in cutter.MESSAGES
        assert row["svc"] in cutter.SERVICES
        services.add(row["svc"])
        assert 1000 <= row["batch"] <= 9999 and 100 <= int(row["segment"][4:]) <= 999
        assert 0 <= row["retry"] <= 4
    assert len(services) == 1
    assert sha256(text.encode()).hexdigest() == GOLDEN


def test_filler_retry_and_shared_exclusions(tmp_path):
    schedule = golden_schedule()
    plan = replace(schedule.sessions[1], long_sprint=True, kind="sprint")
    schedule = replace(schedule, sessions=(schedule.sessions[0], plan, *schedule.sessions[2:]))
    first, second = (_chunk(schedule, plan, 0, a) for a in (0, 1))
    # A varying four-digit batch substring, never a timestamp or vocabulary token.
    token = next(t for t in re.findall(r'"batch":(\d+)', first) if t not in second)
    outputs = []
    for i, flipped in enumerate(("TOK-4410", "TOK-5510")):
        db, built = build(tmp_path / f"retry-{i}.db", token=flipped, schedule=schedule)
        fact(db, "fact-retry", token if i == 0 else "OTHER-7733")
        result = cutting(db, built, exclude_tokens=frozenset([token, "OTHER-7733", "TOK-4410", "TOK-5510"]))
        filler = [r for r in result.rows if r["kind"] == "sprint_log"]
        target = next(r for r in filler if r["session_id"] == plan.session_id and chunk_number(r) == 1)
        assert target["text"] == second
        assert lint(db, result.rows) == []
        outputs.append(filler)
        db.close()
    assert outputs[0] == outputs[1]


def test_filler_retry_bound(world, monkeypatch):
    db, schedule = world
    attempts = []

    def contaminated(schedule, plan, c, a):
        attempts.append(a)
        return TOKEN

    monkeypatch.setattr(cutter, "_chunk", contaminated)
    with pytest.raises(ValueError, match="filler retries exhausted"):
        cutting(db, schedule)
    assert attempts == list(range(8))


def test_turn_boundaries_and_keyed_property(world):
    db, schedule = world
    plan = schedule.sessions[0]
    offsets = [719, 720, 3599] + [uniform_int("g09-turns", unit("life-a", "property", str(i)),
                                             0, "offset", 0, 3599) for i in range(200)]
    for i, offset in enumerate(offsets):
        event(db, f"boundary-{i}", plan.t_start + offset)
    rows = {r["event_id"]: r for r in cutting(db, schedule).rows}
    for i, offset in enumerate(offsets):
        assert rows[f"boundary-{i}"]["turn_key"] == f"{plan.session_id}/t{offset // 720 + 1}"


def test_gap_event_refused(world):
    db, schedule = world
    event(db, "gap-event", schedule.sessions[0].t_end)
    with pytest.raises(ValueError, match="event outside sessions: gap-event"):
        cutting(db, schedule)


def test_fifteen_turn_bridge(tmp_path):
    schedule = build_schedule("g09-bridge", "life-a", named("t0-micro", sessions=1))
    plan = schedule.sessions[0]
    plan = replace(plan, turn_t=tuple(plan.t_start + n * 240 for n in range(15)))
    schedule = replace(schedule, sessions=(plan,))
    db, schedule = build(tmp_path / "bridge.db", schedule=schedule)
    result = cutting(db, schedule)
    assert {r["turn_key"] for r in result.rows} == {f"{plan.session_id}/t{n}" for n in range(1, 16)}
    db.close()


@pytest.mark.parametrize("turns", [(), (0,), (1700000000, 1700000000),
                                  (1700000001, 1700000000), (1700000000, 1700003600)])
def test_invalid_turn_slots(world, turns):
    db, schedule = world
    schedule = replace(schedule, sessions=(replace(schedule.sessions[0], turn_t=turns), *schedule.sessions[1:]))
    with pytest.raises(ValueError, match="invalid turn slots"):
        cutting(db, schedule)


def test_branch_refusal(world):
    with pytest.raises(ValueError):
        cutting(*world, branch="B2")


@pytest.mark.parametrize("field,value", [("seed", "different"), ("scale", named("full"))])
def test_meta_refusal(world, field, value):
    db, schedule = world
    with pytest.raises(ValueError, match="world identity"):
        cutting(db, replace(schedule, **{field: value}))


def test_session_mismatch(world):
    db, schedule = world
    plan = replace(schedule.sessions[0], kind="different")
    with pytest.raises(ValueError, match="world sessions differ"):
        cutting(db, replace(schedule, sessions=(plan, *schedule.sessions[1:])))


def test_unknown_principal(world):
    with pytest.raises(ValueError, match="unknown principal"):
        cutting(*world, principal_id="missing")


def test_missing_expected_state(world):
    db, schedule = world
    expected = states(schedule)
    del expected[1]
    with pytest.raises(ValueError, match="expected state indices"):
        cutting(db, schedule, expected_state=expected)


def test_invalid_expected_state(world):
    db, schedule = world
    expected = states(schedule) | {1: dict(repo_tree_hash="invalid", env_state_hash="b" * 64)}
    with pytest.raises(ValueError):
        cutting(db, schedule, expected_state=expected)


def test_empty_turn(tmp_path):
    db, schedule = build(tmp_path / "empty.db", omit=(1, 2))
    with pytest.raises(ValueError, match="empty turn: session 1"):
        cutting(db, schedule)
    db.close()


@pytest.mark.parametrize("payload", [{"tool": {"name": "read", "args": {}}},
                                    {"tool": {"name": "read", "args": {}}, "result": {}, "extra": 1},
                                    {"tool": {"name": "", "args": {}}, "result": {}},
                                    {"tool": {"name": "read", "args": []}, "result": {}}])
def test_malformed_tool(tmp_path, payload):
    db, schedule = build(tmp_path / "tool.db", tool_payload=payload)
    with pytest.raises(ValueError, match="malformed tool event"):
        cutting(db, schedule)
    db.close()


@pytest.mark.parametrize("kind,channel", [("turn", "tool_result"), ("tool", "chat")])
def test_tool_channel_mismatch(tmp_path, kind, channel):
    db, schedule = build(tmp_path / "channel.db", tool_kind=kind, tool_channel=channel)
    with pytest.raises(ValueError, match="tool kind/channel mismatch"):
        cutting(db, schedule)
    db.close()


def test_twin_stability_and_history_set(tmp_path):
    cuts, manifests = [], []
    for branch, token in (("B0", "TOK-4410"), ("B1", "TOK-5510")):
        db, schedule = build(tmp_path / f"{branch}.db", token=token)
        result = cutting(db, schedule, branch=branch, exclude_tokens=frozenset(["TOK-4410", "TOK-5510"]))
        cuts.append(result)
        manifests.append(write_branch(tmp_path, result))
        db.close()
    a, b = cuts
    assert len(a.rows) == len(b.rows)
    assert [r["event_id"] for r, s in zip(a.rows, b.rows, strict=True) if r != s] == [
        r["event_id"] for r in a.rows if "fact-a" in r["fact_ids"]]
    assert [r for r in a.rows if r["kind"] == "sprint_log"] == [r for r in b.rows if r["kind"] == "sprint_log"]
    assert a.sessions == b.sessions and a.schedule_sha256 == b.schedule_sha256
    h = history_set_hash(manifests)
    assert h == history_set_hash(reversed(manifests))
    baseline = manifests[0] | {"branch": "B1"}
    assert h != history_set_hash([manifests[0], baseline])
    assert a.world_hash != b.world_hash
    lock = json.loads((ROOT / "tests/fixtures/run/contracts.json").read_bytes())["contracts"]["lock"]
    assert build_lock(**(lock | {"rendered_history_set_hash": h}))["rendered_history_set_hash"] == h
    for invalid in ([manifests[0]], manifests + [manifests[0]],
                    [manifests[0], manifests[1] | {"schedule_sha256": "c" * 64}]):
        with pytest.raises(ValueError):
            history_set_hash(invalid)


def test_cache_files_and_bank(world, tmp_path):
    db, schedule = world
    first, second = cutting(db, schedule), cutting(db, schedule)
    assert first.render_key == second.render_key == render_key(first, dict(db.execute("SELECT * FROM meta").fetchone()))
    out1, out2 = tmp_path / "one", tmp_path / "two"
    out1.mkdir()
    out2.mkdir()
    manifest = write_branch(out1, first)
    assert write_branch(out2, second) == manifest
    assert sorted(p.name for p in out1.iterdir()) == ["history.B0.json", "sessions.B0.jsonl", "stream.B0.jsonl"]
    for p in out1.iterdir():
        assert p.read_bytes() == (out2 / p.name).read_bytes()
    assert (out1 / "stream.B0.jsonl").read_bytes() == stream_bytes(first.rows)
    assert (out1 / "sessions.B0.jsonl").read_bytes() == sessions_bytes(first.sessions)
    assert manifest["stream_hash"] == stream_hash(first.rows)
    assert manifest["sessions_hash"] == sessions_hash(first.sessions)
    assert manifest["estimator"] == ESTIMATOR
    assert manifest["session_ids"] == [p.session_id for p in schedule.sessions]
    assert verify_branch(out1, "B0") == manifest
    with pytest.raises(FileExistsError):
        write_branch(out1, second)
    bank_path = tmp_path / "en.toml"
    used_phrase = next(r["text"].split("] ", 1)[1] for r in first.rows
                       if r["kind"] == "turn" and not r["fact_ids"])
    bank_path.write_text((ROOT / "src/bicentennial/render/phrasebank/en.toml").read_text().replace(
        used_phrase, used_phrase + " Understood."))
    changed = cutting(db, schedule, bank=load(bank_path))
    assert changed.render_key != first.render_key and stream_hash(changed.rows) != stream_hash(first.rows)


def test_render_key_covers_exclusions(world, tmp_path):
    db, schedule = world
    meta = dict(db.execute("SELECT * FROM meta").fetchone())
    standalone = cutting(db, schedule)
    shared = cutting(db, schedule, exclude_tokens=frozenset([TOKEN, "caf\u00e9-7733"]))
    again = cutting(db, schedule, exclude_tokens=frozenset(["cafe\u0301-7733", TOKEN]))
    other = cutting(db, schedule, exclude_tokens=frozenset([TOKEN, "OTHER-7733"]))
    assert standalone.exclude_sha256 is None
    assert shared.exclude_sha256 == again.exclude_sha256 == sha256(canon(sorted([TOKEN, "caf\u00e9-7733"]))).hexdigest()
    assert shared.render_key == again.render_key == render_key(shared, meta)
    assert len({standalone.render_key, shared.render_key, other.render_key}) == 3
    for name, result in (("none", standalone), ("shared", shared)):
        out = tmp_path / name
        out.mkdir()
        manifest = write_branch(out, result)
        assert manifest["exclude_sha256"] == result.exclude_sha256
        assert manifest["render_key"] == result.render_key
        assert verify_branch(out, "B0") == manifest


def test_render_key_covers_principal_and_expected_state(world, tmp_path):
    db, schedule = world
    writers.insert_entity(db, id="principal-2", kind="person", canonical_name="Ada Mensah",
                          aliases_json=[], created_t=0, retired_t=None)
    meta = dict(db.execute("SELECT * FROM meta").fetchone())
    expected = states(schedule)
    expected[1] = dict(expected[1], env_state_hash="c" * 64)
    base, again = cutting(db, schedule), cutting(db, schedule, expected_state=states(schedule))
    other_principal = cutting(db, schedule, principal_id="principal-2")
    other_state = cutting(db, schedule, expected_state=expected)
    assert base.render_key == again.render_key == render_key(base, meta)
    assert stream_hash(other_principal.rows) != stream_hash(base.rows)
    assert sessions_hash(other_state.sessions) != sessions_hash(base.sessions)
    assert len({base.render_key, other_principal.render_key, other_state.render_key}) == 3
    assert (base.principal_id, other_principal.principal_id) == ("principal", "principal-2")
    assert base.expected_state_sha256 == sha256_canon([states(schedule)[p.index] for p in schedule.sessions])
    for name, result in (("principal", other_principal), ("state", other_state)):
        out = tmp_path / name
        out.mkdir()
        manifest = write_branch(out, result)
        assert manifest["principal_id"] == result.principal_id
        assert manifest["expected_state_sha256"] == result.expected_state_sha256
        assert manifest["render_key"] == result.render_key
        assert verify_branch(out, "B0") == manifest


@pytest.mark.parametrize("case", ["byte", "manifest", "row-seal", "canonical", "session", "missing"])
def test_cache_tampering(world, tmp_path, case):
    manifest = write_branch(tmp_path, cutting(*world))
    path = tmp_path / "stream.B0.jsonl"
    if case == "byte":
        path.write_bytes(path.read_bytes().replace(b"Rin", b"Sin", 1))
    elif case == "missing":
        path.unlink()
    elif case == "manifest":
        manifest["stream_hash"] = "0" * 64
    else:
        if case == "session":
            path = tmp_path / "sessions.B0.jsonl"
        rows = [json.loads(line) for line in path.read_bytes().splitlines()]
        if case == "row-seal":
            rows[0]["text"] += "changed"
        elif case == "session":
            rows[0]["sha256"] = "0" * 64
        data = stream_bytes(rows) if case != "canonical" else b"".join(json.dumps(r).encode() + b"\n" for r in rows)
        path.write_bytes(data)
        manifest["sessions_hash" if case == "session" else "stream_hash"] = sha256(data).hexdigest()
    (tmp_path / "history.B0.json").write_bytes(canon(manifest))
    with pytest.raises(ValueError):
        verify_branch(tmp_path, "B0")


def test_readonly_connection(tmp_path):
    path = tmp_path / "readonly.db"
    db, schedule = build(path)
    expected = cutting(db, schedule)
    db.close()
    with open_world(path) as readonly:
        assert cutting(readonly, schedule) == expected
        assert world_hash(readonly) == expected.world_hash


def test_render_called_once_and_order(world, monkeypatch):
    db, schedule = world
    seen, original = [], cutter.render_event

    def record(db, eid, **kwargs):
        seen.append(eid)
        return original(db, eid, **kwargs)

    monkeypatch.setattr(cutter, "render_event", record)
    plan = next(p for p in schedule.sessions if p.long_sprint)
    event(db, "same-z", plan.turn_t[0])
    event(db, "same-a", plan.turn_t[0])
    result = cutting(db, schedule)
    assert sorted(seen) == [r[0] for r in db.execute("SELECT id FROM event ORDER BY id")]
    rows = [r for r in result.rows if r["session_id"] == plan.session_id and r["t_sim"] == plan.turn_t[0]]
    assert [r["event_id"] for r in rows[:2]] == ["same-a", "same-z"]
    assert all(r["kind"] == "sprint_log" for r in rows[2:])


def test_determinism_subprocesses(tmp_path):
    code = """
import runpy, sys
from pathlib import Path
helpers = runpy.run_path('tests/render/test_stream.py')
from bicentennial.render.stream import write_branch
out = Path(sys.argv[1])
db, schedule = helpers['build'](out / 'world.db')
write_branch(out, helpers['cutting'](db, schedule))
db.close()
"""
    dirs = [tmp_path / "zero", tmp_path / "randomized"]
    for hashseed, out in zip(("0", "random"), dirs, strict=True):
        out.mkdir()
        subprocess.run([sys.executable, "-c", code, str(out)], cwd=ROOT,
                       env=dict(os.environ, PYTHONHASHSEED=hashseed), check=True,
                       capture_output=True, timeout=60)
    for name in ("stream.B0.jsonl", "sessions.B0.jsonl", "history.B0.json"):
        assert (dirs[0] / name).read_bytes() == (dirs[1] / name).read_bytes()


def test_pure_imports():
    forbidden = {"random", "time", "socket", "ssl", "http", "urllib", "subprocess",
                 "bicentennial.sandbox", "bicentennial.director", "spikes"}
    for filename in ("session_cut.py", "stream.py"):
        tree = ast.parse((ROOT / "src/bicentennial/render" / filename).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
        assert not [name for name in imports if any(name == f or name.startswith(f + ".") for f in forbidden)]
