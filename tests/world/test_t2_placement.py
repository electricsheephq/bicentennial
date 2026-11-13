"""T2 placement window, public roster freeze and error boundaries."""

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.items.templates import g1, g2
from bicentennial.world import targeted as t
from bicentennial.world.processes import mint

from .test_targeted_t2 import ROWS

TEMPLATES = {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}
ROOT = Path(__file__).resolve().parents[2]


def test_window_material(tmp_path):
    for genre in TEMPLATES:
        for seed in range(16):
            row = dict(life=f"window-{genre.lower()}-{seed}", genre=genre, seed=seed)
            if genre == "G1":
                row["reads_session"] = 1
            spec = t._tier_source("T2", lives=[row])
            schedule = t.t1_schedule(spec, row)
            path = tmp_path / f'{row["life"]}.db'
            db, _ = t._build_t1(path, schedule, spec=spec, row=row)
            try:
                facts = ([mint(schedule, "g1_software", f"decision-t2-{i}", "fact", "value", 0) for i in range(2)]
                         if genre == "G1" else
                         [mint(schedule, "corrections", "plan-trip-t2", "fact", "value", i) for i in range(3)] +
                         [mint(schedule, "incidental", "gate-t2", "fact", "detail", 0)])
                sessions = []
                for fid in facts:
                    events = db.execute("SELECT e.t_sim FROM event e JOIN link l ON l.event_id=e.id "
                                        "WHERE l.fact_id=? AND l.role='assert'", (fid,)).fetchall()
                    assert events
                    sessions.extend(next(s.index for s in schedule.sessions if at in s.turn_t) for at, in events)
                assert max(sessions) <= spec["evidence_by"] == 8
                if genre == "G2":
                    assert len(set(sessions[:3])) == 3
            finally:
                db.close()


def test_checkpoint_exhaustion(tmp_path):
    row = ROWS[1]
    assert (row["seed"], row["life"]) == (5, "t2-g1-2")
    spec = t._tier_source("T2", lives=[row])
    del spec["evidence_by"]
    with pytest.raises(t.PlacementError, match="^checkpoint$") as exc:
        t.t1_life(spec, row, g1.TEMPLATES, out_dir=tmp_path / "life")
    assert type(exc.value.__cause__) is ValueError
    assert exc.value.item_id == "wake-loop-v1"


def test_compile_integrity_not_translated(tmp_path, monkeypatch):
    error = ValueError("decision table disagrees with item")

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(t, "compile_branch", broken)
    with pytest.raises(ValueError) as exc:
        t.t1_life(t._tier_source("T2", lives=ROWS), ROWS[0], g1.TEMPLATES, out_dir=tmp_path / "life")
    assert exc.value is error
    assert not isinstance(exc.value, t.PlacementError)


@pytest.mark.parametrize("kind,count", [("qa", 7), ("act", 3)])
def test_t2_caps(kind, count):
    compiled = SimpleNamespace(items=[dict(item_id=str(i), probe_point=5,
                                          stage="act" if kind == "act" else "remember") for i in range(count)],
                               records=[dict(item_id=str(i), branch="B0") for i in range(count)])
    with pytest.raises(t.PlacementError, match="^probe_cap$"):
        t._check_t2(t._tier_source("T2", lives=ROWS), compiled)


