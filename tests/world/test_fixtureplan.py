"""Planner properties, refusal boundaries, rotation and the dry identities."""

import json
import re
from collections import Counter
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from bicentennial.canon import canon
from bicentennial.genres.g1_software.world import KINDS, TEAM_NAMES
from bicentennial.items.templates.g1.common import step
from bicentennial.keyed import uniform_int
from bicentennial.world import fixtureplan as fp
from bicentennial.world import fulltwin as full
from bicentennial.world import unit
from bicentennial.world.processes import Unit, slot
from bicentennial.world.processes.commitments import _plan


def schedule(life="plan", seed=1):
    return fp.build_schedule(full.seed_text(seed), life, fp.named("full"))


def budget(genre, n=1):
    registry = fp.G1 if genre == "G1" else fp.G2
    return [[cell, k, n] for cell in sorted({t.cell_id for t in registry})
            for k in fp.named("full").checkpoints if fp.eligible(genre, cell, k)]


def check_plan(p, s):
    slots = Counter(e.at for f in p.fixtures for e in f.events)
    assert 1 <= p.fork <= 20
    assert len(p.removed) == len(set(p.removed))
    assert all(slots[pos] == 1 for pos in p.removed)
    for f in p.fixtures:
        if f.mode == "tue":
            spec = f.calls[0][1]
            made, trigger, _, _, cancel, lures = _plan(Unit(None, s, "commitments", spec), spec)
            expected = dict(zip(("made", "trigger", "lure", "cancel"),
                                (made, trigger, lures[0], cancel), strict=True))
            assert all(slot(s, *e.at) == expected[e.part] for e in f.events)
            assert all(1 <= e.at[0] <= f.checkpoint - 2 for e in f.events if e.part in ("made", "cancel"))
            assert next(e.at[0] for e in f.events if e.part == "trigger") == f.checkpoint
            assert made < lures[0] < s.sessions[f.checkpoint - 1].t_end
            assert lures[0] != trigger
        else:
            assert all(1 <= e.at[0] <= f.checkpoint - 2 for e in f.events)
            for writer, spec in f.calls:
                if writer in ("corrections", "preferences"):
                    assert all(a[0] < b[0] for a, b in zip(spec.at, spec.at[1:], strict=False))
            if f.template.endswith(".DriftChain"):
                template = next(t for t in fp.G1 if t.template_id == f.binding.template_id)
                if template.fault:
                    assert max(e.at for e in f.events) <= (110, 1)
                elif f.checkpoint >= 110:
                    assert min(e.at for e in f.events) >= (110, 2)


@pytest.mark.parametrize("genre", ("G1", "G2"))
def test_sweep(genre, capsys):
    lives = [(f"sweep-{genre}-{i}", i + 1) for i in range(50)]
    lives += [(f"ocsim-dry-{i:03d}", int.from_bytes(
        sha256(canon(["ocsim-dry", i])).digest()[:8], "big") >> 1)
        for i in range(48) if (i % 2 == 0) == (genre == "G1")]
    rows = fp.sweep(genre, lives, budget(genre))
    assert all(r["refusal"] is None and 1 <= r["fork"] <= 20 for r in rows)
    for life, seed in lives:
        s = schedule(life, seed)
        check_plan(fp.plan(genre, s, budget(genre), fp.G1 if genre == "G1" else fp.G2), s)
    with capsys.disabled():
        print("SWEEP", genre, json.dumps(dict(sorted(Counter(r["fork"] for r in rows).items()))))


