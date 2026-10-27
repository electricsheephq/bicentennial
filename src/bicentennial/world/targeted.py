"""Deterministic placement contracts for Ring 0 targeted lives."""

import json
import re
import shutil
import sqlite3
import tomllib
from collections.abc import Callable
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.genres.g1_software.codebase_model import write_commit
from bicentennial.genres.g1_software.diffs import (
    CALLS,
    EMPTY_TREE_HASH,
    Read,
    expected_result,
    repo_tree_hashes,
    start_boundary,
    write_reads,
)
from bicentennial.genres.g1_software.world import Mix, build_g1, world_meta
from bicentennial.genres.g2_assistant.envseed import env_state_hashes
from bicentennial.genres.g2_assistant.world import build_base, create
from bicentennial.items.compile import compile_branch
from bicentennial.items.levers import STRESS_TAGS
from bicentennial.items.protocol import CANARY
from bicentennial.render.session_cut import cut

from . import create_world, world_hash
from .db import insert_entity
from .processes import mint
from .processes.corrections import Chain, write_corrections
from .scale import PROVISIONAL, named
from .schedule import Schedule, build_schedule
from .twin import IndependenceError, TwinLife, apply, plan, twin_life

MIN_DISTANCE_SESSIONS = 2
MAX_ATTEMPTS = 8
NO_ENV_HASH = sha256_canon({})
NO_ENV_LABEL = "no env server in v0.1"
WAKES = ("none", "kill", "swap", "restart", "compaction", "gap")
ROOT = Path(__file__).resolve().parents[3]


class PlacementError(ValueError):
    def __init__(self, rule):
        self.rule = rule
        super().__init__(rule)


def seed_text(n):
    if type(n) is not int or n < 0:
        raise PlacementError("composition")
    return str(n)


def _tier_source(tier):
    ring = (ROOT / "specs/ring0/RING0.md").read_text(encoding="utf-8")
    scale = named("t1") if tier == "T1" else named("t0-micro", sessions=3)
    common = dict(canary=CANARY, tier=tier, scale=scale.name, window=scale.window,
                  window_label=PROVISIONAL["dev_window"],
                  levers_label=re.search(r'rungs: ([^"]+)', ring)[1])
    if tier == "T0":
        return common | dict(seeds=[1], sessions=[1, 3], wakes=list(WAKES),
                             defaults=dict(sessions=3, distance=1, wake="none"))
    qa, act = map(int, re.search(r"at most (\d+) QA items and (\d+) action items", ring).groups())
    aliases = re.search(r"alias from `([^`]+)` to `([^`]+)`", ring).groups()
    return common | dict(
        checkpoints=list(scale.checkpoints), cold_restart="every session start after the first",
        min_distance_sessions=MIN_DISTANCE_SESSIONS, early_sessions=2, min_early_bundles=2,
        qa_per_checkpoint=qa, act_per_checkpoint=act,
        not_exercised=["KEEP-FORGET", "KEEP-NEIGH", "TUE-EVENT"],
        kill=dict(session=scale.kill, turn=1),
        swap=dict(session=scale.swap, wiring_only=True, from_alias=aliases[0], to_alias=aliases[1]),
        compaction=dict(min_sprints=len(scale.sprint_ranges)),
        g1=dict(deadline_at=[[[1, 1], [2, 1]], [[1, 2], [2, 2]]]),
        lives=[dict(life="t1-g1", genre="G1", seed=1, reads_session=1),
               dict(life="t1-g2", genre="G2", seed=2)],
        selection=dict(g1=["drift-chain", "drift-chain-fault", "drift-config", "recall-value", "wake-loop"],
                       g2=["drift-asof", "drift-booking", "drift-no-update", "keep-incidental", "recall-count"],
                       pinned={"drift-chain-fault": 20}))


def load_tier(path):
    try:
        with Path(path).open("rb") as source:
            spec = tomllib.load(source)
        valid = spec.get("tier") in ("T0", "T1") and canon(spec) == canon(_tier_source(spec["tier"]))
    except (TypeError, ValueError):
        raise PlacementError("composition") from None
    if not valid:
        raise PlacementError("composition")
    return spec


def seeds_manifest(spec):
    lives = [{k: row[k] for k in ("life", "genre", "seed")} for row in spec.get("lives", [])]
    seeds = spec["seeds"] if spec["tier"] == "T0" else [row["seed"] for row in lives]
    for seed in seeds:
        seed_text(seed)
    return dict(canary=CANARY, tier=spec["tier"], seeds=sorted(set(seeds)), lives=lives)


