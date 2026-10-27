"""G06 real-history, surface, scripted-read and refusal acceptance."""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from itertools import count
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.surfaces import tree_hash
from bicentennial.genres.g1_software import diffs as model
from bicentennial.genres.g1_software import repo
from bicentennial.genres.g1_software.codebase_model import PATHS, diffs, state_at
from bicentennial.genres.g1_software.diffs import (
    CALLS,
    EMPTY_TREE_HASH,
    LOG_ARGV,
    REPO_FILES,
    TEMPLATE_FILES,
    Read,
    end_boundary,
    expected_result,
    files_at,
    history,
    normalise,
    read_state,
    repo_tree_hash,
    repo_tree_hashes,
    start_boundary,
    write_reads,
)
from bicentennial.genres.g1_software.repo import materialize, run_git, workspace_hash
from bicentennial.genres.g1_software.world import (
    build_g1,
    build_golden,
    golden_schedule,
    load_golden,
    world_meta,
)
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import _canary, lint
from bicentennial.world import as_valid, create_world, export_jsonl, export_world
from bicentennial.world.db import (
    insert_entity,
    insert_event,
    insert_fact,
    insert_fact_surface,
    insert_link,
    insert_locked_token,
)
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule, write_sessions

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/g1_golden_tidewater.toml"
SERIAL = count()
# Filled from real isolated git builds; subprocess tests independently reproduce them.
KEYED_HEAD = "3be9be2dc5d1450ab659d146b1d86d40a30755b8"
GOLDEN_HEAD = "13435a0b1130bcdd61e41e06c9920fd1437062c6"
GOLDEN_TREE = "c11912bbfaf9438be6cfcdd9450f82b9d56a44aa5a235820e32b47af7c7f369b"


def world(tmp, seed="g06-0"):
    if seed == "6101":
        golden = load_golden(FIXTURE)
        schedule = golden_schedule(golden)
        db = create_world(tmp / f"w{next(SERIAL)}.db", world_meta(seed, 10))
        build_golden(db, golden, schedule)
        principal = db.execute("SELECT id FROM entity WHERE kind='person' ORDER BY id").fetchone()[0]
    else:
        schedule = build_schedule(seed, "life-a", named("t1"))
        db = create_world(tmp / f"w{next(SERIAL)}.db", world_meta(seed, 20))
        principal = build_g1(db, schedule).principal
    return db, schedule, principal


def build(tmp, db, schedule, boundary, branch="B0"):
    return materialize(db, schedule, branch=branch, boundary=boundary, root=tmp / f"r{next(SERIAL)}")


def git(result, schedule, *argv):
    return run_git(result.root, list(argv), tz=schedule.tz)


