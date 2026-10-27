"""G13 exact swaps, generator goldens, independence and keyed 200-case properties."""

import ast
import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.items.compile import compile_branch
from bicentennial.items.protocol import Instance, Option, Template
from bicentennial.keyed import choice, shuffle, uniform_int
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import (
    history_set_hash,
    stream_bytes,
    stream_hash,
    verify_branch,
)
from bicentennial.world import db as writers
from bicentennial.world import twin, unit
from bicentennial.world.bitemporal import as_known, as_valid
from bicentennial.world.export import export_jsonl, export_world, world_hash
from bicentennial.world.lineage import Ev, record, write_event, write_fact
from bicentennial.world.processes import (
    check_tokens,
    check_values,
    mint,
    slot,
    token_value,
)
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.processes.forget import forget_request, request_forget, verify
from bicentennial.world.processes.incidental import Detail, write_details
from bicentennial.world.processes.plants import (
    plant,
    rejection,
    write_authority_rule,
    write_plant,
)
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions

LIFE = "life-a"
TYPES = {"value": "fork", "cancel": "lure", "forget": "trigger", "correction": "trigger", "source": "genuine"}
NAMES = ("principal", "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "third", "authorised")


def base(path, seed="g13-golden"):
    db = writers.create_world(path, dict(generator_version="g13-test", genre="test", seed=seed, scale=3))
    schedule = build_schedule(seed, LIFE, named("t0-micro", sessions=3))
    write_sessions(db, schedule)
    for name in NAMES:
        writers.insert_entity(db, id=name, kind="person", canonical_name=name.title(), aliases_json=[],
                              created_t=0, retired_t=None)
    return db, schedule


def ev(t, actor="principal"):
    return Ev(t_sim=t, kind="message", channel="chat", actor_id=actor, audience=("agent",),
              visibility="shared", salience=500)


def finish(db, schedule):
    write_filler(db, schedule, principal="principal")
    db.commit()


def state(db):
    return {i: dict(repo_tree_hash="a" * 64, env_state_hash="b" * 64) for i in (1, 2, 3)}


def chain(db, s, *, id="chain", subject="alpha", depth=1, mention=None, **kwargs):
    write_corrections(db, s, [Chain(id=id, subject=subject, key="status", stem="VALUE", depth=depth,
                                   mention=mention, at=((1, 2), (2, 2)), **kwargs)], principal="principal")
    return mint(s, "corrections", id, "fact", "value", 1)


def commitment(db, s, *, id="duty", cancelled=True, trigger="time"):
    fields = {} if trigger == "time" else dict(cue_subject="gamma", cue_key="notice", cue_stem="NOTICE", sender="third")
    write_commitments(db, s, [Commitment(id=id, subject="beta", predicate="deliver", stem="DUTY",
                                        trigger=trigger, cancelled=cancelled, made=(1, 4), due=(3, 1), **fields)],
                      principal="principal")
    return mint(s, "commitments", id, "fact", "made", 0)


def detail(db, s, *, id="detail", subject="gamma", predicate="locker", at=None):
    write_details(db, s, [Detail(id=id, subject=subject, predicate=predicate, stem="LOCKER",
                                decoys=("delta", "epsilon", "zeta"),
                                at=at or ((1, 1), (1, 2), (1, 3), (1, 4)))], principal="principal")
    return mint(s, "incidental", id, "fact", "detail", 0)


def forgetting(db, s, *, request=True):
    f = detail(db, s)
    detail(db, s, id="neighbour", predicate="birthday", at=((1, 2), (1, 3), (1, 4), (1, 5)))
    write_event(db, "derived-event", ev(slot(s, 2, 3)), ("chat",))
    write_fact(db, "derived-fact", "derived-event", subject_id="gamma", predicate="memo", object="recorded")
    record(db, artifact_kind="fact", artifact_id="derived-fact", sources=(f,))
    record(db, artifact_kind="event", artifact_id="derived-event", sources=(f,))
    if request:
        request_forget(db, life=LIFE, key="forget", event=ev(slot(s, 3, 4)), subject_id="gamma", predicates=("locker",))
    return f


def source(db, s, *, authority=True, evidence=False, token=False, tool_evidence=False):
    if authority:
        write_authority_rule(db, life=LIFE, key="authority", event=ev(slot(s, 1, 3)),
                             authorised_id="authorised", predicate="approval")
    if evidence:
        if tool_evidence:
            writers.insert_event(db, id="evidence-event", t_sim=slot(s, 1, 5), kind="tool", channel="tool_result",
                                 actor_id="principal", audience_json=["agent"], visibility="shared", salience=500,
                                 payload_json={"tool": {"name": "approval", "args": {}}, "result": {"approval": "declined"}})
        else:
            write_event(db, "evidence-event", ev(slot(s, 1, 5)), ("chat",))
        write_fact(db, "evidence-fact", "evidence-event", subject_id="epsilon", predicate="approval", object="declined",
                   modality="observed" if tool_evidence else "stated")
    value = token_value(db, s, "test", "source", "value", 0, "SOURCE") if token else "accepted"
    p = write_plant(db, life=LIFE, key="plant", kind="third_party_claim", carrier=ev(slot(s, 3, 5), "third"),
                    subject_id="epsilon", predicate="approval", object=value, polarity="affirm",
                    speech_act="quote", strength=1000)
    if token:
        writers.insert_locked_token(db, token_id="source-token", fact_id=p.fact_id, kind="code", value=value)
    return p.fact_id


def flip(db, s, kind, f, key=None):
    return twin.plan_flip(db, s, key=key or (kind, "one"), twin_type=TYPES[kind], decisive_fact_id=f,
                          principal_id="principal")


def lines(db):
    return set(export_jsonl(db).splitlines())


def assert_swap(db0, db1, flips):
    a, b = lines(db0), lines(db1)
    assert a - b == {line for f in flips for line in f.out}
    assert b - a == {line for f in flips for line in f.into}


def assert_involution(db0, db1, flips, path):
    back = twin.apply(db1, flips, path)
    assert world_hash(back) == world_hash(db0)
    back.close()


def cuts(db0, db1, s):
    excluded = frozenset(r[0] for db in (db0, db1) for r in db.execute("SELECT value FROM locked_token"))
    return tuple(cut(db, s, branch=branch, principal_id="principal", expected_state=state(db), exclude_tokens=excluded)
                 for db, branch in ((db0, "B0"), (db1, "B1")))


def assert_diff(cs, flips):
    normalized = [{r["event_id"]: {k: v for k, v in r.items() if k not in ("seq", "sha256")} for r in c.rows} for c in cs]
    d = {e for e in normalized[0].keys() | normalized[1].keys() if normalized[0].get(e) != normalized[1].get(e)}
    assert d == {e for f in flips for e in f.events}
    prefix = min(i for c in cs for i, r in enumerate(c.rows) if r["event_id"] in d)
    raw = [stream_bytes(c.rows).splitlines() for c in cs]
    assert raw[0][:prefix] == raw[1][:prefix]
    assert raw[0][prefix] != raw[1][prefix]
    return frozenset(d), prefix


@pytest.mark.parametrize("kind", TYPES)
def test_generator_goldens(tmp_path, kind):
    db, s = base(tmp_path / "base.db")
    builders = {"value": lambda: chain(db, s), "cancel": lambda: commitment(db, s),
                "correction": lambda: chain(db, s), "forget": lambda: forgetting(db, s), "source": lambda: source(db, s)}
    fid = builders[kind]()
    finish(db, s)
    before = export_jsonl(db)
    ro = writers.open_world(tmp_path / "base.db")
    f = flip(ro, s, kind, fid)
    db1 = twin.apply(ro, (f,), tmp_path / "twin.db")
    assert_swap(db, db1, (f,))
    assert_involution(db, db1, (f,), tmp_path / "back.db")
    if kind in ("cancel", "correction", "forget"):
        expected, es = base(tmp_path / "expected.db")
        if kind == "cancel":
            commitment(expected, es, cancelled=False)
        elif kind == "correction":
            chain(expected, es, depth=0, mention="hedge")
        else:
            forgetting(expected, es, request=False)
            assert db.execute("SELECT count(*) FROM lineage").fetchone()[0] == db1.execute("SELECT count(*) FROM lineage").fetchone()[0]
        finish(expected, es)
        assert world_hash(db1) == world_hash(expected)
        expected.close()
    elif kind == "value":
        old = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchone()[0]
        others = [r[0] for r in db.execute("SELECT value FROM locked_token WHERE fact_id != ?", (fid,))]
        for n in range(8):
            alternate = token_value(db, s, "twin", fid, "value", n, old.split("-")[0])
            try:
                check_values([*others, alternate])
                break
            except ValueError:
                pass
        assert db1.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchone()[0] == alternate
        assert sorted(json.loads(line)["table"] for line in f.out) == ["attr", "fact", "locked_token"]
    else:
        p = plant(db, fid)
        assert {json.loads(line)["table"] for line in f.out} == {"fact", "plant", "event"}
        assert db1.execute("SELECT actor_id FROM event WHERE id=?", (p.carrier_event_id,)).fetchone()[0] == "authorised"
        with pytest.raises(ValueError):
            plant(db1, fid)
        assert rejection(db1, fid, p.carrier_event_id) is None
    assert_diff(cuts(db, db1, s), (f,))
    assert export_jsonl(db) == before
    with pytest.raises(sqlite3.OperationalError):
        db1.execute("INSERT INTO meta VALUES ('x', 'x', 'x', 3)")
    for connection in (db, ro, db1):
        connection.close()


class QA(Template):
    """Read every gold from rows, retaining stable keys and decisive ids."""

    def __init__(self, kind, fid, extra_span=None, token_fact_id=None):
        super().__init__(template_id=kind, version=1, cell_id="RECALL-VERB", kind="qa", twin_type=TYPES[kind],
                         direction="none", semantics="as_known")
        object.__setattr__(self, "flipper_kind", kind)
        object.__setattr__(self, "fid", fid)
        object.__setattr__(self, "extra_span", extra_span)
        object.__setattr__(self, "token_fact_id", token_fact_id or fid)

    def instances(self, db, schedule):
        f = db.execute("SELECT * FROM fact WHERE id=?", (self.fid,)).fetchone()
        events = tuple(r[0] for r in db.execute("SELECT event_id FROM link WHERE fact_id=? AND role='assert' ORDER BY event_id", (self.fid,)))
        kind = self.flipper_kind
        tokens = (self.token_fact_id,)
        if kind == "value":
            answer = json.loads(f["object"])
        elif kind == "cancel":
            answer = "cancelled" if db.execute("SELECT 1 FROM link WHERE fact_id=? AND role='retract'", (self.fid,)).fetchone() else "active"
        elif kind == "forget":
            requests = [r[0] for r in db.execute("SELECT event_id, covered_fact_ids_json FROM forget_request") if self.fid in json.loads(r[1])]
            answer = "forgotten" if requests else "retained"
            events += tuple(requests)
        elif kind == "correction":
            answer = "corrected" if f["speech_act"] == "assert" else "hedged"
        else:
            carrier = events[0]
            answer = "rejected" if rejection(db, self.fid, carrier) else "genuine"
        if self.extra_span:
            events += (self.extra_span,)
        return (Instance(key="one", probe_point=3, prompt="What is the recorded answer?", decisive_fact_id=self.fid,
                         gold_spans=events, options=(Option(key="gold", token_fact_ids=tokens,
                                                           envelope=dict(type="entity", value=answer)),)),)


def life(path, seed="g13-golden"):
    db, s = base(path, seed)
    ids = {"value": detail(db, s, id="value", subject="alpha", predicate="badge", at=((1, 1), (1, 2), (1, 3), (1, 4))),
           "cancel": commitment(db, s), "forget": forgetting(db, s),
           "correction": chain(db, s, subject="delta"), "source": source(db, s, token=True)}
    finish(db, s)
    return db, s, [QA(kind, fid) for kind, fid in ids.items()]


def run_life(tmp_path, seed="g13-golden"):
    db, s, templates = life(tmp_path / "base.db", seed)
    calls = []

    def expected(db):
        calls.append(world_hash(db))
        return state(db)

    result = twin.twin_life(db, s, iter(templates), world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                            principal_id="principal", expected_state=expected)
    assert calls == [world_hash(db), world_hash(result.b1)]
    return db, s, result


def test_twin_life(tmp_path):
    db, s, result = run_life(tmp_path)
    assert len(result.compiled.bundles) == 5
    records = {r["item_id"]: r for r in result.compiled.records}
    for bundle in result.compiled.bundles:
        assert [records[i]["branch"] for i in bundle["items"]] == ["B0", "B1"]
        assert all(records[i]["decisive_fact_id"] == bundle["decisive_fact_id"] for i in bundle["items"])
    d, prefix = assert_diff(result.cuts, result.flips)
    assert result.differing == d and result.prefix == prefix
    for f in result.flips:
        assert f.events & d == f.events
        if f.kind == "source":
            assert plant(db, f.decisive_fact_id).carrier_event_id in d
    raw = [(tmp_path / "branches" / f"stream.{b}.jsonl").read_bytes().splitlines() for b in ("B0", "B1")]
    assert raw[0][:prefix] == raw[1][:prefix] and raw[0][prefix] != raw[1][prefix]
    manifests = [verify_branch(tmp_path / "branches", b) for b in ("B0", "B1")]
    assert tuple(manifests) == result.manifests
    assert history_set_hash(manifests) == result.history_set_hash
    assert result.cuts[0].exclude_sha256 == result.cuts[1].exclude_sha256 is not None
    validate("world", export_world(result.b1))
    assert_involution(db, result.b1, result.flips, tmp_path / "back.db")
    db.close()
    result.b1.close()


def test_keyed_properties_200(tmp_path):
    for c in range(200):
        seed = f"g13-{c}"
        db, s = base(tmp_path / f"base-{c}.db", seed)
        u = unit(LIFE, "g13-properties", "case")
        count = uniform_int(seed, u, 0, "chains", 1, 3)
        latest = []
        for i in range(count):
            turns = tuple((k, uniform_int(seed, u, 0, f"turn:{i}:{k}", 1, 5)) for k in (1, 2))
            spec = Chain(id=f"chain-{i}", subject=NAMES[i + 1], key="status", stem="VALUE", depth=1, at=turns)
            write_corrections(db, s, [spec], principal="principal")
            latest.append(mint(s, "corrections", spec.id, "fact", "value", 1))
        positions = tuple((uniform_int(seed, u, 0, f"detail-session:{n}", 1, 3),
                           uniform_int(seed, u, 0, f"detail-turn:{n}", 1, 5)) for n in range(4))
        latest.append(detail(db, s, subject="third", at=positions))
        selected = [fid for i, fid in enumerate(latest) if choice(seed, u, 0, f"flip:{i}", (False, True))]
        selected = selected or [latest[0]]
        finish(db, s)
        flips = tuple(flip(db, s, "value", fid, ("value", str(i))) for i, fid in enumerate(selected))
        db1 = twin.apply(db, flips, tmp_path / f"twin-{c}.db")
        assert_swap(db, db1, flips)
        assert_involution(db, db1, flips, tmp_path / f"back-{c}.db")
        assert_diff(cuts(db, db1, s), flips)
        check_tokens(db1)
        db.close()
        db1.close()


def test_determinism_subprocesses():
    script = '''
import json, runpy, tempfile
from pathlib import Path
ns = runpy.run_path("tests/world/test_twin.py")
with tempfile.TemporaryDirectory() as directory:
    db, schedule, result = ns["run_life"](Path(directory))
    print(json.dumps([ns["world_hash"](result.b1),
        *[ns["stream_hash"](c.rows) for c in result.cuts], result.history_set_hash]))
    result.b1.close()
    db.close()
'''
    outputs = [subprocess.check_output([sys.executable, "-c", script], env={"PYTHONHASHSEED": seed})
               for seed in ("0", "random")]
    assert outputs[0] == outputs[1]


def test_purity():
    tree = ast.parse(Path(twin.__file__).read_text())
    forbidden = {"random", "time", "socket", "ssl", "http", "urllib", "subprocess", "bicentennial.sandbox", "bicentennial.director", "spikes"}
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) else []
        assert not any(name and any(name == f or name.startswith(f + ".") for f in forbidden) for name in names)
        assert not (isinstance(node, ast.Constant) and type(node.value) is float)


