"""Read-only session cutting and keyed user-pasted compaction pressure."""

import json
import unicodedata
from bisect import bisect_right
from dataclasses import dataclass, replace
from hashlib import sha256

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import choice, mint_id, uniform_int
from bicentennial.world import unit, world_hash
from bicentennial.world.tokens import estimate_tokens, meets_sprint

from . import channel_stamp, default_bank, render_event
from .stream import _canary, _lint_form, _present, content, lint, render_key, seal

LEVELS = ("warn", "error", "info")
SERVICES = ("transport", "spool", "collector")
MESSAGES = ("batch flush timeout", "retry scheduled", "upstream closed connection", "spool file rotated",
            "checksum mismatch on segment", "backpressure engaged", "ack window exceeded")
LINES = 20


@dataclass(frozen=True)
class Cut:
    life: str
    branch: str
    rows: tuple[dict, ...]
    sessions: tuple[dict, ...]
    world_hash: str
    schedule_sha256: str
    bank_id: str
    bank_sha256: str
    bank_calibrated: bool
    exclude_sha256: str | None
    render_key: str


def _chunk(schedule, plan, c, a):
    seed, u = schedule.seed, unit(schedule.life, "sprint", f"{plan.index}-{c}")
    svc = choice(seed, u, a, "svc", SERVICES)
    lines = []
    for i in range(LINES):
        dt = uniform_int(seed, u, a, f"{i}.ts", 0, 6)
        level = choice(seed, u, a, f"{i}.level", LEVELS)
        msg = choice(seed, u, a, f"{i}.msg", MESSAGES)
        batch = uniform_int(seed, u, a, f"{i}.batch", 1000, 9999)
        seg = uniform_int(seed, u, a, f"{i}.segment", 100, 999)
        retry = uniform_int(seed, u, a, f"{i}.retry", 0, 4)
        lines.append(f'{{"ts":"T+{i * 7 + dt:05d}s","level":"{level}","svc":"{svc}",'
                     f'"msg":"{msg}","batch":{batch},"segment":"seg-{seg}","retry":{retry}}}')
    stamp = channel_stamp(plan.turn_t[c % len(plan.turn_t)], schedule.tz, "chat")
    return (stamp + " " + f"Long debugging sprint, chunk {c + 1}. "
            "Here is the next log excerpt from the soak run:\n" + "\n".join(lines) + "\nWhat stands out?")


