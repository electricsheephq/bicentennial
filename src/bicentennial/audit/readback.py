"""The write-turn audit after replay (DESIGN §6.2a, PREREG §10; S7 Part A) over a kit or S6 ledger. A1 rebuilds
each write body itself, importing no director module; reports hold numbers, labels, ids and codes, never text."""

import hashlib
import json
import re
from collections import Counter
from compression import zstd
from pathlib import Path

from bicentennial.audit.effects import request_wire, strings
from bicentennial.keyed import mint_id
from bicentennial.ledger import BlobStore, verify

FORMATS = ("kit", "s6")
INTEGRITY = ("chain_breaks", "truncated_tail", "bad_blobs", "missing_lock_fields")
FAILING = {"A1": ("mismatches", "flag_disagreements", "missing_write_turns"), "A2": ("introduced",),
           "A3": ("failures",), "A4": ("gaps",),
           "A5": ("script_failures", "missing_scripts", "served_write_text", "whole_content_hits")}


def canon(obj):
    """S7's JSON bytes, floats allowed (the S6 ledgers carry them): the A1 comparison and the S6 chain encoder."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _blob_refs(row):
    for entry in [row, *row.get("upstream", [])]:
        for key in ("req", "resp"):
            if entry.get(key) is not None:
                yield entry[key]


def _load_kit(root):
    counts = verify(root)
    bad = [field for field in INTEGRITY if counts[field]] + ["records"] * (not counts["records"])
    if bad:
        raise ValueError(f"ledger_integrity:{bad[0]}")
    raw = (root / "ledger.jsonl").read_bytes()
    rows, blobs, store = [json.loads(line) for line in raw.split(b"\n")[:-1]], {}, BlobStore(root / "blobs", None)
    for row in rows:
        for digest in _blob_refs(row):
            if digest not in blobs:
                blobs[digest] = json.loads(store.get(digest))
    return rows, blobs, hashlib.sha256(raw).hexdigest()


def _load_s6(root):
    """Verify the entire chain and every referenced blob, including non-write roles (the spike's load)."""
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
        for digest in _blob_refs(row):
            if digest in blobs:
                continue
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(f"blob_reference:{seq}")
            data = zstd.decompress((root / "blobs" / digest[:2] / f"{digest}.json.zst").read_bytes())
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"blob_hash:{seq}")
            blobs[digest] = json.loads(data)
    return rows, blobs, hashlib.sha256(raw).hexdigest()


def load(root, fmt):
    """-> (rows, blobs, ledger_sha256); raises ValueError on any integrity failure."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown_format:{fmt}")
    return (_load_kit if fmt == "kit" else _load_s6)(Path(root))


def turns_from_script(script):
    """[(session, n, {"user", "assistant"})] of a K13 script, in life order."""
    return [(s["index"], t["n"], {k: v for k, v in t.items() if k in {"user", "assistant"}})
            for s in script["sessions"] for t in s["turns"]]


def turns_from_life(life):
    """The same for an S6 micro-life: sessions, then probes, keyed by the life's own index ("P1" for probes)."""
    return [(s["index"], i, {k: v for k, v in t.items() if k in {"user", "assistant"}})
            for s in life["sessions"] + life.get("probes", []) for i, t in enumerate(s["turns"], 1)]


def route_models(table, system, schedule):
    """-> (model_for, mode): each session's write-turn model, and "scripted" only when every route is scripted."""
    rows = [row for row in table.to_obj()["routes"] if row["system"] == system]
    if not rows:
        raise ValueError(f"no_routes:{system}")
    mode = "scripted" if all(row["served_by"] == "scripted" for row in rows) else "live"
    return (lambda session: table.resolve(system, session, schedule)["probe_model"]), mode


