"""Public writers, prediction checks and append-only filler rebuilding."""

from collections import defaultdict
from dataclasses import replace

import pytest

from bicentennial.render.session_cut import cut
from bicentennial.world import fixtureplan as fp
from bicentennial.world import fulltwin as full
from bicentennial.world import planned
from bicentennial.world.export import export_jsonl
from bicentennial.world.processes import mint, slot


@pytest.mark.parametrize("genre", ("G1", "G2"))
def test_empty(genre, tmp_path):
    db, s, principal = full._world(genre, "empty", 1, tmp_path)
    before = export_jsonl(db)
    counts = planned.write_extra(genre, db, s, fp.Plan((), (), None), principal)
    assert counts["filler_shadowed"] == counts["shared_default"] == 0
    after = planned.rebuild(db, tmp_path / "rebuilt.db")
    assert export_jsonl(db) == export_jsonl(after) == before
    db.close()
    after.close()


@pytest.mark.parametrize("genre", ("G1", "G2"))
def test_overlay(genre, tmp_path):
    db, s, principal = full._world(genre, "overlay", 1, tmp_path)
    registry = full.G1 if genre == "G1" else full.G2
    budget = [["TUE-EVENT", 20, 2], ["DRIFT-CUR", 20, 3]]
    p = fp.plan(genre, s, budget, registry)
    default_times = {r[0] for r in db.execute("SELECT t_sim FROM event WHERE kind!='filler'")}
    counts = planned.write_extra(genre, db, s, p, principal)
    assert counts["filler_shadowed"] == len(planned.shadowed(db)) > 0
    assert counts["shared_default"] == sum(slot(s, *e.at) in default_times for f in p.fixtures for e in f.events)
    for f in p.fixtures:
        if f.mode == "tue":
            for e in f.events:
                eid = mint(s, "commitments", f.key, "event", e.part, 0)
                assert db.execute("SELECT t_sim FROM event WHERE id=?", (eid,)).fetchone()[0] == slot(s, *e.at)
    pre = cut(db, s, branch="B0", principal_id=principal, expected_state=full.expected_state(genre, s)(db))
    def mixed(c):
        groups = defaultdict(list)
        for r in c.rows:
            groups[r["turn_key"]].append(r)
        sprints = {p.session_id for p in s.sessions if p.long_sprint}
        return [rs for rs in groups.values() if rs[0]["session_id"] not in sprints
                and any(r["kind"] == "filler" for r in rs) and any(r["fact_ids"] for r in rs)]
    assert mixed(pre)
    clean = planned.rebuild(db, tmp_path / "clean.db")
    assert not planned.shadowed(clean)
    c = cut(clean, s, branch="B0", principal_id=principal, expected_state=full.expected_state(genre, s)(clean))
    assert not mixed(c)
    full.host(clean, s, principal, genre, p, registry)
    db.close()
    clean.close()


def test_prediction_mismatch(monkeypatch, tmp_path):
    db, s, principal = full._world("G1", "prediction", 1, tmp_path)
    p = fp.plan("G1", s, [["TUE-EVENT", 20, 1]], full.G1)
    original = planned.write_commitments
    def shifted(db, s, specs, **kwargs):
        original(db, s, [replace(spec, made=(1, 1) if spec.made != (1, 1) else (1, 2))
                         for spec in specs], **kwargs)
    monkeypatch.setattr(planned, "write_commitments", shifted)
    with pytest.raises(ValueError, match="^plan:placement$"):
        planned.write_extra("G1", db, s, p, principal)
    db.close()


def test_keep_separate(tmp_path):
    budget = [["KEEP-FORGET", 200, 1], ["KEEP-NEIGH", 200, 1], ["KEEP-NEIGH", 20, 1]]
    s = full.build_schedule(full.seed_text(1), "keep", full.named("full"))
    p = fp.plan("G2", s, budget, full.G2)
    keys = [dict(b.fields)["forget_key"] for b in p.bindings]
    assert len(set(keys)) == len(keys)
    result = full.build("G2", "keep", 1, budget, tmp_path / "out")
    assert len(result.bindings) == len(result.twin.flips) == 3
    result.twin.b1.close()
