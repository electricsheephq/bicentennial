"""Dependency locks and worker provenance, without installed packages or sockets."""

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from bicentennial.canon import canon
from bicentennial.runner import compare, t0, t1
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems.registry import REGISTRY, load

REPO = Path(__file__).resolve().parents[2]
HASH = " --hash=sha256:" + "a" * 64


def lock(tmp_path, monkeypatch, text="Demo_Pkg==1.0" + HASH):
    path = tmp_path / "systems/locks/mem0-oss.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    monkeypatch.setattr(hp, "DEPENDENCIES", {"mem0-oss": "systems/locks/mem0-oss.txt"})
    return path


def fake_worker(tmp_path, installed=None, dists=(), mode="ok", packaging=True):
    """Execute the supplied -c script against a worker-owned metadata/marker view."""
    python = tmp_path / ".venv/bin/python"
    python.parent.mkdir(parents=True, exist_ok=True)
    python.write_text(f'''#!{sys.executable}
import importlib.metadata as metadata
import json, sys, types
assert sys.argv[1:3] == ['-I', '-c']
if sys.argv[3] == 'import mcp':
    sys.exit(0)
assert 'importlib.metadata' in sys.argv[3]
mode = {mode!r}
if mode == 'crash':
    sys.exit(7)
if mode == 'garbage':
    print('not JSON')
    sys.exit(0)
if mode == 'malformed':
    print('{{"applicable": [], "installed": {{}}, "dists": []}}')
    sys.exit(0)
versions = {installed if installed is not None else {'demo-pkg': '1.0'}!r}
def version(name):
    if name not in versions:
        raise metadata.PackageNotFoundError(name)
    return versions[name]
metadata.version = version
metadata.distributions = lambda: [types.SimpleNamespace(metadata={{'Name': n}}, version=v)
    for n, v in {list(dists)!r}]
class Marker:
    def __init__(self, marker):
        self.marker = marker
    def evaluate(self):
        assert self.marker in ["sys_platform == 'win32'", "sys_platform != 'win32'"]
        return self.marker == "sys_platform != 'win32'"
markers = types.ModuleType('packaging.markers')
markers.Marker = Marker
for error in ('InvalidMarker', 'UndefinedComparison', 'UndefinedEnvironmentName'):
    setattr(markers, error, type(error, (ValueError,), {{}}))
sys.modules['packaging'] = types.ModuleType('packaging')
sys.modules['packaging.markers'] = markers if {packaging!r} else None
exec(sys.argv[3])
''')
    python.chmod(0o755)
    return python


def prepared(tier, tmp_path, monkeypatch, system="mem0-oss", worker_argv=None):
    """Keep real prepare gates and replace only unrelated pack/host work."""
    module = t1 if tier == "t1" else t0
    monkeypatch.setattr(module, "REPO", tmp_path)
    monkeypatch.setattr(module, "read_marker", lambda: NS(exit=0))
    monkeypatch.setattr(module, "admit", lambda *a, **k: NS(admitted=True, max_roots=2))
    entry = load(REGISTRY / f"{system}.toml") | {"fresh_install_hash": "1" * 64}
    pin = load(REGISTRY / "hermes-native.toml")["artifact"]
    index = dict(tier=tier.upper(), harness_artifacts=[pin], packs={"G1": {"pack_id": "G1"}, "G2": {"pack_id": "G2"}}, seed_hash="0" * 64)
    monkeypatch.setattr(module, "verify", lambda *a, **k: index)

    def pack(root, rel):
        return NS(rel=rel, records={}, genre=rel, life=rel, pack={"items": []},
                  meta={"row": {"id": rel}}, template=NS())

    if tier == "t0":
        monkeypatch.setattr(t0, "_Pack", pack)
        monkeypatch.setattr(t0, "_check_c7", lambda *a: None)
        return t0._preflight(system=system, entry=entry, packs=tmp_path, selected=["all"],
            pack_hash="0" * 64, hermes=tmp_path, plugin_source=tmp_path,
            host_overrides={"worker_argv": worker_argv})[6].get("run_properties", ())
    monkeypatch.setattr(t1, "_pack", pack)
    monkeypatch.setattr(t1, "_json", lambda path: {"genre": path.parts[-3]})
    monkeypatch.setattr(t1, "c7_entries", lambda *a: {})
    monkeypatch.setattr(t1.c7, "cells", lambda *a: {})
    monkeypatch.setattr(t1, "_boundaries", lambda *a: {})
    monkeypatch.setattr(t1, "SessionGate", lambda *a: None)
    fields = ("benchmark_commit", "director_commit", "pack_hash", "route_table_hash",
              "write_turn_package_hash", "analysis_commit", "harness_artifacts", "system_artifacts")
    monkeypatch.setattr(t1, "_lock", lambda *a: dict.fromkeys(fields, "0" * 64))
    return t1.prepare(system=system, entry=entry, packs=tmp_path, pack_hash="0" * 64,
        hermes=tmp_path, plugin_source=tmp_path, worker_argv=worker_argv).worker_properties


