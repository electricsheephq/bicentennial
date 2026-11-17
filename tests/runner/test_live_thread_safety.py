"""Transport-free reproducer for sharing the live stack between unit threads."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

from bicentennial.director.responder import Call
from bicentennial.director.upstream import LiveResponder, bridge
from bicentennial.director.upstream.login import CredentialResponder
from bicentennial.runner.live import LiveStack


class WatchedLatch:
    """The bridge's latch, which sets an event when a caller reaches it while another caller holds it."""

    def __init__(self, contended):
        self.lock, self.contended = Lock(), contended

    def __enter__(self):
        if self.lock.locked():
            self.contended.set()
        self.lock.acquire()
        return self

    def __exit__(self, *exc):
        self.lock.release()


def stack(tmp_path):
    pacer = SimpleNamespace(stop=Event())
    upstream = SimpleNamespace(model="synthetic", effort="medium", spend=object())
    responder = LiveResponder("synthetic", pacer, None, [upstream], None)
    # No request can reach auth or transport. No login is constructed or read.
    return responder, LiveStack(CredentialResponder(responder, SimpleNamespace(dead="")), tmp_path / "holder")


def failing(key):
    return Call("probe_main", "", "chat", {key: 0}, "synthetic", None, key)


@pytest.mark.parametrize("first,second", [("a_extra", "z_extra"), ("z_extra", "a_extra")])
def test_concurrent_translation_failures_keep_the_first_reason(monkeypatch, tmp_path, first, second):
    entered, first_stopping, second_moved = Barrier(2), Event(), Event()
    translate = bridge.to_responses
    first_reason, second_reason = ("bridge_unmapped_key:" + key for key in (first, second))

    def interleaved(body, **kwargs):
        # Both calls pass the bridge's failure check before either fails. The second fails only once the first
        # is stopping the inner stack.
        entered.wait(timeout=5)
        if second in body:
            assert first_stopping.wait(timeout=5)
        return translate(body, **kwargs)

    monkeypatch.setattr(bridge, "to_responses", interleaved)
    responder, live = stack(tmp_path)
    live._latch = WatchedLatch(second_moved)
    stop, seen = responder.stop, {}

    def interleaved_stop(reason):
        if reason != first_reason:
            # Before #604 the second caller stopped the inner stack with its own reason, outside the latch.
            stop(reason)
            second_moved.set()
            return
        first_stopping.set()
        # The first stop lands only after the second failure has stopped the inner stack itself, or has reached
        # the latch that the first caller still holds.
        assert second_moved.wait(timeout=5)
        seen["between"] = live.state()["stop_reason"]
        stop(reason)

    monkeypatch.setattr(responder, "stop", interleaved_stop)

    def fail(key):
        with pytest.raises(ValueError) as caught:
            live.respond(failing(key))
        return str(caught.value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(fail, first), pool.submit(fail, second)
        errors = (a.result(timeout=10), b.result(timeout=10))
    observed = dict(errors=errors, between=seen.get("between"), inner=responder.state()["stop_reason"],
                    stack=live.state()["stop_reason"], latch=live.failure, active=live._active)
    assert observed == dict(errors=(first_reason, second_reason), between=None, inner=first_reason,
                            stack=first_reason, latch=first_reason, active=0)


def test_a_translation_failure_names_no_reason_until_the_inner_stack_has_one(monkeypatch, tmp_path):
    # Another source, here a credential failure on another unit's send, stops the inner stack while the bridge
    # is stopping it. state() must not name the bridge's reason first and then switch to the other one.
    responder, live = stack(tmp_path)
    stop, seen = responder.stop, []

    def other_source_first(reason):
        seen.append(live.state()["stop_reason"])
        stop("upstream_401")
        stop(reason)

    monkeypatch.setattr(responder, "stop", other_source_first)
    with pytest.raises(ValueError, match="^bridge_unmapped_key:a_extra$"):
        live.respond(failing("a_extra"))
    assert dict(seen=seen, stack=live.state()["stop_reason"], latch=live.failure) == dict(
        seen=[None], stack="upstream_401", latch="bridge_unmapped_key:a_extra")
