"""Offline T2 publication, cache identity, retention and slot invariance."""

import fcntl
import json
import time
from dataclasses import replace
from threading import Event, Lock
from types import SimpleNamespace

import pytest
from test_kept_order import PINS, captured
from test_t2lite import Stack, live_settings, row, scenario  # noqa: F401

from bicentennial import cli
from bicentennial.contracts.run import validate
from bicentennial.runner import t2, units
from bicentennial.runner.arm_time import calculate_arm_times
from bicentennial.runner.hermes_score import Infra, identity0
from bicentennial.runner.kept import KeptRefused
from bicentennial.runner.probe_live import LiveStop
from bicentennial.runner.spend import Price, Spend
from bicentennial.score.classes import outcome


def read(out, name):
    return json.loads((out / name).read_bytes())


@pytest.fixture
def t2_scenario(scenario, monkeypatch, tmp_path):  # noqa: F811
    state, ctx = scenario, scenario.ctx
    ctx.roots, ctx.turn_wait_s = 4, 3.0
    ctx.index = {"packs": {p.rel: {"tree_sha256": str(n + 1) * 64} for n, p in enumerate(ctx.packs)}}
    ctx.pins.update({k: "c" * 64 for k in ("system_hash", "route_table_hash", "write_turn_package_hash")})
    packs = []
    for n, pack in enumerate(ctx.packs):
        directory = tmp_path / "packs" / pack.life
        (directory / "sealed").mkdir(parents=True)
        t2._write(directory / "sealed", "controls.json", {"broken": [dict(stage="remember", track="Recall")],
            "arms": {name: {"aggregates": [dict(stage="remember", track="Recall", score_milli=1000)]}
                     for name in ("no_memory", "oracle_evidence", "full_history")}})
        # Reuse one id in both branches to prove publication uses the full identity.
        items = {b: [dict(i, item_id=pack.life + "-shared") for i in pack.items[b]] for b in pack.items}
        if n == 1:
            for values in items.values():
                values.append(dict(row("action"), stage="act", probe_point=2))
                values.append(dict(row("unreached"), probe_point=5))
        records = {i["item_id"]: dict(item_id=i["item_id"], template_id="synthetic", template_version=1)
                   for values in items.values() for i in values}
        packs.append(replace(pack, dir=directory, life_dir=directory, genre="G2" if n else "G1",
            items=items, records=records, manifest={"pins": PINS},
            records_b={b: [records[i["item_id"]] for i in values] for b, values in items.items()},
            keys={iid: {} for iid in records},
            cases={i["item_id"]: SimpleNamespace(item=i) for values in items.values() for i in values}))
        pack.schedule.sessions = range(10)
    ctx.packs = packs
    state.behaviour, state.order, state.executed, state.finished = {}, False, [], []
    drive, score = units.run_life, units.score_item

    def life(**kw):
        key = (kw["arm"], kw["life_dir"].name, kw["branch"])
        state.executed.append(key)
        time.sleep(.015 if (kw["branch"] == "B0") != state.order else .001)
        behaviour = state.behaviour.get(key)
        if behaviour == "exception":
            raise RuntimeError("synthetic unit error")
        run = drive(**kw)
        if behaviour == "503":
            records = tuple(dict(r, status=503) for r in run.records)
            run = replace(run, records=records, classes={i["item_id"]: ("INFRA_FAILURE", "unavailable")
                                                       for i in kw["items"]})
        if behaviour == "non_live":
            run = replace(run, records=tuple(dict(r, served_by="local") for r in run.records))
        if behaviour == "stopped":
            run = replace(run, stopped=("SYSTEM_FAILURE", "turn_timeout", 5))
        if kw["arm"] == "system":
            run = replace(run, classes={**run.classes, **{i["item_id"]: ("SYSTEM_FAILURE", "turn_timeout")
                for i in kw["items"] if i["item_id"] in ("action", "unreached")}})
            pre = {}
            for item in kw["items"]:
                iid = item["item_id"]
                if behaviour == "stopped" and iid == "unreached":
                    continue
                source = captured(run._root / "capture" / iid, run.life, run.branch).pre_probe["a"]
                pre[iid] = replace(source, probe_point=item["probe_point"])
            run = replace(run, pre_probe=pre)
        state.finished.append(key)
        return run

    def scoring(item, **kw):
        if kw["cls"] == "INFRA_FAILURE":
            return Infra("synthetic")
        if item["item_id"] in (ctx.packs[0].life + "-shared", "action", "unreached"):
            return outcome(identity0(item), None, cause="SYSTEM_FAILURE")
        return score(item, **kw)

    build = __import__("bicentennial.runner.t2lite", fromlist=["build_live_stack"]).build_live_stack

    def stack(path, **kw):
        Spend(path, 0, Price(0, 0))
        return build(path, **kw)

    monkeypatch.setattr(units, "run_life", life)
    monkeypatch.setattr(units, "score_item", scoring)
    monkeypatch.setattr(t2, "build_live_stack", stack)
    monkeypatch.setattr(t2, "verify", lambda *a, **kw: None)
    state.invoke = lambda name="out", **kw: t2.run_t2(**(dict(system="hermes-native", packs_dir=tmp_path / "packs",
        pack_hash=ctx.pack_hash, out=tmp_path / name, login_home=state.home, max_sends=100) | kw))
    state.behaviour.update({("system", ctx.packs[1].life, b): "stopped" for b in ("B0", "B1")})
    return state


