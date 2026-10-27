"""G15 micro-life acceptance, real tool execution and 200 keyed placement cases."""

import ast
import json
import os
import re
import subprocess
import sys
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.decision_table import predicate_names
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.genres.g2_assistant.envseed import (
    env_key,
    env_state_hashes,
    probe_envseed,
)
from bicentennial.genres.g2_assistant.preferences import Pref, write_preferences
from bicentennial.genres.g2_assistant.world import (
    build_base,
    create,
    finish,
    write_entity,
    write_forget,
    write_people,
)
from bicentennial.items.bundle import compile_life
from bicentennial.items.compile import _id, compile_branch
from bicentennial.items.templates.g2 import TEMPLATES, option_roles
from bicentennial.items.templates.g2.common import (
    PREDICATE_KINDS,
    TOOLS_BY_NAME,
    entity,
    linking,
    name,
    role,
    slot_key,
    step,
    token,
)
from bicentennial.keyed import uniform_int
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import content
from bicentennial.sandbox.envserver.tools_g2.state import G2State
from bicentennial.score.action import Trace, score_action
from bicentennial.score.qa import score_qa
from bicentennial.world import db as rows
from bicentennial.world import lineage, open_world, unit, world_hash
from bicentennial.world.processes import mint, slot
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.forget import forget_request
from bicentennial.world.processes.incidental import Detail, write_details
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.twin import twin_life

CATALOGUE = {t.template_id: t for t in TEMPLATES}
LIVES = {
    "drift": ("drift-asof", "drift-booking", "drift-no-update"),
    "inc": ("keep-incidental",), "forget": ("keep-forget",),
    "neigh": ("keep-neighbour",), "tue": ("tue-passport",), "count": ("recall-count",),
}


def expected_state(db):
    return {k: {"repo_tree_hash": "a" * 64, "env_state_hash": h} for k, h in env_state_hashes(db).items()}


def new_world(path, seed):
    schedule = build_schedule(seed, "life-a", named("t0-micro", sessions=3))
    db = create(path, schedule)
    return db, schedule, write_people(db, schedule)


def preferences(db, schedule, principal, *, depth=1, keyed=False):
    write_preferences(db, schedule, [
        Pref(id="seat-long", domain="seat", scope=("context", "long_haul"), stem="SEAT", depth=depth,
             at=None if keyed else ((1, 2), (2, 2))),
        Pref(id="seat-short", domain="seat", scope=("context", "short_haul"), stem="SEAT", mention="hedge",
             at=None if keyed else ((1, 3), (2, 3)))], principal=principal)


