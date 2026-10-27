"""G11 offline goldens, contract agreement and keyed property loops."""

import ast
import copy
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.items import (
    CELL_IDS,
    DEFERRED_CELLS,
    LEVERS,
    Instance,
    Option,
    Template,
    cell_stage,
    cell_track,
    check_precondition,
    compile_branch,
    compile_life,
    compute,
    decisive_fact,
    memory_tag,
    unfiltered_sample,
    wake_points,
)
from bicentennial.items.protocol import CANARY
from bicentennial.keyed import shuffle, uniform_int
from bicentennial.render import render_event
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import content
from bicentennial.score.action import Trace, score_action
from bicentennial.score.qa import score_qa
from bicentennial.world import create_world, open_world, unit, world_hash
from bicentennial.world.db import (
    insert_attr,
    insert_commitment,
    insert_entity,
    insert_event,
    insert_fact,
    insert_fact_surface,
    insert_forget_request,
    insert_link,
    insert_locked_token,
    insert_plant,
)
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions
from bicentennial.world.tokens import estimate_tokens

SEED = "g11-golden"
LIFE = "life-a"
STATE = {i: {"repo_tree_hash": "a" * 64, "env_state_hash": "b" * 64} for i in range(1, 4)}
ROOT = Path(__file__).resolve().parents[2]


def table(gold="act", timed=False):
    return dict(canary=CANARY, table_id=f"{gold}-{'timed' if timed else 'plain'}", gold=gold,
                timed=timed, admissible=["gold_state"], disqualifiers=[], benign_extras=[])


def plan(value=None, tool="book_seat"):
    return {"steps": [] if value is None else [{"tool": {"name": tool, "args": {"value": value}}}]}


@dataclass(frozen=True, kw_only=True, eq=False)
class Stub(Template):
    rows: tuple[Instance, ...] = ()

    def instances(self, db, schedule):
        return self.rows


def template(rows=(), **kwargs):
    args = dict(template_id="recall", version=1, cell_id="RECALL-VERB", kind="qa", twin_type=None,
                direction="verbatim retention", semantics="as_known", rows=tuple(rows))
    return Stub(**(args | kwargs))


def entity(db, eid):
    insert_entity(db, id=eid, kind="person", canonical_name=eid, aliases_json=[], created_t=0, retired_t=None)


def event(db, schedule, eid, slot, *, audience=("agent",), t=None):
    s, n = slot
    t = schedule.sessions[s - 1].turn_t[n - 1] + 60 if t is None else t
    insert_event(db, id=eid, t_sim=t, kind="chat", channel="chat", actor_id="principal",
                 audience_json=list(audience), visibility="shared", salience=500, payload_json={})
    return t


def fact(db, fid, value, *, subject="principal", predicate="seat", modality="stated", token=True):
    insert_fact(db, id=fid, subject_id=subject, predicate=predicate, object=value,
                polarity="affirm", modality=modality, strength=1000, speech_act="assert")
    if token:
        insert_locked_token(db, token_id=f"token-{fid}", fact_id=fid, kind="code", value=value)


def assertion(db, schedule, fid, value, slot, **kwargs):
    event(db, schedule, f"event-{fid}", slot)
    fact(db, fid, value, **kwargs)
    insert_link(db, event_id=f"event-{fid}", fact_id=fid, role="assert")


def world(path, *, wake=None, scale=None):
    schedule = build_schedule(SEED, LIFE, scale or named("t0-micro", sessions=3, wake=wake))
    db = create_world(path, dict(generator_version="g11-test", genre="G2", seed=SEED,
                                 scale=len(schedule.sessions)))
    write_sessions(db, schedule)
    entity(db, "principal")
    for p in schedule.sessions:
        for n in range(1, len(p.turn_t) + 1):
            event(db, schedule, f"chat-{p.index}-{n}", (p.index, n))
    return db, schedule


def make_cut(db, schedule, branch="B0"):
    expected = {i: STATE[1] for i in range(1, len(schedule.sessions) + 1)}
    return cut(db, schedule, branch=branch, principal_id="principal", expected_state=expected)


def qa_instance(*, spans=("event-detail",), fid="detail", token_fids=("detail",), value="WINDOW-7401", **kwargs):
    return Instance(**(dict(key="one", probe_point=3, prompt="Which value was stated?",
                           options=(Option(key="gold", token_fact_ids=token_fids,
                                           envelope={"type": "entity", "value": value}),
                                    Option(key="unknown", token_fact_ids=(), envelope={"type": "unknown", "value": None})),
                           gold_spans=spans, decisive_fact_id=fid) | kwargs))


