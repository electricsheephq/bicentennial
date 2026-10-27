"""Session request holds; boundary receipts are separate from request latency."""
import threading
import time

from bicentennial.runner.guard import glm_paused, read_marker


class Holds:
    def __init__(self, *, marker=read_marker, clock=time.monotonic, sleep=None, poll_s=60, rate_hold_s=60, max_hold_s=7200):
        if poll_s <= 0 or rate_hold_s < 0 or max_hold_s < 0:
            raise ValueError("invalid hold interval")
        self.marker, self.clock, self.sleep = marker, clock, sleep
        self.poll_s, self.rate_hold_s, self.max_hold_s = poll_s, rate_hold_s, max_hold_s
        self.lock, self.active, self.receipts = threading.Lock(), {}, {}
        self.marker_at, self.paused = None, True

    def hold(self, run_key, reason):
        if reason not in ("glm", "quota", "rate"):
            raise ValueError("invalid hold reason")
        with self.lock:
            self.active.setdefault(run_key, {})[reason] = self.clock()

    def release(self, run_key):
        with self.lock:
            self.active.pop(run_key, None)

    def at_boundary(self, run_key):
        with self.lock:
            reasons, held = self.receipts.pop(run_key, (set(), 0))
            return {"reasons": sorted(reasons), "held_ms": held}

    def wait(self, run_key, *, glm_plan, stop):
        return self._wait(run_key, glm_plan=glm_plan, stop=stop, max_hold_s=self.max_hold_s)[0]

    def _wait(self, run_key, *, glm_plan, stop, max_hold_s):
        start, reasons = self.clock(), set()
        try:
            while not stop.is_set():
                with self.lock:
                    now = self.clock()
                    active = self.active.setdefault(run_key, {})
                    if glm_plan and (self.marker_at is None or now - self.marker_at >= self.poll_s):
                        try:
                            self.paused = glm_paused(self.marker())
                        except Exception:
                            self.paused = True
                        self.marker_at = now
                    if glm_plan and self.paused:
                        active.setdefault("glm", now)
                    else:
                        active.pop("glm", None)
                    if "rate" in active and now - active["rate"] >= self.rate_hold_s:
                        del active["rate"]
                    if not active:
                        return round((now - start) * 1000), reasons
                    reasons.update(active)
                    remaining = max_hold_s - (now - start)
                    if remaining <= 0:
                        return None, reasons
                    delay = min(self.poll_s, remaining)
                    if "rate" in active:
                        delay = min(delay, self.rate_hold_s - (now - active["rate"]))
                (self.sleep or stop.wait)(delay)
            return None, reasons
        finally:
            with self.lock:
                prior, held = self.receipts.get(run_key, (set(), 0))
                self.receipts[run_key] = (prior | reasons, held + round((self.clock() - start) * 1000))
