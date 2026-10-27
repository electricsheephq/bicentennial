"""G12 amended offline acceptance; independent copy of the G11 golden recipe."""

import ast
import copy
import json
import os
import re
import subprocess
import sys
import unicodedata
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import validate
from bicentennial.items import (
    Instance,
    Option,
    Template,
    compile_branch,
    compile_life,
    decisive_fact,
)
from bicentennial.items.protocol import CANARY
from bicentennial.items.reader_keys import (
    KINDS,
    life_keys,
    query_leaks,
    reader_keys,
    recall_query,
)
from bicentennial.keyed import uniform_int
from bicentennial.render import render_event
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import content
from bicentennial.world import create_world, unit, world_hash
from bicentennial.world.db import (
    insert_attr,
    insert_commitment,
    insert_entity,
    insert_event,
    insert_fact,
    insert_forget_request,
    insert_link,
    insert_locked_token,
    insert_plant,
)
from bicentennial.world.processes import pair
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.forget import forget_request
from bicentennial.world.processes.plants import rejection
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions

SEED = "g11-golden"
LIFE = "life-a"
STATE = {i: {"repo_tree_hash": "a" * 64, "env_state_hash": "b" * 64} for i in range(1, 4)}
ROOT = Path(__file__).resolve().parents[2]
KINDFIXTURES = ("fork", "lure", "trigger", "genuine", "rejection", "g03", "twin")


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
            refrain = Option(key="refrain", token_fact_ids=("marker",) if forgotten else (), plan=plan())
            options = [refrain, use, Option(key="default", token_fact_ids=(), plan=plan())] if forgotten else [use, refrain]
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
            spans = ("event-evid", "event-detail") if self.twin_type is None else ("event-detail",)
            fid, ref, duty = "detail", None, False
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
        assertion(db, schedule, "neighbour", "DAY-8812", (1, 1), predicate="birthday")
        assertion(db, schedule, "detail", "GATE-4410", (1, 2), predicate="gate")
        if branch == "B0":
            assertion(db, schedule, "request", "gate", (2, 1), predicate="forget", token=False)
            fact(db, "marker", "REQ-482913", predicate="forget_ref")
            insert_link(db, event_id="event-request", fact_id="marker", role="assert")
            insert_forget_request(db, event_id="event-request", covered_fact_ids_json=["detail"])
        cell, kind, tables = "KEEP-FORGET", "act", (table(), table("refrain"))
    else:
        if twin_type == "rejection":
            assertion(db, schedule, "evid", "SUN-6620", (1, 1), predicate="source")
        assertion(db, schedule, "detail", "SAT-7781", (1, 2), predicate="source",
                  modality="planted" if branch == "B0" else "stated")
        fact(db, "planted", "PLANTED-7712", predicate="authority")
        fact(db, "told", "TOLD-9912", predicate="authority")
        insert_link(db, event_id="event-detail", fact_id="planted" if branch == "B0" else "told", role="assert")
        if branch == "B0":
            insert_plant(db, fact_id="detail", carrier_event_id="event-detail", kind="forged")
        cell, kind, tables = "RACH-SRC", "qa", ()
    t = Golden(template_id=f"golden-{twin_type}", version=1, cell_id=cell, kind=kind,
               twin_type=None if twin_type == "rejection" else twin_type, direction="none", semantics="as_known", decision_tables=tables)
    c = make_cut(db, schedule, branch)
    b = compile_branch(db, schedule, c, [t])
    return db, schedule, c, t, b


def g03(path, branch):
    db, schedule = world(path)
    for name in ("cue", "sender"):
        entity(db, name)
    write_commitments(db, schedule, [Commitment(id="task", subject="principal", predicate="task", stem="TASK",
        trigger="event", cue_subject="cue", cue_key="arrived", cue_stem="CUE", sender="sender",
        cancelled=branch == "B1", made=(1, 2), due=(3, 2))], principal="principal")
    fid = db.execute("SELECT fact_id FROM commitment").fetchone()[0]
    made = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchone()[0]
    made_event = db.execute("SELECT event_id FROM link WHERE fact_id=? AND role='assert'", (fid,)).fetchone()[0]
    cancellation = db.execute("SELECT event_id FROM link WHERE fact_id=? AND role='retract'", (fid,)).fetchone()
    act = Option(key="act", token_fact_ids=(fid,), plan=plan(made, "do_task"))
    refrain = Option(key="refrain", token_fact_ids=(), plan=plan())
    spans, options = (made_event,), (act, refrain)
    if cancellation:
        cancel_id = db.execute("SELECT fact_id FROM link WHERE event_id=? AND role='assert'", cancellation).fetchone()[0]
        options = (Option(key="gold", token_fact_ids=(cancel_id,), plan=plan()), act, refrain)
        spans += (cancellation[0],)
    i = Instance(key="one", probe_point=3, prompt="Apply the remembered evidence.", options=options,
                 gold_spans=spans, decisive_fact_id=fid,
                 decision_table_ref=table("refrain" if cancellation else "act", True)["table_id"])
    t = template([i], template_id="g03", cell_id="TUE-EVENT", kind="act", twin_type="lure",
                 decision_tables=(table(timed=True), table("refrain", True)))
    c = make_cut(db, schedule, branch)
    return db, schedule, c, t, compile_branch(db, schedule, c, [t])


