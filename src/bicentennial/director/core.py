"""The director (DESIGN §6.2): a fail-closed handler for the chat-completions and Responses wires. It serves the
scripted history itself and asks a Responder for every other answer, so it never opens a socket. Each request is
classified by S1 and gets one K13 ledger record, appended before the response is returned, under one lock."""

import json
import os
import re
import threading
import time
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.director import roles
from bicentennial.director.responder import Call, Reply
from bicentennial.director.route_role import RouteState, route
from bicentennial.director.wire import chat, embeddings, responses, writeturn
from bicentennial.keyed import mint_id
from bicentennial.ledger import CredentialLeak, Ledger, apply_masks
from bicentennial.runtime.faultlite import FaultLite

# Hermes's auxiliary tasks (spikes/s6a/replay.py AUX_TASKS), each with a /aux/{task}/ base URL and a model alias
AUX_TASKS = ("compression", "title_generation", "vision", "approval", "mcp", "memory_query_rewrite", "curator",
             "skills_hub", "tts_audio_tags", "voice_chat", "triage_specifier", "kanban_decomposer",
             "profile_describer", "goal_judge", "monitor", "moa_reference", "moa_aggregator", "review")
SERVED_WIRES = {"openai_chat": "chat", "openai_responses": "responses",
                "openai_responses_compact": "responses_compact"}
JSON, SSE = "application/json", "text/event-stream"
_NAME = re.compile(r"[a-z0-9_]+")


def _alias(task: str) -> tuple[str, frozenset]:
    special = {"compression": roles.alias("compaction"), "title_generation": roles.alias("title"),
               "review": roles.alias("aux", "memory_write")}  # a background review on /aux/review/ is memory_write
    return special.get(task, roles.alias("aux"))