class Golden(Template):
    def instances(self, db, schedule):
        k = schedule.scale.checkpoints[-1]
        if self.twin_type == "fork":
            fid = decisive_fact(db, "principal", "seat", schedule.sessions[k - 1].t_end, self.semantics)
            value = json.loads(db.execute("SELECT object FROM fact WHERE id=?", (fid,)).fetchone()[0])
            options = [Option(key="gold", token_fact_ids=(fid,), plan=plan(value))]
            for other in ("stale", "decoy-a", "decoy-b"):
                val = json.loads(db.execute("SELECT object FROM fact WHERE id=?", (other,)).fetchone()[0])
                options.append(Option(key=other, token_fact_ids=(other,), plan=plan(val)))
            options.append(Option(key="refrain", token_fact_ids=(), plan=plan()))
            spans, ref, duty = ("event-detail",), table()["table_id"], True
        elif self.twin_type == "lure":
            cancelled = bool(db.execute("SELECT 1 FROM fact WHERE id='cancel'").fetchone())
            value = "CANCEL-6631" if cancelled else "TASK-5521"
            options = [Option(key="gold", token_fact_ids=("cancel" if cancelled else "detail",),
                              plan=plan() if cancelled else plan(value, "do_task")),
                       Option(key="refrain", token_fact_ids=(), plan=plan())]
            spans = ("event-detail", "event-cancel") if cancelled else ("event-detail",)
            fid, ref, duty = "detail", table("refrain" if cancelled else "act", True)["table_id"], True
        elif self.twin_type == "trigger":
            forgotten = bool(db.execute("SELECT 1 FROM forget_request").fetchone())
            use = Option(key="use", token_fact_ids=("detail",), plan=plan("GATE-4410", "use_detail"))
            refrain = Option(key="refrain", token_fact_ids=(), plan=plan())
            options = [refrain, use] if forgotten else [use, refrain]
            spans = ("event-detail", "event-request") if forgotten else ("event-detail",)
            fid, ref, duty = "detail", table("refrain" if forgotten else "act")["table_id"], False
        else:
            text = render_event(db, "event-detail", life=LIFE, tz=schedule.tz).text
            # Classification is chosen from observable provenance, never the plant table or supplied gold.
            classification = "planted" if "PLANTED-7712" in text else "told" if "TOLD-9912" in text else None
            assert classification is not None
            options = [Option(key=role, token_fact_ids=(role,), envelope={"type": "entity", "value": role})
                       for role in (classification, "told" if classification == "planted" else "planted")]
            options.append(Option(key="unknown", token_fact_ids=(), envelope={"type": "unknown", "value": None}))
            spans, fid, ref, duty = ("event-detail",), "detail", None, False
        return (Instance(key="one", probe_point=k, prompt="Apply the remembered evidence.", options=tuple(options),
                         gold_spans=spans, decisive_fact_id=fid, decision_table_ref=ref, duty=duty),)


