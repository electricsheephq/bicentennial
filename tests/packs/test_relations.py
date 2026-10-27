"""Synthetic readers, branch-sensitive INV checks and diagnostic refusals."""

from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.keyed import uniform_int
from bicentennial.packs.catalogue import load_catalogue
from bicentennial.packs.relations import check

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue(ROOT / "packs/catalogue-v0.toml", c7_path=ROOT / "specs/ring0/c7-partial.json",
                          tier_path=ROOT / "tiers/life_specs/t0.toml")


def reader(rows, score):
    return {r.id: {b: dict(failure_class=None, score_milli=score(r))
                   for b in (("B0", "B1") if r.twin else ("B0",))} for r in rows}


@pytest.mark.parametrize("score", (0, 1000))
def test_flat_readers(catalogue, score):
    report = check(catalogue.rows, reader(catalogue.rows, lambda r: score))
    assert report.flagged == ()
    assert report.to_obj()["counts"] == dict(holds=50, flagged=0, unscored=0, confounded=4)
    assert len(report.relations) == 54
    assert [r.row for r in report.relations] == sorted(r.row for r in report.relations)
    assert report.to_obj()["labels"] == ["not predictive of the full tier; never certifies",
                                          "rungs: uncalibrated (v0.2)"]
    assert canon(report.to_obj())
    with pytest.raises((AttributeError, TypeError)):
        report.relations = ()
    with pytest.raises((AttributeError, TypeError)):
        report.relations[0].status = "flagged"
    with pytest.raises(FrozenInstanceError):
        catalogue.rows[0].seed = 7


@pytest.mark.parametrize("kind", ("seed", "distance", "wake"))
def test_sensitive_readers(catalogue, kind):
    scores = {
        "seed": lambda r: 1000 if r.seed == 1 else -1000,
        "distance": lambda r: 1000 if r.distance >= 2 else 0,
        "wake": lambda r: 1000 if r.wake != "none" else 0,
    }
    report = check(catalogue.rows, reader(catalogue.rows, scores[kind]))
    if kind == "seed":
        expected = sorted(r.id for r in catalogue.rows if r.test == "INV" and not r.confounded)
        assert len(expected) == 26
    elif kind == "distance":
        expected = ["g1-recall-value-dir-1", "g1-wake-loop-dir-1",
                    "g2-keep-incidental-dir-1", "g2-keep-neighbour-dir-1"]
    else:
        expected = sorted(r.id for r in catalogue.rows if r.test == "DIR" and r.vary == "wake")
        assert len(expected) == 20
        assert all(r.status == "holds" for r in report.relations if "drift-chain-fault" in r.row)
    assert list(report.flagged) == expected


def test_branch_swap(catalogue):
    row = catalogue.by_id()["g1-drift-chain-inv-1"]
    outcomes = reader(catalogue.rows, lambda r: 1000)
    outcomes[row.id]["B1"]["score_milli"] = -1000
    outcomes[row.base]["B0"]["score_milli"] = -1000
    relation = next(r for r in check(catalogue.rows, outcomes).relations if r.row == row.id)
    assert relation.row_score == relation.base_score == -1000
    assert relation.status == "flagged"


def test_nonresults(catalogue):
    outcomes = reader(catalogue.rows, lambda r: 1000)
    base = "g1-drift-chain-mft-1"
    outcomes[base]["B1"] = dict(failure_class="BLOCKED", score_milli=None)
    report = check(catalogue.rows, outcomes)
    related = [r for r in report.relations if r.base == base]
    assert len(related) == 4
    assert all(r.status == "unscored" and r.base_score is None for r in related)
    row = catalogue.by_id()["g2-recall-count-inv-1"]
    outcomes[row.id]["B0"] = dict(failure_class="N/A_CLOCK", score_milli=None)
    assert next(r for r in check(catalogue.rows, outcomes).relations if r.row == row.id).status == "unscored"


@pytest.mark.parametrize("case", (
    "missing-row", "missing-base", "singleton-b1", "twin-missing-b1", "score", "bool", "float",
    "null-scored", "nonnull-blocked", "missing-score", "missing-failure", "duplicate-row",
))
def test_refusals(catalogue, case):
    rows = catalogue.rows
    outcomes = reader(rows, lambda r: 0)
    row = catalogue.by_id()["g1-recall-value-mft-1"]
    if case == "missing-row":
        del outcomes[row.id]
    elif case == "missing-base":
        rows = tuple(replace(r, base="missing") if r.test == "INV" else r for r in rows)
    elif case == "singleton-b1":
        outcomes[row.id]["B1"] = dict(failure_class=None, score_milli=0)
    elif case == "twin-missing-b1":
        del outcomes["g1-drift-chain-mft-1"]["B1"]
    elif case == "missing-score":
        del outcomes[row.id]["B0"]["score_milli"]
    elif case == "missing-failure":
        del outcomes[row.id]["B0"]["failure_class"]
    elif case == "duplicate-row":
        rows = (*rows, row)
    else:
        failure, score = {"score": (None, 1001), "bool": (None, True), "float": (None, 1.0),
                          "null-scored": (None, None), "nonnull-blocked": ("BLOCKED", 0)}[case]
        outcomes[row.id]["B0"] = dict(failure_class=failure, score_milli=score)
    with pytest.raises(ValueError):
        check(rows, outcomes)


def test_keyed_direction_property(catalogue):
    """Seeded K10 draws check both boundaries and the monotonicity rule."""
    row = catalogue.by_id()["g1-recall-value-dir-1"]
    base = catalogue.by_id()[row.base]
    for case in range(64):
        key = ("g18", "relations", str(case))
        a = uniform_int("1", key, 0, "hard", -1000, 1000)
        b = uniform_int("1", key, 0, "base", -1000, 1000)
        outcomes = reader((row, base), lambda r, a=a, b=b: a if r.id == row.id else b)
        report = check((row, base), outcomes)
        assert (report.flagged == (row.id,)) == (a > b)
        assert report.relations[0].row_score == a
        assert report.relations[0].base_score == b


def test_empty():
    assert check((), {}).to_obj()["counts"] == dict(holds=0, flagged=0, unscored=0, confounded=0)


@pytest.mark.parametrize("blocked", (False, True))
def test_confounded_precedes_verdict(catalogue, blocked):
    row = catalogue.by_id()["g1-tue-ticket-inv-1"]
    base = catalogue.by_id()[row.base]
    outcomes = reader((row, base), lambda r: -1000 if r.seed == 1 else 1000)
    if blocked:
        outcomes[base.id]["B0"] = dict(failure_class="BLOCKED", score_milli=None)
    report = check((row, base), outcomes)
    assert report.flagged == ()
    assert report.to_obj()["counts"] == dict(holds=0, flagged=0, unscored=0, confounded=1)
    assert report.relations[0].status == "confounded"
    assert report.to_obj()["relations"][0]["lever_delta"] == row.lever_delta
