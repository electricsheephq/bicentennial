"""Offline runner boundaries and the real T1 fake-worker acceptance."""

import fcntl
import json
import runpy
import socket
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.director.responder import Call, Reply
from bicentennial.items.protocol import CANARY
from bicentennial.probe.scripted_reader import UNKNOWN
from bicentennial.report.t2lite_card import validate_t2lite_card
from bicentennial.runner import t2lite as runner
from bicentennial.runner.hermes_score import Infra
from bicentennial.runner.life import LifeRun
from bicentennial.runner.probe_live import LiveCredentialStop


def row(iid, score=1000):
    return dict(item_id=iid, cell_id="RECALL-VAL", stage="remember", track="Recall",
        base_verdict=None, benign_extra=False, failure_class=None, infra_reruns=0,
        score_milli=score, worst_case_milli=score, accuracy_correct=None, tuesday_class=None,
        envelope=UNKNOWN, selected_option=None, competing_present=[], carry_over=False,
        stage_attribution=None if score == 1000 else "used")


class Stack:
    upstreams = {runner.MODEL: SimpleNamespace(effort=runner.EFFORT)}
    wire = "responses"

    def __init__(self):
        self.closed, self.drained, self.calls, self.values = False, False, [], {}
        self.identity = "synthetic-identity"
        self.inner = SimpleNamespace(login=SimpleNamespace(needles=lambda: {}, drain=self.drain))

    def drain(self):
        assert self.closed
        self.drained = True

    def close(self):
        assert not self.closed
        self.closed = True

    def state(self):
        return self.values.copy()

    def served_identities(self):
        return {runner.MODEL: self.identity}

    def respond(self, call):
        assert not self.closed
        self.calls.append(call)
        return Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode())


