"""Offline seeded checks for S8's renderer and world-state records."""

import ast
import csv
import json
import os
import runpy
import subprocess
import sys
from hashlib import sha256
from itertools import combinations
from pathlib import Path

import pytest
import render
import run

from bicentennial.canon import canon
from bicentennial.director.responder import Call, Reply
from bicentennial.keyed import uniform_int


def cases():
    for index in range(200):
        kind = uniform_int("p08-tests", ("renderer",), 0, f"kind#{index}", 0, 2)
        family = uniform_int("p08-tests", ("renderer",), 0, f"family#{index}", 0, 4)
        yield run.world(f"case-{index:03d}")[kind], f"F{family}"


def test_renderer_200_cases():
    assert len(set(render.FONT.values())) == len(render.FONT)
    assert set(render.FONT) == set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ .:-$")
    for background, foreground, _accent in render.FAMILIES.values():
        assert abs(render.luminance(background) - render.luminance(foreground)) >= 100
    seen = set()
    for record, family in cases():
        seen.add((record["kind"], family))
        png, manifest = render.render(record, family, run.SEED)
        assert (png, manifest) == render.render(record, family, run.SEED)
        assert png.startswith(render.SIGNATURE)
        assert render.decode(png)[:2] == (480, 320)
        assert render.verify(png, manifest) == {"checked": len(manifest), "matched": len(manifest),
                                                 "recall_milli": 1000}
        for entry in manifest:
            x0, y0, x1, y1 = entry["bbox"]
            assert 0 <= x0 < x1 <= 480
            assert 0 <= y0 < y1 <= 320
            assert entry["value"] == record["values"][entry["field"]]
        assert all(not render.intersects(a["bbox"], b["bbox"]) for a, b in combinations(manifest, 2))
        if record["kind"] == "desk":
            assert {entry["field"] for entry in manifest} == {
                f"{field}{i}" for field in ("OBJECT", "CODE") for i in range(1, 5)}
        width, height, original = render.decode(png)
        pixels = bytearray(original)
        first = manifest[0]
        x0, y0, x1, y1 = first["bbox"]
        foreground = bytes(first["foreground"])
        position = next((y * width + x) * 3 for y in range(y0, y1) for x in range(x0, x1)
                        if pixels[(y * width + x) * 3:(y * width + x) * 3 + 3] == foreground)
        pixels[position] ^= 1
        corrupted = render.encode(pixels, width, height)
        result = render.verify(corrupted, manifest)
        assert result["matched"] == len(manifest) - 1
        damaged_crc = bytearray(png)
        damaged_crc[-1] ^= 1
        with pytest.raises(ValueError, match="CRC"):
            render.decode(damaged_crc)
    assert len(seen) == 15


def test_subprocess_hashseeds():
    script = """
import hashlib
import render
import run
from bicentennial.canon import canon
result = []
for index in range(200):
    record = run.world(f'case-{index:03d}')[index % 3]
    png, manifest = render.render(record, f'F{index % 5}', 'p08')
    result.append(hashlib.sha256(png + canon(manifest)).hexdigest())
print(hashlib.sha256(canon(result)).hexdigest())
"""
    outputs = []
    for seed in ("0", "random"):
        result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).parent,
                                env=dict(os.environ, PYTHONHASHSEED=seed), capture_output=True, check=True)
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_twins_and_presentation_200_cases():
    for index in range(200):
        life = f"twin-{index:03d}"
        for original, twin in zip(run.world(life), run.world(life, "B1"), strict=True):
            assert render.presentation(original, "p08") == render.presentation(twin, "p08")
            saved = canon(original["values"])
            render.render(original, "F0", "alternate")
            assert canon(original["values"]) == saved
            a, b = original["values"], twin["values"]
            if original["kind"] == "settings":
                assert a["SERVICE"] == b["SERVICE"]
                assert a["PORT"] != b["PORT"]
                assert a["MODE"] != b["MODE"]
            elif original["kind"] == "receipt":
                assert a["STORE"] == b["STORE"]
                assert a["TOTAL"] != b["TOTAL"]
                assert {a[f"ITEM{i}"] for i in range(1, 4)} != {b[f"ITEM{i}"] for i in range(1, 4)}
                for values in (a, b):
                    cents = [int(values[f"PRICE{i}"].replace(".", "")) for i in range(1, 4)]
                    assert run._money(sum(cents)) == values["TOTAL"]
                    assert len({values[f"ITEM{i}"] for i in range(1, 4)}) == 3
            else:
                assert a["OBJECT1"] == b["OBJECT1"]
                assert a["CODE1"] != b["CODE1"]
                assert {a[f"OBJECT{i}"] for i in range(1, 5)} != {b[f"OBJECT{i}"] for i in range(1, 5)}
                for i in range(2, 6):
                    assert a[f"CODE{i}"] == b[f"CODE{i}"]
                assert a["OBJECT5"] == b["OBJECT5"]


