import os

import pytest

from bicentennial.gitenv import git_env


@pytest.mark.parametrize("present", [False, True])
def test_git_env_removes_only_location_variables(monkeypatch, present):
    locations = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")
    for name in locations:
        if present:
            monkeypatch.setenv(name, "conflicting-location")
        else:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "preserved-config")
    monkeypatch.setenv("BICENTENNIAL_GIT_ENV_TEST", "preserved-value")
    original = dict(os.environ)
    env = git_env()
    assert env == {name: value for name, value in original.items() if name not in locations}
    assert dict(os.environ) == original
    env["BICENTENNIAL_GIT_ENV_TEST"] = "changed-copy"
    assert os.environ["BICENTENNIAL_GIT_ENV_TEST"] == "preserved-value"
