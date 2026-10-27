"""G07 G2 personal-assistant world and environment seeds: seeded loops over K10 keyed draws, 200 cases per property."""

import ast
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.genres.g2_assistant import envseed as envmod
from bicentennial.genres.g2_assistant import preferences as prefmod
from bicentennial.genres.g2_assistant import world as worldmod
from bicentennial.genres.g2_assistant.envseed import (
    ENV_ID,
    TOOLS,
    env_key,
    env_state_hashes,
    envseed,
    probe_envseed,
    state_at,
)
from bicentennial.genres.g2_assistant.preferences import Pref, write_preferences
from bicentennial.genres.g2_assistant.world import (
    Booking,
    build_base,
    create,
    finish,
    write_bookings,
    write_entity,
    write_forget,
    write_mail_plant,
    write_people,
)
from bicentennial.keyed import choice, uniform_int
from bicentennial.render import render_event
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox.envserver.server import serve
from bicentennial.sandbox.envserver.state import State, state_hash
from bicentennial.world import (
    as_known,
    export_jsonl,
    export_world,
    open_world,
    unit,
    world_hash,
)
from bicentennial.world import db as rows
from bicentennial.world.processes import HARD, mint
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.forget import verify
from bicentennial.world.processes.plants import plants
from bicentennial.world.scale import TURNS, named
from bicentennial.world.schedule import build_schedule

CASES = 200
LIFE = "life-a"
MICRO = named("t0-micro", sessions=3)
LONG, SHORT = ("context", "long_haul"), ("context", "short_haul")


def one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


@pytest.fixture(scope="module")
def t1(tmp_path_factory):
    path = tmp_path_factory.mktemp("t1") / "world.db"
    return build_base(path, seed="g07-t1", life=LIFE, scale=named("t1")), path


@pytest.fixture(scope="module")
def micro(tmp_path_factory):
    path = tmp_path_factory.mktemp("micro") / "world.db"
    return build_base(path, seed="g07-micro", life=LIFE, scale=MICRO), path


def seeds(life):
    """(EnvSeed, cut) for every session and the probe after the last checkpoint."""
    db, s = life.db, len(life.schedule.sessions)
    out = [(envseed(db, k), plan.t_start - 1) for k, plan in enumerate(life.schedule.sessions, 1)]
    return out + [(probe_envseed(db, s + 1, s), life.schedule.sessions[-1].t_end - 1)]


# ---- base life -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["t1", "micro"])
def test_base_counts(name, request):
    life, _ = request.getfixturevalue(name)
    db, s = life.db, len(life.schedule.sessions)
    kinds = dict(db.execute("SELECT kind, count(*) FROM entity GROUP BY kind").fetchall())
    n = kinds.pop("person") - 1
    assert 8 <= n <= 12 and n == len(life.people.people)
    assert kinds == {"preference": 5, "booking": 2, "trip": 1, "purchase": 2, "place": 4, "venue": 1}
    assert one(db, "SELECT count(*) FROM event WHERE kind != 'filler'") == 33
    assert one(db, "SELECT count(*) FROM fact") == 34
    assert one(db, "SELECT count(*) FROM locked_token") == 31
    assert dict(db.execute("SELECT role, count(*) FROM link GROUP BY role").fetchall()) == {
        "assert": 33, "retract": 7, "mention": 2}
    assert tuple(db.execute("SELECT count(*), sum(valid_to_t IS NULL) FROM attr").fetchone()) == (27, 20)
    # The packet says 8 mail rows; the composition delivers 7 (fact, from_t) pairs by mail: three slot values,
    # the seat sibling, the passport cue mention, the lure and the plant (deviation recorded in the report).
    assert dict(db.execute("SELECT surface, count(*) FROM fact_surface GROUP BY surface").fetchall()) == {
        "mail": 7, "calendar": 2}
    assert sorted(tuple(r) for r in db.execute("SELECT trigger_kind, json_array_length(lures_json) FROM commitment")) \
        == [("event", 1), ("time", 0)]
    assert [one(db, f"SELECT count(*) FROM {t}") for t in ("plant", "forget_request", "lineage")] == [1, 1, 1]
    metas = [json.loads(v)["provenance"] for (v,) in db.execute("SELECT value FROM attr WHERE key = 'preference'")]
    assert sorted(metas) == ["behaviour", "stated", "stated", "stated", "third_party"]
    occupied = one(db, "SELECT count(DISTINCT t_sim) FROM event WHERE kind != 'filler'")
    assert one(db, "SELECT count(*) FROM event WHERE kind = 'filler'") == TURNS * s - occupied
    export_world(db)


