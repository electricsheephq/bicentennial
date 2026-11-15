"""Pure draw rules over saved records, with a small append-only command layer."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

REPOSITORY = "repos/electricsheephq/bicentennial"
DECLARATION_PATH = "results/followup/DECLARATION.md"
CHAIN = "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971"
GENESIS = 1692803367
FIRST_LINES = {"first": "Follow-up draw: first post", "second": "Follow-up draw: second post",
               "tasks": "Follow-up draw: task lists", "stop": "Follow-up draw: stop"}
IDENTITY_FIELDS = ("registry_entry_sha256", "fresh_install_hash", "artifact_sha256",
                   "system_hash", "harness_hash", "route_table_hash")
RECORD_NAME = re.compile(r"([0-9]{4,})-([a-z][a-z-]*)\.(json|body)(?:\.partial)?\Z")


class Refused(Exception):
    """A fixed, public-safe refusal label."""


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def seconds(value):
    return int(datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp())


def round_due(number):
    if type(number) is not int or number < 1:
        raise Refused("invalid round")
    return GENESIS + (number - 1) * 3


def parse_body(body):
    """The maintainers' line reading, fixed before the draw."""
    lines = [line[:-1] if line.endswith("\r") else line for line in body.split("\n")]
    kind = next((k for k, line in FIRST_LINES.items() if lines[0] == line), None)
    rounds = {int(line[6:]) for line in lines if re.fullmatch(r"round [1-9][0-9]*", line)}
    commits = {line[11:] for line in lines if re.fullmatch(r"run_commit [0-9a-f]{40}", line)}
    values = {}
    for line in lines[1:]:
        match = re.fullmatch(r"([a-z][a-z0-9_]*) ([^\s]+)", line)
        if match:
            name, value = match.groups()
            if name == "round" and not re.fullmatch(r"[1-9][0-9]*", value):
                continue
            if name == "run_commit" and not re.fullmatch(r"[0-9a-f]{40}", value):
                continue
            if name in values and values[name] != value:
                values[name] = None
            else:
                values[name] = value
    reason = ("missing round" if not rounds else "conflicting round" if len(rounds) != 1 else
              "missing commit" if not commits else "conflicting commit" if len(commits) != 1 else "")
    return {"kind": kind, "round": next(iter(rounds)) if len(rounds) == 1 else None,
            "run_commit": next(iter(commits)) if len(commits) == 1 else None,
            "values": values, "reason": reason}


def newest(records, kind):
    return next((r["data"] for r in sorted(records, key=lambda r: r["number"], reverse=True)
                 if r["kind"] == kind), None)


def initial_declaration(pr, content):
    if not pr["merged"] or not pr["merged_at"] or not pr["merged_by"] or not pr["merge_commit_sha"]:
        raise Refused("declaration pull request not merged")
    return {"merging_login": pr["merged_by"]["login"], "merge_time": pr["merged_at"],
            "declaration_commit": pr["merge_commit_sha"],
            "sha256": hashlib.sha256(content).hexdigest(), "length": len(content)}


def github_clock(headers, machine_seconds):
    served = int(parsedate_to_datetime(headers["date"]).timestamp())
    skew = int(machine_seconds) - served
    if abs(skew) > 60:
        raise Refused("clock skew exceeds 60 seconds")
    return served, skew


def normalize_comment(node):
    return {"id": int(node["fullDatabaseId"]), "author": (node["author"] or {}).get("login"),
            "created_at": node["createdAt"], "body": node["body"],
            "lastEditedAt": node["lastEditedAt"], "includesCreatedEdit": node["includesCreatedEdit"],
            "edits": node["userContentEdits"]["nodes"]}


def rest_comment(node):
    return {"id": int(node["id"]), "author": node["user"]["login"],
            "created_at": node["created_at"], "body": node["body"]}