def test_placed_lock():
    data = (REPO / "systems/locks/mem0-oss.txt").read_bytes()
    assert hp.DEPENDENCIES == {"holographic": "systems/locks/holographic.txt",
                               "mem0-oss": "systems/locks/mem0-oss.txt", "omega": "systems/locks/omega.txt"}
    hp.validate_dependencies(REPO)
    rows = hp.parse_dependencies(data)
    assert len(rows) == 33
    assert sum(marker is not None and "win32" in marker for _, _, marker in rows) == 1
    assert len({(n, m) for n, _, m in rows}) == 33
    # The parser requires a hash on every row, including the universal Windows row.
    assert data.count(b"--hash=sha256:") >= 33


def test_placed_holographic_lock():
    # Holographic turns off its vector recall without numpy (#210); both pins match pinned Hermes's lockfile.
    data = (REPO / "systems/locks/holographic.txt").read_bytes()
    assert hp.parse_dependencies(data) == [["numpy", "2.4.3", None], ["snowballstemmer", "3.1.1", None]]
    assert data.count(b"--hash=sha256:") >= 2


def test_placed_omega_lock():
    data = (REPO / hp.DEPENDENCIES["omega"]).read_bytes()
    rows = hp.parse_dependencies(data)
    assert len(rows) == 32 and data.count(b"--hash=sha256:") == 324
    assert {n: v for n, v, _ in rows}.items() >= {
        "omega-memory": "1.5.20", "onnxruntime": "1.29.0", "numpy": "2.4.3",
        "tokenizers": "0.23.1", "huggingface-hub": "1.24.0"}.items()


def test_parser_continuations_comments_and_hashes():
    text = "# lock\n\nDemo_Pkg==1.0 \\\n  " + HASH + " \\\n  " + HASH + " # second hash\nOther.name==2; sys_platform == 'win32'" + HASH + HASH
    assert hp.parse_dependencies(text.encode()) == [
        ["demo-pkg", "1.0", None], ["other-name", "2", "sys_platform == 'win32'"]]


@pytest.mark.parametrize("text", [
    "demo[extra]==1" + HASH, "demo @ https://example.invalid/a.whl" + HASH,
    "https://example.invalid/a.whl" + HASH, "-e demo==1" + HASH, "-r other.txt", "-c other.txt",
    "demo>=1" + HASH, "demo===1" + HASH, "demo==1", "demo==1 --hash=sha256:abc",
    "demo==1" + HASH + "\nDemo==1" + HASH, "# empty\n", "demo==1 \\",
    "demo==1; sys_platform == 'win32'" + HASH + "\nDemo==2; sys_platform == 'win32'" + HASH,
])
def test_invalid_lock(text):
    with pytest.raises(ValueError, match="^plugin_deps_lock_invalid$"):
        hp.parse_dependencies(text.encode())


