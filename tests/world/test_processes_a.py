"""G03 shared processes: exact mixes, keyed independence, twin flips and refusals, 200 seeds each."""

import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from itertools import count
from pathlib import Path

import pytest

import bicentennial.world.processes as processes
from bicentennial.canon import canon
from bicentennial.keyed import uniform_int
from bicentennial.world import (
    as_known,
    as_valid,
    create_world,
    export_jsonl,
    export_world,
    unit,
    world_hash,
)
from bicentennial.world.db import (
    TABLES,
    insert_entity,
    insert_event,
    insert_fact,
    insert_locked_token,
)
from bicentennial.world.processes import (
    HARD,
    LOW_SALIENCE,
    SALIENCE,
    SOFT,
    SURFACES,
    check_tokens,
    mint,
    slot,
    token_value,
)
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.processes.incidental import (
    DECOY_RATIO_LABEL,
    Detail,
    write_details,
)
from bicentennial.world.scale import TURNS, named
from bicentennial.world.schedule import build_schedule, write_sessions

SEEDS = [f"g03-{case}" for case in range(200)]
WORLDS = count()
LIFE = "life-a"
PRINCIPAL, OUTSIDER, SENDER = "Principal", "Outsider", "Sender"
SPEECH_ACTS = ("assert", "hedge", "propose", "quote")
MINTED = re.compile(r"^[A-Z]{2,12}-[0-9]{6}$")
MIX_A = [(1, "hedge", 0), (1, "quote", 0), (1, "third_party", 0), (1, None, 0), (1, None, 0), (1, None, 0),
         (2, "hedge", 0), (2, None, 1), (2, None, 0), (2, None, 0), (3, "quote", 0), (3, None, 1), (3, None, 0),
         (4, "third_party", 0), (4, None, 0), (5, "hedge", 0), (6, None, 0),
         (0, "hedge", 0), (0, "hedge", 0), (0, "quote", 0), (0, "third_party", 0)]
MIX_B = [("time", True, 0), ("time", False, 0), ("time", False, 0), ("event", False, 1), ("event", True, 1),
         ("event", False, 1), ("cue", False, 2), ("cue", True, 2)]
PREDICATES = ("locker", "badge", "gate", "desk", "shelf")


