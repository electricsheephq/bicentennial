"""Pure fixture allocation over planned occupancy, never background occupancy.

TUE scans made slots in keyed order, at the original seed and attempt zero.
The unchanged commitments._plan predicts made, trigger, cancel and lure events;
bridge and close are bounds, not events for an event-trigger commitment.
"""

from collections import Counter
from dataclasses import asdict, dataclass, replace

from bicentennial.canon import canon
from bicentennial.genres.g1_software.world import KINDS, TEAM_NAMES, Statement
from bicentennial.genres.g2_assistant.preferences import Pref
from bicentennial.items.bindings import Binding
from bicentennial.items.protocol import CELL_IDS, DEFERRED_CELLS
from bicentennial.items.templates.g1 import TEMPLATES as G1
from bicentennial.items.templates.g2 import TEMPLATES as G2
from bicentennial.keyed import shuffle, uniform_int

from . import unit
from .processes import Unit, mint
from .processes.commitments import Commitment, _plan
from .processes.corrections import Chain
from .processes.incidental import Detail
from .scale import TURNS, named
from .schedule import build_schedule
from .targeted import seed_text

MODIFIERS = "amber azure coral ebony ivory lilac ochre olive pearl russet silver umber violet walnut".split()
G1_NOUNS = {
    "milestone": "cutover handoff launch rollout preview delivery",
    "constant": "buffer cadence ceiling interval margin quota",
    "decision": "adapter broker codec dispatcher gateway scheduler",
    "commitment": "approval review signoff inspection handover acceptance",
    "ticket": "backfill cleanup compaction indexing profiling recovery",
}
LEXICONS = {k: tuple(f"{a}_{b}" for a in MODIFIERS for b in nouns.split())
            for k, nouns in G1_NOUNS.items()}
BANDS = {"person": ("Person", 130, 999), "place": ("Place", 500, 999),
         "purchase": ("Parcel", 300, 999), "trip": ("Trip", 200, 999)}
CONTEXTS = tuple((domain, ref) for domain in ("seat", "meal") for ref in (
    "coastal_hop", "overnight_route", "regional_visit", "winter_break", "summer_break",
    "conference_visit", "family_visit", "weekend_away", "morning_departure", "evening_departure",
    "island_hop", "mountain_trip", "city_break", "early_connection", "late_connection",
    "return_journey", "outbound_journey", "holiday_route", "business_visit", "festival_visit"))


def qualname(t):
    return f"{type(t).__module__}.{type(t).__qualname__}"


@dataclass(frozen=True)
class Shape:
    mode: str
    kinds: tuple[str, ...]
    count: int
    key: str = "value"
    stem: str = "CONST"
    depth: int = 1
    mention: str | None = None


FACTORIES = {
    "g1.drift_chain.DriftChain": lambda t: Shape("chain", ("milestone",), 2, "deadline", "DUE"),
    "g1.drift_action.DriftAction": lambda t: Shape("config", ("constant",), 2),
    "g1.drift_action.DriftQuote": lambda t: Shape("quote", ("constant",), 2, depth=0, mention="quote"),
    "g1.recall_value.RecallValue": lambda t: Shape("statement", ("decision",), 1, "choice", "DECISION"),
    "g1.wake_open_loop.WakeLoop": lambda t: Shape("statement", ("decision",), 1, "choice", "DECISION"),
    "g1.tuesday_trigger.TuesdayTrigger": lambda t: Shape("tue", ("commitment", "ticket", "ticket"), 4),
    "g2.tuesday_trigger.TuesdayTrigger": lambda t: Shape("tue", ("trip", "purchase", "purchase"), 4),
    "g2.recall_count.RecallCount": lambda t: Shape("chain", ("trip",), 2, "date", "DATE"),
    "g2.recall_count.DriftAsOf": lambda t: Shape("pref", (), 2, stem="SEAT"),
    "g2.drift_booking.DriftBooking": lambda t: Shape(
        "pref", (), 2, stem="SEAT", depth=0 if t.control else 1, mention="hedge" if t.control else None),
    "g2.keep_incidental.KeepIncidental": lambda t: Shape("detail", ("place",) * 4, 4, "gate_code", "GATE"),
    "g2.keep_forget.KeepForget": lambda t: Shape("forget", ("person",), 3),
    "g2.keep_forget.KeepNeighbour": lambda t: Shape("neighbour", ("person",) * 4, 6, "birthday", "BDAY"),
}
FACTORIES = {"bicentennial.items.templates." + k: v for k, v in FACTORIES.items()}
CUES = {k: "trigger" for k in FACTORIES if k.endswith(".TuesdayTrigger")}


