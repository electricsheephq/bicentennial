"""Offline registry policy and runner-admission acceptance."""

import copy
import tomllib
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.contracts.run import validate
from bicentennial.contracts.surfaces import tree_hash
from bicentennial.director.roles import SUMMARISER_ALIAS
from bicentennial.systems import SystemRefused, admit_system, check, load
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems.__main__ import main
from bicentennial.systems.registry import PROVISIONAL_OSI_LICENCES, REGISTRY, ZERO_HASH

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "systems"
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
REASONS = ("artifact_unpinned", "route_unroutable", "licence_not_osi", "state_path_undeclared")


def hermes():
    return load(REGISTRY / "hermes-native.toml")


def measured():
    entry = hermes()
    entry["fresh_install_hash"] = "a" * 64
    return entry


@pytest.mark.parametrize("name", ["hermes-native", "holographic", "lcm-x", "mem0-oss", "no-memory"])
def test_shipped_entries_validate(name):
    entry = load(REGISTRY / f"{name}.toml")
    validate("system", entry)
    assert check(entry) == []
    assert entry["embedding_dim"] == (1536 if name == "mem0-oss" else None)


def test_shipped_hermes_compaction_uses_served_alias():
    entry = hermes()
    routes = {route["role"]: route["alias"] for route in entry["own_model_routes"]}
    assert routes["compaction"] == routes["summariser"] == SUMMARISER_ALIAS
    assert check(entry) == []


