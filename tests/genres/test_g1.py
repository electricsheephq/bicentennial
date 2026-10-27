"""G05 G1 software-partner world: the tidewater golden one-for-one, keyed exact counts over 200 seeds, diffs."""

import ast
import json
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from itertools import count
from pathlib import Path
from zoneinfo import available_timezones

import pytest

import bicentennial.genres.g1_software.world as g1
from bicentennial.genres.g1_software.codebase_model import (
    COMMIT_LAG_S,
    OPS,
    PATHS,
    diffs,
    state_at,
    write_commit,
)
from bicentennial.genres.g1_software.world import (
    GENERATOR_VERSION,
    GENRE,
    MIX,
    PROCESS,
    TEAM_NAMES,
    ZONES,
    Mix,
    Statement,
    build_g1,
    build_golden,
    golden_schedule,
    load_golden,
    tail_filler,
    world_meta,
    write_statements,
)
from bicentennial.world import (
    as_known,
    as_valid,
    create_world,
    export_jsonl,
    export_world,
    world_hash,
)
from bicentennial.world.db import (
    insert_entity,
    insert_event,
    insert_fact,
    insert_link,
    insert_locked_token,
)
from bicentennial.world.processes import HARD, SOFT, check_tokens, mint
from bicentennial.world.scale import WORLD_TZ, named
from bicentennial.world.schedule import build_schedule, write_sessions

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "fixtures" / "g1_golden_tidewater.toml"
MICRO = json.loads((ROOT / "spikes" / "s6a" / "micro_life.json").read_text(encoding="utf-8"))
GOLDEN_HASH = "5e897e65475117634d1b9b9be4f753c4a7b8d0a22e062dea9a6d4af73a0340ae"
SEEDS = [f"g05-{c}" for c in range(200)]
LIFE = "life-a"
WORLDS = count()
EXPLICIT = ["6432", "6543", "release/ember", "Python 3.12", "JSON lines", "defaults to off", "under 50 characters"]


def new_db(tmp, seed, sessions, meta=None):
    return create_world(tmp / f"w{next(WORLDS)}.db", meta or world_meta(seed, sessions))


def keyed_world(tmp, seed, mix=MIX, scale=None):
    schedule = build_schedule(seed, LIFE, scale or named("t1"))
    db = new_db(tmp, seed, len(schedule.sessions))
    return db, schedule, build_g1(db, schedule, mix=mix)


def golden_world(tmp, seed=None):
    golden = load_golden(FIXTURE)
    schedule = golden_schedule(golden, seed=seed)
    db = new_db(tmp, schedule.seed, len(schedule.sessions))
    return db, schedule, build_golden(db, golden, schedule)


