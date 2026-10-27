import json
import os
import shlex
import subprocess
import sys
import time
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from bicentennial.runner import guard
from bicentennial.runner.guard import Admission, Marker, admit, glm_paused, read_marker


def marker_command(tmp_path, monkeypatch, body):
    script = tmp_path / "marker.py"
    script.write_text(body)
    command = f"exec {shlex.quote(sys.executable)} {shlex.quote(str(script))}"
    monkeypatch.setenv("BICENTENNIAL_BUSY_CMD", command)


def test_unset_marker_is_idle(monkeypatch):
    monkeypatch.delenv("BICENTENNIAL_BUSY_CMD", raising=False)
    assert read_marker() == Marker(0, False, "unset")
    assert not glm_paused(read_marker())


@pytest.mark.parametrize("code,heavy,roots,admitted,limit", [
    (0, True, 12, True, 8), (0, False, 1, True, 1),
    (10, True, 8, False, 0), (10, False, 8, True, 2),
    (10, False, 1, True, 1), (11, False, 8, False, 0),
    (12, False, 8, False, 0), (None, False, 8, False, 0),
    (-9, False, 8, False, 0), (True, False, 8, False, 0),
])
def test_admission_table(code, heavy, roots, admitted, limit):
    decision = admit(Marker(code, False, None), heavy=heavy, roots=roots)
    assert decision.admitted is admitted
    assert decision.max_roots == limit
    assert admitted or decision.reason
    with pytest.raises(FrozenInstanceError):
        decision.max_roots = 99


@pytest.mark.parametrize("roots", [0, -1, True, 1.5])
def test_invalid_root_count_refused(roots):
    assert not admit(Marker(0, False, None), heavy=False, roots=roots).admitted


