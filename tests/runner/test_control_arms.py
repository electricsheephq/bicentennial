"""Live control arms for T2: one probe-only arm, with a pinned control's text placed in the probe turn."""

import json
from hashlib import sha256

from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.canon import canon


def _digests(out):
    """Every file a run writes, with only its wall-clock and monotonic timing fields zeroed."""
    result = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".json":
            value = json.loads(data)
            def zero(obj):
                if isinstance(obj, dict):
                    return {k: 0 if k in TIMING else zero(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [zero(v) for v in obj]
                return obj
            data = canon(zero(value))
        result[path.relative_to(out).as_posix()] = sha256(data).hexdigest()
    return result


TIMING = {"wall_start_ms", "wall_end_ms", "load_milli", "start_ms", "end_ms", "t_start_ms", "t_end_ms",
          "pre_probe_ms", "keep_ms", "latency_ms", "runtime_by_role", "arm_time", "t_ms"}


def test_probe_digests(t2_scenario):
    s = t2_scenario
    assert s.invoke("a", slots=1) == 0
    assert s.invoke("b", slots=1) == 0
    a, b = _digests(s.out.parent / "a"), _digests(s.out.parent / "b")
    for k in sorted(set(a) | set(b)):
        print(k, a.get(k) == b.get(k), a.get(k))
    assert False
