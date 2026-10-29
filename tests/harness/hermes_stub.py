"""Write isolated, stdlib-only substitutes for the worker's public Hermes imports."""

from pathlib import Path

COMMON = r'''
import json
import os
import re
import threading
import time
from pathlib import Path

MODE = __MODE__
SYNC_MS = __SYNC_MS__
MAX_LENGTH = __MAX_LENGTH__
PROVIDER = ""
THREADS = []


def log(name, *args, **kwargs):
    path = Path(__LOG__)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        stream.write(json.dumps(dict(name=name, args=args, kwargs=kwargs)) + "\n")


def path():
    base = Path(os.environ["HOME"]) / ".mem0" if PROVIDER == "mem0" else Path(os.environ["HERMES_HOME"])
    base.mkdir(parents=True, exist_ok=True)
    return base / "stub_store.json"


def read():
    p = path()
    return json.loads(p.read_text()) if p.exists() else []


def save(rows):
    path().write_text(json.dumps(rows))


def opened():
    if MODE == "wipe_on_open":
        save([])


def schema(name, key="content"):
    field = dict(type="string")
    if MAX_LENGTH is not None:
        field["maxLength"] = MAX_LENGTH
    return dict(name=name, parameters=dict(type="object", properties={key: field}))


def search(query):
    words = lambda text: set(re.findall(r"\w+", text.casefold()))
    ranked = [(len(words(query) & words(row["text"])),
               -row["t"] if MODE == "stale_wins" else row["t"], row["seq"], row) for row in read()]
    ranked = [r for r in ranked if r[0] > 0]
    if MODE == "all_hits":
        return [r[3] for r in sorted(ranked, key=lambda r: r[:3], reverse=True)]
    return [max(ranked, key=lambda r: r[:3])[3]] if ranked else []


def tool(name, args):
    action = args.get("action", "")
    if name in ("memory", "fact_store") and action == "add" or name == "mem0_add":
        if name == "mem0_add" and MODE == "delayed_sync":
            return json.dumps(dict(ok=True))
        rows = read()
        if name == "memory" and any(r["text"] == args["content"] for r in rows):
            return json.dumps(dict(ok=True))
        rows.append(dict(t=time.time(), seq=max((r["seq"] for r in rows), default=0) + 1, text=args["content"]))
        save(rows)
        return json.dumps(dict(ok=True))
    if name in ("session_search", "mem0_search") or name == "fact_store" and action == "search":
        rows = search(args.get("query", ""))
        if name == "fact_store":
            result = [dict(content=r["text"], fact_id=str(r["seq"])) for r in rows]
        elif name == "mem0_search":
            result = [dict(memory=r["text"], id=str(r["seq"]), score=1) for r in rows]
        else:
            result = [dict(content=r["text"]) for r in rows]
        return json.dumps(dict(results=result))
    if name in ("memory", "fact_store") and action == "remove" or name == "mem0_delete":
        if MODE != "keep_on_remove":
            if name == "memory":
                save([r for r in read() if r["text"] != args["old_text"]])
            else:
                key = args["fact_id" if name == "fact_store" else "memory_id"]
                save([r for r in read() if str(r["seq"]) != key])
        return json.dumps(dict(ok=True))
    return json.dumps(dict(error="unknown tool"))
'''

