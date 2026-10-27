"""One Hermes session, driven in process through Hermes's own ACP session path (S6a hermes_worker.py, promoted):
SessionManager, AIAgent.run_conversation, save_session and end_all_sessions, without the JSON-RPC transport whose
dependency the pinned install lacks (the disclosed fallback). Run as a file by the pinned interpreter. After a first
{"ready": true} line, one JSON line answers each op: {"op": "open", "session_id": null | id, "cwd": dir},
{"op": "turn", "text": ...} or {"op": "end"}. Times are integer milliseconds; the final is returned in full."""

import json
import os
import sys
import time


def emit(obj):
    sys.__stdout__.write(json.dumps(obj) + "\n")
    sys.__stdout__.flush()


def ms(t0):
    return int((time.monotonic() - t0) * 1000)


def main():
    t0 = time.monotonic()
    sys.stdout = sys.stderr  # keep Hermes chatter off the control channel
    from acp_adapter.entry import _load_env, _setup_logging
    _setup_logging()
    _load_env()
    from agent.ssl_verify import install_truststore
    install_truststore()
    from acp_adapter.session import SessionManager
    from gateway.session_context import clear_session_vars, set_session_vars
    mgr, state = SessionManager(), None
    emit({"ready": True, "t_import_ms": ms(t0)})
    for line in sys.stdin:
        cmd = json.loads(line)
        t1 = time.monotonic()
        if cmd["op"] == "open":
            state = mgr.get_session(cmd["session_id"]) if cmd.get("session_id") else mgr.create_session(cmd["cwd"])
            memory = getattr(getattr(state, "agent", None), "_memory_manager", None)
            emit({"ok": state is not None, "session_id": state and state.session_id,
                  "active_memory_providers": [p.name for p in getattr(memory, "providers", None) or []],
                  "history": state and len(state.history), "t_ms": ms(t1)})
        elif cmd["op"] == "turn":
            tokens = set_session_vars(session_key=state.session_id, session_id=state.session_id, cwd=state.cwd,
                                      cron_session="")
            os.environ["HERMES_SESSION_ID"] = state.session_id
            try:
                result = state.agent.run_conversation(user_message=cmd["text"], conversation_history=state.history,
                                                      task_id=state.session_id, persist_user_message=cmd["text"])
                err = None
            except Exception as e:  # recorded, never hidden
                result, err = {"messages": state.history, "final_response": ""}, f"{type(e).__name__}: {e}"[:300]
            finally:
                clear_session_vars(tokens)
            if isinstance(result.get("messages"), list):
                state.history = result["messages"]
                mgr.save_session(state.session_id)
            emit({"ok": err is None, "error": err, "final": result.get("final_response") or "",
                  "history": len(state.history), "hermes_session_id": getattr(state.agent, "session_id", None),
                  "t_ms": ms(t1)})
        elif cmd["op"] == "end":
            import threading
            mgr.end_all_sessions()
            emit({"ok": True, "ended": True, "t_ms": ms(t1),
                  "alive_threads": sorted(t.name for t in threading.enumerate() if t.is_alive())})
            break


if __name__ == "__main__":
    main()
