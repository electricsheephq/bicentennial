"""Observed drain barriers; an unsettled result is SYSTEM_FAILURE (ERRATA E6)."""

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SettleResult:
    kind: str
    settled: bool
    polls: int
    reason: str
    waited_ms: int  # volatile receipt only


def settle(entry, observe=None, *, poll_s=0.25, monotonic=time.monotonic, sleep=time.sleep):
    kind, bound = entry["settle"]["kind"], entry["settle"]["bound_s"]
    if kind == "none":
        if observe is not None:
            raise ValueError("none settle cannot observe")
        return SettleResult(kind, True, 0, "no_background_work", 0)
    if kind != "hook" or observe is None:
        raise ValueError("hook settle requires an observer")
    if poll_s <= 0:
        raise ValueError("poll_s must be positive")
    t0, polls = monotonic(), 0
    while True:
        polls += 1
        drained = observe()
        if type(drained) is not bool:
            raise TypeError("drain observation must be bool")
        elapsed = monotonic() - t0
        if drained and elapsed <= bound:
            return SettleResult(kind, True, polls, "drained", int(elapsed * 1000))
        if elapsed >= bound:
            return SettleResult(kind, False, polls, "bound_reached", int(elapsed * 1000))
        sleep(poll_s)


def threads_drained(names, enumerate=threading.enumerate):
    """Observer for the in-process host: only named live threads count."""
    return lambda: not any(t.name in names and t.is_alive() for t in enumerate())
