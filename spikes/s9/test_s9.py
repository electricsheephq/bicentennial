"""Offline S9 primitives; synthetic roots and responder stubs only."""

import ast
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_s9 as s9

from bicentennial.canon import canon
from bicentennial.director.responder import Call, Reply
from bicentennial.director.upstream import Upstream
from bicentennial.keyed import choice, uniform_int
from bicentennial.sandbox.surfaces import surface_hash
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.systems.settle import SettleResult


class FakeAdapter:
    def __init__(self, root):
        self.paths = {k: root / v for k, v in (("hermes_home", "hermes-home"), ("home", "home"),
                                              ("workspace", "workspace"), ("tmp", "tmp"))}
        for directory in self.paths.values():
            directory.mkdir(parents=True)
        home = self.paths["hermes_home"]
        (home / ".bicentennial-sandbox").touch()
        (home / "memories").mkdir()
        (home / "memories/MEMORY.md").write_text("saved note")
        (home / "logs").mkdir()
        (home / "logs/a").write_text("volatile")
        self._worker = None
        self.ran = []
        self.rows = []

    def run_session(self, index, **kwargs):
        self.ran.append(index)
        return SimpleNamespace(session=index, kind="replay", turns_ok=1, finals_matched=1,
                               summariser_records=0, reset=None, end_threads=(), gate=(),
                               surface_hash=surface_hash(self.paths["hermes_home"], ["logs", ".mcp-discovery.lock"]))

    def records(self):
        return self.rows

    def stable_digest(self):
        return "ab" * 32


@pytest.fixture
def arm(tmp_path):
    adapter = FakeAdapter(tmp_path)
    entry = load(REGISTRY / "hermes-native.toml")
    digest = surface_hash(adapter.paths["hermes_home"], entry["surfaces"][0]["volatile_paths"])
    return s9.Arm(adapter, entry, after=1, surface_hash=digest)


def test_firewall():
    assert s9.ARMS == ("hermes-native", "mem0-oss", "wiped", "no-memory")
    tree = ast.parse(Path(s9.__file__).read_text())
    allowed = {"canon", "keyed", "contracts.surfaces", "contracts.run", "sandbox.surfaces", "sandbox.spansearch",
               "ledger", "runtime.clock", "runtime.faultlite", "director.routes", "director.responder",
               "director.scripted", "director.upstream", "director.upstream.login", "harness.hermes.adapter",
               "runner.guard", "runner.spend", "systems.registry", "systems.hermes_plugin", "systems.settle",
               "systems.controls"}
    for node in ast.walk(tree):
        names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                 [a.name for a in node.names] if isinstance(node, ast.Import) else [])
        for name in names:
            assert not name.startswith(("spikes", "tests")) and "lcm" not in name
            if name.startswith("bicentennial."):
                assert name.removeprefix("bicentennial.") in allowed
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            assert name != "install_placeholder"


def test_zero_spend(tmp_path):
    spend = s9.zero_spend(tmp_path / "spend.json")
    assert spend.policy == {"cap": 0, "price": {"input_per_million": 0, "output_per_million": 0}}
    with pytest.raises(ValueError):
        Upstream("sol", "model", "https://unit.invalid", "responses", spend, s9.Price(1, 0), 100)
    rid = spend.reserve(10**6, 10**6, s9.Price(0, 0))
    assert rid is not None
    assert spend.settle(rid, {"prompt_tokens": 10**6, "completion_tokens": 10**6})[0] == 0
    with spend.locked() as state:
        assert state["settled"] == 0 and state["open"] == {}


def test_public_scripts():
    replay, probes = s9.micro_script(), s9.micro_script(probes_only=True)
    assert len(replay["sessions"]) == 10 and len(probes["sessions"]) == 2
    assert sum(len(s["turns"]) for s in replay["sessions"]) == 60
    assert {s["kind"] for s in replay["sessions"]} == {"replay"}
    assert {s["kind"] for s in probes["sessions"]} == {"probe"}
    assert len(s9.micro_script(sessions=[1, 2, 3, 4])["sessions"]) == 4
    system, control, nonces = s9.canary_scripts("r")
    assert (system, control, nonces) == s9.canary_scripts("r")
    assert len(set(nonces)) == 3
    for nonce in nonces:
        assert re.fullmatch(r"bcw-[0-9a-f]{16}", nonce)
        assert canon(system).count(nonce.encode()) == 1 and nonce.encode() not in canon(control)


def test_nonce_hashseed_independent():
    code = "import run_s9 as s; print(s.canary_scripts('r')[2])"
    outputs = []
    for seed in ("0", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, "-c", code], cwd=Path(s9.__file__).parent, env=env))
    assert outputs[0] == outputs[1]


def test_canary_verdicts(arm):
    _, _, nonces = s9.canary_scripts("r")
    sent = [" ".join(nonces).encode()]
    assert s9.canary_result(sent, [], nonces, live_probes=[1, 2, 3])["verdict"] == "pass"
    assert s9.canary_result(sent, [nonces[0]], nonces, live_probes=[1, 2, 3])["verdict"] == "fail"
    assert s9.canary_result([nonces[0], nonces[1]], [], nonces)["verdict"] == "vacuous"
    assert s9.canary_result(sent, [], nonces)["verdict"] == "incomplete"
    assert s9.canary_result(sent, [], nonces, live_probes=[1, 2])["verdict"] == "incomplete"
    home = arm.adapter.paths["hermes_home"]
    assert s9.canary_surface_replies(home, nonces) == []
    (home / "memories/MEMORY.md").write_text(nonces[1])
    assert s9.canary_surface_replies(home, nonces) == [nonces[1].encode("ascii")]


@pytest.mark.parametrize(("key", "relative", "expected"), [
    ("hermes_home", "memories/MEMORY.md", ["HERMES_HOME/.:memories/MEMORY.md"]),
    ("hermes_home", "logs/b", []), ("workspace", "x", ["workspace:x"]), ("tmp", "y", ["tmp:y"]),
])
def test_proof_changes(arm, key, relative, expected):
    def sleep(seconds):
        assert seconds == 120 and arm.adapter._worker is None
        (arm.adapter.paths[key] / relative).write_text("changed")

    proof = s9.pause_proof(arm, 120, sleep)
    assert proof["changed"] == expected and proof["equal"] == (not expected)
    assert proof["declared_matches"]
    assert proof["after"] == 1 and type(proof["pause_s"]) is int
    canon(proof)


def test_proof_unchanged_and_alive(arm):
    proof = s9.pause_proof(arm, 0, lambda _: None)
    assert proof["equal"] and proof["changed"] == [] and proof["declared_matches"]
    arm.adapter._worker = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None))
    with pytest.raises(s9.BoundaryBlocked, match="harness_alive") as exc:
        s9.boundary(arm, 0)
    assert exc.value.exit_code == 2