@dataclass(frozen=True, kw_only=True)
class MicroSpec:
    genre: str
    seed: int
    sessions: int
    distance: int
    wake: str
    recipe: str

    def __post_init__(self):
        seed_text(self.seed)
        if self.genre not in ("G1", "G2") or type(self.recipe) is not str or not self.recipe:
            raise PlacementError("composition")
        if type(self.sessions) is not int or not 1 <= self.sessions <= 3:
            raise PlacementError("sessions")
        if type(self.distance) is not int or not 0 <= self.distance < self.sessions:
            raise PlacementError("distance")
        if self.wake not in WAKES or self.wake != "none" and (self.sessions < 2 or self.distance < 1):
            raise PlacementError("wake")

    @property
    def evidence_session(self):
        return self.sessions - self.distance

    def to_obj(self, template):
        return asdict(self) | {"template": template.ref}


def life_id(spec, template):
    return f"t0-{spec.genre.lower()}-{template.ref}-s{spec.sessions}-d{spec.distance}-{spec.wake}"


def micro_schedule(spec, template):
    return build_schedule(seed_text(spec.seed), life_id(spec, template),
                          named("t0-micro", sessions=spec.sessions,
                                wake=None if spec.wake == "none" else spec.wake))


@dataclass(frozen=True)
class Placement:
    evidence_session: int | None
    attempt: int = 0
    rejected: tuple[tuple[str, str], ...] = ()


Recipe = Callable[[sqlite3.Connection, Schedule, Placement], str]


def hostable(evidence_session, k):
    return k - evidence_session >= MIN_DISTANCE_SESSIONS


def cold_restarts(schedule):
    return tuple(range(2, len(schedule.sessions) + 1))


def crosses_cold_restart(schedule, s_e, k):
    return any(s_e < c <= k for c in cold_restarts(schedule))


def expected_state(genre, schedule):
    if genre not in ("G1", "G2"):
        raise PlacementError("composition")

    def state(db):
        if genre == "G1":
            return {k: dict(repo_tree_hash=h, env_state_hash=NO_ENV_HASH)
                    for k, h in repo_tree_hashes(db, schedule).items()}
        return {k: dict(repo_tree_hash=EMPTY_TREE_HASH, env_state_hash=h)
                for k, h in env_state_hashes(db).items()}

    return state


def t1_schedule(spec, row):
    schedule = build_schedule(seed_text(row["seed"]), row["life"], named("t1"))
    kill, swap = spec["kill"], spec["swap"]
    faults = [dict(kind="kill", session=kill["session"], turn=kill["turn"]),
              dict(kind="swap", session=swap["session"], turn=None)]
    sprints = [p.index for p in schedule.sessions if p.long_sprint]
    if (len(schedule.sessions) != 20 or schedule.scale.checkpoints != (10, 20)
            or schedule.scale.window != spec["window"] or schedule.fault_lite() != faults
            or len(sprints) < spec["compaction"]["min_sprints"]
            or not any(s < kill["session"] for s in sprints)
            or not any(s > kill["session"] for s in sprints) or not swap["wiring_only"]):
        raise PlacementError("composition")
    return schedule


def _select_templates(spec, row, templates):
    templates = tuple(templates)
    indexed = {t.template_id: t for t in templates}
    names = spec["selection"][row["genre"].lower()]
    if len(indexed) != len(templates) or any(name not in indexed for name in names):
        raise PlacementError("composition")
    selected = tuple(indexed[name] for name in sorted(names))
    if (sum(t.kind == "act" for t in selected) > 4
            or any(t.cell_id in spec["not_exercised"] for t in selected)
            or any(not is_dataclass(t) or "checkpoint" not in {f.name for f in fields(t)}
                   for t in selected)):
        raise PlacementError("composition")
    return selected


