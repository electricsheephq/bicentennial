"""R08 acceptance: an offline fake harness drives the director over loopback HTTP on both wires.

The replay rehydrates R01's recorded Hermes request shapes (tests/director/fixtures/shapes.json) into bodies,
with the S6a micro-life's own user text and synthetic marker text (the fixtures hold marker hashes, never
harness text, so each harness marker is re-keyed to a synthetic text of the same name, role and field). No
Hermes, no network and no model call: a fake responder answers everything the script does not.
"""

import http.client
import json
import runpy
import socket
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.director import roles
from bicentennial.director.core import Director
from bicentennial.director.responder import Reply
from bicentennial.director.routes import RouteTable
from bicentennial.director.serve import serve, shutdown
from bicentennial.director.wire import responses
from bicentennial.keyed import mint_id
from bicentennial.ledger import BlobStore, CredentialLeak, Guard, stable_digest
from bicentennial.runtime.clock import SimClock

ROOT = Path(__file__).resolve().parents[2]
FIX = {s["source"]: s for s in json.loads((ROOT / "tests/director/fixtures/shapes.json").read_text())["sources"]}
LIFE = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
compile_micro_life = runpy.run_path(str(ROOT / "tests/contracts/test_run_contracts.py"))["compile_micro_life"]
SCRIPT = compile_micro_life(LIFE)
TEXTS = {roles.h16(t["user"].strip()): t["user"] for s in (*LIFE["sessions"], *LIFE["probes"]) for t in s["turns"]}
LOCK, BASE, STEP, DAY = "ab" * 32, 1_600_000_000, 60, 86400
ROUTES = {"routes": [{"system": "hermes", "segment": "seg0", "probe_model": "probe-model", "alias": "bicentennial-main",
                      "summariser": "summary-model", "vision": None, "served_by": "scripted"}]}
SYN = {"hermes_title": "Synthetic title marker", "hermes_compression": "Synthetic compression marker",
       "hermes_background_review": "Synthetic background review marker"}
SIGS = tuple(roles.Signature(s.name, s.role, s.field, len(SYN[s.name]), roles.h16(SYN[s.name])) if s.name in SYN
             else s for s in roles.SIGNATURES)
TOOL_NAMES = ["memory", "session_search", "todo", "skill_view", "terminal", "read_file"]
LEDGER_ROLE = {"title": "aux", "compaction": "summariser"}  # route_role's ledger names for the S1 roles
WIRE_SOURCE = {"chat": "s6a-r6-write", "responses": "s6b-r7c-write"}


class Fake:
    """Answers every responder call; n_calls tool calls per request, then text."""

    def __init__(self, model=None, served_by="scripted", fail=()):
        self.model, self.served_by, self.fail, self.calls, self.n_calls = model, served_by, fail, [], 0

    def respond(self, call):
        self.calls.append(call)
        if call.role in self.fail:
            raise RuntimeError("fake responder failure")
        model = self.model or call.model
        if call.wire == "embeddings":
            return Reply(200, "fake", self.served_by, model, embedding=[[3, 0, -1]], scale=4)
        tools = [t["function"]["name"] if call.wire == "chat" else t["name"] for t in call.body.get("tools") or []]
        calls = tuple({"name": (tools or ["recall"])[0], "arguments": json.dumps({"action": "add", "content": "x"})}
                      for _ in range(self.n_calls))
        return Reply(200, "fake", self.served_by, model, text=f"fake {call.role} text, discard me", tool_calls=calls)


def make(tmp, responder, sandbox="sandbox", **kw):
    clock = SimClock(tmp / "clock.json", BASE, STEP)
    d = Director(kw.pop("script", SCRIPT), RouteTable.load(ROUTES), "hermes", "s6a-micro", "B0", "run-1", ("memory",),
                 responder, clock, Guard([]), {"sandbox_root": str(tmp / sandbox), "director_port": "1"}, **kw)
    d.ctx.signatures = SIGS
    return d


def start(d, tmp, session=1):
    d.start_session(session, BASE + session * DAY, LOCK, f"attempt-s{session}", tmp / "ledger")


def records(tmp):
    lines = (tmp / "ledger" / "ledger.jsonl").read_bytes().splitlines()
    recs = [json.loads(line) for line in lines]
    for rec in recs:
        validate("ledger-record", rec)
    return recs


# ---- the fake harness ---------------------------------------------------------------------------------------
def tools_of(n, chat):
    names = (TOOL_NAMES + [f"tool_{i}" for i in range(n)])[:n]
    params = {"type": "object", "properties": {}}
    return [{"type": "function", "function": {"name": x, "parameters": params}} if chat
            else {"type": "function", "name": x, "parameters": params} for x in names]


