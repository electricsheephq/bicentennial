"""Pinned plug-in trees, isolated surfaces and observed Hermes drain (R13b)."""

import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.gitenv import git_env
from bicentennial.harness.hermes.adapter import HarnessFailed, PinMismatch
from bicentennial.harness.hermes.config import (
    _PASSED,
    _PLUGIN,
    _PROXIES,
    PLACEHOLDER_KEY,
    hermes_config,
    worker_env,
    write_config,
)
from bicentennial.sandbox.spansearch import span_search
from bicentennial.sandbox.surfaces import (
    clone_tree,
    install_hash,
    surface_hash,
    verify_empty,
    wipe_to_fresh,
)
from bicentennial.systems.settle import SettleResult, settle

PROVIDERS = {"holographic": "holographic", "mem0-oss": "mem0", "omega": "omega"}
TREES = {"holographic": ("HEAD",), "mem0-oss": ("HEAD", "integrations/hermes-plugin-mem0"),
         "omega": ("HEAD", "adapters/hermes-plugin-omega")}
ENGINES = {}  # System -> context.engine id.
PLUGIN_DIRS = {}  # System -> install directory when it differs from the slot id.
ENABLED = frozenset()  # Systems using Hermes's general plug-in manager.
WORKER_ENV = {"omega": {"OMEGA_ONNX_MODEL_DIR": "{model_cache}/bge-small-en-v1.5-onnx",
    "OMEGA_ONNX_THREADS": "1", "OMEGA_QUERY_EXPANSION": "0", "OMEGA_CROSS_ENCODER": "0",
    "OMEGA_RERANKER_AUTODOWNLOAD": "0", "ORT_DISABLE_TELEMETRY": "1"}}
# #266: known default telemetry requires the documented worker switch.
TELEMETRY_SWITCHES = {"onnxruntime": ("ORT_DISABLE_TELEMETRY", "1")}
# Benchmark-owned hash locks, covered by benchmark_commit.
DEPENDENCIES = {"holographic": "systems/locks/holographic.txt", "mem0-oss": "systems/locks/mem0-oss.txt",
                "omega": "systems/locks/omega.txt"}