def test_exit_11_refuses_before_any_child_starts(tmp_path, monkeypatch):
    marker_command(tmp_path, monkeypatch, 'print(\'{"state":"row"}\'); raise SystemExit(11)')
    assert read_marker() == Marker(11, None, "row")
    assert not admit(read_marker(), heavy=False, roots=1).admitted
    sentinel = tmp_path / "child-started"
    stub = tmp_path / "runner.py"
    stub.write_text(
        "import subprocess, sys\n"
        "from bicentennial.runner.guard import admit, read_marker, refuse_exit\n"
        "refuse_exit(admit(read_marker(), heavy=False, roots=1))\n"
        "subprocess.run([sys.executable, '-c', "
        "\"from pathlib import Path; import sys; Path(sys.argv[1]).touch()\", "
        "sys.argv[1]], check=True)\n"
    )
    result = subprocess.run([sys.executable, str(stub), str(sentinel)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 3
    assert "marker exit 11" in result.stderr
    assert not sentinel.exists()


@pytest.mark.parametrize("body", [
    "print('not json')", "print('[]')", "print('{}'); raise SystemExit(1)",
    "print('{\"glm\":\"false\"}')", "print('{\"state\":1}')", "pass",
    "print('[' * 200000 + ']' * 200000)",
])
def test_unreadable_marker_fails_closed(tmp_path, monkeypatch, body):
    marker_command(tmp_path, monkeypatch, body)
    marker = read_marker()
    assert marker == Marker(None, None, "unreadable")
    assert not admit(marker, heavy=False, roots=1).admitted
    assert glm_paused(marker)


def test_marker_timeout_fails_closed(tmp_path, monkeypatch):
    # The marker would answer idle after the sleep, so only the timeout makes it unreadable.
    marker_command(tmp_path, monkeypatch, "import time; time.sleep(2); print('{\"state\":\"idle\"}')")
    monkeypatch.setattr(guard, "_MARKER_TIMEOUT", 0.05)
    started = time.monotonic()
    marker = read_marker()
    assert time.monotonic() - started < 1.5
    assert marker == Marker(None, None, "unreadable")
    assert not admit(marker, heavy=False, roots=1).admitted
    assert glm_paused(marker)


@pytest.mark.parametrize("code", [0, 10, 11])
def test_valid_marker_and_glm_pause(tmp_path, monkeypatch, code):
    marker_command(tmp_path, monkeypatch,
                   f'print(\'{"{\"state\":\"busy\",\"glm\":true}"}\'); raise SystemExit({code})')
    assert read_marker() == Marker(code, True, "busy")
    assert glm_paused(read_marker())


def test_refuse_exit_allows_admitted_work():
    assert guard.refuse_exit(Admission(True, 1)) is None


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_reexec_command_and_loop_guard(monkeypatch, platform):
    monkeypatch.setattr(guard.sys, "platform", platform)
    monkeypatch.delenv(guard._NICED_FLAG, raising=False)
    monkeypatch.setattr(guard.os, "getpriority", lambda which, who: 0)
    monkeypatch.setattr(guard.shutil, "which", lambda name: name)
    execute = Mock()
    monkeypatch.setattr(guard.os, "execvpe", execute)
    guard.reexec_niced(["-m", "example"])
    name, args, env = execute.call_args.args
    expected = ["nice", "-n", "19"]
    if platform == "darwin":
        expected += ["taskpolicy", "-b"]
    assert name == "nice"
    assert args == [*expected, sys.executable, "-m", "example"]
    assert env[guard._NICED_FLAG] == "1"
    monkeypatch.setenv(guard._NICED_FLAG, "1")
    with pytest.raises(RuntimeError, match="did not establish"):
        guard.reexec_niced(["script.py"])
    assert execute.call_count == 1


@pytest.mark.parametrize("start,increment", [(5, "14"), (19, "0"), (-5, "24")])
def test_reexec_sets_niceness_to_19_not_plus_19(monkeypatch, start, increment):
    monkeypatch.setattr(guard.sys, "platform", "darwin")
    monkeypatch.delenv(guard._NICED_FLAG, raising=False)
    monkeypatch.setattr(guard.os, "getpriority", lambda which, who: 0 if which == 4 else start)
    monkeypatch.setattr(guard.shutil, "which", lambda name: name)
    execute = Mock()
    monkeypatch.setattr(guard.os, "execvpe", execute)
    guard.reexec_niced(["script.py"])
    assert execute.call_args.args[1][:5] == ["nice", "-n", increment, "taskpolicy", "-b"]


def test_niceness_above_19_fails(monkeypatch):
    monkeypatch.setattr(guard.sys, "platform", "darwin")
    monkeypatch.delenv(guard._NICED_FLAG, raising=False)
    monkeypatch.setattr(guard.os, "getpriority", lambda which, who: 0 if which == 4 else 20)
    monkeypatch.setattr(guard.os, "execvpe", Mock())
    with pytest.raises(RuntimeError, match="above 19"):
        guard.reexec_niced(["script.py"])


def test_already_background_and_niced_does_not_reexec(monkeypatch):
    monkeypatch.setattr(guard.sys, "platform", "darwin")
    monkeypatch.setattr(guard.os, "getpriority", lambda which, who: 1 if which == 4 else 19)
    execute = Mock()
    monkeypatch.setattr(guard.os, "execvpe", execute)
    guard.reexec_niced(["script.py"])
    guard.reexec_niced(["script.py"])
    execute.assert_not_called()


@pytest.mark.parametrize("missing", ["nice", "taskpolicy"])
def test_missing_priority_tool_fails(monkeypatch, missing):
    monkeypatch.setattr(guard.sys, "platform", "darwin")
    monkeypatch.delenv(guard._NICED_FLAG, raising=False)
    monkeypatch.setattr(guard.os, "getpriority", lambda which, who: 0)
    monkeypatch.setattr(guard.shutil, "which", lambda name: None if name == missing else name)
    with pytest.raises(RuntimeError, match=f"{missing} is required"):
        guard.reexec_niced(["script.py"])


@pytest.mark.parametrize("start", [0, 5, 19])
def test_real_reexec_and_second_call_no_loop(tmp_path, start):
    if os.getpriority(os.PRIO_PROCESS, 0) != 0 or (
        sys.platform == "darwin" and os.getpriority(4, 0) != 0
    ):
        pytest.skip("the test process is already niced or in the background band")
    if start == 19 and sys.platform != "darwin":
        pytest.skip("niceness 19 is already compliant where there is no QoS band")
    script = tmp_path / "niced.py"
    script.write_text(
        "import json, os, sys\n"
        "from bicentennial.runner.guard import reexec_niced\n"
        "reexec_niced(sys.argv)\n"
        "reexec_niced(sys.argv)\n"
        "print(json.dumps({'niceness': os.getpriority(os.PRIO_PROCESS, 0), "
        "'background': os.getpriority(4, 0) if sys.platform == 'darwin' else None, "
        "'flag': os.environ.get('BICENTENNIAL_NICED')}))\n"
    )
    env = os.environ.copy()
    env.pop(guard._NICED_FLAG, None)
    result = subprocess.run(["nice", "-n", str(start), sys.executable, str(script)], env=env,
                            capture_output=True, text=True, timeout=10)
    if result.returncode and "Operation not permitted" in result.stderr:
        pytest.skip(f"host sandbox denies priority change: {result.stderr.strip()}")
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["niceness"] == 19
    assert observed["flag"] == "1"
    if sys.platform == "darwin":
        assert observed["background"] == 1


@pytest.mark.parametrize("output,ok", [(" 19\n", True), ("10\n", False), ("", False)])
def test_assert_niced_uses_ps(monkeypatch, output, ok):
    run = Mock(return_value=SimpleNamespace(stdout=output))
    monkeypatch.setattr(guard.subprocess, "run", run)
    if ok:
        guard.assert_niced(123)
    else:
        with pytest.raises(AssertionError):
            guard.assert_niced(123)
    assert run.call_args.args[0] == ["ps", "-o", "ni=", "-p", "123"]


def test_assert_niced_propagates_ps_failure(monkeypatch):
    monkeypatch.setattr(guard.subprocess, "run", Mock(side_effect=OSError("denied")))
    with pytest.raises(OSError):
        guard.assert_niced(123)
