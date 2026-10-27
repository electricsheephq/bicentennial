"""S7 Part B: generated-life write turns and passive pacing (advisory only)."""

import argparse
import ast
import json
import os
import re
import runpy
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

from bicentennial.audit import effects
from bicentennial.audit import readback as audit_api
from bicentennial.canon import canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.director.responder import Call
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream import (
    BURST,
    RATE_PER_MIN,
    Holds,
    LiveResponder,
    Pacer,
    Upstream,
    forward,
)
from bicentennial.director.upstream.login import (
    ENV_STORE,
    CredentialResponder,
    NeedleGuard,
    Stop,
    auth_for,
    open_login,
)
from bicentennial.director.wire.responses import typed
from bicentennial.genres.g1_software.world import (
    PROCESS,
    build_golden,
    golden_schedule,
    load_golden,
    world_meta,
)
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
)
from bicentennial.harness.hermes.config import hermes_config, write_config
from bicentennial.items.protocol import CANARY
from bicentennial.ledger import apply_masks
from bicentennial.render.export_s6a import (
    ASSISTANT,
    PLACEHOLDER_STATE,
    export_s6a,
    write_s6a,
)
from bicentennial.render.session_cut import cut
from bicentennial.runner.guard import REFUSED_EXIT, read_marker, reexec_niced
from bicentennial.runner.lock import attempt_id
from bicentennial.runner.spend import Price, Spend
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.spansearch import span_search
from bicentennial.systems import registry
from bicentennial.systems.hermes_plugin import PROVIDERS, PluginCell
from bicentennial.world import create_world
from bicentennial.world.processes import mint

ROOT = Path(__file__).resolve().parents[2]
GOLDEN_PATH = ROOT / "tests/fixtures/g1_golden_tidewater.toml"
SUFFIX = runpy.run_path(str(Path(__file__).with_name("readback.py")))["SUFFIX"]
SYSTEMS = {"W": "hermes-native", "N": "hermes-native", "P1": "mem0-oss",
           "U1": "mem0-oss", "U2": "mem0-oss", "P2": "mem0-oss"}
MODEL, EFFORT, ACCOUNT, MAX_SENDS = "gpt-6.1-sol", "medium", "sol-0", 400
PROBE_GAP_S, STEP_S = 3600, 60
START_WAIT_S, ARM_WALL_S = 7200, 2700
PLANTED = {
    "P1/1": {"cursor": (11, 1), "gold": ("F1b",), "stale": ("F1",)},
    "P1/2": {"cursor": (11, 2), "gold": ("F4",), "stale": ()},
    "P2/1": {"cursor": (12, 1), "gold": ("F3", "F2"), "stale": ()},
}
CHAT_KEYS = frozenset({"model", "messages", "tools", "tool_choice", "stream", "stream_options",
                       "max_tokens", "max_completion_tokens", "reasoning_effort", "parallel_tool_calls"})
UUID_RE = re.compile(r"[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")


def load_entry(name):
    if name not in {"hermes-native", "mem0-oss"}:
        raise ValueError("unsupported S7 system")
    return registry.load(ROOT / "systems/registry" / f"{name}.toml")


def golden_life(workdir):
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    golden = load_golden(GOLDEN_PATH)
    schedule = golden_schedule(golden)
    db = create_world(workdir / "world.db", world_meta(schedule.seed, len(schedule.sessions)))
    try:
        mapping = build_golden(db, golden, schedule)
        gold = {}
        for item, declaration in PLANTED.items():
            gold[item] = {}
            for kind in ("gold", "stale"):
                values = []
                for fact in declaration[kind]:
                    tokens = db.execute("SELECT value FROM locked_token WHERE fact_id = ?",
                                        (mapping[fact],)).fetchall()
                    if len(tokens) != 1:
                        raise ValueError("gold fact must have exactly one locked token")
                    values.append(tokens[0]["value"])
                gold[item][kind] = values
        principal = mint(schedule, PROCESS, "entities", "entity", golden.principal, 0)
        result = cut(db, schedule, branch="B0", principal_id=principal,
                     expected_state={p.index: dict(PLACEHOLDER_STATE) for p in schedule.sessions})
        life = export_s6a(db, result, schedule)
        sealed = [row["id"] for table in ("fact", "event")
                  for row in db.execute(f"SELECT id FROM {table}")]
        for probes in (False, True):
            script, _, _ = build_script(life, schedule, probes=probes)
            if scan_script(script, sealed, []):
                raise ValueError("sealed id in script")
        return life, gold, schedule
    finally:
        db.close()


def build_script(life, schedule, *, probes):
    sessions, faults = [], []
    starts = {p.index: p.t_start for p in schedule.sessions}
    for source in life["sessions"]:
        index = source["index"]
        sessions.append({"index": index, "kind": "replay", "turns": [
            {"n": n, "kind": "replay", "user": turn["user"], "assistant": ASSISTANT, "tool_calls": []}
            for n, turn in enumerate(source["turns"], 1)]})
        if "restart_after_turn" in source:
            faults.append({"kind": "kill", "session": index, "turn": source["restart_after_turn"]})
    if probes:
        micro = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
        for index, source in enumerate(micro["probes"], 11):
            starts[index] = schedule.sessions[9].t_end + (index - 10) * PROBE_GAP_S
            sessions.append({"index": index, "kind": "probe", "turns": [
                {"n": n, "kind": "probe", "user": turn["user"], "assistant": None, "tool_calls": []}
                for n, turn in enumerate(source["turns"], 1)]})
    script = {"canary": CANARY, "life_id": "tidewater", "genre": life["genre"],
              "harness": "hermes", "sessions": sessions}
    validate("script", script)
    return script, faults, starts


