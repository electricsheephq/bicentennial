"""Pure draw rules over saved records, with a small append-only command layer."""

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextvars import ContextVar
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

REPOSITORY = "repos/electricsheephq/bicentennial"
DECLARATION_PATH = "results/followup/DECLARATION.md"
MODULE_PATH = "results/followup/run/draw_record.py"
CHAIN = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
GENESIS = 1692803367
FIRST_LINES = {"first": "Follow-up draw: first post", "second": "Follow-up draw: second post",
               "tasks": "Follow-up draw: task lists", "stop": "Follow-up draw: stop"}
IDENTITY_FIELDS = ("registry_entry_sha256", "fresh_install_hash", "artifact_sha256",
                   "system_hash", "harness_hash", "route_table_hash")
RECORD_NAME = re.compile(r"([0-9]{6})-([a-z][a-z-]*)\.(json|body)\Z")
RUNTIME = ContextVar("runtime", default=None)


class Refused(Exception):
    """A fixed, public-safe refusal label."""


def parse_integer(text):
    if not re.fullmatch(r"[+-]?[0-9]{1,18}", text):
        raise Refused("invalid or overlong integer")
    return int(text)


def read_json(raw):
    return json.loads(raw, parse_int=parse_integer)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def seconds(value):
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def stamp(value):
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def round_due(number):
    if type(number) is not int or number < 1:
        raise Refused("invalid round")
    return GENESIS + (number - 1) * 3


def parse_body(body):
    """One value grammar; repeated names never give a valid post."""
    lines = [line[:-1] if line.endswith("\r") else line for line in body.split("\n")]
    kind = next((k for k, line in FIRST_LINES.items() if lines[0] == line), None)
    values, repeated = {}, False
    for line in lines:
        match = re.fullmatch(r"([a-z0-9_]+) ([^\s]+)", line)
        if match:
            name, value = match.groups()
            if name in values:
                repeated = True
            values[name] = value
    r = values.get("round", "")
    c = values.get("run_commit", "")
    number = int(r) if re.fullmatch(r"[1-9][0-9]{0,17}", r) else None
    commit = c.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", c) else None
    if commit is not None:
        values["run_commit"] = commit
    reason = ("repeated value name" if repeated else "missing round" if number is None else
              "missing commit" if commit is None else "")
    return {"kind": kind, "first_line": lines[0], "round": number, "run_commit": commit,
            "values": values, "repeated": repeated, "reason": reason}


def newest(records, kind):
    return next((r["data"] for r in sorted(records, key=lambda r: r["number"], reverse=True)
                 if r["kind"] == kind), None)


def initial_declaration(pr, content):
    if not pr["merged"] or not pr["merged_at"] or not pr["merged_by"] or not pr["merge_commit_sha"]:
        raise Refused("declaration pull request not merged")
    if not content:
        raise Refused("empty declaration")
    uid = pr["merged_by"]["id"]
    if type(uid) is not int:
        raise Refused("invalid merging account id")
    return {"merging_id": uid, "merging_login": pr["merged_by"]["login"], "merge_time": pr["merged_at"],
            "declaration_commit": pr["merge_commit_sha"],
            "sha256": hashlib.sha256(content).hexdigest(), "length": len(content)}


def github_clock(headers, machine_seconds):
    served = int(parsedate_to_datetime(headers["date"]).timestamp())
    skew = int(machine_seconds) - served
    if abs(skew) > 60:
        raise Refused("clock skew exceeds 60 seconds")
    return served, skew


def effective_time(github, machine):
    return max(github, int(machine))


def normalize_comment(node):
    author = node["author"]
    uid = author.get("databaseId") if author else None
    cid = node.get("fullDatabaseId")
    if isinstance(cid, str):
        cid = parse_integer(cid)
    if type(cid) is not int or (uid is not None and type(uid) is not int):
        raise Refused("invalid comment or author id")
    return {"id": cid, "author": uid, "created_at": node["createdAt"], "body": node["body"],
            "lastEditedAt": node["lastEditedAt"], "includesCreatedEdit": node["includesCreatedEdit"],
            "edits": node["userContentEdits"]["nodes"]}


def rest_comment(node):
    cid, uid = node["id"], node["user"]["id"]
    if type(cid) is not int or type(uid) is not int:
        raise Refused("invalid post response id")
    seconds(node["created_at"])
    if not isinstance(node["body"], str):
        raise Refused("invalid post response body")
    return {"id": cid, "author": uid, "created_at": node["created_at"], "body": node["body"]}


def created_body(comment, kind):
    if kind == "post" or comment["lastEditedAt"] is None:
        return comment["body"], None
    nodes = [e for e in comment["edits"] if e["editedAt"] == comment["created_at"]]
    if comment["includesCreatedEdit"] and len(nodes) == 1:
        node = nodes[0]
        if node["deletedAt"] is None:
            return node["diff"], None
        return None, node["deletedAt"]
    return None, None


def comment_set(records):
    """First sight fixes author and created body even for non-candidates."""
    seen = {}
    for record in sorted(records, key=lambda r: r["number"]):
        kind, data = record["kind"], record["data"]
        comments = data["comments"] if kind == "read" else [data] if kind == "post" else []
        for comment in comments:
            cid = int(comment["id"])
            if set(comment) == {"id"}:  # Exported other-author POST: id only.
                continue
            if cid in seen:
                continue
            body, deleted = created_body(comment, kind)
            seen[cid] = {"id": cid, "author": comment["author"], "created_at": comment["created_at"],
                         "body": body, "deletedAt": deleted,
                         "first_seen": data.get("github_time")}
    return sorted(seen.values(), key=comment_order)


