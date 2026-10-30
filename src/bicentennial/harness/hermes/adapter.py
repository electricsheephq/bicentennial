"""The Hermes adapter in replay mode (R12). It drives a pinned Hermes through its ACP session path, in process in a
niced worker (the disclosed S6a fallback), against the director on loopback. Faults run at turn boundaries, the R15
gate runs before every spawn, and the director drains at every idle boundary, so the clock steps only there."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from threading import Lock

from bicentennial.director.core import Director
from bicentennial.director.serve import serve, shutdown
from bicentennial.gitenv import git_env
from bicentennial.harness.egress import Egress
from bicentennial.harness.hermes.config import (
    CONFIG_DEVIATIONS,
    SCRIPTED_DEVIATIONS,
    T1_TOOLSETS,
    hermes_config,
    layout,
    validate_paths,
    worker_env,
    write_config,
)
from bicentennial.ledger import BlobStore, Guard, stable_digest
from bicentennial.runner.guard import admit, assert_niced, read_marker
from bicentennial.sandbox.envserver.honeypot import hits
from bicentennial.sandbox.surfaces import surface_hash
from bicentennial.systems.registry import SystemRefused, check

ENTRYPOINT = "acp_adapter.session.SessionManager in process (S6a fallback)"
WORKER = Path(__file__).resolve().with_name("worker.py")
DRAIN_QUIET_S, DRAIN_CAP_S, EXIT_TIMEOUT_S = 3.0, 240.0, 300
STARTUP_TIMEOUT_S, OPEN_TIMEOUT_S, TURN_TIMEOUT_S, END_TIMEOUT_S = 300, 300, 3600, 300


class PinMismatch(RuntimeError):
    """The checkout is not the pinned artifact (RING0 §8: exit code 3)."""


class HarnessFailed(RuntimeError):
    """The session cannot complete as scripted; the message is a stable label."""


class HarnessKilled(Exception):
    """Raised from the director's on_hold hook after a held kill, so the held response is never sent."""


@dataclass(frozen=True)
class SessionResult:
    session: int
    kind: str
    acp_session_id: str
    entrypoint: str
    turns_ok: int
    finals_matched: int
    restarts: tuple  # ({after_turn, kind, mode, history_before, history_after}, ...)
    compaction_expected: bool
    summariser_records: int
    surface_hash: str
    gate: tuple  # ({exit, state}, ...): receipts only
    timings_ms: dict  # volatile
    finals: tuple = ()  # ((turn, text), ...) in turn order: every delivered final; a probe's is never compared
    reset: str | None = None  # "control_wipe" when the wipe hook reported a wipe (Amendment 1, A2)
    active_memory_providers: tuple = ()
    end_threads: tuple | None = None


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _group_survivors(pgid) -> list[int]:
    rows = subprocess.run(["ps", "-A", "-o", "pid=,pgid=,stat="], capture_output=True, text=True, check=True)
    return [int(pid) for pid, group, stat in (line.split() for line in rows.stdout.splitlines())
            if int(group) == pgid and int(pid) != pgid and not stat.startswith("Z")]


