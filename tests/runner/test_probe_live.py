"""Probe-live boundaries use synthetic objects; the oracle uses the offline T1 worker."""

import copy
import json
import runpy
import socket
import subprocess
from contextlib import ExitStack, closing
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.audit import readback
from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.hermes import compile_script, step_call
from bicentennial.director.responder import Call, Reply
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream.bridge import to_responses
from bicentennial.director.upstream.router import ProbeLiveRouter
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.ledger import BlobStore, Guard, apply_masks
from bicentennial.packs.build import _templates, g1_cases
from bicentennial.probe.probe_responder import ProbeResponder
from bicentennial.probe.scripted_reader import UNKNOWN
from bicentennial.render.stream import content
from bicentennial.runner import life as runner
from bicentennial.runner import probe_live
from bicentennial.runner.hermes_score import MISSING, Infra, score_item
from bicentennial.runner.life import STEP_S
from bicentennial.runner.probe_live import (
    LiveCredentialStop,
    ProbeLiveLeg,
    strip_contract,
)
from bicentennial.sandbox.surfaces import surface_hash
from bicentennial.score.check_selftest import g2_cases
from bicentennial.systems.hermes_plugin import PluginCell
from bicentennial.world.db import open_world

ROOT = Path(__file__).resolve().parents[2]
HELPERS = runpy.run_path(str(Path(__file__).with_name("test_life_fake.py")))
lives = HELPERS["lives"]
harness = HELPERS["harness"]
drive = HELPERS["drive"]
ENTRY = HELPERS["ENTRY"]


class FakeLive:
    wire = "responses"
    upstreams = {"synthetic-live-model": SimpleNamespace(effort="medium")}

    def __init__(self, reply=None):
        self.calls, self.values = [], {}
        self.reply = reply

    def state(self):
        return copy.deepcopy(self.values)

    def served_identities(self):
        return {"synthetic-live-model": "synthetic-identity"}

    def respond(self, call):
        self.calls.append(call)
        # Every synthetic live request also exercises L1's structural/effort bridge.
        assert call.wire == "chat"
        assert to_responses(call.body, effort="medium")["reasoning"] == {"effort": "medium"}
        return self.reply(call) if self.reply else Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode())


def scripted(case, root):
    return ProbeResponder(ScriptedResponder(ENTRY), ENTRY,
        {iid: (p.index, n) for p in case["compiled"].probes for n, iid in enumerate(p.item_ids, 1)},
        {i["item_id"]: (reader_view(i), case["keys"][i["item_id"]]) for i in case["items"]},
        earlier=lambda key, session: runner._earlier(root / "B0/run/ledger", session), step_call=step_call)


def unit_leg(token="ANSWER-TOKEN"):
    fixtures = runpy.run_path(str(ROOT / "tests/probe/test_scripted_reader.py"))["fixtures"]()
    item, keys = copy.deepcopy(fixtures[0]["qf0"]), copy.deepcopy(fixtures[1]["qf0"])
    item["options"][0]["tokens"] = [token]
    keys["required"] = [token]
    view = reader_view(item)
    shadow = SimpleNamespace(cursors={(21, 1): item["item_id"]}, readers={item["item_id"]: (view, keys)},
                             earlier=lambda *args: ())
    live = FakeLive()
    leg = ProbeLiveLeg(live, None, shadow, answer_contract)
    suffix = answer_contract.render([o["envelope"] for o in view["options"]])
    call = Call("probe_main", "cursor", "chat", dict(model="alias", messages=[
        dict(role="system", content="system"), dict(role="user", content=item["prompt"] + suffix)]),
        "probe-model", dict(session=21, turn=1), "synthetic-run")
    return item, leg, live, call


def test_shadow_suffix_model_and_immutable_body():
    item, leg, live, call = unit_leg("confidence_milli")
    before = copy.deepcopy(call.body)
    reply = leg.respond(call)
    result = leg.results()[item["item_id"]]
    assert result.in_context is False and result.selected_option != item["options"][0]["option_id"]
    assert live.calls[0].body == before == call.body
    assert live.calls[0].model == "synthetic-live-model" and reply.model == "probe-model"
    assert leg.served_identities() == live.served_identities()


