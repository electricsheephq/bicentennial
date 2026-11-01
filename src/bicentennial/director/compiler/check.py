"""Runner-side preconditions; no harness is imported by these checks."""

import json
from fractions import Fraction

from bicentennial.canon import milli, sha256_canon
from bicentennial.genres.g2_assistant.envseed import probe_envseed
from bicentennial.items.tags import check_precondition
from bicentennial.sandbox.fixedroot import holding, remove_tree, within


def precondition_holds(item, *, repo_tree_hash, env_state_hash, probe_env_state_hash):
    try:
        obj = json.loads(item["precondition"])
        own_hash = obj.get("env_state_hash") if type(obj) is dict else None
        repo_ok = check_precondition(item["precondition"], repo_tree_hash=repo_tree_hash, env_state_hash=own_hash)
    except (TypeError, KeyError) as error:
        raise ValueError("invalid precondition") from error
    if obj["after_session"] != item["probe_point"]:
        raise ValueError("precondition checkpoint mismatch")
    return repo_ok and env_state_hash == probe_env_state_hash


def expected_probe_env(db, genre, p, k):
    if genre == "G1":
        return sha256_canon({})
    if genre == "G2":
        return probe_envseed(db, p, k).env_state_hash
    raise ValueError("unknown genre")


def void_outcome(item):
    """Cause packet for the runner's S06 outcome(..., cause=...) / two-rerun loop."""
    return {"item_id": item["item_id"], "cause": "INFRA_FAILURE"}


class Voids:
    def __init__(self):
        self.records = {}
        self.diagnostics = []

    def record(self, item_id, arm, holds, *, call=None, expected_sha256=None, got_sha256=None):
        if (item_id, arm) in self.records:
            raise ValueError("duplicate precondition record")
        if type(holds) is not bool:
            raise ValueError("holds must be boolean")
        self.records[item_id, arm] = holds
        self.diagnostics.append(dict(item_id=item_id, arm=arm, holds=holds, call=call,
                                     expected_sha256=expected_sha256, got_sha256=got_sha256))

    def voided(self):
        return {item for (item, _), holds in self.records.items() if not holds}

    def summary(self):
        checked, voided = len({i for i, _ in self.records}), len(self.voided())
        return dict(checked=checked, voided=voided, void_milli=milli(Fraction(voided, checked)) if checked else None)


def _mismatch(call, kind, got):
    from dataclasses import asdict

    row = asdict(call)
    expected = row.pop("expected")
    return dict(row, kind=kind, expected_sha256=sha256_canon(expected), got_sha256=sha256_canon(got))


def _compare(adapter, calls):
    from bicentennial.audit.readback import output
    from bicentennial.harness.normalize import normalise
    from bicentennial.ledger import BlobStore, Guard

    rows, mismatches = adapter.records(), []
    store = BlobStore(adapter.paths["root"] / "ledger" / "blobs", Guard([]))
    for call in calls:
        cursor = dict(session=call.session, turn=call.turn)
        relevant = [r for r in rows if r.get("cursor") == cursor]
        if any(r.get("served") == "script_tool_calls_retry" for r in relevant):
            mismatches.append(_mismatch(call, "retried", None))
            continue
        issued = next((r for r in relevant if r.get("served") == "script_tool_calls"), None)
        got = None
        if issued:
            issued_calls, _ = output(json.loads(store.get(issued["resp"])), "chat")
            if call.index < len(issued_calls):
                ident = issued_calls[call.index]["id"]
                # Take the first later request carrying this id, including across cursor changes.
                for row in rows:
                    if row.get("type") != "request" or row["seq"] <= issued["seq"]:
                        continue
                    messages = json.loads(store.get(row["req"])).get("messages", [])
                    result = next((m for m in messages if m.get("role") == "tool"
                                   and m.get("tool_call_id") == ident), None)
                    if result is not None:
                        got = normalise(call.call, result["content"])
                        break
        if got is None or sha256_canon(got) != sha256_canon(call.expected):
            mismatches.append(_mismatch(call, "no_result" if got is None else "result", got))
    return mismatches