def test_image_index_and_keysheet(tmp_path):
    images = list(run.images())
    assert len(images) == 120
    assert all(image["family"] != "F4" for image in images if image["view"] == "life")
    digest = run.render_all(tmp_path / "images")
    assert digest == "459801181a7342dc1519185c50ccdf4daabe9d8ab8e9a6e066d2a5ca787f9bff"
    index = json.loads((tmp_path / "images" / "index.json").read_bytes())
    assert digest == sha256(canon(index)).hexdigest()
    for entry in index:
        for suffix, field in ((".png", "sha256"), (".json", "manifest_sha256")):
            assert sha256((tmp_path / "images" / (entry["id"] + suffix)).read_bytes()).hexdigest() == entry[field]
    rows = render.keysheet(images)
    assert len(rows) == 200
    assert rows == render.keysheet(images)
    assert all(render.decode(row["png"])[0] <= 480 for row in rows)
    key = tmp_path / "key.csv"
    with key.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("id", "crop", "typed"))
        writer.writeheader()
        writer.writerows({"id": row["id"], "crop": row["crop"], "typed": ""} for row in rows)
    assert render.fidelity(rows, key) == {"n": 200, "state": "pending_human_key"}
    with key.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("id", "crop", "typed"))
        writer.writeheader()
        writer.writerows({"id": row["id"], "crop": row["crop"], "typed": row["value"]} for row in rows)
    assert render.fidelity(rows, key) == {"n": 200, "legible_milli": 1000, "verifier_recall_milli": 1000}


def test_system_firewall():
    assert run.load_entry()["name"] == "hermes-native"
    with pytest.raises(ValueError):
        run.load_entry("another-system")
    for filename in ("render.py", "run.py", "worker.py"):
        tree = ast.parse(Path(__file__).with_name(filename).read_text())
        for node in ast.walk(tree):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert all("lcm" not in module for module in modules)
            assert all(module.split(".")[0] not in ("urllib", "socket", "http") for module in modules)


class FakeResponder:
    def __init__(self, text, status=200):
        self.text, self.status, self.calls = text, status, []

    def respond(self, call):
        self.calls.append(call)
        return Reply(self.status, "fake", "live", call.model, self.text)


def test_responder_routing_and_cache():
    live, scripted = FakeResponder("live"), FakeResponder("scripted")
    routed = run.Routed(live, scripted)
    for role, subrole in (("write_turn", "write_turn"), ("probe_main", "cursor"),
                          ("probe_main", "tool_results"), ("memory_write", "background_review"),
                          ("summariser", "compression"), ("aux", "summariser"), ("aux", "vision")):
        assert routed.respond(Call(role, subrole, "chat", {}, "model", None, "key")).text == "live"
    for role, subrole in (("aux", "title_generation"), ("aux", "extraction"), ("embeddings", "embedding")):
        assert routed.respond(Call(role, subrole, "chat", {}, "model", None, "key")).text == "scripted"
    by_model = run.ByModel({"model-a": live, "model-b": scripted})
    assert by_model.respond(Call("aux", "vision", "chat", {}, "model-b", None, "key")).text == "scripted"
    with pytest.raises(KeyError):
        by_model.respond(Call("aux", "vision", "chat", {}, "absent", None, "key"))
    inner = FakeResponder("caption")
    cache = run.CaptionCache(inner)
    cache.arm = "M"
    call = Call("aux", "vision", "chat", {"image": "one"}, "model", None, "key")
    first = cache.respond(call)
    cache.arm = "D"
    assert cache.respond(call) is first
    assert len(inner.calls) == 1 and cache.hits == {"D": 1}
    other = Call("aux", "vision", "chat", {"image": "two"}, "model", None, "key")
    cache.respond(other)
    assert len(inner.calls) == 2
    inner.status = 503
    failure = Call("aux", "vision", "chat", {"image": "three"}, "model", None, "key")
    assert cache.respond(failure).status == cache.respond(failure).status == 503
    assert len(inner.calls) == 4
    bypass = Call("probe_main", "cursor", "chat", {}, "model", None, "key")
    cache.respond(bypass)
    cache.respond(bypass)
    assert len(inner.calls) == 6


def test_image_request_predicate_and_scoring():
    records = [{"role": "replay_main", "subrole": "cursor", "req": "text"},
               {"role": "replay_main", "subrole": "cursor", "req": "image"},
               {"role": "aux", "subrole": "vision", "req": "refusal", "served": "refused_float"}]
    blobs = {"text": {"messages": [{"content": [{"type": "text", "text": "caption"}]}]},
             "image": {"messages": [{"content": [{"type": "image_url", "image_url": {"url": "data:fake"}}]}]},
             "refusal": {"float_keys": ["temperature"]}}
    assert run.image_requests(records, blobs) == records[1:]
    for kind, gold, answer in (("number", "12.30", "$12.30"), ("list", ["MUG", "LAMP"], "lamp,mug"),
                                ("number", "8080", "8080."), ("string", "A123", " a123. ")):
        assert run.score(kind, gold, answer)
    assert not run.score("number", "8080", "808")
    assert run.score("list", ["LAMP", "MUG"], "lamp,mug.")
    assert not run.score("list", ["LAMP", "MUG"], "lamp,mug..")


def fixture_paths(tmp_path):
    return {"home": tmp_path / "home", "workspace": tmp_path / "workspace", "attachments": {},
            "native_text": lambda text, path: text + " fixture attachment " + path}