@dataclass(frozen=True)
class Entity:
    id: str
    kind: str
    key: str
    name: str


@dataclass(frozen=True)
class Event:
    part: str
    at: tuple[int, int]
    removed: bool = False
    changed: bool = False


@dataclass(frozen=True)
class Forget:
    key: str
    subject: str
    covered: tuple = (("address", "ADDR"),)
    neighbours: tuple = (("birthday", "BDAY"),)
    summaries: int = 1
    at: tuple = ()


@dataclass(frozen=True)
class Fixture:
    key: str
    cell: str
    checkpoint: int
    template: str
    mode: str
    entities: tuple[Entity, ...]
    calls: tuple
    events: tuple[Event, ...]
    binding: Binding
    subject: str


@dataclass(frozen=True)
class Plan:
    fixtures: tuple[Fixture, ...]
    offsets: tuple[tuple[str, int, int], ...]
    fork: int | None
    names: tuple[tuple[str, int, int], ...] = ()

    @property
    def bindings(self):
        return tuple(f.binding for f in self.fixtures)

    @property
    def removed(self):
        return tuple(e.at for f in self.fixtures for e in f.events if e.removed)


def validate_budget(budget):
    if type(budget) is not list:
        raise ValueError("budget:shape")
    seen = set()
    for row in budget:
        if (type(row) is not list or len(row) != 3 or type(row[0]) is not str
                or row[0] not in CELL_IDS or row[0] in DEFERRED_CELLS
                or type(row[1]) is not int or row[1] not in named("full").checkpoints
                or type(row[2]) is not int or row[2] < 1 or tuple(row[:2]) in seen):
            raise ValueError("budget:shape")
        seen.add(tuple(row[:2]))


def eligible(genre, cell, k, registry=None):
    if genre not in ("G1", "G2"):
        raise ValueError("genre")
    return tuple(t for t in (registry if registry is not None else G1 if genre == "G1" else G2)
                 if t.cell_id == cell and qualname(t) in FACTORIES
                 and qualname(t).split(".")[-3] == genre.lower()
                 and (not getattr(t, "fault", False) or k >= named("full").kill))


def window(k):
    return 1, k - 2


def _draw(s, key, purpose, lo, hi):
    return uniform_int(s.seed, unit(s.life, "fixture-plan", key), 0, purpose, lo, hi)


def _names(genre, s, demand):
    pools = {}
    banned = {*KINDS, *TEAM_NAMES, *(n for names, _, _ in KINDS.values() for n in names)}
    for kind, n in sorted(demand.items()):
        if kind == "context":
            values = CONTEXTS
        elif genre == "G1":
            values = LEXICONS[kind]
            if any(v in banned or any(v.lower() in b.lower() or b.lower() in v.lower()
                                      for b in banned) for v in values):
                raise ValueError("plan:names")
        else:
            label, lo, hi = BANDS[kind]
            values = tuple(f"{label} {i:03d}" for i in range(lo, hi + 1))
        if n > len(values) or len(set(values)) != len(values):
            raise ValueError("plan:names")
        pools[kind] = shuffle(s.seed, unit(s.life, "fixture-plan", kind), 0, "names", values)
    return pools


def _place(s, key, k, count, load, reserved, *, lo=None, hi=None, removed=(), fault=False):
    a, b = window(k)
    a, b = a if lo is None else lo, b if hi is None else hi
    sessions = list(range(a, b + 1))
    if count > len(sessions):
        raise ValueError(f"plan:window:{key.split('/')[0]}@{k}")
    chosen = []
    for j in range(count):
        chosen.append(sessions.pop(_draw(s, key, f"session:{j}", 0, len(sessions) - 1)))
    out = []
    for j, session in enumerate(sorted(chosen)):
        turns = [(session, turn) for turn in range(1, TURNS + 1)
                 if (session, turn) not in reserved
                 and (j not in removed or not load[session, turn])
                 and not (lo == s.scale.kill and session == lo and turn == 1)
                 and not (fault and session == s.scale.kill and turn > 1)]
        if not turns:
            raise ValueError(f"plan:slots:{key.split('/')[0]}@{k}")
        minimum = min(load[p] for p in turns)
        turns = [p for p in turns if load[p] == minimum]
        at = turns[_draw(s, key, f"turn:{j}", 0, len(turns) - 1)]
        load[at] += 1
        if j in removed:
            reserved.add(at)
        out.append(at)
    return tuple(out)


