"""Arm time uses one monotonic clock while receipts retain wall stamps."""

import json
import re
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_t2 import live_settings, read, scenario, t2_scenario  # noqa: F401

from bicentennial.runner import arm_time, t2, t2lite, units
from bicentennial.runner.arm_time import calculate_arm_times, units_json_inputs


class Clock:
    def __init__(self, step_ns=0):
        self.elapsed_ns = 0
        self.shift_ns = 0
        self.step_ns = step_ns
        self.stepped = False

    def monotonic_ns(self):
        return 9_000_000_700_000 + self.elapsed_ns

    def time_ns(self):
        return 1_800_000_000_000_000_000 + self.elapsed_ns + self.shift_ns

    def time(self):
        return self.time_ns() / 1_000_000_000

    def advance(self, ns):
        self.elapsed_ns += ns


@pytest.fixture
def clocked_t2(t2_scenario, monkeypatch):  # noqa: F811
    drive, keep, scan = units.run_life, t2.keep_failed, t2._scan
    build = t2.build_live_stack
    state = SimpleNamespace(clock=None, scan_ends=[])

    def life(**kw):
        run = drive(**kw)
        state.clock.advance(2_000_600_000)
        if kw["arm"] == "system" and not state.clock.stepped:
            state.clock.shift_ns += state.clock.step_ns
            state.clock.stepped = True
        return run

    def kept(*args, **kw):
        keep(*args, **kw)
        state.clock.advance(700_500_000)

    def scanned(*args):
        scan(*args)
        state.clock.advance(91_500_000)
        state.scan_ends.append(state.clock.elapsed_ns // 1_000_000)

    def stack(*args, **kw):
        result = build(*args, **kw)
        state.clock.advance(state.setup_ns)
        return result

    def run(name, step_ns=0, setup_ns=0):
        state.clock = Clock(step_ns)
        state.setup_ns = setup_ns
        state.scan_ends.clear()
        monkeypatch.setattr(units, "time", state.clock)
        monkeypatch.setattr(t2, "time", state.clock)
        out = t2_scenario.out.parent / name
        cache = out.with_name(name + "-cache")
        code = t2_scenario.invoke(name, slots=1, cache=cache)
        assert state.clock.stepped
        return code, out, cache

    def invoke(name, step_ns=0, setup_ns=0):
        code, out, cache = run(name, step_ns, setup_ns)
        assert code == 0
        card = read(out, "card.json")
        assert card["counts"]["kept_copies"] == 2
        assert (out / "receipt.json").is_file()
        kept_paths = [r["kept"] for r in read(out, "kept/index.json") if r["kept"]]
        assert len(kept_paths) == 2
        assert all((out / path / "bundle.json").is_file() for path in kept_paths)
        assert len(list(cache.glob("*.t2-floor.json"))) == 4
        data = read(out, "units.json")
        for name in ("receipt.json", "receipts/system.json", "receipts/no_memory.json"):
            receipt = read(out, name)
            assert receipt["wall_start_ms"] == data["start_ms"]
            assert receipt["wall_end_ms"] == data["end_ms"]
            for row in receipt["units"]:
                assert set(row) == {"life", "branch", "arm", "slot", "start_ms", "end_ms", "attempts"}
                source, = [r for r in data["units"]
                           if all(r[k] == row[k] for k in ("arm", "life", "branch"))]
                assert all(source[k] == v for k, v in row.items())
        return data

    monkeypatch.setattr(units, "run_life", life)
    monkeypatch.setattr(t2, "keep_failed", kept)
    monkeypatch.setattr(t2, "_scan", scanned)
    monkeypatch.setattr(t2, "build_live_stack", stack)
    state.run = run
    state.invoke = invoke
    return state


@pytest.mark.parametrize("step_ns", [-5_000_000_000, -250_000_000, 3_600_000_000_000],
                         ids=["backwards-larger-than-unit", "backwards-small", "forwards-hour"])
def test_wall_steps_do_not_change_arm_time(clocked_t2, step_ns):
    setup_ns = 10_000_000_000
    normal = clocked_t2.invoke("normal", setup_ns=setup_ns)
    stepped = clocked_t2.invoke("stepped", step_ns, setup_ns=setup_ns)
    assert stepped["arm_time"] == normal["arm_time"]
    assert stepped["end_ms"] - normal["end_ms"] == step_ns // 1_000_000
    changed, = [r for r in stepped["units"] if r["arm"] == "system" and
                r["start_ms"] - stepped["start_ms"] == r["t_start_ms"]]
    wall_duration = changed["end_ms"] - changed["start_ms"]
    mono_duration = changed["t_end_ms"] - changed["t_start_ms"]
    assert wall_duration - mono_duration == step_ns // 1_000_000
    if step_ns == -5_000_000_000:
        assert mono_duration < -step_ns // 1_000_000 < changed["t_start_ms"]
        assert wall_duration < 0
        assert stepped["end_ms"] >= stepped["start_ms"]


def test_backward_step_reversing_run_fails_receipt_check(clocked_t2, capsys):
    code, out, cache = clocked_t2.run("reversed", -3_600_000_000_000)
    assert clocked_t2.clock.elapsed_ns < 3_600_000_000_000
    assert code == 70
    assert "ValueError: wall time reversed" in capsys.readouterr().err
    assert read(out, "refusal.json") == {"code": "tool_failure"}
    assert all(not (out / name).exists() for name in ("card.json", "receipt.json", "units.json"))
    assert not list(cache.glob("*.t2-floor.json"))


def test_units_json_recomputes_from_monotonic_offsets(clocked_t2):
    data = clocked_t2.invoke("normal")
    snapshot = deepcopy(data)
    assert calculate_arm_times(*units_json_inputs(data)) == data["arm_time"]
    assert data == snapshot
    assert all(type(r[k]) is int for r in data["units"] for k in ("t_start_ms", "t_end_ms"))
    assert all(0 <= r["t_start_ms"] <= r["t_end_ms"] <= data["t_end_ms"] for r in data["units"])
    # Fractional milliseconds accumulate before flooring each offset from the run start.
    assert data["t_end_ms"] == (8 * 2_000_600_000 + 4 * 700_500_000 + 91_500_000) // 1_000_000


def test_monotonic_run_end_includes_full_scan(clocked_t2):
    data = clocked_t2.invoke("normal")
    assert clocked_t2.scan_ends == [data["t_end_ms"]]
    assert data["t_end_ms"] - max(r["t_end_ms"] for r in data["units"]) >= 91
    assert data["arm_time"]["arms"]["system"]["outside_ms"] >= 91


def test_monotonic_unit_end_includes_keep(clocked_t2):
    data = clocked_t2.invoke("normal")
    rows = [r for r in data["units"] if r["arm"] == "system"]
    assert len(rows) == 4
    assert all(r["keep_ms"] == 700 for r in rows)
    assert all(r["t_end_ms"] - r["t_start_ms"] >= 2701 for r in rows)
    assert all(r["duration_ms"] >= 2701 for r in data["arm_time"]["arms"]["system"]["units"])


def test_units_json_inputs_ignore_wall_endpoints():
    data = dict(slots=1, start_ms=50_000, end_ms=-50_000, t_end_ms=30,
                units=[dict(arm="system", life="life", branch="B0", slot=0, slots=1,
                            predicted_s=1, card_index=0, start_ms=50_010, end_ms=-50_010,
                            t_start_ms=10, t_end_ms=20)])
    snapshot = deepcopy(data)
    slots, rows, start, end = units_json_inputs(json.loads(json.dumps(data)))
    assert (slots, start, end) == (1, 0, 30)
    assert rows[0]["start_ms"] == 10 and rows[0]["end_ms"] == 20
    assert "slots" not in rows[0]
    assert calculate_arm_times(slots, rows, start, end)["arms"]["system"]["arm_time_ms"] == 30
    assert data == snapshot


def test_refused_unit_retains_monotonic_span(t2_scenario, monkeypatch, tmp_path):  # noqa: F811
    clock = Clock()
    monkeypatch.setattr(units, "time", clock)

    def refused(*args, **kw):
        clock.advance(3_000_000)
        clock.shift_ns -= 3_600_000_000_000
        raise ValueError("synthetic refusal")

    monkeypatch.setattr(units, "_unit_attempts", refused)
    with pytest.raises(units.UnitRefusal) as caught:
        units._unit(t2_scenario.ctx, t2_scenario.ctx.packs[0], "B0", "system", tmp_path,
                    units._Guard(SimpleNamespace()), tmp_path)
    refusal = caught.value
    assert refusal.mono_ns == (9_000_000_700_000, 9_000_003_700_000)
    assert refusal.timing["end_ms"] < refusal.timing["start_ms"]
    assert set(refusal.timing) == {"life", "branch", "arm", "slot", "start_ms", "end_ms", "attempts"}


def test_t2lite_receipts_have_only_wall_unit_fields(scenario):  # noqa: F811
    assert scenario.invoke() == 0
    receipt = read(scenario.out, "receipt.json")
    assert receipt["units"]
    assert all(set(row) == {"life", "branch", "arm", "slot", "start_ms", "end_ms", "attempts"}
               for row in receipt["units"])
    assert t2lite._unit is units._unit


def test_monotonic_erratum_and_guide_name_recompute_helper():
    root = Path(__file__).resolve().parents[2]
    text = (root / "specs/ring0/RING0.md").read_text()
    heading = "**Erratum, 2026-11-04 (#460): the clock that times an arm.**"
    assert text.count(heading) == 1
    erratum = text.split(heading, 1)[1].split("\n\n", 1)[0]
    assert re.search(r"Unit intervals and the run's elapsed time.*monotonic clock.*run's start", erratum)
    assert "wall-clock step changes no arm time" in erratum
    assert "Receipts keep their wall-clock stamps" in erratum
    assert text.index("**Erratum, 2026-11-04 (#391): when a run ends.**") < text.index(heading)
    guide = (root / "docs/developers/t2.md").read_text()
    assert f"calculate_arm_times(*{arm_time.units_json_inputs.__name__}(json.loads(...)))" in guide
    assert all(f"`{field}`" in guide for field in ("t_start_ms", "t_end_ms"))
    changelog = (root / "prereg/CHANGELOG.md").read_text()
    section = changelog.split("## Ring 0 erratum, 2026-11-04: the clock that times an arm (#460, §14.8)\n", 1)[1]
    section = section.split("\n## ", 1)[0]
    assert "monotonic" in section and "wall-clock stamps" in section
    assert section.rstrip().endswith("No PREREG version change; PREREG-v0.5 remains frozen.")
    boundary = ("A backward wall-clock step larger than the run's elapsed time still fails "
                "the receipt's existing check, and the run publishes nothing.")
    assert all(boundary in document for document in (erratum, guide, section))