def scalar(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def asserting(db, fact_id):
    rows = db.execute("SELECT e.* FROM link l JOIN event e ON e.id = l.event_id "
                      "WHERE l.fact_id = ? AND l.role = 'assert'", (fact_id,)).fetchall()
    assert len(rows) == 1
    return rows[0]


def session_of(schedule, t):
    return next(p.index for p in schedule.sessions if p.t_start <= t < p.t_end)


def kind_of(db, fact_id):
    return scalar(db, "SELECT s.kind FROM fact f JOIN entity s ON s.id = f.subject_id WHERE f.id = ?", fact_id)


@pytest.fixture(scope="module")
def keyed(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("keyed")
    return [(seed, *keyed_world(tmp, seed)) for seed in SEEDS]


@pytest.fixture(scope="module")
def golden(tmp_path_factory):
    return golden_world(tmp_path_factory.mktemp("golden"))


# --- the tidewater golden ---------------------------------------------------------------------------------------

def test_golden_one_for_one(golden):
    db, schedule, mapping = golden
    facts = {f["id"]: f for f in MICRO["facts"]}
    assert set(mapping) == set(facts) and list(mapping) == sorted(mapping)
    events = {mid: asserting(db, mapping[mid]) for mid in facts}
    for mid, f in facts.items():
        e, fid = events[mid], mapping[mid]
        assert session_of(schedule, e["t_sim"]) == f["session"]
        retracts = [r[0] for r in db.execute("SELECT fact_id FROM link WHERE event_id = ? AND role = 'retract'",
                                             (e["id"],))]
        row = db.execute("SELECT * FROM commitment WHERE fact_id = ?", (fid,)).fetchone()
        if f["kind"] == "fact":
            assert retracts == [] and row is None
        elif f["kind"] == "correction":
            assert retracts == [mapping[f["supersedes"]]] and row is None
        else:
            plan = schedule.sessions[f["due_session"] - 1]
            assert (row["trigger_kind"], row["lures_json"]) == ("event", "[]")
            assert (row["window_open_t"], row["window_close_t"]) == (plan.t_start, plan.t_end)
        if f["kind"] != "commitment":
            assert scalar(db, "SELECT value FROM locked_token WHERE fact_id = ?", fid) in f["text"]
    # The only retraction is F1b's; the only other fact is C1's cue.
    assert [tuple(r) for r in db.execute("SELECT event_id, fact_id FROM link WHERE role = 'retract'")] == [
        (events["F1b"]["id"], mapping["F1"])]
    others = {r[0] for r in db.execute("SELECT id FROM fact")} - set(mapping.values())
    assert others == {mint(schedule, "commitments", "C1", "fact", "cue", 0)}
    assert schedule.wakes() == [("kill", 5, 2), ("gap", 8, None)]
    assert schedule.fault_lite() == [{"kind": "kill", "session": 5, "turn": 2}]
    for s, plan in zip(MICRO["sessions"], schedule.sessions, strict=True):
        assert len(plan.turn_t) == len(s["turns"])
        kill = [r["turn"] for r in plan.fault_points if r["kind"] == "kill"]
        assert s.get("restart_after_turn") == (kill[0] if kill else None)
        assert s.get("long_session", False) == plan.long_sprint
        assert s.get("gap_before", False) == ("gap" in plan.wake_before)
    ev = MICRO["events"]
    assert schedule.sessions[ev["restart_wake"]["session"] - 1].fault_points[0]["turn"] == ev["restart_wake"]["after_turn"]
    assert "gap" in schedule.sessions[ev["long_gap"]["before_session"] - 1].wake_before
    assert schedule.sessions[ev["long_session"]["session"] - 1].long_sprint


def test_golden_rows(golden):
    db, schedule, mapping = golden
    counts = {t: scalar(db, f"SELECT count(*) FROM {t}") for t in (
        "entity", "session", "event", "fact", "locked_token", "link", "attr", "commitment", "fact_surface",
        "plant", "forget_request", "lineage")}
    assert counts == {"entity": 9, "session": 10, "event": 60, "fact": 9, "locked_token": 9, "link": 11, "attr": 7,
                      "commitment": 1, "fact_surface": 0, "plant": 0, "forget_request": 0, "lineage": 0}
    assert dict(db.execute("SELECT role, count(*) FROM link GROUP BY role").fetchall()) == {
        "assert": 9, "retract": 1, "mention": 1}
    assert scalar(db, "SELECT count(*) FROM event WHERE id IN (SELECT event_id FROM link)") == 9
    assert scalar(db, "SELECT count(*) FROM attr WHERE valid_to_t IS NULL") == 6
    assert diffs(db) == ()
    values = sorted(v for (v,) in db.execute("SELECT value FROM locked_token"))
    minted = [v for v in values if v not in EXPLICIT]
    assert sorted(set(values) - set(minted)) == sorted(EXPLICIT) and len(minted) == 2
    assert any(re.fullmatch(r"ROTATION-[0-9]{6}", v) for v in minted)
    assert any(re.fullmatch(r"FREEZE-[0-9]{6}", v) for v in minted)
    staging = mint(schedule, PROCESS, "entities", "entity", "staging_db", 0)
    t = asserting(db, mapping["F1b"])["t_sim"]
    for f in (as_valid, as_known):
        assert f(db, staging, "port", t - 1) == "6432"
        assert f(db, staging, "port", t) == f(db, staging, "port", schedule.sessions[-1].t_end) == "6543"
    slots = sorted(t for plan in schedule.sessions for t in plan.turn_t)
    assert sorted(t for (t,) in db.execute("SELECT t_sim FROM event")) == slots and len(slots) == 60
    assert [len(p.turn_t) for p in schedule.sessions] == [5, 5, 5, 5, 5, 15, 5, 5, 5, 5]
    assert schedule.sessions[7].gap_before_s == 1_814_400 and schedule.sessions[5].min_tokens == 20_480
    assert schedule.tz == WORLD_TZ and schedule.scale.name == "tidewater"
    assert world_hash(db) == GOLDEN_HASH


def test_golden_filler_counts(tmp_path, monkeypatch):
    seen = {}

    def spy(name, fn):
        def wrapped(*args, **kwargs):
            seen[name] = fn(*args, **kwargs)
            return seen[name]
        monkeypatch.setattr(g1, name, wrapped)

    spy("tail_filler", g1.tail_filler)
    spy("write_filler", g1.write_filler)
    db, schedule, _ = golden_world(tmp_path)
    assert seen == {"tail_filler": 10, "write_filler": 41}
    assert tail_filler(db, schedule, principal=mint(schedule, PROCESS, "entities", "entity", "lead", 0)) == 0


def edit(tmp_path, old, new):
    text = FIXTURE.read_text(encoding="utf-8")
    assert old in text
    path = tmp_path / f"g{next(WORLDS)}.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize("old, new", [
    ('principal = "lead"\n', 'principal = "lead"\nextra = 1\n'),
    ("long_gap_s = 1814400\n", "long_gap_s = 1814400\nextra = 1\n"),
    ('token_kind = "name"\n', 'token_kind = "name"\nextra = 1\n'),
    ('life = "tidewater"\n', ""),
    ("long_gap_s = 1814400\n", ""),
    ('due = [7, 1]\n', ""),
    ('subject = "ci"', 'subject = "nobody"'),
    ('sender = "lead"', 'sender = "nobody"'),
    ('principal = "lead"', 'principal = "nobody"'),
    ('fact = "F6"', 'fact = "F2"'),
    ('fact = "C1"', 'fact = "F1b"'),
    ('trigger = "event"', 'trigger = "time"'),
    ('lead = ["person", "lead developer"]', 'lead = ["person", ""]'),
    ('lead = ["person", "lead developer"]', 'lead = ["person"]'),
], ids=["extra-top", "extra-schedule", "extra-statement", "missing-top", "missing-schedule", "missing-commitment",
        "undeclared-subject", "undeclared-sender", "undeclared-principal", "repeated-fact", "repeated-chain-fact",
        "trigger", "empty-name", "one-string"])