@pytest.fixture(autouse=True)
def live_settings(monkeypatch):
    for name, value in zip(runner.LIVE_ENV, ("https://synthetic.invalid/token", "synthetic-client",
                                              "https://synthetic.invalid/v1"), strict=True):
        monkeypatch.setenv(name, value)


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    home = tmp_path / "login"
    home.mkdir()
    (home / "auth.json").write_bytes(canon({"tokens": {
        "access_token": "synthetic-access-token", "refresh_token": "synthetic-refresh-token"}}))
    packs = []
    for life in ("t1-g1", "t1-g2"):
        items = {b: [dict(row(life + b), probe_point=2)] for b in ("B0", "B1")}
        records = {i["item_id"]: dict(item_id=i["item_id"], template_id="synthetic", template_version=1)
                   for branch in items.values() for i in branch}
        packs.append(runner.t1._Pack(rel=life, dir=tmp_path, manifest={}, schedule=None,
            life=life, items=items, records=records, genre="G1",
            records_b={b: [records[i["item_id"]] for i in items[b]] for b in items},
            keys={iid: {} for iid in records}, cases={i["item_id"]: SimpleNamespace(item=i)
                for branch in items.values() for i in branch}, scoring={"evidence": {}},
            pack={"bundles": []}, life_dir=tmp_path, visible={}, meta={"honeypot_token": "synthetic-honey"}))
    ctx = SimpleNamespace(entry={"name": "hermes-native"}, pack_hash="a" * 64,
        pins={k: "b" * (64 if k in ("harness_hash", "seed_hash") else 40)
              for k in (*runner.PIN_FIELDS, "seed_hash")}, packs=packs, run_id="synthetic",
        harness_pin={}, hermes=None, plugin_source=None, worker_argv=None, model_cache=None,
        gate=None, current_lock=None)
    state = SimpleNamespace(ctx=ctx, stacks=[], seen=[], mode=None, score=1000, home=home)
    def build(*args, **kw):
        stack = Stack()
        if state.mode == "identity":
            stack.identity = "changed-identity"
            stack.values["identity_drift"] = {"served": stack.identity}
        state.stacks.append(stack)
        return stack
    def life(**kw):
        live = kw["live"]
        assert not live.closed
        state.seen.append((kw["arm"], kw["attempt"]))
        call = Call("probe_main", "", "chat", {"messages": [{"role": "user", "content":
            CANARY if state.mode == "canary" else "synthetic prompt"}]}, runner.MODEL,
            {"session": 21, "turn": 1}, "synthetic")
        live.respond(call)
        if state.mode == "credential":
            raise LiveCredentialStop("upstream_401")
        if state.mode == "spend":
            live.stack.values["spend_stopped"] = True
        root = kw["scratch"] / kw["branch"]
        root.mkdir(parents=True)
        probes = [dict(item_id=i["item_id"], checkpoint=i["probe_point"], probe_session=21,
            stage="remember", shadow=dict(selected_option=None, in_context=True,
                in_context_initial=True, carry_over=False, stage_attribution="used", shadow_error=None),
            envelope=dict(parsed=UNKNOWN, value_match=True, value_match_normalised=True, citation_match=None),
            live=dict(served_by="live", served="responder_live", identity_flag=state.mode == "identity"))
            for i in kw["items"]]
        runner._write(root, "t2lite_probes.json", probes)
        rows = ({"role": "probe_main", "served_by": "live"},)
        if state.mode == "live_replay":
            rows = ({"role": "replay_main", "served_by": "live"},)
        if state.mode == "token":
            runner._write(tmp_path / "out", "planted.json", "synthetic-access-token")
        if state.mode == "authbytes":
            target = tmp_path / "out/planted.bin"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((home / "auth.json").read_bytes())
        return LifeRun(kw["arm"], kw["life_dir"].name, kw["branch"], kw["attempt"], _root=root,
            egress={"non_loopback": ["203.0.113.1:443"] if state.mode == "socket" else []},
            audit={"status": "INFRA_FAILURE" if state.mode == "audit" else "OK", "failures": []},
            classes={i["item_id"]: ("INFRA_FAILURE", "responder_live_unavailable") for i in kw["items"]}
                if state.mode in (429, 503) else {}, records=rows,
            timings={"pin_check_ms": 1, "sessions": []}, tokens_by_role={"probe_main": (2, 1)})
    def score(item, **kw):
        return Infra("synthetic") if kw["cls"] == "INFRA_FAILURE" else row(item["item_id"], state.score)
    monkeypatch.setattr(runner.t1, "prepare", lambda **kw: ctx)
    monkeypatch.setattr(runner.t1, "_crosses", lambda *args: False)
    monkeypatch.setattr(runner, "build_live_stack", build)
    monkeypatch.setattr(runner, "run_life", life)
    monkeypatch.setattr(runner, "score_item", score)
    monkeypatch.setattr(runner.fixedroot, "PARENT", str(tmp_path))
    state.invoke = lambda name="out", **kw: runner.run_t2lite(**dict(system="hermes-native", packs_dir=tmp_path / "packs",
        pack_hash=ctx.pack_hash, out=tmp_path / name, login_home=home, max_sends=20) | kw)
    state.out = tmp_path / "out"
    return state


def test_complete_cache_and_actual_work_receipt(scenario, tmp_path, capsys):
    s = scenario
    assert s.invoke(cache=tmp_path / "cache") == 0
    card = runner._read(s.out, "card.json")
    validate_t2lite_card(card)
    validate("receipt", runner._read(s.out, "receipt.json"))
    receipt = runner._read(s.out, "receipt.json")
    assert {t["arm"] for t in receipt["timings"]} == {"system", "no_memory"}
    assert receipt["tokens"] == {"input": 16, "output": 8}
    assert card["counts"] == {"floor_cached": 0, "null_citation": 4}
    assert len(s.seen) == 8 and s.stacks[0].closed and s.stacks[0].drained
    assert s.invoke("second", cache=tmp_path / "cache") == 0
    assert runner._read(tmp_path / "second", "card.json")["counts"]["floor_cached"] == 1
    cached_receipt = runner._read(tmp_path / "second", "receipt.json")
    assert {t["arm"] for t in cached_receipt["timings"]} == {"system"}
    assert cached_receipt["tokens"] == {"input": 8, "output": 4}
    assert len(s.seen) == 12
    assert "floor: reused from the cache" in capsys.readouterr().err
    assert all(p.read_bytes() == canon(json.loads(p.read_bytes())) for p in s.out.rglob("*.json"))


