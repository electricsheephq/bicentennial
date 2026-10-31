"""Full fixture builds, hosting boundaries and publication failures."""

import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.controls.cache import CONTROL_FILES
from bicentennial.items.bindings import Binding
from bicentennial.render.stream import stream_hash
from bicentennial.world import fixtureplan as fp
from bicentennial.world import fulltwin as full
from bicentennial.world import planned
from bicentennial.world.processes import mint

ROOT = Path(__file__).resolve().parents[2]
SLOW_BUILD = False


def budget(genre, n=1):
    registry = full.G1 if genre == "G1" else full.G2
    return [[cell, k, n] for cell in sorted({t.cell_id for t in registry})
            for k in full.named("full").checkpoints if fp.eligible(genre, cell, k)]


@pytest.mark.parametrize("budget", [None, (), {}, [None], [[]], [["DRIFT-CUR", 20]],
    [["DRIFT-CUR", 20, 1, 2]], [["absent", 20, 1]], [["RACH-PLANT", 20, 1]],
    [["DRIFT-CUR", 21, 1]], [["DRIFT-CUR", True, 1]], [["DRIFT-CUR", "20", 1]],
    [["DRIFT-CUR", 20, 0]], [["DRIFT-CUR", 20, -1]], [["DRIFT-CUR", 20, True]],
    [["DRIFT-CUR", 20, "1"]], [["DRIFT-CUR", 20, 1], ["DRIFT-CUR", 20, 2]],
])
def test_budget_shape_before_world(budget, monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        pytest.fail("world must not be created for an invalid budget")

    monkeypatch.setattr(full, "_world", forbidden)
    with pytest.raises(ValueError, match="^budget:shape$"):
        full.build("G1", "test", 1, budget, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_failed_world_leaves_no_world(monkeypatch, tmp_path):
    def broken(db, schedule):
        raise RuntimeError("synthetic")

    def mismatched(path, **kwargs):
        Path(path).open("xb").close()
        return SimpleNamespace(db=SimpleNamespace(close=lambda: None), people=SimpleNamespace(principal="p"),
                               schedule=SimpleNamespace(to_json=lambda: None))

    monkeypatch.setattr(full, "build_g1", broken)
    monkeypatch.setattr(full, "build_base", mismatched)
    with pytest.raises(RuntimeError, match="^synthetic$"):
        full._world("G1", "full-g1", 1, tmp_path)
    assert not (tmp_path / "world.B0.db").exists()
    with pytest.raises(ValueError, match="^composition$"):
        full._world("G2", "full-g2", 2, tmp_path)
    assert not (tmp_path / "world.B0.db").exists()
    def failing(path, **kwargs):
        Path(path).open("xb").close()
        raise RuntimeError("synthetic writer failure")

    monkeypatch.setattr(full, "build_base", failing)
    with pytest.raises(RuntimeError, match="^synthetic writer failure$"):
        full._world("G2", "full-g2", 2, tmp_path)
    assert not (tmp_path / "world.B0.db").exists()
    (tmp_path / "world.B0.db").write_bytes(b"kept")
    for genre, life, seed in (("G1", "full-g1", 1), ("G2", "full-g2", 2)):
        with pytest.raises(FileExistsError):
            full._world(genre, life, seed, tmp_path)
        assert (tmp_path / "world.B0.db").read_bytes() == b"kept"


@pytest.fixture(scope="module", params=[("G1", 1), ("G2", 2)])
def measured(request, tmp_path_factory):
    global SLOW_BUILD
    if SLOW_BUILD and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("an earlier measured full build exceeded 90 seconds")
    genre, seed = request.param
    life = f"planned-{genre}"
    root = tmp_path_factory.mktemp(genre)
    hosting = []
    original = full.host
    def timed_host(*args):
        started = monotonic()
        result = original(*args)
        hosting.append(monotonic() - started)
        return result
    started = monotonic()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(full, "host", timed_host)
        result = full.build(genre, life, seed, budget(genre), root / "out")
    elapsed = monotonic() - started
    SLOW_BUILD = SLOW_BUILD or elapsed > 90
    p = json.loads((root / "out/plan.json").read_bytes())
    facts = dict(genre=genre, seed=seed, life=life, seconds=elapsed, hosting_seconds=hosting[0],
                 sizes={p.name: p.stat().st_size for p in sorted((root / "out/branches").iterdir())},
                 plan=p)
    yield result, facts, root
    result.twin.b1.close()


def slow(facts):
    if facts["seconds"] > 90 and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("measured full build exceeded 90 seconds")


def test_full_scale(measured, capsys):
    result, facts, root = measured
    with capsys.disabled():
        print("\nPLANNED_FULL " + json.dumps(facts | {"plan": {
            k: facts["plan"][k] for k in ("fork", "histogram", "names", "prompt_distinctness", "written")}},
            sort_keys=True), flush=True)
    slow(facts)
    p = facts["plan"]
    assert Counter((i["cell_id"], i["probe_point"]) for i in result.twin.compiled.items) == {
        (c, k): 2 * n for c, k, n in budget(facts["genre"])}
    assert len(result.bindings) == len(p["fixtures"])
    assert len({f["key"] for f in p["fixtures"]}) == len(p["fixtures"])
    records = [r for r in result.twin.compiled.records if r["branch"] == "B0"]
    assert len({r["decisive_fact_id"] for r in records}) == len(records)
    assert len(result.twin.flips) == sum(r["twin_type"] is not None for r in records)
    s = full.build_schedule(full.seed_text(facts["seed"]), facts["life"], full.named("full"))
    indices = {v.session_id: v.index for v in s.sessions}
    assert indices[result.twin.cuts[0].rows[result.twin.prefix]["session_id"]] == p["fork"] <= 20
    assert len(s.sessions) == 200
    assert s.scale.checkpoints == (20, 60, 120, 200)
    assert s.scale.kill == 110 and s.scale.swap == 150
    templates = {t.template_id: t for t in (*full.G1, *full.G2)}
    checkpoints = {b.checkpoint for b in result.bindings}
    assert set(result.prompts) == {(branch, k) for k in checkpoints for branch in ("B0", "B1")}
    assert checkpoints == {k for _, k, _ in budget(facts["genre"])}
    for branch in ("B0", "B1"):
        branch_records = [r for r in result.twin.compiled.records if r["branch"] == branch]
        assert len(branch_records) == len(result.bindings)
        for b in result.bindings:
            assert templates[b.template_id].checkpoint is None
            bound = replace(templates[b.template_id], **dict(b.fields), checkpoint=b.checkpoint)
            instance, = bound.instances(result.twin.b1, s)
            assert len([r for r in branch_records if r["template_id"] == b.template_id
                        and r["instance_key"] == instance.key]) == 1
        ids = {r["item_id"] for r in branch_records}
        for checkpoint in checkpoints:
            assert result.prompts[branch, checkpoint] == tuple(i["prompt"] for i in result.twin.compiled.items
                                                              if i["item_id"] in ids and i["probe_point"] == checkpoint)
    cells = {r["item_id"]: next(i["cell_id"] for i in result.twin.compiled.items if i["item_id"] == r["item_id"])
             for r in records}
    actual = {}
    record_ids = {r["item_id"] for r in records}
    for i in result.twin.compiled.items:
        if i["item_id"] in record_ids:
            actual.setdefault((cells[i["item_id"]], i["probe_point"]), set()).add(i["prompt"])
    distinct = [[c, k, len(v)] for (c, k), v in sorted(actual.items())]
    assert p["prompt_distinctness"] == distinct
    for name in ("bindings.json", "plan.json"):
        raw = (root / "out" / name).read_bytes()
        assert raw == canon(json.loads(raw)) + b"\n"
    assert all(type(v) is int for share in p["written"]["probed"].values() for v in share)


def test_capacity(measured, capsys):
    _, facts, root = measured
    counts = full.capacity(facts["genre"], facts["life"], facts["seed"], root / "diagnostic")
    assert counts == full.capacity(facts["genre"], facts["life"], facts["seed"], root / "diagnostic")
    assert list((root / "diagnostic").iterdir()) == []
    assert all(counts["TUE-EVENT", k] == 0 for k in full.named("full").checkpoints)
    for seed in (1, 2):
        rows = full.survey(facts["genre"], facts["life"], seed, root / "diagnostic")
        unavailable = sorted({(c.template.template_id, c.fixture) for c, _, _ in rows
                              if all(refusal is not None for other, _, refusal in rows if other == c)})
        with capsys.disabled():
            print("SURVEY", facts["genre"], seed, json.dumps(unavailable))
        expected = {
            ("drift-chain-fault", ("chain", key)) for key in ("constraint-0", "deadline-0", "deadline-1")
        } | {(t, ("chain", key)) for t in ("drift-config", "drift-quote") for key in ("constant-0", "constant-1")
        } | {("tue-ticket", ("commitment", key)) for key in ("commitment-0", "commitment-1")}
        if facts["genre"] == "G1":
            expected |= {("drift-chain", ("chain", key)) for key in (
                ("deadline-0", "deadline-1") if seed == 1 else ("constraint-0",))}
        else:
            expected = {("keep-neighbour", ("forget", "ex")), ("tue-passport", ("commitment", "passport"))}
        assert set(unavailable) == expected


def fake_build(monkeypatch):
    original = fp.plan
    state = {}
    def plan(*args):
        p = original(*args)
        state["fork"] = p.fork
        return p
    monkeypatch.setattr(fp, "plan", plan)
    db = SimpleNamespace(close=lambda: None)
    def world(genre, life, seed, directory):
        (Path(directory) / "reserved").write_text("synthetic")
        return db, None, "principal"
    monkeypatch.setattr(full, "_world", world)
    monkeypatch.setattr(planned, "write_extra", lambda *a: {})
    monkeypatch.setattr(planned, "rebuild", lambda *a: db)
    monkeypatch.setattr(full, "host", lambda *a: None)
    def twin(db, s, *a, **kw):
        row = dict(session_id=s.sessions[state["fork"] - 1].session_id)
        return full.TwinLife((), db, (SimpleNamespace(rows=(row,)),), (), "",
                             SimpleNamespace(records=(), items=()), frozenset(), 0)
    monkeypatch.setattr(full, "twin_life", twin)
    monkeypatch.setattr(full, "open_world", lambda path: db)


@pytest.mark.parametrize("step", ("world", "rebuild", "host", "twin", "bindings", "plan", "rename"))
def test_staging(monkeypatch, tmp_path, step):
    fake_build(monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError("injected")
    target, attr = {"world": (full, "_world"), "rebuild": (planned, "rebuild"),
                    "host": (full, "host"), "twin": (full, "twin_life"),
                    "rename": (full.os, "rename")}.get(step, (None, None))
    if target is not None:
        monkeypatch.setattr(target, attr, fail)
    else:
        original = Path.write_bytes
        def write(path, value):
            if path.name == ("bindings.json" if step == "bindings" else "plan.json"):
                fail()
            return original(path, value)
        monkeypatch.setattr(Path, "write_bytes", write)
    before = list(tmp_path.iterdir())
    with pytest.raises(RuntimeError, match="^injected$"):
        full.build("G1", "staging", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "out")
    assert list(tmp_path.iterdir()) == before
    assert not (tmp_path / "out").exists()


def test_missing_parent_cleanup(monkeypatch, tmp_path):
    fake_build(monkeypatch)
    def fail(*args, **kwargs):
        raise RuntimeError("injected")
    monkeypatch.setattr(full, "host", fail)
    with pytest.raises(RuntimeError, match="injected"):
        full.build("G1", "staging", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "missing" / "nested" / "out")
    assert list(tmp_path.iterdir()) == []


def test_fork_mismatch(monkeypatch, tmp_path):
    fake_build(monkeypatch)
    original = fp.plan
    monkeypatch.setattr(fp, "plan", lambda *args: replace(original(*args), fork=19))
    with pytest.raises(ValueError, match="^plan:fork_mismatch$"):
        full.build("G1", "staging", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "out")
    assert list(tmp_path.iterdir()) == []


def test_output_exists(tmp_path):
    (tmp_path / "existing").write_bytes(b"kept")
    with pytest.raises(ValueError, match="^out:exists$"):
        full.build("G1", "existing", 1, [["DRIFT-CUR", 20, 1]], tmp_path)
    assert (tmp_path / "existing").read_bytes() == b"kept"


@pytest.mark.parametrize("twin_type", ("fork", "trigger"))
@pytest.mark.parametrize("distance", (1, 2))
def test_hostability_boundary(monkeypatch, distance, twin_type):
    t = replace(full.G1[0], twin_type=twin_type)
    binding = Binding(t.template_id, (("chain_id", "synthetic"), ("depth", 1)), 20)
    p = SimpleNamespace(bindings=(binding,))
    s = full.build_schedule("1", "hosting", full.named("full"))
    event = "evidence"
    pre = SimpleNamespace(rows=(dict(event_id=event, session_id=s.sessions[20 - distance - 1].session_id,
                                     kind="statement", fact_ids=["fact"], turn_key="turn"),))
    monkeypatch.setattr(full, "cut", lambda *a, **k: pre)
    monkeypatch.setattr(full, "expected_state", lambda *a: lambda db: {})
    monkeypatch.setattr(type(t), "instances", lambda *a: (SimpleNamespace(key="key"),))
    compiled = SimpleNamespace(entries=((dict(gold_spans=[event]),
                                         dict(template_id=t.template_id, instance_key="key")),))
    monkeypatch.setattr(full, "compile_bound", lambda *a: compiled)
    if distance == 1:
        with pytest.raises(ValueError, match="^plan:distance:DRIFT-CUR@20:drift-chain$"):
            full.host(None, s, None, "G1", p, (t,))
    else:
        assert full.host(None, s, None, "G1", p, (t,)) is compiled


@pytest.mark.parametrize("distance", (1, 2))
def test_tue_boundary(monkeypatch, distance):
    t = next(t for t in full.G1 if t.template_id == "tue-ticket")
    s = full.build_schedule("1", "hosting", full.named("full"))
    b = Binding(t.template_id, (("commitment_id", "synthetic"),), 20)
    cue = mint(s, "commitments", "synthetic", "event", "trigger", 0)
    cancel = mint(s, "commitments", "synthetic", "event", "cancel", 0)
    pre = SimpleNamespace(rows=tuple(dict(event_id=e, session_id=s.sessions[k - 1].session_id,
        kind="statement", fact_ids=["fact"], turn_key=e) for e, k in (("made", 1), (cancel, 20 - distance), (cue, 20))))
    monkeypatch.setattr(full, "cut", lambda *a, **k: pre)
    monkeypatch.setattr(full, "expected_state", lambda *a: lambda db: {})
    monkeypatch.setattr(type(t), "instances", lambda *a: (SimpleNamespace(key="key"),))
    compiled = SimpleNamespace(entries=((dict(gold_spans=["made", cancel, cue]),
                                         dict(template_id=t.template_id, instance_key="key")),))
    monkeypatch.setattr(full, "compile_bound", lambda *a: compiled)
    if distance == 1:
        with pytest.raises(ValueError, match="^plan:distance:TUE-EVENT@20:tue-ticket$"):
            full.host(None, s, None, "G1", SimpleNamespace(bindings=(b,)), (t,))
    else:
        assert full.host(None, s, None, "G1", SimpleNamespace(bindings=(b,)), (t,)) is compiled


def test_refusal_versus_integrity(monkeypatch, tmp_path):
    db, s, principal = full._world("G1", "integrity", 1, tmp_path)
    t = full.G1[0]
    p = fp.plan("G1", s, [["DRIFT-CUR", 20, 1]], (t,))
    planned.write_extra("G1", db, s, p, principal)
    clean = planned.rebuild(db, tmp_path / "clean.db")
    original = type(t).instances
    def refused(*args):
        raise ValueError("synthetic")
    monkeypatch.setattr(type(t), "instances", refused)
    with pytest.raises(ValueError, match="^plan:unhostable:DRIFT-CUR@20:drift-chain:synthetic$"):
        full.host(clean, s, principal, "G1", p, (t,))
    def corrupt(self, db, schedule):
        instance, = original(self, db, schedule)
        foreign = clean.execute("SELECT value FROM locked_token WHERE fact_id!=? ORDER BY token_id",
                                (instance.decisive_fact_id,)).fetchone()[0]
        options = list(instance.options)
        option = options[-1]
        options[-1] = replace(option, plan={"steps": [{"tool": {"name": "set_entry", "args": {
            "path": "docs/decisions.md", "name": "synthetic", "value": foreign}}}]})
        return (replace(instance, options=tuple(options)),)
    monkeypatch.setattr(type(t), "instances", corrupt)
    with pytest.raises(ValueError, match="^foreign token in option:"):
        full.host(clean, s, principal, "G1", p, (t,))
    clean.close()
    db.close()


def test_pin():
    assert not {f"world/{name}.py" for name in ("fixtureplan", "planned", "fulltwin", "twin")} & set(CONTROL_FILES)
    assert "items/bindings.py" not in CONTROL_FILES


def test_determinism(measured, tmp_path):
    result, facts, root = measured
    slow(facts)
    script = """
import json, sys
from pathlib import Path
from bicentennial.world.fulltwin import build
from bicentennial.render.stream import stream_hash
p = Path(sys.argv[5])
r = build(sys.argv[1], sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4]), p)
print(json.dumps([[stream_hash(c.rows) for c in r.twin.cuts],
    *[(p / n).read_text() for n in ("bindings.json", "plan.json")]]))
r.twin.b1.close()
"""
    expected = [[stream_hash(c.rows) for c in result.twin.cuts],
                *[(root / "out" / n).read_text() for n in ("bindings.json", "plan.json")]]
    for j, seed in enumerate(("0", "random")):
        run = subprocess.run([sys.executable, "-c", script, facts["genre"], facts["life"],
            str(facts["seed"]), json.dumps(budget(facts["genre"])), str(tmp_path / str(j))],
            cwd=ROOT, env=os.environ | {"PYTHONHASHSEED": seed}, capture_output=True, check=True)
        assert json.loads(run.stdout) == expected


def test_reads(measured, tmp_path):
    _, facts, _ = measured
    slow(facts)
    if facts["genre"] != "G1":
        return
    script = """
import json, sys
from pathlib import Path
root = Path.cwd().resolve()
seen = set()
def audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes)):
        p = Path(args[0]).resolve()
        if p.is_relative_to(root):
            seen.add(p.relative_to(root).as_posix())
sys.addaudithook(audit)
from bicentennial.world.fulltwin import build
r = build("G1", "reads", 1, json.loads(sys.argv[2]), Path(sys.argv[1]))
r.twin.b1.close()
print(json.dumps(sorted(seen)))
"""
    run = subprocess.run([sys.executable, "-c", script, str(tmp_path / "out"), json.dumps(budget("G1"))],
                         cwd=ROOT, env=os.environ | {"PYTHONHASHSEED": "0"}, capture_output=True, check=True)
    paths = json.loads(run.stdout)
    assert paths
    assert all(any(p.startswith(root + "/") for root in ("src/bicentennial", "tiers", "specs/ring0", "schemas"))
               for p in paths)
