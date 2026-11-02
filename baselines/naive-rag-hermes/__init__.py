"""Apache-2.0 Hermes memory provider for the benchmark's developer baseline."""

import json
import threading

from agent.memory_provider import MemoryProvider

from .store import Store
from .tfidf import TOP_K, scored


def _text(args, key):
    """A string argument; anything else is refused before it can reach the store."""
    if type(args[key]) is not str:
        raise ValueError(f"{key} must be a string")
    return args[key]


class NaiveRagProvider(MemoryProvider):
    name = "naive-rag-dev"

    def __init__(self):
        self.store = None
        self.lock = threading.Lock()

    def is_available(self):
        return True

    def unavailable_reason(self):
        return ""

    def initialize(self, session_id, **kwargs):
        self.store = Store(kwargs["hermes_home"])

    def get_tool_schemas(self):
        return [dict(name=name, description=description, parameters=dict(type="object",
                    properties=properties, required=required)) for name, description, properties, required in (
            ("naive_rag_add", "Store a memory", {"content": {"type": "string"}}, ["content"]),
            ("naive_rag_search", "Search memories", {"query": {"type": "string"},
                "whole": {"type": "boolean", "default": False}}, ["query"]),
            ("naive_rag_delete", "Delete a memory", {"memory_id": {"type": "string"}}, ["memory_id"]),
        )]

    def handle_tool_call(self, tool_name, args, **kwargs):
        with self.lock:
            if tool_name == "naive_rag_add":
                result = {"id": self.store.add(_text(args, "content"))}
            elif tool_name == "naive_rag_delete":
                result = {"deleted": self.store.delete(_text(args, "memory_id"))}
            elif tool_name == "naive_rag_search":
                results, seen = [], set()
                for _, mid, ordinal, text in scored(self.store.memories, _text(args, "query")):
                    if args.get("whole", False):
                        if mid in seen:
                            continue
                        seen.add(mid)
                        results.append({"id": mid, "content": self.store.memories[mid]})
                    else:
                        results.append({"id": mid, "ordinal": ordinal, "content": text})
                    if len(results) == TOP_K:
                        break
                result = {"results": results}
            else:
                raise ValueError("unknown naive-RAG tool")
        return json.dumps(result, ensure_ascii=False)

    def prefetch(self, query, *, session_id=""):
        return ""

    def sync_turn(self, user_content, assistant_content, **kwargs):
        pass  # Explicit writes only.

    def shutdown(self):
        pass  # Every change is persisted before its tool returns.


def register(ctx):
    ctx.register_memory_provider(NaiveRagProvider())
