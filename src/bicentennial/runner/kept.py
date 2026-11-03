"""Capture pre-session inputs and retain failed scored snapshots before attempt cleanup."""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.repro_bundle import check_repro_bundle
from bicentennial.director.routes import segment_of
from bicentennial.genres.g1_software.repo import workspace_hash
from bicentennial.harness.hermes.config import worker_env
from bicentennial.sandbox.surfaces import clone_tree, install_hash

# Budget for 16 sessions in each of 20 units, allowing 1 GiB per complete snapshot.
KEPT_CAP_BYTES = 16 * 20 * (1 << 30)


@dataclass(frozen=True)
class PreProbe:
    directory: Path
    roots: tuple
    probe_point: int
    fields: dict


def record_pre_probe(directory, *, surfaces, adapter, probe, slot, session, clock, table, faults,
                     environment, attempt_id, lock_hash, attempt, probe_mode, live_probe, contract_hash):
    """Copy the untouched surfaces and workspace, retaining every hashed context record."""
    directory = Path(directory)
    directory.mkdir(parents=True)
    paths = adapter.paths
    port = int(adapter.director.run_values["director_port"])
    route = table.resolve(adapter.entry["name"], probe.index, faults)
    config = dict(entry=adapter.entry, plugin=adapter.plugin, plugin_config=adapter.plugin_config,
                  context_engine=adapter.context_engine, plugins_enabled=adapter.plugins_enabled,
                  memory=adapter.memory, window=adapter.window, scripted=adapter.scripted,
                  toolsets=adapter.toolsets, turn_wait_s=str(adapter.turn_wait_s),
                  probe_mode=probe_mode, live_probe=live_probe, answer_contract_sha256=contract_hash,
                  harness_pin=adapter.harness_pin, checkout=str(adapter.checkout) if adapter.checkout else None)
    inputs = dict(
        canonical_paths={k: str(v) for k, v in paths.items()},
        director_bindings=dict(run_values=adapter.director.run_values,
                               route_table=table.to_obj(), probe_config=config),
        attempt_identity=dict(run=adapter.director.run, life=adapter.director.life,
                              branch=adapter.director.branch, attempt=attempt, attempt_id=attempt_id,
                              lock_hash=lock_hash, cursor=adapter.director.ctx.cursor),
        resolved_route=route,
        replay_segment=dict(segment=segment_of(probe.index, faults), faults=faults.to_obj(),
                            replay_prefix=faults.replay_prefix(probe.index)),
        clock_cadence=dict(sim_t_s=clock.sim_t_s, step_s=clock.step_s, clock_path=str(clock.path),
                           published=json.loads(clock.path.read_bytes())),
        compiled_probe=session,
        workspace_inputs=dict(cwd=str(paths["workspace"]), copy="workspace"),
        environment_inputs=dict(seed=environment,
            worker_env=worker_env(paths, port, clock.path, adapter.checkout, adapter.extra_env),
            worker_argv=adapter.argv, envwire_root=str(adapter.env_server.root) if adapter.env_server else None))
    context = directory / "context"
    context.mkdir()
    references = {}
    for name, value in inputs.items():
        digest = sha256_canon(value)
        (context / f"{digest}.json").write_bytes(canon(value))
        references[name] = digest
    roots, hashes = [], {}
    for n, (surface, source) in enumerate(surfaces):
        target = directory / "surfaces" / str(n)
        target.parent.mkdir(exist_ok=True)
        clone_tree(source, target)
        roots.append(target)
        hashes[f"{surface['root']}/{surface['relative']}"] = install_hash(source, surface["volatile_paths"], port)
    clone_tree(paths["workspace"], directory / "workspace")
    fields = dict(surface_hashes=hashes,
                  workspace_hash=workspace_hash(paths["workspace"]),
                  environment_hash=sha256_canon(environment.get("state", {})),
                  sim_t_s=clock.sim_t_s, probe_session_index=probe.index, probe_slot=slot,
                  route_table_sha256=sha256_canon(table.to_obj()), probe_config_sha256=sha256_canon(config),
                  replay_context=references)
    return PreProbe(directory, tuple(roots), probe.checkpoint, fields)


class KeptRefused(ValueError):
    """A failed item's snapshot cannot be published safely or within the byte budget."""


def _bytes(root):
    return sum(p.lstat().st_size for p in root.rglob("*") if p.is_file() and not p.is_symlink())


