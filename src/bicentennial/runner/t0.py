"""Offline T0 execution over verified installed packs."""

import json
import os
import shutil
import stat
import subprocess
import sys
import time
import traceback
import unicodedata
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from bicentennial.api.adapters import mutants
from bicentennial.api.adapters.bm25 import BM25
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.contract import event_copy, shape
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.items import reader_view
from bicentennial.controls.cache import (
    ControlsTampered,
    cache_key,
    card_controls,
    code_sha256,
    ensure,
    read_entry,
)
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.director.scripted import ScriptedResponder, stub_disclosures
from bicentennial.gitenv import git_env
from bicentennial.harness.hermes.adapter import HarnessFailed, PinMismatch
from bicentennial.harness.hermes.plugin_host import (
    ENTRYPOINT,
    GateRefused,
    HermesMemoryHost,
    WriteDelivery,
)
from bicentennial.items import c7
from bicentennial.keyed import mint_id
from bicentennial.ledger import BlobStore, Guard
from bicentennial.packs import relations
from bicentennial.packs.catalogue import TEMPLATES_BY_GENRE, c7_entries, load_catalogue
from bicentennial.packs.install import verify
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.packs.scoring import control_input, make_score
from bicentennial.probe.scripted_reader import api_task, failing_stage, read_api
from bicentennial.report.card import assemble, finalize
from bicentennial.report.junit import (
    Case,
    item_suite,
    junit_cases_from_invariants,
    junit_xml,
    run_properties,
)
from bicentennial.report.receipt import (
    SpendRefused,
    build_receipt,
    busy,
    ledger_latencies,
    load_milli,
    raw_body_digest,
    write_run,
)
from bicentennial.runner.guard import admit, read_marker
from bicentennial.runner.lock import LockMismatch, SessionGate, build_lock, lock_hash
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox.envserver.honeypot import hits
from bicentennial.sandbox.surfaces import clone_tree
from bicentennial.score.aggregate import reduce
from bicentennial.score.bundle import make_bundle
from bicentennial.score.classes import outcome
from bicentennial.score.invariants import (
    INVARIANTS,
    STRESSES,
    VERBATIM,
    ItemEvidence,
    SystemFault,
    Verdict,
    adapter_invariant,
    run_invariants,
)
from bicentennial.systems.hermes_plugin import (
    ENGINES,
    PROVIDERS,
    cache_digest,
    is_plugin,
    prepare_cache,
    resolve_worker_env,
    validate_maps,
    worker_properties,
)
from bicentennial.systems.registry import REGISTRY, SystemRefused, admit_system, load
from bicentennial.world.db import open_world
from bicentennial.world.targeted import MicroSpec, micro_schedule

REPO = Path(__file__).resolve().parents[3]
STEP_S, REFERENCE_BOUND_S = 60, 5
REFERENCE_SYSTEMS = {"reference_store": ReferenceStore, "bm25": BM25,
                     **{name: getattr(mutants, name) for name in (
                         "wipe_on_restart", "truncate_after_compaction", "orphan_tool_result",
                         "forget_ignored", "stale_wins", "forget_cached_output", "reset_cached_output")}}
ROUTE_TABLE = {"routes": [dict(system=name, segment="seg0", probe_model="probe-model",
                              summariser="summary-model", alias="bicentennial-main", vision=None,
                              served_by="scripted") for name in ("hermes-native", *sorted(PROVIDERS))]}
REFUSALS = (PinnedArtifactChanged, LockMismatch, ControlsTampered, GateRefused,
            PinMismatch, SystemRefused)
SYSTEM_CAUSES = frozenset(("ingest_failed", "query_failed", "tool_failed", "drain_failed",
                           "forget_unsettled", "turn_timeout", "session_end_failed"))
ADAPTER_PROBES = {
    "INV-VERB": ("verb-1", "verb-2", "verb-3"),
    "INV-NEW": ("new-a", "new-b"),
    "INV-PAIR": ("pair-call", "pair-result"),
    "INV-FORGET": ("forget-1", "forget-2", "forget-store"),
}


class T0Refused(RuntimeError):
    def __init__(self, code, fields=(), detail=()):
        self.code, self.fields = code, tuple(sorted(fields))
        self.detail = tuple(sorted(detail))
        super().__init__(code)


def _json(path):
    return json.loads(Path(path).read_bytes())


def _commit():
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True, env=git_env()).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise T0Refused("benchmark_commit") from None


class _Pack:
    def __init__(self, root, rel):
        self.root, self.rel = root / rel, rel
        self.manifest = _json(self.root / "manifest.json")
        self.pack = _json(self.root / "sealed/pack.json")
        self.meta = _json(self.root / "sealed/meta.json")
        self.records = {r["item_id"]: r for r in _json(self.root / "sealed/records.json")}
        self.keys = {r["item_id"]: r for r in map(json.loads,
                     (self.root / "sealed/reader_keys.jsonl").read_bytes().splitlines())}
        gen = self.meta["generator"]
        self.template = TEMPLATES_BY_GENRE[self.meta["genre"]][self.meta["row"]["template"]]
        self.schedule = micro_schedule(MicroSpec(**{k: v for k, v in gen["spec"].items()
                                                   if k != "template"}), self.template)
        self.events, self.forgets = {}, {}
        for b in ("B0", "B1"):
            life = self.root / "sealed/life"
            if (sha256(self.schedule.to_json()).hexdigest() !=
                    _json(life / f"history.{b}.json")["schedule_sha256"] or
                    self.schedule.fault_lite() != gen["fault_lite"]):
                raise T0Refused("schedule_mismatch")
            sessions = {s.session_id: s.index for s in self.schedule.sessions}
            stream = {r["event_id"]: sessions[r["session_id"]] for r in map(json.loads,
                      (life / f"stream.{b}.jsonl").read_bytes().splitlines())}
            self.events[b] = [(stream[e["event_id"]], event_copy(e))
                              for e in _json(self.root / f"visible/events.{b}.json")["events"]]
            with closing(open_world(life / f"world.{b}.db", readonly=True)) as db:
                tokens = db.execute("SELECT fact_id, value FROM locked_token").fetchall()
                self.forgets[b] = {r["event_id"]: tuple(unicodedata.normalize("NFC", t["value"])
                    for t in tokens if t["fact_id"] in json.loads(r["covered_fact_ids_json"]))
                    for r in db.execute("SELECT * FROM forget_request")}
        self.score = make_score(_json(self.root / "sealed/scoring.json"))