def copy_rows(db, path, transform):
    """Build malformed but schema-valid inputs without bypassing append-only writers."""
    rows = transform([json.loads(line) for line in export_jsonl(db).splitlines()])
    meta, = [r["row"] for r in rows if r["table"] == "meta"]
    result = writers.create_world(path, meta)
    for table in writers.TABLES[1:]:
        for r in sorted(rows, key=canon):
            if r["table"] == table:
                getattr(writers, f"insert_{table}")(result, **r["row"])
    result.commit()
    return result


@pytest.mark.parametrize("mode", ("evidence", "lineage", "slot", "unrelated"))
def test_independence(tmp_path, mode):
    db, s = base(tmp_path / "base.db")
    if mode == "slot":
        a = commitment(db, s, id="one")
        b = commitment(db, s, id="two")
        cancel_events = [r[0] for r in db.execute("SELECT event_id FROM link WHERE role='retract'")]
        t = db.execute("SELECT t_sim FROM event WHERE id=?", (cancel_events[0],)).fetchone()[0]

        def same_time(rows):
            return [r | {"row": r["row"] | {"t_sim": t}} if r["table"] == "event" and r["row"]["id"] in cancel_events else r for r in rows]

        other = copy_rows(db, tmp_path / "pinned.db", same_time)
        db.close()
        db = other
        templates = [QA("cancel", a), QA("cancel", b)]
        object.__setattr__(templates[1], "template_id", "cancel-other")
    else:
        a = chain(db, s)
        b = detail(db, s)
        eb = db.execute("SELECT event_id FROM link WHERE fact_id=?", (b,)).fetchone()[0]
        if mode == "evidence":
            writers.insert_link(db, event_id=eb, fact_id=a, role="mention")
        if mode == "lineage":
            record(db, artifact_kind="fact", artifact_id=b, sources=(a,))
        templates = [QA("value", a), QA("value", b)]
        object.__setattr__(templates[1], "template_id", "value-other")
    finish(db, s)
    c = cut(db, s, branch="B0", principal_id="principal", expected_state=state(db))
    compiled = compile_branch(db, s, c, templates)
    fs, guards, item_ids = [], {}, {}
    for item, meta in compiled.entries:
        key = meta["template_id"], meta["instance_key"]
        fs.append(flip(db, s, "cancel" if mode == "slot" else "value", meta["decisive_fact_id"], key))
        guards[key] = frozenset(item["gold_spans"]), twin.guard(db, item, meta["decisive_fact_id"])
        item_ids[key] = item["item_id"]
    order = shuffle(s.seed, unit(LIFE, "twin", "order"), 0, "order", sorted(canon(list(f.key)).decode() for f in fs))
    accepted, rejected = twin.independent(db, s, fs, guards)
    if mode == "unrelated":
        assert len(accepted) == 2 and rejected == ()
        result = twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                                principal_id="principal", expected_state=state)
        result.b1.close()
    else:
        expected = tuple(json.loads(order[1]))
        assert rejected == (expected,) and len(accepted) == 1
        with pytest.raises(twin.IndependenceError) as error:
            twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                           principal_id="principal", expected_state=state)
        assert error.value.rejected == (expected,)
        assert str(error.value) == item_ids[expected]
        assert not (tmp_path / "twin.db").exists()
        assert not (tmp_path / "branches").exists()
    db.close()


