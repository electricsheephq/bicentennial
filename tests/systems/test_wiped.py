"""S10 offline acceptance. The token reader below is a stand-in, not S04."""

import json
import runpy
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.bundle import bundle_outcome
from bicentennial.contracts.run import validate
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.director.responder import Reply
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HermesAdapter
from bicentennial.harness.hermes.config import hermes_config, write_config
from bicentennial.keyed import choice, uniform_int
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.spansearch import span_search
from bicentennial.sandbox.surfaces import NotEmpty, clone_tree, surface_hash, swap_in
from bicentennial.score.qa import parse_envelope, score_qa
from bicentennial.systems import controls
from bicentennial.systems.controls import (
    WIPED_LABEL,
    WipeOnWake,
    control_report,
    control_status,
    floor_mismatches,
    no_memory_cell,
)
from bicentennial.systems.registry import REGISTRY, SystemRefused, load

ROOT = Path(__file__).resolve().parents[2]
WORKER = Path(__file__).with_name("memory_worker.py")
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
compile_micro_life = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
SCRIPT = compile_micro_life(dict(LIFE, sessions=LIFE["sessions"][:5]))
PROBES = compile_micro_life(dict(LIFE, sessions=[]))
ENTRY = load(REGISTRY / "hermes-native.toml")
VOLATILE = ENTRY["surfaces"][0]["volatile_paths"]
ROUTES = {"routes": [{"system": "hermes-native", "segment": seg, "probe_model": "probe-model", "alias": alias,
                      "summariser": "summary-model", "vision": None, "served_by": "scripted"}
                     for seg, alias in (("seg0", "bicentennial-main"), ("seg1", "bicentennial-swap"))]}
FAULTS = [{"kind": "kill", "session": 5, "turn": 2}]
BASE, STEP, DAY, LOCK = 1_600_000_000, 60, 86400, "ab" * 32
TOKENS = ("6543", "JSON lines", "release/ember", "cache signing key")
COMPETITORS = ("5433", "logfmt", "release/ash", "TLS certificate")
EXAMPLES = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"]


def qa_items():
    template = json.loads((ROOT / "schemas/fixtures/gen/item.json").read_bytes())
    items = []
    users = [t["user"] for s in SCRIPT["sessions"] if s["kind"] == "replay" for t in s["turns"]]
    for i, (gold, competitor) in enumerate(zip(TOKENS, COMPETITORS, strict=True)):
        assert sum(gold in text for text in users) == 1
        assert not any(competitor in text for text in users)
        item = deepcopy(template)
        item.update(item_id=f"Q{i + 1}", cell_id=("RECALL-VERB", "RECALL-HOP")[i // 2], stage="remember",
                    memory_tag="memory_exclusive")
        for option, token in zip(item["options"], (gold, competitor, None), strict=True):
            option["tokens"] = [token] if token else []
            option["envelope"] = {"type": "entity" if token else "unknown", "value": token,
                                  "confidence_milli": 1000 if token else 0}
        item["gold"]["never_observed"] = False
        validate("item", item)
        items.append(item)
    return items


ITEMS = qa_items()


class TokenReaderStandIn(ScriptedResponder):
    """Select the first complete token option in the actual request; never S04."""

    def respond(self, call):
        if call.role == "probe_main":
            i = (call.cursor["session"] - self.probe_start) * 2 + call.cursor["turn"] - 1
            text = "".join(str(m.get("content") or "") for m in call.body["messages"])
            item = ITEMS[i]
            selected = next((o for o in item["options"] if o["tokens"]
                             and all(t in text for t in o["tokens"])), item["options"][-1])
            return Reply(200, "probe", "scripted", call.model, text=canon(selected["envelope"]).decode())
        return super().respond(call)

    def __init__(self, probe_start=6):
        super().__init__(ENTRY)
        self.probe_start = probe_start


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.05)
    for name in ("BICENTENNIAL_BUSY_CMD", "BICENTENNIAL_OPERATOR"):
        monkeypatch.delenv(name, raising=False)