@pytest.mark.parametrize("changed", ["contract", "harness"])
def test_floor_key_mismatch_runs_live(scenario, tmp_path, monkeypatch, changed):
    assert scenario.invoke(cache=tmp_path / "cache") == 0
    if changed == "contract":
        monkeypatch.setattr(runner.answer_contract, "contract_hash", lambda: "c" * 64)
    else:
        scenario.ctx.pins["harness_hash"] = "c" * 64
    assert scenario.invoke("changed", cache=tmp_path / "cache") == 0
    assert runner._read(tmp_path / "changed", "card.json")["counts"]["floor_cached"] == 0
    assert len(scenario.seen) == 16


@pytest.mark.parametrize("mode,code", [("credential", "credential_stop"), ("spend", "spend_stop"),
    ("canary", "canary"), ("token", "credential_scan"), ("authbytes", "credential_scan"),
    ("socket", "isolation"), ("live_replay", "isolation")])
def test_stops_and_invalid_cleanup(scenario, mode, code):
    scenario.mode = mode
    assert scenario.invoke() == 3
    assert runner._read(scenario.out, "refusal.json") == {"code": code}
    infra = code in ("credential_stop", "spend_stop")
    assert sorted(p.name for p in scenario.out.iterdir()) == (["receipt.json", "refusal.json"] if infra else ["refusal.json"])
    if infra:
        assert runner._read(scenario.out, "receipt.json")["run_status"] == "INFRA_FAILURE"
    assert scenario.stacks[0].closed and scenario.stacks[0].drained
    if mode == "canary":
        assert not scenario.stacks[0].calls
    assert all(b"synthetic-access-token" not in p.read_bytes() for p in scenario.out.iterdir())


@pytest.mark.parametrize("mode", [429, 503, "audit"])
def test_infra_reruns_use_scorer_class_and_null_attribution(scenario, mode):
    scenario.mode = mode
    assert scenario.invoke() == 0
    card = runner._read(scenario.out, "card.json")
    assert {r["failure_class"] for r in card["items"]} == {"BLOCKED"}
    assert len(scenario.seen) == 24
    assert all(r["failure_class"] == "BLOCKED" for r in runner._read(scenario.out, "outcomes.json").values())
    assert all(r["shadow"]["stage_attribution"] is None for p in scenario.out.rglob("t2lite_probes.json")
               for r in json.loads(p.read_bytes()))