def make_life(path, which):
    path.mkdir()
    db, s, people = new_world(path / "base.db", f"g15-{which}")
    p = people.principal

    def ent(kind, key):
        return write_entity(db, s, kind=kind, key=key, name=key.title())

    if which == "drift":
        preferences(db, s, p)
    elif which in ("inc", "neigh"):
        subjects = (tuple(ent("place", f"place-{j}") for j in range(1, 5))
                    if which == "inc" else people.people[4:8])
        with lineage.atomic(db):
            write_details(db, s, [Detail(id="gate" if which == "inc" else "nbday", subject=subjects[0],
                                        predicate="gate_code" if which == "inc" else "birthday",
                                        stem="GATE" if which == "inc" else "BDAY", decoys=subjects[1:],
                                        at=((1, 2), (1, 3), (2, 2), (2, 3)) if which == "inc" else
                                        ((1, 1), (1, 3), (1, 4), (1, 5)))], principal=p, ratio=3)
    if which in ("forget", "neigh"):
        write_forget(db, s, key="ex" if which == "forget" else "neigh",
                     subject=people.people[2 if which == "forget" else 4], covered=(("address", "ADDR"),),
                     neighbours=(("birthday", "BDAY"),) if which == "forget" else (("phone", "PHONE"),),
                     principal=p, at=((1, 2), (2, 2), (3, 2)))
    elif which == "tue":
        trip, passport, lure = ent("trip", "trip"), ent("purchase", "passport"), ent("purchase", "lure")
        with lineage.atomic(db):
            write_commitments(db, s, [Commitment(
                id="passport", subject=trip, predicate="book", stem="TRIP", trigger="event",
                cue_subject=passport, cue_key="delivery", cue_stem="PARCEL", sender=people.people[1],
                lures=(lure,), cancelled=True, made=(1, 1), due=(3, 1))], principal=p)
    elif which == "count":
        trip = ent("trip", "trip")
        with lineage.atomic(db):
            write_corrections(db, s, [Chain(id="plan-trip", subject=trip, key="date", stem="DATE", depth=2,
                                            at=((1, 2), (2, 2), (3, 2)))], principal=p)
    finish(db, s, principal=p)
    templates = tuple(CATALOGUE[key] for key in LIVES[which])
    if which != "count":
        twin = twin_life(db, s, templates, world_path=path / "twin.db", out_dir=path / "streams",
                         principal_id=p, expected_state=expected_state)
        dbs, cuts, compiled = (db, twin.b1), twin.cuts, twin.compiled
    else:
        dbs = (db, db)
        cuts = tuple(cut(db, s, branch=b, principal_id=p, expected_state=expected_state(db)) for b in ("B0", "B1"))
        compiled = compile_life(*(compile_branch(d, s, c, templates) for d, c in zip(dbs, cuts, strict=True)))
    return SimpleNamespace(dbs=dbs, cuts=cuts, compiled=compiled, schedule=s, templates=templates,
                           principal=p, path=path / "base.db")


@pytest.fixture(scope="module")
def lives(tmp_path_factory):
    root = tmp_path_factory.mktemp("g15-lives")
    data = {which: make_life(root / which, which) for which in LIVES}
    yield data
    for life in data.values():
        life.dbs[0].close()
        if life.dbs[1] is not life.dbs[0]:
            life.dbs[1].close()


def reader(item, text):
    text = unicodedata.normalize("NFC", text)
    return next((o for o in item["options"] if o["tokens"] and all(
        unicodedata.normalize("NFC", t) in text for t in o["tokens"])),
        next((o for o in item["options"] if not o["tokens"]), None))


def by_template(life, branch):
    return {m["template_id"]: (i, m) for i, m in compile_branch(
        life.dbs[branch], life.schedule, life.cuts[branch], life.templates).entries}


def chain_facts(db, subject, predicate, t, *, assert_only=False):
    # Independent row query: no template target/ordering helper supplies the oracle.
    rows = db.execute("SELECT f.*, e.t_sim, e.audience_json FROM fact f JOIN link l ON l.fact_id=f.id "
                      "JOIN event e ON e.id=l.event_id WHERE f.subject_id=? AND f.predicate=? "
                      "AND l.role='assert' ORDER BY e.t_sim, f.id", (subject, predicate)).fetchall()
    result, seen = [], set()
    for r in rows:
        if r["id"] not in seen and r["t_sim"] < t and "agent" in json.loads(r["audience_json"]) and (
                not assert_only or r["speech_act"] == "assert"):
            result.append(r["id"])
            seen.add(r["id"])
    return result


def latest(db, subject, predicate, t):
    attr = db.execute("SELECT * FROM attr WHERE entity_id=? AND key=? AND recorded_t<=? "
                      "AND valid_from_t<=? ORDER BY valid_from_t DESC LIMIT 1", (subject, predicate, t, t)).fetchone()
    return db.execute("SELECT f.id FROM fact f JOIN link l ON l.fact_id=f.id WHERE f.subject_id=? "
                      "AND f.predicate=? AND f.object=? AND l.event_id=? AND l.role='assert'",
                      (subject, predicate, attr["value"], attr["source_event_id"])).fetchone()[0]