FILE_TIME_SITES = {
    "hermes": (
        "apps/desktop/electron/desktop-installation.ts:reclaimDeadRepairLock",
        "apps/desktop/electron/desktop-plugin-install.ts:installDesktopPluginFromGit",
        "apps/desktop/electron/desktop-plugins-root.ts:materializeDesktopHalf",
        "apps/desktop/electron/main.ts:readDesktopConnectionConfig",
        "apps/desktop/electron/main.ts:readDesktopConnectionsRegistry",
        "apps/desktop/electron/main.ts:watchPreviewFile",
        "apps/desktop/electron/main.ts:writeDesktopConnectionConfig",
        "apps/desktop/electron/main.ts:writeDesktopConnectionsRegistry",
        "apps/desktop/electron/managed-ssh-update.ts:receipt",
        "apps/desktop/electron/profile-migration.ts:scoreStateDb",
        "apps/desktop/electron/remote-lifecycle.ts:spawnRemoteDashboard",
        "apps/desktop/electron/update-marker-gate.ts:markerHoldId",
        "apps/desktop/electron/update-marker.ts:inspectUpdateMarker",
        "apps/desktop/electron/updater-process.ts:stagedFileMtimeMs",
        "ui-tui/src/lib/memory.ts:pruneHeapdumps",
        "agent/curator.py:_claim_run",
        "agent/learning_graph.py:_memory_cards",
        "agent/learning_graph.py:build_skill_nodes",
        "agent/model_metadata.py:_model_metadata_disk_cache_age_seconds",
        "agent/models_dev.py:stat",
        "agent/shell_hooks.py:script_mtime_iso",
        "agent/skill_bundles.py:_max_mtime",
        "agent/turn_explainers.py:_file_stat_signature",
        "cron/jobs.py:_jobs_file_stamp",
        "cron/scheduler_prompt.py:_inject_context_from",
        "cron/store_health.py:probe_report",
        "gateway/browser_control_artifacts.py:prune_expired",
        "gateway/kanban_watchers_dispatcher.py:board_db_fingerprint",
        "gateway/platforms/base.py:_cleanup_cache_dir",
        "gateway/platforms/base.py:_file_is_recently_produced",
        "gateway/platforms/webhook.py:_reload_dynamic_routes",
        "gateway/run_delivery_queue_watch.py:_stamp",
        "gateway/scale_to_zero.py:dashboard_client_last_seen",
        "gateway/status.py:_file_cache_signature",
        "hermes_cli/_early_recovery.py:_claim_owner_alive",
        "hermes_cli/_early_recovery.py:_lock_identity",
        "hermes_cli/_early_recovery_zip.py:zip_entry_identity",
        "hermes_cli/_launchers.py:_publish_conveniences",
        "hermes_cli/_subprocess_compat.py:_safe_directory_cache_key",
        "hermes_cli/auth.py:_auth_file_cache_key",
        "hermes_cli/auth_nous.py:_quarantine_forensics",
        "hermes_cli/banner.py:_inputs",
        "hermes_cli/boot_bootstrap.py:_is_stale",
        "hermes_cli/curator.py:_archived_ts",
        "hermes_cli/doctor_platform.py:_desktop_app_bundle",
        "hermes_cli/foreign_sessions.py:_list_sessions",
        "hermes_cli/foreign_sessions.py:_walk",
        "hermes_cli/foreign_sessions_browser.py:_candidates",
        "hermes_cli/free_tier_bootstrap.py:_config_stamp",
        "hermes_cli/gateway.py:probe_gateway_loop_liveness",
        "hermes_cli/git_pack_tidy.py:_erase_redundant_packs",
        "hermes_cli/git_pack_tidy.py:_pinned",
        "hermes_cli/git_pack_tidy.py:_sweep_remnants",
        "hermes_cli/gitlock.py:_killed_update_owns",
        "hermes_cli/gitlock.py:_sweep_stale",
        "hermes_cli/kanban_db.py:gc_worker_logs",
        "hermes_cli/kanban_db_connect.py:_mtime",
        "hermes_cli/local_runtime/recovery.py:legacy_recorded_process",
        "hermes_cli/logs.py:list_logs",
        "hermes_cli/main.py:_termux_bundled_skills_fingerprint",
        "hermes_cli/main_desktop.py:_desktop_packaged_executable_in",
        "hermes_cli/memory_provider_migration.py:_failed_recently",
        "hermes_cli/model_catalog.py:_read_disk_cache",
        "hermes_cli/models.py:_mtime_part",
        "hermes_cli/observability/shared_metrics_install_run.py:_mark_recorded",
        "hermes_cli/observability/shared_metrics_update.py:_claim_update_id",
        "hermes_cli/plugin_catalog.py:_catalog_worktree_mtime",
        "hermes_cli/plugin_catalog.py:_stale_live_cache",
        "hermes_cli/plugin_catalog.py:fetch_live_catalog",
        "hermes_cli/plugin_host_profiles.py:_fingerprint",
        "hermes_cli/plugins_cadence.py:check_due",
        "hermes_cli/profiles.py:_profile_file_signature",
        "hermes_cli/profiles.py:_skills_dir_signature",
        "hermes_cli/runtime_state.py:collect_generations",
        "hermes_cli/session_recovery.py:_source_fingerprint",
        "hermes_cli/terminal_breadcrumbs.py:_prune_stale",
        "hermes_cli/tools_config_cua.py:_cua_driver_contract_status",
        "hermes_cli/update_cmd_zip.py:_copy_file_exclusive",
        "hermes_cli/update_lock.py:_read_marker",
        "hermes_cli/update_lock.py:_tmp_writer_gone",
        "hermes_cli/update_receipt.py:_prune_old_receipts",
        "hermes_cli/update_receipt.py:read_latest_receipt",
        "hermes_cli/update_receipt.py:read_receipt_for_action",
        "hermes_cli/update_receipt.py:reconcile_interrupted_runs",
        "hermes_cli/venv_sync.py:_tree_matches_completed_stamp",
        "hermes_cli/venv_sync.py:completion_retry_state",
        "hermes_cli/web_routers/cron.py:_list_cron_output_runs",
        "hermes_cli/web_routers/profiles.py:_stat_fingerprint",
        "hermes_cli/web_server_files.py:_managed_file_entry",
        "hermes_cli/worktree_gc.py:audit_worktrees",
        "hermes_cli/worktree_ops.py:_claim_repack_slot",
        "hermes_cli/worktree_ops.py:_fetch_head_age",
        "hermes_cli/worktree_ops.py:_prune_candidates",
        "hermes_constants.py:_prune_scratch_dir_once",
        "hermes_constants_scratch.py:subtree_touched_since",
        "mcp_serve.py:_read_state_db_mtime",
        "plugins/platforms/feishu/feishu_comment_rules.py:load",
        "plugins/platforms/photon/sidecar_paths.py:_lock_newer_than_install",
        "pm/download_state.py:collect_partials",
        "pm/environments.py:activation_input_mtimes",
        "pm/packages.py:_uv_lock_digest",
        "providers/__init__.py:stamp",
        "tools/approval_floors.py:_save_blocked_payload",
        "tools/bot_desktop/runtime.py:idle_seconds",
        "tools/bot_relay.py:_expire_if_stale",
        "tools/bot_relay.py:_queued_at",
        "tools/bot_relay.py:_reoffer_unanswered",
        "tools/bot_relay.py:_target_liveness",
        "tools/bot_relay.py:unlink_files_older_than",
        "tools/browser_tool_lifecycle.py:_socket_dir_idle_seconds",
        "tools/browser_tool_lifecycle.py:_unlink_older_than",
        "tools/browser_use_cli.py:_find_screenshot",
        "tools/browser_use_cli.py:default_downgrade_notice",
        "tools/checkpoint_maintenance.py:_prune_checkpoints",
        "tools/checkpoint_maintenance.py:store_status",
        "tools/code_kernel.py:_sweep_stale_staging_dirs",
        "tools/computer_use/tool.py:_cache_file",
        "tools/credential_files.py:iter_cache_files",
        "tools/delegation_live_log.py:prune_stale_live_dirs",
        "tools/environments/base.py:_file_mtime_key",
        "tools/environments/base_output.py:_new_output_collector",
        "tools/environments/file_sync.py:_cleanup_stale_sync_back_temp",
        "tools/environments/local.py:cleanup_terminal_temp_cache",
        "tools/file_operations.py:_read_file_native",
        "tools/file_state.py:_mtime_or_none",
        "tools/file_tools.py:_record_successful_read",
        "tools/file_tools_read_tracking.py:_file_metadata",
        "tools/file_tools_read_tracking.py:_file_version",
        "tools/file_tools_read_tracking.py:_read_mtime_drifted",
        "tools/file_tools_read_tracking.py:_update_read_timestamp",
        "tools/mcp_oauth.py:_rebase_expires_in",
        "tools/mcp_oauth.py:credential_stamp",
        "tools/mcp_oauth_manager.py:evict",
        "tools/process_registry_results.py:_result_paths",
        "tools/registry.py:discover_builtin_tools",
        "tools/skill_ledger.py:_gc_blobs_locked",
        "tools/skills_hub.py:_read_json_if_fresh",
        "tools/skills_tool.py:_skills_scan_signature",
        "tools/skills_tool_dedup.py:_check_skill_view_dedup",
        "tools/skills_tool_dedup.py:_skill_view_fingerprint",
        "tools/tool_result_storage.py:cleanup_spillover_cache",
        "tools/transcription_whisper_cpp.py:_file_signature",
        "tools/voice_mode.py:cleanup_temp_recordings",
        "tui_gateway/change_watcher.py:_pairing_sig",
        "tui_gateway/change_watcher.py:_projects_sig",
        "tui_gateway/change_watcher.py:_session_db_content_sig",
        "tui_gateway/change_watcher.py:_skin_sig",
        "tui_gateway/change_watcher.py:_watcher_mtime_ns",
        "tui_gateway/methods_config.py:_cfg_get_mtime",
        "tui_gateway/methods_display_watch.py:_mtime",
        "tui_gateway/methods_display_watch.py:_poll_lease_files",
        "tui_gateway/methods_session.py:_legacy_spawn_tree_entry",
        "tui_gateway/profile_roster_cache.py:_file_parts",
        "tui_gateway/server.py:_pet_gen_sweep",
        "tui_gateway/server.py:_pet_sheet_revision",
        "tui_gateway/server.py:_pet_sprite_payload",
        "utils.py:file_signature",
    ),
    "holographic": (),
    "mem0-oss": (),
    "omega": ("omega/sqlite_store/_base.py:_auto_backup_if_stale", "omega/hooks/session_start.py:run",
              "omega/milestones.py:list_milestones", "omega/cli.py:cmd_backup",
              "omega/bridge.py:_auto_backup_before_consolidate"),
}
MARKER = ".bicentennial-sandbox"
MEM0_THREADS = ("mem0-prefetch", "mem0-sync")
OMEGA_THREADS = ("auto-relate", "omega-deferred-init")