MANAGER = '''
import _stub as s


class MemoryManager:
    def __init__(self):
        s.log("MemoryManager")
        self.providers = []

    def add_provider(self, provider):
        s.log("add_provider")
        self.providers.append(provider)

    def initialize_all(self, **kwargs):
        s.log("initialize_all", **kwargs)
        s.opened()

    def build_system_prompt(self):
        s.log("build_system_prompt")
        return "ignored system prompt"

    def get_all_tool_schemas(self):
        s.log("get_all_tool_schemas")
        return [s.schema(n) for n in ("mem0_add", "mem0_search", "mem0_delete")] if s.PROVIDER == "mem0" else [s.schema("fact_store")]

    def on_turn_start(self, n, text):
        s.log("on_turn_start", n, text)

    def prefetch_all(self, text, **kwargs):
        s.log("prefetch_all", text, **kwargs)
        return "prefetched context"

    def handle_tool_call(self, name, args):
        s.log("handle_tool_call", name, args)
        return s.tool(name, args)

    def sync_all(self, user, assistant, **kwargs):
        s.log("sync_all", user, assistant, **kwargs)
        if s.PROVIDER == "mem0" and s.SYNC_MS:
            def sync():
                s.time.sleep(s.SYNC_MS / 1000)
                if s.MODE == "delayed_sync":
                    rows = s.read()
                    rows.append(dict(t=s.time.time(), seq=max((r["seq"] for r in rows), default=0) + 1, text=user))
                    s.save(rows)
                    s.log("sync_landed", user)
            thread = s.threading.Thread(target=sync, name="mem0-sync", daemon=True)
            s.THREADS.append(thread)
            thread.start()

    def queue_prefetch_all(self, text, **kwargs):
        s.log("queue_prefetch_all", text, **kwargs)

    def flush_pending(self, timeout=None):
        s.log("flush_pending", timeout=timeout)
        deadline = s.time.monotonic() + timeout
        for thread in s.THREADS:
            thread.join(max(0, deadline - s.time.monotonic()))
        return not any(t.is_alive() for t in s.THREADS)

    def on_session_end(self, messages):
        s.log("on_session_end", messages)

    def shutdown_all(self):
        s.log("shutdown_all")
'''

MODULES = {
    "acp_adapter/entry.py": '''
def _setup_logging():
    print("stub logging chatter")


def _load_env():
    print("stub environment chatter")
''',
    "agent/memory_manager.py": MANAGER,
    "plugins/memory/__init__.py": '''
import _stub as s


class Provider:
    def __init__(self, name):
        self.name = name

    def is_available(self):
        s.log("is_available")
        return True


def load_memory_provider(name):
    s.log("load_memory_provider", name)
    s.PROVIDER = name
    return None if s.MODE == "missing" else Provider(name)
''',
    "tools/memory_tool.py": '''
import _stub as s

MEMORY_SCHEMA = s.schema("memory")


class MemoryStore:
    memory_enabled = True
    user_profile_enabled = True

    def format_for_system_prompt(self, target):
        return None


def load_on_disk_store():
    s.log("load_on_disk_store")
    s.opened()
    return MemoryStore()


def memory_tool(action=None, target="memory", content=None, old_text=None, new_text=None, operations=None, store=None):
    args = dict(action=action, target=target)
    args.update({k: v for k, v in dict(content=content, old_text=old_text, new_text=new_text, operations=operations).items() if v is not None})
    s.log("memory_tool", **args)
    return s.tool("memory", args)
''',
    "tools/session_search_tool.py": '''
import _stub as s

SESSION_SEARCH_SCHEMA = s.schema("session_search", "query")


def session_search(query="", role_filter=None, limit=3, db=None, current_session_id=None, session_id=None,
                   around_message_id=None, window=5, sort=None, profile=None, detail="adaptive", after=None,
                   before=None, exclude_session_ids=None):
    s.log("session_search", query=query, current_session_id=current_session_id)
    return s.tool("session_search", dict(query=query))
''',
    "hermes_state.py": '''
import _stub as s


class SessionDB:
    def __init__(self):
        s.log("SessionDB")

    def create_session(self, sid, source):
        s.log("create_session", sid, source=source)

    def append_message(self, sid, role, text):
        s.log("append_message", sid, role, text)

    def end_session(self, sid, reason):
        s.log("end_session", sid, reason)

    def close(self):
        s.log("close")
''',
}


def write_tree(dest, *, log, mode="none", sync_ms=0, max_length=None):
    """Create exactly the Hermes import surfaces used by the file-launched worker."""
    if mode not in {"none", "wipe_on_open", "keep_on_remove", "stale_wins", "missing", "delayed_sync", "all_hits"}:
        raise ValueError("unknown stub mode")
    dest = Path(dest)
    source = COMMON.replace("__MODE__", repr(mode)).replace("__SYNC_MS__", str(sync_ms))
    source = source.replace("__MAX_LENGTH__", repr(max_length))
    source = source.replace("__LOG__", repr(str(Path(log).resolve())))
    modules = dict(MODULES, **{"_stub.py": source})
    for name, source in modules.items():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        for parent in target.parents:
            if parent == dest:
                break
            (parent / "__init__.py").touch(exist_ok=True)
        target.write_text(source.lstrip())
    return dest
