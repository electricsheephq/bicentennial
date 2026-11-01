"""Offline acceptance for the v0.1 run-side wire contracts."""

import copy
import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import FORBIDDEN, NAMES, SCHEMAS, scan_script, validate
from bicentennial.contracts.surfaces import tree_hash, tree_listing

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "run"
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
# Each unit keeps a contracts.json registry beside its own fixtures, so a later
# schema needs no edit here; every contract name must appear in exactly one.
REGISTRIES = sorted([*ROOT.glob("tests/fixtures/*/contracts.json"),
                     *ROOT.glob("schemas/fixtures/*/contracts.json")])


def fixture(name):
    found = [registry["contracts"][name] for registry in
             (json.loads(path.read_bytes()) for path in REGISTRIES)
             if name in registry["contracts"]]
    assert len(found) == 1, f"{name}: {len(found)} fixture registry entries, expected 1"
    return found[0]


def test_every_registry_carries_the_canary_and_known_names():
    for path in REGISTRIES:
        registry = json.loads(path.read_bytes())
        assert registry["canary"] == CANARY, path.parent.name
        assert set(registry["contracts"]) <= NAMES, path.parent.name


def compile_micro_life(life):
    """Project public spike turns only; no facts, events or probe answers."""
    sessions = []
    for kind, source in (("replay", life["sessions"]), ("probe", life["probes"])):
        for session in source:
            sessions.append({"index": len(sessions) + 1, "kind": kind, "turns": [
                {"n": n, "kind": kind, "user": turn["user"],
                 "assistant": turn.get("assistant"), "tool_calls": []}
                for n, turn in enumerate(session["turns"], 1)
            ]})
    return {"canary": CANARY, "life_id": "s6a-micro", "genre": life["genre"],
            "harness": "hermes", "sessions": sessions}


@pytest.mark.parametrize("name", sorted(NAMES))
def test_contract_fixtures_validate(name):
    validate(name, fixture(name))


def test_additional_properties_schema():
    receipt = fixture("receipt")
    receipt["egress_failed_samples"] = {"ValueError": 0, "OSError": 2}
    validate("receipt", receipt)
    for value in (-1, "1", True):
        receipt["egress_failed_samples"]["ValueError"] = value
        with pytest.raises(ValueError, match=r'\$\["egress_failed_samples"\]\["ValueError"\]'):
            validate("receipt", receipt)


ENTRY_KEYS = ("arm", "life", "branch", "attempt", "pin_check_ms",
              "egress_pid_samples", "egress_sample_ms", "sessions")
SESSION_KEYS = ("session", "kind", "wall", "gate", "egress_wait", "spawn", "import",
                "open", "turn", "drain", "resume", "shutdown_hook", "close", "finish", "workspace")
NULLABLE = {"egress_pid_samples", "egress_sample_ms", "wall", "shutdown_hook",
            "close", "finish", "workspace"}
ARRAYS = {"gate", "egress_wait", "spawn", "import", "open", "turn", "drain", "resume"}


def timing_receipt():
    receipt = fixture("receipt")
    session = dict.fromkeys(SESSION_KEYS, 0)
    session.update(kind="replay", **{k: [0] for k in ARRAYS})
    entry = dict.fromkeys(ENTRY_KEYS, 0)
    entry.update(arm="system", life="life", branch="B0", sessions=[session])
    receipt["timings"] = [entry]
    validate("receipt", receipt)
    return receipt


@pytest.mark.parametrize("level,key", [*(("entry", k) for k in ENTRY_KEYS),
                                         *(("session", k) for k in SESSION_KEYS)])
def test_timing_fields_required_and_closed(level, key):
    receipt = timing_receipt()
    entry = receipt["timings"][0]
    target = entry if level == "entry" else entry["sessions"][0]
    old = target.pop(key)
    with pytest.raises(ValueError):
        validate("receipt", receipt)
    target[key] = old
    target["extra"] = 0
    with pytest.raises(ValueError):
        validate("receipt", receipt)


@pytest.mark.parametrize("level,key", [*(("entry", k) for k in ENTRY_KEYS if k not in {"sessions", "arm", "life", "branch"}),
                                         *(("session", k) for k in SESSION_KEYS if k not in {"kind", "session"} or k == "session")])
