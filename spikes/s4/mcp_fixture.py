"""Spike S4 MCP fixture: a stdio MCP server with one deterministic tool over a synthetic table.

JSON-RPC 2.0, one message per line on stdin/stdout. Methods: initialize, ping, tools/list and
tools/call; notifications are ignored and any other request gets -32601. The one tool is
fixture_lookup(key), which returns the table's value for key, or an error result for an unknown key.
"""

from __future__ import annotations

import json
import sys

TABLE = {"alpha": "A-1931", "beta": "B-2047", "gamma": "G-5582", "delta": "D-7310"}  # synthetic
TOOL = {"name": "fixture_lookup", "description": "Look up a key in the S4 fixture table and return its value.",
        "inputSchema": {"type": "object", "properties": {"key": {"type": "string", "description": "the key"}},
                        "required": ["key"]}}


def handle(msg: dict) -> dict | None:
    if "id" not in msg:  # a notification
        return None
    mid, method, params = msg["id"], msg.get("method"), msg.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "s4-fixture", "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call" and params.get("name") == TOOL["name"]:
        key = str((params.get("arguments") or {}).get("key", ""))
        if key in TABLE:
            result = {"content": [{"type": "text", "text": f"{key} = {TABLE[key]}"}], "isError": False}
        else:
            result = {"content": [{"type": "text", "text": f"unknown key: {key}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        out = handle(msg) if isinstance(msg, dict) else None
        if out is not None:
            sys.stdout.write(json.dumps(out) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
