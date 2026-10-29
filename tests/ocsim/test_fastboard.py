"""SPEC-C C5 hand values and reference-board equivalence."""

import re
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from itertools import product

import pytest

from bicentennial.ocsim import board, drift, fastboard, locate, model, schedule

P, Q = "pair-000", "pair-001"
PAIRS = (P, Q)
ALLOC = {("T", 2): 1, ("T", 3): 2, ("X", 2): 2, ("X", 3): 1}


@pytest.fixture(scope="module")
def params():
    return model.LatentParams(tuple(
        model.CellModel(k, (-1000, 0, 1000), (-0.5, 0.5), -200., 600., 10., 10.)
        for k in ("T", "X")
    ), 0.2, 0.1, 0.5, 0.2)


@pytest.fixture(scope="module")
def solver(params):
    return locate.table_solver(params)


@pytest.fixture(scope="module")
def prepared():
    return schedule.prepare(schedule.ScheduleDesign(
        (schedule.LifeSpec(P, (1000, 2000, 1000), (2000, 1000), 2, 3, (1000, 0), (0, 0)),
         schedule.LifeSpec(Q, (1000, 1000, 1000), (1000, 1000), 2, 3, (0, 0), (0, 0))),
        (schedule.Row("A", 3600),), (2, 3), schedule.Capacity(2, 2),
        schedule.PassOverRates(0, 0), 0,
    ))


def fake_draws(stops=0):
    patterns = ({}, {("S", P): ("failed", 3), ("A", Q): ("blocked", 2)},
                {("A", P): ("failed", 1)})
    return schedule.Draws(
        {p: ("A", "S") for p in PAIRS}, ("A",),
        patterns[stops],
        frozenset(), "fake", 1,
    )


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def zero_solver(cell, target):
    return 0.0


@pytest.mark.parametrize("s0,s1,expected", (
    ("OK", "OK", -1000), ("SYSTEM_FAILURE", "OK", 0),
    ("OK", "SYSTEM_FAILURE", -1000), ("SYSTEM_FAILURE", "SYSTEM_FAILURE", 0),
    *(("BLOCKED", other, None) for other in schedule.STATUSES),
    *((other, "BLOCKED", None) for other in ("OK", "SYSTEM_FAILURE")),
))
def test_system_hand(params, s0, s1, expected):
    lat = {(P, "X", 2): {"S": ((0.7, -0.2), (-0.6, 0.9), (0.1, 0.2))}}
    status = {(P, "B0", 2): s0, (P, "B1", 2): s1}
    assert fastboard.system_sums(params, lat, {("S", P, "X", 2): 0.}, status,
                                 zero_solver, alloc={("X", 2): 3}) == {(P, "X", 2): expected}
    if expected is None or (s0 == s1 == "SYSTEM_FAILURE"):
        def no_solve(*args):
            pytest.fail("unneeded solve")
        fastboard.system_sums(params, lat, {("S", P, "X", 2): 0.}, status,
                              no_solve, alloc={("X", 2): 3})


def test_control_hand(params):
    lat = {(P, "X", 2): {"F": ((0.7, -0.2), (-0.6, 0.9), (0.1, 0.2))}}
    assert fastboard.control_sums(params, lat, {("F", P, "X", 2): 0.}, zero_solver,
                                  alloc={("X", 2): 3}) == {("F", P, "X", 2): -1000}


@pytest.fixture
def sums():
    alloc = {("X", 2): 2, ("X", 3): 1}
    control = {(a, p, k, c): (1000 * n if a == "C" else
                             -1000 if (p, c) == (P, 2) else 0)
               for a in ("F", "C") for p in PAIRS for (k, c), n in alloc.items()}
    system = {(p, k, c): 0 if p == P else None for p in PAIRS for k, c in alloc}
    return dict(control=control, system=system, control_failed=frozenset(),
                swap={P: 3, Q: 3}, alloc=alloc, pairs=PAIRS)


