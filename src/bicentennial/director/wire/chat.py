"""Single-choice chat-completions codec promoted from S6a."""

import json
from copy import deepcopy

from .responses import parse_sse

__all__ = ["parse_request", "build_response", "sse_chunks", "sse_bytes",
           "parse_sse", "chunks_to_response", "usage_estimate"]


def parse_request(body: dict) -> dict:
    """Validate the routing fields, preserving all other harness parameters."""
    if (not isinstance(body, dict) or not isinstance(body.get("model"), str) or not body["model"]
            or not isinstance(body.get("messages"), list)
            or not all(isinstance(m, dict) and m.get("role") in
                       ("system", "developer", "user", "assistant", "tool") for m in body["messages"])
            or not isinstance(body.get("tools", []), list)
            or not all(isinstance(t, dict) and t.get("type") == "function" and
                       isinstance(t.get("function"), dict) and isinstance(t["function"].get("name"), str)
                       for t in body.get("tools", []))
            or type(body.get("stream", False)) is not bool):
        raise ValueError("invalid_chat_request")
    return deepcopy(dict(body, tools=body.get("tools", []), stream=body.get("stream", False)))


def usage_estimate(body: dict, response: dict) -> dict:
    """Ceil compact sorted UTF-8 JSON byte lengths / 4, matching S6a's canon proxy."""
    def size(value):
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
    msg = response["choices"][0]["message"]
    return {"prompt_tokens": (size(body.get("messages")) + size(body.get("tools") or []) + 3) // 4,
            "completion_tokens": (size(msg) + 3) // 4, "estimated": True}


def build_response(body: dict, message: dict, *, response_id: str = "bc", created: int = 0) -> dict:
    """Build the S6a envelope with caller-owned identity/time (no clock or randomness)."""
    if (message.get("role", "assistant") != "assistant" or not isinstance(message.get("content", ""), str)
            or set(message) - {"role", "content", "reasoning_content", "tool_calls"}):
        raise ValueError("invalid_chat_message")
    msg = deepcopy({"role": "assistant", "content": "", **message})
    for key in ("reasoning_content", "tool_calls"):
        if key in msg and not msg[key]:
            del msg[key]
    resp = {"id": response_id, "object": "chat.completion", "created": created, "model": body["model"],
            "choices": [{"index": 0, "message": msg,
                         "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}]}
    usage = usage_estimate(body, resp)
    resp["usage"] = dict(usage, total_tokens=usage["prompt_tokens"] + usage["completion_tokens"])
    return resp


def sse_chunks(resp: dict) -> list[dict]:
    msg = resp["choices"][0]["message"]
    base = {"id": resp.get("id", "bc"), "object": "chat.completion.chunk",
            "created": resp.get("created", 0), "model": resp.get("model")}
    delta = {"role": "assistant"}
    for key in ("content", "reasoning_content"):
        if msg.get(key):
            delta[key] = msg[key]
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{"index": i, **tc} for i, tc in enumerate(msg["tool_calls"])]
    return deepcopy([{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                     {**base, "choices": [{"index": 0, "delta": {},
                                           "finish_reason": resp["choices"][0]["finish_reason"]}]},
                     {**base, "choices": [], "usage": resp.get("usage")}])


def sse_bytes(resp: dict) -> bytes:
    return b"".join(b"data: " + json.dumps(c).encode() + b"\n\n" for c in sse_chunks(resp)) + b"data: [DONE]\n\n"


def chunks_to_response(chunks: list[dict]) -> dict:
    """Reassemble the three chunks emitted by this codec, including empty text."""
    first, last, usage = deepcopy(chunks)
    msg = {"content": "", **first["choices"][0]["delta"]}
    if "tool_calls" in msg:
        msg["tool_calls"] = [{k: v for k, v in t.items() if k != "index"} for t in msg["tool_calls"]]
    return {**{k: first[k] for k in ("id", "created", "model")}, "object": "chat.completion",
            "choices": [{"index": 0, "message": msg, "finish_reason": last["choices"][0]["finish_reason"]}],
            "usage": usage["usage"]}
