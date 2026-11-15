"""Offline specifications for the draw's saved-record rules."""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

import pytest

MODULE = Path(__file__).with_name("draw_record.py")
COMMIT = "a" * 40
OTHER = "b" * 40
GENESIS = 1692803367
N = 1001
DUE = GENESIS + (N - 1) * 3
MERGE = DUE - 2000
LOGIN = "synthetic-merge"
SENTINEL = "synthetic-private-sentinel"


@pytest.fixture
def dr():
    spec = importlib.util.spec_from_file_location("draw_record", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stamp(seconds):
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def body(kind="first", n=N, commit=COMMIT, tail=""):
    headers = {"first": "first post", "second": "second post", "tasks": "task lists", "stop": "stop"}
    return f"Follow-up draw: {headers[kind]}\nround {n}\nrun_commit {commit}\n{tail}"


def comment(cid=1, when=DUE - 900, text=None, author=LOGIN, **extra):
    return {"id": cid, "author": author, "created_at": stamp(when),
            "body": body() if text is None else text, "lastEditedAt": None,
            "includesCreatedEdit": False, "edits": [], **extra}


def rec(kind, data, number):
    return {"kind": kind, "data": data, "number": number}


def declaration():
    raw = b"synthetic declaration\n"
    return {"merging_login": LOGIN, "merge_time": stamp(MERGE),
            "declaration_commit": COMMIT, "sha256": hashlib.sha256(raw).hexdigest(),
            "length": len(raw)}


def evidence(merged=MERGE + 1, **changes):
    data = {"commit": COMMIT, "content": {"status": 200, "sha256": declaration()["sha256"],
                                         "length": declaration()["length"]},
            "pulls": [{"number": 71, "base": "main", "merged_at": stamp(merged),
                       "merge_commit_sha": OTHER, "compare": "ahead"}]}
    data.update(changes)
    return data


def records(comments=(), ev=None):
    result = [rec("declaration", declaration(), 1), rec("read", list(comments), 2)]
    result.append(rec("evidence", evidence() if ev is None else ev, 3))
    return result


FAKE = r'''#!SHEBANG
import json, os, pathlib, sys
root = pathlib.Path(os.environ["DRAW_FIXTURE"])
args = sys.argv[1:]
with (root / "calls").open("a") as out:
    out.write(json.dumps({"tool": pathlib.Path(sys.argv[0]).name, "args": args}) + "\n")
queue = json.loads((root / "queue.json").read_text())
if not queue:
    sys.exit(92)
step = queue.pop(0)
(root / "queue.json").write_text(json.dumps(queue))
if step.get("contains") and step["contains"] not in " ".join(args):
    sys.exit(93)
sys.stdout.buffer.write(bytes.fromhex(step["output"]))
sys.exit(step.get("exit", 0))
'''


class Harness:
    def __init__(self, dr, root, monkeypatch):
        self.dr = dr
        self.root = root
        self.state = root / "state"
        self.bin = root / "bin"
        self.bin.mkdir()
        for tool in ("gh", "curl"):
            target = self.bin / tool
            target.write_text(FAKE.replace("SHEBANG", sys.executable))
            target.chmod(0o755)
        monkeypatch.setenv("PATH", str(self.bin) + os.pathsep + os.environ["PATH"])
        monkeypatch.setenv("DRAW_FIXTURE", str(root))
        self.queue([])

    def queue(self, steps):
        (self.root / "queue.json").write_text(json.dumps(steps))

    def calls(self):
        path = self.root / "calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def save(self, kind, data):
        return self.dr.append_record(self.state, kind, data)

    def init(self):
        self.save("declaration", declaration())

    def seed(self, comments=None):
        self.init()
        self.save("read", [comment()] if comments is None else comments)
        self.save("evidence", evidence())

    def run(self, *args, code=0):
        result = subprocess.run([sys.executable, "-I", str(MODULE), args[0], "--state",
                                 str(self.state), *map(str, args[1:])], capture_output=True)
        assert result.returncode == code, (result.returncode, result.stdout, result.stderr)
        assert SENTINEL.encode() not in result.stdout + result.stderr
        return result.stdout.decode()

    def file(self, text):
        target = self.root / "post.txt"
        target.write_bytes(text.encode())
        return target

    def snapshot(self):
        folder = self.state / "records"
        return {p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest())
                for p in folder.iterdir()} if folder.exists() else {}


