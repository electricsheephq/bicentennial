"""Read-only installation, complete pin checks, and guard-refusal CLI behavior."""

import json
import os
import shutil
import stat
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.controls.cache import PACKAGE_ROOT, ControlsTampered
from bicentennial.packs import build
from bicentennial.packs import install as installer
from bicentennial.packs.manifest import (
    PinnedArtifactChanged,
    file_manifest,
    tree_sha256,
)
from bicentennial.runner.lock import LockMismatch, build_lock

A = [dict(name="hermes", version="test", sha256="a" * 64)]


def writable(root):
    if not root.exists():
        return
    for directory, dirs, files in os.walk(root):
        Path(directory).chmod(0o755)
        for name in sorted(dirs + files):
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | stat.S_IWUSR)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("install-source")
    root = build.REPO_ROOT
    catalogue = build.load_catalogue(root / "packs/catalogue-v0.toml",
                                    c7_path=root / "specs/ring0/c7-partial.json",
                                    tier_path=root / "tiers/life_specs/t0.toml")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(build, "check_distribution", lambda packs, **kw:
                   SimpleNamespace(ok=True, to_obj=lambda: {}))
        result = build.build_tier("T0", tmp / "o1", harness_artifacts=A,
                                 rows=[catalogue.by_id()["g2-keep-incidental-mft-1"]])
    return tmp / "o1/T0", result


@pytest.fixture
def installed(built, tmp_path):
    source, result = built
    dest = tmp_path / "inst"
    digest = installer.install(source, dest)
    try:
        yield dest, digest, result["index"]
    finally:
        writable(dest)


def command(*args, seed="0"):
    return subprocess.run([sys.executable, "-m", "bicentennial.packs.install", *map(str, args)],
                          env={**os.environ, "PYTHONHASHSEED": seed}, capture_output=True,
                          text=True, timeout=30)


def pack_file(root, index, name):
    return root / next(iter(index["packs"])) / name


def edit_json(path, change):
    value = json.loads(path.read_bytes())
    change(value)
    path.chmod(0o644)
    path.write_bytes(canon(value))
    path.chmod(0o444)


def test_install_verify_modes_and_existing_destination(built, installed):
    root, digest, index = installed
    assert digest == built[1]["pack_hash"] == tree_sha256(root)
    for path in [root, *root.rglob("*")]:
        assert stat.S_IMODE(path.stat().st_mode) == (0o555 if path.is_dir() else 0o444)
    before = file_manifest(root), {p: p.stat().st_mode for p in [root, *root.rglob("*")]}
    assert installer.verify(root, pack_hash=digest) == index
    assert before == (file_manifest(root), {p: p.stat().st_mode for p in [root, *root.rglob("*")]})
    with pytest.raises(FileExistsError):
        installer.install(built[0], root)
    assert installer.verify(root, pack_hash=digest) == index
    completed = command("verify", root, "--pack-hash", digest)
    assert (completed.returncode, completed.stdout, completed.stderr) == (0, "", "")


@pytest.mark.parametrize("mutation", ["byte", "mode", "added", "hash"])
def test_cli_pinned_refusals(installed, mutation):
    root, digest, index = installed
    target = pack_file(root, index, "sealed/pack.json")
    if mutation in ("byte", "mode"):
        target.chmod(0o644)
        if mutation == "byte":
            with target.open("ab") as stream:
                stream.write(b" ")
    elif mutation == "added":
        target.parent.chmod(0o755)
        (target.parent / "extra").write_bytes(b"extra")
    else:
        digest = "0" * 64
    completed = command("verify", root, "--pack-hash", digest)
    assert (completed.returncode, completed.stdout, completed.stderr) == (
        3, "", "pinned_artifact_changed\n")


def test_cli_hashseed_usage_missing_and_install(built, tmp_path):
    dest = tmp_path / "cli-inst"
    try:
        completed = command("install", built[0], dest)
        assert (completed.returncode, completed.stdout, completed.stderr) == (
            0, built[1]["pack_hash"] + "\n", "")
        for args in (("install", built[0], dest), ("verify", tmp_path / "missing", "--pack-hash", "a")):
            completed = command(*args)
            assert (completed.returncode, completed.stdout, completed.stderr) == (3, "", "refused\n")
        completed = command("install", built[0], tmp_path / "untouched", seed="random")
        assert (completed.returncode, completed.stdout, completed.stderr) == (3, "", "hashseed\n")
        assert not (tmp_path / "untouched").exists()
        for args in ((), ("verify",), ("verify", dest), ("unknown",)):
            completed = command(*args)
            assert completed.returncode == 3 and "usage:" in completed.stderr
            assert "Traceback" not in completed.stderr
        assert sorted(p.name for p in tmp_path.iterdir()) == ["cli-inst"]
    finally:
        writable(dest)