class _Guarded:
    def __init__(self, adapter):
        self.adapter = adapter

    def __getattr__(self, name):
        def call(*args, **kwargs):
            try:
                value = getattr(self.adapter, name)(*args, **kwargs)
                if name == "settle" and value is not True:
                    raise SystemFault()
                if name == "checkpoint" and type(value) is not bytes:
                    raise SystemFault()
                if name == "query":
                    try:
                        shape(value, {"output": str, "citations": list, "confidence_milli": int})
                    except (ValueError, TypeError):
                        raise SystemFault() from None
                    if (any(type(c) is not str for c in value["citations"]) or
                            not 0 <= value["confidence_milli"] <= 1000):
                        raise SystemFault()
                return value
            except (*REFUSALS, T0Refused, SystemFault):
                raise
            except HarnessFailed as error:
                if str(error) in SYSTEM_CAUSES:
                    raise SystemFault() from error
                raise
            except Exception as error:
                if isinstance(self.adapter, _OwnedHost):
                    raise
                raise SystemFault() from error
        return call


def _identity(item, result=None, stage=None):
    return {**{k: item[k] for k in ("item_id", "cell_id", "stage", "track")},
            "selected_option": result.selected_option if result else None,
            "competing_present": list(result.competing_present) if result else [],
            "carry_over": result.carry_over if result else False, "stage_attribution": stage}


def drive_branch(pack, branch, factory, *, bound_s, snapshot):
    """Drive one attempt, retaining completed probes when a system call fails."""
    results, outcomes, ingested, roots = {}, {}, [], ()
    items = sorted((i for i in pack.pack["items"] if pack.records[i["item_id"]]["branch"] == branch),
                   key=lambda i: i["item_id"])
    a, system_failed = None, False

    def crash():
        nonlocal a
        a.settle(bound_s)
        data = a.checkpoint()
        if hasattr(a.adapter, "close"):
            a.close()
        a = None
        a = _Guarded(factory())
        a.restore(data)

    try:
        a = _Guarded(factory())
        a.reset()
        for plan in pack.schedule.sessions:
            if plan.index > 1 and hasattr(a.adapter, "begin_session"):
                a.settle(bound_s)
                a.begin_session(plan.index)
            faults = [r for r in pack.schedule.fault_lite() if r["session"] == plan.index]
            for row in faults:
                if row["turn"] is None:
                    if row["kind"] == "restart":
                        crash()
                    elif row["kind"] == "compaction":
                        a.maintain()
            kills = [r["turn"] for r in faults if r["kind"] == "kill"]
            for session, event in pack.events[branch]:
                if session != plan.index:
                    continue
                while kills and bisect_right(plan.turn_t, event["t_sim"]) > kills[0]:
                    crash()
                    kills.pop(0)
                a.ingest(event)
                ingested.append(event)
                if event["event_id"] in pack.forgets[branch]:
                    needles = pack.forgets[branch][event["event_id"]]
                    a.forget({"event_ids": sorted(e["event_id"] for e in ingested if any(
                        t in unicodedata.normalize("NFC", e["text"]) for t in needles))})
            for _ in kills:
                crash()
            for item in items:
                if item["probe_point"] != plan.index:
                    continue
                a.settle(bound_s)
                if not roots:
                    roots = snapshot(a.adapter)
                iid = item["item_id"]
                view, key, now = reader_view(item), pack.keys[iid], pack.meta["now"][iid]
                blocks = a.probe(api_task(view, key), now) if hasattr(a.adapter, "probe") else ()
                result = read_api(a, view, key, now, injected=blocks)
                score = pack.score(item, result)
                stage = failing_stage(result, key, failed=score.score_milli != 1000, retained_roots=roots)
                results[iid], outcomes[iid] = result, outcome(_identity(item, result, stage), score)
    except SystemFault:
        system_failed = True
        outcomes.update((i["item_id"], outcome(_identity(i), None, cause="SYSTEM_FAILURE"))
                        for i in items if i["item_id"] not in outcomes)
    finally:
        if a is not None and hasattr(a.adapter, "close"):
            active = sys.exception()
            try:
                a.close()
            except (*REFUSALS, T0Refused):
                raise
            except Exception as error:
                if active is not None:
                    active.add_note(f"cleanup: {type(error).__name__}")
                elif not system_failed:
                    raise
    return results, outcomes, roots


def _lock(index, pack, entry, pack_hash, real):
    commit = _commit()
    module = ("mutants" if entry["name"] not in ("reference_store", "bm25") else entry["name"])
    artifacts = [entry["artifact"]] if real else [dict(name=entry["name"], version="r16a",
        sha256=code_sha256(("api/contract.py", f"api/adapters/{module}.py",
                           *(("api/adapters/reference_store.py",) if module != "reference_store" else ()))))]
    return build_lock(benchmark_commit=commit, director_commit=commit, analysis_commit=commit,
        generator_version=index["generator_version"], seeds=index["seeds_manifest"]["seeds"],
        rendered_history_set_hash=index["rendered_history_set_hash"], pack_hash=pack_hash,
        harness_artifacts=index["harness_artifacts"], system_artifacts=artifacts,
        environment_hash=pack.manifest["pins"]["environment_boundary_hash"],
        fault_lite_schedule_hash=sha256_canon(pack.meta["generator"]["fault_lite"]),
        tool_lists_hash=sha256_canon({k: entry.get(k) for k in ("write_tools", "read_tools", "recall")}),
        route_table_hash=route_table_hash(RouteTable.load(ROUTE_TABLE)),
        write_turn_package_hash=code_sha256(("director/scripted.py",)), account_pool=[])


