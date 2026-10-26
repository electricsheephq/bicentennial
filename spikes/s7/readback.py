"""Independent, offline S7 Part A audit. Python 3.14; no director imports or live stores."""

import argparse
import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from compression import zstd

SUFFIX = (
    "[Memory checkpoint, provisional text] Before this turn is answered, decide whether anything in the "
    "conversation so far is worth keeping in long-term memory for future sessions. If so, call the memory "
    "tool now. If not, reply with the single word: none. Any text you write here is discarded.")
MODELS = {"chat": "glm-5.3", "responses": "gpt-6.1-sol"}


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (list, dict)):
        for value in obj.values() if isinstance(obj, dict) else obj:
            yield from strings(value)


def norm(text):
    return " ".join(text.split())


def load(root):
    """Verify the entire chain and every referenced blob, including non-write roles."""
    raw = (root / "ledger.jsonl").read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("empty_or_torn_ledger")
    rows, blobs, prev = [], {}, "0" * 64
    for seq, line in enumerate(raw.splitlines(), 1):
        row = json.loads(line)
        body = {k: v for k, v in row.items() if k != "hash"}
        if (row["seq"] != seq or row["prev_hash"] != prev or
                row["hash"] != hashlib.sha256(prev.encode() + canon(body)).hexdigest()):
            raise ValueError(f"chain:{seq}")
        prev = row["hash"]
        rows.append(row)
        for entry in [row, *row.get("upstream", [])]:
            for key in ("req", "resp"):
                digest = entry.get(key)
                if digest is None or digest in blobs:
                    continue
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError(f"blob_reference:{seq}")
                data = zstd.decompress((root / "blobs" / digest[:2] / f"{digest}.json.zst").read_bytes())
                if hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError(f"blob_hash:{seq}")
                blobs[digest] = json.loads(data)
    return rows, blobs, hashlib.sha256(raw).hexdigest()


def expected(body, wire):
    """Rebuild from the harness; pin adaptations rather than trusting the recorded wire."""
    out = {k: v for k, v in body.items() if wire != "chat" or k not in {"model", "stream", "stream_options"}}
    if wire == "chat":
        out["messages"] = body["messages"] + [{"role": "user", "content": SUFFIX}]
        out["tools"] = [t for t in body.get("tools", []) if t.get("function", {}).get("name") == "memory"]
    else:
        items = body.get("input", [])
        if isinstance(items, str):
            items = [{"type": "message", "role": "user", "content": items}]
        out["input"] = [dict(it, content=[{"type": "output_text" if it.get("role") == "assistant" else
                                        "input_text", "text": it["content"]}])
                        if it.get("type", "message") == "message" and isinstance(it.get("content"), str)
                        else it for it in items]
        out["input"].append({"type": "message", "role": "user", "content": [{"type": "input_text", "text": SUFFIX}]})
        out["tools"] = [t for t in body.get("tools", []) if t.get("name") == "memory"]
    return dict(out, model=MODELS[wire], stream=wire == "responses")


def output(obj, wire):
    """Decode the stored response, including the directors' two SSE envelopes."""
    if wire == "responses":
        events = []
        for block in obj["sse"].replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
            if data and data != "[DONE]":
                events.append(json.loads(data))
        items = [e["item"] for e in events if e.get("type") == "response.output_item.done"]
        streamed = {}  # the text a client renders from the deltas, per output item
        for e in events:
            if e.get("type") == "response.output_text.delta":
                key = (e.get("item_id"), e.get("output_index"))
                streamed[key] = streamed.get(key, "") + str(e.get("delta", ""))
        calls = [{"id": it["call_id"], "name": it["name"], "arguments": it["arguments"]}
                 for it in items if it.get("type") == "function_call"]
        texts = ["".join(strings(it.get("content", []) if isinstance(it.get("content"), str) else
                               [p.get("text", "") for p in it.get("content", [])]))
                 for it in items if it.get("type") == "message"]
        return calls, texts + [t for t in streamed.values() if t and t not in texts]  # a disagreeing stream is kept
    if "__sse__" in obj:
        deltas = [c["choices"][0]["delta"] for c in obj["__sse__"] if c.get("choices")]
        msg = {"content": "".join(d.get("content", "") for d in deltas),
               "tool_calls": [tc for d in deltas for tc in d.get("tool_calls", [])]}
    else:
        msg = obj["choices"][0]["message"]
    return [dict(id=tc["id"], **tc["function"]) for tc in msg.get("tool_calls", [])], [msg.get("content") or ""]


