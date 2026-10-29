"""OMEGA boundary tests: synthetic modules only, never import the vendor package."""

import builtins
import io
import json
import os
import runpy
import sqlite3
import sys
import threading
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace as NS

import pytest

from bicentennial.harness.hermes.plugin_host import FORGET, SETTLE_THREADS
from bicentennial.systems import hermes_plugin as hp

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def provider(tmp_path, monkeypatch):
    base = ModuleType("agent.memory_provider")
    base.MemoryProvider = object
    monkeypatch.setitem(sys.modules, "agent", ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.memory_provider", base)
    module = runpy.run_path(str(ROOT / "adapters/hermes-plugin-omega/__init__.py"))
    p = module["OmegaProvider"]()
    ctx = NS(register_memory_provider=lambda value: setattr(ctx, "provider", value))
    module["register"](ctx)
    assert ctx.provider.name == "omega"
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("model.onnx", "tokenizer.json"):
        (cache / name).write_bytes(b"synthetic model")
    monkeypatch.setenv("OMEGA_ONNX_MODEL_DIR", str(cache))
    monkeypatch.setitem(sys.modules, "onnxruntime", ModuleType("onnxruntime"))
    home = tmp_path / "hermes"
    embedding = NS(preload_embedding_model=lambda: True, get_active_backend=lambda: "onnx")

    class Store:
        def type_stats(self):
            assert embedding.get_active_backend() == "onnx"
            self.stats_calls += 1
            assert Path(os.environ["OMEGA_HOME"]) == home / "plugin-data/omega"
            self.db = sqlite3.connect(home / "plugin-data/omega/omega.db", check_same_thread=False)
            self.db.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, node_id TEXT, content TEXT)")
            self.db.execute("CREATE TABLE forgetting_log(preview TEXT)")
            self.thread = NS(name="omega-deferred-init", alive=True)
            self.thread.join = lambda: setattr(self.thread, "alive", False)
            monkeypatch.setattr(threading, "enumerate",
                                lambda: [self.thread, NS(name="unrelated"), *(r for r in self.relates if r.alive)])

        def store(self, content, **kwargs):
            assert kwargs == {"session_id": "s1"}  # inference/supersession retain defaults
            self.events.append("store")
            relate = NS(name="auto-relate", alive=True)
            relate.is_alive = lambda: relate.alive

            def join(timeout=None):
                relate.alive = self.stuck  # a stuck relate outlives the wait
                self.events.append(f"join {timeout}")
            relate.join = join
            self.relates.append(relate)
            row = self.db.execute("SELECT node_id FROM memories WHERE content=?", (content,)).fetchone()
            if row:
                return f"Deduped → {row[0]}"
            rid = self.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] * 41 + 41
            node = f"mem-{rid:012x}"
            self.db.execute("INSERT INTO memories VALUES (?, ?, ?)", (rid, node, content))
            self.db.commit()
            return self.reply or f"Stored {node} (memory, 90 days)"

        def query(self, query, **kwargs):
            self.queries.append((query, kwargs))
            assert kwargs == dict(limit=7 if query == "ordered" else 10)
            return [dict(id=n, content=c, is_constraint=True, is_preference=True) for n, c in
                    self.db.execute("SELECT node_id, content FROM memories ORDER BY id DESC")]

        def delete_node(self, node):
            self.deleted.append(node)
            content = self.db.execute("SELECT content FROM memories WHERE node_id=?", (node,)).fetchone()[0]
            self.db.execute("INSERT INTO forgetting_log VALUES (?)", (content[:200],))
            self.db.execute("DELETE FROM memories WHERE node_id=?", (node,))
            self.db.commit()
            return {"success": self.success}

        def close(self):
            self.resets += 1
            self.db.close()

    api = embedding.api = Store()
    api.stats_calls, api.resets, api.reply, api.deleted, api.success = 0, 0, None, [], True
    api.queries, api.relates, api.events, api.stuck = [], [], [], False
    omega, bridge = ModuleType("omega"), ModuleType("omega.bridge")
    omega.embedding, omega.type_stats, omega.store = embedding, api.type_stats, api.store
    omega.query_structured, omega.delete_memory, bridge.reset_memory = api.query, api.delete_node, api.close
    monkeypatch.setitem(sys.modules, "omega", omega)
    monkeypatch.setitem(sys.modules, "omega.bridge", bridge)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert name != "omega.sqlite_store"
        if name == "omega" or name.startswith("omega."):
            assert Path(os.environ["OMEGA_HOME"]) == home / "plugin-data/omega"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setenv("OMEGA_HOME", "must-be-replaced")
    yield p, home, cache, embedding
    p.shutdown()


