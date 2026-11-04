"""Probe policy and final-attempt retention through the default unit executor."""

import time
from dataclasses import replace
from threading import Barrier, Event, Lock

import pytest
from test_t2lite import Stack, live_settings, scenario  # noqa: F401

from bicentennial.runner import units
from bicentennial.runner.hermes_score import Infra
from bicentennial.runner.kept import KeptRefused
from bicentennial.runner.life import LifeRun
from bicentennial.runner.probe_live import LatchStop, LiveCredentialStop, LiveStop


@pytest.fixture
def core(scenario, tmp_path):  # noqa: F811
    ctx = scenario.ctx
    ctx.turn_wait_s, ctx.roots = 0, 8
    for pack in ctx.packs:
        pack.schedule.sessions = range(10)

    def queue(keys=("system",), *, floor=False):
        arms = [units.Arm.from_context(ctx, key) for key in keys]
        if floor:
            arms.insert(0, units.Arm.from_context(ctx, "no_memory"))
        return [units.Unit(arm, ctx.packs[0], "B0", tmp_path / arm.key / "scratch",
                           tmp_path / arm.key / "out") for arm in arms]

    return ctx, queue


def schedule(core, *, keys=("system",), floor=False, keep=None, spec=units.T2_SPEC, roots=1, live=None):
    ctx, queue = core
    queued = queue(keys, floor=floor)
    result = units.schedule(ctx, queued, live or units._Guard(Stack()),
                            roots=roots, spec=spec, keep=keep)
    return queued, result


def test_probe_policy_t1_t2_and_t2lite(core, scenario, monkeypatch):  # noqa: F811
    drive, seen = units.run_life, []

    def record(**kw):
        seen.append((kw["arm"], kw["probe_mode"], kw["keep_pre_probe"], kw["pre_probe_attribution"]))
        return drive(**kw)

    monkeypatch.setattr(units, "run_life", record)
    _, collected = schedule(core, floor=True, spec=units.T1_SPEC)
    assert not collected.errors
    assert seen == [("no_memory", "ring0", False, False), ("system", "ring0", False, False)]
    seen.clear()
    assert scenario.invoke() == 0
    assert len(seen) == 8
    assert set(seen) == {("no_memory", "ring0", False, False), ("system", "ring0", False, False)}
    seen.clear()
    _, collected = schedule(core, keys=("other",), floor=True)
    assert not collected.errors
    assert set(seen) == {("no_memory", "per_item", False, False), ("system", "per_item", True, True)}


@pytest.mark.parametrize("infra_attempts", [0, 1, 3])
def test_keep_final_scored_attempt_before_cleanup(core, monkeypatch, infra_attempts):
    score, cleanup, events, seen = units.score_item, LifeRun.cleanup, [], []

    def scoring(item, **kw):
        return Infra("synthetic") if kw["attempt"] < infra_attempts else score(item, **kw)

    def cleaned(run):
        events.append(("cleanup", run.attempt))
        cleanup(run)

    def keep(unit, run, scores, excluded):
        assert run._root.is_dir()
        seen.append((unit, run, scores, excluded))
        events.append(("keep", run.attempt))
        # Mutating the copied row cannot change the returned score.
        scores[next(iter(scores))]["marker"] = True

    monkeypatch.setattr(units, "score_item", scoring)
    monkeypatch.setattr(LifeRun, "cleanup", cleaned)
    queued, result = schedule(core, keep=keep)
    assert not result.errors
    attempts = min(infra_attempts + 1, 3)
    assert len(seen) == 1
    unit, run, scores, excluded = seen[0]
    assert unit is queued[0] and run.attempt == attempts - 1 and excluded == set()
    assert events == [("cleanup", i) for i in range(attempts - 1)] + [
        ("keep", attempts - 1), ("cleanup", attempts - 1)]
    final = result.results[unit.identity]
    assert final.attempts == attempts
    assert "marker" not in next(iter(final.scores.values()))
    if infra_attempts == 3:
        iid = next(iter(final.scores))
        assert scores[iid]["failure_class"] == final.scores[iid]["failure_class"] == "BLOCKED"
        assert scores[iid]["infra_reruns"] == final.scores[iid]["infra_reruns"] == 2


