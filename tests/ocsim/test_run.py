"""C2, C8-C10 acceptance: tiny runs only, under the machine's test gate."""

import ast
import inspect
import json
import os
import re
import sys
from concurrent.futures import Future
from dataclasses import replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.ocsim import fastcert, locate, model, run
from bicentennial.stats import seeds, tcal

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/ocsim/planning.json"
# RunConfig caps workers at cpu_count, and the width checks need more than two workers.
NEEDS_4_CPUS = pytest.mark.skipif((os.cpu_count() or 1) < 4, reason="needs four workers")
NEEDS_2_CPUS = pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs two workers")
TINY_CONSTANTS = run.test_constants(DRAWS=64, R_SCREEN=4, R_REPORT=4, R_SENS=4,
                                   R_MAIN=8, R_MAX=16, CHUNK=25, CHUNK_LARGE=5)


def rejects(message):
    return pytest.raises(ValueError, match="^" + re.escape(message) + "$")


def tiny_raw():
    def life(name, first):
        return {"life": name, "b0_tokens": [1000, 2000 if first else 1000, 1000],
                "b1_tokens": [2000 if first else 1000, 1000], "fork": 2, "swap": 3,
                "b0_probe_tokens": [1000 if first else 0, 0], "b1_probe_tokens": [0, 0]}
    return {
        "params": {"cells": [{"cell": "X", "levels": [-1000, 1000], "cuts": [0.0.hex()],
                                "f0": (-200.0).hex(), "c0": 600.0.hex(),
                                "sigma_f": 0.0.hex(), "sigma_c": 0.0.hex()}],
                   "rho_x": 0.0.hex(), "rho_a": 0.0.hex(), "rho_t": 1.0.hex(),
                   "sigma_d2": 0.99.hex(), "sigma_r2": None},
        "latent_flags": ["sigma_d2_constrained"], "sensitivity_params": {}, "required": ["X"],
        "alloc_by_b": {"5": [["X", 2, 3], ["X", 3, 2]]}, "checkpoints": [2, 3],
        "lives": [life("life-a", True), life("life-b", False)],
        "rows": [{"row": "A", "rate": "3600/1"}],
        "lanes": [{"name": "pinned", "concurrency": 2, "accounts": 1},
                  {"name": "swap", "concurrency": 2, "accounts": 1}],
        "passover": {"failed": "1/10", "blocked": "1/10"}, "control_failure": "1/10",
        "probe_only": {"tokens": [], "anchor_tokens": {"life-a": 0, "life-b": 0}, "rates": {}},
        "n_lives_floor": 1, "planning": True, "c8_hash": "planning",
    }


def tiny_config(**kwargs):
    constants = kwargs.pop("constants", TINY_CONSTANTS)
    return run.configure(run.RunConfig(**{"alternatives": tuple(run.ALTERNATIVES), "workers": 1,
                                          "variants": ("main",), "ladder": ((2, 5),), **kwargs}),
                         constants=constants)


@pytest.fixture(scope="module")
def tiny_inputs():
    return run.parse_inputs(canon(tiny_raw()), ladder=((2, 5),))


@pytest.fixture(scope="module")
def tables(tiny_inputs):
    return {cell.cell: locate.build_table(cell, tiny_inputs.params.rho_t)
            for cell in tiny_inputs.params.cells}


def context(inputs, config, tables, **kwargs):
    def solver(cell, target):
        return locate.locate(tables[cell.cell], cell, target)
    return run.PointContext(inputs, config, config.ladder[0], solver=solver, tables=tables, **kwargs)


@pytest.mark.parametrize("bar,counts,labels", (
    (Fraction(1, 20), (457, 458, 542, 543), ("PASS", "EXTEND", "EXTEND", "FAIL")),
    (Fraction(4, 5), (7921, 7922, 8078, 8079), ("FAIL", "EXTEND", "EXTEND", "PASS")),
    (Fraction(1, 5), (1921, 1922, 2078, 2079), ("PASS", "EXTEND", "EXTEND", "FAIL")),
))
def test_wilson_fixed_counts(bar, counts, labels):
    criterion = ("ge" if bar == Fraction(4, 5) else "le", bar)
    assert tuple(run.decision(x, 10_000, criterion) for x in counts) == labels
    assert run.straddles(counts[1], 10_000, criterion)
    assert not run.straddles(counts[0], 10_000, criterion)


def test_wilson_40k_screen_and_display():
    le, ge = ("le", Fraction(1, 20)), ("ge", Fraction(4, 5))
    assert run.decision(2000, 40_000, le) == "PASS_40K"
    assert run.decision(2001, 40_000, le) == "FAIL_40K"
    assert run.decision(32_000, 40_000, ge) == "PASS_40K"
    assert run.decision(31_999, 40_000, ge) == "FAIL_40K"
    assert run.screened_out(133, 2000, le)
    assert not run.screened_out(132, 2000, le)
    # Closed Wilson ends are tested exactly, not with rounded interval text.
    assert run.straddles(6, 10, ("le", Fraction(1, 2)), Fraction(2, 5))
    rate, mcse, (lo, hi) = run.rate_stats(500, 10_000)
    assert (rate, mcse) == (50_000, 2179)
    def inside(ppm):
        p = Fraction(ppm, 1_000_000)
        return (Fraction(1, 20) - p)**2 <= run.Z2 * p * (1 - p) / 10_000
    assert not inside(lo) and inside(lo + 1)
    assert not inside(hi) and inside(hi - 1)
    assert run.rate_stats(0, 1)[2][0] == 0
    assert run.rate_stats(1, 1)[2][1] == 1_000_000