def golden(path, twin_type="fork", branch="B0", wake=None):
    db, schedule = world(path, wake=wake)
    if twin_type == "fork":
        assertion(db, schedule, "stale", "MIDDLE-3301", (1, 1))
        value = "WINDOW-7401" if branch == "B0" else "AISLE-9201"
        assertion(db, schedule, "detail", value, (1, 2))
        insert_link(db, event_id="event-detail", fact_id="stale", role="retract")
        insert_attr(db, entity_id="principal", key="seat", value="MIDDLE-3301", valid_from_t=0,
                    valid_to_t=schedule.sessions[0].turn_t[1] + 60, recorded_t=schedule.sessions[0].turn_t[0] + 60,
                    source_event_id="event-stale")
        insert_attr(db, entity_id="principal", key="seat", value=value,
                    valid_from_t=schedule.sessions[0].turn_t[1] + 60, valid_to_t=None,
                    recorded_t=schedule.sessions[0].turn_t[1] + 60, source_event_id="event-detail")
        for n, name in enumerate(("decoy-a", "decoy-b"), 1):
            entity(db, name)
            assertion(db, schedule, name, f"OTHER-{n}229", (2, n), subject=name)
        cell, kind, tables = "WAKE-PREF", "act", (table(),)
    elif twin_type == "lure":
        assertion(db, schedule, "detail", "TASK-5521", (1, 2), predicate="task")
        insert_commitment(db, fact_id="detail", trigger_kind="event", window_open_t=1700042477,
                          window_close_t=1700045357, lures_json=[])
        if branch == "B1":
            assertion(db, schedule, "cancel", "CANCEL-6631", (2, 1), predicate="cancel")
            insert_link(db, event_id="event-cancel", fact_id="detail", role="retract")
        cell, kind, tables = "TUE-CUE", "act", (table(timed=True), table("refrain", True))
    elif twin_type == "trigger":
        assertion(db, schedule, "detail", "GATE-4410", (1, 2), predicate="gate")
        if branch == "B0":
            assertion(db, schedule, "request", "gate", (2, 1), predicate="forget", token=False)
            insert_forget_request(db, event_id="event-request", covered_fact_ids_json=["detail"])
        cell, kind, tables = "KEEP-FORGET", "act", (table(), table("refrain"))
    else:
        assertion(db, schedule, "detail", "SAT-7781", (1, 2), predicate="source",
                  modality="planted" if branch == "B0" else "stated")
        fact(db, "planted", "PLANTED-7712", predicate="authority")
        fact(db, "told", "TOLD-9912", predicate="authority")
        insert_link(db, event_id="event-detail", fact_id="planted" if branch == "B0" else "told", role="assert")
        if branch == "B0":
            insert_plant(db, fact_id="detail", carrier_event_id="event-detail", kind="forged")
        cell, kind, tables = "RACH-SRC", "qa", ()
    t = Golden(template_id=f"golden-{twin_type}", version=1, cell_id=cell, kind=kind,
               twin_type=twin_type, direction="none", semantics="as_known", decision_tables=tables)
    c = make_cut(db, schedule, branch)
    b = compile_branch(db, schedule, c, [t])
    return db, schedule, c, t, b


@pytest.mark.parametrize("twin_type", ("fork", "lure", "trigger", "genuine"))
def test_golden_twins(tmp_path, twin_type):
    d0, s, c0, t, b0 = golden(tmp_path / "b0.db", twin_type)
    d1, _, c1, _, b1 = golden(tmp_path / "b1.db", twin_type, "B1")
    result = compile_life(b0, b1)
    assert len(result.bundles) == 1
    bundle = result.bundles[0]
    assert bundle["twin_type"] == twin_type and bundle["decisive_fact_id"] == "detail"
    assert bundle["items"] == [b0.entries[0][0]["item_id"], b1.entries[0][0]["item_id"]]
    assert {i["stage"] for i in result.items} == {"remember" if twin_type == "genuine" else "act"}
    for contract, values in (("item", result.items), ("bundle", result.bundles), ("item_record", result.records)):
        for value in values:
            validate(contract, value)
    assert len({r["unfiltered_sample"] for r in result.records}) == 1
    assert result.singleton_lives() == {}
    assert result.duty_items() == (frozenset(i["item_id"] for i in result.items) if twin_type in ("fork", "lure") else frozenset())
    with pytest.raises(ValueError, match="different gold"):
        compile_life(b0, compile_branch(d0, s, replace(c0, branch="B1"), [t]))
    i0, i1 = b0.entries[0][0], b1.entries[0][0]
    assert {o["option_id"] for o in i0["options"]} == {o["option_id"] for o in i1["options"]}
    if twin_type == "fork":
        assert i0["options"][0]["tokens"] == ["WINDOW-7401"]
        assert i1["options"][0]["tokens"] == ["AISLE-9201"]
        fixture = json.loads((SCHEMAS / "fixtures/gen/pack.json").read_bytes())
        pack = dict(canary=CANARY, pack_id="test", tier="T0", genre="G2", seeds=[], lives=[LIFE],
                    items=list(result.items), bundles=list(result.bundles), qa_order=[], controls=fixture["controls"], hashes={})
        validate("pack", pack)
    elif twin_type == "lure":
        assert i0["options"][0]["tokens"] == ["TASK-5521"]
        assert i1["options"][0]["tokens"] == ["CANCEL-6631"]
        assert i0["options"][0]["plan"]["steps"] and not i1["options"][0]["plan"]["steps"]
    elif twin_type == "trigger":
        assert i0["options"][0]["tokens"] == [] and i1["options"][0]["tokens"] == ["GATE-4410"]
        assert d0.execute("SELECT object FROM fact WHERE predicate='forget'").fetchone()[0] == canon("gate").decode()
        assert not d1.execute("SELECT 1 FROM forget_request").fetchone()
    else:
        for item, c, expected in ((i0, c0, "planted"), (i1, c1, "told")):
            context = "".join(content(r) for r in c.rows)
            option = next(o for o in reader_view(item)["options"] if o["tokens"] and all(token in context for token in o["tokens"]))
            assert option["envelope"]["value"] == expected
        scored = score_qa(i0, i0["options"][0]["envelope"] | {"citation": None}, evidence_texts=())
        assert scored.score_milli == 1000
    d0.close()
    d1.close()