def test_floor_gate_sees_original_infra_and_never_keeps(core, monkeypatch):
    measured, seen = units._floor_measured, []
    monkeypatch.setattr(units, "score_item", lambda *args, **kw: Infra("synthetic"))

    def gate(pack, branch, run, probes, scores):
        assert run.attempt == 2
        assert all(isinstance(score, Infra) for score in scores.values())
        seen.append(True)
        return measured(pack, branch, run, probes, scores)

    def keep(*args):
        pytest.fail("floor called keep")

    monkeypatch.setattr(units, "_floor_measured", gate)
    ctx, queue = core
    floor = queue(floor=True)[0]
    result = units.schedule(ctx, [floor], units._Guard(Stack()), spec=units.T2_SPEC, roots=1, keep=keep)
    assert not result.errors and seen == [True]
    assert result.results[floor.identity].measured is False


def test_excluded_matches_scoring_with_failed_action_kept(core, monkeypatch):
    ctx, _ = core
    pack = ctx.packs[0]
    pack = replace(pack, genre="G2")
    ctx.packs[0] = pack
    first = pack.items["B0"][0]
    first["stage"] = "act"
    second = dict(first, item_id="failed-action")
    pack.items["B0"].append(second)
    pack.cases[second["item_id"]] = type(pack.cases[first["item_id"]])(item=second)
    pack.keys[second["item_id"]] = {}
    drive, score, seen = units.run_life, units.score_item, []

    def scoring(item, **kw):
        if kw["cls"] == "SYSTEM_FAILURE":
            from bicentennial.score.classes import outcome
            return outcome(units.identity0(item), None, cause="SYSTEM_FAILURE", infra_reruns=kw["attempt"])
        return score(item, **kw)

    monkeypatch.setattr(units, "score_item", scoring)

    def stopped(**kw):
        run = drive(**kw)
        return replace(run, classes={second["item_id"]: ("SYSTEM_FAILURE", "turn_failed")},
                       stopped=("SYSTEM_FAILURE", "turn_failed", 21))

    def keep(unit, run, scores, excluded):
        seen.append((scores, excluded))

    monkeypatch.setattr(units, "run_life", stopped)
    _, result = schedule(core, keep=keep)
    assert not result.errors
    assert len(seen) == 1
    scores, excluded = seen[0]
    assert excluded == {first["item_id"]}
    assert scores[first["item_id"]]["score_milli"] is None
    assert scores[second["item_id"]]["score_milli"] == 0


def test_session_crash_recorded_by_life_keeps_final_attempt(core, monkeypatch):
    drive, seen = units.run_life, []

    def crashed(**kw):
        run = drive(**kw)
        return replace(run, stopped=("SYSTEM_FAILURE", "turn_failed", 21),
                       classes={i["item_id"]: ("SYSTEM_FAILURE", "turn_failed") for i in kw["items"]})

    monkeypatch.setattr(units, "run_life", crashed)
    queued, result = schedule(core, keep=lambda *args: seen.append(args))
    assert not result.errors and len(seen) == 1
    assert seen[0][0] is queued[0] and seen[0][1].stopped is not None
    assert result.results[queued[0].identity].attempts == 1


@pytest.mark.parametrize("failure", ["latch", "canary", "credential", "live", "spend", "isolation", "crash"])
def test_unscored_refusals_never_keep(core, monkeypatch, failure):
    drive, seen = units.run_life, []
    live = units._Guard(Stack())

    def refuse(**kw):
        if failure == "latch":
            raise LatchStop("latched_stop")
        if failure == "credential":
            raise LiveCredentialStop("upstream_401")
        if failure == "live":
            raise LiveStop("upstream_unavailable")
        if failure == "crash":
            raise RuntimeError("synthetic")
        run = drive(**kw)
        if failure == "canary":
            live.canary = True
        if failure == "spend":
            live.stack.values["spend_stopped"] = True
        if failure == "isolation":
            run = replace(run, egress={"non_loopback": ["unpermitted"]})
        return run

    monkeypatch.setattr(units, "run_life", refuse)
    _, result = schedule(core, live=live, keep=lambda *args: seen.append(args))
    assert seen == [] and len(result.errors) == 1
    expected = dict(latch="live_stop", canary="canary", credential="credential_stop", live="live_stop",
                    spend="spend_stop", isolation="isolation", crash="pin_mismatch")[failure]
    assert units.refusal_code(units.reduce_refusals(result.errors)) == expected
    assert live.stopped.is_set()
    assert len(result.runs) == (0 if failure == "crash" else 1)


