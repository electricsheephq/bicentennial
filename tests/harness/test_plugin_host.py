"""R16b: real file worker, isolated stdlib Hermes surfaces, no provider download."""

import ast
import json
import os
import random
import runpy
import shlex
import shutil
import subprocess
import sys
import time
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
from hermes_stub import MODULES, write_tree

from bicentennial.api import conformance
from bicentennial.api.contract import answer
from bicentennial.canon import canon
from bicentennial.director.routes import RouteTable, segment_of
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.harness.hermes import plugin_host
from bicentennial.harness.hermes.adapter import HarnessFailed, verify_pin
from bicentennial.harness.hermes.plugin_host import (
    CHECKPOINT_FORMAT,
    SESSION_PREFIX,
    WORKER,
    GateRefused,
    HermesMemoryHost,
)
from bicentennial.items.protocol import CANARY
from bicentennial.probe.scripted_reader import read_api
from bicentennial.runner.guard import assert_niced
from bicentennial.runtime.clock import SimClock
from bicentennial.systems.hermes_plugin import MARKER, TREES, PluginCell
from bicentennial.systems.registry import REGISTRY, SystemRefused, load

NAMES = ("hermes-native", "holographic", "mem0-oss")
BASE, LOCK = 1_600_000_000, "ab" * 32
ROUTES = {"routes": [{"system": "hermes-native", "segment": seg, "probe_model": "probe-model", "alias": alias,
                      "summariser": "summary-model", "vision": None, "served_by": "scripted"}
                     for seg, alias in (("seg0", "bicentennial-main"), ("seg1", "bicentennial-swap"))]}


def event(i=1, text="quartz", **kw):
    return dict(event_id=f"e{i}", t_sim=i, kind="message", actor="user", text=text, **kw)


def task(prompt="quartz", **kw):
    return dict(task_id="probe", prompt=prompt, **kw)


def report(capsys, value):
    with capsys.disabled():
        print(json.dumps(value, sort_keys=True), flush=True)


