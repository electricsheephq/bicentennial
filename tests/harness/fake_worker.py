"""A standard-library stand-in for the Hermes worker in the CI adapter tests: no Hermes, no network.

It speaks the worker protocol (a ready line, then open, turn and end), reads model.base_url and model.default from
HERMES_HOME/config.yaml, and posts Hermes-like chat bodies offering memory and session_search to the director. When
write calls come back it answers them with a tool-result request. History persists under HERMES_HOME, so a respawn
resumes it by session id.
"""

import http.client
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

HOME = Path(os.environ["HERMES_HOME"])
TOOLS = [{"type": "function", "function": {"name": name}} for name in ("memory", "session_search")]


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def post(model, messages):
    url = urlsplit(model["base_url"])
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=60)
    body = {"model": model["default"], "messages": messages, "tools": TOOLS}
    conn.request("POST", url.path + "/chat/completions", json.dumps(body),
                 {"Content-Type": "application/json", "Authorization": f"Bearer {model['api_key']}"})
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    if resp.status != 200:
        raise RuntimeError(f"director status {resp.status}")
    return json.loads(data)["choices"][0]["message"]


def main():
    t0 = time.monotonic()
    store = HOME / "fake-sessions"
    store.mkdir(exist_ok=True)
    emit({"ready": True, "t_import_ms": int((time.monotonic() - t0) * 1000)})
    sid, cwd, history = None, None, []
    for line in sys.stdin:
        cmd, t1 = json.loads(line), time.monotonic()
        if cmd["op"] == "open":
            sid, cwd = cmd["session_id"] or str(uuid.uuid4()), cmd["cwd"]
            path = store / f"{sid}.json"
            history = json.loads(path.read_text()) if path.exists() else []
            ok = cmd["session_id"] is None or path.exists()
            emit({"ok": ok, "session_id": sid, "history": len(history), "active_memory_providers": ["holographic"],
                  "t_ms": int((time.monotonic() - t1) * 1000)})
        elif cmd["op"] == "turn":
            model = json.loads((HOME / "config.yaml").read_text())["model"]
            system = {"role": "system", "content": f"fake harness; cwd {cwd}; home {HOME}"}
            turn = [{"role": "user", "content": cmd["text"]}]
            msg = post(model, [system, *history, *turn])
            while msg.get("tool_calls"):
                turn += [{"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]},
                         *({"role": "tool", "tool_call_id": c["id"], "content": "saved"} for c in msg["tool_calls"])]
                msg = post(model, [system, *history, *turn])
            history += [*turn, {"role": "assistant", "content": msg["content"]}]
            (store / f"{sid}.json").write_text(json.dumps(history))
            emit({"ok": True, "error": None, "final": msg["content"], "history": len(history),
                  "t_ms": int((time.monotonic() - t1) * 1000)})
        elif cmd["op"] == "end":
            emit({"ok": True, "ended": True, "t_ms": 0})
            break


if __name__ == "__main__":
    main()