def visible_twin(path, branch):
    db, schedule = world(path)
    assertion(db, schedule, "detail", "LEFT-7712", (1, 1))
    assertion(db, schedule, "other", "RIGHT-9912", (1, 2), predicate="birthday")
    chosen = "detail" if branch == "B0" else "other"
    value = "left" if branch == "B0" else "right"
    i = qa_instance(spans=(f"event-{chosen}",), token_fids=(chosen,), value=value)
    t = template([i], template_id="visible-twin", twin_type="genuine")
    c = make_cut(db, schedule, branch)
    return db, schedule, c, t, compile_branch(db, schedule, c, [t])


@contextmanager
def fixture_worlds(path, kind):
    path.mkdir(parents=True, exist_ok=True)
    builder = g03 if kind == "g03" else visible_twin if kind == "twin" else golden
    a = builder(path / "b0.db", "B0") if kind in ("g03", "twin") else golden(path / "b0.db", kind)
    db0, schedule, c0, t0, b0 = a
    db1 = None
    try:
        if kind == "rejection":
            db1 = db0
            c1 = make_cut(db0, schedule, "B1")
            b1 = compile_branch(db0, schedule, c1, [t0])
        else:
            b = builder(path / "b1.db", "B1") if kind in ("g03", "twin") else golden(path / "b1.db", kind, "B1")
            db1, _, c1, _, b1 = b
        yield schedule, {"B0": (db0, c0), "B1": (db1, c1)}, compile_life(b0, b1)
    finally:
        if db1 is not None and db1 is not db0:
            db1.close()
        db0.close()


HAND = {
    "fork": ((["WINDOW-7401"], [("MIDDLE-3301", "stale")], [], ["event-detail"]),
             (["AISLE-9201"], [("MIDDLE-3301", "stale")], [], ["event-detail"])),
    "lure": ((["TASK-5521"], [], [], ["event-detail"]),
             (["CANCEL-6631"], [("TASK-5521", "stale")], [], ["event-detail", "event-cancel"])),
    "trigger": ((["REQ-482913"], [], ["GATE-4410"], ["event-request"]),
                (["GATE-4410"], [], [], ["event-detail"])),
    "genuine": ((["PLANTED-7712"], [("SAT-7781", "planted")], [], ["event-detail"]),
                (["TOLD-9912"], [], [], ["event-detail"])),
    "rejection": ((["PLANTED-7712", "SUN-6620"], [("SAT-7781", "planted")], [], ["event-evid", "event-detail"]),) * 2,
    "twin": ((["LEFT-7712"], [("RIGHT-9912", "twin")], [], ["event-detail"]),
             (["RIGHT-9912"], [("LEFT-7712", "twin")], [], ["event-other"])),
}


def choose(item, context):
    context = unicodedata.normalize("NFC", context)
    options = reader_view(item)["options"]
    return next((o for o in options if o["tokens"] and all(
        unicodedata.normalize("NFC", t) in context for t in o["tokens"])),
        next((o for o in options if not o["tokens"]), None))


