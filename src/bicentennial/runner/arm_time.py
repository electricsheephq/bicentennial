"""Reconstruct each system arm's isolated schedule from measured unit spans."""

import heapq
import math


def units_json_inputs(data):
    """Return arm-time inputs from units.json's monotonic millisecond offsets.

    Wall endpoints remain receipt cross-references and do not time an arm.
    """
    rows = [dict({k: v for k, v in row.items() if k != "slots"},
                 start_ms=row["t_start_ms"], end_ms=row["t_end_ms"])
            for row in data["units"]]
    return data["slots"], rows, 0, data["t_end_ms"]


def calculate_arm_times(slots, timings, start_ms, end_ms):
    """Return millisecond budgets and their inputs; the floor counts in no arm, only beside them.

    The no-memory floor is a cached control (PREREG §6, RING0 §14.8 erratum), so an arm
    replays only its own units in admission order: descending predicted time, then
    card order. Start order is zero-based across the whole run; equal starts use
    card order. Replay queues work immediately on the earliest
    free slot, without reproducing gaps caused by the other arms. Intervals within
    the clock tolerance retain their full replay duration; their union is clipped
    to the measured run when computing time outside units.
    """
    if type(slots) is not int or slots < 1:
        raise ValueError("invalid slots")
    if not all(math.isfinite(t) for t in (start_ms, end_ms)) or end_ms < start_ms:
        raise ValueError("invalid run interval")
    timings = [dict(row) for row in timings]
    indices = set()
    for row in timings:
        predicted, index = row.get("predicted_s"), row.get("card_index")
        if (type(predicted) not in (int, float) or not math.isfinite(predicted) or predicted < 0
                or type(index) is not int or index in indices):
            raise ValueError("invalid unit order")
        indices.add(index)
        start, end = row["start_ms"], row["end_ms"]
        if not all(math.isfinite(t) for t in (start, end)) or end < start:
            raise ValueError("invalid unit interval")
        if type(row["slot"]) is not int or not 0 <= row["slot"] < slots:
            raise ValueError("invalid unit slot")
        if start < start_ms - 1000 or end > end_ms + 1000:
            raise ValueError("unit interval outside run")

    covered, right = 0, start_ms
    for row in sorted(timings, key=lambda row: row["start_ms"]):
        left, end = max(start_ms, row["start_ms"]), min(end_ms, row["end_ms"])
        covered += max(0, end - max(left, right))
        right = max(right, end)
    elapsed = end_ms - start_ms
    outside = elapsed - covered
    ordered = [dict(arm=row["arm"], life=row["life"], branch=row["branch"],
                    predicted_s=row["predicted_s"], card_index=row["card_index"],
                    start_order=order, duration_ms=row["end_ms"] - row["start_ms"])
               for order, row in enumerate(sorted(timings, key=lambda row: (row["start_ms"], row["card_index"])))]
    ordered.sort(key=lambda row: (-row["predicted_s"], row["card_index"]))

    def replay(rows):
        available = [0] * slots
        for row in rows:
            free = heapq.heappop(available)
            heapq.heappush(available, free + row["duration_ms"])
        return max(available)

    arms = {}
    for arm in sorted({row["arm"] for row in timings} - {"no_memory"}):
        units = [row for row in ordered if row["arm"] == arm]
        length = replay(units)
        arms[arm] = dict(arm_time_ms=length + outside, replay_ms=length,
                         slots=slots, units=units, outside_ms=outside, elapsed_ms=elapsed)
    return dict(arms=arms, floor_replay_ms=replay([row for row in ordered if row["arm"] == "no_memory"]),
                start_ms=start_ms, end_ms=end_ms, timings=timings)
