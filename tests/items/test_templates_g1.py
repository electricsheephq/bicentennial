"""G14 micro-lives, real repository scoring and seeded placement properties."""

import ast
import json
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.decision_table import predicate_names
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.genres.g1_software.codebase_model import PATHS, PROCESS, write_commit
from bicentennial.genres.g1_software.diffs import (
    end_boundary,
    read_state,
    render,
    repo_tree_hashes,
)
from bicentennial.genres.g1_software.repo import materialize, workspace_hash
from bicentennial.genres.g1_software.world import (
    KINDS,
    Statement,
    build_g1,
    tail_filler,
    world_meta,
    write_statements,
)
from bicentennial.items.bundle import compile_life
from bicentennial.items.compile import compile_branch
from bicentennial.items.templates.g1 import (
    G1_MUTANT_ROLES,
    TEMPLATES,
    option_roles,
    repo_checks,
)
from bicentennial.items.templates.g1.common import (
    LEVER_MIX_LABEL,
    PICKUP_W,
    PREDICATE_KINDS,
    REPO_TOOLS_BY_NAME,
    apply_steps,
    fact,
    linking,
    mentions,
    name,
    position,
    repo_state,
    role,
    step,
    token,
    value,
)
from bicentennial.keyed import uniform_int
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import content
from bicentennial.score.action import Trace, score_action
from bicentennial.score.qa import score_qa
from bicentennial.world import create_world, lineage, open_world, unit, world_hash
from bicentennial.world.db import insert_entity
from bicentennial.world.processes import check_tokens, mint
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.processes.forget import verify
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions
from bicentennial.world.twin import twin_life

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = {t.template_id: t for t in TEMPLATES}
LIVES = {"chain": "drift-chain", "fault": "drift-chain-fault", "config": "drift-config",
         "quote": "drift-quote", "wake": "wake-loop", "recall": "recall-value", "tue": "tue-ticket"}


def expected_state(db, schedule):
    return {k: {"repo_tree_hash": h, "env_state_hash": sha256_canon({})}
            for k, h in repo_tree_hashes(db, schedule).items()}


def new_world(path, seed, *, wake=None):
    s = build_schedule(seed, "life-a", named("t0-micro", sessions=3, wake=wake))
    db = create_world(path, world_meta(seed, 3))
    write_sessions(db, s)
    entities = {}
    for kind, names in [("person", ("Heron", "Wren")), *[(k, v[0]) for k, v in KINDS.items()]]:
        for j, label in enumerate(names):
            eid = mint(s, PROCESS, "entities", "entity", kind, j)
            insert_entity(db, id=eid, kind=kind, canonical_name=label, aliases_json=[],
                          created_t=s.sessions[0].t_start, retired_t=None)
            entities[label] = eid
    return db, s, entities


def finish(db, s, principal):
    tail_filler(db, s, principal=principal)
    write_filler(db, s, principal=principal)
    check_tokens(db)
    verify(db)
    db.commit()


def chain(s, uid, n):
    return mint(s, "corrections", uid, "fact", "value", n)


def statement(s, uid):
    return mint(s, PROCESS, uid, "fact", "value", 0)


def commitment(s, part, table="fact", n=0):
    return mint(s, "commitments", "commitment-1", table, part, n)