def test_shadow_first_last_earlier_and_error(monkeypatch):
    item, leg, live, call = unit_leg()
    iid = item["item_id"]
    leg.scripted.earlier = lambda *args: (canon({"text": "ANSWER-TOKEN"}),)
    leg.respond(call)
    leg.respond(replace(call, subrole="tool_results", body=dict(call.body, messages=call.body["messages"] + [
        dict(role="tool", tool_call_id="synthetic-call", content="ANSWER-TOKEN")])))
    assert leg.initial[(call.run_key, 21, 1)] is False
    assert leg.results()[iid].in_context is True
    assert leg.results()[iid].carry_over is True
    def broken(*args, **kwargs):
        raise LookupError("synthetic")
    monkeypatch.setattr(probe_live, "read", broken)
    leg.respond(call)
    assert leg.errors == {iid: "LookupError"} and iid not in leg.results()
    assert len(live.calls) == 3


def test_model_ambiguity_explicit_override_and_chat_pin():
    _, leg, live, call = unit_leg()
    for upstreams in ({}, {"model-a": SimpleNamespace(effort="medium"), "model-b": SimpleNamespace(effort="medium")}):
        live.upstreams = upstreams
        with pytest.raises(ValueError, match="probe_live_model_ambiguous"):
            ProbeLiveLeg(live, None, leg.scripted, answer_contract)
    explicit = ProbeLiveLeg(live, "explicit", leg.scripted, answer_contract)
    explicit.respond(call)
    assert live.calls[-1].model == "explicit"
    with pytest.raises(ValueError, match="probe_live_requires_chat"):
        explicit.respond(replace(call, wire="responses"))


@pytest.mark.parametrize("reason,login_stop", [("upstream_401", None), ("upstream_403", None),
    ("upstream_sse_auth", None), ("unrelated", "synthetic_login_stop")])
def test_credential_stop_and_identity(reason, login_stop):
    _, leg, live, _ = unit_leg()
    live.values.update(stop_reason=reason, login_stop=login_stop, identity_drift={"served": "changed"})
    with pytest.raises(LiveCredentialStop) as error:
        leg.check_session(21)
    assert error.value.reason == (login_stop or reason)
    assert leg.identity_flags == {21}


def test_only_probe_main_reaches_leg():
    _, leg, live, call = unit_leg()
    scripted_calls = []
    scripted = SimpleNamespace(respond=lambda c: scripted_calls.append(c) or Reply(200, "stub", "scripted", c.model))
    router = ProbeLiveRouter(scripted, leg)
    for role in ("write_turn", "summariser", "aux", "memory_write", "embeddings"):
        assert router.respond(replace(call, role=role)).served_by == "scripted"
    assert len(scripted_calls) == 5 and not live.calls
    assert router.respond(call).served_by == "live" and len(live.calls) == 1


@pytest.fixture
def unit_sessions(monkeypatch):
    """Use the real director in process for probe sessions; no listening socket or worker."""
    HELPERS["offline_life_adapter"](monkeypatch)
    def run_session(self, index, *, sim_t_s, lock_hash, attempt_id):
        session = next(s for s in self.script["sessions"] if s["index"] == index)
        self.director.start_session(index, sim_t_s, lock_hash, attempt_id, self.paths["root"] / "ledger")
        self.director.ctx.cursor = next(n for n, t in enumerate(self.director.turns) if t["session"] == index)
        finals = []
        if session["kind"] == "probe":
            for turn in session["turns"]:
                body = dict(model=self.director.route["alias"], messages=[dict(role="user", content=turn["user"])],
                            tools=[dict(type="function", function=dict(name="terminal"))])
                status, _, raw = self.director.handle("POST", "/main/v1/chat/completions", {}, canon(body))
                if status != 200:
                    raise HarnessFailed("turn_failed")
                finals.append((turn["n"], json.loads(raw)["choices"][0]["message"]["content"]))
        turns = len(session["turns"])
        return adapter.SessionResult(index, session["kind"], "unit-session", "test-double", turns, turns,
            (), False, 0, surface_hash(self.paths["hermes_home"], self.volatile), (), {}, tuple(finals))
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run_session)