def test_load_golden_refusals(tmp_path, old, new):
    with pytest.raises(ValueError):
        load_golden(edit(tmp_path, old, new))


@pytest.mark.parametrize("change", [
    {"turns": (5,) * 9}, {"sessions": 1, "turns": (5,)}, {"turns": (4,) + (5,) * 9}, {"turns": (7,) + (5,) * 9},
    {"kill": (5, 0)}, {"kill": (5, 5)}, {"kill": (11, 1)}, {"sprint": 1}, {"sprint": 11}, {"long_gap": 1},
    {"sprint": 5}, {"long_gap": 6}, {"long_gap_s": 604_799}, {"long_gap_s": 1_814_401},
    {"checkpoints": (5, 5, 10)}, {"checkpoints": (9,)}, {"checkpoints": (0, 10)}, {"checkpoints": ()},
], ids=["turns-length", "one-session", "few-turns", "turns-not-dividing", "kill-turn-0", "kill-last-turn",
        "kill-session", "sprint-1", "sprint-over", "long-gap-1", "sprint-at-kill", "long-gap-at-sprint",
        "gap-short", "gap-long", "checkpoints-repeat", "checkpoints-end", "checkpoints-zero", "checkpoints-empty"])
def test_golden_schedule_refusals(change):
    golden = load_golden(FIXTURE)
    golden_schedule(golden)
    with pytest.raises(ValueError):
        golden_schedule(replace(golden, schedule=golden.schedule | change))


def test_golden_schedule_kill_in_long_session():
    golden = load_golden(FIXTURE)
    schedule = golden_schedule(replace(golden, schedule=golden.schedule | {"kill": (6, 14), "sprint": 5}))
    assert schedule.fault_lite() == [{"kind": "kill", "session": 6, "turn": 14}]


def test_build_golden_refusals(tmp_path):
    golden = load_golden(FIXTURE)
    schedule = golden_schedule(golden)
    db = new_db(tmp_path, golden.seed, 10)
    write_sessions(db, schedule)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        build_golden(db, golden, schedule)
    assert export_jsonl(db) == before
    for meta, life in ((world_meta("6102", 10), golden.life), (world_meta(golden.seed, 10) | {"genre": "G2"}, golden.life),
                       (world_meta(golden.seed, 10) | {"generator_version": "g1-0.0"}, golden.life),
                       (world_meta(golden.seed, 10), "other")):
        db = new_db(tmp_path, None, None, meta)
        before = export_jsonl(db)
        with pytest.raises(ValueError):
            build_golden(db, golden, replace(schedule, life=life))
        assert export_jsonl(db) == before


# --- keyed lives ------------------------------------------------------------------------------------------------

def check_counts(db, schedule, world, mix_n=None):
    n = len(world.team)
    nonfiller = scalar(db, "SELECT count(*) FROM event WHERE kind != 'filler'")
    assert scalar(db, "SELECT count(*) FROM entity") == n + 22
    assert scalar(db, "SELECT count(*) FROM fact") == scalar(db, "SELECT count(*) FROM locked_token") == n + 30
    assert (nonfiller, scalar(db, "SELECT count(*) FROM event WHERE kind = 'commit'")) == (n + 39, 9)
    assert dict(db.execute("SELECT role, count(*) FROM link GROUP BY role").fetchall()) == {
        "assert": n + 30, "retract": 6, "mention": 11}
    assert scalar(db, "SELECT count(*) FROM attr") == n + 21
    assert scalar(db, "SELECT count(*) FROM attr WHERE valid_to_t IS NULL") == n + 16
    assert [tuple(r) for r in db.execute("SELECT surface, count(*) FROM fact_surface GROUP BY surface")] == [("repo", 9)]
    assert scalar(db, "SELECT count(*) FROM commitment") == 2
    assert sum(len(json.loads(r[0])) for r in db.execute("SELECT lures_json FROM commitment")) == 2
    assert scalar(db, "SELECT count(*) FROM fact WHERE polarity = 'negate'") == 1
    assert Counter(d.op for d in diffs(db)) == {"add_flag": 2, "add_constant": 2, "change_constant": 1,
                                                "add_endpoint": 2, "record_decision": 2}
    retracted = Counter((r[0], r[1]) for r in db.execute(
        "SELECT f.subject_id, f.predicate FROM link l JOIN fact f ON f.id = l.fact_id WHERE l.role = 'retract'"))
    assert Counter(retracted.values()) == {1: 4, 2: 1}
    slots = {t for plan in schedule.sessions for t in plan.turn_t}
    occupied = {t for (t,) in db.execute("SELECT t_sim FROM event WHERE kind != 'filler'")}
    assert {t for (t,) in db.execute("SELECT t_sim FROM event")} == slots and occupied <= slots
    assert scalar(db, "SELECT count(*) FROM event WHERE kind = 'filler'") == len(slots) - len(occupied)
    return n


