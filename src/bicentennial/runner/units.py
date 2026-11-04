"""Shared unit execution and tier admission policy."""

import json
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path
from threading import Event, Lock
from typing import Callable

from bicentennial.audit.readback import output
from bicentennial.canon import canon, sha256_canon
from bicentennial.director.compiler.check import Voids
from bicentennial.director.responder import Reply
from bicentennial.director.upstream import login as custody
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items.protocol import CANARY
from bicentennial.ledger import BlobStore, Guard
from bicentennial.probe.scripted_reader import ReaderResult
from bicentennial.report.t2lite_card import _LIVE_ANSWER
from bicentennial.report.t2lite_flips import BaselineRefused
from bicentennial.runner import t0
from bicentennial.runner.hermes_score import MISSING, Infra, identity0, score_item
from bicentennial.runner.kept import KeptRefused
from bicentennial.runner.life import LifeRun, _rows, _tokens, run_life
from bicentennial.runner.lock import SessionGate
from bicentennial.runner.probe_live import (
    LatchStop,
    LiveCredentialStop,
    LiveStop,
    check_live_stop,
)
from bicentennial.sandbox.envserver.honeypot import hits
from bicentennial.score.classes import outcome
from bicentennial.systems.hermes_plugin import is_plugin, resolve_worker_env


@dataclass(frozen=True)
class TierSpec:
    pack_tier: str
    composition: tuple[str, ...]
    roots: int
    context_roots: Callable
    order: str = "serial"
    min_roots: int = 1
    probe_mode: str = "ring0"
    keep_pre_probe: bool = False
    pre_probe_attribution: bool = False


def _t1_roots(marker, admission):
    return 2 if marker.exit == 0 else 1


T1_SPEC = TierSpec("T1", ("G1", "G2"), 2, _t1_roots)
T2_SPEC = TierSpec("T2", ("G1",) * 5 + ("G2",) * 5, 8,
                   lambda marker, admission: admission.max_roots, "longest", 4, "per_item", True, True)

# Only T2 raises these (T1 and T2-lite always admit a root); T2's guide, written with its runner, documents them.
T2_ONLY_REFUSALS = frozenset({"roots_below_min"})


@dataclass(frozen=True)
class UnitResult:
    scores: dict
    probes: list
    measured: bool
    runs: tuple[LifeRun, ...]
    attempts: int
    stop: tuple | None
    timing: dict | None = None
    keep_ms: int = 0


class UnitRefusal(Exception):
    """Deliver every attempt to the caller before it handles the original refusal."""

    def __init__(self, error, runs, timing):
        self.error, self.runs, self.timing = error, runs, timing
        super().__init__(str(error))


class _Guard:
    def __init__(self, stack):
        self.stack = stack
        self._canary, self.stopped = Event(), Event()
        self.launch = Lock()

    @property
    def canary(self):
        return self._canary.is_set()

    @canary.setter
    def canary(self, value):
        # Preserve flag injection while allowing only monotonic transitions.
        if value:
            self._canary.set()

    def __getattr__(self, name):
        return getattr(self.stack, name)

    def state(self):
        state = dict(self.stack.state())
        if self.stopped.is_set():
            state["latch_stopped"] = not (state.get("stopped") or state.get("stop_reason"))
            state["stopped"] = True
        return state

    def respond(self, call):
        if CANARY.encode() in canon(call.body):
            self._canary.set()
        if self.canary:
            return Reply(503, "live_stopped", "live", call.model)
        return self.stack.respond(call)


def _write(root, name, value):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canon(value))


def _read(root, name):
    return json.loads((Path(root) / name).read_bytes())


def _isolation(run):
    from bicentennial.runner import t1

    # Worker sockets use T1's check. Provider rows use A5's live predicate (audit/readback.py) and only
    # that: A5's other failures are scripted-reply checks, which the audit status makes INFRA, as in T1.
    try:
        t0._check_egress([([], run.egress)], t1.T1Refused)
    except t1.T1Refused:
        raise t1.T1Refused("isolation") from None
    if _live_breach(run.records):
        raise t1.T1Refused("isolation")


