"""Offline checks for the implemented subset; live orchestration is unfinished."""

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream import Upstream
from bicentennial.harness.hermes import adapter as adapter_module
from bicentennial.harness.hermes.adapter import HermesAdapter
from bicentennial.harness.hermes.config import hermes_config
from bicentennial.items.protocol import CANARY
from bicentennial.runner.spend import Price, Spend
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.bytes import allocated_bytes, store_bytes

ROOT = Path(__file__).resolve().parents[2]
MODULE_SPEC = importlib.util.spec_from_file_location("s6_runner", Path(__file__).with_name("run.py"))
s6 = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(s6)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("s6-build")
    outputs = []
    for seed in ("0", "random"):
        output = scratch / seed
        proc = subprocess.run(["nice", "-n", "19", sys.executable, str(ROOT / "spikes/s6/run.py"),
                               "build", "--out", str(output)], cwd=ROOT,
                              env=dict(os.environ, PYTHONHASHSEED=seed), capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == "sha256 78f85667be31e1840caec345816689c2507a6089d5010daed8b81b0c9ec1f442\n"
        outputs.append(output)
    return outputs


def test_full_life_and_cross_process_determinism(built):
    a, b = built
    assert (a / "script.json").read_bytes() == (b / "script.json").read_bytes()
    assert (a / "life.json").read_bytes() == (b / "life.json").read_bytes()
    script = json.loads((a / "script.json").read_bytes())
    validate("script", script)
    assert scan_script(script, (), ()) == []
    assert len(script["sessions"]) == 201
    assert [s["index"] for s in script["sessions"]] == list(range(1, 202))
    assert [s["kind"] for s in script["sessions"]] == ["replay"] * 200 + ["probe"]
    plans = [json.loads(line) for line in (a / "sessions.B0.jsonl").read_bytes().splitlines()]
    sprints = [s["index"] for s in plans if s["long_sprint"]]
    assert len(sprints) == 8
    assert [(s - 1) // 25 for s in sprints] == list(range(8))
    faults = [f for s in plans for f in s["fault_points"]]
    assert faults == [dict(kind="kill", session=110, turn=1), dict(kind="swap", session=150, turn=None)]
    assert FaultLite.load(faults, script).to_obj() == faults
    probes = json.loads((a / "probes.json").read_bytes())
    assert len(probes) == 1 and probes[0]["index"] == 201 and probes[0]["checkpoint"] == 200
    assert len(probes[0]["item_ids"]) == 2
    assert len(script["sessions"][-1]["turns"]) == 2
    assert {t.template_id for t in s6.QA} == {"drift-asof", "recall-count"}
    assert {p.name for p in a.iterdir()} == {
        "world.B0.db", "history.B0.json", "stream.B0.jsonl", "sessions.B0.jsonl",
        "script.json", "life.json", "items.B0.json", "probes.json"}


def test_existing_build_is_unchanged_and_failures_remove_new_tree(built, tmp_path, monkeypatch):
    before = {p.name: p.read_bytes() for p in built[0].iterdir()}
    with pytest.raises(FileExistsError):
        s6.build_life(built[0])
    assert before == {p.name: p.read_bytes() for p in built[0].iterdir()}

    def refuse(*args, **kwargs):
        raise ValueError("seed refused")

    monkeypatch.setattr(s6, "build_base", refuse)
    with pytest.raises(ValueError, match="seed refused"):
        s6.build_life(tmp_path / "failed")
    assert not (tmp_path / "failed").exists()


def test_window_matches_base_golden_and_sets_full_threshold():
    default = hermes_config(1234, "bicentennial-main")
    assert sha256_canon(default) == "c6e1612d6953ce9be177a81aca16f024efedfcd584e51dbfe6e1d0f47d843d9d"
    assert default == hermes_config(1234, "bicentennial-main", window=None)
    full = hermes_config(1234, "bicentennial-main", window=131072)
    assert full["compression"]["threshold_tokens"] == 131072
    assert full["model"]["context_length"] == full["auxiliary"]["compression"]["context_length"] == 524288
    for bad in (True, 0, 16383, "131072", 131072.0):
        with pytest.raises(ValueError, match="window must be an int of at least 16384"):
            hermes_config(1234, "bicentennial-main", window=bad)


@pytest.mark.parametrize("role,subrole,live", [
    ("write_turn", None, True), ("probe_main", "cursor", True), ("memory_write", None, True),
    ("summariser", None, True), ("aux", "summariser", True), ("aux", "title_generation", False),
    ("aux", "extraction", False), ("embeddings", None, False)])
def test_routes_by_ledger_role(role, subrole, live):
    router = s6.Routed(SimpleNamespace(respond=lambda call: "live"),
                       SimpleNamespace(respond=lambda call: "scripted"))
    assert router.respond(SimpleNamespace(role=role, subrole=subrole)) == ("live" if live else "scripted")


def test_price_mismatch_refused_directly_by_upstream(tmp_path):
    spend = Spend(tmp_path / "spend.json", 0, Price(0, 0))
    with pytest.raises(ValueError):
        Upstream("sol", "gpt-6.1-sol", "http://127.0.0.1:1", "responses", spend, Price(0, 1), 100)
    routed, cred, holds = s6.build_stack(s6.load_entry("hermes-native"), tmp_path / "spend.json",
                                       auth=lambda: {}, base_url="http://127.0.0.1:1",
                                       max_output=100, max_sends=20)
    assert routed.state() == cred.state()
    assert routed.served_identities() == {}
    assert holds.at_boundary(None) == {"reasons": [], "held_ms": 0}


def test_byte_baseline_volatile_and_k10(tmp_path):
    (tmp_path / "store").write_bytes(b"a" * 8192)
    (tmp_path / "volatile").mkdir()
    baseline = allocated_bytes(tmp_path, ["volatile"])
    (tmp_path / "volatile" / "log").write_bytes(b"b" * 16384)
    assert store_bytes(tmp_path, baseline, ["volatile"]) == 0
    (tmp_path / "more").write_bytes(b"c" * 8192)
    assert store_bytes(tmp_path, baseline, ["volatile"]) == (tmp_path / "more").stat().st_blocks * 512
    result = s6.byte_checkpoint(1006, 1005)
    assert result["K100"] == {"cap": 1005, "over": True}
    assert s6.byte_checkpoint(1005, 1005)["K100"]["over"] is False
    assert result["K10"] == {"cap": 100, "verdict": None, "reason": "r06_k100_only_v01"}
    canon(result)


class FakeAdapter:
    def __init__(self, root):
        root.mkdir()
        self.paths = dict(root=root, hermes_home=root, home=root)
        self.entry = {"surfaces": [{"root": "HERMES_HOME", "relative": ".", "volatile_paths": []}]}
        self.done, self.ledger, self.closed = [], [], False

    def run_session(self, index, **kwargs):
        self.done.append(index)
        self.ledger.append(dict(attempt_id=kwargs["attempt_id"], upstream=[
            dict(diagnostics=[dict(identity_changed=index == 2)])]))
        return SimpleNamespace(session=index, kind="replay", turns_ok=1, finals_matched=1,
                               restarts=(), compaction_expected=False, summariser_records=0,
                               surface_hash="a" * 64, gate=(), end_threads=(),
                               timings_ms=dict(spawn=[3], open=[4], turn=[10], close=5),
                               finals=((1, "probe final must stay out of artifacts"),))

    def records(self):
        return self.ledger

    def close(self):
        self.closed = True
        return {"non_loopback": []}


@pytest.mark.parametrize("stop,expected,count", [
    ("identity_drift", "identity_drift", 2), ("login_stop", "login_stop", 0),
    ("spend_stopped", "live_spend_stop", 0), ("stopped", "upstream_401", 0),
    ("quota", "quota_hold", 0), ("wall", "arm_wall", 0), (None, None, 3)])
def test_session_boundary_stops_and_flagged_sessions(tmp_path, stop, expected, count):
    adapter = FakeAdapter(tmp_path / "root")

    def state():
        return dict(identity_drift=stop == "identity_drift" and len(adapter.done) >= 2,
                    login_stop=stop == "login_stop", spend_stopped=stop == "spend_stopped",
                    stopped=stop == "stopped", stop_reason="upstream_401" if stop == "stopped" else None)

    cred = SimpleNamespace(state=state, served_identities=lambda: {})
    holds = SimpleNamespace(at_boundary=lambda prev: dict(reasons=["quota"] if stop == "quota" else []))
    result = s6.run_arm("hermes-native", adapter,
                        {"sessions": [dict(index=i, kind="replay") for i in (1, 2, 3)]},
                        {1: 0, 2: 60, 3: 120}, cred=cred, holds=holds, lock="a" * 64,
                        wall_s=0 if stop == "wall" else 86400, monotonic=lambda: 0)
    assert result["sessions_run"] == count
    assert result["stop_reason"] == expected
    assert result["flagged_sessions"] == ([2] if count >= 2 else [])
    assert adapter.closed
    assert b"probe final" not in (adapter.paths["root"] / "arm.json").read_bytes()
    canon(result)


def test_fake_worker_full_window_and_kill_timing(tmp_path, monkeypatch):
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    root = tmp_path / "worker"
    root.mkdir()
    entry = s6.load_entry("hermes-native")
    script = dict(canary=CANARY, life_id=s6.LIFE_ID, genre="G2", harness="hermes", sessions=[
        dict(index=1, kind="replay", turns=[dict(n=i, kind="replay", user=f"P06 fake turn {i}",
                                                assistant="Noted.", tool_calls=[]) for i in (1, 2)])])
    routes = RouteTable.load({"routes": [dict(system="hermes-native", segment="seg0", probe_model="fake",
                                               summariser="fake", alias="bicentennial-main", vision=None,
                                               served_by="scripted")]})
    adapter = HermesAdapter(entry, script=script, route_table=routes,
                            schedule=FaultLite.load([dict(kind="kill", session=1, turn=1)], script),
                            responder=ScriptedResponder(entry), clock=SimClock(root / "clock.json", 1_700_000_000, 60),
                            root=root, scratch=tmp_path, life=s6.LIFE_ID, branch="B0", run="p06-fake-window",
                            worker_argv=[sys.executable, str(ROOT / "tests/harness/fake_worker.py")], window=131072)
    try:
        result = adapter.run_session(1, sim_t_s=1_700_000_000, lock_hash="a" * 64, attempt_id="p06-fake")
        config = json.loads((adapter.paths["hermes_home"] / "config.yaml").read_bytes())
        assert config["compression"]["threshold_tokens"] == 131072
        assert len(result.restarts) == 1
        raw = result.timings_ms
        clean, job = s6.session_timing(raw)
        assert len(raw["spawn"]) == len(raw["open"]) == 2
        assert len(clean["spawn"]) == len(clean["open"]) == 1
        assert job == sum(sum(v) if isinstance(v, list) else v for v in raw.values()) - raw["spawn"][1] - raw["open"][1]
    finally:
        adapter.close()


def test_import_firewall_and_system_allowlist():
    with pytest.raises(ValueError):
        s6.load_entry("lcm-x")
    for relative in ("spikes/s6/run.py", "src/bicentennial/runner/projection.py"):
        tree = ast.parse((ROOT / relative).read_text())
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "install_placeholder"
        assert all("lcm" not in name and name.split(".")[0] not in ("urllib", "socket", "http") for name in imports)
        if relative.endswith("projection.py"):
            assert set(imports) <= {"dataclasses", "fractions", "math", "bicentennial.canon"}


def run_args(tmp_path, arm="hermes-native"):
    return ["run", "--arm", arm, "--life", str(tmp_path / "life"),
            "--scratch", str(tmp_path), "--hermes", str(tmp_path / "hermes"),
            "--sol-max-output", "100", "--sol-max-output-source", "offline fixture",
            "--max-sends", "2000"]


def ready_preflight(monkeypatch):
    from bicentennial.runner.guard import Marker

    order = []
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    for name in (s6.ENV_STORE, "BICENTENNIAL_SOL_TOKEN_URL", "BICENTENNIAL_SOL_CLIENT_ID",
                 "BICENTENNIAL_SOL_BASE_URL"):
        monkeypatch.setenv(name, "offline-fixture")
    monkeypatch.setattr(s6, "reexec_niced", lambda argv: order.append("nice"))
    monkeypatch.setattr(s6.shutil, "disk_usage", lambda path: SimpleNamespace(free=150_000_000_000))
    monkeypatch.setattr(s6, "read_marker", lambda: (order.append("marker") or Marker(0, False, "idle")))
    return order


def test_mem0_cli_blocks_before_preflight_or_login(tmp_path, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        pytest.fail("blocked Mem0 must not preflight, login or construct an adapter")

    for name in ("preflight", "open_login", "HermesAdapter"):
        monkeypatch.setattr(s6, name, forbidden)
    assert s6.main(run_args(tmp_path, "mem0-oss")) == 2
    assert capsys.readouterr().out == "mem0_blocked\n"
    assert not list(tmp_path.glob("p06-*"))


@pytest.mark.parametrize("state,exit_code", [("busy", 10), ("unset", 0)])
def test_guard_refuses_without_root_after_nicing(tmp_path, monkeypatch, capsys, state, exit_code):
    from bicentennial.runner.guard import Marker

    order = ready_preflight(monkeypatch)
    monkeypatch.setattr(s6, "START_WAIT_S", 0)
    monkeypatch.setattr(s6, "read_marker", lambda: (order.append("marker") or Marker(exit_code, False, state)))
    monkeypatch.setattr(s6, "open_login", lambda *a: pytest.fail("login on busy machine"))
    with pytest.raises(SystemExit) as exc:
        s6.main(run_args(tmp_path))
    assert exc.value.code == 3
    assert order == ["nice", "marker"]
    assert "start_marker_timeout" in capsys.readouterr().err
    assert not list(tmp_path.glob("p06-*"))


def test_preflight_order_missing_env_disk_and_hashseed(tmp_path, monkeypatch, capsys):
    order = ready_preflight(monkeypatch)
    monkeypatch.delenv("BICENTENNIAL_SOL_CLIENT_ID")
    with pytest.raises(SystemExit) as exc:
        s6.main(run_args(tmp_path))
    assert exc.value.code == 3
    assert order == ["nice"]
    assert capsys.readouterr().err == "missing:BICENTENNIAL_SOL_CLIENT_ID\n"
    monkeypatch.setenv("BICENTENNIAL_SOL_CLIENT_ID", "offline-fixture")
    monkeypatch.setattr(s6.shutil, "disk_usage", lambda p: SimpleNamespace(free=149_999_999_999))
    with pytest.raises(SystemExit) as exc:
        s6.main(run_args(tmp_path))
    assert exc.value.code == 3
    assert "disk_floor" in capsys.readouterr().err
    monkeypatch.setenv("PYTHONHASHSEED", "random")
    with pytest.raises(SystemExit) as exc:
        s6.main(run_args(tmp_path))
    assert exc.value.code == 70
    assert order == ["nice", "nice"]
    assert not list(tmp_path.glob("p06-*"))
    monkeypatch.setenv("PYTHONHASHSEED", "0")

    def denied(argv):
        raise RuntimeError("private diagnostic must not be printed")

    monkeypatch.setattr(s6, "reexec_niced", denied)
    with pytest.raises(SystemExit) as exc:
        s6.main(run_args(tmp_path))
    assert exc.value.code == 3
    assert capsys.readouterr().err == "background_policy\n"


def test_marker_wait_keeps_every_reading(tmp_path, monkeypatch):
    from bicentennial.runner.guard import Marker

    ready_preflight(monkeypatch)
    markers = iter([Marker(10, False, "busy"), Marker(0, False, "idle")])
    waited = []
    monkeypatch.setattr(s6, "read_marker", lambda: next(markers))
    monkeypatch.setattr(s6.time, "sleep", waited.append)
    readings = s6.preflight(SimpleNamespace(scratch=tmp_path))
    assert readings == [dict(exit=10, state="busy"), dict(exit=0, state="idle")]
    assert waited == [60]


def test_live_reference_checkout_refused():
    with pytest.raises(ValueError, match="isolated Hermes"):
        s6.safe_checkout(Path.home() / ".hermes" / "checkout")


def test_life_inputs_raw_bytes_and_starts(built):
    script, plans, starts, faults, raw = s6.life_inputs(built[0])
    assert len(plans) == 200 and len(script["sessions"]) == 201
    assert starts[1] == s6.build_schedule("6", s6.LIFE_ID, s6.named("full")).sessions[0].t_start
    assert starts[201] == json.loads((built[0] / "probes.json").read_bytes())[0]["sim_t_s"]
    assert faults.to_obj() == [dict(kind="kill", session=110, turn=1),
                               dict(kind="swap", session=150, turn=None)]
    events = [json.loads(row) for row in (built[0] / "stream.B0.jsonl").read_bytes().splitlines()]
    indices = {p.session_id: p.index for p in s6.build_schedule("6", s6.LIFE_ID, s6.named("full")).sessions}
    for checkpoint in (20, 60, 120, 200):
        assert raw[checkpoint] == sum(len(s6.content(row).encode()) for row in events
                                      if indices[row["session_id"]] <= checkpoint)


def test_empty_initialisation_precedes_baseline(tmp_path):
    import threading

    adapter = FakeAdapter(tmp_path / "empty")
    events = []
    adapter.egress = SimpleNamespace(forking=threading.Lock(), summary=lambda: dict(non_loopback=[]))
    adapter.director = SimpleNamespace(start_session=lambda *a: events.append("start"),
                                      route={"alias": "bicentennial-main"})
    adapter._gate = lambda readings: readings.append(dict(exit=0, state="idle"))

    def spawn(*args):
        events.append("open_empty")
        (adapter.paths["hermes_home"] / "initialised").write_bytes(b"a" * 8192)

    adapter._spawn_open = spawn
    adapter._drain = lambda: events.append("drain")
    adapter._end = lambda: events.append("end") or ()
    from bicentennial.systems.settle import SettleResult
    cell = SimpleNamespace(settle=lambda: events.append("settle") or SettleResult("hook", True, 1, "drained", 0))
    receipt = s6.initialise(adapter, {1: 0}, "a" * 64, cell)
    assert events == ["start", "open_empty", "drain", "end", "settle"]
    assert receipt["baseline"][0] >= 8192
    cred = SimpleNamespace(state=lambda: {}, served_identities=lambda: {})
    holds = SimpleNamespace(at_boundary=lambda _: dict(reasons=[]))
    result = s6.run_arm("hermes-native", adapter, {"sessions": [dict(index=1, kind="replay")]},
                        {1: 0}, cred=cred, holds=holds, lock="a" * 64)
    assert result["sessions"][0]["bytes"] == 0


def test_recovery_timing_and_own_probe_measurements():
    timing = dict(spawn=[3, 13], open=[4, 14], turn=[100, 80], drain=[5, 5], resume=[30], close=6)
    clean, job = s6.session_timing(timing)
    assert job == 233 and clean["resume"] == [30]
    sessions = [dict(session=110, kind="replay", attempt_id="r", job_ms=job,
                     timings_ms=clean, summariser_records=1),
                dict(session=201, kind="probe", attempt_id="p", job_ms=160,
                     timings_ms=dict(spawn=[10], open=[20], turn=[60, 40], close=30), summariser_records=0)]
    rows = [dict(type="request", attempt_id=a, role=role, subrole="cursor", upstream=[dict(role=role,
             resp="blob", diagnostics=[dict(kind="try", sent=True, t_ms=100),
                                         dict(kind="hold", held_ms=20)])])
            for a, role in [("r", "write_turn"), ("p", "probe_main")]]
    t, metrics = s6.measurements(dict(sessions=sessions), rows,
        {"blob": {"usage": dict(prompt_tokens=10, completion_tokens=3)}},
        {"sessions": [dict(index=201, kind="probe", turns=[{}, {}])]},
        [dict(index=110, long_sprint=True)])
    assert t.R.wall_ms == 213
    assert t.e_probe.wall_ms == 100  # fixed 60 + (turn 100 - hold 20) / 2
    assert metrics["critical_path_lower_bound_ms"] == 313
    assert metrics["roles"]["write_turn/cursor"]["requests"] == 1
    assert metrics["probe_roles"]["probe_main/cursor"]["input_tokens"] == 10
    assert metrics["recovery_110_120"] == t.R.to_obj()
    assert metrics["compactions"] == dict(sprints={"110": 1}, ordinary={})
    assert set(s6.term_table(t)) == {"R", "R_cap", "P", "f", "r_c", "p_c", "P_K", "P_W", "R_B", "P_B",
                                   "delta_W", "C_learn", "C_erase", "C_image", "C_cross", "C_marker", "C_aa",
                                   "C_ctrl", "C_ring1", "C_ring2"}
    canon(metrics)
    canon(s6.term_table(t))


def test_last_session_drift_and_quota_are_stops(tmp_path):
    adapter = FakeAdapter(tmp_path / "last")
    cred = SimpleNamespace(state=lambda: dict(identity_drift=bool(adapter.done)), served_identities=lambda: {})
    calls = []
    holds = SimpleNamespace(at_boundary=lambda _: calls.append(1) or dict(reasons=["quota"] if adapter.done else []))
    result = s6.run_arm("hermes-native", adapter, {"sessions": [dict(index=1, kind="replay")]},
                        {1: 0}, cred=cred, holds=holds, lock="a" * 64)
    assert result["status"] == "stopped" and result["stop_reason"] == "identity_drift"
    assert result["pauses"][-1]["reasons"] == ["quota"]
    assert len(calls) == 2


@pytest.fixture
def responses_server(monkeypatch):
    import socket
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    bodies, outbound = [], []
    connect = socket.socket.connect

    def guarded(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            outbound.append(address[0])
            raise OSError("non-loopback refused")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            bodies.append(body)
            events = [dict(type="response.output_item.done", output_index=0, item=dict(
                type="message", role="assistant", content=[dict(type="output_text", text="offline final")])),
                dict(type="response.completed", response=dict(model="fake-served",
                    usage=dict(input_tokens=10, output_tokens=3)))]
            data = b"".join(b"data: " + canon(e) + b"\n\n" for e in events)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", bodies, outbound
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_fake_responses_worker_and_summary(built, tmp_path, responses_server, monkeypatch):
    base, bodies, outbound = responses_server
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    full, plans, starts, _, raw = s6.life_inputs(built[0])
    script = dict(full, sessions=[full["sessions"][0], full["sessions"][1], dict(full["sessions"][-1], index=3)])
    starts[3] = starts[201]
    validate("script", script)
    root = tmp_path / "p06-hermes-native"
    root.mkdir()
    routed, cred, holds = s6.build_stack(s6.load_entry("hermes-native"), root / "spend.json",
        auth=lambda: {"Authorization": "Bearer t"}, base_url=base, max_output=100, max_sends=2000)
    adapter = HermesAdapter(s6.load_entry("hermes-native"), script=script,
        route_table=RouteTable.load(s6.routes("hermes-native")), schedule=FaultLite.load([], script),
        responder=routed, clock=SimClock(root / "clock.json", starts[1], 60), root=root, scratch=tmp_path,
        life=s6.LIFE_ID, branch="B0", run="p06-fake-sse", window=131072,
        worker_argv=[sys.executable, str(ROOT / "tests/harness/fake_worker.py")])
    try:
        initial = s6.initialise(adapter, starts, "a" * 64)
        assert not bodies
    except BaseException:
        adapter.close()
        raise
    result = s6.run_arm("hermes-native", adapter, script, starts, cred=cred, holds=holds,
                        lock="a" * 64, raw=raw)
    assert result["status"] == "complete" and result["sessions_run"] == 3
    assert initial["baseline"] and not outbound
    rows, blobs, _ = s6.load_ledger(root / "ledger", "kit")
    by_role = s6.role_costs(rows, blobs, {r["attempt_id"]: r["session"] for r in result["sessions"]})
    assert len(bodies) == sum(c.requests for roles in by_role.values() for c in roles.values())
    assert all(u["role"] == "write_turn" for row in rows if row.get("role") == "replay_main"
               for u in row.get("upstream", []) if u.get("served_by") == "live")
    assert not any(r.get("role") == "unknown" for r in rows)
    result.update(credential_scan=dict(hits={}, unreadable=0), settled=0,
                  inputs=dict(script_sha256=s6.digest(built[0] / "script.json"), sol_max_output=100,
                              sol_max_output_source="offline fixture", max_sends=2000))
    s6._arm_write(root, result)
    out = tmp_path / "s6.json"
    assert s6.main(["summarise", "--scratch", str(tmp_path), "--life", str(built[0]), "--out", str(out)]) == 0
    obj = json.loads(out.read_bytes())
    assert canon(obj) == out.read_bytes()
    assert obj["arms"]["mem0-oss"] == dict(status="not_run", reason="mem0_blocked")
    assert b"offline final" not in out.read_bytes()
    assert obj["spend_microdollars"] == 0


def test_run_cli_integrates_login_baseline_shutdown_and_summary(built, tmp_path, monkeypatch):
    ready_preflight(monkeypatch)
    order = []
    login = SimpleNamespace(drain=lambda: [])
    cred = SimpleNamespace(login=login, state=lambda: {}, served_identities=lambda: {})
    holds = SimpleNamespace(at_boundary=lambda _: dict(reasons=[], held_ms=0))
    monkeypatch.setattr(s6, "open_login", lambda *a: order.append("login") or login)
    def stack(entry, path, **kwargs):
        Spend(path, 0, Price(0, 0))
        return SimpleNamespace(), cred, holds

    monkeypatch.setattr(s6, "build_stack", stack)

    class Adapter(FakeAdapter):
        def __init__(self, entry, **kwargs):
            # The command owns exclusive root creation before the adapter layout.
            root = kwargs["root"]
            self.paths = dict(root=root, hermes_home=root, home=root)
            self.entry = entry
            self.done, self.ledger, self.closed = [], [], False
            self.director = SimpleNamespace(guard=None)
            order.append("adapter")

        def run_session(self, index, **kwargs):
            assert "baseline" in order
            result = super().run_session(index, **kwargs)
            if index == 201:
                result.kind = "probe"
            return result

        def close(self):
            order.append("close")
            return super().close()

        def harness_record(self):
            return dict(name="fake", sha256="a" * 64)

    monkeypatch.setattr(s6, "HermesAdapter", Adapter)
    monkeypatch.setattr(s6, "initialise", lambda *a: order.append("baseline") or dict(baseline=[0]))

    def scan(*args):
        assert order[-1] == "close"
        order.append("scan")
        return dict(hits={}, unreadable=0)

    monkeypatch.setattr(s6, "scan", scan)
    args = run_args(tmp_path)
    args[args.index("--life") + 1] = str(built[0])
    assert s6.main(args) == 0
    assert order == ["login", "adapter", "baseline", "close", "scan"]
    arm_path = tmp_path / "p06-hermes-native" / "arm.json"
    arm = json.loads(arm_path.read_bytes())
    assert arm["sessions_run"] == 201
    assert arm["initial"]["baseline"] == [0]
    assert arm["inputs"]["max_sends"] == 2000
    assert len(arm["inputs"]["run"]) == 20
    assert b"probe final" not in arm_path.read_bytes()
    assert arm["inputs"]["routes"]["routes"][1]["alias"] == "bicentennial-swap"
    monkeypatch.setattr(s6, "load_ledger", lambda *a: ([], {}, "b" * 64))
    out = tmp_path / "results" / "s6.json"
    summary_args = ["summarise", "--scratch", str(tmp_path), "--life", str(built[0]), "--out", str(out)]
    assert s6.main(summary_args) == 0
    obj = json.loads(out.read_bytes())
    assert out.read_bytes() == canon(obj)
    assert obj["inputs"]["run_parameters"]["hermes-native"]["sol_max_output_source"] == "offline fixture"
    lanes = obj["projection"]["hermes-native"][s6.LIFE_ID]
    assert set(lanes) == {"sol-1", "sol-2", "replication_family", "swap"}
    assert lanes["sol-1"]["cut_order"]["rows"][0]["fits"] == "undetermined: no occupancy projection"
    assert obj["terms"]["hermes-native"]["C_learn"]["status"] == "missing"
    assert obj["bytes"]["mem0-oss"] == dict(status="not_run", reason="mem0_blocked")
    with pytest.raises(FileExistsError):
        s6.main(summary_args)
    before = out.read_bytes()
    arm["credential_scan"]["hits"] = {"synthetic": 1}
    s6._arm_write(arm_path.parent, arm)
    assert s6.main(summary_args[:-1] + [str(tmp_path / "refused.json")]) == 1
    assert not (tmp_path / "refused.json").exists()
    assert out.read_bytes() == before


def test_bridge_failure_stops_underlying_credential_state():
    failures = []

    class Bridge:
        inner = SimpleNamespace(stop=failures.append)

        def respond(self, call):
            raise ValueError("bridge_unmapped_key:logprobs")

    routed = s6.Routed(Bridge(), None)
    with pytest.raises(ValueError, match="bridge_unmapped_key:logprobs"):
        routed.respond(SimpleNamespace(role="write_turn", subrole=None))
    assert failures == ["bridge_unmapped_key:logprobs"]


def test_credential_guard_log_is_exit_one(tmp_path, monkeypatch):
    cred = SimpleNamespace(login=SimpleNamespace(drain=lambda: [dict(type="guard", label="synthetic")]))
    monkeypatch.setattr(s6, "run_command", lambda args: s6.drain_login(cred, tmp_path))
    assert s6.main(run_args(tmp_path)) == 1
    assert json.loads((tmp_path / "login.jsonl").read_bytes())["type"] == "guard"


def test_summary_without_run_and_incomplete_run(built, tmp_path, monkeypatch):
    out = tmp_path / "s6.json"
    args = SimpleNamespace(out=out, life=built[0], scratch=tmp_path)
    assert s6.summarise(args) == 0
    obj = json.loads(out.read_bytes())
    assert obj["arms"]["hermes-native"] == dict(status="not_run", reason="no_run")
    root = tmp_path / "p06-hermes-native"
    root.mkdir()
    s6._arm_write(root, dict(status="stopped", stop_reason="identity_drift", sessions=[],
        bytes={}, settled=0, credential_scan=dict(hits={}, unreadable=0),
        inputs=dict(script_sha256=s6.digest(built[0] / "script.json"), sol_max_output=100,
                    sol_max_output_source="fixture", max_sends=100)))
    monkeypatch.setattr(s6, "load_ledger", lambda *a: ([], {}, "b" * 64))
    second = tmp_path / "partial.json"
    assert s6.summarise(SimpleNamespace(out=second, life=built[0], scratch=tmp_path)) == 0
    obj = json.loads(second.read_bytes())
    assert obj["projection"]["hermes-native"] == dict(status="not_run", reason="incomplete_life")
    assert obj["terms"]["hermes-native"]["R"]["status"] == "partial"


def test_final_boundary_enforces_wall_and_initial_egress(tmp_path):
    now = [0]
    adapter = FakeAdapter(tmp_path / "wall-final")
    run_session = adapter.run_session

    def slow_session(*args, **kwargs):
        result = run_session(*args, **kwargs)
        now[0] = 20
        return result

    adapter.run_session = slow_session
    cred = SimpleNamespace(state=lambda: {}, served_identities=lambda: {})
    holds = SimpleNamespace(at_boundary=lambda _: dict(reasons=[], held_ms=0))
    script = dict(sessions=[dict(index=1, kind="replay")])
    result = s6.run_arm("hermes-native", adapter, script, {1: 0}, cred=cred, holds=holds,
                        lock="a" * 64, wall_s=10, monotonic=lambda: now[0])
    assert result["sessions_run"] == 1 and result["stop_reason"] == "arm_wall"
    assert result["wall_ms"] == 20_000
    adapter = FakeAdapter(tmp_path / "egress-initial")
    adapter.egress = SimpleNamespace(summary=lambda: dict(non_loopback=["synthetic"]))
    result = s6.run_arm("hermes-native", adapter, script, {1: 0}, cred=cred, holds=holds, lock="a" * 64)
    assert result["sessions_run"] == 0 and result["stop_reason"] == "non_loopback"
    assert adapter.closed


def test_native_empty_initialisation_settles(tmp_path):
    import threading

    adapter = FakeAdapter(tmp_path / "native-empty")
    adapter.entry["settle"] = dict(kind="none", bound_s=0)
    adapter.egress = SimpleNamespace(forking=threading.Lock())
    adapter.director = SimpleNamespace(start_session=lambda *a: None, route=dict(alias="bicentennial-main"))
    adapter._gate = lambda readings: None
    adapter._spawn_open = lambda *a: None
    adapter._drain = lambda: None
    adapter._end = lambda: ()
    result = s6.initialise(adapter, {1: 0}, "a" * 64)
    assert result["settle"]["settled"] is True
    assert result["settle"]["reason"] == "no_background_work"
    assert adapter._wiped is False


@pytest.mark.parametrize("missing,reason", [(True, "mem0_source_missing"), (False, "mem0_pin_mismatch")])
def test_measured_mem0_missing_source_and_install_refusal(built, tmp_path, monkeypatch, capsys, missing, reason):
    entry = s6.load_entry("mem0-oss")
    entry["artifact"]["sha256"] = "a" * 64
    original = s6.load_entry
    monkeypatch.setattr(s6, "load_entry", lambda name: entry if name == "mem0-oss" else original(name))
    # Only the artifact pin is tested here; no source tree, login or worker is real.
    monkeypatch.setattr(s6.registry, "unmeasured", lambda entry: [])
    ready_preflight(monkeypatch)
    login = SimpleNamespace(drain=lambda: [])
    monkeypatch.setattr(s6, "open_login", lambda *a: login)
    cred = SimpleNamespace(login=login)
    monkeypatch.setattr(s6, "build_stack", lambda *a, **k: (None, cred, None))
    closed = []
    adapter = SimpleNamespace(director=SimpleNamespace(guard=None), close=lambda: closed.append(True))
    monkeypatch.setattr(s6, "HermesAdapter", lambda *a, **k: adapter)

    class Cell:
        def __init__(self, *args):
            pass

        def install(self, *args, **kwargs):
            raise s6.PinMismatch("offline mismatch")

    monkeypatch.setattr(s6, "PluginCell", Cell)
    args = run_args(tmp_path, "mem0-oss")
    args[args.index("--life") + 1] = str(built[0])
    if not missing:
        args += ["--mem0-source", str(tmp_path / "source")]
    assert s6.main(args) == 2
    assert capsys.readouterr().out == reason + "\n"
    root = tmp_path / "p06-mem0-oss"
    if missing:
        assert not root.exists() and not closed
    else:
        assert closed == [True]
        assert json.loads((root / "arm.json").read_bytes())["reason"] == reason


def test_stack_reaches_responses_and_accounts_live_write_without_worker(built, tmp_path, responses_server):
    from bicentennial.director.core import Director
    from bicentennial.ledger import Guard

    base, bodies, outbound = responses_server
    script = json.loads((built[0] / "script.json").read_bytes())
    entry = s6.load_entry("hermes-native")
    routed, cred, _ = s6.build_stack(entry, tmp_path / "spend.json", auth=lambda: {"Authorization": "Bearer t"},
                                    base_url=base, max_output=100, max_sends=20)
    faults = FaultLite.load([], script)
    director = Director(script, RouteTable.load(s6.routes("hermes-native")), "hermes-native",
        s6.LIFE_ID, "B0", "p06-director-unit", ("memory",), routed,
        SimClock(tmp_path / "clock.json", 0, 60), Guard([]),
        dict(sandbox_root=str(tmp_path), director_port="0"), schedule=faults)
    try:
        director.start_session(1, 0, "a" * 64, "offline-attempt", tmp_path / "ledger")
        body = dict(model="bicentennial-main", messages=[
            dict(role="system", content="offline synthetic harness"),
            dict(role="user", content=script["sessions"][0]["turns"][0]["user"])],
            tools=[dict(type="function", function=dict(name=name)) for name in ("memory", "session_search")])
        status, _, _ = director.handle("POST", "/main/v1/chat/completions", {}, canon(body))
        assert status == 200 and len(bodies) == 1 and not outbound
        assert bodies[0]["model"] == s6.MODEL
        assert bodies[0]["reasoning"] == dict(effort="medium")
        assert "max_output_tokens" not in bodies[0]
    finally:
        director.close()
    rows, blobs, _ = s6.load_ledger(tmp_path / "ledger", "kit")
    costs = s6.role_costs(rows, blobs, {"offline-attempt": 1})
    assert costs[1]["write_turn"].requests == len(bodies)
    assert costs[1]["write_turn"].input_tokens == 10
    assert costs[1]["write_turn"].output_tokens == 3
    assert not any(row.get("role") == "unknown" for row in rows)
    assert cred.state()["sends"] == 1
    assert json.loads((tmp_path / "spend.json").read_bytes())["settled"] == 0


def test_reference_checkout_symlink_is_also_refused(tmp_path, monkeypatch):
    home, target = tmp_path / "home", tmp_path / "reference"
    home.mkdir()
    target.mkdir()
    (home / ".hermes").symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    with pytest.raises(ValueError, match="isolated Hermes"):
        s6.safe_checkout(target / "checkout")