def _check_c7(pack, path):
    frozen, cells = c7_entries(path), c7.cells(REPO)
    templates = {t.ref: t for t in TEMPLATES_BY_GENRE[pack.meta["genre"]].values()}
    refs = sorted({f"{r['template_id']}-v{r['template_version']}" for r in pack.records.values()})
    for ref in refs:
        if ref not in frozen:
            raise T0Refused("c7_missing")
        current = c7.entry(templates[ref], pack.meta["genre"].lower(), cells)["entry_sha256"]
        if current != frozen[ref]["entry_sha256"] or current != pack.manifest["pins"]["c7_entries"][ref]:
            raise T0Refused("c7_changed")


def _surface_bytes(adapter):
    return sum(p.stat().st_size for root, _ in adapter.surfaces() for p in sorted(root.rglob("*"))
               if stat.S_ISREG(p.lstat().st_mode))


class _Capture:
    """Retain refusals and fault causes through S05's conversion."""

    def __init__(self, host, refusals, infra, system):
        self.host, self.refusals, self.infra, self.system = host, refusals, infra, system

    def __getattr__(self, name):
        value = getattr(self.host, name)
        if not callable(value):
            return value

        def call(*args, **kwargs):
            try:
                return value(*args, **kwargs)
            except (*REFUSALS, T0Refused) as error:
                self.refusals.append(error)
                raise
            except HarnessFailed as error:
                if str(error) in SYSTEM_CAUSES:
                    self.system.append(error)
                else:
                    self.infra.append(error)
                raise
            except Exception as error:
                if isinstance(self, _OwnedHost):
                    self.infra.append(error)
                raise
        return call


class _OwnedHost(_Capture):
    """Own a successful construction; close the underlying host exactly once."""

    def __init__(self, host, refusals, infra, system):
        super().__init__(host, refusals, infra, system)
        self.closed = False
        self.initial_bytes, self.growth = 0, 0

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                super().__getattr__("close")()
            finally:
                self.growth = _surface_bytes(self) - self.initial_bytes


class _Factory:
    """A unit's host roots, ownership and refusal capture for S05's guard."""

    def __init__(self, pack, branch, unit, entry, lock, *, real, host_options=None):
        self.pack, self.branch, self.unit = pack, branch, Path(unit)
        self.entry, self.lock, self.real = entry, lock, real
        self.host_options, self.hosts, self.refusals = dict(host_options or {}), [], []
        self.infra = []
        self.system = []
        self.snapshots = 0
        self.unit.mkdir(parents=True)

    def __call__(self):
        try:
            if not self.real:
                return _Capture(REFERENCE_SYSTEMS[self.entry["name"]](), self.refusals,
                                self.infra, self.system)
            n = len(self.hosts)
            root = self.unit / f"h{n}"
            root.mkdir()
            options = dict(route_table=RouteTable.load(ROUTE_TABLE), responder=ScriptedResponder(self.entry),
                clock=SimClock(root / "clock.json", self.pack.schedule.sessions[0].t_start, STEP_S),
                root=root, scratch=self.unit, life=self.pack.meta["life"], branch=self.branch,
                run=mint_id(canon(["t0", lock_hash(self.lock), self.entry["name"],
                                  self.pack.pack["pack_id"]]).decode(), 0),
                lock_hash=lock_hash(self.lock), sim_epoch_s=0, **self.host_options)
            host = HermesMemoryHost(self.entry, **options)
            owned = _OwnedHost(host, self.refusals, self.infra, self.system)
            self.hosts.append(owned)
            owned.initial_bytes = _surface_bytes(host)
            target = host.paths["workspace"] / "pack"
            target.mkdir()
            source = _json(self.pack.root / "visible/answer_key.json")
            data = canon({k: v for k, v in source.items() if k != "canary"})
            if source["canary"].encode() in data:
                raise T0Refused("visible_canary")
            (target / "answer_key.json").write_bytes(data)
            return owned
        except (*REFUSALS, T0Refused) as error:
            self.refusals.append(error)
            raise
        except ValueError as error:
            if str(error) == "no T0 mapping":
                refusal = T0Refused("no T0 mapping")
                self.refusals.append(refusal)
                raise refusal from None
            self.infra.append(error)
            raise
        except Exception as error:
            self.infra.append(error)
            raise

    def snapshot(self, adapter):
        destination = self.unit / "snap" / str(self.snapshots)
        self.snapshots += 1
        destination.mkdir(parents=True)
        if self.real:
            roots = []
            for i, (surface, _) in enumerate(adapter.surfaces()):
                root = destination / str(i)
                clone_tree(surface, root)
                roots.append(root)
            return tuple(roots)
        (destination / "checkpoint.bin").write_bytes(_Guarded(adapter).checkpoint())
        return (destination,)

    def close(self):
        errors = []
        for host in self.hosts:
            try:
                host.close()
            except Exception as error:
                errors.append(error)
        if self.refusals:
            raise self.refusals[0]
        if errors:
            active = sys.exception()
            if active is None:
                raise errors[0]
            active.add_note(f"cleanup: {type(errors[0]).__name__}")

    def invariants(self, bound_s):
        verdicts = {}
        for invariant in INVARIANTS:
            for attempt in range(3):
                factory = _Factory(self.pack, self.branch, self.unit / invariant / f"a{attempt}",
                    self.entry, self.lock, real=self.real, host_options=self.host_options)
                try:
                    try:
                        verdict = adapter_invariant(factory, invariant, bound_s=bound_s,
                            snapshot=factory.snapshot if self.real else None)
                    finally:
                        infra_before_close = len(factory.infra)
                        system_failed = bool(factory.system)
                        try:
                            factory.close()
                        except (*REFUSALS, T0Refused):
                            raise
                        except Exception as error:
                            factory.infra.append(error)
                        if system_failed and not infra_before_close:
                            # Closing a dead worker must preserve its system failure.
                            del factory.infra[infra_before_close:]
                finally:
                    # Keep the closed hosts available for audit until the parent unit is removed.
                    self.hosts.extend(factory.hosts)
                    self.refusals.extend(factory.refusals)
                if not factory.infra and verdict.status != "INFRA_FAILURE":
                    break
                if attempt == 2:
                    ids = ADAPTER_PROBES[invariant]
                    verdict = Verdict(invariant, "INFRA_FAILURE", len(ids), 0, (), (), ids, ("infra",))
            verdicts[invariant] = verdict
        return verdicts


