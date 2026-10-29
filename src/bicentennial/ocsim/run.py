"""Frozen OC simulation, exact audits, phase barriers and resumable reduction.

Test seam: ``configure(config, constants=test_constants(**overrides))`` pins
tiny budgets to a config without changing RunConfig's public constructor.
The options are serialized to spawned workers and checkpoint hashes. Use
``copy_config(config, resume=True)`` to preserve them when resuming a test.
"""

import argparse
import json
import math
import multiprocessing
import os
import platform
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import asdict, dataclass, field, replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

from bicentennial import keyed
from bicentennial.canon import canon
from bicentennial.ocsim import (
    board,
    card,
    drift,
    fastboard,
    fastcert,
    locate,
    model,
    reserve,
    schedule,
)
from bicentennial.stats import certify, tcal
from bicentennial.stats.seeds import CERTIFY_NAME, CERTIFY_SEED

SIM_SEED = "bicentennial-ocsim-v1"
DRAWS = 10_000
LADDER = tuple((n, b) for n in (24, 32, 40, 48) for b in (150, 200, 250, 300))
R_MAIN, R_MAX = 10_000, 40_000
R_REPORT, R_SENS, R_SCREEN = 2_000, 2_000, 2_000
Z2 = Fraction("3.841458820694124")
Z2_SCREEN = Fraction("10.827566170662733")
SE_PERCENTILE_PPM, SE_STATISTIC = 950_000, "max"
AUDIT_PPM, AUDIT_CASES = 5_000, 4
CHUNK, CHUNK_LARGE, BUSY_POLL_S = 25, 5, 30
STEP_EXP, MAX_STEP_EXP = locate.STEP_EXP, locate.MAX_STEP_EXP
BOUND_MILLI = locate.BOUND_MILLI
GRID_LOW, GRID_HIGH = locate.GRID_LOW, locate.GRID_HIGH
KINDS, DRIFT_CASES = schedule.KINDS, drift.DRIFT_CASES
OUTCOMES = ("CERTIFIED", "DEFERRED", "NOT_CERTIFIED", "NO_CERTIFICATE")
VARIANTS = ("main", "reserve0", "tau0", "no_system_passovers", "inputs_low", "inputs_high")
_BUDGET_NAMES = ("DRAWS", "R_MAIN", "R_MAX", "R_REPORT", "R_SENS", "R_SCREEN",
                 "CHUNK", "CHUNK_LARGE", "BUSY_POLL_S", "SE_STATISTIC")


@dataclass(frozen=True)
class MarginConfig:
    name: str
    margins: tuple[tuple[str, int], ...]
    criterion: tuple[str, Fraction] | None


def margin_grid(required: tuple[str, ...]) -> tuple[MarginConfig, ...]:
    cells = tuple(sorted(required))
    bars = {0: ("le", Fraction(1, 20)), 10: ("ge", Fraction(4, 5))}
    return (tuple(MarginConfig(f"m{m}", tuple((k, m) for k in cells), bars.get(m))
                  for m in (0, 5, 10, 15))
            + tuple(MarginConfig(f"rot:{k}", tuple((j, -10 if j == k else 10) for j in cells),
                                 ("le", Fraction(1, 5))) for k in cells))


@dataclass(frozen=True)
class Alternative:
    name: str
    fc: drift.DriftScope
    s: drift.DriftScope
    units: str


ALTERNATIVES = {
    "LITERAL": Alternative("LITERAL", drift.LITERAL, drift.LITERAL, "all"),
    "ALL_UNITS": Alternative("ALL_UNITS", drift.LITERAL, drift.ALL_UNITS, "all"),
    "PRE_SWAP": Alternative("PRE_SWAP", drift.LITERAL, drift.LITERAL, "pre_swap"),
    "SWAP_GATE": Alternative("SWAP_GATE", drift.SWAP_GATE, drift.LITERAL, "all"),
}


def test_constants(**overrides):
    """Documented budget/chunk/statistic seam; overrides travel with the config."""
    if any(k not in _BUDGET_NAMES for k in overrides):
        raise ValueError("only budgets, chunk sizes, polling and SE_STATISTIC may be overridden")
    result = {name: globals()[name] for name in _BUDGET_NAMES}
    result.update(overrides)
    if result["SE_STATISTIC"] not in ("max", "pooled"):
        raise ValueError("SE_STATISTIC must be max or pooled")
    if any(type(v) is not int or v < 1 for k, v in result.items() if k != "SE_STATISTIC"):
        raise ValueError("test constants must be positive ints")
    if not (result["R_REPORT"] == result["R_SCREEN"] <= result["R_MAIN"] < result["R_MAX"]):
        raise ValueError("need R_REPORT = R_SCREEN <= R_MAIN < R_MAX")
    return result


# Prevent pytest from collecting the public seam when imported into a test.
test_constants.__test__ = False


@dataclass(frozen=True)
class RunConfig:
    alternatives: tuple[str, ...]
    workers: int
    variants: tuple[str, ...] = ("main", "reserve0", "tau0", "no_system_passovers")
    ladder: tuple[tuple[int, int], ...] = LADDER
    screen: bool = True
    resume: bool = False

    def __post_init__(self):
        if not self.alternatives:
            raise ValueError("alternatives must be named explicitly (D12 is open)")
        for name in self.alternatives:
            if name not in ALTERNATIVES:
                raise ValueError(f"unknown alternative: {name}")
        if len(set(self.alternatives)) != len(self.alternatives):
            raise ValueError("alternatives must be unique")
        if self.alternatives[0] != "LITERAL":
            raise ValueError("LITERAL must run first (S-27)")
        if type(self.workers) is not int or not 1 <= self.workers <= (os.cpu_count() or 1):
            raise ValueError("workers must be an int in [1, cpu_count]")
        for name in self.variants:
            if name not in VARIANTS:
                raise ValueError(f"unknown variant: {name}")
        if "main" not in self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must be unique and include main")
        if (not self.ladder or any(type(n) is not int or type(b) is not int or n < 1 or b < 1
                                   for n, b in self.ladder)
                or tuple(sorted(set(self.ladder))) != self.ladder):
            raise ValueError("ladder must be nonempty, unique and lexicographic")

    def budgets(self):
        return test_constants(**self.constants)

    @property
    def constants(self):
        return dict(getattr(self, "_constants", {}))

    @property
    def busy_marker(self):
        return getattr(self, "_busy_marker", ())

    @property
    def machine_class(self):
        return getattr(self, "_machine_class", "undeclared")


def configure(config, *, constants=None, busy_marker=None, machine_class=None):
    """Attach CLI metadata or documented test budgets to a fresh frozen config."""
    result = replace(config)
    object.__setattr__(result, "_constants", test_constants(**(
        config.constants if constants is None else constants)))
    object.__setattr__(result, "_busy_marker", config.busy_marker if busy_marker is None
                       else tuple(busy_marker))
    object.__setattr__(result, "_machine_class", config.machine_class if machine_class is None
                       else machine_class)
    return result


def copy_config(config, **changes):
    return configure(replace(config, **changes), constants=config.constants,
                     busy_marker=config.busy_marker, machine_class=config.machine_class)