@pytest.mark.parametrize("served", sorted(probe_live.LIVE_FAILURES))
def test_live_failures_infra_and_continue(lives, tmp_path, unit_sessions, served):
    def fail(call):
        if served == "director_error":
            raise ValueError("synthetic bridge failure")
        return Reply(503, served.removeprefix("responder_"), "live", call.model)
    result = drive(lives["t1-g1", "B0"], tmp_path, live=FakeLive(fail))
    assert set(c[0] for c in result.classes.values()) == {"INFRA_FAILURE"}
    assert set(c[1] for c in result.classes.values()) == {served}
    assert len({r["cursor"]["session"] for r in result.records if r.get("role") == "probe_main"}) == len(
        lives["t1-g1", "B0"]["compiled"].probes)


def test_scripted_director_error_keeps_t1_class(lives, tmp_path, unit_sessions, monkeypatch):
    def broken(self, call):
        raise ValueError("synthetic scripted failure")
    monkeypatch.setattr(ProbeResponder, "respond", broken)
    for live in (None, FakeLive()):
        # A scripted row does not qualify for the live-only override, even inside a live run.
        row = dict(attempt_id="a", role="summariser", served="director_error", upstream=[])
        assert runner._probe_code([row], "a", probe_live=live is not None) is None
    result = drive(lives["t1-g1", "B0"], tmp_path)
    assert result.stopped[0:2] == ("SYSTEM_FAILURE", "turn_failed")


def test_credential_stops_before_next_session(lives, tmp_path, unit_sessions, monkeypatch):
    live = FakeLive()
    original, indices, closed = adapter.HermesAdapter.run_session, [], []
    def run(self, index, **kwargs):
        indices.append(index)
        result = original(self, index, **kwargs)
        live.values.update(stop_reason="upstream_401")
        return result
    close = adapter.HermesAdapter.close
    def finish(self):
        closed.append(True)
        return close(self)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run)
    monkeypatch.setattr(adapter.HermesAdapter, "close", finish)
    with pytest.raises(LiveCredentialStop, match="upstream_401"):
        drive(lives["t1-g1", "B0"], tmp_path, live=live)
    assert indices == [1] and closed == [True]


def test_identity_and_spend_records(lives, tmp_path, unit_sessions):
    live = FakeLive()
    def respond(call):
        if len(live.calls) == 1:
            live.values.update(identity_drift={"served": "changed"}, spend_stopped=True)
            return Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode())
        return Reply(503, "live_spend_stop", "live", call.model)
    live.reply = respond
    result = drive(lives["t1-g1", "B0"], tmp_path, live=live)
    rows = json.loads((result._root / "t2lite_probes.json").read_bytes())
    first_session = lives["t1-g1", "B0"]["compiled"].probes[0].index
    assert all(r["live"]["identity_flag"] == (r["probe_session"] == first_session) for r in rows)
    assert all(c == ("INFRA_FAILURE", "responder_live_spend_stop") for c in result.classes.values())
    assert len(live.calls) >= len(lives["t1-g1", "B0"]["compiled"].probes)


def test_shadow_error_still_sends_and_is_no_result_infra(lives, tmp_path, unit_sessions, monkeypatch):
    def broken(*args, **kwargs):
        raise ArithmeticError("synthetic")
    monkeypatch.setattr(probe_live, "read", broken)
    case, live = lives["t1-g1", "B0"], FakeLive()
    result = drive(case, tmp_path, live=live)
    assert live.calls and result.results == {}
    for item in case["items"]:
        assert score_item(item, cls=None, label=None, result=MISSING, envelope=MISSING, act=MISSING,
            case=None, scoring_evidence=[], keys=None, stored_roots=None, retained_roots=None, attempt=0) == Infra("no_result")
    assert all(r["shadow"]["shadow_error"] == "ArithmeticError" for r in json.loads(
        (result._root / "t2lite_probes.json").read_bytes()))