def test_complete_card_kept_and_receipts(t2_scenario):
    s = t2_scenario
    assert s.invoke() == 0
    out = s.out
    card = read(out, "card.json")
    validate("card_t2", card)
    assert card["controls_broken"] == [dict(stage="remember", track="Recall")]
    assert all({"life", "branch", "probe_point"} <= r.keys() for r in card["items"])
    assert len(read(out, "outcomes.json")) == 8
    assert card["counts"]["kept_copies"] == 2
    index = read(out, "kept/index.json")
    pointers = {r["repro"] for r in card["items"] if r["repro"]}
    assert pointers == {r["kept"] for r in index if r["kept"]}
    assert all((out / p / "bundle.json").is_file() for p in pointers)
    assert all(r["repro"] is None for r in card["items"] if r["item_id"] in ("action", "unreached"))
    assert all(r["kept"] is None and "surface_hashes" in r for r in index if r["item_id"] == "action")
    assert all(not r["reached"] for r in index if r["item_id"] == "unreached")
    assert len(card["not_scored_live"]) == 2
    assert all(r["failure_class"] == "SYSTEM_FAILURE" for r in card["items"] if r["item_id"] == "action")
    for name in ("receipt.json", "receipts/system.json", "receipts/no_memory.json"):
        validate("receipt", read(out, name))
    timing = read(out, "units.json")
    assert len(timing["units"]) == len(read(out, "receipt.json")["units"]) == 8
    assert all(r["slots"] == 4 for r in timing["units"])
    rows = [{k: v for k, v in r.items() if k != "slots"} for r in timing["units"]]
    assert timing["arm_time"] == calculate_arm_times(4, rows, timing["start_ms"], timing["end_ms"])


@pytest.mark.parametrize("repeat", range(3))
def test_slots_and_finish_order_preserve_outputs(t2_scenario, monkeypatch, repeat):
    s = t2_scenario
    snapshots, timing, finishes = [], [], []
    drive = units.run_life

    def ordered(**kw):
        selected = kw["arm"] == "system" and kw["life_dir"].name == s.ctx.packs[0].life
        second = (kw["branch"] == "B0") != s.order
        if slots != 1 and selected and second and not finished.wait(10):
            pytest.fail("first unit did not finish")
        run = drive(**kw)
        if selected and not second:
            finished.set()
        return run

    monkeypatch.setattr(units, "run_life", ordered)
    for n, slots in enumerate((1, None, None)):
        s.order = n == 2
        finished = Event()
        s.finished.clear()
        assert s.invoke(str(n), slots=slots) == 0
        out = s.out.parent / str(n)
        snapshots.append([(out / p).read_bytes() for p in ("card.json", "outcomes.json", "no_memory.json", "kept/index.json")])
        timing.append(read(out, "units.json"))
        finishes.append(list(s.finished))
    assert snapshots[0] == snapshots[1] == snapshots[2]
    a, b = [("system", s.ctx.packs[0].life, branch) for branch in ("B0", "B1")]
    assert finishes[1].index(b) < finishes[1].index(a)
    assert finishes[2].index(a) < finishes[2].index(b)
    first = timing[0]
    assert first["slots"] == 1 and first["admitted_slots"] == s.ctx.roots
    assert all(r["slots"] == 1 for r in first["units"])
    rows = [{k: v for k, v in r.items() if k != "slots"} for r in first["units"]]
    assert first["arm_time"] == calculate_arm_times(1, rows, first["start_ms"], first["end_ms"])
    assert first["arm_time"]["arms"]["system"]["slots"] == 1
    def stable(t):
        return [{k: v for k, v in r.items() if k not in ("slots", "slot", "start_ms", "end_ms", "pre_probe_ms", "keep_ms")} for r in t["units"]]
    assert all(type(r[k]) is int and r[k] >= 0 for t in timing for r in t["units"]
               for k in ("pre_probe_ms", "keep_ms"))
    assert stable(timing[0]) == stable(timing[1]) == stable(timing[2])