def rehydrate(row, ids, env):
    """A body with the recorded shape: keys, item sequence, trailing call batch (recorded ids mapped onto the
    director's), last user text and markers."""
    sh = row["shape"]
    if sh["method"] == "GET":
        return "GET", sh["path"], None
    chat, mk, toks = sh["wire"] == "openai_chat", set(sh["markers"]), sh["seq"]
    last = next((TEXTS[h] for h in sh["user_hashes"] if h in TEXTS), "a synthetic user message")
    last = SYN["hermes_background_review"] + " now" if "hermes_background_review" in mk else last
    system = SYN["hermes_title"] + " for this session" if "hermes_title" in mk else env
    tail = [ids.get(x, x) for x in (reversed(sh["tail_ids"]) if chat else sh["tail_ids"])]
    calls = [ids.get(x, x) for x in sh["tail_calls"]]
    k = len(toks) - len(toks.rstrip("t")) if tail else 0
    k = len(toks) - k
    items, users = [], 0

    def part(text, kind):
        return text if chat else [{"type": kind, "text": text}]

    for i, tok in enumerate(toks):
        if tok == "u":
            users += 1
            text = last if users == toks.count("u") else "an earlier synthetic turn"
            text = SYN["hermes_compression"] + " of the above" if users == 1 and "hermes_compression" in mk else text
            items.append({"role": "user", "content": part(text, "input_text")} if chat
                         else {"type": "message", "role": "user", "content": part(text, "input_text")})
        elif tok == "s":
            items.append({"role": "system", "content": system} if chat
                         else {"type": "message", "role": "developer", "content": part(system, "input_text")})
        elif tok == "a":
            items.append({"role": "assistant", "content": "an earlier answer"} if chat else
                         {"type": "message", "role": "assistant", "content": part("an earlier answer", "output_text")})
        elif tok == "r":
            items.append({"type": "reasoning", "summary": []})
        elif tok == "c" and chat:
            got = calls if tail and i == k - 1 else [f"hist-{i}"]
            items.append({"role": "assistant", "content": "", "tool_calls": [
                {"id": c, "type": "function", "function": {"name": "memory", "arguments": "{}"}} for c in got]})
        elif tok == "c":
            got = calls[i - (k - len(calls))] if tail and k - len(calls) <= i < k else f"hist-{i}"
            items.append({"type": "function_call", "call_id": got, "name": "memory", "arguments": "{}"})
        else:  # t
            cid = tail[i - k] if i >= k else f"hist-{i}"
            items.append({"role": "tool", "tool_call_id": cid, "content": "ok"} if chat
                         else {"type": "function_call_output", "call_id": cid, "output": "ok"})
    fill = {"model": sh["model"], "messages": items, "input": items, "tools": tools_of(sh["n_tools"], chat),
            "instructions": system, "stream": True, "stream_options": {"include_usage": True},
            "reasoning_effort": "medium", "response_format": {"type": "json_object"}, "store": False,
            "include": ["reasoning.encrypted_content"], "parallel_tool_calls": True, "tool_choice": "auto",
            "prompt_cache_key": "synthetic-cache-key", "reasoning": {"effort": "medium"}}
    return "POST", sh["path"], {key: fill[key] for key in sh["keys"]}