@pytest.mark.parametrize("twin,branch", [("fork", "B0"), ("lure", "B0"), ("lure", "B1"), ("trigger", "B0")])
def test_action_scorer_agrees(tmp_path, twin, branch):
    db, _, _, t, b = golden(tmp_path / "world.db", twin, branch)
    item = b.entries[0][0]
    selected_table = next(v for v in t.decision_tables if v["table_id"] == item["decision_table_ref"])
    acts = bool(item["options"][0]["plan"]["steps"])
    trace = Trace(False, acts, 1700042477 if acts and twin == "lure" else None)
    result = score_action(item, selected_table, trace, {"gold_state": acts},
                          window=(1700042477, 1700045357) if twin == "lure" else None)
    assert (result.base_verdict, result.score_milli) == ("PASS", 1000)
    assert result.tuesday_class == ("on_time" if acts and twin == "lure" else None)
    db.close()


def test_option_order_and_readonly(tmp_path):
    db, schedule, c, t, b = golden(tmp_path / "world.db")
    item = b.entries[0][0]
    assert item["gold"]["option_id"] == item["options"][0]["option_id"]
    assert item["options"][-1]["tokens"] == []
    source = {o.key: o for o in t.instances(db, schedule)[0].options}
    expected = shuffle(SEED, unit(LIFE, "options", item["item_id"]), 0, "order", sorted(["stale", "decoy-a", "decoy-b"]))
    assert [o["tokens"][0] for o in item["options"][1:-1]] == [
        db.execute("SELECT value FROM locked_token WHERE fact_id=?", (source[key].token_fact_ids[0],)).fetchone()[0]
        for key in expected]
    before = world_hash(db)
    db.commit()
    with open_world(tmp_path / "world.db") as readonly:
        assert compile_branch(readonly, schedule, c, [t]) == b
    assert world_hash(db) == before
    db.close()


@pytest.mark.parametrize("wake,wakes,proximity,crossed", [(None, 3, None, []), ("kill", 4, 9, ["crash"])])
def test_lever_golden(tmp_path, wake, wakes, proximity, crossed):
    db, schedule, c, _, b = golden(tmp_path / "world.db", wake=wake)
    item, meta = b.entries[0]
    values = meta["levers"]
    assert values | {"distance_tokens_est": 0} == dict(distance_sessions=2, distance_s=44577, dispersion=1,
        interference=2, chain_depth=1, salience=500, fault_proximity=proximity, wake_events=wakes, distance_tokens_est=0)
    anchor_idx = next(n for n, r in enumerate(c.rows) if r["event_id"] == "event-detail")
    assert values["distance_tokens_est"] == estimate_tokens("".join(content(r) for r in c.rows[anchor_idx + 1:])) > 0
    assert meta["crossed"] == crossed and item["stage"] == "act" and item["labels"] == ["voice: template"]
    if wake == "kill":
        values, tags, session = compute(db, schedule, c, gold_spans=("event-detail", "event-decoy-a"),
                                       decisive_fact_id="detail", probe_point=3)
        assert [values[k] for k in ("distance_sessions", "distance_s", "dispersion", "wake_events", "fault_proximity")] == [1, 37643, 2, 3, 5]
        assert tags == ("crash",) and session == 2
    db.close()


