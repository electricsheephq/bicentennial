"""Stdlib T1 double: native memory, persisted sessions, terminal, and MCP stdio."""

import argparse
import http.client
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def emit(obj):
    print(json.dumps(obj), flush=True)


def rpc(proc, method, params):
    proc.stdin.write(json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())["result"]


def request(cfg, messages, tools, *, embeddings=False):
    url = urlsplit(cfg["model"]["base_url"])
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
    body = dict(model=cfg["model"]["default"], messages=messages, tools=tools)
    if embeddings:
        body = dict(model="bicentennial-embeddings", input="post-restart metadata")
    conn.request("POST", url.path + ("/embeddings" if embeddings else "/chat/completions"),
                 json.dumps(body), {"Content-Type": "application/json"})
    response = conn.getresponse()
    raw = response.read()
    conn.close()
    if response.status != 200:
        return None
    return json.loads(raw) if embeddings else json.loads(raw)["choices"][0]["message"]


def execute(call, memory, servers, cwd):
    name, args = call["function"]["name"], json.loads(call["function"]["arguments"])
    if name in ("memory", "fact_store"):
        if args.get("action") in ("search", "read"):
            return json.dumps(dict(success=True, content=memory.read_text() if memory.exists() else ""))
        if args.get("action") != "add" or not isinstance(args.get("content"), str):
            return json.dumps(dict(success=False, error="unsupported memory action"))
        memory.parent.mkdir(exist_ok=True)
        with memory.open("a") as stream:
            stream.write(args["content"] + "\n")
        return json.dumps(dict(success=True))
    if name == "terminal":
        out = subprocess.run(args["command"], shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
        return json.dumps(dict(output=out.stdout, exit_code=out.returncode, error=None))
    if name == "tool_call" or name.startswith("mcp__"):
        # R14b fake_tool_worker has these functions nested in main; restate its stdio bridge. With tool search
        # off (#191) the pin offers MCP tools directly by their mcp__<server>__<tool> name.
        inner = args["calls"][0] if name == "tool_call" else dict(name=name, arguments=args)
        _, server, tool = inner["name"].split("__", 2)
        result = rpc(servers[server], "tools/call", dict(name=tool, arguments=inner["arguments"]))
        return json.dumps({"error" if result["isError"] else "result": "\n".join(
            c["text"] for c in result["content"])})
    return json.dumps(dict(success=True))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-turn", type=int)
    parser.add_argument("--timeline", type=Path, required=True)
    parser.add_argument("--no-tools-in-probe", action="store_true")
    parser.add_argument("--drop-recall", action="store_true")
    parser.add_argument("--embeddings-after-restart", action="store_true")
    args = parser.parse_args()
    timeline = json.loads(args.timeline.read_bytes())
    home = Path(os.environ["HERMES_HOME"])
    cfg = json.loads((home / "config.yaml").read_bytes())
    store, servers = home / "fake-sessions", {}
    store.mkdir(exist_ok=True)
    memory = home / "memories" / "MEMORY.md"
    tools = list(cfg["platform_toolsets"]["acp"])
    provider = cfg["memory"]["provider"]
    if provider == "holographic":
        tools = [n for n in tools if n not in ("memory", "session_search")] + ["fact_store", "fact_feedback"]
    # The pin's tool search hides MCP tools behind tool_call unless the config turns it off (#191)
    eager = cfg.get("tools", {}).get("tool_search", {}).get("enabled") == "off"
    if cfg.get("mcp_servers") and not eager:
        tools.append("tool_call")
    emit(dict(ready=True))
    try:
        for line in sys.stdin:
            op = json.loads(line)
            if op["op"] == "open":
                sid, cwd = op["session_id"] or str(uuid.uuid4()), Path(op["cwd"])
                path = store / f"{sid}.json"
                history = json.loads(path.read_bytes()) if path.exists() else []
                for name, config in cfg.get("mcp_servers", {}).items():
                    proc = servers[name] = subprocess.Popen([config["command"], *config["args"]],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ, **config["env"]))
                    rpc(proc, "initialize", {})
                    if eager:
                        tools[:] = [n for n in tools if not n.startswith(f"mcp__{name}__")] + [
                            f"mcp__{name}__{t['name']}" for t in rpc(proc, "tools/list", {})["tools"]]
                emit(dict(ok=op["session_id"] is None or path.exists(), session_id=sid,
                          history=len(history), active_memory_providers=[provider] if provider else []))
                if op["session_id"] and args.embeddings_after_restart:
                    request(cfg, [], [], embeddings=True)
            elif op["op"] == "turn":
                session, turn, kind = timeline[op["text"]]
                probe = kind == "probe"
                offered = [] if probe and args.no_tools_in_probe else [n for n in tools if not (
                    probe and args.drop_recall and n in ("session_search", "fact_store"))]
                schemas = [dict(type="function", function=dict(name=n)) for n in offered]
                if args.fail_turn == session:
                    emit(dict(ok=False, error="injected turn failure"))
                    continue
                system = f"fake harness; cwd {cwd}; home {home}"
                if cfg["memory"]["memory_enabled"]:
                    system += "\nMEMORY:\n" + (memory.read_text() if memory.exists() else "")
                messages = [dict(role="system", content=system), *history, dict(role="user", content=op["text"])]
                msg = request(cfg, messages, schemas)
                while msg is not None and msg.get("tool_calls"):
                    messages.append(msg)
                    messages.extend(dict(role="tool", tool_call_id=c["id"], content=execute(c, memory, servers, cwd))
                                    for c in msg["tool_calls"])
                    msg = request(cfg, messages, schemas)
                if msg is None:
                    emit(dict(ok=False, error="director refused"))
                    continue
                history = messages[1:] + [msg]
                path.write_text(json.dumps(history))
                emit(dict(ok=True, final=msg.get("content") or "", history=len(history)))
            elif op["op"] == "end":
                for proc in servers.values():
                    proc.stdin.close()
                    proc.wait(timeout=5)
                emit(dict(ok=True, alive_threads=[]))
                break
    finally:
        for proc in servers.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
