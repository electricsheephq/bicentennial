"""A4: the effect of every executed write call on the final store and the next session (spike S7 effects,
unchanged), and the Hermes store hook. Reports hold record numbers, call ids and reason codes, never text."""

import json
from pathlib import Path

ACTIONS = {"add", "patch", "replace", "remove"}


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


def snapshot(body, wire):
    """The memory snapshot a request carries: chat system messages; Responses instructions and the system and
    developer messages in input, as the director extracts them (roles._items)."""
    if wire != "responses":
        return " ".join(strings([m.get("content", "") for m in body.get("messages", []) if m.get("role") == "system"]))
    items = body.get("input") if isinstance(body.get("input"), list) else []  # a string input is a user message
    found = [body["instructions"]] if isinstance(body.get("instructions"), str) else []
    for it in items:
        if isinstance(it, dict) and str(it.get("type", "message")) == "message" and it.get("role") in (
                "system", "developer"):
            found += blocks(it.get("content"))
    return " ".join(found)


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
        if op["applied"] and not known(action):  # a write Hermes applied must be one this audit can check
            raise ValueError(f"unknown_memory_action:{op['record']}")
        if op["applied"] and not isinstance(op["target"], str):
            raise ValueError(f"malformed_memory_target:{op['record']}")
        if op["applied"] and not op["needle"]:
            raise ValueError(f"empty_memory_content:{op['record']}")
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
        def state(until, start, i=i, op=op):
            """The expected effect at `until`, through later applied calls on the same target: ("present", text)
            or ("absent", text). A removal is undone by a later call whose new text carries the removed text."""
            (kind, value), changed = start, []
            for later in ops[i + 1:]:
                act = later.get("action")
                if (later["record"] >= until or not later["applied"] or later["target"] != op["target"]
                        or not known(act)):
                    continue
                old = norm(later.get("old_text", "")) if act in {"patch", "replace", "remove"} else ""
                new = "" if act == "remove" else norm(later.get("content", later.get("new_text", "")))
                if kind == "present" and old and (old in value or value in old):
                    # a span inside this content is replaced; a span that encompasses it replaces all of it
                    changed.append(later["id"])
                    patched = "" if act == "remove" else value.replace(old, new) if old in value else new
                    kind, value = ("present", patched) if patched else ("absent", value)
                elif kind == "absent" and new and value in new:
                    kind = "present"
                    changed.append(later["id"])
            return (kind, value), changed
        def holds(expect, text):
            return (expect[1] in text) == (expect[0] == "present")
        start = ("absent", needle) if action == "remove" else ("present", needle)
        replaced = norm(op.get("old_text", "")) if action in {"patch", "replace"} else ""
        replaced = replaced if replaced and replaced not in needle else ""  # a patch keeping its old span checks nothing
        final, changed = state(float("inf"), start)
        store = norm(stores.get(op["target"], ""))
        present = needle in store
        store_ok = holds(final, store)
        side_ok = holds(state(float("inf"), ("absent", replaced))[0], store) if replaced else True
        visible, next_ok, next_side_ok, next_changed, wanted = None, None, None, [], final
        if nxt:
            r, b = nxt
            snap = norm(snapshot(b, wire))
            wanted, next_changed = state(r["seq"], start)
            visible = needle in snap
            next_ok = holds(wanted, snap)
            next_side_ok = holds(state(r["seq"], ("absent", replaced))[0], snap) if replaced else True
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
        gone = "remove" if action == "remove" else "removed_content"  # the effect expected absent
        if op["applied"] and not store_ok:
            reasons.append("absent_from_final_store" if final[0] == "present" else f"{gone}_still_present")
        if op["applied"] and next_ok is False:
            reasons.append("absent_from_next_session" if wanted[0] == "present" else f"{gone}_visible_next_session")
        if op["applied"] and not side_ok:
            reasons.append("replaced_span_still_present")
        if op["applied"] and next_side_ok is False:
            reasons.append("replaced_span_visible_next_session")
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