@pytest.mark.parametrize("anchor,k,expected,wakes,proximity", [
    ((2, 1), 20, ["compaction", "crash", "swap"], 20, 9),
    ((5, 1), 10, [], 6, None), ((3, 1), 10, ["compaction"], 8, 4),
    ((14, 1), 20, ["swap"], 7, None),
])
def test_t1_levers(tmp_path, anchor, k, expected, wakes, proximity):
    db, schedule = world(tmp_path / "world.db", scale=named("t1"))
    assert [p.index for p in schedule.sessions if p.long_sprint] == [4, 14]
    assert ("kill", 11, 1) in wake_points(schedule) and ("swap", 15, 0) in wake_points(schedule)
    assert [(kind, s) for kind, s, _ in wake_points(schedule) if kind == "gap"] == [("gap", 3), ("gap", 14)]
    s, n = anchor
    event(db, schedule, "evidence", anchor)
    row = dict(event_id="evidence", session_id=schedule.sessions[s - 1].session_id,
               turn_key=f"session/t{n}", t_sim=schedule.sessions[s - 1].turn_t[n - 1] + 60, text="evidence")
    # Function-level test: no sprint filler or render is needed for crossing arithmetic.
    c = type("Rows", (), {"rows": (row,)})()
    values, crossed, session = compute(db, schedule, c, gold_spans=("evidence",), decisive_fact_id=None, probe_point=k)
    assert list(crossed) == expected and values["wake_events"] == wakes and values["fault_proximity"] == proximity
    assert session == s and values["interference"] is values["chain_depth"] is None
    db.close()


@pytest.mark.parametrize("wake,slot,expected", [("kill", (1, 2), "crash"), ("kill", (3, 1), "crash"),
    ("kill", (3, 2), None), ("compaction", (1, 2), "compaction"), ("swap", (1, 2), "swap")])
def test_survive(tmp_path, wake, slot, expected):
    db, schedule = world(tmp_path / "world.db", wake=wake)
    assertion(db, schedule, "detail", "WINDOW-7401", slot)
    b = compile_branch(db, schedule, make_cut(db, schedule), [template([qa_instance()])])
    item = b.entries[0][0]
    assert item["stage"] == ("survive" if expected else "remember")
    assert item["labels"] == ([f"survive:{expected}", "voice: template"] if expected else ["voice: template"])
    db.close()


def test_memory_tag_200_cases_and_supporting_fact(tmp_path):
    db, schedule, _, t, _ = golden(tmp_path / "world.db")
    t_p = schedule.sessions[-1].t_end
    surfaces = ("mail", "notes", "repo", "tracker", "calendar")
    for case in range(200):
        db.execute("SAVEPOINT memtag")
        key, expected = unit("g11", "memtag", str(case)), False
        for n in range(uniform_int(SEED, key, 0, "count", 0, 3)):
            fid = ("detail", "stale", "decoy-a")[uniform_int(SEED, key, 0, f"fact-{n}", 0, 2)]
            surface = surfaces[uniform_int(SEED, key, 0, f"surface-{n}", 0, 4)]
            offset = uniform_int(SEED, key, 0, f"time-{n}", -100, 100)
            db.execute("INSERT OR IGNORE INTO fact_surface VALUES (?, ?, ?)", (fid, surface, t_p + offset))
            expected |= fid == "detail" and offset < 0
        assert memory_tag(db, ["detail"], t_p) == ("env_recoverable" if expected else "memory_exclusive")
        db.execute("ROLLBACK TO memtag")
        db.execute("RELEASE memtag")
    insert_fact_surface(db, fact_id="stale", surface="repo", from_t=0)
    i = t.instances(db, schedule)[0]
    supporting = replace(i.options[0], token_fact_ids=("detail", "stale"))
    stub = template([replace(i, options=(supporting, *i.options[1:]))], template_id=t.template_id,
                    cell_id=t.cell_id, kind=t.kind, twin_type=t.twin_type, decision_tables=t.decision_tables)
    assert compile_branch(db, schedule, make_cut(db, schedule), [stub]).entries[0][0]["memory_tag"] == "memory_exclusive"
    insert_fact_surface(db, fact_id="detail", surface="mail", from_t=t_p - 1)
    assert compile_branch(db, schedule, make_cut(db, schedule), [t]).entries[0][0]["memory_tag"] == "env_recoverable"
    db.close()


def test_unfiltered_200_cases():
    for c in range(200):
        seed, key = f"g11-{c}", unit("g11", "unfiltered-test", str(c))
        counts = {track: uniform_int(seed, key, 0, track, 0, 30) for track in ("Wake", "Recall")}
        units = [(f"{track}-{n}", track) for track in sorted(counts) for n in range(counts[track])]
        selected = unfiltered_sample(seed, LIFE, reversed(units))
        for track in sorted(counts):
            assert len([uid for uid in selected if uid.startswith(track)]) == round(Fraction(counts[track], 5))
        other = unfiltered_sample(seed, LIFE, [*units, ("Recall-extra", "Recall")])
        assert {u for u in other if u.startswith("Wake")} == {u for u in selected if u.startswith("Wake")}
        same = unfiltered_sample(seed, LIFE, [*units, ("Wake-extra", "Wake")])
        assert len(selected ^ same) <= 2 and len(selected - same) <= 1


