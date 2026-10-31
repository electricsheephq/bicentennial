"""Pure checkpoint dispatch for probe-only arms (PREREG-v0.4 §§6, 11)."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from bicentennial.keyed import draw
from bicentennial.world import unit

DISPATCH_DRAW_LABEL = "dispatch"
PassOverCause = Literal["replay_stopped", "life_bound", "start_window"]
NonArrivalKind = Literal["fault_fork", "aa_rerun", "comparator_chain"]


def anchor_order(seed: str, life: str, refs) -> list[str]:
    """B-25's shared anchor order, independent of input enumeration."""
    return sorted(refs, key=lambda ref: (draw(seed, unit(life, "anchor", "order"), 0, ref), ref))


def _check_time(value: int) -> None:
    if type(value) is not int:
        raise TypeError("time must be integer milliseconds")
    if value < 0:
        raise ValueError("time must be since the block's first request")


@dataclass(frozen=True)
class PassOver:
    """An arm can no longer reach this checkpoint on its own branch chain."""

    time: int
    cause: PassOverCause

    def __post_init__(self) -> None:
        _check_time(self.time)
        if self.cause not in ("replay_stopped", "life_bound", "start_window"):
            raise ValueError("unknown pass-over cause")


@dataclass(frozen=True)
class NonArrival:
    """A recorded checkpoint visit on a chain that cannot trigger dispatch."""

    time: int
    kind: NonArrivalKind

    def __post_init__(self) -> None:
        _check_time(self.time)
        if self.kind not in ("fault_fork", "aa_rerun", "comparator_chain"):
            raise ValueError("unknown non-arrival kind")


@dataclass(frozen=True)
class ArmEvents:
    """Events for one eligible arm at one checkpoint of one branch.

    Only arrival_time represents arrival on the arm's own branch chain.
    Waits have neither arrival_time nor pass_over. Non-arrivals are retained
    as immutable input evidence and never participate in dispatch.
    """

    arrival_time: int | None = None
    pass_over: PassOver | None = None
    non_arrivals: tuple[NonArrival, ...] = ()

    def __post_init__(self) -> None:
        if self.arrival_time is not None:
            _check_time(self.arrival_time)
        if self.pass_over is not None and not isinstance(self.pass_over, PassOver):
            raise TypeError("pass_over must be a PassOver record")
        records = tuple(self.non_arrivals)
        if any(not isinstance(record, NonArrival) for record in records):
            raise TypeError("non_arrivals must contain NonArrival records")
        object.__setattr__(self, "non_arrivals", records)


@dataclass(frozen=True)
class DispatchResult:
    """A release decision; all times and lag are integer milliseconds.

    Pending means release_time is None and unmatched is False; followed_arm
    identifies the waiting arm, arrival_time is None and lag is 0.
    Exhaustion has no followed arm or arrival, unmatched=True and lag=0.
    An empty eligible mapping is exhausted with release_time=None because
    there is no last pass-over. It is distinguishable from pending.
    """

    followed_arm: str | None
    arrival_time: int | None
    release_time: int | None
    lag: int
    unmatched: bool


def dispatch(
    seed: str,
    life: str,
    branch: str,
    checkpoint: int,
    arms: Mapping[str, ArmEvents],
) -> DispatchResult:
    """Apply the frozen order and release rule to supplied event evidence.

    The caller filters eligibility and supplies times since the block's
    first request. There is no clock, I/O, mutable random stream or attempt
    state. A resume/retry uses the same unit and attempt 0. This computes
    the release time; the caller records actual probe send times/retries.

    An arrival strictly before its arm's pass-over survives that later
    pass-over. At equal timestamps no arrival came before the pass-over,
    so the arm is passed over. Pending and empty-input results are defined
    in DispatchResult. No independent probe-only timing bound is imposed.
    """
    order = sorted(
        arms,
        key=lambda arm_id: (
            draw(seed, (life, branch, str(checkpoint), arm_id), 0, DISPATCH_DRAW_LABEL),
            arm_id,
        ),
    )
    latest_pass_over = None
    for arm_id in order:
        events = arms[arm_id]
        arrival = events.arrival_time
        passed = events.pass_over
        if passed is not None and (arrival is None or passed.time <= arrival):
            latest_pass_over = (
                passed.time if latest_pass_over is None
                else max(latest_pass_over, passed.time)
            )
            continue
        if arrival is None:
            return DispatchResult(arm_id, None, None, 0, False)
        release = arrival if latest_pass_over is None else max(arrival, latest_pass_over)
        return DispatchResult(arm_id, arrival, release, release - arrival, False)
    return DispatchResult(None, None, latest_pass_over, 0, True)