def gold_facts(db, s, template):
    t = s.sessions[-1].t_end
    ident = template.template_id
    if ident.startswith("drift"):
        subject = entity(s, "preference", f"pref-{template.pref_id}")
        current = latest(db, subject, "value", t)
        if ident == "drift-asof":
            at = db.execute("SELECT max(e.t_sim) FROM event e JOIN link l ON l.event_id=e.id "
                            "JOIN fact f ON f.id=l.fact_id WHERE f.subject_id=? AND l.role='retract'",
                            (subject,)).fetchone()[0]
            return (latest(db, subject, "value", at - 1), current)
        if ident == "drift-no-update":
            first, mention = chain_facts(db, subject, "value", t)
            assert first == current
            return (current, mention)
        return (current,)
    if ident == "keep-incidental":
        return (mint(s, "incidental", "gate", "fact", "detail", 0),)
    if ident == "keep-forget":
        event = lineage.ids(db, s.life, "forget", "ex")(0)
        if db.execute("SELECT 1 FROM forget_request WHERE event_id=?", (event,)).fetchone():
            fr = forget_request(db, event)
            assert re.fullmatch(r"REQ-[0-9]{6}", fr.marker)
            return (fr.marker_fact_id,)
        return (mint(s, "g2-forget", "ex", "fact", "fact", 0),)
    if ident == "keep-neighbour":
        return (mint(s, "incidental", "nbday", "fact", "detail", 0),)
    if ident == "tue-passport":
        cancel = mint(s, "commitments", "passport", "fact", "cancel", 0)
        if db.execute("SELECT 1 FROM fact WHERE id=?", (cancel,)).fetchone():
            return (cancel,)
        return (mint(s, "commitments", "passport", "fact", "made", 0),
                mint(s, "commitments", "passport", "fact", "cue", 0))
    return tuple(chain_facts(db, entity(s, "trip", "trip"), "date", t, assert_only=True))


@pytest.mark.parametrize("which", LIVES)
def test_micro_lives(lives, which):
    life = lives[which]
    c = life.compiled
    expected_bundles = 2 if which == "drift" else 0 if which == "count" else 1
    assert len(c.bundles) == expected_bundles
    assert len(c.records) == 2 * len(life.templates)
    assert sum(r["bundle_id"] is None for r in c.records) == (2 if which in ("drift", "count") else 0)
    assert all(b["twin_type"] == {"forget": "trigger", "tue": "lure"}.get(which, "fork") for b in c.bundles)
    for schema, values in (("item", c.items), ("bundle", c.bundles), ("item_record", c.records)):
        for v in values:
            validate(schema, v)
    for branch in range(2):
        db = life.dbs[branch]
        context = "".join(content(r) for r in life.cuts[branch].rows)
        for template in life.templates:
            item, meta = by_template(life, branch)[template.template_id]
            gold = item["options"][0]
            assert gold["tokens"] == [token(db, f) for f in gold_facts(db, life.schedule, template)]
            assert gold["tokens"] and item["memory_tag"] == "memory_exclusive"
            assert item["stage"] == ("act" if template.kind == "act" else "remember")
            assert reader(item, context) == gold
            empty = reader(item, "")
            if branch == 0 and which in ("forget", "tue"):
                assert empty is None
            else:
                assert empty is not None and empty["tokens"] == []
                assert empty.get("plan", {"steps": []})["steps"] == []
                if template.kind == "qa":
                    assert empty["envelope"]["type"] == "unknown"
            assert meta["duty"] == (which == "tue" and branch == 1)
    if which == "forget":
        db0, db1 = life.dbs
        assert db0.execute("SELECT count(*) FROM forget_request").fetchone()[0] == 1
        assert db1.execute("SELECT count(*) FROM forget_request").fetchone()[0] == 0
        assert db1.execute("SELECT count(*) FROM fact WHERE predicate='forget_ref'").fetchone()[0] == 0
        assert db1.execute("SELECT count(*) FROM locked_token WHERE value LIKE 'REQ-%'").fetchone()[0] == 0
        for branch in range(2):
            item, _ = by_template(life, branch)["keep-forget"]
            tab = next(t for t in life.templates[0].decision_tables if t["table_id"] == item["decision_table_ref"])
            assert tab["gold"] == ("refrain" if branch == 0 else "act")
            assert bool(item["options"][0]["plan"]["steps"]) == bool(branch)
            if branch:
                covered = mint(life.schedule, "g2-forget", "ex", "fact", "fact", 0)
                assert token(db1, covered) in canon(item["options"][0]["plan"]).decode()
                assert tab["admissible"] == ["holds:use"]
            else:
                assert tab["disqualifiers"] == [dict(predicate="leaks:use", verdict="FAIL_MEMORY", tuesday_class=None)]
    if which == "neigh":
        assert life.dbs[1].execute("SELECT count(*) FROM forget_request").fetchone()[0] == 1
    if which == "tue":
        due = by_template(life, 1)["tue-passport"][0]["item_id"]
        assert c.duty_items() == {due}
    else:
        assert not c.duty_items()