def send(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        raw = b"" if body is None else json.dumps(body).encode()
        conn.request(method, path, body=raw or None, headers={
            "Content-Type": "application/json", "Authorization": "Bearer test-placeholder", **(headers or {})})
        resp = conn.getresponse()
        return resp.status, resp.getheader("Content-Type"), resp.read()
    finally:
        conn.close()


def answer(ctype, data):
    """(text, director-issued call ids) from a chat JSON, chat SSE or Responses SSE answer."""
    if ctype != "text/event-stream":
        obj = json.loads(data)
        msg = obj["choices"][0]["message"] if "choices" in obj else {}
        return msg.get("content") or "", [c["id"] for c in msg.get("tool_calls") or []]
    events, text, ids = responses.parse_sse(data), "", []
    for e in events:
        if e.get("object") == "chat.completion.chunk" and e["choices"]:
            delta = e["choices"][0]["delta"]
            text += delta.get("content") or ""
            ids += [c["id"] for c in delta.get("tool_calls") or []]
        elif e.get("type") == "response.output_item.done":
            item = e["item"]
            text += item["content"][0]["text"] if item["type"] == "message" else ""
            ids += [item["call_id"]] if item["type"] == "function_call" else []
    return text, ids


def replay(source, d, fake, tmp, port):
    """Sends every recorded request in order, starting each session before its first scripted turn."""
    rows = FIX[source]["rows"]
    walked = roles.walk(roles.Context.of(FIX[source]["ctx"]), rows)
    env = f"Synthetic system prompt. Workspace {tmp / 'sandbox'}; director http://127.0.0.1:{port}/main/v1"
    ids, out, session = {}, [], None
    for row, s1 in zip(rows, walked, strict=True):
        n = s1[2].get("turn")
        want = d.turns[n]["session"] if isinstance(n, int) else session or 1
        if want != session:
            start(d, tmp, session=want)
            session = want
        method, path, body = rehydrate(row, ids, env)
        fake.n_calls = len(row["issued"])
        status, ctype, data = send(port, method, path, body)
        text, got = answer(ctype, data) if status == 200 and method == "POST" else ("", [])
        ids.update(zip(row["issued"], got, strict=True))  # the recorded ids, mapped onto the director's
        out.append((row, s1, status, text))
    return out


@pytest.fixture
def no_egress(monkeypatch):
    """Refuse and count any connection to a non-loopback address; count loopback ones."""
    seen = {"loopback": 0, "outbound": 0}
    real_create, real_connect = socket.create_connection, socket.socket.connect

    def host_ok(address):
        host = address[0] if isinstance(address, tuple) else address
        seen["loopback" if host in ("127.0.0.1", "::1", "localhost") else "outbound"] += 1
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError("non-loopback connection refused by the test")

    def create(address, *a, **kw):
        host_ok(address)
        return real_create(address, *a, **kw)

    def connect(self, address):
        host_ok(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket, "create_connection", create)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return seen


@pytest.mark.parametrize("wire", sorted(WIRE_SOURCE))
def test_micro_life_replay_on_both_wires(wire, tmp_path, no_egress):
    fake = Fake()
    d = make(tmp_path, fake)
    server = serve(d)
    try:
        results = replay(WIRE_SOURCE[wire], d, fake, tmp_path, server.port)
    finally:
        shutdown(server)
        d.close()
    recs = records(tmp_path)
    assert len(recs) == len(results)
    assert no_egress["outbound"] == 0 and no_egress["loopback"] >= len(results)  # the patch saw every connection
    assert not [r for r in recs if r["role"] == "unknown"]  # every request classified
    readbacks = [r for r in recs if "write_turn_readback" in r]
    assert len(readbacks) == 60 and all(r["write_turn_readback"] for r in readbacks)  # one per replay turn
    by_turn = {(t["session"], t["turn"]): t for t in d.turns}
    sim = {}
    for (row, _, status, text), rec in zip(results, recs, strict=True):
        assert rec["role"] == LEDGER_ROLE.get(row["expected"], row["expected"]) and rec["status"] == status, row["seq"]
        assert rec["incoming_auth_dropped"] is True and rec["served_by"] == "scripted"
        if row["expected"] == "title":
            assert rec["subrole"] == "title_generation"
        if rec["role"] == "write_turn":  # the harness's tool results: the scripted turn, never the fake's text
            turn = by_turn[rec["cursor"]["session"], rec["cursor"]["turn"]]
            assert (rec["subrole"], rec["served"], text) == ("tool_results", "script", turn["assistant"])
        if "write_turn_readback" in rec:
            want = "write_tool_calls" if row["issued"] else "script"
            assert rec["served"] == want and rec["write_calls"] == len(row["issued"])
            assert text == ("" if row["issued"] else by_turn[rec["cursor"]["session"], rec["cursor"]["turn"]]["assistant"])
            assert rec["upstream"][0]["role"] == "write_turn"
        session = rec["cursor"]["session"] if rec["cursor"] else max(sim, default=1)
        start_s = BASE + session * DAY
        if rec["subrole"] == "cursor":  # sim_now steps by step_s per new turn, from the session's instant
            assert rec["sim_now"] == start_s + STEP * rec["cursor"]["turn"]
            sim[session] = rec["sim_now"]
        else:
            quoted = next((t for t in reversed(d.turns) if t["session"] == session and
                           roles.h16(t["user"].strip()) in row["shape"]["user_hashes"]), None)
            assert rec["sim_now"] == (start_s + STEP * quoted["turn"] if quoted else sim.get(session, start_s))
    if wire == "chat":  # r6 request 128: Hermes's title fallback to the main client is a title
        rec = recs[[row["seq"] for row, *_ in results].index(128)]
        assert (rec["role"], rec["subrole"], rec["model_in"]) == ("aux", "title_generation", "bicentennial-main")
    assert {c.role for c in fake.calls} == {"write_turn", "probe_main", "aux", "summariser"}
    assert all(c.model == ("summary-model" if c.role == "summariser" else "probe-model") for c in fake.calls)


def test_two_runs_give_the_same_stable_digest(tmp_path):
    runs = []
    for name in ("a", "b"):
        tmp = tmp_path / name
        tmp.mkdir()
        fake = Fake()
        d = make(tmp, fake)
        runs.append((tmp, fake, d, serve(d)))
    try:  # both servers bound at once, so the ports differ
        for tmp, fake, d, server in runs:
            replay(WIRE_SOURCE["chat"], d, fake, tmp, server.port)
            replay_tail = send(server.port, "GET", "/main/api/v1/models")
            assert replay_tail[0] == 200
    finally:
        for _, _, d, server in runs:
            shutdown(server)
            d.close()
    (ta, _, da, sa), (tb, _, db, sb) = runs
    assert sa.port != sb.port and da.run_values != db.run_values
    ra, rb = records(ta), records(tb)
    assert [r["req"] for r in ra] != [r["req"] for r in rb]  # the raw bodies carry each run's port and root
    assert stable_digest(ra, da.run_values) == stable_digest(rb, db.run_values)


# ---- synthetic Hermes-like bodies ------------------------------------------------------------------------------
TURN1 = LIFE["sessions"][0]["turns"][0]


def turn_body(text=TURN1["user"], tools=("memory", "session_search"), **kw):
    return {"model": "bicentennial-main", "messages": [{"role": "system", "content": "s"},
                                                       {"role": "user", "content": text}],
            "tools": [{"type": "function", "function": {"name": x}} for x in tools], **kw}


def post(d, path, body, headers=None):
    status, hdrs, data = d.handle("POST", path, {"Authorization": "x", **(headers or {})},
                                  body if isinstance(body, bytes) else json.dumps(body).encode())
    return status, hdrs["Content-Type"], data


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("by_path", [False, True])
@pytest.mark.parametrize("vision", [None, "vision-a"])
def test_aux_vision_uses_vision_route_or_refuses(wire, by_path, vision, tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    d.table = RouteTable.load({"routes": [dict(ROUTES["routes"][0], vision=vision)]})
    start(d, tmp_path)
    body = {"model": "bicentennial-main" if by_path else "bicentennial-aux-vision",
            "messages" if wire == "chat" else "input": [{"role": "user", "content": "Describe this image"}]}
    path = ("/aux/vision/v1/" if by_path else "/main/v1/") + (
        "chat/completions" if wire == "chat" else "responses")
    try:
        status, _, _ = post(d, path, body)
        (rec,) = records(tmp_path)
        assert (rec["role"], rec["subrole"], rec["status"]) == ("aux", "vision", status)
        if vision is None:
            assert status == 400 and rec["served"] == "no_vision_route"
            assert not fake.calls and rec["upstream"] == []
        else:
            assert status == 200 and rec["served"] == "responder_fake"
            (call,) = fake.calls
            assert (call.role, call.subrole, call.model, call.body) == ("aux", "vision", "vision-a", body)
    finally:
        d.close()


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("main", [False, True])
@pytest.mark.parametrize("floats", [{"temperature": 0.5}, {"top_p": 0.9, "temperature": 0.5}, {"top_p": 0.9}])
def test_classified_float_refusal_then_canonical_retry(wire, main, floats, tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    body = turn_body(tools=("todo",)) if main else {
        "model": "bicentennial-aux-vision", "messages": [{"role": "user", "content": "Describe this image"}]}
    d.route["vision"] = "vision-a"
    if wire == "responses":
        body["input"] = body.pop("messages")
        body["tools"] = [{"type": "function", "name": "todo"}] if main else []
    path = "/main/v1/" + ("chat/completions" if wire == "chat" else "responses")
    raw = json.dumps(body | floats, indent=2).encode()
    before = deepcopy(d.ctx), d.clock.path.read_bytes(), d.clock.sim_t_s
    try:
        status, _, data = post(d, path, raw)
        assert status == 400
        assert json.loads(data)["error"]["message"] == f"director: unsupported parameter: {sorted(floats)[0]}"
        (rec,) = records(tmp_path)
        expected_role = ("replay_main", "cursor") if main else ("aux", "vision")
        assert (rec["role"], rec["subrole"], rec["served"]) == (*expected_role, "refused_float")
        assert rec["cursor"] == ({"session": 1, "turn": 1} if main else None)
        assert rec["upstream"] == [] and not fake.calls
        store = BlobStore(tmp_path / "ledger/blobs", None)
        assert json.loads(store.get(rec["req"])) == {
            "body_sha256": sha256(raw).hexdigest(), "float_keys": sorted(floats)}
        assert not store._path(sha256(canon(body)).hexdigest()).exists()
        assert (d.ctx, d.clock.path.read_bytes(), d.clock.sim_t_s) == before
        assert d._req == {} and not d.pending and not d.id_roles and d.n_ids == 0
        status, ctype, data = post(d, path, body)
        assert status == 200
        retry = records(tmp_path)[1]
        assert (retry["role"], retry["subrole"]) == expected_role
        if main:
            assert answer(ctype, data)[0] == TURN1["assistant"]
            assert retry["served"] == "script" and not fake.calls
        else:
            assert fake.calls[0].model == "vision-a" and fake.calls[0].body == body
    finally:
        d.close()


@pytest.mark.parametrize("path,body", [
    ("/main/v1/chat/completions", turn_body() | {"nested": {"value": 0.5}}),
    ("/main/v1/chat/completions", turn_body() | {"temperature": 0.5, "nested": [0.5]}),
    ("/main/v1/chat/completions", {"model": "unknown", "temperature": 0.5}),
    ("/main/v1/embeddings", {"model": "embed", "input": "hello", "temperature": 0.5}),
])
def test_nonclassifiable_float_bodies_keep_malformed_refusal(path, body, tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    raw = json.dumps(body).encode()
    try:
        status, _, data = post(d, path, raw)
        assert status == 400 and json.loads(data)["error"]["message"] == "director: malformed request body"
        (rec,) = records(tmp_path)
        assert (rec["role"], rec["subrole"], rec["served"], rec["cursor"]) == (
            "unknown", "malformed_body", "refused_unknown", None)
        store = BlobStore(tmp_path / "ledger/blobs", None)
        assert json.loads(store.get(rec["req"])) == {"body_sha256": sha256(raw).hexdigest()}
        assert not fake.calls and rec["upstream"] == []
        assert d.ctx.cursor == 0 and d._req == {}
    finally:
        d.close()


def title_order_run(tmp, wire, title_first, sessions=1, *, script=None, title_chars=None):
    tmp.mkdir()
    if script is None:
        script = dict(SCRIPT, sessions=[dict(s, turns=s["turns"][:1]) for s in SCRIPT["sessions"][:sessions]])
    fake = Fake()
    fake.n_calls = 1
    d = make(tmp, fake, script=script)
    path = "chat/completions" if wire == "chat" else "responses"
    try:
        for session in script["sessions"]:
            start(d, tmp, session["index"])
            user = session["turns"][0]["user"]
            main = turn_body(user) if wire == "chat" else {
                "model": "bicentennial-main", "input": user, "tools": tools_of(1, False)}
            snippet = user.strip()[:title_chars]
            title = {"model": "bicentennial-aux-title_generation", **(
                {"messages": [{"role": "user", "content": f"  {snippet}\n"}]} if wire == "chat" else
                {"input": f"  {snippet}\n"})}
            requests = [(f"/aux/title_generation/v1/{path}", title), (f"/main/v1/{path}", main)]
            for target, body in requests if title_first and session is script["sessions"][0] else reversed(requests):
                clock_before = d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s
                status, ctype, data = post(d, target, body)
                assert status == 200
                if body is main:
                    _, ids = answer(ctype, data)
                else:
                    assert (d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s) == clock_before
            # Carry the minted main call into a later request, as the harness does.
            if wire == "chat":
                main["messages"] += [{"role": "assistant", "content": "", "tool_calls": [
                    {"id": ids[0], "type": "function", "function": {"name": "memory", "arguments": "{}"}}]},
                                     {"role": "tool", "tool_call_id": ids[0], "content": "saved"}]
            else:
                main["input"] = [{"role": "user", "content": user},
                                 {"type": "function_call", "call_id": ids[0], "name": "memory", "arguments": "{}"},
                                 {"type": "function_call_output", "call_id": ids[0], "output": "saved"}]
            assert post(d, f"/main/v1/{path}", main)[0] == 200
    finally:
        d.close()
    return records(tmp), d.run_values


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_title_arrival_order_keeps_the_same_stable_digest(wire, tmp_path):
    first, fv = title_order_run(tmp_path / "title-first", wire, True)
    last, lv = title_order_run(tmp_path / "main-first", wire, False)
    assert stable_digest(first, fv) == stable_digest(last, lv)
    bodies = []
    for name, recs in (("title-first", first), ("main-first", last)):
        store = BlobStore(tmp_path / name / "ledger/blobs", None)
        bodies.append({(r["role"], r["subrole"]): json.loads(store.get(r["resp"])) for r in recs})
        assert all(r["sim_now"] == BASE + DAY + STEP for r in recs)
        if wire == "chat":
            assert all(obj["created"] == BASE + DAY + STEP for obj in bodies[-1].values())
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("user", [
    pytest.param(("word " * 400).strip(), id="cut-ends-in-space"),
    pytest.param(next(s for s in SCRIPT["sessions"] if s["index"] == 6)["turns"][0]["user"], id="session-six"),
    pytest.param("short opening turn", id="short"),
])
def test_hermes_title_transform_keeps_digest_and_created(wire, user, tmp_path):
    session = next(s for s in SCRIPT["sessions"] if s["index"] == 6)
    turn = dict(session["turns"][0], user=f"  \n{user}\t ")
    script = dict(SCRIPT, sessions=[dict(session, turns=[turn])])
    first, fv = title_order_run(tmp_path / "title-first", wire, True, script=script, title_chars=1000)
    last, lv = title_order_run(tmp_path / "main-first", wire, False, script=script, title_chars=1000)
    assert stable_digest(first, fv) == stable_digest(last, lv)
    bodies = []
    for name, recs in (("title-first", first), ("main-first", last)):
        store = BlobStore(tmp_path / name / "ledger/blobs", None)
        bodies.append({(r["role"], r["subrole"]): json.loads(store.get(r["resp"])) for r in recs})
        assert all(r["sim_now"] == BASE + 6 * DAY + STEP for r in recs)
        if wire == "chat":
            assert all(obj["created"] == BASE + 6 * DAY + STEP for obj in bodies[-1].values())
    assert bodies[0] == bodies[1]


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_second_session_ids_ignore_first_session_title_order(wire, tmp_path):
    first, fv = title_order_run(tmp_path / "title-first", wire, True, sessions=2)
    last, lv = title_order_run(tmp_path / "main-first", wire, False, sessions=2)
    first = [r for r in first if r["attempt_id"] == "attempt-s2"]
    last = [r for r in last if r["attempt_id"] == "attempt-s2"]
    assert stable_digest(first, fv) == stable_digest(last, lv)
    store = BlobStore(tmp_path / "title-first/ledger/blobs", None)
    for rec in first:
        obj = json.loads(store.get(rec["resp"]))
        rid = obj["id"] if wire == "chat" else obj["sse"][0]["response"]["id"]
        seed = "attempt-s2" if rec["cursor"] else canon(["attempt-s2", rec["role"]]).decode()
        assert rid == mint_id(seed, 3 if rec["subrole"] == "tool_results" else 1)


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_non_cursor_instants_use_latest_quoted_turn_and_fallback(wire, tmp_path):
    d = make(tmp_path, Fake())
    start(d, tmp_path)
    users = [t["user"] for t in SCRIPT["sessions"][0]["turns"][:2]]
    for user in users:
        assert post(d, "/main/v1/chat/completions", turn_body(user, tools=("todo",)))[0] == 200
    snapshot = d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s
    path = "chat/completions" if wire == "chat" else "responses"
    # History order differs from script order; match both individual blocks and their joined text.
    for texts, turn in ((users[::-1], 2), ([users[0]], 1), (["not a scripted user"], 2)):
        items = [{"role": "user", "content": [{"type": "text" if wire == "chat" else "input_text", "text": part}
                                              for part in f"  {text}\n".split("\n")]} for text in texts]
        body = {"model": "bicentennial-summariser", "messages" if wire == "chat" else "input": items}
        status, _, data = post(d, f"/v1/{path}", body)
        assert status == 200
        assert records(tmp_path)[-1]["sim_now"] == BASE + DAY + STEP * turn
        if wire == "chat":
            assert json.loads(data)["created"] == BASE + DAY + STEP * turn
        assert (d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s) == snapshot
    d.close()


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_repeated_text_does_not_stamp_an_unreached_turn(wire, tmp_path):
    session = SCRIPT["sessions"][0]
    turns = [dict(t, user="Thanks!" if t["n"] in (2, 5) else t["user"]) for t in session["turns"]]
    script = dict(SCRIPT, sessions=[dict(session, turns=turns)])
    d = make(tmp_path, Fake(), script=script)
    start(d, tmp_path)
    try:
        for turn in turns[:3]:
            assert post(d, "/main/v1/chat/completions", turn_body(turn["user"], tools=("todo",)))[0] == 200
        assert d.ctx.cursor == 3
        snapshot = d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s
        items = [{"role": "user", "content": "  Thanks!\n"}]
        body = {"model": "bicentennial-summariser", "messages" if wire == "chat" else "input": items}
        path = "chat/completions" if wire == "chat" else "responses"
        status, _, data = post(d, f"/v1/{path}", body)
        assert status == 200
        assert records(tmp_path)[-1]["sim_now"] == BASE + DAY + 2 * STEP
        if wire == "chat":
            assert json.loads(data)["created"] == BASE + DAY + 2 * STEP
        assert (d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s) == snapshot
        assert d.ctx.cursor == 3
    finally:
        d.close()


def test_embeddings_use_identifiable_turn_instant(tmp_path):
    d = make(tmp_path, Fake())
    start(d, tmp_path)
    snapshot = d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s
    assert post(d, "/v1/embeddings", {"model": "embed", "input": f" {TURN1['user']}\n"})[0] == 200
    assert records(tmp_path)[0]["sim_now"] == BASE + DAY + STEP
    assert (d.clock.path.read_bytes(), d.clock.path.stat().st_ino, d.clock.sim_t_s) == snapshot
    d.close()


def test_write_turn_tool_calls_then_the_scripted_turn(tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    fake.n_calls = 1
    status, ctype, data = post(d, "/main/v1/chat/completions", turn_body())
    text, ids = answer(ctype, data)
    assert status == 200 and text == "" and ids == [mint_id("attempt-s1", 2)]  # the response id is the first
    sent = fake.calls[0]
    assert (sent.role, sent.model, sent.cursor, sent.run_key) == ("write_turn", "probe-model", {"session": 1, "turn": 1},
                                                                  "attempt-s1")
    assert [t["function"]["name"] for t in sent.body["tools"]] == ["memory"]  # filtered to the declared tools
    assert sent.body["messages"] == turn_body()["messages"]  # Ring 0: no write prompt is added
    back = turn_body()
    back["messages"] += [{"role": "assistant", "content": "", "tool_calls": [
        {"id": ids[0], "type": "function", "function": {"name": "memory", "arguments": "{}"}}]},
                         {"role": "tool", "tool_call_id": ids[0], "content": "saved"}]
    status, ctype, data = post(d, "/main/v1/chat/completions", back)
    assert status == 200 and answer(ctype, data)[0] == TURN1["assistant"] and len(fake.calls) == 1
    first, second = records(tmp_path)
    assert (first["served"], first["write_calls"], first["write_turn_readback"]) == ("write_tool_calls", 1, True)
    assert (second["role"], second["subrole"], second["served"]) == ("write_turn", "tool_results", "script")
    assert second["cursor"] == first["cursor"] == {"session": 1, "turn": 1}


def test_write_turn_text_is_discarded_and_a_retry_is_scripted(tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    for _ in range(2):  # the same turn again is a retry: the script, no second write turn, no tick
        status, ctype, data = post(d, "/main/v1/chat/completions", turn_body(stream=True))
        assert status == 200 and ctype == "text/event-stream" and answer(ctype, data) == (TURN1["assistant"], [])
    first, retry = records(tmp_path)
    assert first["served"] == "script" and first["write_calls"] == 0 and len(fake.calls) == 1
    assert (retry["subrole"], retry["served"], retry["cursor"]) == ("retry", "script_retry", first["cursor"])
    assert "write_turn_readback" not in retry and retry["sim_now"] == first["sim_now"] == BASE + DAY + STEP


def test_no_write_tool_no_write_turn_and_responder_errors(tmp_path):
    fake = Fake(fail=("write_turn",))
    d = make(tmp_path, fake)
    start(d, tmp_path)
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 200  # a failed write turn serves the script
    second = LIFE["sessions"][0]["turns"][1]
    assert answer(*post(d, "/main/v1/chat/completions", turn_body(second["user"], tools=("todo",)))[1:]) == (
        second["assistant"], [])
    a, b = records(tmp_path)
    assert (a["write_turn_failed"], a["served"], d.write_failures) == ("error_runtimeerror", "script", 1)
    assert "write_turn_readback" not in b and len(fake.calls) == 1


def test_unseen_shape_is_refused_and_ledgered(tmp_path):
    d = make(tmp_path, Fake())
    start(d, tmp_path)
    status, _, data = post(d, "/main/v1/chat/completions", turn_body("an unscripted turn"))
    assert status == 400 and json.loads(data)["error"]["message"] == (
        "director: unclassified request refused (fail closed)")
    (rec,) = records(tmp_path)
    assert (rec["role"], rec["served"], rec["status"], rec["cursor"]) == ("unknown", "refused_unknown", 400, None)


def test_background_review_title_and_embeddings_reach_the_responder(tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    review = {"model": "bicentennial-aux-review", "messages": [
        {"role": "user", "content": SYN["hermes_background_review"] + " and save what matters"}]}
    title = {"model": "bicentennial-aux-title_generation", "messages": [
        {"role": "system", "content": SYN["hermes_title"] + ": name it"}, {"role": "user", "content": "hello"}]}
    assert post(d, "/aux/review/v1/chat/completions", review)[0] == 200
    assert post(d, "/aux/title_generation/v1/chat/completions", title)[0] == 200
    status, _, data = post(d, "/main/v1/embeddings", {"model": "embed-alias", "input": "hello"})
    assert status == 200 and json.loads(data)["data"][0]["embedding"] == [0.75, 0.0, -0.25]
    recs = records(tmp_path)
    assert [(r["role"], r["subrole"], r["served"]) for r in recs] == [
        ("memory_write", "background_review", "responder_fake"), ("aux", "title_generation", "responder_fake"),
        ("embeddings", "embedding", "responder_fake")]
    assert [(c.role, c.wire) for c in fake.calls] == [("memory_write", "chat"), ("aux", "chat"),
                                                      ("embeddings", "embeddings")]


def test_a_live_reply_from_the_wrong_model_stops_admission(tmp_path):
    d = make(tmp_path, Fake(model="some-other-model", served_by="live"))
    start(d, tmp_path)
    title = {"model": "bicentennial-aux-title_generation", "messages": [{"role": "user", "content": "hello"}]}
    assert post(d, "/aux/title_generation/v1/chat/completions", title)[0] == 503
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 503
    assert d.control()["stopped"] is True
    a, b = records(tmp_path)
    assert (a["served"], a["served_by"], a["role"]) == ("identity_mismatch", "live", "aux")
    assert (b["served"], b["status"]) == ("stopped", 503)


def test_responses_wire_ids_and_compact(tmp_path):
    fake = Fake()
    d = make(tmp_path, fake)
    start(d, tmp_path)
    body = {"model": "m", "input": TURN1["user"], "tools": tools_of(2, False), "stream": True}
    status, ctype, data = post(d, "/v1/responses", body)
    events = responses.parse_sse(data)
    assert status == 200 and events[0]["response"]["id"] == mint_id("attempt-s1", 1)
    assert answer(ctype, data) == (TURN1["assistant"], [])
    status, _, data = post(d, "/v1/responses/compact", {"model": "m", "input": "compact this"})
    assert status == 200 and json.loads(data)["output"][0]["content"][0]["text"] == "fake summariser text, discard me"
    a, b = records(tmp_path)
    assert (a["n_messages"], a["n_tools"], b["role"], b["subrole"]) == (1, 2, "summariser", "compression")


def test_refusals_catalog_and_control(tmp_path):
    fake = Fake(fail=("aux",))
    d = make(tmp_path, fake)
    start(d, tmp_path)
    title = {"model": "bicentennial-aux-title_generation", "messages": [{"role": "user", "content": "hello"}]}
    got = [d.handle("GET", "/main/v1/files", {}, b"")[0], d.handle("GET", "/mount/api/tags", {}, b"")[0],
           d.handle("GET", "/main/api/v1/models", {}, b"")[0], post(d, "/v1/messages", turn_body())[0],
           post(d, "/main/v1/chat/completions", b"{not json")[0],
           post(d, "/main/v1/chat/completions", {"model": "m", "temperature": 0.5})[0],
           post(d, "/main/v1/chat/completions", turn_body(), {"Content-Encoding": "gzip"})[0],
           post(d, "/aux/title_generation/v1/chat/completions", title)[0]]
    assert got == [404, 404, 200, 404, 400, 400, 415, 500]
    assert d.handle("GET", "/_control", {}, b"")[0] == 200 and len(records(tmp_path)) == len(got)  # not ledgered
    assert [(r["role"], r["subrole"], r["served"]) for r in records(tmp_path)] == [
        ("unknown", "path", "path_refused"), ("aux", "metadata", "path_refused"), ("aux", "metadata", "catalog"),
        ("unknown", "path", "path_refused"), ("unknown", "malformed_body", "refused_unknown"),
        ("unknown", "malformed_body", "refused_unknown"), ("unknown", "encoding", "encoding_refused"),
        ("aux", "title_generation", "director_error")]  # a responder error keeps its classification
    assert all(r["incoming_auth_dropped"] is (r["method"] == "POST") for r in records(tmp_path))
    assert set(d.control()) == {"inflight", "cursor", "stopped", "write_failures", "send_errors"}


def test_probe_tool_calls_are_the_readers(tmp_path):
    script = json.loads(json.dumps(SCRIPT))
    script["sessions"][0]["kind"] = script["sessions"][0]["turns"][0]["kind"] = "probe"
    script["sessions"][0]["turns"] = script["sessions"][0]["turns"][:1]
    script["sessions"][0]["turns"][0]["tool_calls"] = [{"name": "terminal", "args": {}}]
    with pytest.raises(ValueError, match="probe tool calls are the reader's"):
        make(tmp_path, Fake(), script=script)


WRAPPER = "<memory-context>\n[System note: The following is recalled memory context, NOT new user input.]"


def test_a_scripted_turn_holding_hermes_memory_wrapper_is_refused(tmp_path):
    script = json.loads(json.dumps(SCRIPT))
    script["sessions"][0]["turns"][0]["user"] += "\n\n" + WRAPPER  # it would read as Hermes's own block (#197)
    with pytest.raises(ValueError, match="memory wrapper"):
        make(tmp_path, Fake(), script=script)


def test_turn_stamp_reads_the_turn_before_hermes_memory_block(tmp_path):
    d = make(tmp_path, Fake())
    start(d, tmp_path, session=SCRIPT["sessions"][0]["index"])
    turn = d.turns[0]
    fenced = {"messages": [{"role": "user", "content": turn["user"] + "\n\n" + WRAPPER + "\n\nfact\n</memory-context>"}]}
    assert d._request_turn(fenced) is turn
    # history: a plain earlier turn, then the current turn with Hermes's block; the current turn wins
    d.ctx.cursor = 1
    later = d.turns[1]
    history = {"messages": [{"role": "user", "content": turn["user"]}, {"role": "assistant", "content": "ok"},
                            {"role": "user", "content": later["user"] + "\n\n" + WRAPPER + "\n\nfact"}]}
    assert later["session"] == turn["session"] and d._request_turn(history) is later
    assert d._request_turn({"messages": [{"role": "user", "content": turn["user"] + "\n\nother text"}]}) is None


def test_http_egress_hold_and_drain(tmp_path, no_egress):
    held = []

    def on_hold(cursor):
        held.append(cursor)
        if len(held) == 2:
            raise RuntimeError("the harness was killed while held")

    d = make(tmp_path, Fake(), on_hold=on_hold)
    start(d, tmp_path)
    server = serve(d)
    try:
        assert d.run_values["director_port"] == str(server.port)
        assert send(server.port, "CONNECT", "example.com:443")[0] == 403
        assert send(server.port, "GET", "http://example.com/v1/models")[0] == 403
        assert send(server.port, "POST", "/main/v1/chat/completions", turn_body())[0] == 200
        with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):  # held, then never answered
            send(server.port, "POST", "/main/v1/chat/completions", turn_body())
        status, _, data = send(server.port, "GET", "/_control")
        assert status == 200 and json.loads(data)["inflight"] == 0
    finally:
        shutdown(server)
        d.close()
    recs = records(tmp_path)
    assert [(r["method"], r["subrole"], r["served"], r["status"]) for r in recs[:2]] == [
        ("CONNECT", "egress", "refused_egress", 403), ("GET", "egress", "refused_egress", 403)]
    assert [r["served"] for r in recs[2:]] == ["script", "script_retry"]  # recorded before the hold
    assert held == [{"session": 1, "turn": 1}] * 2 and no_egress["outbound"] == 0


def test_a_credential_in_a_body_stops_admission_unrecorded(tmp_path, monkeypatch):
    monkeypatch.setenv("R08_TEST_CANARY", "r08-canary-value-not-a-credential")
    d = make(tmp_path, Fake())
    d.guard = Guard(["R08_TEST_CANARY"])
    start(d, tmp_path)
    with pytest.raises(CredentialLeak):
        post(d, "/main/v1/chat/completions", turn_body("r08-canary-value-not-a-credential"))
    assert d.stopped is True and (tmp_path / "ledger" / "ledger.jsonl").read_bytes() == b""


TITLE = {"model": "bicentennial-aux-title_generation", "messages": [{"role": "user", "content": "hello"}]}


def fail_next_blob(d):
    """The ledger's next blob write raises OSError once (a full or failing disk)."""
    real, state = d.ledger.blob, {"armed": True}

    def blob(obj):
        if state.pop("armed", False):
            raise OSError("test: the blob write failed")
        return real(obj)

    d.ledger.blob = blob


@pytest.mark.parametrize("where", ["upstream", "write_turn"])
def test_a_ledger_failure_inside_dispatch_stops_admission(where, tmp_path):
    # upstream: the first blob is _upstream()'s call body; write_turn: the failed write turn's call-body blob
    d = make(tmp_path, Fake(fail=("write_turn",) if where == "write_turn" else ()))
    start(d, tmp_path)
    fail_next_blob(d)
    path, body = ("/aux/title_generation/v1/chat/completions", TITLE) if where == "upstream" else (
        "/main/v1/chat/completions", turn_body())
    with pytest.raises(OSError):  # nothing recorded, nothing sent: serve closes the connection
        post(d, path, body)
    assert d.stopped is True and (tmp_path / "ledger" / "ledger.jsonl").read_bytes() == b""
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 503
    (rec,) = records(tmp_path)
    assert (rec["served"], rec["status"]) == ("stopped", 503)


def test_a_responder_error_keeps_the_request_evidence(tmp_path):
    d = make(tmp_path, Fake(fail=("aux",)))
    start(d, tmp_path)
    assert post(d, "/aux/title_generation/v1/chat/completions", TITLE)[0] == 500
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 200  # a responder error is recoverable
    rec = records(tmp_path)[0]
    blobs = BlobStore(tmp_path / "ledger" / "blobs", None)
    assert blobs.get(rec["req"]) == canon(TITLE)  # the parsed body, not {}
    assert (rec["role"], rec["subrole"], rec["served"], rec["status"]) == (
        "aux", "title_generation", "director_error", 500)  # S1's title, as route_role ledgers it
    assert rec["upstream"] == [{"role": "aux", "req": rec["req"], "error": "error_runtimeerror"}]


def test_a_director_fault_is_recorded_with_its_request_then_stops(tmp_path, monkeypatch):
    d = make(tmp_path, Fake())
    start(d, tmp_path)

    def broken(*args, **kwargs):
        raise KeyError("test: a director fault")

    monkeypatch.setattr(d, "_answer", broken)
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 500
    assert post(d, "/main/v1/chat/completions", turn_body())[0] == 503
    fault, stopped = records(tmp_path)
    assert (fault["role"], fault["cursor"], fault["subrole"]) == ("replay_main", {"session": 1, "turn": 1},
                                                                  "director_error_keyerror")
    assert BlobStore(tmp_path / "ledger" / "blobs", None).get(fault["req"]) == canon(turn_body())
    assert stopped["served"] == "stopped" and d.stopped is True
