"""Targeted generation acceptance and prerequisite checks."""

import ast
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from bicentennial.genres.g1_software.world import MIX, Mix, build_g1, world_meta
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.items.compile import compile_branch
from bicentennial.items.protocol import CANARY, Instance, Option, Template
from bicentennial.keyed import uniform_int
from bicentennial.render.session_cut import cut
from bicentennial.world import create_world, world_hash
from bicentennial.world.processes import mint
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.targeted import (
    MicroSpec,
    _assign_checkpoints,
    _build_t1,
    cold_restarts,
    crosses_cold_restart,
    expected_state,
    hostable,
    load_tier,
    seeds_manifest,
    t1_schedule,
)

ROOT = Path(__file__).resolve().parents[2]


def test_placement_baseline(tmp_path):
    schedule = build_schedule("1", "t1-g1", named("t1"))
    db = create_world(tmp_path / "baseline.db", world_meta("1", 20))
    try:
        build_g1(db, schedule, mix=Mix(deadlines=(1, 1)))
        assert world_hash(db) == "c7f7f6f955410fed3546af35c1ed93e2ebea29c8afe1e70a0e8ceda191ce15b9"
        occupied = {t for (t,) in db.execute("SELECT t_sim FROM event WHERE kind != 'filler'")}
        tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
        for chain in tier["g1"]["deadline_at"]:
            for session, turn in chain:
                assert schedule.sessions[session - 1].turn_t[turn - 1] not in occupied
    finally:
        db.close()


@dataclass(frozen=True, kw_only=True, eq=False)
class Deadline(Template):
    """Test-local row-derived fork over G14's selected deadline material."""

    checkpoint: int = 20
    chain: str

    def instances(self, db, schedule):
        facts = tuple(mint(schedule, "corrections", self.chain, "fact", "value", j) for j in range(2))
        value = json.loads(db.execute("SELECT object FROM fact WHERE id=?", (facts[-1],)).fetchone()[0])
        events = tuple(r[0] for r in db.execute(
            "SELECT DISTINCT event_id FROM link WHERE fact_id IN (?, ?) ORDER BY event_id", facts))
        return (Instance(
            key=f"chain-{self.chain}", probe_point=self.checkpoint, prompt="Record the current deadline.",
            decisive_fact_id=facts[-1], gold_spans=events,
            decision_table_ref=self.decision_tables[0]["table_id"],
            options=(Option(key="current", token_fact_ids=(facts[-1],),
                            plan=dict(steps=[dict(tool=dict(name="set_entry", args=dict(value=value)))])),)),)


def test_build_prerequisites(tmp_path):
    zero = Mix(deadlines=(), constraints=0, relaxed=0, decisions=0, chat_only=0,
               flags=0, constants=0, changed=0, mentions=(), endpoints=0, commitments=())
    for label, scale, mix in (("micro", named("t0-micro", sessions=3), zero),
                              ("default", named("t1"), MIX),
                              ("targeted", named("t1"), Mix(deadlines=(1, 1)))):
        schedule = build_schedule("1", "t1-g1", scale)
        db = create_world(tmp_path / f"{label}.db", world_meta("1", scale.sessions))
        try:
            build_g1(db, schedule, mix=mix)
            if label == "targeted":
                for chain in ("deadline-0", "deadline-1"):
                    placements = []
                    for j in range(2):
                        fid = mint(schedule, "corrections", chain, "fact", "value", j)
                        t = db.execute("SELECT e.t_sim FROM event e JOIN link l ON l.event_id=e.id "
                                       "WHERE l.fact_id=? AND l.role='assert'", (fid,)).fetchone()[0]
                        placements.append(next((p.index, p.turn_t.index(t) + 1)
                                               for p in schedule.sessions if t in p.turn_t))
                    print(chain, placements)
        finally:
            db.close()
    life = build_base(tmp_path / "g2.db", seed="2", life="t1-g2", scale=named("t1"))
    life.db.close()