def name(i):
    return "Ent" + chr(97 + i // 26) + chr(97 + i % 26)


def chain(i, depth, mention=None, sibling=0, **kw):
    return Chain(id=f"chain{i}", subject=name(i), key="status", stem="VALUE", depth=depth, mention=mention,
                 third_party=OUTSIDER if mention == "third_party" else None,
                 sibling="seat" if sibling else None, **kw)


def commitment(i, trigger, cancelled, lures, **kw):
    cue = trigger != "time"
    return Commitment(id=f"commit{i}", subject=name(100 + i), predicate="task", stem="TASK", trigger=trigger,
                      cue_subject=name(120 + i) if cue else None, cue_key="parcel" if cue else None,
                      cue_stem="PARCEL" if cue else None, sender=SENDER if cue else None,
                      lures=tuple(name(140 + 3 * i + j) for j in range(lures)), cancelled=cancelled, **kw)


def detail(i, decoys=3, **kw):
    return Detail(id=f"detail{i}", subject=name(200 + 4 * i), predicate=PREDICATES[i], stem="LOCKER",
                  decoys=tuple(name(201 + 4 * i + j) for j in range(decoys)), **kw)


def mixes(extra=False):
    a = [chain(i, *spec) for i, spec in enumerate(MIX_A)]
    b = [commitment(i, *spec) for i, spec in enumerate(MIX_B)]
    c = [detail(i) for i in range(4)]
    if extra:
        a, b, c = a + [chain(21, 2, "quote", 1)], b + [commitment(8, "cue", True, 1)], c + [detail(4)]
    return a, b, c


def world(path, seed, scale=None):
    schedule = build_schedule(seed, LIFE, scale or named("t1"))
    db = create_world(path, {"generator_version": "g03-test", "genre": "test", "seed": seed,
                             "scale": len(schedule.sessions)})
    write_sessions(db, schedule)
    for e in (PRINCIPAL, OUTSIDER, SENDER, *(name(i) for i in range(260))):
        insert_entity(db, id=e, kind="person", canonical_name=e, aliases_json=[], created_t=0, retired_t=None)
    return db, schedule


def lines(db):
    return set(export_jsonl(db).splitlines())


def build(path, seed, specs=None, filler=True):
    db, schedule = world(path, seed)
    a, b, c = specs or mixes()
    stages = {}
    for stage, write in (("corrections", lambda: write_corrections(db, schedule, a, principal=PRINCIPAL)),
                         ("commitments", lambda: write_commitments(db, schedule, b, principal=PRINCIPAL)),
                         ("incidental", lambda: write_details(db, schedule, c, principal=PRINCIPAL))):
        before = lines(db)
        write()
        stages[stage] = rows(lines(db) - before)
    if filler:
        before = lines(db)
        stages["occupied"] = {t for (t,) in db.execute("SELECT t_sim FROM event")}
        stages["filler_count"] = write_filler(db, schedule, principal=PRINCIPAL)
        stages["filler"] = rows(lines(db) - before)
    return db, schedule, stages


def rows(raw):
    out = {}
    for line in raw:
        item = json.loads(line)
        out.setdefault(item["table"], []).append(item["row"])
    return out


def non_filler(db):
    return {line for line in lines(db) if b'"kind":"filler"' not in line}


def by_role(link_rows):
    return Counter(r["role"] for r in link_rows)


def check_corrections(db, schedule, d, chains):
    facts = {f["id"]: f for f in d["fact"]}
    assert (len(d["event"]), len(facts), len(d["locked_token"])) == (74, 76, 76)
    assert by_role(d["link"]) == {"assert": 76, "retract": 42}
    assert len(d["attr"]) == 65 and sum(r["valid_to_t"] is None for r in d["attr"]) == 23
    retracts = Counter(facts[r["fact_id"]]["subject_id"] for r in d["link"] if r["role"] == "retract")
    assert Counter(retracts[c.subject] for c in chains) == {0: 4, 1: 6, 2: 4, 3: 3, 4: 2, 5: 1, 6: 1}
    attr = {(r["entity_id"], r["key"], r["value"]) for r in d["attr"]}
    actor = {link["fact_id"]: ev["actor_id"] for ev in d["event"] for link in d["link"]
             if link["event_id"] == ev["id"] and link["role"] == "assert"}
    hedges = [f for f in facts.values() if f["speech_act"] == "hedge"]
    quotes = [f for f in facts.values() if f["speech_act"] == "quote"]
    third = [f for f in facts.values() if actor[f["id"]] == OUTSIDER]
    assert (len(hedges), len(quotes), len(third)) == (5, 3, 3)
    assert all(f["strength"] == SOFT for f in hedges)
    assert not {(f["subject_id"], f["predicate"], f["object"]) for f in hedges + quotes + third} & attr
    starts = [s.t_start for s in schedule.sessions]
    times = {e["id"]: e["t_sim"] for e in d["event"]}
    for c in chains:
        m = c.depth + 1 + (c.mention is not None)
        ts = [times[mint(schedule, "corrections", c.id, "event", "event", j)] for j in range(m)]
        sessions = [sum(s <= t for s in starts) for t in ts]
        assert ts == sorted(set(ts)) and len(set(sessions)) == m and sessions == sorted(sessions)
        last = facts[mint(schedule, "corrections", c.id, "fact", "value", c.depth)]["object"]
        assert as_valid(db, c.subject, "status", ts[-1]) == last == as_known(db, c.subject, "status", ts[-1])


def check_commitments(db, schedule, d, specs):
    assert len(d["commitment"]) == 8 and Counter(r["trigger_kind"] for r in d["commitment"]) == {
        "time": 3, "event": 3, "cue": 2}
    assert sum(len(r["lures_json"]) for r in d["commitment"]) == 7
    assert (len(d["event"]), len(d["fact"]), len(d["locked_token"])) == (25, 23, 23)
    assert by_role(d["link"]) == {"assert": 23, "retract": 3, "mention": 7}
    times = {e["id"]: e["t_sim"] for e in d["event"]}
    rows_ = {r["fact_id"]: r for r in d["commitment"]}
    links = {(r["event_id"], r["fact_id"], r["role"]) for r in d["link"]}
    for c in specs:
        def ident(table, part, n=0, c=c):
            return mint(schedule, "commitments", c.id, table, part, n)
        row, t_c = rows_[ident("fact", "made")], times[ident("event", "made")]
        session = next(s for s in schedule.sessions if s.t_start <= row["window_open_t"] < s.t_end)
        assert row["window_close_t"] == session.t_end
        if c.cancelled:
            assert t_c < times[ident("event", "cancel")] < row["window_open_t"]
            assert (ident("event", "cancel"), ident("fact", "made"), "retract") in links
        if c.trigger == "time":
            assert row["window_open_t"] == session.t_start and row["lures_json"] == []
            assert row["window_close_t"] - row["window_open_t"] == 3_600
        else:
            assert times[ident("event", "trigger")] == row["window_open_t"]
            assert row["lures_json"] == [ident("event", "lure", j) for j in range(len(c.lures))]
            lure_t = [times[e] for e in row["lures_json"]]
            assert lure_t == sorted(lure_t) and all(t_c < t < row["window_close_t"] for t in lure_t)
            assert row["window_open_t"] not in lure_t
        if c.trigger == "cue":
            assert t_c < times[ident("event", "bridge")] < row["window_open_t"]
    assert {e["kind"] for e in d["event"]} == {"statement", "notice"}


def check_life(db, schedule, stages):
    tokens = db.execute("SELECT fact_id, value FROM locked_token").fetchall()
    assert len(tokens) == 115 and all(MINTED.match(v) for _, v in tokens)
    check_tokens(db)
    values = dict(tokens)
    for f in db.execute("SELECT * FROM fact"):
        assert (f["modality"], f["speech_act"] in ("assert", "hedge", "quote")) == ("stated", True)
        assert json.loads(f["object"]) == values[f["id"]]
        assert db.execute("SELECT count(*) FROM link WHERE fact_id=? AND role='assert'", (f["id"],)).fetchone()[0] == 1
    slots = {slot(schedule, k, n) for k in range(1, 21) for n in range(1, TURNS + 1)}
    assert {t for (t,) in db.execute("SELECT t_sim FROM event")} == slots
    assert stages["filler_count"] == 100 - len(stages["occupied"]) == len(stages["filler"]["event"])
    assert set(stages["filler"]) == {"event"}
    assert {(e["kind"], e["salience"]) for e in stages["filler"]["event"]} <= {("filler", LOW_SALIENCE)}
    # G08 absent at base: the static form of its consumer contract.
    assert {f["speech_act"] for f in db.execute("SELECT speech_act FROM fact")} <= set(SPEECH_ACTS)
    assert not db.execute("SELECT 1 FROM fact WHERE modality IN ('planted', 'inferred_allowed')").fetchall()
    export_world(db)


def test_mixes_exact(tmp_path):
    for seed in SEEDS:
        a, b, c = mixes()
        db, schedule, stages = build(tmp_path / f"{seed}.db", seed)
        check_corrections(db, schedule, stages["corrections"], a)
        check_commitments(db, schedule, stages["commitments"], b)
        d = stages["incidental"]
        assert [len(d[t]) for t in ("event", "fact", "locked_token", "attr")] == [16] * 4
        assert {e["salience"] for e in d["event"]} == {LOW_SALIENCE}
        assert Counter(f["predicate"] for f in d["fact"]) == {p: 4 for p in PREDICATES[:4]}
        check_life(db, schedule, stages)
        assert {e["salience"] for e in stages["commitments"]["event"]} == {SALIENCE}
        db.close()
    assert DECOY_RATIO_LABEL == "provisional pending PREREG-v0.5"


def test_surfaces_and_explicit_values(tmp_path):
    db, schedule = world(tmp_path / "w.db", "g03-surface")
    c = chain(0, 1, "hedge", 1, channel="mail", surfaces=("notes",), at=((2, 1), (4, 3), (9, 5)),
              values=("Ålborg", "Bergen", "Cádiz", "Dover"))
    write_corrections(db, schedule, [c], principal=PRINCIPAL)
    write_commitments(db, schedule, [commitment(0, "event", True, 1, surfaces=("calendar",))], principal=PRINCIPAL)
    got = {(json.loads(f["object"]), s["surface"], s["from_t"]) for s in db.execute("SELECT * FROM fact_surface")
           for f in db.execute("SELECT object FROM fact WHERE id=?", (s["fact_id"],))}
    t = [slot(schedule, *p) for p in c.at]
    for value, ti in (("Ålborg", t[0]), ("Dover", t[0]), ("Bergen", t[1])):
        assert {(value, "notes", ti), (value, "mail", ti)} <= got
    assert ("Cádiz", "mail", t[2]) in got and ("Cádiz", "notes", t[2]) not in got
    assert {s for _, s, _ in got} <= set(SURFACES) and {s for _, s, _ in got} == {"notes", "mail", "calendar"}
    assert as_valid(db, name(0), "seat", t[2]) == "Dover"


def test_token_refusals_and_retry(tmp_path):
    db, schedule = world(tmp_path / "w.db", "g03-tokens")
    insert_event(db, id="ev", t_sim=0, kind="statement", channel="chat", actor_id=PRINCIPAL,
                 audience_json=["agent"], visibility="shared", salience=500, payload_json={})
    insert_fact(db, id="f0", subject_id=PRINCIPAL, predicate="p", object="x", polarity="affirm",
                modality="stated", strength=HARD, speech_act="assert")
    d0, d1 = (uniform_int("g03-tokens", unit(LIFE, "corrections", "chain0"), k, "token:value:0", 100000, 999999)
              for k in (0, 1))
    insert_locked_token(db, token_id="t0", fact_id="f0", kind="code", value=f"PRE-{d0}")
    assert token_value(db, schedule, "corrections", "chain0", "value", 0, "VALUE") == f"VALUE-{d1}"
    write_corrections(db, schedule, [chain(0, 1)], principal=PRINCIPAL)
    assert db.execute("SELECT value FROM locked_token WHERE token_id=?",
                      (mint(schedule, "corrections", "chain0", "token", "value", 0),)).fetchone()[0] == f"VALUE-{d1}"
    for i, values in enumerate([("AB-123456", "AB-123456"), ("AB-123456", "XAB-123456"), ("Café",)]):
        bad, _ = world(tmp_path / f"bad{i}.db", "g03-tokens")
        insert_event(bad, id="ev", t_sim=0, kind="statement", channel="chat", actor_id=PRINCIPAL,
                     audience_json=["agent"], visibility="shared", salience=500, payload_json={})
        insert_fact(bad, id="f", subject_id=PRINCIPAL, predicate="p", object="x", polarity="affirm",
                    modality="stated", strength=HARD, speech_act="assert")
        for j, v in enumerate(values):
            insert_locked_token(bad, token_id=f"t{j}", fact_id="f", kind="code", value=v)
        with pytest.raises(ValueError):
            check_tokens(bad)
    with pytest.raises(ValueError):
        token_value(db, schedule, "corrections", "chain0", "value", 0, "AB1")


@pytest.mark.parametrize("paired", [False, True], ids=["made", "cancellation"])
@pytest.mark.parametrize("relation", ["contains", "contained-in"])
def test_token_containment_retries_same_attempt_sequence(tmp_path, monkeypatch, paired, relation):
    db, schedule = world(tmp_path / "w.db", "g03-containment")
    first = 654321 if paired else 123456
    # Seven digits hide the candidate's six-digit number from NUMBER, so only containment rejects it.
    existing = str(first)[1:5] if relation == "contains" else f"XVALUE-{first}7"
    insert_fact(db, id="f0", subject_id=PRINCIPAL, predicate="p", object=existing, polarity="affirm",
                modality="stated", strength=HARD, speech_act="assert")
    insert_locked_token(db, token_id="t0", fact_id="f0", kind="code", value=existing)
    calls = []

    def draw(seed, key, attempt, label, lo, hi):
        calls.append((seed, key, attempt, label, lo, hi))
        return 112233 if key == unit(LIFE, "corrections", "chain1") else (123456, 987654)[attempt]

    monkeypatch.setattr(processes, "uniform_int", draw)
    monkeypatch.setattr(processes, "pair", lambda schedule, d: {123456: 654321, 987654: 876543}[d])
    assert token_value(db, schedule, "corrections", "chain0", "value", 0, "VALUE", paired=paired) == "VALUE-987654"
    assert calls == [(schedule.seed, unit(LIFE, "corrections", "chain0"), attempt, "token:value:0", 100000, 999999)
                     for attempt in (0, 1)]
    # A different draw retains attempt zero, even after the retry above.
    assert token_value(db, schedule, "corrections", "chain1", "value", 0, "OTHER") == "OTHER-112233"
    assert calls[-1] == (schedule.seed, unit(LIFE, "corrections", "chain1"), 0, "token:value:0", 100000, 999999)
    db.close()


def test_token_without_containment_preserves_attempt_zero(tmp_path, monkeypatch):
    db, schedule = world(tmp_path / "w.db", "g03-containment")
    # Reuse the containment retry test's attempt sequence: 123456, then 987654.
    draws = (123456, 987654)
    first, later = (f"VALUE-{number}" for number in draws)
    short = str(draws[0])[1:5]
    insert_fact(db, id="f0", subject_id=PRINCIPAL, predicate="p", object=short, polarity="affirm",
                modality="stated", strength=HARD, speech_act="assert")
    insert_locked_token(db, token_id="t0", fact_id="f0", kind="code", value=short)
    calls = []

    def draw(seed, key, attempt, label, lo, hi):
        calls.append((seed, key, attempt, label, lo, hi))
        return draws[attempt]

    monkeypatch.setattr(processes, "uniform_int", draw)
    unchecked = token_value(db, schedule, "corrections", "chain0", "value", 0, "VALUE", containment=False)
    assert unchecked == first and short in unchecked
    expected = [(schedule.seed, unit(LIFE, "corrections", "chain0"), attempt, "token:value:0", 100000, 999999)
                for attempt in (0, 1)]
    assert calls == expected[:1]
    calls.clear()
    checked = token_value(db, schedule, "corrections", "chain0", "value", 0, "VALUE")
    assert checked == later and short not in checked and checked != unchecked
    assert calls == expected
    db.close()


@pytest.mark.parametrize("existing", ["VALUE", "VALUE-"])
def test_token_prefix_collision_refuses(tmp_path, existing):
    db, schedule = world(tmp_path / "w.db", "g03-prefix")
    insert_fact(db, id="f0", subject_id=PRINCIPAL, predicate="p", object=existing, polarity="affirm",
                modality="stated", strength=HARD, speech_act="assert")
    insert_locked_token(db, token_id="t0", fact_id="f0", kind="code", value=existing)
    with pytest.raises(ValueError, match="token stem contains a locked token"):
        token_value(db, schedule, "corrections", "chain0", "value", 0, "VALUE")
    db.close()


HASH = ("import sys; sys.path.insert(0, sys.argv[1]); import test_processes_a as t; "
        "print(t.world_hash(t.build(sys.argv[2], sys.argv[3])[0]))")


def test_determinism(tmp_path):
    hashes = [subprocess.check_output([sys.executable, "-c", HASH, str(Path(__file__).parent),
                                       str(tmp_path / f"{h}.db"), "g03-det"],
                                      env=dict(os.environ, PYTHONHASHSEED=h), timeout=120).strip()
              for h in ("0", "random")]
    assert hashes[0] == hashes[1]
    first, second = (build(tmp_path / f"again{i}.db", "g03-det")[0] for i in range(2))
    assert export_jsonl(first) == export_jsonl(second) and world_hash(first).encode() == hashes[0]
    assert world_hash(build(tmp_path / "other.db", "g03-other")[0]) != hashes[0].decode()


def test_keyed_independence(tmp_path):
    for seed in SEEDS:
        base = build(tmp_path / f"{seed}-a.db", seed)[0]
        more = build(tmp_path / f"{seed}-b.db", seed, mixes(extra=True))[0]
        assert non_filler(base) <= non_filler(more)
        base.close()
        more.close()


def test_twin_flips(tmp_path):
    for i, seed in enumerate([*SEEDS, "g03-11577"]):  # g03-11577: commit1's cancel number is commit7's lure draw
        a, b, c = mixes()
        flipped = [replace(x, cancelled=not x.cancelled) for x in b]
        one = build(tmp_path / f"{seed}-x.db", seed, (a, b, c))[0]
        two = build(tmp_path / f"{seed}-y.db", seed, (a, flipped, c))[0]
        for sql in ("SELECT id, object FROM fact", "SELECT token_id, value FROM locked_token"):
            x, y = (dict(db.execute(sql).fetchall()) for db in (one, two))
            assert {k: x[k] for k in x.keys() & y.keys()} == {k: y[k] for k in x.keys() & y.keys()}, seed
        diff = rows(non_filler(one) ^ non_filler(two))
        schedule = build_schedule(seed, LIFE, named("t1"))
        def ident(x, table, part, schedule=schedule):
            return mint(schedule, "commitments", x.id, table, part, 0)
        assert sorted(diff) == ["event", "fact", "link", "locked_token"]
        assert sorted(r["id"] for r in diff["event"]) == sorted(ident(x, "event", "cancel") for x in b)
        assert sorted(r["id"] for r in diff["fact"]) == sorted(ident(x, "fact", "cancel") for x in b)
        assert sorted(r["token_id"] for r in diff["locked_token"]) == sorted(ident(x, "token", "cancel") for x in b)
        assert sorted((r["event_id"], r["fact_id"], r["role"]) for r in diff["link"]) == sorted(
            (ident(x, "event", "cancel"), ident(x, "fact", part), role) for x in b
            for part, role in (("made", "retract"), ("cancel", "assert")))
        depth = i % 6
        pair = [build(tmp_path / f"{seed}-{k}.db", seed, ([chain(0, depth + k, "hedge" if k == 0 else None)], [], []),
                      filler=False)[0] for k in (0, 1)]
        hedge, corrected = (rows(lines(db)) for db in pair)
        for table in ("event", "locked_token", "session", "entity"):
            assert sorted(map(canon, hedge[table])) == sorted(map(canon, corrected[table]))
        fact_diff = rows(lines(pair[0]) ^ lines(pair[1]))
        target = mint(schedule, "corrections", "chain0", "fact", "value", depth + 1)
        assert {r["id"] for r in fact_diff["fact"]} == {target} and len(fact_diff["fact"]) == 2
        assert {(r["role"], r["fact_id"]) for r in fact_diff["link"]} == {
            ("retract", mint(schedule, "corrections", "chain0", "fact", "value", depth))}
        assert len(fact_diff["link"]) == 1 and set(fact_diff) == {"fact", "link", "attr"}
        assert len(fact_diff["attr"]) == 3 and len(corrected["attr"]) == len(hedge["attr"]) + 1
        for db in (one, two, *pair):
            db.close()


CHAIN = dict(id="c", subject=name(0), key="status", stem="VALUE", depth=1, mention="hedge")
DETAIL = dict(id="d", subject=name(0), predicate="locker", stem="LOCKER", decoys=(name(1), name(2), name(3)))


def test_refusal_bases_are_valid(tmp_path):
    db, schedule = world(tmp_path / "w.db", "g03-refuse")
    write_corrections(db, schedule, [Chain(**CHAIN)], principal=PRINCIPAL)
    write_commitments(db, schedule, [commitment(0, "cue", False, 0)], principal=PRINCIPAL)
    write_details(db, schedule, [Detail(**DETAIL)], principal=PRINCIPAL)
    assert db.execute("SELECT count(*) FROM locked_token").fetchone()[0] == 3 + 2 + 4


def refuse(tmp_path, call, scale=None, schedule_seed=None):
    db, schedule = world(tmp_path / f"r{next(WORLDS)}.db", "g03-refuse", scale)
    if schedule_seed is not None:
        schedule = build_schedule(schedule_seed, LIFE, scale or named("t1"))
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        call(db, schedule)
    assert export_jsonl(db) == before


@pytest.mark.parametrize("spec", [
    dict(depth=7), dict(depth=0, mention=None), dict(depth=-1), dict(depth=True), dict(mention="aside"),
    dict(mention="third_party"), dict(third_party=OUTSIDER), dict(mention="third_party", third_party=PRINCIPAL),
    dict(sibling="status"), dict(stem="Value"), dict(stem="V"), dict(stem="VALUE1"), dict(strength=1001),
    dict(strength=True), dict(strength=500.0), dict(surfaces=("wiki",)), dict(token_kind="secret"),
    dict(at=((1, 1), (2, 1))), dict(at=((2, 1), (2, 2), (3, 1))), dict(at=((1, 1), (2, 6), (3, 1))),
    dict(values=("Ålborg", "Bergen")), dict(values=("Ålborg", "Bergen", "Cad")),
    dict(values=("Ålborg", "Bergen", "Cadiz")), dict(subject="Nobody"), dict(id=""),
])
def test_chain_refusals(tmp_path, spec):
    refuse(tmp_path, lambda db, s: write_corrections(db, s, [Chain(**CHAIN | spec)], principal=PRINCIPAL))


@pytest.mark.parametrize("values", [("same", "same"), ("same", "xsamex"), ("xsamex", "same"), ("VALUE-1", "PRE-0")])
def test_explicit_values_refused_before_insert(tmp_path, values):
    db, schedule = world(tmp_path / "w.db", "g03-refuse")
    insert_event(db, id="ev", t_sim=0, kind="statement", channel="chat", actor_id=PRINCIPAL,
                 audience_json=["agent"], visibility="shared", salience=500, payload_json={})
    insert_fact(db, id="f0", subject_id=PRINCIPAL, predicate="p", object="x", polarity="affirm",
                modality="stated", strength=HARD, speech_act="assert")
    insert_locked_token(db, token_id="t0", fact_id="f0", kind="code", value="PRE-0")
    counts = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_corrections(db, schedule, [Chain(**CHAIN | dict(mention=None, values=values))], principal=PRINCIPAL)
    assert {t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES} == counts
    assert export_jsonl(db) == before


def _snapshot(db):
    return ({t: db.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}, export_jsonl(db))


def test_explicit_values_after_generated_chain_refuse_atomically(tmp_path):
    db, schedule = world(tmp_path / "w.db", "g03-mixed-values")
    before = _snapshot(db)
    with pytest.raises(ValueError, match="locked token duplicates or is a substring of another"):
        write_corrections(db, schedule, [chain(0, 1, surfaces=("notes",)),
                                        chain(1, 1, values=("VALUE", "OTHER"))], principal=PRINCIPAL)
    assert _snapshot(db) == before
    assert db.in_transaction
    # The refused batch's ids are available again in the caller's transaction.
    write_corrections(db, schedule, [chain(0, 1)], principal=PRINCIPAL)
    db.close()


@pytest.mark.parametrize("writer", ["corrections", "commitments"])
@pytest.mark.parametrize("open_transaction", [False, True])
def test_writer_integrity_refusal_is_atomic(tmp_path, writer, open_transaction):
    db, schedule = world(tmp_path / "w.db", "g03-integrity")
    if writer == "corrections":
        write_corrections(db, schedule, [chain(0, 1)], principal=PRINCIPAL)
        specs = [chain(1, 1, surfaces=("notes",)), replace(chain(2, 1), subject=name(0))]
        write, message = write_corrections, "overlapping validity"
    else:
        write_commitments(db, schedule, [commitment(1, "time", False, 0)], principal=PRINCIPAL)
        specs = [commitment(0, "cue", True, 1, surfaces=("calendar",)), commitment(1, "time", False, 0)]
        write, message = write_commitments, "UNIQUE constraint failed: event.id"
    if not open_transaction:
        db.commit()
    before = _snapshot(db)
    # The first spec succeeds; the second hits a real database constraint after writes.
    with pytest.raises(sqlite3.IntegrityError, match=message):
        write(db, schedule, specs, principal=PRINCIPAL)
    assert _snapshot(db) == before
    assert db.in_transaction
    db.close()


@pytest.mark.parametrize("writer", ["corrections", "commitments"])
def test_writer_final_token_refusal_is_atomic(tmp_path, monkeypatch, writer):
    db, schedule = world(tmp_path / "w.db", "g03-final-check")
    before = _snapshot(db)

    def refuse_after_writes(db):
        counts, _ = _snapshot(db)
        assert all(counts[t] > before[0][t] for t in ("event", "fact", "locked_token", "link", "fact_surface"))
        raise ValueError("final token refusal")

    monkeypatch.setattr(f"bicentennial.world.processes.{writer}.check_tokens", refuse_after_writes)
    if writer == "corrections":
        write, specs = write_corrections, [chain(0, 1, "hedge", 1, surfaces=("notes",))]
    else:
        write, specs = write_commitments, [commitment(0, "cue", True, 1, surfaces=("calendar",))]
    with pytest.raises(ValueError, match="final token refusal"):
        write(db, schedule, specs, principal=PRINCIPAL)
    assert _snapshot(db) == before
    assert db.in_transaction
    db.close()


def test_writer_level_refusals(tmp_path):
    def write(*chains, principal=PRINCIPAL):
        return lambda db, s: write_corrections(db, s, chains, principal=principal)
    refuse(tmp_path, write(chain(0, 1)), schedule_seed="g03-other")
    refuse(tmp_path, write(chain(0, 1), principal="Nobody"))
    refuse(tmp_path, write(chain(0, 1), replace(chain(1, 1), subject=name(0))))
    refuse(tmp_path, write(chain(0, 1, sibling=1), replace(chain(1, 1), id="x", subject=name(0), key="seat")))
    refuse(tmp_path, write(chain(0, 1), replace(chain(1, 1), id="chain0")))
    refuse(tmp_path, write(chain(0, 2, "hedge")), scale=named("t0-micro", sessions=3))
    for s in (1, 2, 3):
        refuse(tmp_path, lambda db, sch: slot(sch, 0, 1) and None, scale=named("t0-micro", sessions=s))
        refuse(tmp_path, lambda db, sch, s=s: slot(sch, s, TURNS + 1) and None, scale=named("t0-micro", sessions=s))


@pytest.mark.parametrize("spec,scale", [
    (dict(trigger="tuesday"), None), (dict(lures=(name(1),), trigger="time", cue_subject=None, cue_key=None,
                                            cue_stem=None, sender=None), None),
    (dict(trigger="time"), None), (dict(cue_key=None), None), (dict(sender=None), None),
    (dict(lures=(name(120),)), None), (dict(lures=(name(1), name(1))), None), (dict(cancelled=1), None),
    (dict(made=(3, 2), due=(3, 2)), None), (dict(made=(4, 1), due=(3, 2)), None),
    (dict(made=(3, 5), due=(4, 1)), None), (dict(made=(3, 3), due=(3, 5), lures=(name(1), name(2))), None),
    (dict(stem="task"), None), (dict(cue_stem="P"), None), (dict(surfaces=("wiki",)), None),
    (dict(sender="Nobody"), None), (dict(lures=("Nobody",)), None), (dict(made=(1, 1), due=(21, 1)), None), (dict(made=(1, 1, 1)), None), (dict(due=[2, 1]), None),
    (dict(), named("t0-micro", sessions=1)),
])
def test_commitment_refusals(tmp_path, spec, scale):
    c = replace(commitment(0, "cue", False, 0), **spec)
    refuse(tmp_path, lambda db, s: write_commitments(db, s, [c], principal=PRINCIPAL), scale=scale)


def test_commitment_explicit_placement(tmp_path):
    db, schedule = world(tmp_path / "w.db", "g03-explicit")
    write_commitments(db, schedule, [commitment(0, "time", True, 0, made=(3, 3), due=(3, 5))], principal=PRINCIPAL)
    row = db.execute("SELECT * FROM commitment").fetchone()
    assert (row["window_open_t"], row["window_close_t"]) == (slot(schedule, 3, 5), schedule.sessions[2].t_end)
    assert db.execute("SELECT t_sim FROM event WHERE id=?", (mint(
        schedule, "commitments", "commit0", "event", "cancel", 0),)).fetchone()[0] == slot(schedule, 3, 4)


@pytest.mark.parametrize("spec,ratio", [
    (dict(decoys=(name(1), name(2))), 3), (dict(decoys=(name(1), name(2))), 2), (dict(), True),
    (dict(decoys=(name(0), name(1), name(2))), 3), (dict(decoys=(name(1), name(1), name(2))), 3),
    (dict(decoys=[name(1), name(2), name(3)]), 3), (dict(at=((1, 1),) * 3), 3), (dict(at=((1, 1),) * 3 + ((0, 1),)), 3),
    (dict(stem="lock"), 3), (dict(surfaces=("wiki",)), 3), (dict(token_kind="secret"), 3),
    (dict(decoys=(name(1), name(2), "Nobody")), 3),
])
def test_detail_refusals(tmp_path, spec, ratio):
    d = Detail(**DETAIL | spec)
    refuse(tmp_path, lambda db, s: write_details(db, s, [d], principal=PRINCIPAL, ratio=ratio))


def test_details_share_pair_refused(tmp_path):
    twins = [detail(0), replace(detail(1), subject=name(201), predicate="locker")]
    refuse(tmp_path, lambda db, s: write_details(db, s, twins, principal=PRINCIPAL))


def test_filler_refusals_and_idempotence(tmp_path):
    refuse(tmp_path, lambda db, s: write_filler(db, s, principal="Nobody"))
    refuse(tmp_path, lambda db, s: write_filler(db, s, principal=PRINCIPAL), schedule_seed="g03-other")
    db, schedule = world(tmp_path / "w.db", "g03-filler")
    assert write_filler(db, schedule, principal=PRINCIPAL) == 100
    assert write_filler(db, schedule, principal=PRINCIPAL) == 0
    assert not db.execute("SELECT 1 FROM link").fetchall()


def test_no_forbidden_imports():
    banned = {"random", "time", "socket", "ssl", "http", "urllib", "bicentennial.sandbox"}
    for path in (Path(__file__).parents[2] / "src/bicentennial/world/processes").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for n in names:
                assert not any(n == b or n.startswith(b + ".") for b in banned), (path, n)