def test_shadow_error_stays_infra_after_later_failure(lives, tmp_path, unit_sessions, monkeypatch):
    case = lives["t1-g1", "B0"]
    first, sessions = case["compiled"].probes[0], case["compiled"].script["sessions"]
    # Probe indices follow the replay indices, so take the next replay in script order.
    at = next(n for n, s in enumerate(sessions) if s["index"] == first.index)
    later = next((s["index"] for s in sessions[at + 1:] if s["kind"] != "probe"), None)
    assert later is not None
    read, run_session = probe_live.read, adapter.HermesAdapter.run_session
    def broken(view, *args, **kwargs):
        if view["item_id"] in first.item_ids:
            raise ArithmeticError("synthetic")
        return read(view, *args, **kwargs)
    def run(self, index, **kwargs):
        if index == later:
            raise HarnessFailed("turn_failed")
        return run_session(self, index, **kwargs)
    monkeypatch.setattr(probe_live, "read", broken)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", run)
    result = drive(case, tmp_path, live=FakeLive())
    # The replay failure stops the life, but cannot turn the earlier shadow error into a system failure.
    assert result.stopped == ("SYSTEM_FAILURE", "turn_failed", later)
    assert {iid: result.classes[iid] for iid in first.item_ids} == {
        iid: ("INFRA_FAILURE", "shadow_error") for iid in first.item_ids}


@pytest.mark.parametrize("shadow_fails", [False, True])
@pytest.mark.parametrize("status", [200, 503])
def test_unsettled_checkpoint_wins_over_live_failure(lives, tmp_path, unit_sessions, monkeypatch, status, shadow_fails):
    # The store settles, or not, before its probe runs, and only scripted roles reach it, as at T1.
    source, entry = HELPERS["plugin_source"](tmp_path)
    monkeypatch.setattr(PluginCell, "settle", lambda self: SimpleNamespace(settled=False))
    if shadow_fails:
        # A failed shadow read is pinned only where nothing has classed the item, so unsettled still wins.
        def broken(view, *args, **kwargs):
            raise ArithmeticError("synthetic")
        monkeypatch.setattr(probe_live, "read", broken)
    case = lives["t1-g1", "B0"]
    live = FakeLive(lambda call: Reply(status, "live_unavailable", "live", call.model, text=canon(UNKNOWN).decode()))
    # A 200 completes the session with the failure in its row; a 503 fails the turn.
    result = drive(case, tmp_path / "run", entry=entry, plugin_source=source, live=live)
    assert live.calls
    assert result.classes == {i["item_id"]: ("SYSTEM_FAILURE", "unsettled") for i in case["items"]}


def test_record_bytes_fields_and_live_answer_independence(lives, tmp_path, unit_sessions):
    case = lives["t1-g1", "B0"]
    by_cursor = {(p.index, n): next(i for i in case["items"] if i["item_id"] == iid)
                 for p in case["compiled"].probes for n, iid in enumerate(p.item_ids, 1)}
    def answer(call):
        item = by_cursor[call.cursor["session"], call.cursor["turn"]]
        env = dict(item["options"][0].get("envelope", UNKNOWN), citation={"quote": "synthetic bad citation", "context_offset": 0})
        if env["type"] == "unknown":
            env = UNKNOWN
        return Reply(200, "live", "live", call.model, text=canon(env).decode())
    first = drive(case, tmp_path / "first", live=FakeLive(answer))
    second = drive(case, tmp_path / "other", live=FakeLive(answer))
    raw = (first._root / "t2lite_probes.json").read_bytes()
    assert raw == (second._root / "t2lite_probes.json").read_bytes()
    rows = json.loads(raw)
    assert raw == canon(rows) and len(rows) == len(case["items"])
    assert [r["item_id"] for r in rows] == sorted(r["item_id"] for r in rows)
    for row in rows:
        iid = row["item_id"]
        assert set(row) == {"item_id", "probe_session", "checkpoint", "stage", "shadow", "envelope", "live"}
        assert set(row["shadow"]) == {"selected_option", "in_context", "in_context_initial", "carry_over", "stage_attribution", "shadow_error"}
        assert set(row["envelope"]) == {"parsed", "value_match", "value_match_normalised", "citation_match"}
        assert set(row["live"]) == {"served_by", "served", "identity_flag"}
        assert row["shadow"]["selected_option"] == first.results[iid].selected_option
        if row["stage"] != "act":
            assert row["envelope"]["parsed"] == first.envelopes[iid]
            assert row["envelope"]["citation_match"] is (None if first.envelopes[iid]["type"] == "unknown" else False)
            assert row["shadow"]["in_context_initial"] == row["shadow"]["in_context"]
        assert row["live"] == dict(served_by="live", served="responder_live", identity_flag=False)
    assert any(r["envelope"]["value_match"] is True and r["shadow"]["in_context"] is False for r in rows)
    # A bad citation or an action never taken fails items of both stages, so attributions are set, and each is the scorer's.
    attribution = {iid: o["stage_attribution"] if isinstance(o, dict) else None
                   for iid, o in scored(case, "t1-g1", first).items()}
    assert all(row["shadow"]["stage_attribution"] == attribution[row["item_id"]] for row in rows)
    assert {row["stage"] == "act" for row in rows if row["shadow"]["stage_attribution"]} == {True, False}
    baseline = drive(case, tmp_path / "plain")
    assert not (baseline._root / "t2lite_probes.json").exists()


