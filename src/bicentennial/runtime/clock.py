"""Logical time published at idle turn/session boundaries by the director."""

import json
import os
import tempfile
import time
from pathlib import Path

from bicentennial.canon import canon

MARGIN_S = 3600


class SimClock:
    """One director owns the clock; tick before answering the turn it counts.

    Construction publishes the initial instant. Only call tick/set_session while
    the child is idle. The shim's duration clocks remain on real time.
    """

    def __init__(self, path: str | Path, sim_start_s: int, step_s: int):
        self.path = Path(path)
        self._integer(step_s)
        if step_s <= 0:
            raise ValueError("step_s must be positive")
        self.step_s = step_s
        self._write(sim_start_s)

    @staticmethod
    def _integer(value: int) -> None:
        if type(value) is not int:
            raise TypeError("clock values must be integers")

    def _write(self, sim_t_s: int) -> None:
        self._integer(sim_t_s)
        wall_now = time.time()
        if sim_t_s >= wall_now - MARGIN_S:
            raise ValueError("simulated time must stay behind the wall-time margin")
        data = canon({"sim_start": sim_t_s, "wall_anchor": int(wall_now),
                      "rate": 0, "step_s": self.step_s})
        fd, name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.sim_t_s = sim_t_s

    def tick(self) -> None:
        """Publish one logical step before the director answers its turn."""
        self._write(self.sim_t_s + self.step_s)

    def set_session(self, sim_t_s: int, step_s: int | None = None) -> None:
        """Publish the scheduled instant at an idle session boundary."""
        previous_step_s = self.step_s
        if step_s is not None:
            self._integer(step_s)
            if step_s <= 0:
                raise ValueError("step_s must be positive")
            self.step_s = step_s
        try:
            self._write(sim_t_s)
        except Exception:
            self.step_s = previous_step_s
            raise

    @classmethod
    def resume(cls, path: str | Path, schedule_sim_t_s: int) -> "SimClock":
        """Restore cadence from the file, but time only from the given schedule."""
        step_s = json.loads(Path(path).read_bytes())["step_s"]
        return cls(path, schedule_sim_t_s, step_s)
