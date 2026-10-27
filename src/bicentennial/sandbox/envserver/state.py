"""Canonical environment operations and scorer trace projection."""

import json

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import validate

from .ask import ask_user


def state_hash(state) -> str:
    return sha256_canon(state)


class State:
    def __init__(self, seed):
        validate("env_seed", seed)
        seed = json.loads(canon(seed))
        self.state = seed["state"]
        self.tools = {tool["name"]: tool for tool in seed["tools"]}

    def call(self, name, args) -> tuple[str, bool]:
        tool = self.tools.get(name) if isinstance(name, str) else None
        if name != "ask_user" and tool is None:
            raise ValueError("unknown tool")
        required = {"question"} if name == "ask_user" else {tool["key_arg"]}
        if tool and tool["value_arg"] is not None:
            required.add(tool["value_arg"])
        if type(args) is not dict or set(args) != required:
            raise ValueError("arguments must contain exactly the declared keys")
        if name == "ask_user":
            return ask_user(args["question"]), False
        key = args[tool["key_arg"]]
        if type(key) is not str:
            raise ValueError("key must be a string")
        canon(args)
        collection, op = self.state[tool["collection"]], tool["op"]
        if op in {"get", "remove"} and key not in collection:
            raise ValueError("unknown key")
        if op == "add" and key in collection:
            raise ValueError("key already exists")
        before = state_hash(self.state)
        if op in {"set", "add"}:
            value = json.loads(canon(args[tool["value_arg"]]))
            collection[key] = value
        else:
            value = collection[key]
            if op == "remove":
                del collection[key]
        return canon(value).decode("utf-8"), before != state_hash(self.state)


def trace(records, action_tools) -> tuple[bool, bool, int | None]:
    actions = [row for row in records if row["type"] == "action"]
    return (any(row["asked_user"] for row in actions),
            any(row["state_changed"] for row in actions),
            next((row["t_sim"] for row in actions
                  if row["ok"] and row["tool"] in action_tools), None))
