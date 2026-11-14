"""One scripted Hermes life attempt; scoring and reruns belong to the caller."""

import json
import shutil
import stat
from contextlib import ExitStack, closing
from dataclasses import dataclass, field, replace
from pathlib import Path

from bicentennial.audit.effects import hermes as hermes_effects
from bicentennial.audit.readback import (
    audit,
    failures,
    life_ids,
    output,
    route_models,
    run_status,
    turns_from_script,
)
from bicentennial.audit.readback import (
    load as load_ledger,
)
from bicentennial.audit.source_damage import SIDECARS, SourceBaseline
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.director.compiler import answer_contract
from bicentennial.director.compiler.check import expected_probe_env, precondition_holds
from bicentennial.director.compiler.hermes import compile_script, step_call
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.genres.g1_software.diffs import (
    EMPTY_TREE_HASH,
    PATHS,
    end_boundary,
    read_state,
    render,
    start_boundary,
)
from bicentennial.genres.g1_software.repo import materialize, workspace_hash
from bicentennial.genres.g2_assistant.envseed import envseed, probe_envseed
from bicentennial.harness.hermes.adapter import (
    HarnessFailed,
    HermesAdapter,
    PinMismatch,
    _now,
)
from bicentennial.harness.hermes.config import (
    HERMES_TOOLSETS,
    install_directory,
    install_file,
)
from bicentennial.harness.hermes.envwire import END_WAIT_S, EnvWiring
from bicentennial.harness.hermes.plugin_host import GateRefused
from bicentennial.ledger import BlobStore, Guard
from bicentennial.probe.probe_responder import ProbeResponder
from bicentennial.runner.lock import LockMismatch
from bicentennial.runner.probe_live import (
    LiveCredentialStop,
    ProbeLiveLeg,
    ProbeLiveRouter,
    live_probe_code,
)
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.sandbox.surfaces import clone_tree, install_hash, swap_in
from bicentennial.score.qa import parse_envelope
from bicentennial.systems.controls import (
    WAKE_REASONS,
    WIPED_LABEL,
    WipeOnWake,
    no_memory_cell,
)
from bicentennial.systems.hermes_plugin import (
    MARKER,
    PluginCell,
    is_plugin,
    plugin_dir,
)
from bicentennial.systems.recipe import recipe
from bicentennial.systems.registry import REGISTRY, SystemRefused, load
from bicentennial.world.db import open_world
from bicentennial.world.scale import TURN_S, named
from bicentennial.world.schedule import build_schedule
from bicentennial.world.targeted import expected_state

ARMS = ("system", "wiped", "no_memory")
STEP_S = 60
PROBE_INFRA_CODES = ("error_recalltoolmissing", "error_plantoolmissing")

SEGMENTS = (("seg0", "bicentennial-main"), ("seg1", "bicentennial-swap"))
CAUSES = tuple((label, "SYSTEM_FAILURE") for label in (
    "turn_failed", "final_mismatch", "resume_failed", "plugin_inactive", "engine_inactive", "end_failed", "exit_timeout",
    "turn_timeout", "end_timeout", "act_state_collision", "worker_protocol", "invalid_store", "invalid_surface")) + tuple(
    (label, "INFRA_FAILURE") for label in (
        "director_stopped", "director_inflight", "write_failure", "held_kill_missed", "open_failed", "drain_timeout",
        "startup_timeout", "open_timeout", "worker_start", "checkpoint_busy", "admission_deadline"))
TERMINAL_DISCLOSURE = ("T1 toolset includes terminal; scripted turns run only compiled workspace commands; "
                       "a live model could reach the Hermes home")


class SourceDamage(HarnessFailed):
    """A parent-held receipt proves damage to a system source."""


@dataclass(frozen=True)
class LifeRun:
    arm: str
    life: str
    branch: str
    attempt: int
    results: dict = field(default_factory=dict)
    envelopes: dict = field(default_factory=dict)
    transforms: tuple = ()
    classes: dict = field(default_factory=dict)
    stored_roots: dict = field(default_factory=dict)
    retained_roots: dict = field(default_factory=dict)
    act: dict = field(default_factory=dict)
    item_labels: dict = field(default_factory=dict)
    incidental_unknown_400: int = 0
    infra_item_labels: tuple = ()
    source_receipts: list = field(default_factory=list)
    restore_failures: list = field(default_factory=list)
    retention_failures: list = field(default_factory=list)
    superseded_causes: list = field(default_factory=list)
    kill: tuple | None = None
    expected_call_ids: tuple = ()
    post_restart_requests: tuple = ()
    audit: dict = field(default_factory=dict)
    sessions: tuple = ()
    stopped: tuple | None = None
    records: tuple = ()
    run_values: dict = field(default_factory=dict)
    stable_digest: str = ""
    honeypot_hits: int = 0
    egress: dict = field(default_factory=dict)
    hooks: tuple = ()
    harness_record: dict = field(default_factory=dict)
    verified_empty: dict = field(default_factory=dict)
    tokens_by_role: dict = field(default_factory=dict)
    store_growth_bytes: int = 0
    process_ids: tuple = ()
    timings: dict | None = None
    background_records: tuple = ()  # quote-attributed volatile copies, never used by a card
    background_threads: tuple = ()
    _root: Path | None = field(default=None, repr=False)
    pre_probe: dict | None = None  # with keep_pre_probe, a record per item whose probe was reached

    def cleanup(self):
        """Release this attempt after its evidence has been scored."""
        if self._root is not None and self._root.exists():
            shutil.rmtree(self._root)


