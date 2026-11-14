"""Live control arms for T2: one probe-only arm, with a pinned control's text placed in the probe turn."""

import json
import runpy
from contextlib import closing
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_t2 import read, t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial import cli
from bicentennial.anchors import WINDOW
from bicentennial.anchors import run as run_anchor
from bicentennial.anchors.report import ANCHORS, header
from bicentennial.audit.readback import life_ids
from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.controls import common, naive_rag, oracle_evidence
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.hermes import compile_script
from bicentennial.director.responder import Call, Reply
from bicentennial.director.roles import HERMES_MEMORY_FENCE
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.config import (
    HERMES_TOOLSETS,
    hermes_config,
    write_config,
)
from bicentennial.ledger import apply_masks
from bicentennial.packs import build
from bicentennial.packs.scoring import control_input, make_score
from bicentennial.probe.scripted_reader import UNKNOWN
from bicentennial.runner import control_arm, t1, t2, units
from bicentennial.runner.life import STEP_S, run_life
from bicentennial.runner.units import T2_SPEC
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.world.db import open_world
from bicentennial.world.targeted import load_tier

ROOT = Path(__file__).resolve().parents[2]
HELPERS = runpy.run_path(str(Path(__file__).with_name("test_life_fake.py")))
drive = HELPERS["drive"]
TEXT_ARMS = ("naive_rag", "oracle_evidence", *ANCHORS)
MEMORY_TOOLS = {"memory", "session_search", "fact_store", "fact_feedback"}
# Whole canonical reader config captured at 833a82e: port 1, default alias, no memory, no MCP.
READER_CONFIG_833A82E = "7cdae910ab8916e1338c4171648c9f3bc7cf9eef15739eb42cee68fdd2d746b8"


def assert_reader_config(cfg, control):
    # Freeze the complete base config, then compare the complete written config, including G2's MCP transport.
    baseline = hermes_config(1, "bicentennial-main", memory=False, toolsets=HERMES_TOOLSETS, scripted=True)
    assert sha256(canon(baseline)).hexdigest() == READER_CONFIG_833A82E
    port = int(cfg["model"]["base_url"].split(":")[2].split("/")[0])
    expected = hermes_config(port, cfg["model"]["default"], memory=False,
        toolsets=HERMES_TOOLSETS + (("envserver",) if "mcp_servers" in cfg else ()),
        mcp_servers=cfg.get("mcp_servers"), scripted=True)
    if control in ("grep", "recent_window"):
        expected["compression"]["threshold_tokens"] = 2 * WINDOW
        expected["model"]["context_length"] = expected["auxiliary"]["compression"]["context_length"] = 8 * WINDOW
    assert canon(cfg) == canon(expected)


@pytest.mark.parametrize("control", control_arm.CONTROL_ARMS)
def test_written_reader_config_without_sockets(tmp_path, monkeypatch, control):
    pack = SimpleNamespace(life="synthetic-life")
    ctx = SimpleNamespace(entry={}, plugin_source=None, model_cache=None, worker_argv=None, packs=[pack])
    monkeypatch.setattr(control_arm, "probe_blocks", lambda pack, control: {
        (pack.life, b): {"synthetic-item": "synthetic block"} for b in ("B0", "B1")})
    queued = control_arm.control_units(ctx, control, tmp_path / "scratch", tmp_path / "out")
    for unit in queued:
        assert unit.arm.probe_window == (2 * WINDOW if control in ("grep", "recent_window") else None)
        cfg = hermes_config(1, "bicentennial-main", memory=False, toolsets=HERMES_TOOLSETS,
                            scripted=True, window=unit.arm.probe_window)
        assert_reader_config(json.loads(write_config(tmp_path, cfg).read_bytes()), control)


