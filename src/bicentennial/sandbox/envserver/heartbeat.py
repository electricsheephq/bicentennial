"""Uniform simulated-time opportunities; delivery belongs to the harness."""


def ticks(t_start: int, t_end: int, interval_s: int) -> list[int]:
    if any(type(v) is not int for v in (t_start, t_end, interval_s)):
        raise ValueError("integer times and interval required")
    if interval_s <= 0 or t_end < t_start:
        raise ValueError("positive interval and ordered times required")
    return list(range(t_start, t_end, interval_s))