def is_plugin(name):
    return name in PROVIDERS or name in ENGINES


def plugin_dir(name):
    return PLUGIN_DIRS.get(name, PROVIDERS.get(name, ENGINES.get(name)))


def validate_maps():
    for value in (*PROVIDERS.values(), *ENGINES.values(), *PLUGIN_DIRS.values()):
        if not isinstance(value, str) or not _PLUGIN.fullmatch(value):
            raise ValueError("invalid plug-in id or directory")
    if "compressor" in ENGINES.values() or (PROVIDERS.keys() | ENGINES.keys()) - TREES.keys():
        raise ValueError("invalid engine or missing tree recipe")
    for name in WORKER_ENV:
        resolve_worker_env(name)


def resolve_worker_env(name, model_cache=None):
    extra = WORKER_ENV.get(name, {})
    reserved = set(worker_env(dict.fromkeys(("hermes_home", "home", "tmp"), Path(".")), 1, ".", None))
    for key, value in extra.items():
        if (not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in reserved | set(_PASSED) | set(_PROXIES)
                or key.startswith(("BICENTENNIAL_", "HERMES_", "PYTHON", "LD_", "DYLD_"))):
            raise ValueError("reserved worker environment name")
        if not isinstance(value, str):
            raise ValueError("worker environment value must be a string")
        if value == "{model_cache}" or value.startswith("{model_cache}/"):
            # One relative path inside the cache: no list separators, so no second path can follow.
            suffix = value[len("{model_cache}/"):]
            if suffix and (not re.fullmatch(r"[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*", suffix)
                           or ".." in suffix.split("/")):
                raise ValueError("invalid model cache path")
        elif not re.fullmatch(r"[A-Za-z0-9._,=+-]*", value):  # a plain value never names a path
            raise ValueError("invalid worker environment value")
    return {k: v.replace("{model_cache}", str(model_cache)) if model_cache is not None else v
            for k, v in extra.items()}