def test_shipped_cli(capsys):
    assert main(["check"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "hermes-native: ok",
        "holographic: ok",
        "lcm-x: UNMEASURED artifact.sha256 fresh_install_hash",
        "mem0-oss: ok",
        "no-memory: ok",
        "omega: ok",
    ]


@pytest.mark.parametrize("reason", REASONS)
def test_each_bad_fixture_has_exactly_one_refusal(reason, capsys):
    path = FIXTURES / f"{reason}.toml"
    assert CANARY in path.read_text()
    entry = load(path)
    assert check(entry) == [reason]
    assert main(["check", str(path)]) == 1
    assert capsys.readouterr().out == f"{reason}: REFUSED {reason}\n"
    with pytest.raises(SystemRefused) as error:
        admit_system(entry, operator="other")
    assert reason in error.value.reasons


def test_multiple_fixture_paths_all_checked(capsys):
    assert main(["check", *(str(FIXTURES / f"{r}.toml") for r in REASONS)]) == 1
    assert capsys.readouterr().out.splitlines() == [f"{r}: REFUSED {r}" for r in REASONS]


@pytest.mark.parametrize("version", ["", "latest", "main", "v0.22", ">=0.22.2", "1.*",
                                     "0.22.2\n", "v0.22.2..v0.23.0"])
def test_release_pin_refuses_floating_versions(version):
    entry = hermes()
    entry["artifact"]["version"] = version
    assert check(entry) == ["artifact_unpinned"]


@pytest.mark.parametrize("digest", ["", "a" * 63, "g" * 64, "A" * 64])
def test_artifact_digest_must_match_k13(digest):
    entry = hermes()
    entry["artifact"]["sha256"] = digest
    assert check(entry) == ["artifact_unpinned"]


@pytest.mark.parametrize("alias", ["https://api.example.com/v1", "vendor-model", "bicentennial-X",
                                   "bicentennial-", "bicentennial-main\n"])
def test_every_own_route_is_a_director_alias(alias):
    entry = hermes()
    entry["own_model_routes"][-1]["alias"] = alias
    assert check(entry) == ["route_unroutable"]


@pytest.mark.parametrize("alias", ["bicentennial-compaction", "bicentennial-extraction",
                                   "bicentennial-summariser-other"])
def test_compaction_route_requires_served_alias(alias):
    entry = measured()
    entry["name"] = "custom-system"
    compaction = next(route for route in entry["own_model_routes"] if route["role"] == "compaction")
    compaction["alias"] = alias
    validate("system", entry)
    reason = "compaction_alias_mismatch"
    assert check(entry) == [reason]
    with pytest.raises(SystemRefused) as error:
        admit_system(entry, operator="other")
    assert error.value.reasons == (reason,)
    assert str(error.value) == reason


@pytest.mark.parametrize("licence", sorted(PROVISIONAL_OSI_LICENCES))
def test_provisional_allow_list(licence):
    entry = hermes()
    entry["licence"] = licence
    assert check(entry) == []


@pytest.mark.parametrize("licence", ["Elastic-2.0", "BUSL", "BUSL-1.1", "unknown"])
def test_non_osi_selection(licence):
    entry = hermes()
    entry["licence"] = licence
    assert check(entry) == ["licence_not_osi"]


@pytest.mark.parametrize("path", ["/absolute", "../state", "state/../db", "state/..",
                                  "C:\\state", "state\\..\\db"])
def test_surface_escape_has_named_refusal(path):
    entry = hermes()
    entry["surfaces"][0]["relative"] = path
    assert check(entry) == ["state_path_undeclared"]


@pytest.mark.parametrize("writers,routes", [(True, False), (False, True), (True, True)])
def test_each_active_state_path_requires_a_surface(writers, routes):
    entry = hermes()
    entry["surfaces"] = []
    if not writers:
        entry["write_tools"] = []
    if not routes:
        entry["own_model_routes"] = []
    assert check(entry) == ["state_path_undeclared"]


@pytest.mark.parametrize("template", [
    {"query": "{gold}"}, {"query": [{"value": "{prompt} {answer}"}]},
    {"{fact_id}": "literal"}, {"query": "{prompt!r}"}, {"query": "{prompt"},
])
def test_only_prompt_placeholders(template):
    entry = hermes()
    entry["recall"]["argument_template"] = template
    assert check(entry) == ["recall_placeholder"]


def test_load_enforces_k13_beyond_selection_policy(tmp_path):
    text = (REGISTRY / "hermes-native.toml").read_text()
    path = tmp_path / "invalid.toml"
    path.write_text(text + '\nunexpected = true\n')
    with pytest.raises(ValueError, match="extra"):
        load(path)
    entry = measured()
    entry["recall"]["tool"] = "undeclared_read"
    assert check(entry) == ["schema_invalid"]
    with pytest.raises(SystemRefused, match="schema_invalid"):
        admit_system(entry)


def test_control_nullable_keys_and_measured_empty_listing():
    raw = tomllib.loads((REGISTRY / "no-memory.toml").read_text())
    assert "recall" not in raw and "embedding_dim" not in raw
    entry = load(REGISTRY / "no-memory.toml")
    assert entry["recall"] is None
    assert entry["read_tools"] == entry["write_tools"] == entry["surfaces"] == []
    assert entry["own_model_routes"] == []
    assert entry["fresh_install_hash"] == tree_hash([])
    assert entry["artifact"]["sha256"] == sha256(b"").hexdigest()
    assert admit_system(entry, operator="benchmark") is None


def test_hermes_manifest_and_wal_preservation():
    entry = hermes()
    assert entry["write_tools"] == [{"tool": "memory", "actions": ["add", "patch", "remove"]}]
    assert entry["read_tools"] == ["session_search"]
    assert entry["recall"] == {"tool": "session_search", "argument_template": {"query": "{prompt}"}}
    assert entry["artifact"]["version"] == "v0.22.2"
    assert entry["artifact"]["sha256"] != ZERO_HASH
    for name in ("hermes-native", "lcm-x"):
        surfaces = load(REGISTRY / f"{name}.toml")["surfaces"]
        assert surfaces == [{"root": "HERMES_HOME", "relative": ".",
                             "volatile_paths": [".mcp-discovery.lock", "logs"]}]
        for path in surfaces[0]["volatile_paths"]:
            assert path == "logs" or path.endswith(".lock")
            assert not path.startswith(("state.db", "memories"))


def test_admission_unmeasured_and_measured_hermes():
    assert admit_system(hermes(), operator="benchmark") is None
    entry = hermes()
    entry["fresh_install_hash"] = ZERO_HASH
    with pytest.raises(SystemRefused) as error:
        admit_system(entry, operator="benchmark")
    assert error.value.reasons == ("unmeasured:fresh_install_hash",)
    entry = measured()
    before = copy.deepcopy(entry)
    assert admit_system(entry, operator="benchmark") is None
    assert entry == before
    entry["artifact"]["sha256"] = ZERO_HASH
    with pytest.raises(SystemRefused, match="unmeasured:artifact.sha256"):
        admit_system(entry)


def test_lcm_operator_gate_independent_of_hashes(monkeypatch):
    entry = load(REGISTRY / "lcm-x.toml")
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    with pytest.raises(SystemRefused) as error:
        admit_system(entry)
    assert "benchmark_operator_forbidden" in error.value.reasons
    entry["artifact"]["sha256"] = "a" * 64
    entry["fresh_install_hash"] = "b" * 64
    with pytest.raises(SystemRefused, match="benchmark_operator_forbidden"):
        admit_system(entry)
    assert admit_system(entry, operator="system-owner") is None
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "system-owner")
    assert admit_system(entry) is None