def test_se_rounding_indices_and_missing():
    for value, expected in (("18.49", "4.5"), ("20.25", "4.5"), ("20.3401", "5")):
        assert run.se_bound([Fraction(value)]) == Fraction(expected)
    assert tcal.index(10_000, 950_000) == 9499
    assert tcal.index(20, 950_000) == 18
    assert tcal.index(18, 950_000) == 17
    assert run.se_bound([Fraction(i) for i in range(20)]) == run.se_bound([Fraction(18)])
    assert run.se_bound([None, None]) is None
    assert run.se_bound([Fraction(i) for i in range(18)] + [None, None]) == run.se_bound([Fraction(17)])
    assert run._half(Fraction(5)) == "10/2"


def test_config_validation():
    assert tuple(inspect.signature(run.RunConfig).parameters) == (
        "alternatives", "workers", "variants", "ladder", "screen", "resume")
    with pytest.raises(TypeError):
        run.RunConfig(workers=1)
    for kwargs, message in (
        ({"alternatives": ()}, "alternatives must be named explicitly (D12 is open)"),
        ({"alternatives": ("ALL_UNITS", "LITERAL")}, "LITERAL must run first (S-27)"),
        ({"alternatives": ("LITERAL", "unknown")}, "unknown alternative: unknown"),
        ({"alternatives": ("LITERAL", "LITERAL")}, "alternatives must be unique"),
        ({"workers": True}, "workers must be an int in [1, cpu_count]"),
        ({"workers": 0}, "workers must be an int in [1, cpu_count]"),
        ({"workers": (os.cpu_count() or 1) + 1}, "workers must be an int in [1, cpu_count]"),
        ({"variants": ("main", "bad")}, "unknown variant: bad"),
    ):
        with rejects(message):
            tiny_config(**kwargs)
    assert run.SIM_SEED == "bicentennial-ocsim-v1"
    assert (run.CERTIFY_SEED, run.CERTIFY_NAME) == (seeds.CERTIFY_SEED, seeds.CERTIFY_NAME)
    assert run.DRAWS == 10_000
    assert run.LADDER == tuple((n, b) for n in (24, 32, 40, 48) for b in (150, 200, 250, 300))
    assert [run.R_MAIN, run.R_MAX, run.R_REPORT, run.R_SENS, run.R_SCREEN] == [10_000, 40_000, 2000, 2000, 2000]


def test_grid_ids_and_scope_counts():
    grid = run.margin_grid(("D", "B", "A", "C"))
    assert [m.name for m in grid] == ["m0", "m5", "m10", "m15", "rot:A", "rot:B", "rot:C", "rot:D"]
    assert grid[4].margins == (("A", -10), ("B", 10), ("C", 10), ("D", 10))
    assert grid[1].criterion is grid[3].criterion is None
    assert len(run.case_ids(("LITERAL",), ("A", "B", "C", "D"), reported=False)) == 162
    assert len(run.case_ids(("LITERAL",), tuple("ABCDEFGH"), reported=False)) == 270
    assert len(run.case_ids(("LITERAL",), ("A", "B", "C", "D"))) - 162 == 54
    assert run.case_ids(tuple(run.ALTERNATIVES), ("X",))[0] == "LITERAL|base|none|m0"
    assert model.ARMS == run.drift.ARMS


def test_crn_and_scope_caches(tiny_inputs, tables, monkeypatch):
    observed = {}
    ctx = context(tiny_inputs, tiny_config(), tables,
                  bounds={a: Fraction(5) for a in run.ALTERNATIVES},
                  trace=lambda case, fc, ss, cs: observed.update({case: (fc, ss, cs)}))
    calls = []
    original = model.bundle_latents

    def latents(*args, **kwargs):
        calls.append(args[4])
        return original(*args, **kwargs)

    monkeypatch.setattr(model, "bundle_latents", latents)
    monkeypatch.setattr(run, "audit_selected", lambda rep: False)
    ids = tuple(f"{a}|base|{d}|{m}" for a in run.ALTERNATIVES
                for d in ("none", "step+5") for m in ("m0", "m10"))
    result = run.evaluate(ctx, 1, ids)
    assert calls == [1]
    for margin in ("m0", "m10"):
        assert result[f"LITERAL|base|none|{margin}"] is result[f"ALL_UNITS|base|none|{margin}"]
        assert result[f"LITERAL|base|none|{margin}"] is result[f"SWAP_GATE|base|none|{margin}"]
    for alt in run.ALTERNATIVES:
        for drift_name in ("none", "step+5"):
            assert observed[f"{alt}|base|{drift_name}|m0"][0] is observed[f"{alt}|base|{drift_name}|m10"][0]
    assert observed["LITERAL|base|step+5|m0"][1] is observed["PRE_SWAP|base|step+5|m0"][1]
    assert observed["LITERAL|base|step+5|m0"][1] is observed["SWAP_GATE|base|step+5|m0"][1]
    assert len({id(value[0]) for value in observed.values()}) == 3  # none, literal, swap gate


def test_audit_selection():
    a = [run.audit_selected(i) for i in range(1000)]
    assert a == [run.audit_selected(i) for i in range(1000)]
    assert 0 < sum(a) < 20