def test_keyed_exact_counts(keyed):
    sizes = {check_counts(db, schedule, world) for _, db, schedule, world in keyed}
    assert sizes == {3, 4, 5}
    assert all(len({t for p in s.sessions for t in p.turn_t}) == 100 for _, _, s, _ in keyed)


def test_team(keyed):
    assert ZONES[0] == WORLD_TZ and len(set(ZONES)) == len(ZONES)
    for _, db, schedule, world in keyed:
        assert world.principal == world.team[0]
        zones = {}
        for subject, kind, name in db.execute("SELECT id, kind, canonical_name FROM entity WHERE kind = 'person'"):
            assert kind == "person" and name in TEAM_NAMES
            zones[subject] = as_valid(db, subject, "time_zone", schedule.sessions[-1].t_end)
        assert set(zones) == set(world.team) and len(set(zones.values())) == len(world.team)
        assert set(zones.values()) <= available_timezones() and zones[world.principal] == "Europe/Paris"
        tokens = [r[0] for r in db.execute("SELECT t.kind FROM fact f JOIN locked_token t ON t.fact_id = f.id "
                                           "WHERE f.predicate = 'time_zone'")]
        assert tokens == ["name"] * len(world.team)


def test_chat_only_and_constraints(keyed):
    for _, db, _, world in keyed:
        commits = {r[0]: r[1] for r in db.execute(
            "SELECT l.fact_id, e.t_sim FROM link l JOIN event e ON e.id = l.event_id WHERE e.kind = 'commit'")}
        decisions = [r[0] for r in db.execute(
            "SELECT f.id FROM fact f JOIN entity s ON s.id = f.subject_id WHERE s.kind = 'decision'")]
        surfaces = {f: [tuple(r) for r in db.execute("SELECT surface, from_t FROM fact_surface WHERE fact_id = ?",
                                                     (f,))] for f in decisions}
        chat_only = [f for f in decisions if not surfaces[f]]
        assert len(chat_only) == MIX.chat_only and not set(chat_only) & set(commits)
        assert all(surfaces[f] == [("repo", commits[f])] for f in decisions if f not in chat_only)
        for fid, surface, t in db.execute("SELECT * FROM fact_surface"):
            assert surface == "repo" and commits[fid] == t
        for (fid,) in db.execute("SELECT f.id FROM fact f JOIN entity s ON s.id = f.subject_id "
                                 "WHERE s.kind = 'constraint'"):
            e = asserting(db, fid)
            assert (e["kind"], e["channel"], e["actor_id"]) == ("statement", "chat", world.principal)
            assert fid not in commits


def test_diffs(keyed):
    for _, db, schedule, world in keyed:
        found, last = diffs(db), {}
        assert len(found) == 9 and {d.op for d in found} <= set(OPS)
        assert [(d.t, d.event_id) for d in found] == sorted((d.t, d.event_id) for d in found)
        for d in found:
            statement = asserting(db, d.fact_id)
            assert COMMIT_LAG_S == 0 and d.t == statement["t_sim"] + COMMIT_LAG_S
            assert statement["kind"] == "statement" and statement["id"] != d.event_id
            plan = schedule.sessions[session_of(schedule, d.t) - 1]
            assert plan.turn_t.index(d.t) == plan.turn_t.index(statement["t_sim"])
            assert as_valid(db, d.entity_id, d.key, d.t) == d.after and d.path == PATHS[kind_of(db, d.fact_id)]
            assert d.before == last.get((d.entity_id, d.key)) and d.author_id in world.team
            assert scalar(db, "SELECT canonical_name FROM entity WHERE id = ?", d.entity_id) == d.name
            last[(d.entity_id, d.key)] = d.after
        names = {(d.entity_id, d.key): (d.path, d.name) for d in found}
        times = {t for (t,) in db.execute("SELECT t_sim FROM event WHERE kind = 'statement'")}
        for t in sorted(times | {p.t_end for p in schedule.sessions}):
            state = state_at(db, t)
            assert list(state) == sorted(PATHS.values())
            expected = {path: {} for path in state}
            for (entity, key), (path, name) in names.items():
                if (value := as_valid(db, entity, key, t)) is not None:
                    expected[path][name] = value
            assert state == expected