def reasoning(obj, wire):
    """Textual reasoning a stored response carries: Responses reasoning items and deltas, chat reasoning fields."""
    if wire == "responses":
        found = []
        for block in obj["sse"].replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
            data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
            if not data or data == "[DONE]":
                continue
            e = json.loads(data)
            if e.get("type") in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                found.append(str(e.get("delta", "")))
            item = e.get("item") or {}
            if e.get("type") == "response.output_item.done" and item.get("type") == "reasoning":
                found += [str(part.get("text", "")) for key in ("summary", "content") for part in item.get(key) or []
                          if isinstance(part, dict)]
        return [t for t in found if t]
    msgs = [c["choices"][0]["delta"] for c in obj["__sse__"] if c.get("choices")] if "__sse__" in obj else [
        obj["choices"][0]["message"]]
    return [str(m[k]) for m in msgs for k in ("reasoning_content", "reasoning") if m.get(k)]


def conversation(body, wire):
    if wire == "chat":
        return list(strings([m.get("content", "") for m in body.get("messages", [])]))
    return list(strings([body.get("instructions", ""), [m.get("content", "") for m in body.get("input", [])
                        if m.get("type", "message") == "message"]]))


def channels(body, wire):
    """Every string of a request in three labelled channels: conversation text, tool-call arguments and
    outputs outside it, and every other string (configuration, schemas). Each string falls in one channel."""
    conv = conversation(body, wire)
    items = body.get("messages" if wire == "chat" else "input", [])
    if wire == "chat":
        tool = [tc.get("function", {}).get("arguments", "") for m in items for tc in m.get("tool_calls") or []]
    else:
        tool = [it.get("arguments" if it.get("type") == "function_call" else "output", "") for it in items
                if it.get("type") in {"function_call", "function_call_output"}]
    tool = list(strings(tool))
    return conv, tool, list((Counter(strings(body)) - Counter(conv) - Counter(tool)).elements())


def calls_in(body, wire):
    """(id, name) of every tool call already in a request's history."""
    items = body.get("messages" if wire == "chat" else "input", [])
    if wire == "chat":
        return {(tc.get("id"), tc.get("function", {}).get("name")) for m in items for tc in m.get("tool_calls") or []}
    return {(it.get("call_id"), it.get("name")) for it in items if it.get("type") == "function_call"}


def results(body, wire):
    items = body.get("messages" if wire == "chat" else "input", [])
    return {it.get("tool_call_id", it.get("call_id")): it.get("content", it.get("output")) for it in items
            if it.get("role") == "tool" or it.get("type") == "function_call_output"}


