"""Never-skipped selection contracts and measured default-fixture full lives."""

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from time import monotonic
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.render.stream import stream_hash
from bicentennial.world import fulltwin as full

ROOT = Path(__file__).resolve().parents[2]
SLOW_BUILD = False


def candidate(template="a", fixture="one", cell="DRIFT-CUR", kind="statement"):
    return full.Candidate(SimpleNamespace(template_id=template, cell_id=cell),
                          (("fixture", fixture),), (kind, fixture))


def stub(binding, *, distance=2):
    return SimpleNamespace(entries=((dict(probe_point=binding.checkpoint),
        dict(evidence_session=binding.checkpoint - distance)),))


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
        full.select(budget, [candidate()], stub)
    with pytest.raises(ValueError, match="^budget:shape$"):
        full.build("G1", "test", 1, budget, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_hostability_boundary():
    table = [candidate()]
    with pytest.raises(ValueError, match="^budget:DRIFT-CUR@20:0/1$"):
        full.select([["DRIFT-CUR", 20, 1]], table, lambda b: stub(b, distance=1))
    assert len(full.select([["DRIFT-CUR", 20, 1]], table, stub)) == 1
    with pytest.raises(ValueError, match="0/1"):
        full.select([["DRIFT-CUR", 20, 1]], table,
                    lambda b: SimpleNamespace(entries=(({}, {"evidence_session": None}),)))


def test_fixture_uniqueness_across_templates_and_checkpoints():
    table = [candidate("a", "one"), candidate("b", "one"), candidate("b", "two")]
    chosen = full.select([["DRIFT-CUR", 60, 1], ["DRIFT-CUR", 20, 1]], table, stub)
    assert [(b.template_id, b.fields, b.checkpoint) for b in chosen] == [
        ("a", (("fixture", "one"),), 20), ("b", (("fixture", "two"),), 60)]
    assert chosen == full.select([["DRIFT-CUR", 20, 1], ["DRIFT-CUR", 60, 1]],
                                 reversed(table), stub)
    with pytest.raises(ValueError, match="^budget:DRIFT-CUR@20:2/3$"):
        full.select([["DRIFT-CUR", 20, 3]], table, stub)


def test_shared_forget_identity_and_unmet_budget():
    table = [candidate("keep-forget", cell="KEEP-FORGET", kind="forget"),
             candidate("keep-neighbour", cell="KEEP-NEIGH", kind="forget")]
    with pytest.raises(ValueError, match="^budget:KEEP-NEIGH@60:0/1$"):
        full.select([["KEEP-FORGET", 20, 1], ["KEEP-NEIGH", 60, 1]], table, stub)


def test_compile_refusal_skips_candidate():
    def compile_one(b):
        if b.template_id == "a":
            raise ValueError("not available")
        return stub(b)

    chosen = full.select([["DRIFT-CUR", 20, 1]], [candidate(), candidate("b")], compile_one)
    assert chosen[0].template_id == "b"


def greedy(table, compile_one):
    budget = []
    for cell in sorted({c.template.cell_id for c in table}):
        for checkpoint in full.named("full").checkpoints:
            trial = [*budget, [cell, checkpoint, 1]]
            try:
                full.select(trial, table, compile_one)
            except ValueError:
                continue
            budget = trial
            if len(budget) == 6:
                return budget
    return budget


@pytest.fixture(scope="module", params=[("G1", 1), ("G2", 2)])
def measured(request, tmp_path_factory):
    global SLOW_BUILD
    if SLOW_BUILD and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("an earlier measured full-scale build exceeded 90 seconds")
    genre, seed = request.param
    life = f"full-{genre.lower()}"
    root = tmp_path_factory.mktemp(f"full-{genre}")
    table = full.candidates(genre)
    db, schedule, principal = full._world(genre, life, seed, root)
    try:
        compile_one = full._compiler(db, schedule, principal, genre)
        unavailable = []
        for c in table:
            errors = []
            for checkpoint in schedule.scale.checkpoints:
                try:
                    branch = compile_one(c.binding(checkpoint))
                    assert len(branch.entries) == 1
                except ValueError as error:
                    errors.append([checkpoint, str(error)])
            if len(errors) == len(schedule.scale.checkpoints):
                unavailable.append([c.template.template_id, c.fixture, errors])
        budget = greedy(table, compile_one)
    finally:
        db.close()
    started = monotonic()
    result = full.build(genre, life, seed, budget, root / "twin")
    elapsed = monotonic() - started
    SLOW_BUILD = SLOW_BUILD or elapsed > 90
    indices = {p.session_id: p.index for p in schedule.sessions}
    fork = min(indices[r["session_id"]] for c in result.twin.cuts for r in c.rows
               if r["event_id"] in result.twin.differing)
    facts = dict(genre=genre, seed=seed, life=life, seconds=elapsed, fork=fork, budget=budget,
                 sizes={p.name: p.stat().st_size for p in sorted((root / "twin/branches").iterdir())},
                 unavailable=unavailable)
    yield result, facts, root
    result.twin.b1.close()


def test_full_scale(measured, capsys):
    result, facts, root = measured
    with capsys.disabled():
        print("\nFULLTWIN " + json.dumps(facts, sort_keys=True), flush=True)
    if facts["seconds"] > 90 and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("measured full-scale build exceeded 90 seconds")
    assert 0 < len(result.bindings) <= 6
    assert (root / "twin/bindings.json").read_bytes() == canon(json.loads(
        (root / "twin/bindings.json").read_bytes())) + b"\n"
    templates = {t.template_id: t for t in (*full.G1, *full.G2)}
    schedule = full.build_schedule(full.seed_text(facts["seed"]), facts["life"], full.named("full"))
    assert len(schedule.sessions) == 200
    assert schedule.scale.checkpoints == (20, 60, 120, 200)
    assert schedule.scale.kill == 110 and schedule.scale.swap == 150
    table = full.candidates(facts["genre"])
    fixtures = [next(c.fixture for c in table if c.binding(b.checkpoint) == b) for b in result.bindings]
    assert len(set(fixtures)) == len(fixtures)
    assert set(result.prompts) == {(branch, row[1]) for row in facts["budget"] for branch in ("B0", "B1")}
    for branch in ("B0", "B1"):
        records = [r for r in result.twin.compiled.records if r["branch"] == branch]
        assert len(records) == len(result.bindings)
        for b in result.bindings:
            bound = replace(templates[b.template_id], **dict(b.fields), checkpoint=b.checkpoint)
            instance, = bound.instances(result.twin.b1, schedule)
            matches = [r for r in records if r["template_id"] == b.template_id
                       and r["instance_key"] == instance.key]
            assert len(matches) == 1
            assert templates[b.template_id].checkpoint is None
        for checkpoint in {b.checkpoint for b in result.bindings}:
            ids = {r["item_id"] for r in records}
            assert result.prompts[branch, checkpoint] == tuple(i["prompt"]
                for i in result.twin.compiled.items if i["item_id"] in ids and i["probe_point"] == checkpoint)


def test_capacity(measured, capsys):
    _, facts, root = measured
    if facts["seconds"] > 90 and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("measured full-scale build exceeded 90 seconds")
    counts = full.capacity(facts["genre"], facts["life"], facts["seed"], root / "capacity")
    with capsys.disabled():
        print("\nCAPACITY " + json.dumps([[*key, n] for key, n in counts.items()]), flush=True)
    assert all(counts["TUE-EVENT", k] == 0 for k in full.named("full").checkpoints)


def test_determinism(measured, tmp_path):
    result, facts, root = measured
    if facts["seconds"] > 90 and os.environ.get("BICENTENNIAL_FULLTWIN") != "1":
        pytest.skip("measured full-scale build exceeded 90 seconds")
    script = '''
import json, sys
from pathlib import Path
from bicentennial.world.fulltwin import build
from bicentennial.render.stream import stream_hash
r = build(sys.argv[1], sys.argv[2], int(sys.argv[3]), json.loads(sys.argv[4]), Path(sys.argv[5]))
print(json.dumps([[stream_hash(c.rows) for c in r.twin.cuts],
    (Path(sys.argv[5]) / "bindings.json").read_text()]))
r.twin.b1.close()
'''
    expected = [[stream_hash(c.rows) for c in result.twin.cuts],
                (root / "twin/bindings.json").read_text()]
    for j, seed in enumerate(("0", "random")):
        run = subprocess.run([sys.executable, "-c", script, facts["genre"], facts["life"],
            str(facts["seed"]), json.dumps(facts["budget"]), str(tmp_path / str(j))],
            cwd=ROOT, env=os.environ | {"PYTHONHASHSEED": seed}, capture_output=True, check=True)
        assert json.loads(run.stdout) == expected