def test_keyed_surface_property_200(arm):
    """Every case draws the root, path and operation independently under K10."""
    keys = ("hermes_home", "home", "workspace", "tmp")
    names = {"hermes_home": "HERMES_HOME/.", "home": "home", "workspace": "workspace", "tmp": "tmp"}
    for case in range(200):
        unit = ("case", str(case))
        key = choice("p09", unit, 0, "root", keys)
        relative = choice("p09", unit, 0, "relative", ("logs/item", ".mcp-discovery.lock/item", "data/item"))
        number = uniform_int("p09", unit, 0, "number", 0, 1000)
        relative = relative.replace("item", str(number))
        operation = choice("p09", unit, 0, "operation", ("add", "edit", "remove"))
        path = arm.adapter.paths[key] / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if operation == "add":
            path.unlink(missing_ok=True)
        else:
            path.write_text("before")

        def mutate(_, operation=operation, path=path):
            if operation == "remove":
                path.unlink()
            else:
                path.write_text("after")

        proof = s9.pause_proof(arm, 0, mutate)
        volatile = key == "hermes_home" and relative.split("/")[0] in ("logs", ".mcp-discovery.lock")
        assert proof["equal"] is volatile, (case, key, relative, operation)
        assert proof["changed"] == ([] if volatile else [f"{names[key]}:{relative}"])


def test_multi_surface_crosscheck_and_settle(arm):
    arm.entry = load(REGISTRY / "mem0-oss.toml")
    (arm.adapter.paths["home"] / ".mem0").mkdir()
    calls = []

    def declared_hash():
        return s9.sha256_canon([
            {"root": s["root"], "relative": s["relative"], "tree_hash": surface_hash(directory, volatile)}
            for s, (_, directory, volatile) in zip(arm.entry["surfaces"], s9.proof_roots(arm), strict=False)
        ])

    arm.cell = SimpleNamespace(surface_hash=declared_hash,
                               settle=lambda: SettleResult("hook", True, 1, "drained", 0),
                               checkpoint=lambda: calls.append("checkpoint"))
    proof = s9.boundary(arm, 0, lambda _: calls.append("sleep"))
    assert proof["equal"] and proof["declared_matches"]
    assert calls == ["checkpoint", "sleep"]
    assert list(proof["pause"]) == ["HERMES_HOME/.", "SANDBOX_HOME/.mem0", "home", "workspace", "tmp"]
    arm.cell.settle = lambda: SettleResult("hook", False, 21, "bound_reached", 5000)
    arm.cell.checkpoint = lambda: pytest.fail("unsettled cell must not checkpoint")
    proof = s9.boundary(arm, 0, lambda _: pytest.fail("unsettled boundary must not wait"))
    assert proof["pause"] == "unsettled" and "equal" not in proof


def test_admission():
    base = {"identity_drift": None, "stopped": False, "spend_stopped": False}
    cases = [("identity_drift", {"model": "m"}, "identity_drift"),
             ("stopped", True, "responder_stopped:reason"), ("spend_stopped", True, "spend_stop"),
             ("login_stop", "reason", "login_stop")]
    for key, value, expected in cases:
        assert s9.admission_stop(dict(base, **{key: value}, stop_reason="reason"), {}, 0, "live") == expected
    assert s9.admission_stop(base, {"reasons": ["quota"]}, 0, "live") == "hold:quota"
    assert s9.admission_stop(base, {"reasons": ["rate"]}, 0, "live") is None
    assert s9.admission_stop(base, {}, 10801, "live") == "budget"
    assert s9.admission_stop(base, {}, 10800, "live") is None


@pytest.mark.parametrize(("counts", "after"), [([0, 0, 1, 0], 3), ([0, 1, 0, 0], 2),
                                              ([0, 0, 0, 0], None), ([0, 0, 0, 1], None)])
def test_pause_requires_retained_compaction(counts, after):
    total = 0
    selected = None
    for index, count in enumerate(counts, 1):
        total += count
        if s9.should_pause(index, len(counts), total):
            selected = index
            break
    assert selected == after


class Stub:
    def __init__(self):
        self.calls = []

    def respond(self, call):
        self.calls.append(call)
        return Reply(200, "stub", "live", call.model, text="reply", tool_calls=({"name": "memory", "arguments": "{}"},),
                     usage={"input_tokens": 10, "output_tokens": 3})

    def state(self):
        return {"identity_drift": None}

    def served_identities(self):
        return {"model": "served"}


def test_split_routes():
    live, scripted = Stub(), Stub()
    responder = s9.SplitResponder(live, scripted)
    routes = [("embeddings", "embedding"), ("aux", "extraction"), ("write_turn", "write_turn"),
              ("probe_main", "cursor"), ("summariser", "compaction"), ("aux", "title")]
    for role, subrole in routes:
        responder.respond(Call(role, subrole, "chat", {}, "model", None, "r"))
    assert [(c.role, c.subrole) for c in scripted.calls] == routes[:2]
    assert [(c.role, c.subrole) for c in live.calls] == routes[2:]
    assert responder.state() == live.state()
    assert responder.served_identities() == live.served_identities()


def test_hermes_chat_through_bridge():
    stub = Stub()
    bridge = s9.ResponsesBridge(stub)
    body = {"model": "bicentennial-main", "messages": [{"role": "system", "content": "fake harness"},
            {"role": "user", "content": "opening question"}],
            "tools": [{"type": "function", "function": {"name": name}} for name in ("memory", "session_search")]}
    call = Call("write_turn", "write_turn", "chat", body, "model", {"session": 1, "turn": 1}, "r")
    before = canon(body)
    reply = bridge.respond(call)
    sent = stub.calls[0]
    assert sent.wire == "responses" and sent.body["instructions"] == "fake harness"
    assert sent.body["input"] == [{"type": "message", "role": "user",
                                   "content": [{"type": "input_text", "text": "opening question"}]}]
    assert [t["name"] for t in sent.body["tools"]] == ["memory", "session_search"]
    assert reply.text == "reply" and reply.tool_calls == ({"name": "memory", "arguments": "{}"},)
    assert reply.usage == {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}
    assert canon(body) == before
    assert canon(sent.body) == canon(s9.to_responses(body))
    assert bridge.state() == stub.state() and bridge.served_identities() == stub.served_identities()
    other = Call("summariser", "", "responses", {}, "model", None, "r")
    bridge.respond(other)
    assert stub.calls[-1] is other


