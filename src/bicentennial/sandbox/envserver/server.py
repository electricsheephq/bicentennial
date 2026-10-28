"""Line-delimited MCP stdio server with durable, canonical action receipts."""

import argparse
import json
import os
import select
import signal
import sys
from contextlib import contextmanager
from pathlib import Path

from bicentennial.canon import canon

from .state import State, state_hash
from .tools_g2 import G2_ENV_ID, G2State


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


MAX_DEPTH = 64


def _canonical(value):
    try:
        canon(value)
        return True
    except (ValueError, TypeError, RecursionError):
        return False


def _shallow(value):
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        if depth > MAX_DEPTH:
            return False
        children = item.values() if type(item) is dict else item if type(item) is list else ()
        stack.extend((child, depth + 1) for child in children)
    return True


def _envelope(line):
    """Only the envelope decides whether a line is malformed; the wire is UTF-8 whatever the locale."""
    msg = json.loads(line.decode("utf-8") if type(line) is bytes else line, object_pairs_hook=_object)
    if (type(msg) is not dict or msg.get("jsonrpc") != "2.0"
            or type(msg.get("method")) is not str or not _shallow(msg)
            or ("id" in msg and (type(msg["id"]) not in (str, int, type(None))
                                 or not _canonical(msg["id"])))):
        raise ValueError("invalid request")
    return msg


def _tools(state):
    tools = []
    for tool in state.tools.values():
        props = {tool["key_arg"]: {"type": "string"}}
        if tool["value_arg"] is not None:
            props[tool["value_arg"]] = tool.get("value_schema", {})
        tools.append({"name": tool["name"], "description": tool["description"],
                      "inputSchema": {"type": "object", "properties": props,
                                      "required": list(props), "additionalProperties": False}})
    tools.append({"name": "ask_user", "description": "Ask the simulated user a question.",
                  "inputSchema": {"type": "object", "properties": {"question": {"type": "string"}},
                                  "required": ["question"], "additionalProperties": False}})
    return tools


def serve(seed, log_dir, clock, source, sink):
    state, seq = (G2State if type(seed) is dict and seed.get("env_id") == G2_ENV_ID else State)(seed), 0
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
                msg = _envelope(line)
            except (ValueError, TypeError, RecursionError):
                write({"type": "malformed"})
                continue
            if "id" not in msg:
                continue
            # Params that canon cannot encode (a float, a lone surrogate) are answered, never dropped.
            clean = _canonical(msg)
            method, params = msg["method"], msg.get("params", {}) if clean else {}
            response = {"jsonrpc": "2.0", "id": msg["id"]}
            if method == "tools/call":
                seq += 1
                t_sim = now()
                raw = msg.get("params")
                params = params if type(params) is dict else {}
                name, args = params.get("name"), params.get("arguments", {})
                changed, ok = False, False
                if not clean:
                    name = raw.get("name") if type(raw) is dict and _canonical(raw.get("name")) else None
                    args, text = None, "arguments must be canonical JSON: no floats or lone surrogates"
                else:
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
            sink.write(canon(response) + b"\n")
            sink.flush()
        boundary("session_end")
    return state.state


@contextmanager
def _sigterm_source(source):
    reader, writer = os.pipe()
    stopped = False

    def stop(signum, frame):
        nonlocal stopped
        if not stopped:
            stopped = True
            # Wake select without raising through a state change, fsync, or response write.
            os.write(writer, b"\0")

    def lines():
        pending = b""
        while not stopped:
            if b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                yield line + b"\n"
                continue
            select.select([source, reader], [], [])
            if stopped:
                break
            chunk = os.read(source.fileno(), 65536)
            if not chunk:
                if pending:
                    yield pending
                break
            pending += chunk
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    signal.signal(signal.SIGTERM, stop)
    try:
        yield lines()
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        os.close(reader)
        os.close(writer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("seed", "log-dir", "clock"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    with _sigterm_source(sys.stdin.buffer) as source:
        serve(_load(args.seed.read_bytes()), args.log_dir, args.clock, source, sys.stdout.buffer)