def candidates(records):
    declaration = newest(records, "declaration")
    seen = {}
    for record in sorted(records, key=lambda r: r["number"]):
        comments = record["data"] if record["kind"] == "read" else (
            [record["data"]] if record["kind"] == "post" else [])
        for comment in comments:
            cid = int(comment["id"])
            if cid in seen:
                continue
            seen[cid] = None
            if comment["author"] != declaration["merging_login"]:
                continue
            if seconds(comment["created_at"]) <= seconds(declaration["merge_time"]):
                continue
            body = None
            if record["kind"] == "post" or comment["lastEditedAt"] is None:
                body = comment["body"]
            elif comment["includesCreatedEdit"] and comment["edits"]:
                earliest = min(comment["edits"], key=lambda e: seconds(e["editedAt"]))
                if earliest["deletedAt"] is None:
                    body = earliest["diff"]
            seen[cid] = {"id": cid, "created_at": comment["created_at"], "body": body}
    return sorted((c for c in seen.values() if c is not None), key=comment_order)


def comment_order(comment):
    return seconds(comment["created_at"]), int(comment["id"])


def commitment_test(comment, evidence, declaration):
    result = {"id": int(comment["id"]), "commit": evidence["commit"], "passed": False,
              "reason": "not found", "pull_request": None, "merged_at": None}
    content = evidence["content"]
    if evidence.get("failure") or content["status"] != 200:
        result["reason"] = evidence.get("failure", "not found")
        return result
    if content["sha256"] != declaration["sha256"] or content["length"] != declaration["length"]:
        result["reason"] = "declaration differs"
        return result
    qualifying = [p for p in evidence["pulls"] if p["base"] == "main" and p["merged_at"]
                  and p["merge_commit_sha"] and p.get("compare") in ("identical", "ahead")]
    if not qualifying:
        result["reason"] = "no qualifying pull request"
        return result
    earliest = min(qualifying, key=lambda p: (seconds(p["merged_at"]), p["number"]))
    result.update(pull_request=earliest["number"], merged_at=earliest["merged_at"])
    result["passed"] = seconds(earliest["merged_at"]) < seconds(comment["created_at"])
    result["reason"] = "passed" if result["passed"] else "merge not before comment"
    return result


def saved_test(records, comment, parsed):
    tests = [r for r in records if r["kind"] == "test" and r["data"]["id"] == comment["id"]]
    if tests:
        return min(tests, key=lambda r: r["number"])["data"]
    evidence = next((r["data"] for r in sorted(records, key=lambda r: r["number"])
                     if r["kind"] == "evidence" and r["data"]["commit"] == parsed["run_commit"]), None)
    if evidence is None:
        raise Refused("commitment evidence missing")
    return commitment_test(comment, evidence, newest(records, "declaration"))


def evaluate_records(records):
    """Return the counted draw and the public list using saved facts only."""
    rows = []
    seen_rounds = {}
    voids = {r["data"]["round"] for r in records if r["kind"] == "void"}
    counted = None
    unreadable = []
    for comment in candidates(records):
        row = {"id": comment["id"], "created_at": comment["created_at"], "round": None,
               "commit": None, "pull_request": None, "merged_at": None, "on_time": None,
               "test": None, "test_reason": None, "counted": False}
        if comment["body"] is None:
            row["reason"] = "unrecoverable"
            unreadable.append(comment)
        else:
            parsed = parse_body(comment["body"])
            if parsed["kind"] != "first":
                continue
            row.update(round=parsed["round"], commit=parsed["run_commit"])
            if parsed["round"] is not None:
                row["on_time"] = seconds(comment["created_at"]) <= round_due(parsed["round"]) - 600
            if parsed["reason"]:
                row["reason"] = "not a commitment post: " + parsed["reason"]
            else:
                test = saved_test(records, comment, parsed)
                row.update(test=test["passed"], test_reason=test["reason"],
                           pull_request=test["pull_request"], merged_at=test["merged_at"])
                n = parsed["round"]
                if not test["passed"]:
                    row["reason"] = "failed: " + test["reason"]
                elif n in seen_rounds:
                    row["reason"] = f"same round as {seen_rounds[n]}"
                else:
                    seen_rounds[n] = comment["id"]
                    if not row["on_time"]:
                        row["reason"] = "late"
                    elif n in voids:
                        row["reason"] = "void round"
                    elif counted is not None:
                        row["reason"] = "after the counted post"
                    else:
                        row["reason"] = "counted"
                        row["counted"] = True
                        counted = {**row, "values": parsed["values"]}
        rows.append(row)
    blocked = [c["id"] for c in unreadable if counted is None or comment_order(c) < comment_order(counted)]
    if blocked:
        return {"code": 3, "counted": counted, "blocked": blocked, "rows": rows}
    return {"code": 0 if counted is not None else 1, "counted": counted, "blocked": [], "rows": rows}