def test_singletons_never_affect_bundle_sample(tmp_path):
    db, s, c, t, b0 = golden(tmp_path / "b0.db")
    db1, _, _, _, b1 = golden(tmp_path / "b1.db", branch="B1")
    # Repeat independent instance keys to obtain a nonzero 20% bundle quota.
    i = t.instances(db, s)[0]
    ts = template([replace(i, key=f"twin-{n}") for n in range(5)], template_id=t.template_id,
                  cell_id=t.cell_id, kind=t.kind, twin_type=t.twin_type, decision_tables=t.decision_tables)
    i1 = Golden.instances(t, db1, s)[0]
    ts1 = replace(ts, rows=tuple(replace(i1, key=f"twin-{n}") for n in range(5)))
    b0 = compile_branch(db, s, c, [ts])
    b1 = compile_branch(db1, s, make_cut(db1, s, "B1"), [ts1])
    before = compile_life(b0, b1)
    singletons = template([replace(qa_instance(), key=f"single-{n}") for n in range(12)])
    after = compile_life(compile_branch(db, s, c, [ts, singletons]), b1)
    assert sum(r["unfiltered_sample"] for r in before.records) == 2
    flags = {r["item_id"]: r["unfiltered_sample"] for r in after.records}
    assert all(flags[r["item_id"]] == r["unfiltered_sample"] for r in before.records)
    assert len(after.singleton_lives()) == 12 and set(after.singleton_lives().values()) == {LIFE}
    assert all(not flags[iid] for iid in after.singleton_lives())
    db.close()
    db1.close()


def test_precondition(tmp_path):
    db, _, _, _, b = golden(tmp_path / "world.db")
    text = b.entries[0][0]["precondition"]
    assert text == canon(dict(after_session=3, **STATE[3])).decode()
    assert check_precondition(text, **STATE[3])
    for field in ("repo_tree_hash", "env_state_hash"):
        assert not check_precondition(text, **(STATE[3] | {field: "c" * 64}))
    with pytest.raises(ValueError):
        check_precondition(" " + text, **STATE[3])
    db.close()


def test_cell_map():
    rows = [line.split("|")[1:-1] for line in (ROOT / "docs/inventory/CELLS-v0.md").read_text().splitlines()
            if line.startswith("| ") and line.split("|")[1].strip() in CELL_IDS]
    assert len(rows) == 37 and {row[0].strip() for row in rows} == set(CELL_IDS)
    for row in rows:
        cid, track, _, stage, *rest = [x.strip() for x in row]
        assert cell_track(cid) == track and cell_stage(cid) == stage[0]
        assert (cid in DEFERRED_CELLS) == rest[3].startswith("live")


@pytest.mark.parametrize("kwargs", [
    {"template_id": "bad_id"}, {"template_id": "bad\n"}, {"version": 0}, {"version": True},
    {"cell_id": "NO-CELL"}, {"cell_id": "RACH-PLANT"}, {"cell_id": "RACH-PREM"}, {"cell_id": "FAULT-DUP"},
    {"kind": "act"}, {"kind": "other"}, {"cell_id": "WAKE-PREF"}, {"twin_type": "source"},
    {"direction": "distance"}, {"semantics": "latest"}, {"decision_tables": (table(),)},
    {"cell_id": "WAKE-PREF", "kind": "act", "twin_type": None, "decision_tables": (table(),)},
    {"cell_id": "WAKE-PREF", "kind": "act", "twin_type": "fork"},
    {"cell_id": "WAKE-PREF", "kind": "act", "twin_type": "fork", "decision_tables": ({},)},
    {"cell_id": "WAKE-PREF", "kind": "act", "twin_type": "fork", "decision_tables": (table(), table())},
])
def test_template_refusals(kwargs):
    with pytest.raises(ValueError):
        template(**kwargs)


@pytest.mark.parametrize("case", ["duplicate-template", "duplicate-instance", "checkpoint", "missing-span",
    "nongold-span", "late-span", "empty-observed", "nonempty-unobserved", "missing-token", "foreign-plan",
    "prompt-token", "prompt-canary", "table-gold", "qa-duty", "world-hash", "schedule-hash", "seed",
    "fault-remember", "qa-table", "missing-decisive", "unknown-decisive", "duplicate-option", "duplicate-token",
    "bad-envelope", "bad-act-payload", "bad-timed", "unknown-table"])
