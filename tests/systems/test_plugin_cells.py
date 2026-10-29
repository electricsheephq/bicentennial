"""R13b acceptance: wiring proven against fakes, never a real provider run."""

import ast
import ipaddress
import json
import os
import random
import runpy
import socket
import subprocess
import sys
import threading
import time
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import _check
from bicentennial.director.responder import Call
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import FORMATS, WRITE_ARGS, ScriptedResponder
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
)
from bicentennial.harness.hermes.config import PLACEHOLDER_KEY
from bicentennial.ledger import BlobStore, Guard, verify
from bicentennial.runner.life import PluginWake
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.surfaces import surface_hash, verify_empty
from bicentennial.systems import hermes_plugin
from bicentennial.systems.hermes_plugin import (
    MEM0_THREADS,
    PROVIDERS,
    TREES,
    PluginCell,
)
from bicentennial.systems.registry import (
    REGISTRY,
    ZERO_HASH,
    SystemRefused,
    admit_system,
    check,
    load,
)
from bicentennial.systems.settle import settle, threads_drained

ROOT = Path(__file__).resolve().parents[2]
FAKE = Path(__file__).with_name("fake_plugin_worker.py")
SCHEMAS = json.loads((ROOT / "tests/fixtures/systems/tool-schemas.json").read_bytes())
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
COMPILE = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
SCRIPT = COMPILE(dict(LIFE, sessions=LIFE["sessions"][:2], probes=[]))
NAMES = tuple(PROVIDERS)
ARCHIVED_NAMES = ("holographic", "mem0-oss")  # Existing synthetic worker models these two only.
BASE, LOCK, NONCE = 1_600_000_000, "ab" * 32, "R13B_NONCE_ONLY_SESSION_ONE"
ACTIONS = "add change end correct revert merge forget update remove alias rename delete_entity split rebuild_entities".split()
SURFACE = {"root": "HERMES_HOME", "relative": ".", "volatile_paths": [".mcp-discovery.lock", "logs"]}


def entry(name):
    return load(REGISTRY / f"{name}.toml")


@pytest.mark.parametrize("name", NAMES)
def test_entries_exact(name):
    e = entry(name)
    mem = name == "mem0-oss"
    expected = {
        "name": name, "licence": "Apache-2.0" if mem else "MIT", "harness": "hermes",
        "artifact": {"name": "hermes-plugin-mem0" if mem else "hermes-plugin-holographic",
                     "version": "1.3.0" if mem else "0.13.0",
                     "sha256": "bcdeee0243eb5367fdfdb5589c8025ae13d9198954f793fb5b8e1ae212ac8465" if mem else
                     "22a2c514fa6b4141e3bcb75f4ac6e5ddbb4028244a73a95503d8900a92ce2fc1"},
        "write_tools": [{"tool": t, "actions": []} for t in ("mem0_add", "mem0_update", "mem0_delete")] if mem else [
            {"tool": "fact_store", "actions": ACTIONS},
            {"tool": "fact_feedback", "actions": ["helpful", "unhelpful", "confirmed"]}],
        "read_tools": ["mem0_search" if mem else "fact_store"],
        "recall": {"tool": "mem0_search" if mem else "fact_store", "argument_template": {
            "query": "{prompt}", **({} if mem else {"action": "search"})}},
        "surfaces": [SURFACE, *([{"root": "SANDBOX_HOME", "relative": ".mem0", "volatile_paths": []}] if mem else [])],
        "fresh_install_hash": "a2591a33006ad2ec3dc65eac9ed0aac78cda3e4aae23e1f7d2f7ee76ef02f486" if mem else
        "37f634904b04f0e315983382c5afec0e367c00d1bd32b1083e99dd70b8843fa9",
        "own_model_routes": [{"role": r, "alias": f"bicentennial-{r}"} for r in ("extraction", "embeddings")] if mem else [],
        "structured_formats": {}, "embedding_dim": 1536 if mem else None,
        "settle": {"kind": "hook" if mem else "none", "bound_s": 5 if mem else 0},
        "machine_class": "light", "benchmark_operator_runs": True,
    }
    if mem:
        string = {"type": "string"}
        schema = {"oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["facts"],
             "properties": {"facts": {"type": "array", "items": string}}},
            {"type": "object", "additionalProperties": False, "required": ["memory"],
             "properties": {"memory": {"type": "array", "items": {
                 "type": "object", "additionalProperties": False, "required": ["event", "id", "text"],
                 "properties": {"event": {"enum": ["ADD"]}, "id": string, "text": string}}}}},
        ]}
        expected["structured_formats"] = {"extraction": {"kind": "json", "schema": schema}}
    if name == "omega":
        expected.update(licence="Apache-2.0", artifact=dict(name="hermes-plugin-omega", version="1.5.20",
            sha256=e["artifact"]["sha256"]), write_tools=[dict(tool=t, actions=[]) for t in ("omega_store", "omega_delete")],
            read_tools=["omega_query"], recall=dict(tool="omega_query", argument_template={"query": "{prompt}"}),
            fresh_install_hash=e["fresh_install_hash"], settle=dict(kind="hook", bound_s=5))  # CLI pins the unmeasured/measured phase.
    assert e == expected and check(e) == []
    if name != "omega" or e["artifact"]["sha256"] != ZERO_HASH:
        assert admit_system(e, operator="benchmark") is None
    unmeasured = deepcopy(e)
    unmeasured["artifact"]["sha256"] = unmeasured["fresh_install_hash"] = ZERO_HASH
    with pytest.raises(SystemRefused) as refused:
        admit_system(unmeasured, operator="benchmark")
    assert refused.value.reasons == ("unmeasured:artifact.sha256", "unmeasured:fresh_install_hash")
    measured = deepcopy(e)
    measured["artifact"]["sha256"], measured["fresh_install_hash"] = "a" * 64, "b" * 64
    assert admit_system(measured, operator="benchmark") is None
    tools = {t["name"]: t["parameters"] for t in SCHEMAS["tools"][PROVIDERS[name]]}
    tool, fixed, content = WRITE_ARGS[name]
    assert tools[tool]["properties"][content]["type"] == "string"
    if fixed:
        assert fixed["action"] in tools[tool]["properties"]["action"]["enum"]
    assert SCHEMAS["canary"] in (ROOT / "CANARY").read_text()
    assert "description" not in canon(SCHEMAS).decode()