def test_different_markers_allowed():
    assert hp.parse_dependencies(("demo==1; sys_platform == 'win32'" + HASH +
        "\ndemo==2; sys_platform != 'win32'" + HASH).encode()) == [
        ["demo", "1", "sys_platform == 'win32'"], ["demo", "2", "sys_platform != 'win32'"]]


@pytest.mark.parametrize("name,path", [
    ("mem0-oss", "/systems/locks/a.txt"), ("mem0-oss", "systems/locks/../a.txt"),
    ("mem0-oss", "other/a.txt"), ("mem0-oss", "systems/locks/missing.txt"),
    ("mem0-oss", "systems/locks\\a.txt"), ("hermes-native", "systems/locks/mem0-oss.txt"),
])
def test_map_validation(tmp_path, monkeypatch, name, path):
    lock(tmp_path, monkeypatch)
    monkeypatch.setattr(hp, "DEPENDENCIES", {name: path})
    with pytest.raises(ValueError, match="^plugin_deps_lock_invalid$"):
        hp.validate_dependencies(tmp_path)


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_equal_and_worker_marker(tmp_path, monkeypatch, tier):
    path = lock(tmp_path, monkeypatch, "Demo_Pkg==1.0" + HASH +
        "\nWindows_Only==9; sys_platform == 'win32'" + HASH)
    fake_worker(tmp_path, dists=[("Demo_Pkg", "1.0")])
    real, calls = hp.subprocess.run, []

    def run(argv, **kwargs):
        if "importlib.metadata" in argv[-1]:
            calls.append(kwargs)
        return real(argv, **kwargs)

    monkeypatch.setattr(hp.subprocess, "run", run)
    props = dict(prepared(tier, tmp_path, monkeypatch))
    assert len(calls) == 1
    assert calls[0] == dict(input=json.dumps(hp.parse_dependencies(path.read_bytes())),
                            capture_output=True, text=True, env={}, timeout=60)
    assert props[tier + ".plugin_deps"] == f"sha256:{sha256(path.read_bytes()).hexdigest()} n=1"
    assert props[tier + ".worker_dists"] == '[["demo-pkg","1.0"]]'


@pytest.mark.parametrize("tier", ["t0", "t1"])
@pytest.mark.parametrize("installed", [{}, {"demo-pkg": "2"}])
def test_mismatch(tmp_path, monkeypatch, capsys, tier, installed):
    lock(tmp_path, monkeypatch)
    fake_worker(tmp_path, installed=installed)
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_missing:demo-pkg$"):
        prepared(tier, tmp_path, monkeypatch)
    assert capsys.readouterr().err == f"demo-pkg locked=1.0 installed={installed.get('demo-pkg', 'none')}\n"


@pytest.mark.parametrize("tier", ["t0", "t1"])
@pytest.mark.parametrize("mode", ["crash", "garbage", "malformed", "packaging", "timeout", "start"])
def test_check_failure(tmp_path, monkeypatch, tier, mode):
    lock(tmp_path, monkeypatch)
    fake_worker(tmp_path, mode=mode, packaging=mode != "packaging")
    real = hp.subprocess.run

    def run(argv, **kwargs):
        if "importlib.metadata" in argv[-1]:
            if mode == "timeout":
                raise subprocess.TimeoutExpired(argv, 60)
            if mode == "start":
                raise OSError("could not start")
        return real(argv, **kwargs)

    monkeypatch.setattr(hp.subprocess, "run", run)
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_check_failed$"):
        prepared(tier, tmp_path, monkeypatch)


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_conflicting_applicable_versions(tmp_path, monkeypatch, tier):
    lock(tmp_path, monkeypatch, "demo-pkg==1" + HASH +
        "\ndemo-pkg==2; sys_platform != 'win32'" + HASH)
    fake_worker(tmp_path)
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_lock_invalid$"):
        prepared(tier, tmp_path, monkeypatch)


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_invalid_lock_before_worker(tmp_path, monkeypatch, tier):
    lock(tmp_path, monkeypatch, "demo>=1")
    fake_worker(tmp_path)
    real = hp.subprocess.run

    def run(argv, **kwargs):
        assert "importlib.metadata" not in argv[-1]
        return real(argv, **kwargs)

    monkeypatch.setattr(hp.subprocess, "run", run)
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_lock_invalid$"):
        prepared(tier, tmp_path, monkeypatch)


