"""Environment for Git commands targeting an explicit checkout."""

import os


def git_env() -> dict[str, str]:
    """Copy the process environment without inherited repository locations."""
    env = os.environ.copy()
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        env.pop(name, None)
    return env