def other_comment_ids(records):
    declaration = newest(records, "declaration")
    ids = {c["id"] for c in comment_set(records) if c["author"] != declaration["merging_id"]}
    for record in records:
        if record["kind"] == "read":
            ids.update(record["data"].get("other_comment_ids", []))
        elif record["kind"] == "post" and set(record["data"]) == {"id"}:
            ids.add(record["data"]["id"])
    return ids


def candidates(records):
    declaration = newest(records, "declaration")
    return [c for c in comment_set(records) if c["author"] == declaration["merging_id"]
            and seconds(c["created_at"]) > seconds(declaration["merge_time"])]


def comment_order(comment):
    return seconds(comment["created_at"]), int(comment["id"])


def commitment_test(comment, evidence, declaration):
    """None means this snapshot cannot decide this comment; rechecks are separate."""
    result = {"id": int(comment["id"]), "commit": evidence["commit"], "passed": False,
              "reason": "not found", "pull_request": None, "merged_at": None}
    if evidence["default_branch"] != "main" or evidence.get("default_branch_after", evidence["default_branch"]) != "main":
        return None
    content = evidence["content"]
    predates = evidence["github_time"] < seconds(comment["created_at"])
    if content["status"] != 200:
        result["reason"] = evidence.get("failure", "not found")
        return None if predates else result
    if content["sha256"] != declaration["sha256"] or content["length"] != declaration["length"]:
        result["reason"] = "declaration differs"
        return result
    qualifying = [p for p in evidence["pulls"] if p["base"] == "main" and p["merged_at"]
                  and p["merge_commit_sha"] and p.get("compare") in ("identical", "ahead")]
    earliest = min(qualifying, key=lambda p: (seconds(p["merged_at"]), p["number"])) if qualifying else None
    if earliest:
        result.update(pull_request=earliest["number"], merged_at=earliest["merged_at"])
    result["passed"] = not evidence.get("failure") and earliest is not None and seconds(earliest["merged_at"]) < seconds(comment["created_at"])
    result["reason"] = ("passed" if result["passed"] else evidence.get("failure") or
                        ("merge not before comment" if earliest else "no qualifying pull request"))
    if not result["passed"] and predates:
        return None
    return result


def saved_test(records, comment, parsed):
    ordered = sorted(records, key=lambda r: r["number"])
    for r in ordered:
        if r["kind"] == "test" and r["data"]["id"] == comment["id"]:
            return r["data"]
    for r in ordered:
        if r["kind"] == "evidence" and r["data"]["commit"] == parsed["run_commit"]:
            test = commitment_test(comment, r["data"], newest(records, "declaration"))
            if test is not None:
                return test
    return None


def first_row(comment, records, seen_rounds, counted):
    row = {k: comment[k] for k in ("id", "created_at", "deletedAt", "first_seen")}
    row.update(round=None, commit=None, pull_request=None, merged_at=None, on_time=None,
               test=None, test_reason=None, counted=False, values={})
    declaration = newest(records, "declaration")
    if (comment["author"] == declaration["merging_id"]
            and seconds(comment["created_at"]) <= seconds(declaration["merge_time"])):
        row["reason"] = "not after the merge"
        return row
    if comment["body"] is None:
        row["reason"] = "unrecoverable"
        return row
    p = parse_body(comment["body"])
    row.update(round=p["round"], commit=p["run_commit"],
               values={k: p["values"][k] for k in IDENTITY_FIELDS if k in p["values"]})
    if p["round"] is not None:
        row["on_time"] = seconds(comment["created_at"]) <= round_due(p["round"]) - 600
    if p["reason"]:
        row["reason"] = "not a commitment post: " + p["reason"]
    elif comment["author"] != declaration["merging_id"]:
        row["reason"] = "not the merging account"
    else:
        test = saved_test(records, comment, p)
        if test is None:
            row["reason"] = "untested: commitment evidence missing"
            return row
        row.update(test=test["passed"], test_reason=test["reason"],
                   pull_request=test["pull_request"], merged_at=test["merged_at"])
        n = p["round"]
        if not test["passed"]:
            row["reason"] = "failed: " + test["reason"]
        elif n in seen_rounds:
            row["reason"] = f"same round as {seen_rounds[n]}"
        else:
            seen_rounds[n] = comment["id"]
            if not row["on_time"]:
                row["reason"] = "late"
            elif any(r["kind"] == "void" and r["data"]["round"] == n for r in records):
                row["reason"] = "void round"
            elif counted:
                row["reason"] = "after the counted post"
            else:
                row.update(reason="counted", counted=True)
    return row


def task_list_comments(records, counted):
    """Task lists need a unique round and value names, never a run_commit."""
    result = []
    for c in candidates(records):
        if c["body"] is None:
            continue
        p = parse_body(c["body"])
        if (p["kind"] == "tasks" and not p["repeated"] and p["round"] == counted["round"]
                and seconds(c["created_at"]) >= round_due(counted["round"])):
            result.append(c)
    return result


