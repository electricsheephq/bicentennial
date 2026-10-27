"""The G1 software-partner world: a small team, told-once statements, a keyed life and the tidewater golden."""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.keyed import choice, mint_id, shuffle, uniform_int
from bicentennial.world import unit
from bicentennial.world.db import (
    TABLES,
    insert_attr,
    insert_entity,
    insert_event,
    insert_fact,
    insert_link,
    insert_locked_token,
)
from bicentennial.world.lineage import atomic
from bicentennial.world.processes import (
    HARD,
    LOW_SALIENCE,
    SALIENCE,
    check_tokens,
    mint,
    slot,
    token_value,
)
from bicentennial.world.processes.commitments import Commitment, write_commitments
from bicentennial.world.processes.corrections import Chain, write_corrections
from bicentennial.world.processes.filler import write_filler
from bicentennial.world.processes.forget import verify
from bicentennial.world.scale import (
    ANCHOR_T,
    DEV_WINDOW,
    HEARTBEAT_S,
    LONG_GAP_S,
    ORDINARY_GAP_S,
    SESSION_S,
    TURNS,
    WORLD_TZ,
    Scale,
)
from bicentennial.world.schedule import Schedule, SessionPlan, ticks, write_sessions
from bicentennial.world.tokens import sprint_floor

from .codebase_model import PROCESS as PROCESS
from .codebase_model import write_commit

GENRE, GENERATOR_VERSION = "G1", "g1-0.1"
TOKEN_KINDS = ("number", "name", "date", "code")
STEM = re.compile(r"[A-Z]{2,12}")
# Explicit tokens are printable ASCII without a quote or backslash, so JSON escaping never changes them.
EXPLICIT = re.compile(r'[ !#-\[\]-~]{4,}')
TEAM_NAMES = ("Heron", "Wren", "Kestrel", "Plover", "Tern")
ZONES = ("Europe/Paris", "America/New_York", "Asia/Tokyo", "Australia/Sydney", "America/Sao_Paulo")
KINDS = {  # kind: (canonical names, predicate, stem), in entity write order after the team
    "milestone": (("beta release", "general release"), "deadline", "DUE"),
    "constraint": (("logging rule", "auth rule", "licence rule", "commit style rule"), "rule", "RULE"),
    "decision": (("queue backend", "retry policy", "config format", "test runner"), "choice", "DECISION"),
    "flag": (("quiet_retry", "metrics_endpoint"), "default", "FLAG"),
    "constant": (("batch_size", "flush_timeout_ms"), "value", "CONST"),
    "endpoint": (("metrics endpoint", "health endpoint", "status endpoint"), "path", "ROUTE"),
    "commitment": (("release checklist", "key rotation"), "deliver", "TASK"),
    "ticket": (("schema migration", "load test", "billing migration", "audit fix"), "status", "TICKET"),
}


def world_meta(seed, sessions) -> dict:
    return {"generator_version": GENERATOR_VERSION, "genre": GENRE, "seed": seed, "scale": sessions}


@dataclass(frozen=True, kw_only=True)
class Statement:
    id: str
    subject: str
    key: str
    value: str | None = None
    stem: str | None = None
    token_kind: str = "code"
    at: tuple[int, int] | None = None


def _known(db, entity) -> bool:
    return type(entity) is str and db.execute("SELECT 1 FROM entity WHERE id = ?", (entity,)).fetchone() is not None