def test_timing_value_types_and_bounds(level, key):
    receipt = timing_receipt()
    row = receipt["timings"][0]
    target = row if level == "entry" else row["sessions"][0]
    old = target[key]
    if key in NULLABLE:
        target[key] = None
        validate("receipt", receipt)
    else:
        target[key] = None
        with pytest.raises(ValueError):
            validate("receipt", receipt)
    for bad in (-1, True):
        target[key] = [bad] if key in ARRAYS else bad
        with pytest.raises(ValueError):
            validate("receipt", receipt)
    target[key] = old


@pytest.mark.parametrize("level,key", [("entry", k) for k in ("arm", "life", "branch")] + [("session", "kind")])
def test_timing_names_nonempty(level, key):
    for bad in ("", None):
        receipt = timing_receipt()
        row = receipt["timings"][0]
        (row if level == "entry" else row["sessions"][0])[key] = bad
        with pytest.raises(ValueError):
            validate("receipt", receipt)


def test_timing_import_nullable_item_and_receipt_required():
    receipt = timing_receipt()
    receipt["timings"][0]["sessions"][0]["import"] = [None, 0]
    validate("receipt", receipt)
    receipt["timings"][0]["sessions"] = None
    with pytest.raises(ValueError):
        validate("receipt", receipt)
    del receipt["timings"]
    with pytest.raises(ValueError):
        validate("receipt", receipt)


def test_micro_life_converts_to_canonical_script(tmp_path):
    source = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
    script = compile_micro_life(source)
    path = tmp_path / "script.json"
    path.write_bytes(canon(script))
    validate("script", json.loads(path.read_bytes()))
    assert len(script["sessions"]) == len(source["sessions"]) + len(source["probes"])
    assert {s["kind"] for s in script["sessions"]} == {"replay", "probe"}
    assert script["sessions"][-1]["turns"][0]["assistant"] is None
    assert scan_script(script, [f["id"] for f in source["facts"]], []) == []
    assert not {"facts", "events", "probes"} & script.keys()
    assert canon(json.loads(path.read_bytes())) == path.read_bytes()


@pytest.mark.parametrize("director", ["s6a/director.py", "s6b/sol_director.py"])
def test_spike_request_field_projection(director):
    """Specimens follow the directors' field lists, not a live harness run."""
    source = (ROOT / "spikes" / director).read_text()
    ledger_source = (ROOT / "spikes/s6a/director.py").read_text()
    rec = fixture("ledger-record")
    # Explicit conversion from the spike's seconds/loadavg float wire format.
    spike = {"t": 1720000000.125, "load": [0.125, 1.2345, 2.3455]}
    rec["t"] = round(spike["t"] * 1000)
    rec["load"] = [round(x * 1000) for x in spike["load"]]
    rec.update(write_turn_readback=True, write_calls=1,
               write_turn_failed="budget_or_stop", client_disconnected=False)
    rec["path"] = "/v1/responses" if "s6b" in director else "/v1/chat/completions"
    for key in ("type", "run", "seq", "t", "t_ms", "hash", "prev_hash", "method",
                "path", "role", "subrole", "cursor", "status", "req", "resp",
                "req_chars", "n_tools", "model_in", "served", "upstream", "load",
                "client_disconnected", "write_turn_readback", "write_turn_failed",
                "write_calls"):
        origin = ledger_source if key in {"seq", "hash", "prev_hash"} else source
        assert f'"{key}"' in origin or key in {"req", "resp", "status"}
    # S6b counts Responses input items; R08 normalises that count to n_messages.
    count_key = "n_items" if "s6b" in director else "n_messages"
    assert f'"{count_key}"' in source
    if "s6b" in director:
        assert '"in_headers"' in source
        rec["incoming_auth_dropped"] = True
    validate("ledger-record", rec)
    assert rec["t"] == 1720000000125
    assert len(rec["load"]) == 3
    assert canon(json.loads(canon(rec))) == canon(rec)


