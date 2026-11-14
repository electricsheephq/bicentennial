"""Offline T1 preparation, three-arm execution and in-memory scoring."""

import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.controls.cache import ControlsTampered, code_sha256
from bicentennial.director.compiler.check import Voids, check_compile
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.gitenv import git_env
from bicentennial.harness.hermes.adapter import PinMismatch, turn_wait_seconds
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items import c7
from bicentennial.items.editions import BY_REF, C7_FILES, EDITIONS
from bicentennial.items.protocol import CANARY
from bicentennial.keyed import mint_id
from bicentennial.packs.catalogue import c7_entries
from bicentennial.packs.install import verify
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.packs.scoring import case_from_obj
from bicentennial.runner.guard import admit, read_marker
from bicentennial.runner.hermes_score import MISSING, Infra, identity0, score_item
from bicentennial.runner.life import SEGMENTS, STEP_S, LifeRun, run_life
from bicentennial.runner.lock import LockMismatch, SessionGate, build_lock, lock_hash
from bicentennial.runner.units import T1_SPEC
from bicentennial.sandbox.fixedroot import remove_tree
from bicentennial.score.bundle import make_bundle
from bicentennial.score.classes import outcome
from bicentennial.score.invariants import INVARIANTS, ItemEvidence, run_invariants
from bicentennial.systems import pins as install_pins
from bicentennial.systems.hermes_plugin import (
    is_plugin,
    prepare_cache,
    resolve_worker_env,
    validate_maps,
    verify_install_pin,
    worker_properties,
)
from bicentennial.systems.mapping import check_mapping, resolve_mapping
from bicentennial.systems.recipe import recipe, system_artifacts
from bicentennial.systems.registry import REGISTRY, SystemRefused, admit_system, load
from bicentennial.world.db import open_world
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.targeted import crosses_cold_restart, expected_state

UNIT_ORDER = ("no_memory", "system", "wiped")
GATED_ARMS = ("system", "wiped")
RELABEL = ("end_timeout", "final_mismatch", "resume_failed", "turn_timeout")
REPO = Path(__file__).resolve().parents[3]
TEMPLATE_ADMISSIONS = REPO / "specs/ring0/template-admissions.json"
CONTROL_ONLY_PACKS = REPO / "specs/ring0/control-only-packs.json"


class T1Refused(RuntimeError):
    def __init__(self, code, fields=(), detail=()):
        self.code, self.fields = code, tuple(sorted(fields))
        self.detail = tuple(sorted(detail))
        super().__init__(code)


def validate_turn_wait(value):
    try:
        return turn_wait_seconds(value)
    except ValueError:
        raise T1Refused("usage") from None


REFUSALS = (T1Refused, SystemRefused, PinnedArtifactChanged, LockMismatch,
            ControlsTampered, GateRefused, PinMismatch)


@dataclass(frozen=True)
class _Pack:
    rel: str
    dir: Path
    pack: dict
    meta: dict
    manifest: dict
    records: dict
    keys: dict
    scoring: dict
    cases: dict
    life_dir: Path
    life: str
    genre: str
    schedule: object
    items: dict
    records_b: dict
    visible: dict


@dataclass(frozen=True)
class T1Context:
    entry: dict
    harness_pin: dict
    index: dict
    pack_hash: str
    packs: tuple[_Pack, ...]
    lock: dict
    pins: dict
    gate: SessionGate
    current_lock: object
    run_id: str
    roots: int
    marker: object
    hermes: object
    plugin_source: object
    worker_argv: object
    table: dict
    model_cache: object = None
    model_cache_sha256: str | None = None
    worker_properties: tuple = ()
    turn_wait_s: float = 1.0


@dataclass(frozen=True)
class UnitResult:
    life: str
    branch: str
    arm: str
    runs: tuple[LifeRun, ...]
    reclassified: tuple
    stop_reclassified: bool = False


@dataclass(frozen=True)
class ArmResult:
    arm: str
    outcomes: dict
    labels: dict
    bundles: tuple
    verdicts: tuple | None
    voids: dict | None
    units: tuple[UnitResult, ...]
    recall: tuple
    transforms: tuple
    honeypot_hits: int


@dataclass(frozen=True)
class T1Run:
    ctx: T1Context
    arms: dict
    crossing: tuple
    singleton_lives: dict
    duty_items: tuple
    not_exercised: tuple