def _tue(s, key, k, entities, load, reserved):
    g1 = entities[0].kind == "commitment"
    turns = [n for n in range(1, TURNS + 1) if (k, n) not in reserved]
    if not turns:
        raise ValueError(f"plan:slots:TUE-EVENT@{k}")
    minimum = min(load[k, n] for n in turns)
    turns = [n for n in turns if load[k, n] == minimum]
    due_turn = turns[_draw(s, key, "due-turn", 0, len(turns) - 1)]
    base = Commitment(id=key, subject=entities[0].id, predicate="deliver" if g1 else "book",
                      stem="TASK" if g1 else "TRIP", trigger="event", cue_subject=entities[1].id,
                      cue_key="status" if g1 else "delivery", cue_stem="TICKET" if g1 else "PARCEL",
                      sender="", lures=(entities[2].id,), cancelled=True,
                      notice_channel="chat" if g1 else "mail", due=(k, due_turn))
    positions = {t: (p.index, n) for p in s.sessions for n, t in enumerate(p.turn_t, 1)}
    candidates = [(a, n) for a in range(1, k - 2) for n in range(1, TURNS)]
    for made in shuffle(s.seed, unit(s.life, "fixture-plan", key), 0, "made", candidates):
        spec = replace(base, made=made)
        try:
            tc, to, _, _, tx, lures = _plan(Unit(None, s, "commitments", spec), spec)
        except ValueError:
            continue
        ordinary, cancel = [positions[t] for t in (tc, to, *lures)], positions[tx]
        if cancel[0] > k - 2 or load[cancel] or cancel in ordinary or any(p in reserved for p in ordinary):
            continue
        events = tuple(Event(part, at, part == "cancel", part == "cancel") for part, at in
                       zip(("made", "trigger", "lure", "cancel"), (*ordinary, cancel), strict=True))
        for e in events:
            load[e.at] += 1
        reserved.add(cancel)
        return spec, events
    raise ValueError(f"plan:slots:TUE-EVENT@{k}")


def _fixture(genre, s, t, shape, key, k, pools, load, reserved):
    entities = []
    for j, kind in enumerate(shape.kinds):
        ek = f"{key}/entity/{j}"
        ident = mint(s, "fixture-plan", ek, "entity", kind, 0) if genre == "G1" else mint(
            s, "g2-entities", kind, "entity", ek, 0)
        entities.append(Entity(ident, kind, ek, pools[kind].pop()))
    entities = tuple(entities)
    subject = entities[0].id if entities else ""
    mode, calls = shape.mode, []
    if mode == "tue":
        spec, events = _tue(s, key, k, entities, load, reserved)
        calls.append(("commitments", spec))
        fields = dict(commitment_id=key)
    else:
        fault = getattr(t, "fault", False)
        post = qualname(t).endswith(".DriftChain") and not fault and k >= s.scale.kill
        removed = (shape.count - 1,) if mode == "forget" and t.twin_type == "trigger" else ()
        at = _place(s, key, k, shape.count, load, reserved,
                    lo=s.scale.kill if post else None, hi=s.scale.kill if fault else None,
                    removed=removed, fault=fault)
        changed = (shape.count - 1 if mode in ("chain", "config", "forget") else 0)
        events = tuple(Event(str(j), p, j in removed, t.twin_type is not None and j == changed)
                       for j, p in enumerate(at))
        if mode in ("chain", "config", "quote"):
            calls.append(("corrections", Chain(id=key, subject=subject, key=shape.key, stem=shape.stem,
                                               depth=shape.depth, mention=shape.mention, at=at)))
            fields = dict(chain_id=key)
            if qualname(t).endswith(".DriftChain"):
                fields["depth"] = shape.depth
            if genre == "G2":
                fields = dict(entity_kind=entities[0].kind, entity_key=entities[0].key, attr_key=shape.key)
            if mode == "config":
                calls.append(("commit", key))
                events += (Event("commit", at[0]),)
                load[at[0]] += 1
        elif mode == "statement":
            calls.append(("statements", Statement(id=key, subject=subject, key=shape.key, stem=shape.stem, at=at[0])))
            fields = dict(statement_id=key)
        elif mode == "pref":
            domain, ref = pools["context"].pop()
            calls.append(("preferences", Pref(id=key, domain=domain, scope=("context", ref), stem=shape.stem,
                                               depth=shape.depth, mention=shape.mention, at=at)))
            subject = mint(s, "g2-entities", "preference", "entity", f"pref-{key}", 0)
            fields = dict(pref_id=key)
            # Controls flip the initial assert, updated preferences the correction.
            events = tuple(replace(e, changed=t.twin_type is not None and j == shape.depth)
                           for j, e in enumerate(events))
        else:
            if mode in ("detail", "neighbour"):
                calls.append(("details", Detail(id=key, subject=subject, predicate=shape.key, stem=shape.stem,
                                                decoys=tuple(e.id for e in entities[1:]), at=at[:4])))
                fields = dict(detail_id=key)
            if mode in ("forget", "neighbour"):
                calls.append(("forget", Forget(key=key, subject=subject, at=at if mode == "forget" else at[4:],
                    neighbours=(("birthday", "BDAY"),) if mode == "forget" else (("phone", "PHONE"),),
                    summaries=1 if mode == "forget" else 0)))
                fields = dict(forget_key=key)
                if mode == "neighbour":
                    fields["predicate"] = "birthday"
    return Fixture(key, t.cell_id, k, qualname(t), mode, entities, tuple(calls), events,
                   Binding(t.template_id, tuple(fields.items()), k), subject)