def test_last_session_identity_is_recorded(lives, tmp_path, unit_sessions):
    case, live = lives["t1-g1", "B0"], FakeLive()
    last = case["compiled"].probes[-1].index
    def answer(call):
        if call.cursor["session"] == last:
            live.values["identity_drift"] = {"served": "late-change"}
        return Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode())
    live.reply = answer
    result = drive(case, tmp_path, live=live)
    rows = json.loads((result._root / "t2lite_probes.json").read_bytes())
    assert all(row["live"]["identity_flag"] == (row["probe_session"] == last) for row in rows)


def test_each_identity_change_flags_its_session(lives, tmp_path, unit_sessions):
    case, live = lives["t1-g1", "B0"], FakeLive()
    first, last = case["compiled"].probes[0].index, case["compiled"].probes[-1].index
    assert first != last
    def answer(call):
        changed = call.cursor["session"] in (first, last)
        if changed:
            # As L1 does, the stack's state keeps only the first drift; each reply's diagnostics mark its own.
            live.values.setdefault("identity_drift", {"served": "first-change"})
        return Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode(),
                     upstream=(dict(identity_changed=True),) if changed else ())
    live.reply = answer
    result = drive(case, tmp_path, live=live)
    rows = json.loads((result._root / "t2lite_probes.json").read_bytes())
    assert {row["probe_session"] for row in rows if row["live"]["identity_flag"]} == {first, last}


@pytest.mark.parametrize("life", ["t1-g1", "t1-g2"])
def test_default_compile_matches_base_bytes(lives, life):
    case = lives[life, "B0"]
    # Read the dispatched implementation, so adding a suffix with None is detected byte for byte.
    source = subprocess.run(["git", "show", "dd5fcf58:src/bicentennial/director/compiler/hermes.py"],
        check=True, capture_output=True, text=True).stdout
    scope = dict(__name__="bicentennial.director.compiler.hermes")
    exec(compile(source, "base-hermes.py", "exec"), scope)
    with closing(open_world(case["t"].out_dir / "world.B0.db", readonly=True)) as db:
        args = (case["t"].out_dir, "B0", case["t"].schedule, db)
        base = scope["compile_script"](*args, items=case["items"], step_s=STEP_S)
        current = compile_script(*args, items=case["items"], step_s=STEP_S, answer_contract=None)
    assert canon(base.script) == canon(current.script)


@pytest.fixture
def loopback():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("sandbox cannot bind loopback sockets; owner must rerun oracle")


class Oracle(FakeLive):
    def __init__(self, case, root):
        super().__init__()
        self.scripted = scripted(case, root)

    def respond(self, call):
        super().respond(call)
        body = call.body
        for view, _ in self.scripted.readers.values():
            if "envelope" in view["options"][0]:
                body = strip_contract(body, view["prompt"], answer_contract.render([o["envelope"] for o in view["options"]]))
        return replace(self.scripted.respond(replace(call, body=body)), served_by="live")


def contract_timeline(case, path):
    timeline = json.loads(case["timeline"].read_bytes())
    for item in case["items"]:
        if item["stage"] != "act":
            prompt = item["prompt"]
            timeline[prompt + answer_contract.render([o["envelope"] for o in item["options"]])] = timeline[prompt]
    path.write_bytes(canon(timeline))
    return dict(case, timeline=path)