def _attempts(index, pack, branch, entry, pack_hash, real, work, worker, *, bound_s, host_options,
              expected_lock=None):
    gate = SessionGate(expected_lock if expected_lock is not None else
                       _lock(index, pack, entry, pack_hash, real))
    factories = []
    try:
        for attempt in range(3):
            current = _lock(index, pack, entry, pack_hash, real)
            gate.start_session(current, "system", pack.meta["life"], branch, 1, attempt)
            unit = Path(work) / f"worker-{worker}" / f"{pack.pack['pack_id']}-{branch}-a{attempt}"
            factory = _Factory(pack, branch, unit, entry, current,
                               real=real, host_options=host_options)
            factories.append(factory)
            try:
                try:
                    results, outcomes, roots = drive_branch(pack, branch, factory,
                        bound_s=bound_s, snapshot=factory.snapshot)
                finally:
                    factory.close()
                for row in outcomes.values():
                    row["infra_reruns"] = attempt
                return results, outcomes, roots, factories
            except (*REFUSALS, T0Refused):
                raise
            except Exception:
                if attempt == 2:
                    outcomes = {i["item_id"]: outcome(_identity(i), None, cause="INFRA_FAILURE",
                                infra_reruns=2) for i in pack.pack["items"]
                                if pack.records[i["item_id"]]["branch"] == branch}
                    return {}, outcomes, (), factories
        raise AssertionError("unreachable attempts")
    except BaseException:
        _remove_units(factories)
        raise


def _verb_member(pack, item):
    record, key = pack.records[item["item_id"]], pack.keys[item["item_id"]]
    return record["direction"] == VERBATIM and bool(set(record["crossed"]) & set(STRESSES)) and bool(key["required"])


def _pack_invariants(pack, results, outcomes, roots, baseline, adapter_verdicts, *,
                     baseline_infra=(), session_wakes=False):
    evidence = []
    intrinsic = pack.template.fault if hasattr(pack.template, "fault") else False
    for item in sorted(pack.pack["items"], key=lambda i: i["item_id"]):
        iid, record = item["item_id"], pack.records[item["item_id"]]
        earlier = record["evidence_session"]
        # Registry hosts restart their worker on existing state at every session start.
        crosses = earlier is not None and (session_wakes and earlier < item["probe_point"] or
            any(kind in ("restart", "kill") and earlier < session <= item["probe_point"]
                for kind, session, _ in pack.schedule.wakes()))
        evidence.append(ItemEvidence(item, record, pack.keys[iid], results.get(iid),
            outcomes[iid]["failure_class"], crosses, False if intrinsic else baseline.get(iid),
            roots[record["branch"]]))
    for _ in range(3):
        verdicts = run_invariants(evidence, tier="T0")
        # A known failure stands: a later attempt's scan fault must not mask it (RING0 E3).
        if not any("infra" in v.reasons and v.status != "FAIL" for v in verdicts.values()):
            break
    if baseline_infra:
        verb = verdicts["INV-VERB"]
        verdicts["INV-VERB"] = replace(verb,
            status="INFRA_FAILURE" if verb.status in ("PASS", "INCONCLUSIVE", "NOT_EXERCISED") else verb.status,
            infra=tuple(sorted(set(verb.infra) | set(baseline_infra))))
    if intrinsic:
        verdicts["INV-VERB"] = adapter_verdicts["INV-VERB"]
    return [verdicts[inv].to_obj() for inv in INVARIANTS]


def _remove_units(factories):
    for factory in factories:
        shutil.rmtree(factory.unit)


def _branches(index, pack, entry, pack_hash, real, work, workers, *, bound_s, host_options,
              expected_lock=None):
    """Retain both units through invariant evaluation; drain both futures on refusal."""
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=min(workers, 2)) as pool:
        futures = [pool.submit(_attempts, index, pack, branch, entry, pack_hash, real, work,
                   n % workers, bound_s=bound_s, host_options=host_options, expected_lock=expected_lock)
                   for n, branch in enumerate(("B0", "B1"))]
        for future in futures:
            try:
                rows.append(future.result())
            except BaseException as error:
                errors.append(error)
    if errors:
        _remove_units([f for row in rows for f in row[3]])
        raise errors[0]
    results = {i: result for row in rows for i, result in sorted(row[0].items())}
    outcomes = {i: result for row in rows for i, result in sorted(row[1].items())}
    return results, outcomes, {b: row[2] for b, row in zip(("B0", "B1"), rows, strict=True)}, [
        f for row in rows for f in row[3]]