def _assign_checkpoints(db, schedule, templates, *, spec, principal_id, genre):
    rendered = cut(db, schedule, branch="B0", principal_id=principal_id,
                   expected_state=expected_state(genre, schedule)(db))
    assigned, counts = [], {}

    def compile_one(template):
        return compile_branch(db, schedule, rendered, (template,)).entries

    def hosts(entries):
        return all(meta["evidence_session"] is not None
                   and hostable(meta["evidence_session"], item["probe_point"])
                   for item, meta in entries)

    for template in sorted(templates, key=lambda t: t.template_id):
        pin = spec["selection"]["pinned"].get(template.template_id)
        chosen = replace(template, checkpoint=pin if pin is not None else 20)
        try:
            entries = compile_one(chosen)
        except ValueError:
            if pin is not None:
                raise
            chosen = replace(template, checkpoint=10)
            entries = compile_one(chosen)
            if counts.get((10, template.kind), 0) + len(entries) > spec[f"{template.kind}_per_checkpoint"]:
                raise PlacementError("composition") from None
        if not entries or not hosts(entries):
            raise PlacementError("hostable")
        limit = spec[f"{template.kind}_per_checkpoint"]
        if pin is None and chosen.checkpoint == 20 and all(hostable(meta["evidence_session"], 10) for _, meta in entries):
            try:
                earlier = replace(template, checkpoint=10)
                candidates = compile_one(earlier)
            except ValueError:
                candidates = ()
            if (candidates and hosts(candidates)
                    and counts.get((10, template.kind), 0) + len(candidates) <= limit):
                chosen, entries = earlier, candidates
        key = chosen.checkpoint, template.kind
        counts[key] = counts.get(key, 0) + len(entries)
        assigned.append(chosen)
    compile_branch(db, schedule, rendered, assigned)
    return tuple(assigned)


def _build_t1(path, schedule, *, spec, row):
    """Build the fixed-seed material before checkpoint assignment and twin planning."""
    path, db = Path(path), None
    try:
        if row["genre"] == "G2":
            life = build_base(path, seed=seed_text(row["seed"]), life=row["life"], scale=named("t1"))
            db, principal = life.db, life.people.principal
            if life.schedule.to_json() != schedule.to_json():
                raise PlacementError("composition")
        elif row["genre"] == "G1":
            db = create_world(path, world_meta(seed_text(row["seed"]), len(schedule.sessions)))
            at = tuple(tuple(tuple(p) for p in chain) for chain in spec["g1"]["deadline_at"])
            world = build_g1(db, schedule, mix=Mix(deadlines=(1, 1), deadline_at=at))
            principal = world.principal
            subject = mint(schedule, "targeted", "setting-fix", "entity", "constant", 0)
            insert_entity(db, id=subject, kind="constant", canonical_name="retry interval", aliases_json=[],
                          created_t=schedule.sessions[0].t_start, retired_t=None)
            write_corrections(db, schedule, [Chain(
                id="setting-fix", subject=subject, key="value", stem="SETTING", depth=1,
                at=((1, 3), (2, 3)))], principal=principal)
            original = mint(schedule, "corrections", "setting-fix", "fact", "value", 0)
            write_commit(db, schedule, unit_id="setting-fix", n=0, fact_id=original, author=principal)
            reads = [Read(id=f"read-{i:02d}", session=row["reads_session"], turn=i % 5 + 1,
                          name=name, args=args) for i, (name, args) in enumerate(CALLS)]
            write_reads(db, schedule, reads, principal=principal)
        else:
            raise PlacementError("composition")
        db.commit()
        return db, principal
    except Exception:
        if db is not None:
            db.close()
        path.unlink(missing_ok=True)
        raise


def _links(db, event_id):
    return [tuple(r) for r in db.execute(
        "SELECT event_id, fact_id, role FROM link WHERE event_id=? ORDER BY fact_id, role", (event_id,))]


def _write_pair(db0, db1, schedule, principal):
    """Try calls in registered order, rolling back each speculative materialization."""
    session = schedule.scale.kill
    for name, args in CALLS:
        results = [expected_result(db, schedule, boundary=start_boundary(schedule, session),
                                   name=name, args=args) for db in (db0, db1)]
        if results[0] != results[1]:
            continue
        read = Read(id="read-pair", session=session, turn=1, name=name, args=args)
        links = []
        for db in (db0, db1):
            db.execute("SAVEPOINT pair_candidate")
            try:
                eid, = write_reads(db, schedule, (read,), principal=principal)
                links.append(_links(db, eid))
            finally:
                db.execute("ROLLBACK TO pair_candidate")
                db.execute("RELEASE pair_candidate")
        if links[0] == links[1]:
            write_reads(db0, schedule, (read,), principal=principal)
            db0.commit()
            return
    raise PlacementError("reads")


@dataclass(frozen=True)
class TargetedLife:
    life: str
    genre: str
    seed: int
    schedule: Schedule
    principal_id: str
    out_dir: Path
    attempt: int
    twin: TwinLife
    singleton_lives: dict
    restart_crossing: frozenset[str]
    manifest: dict


def _untouched(db):
    if db.execute(
            "SELECT c.fact_id FROM commitment c JOIN link l ON l.fact_id=c.fact_id "
            "JOIN event e ON e.id=l.event_id WHERE e.t_sim BETWEEN c.window_open_t AND c.window_close_t "
            "ORDER BY c.fact_id LIMIT 1").fetchone():
        raise PlacementError("untouched")