@pytest.mark.parametrize("key", sorted(FORBIDDEN))
@pytest.mark.parametrize("nested", [False, True])
def test_script_forbidden_keys_including_open_arguments(key, nested):
    script = fixture("script")
    if nested:
        script["sessions"][0]["turns"][0]["tool_calls"][0]["args"]["x"] = [{key: "x"}]
    else:
        script[key] = "x"
    with pytest.raises(ValueError):
        validate("script", script)


def test_script_string_scan_returns_all_paths_once():
    script = fixture("script")
    turn = script["sessions"][0]["turns"][0]
    turn["user"] = "seen event-sealed then GOLD-9201"
    turn["assistant"] = "fact-sealed is here"
    turn["tool_calls"][0]["args"]["nested"] = ["GOLD-9201", {"text": "event-sealed"}]
    validate("script", script)
    prefix = '$["sessions"][0]["turns"][0]'
    assert scan_script(script, ["event-sealed", "fact-sealed"], ["GOLD-9201"]) == [
        prefix + '["assistant"]',
        prefix + '["tool_calls"][0]["args"]["nested"][0]',
        prefix + '["tool_calls"][0]["args"]["nested"][1]["text"]',
        prefix + '["user"]',
    ]
    assert scan_script(script, ["EVENT-SEALED"], ["absent"]) == []


