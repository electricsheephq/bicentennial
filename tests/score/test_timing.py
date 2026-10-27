"""S01: Tuesday timing of the first execution (PREREG §3 Tuesday table)."""

from fractions import Fraction

import pytest

from bicentennial.canon import milli
from bicentennial.score.timing import check_window, tuesday_timing

WINDOW = (1000, 1100)  # W = 100 simulated seconds


@pytest.mark.parametrize("first_t,expected", [
    (999, ("early", -250)),
    (0, ("early", -250)),
    (1000, ("on_time", 1000)),  # open_t
    (1050, ("on_time", 1000)),
    (1100, ("on_time", 1000)),  # close_t
    (1101, ("late", 995)),  # close_t + 1: 1 - 1/200
    (1200, ("late", 500)),  # halfway through the 2W horizon
    (1299, ("late", 5)),
    (1300, ("late", 0)),  # close_t + 2W: the end of the late horizon
    (1301, ("late", 0)),  # beyond the horizon stays 0
    (10 ** 9, ("late", 0)),
])
def test_boundaries(first_t, expected):
    assert tuesday_timing(first_t, WINDOW) == expected


def test_late_decay_matches_the_linear_formula_inside_the_horizon():
    open_t, close_t = WINDOW
    width = close_t - open_t
    for first_t in range(close_t + 1, close_t + 2 * width):
        cls, score = tuesday_timing(first_t, WINDOW)
        assert cls == "late"
        assert score == milli(1 - Fraction(first_t - close_t, 2 * width))
        assert 0 <= score < 1000


def test_rounding_goes_through_canon_milli_ties_to_even():
    window = (0, 8)  # 2W = 16, so each late second is 62.5 milli
    assert tuesday_timing(9, window) == ("late", 938)  # 937.5 -> 938
    assert tuesday_timing(11, window) == ("late", 812)  # 812.5 -> 812
    assert tuesday_timing(13, window) == ("late", 688)  # 687.5 -> 688
    assert tuesday_timing(15, window) == ("late", 562)  # 562.5 -> 562


def test_a_one_second_late_action_on_a_long_window_can_round_to_1000_and_stays_late():
    assert tuesday_timing(2001, (1000, 2000)) == ("late", 1000)  # 999.5 -> 1000, still late


@pytest.mark.parametrize("window", [
    (5, 5), (6, 5), [0, 10], (0,), (0, 10, 20), (0.0, 10), (0, True), ("0", 10), None,
])
def test_invalid_windows_are_refused(window):
    with pytest.raises(ValueError):
        tuesday_timing(5, window)
    with pytest.raises(ValueError):
        check_window(window)


@pytest.mark.parametrize("first_t", [None, 1.5, True, "1000"])
def test_first_execution_must_be_integer_seconds(first_t):
    with pytest.raises(ValueError):
        tuesday_timing(first_t, WINDOW)


def test_window_length():
    assert check_window(WINDOW) == 100
