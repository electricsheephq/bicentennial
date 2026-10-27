"""S9 boundary proofs; live commands are operator-only, never run by Part A."""

import argparse
import json
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, replace
from itertools import permutations
from pathlib import Path

from bicentennial import keyed
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.contracts.surfaces import tree_hash, tree_listing
from bicentennial.director.responder import Reply
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.upstream import (
    BURST,
    RATE_PER_MIN,
    Holds,
    LiveResponder,
    Pacer,
    Upstream,
)
from bicentennial.director.upstream.login import (
    CredentialResponder,
    NeedleGuard,
    Stop,
    auth_for,
    exit_on_refusal,
    open_login,
    scan,
)
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
    verify_pin,
)
from bicentennial.ledger import BlobStore, CredentialLeak, Guard, verify
from bicentennial.runner.guard import read_marker, reexec_niced
from bicentennial.runner.spend import Price, Spend
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.spansearch import span_search
from bicentennial.systems.controls import WipeOnWake, no_memory_cell
from bicentennial.systems.hermes_plugin import PROVIDERS, PluginCell
from bicentennial.systems.registry import REGISTRY, load
from bicentennial.systems.settle import settle

ARMS = ("hermes-native", "mem0-oss", "wiped", "no-memory")
BASE, STEP, DAY = 1_600_000_000, 60, 86400
PAUSE_S, MAX_SENDS = 120, 400
BUDGET_S = {"twin": 7200, "live": 10800, "resume24": 5400}
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
SUBJECTS = ("storage locker code", "parcel reference", "desk booking number")
ROOT = Path(__file__).resolve().parents[2]


def zero_spend(path):
    return Spend(path, 0, Price(0, 0))


def micro_script(probes_only=False, sessions=None):
    life = json.loads((ROOT / "spikes/s6a/micro_life.json").read_bytes())
    kind = "probe" if probes_only else "replay"
    source = life["probes" if probes_only else "sessions"]
    if sessions is not None:
        source = [s for i, s in enumerate(source, 1) if i in sessions]
    projected = []
    for index, session in enumerate(source, 1):
        turns = [{"n": n, "kind": kind, "user": turn["user"],
                  "assistant": turn.get("assistant"), "tool_calls": []}
                 for n, turn in enumerate(session["turns"], 1)]
        projected.append({"index": index, "kind": kind, "turns": turns})
    result = {"canary": CANARY, "life_id": "s6a-micro", "genre": life["genre"],
              "harness": "hermes", "sessions": projected}
    validate("script", result)
    return result


def canary_scripts(run):
    nonces = [keyed.mint_id(f"{run}-canary", i) for i in range(3)]
    scripts = []
    for kind in ("replay", "probe"):
        turns = []
        for n, (subject, nonce) in enumerate(zip(SUBJECTS, nonces, strict=True), 1):
            user = (f"For the record, the {subject} is {nonce}." if kind == "replay"
                    else f"What is the {subject} I gave you?")
            turns.append({"n": n, "kind": kind, "user": user,
                          "assistant": "Noted." if kind == "replay" else None, "tool_calls": []})
        script = {"canary": CANARY, "life_id": "s9-canary", "genre": "canary",
                  "harness": "hermes", "sessions": [{"index": 1, "kind": kind, "turns": turns}]}
        validate("script", script)
        scripts.append(script)
    return *scripts, nonces


def canary_result(sent_bodies, replies, nonces, *, live_probes=()):
    """live_probes contains successful, live control item indices (1 through 3)."""
    def encoded(values):
        return [v.encode("utf-8") if isinstance(v, str) else v for v in values]

    sent_bodies, replies = encoded(sent_bodies), encoded(replies)
    needles = [n.encode("ascii") for n in nonces]
    sent = sum(any(n in body for body in sent_bodies) for n in needles)
    carried = sum(any(n in reply for reply in replies) for n in needles)
    if sent < len(nonces):
        verdict = "vacuous"
    elif carried:
        verdict = "fail"
    elif not set(range(1, len(nonces) + 1)) <= set(live_probes):
        verdict = "incomplete"
    else:
        verdict = "pass"
    return {"items": len(nonces), "sent": sent, "carried": carried, "verdict": verdict}


def canary_surface_replies(home, nonces):
    hits = span_search(home, [n.encode("ascii") for n in nonces])
    return [needle for needle, paths in hits.items() if paths]


