"""S6 offline life preparation and measurement helpers; no quality scoring."""

import argparse
import json
import os
import runpy
import shutil
import sqlite3
import sys
import threading
import time
from dataclasses import asdict, replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from bicentennial.audit.readback import load as load_ledger
from bicentennial.canon import canon, milli, sha256_canon
from bicentennial.director.compiler.hermes import compile_script, write_script
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream import (
    BURST,
    RATE_PER_MIN,
    Holds,
    LiveResponder,
    Pacer,
    Upstream,
)
from bicentennial.director.upstream.login import (
    ENV_STORE,
    CredentialLeak,
    CredentialResponder,
    NeedleGuard,
    Stop,
    auth_for,
    exit_on_refusal,
    open_login,
    scan,
)
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
)
from bicentennial.items.compile import compile_branch
from bicentennial.items.protocol import CANARY
from bicentennial.items.templates.g2 import TEMPLATES
from bicentennial.keyed import assert_hashseed
from bicentennial.ledger import Guard
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import content, verify_branch, write_branch
from bicentennial.runner.guard import read_marker, reexec_niced
from bicentennial.runner.lock import attempt_id
from bicentennial.runner.projection import (
    LIFE_BOUND_MS,
    Cost,
    Lane,
    P,
    Terms,
    breakeven,
    cut_order,
    role_costs,
    stats,
)
from bicentennial.runner.spend import Price, Spend
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.bytes import allocated_bytes, apply_budget, store_bytes
from bicentennial.systems import SystemRefused, registry
from bicentennial.systems.hermes_plugin import PROVIDERS, PluginCell
from bicentennial.systems.settle import settle
from bicentennial.world.scale import FULL_WINDOW, named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.targeted import expected_state, hostable, seed_text

ROOT = Path(__file__).resolve().parents[2]
LIFE_ID, SEED, GENRE = "s6-g2", 6, "G2"
STEP_S = 60
ARM_WALL_S = 86_400
MIN_FREE_GB, START_WAIT_S = 150, 7200
MODEL, EFFORT, ACCOUNT = "gpt-6.1-sol", "medium", "sol-0"
BASE_COMMIT = "85f40375be0e89f1d253b5d6b7d30ea73bff9941"
SYSTEMS = ("hermes-native", "mem0-oss")
QA = tuple(t for t in TEMPLATES if t.kind == "qa")
TERMS = ("R", "R_cap", "P", "f", "r_c", "p_c", "P_K", "P_W", "R_B", "P_B", "delta_W",
         "C_learn", "C_erase", "C_image", "C_cross", "C_marker", "C_aa", "C_ctrl", "C_ring1", "C_ring2")


def load_entry(name):
    if name not in SYSTEMS:
        raise ValueError("unsupported S6 arm")
    return registry.load(registry.REGISTRY / f"{name}.toml")


def build_stack(entry, spend_path, *, auth, base_url, max_output, max_sends, login=None):
    spend = Spend(spend_path, 0, Price(0, 0))
    upstream = Upstream("sol", MODEL, base_url, "responses", spend, Price(0, 0),
                        max_output, effort=EFFORT, send_cap=False)
    pacer = Pacer(RATE_PER_MIN, BURST, threading.Event())
    if login is not None:
        auth = auth_for(login, pacer)
    holds = Holds()
    live = LiveResponder(ACCOUNT, pacer, auth, [upstream], holds, max_sends=max_sends)
    cred = CredentialResponder(live, login) if login is not None else live
    bridge = runpy.run_path(ROOT / "spikes/s7/partB.py")["ResponsesBridge"]
    return Routed(bridge(cred), ScriptedResponder(entry)), cred, holds


class Routed:
    def __init__(self, live, scripted):
        self.live, self.scripted = live, scripted

    def respond(self, call):
        live = (call.role in ("write_turn", "probe_main", "memory_write", "summariser")
                or (call.role, call.subrole) == ("aux", "summariser"))
        try:
            return (self.live if live else self.scripted).respond(call)
        except ValueError as exc:
            if str(exc).startswith("bridge_"):
                self.live.inner.stop(str(exc))
            raise

    def state(self):
        return self.live.state()

    def served_identities(self):
        return self.live.served_identities()