def test_tight_noise_and_reference(tables, monkeypatch):
    raw = tiny_raw()
    template = raw["lives"][1]
    raw["lives"] = [{**template, "life": f"life-{i:03d}"} for i in range(24)]
    raw["probe_only"]["anchor_tokens"] = {life["life"]: 0 for life in raw["lives"]}
    raw["rows"][0]["rate"] = "1/1"
    for lane in raw["lanes"]:
        lane["concurrency"] = 50
    raw["passover"] = {"failed": "0/1", "blocked": "0/1"}
    raw["control_failure"] = "0/1"
    raw["alloc_by_b"] = {"100": [["X", 2, 50], ["X", 3, 50]]}
    inputs = run.parse_inputs(canon(raw), ladder=((24, 100),))
    config = tiny_config(ladder=((24, 100),), constants={**TINY_CONSTANTS, "DRAWS": 200})
    ctx = context(inputs, config, tables, bounds={"LITERAL": Fraction(5)})
    ctx.tau = {"X": 0.0}
    monkeypatch.setattr(run, "audit_selected", lambda rep: True)
    margins = (run.MarginConfig("p20", (("X", 20),), None),
               run.MarginConfig("n20", (("X", -20),), None))
    ids = ("LITERAL|base|none|p20", "LITERAL|base|none|n20")
    totals = [0, 0]
    for rep in range(20):
        dec = run.evaluate(ctx, rep, ids, margins=margins)
        for i, case in enumerate(ids):
            totals[i] += dec[case].certified[0]
    assert totals == [20, 0]
    assert ctx.audits["replicates"] == 20
    assert ctx.audits["certify_calls"] == 40
    assert ctx.audits["fields_compared"] == 40 * 8


def test_audit_abort_coefficient(tiny_inputs, tables, monkeypatch):
    raw = tiny_raw()
    raw["passover"] = {"failed": "0/1", "blocked": "0/1"}
    raw["control_failure"] = "0/1"
    inputs = run.parse_inputs(canon(raw), ladder=((2, 5),))
    ctx = context(inputs, tiny_config(), tables)
    original = fastcert.margin_functionals

    def damaged(*args, **kwargs):
        cells, joint = original(*args, **kwargs)
        k, f = cells[0]
        if f is not None:
            cells = ((k, replace(f, coef=(f.coef[0] + 1, *f.coef[1:]))), *cells[1:])
        return cells, joint

    monkeypatch.setattr(fastcert, "margin_functionals", damaged)
    with pytest.raises(run.AuditMismatch, match=r"audit mismatch at rep 0 case LITERAL\|base\|none\|m0:"):
        run.evaluate(ctx, 0, ("LITERAL|base|none|m0",))


def test_solver_audit_and_failure(tiny_inputs, tables):
    ctx = context(tiny_inputs, tiny_config(), tables)
    diagnostic = run.solver_audit(ctx)
    assert diagnostic["X"]["audit_error_ppm"] <= diagnostic["X"]["bound_milli_ppm"] + 1
    ctx.solver = lambda cell, target: 0.0
    with pytest.raises(run.AuditMismatch, match="solver audit at cell X:"):
        run.solver_audit(ctx)


def test_parser_validation_and_fallback():
    raw = tiny_raw()
    parsed = run.parse_inputs(canon(raw), ladder=((2, 5),))
    assert parsed.probe_only.rates["anchor"] == parsed.rows[0].rate == 3600
    for name in raw:
        bad = {k: v for k, v in raw.items() if k != name}
        with rejects(f"inputs: missing {name}"):
            run.parse_inputs(canon(bad), ladder=((2, 5),))
    with rejects("need at least 3 lives in the dry history set"):
        run.parse_inputs(canon(raw), ladder=((3, 5),))
    raw["required"] = ["Y"]
    with rejects("required cells must equal the model's cells"):
        run.parse_inputs(canon(raw), ladder=((2, 5),))
    raw = tiny_raw()
    raw["alloc_by_b"] = {}
    with rejects("allocation for b = 5 must cover every (cell, checkpoint)"):
        run.parse_inputs(canon(raw), ladder=((2, 5),))
    raw["alloc_by_b"] = {"5": [["X", 2, 5]]}
    with rejects("allocation for b = 5 must cover every (cell, checkpoint)"):
        run.parse_inputs(canon(raw), ladder=((2, 5),))
    for value in ("nan", "inf", "0x1p+99999", "1.0", 1):
        raw = tiny_raw()
        raw["params"]["rho_x"] = value
        with rejects("inputs: bad float in params.rho_x"):
            run.parse_inputs(canon(raw), ladder=((2, 5),))
    for value in (0.1, True, 1, "0.1", "1e-1", "1/0", "1/-2"):
        for field in ("control_failure", "passover.failed", "rows.rate", "probe_only.rates.F"):
            raw = tiny_raw()
            owner, key = {"control_failure": (raw, "control_failure"),
                          "passover.failed": (raw["passover"], "failed"),
                          "rows.rate": (raw["rows"][0], "rate"),
                          "probe_only.rates.F": (raw["probe_only"]["rates"], "F")}[field]
            owner[key] = value
            with rejects(f"inputs: bad fraction in {field}"):
                run.parse_inputs(json.dumps(raw).encode(), ladder=((2, 5),))
    raw = tiny_raw()
    raw["alloc_by_b"]["5"].append(["X", 2, 4])
    with rejects("allocation for b = 5 must cover every (cell, checkpoint)"):
        run.parse_inputs(canon(raw), ladder=((2, 5),))
    raw = tiny_raw()
    key = ("F", "life-z", "B0", 2)
    raw["probe_only"]["tokens"] = [[*key, 1]]
    with rejects(f"bad probe-only key: {key}"):
        run.parse_inputs(canon(raw), ladder=((2, 5),))


@pytest.mark.parametrize("keys", (("0150",), (" 150",), ("+150",), ("x",), ("x", "+150")))
def test_parser_canonical_allocation_keys(keys):
    raw = json.loads(FIXTURE.read_bytes())
    raw["alloc_by_b"] = {key: raw["alloc_by_b"]["150"] for key in keys}
    with rejects(f"allocation for b = {keys[0]} must cover every (cell, checkpoint)"):
        run.parse_inputs(json.dumps(raw).encode())


