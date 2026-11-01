"""S7 chat-to-Responses translation, with reasoning pinned by the live upstream."""

from dataclasses import replace

from bicentennial.director.responder import Reply
from bicentennial.director.wire.responses import typed

CHAT_KEYS = frozenset({"model", "messages", "tools", "tool_choice", "stream", "stream_options",
                       "max_tokens", "max_completion_tokens", "reasoning_effort", "parallel_tool_calls"})


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(p, dict) and p.get("type") == "text"
                                         and isinstance(p.get("text"), str) for p in content):
        return "".join(p["text"] for p in content)
    raise ValueError("bridge_unsupported_content")


def _listed(value):
    return [] if value is None else value  # an explicit null collection is an empty one


def to_responses(body, *, effort):
    unknown = body.keys() - CHAT_KEYS
    if unknown:
        raise ValueError(f"bridge_unmapped_key:{sorted(unknown)[0]}")
    instructions, items = [], []
    for message in body.get("messages", []):
        role = message["role"]
        content = message.get("content")
        text = "" if role == "assistant" and content is None else _text(content)
        if role in ("system", "developer"):
            # Instructions take only the leading system messages; hoisting a later one would move it.
            if items:
                raise ValueError("bridge_late_system")
            instructions.append(text)
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": text})
        elif role in ("user", "assistant"):
            if text or role == "user":
                items.append({"type": "message", "role": role, "content": text})
            for call in _listed(message.get("tool_calls")):
                if role != "assistant" or call.get("type") != "function":
                    raise ValueError("bridge_unsupported_tool_call")
                function = call["function"]
                items.append({"type": "function_call", "call_id": call["id"], "name": function["name"],
                              "arguments": function["arguments"]})
        else:
            raise ValueError("bridge_unsupported_role")
    out = {"instructions": "\n\n".join(instructions), "input": typed(items),
           "store": False, "reasoning": {"effort": effort}}
    tools = []
    for tool in _listed(body.get("tools")):
        if tool.get("type") != "function":
            raise ValueError("bridge_unsupported_tool")
        function = tool["function"]
        # Chat functions are non-strict unless they say so; Responses is strict when strict is omitted.
        strict = function.get("strict", False)
        if strict is not None and type(strict) is not bool:
            raise ValueError("bridge_unsupported_tool")
        tools.append({"type": "function", "name": function["name"],
                      "description": function.get("description", ""), "parameters": function.get("parameters", {}),
                      "strict": strict is True})
    if tools:
        out["tools"] = tools
    if "tool_choice" in body:
        choice = body["tool_choice"]
        if isinstance(choice, str):
            out["tool_choice"] = choice
        elif isinstance(choice, dict) and choice.get("type") == "function":
            out["tool_choice"] = {"type": "function", "name": choice["function"]["name"]}
        else:
            raise ValueError("bridge_unsupported_tool_choice")
    if "parallel_tool_calls" in body:
        out["parallel_tool_calls"] = body["parallel_tool_calls"]
    return out


def chat_usage(usage):
    if not isinstance(usage, dict) or any(type(usage.get(k)) is not int for k in ("input_tokens", "output_tokens")):
        return None
    prompt, completion = usage["input_tokens"], usage["output_tokens"]
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


class ResponsesBridge:
    wire = "responses"

    def __init__(self, inner):
        live = inner
        while not hasattr(live, "upstreams") and hasattr(live, "inner"):
            live = live.inner
        self.upstreams = getattr(live, "upstreams", {})
        if not self.upstreams or any(not up.effort for up in self.upstreams.values()):
            raise ValueError("bridge_effort_unpinned")
        self.inner, self.failure = inner, None

    def respond(self, call):
        # A translation failure latches: nothing more is forwarded on either wire, and the inner stack stops.
        if self.failure:
            return Reply(503, "live_stopped", "live", call.model)
        if call.wire != "chat":
            return self.inner.respond(call)
        try:
            up = self.upstreams.get(call.model)
            if up is None:
                raise ValueError("bridge_no_upstream")
            body = to_responses(call.body, effort=up.effort)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            # A structural failure latches too, under a fixed code that never echoes the request.
            self.failure = str(exc) if type(exc) is ValueError else "bridge_malformed"
            if hasattr(self.inner, "stop"):
                self.inner.stop(self.failure)
            raise ValueError(self.failure) from None
        reply = self.inner.respond(replace(call, wire="responses", body=body))
        return replace(reply, usage=chat_usage(reply.usage))

    def state(self):
        state = self.inner.state()
        return dict(state, stopped=True, stop_reason=self.failure) if self.failure else state

    def served_identities(self):
        return self.inner.served_identities()