@pytest.mark.parametrize("arm", ("system", "wiped", "no_memory"))
def test_probe_window_without_blocks_refuses_before_io(arm):
    with pytest.raises(ValueError, match="probe window requires probe blocks"):
        run_life(arm=arm, entry={}, life_dir=None, branch="B0", items=[], records=[], keys={}, scratch=None,
                 run="synthetic", attempt=0, gate=None, current_lock=None, voids=None, harness_pin={},
                 probe_window=2 * WINDOW)


@pytest.mark.parametrize("control", control_arm.CONTROL_ARMS)
def test_arm_probe_window_requires_blocks(control):
    with pytest.raises(ValueError, match="probe window requires probe blocks"):
        units.Arm(control, {}, role="no_memory", probe_window=2 * WINDOW)

# Raw bytes captured on 87e4d9a, before anchor live arms; no timing normalization.
LEGACY_BYTES = {
    "no_memory": ("46201410aeacfdb657920c2780dcd05cd8e0c7a00a3813650bdfee6b9bc37c6f",
                  "d66c079fb07603f22a9293f411d03f77003e92bd58f0f19d1976da6c238763bc"),
    "naive_rag": ("0e8b2114afdab6dbc0f9bc7026ed9ce26ee7cfceda8a49af90055ec1c14ea6f4",
                  "d3147bc5c60edde78c6b49742bccd3ddd9bd890ac7e0bf64aa2bbce996b3a047"),
    "oracle_evidence": ("e055824285fcae667104139d2db84cf9615501138c0e76d4e47758cfa26aef72",
                        "1e93f2e0d2ffd86471258bd0cd15263df40281611806fa0da77f41d77bb6e199"),
}


@pytest.mark.parametrize("control", ANCHORS)
def test_cli_accepts_anchor_control_but_keeps_it_hidden(monkeypatch, capsys, control):
    seen = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "run_t2", lambda **kw: seen.append(kw) or 0)
    assert cli.main(["t2", "--system", "hermes-native", "--packs", "packs", "--pack-hash", "a" * 64,
                     "--out", "out", "--login-home", "synthetic-home", "--max-sends", "100",
                     "--control", control]) == 0
    assert seen[0]["control"] == control
    with pytest.raises(SystemExit) as caught:
        cli.main(["t2", "--help"])
    assert caught.value.code == 0 and "--control" not in capsys.readouterr().out


def _digests(out, budget=None):
    """Every file a run writes, with only its wall-clock and monotonic timing fields zeroed.

    budget: a system run's send-budget disclosure (#507), removed from disclosures.json and checked here,
    along with the additive zero unreadable-state counters (#524).
    """
    result = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".json":
            value = json.loads(data)
            if budget is not None and path.name == "disclosures.json":
                assert {k: value["live"].pop(k) for k in budget} == budget
                assert value.pop("unreadable_state") == {"system": 0, "no_memory": 0}
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
    # The fake stack counts no sends; the send-budget disclosure is the only addition (#507).
    assert _digests(s.out, dict(max_sends=100, phase_sends=dict(floor=0, system=0))) == BASE_DIGESTS


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
        if control in ANCHORS:
            run_anchor(control_input(pack.dir), ANCHORS[control], score=score)
        else:
            {"naive_rag": naive_rag, "oracle_evidence": oracle_evidence}[control].run(
                control_input(pack.dir), score=score)
    return seen


