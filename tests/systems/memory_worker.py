"""Stdlib memory-capable worker double, using only the director on loopback."""

import http.client
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

HERMES_HOME = Path(os.environ["HERMES_HOME"])


def emit(obj):
    print(json.dumps(obj), flush=True)


def post(cfg, messages):
    model = cfg["model"]
    url = urlsplit(model["base_url"])
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=60)
    tools = [{"type": "function", "function": {"name": name}}
             for name in ("memory", "session_search") if name in cfg["platform_toolsets"]["acp"]
             and (name != "memory" or cfg["memory"]["memory_enabled"])]
    body = {"model": model["default"], "messages": messages, "tools": tools}
    conn.request("POST", url.path + "/chat/completions", json.dumps(body),
                 {"Content-Type": "application/json", "Authorization": f"Bearer {model['api_key']}"})
    response = conn.getresponse()
    data = response.read()
    conn.close()
    if response.status != 200:
        raise RuntimeError(f"director status {response.status}")
    return json.loads(data)["choices"][0]["message"]


def main():
    store = HERMES_HOME / "fake-sessions"
    store.mkdir(exist_ok=True)
    emit({"ready": True})
    sid, cwd, history = None, None, []
    for line in sys.stdin:
        cmd = json.loads(line)
        if cmd["op"] == "open":
            sid, cwd = cmd["session_id"] or str(uuid.uuid4()), Path(cmd["cwd"])
            path = store / f"{sid}.json"
            history = json.loads(path.read_bytes()) if path.exists() else []
            emit({"ok": cmd["session_id"] is None or path.exists(), "session_id": sid, "history": len(history)})
        elif cmd["op"] == "turn":
            cfg = json.loads((HERMES_HOME / "config.yaml").read_bytes())
            memory = (Path(os.environ["HOME"]) if (cwd / "leak-to-home").is_file() else HERMES_HOME)
            memory = memory / "memories" / "MEMORY.md"
            text = f"fake harness; cwd {cwd}; home {HERMES_HOME}"
            if cfg["memory"]["memory_enabled"]:
                text += "\nMEMORY:\n" + (memory.read_text() if memory.exists() else "")
            system = {"role": "system", "content": text}
            turn = [{"role": "user", "content": cmd["text"]}]
            msg = post(cfg, [system, *history, *turn])
            while msg.get("tool_calls"):
                for call in msg["tool_calls"]:
                    if call["function"]["name"] == "memory":
                        memory.parent.mkdir(exist_ok=True)
                        with memory.open("a") as stream:
                            stream.write(json.loads(call["function"]["arguments"])["content"] + "\n")
                turn += [{"role": "assistant", "content": msg.get("content") or "", "tool_calls": msg["tool_calls"]},
                         *({"role": "tool", "tool_call_id": c["id"], "content": "saved"} for c in msg["tool_calls"])]
                msg = post(cfg, [system, *history, *turn])
            history += [*turn, {"role": "assistant", "content": msg["content"]}]
            (store / f"{sid}.json").write_text(json.dumps(history))
            emit({"ok": True, "error": None, "final": msg["content"], "history": len(history)})
        elif cmd["op"] == "end":
            emit({"ok": True, "ended": True})
            break


if __name__ == "__main__":
    main()
