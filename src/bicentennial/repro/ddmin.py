"""Delta debugging over shared twin event ids with deletion closure."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

Oracle = Callable[[tuple[str, ...], int], str | None]


def _ident(value):
    return type(value) is str and bool(value)


@dataclass(frozen=True)
class Constraints:
    groups: tuple[frozenset[str], ...] = ()
    requires: tuple[tuple[str, frozenset[str]], ...] = ()

    def __post_init__(self):
        if type(self.groups) is not tuple or type(self.requires) is not tuple:
            raise ValueError("constraints must be tuples")
        seen = set()
        for group in self.groups:
            if (type(group) is not frozenset or not group
                    or not all(_ident(e) for e in group) or seen & group):
                raise ValueError("groups must be nonempty, disjoint id sets")
            seen.update(group)
        for row in self.requires:
            if type(row) is not tuple or len(row) != 2:
                raise ValueError("requires must contain (derivative, sources) pairs")
            derivative, sources = row
            if (not _ident(derivative) or type(sources) is not frozenset
                    or not sources or not all(_ident(e) for e in sources)
                    or derivative in sources):
                raise ValueError("requires needs distinct, nonempty source ids")


NO_CONSTRAINTS = Constraints()


@dataclass(frozen=True)
class Shrink:
    kept: tuple[str, ...]
    failures: int
    runs: int
    tests: int
    exhausted: bool


def is_closed(kept, constraints: Constraints) -> bool:
    """Whether groups are atomic and every kept derivative has each source set."""
    kept = frozenset(kept)
    return (all(not (group & kept) or group <= kept for group in constraints.groups)
            and all(d not in kept or bool(sources & kept)
                    for d, sources in constraints.requires))


def _units(ids, constraints):
    known = frozenset(ids)
    for group in constraints.groups:
        if not group <= known:
            raise ValueError("unknown id in group")
    for derivative, sources in constraints.requires:
        if derivative not in known or not sources <= known:
            raise ValueError("unknown id in requires")
    grouped = {event: group for group in constraints.groups for event in group}
    units, seen = [], set()
    for event in ids:
        unit = grouped.get(event, frozenset((event,)))
        if unit not in seen:
            units.append(unit)
            seen.add(unit)
    return units


def _close(kept, units, constraints):
    while True:
        invalid = {d for d, sources in constraints.requires
                   if d in kept and not sources & kept}
        dropped = frozenset(e for unit in units if unit & invalid for e in unit)
        closed = kept - dropped
        if closed == kept:
            return closed
        kept = closed


class _BudgetReached(Exception):
    pass


def ddmin(ids: Sequence[str], oracle: Oracle, *, target: str,
          constraints: Constraints = NO_CONSTRAINTS, repeats: int = 3,
          threshold: int = 1, max_tests: int | None = None) -> Shrink:
    """Shrink a failing schedule; each distinct closed set gets all repeat attempts.

    The result is only 1-minimal under the deletions tested. Fault-point session
    rows are outside this event-id schedule and cannot be deleted here.
    Boolean integer parameters are refused with ValueError.
    """
    if (not isinstance(ids, Sequence) or isinstance(ids, (str, bytes))
            or not ids or not all(_ident(e) for e in ids)):
        raise ValueError("ids must be a nonempty sequence of nonempty strings")
    ids = tuple(ids)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate event id")
    if not _ident(target):
        raise ValueError("target must be a nonempty string")
    if type(repeats) is not int or repeats < 1:
        raise ValueError("repeats must be an integer >= 1")
    if type(threshold) is not int or not 1 <= threshold <= repeats:
        raise ValueError("threshold must be an integer in 1..repeats")
    if max_tests is not None and (type(max_tests) is not int or max_tests < 1):
        raise ValueError("max_tests must be None or an integer >= 1")
    if not isinstance(constraints, Constraints):
        raise ValueError("constraints must be Constraints")
    units = _units(ids, constraints)
    current = frozenset(ids)
    memo: dict[frozenset[str], int] = {}

    def fails(candidate):
        if not candidate:
            return False
        if candidate not in memo:
            if max_tests is not None and len(memo) == max_tests:
                raise _BudgetReached
            ordered = tuple(e for e in ids if e in candidate)
            memo[candidate] = sum(oracle(ordered, attempt) == target
                                  for attempt in range(repeats))
        return memo[candidate] >= threshold

    if not fails(current):
        raise ValueError("the full schedule does not reproduce target")
    n, exhausted = 2, False
    try:
        while True:
            active = [unit for unit in units if unit <= current]
            if len(active) < 2:
                break
            width, extra = divmod(len(active), n)
            chunks, start = [], 0
            for index in range(n):
                end = start + width + (index < extra)
                chunks.append(frozenset(e for unit in active[start:end] for e in unit))
                start = end
            for chunk in chunks:
                candidate = _close(chunk, units, constraints)
                if fails(candidate):
                    current, n = candidate, 2
                    break
            else:
                for chunk in chunks:
                    candidate = _close(current - chunk, units, constraints)
                    if fails(candidate):
                        current, n = candidate, max(n - 1, 2)
                        break
                else:
                    if n == len(active):
                        break
                    n = min(2 * n, len(active))
                continue
            # A successful subset restarts partitioning at two chunks.
    except _BudgetReached:
        exhausted = True
    return Shrink(tuple(e for e in ids if e in current), memo[current], repeats,
                  len(memo), exhausted)