def test_rotation():
    offsets = set()
    for i in range(8):
        s = schedule(f"rotation-{i}")
        p = fp.plan("G1", s, [["DRIFT-CUR", 20, 1], ["DRIFT-CUR", 120, 7]], fp.G1)
        choices = fp.eligible("G1", "DRIFT-CUR", 120)
        assert len(choices) == 4
        offset = next(o for c, k, o in p.offsets if (c, k) == ("DRIFT-CUR", 120))
        assert offset == uniform_int(s.seed, unit(s.life, "fixture-plan", "DRIFT-CUR@120"),
                                     0, "rotation", 0, 3)
        offsets.add(offset)
        assert [f.binding.template_id for f in p.fixtures if f.checkpoint == 120] == [
            choices[(offset + j) % 4].template_id for j in range(7)]
    assert len(offsets) > 1
    t = replace(fp.G1[0], template_id="x")
    assert fp.plan("G1", schedule(), [["DRIFT-CUR", 20, 1]], (t,)).bindings[0].template_id == "x"


@pytest.mark.parametrize("genre,cell", (("G1", "KEEP-INC"), ("G2", "WAKE-LOOP")))
def test_no_template(genre, cell, tmp_path):
    with pytest.raises(ValueError, match=f"^plan:no_template:{cell}@20$"):
        full.build(genre, "refusal", 1, [[cell, 20, 1]], tmp_path / "absent" / "out")
    assert list(tmp_path.iterdir()) == []


def test_no_fork(tmp_path):
    for rows in ([["DRIFT-CUR", 60, 1]], [["RECALL-VERB", 20, 1]], []):
        with pytest.raises(ValueError, match="^budget:no_fork$"):
            full.build("G1", "refusal", 1, rows, tmp_path / "absent" / "out")
    assert list(tmp_path.iterdir()) == []