class Director:
    def __init__(self, script, route_table, system, life, branch, run, write_tools, responder, clock, guard,
                 run_values, write_prompt=None, on_hold=None, *, schedule=None):
        validate("script", script)
        for turn in (t for s in script["sessions"] for t in s["turns"]):
            if turn["tool_calls"]:
                raise ValueError("scripted tool calls need the tool-call compiler")
            if turn["kind"] == "replay" and turn["assistant"] is None:
                raise ValueError("a replay turn needs assistant text")
        self.turns = tuple({"session": s["index"], "turn": t["n"], "kind": t["kind"], "user": t["user"],
                            "assistant": t["assistant"]} for s in script["sessions"] for t in s["turns"])
        self.ctx = roles.Context(expected=[{"kind": t["kind"], "hash": roles.h16(t["user"].strip())}
                                           for t in self.turns])
        for task in AUX_TASKS:
            self.ctx.path_aliases[f"/aux/{task}/"] = self.ctx.aliases[f"bicentennial-aux-{task}"] = _alias(task)
        self.ctx.aliases["bicentennial-summariser"] = roles.alias("compaction")
        apply_masks({}, run_values)  # refuses incomplete run values before any request
        self.run_values = dict(run_values)
        self.table, self.schedule = route_table, schedule or FaultLite.load([], script)
        self.system, self.life, self.branch, self.run = system, life, branch, run
        self.write_tools, self.responder, self.clock, self.guard = tuple(write_tools), responder, clock, guard
        self.write_prompt, self.on_hold = write_prompt, on_hold
        self.pending, self.id_roles = {}, {}  # director-issued call id -> its scripted turn; -> (role, subrole)
        self.ledger = self.route = self.attempt_id = None
        self.n_ids = self.inflight = self.write_failures = self.send_errors = 0
        self.stopped, self._lock, self._count = False, threading.Lock(), threading.Lock()

    def start_session(self, index, sim_t_s, lock_hash, attempt_id, ledger_root) -> None:
        """Called while the harness is idle: a new ledger writer, the session's route, its clock instant."""
        with self._lock:
            if self.ledger is not None:
                self.ledger.close()
                self.ledger = None
            self.ledger = Ledger(ledger_root, self.guard, lock_hash=lock_hash, attempt_id=attempt_id)
            self.route = self.table.resolve(self.system, index, self.schedule)
            self.attempt_id, self.n_ids = attempt_id, 0
            self.clock.set_session(sim_t_s)

    def bind_port(self, port: int) -> None:  # serve() names the bound port, so the masks remove the real one
        self.run_values["director_port"] = str(port)

    def note_send_error(self) -> None:
        with self._count:
            self.send_errors += 1

    def control(self) -> dict:
        return {"inflight": self.inflight, "cursor": self.ctx.cursor, "stopped": self.stopped,
                "write_failures": self.write_failures, "send_errors": self.send_errors}

    def close(self) -> None:
        with self._lock:
            if self.ledger is not None:
                self.ledger.close()

    def handle(self, method, path, headers, raw_body, *, peek=None) -> tuple[int, dict, bytes]:
        """-> (status, headers, body). Raises only when nothing may be sent: a ledger or guard failure (which
        also stops admission) or an on_hold hook that raised. peek() reports a client that already hung up."""
        if method == "GET" and path.split("?")[0].rstrip("/") == "/_control":
            return 200, {"Content-Type": JSON}, json.dumps(self.control()).encode()
        with self._count:
            self.inflight += 1
        try:
            t, t0 = int(time.time() * 1000), time.monotonic()
            names = {k.lower() for k in headers.keys()}  # header values, Authorization's above all, are never read
            with self._lock:
                if self.ledger is None:
                    return 503, {"Content-Type": JSON}, _refusal(503, "no session", {})[2]
                rec = {"role": "unknown", "subrole": "", "cursor": None, "served_by": "scripted", "upstream": [],
                       "model_in": "none", "n_messages": 0, "n_tools": 0,
                       "req_chars": len(raw_body.decode("utf-8", "replace"))}
                try:  # a guard or ledger failure stops admission: nothing unrecorded is ever sent
                    try:
                        status, ctype, out, resp, req, hold = self._dispatch(method, path, names, raw_body, rec)
                    except CredentialLeak:
                        raise
                    except Exception as e:  # noqa: BLE001 - every other failure is answered and recorded
                        rec = {k: rec[k] for k in ("served_by", "model_in", "n_messages", "n_tools", "req_chars")} | {
                            "role": "unknown", "subrole": f"director_error_{type(e).__name__.lower()}", "cursor": None,
                            "upstream": [], "served": "director_error"}
                        status, ctype, out, resp, req, hold = _refusal(500, "internal error", {})
                    rec.update(type="request", run=self.run, method=method, path=path, life=self.life,
                               branch=self.branch, system=self.system, status=status, sim_now=self.clock.sim_t_s,
                               incoming_auth_dropped="authorization" in names, t=t,
                               load=[round(x * 1000) for x in os.getloadavg()],
                               req=self.ledger.blob(req), resp=self.ledger.blob(resp),
                               req_masked_sha256=self._masked(req), resp_masked_sha256=self._masked(resp))
                    if peek is not None and peek():
                        rec["client_disconnected"] = True
                    rec["t_ms"] = round((time.monotonic() - t0) * 1000)
                    self.ledger.append(rec)
                except BaseException:
                    self.stopped = True
                    raise
            if hold and self.on_hold is not None:
                self.on_hold(rec["cursor"])  # R12 holds or kills here; a raise means the response is never sent
            return status, {"Content-Type": ctype}, out
        finally:
            with self._count:
                self.inflight -= 1

    def _masked(self, obj) -> str:
        return sha256(canon(apply_masks(obj, self.run_values))).hexdigest()

    def _dispatch(self, method, path, names, raw, rec):
        """-> (status, content type, bytes, response object, request object, hold); fills rec in place."""
        p = path.split("?")[0].rstrip("/")
        if self.stopped:
            rec["subrole"] = "stopped"
            return _refuse(rec, 503, "stopped", "admission stopped")
        if method == "CONNECT" or not path.startswith("/"):  # a proxied or absolute-URI egress attempt
            rec["subrole"] = "egress"
            return _refuse(rec, 403, "refused_egress", "egress refused")
        if method == "GET":
            aux = roles.classify({"method": "GET", "path": path, "body": None}, self.ctx)[0] == "aux"
            rec.update(role="aux" if aux else "unknown", subrole="metadata" if aux else "path")
            models = [self.route["alias"], "bicentennial-summariser", *(f"bicentennial-aux-{t}" for t in AUX_TASKS)]
            m = re.search(r"/models(?:/([^/]+))?$", p)
            if aux and m and m[1] in (None, *models):
                obj = ({"object": "list", "data": [{"id": x, "object": "model"} for x in models]} if m[1] is None
                       else {"id": m[1], "object": "model"})
                rec["served"] = "catalog"
                return 200, JSON, json.dumps(obj).encode(), obj, {}, False
            return _refuse(rec, 404, "path_refused", "unknown path (fail closed)")
        wire = "embeddings" if method == "POST" and p.endswith("/embeddings") else (
            SERVED_WIRES.get(roles.wire_of(method, p)) if method == "POST" else None)
        if wire is None:
            rec["subrole"] = "path"
            return _refuse(rec, 404, "path_refused", "unknown path (fail closed)")
        if "content-encoding" in names:
            rec["subrole"] = "encoding"
            return _refuse(rec, 415, "encoding_refused", "encoded request body refused")
        try:
            body = json.loads(raw)
            if not isinstance(body, dict):
                raise ValueError("body")
            canon(body)  # a float has no canonical form, so it could never be ledgered
        except (ValueError, TypeError):
            rec["subrole"] = "malformed_body"
            return _refuse(rec, 400, "refused_unknown", "malformed request body", {"body_sha256": sha256(raw).hexdigest()})
        items = body.get("messages") if wire == "chat" else body.get("input")
        rec.update(model_in=body["model"] if isinstance(body.get("model"), str) and body["model"] else "none",
                   n_tools=len(body["tools"]) if isinstance(body.get("tools"), list) else 0,
                   n_messages=0 if wire == "embeddings" or not isinstance(items, (list, str))
                   else len(items) if wire == "chat" else len(responses.typed(items)))
        if wire == "embeddings":
            return self._embeddings(body, rec)
        return self._classified(wire, path, body, rec)

    def _embeddings(self, body, rec):
        try:  # decided by the endpoint alone, before S1, which has no embeddings wire
            embeddings.parse_request(body)
        except ValueError:
            rec["subrole"] = "malformed_body"
            return _refuse(rec, 400, "refused_unknown", "malformed embeddings request", body)
        rec.update(role="embeddings", subrole="embedding")
        reply = self._ask(Call("embeddings", "embedding", "embeddings", deepcopy(body), self._model("embeddings"),
                               None, self.attempt_id), rec)
        if reply is None:
            return _refuse(rec, 503, "identity_mismatch", "served model identity mismatch", body)
        if reply.status != 200:
            return _refuse(rec, reply.status, rec["served"], "responder refused", body)
        obj = embeddings.build_response(reply.embedding, reply.scale, body["model"],
                                        prompt_tokens=(reply.usage or {}).get("prompt_tokens", 0))
        stored = {"object": "list", "model": body["model"], "vectors": reply.embedding, "scale": reply.scale}
        return 200, JSON, json.dumps(obj).encode(), stored, body, False

    def _classified(self, wire, path, body, rec):
        s1 = roles.classify({"method": "POST", "path": path, "body": body}, self.ctx)
        state = RouteState(self.pending, self.turns, self.ctx.cursor, self.ctx.current, self.ctx.path_aliases,
                           self.ctx.aliases, self.id_roles)
        role, sub, turn = route(s1, path, body, state)
        cursor = turn and {"session": turn["session"], "turn": turn["turn"]}
        rec.update(role=role, subrole=sub, cursor=cursor)
        if role == "unknown":
            return _refuse(rec, 400, "refused_unknown", "unclassified request refused (fail closed)", body)
        roles.advance(self.ctx, s1)
        if sub == "cursor":  # a new integer turn, replay or probe; a retry, continuation or tool result never ticks
            self.clock.tick()
        if role in ("replay_main", "write_turn"):  # the scripted turn: its cursor, a retry, or its tool results
            text, calls, rec["served"] = turn["assistant"], (), "script_retry" if sub == "retry" else "script"
            if role == "replay_main" and sub == "cursor" and _tool_names(wire, body) & set(self.write_tools):
                calls = self._write_turn(wire, body, cursor, rec)
                if calls is None:
                    return _refuse(rec, 503, "identity_mismatch", "served model identity mismatch", body)
                if calls:
                    text, rec["served"] = "", "write_tool_calls"
            return self._answer(wire, body, text, calls, ("write_turn", "tool_results", "write_turn", turn),
                                hold=not calls)
        reply = self._ask(Call(role, sub, wire, deepcopy(body), self._model(role), cursor, self.attempt_id), rec)
        if reply is None:
            return _refuse(rec, 503, "identity_mismatch", "served model identity mismatch", body)
        if reply.status != 200:
            return _refuse(rec, reply.status, rec["served"], "responder refused", body)
        issued = (role, "tool_results" if sub in ("cursor", "retry") else sub, s1[0], turn)
        return self._answer(wire, body, reply.text, reply.tool_calls, issued, usage=reply.usage)

    def _write_turn(self, wire, body, cursor, rec):
        """-> the write-tool calls to return (empty: serve the scripted turn), or None on an identity mismatch."""
        model, tools = self.route["probe_model"], frozenset(self.write_tools)
        expected = writeturn.expected_write_body(deepcopy(body), wire, model, self.write_prompt, write_tools=tools)
        call = Call("write_turn", "write_turn", wire, writeturn.expected_write_body(
            body, wire, model, self.write_prompt, write_tools=tools), model, cursor, self.attempt_id)
        try:
            reply = self._respond(call)
        except CredentialLeak:
            raise
        except Exception as e:  # noqa: BLE001 - a responder error serves the scripted turn
            reply, failed = None, f"error_{type(e).__name__.lower()}"
            rec["upstream"].append({"role": "write_turn", "req": self.ledger.blob(call.body), "error": failed})
        rec["write_turn_readback"] = writeturn.readback(call.body, expected)
        if reply is not None:
            self._upstream(call, reply, rec)
            if self.stopped:
                return None
            failed = None if reply.status == 200 else f"status_{reply.status}"
        if failed:
            rec["write_turn_failed"] = failed
            with self._count:
                self.write_failures += 1
            return ()
        calls = tuple(c for c in reply.tool_calls if c["name"] in _tool_names(wire, call.body))
        rec["write_calls"] = len(calls)
        return calls  # any text the model wrote is discarded

    def _model(self, role: str) -> str:
        return self.route["summariser"] if role == "summariser" else self.route["probe_model"]

    def _respond(self, call: Call) -> Reply:
        reply = self.responder.respond(call)
        if (not isinstance(reply, Reply) or type(reply.status) is not int or not 100 <= reply.status < 600
                or not isinstance(reply.served, str)
                or not _NAME.fullmatch(reply.served) or reply.served_by not in ("scripted", "live") or not reply.model
                or not isinstance(reply.model, str) or not isinstance(reply.text, str) or not all(
                    isinstance(c, dict) and isinstance(c.get("name"), str) and isinstance(c.get("arguments"), str)
                    for c in reply.tool_calls)):
            raise ValueError("invalid responder reply")
        return reply

    def _upstream(self, call, reply, rec) -> None:
        """Records the call and its reply, then checks the served identity (DESIGN §6.2 job 6)."""
        rec["upstream"].append({"role": call.role, "req": self.ledger.blob(call.body), "model": reply.model,
                                "resp": self.ledger.blob(asdict(reply)), "status": reply.status,
                                "served_by": reply.served_by, "diagnostics": list(reply.upstream)})
        if call.role != "write_turn":
            rec.update(served=f"responder_{reply.served}", served_by=reply.served_by)
        if reply.model != call.model:
            self.stopped = True  # admission stops: this request gets identity_mismatch, every later one stopped

    def _ask(self, call: Call, rec) -> Reply | None:
        reply = self._respond(call)
        self._upstream(call, reply, rec)
        return None if self.stopped else reply

    def _mint(self) -> str:
        self.n_ids += 1
        return mint_id(self.attempt_id, self.n_ids)

    def _answer(self, wire, body, text, calls, issued, usage=None, hold=False):
        role, sub, s1_role, turn = issued
        rid = self._mint()
        ids = [self._mint() for _ in calls]
        for cid in ids:
            self.id_roles[cid] = (role, sub)
            self.ctx.issued.setdefault(cid, s1_role)
            if turn is not None:
                self.pending[cid] = turn
        model = body["model"] if isinstance(body.get("model"), str) and body["model"] else self.route["alias"]
        if wire == "chat":
            msg = {"role": "assistant", "content": text or ""}
            if calls:
                msg["tool_calls"] = [{"id": i, "type": "function", "function": {
                    "name": c["name"], "arguments": c["arguments"]}} for i, c in zip(ids, calls, strict=True)]
            resp = chat.build_response(dict(body, model=model), msg, response_id=rid, created=self.clock.sim_t_s)
            resp["usage"] = usage or resp["usage"]
            if body.get("stream") is True:
                return 200, SSE, chat.sse_bytes(resp), {"sse": chat.sse_chunks(resp)}, body, hold
            return 200, JSON, json.dumps(resp).encode(), resp, body, hold
        items = [{"type": "function_call", "call_id": i, "name": c["name"], "arguments": c["arguments"],
                  "status": "completed"} for i, c in zip(ids, calls, strict=True)]
        if text or not items:
            items.insert(0, {"type": "message", "role": "assistant", "status": "completed",
                             "content": [{"type": "output_text", "text": text or ""}]})
        if usage is None:  # S6b's estimate: canonical JSON characters / 4, rounded up
            n_in, n_out = ((len(x) + 3) // 4 for x in (canon(body.get("instructions") or "") + canon(
                body.get("input")) + canon(body.get("tools") or []), canon(items)))
            usage = {"input_tokens": n_in, "output_tokens": n_out, "total_tokens": n_in + n_out, "estimated": True}
        if wire == "responses_compact":
            obj = {"id": rid, "object": "response.compaction", "model": model, "output": items, "usage": usage}
            return 200, JSON, json.dumps(obj).encode(), obj, body, hold
        out = responses.sse_bytes(items, usage, model, response_id=rid)
        return 200, SSE, out, {"sse": responses.parse_sse(out)}, body, hold


def _tool_names(wire, body) -> set:
    tools = [t for t in body.get("tools") or [] if isinstance(t, dict)]
    return {(t["function"].get("name") if isinstance(t.get("function"), dict) else None) if wire == "chat"
            else t.get("name") for t in tools}


def _refusal(status, message, req):
    obj = {"error": {"message": f"director: {message}"}}
    return status, JSON, json.dumps(obj).encode(), obj, req, False


def _refuse(rec, status, served, message, req=None):
    rec["served"] = served
    return _refusal(status, message, {} if req is None else req)