def test_bridge_tool_history_and_fail_closed():
    body = {"messages": [{"role": "system", "content": "one"}, {"role": "developer", "content": "two"},
            {"role": "assistant", "content": [{"type": "text", "text": "thinking"}],
             "tool_calls": [{"type": "function", "id": "c", "function": {"name": "memory", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c", "content": "saved"}],
            "tool_choice": {"type": "function", "function": {"name": "memory"}},
            "reasoning_effort": "low", "max_tokens": 1, "max_completion_tokens": 2,
            "parallel_tool_calls": False, "stream": True, "stream_options": {"include_usage": True}}
    converted = s9.to_responses(body)
    assert converted["instructions"] == "one\n\ntwo"
    assert [i["type"] for i in converted["input"]] == ["message", "function_call", "function_call_output"]
    assert converted["input"][0]["content"] == [{"type": "output_text", "text": "thinking"}]
    assert converted["input"][1]["call_id"] == converted["input"][2]["call_id"] == "c"
    assert converted["reasoning"] == {"effort": "medium"} and converted["store"] is False
    assert converted["tool_choice"] == {"type": "function", "name": "memory"}
    assert not {"max_tokens", "max_completion_tokens", "stream", "stream_options"} & converted.keys()
    with pytest.raises(ValueError, match="bridge_unmapped_key:logprobs"):
        s9.to_responses(dict(body, logprobs=True))
    with pytest.raises(ValueError, match="bridge_content_part"):
        s9.to_responses({"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": "fixture"}]}]})
    assert s9.chat_usage({"input_tokens": 1}) is None
    assert s9.chat_usage({"input_tokens": True, "output_tokens": 1}) is None


def test_life_stops_before_resume_on_mismatch(arm):
    def sleep(_):
        if arm.after == 2:
            (arm.adapter.paths["hermes_home"] / "memories/MEMORY.md").write_text("tampered")

    record, code = s9.run_life(arm, "twin", "r", {}, wait_s=120, sleep=sleep,
                               script=s9.micro_script(sessions=[1, 2, 3, 4]))
    assert record["sessions_run"] == [1, 2] and record["stop"] == "proof_failed" and code == 1
    assert record["boundaries"][-1]["changed"] == ["HERMES_HOME/.:memories/MEMORY.md"]


def test_life_unsettled_continues_four_sessions(arm):
    arm.cell = SimpleNamespace(settle=lambda: SettleResult("hook", False, 21, "bound_reached", 5000))
    record, code = s9.run_life(arm, "twin", "r", {}, wait_s=0,
                               sleep=lambda _: pytest.fail("unsettled pause must not sleep"),
                               script=s9.micro_script(sessions=[1, 2, 3, 4]))
    assert record["sessions_run"] == [1, 2, 3, 4] and code == 1
    assert len(record["boundaries"]) == 3
    assert all(b["pause"] == "unsettled" for b in record["boundaries"])


def test_life_identity_stop_and_flag(arm):
    def state():
        if arm.adapter.ran == [1, 2]:
            arm.adapter.rows = [{"attempt_id": "hermes-native-s2", "upstream": [
                {"diagnostics": [{"identity_changed": True}]}]}]
            return {"identity_drift": {"model": "m"}}
        return {"identity_drift": None}

    record, code = s9.run_life(arm, "live", "r", {}, wait_s=0, sleep=lambda _: None,
                               script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               responder=SimpleNamespace(state=state))
    assert record["sessions_run"] == [1, 2] and record["stop"] == "identity_drift" and code == 2
    assert record["flagged_sessions"] == [2]


@pytest.mark.parametrize(("state", "held", "reason"), [
    ({}, {"reasons": ["quota"], "held_ms": 5}, "hold:quota"),
    ({"login_stop": "fixture"}, {"reasons": [], "held_ms": 0}, "login_stop"),
])
def test_life_stops_on_live_boundary_admission(arm, state, held, reason):
    reads = iter([{}])  # clean before session 1, so the stop arrives at the first boundary
    record, code = s9.run_life(arm, "live", "r", {}, wait_s=0, sleep=lambda _: None,
                               script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               responder=SimpleNamespace(state=lambda: next(reads, state)),
                               holds=SimpleNamespace(at_boundary=lambda _: held))
    assert record["sessions_run"] == [1] and record["stop"] == reason and code == 2
    assert record["boundaries"][0]["holds"] == held


def test_life_all_equal(arm):
    record, code = s9.run_life(arm, "twin", "r", {}, wait_s=0, sleep=lambda _: None,
                               script=s9.micro_script(sessions=[1, 2, 3, 4]))
    assert record["sessions_run"] == [1, 2, 3, 4] and record["stop"] is None and code == 0
    assert len(record["boundaries"]) == 3
    assert all(b["equal"] and b["declared_matches"] for b in record["boundaries"])
    canon(record)


@pytest.mark.parametrize("name", ["lcm-x", "holographic"])
def test_cli_rejects_other_arms(name, tmp_path):
    with pytest.raises(SystemExit) as exc:
        s9.main(["twin", "--run", "r", "--out", str(tmp_path / "out"), "--arms", name])
    assert exc.value.code == 2


def test_cli_rejects_short_resume_and_spare(tmp_path):
    base = ["resume24", "--run", "r", "--out", str(tmp_path / "out"), "--max-output-tokens", "1024"]
    for extra in (["--wait-s", "86399"], ["--resume-auth", "deferred"], ["--arms", "wiped"]):
        with pytest.raises(SystemExit) as exc:
            s9.main(base + extra)
        assert exc.value.code == 2


@pytest.fixture
def idle_marker(monkeypatch, tmp_path):
    marker = tmp_path / "idle-marker.sh"
    marker.write_text("printf '%s' '{\"glm\":false,\"state\":\"fixture\"}'\nexit 0\n")
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", "sh " + str(marker))


@pytest.fixture
def preflight_env(monkeypatch, tmp_path, idle_marker):
    monkeypatch.setattr(s9, "reexec_niced", lambda _: None)
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    for key in ("BASE_URL", "TOKEN_URL", "CLIENT_ID", "AUTH"):
        monkeypatch.setenv("BICENTENNIAL_SOL_" + key, "synthetic-" + key)
    for name in ("HermesAdapter", "open_login"):
        monkeypatch.setattr(s9, name, lambda *a, **kw: pytest.fail("preflight constructed runtime"))
    return ["live", "--run", "r", "--out", str(tmp_path / "out"), "--max-output-tokens", "1024"]


@pytest.mark.parametrize("status", [10, 11, 1])
def test_preflight_marker_refuses_first(preflight_env, monkeypatch, tmp_path, status):
    marker = tmp_path / "marker.sh"
    marker.write_text(f"printf '%s' '{{\"glm\":false,\"state\":\"fixture\"}}'\nexit {status}\n")
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", "sh " + str(marker))
    monkeypatch.delenv("BICENTENNIAL_OPERATOR")
    with pytest.raises(SystemExit) as exc:
        s9.main(preflight_env)
    assert exc.value.code == 3 and not (tmp_path / "out").exists()


@pytest.mark.parametrize("cause", ["operator", "token_url", "existing", "pin"])
def test_preflight_never_opens_login(preflight_env, monkeypatch, tmp_path, capsys, cause):
    if cause == "operator":
        monkeypatch.delenv("BICENTENNIAL_OPERATOR")
    elif cause == "token_url":
        monkeypatch.delenv("BICENTENNIAL_SOL_TOKEN_URL")
    elif cause == "existing":
        (tmp_path / "out").mkdir()
    else:
        checkout = tmp_path / "checkout"
        (checkout / ".venv/bin").mkdir(parents=True)
        (checkout / ".venv/bin/python").touch()
        monkeypatch.setenv("BICENTENNIAL_HERMES", str(checkout))
        monkeypatch.setattr(s9, "verify_pin", lambda *a: (_ for _ in ()).throw(s9.PinMismatch("fixture")))
    with pytest.raises(SystemExit) as exc:
        s9.main(preflight_env)
    assert exc.value.code == 3
    stderr = capsys.readouterr().err
    assert "synthetic-" not in stderr
    if cause == "token_url":
        assert "BICENTENNIAL_SOL_TOKEN_URL" in stderr


def test_cli_hashseed_refused_before_everything(tmp_path):
    env = dict(os.environ)
    env.pop("PYTHONHASHSEED", None)
    proc = subprocess.run([sys.executable, s9.__file__, "twin", "--run", "r", "--out", str(tmp_path / "out")],
                          env=env, capture_output=True)
    assert proc.returncode == 70 and not (tmp_path / "out").exists()


def test_active_clock_shared_excludes_gate_and_pause_even_on_error():
    now = [0]
    active = s9.ActiveClock(lambda: now[0])
    now[0] += 3

    def delay(seconds):
        now[0] += seconds
    active.omit(delay, 120)
    assert active() == 3
    now[0] += 4

    def gate():
        delay(60)
        raise ValueError("fixture")
    with pytest.raises(ValueError):
        active.omit(gate)
    assert active() == 7
    active.omit(delay, 86400)
    now[0] += 2
    assert active() == 9


def ledger_fixture(arm, *, role="probe_main", attempt="hermes-native-s1", text="summary", status=200, sent=True):
    store = s9.BlobStore(arm.adapter.paths["root"] / "ledger/blobs", s9.Guard([]))
    body = {"messages": [{"role": "user", "content": text}]}
    req, resp = store.put(body), store.put({"text": text})
    arm.adapter.rows.append({"seq": len(arm.adapter.rows) + 1, "attempt_id": attempt, "req": req,
        "cursor": {"session": 1, "turn": 1},
        "upstream": [{"role": role, "status": status, "served_by": "live", "req": req, "resp": resp,
            "diagnostics": [{"kind": "try", "sent": sent, "status": status, "n_dropped_items": 2}]}]})
    return store


def test_ledger_observations_and_retained_summary(arm):
    arm.adapter.paths["root"] = arm.adapter.paths["home"].parent
    ledger_fixture(arm, role="summariser", text="retained summary")
    ev = s9.observations(arm.adapter)
    assert ev["summaries"] == ["retained summary"] and ev["dropped_items"] == 2
    assert ev["counts"] == {"tries": 1, "forwarded": 1, "refused": 0, "credential_stop": 0}
    ledger_fixture(arm, attempt="resumed", text="prefix retained summary suffix")
    assert s9.retained_summary(arm.adapter, "resumed", ev["summaries"])
    assert not s9.retained_summary(arm.adapter, "resumed", ["absent summary"])
    assert not s9.retained_summary(arm.adapter, "missing", ev["summaries"])
    ledger_fixture(arm, attempt="refused", status=401, sent=False)
    refused = s9.observations(arm.adapter, "refused")
    assert refused["live_probes"] == [] and refused["sent"] == []
    assert refused["counts"]["credential_stop"] == 1
    assert s9.observations(arm.adapter, "resumed")["live_probes"] == [1]


def test_resume24_reopens_compaction_and_checks_first_request(arm):
    arm.adapter.paths["root"] = arm.adapter.paths["home"].parent
    original, options = arm.adapter.run_session, []

    def session(index, **kwargs):
        options.append(kwargs.get("resume_session_id"))
        result = original(index, **kwargs)
        result.acp_session_id = "saved-session"
        result.summariser_records = int(index == 2)
        if index == 2:
            ledger_fixture(arm, role="summariser", attempt=kwargs["attempt_id"], text="retained summary")
        elif index == 3:
            ledger_fixture(arm, attempt=kwargs["attempt_id"], text="retained summary in history")
        return result

    arm.adapter.run_session = session
    waits = []
    record, code = s9.run_life(arm, "resume24", "r", {}, script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               wait_s=86400, sleep=waits.append)
    assert code == 0 and record["sessions_run"] == [1, 2, 3, 4]
    assert options == [None, None, "saved-session", None]
    assert waits == [0, 86400, 0]
    assert arm.resume_record["resumed_ok"] and arm.resume_record["pause_after"] == 2
    assert arm.resume_record["account_switched"] is False


def test_resume24_no_compaction_is_blocked(arm):
    record, code = s9.run_life(arm, "resume24", "r", {}, script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               wait_s=86400, sleep=lambda n: None)
    assert code == 2 and record["stop"] == "no_compaction" and arm.resume_record is None


@pytest.mark.parametrize("failure_index", [2, 3], ids=["pending", "proven"])
def test_harness_failure_preserves_resume_result(arm, failure_index):
    arm.adapter.paths["root"] = arm.adapter.paths["home"].parent
    original, options = arm.adapter.run_session, []
    proven = []

    def session(index, **kwargs):
        options.append(kwargs.get("resume_session_id"))
        if index == failure_index:
            if index == 3:
                proven.append(dict(arm.resume_record))
            raise s9.HarnessFailed("synthetic failure")
        result = original(index, **kwargs)
        result.acp_session_id = "saved-session"
        result.summariser_records = int(index == 1)
        ledger_fixture(arm, role="summariser" if index == 1 else "probe_main",
                       attempt=kwargs["attempt_id"], text="retained summary")
        return result

    arm.adapter.run_session = session
    record, code = s9.run_life(arm, "resume24", "r", {}, script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               wait_s=86400, sleep=lambda _: None)
    assert code == 1 and record["sessions_run"] == list(range(1, failure_index))
    assert record["stop"] == ("resume_failed" if failure_index == 2 else "harness_failed")
    assert options == ([None, "saved-session"] if failure_index == 2 else [None, "saved-session", None])
    assert arm.resume_record["resumed_ok"] is (failure_index == 3)
    if proven:
        assert arm.resume_record == proven[0]
    assert record["exit_holds"] == {}


FAILURE_EXITS = [
    ("proof_failed", 1), ("harness_alive", 2), ("compaction_not_retained", 1),
    ("compaction_unobserved", 2), ("compaction_unsettled", 2), ("harness_failed", 1),
]


@pytest.fixture
def failure_exit():
    """Arrange real run_life exits using the existing adapter and ledger fakes."""
    def configure(arm, stop):
        arm.adapter.paths["root"] = arm.adapter.paths["home"].parent
        original, attempts = arm.adapter.run_session, []
        compaction = stop.startswith("compaction_")
        last_index = 2 if stop == "compaction_not_retained" else 1

        def session(index, **kwargs):
            attempts.append(kwargs["attempt_id"])
            result = original(index, **kwargs)
            if stop == "harness_failed":
                raise s9.HarnessFailed("synthetic failure")
            if stop == "harness_alive":
                arm.adapter._worker = SimpleNamespace(proc=SimpleNamespace(poll=lambda: None))
            if stop == "proof_failed":
                result.surface_hash = "00" * 32
            if compaction:
                result.acp_session_id = "saved-session"
                result.summariser_records = int(index == 1)
                if stop != "compaction_unobserved":
                    ledger_fixture(arm, role="summariser" if index == 1 else "probe_main",
                                   attempt=kwargs["attempt_id"],
                                   text="retained summary" if index == 1 else "history missing")
            return result

        if stop == "compaction_unsettled":
            arm.cell = SimpleNamespace(settle=lambda: SettleResult("hook", False, 21, "bound_reached", 5000))
        arm.adapter.run_session = session
        return "resume24" if compaction else "live", last_index, attempts
    return configure


@pytest.mark.parametrize(("stop", "status"), FAILURE_EXITS)
@pytest.mark.parametrize("receipt", [
    {"reasons": ["quota"], "held_ms": 5}, {"reasons": [], "held_ms": 0}, None,
], ids=["quota", "empty", "no-holds"])
def test_failure_exit_reads_last_session_hold(arm, failure_exit, stop, status, receipt):
    part, last_index, attempts = failure_exit(arm, stop)
    arm.execution = "hermes-native.micro"
    reads = []

    def at_boundary(attempt):
        assert attempt == attempts[-1]
        reads.append(attempt)
        return receipt if attempt.endswith(f"-s{last_index}") else {"reasons": [], "held_ms": 0}

    record, code = s9.run_life(arm, part, "r", {}, script=s9.micro_script(sessions=[1, 2, 3, 4]),
        wait_s=0, sleep=lambda _: None,
        holds=SimpleNamespace(at_boundary=at_boundary) if receipt is not None else None)
    assert attempts == [f"hermes-native.micro-s{i}" for i in range(1, last_index + 1)]
    assert reads == (attempts if receipt is not None else [])
    assert record["exit_holds"] == (receipt if receipt is not None else {})
    if receipt and "quota" in receipt["reasons"]:
        expected_status = 1 if stop in {"compaction_not_retained", "proof_failed"} else 2
        assert record["stop"] == "hold:quota" and code == expected_status
        assert record["superseded_stop"] == stop
    else:
        assert record["stop"] == stop and code == status
        assert "superseded_stop" not in record


def test_summary_counts_and_hashes_only(tmp_path, monkeypatch):
    s9.write_result(tmp_path / "arms/hermes-native.micro.json", {"boundaries": [{"equal": True}],
                    "digest": "ab" * 32, "unknown_requests": 0, "private": str(tmp_path)})
    s9.write_result(tmp_path / "run.json", {"exit": 0, "sends": 4})
    summary = s9.summarise([tmp_path])
    assert summary["parts"][0]["files"] == 2 and summary["parts"][0]["arms"] == 1
    encoded = canon(summary).decode()
    assert str(tmp_path) not in encoded and "BICENTENNIAL_SOL" not in encoded
    monkeypatch.setenv("BICENTENNIAL_SOL_AUTH", "fake-store-value")
    assert s9.public("fake-store-value").startswith("sha256:")


@pytest.mark.parametrize("label", ["hermes-native", "wiped", "no-memory"])
def test_fake_worker_twins(tmp_path, monkeypatch, label, idle_marker):
    from bicentennial.harness.hermes import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    script = s9.micro_script(probes_only=label == "no-memory", sessions=None if label == "no-memory" else [1, 2, 3, 4])
    digests = []
    for suffix in ("u", "p"):
        arm, routes = s9.build_arm(label, tmp_path / suffix, script, "r", s9.ActiveClock(),
                                   worker_argv=[sys.executable, str(s9.ROOT / "tests/harness/fake_worker.py")])

        def wait(_, arm=arm):
            assert arm.adapter._worker.proc.poll() is not None
        try:
            record, code = s9.run_life(arm, "twin", "r", routes, script=script,
                                       wait_s=0 if suffix == "u" else 120, sleep=wait)
        finally:
            s9.finish_arm(arm, record)
        assert code == 0 and len(record["boundaries"]) == (1 if label == "no-memory" else 3)
        assert all(b["equal"] and b["declared_matches"] for b in record["boundaries"])
        if label == "wiped":
            assert [r["reset"] for r in record["results"]] == [None] + ["control_wipe"] * 3
        digests.append(record["digest"])
    assert digests[0] == digests[1], "STOP: fake-worker twin digest mismatch; do not change masks"


def test_fake_worker_proof_refuses_later_session(tmp_path, monkeypatch, idle_marker):
    from bicentennial.harness.hermes import adapter as adapter_module

    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    script = s9.micro_script(sessions=[1, 2, 3, 4])
    arm, routes = s9.build_arm("hermes-native", tmp_path / "negative", script, "r", s9.ActiveClock(),
                               worker_argv=[sys.executable, str(s9.ROOT / "tests/harness/fake_worker.py")])

    def wait(_):
        if arm.after == 2:
            home = arm.adapter.paths["hermes_home"]
            (home / "memories").mkdir(exist_ok=True)
            (home / "memories/MEMORY.md").write_text("changed during pause")
    try:
        record, code = s9.run_life(arm, "twin", "r", routes, script=script, wait_s=120, sleep=wait)
    finally:
        s9.finish_arm(arm, record)
    assert code == 1 and record["sessions_run"] == [1, 2]
    assert not any(r["attempt_id"] == "hermes-native-s3" for r in arm.adapter.records())


@pytest.mark.parametrize(("part", "expected"), [
    ("twin", ["hermes-native.micro-u", "hermes-native.micro-p", "wiped.micro-u", "wiped.micro-p",
              "no-memory.micro-u", "no-memory.micro-p"]),
    ("live", ["hermes-native.micro", "hermes-native.canary", "no-memory.canary", "wiped.micro", "no-memory.micro"]),
    ("resume24", ["hermes-native.micro"]),
])
def test_offline_orchestration_publication_and_execution_identity(tmp_path, monkeypatch, part, expected):
    args = SimpleNamespace(part=part, out=tmp_path / "out", run="synthetic", arms=["hermes-native", "wiped", "no-memory"],
                           mem0_source=None, max_output_tokens=1024, wait_s=86400, resume_auth=None)
    active_ids, constructed, closed = set(), [], []

    def build(label, root, script, run, active, **kwargs):
        assert len(constructed) == len(closed), "adapters must close before the next is constructed"
        active_ids.add(id(active))
        constructed.append(root.name)
        a = FakeAdapter(root)
        a.script = script
        original = a.run_session

        def session(index, **kw):
            result = original(index, **kw)
            result.finals = tuple((turn["n"], "clean answer") for turn in script["sessions"][index - 1]["turns"])
            return result
        a.run_session = session
        return s9.Arm(a, load(REGISTRY / "hermes-native.toml"), label=label), {}

    def finish(arm, record):
        closed.append(constructed[len(closed)])
        record.update(unknown_requests=0, non_loopback=0, auth_path_requests=0, digest="ab" * 32, ledger={})

    def observe(adapter, attempt=None):
        system, _, nonces = s9.canary_scripts(args.run)
        canary = adapter.script["life_id"] == system["life_id"]
        return {"sent": [" ".join(nonces)] if canary else [], "replies": [],
                "live_probes": [1, 2, 3] if canary else [], "summaries": [], "counts": {},
                "sends": 3, "dropped_items": 0, "encrypted_bodies": 0}

    login = SimpleNamespace(log=[], needles=lambda: {})
    responder = SimpleNamespace(state=lambda: {"identity_drift": None, "sends": 3}, served_identities=lambda: {})
    monkeypatch.setattr(s9, "build_arm", build)
    monkeypatch.setattr(s9, "finish_arm", finish)
    monkeypatch.setattr(s9, "observations", observe)
    monkeypatch.setattr(s9, "live_responder", lambda *a: (responder, None, login))
    monkeypatch.setattr(s9, "scan", lambda *a: {"hits": {}, "unreadable": 0})
    code = s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None)
    assert code == (2 if part == "resume24" else 0)
    assert constructed == closed == expected and len(active_ids) == 1
    assert sorted(p.stem for p in (args.out / "arms").glob("*.json")) == sorted(expected)
    assert (args.out / "run.json").is_file()
    if part == "live":
        assert s9.json.loads((args.out / "canary.json").read_bytes())["verdict"] == "pass"
    if part == "resume24":
        assert s9.json.loads((args.out / "resume24.json").read_bytes())["stop"] == "no_compaction"
    for path in (args.out / "arms").glob("*.json"):
        assert str(tmp_path) not in path.read_text()