def _check_reads(db0, db1, schedule):
    rows = db0.execute("SELECT id, t_sim, payload_json FROM event WHERE kind='tool' "
                       "AND channel='tool_result' ORDER BY id").fetchall()
    calls, pair = [], []
    for eid, t, payload in rows:
        session = next(p.index for p in schedule.sessions if t in p.turn_t)
        payload = json.loads(payload)
        tool = payload["tool"]
        results = [expected_result(db, schedule, boundary=start_boundary(schedule, session), **tool)
                   for db in (db0, db1)]
        other = db1.execute("SELECT t_sim, payload_json FROM event WHERE id=?", (eid,)).fetchone()
        if (results[0] != results[1] or results[0] != payload["result"]
                or other is None or tuple(other) != (t, canon(payload).decode())
                or _links(db0, eid) != _links(db1, eid)):
            raise PlacementError("reads")
        if session == 1:
            calls.append(canon((tool["name"], tool["args"])))
        else:
            pair.append((session, t))
    if (len(rows) != len(CALLS) + 1 or sorted(calls) != sorted(canon(c) for c in CALLS)
            or pair != [(schedule.scale.kill, schedule.sessions[schedule.scale.kill - 1].turn_t[0])]):
        raise PlacementError("reads")


def _check_micro(spec, template, schedule, compiled):
    records, bundles = compiled.records, compiled.bundles
    if len(schedule.sessions) != spec.sessions or spec.sessions > 3:
        raise PlacementError("sessions")
    if (len(records) != 2 or any(r["template_id"] != template.template_id for r in records)
            or len(bundles) != (0 if template.twin_type is None else 1)):
        raise PlacementError("bundles")
    by_id = {r["item_id"]: r for r in records}
    if template.twin_type is None:
        if set(by_id) != set(compiled.singleton_lives()):
            raise PlacementError("bundles")
    elif [by_id[i]["branch"] for i in bundles[0]["items"]] != ["B0", "B1"]:
        raise PlacementError("bundles")
    b0, = [r for r in records if r["branch"] == "B0"]
    if (b0["evidence_session"] != spec.evidence_session
            or b0["levers"]["distance_sessions"] != spec.distance):
        raise PlacementError("distance")
    if spec.wake != "none":
        wakes = schedule.wakes()
        if (len(wakes) != 1 or wakes[0][1] != spec.sessions
                or any(r["evidence_session"] is None or r["evidence_session"] >= spec.sessions
                       or spec.wake in STRESS_TAGS and STRESS_TAGS[spec.wake] not in r["crossed"]
                       for r in records)):
            raise PlacementError("wake")


def _check_t1(spec, compiled):
    items = {i["item_id"]: i for i in compiled.items}
    if any(r["evidence_session"] is None
           or not hostable(r["evidence_session"], items[r["item_id"]]["probe_point"])
           for r in compiled.records):
        raise PlacementError("hostable")
    early = {r["bundle_id"] for r in compiled.records if r["branch"] == "B0"
             and r["bundle_id"] is not None and r["evidence_session"] <= spec["early_sessions"]}
    if len(early) < spec["min_early_bundles"]:
        raise PlacementError("early")


def _restart_crossing(schedule, compiled):
    records = {r["item_id"]: r for r in compiled.records}
    items = {i["item_id"]: i for i in compiled.items}
    return frozenset(b["bundle_id"] for b in compiled.bundles if all(
        records[i]["evidence_session"] is not None
        and crosses_cold_restart(schedule, records[i]["evidence_session"], items[i]["probe_point"])
        and items[i]["memory_tag"] == "memory_exclusive" for i in b["items"]))