def test_scripts_and_gold(tmp_path):
    from collections import Counter

    from bicentennial.contracts.run import scan_script, validate
    counts = Counter()
    for i in range(10):
        life = f"s8-life-{i:02d}"
        for c, k in run.channels(life).items():
            counts[c, k] += 1
        for mode in ("text", "native"):
            for branch in ("B0", "B1"):
                script = run.build_script(life, mode, branch=branch, paths=fixture_paths(tmp_path))
                validate("script", script)
                assert [s["kind"] for s in script["sessions"]] == ["replay"] * 5 + ["probe"]
                assert len(script["sessions"][-1]["turns"]) == 4
                assert all(t["assistant"] == "Noted." for s in script["sessions"][:5] for t in s["turns"])
                calls = script["sessions"][1]["turns"][1]["tool_calls"]
                assert len(calls) == 1 and calls[0]["name"] == "vision_analyze"
                assert calls[0]["args"]["question"] == run.ANALYSIS_PROMPT
                values = [v for b in ("B0", "B1") for r in run.world(life, b) for v in r["values"].values()]
                assert scan_script(script, [], values) == []
                for q in run.questions(life, branch):
                    rec = next(r for r in run.world(life, branch) if r["image_id"] == q["image_id"])
                    png, manifest = render.render(rec, "F0", "p08")
                    gold = q["gold"] if isinstance(q["gold"], list) else [q["gold"]]
                    assert all(v in [entry["value"] for entry in manifest] for v in gold)
                    assert render.verify(png, manifest)["recall_milli"] == 1000
    assert all(n >= 3 for (c, k), n in counts.items() if c != "screen")