@pytest.mark.parametrize("units,n,blocked,floor", (
    ("all", 6, 3, Fraction(-100, 3)), ("pre_swap", 4, 2, Fraction(-50)),
))
def test_b3_hand(sums, units, n, blocked, floor):
    cs = fastboard.cell_sums(**sums, units=units)
    result = fastboard.to_board_inputs(cs, {P: 0, Q: 1})
    assert result.scores == {("X", P): Fraction(0)}
    assert result.controls == {("X", P): (floor, Fraction(100)),
                               ("X", Q): (Fraction(0), Fraction(100))}
    assert cs.assigned == {"X": n}
    assert cs.blocked == {"X": blocked}
    assert cs.coverage == {"X": Fraction(1, 2)}
    assert cs.shortfall == {"X": "infrastructure"}
    assert cs.entries["X", Q].n_control == (3 if units == "all" else 2)
    with pytest.raises(FrozenInstanceError):
        cs.pairs = ()
    with pytest.raises(FrozenInstanceError):
        cs.entries["X", P].s_sum = 1


@pytest.mark.parametrize("arm", ("F", "C"))
def test_control_failure(sums, arm):
    sums["alloc"].update({("Y", c): n for (_, c), n in sums["alloc"].copy().items()})
    sums["control"].update({(a, p, "Y", c): n
                            for (a, p, _, c), n in sums["control"].copy().items()})
    sums["system"].update({(p, "Y", c): n for (p, _, c), n in sums["system"].copy().items()})
    sums["control_failed"] = frozenset({(arm, P)})
    cs = fastboard.cell_sums(**sums, units="all")
    assert not cs.entries["X", P].control_valid
    result = fastboard.to_board_inputs(cs, {P: 0, Q: 1})
    assert result.scores == {(k, P): Fraction(0) for k in ("X", "Y")}
    assert set(result.controls) == {(k, Q) for k in ("X", "Y")}


def test_coverage_and_empty(sums):
    sums["alloc"] = {("X", 2): 9, ("X", 3): 1}
    sums["system"] = {(p, "X", c): 0 for p in PAIRS for c in (2, 3)}
    sums["system"][P, "X", 3] = None
    cs = fastboard.cell_sums(**sums, units="all")
    assert cs.coverage["X"] == Fraction(19, 20)
    assert cs.shortfall["X"] is None
    sums["system"][Q, "X", 3] = None
    cs = fastboard.cell_sums(**sums, units="all")
    assert cs.coverage["X"] == Fraction(9, 10)
    assert cs.shortfall["X"] == "infrastructure"
    sums["swap"] = {p: 2 for p in PAIRS}
    cs = fastboard.cell_sums(**sums, units="pre_swap")
    assert cs.coverage["X"] == 1
    assert not fastboard.to_board_inputs(cs, {P: 1, Q: 0}).controls
    assert cs.pairs == PAIRS


def targets_for(params, sch, expected, case, scope):
    return drift.drifted_targets(
        {c.cell: (c.f0, c.c0) for c in params.cells}, expected,
        schedule.unit_times(sch), sch.post_swap, (2, 3), case, scope,
        t1_ms=sch.t1_ms, step_start_ms=sch.block_first[1],
    )