def present(token, text):
    return unicodedata.normalize("NFC", token) in unicodedata.normalize("NFC", text)


def grade(final, item):
    return {"answered": all(present(token, final) for token in item["gold"]),
            "stale": any(present(token, final) for token in item["stale"])}


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list) and all(isinstance(p, dict) and p.get("type") == "text"
                                         and isinstance(p.get("text"), str) for p in content):
        return "".join(p["text"] for p in content)
    raise ValueError("bridge_unsupported_content")


def to_responses(body):
    unknown = body.keys() - CHAT_KEYS
    if unknown:
        raise ValueError(f"bridge_unmapped_key:{sorted(unknown)[0]}")
    instructions, items = [], []
    for message in body.get("messages", []):
        role = message["role"]
        content = message.get("content")
        text = "" if role == "assistant" and content is None else _text(content)
        if role in ("system", "developer"):
            instructions.append(text)
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": text})
        elif role in ("user", "assistant"):
            if text or role == "user":
                items.append({"type": "message", "role": role, "content": text})
            for call in message.get("tool_calls", []):
                if role != "assistant" or call.get("type") != "function":
                    raise ValueError("bridge_unsupported_tool_call")
                function = call["function"]
                items.append({"type": "function_call", "call_id": call["id"], "name": function["name"],
                              "arguments": function["arguments"]})
        else:
            raise ValueError("bridge_unsupported_role")
    out = {"instructions": "\n\n".join(instructions), "input": typed(items),
           "store": False, "reasoning": {"effort": EFFORT}}
    tools = []
    for tool in body.get("tools", []):
        if tool.get("type") != "function":
            raise ValueError("bridge_unsupported_tool")
        function = tool["function"]
        tools.append({"type": "function", "name": function["name"],
                      "description": function.get("description", ""), "parameters": function.get("parameters", {})})
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
    def __init__(self, inner):
        self.inner, self.failure = inner, None

    def respond(self, call):
        if call.wire != "chat":
            return self.inner.respond(call)
        try:
            body = to_responses(call.body)
        except ValueError as exc:
            self.failure = str(exc)
            raise
        reply = self.inner.respond(replace(call, wire="responses", body=body))
        return replace(reply, usage=chat_usage(reply.usage))

    def state(self):
        state = self.inner.state()
        return dict(state, stopped=True, stop_reason=self.failure) if self.failure else state

    def served_identities(self):
        return self.inner.served_identities()


class Routed:
    def __init__(self, live, scripted):
        self.live, self.scripted = live, scripted

    def respond(self, call):
        live = call.role in ("write_turn", "probe_main", "memory_write", "summariser")
        target = self.live if live or (call.role, call.subrole) == ("aux", "summariser") else self.scripted
        return target.respond(call)

    def state(self):
        return self.live.state()

    def served_identities(self):
        return self.live.served_identities()


def make_live(spend_path, *, auth, base_url, max_output_tokens, login=None, model=MODEL, max_sends=MAX_SENDS):
    spend = Spend(spend_path, 0, Price(0, 0))
    upstream = Upstream("sol", model, base_url, "responses", spend, Price(0, 0), max_output_tokens,
                        effort=EFFORT, send_cap=False)
    pacer, holds = Pacer(RATE_PER_MIN, BURST, threading.Event()), Holds()
    live = LiveResponder(ACCOUNT, pacer, auth, [upstream], holds, max_sends=max_sends)
    bridge = ResponsesBridge(CredentialResponder(live, login) if login is not None else live)
    bridge.spend_path = Path(spend_path)
    return bridge, holds


def _normal_bytes(data, run_values):
    replacements = {run_values["sandbox_root"].encode(): b"<root>",
                    run_values["director_port"].encode(): b"<port>"}
    if any(not token for token in replacements):
        raise ValueError("nonempty run values required")
    pattern = re.compile(b"|".join(re.escape(token) for token in sorted(replacements, key=len, reverse=True)))
    data = pattern.sub(lambda match: replacements[match[0]], data)
    data = re.sub(UUID_RE.pattern.encode(), b"<uuid>", data)
    return re.sub(TS_RE.pattern.encode(), b"<ts>", data)


def _sql_value(value, run_values):
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, bytes):
        value = value.hex()
    return _normal_bytes(value.encode(), run_values).decode() if isinstance(value, str) else value


