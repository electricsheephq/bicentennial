"""Offline pin measurements use the real installer with a socket-free director."""

import subprocess
import tempfile
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial import cli
from bicentennial.harness.hermes import plugin_host
from bicentennial.sandbox import fixedroot
from bicentennial.sandbox.surfaces import install_hash, surface_hash
from bicentennial.systems import pins
from bicentennial.systems.hermes_plugin import TREES
from bicentennial.systems.registry import REGISTRY, ZERO_HASH, load


@pytest.fixture
def offline(monkeypatch):
    active, ports = set(), []

    def serve(director, port):
        assert port == 0
        port = next(port for port in range(19000, 19010) if port not in active)
        active.add(port)
        ports.append(port)
        director.bind_port(port)
        return SimpleNamespace(port=port)

    monkeypatch.setattr(plugin_host, "serve", serve)
    monkeypatch.setattr(plugin_host, "shutdown", lambda server: active.discard(server.port))
    monkeypatch.setattr(plugin_host, "verify_pin", lambda checkout, pin: "synthetic")
    monkeypatch.setattr(plugin_host, "Egress", lambda: SimpleNamespace(
        start=lambda: None, stop=lambda: None, summary=lambda: {}))
    monkeypatch.setattr(plugin_host.HermesMemoryHost, "_start", lambda self: pytest.fail("worker started"))
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "_source_checkout", lambda root: True)
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.delenv("BICENTENNIAL_OPERATOR", raising=False)
    return SimpleNamespace(active=active, ports=ports)