def _json(path):
    return json.loads(path.read_bytes())


def _check_control_only(pack_hash):
    try:
        record = _json(CONTROL_ONLY_PACKS)
        listed = record["control_only"]
    except (OSError, ValueError, KeyError, TypeError):
        raise T1Refused("control_only_pack") from None
    if not isinstance(listed, dict) or any(
        len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
        or not isinstance(entry, dict)
        or any(not isinstance(entry.get(field), str) or not entry[field].strip()
               for field in ("round", "declaration", "result"))
        for digest, entry in listed.items()
    ):
        raise T1Refused("control_only_pack")
    if pack_hash in listed:
        raise T1Refused("control_only_pack")


def _routes(name):
    return {"routes": [dict(sorted(dict(system=name, segment=s, probe_model="probe-model",
        summariser="summary-model", alias=a, vision=None, served_by="scripted").items()))
        for s, a in SEGMENTS]}


def _pack(root, rel):
    directory = root / rel
    pack, meta, manifest, scoring = (_json(directory / p) for p in
        ("sealed/pack.json", "sealed/meta.json", "manifest.json", "sealed/scoring.json"))
    records = {r["item_id"]: r for r in _json(directory / "sealed/records.json")}
    keys = {r["item_id"]: r for r in (json.loads(line) for line in
        (directory / "sealed/reader_keys.jsonl").read_bytes().splitlines())}
    life_dir = directory / "sealed/life"
    life = _json(life_dir / "life.json")
    schedule = build_schedule(life["seed"], life["life"], named(life["scale"]))
    items, records_b = {}, {}
    packed_ids = {i["item_id"] for i in pack["items"]}
    for b in ("B0", "B1"):
        if hashlib.sha256(schedule.to_json()).hexdigest() != _json(life_dir / f"history.{b}.json")["schedule_sha256"]:
            raise T1Refused("schedule_mismatch")
        items[b] = _json(life_dir / f"items.{b}.json")
        if any(i["item_id"] not in packed_ids for i in items[b]):
            raise ValueError("branch item outside pack")
        records_b[b] = tuple(records[iid] for iid in sorted(i["item_id"] for i in items[b]))
    answer = _json(directory / "visible/answer_key.json")
    answer.pop("canary")
    visible = {"answer_key.json": canon(answer)}
    assert CANARY.encode() not in visible["answer_key.json"]
    return _Pack(rel, directory, pack, meta, manifest, dict(sorted(records.items())),
        dict(sorted(keys.items())), scoring,
        {c["item"]["item_id"]: case_from_obj(c) for c in scoring["cases"]},
        life_dir, meta["life"], meta["genre"], schedule, items, records_b, visible)


def _boundaries(packs):
    values = {field: {} for field in ("env_state_hash", "repo_tree_hash")}
    for pack in packs:
        branches = {}
        for b in ("B0", "B1"):
            db = open_world(pack.life_dir / f"world.{b}.db", readonly=True)
            try:
                branches[b] = expected_state(pack.genre, pack.schedule)(db)
            finally:
                db.close()
        for field in sorted(values):
            values[field][pack.life] = {b: {str(k): branches[b][k][field]
                for k in sorted(branches[b], key=lambda k: str(k))} for b in ("B0", "B1")}
    return dict(sorted((name, sha256_canon(values[field])) for name, field in
        (("environment_boundary_hash", "env_state_hash"), ("repository_boundary_hash", "repo_tree_hash"))))


def _commit():
    try:
        value = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True, env=git_env()).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        raise T1Refused("benchmark_commit") from None
    if len(value) != 40 or any(c not in "0123456789abcdef" for c in value):
        raise T1Refused("benchmark_commit")
    return value


def _lock(index, packs, entry, table, pack_hash):
    commit, boundary = _commit(), _boundaries(packs)
    return dict(sorted(build_lock(benchmark_commit=commit, director_commit=commit,
        analysis_commit=commit, generator_version=index["generator_version"],
        seeds=index["seeds_manifest"]["seeds"],
        rendered_history_set_hash=index["rendered_history_set_hash"],
        harness_artifacts=index["harness_artifacts"], system_artifacts=system_artifacts(entry),
        environment_hash=boundary["environment_boundary_hash"],
        route_table_hash=route_table_hash(RouteTable.load(table)),
        write_turn_package_hash=code_sha256(("director/scripted.py",)),
        fault_lite_schedule_hash=sha256_canon({p.life: p.schedule.fault_lite()
            for p in sorted(packs, key=lambda p: p.life)}), pack_hash=pack_hash,
        tool_lists_hash=sha256_canon({k: entry.get(k) for k in ("read_tools", "recall", "write_tools")}),
        account_pool=[]).items()))