def _baseline_members(pack, baseline):
    fields = ("branch", "template_id", "template_version", "instance_key")
    by_identity = {tuple(r[k] for k in fields): i for i, r in baseline.records.items()}
    members = {}
    for item in sorted(pack.pack["items"], key=lambda i: i["item_id"]):
        if _verb_member(pack, item):
            identity = tuple(pack.records[item["item_id"]][k] for k in fields)
            if identity not in by_identity:
                raise T0Refused("baseline_missing")
            members[item["item_id"]] = by_identity[identity]
    return members


def _baseline_context(pack, baseline, results):
    return {i: results[twin].in_context is True if results.get(twin) else False
            for i, twin in _baseline_members(pack, baseline).items()}


def _preflight(*, system, packs, selected, pack_hash, workers=1, mode="api", hermes=None,
               plugin_source=None, entry=None, host_overrides=None, model_cache=None):
    """Resolve all selected and baseline packs before constructing any adapter."""
    if mode != "api":
        raise T0Refused("mode_unavailable:" + mode)
    if Path(system).name != system or "\\" in system:
        raise T0Refused("unknown_system")
    registry = REGISTRY / f"{system}.toml"
    real = registry.is_file()
    if real == (system in REFERENCE_SYSTEMS):
        raise T0Refused("unknown_system")
    if real:
        entry = load(registry) if entry is None else entry
        if entry["name"] != system:
            raise T0Refused("unknown_system")
        admit_system(entry)
        if entry["harness"] != "hermes":
            raise T0Refused("harness_not_hermes")
    else:
        entry = dict(name=system, surfaces=[])
    validate_maps()
    if system in ENGINES and system not in PROVIDERS:
        raise T0Refused("no_t0_surface:context_engine")
    from bicentennial.harness.hermes.plugin_host import SETTLE_THREADS
    if real and entry["settle"]["kind"] == "hook" and system not in SETTLE_THREADS:
        raise T0Refused("settle_unmapped")
    marker = read_marker()
    admission = admit(marker, heavy=entry.get("machine_class") == "heavy", roots=workers)
    if not admission.admitted:
        raise T0Refused(admission.reason)
    index = verify(packs, pack_hash=pack_hash)
    if index["tier"] != "T0":
        raise T0Refused("tier")
    paths = sorted(index["packs"])
    by_id = {index["packs"][rel]["pack_id"]: rel for rel in paths}
    if any(p != "all" and p not in by_id and p not in index["packs"] for p in selected):
        raise T0Refused("unknown_pack")
    wanted = paths if "all" in selected else sorted({by_id.get(p, p) for p in selected})
    if not wanted or any(p not in index["packs"] for p in wanted):
        raise T0Refused("unknown_pack")
    all_packs = {rel: _Pack(Path(packs), rel) for rel in paths}
    by_row = {p.meta["row"]["id"]: p for p in all_packs.values()}
    options = {}
    model_cache, model_cache_sha256 = prepare_cache(system, model_cache, T0Refused)
    if real:
        harness_pin = load(REGISTRY / "hermes-native.toml")["artifact"]
        options = dict(checkout=hermes, plugin_source=plugin_source, harness_pin=harness_pin)
        options.update(host_overrides or {})
        if options["checkout"] is None or is_plugin(system) and plugin_source is None:
            raise T0Refused("missing_input")
        options.update(extra_env=resolve_worker_env(system, model_cache),
                       model_cache=model_cache, model_cache_sha256=model_cache_sha256)
        if index["harness_artifacts"] != [harness_pin]:
            raise T0Refused("harness_artifact_mismatch")
        options["run_properties"] = worker_properties(system, options["checkout"], REPO, "t0", T0Refused,
                                                       options.get("worker_argv"))
    for rel in wanted:
        pack = all_packs[rel]
        needed = [pack]
        if any(_verb_member(pack, item) for item in pack.pack["items"]):
            baseline = pack.meta["row"].get("baseline")
            intrinsic = getattr(pack.template, "fault", False)
            if not intrinsic and (baseline is None or baseline not in by_row):
                raise T0Refused("baseline_missing")
            if not intrinsic:
                needed.append(by_row[baseline])
        if real:
            for member in needed:
                _check_c7(member, REPO / "specs/ring0/c7-partial.json")
    bound_s = entry["settle"]["bound_s"] if real else REFERENCE_BOUND_S
    return index, [all_packs[rel] for rel in wanted], by_row, entry, marker, admission, options, bound_s


def _pins(lock, pack):
    pins = {k: lock[k] for k in ("benchmark_commit", "director_commit", "pack_hash",
            "route_table_hash", "write_turn_package_hash")}
    pins.update(scorer_commit=lock["analysis_commit"], generator_commit=lock["benchmark_commit"],
                harness_hash=sha256_canon(lock["harness_artifacts"]),
                system_hash=sha256_canon(lock["system_artifacts"]))
    return pins | {k: pack.manifest["pins"][k] for k in (
        "seed_hash", "environment_boundary_hash", "repository_boundary_hash")}


def _controls(pack, index, cache):
    inp, pin = control_input(pack.root), sha256_canon(index["harness_artifacts"])
    entry = read_entry(pack.root / "sealed/controls.json", cache_key(inp, harness_pin=pin),
                       expected_sha256=pack.pack["hashes"]["controls"])
    if entry is None:
        cache.mkdir(parents=True, exist_ok=True)
        entry = ensure(inp, cache / f"{pack.pack['pack_id']}.controls.json",
                       score=pack.score, harness_pin=pin)
    return entry