@dataclass(frozen=True)
class RunInputs:
    """Parsed C9.1 data and exact source bytes for hashing/spawn.

    params/sensitivity_params hold model inputs; required, alloc_by_b and
    checkpoints declare scoring. lives/rows/lanes/passover/control_failure
    declare scheduling; probe_only declares reserve load. n_lives_floor,
    planning and c8_hash control eligibility. latent_flags are disclosures.
    source_bytes retain the original JSON; root locates the C-8 file set.
    """

    params: model.LatentParams
    latent_flags: tuple[str, ...]
    sensitivity_params: dict[str, model.LatentParams]
    required: tuple[str, ...]
    alloc_by_b: dict[int, dict[tuple[str, int], int]]
    checkpoints: tuple[int, ...]
    lives: tuple[schedule.LifeSpec, ...]
    rows: tuple[schedule.Row, ...]
    lanes: tuple[schedule.LaneCapacity, schedule.LaneCapacity]
    passover: schedule.PassOverRates
    control_failure: Fraction
    probe_only: reserve.ProbeOnlyLoad
    n_lives_floor: int
    planning: bool
    c8_hash: str
    source_bytes: bytes = field(repr=False)
    root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[3])


def _float(value, name):
    try:
        if not isinstance(value, str) or not value.lower().startswith(("0x", "-0x", "+0x")):
            raise ValueError
        result = float.fromhex(value)
        if not math.isfinite(result):
            raise ValueError
        return result
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"inputs: bad float in {name}") from None


def _params(data, name):
    cells = []
    for cell in data["cells"]:
        fields = {k: _float(cell[k], f"{name}.{k}")
                  for k in ("f0", "c0", "sigma_f", "sigma_c")}
        cells.append(model.CellModel(cell["cell"], tuple(cell["levels"]),
                                     tuple(_float(v, f"{name}.cuts") for v in cell["cuts"]),
                                     **fields))
    return model.LatentParams(tuple(cells),
                              *(_float(data[k], f"{name}.{k}")
                                for k in ("rho_x", "rho_a", "rho_t", "sigma_d2")),
                              None if data.get("sigma_r2") is None else
                              _float(data["sigma_r2"], f"{name}.sigma_r2"))


def _fraction(value, name):
    if (not isinstance(value, str) or not re.fullmatch(r"-?[0-9]+/[0-9]+", value)
            or int(value.split("/")[1]) == 0):
        raise ValueError(f"inputs: bad fraction in {name}")
    return Fraction(value)


def _parse_inputs(data: bytes, *, ladder=LADDER, root: Path | None = None) -> RunInputs:
    """Read data only. Tuple-key maps use sorted JSON rows [key..., value].

    Missing load rates inherit the slowest measured row/load rate (S-41).
    ``ladder`` is the validation seam used for tiny tests and custom ladders.
    """
    raw = json.loads(data)
    fields = ("params", "latent_flags", "sensitivity_params", "required", "alloc_by_b",
              "checkpoints", "lives", "rows", "lanes", "passover", "control_failure",
              "probe_only", "n_lives_floor", "planning", "c8_hash")
    for name in fields:
        if name not in raw:
            raise ValueError(f"inputs: missing {name}")
    params = _params(raw["params"], "params")
    required = tuple(raw["required"])
    if required != tuple(c.cell for c in params.cells):
        raise ValueError("required cells must equal the model's cells")
    checkpoints = tuple(raw["checkpoints"])
    alloc = {int(b): {(k, c): n for k, c, n in values}
             for b, values in sorted(raw["alloc_by_b"].items())}
    expected = {(k, c) for k in required for c in checkpoints}
    for b in sorted({b for _, b in ladder} | set(alloc)):
        if (b not in alloc or set(alloc[b]) != expected
                or len(raw["alloc_by_b"][str(b)]) != len(alloc[b])):
            raise ValueError(f"allocation for b = {b} must cover every (cell, checkpoint)")
        if any(type(n) is not int or n < 0 for n in alloc[b].values()):
            raise ValueError("allocations must be ints >= 0")
    lives = tuple(schedule.LifeSpec(
        life["life"], tuple(life["b0_tokens"]), tuple(life["b1_tokens"]),
        life["fork"], life["swap"], tuple(life["b0_probe_tokens"]),
        tuple(life["b1_probe_tokens"])) for life in raw["lives"])
    largest = max(n for n, _ in ladder)
    if len(lives) < largest:
        raise ValueError(f"need at least {largest} lives in the dry history set")
    rows = tuple(schedule.Row(r["row"], _fraction(r["rate"], "rows.rate")) for r in raw["rows"])
    lanes = tuple(schedule.LaneCapacity(**r) for r in raw["lanes"])
    load = raw["probe_only"]
    rates = {arm: _fraction(rate, f"probe_only.rates.{arm}")
             for arm, rate in sorted(load["rates"].items())}
    slowest = max([r.rate for r in rows] + list(rates.values()))
    for arm in (*reserve.PROBE_ONLY_LOAD, "anchor"):
        rates.setdefault(arm, slowest)
    probe = reserve.ProbeOnlyLoad({(a, who, branch, c): n
                                   for a, who, branch, c, n in load["tokens"]},
                                  dict(load["anchor_tokens"]), rates)
    reserve.lane_load(probe, lives, checkpoints)
    if tuple(lane.name for lane in lanes) != schedule.LANES:
        raise ValueError("lanes must be the pinned and swap lanes, in that order")
    passes = schedule.PassOverRates(*(_fraction(raw["passover"][k], f"passover.{k}")
                                      for k in ("failed", "blocked")))
    failure = _fraction(raw["control_failure"], "control_failure")
    # Validate durations and rates independently of reserve feasibility.
    schedule.prepare(schedule.ScheduleDesign(lives, rows, checkpoints,
                                             schedule.Capacity(1, 1), passes, failure))
    if type(raw["planning"]) is not bool:
        raise ValueError("planning must be a bool")
    if type(raw["n_lives_floor"]) is not int or raw["n_lives_floor"] < 1:
        raise ValueError("n_lives_floor must be a positive int")
    sensitivities = {k: _params(v, k) for k, v in sorted(raw["sensitivity_params"].items())}
    for name, value in sensitivities.items():
        if name not in ("inputs_low", "inputs_high"):
            raise ValueError(f"unknown variant: {name}")
        if tuple(c.cell for c in value.cells) != required:
            raise ValueError("required cells must equal the model's cells")
    return RunInputs(params, tuple(sorted(raw["latent_flags"])),
                     sensitivities,
                     required, alloc, checkpoints, lives, rows, lanes, passes, failure,
                     probe, raw["n_lives_floor"], raw["planning"], raw["c8_hash"], data,
                     root or Path(__file__).resolve().parents[3])


def parse_inputs(data: bytes, *, ladder=LADDER, root: Path | None = None) -> RunInputs:
    """Parse C9.1 JSON, including nested missing-field diagnostics."""
    try:
        return _parse_inputs(data, ladder=ladder, root=root)
    except KeyError as exc:
        raise ValueError(f"inputs: missing {exc.args[0]}") from None


def load_inputs(path: Path, *, ladder=LADDER, root=None) -> RunInputs:
    return parse_inputs(path.read_bytes(), ladder=ladder, root=root)