def test_provider_round_trip(provider):
    p, home, cache, embedding = provider
    api = embedding.api
    p.shutdown()
    assert api.resets == 0
    assert p.is_available() and os.environ["OMEGA_HOME"] == "must-be-replaced"
    p.initialize("s1", hermes_home=home)
    assert api.stats_calls == 1 and not api.thread.alive
    def call(name, **args):
        return json.loads(p.handle_tool_call("omega_" + name, args))
    text = "synthetic head " + "猫 payload " * 8192 + " TAIL_TOKEN"
    assert call("store", content=text) == {"id": 41, "outcome": "stored"}
    assert call("store", content=text) == {"id": 41, "outcome": "deduped"}
    assert call("store", content="second") == {"id": 82, "outcome": "stored"}
    assert call("query", query="ordered", limit=7) == {"results": [
        {"id": 82, "content": "second"}, {"id": 41, "content": text}]}
    assert call("delete", memory_id=82) == {"deleted": True}
    assert call("delete", memory_id=82) == {"deleted": False}
    assert api.deleted == ["mem-000000000052"]
    assert api.db.execute("SELECT preview FROM forgetting_log").fetchall() == [("second",)]
    with pytest.raises(ValueError, match="integer rowid"):
        call("delete", memory_id="opaque-uuid-41")
    with pytest.raises(RuntimeError, match="missing memory"):
        p._rowid("missing")
    p.sync_turn("unstored", "unstored")
    assert p.prefetch("prompt") == ""
    assert call("query", query="TAIL_TOKEN") == {"results": [{"id": 41, "content": text}]}
    assert api.queries == [("ordered", {"limit": 7}), ("TAIL_TOKEN", {"limit": 10})]
    schemas = [{k: s[k] for k in ("name", "parameters")} for s in p.get_tool_schemas()]
    assert schemas == json.loads((ROOT / "tests/fixtures/systems/tool-schemas.json").read_bytes())["tools"]["omega"]
    assert all(f.is_relative_to(home) or f.is_relative_to(cache) for f in home.parent.rglob("*") if f.is_file())
    p.shutdown()
    p.shutdown()
    assert api.resets == 1


@pytest.mark.parametrize("reply,outcome", [
    ("Reconfirmed mem-000000000029", "reconfirmed"), ("Evolved mem-000000000029 (#2)", "evolved"),
    ("Stored mem-000000000029 (memory, 90 days) | superseded mem-000000000052", "stored"),
    *[(f"**Memory Blocked** ({reason})", "blocked") for reason in ("system noise", "too short",
       "infrastructure noise", "zero-token outcome", "JSON blob, not a decision")],
    ("Blocked (error burst — duplicate)", "blocked"), ("unknown private text", None),
    ("Stored without id", None), ("Unexpected mem-000000000029", None)])
def test_store_forms(provider, reply, outcome):
    p, home, _, embedding = provider
    p.initialize("s1", hermes_home=home)
    embedding.api.reply = reply
    if outcome is None:
        with pytest.raises(RuntimeError, match="^unrecognized OMEGA store result$"):
            p.handle_tool_call("omega_store", {"content": "synthetic"})
    else:
        assert json.loads(p.handle_tool_call("omega_store", {"content": "synthetic"})) == {
            "id": None if outcome == "blocked" else 41, "outcome": outcome}