def _quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def _file_export(path, run_values):
    with path.open("rb") as stream:
        sqlite = stream.read(16) == b"SQLite format 3\x00"
    if not sqlite:
        return {"sha256": sha256(_normal_bytes(path.read_bytes(), run_values)).hexdigest()}
    tables = {}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            columns = [row[1] for row in db.execute(f"PRAGMA table_info({_quote(table)})")
                       if not re.search(r"(?i)(time|date|_at$)", row[1])]
            count = db.execute(f"SELECT count(*) FROM {_quote(table)}").fetchone()[0]
            if columns:
                query = f"SELECT {', '.join(map(_quote, columns))} FROM {_quote(table)}"
                rows = [[_sql_value(value, run_values) for value in row] for row in db.execute(query)]
            else:
                rows = [[] for _ in range(count)]
            tables[table] = [count, sha256(canon(sorted(rows, key=canon))).hexdigest()]
    return {"tables": tables}


def _surface_files(cell):
    for index, (surface, directory) in enumerate(cell.surfaces):
        listing = tree_listing(directory, surface["volatile_paths"] + [".bicentennial-sandbox"])
        sqlite_paths = set()
        for row in listing:
            if row["kind"] == "symlink":
                raise ValueError("store export refuses symlinks")
            if row["kind"] == "file":
                path = directory / row["path"]
                with path.open("rb") as stream:
                    if stream.read(16) == b"SQLite format 3\x00":
                        sqlite_paths.add(row["path"])
        for row in listing:
            name = row["path"]
            if row["kind"] != "file" or any(name == db + suffix for db in sqlite_paths for suffix in ("-wal", "-shm")):
                continue
            yield index, surface, name, directory / name, name in sqlite_paths


def _export_files(cell, snapshot=None):
    files, live_copy = {}, []
    run_values = cell.adapter.director.run_values
    for index, surface, name, source, sqlite in _surface_files(cell):
        label = f"{surface['root']}/{surface['relative']}/{name}"
        target = source
        if snapshot is not None:
            target = snapshot / str(index) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if sqlite:
                with sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True) as db:
                    with sqlite3.connect(target) as copied:
                        db.backup(copied)
            else:
                shutil.copyfile(source, target)
                live_copy.append(label)
        files[label] = _file_export(target, run_values)
    return {"files": files, "live_copy": live_copy}


def before_store_export(cell, directory):
    """Copy committed SQLite WAL state without checkpointing a running worker.

    Other files are best-effort live copies. Compare the normalized files map;
    the live_copy manifest describes observation provenance, not store content.
    """
    directory = Path(directory).resolve()
    for _, surface in cell.surfaces:
        root = surface.resolve()
        if directory.is_relative_to(root) or root.is_relative_to(directory):
            raise ValueError("export directory overlaps a declared surface")
    directory.mkdir(parents=True, exist_ok=False)
    result = _export_files(cell, directory)
    (directory / "manifest.json").write_bytes(canon(result) + b"\n")
    return result


def store_export(cell):
    """Export after settle; preserve the cell's existing live-worker refusal."""
    cell.checkpoint()
    return _export_files(cell)


def write_json(path, obj, *, exclusive=False):
    path = Path(path)
    data = canon(obj) + b"\n"
    if exclusive:
        with path.open("xb") as stream:
            stream.write(data)
    else:
        pending = path.with_name(path.name + ".pending")
        pending.write_bytes(data)
        pending.replace(path)


def _cursor(row):
    c = row.get("cursor")
    return (c["session"], c["turn"]) if c else None


def _diags(row):
    return [d for u in row.get("upstream", []) for d in u.get("diagnostics", [])]


def _channels(home, gold):
    texts = []
    for name in ("MEMORY.md", "USER.md"):
        path = home / "memories" / name
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError("store_symlink")
        texts.append(path.read_text() if path.is_file() else "")
    needles = [t.encode() for item in gold.values() for t in item["gold"]]
    found = span_search(home, needles)
    return ({k: [any(present(t, text) for text in texts) for t in v["gold"]] for k, v in gold.items()},
            {k: [any(Path(p).name.startswith("state.db") for p in found[t.encode()])
                 for t in v["gold"]] for k, v in gold.items()})


