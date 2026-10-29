"""Hand-derived board inputs and validation from SPEC-B §B3.3."""

import re
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from itertools import product

import pytest

from bicentennial.ocsim.board import (
    BoardInputs,
    assemble,
    assemble_schedule,
    bundle_value,
)
from bicentennial.ocsim.drift import ARMS
from bicentennial.ocsim.schedule import (
    STATUSES,
    Capacity,
    Draws,
    LifeSpec,
    PassOverRates,
    Row,
    ScheduleDesign,
    prepare,
    project,
)
from bicentennial.score.bundle import twin_min

P0, P1 = "pair-000", "pair-001"


@pytest.fixture
def board_case():
    # Owner amendment 5: this hand-built SF pattern is not F3-V1's pattern.
    status = {
        (P0, "B0", 2): "OK",
        (P0, "B1", 2): "SYSTEM_FAILURE",
        (P0, "B0", 3): "SYSTEM_FAILURE",
        (P0, "B1", 3): "SYSTEM_FAILURE",
        (P1, "B0", 2): "OK",
        (P1, "B1", 2): "BLOCKED",
        (P1, "B0", 3): "OK",
        (P1, "B1", 3): "BLOCKED",
    }
    items = {
        ("S", P0, "X", 2): ((1000, 1000), (0, 1000)),
        ("S", P0, "X", 3): ((1000, -1000),),
        ("F", P0, "X", 2): ((0, 0), (-1000, 0)),
        ("F", P0, "X", 3): ((0, 0),),
        ("C", P0, "X", 2): ((1000, 1000), (1000, 1000)),
        ("C", P0, "X", 3): ((1000, 1000),),
        ("S", P1, "X", 2): ((1000, 1000), (1000, 1000)),
        ("S", P1, "X", 3): ((0, 0),),
        ("F", P1, "X", 2): ((0, 0), (0, 0)),
        ("F", P1, "X", 3): ((0, 0),),
        ("C", P1, "X", 2): ((1000, 1000), (1000, 1000)),
        ("C", P1, "X", 3): ((1000, 1000),),
    }
    return dict(status=status, control_failed=frozenset(), swap={P0: 3, P1: 3},
                block_of={P0: 0, P1: 1}, items=items, alloc={("X", 2): 2, ("X", 3): 1})


@pytest.fixture
def v1():
    # SPEC-B §B1.7 F3-V1, unchanged: S's first c2 arrival misses its bound.
    design = ScheduleDesign(
        (LifeSpec(P0, (1000, 1000, 1000), (1000, 1000), 2, 3, (0, 0), (0, 0)),),
        (Row("A", 3600), Row("B", 3600)), (2, 3), Capacity(1, 1),
        PassOverRates(0, 0), 0, system_rate=46_800,
    )
    draws = Draws({P0: ("A", "S", "B")}, ("A", "B"), {}, frozenset(), "fake", 0)
    prepared = prepare(design)
    return prepared, project(prepared, "base", draws)


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def test_all(board_case):
    board = assemble(**board_case)
    assert board == BoardInputs(
        {"X": (P0, P1)}, {("X", P0): Fraction(0)},
        {("X", P0): (Fraction(-100, 3), Fraction(100)),
         ("X", P1): (Fraction(0), Fraction(100))},
        {"X": Fraction(1, 2)}, {"X": "infrastructure"},
        {P0: 0, P1: 1}, {"X": 6}, {"X": 3},
    )
    with pytest.raises(FrozenInstanceError):
        board.pairs = {}


def test_pre_swap(board_case):
    board = assemble(**board_case, units="pre_swap")
    assert board == BoardInputs(
        {"X": (P0, P1)}, {("X", P0): Fraction(0)},
        {("X", P0): (Fraction(-50), Fraction(100)),
         ("X", P1): (Fraction(0), Fraction(100))},
        {"X": Fraction(1, 2)}, {"X": "infrastructure"},
        {P0: 0, P1: 1}, {"X": 4}, {"X": 2},
    )


def test_each_item_takes_its_own_branch_status(board_case):
    # pair-000 c2 is B0 OK and B1 SF, so (-1000, 1000) scores min(-1000, 0), not min(0, 1000).
    items = {**board_case["items"], ("S", P0, "X", 2): ((-1000, 1000), (-1000, 1000))}
    board = assemble(**{**board_case, "items": items}, units="pre_swap")
    assert board.scores == {("X", P0): Fraction(-100)}