def cache_digest(directory, refuse):
    try:
        rows = tree_listing(directory, [])
        if any(r["kind"] == "symlink" for r in rows):
            raise ValueError("symlink in model cache")
        return sha256(b"".join(f"{r['path']}\0{r['size']}\0{r['sha256']}\n".encode()
                              for r in rows if r["kind"] == "file")).hexdigest()
    except (OSError, ValueError):
        raise refuse("model_cache_invalid") from None


def prepare_cache(name, directory, refuse):
    extra = resolve_worker_env(name)
    needed = any("{model_cache}" in v for v in extra.values())
    if needed != (directory is not None):
        raise refuse("missing_input")
    if directory is None:
        return None, None
    resolved = Path(directory).resolve()
    # Any separator (":", ";", whitespace) would let a path-list variable read outside the cache.
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", str(resolved)):
        raise refuse("model_cache_invalid")
    digest = cache_digest(directory, refuse)
    return resolved, digest


def normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_dependencies(repo):
    for name, value in DEPENDENCIES.items():
        path = PurePosixPath(value)
        if (not is_plugin(name) or path.is_absolute() or ".." in path.parts or "\\" in value
                or path.parts[:2] != ("systems", "locks") or not (repo / path).is_file()):
            raise ValueError("plugin_deps_lock_invalid")


