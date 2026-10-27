"""Validated G2 writes and read-only discovery over canonical state."""

from bicentennial.canon import canon

from ..state import State
from .catalog import COLLECTIONS, G2_ENV_ID, SEARCH_TOOLS, SEED_TOOLS, VALUE_SCHEMAS


def check_value(value) -> bool:
    """Recognise the non-empty string maps accepted by all G2 writes."""
    return (type(value) is dict and len(value) >= 1
            and all(type(k) is str and k != "" and k not in ("items", "t_sim", "from")
                    and type(v) is str and v != "" for k, v in value.items()))


def _contains(value, query):
    if type(value) is str:
        return query in value
    if type(value) is dict:
        return any(_contains(child, query) for child in value.values())
    if type(value) is list:
        return any(_contains(child, query) for child in value)
    return False


def search(collection, query) -> dict:
    """Select entries by case-sensitive substrings of their string leaves."""
    return {key: value for key, value in collection.items()
            if query == "" or _contains(value, query)}


class G2State(State):
    def __init__(self, seed):
        super().__init__(seed)
        if seed["env_id"] != G2_ENV_ID:
            raise ValueError("not a G2 seed")
        if seed["tools"] != [dict(t) for t in SEED_TOOLS]:
            raise ValueError("G2 seed tools differ")
        if set(seed["state"]) != set(COLLECTIONS):
            raise ValueError("G2 seed collections differ")
        self.tools = {
            row["name"]: (dict(row, value_schema=VALUE_SCHEMAS[row["name"]])
                          if row["name"] in VALUE_SCHEMAS else dict(row))
            for row in (*SEED_TOOLS, *SEARCH_TOOLS)
        }

    def call(self, name, args) -> tuple[str, bool]:
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool and tool["op"] == "search":
            if type(args) is not dict or set(args) != {"query"}:
                raise ValueError("arguments must contain exactly the declared keys")
            if type(args["query"]) is not str:
                raise ValueError("query must be a string")
            return canon(search(self.state[tool["collection"]], args["query"])).decode("utf-8"), False
        if (tool and tool["value_arg"] is not None and type(args) is dict
                and set(args) == {tool["key_arg"], tool["value_arg"]}
                and type(args[tool["key_arg"]]) is str
                and not check_value(args[tool["value_arg"]])):
            raise ValueError(f"{tool['value_arg']} does not match its schema")
        return super().call(name, args)