@pytest.mark.parametrize("path,field", [
    ("score/action.py", "scorer_sha256"),
    ("controls/cache.py", "controls_sha256"),
    ("probe/scripted_reader.py", "reader_sha256"),
    ("items/checks/env.py", "scoring_code_sha256"),
])
def test_code_pins(installed, tmp_path, path, field):
    root, digest, _ = installed
    package = tmp_path / "package"
    shutil.copytree(PACKAGE_ROOT, package)
    with (package / path).open("ab") as stream:
        stream.write(b"\n")
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest, package_root=package)
    assert field in error.value.fields


def make_lock(digest):
    fixture = build.REPO_ROOT / "tests/fixtures/run/contracts.json"
    pins = json.loads(fixture.read_bytes())["contracts"]["lock"]
    return build_lock(**(pins | {"pack_hash": digest, "harness_artifacts": deepcopy(A)}))


def test_lock_pins_and_mismatch_precedence(installed):
    root, digest, index = installed
    expected = make_lock(digest)
    assert installer.verify(root, pack_hash=digest, lock=deepcopy(expected), expected_lock=expected) == index
    changed = deepcopy(expected)
    changed["harness_artifacts"][0]["sha256"] = "b" * 64
    with pytest.raises(LockMismatch) as error:
        installer.verify(root, pack_hash="0" * 64, lock=changed, expected_lock=expected)
    assert error.value.fields == ("harness_artifacts",)
    changed = make_lock("0" * 64)
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest, lock=changed, expected_lock=changed)
    assert error.value.fields == ("pack_hash",)
    changed = deepcopy(expected)
    changed["harness_artifacts"][0]["sha256"] = "c" * 64
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest, lock=changed, expected_lock=changed)
    assert error.value.fields == ("harness_pin",)


def test_index_harness_pin_even_with_matching_tree_hash(installed):
    root, _, _ = installed
    edit_json(root / "index.json", lambda value: value["harness_artifacts"][0].update(version="edited"))
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=tree_sha256(root))
    assert error.value.fields == ("harness_pin",)


def test_collects_file_mode_tree_scoring_and_harness_failures(installed):
    root, digest, index = installed
    missing = pack_file(root, index, "sealed/pack.json")
    missing.parent.chmod(0o755)
    missing.unlink()
    extra = missing.parent / "extra"
    extra.write_bytes(b"extra")
    scoring = missing.with_name("scoring.json")
    edit_json(scoring, lambda value: value.update(test_change=True))
    edit_json(root / "index.json", lambda value: value["harness_artifacts"].clear())
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest)
    expected = {missing.relative_to(root).as_posix(), extra.relative_to(root).as_posix(),
                scoring.relative_to(root).as_posix(),
                "mode:" + extra.relative_to(root).as_posix(),
                "mode:" + missing.parent.relative_to(root).as_posix(),
                "pack_hash", "scoring_sha256", "harness_pin"}
    assert error.value.fields == tuple(sorted(expected))


@pytest.mark.parametrize("kind", ["symlink", "directory-link", "fifo"])
def test_install_refuses_special_entries_without_destination(built, tmp_path, kind):
    source = tmp_path / "source"
    shutil.copytree(built[0], source)
    target = source / "unexpected"
    if kind == "fifo":
        os.mkfifo(target)
    else:
        target.symlink_to(built[0] if kind == "directory-link" else built[0] / "index.json")
    dest = tmp_path / "absent"
    with pytest.raises(ValueError):
        installer.install(source, dest)
    assert not os.path.lexists(dest)


@pytest.mark.parametrize("rel", ["unexpected", "index.json", "sealed-directory"])
def test_verify_never_reads_links_and_collects_other_failures(installed, tmp_path, monkeypatch, rel):
    root, digest, index = installed
    target = pack_file(root, index, "sealed") if rel == "sealed-directory" else root / rel
    target.parent.chmod(0o755)
    if target.is_dir():
        writable(target)
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    # An invalid JSON target detects accidental reads; a directory target detects traversal.
    external = tmp_path / "external"
    external.mkdir()
    (external / "index.json").write_bytes(b"invalid")
    target.symlink_to(external if rel != "index.json" else external / "index.json")
    original = installer.os.open

    def no_link_reads(path, flags):
        assert path != target and target not in path.parents
        return original(path, flags)

    with monkeypatch.context() as patch:  # undone before tmp_path's cleanup, which opens by descriptor (#348)
        patch.setattr(installer.os, "open", no_link_reads)
        with pytest.raises(PinnedArtifactChanged) as error:
            installer.verify(root, pack_hash=digest)
    assert "mode:" + target.relative_to(root).as_posix() in error.value.fields
    assert "pack_hash" in error.value.fields
    assert (external / "index.json").read_bytes() == b"invalid"


