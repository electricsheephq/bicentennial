"""Pure repository history, file surfaces and scripted read evidence."""

import re
import tomllib
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_hash
from bicentennial.render.stream import lint
from bicentennial.world.db import insert_event, insert_link
from bicentennial.world.lineage import atomic
from bicentennial.world.processes import SALIENCE, mint

from .codebase_model import PATHS, Diff, diffs, state_at
from .world import EXPLICIT

REPO_PROCESS = "g1_repo"
TEMPLATE_IDENTITY = ("Template", "template@example.invalid")
TEMPLATE_FILES = (".gitignore", "README.md", "service/app.py", "service/config.py",
                  "tests/test_app.py", "tests/test_config.py")
REPO_FILES = tuple(sorted(TEMPLATE_FILES + tuple(PATHS.values())))
VOLATILE = (".git",)
EMPTY_TREE_HASH = tree_hash([])
TITLES = {"config/flags.toml": "Feature flags", "config/settings.toml": "Service settings",
          "service/routes.toml": "Service routes", "docs/decisions.md": "Decisions"}
LOG_ARGV = ("log", "--no-color", "--format=%aI %an %s")
CALLS = (("git", {"argv": list(LOG_ARGV)}),
         *(("git", {"argv": ["show", f"HEAD:{p}"]}) for p in sorted(PATHS.values())),
         *(("read_file", {"path": p}) for p in REPO_FILES))


@dataclass(frozen=True)
class Commit:
    t: int
    name: str
    email: str
    subject: str
    diff: Diff | None


def history(db, schedule) -> tuple[Commit, ...]:
    t0 = schedule.sessions[0].t_start - 1
    commits = [Commit(t0, *TEMPLATE_IDENTITY, "add_template: service", None)]
    pairs = {}
    for entity_id, kind, name in db.execute("SELECT id, kind, canonical_name FROM entity ORDER BY id"):
        if kind in PATHS:
            pair = (PATHS[kind], name)
            if pair in pairs:
                raise ValueError(f"duplicate name: {entity_id}")
            pairs[pair] = entity_id
    for d in diffs(db):
        name = db.execute("SELECT canonical_name FROM entity WHERE id = ?", (d.author_id,)).fetchone()[0]
        if not re.fullmatch(r"[A-Za-z]+( [A-Za-z]+)*", name):
            raise ValueError(f"invalid author: {d.author_id}")
        if not re.fullmatch(r"[a-z][a-z_ ]*[a-z]", d.name):
            raise ValueError(f"invalid name: {d.entity_id}")
        if not EXPLICIT.fullmatch(d.after) or d.after != d.after.strip(" "):
            raise ValueError(f"invalid value: {d.fact_id}")
        pair = (d.path, d.name)
        if pair in pairs and pairs[pair] != d.entity_id:
            raise ValueError(f"duplicate name: {d.entity_id}")
        pairs[pair] = d.entity_id
        if d.t <= t0:
            raise ValueError(f"early commit: {d.event_id}")
        commits.append(Commit(d.t, name, name.lower().replace(" ", ".") + "@example.invalid",
                              f"{d.op}: {d.name}", d))
    if any(datetime.fromtimestamp(c.t, ZoneInfo(schedule.tz)).strftime("%z") == "+0000" for c in commits):
        raise ValueError("zero commit offset")
    return tuple(commits)


def render(state) -> dict[str, bytes]:
    return {p: (f"# {TITLES[p]}\n" + "".join(
        f"- {n}: {v}\n" if p.endswith(".md") else f'"{n}" = "{v}"\n'
        for n, v in sorted(entries.items()))).encode("ascii") for p, entries in state.items()}


def files_at(db, schedule, boundary) -> dict[str, bytes]:
    history(db, schedule)
    template = Path(__file__).with_name("service_template")
    return {p: (template / p).read_bytes() for p in TEMPLATE_FILES} | render(state_at(db, boundary))


def read_state(root) -> dict[str, dict[str, str]]:
    state = {}
    try:
        for p in sorted(PATHS.values()):
            raw = (Path(root) / p).read_text(encoding="utf-8")
            if p.endswith(".md"):
                lines = raw.splitlines()
                if not lines or lines[0] != "# Decisions":
                    raise ValueError("invalid decisions heading")
                entries = [line[2:].split(": ", 1) for line in lines[1:] if line.startswith("- ")]
                if len(entries) != len(lines) - 1 or any(len(e) != 2 for e in entries):
                    raise ValueError("invalid decisions entry")
                data = dict(entries)
                if len(data) != len(entries):
                    raise ValueError("duplicate decision")
            else:
                data = tomllib.loads(raw)
            if any(type(k) is not str or not k or type(v) is not str or not v for k, v in data.items()):
                raise ValueError("invalid repository table")
            state[p] = data
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as error:
        raise ValueError("missing or malformed repository file") from error
    return state


