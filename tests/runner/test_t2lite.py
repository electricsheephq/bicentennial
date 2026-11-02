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
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.items.protocol import CANARY
from bicentennial.probe.scripted_reader import UNKNOWN, ReaderResult
from bicentennial.report.t2lite_card import validate_t2lite_card
from bicentennial.runner import t2lite as runner
from bicentennial.runner.hermes_score import Infra
from bicentennial.runner.life import LifeRun
from bicentennial.runner.probe_live import LiveCredentialStop

ANSWER = dict(type="entity", value="synthetic", confidence_milli=900, citation=None)
SHADOW_ANSWER = dict(type="entity", value="shadow-only", confidence_milli=800, citation=None)


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
        return [{"type": "holder"}]

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


def hold_rows():
    def held(reason, ms):
        return dict(kind="hold", reason=reason, held_ms=ms)
    def ledger(diagnostics):
        return dict(role="probe_main", served_by="live", upstream=[
            dict(role="probe_main", served_by="live", diagnostics=diagnostics)])
    return (ledger([held("quota", 11), held("rate", 11), dict(kind="try"),
                    held("rate", 11), dict(kind="try")]),
            ledger([held("quota", 7), dict(kind="try")]))


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
        packs.append(runner.t1._Pack(rel=life, dir=tmp_path, manifest={}, schedule=SimpleNamespace(
            scale=SimpleNamespace(swap=15)),
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
        if state.mode == "gate":
            raise GateRefused("machine guard refused")
        call = Call("probe_main", "", "chat", {"messages": [{"role": "user", "content":
            CANARY if state.mode in ("canary", "canary_credential") else "synthetic prompt"}]}, runner.MODEL,
            {"session": 21, "turn": 1}, "synthetic")
        live.respond(call)
        if state.mode in ("credential", "canary_credential"):
            raise LiveCredentialStop("upstream_401")
        if state.mode == "spend":
            live.stack.values["spend_stopped"] = True
        root = kw["scratch"] / kw["branch"]
        root.mkdir(parents=True)
        probes = [dict(item_id=i["item_id"], checkpoint=i["probe_point"], probe_session=21,
            stage="remember", shadow=dict(selected_option="opt-a" if state.mode == "competing" else None, in_context=True,
                in_context_initial=True, carry_over=False, stage_attribution="used", shadow_error=None),
            envelope=dict(parsed=UNKNOWN, value_match=True, value_match_normalised=True, citation_match=None),
            live=dict(served_by="live", served="responder_live", identity_flag=state.mode == "identity"))
            for i in kw["items"]]
        runner._write(root, "t2lite_probes.json", probes)
        rows = ({"role": "probe_main", "served_by": "live"},)
        if state.mode == "holds" and kw["items"][0]["item_id"] == "t1-g1B0":
            rows = (hold_rows()[0 if kw["arm"] == "no_memory" else 1],)
        if state.mode == "live_replay":
            rows = ({"role": "replay_main", "served_by": "live"},)
        if state.mode == "live_upstream":
            rows = ({"role": "probe_main", "upstream": [{"role": "replay_main", "served_by": "live"}]},)
        if state.mode == "live_upstream_mixed":
            rows = ({"role": "probe_main", "upstream": [{"role": "probe_main", "served_by": "live"},
                                                        {"role": "replay_main", "served_by": "live"}]},)
        # The shadow saw two options and the live model said unknown, or it saw none and the model answered. The
        # shadow's own envelope differs from the live one in both modes, so a scorer handed the wrong one is caught.
        shadow = {"competing": ("opt-a", ("opt-b",), SHADOW_ANSWER), "asserted": (None, (), UNKNOWN)}.get(state.mode)
        results = {i["item_id"]: ReaderResult(item_id=i["item_id"], mode="hermes", kind="qa",
            selected_option=shadow[0], envelope=shadow[2], plan=None, competing_present=shadow[1], carry_over=False,
            in_context=True, missing_required=0, competing={}, forbidden_in_context=None, recall=None)
            for i in kw["items"]} if shadow else {}
        envelopes = {i["item_id"]: ANSWER if state.mode == "asserted" else UNKNOWN for i in kw["items"]} if shadow else {}
        if state.mode == "token":
            runner._write(tmp_path / "out", "planted.json", "synthetic-access-token")
        if state.mode == "authbytes":
            target = tmp_path / "out/planted.bin"
            target.parent.mkdir(exist_ok=True)
            target.write_bytes((home / "auth.json").read_bytes())
        return LifeRun(kw["arm"], kw["life_dir"].name, kw["branch"], kw["attempt"], _root=root,
            egress={"non_loopback": ["203.0.113.1:443"] if state.mode == "socket" else []},
            audit={"status": "INFRA_FAILURE", "failures": ["A5.missing_scripts"]} if state.mode == "audit"
                else {"status": "OK", "failures": []}, results=results, envelopes=envelopes,
            classes={i["item_id"]: ("INFRA_FAILURE", "responder_live_unavailable") for i in kw["items"]}
                if state.mode in (429, 503) else {i["item_id"]: ("SYSTEM_FAILURE", "final_mismatch"
                if i["item_id"] == "t1-g2B1" else "turn_timeout") for i in kw["items"]}
                if state.mode in ("relabel", "relabel_alone", "relabel_elsewhere") else {}, records=rows,
            stopped=("SYSTEM_FAILURE", "turn_timeout", 5) if state.mode == "relabel" or state.mode in (
                "relabel_alone", "relabel_elsewhere") and kw["arm"] == "system" else
                ("SYSTEM_FAILURE", "turn_timeout", 4) if state.mode == "relabel_elsewhere" else None,
            timings={"pin_check_ms": 1, "sessions": []}, tokens_by_role={"probe_main": (2, 1)})
    def score(item, **kw):
        if kw["cls"] == "INFRA_FAILURE":
            return Infra("synthetic")
        scored = row(item["item_id"], state.score)
        if state.mode in ("competing", "asserted"):
            # The real scorer's Ring 0 checks, applied as hermes_score applies them to the reader result.
            assert kw["envelope"] == (ANSWER if state.mode == "asserted" else UNKNOWN)  # the live answer, not the shadow's
            validate("item_outcome", dict(scored, envelope=kw["envelope"], selected_option=kw["result"].selected_option,
                competing_present=list(kw["result"].competing_present)))
        return scored
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
    assert card["counts"] == {"floor_cached": 0, "null_citation": 0}
    assert card["answer_contract_sha256"] == runner.answer_contract.contract_hash()
    assert runner._read(s.out, "custody.json") == [{"type": "holder"}]
    assert len(s.seen) == 8 and s.stacks[0].closed and s.stacks[0].drained
    assert s.invoke("second", cache=tmp_path / "cache") == 0
    assert runner._read(tmp_path / "second", "card.json")["counts"]["floor_cached"] == 1
    cached_receipt = runner._read(tmp_path / "second", "receipt.json")
    assert {t["arm"] for t in cached_receipt["timings"]} == {"system"}
    assert cached_receipt["tokens"] == {"input": 8, "output": 4}
    assert len(s.seen) == 12
    assert "floor: reused from the cache" in capsys.readouterr().err
    assert all(p.read_bytes() == canon(json.loads(p.read_bytes())) for p in s.out.rglob("*.json"))


@pytest.mark.parametrize("held", [False, True])
def test_holds_count_waits_on_rows(held):
    rows = hold_rows() if held else ({}, {"upstream": [{"served_by": "live", "diagnostics": []}]})
    assert runner._holds(rows) == (dict(waits=3, held_ms=29, reasons=["quota", "rate"]) if held
                                   else dict(waits=0, held_ms=0, reasons=[]))


def test_holds_count_terminal_wait_and_ignore_scripted():
    row = hold_rows()[0]
    row["upstream"][0]["diagnostics"] = row["upstream"][0]["diagnostics"][:2]
    assert runner._holds([row]) == dict(waits=1, held_ms=11, reasons=["quota", "rate"])
    row["upstream"][0]["served_by"] = "scripted"
    assert runner._holds([row]) == dict(waits=0, held_ms=0, reasons=[])


@pytest.mark.parametrize("held", [False, True])
def test_run_discloses_holds_from_both_arms(scenario, held):
    scenario.mode = "holds" if held else None
    assert scenario.invoke() == 0
    assert {arm for arm, _ in scenario.seen} == {"no_memory", "system"}
    assert runner._read(scenario.out, "disclosures.json")["live"]["holds"] == (
        dict(waits=3, held_ms=29, reasons=["quota", "rate"]) if held
        else dict(waits=0, held_ms=0, reasons=[]))


@pytest.fixture
def action_scenario(scenario, monkeypatch):
    s = scenario
    s.mode, s.failure, s.scored = "competing", None, []
    s.ctx.packs[1] = replace(s.ctx.packs[1], genre="G2")
    for pack in s.ctx.packs:
        pack.items["B0"][0]["stage"] = "act"
    pack = s.ctx.packs[1]
    failed = dict(pack.items["B0"][0], item_id="g2-failed")
    pack.items["B0"].append(failed)
    pack.records[failed["item_id"]] = dict(item_id=failed["item_id"], template_id="synthetic", template_version=1)
    pack.cases[failed["item_id"]] = SimpleNamespace(item=failed)
    pack.keys[failed["item_id"]] = {}
    drive, score = runner.run_life, runner.score_item
    def life(**kw):
        run = drive(**kw)
        classes = {i["item_id"]: ("SYSTEM_FAILURE", "final_mismatch")
                   for i in kw["items"] if i["item_id"] == "g2-failed"}
        if s.failure == "peer_infra" and "g2-failed" in classes and kw["attempt"] == 0:
            classes["g2-failed"] = ("INFRA_FAILURE", "synthetic")
        for i in kw["items"]:
            if i["item_id"] == "t1-g2B0" and s.failure in ("system", "infra", "relabel"):
                classes[i["item_id"]] = ("INFRA_FAILURE" if s.failure == "infra" else "SYSTEM_FAILURE", "turn_timeout")
        return replace(run, classes=classes,
            audit={"status": "INFRA_FAILURE" if s.failure == "audit" else "OK"},
            stopped=("SYSTEM_FAILURE", "turn_timeout", 5) if s.failure == "relabel" else None)
    def scoring(item, **kw):
        from bicentennial.runner.hermes_score import score_item
        s.scored.append((item["item_id"], kw["attempt"], kw["cls"]))
        if kw["cls"]:
            return score_item(item, **kw)
        if item["stage"] != "act":
            return score(item, **kw)
        result = dict(row(item["item_id"]), stage="act", envelope=None,
                      base_verdict="PASS", accuracy_correct=True)
        validate("item_outcome", result)
        return result
    monkeypatch.setattr(runner, "run_life", life)
    monkeypatch.setattr(runner, "score_item", scoring)
    return s


def test_g2_actions_publish_unscored_rows_on_both_arms(action_scenario):
    s = action_scenario
    assert s.invoke() == 0
    card = runner._read(s.out, "card.json")
    assert card["not_scored_live"] == ["t1-g2B0"]
    assert "t1-g2B0" not in {iid for iid, _, _ in s.scored}
    outcomes = runner._read(s.out, "outcomes.json")
    floor = runner._read(s.out, "no_memory.json")["outcomes"]
    rows = {r["item_id"]: r for r in card["items"]}
    for target in (rows, outcomes, floor):
        unscored = target["t1-g2B0"]
        assert all(unscored[k] is None for k in ("base_verdict", "score_milli", "worst_case_milli",
            "accuracy_correct", "tuesday_class", "envelope", "failure_class", "stage_attribution"))
        assert unscored["stage"] == "act" and unscored["infra_reruns"] == 0
        assert unscored["benign_extra"] is False and unscored["carry_over"] is False
        assert unscored["selected_option"] == "opt-a" and unscored["competing_present"] == ["opt-b"]
        assert target["t1-g1B0"]["score_milli"] == 1000 and target["t1-g1B0"]["accuracy_correct"] is True
        assert target["t1-g2B1"]["score_milli"] == 1000
        assert target["g2-failed"]["score_milli"] == 0 and target["g2-failed"]["failure_class"] == "SYSTEM_FAILURE"
    assert all(outcomes["t1-g2B0"][k] == v for k, v in rows["t1-g2B0"].items())
    probes = [p for path in s.out.rglob("t2lite_probes.json") for p in json.loads(path.read_bytes())
              if p["item_id"] in ("t1-g2B0", "g2-failed")]
    assert len(probes) == 4 and all(p["shadow"]["stage_attribution"] is None for p in probes)


def test_unscored_action_keeps_the_unit_retry_attempt(action_scenario):
    s = action_scenario
    s.failure = "peer_infra"
    assert s.invoke() == 0
    rows = runner._read(s.out, "outcomes.json")
    floor = runner._read(s.out, "no_memory.json")["outcomes"]
    for target in (rows, floor):
        assert target["t1-g2B0"]["infra_reruns"] == 1
        assert target["t1-g2B0"]["score_milli"] is None
    assert "t1-g2B0" not in {iid for iid, _, _ in s.scored}


@pytest.mark.parametrize("failure,expected", [("system", "SYSTEM_FAILURE"), ("infra", "BLOCKED"),
                                             ("audit", "BLOCKED"), ("relabel", "BLOCKED")])
def test_g2_action_failures_keep_t1_handling(action_scenario, monkeypatch, failure, expected):
    s = action_scenario
    s.failure = failure
    if failure == "relabel":
        monkeypatch.setattr(runner, "is_plugin", lambda name: True)
        monkeypatch.setattr(runner, "resolve_worker_env", lambda *args: None)
    assert s.invoke() == 0
    card = runner._read(s.out, "card.json")
    assert card["not_scored_live"] == []
    rows = {r["item_id"]: r for r in card["items"]}
    floor = runner._read(s.out, "no_memory.json")["outcomes"]
    for target, cls in ((rows, expected), (floor, "SYSTEM_FAILURE" if failure == "relabel" else expected)):
        result = target["t1-g2B0"]
        assert result["failure_class"] == cls
        assert result["score_milli"] == (0 if cls == "SYSTEM_FAILURE" else None)
        assert result["infra_reruns"] == (0 if cls == "SYSTEM_FAILURE" else 2)
    assert any(iid == "t1-g2B0" for iid, _, _ in s.scored)


@pytest.mark.parametrize("changed", ["contract", "harness", "pack", "commit", "damaged", "no_outcome", "no_stop"])
def test_floor_key_mismatch_runs_live(scenario, tmp_path, monkeypatch, changed):
    assert scenario.invoke(cache=tmp_path / "cache") == 0
    entry, = (tmp_path / "cache").iterdir()
    if changed == "contract":
        monkeypatch.setattr(runner.answer_contract, "contract_hash", lambda: "c" * 64)
    elif changed == "harness":
        scenario.ctx.pins["harness_hash"] = "c" * 64
    elif changed == "pack":
        scenario.ctx.pack_hash = "c" * 64
    elif changed == "commit":
        scenario.ctx.pins["benchmark_commit"] = "c" * 40
    elif changed == "damaged":
        entry.write_bytes(b"{")
    else:
        # A whole entry less one floor item, or less one unit's stop: each half of the coverage check must hold.
        cached = json.loads(entry.read_bytes())
        part = cached["outcomes" if changed == "no_outcome" else "stops"]
        part.pop(next(iter(part)))
        entry.write_bytes(canon(cached))
    assert scenario.invoke("changed", cache=tmp_path / "cache") == 0
    assert runner._read(tmp_path / "changed", "card.json")["counts"]["floor_cached"] == 0
    assert len(scenario.seen) == 16
    assert json.loads(entry.read_bytes())["outcomes"]
    assert all(p.name.endswith(".t2lite-floor.json") for p in (tmp_path / "cache").iterdir())


@pytest.mark.parametrize("mode,code", [("credential", "credential_stop"), ("spend", "spend_stop"),
    ("canary", "canary"), ("canary_credential", "canary"), ("token", "credential_scan"),
    ("authbytes", "credential_scan"), ("socket", "isolation"), ("live_replay", "isolation"),
    ("live_upstream", "isolation"), ("live_upstream_mixed", "isolation"), ("gate", "gate_refused")])
def test_stops_and_invalid_cleanup(scenario, mode, code):
    scenario.mode = mode
    assert scenario.invoke() == 3
    assert runner._read(scenario.out, "refusal.json") == {"code": code}
    infra = code in ("credential_stop", "spend_stop")
    assert sorted(p.name for p in scenario.out.iterdir()) == (
        ["custody.json", "receipt.json", "refusal.json"] if infra else ["refusal.json"])
    if infra:
        assert runner._read(scenario.out, "receipt.json")["run_status"] == "INFRA_FAILURE"
        assert runner._read(scenario.out, "custody.json") == [{"type": "holder"}]
    assert scenario.stacks[0].closed and scenario.stacks[0].drained
    if mode in ("canary", "canary_credential"):
        assert not scenario.stacks[0].calls
    if mode == "credential":
        # A credential stop ends the run at once: one life, one send, no retry.
        assert len(scenario.seen) == 1 and len(scenario.stacks[0].calls) == 1
    assert all(b"synthetic-access-token" not in p.read_bytes() for p in scenario.out.iterdir())


@pytest.mark.parametrize("mode", [429, 503, "audit"])
def test_infra_reruns_use_scorer_class_and_null_attribution(scenario, tmp_path, mode):
    scenario.mode = mode
    assert scenario.invoke(cache=tmp_path / "cache") == 0
    # A BLOCKED floor is never cached.
    assert not (tmp_path / "cache").exists() or not any((tmp_path / "cache").iterdir())
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
    assert runner._read(scenario.out, "refusal.json") == {"code": "invalid_card:baseline" if field in ("tier", "profile") else field}


@pytest.mark.parametrize("flipped", [False, True])
@pytest.mark.parametrize("alias", [False, True])
def test_aa_of_own_baseline_uses_final_outcomes(scenario, tmp_path, monkeypatch, flipped, alias):
    s = scenario
    s.ctx.packs[1] = replace(s.ctx.packs[1], genre="G2")
    s.ctx.packs[1].items["B0"][0]["stage"] = "act"
    baseline = tmp_path / "baseline"
    assert s.invoke("baseline") == 0
    reference = tmp_path / "alias" if alias else baseline
    if alias:
        reference.symlink_to(baseline, target_is_directory=True)
    score, report = runner.score_item, runner.flip_report
    calls = []
    def scoring(item, **kw):
        return row(item["item_id"], 0) if flipped and item["item_id"] == "t1-g1B1" else score(item, **kw)
    def reporting(*args, **kw):
        calls.append((args, kw))
        return report(*args, **kw)
    monkeypatch.setattr(runner, "score_item", scoring)
    monkeypatch.setattr(runner, "flip_report", reporting)
    assert s.invoke(aa_of=reference, baseline=baseline) == 0
    result = runner._read(s.out, "flips.json")
    assert result["q0"] == dict(numerator=int(flipped), denominator=3 if flipped else 1,
                                milli=333 if flipped else 0)
    assert result["counts"]["aa_prime_scored"] == result["counts"]["scored"] == 3
    assert result["counts"]["unstable"] == result["counts"]["flips"] == int(flipped)
    assert len(result["rows"]) == int(flipped)
    assert "no A/A′ band" not in result["labels"]
    assert all(r["unstable"] is True for r in result["rows"])
    args, kwargs = calls[-1]
    assert kwargs["aa_prime"] is args[3]
    assert kwargs["aa_prime_card"] is args[0]
    assert kwargs["aa_prime"] == runner._read(s.out, "outcomes.json")
    assert kwargs["aa_prime_card"] == runner._read(s.out, "card.json")


@pytest.mark.parametrize("copied", [False, True])
def test_aa_of_different_baseline_has_no_band(scenario, tmp_path, copied):
    from shutil import copytree
    s = scenario
    assert s.invoke("baseline") == 0
    if copied:
        copytree(tmp_path / "baseline", tmp_path / "other")
    else:
        assert s.invoke("other") == 0
    s.score = 0
    assert s.invoke(aa_of=tmp_path / "baseline", baseline=tmp_path / "other") == 0
    report = runner._read(s.out, "flips.json")
    assert report["q0"] is None and "no A/A′ band" in report["labels"]
    assert len(report["rows"]) == 4 and all(r["unstable"] is None for r in report["rows"])


def test_aa_of_band_decided_before_any_send(scenario, tmp_path, monkeypatch):
    from shutil import copytree
    s = scenario
    baseline, other, alias = tmp_path / "baseline", tmp_path / "other", tmp_path / "alias"
    assert s.invoke("baseline") == 0
    copytree(baseline, other)
    alias.symlink_to(baseline, target_is_directory=True)
    score = runner.score_item
    def scoring(item, **kw):
        # Once the run is sending, the alias names the copy instead; the band was already decided.
        if alias.resolve() != other.resolve():
            alias.unlink()
            alias.symlink_to(other, target_is_directory=True)
        return score(item, **kw)
    monkeypatch.setattr(runner, "score_item", scoring)
    assert s.invoke(aa_of=alias, baseline=baseline) == 0
    assert alias.resolve() == other.resolve()
    report = runner._read(s.out, "flips.json")
    assert report["q0"] is not None and "no A/A′ band" not in report["labels"]


def test_aa_of_band_follows_file_identity(scenario, tmp_path):
    s = scenario
    assert s.invoke("baseline") == 0
    other_spelling = tmp_path / "BASELINE"
    if not other_spelling.exists():
        pytest.skip("case-sensitive file system: the directory has one spelling")
    assert s.invoke(aa_of=other_spelling, baseline=tmp_path / "baseline") == 0
    report = runner._read(s.out, "flips.json")
    assert report["q0"] is not None and "no A/A′ band" not in report["labels"]


def test_aa_of_with_aa_prime_refused_before_output(scenario, tmp_path, capsys):
    s = scenario
    baseline = tmp_path / "baseline"
    assert s.invoke("baseline") == 0
    assert s.invoke("prime", aa_of=baseline) == 0
    s.stacks.clear(), s.seen.clear()
    capsys.readouterr()
    assert s.invoke(aa_of=baseline, baseline=baseline, aa_prime=tmp_path / "prime") == 3
    assert not s.out.exists() and s.stacks == [] and s.seen == []
    assert capsys.readouterr().err.split() == ["rerun_arguments"]


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
    assert report["counts"]["aa_prime_scored"] == 4
    assert "no A/A′ band" not in report["labels"]
    assert all(r["unstable"] is False for r in report["rows"])


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
        return replace(drive(**kw), transforms=(kw["arm"] + "-transformed",))
    monkeypatch.setattr(runner, "_scan", verify)
    monkeypatch.setattr(runner, "run_life", transformed)
    assert scenario.invoke() == 0 and checked == [scenario.out]
    disclosures = runner._read(scenario.out, "disclosures.json")
    assert disclosures["t1.transforms"] == ["system-transformed"]
    assert disclosures["no_memory.transforms"] == ["no_memory-transformed"]


def test_planted_flip_rerun_command_repeats_checkpoint(scenario, tmp_path, monkeypatch):
    import shlex

    from bicentennial import cli
    s = scenario
    assert s.invoke("baseline", cache=tmp_path / "cache") == 0
    s.score = 0
    assert s.invoke(baseline=tmp_path / "baseline", cache=tmp_path / "cache") == 0
    flip = runner._read(s.out, "flips.json")["rows"][0]
    command = flip["rerun"]
    # Filling the placeholders alone makes a command the parser accepts.
    for old, new in (("<packs>", str(tmp_path / "packs")), ("<hermes checkout>", "unused"),
                     ("<login home>", str(s.home)), ("<max sends>", "30"), ("<new dir>", str(tmp_path / "rerun"))):
        command = command.replace(old, new)
    assert "<" not in command
    argv = shlex.split(command)[2:]
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


@pytest.mark.parametrize("damage", ["items", "outcome", "place", "place_life", "place_branch", "prime_flag",
                                    "prime_invalid", "prime_field"])
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
    elif damage.startswith("place"):
        field, value = {"place": ("probe_point", 9), "place_life": ("life", "t1-g9"), "place_branch": ("branch", "B9")}[damage]
        next(iter(outcomes.values()))[field] = value
    elif damage in ("prime_invalid", "prime_field"):
        prime_card = runner._read(tmp_path / "prime", "card.json")
        if damage == "prime_invalid":
            prime_card["tier"] = "T1"
        else:
            prime_card["pins"]["benchmark_commit"] = "f" * 40
        runner._write(tmp_path / "prime", "card.json", prime_card)
    runner._write(tmp_path / "baseline", "outcomes.json", outcomes)
    prime = tmp_path / ("baseline" if damage == "prime_flag" else "prime")
    s.stacks.clear(), s.seen.clear()
    assert s.invoke(baseline=tmp_path / "baseline", aa_prime=prime) == 3
    assert s.stacks == [] and s.seen == []
    expected = {"items": "baseline_items", "outcome": "items:baseline", "place": "baseline_items",
                "place_life": "baseline_items", "place_branch": "baseline_items",
                "prime_flag": "aa_prime:flag", "prime_invalid": "invalid_card:aa_prime",
                "prime_field": "aa_prime:pins.benchmark_commit"}[damage]
    assert runner._read(s.out, "refusal.json") == {"code": expected}


@pytest.mark.parametrize("damage,code", [("tier", "invalid_card:aa_of"), ("commit", "aa_of:pins.benchmark_commit")])
def test_aa_of_card_refused_by_its_own_name(scenario, tmp_path, damage, code):
    assert scenario.invoke("baseline") == 0
    card = runner._read(tmp_path / "baseline", "card.json")
    if damage == "tier":
        card["tier"] = "T1"
    else:
        card["pins"]["benchmark_commit"] = "f" * 40
    runner._write(tmp_path / "baseline", "card.json", card)
    assert scenario.invoke(aa_of=tmp_path / "baseline") == 3
    assert runner._read(scenario.out, "refusal.json") == {"code": code}


def test_rerun_replays_the_branch_and_keeps_the_checkpoint(scenario, monkeypatch):
    s = scenario
    pack = s.ctx.packs[0]
    for iid, point in (("t1-g1B0-same", 2), ("t1-g1B0-later", 3)):
        extra = dict(row(iid), probe_point=point)
        pack.items["B0"].append(extra)
        pack.records[iid] = dict(item_id=iid, template_id="synthetic", template_version=1)
        pack.records_b["B0"].append(pack.records[iid])
        pack.keys[iid] = {}
        pack.cases[iid] = SimpleNamespace(item=extra)
    drive, ran = runner.run_life, []
    def capture(**kw):
        ran.append((kw["arm"], sorted(i["item_id"] for i in kw["items"])))
        return drive(**kw)
    monkeypatch.setattr(runner, "run_life", capture)
    assert s.invoke(only=("t1-g1", "B0", 2), repeat=2) == 0
    # Each repetition replays the whole branch, so both items run; only the checkpoint's are kept.
    assert [ids for arm, ids in ran if arm == "system"] == [["t1-g1B0", "t1-g1B0-later", "t1-g1B0-same"]] * 2
    # Every item at the checkpoint is kept, and only those.
    assert {i["item_id"] for i in runner._read(s.out, "card.json")["items"]} == {"t1-g1B0", "t1-g1B0-same"}
    repetitions = runner._read(s.out, "repetitions.json")
    assert [set(rep) for rep in repetitions] == [{"t1-g1B0", "t1-g1B0-same"}] * 2
    assert s.invoke("missing", only=("t1-g1", "B0", 9), repeat=2) == 3
    assert runner._read(s.out.parent / "missing", "refusal.json") == {"code": "only"}


@pytest.mark.parametrize("mode,shadow", [("competing", ("opt-a", ("opt-b",))), ("asserted", (None, ()))])
def test_shadow_reading_kept_off_the_live_score(scenario, mode, shadow):
    scenario.mode = mode
    assert scenario.invoke() == 0
    items = runner._read(scenario.out, "card.json")["items"]
    assert {(i["selected_option"], tuple(i["competing_present"])) for i in items} == {shadow}


@pytest.mark.parametrize("mode,blocked", [("relabel", {"t1-g1B0", "t1-g1B1", "t1-g2B0"}), ("relabel_alone", set()),
                                         ("relabel_elsewhere", set())])
def test_relabel_follows_t1(scenario, monkeypatch, mode, blocked):
    # A plug-in's stop that the floor shared is the harness's. An item's own different stop code, or a stop
    # the floor did not share, stays the system's.
    scenario.mode = mode
    monkeypatch.setattr(runner, "is_plugin", lambda name: True)
    monkeypatch.setattr(runner, "resolve_worker_env", lambda *args: None)
    assert scenario.invoke() == 0
    classes = {i["item_id"]: i["failure_class"] for i in runner._read(scenario.out, "card.json")["items"]}
    assert {iid for iid, c in classes.items() if c == "BLOCKED"} == blocked and len(classes) == 4


def test_swap_position_follows_the_schedule(scenario):
    scenario.ctx.packs[0].schedule.scale.swap = 2
    assert scenario.invoke() == 0
    rows = runner._read(scenario.out, "outcomes.json")
    assert {iid: r["swap_position"] for iid, r in rows.items()} == {
        "t1-g1B0": "after", "t1-g1B1": "after", "t1-g2B0": "before", "t1-g2B1": "before"}


def test_failure_while_refusing_removes_output(scenario, monkeypatch):
    scenario.mode = "credential"
    def broken(out, needles):
        raise OSError("synthetic read failure")
    monkeypatch.setattr(runner, "_scan", broken)
    assert scenario.invoke() == 70
    assert sorted(p.name for p in scenario.out.iterdir()) == ["refusal.json"]
    assert runner._read(scenario.out, "refusal.json") == {"code": "tool_failure"}


def test_refusal_codes_follow_t1(scenario, monkeypatch):
    from bicentennial.systems.registry import SystemRefused
    def refuse(**kw):
        raise SystemRefused(("b_reason", "a_reason"))
    monkeypatch.setattr(runner.t1, "prepare", refuse)
    assert scenario.invoke() == 3
    assert runner._read(scenario.out, "refusal.json") == {"code": "a_reason,b_reason"}


def test_null_citation_counts_only_answers(scenario):
    rows = [row("a"), dict(row("b"), envelope=ANSWER),
            dict(row("c"), envelope=dict(ANSWER, citation=dict(quote="synthetic", context_offset=0)))]
    assert runner._card(scenario.ctx, rows)["counts"]["null_citation"] == 1


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
    outcomes = runner._read(tmp_path / "full", "outcomes.json")
    g2_actions = sorted(iid for iid, r in outcomes.items() if r["genre"] == "G2" and r["stage"] == "act")
    assert g2_actions and card["not_scored_live"] == g2_actions
    floor = runner._read(tmp_path / "full", "no_memory.json")["outcomes"]
    for target in (outcomes, floor):
        assert all(target[iid]["score_milli"] is None and target[iid]["accuracy_correct"] is None
                   for iid in g2_actions)
    outcome = next(r for r in outcomes.values() if r["stage"] != "act")
    assert runner._read(tmp_path / "full", "disclosures.json")["live"]["holds"] == {
        "waits": 0, "held_ms": 0, "reasons": []}
    assert runner.run_t2lite(out=tmp_path / "prime", aa_of=tmp_path / "full",
                            baseline=tmp_path / "full", **args) == 0
    noise = runner._read(tmp_path / "prime", "flips.json")
    assert noise["q0"]["numerator"] == 0 and noise["counts"]["aa_prime_scored"] > 0
    assert noise["rows"] == [] and "no A/A′ band" not in noise["labels"]
    only = outcome["life"], outcome["branch"], outcome["probe_point"]
    assert runner.run_t2lite(out=tmp_path / "rerun", only=only, repeat=3, **args) == 0
    repetitions = runner._read(tmp_path / "rerun", "repetitions.json")
    assert len(repetitions) == 3 and all(outcome["item_id"] in rep for rep in repetitions)
    assert all(s.closed and s.drained for s in stacks)
