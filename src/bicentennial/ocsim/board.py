"""Exact board scores, common control bundles and infrastructure coverage."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from bicentennial.ocsim.drift import ARMS
from bicentennial.ocsim.schedule import STATUSES, Prepared, Schedule


@dataclass(frozen=True)
class BoardInputs:
    pairs: dict[str, tuple[str, ...]]
    scores: dict[tuple[str, str], Fraction]
    controls: dict[tuple[str, str], tuple[Fraction, Fraction]]
    coverage: dict[str, Fraction]
    shortfall: dict[str, str | None]
    block_of: dict[str, int]
    assigned: dict[str, int]
    blocked: dict[str, int]


def bundle_value(x0: int, x1: int, s0: str, s1: str) -> int | None:
    """Apply each item's status before taking the twin minimum (S-20/S-21)."""
    if s0 == "BLOCKED" or s1 == "BLOCKED":
        return None
    return min(0 if s0 == "SYSTEM_FAILURE" else x0,
               0 if s1 == "SYSTEM_FAILURE" else x1)


def assemble(
    status: Mapping[tuple[str, str, int], str],
    control_failed: frozenset[tuple[str, str]],
    swap: Mapping[str, int],
    block_of: Mapping[str, int],
    items: Mapping[tuple[str, str, str, int], tuple[tuple[int, int], ...]],
    alloc: Mapping[tuple[str, int], int],
    *, units: str = "all",
) -> BoardInputs:
    """Keep scores in milli until the final exact conversion to raw points.

    Item zero takes B0's status and item one takes B1's. Controls use S's
    common valid bundles, falling back to all retained bundles if none survive.
    All returned dicts have sorted keys; each cell's pairs stay in block order.
    """
    if units not in ("all", "pre_swap"):
        raise ValueError('units must be "all" or "pre_swap"')
    for key, count in alloc.items():
        if (not isinstance(key, tuple) or len(key) != 2
                or not isinstance(key[0], str) or type(count) is not int or count < 0):
            raise ValueError(f"bad alloc entry: {key}")
    pairs = set(swap) | set(block_of) | {
        key[1] for key in items if isinstance(key, tuple) and len(key) == 4
    }
    if not pairs <= swap.keys() or not pairs <= block_of.keys():
        raise ValueError("swap and block_of must name every pair")
    expected = {(arm, pair, cell, c)
                for arm in ARMS for pair in pairs for cell, c in alloc}
    if items.keys() != expected:
        raise ValueError("items must cover every (arm, pair, cell, checkpoint) unit")
    for key in sorted(items):
        bundles = items[key]
        count = alloc[key[2], key[3]]
        if len(bundles) != count:
            raise ValueError(f"unit {key} has {len(bundles)} bundles, alloc says {count}")
        if any(len(bundle) != 2 or any(type(x) is not int or not -1000 <= x <= 1000
                                       for x in bundle) for bundle in bundles):
            raise ValueError("item scores must be ints in [-1000, 1000]")
    checkpoints = sorted({c for _, c in alloc})
    for pair in sorted(pairs):
        for branch in ("B0", "B1"):
            for c in checkpoints:
                key = (pair, branch, c)
                if status.get(key) not in STATUSES:
                    raise ValueError(f"bad or missing status: {key}")

    cells = sorted({cell for cell, _ in alloc})
    ordered_pairs = tuple(sorted(pairs, key=lambda pair: (block_of[pair], pair)))
    scores, controls, assigned, blocked = {}, {}, {}, {}
    for cell in cells:
        assigned[cell] = blocked[cell] = 0
        for pair in sorted(pairs):
            valid = []
            retained = []
            for k, c in sorted(alloc):
                if k != cell or (units == "pre_swap" and c >= swap[pair]):
                    continue
                assigned[cell] += alloc[k, c]
                s0, s1 = status[pair, "B0", c], status[pair, "B1", c]
                for system, floor, ceiling in zip(
                    items["S", pair, cell, c], items["F", pair, cell, c],
                    items["C", pair, cell, c], strict=True,
                ):
                    control = (min(floor), min(ceiling))
                    retained.append(control)
                    value = bundle_value(*system, s0, s1)
                    if value is None:
                        blocked[cell] += 1
                    else:
                        valid.append((value, *control))
            key = (cell, pair)
            if valid:
                scores[key] = Fraction(sum(value[0] for value in valid), 10 * len(valid))
            if ("F", pair) not in control_failed and ("C", pair) not in control_failed:
                common = [(value[1], value[2]) for value in valid] if valid else retained
                if common:
                    controls[key] = (
                        Fraction(sum(value[0] for value in common), 10 * len(common)),
                        Fraction(sum(value[1] for value in common), 10 * len(common)),
                    )
    coverage = {cell: Fraction(assigned[cell] - blocked[cell], assigned[cell])
                if assigned[cell] else Fraction(1) for cell in cells}
    shortfall = {cell: "infrastructure" if coverage[cell] < Fraction(95, 100) else None
                 for cell in cells}
    return BoardInputs(
        {cell: ordered_pairs for cell in cells}, scores, controls, coverage, shortfall,
        {pair: block_of[pair] for pair in sorted(pairs)}, assigned, blocked,
    )


def assemble_schedule(
    schedule: Schedule, prepared: Prepared,
    items: Mapping[tuple[str, str, str, int], tuple[tuple[int, int], ...]],
    alloc: Mapping[tuple[str, int], int], *, units: str = "all",
) -> BoardInputs:
    """Adapt a projected schedule without importing the model or certification."""
    return assemble(
        schedule.system, schedule.control_failed,
        {life.life: life.swap for life in prepared.design.lives},
        {life.life: index for index, life in enumerate(prepared.design.lives)},
        items, alloc, units=units,
    )