@pytest.mark.parametrize("kind", KINDFIXTURES)
def test_hand_table_and_oracle(tmp_path, kind):
    with fixture_worlds(tmp_path / kind, kind) as (schedule, worlds, compiled):
        before = {b: world_hash(db) for b, (db, _) in worlds.items()}
        compiled_bytes = canon([compiled.items, compiled.records, compiled.bundles])
        records = life_keys(compiled, schedule, worlds)
        assert [r["item_id"] for r in records] == sorted(i["item_id"] for i in compiled.items)
        assert KINDS == ("stale", "planted", "twin")
        for keys in records:
            branch = keys["branch"]
            db, c = worlds[branch]
            item = next(i for i in compiled.items if i["item_id"] == keys["item_id"])
            if kind == "g03":
                fid = db.execute("SELECT fact_id FROM commitment").fetchone()[0]
                made = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchone()[0]
                cancel = f"TASK-{pair(schedule, int(made[-6:]))}"
                spans = [r["event_id"] for r in c.rows if r["event_id"] in item["gold_spans"]]
                expected = ([made], [], [], spans) if branch == "B0" else ([cancel], [(made, "stale")], [], spans)
                if branch == "B0":
                    assert not db.execute("SELECT 1 FROM locked_token WHERE value=?", (cancel,)).fetchone()
                assert len(item["options"][0]["plan"]["steps"]) == (1 if branch == "B0" else 0)
            else:
                expected = HAND[kind][branch == "B1"]
            required, competing, forbidden, spans = expected
            assert keys == dict(canary=CANARY, item_id=item["item_id"], life=LIFE, branch=branch,
                recall_query=item["prompt"], required=required, competing=[dict(token=t, kind=k) for t, k in competing],
                forbidden=forbidden, oracle_spans=spans)
            validate("reader_keys", keys)
            context = "\n".join(content(r) for r in c.rows if r["event_id"] in keys["oracle_spans"])
            assert choose(item, context)["option_id"] == item["gold"]["option_id"]
            assert all(t in context for t in keys["required"])
            assert not any(t in context for t in keys["forbidden"])
            assert choose(item, "") == next(o for o in item["options"] if not o["tokens"])
            texts = [content(r) for r in c.rows if r["event_id"] in item["gold_spans"]]
            assert recall_query(item) == item["prompt"] == keys["recall_query"]
            assert query_leaks(keys["recall_query"], item["prompt"], texts) == ()
            if kind == "rejection":
                rej = rejection(db, "detail", "event-detail")
                assert (rej.basis, rej.evidence_fact_id, rej.evidence_event_id) == ("contradiction", "evid", "event-evid")
            if kind == "trigger" and branch == "B0":
                req = forget_request(db, "event-request")
                assert req.marker == keys["required"][0] and req.neighbours == ("neighbour",)
        assert {b: world_hash(db) for b, (db, _) in worlds.items()} == before
        assert canon([compiled.items, compiled.records, compiled.bundles]) == compiled_bytes


def test_historical_answer_keeps_old_value(tmp_path):
    db, schedule = world(tmp_path / "history.db")
    try:
        assertion(db, schedule, "old", "OLD-4421", (1, 1))
        assertion(db, schedule, "correction", "NEW-5532", (2, 1))
        insert_link(db, event_id="event-correction", fact_id="old", role="retract")
        old_t, new_t = (schedule.sessions[k - 1].turn_t[0] + 60 for k in (1, 2))
        for fid, value, start, end in (("old", "OLD-4421", old_t, new_t), ("correction", "NEW-5532", new_t, None)):
            insert_attr(db, entity_id="principal", key="seat", value=value, valid_from_t=start,
                        valid_to_t=end, recorded_t=start, source_event_id=f"event-{fid}")
        date = old_t + 1
        fid = decisive_fact(db, "principal", "seat", date, "as_known")
        assert fid == "old" and date < new_t
        i = qa_instance(fid=fid, token_fids=(fid,), value="OLD-4421", spans=("event-old",),
                        prompt="Which seat value did we believe before the correction?")
        t = template([i], cell_id="DRIFT-ASOF")
        c = make_cut(db, schedule)
        b = compile_branch(db, schedule, c, [t])
        item, meta = b.entries[0]
        assert meta["levers"]["chain_depth"] == 1
        compiled = compile_life(b, compile_branch(db, schedule, make_cut(db, schedule, "B1"), [t]))
        keys = life_keys(compiled, schedule, {"B0": (db, c), "B1": (db, make_cut(db, schedule, "B1"))})
        assert all(k["required"] == ["OLD-4421"] and k["oracle_spans"] == ["event-old"] for k in keys)
        assert item["gold_spans"] == ["event-old"]
    finally:
        db.close()