def scored(case, life, result):
    """Score every item of one run as the tier runners do."""
    with ExitStack() as stack:
        worlds = {b: (stack.enter_context(closing(open_world(case["t"].out_dir / f"world.{b}.db"))), cut)
                  for b, cut in zip(("B0", "B1"), case["t"].twin.cuts, strict=True)}
        cases = (g1_cases if life == "t1-g1" else g2_cases)(case["t"].twin.compiled, worlds,
            case["t"].schedule, _templates(case["t"], case["t"].twin.compiled.records), life=life)
    cases = {c.item["item_id"]: c for c in cases}
    stream = [json.loads(line) for line in (case["t"].out_dir / "stream.B0.jsonl").read_bytes().splitlines()]
    return {item["item_id"]: score_item(item, cls=None, label=None, result=result.results[item["item_id"]],
        envelope=result.envelopes.get(item["item_id"], MISSING), act=result.act.get(item["item_id"], MISSING),
        case=cases[item["item_id"]], scoring_evidence=[content(s) for s in stream if s["event_id"] in item["gold_spans"]],
        keys=case["keys"][item["item_id"]], stored_roots=result.stored_roots.get(item["item_id"]),
        retained_roots=result.retained_roots.get(item["item_id"]), attempt=0) for item in case["items"]}


def replay_rows(result):
    # As in T1's determinism test: raw chains/wall time differ; stable fields and masked bodies must agree.
    schema = json.loads((SCHEMAS / "ledger-record.schema.json").read_bytes())["properties"]
    stable = {k for k, prop in schema.items() if prop["x-stability"] == "stable"}
    digests = {k for k in stable if schema[k].get("pattern") == "^[0-9a-f]{64}$"}
    blobs = BlobStore(result._root / "run/ledger/blobs", Guard([]))
    rows = []
    for row in result.records:
        if (row.get("cursor") or {}).get("session", 100) > 20:
            continue
        projected = dict(apply_masks({k: v for k, v in row.items() if k in stable - digests}, result.run_values),
                         **{k: row[k] for k in digests if k in row})
        projected["upstream"] = apply_masks([dict(u, req=json.loads(blobs.get(u["req"])),
            resp=json.loads(blobs.get(u["resp"]))) for u in row.get("upstream", [])], result.run_values)
        rows.append(projected)
    return rows