def parse_dependencies(data):
    """Read the restricted, hash-required subset of a universal requirements lock."""
    requirements, seen, pending = [], set(), ""
    for raw in data.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].rstrip()
        pending += line[:-1] + " " if line.endswith("\\") else line
        if line.endswith("\\"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
            r"(?:\s*;\s*(.+?))?\s+((?:--hash=sha256:[0-9a-fA-F]{64}\s*)+)", pending)
        if not match or "[" in pending:
            raise ValueError("plugin_deps_lock_invalid")
        name, version, marker, _ = match.groups()
        key = normalise(name), marker
        if key in seen:
            raise ValueError("plugin_deps_lock_invalid")
        seen.add(key)
        requirements.append([key[0], version, marker])
        pending = ""
    if pending or not requirements:
        raise ValueError("plugin_deps_lock_invalid")
    return requirements


WORKER_DISTS = r"""
import importlib.metadata as metadata
import json, re, sys
normalise = lambda name: re.sub(r"[-_.]+", "-", name).lower()
requirements = json.load(sys.stdin)
applicable, invalid = {}, False
if requirements:
    from packaging.markers import InvalidMarker, Marker, UndefinedComparison, UndefinedEnvironmentName
for name, version, marker in requirements:
    try:
        applies = marker is None or Marker(marker).evaluate()
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        invalid = True
        continue
    if applies:
        if name in applicable and applicable[name] != version:
            invalid = True
        applicable[name] = version
installed = {}
for name in applicable:
    try:
        installed[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        installed[name] = None
dists = sorted({(normalise(d.metadata['Name']), d.version) for d in metadata.distributions()})
print(json.dumps(dict(applicable=applicable, installed=installed, dists=dists, invalid=invalid)))
"""


def worker_properties(system, checkout, repo, tier, refused, worker_argv=None):
    """Inspect only the isolated worker; injected workers have no disclosures."""
    if worker_argv is not None:
        return ()
    data, requirements = None, []
    if system in DEPENDENCIES:
        try:
            validate_dependencies(repo)
            data = (repo / DEPENDENCIES[system]).read_bytes()
            requirements = parse_dependencies(data)
        except (OSError, ValueError):
            raise refused("plugin_deps_lock_invalid") from None
    try:
        checked = subprocess.run([str(Path(checkout).resolve() / ".venv/bin/python"), "-I", "-c",
            WORKER_DISTS], input=json.dumps(requirements), capture_output=True, text=True, env={}, timeout=60)
        if checked.returncode:
            raise ValueError()
        result = json.loads(checked.stdout)
        if result.get("invalid") is True:
            raise refused("plugin_deps_lock_invalid")
        applicable, installed, dists = (result[k] for k in ("applicable", "installed", "dists"))
        if (not isinstance(applicable, dict) or not isinstance(installed, dict)
                or set(applicable) != set(installed) or not isinstance(dists, list)
                or any([name, version] not in [[n, v] for n, v, _ in requirements]
                       for name, version in applicable.items())
                or any(v is not None and not isinstance(v, str) for v in installed.values())
                or any(not isinstance(row, list) or len(row) != 2 or
                       any(not isinstance(v, str) or not v for v in row) for row in dists)):
            raise ValueError()
        dists = sorted({(normalise(n), v) for n, v in dists})
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError):
        raise refused("plugin_deps_check_failed") from None
    mismatches = sorted(n for n, v in applicable.items() if installed[n] != v)
    if mismatches:
        for name in mismatches:
            print(f"{name} locked={applicable[name]} installed={installed[name] or 'none'}", file=sys.stderr)
        raise refused("plugin_deps_missing:" + mismatches[0])
    encoded = canon(dists)
    props = [(tier + ".worker_dists", encoded.decode()),
             (tier + ".worker_dists_sha256", f"sha256:{sha256(encoded).hexdigest()} n={len(dists)}")]
    if data is not None:
        props.append((tier + ".plugin_deps", f"sha256:{sha256(data).hexdigest()} n={len(applicable)}"))
    sites = FILE_TIME_SITES.get("hermes", ()) + FILE_TIME_SITES.get(system, ())
    if sites:
        props.append((tier + ".file_time_sites", canon(sites).decode()))
    return tuple(props)


