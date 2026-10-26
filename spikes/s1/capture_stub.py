"""Recording stub for spike S1's fresh captures. Binds 127.0.0.1 only; calls nothing upstream.

It extends the S2 recording stub with what S1 needs (any other path is recorded and answered 404):
  POST .../responses           the OpenAI Responses wire (Codex): an SSE stream ending in response.completed
  POST .../messages            Anthropic messages (Claude Code), with the reported usage inflated (--inflate)
and it records each exchange as one JSON line: the header NAMES only (no value is kept), the full request
body and the reply it served, so the issued call ids are known. The ledger is regenerable bulk and stays
in the scratch folder; only minimized shapes are ever committed.

Canned replies follow the S2 stub's directive lines ("STUB_RUN: <command>" becomes one shell tool call).

Usage: python3.14 capture_stub.py --ledger <file.jsonl> --port-file <file> [--inflate N]
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "s2" / "stub"))
import recording_stub as rs

_lock = threading.Lock()
SHELL_TOOLS = ("exec_command", "shell", "local_shell", "container.exec")


def _user_texts(items) -> list[str]:
    out = []
    for it in items or []:
        if isinstance(it, dict) and it.get("role") == "user" and it.get("type", "message") == "message":
            c = it.get("content")
            out.append(c if isinstance(c, str) else "\n".join(
                p.get("text", "") for p in c or [] if isinstance(p, dict)))
    return out


class Handler(rs.Handler):
    server_version = "s1-stub/1"

    def _record(self, body_obj, raw_len):  # replaced: names only, and the reply is added by _log
        self._req = {"t": time.time(), "method": self.command, "path": self.path,
                     "header_names": sorted({k.lower() for k in self.headers}), "body_bytes": raw_len,
                     "body": body_obj}
        if self.command != "POST":
            self._log(None)

    def _log(self, reply):
        with _lock, open(self.server.ledger, "a", encoding="utf-8") as fh:
            self.server.seq += 1
            fh.write(json.dumps({"seq": self.server.seq, **self._req, "reply": reply}, ensure_ascii=False) + "\n")

    def _send_json(self, code, obj):
        if getattr(self, "_anth_in", None) and isinstance(obj, dict) and obj.get("type") == "message":
            obj = dict(obj, usage=dict(obj["usage"], input_tokens=self._anth_in))
        if self.command == "POST":
            self._log({"status": code, "json": obj})
        super()._send_json(code, obj)

    def _send_sse(self, events):
        if getattr(self, "_anth_in", None) and events and events[0][0] == "message_start":
            events = json.loads(json.dumps(events))
            events[0][1]["message"]["usage"]["input_tokens"] = self._anth_in
        self._log({"status": 200, "sse": [p for _, p in events]})
        super()._send_sse(events)

    def do_POST(self):
        if self.path.split("?")[0].rstrip("/").endswith("/responses"):  # any other path: recorded, 404
            body, n = self._read()
            self._record(body, n)
            return self._responses(body or {})
        return super().do_POST()

    # -- usage: inflated on request so the harness nears its window ------------------------------
    def _inflated(self, n_user: int) -> int:
        return max(10, self.server.inflate * n_user)

    def _anthropic(self, body):
        self._anth_in = self._inflated(len(_user_texts(body.get("messages"))))
        return super()._anthropic(body)

    # -- Responses (Codex) --------------------------------------------------------------------
    def _responses(self, body):
        items, tools = body.get("input") or [], body.get("tools") or []
        names = [t.get("name") or t.get("type") for t in tools]
        call, texts, done = None, _user_texts(items), 0
        for it in reversed(items):  # tool calls already answered since the newest user text
            if it.get("type", "message") == "message" and it.get("role") == "user":
                break
            done += str(it.get("type")).endswith("_output")
        directives = rs._directives(texts[-1]) if texts else []
        if done < len(directives) and directives[done][0] == "RUN":
            tool = next((n for n in SHELL_TOOLS if n in names), None)
            if tool:
                cmd = directives[done][1]
                args = {"cmd": cmd} if tool == "exec_command" else {"command": ["bash", "-lc", cmd]}
                call = {"type": "function_call", "call_id": "call_" + uuid.uuid4().hex[:12], "name": tool,
                        "arguments": json.dumps(args), "status": "completed"}
        item = call or {"type": "message", "role": "assistant", "status": "completed", "id": "msg_" + uuid.uuid4().hex[:8],
                        "content": [{"type": "output_text", "text": "Stub reply.", "annotations": []}]}
        n_in = self._inflated(len(texts))
        usage = {"input_tokens": n_in, "input_tokens_details": {"cached_tokens": 0}, "output_tokens": 5,
                 "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": n_in + 5}
        raw = sse_bytes(item, usage, body.get("model") or "stub-model")
        self._log({"status": 200, "sse_raw": raw.decode()})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def sse_bytes(item: dict, usage: dict, model: str) -> bytes:
    """One Responses SSE stream: created, the item added, its text delta, the item done, completed."""
    rid = f"resp_s1{time.time_ns()}"
    evs = [{"type": "response.created", "response": {"id": rid, "status": "in_progress", "model": model}},
           {"type": "response.output_item.added", "output_index": 0, "item": dict(item, status="in_progress")}]
    if item["type"] == "message":
        evs.append({"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                    "item_id": item["id"], "delta": item["content"][0]["text"]})
    evs += [{"type": "response.output_item.done", "output_index": 0, "item": item},
            {"type": "response.completed", "response": {"id": rid, "status": "completed", "model": model,
                                                        "output": [item], "usage": usage}}]
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(dict(e, sequence_number=n))}\n\n".encode()
                    for n, e in enumerate(evs))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--port-file", required=True)
    ap.add_argument("--inflate", type=int, default=0, help="reported input tokens per user message (0: 10)")
    a = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    srv.daemon_threads, srv.ledger, srv.seq, srv.inflate = True, a.ledger, 0, a.inflate
    Path(a.port_file).write_text(str(srv.server_address[1]))
    srv.serve_forever()


if __name__ == "__main__":
    main()
