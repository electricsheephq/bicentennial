"""Socket-only fake-host acceptance of several arms sharing the unit worker pool."""

import json
import socket
import sys
from contextlib import closing
from pathlib import Path
from threading import Barrier, Lock

import pytest
from test_t1 import environment, installed, prepare  # noqa: F401
from test_t2lite import Stack

from bicentennial.canon import canon
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.runner import life, t2lite, units
from bicentennial.runner.probe_live import LiveStop
from bicentennial.world.db import open_world


@pytest.fixture
def sockets():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("socket-only fake-host worker acceptance")


class SharedStack(Stack):
    def __init__(self):
        super().__init__()
        self.lock = Lock()

    def respond(self, call):
        with self.lock:
            return super().respond(call)

    def state(self):
        with self.lock:
            return super().state()


def receipt_projection(collected, status):
    receipt = t2lite._receipt(collected.runs, 0, status, units=collected.timings)
    # STABLE-FIELDS marks all these measurements volatile. Retain unit identity and attempts.
    keep = ("canary", "run_status", "spend_micro_usd", "turn_wait_s")
    return {k: receipt[k] for k in keep} | {"units": [
        {k: v for k, v in row.items() if k not in ("start_ms", "end_ms", "slot")}
        for row in receipt["units"]]}


def install_fake_driver(monkeypatch):
    def drive(**kw):
        directory, branch = kw["life_dir"], kw["branch"]
        meta = json.loads((directory / "life.json").read_bytes())
        schedule = life.build_schedule(meta["seed"], meta["life"], life.named(meta["scale"]))
        with closing(open_world(directory / f"world.{branch}.db", readonly=True)) as db:
            compiled = compile_script(directory, branch, schedule, db, items=kw["items"],
                                      step_s=life.STEP_S, answer_contract=answer_contract)
        timeline = kw["scratch"] / "timeline.json"
        timeline.parent.mkdir(parents=True, exist_ok=True)
        timeline.write_bytes(canon({t["user"]: [s["index"], t["n"], s["kind"]]
                                    for s in compiled.script["sessions"] for t in s["turns"]}))
        kw["worker_argv"] = [sys.executable, str(Path(__file__).with_name("fake_life_worker.py")),
                             "--timeline", str(timeline)]
        return life.run_life(**kw)

    monkeypatch.setattr(units, "run_life", drive)


def test_two_fake_arms_serial_parallel_equal(sockets, installed, tmp_path, monkeypatch):  # noqa: F811
    install_fake_driver(monkeypatch)
    ctx = prepare(installed)
    arms = [units.Arm.from_context(ctx, key) for key in ("a", "b")]
    results = []
    for roots in (1, 2):
        queue = units.make_units(ctx, arms, tmp_path / str(roots) / "scratch", tmp_path / str(roots) / "out")
        collected = units.schedule(ctx, queue, units._Guard(SharedStack()), roots=roots)
        collected.merge([], [])
        results.append(collected)
        assert list(collected.results) == [u.identity for u in queue]
        assert len([r for r in collected.runs if r.arm == "no_memory"]) == 4
    assert {k: v.scores for k, v in results[0].results.items()} == {
        k: v.scores for k, v in results[1].results.items()}
    assert receipt_projection(results[0], "COMPLETE") == receipt_projection(results[1], "COMPLETE")


def test_fake_arm_stop_infra_keeps_all_attempts(sockets, installed, tmp_path, monkeypatch):  # noqa: F811
    install_fake_driver(monkeypatch)
    ctx = prepare(installed)
    a, b = [units.Arm.from_context(ctx, key) for key in ("a", "b")]
    p = ctx.packs[0]
    queue = [units.Unit(arm, p, "B0", tmp_path / arm.key, tmp_path / "out" / arm.key) for arm in (a, b)]
    barrier = Barrier(2)
    execute = units._unit

    def failing(*args, **kw):
        result = execute(*args, **kw)
        barrier.wait(timeout=60)
        key = args[3]
        error = LiveStop("synthetic provider stop") if key == "a" else units.LatchStop("stopped")
        raise units.UnitRefusal(error, result.runs, result.timing)

    collected = units.schedule(ctx, queue, units._Guard(SharedStack()), roots=2, execute=failing)
    runs, timings = [], []
    with pytest.raises(LiveStop, match="synthetic provider stop"):
        collected.merge(runs, timings)
    assert units.refusal_code(units.reduce_refusals(collected.errors)) == "live_stop"
    assert [r.arm for r in runs] == ["a", "b"]
    receipt = t2lite._receipt(runs, 0, "INFRA_FAILURE", units=timings)
    assert receipt["run_status"] == "INFRA_FAILURE"
    assert [r["arm"] for r in receipt["units"]] == ["a", "b"]
    assert receipt["raw_body_digest"] == t2lite.raw_body_digest([r for run in runs for r in run.records])