class PluginWake:
    """Wipe the cell at its canonical paths, which may currently hold clones."""

    label = WIPED_LABEL

    def __init__(self):
        self.cell, self._records = None, []

    def __call__(self, reason):
        wake = bool(self._records)
        if reason not in WAKE_REASONS or (not wake and reason != "session_start"):
            raise ValueError("invalid wake reason")
        if self.cell is None:
            raise ValueError("plug-in cell is not installed")
        if wake:
            self.cell.wipe()
        port = int(self.cell.adapter.director.run_values["director_port"])
        rows = [{"root": s["root"], "relative": s["relative"],
                 "fresh_install_hash": install_hash(snapshot, s["volatile_paths"], port),
                 "post_wipe_hash": install_hash(directory, s["volatile_paths"], port) if wake else None}
                for (s, directory), (snapshot, _) in zip(self.cell.surfaces, self.cell.snapshots, strict=True)]
        self._records.append(dict(call=len(self._records) + 1, reason=reason, wake=wake, surfaces=rows))
        return wake

    def records(self):
        return tuple(json.loads(json.dumps(self._records)))


READER_OS_ERRORS = (FileNotFoundError, IsADirectoryError, NotADirectoryError)
STATE_READ_ERRORS = (ValueError, FileNotFoundError, IsADirectoryError, NotADirectoryError, RecursionError)


def reader_made(error):
    """Whether a read_state failure after a live probe comes from the reader's own edits.

    read_state (genres/g1_software/diffs.py) raises malformed content as a plain ValueError and wraps OSError,
    UnicodeError and TOMLDecodeError in ValueError, keeping the original as __cause__; tomllib raises RecursionError
    on deeply nested arrays. The reader's: malformed content, bad UTF-8 or TOML, deep nesting, a deleted file, a file
    replaced by a directory or a path through a file. Any other OS error (descriptor exhaustion, I/O, permission) is
    the harness's, so it keeps the infrastructure class.
    """
    cause = error if isinstance(error, OSError) else error.__cause__
    return not isinstance(cause, OSError) or isinstance(cause, READER_OS_ERRORS)


def _read_action_state(workspace, scratch, *, absent_before=False):
    """Read each live action file with the pinned parser; omit only reader-made failures."""
    state, unreadable = {}, False
    empty = render({p: {} for p in PATHS.values()})
    # One fixed scratch folder inside the life's fresh root: tempfile's random names are outside this module's
    # firewall (tests/runner/test_life_fake.py). The caller carries provenance across the attempt's sessions.
    root = Path(scratch) / "act-state"
    try:
        root.mkdir()
    except FileExistsError as error:
        if absent_before:
            raise HarnessFailed("act_state_collision") from error
        raise
    try:
        for p, data in empty.items():
            (root / p).parent.mkdir(parents=True, exist_ok=True)
            (root / p).write_bytes(data)
        for p in sorted(empty):
            try:
                raw = (workspace / p).read_bytes()
            except STATE_READ_ERRORS as error:
                if not reader_made(error):
                    raise
                unreadable = True
                continue
            # Scratch writes are harness operations, outside the reader-error boundary.
            (root / p).write_bytes(raw)
            try:
                state[p] = read_state(root)[p]
            except STATE_READ_ERRORS as error:
                if not reader_made(error):
                    raise
                unreadable = True
            (root / p).write_bytes(empty[p])
    finally:
        shutil.rmtree(root)
    return state, unreadable


def _cause(error):
    label = str(error) if isinstance(error, HarnessFailed) else type(error).__name__
    return dict(CAUSES).get(label, "INFRA_FAILURE"), label


def _rows(root):
    path = root / "ledger.jsonl"
    return [json.loads(line) for line in path.read_bytes().split(b"\n")[:-1]] if path.exists() else []


def _surface_bytes(surfaces):
    return sum(p.stat().st_size for _, root in surfaces for p in sorted(root.rglob("*"))
               if not p.is_symlink() and p.is_file())