def prepare(*, system, packs, pack_hash, hermes=None, plugin_source=None, entry=None,
            worker_argv=None, model_cache=None, turn_wait_s=1.0, spec=T1_SPEC, control=False) -> T1Context:
    """Refuse invalid inputs and pin both lives before constructing any adapter."""
    turn_wait_s = validate_turn_wait(turn_wait_s)
    if entry is None:
        try:
            entry = load(REGISTRY / f"{system}.toml")
            if "recipe" in entry:
                raise T1Refused("recipe_in_builtin")
        except FileNotFoundError:
            raise T1Refused("unknown_system") from None
    if entry["name"] != system:
        raise T1Refused("unknown_system")
    entry = json.loads(canon(entry))
    admit_system(entry, hermes=hermes)
    if entry["harness"] != "hermes":
        raise T1Refused("harness_not_hermes")
    engine_only = recipe(entry).engine is not None and recipe(entry).provider is None
    reason = check_mapping(entry, resolve_mapping(entry), require_forget=not engine_only)
    if reason is not None:
        raise T1Refused(reason)
    harness_pin = dict(sorted(load(REGISTRY / "hermes-native.toml")["artifact"].items()))
    if (hermes is None and worker_argv is None) or (is_plugin(entry) and plugin_source is None):
        raise T1Refused("missing_input")
    early_admission = None
    if spec.min_roots > 1:
        marker = read_marker()
        early_admission = admit(marker, heavy=entry.get("machine_class") == "heavy", roots=spec.roots)
        if not early_admission.admitted:
            raise T1Refused(early_admission.reason)
        if early_admission.max_roots < spec.min_roots:
            raise T1Refused("roots_below_min")
    validate_maps()
    model_cache, model_cache_sha256 = prepare_cache(entry, model_cache, T1Refused)
    if entry["settle"]["kind"] == "hook" and recipe(entry).settle_threads is None:
        raise T1Refused("settle_unmapped")
    if hermes is not None and worker_argv is None:
        python = Path(hermes).resolve() / ".venv" / "bin" / "python"
        try:
            # Isolated mode and an empty environment: ambient PYTHONPATH cannot make it pass, and no runner
            # variable reaches checkout code.
            checked = subprocess.run([str(python), "-I", "-c", "import mcp"], env={}, timeout=60,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired):
            raise T1Refused("harness_extra_missing:mcp") from None
        if checked.returncode != 0:
            raise T1Refused("harness_extra_missing:mcp")
    properties = ()
    if recipe(entry).dependency_lock is not None:
        properties = worker_properties(entry, hermes, REPO, "t1", T1Refused, worker_argv)
    if early_admission is None:
        marker = read_marker()
        admission = admit(marker, heavy=entry.get("machine_class") == "heavy", roots=spec.roots)
    else:
        admission = early_admission
    if not admission.admitted:
        raise T1Refused(admission.reason)
    if admission.max_roots < spec.min_roots:
        raise T1Refused("roots_below_min")
    if recipe(entry).dependency_lock is None:
        properties = worker_properties(entry, hermes, REPO, "t1", T1Refused, worker_argv)
    index = verify(packs, pack_hash=pack_hash)
    if not control:
        _check_control_only(pack_hash)
    if index["tier"] != spec.pack_tier:
        raise T1Refused("tier")
    if index["harness_artifacts"] != [harness_pin]:
        raise T1Refused("harness_artifact_mismatch")
    rels = sorted(index["packs"])
    genres = sorted(_json(Path(packs) / rel / "sealed/meta.json")["genre"] for rel in rels)
    if genres != sorted(spec.composition) and not (
        control and any(genres == sorted(composition) for composition in spec.control_compositions)
    ):
        raise T1Refused("tier_composition")
    packed = tuple(_pack(Path(packs), rel) for rel in rels)
    _check_c7(packed, control=control)
    table = _routes(system)

    def current_lock():
        return _lock(index, packed, entry, table, pack_hash)

    lock = current_lock()
    pins = {k: lock[k] for k in ("benchmark_commit", "director_commit", "pack_hash",
        "route_table_hash", "write_turn_package_hash")}
    pins.update(scorer_commit=lock["analysis_commit"], generator_commit=lock["benchmark_commit"],
        seed_hash=index["seed_hash"], harness_hash=sha256_canon(lock["harness_artifacts"]),
        system_hash=sha256_canon(lock["system_artifacts"]), **_boundaries(packed))
    return T1Context(entry, harness_pin, index, pack_hash, packed, lock, dict(sorted(pins.items())),
        SessionGate(lock), current_lock, mint_id(canon(["t1", lock_hash(lock), system]).decode(), 0),
        spec.context_roots(marker, admission), marker, hermes, plugin_source, worker_argv, table, model_cache, model_cache_sha256,
        properties, turn_wait_s)


