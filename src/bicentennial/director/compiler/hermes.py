"""Read-only stream compiler for the pinned Hermes dialect."""

import json
import re
import shlex
from dataclasses import dataclass

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.genres.g1_software.diffs import CALLS, EXPLICIT, PATHS, REPO_FILES
from bicentennial.render.stream import verify_branch
from bicentennial.sandbox.envserver.tools_g2 import SEARCH_TOOLS, SEED_TOOLS

ASSISTANT, ENV_SERVER = "Noted.", "envserver"
ENV_TOOLS = frozenset(t["name"] for t in (*SEED_TOOLS, *SEARCH_TOOLS)) | {"ask_user"}


@dataclass(frozen=True)
class ProbeSession:
    index: int
    checkpoint: int
    item_ids: tuple[str, ...]
    sim_t_s: int


@dataclass(frozen=True)
class CheckCall:
    branch: str
    session: int
    turn: int
    index: int
    call: dict
    expected: dict


@dataclass(frozen=True)
class Compiled:
    script: dict
    probes: tuple[ProbeSession, ...]
    calls: tuple[CheckCall, ...]


def hermes_call(name, args):
    try:
        if type(args) is not dict:
            raise ValueError
        canon(args)
        if name == "git" and canon((name, args)) in [canon(c) for c in CALLS]:
            return {"name": "terminal", "args": {"command": shlex.join(["git", *args["argv"]])}}
        if name == "read_file" and set(args) == {"path"} and args["path"] in REPO_FILES:
            return {"name": "terminal", "args": {"command": shlex.join(["cat", "--", args["path"]])}}
        if name in ENV_TOOLS:
            return {"name": "tool_call", "args": {"calls": [
                {"name": f"mcp__{ENV_SERVER}__{name}", "arguments": args}]}}
    except (TypeError, ValueError, KeyError):
        pass
    raise ValueError(f"invalid tool: {name}")


def wire_call(name, args):
    call = hermes_call(name, args)
    return {"name": call["name"], "arguments": canon(call["args"]).decode()}


def step_call(step):
    """S04 callback: config edits extend replay's read dialect."""
    if type(step) is not dict or set(step) != {"tool"} or type(step["tool"]) is not dict:
        raise ValueError("invalid plan step")
    tool = step["tool"]
    if set(tool) != {"name", "args"}:
        raise ValueError("invalid plan step")
    name, args = tool["name"], tool["args"]
    if name == "set_entry":
        if type(args) is not dict or set(args) != {"path", "name", "value"}:
            raise ValueError("invalid plan step")
        p, n, v = args["path"], args["name"], args["value"]
        if (p not in PATHS.values() or type(n) is not str or not re.fullmatch(r"[a-z][a-z_ ]*[a-z]", n)
                or type(v) is not str or not EXPLICIT.fullmatch(v)):
            raise ValueError("invalid plan step")
        if p.endswith(".md"):
            fmt, parse = r'"- %s: %s\n"', 'key = substr($0, 3); sub(/:.*/, "", key)'
        else:
            fmt, parse = r'"\"%s\" = \"%s\"\n"', 'key = substr($0, 2); sub(/".*/, "", key)'
        program = (f"function emit() {{ printf {fmt}, n, v; done = 1 }} "
                   "NR == 1 { print; next } "
                   f"{{ {parse}; if (!done && n <= key) emit(); if (key != n) print }} "
                   "END { if (!done) emit() }")
        temp = p + ".set-entry.tmp"
        cmd = "LC_ALL=C " + shlex.join(["awk", "-v", f"n={n}", "-v", f"v={v}", program, p])
        cmd += f" > {shlex.quote(temp)} && mv {shlex.quote(temp)} {shlex.quote(p)}"
        return {"name": "terminal", "arguments": canon({"command": cmd}).decode()}
    if name == "write_file" and type(args) is dict and set(args) == {"path", "content"}:
        p, text = args["path"], args["content"]
        if p in REPO_FILES and (p.endswith(".toml") or p == "docs/decisions.md") and type(text) is str:
            return {"name": "terminal", "arguments": canon({
                "command": f"printf %s {shlex.quote(text)} > {shlex.quote(p)}"}).decode()}
    return wire_call(name, args)