def test_store_waits_for_auto_relate(provider):
    p, home, _, embedding = provider
    p.initialize("s1", hermes_home=home)
    for content in ("first", "first", "second"):  # a dedup starts auto-relate too
        p.handle_tool_call("omega_store", {"content": content})
    assert embedding.api.events == ["store", "join 30"] * 3


def test_a_running_relate_refuses_calls_before_omega(provider):
    p, home, _, embedding = provider
    api = embedding.api
    p.initialize("s1", hermes_home=home)

    def manager(name, args):  # Hermes's MemoryManager.handle_tool_call returns provider errors as tool errors
        try:
            return json.loads(p.handle_tool_call(name, args))
        except Exception as e:
            return {"error": f"Memory tool '{name}' failed: {e}"}
    api.stuck = True  # the relate outlives every wait
    assert manager("omega_store", {"content": "first"}) == {"id": 41, "outcome": "stored"}
    for name, args in (("omega_store", {"content": "second"}), ("omega_query", {"query": "first"}),
                       ("omega_delete", {"memory_id": 41})):
        assert manager(name, args) == {"error": f"Memory tool '{name}' failed: "
                                      "OMEGA's auto-relate is still running after 30 s; call refused"}
    assert api.events == ["store"] + ["join 30"] * 4
    assert api.queries == [] and api.deleted == []
    assert api.db.execute("SELECT content FROM memories").fetchall() == [("first",)]
    api.stuck = False  # once the relate finishes, calls reach OMEGA again
    assert manager("omega_store", {"content": "second"}) == {"id": 82, "outcome": "stored"}
    assert api.events[5:] == ["join 30", "store", "join 30"]


def test_one_omega_call_at_a_time(provider, monkeypatch):
    p, home, _, embedding = provider
    api = embedding.api
    p.initialize("s1", hermes_home=home)
    monkeypatch.setitem(type(p).handle_tool_call.__globals__, "AUTO_RELATE_WAIT_S", 0.05)
    entered, release, store = threading.Event(), threading.Event(), p.store

    def abandoned_store(content, **kwargs):  # still inside OMEGA after Hermes gave up on the call
        entered.set()
        assert release.wait(5)
        return store(content, **kwargs)
    p.store = abandoned_store
    first = threading.Thread(target=p.handle_tool_call, args=("omega_store", {"content": "first"}))
    first.start()
    assert entered.wait(5)
    p.store = store
    with pytest.raises(RuntimeError, match="^another OMEGA call is still running after 0.05 s; call refused$"):
        p.handle_tool_call("omega_query", {"query": "first"})
    assert api.queries == [] and api.events == []
    release.set()
    first.join(5)
    assert api.events == ["store", "join 0.05"]
    assert json.loads(p.handle_tool_call("omega_query", {"query": "first"})) == {"results": [
        {"id": 41, "content": "first"}]}


def test_availability_and_backend_refusal(provider, monkeypatch):
    p, home, cache, embedding = provider
    (cache / "model.onnx").unlink()
    assert not p.is_available() and "model.onnx" in p.unavailable_reason()
    (cache / "model.onnx").write_bytes(b"synthetic")
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    assert not p.is_available() and "onnxruntime" in p.unavailable_reason()
    monkeypatch.setitem(sys.modules, "onnxruntime", ModuleType("onnxruntime"))
    embedding.get_active_backend = lambda: None
    with pytest.raises(RuntimeError, match="plugin_inactive"):
        p.initialize("s1", hermes_home=home)
    assert p.store is None and not p.is_available()
    assert embedding.api.stats_calls == 0


@pytest.mark.parametrize("success", [True, False, 1])
def test_delete_success_is_true(provider, success):
    p, home, _, embedding = provider
    p.initialize("s1", hermes_home=home)
    p.handle_tool_call("omega_store", {"content": "synthetic"})
    embedding.api.success = success
    assert json.loads(p.handle_tool_call("omega_delete", {"memory_id": 41})) == {"deleted": success is True}