def generate(spec_or_row, templates, build, *, out_dir, _tier=None):
    """Build a micro Recipe, or a T1 path factory returning (connection, principal).

    The caller owns the returned twin's B1 connection; B0 is closed on return.
    Every failure after reserving the directory removes the entire reservation.
    """
    templates, out_dir = tuple(templates), Path(out_dir)
    micro = isinstance(spec_or_row, MicroSpec)
    spec = spec_or_row if micro else (_tier if _tier is not None else _tier_source("T1"))
    row = None if micro else spec_or_row
    if micro:
        if not templates:
            raise PlacementError("bundles")
        genre, seed = spec.genre, spec.seed
        schedule = micro_schedule(spec, templates[0])
    else:
        genre, seed = row["genre"], row["seed"]
        schedule = t1_schedule(spec, row)
    if out_dir.exists():
        raise PlacementError("composition")
    out_dir.mkdir(parents=True)
    previous, rejected, db0, twin = None, (), None, None
    try:
        for attempt in range(MAX_ATTEMPTS):
            placement = Placement(spec.evidence_session if micro else None, attempt, rejected)
            path = out_dir / "world.B0.db"
            try:
                if micro:
                    db0 = (create_world(path, world_meta(seed_text(seed), spec.sessions)) if genre == "G1"
                           else create(path, schedule))
                    principal = build(db0, schedule, placement)
                else:
                    db0, principal = build(path, schedule, placement)
                db0.commit()
                meta = dict(db0.execute("SELECT * FROM meta").fetchone())
                if meta["genre"] != genre or meta["seed"] != seed_text(seed):
                    raise PlacementError("composition")
                assigned = templates if micro else _assign_checkpoints(
                    db0, schedule, templates, spec=spec, principal_id=principal, genre=genre)
                if not micro and genre == "G1":
                    rendered = cut(db0, schedule, branch="B0", principal_id=principal,
                                   expected_state=expected_state(genre, schedule)(db0))
                    flips = plan(db0, schedule, compile_branch(db0, schedule, rendered, assigned),
                                 principal_id=principal)
                    preview_path = out_dir / "pair-preview.db"
                    snapshot_path = out_dir / "pair-snapshot.db"
                    snapshot = apply(db0, flips, snapshot_path)
                    try:
                        preview = create_world(preview_path, meta)
                        try:
                            snapshot.backup(preview)
                            _write_pair(db0, preview, schedule, principal)
                        finally:
                            preview.close()
                            preview_path.unlink(missing_ok=True)
                    finally:
                        snapshot.close()
                        snapshot_path.unlink(missing_ok=True)
                twin = twin_life(db0, schedule, assigned, world_path=out_dir / "world.B1.db",
                                 out_dir=out_dir / "branches", principal_id=principal,
                                 expected_state=expected_state(genre, schedule))
            except IndependenceError as error:
                current = world_hash(db0)
                db0.close()
                db0 = None
                path.unlink(missing_ok=True)
                if current == previous or attempt == MAX_ATTEMPTS - 1:
                    raise
                previous, rejected = current, error.rejected
                continue
            if micro and len(templates) == 1:
                _check_micro(spec, templates[0], schedule, twin.compiled)
            elif not micro:
                _check_t1(spec, twin.compiled)
            for db in (db0, twin.b1):
                _untouched(db)
            if not micro and genre == "G1":
                _check_reads(db0, twin.b1, schedule)
            manifest = dict(canary=CANARY, tier="T0" if micro else "T1", life=schedule.life,
                            genre=genre, seed=seed, generator_version=meta["generator_version"],
                            spec=spec.to_obj(templates[0]) if micro else dict(row),
                            world_hash_b0=world_hash(db0), world_hash_b1=world_hash(twin.b1),
                            history_set_hash=twin.history_set_hash, fault_lite=schedule.fault_lite())
            if genre == "G1":
                manifest["env_state_label"] = NO_ENV_LABEL
            (out_dir / "life.json").write_bytes(canon(dict(
                canary=CANARY, life=schedule.life, seed=seed_text(seed), scale=schedule.scale.name)) + b"\n")
            records = {r["item_id"]: r for r in twin.compiled.records}
            for branch in ("B0", "B1"):
                (out_dir / f"items.{branch}.json").write_bytes(canon([
                    i for i in twin.compiled.items if records[i["item_id"]]["branch"] == branch]) + b"\n")
            for branch_file in sorted((out_dir / "branches").iterdir()):
                shutil.copyfile(branch_file, out_dir / branch_file.name)
            return TargetedLife(schedule.life, genre, seed, schedule, principal, out_dir, attempt, twin,
                                twin.compiled.singleton_lives(), _restart_crossing(schedule, twin.compiled), manifest)
    except BaseException:
        if twin is not None:
            twin.b1.close()
        if db0 is not None:
            db0.close()
            db0 = None
        shutil.rmtree(out_dir)
        raise
    finally:
        if db0 is not None:
            db0.close()


def micro_life(spec, template, recipe, *, out_dir):
    return generate(spec, (template,), recipe, out_dir=out_dir)


def t1_life(spec, row, templates, *, out_dir):
    selected = _select_templates(spec, row, templates)
    return generate(row, selected, lambda path, schedule, placement: _build_t1(
        path, schedule, spec=spec, row=row), out_dir=out_dir, _tier=spec)


def t1_lives(spec, templates_by_genre, *, root):
    return tuple(t1_life(spec, row, templates_by_genre[row["genre"]],
                         out_dir=Path(root) / row["life"]) for row in spec["lives"])
