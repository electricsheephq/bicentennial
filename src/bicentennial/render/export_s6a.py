"""Read-only, explicitly lossy bridge from a sealed cut to S6a replay data."""

from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.world import world_hash

from .stream import _canary, event_sha256, stream_hash

FORMAT = "s6a-micro-life"
EXPORTER = "g10-0.1"
ASSISTANT = "Noted."
JOIN = "\n\n"
PLACEHOLDER_STATE = {"repo_tree_hash": "a" * 64, "env_state_hash": "b" * 64}
LOSSY = ("tool_as_user", "rows_joined", "assistant_placeholder", "wall_time",
         "session_fields", "no_probes", "no_gold")


def export_s6a(db, cut, schedule) -> dict:
    """Validate identity and replay safety before assembling the exported life."""
    if world_hash(db) != cut.world_hash:
        raise ValueError("world hash mismatch")
    if sha256(schedule.to_json()).hexdigest() != cut.schedule_sha256:
        raise ValueError("schedule hash mismatch")
    if cut.life != schedule.life:
        raise ValueError("life mismatch")
    plans = schedule.sessions
    if [s["index"] for s in cut.sessions] != [p.index for p in plans]:
        raise ValueError("session indices differ")
    for session, plan in zip(cut.sessions, plans, strict=True):
        if (session["long_sprint"] != plan.long_sprint or
                session["wake_before"] != list(plan.wake_before) or
                session["fault_points"] != [dict(f) for f in plan.fault_points]):
            raise ValueError("session metadata differs")
        if any(wake != "gap" for wake in plan.wake_before):
            raise ValueError("unsupported wake")
        if any(f["kind"] != "kill" for f in plan.fault_points):
            raise ValueError("unsupported fault")
        if len(plan.fault_points) > 1:
            raise ValueError("multiple kills")
        for fault in plan.fault_points:
            if type(fault["turn"]) is not int or not 1 <= fault["turn"] < len(plan.turn_t):
                raise ValueError("kill must precede the last turn")

    positions = {p.session_id: i for i, p in enumerate(plans)}
    slots = [{f"{p.session_id}/t{n}": n for n in range(1, len(p.turn_t) + 1)} for p in plans]
    grouped = [[[] for _ in p.turn_t] for p in plans]
    counts, last_turns, previous = [0] * len(plans), [0] * len(plans), -1
    tool_rows = 0
    for row in cut.rows:
        if row["sha256"] != event_sha256(row):
            raise ValueError("invalid row hash")
        position = positions.get(row["session_id"])
        if position is None:
            raise ValueError("unknown session")
        if position < previous:
            raise ValueError("rows outside plan order")
        previous = position
        counts[position] += 1
        if type(row["seq"]) is not int or row["seq"] != counts[position]:
            raise ValueError("nonconsecutive seq")
        n = slots[position].get(row["turn_key"])
        if n is None:
            raise ValueError("invalid turn key")
        if n < last_turns[position]:
            raise ValueError("decreasing turn number")
        last_turns[position] = n
        if "text" in row:
            block = row["text"]
        else:
            block = canon({"result": row["payload"], "tool": row["tool"]}).decode()
            tool_rows += 1
        grouped[position][n - 1].append(block)

    users, seen = [], set()
    for turns in grouped:
        current = []
        for blocks in turns:
            if not blocks:
                raise ValueError("empty turn")
            user = JOIN.join(blocks)
            stripped = user.strip()
            if not stripped or stripped in seen:
                raise ValueError("empty or duplicate user text")
            seen.add(stripped)
            current.append(user)
        users.append(current)

    sessions = []
    for plan, turns in zip(plans, users, strict=True):
        session = {"index": plan.index, "turns": [
            {"user": user, "assistant": ASSISTANT} for user in turns]}
        if plan.fault_points:
            session["restart_after_turn"] = plan.fault_points[0]["turn"]
        if plan.long_sprint:
            session["long_session"] = True
        if "gap" in plan.wake_before:
            session["gap_before"] = True
        sessions.append(session)
    meta = db.execute("SELECT genre, seed FROM meta").fetchone()
    return {"genre": meta["genre"], "seed": meta["seed"], "synthetic": True,
            "export": {"canary": _canary(), "format": FORMAT, "exporter": EXPORTER,
                       "lossy": True, "lossy_mappings": list(LOSSY), "life": cut.life,
                       "branch": cut.branch, "world_hash": cut.world_hash,
                       "schedule_sha256": cut.schedule_sha256,
                       "stream_hash": stream_hash(cut.rows), "tool_rows": tool_rows},
            "sessions": sessions, "probes": []}


def export_bytes(life) -> bytes:
    """Canonical UTF-8 JSON, terminated by one newline."""
    return canon(life) + b"\n"


def write_s6a(path, life) -> None:
    """Write exclusively so an existing replay file is never overwritten."""
    with Path(path).open("xb") as file:
        file.write(export_bytes(life))
