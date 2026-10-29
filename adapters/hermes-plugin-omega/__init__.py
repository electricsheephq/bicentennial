"""Benchmark-authored Apache-2.0 Hermes provider; OMEGA loads only in the worker."""

import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from agent.memory_provider import MemoryProvider


class OmegaProvider(MemoryProvider):
    name = "omega"

    def __init__(self):
        self.store = self.embedding = None
        self.reason = ""

    def is_available(self):
        # The worker calls this before initialize: never import OMEGA here.
        model = Path(os.environ.get("OMEGA_ONNX_MODEL_DIR", ""))
        if not all((model / f).is_file() for f in ("model.onnx", "tokenizer.json")):
            self.reason = "Pinned ONNX model.onnx and tokenizer.json are required"
            return False
        try:
            import onnxruntime  # noqa: F401
        except (ImportError, OSError):
            self.reason = "onnxruntime is required"
            return False
        if self.embedding is not None and self.embedding.get_active_backend() != "onnx":
            self.reason = "OMEGA ONNX backend is inactive"
            return False
        self.reason = ""
        return True

    def unavailable_reason(self):
        return self.reason

    def initialize(self, session_id, **kwargs):
        home = Path(kwargs["hermes_home"]).resolve() / "plugin-data/omega"
        home.mkdir(parents=True, exist_ok=True)
        os.environ["OMEGA_HOME"] = str(home)
        # omega.__init__ also imports bridge, whose OMEGA_HOME is import-time state.
        from omega import embedding
        from omega.sqlite_store import SQLiteStore

        self.embedding = embedding
        if not embedding.preload_embedding_model() or not self.is_available():
            raise RuntimeError("plugin_inactive: OMEGA ONNX backend is required")

        class ForegroundStore(SQLiteStore):
            def _deferred_startup(self):
                # No integrity/checkpoint/backup work; retain all normal store/delete behaviour.
                self._deferred_startup_done = True

        self.path, self.session_id = home / "omega.db", session_id
        self.store = ForegroundStore(db_path=self.path)
        # Upstream creates this no-op thread unconditionally. It cannot outlive initialization.
        self.store._deferred_thread.join()

    def _lookup(self, select, key, value):
        with closing(sqlite3.connect(self.path)) as db:
            row = db.execute(f"SELECT {select} FROM memories WHERE {key} = ?", (value,)).fetchone()
        return row[0] if row else None

    def get_tool_schemas(self):
        return [dict(name=name, description=description, parameters=dict(type="object",
                    properties=properties, required=required)) for name, description, properties, required in (
            ("omega_store", "Store a memory", {"content": {"type": "string"}}, ["content"]),
            ("omega_query", "Search memories", {"query": {"type": "string"},
                "limit": {"type": "integer", "default": 10, "minimum": 1}}, ["query"]),
            ("omega_delete", "Delete a memory", {"memory_id": {"type": "integer"}}, ["memory_id"]),
        )]

    def _rowid(self, node):
        rowid = self._lookup("rowid", "node_id", node)
        if type(rowid) is not int:
            raise RuntimeError("OMEGA returned a missing memory")
        return rowid

    def handle_tool_call(self, tool_name, args, **kwargs):
        if tool_name == "omega_store":
            node = self.store.store(args["content"], session_id=self.session_id)
            result = {"id": self._rowid(node)}
        elif tool_name == "omega_query":
            rows = self.store.query(args["query"], limit=args.get("limit", 10),
                                    use_cache=False, expand_query=False, rerank=False)
            result = {"results": [{"id": self._rowid(r.id),
                                   "content": r.content} for r in rows]}
        elif tool_name == "omega_delete":
            memory_id = args["memory_id"]
            if type(memory_id) is not int:
                raise ValueError("memory_id must be an integer rowid")
            node = self._lookup("node_id", "rowid", memory_id)
            result = {"deleted": bool(node is not None and self.store.delete_node(node))}
        else:
            raise ValueError("unknown OMEGA tool")
        return json.dumps(result, ensure_ascii=False)

    def sync_turn(self, user_content, assistant_content, **kwargs):
        pass  # Explicit writes only.

    def prefetch(self, query, *, session_id=""):
        return ""  # The shipped UserPromptSubmit hook captures; it does not query.

    def shutdown(self):
        if self.store is not None:
            self.store.close()
            self.store = None


def register(ctx):
    ctx.register_memory_provider(OmegaProvider())