@pytest.mark.parametrize("chain,fault", (("deadline-0", False), ("deadline-1", True)))
def test_t1_deadline_material(tmp_path, chain, fault):
    """G17 A3 must satisfy G14's selected DriftChain material predicates."""
    schedule = build_schedule("1", "t1-g1", named("t1"))
    db = create_world(tmp_path / "material.db", world_meta("1", 20))
    try:
        tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
        at = tuple(tuple(tuple(p) for p in positions) for positions in tier["g1"]["deadline_at"])
        build_g1(db, schedule, mix=Mix(deadlines=(1, 1), deadline_at=at))
        facts = tuple(mint(schedule, "corrections", chain, "fact", "value", j)
                      for j in range(2))
        assert not db.execute("SELECT 1 FROM fact WHERE id=?",
                              (mint(schedule, "corrections", chain, "fact", "value", 2),)).fetchone()
        positions = []
        for fid in facts:
            assert not db.execute("SELECT 1 FROM fact_surface WHERE fact_id=?", (fid,)).fetchone()
            t = db.execute("SELECT e.t_sim FROM event e JOIN link l ON l.event_id=e.id "
                           "WHERE l.fact_id=? AND l.role='assert'", (fid,)).fetchone()[0]
            positions.append(next((p.index, p.turn_t.index(t) + 1)
                                  for p in schedule.sessions if t in p.turn_t))
        kill = (schedule.scale.kill, 1)
        template_id = "drift-chain-fault" if fault else "drift-chain"
        template = Deadline(
            template_id=template_id, version=1, cell_id="DRIFT-CUR", kind="act", twin_type="fork",
            direction="recency", semantics="as_known", chain=chain,
            checkpoint=20 if fault else 10,
            decision_tables=(dict(canary=CANARY, table_id=f"{template_id}-v1", gold="act", timed=False,
                                  admissible=["gold_state"], disqualifiers=[], benign_extras=[]),))
        principal = db.execute("SELECT actor_id FROM event ORDER BY id LIMIT 1").fetchone()[0]
        rendered = cut(db, schedule, branch="B0", principal_id=principal,
                       expected_state=expected_state("G1", schedule)(db))
        compiled = compile_branch(db, schedule, rendered, (template,))
        item, record = compiled.entries[0]
        evidence = dict(template=template_id, item_id=item["item_id"], decisive_fact_id=facts[-1],
                        positions=positions, evidence_session=record["evidence_session"],
                        distance_sessions=record["levers"]["distance_sessions"], crossed=record["crossed"])
        print(evidence)
        if fault:
            assert all(position <= kill for position in positions), evidence
            assert "crash" in record["crossed"]
        else:
            assert item["probe_point"] < kill[0]
            assert "crash" not in record["crossed"]
        assert positions == list(at[1 if fault else 0])
        assert hostable(record["evidence_session"], item["probe_point"]), evidence
    finally:
        db.close()


def test_t1_composition_and_three_act_allocation(tmp_path):
    tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
    for row in tier["lives"]:
        schedule = t1_schedule(tier, row)
        assert len(schedule.sessions) == 20
        assert schedule.scale.checkpoints == (10, 20)
        assert schedule.fault_lite() == [dict(kind="kill", session=11, turn=1),
                                        dict(kind="swap", session=15, turn=None)]
        db, principal = _build_t1(tmp_path / f"{row['life']}.db", schedule, spec=tier, row=row)
        try:
            state = expected_state(row["genre"], schedule)(db)
            if row["genre"] == "G2":
                from bicentennial.genres.g1_software.diffs import EMPTY_TREE_HASH
                assert all(v["repo_tree_hash"] == EMPTY_TREE_HASH for v in state.values())
                continue
            from bicentennial.canon import sha256_canon
            from bicentennial.genres.g1_software.diffs import CALLS
            assert all(v["env_state_hash"] == sha256_canon({}) for v in state.values())
            assert db.execute("SELECT count(*) FROM event WHERE kind='tool'").fetchone()[0] == len(CALLS)
            ids = ("drift-chain", "drift-chain-fault", "drift-config")
            templates = tuple(Deadline(
                template_id=tid, version=1, cell_id="DRIFT-CUR", kind="act", twin_type="fork",
                direction="recency", semantics="as_known", chain=f"deadline-{i % 2}",
                decision_tables=(dict(canary=CANARY, table_id=f"{tid}-v1", gold="act", timed=False,
                                      admissible=["gold_state"], disqualifiers=[], benign_extras=[]),))
                for i, tid in enumerate(ids))
            assigned = _assign_checkpoints(db, schedule, templates, spec=tier,
                                           principal_id=principal, genre="G1")
            assert [t.checkpoint for t in assigned] == [10, 20, 10]
            facts = tuple(mint(schedule, "corrections", "setting-fix", "fact", "value", i) for i in range(2))
            assert db.execute("SELECT count(*) FROM fact_surface WHERE fact_id=?", (facts[0],)).fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM fact_surface WHERE fact_id=?", (facts[1],)).fetchone()[0] == 0
            assert db.execute("SELECT speech_act FROM fact WHERE id=?", (facts[1],)).fetchone()[0] == "assert"
        finally:
            db.close()


def test_tier_sources():
    t0, t1 = (load_tier(ROOT / "tiers/life_specs" / f"{tier}.toml") for tier in ("t0", "t1"))
    assert seeds_manifest(t0) == dict(canary=t0["canary"], tier="T0", seeds=[1], lives=[])
    assert seeds_manifest(t1) == dict(
        canary=t1["canary"], tier="T1", seeds=[1, 2],
        lives=[dict(life="t1-g1", genre="G1", seed=1), dict(life="t1-g2", genre="G2", seed=2)])


