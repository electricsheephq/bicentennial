"""Live control arms for T2: one probe-only arm, with a pinned control's text placed in the probe turn."""

import json
import runpy
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_t2 import read, t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.audit.readback import life_ids
from bicentennial.canon import canon
from bicentennial.controls import common, naive_rag, oracle_evidence
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.director.responder import Reply
from bicentennial.director.roles import HERMES_MEMORY_FENCE
from bicentennial.harness.hermes import adapter
from bicentennial.ledger import apply_masks
from bicentennial.packs import build
from bicentennial.packs.scoring import control_input, make_score
from bicentennial.probe.scripted_reader import UNKNOWN
from bicentennial.runner import control_arm, t1
from bicentennial.runner.life import STEP_S
from bicentennial.runner.units import T2_SPEC
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.world.db import open_world
from bicentennial.world.targeted import load_tier

ROOT = Path(__file__).resolve().parents[2]
HELPERS = runpy.run_path(str(Path(__file__).with_name("test_life_fake.py")))
drive = HELPERS["drive"]
TEXT_ARMS = ("naive_rag", "oracle_evidence")
MEMORY_TOOLS = {"memory", "session_search", "fact_store", "fact_feedback"}


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


# Captured on main 5e09bbe, before control arms existed: a T2 fixture run without a control arm.
BASE_DIGESTS = {
    "card.json": "9b91b3deeacbc197a99ce34260dc4d28ea6d2bed7ab4e09ca63a47a254872ca7",
    "custody.json": "862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8",
    "disclosures.json": "6ad998c00551198376590a7d8cc613354e089213d2a4b3a1931bd0801e76543f",
    "kept/index.json": "5b59eae9a6b8274f8ed0c10d55ac7d8628dd048eeccd52a6b142c2fede1286dc",
    "kept/t1-g1/B0/t1-g1-shared/bundle.json": "6206c1011972b02f22995a0439dc0dbabbaa1854ae9e469d7d9a9e9352f93d8a",
    "kept/t1-g1/B0/t1-g1-shared/surfaces/0/state": "c81c3c7eb75c5cd6d79f8b690177d08de6f7bba5e5755abb4cd39d0504b66316",
    "kept/t1-g1/B1/t1-g1-shared/bundle.json": "a6e1dcb0703620216014943564ed90e85a857b633ce12b6bbaa6c11cdfedc34a",
    "kept/t1-g1/B1/t1-g1-shared/surfaces/0/state": "c81c3c7eb75c5cd6d79f8b690177d08de6f7bba5e5755abb4cd39d0504b66316",
    "no_memory.json": "6ca9132126b57f05845ed90385aa12f23ce8408a0d776d826228bb33ddbbc4b9",
    "no_memory/t1-g1/B0/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "no_memory/t1-g1/B1/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "no_memory/t1-g2/B0/t2lite_probes.json": "02cc16ac52b08fc5b4a4a409f28a743d70c1292f7e236cd55c46679a3e67114d",
    "no_memory/t1-g2/B1/t2lite_probes.json": "02cc16ac52b08fc5b4a4a409f28a743d70c1292f7e236cd55c46679a3e67114d",
    "outcomes.json": "504e3c271052e0496079f182d79c448da4160c4a95d135c08af4e177af6b0cf0",
    "receipt.json": "f8823d658a4bae7d8b3abf12eaa6429d9f7325eaaf7d9a356158840fb2c97006",
    "receipts/no_memory.json": "ec2d5472054ac717a64ff80f2169083206e4b75503b93b852bbb4955d4f7d86a",
    "receipts/system.json": "d5a65a0c156b33d2633dba32af5d4b23629d4ac63d62685287e5e973d8f96ea7",
    "spend.json": "d5487556beab2972871ade7dd07e3fa048fb1964cc65bbee635a95e5793849ea",
    "system/t1-g1/B0/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "system/t1-g1/B1/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "system/t1-g2/B0/t2lite_probes.json": "8f8cf8b93836aeede6d5523917ef4905d05850a2ec6f31f1e025f0cae6c3d8c7",
    "system/t1-g2/B1/t2lite_probes.json": "8f8cf8b93836aeede6d5523917ef4905d05850a2ec6f31f1e025f0cae6c3d8c7",
    "units.json": "edef413e1537f926db2dcc50bad095d3a0d158a7aad2de4923848561d59fe237",
}


def test_f_run_without_a_control_arm_keeps_base_bytes(t2_scenario):  # noqa: F811
    # Acceptance F: with no control arm requested, a T2 fixture run writes the bytes it wrote before control arms
    # existed, for every file, and a floor cache entry is still read and written as before.
    s = t2_scenario
    assert s.invoke(slots=1) == 0
    assert _digests(s.out) == BASE_DIGESTS


# ---- real T2 packs through the real life runner, the offline fake Hermes worker and a recording live route ----