def call(messages, role="aux", subrole="extraction", **body):
    return Call(role, subrole, "chat", {"messages": messages, **body}, "route-model", None, "attempt")


def user(text):
    return {"role": "user", "content": text}


@pytest.mark.parametrize("name", NAMES)
def test_write_mapping_and_offered_schema_limit(name):
    responder = ScriptedResponder(entry(name))
    tool, fixed, content = WRITE_ARGS[name]
    tools = [{"type": "function", "function": t} for t in deepcopy(SCHEMAS["tools"][PROVIDERS[name]])]
    messages = [user("old"), {"role": "assistant", "content": "answer"}, user("latest 猫")]
    c = call(messages, role="write_turn", subrole="write_turn", tools=tools)
    assert responder.respond(c).tool_calls == ({"name": tool, "arguments": canon({**fixed, content: "latest 猫"}).decode()},)
    target = next(t["function"] for t in tools if t["function"]["name"] == tool)
    target["parameters"]["properties"][content]["maxLength"] = 3
    assert json.loads(responder.respond(c).tool_calls[0]["arguments"])[content] == "lat"
    other = next(t for t in tools if t["function"]["name"] != tool and t["function"]["name"] in responder.write_tools)
    refused = responder.respond(replace(c, body=dict(c.body, tools=[other])))
    assert (refused.status, refused.served, refused.tool_calls) == (400, "write_tool_unmapped", ())


def test_mem0_filler_shapes_and_limits():
    r = ScriptedResponder(entry("mem0-oss"))
    assert ("mem0-oss", "extraction") in FORMATS
    messages = [{"role": "system", "content": "extract"}, user("a" * 300), user("猫" * 300)]
    reply = r.respond(call(messages))
    assert reply.text == canon({"facts": ["a" * 240, "猫" * 240]}).decode()
    assert reply.tool_calls == () and reply.usage["estimated"]
    assert r.respond(call(messages, role="extraction", subrole="")).text == reply.text
    assert r.respond(call([user("no array")], max_tokens=3)).served == "reply_over_budget"
    for text, facts in [('[{"id":"x","text":"old"}] then ["a","b"]', ["a", "b"]),
                        ('["keep [] literally"]', ["keep [] literally"]), ("no array", []),
                        ('{"nested":["wrong"]} ["right"] "[\\"also wrong\\"]"', ["right"]),
                        ('["first"] {"nested":["wrong"]}', ["first"])]:
        assert r.respond(call([user(text)])).text == canon({"memory": [
            {"event": "ADD", "id": str(i), "text": f} for i, f in enumerate(facts)]}).decode()
    for limit in (0, 1, 2, 3, 8, 70, 300):
        reply = r.respond(call(messages, max_tokens=limit))
        if limit < 3:
            assert (reply.status, reply.served) == (400, "reply_over_budget")
        else:
            assert len(reply.text.encode()) <= 4 * limit
            assert len(json.loads(reply.text)["facts"]) < 2 if limit < 300 else True
    no_limit = r.respond(call([*messages, *[user("猫" * 240) for _ in range(30)]]))
    assert len(no_limit.text) <= 4096
    rng = random.Random(13)
    for _ in range(50):
        facts = [''.join(rng.choices('[]{}"\\猫abc', k=30)) for _ in range(rng.randrange(8))]
        text = '[{"text":"old"}]\n' + json.dumps(facts)
        got = json.loads(r.respond(call([user(text)])).text)["memory"]
        assert [row["text"] for row in got] == facts
    native = entry("holographic")
    native["name"] = "hermes-native"
    native["write_tools"] = []
    native["structured_formats"] = {"extraction": {"kind": "json", "schema": {}}}
    with pytest.raises(ValueError):
        ScriptedResponder(native)
    vector = r.respond(Call("embeddings", "embeddings", "embeddings", {"input": ["a b"], "dimensions": 1536},
                           "route-model", None, "attempt"))
    assert len(vector.embedding[0]) == 1536 and all(type(v) is int for v in vector.embedding[0])