def test_leak_loop_200_cases(tmp_path):
    with ExitStack() as stack:
        fixtures = [stack.enter_context(fixture_worlds(tmp_path / kind, kind)) for kind in KINDFIXTURES]
        for case in range(200):
            u = unit("g12", "leak", str(case))
            _, worlds, compiled = fixtures[uniform_int("g12", u, 0, "fixture", 0, len(fixtures) - 1)]
            item = compiled.items[uniform_int("g12", u, 0, "item", 0, len(compiled.items) - 1)]
            record = next(r for r in compiled.records if r["item_id"] == item["item_id"])
            texts = [content(r) for r in worlds[record["branch"]][1].rows if r["event_id"] in item["gold_spans"]]
            text = texts[uniform_int("g12", u, 0, "row", 0, len(texts) - 1)]
            start = uniform_int("g12", u, 0, "start", 0, len(text) - 1)
            length = uniform_int("g12", u, 0, "length", 1, min(12, len(text) - start))
            sub = text[start:start + length]
            if sub not in item["prompt"]:
                assert query_leaks(item["prompt"] + " " + sub, item["prompt"], texts)


def test_query_leaks_exact_minima_200_cases():
    alphabet = ("a", "b", "e\u0301", "é", " ", "\n")
    for case in range(200):
        u = unit("g12", "query", str(case))
        def draw(label, u=u):
            return "".join(alphabet[uniform_int("g12", u, 0, f"{label}-{n}", 0, len(alphabet) - 1)]
                           for n in range(uniform_int("g12", u, 0, label, 0, 10)))
        query, prompt, text = (draw(label) for label in ("query", "prompt", "text"))
        q, p, t = (unicodedata.normalize("NFC", s) for s in (query, prompt, text))
        expected = set()
        for i in range(len(q)):
            missing = [q[i:j] for j in range(i + 1, len(q) + 1) if q[i:j] not in p]
            if missing and missing[0] in t:
                expected.add(missing[0])
        result = query_leaks(query, prompt, [text])
        assert result == tuple(sorted(expected))
        assert bool(result) == any(q[i:j] in t and q[i:j] not in p for i in range(len(q)) for j in range(i + 1, len(q) + 1))
    assert query_leaks("cafe\u0301", "", ["café"]) == ("a", "c", "f", "é")


@pytest.mark.parametrize(("case", "message"), {
    "cancel-span": "conflicting keys or missing required span",
    "forget-span": "conflicting keys or missing required span",
    "rejection-span": "conflicting keys or missing required span",
    "required-forbidden": "conflicting keys or missing required span",
    "required-outside-oracle": "invalid oracle evidence or recall query",
    "second-plant": "multiple decisive plants",
}.items())
def test_evidence_refusals(tmp_path, case, message):
    kind = "lure" if case.startswith("cancel") else "rejection" if case == "rejection-span" else (
        "genuine" if case == "second-plant" else "trigger")
    branch = "B1" if case.startswith("cancel") or case == "required-outside-oracle" else "B0"
    db, s, c, t, _ = golden(tmp_path / "refusal.db", kind, branch)
    try:
        i = t.instances(db, s)[0]
        if case == "cancel-span":
            i = replace(i, gold_spans=("event-detail",))
        elif case == "forget-span":
            i = replace(i, gold_spans=("event-detail",))
        elif case == "rejection-span":
            i = replace(i, gold_spans=("event-detail",))
        elif case.startswith("required-"):
            i = qa_instance(token_fids=("neighbour",) if case == "required-outside-oracle" else ("detail",),
                            value="DAY-8812" if case == "required-outside-oracle" else "GATE-4410")
            t = template()
        else:
            insert_plant(db, fact_id="detail", carrier_event_id="event-detail", kind="third_party_claim")
            c = make_cut(db, s, branch)
        t = template([i], template_id=t.template_id, cell_id=t.cell_id, kind=t.kind, twin_type=t.twin_type,
                     decision_tables=t.decision_tables)
        b = compile_branch(db, s, c, [t])
        item, meta = b.entries[0]
        record = meta | dict(item_id=item["item_id"], branch=branch, life=LIFE,
                             bundle_id="bundle" if t.twin_type else None)
        twin = item | {"item_id": "other-item"} if t.twin_type else None
        identity = "detail" if case == "second-plant" else item["item_id"]
        with pytest.raises(ValueError, match=rf"^{re.escape(f'{message}: {identity}')}$") as exc:
            reader_keys(db, s, c, item, record, twin=twin)
        for (token,) in db.execute("SELECT value FROM locked_token"):
            assert token not in str(exc.value)
    finally:
        db.close()


def test_gold_span_not_visible_to_agent(tmp_path):
    db, s = world(tmp_path / "unseen.db")
    try:
        event(db, s, "event-detail", (1, 2), audience=("principal",))
        fact(db, "detail", "WINDOW-7401")
        insert_link(db, event_id="event-detail", fact_id="detail", role="assert")
        c = make_cut(db, s)
        item, meta = compile_branch(db, s, c, [template([qa_instance()])]).entries[0]
        assert item["gold_spans"] == ["event-detail"]
        row = next(r for r in c.rows if r["event_id"] == "event-detail")
        assert row["audience"] == ["principal"]
        record = meta | dict(item_id=item["item_id"], branch="B0", life=LIFE, bundle_id=None)
        with pytest.raises(ValueError, match=rf"^gold span not visible to the agent: {re.escape(item['item_id'])}$"):
            reader_keys(db, s, c, item, record)
    finally:
        db.close()


def test_a1_overrides_old_cancel_token_refusal(tmp_path):
    # A1 explicitly replaces the old refusal when tok(d) is in G.
    db, s, c, t, _ = golden(tmp_path / "old-cancel.db", "lure", "B1")
    try:
        i = t.instances(db, s)[0]
        i = replace(i, options=(replace(i.options[0], token_fact_ids=("detail",)), *i.options[1:]))
        t = template([i], template_id=t.template_id, cell_id=t.cell_id, kind=t.kind, twin_type=t.twin_type,
                     decision_tables=t.decision_tables)
        item, meta = compile_branch(db, s, c, [t]).entries[0]
        record = meta | dict(item_id=item["item_id"], branch="B1", life=LIFE, bundle_id="bundle")
        keys = reader_keys(db, s, c, item, record, twin=item | {"item_id": "other-item"})
        assert keys["required"] == ["TASK-5521"] and keys["competing"] == []
    finally:
        db.close()


@pytest.mark.parametrize("case", ["world", "branch", "missing-twin", "extra-twin", "same-twin", "schedule", "cut-life", "record-life", "item-id"])
def test_identity_refusals(tmp_path, case):
    # The rejection fixture has no bundle, so the default twin is the extra input.
    kind = "rejection" if case == "extra-twin" else "fork"
    with fixture_worlds(tmp_path / "ids", kind) as (s, worlds, compiled):
        record = next(r for r in compiled.records if r["branch"] == "B0")
        item = next(i for i in compiled.items if i["item_id"] == record["item_id"])
        twin = next(i for i in compiled.items if i["item_id"] != item["item_id"])
        db, c = worlds["B0"]
        if case == "world":
            c = worlds["B1"][1]
        elif case == "branch":
            record = record | {"branch": "B1"}
        elif case == "missing-twin":
            twin = None
        elif case == "same-twin":
            twin = item
        elif case == "schedule":
            c = replace(c, schedule_sha256="0" * 64)
        elif case == "cut-life":
            c = replace(c, life="other")
        elif case == "record-life":
            record = record | {"life": "other"}
        elif case == "item-id":
            record = record | {"item_id": "other"}
        with pytest.raises(ValueError, match=rf"^reader identity mismatch: {re.escape(item['item_id'])}$"):
            reader_keys(db, s, c, item, record, twin=twin)


@pytest.mark.parametrize(("case", "message"), {
    "branch": "reader life or branch mismatch",
    "cut-branch": "reader life or branch mismatch",
    "life": "reader life or branch mismatch",
    "missing-record": "reader item and record mismatch",
    "extra-record": "reader item and record mismatch",
    "duplicate-record": "reader item and record mismatch",
    "duplicate-item": "reader item and record mismatch",
}.items())
def test_life_refusals(tmp_path, case, message):
    with fixture_worlds(tmp_path / "life", "fork") as (s, worlds, compiled):
        if case == "branch":
            del worlds["B1"]
        elif case == "cut-branch":
            worlds = worlds | {"B0": worlds["B1"]}
        elif case == "life":
            compiled = replace(compiled, life="other")
        elif case == "missing-record":
            compiled = replace(compiled, records=compiled.records[:-1])
        elif case == "extra-record":
            compiled = replace(compiled, records=(*compiled.records, compiled.records[0] | {"item_id": "extra"}))
        elif case == "duplicate-record":
            compiled = replace(compiled, records=(*compiled.records, compiled.records[0]))
        else:
            compiled = replace(compiled, items=(*compiled.items, compiled.items[0]))
        with pytest.raises(ValueError, match=rf"^{re.escape(message)}$"):
            life_keys(compiled, s, worlds)


def registry():
    return json.loads((ROOT / "tests/fixtures/reader_keys/contracts.json").read_bytes())["contracts"]["reader_keys"]


@pytest.mark.parametrize(("delta", "message"), [
    ({"required": ["ZZZZ-1234", "AAAA-1234"]}, "reader keys: token lists must strictly increase"),
    ({"required": ["VALUE-1234"] * 2}, "reader keys: token lists must strictly increase"),
    ({"forbidden": ["ZZZZ-1234", "AAAA-1234"]}, "reader keys: token lists must strictly increase"),
    ({"forbidden": ["ERASE-7712"] * 2}, "reader keys: token lists must strictly increase"),
    ({"competing": [{"token": "STALE-5600", "kind": "stale"}] * 2}, "reader keys: token lists must strictly increase"),
    ({"competing": [{"token": "ZZZZ-1234", "kind": "stale"}, {"token": "AAAA-1234", "kind": "twin"}]},
     "reader keys: token lists must strictly increase"),
    ({"forbidden": ["VALUE-1234"]}, "reader keys: overlapping token sets"),
    ({"competing": [{"token": "VALUE-1234", "kind": "twin"}]}, "reader keys: overlapping token sets"),
    ({"competing": [{"token": "ERASE-7712", "kind": "planted"}]}, "reader keys: overlapping token sets"),
    ({"competing": [{"token": "STALE-5600", "kind": "decoy"}]}, '$["competing"][0]["kind"]: invalid enum value'),
    ({"required": ["ABC"]}, '$["required"][0]: pattern mismatch'),
    ({"recall_query": "Find VALUE-1234"}, "reader keys: non-NFC token or token in query"),
    ({"extra": None}, "$: missing=[], extra=['extra']"),
    ({"oracle_spans": ["event"] * 2}, "reader keys: duplicate oracle span"),
    ({"required": ["CAFE\u0301-1234"]}, "reader keys: non-NFC token or token in query"),
    ({"recall_query": "Find STALE-5600"}, "reader keys: non-NFC token or token in query"),
    ({"recall_query": "Find ERASE-7712"}, "reader keys: non-NFC token or token in query"),
    ({"required": ["CAFÉ-1234"], "recall_query": "Find CAFE\u0301-1234"}, "reader keys: non-NFC token or token in query"),
])
def test_contract_refusals(delta, message):
    value = copy.deepcopy(registry())
    value.update(delta)
    with pytest.raises(ValueError, match=rf"^{re.escape(message)}$"):
        validate("reader_keys", value)


def test_query_leak_refusal(tmp_path, monkeypatch):
    with fixture_worlds(tmp_path / "leak-guard", "fork") as (s, worlds, compiled):
        monkeypatch.setattr("bicentennial.items.reader_keys.recall_query", lambda item: item["prompt"] + " WINDOW-7401")
        with pytest.raises(ValueError, match="recall query"):
            life_keys(compiled, s, worlds)


def test_hashseed_determinism(tmp_path):
    code = """
import sys
from pathlib import Path
from tests.items.test_reader_keys import fixture_worlds
from bicentennial.items.reader_keys import life_keys
from bicentennial.canon import canon
results = []
for kind in ('fork', 'trigger', 'g03'):
    with fixture_worlds(Path(sys.argv[1]) / kind, kind) as (s, worlds, compiled):
        results.append(life_keys(compiled, s, worlds))
sys.stdout.buffer.write(canon(results))
"""
    outputs = []
    for seed in ("0", "random"):
        completed = subprocess.run([sys.executable, "-c", code, str(tmp_path / seed)], cwd=ROOT,
                                   env=os.environ | {"PYTHONHASHSEED": seed}, capture_output=True, check=True)
        outputs.append(completed.stdout)
    assert outputs[0] == outputs[1]


def test_purity():
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess",
                 "bicentennial.sandbox", "bicentennial.director", "spikes")
    for file in ("items/reader_keys.py", "contracts/reader_keys.py"):
        for node in ast.walk(ast.parse((ROOT / "src/bicentennial" / file).read_text())):
            imports = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0 else [])
            assert not any(name == bad or name.startswith(bad + ".") for name in imports for bad in forbidden)
            assert not isinstance(node, ast.Constant) or type(node.value) is not float