def check_compile(life_dir, *, entry, route_table, harness_pin, checkout, scratch, step_s=60, worker_argv=None,
                  answer_contract=None):
    """Hold scratch exclusively for the call: its job roots have fixed names (#282)."""
    import fcntl
    import os
    from pathlib import Path

    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    # Each job root is cleared before use, so an input at or below scratch could be deleted.
    if any(path is not None and within(path, scratch) for path in (life_dir, checkout)):
        raise ValueError("scratch_overlap")
    fd = os.open(scratch / ".check.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("scratch_busy") from None
        with holding(fd):  # workers inherit the lock, so a killed caller's live workers keep scratch busy
            return _check_compile(life_dir, entry=entry, route_table=route_table, harness_pin=harness_pin,
                                  checkout=checkout, scratch=scratch, step_s=step_s, worker_argv=worker_argv,
                                  answer_contract=answer_contract)
    finally:
        os.close(fd)


def _check_contract(compiled, items, answer_contract):
    from . import answer_contract as fixed

    by_id = {i["item_id"]: i for i in items}
    cursors = {(p.index, n): by_id[iid] for p in compiled.probes for n, iid in enumerate(p.item_ids, 1)}
    for session in compiled.script["sessions"]:
        for turn in session["turns"]:
            item = cursors.get((session["index"], turn["n"]))
            suffix = (answer_contract.render([o["envelope"] for o in item["options"]])
                      if item and item["stage"] != "act" and answer_contract is not None else "")
            if suffix:
                valid = turn["user"].endswith(suffix)
            else:
                valid = not any(fixed.CONTRACT["template"].replace("<<TYPE>>", kind).replace(
                    "<<VALUE>>", form) in turn["user"] for kind, form in fixed.CONTRACT["value_forms"].items())
            if not valid:
                raise ValueError("answer_contract_suffix")


def _check_compile(life_dir, *, entry, route_table, harness_pin, checkout, scratch, step_s, worker_argv,
                   answer_contract=None):
    """Execute each check session in a fresh home and compare its durable tool-result receipts."""
    import sqlite3
    from pathlib import Path

    from bicentennial.director.routes import RouteTable
    from bicentennial.director.scripted import ScriptedResponder
    from bicentennial.genres.g1_software.diffs import expected_result, start_boundary
    from bicentennial.genres.g1_software.repo import materialize
    from bicentennial.harness.hermes.adapter import HarnessFailed, HermesAdapter
    from bicentennial.harness.hermes.config import HERMES_TOOLSETS
    from bicentennial.harness.hermes.envwire import EnvWiring
    from bicentennial.runtime.clock import SimClock
    from bicentennial.runtime.faultlite import FaultLite
    from bicentennial.sandbox.envserver.state import state_hash
    from bicentennial.sandbox.envserver.tools_g2 import G2State
    from bicentennial.world.scale import TURN_S, named
    from bicentennial.world.schedule import build_schedule

    from .hermes import ASSISTANT, CheckCall, compile_script, hermes_call

    life_dir, scratch = Path(life_dir).resolve(), Path(scratch).resolve()
    meta = json.loads((life_dir / "life.json").read_bytes())
    if set(meta) != {"canary", "life", "seed", "scale"}:
        raise ValueError("invalid life metadata")
    schedule = build_schedule(meta["seed"], meta["life"], named(meta["scale"]))
    table = RouteTable.load(route_table) if isinstance(route_table, dict) else route_table
    scratch.mkdir(parents=True, exist_ok=True)
    branches, genre = {}, None
    for branch in ("B0", "B1"):
        db = sqlite3.connect((life_dir / f"world.{branch}.db").as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        try:
            if tuple(db.execute("SELECT seed FROM meta").fetchone()) != (meta["seed"],):
                raise ValueError("world seed differs")
            items = json.loads((life_dir / f"items.{branch}.json").read_bytes())
            compiled = compile_script(life_dir, branch, schedule, db, items=items, step_s=step_s,
                                      answer_contract=answer_contract)
            _check_contract(compiled, items, answer_contract)
            if meta["canary"] != compiled.script["canary"]:
                raise ValueError("life canary differs")
            if genre is not None and genre != compiled.script["genre"]:
                raise ValueError("branch genres differ")
            genre = compiled.script["genre"]
            jobs = []
            if genre == "G1":
                for session in compiled.script["sessions"]:
                    calls = tuple(c for c in compiled.calls if c.session == session["index"])
                    if calls:
                        plan = schedule.sessions[session["index"] - 1]
                        jobs.append((session, calls, plan.turn_t[0] - TURN_S, TURN_S, None, None))
            elif genre == "G2":
                for probe in compiled.probes:
                    for item in (i for i in items if i["item_id"] in probe.item_ids and i["stage"] == "act"):
                        for option in item["options"]:
                            steps = option.get("plan", {}).get("steps", [])
                            if not steps:
                                continue
                            seed = probe_envseed(db, probe.index, probe.checkpoint).seed
                            state, calls = G2State(seed), []
                            for index, step in enumerate(steps):
                                call = step["tool"]
                                try:
                                    text, _ = state.call(call["name"], call["args"])
                                    expected = dict(text=text, isError=False)
                                except (ValueError, TypeError) as error:
                                    expected = dict(text=str(error), isError=True)
                                calls.append(CheckCall(branch, probe.index, 1, index, call, expected))
                            turn = dict(n=1, kind="replay", user=item["prompt"], assistant=ASSISTANT,
                                        tool_calls=[hermes_call(c.call["name"], c.call["args"]) for c in calls])
                            session = dict(index=probe.index, kind="replay", turns=[turn])
                            jobs.append((session, calls, probe.sim_t_s, step_s, seed, state_hash(state.state)))
            else:
                raise ValueError("unknown genre")
            result = branches[branch] = dict(sessions=0, calls=0, mismatches=[])
            for k, (session, calls, instant, cadence, seed, end_hash) in enumerate(jobs):
                root = scratch / f"check-{branch}-{k}"
                remove_tree(root)  # a stale root from an earlier call; this call's evidence stays for its caller
                root.mkdir(parents=True)
                if genre == "G1":
                    materialize(db, schedule, branch=branch, boundary=start_boundary(schedule, session["index"]),
                                root=root / "workspace")
                script = dict(compiled.script, sessions=[session])
                clock = SimClock(root / "clock.json", instant, cadence)
                env = EnvWiring(root, {session["index"]: seed}, clock.path) if seed is not None else None
                adapter = None
                result["sessions"] += 1
                result["calls"] += len(calls)
                try:
                    adapter = HermesAdapter(entry, script=script, route_table=table, schedule=FaultLite.load([], script),
                        responder=ScriptedResponder(entry), clock=clock, root=root, scratch=scratch, life=meta["life"],
                        branch=branch, run="check-compile", checkout=checkout, harness_pin=harness_pin,
                        worker_argv=worker_argv, toolsets=HERMES_TOOLSETS, env_server=env)
                    adapter.run_session(session["index"], sim_t_s=instant, lock_hash=sha256_canon(meta),
                                        attempt_id=f"check-{branch}-{session['index']}")
                    mismatches = _compare(adapter, calls)
                    if genre == "G1":
                        for call in calls:
                            offline = expected_result(db, schedule, boundary=start_boundary(schedule, call.session),
                                                      **call.call)
                            if offline != call.expected and not any(m["turn"] == call.turn and m["index"] == call.index
                                                                    for m in mismatches):
                                mismatches.append(_mismatch(call, "result", offline))
                    else:
                        actions = [r for r in env.records(session["index"]) if r.get("type") == "action"]
                        got_hash = actions[-1]["state_hash"] if actions else None
                        if got_hash != end_hash:
                            from dataclasses import replace
                            mismatches.append(_mismatch(replace(calls[-1], expected=end_hash), "env_state", got_hash))
                    result["mismatches"].extend(mismatches)
                except HarnessFailed as error:
                    result["mismatches"].extend(_mismatch(c, f"harness_failed:{error}", None) for c in calls)
                finally:
                    if adapter is not None:
                        try:
                            adapter.close()
                        except HarnessFailed as error:
                            result["mismatches"].extend(_mismatch(c, f"harness_failed:{error}", None) for c in calls)
        finally:
            db.close()
    return dict(life=meta["life"], genre=genre, branches=branches,
                ok=all(b["calls"] > 0 and not b["mismatches"] for b in branches.values()))