@pytest.mark.parametrize("phase", ["copy", "hash"])
def test_partial_install_cleanup(built, tmp_path, monkeypatch, phase):
    dest = tmp_path / "partial"
    if phase == "copy":
        original = installer.shutil.copyfile
        calls = []

        def fail_copy(src, dst):
            calls.append(src)
            if len(calls) == 2:
                raise OSError("copy failure")
            return original(src, dst)

        monkeypatch.setattr(installer.shutil, "copyfile", fail_copy)
        exception = OSError
    else:
        original = installer.tree_sha256
        monkeypatch.setattr(installer, "tree_sha256", lambda path: "0" * 64 if path == dest else original(path))
        exception = PinnedArtifactChanged
    with pytest.raises(exception):
        installer.install(built[0], dest)
    assert not dest.exists()


@pytest.mark.parametrize("exception", [PinnedArtifactChanged, LockMismatch, ControlsTampered])
def test_cli_exception_codes(monkeypatch, capsys, exception):
    def refuse(*args, **kwargs):
        raise exception(("pin",))

    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(installer, "verify", refuse)
    assert installer.main(["verify", "unused", "--pack-hash", "unused"]) == 3
    assert capsys.readouterr() == ("", exception.code + "\n")


@pytest.mark.parametrize("name", ["index.json", "manifest.json", "sealed/scoring.json"])
@pytest.mark.parametrize("data", [b"{", b"[]"])
def test_malformed_metadata_is_collected(installed, name, data):
    root, digest, index = installed
    target = root / name if name == "index.json" else pack_file(root, index, name)
    target.chmod(0o644)
    target.write_bytes(data)
    target.chmod(0o444)
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest)
    assert target.relative_to(root).as_posix() in error.value.fields
    assert "pack_hash" in error.value.fields


@pytest.mark.parametrize("interface", ["api", "cli"])
@pytest.mark.parametrize("name,mutation", [
    ("sealed/scoring.json", "float"),
    ("sealed/scoring.json", "nan"),
    ("index.json", "harness-float"),
    ("index.json", "deep"),
    ("manifest.json", "deep"),
    ("sealed/scoring.json", "deep"),
])
def test_noncanonical_metadata_is_collected(installed, name, mutation, interface):
    root, digest, index = installed
    target = root / name if name == "index.json" else pack_file(root, index, name)
    if mutation == "deep":
        data = b"[" * 200000
    else:
        value = json.loads(target.read_bytes())
        if mutation == "float":
            assert type(value["cases"][0]["item"]["probe_point"]) is int
            value["cases"][0]["item"]["probe_point"] = 1.0
        elif mutation == "nan":
            value["x"] = float("nan")
        else:
            value["harness_artifacts"][0]["version"] = 1.5
        data = json.dumps(value).encode("utf-8")
    target.chmod(0o644)
    try:
        target.write_bytes(data)
    finally:
        target.chmod(0o444)
    if interface == "api":
        with pytest.raises(PinnedArtifactChanged) as error:
            installer.verify(root, pack_hash=digest)
        assert target.relative_to(root).as_posix() in error.value.fields
        assert "pack_hash" in error.value.fields
    else:
        completed = command("verify", root, "--pack-hash", digest)
        assert (completed.returncode, completed.stdout, completed.stderr) == (
            3, "", "pinned_artifact_changed\n")


@pytest.mark.parametrize("name,key", [("index.json", "packs"), ("manifest.json", "files"),
                                      ("manifest.json", "pins")])
def test_malformed_metadata_mapping_is_collected(installed, name, key):
    root, digest, index = installed
    target = root / name if name == "index.json" else pack_file(root, index, name)
    edit_json(target, lambda value: value.update({key: []}))
    with pytest.raises(PinnedArtifactChanged) as error:
        installer.verify(root, pack_hash=digest)
    assert target.relative_to(root).as_posix() in error.value.fields
    assert "pack_hash" in error.value.fields


def test_unreadable_entry_still_collects_modes_and_file_failures(installed, monkeypatch):
    root, digest, index = installed
    target = pack_file(root, index, "sealed/pack.json")
    target.chmod(0)
    original = installer.os.open

    def unreadable(path, flags):
        if path == target:
            raise PermissionError("unreadable")
        return original(path, flags)

    with monkeypatch.context() as patch:  # undone before tmp_path's cleanup, which opens by descriptor (#348)
        patch.setattr(installer.os, "open", unreadable)
        with pytest.raises(PinnedArtifactChanged) as error:
            installer.verify(root, pack_hash=digest)
    rel = target.relative_to(root).as_posix()
    assert error.value.fields == tuple(sorted(("mode:" + rel, rel, "pack_hash")))