def test_t1_does_not_check_t2(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("T1 called T2 cap check")

    monkeypatch.setattr(t, "_check_t2", forbidden)
    spec = t.load_tier(ROOT / "tiers/life_specs/t1.toml")
    life = t.t1_life(spec, spec["lives"][0], g1.TEMPLATES, out_dir=tmp_path / "life")
    life.twin.b1.close()


def test_frozen_roster_and_dry_run(tmp_path):
    spec = t.load_tier(ROOT / "tiers/life_specs/t2.toml")
    assert spec["lives"] == ROWS
    assert spec["replacements"] == []
    subset = t._tier_source("T2", lives=[ROWS[0], ROWS[5]])
    frozen, table = t.t2_dry_run(subset, TEMPLATES, root=tmp_path)
    assert frozen == subset
    for row in table:
        assert row["placement"] and row["result"] == "pass"
        assert row["checkpoint_5"] and row["early_bundles"] >= 2
        assert all(n <= (2 if key.endswith("act") else 6) for key, n in row["caps"].items())


def test_failed_seed_replaced_in_order(tmp_path, monkeypatch):
    original = t.t1_life
    tried = []

    def draw(spec, row, templates, **kwargs):
        tried.append((row["life"], row["seed"]))
        if row["seed"] in (4, 14):
            error = t.PlacementError("hostable")
            error.item_id = "recall-value-v1"
            raise error
        return original(spec, row, templates, **kwargs)

    monkeypatch.setattr(t, "t1_life", draw)
    spec = t._tier_source("T2", lives=[ROWS[0], ROWS[5]])
    frozen, table = t.t2_dry_run(spec, TEMPLATES, root=tmp_path)
    assert tried == [("t2-g1-1", 4), ("t2-g1-1", 14), ("t2-g1-1", 15), ("t2-g2-1", 9)]
    assert [r["seed"] for r in frozen["lives"]] == [15, 9]
    assert [r["replacement_seed"] for r in frozen["replacements"]] == [14, 15]
    assert all(r["rule"] == "hostable" and r["item_id"] == "recall-value-v1" for r in frozen["replacements"])
    assert Counter(r["result"] for r in table) == {"PlacementError": 2, "pass": 2}


def test_dry_run_preserves_existing_directory(tmp_path):
    spec = t._tier_source("T2", lives=[ROWS[0]])
    life_dir = tmp_path / ROWS[0]["life"]
    life_dir.mkdir()
    sentinel = life_dir / "keep"
    sentinel.write_text("original")
    with pytest.raises(FileExistsError):
        t.t2_dry_run(spec, TEMPLATES, root=tmp_path)
    assert sentinel.read_text() == "original"


def test_replacements_capped(tmp_path, monkeypatch):
    calls = []

    def always(spec, row, templates, **kwargs):
        calls.append(row["seed"])
        if len(calls) > 50:
            raise RuntimeError("unbounded replacement loop")
        raise t.PlacementError("hostable")

    monkeypatch.setattr(t, "t1_life", always)
    spec = t._tier_source("T2", lives=[ROWS[0], ROWS[5]])
    with pytest.raises(t.PlacementError, match="^replacements$") as exc:
        t.t2_dry_run(spec, TEMPLATES, root=tmp_path)
    assert calls == [4, *range(14, 14 + t.MAX_REPLACEMENTS)]
    assert exc.value.__cause__.rule == "hostable"
    assert not (tmp_path / ROWS[0]["life"]).exists()


def test_template_composition_not_replaced(tmp_path, monkeypatch):
    original, calls = t._select_templates, []

    def counted(*args):
        calls.append(1)
        if len(calls) > 50:
            raise RuntimeError("unbounded replacement loop")
        return original(*args)

    monkeypatch.setattr(t, "_select_templates", counted)
    missing = {"G1": tuple(x for x in g1.TEMPLATES if x.template_id != "recall-value"), "G2": g2.TEMPLATES}
    with pytest.raises(t.PlacementError, match="^composition$"):
        t.t2_dry_run(t._tier_source("T2", lives=[ROWS[0]]), missing, root=tmp_path)
    assert len(calls) == 1
    assert not (tmp_path / ROWS[0]["life"]).exists()


def test_dry_run_reserves_life_directory(tmp_path, monkeypatch):
    life_dir, seen = tmp_path / ROWS[0]["life"], []

    def rival(spec, row, templates, **kwargs):
        try:
            life_dir.mkdir()  # a concurrent run claiming the same life
        except FileExistsError:
            seen.append("reserved")
        else:
            (life_dir / "keep").write_text("theirs")
            seen.append("stolen")
        raise RuntimeError("stop")

    monkeypatch.setattr(t, "t1_life", rival)
    with pytest.raises(RuntimeError, match="^stop$"):
        t.t2_dry_run(t._tier_source("T2", lives=[ROWS[0]]), TEMPLATES, root=tmp_path)
    assert seen == ["reserved"]
    assert not life_dir.exists()


def _fake_dry_run(monkeypatch, fails):
    """Stub the build and caps so only the seed bookkeeping runs; `fails(seed)` decides each seed."""
    tried = []

    def fake(spec, row, templates, **kwargs):
        tried.append((row["life"], row["seed"]))
        if len(tried) > 50:
            raise RuntimeError("unbounded replacement loop")
        if fails(row["seed"]):
            error = t.PlacementError("hostable")
            error.item_id = "recall-value-v1"
            raise error
        compiled = SimpleNamespace(items=[], records=[])
        return SimpleNamespace(twin=SimpleNamespace(compiled=compiled, b1=SimpleNamespace(close=lambda: None)))

    monkeypatch.setattr(t, "t1_life", fake)
    monkeypatch.setattr(t, "_check_t1", lambda *args: None)
    monkeypatch.setattr(t, "_check_t2", lambda *args: None)
    return tried


def test_pool_consumed_in_order(tmp_path, monkeypatch):
    big = 2 ** 63 - 1
    tried = _fake_dry_run(monkeypatch, lambda seed: seed in (4, big, 101))
    spec = t._tier_source("T2", lives=[ROWS[0], ROWS[5]])
    frozen, table = t.t2_dry_run(spec, TEMPLATES, root=tmp_path, pool=[big, 9, 101, 102, 103])
    # 9 is already the second life's design seed, so it is passed over; nothing unused is skipped.
    assert tried == [("t2-g1-1", 4), ("t2-g1-1", big), ("t2-g1-1", 101), ("t2-g1-1", 102), ("t2-g2-1", 9)]
    assert [r["seed"] for r in frozen["lives"]] == [102, 9]
    assert [(r["seed"], r["replacement_seed"]) for r in frozen["replacements"]] == [(4, big), (big, 101), (101, 102)]
    assert [r["result"] for r in table] == ["PlacementError"] * 3 + ["pass"] * 2
    assert not any(tmp_path.iterdir())


def test_pool_refuses_bad_seed_before_building(tmp_path, monkeypatch):
    tried = _fake_dry_run(monkeypatch, lambda seed: False)
    for bad in (-1, "15", True):
        with pytest.raises(t.PlacementError, match="^composition$"):
            t.t2_dry_run(t._tier_source("T2", lives=[ROWS[0]]), TEMPLATES, root=tmp_path, pool=[15, bad])
    assert tried == []


def test_pool_exhausted_carries_table(tmp_path, monkeypatch):
    tried = _fake_dry_run(monkeypatch, lambda seed: seed != 9)
    spec = t._tier_source("T2", lives=[ROWS[5], ROWS[0]])
    with pytest.raises(t.PlacementError, match="^pool$") as exc:
        t.t2_dry_run(spec, TEMPLATES, root=tmp_path, pool=[100, 9])
    assert tried == [("t2-g2-1", 9), ("t2-g1-1", 4), ("t2-g1-1", 100)]
    assert exc.value.__cause__.rule == "hostable"
    assert [(r["life"], r["seed"], r["result"]) for r in exc.value.table] == [
        ("t2-g2-1", 9, "pass"), ("t2-g1-1", 4, "PlacementError"), ("t2-g1-1", 100, "PlacementError")]
    assert exc.value.replacements == [dict(life="t2-g1-1", seed=4, replacement_seed=100, rule="hostable",
                                           item_id="recall-value-v1")]
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize("pool", [None, list(range(100, 120))])
def test_terminal_errors_carry_table(tmp_path, monkeypatch, pool):
    _fake_dry_run(monkeypatch, lambda seed: seed in (4, 9))
    spec = t._tier_source("T2", lives=[ROWS[0], ROWS[5]])
    with pytest.raises(t.PlacementError, match="^design_failures$") as exc:
        t.t2_dry_run(spec, TEMPLATES, root=tmp_path / "design", pool=pool)
    first = 14 if pool is None else 100
    assert [(r["seed"], r["result"]) for r in exc.value.table] == [
        (4, "PlacementError"), (first, "pass"), (9, "PlacementError")]
    assert [r["replacement_seed"] for r in exc.value.replacements] == [first]

    _fake_dry_run(monkeypatch, lambda seed: True)
    with pytest.raises(t.PlacementError, match="^replacements$") as exc:
        t.t2_dry_run(spec, TEMPLATES, root=tmp_path / "replacements", pool=pool)
    assert len(exc.value.table) == t.MAX_REPLACEMENTS + 1
    assert not any(r["placement"] for r in exc.value.table)
    assert len(exc.value.replacements) == t.MAX_REPLACEMENTS
    assert exc.value.replacements[0]["replacement_seed"] == first


def test_63_bit_seeds_build(tmp_path):
    big, drawn = 2 ** 63 - 1, 7_316_270_582_391_045_117
    rows = [dict(ROWS[0], seed=big), dict(ROWS[5], seed=drawn)]
    spec = t._tier_source("T2", lives=rows)
    frozen, table = t.t2_dry_run(spec, TEMPLATES, root=tmp_path, pool=[])
    assert frozen == spec
    assert [(r["genre"], r["seed"], r["result"]) for r in table] == [("G1", big, "pass"), ("G2", drawn, "pass")]