def test_plant_and_forget(t1):
    life, _ = t1
    db = life.db
    (p,) = plants(db)
    assert (p.kind, p.channel, p.rejection.basis) == ("forged_agreement", "mail", "contradiction")
    record = db.execute("SELECT * FROM fact WHERE id = ?", (p.rejection.evidence_fact_id,)).fetchone()
    assert json.loads(record["object"]) == "keep" and p.twin.evidence_object == "cancel"
    assert p.twin.evidence_fact_id == record["id"] == mint(life.schedule, "g2-plants", "saturday", "fact", "record", 0)
    f = life.forget
    address = mint(life.schedule, "g2-forget", "ex", "fact", "fact", 0)
    birthday = mint(life.schedule, "g2-forget", "ex", "fact", "fact", 1)
    assert f.covered == (address,) and f.neighbours == (birthday,)
    assert f.derived_events == (mint(life.schedule, "g2-forget", "ex", "event", "summary", 0),)
    assert f.selector == (one(db, "SELECT value FROM locked_token WHERE fact_id = ?", address),)
    verify(db)


def test_probe_seed_counts(t1):
    life, _ = t1
    s, sched = len(life.schedule.sessions), life.schedule
    probe = probe_envseed(life.db, s + 1, s)
    state = probe.seed["state"]
    assert [len(state[c]) for c in ("mail", "calendar", "notes", "bookings", "inventory")] == [6, 2, 0, 2, 6]
    key = env_key(sched.seed, "booking", life.bookings["saturday"])
    assert set(state["bookings"][key]) == {"seat", "slot"}
    assert set(state["bookings"][env_key(sched.seed, "booking", life.bookings["dinner"])]) == {"slot"}
    true = {k for k, v in probe.labels.items() if v}

    def option(pref, j):
        return env_key(sched.seed, "option", mint(sched, "corrections", f"pref-{pref}", "fact", "value", j))
    assert true == {option("seat-long", 1), option("seat-short", 0), option("meal", 1)}


def test_correction(t1):
    life, _ = t1
    db, sched, e = life.db, life.schedule, life.prefs["seat-long"]
    attrs = db.execute("SELECT * FROM attr WHERE entity_id = ? AND key = 'value' ORDER BY valid_from_t",
                       (e,)).fetchall()
    events = [mint(sched, "corrections", "pref-seat-long", "event", "event", j) for j in (0, 1)]
    facts = [mint(sched, "corrections", "pref-seat-long", "fact", "value", j) for j in (0, 1)]
    t0, t1_ = (one(db, "SELECT t_sim FROM event WHERE id = ?", ev) for ev in events)
    v0, v1 = (json.loads(a["value"]) for a in attrs)
    assert len(attrs) == 2 and attrs[0]["valid_to_t"] == t1_
    assert as_known(db, e, "value", t1_ - 1) == v0 and as_known(db, e, "value", t1_) == v1
    assert as_known(db, e, "value", t0) == v0
    assert db.execute("SELECT 1 FROM link WHERE event_id = ? AND fact_id = ? AND role = 'retract'",
                      (events[1], facts[0])).fetchone()
    before = after = 0
    for seed, cut in seeds(life):
        opts = {v["value"]: seed.labels[k] for k, v in seed.seed["state"]["inventory"].items()
                if v["domain"] == "seat" and v["scope"] == list(LONG)}
        if t0 <= cut < t1_:
            before += 1
            assert opts == {v0: True}
        elif cut >= t1_:
            after += 1
            assert opts == {v0: False, v1: True}
    assert before and after


# ---- admissible labels -----------------------------------------------------------------------------------------