def test_mem0_hashseed_determinism():
    program = '''
import json,sys
from dataclasses import asdict
from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder
obj=json.load(sys.stdin)
r=ScriptedResponder(obj['entry'])
sys.stdout.buffer.write(canon([asdict(r.respond(Call(**c))) for c in obj['calls']]))
'''
    payload = canon({"entry": entry("mem0-oss"), "calls": [asdict(call([user('["keep [] literally"]')])),
                       asdict(call([{"role": "system", "content": "extract"}, user("猫")]))]})
    output = [subprocess.run([sys.executable, "-c", program], input=payload, capture_output=True, check=True,
                            env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("0", "random")]
    assert output[0] == output[1]


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def wait(e, observe=None, **kw):
    clock = Clock()
    return settle(e, observe, monotonic=clock.monotonic, sleep=clock.sleep, **kw)


def test_settle_units():
    e = {"settle": {"kind": "hook", "bound_s": 5}}
    result = wait(e, lambda: False, poll_s=1)
    assert (result.settled, result.reason, result.polls, result.waited_ms) == (False, "bound_reached", 6, 5000)
    count = iter([False, False, True])
    assert wait(e, lambda: next(count), poll_s=1).polls == 3
    assert wait({"settle": {"kind": "hook", "bound_s": 0}}, lambda: False).polls == 1
    assert wait({"settle": {"kind": "none", "bound_s": 0}}).polls == 0
    with pytest.raises(ValueError):
        wait({"settle": {"kind": "none", "bound_s": 0}}, lambda: pytest.fail("observed"))
    with pytest.raises(ValueError):
        wait(e)
    with pytest.raises(TypeError):
        wait(e, lambda: 1)
    clock = Clock()
    def late():
        clock.now = 6
        return True
    late_result = settle(e, late, monotonic=clock.monotonic, sleep=clock.sleep)
    assert (late_result.settled, late_result.reason, late_result.polls) == (False, "bound_reached", 1)
    stop = threading.Event()
    t = threading.Thread(target=stop.wait, name="mem0-sync")
    t.start()
    try:
        assert not threads_drained(MEM0_THREADS)()
    finally:
        stop.set()
        t.join()
    assert threads_drained(MEM0_THREADS)()


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.01)
    for name in ("BICENTENNIAL_BUSY_CMD", "BICENTENNIAL_OPERATOR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def socket_guard(monkeypatch):
    seen, real = [], socket.socket.connect
    def connect(sock, address):
        if not ipaddress.ip_address(address[0]).is_loopback:
            seen.append(address)
            raise OSError("non-loopback socket refused")
        return real(sock, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return seen


def plugin_repo(scratch, name):
    repo = scratch / f"repo-{name}"
    repo.mkdir()
    target = repo / "integrations/hermes-plugin-mem0" if name == "mem0-oss" else repo
    target.mkdir(parents=True, exist_ok=True)
    (target / "provider.py").write_text("# stand-in provider\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=test", "-c", "user.email=test@example.invalid",
                                               "commit", "-qm", "fake pin"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", *TREES[name]],
                             capture_output=True, check=True).stdout
    return repo, sha256(archive).hexdigest(), target / "provider.py"


def test_install_ignores_git_location_variables(tmp_path, git_checkouts, monkeypatch):
    def install(label):
        root = tmp_path / label
        paths = {name: root / name for name in ("home", "hermes_home", "workspace", "tmp")}
        for path in paths.values():
            path.mkdir(parents=True)
        paths["root"] = root
        stub = SimpleNamespace(paths=paths, director=SimpleNamespace(run_values={"director_port": 12345}))
        e = entry("holographic")
        e["artifact"]["sha256"] = sha256(git_checkouts.archive).hexdigest()
        cell = PluginCell(e, stub)
        digest = cell.install(git_checkouts.checkout, alias="bicentennial-main")
        installed = paths["hermes_home"] / "plugins/holographic/README"
        assert installed.read_text() == "checkout\n"
        assert not installed.with_name("other-only.txt").exists()
        return digest

    clean = install("clean-install")
    (git_checkouts.other / "README").write_text("Unrelated tracked changes.\n")
    for name, value in git_checkouts.conflict.items():
        monkeypatch.setenv(name, value)
    assert install("conflicting-install") == clean


def test_mem0_archive_repeatable(tmp_path):
    assert TREES == {"holographic": ("HEAD",), "mem0-oss": ("HEAD", "integrations/hermes-plugin-mem0"),
                     "omega": ("HEAD", "adapters/hermes-plugin-omega")}
    repo, digest, _ = plugin_repo(tmp_path, "mem0-oss")
    time.sleep(1.1)
    archive = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", *TREES["mem0-oss"]],
                             capture_output=True, check=True).stdout
    assert sha256(archive).hexdigest() == digest


def make(scratch, label, name, digest):
    e, script = entry(name), deepcopy(SCRIPT)
    e["artifact"]["sha256"] = digest
    script["sessions"][0]["turns"][0]["user"] += " " + NONCE
    routes = {"routes": [{"system": name, "segment": "seg0", "probe_model": "probe-model",
                          "alias": "bicentennial-main", "summariser": "summary-model", "vision": None,
                          "served_by": "scripted"}]}
    root = scratch / label
    root.mkdir()
    a = HermesAdapter(e, script=script, route_table=RouteTable.load(routes), schedule=FaultLite.load([], script),
                      responder=ScriptedResponder(e), clock=SimClock(root / "clock.json", BASE, 60), root=root,
                      scratch=scratch, life="s6a-micro", branch="B0", run=f"run-{label}",
                      plugin=PROVIDERS[name], worker_argv=[sys.executable, str(FAKE)], gate_poll_s=0)
    return a, PluginCell(e, a)


def session(a, index):
    return a.run_session(index, sim_t_s=BASE + index * 86400, lock_hash=LOCK, attempt_id=f"attempt-s{index}")


def branches(schema, obj):
    matches = 0
    for branch in schema["oneOf"]:
        try:
            _check(branch, obj)
        except ValueError:
            continue
        matches += 1
    assert matches == 1


@pytest.mark.parametrize("name", ARCHIVED_NAMES)
def test_two_sessions_wipe_and_digest(tmp_path, name, socket_guard):
    repo, digest, _ = plugin_repo(tmp_path, name)
    digests = []
    for label in ("a", "b"):
        a, cell = make(tmp_path, label, name, digest)
        wiped = []
        def hook(reason, a=a, cell=cell, wiped=wiped):
            if a.director.session_index == 2 and reason == "session_start":
                assert cell.wipe() is True
                assert cell.store_contains(NONCE.encode()) == []
                for (s, d), (_, h) in zip(cell.surfaces, cell.snapshots, strict=True):
                    verify_empty(d, s["volatile_paths"], h)
                wiped.append(True)
                return True
        a.before_spawn = hook
        try:
            fresh = cell.install(repo, alias="bicentennial-main")
            assert cell.surface_hash() == fresh
            first = session(a, 1)
            assert cell.settle().settled
            assert cell.surface_hash() != fresh
            found = cell.store_contains(NONCE.encode())
            if name == "holographic":
                assert "HERMES_HOME/./memory_store.db" in found
            else:
                assert any(p.startswith("SANDBOX_HOME/.mem0/") for p in found)
            second = session(a, 2)
            assert wiped == [True] and second.reset == "control_wipe"
            assert first.end_threads == second.end_threads == ()
            assert second.turns_ok == second.finals_matched == 5
            result = cell.settle()
            if name == "holographic":
                assert (result.kind, result.settled, result.polls, result.reason) == ("none", True, 0, "no_background_work")
            else:
                assert (result.settled, result.reason) == (True, "drained")
            assert cell.audit() == []
            records = a.records()
            writes = [r for r in records if r.get("served") == "write_tool_calls"]
            assert len(writes) == 10 and all(r["write_turn_readback"] is True for r in writes)
            blobs = BlobStore(a.paths["root"] / "ledger/blobs", Guard([]))
            for row in writes:
                reply = json.loads(blobs.get(row["upstream"][0]["resp"]))
                assert [c["name"] for c in reply["tool_calls"]] == [WRITE_ARGS[name][0]]
            assert not [r for r in records if r.get("role") == "unknown" or r.get("subrole") in (
                "egress", "malformed_body") or r.get("served") == "director_error"]
            counts = verify(a.paths["root"] / "ledger")
            assert counts["records"] == len(records)
            assert counts["chain_breaks"] == counts["truncated_tail"] == counts["bad_blobs"] == 0
            embeddings = [r for r in records if r.get("role") == "embeddings"]
            if name == "holographic":
                assert not embeddings
            else:
                assert embeddings
                steps = set()
                for row in records:
                    if row.get("subrole") != "extraction":
                        continue
                    assert (row["role"], row["served"], row["status"]) == ("aux", "responder_scripted", 200)
                    reply = json.loads(blobs.get(row["upstream"][0]["resp"]))
                    obj = json.loads(reply["text"])
                    branches(cell.entry["structured_formats"]["extraction"]["schema"], obj)
                    steps.update(obj)
                assert steps == {"facts", "memory"}
            digests.append(a.stable_digest())
        finally:
            summary = a.close()
        assert summary["non_loopback"] == []
    assert digests[0] == digests[1]
    assert socket_guard == []


@pytest.mark.parametrize("name", ARCHIVED_NAMES)
def test_install_refusals_and_config(tmp_path, name):
    repo, digest, tracked = plugin_repo(tmp_path, name)
    a, cell = make(tmp_path, "install", name, digest)
    try:
        for bad in ("0" * 64, "f" * 64):
            cell.entry["artifact"]["sha256"] = bad
            with pytest.raises(PinMismatch):
                cell.install(repo, alias="bicentennial-main")
        cell.entry["artifact"]["sha256"] = digest
        tracked.write_text("# dirty tracked file\n")
        with pytest.raises(PinMismatch):
            cell.install(repo, alias="bicentennial-main")
        tracked.write_text("# stand-in provider\n")
        fresh = cell.install(repo, alias="bicentennial-main")
        with pytest.raises(ValueError, match="directory exists"):
            cell.install(repo, alias="bicentennial-main")
        home = a.paths["hermes_home"]
        cfg = json.loads((home / "config.yaml").read_bytes())
        assert cfg["memory"]["provider"] == PROVIDERS[name]
        assert "plugins" not in cfg
        assert (home / "plugins" / PROVIDERS[name] / "provider.py").is_file()
        if name == "holographic":
            assert fresh == surface_hash(home, SURFACE["volatile_paths"])
            assert not (home / "mem0.json").exists()
        else:
            base = f"http://127.0.0.1:{a.server.port}/mem0/v1"
            common = {"api_key": PLACEHOLDER_KEY, "openai_base_url": base}
            expected = {"mode": "oss", "user_id": "hermes-user", "agent_id": "hermes", "rerank": False,
                        "oss": {"llm": {"provider": "openai", "config": {
                            **common, "model": "bicentennial-extraction", "is_reasoning_model": True}},
                            "embedder": {"provider": "openai", "config": {
                                **common, "model": "bicentennial-embeddings", "embedding_dims": 1536}},
                            "vector_store": {"provider": "qdrant", "config": {
                                "path": "~/.mem0/qdrant", "collection_name": "mem0"}}}}
            assert (home / "mem0.json").read_bytes() == canon(expected) + b"\n"
            assert (home / ".env").read_bytes() == b"MEM0_TELEMETRY=false\n"
            hashes = [{"relative": s["relative"], "root": s["root"], "tree_hash": h}
                      for (s, _), (_, h) in zip(cell.surfaces, cell.snapshots, strict=True)]
            assert fresh == sha256(canon(hashes)).hexdigest()
    finally:
        a.close()


@pytest.mark.parametrize("fault,expected", [(".fake-stray", ["home/stray"]), (".fake-tmp-stray", ["tmp/stray"])])
def test_undeclared_write_audit(tmp_path, fault, expected):
    repo, digest, _ = plugin_repo(tmp_path, "holographic")
    a, cell = make(tmp_path, "stray", "holographic", digest)
    try:
        cell.install(repo, alias="bicentennial-main")
        (a.paths["hermes_home"] / fault).touch()
        session(a, 1)
        assert cell.audit() == expected
    finally:
        a.close()


def test_audit_changes_and_removals(tmp_path):
    repo, digest, _ = plugin_repo(tmp_path, "holographic")
    a, cell = make(tmp_path, "audit", "holographic", digest)
    try:
        path = a.paths["workspace"] / "baseline"
        path.write_text("before")
        cell.install(repo, alias="bicentennial-main")
        path.write_text("after")
        assert cell.audit() == ["workspace/baseline"]
        path.unlink()
        assert cell.audit() == ["workspace/baseline"]
    finally:
        a.close()


def test_mem0_telemetry_fault(tmp_path):
    repo, digest, _ = plugin_repo(tmp_path, "mem0-oss")
    a, cell = make(tmp_path, "telemetry", "mem0-oss", digest)
    try:
        cell.install(repo, alias="bicentennial-main")
        (a.paths["hermes_home"] / ".env").unlink()
        session(a, 1)
        assert any(r.get("subrole") == "egress" for r in a.records())
    finally:
        a.close()


def test_mem0_settle_before_session(tmp_path, monkeypatch):
    a, cell = make(tmp_path, "unstarted", "mem0-oss", "a" * 64)
    monkeypatch.setattr(hermes_plugin, "settle", wait)
    try:
        assert a.end_threads is None
        barrier = cell.settle()
        assert not barrier.settled and barrier.reason == "bound_reached"
    finally:
        a.close()


@pytest.mark.parametrize("failure", ["worker_start", "end_failed"])
def test_mem0_failed_session_clears_end_observation(tmp_path, monkeypatch, failure):
    repo, digest, _ = plugin_repo(tmp_path, "mem0-oss")
    a, cell = make(tmp_path, "failed", "mem0-oss", digest)
    monkeypatch.setattr(hermes_plugin, "settle", wait)
    try:
        cell.install(repo, alias="bicentennial-main")
        assert session(a, 1).end_threads == a.end_threads == ()
        assert cell.settle().settled
        if failure == "worker_start":
            a.plugin = "inactive"
        else:
            (a.paths["hermes_home"] / ".fake-end").write_bytes(canon({"ok": False}))
        with pytest.raises(HarnessFailed, match=f"^{failure}$"):
            session(a, 2)
        assert a.end_threads is None
        barrier = cell.settle()
        assert not barrier.settled and barrier.reason == "bound_reached"
    finally:
        a.close()


@pytest.mark.parametrize("payload,expected", [({"alive_threads": ["mem0-sync"]}, ("mem0-sync",)), ({}, None)])
def test_mem0_requires_observed_threads(tmp_path, monkeypatch, payload, expected):
    repo, digest, _ = plugin_repo(tmp_path, "mem0-oss")
    a, cell = make(tmp_path, "pending", "mem0-oss", digest)
    monkeypatch.setattr(hermes_plugin, "settle", (lambda *a, **kw: pytest.fail("cut work must not poll"))
                        if expected is not None else wait)
    try:
        cell.install(repo, alias="bicentennial-main")
        (a.paths["hermes_home"] / ".fake-end").write_bytes(canon(payload))
        result = session(a, 1)
        assert result.end_threads == expected and a.end_threads == expected
        barrier = cell.settle()
        assert not barrier.settled
        if expected is not None:
            assert (barrier.reason, barrier.polls, barrier.waited_ms) == ("cut_at_exit", 0, 0)
        else:
            assert barrier.reason == "bound_reached" and barrier.waited_ms == 5000
    finally:
        a.close()


@pytest.mark.parametrize("kind,threads,expected", [
    ("hook", ("mem0-sync",), ("cut_at_exit", False, 0, 0)),
    ("hook", ("unrelated-worker",), ("drained", True, 2, 250)),
    ("none", ("mem0-sync",), ("no_background_work", True, 0, 0)),
    ("hook", ["mem0-sync"], ("bound_reached", False, 21, 5000)),
])
def test_settle_cut_and_delegation(tmp_path, monkeypatch, kind, threads, expected):
    inflight, calls = iter((1, 0)), []
    paths = {k: tmp_path / k for k in ("home", "hermes_home", "workspace", "tmp")}
    a = SimpleNamespace(paths=dict(paths, root=tmp_path), end_threads=threads,
                        director=SimpleNamespace(control=lambda: dict(inflight=next(inflight))))
    cell = PluginCell(entry("mem0-oss"), a)
    cell.entry["settle"]["kind"] = kind

    def polling(entry, observe):
        if expected[0] == "cut_at_exit":
            pytest.fail("cut work must not poll")
        calls.append(entry["settle"]["kind"])
        return wait(entry, observe)

    monkeypatch.setattr(hermes_plugin, "settle", polling)
    result = cell.settle()
    assert calls == ([] if expected[0] == "cut_at_exit" else [kind])
    assert result.kind == kind
    assert (result.reason, result.settled, result.polls, result.waited_ms) == expected


def test_surface_and_home_refusals(tmp_path, monkeypatch):
    paths = {k: tmp_path / k for k in ("root", "home", "hermes_home", "workspace", "tmp")}
    paths["home"] = paths["root"] / "home"
    a = SimpleNamespace(paths=paths)
    e = entry("holographic")
    for changed in (dict(e, name="other"), dict(e, harness="other"),
                    dict(e, surfaces=[dict(SURFACE, root="SERVER_DATA")]),
                    dict(e, surfaces=[dict(SURFACE, relative="../outside")])):
        with pytest.raises(ValueError):
            PluginCell(changed, a)
    paths["hermes_home"].mkdir()
    (paths["hermes_home"] / "escape").symlink_to(tmp_path)
    with pytest.raises(ValueError):
        PluginCell(dict(e, surfaces=[dict(SURFACE, relative="escape")]), a)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "user")
    paths["home"] = tmp_path / "user" / "unsafe"
    with pytest.raises(ValueError, match="isolated"):
        PluginCell(e, a)