def _check_c7(packed, control=False):
    """Every pack record's template ref has one C-7 entry, across every edition's freeze, that its template rebuilds;
    and one template edition holds every ref of every pack, so v1 and v2 of a template never meet in a run."""
    freeze, cells, seen = {}, c7.cells(REPO), set()
    for path in sorted(C7_FILES.values()):
        for ref, frozen in c7_entries(REPO / path).items():
            if freeze.setdefault(ref, frozen)["entry_sha256"] != frozen["entry_sha256"]:
                raise T1Refused("c7_changed")
    for pack in packed:
        refs = sorted({f"{r['template_id']}-v{r['template_version']}" for r in pack.records.values()})
        seen.update(refs)
        for ref in refs:
            if ref not in freeze or ref not in BY_REF:
                raise T1Refused("c7_missing")
            digest = c7.entry(BY_REF[ref], pack.genre.lower(), cells)["entry_sha256"]
            if digest != freeze[ref]["entry_sha256"] or digest != pack.manifest["pins"]["c7_entries"][ref]:
                raise T1Refused("c7_changed")
    if not any(seen <= {t.ref for templates in edition.values() for t in templates} for edition in EDITIONS.values()):
        raise T1Refused("c7_edition")
    outside = seen - {t.ref for templates in EDITIONS[1].values() for t in templates}
    if outside and not control:
        try:
            admitted = _json(TEMPLATE_ADMISSIONS)["admitted"]
        except (OSError, ValueError, KeyError, TypeError):
            raise T1Refused("template_not_admitted") from None
        if not isinstance(admitted, dict) or any(
            not isinstance(admitted.get(ref), dict)
            or admitted[ref].get("reading") != "cleared"
            or admitted[ref].get("entry_sha256") != freeze[ref]["entry_sha256"]
            for ref in outside
        ):
            raise T1Refused("template_not_admitted")


def check_install(ctx, sandbox):
    """Refuse a wrong install pin before any arm, while holding the run's lease."""
    if recipe(ctx.entry).engine is not None and "recipe" not in ctx.entry:
        # T0's memory-layer host cannot install a built-in context engine as an arm does; the arm's install checks the
        # pin. An outside entry's engine is measured by pins' engine host, the installer its arm uses (#477).
        return
    try:
        measured = install_pins.measure_once(ctx.entry, sandbox, hermes=ctx.hermes,
            plugin_source=ctx.plugin_source,
            worker_argv=[] if callable(ctx.worker_argv) else ctx.worker_argv)
        verify_install_pin(ctx.entry, measured["fresh_install_hash"])
    except install_pins.PinsRefused as error:
        raise T1Refused(error.code, detail=error.detail) from None
    except PinMismatch as error:
        raise T1Refused("pin_mismatch", detail=(str(error),)) from None


def _worker(ctx, life, branch, arm):
    return ctx.worker_argv(life, branch, arm) if callable(ctx.worker_argv) else ctx.worker_argv