def write_statements(db, schedule, statements, *, principal) -> tuple[str, ...]:
    """Facts told once in chat by the principal; chat-only until a commit surfaces them."""
    statements = tuple(statements)
    with atomic(db):
        meta = db.execute("SELECT seed FROM meta").fetchall()
        if len(meta) != 1 or meta[0][0] != schedule.seed:
            raise ValueError("world seed does not match schedule")
        if not _known(db, principal) or not all(_known(db, s.subject) for s in statements):
            raise ValueError("unknown principal or subject")
        ids, pairs = [s.id for s in statements], [(s.subject, s.key) for s in statements]
        if any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("statement ids must be unique nonempty strings")
        if len(set(pairs)) != len(pairs) or any(db.execute(
                "SELECT 1 FROM attr WHERE entity_id = ? AND key = ?", p).fetchone() for p in pairs):
            raise ValueError("a (subject, key) pair is told once and holds no earlier attr row")
        for s in statements:
            if type(s.key) is not str or not s.key or (s.value is None) == (s.stem is None):
                raise ValueError("a statement needs a key and exactly one of value and stem")
            if s.stem is not None and (type(s.stem) is not str or not STEM.fullmatch(s.stem)):
                raise ValueError("token stem must match ^[A-Z]{2,12}$")
            if s.value is not None and (type(s.value) is not str or not EXPLICIT.fullmatch(s.value)):
                raise ValueError("an explicit value is 4+ printable ASCII characters, no quote or backslash")
            if s.token_kind not in TOKEN_KINDS:
                raise ValueError("unknown token kind")
            if s.at is not None:
                if type(s.at) is not tuple or len(s.at) != 2:
                    raise ValueError("at is one (session, turn) pair")
                slot(schedule, *s.at)
        facts = []
        for s in statements:
            u = unit(schedule.life, PROCESS, s.id)
            t = slot(schedule, *(s.at or (uniform_int(schedule.seed, u, 0, "session", 1, len(schedule.sessions)),
                                          uniform_int(schedule.seed, u, 0, "turn", 1, TURNS))))
            eid, fid = mint(schedule, PROCESS, s.id, "event", "event", 0), mint(schedule, PROCESS, s.id, "fact", "value", 0)
            v = s.value or token_value(db, schedule, PROCESS, s.id, "value", 0, s.stem)
            insert_event(db, id=eid, t_sim=t, kind="statement", channel="chat", actor_id=principal,
                         audience_json=["agent"], visibility="shared", salience=SALIENCE, payload_json={})
            insert_fact(db, id=fid, subject_id=s.subject, predicate=s.key, object=v, polarity="affirm",
                        modality="stated", strength=HARD, speech_act="assert")
            insert_locked_token(db, token_id=mint(schedule, PROCESS, s.id, "token", "value", 0), fact_id=fid,
                                kind=s.token_kind, value=v)
            insert_link(db, event_id=eid, fact_id=fid, role="assert")
            insert_attr(db, entity_id=s.subject, key=s.key, value=v, valid_from_t=t, valid_to_t=None,
                        recorded_t=t, source_event_id=eid)
            facts.append(fid)
        check_tokens(db)
    return tuple(facts)


def tail_filler(db, schedule, *, principal) -> int:
    """Factless events for empty slots past turn TURNS; makes no draw."""
    if not _known(db, principal):
        raise ValueError("unknown principal")
    occupied, count = {t for (t,) in db.execute("SELECT t_sim FROM event")}, 0
    for plan in schedule.sessions:
        for n in range(TURNS + 1, len(plan.turn_t) + 1):
            if plan.turn_t[n - 1] not in occupied:
                insert_event(db, id=mint(schedule, PROCESS, "tail", "event", str(plan.index), n),
                             t_sim=plan.turn_t[n - 1], kind="filler", channel="chat", actor_id=principal,
                             audience_json=["agent"], visibility="shared", salience=LOW_SALIENCE, payload_json={})
                count += 1
    return count


def _begin(db, schedule) -> None:
    if any(db.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone() for table in TABLES if table != "meta"):
        raise ValueError("the world must hold only its meta row")
    meta = db.execute("SELECT genre, generator_version, seed FROM meta").fetchall()
    if len(meta) != 1 or tuple(meta[0]) != (GENRE, GENERATOR_VERSION, schedule.seed):
        raise ValueError("world meta does not match the G1 generator and the schedule seed")
    write_sessions(db, schedule)


def _finish(db, schedule, principal) -> None:
    tail_filler(db, schedule, principal=principal)
    write_filler(db, schedule, principal=principal)
    check_tokens(db)
    verify(db)


@dataclass(frozen=True, kw_only=True)
class Mix:
    deadlines: tuple[int, ...] = (1, 2)
    constraints: int = 4
    relaxed: int = 1
    decisions: int = 4
    chat_only: int = 2
    flags: int = 2
    constants: int = 2
    changed: int = 1
    # Amendment 1 A3: constant i's later mention; a constant is a chain if changed or mentioned.
    mentions: tuple[str | None, ...] = ("hedge", "quote")
    endpoints: int = 2
    commitments: tuple[bool, ...] = (False, True)


MIX = Mix()


@dataclass(frozen=True)
class G1World:
    principal: str
    team: tuple[str, ...]