def test_bootstrap_and_admission(monkeypatch):
    calls = []
    real = run.uniform_int
    def counted(*args):
        calls.append(args)
        return real(*args)
    monkeypatch.setattr(run, "uniform_int", counted)
    perfect = run.bootstrap("text", "D-F", [[(1, 0)]] * 10)
    assert perfect == {"n_draws": 10000, "lb": 1000, "ub": 1000}
    assert len(calls) == 100000
    assert {a[0] for a in calls} == {"p08-bootstrap"}
    calls.clear()
    fixture = [[(1, 0), (0, 0)], [(0, 1)]]
    got = run.bootstrap("native", "fixture", fixture)
    expected = []
    for b in range(10000):
        chosen = [fixture[real("p08-bootstrap", ("native", "fixture"), b, f"life#{j}", 0, 1)] for j in range(2)]
        values = [a - c for life in chosen for a, c in life]
        expected.append(1000 * sum(values) // len(values))
    expected.sort()
    assert got == {"n_draws": 10000, "lb": expected[500], "ub": expected[9499]}
    assert got == run.bootstrap("native", "fixture", fixture)
    fidelity = {"n": 200, "legible_milli": 950, "verifier_recall_milli": 990}
    bounds = {"D-F": {"lb": 300}, "S-F": {"ub": 100}}
    assert run.admission(fidelity, 40, 10, 8, bounds)["admitted"]
    for f, n, life_count, na, b in ((dict(fidelity, legible_milli=949), 40, 10, 8, bounds),
                           (dict(fidelity, verifier_recall_milli=989), 40, 10, 8, bounds),
                           (fidelity, 29, 10, 0, bounds), (fidelity, 40, 9, 0, bounds),
                           (fidelity, 40, 10, 9, bounds),
                           (fidelity, 40, 10, 8, dict(bounds, **{"D-F": {"lb": 299}})),
                           (fidelity, 40, 10, 8, dict(bounds, **{"S-F": {"ub": 101}}))):
        assert not run.admission(f, n, life_count, na, b)["admitted"]
    pending = run.admission({"n": 200, "state": "pending_human_key"}, 40, 10, 0, bounds)
    assert pending["state"] == "pending_human_key" and not pending["admitted"]
    mode = {"admission": {"admitted": True}, "channels": {"attachment": {"routed": True}, "workspace": {"routed": True}}}
    assert run.profile({"text": mode, "native": mode}) == "admitted"
    mode["channels"]["screen"] = {"not_run": "no_screen_tool"}
    assert run.profile({"text": mode, "native": mode}) == "pending"


def live_args(tmp_path):
    return ["live", "--mode", "text", "--scratch", str(tmp_path), "--hermes", str(tmp_path / "checkout"),
            "--glm-model", "text", "--vision-model", "vision", "--native-model", "vision",
            "--max-output", "10", "--max-output-source", "fixture"]


def test_guard_before_root_and_model_cap_refusals(tmp_path, monkeypatch):
    from bicentennial.runner.guard import Marker
    events = []
    monkeypatch.setattr(run, "reexec_niced", lambda argv: events.append("nice"))
    monkeypatch.setattr(run.time, "sleep", lambda s: events.append(s))
    for marker in (Marker(10, False, "busy"), Marker(0, False, "unset")):
        events.clear()
        monkeypatch.setattr(run, "read_marker", lambda marker=marker: events.append("marker") or marker)
        assert run.main(live_args(tmp_path)) == 3
        assert events[:2] == ["nice", "marker"]
        assert events.count(60) == 120
        assert list(tmp_path.glob("p08-*")) == []
    assert run.VISION_CAP == 10000000
    events.clear()
    assert run.main(live_args(tmp_path) + ["--vision-cap", "10000001"]) != 0
    args = live_args(tmp_path)
    args[args.index("--native-model") + 1] = "unprovisioned"
    assert run.main(args) != 0
    assert "marker" not in events


def test_paid_spend_reservations(tmp_path, monkeypatch):
    from threading import Event

    from bicentennial.director.upstream import (
        Holds,
        LiveResponder,
        Pacer,
        Upstream,
        forward,
    )
    from bicentennial.runner.guard import Marker
    from bicentennial.runner.spend import Price, Spend
    sends = []
    def send(up, data, headers):
        sends.append(data)
        return {"status": 200, "category": None, "retry_after_s": None, "body_shape": {}, "body_read_error": None,
                "n_unparsed": 0, "n_dropped_items": 0, "served_model": "vision", "usage": None,
                "text": "ok", "tool_calls": (), "forward": True, "stop_reason": None}
    monkeypatch.setattr(forward, "send", send)
    spend = Spend(tmp_path / "spend.json", 1000, Price(0, 400000000))
    up = Upstream("fake", "vision", "http://127.0.0.1:1/v1", "chat", spend, Price(0, 400000000), 1)
    live = LiveResponder("vision-0", Pacer(0, 1, Event()), lambda: {}, [up],
                         Holds(marker=lambda: Marker(0, False, "idle")))
    call = Call("aux", "vision", "chat", {"messages": []}, "vision", None, "key")
    assert [live.respond(call).served for _ in range(3)] == ["live", "live", "live_spend_stop"]
    assert len(sends) == 2 and json.loads(spend.path.read_bytes())["settled"] == 800
    assert live.state()["spend_stopped"]


def test_worker_config_and_attachment_modes(tmp_path, monkeypatch):
    import runpy
    import types

    from bicentennial.harness.hermes.config import hermes_config
    worker = runpy.run_path(str(Path(__file__).with_name("worker.py")))
    cfg = hermes_config(8000, "bicentennial-main")
    for mode in ("text", "native"):
        (tmp_path / "config.yaml").write_bytes(canon(cfg) + b"\n")
        worker["rewrite_config"](tmp_path, mode)
        got = json.loads((tmp_path / "config.yaml").read_bytes())
        expected = json.loads(canon(cfg))
        expected["platform_toolsets"]["acp"].append("vision")
        expected["agent"]["image_input_mode"] = mode
        if mode == "native":
            expected["model"]["supports_vision"] = True
        assert got == expected
        assert (tmp_path / "config.yaml").read_bytes() == canon(expected) + b"\n"
    routing = types.ModuleType("agent.image_routing")
    routing.build_native_content_parts = lambda text, paths: ([{"type": "text", "text": "wrong"}], [])
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.image_routing", routing)
    side = {"mode": "native", "attachments": {"scripted": {"text": "original", "paths": ["path"]}}}
    with pytest.raises(ValueError, match="native_text_mismatch"):
        worker["attachment_message"]("scripted", side)
    gateway = types.ModuleType("gateway.run")
    async def enrich(self, text, paths):
        return "description"
    gateway.GatewayRunner = types.SimpleNamespace(_enrich_message_with_vision=enrich)
    monkeypatch.setitem(sys.modules, "gateway", types.ModuleType("gateway"))
    monkeypatch.setitem(sys.modules, "gateway.run", gateway)
    side["mode"] = "text"
    assert worker["attachment_message"]("scripted", side) == [
        {"type": "text", "text": "description"}, {"type": "text", "text": "scripted"}]


CORE = runpy.run_path(str(run.REPO / "tests/director/test_core.py"))
UPSTREAM = runpy.run_path(str(run.REPO / "tests/director/test_upstream.py"))
no_egress = CORE["no_egress"]


def test_r08_classification_six_requests(tmp_path, no_egress):
    import base64
    from threading import Event

    from bicentennial.director.upstream import Holds, LiveResponder, Pacer, Upstream
    from bicentennial.runner.guard import Marker
    from bicentennial.runner.spend import Price, Spend
    fake = UPSTREAM["FakeUpstream"](UPSTREAM["Clock"](), [], default=(200, {}, UPSTREAM["chat"]()))
    spend = Spend(tmp_path / "spend.json", 0, Price(0, 0))
    ups = [Upstream("fake", name, fake.url, "chat", spend, Price(0, 0), 10) for name in ("vision", "probe-model")]
    live = LiveResponder("fixture", Pacer(0, 1, Event()), lambda: {}, ups,
                         Holds(marker=lambda: Marker(0, False, "idle")))
    old = CORE["ROUTES"]["routes"][0]["vision"]
    CORE["ROUTES"]["routes"][0]["vision"] = "vision"
    script = run.script_of("fixture", [
        {"index": 1, "kind": "replay", "turns": [run.turn("native fixture text", 1, "replay"),
         run.turn("plain scripted text", 2, "replay", [{"name": "vision_analyze", "args": {"image_url": "fixture.png", "question": run.ANALYSIS_PROMPT}}])]},
        {"index": 6, "kind": "probe", "turns": [run.turn("probe fixture", 1)]}])
    d = CORE["make"](tmp_path, live, script=script)
    post = CORE["post"]
    png, _ = render.render(run.world("s8-life-00")[0], "F0", "p08")
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}
    def body(user):
        return CORE["turn_body"](user, tools=("vision_analyze",))
    try:
        CORE["start"](d, tmp_path)
        assert post(d, "/main/v1/chat/completions", body([{"type": "text", "text": "native fixture text"}, image]))[0] == 200
        text_body = body([{"type": "text", "text": "fixture description"}, {"type": "text", "text": "plain scripted text"}])
        status, _, data = post(d, "/main/v1/chat/completions", text_body)
        assert status == 200
        msg = json.loads(data)["choices"][0]["message"]
        issued = msg["tool_calls"][0]["id"]
        aux = {"model": "bicentennial-aux-vision", "messages": [{"role": "user", "content": [image]}], "temperature": 0.1}
        status, _, data = post(d, "/aux/vision/v1/chat/completions", aux)
        assert status == 400 and json.loads(data)["error"]["message"] == "director: unsupported parameter: temperature"
        assert len(fake.seen) == 0
        del aux["temperature"]
        assert post(d, "/aux/vision/v1/chat/completions", aux)[0] == 200
        assert fake.seen[-1]["body"]["model"] == "vision"
        text_body["messages"] += [{"role": "assistant", "content": "", "tool_calls": msg["tool_calls"]},
                                  {"role": "tool", "tool_call_id": issued, "content": [image]}]
        assert post(d, "/main/v1/chat/completions", text_body)[0] == 200
        CORE["start"](d, tmp_path, 6)
        assert post(d, "/main/v1/chat/completions", body([{"type": "text", "text": "probe fixture"}, image]))[0] == 200
        records, blobs = run.ledger(tmp_path)
        assert [(r["role"], r["subrole"]) for r in records] == [
            ("replay_main", "cursor"), ("replay_main", "cursor"), ("aux", "vision"), ("aux", "vision"),
            ("replay_main", "tool_results"), ("probe_main", "cursor")]
        assert records[2]["served"] == "refused_float"
        assert len(records) == 6 and len(run.image_requests(records, blobs)) == 5
        assert sum(r["role"] == "unknown" for r in records) == 0
        assert all(r["cursor"] is None for r in records[2:4])
        assert len(fake.seen) == 2 and no_egress["outbound"] == 0
    finally:
        d.close()
        CORE["ROUTES"]["routes"][0]["vision"] = old
        fake.close()