def test_window(monkeypatch, tmp_path):
    assert fp.window(20) == (1, 18)
    monkeypatch.setitem(fp.FACTORIES, fp.qualname(fp.G1[0]), lambda t: fp.Shape("chain", ("milestone",), 19))
    monkeypatch.setattr(full, "G1", (fp.G1[0],))
    with pytest.raises(ValueError, match="^plan:window:DRIFT-CUR@20$"):
        full.build("G1", "refusal", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_removed_slots(monkeypatch):
    monkeypatch.setattr(fp, "window", lambda k: (1, 1))
    t = next(t for t in fp.G2 if t.template_id == "keep-forget")
    monkeypatch.setitem(fp.FACTORIES, fp.qualname(t), lambda t: fp.Shape("forget", ("person",), 1))
    with pytest.raises(ValueError, match="^plan:slots:KEEP-FORGET@20$"):
        fp.plan("G2", schedule(), [["KEEP-FORGET", 20, 6]], (t,))
    load, reserved = Counter(), {(1, i) for i in range(1, 5)}
    fp._place(schedule(), "DRIFT-CUR/20/0", 20, 1, load, reserved)
    assert load[1, 5] == 1
    with pytest.raises(ValueError, match="^plan:slots:DRIFT-CUR@20$"):
        fp._place(schedule(), "DRIFT-CUR/20/1", 20, 1, load, reserved, removed=(0,))


def test_tue_exhausted(monkeypatch):
    def miss(*args):
        raise ValueError("synthetic")
    monkeypatch.setattr(fp, "_plan", miss)
    with pytest.raises(ValueError, match="^plan:slots:TUE-EVENT@20$"):
        fp.plan("G1", schedule(), [["TUE-EVENT", 20, 1]], fp.G1)


@pytest.mark.parametrize("bad", (("milestone",), ("batch_size",)))
def test_names_refuse_g1(monkeypatch, tmp_path, bad):
    monkeypatch.setitem(fp.LEXICONS, "milestone", bad)
    monkeypatch.setattr(full, "G1", (fp.G1[0],))
    with pytest.raises(ValueError, match="^plan:names$"):
        full.build("G1", "refusal", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_names_refuse_g2(monkeypatch):
    monkeypatch.setitem(fp.BANDS, "person", ("Person", 130, 130))
    with pytest.raises(ValueError, match="^plan:names$"):
        fp.plan("G2", schedule(), [["KEEP-FORGET", 20, 2]], fp.G2)


def test_fork_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(fp, "predicted_fork", lambda fixtures: 21)
    with pytest.raises(ValueError, match="^plan:fork$"):
        full.build("G1", "refusal", 1, [["DRIFT-CUR", 20, 1]], tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_lower_bounds(monkeypatch):
    monkeypatch.setattr(fp, "_draw", lambda s, key, purpose, lo, hi: lo)
    p = fp.plan("G1", schedule(), [["DRIFT-CUR", 20, 1], ["DRIFT-CUR", 120, 4], ["TUE-EVENT", 20, 1]], fp.G1)
    chain = next(f for f in p.fixtures if f.binding.template_id == "drift-chain" and f.checkpoint == 120)
    assert chain.events[0].at == (110, 2)
    fault = next(f for f in p.fixtures if f.binding.template_id == "drift-chain-fault")
    assert max(e.at for e in fault.events) <= (110, 1)
    check_plan(p, schedule())


def test_planned_load(monkeypatch):
    monkeypatch.setattr(fp, "_draw", lambda s, key, purpose, lo, hi: lo)
    s = schedule()
    t = next(t for t in fp.G1 if t.template_id == "drift-config")
    load = Counter()
    f = fp._fixture("G1", s, t, fp.FACTORIES[fp.qualname(t)](t), "DRIFT-CUR/20/0", 20,
                    {"constant": ["amber_buffer"]}, load, set())
    assert load == Counter(e.at for e in f.events)
    p = fp.plan("G1", s, [["TUE-EVENT", 20, 1]], fp.G1)
    entities = p.fixtures[0].entities
    load = Counter({(20, 1): 2})
    spec, _ = fp._tue(s, "TUE-EVENT/20/0", 20, entities, load, set())
    assert spec.due == (20, 2)


@pytest.mark.parametrize("genre", ("G1", "G2"))
def test_names_and_json(genre, tmp_path):
    p = fp.plan(genre, schedule(), budget(genre, 2), fp.G1 if genre == "G1" else fp.G2)
    other = fp.plan(genre, schedule(seed=2), budget(genre, 2), fp.G1 if genre == "G1" else fp.G2)
    names = [e.name for f in p.fixtures for e in f.entities]
    assert names != [e.name for f in other.fixtures for e in f.entities]
    with pytest.raises(FrozenInstanceError):
        p.fork = 100
    db, _, _ = full._world(genre, "plan", 1, tmp_path)
    defaults = {r[0] for r in db.execute("SELECT canonical_name FROM entity")}
    db.close()
    assert not set(names) & defaults
    if genre == "G1":
        banned = {*KINDS, *TEAM_NAMES, *(n for ns, _, _ in KINDS.values() for n in ns)}
        assert not set(names) & banned
        assert all(not re.search(r"\d", n) for n in names)
        assert not any(a in b or b in a for a in names for b in defaults)
        assert not any(a in b for i, a in enumerate(names) for j, b in enumerate(names) if i != j)
        for n in names:
            step("docs/decisions.md", n, "TEST-123456")
    else:
        for f in p.fixtures:
            for e in f.entities:
                label, lo, hi = fp.BANDS[e.kind]
                assert re.fullmatch(label + r" \d{3}", e.name)
                assert lo <= int(e.name.split()[1]) <= hi
    raw = fp.plan_json(p)
    obj = json.loads(raw)
    assert raw == canon(obj) + b"\n"
    assert obj["fork"] == p.fork
    assert obj["removed"] == [list(pos) for pos in p.removed]
    assert obj["offsets"] == [list(v) for v in p.offsets]
    assert obj["histogram"] == [[k, n] for k, n in sorted(Counter(e.at[0] for f in p.fixtures for e in f.events).items())]
    assert obj["tue_distance_note"] == "Only the trigger is exempt; compiled distance_sessions remains 0."
    assert all(n == 1 for c, k, n in obj["prompt_distinctness"] if c in ("TUE-EVENT", "WAKE-LOOP"))
    assert all(n == 2 for c, k, n in obj["prompt_distinctness"] if c not in ("TUE-EVENT", "WAKE-LOOP"))