def test_tree_listing_volatile_content_modes_and_links(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_text("never traverse")
    (root / "store").mkdir()
    data = root / "store" / "memory"
    data.write_bytes(b"before")
    data.chmod(0o640)
    (root / "logs").mkdir()
    (root / "logs" / "volatile").write_text("ignored")
    (root / "runtime.lock").write_text("ignored")
    (root / "logs-kept").write_text("keep")
    (root / "link").symlink_to("../outside", target_is_directory=True)
    (root / "dangling").symlink_to("missing")
    listing = tree_listing(root, ["logs", "runtime.lock"])
    by_path = {row["path"]: row for row in listing}
    assert list(by_path) == sorted(by_path)
    assert not {"logs", "logs/volatile", "runtime.lock", "link/secret"} & by_path.keys()
    assert by_path["link"] == {"path": "link", "kind": "symlink", "target": "../outside"}
    assert by_path["dangling"]["target"] == "missing"
    assert by_path["store/memory"] == {"path": "store/memory", "kind": "file",
        "mode": 0o640, "size": 6, "sha256": sha256(b"before").hexdigest()}
    digest = tree_hash(listing)
    assert digest == sha256(canon(listing)).hexdigest()
    (root / "logs" / "volatile").write_text("changed")
    (outside / "secret").write_text("changed")
    assert tree_hash(tree_listing(root, ["logs", "runtime.lock"])) == digest
    data.write_bytes(b"after!")
    assert tree_hash(tree_listing(root, ["logs", "runtime.lock"])) != digest
    with pytest.raises(ValueError):
        tree_listing(root / "link", [])


@pytest.mark.parametrize("path", ["/absolute", "../escape", "a/../b", "a//b", "a\\b", ".", "a/./b"])
def test_surface_rejects_unsafe_paths(tmp_path, path):
    with pytest.raises(ValueError):
        tree_listing(tmp_path, [path])


def test_tree_listing_rejects_special_files(tmp_path):
    import os

    os.mkfifo(tmp_path / "pipe")
    with pytest.raises(ValueError, match="unsupported surface entry"):
        tree_listing(tmp_path, [])


def test_ledger_stability_tags_and_units():
    schema = json.loads((SCHEMAS / "ledger-record.schema.json").read_bytes())

    def visit(node):
        if isinstance(node, dict):
            for prop in node.get("properties", {}).values():
                assert prop["x-stability"] in {"stable", "volatile"}
                assert prop["description"]
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(schema)
    props = schema["properties"]
    for name in ("t", "t_ms", "load", "seq", "req", "resp"):
        assert props[name]["x-stability"] == "volatile"
    for name in ("role", "cursor", "served", "served_by", "life", "branch", "system",
                 "lock_hash", "attempt_id", "sim_now", "req_masked_sha256", "resp_masked_sha256"):
        assert props[name]["x-stability"] == "stable"
    assert "milliseconds" in props["t"]["description"]
    assert "milliseconds" in props["t_ms"]["description"]
    assert "1000" in props["load"]["description"]


def test_canonical_fixture_bytes_and_schema_defaults():
    for path in [*FIXTURES.glob("*.json"), *SCHEMAS.glob("*.schema.json"),
                 ROOT / "src/bicentennial/contracts/masks.json"]:
        raw = path.read_bytes()
        obj = json.loads(raw)
        assert canon(obj) == raw
        if path.parent == FIXTURES:
            assert obj["canary"] == CANARY


@pytest.mark.parametrize("name", sorted(NAMES))
def test_float_rejected_in_every_contract(name):
    value = fixture(name)
    if isinstance(value, list):
        value[0]["float"] = 0.5
    else:
        value["float"] = 0.5
    with pytest.raises(ValueError, match="float"):
        validate(name, value)


def test_open_payloads_still_reject_floats_and_foreign_templates():
    system = fixture("system")
    system["recall"]["argument_template"]["nested"] = [{"q": "before {prompt} after"}]
    validate("system", system)
    for value in ("{fact_id}", "{prompt} {other}", "{{prompt}}"):
        system["recall"]["argument_template"]["nested"] = [value]
        with pytest.raises(ValueError, match="only"):
            validate("system", system)
    for part in ("args", "argument_template", "schema", "upstream"):
        value = fixture("script" if part == "args" else "ledger-record" if part == "upstream" else "system")
        if part == "args":
            value["sessions"][0]["turns"][0]["tool_calls"][0][part]["x"] = [0.5]
        elif part == "argument_template":
            value["recall"][part]["x"] = 0.5
        elif part == "schema":
            value["structured_formats"]["extraction"][part]["default"] = 0.5
        else:
            value[part] = [{"x": 0.5}]
        with pytest.raises(ValueError, match="float"):
            validate("script" if part == "args" else "ledger-record" if part == "upstream" else "system", value)


@pytest.mark.parametrize("name,edit", [
    ("script", lambda v: v["sessions"][0].update(extra=True)),
    ("script", lambda v: v["sessions"][0]["turns"][0].update(n=True)),
    ("script", lambda v: v["sessions"][0]["turns"][0].update(kind="probe")),
    ("ledger-record", lambda v: v.update(load=[1, 2])),
    ("ledger-record", lambda v: v.update(type="send_error")),
    ("ledger-record", lambda v: v.update(status=-1)),
    ("ledger-record", lambda v: v.update(cursor={"session": 1})),
    ("route-table", lambda v: v["routes"].append(copy.deepcopy(v["routes"][0]))),
    ("route-table", lambda v: v["routes"][0].update(vision="")),
    ("route-table", lambda v: v["routes"][0].update(segment="invalid space")),
    ("fault-lite", lambda v: v[0].update(turn=0)),
    ("surfaces", lambda v: v.reverse()),
    ("surfaces", lambda v: v[0].update(mode=0o10000)),
    ("surfaces", lambda v: v[1].pop("sha256")),
    ("surfaces", lambda v: v[2].update(size=0)),
    ("lock", lambda v: v.update(tool_lists_hash="bad")),
    ("lock", lambda v: v.update(seeds=[True])),
    ("lock", lambda v: v.update(account_pool=[{"credential": "dummy"}])),
    ("system", lambda v: v.update(name="LCM-X", benchmark_operator_runs=True)),
    ("system", lambda v: v["recall"].update(tool="undeclared")),
    ("system", lambda v: v["own_model_routes"].clear()),
    ("system", lambda v: v["structured_formats"].update(other={"kind": "text", "schema": None})),
])
def test_invalid_structural_and_semantic_cases(name, edit):
    value = fixture(name)
    edit(value)
    with pytest.raises(ValueError):
        validate(name, value)


def test_nullable_fields_and_lcmx_registration():
    ledger = fixture("ledger-record")
    ledger["cursor"] = None
    validate("ledger-record", ledger)
    system = fixture("system")
    system.update(name="LCM-X", benchmark_operator_runs=False, embedding_dim=1536)
    system["structured_formats"]["extraction"] = {"kind": "text", "schema": None}
    validate("system", system)
    with pytest.raises(ValueError, match="unknown contract"):
        validate("../script", {})


def test_masks_cover_required_categories_and_exclude_director_tool_ids():
    masks = json.loads((ROOT / "src/bicentennial/contracts/masks.json").read_bytes())
    validate("masks", masks)
    assert masks == fixture("masks")
    names = {m["name"] for m in masks}
    assert {"hermes-session", "harness-tool-call", "harness-function-call",
            "harness-response", "harness-root-response", "harness-stream-response",
            "wall-clock-t", "wall-clock-created", "random-uuid", "random-uuid-hex-file", "sandbox-root",
            "director-port"} <= names
    for entry in masks:
        if entry["placeholder"] in {"{HERMES_SESSION_ID}", "{HARNESS_TOOL_CALL_ID}",
                                    "{HARNESS_RESPONSE_ID}"}:
            assert entry["except_prefix"] == "bcw-"
        assert entry["target"] != "bcw-"
        assert not entry["placeholder"].startswith("bcw-")
    assert [m["target"] for m in masks if m["kind"] == "run_value"] == [
        "sandbox_root", "director_port"]


@pytest.mark.parametrize("target", ['$[?(@ == $.id)]', '$..[?(@.x)].y', 'session_id', '$.a b'])
def test_mask_targets_outside_the_path_subset_are_refused(target):
    masks = [{"name": "m", "kind": "jsonpath", "target": target, "placeholder": "{X}"}]
    with pytest.raises(ValueError):
        validate("masks", masks)


def test_patterns_full_match_so_a_trailing_newline_is_refused():
    system = copy.deepcopy(fixture("system"))
    system["artifact"]["sha256"] += "\n"
    with pytest.raises(ValueError, match="pattern"):
        validate("system", system)


def test_scan_script_reports_sealed_text_in_object_keys():
    script = copy.deepcopy(fixture("script"))
    turn = script["sessions"][0]["turns"][0]
    turn["tool_calls"] = [{"name": "mem", "args": {"bcw-fact-0001": "x", "q": "gold-token"}}]
    hits = scan_script(script, ["bcw-fact-0001"], ["gold-token"])
    assert any(h.endswith('["bcw-fact-0001"]') for h in hits)
    assert any(h.endswith('["q"]') for h in hits)


def test_a_system_without_recall_declares_null():
    system = copy.deepcopy(fixture("system"))
    system.update(recall=None, read_tools=[])
    validate("system", system)


def test_names_come_from_schema_files_and_checks_can_be_registered(monkeypatch):
    from bicentennial.contracts import run
    assert run.NAMES == {p.name.removesuffix(".schema.json") for p in SCHEMAS.glob("*.schema.json")}
    with pytest.raises(ValueError, match="unknown contract"):
        run.register_check("../script", lambda obj: None)
    seen = []
    monkeypatch.setattr(run, "_CHECKS", {})
    run.register_check("fault-lite", seen.append)
    validate("fault-lite", fixture("fault-lite"))
    assert seen == [fixture("fault-lite")]


@pytest.mark.parametrize("target", ["(x)", "(?P<p0>x)", "[", "x*", "(?i)abc"])
def test_pattern_masks_refuse_groups_bad_syntax_and_empty_matches(target):
    masks = [{"name": "m", "kind": "pattern", "target": target, "placeholder": "{X}"}]
    with pytest.raises(ValueError, match="pattern"):
        validate("masks", masks)


def test_run_value_masks_name_known_values_only():
    masks = [{"name": "m", "kind": "run_value", "target": "home_dir", "placeholder": "{X}"}]
    with pytest.raises(ValueError, match="run value"):
        validate("masks", masks)


def test_validate_loads_every_registering_module_itself():
    # A caller that imports only run must still get every sibling module's checks.
    script = ("import sys\nfrom bicentennial.contracts import run\n"
              "assert 'bicentennial.contracts.surfaces' not in sys.modules\n"
              "run.validate('lock', __import__('json').loads(sys.argv[1]))\n"
              "print(sorted(m for m in sys.modules if m.startswith('bicentennial.contracts.')))")
    out = subprocess.run([sys.executable, "-c", script, json.dumps(fixture("lock"))],
                         capture_output=True, text=True, check=True, timeout=10).stdout
    assert "bicentennial.contracts.surfaces" in out