def should_pause(k, sessions, summariser_total):
    """Called until the first qualifying boundary; no compaction means BLOCKED."""
    return summariser_total >= 1 and k < sessions


def _text(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("bridge_content")
    if any(not isinstance(p, dict) or p.get("type") != "text"
           or not isinstance(p.get("text"), str) for p in content):
        raise ValueError("bridge_content_part")
    return "".join(p["text"] for p in content)


def to_responses(body):
    """P07's declared text-only chat adaptation; unknown keys fail closed."""
    allowed = {"model", "messages", "tools", "tool_choice", "stream", "stream_options",
               "max_tokens", "max_completion_tokens", "reasoning_effort", "parallel_tool_calls"}
    unknown = sorted(body.keys() - allowed)
    if unknown:
        raise ValueError(f"bridge_unmapped_key:{unknown[0]}")
    instructions, items = [], []
    for message in body["messages"]:
        role, text = message["role"], _text(message.get("content"))
        if role in ("system", "developer"):
            instructions.append(text)
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": message["tool_call_id"], "output": text})
        elif role in ("user", "assistant"):
            if text or not message.get("tool_calls"):
                part = "output_text" if role == "assistant" else "input_text"
                items.append({"type": "message", "role": role, "content": [{"type": part, "text": text}]})
            for call in message.get("tool_calls", []):
                if role != "assistant" or call.get("type") != "function":
                    raise ValueError("bridge_tool_call")
                function = call["function"]
                items.append({"type": "function_call", "call_id": call["id"],
                              "name": function["name"], "arguments": function["arguments"]})
        else:
            raise ValueError("bridge_role")
    result = {"instructions": "\n\n".join(instructions), "input": items,
              "store": False, "reasoning": {"effort": "medium"}}
    if "model" in body:
        result["model"] = body["model"]
    tools = []
    for tool in body.get("tools", []):
        if tool.get("type") != "function":
            raise ValueError("bridge_tool")
        function = tool["function"]
        tools.append({"type": "function", "name": function["name"],
                      "description": function.get("description", ""),
                      "parameters": function.get("parameters", {})})
    if tools:
        result["tools"] = tools
    if "tool_choice" in body:
        selected = body["tool_choice"]
        if isinstance(selected, dict):
            if selected.get("type") != "function":
                raise ValueError("bridge_tool_choice")
            selected = {"type": "function", "name": selected["function"]["name"]}
        elif not isinstance(selected, str):
            raise ValueError("bridge_tool_choice")
        result["tool_choice"] = selected
    if "parallel_tool_calls" in body:
        result["parallel_tool_calls"] = body["parallel_tool_calls"]
    canon(result)
    return result


def chat_usage(usage):
    if not isinstance(usage, dict):
        return None
    if not all(type(usage.get(k)) is int for k in ("input_tokens", "output_tokens")):
        return None
    return {"prompt_tokens": usage["input_tokens"], "completion_tokens": usage["output_tokens"],
            "total_tokens": usage["input_tokens"] + usage["output_tokens"]}


class ResponsesBridge:
    def __init__(self, inner):
        self.inner = inner

    def respond(self, call):
        if call.wire != "chat":
            return self.inner.respond(call)
        reply = self.inner.respond(replace(call, wire="responses", body=to_responses(call.body)))
        return replace(reply, usage=chat_usage(reply.usage))

    def state(self):
        return self.inner.state()

    def served_identities(self):
        return self.inner.served_identities()


class SplitResponder:
    def __init__(self, live, scripted):
        self.live, self.scripted = live, scripted

    def respond(self, call):
        stubbed = call.role == "embeddings" or (call.role, call.subrole) == ("aux", "extraction")
        return (self.scripted if stubbed else self.live).respond(call)

    def state(self):
        return self.live.state()

    def served_identities(self):
        return self.live.served_identities()


class ProbeResponder(ScriptedResponder):
    def respond(self, call):
        if call.role == "probe_main":
            return Reply(200, "probe", "scripted", call.model, text=f"probe answer {call.cursor['turn']}")
        return super().respond(call)


@dataclass
class Arm:
    adapter: object
    entry: dict
    after: int = 0
    surface_hash: str | None = None
    cell: object = None
    label: str | None = None
    execution: str | None = None


class ActiveClock:
    """One part-wide clock; gate calls and pause waits are excluded even on error."""
    def __init__(self, clock=time.monotonic):
        self.clock, self.start, self.excluded = clock, clock(), 0
        self.markers = []

    def __call__(self):
        return self.clock() - self.start - self.excluded

    def omit(self, function, *args):
        start = self.clock()
        try:
            return function(*args)
        finally:
            self.excluded += self.clock() - start


def proof_roots(arm):
    paths = arm.adapter.paths
    declared = {"HERMES_HOME": paths["hermes_home"], "SANDBOX_HOME": paths["home"]}
    roots = [(f"{s['root']}/{s['relative']}", declared[s["root"]] / s["relative"], s["volatile_paths"])
             for s in arm.entry["surfaces"]]
    return roots + [(name, paths[name], []) for name in ("home", "workspace", "tmp")]


def _snapshot(arm):
    return {name: tree_listing(directory, volatile) for name, directory, volatile in proof_roots(arm)}


def _digests(listings):
    return {name: tree_hash(rows) for name, rows in listings.items()}


def pause_proof(arm, wait_s, sleep=time.sleep):
    worker = arm.adapter._worker
    if worker is not None and worker.proc.poll() is None:
        raise BoundaryBlocked("harness_alive")
    before = _snapshot(arm)
    pause = _digests(before)
    if arm.cell is None:
        declared_matches = pause["HERMES_HOME/."] == arm.surface_hash
    else:
        hashes = [{"relative": s["relative"], "root": s["root"],
                   "tree_hash": pause[f"{s['root']}/{s['relative']}"]} for s in arm.entry["surfaces"]]
        declared = hashes[0]["tree_hash"] if len(hashes) == 1 else sha256_canon(hashes)
        declared_matches = declared == arm.cell.surface_hash()
    t0 = time.monotonic()
    sleep(wait_s)
    pause_s = int(time.monotonic() - t0)
    after = _snapshot(arm)
    changed = []
    for name in before:
        left = {r["path"]: r for r in before[name]}
        right = {r["path"]: r for r in after[name]}
        changed.extend(f"{name}:{p}" for p in left.keys() | right.keys() if left.get(p) != right.get(p))
    resume = _digests(after)
    return {"after": arm.after, "pause_s": pause_s, "pause": pause, "resume": resume,
            "equal": pause == resume, "changed": sorted(changed), "declared_matches": declared_matches}


class BoundaryBlocked(RuntimeError):
    exit_code = 2


def boundary(arm, wait_s, sleep=time.sleep, *, proof=True):
    worker = arm.adapter._worker
    if worker is not None and worker.proc.poll() is None:
        raise BoundaryBlocked("harness_alive")
    observed = arm.cell.settle() if arm.cell else settle(arm.entry)
    receipt = {k: getattr(observed, k) for k in ("kind", "settled", "polls", "reason")}
    if not observed.settled:
        return {"after": arm.after, "settle": receipt, "pause": "unsettled"}
    if arm.cell:
        arm.cell.checkpoint()
    if not proof:
        return {"after": arm.after, "settle": receipt}
    return dict(pause_proof(arm, wait_s, sleep), settle=receipt)


def admission_stop(state, holds, active_s, part):
    if state.get("identity_drift") is not None:
        return "identity_drift"
    if state.get("stopped"):
        return f"responder_stopped:{state.get('stop_reason')}"
    if state.get("spend_stopped"):
        return "spend_stop"
    if state.get("login_stop"):
        return "login_stop"
    if "quota" in holds.get("reasons", []):
        return "hold:quota"
    if active_s > BUDGET_S[part]:
        return "budget"
    return None


def run_life(arm, part, run, routes, *, script, wait_s, sleep=time.sleep,
             responder=None, holds=None, active_seconds=lambda: 0):
    """Drive one already-constructed arm; the caller owns closing and publication.

    active_seconds is the part-wide clock excluding pause and gate waits. This
    loop neither constructs a live responder nor opens a login or worker itself.
    """
    adapter = arm.adapter
    label = arm.label or arm.entry["name"]
    lock = sha256_canon({"spike": "S9", "run": run, "script": sha256_canon(script), "routes": routes})
    record = {"arm": label, "part": part, "sessions_run": [], "stop": None,
              "fresh": _digests(_snapshot(arm)), "boundaries": [], "results": [], "flagged_sessions": []}
    failed, resume_sid, summaries = False, None, []
    held = {}
    arm.resume_record, arm.finals = None, []
    for position, session in enumerate(script["sessions"]):
        record["stop"] = admission_stop(responder.state() if responder else {}, held, active_seconds(), part)
        if record["stop"]:
            return record, 2
        index = session["index"]
        attempt = f"{arm.execution or label}-s{index}"
        options = {"resume_session_id": resume_sid} if resume_sid else {}
        try:
            result = adapter.run_session(index, sim_t_s=BASE + index * DAY, lock_hash=lock,
                                         attempt_id=attempt, **options)
        except HarnessFailed:
            held = holds.at_boundary(attempt) if holds else {}
            reason = admission_stop(responder.state() if responder else {}, held, active_seconds(), part)
            record["stop"] = reason or ("resume_failed" if resume_sid else "harness_failed")
            if arm.resume_record:
                arm.resume_record["resumed_ok"] = False
            return record, 2 if reason else 1
        arm.after, arm.surface_hash = index, result.surface_hash
        arm.finals.extend(getattr(result, "finals", ()))
        record["sessions_run"].append(index)
        fields = ("session", "kind", "turns_ok", "finals_matched", "summariser_records", "reset", "end_threads")
        record["results"].append({key: getattr(result, key) for key in fields})
        if record["boundaries"] and record["boundaries"][-1].get("first_after_pause") == index:
            first = next(({"seq": row["seq"], "try": diag.get("try"), "excluded_latency": True}
                          for row in adapter.records() if row.get("attempt_id") == attempt
                          for up in row.get("upstream", []) for diag in up.get("diagnostics", [])
                          if diag.get("kind") == "try"), None)
            record["boundaries"][-1]["first_after_pause"] = first
        if resume_sid:
            retained = retained_summary(adapter, attempt, summaries)
            arm.resume_record.update(resumed_ok=retained, resumed_total=result.turns_ok,
                                     post_resume=observations(adapter, attempt)["counts"])
            resume_sid = None
            if not retained:
                record["stop"] = "compaction_not_retained"
                return record, 1
        has_next = position + 1 < len(script["sessions"])
        delay = wait_s
        if part == "resume24":
            qualifies = arm.resume_record is None and should_pause(index, len(script["sessions"]),
                sum(r["summariser_records"] for r in record["results"]))
            delay = wait_s if qualifies else 0
            if qualifies:
                summaries = observations(adapter)["summaries"][-1:]
                if not summaries:
                    record["stop"] = "compaction_unobserved"
                    return record, 2
                resume_sid = result.acp_session_id
                arm.resume_record = {"pause_after": index, "holds_compaction": True,
                    "summariser_before": sum(r["summariser_records"] for r in record["results"]),
                    "wait_s": wait_s, "resumed_ok": False, "resumed_total": 0,
                    "account_switched": False, "spare_account": "not run (deferred)"}
        try:
            proof = boundary(arm, delay if has_next else 0, sleep, proof=has_next)
        except BoundaryBlocked as exc:
            record["stop"] = str(exc)
            return record, exc.exit_code
        failed |= proof.get("pause") == "unsettled"
        if has_next:
            record["boundaries"].append(proof)
        if resume_sid:
            arm.resume_record.update({k: proof.get(k) for k in ("equal", "changed")})
            if "equal" not in proof:
                record["stop"] = "compaction_unsettled"
                return record, 2
        if proof.get("equal") is False or proof.get("declared_matches") is False:
            record["stop"] = "proof_failed"
            return record, 1
        state = responder.state() if responder else {}
        held = holds.at_boundary(attempt) if holds else {"reasons": [], "held_ms": 0}
        proof["holds"] = held
        proof["first_after_pause"] = index + 1 if has_next and delay > 0 and "equal" in proof else None
        rows = [row for row in adapter.records() if row.get("attempt_id") == attempt]
        changed_identity = any(diag.get("identity_changed") is True for row in rows
                               for upstream in row.get("upstream", []) for diag in upstream.get("diagnostics", []))
        if changed_identity:
            record["flagged_sessions"].append(index)
        record["stop"] = admission_stop(state, held, active_seconds(), part)
        if record["stop"]:
            return record, 2
    if part == "resume24" and arm.resume_record is None:
        record["stop"] = "no_compaction"
        return record, 2
    return record, int(failed)


def observations(adapter, attempt=None):
    """Read evidence in memory; raw bodies and summaries never enter public records."""
    store = BlobStore(adapter.paths["root"] / "ledger/blobs", Guard([]))
    evidence = {"sent": [], "replies": [], "live_probes": [], "summaries": [],
                "counts": dict(tries=0, forwarded=0, refused=0, credential_stop=0),
                "dropped_items": 0, "encrypted_bodies": 0, "sends": 0}
    for row in adapter.records():
        if attempt is not None and row.get("attempt_id") != attempt:
            continue
        for up in row.get("upstream", []):
            diags = [d for d in up.get("diagnostics", []) if d.get("kind") == "try"]
            counts = evidence["counts"]
            counts["tries"] += len(diags)
            evidence["sends"] += sum(d.get("sent") is True for d in diags)
            counts["forwarded"] += int(up.get("status") == 200 and up.get("served_by") == "live")
            counts["refused"] += sum(d.get("status", 0) != 200 for d in diags)
            counts["credential_stop"] += sum(d.get("status") in (401, 403) or
                                             d.get("category") == "auth_sse" for d in diags)
            evidence["dropped_items"] += sum(d.get("n_dropped_items", 0) for d in diags)
            body = store.get(up["req"])
            if any(d.get("sent") is True for d in diags):
                evidence["sent"].append(body)
                evidence["encrypted_bodies"] += int(b'"encrypted_content"' in body or b'"type":"reasoning"' in body)
            if "resp" not in up:
                continue
            reply = json.loads(store.get(up["resp"]))
            if up.get("role") == "summariser" and up.get("status") == 200 and reply.get("text"):
                evidence["summaries"].append(reply["text"])
            if up.get("role") == "probe_main":
                evidence["replies"].append(canon(reply))
                if (up.get("status") == 200 and up.get("served_by") == "live" and
                        any(d.get("sent") and d.get("status") == 200 for d in diags)):
                    evidence["live_probes"].append((row.get("cursor") or {}).get("turn"))
    return evidence


def retained_summary(adapter, attempt, summaries):
    first = next((r for r in adapter.records() if r.get("attempt_id") == attempt and "req" in r), None)
    if first is None or not summaries:
        return False
    body = json.loads(BlobStore(adapter.paths["root"] / "ledger/blobs", Guard([])).get(first["req"]))

    def strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, (list, dict)):
            for item in (value.values() if isinstance(value, dict) else value):
                yield from strings(item)
    return any(summary in text for text in strings(body) for summary in summaries)