def make(scratch, name, *, script=SCRIPT, faults=FAULTS, hook=None, floor=False, **kw):
    root = scratch / name
    root.mkdir()
    kw.setdefault("worker_argv", [sys.executable, str(WORKER)])
    kw.setdefault("harness_pin", dict(ENTRY["artifact"]))
    kwargs = dict(script=script, route_table=RouteTable.load(ROUTES), schedule=FaultLite.load(faults, script),
                  responder=TokenReaderStandIn(next(s["index"] for s in script["sessions"] if s["kind"] == "probe")
                                               if any(s["kind"] == "probe" for s in script["sessions"]) else 6),
                  clock=SimClock(root / "clock.json", BASE, STEP), root=root, scratch=scratch,
                  life="s6a-micro", branch="B0", run=f"run-{name}", gate_poll_s=0, **kw)
    a = no_memory_cell(**kwargs) if floor else HermesAdapter(ENTRY, before_spawn=hook, **kwargs)
    (a.paths["hermes_home"] / ".bicentennial-sandbox").touch()
    return a


def session(a, index):
    result = a.run_session(index, sim_t_s=BASE + index * DAY, lock_hash=LOCK, attempt_id=f"attempt-s{index}")
    expected = hermes_config(a.server.port, a._alias, memory=a.memory)
    assert (a.paths["hermes_home"] / "config.yaml").read_bytes() == canon(expected) + b"\n"
    return result


def request_bodies(a):
    store = BlobStore(a.paths["root"] / "ledger/blobs", Guard([]))
    return [json.loads(store.get(r["req"])) for r in a.records() if r.get("type") == "request"]


def outcomes(results):
    finals = [text for r in results if r.kind == "probe" for _, text in r.finals]
    assert len(finals) == 4
    rows = []
    for item, text in zip(ITEMS, finals, strict=True):
        env = parse_envelope(text)
        scored = score_qa(item, env, evidence_texts=())
        selected = next(o["option_id"] for o in item["options"] if o["envelope"]["value"] == env["value"])
        row = dict(deepcopy(EXAMPLES["item_outcome"]), item_id=item["item_id"], cell_id=item["cell_id"],
                   envelope=env, selected_option=selected, score_milli=scored.score_milli,
                   worst_case_milli=scored.score_milli)
        validate("item_outcome", row)
        rows.append(row)
    bundles = []
    for a, b in ((rows[0], rows[1]), (rows[2], rows[3])):
        row = dict(deepcopy(EXAMPLES["bundle_outcome"]), bundle_id=f"bundle-{a['cell_id']}",
                   cell_id=a["cell_id"], items=[a["item_id"], b["item_id"]], **bundle_outcome(a, b))
        validate("bundle_outcome", row)
        bundles.append(row)
    return rows, bundles


def checked_hook(root, hook, observed):
    def wrapped(reason):
        home, workspace = root / "home", root / "workspace"
        before = (surface_hash(home, []), surface_hash(workspace, []), sha256(WORKER.read_bytes()).hexdigest())
        wiped = hook(reason)
        after = (surface_hash(home, []), surface_hash(workspace, []), sha256(WORKER.read_bytes()).hexdigest())
        assert before == after
        if wiped:
            hermes = root / "hermes-home"
            assert surface_hash(hermes, VOLATILE) == hook.fresh_install_hashes[0]
            assert not any(span_search(hermes, [t.encode() for t in TOKENS]).values())
            assert tree_listing(hermes, VOLATILE) == tree_listing(root / "control/fresh-0", VOLATILE)
        observed.append((reason, wiped))
        return wiped
    return wrapped


def run_arm(tmp_path, name, kind, *, leak=False):
    root, observed = tmp_path / name, []
    hook = WipeOnWake(ENTRY, {"HERMES_HOME": root / "hermes-home"}, root / "control") if kind == "wiped" else None
    wrapped = checked_hook(root, hook, observed) if hook else lambda reason: observed.append((reason, None))
    a = make(tmp_path, name, script=PROBES if kind == "floor" else SCRIPT,
             faults=[] if kind == "floor" else FAULTS, hook=wrapped, floor=kind == "floor")
    if leak:
        (a.paths["workspace"] / "leak-to-home").touch()
    try:
        results = [session(a, s["index"]) for s in a.script["sessions"]]
        rows, bundles = outcomes(results)
        if kind == "floor":
            assert a.harness_record()["memory"] is False
            bodies = request_bodies(a)
            assert bodies
            for body in bodies:
                assert not {"memory", "session_search"} & {t["function"]["name"] for t in body.get("tools", [])}
        return a.stable_digest(), rows, bundles, hook, results, observed
    finally:
        a.close()


