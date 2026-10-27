"""Offline T1 preparation, three-arm execution and in-memory scoring."""

import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.controls.cache import ControlsTampered, code_sha256
from bicentennial.director.compiler.check import Voids, check_compile
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.harness.hermes.adapter import PinMismatch
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items import c7
from bicentennial.items.protocol import CANARY
from bicentennial.keyed import mint_id
from bicentennial.packs.catalogue import TEMPLATES_BY_GENRE, c7_entries
from bicentennial.packs.install import verify
from bicentennial.packs.manifest import PinnedArtifactChanged
from bicentennial.packs.scoring import case_from_obj
from bicentennial.runner.guard import admit, read_marker
from bicentennial.runner.hermes_score import MISSING, Infra, identity0, score_item
from bicentennial.runner.life import SEGMENTS, STEP_S, LifeRun, run_life
from bicentennial.runner.lock import LockMismatch, SessionGate, build_lock, lock_hash
from bicentennial.score.bundle import make_bundle
from bicentennial.score.classes import outcome
from bicentennial.score.invariants import INVARIANTS, ItemEvidence, run_invariants
from bicentennial.systems.hermes_plugin import PROVIDERS
from bicentennial.systems.registry import REGISTRY, SystemRefused, admit_system, load
from bicentennial.world.db import open_world
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.targeted import crosses_cold_restart, expected_state

UNIT_ORDER = ("no_memory", "system", "wiped")
GATED_ARMS = ("system", "wiped")
RELABEL = ("end_timeout", "final_mismatch", "resume_failed", "turn_timeout")
REPO = Path(__file__).resolve().parents[3]


class T1Refused(RuntimeError):
    def __init__(self, code, fields=()):
        self.code, self.fields = code, tuple(sorted(fields))
        super().__init__(code)


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


@dataclass(frozen=True)
class UnitResult:
    life: str
    branch: str
    arm: str
    runs: tuple[LifeRun, ...]
    reclassified: tuple


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
            check=True, capture_output=True, text=True).stdout.strip()
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
        harness_artifacts=index["harness_artifacts"], system_artifacts=[entry["artifact"]],
        environment_hash=boundary["environment_boundary_hash"],
        route_table_hash=route_table_hash(RouteTable.load(table)),
        write_turn_package_hash=code_sha256(("director/scripted.py",)),
        fault_lite_schedule_hash=sha256_canon({p.life: p.schedule.fault_lite()
            for p in sorted(packs, key=lambda p: p.life)}), pack_hash=pack_hash,
        tool_lists_hash=sha256_canon({k: entry.get(k) for k in ("read_tools", "recall", "write_tools")}),
        account_pool=[]).items()))


def prepare(*, system, packs, pack_hash, hermes=None, plugin_source=None, entry=None,
            worker_argv=None) -> T1Context:
    """Refuse invalid inputs and pin both lives before constructing any adapter."""
    if entry is None:
        try:
            entry = load(REGISTRY / f"{system}.toml")
        except FileNotFoundError:
            raise T1Refused("unknown_system") from None
    if entry["name"] != system:
        raise T1Refused("unknown_system")
    entry = json.loads(canon(entry))
    admit_system(entry)
    if entry["harness"] != "hermes":
        raise T1Refused("harness_not_hermes")
    harness_pin = dict(sorted(load(REGISTRY / "hermes-native.toml")["artifact"].items()))
    if (hermes is None and worker_argv is None) or (system in PROVIDERS and plugin_source is None):
        raise T1Refused("missing_input")
    marker = read_marker()
    admission = admit(marker, heavy=entry.get("machine_class") == "heavy", roots=2)
    if not admission.admitted:
        raise T1Refused(admission.reason)
    index = verify(packs, pack_hash=pack_hash)
    if index["tier"] != "T1":
        raise T1Refused("tier")
    if index["harness_artifacts"] != [harness_pin]:
        raise T1Refused("harness_artifact_mismatch")
    rels = sorted(index["packs"])
    if sorted(_json(Path(packs) / rel / "sealed/meta.json")["genre"] for rel in rels) != ["G1", "G2"]:
        raise T1Refused("tier_composition")
    packed = tuple(_pack(Path(packs), rel) for rel in rels)
    freeze, cells = c7_entries(REPO / "specs/ring0/c7-partial.json"), c7.cells(REPO)
    for pack in packed:
        templates = dict(sorted((t.ref, t) for t in TEMPLATES_BY_GENRE[pack.genre].values()))
        refs = sorted({f"{r['template_id']}-v{r['template_version']}" for r in pack.records.values()})
        for ref in refs:
            if ref not in freeze:
                raise T1Refused("c7_missing")
            digest = c7.entry(templates[ref], pack.genre.lower(), cells)["entry_sha256"]
            if digest != freeze[ref]["entry_sha256"] or digest != pack.manifest["pins"]["c7_entries"][ref]:
                raise T1Refused("c7_changed")
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
        2 if marker.exit == 0 else 1, marker, hermes, plugin_source, worker_argv, table)


def _worker(ctx, life, branch, arm):
    return ctx.worker_argv(life, branch, arm) if callable(ctx.worker_argv) else ctx.worker_argv


def _unit(ctx, pack, arm, b, scratch, voids, floor):
    runs, reclassified = [], set()
    for attempt in range(3):
        run = run_life(arm=arm, entry=ctx.entry, life_dir=pack.life_dir, branch=b,
            items=pack.items[b], records=pack.records_b[b], keys=pack.keys,
            scratch=scratch / "units", run=ctx.run_id, attempt=attempt, gate=ctx.gate,
            current_lock=ctx.current_lock, voids=voids, harness_pin=ctx.harness_pin,
            hermes=ctx.hermes, plugin_source=None if arm == "no_memory" else ctx.plugin_source,
            worker_argv=_worker(ctx, pack.life, b, arm), visible=pack.visible,
            honeypot_token=pack.meta["honeypot_token"])
        runs.append(run)
        scores, labels = {}, {}
        try:
            relabel = (ctx.entry["name"] in PROVIDERS and arm in GATED_ARMS and run.stopped
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
    return UnitResult(pack.life, b, arm, tuple(runs), tuple(sorted(reclassified))), scores, labels


def _crosses(pack, item):
    session = pack.records[item["item_id"]]["evidence_session"]
    return session is not None and crosses_cold_restart(pack.schedule, session, item["probe_point"])


def _arm(arm, packs, units, scores, labels, voids):
    bundles, evidence, requests, ids, recall = [], [], [], set(), {}
    transforms, hits = set(), 0
    by_life = {p.life: p for p in packs}
    for unit in units:
        pack, run = by_life[unit.life], unit.runs[-1]
        requests.extend(run.post_restart_requests)
        ids.update(run.expected_call_ids)
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
        verdicts = tuple(values[name] for name in INVARIANTS)
    summary = voids.summary()
    return ArmResult(arm, dict(sorted(scores.items())), dict(sorted(labels.items())),
        tuple(sorted(bundles, key=lambda b: b["bundle_id"])), verdicts,
        dict(sorted(summary.items())) if summary["checked"] else None, tuple(units),
        tuple(recall[iid] for iid in sorted(recall)), tuple(sorted(transforms)), hits)


def _remove_tree(path):
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        return
    for child in sorted(path.iterdir()):
        _remove_tree(child)
    path.rmdir()


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
                worker_argv=_worker(ctx, pack.life, "B0", "check_compile"))
            if not checked["ok"]:
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
        _remove_tree(scratch)
