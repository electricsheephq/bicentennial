"""A4: each executed write's whole-entry effect in the final store and the next session, and the Hermes
store hook. Reports hold record numbers, call ids and reason codes, never text."""

import json
import re
from pathlib import Path

ACTIONS = {"add", "patch", "replace", "remove"}
ENTRY_DELIMITER = "\n§\n"  # Hermes memory_tool_store, not an arbitrary line or paragraph boundary
MEMORY_HEADER = re.compile(r"═{46}\n(MEMORY \(your personal notes\)|USER PROFILE \(who the user is\))[^\n]*\n═{46}\n")
# Pinned Hermes agent/system_prompt.py:35,386,498,507,727,779-792 and
# agent/prompt_builder.py:1153; retain the older date labels as well.
FOLLOWING_PART = re.compile(r"\n\n(?:Active Hermes profile:|Conversation started:|Current date:|Today's date:|"
                            r"Today's date \(as of the last context rebuild\):|## Plugin Context: |"
                            r"# Hermes runtime environment)")


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (list, dict)):
        for value in obj.values() if isinstance(obj, dict) else obj:
            yield from strings(value)


def norm(text):
    return " ".join(text.split())


def known(action):
    return isinstance(action, str) and action in ACTIONS


def blocks(content):
    """A content's text blocks, as the director reads them (roles._blocks): a string, or its text parts."""
    if isinstance(content, str):
        return [content]
    return [p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)
            and p.get("type") in (None, "text", "input_text", "output_text")] if isinstance(content, list) else []


def request_wire(row, wire):
    """A request's own wire, from its recorded endpoint (the director dispatches each request by path, embeddings
    included), else the replay's: one ledger may mix wires, such as Responses turns and a chat title request."""
    path = str(row.get("path", "")).split("?")[0].rstrip("/")
    return ("chat" if path.endswith("/chat/completions") else
            "responses" if path.endswith(("/responses", "/responses/compact")) else
            "embeddings" if path.endswith("/embeddings") else wire)


def snapshot_parts(body, wire):
    """The memory snapshot a request carries: chat system and developer messages; Responses instructions and the
    system and developer messages in input, as the director extracts them (roles._items)."""
    if wire != "responses":
        return list(strings([m.get("content", "") for m in body.get("messages", []) if m.get("role") in (
            "system", "developer")]))
    items = body.get("input") if isinstance(body.get("input"), list) else []  # a string input is a user message
    found = [body["instructions"]] if isinstance(body.get("instructions"), str) else []
    for it in items:
        if isinstance(it, dict) and str(it.get("type", "message")) == "message" and it.get("role") in (
                "system", "developer"):
            found += blocks(it.get("content"))
    return found


def snapshot(body, wire):
    return " ".join(snapshot_parts(body, wire))


def entry_texts(text):
    """Split before normalising: newlines within an entry are content, not entry boundaries."""
    return [norm(part) for part in text.split(ENTRY_DELIMITER) if part.strip()]