def predicates(table, options, initial, state, trace):
    """Decision 3/A3 evaluator, independent of templates and production predicate code."""
    result = {}
    for pred in predicate_names(table):
        kind, target = pred.split(":")
        selected = [o for r, o in options if r == target]
        steps = [s["tool"] for o in selected for s in o["plan"]["steps"]]
        if kind == "holds":
            result[pred] = any(o["plan"]["steps"] and all(
                canon(state[TOOLS_BY_NAME[s["tool"]["name"]]["collection"]].get(
                    s["tool"]["args"][TOOLS_BY_NAME[s["tool"]["name"]]["key_arg"]])) ==
                canon(s["tool"]["args"][TOOLS_BY_NAME[s["tool"]["name"]]["value_arg"]])
                for s in o["plan"]["steps"]) for o in selected)
        elif kind == "leaks":
            tokens = [unicodedata.normalize("NFC", t) for o in selected for t in o["tokens"]]
            result[pred] = any(any(t in unicodedata.normalize("NFC", canon(v).decode()) for t in tokens)
                               for coll in sorted(state) for key, v in sorted(state[coll].items())
                               if key not in initial[coll] or canon(v) != canon(initial[coll][key]))
        elif kind == "repeated":
            result[pred] = any(sum(row["name"] == s["name"] and row["args"].get(
                TOOLS_BY_NAME[s["name"]]["key_arg"]) == s["args"][TOOLS_BY_NAME[s["name"]]["key_arg"]]
                for row in trace) > 1 for s in steps)
        else:
            assert kind == "wrote"
            result[pred] = any(not row["isError"] and row["name"] == s["name"] and
                               row["args"].get(TOOLS_BY_NAME[s["name"]]["key_arg"]) ==
                               s["args"][TOOLS_BY_NAME[s["name"]]["key_arg"]] and canon(
                                   row["args"].get(TOOLS_BY_NAME[s["name"]]["value_arg"])) == canon(
                                       s["args"][TOOLS_BY_NAME[s["name"]]["value_arg"]])
                               for s in steps for row in trace)
    return result


def execute(life, branch, template, item, options):
    db = life.dbs[branch]
    seed = probe_envseed(db, 4, 3).seed
    initial = json.loads(canon(seed["state"]))
    state, trace = G2State(seed), []
    for option in options:
        for s in option["plan"]["steps"]:
            call = s["tool"]
            try:
                state.call(call["name"], call["args"])
                error = False
            except ValueError:
                error = True
            trace.append(dict(call, isError=error))
    roles = option_roles(template, db, life.schedule)[template.instances(db, life.schedule)[0].key]
    labelled = [(roles[o["option_id"]], o) for o in item["options"]]
    tab = next(t for t in template.decision_tables if t["table_id"] == item["decision_table_ref"])
    window = None
    t = life.schedule.sessions[-1].t_end
    if template.track == "Tuesday":
        row = db.execute("SELECT window_open_t, window_close_t FROM commitment").fetchone()
        window = tuple(row)
        t = window[0]
    result = score_action(item, tab, Trace(False, bool(trace), t if trace else None),
                          predicates(tab, labelled, initial, state.state, trace), window=window)
    return result, trace