def predicted_fork(fixtures):
    return min((e.at[0] for f in fixtures for e in f.events if e.changed), default=None)


def plan(genre, schedule, budget, registry) -> Plan:
    validate_budget(budget)
    selected, offsets, demand = [], [], Counter()
    for cell, k, n in sorted(budget):
        choices = eligible(genre, cell, k, registry)
        if not choices:
            raise ValueError(f"plan:no_template:{cell}@{k}")
        offset = _draw(schedule, f"{cell}@{k}", "rotation", 0, len(choices) - 1)
        offsets.append((cell, k, offset))
        for j in range(n):
            t = choices[(offset + j) % len(choices)]
            shape = FACTORIES[qualname(t)](t)
            selected.append((t, shape, f"{cell}/{k}/{j}", k))
            demand.update(shape.kinds)
            demand["context"] += shape.mode == "pref"
    if not any(k == 20 and t.twin_type is not None for t, _, _, k in selected):
        raise ValueError("budget:no_fork")
    demand = +demand
    pools = _names(genre, schedule, demand)
    supply = tuple((kind, n, len(pools[kind])) for kind, n in sorted(demand.items()))
    load, reserved = Counter(), set()
    fixtures = tuple(_fixture(genre, schedule, t, shape, key, k, pools, load, reserved)
                     for t, shape, key, k in selected)
    names = [e.name for f in fixtures for e in f.entities]
    if genre == "G1" and any(a in b for i, a in enumerate(names) for j, b in enumerate(names) if i != j):
        raise ValueError("plan:names")
    fork = predicted_fork(fixtures)
    if fork is None or fork > 20:
        raise ValueError("plan:fork")
    return Plan(fixtures, tuple(offsets), fork, supply)


def plan_json(p):
    histogram = Counter(e.at[0] for f in p.fixtures for e in f.events)
    prompts = {}
    for f in p.fixtures:
        signature = "fixed" if f.mode == "tue" or f.template.endswith(".WakeLoop") else f.key
        prompts.setdefault((f.cell, f.checkpoint), set()).add(signature)
    return canon(asdict(p) | dict(bindings=[asdict(b) for b in p.bindings], removed=p.removed,
        histogram=[[k, n] for k, n in sorted(histogram.items())],
        prompt_distinctness=[[c, k, len(v)] for (c, k), v in sorted(prompts.items())],
        tue_distance_note="Only the trigger is exempt; compiled distance_sessions remains 0.")) + b"\n"


def sweep(genre, lives, budget):
    result = []
    for life, seed in lives:
        try:
            p = plan(genre, build_schedule(seed_text(seed), life, named("full")), budget,
                     G1 if genre == "G1" else G2)
        except ValueError as error:
            result.append(dict(life=life, seed=seed, fork=None, refusal=str(error)))
        else:
            result.append(dict(life=life, seed=seed, fork=p.fork, refusal=None))
    return tuple(result)