class Recorder:
    """A scripted live route: it records each request body and answers unknown, as the repository's fakes do."""
    wire = "responses"
    upstreams = {"synthetic-live-model": SimpleNamespace(effort="medium")}

    def __init__(self):
        self.calls = []

    def state(self):
        return {}

    def served_identities(self):
        return {"synthetic-live-model": "synthetic-identity"}

    def respond(self, call):
        self.calls.append(call)
        return Reply(200, "live", "live", call.model, text=canon(UNKNOWN).decode())


@pytest.fixture(scope="module")
def t2_packs(tmp_path_factory):
    """One G1 and one G2 life of the public T2 tier, packed as the tier build packs them and loaded as T2 loads them."""
    spec = load_tier(ROOT / "tiers/life_specs/t2.toml")
    spec["lives"] = [spec["lives"][0], spec["lives"][5]]
    out = tmp_path_factory.mktemp("t2-packs")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "load_tier", lambda path: spec)
        built = build.build_tier("T2", out, harness_artifacts=[load(REGISTRY / "hermes-native.toml")["artifact"]])
    return [t1._pack(out / "T2", rel) for rel in sorted(built["index"]["packs"])]


def pinned_texts(pack, control):
    """{item_id: text} the pinned control itself returns, captured inside its own run (controls/common.py)."""
    seen, read_api = {}, common.read_api

    def spy(adapter, view, keys, now, *, oracle=False):
        seen[view["item_id"]] = adapter.query(dict(task_id=view["item_id"], prompt=keys["recall_query"],
            **({"oracle_evidence": list(keys["oracle_spans"])} if oracle else {})), now)["output"]
        return read_api(adapter, view, keys, now, oracle=oracle)

    score = make_score(json.loads((pack.dir / "sealed/scoring.json").read_bytes()))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(common, "read_api", spy)
        {"naive_rag": naive_rag, "oracle_evidence": oracle_evidence}[control].run(control_input(pack.dir), score=score)
    return seen


def run_unit(pack, branch, control, scratch):
    """The unit a control arm runs: the live no-memory life, with the arm's blocks when it has text."""
    blocks = None if control == "no_memory" else control_arm.probe_blocks(pack, control)[pack.life, branch]
    with closing(open_world(pack.life_dir / f"world.{branch}.db", readonly=True)) as db:
        compiled = compile_script(pack.life_dir, branch, pack.schedule, db, items=pack.items[branch], step_s=STEP_S,
                                  answer_contract=answer_contract, probe_mode=T2_SPEC.probe_mode)
    script = compiled.script if blocks is None else control_arm.with_blocks(compiled.script, compiled.probes, blocks)
    timeline = scratch.parent / f"timeline-{control}.json"
    timeline.write_bytes(canon({t["user"]: [s["index"], t["n"], s["kind"]]
                                for s in script["sessions"] for t in s["turns"]}))
    case = dict(t=SimpleNamespace(out_dir=pack.life_dir, life=pack.life), branch=branch, items=pack.items[branch],
                records=pack.records_b[branch], keys=pack.keys, cases=pack.cases, timeline=timeline)
    live = Recorder()
    result = drive(case, scratch, arm="no_memory", live=live, probe_mode=T2_SPEC.probe_mode, visible=pack.visible,
                   honeypot_token=pack.meta["honeypot_token"],
                   **({} if blocks is None else {"probe_blocks": blocks}))
    probes = {r["item_id"]: r for r in json.loads((result._root / "t2lite_probes.json").read_bytes())}
    turns = {(s["index"], t["n"]): t["user"] for s in compiled.script["sessions"] for t in s["turns"]}
    items = {(p.index, n): iid for p in compiled.probes for n, iid in enumerate(p.item_ids, 1)}
    bodies = [(items[c.cursor["session"], c.cursor["turn"]], turns[c.cursor["session"], c.cursor["turn"]],
               apply_masks(c.body, result.run_values)) for c in live.calls]
    unit = SimpleNamespace(result=result, probes=probes, bodies=bodies, blocks=blocks, audit=result.audit,
                           stopped=result.stopped, classes=dict(result.classes))
    result.cleanup()
    return unit


def last_user(body):
    return next(m for m in reversed(body["messages"]) if m["role"] == "user")["content"]


@pytest.fixture(scope="module")
def arm_units(t2_packs, tmp_path_factory):
    """Every arm on every unit of both packs, each arm on the same scratch path so bodies compare byte for byte."""
    runs = {}
    with pytest.MonkeyPatch.context() as mp:
        # As test_life_fake's harness fixture: the fake worker is not niced and drains quickly.
        mp.setattr(adapter, "DRAIN_QUIET_S", 0.05)
        mp.setattr(adapter, "assert_niced", lambda pid: None)
        for pack in t2_packs:
            for branch in ("B0", "B1"):
                base = tmp_path_factory.mktemp(f"{pack.life}-{branch}")
                for control in ("no_memory", *TEXT_ARMS):
                    runs[pack.life, branch, control] = run_unit(pack, branch, control, base / "unit")
    return runs


def scored_actions(pack, branch):
    # T2 scores G1 actions live; G2 actions are not scored live (runner/units.py _score_run).
    return [i["item_id"] for i in pack.items[branch] if i["stage"] == "act" and pack.genre == "G1"]