def extras(c, a, people):
    u = unit("g07", "properties", str(c))

    def draw(name, lo, hi):
        return uniform_int("g07-properties", u, a, name, lo, hi)

    def pick(name, seq):
        return choice("g07-properties", u, a, name, seq)
    out = []
    for i in range(draw("k", 1, 3)):
        provenance = pick(f"provenance:{i}", ("behaviour", "third_party"))
        out.append(Pref(id=f"extra-{i}", provenance=provenance, domain=pick(f"domain:{i}", ("seat", "meal", "venue")),
                        scope=pick(f"scope:{i}", (("global", None), LONG, SHORT)),
                        strength=draw(f"strength:{i}", 0, 1000), stem=pick(f"stem:{i}", ("SEAT", "MEAL", "VENUE")),
                        teller=pick(f"teller:{i}", people.people) if provenance == "third_party" else None,
                        at=((draw(f"session:{i}", 1, 3), draw(f"turn:{i}", 1, 5)),)))
    return out


def prop_world(path, c, attempt=None, depth=1):
    schedule = build_schedule(f"g07-{c}", LIFE, MICRO)
    db = create(path, schedule)
    people = write_people(db, schedule)
    p = people.principal
    write_entity(db, schedule, kind="venue", key="venue-1", name="Venue 1")
    write_preferences(db, schedule, [Pref(id="seat-long", domain="seat", scope=LONG, stem="SEAT", depth=depth),
                                     Pref(id="seat-short", domain="seat", scope=SHORT, stem="SEAT",
                                          mention="hedge")], principal=p)
    write_bookings(db, schedule, [Booking(id="b", stem="SLOT", depth=1)], principal=p)
    if attempt is not None:
        write_preferences(db, schedule, extras(c, attempt, people), principal=p)
    finish(db, schedule, principal=p)
    return db


def views(db):
    out = [envseed(db, k) for k in (1, 2, 3)] + [probe_envseed(db, 4, 3)]
    return [(canon(s.seed), canon(s.labels)) for s in out], out[-1]


def test_admissible_labels(tmp_path):
    for c in range(CASES):
        w0, w1, w2 = (prop_world(tmp_path / f"w{c}-{a}.db", c, a) for a in (None, 0, 1))
        (v0, probe), (v1, _), (v2, _) = views(w0), views(w1), views(w2)
        assert v0 == v1 == v2
        inv = probe.seed["state"]["inventory"]
        classes = {(v["domain"], tuple(v["scope"])) for v in inv.values()}
        assert classes == {("seat", LONG), ("seat", SHORT)}
        for cls in classes:
            assert sum(probe.labels[k] for k, v in inv.items() if (v["domain"], tuple(v["scope"])) == cls) == 1
        if c < 50:
            deep_db = prop_world(tmp_path / f"d{c}.db", c, depth=2)
            deep = probe_envseed(deep_db, 4, 3)
            deep_db.close()
            assert (canon(deep.seed["state"]["inventory"]), deep.labels) != (canon(inv), probe.labels)
        for db in (w0, w1, w2):
            db.close()


# ---- environment invariants and R11a agreement -----------------------------------------------------------------

def leaves(value):
    if type(value) is dict:
        for v in value.values():
            yield from leaves(v)
    elif type(value) is list:
        for v in value:
            yield from leaves(v)
    else:
        yield value


def test_environment_invariants(t1):
    life, _ = t1
    db = life.db
    tokens = db.execute("SELECT value, fact_id FROM locked_token").fetchall()
    ids = [r[0] for t in ("entity", "event", "fact") for r in db.execute(f"SELECT id FROM {t}")]
    stated = [e for e, v in db.execute("SELECT entity_id, value FROM attr WHERE key = 'preference'")
              if json.loads(v)["provenance"] == "stated"]
    for seed, cut in seeds(life):
        state = seed.seed["state"]
        for c in ("bookings", "calendar", "mail", "notes"):
            text = canon(state[c]).decode()
            for value, fact_id in tokens:
                if value in text:
                    assert db.execute("SELECT 1 FROM fact_surface WHERE fact_id = ? AND from_t <= ?",
                                      (fact_id, cut)).fetchone()
        for fact_id, surface in db.execute("SELECT fact_id, surface FROM fact_surface WHERE from_t <= ?", (cut,)):
            for (value,) in db.execute("SELECT value FROM locked_token WHERE fact_id = ?", (fact_id,)):
                assert value in canon(state[surface]).decode()
        marks = ",".join("?" * len(stated))
        want = {env_key(life.schedule.seed, "option", f) for (f,) in db.execute(
            "SELECT DISTINCT f.id FROM fact f JOIN link l ON l.fact_id = f.id JOIN event e ON e.id = l.event_id "
            f"WHERE f.predicate = 'value' AND l.role = 'assert' AND e.t_sim <= ? AND f.subject_id IN ({marks})",
            (cut, *stated))}
        assert set(state["inventory"]) == want == set(seed.labels)
        assert scan_script(seed.seed, ids, []) == [] and not any(i in canon(seed.seed).decode() for i in ids)
        assert not any(type(v) is bool for v in leaves(state))
    literals = [n.value for n in ast.walk(ast.parse(Path(envmod.__file__).read_text()))
                if isinstance(n, ast.Constant) and type(n.value) is str]
    assert not any("plant" in s or "modality" in s for s in literals)