def _isolation_detail(records, egress):
    detail = list(egress.get("non_loopback_seen", []))
    for index, record in enumerate(records):
        ident = record.get("req", index)
        if record.get("served_by") not in (None, "scripted"):
            detail.append(f"record id={ident} served_by={record['served_by']}")
        for attempt in record.get("upstream", ()):
            if ((attempt.get("served_by") != "scripted" and "error" not in attempt)
                    or attempt.get("diagnostics")):
                suffix = " diagnostics" if attempt.get("diagnostics") else ""
                detail.append(f"record id={ident} served_by={attempt.get('served_by')}{suffix}")
    return tuple(sorted(detail))


def _unobserved_detail(egress):
    if egress.get("alive_at_stop", True) and not egress.get("unsampled"):
        return ()
    return tuple(sorted([f"egress sampler alive_at_stop={str(egress.get('alive_at_stop', True)).lower()}",
        *(f"egress failed_samples type={k} count={v}" for k, v in egress.get("failed_samples", {}).items()),
        *egress.get("unsampled", ())]))


def _check_egress(evidence, T0Refused=T0Refused):
    """Check all available isolation evidence before refusing incomplete observation."""
    for rows, egress in evidence:
        if egress.get("non_loopback", []) or _isolation_detail(rows, {}):
            raise T0Refused("upstream_record", detail=_isolation_detail(rows, egress))
    for rows, egress in evidence:
        if detail := _unobserved_detail(egress):
            raise T0Refused("egress_unobserved", detail=detail)


def _audit(factories, evidence=None):
    """Read closed hosts while their ledgers and response blobs still exist."""
    records, texts, tokens, runtime, markers, pids, ports, paths = [], [], {}, {}, [], [], [], []
    hosts = [h for f in factories for h in f.hosts]
    if evidence is None:
        evidence = {id(h): (h.records(), h.egress.summary()) for h in hosts}
    _check_egress(list(evidence.values()))
    failed_samples = {}
    for host in hosts:
        rows, egress = evidence[id(host)]
        for name, count in egress.get("failed_samples", {}).items():
            failed_samples[name] = failed_samples.get(name, 0) + count
        records.extend(rows)
        store = BlobStore(host.paths["root"] / "ledger/blobs", Guard([]))
        for row in rows:
            if row.get("type") != "request":
                continue
            texts.append(store.get(row["req"]).decode())
            response = json.loads(store.get(row["resp"]))
            usage = response.get("usage") or {}
            for frame in response.get("sse", ()):
                usage = frame.get("usage") or frame.get("response", {}).get("usage") or usage
            role = row["role"]
            before = tokens.get(role, (0, 0))
            tokens[role] = (before[0] + usage.get("input_tokens", usage.get("prompt_tokens", 0)),
                            before[1] + usage.get("output_tokens", usage.get("completion_tokens", 0)))
            runtime[role] = runtime.get(role, 0) + row["t_ms"]
        markers.extend(r["exit"] != 0 for r in host.gate)
        pids.extend(host.pids)
        ports.append(host.server.port)
        paths.extend(str(p) for p in host.paths.values())
    return dict(records=records, texts=texts, tokens=tokens, runtime=runtime, markers=markers,
                failed_samples=failed_samples,
                pids=pids, ports=ports, paths=paths, growth=sum(h.growth for h in hosts),
                run_values=dict(hosts[0].director.run_values) if hosts else None)


def _report_pack(pack, entry, lock, outcomes, verdicts, adapter, controls, audit, out, marker, start, properties=()):
    items = [outcomes[i] for i in sorted(outcomes)]
    bundles = [make_bundle({**{k: b[k] for k in ("bundle_id", "cell_id", "twin_type")},
                           "life": pack.pack["lives"][0]}, *(outcomes[i] for i in b["items"]))
               for b in sorted(pack.pack["bundles"], key=lambda b: b["bundle_id"])]
    all_verdicts = [*adapter, *verdicts]
    status = "BLOCKED" if (any(i["failure_class"] == "BLOCKED" for i in items) or
        any(v["status"] == "INFRA_FAILURE" or v["infra"] for v in all_verdicts)) else "COMPLETE"
    hit_count = hits(pack.meta["honeypot_token"], audit["texts"])
    known_failure = (
        any(v["status"] == "FAIL" for v in all_verdicts) or
        any(i["failure_class"] == "SYSTEM_FAILURE" for i in items))
    gate = ("INVALID" if hit_count else "FAIL" if known_failure else
            "BLOCKED" if status == "BLOCKED" else "PASS")
    kwargs = dict(singleton_lives=pack.meta["singleton_lives"],
                  duty_items=frozenset(pack.meta["duty_items"]))
    provisional = assemble(tier="T0", mode="api", system_entry=entry, run_status=status,
        pins=_pins(lock, pack), ledger_records=audit["records"], run_values=audit["run_values"] or
        dict(sandbox_root=str(out), director_port="0"), items=items, bundles=bundles,
        controls=card_controls(controls) | {"wiped_store": "not run at T0"}, voids=None, **kwargs)
    card = finalize(provisional, gate)
    extra = [("t0.entrypoint", "reference adapter" if entry["name"] in REFERENCE_SYSTEMS else ENTRYPOINT),
        ("t0.event_mapping", "every event becomes one user-side turn with an empty assistant side"),
        ("t0.crash", "API-mode crash equals restart"), ("honeypot.hits", hit_count),
        ("invariants.forget_inconclusive", sum(len(v["inconclusive"]) for v in all_verdicts
                                              if v["invariant"] == "INV-FORGET")),
        ("t0.pair", "API-mode INV-PAIR certifies call and result survival; linkage requires Hermes mode"),
        *stub_disclosures(entry, "t0")]
    if entry["name"] in ENGINES:
        extra.append(("t0.engine", "context engine not loaded at T0 (memory-layer host)"))
    if audit.get("model_cache_sha256") is not None:
        extra.append(("t0.model_cache", "sha256:" + audit["model_cache_sha256"]))
    extra.extend(properties)
    if entry["name"] == "hermes-native":
        extra.append(("t0.injection", "The session-start memory snapshot is read; other harness prompt injection "
                      "is not exercised."))
    if getattr(pack.template, "fault", False):
        extra.append(("t0.baseline", "no fault-free twin at v0.1"))
    suites = [item_suite(json.loads(card), "system", run_properties(reduce(items, bundles,
        **kwargs), extra)), (f"ring0.T0.{entry['name']}.invariants.pack", [],
        junit_cases_from_invariants(verdicts)), (f"ring0.T0.{entry['name']}.invariants.adapter", [],
        junit_cases_from_invariants(adapter))]
    junit = junit_xml(suites)
    receipt_records = audit.get("receipt_records", audit["records"])
    receipt = build_receipt(run_status=status, wall_start_ms=start, wall_end_ms=time.time_ns() // 1_000_000,
        latency_ms=ledger_latencies(receipt_records), load_milli=load_milli(os.getloadavg()),
        busy_marker_readings=[busy(marker), *audit["markers"]], tokens_by_role=audit["tokens"],
        runtime_by_role=audit["runtime"], spend_micro_usd=0, store_growth_bytes=audit["growth"],
        process_ids=audit["pids"], ports=audit["ports"], temporary_paths=audit["paths"],
        egress_failed_samples=audit["failed_samples"],
        raw_body_digest=raw_body_digest(receipt_records))
    return dict(card=card, receipt=receipt, junit=junit, suites=suites, invariants=canon(verdicts),
                controls=canon(controls), code=1 if gate in ("INVALID", "FAIL") else
                2 if gate == "BLOCKED" else 0)