def test_sf_item_rule():
    assert bundle_value(600, -1000, "SYSTEM_FAILURE", "OK") == -1000
    assert bundle_value(1000, 1000, "OK", "SYSTEM_FAILURE") == 0
    for other in STATUSES:
        assert bundle_value(600, -1000, "BLOCKED", other) is None
        assert bundle_value(600, -1000, other, "BLOCKED") is None


def test_twin_min_equivalence():
    for x0, x1, s0, s1 in product(
        (-1000, -250, 0, 375, 1000), (-1000, 0, 1000), STATUSES, STATUSES,
    ):
        items = [
            {"failure_class": None if status == "OK" else status,
             "score_milli": value if status == "OK" else
             0 if status == "SYSTEM_FAILURE" else None}
            for value, status in ((x0, s0), (x1, s1))
        ]
        assert bundle_value(x0, x1, s0, s1) == twin_min(*items)


@pytest.mark.parametrize("arm", ("F", "C"))
def test_control_failure_every_cell(board_case, arm):
    board_case["alloc"].update({("Y", c): n for (_, c), n in board_case["alloc"].copy().items()})
    board_case["items"].update({
        (a, pair, "Y", c): values
        for (a, pair, _, c), values in board_case["items"].copy().items()
    })
    before = assemble(**board_case)
    board_case["control_failed"] = frozenset({(arm, P0)})
    board = assemble(**board_case)
    assert board.controls == {
        (cell, P1): (Fraction(0), Fraction(100)) for cell in ("X", "Y")
    }
    assert board.scores == before.scores == {
        (cell, P0): Fraction(0) for cell in ("X", "Y")
    }
    assert board.coverage == before.coverage
    assert board.assigned == before.assigned
    assert board.blocked == before.blocked


def test_coverage_edge(board_case):
    board_case["alloc"] = {("Y", 2): 9, ("Y", 3): 1}
    board_case["items"] = {
        (arm, pair, cell, c): ((0, 0),) * n
        for arm in ARMS for pair in (P0, P1) for (cell, c), n in board_case["alloc"].items()
    }
    board_case["status"] = {key: "OK" for key in board_case["status"]}
    board_case["status"][P0, "B1", 3] = "BLOCKED"
    board = assemble(**board_case)
    assert board.assigned == {"Y": 20}
    assert board.blocked == {"Y": 1}
    assert board.coverage == {"Y": Fraction(19, 20)}
    assert board.shortfall == {"Y": None}
    board_case["status"][P1, "B1", 3] = "BLOCKED"
    board = assemble(**board_case)
    assert board.assigned == {"Y": 20}
    assert board.blocked == {"Y": 2}
    assert board.coverage == {"Y": Fraction(9, 10)}
    assert board.shortfall == {"Y": "infrastructure"}


def test_end_to_end_v1(v1):
    prepared, schedule = v1
    assert schedule.system == {
        (P0, branch, c): "SYSTEM_FAILURE" for branch in ("B0", "B1") for c in (2, 3)
    }
    alloc = {("X", 2): 1, ("X", 3): 1}
    items = {(arm, P0, cell, c): ((1000, 1000),) for arm in ARMS for cell, c in alloc}
    board = assemble_schedule(schedule, prepared, items, alloc)
    assert board == BoardInputs(
        {"X": (P0,)}, {("X", P0): Fraction(0)},
        {("X", P0): (Fraction(100), Fraction(100))},
        {"X": Fraction(1)}, {"X": None}, {P0: 0}, {"X": 2}, {"X": 0},
    )


def test_schedule_adapter_forwards_design_order_and_filter(board_case, v1):
    prepared, schedule = v1
    life = prepared.design.lives[0]
    prepared = replace(prepared, design=replace(
        prepared.design, lives=(replace(life, life=P1, swap=2), life),
    ))
    schedule = replace(schedule, system=board_case["status"],
                       control_failed=frozenset({("C", P0)}))
    board = assemble_schedule(schedule, prepared, board_case["items"],
                              board_case["alloc"], units="pre_swap")
    assert board == BoardInputs(
        {"X": (P1, P0)}, {("X", P0): Fraction(0)}, {},
        {"X": Fraction(1)}, {"X": None}, {P0: 1, P1: 0}, {"X": 2}, {"X": 0},
    )


def test_common_valid_control_bundles(board_case):
    board_case["status"] = {key: "OK" for key in board_case["status"]}
    board_case["status"][P0, "B1", 3] = "BLOCKED"
    board = assemble(**board_case)
    assert board.scores == {("X", P0): Fraction(50), ("X", P1): Fraction(200, 3)}
    assert board.controls == {
        ("X", P0): (Fraction(-50), Fraction(100)),
        ("X", P1): (Fraction(0), Fraction(100)),
    }
    assert board.blocked == {"X": 1}
    assert board.coverage == {"X": Fraction(5, 6)}


