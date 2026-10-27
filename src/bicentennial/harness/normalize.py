"""Normalize only the pinned terminal and text-only MCP result envelopes."""

import hashlib
import json

from bicentennial.genres.g1_software.diffs import normalise as repo_normalise

ENV_TOOLS = {"get_mail", "get_note", "get_calendar_entry", "get_booking", "get_option", "book",
             "cancel_booking", "add_note", "send_mail", "add_calendar_entry", "search_mail", "search_notes",
             "search_calendar", "search_bookings", "search_options", "ask_user"}


def normalise(call, content: str) -> dict:
    try:
        obj = json.loads(content)
        if type(obj) is not dict:
            raise ValueError
        if call["name"] in ("git", "read_file"):
            if type(obj.get("exit_code")) is not int or obj["exit_code"] != 0 or obj.get("error") is not None:
                raise ValueError
            key = "stdout" if call["name"] == "git" else "content"
            return {key: repo_normalise(obj["output"].encode())}
        # Hermes d923a5e: tool_search.py:561-586, model_tools.py:701-753:
        # a single local bridge call re-dispatches directly, without a batch envelope.
        # mcp_tool_handlers.py:435-480,537-549 and mcp_tool_content.py:31-33:
        # text is joined/capped, success is {result: text}, failure {error: text}.
        if call["name"] not in ENV_TOOLS:
            raise ValueError
        if set(obj) == {"result"} and type(obj["result"]) is str:
            return {"text": obj["result"], "isError": False}
        if set(obj) == {"error"} and type(obj["error"]) is str:
            return {"text": obj["error"], "isError": True}
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, RecursionError):
        pass
    return {"unparsed_sha256": hashlib.sha256(content.encode("utf-8", "surrogatepass")).hexdigest()}