@pytest.mark.parametrize("control", TEXT_ARMS)
def test_probe_blocks_equal_the_scripted_outputs(t2_packs, control):
    for pack in t2_packs:
        expected = pinned_texts(pack, control)
        assert control_arm.probe_blocks(pack, control) == {
            (pack.life, b): {i["item_id"]: expected[i["item_id"]] for i in pack.items[b]}
            for b in ("B0", "B1")}


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
    configs = []

    def record_config(home, cfg):
        path = write_config(home, cfg)
        configs.append(json.loads(path.read_bytes()))
        return path

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(adapter, "write_config", record_config)
        result = drive(case, scratch, arm="no_memory", live=live, probe_mode=T2_SPEC.probe_mode, visible=pack.visible,
                       honeypot_token=pack.meta["honeypot_token"],
                       **({} if blocks is None else {"probe_blocks": blocks}),
                       **({} if control_arm.probe_window(control) is None else {
                           "probe_window": control_arm.probe_window(control)}))
    probes = {r["item_id"]: r for r in json.loads((result._root / "t2lite_probes.json").read_bytes())}
    turns = {(s["index"], t["n"]): t["user"] for s in compiled.script["sessions"] for t in s["turns"]}
    items = {(p.index, n): iid for p in compiled.probes for n, iid in enumerate(p.item_ids, 1)}
    bodies = [(items[c.cursor["session"], c.cursor["turn"]], turns[c.cursor["session"], c.cursor["turn"]],
               apply_masks(c.body, result.run_values)) for c in live.calls]
    unit = SimpleNamespace(result=result, probes=probes, bodies=bodies, blocks=blocks, audit=result.audit,
                           stopped=result.stopped, classes=dict(result.classes), configs=configs)
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


@pytest.mark.parametrize("control", ["grep", "recent_window", "no_memory", "naive_rag", "oracle_evidence", "bm25"])
def test_probe_session_writes_the_arms_reader_config(arm_units, control):
    for (life, branch, arm), unit in arm_units.items():
        if arm == control:
            assert unit.configs, (life, branch, arm)
            for cfg in unit.configs:
                assert_reader_config(cfg, control)


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


@pytest.mark.parametrize("control", ANCHORS)
def test_b_anchor_initial_in_context_equals_the_scripted_report(t2_packs, arm_units, control):
    for pack in t2_packs:
        score = make_score(json.loads((pack.dir / "sealed/scoring.json").read_bytes()))
        scripted = run_anchor(control_input(pack.dir), ANCHORS[control], score=score)
        reports = {r["item_id"]: r for r in scripted["reports"]}
        for branch in ("B0", "B1"):
            probes = arm_units[pack.life, branch, control].probes
            assert set(probes) == {i["item_id"] for i in pack.items[branch]}
            assert {iid: p["shadow"]["in_context_initial"] for iid, p in probes.items()} == {
                iid: reports[iid]["in_context"] for iid in probes}


@pytest.mark.parametrize("control", ANCHORS)
def test_anchor_has_no_sealed_key(t2_packs, control):
    for pack in t2_packs:
        assert not (pack.dir / "sealed" / f"{control}.json").exists()
        assert control_arm.control_key_sha256(pack, control) is None


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
                    # Only this item, so the cut cannot remove a later probe's own evidence.
                    alone = replace(pack, items={b: [i for i in pack.items[b] if i["item_id"] == iid]
                                                 for b in ("B0", "B1")})
                    with pytest.MonkeyPatch.context() as mp:
                        mp.setattr(control_arm, "control_input", lambda d, value=cut_inp: value)
                        assert control_arm.probe_blocks(alone, control)[life, branch][iid] == text, (control, iid)


# ---- the T2 runner with one control arm, on the T2 fixture's synthetic packs ----

def synthetic_text(pack, branch, iid):
    return f"synthetic control text for {pack.life} {branch} {iid}"


@pytest.fixture
def control_scenario(t2_scenario, monkeypatch):  # noqa: F811
    s = t2_scenario
    monkeypatch.setattr(control_arm, "probe_blocks", lambda pack, control: {
        (pack.life, b): {i["item_id"]: synthetic_text(pack, b, i["item_id"]) for i in pack.items[b]}
        for b in ("B0", "B1")})
    key_hash = t2.control_key_sha256
    monkeypatch.setattr(t2, "control_key_sha256", lambda pack, control: (
        key_hash(pack, control) if control in ANCHORS else f"{control}-{pack.life}-key"))
    s.lives, drive_life = [], units.run_life

    def recorded(**kw):
        s.lives.append(kw)
        return drive_life(**kw)

    monkeypatch.setattr(units, "run_life", recorded)
    return s


