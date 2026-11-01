"""Memory-layer host with Hermes native's frozen session-start memory snapshot.

Token statistics are estimates. Each event is one user turn with an empty
assistant side. The native snapshot is rendered by Hermes at session open;
other prompt injection belongs to replay. Only decoded recall quotes become
event citations.
"""

import json
import os
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path

from bicentennial.api.contract import (
    Adapter,
    answer,
    event_copy,
    integer,
    shape,
    task_ids,
)
from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.director.core import Director
from bicentennial.director.scripted import WRITE_ARGS
from bicentennial.director.serve import serve, shutdown
from bicentennial.harness.egress import Egress
from bicentennial.harness.hermes.adapter import HarnessFailed, _Worker, verify_pin
from bicentennial.harness.hermes.config import (
    hermes_config,
    layout,
    validate_paths,
    worker_env,
    write_config,
)
from bicentennial.items.protocol import CANARY
from bicentennial.ledger import Guard
from bicentennial.probe.argtemplate import recall_call
from bicentennial.runner.guard import admit, assert_niced, read_marker
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.surfaces import (
    clone_tree,
    install_hash,
    surface_hash,
    verify_empty,
    wipe_to_fresh,
)
from bicentennial.systems.hermes_plugin import (
    ENABLED,
    MARKER,
    MEM0_THREADS,
    OMEGA_THREADS,
    PROVIDERS,
    PluginCell,
    plugin_dir,
)
from bicentennial.systems.registry import SystemRefused, check
from bicentennial.systems.settle import settle
from bicentennial.world.tokens import estimate_tokens

ENTRYPOINT = "in-process memory host: MemoryManager or memory tool + SessionDB (T0)"
WORKER = Path(__file__).resolve().with_name("plugin_host_worker.py")
CHECKPOINT_FORMAT, SESSION_PREFIX = "bicentennial-t0-host-1", "bicentennial-t0-s"
SETTLE_THREADS = {"mem0-oss": MEM0_THREADS, "omega": OMEGA_THREADS}
FORGET = {
    "hermes-native": (None, {}, "", "", "", "", "memory", {"action": "remove", "target": "memory"}, "old_text"),
    "holographic": ("fact_store", {"action": "search"}, "query", "results", "content", "fact_id",
                    "fact_store", {"action": "remove"}, "fact_id"),
    "mem0-oss": ("mem0_search", {}, "query", "results", "memory", "id", "mem0_delete", {}, "memory_id"),
    "omega": ("omega_query", {}, "query", "results", "content", "id", "omega_delete", {}, "memory_id"),
}


class GateRefused(RuntimeError):
    """The machine gate refused a worker spawn."""


def _entries(raw):
    def leaves(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, (list, dict)):
            for child in value.values() if isinstance(value, dict) else value:
                yield from leaves(child)
    try:
        return list(leaves(json.loads(raw)))
    except ValueError:
        return [raw]


def _corpus(raw):
    return "\n".join(_entries(raw))


def _schedule(script, index):
    sessions = [{"index": i, "kind": "replay", "turns": []} for i in range(1, index + 1)]
    return FaultLite.load([], dict(script, sessions=sessions))


def _fields(limit):
    return {"actor": "not_delivered", "text": "full" if limit is None else f"clipped:{limit}",
            "time": "session_clock"}


