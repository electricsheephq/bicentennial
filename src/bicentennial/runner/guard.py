"""Fail-closed machine admission and background execution."""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass

_MARKER_TIMEOUT = 30
_NICED_FLAG = "BICENTENNIAL_NICED"
REFUSED_EXIT = 3


@dataclass(frozen=True)
class Marker:
    exit: int | None
    glm: bool | None
    state: str | None


@dataclass(frozen=True)
class Admission:
    admitted: bool
    max_roots: int
    reason: str | None = None


def read_marker() -> Marker:
    """Read the shell marker; only its documented exit codes are readable."""
    cmd = os.environ.get("BICENTENNIAL_BUSY_CMD")
    if cmd is None:
        return Marker(0, False, "unset")
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=_MARKER_TIMEOUT,
        )
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or result.returncode not in (0, 10, 11):
            raise ValueError("invalid marker")
        glm, state = value.get("glm"), value.get("state")
        if (glm is not None and type(glm) is not bool) or (
            state is not None and not isinstance(state, str)
        ):
            raise ValueError("invalid marker fields")
        return Marker(result.returncode, glm, state)
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return Marker(None, None, "unreadable")


def admit(marker: Marker, *, heavy: bool, roots: int) -> Admission:
    if type(roots) is not int or roots < 1:
        return Admission(False, 0, "positive integer roots required")
    if type(marker.exit) is int and marker.exit == 0:
        return Admission(True, min(roots, 8))
    if type(marker.exit) is int and marker.exit == 10:
        if not heavy:
            return Admission(True, min(roots, 2))
        return Admission(False, 0, "machine busy: heavy work refused")
    return Admission(False, 0, f"machine guard refused: marker exit {marker.exit}")


def glm_paused(marker: Marker) -> bool:
    return marker.glm is True or marker.exit is None or marker.state == "unreadable"


def refuse_exit(admission: Admission) -> None:
    if not admission.admitted:
        print(admission.reason, file=sys.stderr)
        raise SystemExit(REFUSED_EXIT)


def reexec_niced(argv) -> None:
    """argv is the Python argument vector (e.g. sys.argv or ['-m', module])."""
    # getpriority(PRIO_DARWIN_PROCESS) reads 1 in the background band, not PRIO_DARWIN_BG
    background = sys.platform != "darwin" or os.getpriority(4, 0) == 1
    if os.getpriority(os.PRIO_PROCESS, 0) == 19 and background:
        return
    if os.environ.get(_NICED_FLAG):
        raise RuntimeError("background re-exec did not establish niceness 19 and QoS")
    if shutil.which("nice") is None:
        raise RuntimeError("nice is required")
    command = ["nice", "-n", "19"]
    if sys.platform == "darwin":
        if shutil.which("taskpolicy") is None:
            raise RuntimeError("taskpolicy is required on macOS")
        command += ["taskpolicy", "-b"]
    env = dict(os.environ, **{_NICED_FLAG: "1"})
    os.execvpe("nice", [*command, sys.executable, *argv], env)


def assert_niced(pid) -> None:
    result = subprocess.run(
        ["ps", "-o", "ni=", "-p", str(pid)],
        check=True, capture_output=True, text=True,
    )
    if result.stdout.strip() != "19":
        raise AssertionError(f"process {pid} is not at niceness 19")
