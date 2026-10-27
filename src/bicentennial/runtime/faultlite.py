"""Boundary-only fault-lite schedules bound to a validated script timeline."""

from copy import deepcopy

from bicentennial.canon import sha256_canon
from bicentennial.contracts.run import validate


class FaultLite:
    """Validated faults; wire snapshots and boundary results are detached copies."""

    @classmethod
    def load(cls, obj: list, script: dict) -> "FaultLite":
        validate("fault-lite", obj)
        validate("script", script)
        sessions = {session["index"]: session for session in script["sessions"]}
        seen = set()
        for fault in obj:
            kind, index, turn = fault["kind"], fault["session"], fault["turn"]
            if index not in sessions:
                raise ValueError("fault session is not in the script")
            session = sessions[index]
            if session["kind"] != "replay":
                raise ValueError("faults must reference replay sessions")
            if turn is not None and turn not in {row["n"] for row in session["turns"]}:
                raise ValueError("fault turn is not in its session")
            if kind == "swap" and turn is not None:
                raise ValueError("swap must be at a session start")
            key = kind, index, turn
            if key in seen:
                raise ValueError("duplicate fault")
            seen.add(key)
        schedule = cls()
        schedule._faults = sorted(deepcopy(obj), key=lambda fault: (
            fault["session"], fault["turn"] is not None, fault["turn"], fault["kind"]))
        schedule._timeline = tuple((row["index"], row["kind"]) for row in script["sessions"])
        return schedule

    def at(self, session: int, turn: int | None) -> list[dict]:
        """Return faults at a session start (None) or after the named turn."""
        return deepcopy([fault for fault in self._faults
                         if fault["session"] == session and fault["turn"] == turn])

    def replay_prefix(self, session: int) -> tuple[int, ...]:
        """Replay indices through this point in timeline order, including this replay."""
        if type(session) is not int:
            raise ValueError("session must be an integer index")
        prefix = []
        for index, kind in self._timeline:
            if kind == "replay":
                prefix.append(index)
            if index == session:
                if not prefix:
                    raise ValueError("probe has no preceding replay session")
                return tuple(prefix)
        raise ValueError("session is not in the script")

    def to_obj(self) -> list[dict]:
        """Return the sorted K13 wire array for canonical serialization."""
        return deepcopy(self._faults)


def fault_lite_hash(schedule: FaultLite) -> str:
    """Hash only the canonical sorted fault array for the run lock."""
    return sha256_canon(schedule.to_obj())