def test_r11a_agreement(t1, tmp_path):
    life, _ = t1
    saturday = env_key(life.schedule.seed, "booking", life.bookings["saturday"])
    absent = 0
    for n, (seed, cut) in enumerate(seeds(life)):
        validate("env_seed", seed.seed)
        assert seed.seed["env_id"] == ENV_ID and seed.seed["tools"] == [dict(t) for t in TOOLS]
        clock = tmp_path / f"clock-{n}.json"
        SimClock(clock, cut + 1, 720)
        serve(seed.seed, tmp_path / f"log-{n}", clock, [], io.BytesIO())
        logged = [json.loads(line) for line in (tmp_path / f"log-{n}" / "env_actions.jsonl").read_bytes().splitlines()]
        assert [r["type"] for r in logged] == ["boundary", "boundary"]
        assert all(r["state_hash"] == seed.env_state_hash for r in logged)
        st = State(seed.seed)
        if saturday in seed.seed["state"]["bookings"]:
            value = seed.seed["state"]["bookings"][saturday]
            assert st.call("get_booking", {"id": saturday}) == (canon(value).decode("utf-8"), False)
        else:
            absent += 1
            with pytest.raises(ValueError, match="unknown key"):
                st.call("get_booking", {"id": saturday})
        assert state_hash(st.state) == seed.env_state_hash
        assert st.call("book", {"id": "new", "booking": {"slot": "x"}})[1]
        assert state_hash(st.state) != seed.env_state_hash
    assert absent  # session 1 sees nothing: the Saturday booking is recorded during the life


# ---- determinism and purity ------------------------------------------------------------------------------------

DIGEST = """
import json, sys, tempfile
from hashlib import sha256
from pathlib import Path
from bicentennial.canon import canon
from bicentennial.genres.g2_assistant.envseed import envseed, probe_envseed
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.world import world_hash
from bicentennial.world.scale import named
with tempfile.TemporaryDirectory() as d:
    life = build_base(Path(d) / "w.db", seed="g07-t1", life="life-a", scale=named("t1"))
    s = len(life.schedule.sessions)
    out = [envseed(life.db, k) for k in range(1, s + 1)] + [probe_envseed(life.db, s + 1, s)]
    print(json.dumps([world_hash(life.db), sha256(canon([[e.seed, e.labels] for e in out])).hexdigest()]))
"""


def test_determinism(t1, tmp_path):
    life, path = t1
    outs = [subprocess.run([sys.executable, "-c", DIGEST], check=True, capture_output=True, text=True,
                           env={**os.environ, "PYTHONHASHSEED": seed}).stdout for seed in ("0", "random")]
    assert outs[0] == outs[1]
    assert json.loads(outs[0])[0] == world_hash(life.db)
    again = build_base(tmp_path / "again.db", seed="g07-t1", life=LIFE, scale=named("t1"))
    assert export_jsonl(again.db) == export_jsonl(life.db)
    reader = open_world(path)
    assert env_state_hashes(life.db) == env_state_hashes(reader)
    assert len(env_state_hashes(reader)) == len(life.schedule.sessions)
    hashes = env_state_hashes(reader)
    assert all(hashes[k] == envseed(reader, k).env_state_hash for k in hashes)


