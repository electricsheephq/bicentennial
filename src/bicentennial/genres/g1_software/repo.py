"""Isolated real git materialization, with no future objects or inherited config."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from bicentennial.contracts.surfaces import tree_hash, tree_listing

from .codebase_model import PATHS
from .diffs import VOLATILE, files_at, history, render, repo_tree_hash

BRANCH = "main"
MIN_GIT = (2, 32, 0)
LOCAL_CONFIG = (("core.hooksPath", os.devnull), ("core.excludesFile", os.devnull),
                ("core.attributesFile", os.devnull), ("core.autocrlf", "false"),
                ("core.fsmonitor", "false"), ("core.pager", "cat"), ("color.ui", "false"),
                ("commit.gpgSign", "false"), ("tag.gpgSign", "false"), ("gc.auto", "0"),
                ("maintenance.auto", "false"))


def _environment(tz, root=None):
    env = dict(PATH=os.defpath, LC_ALL="C", LANG="C", TZ=tz, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1",
               GIT_TERMINAL_PROMPT="0", GIT_NO_REPLACE_OBJECTS="1")
    if root is not None:
        env.update(GIT_DIR=str(root / ".git"), GIT_WORK_TREE=str(root))
    return env


def _run(argv, *, cwd, env, data=None):
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git unavailable")
    result = subprocess.run([git, *argv], cwd=cwd, env=env, input=data,
                            capture_output=True, timeout=60, check=False)
    if result.returncode:
        raise RuntimeError(f"git {argv[0]} exited {result.returncode}")
    return result.stdout


def git_version():
    raw = _run(["--version"], cwd=None, env=_environment("UTC"))
    match = re.match(rb"^git version (\d+)\.(\d+)\.(\d+)", raw)
    if match is None:
        raise RuntimeError("unrecognised git version")
    return tuple(int(part) for part in match.groups())


def run_git(root, argv, *, tz) -> bytes:
    root = Path(root).resolve()
    return _run(argv, cwd=root, env=_environment(tz, root))


def workspace_hash(root) -> str:
    return tree_hash(tree_listing(root, VOLATILE))


@dataclass(frozen=True)
class Repo:
    root: Path
    branch: str
    boundary: int
    head: str
    commits: int
    repo_tree_hash: str


def materialize(db, schedule, *, branch, boundary, root) -> Repo:
    root = Path(root).absolute()
    if branch not in ("B0", "B1") or type(boundary) is not int or boundary < schedule.sessions[0].t_start - 1:
        raise ValueError("invalid branch or boundary")
    if [tuple(r) for r in db.execute("SELECT seed, scale FROM meta")] != [(schedule.seed, schedule.scale.sessions)]:
        raise ValueError("world identity differs")
    actual = [tuple(r) for r in db.execute("SELECT idx, t_start, t_end, kind FROM session ORDER BY idx")]
    if actual != [(p.index, p.t_start, p.t_end, p.kind) for p in schedule.sessions]:
        raise ValueError("world sessions differ")
    if root.exists() or root.is_symlink() or not root.parent.is_dir():
        raise ValueError("root exists or parent missing")
    commits = [c for c in history(db, schedule) if c.t <= boundary]
    if git_version() < MIN_GIT:
        raise RuntimeError("git version below minimum")
    root.mkdir(mode=0o755)
    _run(["init", "--quiet", f"--initial-branch={BRANCH}", "--object-format=sha1", str(root)],
         cwd=root.parent, env=_environment(schedule.tz))
    env = _environment(schedule.tz, root)
    for key, value in LOCAL_CONFIG:
        _run(["config", "--local", key, value], cwd=root, env=env)
    previous = {}
    files = files_at(db, schedule, commits[0].t)
    state = {p: {} for p in PATHS.values()}
    for c in commits:
        if c.diff is not None:
            state[c.diff.path][c.diff.name] = c.diff.after
            files = files | render(state)
        for p, data in files.items():
            target = root / p
            if previous.get(p) != data:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            target.chmod(0o644)
        for directory in [root, *(p for p in root.rglob("*") if p.is_dir() and ".git" not in p.relative_to(root).parts)]:
            directory.chmod(0o755)
        date = f"@{c.t} {datetime.fromtimestamp(c.t, ZoneInfo(schedule.tz)).strftime('%z')}"
        identity = {f"GIT_{role}_{field}": value for role in ("AUTHOR", "COMMITTER")
                    for field, value in (("NAME", c.name), ("EMAIL", c.email), ("DATE", date))}
        _run(["add", "--all"], cwd=root, env=env)
        _run(["commit", "--quiet", "--no-verify", "--no-gpg-sign", "--cleanup=verbatim", "--file=-"],
             cwd=root, env=env | identity, data=(c.subject + "\n").encode())
        previous = files
    paths = [root, *(p for p in root.rglob("*") if ".git" not in p.relative_to(root).parts)]
    for path in paths:
        os.utime(path, (commits[-1].t, commits[-1].t))
    digest = workspace_hash(root)
    if digest != repo_tree_hash(db, schedule, boundary):
        raise RuntimeError("repository surface mismatch")
    head = run_git(root, ["rev-parse", "HEAD"], tz=schedule.tz).decode().strip()
    # Surface verification reads files; restore their simulated access times too.
    for path in paths:
        os.utime(path, (commits[-1].t, commits[-1].t))
    return Repo(root, branch, boundary, head, len(commits), digest)