def test_vision_probe_ledgered(tmp_path):
    responder = FakeResponder("visible settings")
    script = run.script_of("probe", [{"index": 1, "kind": "probe", "turns": [run.turn(run.ANALYSIS_PROMPT, 1)]}])
    d = run.Director(script, run.routes("text", "text", "vision"), "hermes-native", "probe", "B0", "probe", (),
                     responder, run.SimClock(tmp_path / "clock.json", run.BASE, run.STEP), run.Guard([]), {"sandbox_root": str(tmp_path), "director_port": "0"})
    try:
        d.start_session(1, run.BASE, "ab" * 32, "attempt", tmp_path / "ledger")
        assert run.probe_vision("vision", director=d) == {"model": "vision", "status": 200,
                                                         "served": "responder_fake", "answered": True}
        assert len(run.ledger(tmp_path)[0]) == 1
        assert responder.calls[0].model == "vision"
    finally:
        d.close()


def test_fake_worker_six_sessions_and_summary(tmp_path, monkeypatch, no_egress):
    import bicentennial.harness.hermes.adapter as adapter_module
    from bicentennial.runner.guard import Marker
    monkeypatch.setattr(run, "read_marker", lambda: Marker(0, False, "idle"))
    monkeypatch.setattr(adapter_module, "read_marker", lambda: Marker(0, False, "idle"))
    monkeypatch.setattr(adapter_module, "DRAIN_QUIET_S", 0.01)
    monkeypatch.setattr(run, "reexec_niced", lambda argv: None)
    fake = UPSTREAM["FakeUpstream"](UPSTREAM["Clock"](), [], default=(200, {}, UPSTREAM["chat"]()))
    monkeypatch.setenv("BICENTENNIAL_UPSTREAM_OPENAI_URL", fake.url)
    monkeypatch.setenv("BICENTENNIAL_UPSTREAM_KEY", "fixture-synthetic-key")
    cache, responders = run.provision(tmp_path, "text", "vision", 10)
    inputs = {"script_hashes": {}, "hermes_pin": run.load_entry()["artifact"], "hermes_commit": "fixture",
              "models": {"glm": "text", "vision": "vision", "native": "vision"}}
    try:
        try:
            root = run.run_arm(tmp_path, "text", "s8-life-00", "M", cache, responders, run.routes("text", "text", "vision"),
                               tmp_path / "unused-checkout", inputs, run.time.monotonic(),
                               worker_argv=[sys.executable, str(run.REPO / "tests/harness/fake_worker.py")])
        except run.Stopped as exc:
            logs = list(tmp_path.glob("p08-*/logs/*.stderr"))
            if exc.code == "HarnessFailed:worker_start" and any(
                    "taskpolicy: setpriority(): Operation not permitted" in path.read_text() for path in logs):
                pytest.skip("sandbox denies taskpolicy/setpriority; dispatcher must rerun fake worker")
            raise
        receipt = json.loads((root / "receipt.json").read_bytes())
        assert [s["index"] for s in receipt["sessions"]] == list(range(1, 7))
        assert len(receipt["answers"]) == 4
        assert list((root / "home/.s8-inbox").glob("*.png")) == []
        assert len(list((root / "workspace").glob("*.png"))) == 1
        key = tmp_path / "fidelity.json"
        key.write_bytes(canon({"n": 200, "state": "pending_human_key"}))
        out = tmp_path / "s8.json"
        assert run.main(["summarise", "--scratch", str(tmp_path), "--fidelity", str(key), "--out", str(out)]) == 0
        summary = json.loads(out.read_bytes())
        assert summary["operating"]["unknown_total"] == 0
        assert summary["admission"]["profile"] == "pending"
        assert summary["modes"]["text"]["channels"]["screen"]["not_run"] == "no_screen_tool"
        assert run.main(["summarise", "--scratch", str(tmp_path), "--fidelity", str(key), "--out", str(out)]) != 0
        assert no_egress["outbound"] == 0
    finally:
        fake.close()


