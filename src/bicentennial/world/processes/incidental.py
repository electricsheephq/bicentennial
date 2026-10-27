"""Incidental details said once, each mixed with exactly `ratio` look-alike decoys."""

from dataclasses import dataclass

from ..scale import DECOY_MIN_RATIO, PROVISIONAL, TURNS
from . import LOW_SALIENCE, Unit, check_at, check_common, check_tokens, slot

DECOY_RATIO_LABEL = PROVISIONAL["decoy_ratio"]


@dataclass(frozen=True, kw_only=True)
class Detail:
    id: str
    subject: str
    predicate: str
    stem: str
    decoys: tuple[str, ...]
    token_kind: str = "code"
    channel: str = "chat"
    surfaces: tuple[str, ...] = ()
    at: tuple[tuple[int, int], ...] | None = None


def write_details(db, schedule, details, *, principal, ratio=DECOY_MIN_RATIO) -> None:
    if type(ratio) is not int or ratio < DECOY_MIN_RATIO:
        raise ValueError("decoy ratio is below the minimum")
    for d in (details := tuple(details)):
        if type(d.decoys) is not tuple or len(d.decoys) != ratio:
            raise ValueError("every detail needs exactly `ratio` decoys")
        if d.subject in d.decoys or len(set(d.decoys)) != len(d.decoys):
            raise ValueError("decoys must be distinct and differ from the subject")
        check_at(schedule, d.at, 1 + ratio)
    pairs = [(s, d.predicate) for d in details for s in (d.subject, *d.decoys)]
    if len(set(pairs)) != len(pairs):
        raise ValueError("details share a (subject, predicate) pair")
    check_common(db, schedule, [principal, *(s for s, _ in pairs)], details, [d.stem for d in details])
    for d in details:
        w = Unit(db, schedule, "incidental", d)
        for n, subject in enumerate((d.subject, *d.decoys)):
            t = slot(schedule, *(d.at[n] if d.at else (w.draw(f"session:{n}", 1, len(schedule.sessions)),
                                                       w.draw(f"turn:{n}", 1, TURNS))))
            e = w.event("detail", n, t, kind="statement", channel=d.channel, actor=principal, salience=LOW_SALIENCE)
            f, v = w.fact("detail", n, subject, d.predicate, d.stem)
            w.link(e, f, "assert", d.surfaces)
            w.attr(subject, d.predicate, v, t, e)
    check_tokens(db)