def expected(body, wire, model, suffix, write_tools):
    """Rebuild the write body from the harness's request; pin adaptations rather than trusting the recorded wire."""
    out = {k: v for k, v in body.items() if wire != "chat" or k not in {"model", "stream", "stream_options"}}
    if wire == "chat":
        out["messages"] = body["messages"] + ([] if suffix is None else [{"role": "user", "content": suffix}])
        out["tools"] = [t for t in body.get("tools", []) if t.get("function", {}).get("name") in write_tools]
    else:
        items = body.get("input", [])
        if isinstance(items, str):
            items = [{"type": "message", "role": "user", "content": items}]
        out["input"] = [dict(it, content=[{"type": "output_text" if it.get("role") == "assistant" else
                                           "input_text", "text": it["content"]}])
                        if it.get("type", "message") == "message" and isinstance(it.get("content"), str)
                        else it for it in items]
        out["input"] += [] if suffix is None else [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": suffix}]}]
        out["tools"] = [t for t in body.get("tools", []) if t.get("name") in write_tools]
    return dict(out, model=model, stream=wire == "responses")


def _events(obj):
    """Responses events: the S6 raw SSE string, or the kit's parsed event list as given."""
    if isinstance(obj["sse"], list):
        return obj["sse"]
    events = []
    for block in obj["sse"].replace("\r\n", "\n").replace("\r", "\n").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
        if data and data != "[DONE]":
            events.append(json.loads(data))
    return events


def _messages(obj):
    """Chat: the stream's deltas (S6 __sse__, kit sse list) or the JSON response's one message."""
    chunks = obj["__sse__"] if "__sse__" in obj else obj["sse"] if isinstance(obj.get("sse"), list) else None
    if chunks is None:
        return None, [obj["choices"][0]["message"]]
    return chunks, [c["choices"][0]["delta"] for c in chunks if c.get("choices")]


def output(obj, wire):
    """(calls, texts) of a served response, through both SSE envelopes of both formats."""
    if wire == "responses":
        events = _events(obj)
        done = [(e.get("output_index", n), e["item"]) for n, e in enumerate(
            e for e in events if e.get("type") == "response.output_item.done")]  # an item's index is its position
        items = [it for _, it in done]
        streamed = {}  # the text a client renders from the deltas, per output item
        for e in events:
            if e.get("type") == "response.output_text.delta":
                key = (e.get("item_id"), e.get("output_index"))
                streamed[key] = streamed.get(key, "") + str(e.get("delta", ""))
        calls = [{"id": it["call_id"], "name": it["name"], "arguments": it["arguments"]}
                 for it in items if it.get("type") == "function_call"]
        texts, completed = [], {}  # each completed message's text, and the same by item id and by output index
        for index, it in done:
            if it.get("type") == "message":
                texts.append("".join(strings(it.get("content", []) if isinstance(it.get("content"), str) else
                                             [p.get("text", "") for p in it.get("content", [])])))
                completed[("index", index)] = texts[-1]
                if it.get("id") is not None:
                    completed[("id", it["id"])] = texts[-1]
        # a stream is dropped only where it is that same completed message; any other streamed text is kept
        return calls, texts + [t for (item_id, index), t in streamed.items() if t and not (
            item_id is not None and completed.get(("id", item_id)) == t or
            index is not None and completed.get(("index", index)) == t)]
    chunks, msgs = _messages(obj)
    msg = msgs[0] if chunks is None else {"content": "".join(d.get("content", "") for d in msgs),
                                          "tool_calls": [tc for d in msgs for tc in d.get("tool_calls", [])]}
    return [dict(id=tc["id"], **tc["function"]) for tc in msg.get("tool_calls", [])], [msg.get("content") or ""]


def refused(row, obj):
    """A served refusal or other non-completion (R08's identity_mismatch or stopped error envelope): never parsed."""
    return row.get("status", 200) != 200 or not isinstance(obj, dict) or "error" in obj


def reasoning(obj, wire):
    """Textual reasoning a stored response carries: Responses reasoning items and deltas, chat reasoning fields."""
    if wire == "responses":
        found = []
        for e in _events(obj):
            if e.get("type") in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                found.append(str(e.get("delta", "")))
            item = e.get("item") or {}
            if e.get("type") == "response.output_item.done" and item.get("type") == "reasoning":
                found += [str(part.get("text", "")) for key in ("summary", "content") for part in item.get(key) or []
                          if isinstance(part, dict)]
        return [t for t in found if t]
    return [str(m[k]) for m in _messages(obj)[1] for k in ("reasoning_content", "reasoning") if m.get(k)]


def _reply(obj, wire, fmt):
    """(calls, texts) of a write-turn reply: S6 stores a served response, the kit asdict(Reply)."""
    if fmt == "s6":
        return output(obj, wire)
    return [{"id": None, "name": c["name"], "arguments": c["arguments"]} for c in obj["tool_calls"]], [obj["text"]]


def _n_calls(obj):
    """Tool calls anywhere in a kit served response: chat tool_calls entries and Responses function_call items."""
    if isinstance(obj, list):
        return sum(_n_calls(value) for value in obj)
    return isinstance(obj, dict) and (obj.get("type") == "function_call") + sum(
        len(v) if k == "tool_calls" and isinstance(v, list) else _n_calls(v) for k, v in obj.items())


def _minted_ids(rows, blobs):
    """Kit mint budgets: scripted turns share the attempt seed; other records use their ledger role."""
    budget = Counter()
    for r in rows:
        attempt = r.get("attempt_id")
        if isinstance(attempt, str):
            seed = attempt if r.get("cursor") is not None else canon([attempt, r["role"]]).decode()
            budget[seed] += 1 + _n_calls(blobs.get(r.get("resp")))
    return {mint_id(seed, k): (seed, k) for seed, n in budget.items() for k in range(1, n + 1)}


def _items(body, wire):
    """A request's history items. A string input is one user message; token ids and other non-object
    items (an embeddings request's input) carry no history, and their strings stay in the other channel."""
    items = [] if wire == "embeddings" else body.get("messages" if wire == "chat" else "input", [])
    items = [{"type": "message", "role": "user", "content": items}] if isinstance(items, str) else items
    return [it for it in items if isinstance(it, dict)] if isinstance(items, list) else []


def conversation(body, wire):
    if wire != "responses":
        return list(strings([m.get("content", "") for m in _items(body, wire) if m.get("role") != "tool"]))
    return list(strings([body.get("instructions", ""), [m.get("content", "") for m in _items(body, wire)
                        if m.get("type", "message") == "message"]]))


def channels(body, wire):
    """Every string of a request in three labelled channels: conversation text, tool-call arguments and
    outputs outside it, and every other string (configuration, schemas). Each string falls in one channel."""
    conv, items = conversation(body, wire), _items(body, wire)
    if wire == "chat":
        tool = [tc.get("function", {}).get("arguments", "") for m in items for tc in m.get("tool_calls") or []]
        tool += [m.get("content", "") for m in items if m.get("role") == "tool"]
    else:
        tool = [it.get("arguments" if it.get("type") == "function_call" else "output", "") for it in items
                if it.get("type") in {"function_call", "function_call_output"}]
    tool = list(strings(tool))
    return conv, tool, list((Counter(strings(body)) - Counter(conv) - Counter(tool)).elements())


def calls_in(body, wire):
    """(id, name) of every tool call already in a request's history."""
    items = _items(body, wire)
    if wire == "chat":
        return {(tc.get("id"), tc.get("function", {}).get("name")) for m in items for tc in m.get("tool_calls") or []}
    return {(it.get("call_id"), it.get("name")) for it in items if it.get("type") == "function_call"}


def results(body, wire):
    items = _items(body, wire)
    return {it.get("tool_call_id", it.get("call_id")): it.get("content", it.get("output")) for it in items
            if it.get("role") == "tool" or it.get("type") == "function_call_output"}


def life_ids(obj, path="life"):
    """ID values, references, and the event-map keys; never fact/gold text."""
    found = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            label = f"{path}.{key}"
            if key == "events" and isinstance(value, dict):
                found.extend((f"{label}.{k}", k) for k in value)
            if key in {"id", "supersedes"} or key.endswith(("_id", "_ids")):
                found.extend((label, v) for v in strings(value))
            found.extend(life_ids(value, label))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(life_ids(value, f"{path}.{i}"))
    return found


def audit(rows, blobs, turns, wire, *, fmt, model_for, suffix, write_tools, id_needles, effects=None):
    """-> {"A1".."A5"}; A4 is None without an effects hook. Raises on a ledger this audit cannot read."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown_format:{fmt}")
    write_tools = tuple(write_tools)

    def attempts_of(r):  # S6 names an upstream entry's kind, the kit its role
        return [u for u in r.get("upstream", []) if u.get("kind" if fmt == "s6" else "role") == "write_turn"]

    def turn_index(seq, cursor):
        found = next((i for i, (s, t, _) in enumerate(turns) if cursor == {"session": s, "turn": t}), None)
        if found is None:
            raise ValueError(f"unknown_cursor:{seq}")
        return found

    requests = [(r, blobs[r["req"]]) for r in rows if "req" in r]
    a1 = {"write_records": 0, "forwarded": 0, "matches": 0, "mismatches": [], "flag_disagreements": [],
          "missing_write_turns": []}
    a2 = {"hits": [], "introduced": []}
    a3 = {"offered": 0, "executed": 0, "non_write_attempts": 0, "non_write_blocked": 0, "non_write_calls": [], "failures": []}
    a5 = {"scripted": 0, "matches": 0, "script_failures": [], "missing_scripts": [], "text_hits": [], "whole_content_hits": [], "tool_channel_hits": [], "non_content_collisions": [], "served_write_text": []}
    calls, drafts, issued = [], [], 0
    issued_at = {}  # each call id served to the harness, by the record that served it
    for r in rows:
        if r.get("served") == "write_tool_calls" and not refused(r, blobs.get(r.get("resp"))):
            for tc in output(blobs[r["resp"]], wire)[0]:
                issued_at.setdefault(tc["id"], r["seq"])
    minted = _minted_ids(rows, blobs) if fmt == "kit" else {}
    last_k, served_ids = {}, set()  # each namespace's last served counter; ids served once in the ledger
    for r, body in requests:
        seq, cursor = r["seq"], r.get("cursor")
        attempts, bad = attempts_of(r), refused(r, blobs.get(r.get("resp")))
        if bad and (attempts or r.get("served") in {"write_tool_calls", "script", "script_retry"}):
            a3["failures"].append({"record": seq, "kind": "served_refusal"})  # the turn served no completion
        if r.get("write_turn_failed"):
            a3["failures"].append({"record": seq, "kind": "write_turn_failed"})
        if attempts and not write_tools:  # PREREG §10: no write turn for a system without write tools
            a3["failures"].append({"record": seq, "kind": "write_turn_without_write_tools"})
        if "write_turn_readback" in r and not attempts:
            a1["flag_disagreements"].append(seq)
        if attempts:
            a1["write_records"] += 1
            idx = turn_index(seq, cursor)
            want = expected(body, wire, model_for(cursor["session"]), suffix, write_tools)
            verdicts = []
            served, served_texts = ([], []) if bad else output(blobs[r["resp"]], wire)
            if not bad and r.get("served") == "write_tool_calls" and (any(served_texts) or reasoning(blobs[r["resp"]], wire)):
                # the harness gets the calls only: no reply or reasoning text
                a5["served_write_text"].append(seq)
            following = next(((rr, bb) for rr, bb in requests if rr["seq"] > seq and
                              rr.get("cursor") == cursor and results(bb, request_wire(rr, wire))), None)
            if following is None:
                following = next(((rr, bb) for rr, bb in requests if rr["seq"] > seq and
                                  rr.get("role") in {"replay_main", "write_turn", "probe_main"}), None)
            new_results, seen_at = {}, {}  # one turn's results may arrive over several continuation requests
            for rr, bb in requests:
                if rr["seq"] > seq and rr.get("cursor") == cursor:
                    for tid, out in results(bb, request_wire(rr, wire)).items():
                        new_results.setdefault(tid, out)
                        seen_at.setdefault(tid, rr["seq"])
            if not new_results and following:
                new_results = results(following[1], request_wire(following[0], wire))
                seen_at = dict.fromkeys(new_results, following[0]["seq"])
            for tid in new_results.keys() - results(body, wire).keys() - {tc["id"] for tc in served}:
                if not issued_at.get(tid, float("inf")) < seen_at[tid]:  # another record's earlier call is not unissued
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
                needles += [(label, value, "life_id") for label, value in id_needles]
                for label, value, kind in needles:
                    if value and any(value in text for text in strings(sent)):
                        # inherited only when the sent body holds no more copies than the expected body does
                        hit = {"record": seq, "attempt": n, "kind": kind, "id": label, "inherited": sum(
                            t.count(value) for t in strings(sent)) <= sum(t.count(value) for t in strings(want))}
                        a2["hits"].append(hit)
                        if not hit["inherited"]:
                            a2["introduced"].append(hit)
                if "resp" in u:  # a kit responder error records no reply: no calls, no texts
                    attempted, texts = _reply(blobs[u["resp"]], wire, fmt)
                    drafts.extend((seq, text) for text in texts if text)
                    for j, tc in enumerate(attempted, 1):
                        if tc["name"] in write_tools:
                            continue
                        a3["non_write_attempts"] += 1
                        label = tc["id"] if tc["id"] is not None else f"{seq}:{n}:{j}"
                        # reachability counts only calls and results new relative to the triggering request
                        prior_calls, prior_results = {c for c, _ in calls_in(body, wire)}, results(body, wire).keys()
                        new_calls = (calls_in(following[1], request_wire(following[0], wire)) - calls_in(body, wire)
                                     if following else set())
                        later = set()  # calls and results are new against their own kind: an old call, new result is new
                        for rr, bb in requests:
                            if rr["seq"] > seq:  # each later request read on its own wire
                                later |= {c for c, _ in calls_in(bb, request_wire(rr, wire))} - prior_calls
                                later |= results(bb, request_wire(rr, wire)).keys() - prior_results
                        blocked = (not any(c["name"] == tc["name"] for c in served) and not any(
                            nm == tc["name"] for _, nm in new_calls) and (tc["id"] is None or tc["id"] not in later
                            and not any(i == tc["id"] for i, _ in new_calls)))  # a kit attempt has no id clauses
                        a3["non_write_blocked"] += blocked
                        a3["non_write_calls"].append({"record": seq, "attempt": n, "call": label, "blocked": blocked,
                            "next_request_record": following[0]["seq"] if following else None})
                        if not blocked:
                            a3["failures"].append({"record": seq, "kind": "non_write_reached_harness", "call": label})
                bad_tools = [t for t in sent.get("tools", []) if t.get("function", t).get("name") not in write_tools]
                a3["offered"] += len(sent.get("tools", []))
                if bad_tools:
                    a3["failures"].append({"record": seq, "kind": "non_write_offered"})
            if r.get("write_turn_readback") != verdicts[-1]:
                a1["flag_disagreements"].append(seq)
            upstream = _reply(blobs[attempts[-1]["resp"]], wire, fmt)[0] if "resp" in attempts[-1] else []
            filtered = [tc for tc in upstream if tc["name"] in write_tools]
            if not bad and len(filtered) != len(served):
                a3["failures"].append({"record": seq, "kind": "call_count"})
            for i, tc in enumerate(served):
                if fmt == "s6":
                    issued += 1
                    origin = tc["id"] == f"bcw{issued:05d}"
                else:  # minted by this record's attempt, in increasing counter order, served once in the ledger
                    a, k = minted.get(tc["id"], (None, 0))
                    origin = a == r.get("attempt_id") and k > last_k.get(a, 0) and tc["id"] not in served_ids
                    if origin:
                        last_k[a] = k
                    served_ids.add(tc["id"])
                valid = origin and i < len(filtered) and all(
                    tc[k] == filtered[i][k] for k in ("name", "arguments")) and tc["id"] in new_results
                if not valid:
                    a3["failures"].append({"record": seq, "kind": "call_provenance_or_result", "call": tc["id"]})
                if tc["id"] in new_results and tc["name"] in write_tools:
                    a3["executed"] += 1
                    calls.append(dict(tc, record=seq, session=cursor["session"], result=new_results[tc["id"]]))
        if r.get("served") in {"script", "script_retry"} and not bad:
            script_calls, texts = output(blobs[r["resp"]], wire)
            script = turns[turn_index(seq, cursor)][2].get("assistant")
            a5["scripted"] += 1
            ok = texts == [script] and not script_calls and not reasoning(blobs[r["resp"]], wire)  # the script only
            if script_calls:  # a scripted reply is text only: a call on it would bypass the write-turn checks
                a3["failures"].append({"record": seq, "kind": "scripted_tool_call"})
            a5["matches"] += ok
            if not ok:
                a5["script_failures"].append(seq)
    for origin, text in drafts:
        for r, body in requests:
            if r["seq"] > origin:
                hit = {"record": r["seq"], "write_record": origin}
                conv, tool, other = channels(body, request_wire(r, wire))  # case-sensitive substring, every string, labelled
                if any(text in part for part in conv):
                    a5["text_hits"].append(hit)
                    if text in conv:
                        a5["whole_content_hits"].append(hit)
                if any(text in part for part in tool):
                    a5["tool_channel_hits"].append(hit)
                if any(text in part for part in other):
                    a5["non_content_collisions"].append(hit)
    for r, _ in requests:
        if attempts_of(r) and not any(
                rr.get("cursor") == r["cursor"] and rr.get("served") in {"script", "script_retry"} for rr in rows):
            a5["missing_scripts"].append(r["seq"])
    attempted = {(r["cursor"]["session"], r["cursor"]["turn"]) for r, _ in requests if attempts_of(r)}
    for r, _ in requests:  # PREREG §10: with write tools, every replay turn classified by its cursor gets a write turn
        if write_tools and r.get("role") == "replay_main" and r.get("subrole") == "cursor" and r.get("cursor") and (
                r["cursor"]["session"], r["cursor"]["turn"]) not in attempted:
            a1["missing_write_turns"].append(r["seq"])
    a2.update(raw_hits=len(a2["hits"]), introduced_hits=len(a2["introduced"]))
    a5["write_texts_checked"] = len(drafts)
    return {"A1": a1, "A2": a2, "A3": a3, "A4": effects(calls, requests, wire) if effects else None, "A5": a5}


def failures(report):
    """Sorted failure codes. Inherited A2 hits (ERRATA E8) and A5 substring collisions are reported only."""
    found = [f"{a}.{k}" for a, keys in FAILING.items() if report[a] is not None for k in keys if report[a][k]]
    return sorted(found + (["A4.no_effects_hook"] if report["A4"] is None else []))


def run_status(report, mode):
    """OK, else INFRA_FAILURE (scripted) or UNATTRIBUTED (live: X02 or P07 attributes it by cause, PREREG §7)."""
    if mode not in ("scripted", "live"):
        raise ValueError(f"unknown_mode:{mode}")
    if not failures(report):
        return "OK"
    return "INFRA_FAILURE" if mode == "scripted" else "UNATTRIBUTED"