def test_planning_fixture_real_parser_and_replicate():
    inputs = run.load_inputs(FIXTURE)
    assert inputs.planning and len(inputs.lives) == 48 and len(inputs.rows) == 6
    assert len(inputs.required) == 4
    for b, alloc in inputs.alloc_by_b.items():
        assert len(alloc) == 16 and sum(alloc.values()) == round(Fraction(3, 5) * b)
        assert min(alloc.values()) >= 1 and max(alloc.values()) - min(alloc.values()) <= 1
    config = run.configure(run.RunConfig(("LITERAL",), 1), constants=TINY_CONSTANTS)
    ctx = run.PointContext(inputs, config, run.LADDER[0])
    decisions = run.evaluate(ctx, 0, ("LITERAL|base|none|m0",))
    assert decisions["LITERAL|base|none|m0"].outcome in run.OUTCOMES


def test_c8_hash_copy_change_missing_and_dirty(tmp_path, monkeypatch):
    paths = run.c8_paths(ROOT)
    for name in paths:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    initial = run.c8_hash(tmp_path)
    assert run.c8_hash(tmp_path) == initial == run.c8_hash(ROOT)
    assert initial == sha256(canon([[p, sha256((tmp_path / p).read_bytes()).hexdigest()]
                                   for p in paths])).hexdigest()
    target = tmp_path / run._C8_FIXED[0]
    target.write_bytes(target.read_bytes() + b"\n")
    assert run.c8_hash(tmp_path) != initial
    target.unlink()
    with rejects(f"C-8 file missing: {run._C8_FIXED[0]}"):
        run.c8_hash(tmp_path)
    target.write_bytes((ROOT / run._C8_FIXED[0]).read_bytes())
    assert run._git(tmp_path, "init") is not None
    assert run._git(tmp_path, "add", ".") is not None
    assert run._git(tmp_path, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                    "-c", "commit.gpgsign=false", "commit", "-m", "synthetic fixture") is not None
    assert not run.c8_dirty(tmp_path)
    deleted = tmp_path / "tests/ocsim/test_reserve.py"
    deleted.unlink()
    assert run.c8_dirty(tmp_path)
    deleted.write_bytes((ROOT / "tests/ocsim/test_reserve.py").read_bytes())
    assert not run.c8_dirty(tmp_path)
    (tmp_path / "src/bicentennial/ocsim/new.py").write_text("# synthetic\n")
    assert run.c8_dirty(tmp_path) and run.c8_hash(tmp_path) != initial
    monkeypatch.setattr(run, "_git", lambda *args: None)
    assert run.c8_dirty(ROOT)
    monkeypatch.setattr(run, "_git", lambda *args: " M tracked.py")
    assert run.c8_dirty(ROOT)
    monkeypatch.setattr(run, "_git", lambda *args: "")
    assert not run.c8_dirty(ROOT)


def _imported_files(path):
    """The repository files a bicentennial import in `path` runs: each imported module and its packages."""
    package = Path(path).with_suffix("").parts[1:-1]
    names = []
    for node in ast.walk(ast.parse((ROOT / path).read_text())):
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = ".".join((*package[:len(package) - node.level + 1], node.module or "") if node.level
                            else (node.module or "",)).strip(".")
            names += [base, *(f"{base}.{alias.name}" for alias in node.names)]
    files = []
    for parts in (name.split(".") for name in names if name.split(".")[0] == "bicentennial"):
        for i in range(1, len(parts) + 1):
            for candidate in (Path("src", *parts[:i], "__init__.py"), Path("src", *parts[:i]).with_suffix(".py")):
                if (ROOT / candidate).is_file():
                    files.append(candidate.as_posix())
    return files


def test_c8_covers_every_imported_module():
    # A module the simulation imports, directly or through another, can change its samples, so C-8 hashes it
    paths = set(run.c8_paths(ROOT))
    closure, todo = set(), [p for p in paths if p.startswith("src/")]
    while todo:
        path = todo.pop()
        if path not in closure:
            closure.add(path)
            todo += _imported_files(path)
    assert "src/bicentennial/keyed.py" in closure
    assert closure <= paths, sorted(closure - paths)


def test_resume_keeps_busy_marker_history(tiny_inputs, tmp_path, monkeypatch):
    # Interrupted after a pause and resumed, a run reports the busy-marker history of an uninterrupted run
    config = tiny_config(alternatives=("LITERAL",), constants={**TINY_CONSTANTS, "CHUNK": 1})
    holding = [True]

    def stop(point, variant, phase):
        if phase == "phase1a":
            raise InterruptedError("test barrier")

    def poll():
        holding[0] = False

    monkeypatch.setattr(run, "_marker", lambda command: 11 if holding[0] else 0)
    monkeypatch.setattr(run, "_pause_wait", poll)
    assert run.run(tiny_inputs, config, tmp_path / "whole") == 0
    holding[0] = True
    monkeypatch.setattr(run, "_barrier_hook", stop)
    with pytest.raises(InterruptedError, match="test barrier"):
        run.run(tiny_inputs, config, tmp_path / "resumed")
    monkeypatch.setattr(run, "_barrier_hook", lambda *args: None)
    assert run.run(tiny_inputs, run.copy_config(config, resume=True), tmp_path / "resumed") == 0
    whole, resumed = (json.loads((tmp_path / name / "RESULT-MANIFEST.json").read_bytes())["run"]["pauses"]
                      for name in ("whole", "resumed"))
    assert [p["event"] for p in whole] == ["pause", "width"] and resumed == whole