def _sizes(mix) -> dict[str, int]:
    if any(type(v) is not tuple for v in (mix.deadlines, mix.mentions, mix.commitments)):
        raise ValueError("deadlines, mentions and commitments are tuples")
    sizes = {"milestone": len(mix.deadlines), "constraint": mix.constraints, "decision": mix.decisions,
             "flag": mix.flags, "constant": mix.constants, "endpoint": mix.endpoints,
             "commitment": len(mix.commitments)}
    if any(type(c) is not int or c < 0 for c in (*sizes.values(), mix.relaxed, mix.chat_only, mix.changed)):
        raise ValueError("counts are non-negative ints")
    if any(c > len(KINDS[kind][0]) for kind, c in sizes.items()):
        raise ValueError("a count exceeds its name tuple")
    if any(type(d) is not int or not 1 <= d <= 6 for d in mix.deadlines):
        raise ValueError("a deadline chain has depth 1..6")
    if (mix.relaxed > mix.constraints or mix.chat_only > mix.decisions or mix.changed > mix.constants
            or len(mix.mentions) > mix.constants):
        raise ValueError("relaxed, chat_only, changed and mentions are bounded by their kind's count")
    if any(m not in ("hedge", "quote", None) for m in mix.mentions):
        raise ValueError("a constant's mention is hedge, quote or None")
    if any(type(c) is not bool for c in mix.commitments):
        raise ValueError("commitment entries are bools")
    return sizes | {"ticket": 2 * len(mix.commitments)}


def build_g1(db, schedule, *, mix=MIX) -> G1World:
    with atomic(db):
        sizes = _sizes(mix)
        _begin(db, schedule)
        seed, life, t0 = schedule.seed, schedule.life, schedule.sessions[0].t_start
        t = unit(life, PROCESS, "team")
        n = uniform_int(seed, t, 0, "size", 3, 5)
        zones = (WORLD_TZ, *shuffle(seed, t, 0, "zones", ZONES[1:]))

        def entity(kind, i, name):
            eid = mint(schedule, PROCESS, "entities", "entity", kind, i)
            insert_entity(db, id=eid, kind=kind, canonical_name=name, aliases_json=[], created_t=t0, retired_t=None)
            return eid

        team = tuple(entity("person", i, name) for i, name in enumerate(shuffle(seed, t, 0, "names", TEAM_NAMES)[:n]))
        e = {kind: tuple(entity(kind, i, names[i]) for i in range(sizes[kind])) for kind, (names, _, _) in KINDS.items()}

        def spec(cls, kind, i, uid=None, **kw):
            return cls(id=uid or f"{kind}-{i}", subject=e[kind][i], key=KINDS[kind][1], stem=KINDS[kind][2], **kw)

        principal = team[0]
        write_statements(db, schedule, [Statement(id=f"zone-{i}", subject=m, key="time_zone", value=zones[i],
                                                  token_kind="name") for i, m in enumerate(team)], principal=principal)
        constants = [(i, int(i < mix.changed), mix.mentions[i] if i < len(mix.mentions) else None)
                     for i in range(mix.constants)]
        chained = [c for c in constants if c[1] or c[2]]
        write_corrections(db, schedule, [
            *(spec(Chain, "milestone", i, f"deadline-{i}", depth=d) for i, d in enumerate(mix.deadlines)),
            *(spec(Chain, "constraint", i, depth=1) for i in range(mix.relaxed)),
            *(spec(Chain, "constant", i, depth=d, mention=m) for i, d, m in chained)], principal=principal)
        write_statements(db, schedule, [
            *(spec(Statement, "constraint", i) for i in range(mix.relaxed, mix.constraints)),
            *(spec(Statement, kind, i) for kind in ("decision", "flag") for i in range(sizes[kind])),
            *(spec(Statement, "constant", i) for i, d, m in constants if (i, d, m) not in chained),
            *(spec(Statement, "endpoint", i) for i in range(mix.endpoints))], principal=principal)

        def told(uid):
            return [(uid, 0, mint(schedule, PROCESS, uid, "fact", "value", 0))]

        commits = [c for i in range(mix.chat_only, mix.decisions) for c in told(f"decision-{i}")]
        commits += [c for i in range(mix.flags) for c in told(f"flag-{i}")]
        for i, d, m in constants:
            commits += [(f"constant-{i}", j, mint(schedule, "corrections", f"constant-{i}", "fact", "value", j))
                        for j in range(d + 1)] if (i, d, m) in chained else told(f"constant-{i}")
        commits += [c for i in range(mix.endpoints) for c in told(f"endpoint-{i}")]
        for uid, j, fid in commits:
            write_commit(db, schedule, unit_id=uid, n=j, fact_id=fid,
                         author=choice(seed, unit(life, PROCESS, uid), 0, f"author:{j}", team))
        write_commitments(db, schedule, [Commitment(
            id=f"commitment-{i}", subject=e["commitment"][i], predicate="deliver", stem="TASK", trigger="event",
            cue_subject=e["ticket"][2 * i], cue_key="status", cue_stem="TICKET", lures=(e["ticket"][2 * i + 1],),
            sender=choice(seed, unit(life, PROCESS, f"commitment-{i}"), 0, "sender", team[1:]),
            cancelled=c, channel="chat", notice_channel="chat") for i, c in enumerate(mix.commitments)],
            principal=principal)
        _finish(db, schedule, principal)
    return G1World(principal, team)


