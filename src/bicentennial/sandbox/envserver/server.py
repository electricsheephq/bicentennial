"""Line-delimited MCP stdio server with durable, canonical action receipts."""

import argparse
import json
import os
import sys
from pathlib import Path

from bicentennial.canon import canon

from .state import State, state_hash


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _load(raw):
    value = json.loads(raw, object_pairs_hook=_object)
    canon(value)
    return value


def _tools(state):
    tools = []
    for tool in state.tools.values():
        props = {tool["key_arg"]: {"type": "string"}}
        if tool["value_arg"] is not None:
            props[tool["value_arg"]] = {}
        tools.append({"name": tool["name"], "description": tool["description"],
                      "inputSchema": {"type": "object", "properties": props,
                                      "required": list(props), "additionalProperties": False}})
    tools.append({"name": "ask_user", "description": "Ask the simulated user a question.",
                  "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}},
                                  "required": ["question"], "additionalProperties": False}})
    return tools


def serve(seed, log_dir, clock, source, sink):
    state, seq = State(seed), 0
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "env_actions.jsonl").open("ab") as log:
        def write(row):
            log.write(canon(row) + b"\n")
            log.flush()
            os.fsync(log.fileno())

        def now():
            data = _load(Path(clock).read_bytes())
            if type(data["sim_start"]) is not int or type(data["rate"]) is not int or data["rate"] != 0:
                raise ValueError("clock requires integer sim_start and rate zero")
            return data["sim_start"]

        def boundary(kind):
            write({"type": "boundary", "kind": kind, "session": seed["session"],
                   "t_sim": now(), "state_hash": state_hash(state.state)})

        boundary("session_start")
        for line in source:
            try:
                msg = _load(line)
                if (type(msg) is not dict or msg.get("jsonrpc") != "2.0"
                        or type(msg.get("method")) is not str
                        or ("id" in msg and type(msg["id"]) not in (str, int, type(None)))):
                    raise ValueError("invalid request")
            except (ValueError, TypeError, UnicodeError):
                write({"type": "malformed"})
                continue
            if "id" not in msg:
                continue
            method, params = msg["method"], msg.get("params", {})
            response = {"jsonrpc": "2.0", "id": msg["id"]}
            if method == "tools/call":
                seq += 1
                t_sim = now()
                params = params if type(params) is dict else {}
                name, args = params.get("name"), params.get("arguments", {})
                changed, ok = False, False
                try:
                    text, changed = state.call(name, args)
                    ok = True
                except (ValueError, TypeError) as error:
                    text = str(error)
                result = {"content": [{"type": "text", "text": text}], "isError": not ok}
                write({"type": "action", "seq": seq, "session": seed["session"], "t_sim": t_sim,
                       "tool": name, "args": args, "ok": ok, "state_changed": changed,
                       "asked_user": name == "ask_user", "state_hash": state_hash(state.state)})
            elif method == "initialize":
                params = params if type(params) is dict else {}
                result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"),
                          "capabilities": {"tools": {}},
                          "serverInfo": {"name": "bicentennial-envserver", "version": "1"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": _tools(state)}
            else:
                response["error"] = {"code": -32601, "message": "method not found"}
            if "error" not in response:
                response["result"] = result
            sink.write(canon(response).decode("utf-8") + "\n")
            sink.flush()
        boundary("session_end")
    return state.state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "log-dir", "clock"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    serve(_load(args.seed.read_bytes()), args.log_dir, args.clock, sys.stdin, sys.stdout)