def test_output_guard_refuses_before_persisting(tmp_path):
    class Guard:
        def check(self, _):
            raise s9.CredentialLeak("fixture")
    path = tmp_path / "run.json"
    with pytest.raises(s9.CredentialLeak):
        s9.write_result(path, {"state": "forbidden synthetic value"}, Guard())
    assert not path.exists()


def test_unretained_compaction_refuses_later_sessions(arm):
    arm.adapter.paths["root"] = arm.adapter.paths["home"].parent
    original = arm.adapter.run_session

    def session(index, **kwargs):
        result = original(index, **kwargs)
        result.acp_session_id = "saved"
        result.summariser_records = int(index == 1)
        ledger_fixture(arm, role="summariser" if index == 1 else "probe_main",
                       attempt=kwargs["attempt_id"], text="retained summary" if index == 1 else "history missing")
        return result
    arm.adapter.run_session = session
    record, code = s9.run_life(arm, "resume24", "r", {}, script=s9.micro_script(sessions=[1, 2, 3, 4]),
                               wait_s=86400, sleep=lambda _: None)
    assert code == 1 and record["sessions_run"] == [1, 2]
    assert record["stop"] == "compaction_not_retained" and arm.resume_record["resumed_ok"] is False


def test_constructed_gate_excludes_wait_and_preserves_marker_readings(tmp_path, monkeypatch, idle_marker):
    now = [0]
    active = s9.ActiveClock(lambda: now[0])

    def construct(entry, **kwargs):
        adapter = FakeAdapter(kwargs["root"])

        def gate(readings):
            now[0] += 60
            readings.extend([{"exit": 11, "state": "busy"}, {"exit": 0, "state": "idle"}])
        adapter._gate = gate
        return adapter
    monkeypatch.setattr(s9, "HermesAdapter", construct)
    arm, _ = s9.build_arm("hermes-native", tmp_path / "cell", s9.micro_script(), "r", active)
    readings = []
    arm.adapter._gate(readings)
    assert active() == 0 and active.markers == readings
    assert readings[:2] == [{"exit": 11, "state": "busy"}, {"exit": 0, "state": "idle"}]
    assert readings[-1] == {"exit": 0, "state": "fixture"}


