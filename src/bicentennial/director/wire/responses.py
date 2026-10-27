"""S6b Responses frames; provider error text is private to classification."""

import json
import re
import time

_AUTH = re.compile(r"invalid[ _]api[ _]key|invalid[ _]token|token[ _](expired|invalid|revoked)|unauthori[sz]ed|"
                   r"authentication|permission_denied|forbidden|account_deactivated|access[ _]denied|"
                   r"gateway_auth_failed|failed to extract accountid from token", re.IGNORECASE)
_FIELDS = ("code", "type", "status", "status_code", "message", "detail")


def typed(items) -> list:
    """Wrap message strings in role-appropriate text parts; preserve all other items."""
    if isinstance(items, str):
        items = [{"type": "message", "role": "user", "content": items}]
    return [dict(it, content=[{"type": "output_text" if it.get("role") == "assistant" else "input_text",
                               "text": it["content"]}])
            if isinstance(it, dict) and it.get("type", "message") == "message" and isinstance(it.get("content"), str)
            else it for it in items or []]


def parse_sse(raw: bytes) -> list[dict]:
    events = []
    for block in raw.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.split("\n") if line.startswith("data:"))
        if data and data != "[DONE]":
            try:
                ev = json.loads(data)
            except ValueError:
                ev = None
            events.append(ev if isinstance(ev, dict) else {"type": "director.unparsed"})
    return events


def sse_bytes(items: list[dict], usage: dict, model: str, *, response_id: str | None = None) -> bytes:
    """S6b stream: created, one text delta per message, done items, completed.

    response_id defaults to S6b's wall-clock id; the director passes a keyed one."""
    rid, evs = response_id or f"resp_bc{time.time_ns()}", []
    evs.append({"type": "response.created", "response": {"id": rid, "object": "response", "status": "in_progress",
                                                         "model": model}})
    for i, it in enumerate(items):
        if it["type"] == "message":
            evs.append({"type": "response.output_text.delta", "output_index": i, "content_index": 0,
                        "delta": it["content"][0]["text"]})
        evs.append({"type": "response.output_item.done", "output_index": i, "item": it})
    evs.append({"type": "response.completed", "response": {"id": rid, "object": "response", "status": "completed",
                                                           "model": model, "output": [], "usage": usage}})
    return b"".join(f"event: {e['type']}\ndata: {json.dumps(dict(e, sequence_number=n))}\n\n".encode()
                    for n, e in enumerate(evs))


def _provider_errors(e: dict) -> list[dict]:
    objs = [e] if e.get("type") == "error" else []
    resp = e.get("response") if isinstance(e.get("response"), dict) else {}
    objs += [resp.get("error"), e.get("error")]
    return [o if isinstance(o, dict) else {"message": o} for o in objs if o]


def _error_text(o: dict, etype) -> str:
    return " ".join(str(o[k]) for k in _FIELDS if o.get(k) is not None and o.get(k) != etype)


def _is_auth(o: dict, etype) -> bool:
    return bool(_AUTH.search(_error_text(o, etype)) or any(str(o.get(k)) in ("401", "403")
                for k in ("code", "status", "status_code")))


def _category(o: dict) -> str:
    # S6b's sol_category(0, json.dumps(basis)): an in-stream error carries no HTTP status, so
    # status-only labels (rate on 429, overload on 5xx, server) never apply and digits never match.
    text = json.dumps({k: o[k] for k in _FIELDS if k in o}).lower()
    for label, pattern in (("quota", r"usage[ _]limit|quota|insufficient|exceeded your|billing"),
                           ("concurrency", r"concurren"), ("rate", r"rate.?limit|too many"),
                           ("overload", r"overload|capacity")):
        if re.search(pattern, text):
            return label
    return "other"


def error_objects(event: dict) -> list[dict]:
    """Same S6b error-object discovery, returning only fixed category labels."""
    return [{"category": "auth_sse" if _is_auth(o, event.get("type")) else _category(o)}
            for o in _provider_errors(event)]


def sse_auth_error(events: list[dict]) -> bool:
    return any(_is_auth(o, e.get("type")) for e in events for o in _provider_errors(e))