def _live_breach(records):
    for r in records:
        live = [u for u in r.get("upstream", ()) if u.get("served_by") == "live"]
        if (r.get("served_by") == "live" or live) and not (
                r.get("role") == "probe_main" and all(u.get("role") == "probe_main" for u in live)):
            return True
    return False


def _breached(run):
    # What outranks a stop: worker egress or a non-probe live role, seen before it. Unobserved egress does not,
    # since a stopped attempt can end before a worker is sampled.
    return bool(run.egress.get("non_loopback")) or _live_breach(run.records)


def _check_stop(live):
    from bicentennial.runner import t1

    state = live.state()
    check_live_stop(state)
    if state.get("spend_stopped"):
        raise t1.T1Refused("spend_stop")


def _floor_measured(pack, branch, run, probes, scores):
    """Check each scored item's terminal live reply before this attempt's blobs are removed."""
    if run.stopped or run.audit.get("status") != "OK":
        return False
    store = BlobStore(run._root / "run/ledger/blobs", Guard([]))
    sessions = {p["item_id"]: p["probe_session"] for p in probes}
    turns, measured = {}, []
    # The compiler preserves item order within each probe session, including its separate act sessions.
    for item in pack.items[branch]:
        iid = item["item_id"]
        session = sessions[iid]
        turns[session] = turns.get(session, 0) + 1
        scored = scores[iid]
        if (pack.genre == "G2" and item["stage"] == "act"
                and not isinstance(scored, Infra) and scored["failure_class"] is None):
            continue
        final = next((r for r in reversed(run.records) if r.get("role") == "probe_main"
            and r.get("cursor") == dict(session=session, turn=turns[session])), {})
        answered = False
        if (not run.classes.get(iid, (None, None))[0] and not isinstance(scored, Infra)
                and final.get("served_by") == "live" and final.get("status") == 200):
            try:
                calls, texts = output(json.loads(store.get(final["resp"])), "chat")
                # A blank reply is no answer: caching it would keep a provider glitch for every later run.
                answered = not calls and any(t.strip() if isinstance(t, str) else t for t in texts)
            except (OSError, ValueError, KeyError, TypeError, IndexError):
                pass
        measured.append(answered)
    return all(measured)


class _ArmGate:
    """Pass the run-local arm key through the life runner's role-based interface."""

    def __init__(self, context, key):
        self.context, self.key = context, key

    def start_session(self, current_lock, role, life, branch, session, attempt):
        return self.context.session_gate.start_session(
            current_lock, self.key, life, branch, session, attempt)


class _ArmContext:
    """An arm's entry pins over the run's detached baseline and fresh pin checks."""

    def __init__(self, context, config):
        self.context, self.entry = context, config.entry
        self.plugin_source, self.model_cache = config.plugin_source, config.model_cache
        self.worker_argv = config.worker_argv
        self.gate = _ArmGate(self, config.key)

    def __getattr__(self, name):
        return getattr(self.context, name)

    def _entry_lock(self, lock):
        # make_units keeps every arm on the run's system, so its route table is the run's, and these are the
        # two fields of t1._lock that an arm's entry can change.
        from bicentennial.systems.recipe import system_artifacts

        return lock | dict(system_artifacts=system_artifacts(self.entry),
            tool_lists_hash=sha256_canon({k: self.entry.get(k)
                for k in ("read_tools", "recall", "write_tools")}))

    @cached_property
    def lock(self):
        return (self.context.lock if self.entry == self.context.entry
                else self._entry_lock(self.context.lock))

    @cached_property
    def pins(self):
        return (self.context.pins if self.entry == self.context.entry else
                self.context.pins | dict(system_hash=sha256_canon(self.lock["system_artifacts"])))

    def current_lock(self):
        lock = self.context.current_lock()
        return lock if self.entry == self.context.entry else self._entry_lock(lock)

    @cached_property
    def session_gate(self):
        return (self.context.gate if self.entry == self.context.entry else SessionGate(self.lock))