def test_worker_recipe():
    assert hp.PROVIDERS["omega"] == "omega"
    assert SETTLE_THREADS["omega"] == hp.OMEGA_THREADS == ("auto-relate", "omega-deferred-init")
    assert FORGET["omega"] == ("omega_query", {}, "query", "results", "content", "id",
                               "omega_delete", {}, "memory_id")
    assert hp.resolve_worker_env("omega") == {
        "OMEGA_ONNX_MODEL_DIR": "{model_cache}/bge-small-en-v1.5-onnx", "OMEGA_ONNX_THREADS": "1",
        "OMEGA_QUERY_EXPANSION": "0", "OMEGA_CROSS_ENCODER": "0", "OMEGA_RERANKER_AUTODOWNLOAD": "0",
        "ORT_DISABLE_TELEMETRY": "1"}


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_preflight_settle_mapped(monkeypatch, tier):
    from bicentennial.runner import t0, t1
    from bicentennial.systems.registry import REGISTRY, load
    runner = t0 if tier == "t0" else t1
    entry = load(REGISTRY / "omega.toml")
    assert entry["settle"] == dict(kind="hook", bound_s=5)
    monkeypatch.setattr(runner, "admit_system", lambda *a: None)
    monkeypatch.setattr(runner, "prepare_cache", lambda *a: (None, None))
    monkeypatch.setattr(runner, "worker_properties", lambda *a: ())
    def reached():
        raise RuntimeError("past settle mapping")
    monkeypatch.setattr(runner, "read_marker", reached)
    with pytest.raises(RuntimeError, match="^past settle mapping$"):
        (t0._preflight if tier == "t0" else t1.prepare)(system="omega", entry=entry,
            packs="unused", pack_hash="unused", plugin_source="unused",
            **(dict(selected=["all"]) if tier == "t0" else dict(worker_argv=["fake"])))


def test_fidelity_docs():
    from bicentennial.director.scripted import stub_disclosures
    readme = (ROOT / "adapters/hermes-plugin-omega/README.md").read_text()
    assert [line.split("`")[1] for line in readme.splitlines() if line.startswith("| `omega.")] == [
        name for name, _ in stub_disclosures({"name": "omega"}, "t0")]
    guide = (ROOT / "docs/developers/ring0.md").read_text().split("**OMEGA prep.**")[1].split("\n\n")[0]
    assert "benchmark-authored adapter" in guide
    assert "The registry entry's comments name the adapter commit each pin was measured at." in guide


def test_prep_offline(tmp_path, monkeypatch, capsys):
    prep = runpy.run_path(str(ROOT / "scripts/prepare_omega.py"))
    stage, main = prep["stage"], prep["main"]
    assert prep["REVISION"] == "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
    assert len(prep["FILES"]) == 4 and prep["FILES"]["model.onnx"][0] == "onnx/model.onnx"
    urls = []
    monkeypatch.setattr(prep["urllib"].request, "urlopen",
        lambda url, **kw: (urls.append(url) or io.BytesIO(b"synthetic")))
    monkeypatch.setitem(stage.__globals__, "FILES", {n: (r, sha256(b"synthetic").hexdigest())
                                                   for n, (r, _) in prep["FILES"].items()})
    cache = tmp_path / "models"
    main(["--model-cache", str(cache), "--hermes-source", "source", "--hermes", "dedicated",
          "--plugin-source", "detached", "--commit-a", "a" * 40])
    output = capsys.readouterr().out
    assert "--require-hashes" in output and "uv sync --frozen --extra mcp" in output
    assert "worktree add --detach detached " + "a" * 40 in output
    assert all("-u " + name in output for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"))
    assert len(urls) == 4 and all("/resolve/" + prep["REVISION"] + "/" in u for u in urls)
    stage(cache)
    assert len(urls) == 4
    (cache / "bge-small-en-v1.5-onnx/model.onnx").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        stage(cache)
    (cache / "link").symlink_to(tmp_path)
    with pytest.raises(ValueError, match="symlinks"):
        stage(cache)