def test_reference_equivalence(params, solver, prepared):
    alternatives = ((drift.LITERAL, "all"), (drift.ALL_UNITS, "all"),
                    (drift.LITERAL, "pre_swap"), (drift.SWAP_GATE, "all"))
    cases = tuple(c for c in drift.DRIFT_CASES if c.name in ("none", "step+5", "cycle90"))
    for rep in range(20):
        lat = model.bundle_latents(params, ALLOC, PAIRS, "fastboard-fakes", rep)
        eff = model.life_effects(params, PAIRS, "fastboard-fakes", rep)
        expected = model.expected_units(params, eff, {"T": 0, "X": 0})
        for stops, kind, case, (scope, units) in product(
            (0, 1, 2), schedule.KINDS, cases, alternatives,
        ):
            sch = schedule.project(prepared, kind, fake_draws(stops))
            targets = targets_for(params, sch, expected, case, scope)
            fc = {k: v for k, v in targets.items() if k[0] != "S"}
            st = {k: v for k, v in targets.items() if k[0] == "S"}
            control = fastboard.control_sums(params, lat, fc, solver, alloc=ALLOC)
            system = fastboard.system_sums(params, lat, st, sch.system, solver, alloc=ALLOC)
            cs = fastboard.cell_sums(control, system, sch.control_failed, {p: 3 for p in PAIRS},
                                     ALLOC, PAIRS, units=units)
            items = model.sample_items(params, targets, ALLOC, PAIRS,
                                       "fastboard-fakes", rep, solver=solver)
            assert fastboard.to_board_inputs(cs, {P: 0, Q: 1}) == board.assemble_schedule(
                sch, prepared, items, ALLOC, units=units)
            # Compare the monotone-min optimisation against both item lookups.
            assert control == {k: sum(min(pair) for pair in items[k]) for k in fc}



def test_board_pairs_in_block_order(params, solver, prepared):
    # cell_sums keeps the caller's pair order; the board must still list pairs in block order.
    sch = schedule.project(prepared, "base", fake_draws())
    lat = model.bundle_latents(params, ALLOC, PAIRS, "fastboard-fakes", 0)
    eff = model.life_effects(params, PAIRS, "fastboard-fakes", 0)
    targets = targets_for(params, sch, model.expected_units(params, eff, {"T": 0, "X": 0}),
                          drift.DRIFT_CASES[0], drift.LITERAL)
    fc = {k: v for k, v in targets.items() if k[0] != "S"}
    st = {k: v for k, v in targets.items() if k[0] == "S"}
    control = fastboard.control_sums(params, lat, fc, solver, alloc=ALLOC)
    system = fastboard.system_sums(params, lat, st, sch.system, solver, alloc=ALLOC)
    cs = fastboard.cell_sums(control, system, sch.control_failed, {p: 3 for p in PAIRS},
                             ALLOC, (Q, P), units="all")
    assert cs.pairs == (Q, P)
    result = fastboard.to_board_inputs(cs, {P: 0, Q: 1})
    assert set(result.pairs.values()) == {(P, Q)}
    items = model.sample_items(params, targets, ALLOC, PAIRS, "fastboard-fakes", 0, solver=solver)
    assert result == board.assemble_schedule(sch, prepared, items, ALLOC, units="all")
    assert set(fastboard.to_board_inputs(cs, {P: 1, Q: 0}).pairs.values()) == {(Q, P)}

def test_crn_and_scope_splitting(params, solver, prepared):
    sch = schedule.project(prepared, "base", fake_draws())
    eff = model.life_effects(params, PAIRS, "crn", 0)
    expected = model.expected_units(params, eff, {"T": 0, "X": 0})
    for scope, case in product((drift.LITERAL, drift.ALL_UNITS, drift.SWAP_GATE), drift.DRIFT_CASES):
        fc = {k: v for k, v in expected.items() if k[0] != "S"}
        st = {k: v for k, v in expected.items() if k[0] == "S"}
        assert (targets_for(params, sch, fc, case, scope)
                | targets_for(params, sch, st, case, scope)) == targets_for(
                    params, sch, expected, case, scope)
    lat = model.bundle_latents(params, ALLOC, PAIRS, "crn", 0)
    targets = targets_for(params, sch, expected, drift.DRIFT_CASES[0], drift.LITERAL)
    fc = {k: v for k, v in targets.items() if k[0] != "S"}
    controls = fastboard.control_sums(params, lat, fc, solver, alloc=ALLOC)
    results = []
    for margin in (0, 10):
        exp = model.expected_units(params, eff, {"T": margin, "X": margin})
        st = {k: v for k, v in targets_for(params, sch, exp, drift.DRIFT_CASES[0],
                                         drift.LITERAL).items() if k[0] == "S"}
        ss = fastboard.system_sums(params, lat, st, sch.system, solver, alloc=ALLOC)
        cs = fastboard.cell_sums(controls, ss, frozenset(), {p: 3 for p in PAIRS},
                                 ALLOC, PAIRS, units="all")
        results.append(fastboard.to_board_inputs(cs, {P: 0, Q: 1}))
    assert results[0].controls == results[1].controls