def run_arm(arm, adapter, script, starts, *, live=None, holds=None, cell=None, gold=None,
            lock, wall_s=ARM_WALL_S, monotonic=time.monotonic):
    root, start = adapter.paths["root"], monotonic()
    result = {"arm": arm, "sessions": [], "sessions_run": 0, "stop_reason": None,
              "flagged_sessions": [], "pauses": []}
    previous, before, attempts = None, {}, {}
    result["start_gate"] = getattr(adapter, "start_readings", [])
    if cell is not None:
        adapter.before_shutdown = lambda: before.update(before_store_export(
            cell, root / "before" / str(current)))
    try:
        for session in script["sessions"]:
            if getattr(adapter, "egress", None) is not None and adapter.egress.summary().get("non_loopback"):
                result["stop_reason"] = "non_loopback"
                break
            state = live.state() if live else {}
            pause = holds.at_boundary(previous) if holds and previous else {"reasons": []}
            result["pauses"].append(dict(pause, after_attempt=previous))
            reason = ("identity_drift" if state.get("identity_drift") else
                      state.get("stop_reason") or "responder_stopped" if state.get("stopped") else
                      "live_spend_stop" if state.get("spend_stopped") else
                      "quota_hold" if "quota" in pause["reasons"] else
                      "arm_wall" if monotonic() - start >= wall_s else None)
            if reason:
                result["stop_reason"] = reason
                break
            current = session["index"]
            previous = attempt_id(lock, arm, "tidewater", "B0", current, 0)
            attempts[previous] = current
            before.clear()
            try:
                r = adapter.run_session(current, sim_t_s=starts[current], lock_hash=lock, attempt_id=previous)
            except HarnessFailed as exc:
                state = live.state() if live else {}
                result["stop_reason"] = state.get("stop_reason") or str(exc)
                break
            record = {k: getattr(r, k) for k in ("session", "kind", "turns_ok", "finals_matched", "restarts",
                      "summariser_records", "surface_hash", "gate", "timings_ms", "end_threads")}
            record["attempt_id"] = previous
            if cell is not None:
                record.update(before=dict(before), settle=asdict(cell.settle()), after=store_export(cell))
                if (root / "ledger/ledger.jsonl").exists():
                    rows, blobs, _ = audit_api.load(root / "ledger", "kit")
                    try:
                        record["withholding"] = verify_withholding(rows, blobs, cell.entry)
                    except ValueError:
                        result["stop_reason"] = "mem0_write_tool_offered"
                if not record["settle"]["settled"]:
                    result["stop_reason"] = "settle_failed"
            elif gold is not None:
                record["stored"], record["transcript"] = _channels(adapter.paths["hermes_home"], gold)
                finals = dict(r.finals)
                record["probe"] = [dict(item=item, **grade(finals.get(turn, ""), gold[item]))
                                   for item, declaration in PLANTED.items()
                                   for s, turn in [declaration["cursor"]] if s == current]
            result["sessions"].append(record)
            result["sessions_run"] += 1
            flagged = {row.get("attempt_id") for row in adapter.records()
                       if any(d.get("identity_changed") for d in _diags(row))}
            result["flagged_sessions"] = [s["session"] for s in result["sessions"]
                                          if s["attempt_id"] in flagged]
            write_json(root / "arm.json", result)
            if result["stop_reason"]:
                break
    finally:
        result["egress"] = adapter.close()
        flagged = {row.get("attempt_id") for row in adapter.records()
                   if any(d.get("identity_changed") for d in _diags(row))}
        result["flagged_sessions"] = sorted(attempts[a] for a in flagged if a in attempts)
        result["wall_ms"] = round((monotonic() - start) * 1000)
        if live is not None:
            result.update(live=live.state(), served_identities=live.served_identities())
            state = result["live"]
            if not result["stop_reason"]:
                result["stop_reason"] = ("identity_drift" if state.get("identity_drift") else
                    state.get("stop_reason") or ("live_spend_stop" if state.get("spend_stopped") else None))
            path = getattr(live, "spend_path", None)
            if path is not None:
                spend = json.loads(Path(path).read_bytes())
                result["spend"] = {k: spend[k] for k in ("settled", "refused_calls")}
                if spend["settled"]:
                    result["stop_reason"] = "nonzero_spend"
        if result["egress"].get("non_loopback"):
            result["stop_reason"] = "non_loopback"
        write_json(root / "arm.json", result)
    return result


def wait_for_start(*, monotonic=time.monotonic, sleep=time.sleep):
    start, readings = monotonic(), []
    while True:
        marker = read_marker()
        readings.append({"exit": marker.exit, "state": marker.state})
        if marker.exit == 0 and marker.state != "unset":
            return True, readings
        if monotonic() - start >= START_WAIT_S:
            return False, readings
        sleep(min(60, max(0, START_WAIT_S - (monotonic() - start))))


def waits_from_rows(rows):
    waits = {}
    for row in rows:
        c = _cursor(row)
        if row.get("role") == "replay_main" and row.get("subrole") == "cursor" and c not in waits:
            held = sum(d.get("held_ms", 0) for u in row.get("upstream", []) if u.get("role") == "write_turn"
                       for d in u.get("diagnostics", []) if d.get("kind") == "hold")
            waits[c] = max(0, row["t_ms"] - held)
    return waits


def check_waits(waits, script):
    required = {(s["index"], t["n"]) for s in script["sessions"] if s["kind"] == "replay" for t in s["turns"]}
    if required - waits.keys() or any(type(waits[c]) is not int or waits[c] < 0 for c in required):
        raise ValueError("missing_or_invalid_wait")


class Pacing:
    def __init__(self, inner, waits, *, sleep=time.sleep):
        self.inner, self.waits, self.sleep, self.seen = inner, waits, sleep, set()

    def __call__(self, cursor):
        c = _cursor({"cursor": cursor})
        if c in self.waits and c not in self.seen:
            self.seen.add(c)
            self.sleep(self.waits[c] / 1000)
        return self.inner(cursor) if self.inner is not None else None


def normalized_request(body, run_values):
    return json.loads(TS_RE.sub("<ts>", UUID_RE.sub("<uuid>", canon(apply_masks(body, run_values)).decode())))


def request_digest(body, run_values):
    return sha256(canon(normalized_request(body, run_values))).hexdigest()