_C8_FIXED = tuple(sorted(
    [f"src/bicentennial/stats/{name}.py" for name in ("certify", "tcal", "variance_inputs")]
    + [f"src/bicentennial/runner/{name}.py" for name in ("dispatch", "occupancy")]
    + [f"tests/stats/test_{name}.py" for name in ("certify", "tcal", "variance_inputs")]
    + [f"tests/runner/test_{name}.py" for name in ("dispatch", "occupancy")]))
_C8_DIRS = ("src/bicentennial/ocsim", "tests/ocsim")


def c8_paths(root):
    return tuple(sorted((*_C8_FIXED, *(
        p.relative_to(root).as_posix() for directory in _C8_DIRS
        for p in (root / directory).rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"))))


def c8_hash(root: Path) -> str:
    entries = []
    for path in c8_paths(root):
        try:
            digest = sha256((root / path).read_bytes()).hexdigest()
        except FileNotFoundError:
            raise ValueError(f"C-8 file missing: {path}") from None
        entries.append([path, digest])
    return sha256(canon(entries)).hexdigest()


def _git(root, *args):
    try:
        result = subprocess.run(("git", *args), cwd=root, capture_output=True, check=False)
        return result.stdout.decode().strip() if result.returncode == 0 else None
    except OSError:
        return None


def c8_dirty(root):
    status = _git(root, "status", "--porcelain", "--", *_C8_DIRS, *_C8_FIXED)
    return status is None or bool(status)


def straddles(x, n, criterion, z2=Z2):
    _, bar = criterion
    c, d = bar.numerator, bar.denominator
    return (x * d - n * c)**2 <= z2 * n * c * (d - c)


def decision(x, n, criterion, *, maximum=R_MAX):
    direction, bar = criterion
    diff = x * bar.denominator - n * bar.numerator
    if n < maximum and straddles(x, n, criterion):
        return "EXTEND"
    passed = diff <= 0 if direction == "le" else diff >= 0
    return ("PASS_40K" if passed else "FAIL_40K") if n >= maximum else (
        "PASS" if passed else "FAIL")


def screened_out(x, n, criterion):
    direction, bar = criterion
    diff = x * bar.denominator - n * bar.numerator
    return not straddles(x, n, criterion, Z2_SCREEN) and (
        diff > 0 if direction == "le" else diff < 0)


def rate_stats(x, n):
    """Integer ppm display, with outward Wilson rounding at 10**12 scale."""
    if not n:
        return 0, 0, [0, 1_000_000]
    scale = 10**12
    z = Z2
    center = (Fraction(x) + z / 2) / (n + z)
    radius2 = z * (Fraction(x * (n - x), n) + z / 4) / (n + z)**2
    floor_root = math.isqrt(radius2.numerator * scale**2 // radius2.denominator)
    radius = Fraction(floor_root if Fraction(floor_root**2, scale**2) == radius2
                      else floor_root + 1, scale)
    lo = max(0, (center - radius) * 1_000_000)
    hi = min(1_000_000, (center + radius) * 1_000_000)
    return (round(Fraction(1_000_000 * x, n)),
            math.isqrt(x * (n - x) * 10**12 // n**3),
            [math.floor(lo), math.ceil(hi)])


def se_bound(values):
    """Nearest-rank 95th percentile followed by exact upward half-point rounding."""
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    q2 = values[tcal.index(len(values), SE_PERCENTILE_PPM)]
    q4 = 4 * q2
    k = math.isqrt(q4.numerator // q4.denominator)
    return Fraction(k if k * k == q4 else k + 1, 2)


class AuditMismatch(RuntimeError):
    pass


@dataclass
class PointContext:
    """Worker-local point state, never sent through a process queue.

    inputs/config/point/variant identify the run. bounds is per alternative.
    pairs/lives/prep, solver/tables and wcache cache deterministic setup;
    params/tau/alloc/grid/fc/swap/block_of feed evaluate. audits and solver_info
    collect integer diagnostics. trace is an optional test observer.
    """

    inputs: RunInputs
    config: RunConfig
    point: tuple[int, int]
    variant: str = "main"
    bounds: dict[str, Fraction] = field(default_factory=dict)
    solver: object = None
    tables: dict = field(default_factory=dict)
    trace: object = None

    def __post_init__(self):
        self.params = self.inputs.sensitivity_params.get(self.variant, self.inputs.params)
        self.pairs = tuple(f"pair-{i:03d}" for i in range(self.point[0]))
        self.lives = tuple(replace(life, life=p) for life, p in
                           zip(self.inputs.lives[:self.point[0]], self.pairs, strict=True))
        self.load = reserve.relabel(self.inputs.probe_only,
                                    self.inputs.lives[:self.point[0]], self.pairs)
        self.reserves = ((0, 0) if self.variant == "reserve0" else
                         reserve.reserves(self.load, self.lives, self.inputs.checkpoints))
        capacity = reserve.capacity(self.inputs.lanes, self.reserves)
        self.prep = schedule.prepare(schedule.ScheduleDesign(
            self.lives, self.inputs.rows, self.inputs.checkpoints, capacity,
            self.inputs.passover, self.inputs.control_failure, None,
            self.variant != "no_system_passovers"))
        if self.solver is None:
            self.tables = {c.cell: locate.build_table(c, self.params.rho_t) for c in self.params.cells}
            self.solver = self._solve
        self.wcache = fastcert.WeightCache.from_seed(self.pairs, CERTIFY_SEED, CERTIFY_NAME,
                                                    self.config.budgets()["DRAWS"])
        self.tau = {k: 0.0 for k in self.inputs.required} if self.variant == "tau0" else None
        self.alloc = self.inputs.alloc_by_b[self.point[1]]
        self.grid = margin_grid(self.inputs.required)
        self.fc = {c.cell: (c.f0, c.c0) for c in self.params.cells}
        self.swap = {life.life: life.swap for life in self.lives}
        self.block_of = {p: i for i, p in enumerate(self.pairs)}
        self.audits = {"replicates": 0, "certify_calls": 0, "fields_compared": 0, "mismatches": 0}
        self.solver_info = {}
        self.phase = "phase1"

    def _solve(self, cell, target):
        return locate.locate(self.tables[cell.cell], cell, target)


def case_ids(alternatives, required, *, reported=True):
    return tuple(f"{a}|{k}|{d.name}|{m.name}" for a in alternatives for k in KINDS
                 for d in DRIFT_CASES for m in margin_grid(required)
                 if reported or m.criterion is not None)


def audit_selected(rep):
    return keyed.uniform_int(SIM_SEED, ("ocsim", "audit"), rep, "audit", 0, 999_999) < AUDIT_PPM


def _scope(scope, arms, case):
    return ("none",) if case.name == "none" else tuple(sorted(
        entry for entry in scope.drifts if entry[0] in arms))


def _compare(ctx, rep, case, field_name, left, right):
    ctx.audits["fields_compared"] += 1
    if left != right:
        raise AuditMismatch(f"audit mismatch at rep {rep} case {case}: {field_name}")


def _audit(ctx, rep, case, sch, targets, cs, adm, dec, bound):
    alt = ALTERNATIVES[case.split("|")[0]]
    required = ctx.inputs.required
    items = model.sample_items(ctx.params, targets, ctx.alloc, ctx.pairs, SIM_SEED, rep,
                               solver=ctx.solver)
    reference = board.assemble_schedule(sch, ctx.prep, items, ctx.alloc, units=alt.units)
    _compare(ctx, rep, case, "board", fastboard.to_board_inputs(cs, ctx.block_of), reference)
    kwargs = dict(pairs=reference.pairs, scores=reference.scores, controls=reference.controls,
                  required=required,
                  eligibility={k: certify.Eligibility(False, reference.coverage[k],
                                                     reference.shortfall[k]) for k in required},
                  board=certify.Board("season", "text", True, *ctx.point),
                  seed=CERTIFY_SEED, name=CERTIFY_NAME, draws=ctx.wcache.draws,
                  bounds=certify.Bounds(*ctx.point, bound), block_of=reference.block_of)
    ref = certify.certify(**kwargs, admissions={k: "ADMITTED" for k in required})
    ctx.audits["certify_calls"] += 1
    ref_adm = {c.cell: certify.cell_admission(c, replace(
        c, verdict="UNRESOLVED", score_pairs=c.pairs, pooled_pairs=())) for c in ref.cells}
    _compare(ctx, rep, case, "admissions", adm, tuple(sorted(ref_adm.items())))
    if any(v != "ADMITTED" for v in ref_adm.values()):
        ref = certify.certify(**kwargs, admissions=ref_adm)
        ctx.audits["certify_calls"] += 1
    full = fastcert.decide(cs, ctx.wcache, required=required, se_bound=bound,
                           n_lives=ctx.point[0], b=ctx.point[1], mode="full", admissions=adm)
    _compare(ctx, rep, case, "outcome", full.outcome, ref.outcome)
    _compare(ctx, rep, case, "reasons", full.reasons, ref.reasons)
    _compare(ctx, rep, case, "se2", full.se2,
             tuple((c.cell, c.margin.se2 if c.margin else None) for c in ref.cells))
    estimates = (("mean", ref.mean_margin), *((c.cell, c.margin) for c in ref.cells))
    lowers = tuple((k, e.lower if e else None,
                    sorted(e.replicates)[tcal.index(ctx.wcache.draws, 50_000)] if e else None)
                   for k, e in estimates)
    _compare(ctx, rep, case, "lower", full.lower, lowers)
    cal = ref.outcome == "CERTIFIED"
    unc = (not any(reason.startswith(("se:", "coverage_", "blocked:", "not_admitted:",
                                      "admission_undefined:", "empty_")) for reason in ref.reasons)
           and all(v is not None and v >= (-10 if k != "mean" else 0) for k, _, v in lowers))
    _compare(ctx, rep, case, "certified", full.certified, (cal, unc))
    _compare(ctx, rep, case, "decide flags", (dec.outcome, dec.certified),
             (full.outcome, full.certified))


def evaluate(ctx: PointContext, rep: int, case_ids: Sequence[str], *,
             margins: Sequence[MarginConfig] | None = None) -> dict[str, fastcert.Decision]:
    """One pure replicate; caches share restricted scopes and undrifted decisions."""
    grid = {m.name: m for m in (ctx.grid if margins is None else margins)}
    effects = model.life_effects(ctx.params, ctx.pairs, SIM_SEED, rep)
    latents = model.bundle_latents(ctx.params, ctx.alloc, ctx.pairs, SIM_SEED, rep)
    draws = schedule.draw_all(ctx.prep, SIM_SEED, rep)
    expected0 = model.expected_units(ctx.params, effects, {k: 0 for k in ctx.inputs.required},
                                     tau=ctx.tau)
    expected_fc = {k: v for k, v in expected0.items() if k[0] in ("F", "C")}
    expected_s = {}
    for name in dict.fromkeys(c.split("|")[3] for c in case_ids):
        expected_s[name] = {k: v for k, v in model.expected_units(
            ctx.params, effects, dict(grid[name].margins), tau=ctx.tau).items() if k[0] == "S"}
    chosen = set()
    if audit_selected(rep):
        chosen.update(keyed.shuffle(SIM_SEED, ("ocsim", "audit-cases"), rep,
                                    "audit-cases", sorted(case_ids))[:AUDIT_CASES])
    if rep == 0 and ctx.phase.startswith("phase1"):
        chosen.update(c for c in case_ids if c.startswith("LITERAL|base|none|"))
    if chosen:
        ctx.audits["replicates"] += 1
    schedules, controls, systems, admissions, decisions = {}, {}, {}, {}, {}
    result = {}
    drift_cases = {d.name: d for d in DRIFT_CASES}
    for case in case_ids:
        alt_name, kind, drift_name, margin = case.split("|")
        alt, dc = ALTERNATIVES[alt_name], drift_cases[drift_name]
        if kind not in schedules:
            sch = schedule.project(ctx.prep, kind, draws)
            schedules[kind] = sch, schedule.unit_times(sch)
        sch, times = schedules[kind]
        ck = (kind, drift_name, _scope(alt.fc, ("F", "C"), dc))
        sk = (kind, drift_name, _scope(alt.s, ("S",), dc), margin)
        if ck not in controls:
            targets = drift.drifted_targets(ctx.fc, expected_fc, times, sch.post_swap,
                                             ctx.inputs.checkpoints, dc, alt.fc,
                                             t1_ms=sch.t1_ms,
                                             step_start_ms=sch.block_first[draws.step_block])
            controls[ck] = targets, fastboard.control_sums(
                ctx.params, latents, targets, ctx.solver, alloc=ctx.alloc)
        if sk not in systems:
            targets = drift.drifted_targets(ctx.fc, expected_s[margin], times, sch.post_swap,
                                             ctx.inputs.checkpoints, dc, alt.s,
                                             t1_ms=sch.t1_ms,
                                             step_start_ms=sch.block_first[draws.step_block])
            systems[sk] = targets, fastboard.system_sums(
                ctx.params, latents, targets, sch.system, ctx.solver, alloc=ctx.alloc)
        bound = ctx.bounds.get(alt_name, Fraction(10**9))
        key = ck, sk, alt.units, bound
        if key not in decisions:
            cs = fastboard.cell_sums(controls[ck][1], systems[sk][1], sch.control_failed,
                                     ctx.swap, ctx.alloc, ctx.pairs, units=alt.units)
            adm_key = ck, alt.units
            if adm_key not in admissions:
                admissions[adm_key] = fastcert.admissions(cs, ctx.wcache, required=ctx.inputs.required)
            adm = admissions[adm_key]
            dec = fastcert.decide(cs, ctx.wcache, required=ctx.inputs.required, se_bound=bound,
                                  n_lives=ctx.point[0], b=ctx.point[1], admissions=adm)
            decisions[key] = cs, adm, dec
        cs, adm, dec = decisions[key]
        if ctx.trace is not None:
            ctx.trace(case, controls[ck][1], systems[sk][1], cs)
        if case in chosen:
            _audit(ctx, rep, case, sch, controls[ck][0] | systems[sk][0], cs, adm, dec, bound)
        result[case] = dec
    return result


def solver_audit(ctx):
    """Rep-zero table diagnostic; only integer ppm-of-milli results escape."""
    effects = model.life_effects(ctx.params, ctx.pairs, SIM_SEED, 0)
    expected = model.expected_units(ctx.params, effects,
                                    {k: 0 for k in ctx.inputs.required}, tau=ctx.tau)
    candidates = [(a, p, k, c) for (a, p, k), target in sorted(expected.items())
                  if a == "S" and ctx.params.cell(k).levels[0] < target < ctx.params.cell(k).levels[-1]
                  for c in ctx.inputs.checkpoints]
    targets = {}
    errors = {k: 0.0 for k in ctx.inputs.required}
    for i in range(200):
        if not candidates:
            break
        unit = keyed.choice(SIM_SEED, ("ocsim", "solver-audit"), i, "solver-audit", candidates)
        a, p, k, _ = unit
        target, cell = expected[a, p, k], ctx.params.cell(k)
        theta = ctx.solver(cell, target)
        if isinstance(theta, str):
            raise AuditMismatch(f"solver audit at cell {k}: non-interior location milli")
        err = abs(model.expected_min(cell, ctx.params.rho_t, theta) - target)
        table = ctx.tables[k]
        if err > table.bound_milli + table.max_correction + 1e-6:
            raise AuditMismatch(f"solver audit at cell {k}: {err} milli")
        errors[k] = max(errors[k], err)
        targets[unit] = target
    approx = model.sample_items(ctx.params, targets, ctx.alloc, ctx.pairs, SIM_SEED, 0,
                                solver=ctx.solver)
    exact = model.sample_items(ctx.params, targets, ctx.alloc, ctx.pairs, SIM_SEED, 0, solver=None)
    info = {}
    for cell in ctx.params.cells:
        table = ctx.tables[cell.cell]
        comparisons = [(v, w) for key in sorted(approx) if key[2] == cell.cell
                       for xs, ys in zip(approx[key], exact[key], strict=True)
                       for v, w in zip(xs, ys, strict=True)]
        info[cell.cell] = {
            "step_exp": table.step_exp,
            "bound_milli_ppm": math.ceil(table.bound_milli * 1_000_000),
            "midpoint_error_ppm": math.ceil(locate.midpoint_error(table, cell) * 1_000_000),
            "audit_error_ppm": math.ceil(errors[cell.cell] * 1_000_000),
            "items_differ_ppm": round(Fraction(sum(x != y for x, y in comparisons) * 1_000_000,
                                               len(comparisons))) if comparisons else 0,
        }
    return info


@dataclass(frozen=True)
class ChunkResult:
    r0: int
    counts: dict[str, tuple[int, ...]]
    se2_max: dict[str, tuple[tuple[Fraction | None, tuple[Fraction, ...]], ...]]
    audits: dict[str, int]
    cpu_ms: int = 0


_WORKER = None


def _init(inputs_bytes, config, point, variant, nice):
    global _WORKER
    keyed.assert_hashseed()
    if nice and os.nice(0) < 19:
        os.nice(19 - os.nice(0))
    inputs = parse_inputs(inputs_bytes, ladder=config.ladder)
    _WORKER = PointContext(inputs, config, point, variant)


def _solver_task():
    return solver_audit(_WORKER)


def _worker_nice():
    """Owner-run process check for exit-10 etiquette."""
    return os.nice(0)


def _task(task, bounds):
    cpu_start = time.process_time()
    phase, r0, r1, ids = task
    ctx = _WORKER
    ctx.phase, ctx.bounds = phase, bounds
    ctx.audits = {k: 0 for k in ctx.audits}
    counts = {case: [0] * 7 for case in ids}
    is_bound = phase in ("phase0", "sensitivity_bound")
    values = {case: [] for case in ids} if is_bound else {}
    for rep in range(r0, r1):
        decisions = evaluate(ctx, rep, ids)
        for case in ids:
            dec = decisions[case]
            row = counts[case]
            row[0] += int(dec.certified[0])
            row[1] += int(dec.certified[1])
            row[2 + OUTCOMES.index(dec.outcome)] += 1
            row[6] += int(any(v == "NOT_ADMITTED" for _, v in dec.admissions))
            if is_bound:
                pooled = tuple(v for _, v in dec.se2 if v is not None)
                values[case].append((max(pooled) if pooled else None, pooled))
    return ChunkResult(r0, {k: tuple(v) for k, v in counts.items()},
                       {k: tuple(v) for k, v in values.items()}, dict(ctx.audits),
                       round((time.process_time() - cpu_start) * 1000))


def _encode(value):
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, dict):
        return {str(k): _encode(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(v) for v in value]
    return value


def _config_data(config):
    data = asdict(config)
    # Resume is transport, not a change to the statistical run.
    data.pop("resume")
    data["constants"] = config.budgets()
    data["busy_marker"] = config.busy_marker
    data["machine_class"] = config.machine_class
    data["frozen_constants"] = constants_manifest(config)
    return _encode(data)


def _marker(command):
    if not command:
        return 0
    code = subprocess.run(command, check=False, capture_output=True).returncode
    if code not in (0, 10, 11):
        raise ValueError(f"busy marker exited {code}")
    return code


def _pause_wait():
    """Test seam for the marker's sixty-second suspended poll."""
    time.sleep(60)


def _barrier_hook(point, variant, phase):
    """Test seam: may raise after a durable phase checkpoint."""


class _Pool:
    """One point/variant pool, rebuilt when marker width or niceness changes."""

    def __init__(self, inputs, config, point, variant, pauses, phases=None):
        self.inputs, self.config = inputs, config
        self.point, self.variant, self.pauses = point, variant, pauses
        self.executor = None
        self.mode = None
        self.width = config.workers
        self.phases = {} if phases is None else phases

    def close(self, *, terminate=False):
        if self.executor is not None:
            if terminate:
                self.executor.terminate_workers()
            else:
                self.executor.shutdown(wait=True, cancel_futures=True)
            self.executor = None

    def start(self, mode):
        self.width = min(2, self.config.workers) if mode == 10 else self.config.workers
        self.executor = ProcessPoolExecutor(
            max_workers=self.width, mp_context=multiprocessing.get_context("spawn"),
            initializer=_init, initargs=(self.inputs.source_bytes, self.config, self.point,
                                         self.variant, mode == 10))
        self.mode = mode

    def _observe(self, code):
        if code == self.mode:
            return
        if code == 11:
            self.pauses.append({"point": list(self.point), "variant": self.variant,
                                "event": "pause", "exit": 11})
        else:
            width = min(2, self.config.workers) if code == 10 else self.config.workers
            current = next((p["workers"] for p in reversed(self.pauses)
                            if p["event"] == "width"), self.config.workers)
            if width == current:
                return
            self.pauses.append({"point": list(self.point), "variant": self.variant,
                                "event": "width", "exit": code,
                                "workers": width})

    def results(self, tasks, bounds, *, solver=False):
        todo = list(tasks)
        pending = {}
        # Buffered results stay outside the pool so exit 11 cannot discard
        # already-reduced work. Unfinished tasks are resubmitted verbatim.
        try:
            while todo or pending:
                code = _marker(self.config.busy_marker)
                if code == 11:
                    self._observe(code)
                    self.mode = code
                    for task in pending.values():
                        todo.append(task)
                    pending.clear()
                    self.close(terminate=True)
                    todo.sort(key=lambda task: task[1])
                    while code == 11:
                        _pause_wait()
                        code = _marker(self.config.busy_marker)
                    self._observe(code)
                    self.start(code)
                    continue
                if self.executor is None:
                    self._observe(code)
                    self.start(code)
                if code != self.mode:
                    # Drain one in-flight task per worker, without submissions.
                    while pending:
                        ready, _ = wait(pending, timeout=self.config.budgets()["BUSY_POLL_S"],
                                        return_when=FIRST_COMPLETED)
                        current = _marker(self.config.busy_marker)
                        if current == 11:
                            break
                        for future in ready:
                            pending.pop(future)
                            yield future.result()
                        code = current
                    if pending:
                        continue
                    self._observe(code)
                    self.close()
                    self.start(code)
                while todo and len(pending) < self.width:
                    # Poll immediately before *each* submission.
                    if _marker(self.config.busy_marker) != self.mode:
                        break
                    task = todo.pop(0)
                    future = (self.executor.submit(_solver_task) if solver else
                              self.executor.submit(_task, task, bounds))
                    pending[future] = task
                if pending:
                    ready, _ = wait(pending, timeout=self.config.budgets()["BUSY_POLL_S"],
                                    return_when=FIRST_COMPLETED)
                    # Marker 11 takes precedence over completed but unreduced work.
                    if _marker(self.config.busy_marker) == 11:
                        continue
                    for future in ready:
                        pending.pop(future)
                        yield future.result()
        except BaseException:
            self.close(terminate=True)
            raise


def _checkpoint_files(out):
    return sorted((out / "checkpoints").glob("*.json"))


def _save_checkpoint(out, point, variant, phase, state, hashes):
    directory = out / "checkpoints"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"{point[0]}-{point[1]}-{variant}-{phase}-{state['r_end']}.json"
    path = directory / name
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(canon({"hashes": hashes, "state": _encode(state)}))
    temporary.replace(path)


def _phase(pool, phase, start, stop, ids, bounds, out, hashes):
    wall_start = time.perf_counter()
    is_bound = phase in ("phase0", "sensitivity_bound")
    state = {"r_end": start, "counts": {case: [0] * 7 for case in ids},
             "se2_max": {case: [] for case in ids} if is_bound else {},
             "audits": {"replicates": 0, "certify_calls": 0, "fields_compared": 0, "mismatches": 0},
             "cpu_ms": 0, "wall_ms": 0}
    prefix = f"{pool.point[0]}-{pool.point[1]}-{pool.variant}-{phase}-"
    matches = [p for p in _checkpoint_files(out) if p.name.startswith(prefix)]
    if pool.config.resume and matches:
        latest = max(matches, key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        saved = json.loads(latest.read_bytes())
        if saved["hashes"] != hashes:
            raise ValueError("checkpoint does not match the inputs, C-8 hash or config")
        state = saved["state"]
        state["se2_max"] = {
            c: [(None if v is None else Fraction(v), tuple(Fraction(x) for x in vals))
                for v, vals in rows] for c, rows in state["se2_max"].items()}
    prior_wall = state["wall_ms"]
    chunk = pool.config.budgets()["CHUNK_LARGE" if math.prod(pool.point) >= 9_600 else "CHUNK"]
    tasks, r0 = [], state["r_end"]
    while r0 < stop:
        r1 = min(stop, r0 + chunk, (r0 // 1000 + 1) * 1000)
        tasks.append((phase, r0, r1, tuple(ids)))
        r0 = r1
    buffered = {}
    ends = {task[1]: task[2] for task in tasks}
    for result in pool.results(tasks, bounds):
        buffered[result.r0] = result
        while state["r_end"] in buffered:
            result = buffered.pop(state["r_end"])
            for case in ids:
                state["counts"][case] = [a + b for a, b in
                                          zip(state["counts"][case], result.counts[case], strict=True)]
                if is_bound:
                    state["se2_max"][case].extend(result.se2_max[case])
            for name, value in result.audits.items():
                state["audits"][name] += value
            state["cpu_ms"] += result.cpu_ms
            state["r_end"] = ends[result.r0]
            if state["r_end"] % 1000 == 0:
                state["wall_ms"] = prior_wall + round((time.perf_counter() - wall_start) * 1000)
                _save_checkpoint(out, pool.point, pool.variant, phase, state, hashes)
    state["wall_ms"] = prior_wall + round((time.perf_counter() - wall_start) * 1000)
    _save_checkpoint(out, pool.point, pool.variant, phase, state, hashes)
    pool.phases[f"{pool.point[0]}-{pool.point[1]}-{pool.variant}-{phase}"] = {
        "wall_s": state["wall_ms"] // 1000, "cpu_s": state["cpu_ms"] // 1000}
    _barrier_hook(pool.point, pool.variant, phase)
    return state


def _sum_counts(left, right):
    for case, row in right.items():
        left[case] = [a + b for a, b in zip(left.get(case, [0] * 7), row, strict=True)]


def _case_table(counts, required, budgets, *, reported=False):
    grid = {m.name: m for m in margin_grid(required)}
    result = {}
    for case, row in sorted(counts.items()):
        criterion = grid[case.split("|")[3]].criterion
        n = sum(row[2:6])
        rate, mcse, wilson = rate_stats(row[0], n)
        label = ("REPORTED" if reported or criterion is None else
                 decision(row[0], n, criterion, maximum=budgets["R_MAX"]))
        # An early screen gives no extension decision; its table remains an
        # observed PASS/FAIL, with SCREENED_OUT carried by the alternative.
        if label == "EXTEND":
            direction, bar = criterion
            label = "PASS" if (Fraction(row[0], n) <= bar if direction == "le"
                               else Fraction(row[0], n) >= bar) else "FAIL"
        result[case] = {"criterion": None if criterion is None else
                        f"{criterion[0]} {criterion[1].numerator}/{criterion[1].denominator}",
                        "n": n, "certified": row[0], "certified_uncal": row[1],
                        "outcomes": dict(zip(OUTCOMES, row[2:6], strict=True)),
                        "not_admitted": row[6], "rate_ppm": rate, "mcse_ppm": mcse,
                        "wilson_ppm": wilson, "decision": label}
    return result


def _half(value):
    return None if value is None else f"{int(value * 2)}/2"


def _bounds(phase, alternatives, config=None):
    bounds, pooled = {}, {}
    for alt in alternatives:
        by_margin, by_pooled = [], []
        for margin in ("m0", "m10"):
            rows = phase["se2_max"][f"{alt}|base|none|{margin}"]
            by_margin.append(se_bound([value for value, _ in rows]))
            by_pooled.append(se_bound([v for _, vals in rows for v in vals]))
        bounds[alt] = None if None in by_margin else max(by_margin)
        pooled[alt] = None if None in by_pooled else max(by_pooled)
    statistic = (config.budgets() if config is not None else test_constants())["SE_STATISTIC"]
    return (bounds if statistic == "max" else pooled), pooled


def _main_point(inputs, config, point, alternatives, out, hashes, diagnostics):
    n, b = point
    lives = tuple(replace(life, life=f"pair-{i:03d}") for i, life in enumerate(inputs.lives[:n]))
    load = reserve.relabel(inputs.probe_only, inputs.lives[:n], tuple(pair.life for pair in lives))
    reserves = reserve.reserves(load, lives, inputs.checkpoints)
    result = {"n_L": n, "b": b, "status": "EVALUATED", "reserve": list(reserves),
              "alternatives": {}, "variants": {}}
    if n < inputs.n_lives_floor:
        result["status"] = "SKIPPED"
        return result
    try:
        reserve.capacity(inputs.lanes, reserves)
    except ValueError as exc:
        if str(exc) != "reserve must leave at least one chain slot":
            raise
        result["status"] = "CAPACITY_INFEASIBLE"
        return result
    budgets = config.budgets()
    pool = _Pool(inputs, config, point, "main", diagnostics["pauses"], diagnostics["phases"])
    phases = []
    try:
        info = list(pool.results([("solver", 0, 1, ())], {}, solver=True))[0]
        diagnostics["solver"][f"{n}-{b}"] = info
        phase0_ids = tuple(f"{a}|base|none|{m}" for a in alternatives for m in ("m0", "m10"))
        p0 = _phase(pool, "phase0", 0, budgets["R_MAIN"], phase0_ids, {}, out, hashes)
        phases.append(p0)
        bounds, pooled = _bounds(p0, alternatives, config)
        active = tuple(a for a in alternatives if bounds[a] is not None)
        counts = {}
        screened = set()
        grid = {m.name: m for m in margin_grid(inputs.required)}
        if active:
            p1a = _phase(pool, "phase1a", 0, budgets["R_SCREEN"],
                         case_ids(active, inputs.required), bounds, out, hashes)
            phases.append(p1a)
            _sum_counts(counts, p1a["counts"])
            if config.screen:
                for a in active:
                    if any(screened_out(row[0], sum(row[2:6]), grid[c.split("|")[3]].criterion)
                           for c, row in counts.items() if c.startswith(a + "|")
                           and grid[c.split("|")[3]].criterion is not None):
                        screened.add(a)
            continuing = tuple(a for a in active if a not in screened)
            if continuing:
                p1b = _phase(pool, "phase1b", budgets["R_SCREEN"], budgets["R_MAIN"],
                             case_ids(continuing, inputs.required, reported=False), bounds, out, hashes)
                phases.append(p1b)
                _sum_counts(counts, p1b["counts"])
                extend = tuple(c for c in case_ids(continuing, inputs.required, reported=False)
                               if decision(counts[c][0], budgets["R_MAIN"],
                                           grid[c.split("|")[3]].criterion,
                                           maximum=budgets["R_MAX"]) == "EXTEND")
                if extend:
                    p2 = _phase(pool, "phase2", budgets["R_MAIN"], budgets["R_MAX"], extend,
                                bounds, out, hashes)
                    phases.append(p2)
                    _sum_counts(counts, p2["counts"])
        table = _case_table(counts, inputs.required, budgets)
        for a in alternatives:
            cases = {c: row for c, row in table.items() if c.startswith(a + "|")}
            passed = bounds[a] is not None and all(
                row["decision"] in ("PASS", "PASS_40K", "REPORTED") for row in cases.values())
            result["alternatives"][a] = {
                "se_bound": _half(bounds[a]), "se_bound_pooled": _half(pooled[a]),
                "verdict": "SCREENED_OUT" if a in screened else "PASS" if passed else "FAIL",
                "cases": cases}
        for phase in phases:
            for key, value in phase["audits"].items():
                diagnostics["audits"][key] += value
    finally:
        pool.close()
    return result


def _sensitivities(inputs, config, point_result, out, hashes, diagnostics):
    if config.variants == ("main",):
        return
    point = point_result["n_L"], point_result["b"]
    literal = point_result["alternatives"].get("LITERAL")
    # The main LITERAL bound is needed even when another alternative chose
    # this point. It was active here unless it passed earlier; in that case
    # run phase0 only to obtain its bound, without re-entering its ladder.
    if literal is None:
        main = _Pool(inputs, config, point, "main", diagnostics["pauses"], diagnostics["phases"])
        try:
            p0 = _phase(main, "sensitivity_bound", 0, config.budgets()["R_MAIN"],
                        ("LITERAL|base|none|m0", "LITERAL|base|none|m10"), {}, out, hashes)
            deciding, pooled = _bounds(p0, ("LITERAL",), config)
            bound, pooled_bound = deciding["LITERAL"], pooled["LITERAL"]
            for key, value in p0["audits"].items():
                diagnostics["audits"][key] += value
        finally:
            main.close()
    else:
        bound = None if literal["se_bound"] is None else Fraction(literal["se_bound"])
        pooled_bound = None if literal["se_bound_pooled"] is None else Fraction(literal["se_bound_pooled"])
    if bound is None:
        return
    for variant in config.variants:
        if variant == "main" or (variant.startswith("inputs_")
                                  and variant not in inputs.sensitivity_params):
            continue
        pool = _Pool(inputs, config, point, variant, diagnostics["pauses"], diagnostics["phases"])
        try:
            try:
                # Preflight reserve0 has its own preparation/capacity.
                reserves = ((0, 0) if variant == "reserve0" else tuple(point_result["reserve"]))
                reserve.capacity(inputs.lanes, reserves)
            except ValueError:
                continue
            phase = _phase(pool, "sensitivity", 0, config.budgets()["R_SENS"],
                           case_ids(("LITERAL",), inputs.required, reported=False),
                           {"LITERAL": bound}, out, hashes)
            point_result["variants"][variant] = {"LITERAL": {
                "se_bound": _half(bound), "se_bound_pooled": _half(pooled_bound), "verdict": "REPORTED",
                "cases": _case_table(phase["counts"], inputs.required, config.budgets(), reported=True)}}
            for key, value in phase["audits"].items():
                diagnostics["audits"][key] += value
        finally:
            pool.close()


def constants_manifest(config, required=()):
    return _encode({**config.budgets(), "SIM_SEED": SIM_SEED, "CERTIFY_SEED": CERTIFY_SEED,
                    "CERTIFY_NAME": CERTIFY_NAME, "LADDER": config.ladder,
                    "MARGIN_GRID": [asdict(m) for m in margin_grid(tuple(required))],
                    "KINDS": KINDS, "DRIFT_CASES": [asdict(d) for d in DRIFT_CASES],
                    "ALTERNATIVES": {a: {"fc": sorted(ALTERNATIVES[a].fc.drifts),
                                           "s": sorted(ALTERNATIVES[a].s.drifts),
                                           "units": ALTERNATIVES[a].units} for a in config.alternatives},
                    "Z2": Z2, "Z2_SCREEN": Z2_SCREEN, "SE_PERCENTILE_PPM": SE_PERCENTILE_PPM,
                    "AUDIT_PPM": AUDIT_PPM, "AUDIT_CASES": AUDIT_CASES,
                    "STEP_EXP": STEP_EXP, "MAX_STEP_EXP": MAX_STEP_EXP, "BOUND_MILLI": BOUND_MILLI,
                    "GRID_LOW": GRID_LOW, "GRID_HIGH": GRID_HIGH, "variants": config.variants,
                    "alternatives": config.alternatives, "workers": config.workers})


def run(inputs: RunInputs, config: RunConfig, out: Path) -> int:
    keyed.assert_hashseed()
    code_hash = c8_hash(inputs.root)
    dirty = c8_dirty(inputs.root)
    if not inputs.planning and code_hash != inputs.c8_hash:
        raise ValueError("C-8 hash mismatch: refusing a non-planning run")
    if not inputs.planning and dirty:
        raise ValueError("C-8 working tree dirty: refusing a non-planning run")
    hashes = {"inputs": sha256(inputs.source_bytes).hexdigest(), "c8": code_hash,
              "config": sha256(canon(_config_data(config))).hexdigest()}
    if out.exists() and not config.resume:
        raise ValueError("output directory exists: refusing to overwrite")
    if config.resume:
        files = _checkpoint_files(out)
        if not files:
            raise ValueError("nothing to resume")
        for path in files:
            if json.loads(path.read_bytes()).get("hashes") != hashes:
                raise ValueError("checkpoint does not match the inputs, C-8 hash or config")
    out.mkdir(parents=True, exist_ok=True)
    diagnostics = {"audits": {"replicates": 0, "certify_calls": 0, "fields_compared": 0,
                              "mismatches": 0}, "solver": {}, "pauses": [], "phases": {}}
    results = {"points": [], "first_passing": {a: None for a in config.alternatives},
               "freeze_gate": "OPEN: D12 (S-27)"}
    active = list(config.alternatives)
    try:
        for point in config.ladder:
            item = _main_point(inputs, config, point, tuple(active), out, hashes, diagnostics)
            results["points"].append(item)
            for a in tuple(active):
                if item["alternatives"].get(a, {}).get("verdict") == "PASS":
                    results["first_passing"][a] = list(point)
                    active.remove(a)
            if not active:
                break
        chosen = set()
        for a in config.alternatives:
            passing = results["first_passing"][a]
            if passing is not None:
                chosen.add(tuple(passing))
            else:
                evaluated = [p for p in results["points"] if a in p["alternatives"]]
                if evaluated:
                    chosen.add((evaluated[-1]["n_L"], evaluated[-1]["b"]))
        for item in results["points"]:
            if (item["n_L"], item["b"]) in chosen:
                _sensitivities(inputs, config, item, out, hashes, diagnostics)
    except AuditMismatch as exc:
        # A failed audit never leaves a card, including when resuming a run
        # whose prior card is now invalidated by a deliberately injected bug.
        for name in ("results.json", "RESULT-MANIFEST.json", "RESULT.md"):
            (out / name).unlink(missing_ok=True)
        print(str(exc), file=sys.stderr)
        return 4
    manifest = {
        "schema": "bicentennial.ocsim.result/v1",
        "claim_class": "planning smoke, not the gate" if inputs.planning else
                       "OC simulation under frozen M2 with plug-in bar-2 inputs",
        "code": {"commit": _git(inputs.root, "rev-parse", "HEAD"), "c8_hash": code_hash,
                 "certify_sha256": sha256((inputs.root / "src/bicentennial/stats/certify.py").read_bytes()).hexdigest(),
                 "tcal_sha256": sha256((inputs.root / "src/bicentennial/stats/tcal.py").read_bytes()).hexdigest(),
                 "dirty": dirty},
        "inputs": {"sha256": hashes["inputs"], "planning": inputs.planning,
                   "latent_flags": list(inputs.latent_flags)},
        "config": constants_manifest(config, inputs.required), "audits": diagnostics["audits"],
        "solver": diagnostics["solver"],
        "occupancy": {"reserves": [{"n_L": p["n_L"], "b": p["b"], "reserve": p["reserve"]}
                                     for p in results["points"]],
                      "extra_chains": "not modelled: under-count disclosed",
                      "missing": card.EXTRA_CHAINS},
        "run": {"phases": diagnostics["phases"], "pauses": diagnostics["pauses"],
                "workers": config.workers},
        "machine": {"platform": platform.platform(), "machine": platform.machine(),
                    "python_version": platform.python_version(), "cpu_count": os.cpu_count(),
                    "class": config.machine_class}, "not_proven": list(card.NOT_PROVEN),
    }
    card.write(out, results, manifest)
    return 0


def _profile(inputs, config, out, reps):
    """Explicit diagnostic mode; no result card or ladder verdict."""
    if out.exists():
        raise ValueError("output directory exists: refusing to overwrite")
    if not inputs.planning:
        if c8_hash(inputs.root) != inputs.c8_hash:
            raise ValueError("C-8 hash mismatch: refusing a non-planning run")
        if c8_dirty(inputs.root):
            raise ValueError("C-8 working tree dirty: refusing a non-planning run")
    ctx = PointContext(inputs, config, config.ladder[0])
    stages = {name: 0.0 for name in ("life_effects", "bundle_latents", "draw_all",
                                    "expected_units", "project", "unit_times", "drifted_targets",
                                    "control_sums", "system_sums", "cell_sums", "admissions", "decide")}
    # Wrappers are restricted to this single-process diagnostic invocation.
    bindings = ((model, ("life_effects", "bundle_latents", "expected_units")),
                (schedule, ("draw_all", "project", "unit_times")),
                (drift, ("drifted_targets",)),
                (fastboard, ("control_sums", "system_sums", "cell_sums")),
                (fastcert, ("admissions", "decide")))
    originals = []

    def timed(function, name):
        def invoke(*args, **kwargs):
            start = time.perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                stages[name] += time.perf_counter() - start
        return invoke

    start = time.perf_counter()
    try:
        for module, names in bindings:
            for name in names:
                function = getattr(module, name)
                originals.append((module, name, function))
                setattr(module, name, timed(function, name))
        for rep in range(reps):
            evaluate(ctx, rep, case_ids(config.alternatives, inputs.required))
    finally:
        for module, name, function in originals:
            setattr(module, name, function)
    elapsed = time.perf_counter() - start
    out.mkdir(parents=True)
    payload = {"replicates": reps, "stage_ms": {k: round(v * 1000) for k, v in stages.items()},
               "wall_ms": round(elapsed * 1000),
               "projected_main_wall_s": round(elapsed * R_MAIN / reps), "claim_class": "diagnostic estimate"}
    (out / "PROFILE.json").write_bytes(canon(payload))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--alternatives", required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--profile", type=int)
    parser.add_argument("--busy-marker")
    parser.add_argument("--machine-class", default="undeclared")
    args = parser.parse_args(argv)
    try:
        config = configure(RunConfig(tuple(args.alternatives.split(",")), args.workers, resume=args.resume),
                           busy_marker=tuple(shlex.split(args.busy_marker)) if args.busy_marker else (),
                           machine_class=args.machine_class)
        inputs = load_inputs(args.inputs, ladder=config.ladder)
        if args.profile is not None:
            if args.profile < 1:
                raise ValueError("profile must be a positive int")
            keyed.assert_hashseed()
            return _profile(inputs, config, args.out, args.profile)
        return run(inputs, config, args.out)
    except (ValueError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except AuditMismatch as exc:
        print(str(exc), file=sys.stderr)
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
