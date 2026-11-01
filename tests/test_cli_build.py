"""Build dispatch, pack identity and refusals through the source CLI."""

from types import SimpleNamespace

import pytest

from bicentennial import cli
from bicentennial.packs import build, install
from bicentennial.systems import registry


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    calls = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: calls.append(argv))
    return calls


@pytest.mark.parametrize("tier", ["T0", "T1"])
def test_build_dispatch(ready, monkeypatch, capsys, tier):
    argv = ["build", "--tier", tier, "--out", "parent"]

    def built(*args, **kwargs):
        assert ready == [["-m", "bicentennial.cli", *argv]]
        assert args == (tier, "parent")
        assert kwargs == {"harness_artifacts": [
            registry.load(registry.REGISTRY / "hermes-native.toml")["artifact"]]}
        ready.append("built")

    monkeypatch.setattr(build, "build_tier", built)
    assert cli.main(argv) == 0
    assert ready[-1] == "built"
    assert capsys.readouterr() == ("", "")


def test_build_hash_matches_one_liner_with_existing_parent(ready, tmp_path, monkeypatch, capsys):
    root = build.REPO_ROOT
    catalogue = build.load_catalogue(root / "packs/catalogue-v0.toml",
                                    c7_path=root / "specs/ring0/c7-partial.json",
                                    tier_path=root / "tiers/life_specs/t0.toml")
    row = catalogue.by_id()["g2-keep-incidental-mft-1"]
    original = build.build_tier
    # One real pack, as in tests/packs/test_build.py; only the cross-pack gate is bypassed.
    monkeypatch.setattr(build, "check_distribution", lambda *a, **kw:
                        SimpleNamespace(ok=True, to_obj=lambda: {}))
    monkeypatch.setattr(build, "build_tier", lambda *a, **kw: original(*a, rows=[row], **kw))
    parent = tmp_path / "cli"
    parent.mkdir()
    assert cli.main(["build", "--tier", "T0", "--out", str(parent)]) == 0
    expected = original("T0", tmp_path / "direct", rows=[row], harness_artifacts=[
        registry.load(registry.REGISTRY / "hermes-native.toml")["artifact"]])
    assert install.tree_sha256(parent / "T0") == expected["pack_hash"]
    assert len(expected["index"]["packs"]) == 1
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("name", ["T0", "T0.staging", "T0.work"])
def test_build_existing_tier_unchanged(ready, tmp_path, capsys, name):
    target = tmp_path / name
    target.mkdir()
    (target / "sentinel").write_bytes(b"keep")
    before = build.file_manifest(tmp_path), target.stat().st_mode
    assert cli.main(["build", "--tier", "T0", "--out", str(tmp_path)]) == 3
    assert capsys.readouterr() == ("", "out_exists\n")
    assert (build.file_manifest(tmp_path), target.stat().st_mode) == before


@pytest.mark.parametrize("args", [["--tier", "T2", "--out", "unused"],
                                  ["--out", "unused"], ["--tier", "T0"],
                                  ["--tier", "T0", "--out", "unused", "extra"]])
def test_build_usage(ready, capsys, args):
    with pytest.raises(SystemExit) as caught:
        cli.main(["build", *args])
    assert caught.value.code == 3
    assert capsys.readouterr().err.splitlines()[-1].startswith("usage: ")
    assert ready == []


def test_build_requires_hashseed(monkeypatch, capsys):
    monkeypatch.delenv("PYTHONHASHSEED", raising=False)
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: pytest.fail("reexec before hashseed"))
    monkeypatch.setattr(cli, "run_build", lambda **kw: pytest.fail("build before hashseed"))
    assert cli.main(["build", "--tier", "T0", "--out", "unused"]) == 3
    assert capsys.readouterr() == ("", "hashseed\n")


@pytest.mark.parametrize("module, name", [(build, "build_tier"), (registry, "load")])
def test_build_unexpected_failure(ready, monkeypatch, capsys, module, name):
    def fail(*args, **kwargs):
        raise RuntimeError("broken build")

    monkeypatch.setattr(module, name, fail)
    assert cli.main(["build", "--tier", "T0", "--out", "unused"]) == 70
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("tool_failure\nTraceback")
    assert "RuntimeError: broken build" in captured.err


def test_t2lite_rerun_command_roundtrip(ready, monkeypatch):
    import runpy
    import shlex
    from pathlib import Path

    from bicentennial.report.t2lite_flips import rerun_command
    helpers = runpy.run_path(str(Path(__file__).parent / "report/test_t2lite_flips.py"))
    item = helpers["item"]("synthetic")
    command = rerun_command(helpers["card"](), item)
    for placeholder, path in (("<packs>", "packs"), ("<hermes checkout>", "hermes"), ("<new dir>", "out")):
        command = command.replace(placeholder, path)
    argv = shlex.split(command)[2:] + ["--login-home", "fake-login", "--max-sends", "30"]
    captured = []
    monkeypatch.setattr(cli, "run_t2lite", lambda **kw: captured.append(kw) or 0)
    assert cli.main(argv) == 0
    assert captured[0]["only"] == (item["life"], item["branch"], item["probe_point"])
    assert captured[0]["repeat"] == 3 and captured[0]["max_sends"] == 30


@pytest.mark.parametrize("extra", [[], ["--max-sends", "-1"], ["--max-sends", "1", "--only", "bad"],
                                   ["--max-sends", "1", "--repeat", "0"]])
def test_t2lite_invalid_usage(ready, extra):
    with pytest.raises(SystemExit) as caught:
        cli.main(["t2lite", "--system", "hermes-native", "--packs", "packs", "--pack-hash", "a" * 64,
                  "--out", "out", "--login-home", "fake-login", *extra])
    assert caught.value.code == 3
    assert ready == []