class HermesMemoryHost(Adapter):
    UNSUPPORTED_FIELDS = frozenset({"actor"})

    def __init__(self, entry, *, route_table, responder, clock, root, scratch, life, branch, run,
                 lock_hash, checkout=None, harness_pin=None, worker_argv=None, plugin_source=None,
                 sim_epoch_s=1_600_000_000, extra_env=None):
        reasons = ([] if entry.get("harness") == "hermes" else ["harness_not_hermes"]) + check(entry)
        if entry.get("benchmark_operator_runs") is False and os.environ.get("BICENTENNIAL_OPERATOR") == "benchmark":
            reasons.append("benchmark_operator_forbidden")
        if reasons:
            raise SystemRefused(reasons)
        self.extra_env = extra_env
        self.active_context_engine = None
        self.name = entry["name"]
        if self.name not in WRITE_ARGS or self.name not in FORGET:
            raise ValueError("no T0 mapping")
        self.checkout = Path(checkout).resolve() if checkout is not None else None
        self.commit, self.harness_pin = None, harness_pin or {}
        if worker_argv is None:
            if self.checkout is None or harness_pin is None:
                raise ValueError("a pinned checkout and its harness pin are required")
            self.commit = verify_pin(self.checkout, harness_pin)
            worker_argv = [str(self.checkout / ".venv/bin/python"), str(WORKER)]
        self.entry, self.argv, self.clock = entry, list(worker_argv), clock
        self.lock_hash, self.sim_epoch_s = lock_hash, sim_epoch_s
        self.paths = layout(root, scratch)
        self._worker, self.pids, self.gate, self.active_memory_providers = None, [], [], []
        self.events, self.session, self.turn, self.latency_ms = {}, 1, 0, 0
        self.forget_kept, self.forget_kept_texts, self._store_generation = {}, {}, 0
        self.write_clipped, self.write_max_length = 0, None
        self.settled, self._blocks, self._cache = True, (), None
        self.script = script = dict(canary=CANARY, life_id=life, genre="t0", harness="hermes", sessions=[])
        self.director = Director(script, route_table, self.name, life, branch, run,
                                 tuple(t["tool"] for t in entry["write_tools"]), responder, clock, Guard([]),
                                 {"sandbox_root": str(self.paths["root"]), "director_port": "0"},
                                 schedule=_schedule(script, 1))
        self.server = serve(self.director, 0)
        try:
            assert self.director.run_values["director_port"] == str(self.server.port)
            self.director.start_session(1, clock.sim_t_s, lock_hash, "t0-s1", self.paths["root"] / "ledger")
            for surface in entry["surfaces"]:
                directory = self.paths["home"] / surface["relative"]
                if (surface["root"] == "SANDBOX_HOME" and directory.exists()
                        and any(p.name != MARKER for p in directory.iterdir())):
                    raise SystemRefused(["surface_not_empty"])
            if self.name in PROVIDERS:
                if plugin_source is None:
                    raise ValueError("plugin_source required")
                PluginCell(entry, self).install(plugin_source, alias=self.director.route["alias"], context=False)
            else:
                if plugin_source is not None:
                    raise ValueError("unexpected plugin_source")
                self._config()
            self._surfaces, self._fresh, hashes = [], [], []
            for i, surface in enumerate(entry["surfaces"]):
                base = self.paths[{"HERMES_HOME": "hermes_home", "SANDBOX_HOME": "home"}[surface["root"]]]
                directory = (base / surface["relative"]).resolve()
                if not directory.is_relative_to(base.resolve()):
                    raise ValueError("surface escapes its root")
                directory.mkdir(parents=True, exist_ok=True)
                (directory / MARKER).touch(exist_ok=True)
                fresh = self.paths["root"] / "t0-fresh" / str(i)
                fresh.parent.mkdir(exist_ok=True)
                clone_tree(directory, fresh)
                digest = surface_hash(directory, surface["volatile_paths"])
                self._surfaces.append((directory, surface["volatile_paths"]))
                self._fresh.append((fresh, digest, self._listing(i)))
                hashes.append({"relative": surface["relative"], "root": surface["root"],
                               "tree_hash": install_hash(directory, surface["volatile_paths"], self.server.port)})
            self.fresh_install_hash = hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()
            self.egress = Egress()
            self.egress.start()
        except BaseException:
            shutdown(self.server)
            self.director.close()
            raise

    def _config(self):
        write_config(self.paths["hermes_home"], hermes_config(self.server.port, self.director.route["alias"],
                                                           plugin=PROVIDERS.get(self.name),
            plugins_enabled=(plugin_dir(self.name),) if self.name in ENABLED else ()))

    def _start(self):
        if self._worker is not None:
            return
        marker = read_marker()
        self.gate.append({"exit": marker.exit, "state": marker.state})
        if not admit(marker, heavy=self.entry["machine_class"] == "heavy", roots=1).admitted:
            raise GateRefused("machine guard refused")
        validate_paths(self.paths)
        self._config()
        self._worker = _Worker(self.argv, worker_env(self.paths, self.server.port, self.clock.path, self.checkout, self.extra_env),
                               str(self.paths["workspace"]), self.paths["logs"] / f"host-{len(self.pids) + 1}.stderr",
                               self.egress)
        self.pids.append(self._worker.proc.pid)
        assert_niced(self.pids[-1])
        out = self._worker.call(op="open", session_id=SESSION_PREFIX + str(self.session),
                                provider=PROVIDERS.get(self.name, "")) or {}
        self.latency_ms += out.get("t_ms", 0)
        self.active_memory_providers = out.get("active_memory_providers", [])
        if self.name in PROVIDERS and PROVIDERS[self.name] not in self.active_memory_providers:
            raise HarnessFailed("plugin_inactive")
        if not out.get("ok"):
            raise HarnessFailed("open_failed")
        self.schemas = out["schemas"]
        tool, _, key = WRITE_ARGS[self.name]
        schema = next((s for s in self.schemas if s["name"] == tool), {})
        self.write_max_length = schema.get("parameters", {}).get("properties", {}).get(key, {}).get("maxLength")

    def _call(self, call, **args):
        self._start()
        out = self._worker.call(op="turn", call=call, **args)
        if out is None or not out.get("ok"):
            raise HarnessFailed(f"{call}_failed")
        self.latency_ms += out.get("t_ms", 0)
        return out

    def _stop(self):
        if self._worker is None:
            return
        worker, self._worker = self._worker, None
        try:
            out = worker.call(op="end")
            worker.kill(clean=True)
            if out is None or not out.get("ok"):
                raise HarnessFailed("end_failed")
            self.latency_ms += out.get("t_ms", 0)
        except subprocess.TimeoutExpired:
            worker.kill()
            raise HarnessFailed("exit_timeout") from None
        except BaseException:
            worker.kill()
            raise

    def ingest(self, event):
        self._cache = None
        e = event_copy(event)
        previous = self.events.get(e["event_id"])
        if previous is not None:
            if previous["event"] != e:
                raise ValueError("conflicting event_id")
            return
        if e["kind"] == "tool_result":
            call = self.events.get(e["call_id"], {}).get("event", {})
            if call.get("kind") != "tool_call" or call["t_sim"] > e["t_sim"]:
                raise ValueError("tool_result requires an earlier tool_call")
        written = e["text"]
        if e["text"]:
            self.clock.set_session(self.sim_epoch_s + e["t_sim"])
            self._start()
            tool, fixed, key = WRITE_ARGS[self.name]
            schema = next((s for s in self.schemas if s["name"] == tool), {})
            limit = schema.get("parameters", {}).get("properties", {}).get(key, {}).get("maxLength")
            self.write_max_length = limit
            written = e["text"][:limit]
            self.turn += 1
            self._call("ingest", n=self.turn, text=e["text"], write={"name": tool, "arguments": {
                **fixed, key: written}})
            self.settled = False
        self.write_clipped += int(written != e["text"])
        self.events[e["event_id"]] = {"event": e, "session": self.session, "written": written}

    def fields(self):
        return _fields(self.write_max_length)

    def query(self, task, now):
        task_ids(task, now)
        key, cached = canon([task, now]), self._cache
        self._cache = None
        if cached is not None and cached[0] == key:
            return json.loads(cached[1])
        if not self.settled:
            raise RuntimeError("query before settle")
        call = recall_call(self.entry, task["prompt"])
        self._blocks = ()
        if call is None:
            return answer([])
        self.clock.set_session(self.sim_epoch_s + now)
        out = self._call("query", text=task["prompt"], recall={"name": call["name"],
                                                            "arguments": json.loads(call["arguments"])})
        self.settled = False
        entries, pre = _entries(out["recall"]), out["prefetch"]
        snap = out.get("snapshot", "")
        corpus = "\n".join(entries)
        self._blocks = tuple(t for t in (snap, corpus, pre) if t)
        cited = {}
        for entry in entries:
            matches = [dict(r["event"], text=r.get("written", r["event"]["text"]))
                       for r in self.events.values() if r.get("written", r["event"]["text"])
                       and r["event"]["t_sim"] <= now and r.get("written", r["event"]["text"]) in entry]
            cited.update((e["event_id"], e) for e in matches if not any(
                e["text"] != other["text"] and e["text"] in other["text"] for other in matches))
        return answer(sorted(cited.values(), key=lambda e: (corpus.find(e["text"]), -e["t_sim"], e["event_id"])))

    def probe(self, task, now):
        result = self.query(task, now)
        self._cache = canon([task, now]), canon(result)
        return self.context_blocks()

    def context_blocks(self):
        return self._blocks

    def _listing(self, i):
        directory, volatile = self._surfaces[i]
        rows = tree_listing(directory, volatile)
        if any(r["kind"] == "symlink" for r in rows):
            raise ValueError("symlink in surface")
        return {r["path"]: r for r in rows if not Path(r["path"]).name.endswith("-shm")
                and not (directory == self.paths["hermes_home"] and r["path"] == "config.yaml")}

    def checkpoint(self):
        if not self.settled:
            raise RuntimeError("checkpoint before settle")
        header = dict(format=CHECKPOINT_FORMAT, system=self.name, session=self.session, turn=self.turn,
                      events=list(self.events.values()), files=[], dirs=[], removed=[])
        payload = []
        for i, (_, _, fresh) in enumerate(self._fresh):
            current = self._listing(i)
            for path, row in current.items():
                if row == fresh.get(path):
                    continue
                if row["kind"] == "file":
                    header["files"].append(dict(surface=i, path=path, mode=row["mode"], size=row["size"]))
                    payload.append((self._surfaces[i][0] / path).read_bytes())
                elif path not in fresh:
                    header["dirs"].append(dict(surface=i, path=path, mode=row["mode"]))
            header["removed"].extend(dict(surface=i, path=p) for p in fresh if p not in current)
        return canon(header) + b"\n" + b"".join(payload)

    def restore(self, data):
        self._cache = None
        if type(data) is not bytes:
            raise TypeError("checkpoint must be bytes")
        raw, separator, payload = data.partition(b"\n")
        header = json.loads(raw)
        if not separator or header["format"] != CHECKPOINT_FORMAT or header["system"] != self.name:
            raise ValueError("wrong checkpoint")
        integer(header["session"])
        integer(header["turn"])
        for row in header["files"]:
            integer(row["size"])
        if sum(r["size"] for r in header["files"]) != len(payload):
            raise ValueError("wrong payload size")
        for row in header["removed"] + header["dirs"] + header["files"]:
            integer(row["surface"])
            path = Path(row["path"])
            if row["surface"] >= len(self._surfaces) or path.is_absolute() or ".." in path.parts or path == Path("."):
                raise ValueError("invalid checkpoint path")
            base = self._surfaces[row["surface"]][0]
            if not (base / path).resolve().is_relative_to(base):
                raise ValueError("checkpoint escapes surface")
        events = [{"event": event_copy(r["event"]), "session": r["session"],
                   "written": r.get("written", r["event"]["text"])} for r in header["events"]]
        self._wipe()
        for row in sorted(header["removed"], key=lambda r: r["path"], reverse=True):
            path = self._surfaces[row["surface"]][0] / row["path"]
            shutil.rmtree(path) if path.is_dir() else path.unlink(missing_ok=True)
        for row in sorted(header["dirs"], key=lambda r: r["path"]):
            path = self._surfaces[row["surface"]][0] / row["path"]
            path.mkdir(parents=True, exist_ok=True)
            path.chmod(row["mode"])
        for row in header["files"]:
            path = self._surfaces[row["surface"]][0] / row["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload[:row["size"]])
            payload = payload[row["size"]:]
            path.chmod(row["mode"])
        self.events = {r["event"]["event_id"]: r for r in events}
        self.session, self.turn, self.settled = header["session"], header["turn"], True

    def _wipe(self):
        self._stop()
        for (directory, volatile), (fresh, digest, _) in zip(self._surfaces, self._fresh, strict=True):
            wipe_to_fresh(directory, fresh)
            verify_empty(directory, volatile, digest)
        self._blocks, self._cache = (), None
        self._store_generation += 1  # a fresh store may reuse row ids, so keep keys apart

    def reset(self):
        self._wipe()
        self.events, self.turn, self.settled = {}, 0, True

    @property
    def forget_ambiguous(self):
        return sum(r in ("ambiguous", "same_text") for r in self.forget_kept.values())

    def forget(self, selector):
        self._cache = None
        if self._worker is not None:
            self.settled = settle(dict(self.entry, settle={"kind": "hook", "bound_s":
                                  self.entry["settle"]["bound_s"] or 5}), self._drain).settled
            if not self.settled:
                raise HarnessFailed("forget_unsettled")
        shape(selector, {"event_ids": list})
        ids = selector["event_ids"]
        if any(type(i) is not str or not i for i in ids):
            raise ValueError("invalid event ids")
        targets = [r["event"] for r in self.events.values()
                   if r["event"]["event_id"] in ids or r["event"].get("call_id") in ids]
        selected = {e["event_id"] for e in targets}
        written = {i: r["written"] for i, r in self.events.items()}
        kept, seen = {}, set()

        def record(key, reason, text):
            if key not in self.forget_kept:
                self.forget_kept[key] = reason
                self.forget_kept_texts[key] = text

        def owns(hit, row_id):
            if row_id in seen:  # each row is decided once per call, however many searches return it
                return False
            seen.add(row_id)
            exact = {i for i, text in written.items() if text == hit}
            if exact:
                if not exact & selected:
                    return False
                if kept.get(hit, 0) < len(exact - selected):
                    kept[hit] = kept.get(hit, 0) + 1
                    record(("row", self._store_generation, row_id), "ambiguous", hit)
                    return False
                return True
            candidates = {i for i, text in written.items() if text and (hit in text or text in hit)}
            if candidates & selected and candidates - selected:
                record(("row", self._store_generation, row_id), "ambiguous", hit)
            elif not candidates:
                record(("row", self._store_generation, row_id), "unattributed", hit)
            return bool(candidates) and candidates <= selected

        search, args, query, listing, text_key, id_key, delete, fixed, key = FORGET[self.name]
        for text in dict.fromkeys(written[event["event_id"]] for event in targets):
            if not text:
                continue
            if not search and any(value == text and i not in selected for i, value in written.items()):
                record(("text", self._store_generation, sha256(text.encode()).hexdigest()), "same_text", text)
                continue
            # A backend's result page can hide matching rows until deletes free room, so search again
            # while the last pass deleted a row. Rows already decided are skipped, so this ends.
            while True:
                values = [text]
                if search:
                    raw = self._call("tool", name=search, arguments={**args, query: text})["result"]
                    try:
                        result = json.loads(raw)
                        values = [] if result.get("error") else [r[id_key] for r in result.get(listing, []) if isinstance(r.get(text_key), str)
                                  and r[text_key] and owns(r[text_key], r[id_key])]
                    except (ValueError, TypeError, KeyError, AttributeError):
                        values = []
                for value in values:
                    self._call("tool", name=delete, arguments={**fixed, key: value})
                if not search or not values:
                    break
        for event in targets:
            del self.events[event["event_id"]]
        self.settled = False

    def _drain(self):
        reply = self._call("drain", timeout_ms=200)
        return reply["drained"] is True and not set(reply["threads"]) & set(SETTLE_THREADS.get(self.name, ()))

    def settle(self, bound_s):
        integer(bound_s)
        self.settled = self._worker is None or (
            self._drain() if bound_s == 0 or self.entry["settle"]["kind"] == "none" else settle(
                dict(self.entry, settle={"kind": "hook", "bound_s": bound_s}), self._drain).settled)
        return self.settled

    def begin_session(self, index):
        self._cache = None
        if not self.settled:
            raise RuntimeError("session before settle")
        integer(index)
        if index <= self.session:
            raise ValueError("session must increase")
        if self._worker is not None:
            self._call("session_end", messages=[{"role": "user", "content": r["event"]["text"]}
                                               for r in self.events.values() if r["session"] == self.session])
            self._stop()
        with self.egress.forking:
            self.director.schedule = _schedule(self.script, index)
            self.director.start_session(index, self.clock.sim_t_s, self.lock_hash, f"t0-s{index}",
                                        self.paths["root"] / "ledger")
        self.session, self.turn, self._blocks = index, 0, ()

    def stats(self):
        return {"tokens": sum(estimate_tokens(r["event"]["text"]) for r in self.events.values()),
                "latency_ms": self.latency_ms}

    def surfaces(self):
        return [(d, list(v)) for d, v in self._surfaces]

    def records(self):
        path = self.paths["root"] / "ledger/ledger.jsonl"
        return [json.loads(line) for line in path.read_bytes().splitlines()] if path.exists() else []

    def harness_record(self):
        return {**{k: self.harness_pin.get(k, "") for k in ("name", "version", "sha256")},
                "commit": self.commit or "", "entrypoint": ENTRYPOINT if self.commit else "test-double",
                "active_memory_providers": list(self.active_memory_providers)}

    def close(self):
        try:
            self._stop()
        finally:
            shutdown(self.server)
            self.director.close()
            self.egress.stop()
        return self.egress.summary()


class WriteDelivery:
    """Accumulate counts and field metadata without retaining hosts or event text."""

    def __init__(self):
        self.clipped, self.limits, self.delivered = 0, set(), _fields(None)
        self.forget_kept = dict.fromkeys(("ambiguous", "same_text", "unattributed"), 0)

    def add(self, hosts):
        for host in hosts:
            self.clipped += host.write_clipped
            for reason in getattr(host, "forget_kept", {}).values():
                self.forget_kept[reason] += 1
            limit = host.write_max_length
            if limit is not None:
                self.limits.add(limit)
                self.delivered = host.fields()
            elif not self.limits:
                self.delivered = host.fields()

    def properties(self, tier):
        if len(self.limits) > 1:
            raise ValueError("write tool maxLength changed within a run")
        properties = [(f"{tier}.write_clipped", self.clipped),
                      (f"{tier}.fields", canon(self.delivered).decode())]
        if self.limits:
            properties.append((f"{tier}.write_max_length", next(iter(self.limits))))
        properties.append((f"{tier}.forget_kept", canon(self.forget_kept).decode()))
        return properties
