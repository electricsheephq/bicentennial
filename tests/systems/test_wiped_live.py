"""Pinned-Hermes acceptance, explicitly opt-in; no upstream or model calls."""

import os
import runpy
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.harness.hermes.adapter import verify_pin
from bicentennial.harness.hermes.config import hermes_config
from bicentennial.runner.guard import admit, read_marker
from bicentennial.sandbox.surfaces import surface_hash
from bicentennial.systems.controls import WipeOnWake

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_wiped.py")))
ENTRY, LIFE = HELPERS["ENTRY"], HELPERS["LIFE"]
compile_micro_life, make, session = (HELPERS[k] for k in ("compile_micro_life", "make", "session"))


def checkout():
    given = os.environ.get("BICENTENNIAL_HERMES")
    if not given or not (Path(given) / ".venv/bin/python").exists():
        pytest.skip("BICENTENNIAL_HERMES is unset or has no .venv/bin/python")
    admission = admit(read_marker(), heavy=False, roots=1)
    if not admission.admitted:
        pytest.skip(f"busy marker: {admission.reason}")
    hermes = Path(given)
    verify_pin(hermes, ENTRY["artifact"])
    return hermes


def test_live_wiped_replay(tmp_path):
    hermes = checkout()
    root, seen = tmp_path / "wiped", []
    hook = WipeOnWake(ENTRY, {"HERMES_HOME": root / "hermes-home"}, root / "control")

    def before_spawn(reason):
        wiped = hook(reason)
        if wiped:
            assert surface_hash(root / "hermes-home", HELPERS["VOLATILE"]) == hook.fresh_install_hashes[0]
        seen.append(reason)
        return wiped

    script = compile_micro_life(dict(LIFE, sessions=LIFE["sessions"][:5], probes=[]))
    a = make(tmp_path, "wiped", script=script, hook=before_spawn, checkout=hermes, worker_argv=None)
    try:
        results = [session(a, i) for i in range(1, 6)]
        assert [r.reset for r in results] == [None] + ["control_wipe"] * 4
        for result, scripted in zip(results, script["sessions"], strict=True):
            assert result.finals_matched == len(scripted["turns"])
            assert result.finals == tuple((t["n"], t["assistant"]) for t in scripted["turns"])
        assert results[-1].restarts[0]["history_after"] == 0
        assert seen == ["session_start"] * 5 + ["kill"]
    finally:
        a.close()


def test_live_no_memory_cell(tmp_path):
    hermes = checkout()
    script = compile_micro_life(dict(LIFE, sessions=[], probes=LIFE["probes"][:1]))
    # TokenReaderStandIn returns text only on probe_main; no tool calls are requested.
    a = make(tmp_path, "floor", script=script, faults=[], floor=True, checkout=hermes, worker_argv=None)
    try:
        result = session(a, 1)
        assert result.turns_ok == 2 and len(result.finals) == 2
        bodies = HELPERS["request_bodies"](a)
        assert bodies
        for body in bodies:
            offered = {t.get("function", t).get("name") for t in body.get("tools", [])}
            assert not offered & {"memory", "session_search"}
        assert a.harness_record()["memory"] is False
        assert (a.paths["hermes_home"] / "config.yaml").read_bytes() == canon(
            hermes_config(a.server.port, "bicentennial-main", memory=False)) + b"\n"
    finally:
        a.close()