def writers(db, s, e, which, *, depth=1, mention="quote", at=True, commit_p=True,
            commit_h=False, subject=None, due=(3, 1), trigger="event", lures=True, statement_at=None):
    p = e["Heron"]
    if which in ("chain", "fault", "config", "quote"):
        uid = {"chain": "deadline-0", "fault": "deadline-1", "config": "setting-fix",
               "quote": "setting-quote"}[which]
        subject = subject or {"chain": "beta release", "fault": "general release",
                              "config": "batch_size", "quote": "flush_timeout_ms"}[which]
        d = 0 if which == "quote" else depth
        m = mention if which == "quote" else None
        count = d + 1 + (m is not None)
        with lineage.atomic(db):
            write_corrections(db, s, [Chain(id=uid, subject=e[subject], key="deadline" if which in (
                "chain", "fault") else "value", stem="DUE" if which in ("chain", "fault") else "CONST",
                depth=d, mention=m, at=tuple((j + 1, 2) for j in range(count)) if at else None)], principal=p)
            if which == "config" and commit_p:
                write_commit(db, s, unit_id=uid, n=0, fact_id=chain(s, uid, 0), author=e["Wren"])
            if commit_h:
                write_commit(db, s, unit_id=uid, n=1, fact_id=chain(s, uid, 1), author=e["Wren"])
    elif which in ("wake", "recall"):
        uid, label = ("decision-1", "retry policy") if which == "wake" else ("decision-0", "queue backend")
        write_statements(db, s, [Statement(id=uid, subject=e[label], key="choice", stem="DECISION",
                                          at=statement_at or (1, 3 if which == "wake" else 2))], principal=p)
    else:
        with lineage.atomic(db):
            write_commitments(db, s, [Commitment(
                id="commitment-1", subject=e["release checklist"], predicate="deliver", stem="TASK", trigger=trigger,
                cue_subject=e["schema migration"] if trigger != "time" else None,
                cue_key="status" if trigger != "time" else None, cue_stem="TICKET" if trigger != "time" else None,
                lures=(e["load test"],) if lures and trigger != "time" else (),
                sender=e["Wren"] if trigger != "time" else None, cancelled=True, channel="chat",
                notice_channel="chat", made=(1, 1), due=due)], principal=p)


def make_life(path, which):
    path.mkdir()
    db, s, e = new_world(path / "base.db", f"g14-{which}", wake="kill" if which == "fault" else None)
    writers(db, s, e, which)
    finish(db, s, e["Heron"])
    templates = (CATALOGUE[LIVES[which]],)
    if which != "recall":
        twin = twin_life(db, s, templates, world_path=path / "twin.db", out_dir=path / "streams",
                         principal_id=e["Heron"], expected_state=lambda d: expected_state(d, s))
        dbs, cuts, compiled = (db, twin.b1), twin.cuts, twin.compiled
    else:
        dbs = (db, db)
        cuts = tuple(cut(db, s, branch=b, principal_id=e["Heron"], expected_state=expected_state(db, s))
                     for b in ("B0", "B1"))
        compiled = compile_life(*(compile_branch(db, s, c, templates) for c in cuts))
    return SimpleNamespace(dbs=dbs, schedule=s, entities=e, templates=templates, cuts=cuts, compiled=compiled,
                           path=path / "base.db")


@pytest.fixture(scope="module")
def lives(tmp_path_factory):
    root = tmp_path_factory.mktemp("g14-lives")
    result = {which: make_life(root / which, which) for which in LIVES}
    yield result
    for life in result.values():
        life.dbs[0].close()
        if life.dbs[1] is not life.dbs[0]:
            life.dbs[1].close()


def reader(item, text):
    text = unicodedata.normalize("NFC", text)
    return next((o for o in item["options"] if o["tokens"] and all(
        unicodedata.normalize("NFC", t) in text for t in o["tokens"])),
        next((o for o in item["options"] if not o["tokens"]), None))


def entry(life, b):
    return compile_branch(life.dbs[b], life.schedule, life.cuts[b], life.templates).entries[0]


def gold_facts(db, s, which, b):
    if which in ("chain", "fault", "config", "quote"):
        uid = {"chain": "deadline-0", "fault": "deadline-1", "config": "setting-fix",
               "quote": "setting-quote"}[which]
        return tuple(chain(s, uid, j) for j in ((0, 1) if which == "quote" else (1,)))
    if which in ("wake", "recall"):
        return (statement(s, "decision-1" if which == "wake" else "decision-0"),)
    return (commitment(s, "cancel"),) if b == 0 else (commitment(s, "made"), commitment(s, "cue"))