@pytest.mark.parametrize("control", ["no_memory", *TEXT_ARMS])
def test_outputs_use_the_floors_shapes_with_the_arm_and_its_hashes(control_scenario, monkeypatch, control):
    s = control_scenario
    metadata_reads = []

    def snapshot():
        assert not s.stacks
        metadata_reads.append(control)
        return header()

    monkeypatch.setattr(control_arm, "header", snapshot)
    assert s.invoke(control=control) == 0
    assert metadata_reads == ([control] if control in ANCHORS else [])
    out = s.out
    names = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert {"card.json", "outcomes.json", control + ".json", "control.json", "units.json", "receipt.json",
            f"receipts/{control}.json", "disclosures.json", "custody.json", "spend.json"} <= names
    assert not any(n.startswith(("system/", "kept/", "receipts/system")) for n in names)
    assert control == "no_memory" or "no_memory.json" not in names
    card = read(out, "card.json")
    validate("card_t2", card)
    assert card["control"] == control and card["system"] == "hermes-native"
    assert card["live_roles"] == ["probe_main"] and card["served_identity"] == read(out, control + ".json")[
        f"{s.ctx.packs[0].life}/B0"]["served_identity"]
    assert len(read(out, "outcomes.json")) == len(card["items"]) == 8
    floor = read(out, control + ".json")
    assert set(floor) == set(card["floor"]["units"]) and all(
        set(v) == {"outcomes", "stops", "served_identity"} for v in floor.values())
    assert not any(v["cached"] for v in card["floor"]["units"].values())
    for name in ("receipt.json", f"receipts/{control}.json"):
        validate("receipt", read(out, name))
    timing = read(out, "units.json")
    assert len(timing["units"]) == 4 and all(r["arm"] == control for r in timing["units"])
    assert all(r["end_ms"] >= r["start_ms"] > 0 for r in timing["units"])
    assert all(r == dict(cached=False, reason="control arm") for r in read(out, "disclosures.json")["floor"].values())
    record = read(out, "control.json")
    if control in LEGACY_BYTES:
        assert tuple(sha256((out / n).read_bytes()).hexdigest()
                     for n in ("control.json", "card.json")) == LEGACY_BYTES[control]
    texts = {f"{p.life}/{b}/{i['item_id']}": synthetic_text(p, b, i["item_id"])
             for p in s.ctx.packs for b in ("B0", "B1") for i in p.items[b]}
    expected = dict(arm=control,
        frame_sha256=None if control == "no_memory" else sha256(control_arm.FRAME.encode()).hexdigest(),
        control_key_sha256={p.life: None if control in ANCHORS else f"{control}-{p.life}-key" for p in s.ctx.packs},
        block_sha256={} if control == "no_memory" else {k: sha256(v.encode()).hexdigest() for k, v in texts.items()})
    if control in ANCHORS:
        definition = header()["anchors"][control]
        expected["anchor"] = dict(name=control, **{k: definition[k] for k in (
            "version", "spec_sha256", "code_sha256")})
        assert card["anchor"] == record["anchor"] == expected["anchor"]
    else:
        assert "anchor" not in card and "anchor" not in record
    assert record == expected
    # Each unit's life receives exactly its own blocks; the no_memory arm receives none.
    for kw in s.lives:
        pack = next(p for p in s.ctx.packs if p.life == kw["life_dir"].name)
        assert kw["arm"] == "no_memory" and kw["probe_mode"] == "per_item"
        assert kw.get("probe_blocks") == (None if control == "no_memory" else {
            i["item_id"]: synthetic_text(pack, kw["branch"], i["item_id"]) for i in kw["items"]})
        assert kw.get("probe_window") == (2 * WINDOW if control in ("grep", "recent_window") else None)