@pytest.mark.parametrize("case", ("explicit", "commitment", "elsewhere", "payload", "uncancelled", "neither",
                                  "surface", "second-link", "unobservable", "reference"))
def test_plan_refusals(tmp_path, case):
    db, s = base(tmp_path / "base.db")
    if case in ("commitment", "uncancelled", "reference"):
        fid = commitment(db, s, cancelled=case != "uncancelled")
        kind = "value" if case == "commitment" else "cancel"
    elif case == "unobservable":
        fid, kind = source(db, s, authority=False), "source"
    else:
        fields = dict(values=("literal-alpha", "literal-beta")) if case == "explicit" else {}
        fid = chain(db, s, **fields)
        kind = "correction" if case in ("surface", "second-link", "neither") else "value"
        if case == "neither":
            fid = mint(s, "corrections", "chain", "fact", "value", 0)
    if case == "elsewhere":
        value = db.execute("SELECT value FROM locked_token WHERE fact_id=?", (fid,)).fetchone()[0]
        writers.insert_entity(db, id="leak", canonical_name=value, kind="person", aliases_json=[], created_t=0, retired_t=None)
    if case in ("payload", "second-link", "reference"):
        write_event(db, "extra", ev(slot(s, 3, 3)), ("chat",))
        target = mint(s, "commitments", "duty", "fact", "cancel", 0) if case == "reference" else fid
        writers.insert_link(db, event_id="extra", fact_id=target, role="mention")
    if case == "payload":
        def payload(rows):
            return [r | {"row": r["row"] | {"payload_json": {"note": "nonempty"}}}
                    if r["table"] == "event" and r["row"]["id"] == "extra" else r for r in rows]
        other = copy_rows(db, tmp_path / "payload.db", payload)
        db.close()
        db = other
    if case == "surface":
        writers.insert_fact_surface(db, fact_id=fid, surface="notes", from_t=slot(s, 2, 2))
    finish(db, s)
    before = export_jsonl(db)
    with pytest.raises(ValueError) as error:
        flip(db, s, kind, fid)
    assert str(error.value) == fid
    assert export_jsonl(db) == before
    db.close()