@pytest.mark.parametrize("arm", ("F", "C", "S"))
@pytest.mark.parametrize("change", ("unit", "arm", "short", "long", "off_alloc"))
@pytest.mark.parametrize("state", ("OK", "SYSTEM_FAILURE", "BLOCKED"))
def test_latent_validation(params, arm, change, state):
    key, unit = (arm, P, "X", 2), (P, "X", 2)
    lat = {unit: {arm: ((0., 0.),) * 2}}
    alloc = {("X", 2): 2}
    if change == "unit":
        lat = {}
    elif change == "arm":
        lat[unit] = {}
    elif change in ("short", "long"):
        n = 1 if change == "short" else 3
        lat[unit][arm] = ((0., 0.),) * n
    else:
        alloc = {}
    message = (f"missing latents: {key}" if change in ("unit", "arm") else
               f"bad alloc or target key: {key}" if change == "off_alloc" else
               f"unit {unit} has {len(lat[unit][arm])} latents, alloc says 2")
    with rejects(message):
        if arm == "S":
            fastboard.system_sums(params, lat, {key: 0.},
                                  {(P, b, 2): state for b in ("B0", "B1")},
                                  zero_solver, alloc=alloc)
        else:
            fastboard.control_sums(params, lat, {key: 0.}, zero_solver, alloc=alloc)


def test_other_validation(params, sums):
    with rejects("control targets must be F or C units"):
        fastboard.control_sums(params, {}, {("S", P, "X", 2): 0.}, zero_solver, alloc={})
    with rejects("system targets must be S units"):
        fastboard.system_sums(params, {}, {("F", P, "X", 2): 0.}, {}, zero_solver, alloc={})
    for bad in (None, "FAILED", "missing"):
        for branch in ("B0", "B1"):
            status = {(P, b, 2): "OK" for b in ("B0", "B1")}
            if bad == "missing":
                del status[P, branch, 2]
            else:
                status[P, branch, 2] = bad
            with rejects(f"bad or missing status: {(P, branch, 2)}"):
                fastboard.system_sums(params, {(P, "X", 2): {"S": ()}},
                                      {("S", P, "X", 2): 0.}, status, zero_solver,
                                      alloc={("X", 2): 0})
    with rejects('units must be "all" or "pre_swap"'):
        fastboard.cell_sums(**sums, units="post_swap")
    for arm in ("F", "C", "S"):
        changed = dict(sums)
        field = "system" if arm == "S" else "control"
        changed[field] = dict(changed[field])
        key = (P, "X", 3) if arm == "S" else (arm, P, "X", 3)
        del changed[field][key]
        with rejects(f"missing unit sum: {key}"):
            fastboard.cell_sums(**changed, units="pre_swap")
    with rejects("swap and block_of must name every pair"):
        fastboard.cell_sums(**{**sums, "swap": {P: 3}}, units="all")
    cs = fastboard.cell_sums(**sums, units="all")
    with rejects("swap and block_of must name every pair"):
        fastboard.to_board_inputs(cs, {P: 0})
    reverse = replace(cs, entries=dict(reversed(tuple(cs.entries.items()))))
    assert fastboard.to_board_inputs(cs, {P: 0, Q: 1}) == fastboard.to_board_inputs(
        reverse, {Q: 1, P: 0})