@pytest.mark.parametrize("configured", [False, True])
def test_preflight_requires_configured_marker(preflight_env, monkeypatch, tmp_path, capsys, configured):
    if not configured:
        monkeypatch.delenv("BICENTENNIAL_BUSY_CMD")
    monkeypatch.delenv("BICENTENNIAL_OPERATOR")
    with pytest.raises(SystemExit) as exc:
        s9.main(preflight_env)
    assert exc.value.code == 3
    assert ("benchmark_operator_required" if configured else "marker_refused") in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("configured", [False, True])
def test_adapter_admission_requires_configured_marker(tmp_path, monkeypatch, idle_marker, configured):
    def construct(entry, **kwargs):
        adapter = FakeAdapter(kwargs["root"])
        def gate(readings):
            marker = s9.read_marker()
            readings.append({"exit": marker.exit, "state": marker.state})
        adapter._gate = gate
        return adapter

    monkeypatch.setattr(s9, "HermesAdapter", construct)
    active = s9.ActiveClock()
    arm, _ = s9.build_arm("hermes-native", tmp_path / "cell", s9.micro_script(), "r", active)
    # The marker can disappear after preflight, even after the adapter is built.
    if not configured:
        monkeypatch.delenv("BICENTENNIAL_BUSY_CMD")
        with pytest.raises(s9.Stop, match="marker_refused"):
            arm.adapter._gate([])
    else:
        arm.adapter._gate([])
    assert active.markers[-1] == {"exit": 0, "state": "fixture" if configured else "unset"}


