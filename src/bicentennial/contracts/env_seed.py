"""Semantic checks for the environment seed, loaded by run.validate."""

from .run import register_check


def check_env_seed(seed):
    if any(type(collection) is not dict for collection in seed["state"].values()):
        raise ValueError("state collections must be objects")
    names = [tool["name"] for tool in seed["tools"]]
    if len(names) != len(set(names)) or "ask_user" in names:
        raise ValueError("duplicate or reserved tool name")
    for tool in seed["tools"]:
        if tool["collection"] not in seed["state"]:
            raise ValueError("unknown collection")
        if tool["op"] in {"set", "add"}:
            if not tool["value_arg"] or tool["value_arg"] == tool["key_arg"]:
                raise ValueError("distinct value_arg required")
        elif tool["value_arg"] is not None:
            raise ValueError("value_arg must be null")


register_check("env_seed", check_env_seed)