def publish_list(records):
    return evaluate_records(records)["rows"]


def choose_round(t, saved):
    if saved is not None:
        ahead = round_due(saved) - t
        if ahead > 3600:
            raise Refused("saved round more than 3600 seconds ahead")
        if ahead > 600:
            return saved, "kept"
    number = max(1, (t + 900 - GENESIS + 2) // 3 + 1)
    return number, "new"


def validate_first(parsed, saved_round, t, evidence, declaration):
    if parsed["reason"]:
        raise Refused("first post lacks unambiguous round or commit")
    if saved_round is None or parsed["round"] != saved_round["round"]:
        raise Refused("first post does not use saved round")
    if round_due(parsed["round"]) - t <= 600:
        raise Refused("first post round due too soon")
    test = commitment_test({"id": 0, "created_at": datetime.fromtimestamp(t, UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ")}, evidence, declaration)
    if not test["passed"] or seconds(test["merged_at"]) > t - 60:
        raise Refused("first post commit not merged at least 60 seconds ago")


def accept_beacon(number, left, right, t):
    if t >= round_due(number) + 86400:
        return "cutoff", None
    try:
        a, b = json.loads(left), json.loads(right)
        if a != b:
            return "relay disagreement", None
        if not isinstance(a, dict) or set(a) != {"round", "randomness", "signature"}:
            return "beacon fields", None
        if type(a["round"]) is not int or a["round"] != number:
            return "wrong round", None
        if not isinstance(a["signature"], str) or not re.fullmatch(r"(?:[0-9a-f]{2})+", a["signature"]):
            return "signature format", None
        if hashlib.sha256(bytes.fromhex(a["signature"])).hexdigest() != a["randomness"]:
            return "randomness hash", None
        return "accepted", a
    except (ValueError, TypeError, UnicodeError):
        return "relay JSON", None


def matching_comments(records, kind, expected, counted):
    if expected["kind"] != kind or expected["round"] != counted["round"]:
        raise Refused("match file has wrong kind or round")
    matches, differences = [], []
    for comment in candidates(records):
        if comment["body"] is None or comment_order(comment) <= comment_order(counted):
            continue
        parsed = parse_body(comment["body"])
        if parsed["kind"] != kind or parsed["round"] != counted["round"]:
            continue
        if parsed["values"] == expected["values"]:
            matches.append(comment["id"])
        else:
            differences.append(comment["id"])
    return matches, differences


# The remaining functions are the thin I/O layer. No rule reads a clock or a file.
def load_records(state):
    folder = Path(state) / "records"
    result = []
    if folder.exists():
        for path in folder.iterdir():
            match = RECORD_NAME.fullmatch(path.name)
            if match and not path.name.endswith(".partial") and match[3] == "json":
                result.append({"number": int(match[1]), "kind": match[2],
                               "data": json.loads(path.read_bytes())})
    return sorted(result, key=lambda r: r["number"])


def write_record(state, number, kind, data, raw=False):
    if not re.fullmatch(r"[a-z][a-z-]*", kind) or number < 1:
        raise Refused("invalid record name")
    folder = Path(state) / "records"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{number:04d}-{kind}.{'body' if raw else 'json'}"
    partial = target.with_name(target.name + ".partial")
    if target.exists() or partial.exists():
        raise Refused("record name exists")
    with partial.open("xb") as out:
        out.write(data if raw else canonical(data))
        out.flush()
        os.fsync(out.fileno())
    try:
        os.link(partial, target)
    except FileExistsError as error:
        raise Refused("record name exists") from error
    partial.unlink()
    return target


def append_record(state, kind, data, raw=False):
    folder = Path(state) / "records"
    numbers = [int(match[1]) for path in folder.iterdir()
               if (match := RECORD_NAME.fullmatch(path.name))] if folder.exists() else []
    return write_record(state, max(numbers, default=0) + 1, kind, data, raw)


def parse_http(raw):
    status, headers = None, {}
    while raw.startswith(b"HTTP/"):
        parts = re.split(br"\r?\n\r?\n", raw, maxsplit=1)
        if len(parts) != 2:
            raise Refused("missing HTTP header block")
        block, raw = parts
        lines = block.splitlines()
        match = re.fullmatch(br"HTTP/\S+ ([0-9]{3})(?: .*)?", lines[0])
        if not match:
            raise Refused("missing HTTP status")
        status = int(match[1])
        headers = {}
        for line in lines[1:]:
            name, value = line.split(b":", 1)
            headers[name.decode("ascii").lower()] = value.strip().decode("ascii")
    if status is None:
        raise Refused("missing HTTP status")
    return {"status": status, "headers": headers, "body": raw}


def gh(*args):
    args = list(args)
    if args[:1] == ["api"] and "-i" not in args:
        args.insert(1, "-i")
    try:
        response = subprocess.run(["gh", *args], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, timeout=60, check=False)
    except subprocess.TimeoutExpired as error:
        raise Refused("GitHub timeout") from error
    except OSError as error:
        raise Refused("GitHub tool unavailable") from error
    return parse_http(response.stdout)


def curl(url):
    try:
        response = subprocess.run(["curl", "--silent", "--show-error", "--max-time", "20", url],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30, check=False)
        return response.returncode == 0, response.stdout
    except subprocess.TimeoutExpired as error:
        return False, error.stdout or b""
    except OSError:
        return False, b""


def response_json(response):
    if response["status"] not in (200, 201):
        raise Refused("GitHub HTTP status")
    value = json.loads(response["body"])
    if isinstance(value, dict) and "errors" in value:
        raise Refused("GitHub GraphQL errors")
    return value


def machine_time():
    return time.time()


def now():
    response = gh("api", "rate_limit")
    if response["status"] != 200:
        raise Refused("GitHub time unavailable")
    return github_clock(response["headers"], machine_time())


EDIT_FIELDS = "userContentEdits(first:100,after:$c){pageInfo{hasNextPage endCursor} nodes{editedAt deletedAt diff}}"
COMMENT_FIELDS = ("id fullDatabaseId author{login} createdAt lastEditedAt includesCreatedEdit body "
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
    nodes = page["nodes"]
    info = page["pageInfo"]
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
    append_record(state, "read", comments)
    return len(comments)


def evidence_status(response):
    status = response["status"]
    if status == 404:
        return "not found"
    if status == 422:
        value = json.loads(response["body"])
        message = value.get("message", "").casefold()
        if "no commit" in message and "found" in message:
            return "no commit found"
    if status != 200:
        raise Refused("commitment evidence unavailable")
    return None


def fetch_evidence(commit):
    raw = gh("api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json",
             f"{REPOSITORY}/contents/{DECLARATION_PATH}?ref={commit}")
    failure = evidence_status(raw)
    evidence = {"commit": commit, "content": {"status": raw["status"],
                "sha256": hashlib.sha256(raw["body"]).hexdigest(), "length": len(raw["body"])}, "pulls": []}
    if failure:
        return {**evidence, "failure": failure}
    response = gh("api", f"{REPOSITORY}/commits/{commit}/pulls?per_page=100")
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


def evaluate_saved(state, recheck=False):
    records = load_records(state)
    declaration = newest(records, "declaration")
    pending = []
    evidence_cache = {}
    changes = []
    for comment in candidates(records):
        if comment["body"] is None:
            continue
        parsed = parse_body(comment["body"])
        if parsed["kind"] != "first" or parsed["reason"]:
            continue
        existing_test = any(r["kind"] == "test" and r["data"]["id"] == comment["id"] for r in records)
        if existing_test and not recheck:
            continue
        commit = parsed["run_commit"]
        if commit not in evidence_cache:
            saved = next((r["data"] for r in records if r["kind"] == "evidence"
                          and r["data"]["commit"] == commit), None)
            evidence_cache[commit] = fetch_evidence(commit) if recheck or saved is None else saved
            if not recheck and saved is None:
                pending.append(("evidence", evidence_cache[commit]))
        test = commitment_test(comment, evidence_cache[commit], declaration)
        if recheck:
            old = saved_test(records, comment, parsed)
            differences = [key for key in ("passed", "reason", "pull_request", "merged_at") if old[key] != test[key]]
            changes.extend(f"changed {comment['id']} {key} {json.dumps(old[key])} {json.dumps(test[key])}"
                           for key in differences)
            if not differences:
                changes.append(f"unchanged {comment['id']}")
        else:
            pending.append(("test", test))
    # No logical records from a partially failed evaluation are published.
    for kind, data in pending:
        append_record(state, kind, data)
    return changes if recheck else evaluate_records(load_records(state))


def evaluation_line(result):
    if result["code"] == 3:
        return "blocked " + " ".join(map(str, result["blocked"]))
    counted = result["counted"]
    if counted is None:
        return "none"
    return (f"counted {counted['id']} round {counted['round']} due {round_due(counted['round'])} "
            f"commit {counted['commit']}")


def require_counted(result, number=None):
    if result["code"] != 0:
        raise Refused("no counted draw")
    counted = result["counted"]
    if number is not None and counted["round"] != number:
        raise Refused("round is not counted")
    return counted


def post(state, kind, filename, records):
    text = Path(filename).read_bytes().decode("utf-8")
    parsed = parse_body(text)
    if parsed["kind"] != kind:
        raise Refused("post first line does not match kind")
    user = response_json(gh("api", "user"))
    declaration = newest(records, "declaration")
    if user["login"] != declaration["merging_login"]:
        raise Refused("posting login differs")
    evidence = None
    if kind == "first":
        result = evaluate_saved(state)
        if result["code"] == 0:
            raise Refused("counted draw already exists")
        t, _ = now()
        evidence = next((r["data"] for r in load_records(state) if r["kind"] == "evidence"
                         and r["data"]["commit"] == parsed["run_commit"]), None)
        if evidence is None and parsed["run_commit"] is not None:
            evidence = fetch_evidence(parsed["run_commit"])
        validate_first(parsed, newest(records, "round"), t, evidence, declaration)
    response = response_json(gh("api", "-X", "POST", f"{REPOSITORY}/issues/394/comments",
                                "-F", "body=@" + str(filename)))
    saved = rest_comment(response)
    append_record(state, "post", saved)
    if kind == "first":
        # The response is durable even if a later record write is interrupted.
        if not any(r["kind"] == "evidence" and r["data"]["commit"] == evidence["commit"]
                   for r in load_records(state)):
            append_record(state, "evidence", evidence)
        append_record(state, "test", commitment_test(saved, evidence, declaration))
    return f"posted {saved['id']} {saved['created_at']}"


def beacon_attempt(state, number):
    counted = require_counted(evaluate_saved(state), number)
    t, _ = now()
    if t < round_due(counted["round"]):
        raise Refused("round not due")
    if t >= round_due(number) + 86400:
        return f"cutoff round {number}", 3
    left_ok, left = curl(f"https://api.drand.sh/{CHAIN}/public/{number}")
    append_record(state, "relay-primary", left, raw=True)
    right_ok, right = curl(f"https://drand.cloudflare.com/{CHAIN}/public/{number}")
    append_record(state, "relay-secondary", right, raw=True)
    after, _ = now()
    reason, value = accept_beacon(number, left, right, after)
    if reason == "cutoff":
        return f"cutoff round {number}", 3
    if not left_ok or not right_ok:
        return "not-accepted relay unavailable", 1
    if value is None:
        return "not-accepted " + reason, 1
    append_record(state, "beacon", value)
    return f"accepted round {number}", 0


class PublicParser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused("invalid arguments")


def parser():
    result = PublicParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("init", "now", "read", "evaluate", "choose-round", "post", "beacon",
                    "match", "record-void", "publish-list"):
        sub = commands.add_parser(command)
        sub.add_argument("--state", required=True)
        if command == "evaluate":
            sub.add_argument("--recheck", action="store_true")
        if command in ("post", "match"):
            sub.add_argument("kind", choices=list(FIRST_LINES) if command == "post" else ["second", "tasks"])
            sub.add_argument("file")
        if command in ("beacon", "record-void"):
            sub.add_argument("--round", type=int, required=True)
        if command == "record-void":
            sub.add_argument("--receipt-sha256", required=True)
    return result


def execute(args):
    state, command = args.state, args.command
    records = load_records(state)
    declaration = newest(records, "declaration")
    if command != "init" and declaration is None:
        raise Refused("init required")
    if declaration is not None and command not in ("evaluate", "publish-list"):
        if any(c["body"] is None for c in candidates(records)):
            if evaluate_records(records)["code"] == 3:
                raise Refused("unrecoverable earlier candidate")
    if command == "init":
        pr = response_json(gh("api", f"{REPOSITORY}/pulls/573"))
        initial_declaration(pr, b"")
        content = gh("api", "-X", "GET", "-H", "Accept: application/vnd.github.raw+json",
                     f"{REPOSITORY}/contents/{DECLARATION_PATH}?ref={pr['merge_commit_sha']}")
        if content["status"] != 200:
            raise Refused("declaration content unavailable")
        data = initial_declaration(pr, content["body"])
        if declaration is not None and data != declaration:
            raise Refused("declaration changed")
        append_record(state, "declaration", data)
        print("initialized")
    elif command == "now":
        t, skew = now()
        print(f"github {t} skew {skew}")
    elif command == "read":
        print(f"read {read_issue(state)}")
    elif command == "evaluate":
        result = evaluate_saved(state, args.recheck)
        if args.recheck:
            for line in result:
                print(line)
        else:
            print(evaluation_line(result))
            return result["code"]
    elif command == "choose-round":
        t, _ = now()
        saved = newest(records, "round")
        number, action = choose_round(t, saved["round"] if saved else None)
        if action == "new":
            append_record(state, "round", {"round": number})
        print(f"round {number} due {round_due(number)} {action}")
    elif command == "post":
        print(post(state, args.kind, args.file, records))
    elif command == "beacon":
        line, code = beacon_attempt(state, args.round)
        print(line)
        return code
    elif command == "match":
        counted = require_counted(evaluate_saved(state))
        expected = parse_body(Path(args.file).read_bytes().decode("utf-8"))
        matches, differences = matching_comments(load_records(state), args.kind, expected, counted)
        for cid in differences:
            append_record(state, "difference", {"kind": args.kind, "id": cid, "round": counted["round"]})
            print(f"differs {cid}")
        if matches:
            print(f"matched {matches[0]}")
        else:
            print("none")
            return 1
    elif command == "record-void":
        require_counted(evaluate_saved(state), args.round)
        if not re.fullmatch(r"[0-9a-f]{64}", args.receipt_sha256):
            raise Refused("invalid receipt hash")
        append_record(state, "void", {"round": args.round, "receipt_sha256": args.receipt_sha256})
        print(f"void round {args.round}")
    elif command == "publish-list":
        sys.stdout.write(canonical(publish_list(records)).decode("ascii"))
    return 0


def main(argv=None):
    try:
        return execute(parser().parse_args(argv))
    except Refused as error:
        print("refused: " + str(error), file=sys.stderr)
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError, AttributeError):
        print("refused: malformed or unavailable record", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