@pytest.mark.parametrize("control", TEXT_ARMS)
def test_a_block_is_the_pinned_controls_text_in_the_probe_turn(t2_packs, arm_units, control):
    for pack in t2_packs:
        expected = pinned_texts(pack, control)
        options = {o["option_id"] for i in pack.pack["items"] for o in i["options"]}
        sealed = {v for _, v in life_ids(dict(items=pack.pack["items"], records=list(pack.records.values())))}
        for branch in ("B0", "B1"):
            unit = arm_units[pack.life, branch, control]
            assert unit.stopped is None and unit.classes == {} and unit.audit == {"status": "OK", "failures": []}
            assert unit.blocks == {i["item_id"]: expected[i["item_id"]] for i in pack.items[branch]}
            seen = set()
            for iid, user, body in unit.bodies:
                # The pinned text, framed once, at the top of the probe turn's user message; the turn itself unchanged.
                assert last_user(body) == control_arm.FRAME.format(expected[iid]) + user
                head, tail = control_arm.FRAME.split("{}")
                assert last_user(body)[len(head):len(head) + len(expected[iid])] == expected[iid]
                assert last_user(body)[len(head) + len(expected[iid]):].startswith(tail + user)
                seen.add(iid)
            assert seen == {i["item_id"] for i in pack.items[branch]}
            for iid, text in unit.blocks.items():
                # No answer key, no option ids or order, no sealed identifier, no honeypot token.
                assert not {s for s in sealed | options | {pack.meta["honeypot_token"]} if s in text}, iid
                assert '"option_id"' not in text and "gold" not in text
            if control == "oracle_evidence":
                actions = scored_actions(pack, branch)
                assert all(unit.probes[iid]["shadow"]["in_context"] is True for iid in actions)
    assert any(scored_actions(p, b) for p in t2_packs for b in ("B0", "B1"))


def test_b_naive_rag_in_context_equals_the_packs_scripted_report(t2_packs, arm_units):
    for pack in t2_packs:
        reports = {r["item_id"]: r for r in json.loads(
            (pack.dir / "sealed/naive_rag.json").read_bytes())["arm"]["reports"]}
        for branch in ("B0", "B1"):
            probes = arm_units[pack.life, branch, "naive_rag"].probes
            assert set(probes) == {i["item_id"] for i in pack.items[branch]}
            assert {iid: p["shadow"]["in_context"] for iid, p in probes.items()} == {
                iid: reports[iid]["in_context"] for iid in probes}


def test_c_floor_bodies_and_memory_off(t2_packs, arm_units):
    # The no_memory arm is the plain floor (no block); each text arm's bodies are the floor's plus the block alone.
    for pack in t2_packs:
        for branch in ("B0", "B1"):
            floor = arm_units[pack.life, branch, "no_memory"]
            assert floor.blocks is None and floor.bodies
            for _iid, user, body in floor.bodies:
                assert last_user(body) == user
            for control in ("no_memory", *TEXT_ARMS):
                unit = arm_units[pack.life, branch, control]
                stripped = []
                for iid, user, body in unit.bodies:
                    text = canon(body).decode()
                    assert HERMES_MEMORY_FENCE.strip() not in text and "MEMORY (your personal notes)" not in text
                    assert not MEMORY_TOOLS & {t["function"]["name"] for t in body.get("tools", [])}
                    if unit.blocks is not None:
                        prefix = control_arm.FRAME.format(unit.blocks[iid])
                        body = json.loads(text.replace(json.dumps(prefix)[1:-1], "", 1))
                    stripped.append((iid, user, body))
                assert stripped == floor.bodies


def test_time_block_holds_nothing_after_the_probe(t2_packs):
    # Decision 4: each block equals the block computed from a stream cut at that probe's own time, so no later event
    # reaches it. The cut is the live probe session's clock, which is before the pack's probe time.
    for pack in t2_packs:
        sim = {}
        for branch in ("B0", "B1"):
            with closing(open_world(pack.life_dir / f"world.{branch}.db", readonly=True)) as db:
                compiled = compile_script(pack.life_dir, branch, pack.schedule, db, items=pack.items[branch],
                    step_s=STEP_S, answer_contract=answer_contract, probe_mode=T2_SPEC.probe_mode)
            sim.update({iid: p.sim_t_s for p in compiled.probes for iid in p.item_ids})
        inp = control_input(pack.dir)
        assert all(sim[i] <= inp.now[i] for i in sim)
        for control in TEXT_ARMS:
            full = control_arm.probe_blocks(pack, control)
            for (life, branch), texts in full.items():
                for iid, text in texts.items():
                    cut = dict(inp.events)
                    cut[life] = dict(cut[life], **{branch: [e for e in inp.events[life][branch] if e["t_sim"] <= sim[iid]]})
                    cut_inp = common.ControlInput(inp.pack, inp.keys, cut, inp.now, inp.scoring_sha256)
                    with pytest.MonkeyPatch.context() as mp:
                        mp.setattr(control_arm, "control_input", lambda d, value=cut_inp: value)
                        assert control_arm.probe_blocks(pack, control)[life, branch][iid] == text, (control, iid)
