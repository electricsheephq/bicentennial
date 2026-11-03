"""Transport-free reproducer for sharing the live stack between unit threads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from bicentennial.director.responder import Call
from bicentennial.director.upstream import LiveResponder, bridge
from bicentennial.director.upstream.login import CredentialResponder
from bicentennial.runner.live import LiveStack


@pytest.mark.parametrize("first,second", [("a_extra", "z_extra"), ("z_extra", "a_extra")])
def test_concurrent_translation_failures_preserve_each_cause(monkeypatch, tmp_path, first, second):
    entered, first_latched, second_latched = Barrier(2), Event(), Event()
    translate = bridge.to_responses
    first_reason, second_reason = ("bridge_unmapped_key:" + key for key in (first, second))

    def interleaved(body, **kwargs):
        # Both calls have passed the bridge's failure check before either can fail.
        entered.wait(timeout=5)
        if second in body:
            assert first_latched.wait(timeout=5)
        return translate(body, **kwargs)

    monkeypatch.setattr(bridge, "to_responses", interleaved)
    pacer = SimpleNamespace(stop=Event())
    upstream = SimpleNamespace(model="synthetic", effort="medium", spend=object())
    responder = LiveResponder("synthetic", pacer, None, [upstream], None)
    stop = responder.stop

    def interleaved_stop(reason):
        stop(reason)
        if reason == first_reason:
            first_latched.set()
            assert second_latched.wait(timeout=5)
        else:
            second_latched.set()

    monkeypatch.setattr(responder, "stop", interleaved_stop)
    # Neither request can reach auth or transport. No login is constructed or read.
    live = LiveStack(CredentialResponder(responder, SimpleNamespace(dead="")), tmp_path / "holder")

    def fail(key):
        call = Call("probe_main", "", "chat", {key: 0}, "synthetic", None, key)
        with pytest.raises(ValueError) as caught:
            live.respond(call)
        return str(caught.value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(fail, first), pool.submit(fail, second)
        errors = (a.result(timeout=10), b.result(timeout=10))
    observed = dict(errors=errors, inner=responder.state()["stop_reason"],
                    stack=live.state()["stop_reason"], active=live._active)
    assert observed == dict(errors=(first_reason, second_reason), inner=first_reason,
                            stack=first_reason, active=0)