def _needle_forms(needles):
    # A credential inside a JSON file is escaped (a quote, a backslash, a newline, or non-ASCII
    # from an ASCII-only writer), so each needle is also scanned in those spellings.
    forms = dict.fromkeys(needles)
    for needle in needles:
        try:
            text = needle.decode()
        except UnicodeDecodeError:
            continue
        for ascii_only in (False, True):
            forms.setdefault(json.dumps(text, ensure_ascii=ascii_only)[1:-1].encode())
    return tuple(forms)


def _credential_hit(root, needles):
    for path in root.rglob("*"):
        if path.is_symlink():
            if any(n in os.fsencode(os.readlink(path)) for n in needles):
                return True
        elif path.is_file():
            with path.open("rb") as stream:
                tail = b""
                while chunk := stream.read(1 << 20):
                    data = tail + chunk
                    if any(n in data for n in needles):
                        return True
                    tail = data[-(max(map(len, needles)) - 1):] if max(map(len, needles)) > 1 else b""
    return False


def keep_failed(run, scores, out, *, pack_hash, pins, canary, excluded=(), credential_needles=()):
    """Move failed scored copies to their contract paths; append all captured hashes to the index.

    Call once per final unit attempt, before cleanup, with the same exclusion set as scoring.
    A scored failure without a pre-session record refuses rather than losing a miss silently, unless the life stopped
    before that item's probe: its row then says it was not reached, and it keeps no copy.
    """
    needles = tuple(n.encode() if isinstance(n, str) else n for n in credential_needles)
    if any(not n for n in needles):
        raise ValueError("credential needle must not be empty")
    needles = _needle_forms(needles)
    scores = list(scores.values()) if isinstance(scores, dict) else list(scores)
    failed = {s["item_id"]: s for s in scores if s["item_id"] not in excluded
              and s["score_milli"] is not None and s["score_milli"] < 1000}
    if run.pre_probe is None:
        raise KeptRefused("pre_probe_missing")
    # A record is written for every item of a probe before the probe runs, so a failed item without one was never
    # probed: the life stopped before its session, and it stays a miss in the scores with no copy to keep. A life
    # that ran to its end probed every item, so there a missing record would lose a miss's copy.
    unreached = failed.keys() - run.pre_probe.keys()
    if unreached and run.stopped is None:
        raise KeptRefused("pre_probe_missing")
    out = Path(out)
    kept = out / "kept"
    index_path = kept / "index.json"
    rows = json.loads(index_path.read_bytes()) if index_path.exists() else []
    pending = []
    for iid in sorted(run.pre_probe.keys() | unreached):
        if iid in unreached:
            rows.append(dict(life=run.life, branch=run.branch, item_id=iid, reached=False, kept=None, bytes=0))
            continue
        record = run.pre_probe[iid]
        row = dict(life=run.life, branch=run.branch, item_id=iid, reached=True, **record.fields, kept=None, bytes=0)
        if iid in failed:
            score = failed[iid]
            relative = f"kept/{run.life}/{run.branch}/{iid}"
            bundle = dict(canary=canary, repro_class="snapshot-probe", repro_version="v0.2",
                identity=dict(life=run.life, branch=run.branch, item_id=iid, probe_point=record.probe_point,
                              failure_class=score["failure_class"], score_milli=score["score_milli"],
                              pack_hash=pack_hash, pins=pins), kept=relative, **record.fields)
            check_repro_bundle(bundle)
            target = out / relative
            if target.exists():
                raise KeptRefused("kept_exists")
            (record.directory / "bundle.json").write_bytes(canon(bundle))
            if needles and _credential_hit(record.directory, needles):
                shutil.rmtree(record.directory)
                raise KeptRefused("credential_scan")
            row.update(kept=relative, bytes=_bytes(record.directory))
            pending.append((record.directory, target))
        rows.append(row)
    # Include existing copies and metadata, not only this unit's snapshots.
    index_bytes = canon(rows)
    if any(n in index_bytes for n in needles):
        for source, _ in pending:
            shutil.rmtree(source)
        raise KeptRefused("credential_scan")
    total = (_bytes(kept) - (index_path.stat().st_size if index_path.exists() else 0)
             if kept.exists() else 0)
    total += sum(_bytes(source) for source, _ in pending) + len(index_bytes)
    if total > KEPT_CAP_BYTES:
        raise KeptRefused("kept_cap")
    moved = []
    try:
        for source, target in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), target)
            moved.append((source, target))
        kept.mkdir(parents=True, exist_ok=True)
        temporary = kept / "index.json.pending"
        temporary.write_bytes(index_bytes)
        temporary.replace(index_path)
    except BaseException:
        for source, target in reversed(moved):
            shutil.move(str(target), source)
        raise
    return rows