@pytest.fixture(scope="module")
def boundaries(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("repo-boundaries")
    started = monotonic()
    cases = []
    for seed in [*(f"g06-{n}" for n in range(10)), "6101"]:
        db, schedule, principal = world(tmp, seed)
        builds = [build(tmp, db, schedule, end_boundary(schedule, k))
                  for k in range(1, len(schedule.sessions) + 1)]
        cases.append((seed, db, schedule, principal, builds))
    print(f"\nG06 boundary materializations (200 keyed + 10 golden): {monotonic() - started:.3f}s")
    yield cases
    for _, db, _, _, _ in cases:
        db.close()


def test_boundary_properties(boundaries):
    for seed, db, schedule, _, builds in boundaries:
        ds = diffs(db)
        for result in builds:
            b = result.boundary
            assert result.repo_tree_hash == repo_tree_hash(db, schedule, b) == workspace_hash(result.root)
            assert int(git(result, schedule, "rev-list", "--all", "--count")) == result.commits
            assert result.commits == 1 + db.execute(
                "SELECT count(*) FROM event WHERE kind='commit' AND t_sim<=?", (b,)).fetchone()[0]
            assert read_state(result.root) == state_at(db, b)
            files = files_at(db, schedule, b)
            for p in PATHS.values():
                assert git(result, schedule, "show", f"HEAD:{p}") == files[p]
                names = {d.name for d in ds if d.path == p and d.t <= b}
                assert set(read_state(result.root)[p]) == names
            for d in ds:
                assert as_valid(db, d.entity_id, d.key, d.t) == d.after
                if d.t <= b:
                    assert read_state(result.root)[d.path][d.name] == as_valid(db, d.entity_id, d.key, b)
            head_t = int(git(result, schedule, "log", "-1", "--format=%ct"))
            for p in [result.root, *result.root.rglob("*")]:
                if ".git" not in p.relative_to(result.root).parts:
                    assert int(p.stat().st_mtime) == head_t
        assert builds[-1].commits == (1 if seed == "6101" else 10)


def test_pure_gap_property_200_worlds(tmp_path):
    started = monotonic()
    for n in range(200):
        db, schedule, _ = world(tmp_path, f"g06-{n}")
        for k in range(1, 20):
            assert repo_tree_hash(db, schedule, start_boundary(schedule, k + 1)) == repo_tree_hash(
                db, schedule, end_boundary(schedule, k))
        db.close()
    print(f"\nG06 pure gap loop (200 seeds x 19 gaps): {monotonic() - started:.3f}s")


def test_expected_results_real(boundaries):
    for seed, db, schedule, _, builds in boundaries:
        if seed not in ["6101", *(f"g06-{i}" for i in range(5))]:
            continue
        for result in builds:
            for name, args in CALLS:
                expected = expected_result(db, schedule, boundary=result.boundary, name=name, args=args)
                if name == "git":
                    actual = {"stdout": normalise(git(result, schedule, *args["argv"]))}
                else:
                    actual = {"content": normalise((result.root / args["path"]).read_bytes())}
                assert sha256_canon(expected) == sha256_canon(actual)
    _, db, schedule, _, builds = boundaries[0]
    result = builds[-1]
    env = {"PATH": os.defpath, "LC_ALL": "C", "LANG": "C", "TZ": schedule.tz,
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_ATTR_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1",
           "GIT_DIR": str(result.root / ".git"), "GIT_WORK_TREE": str(result.root)}
    actual = subprocess.run(["git", *LOG_ARGV], cwd=result.root, env=env,
                            capture_output=True, timeout=60, check=True).stdout
    assert {"stdout": normalise(actual)} == expected_result(
        db, schedule, boundary=result.boundary, name="git", args={"argv": list(LOG_ARGV)})


def test_dates_and_identities(boundaries):
    _, db, schedule, _, builds = boundaries[0]
    result = builds[-1]
    rows = git(result, schedule, "log", "--format=%at|%ct|%an|%ae|%cn|%ce|%aI").decode().splitlines()
    for row, c in zip(rows, reversed(history(db, schedule)), strict=True):
        at, ct, an, ae, cn, ce, iso = row.split("|")
        assert int(at) == int(ct) == c.t
        assert an == cn == c.name and ae == ce == c.email and ae.endswith("@example.invalid")
        assert iso == datetime.fromtimestamp(c.t, ZoneInfo(schedule.tz)).isoformat()
    assert git(result, schedule, "cat-file", "commit", "HEAD").endswith(
        b"\n\n" + history(db, schedule)[-1].subject.encode() + b"\n")


def test_no_future_objects(boundaries):
    _, db, schedule, _, builds = boundaries[0]
    for result in builds:
        objects = git(result, schedule, "cat-file", "--batch-all-objects", "--batch-check=%(objectname)")
        reachable = git(result, schedule, "rev-list", "--objects", "--all")
        assert set(objects.splitlines()) == {line.split()[0] for line in reachable.splitlines()}
        assert git(result, schedule, "for-each-ref", "--format=%(refname)") == b"refs/heads/main\n"
        dump = git(result, schedule, "cat-file", "--batch-all-objects", "--batch")
        worktree = b"\n".join((result.root / p).read_bytes() for p in REPO_FILES)
        for d in diffs(db):
            if d.t > result.boundary:
                assert d.after.encode() not in dump and d.after.encode() not in worktree
            else:
                assert d.after.encode() in dump
        assert all(p.name.endswith(".sample") for p in (result.root / ".git/hooks").iterdir())
        assert git(result, schedule, "config", "--local", "--get", "commit.gpgsign") == b"false\n"


SCRIPT = '''
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from bicentennial.genres.g1_software.world import world_meta, build_g1, load_golden, golden_schedule, build_golden
from bicentennial.genres.g1_software.diffs import end_boundary, repo_tree_hashes
from bicentennial.genres.g1_software.repo import materialize, run_git
from bicentennial.world import create_world
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
out = []
with TemporaryDirectory() as tmp:
    parent = Path(tmp)
    for seed in ("g06-0", "6101"):
        if seed == "6101":
            golden = load_golden("tests/fixtures/g1_golden_tidewater.toml")
            schedule = golden_schedule(golden)
        else:
            schedule = build_schedule(seed, "life-a", named("t1"))
        db = create_world(parent / (seed + ".db"), world_meta(seed, len(schedule.sessions)))
        if seed == "6101":
            build_golden(db, golden, schedule)
        else:
            build_g1(db, schedule)
        hashes = repo_tree_hashes(db, schedule)
        result = materialize(db, schedule, branch="B0", boundary=end_boundary(schedule, len(schedule.sessions)),
                             root=parent / seed)
        out.append([run_git(result.root, ["rev-list", "--all"], tz=schedule.tz).decode(),
                    result.repo_tree_hash, hashes])
        db.close()
print(json.dumps(out, sort_keys=True))
'''


def test_process_determinism(boundaries):
    outputs = [subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT,
                              env=dict(os.environ, PYTHONHASHSEED=seed),
                              capture_output=True, check=True, timeout=60).stdout
               for seed in ("0", "random")]
    assert outputs[0] == outputs[1]
    actual = json.loads(outputs[0])
    for i, case in enumerate((boundaries[0], boundaries[-1])):
        _, db, schedule, _, builds = case
        result = builds[-1]
        assert actual[i] == [git(result, schedule, "rev-list", "--all").decode(), result.repo_tree_hash,
                             {str(k): v for k, v in repo_tree_hashes(db, schedule).items()}]
    assert boundaries[0][-1][-1].head == KEYED_HEAD
    assert boundaries[-1][-1][-1].head == GOLDEN_HEAD
    assert boundaries[-1][-1][-1].repo_tree_hash == GOLDEN_TREE