def ids(obj, path="life"):
    """ID values, references, and the event-map keys; never fact/gold text."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            label = f"{path}.{key}"
            if key == "events" and isinstance(value, dict):
                found.extend((f"{label}.{k}", k) for k in value)
            if key in {"id", "supersedes"} or key.endswith(("_id", "_ids")):
                found.extend((label, v) for v in strings(value))
            found.extend(ids(value, label))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(ids(value, f"{path}.{i}"))
    return found


ACTIONS = {"add", "patch", "replace", "remove"}


def effects(calls, requests, stores, wire):
    ops, reports = [], []
    for call in calls:
        try:
            args = json.loads(call["arguments"])
        except (TypeError, ValueError):
            args = None
        try:
            result = json.loads(call["result"])
        except (TypeError, ValueError):
            result = None
        staged = isinstance(result, dict) and bool(result.get("staged"))  # held for approval: not written
        applied = (False if staged else result.get("success")) if isinstance(result, dict) else None
        report = {"record": call["record"], "call": call["id"], "applied": applied, "staged": staged, "operations": []}
        reports.append(report)
        args = args if isinstance(args, dict) else {}
        listed = args.get("operations", [args])
        for i, op in enumerate(listed if isinstance(listed, list) else [{}]):
            ops.append(dict(op if isinstance(op, dict) else {}, target=args.get("target", "memory"),
                            record=call["record"], session=call["session"], applied=applied, report=report,
                            id=f"{call['id']}:{i + 1}"))
    for op in ops:
        action = op.get("action")
        raw = op.get("old_text", "") if action == "remove" else op.get("content", op.get("new_text", ""))
        op["needle"] = norm(raw) if isinstance(raw, str) and isinstance(op.get("old_text", ""), str) else ""
        if op["applied"] and action not in ACTIONS:  # a write Hermes applied must be one this audit can check
            raise ValueError(f"unknown_memory_action:{op['record']}")
        if op["applied"] and not op["needle"]:
            raise ValueError(f"empty_memory_content:{op['record']}")
    for i, op in enumerate(ops):
        action, needle = op.get("action"), op["needle"]
        if action not in ACTIONS or not needle:  # a malformed call Hermes refused, staged or left unclassified
            op["report"]["operations"].append({"id": op["id"], "action": action, "reasons": [
                "staged_not_applied" if op["report"]["staged"] else "hermes_refused" if op["applied"] is False
                else "unclassified_result", "malformed_operation"]})
            continue
        nxt = next(((r, b) for r, b in requests if r["seq"] > op["record"] and r.get("cursor") and
                    r["cursor"]["session"] != op["session"] and r["cursor"]["turn"] == 1 and
                    r.get("role") in {"replay_main", "probe_main"}), None)
        def state(until, i=i, op=op, needle=needle):
            value, changed = needle, []
            for later in ops[i + 1:]:
                if later["record"] >= until or not later["applied"] or later["target"] != op["target"]:
                    continue
                old = norm(later.get("old_text", ""))
                if old and old in value and later.get("action") in {"patch", "replace", "remove"}:
                    value = "" if later["action"] == "remove" else value.replace(
                        old, norm(later.get("content", later.get("new_text", ""))))
                    changed.append(later["id"])
                elif old and value and value in old and later.get("action") in {"patch", "replace", "remove"}:
                    # a later span that encompasses this content replaces all of it with the new text
                    value = "" if later["action"] == "remove" else norm(later.get("content", later.get("new_text", "")))
                    changed.append(later["id"])
            return value, changed
        final, changed = state(float("inf"))
        store = norm(stores.get(op["target"], ""))
        present = needle in store
        store_ok = (final in store if final else needle not in store) if action != "remove" else not present
        visible, next_ok, next_changed = None, None, []
        if nxt:
            r, b = nxt
            system = b.get("instructions", "") if wire == "responses" else " ".join(
                strings([m.get("content", "") for m in b.get("messages", []) if m.get("role") == "system"]))
            snapshot = norm(system)
            wanted, next_changed = state(r["seq"])
            visible = needle in snapshot
            next_ok = (wanted in snapshot if wanted else needle not in snapshot) if action != "remove" else not visible
        reasons = []
        if op["report"]["staged"]:
            reasons.append("staged_not_applied")
        elif op["applied"] is False:
            reasons.append("hermes_refused")
        if op["applied"] is None:
            reasons.append("unclassified_result")
        if changed:
            reasons.append("later_modified_or_removed")
        if nxt is None:
            reasons.append("no_next_session")
        if op["applied"] and not store_ok:
            reasons.append("absent_from_final_store" if action != "remove" else "remove_still_present")
        if op["applied"] and next_ok is False:
            reasons.append("absent_from_next_session" if action != "remove" else "remove_visible_next_session")
        op["report"]["operations"].append({"id": op["id"], "action": action, "in_store": present,
            "visible_next_session": visible, "store_satisfied": store_ok, "next_session_satisfied": next_ok,
            "next_session_record": nxt[0]["seq"] if nxt else None, "superseded_by": changed,
            "superseded_before_next": next_changed, "reasons": reasons})
    gaps = [r["call"] for r in reports if r["applied"] is None or r["applied"] and any(
        not o["store_satisfied"] or o["next_session_satisfied"] is not True for o in r["operations"])]
    all_ops = [o for r in reports if r["applied"] for o in r["operations"]]
    counts = {key: sum(o[key] is True for o in all_ops) for key in (
        "in_store", "visible_next_session", "store_satisfied", "next_session_satisfied")}
    return dict(executed=len(reports), applied=sum(r["applied"] is True for r in reports),
                refused=sum(r["applied"] is False and not r["staged"] for r in reports),
                staged=sum(r["staged"] for r in reports), applied_operations=len(all_ops),
                gaps=gaps, calls=reports, **counts)


def audit(rows, blobs, life, stores, wire):
    turns = [(s["index"], i, t) for s in life["sessions"] + life.get("probes", []) for i, t in enumerate(s["turns"], 1)]
    requests = [(r, blobs[r["req"]]) for r in rows if "req" in r]
    a1 = {"write_records": 0, "forwarded": 0, "matches": 0, "mismatches": [], "flag_disagreements": []}
    a2 = {"hits": [], "introduced": []}
    a3 = {"offered": 0, "executed": 0, "non_write_attempts": 0, "non_write_blocked": 0, "non_write_calls": [], "failures": []}
    a5 = {"scripted": 0, "matches": 0, "script_failures": [], "missing_scripts": [], "text_hits": [], "whole_content_hits": [], "tool_channel_hits": [], "non_content_collisions": [], "served_write_text": []}
    calls, drafts, issued = [], [], 0
    for r, body in requests:
        seq, cursor = r["seq"], r.get("cursor")
        attempts = [u for u in r.get("upstream", []) if u.get("kind") == "write_turn"]
        if attempts:
            a1["write_records"] += 1
            idx = next(i for i, (s, t, _) in enumerate(turns) if cursor == {"session": s, "turn": t})
            want = expected(body, wire)
            verdicts = []
            served, served_texts = output(blobs[r["resp"]], wire)
            if r.get("served") == "write_tool_calls" and (any(served_texts) or reasoning(blobs[r["resp"]], wire)):
                # the harness gets the calls only: no reply or reasoning text
                a5["served_write_text"].append(seq)
            following = next(((rr, bb) for rr, bb in requests if rr["seq"] > seq and
                              rr.get("cursor") == cursor and results(bb, wire)), None)
            if following is None:
                following = next(((rr, bb) for rr, bb in requests if rr["seq"] > seq and
                                  rr.get("role") in {"replay_main", "write_turn", "probe_main"}), None)
            new_results = {}  # the harness may return one turn's results over several continuation requests
            for rr, bb in requests:
                if rr["seq"] > seq and rr.get("cursor") == cursor:
                    for tid, out in results(bb, wire).items():
                        new_results.setdefault(tid, out)
            if not new_results and following:
                new_results = results(following[1], wire)
            for tid in new_results.keys() - results(body, wire).keys() - {tc["id"] for tc in served}:
                a3["failures"].append({"record": seq, "kind": "unissued_execution", "call": tid})
            for n, u in enumerate(attempts, 1):
                sent = blobs[u["req"]]
                diff = sorted(k for k in set(want) | set(sent) if (k in want) != (k in sent) or canon(want.get(k)) != canon(sent.get(k)))
                verdicts.append(not diff)
                a1["forwarded"] += 1
                a1["matches"] += not diff
                if diff:
                    a1["mismatches"].append({"record": seq, "attempt": n, "keys": diff})
                s0, t0, now = turns[idx]  # the cursor turn's own reply is served after the write turn: still future
                needles = [(f"{s0}:{t0}:assistant", now.get("assistant"), "pending_assistant")]
                needles += [(f"{s}:{t}:{k}", v, f"future_{k}") for s, t, turn in turns[idx + 1:]
                            for k, v in turn.items() if k in {"user", "assistant"}]
                needles += [(label, value, "life_id") for label, value in ids(life)]
                for label, value, kind in needles:
                    if value and any(value in text for text in strings(sent)):
                        # inherited only when the sent body holds no more copies than the expected body does
                        hit = {"record": seq, "attempt": n, "kind": kind, "id": label, "inherited": sum(
                            t.count(value) for t in strings(sent)) <= sum(t.count(value) for t in strings(want))}
                        a2["hits"].append(hit)
                        if not hit["inherited"]:
                            a2["introduced"].append(hit)
                if "resp" in u:
                    attempted, texts = output(blobs[u["resp"]], wire)
                    drafts.extend((seq, text) for text in texts if text)
                    for tc in attempted:
                        if tc["name"] == "memory":
                            continue
                        a3["non_write_attempts"] += 1
                        # reachability counts only calls and results new relative to the triggering request
                        prior_calls, prior_results = {c for c, _ in calls_in(body, wire)}, results(body, wire).keys()
                        new_calls = calls_in(following[1], wire) - calls_in(body, wire) if following else set()
                        later = set()  # calls and results are new against their own kind: an old call, new result is new
                        for rr, bb in requests:
                            if rr["seq"] > seq:
                                later |= {c for c, _ in calls_in(bb, wire)} - prior_calls
                                later |= results(bb, wire).keys() - prior_results
                        blocked = (not any(c["name"] == tc["name"] for c in served) and tc["id"] not in later
                                   and not any(i == tc["id"] or n == tc["name"] for i, n in new_calls))
                        a3["non_write_blocked"] += blocked
                        a3["non_write_calls"].append({"record": seq, "attempt": n, "call": tc["id"], "blocked": blocked,
                            "next_request_record": following[0]["seq"] if following else None})
                        if not blocked:
                            a3["failures"].append({"record": seq, "kind": "non_write_reached_harness", "call": tc["id"]})
                bad_tools = [t for t in sent.get("tools", []) if t.get("function", t).get("name") != "memory"]
                a3["offered"] += len(sent.get("tools", []))
                if bad_tools:
                    a3["failures"].append({"record": seq, "kind": "non_write_offered"})
            if r.get("write_turn_readback") != verdicts[-1]:
                a1["flag_disagreements"].append(seq)
            upstream, _ = output(blobs[attempts[-1]["resp"]], wire)
            filtered = [tc for tc in upstream if tc["name"] == "memory"]
            if len(filtered) != len(served):
                a3["failures"].append({"record": seq, "kind": "call_count"})
            for i, tc in enumerate(served):
                issued += 1
                valid = tc["id"] == f"bcw{issued:05d}" and i < len(filtered) and all(
                    tc[k] == filtered[i][k] for k in ("name", "arguments")) and tc["id"] in new_results
                if not valid:
                    a3["failures"].append({"record": seq, "kind": "call_provenance_or_result", "call": tc["id"]})
                if tc["id"] in new_results and tc["name"] == "memory":
                    a3["executed"] += 1
                    calls.append(dict(tc, record=seq, session=cursor["session"], result=new_results[tc["id"]]))
        if r.get("served") in {"script", "script_retry"}:
            script_calls, texts = output(blobs[r["resp"]], wire)
            script = next(t["assistant"] for s, i, t in turns if cursor == {"session": s, "turn": i})
            a5["scripted"] += 1
            ok = texts == [script] and not script_calls
            if script_calls:  # a scripted reply is text only: a call on it would bypass the write-turn checks
                a3["failures"].append({"record": seq, "kind": "scripted_tool_call"})
            a5["matches"] += ok
            if not ok:
                a5["script_failures"].append(seq)
    for origin, text in drafts:
        for r, body in requests:
            if r["seq"] > origin:
                hit = {"record": r["seq"], "write_record": origin}
                conv, tool, other = channels(body, wire)  # case-sensitive substring, every string, labelled
                if any(text in part for part in conv):
                    a5["text_hits"].append(hit)
                    if text in conv:
                        a5["whole_content_hits"].append(hit)
                if any(text in part for part in tool):
                    a5["tool_channel_hits"].append(hit)
                if any(text in part for part in other):
                    a5["non_content_collisions"].append(hit)
    for r, _ in requests:
        if any(u.get("kind") == "write_turn" for u in r.get("upstream", [])) and not any(
                rr.get("cursor") == r["cursor"] and rr.get("served") in {"script", "script_retry"}
                for rr in rows):
            a5["missing_scripts"].append(r["seq"])
    a2.update(raw_hits=len(a2["hits"]), introduced_hits=len(a2["introduced"]))
    a5["write_texts_checked"] = len(drafts)
    return {"A1": a1, "A2": a2, "A3": a3, "A4": effects(calls, requests, stores, wire), "A5": a5}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger_dir", type=Path)
    parser.add_argument("hermes_home", type=Path)
    parser.add_argument("--wire", choices=MODELS, required=True)
    parser.add_argument("--life", type=Path, required=True)
    args = parser.parse_args()
    rows, blobs, digest = load(args.ledger_dir)
    if not args.hermes_home.is_dir():
        raise ValueError("missing_hermes_home")
    stores = {}
    for target, name in (("memory", "memories/MEMORY.md"), ("user", "memories/USER.md")):
        path = args.hermes_home / name
        stores[target] = path.read_text() if path.is_file() else ""
    result = audit(rows, blobs, json.loads(args.life.read_text()), stores, args.wire)
    print(json.dumps(dict(ledger_records=len(rows), ledger_sha256=digest, blobs_verified=len(blobs), **result),
                     sort_keys=True))


if __name__ == "__main__":
    main()