GOLDEN_KEYS = {
    "golden": ("name", "seed", "life", "principal", "schedule", "entities", "chain", "statement", "commitment"),
    "schedule": ("sessions", "turns", "kill", "sprint", "long_gap", "long_gap_s", "checkpoints"),
    "chain": ("facts", "subject", "key", "stem", "token_kind", "values", "at"),
    "statement": ("fact", "subject", "key", "value", "token_kind", "at"),
    "commitment": ("fact", "subject", "predicate", "stem", "trigger", "cue_subject", "cue_key", "cue_stem",
                   "sender", "made", "due"),
}


@dataclass(frozen=True)
class Golden:
    name: str
    seed: str
    life: str
    principal: str
    schedule: dict
    entities: dict
    chain: tuple
    statement: tuple
    commitment: tuple


def _tuples(v):
    return tuple(map(_tuples, v)) if type(v) is list else v


def _exact(table, where) -> dict:
    if type(table) is not dict or set(table) != set(GOLDEN_KEYS[where]):
        raise ValueError(f"{where}: expected exactly {list(GOLDEN_KEYS[where])}")
    return {k: _tuples(table[k]) for k in GOLDEN_KEYS[where]}


def load_golden(path) -> Golden:
    top = _exact(tomllib.loads(Path(path).read_text(encoding="utf-8")), "golden")
    top["schedule"] = _exact(top["schedule"], "schedule")
    for where in ("chain", "statement", "commitment"):
        if type(top[where]) is not tuple:
            raise ValueError(f"{where} is an array of tables")
        top[where] = tuple(_exact(item, where) for item in top[where])
    entities = top["entities"] = {k: _tuples(v) for k, v in top["entities"].items()} if type(
        top["entities"]) is dict else None
    if entities is None or any(type(v) is not tuple or len(v) != 2 or any(
            type(s) is not str or not s for s in v) for v in entities.values()):
        raise ValueError("an entity is [kind, canonical name], two nonempty strings")
    refs = [top["principal"], *(x["subject"] for w in ("chain", "statement", "commitment") for x in top[w]),
            *(x[k] for x in top["commitment"] for k in ("cue_subject", "sender"))]
    if any(type(r) is not str or r not in entities for r in refs):
        raise ValueError("reference to an undeclared entity")
    facts = [*(f for c in top["chain"] for f in c["facts"]), *(x["fact"] for w in ("statement", "commitment")
                                                               for x in top[w])]
    if len(set(facts)) != len(facts):
        raise ValueError("a fact id is repeated")
    if any(c["trigger"] not in ("event", "cue") for c in top["commitment"]):
        raise ValueError("a golden commitment trigger is event or cue")
    return Golden(**top)


def _ints(*values) -> bool:
    return all(type(v) is int for v in values)


