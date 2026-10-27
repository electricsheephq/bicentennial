"""Validated per-system routes, cut into segments at replay-session swaps."""

import re
from copy import deepcopy

from bicentennial.canon import sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.runtime.faultlite import FaultLite


class UnknownRoute(ValueError):
    """The table has no route for the requested system and segment."""


def segment_of(session: int, schedule: FaultLite) -> str:
    """A swap starts its segment; probes inherit the preceding replay's segment."""
    prefix = schedule.replay_prefix(session)
    swaps = sum(fault["kind"] == "swap" and fault["session"] in prefix
                for fault in schedule.to_obj())
    return f"seg{swaps}"


class RouteTable:
    """Load a route-table wire object; returned routes and snapshots are copies."""

    @classmethod
    def load(cls, obj: dict) -> "RouteTable":
        validate("route-table", obj)
        rows = obj["routes"]
        for row in rows:
            if re.fullmatch(r"seg(0|[1-9][0-9]*)", row["segment"]) is None:
                raise ValueError("route segment must be segN without leading zeros")
        previous = {}
        for row in sorted(rows, key=lambda row: (row["system"], int(row["segment"][3:]))):
            system = row["system"]
            if system in previous and previous[system] != row["vision"]:
                raise ValueError("a swap must not move vision")
            previous[system] = row["vision"]
        if any(row["vision"] is not None for row in rows):
            raise ValueError("v0.1 routes must have null vision")
        table = cls()
        table._obj = deepcopy(obj)
        table._routes = {(row["system"], row["segment"]): row
                         for row in table._obj["routes"]}
        return table

    def resolve(self, system: str, session: int, schedule: FaultLite) -> dict:
        """Return the segment's route, or refuse an absent system/segment pair."""
        key = system, segment_of(session, schedule)
        try:
            return deepcopy(self._routes[key])
        except KeyError as error:
            raise UnknownRoute(f"unknown route: {key}") from error

    def to_obj(self) -> dict:
        """Return the K13 wire object for canonical serialization."""
        return deepcopy(self._obj)


def route_table_hash(table: RouteTable) -> str:
    """Hash only the canonical route-table wire bytes for the run lock."""
    return sha256_canon(table.to_obj())