def differing_paths(a, b, path=""):
    if type(a) is not type(b):
        return [path or "/"]
    if isinstance(a, dict):
        return [p for k in sorted(a.keys() | b.keys()) for p in (
            [path + "/" + k.replace("~", "~0").replace("/", "~1")] if k not in a or k not in b else
            differing_paths(a[k], b[k], path + "/" + k.replace("~", "~0").replace("/", "~1")))][:20]
    if isinstance(a, list):
        return [p for i in range(max(len(a), len(b))) for p in (
            [f"{path}/{i}"] if i >= min(len(a), len(b)) else differing_paths(a[i], b[i], f"{path}/{i}"))][:20]
    return [] if a == b else [path or "/"]


def bridge_readback(rows, blobs):
    result = {"sent": 0, "matched": 0, "mismatches": []}
    for row in rows:
        for upstream in row.get("upstream", []):
            if upstream.get("served_by") != "live":
                continue
            for d in upstream.get("diagnostics", []):
                if d.get("kind") != "try" or not d.get("sent"):
                    continue
                result["sent"] += 1
                call = Call(upstream["role"], row.get("subrole", ""), "responses",
                            to_responses(blobs[upstream["req"]]), upstream["model"], row.get("cursor"), "")
                matches = sha256(canon(forward.wire_body(call))).hexdigest() == d.get("sent_sha256")
                result["matched"] += matches
                if not matches:
                    result["mismatches"].append({"record": row["seq"], "try": d.get("try")})
    return result


def route_table(arm):
    live = arm in ("W", "N")
    return RouteTable.load({"routes": [{"system": SYSTEMS[arm], "segment": "seg0",
        "probe_model": MODEL if live else "probe-model", "summariser": MODEL if live else "summary-model",
        "alias": "bicentennial-main", "vision": None, "served_by": "live" if live else "scripted"}]})


def arm_readback(root, manifest):
    rows, blobs, digest = audit_api.load(root / "ledger", "kit")
    script, entry = json.loads((root / "script.json").read_bytes()), manifest["entry"]
    schedule = FaultLite.load(manifest["faults"], script)
    model_for, mode = audit_api.route_models(RouteTable.load(manifest["routes"]), entry["name"], schedule)
    report = audit_api.audit(rows, blobs, audit_api.turns_from_script(script), "chat", fmt="kit",
        model_for=model_for, suffix=SUFFIX, write_tools=[t["tool"] for t in entry["write_tools"]],
        id_needles=audit_api.life_ids(script) + [("script.canary", script["canary"])],
        effects=effects.hermes(root / "hermes-home") if entry["name"] == "hermes-native" else None)
    report.update(failures=audit_api.failures(report), run_status=audit_api.run_status(report, mode),
                  ledger_sha256=digest, calls_by_role=dict(Counter(r.get("role") for r in rows)))
    report["bridge"] = bridge_readback(rows, blobs) if manifest["arm"] in ("W", "N") else None
    actions = Counter()
    for row in rows:
        for up in row.get("upstream", []):
            if up["role"] == "write_turn" and up.get("resp"):
                for call in blobs[up["resp"]].get("tool_calls", []):
                    try:
                        args = json.loads(call["arguments"])
                        for op in args.get("operations", [args]):
                            action = op.get("action")
                            actions[action if action in effects.ACTIONS else "other"] += 1
                    except (ValueError, TypeError, AttributeError):
                        actions["unparsed"] += 1
    report["write_actions"] = dict(actions)
    return report, rows, blobs


def injection_blocks(body):
    """Extract memory sections only; surrounding system instructions are diagnostics.

    Named XML memory blocks and headed memory sections are supported. Refuse an
    unclosed recognized marker instead of silently comparing an empty injection.
    """
    text = effects.snapshot(body, "chat")
    tags = r"mem0|memory|recalled_memories|relevant_memories|memory_context|prefetched_memories"
    xml = re.compile(rf"<({tags})(?:\s[^>]*)?>.*?</\1>", re.I | re.S)
    blocks = [m.group() for m in xml.finditer(text)]
    remainder = xml.sub("", text)
    if re.search(rf"<(?:{tags})(?:\s|>)", remainder, re.I):
        raise ValueError("injection_block_unclosed")
    heading = re.compile(r"(?im)^#{1,6} (?:recalled|relevant|prefetched|persistent|mem0)?\s*memories?\s*[^\n]*\n")
    for match in heading.finditer(remainder):
        end = re.search(r"(?m)^#{1,6} ", remainder[match.end():])
        blocks.append(remainder[match.start():match.end() + end.start() if end else len(remainder)])
    if not blocks and re.search(r"(?i)(recalled|relevant|prefetched|mem0|persistent) memor(?:y|ies)", text):
        raise ValueError("injection_shape_unverified")
    return blocks


def _first_requests(rows, blobs):
    requests = {}
    for row in rows:
        c = _cursor(row)
        if c and row.get("role") in ("replay_main", "probe_main") and row.get("subrole") == "cursor":
            requests.setdefault(c, (row, blobs[row["req"]]))
    return requests