def test_operator_and_account_lock_precede_stack(scenario):
    s = scenario
    (s.home / ".bicentennial-operator").touch()
    assert runner.run_t2lite(system="lcm-x", packs_dir="unused", pack_hash="a" * 64,
        out=s.out, login_home=s.home, max_sends=1) == 3
    assert runner._read(s.out, "refusal.json")["code"] == "operator_identity"
    with (s.home / ".t2lite.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert s.invoke("busy") == 3
        assert runner._read(s.out.parent / "busy", "refusal.json")["code"] == "account_busy"
    assert s.stacks == []


def test_out_exists_preserves_files(scenario):
    scenario.out.mkdir()
    (scenario.out / "keep").write_text("sentinel")
    assert scenario.invoke() == 3
    assert list(scenario.out.iterdir()) == [scenario.out / "keep"]
    assert scenario.stacks == []


def test_sandbox_overlap_precedes_stack(scenario, tmp_path):
    assert scenario.invoke(cache=tmp_path / "bicentennial-0/cache") == 3
    assert scenario.stacks == []


def test_real_stack_max_sends_exhaustion(scenario, monkeypatch):
    from bicentennial.director.upstream import forward
    from bicentennial.runner.live import build_live_stack
    helpers = runpy.run_path(str(Path(__file__).with_name("test_live_stack.py")))
    helpers["home"].__wrapped__(scenario.home)
    stacks = []
    def build(*args, **kwargs):
        stack = build_live_stack(*args, **(kwargs | {"max_sends": 0}))
        stacks.append(stack)
        return stack
    # A zero-send cap refuses before token admission or any HTTP call.
    monkeypatch.setattr(runner, "build_live_stack", build)
    monkeypatch.setattr(forward, "send", lambda *args: pytest.fail("zero cap reached transport"))
    assert scenario.invoke() == 3
    assert runner._read(scenario.out, "refusal.json")["code"] == "spend_stop"
    assert stacks[0].closed and stacks[0].inner.login.drain() == []


@pytest.mark.parametrize("field", ["tier", "system", "model", "effort", "pack_hash", "seed_hash", "profile",
    "answer_contract_sha256", *["pins." + k for k in runner.PIN_FIELDS]])
def test_baseline_checked_before_build_or_send(scenario, tmp_path, field):
    card = runner._card(scenario.ctx, [])
    target = card
    parts = field.split(".")
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = "T1" if field == "tier" else "f" * (40 if field.startswith("pins.") and field != "pins.harness_hash" else 64)
    runner._write(tmp_path / "baseline", "card.json", card)
    runner._write(tmp_path / "baseline", "outcomes.json", {})
    assert scenario.invoke(baseline=tmp_path / "baseline") == 3
    assert scenario.stacks == [] and scenario.seen == []
    assert runner._read(scenario.out, "refusal.json") == {"code": "invalid_card:baseline" if field == "tier" else field}


def test_flip_identities_and_prime_card(scenario, tmp_path):
    s = scenario
    assert s.invoke("baseline") == 0
    assert s.invoke("prime", aa_of=tmp_path / "baseline") == 0
    assert runner._read(tmp_path / "prime", "card.json")["aa_prime"] is True
    s.score, s.mode = 0, "identity"
    assert s.invoke(baseline=tmp_path / "baseline", aa_prime=tmp_path / "prime") == 0
    assert runner._read(s.out, "card.json")["aa_prime"] is False
    report = runner._read(s.out, "flips.json")
    assert len(report["rows"]) == 4
    assert report["served_identity"]["changed"] is True
    assert "synthetic-identity" in report["served_identity"]["baseline"]
    assert "changed-identity" in report["served_identity"]["current"]
    assert report["q0"]["numerator"] == 0


def test_guard_delegates_stack_and_never_forwards_canary():
    stack = Stack()
    guard = runner._Guard(stack)
    assert guard.upstreams is stack.upstreams and guard.wire == stack.wire
    assert guard.state() == {} and guard.served_identities() == stack.served_identities()
    call = Call("probe_main", "", "chat", {"messages": [{"content": CANARY}]}, runner.MODEL, {}, "fake")
    assert guard.respond(call).status == 503
    assert guard.respond(replace(call, body={})).status == 503
    assert stack.calls == []


def test_publication_waits_for_scan_and_discloses_transforms(scenario, monkeypatch):
    scan, drive = runner._scan, runner.run_life
    checked = []
    def verify(out, needles):
        assert not (out / "card.json").exists() and not (out / "receipt.json").exists()
        checked.append(out)
        return scan(out, needles)
    def transformed(**kw):
        return replace(drive(**kw), transforms=("synthetic-transformed-item",))
    monkeypatch.setattr(runner, "_scan", verify)
    monkeypatch.setattr(runner, "run_life", transformed)
    assert scenario.invoke() == 0 and checked == [scenario.out]
    assert runner._read(scenario.out, "disclosures.json")["t1.transforms"] == ["synthetic-transformed-item"]


def test_planted_flip_rerun_command_repeats_checkpoint(scenario, tmp_path, monkeypatch):
    import shlex

    from bicentennial import cli
    s = scenario
    assert s.invoke("baseline", cache=tmp_path / "cache") == 0
    s.score = 0
    assert s.invoke(baseline=tmp_path / "baseline", cache=tmp_path / "cache") == 0
    flip = runner._read(s.out, "flips.json")["rows"][0]
    command = flip["rerun"]
    for old, new in (("<packs>", str(tmp_path / "packs")), ("<hermes checkout>", "unused"),
                     ("<new dir>", str(tmp_path / "rerun"))):
        command = command.replace(old, new)
    argv = shlex.split(command)[2:] + ["--login-home", str(s.home), "--max-sends", "30", "--cache", str(tmp_path / "cache")]
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(cli, "reexec_niced", lambda *args: None)
    assert cli.main(argv) == 0
    repetitions = runner._read(tmp_path / "rerun", "repetitions.json")
    assert len(repetitions) == 3
    assert all(set(rep) == {flip["item_id"]} and rep[flip["item_id"]]["score_milli"] == 0 for rep in repetitions)


@pytest.mark.parametrize("kw", [dict(only=("t1-g1", "B0", 2), baseline="baseline"), dict(only=("t1-g1", "B0", 2), aa_of="b"),
    dict(aa_prime="prime"), dict(baseline="baseline", aa_of="baseline", aa_prime="prime"), dict(repeat=2),
    dict(only=("t1-g1", "B0", 2), repeat=0), dict(max_sends=-1)])
def test_argument_refusals_create_nothing(scenario, tmp_path, capsys, kw):
    kw = {k: tmp_path / v if isinstance(v, str) else v for k, v in kw.items()}
    assert scenario.invoke(**kw) == 3 and not scenario.out.exists()
    assert capsys.readouterr().err.split() == ["rerun_arguments"] and scenario.stacks == []


def test_live_settings_and_login_home_refuse_first(scenario, monkeypatch, capsys):
    monkeypatch.delenv(runner.LIVE_ENV[1])
    assert scenario.invoke() == 3 and not scenario.out.exists()
    assert capsys.readouterr().err.split() == [runner.LIVE_ENV[1], "live_config"]
    monkeypatch.setenv(runner.LIVE_ENV[1], "synthetic-client")
    (scenario.home / "auth.json").unlink()
    assert scenario.invoke() == 3 and not scenario.out.exists()
    assert capsys.readouterr().err.split() == ["login_home"] and scenario.stacks == []


@pytest.mark.parametrize("damage", ["items", "outcome", "prime_flag"])
def test_baseline_files_checked_before_any_send(scenario, tmp_path, damage):
    s = scenario
    assert s.invoke("baseline") == 0 and s.invoke("prime", aa_of=tmp_path / "baseline") == 0
    card, outcomes = runner._read(tmp_path / "baseline", "card.json"), runner._read(tmp_path / "baseline", "outcomes.json")
    if damage == "items":
        dropped = card["items"].pop()["item_id"]
        outcomes.pop(dropped)
        runner._write(tmp_path / "baseline", "card.json", card)
    elif damage == "outcome":
        next(iter(outcomes.values()))["score_milli"] = 7
    runner._write(tmp_path / "baseline", "outcomes.json", outcomes)
    prime = tmp_path / ("baseline" if damage == "prime_flag" else "prime")
    s.stacks.clear(), s.seen.clear()
    assert s.invoke(baseline=tmp_path / "baseline", aa_prime=prime) == 3
    assert s.stacks == [] and s.seen == []
    expected = {"items": "baseline_items", "outcome": "items:baseline", "prime_flag": "aa_prime:flag"}[damage]
    assert runner._read(s.out, "refusal.json") == {"code": expected}


def test_rerun_replays_the_branch_and_keeps_the_checkpoint(scenario, monkeypatch):
    s = scenario
    pack = s.ctx.packs[0]
    extra = dict(row("t1-g1B0-later"), probe_point=3)
    pack.items["B0"].append(extra)
    pack.records[extra["item_id"]] = dict(item_id=extra["item_id"], template_id="synthetic", template_version=1)
    pack.records_b["B0"].append(pack.records[extra["item_id"]])
    pack.keys[extra["item_id"]] = {}
    pack.cases[extra["item_id"]] = SimpleNamespace(item=extra)
    drive, ran = runner.run_life, []
    def capture(**kw):
        ran.append((kw["arm"], sorted(i["item_id"] for i in kw["items"])))
        return drive(**kw)
    monkeypatch.setattr(runner, "run_life", capture)
    assert s.invoke(only=("t1-g1", "B0", 2), repeat=2) == 0
    # Each repetition replays the whole branch, so both items run; only the checkpoint's are kept.
    assert [ids for arm, ids in ran if arm == "system"] == [["t1-g1B0", "t1-g1B0-later"]] * 2
    assert {i["item_id"] for i in runner._read(s.out, "card.json")["items"]} == {"t1-g1B0"}
    repetitions = runner._read(s.out, "repetitions.json")
    assert [set(rep) for rep in repetitions] == [{"t1-g1B0"}] * 2
    assert s.invoke("missing", only=("t1-g1", "B0", 9), repeat=2) == 3
    assert runner._read(s.out.parent / "missing", "refusal.json") == {"code": "only"}


SHARED = runpy.run_path(str(Path(__file__).with_name("test_t1.py")))
PROBE = runpy.run_path(str(Path(__file__).with_name("test_probe_live.py")))
installed = SHARED["installed"]


@pytest.fixture
def loopback_allowed():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("sandbox cannot bind sockets; owner must run full T2-lite fake-worker acceptance")


def test_full_fake_worker_and_rerun_store_hashes(loopback_allowed, installed, tmp_path, monkeypatch):
    """Real preparation, L2 director, shadow, scorer, receipt, cards and checkpoint replay."""
    import sys
    from contextlib import closing

    from bicentennial.contracts.items import reader_view
    from bicentennial.director.compiler.hermes import compile_script, step_call
    from bicentennial.director.scripted import ScriptedResponder
    from bicentennial.probe.probe_responder import ProbeResponder
    from bicentennial.runner import life
    from bicentennial.sandbox.surfaces import surface_hash
    from bicentennial.systems.registry import REGISTRY, load
    from bicentennial.world.db import open_world

    SHARED["environment"].__wrapped__(monkeypatch)
    monkeypatch.setattr(runner.fixedroot, "PARENT", str(tmp_path))
    home = tmp_path / "login"
    home.mkdir()
    (home / "auth.json").write_bytes(canon({"tokens": {"access_token": "synthetic-token"}}))
    stacks, observations, snapshots = [], [], {}
    def build(*args, **kwargs):
        stack = Stack()
        stack.oracle = None
        def respond(call):
            Stack.respond(stack, call)
            return stack.oracle.respond(call)
        stack.respond = respond
        stacks.append(stack)
        return stack
    def drive(**kw):
        meta = runner._read(kw["life_dir"], "life.json")
        with closing(open_world(kw["life_dir"] / f"world.{kw['branch']}.db", readonly=True)) as db:
            schedule = life.build_schedule(meta["seed"], meta["life"], life.named(meta["scale"]))
            compiled = compile_script(kw["life_dir"], kw["branch"], schedule, db,
                items=kw["items"], step_s=life.STEP_S, answer_contract=runner.answer_contract)
            plain = compile_script(kw["life_dir"], kw["branch"], schedule, db,
                items=kw["items"], step_s=life.STEP_S)
        timeline = tmp_path / f"timeline-{len(observations)}.json"
        runner._write(timeline.parent, timeline.name, {t["user"]: [s["index"], t["n"], s["kind"]]
            for s in compiled.script["sessions"] for t in s["turns"]})
        kw["worker_argv"] = [sys.executable, str(Path(__file__).with_name("fake_life_worker.py")), "--timeline", str(timeline)]
        case = dict(items=kw["items"], keys=kw["keys"], compiled=compiled)
        oracle = PROBE["Oracle"](case, kw["scratch"])
        if kw["arm"] == "no_memory":
            # The floor reads as no-memory, which offers no recall tool (run_life's reader rule).
            reader = load(REGISTRY / "no-memory.toml")
            oracle.scripted = ProbeResponder(ScriptedResponder(reader), reader,
                {iid: (p.index, n) for p in compiled.probes for n, iid in enumerate(p.item_ids, 1)},
                {i["item_id"]: (reader_view(i), kw["keys"][i["item_id"]]) for i in kw["items"]},
                earlier=None, step_call=step_call)
        oracle.scripted.earlier = lambda key, session, before=None: life._earlier(
            kw["scratch"] / kw["branch"] / "run/ledger", session, before)
        stacks[-1].oracle = oracle
        result = life.run_life(**kw)
        assert result.audit["status"] == "OK" and not result.classes
        assert all(c.role == "probe_main" for c in oracle.calls)
        assert all(result.envelopes[i["item_id"]] is not None for i in kw["items"] if i["stage"] != "act")
        if kw["arm"] == "system":
            stores = {p.checkpoint: surface_hash(result.retained_roots[p.item_ids[0]][0] / "memories", [])
                      for p in compiled.probes}
            key = result.life, result.branch
            if key in snapshots:
                assert stores.items() <= snapshots[key].items()
            else:
                # A separately executed T1 life uses the full scripted timeline.
                baseline_kw = dict(kw, live=None, scratch=tmp_path / "t1" / result.life / result.branch)
                baseline_timeline = tmp_path / f"baseline-{result.life}-{result.branch}.json"
                runner._write(baseline_timeline.parent, baseline_timeline.name, {t["user"]: [s["index"], t["n"], s["kind"]]
                    for s in plain.script["sessions"] for t in s["turns"]})
                baseline_kw["worker_argv"] = [sys.executable, str(Path(__file__).with_name("fake_life_worker.py")),
                    "--timeline", str(baseline_timeline)]
                baseline = life.run_life(**baseline_kw)
                expected = {p.checkpoint: surface_hash(baseline.retained_roots[p.item_ids[0]][0] / "memories", [])
                            for p in compiled.probes}
                assert stores == expected
                baseline.cleanup()
                snapshots[key] = stores
        observations.append(result)
        return result
    monkeypatch.setattr(runner, "build_live_stack", build)
    monkeypatch.setattr(runner, "run_life", drive)
    args = dict(system="hermes-native", packs_dir=installed.root, pack_hash=installed.digest,
        login_home=home, max_sends=10000, entry=SHARED["measured"](), worker_argv=installed.worker,
        cache=tmp_path / "cache")
    assert runner.run_t2lite(out=tmp_path / "full", **args) == 0
    card = runner._read(tmp_path / "full", "card.json")
    validate_t2lite_card(card)
    assert all(i["failure_class"] != "BLOCKED" for i in card["items"])
    outcome = next(r for r in runner._read(tmp_path / "full", "outcomes.json").values() if r["stage"] != "act")
    only = outcome["life"], outcome["branch"], outcome["probe_point"]
    assert runner.run_t2lite(out=tmp_path / "rerun", only=only, repeat=3, **args) == 0
    repetitions = runner._read(tmp_path / "rerun", "repetitions.json")
    assert len(repetitions) == 3 and all(outcome["item_id"] in rep for rep in repetitions)
    assert all(s.closed and s.drained for s in stacks)