def test_commits_sort_after_statements(keyed, golden):
    worlds = [golden[:2], *((db, schedule) for _, db, schedule, _ in keyed)]
    checked = 0
    for db, _ in worlds:
        for commit in db.execute("SELECT id, t_sim FROM event WHERE kind = 'commit'"):
            fact_id = scalar(db, "SELECT fact_id FROM link WHERE event_id = ?", commit["id"])
            statement = asserting(db, fact_id)
            assert commit["t_sim"] == statement["t_sim"]
            assert (statement["t_sim"], statement["id"]) < (commit["t_sim"], commit["id"])
            checked += 1
    assert checked == 200 * 9


def tiny(tmp_path, *, channel="commit", links=1, second=False):
    db = new_db(tmp_path, "tiny", 1)
    insert_entity(db, id="P", kind="person", canonical_name="Heron", aliases_json=[], created_t=0, retired_t=None)
    insert_entity(db, id="F", kind="flag", canonical_name="quiet_retry", aliases_json=[], created_t=0, retired_t=None)
    for i in range(2):
        insert_event(db, id=f"s{i}", t_sim=i, kind="statement", channel="chat", actor_id="P", audience_json=["agent"],
                     visibility="shared", salience=500, payload_json={})
        insert_fact(db, id=f"f{i}", subject_id="F", predicate="default", object=f"FLAG-11111{i}", polarity="affirm",
                    modality="stated", strength=1000, speech_act="assert")
        insert_locked_token(db, token_id=f"k{i}", fact_id=f"f{i}", kind="code", value=f"FLAG-11111{i}")
        insert_link(db, event_id=f"s{i}", fact_id=f"f{i}", role="assert")
    for i in range(1 + second):
        insert_event(db, id=f"c{i}", t_sim=i, kind="commit", channel=channel, actor_id="P", audience_json=["agent"],
                     visibility="shared", salience=500, payload_json={})
        insert_link(db, event_id=f"c{i}", fact_id=f"f{i}", role="mention")
    if links == 2:
        insert_link(db, event_id="c0", fact_id="f1", role="mention")
    return db


def test_diff_refusals(tmp_path):
    assert [(d.op, d.before, d.after) for d in diffs(tiny(tmp_path))] == [("add_flag", None, "FLAG-111110")]
    for kwargs in ({"links": 2}, {"second": True}, {"channel": "chat"}):
        with pytest.raises(ValueError):
            diffs(tiny(tmp_path, **kwargs))
    db = tiny(tmp_path)
    insert_event(db, id="x", t_sim=5, kind="statement", channel="commit", actor_id="P", audience_json=["agent"],
                 visibility="shared", salience=500, payload_json={})
    with pytest.raises(ValueError):
        diffs(db)


def test_write_commit_refusals(tmp_path):
    db, schedule, world = keyed_world(tmp_path, "g05-0")
    constraint = next(f for (f,) in db.execute("SELECT id FROM fact") if kind_of(db, f) == "constraint")
    flag = next(f for (f,) in db.execute("SELECT id FROM fact") if kind_of(db, f) == "flag")
    milestone = next(e for (e,) in db.execute("SELECT id FROM entity WHERE kind = 'milestone'"))
    before = export_jsonl(db)
    for fact_id, author in ((constraint, world.principal), (flag, milestone), ("missing", world.principal)):
        with pytest.raises(ValueError):
            write_commit(db, schedule, unit_id="extra", n=0, fact_id=fact_id, author=author)
    assert export_jsonl(db) == before


# --- whole worlds -----------------------------------------------------------------------------------------------

def check_whole(db, schedule, *, principal, team, notice_actors=None):
    check_tokens(db)
    cancel_facts = {r[0] for r in db.execute(
        "SELECT a.fact_id FROM link a JOIN link r ON r.event_id = a.event_id "
        "JOIN commitment c ON c.fact_id = r.fact_id JOIN fact original ON original.id = c.fact_id "
        "JOIN fact cancel ON cancel.id = a.fact_id WHERE a.role = 'assert' AND r.role = 'retract' "
        "AND cancel.subject_id = original.subject_id AND cancel.predicate = original.predicate")}
    for fact in db.execute("SELECT * FROM fact").fetchall():
        asserting(db, fact["id"])
        tokens = [r[0] for r in db.execute("SELECT value FROM locked_token WHERE fact_id = ?", (fact["id"],))]
        shape = (fact["speech_act"], fact["strength"], fact["polarity"])
        allowed = {("assert", HARD, "affirm"), ("hedge", SOFT, "affirm"), ("quote", HARD, "affirm")}
        if fact["id"] in cancel_facts:
            assert kind_of(db, fact["id"]) == "commitment"
            allowed = {("assert", HARD, "negate")}
        assert fact["modality"] == "stated" and shape in allowed
        assert len(tokens) == 1 and json.loads(fact["object"]) == tokens[0]
    for e in db.execute("SELECT * FROM event").fetchall():
        assert (e["kind"], e["channel"]) in {
            ("statement", "chat"), ("commit", "commit"), ("filler", "chat"), ("notice", "chat")}
        actors = {"statement": (principal,), "commit": team, "filler": (principal,),
                  "notice": team[1:] if notice_actors is None else notice_actors}
        assert e["actor_id"] in actors[e["kind"]]
        assert (e["payload_json"], e["audience_json"], e["visibility"]) == ("{}", '["agent"]', "shared")
        assert scalar(db, "SELECT kind FROM entity WHERE id = ?", e["actor_id"]) == "person"
        session_of(schedule, e["t_sim"])
    export_world(db)


