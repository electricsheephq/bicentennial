"""Mapping refusals precede adapters, servers, workers and result publication."""

import json

import pytest

from bicentennial import cli
from bicentennial.harness.hermes import adapter, plugin_host
from bicentennial.runner import compare, life, t0, t1, t2lite
from bicentennial.systems import hermes_plugin
from bicentennial.systems.registry import REGISTRY, load


def entry_with_extra():
    entry = load(REGISTRY / "hermes-native.toml")
    entry["write_tools"].append(dict(tool="extra", actions=[]))
    return entry


@pytest.fixture
def no_start(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("preflight started an adapter, server or worker")
    for module, names in (
        (t0, ("HermesMemoryHost", "_OwnedHost")),
        (compare, ("HermesMemoryHost", "run_arms")),
        (life, ("HermesAdapter",)),
        (plugin_host, ("_Worker", "serve")),
        (adapter, ("_Worker", "serve")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)


def invoke(tier, tmp_path, entry):
    common = dict(system=entry["name"], entry=entry, packs_dir=tmp_path / "packs",
                  pack_hash="a" * 64, out=tmp_path / "out", hermes=tmp_path / "checkout")
    if tier == "T0":
        return t0.run_t0(packs=["all"], **common)
    return compare.run_t1(**common)


@pytest.mark.parametrize("tier", ["T0", "T1"])
def test_write_mapping_refusal_before_start(tier, tmp_path, monkeypatch, capsys, no_start):
    # If mapping admission is delayed, a valid pack boundary would be needed first.
    def no_pack(*args, **kwargs):
        pytest.fail("mapping admission was delayed until pack loading")
    monkeypatch.setattr(t0 if tier == "T0" else t1, "verify", no_pack)
    assert invoke(tier, tmp_path, entry_with_extra()) == 3
    assert capsys.readouterr().err.strip() == "write_mapping_missing:extra"
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("tier", ["T0", "T1"])
@pytest.mark.parametrize("case,code", [
    ("forget", "forget_mapping_missing"),
    ("embedding", "embedding_dim_invalid"),
])
def test_mapping_requirements_in_both_runners(tier, case, code, tmp_path, monkeypatch, capsys, no_start):
    entry = load(REGISTRY / "hermes-native.toml")
    if case == "forget":
        monkeypatch.delitem(plugin_host.FORGET, "hermes-native")
    else:
        entry["own_model_routes"].append(dict(role="embeddings", alias="bicentennial-embeddings"))
        entry["embedding_dim"] = None
    assert invoke(tier, tmp_path, entry) == 3
    assert capsys.readouterr().err.strip() == code
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("provider", [False, True])
def test_engine_only_forget_requirement(tmp_path, monkeypatch, no_start, provider):
    monkeypatch.setitem(hermes_plugin.ENGINES, "hermes-native", "synthetic")
    if provider:
        monkeypatch.setitem(hermes_plugin.PROVIDERS, "hermes-native", "synthetic")
    monkeypatch.delitem(plugin_host.FORGET, "hermes-native")
    def past_mapping(*args, **kwargs):
        raise LookupError("past mapping admission")
    monkeypatch.setattr(t1, "validate_maps", past_mapping)
    exception = t1.T1Refused if provider else LookupError
    reason = "forget_mapping_missing" if provider else "past mapping admission"
    with pytest.raises(exception, match=reason):
        t1.prepare(system="hermes-native", entry=load(REGISTRY / "hermes-native.toml"),
                   packs=tmp_path, pack_hash="a" * 64, worker_argv=["unused"], plugin_source=tmp_path)
    with pytest.raises(t0.T0Refused, match="forget_mapping_missing"):
        t0._preflight(system="hermes-native", entry=load(REGISTRY / "hermes-native.toml"),
                      packs=tmp_path, selected=["all"], pack_hash="a" * 64)


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_cli_mapping_refusal(tier, tmp_path, monkeypatch, capsys, no_start):
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(t0 if tier == "t0" else t1, "load", lambda path: entry_with_extra())
    args = [tier, "--system", "hermes-native", "--packs", str(tmp_path / "packs"),
            "--pack-hash", "a" * 64, "--out", str(tmp_path / "out")]
    if tier == "t0":
        args += ["--pack", "all"]
    assert cli.main(args) == 3
    assert capsys.readouterr().err.strip() == "write_mapping_missing:extra"
    assert not (tmp_path / "out").exists()


def test_t2lite_prepare_refusal_artifacts(tmp_path, monkeypatch, capsys, no_start):
    # Synthetic settings and an empty file suffice: refusal precedes credential loading.
    for name in t2lite.LIVE_ENV:
        monkeypatch.setenv(name, "synthetic")
    home = tmp_path / "login"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    out = tmp_path / "out"
    assert t2lite.run_t2lite(system="hermes-native", entry=entry_with_extra(),
        packs_dir=tmp_path / "packs", pack_hash="a" * 64, out=out, login_home=home, max_sends=0) == 3
    assert capsys.readouterr().err.strip() == "write_mapping_missing:extra"
    assert sorted(p.name for p in out.iterdir()) == ["refusal.json"]
    assert json.loads((out / "refusal.json").read_text()) == dict(code="write_mapping_missing:extra")
    assert sorted(p.name for p in home.iterdir()) == [".t2lite.lock", "auth.json"]