def test_config_isolation(tmp_path, monkeypatch, boundaries):
    home = tmp_path / "hostile-home"
    hooks = home / "hooks"
    hooks.mkdir(parents=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    (home / ".gitconfig").write_text(
        f"[commit]\n gpgSign = true\n[core]\n hooksPath = {hooks}\n autocrlf = true\n"
        "[user]\n name = Wrong Person\n[init]\n defaultBranch = other\n")
    config = home / ".config/git"
    config.mkdir(parents=True)
    (config / "ignore").write_text("*.md\n")
    (config / "attributes").write_text("* text eol=crlf\n")
    for key, value in {"HOME": str(home), "GIT_DIR": "unrelated", "GIT_TEMPLATE_DIR": "unrelated",
                       "GIT_AUTHOR_NAME": "Unrelated", "XDG_CONFIG_HOME": str(home / ".config")}.items():
        monkeypatch.setenv(key, value)
    _, db, schedule, _, builds = boundaries[0]
    result = build(tmp_path, db, schedule, end_boundary(schedule, 20))
    assert result.head == builds[-1].head
    assert result.repo_tree_hash == builds[-1].repo_tree_hash


def test_generated_tests_every_commit(tmp_path):
    for seed in ("6101", "g06-0", "g06-1", "g06-2"):
        db, schedule, _ = world(tmp_path, seed)
        for c in history(db, schedule):
            result = build(tmp_path, db, schedule, c.t)
            before = workspace_hash(result.root)
            command = [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests"]
            env = {"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"}
            run = subprocess.run(command, cwd=result.root, env=env, capture_output=True, timeout=60)
            assert run.returncode == 0, run.stderr.decode()
            assert workspace_hash(result.root) == before
        broken = tmp_path / f"broken{next(SERIAL)}"
        shutil.copytree(result.root, broken)
        (broken / "config/settings.toml").write_text('"x" = 1\n')
        assert subprocess.run(command, cwd=broken, env=env, capture_output=True, timeout=60).returncode != 0
        db.close()


def reads(session=18):
    return [Read(id=f"read-{i}", session=session, turn=i % 5 + 1, name=name, args=args)
            for i, (name, args) in enumerate(CALLS)]


@pytest.mark.parametrize("argv", [LOG_ARGV, *(tuple(args["argv"]) for name, args in CALLS[1:] if name == "git")])
def test_tuple_argv_results_and_reads(tmp_path, argv):
    db, schedule, principal = world(tmp_path)
    try:
        tuple_args, list_args = {"argv": argv}, {"argv": list(argv)}
        boundary = start_boundary(schedule, 18)
        expected = expected_result(db, schedule, boundary=boundary, name="git", args=list_args)
        assert expected_result(db, schedule, boundary=boundary, name="git", args=tuple_args) == expected
        rs = [Read(id=f"argv-{i}", session=18, turn=1, name="git", args=args)
              for i, args in enumerate((tuple_args, list_args))]
        ids = write_reads(db, schedule, rs, principal=principal)
        payloads = [json.loads(db.execute("SELECT payload_json FROM event WHERE id=?", (eid,)).fetchone()[0])
                    for eid in ids]
        assert payloads[0] == payloads[1]
        assert payloads[0]["result"] == expected
        assert canon(payloads[0]["tool"]["args"]) == canon(tuple_args) == canon(list_args)
    finally:
        db.close()


def test_reads_in_world(tmp_path):
    db, schedule, principal = world(tmp_path)
    assert any(schedule.sessions[17].t_start <= d.t < schedule.sessions[17].t_end for d in diffs(db))
    before, ds = export_jsonl(db), diffs(db)
    ids = write_reads(db, schedule, reads(), principal=principal)
    hashes = repo_tree_hashes(db, schedule)
    result = cut(db, schedule, branch="B0", principal_id=principal,
                 expected_state={k: {"repo_tree_hash": h, "env_state_hash": "b" * 64} for k, h in hashes.items()})
    assert lint(db, result.rows) == []
    rows = {row["event_id"]: row for row in result.rows}
    changed = False
    for eid, r in zip(ids, reads(), strict=True):
        row = rows[eid]
        payload = expected_result(db, schedule, boundary=start_boundary(schedule, 18), name=r.name, args=r.args)
        assert row["payload"] == payload
        changed |= payload != expected_result(db, schedule, boundary=end_boundary(schedule, 18),
                                              name=r.name, args=r.args)
        assert row["expected_result_sha256"] == sha256_canon(payload)
        held = sorted(fid for fid, value in db.execute("SELECT fact_id, value FROM locked_token")
                      if any(value in part for part in payload.values()))
        assert row["fact_ids"] == held
        assert sorted(tuple(x) for x in db.execute("SELECT fact_id, role FROM link WHERE event_id=?", (eid,))) == [
            (fid, "mention") for fid in held]
    assert changed
    export_world(db)
    assert diffs(db) == ds
    assert set(before.splitlines()) <= set(export_jsonl(db).splitlines())
    assert db.in_transaction
    db.close()


def add_token(db, value):
    insert_fact(db, id="extra-fact", subject_id="marker", predicate="value", object=value, polarity="affirm",
                modality="stated", strength=1000, speech_act="assert")
    insert_locked_token(db, token_id="extra-token", fact_id="extra-fact", kind="name", value=value)


def marker(db):
    insert_entity(db, id="marker", kind="flag", canonical_name="marker", aliases_json=[], created_t=0, retired_t=None)


@pytest.mark.parametrize("bad", ["log-p", "show-readme", "session", "turn", "principal", "duplicate",
                                      "coincidence", "seed", "existing", "empty", "canary", "float"])
def test_read_refusals_atomic(tmp_path, bad, monkeypatch):
    db, schedule, principal = world(tmp_path)
    marker(db)  # Must survive the refused writer in this same transaction.
    rs = [reads()[0]]
    if bad == "log-p":
        rs = [replace(rs[0], args={"argv": ["log", "-p"]})]
    elif bad == "show-readme":
        rs = [replace(rs[0], args={"argv": ["show", "HEAD:README.md"]})]
    elif bad == "float":
        rs = [replace(rs[0], args={"argv": [1.5]})]
    elif bad == "session":
        rs = [replace(rs[0], session=0)]
    elif bad == "turn":
        rs = [replace(rs[0], turn=6)]
    elif bad == "principal":
        principal = "marker"
    elif bad == "duplicate":
        rs *= 2
    elif bad == "seed":
        schedule = replace(schedule, seed="other")
    elif bad == "existing":
        write_reads(db, schedule, rs, principal=principal)
    elif bad == "empty":
        rs = [replace(rs[0], id="")]
    elif bad == "coincidence":
        add_token(db, "small service")
        rs = [Read(id="readme", session=18, turn=1, name="read_file", args={"path": "README.md"})]
    elif bad == "canary":
        monkeypatch.setattr(model, "expected_result", lambda *a, **kw: {"stdout": _canary()})
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        write_reads(db, schedule, rs, principal=principal)
    assert export_jsonl(db) == before
    assert db.execute("SELECT 1 FROM entity WHERE id='marker'").fetchone()
    assert db.in_transaction
    db.close()


@pytest.mark.parametrize("bad", ["branch", "exists", "parent", "bool", "early", "seed", "sessions", "version"])
def test_materialize_refusals(tmp_path, bad, monkeypatch):
    db, schedule, _ = world(tmp_path)
    kwargs = dict(branch="B0", boundary=end_boundary(schedule, 20), root=tmp_path / "repo")
    error = ValueError
    if bad == "branch":
        kwargs["branch"] = "B2"
    elif bad == "exists":
        kwargs["root"].mkdir()
    elif bad == "parent":
        kwargs["root"] = tmp_path / "missing/repo"
    elif bad == "bool":
        kwargs["boundary"] = True
    elif bad == "early":
        kwargs["boundary"] = start_boundary(schedule, 1) - 1
    elif bad == "seed":
        schedule = replace(schedule, seed="other")
    elif bad == "sessions":
        schedule = replace(schedule, sessions=(replace(schedule.sessions[0], t_end=1), *schedule.sessions[1:]))
    elif bad == "version":
        monkeypatch.setattr(repo, "git_version", lambda: (2, 31, 9))
        error = RuntimeError
    marker(db)
    before = export_jsonl(db)
    with pytest.raises(error):
        materialize(db, schedule, **kwargs)
    assert export_jsonl(db) == before
    assert db.in_transaction
    db.close()


def tiny(tmp, *, author="Heron", name="quiet_retry", value="FLAG-abcdef", duplicate=False, early=False, kind="flag"):
    schedule = build_schedule("tiny", "life-a", named("t1"))
    db = create_world(tmp / f"tiny{next(SERIAL)}.db", world_meta(schedule.seed, 20))
    write_sessions(db, schedule)
    insert_entity(db, id="P", kind="person", canonical_name=author, aliases_json=[], created_t=0, retired_t=None)
    for i in range(2 if duplicate else 1):
        insert_entity(db, id=f"F{i}", kind=kind, canonical_name=name, aliases_json=[], created_t=0, retired_t=None)
        t = schedule.sessions[0].t_start + i if not early else start_boundary(schedule, 1)
        insert_event(db, id=f"c{i}", t_sim=t, kind="commit", channel="commit", actor_id="P",
                     audience_json=["agent"], visibility="shared", salience=500, payload_json={})
        insert_fact(db, id=f"f{i}", subject_id=f"F{i}", predicate="default", object=value + str(i), polarity="affirm",
                    modality="stated", strength=1000, speech_act="assert")
        insert_locked_token(db, token_id=f"k{i}", fact_id=f"f{i}", kind="code", value=value + str(i))
        insert_link(db, event_id=f"c{i}", fact_id=f"f{i}", role="mention")
    return db, schedule


@pytest.mark.parametrize("bad", ["duplicate", "quote", "name", "author", "utc", "early", "space"])
def test_history_refusals(tmp_path, bad):
    kwargs = {"duplicate": {"duplicate": True}, "quote": {"value": 'FLAG-"abc'},
              "name": {"name": "Quiet-Retry"}, "author": {"author": "Heron One1"},
              "early": {"early": True}, "space": {"value": " FLAG-abc"}}
    db, schedule = tiny(tmp_path, **kwargs.get(bad, {}))
    if bad == "utc":
        schedule = replace(schedule, tz="UTC")
    marker(db)
    before = export_jsonl(db)
    with pytest.raises(ValueError):
        history(db, schedule)
    assert export_jsonl(db) == before and db.in_transaction
    db.close()


def test_read_state_refusals_and_boundaries(tmp_path):
    db, schedule, _ = world(tmp_path)
    result = build(tmp_path, db, schedule, end_boundary(schedule, 20))
    target = result.root / "docs/decisions.md"
    original = target.read_bytes()
    for raw in (b"", b"# Other\n", b"# Decisions\nwrong\n", b"# Decisions\n- a: b\n- a: c\n"):
        target.write_bytes(raw)
        with pytest.raises(ValueError):
            read_state(result.root)
    target.write_bytes(original)
    settings = result.root / "config/settings.toml"
    for raw in (b"?", b'"x" = 1\n', b'"x" = ""\n', b"\xff"):
        settings.write_bytes(raw)
        with pytest.raises(ValueError):
            read_state(result.root)
    settings.unlink()
    with pytest.raises(ValueError):
        read_state(result.root)
    for k in (True, 0, 21):
        for function in (start_boundary, end_boundary):
            with pytest.raises(ValueError):
                function(schedule, k)
    with pytest.raises(UnicodeDecodeError):
        normalise(b"\xff")
    assert normalise(b"a\n\n") == "a"
    db.close()


def test_golden_and_template(boundaries, tmp_path):
    _, db, schedule, _, builds = boundaries[-1]
    assert diffs(db) == ()
    assert len(set(repo_tree_hashes(db, schedule).values())) == 1
    values = [v for (v,) in db.execute("SELECT value FROM locked_token")]
    for result in builds:
        dump = git(result, schedule, "cat-file", "--batch-all-objects", "--batch")
        files = [(result.root / p).read_bytes() for p in REPO_FILES]
        assert all(v.encode() not in dump and all(v.encode() not in data for data in files) for v in values)
        assert b"defaults to off" not in (result.root / "config/flags.toml").read_bytes()
    template = Path(model.__file__).with_name("service_template")
    paths = sorted(p.relative_to(template).as_posix() for p in template.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts)
    assert paths == sorted(TEMPLATE_FILES)
    tokens = [_canary(), *(v for _, db, _, _, _ in boundaries for (v,) in db.execute("SELECT value FROM locked_token"))]
    for p in paths:
        data = (template / p).read_bytes()
        assert data.decode("ascii").endswith("\n") and b"\r" not in data
        assert not re.search(rb"[0-9]{4}", data)
        assert all(v.encode() not in data for v in tokens)
        if p.endswith(".py"):
            ast.parse(data)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert EMPTY_TREE_HASH == tree_hash([]) == workspace_hash(empty) == (
        "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945")


def test_import_boundaries():
    forbidden = {"random", "time", "socket", "ssl", "http", "urllib", "subprocess", "shutil",
                 "bicentennial.sandbox", "bicentennial.director", "spikes"}
    for module in (model, repo):
        blocked = forbidden - ({"subprocess", "shutil"} if module is repo else set())
        for node in ast.walk(ast.parse(Path(module.__file__).read_bytes())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n == b or n.startswith(b + ".") for n in names for b in blocked)


def test_unread_config_flip_identical_reads(tmp_path):
    # Two G01-built worlds differ only in one constant's locked value. The reads
    # inspect a different path and retain identical event bytes and mention links.
    rows = []
    hashes = []
    for branch, value in (("B0", "CONST-alpha"), ("B1", "CONST-bravo")):
        db, schedule = tiny(tmp_path, value=value, kind="constant", name="batch_size")
        t = schedule.sessions[0].t_start + 1
        insert_entity(db, id="stable-flag", kind="flag", canonical_name="quiet_retry", aliases_json=[],
                      created_t=0, retired_t=None)
        insert_event(db, id="stable-commit", t_sim=t, kind="commit", channel="commit", actor_id="P",
                     audience_json=["agent"], visibility="shared", salience=500, payload_json={})
        insert_fact(db, id="stable-fact", subject_id="stable-flag", predicate="default", object="FLAG-stable",
                    polarity="affirm", modality="stated", strength=1000, speech_act="assert")
        insert_locked_token(db, token_id="stable-token", fact_id="stable-fact", kind="code", value="FLAG-stable")
        insert_link(db, event_id="stable-commit", fact_id="stable-fact", role="mention")
        insert_fact_surface(db, fact_id="stable-fact", surface="repo", from_t=t)
        r = Read(id="unread-flip", session=2, turn=1, name="read_file", args={"path": "config/flags.toml"})
        (eid,) = write_reads(db, schedule, [r], principal="P")
        result = build(tmp_path, db, schedule, start_boundary(schedule, 2), branch)
        hashes.append(result.repo_tree_hash)
        assert expected_result(db, schedule, boundary=result.boundary, name=r.name, args=r.args) == {
            "content": normalise((result.root / r.args["path"]).read_bytes())}
        read_rows = []
        for line in export_jsonl(db).splitlines():
            exported = json.loads(line)
            if (exported["table"] == "event" and exported["row"]["id"] == eid) or (
                    exported["table"] == "link" and exported["row"]["event_id"] == eid):
                read_rows.append(line)
        rows.append(read_rows)
        db.close()
    assert rows[0] == rows[1] and len(rows[0]) == 2
    assert hashes[0] != hashes[1]


def test_git_failures_and_partial_root(tmp_path, monkeypatch):
    db, schedule, _ = world(tmp_path)
    monkeypatch.setattr(repo.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="unavailable"):
        repo.git_version()
    monkeypatch.undo()
    monkeypatch.setattr(repo.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1, b"", b"secret"))
    with pytest.raises(RuntimeError, match="git --version exited 1"):
        repo.git_version()
    monkeypatch.undo()
    original = repo._run

    def fail(argv, **kwargs):
        if argv[0] == "config":
            raise RuntimeError("injected config failure")
        return original(argv, **kwargs)

    monkeypatch.setattr(repo, "_run", fail)
    target = tmp_path / "partial"
    with pytest.raises(RuntimeError, match="injected"):
        materialize(db, schedule, branch="B0", boundary=end_boundary(schedule, 20), root=target)
    assert target.is_dir() and (target / ".git").is_dir()
    db.close()
