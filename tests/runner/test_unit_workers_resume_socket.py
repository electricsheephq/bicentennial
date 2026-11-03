"""Real fake-host session identities reach shared holds under separate arm keys."""

from threading import Lock

from test_t1 import environment, installed, prepare  # noqa: F401
from test_unit_workers_socket import (  # noqa: F401
    SharedStack,
    install_fake_driver,
    sockets,
)

from bicentennial.director.upstream.holds import Holds
from bicentennial.runner import units


def test_two_arm_real_session_hold_keys(sockets, installed, tmp_path, monkeypatch):  # noqa: F811
    install_fake_driver(monkeypatch)
    ctx, holds, calls, lock = prepare(installed), Holds(), [], Lock()

    class RecordingStack(SharedStack):
        def respond(self, call):
            with lock:
                calls.append(call)
                holds.hold(call.run_key, "quota")
            return super().respond(call)

    queue = [units.Unit(units.Arm.from_context(ctx, key), ctx.packs[0], "B0",
                        tmp_path / key, tmp_path / key / "out") for key in ("a", "b")]
    collected = units.schedule(ctx, queue, units._Guard(RecordingStack()), roots=2)
    collected.merge([], [])
    identities = [{row["attempt_id"] for row in collected.results[u.identity].runs[0].records}
                  for u in queue]
    assert all(identities) and not identities[0] & identities[1]
    sent = {c.run_key for c in calls}
    assert sent == set(holds.active)
    assert all(sent & arm_ids for arm_ids in identities)
    assert all(c.run_key in identities[0] | identities[1] for c in calls)