@pytest.mark.parametrize("which", LIVES)
def test_scoring_agreement(lives, which):
    life = lives[which]
    for branch in range(2):
        for template in life.templates:
            item, _ = by_template(life, branch)[template.template_id]
            gold = item["options"][0]
            if template.kind == "qa":
                assert score_qa(item, gold["envelope"] | {"citation": None}, evidence_texts=()).score_milli == 1000
                wrong = next(o for o in item["options"][1:] if o["tokens"])
                assert score_qa(item, wrong["envelope"] | {"citation": None}, evidence_texts=()).score_milli == -1000
                if which == "count":
                    assert gold["envelope"]["value"] == 2
                continue
            outcome, trace = execute(life, branch, template, item, [gold])
            assert (outcome.base_verdict, outcome.score_milli) == ("PASS", 1000)
            assert all(not row["isError"] for row in trace)
            if which == "tue" and branch:
                assert outcome.tuesday_class == "on_time"
            double, _ = execute(life, branch, template, item, [gold, gold])
            steps = bool(gold["plan"]["steps"])
            assert (double.base_verdict, double.score_milli, double.benign_extra) == (
                "PASS", 0 if steps else 1000, steps)
            idle, _ = execute(life, branch, template, item, [])
            assert (idle.base_verdict, idle.score_milli) == (("OMISSION", 0) if steps else ("PASS", 1000))
            if which == "tue" and branch:
                assert idle.tuesday_class == "never"
            roles = option_roles(template, life.dbs[branch], life.schedule)[template.instances(
                life.dbs[branch], life.schedule)[0].key]
            for o in item["options"][1:]:
                if roles[o["option_id"]] not in ("other", "decoy", "forgotten", "lure") and not (
                        branch == 0 and which in ("forget", "tue") and o["plan"]["steps"]):
                    continue
                wrong, _ = execute(life, branch, template, item, [o])
                assert (wrong.base_verdict, wrong.score_milli) == ("FAIL_MEMORY", -1000)
                if which == "tue":
                    assert wrong.tuesday_class == "false_alarm"
                if which == "drift":
                    repaired, _ = execute(life, branch, template, item, [o, gold])
                    assert (repaired.base_verdict, repaired.score_milli) == ("FAIL_MEMORY", -1000)


def test_shares_and_do_nothing(lives):
    counts, restraints, single, mention = Counter(), Counter(), 0, 0
    for life in lives.values():
        items = {i["item_id"]: i for i in life.compiled.items}
        records = {r["item_id"]: r for r in life.compiled.records}
        templates = {t.template_id: t for t in life.templates}
        for bundle in life.compiled.bundles:
            pair = [items[i] for i in bundle["items"]]
            track = pair[0]["track"]
            counts[track] += 1
            golds, scores = set(), []
            for branch, item in enumerate(pair):
                record = records[item["item_id"]]
                template = templates[record["template_id"]]
                tab = next(t for t in template.decision_tables if t["table_id"] == item["decision_table_ref"])
                golds.add(tab["gold"])
                scores.append(execute(life, branch, template, item, [])[0].score_milli)
            assert min(scores) <= 0
            restraints[track] += golds == {"act", "refrain"}
            record = records[bundle["items"][0]]
            single += track == "Drift" and record["levers"]["chain_depth"] == 1
            mention += record["template_id"] == "drift-no-update"
    assert counts == {"Drift": 2, "Keep": 3, "Tuesday": 1}
    assert restraints["Keep"] == 1 and restraints["Tuesday"] == 1
    assert 4 * restraints["Keep"] >= counts["Keep"]
    assert 4 * restraints["Tuesday"] >= counts["Tuesday"]
    assert 4 * (restraints["Keep"] + restraints["Tuesday"]) >= counts["Keep"] + counts["Tuesday"]
    assert single == 1 and 10 * single >= 3 * counts["Drift"] and mention == 1