def no_float(value):
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for child in value.values():
            no_float(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            no_float(child)


def plugin_repo(dest, name):
    """Only synthetic repositories are committed; the lane's checkout is never committed."""
    dest.mkdir()
    target = dest / "integrations/hermes-plugin-mem0" if name == "mem0-oss" else dest
    target.mkdir(parents=True, exist_ok=True)
    (target / "provider.py").write_text("# synthetic archive pin, not an installed provider\n")
    for args in (["init", "-q"], ["add", "."], ["-c", "user.name=test", "-c", "user.email=test@example.invalid",
                                               "commit", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(dest), *args], check=True, capture_output=True)
    archive = subprocess.run(["git", "-C", str(dest), "archive", "--format=tar", *TREES[name]],
                             check=True, capture_output=True).stdout
    return dest, sha256(archive).hexdigest()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, request):
    if request.node.originalname in ("test_live", "test_native_session_start_snapshot_live"):
        return
    for name in ("BICENTENNIAL_BUSY_CMD", "BICENTENNIAL_OPERATOR"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def factory(tmp_path, monkeypatch):
    opened, checked, summaries = [], [], []
    counter = 0
    real = plugin_host.assert_niced

    def niced(pid):
        real(pid)
        checked.append(pid)

    monkeypatch.setattr(plugin_host, "assert_niced", niced)

    def make(name="hermes-native", *, mode="none", sync_ms=0, live=None, max_length=None, **overrides):
        nonlocal counter
        counter += 1
        root = tmp_path / f"run-{counter}"
        root.mkdir()
        entry = load(REGISTRY / f"{name}.toml")
        log = tmp_path / f"calls-{counter}" / "stub-calls.jsonl"
        if live is None:
            checkout = write_tree(tmp_path / f"stub-{counter}", log=log, mode=mode, sync_ms=sync_ms,
                                  max_length=max_length)
            kw = dict(checkout=checkout, worker_argv=[sys.executable, str(WORKER)])
        else:
            kw = dict(checkout=live, harness_pin=entry["artifact"])
        if name != "hermes-native":
            source, digest = plugin_repo(tmp_path / f"plugin-{counter}", name)
            entry["artifact"]["sha256"] = digest
            kw["plugin_source"] = source
        routes = deepcopy(ROUTES)
        for route in routes["routes"]:
            route["system"] = name
        kw.update(overrides)
        host = HermesMemoryHost(entry, route_table=RouteTable.load(routes), responder=ScriptedResponder(entry),
                                clock=SimClock(root / "clock.json", BASE, 60), root=root, scratch=tmp_path,
                                life="t0-pack", branch="B0", run=f"run-{len(opened)}", lock_hash=LOCK, **kw)
        opened.append(host)
        if live is None:
            host.stub_log = log
            assert not log.is_relative_to(root)
            assert all(not log.is_relative_to(directory) for directory, _ in host.surfaces())
        return host

    yield make
    for host in reversed(opened):
        pids = list(host.pids)
        summaries.append(host.close())
        for directory, _ in host.surfaces():
            assert not list(directory.rglob("stub-calls.jsonl"))
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    assert checked == [pid for host in opened for pid in host.pids]
    if shutil.which("lsof"):
        assert all(s["non_loopback"] == [] for s in summaries)


def test_host_surface_before_install(factory, monkeypatch):
    layout, install = plugin_host.layout, PluginCell.install
    installed = []

    def populate(*args, **kwargs):
        paths = layout(*args, **kwargs)
        directory = paths["hermes_home"] if content == "hermes" else paths["home"] / ".mem0"
        directory.mkdir(exist_ok=True)
        (directory / (MARKER if content == "marker" else "stray")).write_bytes(b"")
        return paths

    def installing(self, *args, **kwargs):
        installed.append(content)
        return install(self, *args, **kwargs)

    monkeypatch.setattr(plugin_host, "layout", populate)
    monkeypatch.setattr(PluginCell, "install", installing)
    for content in ("stray", "marker", "hermes"):
        if content == "stray":
            with pytest.raises(SystemRefused) as error:
                factory("mem0-oss")
            assert error.value.reasons == ("surface_not_empty",)
            assert installed == []
        else:
            host = factory("mem0-oss")
            assert installed[-1] == content
            assert (host.paths["hermes_home"] / "stray").exists() == (content == "hermes")


@pytest.mark.parametrize("name", NAMES)
def test_conformance(factory, name, capsys):
    matrix = conformance.run(lambda: factory(name))
    declared = conformance.declared(lambda: factory(name))
    # The declared skip is printed beside the matrix, so its True never reads as a storage pass (E12).
    report(capsys, dict(system=name, mode="none", conformance=matrix, declared=declared))
    assert matrix == dict.fromkeys(conformance.CHECKS, True)
    assert declared == {"actor_stored": "declared"}


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("limit,expected", [(None, 0), (3, 3), (0, 5)])
def test_written_fields_and_clip_count(factory, name, limit, expected):
    host = factory(name, max_length=limit)
    events = [event(i, text) for i, text in enumerate(("", "ab", "abc", "abcd", "猫" * 9, "abcde"), 1)]
    for e in events:
        host.ingest(e)
        host.ingest(e)  # Idempotent delivery must not count twice.
    assert type(host.write_clipped) is int and host.write_clipped == expected
    assert host.write_max_length == limit
    fields = {"actor": "not_delivered", "text": "full" if limit is None else f"clipped:{limit}",
              "time": "session_clock"}
    assert host.fields() == fields
    delivery = plugin_host.WriteDelivery()
    delivery.add([host])
    assert delivery.properties("t0") == [
        ("t0.write_clipped", expected), ("t0.fields", canon(fields).decode())] + (
        [] if limit is None else [("t0.write_max_length", limit)])
    assert vars(delivery) == dict(clipped=expected, limits=set() if limit is None else {limit},
                                 delivered=fields)
    for e in events:
        assert host.events[e["event_id"]] == {"event": e, "session": 1, "written": e["text"][:limit]}
    assert host.settle(5)
    data = host.checkpoint()
    host.restore(data)
    assert host.write_clipped == expected
    assert host.checkpoint() == data  # Disclosure counters do not alter checkpoint bytes.
    host.forget(dict(event_ids=["e4"]))
    host.reset()
    assert host.write_clipped == expected
    host.ingest(event(7, "new delivery"))
    assert host.write_clipped == expected + int(limit is not None)


def test_fault_free_session_schedule(factory):
    host = factory()
    assert host.script["sessions"] == []
    assert host.director.turns == ()
    assert host.director.session_index == 1
    for index in (1, 2, 3):
        if index > 1:
            host.begin_session(index)
        assert host.director.schedule.to_obj() == []
        assert host.director.session_index == index
        assert all(segment_of(i, host.director.schedule) == "seg0" for i in range(1, index + 1))
    assert host._worker is None


@pytest.mark.parametrize("mode,failed", [("wipe_on_open", "checkpoint_restore"),
                                         ("keep_on_remove", "forget_removes"),
                                         ("stale_wins", "supersession_current")])
def test_single_fault(factory, mode, failed, capsys):
    matrix = conformance.run(lambda: factory(mode=mode))
    declared = conformance.declared(lambda: factory(mode=mode))
    report(capsys, dict(system="hermes-native", mode=mode, conformance=matrix, declared=declared))
    assert matrix == {name: name != failed for name in conformance.CHECKS}
    assert declared == {"actor_stored": "declared"}


def calls(host):
    return [json.loads(line) for line in host.stub_log.read_text().splitlines()]


def logged(name, *args, **kw):
    return dict(name=name, args=list(args), kwargs=kw)


def test_plugin_hook_order(factory):
    host = factory("holographic")
    host.ingest(event())
    sid = SESSION_PREFIX + "1"
    assert calls(host) == [logged("load_memory_provider", "holographic"), logged("is_available"),
                           logged("MemoryManager"), logged("add_provider"),
                           logged("initialize_all", session_id=sid, platform="cli", agent_context="primary"),
                           logged("build_system_prompt"), logged("get_all_tool_schemas"),
                           logged("on_turn_start", 1, "quartz"), logged("prefetch_all", "quartz", session_id=sid),
                           logged("handle_tool_call", "fact_store", dict(action="add", content="quartz")),
                           logged("sync_all", "quartz", "", session_id=sid),
                           logged("queue_prefetch_all", "quartz", session_id=sid)]
    assert host.settle(5)
    host.begin_session(2)
    assert calls(host)[-2:] == [logged("on_session_end", [dict(role="user", content="quartz")]),
                               logged("shutdown_all")]
    assert host._worker is None
    host.ingest(event(2, "topaz"))
    assert host.pids[0] != host.pids[1]
    assert logged("initialize_all", session_id=SESSION_PREFIX + "2", platform="cli", agent_context="primary") in calls(host)
    assert host.harness_record()["active_memory_providers"] == ["holographic"]


def test_native_hook_order(factory):
    host = factory()
    host.ingest(event())
    sid = SESSION_PREFIX + "1"
    assert calls(host) == [logged("load_on_disk_store"), logged("SessionDB"),
                           logged("create_session", sid, source="cli"),
                           logged("append_message", sid, "user", "quartz"),
                           logged("memory_tool", action="add", target="memory", content="quartz")]
    assert host.settle(5)
    host.query(task(), 100)
    assert calls(host)[-1] == logged("session_search", query="quartz", current_session_id=None)
    host.forget(dict(event_ids=["e1"]))
    assert calls(host)[-1] == logged("memory_tool", action="remove", target="memory", old_text="quartz")
    assert host.settle(5)
    host.begin_session(2)
    assert calls(host)[-2:] == [logged("end_session", sid, "user_exit"), logged("close")]


@pytest.mark.parametrize("memory_enabled,user_enabled,blocks,expected", [
    (True, True, {"memory": "memory block", "user": "user block"}, "memory block\n\nuser block"),
    (False, True, {"memory": "hidden", "user": "user block"}, "user block"),
    (True, False, {"memory": "memory block", "user": "hidden"}, "memory block"),
    (False, False, {"memory": "hidden", "user": "hidden"}, ""),
    (True, True, {"memory": None, "user": ""}, ""),
])
def test_worker_snapshot_gating_and_order(factory, monkeypatch, memory_enabled, user_enabled, blocks, expected):
    source = MODULES["tools/memory_tool.py"]
    source += f'''
MemoryStore.memory_enabled = {memory_enabled!r}
MemoryStore.user_profile_enabled = {user_enabled!r}


def format_snapshot(self, target):
    assert {{"memory": self.memory_enabled, "user": self.user_profile_enabled}}[target]
    return {blocks!r}[target]


MemoryStore.format_for_system_prompt = format_snapshot
'''
    monkeypatch.setitem(MODULES, "tools/memory_tool.py", source)
    host = factory()
    host.ingest(event())
    assert host.settle(5)
    reply = host._call("query", text="quartz", recall=dict(name="session_search", arguments=dict(query="quartz")))
    assert reply["snapshot"] == expected


@pytest.mark.parametrize("name", ("holographic", "mem0-oss"))
def test_plugin_worker_snapshot_empty(factory, name):
    host = factory(name)
    host.ingest(event())
    assert host.settle(5)
    reply = host._call("query", text="quartz", recall=dict(name="unused", arguments={}))
    assert reply["snapshot"] == ""


@pytest.mark.parametrize("name,search,delete,args", [
    ("holographic", "fact_store", "fact_store", dict(action="remove", fact_id="1")),
    ("mem0-oss", "mem0_search", "mem0_delete", dict(memory_id="1")),
])
def test_provider_forget(factory, name, search, delete, args):
    host = factory(name)
    host.ingest(event())
    host.forget(dict(event_ids=["e1"]))
    found = logged("handle_tool_call", search, dict(query="quartz", **({"action": "search"} if name == "holographic" else {})))
    # The pass that deleted a row is followed by one more search, which finds nothing left to delete.
    assert calls(host)[-3:] == [found, logged("handle_tool_call", delete, args), found]


def pack(host, *, strict):
    answers, blocks = [], []
    for k in range(1, 4):
        for j in range(1, 6):
            host.ingest(dict(event_id=f"e{k}{j}", t_sim=100 * k + j, kind="message", actor="user",
                             text=f"Session {k} note {j}: code K{k}{j}X{k}{j}"))
        assert host.settle(5)
        for j in range(1, 6):
            assert host.settle(5)
            probe = task(f"code K{k}{j}X{k}{j}")
            blocks.append(host.probe(probe, 100 * k + 50))
            result = host.query(probe, 100 * k + 50)
            no_float(result)
            if strict:
                assert result == dict(output=f"Session {k} note {j}: code K{k}{j}X{k}{j}",
                                      citations=[f"e{k}{j}"], confidence_milli=1000)
            answers.append(result)
        if k < 3:
            assert host.settle(5)
            host.begin_session(k + 1)
    host.forget(dict(event_ids=["e11"]))
    assert host.settle(5)
    blocks.append(host.probe(task("K11X11"), 400))
    forgotten = host.query(task("K11X11"), 400)
    answers.append(forgotten)
    assert host.settle(5)
    checkpoint = host.checkpoint()
    if strict:
        assert forgotten == answer([])
        assert b"K11X11" not in checkpoint
        for directory, _ in host.surfaces():
            assert all(b"K11X11" not in p.read_bytes() for p in directory.rglob("*") if p.is_file())
    no_float(host.stats())
    no_float(host.harness_record())
    assert host.records() == []
    return answers, blocks


@pytest.mark.parametrize("name", NAMES)
def test_three_session_pack(factory, name, capsys):
    results = []
    for run in (1, 2):
        start = time.monotonic()
        host = factory(name)
        results.append(pack(host, strict=True))
        elapsed_ms = int((time.monotonic() - start) * 1000)
        report(capsys, dict(system=name, pack_run=run, elapsed_ms=elapsed_ms,
                            answers=results[-1][0], context_blocks=results[-1][1]))
        assert elapsed_ms <= 60_000
        assert len(host.pids) == 3
    assert canon(results[0]) == canon(results[1])


@pytest.mark.parametrize("name", NAMES)
def test_checkpoint_delta_restore(factory, name):
    original, fresh = factory(name), factory(name)
    original.ingest(event())
    surface = original.surfaces()[0][0]
    (surface / "scratch-shm").write_bytes(b"volatile")
    (surface / "extra").mkdir(mode=0o750)
    (surface / "extra/note").write_bytes(b"raw content")
    (surface / "extra/note").chmod(0o640)
    (surface / ".bicentennial-sandbox").unlink()
    assert original.settle(5)
    data = original.checkpoint()
    header, payload = data.split(b"\n", 1)
    header = json.loads(header)
    assert header["format"] == CHECKPOINT_FORMAT
    assert all(r["path"] != "config.yaml" and not r["path"].endswith("-shm") for r in header["files"])
    assert dict(surface=0, path=".bicentennial-sandbox") in header["removed"]
    own_config = (fresh.paths["hermes_home"] / "config.yaml").read_bytes()
    assert original.server.port != fresh.server.port
    fresh.restore(data)
    assert (fresh.paths["hermes_home"] / "config.yaml").read_bytes() == own_config
    assert not (fresh.surfaces()[0][0] / ".bicentennial-sandbox").exists()
    assert (fresh.surfaces()[0][0] / "extra/note").read_bytes() == b"raw content"
    assert (fresh.surfaces()[0][0] / "extra/note").stat().st_mode & 0o777 == 0o640
    assert fresh.query(task(), 100) == original.query(task(), 100)
    for bad in (data[:-1], canon(dict(header, system="wrong")) + b"\n" + payload,
                canon(dict(header, files=[dict(header["files"][0], path="../x"), *header["files"][1:]])) + b"\n" + payload):
        with pytest.raises(ValueError):
            fresh.restore(bad)
    with pytest.raises(TypeError):
        fresh.restore(data.decode())
    # Restore a normal checkpoint so reset and fixture teardown retain the marker invariant.
    (fresh.surfaces()[0][0] / ".bicentennial-sandbox").touch()
    (surface / ".bicentennial-sandbox").touch()


def test_unsettled_guards_and_single_use_cache(factory):
    host = factory()
    assert host.settle(0) is True and host._worker is None
    host.ingest(event())
    for operation in (lambda: host.query(task(), 100), host.checkpoint, lambda: host.begin_session(2)):
        with pytest.raises(RuntimeError):
            operation()
    assert host.settle(5)
    blocks = host.probe(task(), 100)
    count = len(calls(host))
    assert blocks == host.context_blocks()
    assert host.query(task(), 100) == answer([event()])
    assert len(calls(host)) == count
    with pytest.raises(RuntimeError):
        host.query(task(), 100)
    assert host.settle(5)
    host.probe(task(), 100)
    with pytest.raises(RuntimeError):
        host.query(task("different"), 100)


@pytest.mark.parametrize("change", ["ingest", "forget", "reset", "restore", "session"])
def test_cache_invalidation(factory, change):
    host = factory()
    host.ingest(event())
    assert host.settle(5)
    snapshot = host.checkpoint()
    host.probe(task(), 100)
    if change == "ingest":
        host.ingest(event(2, "new quartz"))
    elif change == "forget":
        host.forget(dict(event_ids=["e1"]))
    else:
        assert host.settle(5)
        {"reset": host.reset, "restore": lambda: host.restore(snapshot), "session": lambda: host.begin_session(2)}[change]()
    assert host._cache is None
    assert host.settle(5)
    result = host.query(task(), 100)
    assert result["output"] == {"ingest": "new quartz", "forget": "UNKNOWN", "reset": "UNKNOWN",
                                 "restore": "quartz", "session": "quartz"}[change]
    if change == "ingest":
        assert result["citations"] == ["e2"]


def test_reader_injected_uses_one_recall(factory):
    host = factory("holographic")
    host.ingest(event(text="the CODE7788"))
    view = dict(item_id="probe", prompt="code?", options=[
        dict(option_id="yes", tokens=["CODE7788"], envelope=dict(type="entity", value="CODE7788", confidence_milli=1000)),
        dict(option_id="unknown", tokens=[], envelope=dict(type="unknown", value=None, confidence_milli=0))])
    keys = dict(canary=CANARY, item_id="probe", life="t0-pack", branch="B0", recall_query="code7788",
                required=["CODE7788"], oracle_spans=["e1"], forbidden=[], competing=[])
    assert host.settle(5)
    blocks = host.probe(task("code7788"), 100)
    count = len(calls(host))
    result = read_api(host, view, keys, 100, injected=blocks)
    assert result.selected_option == "yes" and result.recall["hits"] == 1
    assert len(calls(host)) == count
    assert blocks[-1] == "prefetched context"


def test_event_rules_and_character_cut(factory):
    host = factory(max_length=4000)
    host.ingest(event(text=""))
    assert host._worker is None
    host.ingest(event(2))
    count = len(calls(host))
    host.ingest(event(2))
    assert len(calls(host)) == count
    with pytest.raises(ValueError, match="conflicting event_id"):
        host.ingest(event(2, "changed"))
    for result in (dict(event_id="bad", t_sim=3, kind="tool_result", actor="tool", text="x", call_id="e2"),
                   dict(event_id="bad", t_sim=0, kind="tool_result", actor="tool", text="x", call_id="e4")):
        with pytest.raises(ValueError):
            host.ingest(result)
    host.ingest(dict(event_id="e4", t_sim=4, kind="tool_call", actor="tool", text="dispatch"))
    host.ingest(dict(event_id="e5", t_sim=5, kind="tool_result", actor="tool", text="delivered", call_id="e4"))
    host.forget(dict(event_ids=["e4"]))
    assert "e4" not in host.events and "e5" not in host.events
    text = '猫"\\\n' * 1100
    host.ingest(event(6, text))
    assert calls(host)[-1]["kwargs"]["content"] == text[:4000]
    assert host.events["e6"]["event"]["text"] == text
    for ids in ([""], [False], [1]):
        with pytest.raises(ValueError):
            host.forget(dict(event_ids=ids))


@pytest.fixture(params=["unit", "worker"])
def regression_host(request, factory, tmp_path, monkeypatch):
    """Run the same cases against stub tools directly and the file worker."""
    def make(name="hermes-native"):
        if request.param == "worker":
            return factory(name, mode="all_hits", max_length=4000)
        root = tmp_path / "unit-host"
        root.mkdir()
        surface, fresh = root / "surface", root / "fresh"
        surface.mkdir()
        (surface / plugin_host.MARKER).touch()
        shutil.copytree(surface, fresh)
        checkout = write_tree(root / "stub", log=root / "calls.jsonl", mode="all_hits", max_length=4000)
        stub = runpy.run_path(str(checkout / "_stub.py"))
        # The unit double writes only to the test's declared surface.
        stub["tool"].__globals__["path"] = lambda: surface / "stub_store.json"
        host = HermesMemoryHost.__new__(HermesMemoryHost)
        host.name, host.entry = name, load(REGISTRY / f"{name}.toml")
        host.events, host.session, host.turn, host.forget_ambiguous = {}, 1, 0, 0
        host.write_clipped, host.write_max_length = 0, None
        host._worker, host.settled, host._blocks, host._cache = None, True, (), None
        host.paths = dict(hermes_home=surface)
        host._surfaces = [(surface, [])]
        host._fresh = [(fresh, plugin_host.surface_hash(surface, []), host._listing(0))]
        host.clock, host.sim_epoch_s = SimClock(root / "clock.json", BASE, 60), BASE

        def start():
            host.schemas = [stub["schema"](plugin_host.WRITE_ARGS[name][0])]

        def call(kind, **args):
            host._start()
            if kind == "ingest":
                write = args["write"]
                return dict(result=stub["tool"](write["name"], write["arguments"]))
            if kind == "query":
                recall = args["recall"]
                return dict(recall=stub["tool"](recall["name"], recall["arguments"]), prefetch="")
            assert kind == "tool"
            return dict(result=stub["tool"](args["name"], args["arguments"]))

        monkeypatch.setattr(host, "_start", start)
        monkeypatch.setattr(host, "_call", call)
        return host
    return make


def stub_rows(host):
    """The stub's rows, read from whichever declared surface holds its store (mem0-oss uses SANDBOX_HOME)."""
    [store] = [d / "stub_store.json" for d, _ in host.surfaces() if (d / "stub_store.json").is_file()]
    return json.loads(store.read_text())


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("clipped", [False, True])
def test_forget_keeps_identical_unselected_owner(regression_host, monkeypatch, name, clipped):
    host = regression_host(name)
    text = "quartz " + "x" * 3993 if clipped else "quartz"
    host.ingest(event(1, text + "a" if clipped else text))
    host.ingest(event(2, text + "b" if clipped else text))
    tool_calls, real = [], host._call

    def call(kind, **args):
        if kind == "tool":
            tool_calls.append(args)
        return real(kind, **args)

    monkeypatch.setattr(host, "_call", call)
    host.forget(dict(event_ids=["e1"]))
    assert host.settle(5)
    rows = stub_rows(host)
    assert [r["text"] for r in rows] == [text]
    assert host.query(task("quartz"), 100) == answer([event(2, text)])
    assert host.forget_ambiguous == 1
    if name == "hermes-native":
        assert tool_calls == []


@pytest.mark.parametrize("name", NAMES[1:])
@pytest.mark.parametrize("selected,remaining", [(["e1", "e3"], 1), (["e1"], 2)])
def test_forget_identical_rows_once_per_text(regression_host, monkeypatch, name, selected, remaining):
    host = regression_host(name)
    for i in range(1, 4):
        host.ingest(event(i))
    searches, deletes, real = [], [], host._call

    def call(kind, **args):
        if kind == "tool":
            (searches if "query" in args["arguments"] else deletes).append(args)
        return real(kind, **args)

    monkeypatch.setattr(host, "_call", call)
    host.forget(dict(event_ids=selected))
    assert host.settle(5)
    rows = stub_rows(host)
    assert [r["seq"] for r in rows] == ([3] if remaining == 1 else [2, 3])
    assert [r["text"] for r in rows] == ["quartz"] * remaining
    # The second search returns only rows the first pass already decided, so it deletes and counts nothing.
    assert len(searches) == 2 and len(deletes) == 3 - remaining
    assert host.forget_ambiguous == remaining
    assert host.query(task("quartz"), 100) == answer(
        [event(i) for i in (3, 2, 1) if f"e{i}" not in selected])


@pytest.mark.parametrize("name", NAMES)
def test_query_cites_written_prefix(regression_host, name):
    host = regression_host(name)
    text = "quartz " * 600
    host.ingest(event(text=text))
    assert host.settle(5)
    assert host.query(task("quartz"), 100) == answer([event(text=text[:4000])])
    assert host.write_clipped == 1
    assert host.events["e1"]["event"]["text"] == text


def test_query_uses_written_maximal_text_and_order(regression_host, monkeypatch):
    host = regression_host()
    texts = ["quartz", "new quartz", "topaz"]
    # Distinct suffixes: filtering or sorting on the unwritten text would keep e1 or put e3 first.
    host.events = {f"e{i}": dict(event=event(i, f"{text} suffix {i}"), written=text, session=1)
                   for i, text in enumerate(texts, 1)}
    monkeypatch.setattr(host, "_call", lambda *a, **kw: dict(
        recall=json.dumps(dict(results=["new quartz", "topaz"])), prefetch=""))
    assert host.query(task(), 100) == answer([event(2, "new quartz"), event(3, "topaz")])
    assert [r["event"]["text"] for r in host.events.values()] == [f"{text} suffix {i}" for i, text in enumerate(texts, 1)]


@pytest.mark.parametrize("name", NAMES[1:])
@pytest.mark.parametrize("count,page", [(3, 2), (12, 1)])  # twelve one-row pages need thirteen searches
def test_forget_searches_again_past_a_full_page(regression_host, monkeypatch, name, count, page):
    host = regression_host(name)
    for i in range(1, count + 1):
        host.ingest(event(i))
    searches, real, listing = [], host._call, plugin_host.FORGET[name][3]

    def call(kind, **args):  # the backend returns at most `page` rows per search
        reply = real(kind, **args)
        if kind == "tool" and "query" in args["arguments"]:
            searches.append(args)
            result = json.loads(reply["result"])
            reply = dict(reply, result=json.dumps({**result, listing: result[listing][:page]}))
        return reply

    monkeypatch.setattr(host, "_call", call)
    host.forget(dict(event_ids=[f"e{i}" for i in range(1, count + 1)]))
    assert host.settle(5)
    assert stub_rows(host) == []
    assert len(searches) == -(-count // page) + 1 and host.forget_ambiguous == 0


@pytest.mark.parametrize("restore_first", [False, True])
def test_forget_removes_written_prefix(regression_host, restore_first):
    host = regression_host()
    text = "q" * 4001
    host.ingest(event(text=text))
    assert host.settle(5)
    if restore_first:
        host.restore(host.checkpoint())
    host.forget(dict(event_ids=["e1"]))
    assert host.settle(5)
    assert text[:4000].encode() not in host.checkpoint()
    for surface, _ in host.surfaces():
        assert all(text[:4000].encode() not in p.read_bytes() for p in surface.rglob("*") if p.is_file())


@pytest.mark.parametrize("selected", [1, 2])
def test_forget_respects_exact_hit_owner(regression_host, selected):
    host = regression_host("holographic")
    events = [event(1), event(2, "new quartz")]
    for e in events:
        host.ingest(e)
    host.forget(dict(event_ids=[f"e{selected}"]))
    assert host.settle(5)
    kept = events[2 - selected]
    rows = json.loads((host.surfaces()[0][0] / "stub_store.json").read_text())
    assert [r["text"] for r in rows] == [kept["text"]]
    assert host.query(task(kept["text"]), 100) == answer([kept])


@pytest.mark.parametrize("other,hit", [("quartz notes", "old quartz notes"),
                                       ("new quartz", "old new quartz notes")])
def test_forget_keeps_ambiguous_hit(regression_host, other, hit):
    host = regression_host("holographic")
    host.ingest(event())
    host.ingest(event(2, other))
    # Model a provider's merged fact without adding a host-owned event.
    host._call("tool", name="fact_store", arguments=dict(action="add", content=hit))
    host.forget(dict(event_ids=["e1"]))
    assert host.settle(5)
    rows = json.loads((host.surfaces()[0][0] / "stub_store.json").read_text())
    assert [r["text"] for r in rows] == [other, hit]
    assert host.forget_ambiguous == 1
    host.restore(host.checkpoint())
    assert host.forget_ambiguous == 0
    host.forget_ambiguous = 3
    host.reset()
    assert host.forget_ambiguous == 0 and host.events == {}


@pytest.mark.parametrize("failure", ["gate", "call"])
def test_ingest_retry_after_failed_write(regression_host, monkeypatch, failure):
    host = regression_host()
    method = "_start" if failure == "gate" else "_call"
    real = getattr(host, method)

    def fail_once(*args, **kwargs):
        monkeypatch.setattr(host, method, real)
        raise GateRefused("one refusal") if failure == "gate" else HarnessFailed("ingest_failed")

    monkeypatch.setattr(host, method, fail_once)
    with pytest.raises(GateRefused if failure == "gate" else HarnessFailed):
        host.ingest(event())
    assert "e1" not in host.events
    assert host.write_clipped == 0
    host.ingest(event())
    assert host.write_clipped == 0
    assert host.settle(5)
    assert host.query(task(), 100) == answer([event()])
    monkeypatch.setattr(host, method, fail_once)
    with pytest.raises(GateRefused if failure == "gate" else HarnessFailed):
        host.ingest(event(2, "q" * 4001))
    assert "e2" not in host.events and host.write_clipped == 0
    host.ingest(event(2, "q" * 4001))
    assert host.write_clipped == 1


def test_decoded_quotes_corpus_order_and_time(factory, monkeypatch):
    host = factory()
    for i, text in ((1, '猫 "quoted"'), (2, "later"), (3, "future")):
        host.ingest(event(i, text))
    assert host.settle(5)
    real = host._call

    def call(name, **args):
        if name == "query":
            return dict(recall=json.dumps(dict(ignored_key="later", nested=['猫 "quoted"', "future"])), prefetch="injected")
        return real(name, **args)

    monkeypatch.setattr(host, "_call", call)
    result = host.query(task("anything", oracle_evidence=["e3"]), 2)
    assert result["citations"] == ["e2", "e1"]
    assert host.context_blocks() == ('later\n猫 "quoted"\nfuture', "injected")
    assert host.settle(5)
    host.entry = dict(host.entry, recall=None)
    assert host.query(task(), 100) == answer([]) and host.context_blocks() == ()


@pytest.mark.parametrize("snapshot", [None, "", "snapshot quartz"])
@pytest.mark.parametrize("with_recall", [False, True])
def test_snapshot_context_first_without_citations(tmp_path, monkeypatch, snapshot, with_recall):
    host = HermesMemoryHost.__new__(HermesMemoryHost)
    host.entry = load(REGISTRY / "hermes-native.toml")
    host.settled, host._cache, host._blocks = True, None, ()
    host.clock, host.sim_epoch_s = SimClock(tmp_path / "clock.json", BASE, 60), BASE
    host.events = {f"e{i}": dict(event=event(i, text), session=1)
                   for i, text in enumerate(("quartz", "topaz"), 1)}
    reply = dict(recall=json.dumps(dict(results=["topaz"] if with_recall else [])),
                 prefetch="prefetched quartz" if with_recall else "")
    if snapshot is not None:
        reply["snapshot"] = snapshot
    monkeypatch.setattr(host, "_call", lambda *args, **kwargs: reply)
    assert host.query(task(), 100) == answer([event(2, "topaz")] if with_recall else [])
    expected = ((snapshot,) if snapshot else ()) + (("topaz", "prefetched quartz") if with_recall else ())
    assert host.context_blocks() == expected


def test_seeded_json_escape_property():
    rng = random.Random(16)
    for _ in range(50):
        value = "".join(rng.choices('abc猫"\\\n\t', k=30))
        assert plugin_host._corpus(json.dumps({"skip this key": [value, {"skip": value}]})) == value + "\n" + value
    assert plugin_host._corpus("not JSON") == "not JSON"


@pytest.mark.parametrize("texts,leaves,expected", [
    (["quartz", "new quartz"], ["new quartz"], [2]),
    (["quartz", "topaz"], ["quartz and topaz"], [1, 2]),
    (["quartz", "new quartz"], ["quartz", "new quartz"], [1, 2]),
    (["quartz\ntopaz"], ["quartz", "topaz"], []),
    (["quartz", "quartz"], ["quartz"], [2, 1]),
    (["quartz", "new quartz", "brand new quartz"], ["brand new quartz"], [3]),
])
def test_citations_use_maximal_texts_per_leaf(factory, monkeypatch, texts, leaves, expected):
    host = factory()
    events = [event(i, text) for i, text in enumerate(texts, 1)]
    host.events = {e["event_id"]: dict(event=e, session=1) for e in events}
    monkeypatch.setattr(host, "_call", lambda *a, **kw: dict(recall=json.dumps(dict(results=leaves)), prefetch=""))
    result = host.query(task(), 100)
    assert result == answer([events[i - 1] for i in expected])
    assert host.context_blocks() == ("\n".join(leaves),)


def test_native_live_worker_settle_zero(factory):
    host = factory()
    assert host.entry["settle"] == dict(kind="none", bound_s=0)
    host.ingest(event())
    assert host._worker is not None
    assert host.settle(0) is True


@pytest.mark.parametrize("kind,bound,drained,threads,expected", [
    ("none", 0, True, [], True),
    ("none", 5, True, [], True),
    ("hook", 0, True, [], True),
    ("hook", 0, False, [], False),
    ("none", 0, True, ["mem0-sync"], False),
])
def test_single_drain_observation(kind, bound, drained, threads, expected):
    host = HermesMemoryHost.__new__(HermesMemoryHost)
    host.entry, host.name, host._worker = dict(settle=dict(kind=kind)), "mem0-oss", object()
    observed = []

    def call(name, **args):
        observed.append((name, args))
        return dict(drained=drained, threads=threads)

    host._call = call
    assert host.settle(bound) is expected
    assert host.settled is expected
    assert observed == [("drain", dict(timeout_ms=200))]


def test_forget_waits_for_delayed_sync(factory):
    host = factory("mem0-oss", mode="delayed_sync", sync_ms=500)
    token = "DELAYEDMEM0TOKEN7788"
    host.ingest(event(text=token))
    assert not any(c["name"] == "sync_landed" for c in calls(host))
    host.forget(dict(event_ids=["e1"]))
    assert host.settle(5)
    assert token.encode() not in host.checkpoint()
    history = calls(host)
    landed = next(i for i, c in enumerate(history) if c["name"] == "sync_landed")
    searched = next(i for i, c in enumerate(history) if c["name"] == "handle_tool_call" and c["args"][0] == "mem0_search")
    assert landed < searched
    assert any(c["name"] == "handle_tool_call" and c["args"][0] == "mem0_delete" for c in history)
    assert host.query(task(token), 100) == answer([])


@pytest.mark.parametrize("declared_bound", [0, 2])
def test_forget_unsettled_refuses_search(monkeypatch, declared_bound):
    host = HermesMemoryHost.__new__(HermesMemoryHost)
    host.entry = dict(settle=dict(kind="none" if declared_bound == 0 else "hook", bound_s=declared_bound))
    host.name, host._worker, host.settled, host._cache = "mem0-oss", object(), True, object()
    host.events = {"e1": dict(event=event(), session=1)}
    observed = []

    def call(name, **args):
        assert name == "drain", "forget searched or deleted before draining"
        observed.append(args)
        return dict(drained=False, threads=[])

    def timed_settle(entry, observe):
        assert entry["settle"] == dict(kind="hook", bound_s=declared_bound or 5)
        ticks = iter([0, declared_bound or 5])
        return real_settle(entry, observe, monotonic=lambda: next(ticks))

    real_settle = plugin_host.settle
    host._call = call
    monkeypatch.setattr(plugin_host, "settle", timed_settle)
    with pytest.raises(HarnessFailed, match="^forget_unsettled$"):
        host.forget(dict(event_ids=["e1"]))
    assert observed == [dict(timeout_ms=200)]
    assert "e1" in host.events and host.settled is False and host._cache is None


@pytest.mark.parametrize("sync_ms,bound,expected", [(1500, 5, True), (8000, 1, False)])
def test_mem0_settle(factory, sync_ms, bound, expected):
    host = factory("mem0-oss", sync_ms=sync_ms)
    host.ingest(event())
    assert host.settle(bound) is expected
    if not expected:
        with pytest.raises(RuntimeError):
            host.query(task(), 100)


def test_refusals_before_server(tmp_path, monkeypatch):
    def forbidden(*args, **kw):
        pytest.fail("a refusal started a server")

    monkeypatch.setattr(plugin_host, "serve", forbidden)
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    for name, expected in (("lcm-x", "benchmark_operator_forbidden"), ("no-memory", "harness_not_hermes")):
        entry = load(REGISTRY / f"{name}.toml")
        with pytest.raises(SystemRefused) as refused:
            HermesMemoryHost(entry, route_table=None, responder=None, clock=None, root=tmp_path / name,
                             scratch=tmp_path, life="t0", branch="B0", run="refused", lock_hash=LOCK)
        assert expected in refused.value.reasons
        if name == "lcm-x":
            assert list(refused.value.reasons) == [expected]
    other = dict(load(REGISTRY / "hermes-native.toml"), name="other")
    with pytest.raises(ValueError, match="no T0 mapping"):
        HermesMemoryHost(other, route_table=None, responder=None, clock=None, root=tmp_path / "other",
                         scratch=tmp_path, life="t0", branch="B0", run="refused", lock_hash=LOCK)


def test_source_missing_and_plugin_inactive(factory):
    with pytest.raises(ValueError, match="plugin_source"):
        factory("holographic", plugin_source=None)
    host = factory("holographic", mode="missing")
    with pytest.raises(HarnessFailed, match="^plugin_inactive$"):
        host.ingest(event())


def test_busy_marker_no_pid(factory, monkeypatch):
    host = factory()
    cmd = shlex.join([sys.executable, "-c", 'import sys; print(\'{"state":"busy"}\'); sys.exit(11)'])
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", cmd)
    with pytest.raises(GateRefused):
        host.ingest(event())
    assert host.pids == [] and host._worker is None
    assert host.gate == [dict(exit=11, state="busy")]


def test_boundaries():
    paths = [Path(plugin_host.__file__), WORKER]
    forbidden = {"socket", "http", "urllib", "requests"}
    for path in paths:
        text = path.read_text()
        assert "lcm" not in text.casefold()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert (node.module or "").split(".")[0] not in forbidden
    worker_text = WORKER.read_text()
    assert "bicentennial" not in worker_text
    modules = []
    for node in ast.parse(worker_text).body:
        if isinstance(node, ast.Import):
            modules.extend(a.name for a in node.names)
        assert not isinstance(node, ast.ImportFrom)
    assert modules == ["json", "os", "sys", "time"]


def test_pids_egress_and_serialized_types(factory):
    host = factory()
    host.ingest(event())
    for pid in host.pids:
        assert_niced(pid)
    assert host.settle(5)
    for value in (host.query(task(), 100), host.stats(), host.harness_record()):
        no_float(value)
        canon(value)
    assert host.harness_record()["entrypoint"] == "test-double"
    assert all(isinstance(path, Path) for path, _ in host.surfaces())
    if not shutil.which("lsof"):
        pytest.skip("lsof absent; egress sampling unavailable")
    host.egress.sample()
    assert host.egress.summary()["non_loopback"] == []


@pytest.mark.parametrize("name", NAMES)
def test_live(factory, name, capsys):
    if name != "hermes-native":
        pytest.skip("plug-in live runs need the pinned plug-in sources; X03 runs them")
    checkout = os.environ.get("BICENTENNIAL_HERMES")
    if not checkout:
        pytest.skip("BICENTENNIAL_HERMES unset")
    checkout = Path(checkout)
    if not (checkout / ".venv/bin/python").exists():
        pytest.skip("pinned Hermes interpreter absent")
    verify_pin(checkout, load(REGISTRY / "hermes-native.toml")["artifact"])
    try:
        # Refuse immediately if the actual machine marker cannot admit this live run.
        live_host = factory(live=checkout)
        live_host._start()
    except GateRefused:
        pytest.skip("machine gate refused")
    matrix = conformance.run(lambda: factory(live=checkout))
    report(capsys, dict(system=name, live_conformance=matrix,
                        declared=conformance.declared(lambda: factory(live=checkout))))
    for check in ("reset_empty", "citations_are_event_ids", "checkpoint_restore", "settle_returns"):
        assert matrix[check], check
    results = []
    for run in (1, 2):
        start = time.monotonic()
        host = factory(live=checkout)
        results.append(pack(host, strict=False))
        elapsed_ms = int((time.monotonic() - start) * 1000)
        report(capsys, dict(system=name, live_pack=run, elapsed_ms=elapsed_ms, answers=results[-1][0]))
        assert elapsed_ms <= 60_000
    assert canon(results[0][0]) == canon(results[1][0])


def test_native_session_start_snapshot_live(factory):
    checkout = os.environ.get("BICENTENNIAL_HERMES")
    if not checkout:
        pytest.skip("BICENTENNIAL_HERMES unset")
    checkout = Path(checkout)
    if not (checkout / ".venv/bin/python").exists():
        pytest.skip("pinned Hermes interpreter absent")
    verify_pin(checkout, load(REGISTRY / "hermes-native.toml")["artifact"])
    try:
        host = factory(live=checkout)
        host._start()
    except GateRefused:
        pytest.skip("machine gate refused")
    fact, prompt = "Amber flute token ZEPHYR9284", "meteor harbor sequence"
    host.ingest(event(text=fact))
    assert host.settle(5)
    assert host.query(task(prompt), 100) == answer([])
    assert all(fact not in block for block in host.context_blocks())
    assert host.settle(5)
    host.begin_session(2)
    assert host.query(task(prompt), 200) == answer([])
    snapshot = host.context_blocks()[0]
    assert fact in snapshot
    # Later writes cannot alter the already opened session's snapshot.
    host.ingest(event(201, "Cobalt violin code LANTERN4632"))
    assert host.settle(5)
    assert host.query(task(prompt), 300) == answer([])
    assert host.context_blocks()[0] == snapshot


@pytest.mark.parametrize("name", tuple(plugin_host.PROVIDERS))
def test_fresh_install_hash_matches_cell_across_ports(factory, monkeypatch, name):
    installed = []
    original = plugin_host.PluginCell.install

    def install(cell, *args, **kwargs):
        result = original(cell, *args, **kwargs)
        installed.append(cell.fresh_install_hash)
        return result

    monkeypatch.setattr(plugin_host.PluginCell, "install", install)
    first, second = factory(name), factory(name)
    assert first.server.port != second.server.port
    assert installed == [first.fresh_install_hash, second.fresh_install_hash]
    assert first.fresh_install_hash == second.fresh_install_hash
    for host in (first, second):
        for (directory, volatile), (_, digest, _) in zip(host.surfaces(), host._fresh, strict=True):
            assert digest == plugin_host.surface_hash(directory, volatile)
