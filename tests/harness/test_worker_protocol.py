"""Session worker protocol checks use finite subprocess pipes, never listening sockets."""

import json
import os
import sys
from pathlib import Path

import pytest

from bicentennial.harness.hermes import adapter

FAKE = Path(__file__).with_name("fake_line_worker.py")


@pytest.fixture
def worker_factory(tmp_path, monkeypatch):
    real, workers = adapter.subprocess.Popen, []

    def spawn(argv, *args, **kwargs):
        # Scheduling policy is covered elsewhere; retain real pipes, selector I/O and process cleanup.
        if argv[0] == "nice" and str(FAKE) in argv:
            argv = argv[argv.index(sys.executable):]
        return real(argv, *args, **kwargs)

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)

    def make(phase, reply, plugin=True):
        worker = adapter._Worker([sys.executable, str(FAKE), phase, reply], {"PATH": os.defpath},
                                 tmp_path, tmp_path / "stderr", None, plugin)
        workers.append(worker)
        return worker

    yield make
    for worker in workers:
        worker.kill()


@pytest.mark.parametrize("phase", ["open", "turn", "end"])
@pytest.mark.parametrize("reply", ["not-json", "", "null", "[]", '"text"', "7", "true", "{}",
                                   '{"ok": "yes"}', '{"ready": true}', '{"ok": true, "alive_threads": 7}'])
def test_plugin_post_ready_protocol(worker_factory, phase, reply):
    worker = worker_factory(phase, reply)
    with pytest.raises(adapter.HarnessFailed, match="^worker_protocol$"):
        worker.call(op=phase)


@pytest.mark.parametrize("phase,reply", [
    ("open", '{"ok": true}'), ("turn", '{"ok": true}'),
    ("open", '{"ok": true, "session_id": 1, "history": 0}'),
    ("open", '{"ok": true, "session_id": "s", "history": false}'),
    ("turn", '{"ok": true, "final": [], "history": 0}'),
    ("turn", '{"ok": true, "final": "", "history": "0"}'),
    ("open", '{"ok": true, "session_id": "s", "history": 0, "active_memory_providers": "holographic"}'),
    ("open", '{"ok": true, "session_id": "s", "history": 0, "active_context_engine": []}'),
])
def test_plugin_reply_matches_op(worker_factory, phase, reply):
    worker = worker_factory(phase, reply)
    with pytest.raises(adapter.HarnessFailed, match="^worker_protocol$"):
        worker.call(op=phase)


@pytest.mark.parametrize("phase", ["open", "turn", "end"])
def test_explicit_failed_op_keeps_its_existing_label(worker_factory, phase):
    reply = dict(ok=False)
    if phase == "open":
        reply.update(session_id=None, history=None, alive_threads=[])
    worker = worker_factory(phase, json.dumps(reply))
    assert worker.call(op=phase) == reply


@pytest.mark.parametrize("reply", [dict(ok=False), dict(ok=False, history=None, alive_threads=[]),
    dict(ok=False, session_id=None, alive_threads=[]), dict(ok=False, session_id=None, history=None),
    dict(ok=False, session_id="s", history=None, alive_threads=[]),
    dict(ok=False, session_id=None, history=0, alive_threads=[]),
    dict(ok=False, session_id=None, history=None, alive_threads=[1])])
def test_failed_open_requires_real_shape(worker_factory, reply):
    worker = worker_factory("open", json.dumps(reply))
    with pytest.raises(adapter.HarnessFailed, match="^worker_protocol$"):
        worker.call(op="open")


@pytest.mark.parametrize("plugin", [False, True])
def test_before_ready_stays_json_error(worker_factory, plugin):
    with pytest.raises(json.JSONDecodeError):
        worker_factory("startup", "not-json", plugin)


@pytest.mark.parametrize("reply", ["not-json", "null", "[]", "{}", '{"ok": false}'])
def test_no_plugin_keeps_legacy_line_reader(worker_factory, reply):
    worker = worker_factory("open", reply, False)
    if reply == "not-json":
        with pytest.raises(json.JSONDecodeError):
            worker.call(op="open")
    else:
        assert worker.call(op="open") == json.loads(reply)