def stopped_comment(records, counted):
    if counted is None:
        return None
    tasks = task_list_comments(records, counted)
    for c in candidates(records):
        if c["body"] is not None and parse_body(c["body"])["kind"] == "stop":
            if seconds(c["created_at"]) >= round_due(counted["round"]) and not any(
                    comment_order(task) < comment_order(c) for task in tasks):
                return c["id"]
    return None


def evaluate_records(records):
    """Stop at the first counted post; later comments cannot affect its evidence."""
    rows, seen = [], {}
    counted = None
    for c in candidates(records):
        if c["body"] is None or parse_body(c["body"])["kind"] != "first":
            continue
        row = first_row(c, records, seen, counted)
        rows.append(row)
        if row["reason"].startswith("untested:"):
            break
        if row["counted"]:
            counted = {**row, "values": parse_body(c["body"])["values"]}
            break
    stopped = stopped_comment(records, counted)
    return {"code": 14 if stopped is not None else 0 if counted else 10,
            "counted": counted, "stopped": stopped, "rows": rows}


def publish_list(records, untested=None):
    rows, markers, seen, counted = [], [], {}, None
    undecided = False
    declaration = newest(records, "declaration")
    matches = {}
    for record in records:
        if record["kind"] == "match":
            matches[record["data"]["kind"], record["data"]["round"]] = record["data"]
    for c in comment_set(records):
        p = parse_body(c["body"]) if c["body"] is not None else None
        if c["author"] == declaration["merging_id"] and (p is None or p["kind"] == "first"):
            row = first_row(c, records, seen, counted)
            if untested and c["id"] in untested and row["reason"].startswith("untested:"):
                row["reason"] = "untested: " + untested[c["id"]]
            if undecided:
                row.update(counted=False, reason="undecided: an earlier post is untested")
            undecided = undecided or row["reason"].startswith("untested:")
            rows.append(row)
            if row["counted"]:
                counted = row
        elif c["author"] == declaration["merging_id"] and p and p["first_line"].startswith("Follow-up draw:"):
            entry = {"id": c["id"], "created_at": c["created_at"], "first_line": p["first_line"],
                     "after_merge": seconds(c["created_at"]) > seconds(declaration["merge_time"])}
            if p["kind"] in ("second", "tasks"):
                match = matches.get((p["kind"], p["round"]), {})
                entry["match"] = ("matched" if c["id"] in match.get("matches", []) else
                                  "differs" if c["id"] in match.get("differences", []) else "unmatched")
            markers.append(entry)
    return {"first_posts": rows, "markers": markers,
            "other_comments": len(other_comment_ids(records))}