def _unit(ctx, pack, branch, arm, scratch, live, out, floor_stops=None, *, slot=0, config=None,
          spec=T1_SPEC, keep=None, unit=None):
    config = config or Arm.from_context(ctx, arm)
    key, arm = config.key, config.role
    ctx = _ArmContext(ctx, config)
    start, runs = time.time_ns() // 1_000_000, []

    def timing():
        return dict(life=pack.life, branch=branch, arm=key, slot=slot,
            start_ms=start, end_ms=time.time_ns() // 1_000_000, attempts=len(runs))

    try:
        options = dict(spec=spec, keep=keep, unit=unit) if spec is not T1_SPEC or keep is not None else {}
        result = _unit_attempts(ctx, pack, branch, arm, scratch, live, runs, out, floor_stops, **options)
    except Exception as error:
        with live.launch:
            live.stopped.set()
        raise UnitRefusal(error, tuple(replace(r, arm=key) for r in runs), timing()) from error
    return replace(result, runs=tuple(replace(r, arm=key) for r in result.runs), timing=timing())


def _unit_attempts(ctx, pack, branch, arm, scratch, live, runs, out, floor_stops=None, *,
                   spec=T1_SPEC, keep=None, unit=None):
    from bicentennial.runner import t1

    measured, keep_ns = False, 0
    for attempt in range(3):
        try:
            run = run_life(arm=arm, entry=ctx.entry, life_dir=pack.life_dir, branch=branch,
                items=pack.items[branch], records=pack.records_b[branch], keys=pack.keys,
                scratch=scratch / str(attempt), run=ctx.run_id, attempt=attempt, gate=ctx.gate,
                current_lock=ctx.current_lock, voids=Voids(), harness_pin=ctx.harness_pin,
                hermes=ctx.hermes, plugin_source=None if arm == "no_memory" else ctx.plugin_source,
                worker_argv=t1._worker(ctx, pack.life, branch, arm), visible=pack.visible,
                honeypot_token=pack.meta["honeypot_token"], live=live, turn_wait_s=ctx.turn_wait_s,
                probe_mode=spec.probe_mode,
                keep_pre_probe=spec.keep_pre_probe and arm != "no_memory",
                pre_probe_attribution=spec.pre_probe_attribution and arm != "no_memory",
                extra_env=resolve_worker_env(ctx.entry, ctx.model_cache) if arm != "no_memory" else None)
        except LiveCredentialStop as error:
            ledger = scratch / str(attempt) / branch / "run/ledger"
            rows = _rows(ledger)
            # The adapter's honeypot count (harness/hermes/adapter.py), over the requests sent before the stop.
            token, store = pack.meta["honeypot_token"], BlobStore(ledger / "blobs", Guard([]))
            honeypot = hits(token, [store.get(r["req"]).decode() for r in rows
                                    if r.get("type") == "request"]) if token else 0
            runs.append(LifeRun(arm, pack.life, branch, attempt, records=tuple(rows),
                tokens_by_role=_tokens(ledger, rows), honeypot_hits=honeypot,
                egress=getattr(error, "egress", None) or {}))
            if isinstance(error, LatchStop):
                # Another unit's latch stopped this one early. The reduction drops latch stops, so keep the refusal
                # this unit's own checks below would make, judging the partial run as a stop's relabel does.
                if _breached(runs[-1]):
                    raise t1.T1Refused("isolation") from error
                if live.canary:
                    raise t1.T1Refused("canary") from error
            raise
        runs.append(run)
        try:
            _isolation(run)
            if live.canary:
                raise t1.T1Refused("canary")
            _check_stop(live)
            scores, excluded = {}, set()
            probes = _read(run._root, "t2lite_probes.json")
            # T1's relabel (runner/t1.py): a stop the floor shared is the harness's, not the system's.
            floor_stop = (floor_stops or {}).get(pack.life + branch)
            relabel = (arm == "system" and is_plugin(ctx.entry) and run.stopped
                and run.stopped[1] in t1.RELABEL and floor_stop and list(floor_stop)[1:] == list(run.stopped)[1:])
            for item in pack.items[branch]:
                iid = item["item_id"]
                cls, label = run.classes.get(iid, (None, None))
                if relabel and (cls, label) == ("SYSTEM_FAILURE", run.stopped[1]):
                    cls = "INFRA_FAILURE"
                if run.audit.get("status") != "OK" and cls not in ("SYSTEM_FAILURE", "INFRA_FAILURE"):
                    cls, label = "INFRA_FAILURE", "audit"
                shadow, answer = run.results.get(iid, MISSING), run.envelopes.get(iid, MISSING)
                not_scored_live = (pack.genre == "G2" and item["stage"] == "act"
                                  and cls not in ("SYSTEM_FAILURE", "INFRA_FAILURE"))
                result = shadow
                if isinstance(shadow, ReaderResult):
                    # The answer is the live model's; the selection and competitors are the shadow's. Ring 0
                    # ties the two, which does not hold here, so score the answer as L4's card check reads it.
                    asserted = isinstance(answer, dict) and answer.get("type") != "unknown"
                    result = replace(shadow, selected_option=_LIVE_ANSWER if asserted else None, competing_present=())
                if not_scored_live:
                    excluded.add(iid)
                    scores[iid] = dict(identity0(item), infra_reruns=attempt, base_verdict=None,
                        score_milli=None, worst_case_milli=None, accuracy_correct=None,
                        tuesday_class=None, envelope=None, failure_class=None, benign_extra=False)
                else:
                    scores[iid] = score_item(item, cls=cls, label=label,
                        result=result, envelope=answer,
                        act=run.act.get(iid, MISSING), case=pack.cases[iid], keys=pack.keys[iid],
                        scoring_evidence=pack.scoring["evidence"].get(iid), attempt=attempt,
                        stored_roots=run.stored_roots.get(iid), retained_roots=run.retained_roots.get(iid))
                if isinstance(shadow, ReaderResult) and cls != "SYSTEM_FAILURE" and not isinstance(scores[iid], Infra):
                    scores[iid].update(selected_option=shadow.selected_option,
                                       competing_present=list(shadow.competing_present))
                if cls or isinstance(scores[iid], Infra) or not_scored_live:
                    next(p for p in probes if p["item_id"] == iid)["shadow"]["stage_attribution"] = None
            _write(out, "t2lite_probes.json", probes)
            final = attempt == 2 or not any(isinstance(s, Infra) for s in scores.values())
            if arm == "no_memory" and final:
                measured = _floor_measured(pack, branch, run, probes, scores)
            if keep is not None and arm != "no_memory" and final:
                kept_scores = {iid: (outcome(identity0(pack.cases[iid].item), None,
                    cause="INFRA_FAILURE", infra_reruns=2) if isinstance(scored, Infra) else deepcopy(scored))
                    for iid, scored in scores.items()}
                keep_start = time.monotonic_ns()
                keep(unit, run, kept_scores, excluded)
                keep_ns += time.monotonic_ns() - keep_start
        finally:
            run.cleanup()
        if attempt == 2 or not any(isinstance(s, Infra) for s in scores.values()):
            break
    for iid, scored in scores.items():
        if isinstance(scored, Infra):
            scores[iid] = outcome(identity0(pack.cases[iid].item), None, cause="INFRA_FAILURE", infra_reruns=2)
    # The shadow selection belongs to the shadow, not the live scorer's synthetic option.
    for probe in probes:
        row = scores[probe["item_id"]]
        if row["failure_class"] is None:
            row["selected_option"] = probe["shadow"]["selected_option"]
    return UnitResult(scores, probes, measured, tuple(runs), len(runs), runs[-1].stopped,
                      keep_ms=keep_ns // 1_000_000)


def refusal_code(error, *, live=None, runs=(), needles=()):
    """Preserve the serial runner's publication precedence and stop-detail scan."""
    reasons = getattr(error, "reasons", ())
    code = ("live_stop" if isinstance(error, LiveStop) else
        "credential_stop" if isinstance(error, (LiveCredentialStop, custody.Stop)) else
        error.reason if isinstance(error, BaselineRefused) else getattr(error, "code", None) or (
            ",".join(sorted(reasons)) if reasons else
            "gate_refused" if isinstance(error, GateRefused) else "pin_mismatch"))
    if code in ("credential_stop", "spend_stop", "live_stop"):
        if live is not None and live.canary:
            code = "canary"
        elif any(run.honeypot_hits for run in runs):
            code = "honeypot"
        elif any(_breached(run) for run in runs):
            code = "isolation"
    if code == "live_stop" and any(n in error.reason.encode() or n in canon([error.reason]) for n in needles):
        code = "credential_scan"
    return code


def reduce_refusals(errors):
    """Choose a unit refusal by reason, independently of worker completion order."""
    from bicentennial.runner import t1

    errors = tuple(errors)
    primary = tuple(e for e in errors if not isinstance(e, LatchStop))
    # An unexpected exception must reach the tool-failure handler even alongside real refusals.
    crashes = tuple(e for e in primary if not isinstance(e, (
        LiveCredentialStop, custody.Stop, BaselineRefused, KeptRefused, *t1.REFUSALS)))
    errors = crashes or primary or errors
    precedence = {code: rank for rank, code in enumerate(
        ("canary", "honeypot", "credential_scan", "credential_stop", "spend_stop", "live_stop"))}

    def key(error):
        code = refusal_code(error)
        return (precedence.get(code, len(precedence)), code, str(getattr(error, "reason", "")),
                tuple(sorted(getattr(error, "detail", ()))), tuple(sorted(getattr(error, "fields", ()))))

    return min(errors, key=key) if errors else None


@dataclass(frozen=True)
class Arm:
    """Run-local identity, independent of the entry name and the life runner's role."""

    key: str
    entry: dict
    plugin_source: object = None
    model_cache: object = None
    worker_argv: object = None
    role: str = "system"

    def __post_init__(self):
        if not self.key or self.key in (".", "..") or "/" in self.key or "\\" in self.key:
            raise ValueError("invalid arm key")
        if self.role not in ("system", "no_memory") or (self.key == "no_memory") != (self.role == "no_memory"):
            raise ValueError("invalid arm role")

    @classmethod
    def from_context(cls, ctx, key="system"):
        return cls(key, ctx.entry, ctx.plugin_source, ctx.model_cache, ctx.worker_argv,
                   "no_memory" if key == "no_memory" else "system")


@dataclass(frozen=True)
class Unit:
    arm: Arm
    pack: object
    branch: str
    scratch: Path
    out: Path

    @property
    def identity(self):
        return self.arm.key, self.pack.life, self.branch


# Design D10: predicted seconds per replay session and per probe session.
REPLAY_SESSION_SECONDS = 43
PROBE_SESSION_SECONDS = 49


def predicted_seconds(unit):
    # T2 uses one probe session per item. The shared floor has no replay sessions.
    replay = len(unit.pack.schedule.sessions) if unit.arm.role != "no_memory" else 0
    return replay * REPLAY_SESSION_SECONDS + len(unit.pack.items[unit.branch]) * PROBE_SESSION_SECONDS


def make_units(ctx, arms, scratch, out):
    """One shared floor followed by each arm, in card/life/branch order."""
    arms = tuple(arms)
    if len({a.key for a in arms}) != len(arms) or any(a.role != "system" for a in arms):
        raise ValueError("duplicate or reserved system arm")
    if not arms:
        raise ValueError("missing system arm")
    # An arm of another system would bypass the run's admission and keep the run's route table in its lock.
    if any(a.entry.get("name") != ctx.entry["name"] for a in arms):
        raise ValueError("an arm runs another system than the run's")
    floor = replace(arms[0], key="no_memory", role="no_memory")
    return tuple(Unit(a, p, b, Path(scratch) / a.key / p.life / b, Path(out) / a.key / p.life / b)
                 for a in (floor, *arms) for p in ctx.packs for b in ("B0", "B1"))


@dataclass(frozen=True)
class Collected:
    results: dict
    runs: tuple
    timings: tuple
    errors: tuple

    def merge(self, runs, timings):
        """Retain all attempts before the caller maps the selected error to publication."""
        runs.extend(self.runs)
        timings.extend(self.timings)
        error = reduce_refusals(self.errors)
        if error is not None:
            raise error
        return self.results


def schedule(ctx, unit_list, live, *, spec=T1_SPEC, roots=None, floor_stops=None, execute=None, keep=None):
    """Admit ready units to bounded slots; collect every worker before reducing errors."""
    unit_list = tuple(unit_list)
    if len({u.identity for u in unit_list}) != len(unit_list):
        raise ValueError("duplicate unit")
    roots = ctx.roots if roots is None else roots
    if roots < 1:
        raise ValueError("invalid roots")
    if keep is not None and execute is not None:  # a custom executor never calls keep, so a miss's copy would be lost
        raise ValueError("keep needs the default executor")
    floor_stops = dict(floor_stops or {})
    final = set(floor_stops)
    pending, active, completed = list(range(len(unit_list))), {}, {}
    available = list(range(roots))
    default_execute = execute is None
    execute = execute or _unit
    keep_lock = Lock()

    def serialized_keep(unit, run, scores, excluded):
        with keep_lock:
            return keep(unit, run, scores, excluded)

    def ready(i):
        u = unit_list[i]
        return (u.arm.role == "no_memory" or not is_plugin(u.arm.entry)
                or u.pack.life + u.branch in final)

    def run(i, slot):
        u = unit_list[i]
        with live.launch:
            if live.stopped.is_set():
                return None
        try:
            options = (dict(spec=spec, keep=serialized_keep if keep is not None else None, unit=u)
                       if default_execute and (spec is not T1_SPEC or keep is not None) else {})
            return execute(ctx, u.pack, u.branch, u.arm.key, u.scratch, live, u.out,
                           dict(floor_stops), slot=slot, config=u.arm, **options)
        except Exception as error:
            with live.launch:
                live.stopped.set()
            return error

    class InlineExecutor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def submit(self, function, *args):
            future = Future()
            future.set_result(function(*args))
            return future

    executor = InlineExecutor() if roots == 1 else ThreadPoolExecutor(max_workers=roots)
    with executor as pool:
        try:
            while pending or active:
                while pending and available and not live.stopped.is_set():
                    candidates = [i for i in pending if ready(i)]
                    if not candidates:
                        break
                    i = min(candidates, key=lambda i: (-predicted_seconds(unit_list[i]), i)
                            if spec.order == "longest" else (i,))
                    pending.remove(i)
                    slot = available.pop(0)
                    active[pool.submit(run, i, slot)] = (i, slot)
                if not active:
                    if pending and not live.stopped.is_set():
                        raise ValueError("missing final floor")
                    break
                done, _ = wait(active, return_when=FIRST_COMPLETED)
                for future in done:
                    i, slot = active.pop(future)
                    available.append(slot)
                    value = future.result()
                    if value is not None:
                        completed[i] = value
                    if isinstance(value, UnitResult) and unit_list[i].arm.role == "no_memory":
                        key = unit_list[i].pack.life + unit_list[i].branch
                        floor_stops[key] = value.stop
                        final.add(key)
                available.sort()
        except BaseException:
            with live.launch:
                live.stopped.set()
            for future in active:
                future.cancel()
            raise
    results, runs, timings, errors = {}, [], [], []
    for i in sorted(completed):
        value = completed[i]
        if isinstance(value, UnitRefusal):
            runs.extend(value.runs)
            timings.append(value.timing)
            errors.append(value.error)
        elif isinstance(value, Exception):
            errors.append(value)
        else:
            results[unit_list[i].identity] = value
            runs.extend(value.runs)
            timings.append(value.timing)
    return Collected(results, tuple(runs), tuple(timings), tuple(errors))
