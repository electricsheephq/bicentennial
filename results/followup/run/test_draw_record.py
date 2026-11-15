"""Offline draw rules, including frozen comment decisions and uncertain sends."""

import fcntl
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("draw_record.py")
COMMIT, OTHER = "a" * 40, "b" * 40
DECL_COMMIT = "c" * 40
GENESIS, N = 1692803367, 1001
DUE = GENESIS + (N - 1) * 3
MERGE = DUE - 2000
LOGIN, AUTHOR = "synthetic-merge", 71
SENTINEL = "synthetic-private-sentinel"


@pytest.fixture
def dr():
    spec = importlib.util.spec_from_file_location("draw_record", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def body(kind="first", n=N, commit=COMMIT, tail=""):
    names = {"first": "first post", "second": "second post", "tasks": "task lists", "stop": "stop"}
    commit_line = "" if kind == "tasks" else f"run_commit {commit}\n"
    return f"Follow-up draw: {names[kind]}\nround {n}\n{commit_line}{tail}"


def comment(cid=1, when=DUE - 900, text=None, author=AUTHOR, **extra):
    return {"id": cid, "author": author, "created_at": stamp(when),
            "body": body() if text is None else text, "lastEditedAt": None,
            "includesCreatedEdit": False, "edits": [], **extra}


def rec(kind, data, number):
    return {"kind": kind, "data": data, "number": number}


def declaration():
    raw = b"synthetic declaration\n"
    return {"merging_id": AUTHOR, "merging_login": LOGIN, "merge_time": stamp(MERGE),
            "declaration_commit": DECL_COMMIT, "sha256": hashlib.sha256(raw).hexdigest(), "length": len(raw)}


def evidence(merged=MERGE + 1, **changes):
    data = {"commit": COMMIT, "github_time": DUE - 900, "default_branch": "main", "default_branch_after": "main",
            "content": {"status": 200, "sha256": declaration()["sha256"], "length": declaration()["length"]},
            "pulls": [{"number": 71, "base": "main", "merged_at": stamp(merged),
                       "merge_commit_sha": OTHER, "compare": "ahead"}]}
    return {**data, **changes}


def records(comments=(), ev=None):
    return [rec("declaration", declaration(), 1),
            rec("read", {"github_time": DUE - 800, "comments": list(comments)}, 2),
            rec("evidence", evidence() if ev is None else ev, 3)]


def http(data, status=200, when=DUE - 900, exit=0, contains=None, lf=False):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    header = f"HTTP/2.0 {status} Synthetic\r\nDate: {format_datetime(datetime.fromtimestamp(when, UTC), usegmt=True)}\r\nX-Example: yes\r\n\r\n".encode()
    if lf:
        header = header.replace(b"\r\n", b"\n")
    return {"output": (header + raw).hex(), "exit": exit, "contains": contains}


def relay(data, exit=0):
    return {"output": (data if isinstance(data, bytes) else json.dumps(data).encode()).hex(), "exit": exit}


def pr(**changes):
    return {"merged": True, "merged_by": {"login": LOGIN, "id": AUTHOR}, "merged_at": stamp(MERGE),
            "merge_commit_sha": DECL_COMMIT, **changes}


def evidence_steps(when=DUE - 900, merged=MERGE + 1, pulls=None):
    return [http({}, when=when, contains="rate_limit"),
            http({"default_branch": "main"}, when=when, contains="repos/"),
            http(b"synthetic declaration\n", when=when, contains="contents/"),
            http([{"number": 71, "base": {"ref": "main"}, "merged_at": stamp(merged),
                   "merge_commit_sha": OTHER}] if pulls is None else pulls, when=when, contains="/pulls"),
            http({"default_branch": "main"}, when=when, contains="repos/"),
            *([http({"status": "ahead"}, when=when, contains="compare/")] if pulls is None else [])]


def page(nodes, more=False, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}


def graph_comment(cid=1, **changes):
    return {"id": f"node-{cid}", "fullDatabaseId": str(cid), "author": {"login": LOGIN, "databaseId": AUTHOR},
            "createdAt": stamp(DUE - 900), "lastEditedAt": None,
            "includesCreatedEdit": False, "body": body(), "userContentEdits": page([]), **changes}


def graph(nodes, more=False, cursor=None):
    return {"data": {"repository": {"issue": {"comments": page(nodes, more, cursor)}}}}


def read_steps(nodes=(), when=DUE - 900):
    return [http({}, when=when), http(graph(list(nodes)), when=when)]


def response(text, cid=17, when=DUE - 800):
    return {"id": cid, "created_at": stamp(when), "user": {"login": LOGIN, "id": AUTHOR}, "body": text}


FAKE = r'''#!SHEBANG
import json, os, pathlib, sys, time
root = pathlib.Path(os.environ["HOME"])
args = sys.argv[1:]
with (root / "calls").open("a") as out:
    out.write(json.dumps({"tool": pathlib.Path(sys.argv[0]).name, "args": args,
                          "env": sorted(os.environ), "stdin": sys.stdin.read()}) + "\n")
if any("contents/results/followup/run/draw_record.py?ref=" in a for a in args):
    data = pathlib.Path(MODULE).read_bytes()
    if (root / "different-module").exists():
        data += b"different"
    sys.stdout.buffer.write(b"HTTP/2.0 200 Synthetic\r\n\r\n" + data)
    sys.exit(0)
queue = json.loads((root / "queue.json").read_text())
if not queue:
    sys.exit(92)
step = queue.pop(0)
(root / "queue.json").write_text(json.dumps(queue))
if step.get("contains") and step["contains"] not in " ".join(args):
    sys.exit(93)
time.sleep(step.get("delay", 0))
sys.stdout.buffer.write(bytes.fromhex(step["output"]))
sys.exit(step.get("exit", 0))
'''


class Harness:
    def __init__(self, dr, root, monkeypatch, capsys):
        self.dr, self.root, self.capsys = dr, root, capsys
        self.state, self.bin = root / "state", root / "bin"
        self.bin.mkdir()
        for tool in ("gh", "curl"):
            target = self.bin / tool
            target.write_text(FAKE.replace("SHEBANG", sys.executable).replace("MODULE", repr(str(MODULE))))
            target.chmod(0o755)
        monkeypatch.setenv("PATH", str(self.bin))
        monkeypatch.setenv("HOME", str(root))
        for name in list(os.environ):
            if name.startswith("GH_"):
                monkeypatch.delenv(name)
        monkeypatch.setenv("GH_DRAW_FIXTURE", "synthetic")
        monkeypatch.setenv("DROP_SYNTHETIC", SENTINEL)
        monkeypatch.setattr(dr, "machine_time", lambda: DUE - 900)
        self.queue([])
        self.err = ""

    def queue(self, steps):
        (self.root / "queue.json").write_text(json.dumps(steps))

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def save(self, kind, data):
        if kind == "read" and isinstance(data, list):
            data = {"github_time": DUE - 900, "comments": data}
        return self.dr.append_record(self.state, kind, data)

    def init(self):
        self.save("declaration", declaration())

    def seed(self, comments=None):
        self.init()
        self.save("read", [comment()] if comments is None else comments)
        self.save("evidence", evidence())

    def run(self, *args, code=0, clock=None, sleep=lambda _: None, gh_timeout=60):
        if args[0] == "beacon" and "--round" in args and "--out" not in args:
            args = (*args, "--out", self.root / "beacon-output.json")
        self.capsys.readouterr()
        result = self.dr.main([args[0], "--state", str(self.state), *map(str, args[1:])],
                              clock=clock or self.dr.machine_time, sleep=sleep, gh_timeout=gh_timeout)
        out = self.capsys.readouterr()
        self.err = out.err
        assert result == code, (result, out.out, out.err)
        assert SENTINEL not in out.out + out.err
        return out.out

    def file(self, text):
        target = self.root / "post.txt"
        target.write_text(text)
        return target

    def snapshot(self):
        folder = self.state / "records"
        return {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in folder.iterdir()} if folder.exists() else {}

    def data(self, kind):
        return [r["data"] for r in self.dr.load_records(self.state) if r["kind"] == kind]


@pytest.fixture
def h(dr, tmp_path, monkeypatch, capsys):
    return Harness(dr, tmp_path, monkeypatch, capsys)


@pytest.mark.parametrize("line", ["round 5", "round 5\r", "round 5\nprose ignored here"])
def test_t1_exact(dr, line):
    p = dr.parse_body("Follow-up draw: first post\n" + line + "\nrun_commit " + COMMIT)
    assert p["round"] == 5 and p["run_commit"] == COMMIT and not p["reason"]


@pytest.mark.parametrize("line", [" round 5", "round 5 ", "Round 5", "round 05", "round +5", "round 5.0",
                                  "round ٥", "> round 5", "round 5\rx", "round 0"])
def test_t1_invalid_round(dr, line):
    assert dr.parse_body("Follow-up draw: first post\n" + line + "\nrun_commit " + COMMIT)["reason"]


@pytest.mark.parametrize("commit", ["a" * 39, "a" * 41, "g" * 40])
def test_t1_invalid_commit(dr, commit):
    assert dr.parse_body(body(commit=commit))["reason"]


def test_uppercase_and_duplicate_names(dr):
    assert dr.parse_body(body(commit=COMMIT.upper()))["run_commit"] == COMMIT
    for tail in ("round 1001", "round 1002", "run_commit " + COMMIT, "x a\nx a", "x a\nx b"):
        assert dr.parse_body(body(tail=tail))["reason"] == "repeated value name"
    assert dr.parse_body(body().replace("first post\n", "first post \n"))["kind"] is None
    assert dr.parse_body(body(tail="0_name value"))["values"]["0_name"] == "value"
    with pytest.raises(dr.Refused):
        dr.round_due(0)


@pytest.mark.parametrize("reverse", [False, True])
def test_t2_created_revision(dr, reverse):
    edits = [{"editedAt": stamp(DUE - 800), "deletedAt": None, "diff": body(n=N + 1)},
             {"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}]
    c = comment(text="changed", lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                edits=edits[::-1] if reverse else edits)
    assert dr.candidates(records([c]))[0]["body"] == body()


@pytest.mark.parametrize("variant", ["two", "none", "deleted", "absent"])
def test_creation_revision_ambiguous_or_deleted(dr, variant):
    edit = {"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}
    edits = [edit]
    if variant == "two":
        edits.append({**edit, "diff": "other"})
    elif variant == "none":
        edits = [{**edit, "editedAt": stamp(DUE - 899)}]
    elif variant == "deleted":
        edits = [{**edit, "deletedAt": stamp(DUE - 800)}]
    else:
        edits = []
    c = comment(lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True, edits=edits)
    assert dr.candidates(records([c]))[0]["body"] is None


def test_author_id_first_sight_and_union(dr):
    c = dr.normalize_comment(graph_comment(author={"login": "renamed", "databaseId": AUTHOR}))
    assert c["author"] == AUTHOR
    cs = [c, comment(2, author=72), comment(3, author=None), comment(4, text="ordinary prose")]
    rs = records(cs)
    rs += [rec("read", {"github_time": DUE, "comments": [comment(4), comment(2)]}, 4),
           rec("read", {"github_time": DUE, "comments": []}, 5)]
    assert [c["id"] for c in dr.candidates(rs)] == [1, 4]
    assert dr.candidates(rs)[1]["body"] == "ordinary prose"
    assert dr.evaluate_records(rs)["counted"]["id"] == 1
    assert dr.normalize_comment(graph_comment(author=None))["author"] is None
    rs = [rec("declaration", declaration(), 1), rec("post", comment(), 2),
          rec("read", {"github_time": DUE, "comments": [comment(text="edited")]}, 3)]
    assert dr.candidates(rs)[0]["body"] == body()


def test_t3_integer_order(dr):
    rs = records([comment(1000000000), comment(999999999)])
    assert [c["id"] for c in dr.candidates(rs)] == [999999999, 1000000000]
    assert dr.normalize_comment(graph_comment(1000000000))["id"] == 1000000000


@pytest.mark.parametrize("change,reason", [({}, "passed"),
    ({"content": {"status": 200, "sha256": "0" * 64, "length": 22}}, "declaration differs"),
    ({"content": {"status": 200, "sha256": declaration()["sha256"], "length": 999}}, "declaration differs"),
    ({"pulls": []}, "no qualifying pull request")])
def test_t4_commitment(dr, change, reason):
    result = dr.commitment_test(comment(), evidence(**change), declaration())
    assert result["reason"] == reason and result["passed"] == (reason == "passed")


@pytest.mark.parametrize("field,value", [("base", "branch"), ("compare", "behind"),
                                         ("compare", "diverged"), ("merged_at", None), ("merge_commit_sha", None)])
def test_t4_nonqualifying_pull(dr, field, value):
    ev = evidence()
    ev["pulls"][0][field] = value
    assert not dr.commitment_test(comment(), ev, declaration())["passed"]


@pytest.mark.parametrize("offset,passed", [(0, False), (-1, True)])
def test_t4_merge_second(dr, offset, passed):
    assert dr.commitment_test(comment(), evidence(DUE - 900 + offset), declaration())["passed"] is passed


def test_evidence_decidability(dr):
    c = comment()
    assert dr.commitment_test(c, evidence(github_time=DUE - 1000), declaration())["passed"]
    assert dr.commitment_test(c, evidence(pulls=[], github_time=DUE - 1000), declaration()) is None
    assert dr.commitment_test(c, evidence(pulls=[], github_time=DUE - 900), declaration())["passed"] is False
    ev = evidence(github_time=DUE - 1000, content={"status": 200, "sha256": "x", "length": 0})
    assert dr.commitment_test(c, ev, declaration())["reason"] == "declaration differs"
    assert dr.commitment_test(c, evidence(merged=DUE - 800, github_time=DUE - 1000), declaration()) is None


def test_counterexample_frozen_per_comment_and_recheck(h):
    h.init()
    h.save("read", [comment()])
    h.queue(evidence_steps(pulls=[]))
    assert h.run("evaluate", code=10) == "none\n"
    assert COMMIT != declaration()["declaration_commit"]
    first = h.data("test")[0]
    before = h.snapshot()
    h.save("read", {"github_time": DUE - 700, "comments": [comment(), comment(2, when=DUE - 700)]})
    h.queue(evidence_steps(when=DUE - 700, merged=DUE - 800))
    assert h.run("evaluate", clock=lambda: DUE - 700).startswith("counted 2 ")
    assert h.data("test")[0] == first and first["passed"] is False
    assert h.data("test")[1]["passed"] is True
    assert all(h.snapshot()[k] == v for k, v in before.items())
    assert h.run("evaluate").startswith("counted 2 ")
    recheck = evidence_steps(when=DUE - 699, merged=DUE - 800)
    recheck[1] = http({"default_branch": "other"}, when=DUE - 699)
    h.queue([*recheck, *recheck])
    assert "undecided 2" in h.run("evaluate", "--recheck", clock=lambda: DUE - 699)
    assert len(h.data("recheck")) == 2
    assert h.data("test")[0] == first
    assert h.run("evaluate").startswith("counted 2 ")


def test_early_negative_is_refetched_rechecks_never_decide(h):
    h.seed()
    h.save("evidence", evidence(pulls=[], github_time=DUE - 1000))
    # Earlier positive wins; rechecks are never an evidence source.
    h.save("recheck", evidence(pulls=[]))
    assert h.run("evaluate").startswith("counted 1 ")
    assert h.data("test")[0]["passed"] is True


@pytest.mark.parametrize("status,message,refusal", [(404, "missing", False),
    (422, "No commit found for SHA synthetic", False), (422, "No commit found for reference", True),
    (422, "other failure", True), (500, SENTINEL, True), (403, "rate limit", True), (429, SENTINEL, True)])
def test_t4_http_failures(h, status, message, refusal):
    h.init()
    h.save("read", [comment()])
    before = h.snapshot()
    h.queue([*evidence_steps()[:2], http({"message": message}, status=status, exit=1)])
    h.run("evaluate", code=2 if refusal else 10)
    assert (h.snapshot() == before) is refusal


def test_t4_page_limit_and_earliest(h):
    ev = evidence()
    ev["pulls"].append({**ev["pulls"][0], "number": 72, "merged_at": stamp(MERGE)})
    assert h.dr.commitment_test(comment(), ev, declaration())["pull_request"] == 72
    h.init()
    h.save("read", [comment()])
    h.queue([*evidence_steps()[:3], http([{"number": n, "base": {"ref": "other"}, "merged_at": None, "merge_commit_sha": None} for n in range(100)]), evidence_steps()[4]])
    h.run("evaluate", code=2)
    assert h.data("evidence") == []


@pytest.mark.parametrize("offset,code", [(-600, 0), (-599, 10)])
def test_t5_deadline(dr, offset, code):
    assert dr.evaluate_records(records([comment(when=DUE + offset)]))["code"] == code


def test_t5_duplicates_void_and_unrecoverable(dr):
    rs = records([comment(), comment(2, when=DUE - 899), comment(3, when=DUE - 898, text=body(n=N + 1)),
                  comment(4, when=DUE - 901, lastEditedAt=stamp(DUE - 800))])
    assert dr.evaluate_records(rs)["counted"]["id"] == 1
    assert dr.publish_list(rs)["first_posts"][1]["counted"] is True
    rs.append(rec("void", {"round": N}, 4))
    assert dr.evaluate_records(rs)["counted"]["id"] == 3
    assert dr.evaluate_records(records([comment(lastEditedAt=stamp(DUE - 800))]))["code"] == 10


@pytest.mark.parametrize("ahead,action", [(601, "kept"), (600, "new"), (3600, "kept"), (3601, "refused")])
def test_t6_saved_round(dr, ahead, action):
    if action == "refused":
        with pytest.raises(dr.Refused):
            dr.choose_round(DUE - ahead, N)
    else:
        n, chosen = dr.choose_round(DUE - ahead, N)
        assert chosen == action
        if action == "new":
            assert dr.round_due(n) >= DUE - ahead + 900 > dr.round_due(n - 1)


@pytest.mark.parametrize("skew", [-61, -60, 60, 61])
def test_t7_clock_through_main(h, skew):
    h.init()
    h.queue([http({})])
    out = h.run("now", code=2 if abs(skew) > 60 else 0, clock=lambda: DUE - 900 + skew)
    if abs(skew) <= 60:
        assert out == f"github {DUE - 900} skew {skew}\n"


def test_later_clock_and_choose(h):
    assert h.dr.effective_time(100, 220) == 220
    assert h.dr.effective_time(220, 100) == 220
    h.init()
    h.queue([http({})])
    h.run("choose-round", clock=lambda: DUE - 840)
    n = h.data("round")[-1]["round"]
    assert h.dr.round_due(n) >= DUE + 60 > h.dr.round_due(n - 1)


@pytest.mark.parametrize("variant", ["pass", "unmerged", "changed", "empty"])
def test_t16_init(h, variant):
    if variant == "changed":
        h.init()
    before = h.snapshot()
    h.queue([http(pr(merged=variant != "unmerged"), exit=1),
             http(b"" if variant == "empty" else b"changed" if variant == "changed" else b"synthetic declaration\n")])
    h.run("init", code=0 if variant == "pass" else 2)
    if variant == "pass":
        assert h.data("declaration")[0] == declaration()
    else:
        assert h.snapshot() == before
    assert all("-i" in c["args"] for c in h.calls())
    if variant == "unmerged":
        assert len(h.calls()) == 1


def test_t15_read_150_edits_and_pages(h):
    h.init()
    edit = {"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}
    c = graph_comment(1000000000, lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                      userContentEdits=page([edit] * 100, True, "edit-next"))
    h.queue([http({}), http(graph([c], True, "issue-next")),
             http({"data": {"node": {"userContentEdits": page([edit] * 50)}}}),
             http(graph([graph_comment(999999999)]))])
    assert h.run("read") == "read 2\n"
    read = h.data("read")[0]
    assert read["github_time"] == DUE - 900 and len(read["comments"][0]["edits"]) == 150
    calls = " ".join(" ".join(c["args"]) for c in h.calls())
    assert "databaseId" in calls and "... on User" in calls and "node(id:" in calls
    assert "edit-next" in calls and "issue-next" in calls


@pytest.mark.parametrize("variant", ["502", "errors", "cursor", "missing"])
def test_t15_read_refusals_atomic(h, variant):
    h.init()
    before = h.snapshot()
    if variant == "502":
        steps = [http(graph([graph_comment()], True, "next")), http({}, status=502)]
    elif variant == "errors":
        steps = [http({"errors": [{"message": SENTINEL}], **graph([])})]
    elif variant == "cursor":
        steps = [http(graph([], True, None))]
    else:
        steps = [http({"data": {"repository": {"issue": None}}})]
    h.queue([http({}), *steps])
    h.run("read", code=2)
    assert h.snapshot() == before


def first_steps(nodes=(), when=DUE - 900, created=DUE - 899, outcome=None):
    return [http({"id": AUTHOR, "login": "renamed"}), *read_steps(nodes, when),
            *evidence_steps(when), http({}, when=when),
            http(response(body(), when=created), status=201) if outcome is None else outcome,
            *read_steps([graph_comment(17, createdAt=stamp(created))], when)]


def test_t8_first_posts_itself_and_precheck_decides(h):
    h.init()
    h.save("round", {"round": N})
    h.queue(first_steps())
    assert h.run("post", "first", h.file(body())) == f"posted 17 {stamp(DUE - 899)}\n"
    assert h.data("post")[0]["id"] == 17 and h.data("test")[0]["passed"] is True
    assert h.run("evaluate").startswith("counted 17 ")
    calls = h.calls()
    sent = next(i for i, c in enumerate(calls) if "POST" in c["args"])
    assert any("graphql" in c["args"] for c in calls[:sent])
    assert h.data("evidence")[0]["github_time"] < DUE - 899


def test_first_refuses_counted_then_posts_after_void(h):
    h.seed()
    h.save("round", {"round": N})
    h.queue(first_steps([graph_comment()]))
    h.run("post", "first", h.file(body()), code=2)
    assert not any("POST" in c["args"] for c in h.calls())
    h.save("beacon", beacon())
    h.save("void", {"round": N, "receipt_sha256": "0" * 64})
    next_round = N + 301
    h.save("round", {"round": next_round})
    text = body(n=next_round)
    steps = first_steps([graph_comment()], when=DUE + 1, created=DUE + 2)
    steps[-3] = http(response(text, when=DUE + 2), status=201)
    steps[-1] = http(graph([graph_comment(17, createdAt=stamp(DUE + 2), body=text)]), when=DUE + 1)
    h.queue(steps)
    assert h.run("post", "first", h.file(text), clock=lambda: DUE + 1).startswith("posted 17 ")
    assert f"round {next_round} " in h.run("evaluate")


def test_first_blocked_only_when_none(h):
    h.init()
    h.queue([http({"id": AUTHOR}), *read_steps([graph_comment(lastEditedAt=stamp(DUE - 800))])])
    assert h.run("post", "first", h.file(body()), code=13) == "blocked 1\n"
    assert h.run("evaluate", code=10) == "none\n"


@pytest.mark.parametrize("variant", ["wrong-id", "line", "stale", "margin", "merge-age"])
def test_t8_post_refusals(h, variant):
    h.init()
    h.save("round", {"round": N})
    text = "wrong" if variant == "line" else body()
    steps = first_steps()
    if variant == "wrong-id":
        steps[0] = http({"id": AUTHOR + 1, "login": LOGIN})
    if variant == "stale":
        steps[-4] = http({}, when=DUE - 839)
    if variant == "margin":
        steps = first_steps(when=DUE - 600)
    if variant == "merge-age":
        steps[3:9] = evidence_steps(merged=DUE - 959)
    h.queue(steps)
    clocks = iter([DUE - 900, DUE - 900, DUE - 839]) if variant == "stale" else None
    h.run("post", "first", h.file(text), code=2,
          clock=(lambda: next(clocks)) if clocks else lambda: DUE - (600 if variant == "margin" else 900))
    assert not any("POST" in c["args"] for c in h.calls())


def test_t8_readback_failure_still_posted(h):
    h.init()
    h.save("round", {"round": N})
    steps = first_steps()
    steps[-1] = http({}, status=502)
    h.queue(steps)
    assert h.run("post", "first", h.file(body())).startswith("posted 17 ")
    assert "read-back failed" in h.err and len(h.data("post")) == 1


@pytest.mark.parametrize("kind", ["first", "second"])
@pytest.mark.parametrize("outcome", ["timeout", "500", "no-id", "no-status"])
def test_unknown_post_and_first_timing(h, kind, outcome):
    h.seed([] if kind == "first" else None)
    h.save("round", {"round": N})
    text = body(kind)
    bad = {"output": "", "delay": 1} if outcome == "timeout" else (
        http({}, status=500) if outcome == "500" else http(response(text, cid="17", when=DUE - 899), status=201)
        if outcome == "no-id" else {"output": b"no status".hex(), "exit": 4})
    if kind == "first":
        h.queue(first_steps(outcome=bad))
    else:
        h.queue([http({"id": AUTHOR}), http({}), bad])
    h.run("post", kind, h.file(text), code=2, gh_timeout=.5 if outcome == "timeout" else 60)
    assert len(h.data("post-unknown")) == 1 and not h.data("post")
    if kind == "first":
        h.queue(first_steps(when=DUE - 781))
        h.run("post", kind, h.file(text), code=2, clock=lambda: DUE - 781)
        assert "post outcome unknown" in h.err
        h.queue(first_steps(when=DUE - 780, created=DUE - 779))
        assert h.run("post", kind, h.file(text), clock=lambda: DUE - 780).startswith("posted 17 ")
    else:
        h.queue([http({"id": AUTHOR}), http({}), http(response(text), status=201), *read_steps()])
        assert h.run("post", kind, h.file(text)).startswith("posted 17 ")


def test_unknown_new_comment_does_not_gate(h):
    h.seed()
    h.save("post-unknown", {"kind": "second", "github_time": DUE - 900, "known_ids": []})
    h.save("read", {"github_time": DUE - 840, "comments": [comment(9, text=body("second"))]})
    h.queue([http({"id": AUTHOR}), http({}), http(response(body("second")), status=201), *read_steps()])
    assert h.run("post", "second", h.file(body("second"))).startswith("posted 17 ")


def beacon(n=N):
    sig = "ab" * 48
    return {"round": n, "signature": sig, "randomness": hashlib.sha256(bytes.fromhex(sig)).hexdigest()}


@pytest.mark.parametrize("variant", ["accepted", "down", "disagree", "extra", "round", "hash", "upper", "json", "odd", "bool"])
def test_t9_beacon(h, variant):
    h.seed()
    left, right = beacon(), beacon()
    if variant == "disagree":
        right["signature"] = "cd" * 48
    elif variant == "extra":
        left = right = {**left, "extra": SENTINEL}
    elif variant in ("round", "hash", "upper", "odd", "bool"):
        key, value = {"round": ("round", N + 1), "hash": ("randomness", "0" * 64),
                      "upper": ("signature", left["signature"].upper()), "odd": ("signature", "abc"),
                      "bool": ("round", True)}[variant]
        left = right = {**left, key: value}
    elif variant == "json":
        left = right = b"{"
    h.queue([http({}, when=DUE), relay(left, 7 if variant == "down" else 0), relay(right), http({}, when=DUE)])
    out = h.run("beacon", "--round", N, code=0 if variant == "accepted" else 10, clock=lambda: DUE)
    assert out.startswith("accepted" if variant == "accepted" else "not-accepted")
    attempt = h.data("beacon-attempt")[-1]
    assert attempt["github_after"] == DUE and len(attempt["raw_bodies"]) == 2
    if variant == "accepted":
        assert h.data("beacon") == [beacon()]
        p = next((h.state / "records").glob("*-beacon.json"))
        assert p.read_bytes() == h.dr.canonical(beacon())
    else:
        assert not h.data("beacon")


@pytest.mark.parametrize("offset,code", [(86399, 0), (86400, 13)])
def test_t9_after_read_cutoff(h, offset, code):
    h.seed()
    h.queue([http({}, when=DUE), relay(beacon()), relay(beacon()), http({}, when=DUE + offset)])
    times = iter([DUE, DUE + offset])
    h.run("beacon", "--round", N, code=code, clock=lambda: next(times))
    assert h.data("beacon-attempt")[-1]["outcome"] == ("accepted" if code == 0 else "cutoff")


def test_accepted_no_reads_at_cutoff_and_stopped_first(h):
    h.seed()
    h.save("beacon", beacon())
    assert h.run("beacon", "--round", N, clock=lambda: DUE + 86400) == f"accepted round {N}\n"
    assert not h.calls()
    h.save("post", comment(2, when=DUE, text=body("stop")))
    assert h.run("evaluate", code=14) == "stopped 2\n"
    h.run("beacon", "--round", N, code=2)
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64, code=2)
    h.run("post", "first", h.file(body()), code=2)
    assert not h.calls()


@pytest.mark.parametrize("wrong", [False, True])
def test_t9_before_due_or_wrong_round(h, wrong):
    h.seed()
    h.queue([http({}, when=DUE - 1)])
    h.run("beacon", "--round", N + int(wrong), code=2, clock=lambda: DUE - 1)
    assert not any(c["tool"] == "curl" for c in h.calls())


@pytest.mark.parametrize("variant", ["no-count", "early", "build-early", "cutoff-early", "accepted", "not-newest-cutoff", "no-beacon", "no-hash", "beacon", "build"])
def test_stop_guards(h, variant):
    h.seed([] if variant == "no-count" else None)
    reason = "build" if variant in ("build", "build-early", "no-beacon", "no-hash") else "beacon"
    t = DUE - 1 if variant in ("early", "build-early") else DUE + 86399 if variant == "cutoff-early" else DUE + 86400
    h.save("beacon-attempt", {"round": N, "outcome": "cutoff"})
    if variant in ("accepted", "build", "build-early", "no-hash"):
        h.save("beacon", beacon())
    if variant == "not-newest-cutoff":
        h.save("beacon-attempt", {"round": N, "outcome": "not-accepted"})
    text = body("stop")
    h.queue([http({"id": AUTHOR}), http({}, when=t), http(response(text, when=t), status=201), *read_steps(when=t)])
    args = ["--reason", reason]
    if variant in ("build", "build-early", "no-beacon"):
        args += ["--failure-sha256", "f" * 64]
    success = variant in ("beacon", "build")
    h.run("post", "stop", h.file(text), *args, code=0 if success else 2, clock=lambda: t)
    if success:
        assert h.run("evaluate", code=14).startswith("stopped 17")
        if reason == "build":
            assert h.data("post")[0]["failure_sha256"] == "f" * 64
    else:
        assert not any("POST" in c["args"] for c in h.calls())


def test_early_stop_marker(h):
    h.seed([comment(), comment(2, when=DUE - 1, text=body("stop"))])
    assert h.run("evaluate").startswith("counted 1 ")
    assert json.loads(h.run("publish-list"))["markers"][0]["id"] == 2


@pytest.mark.parametrize("command", ["first", "evaluate", "beacon", "match", "record-void", "second", "tasks", "stop", "publish-list", "publish-records"])
def test_module_bytes_enforced(h, command):
    h.seed([] if command == "first" else None)
    h.save("round", {"round": N})
    (h.root / "different-module").write_text("synthetic")
    if command == "first":
        h.queue([http({"id": AUTHOR}), *read_steps()])
        args = ["post", "first", h.file(body())]
    elif command in ("second", "tasks", "stop"):
        args = ["post", command, h.file(body(command))]
        if command == "stop":
            args += ["--reason", "beacon"]
    else:
        args = [command]
        if command in ("beacon", "record-void"):
            args += ["--round", N]
        if command == "record-void":
            args += ["--receipt-sha256", "0" * 64]
        if command == "match":
            args += ["second", h.file(body("second"))]
        if command == "publish-records":
            args += [h.root / "export"]
    h.run(*args, code=2)
    assert "reading module differs" in h.err


@pytest.mark.parametrize("kind", ["second", "tasks"])
def test_t10_exact_match(h, kind):
    expected = body(kind, tail="receipt abc\n0_name value\n")
    cs = [comment(), comment(2, when=DUE - 901, text=expected), comment(3, author=72, text=expected),
          comment(4, when=DUE - 899, text=expected.replace(f"round {N}", f"round {N+1}")),
          comment(5, when=DUE - 898, text=expected.replace("receipt abc\n", "")),
          comment(6, when=DUE - 897, text=expected + "extra value\n"),
          comment(7, when=DUE - 896, text=expected + "receipt abc\n"),
          comment(8, when=DUE - 895, text=expected + "\nprose with several words\n<!-- hidden marker -->"),
          comment(9, when=DUE - 894, text=expected)]
    h.seed(cs)
    assert h.run("match", kind, h.file(expected)) == "differs 5\ndiffers 6\ndiffers 7\nmatched 8\n"
    entries = json.loads(h.run("publish-list"))["markers"]
    assert [e["match"] for e in entries if e["id"] >= 5] == ["differs", "differs", "differs", "matched", "matched"]
    h.run("match", kind, h.file(expected + "receipt abc\n"), code=2)


def test_t10_match_none_and_file_kind(h):
    h.seed()
    assert h.run("match", "second", h.file(body("second")), code=10) == "none\n"
    h.run("match", "second", h.file(body("tasks")), code=2)
    h.run("match", "second", h.file(body("second", n=N + 1)), code=2)


def test_t11_list_reasons_order_identity_and_unrecoverable(h):
    edits = [{"editedAt": stamp(DUE - 799), "deletedAt": stamp(DUE - 798), "diff": SENTINEL}]
    cs = [comment(1, when=MERGE, text=body(tail="round 1002")), comment(2, when=MERGE),
          comment(3, when=DUE - 1100, text=body(n=N - 1)), comment(4, when=DUE - 1000, text=body(commit=OTHER)),
          comment(5, text=body(tail="\n".join(n + " frozen" for n in h.dr.IDENTITY_FIELDS))),
          comment(6, when=DUE - 899), comment(7, when=DUE - 898, text=body(n=N + 1)),
          comment(8, when=DUE - 500, text=body(n=N + 2)),
          comment(9, when=DUE - 799, includesCreatedEdit=True, lastEditedAt=stamp(DUE - 798), edits=edits),
          comment(10, text="Follow-up draw: other marker")]
    h.seed(cs)
    h.save("evidence", {**evidence(content={"status": 404}), "commit": OTHER})
    h.save("void", {"round": N - 1})
    out = h.run("publish-list")
    data = json.loads(out)
    assert out.encode() == h.dr.canonical(data)
    rows = data["first_posts"]
    assert [r["reason"] for r in rows] == ["not after the merge", "not after the merge",
        "void round", "failed: not found", "counted", "same round as 5", "after the counted post", "unrecoverable", "late"]
    assert rows[4]["values"] == {n: "frozen" for n in h.dr.IDENTITY_FIELDS}
    assert rows[-2]["deletedAt"] == stamp(DUE - 798) and rows[-2]["first_seen"] == DUE - 900
    assert data["markers"][0]["first_line"] == "Follow-up draw: other marker"
    assert h.run("evaluate").startswith("counted 5 ")


def test_later_fetch_failure_untested_only_in_list(h):
    h.seed([comment(), comment(2, when=DUE - 899, text=body(commit=OTHER))])
    h.queue([*evidence_steps()[:2], http({}, status=502)])
    assert h.run("evaluate").startswith("counted 1 ")
    # No attempt on the later commit until the list asks for it.
    assert len(h.calls()) == 1
    out = json.loads(h.run("publish-list"))
    assert out["first_posts"][1]["reason"].startswith("untested: ")
    assert h.data("test")[0]["id"] == 1


def test_t12_records_partial_names_and_no_replace(h, monkeypatch):
    h.init()
    folder = h.state / "records"
    (folder / "000099-round.json.partial").write_bytes(b"unfinished")
    (folder / ".DS_Store").write_bytes(b"ignored")
    (folder / "other").write_bytes(b"ignored")
    path = h.save("round", {"round": N})
    assert path.name == "000100-round.json" and path.with_name(path.name + ".partial").exists()
    before = h.snapshot()
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 100, "round", {})
    assert h.snapshot() == before
    assert len(h.dr.load_records(h.state)) == 2
    for number, kind in [(0, "round"), (101, "bad_kind")]:
        with pytest.raises(h.dr.Refused):
            h.dr.write_record(h.state, number, kind, {})

    def race(source, target):
        target.write_bytes(b"winner")
        raise FileExistsError("synthetic")

    monkeypatch.setattr(h.dr.os, "link", race)
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 101, "round", {})
    assert (folder / "000101-round.json").read_bytes() == b"winner"


def test_t12_flush_and_folder_sync(h, monkeypatch):
    calls = []
    original = h.dr.os.fsync
    monkeypatch.setattr(h.dr.os, "fsync", lambda fd: (calls.append(fd), original(fd))[1])
    h.init()
    assert len(calls) == 2


def test_commands_wait_for_folder_lock(h):
    h.init()
    folder = h.state / "records"
    fd = os.open(folder, os.O_RDONLY)
    fcntl.flock(fd, fcntl.LOCK_EX)
    argv = [sys.executable, "-I", str(MODULE), "evaluate", "--state", str(h.state)]
    p = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        time.sleep(.15)
        assert p.poll() is None
    finally:
        os.close(fd)
    out, err = p.communicate(timeout=5)
    assert p.returncode == 10 and out == b"none\n" and not err


def test_record_void_requires_beacon_and_preserves_records(h):
    h.seed()
    before = h.snapshot()
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64, code=2)
    h.save("beacon", beacon())
    h.run("record-void", "--round", N + 1, "--receipt-sha256", "0" * 64, code=2)
    h.run("record-void", "--round", N, "--receipt-sha256", "bad", code=2)
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64)
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64, code=2)
    assert all(h.snapshot()[k] == v for k, v in before.items())
    assert h.run("evaluate", code=10) == "none\n"