def routes_for(entry, live=False):
    model = "gpt-6.1-sol" if live else "probe-model"
    return {"routes": [{"system": entry["name"], "segment": "seg0", "probe_model": model,
                        "alias": "bicentennial-main", "summariser": model if live else "summary-model",
                        "vision": None, "served_by": "live" if live else "scripted"}]}


def build_arm(label, root, script, run, active, *, responder=None, login=None,
              checkout=None, mem0_source=None, worker_argv=None):
    entry = load(REGISTRY / ("mem0-oss.toml" if label == "mem0-oss" else "hermes-native.toml"))
    pin = load(REGISTRY / "hermes-native.toml")["artifact"]
    if label == "mem0-oss" and mem0_source is None:
        raise BoundaryBlocked("mem0_source_missing")
    routes = routes_for(entry, responder is not None)
    answer = responder or ProbeResponder(entry)
    if label == "mem0-oss" and responder:
        answer = SplitResponder(responder, ScriptedResponder(entry))
    root.mkdir(parents=True)
    kwargs = dict(script=script, route_table=RouteTable.load(routes), schedule=FaultLite.load([], script),
                  responder=answer, clock=SimClock(root / "clock.json", BASE, STEP), root=root,
                  scratch=root.parent, life=script["life_id"], branch="B0", run=run,
                  checkout=checkout, harness_pin=pin, worker_argv=worker_argv)
    if label == "no-memory":
        adapter = no_memory_cell(**kwargs)
    else:
        hook = WipeOnWake(entry, {"HERMES_HOME": root / "hermes-home"}, root / "control") if label == "wiped" else None
        adapter = HermesAdapter(entry, before_spawn=hook,
                                plugin=PROVIDERS[label] if label == "mem0-oss" else None, **kwargs)
    try:
        (adapter.paths["hermes_home"] / ".bicentennial-sandbox").write_bytes(b"")
        if login:
            adapter.director.guard = NeedleGuard(login, base=Guard([]))
        gate = adapter._gate
        def gated(readings):
            start = len(readings)
            try:
                active.omit(gate, readings)
                marker = active.omit(read_marker)
                readings.append({"exit": marker.exit, "state": marker.state})
                if marker.state == "unset":
                    raise Stop("marker_refused")
            finally:
                active.markers.extend(readings[start:])
        adapter._gate = gated
        arm = Arm(adapter, entry, label=label)
        if label == "mem0-oss":
            arm.cell = PluginCell(entry, adapter)
            arm.cell.install(mem0_source, alias="bicentennial-main")
        return arm, routes
    except BaseException:
        adapter.close()
        raise


