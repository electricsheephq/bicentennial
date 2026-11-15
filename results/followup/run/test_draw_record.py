"""Offline draw rules, including frozen comment decisions and uncertain sends."""

import fcntl
import hashlib
import importlib.util
import json
import os
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
    return f"Follow-up draw: {names[kind]}\nround {n}\nrun_commit {commit}\n{tail}"


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
    data = {"commit": COMMIT, "github_time": DUE - 900, "default_branch": "main",
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
            *([http({"status": "ahead"}, when=when, contains="compare/")] if pulls is None else [])]


def page(nodes, more=False, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}


def graph_comment(cid=1, **changes):
    return {"id": f"node-{cid}", "databaseId": cid, "author": {"login": LOGIN, "databaseId": AUTHOR},
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
    ({"pulls": []}, "no qualifying pull request"), ({"default_branch": "other"}, "default branch is not main")])
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
    assert "changed 2 passed true false" in h.run("evaluate", "--recheck", clock=lambda: DUE - 699)
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
    h.queue([*evidence_steps()[:3], http([{"number": n, "base": {"ref": "other"}, "merged_at": None, "merge_commit_sha": None} for n in range(100)])])
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
        steps[3:8] = evidence_steps(merged=DUE - 959)
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
def test_unknown_post_and_later_read_gate(h, kind, outcome):
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
    h.queue(first_steps() if kind == "first" else [http({"id": AUTHOR}), http({}),
             http(response(text, when=DUE - 899), status=201), *read_steps()])
    h.run("post", kind, h.file(text), code=2)
    h.save("read", {"github_time": DUE - 840, "comments": []})
    if kind == "first":
        h.queue(first_steps(when=DUE - 840, created=DUE - 839))
    else:
        h.queue([http({"id": AUTHOR}), http({}, when=DUE - 840),
                 http(response(text, when=DUE - 839), status=201), *read_steps(when=DUE - 840)])
    assert h.run("post", kind, h.file(text), clock=lambda: DUE - 840).startswith("posted 17 ")


def test_unknown_new_comment_still_refuses(h):
    h.seed()
    h.save("post-unknown", {"kind": "second", "github_time": DUE - 900, "known_ids": []})
    h.save("read", {"github_time": DUE - 840, "comments": [comment(9, text=body("second"))]})
    assert h.dr.unknown_pending(h.dr.load_records(h.state))
    h.queue([http({"id": AUTHOR})])
    h.run("post", "second", h.file(body("second")), code=2)


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
    assert [r["reason"] for r in rows] == ["not a commitment post: repeated value name", "not after the merge",
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
                                  if k in ("PATH", "HOME") or k.startswith("GH_")}
        assert kwargs["stdin"] == subprocess.DEVNULL
        return original(argv, **kwargs)

    monkeypatch.setattr(h.dr.subprocess, "run", checked)
    h.init()
    h.queue([http({}, lf=True)])
    h.run("now")
    call = h.calls()[0]
    assert call["stdin"] == "" and "DROP_SYNTHETIC" not in call["env"]
    assert set(call["env"]) <= {"PATH", "HOME", "LC_CTYPE", "__CF_USER_TEXT_ENCODING"} | {k for k in os.environ if k.startswith("GH_")}
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


def test_unknown_read_at_59_not_60(h):
    h.seed()
    h.save("post-unknown", {"kind": "second", "github_time": DUE - 900, "known_ids": [1]})
    h.save("read", {"github_time": DUE - 841, "comments": []})
    assert h.dr.unknown_pending(h.dr.load_records(h.state))
    h.save("read", {"github_time": DUE - 840, "comments": []})
    assert not h.dr.unknown_pending(h.dr.load_records(h.state))


def test_beacon_cutoff_uses_later_clock(h):
    h.seed()
    h.queue([http({}, when=DUE + 86340), relay(beacon()), relay(beacon()), http({}, when=DUE + 86340)])
    h.run("beacon", "--round", N, code=13, clock=lambda: DUE + 86400)
    assert h.data("beacon-attempt")[-1]["outcome"] == "cutoff"


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
    for change in ({"databaseId": "1"}, {"author": {"databaseId": "71", "login": LOGIN}}):
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
        assert argv[:5] == ["curl", "--silent", "--show-error", "--max-time", "20"]
        assert kwargs["timeout"] == 30 and kwargs["stdin"] == subprocess.DEVNULL
        assert set(kwargs["env"]) <= {"PATH", "HOME"} | {k for k in os.environ if k.startswith("GH_")}
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
def test_unknown_clearance_uses_frozen_created_body(h, created_second):
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
    assert h.dr.unknown_pending(h.dr.load_records(h.state)) is created_second


@pytest.mark.parametrize("negative", ["absent-content", "non-main"])
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
    steps[3:8] = evidence_steps(when=t, merged=t)
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
    assert "fullDatabaseId" in " ".join(query["args"]) and "databaseId" in " ".join(query["args"])
