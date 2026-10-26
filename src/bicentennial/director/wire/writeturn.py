"""Write-body reconstruction from S7's independent audit, not forwarding code."""

import json
from copy import deepcopy
from typing import Literal

from .responses import typed


def expected_write_body(trigger_body: dict, wire: Literal["chat", "responses"], model: str, suffix: str) -> dict:
    if wire not in ("chat", "responses"):
        raise ValueError("unsupported_write_wire")
    out = {k: v for k, v in trigger_body.items()
           if wire != "chat" or k not in {"model", "stream", "stream_options"}}
    if wire == "chat":
        out["messages"] = trigger_body["messages"] + [{"role": "user", "content": suffix}]
        out["tools"] = [t for t in trigger_body.get("tools", []) if t.get("function", {}).get("name") == "memory"]
    else:
        out["input"] = typed(trigger_body.get("input", [])) + [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": suffix}]}]
        out["tools"] = [t for t in trigger_body.get("tools", []) if t.get("name") == "memory"]
    return deepcopy(dict(out, model=model, stream=wire == "responses"))


def _exact(a, b) -> bool:
    # S7 compares JSON bytes: bool/int/float coercion is never equality here.
    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return encode(a) == encode(b)


def _untyped_eq(w, b) -> bool:
    if isinstance(b, dict) and isinstance(b.get("content"), str) and isinstance(w, dict):
        part = w.get("content")
        return (isinstance(part, list) and len(part) == 1 and isinstance(part[0], dict)
                and part[0].get("type") in ("input_text", "output_text")
                and _exact(part[0].get("text"), b["content"])
                and _exact({**w, "content": None}, {**b, "content": None}))
    return _exact(w, b)


def readback(forwarded: dict, expected: dict) -> bool:
    """Exact key set and per-key JSON equality; input may use S6b's typed adaptation."""
    if not isinstance(forwarded, dict) or not isinstance(expected, dict) or set(forwarded) != set(expected):
        return False
    for key, value in expected.items():
        got = forwarded[key]
        if _exact(got, value):
            continue
        if (key != "input" or not isinstance(got, list) or not isinstance(value, list)
                or len(got) != len(value) or not all(_untyped_eq(w, b) for w, b in zip(got, value, strict=True))):
            return False
    return True