def test_eight_workers_serialize_keep(core, monkeypatch):
    drive, entered, counter = units.run_life, Barrier(8), Lock()
    active, maximum, calls = 0, 0, []

    def together(**kw):
        run = drive(**kw)
        entered.wait(timeout=10)
        return run

    def keep(unit, run, scores, excluded):
        nonlocal active, maximum
        with counter:
            active += 1
            maximum = max(maximum, active)
        time.sleep(0.02)
        with counter:
            calls.append(unit.identity)
            active -= 1

    monkeypatch.setattr(units, "run_life", together)
    queued, result = schedule(core, keys=tuple(str(i) for i in range(8)), roots=8, keep=keep)
    assert not result.errors and maximum == 1 and active == 0
    assert set(calls) == {u.identity for u in queued} and len(calls) == 8


def test_no_keep_still_scores_and_cleans(core, monkeypatch):
    cleanup, seen = LifeRun.cleanup, []

    def cleaned(run):
        cleanup(run)
        seen.append(run._root.exists())

    monkeypatch.setattr(LifeRun, "cleanup", cleaned)
    _, result = schedule(core)
    assert not result.errors and seen == [False]


def test_keep_with_a_custom_executor_refuses(core):
    ctx, queue = core
    calls = []

    def execute(*args, **kwargs):
        calls.append(args)

    with pytest.raises(ValueError, match="keep needs the default executor"):
        units.schedule(ctx, queue(), units._Guard(Stack()), roots=1, spec=units.T2_SPEC,
                       execute=execute, keep=lambda *args: None)
    assert calls == []


@pytest.mark.parametrize("code", ["pre_probe_missing", "kept_exists", "credential_scan", "kept_cap"])
def test_kept_refusal_exact_code_and_merged_runs(core, code):
    def keep(*args):
        raise KeptRefused(code)

    queued, result = schedule(core, keep=keep)
    assert len(result.errors) == 1 and len(result.runs) == 1
    assert units.refusal_code(units.reduce_refusals(result.errors)) == code
    runs, timings = [], []
    with pytest.raises(KeptRefused) as raised:
        result.merge(runs, timings)
    assert raised.value.code == code
    assert runs == list(result.runs) and runs[0].arm == queued[0].arm.key
    assert timings == list(result.timings)


@pytest.mark.parametrize("code,expected", [("credential_scan", "credential_scan"), ("kept_cap", "live_stop")])
@pytest.mark.parametrize("reverse", [False, True])
def test_kept_and_live_precedence_in_either_order(core, monkeypatch, code, expected, reverse):
    barrier = Barrier(2)
    finished, errors = [], {"a": KeptRefused(code), "b": LiveStop("upstream_unavailable")}
    first, second = (("b", "a") if reverse else ("a", "b"))
    released = Event()

    def attempts(ctx, pack, branch, role, scratch, live, runs, out, stops, **kw):
        key = kw["unit"].arm.key
        runs.append(LifeRun(role, pack.life, branch, 0))
        barrier.wait(timeout=5)
        if key == second:
            assert released.wait(5)
            time.sleep(0.02)
        finished.append(key)
        if key == first:
            released.set()
        raise errors[key]

    monkeypatch.setattr(units, "_unit_attempts", attempts)
    _, result = schedule(core, keys=("a", "b"), roots=2)
    assert finished == [first, second]
    assert len(result.runs) == 2 and len(result.errors) == 2
    assert units.refusal_code(units.reduce_refusals(result.errors)) == expected
    assert units.refusal_code(units.reduce_refusals(reversed(result.errors))) == expected