def test_base_life(tmp_path):
    life = build_base(tmp_path / "base.db", seed="g15-base", life="life-a", scale=named("t0-micro", sessions=3))
    try:
        templates = tuple(t for t in TEMPLATES if t.template_id not in ("keep-neighbour", "tue-passport"))
        c = cut(life.db, life.schedule, branch="B0", principal_id=life.people.principal,
                expected_state=expected_state(life.db))
        b = compile_branch(life.db, life.schedule, c, templates)
        assert len(b.entries) == 6
        for item, _ in b.entries:
            validate("item", item)
        item = next(i for i, m in b.entries if m["template_id"] == "keep-forget")
        assert item["options"][0]["tokens"] == [life.forget.marker]
        assert lineage.ids(life.db, life.schedule.life, "forget", "ex")(0) == life.forget.event_id
    finally:
        life.db.close()


def test_keyed_properties_200(tmp_path):
    templates = tuple(CATALOGUE[key] for key in LIVES["drift"])
    for c in range(200):
        seed = f"g15-{c}"
        depth = uniform_int(seed, unit("g15", "drift", str(c)), 0, "depth", 1, 2)
        db, s, people = new_world(tmp_path / f"{c}.db", seed)
        try:
            preferences(db, s, people.principal, depth=depth, keyed=True)
            finish(db, s, principal=people.principal)
            ctx = cut(db, s, branch="B0", principal_id=people.principal, expected_state=expected_state(db))
            b = compile_branch(db, s, ctx, templates)
            text = "".join(content(r) for r in ctx.rows)
            for item, meta in b.entries:
                template = CATALOGUE[meta["template_id"]]
                assert item["options"][0]["tokens"] == [token(db, f) for f in gold_facts(db, s, template)]
                assert reader(item, text) == item["options"][0]
                if template.template_id == "drift-booking":
                    e = entity(s, "preference", "pref-seat-long")
                    facts = chain_facts(db, e, "value", s.sessions[-1].t_end)
                    instance = template.instances(db, s)[0]
                    assert instance.options[0].token_fact_ids == (facts[-1],)
                    assert [o.token_fact_ids for o in instance.options[1:-1]] == [(f,) for f in facts[:-1]]
                    assert meta["levers"]["chain_depth"] == depth
                elif template.template_id == "drift-no-update":
                    assert meta["levers"]["chain_depth"] == 0
        finally:
            db.close()