@pytest.mark.parametrize("variant", ["pass", "down", "different"])
def test_rehearsal(h, variant):
    h.init()
    fixture = h.root / "fixture.json"
    fixture.write_bytes(h.dr.canonical(beacon()))
    live = beacon() if variant != "different" else {**beacon(), "signature": "cd" * 48,
        "randomness": hashlib.sha256(bytes.fromhex("cd" * 48)).hexdigest()}
    h.queue([step for _ in range(3) for step in (http({}, when=DUE), relay(live, 7 if variant == "down" else 0),
                                                relay(live), http({}, when=DUE))])
    sleeps = []
    out = h.run("beacon", "--rehearsal", "--fixture", fixture, code=0 if variant == "pass" else 10,
                clock=lambda: DUE, sleep=sleeps.append)
    assert out.startswith("rehearsal-beacon " + ("pass" if variant == "pass" else "fail"))
    assert not h.data("beacon")
    assert h.data("rehearsal-beacon")[-1]["attempt_count"] == (1 if variant == "pass" else 3)
    assert sleeps == ([] if variant == "pass" else [30, 30])


def test_known_answer_canonical_and_default(h):
    path = MODULE.with_name("known-answer-round.json")
    raw = path.read_bytes()
    value = json.loads(raw)
    assert raw == h.dr.canonical(value) and set(value) == {"round", "randomness", "signature"}
    assert value["round"] == 33965389
    assert hashlib.sha256(raw).hexdigest() == "90993553c28c330681cd4aba6307caa35b5d57be548ec9ccb4c0ed96e41940fa"
    assert h.dr.parser().parse_args(["beacon", "--state", "synthetic", "--rehearsal"]).fixture == str(path)
    h.init()
    h.queue([http({}, when=DUE), relay(value), relay(value), http({}, when=DUE)])
    assert h.run("beacon", "--rehearsal", clock=lambda: DUE) == "rehearsal-beacon pass\n"


def test_publish_records_private_body_and_replay(h):
    h.seed([comment(), comment(2, author=72, text=SENTINEL),
            comment(3, when=DUE - 899, lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                    edits=[{"editedAt": stamp(DUE - 899), "deletedAt": stamp(DUE), "diff": "created"}])])
    h.save("round", {"round": N})
    h.save("post-unknown", {"kind": "tasks", "github_time": DUE, "known_ids": []})
    h.save("recheck", {"id": 1, "passed": False})
    expected = h.run("evaluate")
    out = h.root / "export"
    h.run("publish-records", out)
    assert all(SENTINEL.encode() not in p.read_bytes() for p in out.rglob("*") if p.is_file())
    read = h.dr.newest(h.dr.load_records(out), "read")
    assert read["github_time"] == DUE - 900 and read["other_comments"] == 1
    assert read["comments"][0]["author"] == AUTHOR and read["comments"][1]["includesCreatedEdit"]
    assert {r["kind"] for r in h.dr.load_records(out)} >= {"declaration", "read", "round", "post-unknown", "evidence", "test", "recheck"}
    original = h.state
    h.state = out
    assert h.run("evaluate") == expected
    h.state = original
    h.run("publish-records", out, code=2)


@pytest.mark.parametrize("command,args", [("now", []), ("read", []), ("evaluate", []), ("choose-round", []),
    ("post", ["first", "missing"]), ("beacon", ["--round", N]), ("match", ["second", "missing"]),
    ("record-void", ["--round", N, "--receipt-sha256", "0" * 64]), ("publish-list", []), ("publish-records", ["missing"])])