@pytest.mark.parametrize("case", ("token", "outside", "other-event"))
def test_forget_refusals(tmp_path, case):
    db, s = base(tmp_path / "base.db")
    fid = forgetting(db, s)
    event = db.execute("SELECT event_id FROM forget_request").fetchone()[0]
    fr = forget_request(db, event)
    if case == "token":
        writers.insert_locked_token(db, token_id="bad-token", fact_id=fr.request_fact_ids[0], kind="code", value="MARKER-123456")
    elif case == "outside":
        writers.insert_link(db, event_id=event, fact_id=fr.neighbours[0], role="mention")
    else:
        write_event(db, "extra", ev(slot(s, 3, 5)), ("chat",))
        writers.insert_link(db, event_id="extra", fact_id=fr.request_fact_ids[0], role="mention")
    with pytest.raises(ValueError, match=fid):
        flip(db, s, "forget", fid)
    db.close()


def test_forget_removes_marker(tmp_path):
    db, s = base(tmp_path / "base.db")
    fid = forgetting(db, s)
    event = db.execute("SELECT event_id FROM forget_request").fetchone()[0]
    fr = forget_request(db, event)
    writers.insert_fact_surface(db, fact_id=fr.marker_fact_id, surface="notes", from_t=slot(s, 3, 4))
    finish(db, s)
    verify(db)
    f = flip(db, s, "forget", fid)
    db1 = twin.apply(db, (f,), tmp_path / "twin.db")
    assert not db1.execute("SELECT 1 FROM fact WHERE predicate='forget_ref'").fetchall()
    assert not db1.execute("SELECT 1 FROM locked_token WHERE value LIKE 'REQ-%'").fetchall()
    assert not db1.execute("SELECT 1 FROM fact_surface WHERE fact_id=?", (fr.marker_fact_id,)).fetchall()
    assert not db1.execute("SELECT 1 FROM link WHERE event_id=?", (event,)).fetchall()
    verify(db1)
    assert_swap(db, db1, (f,))
    assert_involution(db, db1, (f,), tmp_path / "back.db")
    db1.close()
    db.close()


