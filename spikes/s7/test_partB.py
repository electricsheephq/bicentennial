"""Offline acceptance for the implemented S7 Part B building blocks."""

import ast
import base64
import json
import pickle
import runpy
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import partB
import pytest
import readback

from bicentennial.canon import canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.director.responder import Call, Reply
from bicentennial.director.upstream import Upstream
from bicentennial.render.export_s6a import ASSISTANT, export_bytes
from bicentennial.runner.spend import Price, Spend
from bicentennial.systems.hermes_plugin import PluginCell


@pytest.fixture
def generated(tmp_path):
    return partB.golden_life(tmp_path / "generated")


def test_golden_export_and_exclusive_cli(generated, tmp_path, capsys):
    life, _, _ = generated
    helpers = runpy.run_path(str(partB.ROOT / "tests/render/test_export_s6a.py"))
    expected = helpers["export_golden"](partB.GOLDEN_PATH, tmp_path)
    assert export_bytes(life) == export_bytes(expected)
    assert export_bytes(partB.golden_life(tmp_path / "second")[0]) == export_bytes(life)
    target = tmp_path / "life.json"
    assert partB.main(["export", "--out", str(target)]) == 0
    assert capsys.readouterr().out.startswith("sha256 ")
    original = target.read_bytes()
    assert original == export_bytes(expected)
    result = subprocess.run([sys.executable, str(Path(partB.__file__)), "export", "--out", str(target)],
                            capture_output=True)
    assert result.returncode != 0
    assert target.read_bytes() == original


def test_scripts_and_gold(generated, tmp_path):
    life, gold, schedule = generated
    assert gold == {
        "P1/1": {"gold": ["6543"], "stale": ["6432"]},
        "P1/2": {"gold": ["JSON lines"], "stale": []},
        "P2/1": {"gold": ["Python 3.12", "release/ember"], "stale": []},
    }
    script, faults, starts = partB.build_script(life, schedule, probes=True)
    validate("script", script)
    assert [s["kind"] for s in script["sessions"]] == ["replay"] * 10 + ["probe"] * 2
    assert [len(s["turns"]) for s in script["sessions"][:10]] == [5, 5, 5, 5, 5, 15, 5, 5, 5, 5]
    replay = [t for s in script["sessions"][:10] for t in s["turns"]]
    probes = [t for s in script["sessions"][10:] for t in s["turns"]]
    micro = json.loads((partB.ROOT / "spikes/s6a/micro_life.json").read_bytes())
    assert [t["user"] for t in probes] == [t["user"] for s in micro["probes"] for t in s["turns"]]
    assert all(t["assistant"] == ASSISTANT and t["tool_calls"] == [] for t in replay)
    assert all(t["assistant"] is None for t in probes)
    assert faults == [{"kind": "kill", "session": 5, "turn": 2}]
    for item in gold.values():
        for kind, tokens in item.items():
            for token in tokens:
                assert not any(partB.present(token, t["user"]) for t in probes)
                if kind == "gold":
                    assert any(partB.present(token, t["user"]) for t in replay)
    pace, pace_faults, pace_starts = partB.build_script(life, schedule, probes=False)
    assert len(pace["sessions"]) == 10
    assert pace_faults == faults
    assert pace_starts == {p.index: p.t_start for p in schedule.sessions}
    assert starts == pace_starts | {
        11: schedule.sessions[9].t_end + 3600, 12: schedule.sessions[9].t_end + 7200}
    db = partB.create_world(tmp_path / "ids.db", partB.world_meta(schedule.seed, len(schedule.sessions)))
    try:
        partB.build_golden(db, partB.load_golden(partB.GOLDEN_PATH), schedule)
        sealed = [r["id"] for table in ("fact", "event") for r in db.execute(f"SELECT id FROM {table}")]
        assert scan_script(script, sealed, []) == []
    finally:
        db.close()


@pytest.mark.parametrize(("token", "text", "found"), [
    ("6543", "port 6543", True), ("6543", "6,543", False),
    ("JSON lines", "json lines", False), ("café", "cafe\u0301", True),
])
def test_presence(token, text, found):
    assert partB.present(token, text) is found


def test_grade_requires_both_tokens(generated):
    gold = generated[1]
    assert partB.grade("Python 3.12", gold["P2/1"]) == {"answered": False, "stale": False}
    assert partB.grade("Python 3.12 release/ember", gold["P2/1"])["answered"]
    assert partB.grade("6543 formerly 6432", gold["P1/1"]) == {"answered": True, "stale": True}


def test_bridge_mapping_and_determinism():
    body = {
        "model": "alias", "messages": [
            {"role": "system", "content": "s"},
            {"role": "developer", "content": [{"type": "text", "text": "d"}]},
            {"role": "user", "content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]},
            {"role": "assistant", "content": "thinking", "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "memory", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c2", "type": "function", "function": {"name": "memory", "arguments": "{}"}}]},
        ],
        "tools": [{"type": "function", "function": {"name": "memory"}}],
        "tool_choice": {"type": "function", "function": {"name": "memory"}},
        "parallel_tool_calls": False, "reasoning_effort": "low", "max_tokens": 100,
        "max_completion_tokens": 200, "stream": True, "stream_options": {"include_usage": True},
    }
    before = canon(body)
    result = partB.to_responses(body)
    assert result == {
        "instructions": "s\n\nd", "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "ab"}]},
            {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "thinking"}]},
            {"type": "function_call", "call_id": "c1", "name": "memory", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "c1", "output": "done"},
            {"type": "function_call", "call_id": "c2", "name": "memory", "arguments": "{}"},
        ],
        "tools": [{"type": "function", "name": "memory", "description": "", "parameters": {}}],
        "tool_choice": {"type": "function", "name": "memory"}, "parallel_tool_calls": False,
        "reasoning": {"effort": "medium"}, "store": False,
    }
    assert canon(result) == canon(partB.to_responses(body))
    assert canon(body) == before
    assert partB.to_responses({"messages": []}) == {
        "instructions": "", "input": [], "reasoning": {"effort": "medium"}, "store": False}
    assert partB.to_responses({"tool_choice": "auto"})["tool_choice"] == "auto"
    detailed = {"type": "function", "function": {"name": "f", "description": "D", "parameters": {"type": "object"}}}
    assert partB.to_responses({"tools": [detailed]})["tools"][0] == {
        "type": "function", "name": "f", "description": "D", "parameters": {"type": "object"}}