def test_equal_hashes_print_pin(monkeypatch, capsys, offline, tmp_path):
    monkeypatch.setattr(plugin_host, "install_hash", lambda directory, volatile, port: "a" * 64)
    assert cli.main(["pins", "--system", "hermes-native", "--hermes", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "fresh_install_hash " + "a" * 64,
        "artifact.sha256 " + load(REGISTRY / "hermes-native.toml")["artifact"]["sha256"],
        "entry hermes-native"]
    assert not offline.active
    assert list(tmp_path.iterdir()) == []


def test_distinct_ports_and_masked_install_hash(monkeypatch, offline, tmp_path):
    observed = []

    def record(directory, volatile, port):
        digest = install_hash(directory, volatile, port)
        observed.append((port, digest, surface_hash(directory, volatile)))
        return digest

    monkeypatch.setattr(plugin_host, "install_hash", record)
    entry = load(REGISTRY / "hermes-native.toml")
    before = deepcopy(entry)
    entry["fresh_install_hash"] = ZERO_HASH
    result = pins.measure(entry, hermes=tmp_path)
    assert len(observed) == 2
    assert observed[0][0] != observed[1][0]
    assert observed[0][1] == observed[1][1] == result["fresh_install_hash"]
    assert observed[0][2] != observed[1][2]
    assert entry == dict(before, fresh_install_hash=ZERO_HASH)
    assert not offline.active


def test_unstable_refuses_and_prints_both(monkeypatch, capsys, offline, tmp_path):
    values = iter(["a" * 64, "b" * 64])
    monkeypatch.setattr(plugin_host, "install_hash", lambda *args: next(values))
    assert pins.run_pins(system="hermes-native", hermes=tmp_path) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.split() == ["pins_unstable", "a" * 64, "b" * 64]
    assert not offline.active


@pytest.fixture
def source(tmp_path, git_checkouts):
    root = tmp_path / "source"
    root.mkdir()
    subdir = TREES["mem0-oss"][1]
    (root / subdir).mkdir(parents=True)
    (root / subdir / "provider.py").write_text("# synthetic provider\n")
    (root / "unrelated.txt").write_text("outside the plug-in\n")
    for args in (["init", "-q", "--template="], ["add", "."],
                 ["-c", "core.hooksPath=", "commit", "--no-gpg-sign", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            check=True, capture_output=True, text=True).stdout.strip()
    return root, commit


@pytest.mark.parametrize("subdir", [None, TREES["mem0-oss"][1]])
def test_archive_hash_at_commit_and_subdirectory(source, subdir):
    root, commit = source
    recipe = (commit,) if subdir is None else (commit, subdir)
    expected = subprocess.run(["git", "-C", str(root), "archive", "--format=tar", *recipe],
                              check=True, capture_output=True).stdout
    (root / "unrelated.txt").write_text("uncommitted changes are outside the archive\n")
    assert pins.archive_hash(root, recipe) == sha256(expected).hexdigest()


@pytest.mark.parametrize("name", ["holographic", "mem0-oss"])
def test_plugin_installer_verifies_measured_archive(source, name, offline, monkeypatch, tmp_path):
    root, commit = source
    recipe = (commit, *TREES[name][1:])
    expected = pins.archive_hash(root, recipe)
    entry = load(REGISTRY / f"{name}.toml")
    entry["artifact"]["sha256"] = ZERO_HASH
    original_tempdir = tempfile.tempdir
    real_file = tempfile.TemporaryFile
    archives = []

    def temporary_file(*args, **kwargs):
        directory = Path(tempfile.gettempdir())
        assert directory.is_relative_to(Path(fixedroot.PARENT))
        archives.append(directory)
        return real_file(*args, **kwargs)

    monkeypatch.setattr(tempfile, "TemporaryFile", temporary_file)
    result = pins.measure(entry, hermes=tmp_path, plugin_source=root, recipe=recipe)
    assert result["artifact.sha256"] == expected
    assert entry["artifact"]["sha256"] == ZERO_HASH
    assert len(archives) == 2
    assert not offline.active
    assert tempfile.tempdir == original_tempdir


def test_registry_recipe_supplies_commit_and_subdirectory(monkeypatch, tmp_path, capsys, source):
    root, commit = source
    subdir = TREES["mem0-oss"][1]
    path = tmp_path / "mem0-oss.toml"
    path.write_text((REGISTRY / path.name).read_text().replace(
        "43849c6e9d4d773b83a8144b6373aedc67241a5d", commit))
    monkeypatch.setattr(pins, "REGISTRY", tmp_path)

    def measure(entry, **kwargs):
        assert kwargs["recipe"] == (commit, subdir)
        assert kwargs["plugin_source"] == root
        return {"fresh_install_hash": "a" * 64}

    monkeypatch.setattr(pins, "measure", measure)
    assert pins.run_pins(system="mem0-oss", hermes=root, plugin_source=root) == 0
    assert capsys.readouterr().out.endswith("entry mem0-oss\n")


@pytest.mark.parametrize("system,hermes,code", [
    ("unknown", True, "unknown_system"), ("../hermes-native", True, "unknown_system"),
    ("hermes-native", False, "missing_input"), ("mem0-oss", True, "missing_input"),
])
def test_preconditions_refuse_before_install(system, hermes, code, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(pins, "HermesMemoryHost", lambda *a, **kw: pytest.fail("installed"))
    assert pins.run_pins(system=system, hermes=tmp_path if hermes else None) == 3
    assert capsys.readouterr().err.strip() == code


def test_other_errors_refuse_with_their_text(monkeypatch, capsys, offline, tmp_path):
    def unmapped(*args, **kwargs):
        raise ValueError("no T0 mapping")

    monkeypatch.setattr(pins, "HermesMemoryHost", unmapped)
    assert pins.run_pins(system="hermes-native", hermes=tmp_path) == 3
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", "refused no T0 mapping\n")


def test_busy_slot_refuses_before_install(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(pins, "HermesMemoryHost", lambda *a, **kw: pytest.fail("installed"))
    with fixedroot.lease(0, pins.PinsRefused):
        assert pins.run_pins(system="hermes-native", hermes=tmp_path) == 3
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("sandbox_busy holder_pid=")


def test_source_in_slot_refuses_before_lease(monkeypatch, capsys):
    monkeypatch.setattr(pins, "HermesMemoryHost", lambda *a, **kw: pytest.fail("installed"))
    assert pins.run_pins(system="hermes-native", hermes=Path(fixedroot.PARENT) / "bicentennial-0") == 3
    assert capsys.readouterr().err.strip() == "sandbox_overlap"