@pytest.mark.parametrize("slots", [0, -1, 1.5, True, "1"])
def test_invalid_slots_no_output(t2_scenario, slots):
    with pytest.raises(ValueError):
        t2_scenario.invoke(slots=slots)
    assert not t2_scenario.out.exists()


def test_slots_above_admission_tool_failure(t2_scenario):
    s = t2_scenario
    assert s.invoke(slots=s.ctx.roots + 1) == 70
    assert read(s.out, "refusal.json") == {"code": "tool_failure"}


def test_per_unit_cache_and_cached_plugin(t2_scenario, tmp_path, monkeypatch):
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache, slots=1) == 0
    keys = read(tmp_path / "first", "card.json")["floor"]["units"]
    s.executed.clear()
    monkeypatch.setattr(units, "is_plugin", lambda name: True)
    assert s.invoke(cache=cache) == 0
    assert all(arm == "system" for arm, _, _ in s.executed)
    assert len([c for c in s.stacks[-1].calls if c.role == "identity_check"]) == 1
    cached = read(s.out, "card.json")["floor"]["units"]
    assert all(v["cached"] for v in cached.values())
    assert {k: v["cache_key"] for k, v in keys.items()} == {k: v["cache_key"] for k, v in cached.items()}
    floor_receipt = read(s.out, "receipts/no_memory.json")
    validate("receipt", floor_receipt)
    assert floor_receipt["units"] == []
    assert [row["arm"] for row in floor_receipt["background"]] == ["system"]
    assert all(row["unattributed"]["count"] == 0 for row in floor_receipt["background"])
    assert read(s.out, "units.json")["arm_time"]["floor_replay_ms"] == 0
    assert all(r["arm"] == "system" for r in read(s.out, "units.json")["units"])
    assert [r["card_index"] for r in read(s.out, "units.json")["units"]] == list(range(4, 8))


def test_floor_key_parameters(t2_scenario):
    ctx = t2_scenario.ctx
    p = ctx.packs[0]
    def key(**kw):
        return t2.floor_key(ctx, p, kw.pop("branch", "B0"), **(dict(probe_mode="per_item", turn_wait_s=3.0) | kw))
    original = key()
    ctx.roots = 1
    ctx.entry["name"] = "synthetic-other-system"
    assert key() == original
    assert key(probe_mode="ring0") != original
    assert key(turn_wait_s=2.0) != original
    assert key(branch="B1") != original
    ctx.index["packs"][p.rel]["tree_sha256"] = "f" * 64
    assert key() != original


def test_identity_mismatch_runs_floor(t2_scenario, tmp_path):
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache) == 0
    s.stack_options["identity"] = "other-identity"
    s.executed.clear()
    assert s.invoke(cache=cache) == 0
    assert len([k for k in s.executed if k[0] == "no_memory"]) == 4
    assert all(r == dict(cached=False, reason="served identity differs")
               for r in read(s.out, "disclosures.json")["floor"].values())


@pytest.mark.parametrize("behaviour", ["503", "non_live"])
def test_non_live_final_floor_not_cached(t2_scenario, tmp_path, behaviour):
    s, cache = t2_scenario, tmp_path / "cache"
    p = s.ctx.packs[0]
    s.behaviour[("no_memory", p.life, "B0")] = behaviour
    assert s.invoke(cache=cache) == 0
    assert len(list(cache.glob("*.t2-floor.json"))) == 3
    key = t2.floor_key(s.ctx, p, "B0", probe_mode="per_item", turn_wait_s=3.0)
    assert not (cache / (key + ".t2-floor.json")).exists()