def test_compile_refusals(tmp_path, case):
    db, s, c, t, _ = golden(tmp_path / "world.db")
    i = t.instances(db, s)[0]
    q = qa_instance()
    if case == "duplicate-template":
        templates = [t, t]
    else:
        if case == "checkpoint":
            i = replace(i, probe_point=2)
        elif case in ("missing-span", "nongold-span", "empty-observed", "nonempty-unobserved"):
            i = replace(i, gold_spans={"missing-span": ("missing",), "nongold-span": ("chat-1-1",),
                                      "empty-observed": (), "nonempty-unobserved": i.gold_spans}[case],
                        never_observed=case == "nonempty-unobserved")
        elif case == "late-span":
            s = replace(s, sessions=tuple(replace(p, probe_point=True) for p in s.sessions))
            c = replace(c, schedule_sha256=sha256(s.to_json()).hexdigest())
            i = replace(i, probe_point=1, gold_spans=("event-decoy-a",))
        elif case == "missing-token":
            fact(db, "no-token", "ABSENT-9911", token=False)
            c = replace(c, world_hash=world_hash(db))
            i = replace(i, options=(replace(i.options[0], token_fact_ids=("no-token",)),))
        elif case == "foreign-plan":
            i = replace(i, options=(replace(i.options[0], plan=plan("OTHER-1229")),))
        elif case.startswith("prompt-"):
            i = replace(i, prompt="OTHER-1229" if case == "prompt-token" else CANARY)
        elif case == "table-gold":
            i = replace(i, options=(replace(i.options[0], plan=plan()), *i.options[1:]))
        elif case == "qa-duty":
            i, t = replace(q, duty=True), template()
        elif case == "world-hash":
            c = replace(c, world_hash="0" * 64)
        elif case == "schedule-hash":
            c = replace(c, schedule_sha256="0" * 64)
        elif case == "seed":
            s = replace(s, seed="other")
            c = replace(c, schedule_sha256=sha256(s.to_json()).hexdigest())
        elif case == "fault-remember":
            i, t = q, template(cell_id="FAULT-CRASH")
        elif case == "qa-table":
            i, t = replace(q, decision_table_ref="unexpected"), template()
        elif case in ("missing-decisive", "unknown-decisive"):
            i = replace(i, decisive_fact_id=None if case == "missing-decisive" else "missing")
        elif case == "duplicate-option":
            i = replace(i, options=(i.options[0], i.options[0]))
        elif case == "duplicate-token":
            i = replace(i, options=(replace(i.options[0], token_fact_ids=("detail", "detail")),))
        elif case == "bad-envelope":
            i, t = replace(q, options=(replace(q.options[0], envelope={"type": "entity"}),)), template()
        elif case == "bad-act-payload":
            i = replace(i, options=(replace(i.options[0], envelope={"type": "entity", "value": "x"}),))
        elif case == "bad-timed":
            t = replace(template(), cell_id="WAKE-PREF", kind="act", twin_type="fork", decision_tables=(table(timed=True),))
            i = replace(i, decision_table_ref=table(timed=True)["table_id"])
        elif case == "unknown-table":
            i = replace(i, decision_table_ref="missing")
        templates = [template([i, i] if case == "duplicate-instance" else [i], template_id=t.template_id,
                              cell_id=t.cell_id, kind=t.kind, twin_type=t.twin_type, decision_tables=t.decision_tables)]
    with pytest.raises(ValueError):
        compile_branch(db, s, c, templates)
    db.close()


@pytest.mark.parametrize("case", ["unpaired", "stage", "decisive", "swapped", "life", "same-plan-different-tokens"])
def test_pair_refusals(tmp_path, case):
    db0, _, _, _, b0 = golden(tmp_path / "b0.db")
    db1, _, _, _, b1 = golden(tmp_path / "b1.db", branch="B1")
    if case == "unpaired":
        b1 = replace(b1, entries=())
    elif case == "stage":
        b1 = replace(b1, entries=((b1.entries[0][0] | {"stage": "remember"}, b1.entries[0][1]),))
    elif case == "decisive":
        b1 = replace(b1, entries=((b1.entries[0][0], b1.entries[0][1] | {"decisive_fact_id": "stale"}),))
    elif case == "swapped":
        b0, b1 = b1, b0
    elif case == "life":
        b1 = replace(b1, life="other")
    else:
        item = copy.deepcopy(b1.entries[0][0])
        item["options"][0]["plan"] = copy.deepcopy(b0.entries[0][0]["options"][0]["plan"])
        assert item["options"][0]["tokens"] != b0.entries[0][0]["options"][0]["tokens"]
        b1 = replace(b1, entries=((item, b1.entries[0][1]),))
    with pytest.raises(ValueError):
        compile_life(b0, b1)
    db0.close()
    db1.close()


