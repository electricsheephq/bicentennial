"""S8's disclosed image delivery adaptation of the R12 JSON-line worker."""

import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path


def emit(obj):
    sys.__stdout__.write(json.dumps(obj) + "\n")
    sys.__stdout__.flush()


def rewrite_config(home, mode):
    path = Path(home) / "config.yaml"
    cfg = json.loads(path.read_bytes())
    tools = cfg["platform_toolsets"]["acp"]
    if "vision" not in tools:
        tools.append("vision")
    cfg["agent"]["image_input_mode"] = mode
    if mode == "native":
        cfg["model"]["supports_vision"] = True
    data = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode() + b"\n"
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".s8-config-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def attachment_message(text, side):
    entry = side["attachments"].get(text)
    if entry is None:
        return text
    if side["mode"] == "text":
        from gateway.run import GatewayRunner
        note = asyncio.run(GatewayRunner._enrich_message_with_vision(None, "", entry["paths"]))
        return [{"type": "text", "text": note}, {"type": "text", "text": text}]
    from agent.image_routing import build_native_content_parts
    parts, skipped = build_native_content_parts(entry["text"], entry["paths"])
    if skipped or not parts or parts[0]["text"] != text:
        raise ValueError("native_text_mismatch")
    return parts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[0] == "--native-text":
        from agent.image_routing import build_native_content_parts
        parts, skipped = build_native_content_parts(argv[1], [argv[2]])
        if skipped:
            raise ValueError("native_text_unreadable")
        print(parts[0]["text"])
        return
    side = json.loads(Path(argv[0]).read_bytes())
    rewrite_config(os.environ["HERMES_HOME"], side["mode"])
    t0 = time.monotonic()
    sys.stdout = sys.stderr
    from acp_adapter.entry import _load_env, _setup_logging
    _setup_logging()
    _load_env()
    from agent.ssl_verify import install_truststore
    install_truststore()
    from acp_adapter.session import SessionManager
    from gateway.session_context import clear_session_vars, set_session_vars
    mgr, state = SessionManager(), None
    emit({"ready": True, "t_import_ms": int((time.monotonic() - t0) * 1000)})
    for line in sys.stdin:
        cmd, t1 = json.loads(line), time.monotonic()
        if cmd["op"] == "open":
            state = mgr.get_session(cmd["session_id"]) if cmd.get("session_id") else mgr.create_session(cmd["cwd"])
            memory = getattr(getattr(state, "agent", None), "_memory_manager", None)
            emit({"ok": state is not None, "session_id": state and state.session_id,
                  "active_memory_providers": [p.name for p in getattr(memory, "providers", None) or []],
                  "history": state and len(state.history), "t_ms": int((time.monotonic() - t1) * 1000)})
        elif cmd["op"] == "turn":
            tokens = set_session_vars(session_key=state.session_id, session_id=state.session_id, cwd=state.cwd,
                                      cron_session="")
            os.environ["HERMES_SESSION_ID"] = state.session_id
            try:
                message = attachment_message(cmd["text"], side)
                result = state.agent.run_conversation(user_message=message, conversation_history=state.history,
                                                      task_id=state.session_id, persist_user_message=cmd["text"])
                err = None
            except Exception as exc:
                # Stable codes only: neither provider text nor paths enter protocol errors.
                err = "native_text_mismatch" if str(exc) == "native_text_mismatch" else type(exc).__name__
                result = {"messages": state.history, "final_response": ""}
                if err == "native_text_mismatch":
                    print(err, file=sys.stderr)
            finally:
                clear_session_vars(tokens)
            if isinstance(result.get("messages"), list):
                state.history = result["messages"]
                mgr.save_session(state.session_id)
            emit({"ok": err is None, "error": err, "final": result.get("final_response") or "",
                  "history": len(state.history), "hermes_session_id": getattr(state.agent, "session_id", None),
                  "t_ms": int((time.monotonic() - t1) * 1000)})
        elif cmd["op"] == "end":
            import threading
            mgr.end_all_sessions()
            emit({"ok": True, "ended": True, "t_ms": int((time.monotonic() - t1) * 1000),
                  "alive_threads": sorted(t.name for t in threading.enumerate() if t.is_alive())})
            break


if __name__ == "__main__":
    main()
