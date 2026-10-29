"""Source-checkout refusal happens before parsing, re-exec or runner work."""

import os
import shutil
import subprocess
import sys
from os import fspath

import pytest

from bicentennial import cli
from bicentennial.runner import t0


def _unexpected(*args, **kwargs):
    raise AssertionError("source-checkout refusal must happen first")


def _guard_runners(monkeypatch):
    for name in ("reexec_niced", "run_t0", "run_t1"):
        monkeypatch.setattr(cli, name, _unexpected)


def test_real_source_checkout():
    assert cli.REPO == t0.REPO
    assert cli._source_checkout(t0.REPO)


@pytest.mark.parametrize("nested", [False, True])
def test_source_checkout_ignores_git_location_variables(git_checkouts, monkeypatch, nested):
    root = git_checkouts.checkout / "nested" if nested else git_checkouts.checkout
    root.mkdir(exist_ok=True)
    (root / "schemas").mkdir()
    (root / "pyproject.toml").touch()
    clean = cli._source_checkout(root)
    assert clean is (not nested)
    # Nested: GIT_DIR alone makes git take the working directory as the top level, so an
    # unfixed gate would accept the nested folder. With all four set it would refuse it
    # either way, and the case could not fail.
    conflict = ({"GIT_DIR": git_checkouts.conflict["GIT_DIR"]} if nested
                else git_checkouts.conflict)
    for name, value in conflict.items():
        monkeypatch.setenv(name, value)
    assert cli._source_checkout(root) == clean


def test_source_checkout_git_root_alias(tmp_path, monkeypatch):
    alias = tmp_path / "root-alias"
    alias.symlink_to(t0.REPO, target_is_directory=True)
    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, stdout=str(alias) + "\n"))
    # Model realpath retaining different spellings on a case-insensitive filesystem.
    monkeypatch.setattr(cli.os.path, "realpath", fspath)
    assert cli._source_checkout(t0.REPO)


@pytest.mark.parametrize("operation", ["git", "samefile"])
def test_source_checkout_oserror_defers_to_runner(monkeypatch, operation):
    def unavailable(*args, **kwargs):
        raise OSError("unavailable")

    monkeypatch.setattr(cli.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(
        a[0], 0, stdout=str(t0.REPO)))
    if operation == "git":
        monkeypatch.setattr(cli.subprocess, "run", unavailable)
    else:
        monkeypatch.setattr(cli.os.path, "samefile", unavailable)
    assert cli._source_checkout(t0.REPO)


@pytest.mark.parametrize("sub", ["t0", "t1", "--bogus"])
def test_empty_source_checkout(tmp_path, monkeypatch, capsys, sub):
    root = tmp_path / "empty"
    root.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(cli, "REPO", root)
    _guard_runners(monkeypatch)
    argv = [sub]
    if sub in ("t0", "t1"):
        argv += ["--system", "reference_store" if sub == "t0" else "hermes-native",
                 "--packs", "packs", "--pack-hash", "0" * 64, "--out", str(out)]
        if sub == "t0":
            argv += ["--pack", "all"]
    assert cli.main(argv) == 3
    captured = capsys.readouterr()
    assert captured.err == "source_checkout_required\n"
    assert captured.out == ""
    assert not out.exists()
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("shape", ["project_only", "schemas_only", "schemas_file"])
def test_partial_source_checkout(tmp_path, monkeypatch, capsys, shape):
    root = tmp_path / "partial"
    root.mkdir()
    if shape != "schemas_only":
        (root / "pyproject.toml").touch()
    if shape == "schemas_only":
        (root / "schemas").mkdir()
    elif shape == "schemas_file":
        (root / "schemas").touch()
    monkeypatch.setattr(cli, "REPO", root)
    _guard_runners(monkeypatch)
    assert cli.main(["t0", "--help"]) == 3
    assert capsys.readouterr().err == "source_checkout_required\n"


def test_complete_source_root_reaches_help(tmp_path, monkeypatch):
    root = tmp_path / "complete"
    root.mkdir()
    (root / "pyproject.toml").touch()
    (root / "schemas").mkdir()
    monkeypatch.setattr(cli, "REPO", root)
    _guard_runners(monkeypatch)
    with pytest.raises(SystemExit) as caught:
        cli.main(["t0", "--help"])
    assert caught.value.code == 0


def test_source_copy_inside_unrelated_repository(tmp_path, monkeypatch, capsys):
    parent = tmp_path / "unrelated"
    parent.mkdir()
    subprocess.run(["git", "init", "-q", str(parent)], check=True)
    root = parent / "copy"
    shutil.copytree(t0.REPO, root, ignore=shutil.ignore_patterns(
        ".git", ".venv", "build", "runs", "__pycache__", ".pytest_cache", ".ruff_cache",
    ))
    assert not (root / ".git").exists()
    monkeypatch.setattr(cli, "REPO", root)
    _guard_runners(monkeypatch)
    out = tmp_path / "out"
    assert cli.main(["t0", "--system", "reference_store", "--pack", "all", "--packs", "p",
                     "--pack-hash", "0" * 64, "--out", str(out)]) == 3
    assert capsys.readouterr().err == "source_checkout_required\n"
    assert not out.exists()


def test_package_without_checkout_refuses_before_runner_imports(tmp_path):
    root = tmp_path / "package-only"
    shutil.copytree(t0.REPO / "src" / "bicentennial", root / "src" / "bicentennial",
                    ignore=shutil.ignore_patterns("__pycache__"))
    script = ("import sys; sys.path.insert(0, sys.argv[1]); from bicentennial import cli; "
              "assert cli.__file__.startswith(sys.argv[1]); sys.argv[1:] = sys.argv[2:]; "
              "raise SystemExit(cli.main())")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-c", script, str(root / "src"), "t0", "--system", "reference_store",
         "--pack", "all", "--packs", "p", "--pack-hash", "0" * 64, "--out", str(out)],
        capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "0"}, cwd=tmp_path,
    )
    assert (result.returncode, result.stdout, result.stderr) == (3, "", "source_checkout_required\n")
    assert not out.exists()