@pytest.fixture
def h(dr, tmp_path, monkeypatch):
    return Harness(dr, tmp_path, monkeypatch)


def http(data, status=200, when=DUE - 900, exit=0, contains=None):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    header = f"HTTP/2.0 {status} Synthetic\r\nDate: {format_datetime(datetime.fromtimestamp(when, UTC), usegmt=True)}\r\nX-Example: yes\r\n\r\n".encode()
    return {"output": (header + raw).hex(), "exit": exit, "contains": contains}


def relay(data, exit=0):
    raw = data if isinstance(data, bytes) else json.dumps(data).encode()
    return {"output": raw.hex(), "exit": exit}


def pr(merged=MERGE):
    return {"merged": True, "merged_by": {"login": LOGIN}, "merged_at": stamp(merged),
            "merge_commit_sha": COMMIT}


def evidence_steps(when=DUE - 900):
    return [http(b"synthetic declaration\n", when=when, contains="contents/"),
            http([{"number": 71, "base": {"ref": "main"}, "merged_at": stamp(MERGE + 1),
                   "merge_commit_sha": OTHER}], when=when, contains="/pulls"),
            http({"status": "ahead"}, when=when, contains="compare/")]


def graph_comment(cid=1, **changes):
    base = {"id": f"node-{cid}", "fullDatabaseId": str(cid), "author": {"login": LOGIN},
            "createdAt": stamp(DUE - 900), "lastEditedAt": None,
            "includesCreatedEdit": False, "body": body(),
            "userContentEdits": {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": []}}
    base.update(changes)
    return base


def page(nodes, more=False, cursor=None):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": more, "endCursor": cursor}}


def graph(nodes, more=False, cursor=None):
    return {"data": {"repository": {"issue": {"comments": page(nodes, more, cursor)}}}}


@pytest.mark.parametrize("line", ["round 5", "round 5\r", "round 5\nround 5"])
def test_t1_exact_and_equal_rounds(dr, line):
    parsed = dr.parse_body("Follow-up draw: first post\n" + line + "\nrun_commit " + COMMIT)
    assert parsed["round"] == 5
    assert parsed["run_commit"] == COMMIT
    assert not parsed["reason"]


@pytest.mark.parametrize("line", [" round 5", "round 5 ", "Round 5", "round 05", "round +5",
                                  "round 5.0", "round ٥", "> round 5", "round 5\rx", "round 0"])
def test_t1_invalid_rounds(dr, line):
    parsed = dr.parse_body("Follow-up draw: first post\n" + line + "\nrun_commit " + COMMIT)
    assert parsed["round"] is None
    assert parsed["reason"]


@pytest.mark.parametrize("commit", ["A" * 40, "a" * 39, "a" * 41])
def test_t1_invalid_commits(dr, commit):
    assert dr.parse_body(body(commit=commit))["run_commit"] is None


def test_t1_conflicts_first_line_and_identity(dr):
    assert dr.parse_body(body(tail="round 1002"))["round"] is None
    assert dr.parse_body(body(tail="run_commit " + OTHER))["run_commit"] is None
    assert dr.parse_body(body().replace("first post\n", "first post \n"))["kind"] is None
    text = body(tail="\n".join(name + " frozen" for name in dr.IDENTITY_FIELDS))
    parsed = dr.parse_body(text)
    assert len(parsed["values"]) == 8
    assert all(parsed["values"][name] == "frozen" for name in dr.IDENTITY_FIELDS)
    assert not parsed["reason"]
    assert dr.parse_body(body(tail="<!-- hidden marker -->"))["run_commit"] == COMMIT


@pytest.mark.parametrize("reverse", [False, True])
def test_t2_created_revision(dr, reverse):
    edits = [{"editedAt": stamp(DUE - 800), "deletedAt": None, "diff": body(n=N + 1)},
             {"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}]
    c = comment(text="changed", lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                edits=edits[::-1] if reverse else edits)
    assert dr.candidates(records([c]))[0]["body"] == body()
    c["edits"][1 if not reverse else 0]["deletedAt"] = stamp(DUE - 700)
    assert dr.candidates(records([c]))[0]["body"] is None


def test_t2_first_sight_union_and_noncandidates(dr):
    c = comment(lastEditedAt=stamp(DUE - 800), includesCreatedEdit=False)
    rs = [rec("declaration", declaration(), 1), rec("post", {k: comment()[k] for k in ("id", "author", "created_at", "body")}, 2), rec("read", [c], 3),
          rec("read", [], 4)]
    assert dr.candidates(rs)[0]["body"] == body()
    rs = records([c, comment(cid=2, author="synthetic-other"), comment(cid=3, when=MERGE)])
    assert len(dr.candidates(rs)) == 1
    assert dr.candidates(rs)[0]["body"] is None
    assert dr.candidates(records([comment()]))[0]["body"] == body()


def test_t3_numeric_order_and_normalization(dr):
    rs = records([comment(1000000000), comment(999999999)])
    assert [c["id"] for c in dr.candidates(rs)] == [999999999, 1000000000]
    assert dr.normalize_comment(graph_comment(1000000000))["id"] == 1000000000
    rs.insert(2, rec("post", comment(1000000000, text="later"), 4))
    assert len(dr.candidates(rs)) == 2


@pytest.mark.parametrize("change,reason", [({}, "passed"),
    ({"content": {"status": 200, "sha256": "0" * 64, "length": 22}}, "declaration differs"),
    ({"content": {"status": 200, "sha256": declaration()["sha256"], "length": 999}}, "declaration differs"),
    ({"pulls": []}, "no qualifying pull request")])
def test_t4_commitment(dr, change, reason):
    ev = evidence(**change)
    result = dr.commitment_test(comment(), ev, declaration())
    assert result["reason"] == reason
    assert result["passed"] == (reason == "passed")


@pytest.mark.parametrize("field,value", [("base", "branch"), ("compare", "behind"),
                                         ("compare", "diverged"), ("merged_at", None)])
def test_t4_nonqualifying_pull(dr, field, value):
    ev = evidence()
    ev["pulls"][0][field] = value
    assert not dr.commitment_test(comment(), ev, declaration())["passed"]


@pytest.mark.parametrize("offset,passes", [(0, False), (-1, True)])
def test_t4_merge_second(dr, offset, passes):
    result = dr.commitment_test(comment(), evidence(DUE - 900 + offset), declaration())
    assert result["passed"] is passes


@pytest.mark.parametrize("status,message,refusal", [(404, "missing", False),
    (422, "No commit found for reference", False), (500, SENTINEL, True),
    (403, "rate limit exceeded " + SENTINEL, True), (429, SENTINEL, True),
    (422, "other failure", True)])
def test_t4_http_failures(h, status, message, refusal):
    h.init()
    h.save("read", [comment()])
    before = h.snapshot()
    h.queue([http({"message": message}, status=status, exit=1), *evidence_steps()[1:]])
    h.run("evaluate", code=2 if refusal else 1)
    if refusal:
        assert h.snapshot() == before
    else:
        assert any(r["kind"] == "test" for r in h.dr.load_records(h.state))


def test_t4_timeout_records_nothing(h, monkeypatch):
    h.init()
    h.save("read", [comment()])
    before = h.snapshot()

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 60
        raise subprocess.TimeoutExpired("synthetic", 60)

    monkeypatch.setattr(h.dr.subprocess, "run", timeout)
    with pytest.raises(h.dr.Refused):
        h.dr.evaluate_saved(h.state)
    assert h.snapshot() == before


def test_t4_saved_test_recheck_and_no_record_changes(h):
    h.init()
    h.save("read", [comment()])
    h.queue(evidence_steps())
    assert h.run("evaluate").startswith("counted 1 round")
    before = h.snapshot()
    assert len(h.calls()) == 3
    h.queue([http(b"different")])
    h.run("evaluate")
    assert len(h.calls()) == 3
    h.queue([http(b"different"), *evidence_steps()[1:]])
    assert "changed 1 passed true false" in h.run("evaluate", "--recheck")
    assert h.snapshot() == before


def test_t4_earliest_pull_and_page_limit(h):
    ev = evidence()
    ev["pulls"].append({**ev["pulls"][0], "number": 72, "merged_at": stamp(MERGE)})
    assert h.dr.commitment_test(comment(), ev, declaration())["pull_request"] == 72
    h.init()
    h.save("read", [comment()])
    h.queue([evidence_steps()[0], http([{"number": n, "base": {"ref": "other"}, "merged_at": None,
                                            "merge_commit_sha": None} for n in range(100)])])
    before = h.snapshot()
    h.run("evaluate", code=2)
    assert h.snapshot() == before


@pytest.mark.parametrize("offset,code", [(-600, 0), (-599, 1)])
def test_t5_deadline(dr, offset, code):
    result = dr.evaluate_records(records([comment(when=DUE + offset)]))
    assert result["code"] == code


def test_t5_duplicate_void_none_and_later_values(dr):
    rs = records([comment(), comment(2, when=DUE - 899, text=body(commit=OTHER)),
                  comment(3, when=DUE - 898, text=body(n=N + 1))])
    # Both commits pass, but the earliest round retains its commit and values.
    rs.append(rec("evidence", {**evidence(), "commit": OTHER}, 4))
    assert dr.evaluate_records(rs)["counted"]["id"] == 1
    assert dr.publish_list(rs)[1]["reason"] == "same round as 1"
    rs.append(rec("void", {"round": N, "receipt_sha256": "0" * 64}, 5))
    assert dr.evaluate_records(rs)["counted"]["id"] == 3
    assert dr.evaluate_records(records())["code"] == 1
    with pytest.raises(dr.Refused):
        dr.require_counted(dr.evaluate_records(records()))


@pytest.mark.parametrize("when,has_counted,code", [(DUE - 901, True, 3),
    (DUE - 899, True, 0), (DUE - 901, False, 3)])
def test_t5_unrecoverable(dr, when, has_counted, code):
    bad = comment(2, when=when, lastEditedAt=stamp(when + 1))
    cs = [bad, comment()] if has_counted else [bad]
    assert dr.evaluate_records(records(cs))["code"] == code


@pytest.mark.parametrize("ahead,action", [(601, "kept"), (600, "new"), (3600, "kept"), (3601, "refused")])
def test_t6_saved_round(dr, ahead, action):
    t = DUE - ahead
    if action == "refused":
        with pytest.raises(dr.Refused):
            dr.choose_round(t, N)
    else:
        n, chosen = dr.choose_round(t, N)
        assert chosen == action
        if action == "new":
            assert dr.round_due(n) >= t + 900 > dr.round_due(n - 1)


def test_t6_new_round(dr, h, monkeypatch, capsys):
    n, action = dr.choose_round(DUE - 899, None)
    assert action == "new"
    assert dr.newest([rec("round", {"round": N}, 9), rec("round", {"round": N+1}, 2)], "round")["round"] == N
    assert dr.round_due(n) >= DUE + 1 > dr.round_due(n - 1)
    h.init()
    monkeypatch.setattr(dr, "machine_time", lambda: DUE - 899)
    h.queue([http({}, when=DUE - 899)])
    assert dr.main(["choose-round", "--state", str(h.state)]) == 0
    assert capsys.readouterr().out == f"round {n} due {dr.round_due(n)} new\n"
    assert dr.newest(dr.load_records(h.state), "round")["round"] == n
    h.queue([http({}, when=DUE - 899)])
    assert dr.main(["now", "--state", str(h.state)]) == 0
    assert capsys.readouterr().out == f"github {DUE - 899} skew 0\n"


@pytest.mark.parametrize("skew", [-61, -60, 60, 61])
def test_t7_clock(dr, skew):
    header = format_datetime(datetime.fromtimestamp(DUE, UTC), usegmt=True)
    if abs(skew) == 61:
        with pytest.raises(dr.Refused):
            dr.github_clock({"date": header}, DUE + skew)
    else:
        assert dr.github_clock({"date": header}, DUE + skew) == (DUE, skew)


def test_init_and_http_status_even_nonzero_exit(h):
    h.queue([http(pr(), exit=1), http(b"synthetic declaration\n")])
    assert h.run("init") == "initialized\n"
    assert all(c["args"][0] == "api" for c in h.calls())
    assert h.dr.load_records(h.state)[0]["data"] == declaration()
    assert all("-i" in call["args"] for call in h.calls())
    h.queue([http(pr()), http(b"synthetic declaration\n")])
    h.run("init")
    before = h.snapshot()
    h.queue([http(pr()), http(b"changed")])
    h.run("init", code=2)
    assert h.snapshot() == before


def test_init_unmerged_refuses(h):
    h.queue([http({**pr(), "merged": False}), http(b"synthetic declaration\n")])
    h.run("init", code=2)
    assert h.snapshot() == {}
    assert len(h.calls()) == 1


def test_read_paginates_comments_and_edits(h):
    h.init()
    c = graph_comment(1000000000, lastEditedAt=stamp(DUE - 800), includesCreatedEdit=True,
                      userContentEdits=page([], True, "edit-cursor"))
    edit = {"editedAt": stamp(DUE - 900), "deletedAt": None, "diff": body()}
    h.queue([http(graph([c], True, "issue-cursor")),
             http({"data": {"node": {"userContentEdits": page([edit])}}}),
             http(graph([graph_comment(999999999)]))])
    assert h.run("read") == "read 2\n"
    read = h.dr.load_records(h.state)[-1]
    assert read["kind"] == "read" and len(read["data"]) == 2
    assert read["data"][0]["id"] == 1000000000
    assert read["data"][0]["edits"] == [edit]
    calls = "\n".join(" ".join(c["args"]) for c in h.calls())
    assert "fullDatabaseId" in calls and "databaseId " not in calls
    assert "edit-cursor" in calls and "issue-cursor" in calls


@pytest.mark.parametrize("bad", [{"errors": [{"message": SENTINEL}], **graph([graph_comment()])},
    {"data": {"repository": {"issue": {"comments": page([], True, None)}}}},
    {"data": {"repository": {"issue": None}}}])
def test_read_incomplete_saves_nothing(h, bad):
    h.init()
    before = h.snapshot()
    h.queue([http(bad)])
    h.run("read", code=2)
    assert h.snapshot() == before


def test_read_failure_after_first_page_is_atomic(h):
    h.init()
    before = h.snapshot()
    h.queue([http(graph([graph_comment()], True, "next")), http({}, status=500)])
    h.run("read", code=2)
    assert h.snapshot() == before


@pytest.mark.parametrize("kind", ["second", "tasks", "stop"])
def test_t8_post_saved_response(h, kind):
    h.init()
    text = body(kind=kind, tail=SENTINEL)
    response = {"id": 17, "created_at": stamp(DUE - 800), "user": {"login": LOGIN}, "body": text}
    h.queue([http({"login": LOGIN}), http(response, status=201)])
    assert h.run("post", kind, h.file(text)) == f"posted 17 {stamp(DUE - 800)}\n"
    saved = h.dr.load_records(h.state)[-1]
    assert saved["kind"] == "post" and saved["data"]["body"] == text
    assert "-F" in h.calls()[-1]["args"]


def test_t8_post_saved_before_print(h, monkeypatch, capsys):
    h.init()
    text = body(kind="second")
    response = {"id": 17, "created_at": stamp(DUE - 800), "user": {"login": LOGIN}, "body": text}
    h.queue([http({"login": LOGIN}), http(response, status=201)])
    original = h.dr.append_record

    def save(*args, **kwargs):
        assert "posted" not in capsys.readouterr().out
        return original(*args, **kwargs)

    monkeypatch.setattr(h.dr, "append_record", save)
    assert h.dr.main(["post", "--state", str(h.state), "second", str(h.file(text))]) == 0
    assert "posted 17" in capsys.readouterr().out


@pytest.mark.parametrize("wrong_line", [False, True])
def test_t8_bad_login_or_line(h, wrong_line):
    h.init()
    text = "wrong\n" if wrong_line else body(kind="second")
    h.queue([http({"login": LOGIN if wrong_line else "synthetic-other"}),
             http({"id": 20, "created_at": stamp(DUE), "user": {"login": LOGIN}, "body": text}, status=201)])
    h.run("post", "second", h.file(text), code=2)
    assert not any("POST" in c["args"] for c in h.calls())
    if wrong_line:
        assert not h.calls()


@pytest.mark.parametrize("age,ahead,code", [(59, 900, 2), (60, 900, 0), (60, 600, 2)])
def test_t8_first_age_round_and_response_time(h, monkeypatch, age, ahead, code):
    h.init()
    h.save("round", {"round": N})
    t = DUE - ahead
    monkeypatch.setattr(h.dr, "machine_time", lambda: t)
    ev = evidence(t - age)
    if age == 60 and ahead == 900:
        for parsed, saved in [(h.dr.parse_body(body(n=N+1)), {"round": N}),
                              (h.dr.parse_body(body()), None),
                              (h.dr.parse_body("Follow-up draw: first post"), {"round": N}),
                              (h.dr.parse_body(f"Follow-up draw: first post\nround {N}"), {"round": N})]:
            with pytest.raises(h.dr.Refused):
                h.dr.validate_first(parsed, saved, t, ev, declaration())
    h.save("evidence", ev)
    response = {"id": 17, "created_at": stamp(t - age), "user": {"login": LOGIN}, "body": body()}
    h.queue([http({"login": LOGIN}), http({}, when=t), http(response, status=201)])
    result = h.dr.main(["post", "--state", str(h.state), "first", str(h.file(body()))])
    assert result == code
    if code == 0:
        tests = [r for r in h.dr.load_records(h.state) if r["kind"] == "test"]
        assert tests[-1]["data"]["passed"] is False
        assert tests[-1]["data"]["reason"] == "merge not before comment"
    else:
        assert not any("POST" in c["args"] for c in h.calls())


def beacon(n=N):
    signature = "ab" * 48
    return {"round": n, "signature": signature,
            "randomness": hashlib.sha256(bytes.fromhex(signature)).hexdigest()}


@pytest.mark.parametrize("variant", ["accepted", "down", "disagree", "extra", "wrong-round", "hash", "upper"])
def test_t9_beacon_variants(h, monkeypatch, variant, capsys):
    h.seed()
    original_run = h.dr.subprocess.run

    def checked_run(argv, **kwargs):
        if argv[0] in ("gh", "curl"):
            assert kwargs["timeout"] == (60 if argv[0] == "gh" else 30)
        return original_run(argv, **kwargs)

    monkeypatch.setattr(h.dr.subprocess, "run", checked_run)
    monkeypatch.setattr(h.dr, "machine_time", lambda: DUE + 1)
    valid = beacon()
    for invalid in [{**valid, "round": True}, {**valid, "signature": "abc"},
                    {**valid, "randomness": valid["randomness"].upper()}, []]:
        reason, accepted = h.dr.accept_beacon(1 if invalid == {**valid, "round": True} else N,
                                             h.dr.canonical(invalid), h.dr.canonical(invalid), DUE+1)
        assert accepted is None and reason != "accepted"
    left = beacon()
    right = beacon()
    exit_code = 0
    if variant == "down":
        exit_code = 7
    if variant == "disagree":
        right["signature"] = "cd" * 48
    if variant == "extra":
        left["extra"] = SENTINEL
        right = left
    if variant == "wrong-round":
        left = right = beacon(N + 1)
    if variant == "hash":
        left["randomness"] = "0" * 64
        right = left
    if variant == "upper":
        left["signature"] = left["signature"].upper()
        right = left
    h.queue([http({}, when=DUE + 1), relay(left, exit_code), relay(right), http({}, when=DUE + 1)])
    code = h.dr.main(["beacon", "--state", str(h.state), "--round", str(N)])
    output = capsys.readouterr()
    assert SENTINEL not in output.out + output.err
    assert code == (0 if variant == "accepted" else 1)
    files = list((h.state / "records").glob("*.body"))
    assert len(files) == 2
    if variant == "accepted":
        saved = [r for r in h.dr.load_records(h.state) if r["kind"] == "beacon"][-1]
        assert saved["data"] == beacon()
        p = next((h.state / "records").glob("*-beacon.json"))
        assert p.read_bytes() == (json.dumps(beacon(), sort_keys=True, separators=(",", ":")) + "\n").encode()
        assert output.out == f"accepted round {N}\n"
    else:
        assert output.out.startswith("not-accepted ")
    assert all(c["args"][:4] == ["--silent", "--show-error", "--max-time", "20"]
               for c in h.calls() if c["tool"] == "curl")


@pytest.mark.parametrize("offset,code", [(86399, 0), (86400, 3)])
def test_t9_after_read_cutoff(h, monkeypatch, offset, code, capsys):
    h.seed()
    times = iter([DUE, DUE + offset])
    monkeypatch.setattr(h.dr, "machine_time", lambda: next(times))
    h.queue([http({}, when=DUE), relay(beacon()), relay(beacon()), http({}, when=DUE + offset)])
    assert h.dr.main(["beacon", "--state", str(h.state), "--round", str(N)]) == code
    assert ("cutoff" in capsys.readouterr().out) == (code == 3)


@pytest.mark.parametrize("wrong_round", [False, True])
def test_t9_before_due_or_wrong_round(h, monkeypatch, wrong_round):
    h.seed()
    monkeypatch.setattr(h.dr, "machine_time", lambda: DUE - 1)
    h.queue([http({}, when=DUE - 1)])
    assert h.dr.main(["beacon", "--state", str(h.state), "--round",
                      str(N + int(wrong_round))]) == 2
    assert not any(c["tool"] == "curl" for c in h.calls())
    if wrong_round:
        assert not h.calls()


def test_t10_matching_and_ignored(h):
    expected = body(kind="second", tail="list_sha256 abc\ndraw_time xyz\nrandomness abc")
    h.seed([comment(), comment(2, when=DUE - 901, text=expected),
            comment(3, when=DUE - 899, text=expected, author="synthetic-other"),
            comment(4, when=DUE - 898, text=expected.replace(f"round {N}", f"round {N+1}")),
            comment(5, when=DUE - 897, text=expected.replace("abc", "def"))])
    h.save("read", [comment(7, when=DUE - 897, text=expected.replace("second post", "first post"))])
    h.run("match", "second", h.file(expected.replace("second post", "task lists")), code=2)
    h.run("match", "second", h.file(expected.replace(f"round {N}", f"round {N+1}")), code=2)
    assert h.run("match", "second", h.file(expected), code=1) == "differs 5\nnone\n"
    assert h.dr.load_records(h.state)[-1]["kind"] == "difference"
    h.save("read", [comment(6, when=DUE - 896, text=expected)])
    assert h.run("match", "second", h.file(expected)) == "differs 5\nmatched 6\n"


def test_t10_tasks_same_second_integer_id(h):
    expected = body(kind="tasks", tail="pack_hash xyz")
    h.seed([comment(10), comment(9, text=expected), comment(11, text=expected)])
    assert h.run("match", "tasks", h.file(expected)) == "matched 11\n"


def test_t11_list_all_reasons_and_canonical(h):
    cs = [comment(1, when=DUE - 1100, text=body(n=N - 1)),
          comment(2, when=DUE - 1000, text=body(tail="round 1002")),
          comment(3, when=DUE - 950, text=body(commit=OTHER)), comment(4),
          comment(5, when=DUE - 899), comment(6, when=DUE - 898, text=body(n=N + 1)),
          comment(7, when=DUE - 500, text=body(n=N + 2)),
          comment(8, when=DUE - 499, lastEditedAt=stamp(DUE - 400))]
    h.seed(cs)
    h.save("evidence", {**evidence(content={"status": 404}), "commit": OTHER})
    h.save("void", {"round": N - 1, "receipt_sha256": "0" * 64})
    output = h.run("publish-list")
    values = json.loads(output)
    assert output.encode() == (json.dumps(values, sort_keys=True, separators=(",", ":")) + "\n").encode()
    assert [v["reason"] for v in values] == ["void round",
        "not a commitment post: conflicting round", "failed: not found", "counted",
        "same round as 4", "after the counted post", "late", "unrecoverable"]
    assert values[3]["pull_request"] == 71
    assert values[3]["merged_at"] == stamp(MERGE + 1)


def test_t12_append_only_and_existing_name(h, monkeypatch):
    h.seed()
    before = h.snapshot()
    h.queue([])
    h.run("evaluate")
    h.run("publish-list")
    h.run("record-void", "--round", N, "--receipt-sha256", "bad", code=2)
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64)
    after = h.snapshot()
    assert all(after[name] == value for name, value in before.items())
    existing = next(iter(before))
    number = int(existing.split("-", 1)[0])
    kind = existing.split("-", 1)[1].split(".", 1)[0]
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, number, kind, {"wrong": True})
    assert h.snapshot() == after
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 0, "round", {})
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 99, "bad_kind", {})
    partial = h.state / "records" / "0099-round.json.partial"
    partial.write_bytes(b"unfinished")
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 99, "round", {})
    h.run("record-void", "--round", N, "--receipt-sha256", "0" * 64, code=2)

    def race(source, target):
        target.write_bytes(b"synthetic winner")
        raise FileExistsError("synthetic race")

    monkeypatch.setattr(h.dr.os, "link", race)
    with pytest.raises(h.dr.Refused):
        h.dr.write_record(h.state, 100, "round", {"round": N})
    assert (h.state / "records" / "0100-round.json").read_bytes() == b"synthetic winner"