@pytest.mark.parametrize("which", LIVES)
def test_micro_lives(lives, which):
    life = lives[which]
    c = life.compiled
    assert len(c.bundles) == (0 if which == "recall" else 1)
    assert len(c.items) == len(c.records) == 2
    for kind, values in (("item", c.items), ("bundle", c.bundles), ("item_record", c.records)):
        for obj in values:
            validate(kind, obj)
    for b, db in enumerate(life.dbs):
        item, meta = entry(life, b)
        assert item["memory_tag"] == "memory_exclusive"
        assert item["stage"] == ("remember" if which == "recall" else "act")
        assert meta["crossed"] == (["crash"] if which == "fault" else [])
        if which == "fault":
            assert item["labels"] == ["voice: template"]
        gold = item["options"][0]
        assert gold["tokens"] == [token(db, f) for f in gold_facts(db, life.schedule, which, b)]
        assert gold["tokens"]
        assert reader(item, "".join(content(r) for r in life.cuts[b].rows)) == gold
        empty = reader(item, "")
        if which == "config" and b == 1 or which == "tue" and b == 0:
            assert empty is None
        else:
            assert empty is not None and not empty["tokens"]
        if which == "config":
            assert len(gold["plan"]["steps"]) == (1 if b == 0 else 0)
            assert fact(db, chain(life.schedule, "setting-fix", 1))["speech_act"] == ("assert" if b == 0 else "hedge")
        if which == "tue":
            assert meta["levers"]["distance_sessions"] == 0  # placement issue #105
    if which == "config":
        assert repo_tree_hashes(life.dbs[0], life.schedule) == repo_tree_hashes(life.dbs[1], life.schedule)
    expected_duty = {entry(life, b)[0]["item_id"] for b in range(2) if which == "wake" or which == "tue" and b == 1}
    assert c.duty_items() == expected_duty
    assert len(c.singleton_lives()) == (2 if which == "recall" else 0)


def predicates(table, instance, state0, state):
    result = {}
    for pred in predicate_names(table):
        kind, target = pred.split(":")
        groups = [o.plan["steps"] for o in instance.options if role(o.key) == target and o.plan["steps"]]
        result[pred] = any(all(state[a["path"]].get(a["name"]) == a["value"] for a in args)
                           and (kind == "holds" or any(state0[a["path"]].get(a["name"]) != a["value"]
                                                      for a in args))
                           for steps in groups for args in [[s["tool"]["args"] for s in steps]])
    return result


def score(life, b, steps, *, state0=None):
    db, template = life.dbs[b], life.templates[0]
    item, _ = entry(life, b)
    instance, = template.instances(db, life.schedule)
    table = next(t for t in template.decision_tables if t["table_id"] == item["decision_table_ref"])
    state0 = repo_state(db, life.schedule, 3) if state0 is None else state0
    state = apply_steps(state0, steps)
    row = db.execute("SELECT * FROM commitment").fetchone() if table["timed"] else None
    window = (row["window_open_t"], row["window_close_t"]) if row else None
    return score_action(item, table, Trace(False, state != state0, window[0] if steps and window else None),
                        predicates(table, instance, state0, state), window=window)


