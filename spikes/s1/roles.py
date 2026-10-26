"""Spike S1: request roles. A harness-neutral, fail-closed classifier for every request a harness makes.

    classify(request, ctx) -> (role, method, evidence)

A request is {"wire", "method", "path", "header_names", "body"}; no header value is read. The work is split
in two pure steps, so a test can run on minimized shapes that hold no harness text:
    shape(request)             -> wire, path, sorted key set, model, the item-role sequence, the trailing
                                  tool-result ids, short hashes of the last user message's text blocks,
                                  text lengths, and the names of the markers present
    classify_shape(shape, ctx) -> (role, method, evidence)

The rule, in order (DESIGN §6.2, job 6):
  1. cursor       in the main frame (no marker of an auxiliary role): trailing tool results that all answer
                  call ids the director issued or forwarded, all of one role. An unmatched result fails closed
                  unless it answers a sibling call in the same call message as an issued id (a harness
                  split); a matching call alone never counts. Or the last user message carries the scripted
                  turn at the cursor, or the current turn again (a retry), or a harness continuation marker
                  on the current turn, with tools offered
  2. model_alias  a declared auxiliary alias: a per-task base-URL prefix or a model name. A marker may refine
                  the role within the alias's allowed set; a marker outside it is a conflict
  3. shape        exactly one marker role (a prefix hash of one text field), or a body-less endpoint shape
                  (count_tokens, a remote compaction endpoint, model-catalog and local-server probes)
  4. unknown      anything else, any conflict between steps, and a wire that disagrees with method and path. The caller must refuse to serve it.

Markers are stored as (field, prefix length, sha256 prefix), so no harness text is kept in this repository.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

ROLES = ("replay_main", "write_turn", "probe_main", "compaction", "summariser", "extraction", "title", "aux",
         "unknown")
METHODS = ("cursor", "model_alias", "shape", "unknown")
MAIN_ROLES = frozenset(("replay_main", "probe_main", "write_turn", "continuation"))
CONTINUATION = "continuation"  # a marker role, resolved to the current scripted turn's role


@dataclass(frozen=True)
class Signature:
    name: str
    role: str  # a role from ROLES, or CONTINUATION
    field: str  # system | first_user | last_user: lists of text blocks; any one block may match
    n: int  # prefix length in characters, after leading whitespace
    sha: str  # the first 16 hex digits of sha256(prefix)


def h16(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# Markers on the pinned versions (REPORT.md: source and derivation of each). The director's write suffix is
# the director's own text, not a harness's: it marks a director-originated write-turn body.
SIGNATURES = (
    Signature("hermes_title", "title", "system", 23, "14320f23ea7a6acd"),
    Signature("hermes_compression", "compaction", "first_user", 59, "7a0ff6e2921bafb5"),
    Signature("hermes_background_review", "aux", "last_user", 33, "f08684c0d919ea6f"),
    Signature("director_write_suffix", "write_turn", "last_user", 18, "90c608fd38ee1fb6"),
    Signature("claude_compact", "compaction", "last_user", 400, "9900234374beeae1"),
    Signature("claude_explore_subagent", "aux", "system", 48, "8cfab4fec11a87a8"),
    Signature("claude_task_notification", CONTINUATION, "last_user", 55, "d1f38e1c23dc1b5e"),
    Signature("codex_compact", "compaction", "last_user", 50, "d33420f8f7458410"),
)

ENDPOINTS = (  # (HTTP method, path pattern, wire, role): shapes decided by the endpoint alone
    ("POST", r"/messages/count_tokens$", "anthropic_count", "aux"),
    ("POST", r"/responses/compact$", "openai_responses_compact", "compaction"),
    ("GET", r"/models(/[^/]+)?$", "metadata", "aux"),
    ("GET", r"/(api/tags|api/v1/models|v1/props|props|version)$", "metadata", "aux"),
    ("GET", r"/wham/usage$", "metadata", "aux"),
)
BODY_WIRES = {"/chat/completions": "openai_chat", "/responses": "openai_responses", "/messages": "anthropic"}


def wire_of(method: str, path: str) -> str:
    p = path.split("?")[0].rstrip("/")
    for m, rx, wire, _ in ENDPOINTS:
        if m == method and re.search(rx, p):
            return wire
    return next((w for suffix, w in BODY_WIRES.items() if method == "POST" and p.endswith(suffix)), "other")


# ---- shape: a request reduced to features that hold no harness text ----------------------------------------
def _blocks(content) -> list[str]:
    if isinstance(content, str):
        return [content]
    return [p["text"] for p in content or [] if isinstance(p, dict) and isinstance(p.get("text"), str)
            and p.get("type") in (None, "text", "input_text", "output_text")]


def _parts(m: dict) -> list:
    return m["content"] if isinstance(m.get("content"), list) else []


def _items(wire: str, body: dict) -> tuple[str, tuple[list, list], list[list[str]], list[str]]:
    """(role tokens, (trailing tool-result ids, ids of the calls they answer), user text-block lists in order,
    system blocks) for one wire.
    Tokens: s system/developer, u user text, a assistant, c tool call, t tool result, r reasoning, x other."""
    toks, users, system, tail, calls = [], [], [], [], []
    if wire == "openai_chat":
        msgs = [m for m in body.get("messages") or [] if isinstance(m, dict)]
        for m in msgs:
            r = m.get("role")
            if r in ("system", "developer"):
                toks.append("s")
                system += _blocks(m.get("content"))
            elif r == "user":
                toks.append("u")
                users.append(_blocks(m.get("content")))
            else:
                toks.append({"assistant": "c" if m.get("tool_calls") else "a", "tool": "t"}.get(r, "x"))
        for m in reversed(msgs):
            if m.get("role") != "tool":
                calls = [tc.get("id") or "" for tc in m.get("tool_calls") or []] if tail and m.get("role") == "assistant" else []
                break
            tail.append(m.get("tool_call_id") or "")
    elif wire == "openai_responses":
        items = body.get("input") or []
        items = [{"type": "message", "role": "user", "content": items}] if isinstance(items, str) else items
        items = [it for it in items if isinstance(it, dict)]
        system += [body["instructions"]] if isinstance(body.get("instructions"), str) else []
        for it in items:
            t, r = str(it.get("type", "message")), it.get("role")
            if t == "message":
                toks.append({"user": "u", "assistant": "a", "system": "s", "developer": "s"}.get(r, "x"))
                users += [_blocks(it.get("content"))] if r == "user" else []
            else:
                toks.append("t" if t.endswith("_output") else "c" if t.endswith("_call") else "r" if t == "reasoning"
                            else "x")
        if items and str(items[-1].get("type", "")).endswith("_output"):
            for it in reversed(items):
                if not str(it.get("type", "")).endswith(("_output", "_call")):
                    break
                (tail if str(it.get("type")).endswith("_output") else calls).append(it.get("call_id") or "")
    elif wire == "anthropic":
        system += _blocks(body.get("system"))
        convo = []
        for m in (m for m in body.get("messages") or [] if isinstance(m, dict)):
            kinds = {p.get("type") for p in _parts(m) if isinstance(p, dict)}
            if m.get("role") == "system":  # mid-conversation harness context: system text, not a turn
                toks.append("s")
                system += _blocks(m.get("content"))
                continue
            convo.append(m)
            if m.get("role") == "user":
                toks.append("t" if "tool_result" in kinds else "u")
                users += [] if "tool_result" in kinds else [_blocks(m.get("content"))]
            else:
                toks.append("c" if "tool_use" in kinds else "a" if m.get("role") == "assistant" else "x")
        if [t for t in toks if t != "s"][-1:] == ["t"]:
            tail = [p.get("tool_use_id") or "" for p in _parts(convo[-1]) if p.get("type") == "tool_result"]
            calls = [p.get("id") or "" for p in _parts(convo[-2]) if p.get("type") == "tool_use"] if len(convo) > 1 else []
    return "".join(toks), (tail, calls), users, system


def markers(fields: dict[str, list[str]], signatures=SIGNATURES) -> list[str]:
    return [s.name for s in signatures if any(len(b.lstrip()) >= s.n and h16(b.lstrip()[:s.n]) == s.sha
                                              for b in fields.get(s.field) or [])]


def shape(req: dict, signatures=SIGNATURES) -> dict:
    method, path = req.get("method", "POST"), (req.get("path") or "").split("?")[0]
    wire = req.get("wire") or wire_of(method, path)
    body = req.get("body") if isinstance(req.get("body"), dict) else {}
    toks, tail, users, system = _items(wire, body)
    last = users[-1] if users else []
    whole = "\n".join(last).strip()
    final = toks.rstrip("s")[-1:]  # trailing system context is not a turn
    fields = {"system": system, "first_user": users[0] if users else [], "last_user": last}
    return {"wire": wire, "method": method, "path": path, "keys": sorted(body), "model": body.get("model"),
            "seq": toks, "n_tools": len(body.get("tools") or []), "tail_ids": tail[0], "tail_calls": tail[1],
            "last_is": {"u": "user_text", "t": "tool_result"}.get(final, "other"),
            "user_hashes": sorted({h16(whole)} | {h16(b.strip()) for b in last if b.strip()}) if whole else [],
            "len": {"system": sum(map(len, system)), "last_user": len(whole)},
            "markers": markers(fields, signatures)}


# ---- the director context and the rule ----------------------------------------------------------------------
@dataclass
class Context:
    """What the director knows: the script cursor, the call ids it issued or forwarded, declared aliases."""
    expected: list[dict] = field(default_factory=list)  # [{"kind": "replay"|"probe", "hash": h16(user text)}]
    cursor: int = 0
    current: dict | None = None
    issued: dict[str, str] = field(default_factory=dict)  # call id -> role of the request whose reply issued it
    aliases: dict[str, tuple[str, frozenset]] = field(default_factory=dict)  # model -> (default, allowed)
    path_aliases: dict[str, tuple[str, frozenset]] = field(default_factory=dict)  # path prefix -> same
    signatures: tuple = SIGNATURES

    @classmethod
    def of(cls, c: dict) -> Context:
        """From the JSON form: {"expected": [...], "aliases": {model: [default, [allowed]]}, "path_aliases": ...}."""
        fz = {k: {a: (d, frozenset(al)) for a, (d, al) in c.get(k, {}).items()} for k in ("aliases", "path_aliases")}
        return cls(expected=list(c.get("expected") or []), **fz)


def alias(default: str, *also: str) -> tuple[str, frozenset]:
    return default, frozenset((default, *also))


def _turn_role(turn: dict) -> str:
    return "replay_main" if turn["kind"] == "replay" else "probe_main"


def classify_shape(s: dict, ctx: Context) -> tuple[str, str, dict]:
    roles_of = {x.name: x.role for x in ctx.signatures}
    mroles = {roles_of.get(m, "unknown") for m in s["markers"]}
    ev = {"markers": s["markers"]} if s["markers"] else {}

    def done(role: str, method: str, **more) -> tuple[str, str, dict]:
        stray = mroles - {role, CONTINUATION}
        if stray:  # a marker naming another role is conflicting evidence: fail closed
            return "unknown", "unknown", {**ev, **more, "conflict": f"{method}:{role} vs {sorted(stray)}"}
        return role, method, {**ev, **more}

    if s["wire"] != wire_of(s["method"], s["path"]):  # supplied wire metadata must agree with method and path
        return "unknown", "unknown", {"reason": "wire, method and path disagree"}
    if s["wire"] not in BODY_WIRES.values():  # body-less endpoint shapes
        for m, rx, wire, role in ENDPOINTS:
            if s["method"] == m and re.search(rx, s["path"].rstrip("/")):
                return role, "shape", {"endpoint": wire}
        return "unknown", "unknown", {"reason": "unrecognised wire or path"}
    if mroles <= MAIN_ROLES:  # 1. cursor, in the main frame only
        if s["tail_ids"]:  # the results answered here: matched by their own ids, never by the calls alone
            got = {ctx.issued[cid] for cid in s["tail_ids"] if cid in ctx.issued}
            # a result with an unissued id passes only as a sibling the harness added to a call message that
            # also carries an issued id (Hermes splits one forwarded call into two); any other fails closed
            stray = [cid for cid in s["tail_ids"] if cid not in ctx.issued and cid not in s["tail_calls"]]
            if len(got) != 1 or stray:
                return "unknown", "unknown", {**ev, "reason": "tool result for an unissued call id or mixed roles"}
            return done(got.pop(), "cursor", call_id=next(c for c in s["tail_ids"] if c in ctx.issued))
        if s["last_is"] == "user_text" and s["n_tools"] > 0:
            if ctx.cursor < len(ctx.expected) and ctx.expected[ctx.cursor]["hash"] in s["user_hashes"]:
                return done(_turn_role(ctx.expected[ctx.cursor]), "cursor", turn=ctx.cursor)
            if ctx.current and ctx.current["hash"] in s["user_hashes"]:
                return done(_turn_role(ctx.current), "cursor", turn="retry")
            if ctx.current and CONTINUATION in mroles:
                return done(_turn_role(ctx.current), "cursor", turn=CONTINUATION)
    mroles.discard(CONTINUATION)  # outside a scripted turn a continuation marker decides nothing
    hits = [v for k, v in ctx.path_aliases.items() if s["path"].startswith(k)]  # 2. model alias
    hits += [ctx.aliases[s["model"]]] if s["model"] in ctx.aliases else []
    if hits and not s["seq"]:  # an alias on a body with no messages or input decides nothing
        return "unknown", "unknown", {"reason": "alias on an empty body", "alias": s["model"]}
    if hits:
        allowed = frozenset.intersection(*(a for _, a in hits))
        defaults = {d for d, _ in hits}
        if len(mroles & allowed) == 1 and mroles <= allowed:
            return done(next(iter(mroles)), "model_alias", alias=s["model"])
        if not mroles and len(defaults) == 1 and defaults <= allowed:
            return done(next(iter(defaults)), "model_alias", alias=s["model"])
        return "unknown", "unknown", {**ev, "conflict": "alias", "alias": s["model"]}
    if len(mroles) == 1 and mroles <= set(ROLES) - {"unknown"}:  # 3. shape
        return done(next(iter(mroles)), "shape")
    return "unknown", "unknown", {**ev, "reason": "conflicting markers" if mroles else "no rule matched"}


def classify(req: dict, ctx: Context) -> tuple[str, str, dict]:
    return classify_shape(shape(req, ctx.signatures), ctx)


def advance(ctx: Context, result: tuple[str, str, dict], issued_ids=(), issued_as: str | None = None) -> None:
    """The director's bookkeeping after serving a request: move the cursor on a scripted-turn match, and
    remember the call ids its reply issued, under the request's role or the role it served them as (a write
    turn's director-issued calls are write_turn)."""
    role, method, ev = result
    if method == "cursor" and isinstance(ev.get("turn"), int):
        ctx.current, ctx.cursor = ctx.expected[ev["turn"]], ev["turn"] + 1
    if role != "unknown":
        for cid in issued_ids:
            ctx.issued.setdefault(cid, issued_as or role)


def walk(ctx: Context, rows: list[dict]) -> list[tuple[str, str, dict]]:
    """Classifies recorded rows ({"shape", "issued", "issued_as"}) in order, as a director serves them."""
    out = []
    for row in rows:
        res = classify_shape(row["shape"], ctx)
        advance(ctx, res, row.get("issued") or (), row.get("issued_as"))
        out.append(res)
    return out