@pytest.mark.parametrize("tier", ["t0", "t1"])
@pytest.mark.parametrize("system", ["hermes-native", "mem0-oss"])
def test_injected_worker_skips_every_check(tmp_path, monkeypatch, tier, system):
    lock(tmp_path, monkeypatch, "invalid lock")

    def forbidden(*a, **kw):
        pytest.fail("injected worker reached subprocess")

    monkeypatch.setattr(hp.subprocess, "run", forbidden)
    assert prepared(tier, tmp_path, monkeypatch, system=system, worker_argv=["fake"]) == ()


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_native_dists_normalised_deduplicated(tmp_path, monkeypatch, tier):
    lock(tmp_path, monkeypatch, "invalid unused lock")
    fake_worker(tmp_path, dists=[("Z_pkg", "2"), ("demo.Pkg", "1"), ("demo-pkg", "1")])
    real, calls = hp.subprocess.run, []

    def run(argv, **kwargs):
        if "importlib.metadata" in argv[-1]:
            calls.append((argv, kwargs))
        return real(argv, **kwargs)

    monkeypatch.setattr(hp.subprocess, "run", run)
    props = dict(prepared(tier, tmp_path, monkeypatch, system="hermes-native"))
    encoded = b'[["demo-pkg","1"],["z-pkg","2"]]'
    assert props == {tier + ".worker_dists": encoded.decode(),
        tier + ".worker_dists_sha256": f"sha256:{sha256(encoded).hexdigest()} n=2",
        tier + ".file_time_sites": canon(hp.FILE_TIME_SITES["hermes"]).decode()}
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv[:3] == [str(tmp_path / ".venv/bin/python"), "-I", "-c"]
    assert kwargs == dict(env={}, timeout=60, input="[]", capture_output=True, text=True)


@pytest.mark.parametrize("tier", ["t0", "t1"])
@pytest.mark.parametrize("system", ["hermes-native", "holographic", "mem0-oss", "omega"])
def test_file_time_sites(tmp_path, monkeypatch, tier, system):
    fake_worker(tmp_path)
    monkeypatch.setattr(hp, "DEPENDENCIES", {})
    monkeypatch.setattr(hp, "WORKER_ENV", {})
    module = t0 if tier == "t0" else t1
    monkeypatch.setattr(module, "prepare_cache", lambda *a: (None, None))
    props = dict(prepared(tier, tmp_path, monkeypatch, system=system))
    expected = hp.FILE_TIME_SITES["hermes"] + hp.FILE_TIME_SITES.get(system, ())
    assert json.loads(props[tier + ".file_time_sites"]) == list(expected)
    monkeypatch.setattr(hp, "FILE_TIME_SITES", {})
    assert tier + ".file_time_sites" not in dict(prepared(tier, tmp_path, monkeypatch, system=system))


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_native_listing_crash(tmp_path, monkeypatch, tier):
    fake_worker(tmp_path, mode="crash")
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_check_failed$"):
        prepared(tier, tmp_path, monkeypatch, system="hermes-native")