def test_value_refuses_forget_marker(tmp_path):
    db, s = base(tmp_path / "base.db")
    forgetting(db, s)
    event = db.execute("SELECT event_id FROM forget_request").fetchone()[0]
    marker = forget_request(db, event).marker_fact_id
    finish(db, s)
    with pytest.raises(ValueError, match=marker):
        flip(db, s, "value", marker)
    db.close()


@pytest.mark.parametrize("stems", (("VALUE", "VALUE"), ("VALUE", "OTHER")))
def test_value_alternate_collision_rejects_later_key(tmp_path, monkeypatch, stems):
    db, s = base(tmp_path / "base.db")
    templates = []
    for i, stem in enumerate(stems):
        spec = Chain(id=f"chain-{i}", subject=NAMES[i + 1], key="status", stem=stem,
                     depth=1, at=((1, i + 1), (2, i + 1)))
        write_corrections(db, s, [spec], principal="principal")
        template = QA("value", mint(s, "corrections", spec.id, "fact", "value", 1))
        object.__setattr__(template, "template_id", f"value-{i}")
        templates.append(template)
    finish(db, s)
    taken = {v.rsplit("-", 1)[1] for (v,) in db.execute("SELECT value FROM locked_token")}
    number = next(str(n) for n in range(100000, 999999) if str(n) not in taken)
    monkeypatch.setattr(twin, "token_value", lambda *args: f"{args[6]}-{number}")
    c = cut(db, s, branch="B0", principal_id="principal", expected_state=state(db))
    compiled = compile_branch(db, s, c, templates)
    ids = {(meta["template_id"], meta["instance_key"]): item["item_id"] for item, meta in compiled.entries}
    order = shuffle(s.seed, unit(LIFE, "twin", "order"), 0, "order",
                    sorted(canon(list(key)).decode() for key in ids))
    expected = tuple(json.loads(order[1]))
    with pytest.raises(twin.IndependenceError) as error:
        twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                       principal_id="principal", expected_state=state)
    assert error.value.rejected == (expected,)
    assert str(error.value) == ids[expected]
    assert not (tmp_path / "twin.db").exists()
    assert not (tmp_path / "branches").exists()
    db.close()


