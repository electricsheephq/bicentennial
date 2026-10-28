"""Session-end polling follows the newest life and only committed log lines."""

import json
import threading
import time

import pytest

from bicentennial.canon import canon
from bicentennial.harness.hermes.envwire import EnvWiring

END = {"type": "boundary", "kind": "session_end"}
START = {"type": "boundary", "kind": "session_start"}


def wiring_at(tmp_path):
    return EnvWiring(tmp_path, {}, tmp_path / "clock.json")


def log_at(tmp_path, life):
    directory = tmp_path / "env" / "1" / f"life-{life}"
    directory.mkdir(parents=True)
    return directory / "env_actions.jsonl"


def test_wait_end_delayed_append(tmp_path):
    wiring = wiring_at(tmp_path)
    path = log_at(tmp_path, 1)

    def append():
        time.sleep(0.06)
        with path.open("ab") as stream:
            stream.write(canon(START) + b"\n" + canon(END) + b"\n")

    helper = threading.Thread(target=append)
    helper.start()
    try:
        assert wiring.wait_end(1, 1) == [START, END]
    finally:
        helper.join(timeout=2)
    assert not helper.is_alive()


@pytest.mark.parametrize("missing", ["life", "file", "end"])
def test_wait_end_timeout(tmp_path, missing):
    wiring = wiring_at(tmp_path)
    if missing != "life":
        path = log_at(tmp_path, 1)
        if missing == "end":
            path.write_bytes(canon(START) + b"\n")
    started = time.monotonic()
    assert wiring.wait_end(1, 0.06) == ([START] if missing == "end" else [])
    assert 0.05 <= time.monotonic() - started < 1


def test_wait_end_ignores_older_end(tmp_path):
    wiring = wiring_at(tmp_path)
    log_at(tmp_path, 1).write_bytes(canon(END) + b"\n")
    log_at(tmp_path, 2).write_bytes(canon(START) + b"\n")
    started = time.monotonic()
    assert wiring.wait_end(1, 0.06) == [END, START]
    assert 0.05 <= time.monotonic() - started < 1


def test_wait_end_waits_past_an_unterminated_end(tmp_path):
    # Polling counts only newline-terminated rows; the returned records keep records()'s parsing.
    wiring = wiring_at(tmp_path)
    log_at(tmp_path, 1).write_bytes(canon(START) + b"\n" + canon(END))
    started = time.monotonic()
    assert wiring.wait_end(1, 0.06) == [START, END]
    assert 0.05 <= time.monotonic() - started < 1


def test_wait_end_keeps_records_strict_on_a_torn_row(tmp_path):
    wiring = wiring_at(tmp_path)
    log_at(tmp_path, 1).write_bytes(canon(START) + b"\n" + b'{"type":')
    with pytest.raises(json.JSONDecodeError):
        wiring.wait_end(1, 0.06)