def test_worker_protocol_with_fake_module_tree(tmp_path):
    module_files = {
        "acp_adapter/__init__.py": "",
        "acp_adapter/entry.py": '''
import json, os
from pathlib import Path
cfg = json.loads((Path(os.environ['HERMES_HOME']) / 'config.yaml').read_text())
assert 'vision' in cfg['platform_toolsets']['acp']
assert cfg['agent']['image_input_mode'] in ('native', 'text')
def _load_env(): pass
def _setup_logging(): pass
''',
        "agent/__init__.py": "",
        "agent/ssl_verify.py": "def install_truststore(): pass\n",
        "agent/image_routing.py": '''
def build_native_content_parts(text, paths):
    return ([{'type': 'text', 'text': text + ' fixture attachment ' + paths[0]}], [])
''',
        "gateway/__init__.py": "",
        "gateway/run.py": '''
class GatewayRunner:
    async def _enrich_message_with_vision(self, text, paths):
        return 'fixture description'
''',
        "gateway/session_context.py": "def set_session_vars(**kw): return ()\ndef clear_session_vars(tokens): pass\n",
        "acp_adapter/session.py": '''
from types import SimpleNamespace
class SessionManager:
    def create_session(self, cwd):
        class Agent:
            def run_conversation(self, **kw):
                message = kw['user_message']
                assert message[0]['text'] == 'fixture description'
                assert message[1]['text'] == 'scripted'
                return {'messages': [], 'final_response': 'Noted.'}
        return SimpleNamespace(agent=Agent(), history=[], cwd=cwd, session_id='fixture')
    def save_session(self, sid): pass
    def end_all_sessions(self): pass
''',
    }
    modules = tmp_path / "modules"
    for name, code in module_files.items():
        path = modules / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code)
    worker = Path(__file__).with_name("worker.py").resolve()
    for mode in ("text", "native"):
        home = tmp_path / mode
        home.mkdir()
        (home / "config.yaml").write_bytes(canon({"platform_toolsets": {"acp": []}, "agent": {}, "model": {}}))
        side = tmp_path / f"{mode}-side.json"
        side.write_bytes(canon({"mode": mode, "attachments": {"scripted": {"text": "original", "paths": ["fixture.png"]}}}))
        commands = [{"op": "open", "session_id": None, "cwd": str(home)}, {"op": "turn", "text": "scripted"}, {"op": "end"}]
        proc = subprocess.run([sys.executable, str(worker), str(side)],
                              input="".join(json.dumps(op) + "\n" for op in commands), capture_output=True, text=True,
                              env={"PATH": os.defpath, "PYTHONPATH": str(modules), "HOME": str(home), "HERMES_HOME": str(home)}, check=True)
        ready, opened, answered, ended = [json.loads(line) for line in proc.stdout.splitlines()]
        assert ready["ready"] and opened["ok"] and ended["ok"]
        assert answered["ok"] == (mode == "text")
        assert answered["error"] == ("native_text_mismatch" if mode == "native" else None)
    proc = subprocess.run([sys.executable, str(worker), "--native-text", "sentence", "fixture.png"],
                          env={"PATH": os.defpath, "PYTHONPATH": str(modules)}, capture_output=True, text=True, check=True)
    assert proc.stdout == "sentence fixture attachment fixture.png\n"


