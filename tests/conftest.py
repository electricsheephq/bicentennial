"""Small, local Git checkouts for environment-isolation regressions, and CI's test shards."""

import hashlib
import os
import subprocess
from types import SimpleNamespace

import pytest


@pytest.fixture
def git_checkouts(tmp_path, monkeypatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    for name, value in {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Git isolation test",
        "GIT_AUTHOR_EMAIL": "git-test@example.invalid",
        "GIT_COMMITTER_NAME": "Git isolation test",
        "GIT_COMMITTER_EMAIL": "git-test@example.invalid",
        "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    }.items():
        monkeypatch.setenv(name, value)
    roots, heads = [], []
    for label in ("checkout", "other"):
        root = tmp_path / label
        root.mkdir()
        (root / "README").write_text(label + "\n")
        if label == "other":
            (root / "other-only.txt").write_text("Only tracked by the conflicting repository.\n")
        for argv in (
            ["init", "-q", "--template=", "--initial-branch=main", "--object-format=sha1"],
            ["add", "."],
            ["-c", "core.hooksPath=" + os.devnull, "commit", "-q", "--no-verify",
             "--no-gpg-sign", "-m", label],
        ):
            subprocess.run(["git", "-C", str(root), *argv], check=True, capture_output=True)
        heads.append(subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                                    check=True, capture_output=True, text=True).stdout.strip())
        roots.append(root)
    checkout, other = roots
    head, other_head = heads
    assert head != other_head
    archive = subprocess.run(["git", "-C", str(checkout), "archive", "--format=tar", "HEAD"],
                             check=True, capture_output=True).stdout
    return SimpleNamespace(checkout=checkout, other=other, head=head, other_head=other_head,
                           archive=archive, conflict={
                               "GIT_DIR": str(other / ".git"),
                               "GIT_WORK_TREE": str(other),
                               "GIT_INDEX_FILE": str(other / ".git/index"),
                               "GIT_COMMON_DIR": str(other / ".git"),
                           })


def shard_of(path, total):
    """The CI shard that runs every test in one test file."""
    return int(hashlib.sha256(path.encode()).hexdigest(), 16) % total


def _shard_setting(name):
    value = os.environ.get(name, "")
    try:
        return int(value)
    except ValueError:
        raise pytest.UsageError(f"{name} must be an integer, not {value!r}") from None


def pytest_collection_modifyitems(config, items):
    if not os.environ.get("BICENTENNIAL_TEST_SHARDS"):
        return
    total = _shard_setting("BICENTENNIAL_TEST_SHARDS")
    if total < 2:
        return
    index = _shard_setting("BICENTENNIAL_TEST_SHARD")
    if not 0 <= index < total:
        raise pytest.UsageError("BICENTENNIAL_TEST_SHARD is out of range")
    keep, drop = [], []
    for item in items:
        (keep if shard_of(item.nodeid.split("::", 1)[0], total) == index else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