def test_t14_before_init(h, command, args):
    h.run(command, *args, code=2)
    assert not h.calls()


@pytest.mark.parametrize("variant", ["empty", "missing", "exception", "timeout"])
def test_t16_top_level_refusals(h, monkeypatch, variant):
    h.init()
    if variant == "missing":
        monkeypatch.setenv("PATH", "")
    elif variant == "exception":
        monkeypatch.setattr(h.dr, "execute", lambda _: 1 / 0)
    else:
        h.queue([{"output": "", "exit": 4, "delay": .2 if variant == "timeout" else 0}])
    h.run("now", code=2, gh_timeout=.05 if variant == "timeout" else 60)
    assert h.err.startswith("refused: ") and SENTINEL not in h.err


def test_tools_fixed_environment_stdin_and_http(h, monkeypatch):
    original = h.dr.subprocess.run

    def checked(argv, **kwargs):
        assert kwargs["env"] == {k: v for k, v in os.environ.items()
                                  if k in ("PATH", "HOME")}
        assert kwargs["stdin"] == subprocess.DEVNULL
        return original(argv, **kwargs)

    monkeypatch.setattr(h.dr.subprocess, "run", checked)
    h.init()
    h.queue([http({}, lf=True)])
    h.run("now")
    call = h.calls()[0]
    assert call["stdin"] == "" and "DROP_SYNTHETIC" not in call["env"]
    assert set(call["env"]) <= {"PATH", "HOME", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"}
    raw = b"HTTP/2 200 OK\r\n\r\nHTTP/body\n\ntext"
    assert h.dr.parse_http(raw)["body"] == b"HTTP/body\n\ntext"


def test_subprocess_each_command_with_wide_margins(h):
    h.init()
    # One external invocation per command; timed invocations use the current second.
    t = int(time.time())
    commands = [("init", [], [http(pr()), http(b"synthetic declaration\n")], 0),
                ("now", [], [http({}, when=t)], 0), ("read", [], read_steps(when=t), 0),
                ("evaluate", [], [], 10), ("choose-round", [], [http({}, when=t)], 0),
                ("post", ["second", str(h.file(body("second")))], [], 2),
                ("beacon", ["--round", str(N)], [], 2), ("match", ["second", "missing"], [], 2),
                ("record-void", ["--round", str(N), "--receipt-sha256", "0"*64], [], 2),
                ("publish-list", [], [], 0), ("publish-records", [str(h.root / "public")], [], 0)]
    for cmd, args, steps, code in commands:
        h.queue(steps)
        result = subprocess.run([sys.executable, "-I", str(MODULE), cmd, "--state", str(h.state), *args],
                                capture_output=True, timeout=10)
        assert result.returncode == code, (cmd, result.stdout, result.stderr)
        assert SENTINEL.encode() not in result.stdout + result.stderr


def test_negative_before_comment_refetches_and_recheck_alone_never_decides(h):
    h.init()
    h.save("read", [comment()])
    h.save("evidence", evidence(pulls=[], github_time=DUE - 1000))
    h.save("recheck", {"id": 1, "evidence": evidence(), "result": {"passed": True}})
    before = h.snapshot()
    assert h.run("evaluate", "--recheck") == ""
    assert h.snapshot() == before and not h.calls()
    h.queue(evidence_steps())
    assert h.run("evaluate").startswith("counted 1 ")
    assert len(h.data("evidence")) == 2 and h.data("test")[0]["passed"]


@pytest.mark.parametrize("variant", ["round", "no-saved", "syntax", "repeated", "age59", "age60", "due600", "due601"])
def test_first_admission_boundaries(dr, variant):
    t = DUE - (600 if variant == "due600" else 601 if variant == "due601" else 900)
    p = dr.parse_body(body(n=N+1 if variant == "round" else N))
    if variant == "syntax":
        p = dr.parse_body("Follow-up draw: first post")
    if variant == "repeated":
        p = dr.parse_body(body(tail=f"round {N}"))
    ev = evidence(merged=t - (59 if variant == "age59" else 60))
    saved = None if variant == "no-saved" else {"round": N}
    if variant in ("age60", "due601"):
        dr.validate_first(p, saved, t, ev, declaration())
    else:
        with pytest.raises(dr.Refused):
            dr.validate_first(p, saved, t, ev, declaration())


def test_tools_timeouts_and_fullsync(h, monkeypatch):
    calls = []
    monkeypatch.setattr(h.dr.fcntl, "F_FULLFSYNC", 12345, raising=False)
    monkeypatch.setattr(h.dr.fcntl, "fcntl", lambda fd, op: calls.append(op))
    h.init()
    assert calls == [12345]

    def timeout(*args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        raise subprocess.TimeoutExpired("synthetic", 30)

    monkeypatch.setattr(h.dr.subprocess, "run", timeout)
    with pytest.raises(h.dr.Refused):
        h.dr.curl("synthetic")


def test_reading_case_renamed_and_reused_login(h):
    good = h.dr.normalize_comment(graph_comment(author={"login": "renamed", "databaseId": AUTHOR}, body=body(commit=COMMIT.upper())))
    bad = h.dr.normalize_comment(graph_comment(2, author={"login": LOGIN, "databaseId": AUTHOR+1}))
    h.seed([bad, good])
    assert h.run("evaluate").startswith("counted 1 ")


def test_unknown_first_timeout_plus_sixty(dr):
    rs = records() + [rec("post-unknown", {"kind": "first", "github_time": DUE - 900}, 4)]
    assert dr.first_unknown_pending(rs, DUE - 781, 60)
    assert not dr.first_unknown_pending(rs, DUE - 780, 60)
    assert dr.first_unknown_pending(rs, DUE - 601, 240)
    assert not dr.first_unknown_pending(rs, DUE - 600, 240)
    rs += [rec("post-unknown", {"kind": "first", "github_time": DUE - 800}, 5)]
    assert dr.first_unknown_pending(rs, DUE - 780, 60)
    assert not dr.first_unknown_pending(rs, DUE - 680, 60)
    assert not dr.first_unknown_pending([r for r in rs if r["kind"] != "post-unknown"], DUE, 60)
    assert not dr.first_unknown_pending(records() + [rec("post-unknown", {"kind": "second", "github_time": DUE}, 4)], DUE, 60)


def test_beacon_cutoff_uses_github_clock(h):
    h.seed()
    h.queue([http({}, when=DUE + 86340), relay(beacon()), relay(beacon()), http({}, when=DUE + 86340)])
    h.run("beacon", "--round", N, clock=lambda: DUE + 86400)
    assert h.data("beacon-attempt")[-1]["outcome"] == "accepted"


def test_all_records_exported_and_first_sight_non_candidates(h):
    ordinary = comment(2, when=MERGE, text="ordinary prose")
    h.seed([comment(), ordinary])
    h.save("read", [comment(2, text=body(), when=MERGE)])
    assert all(c["body"] != body() for c in h.dr.comment_set(h.dr.load_records(h.state)) if c["id"] == 2)
    for kind, data in [("beacon", beacon()), ("beacon-attempt", {"round": N, "outcome": "accepted"}),
                       ("rehearsal-beacon", {"outcome": "pass", "attempt_count": 1}),
                       ("match", {"kind": "tasks", "round": N, "matches": [], "differences": []}),
                       ("void", {"round": N+1}), ("post", comment(5, text=body("second")))]:
        h.save(kind, data)
    h.dr.append_record(h.state, "relay-primary", b"synthetic", raw=True)
    h.run("evaluate")
    out = h.root / "all-export"
    h.run("publish-records", out)
    source = {p.name: p.read_bytes() for p in (h.state / "records").iterdir()
              if not p.name.endswith(".partial") and "-read." not in p.name}
    assert all((out / "records" / name).read_bytes() == raw for name, raw in source.items())


def test_invalid_scalar_types(dr):
    with pytest.raises(dr.Refused):
        dr.round_due(True)
    with pytest.raises(dr.Refused):
        dr.initial_declaration(pr(merged_by={"id": "71", "login": LOGIN}), b"x")
    for change in ({"fullDatabaseId": None}, {"author": {"databaseId": "71", "login": LOGIN}}):
        with pytest.raises(dr.Refused):
            dr.normalize_comment(graph_comment(**change))
    with pytest.raises(dr.Refused):
        dr.rest_comment({**response(body()), "body": None})


def test_newest_and_empty_round(dr):
    assert dr.newest([rec("round", {"round": 2}, 4), rec("round", {"round": 1}, 5)], "round") == {"round": 1}
    n, action = dr.choose_round(DUE - 899, None)
    assert action == "new" and dr.round_due(n) >= DUE + 1 > dr.round_due(n - 1)


def test_includes_created_false(dr):
    c = comment(lastEditedAt=stamp(DUE - 800), includesCreatedEdit=False,
                edits=[{"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}])
    assert dr.candidates(records([c]))[0]["body"] is None


def test_candidates_merge_second(dr):
    assert dr.candidates(records([comment(when=MERGE)])) == []


@pytest.mark.parametrize("value", ["A" * 64, "a" * 63, None])
def test_beacon_formats(dr, value):
    obj = {**beacon(), "randomness": value}
    reason, accepted = dr.accept_beacon(N, dr.canonical(obj), dr.canonical(obj), DUE)
    assert reason == "randomness format" and accepted is None


def test_post_200_valid_response_unknown(h):
    h.seed()
    h.queue([http({"id": AUTHOR}), http({}), http(response(body("second")), status=200)])
    h.run("post", "second", h.file(body("second")), code=2)
    assert len(h.data("post-unknown")) == 1 and not h.data("post")


def test_beacon_fetches_missing_test(h):
    h.init()
    h.save("read", [comment()])
    h.queue([*evidence_steps(when=DUE), http({}, when=DUE), relay(beacon()), relay(beacon()), http({}, when=DUE)])
    assert h.run("beacon", "--round", N, clock=lambda: DUE) == f"accepted round {N}\n"
    assert h.data("test")[0]["passed"]


def test_rehearsal_refuses_stopped(h):
    h.seed()
    h.save("beacon", beacon())
    h.save("post", comment(2, when=DUE, text=body("stop")))
    before = len(h.calls())
    h.run("beacon", "--rehearsal", code=2)
    assert len(h.calls()) == before


def test_two_commands_wait(h):
    h.init()
    t = int(time.time())
    h.queue([{**http({}, when=t), "delay": .7}])
    argv = [sys.executable, "-I", str(MODULE), "now", "--state", str(h.state)]
    first = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    second = None
    try:
        deadline = time.monotonic() + 5
        while not h.calls() and time.monotonic() < deadline:
            time.sleep(.01)
        assert h.calls()
        second = subprocess.Popen([sys.executable, "-I", str(MODULE), "evaluate", "--state", str(h.state)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(.15)
        assert second.poll() is None
        out, err = first.communicate(timeout=5)
        assert first.returncode == 0 and out.startswith(b"github ") and not err
        out, err = second.communicate(timeout=5)
        assert second.returncode == 10 and out == b"none\n" and not err
    finally:
        if first.poll() is None:
            first.kill()
            first.communicate()
        if second is not None and second.poll() is None:
            second.kill()
            second.communicate()


def test_tool_protocol_for_curl(h, monkeypatch):
    original = h.dr.subprocess.run

    def checked(argv, **kwargs):
        assert argv[:6] == ["curl", "-q", "--silent", "--show-error", "--max-time", "20"]
        assert kwargs["timeout"] == 30 and kwargs["stdin"] == subprocess.DEVNULL
        assert set(kwargs["env"]) <= {"PATH", "HOME"}
        return original(argv, **kwargs)

    monkeypatch.setattr(h.dr.subprocess, "run", checked)
    h.queue([relay(beacon())])
    ok, raw = h.dr.curl("synthetic")
    assert ok and json.loads(raw) == beacon()


def test_every_six_digit_prefix_reserves_number(h):
    h.init()
    (h.state / "records" / "٠٠٠٢٩٩-abandoned.partial").write_bytes(b"unfinished")
    assert h.save("round", {"round": N}).name == "000300-round.json"


def test_export_records_use_crash_safe_writer(h):
    h.seed()
    out = h.root / "crash-safe-export"
    h.run("publish-records", out)
    paths = list((out / "records").glob("*.json"))
    assert paths
    for p in paths:
        assert p.with_name(p.name + ".partial").read_bytes() == p.read_bytes()



def test_frozen_test_without_refetch(h):
    h.init()
    h.save("read", [comment()])
    h.save("test", h.dr.commitment_test(comment(), evidence(), declaration()))
    assert h.run("evaluate").startswith("counted 1 ")
    assert all("contents/results/followup/run/draw_record.py" in " ".join(c["args"]) for c in h.calls())


def test_content_status_decides_even_with_matching_bytes(dr):
    ev = evidence(content={"status": 404, "sha256": declaration()["sha256"], "length": declaration()["length"]})
    assert dr.commitment_test(comment(), ev, declaration())["reason"] == "not found"


def test_initial_declaration_merged_pure(dr):
    with pytest.raises(dr.Refused):
        dr.initial_declaration(pr(merged=False), b"synthetic declaration")


@pytest.mark.parametrize("raw", [b"", b"HTTP/2 200\nno blank", b"garbage\n\n{}", b"HTTP/2 x00\n\n{}"])
def test_http_refusal_schema(dr, raw):
    with pytest.raises(dr.Refused):
        dr.parse_http(raw)


def test_post_saved_before_readback(h, monkeypatch):
    h.init()
    h.save("round", {"round": N})
    original = h.dr.read_issue
    events = []

    def checked(state):
        if events:
            assert h.data("post") and h.data("post")[0]["id"] == 17
            events.append("post saved")
        else:
            events.append("initial read")
        return original(state)

    monkeypatch.setattr(h.dr, "read_issue", checked)
    h.queue(first_steps())
    h.run("post", "first", h.file(body()))
    assert events == ["initial read", "post saved"]


@pytest.mark.parametrize("next_post", [False, True])
def test_accepted_receipt_after_void(h, next_post):
    h.seed()
    h.save("beacon", beacon())
    h.save("void", {"round": N})
    if next_post:
        h.save("read", [comment(2, when=DUE - 899, text=body(n=N + 1))])
    assert h.run("beacon", "--round", N, clock=lambda: DUE + 86400) == f"accepted round {N}\n"
    assert not h.calls()


def test_fullsync_unavailable(h, monkeypatch):
    monkeypatch.delattr(h.dr.fcntl, "F_FULLFSYNC", raising=False)
    h.init()
    assert h.data("declaration") == [declaration()]


def test_default_gh_timeout(h, monkeypatch):
    h.init()
    h.queue([http({})])
    original = h.dr.subprocess.run

    def checked(argv, **kwargs):
        assert kwargs["timeout"] == 60
        return original(argv, **kwargs)

    monkeypatch.setattr(h.dr.subprocess, "run", checked)
    assert h.dr.main(["now", "--state", str(h.state)], clock=lambda: DUE - 900) == 0


def test_later_discovered_unrecoverable_never_changes_count(h):
    h.seed()
    assert h.run("evaluate").startswith("counted 1 ")
    c = comment(2, when=DUE - 901, text="edited", lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                edits=[{"editedAt": stamp(DUE - 901), "deletedAt": stamp(DUE - 800), "diff": SENTINEL}])
    h.save("read", {"github_time": DUE + 1, "comments": [c]})
    assert h.run("evaluate").startswith("counted 1 ")
    row = json.loads(h.run("publish-list"))["first_posts"][0]
    assert row["reason"] == "unrecoverable" and row["deletedAt"] == stamp(DUE - 800)
    assert row["first_seen"] == DUE + 1


def test_counted_admission_pure(dr):
    result = dr.evaluate_records(records([comment()]))
    assert dr.require_counted(result, N)["id"] == 1
    for r, n in [(dr.evaluate_records(records()), None), ({**result, "code": 14}, None), (result, N+1)]:
        with pytest.raises(dr.Refused):
            dr.require_counted(r, n)


def test_stop_admission_reason_and_attempt(dr):
    rs = records([comment()])
    counted = dr.evaluate_records(rs)["counted"]
    with pytest.raises(dr.Refused):
        dr.stop_admission(rs, counted, None, None, DUE + 86400)
    with pytest.raises(dr.Refused):
        dr.stop_admission(rs, counted, "beacon", None, DUE + 86400)



@pytest.mark.parametrize("created_second", [False, True])
def test_unknown_second_never_gates_with_frozen_created_body(h, created_second):
    h.seed()
    h.save("post-unknown", {"kind": "second", "github_time": DUE - 900, "known_ids": [1]})
    if not created_second:
        # This new comment was known ordinary prose before its creation revision was deleted.
        h.save("read", {"github_time": DUE - 880,
                        "comments": [comment(9, when=DUE - 890, text="ordinary prose")]})
    c = comment(9, when=DUE - 890, text="edited prose", lastEditedAt=stamp(DUE - 850),
                includesCreatedEdit=True, edits=[{"editedAt": stamp(DUE - 890),
                "deletedAt": None if created_second else stamp(DUE - 850),
                "diff": body("second") if created_second else None}])
    h.save("read", {"github_time": DUE - 839, "comments": [c]})
    h.queue([http({"id": AUTHOR}), http({}), http(response(task_body()), status=201), *read_steps()])
    assert h.run("post", "tasks", h.file(task_body())).startswith("posted 17 ")


@pytest.mark.parametrize("negative", ["absent-content"])
def test_old_non_tree_negative_does_not_decide_later_comment(h, negative):
    h.init()
    h.save("read", [comment()])
    steps = evidence_steps(pulls=[])
    if negative == "absent-content":
        steps = [*steps[:2], http({"message": "not found"}, status=404)]
    else:
        steps[1] = http({"default_branch": "other"})
    h.queue(steps)
    assert h.run("evaluate", code=10) == "none\n"
    first = h.data("test")[0]
    h.save("read", {"github_time": DUE - 700, "comments": [comment(2, when=DUE - 700)]})
    h.queue(evidence_steps(when=DUE - 700, merged=DUE - 800))
    assert h.run("evaluate", clock=lambda: DUE - 700).startswith("counted 2 ")
    assert h.data("test")[0] == first and not first["passed"]
    assert h.data("test")[1]["passed"]


@pytest.mark.parametrize("change", [{"content": {"status": 404}}, {"default_branch": "other"}])
def test_precomment_absence_is_not_a_tree_fact(dr, change):
    ev = evidence(github_time=DUE - 1000, **change)
    assert dr.commitment_test(comment(), ev, declaration()) is None


def test_post_test_uses_response_second_and_read_age_sixty(h):
    h.init()
    h.save("round", {"round": N})
    t = DUE - 900
    steps = first_steps(when=t, created=t)
    steps[3:9] = evidence_steps(when=t, merged=t)
    h.queue(steps)
    assert h.run("post", "first", h.file(body()), clock=lambda: t + 60) == f"posted 17 {stamp(t)}\n"
    test = h.data("test")[0]
    assert not test["passed"] and test["reason"] == "merge not before comment"
    assert h.run("evaluate", code=10) == "none\n"


@pytest.mark.parametrize("negative", ["absent-content", "non-main"])
def test_saved_precheck_decides_post_after_interrupted_test_write(h, negative):
    h.init()
    early = evidence(github_time=DUE - 1000, pulls=[])
    if negative == "absent-content":
        early["content"] = {"status": 404}
    else:
        early["default_branch"] = "other"
    h.save("evidence", early)
    h.save("evidence", evidence(merged=DUE - 960, github_time=DUE - 900))
    saved = h.dr.rest_comment(response(body(), when=DUE - 899))
    h.save("post", {**saved, "github_time": DUE - 900})
    # This is the state after the POST record is durable but before its test is written.
    assert h.run("evaluate").startswith("counted 17 ")
    assert h.data("test")[0]["passed"]
    assert len(h.data("evidence")) == 2


def test_t3_full_comment_id_survives_database_id_overflow(h):
    h.init()
    cid = 5000000000
    node = graph_comment(cid, databaseId=None, fullDatabaseId=str(cid))
    h.queue(read_steps([node]))
    assert h.run("read") == "read 1\n"
    saved = h.data("read")[0]["comments"][0]
    assert saved["id"] == h.dr.rest_comment(response(body(), cid=cid))["id"] == cid
    query = next(c for c in h.calls() if "graphql" in c["args"])
    assert "fullDatabaseId author{" in " ".join(query["args"]) and "on User { databaseId }" in " ".join(query["args"])


# Round 3: the run script's public interface and the reviewed rule corrections.
def task_body(n=N):
    return body("tasks", n=n, tail="\n".join(f"{pack}_{kind}_sha256 {'d' * 64}"
                for pack in ("a", "b", "c") for kind in ("pack", "tasks")))


@pytest.mark.parametrize("case,stopped", [("before", True), ("after", False),
    ("other-round", True), ("repeated", True), ("no-round", True),
    ("tie-stop-first", True), ("tie-tasks-first", False), ("other-author", False)])
def test_r3_stop_task_order(h, case, stopped):
    tasks = task_body(N + 1 if case == "other-round" else N)
    if case == "repeated":
        tasks += f"\nround {N}"
    if case == "no-round":
        tasks = tasks.replace(f"round {N}\n", "")
    stop_time = DUE + (2 if case in ("after", "other-round", "repeated", "no-round") else 0)
    task_time = DUE + (0 if case.startswith("tie-") else 1)
    stop_id, task_id = (3, 2) if case == "tie-tasks-first" else (2, 3)
    cs = [comment(), comment(stop_id, when=stop_time, text=body("stop"),
                           author=AUTHOR + (case == "other-author")),
          comment(task_id, when=task_time, text=tasks)]
    h.init()
    h.queue(read_steps([graph_comment(c["id"], createdAt=c["created_at"], body=c["body"],
              author={"login": LOGIN, "databaseId": c["author"]}) for c in cs], DUE + 2))
    h.run("read", clock=lambda: DUE + 2)
    h.save("evidence", evidence())
    out = h.run("evaluate", code=14 if stopped else 0)
    assert out.startswith(f"stopped {stop_id}" if stopped else "counted 1 ")
    listing = json.loads(h.run("publish-list"))
    if case == "after":
        assert stop_id in [m["id"] for m in listing["markers"]]
        h.save("beacon", beacon())
        h.queue([http({"id": AUTHOR}), http({}, when=DUE + 2)])
        h.run("post", "stop", h.file(body("stop")), "--reason", "build",
              "--failure-sha256", "f" * 64, code=2, clock=lambda: DUE + 2)
        assert "task lists already posted" in h.err
        assert not any("POST" in c["args"] for c in h.calls())


def test_r3_markers_author_time_and_count(h):
    h.seed([comment(), comment(2, when=MERGE - 1, text="Follow-up draw: before"),
            comment(3, when=MERGE, text="Follow-up draw: merge second"),
            comment(4, when=MERGE + 1, text="Follow-up draw: after"),
            comment(5, text="Follow-up draw: " + SENTINEL, author=AUTHOR + 1)])
    data = json.loads(h.run("publish-list"))
    assert [(m["id"], m["after_merge"]) for m in data["markers"]] == [(2, False), (3, False), (4, True)]
    assert data["other_comments"] == 1


def test_r3_reading_refusal_names_counted_commit(h):
    h.seed([comment(text=body(commit=OTHER))])
    h.save("evidence", evidence(commit=OTHER))
    (h.root / "different-module").write_text("synthetic")
    h.run("evaluate", code=2)
    assert h.err == f"refused: reading module differs at {OTHER}\n"


def test_r3_reading_unavailable_names_commit(h, monkeypatch):
    monkeypatch.setattr(h.dr, "gh", lambda *args: {"status": 404, "body": b""})
    with pytest.raises(h.dr.Refused, match=f"reading module unavailable at {OTHER}"):
        h.dr.verify_reading(OTHER)


def s1_beacon_rule(path):
    # Verbatim rule from the reviewed S1 reader; the real integration follows merge.
    data = json.loads(Path(path).read_bytes().decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {"round", "randomness", "signature"}: raise ValueError  # noqa: E701
    if type(data["round"]) is not int or data["round"] <= 0: raise ValueError  # noqa: E701
    if not isinstance(data["randomness"], str) or not re.fullmatch(r"[0-9a-f]{64}", data["randomness"]): raise ValueError  # noqa: E701
    if not isinstance(data["signature"], str) or not re.fullmatch(r"[0-9a-f]+", data["signature"]): raise ValueError  # noqa: E701
    if hashlib.sha256(bytes.fromhex(data["signature"])).hexdigest() != data["randomness"]: raise ValueError  # noqa: E701
    return data


def test_r3_beacon_out_accept_saved_existing_and_s1(h):
    h.seed()
    target = h.root / "accepted.json"
    h.queue([http({}, when=DUE), relay(beacon()), relay(beacon()), http({}, when=DUE)])
    assert h.run("beacon", "--round", N, "--out", target, clock=lambda: DUE) == f"accepted round {N}\n"
    assert target.read_bytes() == h.dr.canonical(beacon())
    assert s1_beacon_rule(target)["round"] == N
    before = target.stat()
    calls = len(h.calls())
    snapshot = h.snapshot()
    h.run("beacon", "--round", N, "--out", target, clock=lambda: DUE + 86400)
    assert target.stat().st_ino == before.st_ino and target.stat().st_mtime_ns == before.st_mtime_ns
    assert h.snapshot() == snapshot and len(h.calls()) == calls
    other = h.root / "saved.json"
    h.run("beacon", "--round", N, "--out", other)
    assert other.read_bytes() == target.read_bytes() and len(h.calls()) == calls
    recovered = h.root / "recovered.json"
    partial = recovered.with_name(recovered.name + ".0.partial")
    partial.write_bytes(b"abandoned")
    h.run("beacon", "--round", N, "--out", recovered)
    assert partial.read_bytes() == b"abandoned"
    assert recovered.read_bytes() == target.read_bytes()
    other.write_bytes(b"different")
    h.run("beacon", "--round", N, "--out", other, code=2)
    assert other.read_bytes() == b"different"
    assert "beacon output differs" in h.err


@pytest.mark.parametrize("offset,code", [(0, 10), (86400, 13)])
def test_r3_beacon_no_output_on_negative(h, offset, code):
    h.seed()
    target = h.root / "negative.json"
    h.queue([http({}, when=DUE + offset), relay(b"{}"), relay(b"{}"), http({}, when=DUE + offset)])
    h.run("beacon", "--round", N, "--out", target, code=code, clock=lambda: DUE + offset)
    assert not target.exists()


@pytest.mark.parametrize("rehearsal", [False, True])
def test_r3_beacon_out_required(h, rehearsal):
    h.seed()
    h.save("beacon", beacon())
    args = ["beacon", "--state", str(h.state), "--round", str(N)]
    assert h.dr.main(args + (["--rehearsal"] if rehearsal else [])) == 2
    assert "beacon round requires out" in h.capsys.readouterr().err and not h.calls()


def test_r3_beacon_output_no_replace_race(h, monkeypatch):
    h.seed()
    h.save("beacon", beacon())
    target = h.root / "raced.json"
    link = h.dr.os.link

    def race(source, destination):
        if destination == target:
            target.write_bytes(b"winner")
        return link(source, destination)

    monkeypatch.setattr(h.dr.os, "link", race)
    h.run("beacon", "--round", N, "--out", target, code=2)
    assert target.read_bytes() == b"winner"


@pytest.mark.parametrize("kind", ["tasks", "stop"])
def test_r3_lost_second_landed_does_not_gate(h, kind):
    h.seed()
    h.queue([http({"id": AUTHOR}), http({}, when=DUE), http({}, status=500)])
    h.run("post", "second", h.file(body("second")), code=2, clock=lambda: DUE)
    assert len(h.data("post-unknown")) == 1
    h.save("read", [comment(17, when=DUE, text=body("second"))])
    h.save("beacon", beacon())
    text = task_body() if kind == "tasks" else body("stop")
    h.queue([http({"id": AUTHOR}), http({}, when=DUE), http(response(text, cid=18, when=DUE), status=201),
             *read_steps(when=DUE)])
    args = ["--reason", "build", "--failure-sha256", "f" * 64] if kind == "stop" else []
    assert h.run("post", kind, h.file(text), *args, clock=lambda: DUE).startswith("posted 18 ")
    out = h.root / "unknown-export"
    h.run("publish-records", out)
    assert h.dr.newest(h.dr.load_records(out), "post-unknown")["kind"] == "second"


def test_r3_kill_after_landed_second_does_not_gate(h, monkeypatch):
    h.seed()
    original = h.dr.append_record

    def crash(state, kind, data, **kwargs):
        if kind == "post":
            raise KeyboardInterrupt
        return original(state, kind, data, **kwargs)

    h.queue([http({"id": AUTHOR}), http({}), http(response(body("second")), status=201)])
    with monkeypatch.context() as m:
        m.setattr(h.dr, "append_record", crash)
        with pytest.raises(KeyboardInterrupt):
            h.run("post", "second", h.file(body("second")))
    assert not h.data("post") and not h.data("post-unknown")
    h.save("read", [comment(17, when=DUE - 800, text=body("second"))])
    h.queue([http({"id": AUTHOR}), http({}), http(response(task_body(), cid=18), status=201), *read_steps()])
    assert h.run("post", "tasks", h.file(task_body())).startswith("posted 18 ")


@pytest.mark.parametrize("landed", [False, True])
def test_r3_lost_first_time_only_and_preread(h, landed):
    h.init()
    h.save("round", {"round": N})
    h.queue(first_steps(outcome=http({}, status=500)))
    h.run("post", "first", h.file(body()), code=2)
    unknown = h.data("post-unknown")[-1]
    assert unknown["github_time"] == DUE - 900
    h.queue(first_steps(when=DUE - 781))
    h.run("post", "first", h.file(body()), code=2, clock=lambda: DUE - 781)
    assert h.err == "refused: post outcome unknown\n"
    nodes = [graph_comment(17, createdAt=stamp(DUE - 899))] if landed else []
    h.queue(first_steps(nodes, when=DUE - 780, created=DUE - 779))
    out = h.run("post", "first", h.file(body()), code=2 if landed else 0, clock=lambda: DUE - 780)
    if landed:
        assert "counted draw already exists" in h.err
    else:
        assert out.startswith("posted 17 ")


@pytest.mark.parametrize("side", ["before", "after", "predates"])
def test_r3_default_branch_undecided_saved_then_restored(h, side):
    h.init()
    h.save("read", [comment()])
    evtime = DUE - 1000 if side == "predates" else DUE - 900
    steps = evidence_steps(when=evtime, pulls=[] if side == "predates" else None)
    if side == "before":
        steps[1] = http({"default_branch": "other"}, when=evtime)
    if side == "after":
        # The after-pulls repository read is new in this round.
        steps[4] = http({"default_branch": "other"}, when=evtime, contains="repos/")
    h.queue(steps)
    assert h.run("evaluate", code=2, clock=lambda: evtime) == ""
    assert h.err == "refused: post 1 undecided\n"
    ev = h.data("evidence")[-1]
    if side != "predates":
        assert ev["default_branch" if side == "before" else "default_branch_after"] == "other"
    assert not h.data("test")
    h.queue([http({"id": AUTHOR}), *read_steps(when=evtime), *steps])
    h.run("post", "first", h.file(body()), code=2, clock=lambda: evtime)
    assert h.err == "refused: post 1 undecided\n"
    h.queue(evidence_steps())
    assert h.run("evaluate").startswith("counted 1 ")
    frozen = h.snapshot()
    assert h.run("evaluate").startswith("counted 1 ")
    assert h.snapshot() == frozen


def test_r3_failed_fetch_keeps_refusal(h):
    h.init()
    h.save("read", [comment()])
    h.queue([*evidence_steps()[:2], http({}, status=502)])
    h.run("evaluate", code=2)
    assert h.err == "refused: commitment evidence unavailable\n"
    assert not h.data("evidence") and not h.data("test")


@pytest.mark.parametrize("branch", ["default_branch", "default_branch_after"])
def test_r3_default_setting_never_decides_tree_failure(dr, branch):
    ev = evidence(**{branch: "other"}, content={"status": 200, "sha256": "x", "length": 0})
    assert dr.commitment_test(comment(), ev, declaration()) is None


@pytest.mark.parametrize("offset,accepted", [(86340, True), (86400, False)])
def test_r3_cutoff_and_stop_github_clock(h, offset, accepted):
    h.seed()
    t = DUE + offset
    h.queue([http({}, when=t), relay(beacon()), relay(beacon()), http({}, when=t)])
    h.run("beacon", "--round", N, "--out", h.root / "clock-beacon.json", code=0 if accepted else 13,
          clock=lambda: t + 60)
    attempt = h.data("beacon-attempt")[-1]
    assert attempt["github_after"] == t and attempt["machine_after"] == t + 60
    assert attempt["outcome"] == ("accepted" if accepted else "cutoff")
    # A forged cutoff attempt still cannot make an early beacon-stop pass admission.
    if accepted:
        rs = records([comment()]) + [rec("beacon-attempt", {"round": N, "outcome": "cutoff"}, 4)]
        state = h.root / "stop-state"
        for r in rs:
            h.dr.append_record(state, r["kind"], r["data"])
        h.state = state
    h.queue([http({"id": AUTHOR}), http({}, when=t), http(response(body("stop"), when=t), status=201),
             *read_steps(when=t)])
    h.run("post", "stop", h.file(body("stop")), "--reason", "beacon", code=2 if accepted else 0,
          clock=lambda: t + 60)
    if accepted:
        assert "beacon stop conditions not met" in h.err
        assert not any("POST" in c["args"] for c in h.calls())


def test_r3_stop_due_uses_github_clock(h):
    h.seed()
    h.save("beacon", beacon())
    h.queue([http({"id": AUTHOR}), http({}, when=DUE - 1)])
    h.run("post", "stop", h.file(body("stop")), "--reason", "build", "--failure-sha256", "f" * 64,
          code=2, clock=lambda: DUE + 59)
    assert "stop before round due" in h.err


def test_r3_full_id_only_query_and_no_fallback(h):
    h.init()
    node = graph_comment(fullDatabaseId="5000000000")
    node.pop("databaseId", None)
    h.queue(read_steps([node]))
    h.run("read")
    assert h.data("read")[0]["comments"][0]["id"] == 5000000000
    query = next(c for c in h.calls() if "graphql" in c["args"])["args"]
    query = next(a for a in query if a.startswith("query="))
    assert "fullDatabaseId author{" in query
    with pytest.raises(h.dr.Refused):
        h.dr.normalize_comment(graph_comment(fullDatabaseId=None, databaseId=1))


def test_r3_public_list_stops_count_after_untested(h):
    h.seed([comment(text=body(commit=OTHER)), comment(2, when=DUE - 899)])
    h.queue([*evidence_steps()[:2], http({}, status=502)])
    data = json.loads(h.run("publish-list"))
    assert data["first_posts"][0]["reason"].startswith("untested:")
    assert data["first_posts"][1]["reason"] == "undecided: an earlier post is untested"
    assert not any(r["counted"] for r in data["first_posts"])


def test_r3_beacon_saved_before_attempt_crash(h, monkeypatch):
    h.seed()
    original = h.dr.append_record

    def crash(state, kind, data, **kwargs):
        if kind == "beacon-attempt":
            raise KeyboardInterrupt
        return original(state, kind, data, **kwargs)

    h.queue([http({}, when=DUE), relay(beacon()), relay(beacon()), http({}, when=DUE)])
    with monkeypatch.context() as m:
        m.setattr(h.dr, "append_record", crash)
        with pytest.raises(KeyboardInterrupt):
            h.run("beacon", "--round", N, "--out", h.root / "crash.json", clock=lambda: DUE)
    assert h.data("beacon") == [beacon()] and not h.data("beacon-attempt")
    h.run("beacon", "--round", N, "--out", h.root / "crash.json", clock=lambda: DUE + 86400)
    assert (h.root / "crash.json").read_bytes() == h.dr.canonical(beacon())


def test_r3_first_readback_evaluates_window_comment(h):
    h.init()
    h.save("round", {"round": N})
    steps = first_steps()
    steps[-1] = http(graph([graph_comment(16, createdAt=stamp(DUE - 900), body=body(commit=OTHER)),
                             graph_comment(17, createdAt=stamp(DUE - 899))]))
    h.queue([*steps, *evidence_steps()])
    h.run("post", "first", h.file(body()))
    assert {t["id"] for t in h.data("test")} == {16, 17}
    assert h.data("test")[-1]["id"] == 16


@pytest.mark.parametrize("when,author,blocked", [(MERGE, AUTHOR, False), (MERGE - 1, AUTHOR, False),
                                                   (MERGE + 1, AUTHOR, True), (MERGE + 1, AUTHOR + 1, False)])
def test_r3_blocked_candidates_only(h, when, author, blocked):
    h.init()
    h.save("round", {"round": N})
    node = graph_comment(9, createdAt=stamp(when), author={"login": LOGIN, "databaseId": author},
                         lastEditedAt=stamp(DUE - 800))
    h.queue(first_steps([node]))
    out = h.run("post", "first", h.file(body()), code=13 if blocked else 0)
    assert out.startswith("blocked 9" if blocked else "posted 17 ")


@pytest.mark.parametrize("number,other", [(5, 5.0), (1, True)])
def test_r3_relay_canonical_agreement(dr, number, other):
    a = beacon(number)
    b = {**a, "round": other}
    assert dr.accept_beacon(number, dr.canonical(a), dr.canonical(b))[1] is None
    assert dr.accept_beacon(number, b' { "round":' + str(number).encode() + b', "signature":"' +
               a["signature"].encode() + b'", "randomness":"' + a["randomness"].encode() + b'"}', dr.canonical(a))[1] == a


def test_r3_tool_environment_and_curl_q(h, monkeypatch):
    h.init()
    monkeypatch.setenv("GH_HOST", "synthetic.invalid")
    monkeypatch.setenv("GH_TOKEN", "synthetic-token")
    h.queue([http({}), relay(beacon())])
    h.run("now")
    h.dr.curl("synthetic")
    calls = h.calls()
    assert all(not any(k.startswith("GH_") for k in c["env"]) for c in calls)
    assert calls[-1]["args"][0] == "-q"


def test_r3_recheck_undecided_not_unchanged(h):
    h.seed()
    h.run("evaluate")
    before = h.data("test")
    steps = evidence_steps()
    steps[1] = http({"default_branch": "other"})
    h.queue(steps)
    assert h.run("evaluate", "--recheck") == "undecided 1\n"
    assert h.data("recheck")[-1]["result"] is None and h.data("test") == before


# Round 4: due-time task lists, pre-merge reasons and saved undecided evidence.
@pytest.mark.parametrize("task_time,stopped", [(DUE - 1000, True), (DUE, False)])
def test_r4_task_list_due_boundary(h, task_time, stopped):
    h.seed([comment(), comment(2, when=task_time, text=task_body()),
            comment(3, when=DUE + 1, text=body("stop"))])
    assert h.run("evaluate", code=14 if stopped else 0).startswith(
        "stopped 3" if stopped else "counted 1 ")


@pytest.mark.parametrize("when", [MERGE - 1, MERGE, MERGE + 1])
@pytest.mark.parametrize("author", [AUTHOR, AUTHOR + 1])
@pytest.mark.parametrize("kind", ["unrecoverable", "malformed", "valid"])
def test_r4_first_row_premerge_reason(h, when, author, kind):
    c = comment(when=when, author=author)
    if kind == "unrecoverable":
        c.update(lastEditedAt=stamp(DUE), includesCreatedEdit=False)
    elif kind == "malformed":
        c["body"] = body(n=0, commit="invalid")
    h.seed([c])
    rs = h.dr.load_records(h.state)
    fixed = h.dr.comment_set(rs)[0]
    if author == AUTHOR and when <= MERGE:
        expected = "not after the merge"
    elif kind == "unrecoverable":
        expected = "unrecoverable"
    elif kind == "malformed":
        expected = "not a commitment post: missing round"
    elif author != AUTHOR:
        expected = "not the merging account"
    else:
        expected = "failed: merge not before comment"
    assert h.dr.first_row(fixed, rs, {}, None)["reason"] == expected
    listing = json.loads(h.run("publish-list"))
    if author == AUTHOR:
        assert listing["first_posts"][0]["reason"] == expected
    else:
        assert listing["first_posts"] == [] and listing["other_comments"] == 1


@pytest.mark.parametrize("side", ["before", "after"])
def test_r4_publish_list_undecided_reloads_saved_evidence(h, monkeypatch, side):
    h.init()
    h.save("read", [comment(), comment(2, when=DUE - 899, text=body(commit=OTHER))])
    steps = evidence_steps()
    steps[1 if side == "before" else 4] = http({"default_branch": "other"})
    h.queue([*steps, *evidence_steps()])
    original_ensure, original_publish = h.dr.ensure_test, h.dr.publish_list
    attempts = []

    def ensure(rs, c):
        saved = [r["data"] for r in rs if r["kind"] == "evidence"]
        assert saved == h.data("evidence")
        attempts.append(c["id"])
        yield from original_ensure(rs, c)

    def publish(rs, failures):
        assert [r["data"] for r in rs if r["kind"] == "evidence"] == h.data("evidence")
        return original_publish(rs, failures)

    monkeypatch.setattr(h.dr, "ensure_test", ensure)
    monkeypatch.setattr(h.dr, "publish_list", publish)
    listing = json.loads(h.run("publish-list"))
    assert attempts == [1, 2]
    assert listing["first_posts"][0]["reason"] == "untested: undecided"
    assert listing["first_posts"][1]["reason"] == "undecided: an earlier post is untested"
    assert len(h.data("evidence")) == 2
    assert h.data("test")[0]["id"] == 2 and h.data("test")[0]["passed"]
    assert len(h.calls()) == 12


def test_r4_publish_list_failed_fetch(h):
    h.init()
    h.save("read", [comment()])
    h.queue([*evidence_steps()[:2], http({}, status=502)])
    listing = json.loads(h.run("publish-list"))
    assert listing["first_posts"][0]["reason"] == "untested: commitment evidence unavailable"
    assert not h.data("evidence") and not h.data("test")


@pytest.mark.parametrize("failure", ["refused-middle", "exception-suffix"])
def test_r4_publish_list_other_failures(h, monkeypatch, failure):
    h.init()
    h.save("read", [comment()])

    def fetch(commit):
        if failure == "refused-middle":
            raise h.dr.Refused("undecided fetch failed")
        raise RuntimeError("fetch undecided")

    monkeypatch.setattr(h.dr, "fetch_evidence", fetch)
    listing = json.loads(h.run("publish-list"))
    assert listing["first_posts"][0]["reason"] == "untested: commitment evidence unavailable"