def choose_round(t, saved):
    if saved is not None:
        ahead = round_due(saved) - t
        if ahead > 3600:
            raise Refused("saved round more than 3600 seconds ahead")
        if ahead > 600:
            return saved, "kept"
    return max(1, (t + 900 - GENESIS + 2) // 3 + 1), "new"


def validate_first(parsed, saved_round, t, evidence, declaration):
    if parsed["reason"]:
        raise Refused("first post lacks unambiguous round or commit")
    if saved_round is None or parsed["round"] != saved_round["round"]:
        raise Refused("first post does not use saved round")
    if round_due(parsed["round"]) - t <= 600:
        raise Refused("first post round due too soon")
    test = commitment_test({"id": 0, "created_at": stamp(t)}, evidence, declaration)
    if test is None or not test["passed"] or seconds(test["merged_at"]) > t - 60:
        raise Refused("first post commit not merged at least 60 seconds ago")


def accept_beacon(number, left, right, t=None):
    if t is not None and t >= round_due(number) + 86400:
        return "cutoff", None
    try:
        a, b = read_json(left), read_json(right)
        if canonical(a) != canonical(b):
            return "relay disagreement", None
        if not isinstance(a, dict) or set(a) != {"round", "randomness", "signature"}:
            return "beacon fields", None
        if type(a["round"]) is not int or a["round"] != number:
            return "wrong round", None
        if not isinstance(a["signature"], str) or not re.fullmatch(r"(?:[0-9a-f]{2})+", a["signature"]):
            return "signature format", None
        if not isinstance(a["randomness"], str) or not re.fullmatch(r"[0-9a-f]{64}", a["randomness"]):
            return "randomness format", None
        if hashlib.sha256(bytes.fromhex(a["signature"])).hexdigest() != a["randomness"]:
            return "randomness hash", None
        return "accepted", a
    except (ValueError, TypeError, UnicodeError):
        return "relay JSON", None


def matching_comments(records, kind, expected, counted):
    if expected["kind"] != kind or expected["round"] != counted["round"] or expected["repeated"]:
        raise Refused("match file has wrong kind, round or repeated value")
    matches, differences = [], []
    for c in candidates(records):
        if c["body"] is None or comment_order(c) <= comment_order(counted):
            continue
        parsed = parse_body(c["body"])
        if parsed["kind"] != kind or parsed["round"] != counted["round"]:
            continue
        if not parsed["repeated"] and parsed["values"] == expected["values"]:
            matches.append(c["id"])
        else:
            differences.append(c["id"])
    return matches, differences


def first_unknown_pending(records, github_time, timeout):
    unknowns = [r for r in records if r["kind"] == "post-unknown" and r["data"]["kind"] == "first"]
    latest = max(unknowns, key=lambda r: r["number"])["data"] if unknowns else None
    return latest is not None and github_time < latest["github_time"] + timeout + 60


def stop_admission(records, counted, reason, failure_hash, t):
    n = counted["round"]
    if task_list_comments(records, counted):
        raise Refused("task lists already posted")
    if t < round_due(n):
        raise Refused("stop before round due")
    accepted = any(r["kind"] == "beacon" and r["data"]["round"] == n for r in records)
    if reason == "beacon":
        attempts = [r for r in records if r["kind"] == "beacon-attempt" and r["data"]["round"] == n]
        latest = max(attempts, key=lambda r: r["number"])["data"] if attempts else None
        if accepted or latest is None or latest["outcome"] != "cutoff" or t < round_due(n) + 86400:
            raise Refused("beacon stop conditions not met")
    elif reason == "build":
        if not accepted or not failure_hash or not re.fullmatch(r"[0-9a-f]{64}", failure_hash):
            raise Refused("build stop needs beacon and failure hash")
    else:
        raise Refused("stop reason required")


# Thin I/O: all remote calls use these two subprocess wrappers.
def load_records(state):
    folder = Path(state) / "records"
    result = []
    if folder.exists():
        for path in folder.iterdir():
            match = RECORD_NAME.fullmatch(path.name)
            if match and match[3] == "json":
                result.append({"number": int(match[1]), "kind": match[2], "data": read_json(path.read_bytes())})
    return sorted(result, key=lambda r: r["number"])


def sync_file(fd):
    os.fsync(fd)
    if hasattr(fcntl, "F_FULLFSYNC"):
        fcntl.fcntl(fd, fcntl.F_FULLFSYNC)


def write_record(state, number, kind, data, raw=False):
    if not re.fullmatch(r"[a-z][a-z-]*", kind) or not 1 <= number <= 999999:
        raise Refused("invalid record name")
    folder = Path(state) / "records"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{number:06d}-{kind}.{'body' if raw else 'json'}"
    partial = target.with_name(target.name + ".partial")
    if target.exists() or partial.exists():
        raise Refused("record name exists")
    with partial.open("xb") as out:
        out.write(data if raw else canonical(data))
        out.flush()
        sync_file(out.fileno())
    try:
        os.link(partial, target)
    except FileExistsError as error:
        raise Refused("record name exists") from error
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    return target


def append_record(state, kind, data, raw=False):
    folder = Path(state) / "records"
    numbers = [int(match[1]) for path in folder.iterdir()
               if (match := re.match(r"^(\d{6})-", path.name))] if folder.exists() else []
    return write_record(state, max(numbers, default=0) + 1, kind, data, raw)


def parse_http(raw):
    parts = re.split(br"\r?\n\r?\n", raw, maxsplit=1)
    if len(parts) != 2:
        raise Refused("missing HTTP header block")
    block, body = parts
    lines = block.splitlines()
    match = re.fullmatch(br"HTTP/\S+ ([0-9]{3})(?: .*)?", lines[0])
    if not match:
        raise Refused("missing HTTP status")
    headers = {}
    for line in lines[1:]:
        name, value = line.split(b":", 1)
        headers[name.decode("ascii").lower()] = value.strip().decode("ascii")
    return {"status": int(match[1]), "headers": headers, "body": body}


def tool_environment():
    return {k: v for k, v in os.environ.items() if k in ("PATH", "HOME")}


def gh(*args):
    args = list(args)
    if args[:1] == ["api"] and "-i" not in args:
        args.insert(1, "-i")
    runtime = RUNTIME.get()
    timeout = runtime["gh_timeout"] if runtime else 60
    try:
        response = subprocess.run(["gh", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=timeout, check=False, env=tool_environment())
    except subprocess.TimeoutExpired as error:
        raise Refused("GitHub timeout") from error
    except OSError as error:
        raise Refused("GitHub tool unavailable") from error
    return parse_http(response.stdout)


def curl(url):
    try:
        response = subprocess.run(["curl", "-q", "--silent", "--show-error", "--max-time", "20", url],
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  timeout=30, check=False, env=tool_environment())
        return response.returncode == 0, response.stdout
    except subprocess.TimeoutExpired as error:
        raise Refused("relay timeout") from error
    except OSError as error:
        raise Refused("relay tool unavailable") from error


def response_json(response):
    if response["status"] not in (200, 201):
        raise Refused("GitHub HTTP status")
    value = read_json(response["body"])
    if isinstance(value, dict) and "errors" in value:
        raise Refused("GitHub GraphQL errors")
    return value


def machine_time():
    return time.time()


def now():
    response = gh("api", "rate_limit")
    if response["status"] != 200:
        raise Refused("GitHub time unavailable")
    runtime = RUNTIME.get()
    machine = (runtime["clock"] if runtime else machine_time)()
    served, skew = github_clock(response["headers"], machine)
    return served, skew, effective_time(served, machine)


EDIT_FIELDS = "userContentEdits(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{editedAt deletedAt diff}}"
COMMENT_FIELDS = ("id fullDatabaseId author{login ... on User { databaseId }} createdAt lastEditedAt includesCreatedEdit body "
                  "userContentEdits(first:100){pageInfo{hasNextPage endCursor} nodes{editedAt deletedAt diff}}")
COMMENTS_QUERY = ("query($cursor:String){repository(owner:\"electricsheephq\",name:\"bicentennial\"){"
                  "issue(number:394){comments(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{"
                  + COMMENT_FIELDS + "}}}}}")
EDITS_QUERY = "query($id:ID!,$c:String){node(id:$id){... on IssueComment{" + EDIT_FIELDS + "}}}"


def graph_query(query, **variables):
    args = ["api", "graphql", "-f", "query=" + query]
    for name, value in variables.items():
        if value is not None:
            args.extend(["-f", name + "=" + value])
    return response_json(gh(*args))


def page_data(page, seen):
    nodes, info = page["nodes"], page["pageInfo"]
    if not isinstance(nodes, list) or type(info["hasNextPage"]) is not bool:
        raise Refused("missing GraphQL page")
    cursor = info["endCursor"]
    if info["hasNextPage"]:
        if not cursor or cursor in seen:
            raise Refused("missing GraphQL page")
        seen.add(cursor)
        return nodes, cursor
    return nodes, None


def read_issue(state):
    github, _, _ = now()
    comments, cursor, seen = [], None, set()
    while True:
        result = graph_query(COMMENTS_QUERY, cursor=cursor)
        nodes, cursor = page_data(result["data"]["repository"]["issue"]["comments"], seen)
        for node in nodes:
            edits, ec = page_data(node["userContentEdits"], edit_seen := set())
            edits = list(edits)
            while ec is not None:
                result = graph_query(EDITS_QUERY, id=node["id"], c=ec)
                more, ec = page_data(result["data"]["node"]["userContentEdits"], edit_seen)
                edits.extend(more)
            node["userContentEdits"]["nodes"] = edits
            comments.append(normalize_comment(node))
        if cursor is None:
            break
    append_record(state, "read", {"github_time": github, "comments": comments})
    return len(comments), github


def evidence_status(response):
    status = response["status"]
    if status == 404:
        return "not found"
    if status == 422:
        value = read_json(response["body"])
        if value.get("message", "").startswith("No commit found for SHA"):
            return "no commit found"
    if status != 200:
        raise Refused("commitment evidence unavailable")
    return None


def fetch_evidence(commit):
    github, _, _ = now()
    repo = response_json(gh("api", REPOSITORY))
    raw = gh("api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json",
             f"{REPOSITORY}/contents/{DECLARATION_PATH}?ref={commit}")
    failure = evidence_status(raw)
    evidence = {"commit": commit, "github_time": github, "default_branch": repo["default_branch"],
                "content": {"status": raw["status"], "sha256": hashlib.sha256(raw["body"]).hexdigest(),
                            "length": len(raw["body"])}, "pulls": []}
    if failure:
        return {**evidence, "failure": failure}
    response = gh("api", f"{REPOSITORY}/commits/{commit}/pulls?per_page=100")
    evidence["default_branch_after"] = response_json(gh("api", REPOSITORY))["default_branch"]
    failure = evidence_status(response)
    if failure:
        return {**evidence, "failure": failure}
    pulls = response_json(response)
    if len(pulls) >= 100:
        raise Refused("commit pull request page is full")
    for pull in pulls:
        saved = {"number": pull["number"], "base": pull["base"]["ref"],
                 "merged_at": pull["merged_at"], "merge_commit_sha": pull["merge_commit_sha"]}
        if saved["base"] == "main" and saved["merged_at"] and saved["merge_commit_sha"]:
            response = gh("api", f"{REPOSITORY}/compare/{commit}...{saved['merge_commit_sha']}")
            failure = evidence_status(response)
            if failure:
                return {**evidence, "failure": failure}
            saved["compare"] = response_json(response)["status"]
        evidence["pulls"].append(saved)
    return evidence


def ensure_test(records, comment, fetch=True):
    parsed = parse_body(comment["body"])
    test = saved_test(records, comment, parsed)
    if test is None and fetch:
        evidence = fetch_evidence(parsed["run_commit"])
        yield "evidence", evidence
        test = commitment_test(comment, evidence, newest(records, "declaration"))
        if test is None:
            raise Refused(f"post {comment['id']} undecided")
    if test is not None and not any(r["kind"] == "test" and r["data"]["id"] == comment["id"] for r in records):
        yield "test", test


def evaluate_saved(state, recheck=False):
    records = load_records(state)
    pending, changes = [], []
    for comment in candidates(records):
        if comment["body"] is None:
            continue
        parsed = parse_body(comment["body"])
        if parsed["kind"] != "first" or parsed["reason"]:
            continue
        if recheck:
            old = next((r["data"] for r in records if r["kind"] == "test" and r["data"]["id"] == comment["id"]), None)
            if old is None:
                continue
            ev = fetch_evidence(parsed["run_commit"])
            fresh = commitment_test(comment, ev, newest(records, "declaration"))
            pending.append(("recheck", {"id": comment["id"], "evidence": ev, "result": fresh}))
            differences = [k for k in ("passed", "reason", "pull_request", "merged_at")
                           if fresh is not None and old[k] != fresh[k]]
            changes.extend(f"changed {comment['id']} {k} {json.dumps(old[k])} {json.dumps(fresh[k])}"
                           for k in differences)
            if fresh is None:
                changes.append(f"undecided {comment['id']}")
            elif not differences:
                changes.append(f"unchanged {comment['id']}")
        else:
            additions = ensure_test(records, comment)
            for kind, data in additions:
                append_record(state, kind, data)
                records = load_records(state)
        result = evaluate_records(records)
        if not recheck and result["counted"] is not None and result["counted"]["id"] == comment["id"]:
            break
    for kind, data in pending:
        append_record(state, kind, data)
    return changes if recheck else evaluate_records(records)


def evaluation_line(result):
    if result["stopped"] is not None:
        return f"stopped {result['stopped']}"
    counted = result["counted"]
    if counted is None:
        return "none"
    return (f"counted {counted['id']} round {counted['round']} due {round_due(counted['round'])} "
            f"commit {counted['commit']}")


def require_counted(result, number=None):
    if result["code"] == 14:
        raise Refused("draw stopped")
    if result["counted"] is None:
        raise Refused("no counted draw")
    counted = result["counted"]
    if number is not None and counted["round"] != number:
        raise Refused("round is not counted")
    return counted


def reading_module(commit):
    try:
        raw = gh("api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json",
                 f"{REPOSITORY}/contents/{MODULE_PATH}?ref={commit}")
        if raw["status"] == 200:
            return "same" if raw["body"] == Path(__file__).read_bytes() else f"differs at {commit}"
    except Exception:
        pass
    return f"unavailable at {commit}"


def verify_reading(commit):
    status = reading_module(commit)
    if status != "same":
        raise Refused("reading module " + status)


def acting_counted(state, number=None):
    counted = require_counted(evaluate_saved(state), number)
    verify_reading(counted["commit"])
    return counted


def post(state, kind, filename, records, reason=None, failure_hash=None):
    if evaluate_records(records)["code"] == 14:
        raise Refused("draw stopped")
    text = Path(filename).read_bytes().decode("utf-8")
    parsed = parse_body(text)
    if parsed["kind"] != kind:
        raise Refused("post first line does not match kind")
    counted = acting_counted(state) if kind != "first" else None
    user = response_json(gh("api", "user"))
    declaration = newest(records, "declaration")
    if type(user["id"]) is not int or user["id"] != declaration["merging_id"]:
        raise Refused("posting account differs")
    evidence = None
    read_time = None
    if kind == "first":
        _, read_time = read_issue(state)
        records = load_records(state)
        if first_unknown_pending(records, read_time, RUNTIME.get()["gh_timeout"]):
            raise Refused("post outcome unknown")
        result = evaluate_saved(state)
        if result["code"] == 14:
            raise Refused("draw stopped")
        if result["counted"] is not None:
            verify_reading(result["counted"]["commit"])
            raise Refused("counted draw already exists")
        records = load_records(state)
        blocked = [c["id"] for c in candidates(records) if c["body"] is None]
        if blocked:
            return "blocked " + " ".join(map(str, blocked)), 13
        if parsed["reason"]:
            raise Refused("first post lacks unambiguous round or commit")
        verify_reading(parsed["run_commit"])
    records = load_records(state)
    if kind == "first":
        evidence = fetch_evidence(parsed["run_commit"])
        append_record(state, "evidence", evidence)
    github, _, t = now()
    if kind == "first":
        if github - read_time > 60:
            raise Refused("pre-post read older than 60 seconds")
        validate_first(parsed, newest(records, "round"), t, evidence, declaration)
    elif kind == "stop":
        stop_admission(records, counted, reason, failure_hash, github)
    known = [c["id"] for c in comment_set(records)]
    try:
        raw = gh("api", "-X", "POST", f"{REPOSITORY}/issues/394/comments", "-f", "body=" + text)
        if raw["status"] != 201:
            raise Refused("post response not 201")
        saved = rest_comment(response_json(raw))
    except Exception as error:
        append_record(state, "post-unknown", {"kind": kind, "github_time": github, "known_ids": known})
        raise Refused("post outcome unknown") from error
    saved["github_time"] = github
    if kind == "stop":
        saved["stop_reason"] = reason
        if reason == "build":
            saved["failure_sha256"] = failure_hash
    append_record(state, "post", saved)
    try:
        if kind == "first":
            test = commitment_test(saved, evidence, declaration)
            if test is not None:
                append_record(state, "test", test)
        read_issue(state)
    except Exception:
        print("read-back failed", file=sys.stderr)
    if kind == "first":
        try:
            evaluate_saved(state)
        except Exception:
            print("evaluation failed", file=sys.stderr)
    return f"posted {saved['id']} {saved['created_at']}", 0


def relay_attempt(state, number, rehearsal=False):
    before, _, _ = now()
    if not rehearsal and before < round_due(number):
        raise Refused("round not due")
    names, bodies, oks = [], [], []
    for host, label in (("api.drand.sh", "relay-primary"), ("drand.cloudflare.com", "relay-secondary")):
        ok, raw = curl(f"https://{host}/{CHAIN}/public/{number}")
        names.append(append_record(state, label, raw, raw=True).name)
        bodies.append(raw)
        oks.append(ok)
    after, skew, _ = now()
    reason, value = accept_beacon(number, *bodies, None if rehearsal else after)
    if reason != "cutoff" and not all(oks):
        reason, value = "relay unavailable", None
    outcome = "accepted" if value else "cutoff" if reason == "cutoff" else "not-accepted"
    if not rehearsal:
        append_record(state, "beacon-attempt", {"round": number, "outcome": outcome, "reason": reason,
                      "github_before": before, "github_after": after, "machine_after": after + skew, "raw_bodies": names})
        if value is not None:
            append_record(state, "beacon", value)
    return reason, value


def write_beacon_output(out, value):
    """Link accepted bytes without replacement; an existing file must be identical."""
    target = Path(out)
    raw = canonical(value)
    if target.exists():
        if target.read_bytes() != raw:
            raise Refused("beacon output differs")
        return
    # Each partial is exclusive and retained, just like the record writer's partials.
    number = 0
    while True:
        partial = target.with_name(target.name + f".{number}.partial")
        try:
            output = partial.open("xb")
            break
        except FileExistsError:
            number += 1
    with output:
        output.write(raw)
        output.flush()
        sync_file(output.fileno())
    try:
        os.link(partial, target)
    except FileExistsError as error:
        if target.read_bytes() != raw:
            raise Refused("beacon output differs") from error
    fd = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def beacon_attempt(state, number, out):
    # A saved acceptance is final; do not even read the module or a clock again.
    records = load_records(state)
    result = evaluate_records(records)
    if result["code"] == 14:
        raise Refused("draw stopped")
    accepted = next((r["data"] for r in records if r["kind"] == "beacon" and r["data"]["round"] == number), None)
    receipts = [r["data"] for r in records if r["kind"] == "beacon-attempt"
                and r["data"]["round"] == number and r["data"]["outcome"] == "accepted"]
    if receipts:
        receipt = receipts[0]
        folder = Path(state) / "records"
        raw_files = {p.name: p for p in folder.iterdir()
                     if (m := RECORD_NAME.fullmatch(p.name)) and m[3] == "body"}
        bodies = [raw_files[name].read_bytes() for name in receipt["raw_bodies"]]
        _, recovered = accept_beacon(number, *bodies, receipt["github_after"])
        if recovered is None or (accepted is not None and canonical(accepted) != canonical(recovered)):
            raise Refused("beacon timing receipt invalid")
        if accepted is None:
            append_record(state, "beacon", recovered)
        accepted = recovered
    if accepted is not None:
        if not receipts:
            raise Refused("beacon timing receipt missing")
        write_beacon_output(out, accepted)
        return f"accepted round {number}", 0
    acting_counted(state, number)
    reason, value = relay_attempt(state, number)
    if value:
        write_beacon_output(out, value)
        return f"accepted round {number}", 0
    return (f"cutoff round {number}", 13) if reason == "cutoff" else ("not-accepted " + reason, 10)


def rehearsal(state, fixture):
    expected = read_json(Path(fixture).read_bytes())
    reason, checked = accept_beacon(expected["round"], canonical(expected), canonical(expected))
    if checked is None:
        raise Refused("invalid rehearsal fixture")
    for attempt in range(1, 4):
        reason, value = relay_attempt(state, expected["round"], rehearsal=True)
        if value is not None and value != expected:
            reason = "fixture differs"
        if value == expected:
            break
        if attempt < 3:
            RUNTIME.get()["sleep"](30)
    passed = value == expected
    append_record(state, "rehearsal-beacon", {"outcome": "pass" if passed else "fail", "attempt_count": attempt,
                                             "reason": reason})
    return ("rehearsal-beacon pass", 0) if passed else ("rehearsal-beacon fail " + reason, 10)


def prepare_list(state):
    failures = {}
    records = load_records(state)
    for c in candidates(records):
        if c["body"] is None:
            continue
        p = parse_body(c["body"])
        if p["kind"] != "first" or p["reason"]:
            continue
        try:
            for kind, data in ensure_test(records, c):
                append_record(state, kind, data)
        except Refused as exc:
            failures[c["id"]] = ("undecided" if str(exc).endswith("undecided") else
                                  "commitment evidence unavailable")
        except Exception:
            failures[c["id"]] = "commitment evidence unavailable"
        finally:
            records = load_records(state)
    result = evaluate_records(records)
    status = reading_module(result["counted"]["commit"]) if result["counted"] else "none"
    return {**publish_list(records, failures), "reading_module": status}


def publish_records(state, out):
    records = load_records(state)
    declaration = newest(records, "declaration")
    own_ids = {c["id"] for c in comment_set(records) if c["author"] == declaration["merging_id"]}
    target = Path(out)
    target.mkdir()  # OUT is new; existing folders are never reused.
    (target / "records").mkdir()
    source = Path(state) / "records"
    for path in sorted(source.iterdir()):
        match = RECORD_NAME.fullmatch(path.name)
        if not match:
            continue
        raw = path.read_bytes()
        if match[2] == "read" and match[3] == "json":
            data = read_json(raw)
            comments = [c for c in data["comments"] if c["id"] in own_ids]
            others = set(data.get("other_comment_ids", [])) | {c["id"] for c in data["comments"] if c["id"] not in own_ids}
            data = {**data, "comments": comments,
                    "other_comment_ids": sorted(others)}
            raw = canonical(data)
        elif match[2] == "post" and match[3] == "json":
            data = read_json(raw)
            if data["id"] not in own_ids:
                raw = canonical({"id": data["id"]})
        write_record(target, int(match[1]), match[2], raw if match[3] == "body" else read_json(raw),
                     raw=match[3] == "body")
    return "published records"


class PublicParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("invalid arguments")


def parser():
    result = PublicParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("init", "now", "read", "evaluate", "choose-round", "post", "beacon",
                    "match", "record-void", "publish-list", "publish-records"):
        sub = commands.add_parser(command)
        sub.add_argument("--state", required=True)
        if command == "evaluate":
            sub.add_argument("--recheck", action="store_true")
        if command in ("post", "match"):
            sub.add_argument("kind", choices=list(FIRST_LINES) if command == "post" else ["second", "tasks"])
            sub.add_argument("file")
        if command == "post":
            sub.add_argument("--reason", choices=["beacon", "build"])
            sub.add_argument("--failure-sha256")
        if command in ("beacon", "record-void"):
            sub.add_argument("--round", type=parse_integer, required=command == "record-void")
        if command == "beacon":
            sub.add_argument("--out")
            sub.add_argument("--rehearsal", action="store_true")
            sub.add_argument("--fixture", default=str(Path(__file__).with_name("known-answer-round.json")))
        if command == "record-void":
            sub.add_argument("--receipt-sha256", required=True)
        if command == "publish-records":
            sub.add_argument("out")
    return result


def execute(args):
    state, command = args.state, args.command
    records = load_records(state)
    declaration = newest(records, "declaration")
    if command != "init" and declaration is None:
        raise Refused("init required")
    if command == "init":
        pr = response_json(gh("api", f"{REPOSITORY}/pulls/573"))
        if not pr["merged"] or not pr["merged_at"] or not pr["merged_by"] or not pr["merge_commit_sha"]:
            raise Refused("declaration pull request not merged")
        content = gh("api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json",
                     f"{REPOSITORY}/contents/{DECLARATION_PATH}?ref={pr['merge_commit_sha']}")
        if content["status"] != 200:
            raise Refused("declaration content unavailable")
        data = initial_declaration(pr, content["body"])
        if declaration is not None:
            data["merging_login"] = declaration["merging_login"]
        if declaration is not None and data != declaration:
            raise Refused("declaration changed")
        append_record(state, "declaration", data)
        print("initialized")
    elif command == "now":
        t, skew, _ = now()
        print(f"github {t} skew {skew}")
    elif command == "read":
        print(f"read {read_issue(state)[0]}")
    elif command == "evaluate":
        result = evaluate_saved(state, args.recheck)
        if args.recheck:
            for line in result:
                print(line)
        else:
            if result["counted"] and result["code"] == 0:
                verify_reading(result["counted"]["commit"])
            print(evaluation_line(result))
            return result["code"]
    elif command == "choose-round":
        _, _, t = now()
        saved = newest(records, "round")
        number, action = choose_round(t, saved["round"] if saved else None)
        if action == "new":
            append_record(state, "round", {"round": number})
        print(f"round {number} due {round_due(number)} {action}")
    elif command == "post":
        line, code = post(state, args.kind, args.file, records, args.reason, args.failure_sha256)
        print(line)
        return code
    elif command == "beacon":
        if evaluate_records(records)["code"] == 14:
            raise Refused("draw stopped")
        if args.round is not None and args.out is None:
            raise Refused("beacon round requires out")
        if args.rehearsal:
            line, code = rehearsal(state, args.fixture)
        else:
            round_due(args.round)
            line, code = beacon_attempt(state, args.round, args.out)
        print(line)
        return code
    elif command == "match":
        counted = acting_counted(state)
        expected = parse_body(Path(args.file).read_bytes().decode("utf-8"))
        matches, differences = matching_comments(load_records(state), args.kind, expected, counted)
        append_record(state, "match", {"kind": args.kind, "round": counted["round"],
                                      "matches": matches, "differences": differences})
        for cid in differences:
            print(f"differs {cid}")
        if matches:
            print(f"matched {matches[0]}")
        else:
            print("none")
            return 10
    elif command == "record-void":
        acting_counted(state, args.round)
        if any(r["kind"] == "void" and r["data"]["round"] == args.round for r in records):
            raise Refused("round already void")
        if not any(r["kind"] == "beacon" and r["data"]["round"] == args.round for r in records):
            raise Refused("void needs accepted beacon")
        if not re.fullmatch(r"[0-9a-f]{64}", args.receipt_sha256):
            raise Refused("invalid receipt hash")
        append_record(state, "void", {"round": args.round, "receipt_sha256": args.receipt_sha256})
        print(f"void round {args.round}")
    elif command == "publish-list":
        sys.stdout.write(canonical(prepare_list(state)).decode("ascii"))
    elif command == "publish-records":
        print(publish_records(state, args.out))
    return 0


def main(argv=None, *, clock=None, sleep=None, gh_timeout=60):
    token = RUNTIME.set({"clock": clock or machine_time, "sleep": sleep or time.sleep, "gh_timeout": gh_timeout})
    try:
        args = parser().parse_args(argv)
        folder = Path(args.state) / "records"
        folder.mkdir(parents=True, exist_ok=True)
        fd = os.open(folder, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            return execute(args)
        finally:
            os.close(fd)
    except Refused as error:
        print("refused: " + str(error), file=sys.stderr)
    except Exception:
        print("refused: malformed or unavailable record", file=sys.stderr)
    finally:
        RUNTIME.reset(token)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
