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

from bicentennial.harness.hermes.plugin_host import FORGET
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
        def __init__(self, db_path):
            assert Path(os.environ["OMEGA_HOME"]) == home / "plugin-data/omega"
            self.db = sqlite3.connect(db_path)
            self.db.execute("CREATE TABLE memories(id INTEGER PRIMARY KEY, node_id TEXT, content TEXT)")
            self.db.execute("CREATE TABLE forgetting_log(preview TEXT)")
            class Joined(threading.Thread):
                def join(self):
                    super().join()
                    self.joined = True
            self._deferred_thread = Joined(target=self._deferred_startup)
            self._deferred_thread.start()

        def _deferred_startup(self):
            raise AssertionError("upstream deferred work must not run")

        def store(self, content, **kwargs):
            assert kwargs == {"session_id": "s1"}  # inference/supersession retain defaults
            row = self.db.execute("SELECT node_id FROM memories WHERE content=?", (content,)).fetchone()
            if row:
                return row[0]
            rid = self.db.execute("SELECT COUNT(*) FROM memories").fetchone()[0] * 41 + 41
            node = f"opaque-uuid-{rid}"
            self.db.execute("INSERT INTO memories VALUES (?, ?, ?)", (rid, node, content))
            self.db.commit()
            return node

        def query(self, query, **kwargs):
            assert kwargs == dict(limit=7 if query == "ordered" else 10,
                                  use_cache=False, expand_query=False, rerank=False)
            return [NS(id=n, content=c, relevance=0.123) for n, c in
                    self.db.execute("SELECT node_id, content FROM memories ORDER BY id DESC")]

        def delete_node(self, node):
            content = self.db.execute("SELECT content FROM memories WHERE node_id=?", (node,)).fetchone()[0]
            self.db.execute("INSERT INTO forgetting_log VALUES (?)", (content[:200],))
            self.db.execute("DELETE FROM memories WHERE node_id=?", (node,))
            self.db.commit()
            return True

        def close(self):
            self.db.close()

    omega, store_module = ModuleType("omega"), ModuleType("omega.sqlite_store")
    omega.embedding, store_module.SQLiteStore = embedding, Store
    monkeypatch.setitem(sys.modules, "omega", omega)
    monkeypatch.setitem(sys.modules, "omega.sqlite_store", store_module)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "omega" or name.startswith("omega."):
            assert Path(os.environ["OMEGA_HOME"]) == home / "plugin-data/omega"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setenv("OMEGA_HOME", "must-be-replaced")
    yield p, home, cache, embedding
    p.shutdown()


def test_provider_round_trip(provider):
    p, home, cache, _ = provider
    assert p.is_available() and os.environ["OMEGA_HOME"] == "must-be-replaced"
    p.initialize("s1", hermes_home=home)
    assert p.store._deferred_thread.joined and not p.store._deferred_thread.is_alive()
    assert p.store._deferred_startup_done
    def call(name, **args):
        return json.loads(p.handle_tool_call("omega_" + name, args))
    text = "synthetic head " + "猫 payload " * 8192 + " TAIL_TOKEN"
    assert call("store", content=text) == call("store", content=text) == {"id": 41}
    assert call("store", content="second") == {"id": 82}
    assert call("query", query="ordered", limit=7) == {"results": [
        {"id": 82, "content": "second"}, {"id": 41, "content": text}]}
    assert call("delete", memory_id=82) == {"deleted": True}
    assert call("delete", memory_id=82) == {"deleted": False}
    assert p.store.db.execute("SELECT preview FROM forgetting_log").fetchall() == [("second",)]
    with pytest.raises(ValueError, match="integer rowid"):
        call("delete", memory_id="opaque-uuid-41")
    with pytest.raises(RuntimeError, match="missing memory"):
        p._rowid("missing")
    p.sync_turn("unstored", "unstored")
    assert p.prefetch("prompt") == ""
    assert call("query", query="TAIL_TOKEN") == {"results": [{"id": 41, "content": text}]}
    schemas = [{k: s[k] for k in ("name", "parameters")} for s in p.get_tool_schemas()]
    assert schemas == json.loads((ROOT / "tests/fixtures/systems/tool-schemas.json").read_bytes())["tools"]["omega"]
    assert all(f.is_relative_to(home) or f.is_relative_to(cache) for f in home.parent.rglob("*") if f.is_file())


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


def test_worker_recipe():
    assert hp.PROVIDERS["omega"] == "omega"
    assert FORGET["omega"] == ("omega_query", {}, "query", "results", "content", "id",
                               "omega_delete", {}, "memory_id")
    assert hp.resolve_worker_env("omega") == {
        "OMEGA_ONNX_MODEL_DIR": "{model_cache}/bge-small-en-v1.5-onnx", "OMEGA_ONNX_THREADS": "1",
        "OMEGA_QUERY_EXPANSION": "0", "OMEGA_CROSS_ENCODER": "0", "OMEGA_RERANKER_AUTODOWNLOAD": "0"}


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
