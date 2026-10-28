"""One durable environment log per server life; resumes replay committed writes."""

import json
import sys
import time
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.sandbox.envserver.state import State, state_hash

ENV_SERVER = "envserver"


def _rows(life_dirs):
    return [json.loads(line) for directory in life_dirs
            if (path := directory / "env_actions.jsonl").exists() for line in path.read_bytes().splitlines()]


def _ended(life_dirs):
    # Only complete lines count: the server may be mid-write while wait_end polls.
    for directory in life_dirs:
        try:
            raw = (directory / "env_actions.jsonl").read_bytes()
        except FileNotFoundError:
            continue
        if any(row.get("type") == "boundary" and row.get("kind") == "session_end"
               for row in map(json.loads, raw.split(b"\n")[:-1])):
            return True
    return False


def derived_seed(seed, life_dirs):
    state, changed = State(seed), False
    try:
        for row in _rows(life_dirs):
            if row.get("type") == "action" and row["ok"] and row["state_changed"]:
                state.call(row["tool"], row["args"])
                if state_hash(state.state) != row["state_hash"]:
                    raise ValueError("resume refused")
                changed = True
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("resume refused") from error
    return dict(seed, state=state.state) if changed else seed


class EnvWiring:
    def __init__(self, root, seeds, clock_path):
        self.root, self.seeds, self.clock = Path(root).resolve(), seeds, Path(clock_path).resolve()

    def _lives(self, session):
        return sorted((self.root / "env" / str(session)).glob("life-*"), key=lambda p: int(p.name[5:]))

    def __call__(self, session, reason):
        lives = self._lives(session)
        seed = derived_seed(self.seeds[session], lives)
        directory = self.root / "env" / str(session) / f"life-{len(lives) + 1}"
        directory.mkdir(parents=True)
        path = directory / "seed.json"
        with path.open("xb") as stream:
            stream.write(canon(seed))
        # Hermes d923a5e mcp_tool_config.py:203-204,644-647; mcp_tool_transport.py:127,370.
        return {"command": sys.executable, "args": ["-m", "bicentennial.sandbox.envserver", "--seed", str(path),
                "--log-dir", str(directory), "--clock", str(self.clock)],
                "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[3]), "PYTHONHASHSEED": "0"}}

    def records(self, session):
        return _rows(self._lives(session))

    def wait_end(self, session, timeout_s):
        """Wait for the newest server life to finish its durable session receipt."""
        deadline = time.monotonic() + timeout_s
        while True:
            if _ended(self._lives(session)[-1:]):
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.02, remaining))
        return self.records(session)