def test_whole_world(keyed, golden):
    for _, db, schedule, world in keyed:
        check_whole(db, schedule, principal=world.principal, team=world.team)
    spec = load_golden(FIXTURE)
    schedule = golden[1]
    ids = {key: mint(schedule, PROCESS, "entities", "entity", key, 0) for key in spec.entities}
    principal = ids[spec.principal]
    # The binding tidewater fixture has a single person, also its explicit notice sender.
    senders = tuple(ids[c["sender"]] for c in spec.commitment)
    check_whole(*golden[:2], principal=principal, team=(principal,), notice_actors=senders)


@pytest.mark.parametrize("table, where, field, value", [
    ("event", "kind = 'statement'", "channel", "mail"),
    ("event", "kind = 'commit'", "channel", "chat"),
    ("event", "kind = 'filler'", "channel", "mail"),
    ("event", "kind = 'notice'", "channel", "mail"),
    ("event", "kind = 'statement'", "actor_id", "teammate"),
    ("event", "kind = 'commit'", "actor_id", "outsider"),
    ("event", "kind = 'notice'", "actor_id", "principal"),
    ("fact", "speech_act = 'assert'", "strength", 500),
    ("fact", "speech_act = 'hedge'", "strength", 1000),
    ("fact", "speech_act = 'quote'", "strength", 500),
    ("fact", "id IN (SELECT fact_id FROM commitment)", "polarity", "negate"),
    ("fact", "polarity = 'negate'", "speech_act", "quote"),
], ids=["statement-channel", "commit-channel", "filler-channel", "notice-channel", "statement-actor",
        "commit-actor", "notice-actor", "assert-strength", "hedge-strength", "quote-strength",
        "negated-made", "quoted-cancel"])
def test_whole_rejects_invalid_shapes(tmp_path, table, where, field, value):
    db, schedule, world = keyed_world(tmp_path, "g05-0")
    insert_entity(db, id="outsider", kind="person", canonical_name="Visitor", aliases_json=[],
                  created_t=schedule.sessions[0].t_start, retired_t=None)
    check_whole(db, schedule, principal=world.principal, team=world.team)
    value = {"teammate": world.team[1], "principal": world.principal}.get(value, value)
    row_id = scalar(db, f"SELECT id FROM {table} WHERE {where} LIMIT 1")
    # Corrupt a built world deliberately; normal writers retain append-only enforcement.
    db.execute(f"DROP TRIGGER {table}_UPDATE")
    db.execute(f"UPDATE {table} SET {field} = ? WHERE id = ?", (value, row_id))
    with pytest.raises(AssertionError):
        check_whole(db, schedule, principal=world.principal, team=world.team)


# --- statements -------------------------------------------------------------------------------------------------

def statement_world(tmp_path, seed="g05-st"):
    schedule = build_schedule(seed, LIFE, named("t1"))
    db = new_db(tmp_path, seed, 20)
    write_sessions(db, schedule)
    for e, kind in (("P", "person"), ("A", "flag"), ("B", "flag")):
        insert_entity(db, id=e, kind=kind, canonical_name=f"name {e}", aliases_json=[], created_t=0, retired_t=None)
    return db, schedule


def test_statements(tmp_path):
    db, schedule = statement_world(tmp_path)
    ids = write_statements(db, schedule, [Statement(id="b", subject="B", key="k", stem="FLAG"),
                                          Statement(id="a", subject="A", key="k", value="VAL/one", at=(3, 5))],
                           principal="P")
    assert ids == tuple(mint(schedule, PROCESS, i, "fact", "value", 0) for i in ("b", "a"))
    e = asserting(db, ids[1])
    assert (e["t_sim"], e["kind"], e["channel"], e["actor_id"]) == (schedule.sessions[2].turn_t[4], "statement",
                                                                    "chat", "P")
    assert scalar(db, "SELECT count(*) FROM fact_surface") == 0
    assert as_valid(db, "A", "k", e["t_sim"]) == "VAL/one" and as_valid(db, "A", "k", e["t_sim"] - 1) is None
    assert re.fullmatch(r"FLAG-[0-9]{6}", as_valid(db, "B", "k", schedule.sessions[-1].t_end))