def byte_checkpoint(store, raw):
    return dict(raw_bytes=raw, store_bytes=store, share_milli=milli(Fraction(store, raw)),
                K100=dict(cap=raw, over=apply_budget(store, raw, "K100")),
                K10=dict(cap=raw * 10 // 100, verdict=None, reason="r06_k100_only_v01"))


def surfaces(adapter):
    roots = {"HERMES_HOME": adapter.paths["hermes_home"], "SANDBOX_HOME": adapter.paths["home"]}
    return [(roots[s["root"]] / s["relative"], s["volatile_paths"]) for s in adapter.entry["surfaces"]]


def session_timing(timings):
    """Recovery includes its own spawn/open; retain only the initial entries there."""
    clean = {k: v[:] if isinstance(v, list) else v for k, v in timings.items()}
    for key in ("spawn", "open"):
        clean[key] = clean.get(key, [])[:1]
    job = sum(sum(v) if isinstance(v, list) else v for v in clean.values())
    return clean, job


def _arm_write(root, obj):
    pending = root / ".arm.json.pending"
    pending.write_bytes(canon(obj))
    os.replace(pending, root / "arm.json")


def stop_reason(cred):
    state = cred.state()
    return ("identity_drift" if state.get("identity_drift") else
            "login_stop" if state.get("login_stop") else
            "live_spend_stop" if state.get("spend_stopped") else
            state.get("stop_reason") if state.get("stopped") else None)


def drain_login(cred, root):
    if hasattr(cred, "login"):
        leaked = False
        with (root / "login.jsonl").open("ab") as stream:
            for row in cred.login.drain():
                stream.write(canon(row) + b"\n")
                leaked |= row.get("type") == "guard"
        if leaked:
            raise CredentialLeak("credential guard stopped a ledger write")


def finalise_failure(root, result, *, adapter, cred, login, run):
    """Persist failure before cleanup; scan even if close or the first drain fails."""
    _arm_write(root, result)
    if adapter is not None:
        try:
            adapter.close()
        except BaseException as exc:
            result["close_failed"] = type(exc).__name__
    drain_error = None
    try:
        drain_login(cred, root)
    except BaseException as exc:
        drain_error = exc
    try:
        result["credential_scan"] = scan(login, [root], run)
    finally:
        try:
            drain_login(cred, root)
        except BaseException as exc:
            if drain_error is None:
                drain_error = exc
        finally:
            _arm_write(root, result)
    if result["credential_scan"]["hits"] or result["credential_scan"]["unreadable"]:
        return True
    if drain_error is not None:
        raise drain_error
    return False


def run_arm(arm, adapter, script, starts, *, cred, holds, lock, cell=None, raw=None,
            wall_s=ARM_WALL_S, monotonic=time.monotonic) -> dict:
    """Measure sessions in script order; callers supply an initialised empty-store baseline."""
    root, began = adapter.paths["root"], monotonic()
    trees = surfaces(adapter)
    baseline = [allocated_bytes(path, volatile) for path, volatile in trees]
    out = dict(status="running", sessions=[], sessions_run=0, pauses=[], flagged_sessions=[], bytes={})
    previous, reason = None, None
    failed = False
    try:
        for session in script["sessions"]:
            reason = stop_reason(cred)
            if reason:
                break
            pause = holds.at_boundary(previous)
            if pause["reasons"]:
                out["pauses"].append(dict(after_attempt=previous, **pause))
            if "quota" in pause["reasons"]:
                reason = "quota_hold"
                break
            if monotonic() - began >= wall_s:
                reason = "arm_wall"
                break
            if hasattr(adapter, "egress") and adapter.egress.summary()["non_loopback"]:
                reason = "non_loopback"
                break
            index = session["index"]
            previous = attempt_id(lock, arm, LIFE_ID, "B0", index, 0)
            try:
                result = adapter.run_session(index, sim_t_s=starts[index], lock_hash=lock, attempt_id=previous)
            except HarnessFailed as exc:
                reason = stop_reason(cred) or "harness_failed:" + str(exc)
                out["failed_attempt"] = dict(session=index, kind=session["kind"], attempt_id=previous)
                break
            keys = ("session", "kind", "turns_ok", "finals_matched", "restarts", "compaction_expected",
                    "summariser_records", "surface_hash", "gate", "end_threads")
            record = {k: getattr(result, k) for k in keys}
            if cell is not None:
                record["settle"] = asdict(cell.settle())
            record["timings_ms"], record["job_ms"] = session_timing(result.timings_ms)
            record["attempt_id"] = previous
            record["bytes"] = sum(store_bytes(path, base, volatile)
                                  for (path, volatile), base in zip(trees, baseline, strict=True))
            if raw is not None and session["kind"] == "replay" and index in (20, 60, 120, 200):
                out["bytes"][str(index)] = byte_checkpoint(record["bytes"], raw[index])
            if any(d.get("identity_changed") for row in adapter.records() if row.get("attempt_id") == previous
                   for up in row.get("upstream", []) for d in up.get("diagnostics", [])):
                out["flagged_sessions"].append(index)
            out["sessions"].append(record)
            out["sessions_run"] += 1
            drain_login(cred, root)
            _arm_write(root, out)
            if cell is not None and not record["settle"]["settled"]:
                reason = "settle_failed"
                break
            if hasattr(adapter, "egress") and adapter.egress.summary()["non_loopback"]:
                reason = "non_loopback"
                break
    except BaseException:
        failed = True
        raise
    finally:
        try:
            out["egress"] = adapter.close()
        except BaseException as exc:
            out["close_failed"] = type(exc).__name__
            _arm_write(root, out)
            raise
        finally:
            try:
                drain_login(cred, root)
            except BaseException:
                failed = True
                raise
            finally:
                # A loop or cleanup exception skips the normal receipt write below.
                if failed and "egress" in out:
                    out["egress"]["non_loopback"] = [sha256(v.encode()).hexdigest()
                                                       for v in out["egress"]["non_loopback"]]
                    _arm_write(root, out)
    reason = reason or stop_reason(cred)
    attempt_sessions = {attempt_id(lock, arm, LIFE_ID, "B0", s["index"], 0): s["index"]
                        for s in script["sessions"]}
    out["flagged_sessions"] = sorted({attempt_sessions[row["attempt_id"]] for row in adapter.records()
        if row.get("attempt_id") in attempt_sessions and any(d.get("identity_changed")
            for up in row.get("upstream", []) for d in up.get("diagnostics", []))})
    final_pause = holds.at_boundary(previous)
    if final_pause["reasons"]:
        out["pauses"].append(dict(after_attempt=previous, **final_pause))
    if "quota" in final_pause["reasons"]:
        reason = reason or "quota_hold"
    if monotonic() - began >= wall_s:
        reason = reason or "arm_wall"
    if out["egress"]["non_loopback"]:
        reason = reason or "non_loopback"
        out["egress"]["non_loopback"] = [sha256(v.encode()).hexdigest()
                                           for v in out["egress"]["non_loopback"]]
    out.update(status="stopped" if reason else "complete", stop_reason=reason,
               state=cred.state(), served_identities=cred.served_identities(),
               wall_ms=round((monotonic() - began) * 1000))
    _arm_write(root, out)
    return out


def build_life(out) -> dict:
    """Build once, removing the new directory on any failed generation step."""
    out = Path(out)
    out.mkdir()
    life = None
    try:
        schedule = build_schedule(seed_text(SEED), LIFE_ID, named("full"))
        life = build_base(out / "world.B0.db", seed=seed_text(SEED), life=LIFE_ID,
                          scale=named("full"))
        if life.schedule.to_json() != schedule.to_json():
            raise ValueError("life schedule differs")
        branch = cut(life.db, schedule, branch="B0", principal_id=life.people.principal,
                     expected_state=expected_state(GENRE, schedule)(life.db))
        write_branch(out, branch)
        entries = compile_branch(life.db, schedule, branch, QA).entries
        items = [item for item, meta in entries
                 if hostable(meta["evidence_session"], item["probe_point"])]
        kept = {item["item_id"] for item in items}
        dropped = [item["item_id"] for item, _ in entries if item["item_id"] not in kept]
        compiled = compile_script(out, "B0", schedule, life.db, items=items, step_s=STEP_S)
        faults = FaultLite.load(schedule.fault_lite(), compiled.script)
        required = [dict(kind="kill", session=110, turn=1),
                    dict(kind="swap", session=150, turn=None)]
        if faults.to_obj() != required:
            raise ValueError("full fault schedule differs")
        write_script(out / "script.json", compiled)
        files = {"life.json": dict(canary=CANARY, life=LIFE_ID, seed=seed_text(SEED), scale="full"),
                 "items.B0.json": items, "probes.json": [asdict(p) for p in compiled.probes]}
        for name, obj in files.items():
            with (out / name).open("xb") as stream:
                stream.write(canon(obj))
        return dict(script=compiled.script, probes=files["probes.json"], dropped=dropped,
                    faults=faults.to_obj(), script_sha256=sha256((out / "script.json").read_bytes()).hexdigest())
    except BaseException:
        if life is not None:
            life.db.close()
            life = None
        shutil.rmtree(out)
        raise
    finally:
        if life is not None:
            life.db.close()


def routes(arm):
    return {"routes": [dict(system=arm, segment=f"seg{i}", probe_model=MODEL,
                            summariser=MODEL, alias=alias, vision=None, served_by="live")
                       for i, alias in enumerate(("bicentennial-main", "bicentennial-swap"))]}


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_bytes())


def life_inputs(directory):
    manifest = verify_branch(directory, "B0")
    script = read_json(directory / "script.json")
    plans = [json.loads(row) for row in (directory / "sessions.B0.jsonl").read_bytes().splitlines()]
    probes = read_json(directory / "probes.json")
    schedule = build_schedule(seed_text(SEED), LIFE_ID, named("full"))
    starts = {p.index: p.t_start for p in schedule.sessions}
    starts.update({p["index"]: p["sim_t_s"] for p in probes})
    faults = FaultLite.load([f for p in plans for f in p["fault_points"]], script)
    totals = dict(zip(manifest["session_ids"], [p["index"] for p in plans], strict=True))
    sizes = {p["index"]: 0 for p in plans}
    for row in (directory / "stream.B0.jsonl").read_bytes().splitlines():
        event = json.loads(row)
        sizes[totals[event["session_id"]]] += len(content(event).encode("utf-8"))
    raw, running = {}, 0
    for index in sorted(sizes):
        running += sizes[index]
        raw[index] = running
    return script, plans, starts, faults, raw


def preflight(args):
    assert_hashseed()
    try:
        reexec_niced(sys.argv)
    except (OSError, RuntimeError):
        raise Stop("background_policy") from None
    if os.environ.get("BICENTENNIAL_OPERATOR") != "benchmark":
        raise Stop("benchmark_operator_required")
    for name in (ENV_STORE, "BICENTENNIAL_SOL_TOKEN_URL", "BICENTENNIAL_SOL_CLIENT_ID",
                 "BICENTENNIAL_SOL_BASE_URL"):
        if not os.environ.get(name):
            raise Stop("missing:" + name)
    try:
        if not args.scratch.is_dir() or not os.access(args.scratch, os.W_OK | os.X_OK):
            raise OSError
        free = shutil.disk_usage(args.scratch).free
    except OSError:
        raise Stop("scratch_unusable") from None
    if free < MIN_FREE_GB * 1_000_000_000:
        raise Stop("disk_floor")
    began, readings = time.monotonic(), []
    while True:
        marker = read_marker()
        readings.append(dict(exit=marker.exit, state=marker.state))
        if marker.exit == 0 and marker.state not in (None, "unset", "unreadable"):
            return readings
        if time.monotonic() - began >= START_WAIT_S:
            raise Stop("start_marker_timeout")
        time.sleep(60)


def safe_checkout(path):
    path = path.resolve()
    reference = Path.home() / ".hermes"
    if path.is_relative_to(reference) or path.is_relative_to(reference.resolve()):
        raise ValueError("isolated Hermes checkout required")
    return path


def initialise(adapter, starts, lock, cell=None):
    """An empty cold session uses the same worker/config path without delivering a turn."""
    readings, timing = [], dict(spawn=[], open=[])
    adapter._gate(readings)
    with adapter.egress.forking:
        adapter.director.start_session(1, starts[1], lock, "p06-empty", adapter.paths["root"] / "ledger")
    adapter._alias = adapter.director.route["alias"]
    adapter._wiped = False
    adapter._spawn_open("session_start", None, timing)
    adapter._drain()
    adapter.end_threads = adapter._end()
    settled = asdict(cell.settle() if cell is not None else settle(adapter.entry))
    if not settled["settled"]:
        raise HarnessFailed("initial_settle_failed")
    db = adapter.paths["hermes_home"] / "state.db"
    if db.exists():
        connection = sqlite3.connect(db)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()
    return dict(gate=readings, timings_ms=timing, settle=settled,
                baseline=[allocated_bytes(p, v) for p, v in surfaces(adapter)])


def run_command(args):
    entry = load_entry(args.arm)
    if args.arm == "mem0-oss":
        reason = ("mem0_blocked" if "artifact.sha256" in registry.unmeasured(entry) else
                  "mem0_source_missing" if args.mem0_source is None else None)
        if reason:
            print(reason)
            return 2
    try:
        checkout = safe_checkout(args.hermes)
    except ValueError:
        raise Stop("isolated_hermes_checkout_required") from None
    markers = preflight(args)
    script, plans, starts, faults, raw = life_inputs(args.life)
    table, script_hash = routes(args.arm), digest(args.life / "script.json")
    run = "p06-" + sha256_canon(dict(script=script_hash, routes=table, arm=args.arm))[:16]
    lock = sha256_canon(dict(spike="S6", run=run, script=script_hash, routes=table))
    root = args.scratch / ("p06-" + args.arm)
    if root.exists():
        raise Stop("arm_root_exists")
    login = open_login(os.environ[ENV_STORE], os.environ["BICENTENNIAL_SOL_TOKEN_URL"],
                       os.environ["BICENTENNIAL_SOL_CLIENT_ID"], run)
    root.mkdir()
    spend_path = root / "spend.json"
    cred = SimpleNamespace(login=login)
    adapter, cell, initial, began = None, None, None, time.monotonic()
    metadata = dict(run=run, lock=lock, routes=table, start_marker=markers,
                    sol_max_output=args.sol_max_output, sol_max_output_source=args.sol_max_output_source,
                    max_sends=args.max_sends, script_sha256=script_hash)
    stage = "build_stack"
    try:
        responder, cred, holds = build_stack(entry, spend_path, auth=None,
            base_url=os.environ["BICENTENNIAL_SOL_BASE_URL"], max_output=args.sol_max_output,
            max_sends=args.max_sends, login=login)
        stage = "adapter"
        adapter = HermesAdapter(entry, script=script, route_table=RouteTable.load(table),
            schedule=faults, responder=responder, clock=SimClock(root / "clock.json", starts[1], STEP_S),
            root=root, scratch=args.scratch, life=LIFE_ID, branch="B0", run=run, checkout=checkout,
            plugin=PROVIDERS.get(args.arm), harness_pin=dict(load_entry("hermes-native")["artifact"]),
            kill_mode="boundary", window=FULL_WINDOW)
        adapter.director.guard = NeedleGuard(login, base=Guard([]))
        if args.arm == "mem0-oss":
            stage = "plugin_cell"
            cell = PluginCell(entry, adapter)
            stage = "plugin_install"
            cell.install(args.mem0_source, alias="bicentennial-main")
        stage = "initialise"
        initial = initialise(adapter, starts, lock, cell)
    except BaseException as exc:
        mem0_pin = isinstance(exc, PinMismatch) and stage == "plugin_install"
        label = ("initial_settle_failed" if isinstance(exc, HarnessFailed) and
                 exc.args == ("initial_settle_failed",) else type(exc).__name__)
        result = (dict(status="not_run", reason="mem0_pin_mismatch", inputs=metadata) if mem0_pin else
                  dict(status="stopped", stop_reason="init_failed:" + label, inputs=metadata))
        if finalise_failure(root, result, adapter=adapter, cred=cred, login=login, run=run):
            return 1
        if mem0_pin:
            print("mem0_pin_mismatch")
            return 2
        if isinstance(exc, PinMismatch):
            raise Stop("hermes_pin_mismatch") from None
        raise
    result = None
    try:
        result = run_arm(args.arm, adapter, script, starts, cred=cred, holds=holds, lock=lock,
                         cell=cell, raw=raw, wall_s=max(0, ARM_WALL_S - (time.monotonic() - began)))
        result["session_loop_wall_ms"] = result["wall_ms"]
        result["wall_ms"] = round((time.monotonic() - began) * 1000)
        spend = read_json(spend_path)
        result.update(inputs=metadata, initial=initial, harness=adapter.harness_record(),
                      settled=spend["settled"], refused_calls=spend["refused_calls"])
        _arm_write(root, result)
        try:
            result["credential_scan"] = scan(login, [root], run)
        finally:
            drain_login(cred, root)
        _arm_write(root, result)
    except BaseException as exc:
        if result is None:
            path = root / "arm.json"
            result = read_json(path) if path.exists() else {}
        result.update(status="stopped", stop_reason="replay_failed:" + type(exc).__name__,
                      inputs=metadata, initial=initial, wall_ms=round((time.monotonic() - began) * 1000))
        if finalise_failure(root, result, adapter=adapter, cred=cred, login=login, run=run):
            return 1
        if isinstance(exc, (CredentialLeak, Stop, SystemRefused)):
            raise
        return 4
    if result["credential_scan"]["hits"] or result["credential_scan"]["unreadable"]:
        return 1
    if result["settled"]:
        result.update(status="stopped", stop_reason="nonzero_spend")
        _arm_write(root, result)
        return 4
    return 0 if result["status"] == "complete" else 4


def measurements(result, rows, blobs, script, plans):
    sessions = result["sessions"]
    attempts = sessions + ([result["failed_attempt"]] if result.get("failed_attempt") else [])
    kinds = {s["index"]: s["kind"] for s in script["sessions"]}
    if any(s["session"] not in kinds or kinds[s["session"]] != s["kind"] for s in attempts):
        raise ValueError("summary_session_mismatch")
    costs = role_costs(rows, blobs, {s["attempt_id"]: s["session"] for s in attempts})
    roles, probe_roles, per_session = {}, {}, {}
    replay, probes, fixed, own_turn, episode_cost = Cost(), [], [], [], Cost()
    probe_sizes = {s["index"]: len(s["turns"]) for s in script["sessions"] if s["kind"] == "probe"}
    for session in sessions:
        index = session["session"]
        role = costs.get(index, {})
        total = sum(role.values(), Cost())
        group = roles if session["kind"] == "replay" else probe_roles
        for name, value in role.items():
            group[name] = group.get(name, Cost()) + value
        own = max(0, session["job_ms"] - total.held_ms)
        per_session[str(index)] = dict(roles={k: v.to_obj() for k, v in role.items()},
                                      job_ms=session["job_ms"], own_ms=own)
        total = replace(total, wall_ms=own)
        if session["kind"] == "replay":
            replay += total
        else:
            probes.append(index)
            timing = session["timings_ms"]
            turns, drains = timing.get("turn", []), timing.get("drain", [])
            if len(drains) != len(turns) + 1:
                raise ValueError("summary_drain_mismatch")
            fixed.append(sum(timing.get("spawn", [])) + sum(timing.get("open", [])) +
                         timing.get("close", 0) + drains[-1])
            own_turn.append(max(0, sum(turns) + sum(drains[:-1]) - total.held_ms))
            episode_cost += replace(total, wall_ms=0)
    n_items = sum(probe_sizes[i] for i in probes)
    episode = episode_cost * Fraction(1, n_items) if n_items else Cost()
    if probes:
        episode = replace(episode, wall_ms=Fraction(sum(fixed), len(fixed)) + Fraction(sum(own_turn), n_items))
    lower = replay.wall_ms + episode.wall_ms
    terms = Terms(R=replay, e_probe=episode, critical_path_ms=lower)
    sprint_ids = {p["index"] for p in plans if p["long_sprint"]}
    compactions = {"sprints": {}, "ordinary": {}}
    for s in sessions:
        if s["kind"] == "replay":
            compactions["sprints" if s["session"] in sprint_ids else "ordinary"][str(s["session"])] = s["summariser_records"]
    metrics = dict(roles={k: v.to_obj() for k, v in roles.items()}, session_costs=per_session,
                   failed_attempt_roles={k: v.to_obj() for k, v in
                       costs.get(result.get("failed_attempt", {}).get("session"), {}).items()},
                   probe_roles={k: v.to_obj() for k, v in probe_roles.items()},
                   R=replay.to_obj(), e_probe=episode.to_obj(), probe_n_items=n_items,
                   probe_n_sessions=len(probes), probe_fixed_ms=stats(fixed), probe_own_turn_ms=stats(own_turn),
                   job_ms=stats([s["job_ms"] for s in sessions]),
                   own_ms=stats([s["own_ms"] for s in per_session.values()]), compactions=compactions,
                   critical_path_lower_bound_ms=round(lower),
                   unknown=sum(r.get("role") == "unknown" for r in rows),
                   recovery_110_120=sum((replace(sum(costs.get(s["session"], {}).values(), Cost()),
                       wall_ms=per_session[str(s["session"])]["own_ms"]) for s in sessions
                       if 110 <= s["session"] <= 120), Cost()).to_obj())
    return terms, metrics


def term_table(t):
    values = dict(R=t.R, R_cap=t.R, P=P(t), f=dict(numerator=1, denominator=2),
                  r_c=t.R * t.r_share, p_c=P(t) * t.p_share, P_K=P(t) * t.pk_share,
                  P_W=P(t) * t.pw_share, R_B=t.R, P_B=P(t), delta_W=1)
    statuses = dict(R="measured", R_cap="derived", P="derived", R_B="assumed", P_B="assumed")
    table = {k: dict(status=statuses.get(k, "assumed"),
                     value=v.to_obj() if isinstance(v, Cost) else v,
                     source="P06 Decision 12; PREREG v0.4 section 11") for k, v in values.items()}
    for name in ("C_learn", "C_erase", "C_image", "C_cross", "C_marker", "C_aa", "C_ctrl", "C_ring1", "C_ring2"):
        table[name] = dict(status="missing" if name in ("C_learn", "C_erase") else
                          "not_run" if name == "C_image" else "shared_unmeasured", value=None,
                          source="ERRATA E9" if name == "C_learn" else "P06 Decision 12")
    return {name: table[name] for name in TERMS}


def summarise(args):
    if args.out.exists():
        raise FileExistsError("summary exists")
    verify_branch(args.life, "B0")
    script = read_json(args.life / "script.json")
    FaultLite.load([], script)  # Validate the script without the unexecuted full-life faults.
    plans = [json.loads(row) for row in (args.life / "sessions.B0.jsonl").read_bytes().splitlines()]
    inputs = dict(life=LIFE_ID, hashes={name: digest(args.life / name) for name in
                  ("world.B0.db", "script.json", "stream.B0.jsonl", "life.json")},
                  route_table_hashes={arm: sha256_canon(routes(arm)) for arm in SYSTEMS},
                  pins={arm: load_entry(arm)["artifact"] for arm in SYSTEMS}, model=MODEL, effort=EFFORT,
                  window=FULL_WINDOW, window_source="illustrative; C-4 open", base_commit=BASE_COMMIT,
                  capacity=dict(rate_per_min=RATE_PER_MIN, rate_source="R17a RATE_PER_MIN; S6c",
                                concurrency=20, concurrency_source="S6b report line 116",
                                accounts=[1, 2], accounts_source="S6c report lines 229-231"))
    obj = dict(canary=CANARY, claim_class="advisory", mode="live", spend_microdollars=0,
               inputs=inputs, arms={}, bytes={}, terms={}, projection={})
    inputs["run_parameters"] = {}
    for arm in SYSTEMS:
        root = args.scratch / ("p06-" + arm)
        path = root / "arm.json"
        if not path.exists():
            result = dict(status="not_run", reason="mem0_blocked" if arm == "mem0-oss" and
                          "artifact.sha256" in registry.unmeasured(load_entry(arm)) else "no_run")
        else:
            result = read_json(path)
        scan_result = result.get("credential_scan", {})
        if (path.exists() and not scan_result) or scan_result.get("hits") or scan_result.get("unreadable"):
            raise CredentialLeak("summary requires a clean credential scan")
        if result["status"] == "not_run" or result.get("close_failed"):
            refusal = (dict(status="not_run", reason="close_failed:" + result["close_failed"])
                       if result.get("close_failed") else
                       {k: result[k] for k in ("status", "reason")})
            for key in ("arms", "bytes", "terms", "projection"):
                obj[key][arm] = refusal
            continue
        if not scan_result:
            raise CredentialLeak("summary requires a clean credential scan")
        if result["inputs"]["script_sha256"] != digest(args.life / "script.json"):
            raise ValueError("summary_script_mismatch")
        if result.get("settled", 0):
            raise ValueError("nonzero spend")
        if result["status"] == "stopped" and "sessions" not in result:
            obj["arms"][arm] = result
            for key in ("bytes", "terms", "projection"):
                obj[key][arm] = dict(status="not_run", reason="incomplete_life")
            continue
        rows, blobs, ledger_hash = load_ledger(root / "ledger", "kit")
        t, metrics = measurements(result, rows, blobs, script, plans)
        obj["arms"][arm] = dict(result, **metrics, ledger_sha256=ledger_hash)
        obj["bytes"][arm], obj["terms"][arm] = result["bytes"], term_table(t)
        inputs["run_parameters"][arm] = {k: result["inputs"][k] for k in
                                        ("sol_max_output", "sol_max_output_source", "max_sends")}
        if result["status"] != "complete":
            obj["projection"][arm] = dict(status="not_run", reason="incomplete_life")
            for name in ("R", "R_cap", "P"):
                obj["terms"][arm][name]["status"] = "partial"
            continue
        projections = {}
        for accounts in (1, 2):
            lane = Lane(f"sol-{accounts}", RATE_PER_MIN, 20, accounts)
            projections[lane.name] = dict(cut_order=cut_order(t, lane), breakeven=dict(
                v04=breakeven(t, lane, n_L=48, n_rob=8),
                s6b=breakeven(t, lane, n_L=48, n_rob=8, bound_ms=LIFE_BOUND_MS, a=0),
                s6b_cuts_1_2=breakeven(replace(t, b=100), lane, n_L=48, n_rob=4,
                                      bound_ms=LIFE_BOUND_MS, a=0)))
        projections.update(replication_family=dict(status="not_run"), swap=dict(status="not_run"))
        obj["projection"][arm] = {LIFE_ID: projections}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as stream:
        stream.write(canon(obj))
    return 0


def positive(text):
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError("positive integer required")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--out", required=True, type=Path)
    run = commands.add_parser("run")
    run.add_argument("--arm", choices=SYSTEMS, required=True)
    for flag in ("life", "scratch", "hermes"):
        run.add_argument("--" + flag, required=True, type=Path)
    run.add_argument("--mem0-source", type=Path)
    run.add_argument("--sol-max-output", required=True, type=positive)
    run.add_argument("--sol-max-output-source", required=True)
    run.add_argument("--max-sends", required=True, type=positive)
    summary = commands.add_parser("summarise")
    for flag in ("scratch", "life", "out"):
        summary.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            print("sha256 " + build_life(args.out)["script_sha256"])
            return 0
        return run_command(args) if args.command == "run" else summarise(args)
    except CredentialLeak:
        print("credential_leak", file=sys.stderr)
        return 1
    except Stop as exc:
        exit_on_refusal(exc)
    except Exception as exc:
        refused = isinstance(exc, SystemRefused) or (args.command in ("summarise", "build") and
                                                   isinstance(exc, (ValueError, FileExistsError)))
        label = (exc.args[0] if args.command == "summarise" and isinstance(exc, ValueError) and
                 exc.args in (("summary_script_mismatch",), ("summary_session_mismatch",),
                              ("summary_drain_mismatch",)) else type(exc).__name__)
        print(label, file=sys.stderr)
        return 3 if refused else 4


if __name__ == "__main__":
    raise SystemExit(main())
