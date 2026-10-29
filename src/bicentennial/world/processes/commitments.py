"""Commitments with time, event and hidden-cue triggers, lures and cancellations."""

from dataclasses import dataclass

from bicentennial.keyed import choice, shuffle

from ..db import insert_commitment
from ..lineage import atomic
from ..scale import TURNS
from . import NUMBER, Unit, check_common, check_tokens, pair, slot, token_value

TRIGGERS = ("time", "event", "cue")


@dataclass(frozen=True, kw_only=True)
class Commitment:
    id: str
    subject: str
    predicate: str
    stem: str
    trigger: str
    cue_subject: str | None = None
    cue_key: str | None = None
    cue_stem: str | None = None
    sender: str | None = None
    lures: tuple[str, ...] = ()
    cancelled: bool = False
    channel: str = "chat"
    notice_channel: str = "mail"
    surfaces: tuple[str, ...] = ()
    made: tuple[int, int] | None = None
    due: tuple[int, int] | None = None


def _plan(w, c) -> tuple:
    """Keyed slots at attempt 0; no draw reads `cancelled` or a drawn part's slot."""
    schedule, s, seed, u = w.schedule, len(w.schedule.sessions), w.schedule.seed, w.u
    a, turn = w.draw("made-session", 1, s - 1), w.draw("made-turn", 1, TURNS - 1)
    due = c.due or (w.draw("due-session", a + 1, s), 1 if c.trigger == "time" else w.draw("trigger-turn", 1, TURNS))
    t_c, t_open = slot(schedule, *(c.made or (a, turn))), slot(schedule, *due)
    if t_c >= t_open:
        raise ValueError("made must be strictly before due")
    t_close = schedule.sessions[due[0] - 1].t_end
    times = [slot(schedule, k, n) for k in range(1, s + 1) for n in range(1, TURNS + 1)]
    inside = [t for t in times if t_c < t < t_open]
    lure_slots = [t for t in times if t_c < t < t_close and t != t_open]
    if not inside or len(lure_slots) < len(c.lures):
        raise ValueError("no bridge or cancel slot, or too few lure slots")
    return (t_c, t_open, t_close, choice(seed, u, 0, "bridge", inside), choice(seed, u, 0, "cancel", inside),
            sorted(shuffle(seed, u, 0, "lures", lure_slots)[:len(c.lures)]))


def write_commitments(db, schedule, commitments, *, principal) -> None:
    with atomic(db):
        _write_commitments(db, schedule, commitments, principal=principal)


def _write_commitments(db, schedule, commitments, *, principal) -> None:
    for c in (commitments := tuple(commitments)):
        if c.trigger not in TRIGGERS:
            raise ValueError("unknown trigger")
        if any((x is None) != (c.trigger == "time") for x in (c.cue_subject, c.cue_key, c.cue_stem, c.sender)):
            raise ValueError("cue fields are required exactly for event and cue triggers")
        if (type(c.lures) is not tuple or (c.trigger == "time" and c.lures) or c.cue_subject in c.lures
                or len(set(c.lures)) != len(c.lures)):
            raise ValueError("lures must be distinct non-cue subjects of an event or cue trigger")
        if type(c.cancelled) is not bool or any(p is not None and (type(p) is not tuple or len(p) != 2)
                                                 for p in (c.made, c.due)):
            raise ValueError("cancelled must be a bool, and made and due (session, turn) pairs")
    check_common(db, schedule, [principal, *(e for c in commitments for e in (
        c.subject, c.cue_subject, c.sender, *c.lures) if e is not None)], commitments,
        [s for c in commitments for s in (c.stem, c.cue_stem) if s is not None])
    if len(schedule.sessions) < 2:
        raise ValueError("commitments need at least two sessions")
    units = [Unit(db, schedule, "commitments", c) for c in commitments]
    for w, (t_c, t_open, t_close, t_b, t_x, t_lures) in zip(units, [_plan(w, w.spec) for w in units], strict=True):
        c = w.spec
        lure_ids = [w.id("event", "lure", j) for j in range(len(c.lures))]
        e_c = w.event("made", 0, t_c, kind="statement", channel=c.channel, actor=principal)
        f_c, v_c = w.fact("made", 0, c.subject, c.predicate, c.stem,
                          value=token_value(db, schedule, "commitments", c.id, "made", 0, c.stem, paired=True))
        w.link(e_c, f_c, "assert", c.surfaces)
        # The row reserves the cancellation's number and value before any other draw, cancelled or not.
        insert_commitment(db, fact_id=f_c, trigger_kind=c.trigger, window_open_t=t_open,
                          window_close_t=t_close, lures_json=lure_ids)
        if c.trigger != "time":
            f_t = w.fact("cue", 0, c.cue_subject, c.cue_key, c.cue_stem)[0]
            if c.trigger == "event":
                w.link(e_c, f_t, "assert")
            else:
                w.link(e_b := w.event("bridge", 0, t_b, kind="statement", channel=c.channel, actor=principal),
                       f_t, "assert")
                w.link(e_b, f_c, "mention")
            e_t = w.event("trigger", 0, t_open, kind="notice", channel=c.notice_channel, actor=c.sender)
            w.link(e_t, f_t, "mention")
            for j, (t, subject) in enumerate(zip(t_lures, c.lures, strict=True)):
                e_l = w.event("lure", j, t, kind="notice", channel=c.notice_channel, actor=c.sender)
                w.link(e_l, w.fact("lure", j, subject, c.cue_key, c.cue_stem)[0], "assert")
        if c.cancelled:  # its number and value were reserved in both twins, so no other token moves
            w.link(e_x := w.event("cancel", 0, t_x, kind="statement", channel=c.channel, actor=principal),
                   f_c, "retract")
            w.link(e_x, w.fact("cancel", 0, c.subject, c.predicate, c.stem, polarity="negate",
                               value=f"{c.stem}-{pair(schedule, int(NUMBER.findall(v_c)[0]))}")[0],
                   "assert", c.surfaces)
    check_tokens(db)