def stripped(records):
    return [{**r, "surfaces": [{k: v for k, v in s.items() if not k.endswith("hash")}
                               for s in r["surfaces"]]} for r in records]


def test_fixture_arms_floor_leak_and_determinism(tmp_path):
    system = run_arm(tmp_path, "system", "system")
    wiped = run_arm(tmp_path, "wiped", "wiped")
    floor = run_arm(tmp_path, "floor", "floor")
    again = run_arm(tmp_path, "again", "wiped")
    leak = run_arm(tmp_path, "leak", "wiped", leak=True)
    for arm, expected in ((system, 1000), (wiped, 0), (floor, 0), (leak, 1000)):
        assert [r["score_milli"] for r in arm[1]] == [expected] * 4
        assert [r["score_milli"] for r in arm[2]] == [expected] * 2
    ids = [b["bundle_id"] for b in wiped[2]]
    assert floor_mismatches(wiped[2], floor[2], ids) == ()
    assert floor_mismatches(leak[2], floor[2], ids) == tuple(sorted(ids))
    assert control_status("FAIL", [r["score_milli"] == 1000 for r in system[1]]) == "FAIL"
    assert wiped[5] == [("session_start", False), *[("session_start", True)] * 4, ("kill", True),
                         ("session_start", True), ("session_start", True)]
    assert [r.reset for r in wiped[4]] == [None] + ["control_wipe"] * 6
    assert wiped[4][4].restarts[0]["history_after"] == 0
    assert wiped[:3] == again[:3]
    assert stripped(wiped[3].records()) == stripped(again[3].records())
    report = control_report([wiped[3], leak[3]], floor_mismatches(leak[2], floor[2], ids))
    assert canon(report) and report["label"] == WIPED_LABEL and report["canary"] == controls.CANARY
    assert report["floor_mismatches"] == sorted(ids)
    assert report["wipes"] == [wiped[3].records(), leak[3].records()]
    reader = TokenReaderStandIn(1)
    for i, item in enumerate(ITEMS):
        reply = reader.respond(SimpleNamespace(role="probe_main", cursor={"session": 1 + i // 2, "turn": 1 + i % 2},
                                                body={"messages": []}, model="probe-model"))
        env = parse_envelope(reply.text)
        assert env["type"] == "unknown" and score_qa(item, env, evidence_texts=()).score_milli == 0


def test_swap_wakes_restore_install_before_current_config(tmp_path):
    script = compile_micro_life(dict(LIFE, sessions=LIFE["sessions"][:4], probes=[]))
    faults = [{"kind": "kill", "session": 2, "turn": 2}, {"kind": "restart", "session": 3, "turn": 3},
              {"kind": "swap", "session": 4, "turn": None}]
    root, seen = tmp_path / "swap", []
    hook = WipeOnWake(ENTRY, {"HERMES_HOME": root / "hermes-home"}, root / "control")
    a = make(tmp_path, "swap", script=script, faults=faults, hook=checked_hook(root, hook, seen))
    try:
        results = [session(a, i) for i in range(1, 5)]
        assert [r.finals_matched for r in results] == [5] * 4
        assert json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())["model"]["default"] == "bicentennial-swap"
    finally:
        a.close()
    assert [reason for reason, _ in seen] == ["session_start", "session_start", "kill", "session_start", "restart",
                                            "session_start"]
    assert all(s["post_wipe_hash"] == s["fresh_install_hash"] for r in hook.records()[1:] for s in r["surfaces"])


def fresh(tmp_path, entry=ENTRY, control=None):
    home = tmp_path / "hermes-home"
    home.mkdir()
    (home / ".bicentennial-sandbox").touch()
    return home, WipeOnWake(entry, {"HERMES_HOME": home}, control or tmp_path / "control")


