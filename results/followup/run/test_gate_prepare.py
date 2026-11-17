"""Preparation sends nothing; all inputs and workers here are synthetic."""

import importlib.util
import re
from functools import partial
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.packs.build import build_tier
from bicentennial.packs.install import install
from bicentennial.runner import t1
from bicentennial.runner.guard import Marker
from bicentennial.runner.units import T2_SPEC
from bicentennial.systems.registry import REGISTRY, load

MODULE = Path(__file__).with_name("gate_prepare.py")


@pytest.fixture
def helper():
    assert MODULE.is_file(), "preparation helper is absent"
    spec = importlib.util.spec_from_file_location("followup_gate_prepare", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_g1_exact_call_and_public_lines(helper, tmp_path, capsys):
    calls = []
    pins = dict(
        system_hash="a" * 64,
        harness_hash="b" * 64,
        route_table_hash="c" * 64,
        benchmark_commit="d" * 40,
    )

    def prepare(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(pins=pins)

    packs, hermes = tmp_path / "packs", tmp_path / "source"
    assert (
        helper.main(
            ["--packs", str(packs), "--pack-hash", "e" * 64, "--hermes", str(hermes)],
            prepare=prepare,
        )
        == 0
    )
    assert calls == [
        dict(
            system="hermes-native",
            packs=packs,
            pack_hash="e" * 64,
            hermes=hermes,
            spec=T2_SPEC,
            control=False,
            turn_wait_s=3.0,
        )
    ]
    registry = sha256((REGISTRY / "hermes-native.toml").read_bytes()).hexdigest()
    assert capsys.readouterr().out.splitlines() == [
        f"registry_entry_sha256 {registry}",
        f"system_hash {pins['system_hash']}",
        f"harness_hash {pins['harness_hash']}",
        f"route_table_hash {pins['route_table_hash']}",
        f"benchmark_commit {pins['benchmark_commit']}",
        "prepared: system run accepted; nothing sent",
    ]


def test_g1_refusal_code_only(helper, tmp_path, capsys):
    def prepare(**kwargs):
        raise t1.T1Refused("synthetic_refusal", detail=("must stay private",))

    assert (
        helper.main(
            [
                "--packs",
                str(tmp_path),
                "--pack-hash",
                "a" * 64,
                "--hermes",
                str(tmp_path),
            ],
            prepare=prepare,
        )
        == 3
    )
    captured = capsys.readouterr()
    assert captured.out + captured.err == "synthetic_refusal\n"


def test_g2_real_preparation_is_repeatable(helper, tmp_path, monkeypatch, capsys):
    artifact = load(REGISTRY / "hermes-native.toml")["artifact"]
    build_tier("T2", tmp_path / "built", harness_artifacts=[artifact], edition=3)
    installed = tmp_path / "installed"
    digest = install(tmp_path / "built/T2", installed)
    entry = load(REGISTRY / "hermes-native.toml")
    for key in ("sha256",):
        if entry["artifact"][key] == "0" * 64:
            entry["artifact"][key] = "1" * 64
    if entry["fresh_install_hash"] == "0" * 64:
        entry["fresh_install_hash"] = "1" * 64
    monkeypatch.setattr(t1, "read_marker", lambda: Marker(0, False, "synthetic"))
    monkeypatch.setattr(t1, "worker_properties", lambda *args: ())
    real_prepare = partial(t1.prepare, entry=entry, worker_argv=["synthetic"])
    arguments = [
        "--packs",
        str(installed),
        "--pack-hash",
        digest,
        "--hermes",
        str(tmp_path / "synthetic-source"),
    ]
    try:
        assert helper.main(arguments, prepare=real_prepare) == 0
        first = capsys.readouterr().out
        assert helper.main(arguments, prepare=real_prepare) == 0
        assert capsys.readouterr().out == first
        lines = dict(line.split(" ", 1) for line in first.splitlines()[:-1])
        for key in ("system_hash", "harness_hash", "route_table_hash"):
            assert re.fullmatch(r"[0-9a-f]{64}", lines[key])
    finally:
        for path in [installed, *installed.rglob("*")]:
            path.chmod(path.stat().st_mode | 0o200)