def test_apply_refusals_and_cleanup(tmp_path):
    db, s = base(tmp_path / "base.db")
    fid = chain(db, s)
    finish(db, s)
    f = flip(db, s, "value", fid)
    path = tmp_path / "twin.db"
    path.write_bytes(b"existing")
    with pytest.raises(ValueError):
        twin.apply(db, (f,), path)
    assert path.read_bytes() == b"existing"
    path.unlink()
    # The wrong side contains an existing row: neither direction is wholly present.
    mixed = replace(f, into=(*f.into, f.out[0]))
    with pytest.raises(ValueError):
        twin.apply(db, (mixed,), path)
    with pytest.raises(ValueError):
        twin.apply(db, (f, f), path)
    assert not path.exists()
    # Forward direction is valid, but writing an unknown actor violates a foreign key.
    event = dict(db.execute("SELECT * FROM event ORDER BY id LIMIT 1").fetchone())
    for column in ("audience_json", "payload_json"):
        event[column] = json.loads(event[column])
    bad = replace(f, out=(canon(dict(table="event", row=event)),),
                  into=(canon(dict(table="event", row=event | {"actor_id": "missing"})),))
    with pytest.raises(ValueError):
        twin.apply(db, (bad,), path)
    assert not path.exists()
    db.close()


@pytest.mark.parametrize("stage", ("state", "compile", "diff", "write", "verify", "history"))
def test_life_failure_cleanup(tmp_path, monkeypatch, stage):
    db, s, templates = life(tmp_path / "base.db")
    expected = state
    fired = False

    def fail(*args, **kwargs):
        nonlocal fired
        fired = True
        raise ValueError("injected")

    if stage == "state":
        def expected(connection):
            if connection is not db:
                fail()
            return state(connection)
    elif stage == "compile":
        monkeypatch.setattr(twin, "compile_life", fail)
    elif stage == "diff":
        original = twin.apply

        def missing_event(*args):
            nonlocal fired
            connection = original(*args)
            # Return a real world with valid rows, but make every planned event footprint empty.
            fired = True
            return connection

        monkeypatch.setattr(twin, "apply", missing_event)
        original_plan = twin.plan
        monkeypatch.setattr(twin, "plan", lambda *a, **kw: tuple(replace(f, events=frozenset()) for f in original_plan(*a, **kw)))
    elif stage == "write":
        original_write = twin.write_branch

        def partial(directory, c):
            if c.branch == "B1":
                fail()
            return original_write(directory, c)

        monkeypatch.setattr(twin, "write_branch", partial)
    else:
        monkeypatch.setattr(twin, "verify_branch" if stage == "verify" else "history_set_hash", fail)
    with pytest.raises(ValueError) as error:
        twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                       principal_id="principal", expected_state=expected)
    assert fired
    assert str(error.value) == ("event footprint mismatch" if stage == "diff" else "injected")
    assert not (tmp_path / "twin.db").exists()
    assert not list((tmp_path / "branches").glob("*"))
    db.close()