def test_nonplanning_pins_and_output_validation(tiny_inputs, tmp_path, monkeypatch):
    config = tiny_config()
    with rejects("C-8 hash mismatch: refusing a non-planning run"):
        run.run(replace(tiny_inputs, planning=False, c8_hash="bad"), config, tmp_path / "bad")
    current = run.c8_hash(ROOT)
    monkeypatch.setattr(run, "c8_dirty", lambda root: True)
    with rejects("C-8 working tree dirty: refusing a non-planning run"):
        run.run(replace(tiny_inputs, planning=False, c8_hash=current), config, tmp_path / "dirty")
    with rejects("output directory exists: refusing to overwrite"):
        run.run(tiny_inputs, config, tmp_path)
    with rejects("nothing to resume"):
        run.run(tiny_inputs, run.copy_config(config, resume=True), tmp_path / "missing")


@NEEDS_4_CPUS
def test_byte_identity_workers_and_chunks(tiny_inputs, tmp_path):
    payloads = []
    for i, (workers, chunk) in enumerate(((1, 1), (4, 1), (4, 25))):
        out = tmp_path / str(i)
        config = tiny_config(workers=workers, variants=run.RunConfig(("LITERAL",), 1).variants,
                             constants={**TINY_CONSTANTS, "CHUNK": chunk})
        assert run.run(tiny_inputs, config, out) == 0
        payloads.append((out / "results.json").read_bytes())
        assert all(p["variants"] for p in json.loads(payloads[-1])["points"])
        manifest = json.loads((out / "RESULT-MANIFEST.json").read_bytes())
        assert canon(manifest) == (out / "RESULT-MANIFEST.json").read_bytes()
        assert manifest["audits"]["replicates"] > 0
        assert manifest["audits"]["mismatches"] == 0
        assert manifest["inputs"]["sha256"] == sha256(tiny_inputs.source_bytes).hexdigest()
        assert manifest["results_sha256"] == sha256(payloads[-1]).hexdigest()
    assert payloads[0] == payloads[1] == payloads[2]


def test_resume_barrier_and_hash_refusal(tiny_inputs, tmp_path, monkeypatch):
    config = tiny_config(alternatives=("LITERAL",), constants={**TINY_CONSTANTS, "CHUNK": 1})
    uninterrupted, resumed = tmp_path / "whole", tmp_path / "resumed"
    assert run.run(tiny_inputs, config, uninterrupted) == 0

    def stop(point, variant, phase):
        if phase == "phase1a":
            raise InterruptedError("test barrier")

    monkeypatch.setattr(run, "_barrier_hook", stop)
    with pytest.raises(InterruptedError, match="test barrier"):
        run.run(tiny_inputs, config, resumed)
    assert list((resumed / "checkpoints").glob("*phase1a-4.json"))
    assert not (resumed / "results.json").exists()
    monkeypatch.setattr(run, "_barrier_hook", lambda *args: None)
    assert run.run(tiny_inputs, run.copy_config(config, resume=True), resumed) == 0
    assert (uninterrupted / "results.json").read_bytes() == (resumed / "results.json").read_bytes()
    checkpoint = next((resumed / "checkpoints").glob("*.json"))
    data = json.loads(checkpoint.read_bytes())
    data["hashes"]["config"] = "changed"
    checkpoint.write_bytes(canon(data))
    with rejects("checkpoint does not match the inputs, C-8 hash or config"):
        run.run(tiny_inputs, run.copy_config(config, resume=True), resumed)


def test_busy_marker_pause_byte_identity(tiny_inputs, tmp_path, monkeypatch):
    constants = {**TINY_CONSTANTS, "R_MAIN": 40, "R_MAX": 80, "CHUNK": 1}
    config = tiny_config(alternatives=("LITERAL",), constants=constants)
    whole, paused = tmp_path / "whole", tmp_path / "paused"
    assert run.run(tiny_inputs, config, whole) == 0
    submitted, holding, released = [], [False], [False]
    original = run.ProcessPoolExecutor.submit

    def submit(executor, fn, *args, **kwargs):
        assert not holding[0], "submitted CPU work while marker was 11"
        future = original(executor, fn, *args, **kwargs)
        submitted.append(fn)
        if len(submitted) == 3:
            holding[0] = True
        return future

    def marker(command):
        return 11 if holding[0] else 0

    def poll():
        assert holding[0]
        holding[0], released[0] = False, True

    monkeypatch.setattr(run.ProcessPoolExecutor, "submit", submit)
    monkeypatch.setattr(run, "_marker", marker)
    monkeypatch.setattr(run, "_pause_wait", poll)
    assert run.run(tiny_inputs, config, paused) == 0
    assert released[0]
    assert (whole / "results.json").read_bytes() == (paused / "results.json").read_bytes()
    manifest = json.loads((paused / "RESULT-MANIFEST.json").read_bytes())
    assert len([p for p in manifest["run"]["pauses"] if p["event"] == "pause"]) == 1