class PluginCell:
    def __init__(self, entry, adapter):
        validate_maps()
        if not is_plugin(entry["name"]) or entry["harness"] != "hermes":
            raise ValueError("unsupported Hermes plug-in")
        self.entry, self.adapter, self.surfaces = entry, adapter, []
        paths, user = adapter.paths, Path.home().resolve()
        home, root = paths["home"].resolve(), paths["root"].resolve()
        if home.is_relative_to(user) and not home.is_relative_to(root):
            raise ValueError("HOME is not isolated inside the run root")
        roots = {"HERMES_HOME": paths["hermes_home"], "SANDBOX_HOME": paths["home"]}
        for surface in entry["surfaces"]:
            if surface["root"] not in roots:
                raise ValueError("unsupported surface root")
            base = roots[surface["root"]].resolve()
            directory = (base / surface["relative"]).resolve()
            if not directory.is_relative_to(base):
                raise ValueError("surface escapes its root")
            self.surfaces.append((surface, directory))
        self.audit_roots = [paths[k] for k in ("home", "hermes_home", "workspace", "tmp")]

    def install(self, source, *, alias, context=True) -> str:
        git = ["git", "-C", str(source)]
        env = git_env()
        recipe = TREES[self.entry["name"]]
        digest = sha256()
        with tempfile.TemporaryFile() as archive:
            with subprocess.Popen([*git, "archive", "--format=tar", *recipe],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env) as proc:
                for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
                    digest.update(chunk)
                    archive.write(chunk)
            status = subprocess.run([*git, "status", "--porcelain", "--untracked-files=no"],
                                    capture_output=True, env=env)
            if proc.returncode or digest.hexdigest() != self.entry["artifact"]["sha256"]:
                raise PinMismatch("plug-in archive differs from the pin")
            if status.returncode or status.stdout.strip():
                raise PinMismatch("plug-in checkout has tracked changes")
            home = self.adapter.paths["hermes_home"]
            target = home / "plugins" / plugin_dir(self.entry["name"])
            if target.exists():
                raise ValueError("plug-in directory exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            archive.seek(0)
            with tempfile.TemporaryDirectory(dir=target.parent) as unpacked:
                with tarfile.open(fileobj=archive) as tree:
                    tree.extractall(unpacked, filter="data")
                (Path(unpacked) / (recipe[1] if len(recipe) > 1 else ".")).rename(target)
        port = int(self.adapter.director.run_values["director_port"])
        name = self.entry["name"]
        write_config(home, hermes_config(port, alias, plugin=PROVIDERS.get(name),
            context_engine=ENGINES.get(name) if context else None,
            plugins_enabled=(plugin_dir(name),) if name in ENABLED else ()))
        if self.entry["name"] == "mem0-oss":
            base = f"http://127.0.0.1:{port}/mem0/v1"
            llm = {"model": "bicentennial-extraction", "api_key": PLACEHOLDER_KEY, "openai_base_url": base,
                   "is_reasoning_model": True}
            embed = {"model": "bicentennial-embeddings", "api_key": PLACEHOLDER_KEY, "openai_base_url": base,
                     "embedding_dims": 1536}
            cfg = {"mode": "oss", "user_id": "hermes-user", "agent_id": "hermes", "rerank": False,
                   "oss": {"llm": {"provider": "openai", "config": llm},
                           "embedder": {"provider": "openai", "config": embed},
                           "vector_store": {"provider": "qdrant", "config": {
                               "path": "~/.mem0/qdrant", "collection_name": "mem0"}}}}
            pending = home / ".mem0.json.pending"
            pending.write_bytes(canon(cfg) + b"\n")
            os.replace(pending, home / "mem0.json")
            (home / ".env").write_bytes(b"MEM0_TELEMETRY=false\n")
        self.snapshots = []
        for i, (surface, directory) in enumerate(self.surfaces):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / MARKER).write_bytes(b"")
            snapshot = self.adapter.paths["root"] / "fresh" / str(i)
            snapshot.parent.mkdir(exist_ok=True)
            clone_tree(directory, snapshot)
            self.snapshots.append((snapshot, surface_hash(directory, surface["volatile_paths"])))
        hashes = [{"relative": s["relative"], "root": s["root"],
                   "tree_hash": install_hash(d, s["volatile_paths"], port)} for s, d in self.surfaces]
        self.fresh_install_hash = hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()
        self.baseline = self._listing()
        return self.surface_hash()

    def _idle(self):
        worker = getattr(self.adapter, "_worker", None)
        if worker is not None and worker.proc.poll() is None:
            raise ValueError("worker must exit before accessing surfaces")

    def checkpoint(self):
        self._idle()
        checkpoint_sqlite(d for _, d in self.surfaces)

    def surface_hash(self) -> str:
        self.checkpoint()
        hashes = [{"relative": s["relative"], "root": s["root"],
                   "tree_hash": surface_hash(d, s["volatile_paths"])} for s, d in self.surfaces]
        return hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()

    def wipe(self):
        self._idle()
        for (surface, directory), (snapshot, digest) in zip(self.surfaces, self.snapshots, strict=True):
            wipe_to_fresh(directory, snapshot)
            verify_empty(directory, surface["volatile_paths"], digest)
        return True  # R12 writes the current route's config after this hook

    def _listing(self):
        return {f"{root.name}/{row['path']}": row for root in self.audit_roots for row in tree_listing(root, [])
                if not any((root / row["path"]).is_relative_to(d) for _, d in self.surfaces)}

    def audit(self) -> list[str]:
        current = self._listing()
        return sorted(p for p in current.keys() | self.baseline.keys() if current.get(p) != self.baseline.get(p))

    def store_contains(self, needle: bytes) -> list[str]:
        self.checkpoint()
        return sorted(f"{s['root']}/{s['relative']}/{p}" for s, d in self.surfaces
                      for p in span_search(d, [needle])[needle])

    def settle(self):
        self._idle()
        from bicentennial.harness.hermes.plugin_host import SETTLE_THREADS
        kind = self.entry["settle"]["kind"]
        threads = getattr(self.adapter, "end_threads", None)
        if (kind == "hook" and isinstance(threads, tuple)
                and any(t in SETTLE_THREADS[self.entry["name"]] for t in threads)):
            return SettleResult(kind, False, 0, "cut_at_exit", 0)
        def observed():
            threads = getattr(self.adapter, "end_threads", None)
            return (isinstance(threads, tuple) and not any(t in SETTLE_THREADS[self.entry["name"]] for t in threads)
                    and self.adapter.director.control()["inflight"] == 0)
        return settle(self.entry, observed if kind == "hook" else None)


def checkpoint_sqlite(directories):
    """Truncate SQLite WALs before hashing closed surfaces."""
    for directory in directories:
        for path in sorted(directory.rglob("*")):
            try:
                if not stat.S_ISREG(path.lstat().st_mode) or not path.with_name(path.name + "-wal").exists():
                    continue
            except FileNotFoundError:  # a WAL that an earlier checkpoint in this walk removed
                continue
            with path.open("rb") as stream:
                sqlite = stream.read(16) == b"SQLite format 3\x00"
            if sqlite:
                con = sqlite3.connect(path)
                try:
                    busy = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0]
                finally:
                    con.close()
                if busy:  # another connection holds a transaction, so the WAL would reach the hash
                    raise HarnessFailed("checkpoint_busy")
