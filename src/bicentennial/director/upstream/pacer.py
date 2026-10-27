"""One in-process token bucket per account, including retry-after deferrals."""
import math
import threading
import time

RATE_PER_MIN, BURST = 180, 10


class Pacer:
    def __init__(self, rate, burst, stop, clock=time.monotonic, sleep=None, allow=False):
        if not math.isfinite(rate) or rate < 0 or not math.isfinite(burst) or burst < 1 or (burst + rate >= 200 and not allow):
            raise ValueError("invalid account pacing")
        self.rate, self.burst, self.stop, self.clock = rate / 60, burst, stop, clock
        self.sleep, self.lock = sleep or stop.wait, threading.Lock()
        self.tokens, self.last, self.not_before = burst, clock(), 0

    def defer(self, seconds: int):
        if type(seconds) is not int or seconds < 0:
            raise ValueError("non-negative integer deferral required")
        with self.lock:
            self.not_before = max(self.not_before, self.clock() + seconds)

    def acquire(self):
        start = self.clock()
        while not self.stop.is_set():
            with self.lock:
                now = self.clock()
                delay = self.not_before - now
                if delay <= 0:
                    self.tokens = min(self.burst, self.tokens + (now - self.last) * self.rate)
                    self.last = now
                    if not self.rate or self.tokens >= 1:
                        self.tokens -= bool(self.rate)
                        return round((now - start) * 1000)
                    delay = max(0.001, (1 - self.tokens) / self.rate)
            self.sleep(delay)
        return None