def compile_script(out_dir, branch, schedule, db, *, items=(), step_s):
    manifest = verify_branch(out_dir, branch)
    with (out_dir / f"stream.{branch}.jsonl").open("rb") as file:
        rows = [json.loads(line) for line in file]
    with (out_dir / f"sessions.{branch}.jsonl").open("rb") as file:
        sessions = [json.loads(line) for line in file]
    plans = schedule.sessions
    if (manifest["life"] != schedule.life or manifest["session_ids"] != [p.session_id for p in plans]
            or [s["index"] for s in sessions] != list(range(1, len(plans) + 1))):
        raise ValueError("schedule identity mismatch")
    if type(step_s) is not int or step_s <= 0:
        raise ValueError("invalid probe cadence")
    slots = {(p.session_id, n): [] for p in plans for n in range(1, len(p.turn_t) + 1)}
    keys = {f"{sid}/t{n}": (sid, n) for sid, n in slots}
    sealed = {r[0] for table in ("event", "fact", "entity") for r in db.execute(f"SELECT id FROM {table}")}
    for row in rows:
        sealed.update(row[k] for k in ("event_id", "call_id", "session_id", "turn_key") if row[k])
        if row["audience"] != ["agent"]:
            raise ValueError("invalid audience")
        slot = keys.get(row["turn_key"])
        if slot is None or row["session_id"] != slot[0]:
            raise ValueError("invalid turn key")
        slots[slot].append(row)
    script_sessions, calls, probes, users = [], [], [], set()

    def turn(n, kind, user, tool_calls):
        key = user.strip()
        if not key or key in users:
            raise ValueError("empty or duplicate user text")
        users.add(key)
        return dict(n=n, kind=kind, user=user, assistant=ASSISTANT if kind == "replay" else None,
                    tool_calls=tool_calls)

    for p in plans:
        if not set(p.heartbeats) <= set(p.turn_t):
            raise ValueError("heartbeat off turn grid")
        turns = []
        for n in range(1, len(p.turn_t) + 1):
            group = sorted(slots[p.session_id, n], key=lambda r: r["seq"])
            tools = []
            for row in group:
                if row["kind"] == "tool" and row["tool"] is not None:
                    if sha256_canon(row["payload"]) != row["expected_result_sha256"]:
                        raise ValueError("tool result hash mismatch")
                    call = row["tool"]
                    calls.append(CheckCall(branch, p.index, n, len(tools), call, row["payload"]))
                    tools.append(hermes_call(call["name"], call["args"]))
            turns.append(turn(n, "replay", "\n\n".join(r["text"] for r in group if "text" in r), tools))
        script_sessions.append(dict(index=p.index, kind="replay", turns=turns))
    groups = {}
    for item in items:
        validate("item", item)
        k = item["probe_point"]
        if type(k) is not int or not 1 <= k <= len(sessions) or not sessions[k - 1]["probe_point"]:
            raise ValueError("invalid probe checkpoint")
        groups.setdefault(k, []).append(item)
        sealed.add(item["item_id"])
        sealed.update(o["option_id"] for o in item["options"])
    index, checkpoint_probes = len(plans) + 1, {}
    for k, group in sorted(groups.items()):
        qa, acts = [i for i in group if i["stage"] != "act"], [i for i in group if i["stage"] == "act"]
        if len(qa) > 6 or len(acts) > 2:
            raise ValueError("too many probe items")
        for batch in ([qa] if qa else []) + [[i] for i in acts]:
            p = plans[k - 1]
            sim_t_s = p.t_end - len(batch) * step_s
            if sim_t_s < p.t_start:
                raise ValueError("probe starts before checkpoint")
            turns = [turn(n, "probe", i["prompt"], []) for n, i in enumerate(batch, 1)]
            probes.append(ProbeSession(index, k, tuple(i["item_id"] for i in batch), sim_t_s))
            checkpoint_probes.setdefault(k, []).append(dict(index=index, kind="probe", turns=turns))
            index += 1
    script_sessions = [s for replay in script_sessions
                       for s in [replay, *checkpoint_probes.get(replay["index"], [])]]
    script = dict(canary=manifest["canary"], life_id=schedule.life,
                  genre=db.execute("SELECT genre FROM meta").fetchone()[0], harness="hermes", sessions=script_sessions)
    validate("script", script)
    paths = scan_script(script, sorted(sealed), ())
    if paths:
        raise ValueError("sealed script paths: " + ", ".join(paths))
    return Compiled(script, tuple(probes), tuple(calls))


def write_script(path, compiled):
    with open(path, "xb") as file:
        file.write(canon(compiled.script))