def _unit(ctx, pack, arm, b, scratch, voids, floor):
    runs, reclassified = [], set()
    for attempt in range(3):
        run = run_life(arm=arm, entry=ctx.entry, life_dir=pack.life_dir, branch=b,
            items=pack.items[b], records=pack.records_b[b], keys=pack.keys,
            scratch=scratch, run=ctx.run_id, attempt=attempt, gate=ctx.gate,
            current_lock=ctx.current_lock, voids=voids, harness_pin=ctx.harness_pin,
            hermes=ctx.hermes, plugin_source=None if arm == "no_memory" else ctx.plugin_source,
            worker_argv=_worker(ctx, pack.life, b, arm), visible=pack.visible,
            honeypot_token=pack.meta["honeypot_token"], turn_wait_s=ctx.turn_wait_s,
            extra_env=resolve_worker_env(ctx.entry, ctx.model_cache) if arm != "no_memory" else None)
        runs.append(run)
        scores, labels = {}, {}
        try:
            relabel = (is_plugin(ctx.entry) and arm in GATED_ARMS and run.stopped
                and run.stopped[1] in RELABEL and floor.stopped
                and floor.stopped[1:] == run.stopped[1:])
            for item in sorted(pack.items[b], key=lambda i: i["item_id"]):
                iid = item["item_id"]
                cls, label = run.classes.get(iid, (None, None))
                if relabel and (cls, label) == ("SYSTEM_FAILURE", run.stopped[1]):
                    cls = "INFRA_FAILURE"
                    reclassified.add(iid)
                if run.audit.get("status") != "OK" and cls not in ("SYSTEM_FAILURE", "INFRA_FAILURE"):
                    cls, label = "INFRA_FAILURE", "audit:" + ",".join(sorted(run.audit.get("failures", ("missing",))))
                scored = score_item(item, cls=cls, label=label,
                    result=run.results.get(iid, MISSING), envelope=run.envelopes.get(iid, MISSING),
                    act=run.act.get(iid, MISSING), case=pack.cases[iid],
                    scoring_evidence=pack.scoring["evidence"].get(iid), keys=pack.keys[iid],
                    stored_roots=run.stored_roots.get(iid), retained_roots=run.retained_roots.get(iid),
                    attempt=attempt)
                labels[iid] = ("INFRA_FAILURE", scored.label) if isinstance(scored, Infra) else (cls, label)
                scores[iid] = scored
        finally:
            run.cleanup()
        if attempt == 2 or not any(isinstance(s, Infra) for s in scores.values()):
            break
    for iid in sorted(scores):
        if isinstance(scores[iid], Infra):
            scores[iid] = dict(sorted(outcome(identity0(pack.cases[iid].item), None,
                cause="INFRA_FAILURE", infra_reruns=2).items()))
    return UnitResult(pack.life, b, arm, tuple(runs), tuple(sorted(reclassified)), bool(relabel)), scores, labels


def _crosses(pack, item):
    session = pack.records[item["item_id"]]["evidence_session"]
    return session is not None and crosses_cold_restart(pack.schedule, session, item["probe_point"])


def _arm(arm, packs, units, scores, labels, voids):
    bundles, evidence, requests, ids, recall = [], [], [], set(), {}
    blocked_ids = set()
    transforms, hits = set(), 0
    by_life = {p.life: p for p in packs}
    for unit in units:
        pack, run = by_life[unit.life], unit.runs[-1]
        requests.extend(run.post_restart_requests)
        missing = set()
        # Only a run that never reached the resume is blocked: once a post-restart request exists,
        # a missing pair is the system's own drop and S05 judges it.
        if (unit.stop_reclassified or run.stopped is not None and run.stopped[0] == "INFRA_FAILURE") \
                and not run.post_restart_requests:
            missing = set(run.expected_call_ids)
        blocked_ids.update(sorted(missing))
        ids.update(sorted(set(run.expected_call_ids) - missing))
        for attempted in unit.runs:
            transforms.update(attempted.transforms)
            hits += attempted.honeypot_hits
        for item in sorted(pack.items[unit.branch], key=lambda i: i["item_id"]):
            iid, crosses = item["item_id"], _crosses(pack, item)
            cls = scores[iid]["failure_class"]
            reader = run.results.get(iid)
            result = None if cls in ("SYSTEM_FAILURE", "BLOCKED") else reader
            evidence.append(ItemEvidence(item, pack.records[iid], pack.keys[iid], result, cls, crosses, None, None))
            if arm == "system" and crosses and type(scores[iid]["score_milli"]) is int:
                recall[iid] = result is not None and result.in_context is True
    for pack in packs:
        for bundle in sorted(pack.pack["bundles"], key=lambda b: b["bundle_id"]):
            a, b = bundle["items"]
            identity = {k: bundle[k] for k in ("bundle_id", "cell_id", "twin_type")}
            identity["life"] = pack.pack["lives"][0]
            bundles.append(dict(sorted(make_bundle(identity, scores[a], scores[b]).items())))
    verdicts = None
    if arm in GATED_ARMS:
        values = run_invariants(evidence, tier="T1", requests=requests, expected_call_ids=tuple(sorted(ids)))
        if blocked_ids:
            pair = values["INV-PAIR"]
            # S05 numbers expected-<n> over the ids it was given, so blocked ids get their own form.
            infra = {f"expected-blocked-{n}" for n in range(1, len(blocked_ids) + 1)}
            values["INV-PAIR"] = replace(pair, infra=tuple(sorted(set(pair.infra) | infra)),
                status="INFRA_FAILURE" if pair.status in ("PASS", "NOT_EXERCISED") else pair.status)
        verdicts = tuple(values[name] for name in INVARIANTS)
    summary = voids.summary()
    return ArmResult(arm, dict(sorted(scores.items())), dict(sorted(labels.items())),
        tuple(sorted(bundles, key=lambda b: b["bundle_id"])), verdicts,
        dict(sorted(summary.items())) if summary["checked"] else None, tuple(units),
        tuple(recall[iid] for iid in sorted(recall)), tuple(sorted(transforms)), hits)


