import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "public_check.py"
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "CANARY").write_text(CANARY + "\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "CANARY"], check=True)
    return tmp_path


def track(repo, name, text):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "--", name], check=True)


def check(repo, *paths, deny_list=None):
    env = dict(os.environ)
    env.pop("BICENTENNIAL_DENY_LIST", None)
    if deny_list is not None:
        env["BICENTENNIAL_DENY_LIST"] = str(deny_list)
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *(["--paths", *paths] if paths else [])],
        cwd=repo, env=env, capture_output=True, text=True,
    )


@pytest.mark.parametrize("root", ["Users", "home", "Volumes"])
def test_local_path_rejected(repo, root):
    track(repo, "bad.txt", "first line\n/" + root + "/example/private\n")
    result = check(repo, "bad.txt")
    assert result.returncode == 1
    assert "bad.txt:2: local filesystem path" in result.stdout


def test_deny_list_is_case_insensitive(repo):
    deny_list = repo / "deny.txt"
    deny_list.write_text("\nTest Person\n")
    track(repo, "name.txt", "A TEST PERSON appears here.\n")
    result = check(repo, "name.txt", deny_list=deny_list)
    assert result.returncode == 1
    assert "name.txt:1: deny-list name" in result.stdout
    assert "unset" not in result.stdout


@pytest.mark.parametrize("name", ["packs/x.json", "corpus/x.txt", "schemas/fixtures/x.json"])
def test_missing_canary_rejected(repo, name):
    track(repo, name, "{}\n")
    result = check(repo, name)
    assert result.returncode == 1
    assert f"{name}:1: missing canary GUID" in result.stdout


def test_clean_repo_passes(repo):
    track(repo, "readme.txt", "Public text.\n")
    track(repo, "packs/x.json", '{"canary":"' + CANARY + '"}\n')
    result = check(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "BICENTENNIAL_DENY_LIST unset; skipping deny-list check.\n"


def test_only_tracked_selected_paths_checked(repo):
    track(repo, "bad.txt", "/home/" + "example/private\n")
    track(repo, "ok.txt", "Public text.\n")
    (repo / "untracked.txt").write_text("/home/" + "example/private\n")
    assert check(repo, "ok.txt").returncode == 0
    subprocess.run(["git", "-C", str(repo), "rm", "--cached", "bad.txt"], check=True)
    assert check(repo).returncode == 0


def test_script_itself_is_skipped(repo):
    track(repo, "scripts/public_check.py", SCRIPT.read_text())
    assert check(repo).returncode == 0