@pytest.mark.parametrize("change", (
    {"sessions": 0}, {"sessions": 4}, {"distance": 3},
    {"sessions": 1, "distance": 0, "wake": "kill"},
    {"distance": 0, "wake": "kill"}, {"wake": "unknown"}, {"seed": True},
))
def test_micro_refusals(change):
    with pytest.raises(ValueError):
        MicroSpec(**(dict(genre="G2", seed=1, sessions=3, distance=1, wake="none", recipe="test") | change))


@pytest.mark.parametrize("old,new", (
    ("[kill]", "extra = 1\n[kill]"),
    ('tier = "T1"', 'tier = "T1"\n[restart]\nsession = 12'),
    ("session = 11", "session = 12"),
    ("wiring_only = true", "wiring_only = false"),
    ("window = 16384", "window = 16384.0"),
    ("window = 16384", "window = true"),
))
def test_tier_refusals(tmp_path, old, new):
    from bicentennial.world.targeted import PlacementError
    text = (ROOT / "tiers/life_specs/t1.toml").read_text(encoding="utf-8")
    path = tmp_path / "invalid.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(PlacementError, match="composition"):
        load_tier(path)


def test_hostable_promotion():
    module_spec = importlib.util.spec_from_file_location("s6a_life", ROOT / "spikes/s6a/life.py")
    spike = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(spike)
    for case in range(200):
        key = ("g17", "hostable", str(case))
        n = uniform_int("1", key, 0, "sessions", 1, 20)
        count = uniform_int("1", key, 0, "facts", 0, 30)
        facts = [dict(id=f"f-{i}", session=uniform_int("1", key, 0, f"session-{i}", 1, n))
                 for i in range(count)]
        result = spike.bundles_hostable(dict(sessions=list(range(n)), facts=facts))
        assert result["pairs_all_boundaries"] == sum(hostable(f["session"], j)
                                                      for f in facts for j in range(1, n + 1))
        assert result["pairs_end_of_life_only"] == sum(hostable(f["session"], n) for f in facts)
    t1 = build_schedule("1", "t1-g1", named("t1"))
    assert cold_restarts(t1) == tuple(range(2, 21))
    assert crosses_cold_restart(t1, 9, 10)
    assert not crosses_cold_restart(t1, 10, 10)
    assert crosses_cold_restart(t1, 19, 20)
    micro = build_schedule("1", "micro", named("t0-micro", sessions=1))
    assert not crosses_cold_restart(micro, 1, 1)


def test_import_purity():
    tree = ast.parse((ROOT / "src/bicentennial/world/targeted.py").read_text(encoding="utf-8"))
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess", "spikes",
                 "bicentennial.sandbox", "bicentennial.director", "bicentennial.genres.g1_software.repo")
    for node in ast.walk(tree):
        names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                 else [node.module] if isinstance(node, ast.ImportFrom) else [])
        assert not any(name and (name == f or name.startswith(f + ".")) for name in names for f in forbidden)
        assert not (isinstance(node, ast.Constant) and type(node.value) is float)


# These templates compute their gold and evidence directly from the generated rows.
@dataclass(frozen=True, kw_only=True, eq=False)
class RowTemplate(Template):
    checkpoint: int | None = None
    mode: str = "value"
    process: str = "incidental"
    target: str = "detail"
    part: str = "detail"
    index: int = 0
    candidate: str | None = None
    extra: bool = False

    def instances(self, db, schedule):
        from bicentennial.world.twin import plan_flip
        if self.candidate:
            candidates = []
            for fid, t in db.execute(
                    "SELECT f.id, min(e.t_sim) FROM fact f JOIN link l ON l.fact_id=f.id "
                    "JOIN event e ON e.id=l.event_id WHERE l.role='assert' GROUP BY f.id ORDER BY 2, 1"):
                session = next(p.index for p in schedule.sessions if t in p.turn_t)
                if not ((session <= 2) if self.candidate == "early" else (9 <= session <= 18)):
                    continue
                # Avoid two facts sharing an assertion/correction event or a surface.
                if db.execute("SELECT count(*) FROM link WHERE fact_id=?", (fid,)).fetchone()[0] != 1:
                    continue
                eid = db.execute("SELECT event_id FROM link WHERE fact_id=?", (fid,)).fetchone()[0]
                if db.execute("SELECT count(*) FROM link WHERE event_id=?", (eid,)).fetchone()[0] != 1:
                    continue
                try:
                    plan_flip(db, schedule, key=(self.template_id, "one"), twin_type="fork",
                              decisive_fact_id=fid, principal_id=db.execute(
                                  "SELECT actor_id FROM event WHERE id=?", (eid,)).fetchone()[0])
                except ValueError:
                    continue
                candidates.append(fid)
            fid = candidates[self.index]
        else:
            fid = mint(schedule, self.process, self.target, "fact", self.part, self.index)
        fact = db.execute("SELECT * FROM fact WHERE id=?", (fid,)).fetchone()
        spans = tuple(r[0] for r in db.execute(
            "SELECT event_id FROM link WHERE fact_id=? AND role='assert' ORDER BY event_id", (fid,)))
        answer, tokens = json.loads(fact["object"]), (fid,)
        if self.mode == "cancel":
            answer = "cancelled" if db.execute(
                "SELECT 1 FROM link WHERE fact_id=? AND role='retract'", (fid,)).fetchone() else "active"
        elif self.mode == "forget":
            requests = tuple(r[0] for r in db.execute("SELECT event_id, covered_fact_ids_json FROM forget_request")
                             if fid in json.loads(r[1]))
            spans += requests
            answer = "forgotten" if requests else "retained"
        elif self.mode == "correction":
            answer = "corrected" if fact["speech_act"] == "assert" else "hedged"
        if self.extra:
            # A genuine independence conflict on attempt 0; the recipe controls its presence.
            spans += tuple(r[0] for r in db.execute("SELECT canonical_name FROM entity WHERE id='overlap'"))
        if self.kind == "act":
            option = Option(key="gold", token_fact_ids=tokens, plan=dict(steps=[
                dict(tool=dict(name="set_entry", args=dict(value=answer)))]))
        else:
            option = Option(key="gold", token_fact_ids=tokens, envelope=dict(type="entity", value=answer))
        return (Instance(key="one", probe_point=self.checkpoint or len(schedule.sessions),
                         prompt="Record the remembered value.", options=(option,), gold_spans=spans,
                         decisive_fact_id=fid, decision_table_ref=(self.decision_tables[0]["table_id"]
                                                                if self.kind == "act" else None)),)


def row_template(tid, *, kind="qa", twin="fork", cell=None, **kwargs):
    tables = () if kind == "qa" else (dict(
        canary=CANARY, table_id=f"{tid}-v1", gold="act", timed=cell == "TUE-TIME",
        admissible=["gold_state"], disqualifiers=[], benign_extras=[]),)
    return RowTemplate(template_id=tid, version=1, cell_id=cell or ("DRIFT-CUR" if kind == "act" else "RECALL-VERB"),
                       kind=kind, twin_type=twin, direction="none", semantics="as_known",
                       decision_tables=tables, **kwargs)


def micro_templates():
    return (
        row_template("t-fork", kind="act", cell="KEEP-INC"),
        row_template("t-lure", kind="act", cell="TUE-TIME", twin="lure", mode="cancel",
                     process="commitments", target="duty", part="made"),
        row_template("t-forget", kind="act", cell="KEEP-FORGET", twin="trigger", mode="forget",
                     process="g2-forget", target="forget", part="fact"),
        row_template("t-hedge", twin="trigger", mode="correction", process="corrections",
                     target="chain", part="value", index=1),
        row_template("t-single", twin=None),
        row_template("t-g1", process="corrections", target="chain", part="value", index=1),
    )


def zero_mix():
    return Mix(deadlines=(), constraints=0, relaxed=0, decisions=0, chat_only=0,
               flags=0, constants=0, changed=0, mentions=(), endpoints=0, commitments=())


def micro_recipe(template):
    def build(db, schedule, placement):
        from bicentennial.genres.g2_assistant.world import (
            finish,
            write_entity,
            write_forget,
            write_people,
        )
        from bicentennial.world.processes import check_tokens
        from bicentennial.world.processes.commitments import (
            Commitment,
            write_commitments,
        )
        from bicentennial.world.processes.corrections import Chain, write_corrections
        from bicentennial.world.processes.incidental import Detail, write_details
        e, n = placement.evidence_session, len(schedule.sessions)
        if template.template_id == "t-g1":
            world = build_g1(db, schedule, mix=zero_mix())
            subject = db.execute("SELECT id FROM entity WHERE kind='constant' LIMIT 1").fetchone()
            # A zero mix contains just people; add the chain's subject explicitly.
            if subject is None:
                from bicentennial.world.db import insert_entity
                insert_entity(db, id="subject", kind="constant", canonical_name="retry limit", aliases_json=[],
                              created_t=schedule.sessions[0].t_start, retired_t=None)
                subject = ("subject",)
            write_corrections(db, schedule, [Chain(id="chain", subject=subject[0], key="value", stem="VALUE",
                                                 depth=1, at=((e - 1, 1), (e, 2)))], principal=world.principal)
            check_tokens(db)
            return world.principal
        people = write_people(db, schedule)
        p = people.principal
        places = tuple(write_entity(db, schedule, kind="place", key=f"place-{i}", name=f"Place {i}")
                       for i in range(4))
        if template.mode == "cancel":
            write_commitments(db, schedule, [Commitment(id="duty", subject=places[0], predicate="deliver",
                stem="DUTY", trigger="time", cancelled=True, made=(e, 1), due=(n, 1))], principal=p)
        elif template.mode == "forget":
            write_forget(db, schedule, key="forget", subject=people.people[0], covered=(("address", "ADDR"),),
                         neighbours=(("birthday", "BDAY"),), principal=p, summaries=0, at=((e - 1, 2), (e, 2)))
        elif template.mode == "correction":
            write_corrections(db, schedule, [Chain(id="chain", subject=places[0], key="value", stem="VALUE",
                                                 depth=1, at=((e - 1, 2), (e, 2)))], principal=p)
        else:
            write_details(db, schedule, [Detail(id="detail", subject=places[0], predicate="code", stem="CODE",
                decoys=places[1:], at=tuple((e, i) for i in range(1, 5)))], principal=p)
        finish(db, schedule, principal=p)
        return p
    return build


