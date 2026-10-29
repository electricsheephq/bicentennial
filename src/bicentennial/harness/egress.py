"""Socket and memory sampler for harness worker processes (S6a replay.py Egress, promoted). Once a second it lists
every registered pid, its process group and descendants, reads sockets with lsof and resident memory with ps, and keeps
every endpoint that is not loopback. A wildcard bind (lsof's `*`) counts as non-loopback."""

import subprocess
import threading
from pathlib import Path

LOOPBACK = frozenset(("127.0.0.1", "[::1]", "localhost"))


def hosts(name: str) -> list[str]:
    """The hosts in one lsof NAME field: `a:p`, or `a:p->b:q` for a connection."""
    return [part.rsplit(":", 1)[0] for part in name.replace("->", " ").split()]


def lsof_names(stdout: str) -> list[str]:
    """The NAME field of each lsof row after the header; a trailing `(STATE)` column is skipped."""
    rows = [line.split() for line in stdout.splitlines()[1:] if line.strip()]
    return [row[-2] if row[-1].endswith(")") else row[-1] for row in rows]


def loopback(name: str) -> bool:
    return bool(hosts(name)) and all(h in LOOPBACK for h in hosts(name))


def _out(argv) -> str:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout


class Egress(threading.Thread):
    def __init__(self, interval_s: float = 1.0):
        super().__init__(name="egress", daemon=True)
        self.interval_s, self.pids, self.per_pid, self.seen = interval_s, set(), {}, set()
        self.samples = self.rss_peak_kib = 0
        self.commands, self.non_loopback_seen = {}, {}
        self._lock, self._halt = threading.Lock(), threading.Event()
        # Held while sampling: a forked child keeps the parent's open files, and their flocks, until it execs, so
        # the adapter holds this while the director reopens its ledger
        self.forking = threading.Lock()

    def add(self, pid: int) -> None:
        with self._lock:
            self.pids.add(pid)

    def discard(self, pid: int) -> None:
        with self._lock:
            self.pids.discard(pid)

    def sample(self) -> None:
        with self._lock:
            tree, todo = set(self.pids), list(self.pids)
        children = {}
        for row in (line.split() for line in _out(["ps", "-A", "-o", "pid=,ppid=,pgid="]).splitlines()):
            if len(row) == 3 and all(c.isdigit() for c in row):
                children.setdefault(int(row[1]), []).append(int(row[0]))
                if int(row[2]) in tree:  # a worker's orphaned child keeps its process group
                    todo.append(int(row[0]))
        tree.update(todo)
        while todo:  # the registered pids and all their descendants
            new = [c for c in children.get(todo.pop(), []) if c not in tree]
            tree.update(new)
            todo += new
        sampled = set()
        for pid in sorted(tree):
            rss = _out(["ps", "-o", "rss=", "-p", str(pid)]).strip()
            if not rss.isdigit():
                continue  # exited: not a sample
            names = lsof_names(_out(["lsof", "-a", "-i", "-P", "-n", "-p", str(pid)]))
            non_loopback = {n for n in names if not loopback(n)}
            if non_loopback and pid not in self.commands:
                self.commands[pid] = Path(_out(["ps", "-o", "comm=", "-p", str(pid)]).strip()).name
            with self._lock:
                self.samples, self.rss_peak_kib = self.samples + 1, max(self.rss_peak_kib, int(rss))
                self.per_pid[str(pid)] = self.per_pid.get(str(pid), 0) + 1
                self.seen.update(n for n in names if not loopback(n))
                for name in non_loopback - sampled:
                    first, comm, count = self.non_loopback_seen.get(name, (pid, self.commands[pid], 0))
                    self.non_loopback_seen[name] = (first, comm, count + 1)
                sampled.update(non_loopback)

    def run(self) -> None:
        while not self._halt.is_set():
            try:
                with self.forking:
                    self.sample()
            except (OSError, subprocess.SubprocessError):
                pass  # lsof absent or stuck: no sample is counted, so an unsampled pid stays visible
            self._halt.wait(self.interval_s)

    def stop(self) -> None:
        self._halt.set()
        if self.is_alive():
            self.join()

    def summary(self) -> dict:
        with self._lock:
            return {"samples": self.samples, "per_pid_samples": dict(self.per_pid),
                    "non_loopback": sorted(self.seen), "rss_peak_kib": self.rss_peak_kib,
                    "non_loopback_seen": sorted(f"egress name={n} pid={pid} comm={comm} samples={count}"
                        for n, (pid, comm, count) in self.non_loopback_seen.items())}
