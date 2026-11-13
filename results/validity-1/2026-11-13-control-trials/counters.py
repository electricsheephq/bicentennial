"""Read out a validity arm's diagnostics (#505, #506) as aggregate counts only: the declaration's disclosure counters.

Edition 2 (validity round 1, results/validity-1/DECLARATION.md §5 "Disclosure counters"): pass --edition 2 and
--tasks TASKS.json, so only the frozen list's 35 target items are read; target rows with no diagnostics are counted.
With --edition 1 and no --tasks it is the 13 November diagnostic run's readout, unchanged.

The diagnostic trace holds corpus text and sealed item ids. This script prints neither: only template names,
predicate labels, class names, booleans and counts. Run it with the run checkout's venv python, so the envelope
checks come from the pinned scorer:

  <run venv>/bin/python -I counters.py --diag DIR --run OUT --packs PACKS [--edition 1|2] [--tasks TASKS.json]
      [--json OUT.json]

What each table answers:
- act items (#505 and #506's drift templates): which decision predicate the reader's final repository state meets,
  read exactly as the scorer reads it (`items/checks/repo.py` repo_state_predicates: state[path][name] == value, any
  group whose checks all hold). For a state that meets no predicate, how it differs from the checked key and value.
- drift-quote: the same, split by whether the reader's first message contains "It was said that" anywhere. That
  message can carry retrieved or handed-over text other than the item's own later statement, so this is not a split
  by the later statement's own wording.
- QA items (#506's count question): why the raw final reply does or does not parse, step by step, mirroring
  `score/qa.py` parse_envelope; and whether the last reply ended in a tool call or a length stop.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path):
    return json.loads(Path(path).read_bytes())


def final_attempts(diag):
    """{(life, branch, iid): item dir} for each unit's highest attempt."""
    out = {}
    for life in sorted(p for p in diag.iterdir() if p.is_dir()):
        for branch in sorted(p for p in life.iterdir() if p.is_dir()):
            attempts = sorted((p for p in branch.iterdir() if p.is_dir() and p.name.isdigit()), key=lambda p: int(p.name))
            if not attempts:
                continue
            for item in sorted(p for p in attempts[-1].iterdir() if p.is_dir()):
                out[(life.name, branch.name, item.name)] = item
    return out


def cases(packs):
    """{item_id: case dict} from every installed pack's sealed scoring.json."""
    found = {}
    for path in sorted(Path(packs).glob("pack/G*/*/*/sealed/scoring.json")):
        for case in load_json(path)["cases"]:
            found[case["item"]["item_id"]] = case
    return found


def holds(state, checks):
    """The scorer's repo_state_predicates over plain check dicts."""
    def ok(c):
        if c["kind"] != "constant":
            raise ValueError("non-constant check")
        return state.get(c["path"], {}).get(c["name"]) == c["value"]
    return {name: any(all(ok(c) for c in group) for group in groups) for name, groups in checks.items()}


def norm(text):
    return re.sub(r"[^0-9a-z]+", "", str(text).casefold())


def act_class(state, state0, checks, prompt):
    """Why a state meets no predicate: compare the checked keys with what the reader wrote."""
    if state == state0:
        return "unchanged"
    targets = [c for groups in checks.values() for group in groups for c in group if c["kind"] == "constant"]
    by_key = {(c["path"], c["name"]) for c in targets}
    owners = defaultdict(set)  # check value -> the predicates whose checks carry it
    for pred, groups in checks.items():
        for group in groups:
            for c in group:
                if c["kind"] == "constant":
                    owners[c["value"]].add(pred)

    def whose(v):
        if v in owners:
            return "the value of " + "+".join(sorted(owners[v]))
        inside = sorted({p for x, ps in owners.items() if str(x) in str(v) for p in ps})
        return "the value of " + "+".join(inside) + " inside extra text" if inside else "another value"
    changed_paths = sorted(p for p in set(state) | set(state0) if state.get(p) != state0.get(p))
    if not any(p in {k[0] for k in by_key} for p in changed_paths):
        return "edited only other files"
    labels = []
    for path, name in sorted(by_key):
        new, old = state.get(path, {}), state0.get(path, {})
        added = {k: v for k, v in new.items() if k not in old or old[k] != v}
        if name in new and new.get(name) != old.get(name):
            labels.append(f"checked key, {whose(new[name])}")
        for key, v in added.items():
            if key == name:
                continue
            # The prompt's whole noun phrase, e.g. "<name> deadline" in "Record the <name> deadline in docs/...".
            m = re.match(r"Record the (.+?) in docs/", prompt or "")
            phrase = bool(m) and key.startswith(name) and key == m.group(1) and key != name
            if phrase:
                form = "key = checked name + the prompt's predicate words"
            elif key.startswith(name):
                form = "key = checked name + other words"
            elif norm(key) == norm(name):
                form = "key = checked name in another case or punctuation"
            else:
                form = "another key"
            labels.append(f"{form}, {whose(v)}")
    return "; ".join(sorted(set(labels))) or "changed, no added or changed checked-path key"