def test_micro_grid(tmp_path):
    import time

    from bicentennial.contracts.run import validate
    from bicentennial.world.targeted import micro_life
    singletons, timings = {}, []
    for template in micro_templates():
        vectors = [(3, 1, w) for w in ("none", "kill", "swap", "restart", "compaction", "gap")]
        if template.template_id in ("t-fork", "t-single"):
            vectors += [(1, 0, "none"), (2, 1, "none"), (3, 0, "none"), (3, 2, "none")]
        for sessions, distance, wake in vectors:
            spec = MicroSpec(genre="G1" if template.template_id == "t-g1" else "G2", seed=1,
                             sessions=sessions, distance=distance, wake=wake, recipe=template.template_id)
            start_cpu, start_wall = time.process_time(), time.perf_counter()
            life = micro_life(spec, template, micro_recipe(template), out_dir=tmp_path / f"life-{len(timings)}")
            cpu, wall = time.process_time() - start_cpu, time.perf_counter() - start_wall
            timings.append((cpu, wall))
            assert cpu < 1, (template.template_id, cpu)
            try:
                c = life.twin.compiled
                assert len(life.schedule.sessions) == sessions
                assert len(c.records) == 2 and len(c.bundles) == int(template.twin_type is not None)
                for name, values in (("item", c.items), ("bundle", c.bundles), ("item_record", c.records)):
                    for value in values:
                        validate(name, value)
                b0, = [r for r in c.records if r["branch"] == "B0"]
                assert b0["levers"]["distance_sessions"] == distance
                assert b0["evidence_session"] == sessions - distance
                if wake != "none":
                    assert all(r["evidence_session"] < sessions for r in c.records)
                if wake in ("kill", "compaction", "swap"):
                    assert all({"kill": "crash"}.get(wake, wake) in r["crossed"] for r in c.records)
                if c.bundles:
                    records = {r["item_id"]: r for r in c.records}
                    assert [records[i]["branch"] for i in c.bundles[0]["items"]] == ["B0", "B1"]
                assert not set(singletons) & life.singleton_lives.keys()
                singletons.update(life.singleton_lives)
                assert set(life.singleton_lives) == {r["item_id"] for r in c.records if r["bundle_id"] is None}
                assert all(value and "\n" not in value for value in life.singleton_lives.values())
                assert (life.out_dir / "life.json").is_file()
                assert json.loads((life.out_dir / "life.json").read_bytes())["seed"] == "1"
                assert all((life.out_dir / f"world.{b}.db").is_file() for b in ("B0", "B1"))
                for source in sorted((life.out_dir / "branches").iterdir()):
                    assert source.read_bytes() == (life.out_dir / source.name).read_bytes()
            finally:
                life.twin.b1.close()
    assert len(timings) == 44
    print("micro timing CPU/wall", timings, "maximum CPU", max(cpu for cpu, _ in timings))


def t1_templates(tier, genre):
    from dataclasses import replace
    names = tier["selection"][genre.lower()]
    templates = [row_template(names[0], candidate="early"), row_template(names[1], candidate="early", index=1),
                 row_template(names[2], candidate="late"),
                 row_template(names[3], kind="act", candidate="late", index=2),
                 row_template(names[4], twin=None, candidate="late", index=1)]
    if genre == "G1":
        # Enforce G14's actual depth-1 and selective-commit material as well.
        templates[0] = replace(templates[0], candidate=None, process="corrections", target="deadline-0",
                               part="value", index=1)
        templates[1] = replace(templates[1], candidate=None, process="corrections", target="deadline-1",
                               part="value", index=1)
    return tuple(templates)


def assert_untouched(db):
    for fid, opened, closed in db.execute("SELECT fact_id, window_open_t, window_close_t FROM commitment"):
        assert not db.execute("SELECT 1 FROM link l JOIN event e ON e.id=l.event_id "
                              "WHERE l.fact_id=? AND ?<=e.t_sim AND e.t_sim<=?", (fid, opened, closed)).fetchone()