def test_checkpoint_and_worker_guards(tmp_path):
    import sqlite3
    repo, digest, _ = plugin_repo(tmp_path, "holographic")
    a, cell = make(tmp_path, "wal", "holographic", digest)
    try:
        cell.install(repo, alias="bicentennial-main")
        db = a.paths["hermes_home"] / "test.db"
        con = sqlite3.connect(db)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE facts(text)")
            con.execute("INSERT INTO facts VALUES (?)", (NONCE,))
            con.commit()
            wal = db.with_name("test.db-wal")
            assert wal.stat().st_size > 0
            assert "HERMES_HOME/./test.db" in cell.store_contains(NONCE.encode())
            assert wal.stat().st_size == 0
        finally:
            con.close()
        assert cell.wipe() is True
        assert cell.store_contains(NONCE.encode()) == []
        for (s, d), (_, h) in zip(cell.surfaces, cell.snapshots, strict=True):
            verify_empty(d, s["volatile_paths"], h)
        a._worker = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None))
        for action in (cell.checkpoint, cell.wipe, cell.settle):
            with pytest.raises(ValueError, match="worker must exit"):
                action()
        a._worker = None
    finally:
        a.close()


def test_checkpoint_refuses_a_held_wal(tmp_path, monkeypatch):
    import sqlite3

    from bicentennial.harness.hermes.adapter import HarnessFailed
    from bicentennial.systems import hermes_plugin as hp

    db = tmp_path / "store" / "test.db"
    db.parent.mkdir()
    writer, reader = sqlite3.connect(db), sqlite3.connect(db)
    wal = db.with_name("test.db-wal")
    monkeypatch.setattr(hp, "sqlite3", SimpleNamespace(connect=lambda path: sqlite3.connect(path, timeout=0.1)))
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE facts(text)")
        writer.execute("INSERT INTO facts VALUES (?)", (NONCE,))
        writer.commit()
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM facts").fetchone()  # a read transaction on the WAL
        with pytest.raises(HarnessFailed, match="checkpoint_busy"):
            hp.checkpoint_sqlite([db.parent])
        assert wal.stat().st_size > 0
        reader.close()
        hp.checkpoint_sqlite([db.parent])  # the open writer keeps the WAL file, so its truncation is visible
        assert wal.stat().st_size == 0
    finally:
        reader.close()
        writer.close()