def golden_schedule(golden, *, seed=None) -> Schedule:
    """The golden's plans, built directly; G02's `check` admits only its presets and is never called."""
    seed = golden.seed if seed is None else seed
    g = golden.schedule
    s, turns, kill, sprint, long_gap, cps = (g[k] for k in ("sessions", "turns", "kill", "sprint", "long_gap",
                                                            "checkpoints"))
    if not _ints(s) or s < 2 or type(turns) is not tuple or len(turns) != s:
        raise ValueError("turns needs one entry per session, and S >= 2")
    if not _ints(*turns) or any(n < TURNS or SESSION_S % n for n in turns):
        raise ValueError("a turns entry is at least TURNS and divides SESSION_S")
    if type(kill) is not tuple or len(kill) != 2 or not _ints(*kill) or not 1 <= kill[0] <= s or not (
            1 <= kill[1] <= turns[kill[0] - 1] - 1):
        raise ValueError("the kill falls after a turn inside its session, before the last")
    if not _ints(sprint, long_gap) or not (2 <= sprint <= s and 2 <= long_gap <= s):
        raise ValueError("sprint and long_gap lie in 2..S")
    if len({kill[0], sprint, long_gap}) != 3:
        raise ValueError("kill, sprint and long-gap sessions are distinct")
    if not _ints(g["long_gap_s"]) or not LONG_GAP_S[0] <= g["long_gap_s"] <= LONG_GAP_S[1]:
        raise ValueError("long_gap_s lies inside LONG_GAP_S")
    if (type(cps) is not tuple or not cps or not _ints(*cps) or cps[0] < 1 or cps[-1] != s
            or any(a >= b for a, b in zip(cps, cps[1:], strict=False))):
        raise ValueError("checkpoints strictly increase inside 1..S and end at S")
    plans, end, key = [], ANCHOR_T, canon([seed, golden.life, "session"]).decode()
    for k in range(1, s + 1):
        gap = None if k == 1 else g["long_gap_s"] if k == long_gap else uniform_int(
            seed, unit(golden.life, "schedule", f"gap-{k}"), 0, "seconds", *ORDINARY_GAP_S)
        start = ANCHOR_T if k == 1 else end + gap
        end, step = start + SESSION_S, SESSION_S // turns[k - 1]
        plans.append(SessionPlan(
            index=k, session_id=mint_id(key, k), kind="sprint" if k == sprint else "work", t_start=start,
            t_end=end, gap_before_s=gap, turn_t=tuple(start + i * step for i in range(turns[k - 1])),
            heartbeats=tuple(ticks(start, end, HEARTBEAT_S)), wake_before=("gap",) if k == long_gap else (),
            fault_points=({"kind": "kill", "session": k, "turn": kill[1]},) if k == kill[0] else (),
            long_sprint=k == sprint, min_tokens=sprint_floor(DEV_WINDOW) if k == sprint else 0,
            probe_point=k in cps))
    scale = Scale(name=golden.name, sessions=s, window=DEV_WINDOW, checkpoints=cps, kill=kill[0], swap=None,
                  restart=None, compaction=None, sprint_ranges=((sprint, sprint),),
                  long_gap_ranges=((long_gap, long_gap),))
    return Schedule(seed, golden.life, scale, WORLD_TZ, tuple(plans))


def build_golden(db, golden, schedule) -> dict[str, str]:
    """Build the golden life; returns micro_life fact id -> world fact id, sorted by key."""
    with atomic(db):
        if schedule.life != golden.life:
            raise ValueError("schedule life does not match the golden")
        _begin(db, schedule)
        ids = {key: mint(schedule, PROCESS, "entities", "entity", key, 0) for key in golden.entities}
        for key, (kind, name) in golden.entities.items():
            insert_entity(db, id=ids[key], kind=kind, canonical_name=name, aliases_json=[],
                          created_t=schedule.sessions[0].t_start, retired_t=None)
        principal = ids[golden.principal]
        write_corrections(db, schedule, [Chain(
            id=c["facts"][0], subject=ids[c["subject"]], key=c["key"], stem=c["stem"], depth=len(c["facts"]) - 1,
            token_kind=c["token_kind"], values=c["values"], at=c["at"]) for c in golden.chain], principal=principal)
        write_statements(db, schedule, [Statement(
            id=x["fact"], subject=ids[x["subject"]], key=x["key"], value=x["value"], token_kind=x["token_kind"],
            at=x["at"]) for x in golden.statement], principal=principal)
        write_commitments(db, schedule, [Commitment(
            id=c["fact"], subject=ids[c["subject"]], predicate=c["predicate"], stem=c["stem"], trigger=c["trigger"],
            cue_subject=ids[c["cue_subject"]], cue_key=c["cue_key"], cue_stem=c["cue_stem"], sender=ids[c["sender"]],
            made=c["made"], due=c["due"], channel="chat", notice_channel="chat") for c in golden.commitment],
            principal=principal)
        _finish(db, schedule, principal)
    mapping = {f: mint(schedule, "corrections", c["facts"][0], "fact", "value", j)
               for c in golden.chain for j, f in enumerate(c["facts"])}
    mapping |= {x["fact"]: mint(schedule, PROCESS, x["fact"], "fact", "value", 0) for x in golden.statement}
    mapping |= {c["fact"]: mint(schedule, "commitments", c["fact"], "fact", "made", 0) for c in golden.commitment}
    return dict(sorted(mapping.items()))
