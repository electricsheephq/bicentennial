"""The only socket-opening module; provider error text never leaves classification."""
import json
import re
import string
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass

from bicentennial.director.wire.responses import (
    error_objects,
    parse_sse,
    sse_auth_error,
    typed,
)

MAX_BODY = 8 * 1024 * 1024
RETRYABLE = ("rate", "overload", "concurrency", "server")
ERROR_FIELDS = ("code", "type", "status", "status_code", "message", "detail")


@dataclass(frozen=True)
class Upstream:
    name: str
    model: str
    base_url: str
    wire: str
    spend: object
    price: object
    max_output_tokens: int
    glm_plan: bool = False
    effort: str | None = None
    timeout_s: int = 900
    send_cap: bool = True

    def __post_init__(self):
        url = urllib.parse.urlsplit(self.base_url)
        if (not isinstance(self.name, str) or not re.fullmatch(r"[a-z0-9_]+", self.name)
                or not isinstance(self.model, str) or not self.model or self.wire not in ("chat", "responses")
                or url.scheme not in ("http", "https") or not url.hostname or url.username or url.password
                or url.query or url.fragment or type(self.max_output_tokens) is not int or self.max_output_tokens < 1
                or type(self.glm_plan) is not bool or (self.effort is not None and (not isinstance(self.effort, str) or not self.effort))
                or type(self.timeout_s) is not int or self.timeout_s < 1 or type(self.send_cap) is not bool
                or asdict(self.price) != self.spend.policy["price"]):
            raise ValueError("invalid upstream or spend policy")


def redact(text):
    cut, text = len(text) > 4096, text[:4096]
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", text, flags=re.I)
    text = re.sub(r"\d{6,}", "<n>", text)
    if cut and len(text) <= 600:
        text = text.rstrip(string.ascii_letters + string.digits + "_.+@-")
    return text[:600]


def shape(obj, key=""):
    if isinstance(obj, dict):
        return {k: shape(v, k) for k, v in obj.items()}
    if isinstance(obj, list):
        return [shape(v) for v in obj[:3]]
    if isinstance(obj, str):
        return redact(obj)[:80] if key in ("code", "type", "param") else "str"
    return type(obj).__name__


def sol_category(status, text):
    for cat, pattern in (("quota", r"usage[ _]limit|quota|insufficient|exceeded your|billing"),
                         ("concurrency", r"concurren"), ("rate", r"rate.?limit|too many"),
                         ("overload", r"overload|capacity")):
        if re.search(pattern, text.lower()) or (cat == "rate" and status == 429) or (cat == "overload" and status in (502, 503, 529)):
            return cat
    return "server" if status >= 500 else "other"


def _typed(text, calls):
    if not isinstance(text, str) or not all(isinstance(c["name"], str) and isinstance(c["arguments"], str) for c in calls):
        raise TypeError("non-string reply field")
    return dict(text=text, tool_calls=calls, forward=True)


def wire_body(call):
    if call.wire == "responses":
        return dict(call.body, model=call.model, stream=True, input=typed(call.body.get("input")))
    return dict({k: v for k, v in call.body.items() if k not in ("stream", "stream_options")}, model=call.model, stream=False)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(up, data, headers):
    result = dict(status=-1, category=None, retry_after_s=None, body_shape=None, n_unparsed=0,
                  n_dropped_items=0, served_model=None, usage=None, text="", tool_calls=(), forward=False, stop_reason=None, body_read_error=None)
    req = urllib.request.Request(up.base_url.rstrip("/") + ("/responses" if up.wire == "responses" else "/chat/completions"),
                                 data=data, headers=headers, method="POST")
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        try:
            response = opener.open(req, timeout=up.timeout_s)
        except urllib.error.HTTPError as exc:
            response = exc
        with response:
            result["status"] = status = response.code
            retry = response.headers.get("retry-after")
            result["retry_after_s"] = int(retry) if retry and retry.isascii() and retry.isdigit() else 60 if retry is not None else None
            if status in (401, 403) or (400 <= status < 500 and status != 429):
                result.update(category="other", stop_reason=f"upstream_{status}" if status in (401, 403) else f"upstream_invalid_request_{status}")
                return result
            try:
                raw = response.read(MAX_BODY + 1)
            except Exception as exc:
                if status == 200:
                    raise
                result.update(category=sol_category(status, ""), body_read_error=type(exc).__name__)
                return result
        if len(raw) > MAX_BODY:
            result["category"] = "error:oversize"
            return result
    except Exception as exc:
        result.update(category=f"error:{type(exc).__name__}")
        return result
    if status != 200:
        result["category"] = "other" if 200 <= status < 400 else sol_category(status, raw.decode("utf-8", "replace"))
        try:
            result["body_shape"] = shape(json.loads(raw))
        except ValueError:
            result["body_shape"] = "non-json"
        return result
    if up.wire == "responses":
        events = parse_sse(raw)
        terminal = next((e for e in reversed(events) if e.get("type") in ("response.completed", "response.incomplete", "response.failed", "error")), {})
        body = terminal.get("response") if isinstance(terminal.get("response"), dict) else {}
        errors = [o["category"] for e in events for o in error_objects(e)]
        result["n_unparsed"] = sum(e.get("type") == "director.unparsed" for e in events)
        if sse_auth_error(events):
            result.update(category="auth_sse", stop_reason="upstream_sse_auth")
        elif result["n_unparsed"]:
            result["category"] = "unparsed"
        elif errors or any(e.get("type") == "response.failed" for e in events) or terminal.get("type") not in ("response.completed", "response.incomplete"):
            result["category"] = next((c for c in ("quota", "concurrency", "rate", "overload") if c in errors), "other")
        else:
            try:
                items = [e["item"] for e in events if e.get("type") == "response.output_item.done" and isinstance(e.get("item"), dict)]
                messages = [i for i in items if i.get("type") == "message"]
                text = "".join(p.get("text") or "" for i in messages for p in i.get("content") or [] if p.get("type") == "output_text") if messages else "".join(e.get("delta") or "" for e in events if e.get("type") == "response.output_text.delta")
                calls = tuple({"name": i["name"], "arguments": i.get("arguments", "{}")} for i in items if i.get("type") == "function_call")
                result.update(_typed(text, calls), n_dropped_items=sum(i.get("type") not in ("message", "function_call") for i in items))
            except (TypeError, KeyError, AttributeError):
                result["category"], result["n_unparsed"] = "unparsed", 1
    else:
        try:
            body = json.loads(raw)
            if isinstance(body, dict) and body.get("error"):
                # a non-dict error is wrapped as {"message": ...} and categorised by its text, as the Responses wire does
                error = body["error"] if isinstance(body["error"], dict) else {"message": str(body["error"])}
                result["category"] = sol_category(0, json.dumps({k: error[k] for k in ERROR_FIELDS if k in error}))
            else:
                msg = body["choices"][0]["message"]
                content = "" if msg.get("content") is None else msg["content"]
                result.update(_typed(content, tuple({"name": t["function"]["name"], "arguments": t["function"]["arguments"]} for t in msg.get("tool_calls") or [])))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            body, result["category"], result["n_unparsed"] = {}, "unparsed", 1
    usage = body.get("usage") if isinstance(body, dict) else None
    result["usage"] = {k: v for k, v in usage.items() if type(v) is int} if isinstance(usage, dict) else None
    result["served_model"] = body.get("model") if isinstance(body.get("model"), str) and body["model"] else None
    return result