def _tokens(root, rows):
    store, tokens = BlobStore(root / "blobs", Guard([])), {}
    for row in rows:
        if row.get("type") != "request":
            continue
        response = json.loads(store.get(row["resp"]))
        usage = response.get("usage") or {}
        for frame in response.get("sse", ()):
            usage = frame.get("usage") or frame.get("response", {}).get("usage") or usage
        before = tokens.get(row["role"], (0, 0))
        tokens[row["role"]] = (before[0] + usage.get("input_tokens", usage.get("prompt_tokens", 0)),
                               before[1] + usage.get("output_tokens", usage.get("completion_tokens", 0)))
    return tokens


def _answer_content(value):
    """Reduce every earlier answer envelope to its value and its citation's quote (#355).

    Its field names and numbers are the answer format, not earlier content. NUL joins the two, as context_text joins
    values. The reader cannot parse envelopes itself: the probe package imports no scoring code."""
    if isinstance(value, bytes):
        value = json.loads(value)
    if isinstance(value, str):
        envelope = parse_envelope(value)
        if envelope is None:
            return value
        answer = envelope["value"]
        texts = [] if answer is None else [answer if isinstance(answer, str) else canon(answer).decode()]
        if envelope["citation"] is not None:
            texts.append(envelope["citation"]["quote"])
        return "\x00".join(texts)
    if isinstance(value, dict):
        return {key: _answer_content(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_answer_content(item) for item in value]
    return value


def _earlier(root, session, before=None):
    rows = [r for r in _rows(root) if r.get("role") == "probe_main"
            and (r.get("cursor") or {}).get("session") == session]
    # T1's reader and the live leg name their turn: a turn's row is written only after its reply, so the ledger's
    # highest turn can be the previous one (#352). Without a turn, the bound is inferred.
    highest = before if before is not None else max((r["cursor"]["turn"] for r in rows), default=0)
    store = BlobStore(root / "blobs", Guard([]))
    return tuple(store.get(r[key]) for r in sorted(rows, key=lambda r: r["seq"])
                 if r["cursor"]["turn"] < highest for key in ("req", "resp") if r.get(key))


def _probe_earlier(ledger):
    """The reader's earlier exchanges, which T2-lite's shadow reads too: answers count by their content only."""
    return lambda run_key, session, before=None: tuple(
        _answer_content(blob) for blob in _earlier(ledger, session, before))


def _probe_rows(rows, attempt_id, session=None):
    return [r for r in rows if attempt_id is not None and r.get("attempt_id") == attempt_id
            and (session is None or (r.get("cursor") or {}).get("session") in (None, session))]


def _probe_code(rows, attempt_id, *, session=None, probe_live=False):
    for r in _probe_rows(rows, attempt_id, session):
        if probe_live and (code := live_probe_code(r)):
            return code
        for upstream in r.get("upstream", []):
            if upstream.get("error") in PROBE_INFRA_CODES:
                return upstream["error"]
        if r.get("role") == "unknown" and r.get("status") == 400:
            return "unknown_400"
    return None


def _act_state_absent(root):
    try:
        (root / "act-state").lstat()
    except FileNotFoundError:
        return True
    return False


def _pair_inputs(root, rows, kill, genre):
    if kill is None:
        return (), ()
    cursor = dict(session=kill[0], turn=kill[1])
    store = BlobStore(root / "blobs", Guard([]))
    ids, requests = [], []
    last = max((r["seq"] for r in rows if r.get("cursor") == cursor), default=0)
    for row in sorted(rows, key=lambda r: r["seq"]):
        path = row.get("path", "")
        wire = "chat" if path.endswith("/chat/completions") else (
            "responses" if path.endswith("/responses") else None)
        if genre == "G1" and row.get("cursor") == cursor and row.get("served") == "script_tool_calls":
            # A streamed reply is stored as its chunks; output() reads both stored forms.
            calls, _ = output(json.loads(store.get(row["resp"])), wire or "chat")
            ids.extend(c["id"] for c in calls)
        if last and row["seq"] > last and row.get("type") == "request" and wire is not None:
            requests.append((wire, json.loads(store.get(row["req"]))))
    return tuple(sorted(ids)), tuple(requests)


def _audit(adapter, table, faults, script, items, records, plugin, arm, probe_live=False):
    try:
        rows, blobs, _ = load_ledger(adapter.paths["root"] / "ledger", "kit")
        model_for, mode = route_models(table, adapter.entry["name"], faults)
        report = audit(rows, blobs, turns_from_script(script), "chat", fmt="kit", model_for=model_for,
                       suffix=None, write_tools=tuple(t["tool"] for t in adapter.entry["write_tools"]),
                       id_needles=life_ids({"items": list(items), "records": list(records)}),
                       effects=None if plugin else hermes_effects(adapter.paths["hermes_home"]), probe_live=probe_live)
        codes = failures(report)
        ignored = ("A4.no_effects_hook",) if plugin else ()
        if arm == "wiped":
            calls = (report["A4"] or {}).get("calls")
            unclassified = sum(c["applied"] is None for c in calls) if isinstance(calls, list) else "unknown"
            if unclassified == 0:
                ignored += ("A4.gaps",)
        status = "OK" if not [c for c in codes if c not in ignored] else run_status(report, mode)
        result = dict(status=status, failures=codes, **(
            {"a4": "not audited for plug-in providers at v0.1"} if plugin else {}))
        if arm == "wiped" and "A4.gaps" in codes:
            if unclassified == 0:
                result["a4_gaps"] = "expected: the wiped arm restores the fresh install at every wake"
            else:
                result["a4_unclassified"] = unclassified
        return result
    except (SystemRefused, PinMismatch, LockMismatch, GateRefused):
        raise
    except Exception:
        return {"status": "INFRA_FAILURE", "failures": ["audit_exception"]}


def _routes(name):
    from bicentennial.runner.t1 import _routes as t1_routes

    return t1_routes(name)


def run_life(*, arm, entry, life_dir, branch, items, records, keys, scratch, run, attempt,
             gate, current_lock, voids, harness_pin, hermes=None, plugin_source=None,
             worker_argv=None, visible=None, honeypot_token=None, schedule=None, extra_env=None,
             live=None, live_model=None, turn_wait_s=1.0, probe_mode="ring0", keep_pre_probe=False,
             pre_probe_attribution=False, cases=None, repro=None, stop_after_target=False,
             probe_blocks=None, probe_window=None, source_checks=False) -> LifeRun:
    """Run in script list order, restoring every canonical surface after each probe."""
    if arm not in ARMS or branch not in ("B0", "B1"):
        raise ValueError("invalid arm or branch")
    if repro is not None:
        keep_pre_probe = True
        # A mismatch visible before the run refuses before anything runs (RING0 §14.8 (c)).
        repro.check_entry(entry)
    if stop_after_target and repro is None:
        raise ValueError("stop_after_target requires repro")
    if pre_probe_attribution and not keep_pre_probe:
        raise ValueError("pre_probe_attribution requires keep_pre_probe")
    if probe_blocks is not None and (arm != "no_memory" or live is None):
        # A live control arm (runner/control_arm.py) is the live floor with a pinned control's text in each probe turn.
        raise ValueError("probe blocks need the live no-memory arm")
    if probe_window is not None and probe_blocks is None:
        raise ValueError("probe window requires probe blocks")
    if live is not None and cases is None:
        # The live leg scores act items as the scorer does, from the pack's sealed cases.
        raise ValueError("live probes need the pack's cases")
    if keep_pre_probe and arm == "wiped":
        # The wiped arm's wake hook wipes the probe's store after the copy is taken, so the copy
        # would hold text the probe never had.
        raise ValueError("keep_pre_probe is not supported on the wiped arm")
    if keep_pre_probe:
        from bicentennial.runner.kept import plain_item_id

        # Each item's copy is a directory named by its id, so the id must not leave that directory.
        if not all(plain_item_id(i["item_id"]) for i in items):
            raise ValueError("keep_pre_probe needs item ids that are one plain path component")
    life_dir, scratch = Path(life_dir), Path(scratch)
    life = json.loads((life_dir / "life.json").read_bytes())
    schedule = schedule if schedule is not None else build_schedule(life["seed"], life["life"], named(life["scale"]))
    root = scratch / branch
    root.mkdir(parents=True)
    evidence = LifeRun(arm, life["life"], branch, attempt, _root=root, pre_probe={} if keep_pre_probe else None)
    sessions, transforms, adapter = [], [], None
    workspace_ms = {}
    stopped, hooks, verified = None, (), {}
    initial_bytes = None
    with closing(open_world(life_dir / f"world.{branch}.db", readonly=True)) as db:
        seed, genre = db.execute("SELECT seed, genre FROM meta").fetchone()
        if seed != life["seed"]:
            raise ValueError("world seed mismatch")
        compiled = compile_script(life_dir, branch, schedule, db, items=items, step_s=STEP_S,
                                  answer_contract=answer_contract if live is not None else None, probe_mode=probe_mode)
        script = compiled.script
        if arm == "no_memory":
            script = dict(script, sessions=[s for s in script["sessions"] if s["kind"] == "probe"])
        if probe_blocks is not None:
            from bicentennial.runner.control_arm import with_blocks

            script = with_blocks(script, compiled.probes, probe_blocks)
        faults = FaultLite.load([] if arm == "no_memory" else schedule.fault_lite(), script)
        kill = next(((f["session"], f["turn"]) for f in faults.to_obj() if f["kind"] == "kill"), None)
        entry_r = load(REGISTRY / "hermes-native.toml") if arm == "no_memory" else entry
        reader = load(REGISTRY / "no-memory.toml") if arm == "no_memory" else entry
        table = RouteTable.load(_routes(entry_r["name"]))
        probes = {p.index: p for p in compiled.probes}
        by_id = {i["item_id"]: i for i in items}
        responder = ProbeResponder(ScriptedResponder(entry_r), reader,
            {iid: (p.index, n) for p in compiled.probes for n, iid in enumerate(p.item_ids, 1)},
            {iid: (reader_view(by_id[iid]), keys[iid]) for iid in sorted(by_id)},
            earlier=_probe_earlier(root / "run" / "ledger"),
            step_call=step_call)
        leg = ProbeLiveLeg(live, live_model, responder, answer_contract) if live is not None else None
        results = leg if leg is not None else responder
        if leg is not None:
            evidence.envelopes.update((i["item_id"], None) for i in items if i["stage"] != "act")
        clock = SimClock(root / "clock.json", schedule.sessions[0].turn_t[0] - TURN_S, TURN_S)
        seeds = ({p.index: envseed(db, p.index).seed for p in schedule.sessions} | {
            p.index: probe_envseed(db, p.index, p.checkpoint).seed for p in compiled.probes}) if genre == "G2" else {}
        wiring = EnvWiring(root / "envwire", seeds, clock.path) if genre == "G2" else None
        plugin = arm != "no_memory" and is_plugin(entry)
        hook = (PluginWake() if plugin else WipeOnWake(entry, {"HERMES_HOME": root / "run" / "hermes-home"},
                root / "control")) if arm == "wiped" else None
        hooks = (hook,) if hook is not None else ()
        common = dict(script=script, route_table=table, schedule=faults,
            responder=ProbeLiveRouter(responder, leg) if leg is not None else responder, clock=clock,
            root=root / "run", scratch=scratch, life=life["life"], branch=branch, run=run,
            checkout=hermes, harness_pin=harness_pin, worker_argv=worker_argv,
            toolsets=HERMES_TOOLSETS, env_server=wiring, turn_wait_s=turn_wait_s)
        halted = None
        try:
            adapter = (no_memory_cell(**common, **({} if probe_window is None else {"window": probe_window}))
                if arm == "no_memory" else HermesAdapter(entry,
                plugin=recipe(entry).provider, context_engine=recipe(entry).engine,
                plugins_enabled=(plugin_dir(entry),) if recipe(entry).enabled else (),
                extra_env=extra_env, before_spawn=hook, **common))
            paths = adapter.paths
            roots = {"HERMES_HOME": paths["hermes_home"], "SANDBOX_HOME": paths["home"]}
            surfaces = [(s, roots[s["root"]] / s["relative"]) for s in adapter.entry["surfaces"]]
            pack = paths["home"] / "pack"
            if any(pack.resolve().is_relative_to(p.resolve()) or p.resolve().is_relative_to(pack.resolve())
                   for p in [paths["workspace"], *(p for _, p in surfaces)]):
                raise SystemRefused(["visible_pack_overlaps_surface"])
            for rel, content in sorted((visible or {}).items()):
                target = pack / rel
                if not target.resolve().is_relative_to(pack.resolve()):
                    raise SystemRefused(["visible_path_escape"])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            for surface, directory in surfaces:
                if (surface["root"] == "SANDBOX_HOME" and directory.exists()
                        and any(p.name != MARKER for p in directory.iterdir())):
                    raise SystemRefused(["surface_not_empty"])
            for _, directory in surfaces:
                install_directory(directory)
                if not (directory / MARKER).exists():
                    install_file(directory / MARKER, b"")
            cell = PluginCell(entry, adapter) if plugin else None
            if cell is not None:
                installed = cell.install(plugin_source, alias=table.resolve(entry["name"],
                    script["sessions"][0]["index"], faults)["alias"])
                if hook is not None:
                    hook.cell = cell
                empty = not cell.audit() and cell.surface_hash() == installed
            else:
                empty = all([r["path"] for r in tree_listing(p, s["volatile_paths"])] == [MARKER]
                            for s, p in surfaces)
            listing = [tree_listing(p, s["volatile_paths"]) for s, p in surfaces]
            verified = dict(taken="before configuration", listing_sha256=sha256_canon(listing[0] if len(listing) == 1 else listing))
            if not empty:
                raise HarnessFailed("not_empty")
            initial_bytes = _surface_bytes(surfaces)
            expected = expected_state(genre, schedule)(db)
            unsettled, checkpoints = [], []
            live_cut = False  # the last session ended on a live failure, before its exit was observed

            def settle_checkpoint(checkpoint):
                # Probes run on clones and a failed session's worker is killed, so after a live failure the store is
                # as its last settle left it: the missing exit observation is not the system's own unsettled store.
                if live_cut:
                    return
                if cell is not None and not cell.settle().settled:
                    unsettled.append(checkpoint)
                    evidence.classes.update((iid, ("SYSTEM_FAILURE", "unsettled"))
                        for iid in sorted(by_id) if by_id[iid]["probe_point"] == checkpoint)

            previous_session = None
            # Harness setup is complete. Observation errors must remain infrastructure, as must a baseline entry.
            act_state_baseline = _act_state_absent(root) if leg is not None and genre == "G1" else False
            act_state_created = False
            # Only callers that keep the evidence (runner/units.py) check sources; T1 does not yet.
            source_surfaces = surfaces if arm == "system" and source_checks else []
            baseline = SourceBaseline(source_surfaces, [paths["hermes_home"] / p for p in (
                "config.yaml", "mem0.json", ".mem0.json.pending", ".env")] + [p / MARKER for _, p in surfaces])
            source_receipt = None

            def check_sources(exc_type=None, error=None, traceback=None):
                nonlocal source_receipt
                if exc_type is not None and not isinstance(error, Exception):
                    return
                source_receipt = source_receipt or session_baseline.receipt(getattr(adapter, "after_kill", False))
                if source_receipt is not None:
                    if source_receipt not in evidence.source_receipts:
                        evidence.source_receipts.append(source_receipt)
                        try:
                            path = source_receipt["_path"]
                            kept = root / f"invalid-source-{index}"
                            path.rename(kept)  # preserve the entry itself, without following it
                            source_receipt["_kept"] = kept
                            if source_receipt["rule"] == "not_a_directory":
                                path.mkdir()
                            if source_receipt["rule"] == "sqlite_malformed":
                                # The journal and WAL beside it may hold the damage the check read.
                                for suffix in SIDECARS:
                                    sidecar = path.with_name(path.name + suffix)
                                    try:
                                        if not stat.S_ISREG(sidecar.lstat().st_mode):
                                            continue
                                    except FileNotFoundError:
                                        continue
                                    sidecar.rename(kept.with_name(kept.name + suffix))
                                    source_receipt.setdefault("_sidecars", []).append(suffix)
                        except Exception as restore_error:
                            evidence.restore_failures.append(type(restore_error).__name__)
                    if not isinstance(error, SourceDamage):
                        if error is not None:
                            evidence.superseded_causes.append(_cause(error)[1])
                        raise SourceDamage(source_receipt["label"])

            adapter.check_sources = check_sources
            for session in script["sessions"]:
                index, probe = session["index"], probes.get(session["index"])
                if repro is not None and (probe is None or repro.item_id not in probe.item_ids):
                    adapter.director.skip_session(index)
                    continue
                if leg is not None:
                    leg.check_session(previous_session)
                previous_session = index
                attempt_id, session_baseline, observed = None, baseline, None
                try:
                    lock_hash, attempt_id = gate.start_session(current_lock(), arm, life["life"], branch, index, attempt)
                    if genre == "G1" and (probe is None or probe.checkpoint not in checkpoints):
                        m = _now()
                        shutil.rmtree(paths["workspace"])
                        boundary = end_boundary(schedule, probe.checkpoint) if probe else start_boundary(schedule, index)
                        materialize(db, schedule, branch=branch, boundary=boundary, root=paths["workspace"])
                        if probe and workspace_hash(paths["workspace"]) != expected[probe.checkpoint]["repo_tree_hash"]:
                            raise HarnessFailed("workspace_state")
                        workspace_ms[index] = int((_now() - m) * 1000)
                    if repro is not None:
                        repro.restore(surfaces, paths["workspace"], int(adapter.director.run_values["director_port"]))
                    instant = probe.sim_t_s if probe else schedule.sessions[index - 1].turn_t[0] - TURN_S
                    clock.set_session(instant, step_s=STEP_S if probe else TURN_S)
                    with ExitStack() as stack:
                        clones = []
                        if probe:
                            checkpoints.append(probe.checkpoint)
                            # Settledness was judged at replay end on the real store; probe exits belong to clones.
                            for n, canonical in enumerate([*(p for _, p in surfaces), paths["workspace"]]):
                                clone = root / "probe" / str(index) / str(n)
                                clone.parent.mkdir(parents=True, exist_ok=True)
                                clone_tree(canonical, clone)
                                clones.append(clone)
                            if keep_pre_probe:
                                from bicentennial.runner.kept import record_pre_probe

                                for slot, iid in enumerate(probe.item_ids):
                                    evidence.pre_probe[iid] = record_pre_probe(
                                        root / "pre-probe" / iid, surfaces=surfaces, adapter=adapter,
                                        probe=probe, slot=slot, session=session, clock=clock, table=table,
                                        faults=faults, environment=seeds.get(index, {}), attempt_id=attempt_id,
                                        lock_hash=lock_hash, attempt=attempt, probe_mode=probe_mode,
                                        live_probe=(dict(model=leg.model, wire=live.wire,
                                            effort=getattr(live.upstreams.get(leg.model), "effort", None))
                                            if leg is not None else None),
                                        contract_hash=compiled.answer_contract_sha256)
                            for iid in probe.item_ids:
                                holds = precondition_holds(by_id[iid],
                                    repo_tree_hash=workspace_hash(clones[-1]) if genre == "G1" else EMPTY_TREE_HASH,
                                    env_state_hash=sha256_canon(seeds[index]["state"] if genre == "G2" else {}),
                                    probe_env_state_hash=expected_probe_env(db, genre, index, probe.checkpoint))
                                if (iid, arm) not in voids.records:
                                    voids.record(iid, arm, holds)
                                elif voids.records[iid, arm] != holds:
                                    raise HarnessFailed("void_mismatch")
                                if not holds:
                                    evidence.classes[iid] = ("INFRA_FAILURE", "void")
                                evidence.retained_roots[iid] = (
                                    evidence.pre_probe[iid].roots if pre_probe_attribution else tuple(clones[:-1]))
                            for clone, canonical in zip(clones, [*(p for _, p in surfaces), paths["workspace"]], strict=True):
                                stack.enter_context(swap_in(clone, canonical))
                        if probe:
                            session_baseline = SourceBaseline(source_surfaces, baseline.excluded)
                        stack.push(check_sources)  # runs before any swap restores, including on exceptions
                        before = workspace_hash(paths["workspace"]) if genre == "G1" else EMPTY_TREE_HASH
                        track_state = leg is not None and genre == "G1"
                        absent_before = _act_state_absent(root) if track_state else False
                        observed = absent_before if track_state else None
                        result = adapter.run_session(index, sim_t_s=instant, lock_hash=lock_hash, attempt_id=attempt_id)
                        if track_state:
                            act_state_created = (act_state_baseline and not _act_state_absent(root)
                                                 and (absent_before or act_state_created))
                        observed = None  # up to date before the harness's own act read below
                        live_cut = False
                        sessions.append(result)
                        if not probe:
                            if result.finals_matched != len(session["turns"]):
                                raise HarnessFailed("final_mismatch")
                            if genre == "G1" and workspace_hash(paths["workspace"]) != before:
                                raise HarnessFailed("workspace_changed")
                            if genre == "G2":
                                ends = [r for r in wiring.wait_end(index, END_WAIT_S) if r.get("type") == "boundary" and r.get("kind") == "session_end"]
                                if not ends or ends[-1]["state_hash"] != expected[index]["env_state_hash"]:
                                    raise HarnessFailed("env_state")
                        elif by_id[probe.item_ids[0]]["stage"] == "act":
                            if genre == "G2":  # the probe's server may still be writing its session_end
                                wiring.wait_end(index, END_WAIT_S)
                            if genre == "G1":
                                if leg is None:
                                    state, unreadable = read_state(paths["workspace"]), False
                                else:
                                    state, unreadable = _read_action_state(paths["workspace"], root,
                                                                         absent_before=act_state_created)
                                for iid in probe.item_ids:
                                    evidence.act[iid] = state
                                    if unreadable:
                                        evidence.item_labels[iid] = "unreadable_state"
                            else:
                                for iid in probe.item_ids:
                                    evidence.act[iid] = {"records": wiring.records(index)}
                    if probe:
                        code = _probe_code(adapter.records(), attempt_id, session=index, probe_live=leg is not None)
                        for n, final in result.finals:
                            iid = probe.item_ids[n - 1]
                            if ((leg is not None and by_id[iid]["stage"] != "act") or
                                    (iid in results.results() and results.results()[iid].kind == "qa")):
                                env = evidence.envelopes[iid] = parse_envelope(final)
                                if leg is not None:
                                    leg.final_items.add(iid)
                                if leg is None and env != results.results()[iid].envelope:
                                    transforms.append(iid)
                            if code:
                                evidence.classes[iid] = ("INFRA_FAILURE", code)
                            if probe.checkpoint in unsettled:
                                evidence.classes[iid] = ("SYSTEM_FAILURE", "unsettled")
                        if leg is not None:
                            # A failed shadow read leaves no result, so a later session's failure must not class it.
                            for iid in probe.item_ids:
                                if iid in leg.errors:
                                    evidence.classes.setdefault(iid, ("INFRA_FAILURE", "shadow_error"))
                    else:
                        needed = [r["item_id"] for r in records if r["evidence_session"] == index]
                        if needed:
                            stored = []
                            for n, (_, canonical) in enumerate(surfaces):
                                clone = root / "stored" / str(index) / str(n)
                                clone.parent.mkdir(parents=True, exist_ok=True)
                                clone_tree(canonical, clone)
                                stored.append(clone)
                            evidence.stored_roots.update((iid, tuple(stored)) for iid in needed)
                        if any(p.checkpoint == index for p in compiled.probes):
                            settle_checkpoint(index)
                except (SystemRefused, PinMismatch, LockMismatch, GateRefused, LiveCredentialStop):
                    raise
                except Exception as error:
                    if observed is not None:
                        # The session failed between the observation and the update above; a later session may
                        # still run (a probe code continues), so an entry it made stays the reader's. An
                        # observation fault claims nothing and keeps this session's own failure.
                        try:
                            act_state_created = (act_state_baseline and not _act_state_absent(root)
                                                 and (observed or act_state_created))
                        except OSError:
                            pass
                    cause = ("SYSTEM_FAILURE", source_receipt["label"]) if source_receipt else _cause(error)
                    if source_receipt and not isinstance(error, SourceDamage):
                        evidence.restore_failures.append(_cause(error)[1])
                    proven = cause[1] in ("act_state_collision", "worker_protocol", "invalid_store", "invalid_surface") and cause[0] == "SYSTEM_FAILURE"
                    try:
                        rows = _probe_rows(adapter.records(), attempt_id, index) if probe or proven else []
                    except (OSError, ValueError):
                        if not proven:
                            raise
                        rows = []
                    if proven:
                        evidence = replace(evidence, incidental_unknown_400=evidence.incidental_unknown_400 + sum(
                            r.get("role") == "unknown" and r.get("status") == 400 for r in rows))
                    code = _probe_code(rows, attempt_id, session=index, probe_live=leg is not None) if probe and not proven else None
                    if code:
                        cause = ("INFRA_FAILURE", code)
                    stopped = (*cause, index)
                    for iid in sorted(by_id):
                        if probe and iid in probe.item_ids:
                            if code and probe.checkpoint not in unsettled:
                                evidence.classes[iid] = cause
                            else:
                                evidence.classes.setdefault(iid, cause)
                        elif iid not in results.results() and not (leg is not None and code):
                            evidence.classes.setdefault(iid, cause)
                    if leg is not None and code:
                        live_cut = True
                        # Its unsent turns would hold the cursor, so no later request could match a scripted turn.
                        adapter.director.skip_session(index)
                        if repro is not None and stop_after_target:
                            break
                        continue
                    break
                if repro is not None and stop_after_target:
                    break
            if leg is not None:
                leg.check_session(previous_session)
        except (SystemRefused, PinMismatch, LockMismatch, GateRefused):
            raise
        except LiveCredentialStop as stop:
            halted = stop
            raise
        except Exception as error:
            cause = _cause(error)
            stopped = (*cause, script["sessions"][0]["index"])
            evidence.classes.update((iid, cause) for iid in sorted(by_id))
        finally:
            if adapter is not None:
                egress = adapter.close()
                if halted is not None:
                    # A breach seen before the stop still outranks it (runner/t2lite.py), so the egress goes with it.
                    halted.egress = egress
        if repro is not None:
            # Only the target is a repetition: every other item is not_restored, even after a stop gave it a cause.
            evidence.classes.update((iid, ("INFRA_FAILURE", "not_restored")) for iid in sorted(by_id)
                                    if iid != repro.item_id)
        if adapter is None:
            if leg is not None:
                leg.write_records(root, compiled, items, evidence, (), life_dir, branch, db, cases)
            return replace(evidence, stopped=stopped)
        rows = tuple(adapter.records())
        if leg is not None:
            leg.write_records(root, compiled, items, evidence, rows, life_dir, branch, db, cases)
            transforms.extend(sorted(leg.transforms))
        ids, requests = _pair_inputs(root / "run" / "ledger", rows, kill, genre)
        timings = {"pin_check_ms": adapter.pin_check_ms, "sessions": [{
            "session": s.session, "kind": s.kind, "workspace": workspace_ms.get(s.session),
            **{k: s.timings_ms.get(k, []) for k in (
                "gate", "egress_wait", "spawn", "import", "open", "turn", "drain", "resume")},
            "background_threads": s.timings_ms.get("background_threads", []),
            **{k: s.timings_ms.get(k) for k in ("wall", "shutdown_hook", "close", "finish")},
        } for s in sessions]}
        return replace(evidence, results=dict(sorted(results.results().items())), transforms=tuple(sorted(transforms)),
            classes=dict(sorted(evidence.classes.items())), kill=kill, expected_call_ids=ids,
            post_restart_requests=requests,
            audit=_audit(adapter, table, faults, script, items, records, plugin, arm, probe_live=leg is not None),
            sessions=tuple(sessions), stopped=stopped, records=rows, run_values=dict(adapter.director.run_values),
            stable_digest=adapter.stable_digest(), honeypot_hits=adapter.honeypot_hits(honeypot_token) if honeypot_token else 0,
            egress=egress, timings=timings, background_records=tuple(adapter.background_records()),
            background_threads=tuple(adapter.background_threads),
            hooks=hooks, harness_record=adapter.harness_record(), verified_empty=verified,
            tokens_by_role=_tokens(root / "run" / "ledger", rows), process_ids=tuple(adapter.pids),
            store_growth_bytes=_surface_bytes(surfaces) - initial_bytes if initial_bytes is not None else 0)
