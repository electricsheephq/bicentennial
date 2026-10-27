"""Tuesday timing of the first execution (PREREG §3 Tuesday table, DESIGN §7.3)."""

from fractions import Fraction

from bicentennial.canon import milli


def _integer(value, label):
    if type(value) is not int:
        raise ValueError(f"{label}: integer simulated seconds required")


def check_window(window) -> int:
    """Return the window length W of (open_t, close_t), or raise ValueError."""
    if type(window) is not tuple or len(window) != 2:
        raise ValueError("window: (open_t, close_t) required")
    open_t, close_t = window
    _integer(open_t, "open_t")
    _integer(close_t, "close_t")
    if open_t >= close_t:
        raise ValueError("window: open_t must precede close_t")
    return close_t - open_t


def tuesday_timing(first_t, window) -> tuple[str, int]:
    """Class and score of the first execution: early -250, on time +1000, late decaying to 0."""
    width = check_window(window)
    _integer(first_t, "first_t")
    open_t, close_t = window
    if first_t < open_t:
        return "early", -250
    if first_t <= close_t:
        return "on_time", 1000
    # Linear decay from +1 at close_t to 0 at the end of the late horizon, 2W after close.
    return "late", milli(max(0, 1 - Fraction(first_t - close_t, 2 * width)))
