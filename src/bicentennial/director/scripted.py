"""T1 deterministic wiring stubs, never a measure of model quality (RING0 §2)."""

import re
from hashlib import sha256
from math import isqrt

from bicentennial.canon import canon
from bicentennial.director.responder import Call, Reply
from bicentennial.director.wire import chat, responses

WRITE_ARGS = {"hermes-native": ("memory", {"action": "add", "target": "memory"}, "content")}
VECTOR_SCALE = 1_000_000_000


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(p["text"] for p in content or [] if isinstance(p, dict)
                   and p.get("type") in ("text", "input_text", "output_text")
                   and isinstance(p.get("text"), str))


def _messages(call):
    if call.wire == "chat":
        return call.body.get("messages", [])
    if call.wire in ("responses", "responses_compact"):
        return responses.typed(call.body.get("input", []))
    raise ValueError("unsupported scripted wire")


def _cut(text, call):
    keys = ("max_tokens", "max_completion_tokens") if call.wire == "chat" else ("max_output_tokens",)
    limits = [call.body[k] for k in keys if call.body.get(k) is not None]
    if any(type(n) is not int or n < 0 for n in limits):
        raise ValueError("invalid output-token limit")
    # R03's provisional ceil(UTF-8 bytes / 4) estimator; preserve whole code points.
    return text.encode()[:4 * min(limits)].decode("utf-8", "ignore") if limits else text[:4096]


def _vector(text, dimension):
    counts = [0] * dimension
    for token in re.findall(r"\w+", text.lower()):
        digest = sha256(token.encode()).digest()
        counts[int.from_bytes(digest[:8], "big") % dimension] += -1 if digest[8] & 1 else 1
    squared = sum(n * n for n in counts)
    if not squared:
        return counts
    # Round each normalised coordinate to 1e-9 using integer arithmetic only.
    vector = []
    for count in counts:
        numerator = count * count * VECTOR_SCALE * VECTOR_SCALE
        component = isqrt(numerator // squared)
        if 4 * numerator > squared * (2 * component + 1) ** 2:
            component += 1
        vector.append(-component if count < 0 else component)
    return vector


def _usage(wire, estimate):
    """R03's estimate in the wire's own usage keys, with the total."""
    n_in, n_out = estimate["prompt_tokens"], estimate["completion_tokens"]
    if wire == "embeddings":
        return {"prompt_tokens": n_in, "total_tokens": n_in, "estimated": True}
    keys = ("input_tokens", "output_tokens") if wire in ("responses", "responses_compact") else (
        "prompt_tokens", "completion_tokens")
    return {keys[0]: n_in, keys[1]: n_out, "total_tokens": n_in + n_out, "estimated": True}


def _kind(call):
    """The Director's ledger roles (R08 route_role): compaction arrives as summariser, and
    titles, summaries and extraction arrive as aux with their task as the subrole."""
    if call.role in ("write_turn", "memory_write"):
        return "write"
    if call.role == "summariser" or (call.role == "aux" and call.subrole in ("summariser", "extraction")):
        return "extract"
    if call.role == "aux":
        return "title" if call.subrole == "title_generation" else "empty"
    raise ValueError("unsupported scripted role")


class ScriptedResponder:
    """Implement R08's Responder for a loaded R13a system-entry dictionary."""

    def __init__(self, system_entry):
        if system_entry.get("structured_formats"):
            raise ValueError("scripted structured formats are not implemented")
        self.write_tools = tuple(t["tool"] for t in system_entry.get("write_tools", []))
        self.write_args = WRITE_ARGS.get(system_entry["name"])
        if self.write_tools and (self.write_args is None or any(
                tool != self.write_args[0] for tool in self.write_tools)):
            raise ValueError("scripted write arguments are not declared for this system")
        if self.write_args:
            name, fixed, content = self.write_args
            self.write_args = name, dict(fixed), content
        self.embedding_dim = system_entry.get("embedding_dim")

    def respond(self, call: Call) -> Reply:
        text, calls, vectors, scale = "", (), None, None
        if call.role == "embeddings":
            if call.wire != "embeddings":
                raise ValueError("embeddings need the embeddings wire")
            dimension = self.embedding_dim
            if type(dimension) is not int or dimension <= 0:
                raise ValueError("scripted embeddings need a positive embedding_dim")
            if "dimensions" in call.body and call.body["dimensions"] != dimension:
                raise ValueError("embedding dimensions differ from the system entry")
            inputs = call.body.get("input")
            inputs = [inputs] if isinstance(inputs, str) else inputs
            if not isinstance(inputs, list) or not inputs or not all(isinstance(t, str) for t in inputs):
                raise ValueError("scripted embeddings need text, not token IDs")
            vectors, scale = [_vector(t, dimension) for t in inputs], VECTOR_SCALE
            usage_body = {"messages": inputs, "tools": []}
        else:
            kind = _kind(call)
            messages = _messages(call)
            if kind == "write":
                calls = self._write(call, messages)
            elif kind == "extract":
                text = _cut("\n".join(_text(m.get("content"))[:240] for m in messages
                                     if m.get("type", "message") == "message"
                                     and m.get("role") in ("user", "assistant")), call)
            elif kind == "title":
                text = "Session"
            usage_body = call.body if call.wire == "chat" else {
                "messages": messages, "tools": call.body.get("tools", [])}
        message = {"role": "assistant", "content": text}
        if calls:
            message["tool_calls"] = [{"type": "function", "function": c} for c in calls]
        usage = _usage(call.wire, chat.usage_estimate(usage_body, {"choices": [{"message": message}]}))
        return Reply(200, "scripted", "scripted", call.model, text=text, tool_calls=calls,
                     embedding=vectors, scale=scale, usage=usage, upstream=[])

    def _write(self, call, messages):
        offered = [t.get("function", {}) if call.wire == "chat" else t for t in call.body.get("tools", [])]
        tool = next((t for name in self.write_tools for t in offered if t.get("name") == name), None)
        users = [i for i, m in enumerate(messages) if m.get("type", "message") == "message" and m.get("role") == "user"]
        # One write per user message: a tool result after it means the write was already issued,
        # whatever the tool answered (RING0 §2: the tool's answer is never retried).
        if tool is None or not users or any(m.get("role") == "tool" or m.get("type") == "function_call_output"
                                            for m in messages[users[-1] + 1:]):
            return ()
        # A memory_write request is recognised by its last user message, the harness's own
        # memory-write prompt, so the content is the conversation's latest user message before it.
        if call.role == "memory_write":
            users = users[:-1]
            if not users:
                return ()
        user = messages[users[-1]]
        name, fixed, content_key = self.write_args
        content = _text(user.get("content"))
        limit = tool.get("parameters", {}).get("properties", {}).get(content_key, {}).get("maxLength")
        if limit is not None:
            if type(limit) is not int or limit < 0:
                raise ValueError("invalid content maxLength")
            content = content[:limit]
        arguments = canon({**fixed, content_key: content}).decode()
        return ({"name": name, "arguments": arguments},)