def test_scan_refusal_never_writes_cache(t2_scenario, tmp_path, monkeypatch):
    def scan(*a):
        raise t2.t1.T1Refused("credential_scan")
    monkeypatch.setattr(t2, "_scan", scan)
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke(cache=cache) == 3
    assert not list(cache.glob("*"))
    assert read(s.out, "refusal.json") == {"code": "credential_scan"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json"}


def test_shared_account_lock(t2_scenario):
    s = t2_scenario
    with (s.home / ".t2lite.lock").open("w") as account:
        fcntl.flock(account, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": "account_busy"}


def test_kept_cap_refusal(t2_scenario, monkeypatch):
    def keep(*a, **kw):
        raise KeptRefused("kept_cap")
    monkeypatch.setattr(t2, "keep_failed", keep)
    s = t2_scenario
    assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": "kept_cap"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json"}


def test_unexpected_unit_tool_failure(t2_scenario):
    s = t2_scenario
    s.behaviour[("system", s.ctx.packs[0].life, "B0")] = "exception"
    assert s.invoke() == 70
    assert read(s.out, "refusal.json") == {"code": "tool_failure"}


@pytest.mark.parametrize("mode,code", [("credential", "credential_stop"), ("spend", "spend_stop"), ("live_stop", "live_stop")])
def test_stop_receipt_and_custody(t2_scenario, mode, code):
    s = t2_scenario
    s.mode = mode
    assert s.invoke() == 3
    assert read(s.out, "refusal.json")["code"] == code
    receipt = read(s.out, "receipt.json")
    validate("receipt", receipt)
    assert receipt["run_status"] == "INFRA_FAILURE"
    assert read(s.out, "custody.json")


def test_cli_exact_flags(monkeypatch, capsys):
    import re
    with pytest.raises(SystemExit) as caught:
        cli.main(["t2", "--help"])
    assert caught.value.code == 0
    flags = set(re.findall(r"--[a-z-]+", capsys.readouterr().out))
    assert flags == {"--help", "--system", "--entry", "--pack-hash", "--out", "--login-home", "--packs", "--max-sends",
                     "--hermes", "--plugin-source", "--model-cache", "--cache", "--sandbox-slot", "--turn-wait"}
    seen = []
    monkeypatch.setattr(cli, "run_t2", lambda **kw: seen.append(kw) or 0)
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: seen.append(argv))
    args = ["t2", "--system", "hermes-native", "--pack-hash", "a" * 64, "--out", "out",
            "--login-home", "login", "--packs", "packs", "--max-sends", "10"]
    assert cli.main(args) == 0
    assert seen[0][:2] == ["-m", "bicentennial.cli"]
    assert seen[1]["turn_wait_s"] == 3.0
    monkeypatch.delenv("PYTHONHASHSEED")
    assert cli.main(args) == 3


@pytest.mark.parametrize("reverse", [False, True])
def test_hook_credential_scan_wins_over_live_stop(t2_scenario, monkeypatch, reverse):
    from threading import Barrier
    s, barrier = t2_scenario, Barrier(2)
    original, keep = units.run_life, t2.keep_failed
    first, second = s.ctx.packs[1].life, s.ctx.packs[0].life

    def drive(**kw):
        if kw["arm"] == "system" and kw["branch"] == "B0":
            if kw["life_dir"].name == second:
                barrier.wait(timeout=5)
                time.sleep(.03 if reverse else 0)
                raise LiveStop("synthetic_stop")
        return original(**kw)

    def hook(run, *a, **kw):
        if run.life == first and run.branch == "B0":
            barrier.wait(timeout=5)
            time.sleep(0 if reverse else .03)
            raise KeptRefused("credential_scan")
        return keep(run, *a, **kw)

    monkeypatch.setattr(units, "run_life", drive)
    monkeypatch.setattr(t2, "keep_failed", hook)
    assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": "credential_scan"}


def test_keep_hook_separates_two_system_arms(t2_scenario, tmp_path):
    ctx = t2_scenario.ctx
    roots = {key: tmp_path / key for key in ("first", "second")}
    queue = units.make_units(ctx, [units.Arm.from_context(ctx, key) for key in roots], tmp_path / "scratch", tmp_path / "unit-out")
    collected = units.schedule(ctx, queue, units._Guard(Stack()), spec=units.T2_SPEC,
                              keep=t2.keep_hook(ctx, roots, set()))
    assert not collected.errors
    for root in roots.values():
        index = read(root, "kept/index.json")
        assert len(index) == 8
        assert len({(r["life"], r["branch"], r["item_id"]) for r in index}) == 8
        assert sum(bool(r["kept"]) for r in index) == 2
        assert all((root / r["kept"]).is_dir() for r in index if r["kept"])