@pytest.mark.parametrize("trigger", ("event", "cue"))
def test_non_time_cancel_structure(tmp_path, trigger):
    db, s = base(tmp_path / "base.db")
    fid = commitment(db, s, trigger=trigger)
    finish(db, s)
    f = flip(db, s, "cancel", fid)
    db1 = twin.apply(db, (f,), tmp_path / "twin.db")
    cs = cuts(db, db1, s)
    assert_diff(cs, (f,))
    assert all(len(stream_hash(c.rows)) == 64 for c in cs)
    made = mint(s, "commitments", "duty", "event", "made", 0)
    assert made not in f.events
    assert next(r for r in cs[0].rows if r["event_id"] == made) == next(r for r in cs[1].rows if r["event_id"] == made)
    assert_involution(db, db1, (f,), tmp_path / "back.db")
    db1.close()
    db.close()


@pytest.mark.parametrize("stage", ("flip", "plan", "publish"))
def test_source_refuses_payload_backed_evidence(tmp_path, stage):
    db, s = base(tmp_path / "base.db")
    token_fact_id = detail(db, s)
    fid = source(db, s, evidence=True, tool_evidence=True)
    finish(db, s)
    before = export_jsonl(db)
    p = plant(db, fid)
    assert p.twin.evidence_fact_id == "evidence-fact"
    assert p.rejection.basis == "verification"
    c = cut(db, s, branch="B0", principal_id="principal", expected_state=state(db))
    tool_row = next(r for r in c.rows if r["event_id"] == "evidence-event")
    assert tool_row["payload"] == {"approval": "declined"}
    templates = [QA("source", fid, token_fact_id=token_fact_id)]
    compiled = compile_branch(db, s, c, templates)
    if stage == "flip":
        with pytest.raises(ValueError) as error:
            flip(db, s, "source", fid)
        assert str(error.value) == fid
    else:
        with pytest.raises(twin.IndependenceError) as error:
            if stage == "plan":
                twin.plan(db, s, compiled, principal_id="principal")
            else:
                twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                               principal_id="principal", expected_state=state)
        assert error.value.rejected == (("source", "one"),)
        assert str(error.value) == compiled.entries[0][0]["item_id"]
    assert export_jsonl(db) == before
    assert not (tmp_path / "twin.db").exists()
    assert not (tmp_path / "branches").exists()
    db.close()


@pytest.mark.parametrize("stage", ("flip", "plan", "publish"))
def test_source_refuses_attribute_backed_evidence(tmp_path, stage):
    db, s = base(tmp_path / "base.db")
    token_fact_id = detail(db, s)
    fid = source(db, s, evidence=True)
    t = slot(s, 1, 5)
    writers.insert_attr(db, entity_id="epsilon", key="approval", value="declined", valid_from_t=t,
                        valid_to_t=None, recorded_t=t, source_event_id="evidence-event")
    finish(db, s)
    before = export_jsonl(db)
    p = plant(db, fid)
    assert p.twin.evidence_fact_id == "evidence-fact"
    assert p.rejection.basis == "contradiction"
    assert as_known(db, "epsilon", "approval", t) == as_valid(db, "epsilon", "approval", t) == "declined"
    c = cut(db, s, branch="B0", principal_id="principal", expected_state=state(db))
    templates = [QA("source", fid, token_fact_id=token_fact_id)]
    compiled = compile_branch(db, s, c, templates)
    if stage == "flip":
        with pytest.raises(ValueError) as error:
            flip(db, s, "source", fid)
        assert str(error.value) == fid
    else:
        with pytest.raises(twin.IndependenceError) as error:
            if stage == "plan":
                twin.plan(db, s, compiled, principal_id="principal")
            else:
                twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                               principal_id="principal", expected_state=state)
        assert error.value.rejected == (("source", "one"),)
        assert str(error.value) == compiled.entries[0][0]["item_id"]
    assert export_jsonl(db) == before
    assert not (tmp_path / "twin.db").exists()
    assert not (tmp_path / "branches").exists()
    db.close()


def test_source_evidence_swap(tmp_path):
    db, s = base(tmp_path / "base.db")
    fid = source(db, s, evidence=True)
    finish(db, s)
    f = flip(db, s, "source", fid)
    db1 = twin.apply(db, (f,), tmp_path / "twin.db")
    assert "evidence-fact" in f.facts and "evidence-event" in f.events
    assert json.loads(db1.execute("SELECT object FROM fact WHERE id='evidence-fact'").fetchone()[0]) == "accepted"
    assert rejection(db1, fid, plant(db, fid).carrier_event_id) is None
    assert_swap(db, db1, (f,))
    assert_diff(cuts(db, db1, s), (f,))
    assert_involution(db, db1, (f,), tmp_path / "back.db")
    db1.close()
    db.close()