@pytest.mark.parametrize("which", [w for w in LIVES if w != "recall"])
def test_real_repository_scoring(lives, which, tmp_path):
    life = lives[which]
    for b, db in enumerate(life.dbs):
        root = tmp_path / f"repo-{b}"
        repo = materialize(db, life.schedule, branch=f"B{b}", boundary=end_boundary(life.schedule, 3), root=root)
        item, _ = entry(life, b)
        assert repo.repo_tree_hash == expected_state(db, life.schedule)[3]["repo_tree_hash"]
        assert workspace_hash(root) == repo.repo_tree_hash
        state0 = read_state(root)
        assert state0 == repo_state(db, life.schedule, 3)
        instance, = life.templates[0].instances(db, life.schedule)
        roles = option_roles(life.templates[0], db, life.schedule)[instance.key]
        for j, option in enumerate(item["options"]):
            steps = option["plan"]["steps"]
            state = apply_steps(state0, steps)
            clone = tmp_path / f"copy-{b}-{j}"
            shutil.copytree(root, clone)
            for path, data in render(state).items():
                (clone / path).write_bytes(data)
            assert read_state(clone) == state
            assert (workspace_hash(clone) != repo.repo_tree_hash) == (state != state0)
            result = score(life, b, steps, state0=state0)
            if j == 0:
                assert (result.base_verdict, result.score_milli) == ("PASS", 1000)
                if which == "tue" and b == 1:
                    assert result.tuesday_class == "on_time"
                if which == "config":
                    run = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"],
                                         cwd=clone, capture_output=True, timeout=30)
                    assert run.returncode == 0, run.stderr.decode()
            elif steps:
                assert (result.base_verdict, result.score_milli) == ("FAIL_MEMORY", -1000)
                if which == "tue":
                    assert roles[option["option_id"]] in ("book", "lure")
                    assert result.tuesday_class == "false_alarm"
            else:
                assert (result.base_verdict, result.score_milli) == ("OMISSION", 0)
        empty = score(life, b, [])
        refrain = which == "config" and b == 1 or which == "tue" and b == 0
        assert (empty.base_verdict, empty.score_milli) == (("PASS", 1000) if refrain else ("OMISSION", 0))
        if which == "tue":
            every = [s for o in item["options"] for s in o["plan"]["steps"]]
            result = score(life, b, every)
            assert (result.score_milli, result.tuesday_class) == (-1000, "false_alarm")
            if b == 1:
                assert empty.tuesday_class == "never"
    assert min(score(life, b, []).score_milli for b in range(2)) <= 0


def test_recall_citations(lives, tmp_path):
    life = lives["recall"]
    for b in range(2):
        db, s = life.dbs[b], life.schedule
        root = tmp_path / f"recall-{b}"
        repo = materialize(db, s, branch=f"B{b}", boundary=end_boundary(s, 3), root=root)
        assert repo.repo_tree_hash == expected_state(db, s)[3]["repo_tree_hash"] == workspace_hash(root)
        assert read_state(root) == repo_state(db, s, 3)
        item, _ = entry(life, b)
        gold = item["options"][0]["envelope"]
        evidence = [content(r) for r in life.cuts[b].rows if r["event_id"] in item["gold_spans"]]
        for quote, expected in ((item["options"][0]["tokens"][0], 1000), ("absent quotation", -1000)):
            answer = gold | {"citation": {"quote": quote, "context_offset": 0}}
            assert score_qa(item, answer, evidence_texts=evidence).score_milli == expected
        assert score_qa(item, item["options"][-1]["envelope"] | {"citation": None}, evidence_texts=evidence).score_milli == 0