def test_t1_probe_budget(tmp_path):
    db, s = world(tmp_path / "world.db", scale=named("t1"))
    assertion(db, s, "detail", "WINDOW-7401", (1, 2))
    # Do not materialize the T1 sprint history for this function-level composition test.
    _, micro_s = world(tmp_path / "micro.db")
    micro_db, _ = world(tmp_path / "cut-source.db")
    assertion(micro_db, micro_s, "detail", "WINDOW-7401", (1, 2))
    c = make_cut(micro_db, micro_s)
    rows = tuple(r | {"session_id": s.sessions[0].session_id} for r in c.rows if r["event_id"] == "event-detail")
    c = replace(c, rows=rows, sessions=({"index": 10, "expected_state": STATE[1]},),
                world_hash=world_hash(db), schedule_sha256=sha256(s.to_json()).hexdigest())
    ts = template([qa_instance(key=f"qa-{n}", probe_point=10) for n in range(7)])
    with pytest.raises(ValueError, match="budget"):
        compile_branch(db, s, c, [ts])
    micro_db.close()
    db.close()


def test_decisive_fact_bitemporal(tmp_path):
    db, s = world(tmp_path / "world.db")
    # The late revelation has record time 20, despite its validity beginning at 10.
    for fid, value, start, end, recorded in (("x", "VALUE-X", 0, 10, 0), ("y", "VALUE-Y", 10, None, 20)):
        event(db, s, fid, (1, 1), t=recorded)
        fact(db, fid, value)
        insert_link(db, event_id=fid, fact_id=fid, role="assert")
        insert_attr(db, entity_id="principal", key="seat", value=value, valid_from_t=start,
                    valid_to_t=end, recorded_t=recorded, source_event_id=fid)
    assert decisive_fact(db, "principal", "seat", 15, "as_valid") == "y"
    assert decisive_fact(db, "principal", "seat", 15, "as_known") == "x"
    assert decisive_fact(db, "principal", "unknown", 15, "as_valid") is None
    db.close()


def test_never_observed_nulls(tmp_path):
    db, s = world(tmp_path / "world.db")
    i = qa_instance(spans=(), fid=None, token_fids=(), never_observed=True,
                    options=(Option(key="unknown", token_fact_ids=(), envelope={"type": "unknown", "value": None}),))
    b = compile_branch(db, s, make_cut(db, s), [template([i], cell_id="RECALL-ABST")])
    item, meta = b.entries[0]
    assert meta["evidence_session"] is None and meta["crossed"] == []
    assert meta["levers"] == {key: 0 if key == "dispersion" else None for key in LEVERS}
    assert item["gold"]["never_observed"]
    db.close()


def test_hashseed_determinism(tmp_path):
    code = """
import sys
from pathlib import Path
from tests.items.test_compile import golden
from bicentennial.items import compile_life
from bicentennial.canon import canon
from hashlib import sha256
results = []
for kind in ('fork', 'lure'):
    d0, _, _, _, b0 = golden(Path(sys.argv[1]) / (kind + '-b0.db'), kind)
    d1, _, _, _, b1 = golden(Path(sys.argv[1]) / (kind + '-b1.db'), kind, 'B1')
    compiled = compile_life(b0, b1)
    results.append([compiled.items, compiled.bundles, compiled.records])
    d0.close()
    d1.close()
sys.stdout.buffer.write(canon(results))
"""
    outputs = []
    for hashseed in ("0", "random"):
        path = tmp_path / hashseed
        path.mkdir()
        completed = subprocess.run([sys.executable, "-c", code, str(path)], cwd=ROOT,
                                   env=os.environ | {"PYTHONHASHSEED": hashseed}, capture_output=True, check=True)
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


def test_purity():
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess",
                 "bicentennial.sandbox", "bicentennial.director", "spikes")
    for path in sorted((ROOT / "src/bicentennial/items").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            assert not any(name == bad or name.startswith(bad + ".") for name in imports for bad in forbidden)
            assert not isinstance(node, ast.Constant) or type(node.value) is not float
