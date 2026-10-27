"""Pure keyed life schedules; generation never starts a harness or clock."""

import json
from dataclasses import asdict, dataclass

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import choice, mint_id, uniform_int

from . import tokens, unit
from .db import insert_session
from .scale import (
    ANCHOR_T,
    HEARTBEAT_S,
    LONG_GAP_S,
    ORDINARY_GAP_S,
    SESSION_S,
    TURN_S,
    TURNS,
    WORLD_TZ,
    Scale,
    candidates,
    check,
)


def ticks(t_start: int, t_end: int, interval_s: int) -> list[int]:
    """Uniform ticks, including the start and excluding the end."""
    if any(type(v) is not int for v in (t_start, t_end, interval_s)) or interval_s <= 0:
        raise ValueError("tick times must be integers with a positive interval")
    return list(range(t_start, t_end, interval_s))


@dataclass(frozen=True)
class SessionPlan:
    index: int
    session_id: str
    kind: str
    t_start: int
    t_end: int
    gap_before_s: int | None
    turn_t: tuple[int, ...]
    heartbeats: tuple[int, ...]
    wake_before: tuple[str, ...]
    fault_points: tuple[dict, ...]
    long_sprint: bool
    min_tokens: int
    probe_point: bool


def _order(row):
    return row["session"], row["turn"] is not None, row["turn"], row["kind"]


@dataclass(frozen=True)
class Schedule:
    seed: str
    life: str
    scale: Scale
    tz: str
    sessions: tuple[SessionPlan, ...]

    def to_obj(self) -> dict:
        return json.loads(canon(asdict(self) | {"estimator": tokens.ESTIMATOR}))

    def to_json(self) -> bytes:
        return canon(self.to_obj())

    def fault_lite(self) -> list[dict]:
        rows = sorted([dict(row) for s in self.sessions for row in s.fault_points], key=_order)
        validate("fault-lite", rows)
        return rows

    def wakes(self) -> list[tuple[str, int, int | None]]:
        rows = self.fault_lite() + [dict(kind="gap", session=s.index, turn=None)
                                    for s in self.sessions if "gap" in s.wake_before]
        return [(r["kind"], r["session"], r["turn"]) for r in sorted(rows, key=_order)]


def build_schedule(seed: str, life: str, scale: Scale) -> Schedule:
    check(scale)

    def select(ranges, prefix):
        return {choice(seed, unit(life, "schedule", f"{prefix}-{i}"), 0, "session",
                       candidates(scale, bounds)) for i, bounds in enumerate(ranges)}

    sprints = select(scale.sprint_ranges, "sprint")
    long_gaps = select(scale.long_gap_ranges, "long-gap")
    plans = []
    end = ANCHOR_T
    key = canon([seed, life, "session"]).decode()
    for k in range(1, scale.sessions + 1):
        gap = None if k == 1 else uniform_int(
            seed, unit(life, "schedule", f"gap-{k}"), 0, "seconds",
            *(LONG_GAP_S if k in long_gaps else ORDINARY_GAP_S))
        start = ANCHOR_T if k == 1 else end + gap
        end = start + SESSION_S
        faults = tuple(dict(kind=kind, session=k, turn=1 if kind == "kill" else None)
                       for kind in ("kill", "swap", "restart", "compaction")
                       if getattr(scale, kind) == k)
        wake = ("gap",) if k in long_gaps else tuple(r["kind"] for r in faults
                                                   if r["turn"] is None)
        plans.append(SessionPlan(
            index=k, session_id=mint_id(key, k), kind="sprint" if k in sprints else "work",
            t_start=start, t_end=end, gap_before_s=gap,
            turn_t=tuple(start + n * TURN_S for n in range(TURNS)),
            heartbeats=tuple(ticks(start, end, HEARTBEAT_S)), wake_before=wake,
            fault_points=faults, long_sprint=k in sprints,
            min_tokens=tokens.sprint_floor(scale.window) if k in sprints else 0,
            probe_point=k in scale.checkpoints))
    return Schedule(seed, life, scale, WORLD_TZ, tuple(plans))


def write_sessions(db, schedule: Schedule) -> None:
    """Append plans in the caller's transaction after checking world identity."""
    meta = db.execute("SELECT seed, scale FROM meta").fetchall()
    if len(meta) != 1 or tuple(meta[0]) != (schedule.seed, schedule.scale.sessions):
        raise ValueError("world seed or scale does not match schedule")
    for plan in schedule.sessions:
        insert_session(db, idx=plan.index, t_start=plan.t_start, t_end=plan.t_end, kind=plan.kind)
