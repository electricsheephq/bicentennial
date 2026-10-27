"""Local live responder: account pacing, session holds and run-wide reservations."""
import threading
from dataclasses import asdict
from hashlib import sha256

from bicentennial.canon import canon
from bicentennial.director.responder import Reply

from . import forward
from .forward import RETRYABLE, Upstream
from .holds import Holds
from .pacer import BURST, RATE_PER_MIN, Pacer

__all__ = ["BURST", "RATE_PER_MIN", "Holds", "LiveResponder", "Pacer", "Upstream"]


class LiveResponder:
    def __init__(self, account, pacer, auth, upstreams, holds, *, sleep=None, max_sends=None):
        upstreams = tuple(upstreams)
        if len({u.model for u in upstreams}) != len(upstreams) or not isinstance(account, str) or not account or (max_sends is not None and (type(max_sends) is not int or max_sends < 0)):
            raise ValueError("invalid responder configuration")
        if len({id(u.spend) for u in upstreams}) > 1:
            raise ValueError("one run-wide Spend required")
        self.account, self.pacer, self.auth, self.holds = account, pacer, auth, holds
        self.upstreams, self.sleep, self.max_sends = {u.model: u for u in upstreams}, sleep or pacer.stop.wait, max_sends
        self.lock, self.identities = threading.Lock(), {}
        self.values = dict(stopped=False, stop_reason=None, spend_stopped=False, failure_streak=0, unparsed_streak=0, sends=0, identity_drift=None)

    def stop(self, reason):
        with self.lock:
            self.values["stop_reason"] = self.values["stop_reason"] or reason
            self.values["stopped"] = True
            self.pacer.stop.set()

    def state(self):
        with self.lock:
            return dict(self.values, stopped=self.values["stopped"] or self.pacer.stop.is_set(), identity_drift=dict(self.values["identity_drift"]) if self.values["identity_drift"] else None)

    def served_identities(self):
        with self.lock:
            return dict(self.identities)

    def _diag(self, up, n):
        return dict(kind="try", try_=n, upstream=up.name if up else None, account=self.account, sent=False,
                    status=0, category=None, retry_wait_s=0, retry_after_s=None, pace_wait_ms=0, t_sent_ms=0,
                    t_ms=0, reserved=None, charged=None, sent_sha256=None, served_model=None, effort_is_pin=None,
                    n_unparsed=0, n_dropped_items=0, body_shape=None)

    def _reply(self, call, served, diags, result=None):
        reply = Reply(200 if result else 503, served, "live", call.model, result["text"] if result else "",
                      result["tool_calls"] if result else (), usage=result["usage"] if result else None, upstream=tuple(diags))
        canon(asdict(reply))
        return reply

    def respond(self, call):
        diags = []
        try:
            return self._respond(call, diags)
        except Exception as exc:
            self.stop(f"responder_error:{type(exc).__name__.lower()}")
            if diags:
                diags[-1]["stop_reason"] = self.state()["stop_reason"]
            return self._reply(call, "live_stopped", diags)

    def _respond(self, call, diags):
        up, reason, held_total = self.upstreams.get(call.model), "glm", 0
        if self.state()["stopped"] or self.state()["spend_stopped"] or up is None or call.wire != up.wire:
            served = "live_stopped" if self.state()["stopped"] else "live_spend_stop" if self.state()["spend_stopped"] else "live_no_upstream" if up is None else "live_unsupported"
            d = self._diag(up, 1)
            d["try"] = d.pop("try_")
            return self._reply(call, served, [d])
        body = forward.wire_body(call)
        data = canon(body)
        cap = next((body[k] for k in (("max_output_tokens",) if call.wire == "responses" else ("max_completion_tokens", "max_tokens")) if type(body.get(k)) is int and body[k] > 0), up.max_output_tokens)
        while True:
            for wait in (5, 15, 45, None):
                t0 = self.pacer.clock()
                held = self.holds._wait(call.run_key, glm_plan=up.glm_plan, stop=self.pacer.stop, max_hold_s=max(0, self.holds.max_hold_s - held_total / 1000))
                elapsed = round((self.pacer.clock() - t0) * 1000)
                held_total += elapsed
                if elapsed or held is None:
                    diags.append(dict(kind="hold", reason=reason, held_ms=elapsed))
                if held is None:
                    if not self.state()["stopped"]:
                        self._failure()
                    return self._reply(call, "live_stopped" if self.state()["stopped"] and self.state()["stop_reason"] != "upstream_failures_3_in_a_row" else "live_hold_expired", diags)
                d = self._diag(up, 1 + sum(x["kind"] == "try" for x in diags))
                d["try"] = d.pop("try_")
                diags.append(d)
                result, served = self._try(up, body, data, cap, d)
                if result is None:
                    return self._reply(call, served, diags)
                if d["retry_after_s"] is not None:
                    self.pacer.defer(d["retry_after_s"])
                if result["stop_reason"]:
                    self.stop(result["stop_reason"])
                with self.lock:
                    if result["forward"]:
                        self.values.update(failure_streak=0, unparsed_streak=0)
                        identity = result["served_model"] or "unidentified"
                        d["served_model"] = identity
                        baseline = self.identities.setdefault(call.model, identity)
                        if identity == "unidentified" or identity != baseline:
                            d["identity_changed"] = True
                            self.values["identity_drift"] = self.values["identity_drift"] or dict(model=call.model, baseline=baseline, served=identity)
                    elif result["category"] == "unparsed":
                        self.values["unparsed_streak"] += 1
                    unparsed = self.values["unparsed_streak"] >= 3
                if unparsed:
                    self.stop("upstream_unparsed_3_in_a_row")
                if self.state()["stopped"]:
                    d["stop_reason"] = self.state()["stop_reason"]
                if result["forward"]:
                    return self._reply(call, "live", diags, result)
                retry = not self.state()["stopped"] and d["category"] in RETRYABLE and wait is not None
                d["retry_wait_s"] = wait if retry else 0
                if not retry:
                    break
                for _ in range(wait):
                    if self.state()["stopped"]:
                        return self._reply(call, "live_stopped", diags)
                    self.sleep(1)
            if not self.state()["stopped"] and d["category"] in ("quota", "rate"):
                reason = d["category"]
                self.holds.hold(call.run_key, reason)
                continue
            if d["sent"] and d["category"] != "unparsed":
                self._failure()
            if self.state()["stopped"]:
                d["stop_reason"] = self.state()["stop_reason"]
            return self._reply(call, "live_unavailable", diags)

    def _failure(self):
        with self.lock:
            self.values["failure_streak"] += 1
            failed = self.values["failure_streak"] >= 3
        if failed:
            self.stop("upstream_failures_3_in_a_row")

    def _try(self, up, body, data, cap, d):
        rid = None
        try:
            with self.lock:
                if self.values["spend_stopped"] or (self.max_sends is not None and self.values["sends"] >= self.max_sends):
                    self.values["spend_stopped"] = True
                    return None, "live_spend_stop"
                rid = up.spend.reserve(len(data), cap, up.price)
                if rid is None:
                    self.values["spend_stopped"] = True
                    return None, "live_spend_stop"
            d["reserved"] = up.price.cost(len(data), cap)
            d["pace_wait_ms"] = self.pacer.acquire()
            if d["pace_wait_ms"] is None or self.state()["stopped"]:
                d["pace_wait_ms"] = 0
                return None, "live_stopped"
            headers = {**self.auth(), "Content-Type": "application/json", "Accept": "text/event-stream" if up.wire == "responses" else "application/json"}
            with self.lock:
                if self.pacer.stop.is_set():
                    return None, "live_stopped"
                if self.max_sends is not None and self.values["sends"] >= self.max_sends:
                    self.values["spend_stopped"] = True
                    return None, "live_spend_stop"
                self.values["sends"] += 1
            d.update(sent=True, sent_sha256=sha256(data).hexdigest(), t_sent_ms=round(self.pacer.clock() * 1000), effort_is_pin=(body.get("reasoning") or {}).get("effort") == up.effort if up.effort and up.wire == "responses" else None)
            t0 = self.pacer.clock()
            result = forward.send(up, data, headers)
            d.update({k: result[k] for k in ("status", "category", "retry_after_s", "body_shape", "n_unparsed", "n_dropped_items", "served_model")}, t_ms=round((self.pacer.clock() - t0) * 1000))
            return result, None
        finally:
            if rid is not None:
                usage = (result.get("usage") or {}) if d["sent"] and "result" in locals() else {}
                keys = ("input_tokens", "output_tokens") if up.wire == "responses" else ("prompt_tokens", "completion_tokens")
                normalized = dict(zip(("prompt_tokens", "completion_tokens"), (usage[k] for k in keys), strict=True)) if all(k in usage for k in keys) else {}
                d["charged"] = up.spend.settle(rid, normalized, provably_unsent=not d["sent"])[0]
