"""Worker start snapshots and adapter baseline subtraction, without sockets."""

import json
import runpy
import sys
import types
from collections import Counter
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace

from bicentennial.director.roles import MAIN_ROLES
from bicentennial.harness.hermes import adapter
from bicentennial.report.receipt import background_summary as summarize_background


def background_summary(*args, **kwargs):
    return summarize_background(*args, **kwargs, main_roles=MAIN_ROLES)


def test_worker_reports_threads_before_conversation_and_after_open(monkeypatch):
    monkeypatch.setenv("HERMES_SESSION_ID", "thread-test")
    release, finished = Event(), Event()
    baseline = Thread(target=release.wait, name="baseline-test-thread")
    late = Thread(target=release.wait, name="late-test-thread")
    calls = []

    def conversation(**kw):
        calls.append(kw)
        if len(calls) == 1:
            late.start()
        else:
            release.set()
            baseline.join(2)
            late.join(2)
            finished.set()
        return dict(messages=[], final_response="done")

    agent = SimpleNamespace(run_conversation=conversation)
    state = SimpleNamespace(agent=agent, session_id="session", cwd=".", history=[])

    def create(cwd):
        baseline.start()
        return state

    manager = SimpleNamespace(create_session=create, save_session=lambda sid: None, end_all_sessions=lambda: None)
    modules = {
        "acp_adapter.entry": dict(_load_env=lambda: None, _setup_logging=lambda: None),
        "agent.ssl_verify": dict(install_truststore=lambda: None),
        "acp_adapter.session": dict(SessionManager=lambda: manager),
        "gateway.session_context": dict(clear_session_vars=lambda tokens: None,
                                         set_session_vars=lambda **kw: None),
    }
    for name, attrs in modules.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    worker = runpy.run_path(str(adapter.WORKER))
    emitted = []
    worker["main"].__globals__["emit"] = emitted.append
    ops = [dict(op="open", cwd="."), dict(op="turn", text="one"), dict(op="turn", text="two"), dict(op="end")]
    def lines():
        for n, op in enumerate(ops):
            if n == 2:
                # A short turn wait elapses with no request in flight; the thread survives it.
                assert late.is_alive()
                Event().wait(0.55)
                assert late.is_alive()
            yield json.dumps(op)

    monkeypatch.setattr(sys, "stdin", lines())
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    try:
        worker["main"]()
        assert finished.is_set()
        assert "baseline-test-thread" in emitted[1]["alive_threads"]
        assert "late-test-thread" not in emitted[2]["alive_threads"]
        assert "late-test-thread" in emitted[3]["alive_threads"]
        assert "baseline-test-thread" in emitted[3]["alive_threads"]
    finally:
        release.set()
        for thread in (baseline, late):
            if thread.ident is not None:
                thread.join(2)


def test_adapter_counts_only_nonbaseline_threads_at_each_start(tmp_path):
    shared = runpy.run_path(str(Path(__file__).with_name("test_turn_wait.py")))
    observed = []
    names = [["main", "baseline"], ["main", "baseline", "late", "late"],
             ["main", "baseline", "late"], ["main", "baseline"], ["main", "baseline"]]
    shared["fake_session"](tmp_path / "session", 0.5, faults={},
        baseline=Counter(["main", "baseline"]), thread_names=names, observed=observed)
    assert observed == [0, 2, 1, 0, 0]
    assert background_summary("system", thread_counts=observed)["threads_at_turn_start"] == dict(count=2, max_alive=2)