def assert_t1(life, tier):
    from collections import Counter

    from bicentennial.canon import sha256_canon
    from bicentennial.genres.g1_software.diffs import (
        CALLS,
        EMPTY_TREE_HASH,
        expected_result,
        start_boundary,
    )
    from bicentennial.world import open_world
    assert life.schedule.fault_lite() == [dict(kind="kill", session=11, turn=1), dict(kind="swap", session=15, turn=None)]
    assert len(life.schedule.sessions) == 20 and life.schedule.scale.checkpoints == (10, 20)
    assert cold_restarts(life.schedule) == tuple(range(2, 21))
    c = life.twin.compiled
    records = {r["item_id"]: r for r in c.records}
    items = {i["item_id"]: i for i in c.items}
    counts = Counter()
    for r in c.records:
        item = items[r["item_id"]]
        assert item["probe_point"] - r["evidence_session"] >= 2
        assert any(r["evidence_session"] < s <= item["probe_point"] for s in range(2, 21))
        counts[r["branch"], item["probe_point"], r["twin_type"] is None or item["track"] == "Recall"] += 1
    assert {i["probe_point"] for i in c.items} == {10, 20}
    assert all(n <= (6 if qa else 2) for (_, _, qa), n in counts.items())
    assert len({r["bundle_id"] for r in c.records if r["branch"] == "B0" and r["bundle_id"]
                and r["evidence_session"] <= 2}) >= 2
    crossing = frozenset(b["bundle_id"] for b in c.bundles if all(
        records[i]["evidence_session"] is not None
        and any(records[i]["evidence_session"] < s <= items[i]["probe_point"] for s in range(2, 21))
        and items[i]["memory_tag"] == "memory_exclusive" for i in b["items"]))
    assert life.restart_crossing == crossing
    db0 = open_world(life.out_dir / "world.B0.db")
    try:
        for db in (db0, life.twin.b1):
            assert_untouched(db)
        state = expected_state(life.genre, life.schedule)(db0)
        if life.genre == "G2":
            assert all(v["repo_tree_hash"] == EMPTY_TREE_HASH for v in state.values())
        else:
            assert all(v["env_state_hash"] == sha256_canon({}) for v in state.values())
            calls, pairs = [], []
            for eid, t, payload in db0.execute("SELECT id, t_sim, payload_json FROM event WHERE kind='tool'"):
                s = next(p.index for p in life.schedule.sessions if t in p.turn_t)
                payload = json.loads(payload)
                tool = payload["tool"]
                for db in (db0, life.twin.b1):
                    assert expected_result(db, life.schedule, boundary=start_boundary(life.schedule, s), **tool) == payload["result"]
                assert [tuple(r) for r in db0.execute("SELECT * FROM link WHERE event_id=? ORDER BY fact_id", (eid,))] == [
                    tuple(r) for r in life.twin.b1.execute("SELECT * FROM link WHERE event_id=? ORDER BY fact_id", (eid,))]
                if s == 1:
                    from bicentennial.canon import canon
                    calls.append(canon((tool["name"], tool["args"])))
                else:
                    pairs.append((s, t))
            assert sorted(calls) == sorted(canon(call) for call in CALLS)
            assert pairs == [(11, life.schedule.sessions[10].turn_t[0])]
    finally:
        db0.close()


def test_t1_lives(tmp_path):
    from bicentennial.world.targeted import t1_lives
    tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
    lives = t1_lives(tier, {g: t1_templates(tier, g) for g in ("G1", "G2")}, root=tmp_path)
    try:
        for life in lives:
            assert_t1(life, tier)
    finally:
        for life in lives:
            life.twin.b1.close()


def test_redraw_and_unchanged_builder(tmp_path):
    from bicentennial.genres.g2_assistant.world import finish
    from bicentennial.world.db import insert_entity
    from bicentennial.world.processes.incidental import Detail, write_details
    from bicentennial.world.targeted import generate
    from bicentennial.world.twin import IndependenceError
    spec = MicroSpec(genre="G2", seed=1, sessions=3, distance=1, wake="none", recipe="redraw")
    a = row_template("first")
    b = row_template("second", target="second", extra=True)
    calls = []

    def recipe(db, schedule, placement):
        calls.append(placement)
        p = micro_recipe(a)(db, schedule, placement)
        places = tuple(r[0] for r in db.execute("SELECT id FROM entity WHERE kind='place' ORDER BY id"))
        write_details(db, schedule, [Detail(id="second", subject=places[0], predicate="other", stem="OTHER",
                      decoys=places[1:], at=((2, 1), (2, 2), (2, 3), (2, 4)))], principal=p)
        event = mint(schedule, "incidental", "detail" if placement.attempt == 0 else "second", "event", "detail", 0)
        insert_entity(db, id="overlap", kind="place", canonical_name=event, aliases_json=[], created_t=0, retired_t=None)
        finish(db, schedule, principal=p)
        return p

    result = generate(spec, (a, b), recipe, out_dir=tmp_path / "redraw")
    try:
        assert result.attempt == 1 and len(calls) == 2
        assert calls[0].rejected == () and calls[1].rejected
        assert len(result.twin.compiled.bundles) == 2
    finally:
        result.twin.b1.close()
    calls.clear()

    def ignores_attempt(db, schedule, placement):
        from dataclasses import replace
        return recipe(db, schedule, replace(placement, attempt=0))

    failed = tmp_path / "unchanged"
    with pytest.raises(IndependenceError):
        generate(spec, (a, b), ignores_attempt, out_dir=failed)
    assert len(calls) == 2 and not failed.exists()