def test_provision_separates_price_policies(tmp_path, monkeypatch):
    monkeypatch.setenv("BICENTENNIAL_UPSTREAM_OPENAI_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("BICENTENNIAL_VISION_URL", "http://127.0.0.1:2/v1")
    paid, free = tmp_path / "paid", tmp_path / "free"
    paid.mkdir()
    free.mkdir()
    _, responders = run.provision(paid, "text", "vision", 10, paid=True, price=run.Price(1, 2))
    assert [r.account for r in responders] == ["glm-0", "vision-0"]
    assert json.loads((paid / "vision-spend.json").read_bytes())["policy"] == {
        "cap": 10000000, "price": {"input_per_million": 1, "output_per_million": 2}}
    cache, responders = run.provision(free, "text", "vision", 10)
    assert len(responders) == 1
    assert cache.inner.models["text"] is cache.inner.models["vision"]
    assert all(up.glm_plan and not up.send_cap for up in responders[0].upstreams.values())
    assert not (free / "vision-spend.json").exists()


def test_summary_identity_attribution_cost_cache_and_controls(tmp_path, monkeypatch):
    import base64
    life = "s8-life-00"
    data = {}
    images = {r["kind"]: render.render(r, "F0", "p08")[0] for r in run.world(life)}
    def img(kind):
        return {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(images[kind]).decode()}}
    for mode in ("text", "native"):
        for arm in ("M", "D", "F", "T", "H", "R"):
            root = tmp_path / f"p08-{mode}-{life}-{arm}"
            root.mkdir()
            qs = run.questions(life)
            receipt = {"mode": mode, "life": life, "arm": arm, "answers": {q["id"]: arm != "F" for q in qs},
                       "shuffled": {q["id"]: False for q in qs}, "inputs": {"script_hashes": {}, "hermes_pin": {},
                       "hermes_commit": "fixture", "models": {}}, "egress": {"non_loopback": []}, "states": [],
                       "identities": [], "sessions": [], "marker": [], "wall_ms": 1, "stop": None,
                       "cache_events": [{"hit": False}, {"hit": True}] if arm == "M" else []}
            (root / "receipt.json").write_bytes(canon(receipt))
            records, blobs = [], {}
            if arm == "M":
                for turn_n, channel in enumerate(("attachment", "workspace"), 1):
                    kind = run.channels(life)[channel]
                    req, resp, upresp = f"request{turn_n}", f"response{turn_n}", f"upresponse{turn_n}"
                    blobs[req], blobs[resp], blobs[upresp] = {"content": [img(kind)]}, {}, {"text": "fixture PRIVATE_CAPTION " + " ".join(str(q["gold"]) for q in qs)}
                    records.append({"type": "request", "seq": len(records) + 1, "req": req, "resp": resp, "attempt_id": "s2",
                                    "role": "aux", "subrole": "vision", "cursor": None, "status": 200, "served": "responder_live",
                                    "upstream": [{"resp": upresp, "diagnostics": [{"kind": "try", "sent": True, "reserved": 50,
                                                                                 "charged": 20, "t_ms": 7}]}]})
                    records.append({"type": "request", "seq": len(records) + 1, "req": "main", "resp": "mainresp", "attempt_id": "s2",
                                    "role": "replay_main", "subrole": "cursor", "cursor": {"session": 2, "turn": turn_n},
                                    "status": 200, "served": "script", "upstream": []})
                blobs["main"], blobs["mainresp"] = {}, {}
            data[root.name] = (records, blobs)
    monkeypatch.setattr(run, "ledger", lambda root: data[Path(root).name])
    # Fixture image families deliberately use F0; inject their identity into the local image source.
    originals = list(run.images())
    for image in originals:
        if image["record"]["life"] == life and image["branch"] == "B0":
            image["png"] = images[image["record"]["kind"]]
    monkeypatch.setattr(run, "images", lambda: iter(originals))
    result = run.summarise(tmp_path, {"n": 200, "legible_milli": 1000, "verifier_recall_milli": 1000})
    assert result["operating"]["unknown_total"] == 0
    assert result["admission"]["profile"] == "pending"
    for mode in ("text", "native"):
        view = result["modes"][mode]
        assert view["channels"]["attachment"]["routed"] and view["channels"]["workspace"]["routed"]
        assert view["accuracy"]["M"] == {"n": 4, "milli": 1000}
        assert view["accuracy"]["S"] == {"n": 4, "milli": 0}
        assert view["na_reader"] == 0
        assert view["projection"]["microdollars"] == 3200
        row = next(row for row in view["rows"] if row["arm"] == "M")
        assert row["cache_hits"] == 1
        assert len(row["vision_calls"]) == 1
    assert result["modes"]["native"]["accuracy"]["R"] == {"not_applicable": True}
    assert b"PRIVATE_CAPTION" not in canon(result)
    assert b"gold" not in canon(result)


def test_boundary_stop_rules(tmp_path):
    from types import SimpleNamespace
    state = {"identity_drift": None, "stopped": False, "spend_stopped": False, "stop_reason": None}
    responder = SimpleNamespace(state=lambda: state, upstreams={}, holds=SimpleNamespace(active={}))
    for field, value, code in (("identity_drift", {"model": "changed"}, "identity_drift"),
                               ("stopped", True, "upstream_401"), ("spend_stopped", True, "live_spend_stop")):
        state[field] = value
        state["stop_reason"] = "upstream_401" if field == "stopped" else None
        with pytest.raises(run.Stopped, match=code):
            run.boundary([responder], run.time.monotonic())
        state[field] = False if field != "identity_drift" else None
    responder.holds.active = {"run": {"quota": 1}}
    with pytest.raises(run.Stopped, match="quota_hold"):
        run.boundary([responder], run.time.monotonic())
    with pytest.raises(run.Stopped, match="MODE_WALL_S"):
        run.boundary([], run.time.monotonic() - run.MODE_WALL_S)
    with pytest.raises(run.Stopped, match="non_loopback"):
        run.boundary([], run.time.monotonic(), {"non_loopback": ["fixture"]})