def test_bridge_refuses_unknown_keys_and_images():
    with pytest.raises(ValueError, match="^bridge_unmapped_key:logprobs$"):
        partB.to_responses({"logprobs": True})
    with pytest.raises(ValueError, match="bridge_unsupported_content"):
        partB.to_responses({"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {}}]}]})


class Recorder:
    def __init__(self):
        self.calls = []

    def respond(self, call):
        self.calls.append(call)
        return Reply(200, "live", "live", call.model,
                     usage={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13})

    def state(self):
        return {"identity_drift": None}

    def served_identities(self):
        return {"model": "identity"}


def test_bridge_and_usage():
    inner = Recorder()
    bridge = partB.ResponsesBridge(inner)
    call = Call("write_turn", "write_turn", "chat", {"messages": []}, "model", None, "run")
    reply = bridge.respond(call)
    expected = {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    assert reply.usage == expected
    assert inner.calls == [replace(call, wire="responses", body=partB.to_responses(call.body))]
    direct = replace(call, wire="responses")
    assert bridge.respond(direct).usage == {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
    assert inner.calls[-1] is direct
    assert partB.chat_usage({"input_tokens": 10, "output_tokens": 3, "total_tokens": 99}) == expected
    assert partB.chat_usage({"input_tokens": 10}) is None
    assert partB.chat_usage({"input_tokens": True, "output_tokens": 3}) is None
    assert bridge.state() == inner.state()
    assert bridge.served_identities() == inner.served_identities()


@pytest.mark.parametrize(("role", "subrole", "live"), [
    ("write_turn", "write_turn", True), ("probe_main", "cursor", True),
    ("probe_main", "tool_results", True), ("memory_write", "background_review", True),
    ("summariser", "compression", True), ("aux", "summariser", True),
    ("aux", "title_generation", False), ("aux", "extraction", False), ("embeddings", "embedding", False),
])
def test_routing(role, subrole, live):
    responders = [Recorder(), Recorder()]
    routed = partB.Routed(*responders)
    call = Call(role, subrole, "chat", {}, "model", None, "run")
    routed.respond(call)
    assert responders[0].calls == ([call] if live else [])
    assert responders[1].calls == ([] if live else [call])
    assert routed.state() == responders[0].state()
    assert routed.served_identities() == responders[0].served_identities()


def test_zero_price_and_send_policy(tmp_path):
    responder, holds = partB.make_live(tmp_path / "spend.json", auth=lambda: {},
                                     base_url="http://127.0.0.1:1", max_output_tokens=1000)
    live = responder.inner
    upstream = live.upstreams[partB.MODEL]
    assert upstream.send_cap is False
    assert upstream.effort == "medium"
    assert live.max_sends == 400
    assert live.holds is holds
    assert upstream.spend.policy == {"cap": 0, "price": {"input_per_million": 0, "output_per_million": 0}}
    spend = Spend(tmp_path / "refusal.json", 0, Price(0, 0))
    with pytest.raises(ValueError, match="invalid upstream or spend policy"):
        Upstream("sol", "model", "http://127.0.0.1:1", "responses", spend, Price(0, 1), 1000)


def test_firewall():
    tree = ast.parse(Path(partB.__file__).read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    assert not any("lcm" in name for name in names)
    assert not any(name.split(".")[0] in {"urllib", "socket", "http"} for name in names)
    assert set(partB.SYSTEMS.values()) == {"hermes-native", "mem0-oss"}
    assert partB.load_entry("hermes-native")["name"] == "hermes-native"
    assert partB.load_entry("mem0-oss")["name"] == "mem0-oss"
    with pytest.raises(ValueError):
        partB.load_entry("lcm-x")
    assert partB.SUFFIX == readback.SUFFIX


def export_cell(root, port):
    surface = root / "store"
    surface.mkdir(parents=True)
    declaration = {"root": "HERMES_HOME", "relative": ".", "volatile_paths": ["logs"]}
    adapter = SimpleNamespace(
        paths={"root": root, "hermes_home": surface, "home": root / "home",
               "workspace": root / "workspace", "tmp": root / "tmp"},
        director=SimpleNamespace(run_values={"sandbox_root": str(root), "director_port": str(port)}),
        _worker=SimpleNamespace(proc=SimpleNamespace(poll=lambda: None)),
    )
    return PluginCell(dict(partB.load_entry("mem0-oss"), surfaces=[declaration]), adapter)


def populate_store(cell, uuid, port, created, *, text="kept"):
    root = cell.adapter.paths["root"]
    surface = cell.surfaces[0][1]
    connection = sqlite3.connect(surface / "facts.db")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE facts(id, text, created_at, weight, data BLOB)")
    connection.executemany("INSERT INTO facts VALUES (?, ?, ?, ?, ?)", [
        (uuid, f"{text} {root} http://127.0.0.1:{port}", created, 1.5, b"blob"),
        (uuid, "second 2026-10-27T01:02:03Z", created, 2.5, b"other"),
    ])
    connection.execute("CREATE TABLE timestamps(created_at)")
    connection.executemany("INSERT INTO timestamps VALUES (?)", [(created,), (created,)])
    connection.commit()
    (surface / "config.json").write_bytes(canon({"root": str(root), "url": f"http://127.0.0.1:{port}", "id": uuid}))
    (surface / ".bicentennial-sandbox").write_text("excluded")
    (surface / "logs").mkdir()
    (surface / "logs/volatile").write_text(created)
    return connection


def test_before_export_reads_live_wal_without_checkpoint_and_after_refuses(tmp_path):
    cell = export_cell(tmp_path / "arm", 32189)
    writer = populate_store(cell, "12345678-1234-1234-1234-123456789abc", 32189, "2026-10-27T01:02:03Z")
    database = cell.surfaces[0][1] / "facts.db"
    wal = database.with_name("facts.db-wal")
    original_db, original_wal = database.read_bytes(), wal.read_bytes()
    assert original_wal
    calls = []
    checkpoint = cell.checkpoint
    cell.checkpoint = lambda: calls.append(True)
    try:
        result = partB.before_store_export(cell, tmp_path / "before")
        assert calls == []
        assert cell.adapter._worker.proc.poll() is None
        assert result["files"]["HERMES_HOME/./facts.db"]["tables"]["facts"][0] == 2
        assert result["files"]["HERMES_HOME/./facts.db"]["tables"]["timestamps"][0] == 2
        assert result["live_copy"] == ["HERMES_HOME/./config.json"]
        assert json.loads((tmp_path / "before/manifest.json").read_bytes()) == json.loads(canon(result))
        assert (tmp_path / "before/0/config.json").read_bytes() == (database.parent / "config.json").read_bytes()
        assert database.read_bytes() == original_db
        assert wal.read_bytes() == original_wal
        cell.checkpoint = checkpoint
        with pytest.raises(ValueError, match="worker must exit"):
            partB.store_export(cell)
        with pytest.raises(ValueError, match="worker must exit"):
            cell.checkpoint()
        cell.adapter._worker.proc.poll = lambda: 0
        after = partB.store_export(cell)
        assert after["files"] == result["files"]
        assert after["live_copy"] == []
    finally:
        writer.close()


def test_store_normalization_and_changed_value(tmp_path):
    cells = [export_cell(tmp_path / arm, port) for arm, port in (("P1", 32189), ("U1", 42189))]
    connections = [populate_store(cell, uuid, port, created) for cell, uuid, port, created in [
        (cells[0], "12345678-1234-1234-1234-123456789abc", 32189, "2026-10-27T01:02:03Z"),
        (cells[1], "87654321-4321-4321-4321-cba987654321", 42189, "2025-01-01T03:04:05+0900"),
    ]]
    try:
        first = partB.before_store_export(cells[0], tmp_path / "before-P1")
        second = partB.before_store_export(cells[1], tmp_path / "before-U1")
        assert first == second
        assert set(first["files"]) == {"HERMES_HOME/./config.json", "HERMES_HOME/./facts.db"}
        assert first["files"]["HERMES_HOME/./facts.db"]["tables"]["timestamps"][0] == 2
        connections[1].execute("UPDATE facts SET text = 'changed' WHERE weight = 1.5")
        connections[1].commit()
        changed = partB.before_store_export(cells[1], tmp_path / "changed")
        original_tables = first["files"]["HERMES_HOME/./facts.db"]["tables"]
        changed_tables = changed["files"]["HERMES_HOME/./facts.db"]["tables"]
        assert original_tables["facts"][0] == changed_tables["facts"][0] == 2
        assert original_tables["facts"][1] != changed_tables["facts"][1]
        assert original_tables["timestamps"] == changed_tables["timestamps"]
        with pytest.raises(ValueError, match="overlaps"):
            partB.before_store_export(cells[0], cells[0].surfaces[0][1] / "inside")
    finally:
        for connection in connections:
            connection.close()


def test_waits_pacing_and_digest():
    rows = [{"role": "replay_main", "subrole": "cursor", "cursor": {"session": 1, "turn": 1},
             "t_ms": 3000, "upstream": [{"role": "write_turn", "diagnostics": [
                 {"kind": "hold", "held_ms": 500}]}]}]
    rows.append(dict(rows[0], t_ms=9000))
    assert partB.waits_from_rows(rows) == {(1, 1): 2500}
    script = {"sessions": [{"index": 1, "kind": "replay", "turns": [{"n": 1}, {"n": 2}]}]}
    with pytest.raises(ValueError, match="missing_or_invalid_wait"):
        partB.check_waits({(1, 1): 2500}, script)
    sleeps, calls = [], []
    pacing = partB.Pacing(calls.append, {(1, 1): 2500, (1, 2): 500}, sleep=sleeps.append)
    for c in ((1, 1), (1, 1), (1, 2), None, (11, 1)):
        pacing({"session": c[0], "turn": c[1]} if c else None)
    assert sleeps == [2.5, 0.5] and len(calls) == 5
    a = {"messages": [{"role": "system", "content": "root /a port 32189 2026-10-27T00:00:00Z "
                       "12345678-1234-1234-1234-123456789abc"}]}
    b = {"messages": [{"role": "system", "content": "root /b port 42189 2025-01-01T00:00:00Z "
                       "87654321-4321-4321-4321-cba987654321"}]}
    av, bv = {"sandbox_root": "/a", "director_port": "32189"}, {"sandbox_root": "/b", "director_port": "42189"}
    assert partB.request_digest(a, av) == partB.request_digest(b, bv)
    b["messages"][0]["content"] = "changed"
    assert partB.differing_paths(partB.normalized_request(a, av), partB.normalized_request(b, bv)) == [
        "/messages/0/content"]


class FakeAdapter:
    def __init__(self, root, live, *, quota=False):
        root.mkdir()
        home = root / "hermes-home"
        home.mkdir()
        self.paths, self.live, self.rows = {"root": root, "hermes_home": home}, live, []
        self.before_shutdown, self.closed, self.quota = None, False, quota

    def run_session(self, index, **kw):
        self.live.count = index
        if index == 2:
            self.rows.append({"attempt_id": kw["attempt_id"], "upstream": [
                {"diagnostics": [{"kind": "try", "identity_changed": True}]}]})
        if self.before_shutdown:
            self.before_shutdown()
        return SimpleNamespace(session=index, kind="replay", turns_ok=1, finals_matched=1, restarts=[],
            summariser_records=0, surface_hash="a" * 64, gate=[], timings_ms={}, end_threads=(), finals=[])

    def records(self):
        return self.rows

    def close(self):
        self.closed = True
        return {"non_loopback": []}


class BoundaryLive(Recorder):
    count = 0

    def state(self):
        return {"identity_drift": {"model": "different"} if self.count >= 2 else None, "stopped": False}


def test_session_boundary_admission_and_receipts(tmp_path):
    live = BoundaryLive()
    adapter = FakeAdapter(tmp_path / "drift", live)
    script = {"sessions": [{"index": n} for n in range(1, 5)]}
    result = partB.run_arm("W", adapter, script, {n: n for n in range(1, 5)}, live=live, lock="ab" * 32)
    assert result["sessions_run"] == 2 and result["stop_reason"] == "identity_drift"
    assert result["flagged_sessions"] == [2] and adapter.closed
    assert json.loads((adapter.paths["root"] / "arm.json").read_bytes()) == json.loads(canon(result))
    live = BoundaryLive()
    adapter = FakeAdapter(tmp_path / "quota", live)
    holds = SimpleNamespace(at_boundary=lambda key: {"reasons": ["quota"], "held_ms": 0})
    result = partB.run_arm("N", adapter, script, {1: 1}, live=live, holds=holds, lock="ab" * 32)
    assert result["sessions_run"] == 1 and result["stop_reason"] == "quota_hold"
    ticks = iter([0, 2, 2])
    adapter = FakeAdapter(tmp_path / "wall", BoundaryLive())
    result = partB.run_arm("W", adapter, script, {}, lock="ab" * 32, wall_s=1, monotonic=lambda: next(ticks))
    assert result["sessions_run"] == 0 and result["stop_reason"] == "arm_wall"


@pytest.mark.parametrize("marker", [partB.read_marker.__globals__["Marker"](10, False, "busy"),
                                   partB.read_marker.__globals__["Marker"](0, False, "unset")])
def test_guard_precedes_root_and_credentials(tmp_path, monkeypatch, marker):
    order = []
    monkeypatch.setattr(partB, "reexec_niced", lambda argv: order.append("nice"))
    monkeypatch.setattr(partB, "read_marker", lambda: order.append("marker") or marker)
    monkeypatch.setattr(partB, "START_WAIT_S", 0)
    result = partB.main(["live", "--scratch", str(tmp_path), "--life", "missing.json", "--hermes", "fixture",
                         "--sol-max-output", "1000", "--sol-max-output-source", "fixture"])
    assert result == 3 and order == ["nice", "marker"] and not list(tmp_path.glob("p07-*"))
    with pytest.raises(ValueError, match="hermes_checkout_in_user_home"):
        partB.safe_checkout(Path.home() / ".hermes/checkout")


def test_injection_only_consequence_and_normalized_pairs():
    names = ("P1", "U1", "U2", "P2")
    script = {"sessions": [{"index": s, "turns": [{"n": t} for t in range(1, 7)]} for s in range(1, 11)]}
    arms, evidence, manifests = {}, {}, {}
    for arm in names:
        arms[arm] = {"stop_reason": None, "sessions": [{"session": s,
            "before": {"files": {}}, "after": {"files": {}}, "settle": {"settled": True}} for s in range(1, 11)]}
        rows, blobs = [], {}
        for s in range(1, 11):
            for t in range(1, 7):
                key = f"{s}/{t}"
                rows.append({"role": "replay_main", "subrole": "cursor", "cursor": {"session": s, "turn": t}, "req": key})
                blobs[key] = {"messages": [{"role": "system", "content": f"different {arm}\n<mem0>same</mem0>"}]}
        evidence[arm] = rows, blobs
        manifests[arm] = {"run_values": {"sandbox_root": f"/fixture/{arm}", "director_port": "30001"}}
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert not result["consequence"] and not result["noise"]
    assert len(result["pairs"]["P1-U1"]["request_diffs"]) == 60
    evidence["U1"][1]["1/1"]["messages"][0]["content"] = "<mem0>changed</mem0>"
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert result["consequence"] and result["noise"]
    assert result["pairs"]["P1-U1"]["cursor_diffs"] == ["1/1"]
    assert partB.injection_blocks({"messages": [{"role": "system", "content": "# Relevant memories\nkept\n# Tools\nother"}]}) == [
        "# Relevant memories\nkept\n"]
    with pytest.raises(ValueError, match="injection_block_unclosed"):
        partB.injection_blocks({"messages": [{"role": "system", "content": "<mem0>unclosed"}]})
    arms["P1"]["sessions"][0]["after"]["files"] = {"a": {"tables": {"facts": [2, "hash"]}}}
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert result["pairs"]["P1-U1"]["session_diffs"] == result["pairs"]["P1-U1"]["count_diffs"] == [1]


def recalled_block(text):
    return ("<memory-context>\n"
            "[System note: The following is recalled memory context, "
            "NOT new user input. Treat as authoritative reference data — "
            "this is the agent's persistent memory and should inform all responses.]\n\n"
            f"{text}\n</memory-context>")


@pytest.mark.parametrize("multipart", [False, True])
def test_injection_reads_current_user_memory_context(multipart):
    block = recalled_block("kept memory")
    content = ([{"type": "text", "text": block}, {"type": "text", "text": "current question"},
                {"type": "image_url", "text": "<memory>ignore image</memory>", "image_url": {"url": "fixture"}}]
               if multipart else block + "\n\ncurrent question")
    body = {"messages": [
        {"role": "system", "content": "<mem0>system</mem0>"},
        {"role": "developer", "content": "<memory_context>developer</memory_context>"},
        {"role": "user", "content": recalled_block("old recall")},
        {"role": "assistant", "content": "previous answer"},
        {"role": "user", "content": content},
        {"role": "assistant", "content": "<memory>ignore assistant</memory>"},
    ]}
    assert partB.injection_blocks(body) == [
        "<mem0>system</mem0>", "<memory_context>developer</memory_context>", block]
    body["messages"][-2]["content"] = "<memory-context>unclosed"
    with pytest.raises(ValueError, match="injection_block_unclosed"):
        partB.injection_blocks(body)


def pacing_inputs():
    script = {"sessions": [{"index": s, "turns": [{"n": t} for t in range(1, 7)]} for s in range(1, 11)]}
    arms, evidence, manifests = {}, {}, {}
    for arm in ("P1", "U1", "U2", "P2"):
        arms[arm] = {"stop_reason": None, "sessions": [{"session": s, "before": {"files": {}},
            "after": {"files": {}}, "settle": {"settled": True}} for s in range(1, 11)]}
        rows, blobs = [], {}
        for session in script["sessions"]:
            for turn in session["turns"]:
                s, t = session["index"], turn["n"]
                key = f"{s}/{t}"
                rows.append({"role": "replay_main", "subrole": "cursor", "cursor": {"session": s, "turn": t}, "req": key})
                blobs[key] = {"messages": [
                    {"role": "system", "content": "# Mem0 Memory Provider Active\nfixed instructions"},
                    {"role": "user", "content": recalled_block(f"kept {key}") + "\n\nquestion"}]}
        evidence[arm] = rows, blobs
        manifests[arm] = {"run_values": {"sandbox_root": f"/fixture/{arm}", "director_port": "30001"}}
    return arms, evidence, manifests, script


def test_recalled_user_blocks_set_cursor_diffs():
    arms, evidence, manifests, script = pacing_inputs()
    evidence["U1"][1]["1/1"]["messages"][-1]["content"] = recalled_block("changed recall") + "\n\nquestion"
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert result["pairs"]["P1-U1"]["cursor_diffs"] == ["1/1"]
    assert result["consequence"] and result["noise"]
    assert result["static_blocks"] == 1
    for body in evidence["U1"][1].values():
        body["messages"][-1]["content"] = recalled_block("constant different recall") + "\n\nquestion"
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert len(result["pairs"]["P1-U1"]["cursor_diffs"]) == 60
    assert result["consequence"] and result["noise"]


def test_static_system_blocks_do_not_set_cursor_diffs():
    arms, evidence, manifests, script = pacing_inputs()
    for arm, (_, blobs) in evidence.items():
        for body in blobs.values():
            body["messages"][0]["content"] += f"\nfixed arm heading {arm}"
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert all(pair["cursor_diffs"] == [] for pair in result["pairs"].values())
    assert not result["consequence"] and not result["noise"]
    assert result["static_blocks"] == 4
    assert len(result["pairs"]["P1-U1"]["request_diffs"]) == 60


@pytest.mark.parametrize("table", ["memories", "points"])
def test_pickled_blob_normalization_and_encoded_point_ids(tmp_path, table):
    arms, evidence, manifests, script = pacing_inputs()
    for _, blobs in evidence.values():
        for body in blobs.values():
            body["messages"] = [{"role": "system", "content": "<mem0>same</mem0>"}]
    exports, payloads, cells = {}, {}, {}
    for arm in arms:
        paced = arm.startswith("P")
        uuid = "12345678-1234-1234-1234-123456789abc" if paced else "87654321-4321-4321-4321-cba987654321"
        stamp = "2026-10-27T01:02:03Z" if paced else "2025-01-01T03:04:05Z"
        cell = cells[arm] = export_cell(tmp_path / arm, 32189 if paced else 42189)
        values = cell.adapter.director.run_values
        payload = payloads[arm] = {"id": uuid, "payload": {"memory": "kept memory", "id": uuid,
            "created_at": stamp, "updated_at": stamp, "root": values["sandbox_root"],
            "url": f"http://127.0.0.1:{values['director_port']}"}}
        blob = pickle.dumps(payload, protocol=4)
        key = base64.b64encode(pickle.dumps(uuid)).decode() if table == "points" else "stable-key"
        with sqlite3.connect(cell.surfaces[0][1] / "vectors.db") as db:
            db.execute(f"CREATE TABLE {table}(id TEXT, point BLOB)")
            db.execute(f"INSERT INTO {table} VALUES (?, ?)", (key, blob))
        cell.adapter._worker.proc.poll = lambda: 0
        exports[arm] = partB.store_export(cell)
        for session in arms[arm]["sessions"]:
            session["before"] = session["after"] = exports[arm]
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert result["pairs"]["P1-U1"]["session_diffs"] == []
    assert not result["consequence"] and not result["noise"]
    if table == "points":
        assert exports["P1"]["files"]["HERMES_HOME/./vectors.db"]["excluded_columns"] == {"points": ["id"]}
    else:
        assert not exports["P1"]["files"]["HERMES_HOME/./vectors.db"].get("excluded_columns")
    for arm, cell in cells.items():
        raw = pickle.dumps(payloads[arm], protocol=4)
        normalized = bytes.fromhex(partB._sql_value(raw, cell.adapter.director.run_values))
        assert len(normalized) == len(raw)
        assert pickle.loads(normalized)["payload"]["memory"] == "kept memory"
        assert payloads[arm]["id"].encode() not in normalized
        assert payloads[arm]["payload"]["created_at"].encode() not in normalized
    payloads["U1"]["payload"]["memory"] = "different memory"
    with sqlite3.connect(cells["U1"].surfaces[0][1] / "vectors.db") as db:
        db.execute(f"UPDATE {table} SET point = ?", (pickle.dumps(payloads["U1"], protocol=4),))
    arms["U1"]["sessions"][0]["after"] = partB.store_export(cells["U1"])
    result = partB.pacing_result(arms, evidence, manifests, script)
    assert result["pairs"]["P1-U1"]["session_diffs"] == [1]
    assert result["consequence"] and result["noise"]
    if table == "memories":
        with sqlite3.connect(cells["P1"].surfaces[0][1] / "vectors.db") as db:
            db.execute("UPDATE memories SET id = 'meaningful-key-change'")
        assert partB.store_export(cells["P1"])["files"] != exports["P1"]["files"]


def test_passive_config_withholding_fixture(tmp_path):
    entry = partB.load_entry("mem0-oss")
    config = partB.hermes_config(30001, "bicentennial-main", plugin="mem0", plugin_config=partB.passive_config(entry))
    tools = [t["tool"] for t in entry["write_tools"]] + entry["read_tools"]
    offered = [t for t in tools if t not in config["disabled_tools"]]
    assert offered == ["mem0_search"]
    rows = [{"req": "a"}]
    blobs = {"a": {"tools": [{"type": "function", "function": {"name": t}} for t in offered]}}
    assert partB.verify_withholding(rows, blobs, entry) == {"checked_requests": 1, "offered_write_tools": []}
    blobs["a"]["tools"].append({"function": {"name": "mem0_add"}})
    with pytest.raises(ValueError, match="mem0_write_tool_offered"):
        partB.verify_withholding(rows, blobs, entry)
    target = tmp_path / "acp_adapter"
    target.mkdir()
    path = target / "session.py"
    path.write_text('# disabled_tools=config.get("disabled_tools", [])\n')
    assert not partB.withholding_supported(tmp_path)
    path.write_text('agent(disabled_tools=config.get("disabled_tools", []))\n')
    assert partB.withholding_supported(tmp_path)


@pytest.fixture
def responses_server(monkeypatch):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    bodies, outbound = [], []
    original = socket.socket.connect

    def connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            outbound.append(address[0])
            raise OSError("non-loopback refused")
        return original(sock, address)

    monkeypatch.setattr(socket.socket, "connect", connect)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            write = body["input"][-1] == partB.typed([{"type": "message", "role": "user", "content": partB.SUFFIX}])[0]
            item = ({"type": "function_call", "call_id": "fake-call", "name": "memory",
                     "arguments": json.dumps({"action": "add", "content": "offline synthetic memory"})} if write else
                    {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "offline final"}]})
            events = [{"type": "response.output_item.done", "output_index": 0, "item": item},
                      {"type": "response.completed", "response": {"model": "fake-served", "usage": {
                          "input_tokens": 10, "output_tokens": 3}}}]
            data = b"".join(b"data: " + canon(e) + b"\n\n" for e in events)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", bodies, outbound
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_director_live_write_bridge_canary(tmp_path, responses_server):
    helpers = runpy.run_path(str(partB.ROOT / "tests/director/test_core.py"))
    base, bodies, outbound = responses_server
    entry = partB.load_entry("hermes-native")
    live, _ = partB.make_live(tmp_path / "spend.json", auth=lambda: {"Authorization": "Bearer t"},
                             base_url=base, max_output_tokens=1000, model="probe-model")
    d = helpers["make"](tmp_path, partB.Routed(live, partB.ScriptedResponder(entry)), write_prompt=partB.SUFFIX)
    try:
        helpers["start"](d, tmp_path)
        status, _, raw = helpers["post"](d, "/main/v1/chat/completions", helpers["turn_body"]())
        assert status == 200
        call = json.loads(raw)["choices"][0]["message"]["tool_calls"][0]
        assert call["function"]["name"] == "memory"
        assert len(bodies) == 1 and not outbound
        body = bodies[0]
        assert body["model"] == "probe-model" and body["stream"] is True
        assert body["instructions"] == "s"
        assert body["input"][-1] == {"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": partB.SUFFIX}]}
        assert [t["name"] for t in body["tools"]] == ["memory"]
        assert body["reasoning"] == {"effort": "medium"} and body["store"] is False
        assert "max_output_tokens" not in body
        rows, blobs, _ = partB.audit_api.load(tmp_path / "ledger", "kit")
        assert rows[0]["write_turn_readback"] and rows[0]["write_calls"] == 1
        assert partB.bridge_readback(rows, blobs) == {"sent": 1, "matched": 1, "mismatches": []}
        audit = partB.audit_api.audit(rows, blobs, partB.audit_api.turns_from_script(helpers["SCRIPT"]),
            "chat", fmt="kit", model_for=lambda s: "probe-model", suffix=partB.SUFFIX,
            write_tools=["memory"], id_needles=[])
        assert audit["A1"]["write_records"] == audit["A1"]["forwarded"] == audit["A1"]["matches"] == 1
        title = {"model": "bicentennial-aux-title_generation", "messages": [{"role": "user", "content": "title"}]}
        assert helpers["post"](d, "/aux/title_generation/v1/chat/completions", title)[0] == 200
        assert len(bodies) == 1
        spend = json.loads((tmp_path / "spend.json").read_bytes())
        assert spend["settled"] == spend["refused_calls"] == 0
        altered = {**blobs, rows[0]["upstream"][0]["req"]: {"messages": []}}
        assert partB.bridge_readback(rows, altered)["mismatches"] == [{"record": 1, "try": 1}]
    finally:
        d.close()


def test_fake_worker_end_to_end(generated, tmp_path, responses_server, monkeypatch):
    from bicentennial.harness.hermes import adapter as adapter_module

    base, bodies, outbound = responses_server
    life, gold, schedule = generated
    script, _, starts = partB.build_script(life, schedule, probes=True)
    script = dict(script, sessions=[*script["sessions"][:2], script["sessions"][10]])
    root = tmp_path / "p07-W"
    root.mkdir()
    entry = partB.load_entry("hermes-native")
    live, holds = partB.make_live(tmp_path / "spend.json", auth=lambda: {}, base_url=base,
                                 max_output_tokens=1000, model="probe-model")
    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    routes = partB.RouteTable.load({"routes": [{"system": "hermes-native", "segment": "seg0",
        "probe_model": "probe-model", "summariser": "probe-model", "alias": "bicentennial-main",
        "vision": None, "served_by": "live"}]})
    a = partB.HermesAdapter(entry, script=script, route_table=routes, schedule=partB.FaultLite.load([], script),
        responder=partB.Routed(live, partB.ScriptedResponder(entry)), clock=partB.SimClock(root / "clock.json", starts[1], 60),
        root=root, scratch=tmp_path, life="tidewater", branch="B0", run="fake-run", write_prompt=partB.SUFFIX,
        harness_pin=dict(entry["artifact"]), worker_argv=[sys.executable, str(partB.ROOT / "tests/harness/fake_worker.py")])
    before = []
    a.before_shutdown = lambda: before.append(a._worker.proc.poll())
    partB.write_json(root / "script.json", script)
    manifest = {"arm": "W", "entry": entry, "faults": [], "routes": routes.to_obj()}
    result = partB.run_arm("W", a, script, starts, live=live, holds=holds, gold=gold, lock="ab" * 32)
    if result["stop_reason"] == "worker_start":
        diagnostics = b"".join(p.read_bytes() for p in (root / "logs").glob("worker-*.stderr"))
        if b"Operation not permitted" in diagnostics and b"taskpolicy" in diagnostics:
            pytest.xfail("dispatcher-rerun: sandbox denies taskpolicy worker start")
    assert result["stop_reason"] is None and result["sessions_run"] == 3
    assert before == [None] * 3 and not outbound
    assert len(json.loads((root / "arm.json").read_bytes())["sessions"]) == 3
    report, _, _ = partB.arm_readback(root, manifest)
    assert report["A1"]["matches"] == report["A1"]["forwarded"] == 10
    assert report["bridge"]["matched"] == report["bridge"]["sent"] == len(bodies)
    assert report["run_status"] == "UNATTRIBUTED" and report["failures"] == ["A4.gaps"]
    assert report["A4"]["gaps"] and not report["A3"]["failures"] and not report["A5"]["script_failures"]


def test_pacing_in_adapter_hold_chain(generated, tmp_path):
    life, _, schedule = generated
    script, _, starts = partB.build_script(life, schedule, probes=False)
    script = dict(script, sessions=script["sessions"][:1])
    entry = dict(partB.load_entry("mem0-oss"), write_tools=[])
    root = tmp_path / "p07-P1"
    root.mkdir()
    a = partB.HermesAdapter(entry, script=script, route_table=partB.route_table("P1"),
        schedule=partB.FaultLite.load([], script), responder=partB.ScriptedResponder(entry),
        clock=partB.SimClock(root / "clock.json", starts[1], 60), root=root, scratch=tmp_path,
        life="tidewater", branch="B0", run="fake-paced", harness_pin=dict(partB.load_entry("hermes-native")["artifact"]),
        worker_argv=[sys.executable, str(partB.ROOT / "tests/harness/fake_worker.py")])
    sleeps, calls = [], []
    original = a.director.on_hold

    def chained(cursor):
        calls.append(cursor)
        return original(cursor)

    a.director.on_hold = partB.Pacing(chained, {(1, 1): 2500}, sleep=sleeps.append)
    try:
        a.director.start_session(1, starts[1], "ab" * 32, "fake-attempt", root / "ledger")
        body = {"model": "bicentennial-main", "messages": [{"role": "system", "content": "s"},
                {"role": "user", "content": script["sessions"][0]["turns"][0]["user"]}],
                "tools": [{"type": "function", "function": {"name": "mem0_search"}}]}
        status, _, raw = a.director.handle("POST", "/main/v1/chat/completions", {}, canon(body))
        assert status == 200 and json.loads(raw)["choices"][0]["message"]["content"] == partB.ASSISTANT
        assert sleeps == [2.5] and calls == [{"session": 1, "turn": 1}]
        rows, blobs, _ = partB.audit_api.load(root / "ledger", "kit")
        assert partB.verify_withholding(rows, blobs, partB.load_entry("mem0-oss"))["offered_write_tools"] == []
    finally:
        a.close()


def test_before_export_wired_to_run_arm(generated, tmp_path):
    life, _, schedule = generated
    script, _, starts = partB.build_script(life, schedule, probes=False)
    script = dict(script, sessions=script["sessions"][:1])
    live = BoundaryLive()
    adapter = FakeAdapter(tmp_path / "boundary", live)
    cell = export_cell(tmp_path / "store-root", 30001)
    writer = populate_store(cell, "12345678-1234-1234-1234-123456789abc", 30001, "2026-10-27T00:00:00Z")
    original = adapter.run_session

    def session(index, **kw):
        result = original(index, **kw)
        cell.adapter._worker.proc.poll = lambda: 0
        return result

    adapter.run_session = session
    cell.settle = lambda: SimpleNamespace()  # replaced with the real receipt dataclass below
    from bicentennial.systems.settle import SettleResult
    cell.settle = lambda: SettleResult("hook", True, 1, "drained", 0)
    try:
        result = partB.run_arm("P1", adapter, script, starts, cell=cell, lock="ab" * 32)
        receipt = result["sessions"][0]
        assert receipt["before"]["files"] == receipt["after"]["files"]
        assert receipt["before"]["files"]["HERMES_HOME/./facts.db"]["tables"]["facts"][0] == 2
        assert receipt["settle"]["settled"]
    finally:
        writer.close()


def test_summarise_real_director_ledgers_and_exclusive_result(generated, tmp_path):
    from bicentennial.director.core import Director
    from bicentennial.ledger import Guard

    life, gold, schedule = generated
    full, _, starts = partB.build_script(life, schedule, probes=True)
    script = dict(full, sessions=[dict(full["sessions"][0], turns=full["sessions"][0]["turns"][:1])])
    inputs = {"model": partB.MODEL, "effort": partB.EFFORT}
    partB.write_json(tmp_path / "run.json", {"inputs": inputs, "gold": gold})
    partB.write_json(tmp_path / "pace-script.json", partB.build_script(life, schedule, probes=False)[0])
    for arm in ("W", "N"):
        root = tmp_path / f"p07-{arm}"
        root.mkdir()
        (root / "hermes-home").mkdir()
        entry = dict(partB.load_entry("hermes-native"), write_tools=[])
        table = partB.route_table(arm)
        d = Director(script, table, entry["name"], "tidewater", "B0", "offline", (),
            partB.ScriptedResponder(entry), partB.SimClock(root / "clock.json", starts[1], 60), Guard([]),
            {"sandbox_root": str(root), "director_port": "30001"}, partB.SUFFIX)
        try:
            d.start_session(1, starts[1], "ab" * 32, f"attempt-{arm}", root / "ledger")
            body = {"model": "bicentennial-main", "messages": [{"role": "system", "content": "s"},
                {"role": "user", "content": script["sessions"][0]["turns"][0]["user"]}],
                "tools": [{"type": "function", "function": {"name": "memory"}}]}
            assert d.handle("POST", "/main/v1/chat/completions", {}, canon(body))[0] == 200
        finally:
            d.close()
        partB.write_json(root / "script.json", script)
        partB.write_json(root / "arm.json", {"sessions": [], "stop_reason": None})
        partB.write_json(root / "manifest.json", {"arm": arm, "entry": entry, "faults": [], "routes": table.to_obj()})
    result = partB.summarise(tmp_path)
    assert result["canary"] == partB.CANARY and result["claim_class"] == "advisory"
    assert result["readback"]["N"]["A1"]["write_records"] == 0
    assert result["pacing"]["status"] == "not_run" and result["pacing"]["reason"] == "mem0_blocked"
    assert result["planted"]["n"] == 3
    out = tmp_path / "partB.json"
    command = ["summarise", "--scratch", str(tmp_path), "--out", str(out)]
    assert partB.main(command) == 0 and out.read_bytes() == canon(result) + b"\n"
    with pytest.raises(FileExistsError, match="result_exists"):
        partB.main(command)
    assert out.read_bytes() == canon(result) + b"\n"


def test_cli_credential_stop_is_not_retried(monkeypatch, tmp_path, capsys):
    calls = []

    def stopped(args):
        calls.append(args.command)
        raise partB.Stop("home_busy")

    monkeypatch.setattr(partB, "_execute", stopped)
    assert partB.main(["live", "--scratch", str(tmp_path), "--life", "life.json", "--hermes", "fixture",
                       "--sol-max-output", "1000", "--sol-max-output-source", "fixture"]) == 4
    assert calls == ["live"] and capsys.readouterr().err == "home_busy\n"


def test_unknown_injection_cannot_produce_a_green_pacing_result():
    assert partB.injection_blocks({"messages": [{"role": "system", "content": "ordinary instructions"}]}) == []
    with pytest.raises(ValueError, match="injection_shape_unverified"):
        partB.injection_blocks({"messages": [{"role": "system", "content": "Relevant memories: unknown layout"}]})
    names = ("P1", "P2", "U1", "U2")
    script = {"sessions": [{"index": s, "turns": [{"n": 1}]} for s in range(1, 11)]}
    arms = {a: {"stop_reason": None, "sessions": [{"session": s} for s in range(1, 11)]} for a in names}
    rows = [{"role": "replay_main", "subrole": "cursor", "cursor": {"session": s, "turn": 1}, "req": str(s)}
            for s in range(1, 11)]
    evidence = {a: (rows, {str(s): {"messages": []} for s in range(1, 11)}) for a in names}
    manifests = {a: {"run_values": {"sandbox_root": "/fixture", "director_port": "30001"}} for a in names}
    assert partB.pacing_result(arms, evidence, manifests, script) == {
        "status": "incomplete", "reason": "injection_shape_unverified"}


def test_stored_tokens_do_not_span_separate_files(tmp_path):
    memories = tmp_path / "memories"
    memories.mkdir()
    (memories / "MEMORY.md").write_text("65")
    (memories / "USER.md").write_text("43")
    (tmp_path / "state.db-wal").write_text("6543")
    gold = {"P1/1": {"gold": ["6543"]}}
    stored, transcript = partB._channels(tmp_path, gold)
    assert stored == {"P1/1": [False]} and transcript == {"P1/1": [True]}
    (memories / "USER.md").write_text("6543")
    assert partB._channels(tmp_path, gold)[0] == {"P1/1": [True]}


def test_egress_stop_prevents_new_session(tmp_path):
    live = BoundaryLive()
    adapter = FakeAdapter(tmp_path / "egress", live)
    adapter.egress = SimpleNamespace(summary=lambda: {"non_loopback": ["synthetic"]})
    result = partB.run_arm("W", adapter, {"sessions": [{"index": 1}]}, {}, live=live, lock="ab" * 32)
    assert result["sessions_run"] == 0 and result["stop_reason"] == "non_loopback" and adapter.closed