@pytest.mark.parametrize("statements, principal", [
    ([Statement(id="a", subject="A", key="k", stem="FLAG")], "nobody"),
    ([Statement(id="a", subject="nobody", key="k", stem="FLAG")], "P"),
    ([Statement(id="", subject="A", key="k", stem="FLAG")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG"), Statement(id="a", subject="B", key="k", stem="FLAG")], "P"),
    ([Statement(id="a", subject="A", key="k")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG", value="VALUE")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="F")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="Flag")], "P"),
    ([Statement(id="a", subject="A", key="k", value="café")], "P"),
    ([Statement(id="a", subject="A", key="k", value="abc")], "P"),
    ([Statement(id="a", subject="A", key="k", value="ab\ncd")], "P"),
    ([Statement(id="a", subject="A", key="k", value='say "hi"')], "P"),
    ([Statement(id="a", subject="A", key="k", value="back\\slash")], "P"),
    ([Statement(id="a", subject="A", key="k", value="café au lait")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG", token_kind="colour")], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG", at=(0, 1))], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG", at=(1, 6))], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG", at=(1,))], "P"),
    ([Statement(id="a", subject="A", key="k", stem="FLAG"), Statement(id="b", subject="A", key="k", stem="FLAG")], "P"),
    ([Statement(id="pre", subject="A", key="k", stem="FLAG")], "P"),
], ids=["principal", "subject", "empty-id", "duplicate-id", "neither", "both", "short-stem", "lower-stem",
        "not-nfc", "short-value", "newline", "quote", "backslash", "non-ascii", "token-kind", "at-session",
        "at-turn", "at-shape", "repeated-pair", "existing-attr"])
def test_statement_refusals(tmp_path, statements, principal):
    db, schedule = statement_world(tmp_path)
    if statements[0].id == "pre":
        write_statements(db, schedule, [Statement(id="first", subject="A", key="k", stem="FLAG")], principal="P")
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_statements(db, schedule, statements, principal=principal)
    assert export_jsonl(db) == before


def test_statement_seed_refusal(tmp_path):
    db, _ = statement_world(tmp_path)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_statements(db, build_schedule("other", LIFE, named("t1")),
                         [Statement(id="a", subject="A", key="k", stem="FLAG")], principal="P")
    assert export_jsonl(db) == before


def test_statement_refusal_after_insert(tmp_path):
    db, schedule = statement_world(tmp_path)
    write_statements(db, schedule, [Statement(id="a", subject="A", key="k", value="VALUE-1")], principal="P")
    insert_entity(db, id="C", kind="flag", canonical_name="name C", aliases_json=[], created_t=0, retired_t=None)
    assert db.in_transaction
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_statements(db, schedule, [Statement(id="b", subject="B", key="k", value="VALUE-1")], principal="P")
    assert export_jsonl(db) == before
    assert db.in_transaction and scalar(db, "SELECT count(*) FROM entity WHERE id = 'C'") == 1


# --- mix and scale ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("change", [
    {"constraints": True}, {"flags": -1}, {"relaxed": -1}, {"endpoints": 4}, {"decisions": 5}, {"constants": 3},
    {"deadlines": (1, 1, 1)}, {"commitments": (False,) * 3}, {"deadlines": (0,)}, {"deadlines": (7,)},
    {"deadlines": (True,)}, {"deadlines": [1, 2]}, {"relaxed": 5}, {"chat_only": 5}, {"changed": 3},
    {"constants": 1}, {"mentions": ("third_party", None)}, {"commitments": (0, 1)},
], ids=["bool-count", "negative-count", "negative-relaxed", "endpoints-over", "decisions-over", "constants-over",
        "deadlines-over", "commitments-over", "depth-0", "depth-7", "depth-bool", "deadlines-list",
        "relaxed-over", "chat-only-over", "changed-over", "mentions-over", "mention-kind", "commitment-int"])
def test_mix_refusals(tmp_path, change):
    schedule = build_schedule("g05-mix", LIFE, named("t1"))
    db = new_db(tmp_path, "g05-mix", 20)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        build_g1(db, schedule, mix=replace(MIX, **change))
    assert export_jsonl(db) == before


def test_mix_and_scale(tmp_path):
    scale = named("t0-micro", sessions=2)
    schedule = build_schedule("g05-micro", LIFE, scale)
    db = new_db(tmp_path, "g05-micro", 2)
    meta_only = export_jsonl(db)
    with pytest.raises(ValueError):
        build_g1(db, schedule)
    assert export_jsonl(db) == meta_only
    # A3's constant-0 mention makes a third event; on two sessions only the depth-0 constant carries one.
    db, schedule, world = keyed_world(tmp_path, "g05-micro", Mix(deadlines=(1,), mentions=(None, "quote")), scale)
    check_whole(db, schedule, principal=world.principal, team=world.team)
    assert {t for (t,) in db.execute("SELECT t_sim FROM event")} == {t for p in schedule.sessions for t in p.turn_t}
    with pytest.raises(ValueError):
        build_g1(db, schedule)
    db = new_db(tmp_path, None, None, {"generator_version": GENERATOR_VERSION, "genre": GENRE, "seed": "g05-micro",
                                       "scale": 3})
    with pytest.raises(ValueError):
        build_g1(db, schedule)