def test_keyed_wipe_property_200_cases(tmp_path):
    kinds = ("file", "nested", "symlink", "readonly", "logs", "config.yaml")
    for c in range(200):
        root = tmp_path / str(c)
        root.mkdir()
        home, hook = fresh(root)
        assert hook.fresh_install_hashes == () and hook.records() == () and hook.label == WIPED_LABEL
        assert hook("session_start") is False
        unit = ("s10", "wipe", str(c))
        count = uniform_int("s10", unit, 0, "count", 1, 6)
        nonces = []
        for n in range(count):
            kind = choice("s10", unit, 0, f"kind-{n}", kinds)
            nonce = f"planted-{c}-{n}-{uniform_int('s10', unit, 0, f'bytes-{n}', 0, 2**64)}".encode()
            nonces.append(nonce)
            path = home / f"entry-{n}"
            if kind == "symlink":
                path.symlink_to(nonce.decode())
            elif kind in ("nested", "readonly", "logs"):
                path = home / "logs" / str(n) if kind == "logs" else path
                path.mkdir(parents=True)
                (path / "payload").write_bytes(nonce)
                if kind == "readonly":
                    path.chmod(0o555)
            else:
                (home / "config.yaml" if kind == "config.yaml" else path).write_bytes(nonce)
        assert hook(choice("s10", unit, 0, "wake", controls.WAKE_REASONS)) is True
        assert surface_hash(home, VOLATILE) == hook.fresh_install_hashes[0]
        assert not any(span_search(home, nonces).values())
        assert tree_listing(home, []) == tree_listing(root / "control/fresh-0", [])
        assert canon(hook.records())
        detached = hook.records()
        detached[0]["surfaces"].clear()
        assert hook.records()[0]["surfaces"]


@pytest.mark.parametrize("reason", ["kill", "restart", "crash"])
def test_first_reason_refused_without_files(tmp_path, reason):
    home, hook = fresh(tmp_path)
    with pytest.raises(ValueError):
        hook(reason)
    assert not (tmp_path / "control").exists()


def test_construction_refusals(tmp_path):
    with pytest.raises(ValueError):
        WipeOnWake(load(REGISTRY / "no-memory.toml"), {}, tmp_path / "c")
    with pytest.raises(SystemRefused, match="licence_not_osi"):
        WipeOnWake(dict(ENTRY, licence="Proprietary"), {}, tmp_path / "c")
    with pytest.raises(ValueError, match="root"):
        WipeOnWake(ENTRY, {}, tmp_path / "c")
    hook = WipeOnWake(ENTRY, {"HERMES_HOME": tmp_path / "not-created"}, tmp_path / "c")
    assert list(tmp_path.iterdir()) == [] and hook.records() == ()


@pytest.mark.parametrize("bad", ["unmarked", "marker-link", "marker-directory", "memory", "config", "existing",
                                  "overlap", "ancestor", "surface-link", "missing", "dangling-control"])
def test_first_call_refusals(tmp_path, bad):
    home, hook = fresh(tmp_path)
    marker, control = home / ".bicentennial-sandbox", tmp_path / "control"
    if bad == "unmarked":
        marker.unlink()
    elif bad == "marker-link":
        marker.unlink()
        marker.symlink_to("absent")
    elif bad == "marker-directory":
        marker.unlink()
        marker.mkdir()
    elif bad == "memory":
        (home / "memories").mkdir()
        (home / "memories/MEMORY.md").write_text("state")
    elif bad == "config":
        write_config(home, hermes_config(4321, "bicentennial-main"))
    elif bad == "existing":
        control.mkdir()
    elif bad in ("overlap", "ancestor"):
        control = home / "control" if bad == "overlap" else tmp_path
        hook = WipeOnWake(ENTRY, {"HERMES_HOME": home}, control)
    elif bad == "surface-link":
        home.rename(tmp_path / "actual")
        home.symlink_to(tmp_path / "actual", target_is_directory=True)
    elif bad == "missing":
        marker.unlink()
        home.rmdir()
    else:
        control.symlink_to("absent")
    with pytest.raises(ValueError):
        hook("session_start")
    assert hook.records() == ()
    if bad not in ("existing", "ancestor", "dangling-control"):
        assert not control.exists()


def test_noop_wipe_raises_before_spawn(tmp_path, monkeypatch):
    home, hook = fresh(tmp_path)
    hook("session_start")
    (home / "state").write_text("not fresh")
    monkeypatch.setattr(controls, "wipe_to_fresh", lambda *args: None)
    with pytest.raises(NotEmpty):
        hook("restart")
    with pytest.raises(ValueError):
        hook("crash")
    root = tmp_path / "adapter"
    hook = WipeOnWake(ENTRY, {"HERMES_HOME": root / "hermes-home"}, root / "control")
    a = make(tmp_path, "adapter", hook=hook)
    try:
        session(a, 1)
        spawned = list(a.pids)
        with pytest.raises(NotEmpty):
            session(a, 2)
        assert a.pids == spawned
    finally:
        a.close()