def _plan(schedule, k):
    if type(k) is not int or not 1 <= k <= len(schedule.sessions):
        raise ValueError("invalid session")
    return schedule.sessions[k - 1]


def start_boundary(schedule, k):
    return _plan(schedule, k).t_start - 1


def end_boundary(schedule, k):
    return _plan(schedule, k).t_end - 1


def listing_at(files) -> list[dict]:
    rows, directories = [], set()
    for p, data in files.items():
        rows.append(dict(path=p, kind="file", mode=0o644, size=len(data), sha256=sha256(data).hexdigest()))
        directories.update(parent.as_posix() for parent in Path(p).parents if parent != Path("."))
    rows.extend(dict(path=p, kind="dir", mode=0o755) for p in directories)
    return sorted(rows, key=lambda row: row["path"])


def repo_tree_hash(db, schedule, boundary) -> str:
    return tree_hash(listing_at(files_at(db, schedule, boundary)))


def repo_tree_hashes(db, schedule) -> dict[int, str]:
    return {k: repo_tree_hash(db, schedule, end_boundary(schedule, k))
            for k in range(1, len(schedule.sessions) + 1)}


def normalise(data: bytes) -> str:
    return data.decode("utf-8").rstrip("\n")


def _check_call(name, args):
    try:
        found = canon((name, args)) in [canon(call) for call in CALLS]
    except TypeError as error:
        raise ValueError("invalid repository call") from error
    if not found:
        raise ValueError("unknown repository call")


def expected_result(db, schedule, *, boundary, name, args) -> dict:
    _check_call(name, args)
    commits = history(db, schedule)
    if name == "git" and args["argv"] == list(LOG_ARGV):
        return {"stdout": "\n".join(
            f"{datetime.fromtimestamp(c.t, ZoneInfo(schedule.tz)).isoformat()} {c.name} {c.subject}"
            for c in reversed(commits) if c.t <= boundary)}
    files = files_at(db, schedule, boundary)
    if name == "git":
        return {"stdout": normalise(files[args["argv"][1].removeprefix("HEAD:")])}
    return {"content": normalise(files[args["path"]])}


@dataclass(frozen=True, kw_only=True)
class Read:
    id: str
    session: int
    turn: int
    name: str
    args: dict


def write_reads(db, schedule, reads, *, principal) -> tuple[str, ...]:
    with atomic(db):
        if [r[0] for r in db.execute("SELECT seed FROM meta")] != [schedule.seed]:
            raise ValueError("world seed differs")
        if type(principal) is not str or not db.execute(
                "SELECT 1 FROM entity WHERE id = ? AND kind = 'person'", (principal,)).fetchone():
            raise ValueError("invalid principal")
        reads = tuple(reads)
        ids = [r.id for r in reads]
        if any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids):
            raise ValueError("empty or duplicate read id")
        pending = []
        for r in reads:
            plan = _plan(schedule, r.session)
            if type(r.turn) is not int or not 1 <= r.turn <= len(plan.turn_t):
                raise ValueError("invalid turn")
            eid = mint(schedule, REPO_PROCESS, r.id, "event", "read", 0)
            if db.execute("SELECT 1 FROM event WHERE id = ?", (eid,)).fetchone():
                raise ValueError(f"existing event: {eid}")
            b = start_boundary(schedule, r.session)
            result = expected_result(db, schedule, boundary=b, name=r.name, args=r.args)
            tool = {"name": r.name, "args": r.args}
            facts = set()
            for _, tid in lint(db, [{"event_id": eid, "payload": result, "tool": tool}]):
                if tid == "canary":
                    raise ValueError("canary in repository read")
                fid = db.execute("SELECT fact_id FROM locked_token WHERE token_id = ?", (tid,)).fetchone()[0]
                if not db.execute("SELECT 1 FROM fact_surface WHERE fact_id = ? AND surface = 'repo' "
                                  "AND from_t <= ?", (fid, b)).fetchone():
                    raise ValueError(f"coincidental token: {tid}")
                facts.add(fid)
            pending.append((eid, plan.turn_t[r.turn - 1], tool, result, facts))
        for eid, t, tool, result, facts in pending:
            insert_event(db, id=eid, t_sim=t, kind="tool", channel="tool_result", actor_id=principal,
                         audience_json=["agent"], visibility="shared", salience=SALIENCE,
                         payload_json={"tool": tool, "result": result})
            for fid in sorted(facts):
                insert_link(db, event_id=eid, fact_id=fid, role="mention")
        return tuple(p[0] for p in pending)
