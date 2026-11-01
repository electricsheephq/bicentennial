"""Unwired live Responses stack for a later runner lane."""

import os
import threading
from pathlib import Path

from bicentennial.director.upstream import (
    BURST,
    RATE_PER_MIN,
    Holds,
    LiveResponder,
    Pacer,
    Upstream,
)
from bicentennial.director.upstream import login as custody
from bicentennial.director.upstream.bridge import ResponsesBridge
from bicentennial.runner.spend import Price, Spend

# One build or close at a time, so a holder entry that changed during a build is that build's own.
_BUILD = threading.Lock()


def _release(holder_path):
    fd = custody.HOME_HOLDERS.pop(holder_path, None)
    if fd is not None:
        os.close(fd)


class LiveStack(ResponsesBridge):
    def __init__(self, inner, holder_path):
        super().__init__(inner)
        self.holder_path, self.closed = holder_path, False

    def close(self):
        with _BUILD:
            if not self.closed:
                self.inner.stop("closed")
                _release(self.holder_path)
                self.closed = True


def build_live_stack(spend_path, *, login_home, token_url, client_id, run, base_url,
                     max_output_tokens, max_sends, model="gpt-6.1-sol", effort="medium",
                     rate=RATE_PER_MIN, burst=BURST):
    """login_home is the directory containing auth.json; close releases its holder."""
    if type(max_sends) is not int or max_sends < 0:
        raise ValueError("invalid responder configuration")
    if not effort:
        raise ValueError("bridge_effort_unpinned")
    spend = Spend(spend_path, 0, Price(0, 0))
    upstream = Upstream("sol", model, base_url, "responses", spend, Price(0, 0),
                        max_output_tokens, effort=effort, send_cap=False)
    pacer, holds = Pacer(rate, burst, threading.Event()), Holds()
    store = Path(login_home) / "auth.json"
    holder_path = store.with_name("holder.lock").resolve()
    with _BUILD:
        previous = custody.HOME_HOLDERS.get(holder_path)
        try:
            login = custody.open_login(store, token_url, client_id, run)
            live = LiveResponder("sol-0", pacer, custody.auth_for(login, pacer), [upstream], holds,
                                 max_sends=max_sends)
            return LiveStack(custody.CredentialResponder(live, login), holder_path)
        except Exception:
            if custody.HOME_HOLDERS.get(holder_path) != previous:
                _release(holder_path)
            raise