def test_import_boundaries():
    for filename in ("hermes_plugin.py", "settle.py"):
        tree = ast.parse((ROOT / "src/bicentennial/systems" / filename).read_text())
        modules = [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        modules += [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module]
        assert not ({m.split(".")[0] for m in modules} & {"socket", "http", "urllib", "requests"})
    fake = ast.parse(FAKE.read_text())
    modules = [a.name for n in ast.walk(fake) if isinstance(n, ast.Import) for a in n.names]
    modules += [n.module for n in ast.walk(fake) if isinstance(n, ast.ImportFrom) and n.module]
    assert all(m.split(".")[0] in sys.stdlib_module_names for m in modules)


def test_director_extraction_and_recorded_refusals(tmp_path):
    a, cell = make(tmp_path, "routing", "mem0-oss", "a" * 64)
    try:
        d = a.director
        d.start_session(1, BASE, LOCK, "attempt-s1", a.paths["root"] / "ledger")
        for messages, limit, status in [
            ([{"role": "system", "content": "extract"}, user("fact")], 100, 200),
            ([user('["keep [] literally"]')], 100, 200),
            ([{"role": "system", "content": "extract"}, user("fact")], 0, 400),
        ]:
            body = {"model": "bicentennial-extraction", "messages": messages,
                    "max_tokens": limit, "response_format": {"type": "json_object"}}
            got, _, _ = d.handle("POST", "/mem0/v1/chat/completions", {}, canon(body))
            assert got == status
            row = a.records()[-1]
            assert (row["role"], row["subrole"]) == ("aux", "extraction")
            assert row["served"] == ("responder_scripted" if status == 200 else "responder_reply_over_budget")
    finally:
        a.close()
    a, cell = make(tmp_path, "unmapped", "holographic", "a" * 64)
    try:
        d = a.director
        d.start_session(1, BASE, LOCK, "attempt-s1", a.paths["root"] / "ledger")
        body = {"model": "bicentennial-main", "messages": [user(a.script["sessions"][0]["turns"][0]["user"])],
                "tools": [{"type": "function", "function": SCHEMAS["tools"]["holographic"][1]}]}
        d.handle("POST", "/main/v1/chat/completions", {}, canon(body))
        assert d.control()["write_failures"] == 1
        row = a.records()[-1]
        blobs = BlobStore(a.paths["root"] / "ledger/blobs", Guard([]))
        reply = json.loads(blobs.get(row["upstream"][0]["resp"]))
        assert reply["served"] == "write_tool_unmapped" and reply["status"] == 400
    finally:
        a.close()


@pytest.mark.parametrize("payload,expected", [({"alive_threads": ["z", "mem0-sync", "a"]}, ("a", "mem0-sync", "z")),
                                              ({}, None)])
def test_end_observation_without_process_priority(tmp_path, monkeypatch, payload, expected):
    """A7 unit path independent of the sandbox's denied process-priority operation."""
    a, cell = make(tmp_path, "end", "mem0-oss", "a" * 64)
    calls = []
    worker = SimpleNamespace(call=lambda **kw: {"ok": True, **payload},
                             kill=lambda **kw: calls.append(kw), proc=SimpleNamespace(poll=lambda: 0))
    a._worker = worker
    monkeypatch.setattr(hermes_plugin, "settle", wait)
    try:
        a.end_threads = a._end()
        assert a.end_threads == expected and calls == [{"clean": True}]
        assert not cell.settle().settled
        a.end_threads = ()
        assert cell.settle().settled
    finally:
        a.close()


@pytest.mark.parametrize("thread", ["auto-relate", "omega-deferred-init"])
def test_omega_settle_thread_ends(monkeypatch, thread):
    cell = PluginCell.__new__(PluginCell)
    cell.entry = entry("omega")
    cell.adapter = SimpleNamespace(end_threads=(thread,), director=SimpleNamespace(control=lambda: {"inflight": 0}))
    monkeypatch.setattr(hermes_plugin, "settle", wait)
    assert not cell.settle().settled
    cell.adapter.end_threads = ()
    assert cell.settle().settled


@pytest.mark.parametrize("name", ARCHIVED_NAMES)
def test_fresh_install_hash_is_port_stable_and_direct(tmp_path, name):
    from bicentennial.sandbox.surfaces import install_hash

    repo, digest, _ = plugin_repo(tmp_path, name)
    opened, cells = [], []
    try:
        for label in ("fresh-a", "fresh-b"):
            a, cell = make(tmp_path, label, name, digest)
            opened.append(a)
            result = cell.install(repo, alias="bicentennial-main")
            assert result == cell.surface_hash()
            hashes = [{"relative": s["relative"], "root": s["root"],
                       "tree_hash": install_hash(d, s["volatile_paths"], a.server.port)}
                      for s, d in cell.surfaces]
            expected = hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()
            assert len(hashes) == (2 if name == "mem0-oss" else 1)
            assert cell.fresh_install_hash == expected
            assert cell.fresh_install_hash != result
            for (s, d), (_, fresh) in zip(cell.surfaces, cell.snapshots, strict=True):
                assert fresh == surface_hash(d, s["volatile_paths"])
            cells.append(cell)
        assert opened[0].server.port != opened[1].server.port
        assert cells[0].fresh_install_hash == cells[1].fresh_install_hash
    finally:
        for a in reversed(opened):
            a.close()


@pytest.mark.parametrize("name", ARCHIVED_NAMES)
def test_plugin_wake_hashes_are_port_stable(tmp_path, monkeypatch, name):
    repo, digest, _ = plugin_repo(tmp_path, name)
    records, raw = [], []
    for port in (41001, 51002):
        root = tmp_path / str(port)
        paths = {key: root / key for key in ("home", "hermes_home", "workspace", "tmp")}
        for path in paths.values():
            path.mkdir(parents=True)
        paths["root"] = root
        fake = SimpleNamespace(paths=paths, director=SimpleNamespace(run_values={"director_port": str(port)}))
        e = entry(name)
        e["artifact"]["sha256"] = digest
        cell = PluginCell(e, fake)
        cell.install(repo, alias="bicentennial-main")
        raw.append([h for _, h in cell.snapshots])
        hook = PluginWake()
        hook.cell = cell
        assert hook("session_start") is False
        for _, directory in cell.surfaces:
            (directory / "unwiped").write_bytes(b"retained memory")
        assert hook("kill") is True
        for (s, directory), (_, fresh) in zip(cell.surfaces, cell.snapshots, strict=True):
            verify_empty(directory, s["volatile_paths"], fresh)
        rows = hook.records()
        assert all(s["post_wipe_hash"] == s["fresh_install_hash"] for s in rows[1]["surfaces"])
        records.append(canon(rows))
        monkeypatch.setattr(cell, "wipe", lambda: True)
        for _, directory in cell.surfaces:
            (directory / "unwiped").write_bytes(b"retained memory")
        hook("restart")
        assert all(s["post_wipe_hash"] != s["fresh_install_hash"] for s in hook.records()[2]["surfaces"])
    assert raw[0] != raw[1]
    assert records[0] == records[1]