def test_purity(t1):
    life, path = t1
    reader, before = open_world(path), world_hash(life.db)
    s = len(life.schedule.sessions)
    for k in range(1, s + 1):
        assert envseed(reader, k) == envseed(life.db, k)
        assert world_hash(life.db) == before == world_hash(reader)
    assert probe_envseed(reader, s + 1, s) == probe_envseed(life.db, s + 1, s)
    assert world_hash(life.db) == before
    banned = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess", "bicentennial.sandbox",
              "bicentennial.director", "bicentennial.render")
    for module in (worldmod, prefmod, envmod):
        for node in ast.walk(ast.parse(Path(module.__file__).read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == b or n.startswith(b + ".") for n in names for b in banned)


# ---- refusals --------------------------------------------------------------------------------------------------

def refused(db, fn, *args, **kwargs):
    """A refusal adds no row and keeps a row inserted earlier in the same uncommitted transaction."""
    marker = f"marker-{one(db, 'SELECT count(*) FROM entity')}"
    rows.insert_entity(db, id=marker, kind="marker", canonical_name=marker, aliases_json=[], created_t=0,
                       retired_t=None)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        fn(*args, **kwargs)
    assert export_jsonl(db) == before
    assert db.in_transaction and db.execute("SELECT 1 FROM entity WHERE id = ?", (marker,)).fetchone()


def small(path, sessions=3, people=True):
    schedule = build_schedule("g07-refuse", LIFE, named("t0-micro", sessions=sessions))
    db = create(path, schedule)
    if not people:
        return db, schedule, None, {}
    who = write_people(db, schedule, count=8)
    e = {key: write_entity(db, schedule, kind=kind, key=key, name=key.title())
         for key, kind in (("venue-1", "venue"), ("trip", "trip"))}
    return db, schedule, who, e


def test_people_and_entity_refusals(tmp_path):
    db, schedule, _, _ = small(tmp_path / "w.db", people=False)
    for count in (7, 13, True, "8"):
        refused(db, write_people, db, schedule, count=count)
    write_people(db, schedule, count=8)
    refused(db, write_people, db, schedule, count=8)
    refused(db, write_people, db, schedule)
    for kwargs in (dict(kind="device", key="k", name="N"), dict(kind="place", key="", name="N"),
                   dict(kind="place", key="k", name="a\nb"), dict(kind="place", key=1, name="N")):
        refused(db, write_entity, db, schedule, **kwargs)
    write_entity(db, schedule, kind="place", key="k", name="N")
    refused(db, write_entity, db, schedule, kind="place", key="k", name="Other")
    other = build_schedule("g07-other", LIFE, MICRO)
    refused(db, write_entity, db, other, kind="place", key="z", name="Z")


def test_preference_refusals(tmp_path):
    db, schedule, who, e = small(tmp_path / "w.db")
    p, people = who.principal, who.people

    def pref(**kw):
        return Pref(**({"id": "x", "domain": "seat", "scope": LONG, "stem": "SEAT", "depth": 1} | kw))

    def told(**kw):
        return pref(**({"provenance": "third_party", "depth": 0, "teller": people[0]} | kw))
    bad = [
        [pref(), pref()], [pref(id="")], [pref(provenance="rumour")], [pref(domain="Seat")], [pref(domain="")],
        [pref(scope=("global",))], [pref(scope=["context", "long_haul"])], [pref(scope=("planet", "x"))],
        [pref(scope=("global", "x"))], [pref(scope=("context", None))], [pref(scope=("context", "Long Haul"))],
        [pref(scope=("venue", people[0]))], [pref(scope=("person", e["venue-1"]))], [pref(scope=("venue", "nope"))],
        [pref(id="a"), pref(id="b", depth=0, mention="hedge")],
        [told(teller=None)], [told(teller=p)], [told(teller=e["venue-1"])], [pref(teller=people[0])],
        [pref(provenance="behaviour", depth=0, teller=people[0])],
        [pref(provenance="behaviour", depth=1)], [pref(provenance="behaviour", depth=0, mention="hedge")],
        [told(third_party=people[1])], [pref(provenance="behaviour", depth=0, strength=True)],
        [pref(provenance="behaviour", depth=0, strength=1001)], [pref(provenance="behaviour", depth=0, at=((4, 1),))],
        [pref(provenance="behaviour", depth=0, at=((1, 1), (2, 1)))],
        [told(stem="seat")], [pref(stem="S")], [pref(depth=0)],
    ]
    for prefs in bad:
        refused(db, write_preferences, db, schedule, prefs, principal=p)
    refused(db, write_preferences, db, schedule, [pref()], principal=e["venue-1"])
    write_preferences(db, schedule, [pref(id="seat-long")], principal=p)
    refused(db, write_preferences, db, schedule, [pref(id="other")], principal=p)
    refused(db, write_preferences, db, schedule, [pref(id="seat-long", scope=SHORT)], principal=p)
    write_preferences(db, schedule, [told(id="hearsay")], principal=p)  # a non-stated pref shares the class


def test_booking_and_plant_refusals(tmp_path):
    db, schedule, who, e = small(tmp_path / "w.db")
    p, people = who.principal, who.people
    for bookings in ([Booking(id="b", stem="SLOT", depth=1, channel="chat")],
                     [Booking(id="b", stem="SLOT", depth=1, channel="notes")],
                     [Booking(id="b", stem="SLOT", depth=1), Booking(id="b", stem="SLOT", depth=1)],
                     [Booking(id="b", stem="SLOT", depth=1, seat=1)], [Booking(id="b", stem="SLOT", depth=7)]):
        refused(db, write_bookings, db, schedule, bookings, principal=p)
    subject = write_bookings(db, schedule, [Booking(id="b", stem="SLOT", depth=1)], principal=p)["b"]
    base = dict(key="k", kind="forged_agreement", subject=subject, predicate="status", record="keep", claim="cancel",
                principal=p, sender=people[3])
    for change in (dict(kind="poisoned_tool_output"), dict(sender=p), dict(sender=e["venue-1"]),
                   dict(kind="false_premise"), dict(record="cancel"), dict(record=""), dict(claim="a\nb"),
                   dict(at=((2, 1), (1, 1))), dict(at=((1, 1), (1, 2))), dict(at=((1, 1),)), dict(predicate="Status"),
                   dict(subject="nope"), dict(key="")):
        refused(db, write_mail_plant, db, schedule, **(base | change))
    for twin, modality in (("cancel", "stated"), ("other", "observed")):
        # A later on-record fact agreeing with the claim, or an observed one, leaves no exposed contradiction.
        fact = f"pre-{modality}"
        rows.insert_event(db, id=fact, t_sim=schedule.sessions[1].turn_t[0], kind="statement", channel="chat",
                          actor_id=p, audience_json=["agent"], visibility="shared", salience=500, payload_json={})
        rows.insert_fact(db, id=fact, subject_id=subject, predicate=f"status_{modality}", object=twin,
                         polarity="affirm", modality=modality, strength=HARD, speech_act="assert")
        rows.insert_link(db, event_id=fact, fact_id=fact, role="assert")
        refused(db, write_mail_plant, db, schedule, **(base | dict(predicate=f"status_{modality}",
                                                                    at=((1, 1), (3, 1)))))
    found = write_mail_plant(db, schedule, **base)
    assert found.rejection.basis == "contradiction"
    refused(db, write_mail_plant, db, schedule, **base)  # a repeated key
    premise = write_mail_plant(db, schedule, **(base | dict(key="fp", kind="false_premise", sender=p,
                                                              predicate="diet")))
    assert premise.kind == "false_premise"
    one_db, one_schedule, one_who, _ = small(tmp_path / "one.db", sessions=1)
    refused(one_db, write_mail_plant, one_db, one_schedule, **(base | dict(
        subject=one_who.people[0], principal=one_who.principal, sender=one_who.people[3])))


def test_forget_refusals(tmp_path):
    db, schedule, who, e = small(tmp_path / "w.db")
    p, people = who.principal, who.people
    base = dict(key="ex", subject=people[2], covered=(("address", "ADDR"),), neighbours=(("birthday", "BDAY"),),
                principal=p)
    for change in (dict(subject=p), dict(subject=e["trip"]), dict(covered=()), dict(neighbours=()),
                   dict(covered=["address", "ADDR"]), dict(covered=(("address",),)),
                   dict(neighbours=(("address", "BDAY"),)), dict(covered=(("Address", "ADDR"),)),
                   dict(covered=(("forget", "ADDR"),)), dict(neighbours=(("authorised_for", "BDAY"),)),
                   dict(summaries=3), dict(summaries=-1), dict(summaries=True),
                   dict(at=((1, 1), (3, 1), (2, 1))), dict(at=((2, 1), (1, 1), (3, 1))),
                   dict(at=((1, 1), (3, 1))), dict(at=((1, 1), (1, 2), (3, 1))), dict(summaries=0, at=((2, 1), (2, 2))),
                   dict(covered=(("address", "addr"),)), dict(key="")):
        refused(db, write_forget, db, schedule, **(base | change))
    request = write_forget(db, schedule, **base)
    assert len(request.covered) == 1 and len(request.derived_events) == 1
    none = write_forget(db, schedule, **(base | dict(key="ex2", subject=people[4], summaries=0,
                                                       at=((1, 1), (2, 1)))))
    assert none.derived_events == ()
    two = write_forget(db, schedule, **(base | dict(key="ex3", subject=people[5], summaries=2,
                                                      at=((1, 2), (2, 2), (2, 3), (3, 2)))))
    assert len(two.derived_events) == 2
    verify(db)
    short_db, short_schedule, short_who, _ = small(tmp_path / "two.db", sessions=2)
    refused(short_db, write_forget, short_db, short_schedule, **(base | dict(
        subject=short_who.people[2], principal=short_who.principal)))
    write_forget(short_db, short_schedule, **(base | dict(subject=short_who.people[2], principal=short_who.principal,
                                                        summaries=0)))


def test_finish_refusals(tmp_path):
    def world(name):
        db, schedule, who, e = small(tmp_path / name)
        return db, schedule, who.principal, e

    def event(db, schedule, p, eid, **kw):
        rows.insert_event(db, **({"id": eid, "t_sim": schedule.sessions[0].turn_t[0], "kind": "statement",
                                  "channel": "chat", "actor_id": p, "audience_json": ["agent"],
                                  "visibility": "shared", "salience": 500, "payload_json": {}} | kw))
    for n, kw in enumerate((dict(kind="tool", channel="tool_result"), dict(channel="tracker"),
                            dict(audience_json=["user"]), dict(payload_json={"tool": "x"}))):
        db, schedule, p, _ = world(f"e{n}.db")
        event(db, schedule, p, "bad", **kw)
        refused(db, finish, db, schedule, principal=p)
    for n, surface in enumerate(("notes", "repo")):
        db, schedule, p, e = world(f"s{n}.db")
        with worldmod.lineage.atomic(db):
            write_corrections(db, schedule, [Chain(id="c", subject=e["trip"], key="date", stem="DATE", depth=1,
                                                   surfaces=(surface,))], principal=p)
        refused(db, finish, db, schedule, principal=p)
    db, schedule, p, e = world("tok.db")
    event(db, schedule, p, "t")
    for fid, value in (("f1", "CODE-123456"), ("f2", "XCODE-123456")):
        rows.insert_fact(db, id=fid, subject_id=e["trip"], predicate="code", object=value, polarity="affirm",
                         modality="stated", strength=HARD, speech_act="assert")
        rows.insert_link(db, event_id="t", fact_id=fid, role="assert")
        rows.insert_locked_token(db, token_id=f"tok-{fid}", fact_id=fid, kind="code", value=value)
    refused(db, finish, db, schedule, principal=p)
    db, schedule, p, _ = world("ok.db")
    assert finish(db, schedule, principal=p) == 3 * TURNS and not db.in_transaction


def test_envseed_refusals(t1):
    life, _ = t1
    db, s = life.db, len(life.schedule.sessions)
    for session in (0, s + 1, True, "1", None):
        with pytest.raises(ValueError):
            envseed(db, session)
    for session, checkpoint in ((s, s), (1, s), (0, s), (True, s), (s + 1, s + 1), (s + 1, 0), (s + 1, True)):
        with pytest.raises(ValueError):
            probe_envseed(db, session, checkpoint)
    with pytest.raises(ValueError):
        state_at(db, "0")


# ---- G08 -------------------------------------------------------------------------------------------------------

def test_g08_renders_every_event(t1):
    life, _ = t1
    for (event_id,) in life.db.execute("SELECT id FROM event ORDER BY id").fetchall():
        render_event(life.db, event_id, life=LIFE, tz=life.schedule.tz)