def test_drift_gate(lives):
    minima = {}
    drift = ("chain", "fault", "config", "quote")
    for policy in ("latest", "first", "reverse-latest"):
        minima[policy] = []
        for which in drift:
            life = lives[which]
            scores = []
            for b, db in enumerate(life.dbs):
                inst, = life.templates[0].instances(db, life.schedule)
                target = fact(db, inst.decisive_fact_id)
                facts = mentions(db, target["subject_id"], target["predicate"], life.schedule.sessions[-1].t_end)
                f = facts[-1] if policy == "latest" else facts[0] if policy == "first" else facts[-2]
                path = "docs/decisions.md" if which in ("chain", "fault") else PATHS["constant"]
                steps = [step(path, name(db, target["subject_id"]), value(db, f))]
                scores.append(score(life, b, steps).score_milli)
            minima[policy].append(min(scores))
    assert minima == {"latest": [1000, 1000, -1000, -1000], "first": [-1000, -1000, 0, 1000],
                      "reverse-latest": [-1000, -1000, 0, 1000]}
    assert {k: sum(v) // 4 for k, v in minima.items()} == {"latest": 0, "first": -250, "reverse-latest": -250}
    single = sum(lives[w].compiled.bundles[0]["twin_type"] == "fork" and
                 entry(lives[w], 0)[1]["levers"]["chain_depth"] == 1 for w in drift)
    later = sum(any(fact(lives[w].dbs[b], f)["speech_act"] in ("hedge", "quote")
                    for b in range(2) for f in gold_facts(lives[w].dbs[b], lives[w].schedule, w, b)) for w in drift)
    assert single == later == 2 and single * 100 >= 30 * len(drift)
    tue = lives["tue"]
    assert {next(t["gold"] for t in tue.templates[0].decision_tables if t["table_id"] == entry(tue, b)[0][
        "decision_table_ref"]) for b in range(2)} == {"act", "refrain"}


def test_200_keyed_placements(tmp_path):
    for c in range(200):
        seed = f"g14-{c}"
        db, s, e = new_world(tmp_path / f"{c}.db", seed)
        try:
            depth = uniform_int(seed, unit("g14", "drift", str(c)), 0, "depth", 1, 2)
            writers(db, s, e, "chain", depth=depth, at=False)
            writers(db, s, e, "quote", at=False)
            finish(db, s, e["Heron"])
            templates = (replace(CATALOGUE["drift-chain"], depth=depth), CATALOGUE["drift-quote"])
            context = cut(db, s, branch="B0", principal_id=e["Heron"], expected_state=expected_state(db, s))
            compiled = compile_branch(db, s, context, templates)
            for item, meta in compiled.entries:
                assert reader(item, "".join(content(r) for r in context.rows)) == item["options"][0]
                if meta["template_id"] == "drift-chain":
                    assert meta["levers"]["chain_depth"] == depth
                    inst, = templates[0].instances(db, s)
                    assert inst.options[0].token_fact_ids == (chain(s, "deadline-0", depth),)
                    assert [o.token_fact_ids for o in inst.options[1:-1]] == [(chain(s, "deadline-0", j),) for j in range(depth)]
                    assert [o.plan["steps"][0]["tool"]["args"]["value"] for o in inst.options[:-1]] == [
                        value(db, chain(s, "deadline-0", j)) for j in (depth, *range(depth))]
                else:
                    assert meta["levers"]["chain_depth"] == 0
                    assert item["options"][0]["tokens"] == [token(db, chain(s, "setting-quote", j)) for j in (0, 1)]
        finally:
            db.close()


@dataclass(frozen=True, kw_only=True)
class Check:
    kind: str
    path: str
    name: str
    value: str


def evaluate_groups(groups, state0, state):
    # changed is group-level: all steps hold, and at least one differs from S0.
    return any(all(state[c.path].get(c.name) == c.value for c in g)
               and (g[0].kind == "holds" or any(state0[c.path].get(c.name) != c.value for c in g)) for g in groups)


def test_or_groups_and_depth_two(tmp_path):
    db, s, e = new_world(tmp_path / "groups.db", "g14-groups")
    try:
        writers(db, s, e, "chain", depth=2)
        writers(db, s, e, "tue")
        for template in (replace(CATALOGUE["drift-chain"], depth=2), CATALOGUE["tue-ticket"]):
            inst, = template.instances(db, s)
            mappings = repo_checks(template, db, s, check_type=Check)[inst.key]
            state0 = repo_state(db, s, 3)
            table = next(t for t in template.decision_tables if t["table_id"] == inst.decision_table_ref)
            for opt in inst.options:
                state = apply_steps(state0, opt.plan["steps"])
                assert {p: evaluate_groups(g, state0, state) for p, g in mappings.items()} == predicates(table, inst, state0, state)
            if template.template_id == "drift-chain":
                assert len(mappings["changed:other"]) == 2
                groups = tuple(tuple(replace(c, kind="holds") for c in g) for g in mappings["changed:other"])
                for opt in inst.options[1:3]:
                    assert evaluate_groups(groups, state0, apply_steps(state0, opt.plan["steps"]))
                assert not evaluate_groups(groups, state0, apply_steps(state0, inst.options[0].plan["steps"]))
                assert not evaluate_groups(groups, state0, state0)
    finally:
        db.close()


def test_base_life(tmp_path):
    s = build_schedule("g14-base", "life-a", named("t1"))
    db = create_world(tmp_path / "base.db", world_meta(s.seed, 20))
    try:
        people = build_g1(db, s)
        db.commit()
        base = CATALOGUE["drift-chain"]
        facts = tuple(chain(s, "deadline-0", j) for j in (0, 1))
        points = [position(s, db.execute("SELECT t_sim FROM event WHERE id=?", (eid,)).fetchone()[0])
                  for eid in linking(db, facts, s.sessions[-1].t_end)]
        template = replace(base, fault=all(p <= (11, 1) for p in points))
        context = cut(db, s, branch="B0", principal_id=people.principal, expected_state=expected_state(db, s))
        for t in (CATALOGUE["recall-value"], template):
            compiled = compile_branch(db, s, context, (t,))
            assert len(compiled.entries) == 1
            assert compiled.entries[0][0]["memory_tag"] == "memory_exclusive"
        for ident, uid in (("drift-config", "constant-0"), ("drift-quote", "constant-1")):
            with pytest.raises(ValueError):
                replace(CATALOGUE[ident], chain_id=uid).instances(db, s)
    finally:
        db.close()


@pytest.mark.parametrize("case", [
    "checkpoint", "chain-depth", "chain-committed", "chain-present", "chain-no-kill", "chain-crossed",
    "config-uncommitted", "config-h-committed", "config-depth2", "config-nonconstant",
    "quote-depth1", "quote-hedge", "wake-committed", "wake-same-session", "recall-committed",
    "tue-time", "tue-no-lure", "tue-early", "tue-present",
])
def test_refusals(tmp_path, case):
    which = case.split("-")[0]
    which = "chain" if which == "checkpoint" else which
    db, s, e = new_world(tmp_path / "refuse.db", f"g14-refuse-{case}", wake="kill" if case == "chain-crossed" else None)
    try:
        kwargs = {"commit_p": case != "config-uncommitted", "commit_h": case == "config-h-committed",
                  "depth": 2 if case in ("chain-depth", "config-depth2") else 1,
                  "subject": "retry policy" if case == "config-nonconstant" else None,
                  "mention": "hedge" if case == "quote-hedge" else "quote",
                  "statement_at": (3, 2) if case == "wake-same-session" else None,
                  "trigger": "time" if case == "tue-time" else "event", "lures": case != "tue-no-lure",
                  "due": (2, 1) if case == "tue-early" else (3, 1)}
        if case == "quote-depth1":
            with lineage.atomic(db):
                write_corrections(db, s, [Chain(id="setting-quote", subject=e["flush_timeout_ms"], key="value",
                                                stem="CONST", depth=1, at=((1, 2), (2, 2)))], principal=e["Heron"])
        else:
            writers(db, s, e, which, **kwargs)
        if case in ("chain-committed", "wake-committed", "recall-committed", "tue-present"):
            fid = (statement(s, "decision-1" if which == "wake" else "decision-0") if which in ("wake", "recall")
                   else commitment(s, "made") if which == "tue" else chain(s, "deadline-0", 0))
            if which == "chain":
                # A milestone has no G05 repository path; a repo surface still disqualifies it.
                from bicentennial.world.db import insert_fact_surface
                insert_fact_surface(db, fact_id=fid, surface="repo", from_t=s.sessions[0].turn_t[1])
            elif which == "tue":
                # A commitment has no G05 path: a committed decision with the same canonical name occupies it.
                insert_entity(db, id="occupied", kind="decision", canonical_name="release checklist", aliases_json=[],
                              created_t=s.sessions[0].t_start, retired_t=None)
                write_statements(db, s, [Statement(id="occupied", subject="occupied", key="choice", stem="OTHER", at=(1, 3))],
                                 principal=e["Heron"])
                write_commit(db, s, unit_id="occupied", n=0, fact_id=statement(s, "occupied"), author=e["Wren"])
            else:
                write_commit(db, s, unit_id="refusal", n=0, fact_id=fid, author=e["Wren"])
        if case == "chain-present":
            insert_entity(db, id="occupied", kind="decision", canonical_name="beta release", aliases_json=[],
                          created_t=s.sessions[0].t_start, retired_t=None)
            write_statements(db, s, [Statement(id="occupied", subject="occupied", key="choice", stem="OTHER", at=(1, 3))],
                             principal=e["Heron"])
            write_commit(db, s, unit_id="occupied", n=0, fact_id=statement(s, "occupied"), author=e["Wren"])
        template = CATALOGUE[LIVES[which]]
        if case == "checkpoint":
            template = replace(template, checkpoint=2)
        if case == "chain-no-kill":
            template = replace(template, fault=True)
        with pytest.raises(ValueError) as error:
            template.instances(db, s)
        assert not any(r[0] in str(error.value) for r in db.execute("SELECT value FROM locked_token"))
    finally:
        db.close()


def test_plan_refusals_and_copy():
    for args in (("service/app.py", "setting", "VALUE-100001"), (PATHS["constant"], "bad:name", "VALUE-100001"),
                 (PATHS["constant"], "setting", 'bad"value'), (PATHS["constant"], "setting", "short\n")):
        with pytest.raises(ValueError):
            step(*args)
    state = {p: {} for p in PATHS.values()}
    for entry in ({"tool": {"name": "unknown", "args": {}}},
                  {"tool": {"name": "set_entry", "args": {"path": "other", "name": "setting", "value": "VALUE"}}}):
        with pytest.raises(ValueError):
            apply_steps(state, [entry])
    steps = [step(PATHS["constant"], "setting", v) for v in ("VALUE-100001", "VALUE-100002")]
    assert apply_steps(state, steps)[PATHS["constant"]]["setting"] == "VALUE-100002"
    assert all(not entries for entries in state.values())


@pytest.mark.parametrize("which", LIVES)
def test_read_only_purity(lives, which):
    life = lives[which]
    db, s = life.dbs[0], life.schedule
    before = world_hash(db)
    writer_result = compile_branch(db, s, life.cuts[0], life.templates)
    with open_world(life.path) as readonly:
        assert compile_branch(readonly, s, life.cuts[0], life.templates) == writer_result
        assert world_hash(readonly) == before
    assert world_hash(db) == before


def test_catalogue_and_imports():
    assert len(TEMPLATES) == 7 and list(CATALOGUE) == sorted(set(CATALOGUE))
    canary = json.loads((SCHEMAS / "decision_table.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
    assert PICKUP_W == 5 and PREDICATE_KINDS == ("holds", "changed")
    assert REPO_TOOLS_BY_NAME["set_entry"]["op"] == "set"
    for t in TEMPLATES:
        assert t.checkpoint is None and t.semantics == "as_known"
        mix = t.lever_mix
        assert mix["label"] == LEVER_MIX_LABEL and type(mix["value"]) in (int, type(None))
        assert canon(mix) == canon(json.loads(canon(mix)))
        for tab in t.decision_tables:
            validate("decision_table", tab)
            assert tab["canary"] == canary and tab["benign_extras"] == []
            mutants = G1_MUTANT_ROLES[tab["table_id"]]
            assert {f"changed:{r}" for roles in mutants.values() for r in roles} == {d["predicate"] for d in tab["disqualifiers"]}
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess", "shutil", "spikes",
                 "bicentennial.sandbox", "bicentennial.director", "bicentennial.render", "bicentennial.world.twin",
                 "bicentennial.genres.g1_software.diffs", "bicentennial.genres.g1_software.repo")
    for path in (ROOT / "src/bicentennial/items/templates/g1").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            modules = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(m == p or m.startswith(p + ".") for m in modules for p in forbidden)
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))


def test_determinism_subprocesses(tmp_path):
    script = ("import runpy,sys; from pathlib import Path; from bicentennial.canon import canon; "
              "m=runpy.run_path('tests/items/test_templates_g1.py'); "
              "lives=[m['make_life'](Path(sys.argv[1])/w,w) for w in ('tue','config')]; "
              "sys.stdout.buffer.write(canon([[l.compiled.items,l.compiled.bundles,l.compiled.records] for l in lives]))")
    outputs = []
    for seed in ("0", "random"):
        root = tmp_path / seed
        root.mkdir()
        run = subprocess.run([sys.executable, "-c", script, str(root)], cwd=ROOT,
                             env={"PYTHONHASHSEED": seed}, capture_output=True, timeout=60)
        assert run.returncode == 0, run.stderr.decode()
        outputs.append(run.stdout)
    assert outputs[0] == outputs[1]