@pytest.mark.parametrize("code", ["roots_below_min", "tier"])
def test_preparation_refusal_published(t2_scenario, monkeypatch, code):
    def prepare(**kw):
        assert kw["spec"] is units.T2_SPEC
        raise t2.t1.T1Refused(code)
    monkeypatch.setattr(t2.t1, "prepare", prepare)
    s = t2_scenario
    assert s.invoke() == 3
    assert read(s.out, "refusal.json") == {"code": code}


def test_real_public_t2_preparation_and_item_identities(tmp_path, monkeypatch):
    from test_t1 import measured, writable

    from bicentennial.packs.build import build_tier
    from bicentennial.packs.install import install
    from bicentennial.runner.guard import Marker
    from bicentennial.systems.registry import REGISTRY, load

    # Real pack trees exercise C-7, composition, boundaries and per-life tree identities.
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    build_tier("T2", tmp_path / "built", harness_artifacts=[artifact])
    digest = install(tmp_path / "built/T2", tmp_path / "installed")
    monkeypatch.setattr(t2.t1, "read_marker", lambda: Marker(0, False, "synthetic"))
    monkeypatch.setattr(t2.t1, "worker_properties", lambda *a: ())
    try:
        ctx = t2.t1.prepare(system="hermes-native", packs=tmp_path / "installed", pack_hash=digest,
                            entry=measured(), worker_argv=["synthetic"], spec=units.T2_SPEC)
        assert ctx.roots == 8 and len(ctx.packs) == 10
        ids = [i["item_id"] for p in ctx.packs for values in p.items.values() for i in values]
        assert len(ids) == len(set(ids))
        assert all(ctx.index["packs"][p.rel]["tree_sha256"] for p in ctx.packs)
        monkeypatch.setattr(t2.t1, "read_marker", lambda: Marker(10, False, "synthetic"))
        with pytest.raises(t2.t1.T1Refused, match="^roots_below_min$"):
            t2.t1.prepare(system="hermes-native", packs=tmp_path / "installed", pack_hash=digest,
                          entry=measured(), worker_argv=["synthetic"], spec=units.T2_SPEC)
    finally:
        writable(tmp_path / "installed")


@pytest.mark.parametrize("damage", ["outcomes", "stops", "identity", "corrupt"])
def test_cache_validation_is_per_unit(t2_scenario, tmp_path, damage):
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache) == 0
    path = next(cache.glob("*.t2-floor.json"))
    entry = json.loads(path.read_bytes())
    if damage == "outcomes":
        entry["outcomes"] = {}
    elif damage == "stops":
        entry["stops"] = {}
    elif damage == "identity":
        entry["served_identity"] = "unidentified"
    path.write_text("{" if damage == "corrupt" else json.dumps(entry))
    s.executed.clear()
    assert s.invoke(cache=cache) == 0
    assert len([k for k in s.executed if k[0] == "no_memory"]) == 1
    assert read(s.out, "card.json")["counts"]["floor_cached_units"] == 3


def test_refreshed_token_scan_reaches_kept_copies(t2_scenario, monkeypatch, tmp_path):
    s, cache = t2_scenario, tmp_path / "cache"
    build, drive, scan = t2.build_live_stack, units.run_life, t2._scan
    seen = []

    def stack(*a, **kw):
        result = build(*a, **kw)
        result.inner.login.needles = lambda: {"synthetic-rotated-token"}
        return result

    def life(**kw):
        run = drive(**kw)
        if run.pre_probe and run.life == s.ctx.packs[0].life:
            record = next(iter(run.pre_probe.values()))
            (record.directory / "rotated").write_text("synthetic-rotated-token")
        return run

    def scanned(out, needles):
        seen.extend(p for p in (out / "kept").rglob("rotated") if p.is_file())
        return scan(out, needles)

    monkeypatch.setattr(t2, "build_live_stack", stack)
    monkeypatch.setattr(units, "run_life", life)
    monkeypatch.setattr(t2, "_scan", scanned)
    assert s.invoke(cache=cache) == 3
    assert seen
    assert read(s.out, "refusal.json") == {"code": "credential_scan"}
    assert not list(cache.glob("*"))


def test_identity_check_filters_hits_individually(t2_scenario, tmp_path):
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache) == 0
    path = next(cache.glob("*.t2-floor.json"))
    entry = json.loads(path.read_bytes())
    entry["served_identity"] = "other-identity"
    path.write_text(json.dumps(entry))
    s.executed.clear()
    assert s.invoke(cache=cache) == 0
    assert len([k for k in s.executed if k[0] == "no_memory"]) == 1
    assert len([c for c in s.stacks[-1].calls if c.role == "identity_check"]) == 1
    assert read(s.out, "card.json")["counts"]["floor_cached_units"] == 3