@NEEDS_4_CPUS
@pytest.mark.parametrize("initial", (0, 10))
def test_busy_marker_exit10_drain_and_pool_width(tiny_inputs, tables, tmp_path, monkeypatch, initial):
    config = tiny_config(workers=4, variants=("main", "reserve0"),
                         constants={**TINY_CONSTANTS, "CHUNK": 1})
    code, submitted, reduced, controlled = [0], [], [], [False]
    class Executor:
        def __init__(self, *, max_workers, mp_context, initializer, initargs):
            self.mode = 10 if initargs[-1] else 0
            self.issued = []
            assert max_workers == (2 if self.mode == 10 else 4)
            monkeypatch.setattr(run, "_WORKER", context(tiny_inputs, config, tables, variant=initargs[3]))
        def submit(self, fn, *args):
            assert code[0] == self.mode, "submission during drain"
            future = Future()
            future.set_result(fn(*args))
            self.issued.append(future)
            submitted.append(args)
            if controlled[0] and initial == 0 and len(submitted) == 3:
                code[0] = 10
            elif initial == 0 and self.mode == 10 and len(submitted) == 6:
                code[0] = 0
            return future
        def shutdown(self, **kwargs):
            assert all(future in waited for future in self.issued), "pool rebuilt before drain"
            if initial == 10:
                code[0] = 0
        def terminate_workers(self):
            pass
    waited = set()
    def wait(pending, **kwargs):
        future = next(iter(pending))
        waited.add(future)
        return {future}, set()
    original = run._Pool.results
    def results(pool, tasks, bounds, **kwargs):
        for result in original(pool, tasks, bounds, **kwargs):
            reduced.append((pool.variant, getattr(result, "r0", -1)))
            yield result
    monkeypatch.setattr(run, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(run, "wait", wait)
    monkeypatch.setattr(run._Pool, "results", results)
    monkeypatch.setattr(run, "_marker", lambda command: code[0])
    # Baseline keeps the marker at zero, even at the third and sixth submission.
    assert run.run(tiny_inputs, config, tmp_path / "whole") == 0
    expected = sorted(reduced)
    controlled[0], code[0] = True, initial
    submitted.clear()
    reduced.clear()
    assert run.run(tiny_inputs, config, tmp_path / "controlled") == 0
    assert sorted(reduced) == expected and len(reduced) == len(submitted)
    assert (tmp_path / "whole/results.json").read_bytes() == (tmp_path / "controlled/results.json").read_bytes()
    pauses = json.loads((tmp_path / "controlled/RESULT-MANIFEST.json").read_bytes())["run"]["pauses"]
    assert [(p["exit"], p["workers"]) for p in pauses] == [(10, 2), (0, 4)]


def test_busy_marker_poll_times_out(monkeypatch):
    monkeypatch.setattr(run, "MARKER_TIMEOUT_S", 0.5)
    with pytest.raises(ValueError, match="busy marker did not exit within 0.5 s"):
        run._marker([sys.executable, "-c", "import time; time.sleep(30)"])
    assert run._marker([sys.executable, "-c", "raise SystemExit(10)"]) == 10


@NEEDS_2_CPUS
def test_busy_marker_same_width_mode_changes(tiny_inputs, monkeypatch):
    config = tiny_config(workers=2)
    code, pauses = [0], []
    class Executor:
        def __init__(self, **kwargs):
            pass
        def submit(self, fn):
            future = Future()
            future.set_result({})
            return future
        def shutdown(self, **kwargs):
            pass
        def terminate_workers(self):
            pass
    monkeypatch.setattr(run, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(run, "_marker", lambda command: code[0])
    monkeypatch.setattr(run, "wait", lambda pending, **kwargs: (set(pending), set()))
    monkeypatch.setattr(run, "_pause_wait", lambda: code.__setitem__(0, 0))
    pool = run._Pool(tiny_inputs, config, (2, 5), "main", pauses)
    tasks = [("phase0", 0, 1, ())]
    for mode in (0, 10, 0):
        code[0] = mode
        assert list(pool.results(tasks, {}, solver=True)) == [{}]
    assert [(p["exit"], p["workers"]) for p in pauses] == [(10, 2), (0, 2)]
    following = run._Pool(tiny_inputs, config, (2, 5), "reserve0", pauses)
    assert list(following.results(tasks, {}, solver=True)) == [{}]
    assert len(pauses) == 2
    code[0] = 11
    assert list(pool.results(tasks, {}, solver=True)) == [{}]
    assert [(p["event"], p["exit"]) for p in pauses[2:]] == [("pause", 11), ("width", 0)]
    assert pauses[-1]["workers"] == 2
    pool.close()
    following.close()


@NEEDS_4_CPUS
def test_busy_marker_exit10_niceness_owner_run(tiny_inputs, monkeypatch):
    """Amendments 6/11: owner-run if sandbox refuses spawn/setpriority."""
    config = tiny_config(workers=4)
    pool = run._Pool(tiny_inputs, config, (2, 5), "main", [])
    monkeypatch.setattr(run, "_marker", lambda command: 10)
    try:
        pool.start(10)
        assert pool.width == 2
        futures = [pool.executor.submit(run._worker_nice) for _ in range(2)]
        assert [f.result() for f in futures] == [19, 19]
    finally:
        pool.close()


def inline_pool(monkeypatch, tables):
    """Deterministic parent-only harness for stubbed ladder and barrier checks."""
    def results(pool, tasks, bounds, *, solver=False):
        ctx = context(pool.inputs, pool.config, tables, variant=pool.variant)
        ctx.point = pool.point
        monkeypatch.setattr(run, "_WORKER", ctx)
        if solver:
            yield {}
        else:
            for task in tasks:
                yield run._task(task, bounds)
    monkeypatch.setattr(run._Pool, "results", results)


def test_ladder_and_sensitivities(tiny_inputs, tables, tmp_path, monkeypatch):
    inline_pool(monkeypatch, tables)
    seen = []

    def stub(ctx, rep, ids, *, margins=None):
        ctx.audits["replicates"] += 1
        seen.extend((ctx.point, ctx.variant, case) for case in ids)
        result = {}
        for case in ids:
            alt, _, _, margin = case.split("|")
            passed = alt == "ALL_UNITS" and margin in ("m10", "m5", "m15")
            result[case] = fastcert.Decision("CERTIFIED" if passed else "NOT_CERTIFIED",
                                             (passed, passed), (("X", Fraction(0)),), None,
                                             None, (("X", "ADMITTED"),))
        return result

    monkeypatch.setattr(run, "evaluate", stub)
    raw = tiny_raw()
    raw["alloc_by_b"]["6"] = [["X", 2, 3], ["X", 3, 3]]
    config = tiny_config(alternatives=("LITERAL", "ALL_UNITS"), ladder=((2, 5), (2, 6)),
                         screen=False, variants=("main", "reserve0", "tau0", "no_system_passovers"))
    inputs = run.parse_inputs(canon(raw), ladder=config.ladder)
    out = tmp_path / "ladder"
    assert run.run(inputs, config, out) == 0
    results = json.loads((out / "results.json").read_bytes())
    assert results["first_passing"] == {"LITERAL": None, "ALL_UNITS": [2, 5]}
    assert list(results["points"][1]["alternatives"]) == ["LITERAL"]
    assert any(point == (2, 6) and case.startswith("LITERAL|") for point, _, case in seen)
    assert not any(point == (2, 6) and case.startswith("ALL_UNITS|") for point, _, case in seen)
    for point in results["points"]:
        assert set(point["variants"]) == {"reserve0", "tau0", "no_system_passovers"}
        assert all(set(data) == {"LITERAL"} for data in point["variants"].values())
    phases = []
    monkeypatch.setattr(run, "_barrier_hook", lambda point, variant, phase: phases.append(phase))
    diagnostics = {"pauses": [], "phases": {}, "audits": {"replicates": 0, "certify_calls": 0,
                                                           "fields_compared": 0, "mismatches": 0}}
    point = {**results["points"][1], "alternatives": {}, "variants": {}}
    run._sensitivities(inputs, config, point, tmp_path / "bound", {}, diagnostics)
    assert phases.count("sensitivity_bound") == 1 and phases.count("sensitivity") == 3
    assert len(diagnostics["phases"]) == 4 and diagnostics["audits"]["replicates"] == 8 + 3 * 4


def test_sensitivities_without_runnable_variant(tiny_inputs, tables, tmp_path, monkeypatch):
    inline_pool(monkeypatch, tables)
    config = tiny_config(variants=("main", "inputs_low"))
    assert tiny_inputs.sensitivity_params == {}
    phases = {"already": {"wall_s": 1, "cpu_s": 1}}
    audits = {"replicates": 7, "certify_calls": 8, "fields_compared": 9, "mismatches": 0}
    diagnostics = {"pauses": [], "phases": dict(phases), "audits": dict(audits)}
    point = {"n_L": 2, "b": 5, "alternatives": {}, "variants": {}}
    run._sensitivities(tiny_inputs, config, point, tmp_path, {}, diagnostics)
    assert diagnostics["phases"] == phases and diagnostics["audits"] == audits
    assert not list(tmp_path.glob("checkpoints/*sensitivity*.json"))
    assert point["variants"] == {} and diagnostics["pauses"] == []


def test_missing_bound_skip_and_capacity(tiny_inputs, tables, tmp_path, monkeypatch):
    inline_pool(monkeypatch, tables)

    def missing(ctx, rep, ids, *, margins=None):
        return {c: fastcert.Decision("DEFERRED", (False, False), (("X", None),), None, None,
                                     (("X", None),)) for c in ids}

    monkeypatch.setattr(run, "evaluate", missing)
    config = tiny_config(alternatives=("LITERAL",))
    out = tmp_path / "missing"
    assert run.run(tiny_inputs, config, out) == 0
    alt = json.loads((out / "results.json").read_bytes())["points"][0]["alternatives"]["LITERAL"]
    assert alt["verdict"] == "FAIL" and alt["se_bound"] is None
    out = tmp_path / "floor"
    assert run.run(replace(tiny_inputs, n_lives_floor=3), config, out) == 0
    assert json.loads((out / "results.json").read_bytes())["points"][0]["status"] == "SKIPPED"
    probe = replace(tiny_inputs.probe_only, anchor_tokens={"life-a": 100_000, "life-b": 0})
    out = tmp_path / "capacity"
    assert run.run(replace(tiny_inputs, probe_only=probe), config, out) == 0
    assert json.loads((out / "results.json").read_bytes())["points"][0]["status"] == "CAPACITY_INFEASIBLE"


def test_run_audit_abort_no_card(tiny_inputs, tables, tmp_path, monkeypatch, capsys):
    inline_pool(monkeypatch, tables)

    def fail(ctx, rep, ids, *, margins=None):
        raise run.AuditMismatch(f"audit mismatch at rep {rep} case {ids[0]}: injected")

    monkeypatch.setattr(run, "evaluate", fail)
    out = tmp_path / "abort"
    assert run.run(tiny_inputs, tiny_config(), out) == 4
    assert "audit mismatch at rep 0" in capsys.readouterr().err
    assert not any((out / name).exists() for name in ("results.json", "RESULT-MANIFEST.json", "RESULT.md"))


def test_bound_max_pooled_and_missing():
    rows = [(Fraction(100) if r >= 18 else Fraction(0),
             (Fraction(100) if r >= 18 else Fraction(0), Fraction(0), Fraction(0), Fraction(0)))
            for r in range(20)]
    phase = {"se2_max": {f"LITERAL|base|none|{m}": rows for m in ("m0", "m10")}}
    assert run._bounds(phase, ("LITERAL",)) == ({"LITERAL": Fraction(10)}, {"LITERAL": Fraction(0)})
    config = tiny_config(constants={**TINY_CONSTANTS, "SE_STATISTIC": "pooled"})
    assert run._bounds(phase, ("LITERAL",), config) == ({"LITERAL": Fraction(0)}, {"LITERAL": Fraction(0)})
    with rejects("SE_STATISTIC must be max or pooled"):
        tiny_config(constants={**TINY_CONSTANTS, "SE_STATISTIC": "bad"})
    missing_rows = [(Fraction(i), (Fraction(i),)) for i in range(18)] + [(None, ())] * 2
    partial = {"se2_max": {f"LITERAL|base|none|{m}": missing_rows for m in ("m0", "m10")}}
    expected = {"LITERAL": run.se_bound([Fraction(17)])}
    assert run._bounds(partial, ("LITERAL",)) == (expected, expected)
    phase["se2_max"]["LITERAL|base|none|m10"] = [(None, ())] * 20
    assert run._bounds(phase, ("LITERAL",)) == ({"LITERAL": None}, {"LITERAL": None})


def test_variant_preparation(tiny_inputs, tables):
    raw = tiny_raw()
    raw["probe_only"]["tokens"] = [["F", "life-a", "B0", 2, 1]]
    inputs = run.parse_inputs(canon(raw), ladder=((2, 5),))
    main = context(inputs, tiny_config(), tables)
    no_reserve = context(inputs, tiny_config(), tables, variant="reserve0")
    assert main.reserves == (1, 0) and no_reserve.reserves == (0, 0)
    assert main.prep.design.capacity.pinned == 1
    assert no_reserve.prep.design.capacity.pinned == 2
    assert context(inputs, tiny_config(), tables, variant="tau0").tau == {"X": 0.0}
    assert not context(inputs, tiny_config(), tables, variant="no_system_passovers").prep.design.system_passovers
    lower = replace(inputs.params, rho_x=0.25)
    inputs = replace(inputs, sensitivity_params={"inputs_low": lower})
    assert context(inputs, tiny_config(), tables, variant="inputs_low").params is lower


def test_niced_parent_adjustment(tiny_inputs, monkeypatch):
    values, increments = [10], []

    def nice(increment):
        if increment:
            increments.append(increment)
            values[0] += increment
        return values[0]

    monkeypatch.setattr(run.os, "nice", nice)
    monkeypatch.setattr(run, "PointContext", lambda *args: object())
    run._init(tiny_inputs.source_bytes, tiny_config(), (2, 5), "main", True)
    assert values == [19] and increments == [9]
    run._init(tiny_inputs.source_bytes, tiny_config(), (2, 5), "main", True)
    assert increments == [9]


def test_checkpoint_1000_order_and_partial_resume(tiny_inputs, tmp_path, monkeypatch):
    config = tiny_config(constants={**TINY_CONSTANTS, "CHUNK": 25})
    pool = run._Pool(tiny_inputs, config, (2, 5), "main", [])
    ids = ("LITERAL|base|none|m0",)
    hashes = {"inputs": "a", "c8": "b", "config": "c"}
    submitted = []

    def reversed_results(pool, tasks, bounds, *, solver=False):
        submitted.extend(tasks)
        for _, r0, r1, cases in reversed(list(tasks)):
            n = r1 - r0
            yield run.ChunkResult(r0, {c: (0, 0, 0, n, 0, 0, 0) for c in cases},
                                  {c: tuple((Fraction(r), (Fraction(r),)) for r in range(r0, r1))
                                   for c in cases}, {"replicates": 0, "certify_calls": 0,
                                                     "fields_compared": 0, "mismatches": 0})

    monkeypatch.setattr(run._Pool, "results", reversed_results)
    full = run._phase(pool, "phase0", 0, 1002, ids, {}, tmp_path, hashes)
    assert [v for v, _ in full["se2_max"][ids[0]]] == list(map(Fraction, range(1002)))
    checkpoints = list((tmp_path / "checkpoints").glob("*.json"))
    assert {p.name for p in checkpoints} == {"2-5-main-phase0-1000.json", "2-5-main-phase0-1002.json"}
    (tmp_path / "checkpoints/2-5-main-phase0-1002.json").unlink()
    pool.config = run.copy_config(config, resume=True)
    submitted.clear()
    resumed = run._phase(pool, "phase0", 0, 1002, ids, {}, tmp_path, hashes)
    assert submitted == [("phase0", 1000, 1002, ids)]
    assert resumed["counts"] == full["counts"]
    assert resumed["se2_max"] == full["se2_max"]


def test_cli_routes_without_running_a_simulation(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(run, "load_inputs", lambda *args, **kwargs: "parsed")
    monkeypatch.setattr(run, "run", lambda inputs, config, out:
                        seen.append((inputs, config, out)) or 0)
    assert run.main(["--inputs", "synthetic.json", "--alternatives", "LITERAL,PRE_SWAP",
                     "--workers", "1", "--out", str(tmp_path), "--resume",
                     "--busy-marker", "marker --synthetic"]) == 0
    assert seen[0][0] == "parsed" and seen[0][1].resume
    assert seen[0][1].alternatives == ("LITERAL", "PRE_SWAP")
    assert seen[0][1].busy_marker == ("marker", "--synthetic")


def test_margin_floor_clamp(tiny_inputs):
    cell = replace(tiny_inputs.params.cells[0], f0=100.0 + 2**-43, c0=400.0)
    assert 0.5 + 150 / (cell.c0 - cell.f0) > 1.0
    assert model.interpolation(cell, 15) == 1.0
    with rejects("cell X: margin gives lambda outside [0, 1]"):
        model.interpolation(cell, 16)