def test_hook_config_write_is_replaced(tmp_path):
    home = tmp_path / "config" / "hermes-home"

    def write_wrong_config(reason):
        write_config(home, {"wrong": reason})
        return False

    a = make(tmp_path, "config", hook=write_wrong_config)
    try:
        result = session(a, 1)
        assert result.finals_matched == 5
    finally:
        a.close()


def test_no_memory_config_and_cell_refusals():
    default = hermes_config(4321, "bicentennial-main")
    disabled = hermes_config(4321, "bicentennial-main", memory=False)
    assert disabled["memory"] == {"memory_enabled": False, "user_profile_enabled": False, "provider": ""}
    assert disabled["platform_toolsets"] == {"acp": ["todo"]}
    assert all(canon(value) == canon(default[key]) for key, value in disabled.items()
               if key not in ("memory", "platform_toolsets"))
    assert canon(default) == canon(hermes_config(4321, "bicentennial-main", memory=True))
    with pytest.raises(ValueError):
        hermes_config(4321, "bicentennial-main", plugin="holographic", memory=False)
    with pytest.raises(ValueError, match="probe-only"):
        no_memory_cell(script=SCRIPT)


def test_probe_only_floor_routes_to_base_segment():
    schedule = FaultLite.load([], PROBES)
    first_probe = PROBES["sessions"][0]["index"]
    assert schedule.replay_prefix(first_probe) == ()
    assert RouteTable.load(ROUTES).resolve("hermes-native", first_probe, schedule)["segment"] == "seg0"


@pytest.mark.parametrize(("gate", "recall", "expected"), [
    ("PASS", [], "PASS"), ("CONFORMANCE_PASS", [True], "PASS"), ("FAIL", [], "uninformative"),
    ("FAIL", [False, False], "uninformative"), ("FAIL", [False, True], "FAIL")])
def test_status(gate, recall, expected):
    assert control_status(gate, iter(recall)) == expected


def test_floor_refusals_and_failure_class():
    b = deepcopy(EXAMPLES["bundle_outcome"])
    with pytest.raises(ValueError):
        control_status("INVALID", [True])
    for wiped, floor in (([b, b], [b]), ([b], [b, b]), ([], [b]), ([b], [])):
        with pytest.raises(ValueError):
            floor_mismatches(iter(wiped), iter(floor), [b["bundle_id"]])
    with pytest.raises(ValueError):
        floor_mismatches([dict(b, score_milli=1001)], [b], [])
    assert floor_mismatches([dict(b, score_milli=0, failure_class="SYSTEM_FAILURE")],
                           [dict(b, score_milli=0)], [b["bundle_id"]]) == (b["bundle_id"],)


def test_multiple_surfaces_disjointness_and_parked_original(tmp_path):
    home, _ = fresh(tmp_path)
    extra = tmp_path / "server"
    extra.mkdir()
    (extra / ".bicentennial-sandbox").touch()
    entry = deepcopy(ENTRY)
    entry["surfaces"].append({"root": "SERVER_DATA", "relative": ".", "volatile_paths": []})
    for other in (home, home / "nested"):
        hook = WipeOnWake(entry, {"HERMES_HOME": home, "SERVER_DATA": other}, tmp_path / "control")
        with pytest.raises(ValueError, match="disjoint"):
            hook("session_start")
        assert not (tmp_path / "control").exists()
    hook = WipeOnWake(entry, {"HERMES_HOME": home, "SERVER_DATA": extra}, tmp_path / "control")
    hook("session_start")
    (home / "original-state").write_text("parked")
    clone = tmp_path / "clone"
    clone_tree(home, clone)
    (extra / "state").write_text("server state")
    with swap_in(clone, home):
        hook("restart")
        assert not (home / "original-state").exists() and not (extra / "state").exists()
        assert len(hook.records()[-1]["surfaces"]) == 2
    assert (home / "original-state").read_text() == "parked"