def test_purity_catalogue_and_helpers(lives):
    assert len(TEMPLATES) == 8 and list(CATALOGUE) == sorted(CATALOGUE)
    assert all(t.version == 1 and t.checkpoint is None and t.semantics == "as_known" for t in TEMPLATES)
    assert PREDICATE_KINDS == ("holds", "leaks", "repeated", "wrote")
    canary = json.loads((SCHEMAS / "decision_table.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
    for t in TEMPLATES:
        for tab in t.decision_tables:
            validate("decision_table", tab)
            assert tab["canary"] == canary
    package = Path("src/bicentennial/items/templates/g2")
    banned = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess", "bicentennial.sandbox",
              "bicentennial.director", "bicentennial.render", "bicentennial.world.twin", "spikes")
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                       [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert all(not any(i == b or i.startswith(b + ".") for b in banned) for i in imports)
            assert not isinstance(node, ast.Constant) or type(node.value) is not float
    assert not (package.parent / "__init__.py").exists()
    for life in lives.values():
        before = world_hash(life.dbs[0])
        writer = compile_branch(life.dbs[0], life.schedule, life.cuts[0], life.templates)
        with open_world(life.path) as db:
            statements = []
            db.set_trace_callback(statements.append)
            readonly = compile_branch(db, life.schedule, life.cuts[0], life.templates)
            assert readonly == writer
            assert all(s.lstrip().upper().startswith("SELECT") for s in statements)
            assert world_hash(db) == before
        assert world_hash(life.dbs[0]) == before
        for template in life.templates:
            instances = [template.instances(db, life.schedule)[0] for db in life.dbs]
            assert instances[0].key == instances[1].key
            assert slot_key(life.schedule, template, instances[0].key) == env_key(
                life.schedule.seed, "item", f"{template.ref}/{instances[0].key}")
            assert len(template.instances(life.dbs[0], life.schedule)) == 1
            for branch, instance in enumerate(instances):
                roles = option_roles(template, life.dbs[branch], life.schedule)[instance.key]
                assert roles == {_id(life.schedule.seed, life.schedule.life, "option", [template.ref, instance.key, o.key]):
                                 role(o.key) for o in instance.options}
                assert not instance.never_observed
    assert role("other-12") == "other" and role("seat-long") == "seat-long"


def test_determinism_subprocesses(tmp_path):
    script = """
import runpy, sys
from pathlib import Path
from bicentennial.canon import canon
ns = runpy.run_path('tests/items/test_templates_g2.py')
root = Path(sys.argv[1])
root.mkdir()
result = []
for which in ('tue', 'forget'):
    life = ns['make_life'](root / which, which)
    result.append([life.compiled.items, life.compiled.bundles, life.compiled.records])
    for db in life.dbs:
        db.close()
sys.stdout.buffer.write(canon(result))
"""
    results = [subprocess.run([sys.executable, "-c", script, str(tmp_path / str(j))],
                              env=os.environ | {"PYTHONHASHSEED": seed}, check=True, capture_output=True).stdout
               for j, seed in enumerate(("0", "random"))]
    assert results[0] == results[1]


def refuses(template, db, schedule):
    tokens = [r[0] for r in db.execute("SELECT value FROM locked_token")]
    with pytest.raises(ValueError) as caught:
        template.instances(db, schedule)
    assert str(caught.value) and all(t not in str(caught.value) for t in tokens)


def test_checkpoint_and_step_refusals(lives):
    life = lives["drift"]
    refuses(replace(CATALOGUE["drift-booking"], checkpoint=2), life.dbs[0], life.schedule)
    with pytest.raises(ValueError, match="get_mail"):
        step("get_mail", "slot", {})
    for tool in ("cancel_booking", "missing"):
        with pytest.raises(ValueError):
            step(tool, "slot", {})


@pytest.mark.parametrize("case", ["missing", "behaviour", "global", "no-update", "update", "asof"])
def test_preference_refusals(tmp_path, case):
    db, s, people = new_world(tmp_path / "world.db", "g15-refuse-pref")
    try:
        if case != "missing":
            fields = dict(provenance="behaviour", scope=("context", "long_haul")) if case == "behaviour" else dict(
                scope=("global", None) if case == "global" else ("context", "long_haul"),
                depth=1 if case == "update" else 0, mention=None if case == "update" else "hedge")
            write_preferences(db, s, [Pref(id="seat-long", domain="seat", stem="SEAT", **fields)],
                              principal=people.principal)
        template = CATALOGUE["drift-asof" if case == "asof" else "drift-booking"]
        if case == "update":
            template = replace(template, control=True)
        refuses(template, db, s)
    finally:
        db.close()


def test_incidental_refusals(tmp_path):
    db, s, people = new_world(tmp_path / "world.db", "g15-refuse-inc")
    template = CATALOGUE["keep-incidental"]
    try:
        refuses(template, db, s)
        # Deliberately malformed substrate: two decoys cannot be emitted by the writer.
        with lineage.atomic(db):
            for n in range(3):
                rows.insert_fact(db, id=mint(s, "incidental", "gate", "fact", "detail", n),
                                 subject_id=people.people[n], predicate="gate_code", object="detail",
                                 polarity="affirm", modality="stated", strength=1000, speech_act="assert")
        refuses(template, db, s)
    finally:
        db.close()


def test_forget_refusals(lives, tmp_path):
    life = lives["forget"]
    db, s = life.dbs[0], life.schedule
    # Probe earlier without changing the real schedule's events.
    early = replace(s, scale=replace(s.scale, checkpoints=(2,)))
    refuses(CATALOGUE["keep-forget"], db, early)
    refuses(replace(CATALOGUE["keep-forget"], forget_key="missing"), db, s)
    neigh = lives["neigh"]
    refuses(replace(CATALOGUE["keep-neighbour"], predicate="address"), neigh.dbs[0], neigh.schedule)
    refuses(CATALOGUE["keep-neighbour"], db, s)
    # The G07 request's own neighbour is only evidenced in the covered-fact event.
    # Supply an attr so the decisive lookup succeeds, then exercise span contamination.
    own, s, people = new_world(tmp_path / "own.db", "g15-own-neighbour")
    try:
        fr = write_forget(own, s, key="neigh", subject=people.people[4], covered=(("address", "ADDR"),),
                          neighbours=(("birthday", "BDAY"),), principal=people.principal,
                          at=((1, 2), (2, 2), (3, 2)))
        f = own.execute("SELECT * FROM fact WHERE id=?", (fr.neighbours[0],)).fetchone()
        event = own.execute("SELECT event_id FROM link WHERE fact_id=?", (f["id"],)).fetchone()[0]
        with lineage.atomic(own):
            rows.insert_attr(own, entity_id=fr.subject_id, key="birthday", value=json.loads(f["object"]),
                             valid_from_t=slot(s, 1, 2), valid_to_t=None, recorded_t=slot(s, 1, 2),
                             source_event_id=event)
        refuses(CATALOGUE["keep-neighbour"], own, s)
    finally:
        own.close()


@pytest.mark.parametrize("case", ["time", "no-lure", "early-window"])
def test_tuesday_refusals(tmp_path, case):
    db, s, people = new_world(tmp_path / "world.db", f"g15-refuse-{case}")
    try:
        ents = [write_entity(db, s, kind="trip" if j == 0 else "purchase", key=str(j), name=f"Target {j}")
                for j in range(3)]
        fields = {} if case == "time" else dict(cue_subject=ents[1], cue_key="delivery", cue_stem="PARCEL",
                                               sender=people.people[1], lures=() if case == "no-lure" else (ents[2],))
        with lineage.atomic(db):
            write_commitments(db, s, [Commitment(id="passport", subject=ents[0], predicate="book", stem="TRIP",
                                                trigger="time" if case == "time" else "event", made=(1, 1),
                                                due=(2 if case == "early-window" else 3, 1), **fields)],
                              principal=people.principal)
        refuses(CATALOGUE["tue-passport"], db, s)
    finally:
        db.close()


def test_count_zero_refusal(tmp_path):
    db, s, people = new_world(tmp_path / "world.db", "g15-refuse-count")
    try:
        trip = write_entity(db, s, kind="trip", key="trip", name="Trip")
        with lineage.atomic(db):
            write_corrections(db, s, [Chain(id="trip", subject=trip, key="date", stem="DATE", depth=0,
                                            mention="hedge")], principal=people.principal)
        refuses(CATALOGUE["recall-count"], db, s)
    finally:
        db.close()


def test_common_row_refusals(lives):
    life = lives["drift"]
    db, s = life.dbs[0], life.schedule
    with pytest.raises(ValueError, match="absent"):
        token(db, "absent")
    with pytest.raises(ValueError, match="absent"):
        name(db, "absent")
    assert linking(db, (), s.sessions[-1].t_end) == ()