def snapshot_entries(body, wire, target):
    """Read Hermes' rendered memory blocks, or a bare store supplied as a system/developer text part.
    Known following parts end a block; only the final block's final entry may precede an unknown part."""
    found = []
    for part in snapshot_parts(body, wire):
        headers = list(MEMORY_HEADER.finditer(part))
        if not headers:
            found.extend(entry_texts(part))
            continue
        for i, header in enumerate(headers):
            if header.group(1).startswith("USER") != (target == "user"):
                continue
            end = headers[i + 1].start() if i + 1 < len(headers) else len(part)
            content = FOLLOWING_PART.split(part[header.end():end].rstrip(), maxsplit=1)[0]
            found.extend(entry_texts(content))
            if i == len(headers) - 1:
                # No trailer: pinned Hermes tools/memory_tool_store.py:638-644.
                # An external provider can follow this entry (agent/system_prompt.py:516-543).
                # Keep raw paragraph boundaries until after choosing each possible entry prefix.
                entries = [e.strip() for e in content.split(ENTRY_DELIMITER) if e.strip()]
                if entries:
                    last = entries[-1]
                    found.extend(norm(last[:boundary.start()]) for boundary in re.finditer(r"\n\n", last)
                                 if last[:boundary.start()].strip())
    return found


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
        batch = isinstance(args.get("operations"), list) and bool(args["operations"])  # Hermes: if operations:
        listed = args["operations"] if batch else [args]
        # the entry each patch produced, when the result records it (memory_tool_store: patch, _batch)
        produced = (result.get("patched_entries_after") if batch else
                    {"1": result.get("patched_entry_after")}) if isinstance(result, dict) else None
        produced = produced if isinstance(produced, dict) else {}
        for i, op in enumerate(listed if isinstance(listed, list) else [{}]):
            ops.append(dict(op if isinstance(op, dict) else {}, target=args.get("target", "memory"),
                            record=call["record"], session=call["session"], applied=applied, report=report,
                            id=f"{call['id']}:{i + 1}", produced=produced.get(str(i + 1))))
    for op in ops:
        action = op.get("action")
        raw = op.get("old_text", "") if action == "remove" else op.get("content", op.get("new_text", ""))
        op["needle"] = norm(raw) if isinstance(raw, str) and isinstance(op.get("old_text", ""), str) else ""
        if op["applied"] and not known(action):  # a write Hermes applied must be one this audit can check
            raise ValueError(f"unknown_memory_action:{op['record']}")
        if op["applied"] and not isinstance(op["target"], str):
            raise ValueError(f"malformed_memory_target:{op['record']}")
        if op["applied"] and not op["needle"]:
            raise ValueError(f"empty_memory_content:{op['record']}")
    held = {}  # each target's entries as tracked here: a patch splices its span into the entry it locates
    for op in ops:
        act, op["entry"] = op.get("action"), op["needle"]  # the text a later whole-entry operation locates
        op["before_entry"] = None
        if not op["applied"] or not known(act) or not op["needle"] or not isinstance(op["target"], str):
            continue
        entries, old = held.setdefault(op["target"], []), "" if act == "add" else norm(op.get("old_text", ""))
        at = next((j for j, e in enumerate(entries) if e == old), None)  # a whole-entry match first, as Hermes
        if at is None:
            matches = [j for j, e in enumerate(entries) if old and old in e]
            if act == "patch" and isinstance(op["produced"], str) and op["produced"].strip():
                matches = [j for j in matches if entries[j].replace(old, op["needle"], 1) == norm(op["produced"])]
            at = matches[0] if len({entries[j] for j in matches}) == 1 else None
        op["before_entry"] = entries[at] if at is not None else None
        if act == "patch":
            recorded = op["produced"]
            op["entry"] = (norm(recorded) if isinstance(recorded, str) and recorded.strip() else
                           entries[at].replace(old, op["needle"], 1) if at is not None else None)
        elif act == "remove":
            op["entry"] = entries[at] if at is not None else None
        if at is None:
            entries += [] if act == "remove" or op["entry"] is None else [op["entry"]]
        elif act == "remove":
            del entries[at]
        elif act != "add":
            entries[at] = op["entry"]
    for i, op in enumerate(ops):
        action, needle = op.get("action"), op["needle"]
        if not known(action) or not needle or not isinstance(op["target"], str):
            # a malformed call Hermes refused, staged or left unclassified: never looked up
            label = action if known(action) else None  # a malformed action is model text: never reported
            op["report"]["operations"].append({"id": op["id"], "action": label, "reasons": [
                "staged_not_applied" if op["report"]["staged"] else "hermes_refused" if op["applied"] is False
                else "unclassified_result", "malformed_operation"]})
            continue
        nxt = next(((r, b) for r, b in requests if r["seq"] > op["record"] and r.get("cursor") and
                    r["cursor"]["session"] != op["session"] and r["cursor"]["turn"] == 1 and
                    r.get("role") in {"replay_main", "probe_main"}), None)
        def state(until, start, i=i, op=op, *, side=False):
            """The expected kind, tracked span and owning entry at `until`, through later applied calls.
            A removal is undone by a later call whose new text carries the removed text.
            Hermes `replace` rewrites the whole matched entry; `patch` splices only its span (memory_tool_store).
            A later replace or remove also finds the owning entry through its text outside a patched span."""
            (kind, value), changed = start, []
            entry = op["before_entry"] if side else op["entry"]
            for later in ops[i + 1:]:
                act = later.get("action")
                if (later["record"] >= until or not later["applied"] or later["target"] != op["target"]
                        or not known(act)):
                    continue
                old = norm(later.get("old_text", "")) if act in {"patch", "replace", "remove"} else ""
                new = "" if act == "remove" else norm(later.get("content", later.get("new_text", "")))
                if (kind == "present" and entry is not None and later["before_entry"] is not None
                        and entry != later["before_entry"]):
                    continue  # this edit belongs to a different recorded entry, even if the spans collide
                if kind == "present" and act == "patch" and old and entry and old in entry and value in entry:
                    # Splice by coordinates in the owning entry: either edge of the patch can overlap the
                    # tracked span without either string containing the other (issue #87).
                    left, patch_start = entry.index(value), entry.index(old)
                    right, end = left + len(value), patch_start + len(old)
                    if patch_start < right and left < end:
                        changed.append(later["id"])
                        value = entry[min(left, patch_start):patch_start] + new + entry[end:max(right, end)]
                    entry = later["entry"] or entry.replace(old, new, 1)
                elif kind == "present" and old and (old in value or value in old or
                                                     act != "patch" and entry and old in entry):
                    # a patch span inside this content is replaced; a replace or remove of its entry, or a span
                    # that encompasses it, replaces all of it
                    changed.append(later["id"])
                    patched = ("" if act == "remove" else value.replace(old, new) if act == "patch" and old in value
                               else new)
                    entry = later["entry"] if act != "remove" else entry
                    kind, value = ("present", patched) if patched else ("absent", value)
                elif kind == "present" and act == "patch" and old and entry and old in entry:
                    entry = entry.replace(old, new, 1)  # a span elsewhere in the owning entry
                elif kind == "absent" and new and value in new:
                    kind, entry = "present", later["entry"]
                    changed.append(later["id"])
            return (kind, value, entry), changed
        def holds(expect, text, whole_entries, *, side=False):
            kind, value, entry = expect
            if kind == "present":
                return entry is not None and entry in whole_entries
            if entry is not None:
                return entry not in whole_entries
            return side and value not in text
        start = ("absent", needle) if action == "remove" else ("present", needle)
        replaced = norm(op.get("old_text", "")) if action in {"patch", "replace"} else ""
        replaced = replaced if replaced and replaced not in needle else ""  # a patch keeping its old span checks nothing
        final, changed = state(float("inf"), start)
        raw_store = stores.get(op["target"], "")
        store, store_entries = norm(raw_store), entry_texts(raw_store)
        present = needle in store  # S7's raw span diagnostic; satisfaction below requires the whole entry
        store_ok = holds(final, store, store_entries)
        side = state(float("inf"), ("absent", replaced), side=True)[0] if replaced else None
        side_ok = holds(side, store, store_entries, side=True) if side else True
        visible, next_ok, next_side_ok, next_changed, wanted = None, None, None, [], final
        if nxt:
            r, b = nxt
            snap = norm(snapshot(b, request_wire(r, wire)))
            snap_entries = snapshot_entries(b, request_wire(r, wire), op["target"])
            wanted, next_changed = state(r["seq"], start)
            visible = needle in snap
            next_ok = holds(wanted, snap, snap_entries)
            next_side = state(r["seq"], ("absent", replaced), side=True)[0] if replaced else None
            next_side_ok = holds(next_side, snap, snap_entries, side=True) if next_side else True
        reasons = []
        if op["report"]["staged"]:
            reasons.append("staged_not_applied")
        elif op["applied"] is False:
            reasons.append("hermes_refused")
        if op["applied"] is None:
            reasons.append("unclassified_result")
        if op["applied"] and op["entry"] is None:
            reasons.append("entry_unidentifiable")
            store_ok, next_ok = False, False if nxt else None
        if changed:
            reasons.append("later_modified_or_removed")
        if nxt is None:
            reasons.append("no_next_session")
        gone = "remove" if action == "remove" else "removed_content"  # the effect expected absent
        if op["applied"] and op["entry"] is not None:
            if not store_ok:
                reasons.append("absent_from_final_store" if final[0] == "present" else f"{gone}_still_present")
            if next_ok is False:
                reasons.append("absent_from_next_session" if wanted[0] == "present" else f"{gone}_visible_next_session")
            if not side_ok:
                reasons.append("absent_from_final_store" if side[0] == "present" else "replaced_span_still_present")
            if next_side_ok is False:
                reasons.append("absent_from_next_session" if next_side[0] == "present" else "replaced_span_visible_next_session")
        store_ok, next_ok = store_ok and side_ok, next_ok and next_side_ok if nxt else next_ok
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


def hermes(home):
    """-> hook(calls, requests, wire). Reads only home/memories/MEMORY.md and USER.md, now; no symlinks."""
    home = Path(home)
    if not home.is_dir():
        raise ValueError("missing_hermes_home")
    stores = {}
    for target, name in (("memory", "MEMORY.md"), ("user", "USER.md")):
        path = home / "memories" / name
        if path.parent.is_symlink() or path.is_symlink():
            raise ValueError(f"hermes_store_symlink:{target}")
        stores[target] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return lambda calls, requests, wire: effects(calls, requests, stores, wire)
