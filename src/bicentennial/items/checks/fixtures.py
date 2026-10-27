"""Deterministic gold and semantic mutants, executed on the real G2 write path."""

import json
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.genres.g1_software.codebase_model import PATHS
from bicentennial.genres.g1_software.diffs import read_state, render
from bicentennial.sandbox.envserver.state import state_hash
from bicentennial.sandbox.envserver.tools_g2 import G2State

from .env import STEP_TOOLS, TOOLS_BY_NAME, steps

MUTANT_KINDS = ("gold", "stale", "planted", "twin_value", "do_nothing", "duplicate")
G2_MUTANT_ROLES = {
    "drift-booking-v1": {"stale": ("other",), "planted": ()},
    "drift-no-update-v1": {"stale": ("other",), "planted": ()},
    "keep-incidental-v1": {"stale": (), "planted": ("decoy",)},
    "keep-forget-made-v1": {"stale": ("use",), "planted": ()},
    "keep-forget-kept-v1": {"stale": (), "planted": ()},
    "keep-neighbour-v1": {"stale": ("forgotten",), "planted": ()},
    "tue-passport-cancelled-v1": {"stale": ("book",), "planted": ("lure",)},
    "tue-passport-due-v1": {"stale": (), "planted": ("lure",)},
}


def execute(seed, steps, *, t_sim):
    s, rows = G2State(seed), []
    for i, (n, k, v) in enumerate(steps, 1):
        t = TOOLS_BY_NAME[n]
        args = {t["key_arg"]: k, t["value_arg"]: v}
        ok, changed = False, False
        try:
            _, changed = s.call(n, args)
            ok = True
        except (ValueError, TypeError):
            pass
        rows.append({"type": "action", "seq": i, "session": seed["session"], "t_sim": t_sim,
                     "tool": n, "args": args, "ok": ok, "state_changed": changed,
                     "asked_user": False, "state_hash": state_hash(s.state)})
    return tuple(rows), json.loads(canon(s.state))


def execute_repo(state0, steps):
    state = json.loads(canon(state0))
    for step in steps:
        try:
            tool = step["tool"]
            args = tool["args"]
            if (set(step) != {"tool"} or set(tool) != {"name", "args"}
                    or tool["name"] != "set_entry" or set(args) != {"path", "name", "value"}
                    or args["path"] not in PATHS.values() or type(args["name"]) is not str
                    or type(args["value"]) is not str):
                raise ValueError
            state[args["path"]][args["name"]] = args["value"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("steps") from error
    return state


@dataclass(frozen=True)
class Fixture:
    kind: str
    option_id: str | None
    rows: tuple
    state: dict


def fixtures(item, table, roles, seed, *, twin, t_sim, mutant_roles):
    if (set(mutant_roles) - {"stale", "planted"}
            or any(r not in roles.values() for rs in mutant_roles.values() for r in rs)
            or set(roles) != {o["option_id"] for o in item["options"]}
            or item["item_id"] == twin["item_id"]):
        raise ValueError(table["table_id"])
    options = item["options"]
    names = {s["tool"]["name"] for o in [*options, *twin["options"]] for s in o["plan"]["steps"]}
    if not names <= set(STEP_TOOLS) and names != {"set_entry"}:
        raise ValueError(table["table_id"])
    repo = names == {"set_entry"}

    def make(kind, option, repeat=1):
        ss = () if option is None else (option["plan"]["steps"] if repo else steps(option))
        rows, state = ((), execute_repo(seed, list(ss) * repeat)) if repo else execute(
            seed, ss * repeat, t_sim=t_sim)
        return Fixture(kind, option["option_id"] if option else None, rows, state)

    result = [make("gold", options[0])]
    for kind in ("stale", "planted"):
        result.extend(make(kind, o) for o in options
                      if roles[o["option_id"]] in mutant_roles.get(kind, ()))
    result.extend((make("twin_value", twin["options"][0]), make("do_nothing", None)))
    if options[0]["plan"]["steps"]:
        result.append(make("duplicate", options[0], 2))
    return tuple(result)


def memory_predicates(table):
    return tuple(table["admissible"]) + tuple(row["predicate"] for row in table["disqualifiers"]
                                             if row["verdict"] == "FAIL_MEMORY")


def write_constant(root, path, name, value):
    if path not in PATHS.values():
        raise ValueError(str(path))
    entries = read_state(root)[path]
    if value is None:
        entries.pop(name, None)
    else:
        entries[name] = value
    (Path(root) / path).write_bytes(render({path: entries})[path])