def planted_result(arms, evidence, gold):
    result = {}
    for item, declaration in PLANTED.items():
        cursor = declaration["cursor"]
        result[item] = {}
        for arm in ("W", "N"):
            data, (rows, blobs) = arms[arm], evidence[arm]
            tenth = next((s for s in data["sessions"] if s["session"] == 10), {})
            probe = next((p for s in data["sessions"] for p in s.get("probe", []) if p["item"] == item), {})
            first = next((b for (s, _), (_, b) in _first_requests(rows, blobs).items() if s == cursor[0]), None)
            later = [blobs[r["req"]] for r in rows if _cursor(r) == cursor and r.get("req")]
            calls = [call for r in rows if _cursor(r) == cursor and r.get("resp") and r.get("status", 200) == 200
                     for call in audit_api.output(blobs[r["resp"]], "chat")[0]]
            tool_text = " ".join(effects.strings([m.get("content", "") for b in later[1:]
                                                for m in b.get("messages", []) if m.get("role") == "tool"]))
            result[item][arm] = dict(probe, stored=tenth.get("stored", {}).get(item),
                transcript=tenth.get("transcript", {}).get(item),
                injected=all(present(t, effects.snapshot(first, "chat")) for t in gold[item]["gold"])
                         if first is not None else None,
                session_search_calls=sum(c["name"] == "session_search" for c in calls),
                tool_hit=all(present(t, tool_text) for t in gold[item]["gold"]))
        w, n = result[item]["W"].get("answered"), result[item]["N"].get("answered")
        result[item]["contrast"] = w and not n if w is not None and n is not None else None
    return {"n": 3, "items": result, "memory_write": {
        arm: sum(r.get("role") == "memory_write" for r in evidence[arm][0]) for arm in ("W", "N")}}


def pacing_result(arms, evidence, manifests, script):
    names = ("P1", "U1", "U2", "P2")
    if not all(name in arms for name in names):
        return {"status": "not_run", "reason": "mem0_blocked"}
    if any(arms[a]["stop_reason"] or len(arms[a]["sessions"]) != 10 for a in names):
        return {"status": "incomplete", "reason": "arm_incomplete"}
    requests, injections = {}, {}
    required = {(s["index"], t["n"]) for s in script["sessions"] for t in s["turns"]}
    for arm in names:
        first = _first_requests(*evidence[arm])
        if set(first) != required:
            return {"status": "incomplete", "reason": "missing_cursor"}
        values = manifests[arm]["run_values"]
        requests[arm] = {c: normalized_request(b, values) for c, (_, b) in first.items()}
        injections[arm] = {c: sha256(_normal_bytes(canon(injection_blocks(b)), values)).hexdigest()
                           for c, (_, b) in first.items()}
    if not any(injection_blocks(b) for arm in names for _, b in _first_requests(*evidence[arm]).values()):
        return {"status": "incomplete", "reason": "injection_shape_unverified"}
    pairs = {}
    for left, right in (("P1", "U1"), ("P1", "U2"), ("P2", "U1"), ("P2", "U2"),
                        ("P1", "P2"), ("U1", "U2")):
        a = {s["session"]: s for s in arms[left]["sessions"]}
        b = {s["session"]: s for s in arms[right]["sessions"]}
        pairs[f"{left}-{right}"] = {
            "n_cursors": len(required), "n_sessions": 10,
            "cursor_diffs": [f"{s}/{t}" for s, t in sorted(required)
                             if injections[left][s, t] != injections[right][s, t]],
            "session_diffs": [s for s in a if a[s]["after"]["files"] != b[s]["after"]["files"]],
            "before_diffs": [s for s in a if a[s]["before"]["files"] != b[s]["before"]["files"]],
            "count_diffs": [s for s in a if _counts(a[s]["after"]) != _counts(b[s]["after"])],
            "request_diffs": {f"{s}/{t}": differing_paths(requests[left][s, t], requests[right][s, t])
                              for s, t in sorted(required) if requests[left][s, t] != requests[right][s, t]}}
    def changed(pair):
        return bool(pair["cursor_diffs"] or pair["session_diffs"])
    return {"status": "complete", "pairs": pairs,
            "consequence": any(changed(pairs[p]) for p in ("P1-U1", "P1-U2", "P2-U1", "P2-U2")),
            "noise": any(changed(pairs[p]) for p in ("P1-P2", "U1-U2")),
            "settle": {a: [dict(session=s["session"], **s["settle"]) for s in arms[a]["sessions"]] for a in names}}


def _counts(export):
    return {f"{file}/{table}": value[0] for file, data in export["files"].items()
            for table, value in data.get("tables", {}).items()}