def test_value_retries_substring_clash(tmp_path, monkeypatch):
    db, s = base(tmp_path / "base.db")
    fid = chain(db, s)
    first = token_value(db, s, "twin", fid, "value", 0, "VALUE")
    short = first[-4:]
    assert all(short not in r[0] for r in db.execute("SELECT value FROM locked_token"))
    writers.insert_fact(db, id="short-fact", subject_id="zeta", predicate="code", object=short,
                        polarity="affirm", modality="stated", strength=1000, speech_act="assert")
    writers.insert_locked_token(db, token_id="short-token", fact_id="short-fact", kind="code", value=short)
    finish(db, s)
    calls = []
    original = twin.token_value

    def observed(*args):
        calls.append(args[5])
        return original(*args)

    monkeypatch.setattr(twin, "token_value", observed)
    f = flip(db, s, "value", fid)
    assert calls[0] == 0 and len(calls) > 1
    db1 = twin.apply(db, (f,), tmp_path / "twin.db")
    check_tokens(db1)
    db1.close()
    monkeypatch.setattr(twin, "token_value", lambda *args: first)
    with pytest.raises(ValueError, match=fid):
        flip(db, s, "value", fid)
    db.close()


def test_guard_transitive_lineage(tmp_path):
    db, s = base(tmp_path / "base.db")
    fid = chain(db, s)
    for i in range(4):
        write_event(db, f"event-{i}", ev(slot(s, 3, i + 1)), ("chat",))
        write_fact(db, f"fact-{i}", f"event-{i}", subject_id="gamma", predicate="memo", object="recorded")
    record(db, artifact_kind="fact", artifact_id="fact-0", sources=(fid,))
    record(db, artifact_kind="fact", artifact_id="fact-1", sources=("fact-0",))
    record(db, artifact_kind="fact", artifact_id="fact-2", sources=("fact-1",))
    record(db, artifact_kind="event", artifact_id="event-3", sources=("fact-1",))
    evidence = twin.guard(db, {"gold_spans": ["event-3"]}, "fact-3")
    assert {fid, "fact-0", "fact-1", "fact-3"} <= evidence
    assert "fact-2" in twin.guard(db, {"gold_spans": []}, fid)
    db.close()


@pytest.mark.parametrize("which", ("world", "branch"))
def test_existing_life_outputs_preserved(tmp_path, which):
    db, s, templates = life(tmp_path / "base.db")
    world, directory = tmp_path / "twin.db", tmp_path / "branches"
    if which == "world":
        existing = world
    else:
        directory.mkdir()
        existing = directory / "stream.B1.jsonl"
    existing.write_bytes(b"existing")
    with pytest.raises(ValueError):
        twin.twin_life(db, s, templates, world_path=world, out_dir=directory, principal_id="principal", expected_state=state)
    assert existing.read_bytes() == b"existing"
    db.close()


def test_second_branch_guard_rejection_cleans_world(tmp_path, monkeypatch):
    db, s, templates = life(tmp_path / "base.db")
    original = twin.guard
    decisive = frozenset(t.fid for t in templates)

    def guarded(connection, item, fid):
        return original(connection, item, fid) | (decisive if connection is not db else frozenset())

    monkeypatch.setattr(twin, "guard", guarded)
    with pytest.raises(twin.IndependenceError) as error:
        twin.twin_life(db, s, templates, world_path=tmp_path / "twin.db", out_dir=tmp_path / "branches",
                       principal_id="principal", expected_state=state)
    assert len(error.value.rejected) == 4
    assert not (tmp_path / "twin.db").exists()
    assert not (tmp_path / "branches").exists()
    db.close()


@pytest.mark.parametrize("surfaced", (False, True))
def test_forget_correction_dispatch(tmp_path, surfaced):
    db, s = base(tmp_path / "base.db")
    fid = chain(db, s)
    prior = mint(s, "corrections", "chain", "fact", "value", 0)
    correction_event = mint(s, "corrections", "chain", "event", "event", 1)
    record(db, artifact_kind="event", artifact_id=correction_event, sources=(prior,))
    detail(db, s, subject="alpha", predicate="badge")
    if surfaced:
        writers.insert_fact_surface(db, fact_id=fid, surface="notes", from_t=slot(s, 2, 2))
    request_forget(db, life=LIFE, key="forget", event=ev(slot(s, 3, 4)), subject_id="alpha", predicates=("status",))
    finish(db, s)
    if surfaced:
        # A surfaced correction fails the full correction pattern, so only forget matches.
        assert flip(db, s, "forget", fid).kind == "forget"
    else:
        with pytest.raises(ValueError, match=fid):
            flip(db, s, "forget", fid)
    db.close()
