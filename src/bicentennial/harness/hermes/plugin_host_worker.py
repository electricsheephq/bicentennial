"""File-launched T0 worker using the pinned harness's public memory surfaces."""

import json
import os
import sys
import time


def emit(value):
    sys.__stdout__.write(json.dumps(value) + "\n")
    sys.__stdout__.flush()


def main():
    started = time.monotonic()
    sys.stdout = sys.stderr
    from acp_adapter.entry import _load_env, _setup_logging
    _setup_logging()
    _load_env()
    import threading

    from agent.memory_manager import MemoryManager
    from hermes_state import SessionDB
    from plugins.memory import load_memory_provider
    from tools.memory_tool import MEMORY_SCHEMA, load_on_disk_store, memory_tool
    from tools.session_search_tool import SESSION_SEARCH_SCHEMA, session_search

    mgr, store, db, sid = None, None, None, None

    def tool(name, args):
        if mgr is not None:
            return mgr.handle_tool_call(name, args)
        if name == "memory":
            return memory_tool(action=args.get("action", ""), target=args.get("target"),
                               content=args.get("content"), old_text=args.get("old_text"),
                               new_text=args.get("new_text"), operations=args.get("operations"), store=store)
        if name == "session_search":
            optional = ("role_filter", "session_id", "around_message_id", "sort", "profile", "after", "before",
                        "exclude_session_ids")
            return session_search(query=args.get("query") or "", limit=args.get("limit", 3),
                                  window=args.get("window", 5), detail=args.get("detail", "adaptive"),
                                  db=db, current_session_id=None, **{k: args[k] for k in optional if k in args})
        return json.dumps({"error": "unknown tool"})

    emit({"ready": True, "t_import_ms": int((time.monotonic() - started) * 1000)})
    for line in sys.stdin:
        started = time.monotonic()
        ending, op = False, None
        try:
            cmd = json.loads(line)
            op = cmd["op"]
            result = {"ok": True}
            if op == "open":
                sid = cmd["session_id"]
                os.environ["HERMES_SESSION_ID"] = sid
                snapshot = ""
                if cmd["provider"]:
                    provider = load_memory_provider(cmd["provider"])
                    if provider is None or not provider.is_available():
                        raise RuntimeError("plugin_inactive")
                    mgr = MemoryManager()
                    mgr.add_provider(provider)
                    mgr.initialize_all(session_id=sid, platform="cli", agent_context="primary")
                    mgr.build_system_prompt()
                    schemas = mgr.get_all_tool_schemas()
                else:
                    store = load_on_disk_store()
                    parts = []
                    for enabled, kind in ((store.memory_enabled, "memory"), (store.user_profile_enabled, "user")):
                        block = store.format_for_system_prompt(kind) if enabled else None
                        if block:
                            parts.append(block)
                    snapshot = "\n\n".join(parts)
                    db = SessionDB()
                    db.create_session(sid, source="cli")
                    schemas = [MEMORY_SCHEMA, SESSION_SEARCH_SCHEMA]
                result.update(session_id=sid, active_context_engine=None, active_memory_providers=[p.name for p in mgr.providers] if mgr else [],
                              schemas=[{k: s[k] for k in ("name", "parameters")} for s in schemas])
            elif op == "end":
                if mgr is not None:
                    mgr.shutdown_all()
                elif db is not None:
                    db.close()
                result["ended"], ending = True, True
            elif op == "turn":
                call = cmd["call"]
                if call == "ingest":
                    text = cmd["text"]
                    if mgr is not None:
                        mgr.on_turn_start(cmd["n"], text)
                        mgr.prefetch_all(text, session_id=sid)
                    else:
                        db.append_message(sid, "user", text)
                    result["result"] = tool(cmd["write"]["name"], cmd["write"]["arguments"])
                    if mgr is not None:
                        mgr.sync_all(text, "", session_id=sid)
                        mgr.queue_prefetch_all(text, session_id=sid)
                elif call == "query":
                    result["snapshot"] = snapshot
                    result["prefetch"] = mgr.prefetch_all(cmd["text"], session_id=sid) if mgr is not None else ""
                    result["recall"] = tool(cmd["recall"]["name"], cmd["recall"]["arguments"])
                elif call == "tool":
                    result["result"] = tool(cmd["name"], cmd["arguments"])
                elif call == "drain":
                    result["drained"] = mgr.flush_pending(timeout=cmd["timeout_ms"] / 1000) if mgr else True
                    result["threads"] = sorted(t.name for t in threading.enumerate() if t.is_alive())
                elif call == "session_end":
                    if mgr is not None:
                        mgr.on_session_end(cmd["messages"])
                    else:
                        db.end_session(sid, "user_exit")
                else:
                    raise ValueError("unknown call")
            else:
                raise ValueError("unknown op")
        except Exception as exc:
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            if op == "open":
                result["active_memory_providers"] = []
        result["t_ms"] = int((time.monotonic() - started) * 1000)
        emit(result)
        if ending:
            break


if __name__ == "__main__":
    main()