def summarise(scratch):
    scratch = Path(scratch)
    run = json.loads((scratch / "run.json").read_bytes())
    arms, readback, evidence, manifests = {}, {}, {}, {}
    for arm in SYSTEMS:
        root = scratch / f"p07-{arm}"
        if not (root / "arm.json").exists():
            continue
        manifests[arm] = json.loads((root / "manifest.json").read_bytes())
        arms[arm] = json.loads((root / "arm.json").read_bytes())
        readback[arm], rows, blobs = arm_readback(root, manifests[arm])
        evidence[arm] = rows, blobs
    if not {"W", "N"} <= arms.keys():
        raise ValueError("missing_W_or_N")
    pace = json.loads((scratch / "pace-script.json").read_bytes())
    pacing = pacing_result(arms, evidence, manifests, pace)
    if (scratch / "pacing-status.json").exists() and pacing["status"] == "not_run":
        pacing = json.loads((scratch / "pacing-status.json").read_bytes())
    if "W" in evidence:
        waits = list(waits_from_rows(evidence["W"][0]).values())
        ordered = sorted(waits)
        median = (ordered[(len(ordered) - 1) // 2] + ordered[len(ordered) // 2]) // 2 if ordered else None
        pacing["wait_source"] = {"arm": "W", "ledger_sha256": readback["W"]["ledger_sha256"],
                                 "n": len(waits), "median_ms": median, "r7c_median_ms": 3100}
    if "P1" in manifests:
        run["inputs"]["mem0_pin"] = manifests["P1"]["entry"]["artifact"]
    return {"canary": CANARY, "claim_class": "advisory", "mode": "live", "inputs": run["inputs"],
            "arms": arms, "readback": readback,
            "planted": planted_result(arms, evidence, run["gold"]), "pacing": pacing}


def safe_checkout(path):
    path, user = Path(path).resolve(), Path.home() / ".hermes"
    if path.is_relative_to(user) or path.is_relative_to(user.resolve()):
        raise ValueError("hermes_checkout_in_user_home")
    return path


def passive_config(entry):
    """Candidate Hermes deny-list configuration; ledger verification is mandatory.

    The measured checkout must support disabled_tools before pacing is admitted.
    A registry write_tools override alone is insufficient.
    """
    return {"disabled_tools": [t["tool"] for t in entry["write_tools"]]}


def withholding_supported(checkout):
    """Admit only an explicit ACP config-to-agent disabled_tools binding.

    Unrecognized implementations need dispatcher inspection; never infer support
    from a config key's mere occurrence in comments or documentation.
    """
    path = Path(checkout) / "acp_adapter/session.py"
    if not path.is_file():
        return False
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.keyword) or node.arg != "disabled_tools":
            continue
        value = node.value
        if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and value.func.attr == "get" and value.args
                and isinstance(value.args[0], ast.Constant) and value.args[0].value == "disabled_tools"):
            return True
    return False


def verify_withholding(rows, blobs, entry):
    blocked = {t["tool"] for t in entry["write_tools"]}
    offered = {t.get("function", {}).get("name") for r in rows if r.get("req")
               for t in blobs[r["req"]].get("tools", [])}
    if offered & blocked:
        raise ValueError("mem0_write_tool_offered")
    return {"checked_requests": sum(bool(r.get("req")) for r in rows), "offered_write_tools": []}


def _inputs(args, life, script, pace):
    return {"life_sha256": sha256(args.life.read_bytes()).hexdigest(),
            "script_sha256": sha256(canon(script)).hexdigest(), "pace_script_sha256": sha256(canon(pace)).hexdigest(),
            "route_table_hashes": {a: route_table_hash(route_table(a)) for a in SYSTEMS},
            "suffix_sha256": sha256(SUFFIX.encode()).hexdigest(),
            "hermes_pin": load_entry("hermes-native")["artifact"], "mem0_pin": load_entry("mem0-oss")["artifact"],
            "model": MODEL, "effort": EFFORT, "max_output_tokens": args.sol_max_output,
            "max_output_source": args.sol_max_output_source,
            "base_commit": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                          capture_output=True, text=True, check=True).stdout.strip()}


