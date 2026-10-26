"""Local recording model stub for spike S2. Binds 127.0.0.1 only; calls nothing upstream.

It records every request as one JSON line (credential headers are dropped, only their
presence is kept) and answers with canned responses:

  POST .../chat/completions   OpenAI chat completions, JSON or SSE stream (Hermes)
  POST .../messages           Anthropic messages, JSON or SSE stream (Claude Code)
  POST .../messages/count_tokens, GET .../models   minimal answers

Canned behaviour, keyed on directive lines in the newest user message of a request that
offers tools. Each directive line becomes one tool call, in order; after the last tool
result the reply is plain text, so every turn ends:
  "STUB_MEMORY: <text>"           the tool named ``memory`` (add <text>)
  "STUB_RUN: <command>"           the terminal tool (``terminal`` or ``Bash``) with <command>
  "STUB_TOOL: <name> <json args>" any offered tool with the given arguments
A request with a JSON ``response_format`` (a title call) gets {"title": "Stub title"}.

Usage: python recording_stub.py --port 0 --ledger <file.jsonl> --port-file <file>
"""

import argparse
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_DROP_HEADERS = {"authorization", "x-api-key", "cookie", "proxy-authorization"}
_DIRECTIVE = re.compile(r"^\s*STUB_(MEMORY|RUN|TOOL):\s*(.+?)\s*$", re.MULTILINE)
_lock = threading.Lock()


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
    return ""


def _directives(user_text):
    return [(m.group(1), m.group(2)) for m in _DIRECTIVE.finditer(user_text or "")]


def _tool_names(tools, anthropic):
    names = []
    for t in tools or []:
        if anthropic:
            names.append(t.get("name", ""))
        else:
            names.append((t.get("function") or {}).get("name", ""))
    return names


def _pick_tool(kind, names, arg):
    if kind == "TOOL":
        name = arg.split(None, 1)[0]
        return name if name in names else None
    if kind == "MEMORY":
        return "memory" if "memory" in names else None
    for candidate in ("terminal", "Bash", "bash"):
        if candidate in names:
            return candidate
    return None


def _tool_args(kind, tool, arg):
    if kind == "TOOL":
        rest = arg.split(None, 1)
        return json.loads(rest[1]) if len(rest) > 1 else {}
    if kind == "MEMORY":
        return {"action": "add", "target": "memory", "content": arg}
    return {"command": arg} if tool != "Bash" else {"command": arg, "description": "stub command"}