def reply_shape(trajectory):
    """(turns, last reply ended in a tool call, any length stop) from the kept ledger rows."""
    turns, tool_end, length = len(trajectory), False, False
    for i, row in enumerate(trajectory):
        resp = (row.get("bodies") or {}).get("resp")
        finish, calls = None, False
        if isinstance(resp, dict) and "choices" in resp:
            choice = (resp.get("choices") or [{}])[0]
            finish = choice.get("finish_reason")
            calls = bool((choice.get("message") or {}).get("tool_calls"))
        elif isinstance(resp, dict) and "sse" in resp:
            for chunk in resp["sse"] or ():
                chunk = json.loads(chunk) if isinstance(chunk, str) and chunk.startswith("{") else chunk
                if isinstance(chunk, dict):
                    for choice in chunk.get("choices") or ():
                        finish = choice.get("finish_reason") or finish
                        calls = calls or bool((choice.get("delta") or {}).get("tool_calls"))
        length = length or finish == "length"
        if i == turns - 1:
            tool_end = calls or finish == "tool_calls"
    return turns, tool_end, length


def last_reply_text(trajectory):
    """The text of the last reply that carries content and no tool call, from the kept ledger rows (the fallback when
    final.txt is absent, e.g. the session's shutdown failed after the final was delivered). None if there is none."""
    found = None
    for row in trajectory:
        resp = (row.get("bodies") or {}).get("resp")
        text, calls = None, False
        if isinstance(resp, dict) and "choices" in resp:
            message = ((resp.get("choices") or [{}])[0].get("message") or {})
            text, calls = message.get("content"), bool(message.get("tool_calls"))
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        elif isinstance(resp, dict) and "sse" in resp:
            parts = []
            for chunk in resp["sse"] or ():
                chunk = json.loads(chunk) if isinstance(chunk, str) and chunk.startswith("{") else chunk
                if isinstance(chunk, dict):
                    for choice in chunk.get("choices") or ():
                        delta = choice.get("delta") or {}
                        calls = calls or bool(delta.get("tool_calls"))
                        if isinstance(delta.get("content"), str):
                            parts.append(delta["content"])
            text = "".join(parts) if parts else None
        if isinstance(text, str) and text.strip() and not calls:
            found = text
    return found