def _execute(args):
    reexec_niced(sys.argv)
    safe_checkout(args.hermes)
    admitted, readings = wait_for_start()
    if not admitted:
        return REFUSED_EXIT
    scratch = args.scratch.resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch) as temporary:
        expected_life, gold, schedule = golden_life(temporary)
    life = json.loads(args.life.read_bytes())
    if canon(life) != canon(expected_life):
        raise ValueError("life_not_generated_golden")
    script, faults, starts = build_script(life, schedule, probes=True)
    pace, _, _ = build_script(life, schedule, probes=False)
    live, holds, waits = None, None, {}
    if args.command == "live":
        inputs = _inputs(args, life, script, pace)
        lock = sha256(canon(inputs)).hexdigest()
        run = "p07-" + lock[:16]
        write_json(scratch / "run.json", {"inputs": inputs, "gold": gold, "lock": lock, "run": run}, exclusive=True)
        write_json(scratch / "pace-script.json", pace, exclusive=True)
        login = open_login(os.environ[ENV_STORE], os.environ["BICENTENNIAL_SOL_TOKEN_URL"],
                           os.environ["BICENTENNIAL_SOL_CLIENT_ID"], run)
        live, holds = make_live(scratch / "spend.json", auth=lambda: {}, login=login,
                               base_url=os.environ["BICENTENNIAL_SOL_BASE_URL"], max_output_tokens=args.sol_max_output)
        live.inner.inner.auth = auth_for(login, live.inner.inner.pacer)
        live.spend_path = scratch / "spend.json"
        names = ("W", "N")
    else:
        saved = json.loads((scratch / "run.json").read_bytes())
        lock, run = saved["lock"], saved["run"]
        if saved["inputs"]["life_sha256"] != sha256(args.life.read_bytes()).hexdigest():
            raise ValueError("pace_life_mismatch")
        entry = load_entry("mem0-oss")
        if "0" * 64 in (entry["artifact"]["sha256"], entry["fresh_install_hash"]):
            write_json(scratch / "pacing-status.json", {"status": "not_run", "reason": "mem0_blocked"})
            return 4
        if not withholding_supported(args.hermes):
            write_json(scratch / "pacing-status.json", {"status": "not_run", "reason": "mem0_withholding_unverified"})
            return 4
        if saved["inputs"]["hermes_pin"] != load_entry("hermes-native")["artifact"]:
            raise ValueError("pace_pin_mismatch")
        wmanifest = json.loads((args.waits / "manifest.json").read_bytes())
        if wmanifest["lock"] != lock or wmanifest["arm"] != "W":
            raise ValueError("wait_source_mismatch")
        waits = waits_from_rows(audit_api.load(args.waits / "ledger", "kit")[0])
        check_waits(waits, pace)
        names = ("P1", "U1", "U2", "P2")
    for n, arm in enumerate(names):
        if n:
            admitted, readings = wait_for_start()
            if not admitted:
                return REFUSED_EXIT
        entry = load_entry(SYSTEMS[arm])
        if arm != "W":
            entry = dict(entry, write_tools=[])
        arm_script, arm_faults, arm_starts = build_script(life, schedule, probes=arm in ("W", "N"))
        root = scratch / f"p07-{arm}"
        if root.exists():
            raise ValueError("arm_root_exists")
        root.mkdir()
        responder = Routed(live, ScriptedResponder(entry)) if live else ScriptedResponder(entry)
        adapter = HermesAdapter(entry, script=arm_script, route_table=route_table(arm),
            schedule=FaultLite.load(arm_faults, arm_script), responder=responder,
            clock=SimClock(root / "clock.json", arm_starts[1], STEP_S), root=root, scratch=scratch,
            life="tidewater", branch="B0", run=run, checkout=args.hermes, kill_mode="boundary",
            plugin=PROVIDERS["mem0-oss"] if arm not in ("W", "N") else None,
            plugin_config=passive_config(load_entry("mem0-oss")) if arm not in ("W", "N") else None,
            write_prompt=SUFFIX, harness_pin=dict(load_entry("hermes-native")["artifact"]))
        adapter.start_readings = readings
        if live is not None:
            adapter.director.guard = NeedleGuard(login, adapter.director.guard)
        cell = None
        if arm not in ("W", "N"):
            cell = PluginCell(load_entry("mem0-oss"), adapter)
            try:
                cell.install(args.mem0_source, alias="bicentennial-main")
                adapter.plugin_config = passive_config(cell.entry)
                write_config(adapter.paths["hermes_home"], hermes_config(adapter.server.port,
                    "bicentennial-main", plugin=PROVIDERS["mem0-oss"], plugin_config=adapter.plugin_config))
            except PinMismatch:
                adapter.close()
                write_json(scratch / "pacing-status.json", {"status": "not_run", "reason": "pin_mismatch"})
                return 4
            if arm.startswith("P"):
                adapter.director.on_hold = Pacing(adapter.director.on_hold, waits)
        write_json(root / "script.json", arm_script, exclusive=True)
        write_json(root / "manifest.json", {"arm": arm, "entry": entry, "faults": arm_faults,
            "routes": route_table(arm).to_obj(), "run_values": adapter.director.run_values, "lock": lock,
            "start_gate": readings, "harness": adapter.harness_record()}, exclusive=True)
        result = run_arm(arm, adapter, arm_script, arm_starts, live=live, holds=holds, cell=cell,
                         gold=gold if arm in ("W", "N") else None, lock=lock)
        if cell is not None and (root / "ledger/ledger.jsonl").exists():
            rows, blobs, _ = audit_api.load(root / "ledger", "kit")
            try:
                result["withholding"] = verify_withholding(rows, blobs, cell.entry)
            except ValueError:
                result["stop_reason"] = "mem0_write_tool_offered"
            write_json(root / "arm.json", result)
        if result["stop_reason"]:
            return 4
    print(run)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    export = subcommands.add_parser("export")
    export.add_argument("--out", type=Path, required=True)
    summary = subcommands.add_parser("summarise")
    summary.add_argument("--scratch", type=Path, required=True)
    summary.add_argument("--out", type=Path, required=True)
    for command in ("live", "pace"):
        sub = subcommands.add_parser(command)
        for name in ("scratch", "life", "hermes"):
            sub.add_argument("--" + name, type=Path, required=True)
        if command == "live":
            sub.add_argument("--sol-max-output", type=int, required=True)
            sub.add_argument("--sol-max-output-source", required=True)
        else:
            sub.add_argument("--mem0-source", type=Path, required=True)
            sub.add_argument("--waits", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "export":
        with tempfile.TemporaryDirectory() as workdir:
            life, _, _ = golden_life(workdir)
            write_s6a(args.out, life)
        print("sha256", sha256(args.out.read_bytes()).hexdigest())
        return 0
    if args.command == "summarise":
        if args.out.exists():
            raise FileExistsError("result_exists")
        write_json(args.out, summarise(args.scratch), exclusive=True)
        return 0
    if args.command == "live" and (args.sol_max_output < 1 or not args.sol_max_output_source.strip()):
        parser.error("positive sol max output and its source are required")
    try:
        return _execute(args)
    except Stop as exc:
        print(str(exc), file=sys.stderr)  # R17b's fixed-vocabulary startup refusal; never retry
        return 4
    except PinMismatch:
        print("pin_mismatch", file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