@pytest.fixture
def offline_execution(tmp_path, monkeypatch):
    args = SimpleNamespace(part="live", out=tmp_path / "out", run="synthetic",
        arms=["hermes-native", "wiped", "no-memory"], mem0_source=None,
        max_output_tokens=1024, wait_s=86400, resume_auth=None)
    constructed, closed = [], []

    def build(label, root, script, run, active, **kwargs):
        assert constructed == closed
        constructed.append(root.name)
        adapter = FakeAdapter(root)
        adapter.paths["root"] = root
        return s9.Arm(adapter, load(REGISTRY / "hermes-native.toml"), label=label), {}

    def finish(arm, record):
        closed.append(constructed[len(closed)])
        record.update(unknown_requests=0, non_loopback=0, auth_path_requests=0,
                      digest="ab" * 32, ledger={})

    login = SimpleNamespace(log=[], needles=lambda: {})
    responder = SimpleNamespace(state=lambda: {"sends": 0}, served_identities=lambda: {})
    monkeypatch.setattr(s9, "build_arm", build)
    monkeypatch.setattr(s9, "finish_arm", finish)
    monkeypatch.setattr(s9, "live_responder", lambda *a: (responder, None, login))
    monkeypatch.setattr(s9, "scan", lambda *a: {"hits": {}, "unreadable": 0})
    return args, constructed, closed