@pytest.mark.parametrize("empty", ("zero_alloc", "no_retained"))
def test_no_retained_bundles(board_case, empty):
    if empty == "zero_alloc":
        board_case["alloc"] = {key: 0 for key in board_case["alloc"]}
        board_case["items"] = {key: () for key in board_case["items"]}
    else:
        board_case["swap"] = {P0: 2, P1: 2}
    board = assemble(**board_case, units="pre_swap")
    assert board == BoardInputs(
        {"X": (P0, P1)}, {}, {}, {"X": Fraction(1)}, {"X": None},
        {P0: 0, P1: 1}, {"X": 0}, {"X": 0},
    )


def test_sorted_dict_keys_and_block_order(board_case):
    board_case["alloc"].update({("A", c): n for (_, c), n in board_case["alloc"].copy().items()})
    board_case["items"].update({
        (arm, pair, "A", c): values
        for (arm, pair, _, c), values in board_case["items"].copy().items()
    })
    board_case["block_of"] = {P1: 0, P0: 1}
    board = assemble(**board_case)
    permuted = {
        name: dict(reversed(tuple(value.items()))) if isinstance(value, dict) else value
        for name, value in board_case.items()
    }
    other = assemble(**permuted)
    assert board == other
    assert board.pairs == {"A": (P1, P0), "X": (P1, P0)}
    for field in board.__dataclass_fields__:
        values = getattr(board, field)
        assert list(values) == sorted(values) == list(getattr(other, field))
    assert all(type(value) is Fraction for value in board.scores.values())
    assert all(type(value) is Fraction for pair in board.controls.values() for value in pair)
    assert all(type(value) is Fraction for value in board.coverage.values())


@pytest.mark.parametrize("units", ("post_swap", "", None))
def test_bad_units(board_case, units):
    with rejects('units must be "all" or "pre_swap"'):
        assemble(**board_case, units=units)


@pytest.mark.parametrize("key, count", (
    (("X", 2), -1), (("X", 2), True), (("X", 2), Fraction(2)),
    (("X", 2), "2"), ((7, 2), 2),
))
def test_bad_alloc_entry(board_case, key, count):
    board_case["alloc"][key] = count
    with rejects(f"bad alloc entry: {key}"):
        assemble(**board_case)


@pytest.mark.parametrize("change", ("missing", "extra", "whole_pair", "malformed"))
def test_items_cover_every_unit(board_case, change):
    if change == "missing":
        del board_case["items"]["F", P0, "X", 2]
    elif change == "extra":
        board_case["items"]["other", P0, "X", 2] = ((0, 0), (0, 0))
    elif change == "malformed":
        board_case["items"][None] = ()
    else:
        board_case["items"] = {
            key: value for key, value in board_case["items"].items() if key[1] != P1
        }
    with rejects("items must cover every (arm, pair, cell, checkpoint) unit"):
        assemble(**board_case)


@pytest.mark.parametrize("count", (0, 1, 3))
def test_bad_unit_length(board_case, count):
    key = ("S", P0, "X", 2)
    board_case["items"][key] = ((0, 0),) * count
    with rejects(f"unit {key} has {count} bundles, alloc says 2"):
        assemble(**board_case)


@pytest.mark.parametrize("arm", ARMS)
@pytest.mark.parametrize("index", (0, 1))
@pytest.mark.parametrize("value", (-1001, 1001, True, False, Fraction(1), "0", None))
def test_bad_item_score(board_case, arm, index, value):
    pair = [0, 0]
    pair[index] = value
    board_case["items"][arm, P0, "X", 2] = (tuple(pair), (0, 0))
    with rejects("item scores must be ints in [-1000, 1000]"):
        assemble(**board_case)


@pytest.mark.parametrize("branch", ("B0", "B1"))
@pytest.mark.parametrize("value", ("missing", "FAILED", None))
def test_bad_or_missing_status(board_case, branch, value):
    key = (P0, branch, 3)
    if value == "missing":
        del board_case["status"][key]
    else:
        board_case["status"][key] = value
    # Validation covers even checkpoints excluded by the requested unit filter.
    with rejects(f"bad or missing status: {key}"):
        assemble(**board_case, units="pre_swap")


@pytest.mark.parametrize("fields", (("swap",), ("block_of",), ("swap", "block_of")))
def test_missing_pair_metadata(board_case, fields):
    for field in fields:
        del board_case[field][P1]
    with rejects("swap and block_of must name every pair"):
        assemble(**board_case)