@pytest.mark.parametrize("system", ["hermes-native", "mem0-oss"])
def test_t1_junit_properties_on_both_arms_and_floor(tmp_path, monkeypatch, system):
    lock(tmp_path, monkeypatch)
    fake_worker(tmp_path, dists=[("demo-pkg", "1.0")])
    props = prepared("t1", tmp_path, monkeypatch, system=system)
    arm = NS(outcomes={}, bundles=(), transforms=(), units=(), verdicts=())
    run = NS(ctx=NS(entry={"name": system}, worker_properties=props), arms={a: arm for a in
        ("system", "wiped", "no_memory")}, not_exercised=(), singleton_lives={}, duty_items=())
    monkeypatch.setattr(compare, "_finals", lambda *a: [])
    for name in ("system", "wiped"):
        data = compare._junit(run, name, canon(dict(tier="T1", system=system, items=[],
            controls={"wiped_store": "PASS"})), NS(to_obj=lambda: {}), "PASS", [], [], [], 0, [])
        suites = ET.fromstring(data)
        for suite in (s for s in suites if s.attrib["name"].endswith((".system", ".wiped", ".no_memory"))):
            actual = {p.attrib["name"]: p.attrib["value"] for p in suite.findall("properties/property")}
            assert all(actual[n] == v for n, v in props)


@pytest.mark.parametrize("system", ["hermes-native", "mem0-oss"])
def test_t0_junit_properties(tmp_path, monkeypatch, system):
    lock(tmp_path, monkeypatch)
    fake_worker(tmp_path, dists=[("demo-pkg", "1.0")])
    props = prepared("t0", tmp_path, monkeypatch, system=system)
    monkeypatch.setattr(t0, "assemble", lambda **kw: dict(tier="T0", system=system, items=[]))
    monkeypatch.setattr(t0, "finalize", lambda card, gate: canon(card))
    monkeypatch.setattr(t0, "_pins", lambda *a: {})
    monkeypatch.setattr(t0, "card_controls", lambda *a: {})
    monkeypatch.setattr(t0, "build_receipt", lambda **kw: {})
    pack = NS(pack={"items": [], "bundles": [], "lives": ["life"]},
        meta=dict(honeypot_token="unused", singleton_lives={}, duty_items=[]), template=NS())
    audit = t0._audit([])
    report = t0._report_pack(pack, {"name": system}, {}, {}, [], [], {}, audit,
                             tmp_path, NS(exit=0), 0, props)
    actual = {p.attrib["name"]: p.attrib["value"] for p in
              ET.fromstring(report["junit"])[0].findall("properties/property")}
    assert all(actual[n] == v for n, v in props)


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_all_mismatches_sorted(tmp_path, monkeypatch, capsys, tier):
    lock(tmp_path, monkeypatch, "Z_Pkg==1" + HASH + "\nA_Pkg==2" + HASH)
    fake_worker(tmp_path, installed={"a-pkg": "3"})
    with pytest.raises((t0.T0Refused, t1.T1Refused), match="^plugin_deps_missing:a-pkg$"):
        prepared(tier, tmp_path, monkeypatch)
    assert capsys.readouterr().err == "a-pkg locked=2 installed=3\nz-pkg locked=1 installed=none\n"


@pytest.mark.parametrize("marker", ["garbage", "python_version >", "python_version > '3' and"])
def test_unusable_marker_is_an_invalid_lock(marker):
    checked = subprocess.run([sys.executable, "-I", "-c", hp.WORKER_DISTS], capture_output=True, text=True,
                             input=json.dumps([["demo", "1.0", marker], ["pip", "0", None]]), timeout=60)
    assert checked.returncode == 0, checked.stderr
    result = json.loads(checked.stdout)
    assert result["invalid"] is True and "demo" not in result["applicable"]


def test_engine_only_dependency_map(tmp_path, monkeypatch):
    path = tmp_path / "systems/locks/fixture.txt"
    path.parent.mkdir(parents=True)
    path.write_text("fixture==1" + HASH + "\n")
    monkeypatch.setattr(hp, "ENGINES", {"fixture-engine": "fixture_engine"})
    monkeypatch.setattr(hp, "DEPENDENCIES", {"fixture-engine": "systems/locks/fixture.txt"})
    hp.validate_dependencies(tmp_path)
    monkeypatch.setattr(hp, "DEPENDENCIES", {"hermes-native": "systems/locks/fixture.txt"})
    with pytest.raises(ValueError, match="^plugin_deps_lock_invalid$"):
        hp.validate_dependencies(tmp_path)