@pytest.mark.parametrize("life", ["t1-g1", "t1-g2"])
def test_oracle_matches_t1(lives, tmp_path, harness, loopback, life):
    case = lives[life, "B0"]
    baseline = drive(case, tmp_path / "t1-run")
    live_case = contract_timeline(case, tmp_path / "live-timeline.json")
    live_root = tmp_path / "live-a"
    oracle = Oracle(case, live_root)
    actual = drive(live_case, live_root, live=oracle)
    assert baseline.stopped is actual.stopped is None
    assert baseline.audit == actual.audit == {"status": "OK", "failures": []}
    assert baseline.classes == actual.classes == {} and actual.transforms == ()
    assert all(c.role == "probe_main" for c in oracle.calls)
    assert all(baseline.results[iid].in_context == r.in_context for iid, r in actual.results.items())
    assert all(actual.envelopes[i["item_id"]] is not None for i in case["items"] if i["stage"] != "act")
    # The native store is memories/. Harness config and fake session UUID files are run-specific.
    def checkpoints(result):
        return {p.checkpoint: surface_hash(result.retained_roots[p.item_ids[0]][0] / "memories", [])
                for p in case["compiled"].probes}
    assert checkpoints(baseline) == checkpoints(actual)
    assert replay_rows(baseline) == replay_rows(actual)
    expected, observed = scored(case, life, baseline), scored(case, life, actual)
    shadow = {r["item_id"]: r["shadow"] for r in json.loads((actual._root / "t2lite_probes.json").read_bytes())}
    for item in case["items"]:
        iid = item["item_id"]
        outcomes = [expected[iid], observed[iid]]
        assert all(isinstance(o, dict) for o in outcomes)
        assert [(o["score_milli"], o["failure_class"]) for o in outcomes] == [
            (outcomes[0]["score_milli"], outcomes[0]["failure_class"])] * 2, iid
        assert shadow[iid]["stage_attribution"] == outcomes[1]["stage_attribution"] == outcomes[0]["stage_attribution"], iid
    again_root = tmp_path / "live-b"
    again = drive(live_case, again_root, live=Oracle(case, again_root))
    record = (actual._root / "t2lite_probes.json").read_bytes()
    assert record == (again._root / "t2lite_probes.json").read_bytes()
    rows = json.loads(record)
    assert record == canon(rows) and [r["item_id"] for r in rows] == sorted(r["item_id"] for r in rows)
    assert set(rows[0]) == {"item_id", "probe_session", "checkpoint", "stage", "shadow", "envelope", "live"}
    assert set(rows[0]["shadow"]) == {"selected_option", "in_context", "in_context_initial", "carry_over", "stage_attribution", "shadow_error"}
    assert set(rows[0]["envelope"]) == {"parsed", "value_match", "value_match_normalised", "citation_match"}
    assert set(rows[0]["live"]) == {"served_by", "served", "identity_flag"}
    # A replay reply is still audited in full even when probe rows are live.
    ledger, blobs, _ = readback.load(actual._root / "run/ledger", "kit")
    replay = next(r for r in ledger if r.get("served") == "script")
    blobs[replay["resp"]]["choices"][0]["message"]["content"] = "tampered"
    report = readback.audit(ledger, blobs, readback.turns_from_script(case["compiled"].script), "chat", fmt="kit",
        model_for=lambda s: "probe-model", suffix=None, write_tools=("memory",), id_needles=[], effects=lambda *args: {})
    assert replay["seq"] in report["A5"]["script_failures"]


def test_missing_envelope_uses_delivered_final(lives, tmp_path, unit_sessions, monkeypatch):
    original = adapter.HermesAdapter.run_session
    def changed(self, index, **kwargs):
        result = original(self, index, **kwargs)
        return replace(result, finals=tuple((n, "not JSON") for n, _ in result.finals))
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", changed)
    result = drive(lives["t1-g1", "B0"], tmp_path, live=FakeLive())
    assert result.transforms == ()
    assert result.envelopes and all(env is None for env in result.envelopes.values())
    rows = json.loads((result._root / "t2lite_probes.json").read_bytes())
    assert all(row["envelope"]["parsed"] is None for row in rows)


def test_earlier_final_survives_later_live_failure(lives, tmp_path, unit_sessions):
    live = FakeLive()
    def answer(call):
        return (Reply(503, "live_unavailable", "live", call.model) if len(live.calls) == 2 else
                Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode()))
    live.reply = answer
    case = dict(lives["t1-g1", "B0"])
    case["items"] = copy.deepcopy(case["items"])
    first_id = case["compiled"].probes[0].item_ids[0]
    first_item = next(i for i in case["items"] if i["item_id"] == first_id)
    second = copy.deepcopy(first_item)
    second.update(item_id="synthetic-second-qa", prompt=first_item["prompt"] + " Answer the synthetic follow-up.")
    case["items"].append(second)
    second_key = dict(copy.deepcopy(case["keys"][first_id]), item_id=second["item_id"], recall_query=second["prompt"])
    case["keys"] = case["keys"] | {second["item_id"]: second_key}
    first_record = next(r for r in case["records"] if r["item_id"] == first_id)
    case["records"] = [*case["records"], dict(first_record, item_id=second["item_id"])]
    with closing(open_world(case["t"].out_dir / "world.B0.db", readonly=True)) as db:
        case["compiled"] = compile_script(case["t"].out_dir, "B0", case["t"].schedule, db,
                                          items=case["items"], step_s=STEP_S)
    result = drive(case, tmp_path, live=live)
    first = case["compiled"].probes[0]
    assert len(first.item_ids) > 1
    assert result.envelopes[first.item_ids[0]] == UNKNOWN
    assert result.envelopes[first.item_ids[1]] is None
    assert all(iid not in result.classes for p in case["compiled"].probes[1:] for iid in p.item_ids)