def envelope_reason(text, qa):
    """Mirror score/qa.py parse_envelope one step at a time and name the first step that fails."""
    if text is None:
        return "no final text kept"
    body = text.strip()
    if not body:
        return "empty"
    fenced = qa.FENCE.fullmatch(body)
    if fenced is not None:
        body = fenced.group(1)
    try:
        env = json.loads(body, parse_float=qa._Float, parse_constant=qa._refuse, object_pairs_hook=qa._unique_keys)
    except Exception:  # noqa: BLE001
        start, end = body.find("{"), body.rfind("}")
        if 0 <= start < end:
            try:
                inner = json.loads(body[start:end + 1])
                if isinstance(inner, dict) and qa.REQUIRED <= inner.keys():
                    return "an envelope with other text around it"
            except Exception:  # noqa: BLE001
                pass
            return "not valid JSON"
        return "no JSON object"
    if type(env) is not dict:
        return "JSON that is not an object"
    if not qa.REQUIRED <= env.keys():
        return "missing a required key"
    if not env.keys() <= qa.REQUIRED | {"citation"}:
        return "an extra key"
    env = {"citation": None, **env}
    if env["type"] == "number" and type(env["value"]) is qa._Float:
        env["value"] = str(env["value"])
    if not qa._float_free(env):
        return "a float outside a number value"
    kind, conf = env["type"], env["confidence_milli"]
    if kind not in qa.TYPES:
        return "an unknown type"
    if type(conf) is not int or not 0 <= conf <= 1000:
        return "confidence out of range"
    if kind == "unknown" and (conf != 0 or env["citation"] is not None):
        return "unknown with confidence or citation"
    if not qa._value_ok(kind, env["value"]):
        return f"value not valid for type {kind}"
    cit = env["citation"]
    if cit is not None:
        if type(cit) is not dict or cit.keys() != {"quote", "context_offset"}:
            return "citation keys"
        if type(cit["quote"]) is not str:
            return "citation quote not a string"
        if "\n" in cit["quote"]:
            return "citation quote spans lines"
        if re.fullmatch(r"^.+$", cit["quote"]) is None:
            return "citation quote empty"
        if type(cit["context_offset"]) is not int or cit["context_offset"] < 0:
            return "citation offset"
    return "parses" if qa.parse_envelope(text) is not None else "fails for another reason"


def value_check(text, case, qa):
    """Whether the answer's value is the gold value when its citation is set aside (score/qa.py's matches); this
    separates a right answer voided by its format or citation from a wrong one. Labels only."""
    from bicentennial.score.answer_types import matches

    if text is None:
        return "no text"
    item = case["item"]
    gold_id = item["gold"]["option_id"]
    gold = next(o["envelope"] for o in item["options"] if o["option_id"] == gold_id)
    if gold["type"] == "unknown":
        return "gold is unknown"
    body = text.strip()
    fenced = qa.FENCE.fullmatch(body)
    body = fenced.group(1) if fenced is not None else body
    start, end = body.find("{"), body.rfind("}")
    if not 0 <= start < end:
        return "no object"
    try:
        env = json.loads(body[start:end + 1], parse_float=qa._Float, parse_constant=qa._refuse)
    except Exception:  # noqa: BLE001
        return "no object"
    if not isinstance(env, dict) or not qa.REQUIRED <= env.keys():
        return "no envelope keys"
    env = {key: env[key] for key in qa.REQUIRED}
    env["citation"] = None
    if env["type"] == "number" and type(env["value"]) is qa._Float:
        env["value"] = str(env["value"])
    try:
        if not qa.valid_envelope(env):
            return "invalid even without citation"
        return "value right" if matches(gold, env, tolerance_s=0) else "value wrong"
    except Exception:  # noqa: BLE001
        return "invalid even without citation"