def finish_arm(arm, record):
    rows, adapter = arm.adapter.records(), arm.adapter
    summary = adapter.close()
    record.update(unknown_requests=sum(r.get("role") == "unknown" for r in rows),
        malformed_or_egress=sum(r.get("subrole") in ("malformed_body", "egress") for r in rows),
        auth_path_requests=sum("openai-codex" in r.get("path", "") for r in rows),
        ledger=verify(adapter.paths["root"] / "ledger"), non_loopback=len(summary["non_loopback"]),
        digest=adapter.stable_digest())
    return record


def public(value):
    """Fail closed on unstructured strings; public records contain no local locations."""
    if isinstance(value, dict):
        return {str(k): public(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [public(v) for v in value]
    if isinstance(value, str):
        forbidden = [os.environ.get(k, "") for k in ("BICENTENNIAL_SOL_BASE_URL", "BICENTENNIAL_SOL_AUTH",
                     "BICENTENNIAL_SOL_TOKEN_URL", "BICENTENNIAL_SOL_CLIENT_ID")]
        if re.search(r"(^|[\s:'\"])/", value) or value.startswith("~") or "://" in value or any(v and v in value for v in forbidden):
            return "sha256:" + sha256_canon(value)
    return value


def write_result(path, value, guard=None):
    data = canon(public(value)) + b"\n"
    if guard:
        data = guard.check(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def preflight(args):
    reexec_niced(sys.argv)
    marker = read_marker()
    if marker.exit != 0 or marker.state == "unset":
        raise Stop("marker_refused")
    if os.environ.get("BICENTENNIAL_OPERATOR") != "benchmark":
        raise Stop("benchmark_operator_required")
    if args.part != "twin":
        for suffix in ("BASE_URL", "TOKEN_URL", "CLIENT_ID", "AUTH"):
            name = "BICENTENNIAL_SOL_" + suffix
            if not os.environ.get(name):
                raise Stop("missing:" + name)
    out = args.out.resolve()
    if out.exists() or out.is_relative_to((Path.home() / ".hermes").resolve()):
        raise Stop("out_not_fresh")
    checkout = Path(os.environ.get("BICENTENNIAL_HERMES", ""))
    if not os.environ.get("BICENTENNIAL_HERMES") or not (checkout / ".venv/bin/python").is_file():
        raise Stop("hermes_checkout_required")
    try:
        verify_pin(checkout, load(REGISTRY / "hermes-native.toml")["artifact"])
    except PinMismatch:
        raise Stop("harness_pin_mismatch") from None
    return {"exit": marker.exit, "state": marker.state}, checkout


def live_responder(args, spend):
    login = open_login(os.environ["BICENTENNIAL_SOL_AUTH"], os.environ["BICENTENNIAL_SOL_TOKEN_URL"],
                       os.environ["BICENTENNIAL_SOL_CLIENT_ID"], args.run)
    pacer, holds = Pacer(RATE_PER_MIN, BURST, threading.Event()), Holds()
    up = Upstream("sol", "gpt-6.1-sol", os.environ["BICENTENNIAL_SOL_BASE_URL"], "responses", spend,
                  Price(0, 0), args.max_output_tokens, effort="medium", send_cap=False)
    live = LiveResponder("A", pacer, auth_for(login, pacer), [up], holds, max_sends=MAX_SENDS)
    return ResponsesBridge(CredentialResponder(live, login)), holds, login


def execute(args, marker, checkout, *, worker_argv=None, sleep=time.sleep):
    out, active = args.out, ActiveClock()
    out.mkdir(parents=True)
    spend = zero_spend(out / "spend.json")
    responder, holds, login = live_responder(args, spend) if args.part != "twin" else (None, None, None)
    records, evidence, code, extra, markers = {}, {}, 0, None, [marker]
    system, probe, nonces = canary_scripts(args.run)
    order = [(a, "micro", suffix) for a in args.arms for suffix in ("u", "p")] if args.part == "twin" else [
        ("hermes-native", "micro", ""), ("hermes-native", "canary", ""), ("no-memory", "canary", ""),
        ("wiped", "micro", ""), ("no-memory", "micro", ""), ("mem0-oss", "micro", "")]
    if args.part == "resume24":
        order = [("hermes-native", "micro", "")]
    try:
        for label, life, suffix in order:
            if life == "micro" and label not in args.arms:
                continue
            execution = f"{label}.{life}" + (f"-{suffix}" if suffix else "")
            script = (probe if label == "no-memory" else system) if life == "canary" else micro_script(label == "no-memory")
            record = {"arm": label, "part": args.part, "stop": "interrupted", "sessions_run": []}
            reason = admission_stop(responder.state() if responder else {}, {}, active(), args.part)
            if reason:
                records[execution] = dict(record, stop=reason)
                code = 2 if code != 1 else code
                break
            try:
                arm, routes = build_arm(label, out / "cells" / execution, script, args.run, active,
                    responder=responder, login=login, checkout=checkout, mem0_source=args.mem0_source,
                    worker_argv=worker_argv)
            except (PinMismatch, BoundaryBlocked):
                records[execution] = {"arm": label, "part": args.part, "stop": "blocked"}
                code = 2 if code != 1 else code
                continue
            refused = False
            try:
                arm.execution = f"{label}.{life}"
                delay = args.wait_s if args.part == "resume24" else (0 if suffix == "u" else PAUSE_S)
                record, status = run_life(arm, args.part, args.run, routes, script=script, wait_s=delay,
                    sleep=lambda seconds: active.omit(sleep, seconds), responder=responder, holds=holds, active_seconds=active)
                evidence[execution] = observations(arm.adapter)
                record["sends"] = evidence[execution]["sends"]
                if life == "canary" and label == "no-memory":
                    ev = evidence[execution]
                    ev["replies"] += canary_surface_replies(arm.adapter.paths["hermes_home"], nonces)
                    ev["replies"] += [text for _, text in arm.finals]
                    ev["live_probes"] = sorted(set(ev["live_probes"]) & {turn for turn, _ in arm.finals})
                if args.part == "resume24":
                    ev = evidence[execution]
                    extra = dict(arm.resume_record or {"stop": record["stop"], "resumed_ok": False,
                                 "pause_after": None, "holds_compaction": False, "summariser_before": 0,
                                 "wait_s": 0, "equal": None, "changed": [], "resumed_total": 0,
                                 "post_resume": {}, "account_switched": False, "spare_account": "not run (deferred)"},
                                 dropped_items=ev["dropped_items"], encrypted_bodies=ev["encrypted_bodies"],
                                 drift=responder.state().get("identity_drift"))
            except Stop as exc:
                record["stop"], status, refused = str(exc), 2, True
            finally:
                finish_arm(arm, record)
            record["execution"] = execution
            records[execution] = record
            if any(record[k] for k in ("unknown_requests", "non_loopback", "auth_path_requests")):
                record["stop"], status = "unexpected_request", 2
            code = 1 if 1 in (code, status) else max(code, status)
            if suffix == "p" and not record["stop"] and records.get(f"{label}.micro-u", {}).get("digest") != record["digest"]:
                record["stop"], code = "twin_digest_mismatch", 1
            if (refused or record["stop"] in {"identity_drift", "spend_stop", "login_stop", "hold:quota", "budget", "unexpected_request"}
                    or (record["stop"] or "").startswith("responder_stopped:")):
                break
        if args.part == "twin":
            for label in args.arms:
                twins = [records.get(f"{label}.micro-{s}", {}) for s in ("u", "p")]
                if all("digest" in r for r in twins) and twins[0]["digest"] != twins[1]["digest"]:
                    code = 1
        if args.part == "live":
            source = evidence.get("hermes-native.canary", {})
            control = evidence.get("no-memory.canary", {})
            extra = canary_result(source.get("sent", []), control.get("replies", []), nonces,
                                  live_probes=control.get("live_probes", []))
            if not all(k in evidence for k in ("hermes-native.canary", "no-memory.canary")):
                extra["verdict"] = "not_run"
            status = {"pass": 0, "fail": 1, "vacuous": 2, "incomplete": 2, "not_run": 2}[extra["verdict"]]
            code = 1 if 1 in (code, status) else max(code, status)
    except CredentialLeak:
        code = 1
    finally:
        scanned = scan(login, [out], args.run) if login else {"hits": {}, "unreadable": 0}
        if login and any(row.get("type") == "guard" for row in login.log):
            code = 1
    if scanned["hits"] or scanned["unreadable"]:
        code = 1
    guard = NeedleGuard(login, base=Guard([])) if login else Guard([])
    for execution, record in records.items():
        write_result(out / "arms" / f"{execution}.json", record, guard)
    if extra is not None:
        write_result(out / ("canary.json" if args.part == "live" else "resume24.json"), extra, guard)
    with spend.locked() as state:
        spending = dict(state)
    run_record = {"part": args.part, "exit": code, "spend": spending,
        "served_identities": responder.served_identities() if responder else {},
        "state": responder.state() if responder else {}, "sends": responder.state()["sends"] if responder else 0,
        "markers": markers + active.markers, "scan": scanned, "max_output_tokens": args.max_output_tokens,
        "argv": role_argv(args)}
    write_result(out / "run.json", run_record, guard)
    if login:
        scanned = scan(login, [out], args.run)
        code = 1 if scanned["hits"] or scanned["unreadable"] else code
        write_result(out / "run.json", dict(run_record, scan=scanned, exit=code), guard)
    return code


def role_argv(args):
    result = [args.part, "--run", args.run, "--out", "OUT", "--arms", ",".join(args.arms)]
    if args.max_output_tokens is not None:
        result += ["--max-output-tokens", str(args.max_output_tokens)]
    if args.part == "resume24":
        result += ["--wait-s", str(args.wait_s)]
    for key, role in (("mem0_source", "MEM0_SOURCE"), ("resume_auth", "AUTH_B")):
        if getattr(args, key, None) is not None:
            result += ["--" + key.replace("_", "-"), role]
    return result


def summarise(paths):
    result = []
    for path in map(Path, paths):
        files = sorted(path.glob("arms/*.json")) + [path / name for name in ("run.json", "canary.json", "resume24.json")
                                                         if (path / name).exists()]
        counts = []
        for file in files:
            row = json.loads(file.read_bytes())
            boundaries = row.get("boundaries", [])
            counts.append({"hash": sha256_canon(row), "boundaries": len(boundaries),
                "equal": sum(b.get("equal") is True for b in boundaries),
                "unsettled": sum(b.get("pause") == "unsettled" for b in boundaries),
                "declared_matches": sum(b.get("declared_matches") is True for b in boundaries),
                **{k: row[k] for k in ("items", "sent", "carried", "sends", "unknown_requests", "non_loopback")
                   if type(row.get(k)) is int}})
        result.append({"files": len(files), "records": counts,
                       "arms": sum(f.parent.name == "arms" for f in files)})
    return {"parts": result}


def main(argv=None):
    keyed.assert_hashseed()
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="part", required=True)
    for part in ("twin", "live", "resume24"):
        command = commands.add_parser(part)
        command.add_argument("--run", required=True)
        command.add_argument("--out", type=Path, required=True)
        command.add_argument("--arms", choices=[",".join(p) for n in range(1, 5) for p in permutations(ARMS, n)],
                             metavar="ARM[,ARM...]", default="hermes-native" if part == "resume24" else "hermes-native,wiped,no-memory")
        command.add_argument("--mem0-source", type=Path)
        command.add_argument("--max-output-tokens", type=int, required=part != "twin", default=None)
        command.add_argument("--wait-s", type=int, default=86400)
        command.add_argument("--resume-auth", type=Path)
    commands.add_parser("summarise").add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if args.part == "summarise":
        print(canon(summarise(args.paths)).decode())
        return 0
    args.arms = args.arms.split(",")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.run):
        parser.error("run must be an ASCII identifier")
    if args.part == "resume24" and args.arms != ["hermes-native"]:
        parser.error("resume24 uses hermes-native")
    if any(a not in ARMS for a in args.arms) or len(set(args.arms)) != len(args.arms):
        parser.error("arms must be distinct supported S9 arms")
    if args.part == "resume24" and (args.wait_s < 86400 or args.resume_auth is not None):
        parser.error("resume24 requires at least 86400 seconds; spare account deferred")
    if args.max_output_tokens is not None and args.max_output_tokens <= 0:
        parser.error("max-output-tokens must be positive")
    try:
        marker, checkout = preflight(args)
        return execute(args, marker, checkout)
    except Stop as exc:
        exit_on_refusal(exc)
    except CredentialLeak:
        return 1
    except (OSError, ValueError, RuntimeError) as exc:
        print("S9 refused:" + type(exc).__name__, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
