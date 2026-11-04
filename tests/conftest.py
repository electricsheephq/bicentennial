"""Local Git checkouts and whole-file CI shards, balanced by measured durations.

Place longest files first on the least-loaded shard; emit per-file timings for refreshes.
"""

import json
import math
import os
import subprocess
from pathlib import Path
from statistics import median
from types import SimpleNamespace

import pytest

from bicentennial.sandbox import fixedroot


@pytest.fixture(autouse=True)
def fixedroot_parent(tmp_path_factory, monkeypatch):
    monkeypatch.setattr(fixedroot, "PARENT", os.path.realpath(tmp_path_factory.mktemp("fixedroot")))


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


def place(files, weights, total):
    """Return deterministic whole-file assignments, longest first, with low-index ties."""
    fallback = median(weights.values()) if weights else 1.0
    loads = [0.0] * total
    placement = {}
    for path in sorted(files, key=lambda path: (-weights.get(path, fallback), path)):
        index = min(range(total), key=lambda index: (loads[index], index))
        placement[path] = index
        loads[index] += weights.get(path, fallback)
    return placement


def _load_weights():
    path = Path(__file__).with_name("shard_weights.json")
    try:
        weights = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(weights, dict) or any(
            not isinstance(name, str) or not name or type(seconds) not in (int, float)
            or not math.isfinite(seconds) or seconds < 0
            for name, seconds in weights.items()
        ):
            raise ValueError("expected an object of file paths to finite nonnegative seconds")
        return weights
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, OverflowError) as exc:
        raise pytest.UsageError(f"cannot load {path}: {exc}") from exc


class _ShardDurations:
    def __init__(self, index, total):
        self.index = index
        self.total = total
        self.seconds = {}

    def pytest_runtest_logreport(self, report):
        path = report.nodeid.split("::", 1)[0]
        self.seconds[path] = self.seconds.get(path, 0.0) + report.duration

    def pytest_terminal_summary(self, terminalreporter):
        payload = json.dumps({path: round(seconds, 1) for path, seconds in self.seconds.items()},
                             sort_keys=True, separators=(",", ":"))
        terminalreporter.write_line(f"shard-durations v1 {self.index} {self.total} {payload}")


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
    files = sorted({item.nodeid.split("::", 1)[0] for item in items})
    placement = place(files, _load_weights(), total)
    config.pluginmanager.register(_ShardDurations(index, total))
    keep, drop = [], []
    for item in items:
        (keep if placement[item.nodeid.split("::", 1)[0]] == index else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep
