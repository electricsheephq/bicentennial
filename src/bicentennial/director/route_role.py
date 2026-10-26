"""Pure translation from S1 classifications to director ledger roles and scripted turns."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class RouteState:
    """Read-only view of the director fields used to route a classified request."""

    pending: Mapping[str, dict]
    expected: tuple[dict, ...]
    cursor: int
    current: dict | None
    path_aliases: Mapping[str, tuple[str, frozenset]]
    aliases: Mapping[str, tuple[str, frozenset]]
    id_roles: Mapping[str, tuple[str, str]]


def route(s1: tuple[str, str, dict], path: str, body: dict, state: RouteState) -> tuple[str, str, dict | None]:
    """Map an already classified request without changing the director state."""
    try:
        role, method, ev = s1
        if role in ("replay_main", "probe_main", "write_turn"):
            if ev.get("call_id"):
                turn = state.pending.get(ev["call_id"])
                if role == "probe_main" or turn is not None:
                    return role, "tool_results", turn
            elif method == "cursor" and role != "write_turn":
                n = ev.get("turn")
                if isinstance(n, int):
                    return role, "cursor", state.expected[n]
                if n in ("retry", "continuation") and state.current and 0 < state.cursor <= len(state.expected):
                    turn = state.expected[state.cursor - 1]
                    role = "replay_main" if turn["kind"] == "replay" else "probe_main"
                    return role, "retry", turn
        elif role == "memory_write":
            return "memory_write", "background_review", None
        elif role == "compaction":
            return "summariser", "compression", None
        elif role == "title":
            return "aux", "title_generation", None
        elif role in ("summariser", "extraction"):
            return "aux", role, None
        elif role == "aux":
            task = next((p.split("/")[2] for p in state.path_aliases if path.startswith(p)), None)
            task = state.id_roles.get(ev.get("call_id"), ("", ""))[1] or task
            model = body.get("model") or ""
            if not task and model in state.aliases:
                task = model.removeprefix("bicentennial-aux-")
            marker = next(iter(ev.get("markers") or []), "metadata").removeprefix("hermes_")
            return "aux", task or marker, None
    except Exception:  # noqa: BLE001 - preserve the original fail-closed routing seam
        pass
    return "unknown", "", None