def run_arms(ctx, *, scratch) -> T1Run:
    """Run the floor first, rerun infrastructure failures and always release scratch."""
    scratch = Path(scratch)
    if scratch.exists() or scratch.is_symlink():
        raise T1Refused("scratch_exists")
    scratch.mkdir(parents=True)
    try:
        for pack in ctx.packs:
            checked = check_compile(pack.life_dir, entry=load(REGISTRY / "hermes-native.toml"),
                route_table=_routes("hermes-native"), harness_pin=ctx.harness_pin,
                checkout=ctx.hermes, scratch=scratch / "check" / pack.life, step_s=STEP_S,
                worker_argv=_worker(ctx, pack.life, "B0", "check_compile"), turn_wait_s=ctx.turn_wait_s)
            if not checked["ok"]:
                for branch, result in sorted(checked["branches"].items()):
                    kinds = {}
                    for mismatch in result["mismatches"]:
                        kind = mismatch["kind"]
                        kinds[kind] = kinds.get(kind, 0) + 1
                    counts = ",".join(f"{kind}:{count}" for kind, count in sorted(kinds.items())) or "-"
                    print(f"check_compile {pack.life} {branch} calls={result['calls']} "
                        f"mismatches={len(result['mismatches'])} kinds={counts}", file=sys.stderr)
                raise T1Refused("check_compile", fields=[b for b in sorted(checked["branches"])
                    if checked["branches"][b]["mismatches"] or not checked["branches"][b]["calls"]])
        units, scores, labels = ({a: [] for a in UNIT_ORDER}, {a: {} for a in UNIT_ORDER},
                                 {a: {} for a in UNIT_ORDER})
        voids, floor = {a: Voids() for a in UNIT_ORDER}, {}
        for pack in ctx.packs:
            for arm in UNIT_ORDER:
                with ThreadPoolExecutor(max_workers=ctx.roots) as pool:
                    pending = [pool.submit(_unit, ctx, pack, arm, b, scratch, voids[arm],
                        floor.get((pack.life, b))) for b in ("B0", "B1")]
                    for b, future in zip(("B0", "B1"), pending, strict=True):
                        unit, values, tagged = future.result()
                        units[arm].append(unit)
                        scores[arm].update(values)
                        labels[arm].update(tagged)
                        if arm == "no_memory":
                            floor[pack.life, b] = unit.runs[-1]
        arms = {a: _arm(a, ctx.packs, units[a], scores[a], labels[a], voids[a]) for a in sorted(UNIT_ORDER)}
        return T1Run(ctx, arms,
            tuple(sorted({i for p in ctx.packs for i in p.meta["restart_crossing"]})),
            dict(sorted((i, life) for p in ctx.packs for i, life in p.meta["singleton_lives"].items())),
            tuple(sorted({i for p in ctx.packs for i in p.meta["duty_items"]})),
            tuple(ctx.index["not_exercised"]))
    finally:
        remove_tree(scratch)