def test_t12_counter_includes_raw_bodies(h):
    h.init()
    h.dr.append_record(h.state, "relay", b"raw", raw=True)
    h.save("round", {"round": N})
    assert sorted(h.snapshot()) == ["0001-declaration.json", "0002-relay.body", "0003-round.json"]


def test_t13_nothing_private_in_refusal(h):
    h.init()
    h.queue([http({"message": SENTINEL}, status=500)])
    h.run("read", code=2)
    h.run("post", "first", h.file(SENTINEL), code=2)


@pytest.mark.parametrize("command,args", [("now", []), ("read", []), ("evaluate", []),
    ("choose-round", []), ("post", ["stop", "missing"]), ("beacon", ["--round", str(N)]),
    ("match", ["second", "missing"]), ("record-void", ["--round", str(N), "--receipt-sha256", "0"*64]),
    ("publish-list", [])])
def test_t14_before_init(h, command, args):
    h.run(command, *args, code=2)
    assert not h.calls()


@pytest.mark.parametrize("command,args", [("init", []), ("now", []), ("read", []),
    ("choose-round", []), ("post", ["stop", "missing"]), ("beacon", ["--round", str(N)]),
    ("match", ["second", "missing"]), ("record-void", ["--round", str(N), "--receipt-sha256", "0"*64])])
def test_t14_after_blocked(h, command, args):
    h.seed([comment(lastEditedAt=stamp(DUE - 800))])
    h.run(command, *args, code=2)
    assert not h.calls()
    assert h.run("evaluate", code=3) == "blocked 1\n"
    assert json.loads(h.run("publish-list"))[0]["reason"] == "unrecoverable"
