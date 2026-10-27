"""Stdlib worker protocol double: real workspace commands and a real stdio MCP child."""

import http.client
import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def emit(obj):
    print(json.dumps(obj), flush=True)


def main():
    cfg = json.loads((Path(os.environ["HERMES_HOME"]) / "config.yaml").read_bytes())
    model, servers, history = cfg["model"], {}, []
    tools = [{"type": "function", "function": {"name": n}} for n in ("memory", "terminal", "tool_call")]
    emit({"ready": True})

    def rpc(proc, method, params):
        proc.stdin.write(json.dumps(dict(jsonrpc="2.0", id=1, method=method, params=params)) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())["result"]

    def execute(call):
        name, args = call["function"]["name"], json.loads(call["function"]["arguments"])
        if name == "terminal":
            out = subprocess.run(args["command"], shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
            return json.dumps(dict(output=out.stdout, exit_code=out.returncode, error=None))
        if name == "tool_call":
            inner = args["calls"][0]
            _, server, tool = inner["name"].split("__", 2)
            result = rpc(servers[server], "tools/call", dict(name=tool, arguments=inner["arguments"]))
            return json.dumps({"error" if result["isError"] else "result": "\n".join(
                c["text"] for c in result["content"])})
        return '{"success":true}'  # scripted memory write; memory quality is outside this check

    def post(messages):
        url = urlsplit(model["base_url"])
        conn = http.client.HTTPConnection(url.hostname, url.port, timeout=30)
        conn.request("POST", url.path + "/chat/completions", json.dumps(dict(
            model=model["default"], messages=messages, tools=tools)), {"Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        if response.status != 200:
            raise RuntimeError(f"director status {response.status}")
        return json.loads(raw)["choices"][0]["message"]

    try:
        for line in sys.stdin:
            op = json.loads(line)
            if op["op"] == "open":
                cwd = op["cwd"]
                for name, config in cfg.get("mcp_servers", {}).items():
                    proc = servers[name] = subprocess.Popen([config["command"], *config["args"]],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=dict(os.environ, **config["env"]))
                    rpc(proc, "initialize", {})
                emit(dict(ok=True, session_id="fake-tool-session", history=0))
            elif op["op"] == "turn":
                history.append(dict(role="user", content=op["text"]))
                msg = post(history)
                while msg.get("tool_calls"):
                    history.append(msg)
                    history.extend(dict(role="tool", tool_call_id=c["id"], content=execute(c))
                                   for c in msg["tool_calls"])
                    msg = post(history)
                history.append(msg)
                emit(dict(ok=True, final=msg["content"], history=len(history)))
            elif op["op"] == "end":
                for proc in servers.values():
                    proc.stdin.close()
                    proc.wait(timeout=5)
                emit(dict(ok=True))
                break
    finally:
        for proc in servers.values():
            if proc.poll() is None:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    main()