@pytest.mark.parametrize("control", ANCHORS)
def test_missing_anchor_spec_refuses_before_any_send_without_sockets(control_scenario, monkeypatch, control):
    s, reads = control_scenario, []

    def missing():
        reads.append(control)
        raise FileNotFoundError("synthetic missing anchor spec")

    def sent(ctx, queued, live, **kw):
        # Regression probe: a late metadata read reaches this in-process fake reader, never a socket.
        live.respond(Call("probe_main", "", "chat", {"messages": []}, t2.MODEL, None, "synthetic"))
        raise RuntimeError("synthetic stop after first request")

    monkeypatch.setattr(control_arm, "header", missing)
    monkeypatch.setattr(t2, "schedule", sent)
    assert s.invoke(control=control) == 70
    assert not [call for stack in s.stacks for call in stack.calls]
    assert not s.stacks
    assert reads == [control]
    assert read(s.out, "refusal.json") == {"code": "tool_failure"}


@pytest.mark.parametrize("control", ["no_memory", *TEXT_ARMS])
def test_c_runner_hands_each_arm_the_floors_life_inputs(control_scenario, control):
    s = control_scenario
    assert s.invoke("base") == 0
    floor = {(kw["life_dir"].name, kw["branch"]): kw for kw in s.lives if kw["arm"] == "no_memory"}
    s.lives.clear()
    assert s.invoke(control=control) == 0
    arm = {(kw["life_dir"].name, kw["branch"]): kw for kw in s.lives}
    assert set(arm) == set(floor) and len(arm) == 4

    def same(kw):
        # The live stack and run id are per run; the scratch path names the arm (runner/units.py make_units).
        return {k: v for k, v in kw.items() if k not in (
            "live", "run", "voids", "scratch", "probe_blocks", "probe_window", "gate", "current_lock")}

    for unit, kw in arm.items():
        assert same(kw) == same(floor[unit])
        # Per-unit wrappers: the same lock, and the session gate keyed by the arm's run-local key.
        assert kw["current_lock"]() == floor[unit]["current_lock"]()
        assert (kw["gate"].key, floor[unit]["gate"].key) == (control, "no_memory")
        assert type(kw["voids"]) is type(floor[unit]["voids"])
        assert kw["scratch"].parts[-4:] == (control, *floor[unit]["scratch"].parts[-3:])
        assert ("probe_blocks" in kw) == (control != "no_memory")
        assert ("probe_window" in kw) == (control in ("grep", "recent_window"))


@pytest.mark.parametrize("control", ["no_memory", *TEXT_ARMS])
def test_d_another_live_role_refuses_a_control_arm(control_scenario, monkeypatch, control):
    s = control_scenario
    drive_life = units.run_life

    def breach(**kw):
        run = drive_life(**kw)
        return replace(run, records=(*run.records, {"role": "replay_main", "served_by": "live"}))

    monkeypatch.setattr(units, "run_life", breach)
    assert s.invoke(control=control) == 3
    assert read(s.out, "refusal.json") == {"code": "isolation"}


@pytest.mark.parametrize("control", ["no_memory", *TEXT_ARMS])
def test_e_control_arm_never_aliases_the_floor_cache(control_scenario, tmp_path, control):
    s, cache = control_scenario, tmp_path / "cache"
    assert s.invoke("floor", cache=cache) == 0
    before = {p.name: p.read_bytes() for p in cache.iterdir()}
    assert len(before) == 4
    for n in range(2):
        s.executed.clear()
        assert s.invoke(f"arm{n}", control=control, cache=cache) == 0
        calls = s.stacks[-1].calls
        assert [c.role for c in calls] == ["probe_main"] * 4  # every unit sends; no identity check for a cache hit
        assert sorted(s.executed) == sorted(("no_memory", p.life, b) for p in s.ctx.packs for b in ("B0", "B1"))
        assert {p.name: p.read_bytes() for p in cache.iterdir()} == before