def test_full_scale(tmp_path):
    db, schedule, world = keyed_world(tmp_path, "g05-full", scale=named("full"))
    assert len(schedule.sessions) == 200
    check_counts(db, schedule, world)


# --- determinism and independence -------------------------------------------------------------------------------

HASH = """
import sys
from pathlib import Path
from bicentennial.genres.g1_software.world import build_g1, build_golden, golden_schedule, load_golden, world_meta
from bicentennial.world import create_world, world_hash
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
golden, out = load_golden(sys.argv[1]), Path(sys.argv[2])
schedule = golden_schedule(golden)
db = create_world(out / "golden.db", world_meta(schedule.seed, 10))
build_golden(db, golden, schedule)
print(world_hash(db))
schedule = build_schedule("g05-0", "life-a", named("t1"))
db = create_world(out / "keyed.db", world_meta("g05-0", 20))
build_g1(db, schedule)
print(world_hash(db))
"""


def test_determinism(tmp_path, keyed, golden):
    outs = []
    for i, hashseed in enumerate(("0", "random")):
        (tmp_path / str(i)).mkdir()
        outs.append(subprocess.check_output([sys.executable, "-c", HASH, str(FIXTURE), str(tmp_path / str(i))],
                                            env=dict(os.environ, PYTHONHASHSEED=hashseed), timeout=120, text=True))
    keyed0 = next(db for seed, db, _, _ in keyed if seed == "g05-0")
    assert outs[0] == outs[1] == f"{GOLDEN_HASH}\n{world_hash(keyed0)}\n"
    assert export_jsonl(keyed_world(tmp_path, "g05-0")[0]) == export_jsonl(keyed0)
    assert export_jsonl(golden_world(tmp_path)[0]) == export_jsonl(golden[0])
    assert world_hash(golden_world(tmp_path, "6102")[0]) != GOLDEN_HASH
    assert len({world_hash(db) for _, db, _, _ in keyed[:2]}) == 2


def nonfiller(db):
    filler = {r[0] for r in db.execute("SELECT id FROM event WHERE kind = 'filler'")}
    return {line for line in export_jsonl(db).splitlines()
            if not (line.startswith(b'{"row":') and json.loads(line)["table"] == "event"
                    and json.loads(line)["row"]["id"] in filler)}


def test_keyed_independence(tmp_path):
    for seed in SEEDS[:50]:
        base = nonfiller(keyed_world(tmp_path, seed)[0])
        more = nonfiller(keyed_world(tmp_path, seed, Mix(endpoints=3))[0])
        assert base < more


# --- consumers and hygiene --------------------------------------------------------------------------------------

def test_g08_renders_every_event(keyed, golden):
    template = pytest.importorskip("bicentennial.render.template")
    worlds = [golden[:2], next((db, schedule) for seed, db, schedule, _ in keyed if seed == "g05-0")]
    for db, schedule in worlds:
        for (eid,) in db.execute("SELECT id FROM event ORDER BY id").fetchall():
            template.render_event(db, eid, life=schedule.life, tz=schedule.tz)


def test_g09_commit_order(keyed, golden):
    cutter = pytest.importorskip("bicentennial.render.session_cut")
    stream = pytest.importorskip("bicentennial.render.stream")
    db, schedule, _ = golden
    spec = load_golden(FIXTURE)
    principal = mint(schedule, PROCESS, "entities", "entity", spec.principal, 0)
    worlds = [(db, schedule, principal), next((db, s, w.principal) for seed, db, s, w in keyed if seed == "g05-0")]
    for db, schedule, principal in worlds:
        result = cutter.cut(db, schedule, branch="B0", principal_id=principal, expected_state={
            p.index: {"repo_tree_hash": "a" * 64, "env_state_hash": "b" * 64} for p in schedule.sessions})
        assert stream.lint(db, result.rows) == []
        positions = {r["event_id"]: i for i, r in enumerate(result.rows)}
        for d in diffs(db):
            assert positions[asserting(db, d.fact_id)["id"]] < positions[d.event_id]
        if schedule.life == spec.life:
            assert {r["turn_key"] for r in result.rows if r["session_id"] == schedule.sessions[5].session_id} == {
                f"{schedule.sessions[5].session_id}/t{i}" for i in range(1, 16)}
            assert result.sessions[4]["fault_points"] == [{"kind": "kill", "session": 5, "turn": 2}]
            assert result.sessions[7]["wake_before"] == ["gap"]


def test_imports():
    banned = {"random", "time", "socket", "ssl", "http", "urllib", "subprocess", "bicentennial.sandbox",
              "bicentennial.director", "spikes"}
    for module in ("world", "codebase_model"):
        path = ROOT / "src" / "bicentennial" / "genres" / "g1_software" / f"{module}.py"
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == b or n.startswith(b + ".") for n in names for b in banned)
    assert not (ROOT / "src" / "bicentennial" / "genres" / "__init__.py").exists()
    assert not (ROOT / "src" / "bicentennial" / "genres" / "g1_software" / "__init__.py").exists()
