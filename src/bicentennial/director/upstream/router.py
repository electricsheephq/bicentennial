"""Opt-in live probe routing; other classified roles retain their scripted responder."""

import threading
from collections import Counter

from bicentennial.director.responder import Reply


class ProbeLiveRouter:
    def __init__(self, scripted, live, live_roles=frozenset({"probe_main"})):
        self.scripted, self.live, self.live_roles = scripted, live, frozenset(live_roles)
        self.lock, self.live_calls = threading.Lock(), Counter()

    def respond(self, call):
        if call.role not in self.live_roles:
            return self.scripted.respond(call)
        # Chat is accepted only by a Responses bridge; the upstream sees Responses.
        if call.wire != self.live.wire and not (call.wire == "chat" and self.live.wire == "responses"):
            return Reply(503, "live_unsupported", "live", call.model)
        reply = self.live.respond(call)
        if reply.status == 200 and reply.served_by == "live":
            with self.lock:
                self.live_calls[call.role] += 1
        return reply

    def state(self):
        scripted = getattr(self.scripted, "state", lambda: {})()
        live = self.live.state()
        with self.lock:
            counts = dict(self.live_calls)
        return dict(scripted | live, scripted=scripted, live=live, live_calls_by_role=counts)

    def served_identities(self):
        return self.live.served_identities()