def _relations(index, selected, outcomes, name):
    path = REPO / "packs/catalogue-v0.toml"
    if sha256(path.read_bytes()).hexdigest() != index["catalogue"]["sha256"]:
        raise T0Refused("catalogue_changed")
    catalogue = load_catalogue(path, c7_path=REPO / "specs/ring0/c7-partial.json",
                               tier_path=REPO / "tiers/life_specs/t0.toml")
    rows = catalogue.by_id()
    held = {p.meta["row"]["id"]: p for p in selected}
    included = {r for r in sorted(held) if rows[r].test == "MFT" or rows[r].base in held}
    branches = {r: {p.records[i]["branch"]: result for i, result in sorted(outcomes[r].items())}
                for r in sorted(included) for p in [held[r]]}
    report = relations.check([rows[r] for r in sorted(included)], branches)
    cases = []
    for r in report.relations:
        result = "passed" if r.status == "holds" else "failure" if r.status == "flagged" else "skipped"
        message = canon(r.lever_delta).decode() if r.status == "confounded" else r.status
        cases.append(Case(r.row, "ring0.relations", result,
                          None if result == "passed" else r.status,
                          None if result == "passed" else message))
    return canon(report.to_obj()), junit_xml([(f"ring0.T0.{name}.relations", [], cases)])


def _remove_output(path):
    """Best-effort rollback: one failed removal must not skip the other entries."""
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    except Exception:
        pass


class _Publication:
    def __init__(self, out):
        self.out, self.staging, self.moved, self.created = out, out / "staging", [], False

    def begin(self):
        self.staging.mkdir()
        # Only a staging directory this run created is ours to remove (a --cache may sit there).
        self.created = True
        return self.staging

    def publish(self, entries):
        for name in entries:
            target = self.out / name
            # Track before rename so an interrupt immediately after it is covered too.
            self.moved.append(target)
            os.replace(self.staging / name, target)
        self.staging.rmdir()

    def cleanup(self):
        for path in reversed(self.moved):
            try:
                # A failed rename leaves its source in place; its destination may be a cache.
                if (self.staging / path.name).exists():
                    continue
            except Exception:
                continue
            _remove_output(path)
        if self.created:
            _remove_output(self.staging)


