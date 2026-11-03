"""Tier-shaped targeted generation through the existing life builder."""

from copy import deepcopy

import pytest

from bicentennial.items.templates import g1, g2
from bicentennial.world import targeted

ROWS = [dict(life=f"t2-g1-{i}", genre="G1", seed=i + 3, reads_session=1) for i in range(1, 6)] + [
    dict(life=f"t2-g2-{i}", genre="G2", seed=i + 8) for i in range(1, 6)]


def test_t2_lives(tmp_path, monkeypatch):
    spec = targeted._tier_source("T2", lives=ROWS)
    checked = []
    original = targeted._check_t1

    def check(spec, compiled):
        original(spec, compiled)
        checked.append(compiled)

    monkeypatch.setattr(targeted, "_check_t1", check)
    lives = targeted.t1_lives(spec, {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}, root=tmp_path)
    try:
        assert checked == [life.twin.compiled for life in lives]
        for row, life in zip(ROWS, lives, strict=True):
            schedule, compiled = life.schedule, life.twin.compiled
            assert life.manifest["tier"] == "T2"
            assert life.manifest["spec"] == row
            assert schedule.scale.name == "t2"
            assert len(schedule.sessions) == 10
            assert schedule.scale.checkpoints == (5, 10)
            assert [s.index for s in schedule.sessions if s.probe_point] == [5, 10]
            assert schedule.fault_lite() == [dict(kind="kill", session=6, turn=1),
                                            dict(kind="swap", session=8, turn=None)]
            assert spec["swap"]["wiring_only"] is True
            assert any(s.long_sprint for s in schedule.sessions[:5])
            assert any(s.long_sprint for s in schedule.sessions[6:])
            items = {i["item_id"]: i for i in compiled.items}
            assert {i["probe_point"] for i in compiled.items} == {5, 10}
            assert all(r["evidence_session"] is not None
                       and targeted.hostable(r["evidence_session"], items[r["item_id"]]["probe_point"])
                       for r in compiled.records)
            early = {r["bundle_id"] for r in compiled.records if r["branch"] == "B0"
                     and r["bundle_id"] is not None and r["evidence_session"] <= 2}
            assert len(early) >= 2
            assert {r["template_id"] for r in compiled.records} == set(spec["selection"][row["genre"].lower()])
            assert all(items[r["item_id"]]["probe_point"] == 10 for r in compiled.records
                       if r["template_id"] in spec["selection"]["pinned"])
    finally:
        for life in lives:
            life.twin.b1.close()


def test_t2_schedule():
    spec = targeted._tier_source("T2", lives=ROWS)
    schedule = targeted.t1_schedule(spec, ROWS[0])
    assert len(schedule.sessions) == 10
    assert schedule.fault_lite() == [dict(kind="kill", session=6, turn=1),
                                    dict(kind="swap", session=8, turn=None)]


@pytest.mark.parametrize("section,field,value", [
    (None, "checkpoints", [10, 20]),
    (None, "window", 131072),
    ("kill", "session", 11),
    ("kill", "session", 7),
    ("kill", "turn", 2),
    ("swap", "session", 9),
    ("swap", "wiring_only", False),
    ("compaction", "min_sprints", 3),
])
def test_t2_schedule_refuses_spec_mismatch(section, field, value):
    spec = targeted._tier_source("T2", lives=ROWS)
    (spec if section is None else spec[section])[field] = value
    with pytest.raises(targeted.PlacementError, match="composition"):
        targeted.t1_schedule(spec, ROWS[0])


@pytest.mark.parametrize("rows", [[], ROWS[:1], ROWS, [*ROWS, dict(life="draw-3", genre="G1", seed=18)]])
def test_t2_source_takes_caller_lives(rows):
    before = deepcopy(rows)
    spec = targeted._tier_source("T2", lives=rows)
    assert spec["lives"] == rows == before
    assert spec["tier"] == "T2" and spec["scale"] == "t2"
    assert spec["checkpoints"] == [5, 10]
    assert spec["kill"] == dict(session=6, turn=1)
    assert spec["swap"]["session"] == 8
    assert set(spec["selection"]["pinned"].values()) == {10}
    assert (spec["qa_per_checkpoint"], spec["act_per_checkpoint"]) == (6, 2)


def test_t2_source_requires_lives():
    with pytest.raises(targeted.PlacementError, match="composition"):
        targeted._tier_source("T2")


def test_t2_load_path_stays_closed(tmp_path):
    path = tmp_path / "tier.toml"
    path.write_text('tier = "T2"\n')
    with pytest.raises(targeted.PlacementError, match="composition"):
        targeted.load_tier(path)