def verify_pin(checkout, pin) -> str:
    """pin: the lock's harness artifact {name, version, sha256}, never the system entry's (Amendment 1, A1). Raises
    PinMismatch unless HEAD's archive hashes to it and no tracked file is changed; -> the commit."""
    git, digest = ["git", "-C", str(checkout)], sha256()
    env = git_env()
    with subprocess.Popen([*git, "archive", "--format=tar", "HEAD"], stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, env=env) as proc:
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
            digest.update(chunk)
    if proc.returncode != 0 or digest.hexdigest() != pin["sha256"]:
        raise PinMismatch("the checkout's archive does not hash to the pinned artifact")
    status = subprocess.run([*git, "status", "--porcelain", "--untracked-files=no"],
                            capture_output=True, text=True, env=env)
    if status.returncode != 0 or status.stdout.strip():
        raise PinMismatch("the checkout has tracked changes")
    return subprocess.run([*git, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True, env=env).stdout.strip()


class _Worker:
    def __init__(self, argv, env, cwd, log, egress=None):
        self._buffer, self._reaped, self.egress = b"", False, egress
        self._cleanup_lock = Lock()
        own = os.getpriority(os.PRIO_PROCESS, 0)  # nice -n adds: only the gap to 19 (guard.py 86-91)
        prefix = ["nice", "-n", str(19 - own)] + (["taskpolicy", "-b"] if sys.platform == "darwin" else [])
        with open(log, "ab") as err:
            self.proc = subprocess.Popen([*prefix, *argv], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=err, env=env, cwd=cwd, text=True, encoding="utf-8",
                                         start_new_session=True)
        os.set_blocking(self.proc.stdin.fileno(), False)
        try:
            if self.egress is not None:
                self.egress.add(self.proc.pid, Path(log).name)
            if not (self.call() or {}).get("ready"):
                raise HarnessFailed("worker_start")
        except BaseException:
            self.kill()
            raise

    def call(self, **op):
        """Sends one op (none: just read the ready line); -> its answer, or None at end-of-file."""
        phase = op.get("op", "startup")
        deadline = time.monotonic() + {"startup": STARTUP_TIMEOUT_S, "open": OPEN_TIMEOUT_S,
                                      "turn": TURN_TIMEOUT_S, "end": END_TIMEOUT_S}[phase]
        try:
            if op:
                pending = memoryview((json.dumps(op) + "\n").encode("utf-8"))
                with selectors.DefaultSelector() as writer:
                    writer.register(self.proc.stdin, selectors.EVENT_WRITE)
                    while pending:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not writer.select(remaining):
                            self.kill()
                            raise HarnessFailed(f"{phase}_timeout")
                        try:
                            pending = pending[os.write(self.proc.stdin.fileno(), pending[:65536]):]
                        except BlockingIOError:
                            continue
            with selectors.DefaultSelector() as reader:
                reader.register(self.proc.stdout, selectors.EVENT_READ)
                while b"\n" not in self._buffer:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not reader.select(remaining):
                        self.kill()
                        raise HarnessFailed(f"{phase}_timeout")
                    chunk = os.read(self.proc.stdout.fileno(), 65536)
                    if not chunk:
                        return None
                    self._buffer += chunk
            line, self._buffer = self._buffer.split(b"\n", 1)
        except OSError:
            return None
        return json.loads(line) if line else None

    def kill(self, *, clean=False):
        with self._cleanup_lock:
            self._cleanup(clean)

    def _cleanup(self, clean):
        if self._reaped:
            return
        if self.proc.returncode is None:  # an interrupted Popen.wait may already have reaped the leader
            if clean:
                deadline = time.monotonic() + EXIT_TIMEOUT_S
                # Keep the exited leader waitable: its pid must still reserve the pgid until killpg.
                while os.waitid(os.P_PID, self.proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is None:
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(self.proc.args, EXIT_TIMEOUT_S)
                    time.sleep(0.01)
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)  # includes children even after the leader exits
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin returns EPERM for a group containing only its exited, unreaped leader.
                if os.waitid(os.P_PID, self.proc.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG) is None:
                    raise
                survivors = _group_survivors(self.proc.pid)
                if survivors:
                    raise HarnessFailed("group_survivors:" + ",".join(map(str, sorted(survivors)))) from None
            self.proc.wait()
        self._reaped = True
        if self.egress is not None:
            self.egress.discard(self.proc.pid)


class HermesAdapter:
    def __init__(self, entry, *, script, route_table, schedule, responder, clock, root, scratch, life, branch, run,
                 checkout=None, plugin=None, kill_mode="boundary", worker_argv=None, gate_poll_s=60,
                 before_spawn=None, write_prompt=None, harness_pin=None, plugin_config: dict | None = None,
                 memory: bool = True, before_shutdown=None, toolsets=None, env_server=None, window=None,
                 context_engine=None, plugins_enabled=(), extra_env=None, scripted: bool = True,
                 admission_deadline: float | None = None):
        self.before_shutdown = before_shutdown
        reasons = ([] if entry.get("harness") == "hermes" else ["harness_not_hermes"]) + check(entry)
        if entry.get("benchmark_operator_runs") is False and os.environ.get("BICENTENNIAL_OPERATOR") == "benchmark":
            reasons.append("benchmark_operator_forbidden")
        if reasons:
            raise SystemRefused(reasons)
        if kill_mode not in ("boundary", "held"):
            raise ValueError("kill_mode is boundary or held")
        if any(f["kind"] in ("restart", "kill", "compaction") and f["turn"] is None for f in schedule.to_obj()):
            raise ValueError("a restart, kill or compaction needs a turn")
        self.toolsets, self.env_server = T1_TOOLSETS if toolsets is None else toolsets, env_server
        # The scripted tier's config (#191, #192: config.SCRIPTED_DEVIATIONS); a live tier passes False for the pin's defaults.
        hermes_config(1, "bicentennial-main", plugin=plugin, plugin_config=plugin_config, memory=memory,
                      toolsets=self.toolsets, window=window, context_engine=context_engine, plugins_enabled=plugins_enabled,
                      scripted=scripted)
        self.context_engine, self.plugins_enabled, self.extra_env = context_engine, plugins_enabled, extra_env
        self.active_context_engine = None
        self.memory, self.window, self.scripted = memory, window, scripted
        self.plugin_config, self.active_memory_providers = deepcopy(plugin_config or {}), []
        checkout = Path(checkout).resolve() if checkout is not None else None
        self.commit = None
        if worker_argv is None:
            if checkout is None or harness_pin is None:
                raise ValueError("a pinned checkout and its harness pin are required")
            self.commit = verify_pin(checkout, harness_pin)
            worker_argv = [str(Path(checkout) / ".venv" / "bin" / "python"), str(WORKER)]
        self.entry, self.script, self.schedule, self.clock = entry, script, schedule, clock
        self.checkout, self.plugin, self.kill_mode, self.argv = checkout, plugin, kill_mode, list(worker_argv)
        self.gate_poll_s, self.before_spawn, self.harness_pin = gate_poll_s, before_spawn, harness_pin or {}
        self.admission_deadline = admission_deadline  # absolute time.monotonic(), or an unbounded admission wait
        self.entrypoint = ENTRYPOINT if self.commit is not None else "test-double"
        self.volatile = next(s["volatile_paths"] for s in entry["surfaces"] if s["root"] == "HERMES_HOME")
        self.paths = layout(root, scratch)
        self.pids, self._worker, self._held, self._fired = [], None, None, set()
        self.end_threads = None
        self.director = Director(script, route_table, entry["name"], life, branch, run,
                                 tuple(t["tool"] for t in entry["write_tools"]), responder, clock, Guard([]),
                                 {"sandbox_root": str(self.paths["root"]), "director_port": "0"}, write_prompt,
                                 self._on_hold, schedule=schedule)
        self.server = serve(self.director, 0)  # serve binds the port into the run values (R08 D2)
        if self.director.run_values["director_port"] != str(self.server.port):
            raise RuntimeError("the director's port mask is not the bound port")
        self.egress = Egress()
        self.egress.start()

    def run_session(self, index, *, sim_t_s, lock_hash, attempt_id, resume_session_id=None) -> SessionResult:
        self._session_index = index
        session, d = next(s for s in self.script["sessions"] if s["index"] == index), self.director
        gate, restarts, finals, compaction, self._wiped = [], [], [], False, False
        self.end_threads = None
        t = {"spawn": [], "open": [], "turn": [], "drain": [], "resume": []}
        failures = None
        try:
            self._gate(gate)
            with self.egress.forking:  # no sampler fork may hold the ledger's flock while it is reopened
                d.start_session(index, sim_t_s, lock_hash, attempt_id, self.paths["root"] / "ledger")
            self._alias = d.route["alias"]  # a swap reaches Hermes's config at session start (RING0 §6)
            sid, history, _ = self._spawn_open("session_start", resume_session_id, t)
            failures, turns_ok, matched = d.control()["write_failures"], 0, 0
            for turn in session["turns"]:
                n, faults = turn["n"], self.schedule.at(index, turn["n"])
                held = self.kill_mode == "held" and any(f["kind"] == "kill" for f in faults)
                self._held, t0 = (index, n) if held else None, time.monotonic()
                out = self._worker.call(op="turn", text=turn["user"])
                t["turn"].append(_ms(t0))
                t["drain"].append(self._drain())
                c, killed, self._held = d.control(), held and out is None and (index, n) in self._fired, None
                if c["stopped"] or c["write_failures"] > failures:
                    raise HarnessFailed("director_stopped" if c["stopped"] else "write_failure")
                if not killed:  # a held-killed turn is not delivered
                    if out is None or not out.get("ok"):
                        raise HarnessFailed("turn_failed")
                    if session["kind"] == "replay" and out["final"].strip() != turn["assistant"].strip():
                        raise HarnessFailed("final_mismatch")
                    finals.append((n, out["final"]))
                    matched += session["kind"] == "replay"
                    turns_ok, history = turns_ok + 1, out["history"]
                for f in faults:
                    compaction |= f["kind"] == "compaction"
                    if f["kind"] not in ("kill", "restart"):
                        continue  # compaction is observed, not forced; a swap acts through the route
                    if held and not killed:
                        raise HarnessFailed("held_kill_missed")
                    self._worker.kill() if f["kind"] == "kill" else self._end()  # restart: a clean end
                    t0, mode = time.monotonic(), "clean" if f["kind"] == "restart" else self.kill_mode
                    self._gate(gate)
                    new_sid, after, wiped = self._spawn_open(f["kind"], sid, t)
                    if wiped:  # a control wipe on this wake: a fresh session, no history check (A2)
                        sid = new_sid
                    elif not (after >= history if mode == "held" else after == history):
                        raise HarnessFailed("resume_failed")
                    restarts.append({"after_turn": n, "kind": f["kind"], "mode": mode, "history_before": history,
                                     "history_after": after})
                    history = after
                    t["resume"].append(_ms(t0))
            t["drain"].append(self._drain())
            if self.before_shutdown is not None:
                self.before_shutdown()
            t0 = time.monotonic()
            end_threads = self._end()
            self.end_threads = end_threads
            c = d.control()
            if c["stopped"] or c["write_failures"] > failures:
                raise HarnessFailed("director_stopped" if c["stopped"] else "write_failure")
            t["close"] = _ms(t0)
        except BaseException as error:
            if self._worker is not None:
                self._worker.kill()
            if isinstance(error, HarnessFailed) and str(error) in (
                    "turn_timeout", "end_timeout", "exit_timeout") and failures is not None:
                c = d.control()
                if c["stopped"]:
                    raise HarnessFailed("director_stopped") from error
                if c["write_failures"] > failures:
                    raise HarnessFailed("write_failure") from error
                if c["inflight"] > 0:
                    raise HarnessFailed("director_inflight") from error
            raise
        finally:
            self._held = None
        from bicentennial.systems.hermes_plugin import checkpoint_sqlite
        roots = {"HERMES_HOME": self.paths["hermes_home"], "SANDBOX_HOME": self.paths["home"]}
        checkpoint_sqlite(roots[s["root"]] / s["relative"] for s in self.entry["surfaces"])
        summarised = sum(r.get("role") == "summariser" and r.get("attempt_id") == attempt_id for r in self.records())
        return SessionResult(index, session["kind"], sid, self.entrypoint, turns_ok, matched, tuple(restarts),
                             compaction, summarised, surface_hash(self.paths["hermes_home"], self.volatile),
                             tuple(gate), t, tuple(finals), "control_wipe" if self._wiped else None,
                             tuple(self.active_memory_providers), end_threads)

    def _gate(self, readings) -> None:
        """R15, before every spawn: wait while the busy marker refuses this machine class."""
        deadline = getattr(self, "admission_deadline", None)  # also supports fakes that bind _gate without __init__
        while True:
            marker = read_marker()
            readings.append({"exit": marker.exit, "state": marker.state})
            if deadline is not None and time.monotonic() >= deadline:
                raise HarnessFailed("admission_deadline")
            if admit(marker, heavy=self.entry["machine_class"] == "heavy", roots=1).admitted:
                return
            if deadline is None:
                time.sleep(self.gate_poll_s)
            else:
                time.sleep(max(0, min(self.gate_poll_s, deadline - time.monotonic())))

    def _spawn_open(self, reason, sid, t) -> tuple[str, int, bool]:
        """before_spawn, a niced worker, then open: a new session (sid None) or a resume by id."""
        wiped = self.before_spawn is not None and self.before_spawn(reason) is True  # S10's hook reports a wipe
        self._wiped |= wiped
        sid = None if wiped else sid
        validate_paths(self.paths)  # hooks may replace directories on any wake; check before writing or spawning
        # After the hook, so a wipe that restores install-time state is always followed by the current config
        from bicentennial.harness.hermes.envwire import ENV_SERVER
        servers = {ENV_SERVER: self.env_server(self._session_index, reason)} if self.env_server is not None else None
        toolsets = self.toolsets + ((ENV_SERVER,) if servers and ENV_SERVER not in self.toolsets else ())
        write_config(self.paths["hermes_home"], hermes_config(self.server.port, self._alias, plugin=self.plugin,
                                                            plugin_config=self.plugin_config, memory=self.memory,
                                                            toolsets=toolsets, mcp_servers=servers, window=self.window,
                                                            context_engine=self.context_engine,
                                                            plugins_enabled=self.plugins_enabled,
                                                            scripted=self.scripted))
        t0 = time.monotonic()
        env = worker_env(self.paths, self.server.port, self.clock.path, self.checkout, self.extra_env)
        self._worker = _Worker(self.argv, env, str(self.paths["workspace"]),
                               self.paths["logs"] / f"worker-{len(self.pids) + 1}.stderr", self.egress)
        self.pids.append(self._worker.proc.pid)  # recorded before the check, as the memory host does
        assert_niced(self.pids[-1])
        t["spawn"].append(_ms(t0))
        t0 = time.monotonic()
        out = self._worker.call(op="open", session_id=sid, cwd=str(self.paths["workspace"]))
        if out is None or not out.get("ok") or (sid is not None and out.get("session_id") != sid):
            raise HarnessFailed("open_failed" if sid is None else "resume_failed")
        self.active_memory_providers = list(out.get("active_memory_providers") or [])
        if self.plugin is not None and self.plugin not in self.active_memory_providers:
            raise HarnessFailed("plugin_inactive")
        self.active_context_engine = out.get("active_context_engine")
        if self.context_engine is not None and self.active_context_engine != self.context_engine:
            raise HarnessFailed("engine_inactive")
        t["open"].append(_ms(t0))
        return out["session_id"], out["history"], wiped

    def _end(self) -> tuple | None:
        out = self._worker.call(op="end")
        try:
            self._worker.kill(clean=True)  # observe exit, signal remaining group members, then reap
        except subprocess.TimeoutExpired:
            self._worker.kill()
            raise HarnessFailed("exit_timeout") from None
        if out is None or not out.get("ok"):
            raise HarnessFailed("end_failed")
        return tuple(sorted(out["alive_threads"])) if "alive_threads" in out else None

    def _drain(self) -> int:
        """Wait for DRAIN_QUIET_S with nothing in flight (background titles and reviews), as replay.py 169-180."""
        t0, calm = time.monotonic(), None
        while time.monotonic() - t0 < DRAIN_CAP_S:
            if self.director.control()["inflight"] == 0:
                calm = calm or time.monotonic()
                if time.monotonic() - calm >= DRAIN_QUIET_S:
                    return _ms(t0)
            else:
                calm = None
            time.sleep(min(0.5, DRAIN_QUIET_S / 4))
        raise HarnessFailed("drain_timeout")

    def _on_hold(self, cursor) -> None:
        """The director's hook before a scripted answer is sent: a held kill fires here, once."""
        key = cursor and (cursor["session"], cursor["turn"])
        if key is not None and key == self._held and key not in self._fired:
            self._fired.add(key)
            self._worker.kill()
            raise HarnessKilled(f"held kill at {key}")

    def records(self) -> list[dict]:
        path = self.paths["root"] / "ledger" / "ledger.jsonl"
        return [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []

    def stable_digest(self) -> str:
        return stable_digest(self.records(), self.director.run_values)

    def honeypot_hits(self, token: str) -> int:
        store = BlobStore(self.paths["root"] / "ledger" / "blobs", Guard([]))
        return hits(token, [store.get(r["req"]).decode() for r in self.records() if r.get("type") == "request"])

    def harness_record(self) -> dict:
        pin = self.harness_pin  # the harness's own pin, never a plug-in system's artifact (A1)
        return {"name": pin.get("name"), "version": pin.get("version"), "sha256": pin.get("sha256"),
                "commit": self.commit, "entrypoint": self.entrypoint, "config_deviations": list(CONFIG_DEVIATIONS) + (list(SCRIPTED_DEVIATIONS) if self.scripted else []),
                "plugin_config": deepcopy(self.plugin_config), "memory": self.memory,
                "active_memory_providers": list(self.active_memory_providers),
                **({"active_context_engine": self.active_context_engine} if self.active_context_engine is not None else {})}

    def close(self) -> dict:
        if self._worker is not None:
            self._worker.kill()
        shutdown(self.server)
        self.director.close()
        self.egress.stop()
        return self.egress.summary()