def _execute(prepared, *, packs_dir, pack_hash, out, cache, workers, publication):
    index, selected, by_row, entry, marker, admission, options, bound_s = prepared
    options = dict(options)
    model_cache = options.pop("model_cache", None)
    model_cache_sha256 = options.pop("model_cache_sha256", None)
    properties = options.pop("run_properties", ())
    (pack_root,) = {Path(p.rel).parts[0] for p in selected}
    run_start = time.time_ns() // 1_000_000
    real, work = bool(options), out / "work"
    count = min(workers, admission.max_roots, 2)
    locks = {p.rel: _lock(index, p, entry, pack_hash, real) for p in selected}
    first = selected[0]
    invariant_factory = _Factory(first, "B0", work / "adapter", entry, locks[first.rel],
                                 real=real, host_options=options)
    reports, outcomes_by_row, delivery = {}, {}, WriteDelivery()
    try:
        adapter_verdicts = invariant_factory.invariants(bound_s)
        adapter = [adapter_verdicts[i].to_obj() for i in INVARIANTS]
        invariant_audit = _audit([invariant_factory])
        delivery.add(invariant_factory.hosts)
        for pack in selected:
            start = run_start if pack is first else time.time_ns() // 1_000_000
            factories = []
            try:
                results, outcomes, roots, made = _branches(index, pack, entry, pack_hash, real,
                    work / pack.pack["pack_id"] / "main", count, bound_s=bound_s, host_options=options,
                    expected_lock=locks[pack.rel])
                factories.extend(made)
                baseline = {}
                baseline_infra = []
                if (not getattr(pack.template, "fault", False) and
                        any(_verb_member(pack, i) for i in pack.pack["items"])):
                    twin = by_row[pack.meta["row"]["baseline"]]
                    base_results, base_outcomes, _, baseline_factories = _branches(index, twin, entry, pack_hash,
                        real, work / pack.pack["pack_id"] / "baseline", count,
                        bound_s=bound_s, host_options=options,
                        expected_lock=_lock(index, twin, entry, pack_hash, real))
                    factories.extend(baseline_factories)
                    baseline = _baseline_context(pack, twin, base_results)
                    baseline_infra = [i for i, twin_id in _baseline_members(pack, twin).items()
                                      if base_outcomes[twin_id]["failure_class"] == "BLOCKED"]
                verdicts = _pack_invariants(pack, results, outcomes, roots, baseline, adapter_verdicts,
                                           baseline_infra=baseline_infra, session_wakes=real)
                evidence = {id(h): (h.records(), h.egress.summary()) for f in factories for h in f.hosts}
                _check_egress(list(evidence.values()))
                audit = _audit(made, evidence)
                # Audit every auxiliary host too; only the selected drive enters its card digest.
                auxiliary = _audit([f for f in factories if f not in made], evidence)
                audit["texts"] += auxiliary["texts"] + invariant_audit["texts"]
                audit["receipt_records"] = list(audit["records"])
                for extra in [auxiliary, *([invariant_audit] if pack is first else [])]:
                    audit["receipt_records"].extend(extra["records"])
                    for field in ("markers", "pids", "ports", "paths"):
                        audit[field].extend(extra[field])
                    audit["growth"] += extra["growth"]
                    for name, count in extra["failed_samples"].items():
                        audit["failed_samples"][name] = audit["failed_samples"].get(name, 0) + count
                    for role, values in sorted(extra["tokens"].items()):
                        before = audit["tokens"].get(role, (0, 0))
                        audit["tokens"][role] = tuple(a + b for a, b in zip(before, values, strict=True))
                    for role, ms in sorted(extra["runtime"].items()):
                        audit["runtime"][role] = audit["runtime"].get(role, 0) + ms
                audit["model_cache_sha256"] = model_cache_sha256
                delivery.add(h for f in factories for h in f.hosts)
                controls = _controls(pack, index, cache)
                reports[pack.rel] = _report_pack(pack, entry, locks[pack.rel], outcomes,
                    verdicts, adapter, controls, audit, out, marker, start, properties=properties)
                outcomes_by_row[pack.meta["row"]["id"]] = outcomes
            finally:
                _remove_units(factories)
        if real:
            for report in reports.values():
                report["suites"][0][1].extend(delivery.properties("t0"))
                report["junit"] = junit_xml(report["suites"])
        relation_json, relation_xml = _relations(index, selected, outcomes_by_row, entry["name"])
        for report in reports.values():
            if report["receipt"]["spend_micro_usd"] > 0:
                raise SpendRefused(report["receipt"]["spend_micro_usd"])
        for pack in selected:
            verify(packs_dir, pack_hash=pack_hash, lock=locks[pack.rel], expected_lock=locks[pack.rel])
        if model_cache is not None and cache_digest(model_cache, T0Refused) != model_cache_sha256:
            raise T0Refused("model_cache_changed")
        staging = publication.begin()
        for rel, report in sorted(reports.items()):
            directory = staging / rel
            directory.mkdir(parents=True)
            for filename in ("invariants", "controls"):
                (directory / f"{filename}.json").write_bytes(report[filename])
            write_run(directory, **{k: report[k] for k in ("card", "receipt", "junit")})
        (staging / "adapter_invariants.json").write_bytes(canon(adapter))
        (staging / "relations.json").write_bytes(relation_json)
        (staging / "relations.xml").write_bytes(relation_xml)
        publication.publish(("adapter_invariants.json", "relations.json", "relations.xml", pack_root))
        codes = {report["code"] for report in reports.values()}
        return 1 if 1 in codes else 2 if 2 in codes else 0
    finally:
        try:
            invariant_factory.close()
        finally:
            _remove_units([invariant_factory])
            if work.exists():
                shutil.rmtree(work)


def run_t0(*, system, packs, packs_dir, pack_hash, out, mode="api", workers=1,
           hermes=None, plugin_source=None, model_cache=None, cache=None, entry=None, host_overrides=None):
    """Run verified offline packs, returning Ring 0's 0/1/2/3/70 exit code."""
    created, published, publication = False, False, None
    try:
        out = Path(out)
        try:
            if os.environ.get("PYTHONHASHSEED") != "0":
                raise T0Refused("hashseed")
            if out.exists() or out.is_symlink():
                raise T0Refused("out_exists")
            prepared = _preflight(system=system, packs=packs_dir, selected=packs, pack_hash=pack_hash,
                workers=workers, mode=mode, hermes=hermes, plugin_source=plugin_source,
                entry=entry, host_overrides=host_overrides, model_cache=model_cache)
            out.mkdir(parents=True)
            created = True
            publication = _Publication(out)
            code = _execute(prepared, packs_dir=packs_dir, pack_hash=pack_hash, out=out,
                            cache=Path(cache) if cache is not None else out / "cache", workers=workers,
                            publication=publication)
            published = True
            return code
        except (*REFUSALS, T0Refused, SpendRefused) as error:
            reasons = getattr(error, "reasons", ())
            code = getattr(error, "code", None) or (",".join(sorted(reasons)) if reasons else
                "SpendRefused" if isinstance(error, SpendRefused) else
                "gate_refused" if isinstance(error, GateRefused) else "pin_mismatch")
            fields = tuple(sorted(getattr(error, "fields", ())))
            if created:
                refusal = dict(code=code, fields=list(fields))
                if getattr(error, "detail", ()):
                    refusal["detail"] = list(error.detail)
                (out / "refusal.json").write_bytes(canon(refusal))
            print(code, file=sys.stderr)
            return 3
    except Exception:
        print("tool_failure", file=sys.stderr)
        traceback.print_exc()
        if created:
            _remove_output(out / "refusal.json")
        return 70
    finally:
        if publication is not None and not published:
            publication.cleanup()
