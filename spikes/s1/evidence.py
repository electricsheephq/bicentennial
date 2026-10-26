"""Spike S1 evidence: classify every recorded request, build the confusion tables, write minimized fixtures.

Sources (paths from flags, never from the repository):
  --s6a / --s6b    the S6a and S6b evidence folders: director ledgers with zstd blobs (and the S6b soak)
  --captures       S1's fresh captures: <dir>/hermes (a director ledger), <dir>/claude and <dir>/codex
                   (capture_stub ledgers)
Each director ledger already carries the director's own role and subrole: those are the labels. A fresh
Claude Code or Codex capture has no director, so its labels are manual, written below per request after
reading the capture, and checked against the harness's own compaction markers (compact_boundary events;
compacted rollout items). Writes the confusion tables and per-request disagreements to --out, and the
minimized shapes (no harness text) to --fixtures.

    python3.14 evidence.py --s6a <dir> --s6b <dir> --captures <dir> --out <dir> --fixtures fixtures/shapes.json
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

from compression import zstd

HERE = Path(__file__).resolve().parent
# AUX_TASKS: the S6a lane's per-task aliases; MOUNT: the S6b director's mount, written as /mount in fixtures
sys.path[:0] = [str(HERE), str(HERE.parent / "s6a"), str(HERE.parent / "s6b")]
import roles
from replay import AUX_TASKS
from sol_director import MOUNT

ROLE_OF_TASK = {"compression": "compaction", "title_generation": "title"}
# Director labels (role, subrole) -> S1 roles. Hermes' "summariser/compression" is the harness's own
# context compaction; S1 keeps "summariser" for a memory system's declared summary model.
LABEL = {("summariser", "compression"): "compaction", ("aux", "title_generation"): "title"}
# Manual labels for the fresh captures, by stub ledger seq (every other request: replay_main), each read from
# the capture: Claude Code's subagent request (the Explore agent the turn-9 directive spawned), its two
# compaction requests (auto at turn 30, then /compact); Codex's three inline compaction requests.
MANUAL = {"s1-claude": {11: "aux", 33: "compaction", 37: "compaction"}, "s1-codex": {7: "compaction",
                                                                                   9: "compaction",
                                                                                   11: "compaction"}}
# Disagreements with a director label, adjudicated from the harness's own log (REPORT.md): the role a correct
# director serves. The fixture expects this role; the confusion table keeps the director's label.
ADJUDICATED = {("s6a-r6-write", 128): "title"}  # Hermes' title call fell back to the main client after a timeout
HERMES_COMPACTION_LINE = "Compression summary call dispatched"  # one line per compaction request Hermes sends
DIRECTOR_RUNS = [("s6a", "fix/r6-write", "hermes-glm"), ("s6b", "r7c-write", "hermes-sol"),
                 ("s6b", "a2-live-smoke", "hermes-sol"), ("s6b", "a3-live-smoke", "hermes-sol"),
                 ("s6b", "a4-live-smoke", "hermes-sol"), ("s6b", "a5-live-smoke", "hermes-sol")]


def label(role: str, sub: str) -> str:
    if (role, sub) in LABEL:
        return LABEL[(role, sub)]
    return "aux" if role == "metadata" else role


def blob(run: Path, h: str):
    return json.loads(zstd.decompress((run / "ledger" / "blobs" / h[:2] / f"{h}.json.zst").read_bytes()))


def ids_in(obj) -> list[str]:
    """Call ids a served reply issued: chat tool_calls, Responses function calls, Anthropic tool_use."""
    if isinstance(obj, str):  # an SSE body
        obj = [json.loads(ln[5:]) for ln in obj.splitlines() if ln.startswith("data:") and ln[5:].strip()[:1] == "{"]
    out = []
    if isinstance(obj, list):
        for v in obj:
            out += ids_in(v)
    elif isinstance(obj, dict):
        if str(obj.get("type")).endswith("_call") and obj.get("call_id"):
            out.append(obj["call_id"])
        if obj.get("type") == "tool_use" or (obj.get("id") and obj.get("function")):  # Anthropic; a chat tool call
            out += [obj["id"]] if obj.get("id") else []
        for v in obj.values():
            out += ids_in(v)  # a string value may be an SSE body (the S6b director stores {"sse": text})
    return list(dict.fromkeys(out))


def life_ctx(args: dict, life: dict, aliases: bool) -> dict:
    lo, hi = (int(x) for x in str(args.get("sessions") or "1-10").split("-"))
    cap = args.get("max_turns") or None
    turns = [("replay", t) for s in life["sessions"] if lo <= s["index"] <= hi for t in s["turns"][:cap]]
    turns += [("probe", t) for p in (life.get("probes") or []) if args.get("probes") for t in p["turns"][:cap]]
    ctx = {"expected": [{"kind": k, "hash": roles.h16(t["user"].strip())} for k, t in turns],
           "aliases": {}, "path_aliases": {}}
    if aliases:  # the S6a lane names every auxiliary task by base URL and model (replay.py hermes_config)
        for t in AUX_TASKS:
            v = [ROLE_OF_TASK.get(t, "aux"), [ROLE_OF_TASK.get(t, "aux")]]
            ctx["path_aliases"][f"/aux/{t}/"] = v
            ctx["aliases"]["bicentennial-summariser" if t == "compression" else f"bicentennial-aux-{t}"] = v
    return ctx


def director_rows(run: Path) -> tuple[list[dict], list[dict]]:
    """(harness requests, director-originated write-turn bodies) of one director ledger, in ledger order."""
    rows, director = [], []
    for line in (run / "ledger" / "ledger.jsonl").read_text().splitlines():
        rec = json.loads(line)
        if rec.get("type") != "request":
            continue
        body = blob(run, rec["req"]) if rec.get("req") else None
        req = {"method": rec["method"], "path": rec["path"], "body": body}
        out = blob(run, rec["resp"]) if rec.get("resp") and rec["method"] == "POST" else None
        rows.append({"seq": rec["seq"], "req": req, "label": label(rec["role"], rec.get("subrole") or ""),
                     "director": f"{rec['role']}/{rec.get('subrole')}", "served": rec.get("served"),
                     "issued": ids_in(out), "issued_as": "write_turn" if rec.get("served") == "write_tool_calls" else None})
        for u in rec.get("upstream") or []:
            if u.get("kind") == "write_turn" and u.get("req"):
                director.append({"seq": rec["seq"], "req": {"method": "POST", "path": rec["path"],
                                                            "body": blob(run, u["req"])},
                                 "label": "write_turn", "director": "upstream/write_turn", "issued": []})
    return rows, director


def soak_rows(run: Path) -> list[dict]:
    rows = []
    for line in (run / "ledger" / "ledger.jsonl").read_text().splitlines():
        rec = json.loads(line)
        rows.append({"seq": rec["seq"], "req": {"method": "POST", "path": MOUNT + "/responses",
                                                "body": blob(run, rec["payload"])},
                     "label": label("summariser", "compression") if rec["kind"] == "summariser" else rec["kind"],
                     "director": f"soak/{rec['kind']}", "issued": []})
    return rows


def stub_rows(cap: Path, name: str) -> list[dict]:
    rows = []
    for line in (cap / "ledger.jsonl").read_text().splitlines():
        rec = json.loads(line)
        rows.append({"seq": rec["seq"], "req": {"method": rec["method"], "path": rec["path"], "body": rec["body"],
                                                "header_names": rec["header_names"]},
                     "label": MANUAL.get(name, {}).get(rec["seq"], "replay_main"), "director": "manual",
                     "issued": ids_in((rec.get("reply") or {}).get("sse_raw") or rec.get("reply"))})
    return rows


def stub_ctx(cap: Path, aliases: dict) -> dict:
    turns = json.loads((cap / "turns.json").read_text())
    return {"expected": [{"kind": "replay", "hash": roles.h16(t.strip())} for t in turns if not t.startswith("/")],
            "aliases": aliases, "path_aliases": {}}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--s6a", required=True)
    p.add_argument("--s6b", required=True)
    p.add_argument("--captures", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--fixtures", required=True)
    a = p.parse_args()
    ev, cap = {"s6a": Path(a.s6a), "s6b": Path(a.s6b)}, Path(a.captures)
    life = json.loads((HERE.parent / "s6a" / "micro_life.json").read_text())
    sources = []  # (name, harness, ctx, rows, dedupe, harness compaction count from its own markers)

    def hermes_count(d: Path) -> int:
        return (d / "hermes.log").read_text(errors="replace").count(HERMES_COMPACTION_LINE)

    def run_markers(d: Path) -> dict:
        return json.loads((d / "run.json").read_text())["markers"]

    for spike, run, harness in DIRECTOR_RUNS:
        d = ev[spike] / run
        args = json.loads((d / "summary.json").read_text())["args"]
        rows, director = director_rows(d)
        name = f"{spike}-{Path(run).name}"
        sources.append((name, harness, life_ctx(args, life, harness == "hermes-glm"), rows, False, hermes_count(d)))
        if director:
            sources.append((f"{name}-director-write-bodies", harness, life_ctx({}, {"sessions": []}, False),
                            director, True, 0))
    sources.append(("s6b-soak", "hermes-sol", life_ctx({}, {"sessions": []}, False), soak_rows(ev["s6b"] / "soak"), True,
                    None))
    h = cap / "hermes" / "s1-hermes-stub"
    hrows, hdir = director_rows(h)
    sources.append(("s1-hermes-stub", "hermes-glm", life_ctx(json.loads((h / "summary.json").read_text())["args"],
                                                             life, True), hrows, False, hermes_count(h)))
    sources.append(("s1-hermes-stub-director-write-bodies", "hermes-glm", life_ctx({}, {"sessions": []}, False),
                    hdir, True, 0))
    fast = {"bicentennial-cc-fast": ["aux", ["aux", "title"]]}  # the declared small-fast alias
    sources.append(("s1-claude", "claude-code", stub_ctx(cap / "claude", fast), stub_rows(cap / "claude", "s1-claude"),
                    False, run_markers(cap / "claude")["stream_compact_boundary"]))
    sources.append(("s1-codex", "codex", stub_ctx(cap / "codex", {}), stub_rows(cap / "codex", "s1-codex"), False,
                    run_markers(cap / "codex")["compacted"]))

    out, fixtures, table, wrong = Path(a.out), [], collections.defaultdict(collections.Counter), []
    out.mkdir(parents=True, exist_ok=True)
    methods = collections.defaultdict(collections.Counter)
    confirm = {}
    for name, harness, cdict, rows, dedupe, marked in sources:
        ctx = roles.Context.of(cdict)
        frows, seen, n_comp = [], {}, 0
        for r in rows:
            s = roles.shape(r["req"])
            res = roles.classify_shape(s, ctx)
            roles.advance(ctx, res, r["issued"], r.get("issued_as"))
            table[harness][(r["label"], res[0])] += 1
            methods[harness][res[1]] += 1
            if r["label"] != res[0]:
                wrong.append({"source": name, "seq": r["seq"], "director": r["director"], "served": r.get("served"),
                              "expected": r["label"], "got": res[0], "method": res[1], "evidence": res[2],
                              "shape": {k: s[k] for k in ("path", "model", "n_tools", "last_is", "markers", "len")}})
            n_comp += res[0] == "compaction"
            want = ADJUDICATED.get((name, r["seq"]), r["label"])
            row = {"seq": r["seq"], "shape": dict(s, path=s["path"].replace(MOUNT, "/mount", 1)), "issued": r["issued"],
                   "expected": want}
            row |= {"label": r["label"]} if want != r["label"] else {}
            row |= {"issued_as": r["issued_as"]} if r.get("issued_as") else {}
            key = json.dumps(s, sort_keys=True)
            if dedupe and key in seen:
                seen[key]["n"] += 1
                continue
            seen[key] = row | {"n": 1}
            frows.append(seen[key])
        fixtures.append({"source": name, "harness": harness, "ctx": cdict, "stateless": dedupe, "rows": frows,
                         "harness_compactions": marked})
        confirm[name] = {"classified_compaction": n_comp, "harness_marker_compactions": marked}
    Path(a.fixtures).write_text(json.dumps({"note": "minimized request shapes: no harness or life text",
                                            "sources": fixtures}, separators=(",", ":"), sort_keys=True) + "\n")
    summary = {}
    for harness, c in table.items():
        n = sum(c.values())
        summary[harness] = {"requests": n, "agree": sum(v for (e, g), v in c.items() if e == g),
                            "compaction_fn": sum(v for (e, g), v in c.items() if e == "compaction" != g),
                            "compaction_fp": sum(v for (e, g), v in c.items() if g == "compaction" != e),
                            "unknown": sum(v for (e, g), v in c.items() if g == "unknown"),
                            "methods": dict(methods[harness]),
                            "matrix": {f"{e} -> {g}": v for (e, g), v in sorted(c.items())}}
    (out / "confusion.json").write_text(json.dumps(summary, indent=1) + "\n")
    (out / "disagreements.json").write_text(json.dumps(wrong, indent=1) + "\n")
    (out / "compaction-confirm.json").write_text(json.dumps(confirm, indent=1) + "\n")
    print(json.dumps(confirm))
    print(json.dumps({h: {k: v for k, v in s.items() if k != "matrix"} for h, s in summary.items()}, indent=1))
    print(f"disagreements: {len(wrong)}")


if __name__ == "__main__":
    main()