@pytest.mark.parametrize("stop", ["proof_failed", "harness_alive", "compaction_unobserved"])
def test_last_session_quota_is_published_and_ends_part(offline_execution, monkeypatch, failure_exit, stop):
    args, constructed, closed = offline_execution
    if stop.startswith("compaction_"):
        args.part = "resume24"
    original, reads, receipts = s9.build_arm, [], {}
    quota = {"reasons": ["quota"], "held_ms": 5}

    def build(*a, **kw):
        arm, routes = original(*a, **kw)
        _, last_index, _ = failure_exit(arm, stop)
        session = arm.adapter.run_session

        def run(index, **kwargs):
            if index == last_index:
                receipts[kwargs["attempt_id"]] = quota
            return session(index, **kwargs)
        arm.adapter.run_session = run
        return arm, routes

    def at_boundary(attempt):
        reads.append(attempt)
        return receipts.pop(attempt, {"reasons": [], "held_ms": 0})

    responder = SimpleNamespace(state=lambda: {"sends": 0}, served_identities=lambda: {})
    monkeypatch.setattr(s9, "build_arm", build)
    monkeypatch.setattr(s9, "live_responder", lambda *a: (responder, SimpleNamespace(at_boundary=at_boundary), None))
    expected_status = 1 if stop == "proof_failed" else 2
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == expected_status
    assert constructed == closed == ["hermes-native.micro"]
    assert reads == ["hermes-native.micro-s1"] and receipts == {}
    records = {p.stem: s9.json.loads(p.read_bytes()) for p in (args.out / "arms").glob("*.json")}
    assert set(records) == {"hermes-native.micro"}
    record = records["hermes-native.micro"]
    assert record["stop"] == "hold:quota" and record["superseded_stop"] == stop
    assert record["exit_holds"] == quota and record["sessions_run"] == [1]
    assert s9.json.loads((args.out / "run.json").read_bytes())["exit"] == expected_status


def test_failed_proof_with_quota_preserves_execute_and_published_failure(offline_execution, monkeypatch):
    args, _, _ = offline_execution
    original, workspaces = s9.build_arm, []
    quota = {"reasons": ["quota"], "held_ms": 5}

    def build(*a, **kw):
        arm, routes = original(*a, **kw)
        workspaces.append(arm.adapter.paths["workspace"])
        return arm, routes

    def tamper(_):
        (workspaces[-1] / "tampered").write_text("changed during pause")

    responder = SimpleNamespace(state=lambda: {"sends": 0}, served_identities=lambda: {})
    monkeypatch.setattr(s9, "build_arm", build)
    monkeypatch.setattr(s9, "live_responder", lambda *a: (
        responder, SimpleNamespace(at_boundary=lambda _: quota), None))
    code = s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=tamper)
    record = s9.json.loads((args.out / "arms/hermes-native.micro.json").read_bytes())
    published = s9.json.loads((args.out / "run.json").read_bytes())
    assert (code, published["exit"], record["stop"], record["superseded_stop"]) == (
        1, 1, "hold:quota", "proof_failed")


@pytest.mark.parametrize("part", ["twin", "live", "resume24"])
def test_relative_output_builds_absolute_arm_paths(offline_execution, monkeypatch, tmp_path, part):
    args, constructed, closed = offline_execution
    monkeypatch.chdir(tmp_path)
    args.out, args.part = Path("relative-out"), part
    resolved = (tmp_path / args.out).resolve()
    original, roots, written = s9.build_arm, [], []
    write_result = s9.write_result

    def build(label, root, *a, **kw):
        roots.append(root)
        assert root.is_absolute() and root.is_relative_to(resolved)
        return original(label, root, *a, **kw)

    def write(path, *a, **kw):
        written.append(path)
        assert path.is_absolute() and path.is_relative_to(resolved)
        return write_result(path, *a, **kw)

    monkeypatch.setattr(s9, "build_arm", build)
    monkeypatch.setattr(s9, "write_result", write)
    code = s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None)
    assert code == (0 if part == "twin" else 2)
    if part == "twin":
        expected = [f"{label}.micro-{suffix}" for label in args.arms for suffix in ("u", "p")]
    elif part == "resume24":
        expected = ["hermes-native.micro"]
    else:
        expected = ["hermes-native.micro", "hermes-native.canary", "no-memory.canary", "wiped.micro", "no-memory.micro"]
    assert constructed == closed == expected
    assert roots == [resolved / "cells" / name for name in expected]
    assert resolved / "run.json" in written
    assert all((resolved / "arms" / f"{name}.json") in written for name in expected)


@pytest.mark.parametrize("reason", ["proof_failed", "harness_failed", "resume_failed",
    "compaction_not_retained", "compaction_unobserved", "compaction_unsettled", "no_compaction", "harness_alive"])
def test_arm_stop_preserves_other_executions(offline_execution, monkeypatch, reason):
    args, constructed, closed = offline_execution
    original = s9.run_life

    def life(arm, *a, **kw):
        if arm.execution == "hermes-native.micro":
            # Exercise the real proof-failure path for the reported finding.
            if reason == "proof_failed":
                def tamper(_):
                    (arm.adapter.paths["workspace"] / "tampered").write_text("changed")
                kw["sleep"] = tamper
                return original(arm, *a, **kw)
            arm.finals = []
            return {"arm": arm.label, "stop": reason}, 1
        return original(arm, *a, **kw)

    monkeypatch.setattr(s9, "run_life", life)
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == 1
    expected = ["hermes-native.micro", "hermes-native.canary", "no-memory.canary", "wiped.micro", "no-memory.micro"]
    assert constructed == closed == expected
    records = {p.stem: s9.json.loads(p.read_bytes()) for p in (args.out / "arms").glob("*.json")}
    assert set(records) == set(expected)
    assert records["hermes-native.micro"]["stop"] == reason
    if reason == "proof_failed":
        assert records["hermes-native.micro"]["sessions_run"] == [1]


@pytest.mark.parametrize("reason", ["identity_drift", "responder_stopped:MAX_SENDS", "spend_stop",
    "login_stop", "hold:quota", "budget", "unexpected_request"])
def test_admission_stop_ends_part_immediately(offline_execution, monkeypatch, reason):
    args, constructed, closed = offline_execution

    def life(arm, *a, **kw):
        arm.finals = []
        return {"arm": arm.label, "stop": reason}, 2

    monkeypatch.setattr(s9, "run_life", life)
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == 2
    assert constructed == closed == ["hermes-native.micro"]
    assert [p.stem for p in (args.out / "arms").glob("*.json")] == constructed


@pytest.mark.parametrize("missing", ["hermes-native.canary", "no-memory.canary"])
def test_missing_canary_execution_is_not_run(offline_execution, monkeypatch, missing):
    args, constructed, closed = offline_execution
    original = s9.build_arm

    def build(label, root, *a, **kw):
        if root.name == missing:
            raise s9.BoundaryBlocked("fixture")
        return original(label, root, *a, **kw)

    monkeypatch.setattr(s9, "build_arm", build)
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == 2
    assert constructed == closed
    canary = s9.json.loads((args.out / "canary.json").read_bytes())
    assert canary == {"items": 3, "sent": 0, "carried": 0, "verdict": "not_run"}


def test_twin_digest_mismatch_preserves_later_arms(offline_execution, monkeypatch):
    args, constructed, closed = offline_execution
    args.part = "twin"
    original = s9.finish_arm

    def finish(arm, record):
        original(arm, record)
        if constructed[-1] == "hermes-native.micro-p":
            record["digest"] = "cd" * 32

    monkeypatch.setattr(s9, "finish_arm", finish)
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == 1
    assert constructed == closed == [f"{label}.micro-{suffix}" for label in args.arms for suffix in ("u", "p")]
    record = s9.json.loads((args.out / "arms/hermes-native.micro-p.json").read_bytes())
    assert record["stop"] == "twin_digest_mismatch"


