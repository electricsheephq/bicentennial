"""Deterministic relative dates and channel stamps in an exact IANA zone, locale-free."""

import email.utils
from datetime import datetime
from functools import cache
from zoneinfo import ZoneInfo, available_timezones

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_zones = cache(available_timezones)


def zone(tz: str) -> ZoneInfo:
    # Exact membership, as K12's check_stream: a case-insensitive filesystem accepts "europe/paris".
    if type(tz) is not str or tz not in _zones():
        raise ValueError(f"tz must be an IANA zone name: {tz!r}")
    return ZoneInfo(tz)


def _local(t: int, tz: str) -> datetime:
    if type(t) is not int:
        raise ValueError("times are integer POSIX seconds")
    return datetime.fromtimestamp(t, zone(tz))


def relative_date(anchor_t: int, target_t: int, tz: str) -> str:
    """Calendar-day difference in the zone, never seconds divided by 86400."""
    target = _local(target_t, tz).date()
    d = (target - _local(anchor_t, tz).date()).days
    if -1 <= d <= 1:
        return ("yesterday", "today", "tomorrow")[d + 1]
    weekday = WEEKDAYS[target.weekday()]
    if 2 <= d <= 6:
        return f"on {weekday}"
    if 7 <= d <= 13:
        return f"next {weekday}"
    if -6 <= d <= -2:
        return f"last {weekday}"
    return f"in {d} days" if d > 0 else f"{-d} days ago"


def window(anchor_t: int, open_t: int, close_t: int, tz: str) -> str:
    """Both bounds as local HH:MM with their relative dates; a shared local date is said once."""
    start, end = _local(open_t, tz), _local(close_t, tz)
    if start.date() == end.date():
        return f"between {start:%H:%M} and {end:%H:%M} {relative_date(anchor_t, open_t, tz)}"
    return (f"from {start:%H:%M} {relative_date(anchor_t, open_t, tz)}"
            f" until {end:%H:%M} {relative_date(anchor_t, close_t, tz)}")


def channel_stamp(t: int, tz: str, style: str) -> str:
    """The offset is always printed, so a repeated fall-back hour stays unambiguous."""
    d = _local(t, tz)
    if style == "chat":
        return f"[{d:%Y-%m-%d %H:%M} {d:%z}]"
    if style == "mail":
        return "Date: " + email.utils.format_datetime(d)
    if style == "log":
        return d.isoformat(timespec="seconds")
    if style == "none":
        return ""
    raise ValueError(f"unknown stamp style: {style!r}")