def test_micro_identity_and_existing_directory(tmp_path):
    from bicentennial.world.targeted import micro_life
    template = micro_templates()[0]
    spec = MicroSpec(genre="G2", seed=1, sessions=3, distance=1, wake="none", recipe="refused")
    exists = tmp_path / "exists"
    exists.mkdir()
    sentinel = exists / "sentinel"
    sentinel.write_text("retained", encoding="utf-8")
    with pytest.raises(ValueError):
        micro_life(spec, template, micro_recipe(template), out_dir=exists)
    assert sentinel.read_text(encoding="utf-8") == "retained"

    def wrong_genre(db, schedule, placement):
        db.execute("DROP TRIGGER meta_UPDATE")
        db.execute("UPDATE meta SET genre='G1'")
        return micro_recipe(template)(db, schedule, placement)

    failed = tmp_path / "wrong-genre"
    with pytest.raises(ValueError):
        micro_life(spec, template, wrong_genre, out_dir=failed)
    assert not failed.exists()


def test_untouched_refusal(tmp_path):
    from bicentennial.world.db import insert_link
    from bicentennial.world.targeted import PlacementError, micro_life
    template = micro_templates()[1]
    spec = MicroSpec(genre="G2", seed=1, sessions=3, distance=1, wake="none", recipe="touch")

    def touched(db, schedule, placement):
        p = micro_recipe(template)(db, schedule, placement)
        fid, opened = db.execute("SELECT fact_id, window_open_t FROM commitment").fetchone()
        eid = db.execute("SELECT id FROM event WHERE t_sim=? ORDER BY id LIMIT 1", (opened,)).fetchone()[0]
        insert_link(db, event_id=eid, fact_id=fid, role="mention")
        return p

    failed = tmp_path / "touched"
    with pytest.raises(PlacementError, match="untouched"):
        micro_life(spec, template, touched, out_dir=failed)
    assert not failed.exists()


def test_t1_selection_refusals(tmp_path):
    from dataclasses import replace

    from bicentennial.world.targeted import t1_life
    tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
    row = tier["lives"][1]
    templates = t1_templates(tier, "G2")
    no_checkpoint = Template(template_id=templates[0].template_id, version=1, cell_id="RECALL-VERB", kind="qa",
                             twin_type="fork", direction="none", semantics="as_known")
    forgotten = replace(row_template(templates[0].template_id, kind="act", cell="KEEP-FORGET"), twin_type="trigger")
    for i, bad in enumerate(((no_checkpoint, *templates[1:]), (forgotten, *templates[1:]), templates[1:])):
        failed = tmp_path / f"selection-{i}"
        with pytest.raises(ValueError):
            t1_life(tier, row, bad, out_dir=failed)
        assert not failed.exists()


@pytest.mark.parametrize("rule", ("hostable", "early", "reads"))
def test_t1_postconditions_and_cleanup(tmp_path, monkeypatch, rule):
    from dataclasses import replace

    import bicentennial.world.targeted as targeted
    tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
    row = tier["lives"][0 if rule == "reads" else 1]
    templates = list(t1_templates(tier, row["genre"]))
    if rule == "hostable":
        # Session 19 is too late even at the final checkpoint.
        templates[-1] = replace(templates[-1], candidate=None, target="too-late", index=0)
        original_build = targeted._build_t1
        def too_late(path, schedule, **kwargs):
            from bicentennial.genres.g2_assistant.world import finish
            from bicentennial.world.processes.incidental import Detail, write_details
            db, principal = original_build(path, schedule, **kwargs)
            places = tuple(r[0] for r in db.execute("SELECT id FROM entity WHERE kind='place' ORDER BY id"))
            write_details(db, schedule, [Detail(id="too-late", subject=places[0], predicate="late", stem="LATE",
                          decoys=places[1:4], at=((19, 1), (19, 2), (19, 3), (19, 4)))], principal=principal)
            finish(db, schedule, principal=principal)
            return db, principal
        monkeypatch.setattr(targeted, "_build_t1", too_late)
    elif rule == "early":
        templates[1] = replace(templates[1], candidate="late", index=3)
    else:
        original = targeted.expected_result
        def unequal(db, *args, **kwargs):
            result = original(db, *args, **kwargs)
            filename = db.execute("PRAGMA database_list").fetchone()[2]
            return result | {"extra": "different"} if filename.endswith("world.B1.db") else result
        monkeypatch.setattr(targeted, "expected_result", unequal)
    failed = tmp_path / rule
    with pytest.raises(targeted.PlacementError) as error:
        targeted.t1_life(tier, row, templates, out_dir=failed)
    assert error.value.rule == rule
    assert not failed.exists()