def test_all_arm_scripts_and_delivery_with_adapter_double(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bicentennial.harness.hermes.config import layout
    from bicentennial.runner.guard import Marker
    made = []
    class Adapter:
        def __init__(self, entry, **kw):
            self.kw, self.paths = kw, layout(kw["root"], kw["scratch"])
            self.egress = SimpleNamespace(summary=lambda: {"non_loopback": []})
            self.session_count = 0
            made.append(self)
            assert kw["kill_mode"] == "boundary"
            assert all(Path(p).is_absolute() for p in kw["worker_argv"])
            assert kw["write_prompt"] == runpy.run_path(str(run.REPO / "spikes/s7/readback.py"))["SUFFIX"]
            self.side = json.loads(Path(kw["worker_argv"][-1]).read_bytes())
        def run_session(self, i, **kw):
            assert kw["sim_t_s"] == run.BASE + i * run.DAY
            self.session_count += 1
            session = next(s for s in self.kw["script"]["sessions"] if s["index"] == i)
            if i == 2:
                assert len(list(self.paths["workspace"].glob("*.png"))) == 1
                assert len(list((self.paths["home"] / ".s8-inbox").glob("*.png"))) == 1
            if i in (3, 4, 5) or (i == 6 and self.kw["run"].endswith(("-M", "-T"))):
                assert list((self.paths["home"] / ".s8-inbox").glob("*.png")) == []
            if i == 1:
                assert list(self.paths["workspace"].glob("*.png")) == []
            qs = run.questions(self.kw["life"], self.kw["branch"])
            users = [t["user"] for t in session["turns"]]
            qs = [q for q in qs if any(q["user"] in u for u in users)]
            finals = [(n, ",".join(q["gold"]) if isinstance(q["gold"], list) else q["gold"]) for n, q in enumerate(qs, 1)] if i == 6 else [(t["n"], "Noted.") for t in session["turns"]]
            assert len(finals) == len(session["turns"])
            return SimpleNamespace(finals=finals, gate=(), timings_ms={})
        def records(self):
            return []
        def close(self):
            return {"non_loopback": []}
    monkeypatch.setattr(run, "HermesAdapter", Adapter)
    monkeypatch.setattr(run, "read_marker", lambda: Marker(0, False, "idle"))
    monkeypatch.setattr(run.subprocess, "run", lambda argv, **kw: SimpleNamespace(stdout=argv[-2] + " fixture attachment " + argv[-1] + "\n"))
    for mode in ("text", "native"):
        for arm in ("M", "T", "F", "D", "H", *(["R"] if mode == "text" else [])):
            kinds = [k for c, k in run.channels("s8-life-00").items() if c != "screen"] if arm in ("D", "H") else [None]
            for kind in kinds:
                root = run.run_arm(tmp_path, mode, "s8-life-00", arm, run.CaptionCache(FakeResponder("unused")), [],
                                   run.routes(mode, "text", "vision"), tmp_path / "checkout",
                                   {"script_hashes": {}, "hermes_pin": {}, "hermes_commit": "fixture", "models": {}},
                                   run.time.monotonic(), image_kind=kind, descriptions=["fixture notes"])
                receipt = json.loads((root / "receipt.json").read_bytes())
                assert all(receipt["answers"].values())
                assert made[-1].session_count == (6 if arm in ("M", "T") else 1)
                if arm == "T":
                    assert not any(receipt["shuffled"].values())
                if arm in ("D", "H"):
                    attached = next(iter(made[-1].side["attachments"].values()))["paths"][0]
                    record = next(r for r in run.world("s8-life-00") if r["kind"] == kind)
                    family = "F4" if arm == "H" else f"F{render.presentation(record, 'p08')['family']}"
                    assert Path(attached).read_bytes() == render.render(record, family, "p08")[0]


def test_rag_ties_and_keysheet_cli(tmp_path, monkeypatch):
    assert run.rag("port mode", ["PORT active", "unrelated"]) == "PORT active"
    assert run.rag("unmatched", ["first", "second"]) == "first"
    monkeypatch.setattr(run, "reexec_niced", lambda argv: None)
    out = tmp_path / "keysheet"
    assert run.main(["keysheet", "--out", str(out)]) == 0
    assert len(list(out.glob("crop-*.png"))) == 200
    with (out / "key.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 200 and all(row["typed"] == "" for row in rows)
    target = tmp_path / "fidelity.json"
    assert run.main(["fidelity", "--key", str(out / "key.csv"), "--out", str(target)]) == 0
    assert json.loads(target.read_bytes()) == {"n": 200, "state": "pending_human_key"}


def test_captions_only_use_session_two(tmp_path, monkeypatch):
    import base64
    png, _ = render.render(run.world("s8-life-00")[0], "F0", "p08")
    digest = sha256(png).hexdigest()
    blob = {"content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]}
    records = [{"attempt_id": "s2", "cursor": {"session": 2}},
               {"attempt_id": "s6", "cursor": {"session": 6}},
               {"attempt_id": "s2", "cursor": None, "role": "aux", "subrole": "vision", "status": 200,
                "req": "image", "upstream": [{"resp": "original"}]},
               {"attempt_id": "s6", "cursor": None, "role": "aux", "subrole": "vision", "status": 200,
                "req": "image", "upstream": [{"resp": "later"}]}]
    monkeypatch.setattr(run, "ledger", lambda root: (records, {"image": blob, "original": {"text": "session two"},
                                                              "later": {"text": "question-time reinspection"}}))
    assert run.captions(tmp_path, {digest: "settings"}) == {"settings": "session two"}