def first_user_text(trajectory):
    for row in trajectory:
        req = (row.get("bodies") or {}).get("req")
        for msg in (req or {}).get("messages", ()) if isinstance(req, dict) else ():
            if msg.get("role") == "user":
                content = msg.get("content")
                if isinstance(content, list):
                    content = " ".join(part.get("text", "") for part in content if isinstance(part, dict))
                return content or ""
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--diag", required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--packs", required=True)
    ap.add_argument("--json")
    ap.add_argument("--edition", type=int, choices=(1, 2), default=1)
    ap.add_argument("--tasks")
    a = ap.parse_args()
    from bicentennial.score import qa

    diag, run = Path(a.diag), Path(a.run)
    outcomes = load_json(run / "outcomes.json")
    sealed = cases(a.packs)
    items = final_attempts(diag)
    absent = 0
    if a.tasks:
        keys = {(r["life"], r["branch"], r["item_id"]) for r in load_json(a.tasks)["rows"]}
        absent = len(keys - items.keys())
        items = {k: v for k, v in items.items() if k in keys}
    manifest = load_json(diag / "manifest.json")
    report = dict(manifest=dict(files=len(manifest["files"]), skips=Counter(s["reason"] for s in manifest["skips"]),
                                failures=Counter(f["error"] for f in manifest["failures"]),
                                # A non-clean rescan lists file paths (which carry item ids): report status and count only.
                                rescan=manifest["rescan"] if manifest["rescan"] == "clean" else dict(
                                    status="not clean", entries=len(manifest["rescan"])
                                    if isinstance(manifest["rescan"], (list, dict)) else None)),
                  items=len(items), missing=[], target_rows_without_diagnostics=absent)
    act = defaultdict(Counter)
    quote = defaultdict(Counter)
    qa_rows = defaultdict(Counter)
    shapes = defaultdict(Counter)
    for (life, branch, iid), folder in sorted(items.items()):
        row = outcomes.get(f"{life}/{branch}/{iid}")
        case = sealed.get(iid)
        if row is None or case is None:
            report["missing"].append("outcome" if row is None else "case")
            continue
        template, verdict = row.get("template_ref"), row.get("base_verdict")
        traj_path = folder / "trajectory.json"
        trajectory = load_json(traj_path) if traj_path.exists() else []
        turns, tool_end, length = reply_shape(trajectory)
        shapes[template][f"turns={min(turns, 9)}{'+' if turns >= 9 else ''}"] += 1
        shapes[template]["last reply ended in a tool call"] += tool_end
        shapes[template]["a length stop"] += length
        shapes[template]["no trajectory rows"] += not trajectory
        if (folder / "act.json").exists() and case.get("checks") is None:
            # G2 actions carry no repository checks and are not scored live yet (#118); outside #505 and #506.
            act[template][f"[{verdict}] not scored live (no checks)"] += 1
        elif (folder / "act.json").exists():
            state = load_json(folder / "act.json")
            met = sorted(k for k, v in holds(state, case["checks"]).items() if v)
            label = "meets " + "+".join(met) if met else "meets no predicate: " + act_class(
                state, case["state0"], case["checks"], case["item"].get("prompt"))
            twin = f" competing={bool(row.get('competing_present'))}" if template == f"drift-config-v{a.edition}" else ""
            act[template][f"[{verdict}{twin}] {label}"] += 1
            if template == f"drift-quote-v{a.edition}":
                wording = "hearsay ('It was said that')" if "It was said that" in first_user_text(trajectory) else "other wording"
                quote[wording][f"[{verdict}] {'meets ' + '+'.join(met) if met else 'meets no predicate'}"] += 1
        elif case["item"].get("stage") == "act":
            # No parsed state: read_state failed or the session never ran. Re-read the kept workspace with the
            # scorer's own reader and name only the exception type.
            ws = folder / "workspace"
            if not ws.is_dir():
                why = "no workspace kept"
            else:
                try:
                    from bicentennial.genres.g1_software.diffs import read_state
                    read_state(ws)
                    why = "workspace parses now (state missing for another reason)"
                except Exception as error:  # noqa: BLE001
                    why = f"read_state raises {type(error).__name__}"
            act[template][f"[{verdict}/{row.get('failure_class')}] no parsed state: {why}"] += 1
        else:
            final = folder / "final.txt"
            source = ""
            if final.exists():
                text = final.read_bytes().decode("utf-8", "replace")
            else:
                text = last_reply_text(trajectory)
                source = " (final from trajectory)" if text is not None else ""
            qa_rows[template][f"[score {row.get('score_milli')}] {envelope_reason(text, qa)}{source}; "
                              f"{value_check(text, case, qa)}"] += 1
    report.update(act={k: dict(v) for k, v in sorted(act.items())}, drift_quote_by_wording={k: dict(v) for k, v in quote.items()},
                  qa={k: dict(v) for k, v in sorted(qa_rows.items())}, reply_shapes={k: dict(v) for k, v in sorted(shapes.items())})
    report["missing"] = dict(Counter(report["missing"]))
    text = json.dumps(report, indent=1, default=dict)
    if a.json:
        Path(a.json).write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    sys.exit(main())