def cut(db, schedule, *, branch, principal_id, expected_state, bank=None,
        exclude_tokens: frozenset[str] | None = None) -> Cut:
    meta = dict(db.execute("SELECT * FROM meta").fetchone())
    plans = schedule.sessions
    if branch not in ("B0", "B1") or (meta["seed"], meta["scale"]) != (
            schedule.seed, schedule.scale.sessions):
        raise ValueError("invalid branch or world identity")
    actual = [tuple(r) for r in db.execute("SELECT idx, t_start, t_end, kind FROM session ORDER BY idx")]
    if actual != [(p.index, p.t_start, p.t_end, p.kind) for p in plans]:
        raise ValueError("world sessions differ from schedule")
    if not db.execute("SELECT 1 FROM entity WHERE id = ?", (principal_id,)).fetchone():
        raise ValueError("unknown principal")
    if set(expected_state) != set(range(1, schedule.scale.sessions + 1)):
        raise ValueError("expected state indices differ")
    for p in plans:
        if not p.turn_t or any(type(t) is not int or not p.t_start <= t < p.t_end for t in p.turn_t) or (
                any(a >= b for a, b in zip(p.turn_t, p.turn_t[1:], strict=False))):
            raise ValueError("invalid turn slots")
    bank = default_bank() if bank is None else bank
    tokens = list(db.execute("SELECT * FROM locked_token ORDER BY token_id"))
    excluded = sorted(unicodedata.normalize("NFC", t) for t in (
        (r["value"] for r in tokens) if exclude_tokens is None else exclude_tokens))
    grouped = {p.index: [] for p in plans}
    events = db.execute("SELECT * FROM event ORDER BY id").fetchall()
    ids = {e["id"] for e in events}
    for e in events:
        plan = next((p for p in plans if p.t_start <= e["t_sim"] < p.t_end), None)
        if plan is None:
            raise ValueError(f"event outside sessions: {e['id']}")
        if (e["kind"] == "tool") != (e["channel"] == "tool_result"):
            raise ValueError(f"tool kind/channel mismatch: {e['id']}")
        r = render_event(db, e["id"], life=schedule.life, tz=schedule.tz, bank=bank)
        row = dict(canary=_canary(), event_id=e["id"], session_id=plan.session_id,
                   t_sim=e["t_sim"], tz=schedule.tz, channel=e["channel"], kind=e["kind"],
                   actor=e["actor_id"], audience=json.loads(e["audience_json"]), visibility=e["visibility"],
                   fact_ids=list(r.fact_ids), gold_critical=r.gold_critical,
                   call_id=None, tool=None, expected_result_sha256=None)
        if e["kind"] == "tool":
            payload = json.loads(e["payload_json"])
            tool = payload.get("tool")
            if set(payload) != {"tool", "result"} or type(payload["result"]) is not dict or (
                    type(tool) is not dict or set(tool) != {"name", "args"} or
                    type(tool["name"]) is not str or not tool["name"] or type(tool["args"]) is not dict):
                raise ValueError(f"malformed tool event: {e['id']}")
            row.update(payload=payload["result"], tool=tool,
                       call_id=mint_id(canon([schedule.seed, schedule.life, "call", e["id"]]).decode(), 0),
                       expected_result_sha256=sha256_canon(payload["result"]),
                       render=dict(lane="template", template_id=None, voice="sandbox"))
            form = _lint_form(row)
            if any(not _present(unicodedata.normalize("NFC", t["value"]), form)
                   for t in tokens if t["fact_id"] in r.fact_ids):
                raise ValueError(f"missing linked token: {e['id']}")
        else:
            row.update(text=r.text, render=r.stream_render())
        grouped[plan.index].append((e["t_sim"], 0, e["id"], row))
    rows, sessions = [], []
    for p in plans:
        chunks = []
        while p.long_sprint and not meets_sprint(estimate_tokens("".join(chunks)), schedule.scale.window):
            c = len(chunks)
            for a in range(8):
                text = _chunk(schedule, p, c, a)
                normal = unicodedata.normalize("NFC", text)
                if _canary() not in normal and not any(t in normal for t in excluded):
                    break
            else:
                raise ValueError(f"filler retries exhausted: session {p.index}, chunk {c}")
            chunks.append(text)
            eid = mint_id(canon([schedule.seed, schedule.life, "sprint", p.index]).decode(), c)
            if eid in ids:
                raise ValueError(f"filler event id collision: {eid}")
            ids.add(eid)
            t = p.turn_t[c % len(p.turn_t)]
            row = dict(canary=_canary(), event_id=eid, session_id=p.session_id, t_sim=t,
                       tz=schedule.tz, channel="chat", kind="sprint_log", actor=principal_id,
                       audience=["agent"], visibility="shared", text=text, fact_ids=[], gold_critical=False,
                       render=dict(lane="template", template_id="sprint-log-v1", voice="template"),
                       call_id=None, tool=None, expected_result_sha256=None)
            grouped[p.index].append((t, 1, c, row))
        current, turns = [], set()
        for seq, (t, _, _, row) in enumerate(sorted(grouped[p.index], key=lambda r: r[:3]), 1):
            n = bisect_right(p.turn_t, t)
            turns.add(n)
            current.append(seal(row | dict(seq=seq, turn_key=f"{p.session_id}/t{n}")))
        if turns != set(range(1, len(p.turn_t) + 1)):
            raise ValueError(f"empty turn: session {p.index}")
        session = dict(canary=_canary(), index=p.index, kind="work", wake_before=list(p.wake_before),
                       fault_points=[dict(f) for f in p.fault_points], long_sprint=p.long_sprint,
                       probe_point=p.probe_point, expected_state=expected_state[p.index],
                       est_tokens=estimate_tokens("".join(content(row) for row in current)))
        validate("session", session)
        rows.extend(current)
        sessions.append(session)
    violations = lint(db, rows)
    if violations:
        raise ValueError(f"closed-world violations: {violations}")
    result = Cut(schedule.life, branch, tuple(rows), tuple(sessions), world_hash(db),
                 sha256(schedule.to_json()).hexdigest(), bank.bank_id, bank.sha256, bank.calibrated,
                 None if exclude_tokens is None else sha256(canon(excluded)).hexdigest(), "")
    return replace(result, render_key=render_key(result, meta))