ADMISSION_FAILURES = [
    ({"stopped": True, "stop_reason": "upstream_failures"}, "responder_stopped:upstream_failures"),
    ({"stopped": True, "stop_reason": "unparsed"}, "responder_stopped:unparsed"),
    ({"stopped": True, "stop_reason": "MAX_SENDS"}, "responder_stopped:MAX_SENDS"),
    ({"spend_stopped": True}, "spend_stop"),
    ({"identity_drift": {"model": "changed"}}, "identity_drift"),
    ({}, "budget"),
]


@pytest.mark.parametrize(("failure", "reason"), ADMISSION_FAILURES + [({"login_stop": "fixture"}, "login_stop")])
def test_failed_proof_checks_current_responder_and_clock(arm, failure_exit, failure, reason):
    _, _, attempts = failure_exit(arm, "proof_failed")
    record, code = s9.run_life(arm, "live", "r", {}, script=s9.micro_script(sessions=[1, 2]),
        wait_s=0, sleep=lambda _: None,
        responder=SimpleNamespace(state=lambda: failure if attempts else {}),
        active_seconds=lambda: s9.BUDGET_S["live"] + 1 if attempts and reason == "budget" else 0)
    assert record["sessions_run"] == [1] and code == 1
    assert record["stop"] == reason and record["superseded_stop"] == "proof_failed"
    assert record["exit_holds"] == {}


@pytest.mark.parametrize(("failure", "reason"), ADMISSION_FAILURES)
@pytest.mark.parametrize("stubbed_life", [False, True])
def test_mid_session_admission_failure_ends_part(offline_execution, monkeypatch, failure, reason, stubbed_life):
    args, constructed, closed = offline_execution
    state, now = {"sends": 0}, [0]
    responder = SimpleNamespace(state=lambda: dict(state), served_identities=lambda: {})
    monkeypatch.setattr(s9, "live_responder", lambda *a: (responder, None, None))
    clock = s9.ActiveClock
    monkeypatch.setattr(s9, "ActiveClock", lambda: clock(lambda: now[0]))

    def fail():
        state.update(failure)
        if reason == "budget":
            now[0] = s9.BUDGET_S[args.part] + 1

    if stubbed_life:
        def life(arm, *a, **kw):
            fail()
            return {"arm": arm.label, "stop": "harness_failed", "sessions_run": []}, 1
        monkeypatch.setattr(s9, "run_life", life)
    else:
        original = s9.build_arm

        def build(*a, **kw):
            arm, routes = original(*a, **kw)

            def session(*a, **kw):
                fail()
                raise s9.HarnessFailed("synthetic upstream refusal")
            arm.adapter.run_session = session
            return arm, routes
        monkeypatch.setattr(s9, "build_arm", build)

    code = s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None)
    assert constructed == closed == ["hermes-native.micro"]
    records = {p.stem: s9.json.loads(p.read_bytes()) for p in (args.out / "arms").glob("*.json")}
    stopped = records["hermes-native.canary" if stubbed_life else "hermes-native.micro"]
    assert stopped["stop"] == reason and stopped["sessions_run"] == []
    assert set(records) == {"hermes-native.micro", *(["hermes-native.canary"] if stubbed_life else [])}
    assert code == (1 if stubbed_life else 2)
    assert s9.json.loads((args.out / "run.json").read_bytes())["exit"] == code


@pytest.mark.parametrize(("failure", "reason"), ADMISSION_FAILURES)
def test_life_admission_checked_before_first_session(arm, failure, reason):
    record, code = s9.run_life(arm, "live", "r", {}, script=s9.micro_script(sessions=[1, 2]), wait_s=0,
        responder=SimpleNamespace(state=lambda: failure),
        active_seconds=lambda: s9.BUDGET_S["live"] + 1 if reason == "budget" else 0)
    assert arm.adapter.ran == [] and record["sessions_run"] == []
    assert record["stop"] == reason and code == 2


def test_light_arm_mid_part_marker_ten_is_admitted(tmp_path, monkeypatch):
    adapter_type = s9.HermesAdapter
    marker = SimpleNamespace(exit=10, state="busy")
    monkeypatch.setattr(sys.modules[adapter_type.__module__], "read_marker", lambda: marker)
    monkeypatch.setattr(s9, "read_marker", lambda: marker)

    def construct(entry, **kwargs):
        adapter = FakeAdapter(kwargs["root"])
        adapter.entry = entry
        adapter._gate = adapter_type._gate.__get__(adapter)
        return adapter
    monkeypatch.setattr(s9, "HermesAdapter", construct)
    active = s9.ActiveClock()
    arm, _ = s9.build_arm("hermes-native", tmp_path / "cell", s9.micro_script(), "r", active)
    assert arm.entry["machine_class"] == "light"
    readings = []
    arm.adapter._gate(readings)
    assert readings == active.markers == [{"exit": 10, "state": "busy"}] * 2


def test_mid_part_unset_marker_publishes_earlier_arms(tmp_path, monkeypatch):
    args = SimpleNamespace(part="live", out=tmp_path / "out", run="synthetic",
        arms=["hermes-native", "wiped", "no-memory"], mem0_source=None,
        max_output_tokens=1024, wait_s=86400, resume_auth=None)
    constructed, closed = [], []
    marker = SimpleNamespace(exit=0, state="fixture")
    monkeypatch.setattr(s9, "read_marker", lambda: marker)
    responder = SimpleNamespace(state=lambda: {"sends": 0}, served_identities=lambda: {})
    monkeypatch.setattr(s9, "live_responder", lambda *a: (responder, None, None))

    def construct(entry, **kwargs):
        assert constructed == closed
        constructed.append(kwargs["root"].name)
        adapter = FakeAdapter(kwargs["root"])
        adapter.paths["root"] = kwargs["root"]
        adapter._gate = lambda readings: readings.append({"exit": marker.exit, "state": marker.state})
        original_session = adapter.run_session

        def session(index, **kw):
            if constructed[-1] == "hermes-native.canary":
                marker.state = "unset"
            adapter._gate([])
            return original_session(index, **kw)
        adapter.run_session = session
        return adapter

    def finish(arm, record):
        closed.append(constructed[len(closed)])
        record.update(unknown_requests=0, non_loopback=0, auth_path_requests=0,
                      digest="ab" * 32, ledger={})

    monkeypatch.setattr(s9, "HermesAdapter", construct)
    monkeypatch.setattr(s9, "finish_arm", finish)
    assert s9.execute(args, {"exit": 0, "state": "fixture"}, None, sleep=lambda _: None) == 2
    assert constructed == closed == ["hermes-native.micro", "hermes-native.canary"]
    records = {p.stem: s9.json.loads(p.read_bytes()) for p in (args.out / "arms").glob("*.json")}
    assert records["hermes-native.micro"]["stop"] is None
    assert records["hermes-native.canary"]["stop"] == "marker_refused"
    assert s9.json.loads((args.out / "canary.json").read_bytes())["verdict"] == "not_run"
    run = s9.json.loads((args.out / "run.json").read_bytes())
    assert run["exit"] == 2 and run["markers"][-1] == {"exit": 0, "state": "unset"}
    assert {"exit": 0, "state": "fixture"} in run["markers"]