class Handler(BaseHTTPRequestHandler):
    server_version = "s2-stub/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; the ledger is the record
        pass

    def _record(self, body_obj, raw_len):
        headers = {k.lower(): ("<present>" if k.lower() in _DROP_HEADERS else v) for k, v in self.headers.items()}
        line = {"wall_received": time.time(), "method": self.command, "path": self.path,
                "headers": headers, "body_bytes": raw_len, "body": body_obj}
        with _lock, open(self.server.ledger, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(line, ensure_ascii=False) + "\n")

    def _read(self):
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            obj = json.loads(raw) if raw else None
        except ValueError:
            obj = {"unparsed": raw[:2000].decode("utf-8", "replace")}
        return obj, len(raw)

    def _send_json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, events):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.end_headers()
        for name, payload in events:
            chunk = (f"event: {name}\n" if name else "") + "data: " + (
                payload if isinstance(payload, str) else json.dumps(payload)) + "\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()
        self.close_connection = True

    def do_GET(self):
        self._record(None, 0)
        if self.path.rstrip("/").endswith("/models"):
            self._send_json(200, {"object": "list", "data": [{"id": "stub-model", "object": "model", "owned_by": "stub"}]})
        else:
            self._send_json(404, {"error": {"message": "stub: not found"}})

    def do_HEAD(self):
        self._record(None, 0)
        self.send_response(200)
        self.send_header("content-length", "0")
        self.end_headers()

    def do_POST(self):
        body, n = self._read()
        self._record(body, n)
        path = self.path.split("?")[0].rstrip("/")
        if path.endswith("/chat/completions"):
            return self._openai(body or {})
        if path.endswith("/messages/count_tokens"):
            return self._send_json(200, {"input_tokens": 100})
        if path.endswith("/messages"):
            return self._anthropic(body or {})
        self._send_json(404, {"error": {"message": "stub: not found"}})

    # -- decisions ---------------------------------------------------------------------------
    @staticmethod
    def _decide(messages, tools, anthropic):
        if not messages or not tools:
            return None

        def is_tool_result(m):
            c = m.get("content")
            return m.get("role") == "tool" or (anthropic and isinstance(c, list) and any(
                isinstance(p, dict) and p.get("type") == "tool_result" for p in c))

        done = 0
        for m in reversed(messages):  # tool calls already answered since the newest real user text
            if is_tool_result(m):
                done += 1
            elif m.get("role") == "user":
                directives = _directives(_text_of(m.get("content")))
                break
        else:
            return None
        if done >= len(directives):
            return None
        kind, arg = directives[done]
        tool = _pick_tool(kind, _tool_names(tools, anthropic), arg)
        return (tool, _tool_args(kind, tool, arg)) if tool else None

    # -- OpenAI ------------------------------------------------------------------------------
    def _openai(self, body):
        call = self._decide(body.get("messages") or [], body.get("tools"), anthropic=False)
        model = body.get("model", "stub-model")
        cid, created = "chatcmpl-" + uuid.uuid4().hex[:12], int(time.time())
        usage = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        if call:
            tc = {"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                  "function": {"name": call[0], "arguments": json.dumps(call[1])}}
            message, finish = {"role": "assistant", "content": None, "tool_calls": [tc]}, "tool_calls"
        elif body.get("response_format"):
            message, finish = {"role": "assistant", "content": json.dumps({"title": "Stub title"})}, "stop"
        else:
            message, finish = {"role": "assistant", "content": "Stub reply."}, "stop"
        if not body.get("stream"):
            return self._send_json(200, {"id": cid, "object": "chat.completion", "created": created, "model": model,
                                         "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                                         "usage": usage})
        base = {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model}
        events = [(None, {**base, "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}]})]
        if call:
            tc = dict(message["tool_calls"][0], index=0)
            events.append((None, {**base, "choices": [{"index": 0, "delta": {"tool_calls": [tc]}, "finish_reason": None}]}))
        else:
            events.append((None, {**base, "choices": [{"index": 0, "delta": {"content": message["content"]},
                                                       "finish_reason": None}]}))
        events.append((None, {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage}))
        events.append((None, "[DONE]"))
        self._send_sse(events)

    # -- Anthropic ---------------------------------------------------------------------------
    def _anthropic(self, body):
        call = self._decide(body.get("messages") or [], body.get("tools"), anthropic=True)
        model = body.get("model", "stub-model")
        mid = "msg_" + uuid.uuid4().hex[:16]
        if call:
            block = {"type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:12], "name": call[0], "input": call[1]}
            stop = "tool_use"
        else:
            block, stop = {"type": "text", "text": "Stub reply."}, "end_turn"
        usage = {"input_tokens": 10, "output_tokens": 5}
        if not body.get("stream"):
            return self._send_json(200, {"id": mid, "type": "message", "role": "assistant", "model": model,
                                         "content": [block], "stop_reason": stop, "stop_sequence": None,
                                         "usage": usage})
        start = {"type": "message_start", "message": {"id": mid, "type": "message", "role": "assistant", "model": model,
                                                      "content": [], "stop_reason": None, "stop_sequence": None,
                                                      "usage": {"input_tokens": 10, "output_tokens": 1}}}
        if call:
            cb_start = {"type": "content_block_start", "index": 0, "content_block": dict(block, input={})}
            delta = {"type": "content_block_delta", "index": 0,
                     "delta": {"type": "input_json_delta", "partial_json": json.dumps(call[1])}}
        else:
            cb_start = {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
            delta = {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": block["text"]}}
        self._send_sse([
            ("message_start", start), ("content_block_start", cb_start), ("content_block_delta", delta),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            ("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                               "usage": {"output_tokens": 5}}),
            ("message_stop", {"type": "message_stop"}),
        ])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--port-file", required=True)
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads = True
    srv.ledger = a.ledger
    with open(a.port_file, "w") as fh:
        fh.write(str(srv.server_address[1]))
    srv.serve_forever()


if __name__ == "__main__":
    main()