def test_card_infra_counts_final_system_outcomes(t2_scenario):
    s = t2_scenario
    s.behaviour[("system", s.ctx.packs[0].life, "B0")] = "503"
    assert s.invoke() == 0
    card = read(s.out, "card.json")
    assert card["counts"]["infra"] == 1
    blocked = [r for r in card["items"] if r["failure_class"] == "BLOCKED"]
    assert len(blocked) == 1 and blocked[0]["infra_reruns"] == 2


def test_unit_rows_order_times_and_closed_receipts(t2_scenario, tmp_path):
    s = t2_scenario
    assert s.invoke() == 0
    queue = units.make_units(s.ctx, [units.Arm.from_context(s.ctx, "system")], tmp_path / "scratch", s.out)
    rows = read(s.out, "units.json")["units"]
    for index, (unit, row0) in enumerate(zip(queue, rows, strict=True)):
        assert row0["predicted_s"] == units.predicted_seconds(unit)
        assert row0["card_index"] == index
        assert all(type(row0[k]) is int and row0[k] >= 0 for k in ("pre_probe_ms", "keep_ms"))
        if unit.arm.role == "no_memory":
            assert row0["keep_ms"] == row0["pre_probe_ms"] == 0
    for name in ("receipt.json", "receipts/system.json", "receipts/no_memory.json"):
        assert all(set(r) == {"life", "branch", "arm", "slot", "start_ms", "end_ms", "attempts"}
                   for r in read(s.out, name)["units"])


def test_keep_ms_includes_keep_lock_wait(t2_scenario, monkeypatch):
    wait = .02
    hook = t2.keep_hook

    def prepared(*args):
        t2._write(args[1]["system"] / "kept", "index.json", [])
        return hook(*args)

    class SlowLock:
        def __init__(self):
            self.lock = Lock()

        def __enter__(self):
            time.sleep(wait)
            self.lock.acquire()

        def __exit__(self, *args):
            self.lock.release()

    monkeypatch.setattr(units, "Lock", SlowLock)
    monkeypatch.setattr(t2, "keep_hook", prepared)
    monkeypatch.setattr(t2, "keep_failed", lambda *a, **kw: None)
    assert t2_scenario.invoke() == 0
    assert all(r["keep_ms"] >= wait * 1000 for r in read(t2_scenario.out, "units.json")["units"]
               if r["arm"] == "system")


def test_pre_probe_ms_sums_attempts(t2_scenario, monkeypatch):
    s, drive = t2_scenario, units.run_life

    def life(**kw):
        run = drive(**kw)
        retry = kw["arm"] == "system" and kw["life_dir"].name == s.ctx.packs[1].life and kw["branch"] == "B0"
        if retry:
            assert len(run.pre_probe) == 2
        pre = {iid: replace(record, copy_ns=1_600_000 if kw["attempt"] == 0 else 2_100_000)
               for iid, record in (run.pre_probe or {}).items()} if run.pre_probe is not None else None
        return replace(run, pre_probe=pre, classes={i["item_id"]: ("INFRA_FAILURE", "synthetic")
                       for i in kw["items"]} if retry and kw["attempt"] == 0 else run.classes)

    monkeypatch.setattr(units, "run_life", life)
    assert s.invoke() == 0
    rows = read(s.out, "units.json")["units"]
    row0, = [r for r in rows
             if (r["arm"], r["life"], r["branch"]) == ("system", s.ctx.packs[1].life, "B0")]
    assert row0["attempts"] == 2 and row0["pre_probe_ms"] == 7
    assert all(r["pre_probe_ms"] == 0 for r in rows if r["arm"] == "no_memory")


@pytest.mark.parametrize("identity", ["unobserved", "unidentified", "different"])
def test_floor_identity_disclosure(t2_scenario, tmp_path, identity):
    s, cache = t2_scenario, tmp_path / "cache"
    assert s.invoke("first", cache=cache) == 0
    s.stack_options = ({"responses": {"identity_check": {"observe": False}}} if identity == "unobserved"
                       else {"identity": identity})
    s.executed.clear()
    assert s.invoke(cache=cache) == 0
    assert len([k for k in s.executed if k[0] == "no_memory"]) == 4
    reason = "served identity differs" if identity == "different" else "served identity not confirmed"
    assert all(r == dict(cached=False, reason=reason) for r in read(s.out, "disclosures.json")["floor"].values())
