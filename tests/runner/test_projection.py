"""Exact workload goldens and keyed arithmetic checks for S6's partial lane."""

from dataclasses import replace
from fractions import Fraction

import pytest

from bicentennial.canon import canon
from bicentennial.keyed import uniform_int
from bicentennial.runner.projection import (
    LIFE_BOUND_MS,
    PAUSE_A,
    UNDETERMINED,
    W_MAX_MS,
    Cost,
    Lane,
    P,
    Terms,
    board,
    breakeven,
    cmax,
    cut_order,
    fit,
    lane_ms,
    n_keep,
    role_costs,
    stats,
    study,
)

LANE = Lane("sol", 180, 20, 1)
GOLDEN = Terms(R=Cost(requests=1330), e_probe=Cost(requests=4), critical_path_ms=0)


def test_preregistered_goldens():
    assert board(GOLDEN, 48).requests == 263700
    assert study(GOLDEN, 48, 8).requests == 166488
    cut = replace(GOLDEN, b=100)
    assert board(cut, 48).requests == 215700
    assert study(cut, 48, 4).requests == 70924
    measured = fit(GOLDEN, LANE)
    assert measured["board"]["rate_mh"] == 24417
    assert measured["board"]["with_a_mh"] == 30521
    assert measured["board"]["fits"] is True
    assert breakeven(GOLDEN, LANE, n_L=48, n_rob=8) == 82869
    assert breakeven(GOLDEN, LANE, n_L=48, n_rob=8, bound_ms=LIFE_BOUND_MS, a=0) == 11589
    assert breakeven(cut, LANE, n_L=48, n_rob=4, bound_ms=LIFE_BOUND_MS, a=0) == 47069
    assert [n_keep(n) for n in (48, 24, 20)] == [12, 6, 6]
    canon(measured)


def test_occupancy_is_not_inferred_from_chain_lower_bound():
    for bound in (0, LIFE_BOUND_MS, LIFE_BOUND_MS + 1):
        result = fit(replace(GOLDEN, critical_path_ms=bound), LANE)
        assert result["fits"] == result["life"]["fits"] == UNDETERMINED
        assert result["life"]["lower_bound_exceeds_bound"] == (bound > LIFE_BOUND_MS)
        assert result["missing"] == ["C_learn", "C_erase"]
        canon(result)
    cuts = cut_order(GOLDEN, LANE)
    assert cuts["first_fit"] is None
    assert cuts["first_work_fit"] == "none"
    assert [(r["b"], r["n_rob"], r["n_L"]) for r in cuts["rows"]] == [
        (150, 8, 48), (100, 8, 48), (100, 4, 48), (100, 4, 24)]
    canon(cuts)


def test_lane_uses_larger_capacity_bound():
    assert lane_ms(Cost(requests=6, upstream_ms=10), LANE) == 2000
    assert lane_ms(Cost(requests=1, upstream_ms=100_000), LANE) == 5000
    assert lane_ms(Cost(requests=6, upstream_ms=100_000), replace(LANE, accounts=2)) == 2500


def test_cost_exact_rounding_and_component_max():
    a = Cost(requests=Fraction(1, 2), held_ms=2)
    b = Cost(requests=1, wall_ms=3)
    assert (a + b).requests == Fraction(3, 2)
    assert (3 * a).held_ms == 6
    assert cmax(a, b) == Cost(requests=1, wall_ms=3, held_ms=2)
    assert a.to_obj()["requests"] == 0
    assert all(type(v) is int for v in (a * Fraction(1, 3)).to_obj().values())
    canon((a * Fraction(1, 3)).to_obj())
    with pytest.raises(TypeError):
        Cost(requests=1.0)
    with pytest.raises(TypeError):
        a * 0.5


def test_study_terms_are_charged_per_study_life_and_rc_is_capped():
    added = replace(GOLDEN, C_learn=Cost(requests=7), C_erase=Cost(requests=11))
    assert study(added, 48, 8).requests - study(GOLDEN, 48, 8).requests == 8 * 18
    assert fit(added, LANE)["missing"] == []
    assert board(replace(GOLDEN, R_cap=Cost()), 48) == board(GOLDEN, 48)
    assert P(GOLDEN).requests == 1200
    assert study(replace(GOLDEN, R_B=Cost(requests=1500)), 48, 8).requests > study(GOLDEN, 48, 8).requests


def test_nearest_rank_stats_and_empty_input():
    assert stats([]) == {"n": 0}
    assert stats([1, 2, 3, 4]) == dict(n=4, mean=2, p50=2, p90=4, min=1, max=4)
    assert stats([99]) == dict(n=1, mean=99, p50=99, p90=99, min=99, max=99)
    with pytest.raises(TypeError):
        stats([1.0])


def test_role_costs_counts_sent_attempts_holds_and_integer_usage():
    rows = [dict(type="request", attempt_id="a", role="replay_main", subrole="cursor", upstream=[
        dict(role="write_turn", resp="live", diagnostics=[
            dict(kind="try", sent=True, t_ms=3000), dict(kind="try", sent=False, t_ms=999),
            dict(kind="hold", held_ms=500)]),
        dict(role="replay_main", resp="script", diagnostics=[])]),
        dict(type="request", attempt_id="unrelated", upstream=[]),
        dict(type="session", attempt_id="a")]
    blobs = {"live": {"usage": {"prompt_tokens": 12, "completion_tokens": 3}}, "script": {}}
    costs = role_costs(rows, blobs, {"a": 2})
    assert costs == {2: {"write_turn": Cost(requests=1, upstream_ms=3000, held_ms=500,
                                           input_tokens=12, output_tokens=3), "replay_main/cursor": Cost()}}
    blobs["live"]["usage"] = {"prompt_tokens": True, "completion_tokens": "3"}
    assert role_costs(rows, blobs, {"a": 2})[2]["write_turn"].input_tokens == 0


def test_keyed_exact_arithmetic_and_breakeven_boundary_256_cases():
    for case in range(256):
        def draw(name, lo, hi, case=case):
            return uniform_int("6", ("s6", "projection", str(case)), 0, name, lo, hi)

        requests, service = draw("requests", 1, 2000), draw("service", 1, 60_000)
        lane = Lane("test", draw("rate", 1, 240), draw("concurrency", 1, 24), draw("accounts", 1, 2))
        terms = Terms(R=Cost(requests=requests, upstream_ms=requests * service),
                      e_probe=Cost(requests=1, upstream_ms=service), critical_path_ms=0)
        before = study(terms, 48, 8)
        limit = breakeven(terms, lane, n_L=48, n_rob=8)
        mean = Fraction(before.upstream_ms, before.requests)
        at = before + Cost(requests=limit * 8, upstream_ms=mean * limit * 8)
        over = at + Cost(requests=8, upstream_ms=mean * 8)
        if lane_ms(before, lane) * (1 + PAUSE_A) <= W_MAX_MS:
            assert lane_ms(at, lane) * (1 + PAUSE_A) <= W_MAX_MS
            assert lane_ms(over, lane) * (1 + PAUSE_A) > W_MAX_MS
        else:
            assert limit == 0
        canon(fit(terms, lane))