def test_wrong_canary(tmp_path):
    text = (ROOT / "tiers/life_specs/t1.toml").read_text(encoding="utf-8")
    source_canary = json.loads((ROOT / "schemas/item.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
    path = tmp_path / "wrong.toml"
    path.write_text(text.replace(source_canary, "wrong"), encoding="utf-8")
    with pytest.raises(ValueError):
        load_tier(path)


def test_manifest_determinism_and_fresh_import(tmp_path):
    import subprocess
    import sys
    script = '''
import json, runpy, sys
from pathlib import Path
from bicentennial.canon import canon
from bicentennial.world.targeted import MicroSpec, load_tier, micro_life, t1_life
assert "bicentennial.genres.g1_software.repo" not in sys.modules
m = runpy.run_path("tests/world/test_targeted.py")
t = m["micro_templates"]()[0]
s = MicroSpec(genre="G2", seed=1, sessions=3, distance=1, wake="none", recipe="t-fork")
a = micro_life(s, t, m["micro_recipe"](t), out_dir=Path(sys.argv[1]) / "micro")
tier = load_tier("tiers/life_specs/t1.toml")
b = t1_life(tier, tier["lives"][1], m["t1_templates"](tier, "G2"), out_dir=Path(sys.argv[1]) / "t1")
print(canon([a.manifest, b.manifest]).decode())
a.twin.b1.close()
b.twin.b1.close()
'''
    outputs = []
    for seed in ("0", "random"):
        result = subprocess.run([sys.executable, "-c", script, str(tmp_path / seed)], cwd=ROOT,
                                env={"PYTHONHASHSEED": seed}, capture_output=True)
        assert result.returncode == 0, result.stderr.decode()
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_t1_g1_selected_material(tmp_path):
    from dataclasses import asdict

    from bicentennial.world import open_world
    from bicentennial.world.targeted import t1_life
    tier = load_tier(ROOT / "tiers/life_specs/t1.toml")
    templates = (
        row_template("drift-chain", kind="act", process="corrections", target="deadline-0", part="value", index=1),
        row_template("drift-chain-fault", kind="act", process="corrections", target="deadline-1", part="value", index=1),
        row_template("drift-config", kind="act", twin="trigger", mode="correction", process="corrections",
                     target="setting-fix", part="value", index=1),
        row_template("recall-value", twin=None, process="g1_software", target="decision-0", part="value"),
        row_template("wake-loop", kind="act", cell="WAKE-LOOP", process="g1_software", target="decision-1", part="value"),
    )
    templates = (NoCrash(**asdict(templates[0])), *templates[1:])
    life = t1_life(tier, tier["lives"][0], templates, out_dir=tmp_path / "material")
    db0 = open_world(life.out_dir / "world.B0.db")
    try:
        assert_t1(life, tier)
        for chain in ("deadline-0", "deadline-1", "setting-fix"):
            facts = tuple(mint(life.schedule, "corrections", chain, "fact", "value", i) for i in range(2))
            assert not db0.execute("SELECT 1 FROM fact WHERE id=?", (
                mint(life.schedule, "corrections", chain, "fact", "value", 2),)).fetchone()
            if chain == "setting-fix":
                assert db0.execute("SELECT count(*) FROM fact_surface WHERE fact_id=?", (facts[0],)).fetchone()[0] == 1
                assert not db0.execute("SELECT 1 FROM fact_surface WHERE fact_id=?", (facts[1],)).fetchone()
                assert life.twin.b1.execute("SELECT speech_act FROM fact WHERE id=?", (facts[1],)).fetchone()[0] == "hedge"
            else:
                assert not db0.execute("SELECT 1 FROM fact_surface WHERE fact_id IN (?,?)", facts).fetchone()
        for target in ("decision-0", "decision-1"):
            fid = mint(life.schedule, "g1_software", target, "fact", "value", 0)
            assert not db0.execute("SELECT 1 FROM fact_surface WHERE fact_id=?", (fid,)).fetchone()
    finally:
        db0.close()
        life.twin.b1.close()


@dataclass(frozen=True, kw_only=True, eq=False)
class NoCrash(RowTemplate):
    """G14's ordinary chain is valid at 10 and refuses a crash-crossing probe at 20."""

    def instances(self, db, schedule):
        entries = super().instances(db, schedule)
        for entry in entries:
            positions = [db.execute("SELECT t_sim FROM event WHERE id=?", (eid,)).fetchone()[0]
                         for eid in entry.gold_spans]
            kills = [p.turn_t[r["turn"] - 1] for p in schedule.sessions if p.index <= entry.probe_point
                     for r in p.fault_points if r["kind"] == "kill"]
            if any(t <= kill for t in positions for kill in kills):
                raise ValueError(self.template_id)
        return entries
