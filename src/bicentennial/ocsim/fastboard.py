"""Integer unit and cell sums from the model's cached item latents."""

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

from bicentennial.ocsim import model
from bicentennial.ocsim.board import BoardInputs


@dataclass(frozen=True)
class PairCell:
    n_valid: int
    s_sum: int
    control_valid: bool
    n_control: int
    f_sum: int
    c_sum: int


@dataclass(frozen=True)
class CellSums:
    cells: tuple[str, ...]
    pairs: tuple[str, ...]
    entries: dict[tuple[str, str], PairCell]
    assigned: dict[str, int]
    blocked: dict[str, int]
    coverage: dict[str, Fraction]
    shortfall: dict[str, str | None]


def _latents(latents, key, alloc):
    arm, pair, cell, ckpt = key
    unit = (pair, cell, ckpt)
    if unit not in latents or arm not in latents[unit]:
        raise ValueError(f"missing latents: {key}")
    if (cell, ckpt) not in alloc:
        raise ValueError(f"bad alloc or target key: {key}")
    values = latents[unit][arm]
    n, m = len(values), alloc[cell, ckpt]
    if n != m:
        raise ValueError(f"unit {unit} has {n} latents, alloc says {m}")
    return values


def _minimum(cell: model.CellModel, theta, eta0, eta1):
    # Addition and the ordered item map are monotone, including at cut ties.
    eta = min(eta0, eta1)
    return model.item_pair(cell, theta, eta, eta)[0]


def control_sums(params: model.LatentParams, latents, targets, solver, *, alloc
                 ) -> dict[tuple[str, str, str, int], int]:
    result = {}
    for key, target in sorted(targets.items()):
        if key[0] not in ("F", "C"):
            raise ValueError("control targets must be F or C units")
        values = _latents(latents, key, alloc)
        cell = params.cell(key[2])
        theta = solver(cell, target)
        result[key] = sum(_minimum(cell, theta, *eta) for eta in values)
    return result


def system_sums(params: model.LatentParams, latents, targets, status, solver, *, alloc
                ) -> dict[tuple[str, str, int], int | None]:
    result = {}
    for key, target in sorted(targets.items()):
        if key[0] != "S":
            raise ValueError("system targets must be S units")
        values = _latents(latents, key, alloc)
        _, pair, cell_id, ckpt = key
        states = []
        for branch in ("B0", "B1"):
            status_key = (pair, branch, ckpt)
            state = status.get(status_key)
            if state not in ("OK", "SYSTEM_FAILURE", "BLOCKED"):
                raise ValueError(f"bad or missing status: {status_key}")
            states.append(state)
        unit = (pair, cell_id, ckpt)
        if "BLOCKED" in states:
            result[unit] = None
        elif states == ["SYSTEM_FAILURE", "SYSTEM_FAILURE"]:
            result[unit] = 0
        else:
            cell = params.cell(cell_id)
            theta = solver(cell, target)
            if states == ["OK", "OK"]:
                result[unit] = sum(_minimum(cell, theta, *eta) for eta in values)
            else:
                result[unit] = sum(
                    min(0 if states[0] == "SYSTEM_FAILURE" else x0,
                        0 if states[1] == "SYSTEM_FAILURE" else x1)
                    for x0, x1 in (model.item_pair(cell, theta, *eta) for eta in values)
                )
    return result


def cell_sums(control, system, control_failed, swap, alloc, pairs, *, units: str) -> CellSums:
    if units not in ("all", "pre_swap"):
        raise ValueError('units must be "all" or "pre_swap"')
    pairs = tuple(pairs)
    if any(pair not in swap for pair in pairs):
        raise ValueError("swap and block_of must name every pair")
    # Check all supplied allocation units, even ones excluded by pre_swap.
    for pair in sorted(pairs):
        for cell, ckpt in sorted(alloc):
            for arm in ("F", "C", "S"):
                key = (pair, cell, ckpt) if arm == "S" else (arm, pair, cell, ckpt)
                if key not in (system if arm == "S" else control):
                    raise ValueError(f"missing unit sum: {key}")
    cells = tuple(sorted({cell for cell, _ in alloc}))
    entries, assigned, blocked = {}, {}, {}
    for cell in cells:
        assigned[cell] = blocked[cell] = 0
        for pair in sorted(pairs):
            retained = [(cell, c) for k, c in sorted(alloc) if k == cell
                        and (units == "all" or c < swap[pair])]
            valid = [(k, c) for k, c in retained if system[pair, k, c] is not None]
            n_valid = sum(alloc[key] for key in valid)
            n_retained = sum(alloc[key] for key in retained)
            assigned[cell] += n_retained
            blocked[cell] += sum(alloc[k, c] for k, c in retained
                                 if system[pair, k, c] is None)
            common = valid if n_valid else retained
            entries[cell, pair] = PairCell(
                n_valid, sum(system[pair, k, c] for k, c in valid),
                ("F", pair) not in control_failed and ("C", pair) not in control_failed,
                n_valid if n_valid else n_retained,
                sum(control["F", pair, k, c] for k, c in common),
                sum(control["C", pair, k, c] for k, c in common),
            )
    coverage = {k: Fraction(assigned[k] - blocked[k], assigned[k]) if assigned[k]
                else Fraction(1) for k in cells}
    shortfall = {k: "infrastructure" if coverage[k] < Fraction(95, 100) else None
                 for k in cells}
    return CellSums(cells, pairs, entries, assigned, blocked, coverage, shortfall)


def to_board_inputs(cs: CellSums, block_of: Mapping[str, int]) -> BoardInputs:
    if any(pair not in block_of for pair in cs.pairs):
        raise ValueError("swap and block_of must name every pair")
    scores, controls = {}, {}
    for key, entry in sorted(cs.entries.items()):
        if entry.n_valid:
            scores[key] = Fraction(entry.s_sum, 10 * entry.n_valid)
        if entry.control_valid and entry.n_control:
            controls[key] = (Fraction(entry.f_sum, 10 * entry.n_control),
                             Fraction(entry.c_sum, 10 * entry.n_control))
    # Each cell's pairs in block order, as board.assemble returns them.
    ordered = tuple(sorted(cs.pairs, key=lambda pair: (block_of[pair], pair)))
    return BoardInputs(
        {k: ordered for k in cs.cells}, scores, controls, dict(cs.coverage),
        dict(cs.shortfall), {p: block_of[p] for p in sorted(cs.pairs)},
        dict(cs.assigned), dict(cs.blocked),
    )
