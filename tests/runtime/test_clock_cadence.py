"""The life runner changes cadence only at idle session boundaries."""

import json

import pytest

from bicentennial.runtime.clock import SimClock


def test_cadence_published_and_kept_at_boundaries(tmp_path):
    clock = SimClock(tmp_path / "clock.json", 1_600_000_000, 720)
    clock.set_session(1_600_001_000, step_s=60)
    clock.tick()
    assert clock.sim_t_s == 1_600_001_060
    assert json.loads(clock.path.read_bytes())["step_s"] == 60
    clock.set_session(1_600_002_000)
    clock.tick()
    assert clock.sim_t_s == 1_600_002_060
    clock.set_session(1_600_003_000, step_s=720)
    clock.tick()
    assert clock.sim_t_s == 1_600_003_720


@pytest.mark.parametrize("value,kind", [(0, ValueError), (-1, ValueError), (True, TypeError),
                                       (60.0, TypeError), ("60", TypeError)])
def test_invalid_cadence_does_not_publish(tmp_path, value, kind):
    clock = SimClock(tmp_path / "clock.json", 1_600_000_000, 720)
    before = clock.path.read_bytes()
    with pytest.raises(kind):
        clock.set_session(1_600_001_000, step_s=value)
    assert clock.step_s == 720
    assert clock.path.read_bytes() == before