def test_cli_unreadable_entry_continues_without_traceback(tmp_path, capsys):
    invalid = tmp_path / "invalid.toml"
    invalid.write_text("not valid TOML")
    assert main(["check", str(invalid), str(REGISTRY / "no-memory.toml")]) == 1
    assert capsys.readouterr().out.splitlines() == [
        "entry: REFUSED entry_unreadable", "no-memory: ok",
    ]


def test_shipped_telemetry_policy_from_other_directory(tmp_path, monkeypatch):
    assert hp.TELEMETRY_SWITCHES == {"onnxruntime": ("ORT_DISABLE_TELEMETRY", "1")}
    monkeypatch.chdir(tmp_path)
    assert all(check(load(path)) == [] for path in REGISTRY.glob("*.toml"))


@pytest.mark.parametrize("value", [None, "0", 1])
def test_telemetry_switch_exact_value(monkeypatch, capsys, value):
    monkeypatch.setitem(hp.WORKER_ENV, "omega", {} if value is None else {"ORT_DISABLE_TELEMETRY": value})
    entry = measured() | {"name": "omega"}
    reason = "telemetry_switch_missing:onnxruntime:ORT_DISABLE_TELEMETRY=1"
    assert check(entry) == [reason]
    with pytest.raises(SystemRefused) as error:
        admit_system(entry, operator="other")
    assert error.value.reasons == (reason,)
    assert main(["check", str(REGISTRY / "omega.toml")]) == 1
    assert capsys.readouterr().out == f"omega: REFUSED {reason}\n"


@pytest.mark.parametrize("text, refused", [
    ("ONNXRuntime==1.0", True),
    ("  onnxruntime==1.0 ; python_version < '0' \\\n    --hash=sha256:" + "a" * 64, True),
    ("onnx_runtime==1.0", False),
    ("\n # onnxruntime==1.0\n --hash=sha256:onnxruntime==1.0\nonnxruntime>=1\nxonnxruntime==1", False),
])
def test_telemetry_lock_pins(tmp_path, monkeypatch, text, refused):
    path = tmp_path / "lock.txt"
    path.write_text(text)
    monkeypatch.setitem(hp.DEPENDENCIES, "omega", path)
    monkeypatch.delitem(hp.WORKER_ENV, "omega")
    assert check(measured() | {"name": "omega"}) == (
        ["telemetry_switch_missing:onnxruntime:ORT_DISABLE_TELEMETRY=1"] if refused else [])


def test_telemetry_lock_unreadable(tmp_path, monkeypatch):
    monkeypatch.setitem(hp.DEPENDENCIES, "omega", tmp_path / "missing.txt")
    monkeypatch.setitem(hp.WORKER_ENV, "omega", {})
    assert check(measured() | {"name": "omega"}) == ["telemetry_lock_unreadable"]


@pytest.mark.parametrize("name", [None, 1, [], {}])
def test_telemetry_invalid_name_keeps_schema_fallback(name):
    assert check(measured() | {"name": name}) == ["schema_invalid"]


def test_telemetry_reasons_sorted_after_recall(tmp_path, monkeypatch):
    path = tmp_path / "lock.txt"
    path.write_text("zzz==1\nonnxruntime==1\naaa==1\nonnxruntime==1\n")
    monkeypatch.setitem(hp.DEPENDENCIES, "omega", path)
    monkeypatch.setattr(hp, "TELEMETRY_SWITCHES", dict.fromkeys(
        ("zzz", "onnxruntime", "aaa"), ("ORT_DISABLE_TELEMETRY", "1")))
    monkeypatch.setitem(hp.WORKER_ENV, "omega", {})
    entry = measured() | {"name": "omega", "extra": True}
    entry["recall"]["argument_template"] = {"query": "{gold}"}
    assert check(entry) == ["recall_placeholder", *("telemetry_switch_missing:" + package + ":ORT_DISABLE_TELEMETRY=1"
        for package in ("aaa", "onnxruntime", "zzz"))]


def test_telemetry_switch_keys_are_normalised():
    # check() matches PEP 503 names from the lock, so a key in another form would never match.
    assert all(hp.normalise(package) == package for package in hp.TELEMETRY_SWITCHES)


def test_telemetry_guide_rows():
    text = (ROOT / "docs/developers/ring0.md").read_text()
    for reason in ("telemetry_switch_missing:<package>:<switch>=<value>", "telemetry_lock_unreadable"):
        row = next(line for line in text.splitlines() if line.startswith(f"| `{reason}` |"))
        assert all(value in row for value in ("onnxruntime", "ORT_DISABLE_TELEMETRY=1", "#266"))
